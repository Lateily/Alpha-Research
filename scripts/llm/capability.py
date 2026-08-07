"""Fail-closed capability registry and router for AIOS Harness A-014.

This module is an offline control-plane core. It does not call an AgentAdapter,
grant production status, or persist a new production data contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import PurePosixPath
from typing import Iterable


class CapabilityStatus(str, Enum):
    SHADOW_ONLY = "SHADOW_ONLY"
    PRODUCTION_ELIGIBLE = "PRODUCTION_ELIGIBLE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class RouteMode(str, Enum):
    SHADOW = "SHADOW"
    PRODUCTION = "PRODUCTION"


class RouteStatus(str, Enum):
    SELECTED = "SELECTED"
    NO_ELIGIBLE_CAPABILITY = "NO_ELIGIBLE_CAPABILITY"
    SPEC_BLOCKED = "SPEC_BLOCKED"


@dataclass(frozen=True)
class CapabilityRecord:
    agent: str
    task_type: str
    tool_access: frozenset[str]
    file_scope: tuple[str, ...]
    network_access: frozenset[str]
    status: CapabilityStatus
    cost_cny_per_run: str | None
    eval_version: str | None = None
    eval_score: str | None = None
    last_tested: str | None = None
    known_failures: tuple[str, ...] = ()
    deterministic: bool = False

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not _non_empty(self.agent):
            errors.append("agent must be a non-empty string")
        if not _non_empty(self.task_type):
            errors.append("task_type must be a non-empty string")
        if not isinstance(self.status, CapabilityStatus):
            errors.append("status must be a CapabilityStatus")
        if not isinstance(self.tool_access, frozenset) or not all(
            _non_empty(item) for item in self.tool_access
        ):
            errors.append("tool_access must be a frozenset of non-empty strings")
        if not isinstance(self.file_scope, tuple) or not self.file_scope:
            errors.append("file_scope must not be empty")
        elif any(_safe_relative_path(scope) is None for scope in self.file_scope):
            errors.append("file_scope contains an unsafe path")
        if (
            not isinstance(self.network_access, frozenset)
            or not self.network_access
            or not self.network_access <= {
            "deny",
            "provider_only",
            }
        ):
            errors.append("network_access is not supported")
        if not isinstance(self.deterministic, bool):
            errors.append("deterministic must be a boolean")
        if not isinstance(self.known_failures, tuple) or not all(
            _non_empty(item) for item in self.known_failures
        ):
            errors.append("known_failures must be a tuple of non-empty strings")
        if self.cost_cny_per_run is not None:
            try:
                if _decimal(self.cost_cny_per_run) < 0:
                    errors.append("cost_cny_per_run must be non-negative")
            except (InvalidOperation, ValueError):
                errors.append("cost_cny_per_run must be a decimal string or null")
        if self.eval_score is not None:
            try:
                if _decimal(self.eval_score) < 0:
                    errors.append("eval_score must be non-negative")
            except (InvalidOperation, ValueError):
                errors.append("eval_score must be a decimal string or null")
        if (
            self.status is CapabilityStatus.PRODUCTION_ELIGIBLE
            and not self.deterministic
            and (not _non_empty(self.eval_version) or self.eval_score is None)
        ):
            errors.append(
                "non-deterministic production capability requires task-specific eval"
            )
        return errors

    def cost(self) -> Decimal | None:
        if self.cost_cny_per_run is None:
            return None
        return _decimal(self.cost_cny_per_run)


@dataclass(frozen=True)
class RouteRequest:
    task_type: str
    mode: RouteMode
    required_tools: frozenset[str]
    target_paths: tuple[str, ...]
    network_policy: str
    risk_level: str
    budget_max_cny: str | None = None
    reviewer_agent: str | None = None

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not _non_empty(self.task_type):
            errors.append("task_type must be a non-empty string")
        if not isinstance(self.mode, RouteMode):
            errors.append("mode must be a RouteMode")
        if not isinstance(self.required_tools, frozenset) or not all(
            _non_empty(item) for item in self.required_tools
        ):
            errors.append("required_tools must be a frozenset of non-empty strings")
        if not isinstance(self.target_paths, tuple) or not self.target_paths:
            errors.append("target_paths must not be empty")
        elif any(_safe_relative_path(path) is None for path in self.target_paths):
            errors.append("target_paths contains an unsafe path")
        if self.network_policy not in {"deny", "provider_only"}:
            errors.append("network_policy is not supported")
        if self.risk_level not in {"LOW", "MEDIUM", "HIGH", "CONSTITUTIONAL"}:
            errors.append("risk_level is not supported")
        if self.budget_max_cny is not None:
            try:
                if _decimal(self.budget_max_cny) < 0:
                    errors.append("budget_max_cny must be non-negative")
            except (InvalidOperation, ValueError):
                errors.append("budget_max_cny must be a decimal string or null")
        if self.risk_level in {"HIGH", "CONSTITUTIONAL"} and not _non_empty(
            self.reviewer_agent
        ):
            errors.append("high-risk routing requires a named independent reviewer")
        return errors


@dataclass(frozen=True)
class RouteDecision:
    status: RouteStatus
    selected_agent: str | None
    reasons: tuple[str, ...]


class CapabilityRegistry:
    def __init__(self, records: Iterable[CapabilityRecord]) -> None:
        self._records = tuple(records)
        errors: list[str] = []
        seen: set[tuple[str, str]] = set()
        for index, record in enumerate(self._records):
            if not isinstance(record, CapabilityRecord):
                errors.append(f"record[{index}]: must be a CapabilityRecord")
                continue
            errors.extend(
                f"record[{index}]: {error}" for error in record.validation_errors()
            )
            key = (record.agent, record.task_type)
            if key in seen:
                errors.append(f"duplicate capability: {record.agent}/{record.task_type}")
            seen.add(key)
        if errors:
            raise ValueError("; ".join(errors))

    @property
    def records(self) -> tuple[CapabilityRecord, ...]:
        return self._records


def route(registry: CapabilityRegistry, request: RouteRequest) -> RouteDecision:
    errors = request.validation_errors()
    if errors:
        return RouteDecision(RouteStatus.SPEC_BLOCKED, None, tuple(errors))

    rejected: list[str] = []
    eligible: list[CapabilityRecord] = []
    for capability in registry.records:
        reasons = _ineligible_reasons(capability, request)
        if reasons:
            rejected.extend(f"{capability.agent}: {reason}" for reason in reasons)
        else:
            eligible.append(capability)

    if not eligible:
        return RouteDecision(
            RouteStatus.NO_ELIGIBLE_CAPABILITY,
            None,
            tuple(rejected) or ("registry has no capabilities",),
        )

    selected = min(
        eligible,
        key=lambda item: (
            not item.deterministic,
            item.cost() is None,
            item.cost() or Decimal("0"),
            item.agent,
        ),
    )
    return RouteDecision(
        RouteStatus.SELECTED,
        selected.agent,
        ("deterministic-first, then known lower cost, then stable agent name",),
    )


def _ineligible_reasons(
    capability: CapabilityRecord, request: RouteRequest
) -> list[str]:
    reasons: list[str] = []
    if capability.task_type != request.task_type:
        reasons.append("task_type mismatch")
    if capability.status in {CapabilityStatus.SUSPENDED, CapabilityStatus.RETIRED}:
        reasons.append(f"status={capability.status.value}")
    elif (
        request.mode is RouteMode.PRODUCTION
        and capability.status is not CapabilityStatus.PRODUCTION_ELIGIBLE
    ):
        reasons.append("not production eligible")
    if not request.required_tools <= capability.tool_access:
        reasons.append("missing required tool access")
    if request.network_policy not in capability.network_access:
        reasons.append("network policy not allowed")
    if not all(_path_allowed(path, capability.file_scope) for path in request.target_paths):
        reasons.append("target path outside file scope")
    if request.reviewer_agent == capability.agent and request.risk_level in {
        "HIGH",
        "CONSTITUTIONAL",
    }:
        reasons.append("executor cannot be the independent reviewer")
    if request.budget_max_cny is not None:
        cost = capability.cost()
        if cost is None:
            reasons.append("cost unknown under finite budget")
        elif cost > _decimal(request.budget_max_cny):
            reasons.append("estimated cost exceeds budget")
    return reasons


def _path_allowed(path: str, scopes: tuple[str, ...]) -> bool:
    normalized = _safe_relative_path(path)
    if normalized is None:
        return False
    return any(
        normalized == scope or normalized.startswith(scope.rstrip("/") + "/")
        for scope in scopes
    )


def _safe_relative_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        return None
    return path.as_posix().rstrip("/")


def _decimal(value: str) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("decimal value must be a non-empty string")
    parsed = Decimal(value)
    if not parsed.is_finite():
        raise ValueError("decimal value must be finite")
    return parsed


def _non_empty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
