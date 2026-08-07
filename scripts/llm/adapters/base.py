"""Provider-neutral contracts for the AIOS Agent Harness.

The module is deliberately independent from provider SDKs and production data
contracts.  Provider wrappers implement ``AgentAdapter.execute``; callers use
``run_adapter`` to receive the same success, timeout, and error envelope.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from time import monotonic
from typing import Any, Callable, Mapping
from uuid import uuid4


class AgentStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    SPEC_BLOCKED = "SPEC_BLOCKED"


class UsageStatus(str, Enum):
    REPORTED = "REPORTED"
    COST_UNKNOWN = "COST_UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class AgentRequest:
    task_id: str
    task_type: str
    input_payload: Mapping[str, Any]
    prompt_version: str
    risk_level: str = "LOW"
    timeout_seconds: float = 60.0
    evidence_grade: str = "E4"
    network_policy: str = "deny"

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        for name, value in (
            ("task_id", self.task_id),
            ("task_type", self.task_type),
            ("prompt_version", self.prompt_version),
        ):
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{name} must be a non-empty string")
        if not isinstance(self.input_payload, Mapping):
            errors.append("input_payload must be a mapping")
        else:
            try:
                _canonical_json(self.input_payload)
            except (TypeError, ValueError):
                errors.append("input_payload must be JSON serializable")
        if not isinstance(self.timeout_seconds, (int, float)) or isinstance(
            self.timeout_seconds, bool
        ) or self.timeout_seconds <= 0:
            errors.append("timeout_seconds must be a positive number")
        if not isinstance(self.risk_level, str) or self.risk_level not in {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CONSTITUTIONAL",
        }:
            errors.append("risk_level is not supported")
        if not isinstance(self.network_policy, str) or self.network_policy not in {
            "deny",
            "provider_only",
        }:
            errors.append("network_policy is not supported")
        if not isinstance(self.evidence_grade, str) or self.evidence_grade not in {
            "E1",
            "E2",
            "E3",
            "E4",
        }:
            errors.append("evidence_grade is not supported")
        return errors

    def input_hash(self) -> str:
        payload = _canonical_json(self.input_payload)
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Usage:
    status: UsageStatus
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_cny: str | None = None

    @classmethod
    def not_applicable(cls) -> "Usage":
        return cls(status=UsageStatus.NOT_APPLICABLE)

    @classmethod
    def cost_unknown(cls) -> "Usage":
        return cls(status=UsageStatus.COST_UNKNOWN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_cny": self.estimated_cost_cny,
        }


class AdapterExecutionError(Exception):
    """Structured provider failure with explicit retry and usage semantics."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        usage: Usage | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.retryable = retryable
        self.usage = usage or Usage.cost_unknown()


@dataclass(frozen=True)
class AgentError:
    code: str
    message: str
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


@dataclass(frozen=True)
class AdapterOutput:
    output: Mapping[str, Any]
    usage: Usage
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentResult:
    run_id: str
    task_id: str
    task_type: str
    provider: str
    model: str | None
    prompt_version: str
    evidence_grade: str
    input_hash: str
    status: AgentStatus
    started_at: str
    finished_at: str
    duration_ms: int
    output: Mapping[str, Any] | None = None
    usage: Usage = field(default_factory=Usage.cost_unknown)
    evidence_refs: tuple[str, ...] = ()
    error: AgentError | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "evidence_grade": self.evidence_grade,
            "input_hash": self.input_hash,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "output": dict(self.output) if self.output is not None else None,
            "usage": self.usage.to_dict(),
            "evidence_refs": list(self.evidence_refs),
            "error": self.error.to_dict() if self.error else None,
        }


class AgentAdapter(ABC):
    """Provider wrapper contract. Implementations must enforce their timeout."""

    provider: str = "unknown"
    model: str | None = None

    @abstractmethod
    def execute(self, request: AgentRequest) -> AdapterOutput:
        """Execute one request or raise TimeoutError/provider exception."""


