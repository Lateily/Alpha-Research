#!/usr/bin/env python3
"""Macro OS M0-A contracts and fail-closed validators.

This module defines the boundary between point-in-time macro facts, public
consensus, pre-registered house expectations, and published event outcomes.
It performs no network requests and emits no market or portfolio action.

M0-A validates declared provider/independence identities and timestamp math.
M0-B must still bind those declarations to immutable raw snapshots and an
append-only registration timestamp before either property is production proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
SPEC_DIR = HERE / "specs"
SCHEMA_DIR = HERE / "schemas"
SOURCE_REGISTRY = SPEC_DIR / "source_registry.v1.json"
EVENT_TIERS = SPEC_DIR / "event_tiers.v1.json"

SOURCE_SCHEMA = "ar.macro.source_registry"
TIER_SCHEMA = "ar.macro.event_tiers"
EXPECTATION_SCHEMA = "ar.macro.house_expectation"
EVENT_SCHEMA = "ar.macro.event"
SCHEMA_VERSION = "1.0"

SOURCE_STATUS = {"AVAILABLE_EXISTING", "PLANNED_M0B", "DATA_BLOCKED", "RETIRED"}
EVIDENCE_LEVELS = {"E1", "E2", "E3", "E4"}
VINTAGE_SUPPORT = {
    "FULL",
    "LIMITED",
    "RELEASE_ARCHIVE",
    "RELEASE_SNAPSHOT_REQUIRED",
    "DAILY_HISTORY",
    "NONE",
}
EVENT_STATUS = {
    "SCHEDULED",
    "WAITING_FOR_OFFICIAL",
    "PUBLISHED",
    "DATA_CONFLICT",
    "DATA_BLOCKED",
}
CONSENSUS_STATUS = {"OK", "DATA_CONFLICT", "DATA_BLOCKED"}
SNAPSHOT_DELTAS = {
    "T_MINUS_24H": timedelta(hours=24),
    "T_MINUS_60M": timedelta(minutes=60),
}
GITHUB_REVIEW_RE = re.compile(
    r"^https://github\.com/Lateily/Alpha-Research/pull/[0-9]+#pullrequestreview-[0-9]+$"
)
FORBIDDEN_ACTION_KEYS = {
    "buy",
    "sell",
    "order",
    "position_action",
    "position_size",
    "target_price",
    "trade_instruction",
}
SECRET_KEY_FRAGMENTS = {"token", "secret", "password", "api_key", "webhook_key"}
SOURCE_ROLES = {"OFFICIAL_ACTUAL", "MIRROR_ACTUAL", "VINTAGE_MIRROR", "MARKET_SERIES", "CONSENSUS"}
SOURCE_REGIONS = {"GLOBAL_US", "CHINA", "MULTI_REGION"}
SOURCE_TRANSPORTS = {
    "API",
    "OFFICIAL_RELEASE",
    "OFFICIAL_DATA_PORTAL",
    "OFFICIAL_DOWNLOAD",
    "LICENSED_API",
    "LICENSED_FEED",
}


class ContractError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def source_registry_hash(payload: dict[str, Any]) -> str:
    return content_hash(
        {
            "schema": payload.get("schema"),
            "schema_version": payload.get("schema_version"),
            "policy_version": payload.get("policy_version"),
            "effective_from": payload.get("effective_from"),
            "status": payload.get("status"),
            "coverage_policy": payload.get("coverage_policy"),
            "consensus_policy": payload.get("consensus_policy"),
            "sources": payload.get("sources"),
        }
    )


def event_tiers_hash(payload: dict[str, Any]) -> str:
    return content_hash(
        {
            "schema": payload.get("schema"),
            "schema_version": payload.get("schema_version"),
            "policy_version": payload.get("policy_version"),
            "effective_from": payload.get("effective_from"),
            "status": payload.get("status"),
            "tier_1_policy": payload.get("tier_1_policy"),
            "tolerance_policy_version": payload.get("tolerance_policy_version"),
            "tier_1": payload.get("tier_1"),
            "tier_2_policy": payload.get("tier_2_policy"),
            "tier_2": payload.get("tier_2"),
            "tier_3_policy": payload.get("tier_3_policy"),
        }
    )


def house_expectation_hash(payload: dict[str, Any]) -> str:
    approval_envelope = {
        "expectation_hash",
        "status",
        "approved_by",
        "approval_ref",
        "approval_commit_sha",
    }
    return content_hash(
        {key: value for key, value in payload.items() if key not in approval_envelope}
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def load_json(path: str | Path) -> Any:
    value = Path(path)
    try:
        return json.loads(
            value.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read valid JSON from {value}: {exc}") from exc


def _require(payload: dict[str, Any], fields: Iterable[str], label: str) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise ContractError(f"{label} missing required fields: {missing}")


def _reject_unknown(payload: dict[str, Any], allowed: Iterable[str], label: str) -> None:
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        raise ContractError(f"{label} contains unknown fields: {unknown}")


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ContractError(f"{label} must be a finite number")
    return result


def _iso(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be an ISO-8601 timestamp")
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ContractError(f"{label} must be an ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _reject_forbidden_keys(payload: Any, label: str) -> None:
    found = sorted({key for key in _walk_keys(payload) if key.lower() in FORBIDDEN_ACTION_KEYS})
    if found:
        raise ContractError(f"{label} contains forbidden trade-action fields: {found}")


def validate_source_registry(payload: dict[str, Any], *, verify_hash: bool = True) -> None:
    if not isinstance(payload, dict):
        raise ContractError("source registry must be an object")
    top_fields = (
            "schema",
            "schema_version",
            "policy_version",
            "effective_from",
            "status",
            "coverage_policy",
            "consensus_policy",
            "sources",
            "registry_hash",
    )
    _require(payload, top_fields, "source registry")
    _reject_unknown(payload, top_fields, "source registry")
    if payload["schema"] != SOURCE_SCHEMA or payload["schema_version"] != SCHEMA_VERSION:
        raise ContractError("source registry schema/version mismatch")
    if payload["status"] != "APPROVED_SPEC":
        raise ContractError("source registry status must be APPROVED_SPEC")
    if not isinstance(payload["policy_version"], str) or not payload["policy_version"]:
        raise ContractError("source registry requires policy_version")
    if not isinstance(payload["effective_from"], str) or not re.fullmatch(
        r"[0-9]{8}", payload["effective_from"]
    ):
        raise ContractError("source registry effective_from must be YYYYMMDD")
    coverage = payload["coverage_policy"]
    expected_coverage = {
        "market_series": (10, 0.95),
        "macro_events": (5, 0.90),
        "consensus": (3, 0.80),
    }
    if not isinstance(coverage, dict):
        raise ContractError("coverage_policy must be an object")
    _reject_unknown(coverage, expected_coverage, "coverage_policy")
    for key, (years, minimum) in expected_coverage.items():
        row = coverage.get(key)
        if not isinstance(row, dict):
            raise ContractError(f"coverage_policy missing {key}")
        _reject_unknown(row, ("lookback_years", "minimum_coverage"), f"coverage_policy.{key}")
        if row.get("lookback_years") != years or row.get("minimum_coverage") != minimum:
            raise ContractError(f"coverage_policy {key} differs from approved M0-A decision")

    consensus = payload["consensus_policy"]
    if not isinstance(consensus, dict):
        raise ContractError("consensus_policy must be an object")
    _reject_unknown(
        consensus,
        (
            "minimum_independent_sources",
            "conflict_action",
            "average_conflicting_values",
            "tolerance_scope",
            "unresolved_source_action",
        ),
        "consensus_policy",
    )
    if consensus.get("minimum_independent_sources", 0) < 2:
        raise ContractError("formal consensus requires at least two independent sources")
    if consensus.get("conflict_action") != "DATA_CONFLICT":
        raise ContractError("consensus conflicts must produce DATA_CONFLICT")
    if consensus.get("average_conflicting_values") is not False:
        raise ContractError("conflicting consensus values must not be averaged")
    if consensus.get("tolerance_scope") != "EVENT_TYPE_VERSIONED":
        raise ContractError("consensus tolerance must be event-specific and versioned")

    sources = payload["sources"]
    if not isinstance(sources, list) or not sources:
        raise ContractError("source registry sources must be a non-empty list")
    ids: list[str] = []
    for index, row in enumerate(sources):
        if not isinstance(row, dict):
            raise ContractError(f"source row {index} must be an object")
        row_fields = (
                "source_id",
                "provider",
                "independence_group",
                "credential_env_vars",
                "region",
                "official",
                "evidence_level",
                "roles",
                "transport",
                "status",
                "vintage_support",
                "base_url",
                "series",
        )
        _require(row, row_fields, f"source row {index}")
        _reject_unknown(row, row_fields, f"source row {index}")
        source_id = str(row["source_id"])
        ids.append(source_id)
        if not re.fullmatch(r"[a-z0-9_]+", source_id):
            raise ContractError(f"invalid source_id: {source_id}")
        if not isinstance(row["provider"], str) or not row["provider"].strip():
            raise ContractError(f"source {source_id} requires provider")
        if not isinstance(row["independence_group"], str) or not row["independence_group"]:
            raise ContractError(f"source {source_id} requires independence_group")
        credential_env_vars = row["credential_env_vars"]
        if (
            not isinstance(credential_env_vars, list)
            or len(credential_env_vars) != len(set(credential_env_vars))
            or not all(
                isinstance(name, str)
                and re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
                for name in credential_env_vars
            )
        ):
            raise ContractError(f"source {source_id} has invalid credential_env_vars")
        if row["region"] not in SOURCE_REGIONS:
            raise ContractError(f"invalid source region for {source_id}")
        if not isinstance(row["official"], bool):
            raise ContractError(f"source {source_id} official must be boolean")
        if row["transport"] not in SOURCE_TRANSPORTS:
            raise ContractError(f"invalid source transport for {source_id}")
        if row["status"] not in SOURCE_STATUS:
            raise ContractError(f"invalid source status for {source_id}: {row['status']}")
        if row["evidence_level"] not in EVIDENCE_LEVELS:
            raise ContractError(f"invalid evidence level for {source_id}")
        if row["vintage_support"] not in VINTAGE_SUPPORT:
            raise ContractError(f"invalid vintage support for {source_id}")
        if row["official"] is True and row["evidence_level"] != "E1":
            raise ContractError(f"official source {source_id} must be E1")
        roles = row["roles"]
        if (
            not isinstance(roles, list)
            or not roles
            or len(roles) != len(set(roles))
            or not set(roles).issubset(SOURCE_ROLES)
        ):
            raise ContractError(f"source {source_id} has invalid roles")
        if row["official"] is True and "OFFICIAL_ACTUAL" not in roles:
            raise ContractError(f"official source {source_id} must declare OFFICIAL_ACTUAL role")
        if "OFFICIAL_ACTUAL" in roles and row["official"] is not True:
            raise ContractError(f"non-official source {source_id} cannot declare OFFICIAL_ACTUAL")
        if not isinstance(row["base_url"], str) or not row["base_url"].startswith("https://"):
            raise ContractError(f"source {source_id} must use an https base_url")
        if (
            not isinstance(row["series"], list)
            or not row["series"]
            or len(row["series"]) != len(set(row["series"]))
            or not all(isinstance(series, str) and series for series in row["series"])
        ):
            raise ContractError(f"source {source_id} must declare series")
        secret_fields = {
            key for key in _walk_keys(row) if any(fragment in key.lower() for fragment in SECRET_KEY_FRAGMENTS)
        }
        if secret_fields:
            raise ContractError(f"source {source_id} contains secret-like fields: {sorted(secret_fields)}")
    if len(ids) != len(set(ids)):
        raise ContractError("source registry contains duplicate source_id")
    if verify_hash and payload["registry_hash"] != source_registry_hash(payload):
        raise ContractError("source registry hash mismatch")


def source_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    validate_source_registry(payload)
    return {row["source_id"]: row for row in payload["sources"]}


def validate_event_tiers(
    payload: dict[str, Any], sources: dict[str, Any], *, verify_hash: bool = True
) -> None:
    if not isinstance(payload, dict):
        raise ContractError("event tiers must be an object")
    top_fields = (
            "schema",
            "schema_version",
            "policy_version",
            "effective_from",
            "status",
            "tier_1_policy",
            "tolerance_policy_version",
            "tier_1",
            "tier_2_policy",
            "tier_2",
            "tier_3_policy",
            "registry_hash",
    )
    _require(payload, top_fields, "event tiers")
    _reject_unknown(payload, top_fields, "event tiers")
    if payload["schema"] != TIER_SCHEMA or payload["schema_version"] != SCHEMA_VERSION:
        raise ContractError("event tiers schema/version mismatch")
    if payload["status"] != "APPROVED_SPEC":
        raise ContractError("event tiers status must be APPROVED_SPEC")
    if not isinstance(payload["policy_version"], str) or not payload["policy_version"]:
        raise ContractError("event tiers require policy_version")
    if not isinstance(payload["effective_from"], str) or not re.fullmatch(
        r"[0-9]{8}", payload["effective_from"]
    ):
        raise ContractError("event tiers effective_from must be YYYYMMDD")
    if not isinstance(payload["tolerance_policy_version"], str) or not payload[
        "tolerance_policy_version"
    ]:
        raise ContractError("event tiers require tolerance_policy_version")
    index = source_index(sources)
    policy = payload["tier_1_policy"]
    _reject_unknown(
        policy,
        (
            "market_consensus_required",
            "house_expectation_required",
            "expectation_snapshots",
            "event_evaluation_horizons",
            "regime_evaluation_horizons",
        ),
        "tier_1_policy",
    )
    if policy.get("market_consensus_required") is not True:
        raise ContractError("tier-1 events require market consensus")
    if policy.get("house_expectation_required") is not True:
        raise ContractError("tier-1 events require house expectations")
    if policy.get("expectation_snapshots") != ["T_MINUS_24H", "T_MINUS_60M"]:
        raise ContractError("tier-1 expectations require T-24h and T-60m snapshots")
    if policy.get("event_evaluation_horizons") != ["M30", "CLOSE", "T1", "T5"]:
        raise ContractError("tier-1 event evaluation horizons differ from approved policy")
    if policy.get("regime_evaluation_horizons") != ["T20", "T60"]:
        raise ContractError("regime evaluation horizons differ from approved policy")

    for key in ("tier_2_policy", "tier_3_policy"):
        if not isinstance(payload[key], dict):
            raise ContractError(f"{key} must be an object")
        _reject_unknown(
            payload[key],
            ("market_consensus_required", "house_expectation_required", "usage"),
            key,
        )
    if payload["tier_2_policy"].get("market_consensus_required") is not True:
        raise ContractError("tier-2 events require market consensus")
    if payload["tier_2_policy"].get("house_expectation_required") is not False:
        raise ContractError("tier-2 events must not require house expectations")
    if payload["tier_3_policy"].get("market_consensus_required") is not False:
        raise ContractError("tier-3 events must not require market consensus")
    if payload["tier_3_policy"].get("house_expectation_required") is not False:
        raise ContractError("tier-3 events must not require house expectations")

    event_types: list[str] = []
    for tier_name in ("tier_1", "tier_2"):
        rows = payload[tier_name]
        if not isinstance(rows, list) or not rows:
            raise ContractError(f"{tier_name} must be a non-empty list")
        for row in rows:
            row_fields = (
                    "event_type",
                    "region",
                    "name_zh",
                    "actual_source_ids",
                    "actual_series",
                    "tolerance_status",
                    "consensus_tolerance",
            )
            _require(row, row_fields, f"{tier_name} row")
            _reject_unknown(row, row_fields, f"{tier_name} row")
            event_type = str(row["event_type"])
            event_types.append(event_type)
            if not re.fullmatch(r"[A-Z0-9_]+", event_type):
                raise ContractError(f"invalid event_type: {event_type}")
            if row["region"] not in {"GLOBAL_US", "CHINA"}:
                raise ContractError(f"{event_type} has invalid region")
            refs = row["actual_source_ids"]
            if not isinstance(row["actual_series"], str) or not row["actual_series"]:
                raise ContractError(f"{event_type} requires actual_series")
            if not isinstance(refs, list) or not refs or len(refs) != len(set(refs)):
                raise ContractError(f"{event_type} requires at least one actual source")
            for source_id in refs:
                source = index.get(source_id)
                if not source:
                    raise ContractError(f"{event_type} references unknown source {source_id}")
                if source["official"] is not True or source["evidence_level"] != "E1":
                    raise ContractError(
                        f"{event_type} actual source {source_id} must be official E1"
                    )
                if "OFFICIAL_ACTUAL" not in source["roles"]:
                    raise ContractError(
                        f"{event_type} actual source {source_id} lacks OFFICIAL_ACTUAL role"
                    )
                if source["region"] not in {row["region"], "MULTI_REGION"}:
                    raise ContractError(
                        f"{event_type} actual source {source_id} has incompatible region"
                    )
                if row["actual_series"] not in source["series"]:
                    raise ContractError(
                        f"{event_type} actual_series is absent from source {source_id}"
                    )
            tolerance_status = row["tolerance_status"]
            tolerance = row["consensus_tolerance"]
            if tolerance_status == "CALIBRATING":
                if tolerance is not None:
                    raise ContractError(f"{event_type} calibrating tolerance must be null")
            elif tolerance_status == "ACTIVE":
                if _number(tolerance, f"{event_type}.consensus_tolerance") < 0:
                    raise ContractError(f"{event_type} tolerance cannot be negative")
            else:
                raise ContractError(f"{event_type} invalid tolerance_status")
    if len(event_types) != len(set(event_types)):
        raise ContractError("event tiers contain duplicate event_type")
    if verify_hash and payload["registry_hash"] != event_tiers_hash(payload):
        raise ContractError("event tiers hash mismatch")


def tier_1_index(payload: dict[str, Any], sources: dict[str, Any]) -> dict[str, dict[str, Any]]:
    validate_event_tiers(payload, sources)
    return {row["event_type"]: row for row in payload["tier_1"]}


def event_index(payload: dict[str, Any], sources: dict[str, Any]) -> dict[str, tuple[int, dict[str, Any]]]:
    validate_event_tiers(payload, sources)
    return {
        row["event_type"]: (tier, row)
        for tier, key in ((1, "tier_1"), (2, "tier_2"))
        for row in payload[key]
    }


def validate_house_expectation(
    payload: dict[str, Any], tiers: dict[str, Any], sources: dict[str, Any]
) -> None:
    if not isinstance(payload, dict):
        raise ContractError("house expectation must be an object")
    _reject_forbidden_keys(payload, "house expectation")
    top_fields = (
            "schema",
            "schema_version",
            "expectation_id",
            "event_id",
            "event_type",
            "event_scheduled_at",
            "snapshot_type",
            "registered_at",
            "status",
            "forecast",
            "surprise_bucket",
            "transmission_hypotheses",
            "formula_version",
            "submitted_by",
            "approved_by",
            "approval_ref",
            "approval_commit_sha",
            "expectation_hash",
    )
    _require(payload, top_fields, "house expectation")
    _reject_unknown(payload, top_fields, "house expectation")
    if payload["schema"] != EXPECTATION_SCHEMA or payload["schema_version"] != SCHEMA_VERSION:
        raise ContractError("house expectation schema/version mismatch")
    if payload["expectation_hash"] != house_expectation_hash(payload):
        raise ContractError("house expectation hash mismatch")
    tier_rows = tier_1_index(tiers, sources)
    if payload["event_type"] not in tier_rows:
        raise ContractError("house expectation is only formal for registered tier-1 events")
    snapshot = payload["snapshot_type"]
    if snapshot not in SNAPSHOT_DELTAS:
        raise ContractError(f"invalid expectation snapshot_type: {snapshot}")
    scheduled = _iso(payload["event_scheduled_at"], "event_scheduled_at")
    registered = _iso(payload["registered_at"], "registered_at")
    cutoff = scheduled - SNAPSHOT_DELTAS[snapshot]
    if registered > cutoff:
        raise ContractError(
            f"{snapshot} expectation registered after cutoff: {registered.isoformat()} > {cutoff.isoformat()}"
        )
    status = payload["status"]
    if status not in {"DRAFT", "APPROVED"}:
        raise ContractError(f"invalid expectation status: {status}")
    if status == "APPROVED":
        if payload["approved_by"] != "Junyan":
            raise ContractError("formal house expectation must be approved by Junyan")
        if not isinstance(payload["approval_ref"], str) or not GITHUB_REVIEW_RE.fullmatch(
            payload["approval_ref"]
        ):
            raise ContractError(
                "approved house expectation requires a GitHub pull-request review URL"
            )
        if not isinstance(payload["approval_commit_sha"], str) or not re.fullmatch(
            r"[0-9a-f]{40}", payload["approval_commit_sha"]
        ):
            raise ContractError("approved house expectation requires approval_commit_sha")
    else:
        if any(
            payload[field] is not None
            for field in ("approved_by", "approval_ref", "approval_commit_sha")
        ):
            raise ContractError("draft expectation cannot carry formal approval")

    forecast = payload["forecast"]
    if not isinstance(forecast, dict):
        raise ContractError("forecast must be an object")
    _require(forecast, ("low", "high", "unit"), "forecast")
    _reject_unknown(forecast, ("low", "high", "unit"), "forecast")
    low = _number(forecast["low"], "forecast.low")
    high = _number(forecast["high"], "forecast.high")
    if low > high:
        raise ContractError("forecast.low cannot exceed forecast.high")
    if not isinstance(payload["surprise_bucket"], str) or not payload["surprise_bucket"]:
        raise ContractError("surprise_bucket must be a non-empty string")
    for field in ("formula_version", "submitted_by"):
        if not isinstance(payload[field], str) or not payload[field]:
            raise ContractError(f"{field} must be a non-empty string")
    hypotheses = payload["transmission_hypotheses"]
    if not isinstance(hypotheses, list) or not hypotheses:
        raise ContractError("at least one transmission hypothesis is required")
    for index, row in enumerate(hypotheses):
        if not isinstance(row, dict):
            raise ContractError(f"transmission hypothesis {index} must be an object")
        hypothesis_fields = (
            "factor",
            "condition",
            "expected_effect",
            "wrong_if",
            "evidence_refs",
        )
        _require(row, hypothesis_fields, f"transmission hypothesis {index}")
        _reject_unknown(row, hypothesis_fields, f"transmission hypothesis {index}")
        if not row["condition"] or not row["wrong_if"]:
            raise ContractError(f"transmission hypothesis {index} needs condition and wrong_if")
        if not isinstance(row["expected_effect"], str) or not row["expected_effect"]:
            raise ContractError(f"transmission hypothesis {index} needs expected_effect")
        if not isinstance(row["evidence_refs"], list) or not all(
            isinstance(ref, str) and ref for ref in row["evidence_refs"]
        ):
            raise ContractError(
                f"transmission hypothesis {index} evidence_refs must contain strings"
            )


def _consensus_values(consensus: dict[str, Any]) -> list[dict[str, Any]]:
    rows = consensus.get("source_values")
    if not isinstance(rows, list):
        raise ContractError("market_consensus.source_values must be a list")
    return rows


def validate_macro_event(payload: dict[str, Any], tiers: dict[str, Any], sources: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ContractError("macro event must be an object")
    _reject_forbidden_keys(payload, "macro event")
    top_fields = (
            "schema",
            "schema_version",
            "event_id",
            "event_type",
            "tier",
            "region",
            "scheduled_at",
            "published_at",
            "status",
            "actual",
            "actual_source_id",
            "unit",
            "previous",
            "previous_revised",
            "market_consensus",
            "house_expectations",
            "surprises",
            "source_refs",
            "formula_version",
            "run_id",
            "generated_at",
    )
    _require(payload, top_fields, "macro event")
    _reject_unknown(payload, top_fields, "macro event")
    if payload["schema"] != EVENT_SCHEMA or payload["schema_version"] != SCHEMA_VERSION:
        raise ContractError("macro event schema/version mismatch")
    if payload["status"] not in EVENT_STATUS:
        raise ContractError(f"invalid macro event status: {payload['status']}")
    if isinstance(payload["tier"], bool) or payload["tier"] not in {1, 2, 3}:
        raise ContractError("macro event tier must be 1, 2, or 3")
    if payload["region"] not in {"GLOBAL_US", "CHINA"}:
        raise ContractError("macro event has invalid region")
    if not isinstance(payload["unit"], str) or not payload["unit"]:
        raise ContractError("macro event unit must be a non-empty string")
    for field in ("formula_version", "run_id"):
        if not isinstance(payload[field], str) or not payload[field]:
            raise ContractError(f"macro event {field} must be a non-empty string")
    for field in ("previous", "previous_revised"):
        if payload[field] is not None:
            _number(payload[field], field)
    _iso(payload["scheduled_at"], "scheduled_at")
    generated_at = _iso(payload["generated_at"], "generated_at")
    source_rows = source_index(sources)
    registered_events = event_index(tiers, sources)
    event_type = payload["event_type"]
    tier = payload["tier"]
    if tier in {1, 2}:
        registered = registered_events.get(event_type)
        if not registered or registered[0] != tier:
            raise ContractError(f"unknown tier-{tier} event_type: {event_type}")
        if payload["region"] != registered[1]["region"]:
            raise ContractError("macro event region differs from event registry")
    refs = payload["source_refs"]
    if not isinstance(refs, list):
        raise ContractError("source_refs must be a list")
    for index, ref in enumerate(refs):
        if not isinstance(ref, dict):
            raise ContractError(f"source_ref {index} must be an object")
        ref_fields = ("source_id", "locator", "snapshot_hash", "as_of", "fetched_at")
        _require(ref, ref_fields, f"source_ref {index}")
        _reject_unknown(ref, ref_fields, f"source_ref {index}")
        if ref["source_id"] not in source_rows:
            raise ContractError(f"source_ref {index} references unknown source")
        if source_rows[ref["source_id"]]["status"] != "AVAILABLE_EXISTING":
            raise ContractError(f"source_ref {index} source is not available")
        if not isinstance(ref["locator"], str) or not ref["locator"]:
            raise ContractError(f"source_ref {index} locator must be non-empty")
        if not isinstance(ref["snapshot_hash"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", ref["snapshot_hash"]
        ):
            raise ContractError(f"source_ref {index} snapshot_hash is invalid")
        as_of = _iso(ref["as_of"], f"source_ref {index}.as_of")
        fetched_at = _iso(ref["fetched_at"], f"source_ref {index}.fetched_at")
        if fetched_at < as_of:
            raise ContractError(f"source_ref {index} fetched_at precedes as_of")
        if generated_at < fetched_at:
            raise ContractError(f"source_ref {index} was fetched after event generation")
    ref_keys = [(ref["source_id"], ref["locator"], ref["snapshot_hash"]) for ref in refs]
    if len(ref_keys) != len(set(ref_keys)):
        raise ContractError("source_refs contain duplicate provenance rows")

    consensus = payload["market_consensus"]
    if not isinstance(consensus, dict) or consensus.get("status") not in CONSENSUS_STATUS:
        raise ContractError("market_consensus has invalid status")
    _reject_unknown(
        consensus,
        ("status", "value", "tolerance", "tolerance_version", "source_values"),
        "market_consensus",
    )
    consensus_rows = _consensus_values(consensus)
    consensus_sources: list[dict[str, Any]] = []
    for index, row in enumerate(consensus_rows):
        if not isinstance(row, dict):
            raise ContractError(f"market_consensus.source_values[{index}] must be an object")
        row_fields = ("source_id", "value", "snapshot_hash", "as_of", "fetched_at")
        _require(row, row_fields, f"market_consensus.source_values[{index}]")
        _reject_unknown(row, row_fields, f"market_consensus.source_values[{index}]")
        source = source_rows.get(str(row["source_id"]))
        if not source:
            raise ContractError(f"market consensus references unknown source {row['source_id']}")
        if "CONSENSUS" not in source["roles"]:
            raise ContractError(f"market consensus source {row['source_id']} lacks CONSENSUS role")
        if source["status"] != "AVAILABLE_EXISTING":
            raise ContractError(f"market consensus source {row['source_id']} is not available")
        _number(row["value"], f"market_consensus.source_values[{index}].value")
        if not any(
            ref["source_id"] == row["source_id"]
            and ref["snapshot_hash"] == row["snapshot_hash"]
            for ref in refs
        ):
            raise ContractError(
                f"market consensus source {row['source_id']} lacks matching source_ref provenance"
            )
        if not isinstance(row["snapshot_hash"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", row["snapshot_hash"]
        ):
            raise ContractError(
                f"market_consensus.source_values[{index}] snapshot_hash is invalid"
            )
        as_of = _iso(row["as_of"], f"market_consensus.source_values[{index}].as_of")
        fetched_at = _iso(
            row["fetched_at"], f"market_consensus.source_values[{index}].fetched_at"
        )
        if fetched_at < as_of:
            raise ContractError(
                f"market_consensus.source_values[{index}] fetched_at precedes as_of"
            )
        consensus_sources.append(source)
    if consensus["status"] in {"OK", "DATA_CONFLICT"}:
        unique_groups = {source["independence_group"] for source in consensus_sources}
        unique_providers = {source["provider"] for source in consensus_sources}
        if len(unique_groups) < 2 or len(unique_providers) < 2:
            raise ContractError(
                "formal market consensus requires two independent providers and groups"
            )
    if consensus["status"] == "OK":
        if tier in {1, 2}:
            tier_row = registered_events[event_type][1]
            if tier_row["tolerance_status"] != "ACTIVE":
                raise ContractError("formal consensus cannot be OK while tolerance is calibrating")
            if consensus.get("tolerance") != tier_row["consensus_tolerance"]:
                raise ContractError("market consensus tolerance differs from approved event tolerance")
            if consensus.get("tolerance_version") != tiers["tolerance_policy_version"]:
                raise ContractError("market consensus tolerance_version mismatch")
        tolerance = _number(consensus.get("tolerance"), "market_consensus.tolerance")
        values = [_number(row.get("value"), "market_consensus.source_values.value") for row in consensus_rows]
        if max(values) - min(values) > tolerance:
            raise ContractError("consensus sources exceed tolerance but status is OK")
        value = _number(consensus.get("value"), "market_consensus.value")
        if value < min(values) or value > max(values):
            raise ContractError("formal consensus value must lie within source values")
    elif consensus["status"] == "DATA_CONFLICT":
        if consensus.get("value") is not None:
            raise ContractError("DATA_CONFLICT consensus must not average to a formal value")
    else:
        if consensus.get("value") is not None:
            raise ContractError("DATA_BLOCKED consensus cannot carry a formal value")
        if consensus.get("tolerance") is not None or consensus.get("tolerance_version") is not None:
            raise ContractError("DATA_BLOCKED consensus cannot carry active tolerance fields")

    published = payload["status"] == "PUBLISHED"
    if published:
        _number(payload["actual"], "actual")
        published_at = _iso(payload["published_at"], "published_at")
        if generated_at < published_at:
            raise ContractError("generated_at cannot precede published_at")
        allowed_actual_sources = (
            set(registered_events[event_type][1]["actual_source_ids"])
            if tier in {1, 2}
            else {
                source_id
                for source_id, source in source_rows.items()
                if source["official"] is True and source["evidence_level"] == "E1"
            }
        )
        actual_source_id = payload["actual_source_id"]
        if actual_source_id not in allowed_actual_sources:
            raise ContractError("actual_source_id is not approved for this event type")
        official_actual_refs = [
            ref
            for ref in refs
            if ref["source_id"] == actual_source_id
            if source_rows[ref["source_id"]]["official"] is True
            and source_rows[ref["source_id"]]["evidence_level"] == "E1"
            and "OFFICIAL_ACTUAL" in source_rows[ref["source_id"]]["roles"]
        ]
        if not official_actual_refs:
            raise ContractError("published macro event requires an official E1 actual source")
        if tier == 1:
            if not isinstance(payload["house_expectations"], list):
                raise ContractError("house_expectations must be a list")
            for index, ref in enumerate(payload["house_expectations"]):
                if not isinstance(ref, dict):
                    raise ContractError(f"house_expectations[{index}] must be an object")
                expectation_ref_fields = (
                        "expectation_id",
                        "event_id",
                        "snapshot_type",
                        "status",
                        "expectation_hash",
                        "approval_ref",
                        "approval_commit_sha",
                )
                _require(ref, expectation_ref_fields, f"house_expectations[{index}]")
                _reject_unknown(
                    ref, expectation_ref_fields, f"house_expectations[{index}]"
                )
                if ref["event_id"] != payload["event_id"]:
                    raise ContractError("house expectation reference belongs to a different event")
                if ref["status"] != "APPROVED":
                    raise ContractError("tier-1 event can reference only approved expectations")
                if not isinstance(ref["expectation_hash"], str) or not re.fullmatch(
                    r"[0-9a-f]{64}", ref["expectation_hash"]
                ):
                    raise ContractError("house expectation reference has invalid hash")
                if not isinstance(ref["approval_ref"], str) or not GITHUB_REVIEW_RE.fullmatch(
                    ref["approval_ref"]
                ):
                    raise ContractError("house expectation reference lacks approved review")
                if not isinstance(ref["approval_commit_sha"], str) or not re.fullmatch(
                    r"[0-9a-f]{40}", ref["approval_commit_sha"]
                ):
                    raise ContractError("house expectation reference lacks approved commit")
            expectation_types = {
                ref.get("snapshot_type")
                for ref in payload["house_expectations"]
                if isinstance(ref, dict) and ref.get("status") == "APPROVED"
            }
            expectation_ids = {ref["expectation_id"] for ref in payload["house_expectations"]}
            if (
                expectation_types != set(SNAPSHOT_DELTAS)
                or len(payload["house_expectations"]) != 2
                or len(expectation_ids) != 2
            ):
                raise ContractError("published tier-1 event requires approved T-24h and T-60m expectations")
            surprises = payload["surprises"]
            if not isinstance(surprises, dict) or not {
                "vs_market",
                "vs_house_t24",
                "vs_house_t60",
            }.issubset(surprises):
                raise ContractError("published tier-1 event requires all three surprise comparisons")
    else:
        if payload["published_at"] is not None:
            raise ContractError("unpublished event cannot carry published_at")
        if payload["actual"] is not None:
            raise ContractError("unpublished event cannot carry actual")
        if payload["actual_source_id"] is not None:
            raise ContractError("unpublished event cannot carry actual_source_id")
        if payload["surprises"] != {}:
            raise ContractError("unpublished event cannot carry surprise results")


def validate_default_specs() -> tuple[dict[str, Any], dict[str, Any]]:
    sources = load_json(SOURCE_REGISTRY)
    tiers = load_json(EVENT_TIERS)
    validate_source_registry(sources)
    validate_event_tiers(tiers, sources)
    schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
    expected_schemas = {
        "consensus_gate.schema.json",
        "event_tiers.schema.json",
        "house_expectation.schema.json",
        "industry_macro_sensitivity.schema.json",
        "m0b3_run_manifest.schema.json",
        "m1a_run_manifest.schema.json",
        "m1b_run_manifest.schema.json",
        "m1c_run_manifest.schema.json",
        "macro_event.schema.json",
        "macro_events.schema.json",
        "macro_panel.schema.json",
        "macro_risk_gate.schema.json",
        "macro_state.schema.json",
        "market_features.schema.json",
        "portfolio_macro_exposure.schema.json",
        "release_discovery.schema.json",
        "release_discovery_status.schema.json",
        "release_calendar.schema.json",
        "scheduler_status.schema.json",
        "source_registry.schema.json",
        "state_rules.schema.json",
    }
    if {path.name for path in schema_files} != expected_schemas:
        raise ContractError(
            "macro schema set mismatch: "
            f"expected {sorted(expected_schemas)}, found {[path.name for path in schema_files]}"
        )
    for path in schema_files:
        schema = load_json(path)
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise ContractError(f"{path.name} is not a draft-2020-12 schema")
        if not schema.get("required"):
            raise ContractError(f"{path.name} has no required list")
    return sources, tiers


def _valid_expectation() -> dict[str, Any]:
    payload = {
        "schema": EXPECTATION_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "expectation_id": "US_CPI_20260812_T24",
        "event_id": "US_CPI_20260812",
        "event_type": "US_CPI",
        "event_scheduled_at": "2026-08-12T12:30:00Z",
        "snapshot_type": "T_MINUS_24H",
        "registered_at": "2026-08-11T12:00:00Z",
        "status": "APPROVED",
        "forecast": {"low": 0.2, "high": 0.3, "unit": "pct_mom"},
        "surprise_bucket": "IN_LINE_TO_SLIGHTLY_HOT",
        "transmission_hypotheses": [
            {
                "factor": "US_RATES",
                "condition": "actual above market consensus",
                "expected_effect": "2Y_UP_PRESSURE",
                "wrong_if": "2Y yield closes lower with credit stable",
                "evidence_refs": ["research://macro/us_cpi/20260812"],
            }
        ],
        "formula_version": "house-expectation/v1",
        "submitted_by": "Macro Agent",
        "approved_by": "Junyan",
        "approval_ref": (
            "https://github.com/Lateily/Alpha-Research/pull/999"
            "#pullrequestreview-123456789"
        ),
        "approval_commit_sha": "a" * 40,
        "expectation_hash": "",
    }
    payload["expectation_hash"] = house_expectation_hash(payload)
    return payload


def selftest() -> None:
    sources, tiers = validate_default_specs()
    checks: list[tuple[str, bool]] = []

    def ck(label: str, condition: bool) -> None:
        checks.append((label, bool(condition)))

    expectation = _valid_expectation()
    validate_house_expectation(expectation, tiers, sources)
    ck("approved T-24h expectation validates", True)

    late = json.loads(json.dumps(expectation))
    late["registered_at"] = "2026-08-12T12:29:00Z"
    late["expectation_hash"] = house_expectation_hash(late)
    try:
        validate_house_expectation(late, tiers, sources)
        ck("late T-24h expectation is rejected", False)
    except ContractError:
        ck("late T-24h expectation is rejected", True)

    damaged = json.loads(json.dumps(sources))
    damaged["registry_hash"] = "0" * 64
    try:
        validate_source_registry(damaged)
        ck("source registry hash mismatch is rejected", False)
    except ContractError:
        ck("source registry hash mismatch is rejected", True)

    for label, ok in checks:
        print(("PASS" if ok else "FAIL"), label)
    if not all(ok for _, ok in checks):
        raise SystemExit(1)
    print(f"ALL MACRO M0-A SELFTESTS PASS ({len(checks)}/{len(checks)})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--validate-specs", action="store_true")
    parser.add_argument("--print-spec-hashes", action="store_true")
    args = parser.parse_args(argv)
    if args.print_spec_hashes:
        sources = load_json(SOURCE_REGISTRY)
        tiers = load_json(EVENT_TIERS)
        print(json.dumps({
            "source_registry": source_registry_hash(sources),
            "event_tiers": event_tiers_hash(tiers),
        }, indent=2))
        return 0
    if args.selftest:
        selftest()
        return 0
    if args.validate_specs:
        validate_default_specs()
        print("MACRO M0-A SPECS VALID")
        return 0
    parser.error("choose --selftest, --validate-specs, or --print-spec-hashes")
    return 2


if __name__ == "__main__":
    sys.exit(main())
