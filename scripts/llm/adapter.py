"""Moonshot Kimi K3 adapter with a tiny usage ledger.

This module is intentionally small and dependency-free. It reads the API key
only from MOONSHOT_API_KEY, calls the OpenAI-compatible chat completions API,
and appends token/cost metadata to llm_usage.json.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


BASE_URL = "https://api.moonshot.cn/v1"
MODEL = "kimi-k3"
USAGE_PATH = Path(__file__).with_name("llm_usage.json")

DEFAULT_USD_CNY = Decimal(os.environ.get("LLM_USD_CNY", "7.20"))
INPUT_CACHE_HIT_USD_PER_1M = Decimal(
    os.environ.get("KIMI_K3_INPUT_CACHE_HIT_USD_PER_1M", "0.30")
)
INPUT_CACHE_MISS_USD_PER_1M = Decimal(
    os.environ.get("KIMI_K3_INPUT_CACHE_MISS_USD_PER_1M", "3.00")
)
OUTPUT_USD_PER_1M = Decimal(os.environ.get("KIMI_K3_OUTPUT_USD_PER_1M", "15.00"))


def chat_completion(
    *,
    task_name: str,
    messages: list[dict[str, str]],
    max_tokens: int = 128,
    reasoning_effort: str = "low",
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Call Kimi K3 and record usage metadata.

    The prompt and response body are not written to the ledger. Research input
    can be sensitive, so the ledger stores only operational metadata.
    """

    api_key = _read_api_key()
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 1.0,
        "reasoning_effort": reasoning_effort,
    }
    response_json = _post_chat_completion(api_key, payload, timeout_seconds)
    usage = response_json.get("usage") or {}
    cost = estimate_cost(usage)
    usage_record = _build_usage_record(task_name, usage, cost)
    append_usage_record(usage_record)

    return {
        "text": extract_text(response_json),
        "response": response_json,
        "usage_record": usage_record,
    }


def estimate_cost(usage: dict[str, Any]) -> dict[str, str]:
    """Estimate USD/CNY cost from OpenAI-compatible usage fields."""

    input_tokens = _int_token(
        usage.get("prompt_tokens", usage.get("input_tokens", 0))
    )
    cached_tokens = _int_token(
        usage.get("cached_tokens", usage.get("cache_read_input_tokens", 0))
    )
    output_tokens = _int_token(
        usage.get("completion_tokens", usage.get("output_tokens", 0))
    )
    cache_miss_input_tokens = max(input_tokens - cached_tokens, 0)

    usd = (
        (Decimal(cached_tokens) * INPUT_CACHE_HIT_USD_PER_1M)
        + (Decimal(cache_miss_input_tokens) * INPUT_CACHE_MISS_USD_PER_1M)
        + (Decimal(output_tokens) * OUTPUT_USD_PER_1M)
    ) / Decimal(1_000_000)
    cny = usd * DEFAULT_USD_CNY

    return {
        "estimated_cost_usd": _money(usd, places="0.00000001"),
        "estimated_cost_cny": _money(cny, places="0.000001"),
    }


def extract_text(response_json: dict[str, Any]) -> str:
    """Extract the assistant text from a chat completion response."""

    choices = response_json.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return ""


def append_usage_record(record: dict[str, Any], usage_path: Path = USAGE_PATH) -> None:
    """Append one record to the JSON usage ledger."""

    ledger = _read_usage_ledger(usage_path)
    ledger.append(record)

    usage_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = usage_path.with_suffix(usage_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(usage_path)


def _post_chat_completion(
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
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
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Kimi K3 API request failed with HTTP {exc.code}: {body[:500]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Kimi K3 API request failed: {exc.reason}") from exc


def _build_usage_record(
    task_name: str,
    usage: dict[str, Any],
    cost: dict[str, str],
) -> dict[str, Any]:
    input_tokens = _int_token(
        usage.get("prompt_tokens", usage.get("input_tokens", 0))
    )
    output_tokens = _int_token(
        usage.get("completion_tokens", usage.get("output_tokens", 0))
    )
    cached_tokens = _int_token(
        usage.get("cached_tokens", usage.get("cache_read_input_tokens", 0))
    )

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "moonshot",
        "base_url": BASE_URL,
        "model": MODEL,
        "task_name": task_name,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": cost["estimated_cost_usd"],
        "estimated_cost_cny": cost["estimated_cost_cny"],
    }


def _read_api_key() -> str:
    api_key = os.environ.get("MOONSHOT_API_KEY")
    if not api_key:
        raise RuntimeError(
            "MOONSHOT_API_KEY is not set. Put it in your local environment only; "
            "never paste it into code, commits, or chat."
        )
    return api_key


def _read_usage_ledger(usage_path: Path) -> list[dict[str, Any]]:
    if not usage_path.exists():
        return []

    raw = usage_path.read_text(encoding="utf-8").strip()
    if not raw:
        return []

    ledger = json.loads(raw)
    if not isinstance(ledger, list):
        raise ValueError(f"{usage_path} must contain a JSON list.")
    return ledger


def _int_token(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _money(value: Decimal, *, places: str) -> str:
    return str(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))
