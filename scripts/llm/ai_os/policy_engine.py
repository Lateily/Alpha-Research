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

try:  # Support package imports and direct CLI execution from this directory.
    from .task_compiler import validate_compiled_manifest
except ImportError:  # pragma: no cover - exercised by the standalone CLI path.
    from task_compiler import validate_compiled_manifest


SCHEMA = "aios-policy-decision.v1"
POLICY_ALLOWED = "POLICY_ALLOWED"
POLICY_BLOCKED = "POLICY_BLOCKED"
SPEC_BLOCKED = "SPEC_BLOCKED"
MODES = {"SHADOW", "PRODUCTION"}
ROUTER_NETWORK_POLICIES = {
    "OFFLINE": "deny",
}
LIVE_DATA_POLICY = "LIVE_DATA"
BLOCKED_PATH_PREFIX = "experiments/execution_tracker"
TASK_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(?:moonshot|deepseek|progress|github|openai|api)"
        r"[\w-]*(?:key|token|secret)\b"
    ),
    re.compile(r"(?i)\bsk(?:_live)?-[a-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\bsk_live_[a-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\bgh[opsur]_[a-z0-9_]{20,}\b"),
    re.compile(r"(?i)\bgithub_pat_[a-z0-9_]{20,}\b"),
    re.compile(r"(?i)\baws[_-]*secret[_-]*access[_-]*key\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"(?i)\bxox[baprs]-[a-z0-9-]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |)PRIVATE KEY-----"),
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
    manifest_hash: str | None = None
    policy_input_hash: str | None = None
    external_input_status: str = "NOT_PROVIDED"

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": SCHEMA,
            "task_id": self.task_id,
            "policy_status": self.policy_status,
            "policy_reasons": [reason.to_dict() for reason in self.policy_reasons],
            "route_request": self.route_request,
            "manifest_hash": self.manifest_hash,
            "policy_input_hash": self.policy_input_hash,
            "external_input_status": self.external_input_status,
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
    external_input_status = _external_input_status(external_texts)

    if not isinstance(task_manifest, Mapping):
        return PolicyDecision(
            SPEC_BLOCKED,
            None,
            (PolicyReason("task_manifest.invalid", "task_manifest must be a mapping"),),
            None,
            external_input_status=external_input_status,
        )

    raw_policy_inputs = {
        "mode": mode,
        "task_type": task_type,
        "required_tools": required_tools,
        "target_paths": target_paths,
        "reviewer_agent": reviewer_agent,
        "approval_evidence": approval_evidence,
        "allowlist_evidence": allowlist_evidence,
        "external_texts": external_texts,
    }
    manifest_has_secret = _contains_secret_like_value(task_manifest)
    external_has_secret = _contains_secret_like_value(external_texts)
    secret_like_input = manifest_has_secret or _contains_secret_like_value(
        raw_policy_inputs
    )
    if external_has_secret:
        external_input_status = "BLOCKED_SECRET_LIKE"
    task_id = _safe_output_task_id(task_manifest.get("task_id"))

    manifest_errors = validate_compiled_manifest(task_manifest)
    # governance-mutation: AIOS_K2_CANONICAL_MANIFEST
    if manifest_errors:
        if manifest_has_secret:
            spec_reasons.append(
                PolicyReason(
                    "task_manifest.invalid",
                    "manifest contract invalid and unsafe to detail",
                )
            )
        else:
            spec_reasons.extend(
                PolicyReason(
                    "task_manifest.invalid",
                    f"manifest contract invalid: {error}",
                )
                for error in manifest_errors
            )
    elif not task_manifest.get("authority_docs"):
        spec_reasons.append(
            PolicyReason(
                "authority_docs.missing",
                "authority_docs must identify at least one task authority",
            )
        )
    if task_manifest.get("source_issue") is None:
        spec_reasons.append(
            PolicyReason(
                "source_issue.missing",
                "source_issue must identify the task's GitHub Issue",
            )
        )
    if task_id is None and not manifest_has_secret:
        spec_reasons.append(
            PolicyReason(
                "task_id.unsafe",
                "task_id cannot be safely serialized",
            )
        )

    manifest_hash = (
        None if manifest_errors or manifest_has_secret else _hash_json(task_manifest)
    )
    policy_input_hash = _policy_input_hash(
        raw_policy_inputs,
        secret_like=secret_like_input,
    )
    manifest_file_scope = task_manifest.get("file_scope")
    manifest_forbidden_scope = task_manifest.get("forbidden_scope")
    file_scope = list(manifest_file_scope) if isinstance(manifest_file_scope, list) else []
    forbidden_scope = (
        list(manifest_forbidden_scope)
        if isinstance(manifest_forbidden_scope, list)
        else []
    )
    budget = _validate_budget(task_manifest.get("budget"))
    if isinstance(budget, PolicyReason):
        spec_reasons.append(budget)

    cleaned_mode = _clean_required_string(mode, "mode", spec_reasons)
    cleaned_task_type = _clean_task_type(task_type, spec_reasons)
    cleaned_tools = _clean_required_identifier_list(
        required_tools,
        "required_tools",
        spec_reasons,
    )
    cleaned_targets = _clean_required_string_list(
        target_paths,
        "target_paths",
        spec_reasons,
    )
    reviewer = _clean_optional_identifier(
        reviewer_agent,
        "reviewer_agent",
        spec_reasons,
    )

    risk_level = task_manifest.get("risk_level")
    if cleaned_mode is not None and cleaned_mode not in MODES:
        spec_reasons.append(PolicyReason("mode.unsupported", "mode is not supported"))

    if spec_reasons:
        if secret_like_input:
            spec_reasons.append(
                PolicyReason(
                    "secret_like_input.blocked",
                    "secret-like strings are not allowed in K2 policy inputs",
                )
            )
        return PolicyDecision(
            SPEC_BLOCKED,
            task_id,
            tuple(spec_reasons),
            None,
            manifest_hash=manifest_hash,
            policy_input_hash=policy_input_hash,
            external_input_status=external_input_status,
        )

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
        return PolicyDecision(
            SPEC_BLOCKED,
            task_id,
            tuple(spec_reasons),
            None,
            manifest_hash=manifest_hash,
            policy_input_hash=policy_input_hash,
            external_input_status=external_input_status,
        )

    for target in normalized_targets:
        if target is None:
            policy_reasons.append(
                PolicyReason("target_path.unsafe", "target_path is unsafe")
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
                    "target_path is outside file_scope",
                )
            )
        if any(scope and _is_inside(target, scope) for scope in normalized_forbidden):
            policy_reasons.append(
                PolicyReason(
                    "target_path.forbidden_scope",
                    "target_path is inside forbidden_scope",
                )
            )

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

    if secret_like_input:
        policy_reasons.append(
            PolicyReason(
                "secret_like_input.blocked",
                "secret-like strings are not allowed in K2 policy inputs",
            )
        )

    if policy_reasons:
        return PolicyDecision(
            POLICY_BLOCKED,
            task_id,
            tuple(policy_reasons),
            None,
            manifest_hash=manifest_hash,
            policy_input_hash=policy_input_hash,
            external_input_status=external_input_status,
        )

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
    return PolicyDecision(
        POLICY_ALLOWED,
        task_id,
        (),
        route_request,
        manifest_hash=manifest_hash,
        policy_input_hash=policy_input_hash,
        external_input_status=external_input_status,
    )


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


