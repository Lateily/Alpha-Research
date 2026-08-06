"""Kimi provider wrapper for the provider-neutral AIOS Agent Harness.

Real calls are frozen by default. Offline tests must explicitly mark their
injected callable with ``offline_stub=True``; dependency injection alone is not
evidence that a callable cannot reach the network.
"""

from __future__ import annotations

import importlib.util
import socket
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Mapping

from .base import (
    AdapterExecutionError,
    AdapterOutput,
    AgentAdapter,
    AgentRequest,
    Usage,
    UsageStatus,
)


Completion = Callable[..., Mapping[str, Any]]


def _load_legacy_kimi() -> ModuleType:
    module_path = Path(__file__).resolve().parents[1] / "adapter.py"
    spec = importlib.util.spec_from_file_location("aios_legacy_kimi_adapter", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load legacy Kimi adapter from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


legacy_kimi = _load_legacy_kimi()


class KimiAdapter(AgentAdapter):
    provider = "moonshot"
    model = legacy_kimi.MODEL

    def __init__(
        self,
        completion: Completion | None = None,
        *,
        allow_real_call: bool = False,
        offline_stub: bool = False,
    ) -> None:
        if allow_real_call and offline_stub:
            raise ValueError("allow_real_call and offline_stub are mutually exclusive")
        self._completion = completion or legacy_kimi.chat_completion
        self._allow_real_call = allow_real_call
        self._offline_stub = offline_stub
        self._is_legacy_completion = self._completion is legacy_kimi.chat_completion

    def execute(self, request: AgentRequest) -> AdapterOutput:
        if request.network_policy != "provider_only":
            raise PermissionError("Kimi requires network_policy=provider_only")
        if not self._allow_real_call:
            if not self._offline_stub:
                raise PermissionError("Kimi calls are frozen without explicit opt-in")
            if self._is_legacy_completion:
                raise PermissionError("legacy Kimi completion cannot be an offline stub")

        messages = request.input_payload.get("messages")
        if not _valid_messages(messages):
            raise ValueError("input_payload.messages must be a non-empty message list")

        try:
            with _network_access(allowed=self._allow_real_call):
                result = self._completion(
                    task_name=request.task_type,
                    messages=messages,
                    prompt_version=request.prompt_version,
                    max_tokens=_positive_int(
                        request.input_payload.get("max_tokens"), 128
                    ),
                    reasoning_effort=_non_empty_string(
                        request.input_payload.get("reasoning_effort"), "low"
                    ),
                    timeout_seconds=request.timeout_seconds,
                )
        except legacy_kimi.UsageLedgerWriteError as exc:
            raise AdapterExecutionError(
                code="USAGE_LEDGER_WRITE_FAILED",
                message="paid provider usage was preserved outside the primary ledger",
                retryable=False,
                usage=_usage_from_record(exc.usage_record),
            ) from exc
        if not isinstance(result, Mapping):
            raise TypeError("Kimi completion must return a mapping")

        text = result.get("text")
        if not isinstance(text, str):
            raise TypeError("Kimi completion text must be a string")

        usage = _usage_from_record(result.get("usage_record"))
        if self._allow_real_call and usage.status is not UsageStatus.REPORTED:
            raise RuntimeError("real Kimi calls require REPORTED usage")

        return AdapterOutput(
            output={"text": text},
            usage=usage,
        )


def _usage_from_record(value: Any) -> Usage:
    if not isinstance(value, Mapping):
        return Usage.cost_unknown()

    required = (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "estimated_cost_cny",
    )
    if any(key not in value for key in required):
        return Usage.cost_unknown()

    try:
        input_tokens = _non_negative_int(value["input_tokens"])
        cached_tokens = _non_negative_int(value["cached_input_tokens"])
        output_tokens = _non_negative_int(value["output_tokens"])
    except (TypeError, ValueError):
        return Usage.cost_unknown()

    cost = value["estimated_cost_cny"]
    if not isinstance(cost, str) or not cost.strip():
        return Usage.cost_unknown()

    return Usage(
        status=UsageStatus.REPORTED,
        input_tokens=input_tokens,
        cached_input_tokens=cached_tokens,
        output_tokens=output_tokens,
        estimated_cost_cny=cost,
    )


def _valid_messages(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return all(
        isinstance(item, Mapping)
        and isinstance(item.get("role"), str)
        and bool(item["role"].strip())
        and isinstance(item.get("content"), str)
        for item in value
    )


def _positive_int(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError("value must be a positive integer")
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("value must be a positive integer")
    return parsed


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("token count must be a non-negative integer")
    parsed = int(value)
    if parsed < 0:
        raise ValueError("token count must be a non-negative integer")
    return parsed


def _non_empty_string(value: Any, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise ValueError("value must be a non-empty string")
    return value


@contextmanager
def _network_access(*, allowed: bool):
    if allowed:
        yield
        return

    original_socket = socket.socket
    original_create_connection = socket.create_connection

    def blocked(*_args, **_kwargs):
        raise PermissionError("network access is forbidden for offline Kimi stubs")

    socket.socket = blocked
    socket.create_connection = blocked
    try:
        yield
    finally:
        socket.socket = original_socket
        socket.create_connection = original_create_connection
