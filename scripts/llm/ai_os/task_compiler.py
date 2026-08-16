"""Compile human task records into fail-closed AIOS task manifests."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Mapping


SCHEMA = "ai-task.v1"
SPEC_READY = "SPEC_READY"
SPEC_BLOCKED = "SPEC_BLOCKED"
RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "CONSTITUTIONAL"}
NETWORK_POLICIES = {"OFFLINE", "ALLOWLIST", "LIVE_DATA"}

STRING_FIELDS = (
    "task_id",
    "objective",
    "human_owner",
    "reviewer",
    "risk_level",
    "network_policy",
)
LIST_FIELDS = (
    "architecture_block",
    "file_scope",
    "acceptance_tests",
    "approval_gates",
)
OPTIONAL_LIST_FIELDS = (
    "non_goals",
    "executor_candidates",
    "dependencies",
    "authority_docs",
    "forbidden_scope",
    "input_contracts",
    "output_artifacts",
)
MANIFEST_ORDER = (
    "schema",
    "task_id",
    "source_issue",
    "architecture_block",
    "objective",
    "non_goals",
    "human_owner",
    "reviewer",
    "executor_candidates",
    "dependencies",
    "authority_docs",
    "file_scope",
    "forbidden_scope",
    "input_contracts",
    "output_artifacts",
    "acceptance_tests",
    "risk_level",
    "network_policy",
    "budget",
    "approval_gates",
    "created_at",
    "source_hash",
    "manifest_hash",
)

SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class CompileResult:
    status: str
    manifest: dict[str, Any] | None
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "manifest": self.manifest,
            "errors": list(self.errors),
        }


def compile_task_manifest(
    source: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> CompileResult:
    """Return a manifest when the contract is complete, otherwise SPEC_BLOCKED."""

    now = now or datetime.now(timezone.utc)
    errors: list[str] = []
    if not isinstance(source, Mapping):
        return CompileResult(SPEC_BLOCKED, None, ("source must be a mapping",))

    for field in STRING_FIELDS:
        if not _non_empty_string(source.get(field)):
            errors.append(f"{field} must be a non-empty string")
    for field in LIST_FIELDS:
        if not _non_empty_string_list(source.get(field)):
            errors.append(f"{field} must be a non-empty string list")
    for field in OPTIONAL_LIST_FIELDS:
        if field in source and not _string_list_or_empty(source.get(field)):
            errors.append(f"{field} must be a string list when present")

    if source.get("schema", SCHEMA) != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if source.get("risk_level") not in RISK_LEVELS:
        errors.append("risk_level is not supported")
    if source.get("network_policy") not in NETWORK_POLICIES:
        errors.append("network_policy is not supported")

    budget = _normalize_budget(source.get("budget"))
    if isinstance(budget, str):
        errors.append(budget)

    source_issue = source.get("source_issue")
    if source_issue is not None and (
        isinstance(source_issue, bool)
        or not isinstance(source_issue, int)
        or source_issue <= 0
    ):
        errors.append("source_issue must be a positive integer when present")
    created_at = _normalize_created_at(source.get("created_at"), now)
    if isinstance(created_at, str) and created_at.startswith("created_at "):
        errors.append(created_at)

    # governance-mutation: AIOS_K1_TASK_REQUIRED_FIELDS
    if errors:
        return CompileResult(SPEC_BLOCKED, None, tuple(errors))

    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "task_id": source["task_id"].strip(),
        "source_issue": source_issue,
        "architecture_block": _clean_string_list(source["architecture_block"]),
        "objective": source["objective"].strip(),
        "non_goals": _clean_string_list(source.get("non_goals", [])),
        "human_owner": source["human_owner"].strip(),
        "reviewer": source["reviewer"].strip(),
        "executor_candidates": _clean_string_list(
            source.get("executor_candidates", [])
        ),
        "dependencies": _clean_string_list(source.get("dependencies", [])),
        "authority_docs": _clean_string_list(source.get("authority_docs", [])),
        "file_scope": _clean_string_list(source["file_scope"]),
        "forbidden_scope": _clean_string_list(source.get("forbidden_scope", [])),
        "input_contracts": _clean_string_list(source.get("input_contracts", [])),
        "output_artifacts": _clean_string_list(source.get("output_artifacts", [])),
        "acceptance_tests": _clean_string_list(source["acceptance_tests"]),
        "risk_level": source["risk_level"],
        "network_policy": source["network_policy"],
        "budget": budget,
        "approval_gates": _clean_string_list(source["approval_gates"]),
        "created_at": created_at,
        "source_hash": _hash_json(source),
    }
    manifest["manifest_hash"] = _hash_json(manifest)
    ordered = {key: manifest[key] for key in MANIFEST_ORDER}
    return CompileResult(SPEC_READY, ordered, ())


def validate_compiled_manifest(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate one canonical compiler output without reconstructing its source."""

    if not isinstance(manifest, Mapping):
        return ("manifest must be a mapping",)

    candidate = dict(manifest)
    errors: list[str] = []
    missing = [field for field in MANIFEST_ORDER if field not in candidate]
    unexpected = sorted(set(candidate) - set(MANIFEST_ORDER))
    if missing:
        errors.append("manifest missing fields: " + ", ".join(missing))
    if unexpected:
        errors.append("manifest has unexpected fields: " + ", ".join(unexpected))
    if missing or unexpected:
        return tuple(errors)

    for field in STRING_FIELDS:
        value = candidate.get(field)
        if not _non_empty_string(value):
            errors.append(f"{field} must be a non-empty string")
        elif value != value.strip():
            errors.append(f"{field} must be canonical without surrounding whitespace")

    for field in (*LIST_FIELDS, *OPTIONAL_LIST_FIELDS):
        value = candidate.get(field)
        if not isinstance(value, list) or not all(_non_empty_string(item) for item in value):
            errors.append(f"{field} must be a canonical string list")
        elif any(item != item.strip() for item in value):
            errors.append(f"{field} must not contain surrounding whitespace")
    for field in LIST_FIELDS:
        if isinstance(candidate.get(field), list) and not candidate[field]:
            errors.append(f"{field} must be a non-empty string list")

    if candidate.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if candidate.get("risk_level") not in RISK_LEVELS:
        errors.append("risk_level is not supported")
    if candidate.get("network_policy") not in NETWORK_POLICIES:
        errors.append("network_policy is not supported")

    source_issue = candidate.get("source_issue")
    if source_issue is not None and (
        isinstance(source_issue, bool)
        or not isinstance(source_issue, int)
        or source_issue <= 0
    ):
        errors.append("source_issue must be a positive integer when present")

    budget = _normalize_budget(candidate.get("budget"))
    if isinstance(budget, str):
        errors.append(budget)
    elif budget != candidate.get("budget"):
        errors.append("budget must use canonical compiler formatting")

    created_at = _normalize_created_at(candidate.get("created_at"), datetime.now(timezone.utc))
    if isinstance(created_at, str) and created_at.startswith("created_at "):
        errors.append(created_at)
    elif created_at != candidate.get("created_at"):
        errors.append("created_at must use canonical UTC formatting")

    for field in ("source_hash", "manifest_hash"):
        value = candidate.get(field)
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
            errors.append(f"{field} must be a sha256 digest")

    if errors:
        return tuple(errors)

    expected_hash = _hash_json(
        {key: candidate[key] for key in MANIFEST_ORDER if key != "manifest_hash"}
    )
    # governance-mutation: AIOS_K1_CANONICAL_MANIFEST_HASH
    if candidate["manifest_hash"] != expected_hash:
        return ("manifest_hash does not match canonical manifest content",)
    return ()