def run_adapter(
    adapter: AgentAdapter,
    request: AgentRequest,
    *,
    run_id_factory: Callable[[], str] | None = None,
    now: Callable[[], datetime] | None = None,
    timer: Callable[[], float] = monotonic,
) -> AgentResult:
    """Run an adapter and fail closed into a provider-neutral result."""

    run_id_factory = run_id_factory or (lambda: f"run_{uuid4().hex}")
    now = now or (lambda: datetime.now(timezone.utc))
    run_id = run_id_factory()
    started_at = now().astimezone(timezone.utc).isoformat()
    started = timer()

    try:
        errors = request.validation_errors()
    except Exception:
        errors = ["request validation failed"]
    if errors:
        return _result(
            adapter,
            request,
            run_id=run_id,
            status=AgentStatus.SPEC_BLOCKED,
            started_at=started_at,
            finished_at=now().astimezone(timezone.utc).isoformat(),
            duration_ms=_duration_ms(started, timer()),
            error=AgentError("INVALID_REQUEST", "; ".join(errors)),
        )

    try:
        adapter_output = adapter.execute(request)
        if not isinstance(adapter_output, AdapterOutput):
            raise TypeError("adapter must return AdapterOutput")
        return _result(
            adapter,
            request,
            run_id=run_id,
            status=AgentStatus.SUCCEEDED,
            started_at=started_at,
            finished_at=now().astimezone(timezone.utc).isoformat(),
            duration_ms=_duration_ms(started, timer()),
            output=adapter_output.output,
            usage=adapter_output.usage,
            evidence_refs=adapter_output.evidence_refs,
        )
    except TimeoutError:
        return _result(
            adapter,
            request,
            run_id=run_id,
            status=AgentStatus.TIMEOUT,
            started_at=started_at,
            finished_at=now().astimezone(timezone.utc).isoformat(),
            duration_ms=_duration_ms(started, timer()),
            error=AgentError("TIMEOUT", "agent execution timed out", retryable=True),
        )
    except AdapterExecutionError as exc:
        return _result(
            adapter,
            request,
            run_id=run_id,
            status=AgentStatus.FAILED,
            started_at=started_at,
            finished_at=now().astimezone(timezone.utc).isoformat(),
            duration_ms=_duration_ms(started, timer()),
            usage=exc.usage,
            error=AgentError(exc.code, exc.safe_message, retryable=exc.retryable),
        )
    except Exception as exc:  # provider failures are data, not harness crashes
        return _result(
            adapter,
            request,
            run_id=run_id,
            status=AgentStatus.FAILED,
            started_at=started_at,
            finished_at=now().astimezone(timezone.utc).isoformat(),
            duration_ms=_duration_ms(started, timer()),
            error=AgentError("PROVIDER_ERROR", _safe_error_message(exc), retryable=True),
        )


def _result(
    adapter: AgentAdapter,
    request: AgentRequest,
    *,
    run_id: str,
    status: AgentStatus,
    started_at: str,
    finished_at: str,
    duration_ms: int,
    output: Mapping[str, Any] | None = None,
    usage: Usage | None = None,
    evidence_refs: tuple[str, ...] = (),
    error: AgentError | None = None,
) -> AgentResult:
    return AgentResult(
        run_id=run_id,
        task_id=request.task_id,
        task_type=request.task_type,
        provider=getattr(adapter, "provider", "unknown"),
        model=getattr(adapter, "model", None),
        prompt_version=request.prompt_version,
        evidence_grade=request.evidence_grade,
        input_hash=_safe_input_hash(request),
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        output=output,
        usage=usage or Usage.cost_unknown(),
        evidence_refs=evidence_refs,
        error=error,
    )


def _duration_ms(started: float, finished: float) -> int:
    return max(0, round((finished - started) * 1000))


def _safe_error_message(exc: Exception) -> str:
    # Avoid serializing exception repr/arguments, which can contain credentials
    # or provider response bodies. The exception class is enough for routing.
    return f"{type(exc).__name__} during provider execution"


def _safe_input_hash(request: AgentRequest) -> str:
    try:
        return request.input_hash()
    except (TypeError, ValueError):
        return "UNAVAILABLE"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