def _clean_required_identifier_list(
    value: Any,
    field_name: str,
    reasons: list[PolicyReason],
) -> list[str]:
    cleaned = _clean_required_string_list(value, field_name, reasons)
    if cleaned and not all(_safe_serialized_identifier(item) for item in cleaned):
        reasons.append(
            PolicyReason(
                f"{field_name}.unsafe",
                f"{field_name} contains an unsafe identifier",
            )
        )
        return []
    return cleaned


def _clean_optional_identifier(
    value: Any,
    field_name: str,
    reasons: list[PolicyReason],
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        reasons.append(
            PolicyReason(
                f"{field_name}.invalid",
                f"{field_name} must be a canonical string when present",
            )
        )
        return None
    if not _safe_serialized_identifier(value):
        reasons.append(
            PolicyReason(
                f"{field_name}.unsafe",
                f"{field_name} contains an unsafe identifier",
            )
        )
        return None
    return value


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
    if _contains_unsafe_unicode(cleaned):
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


def _safe_output_task_id(value: Any) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    if _contains_secret_like_value(value) or _contains_unsafe_unicode(value):
        return None
    return value


def _safe_serialized_identifier(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value)
    return not _contains_unsafe_unicode(normalized)


def _contains_unsafe_unicode(value: str) -> bool:
    return any(unicodedata.category(char).startswith("C") for char in value)


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
        normalized = unicodedata.normalize("NFKC", value)
        return any(pattern.search(normalized) for pattern in SECRET_PATTERNS)
    if isinstance(value, Mapping):
        return any(
            _contains_secret_like_value(item)
            for pair in value.items()
            for item in pair
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_secret_like_value(item) for item in value)
    return False


def _external_input_status(value: Any) -> str:
    if value is None or value == [] or value == {} or value == ():
        return "NOT_PROVIDED"
    return "UNTRUSTED_IGNORED"


def _policy_input_hash(value: Mapping[str, Any], *, secret_like: bool) -> str:
    if secret_like:
        return _hash_json({"policy_inputs": "REDACTED_SECRET_LIKE"})
    return _hash_json(_audit_value(value))


def _audit_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return {"float": repr(value)}
    if isinstance(value, Mapping):
        items = [
            [_audit_value(key), _audit_value(item)]
            for key, item in value.items()
        ]
        return {
            "mapping": sorted(
                items,
                key=lambda item: json.dumps(
                    item[0],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        }
    if isinstance(value, (list, tuple)):
        return [_audit_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_audit_value(item) for item in value]
        return {
            "set": sorted(
                items,
                key=lambda item: json.dumps(
                    item,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        }
    return {"unsupported_type": type(value).__name__}


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


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()