def _normalize_budget(value: Any) -> dict[str, Any] | str:
    if not isinstance(value, Mapping):
        return "budget must be a mapping"
    max_cny = value.get("max_cny")
    max_minutes = value.get("max_minutes")
    try:
        cost = Decimal(str(max_cny))
    except (InvalidOperation, ValueError):
        return "budget.max_cny must be a non-negative decimal"
    if not cost.is_finite():
        return "budget.max_cny must be finite"
    if cost < 0:
        return "budget.max_cny must be non-negative"
    if (
        isinstance(max_minutes, bool)
        or not isinstance(max_minutes, int)
        or max_minutes <= 0
    ):
        return "budget.max_minutes must be a positive integer"
    return {"max_cny": format(cost, "f"), "max_minutes": max_minutes}


def _normalize_created_at(value: Any, now: datetime) -> str:
    if value is None:
        return now.astimezone(timezone.utc).isoformat()
    if not isinstance(value, str) or not value.strip():
        return "created_at must be a non-empty string when present"
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return "created_at must be a valid ISO-8601 timestamp"
    if parsed.tzinfo is None:
        return "created_at must include timezone"
    return parsed.astimezone(timezone.utc).isoformat()


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _non_empty_string_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        _non_empty_string(item) for item in value
    )


def _string_list_or_empty(value: Any) -> bool:
    return isinstance(value, list) and all(_non_empty_string(item) for item in value)


def _clean_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if _non_empty_string(item)]


def _hash_json(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()
