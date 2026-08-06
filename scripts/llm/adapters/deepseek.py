"""DeepSeek provider wrapper for the AIOS Agent Harness.

The adapter follows the provider-neutral ``AgentAdapter`` contract. It is
closed by default: tests may use an explicit offline stub, while real provider
calls require both ``allow_real_call=True`` and ``network_policy="provider_only"``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Mapping

from .base import AdapterOutput, AgentAdapter, AgentRequest, Usage, UsageStatus


BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_PROMPT_VERSION = "aios_deepseek_v1"
DEFAULT_USD_CNY = Decimal(os.environ.get("LLM_USD_CNY", "7.20"))

MODEL_PRICING_USD_PER_1M = {
    "deepseek-v4-flash": {
        "cache_hit_input": Decimal(os.environ.get("DEEPSEEK_V4_FLASH_CACHE_HIT_USD_PER_1M", "0.0028")),
        "cache_miss_input": Decimal(os.environ.get("DEEPSEEK_V4_FLASH_CACHE_MISS_USD_PER_1M", "0.14")),
        "output": Decimal(os.environ.get("DEEPSEEK_V4_FLASH_OUTPUT_USD_PER_1M", "0.28")),
    },
    "deepseek-v4-pro": {
        "cache_hit_input": Decimal(os.environ.get("DEEPSEEK_V4_PRO_CACHE_HIT_USD_PER_1M", "0.003625")),
        "cache_miss_input": Decimal(os.environ.get("DEEPSEEK_V4_PRO_CACHE_MISS_USD_PER_1M", "0.435")),
        "output": Decimal(os.environ.get("DEEPSEEK_V4_PRO_OUTPUT_USD_PER_1M", "0.87")),
    },
}

CompletionFn = Callable[[Mapping[str, Any], int], Mapping[str, Any]]


class DeepSeekAdapter(AgentAdapter):
    provider = "deepseek"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = BASE_URL,
        api_key: str | None = None,
        completion: CompletionFn | None = None,
        allow_real_call: bool = False,
        max_tokens: int = 512,
        thinking: str = "disabled",
        reasoning_effort: str = "high",
    ) -> None:
        if model not in MODEL_PRICING_USD_PER_1M:
            raise ValueError("unsupported DeepSeek model")
        if thinking not in {"enabled", "disabled"}:
            raise ValueError("thinking must be enabled or disabled")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._completion = completion
        self._allow_real_call = allow_real_call
        self._max_tokens = max_tokens
        self._thinking = thinking
        self._reasoning_effort = reasoning_effort

    def execute(self, request: AgentRequest) -> AdapterOutput:
        payload = self._payload(request)
        timeout = max(1, int(request.timeout_seconds))

        if self._allow_real_call and request.network_policy != "provider_only":
            raise PermissionError("real DeepSeek calls require network_policy=provider_only")

        if self._completion is not None:
            if not self._allow_real_call and not getattr(self._completion, "offline_stub", False):
                raise PermissionError("DeepSeek completion injection must be an explicit offline stub")
            response = self._completion(payload, timeout)
        else:
            if not self._allow_real_call:
                raise PermissionError("real DeepSeek calls require allow_real_call=True")
            response = self._post_chat_completion(self._read_api_key(), payload, timeout)

        if not isinstance(response, Mapping):
            raise TypeError("DeepSeek response must be a mapping")

        text = extract_text(response)
        usage = usage_from_response(response, model=self.model, require_reported=self._allow_real_call)
        return AdapterOutput(
            output={
                "text": text,
                "finish_reason": _finish_reason(response),
                "provider_mode": "real" if self._allow_real_call else "offline_stub",
            },
            usage=usage,
            evidence_refs=("provider:deepseek",),
        )

    def _payload(self, request: AgentRequest) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": messages_from_payload(request.input_payload),
            "max_tokens": self._max_tokens,
            "thinking": {"type": self._thinking},
            "reasoning_effort": self._reasoning_effort,
            "stream": False,
        }

    def _read_api_key(self) -> str:
        api_key = self._api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY is not set. Put it in the server/local environment only; "
                "never paste it into code, commits, frontend, or chat."
            )
        return api_key

    def _post_chat_completion(
        self,
        api_key: str,
        payload: Mapping[str, Any],
        timeout_seconds: int,
    ) -> Mapping[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"DeepSeek API request failed with HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("DeepSeek API request failed") from exc


def messages_from_payload(input_payload: Mapping[str, Any]) -> list[dict[str, str]]:
    raw_messages = input_payload.get("messages")
    if isinstance(raw_messages, list) and raw_messages:
        messages: list[dict[str, str]] = []
        for item in raw_messages:
            if not isinstance(item, Mapping):
                raise TypeError("messages entries must be mappings")
            role = item.get("role")
            content = item.get("content")
            if role not in {"system", "user", "assistant"}:
                raise ValueError("messages role must be system, user, or assistant")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("messages content must be a non-empty string")
            messages.append({"role": role, "content": content})
        return messages

    prompt = input_payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("input_payload must include messages or a non-empty prompt")

    system = input_payload.get("system")
    messages = []
    if isinstance(system, str) and system.strip():
        messages.append({"role": "system", "content": system.strip()})
    messages.append({"role": "user", "content": prompt.strip()})
    return messages


def extract_text(response_json: Mapping[str, Any]) -> str:
    choices = response_json.get("choices") or []
    if not choices:
        return ""
    first = choices[0]
    if not isinstance(first, Mapping):
        return ""
    message = first.get("message") or {}
    if not isinstance(message, Mapping):
        return ""
    content = message.get("content")
    return content.strip() if isinstance(content, str) else ""


def usage_from_response(
    response_json: Mapping[str, Any],
    *,
    model: str,
    require_reported: bool,
) -> Usage:
    raw_usage = response_json.get("usage")
    if not isinstance(raw_usage, Mapping):
        if require_reported:
            raise RuntimeError("DeepSeek response did not report usage")
        return Usage.cost_unknown()

    input_tokens = _int_token(raw_usage.get("prompt_tokens", raw_usage.get("input_tokens", 0)))
    output_tokens = _int_token(raw_usage.get("completion_tokens", raw_usage.get("output_tokens", 0)))
    cache_hit_tokens = _int_token(
        raw_usage.get("prompt_cache_hit_tokens", raw_usage.get("cached_tokens", 0))
    )
    cache_miss_tokens = _int_token(raw_usage.get("prompt_cache_miss_tokens", 0))
    if cache_miss_tokens == 0:
        cache_miss_tokens = max(input_tokens - cache_hit_tokens, 0)

    estimated_cost_cny = estimate_cost_cny(
        model=model,
        cache_hit_input_tokens=cache_hit_tokens,
        cache_miss_input_tokens=cache_miss_tokens,
        output_tokens=output_tokens,
    )
    return Usage(
        status=UsageStatus.REPORTED,
        input_tokens=input_tokens,
        cached_input_tokens=cache_hit_tokens,
        output_tokens=output_tokens,
        estimated_cost_cny=estimated_cost_cny,
    )


def estimate_cost_cny(
    *,
    model: str,
    cache_hit_input_tokens: int,
    cache_miss_input_tokens: int,
    output_tokens: int,
) -> str:
    pricing = MODEL_PRICING_USD_PER_1M[model]
    usd = (
        Decimal(cache_hit_input_tokens) * pricing["cache_hit_input"]
        + Decimal(cache_miss_input_tokens) * pricing["cache_miss_input"]
        + Decimal(output_tokens) * pricing["output"]
    ) / Decimal(1_000_000)
    return str((usd * DEFAULT_USD_CNY).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _finish_reason(response_json: Mapping[str, Any]) -> str | None:
    choices = response_json.get("choices") or []
    if not choices or not isinstance(choices[0], Mapping):
        return None
    finish_reason = choices[0].get("finish_reason")
    return finish_reason if isinstance(finish_reason, str) else None


def _int_token(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
