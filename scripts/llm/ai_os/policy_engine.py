"""Deterministic AIOS-K2 policy gate.

The policy engine decides whether a compiled K1 task manifest is allowed to
build context and call Router. It does not execute Agents, read GitHub, call
model APIs, or infer missing fields from chat history.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence


SCHEMA = "aios-policy-decision.v1"
POLICY_ALLOWED = "POLICY_ALLOWED"
POLICY_BLOCKED = "POLICY_BLOCKED"
SPEC_BLOCKED = "SPEC_BLOCKED"
MODES = {"SHADOW", "PRODUCTION"}
RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "CONSTITUTIONAL"}
ROUTER_NETWORK_POLICIES = {
    "OFFLINE": "deny",
}
LIVE_DATA_POLICY = "LIVE_DATA"
BLOCKED_PATH_PREFIX = "experiments/execution_tracker"
TASK_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:moonshot|deepseek|progress|github|openai|api)[\w-]*(?:key|token|secret)\b"),
    re.compile(r"(?i)\bsk(?:_live)?-[a-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bsk_live_[a-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bgh[opsu]_[a-z0-9_]{8,}\b"),
    re.compile(r"(?i)\bgithub_pat_[a-z0-9_]{20,}\b"),
    re.compile(r"(?i)\baws[_-]*secret[_-]*access[_-]*key\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"(?i)\bxox[baprs]-[a-z0-9-]{8,}\b"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |)PRIVATE KEY-----"),
)
EXTERNAL_INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "disregard previous instructions",
    "system prompt",
    "system:",
    "developer:",
    "忽略以上",
    "忽略之前",
)
TASK_MANIFEST_SCHEMA = "ai-task.v1"
REQUIRED_TASK_STRING_FIELDS = (
    "schema",
    "task_id",
    "objective",
    "human_owner",
    "reviewer",
    "risk_level",
    "network_policy",
    "created_at",
)
REQUIRED_TASK_LIST_FIELDS = (
    "authority_docs",
    "file_scope",
    "acceptance_tests",
    "approval_gates",
)
OPTIONAL_TASK_LIST_FIELDS = (
    "forbidden_scope",
    "executor_candidates",
    "dependencies",
    "input_contracts",
    "output_artifacts",
)


@dataclass(frozen=True)
class PolicyReason:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class PolicyDecision:
    policy_status: str
    task_id: str | None
    policy_reasons: tuple[PolicyReason, ...]
    route_request: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": SCHEMA,
            "task_id": self.task_id,
            "policy_status": self.policy_status,
            "policy_reasons": [reason.to_dict() for reason in self.policy_reasons],
            "route_request": self.route_request,
        }
        return {
            **payload,
            "policy_decision_hash": _hash_json(payload),
        }


def evaluate_policy(
    task_manifest: Mapping[str, Any],
    *,
    mode: Any,
    task_type: Any,
    required_tools: Any,
    target_paths: Any,
    reviewer_agent: Any = None,
    approval_evidence: Any = None,
    allowlist_evidence: Any = None,
    external_texts: Any = None,
) -> PolicyDecision:
    """Return a fail-closed policy decision for a K2 Router handoff."""

    spec_reasons: list[PolicyReason] = []
    policy_reasons: list[PolicyReason] = []

    if not isinstance(task_manifest, Mapping):
        return PolicyDecision(
            SPEC_BLOCKED,
            None,
            (PolicyReason("task_manifest.invalid", "task_manifest must be a mapping"),),
            None,
        )

    task_id = _string_or_none(task_manifest.get("task_id"))
    for field_name in REQUIRED_TASK_STRING_FIELDS:
        _require_string(task_manifest, field_name, spec_reasons)
    for field_name in OPTIONAL_TASK_LIST_FIELDS:
        _optional_string_list(task_manifest, field_name, spec_reasons)
    if task_manifest.get("schema") != TASK_MANIFEST_SCHEMA:
        spec_reasons.append(
            PolicyReason("schema.unsupported", f"schema must be {TASK_MANIFEST_SCHEMA}")
        )
    file_scope = _require_string_list(task_manifest, "file_scope", spec_reasons)
    forbidden_scope = _optional_string_list(task_manifest, "forbidden_scope", spec_reasons)
    for field_name in ("authority_docs", "acceptance_tests", "approval_gates"):
        _require_string_list(task_manifest, field_name, spec_reasons)
    budget = _validate_budget(task_manifest.get("budget"))
    if isinstance(budget, PolicyReason):
        spec_reasons.append(budget)

    cleaned_mode = _clean_required_string(mode, "mode", spec_reasons)
    cleaned_task_type = _clean_task_type(task_type, spec_reasons)
    cleaned_tools = _clean_required_string_list(
        required_tools,
        "required_tools",
        spec_reasons,
    )
    cleaned_targets = _clean_required_string_list(
        target_paths,
        "target_paths",
        spec_reasons,
    )

    risk_level = task_manifest.get("risk_level")
    if risk_level not in RISK_LEVELS:
        spec_reasons.append(
            PolicyReason("risk_level.unsupported", "risk_level is not supported")
        )
    if cleaned_mode is not None and cleaned_mode not in MODES:
        spec_reasons.append(PolicyReason("mode.unsupported", "mode is not supported"))

    if spec_reasons:
        return PolicyDecision(SPEC_BLOCKED, task_id, tuple(spec_reasons), None)

    router_network = _map_network_policy(
        str(task_manifest["network_policy"]),
        allowlist_evidence,
    )
    if isinstance(router_network, PolicyReason):
        policy_reasons.append(router_network)

    normalized_scopes = [_normalize_path(path) for path in file_scope]
    normalized_forbidden = [_normalize_path(path) for path in forbidden_scope]
    normalized_targets = [_normalize_path(path) for path in cleaned_targets]

    # governance-mutation: AIOS_K2_SCOPE_NORMALIZATION
    if any(path is None for path in normalized_scopes):
        spec_reasons.append(
            PolicyReason("file_scope.unsafe", "file_scope contains unsafe paths")
        )
    if any(path is None for path in normalized_forbidden):
        spec_reasons.append(
            PolicyReason(
                "forbidden_scope.unsafe",
                "forbidden_scope contains unsafe paths",
            )
        )
    if spec_reasons:
        return PolicyDecision(SPEC_BLOCKED, task_id, tuple(spec_reasons), None)

    for index, target in enumerate(normalized_targets):
        original = cleaned_targets[index]
        if target is None:
            policy_reasons.append(
                PolicyReason("target_path.unsafe", f"target_path is unsafe: {original}")
            )
            continue
        if _is_inside(target, BLOCKED_PATH_PREFIX):
            policy_reasons.append(
                PolicyReason(
                    "target_path.execution_tracker",
                    "experiments/execution_tracker targets are forbidden",
                )
            )
        if not any(scope and _is_inside(target, scope) for scope in normalized_scopes):
            policy_reasons.append(
                PolicyReason(
                    "target_path.outside_file_scope",
                    f"target_path is outside file_scope: {original}",
                )
            )
        if any(scope and _is_inside(target, scope) for scope in normalized_forbidden):
            policy_reasons.append(
                PolicyReason(
                    "target_path.forbidden_scope",
                    f"target_path is inside forbidden_scope: {original}",
                )
            )

    reviewer = _string_or_none(reviewer_agent)
    if risk_level in {"HIGH", "CONSTITUTIONAL"}:
        policy_reasons.append(
            PolicyReason(
                "risk_level.review_contract_unwired",
                "HIGH and CONSTITUTIONAL routing is blocked until reviewer capabilities are wired",
            )
        )
    elif cleaned_mode == "PRODUCTION" and risk_level == "MEDIUM":
        policy_reasons.append(
            PolicyReason(
                "risk_level.medium_production_blocked",
                "MEDIUM production routing is blocked until reviewer capabilities are wired",
            )
        )

    if risk_level == "CONSTITUTIONAL" and not _has_junyan_approval(approval_evidence):
        policy_reasons.append(
            PolicyReason(
                "approval.junyan_required",
                "CONSTITUTIONAL tasks require structured Junyan approval evidence",
            )
        )

    if _contains_secret_like_value(task_manifest) or _contains_secret_like_value(
        {
            "task_type": cleaned_task_type,
            "required_tools": cleaned_tools,
            "target_paths": cleaned_targets,
            "reviewer_agent": reviewer,
            "approval_evidence": approval_evidence,
            "allowlist_evidence": allowlist_evidence,
            "external_texts": external_texts,
        }
    ):
        policy_reasons.append(
            PolicyReason(
                "secret_like_input.blocked",
                "secret-like strings are not allowed in K2 policy inputs",
            )
        )

    if _contains_external_instruction(external_texts):
        policy_reasons.append(
            PolicyReason(
                "external_instruction.untrusted",
                "external instructions are untrusted and cannot modify AIOS policy",
            )
        )

    if policy_reasons:
        return PolicyDecision(POLICY_BLOCKED, task_id, tuple(policy_reasons), None)

    route_request = {
        "task_type": cleaned_task_type,
        "mode": cleaned_mode,
        "required_tools": cleaned_tools,
        "target_paths": normalized_targets,
        "network_policy": router_network,
        "risk_level": risk_level,
        "budget_max_cny": budget,
        "reviewer_agent": reviewer,
    }
    return PolicyDecision(POLICY_ALLOWED, task_id, (), route_request)


def _require_string(
    source: Mapping[str, Any],
    field_name: str,
    reasons: list[PolicyReason],
) -> str | None:
    return _clean_required_string(source.get(field_name), field_name, reasons)


def _require_string_list(
    source: Mapping[str, Any],
    field_name: str,
    reasons: list[PolicyReason],
) -> list[str]:
    return _clean_required_string_list(source.get(field_name), field_name, reasons)


def _optional_string_list(
    source: Mapping[str, Any],
    field_name: str,
    reasons: list[PolicyReason],
) -> list[str]:
    value = source.get(field_name, [])
    if value is None:
        return []
    if not isinstance(value, list):
        reasons.append(
            PolicyReason(
                f"{field_name}.invalid",
                f"{field_name} must be a string list when present",
            )
        )
        return []
    cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(cleaned) != len(value):
        reasons.append(
            PolicyReason(
                f"{field_name}.invalid",
                f"{field_name} must contain only non-empty strings",
            )
        )
    return cleaned


def _clean_required_string(
    value: Any,
    field_name: str,
    reasons: list[PolicyReason],
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        reasons.append(
            PolicyReason(
                f"{field_name}.missing",
                f"{field_name} must be a non-empty string",
            )
        )
        return None
    return value.strip()


def _clean_task_type(value: Any, reasons: list[PolicyReason]) -> str | None:
    cleaned = _clean_required_string(value, "task_type", reasons)
    if cleaned is None:
        return None
    if cleaned != cleaned.strip().casefold() or not TASK_TYPE_RE.fullmatch(cleaned):
        reasons.append(
            PolicyReason(
                "task_type.noncanonical",
                "task_type must be a canonical lowercase token",
            )
        )
        return None
    return cleaned


def _clean_required_string_list(
    value: Any,
    field_name: str,
    reasons: list[PolicyReason],
) -> list[str]:
    if not isinstance(value, list) or not value:
        reasons.append(
            PolicyReason(
                f"{field_name}.missing",
                f"{field_name} must be a non-empty string list",
            )
        )
        return []
    cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(cleaned) != len(value):
        reasons.append(
            PolicyReason(
                f"{field_name}.invalid",
                f"{field_name} must contain only non-empty strings",
            )
        )
    return cleaned


def _validate_budget(value: Any) -> str | PolicyReason:
    if not isinstance(value, Mapping):
        return PolicyReason("budget.invalid", "budget must be a mapping")
    max_cny = value.get("max_cny")
    if not isinstance(max_cny, str) or not max_cny.strip():
        return PolicyReason(
            "budget.max_cny.invalid",
            "budget.max_cny must be a non-empty string amount",
        )
    try:
        amount = Decimal(max_cny.strip())
    except (InvalidOperation, ValueError):
        return PolicyReason(
            "budget.max_cny.invalid",
            "budget.max_cny must be a valid decimal string",
        )
    if not amount.is_finite():
        return PolicyReason("budget.max_cny.invalid", "budget.max_cny must be finite")
    if amount < 0:
        return PolicyReason(
            "budget.max_cny.invalid",
            "budget.max_cny must be non-negative",
        )
    return format(amount, "f")


def _map_network_policy(value: str, allowlist_evidence: Any) -> str | PolicyReason:
    if value == LIVE_DATA_POLICY:
        return PolicyReason(
            "network_policy.live_data_blocked",
            "LIVE_DATA is blocked until Junyan approves the Router mapping",
        )
    if value == "ALLOWLIST":
        # governance-mutation: AIOS_K2_ALLOWLIST_V0_BLOCK
        if _allowlist_registry_is_unwired():
            return PolicyReason(
                "network_policy.allowlist_registry_unwired",
                "ALLOWLIST is blocked until trusted provider allowlist registry is wired",
            )
        return "provider_only"
    if value not in ROUTER_NETWORK_POLICIES:
        return PolicyReason(
            "network_policy.unsupported",
            "network_policy cannot be safely mapped to Router",
        )
    return ROUTER_NETWORK_POLICIES[value]


def _normalize_path(value: str) -> str | None:
    cleaned = unicodedata.normalize("NFKC", value.strip()).replace("\\", "/")
    if not cleaned or cleaned.startswith("/") or ":" in cleaned or "%" in cleaned:
        return None
    parts = PurePosixPath(cleaned).parts
    if any(
        part in {"", ".", ".."} or part.endswith(".")
        for part in parts
    ):
        return None
    return "/".join(parts)


def _is_inside(path: str, scope: str) -> bool:
    path_key = _path_key(path)
    scope_key = _path_key(scope).rstrip("/")
    return path_key == scope_key or path_key.startswith(scope_key + "/")


def _path_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _has_junyan_approval(value: Any) -> bool:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_has_junyan_approval(item) for item in value)
    if isinstance(value, Mapping):
        decided_by = value.get("decided_by")
        decision = value.get("decision")
        has_anchor = any(
            isinstance(value.get(field_name), str) and bool(value.get(field_name, "").strip())
            for field_name in ("approval_ref", "commit_sha", "issue_url")
        )
        return (
            isinstance(decided_by, str)
            and decided_by.casefold().strip() == "junyan"
            and isinstance(decision, str)
            and decision.casefold().strip() in {"approve", "approved"}
            and has_anchor
        )
    return False


def _contains_secret_like_value(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in SECRET_PATTERNS)
    if isinstance(value, Mapping):
        return any(
            _contains_secret_like_value(item)
            for pair in value.items()
            for item in pair
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_secret_like_value(item) for item in value)
    return False


def _contains_external_instruction(value: Any) -> bool:
    if isinstance(value, str):
        lowered = unicodedata.normalize("NFKC", value).casefold()
        return any(marker in lowered for marker in EXTERNAL_INJECTION_MARKERS)
    if isinstance(value, Mapping):
        return any(
            _contains_external_instruction(item)
            for pair in value.items()
            for item in pair
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_external_instruction(item) for item in value)
    return False


def _has_allowlist_evidence(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    endpoints = value.get("allowed_endpoints") or value.get("provider_endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        return False
    if not all(isinstance(item, str) and item.strip() for item in endpoints):
        return False
    return any(
        isinstance(value.get(field_name), str) and bool(value.get(field_name, "").strip())
        for field_name in ("approval_ref", "commit_sha", "issue_url")
    )


def _allowlist_registry_is_unwired() -> bool:
    return True


def _hash_json(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()
