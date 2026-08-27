#!/usr/bin/env python3
"""Build one offline, evidence-bound U4 pre-decision packet.

The packet shows Junyan which same-day semiconductor rows are reviewable and
why every other row is blocked. It never selects a security, creates a paper
order, or writes production state.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from . import closure_experiment as closure
    from . import feature_store as feature_store
    from . import funnel_dag as dag
    from . import funnel_pipeline as funnel
    from . import nightly_funnel as nightly_funnel
    from .security_registry import _atomic_write_json
except ImportError:  # Direct CLI execution adds this directory to sys.path.
    import closure_experiment as closure
    import feature_store as feature_store
    import funnel_dag as dag
    import funnel_pipeline as funnel
    import nightly_funnel as nightly_funnel
    from security_registry import _atomic_write_json


SCHEMA = "ar.u4_pre_decision_packet.v0"
SCHEMA_VERSION = "0.1"
DIAGNOSTIC_TOOL = "u4_pre_decision.py"
DIAGNOSTIC_VERSION = "0.1"
RUNTIME_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_METHOD_VERSION = "RESEARCH_CLOSED_LOOP_V1"
DEFAULT_INDUSTRY = "半导体"
DISCLAIMER = "不是买卖指令；研究信号，human executes."
UNAVAILABLE = "UNAVAILABLE"
SOURCE_FIELDS = {
    "same_day_bundle_ref",
    "same_day_bundle_hash",
    "u2_candidate_pool_hash",
    "u3_battery_hash",
    "feature_store_health_ref",
    "feature_store_health_hash",
    "funnel_health_ref",
    "funnel_health_hash",
    "stage_receipts_hash",
    "diagnostic_report_ref",
    "diagnostic_report_hash",
}
PACKET_FIELDS = {
    "schema",
    "packet_version",
    "status",
    "as_of",
    "generated_at",
    "method_version",
    "source_refs",
    "source_publication",
    "diagnostic",
    "candidate_rows",
    "packet_summary",
    "selection_boundary",
    "authority",
    "packet_hash",
}
CANDIDATE_FIELDS = {
    "ts_code",
    "display_name",
    "candidate_status",
    "method_version",
    "cohort_id",
    "cohort_identity_state",
    "causal_cluster_id",
    "causal_cluster_identity_state",
    "u2_candidate_row_hash",
    "u3_battery_row_hash",
    "positive_channels",
    "red_flag_channels",
    "blocked_reasons",
    "missing_evidence",
    "quality_status",
    "allowed_for_u4_packet",
    "question_for_junyan",
}
CHANNEL_MAP = {
    "PRICE_VOLUME": "PRICE_VOLUME",
    "FUND_FLOW_CHIPS": "MONEYFLOW_CHIPS",
    "FUNDAMENTAL_VALUATION": "FUNDAMENTAL_VALUATION",
    "INDUSTRY_VALUE_CHAIN": "INDUSTRY_CHAIN",
    "MACRO_CROSS_ASSET": "MACRO_CONTEXT",
}
DAILY_SOURCES = ("moneyflow_dc", "cyq_perf")
QUARTERLY_SOURCES = ("fina_indicator_pit",)
SOURCE_STATUS = {"PUBLISHED", "PENDING", "STALE", "DATA_BLOCKED"}
PACKET_STATUS = {
    "READY_FOR_JUNYAN_REVIEW",
    "BLOCKED_BEFORE_U4",
    "SOURCE_PUBLICATION_PENDING",
    "DATA_BLOCKED",
    "REVISE_REQUIRED",
}
ROW_BLOCKERS = {
    "U3_BATTERY_INCOMPLETE",
    "E1_RED_FLAG_ACTIVE",
    "NO_POSITIVE_CHANNEL",
    "RANDOM_CONTROL_NOT_SELECTABLE",
    "QUALITY_GATE_INCOMPLETE",
    "RECEIPT_SELF_REPORT_MISMATCH",
    "DIAGNOSTIC_EVIDENCE_HASH_MISMATCH",
}
CANDIDATE_STATUS = {
    "MAIN_CHANNEL",
    "RESERVED_SLOW_BULL",
    "RESERVED_CONTRARIAN",
    "RANDOM_CONTROL",
}
POSITIVE_CHANNELS = set(CHANNEL_MAP.values()) | {"OTHER"}
RED_FLAG_CHANNELS = {"E1_EVENT", "FINANCIAL_RED_FLAG", "DISCLOSURE_RED_FLAG", "OTHER"}
DIAGNOSTIC_FIELDS = {
    "tool", "tool_version", "evidence_rows_checked",
    "evidence_rows_hash_verified", "receipt_self_report_checked",
    "red_flag_only_rows", "positive_channel_rows", "u3_complete_rows",
    "u4_ready_rows", "blocker_codes",
}
SUMMARY_FIELDS = {
    "candidate_count", "allowed_for_review_count", "blocked_count",
    "red_flag_count", "data_blocked_count", "same_day_hash",
}


class PreDecisionError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PreDecisionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise PreDecisionError(f"JSON input must be one regular file: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise PreDecisionError(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PreDecisionError(f"JSON root must be an object: {path}")
    return value


def _sha(value: Any) -> str:
    return f"sha256:{funnel._hash(value)}"


def _without_hash(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "packet_hash"}


def _require_exact(value: Mapping[str, Any], fields: set[str], label: str) -> None:
    if set(value) != fields:
        raise PreDecisionError(f"{label} fields are not exact")


def _source_ref(path: Path, fallback: str) -> str:
    parts = path.resolve().parts
    if "data_history" in parts:
        index = parts.index("data_history")
        return Path(*parts[index:]).as_posix()
    if "public" in parts:
        index = parts.index("public")
        return Path(*parts[index:]).as_posix()
    return fallback


def _publication_status(sources: Mapping[str, Any], names: Sequence[str]) -> tuple[str, list[str]]:
    missing: list[str] = []
    statuses: list[str] = []
    for name in names:
        row = sources.get(name)
        if not isinstance(row, Mapping):
            missing.append(name)
            statuses.append("DATA_BLOCKED")
            continue
        status = str(row.get("status") or "")
        statuses.append(status)
        if status != "COMPLETE":
            missing.append(name)
    if any(status in {"PENDING", "SOURCE_PUBLICATION_PENDING"} for status in statuses):
        return "PENDING", sorted(missing)
    if any(status == "STALE" for status in statuses):
        return "STALE", sorted(missing)
    if any(status != "COMPLETE" for status in statuses):
        return "DATA_BLOCKED", sorted(missing)
    return "PUBLISHED", []


def _source_publication(
    feature_health: Mapping[str, Any], bundle: Mapping[str, Any], as_of: str,
) -> tuple[dict[str, Any], Any]:
    if (
        feature_health.get("schema") != "ar.feature_store_health"
        or feature_health.get("as_of") != as_of
    ):
        raise PreDecisionError("feature-store health is not bound to the bundle date")
    positive = feature_health.get("semiconductor_positive_inputs")
    if not isinstance(positive, Mapping) or positive.get("as_of") != as_of:
        raise PreDecisionError("semiconductor source health is missing or stale")
    sources = positive.get("sources")
    if not isinstance(sources, Mapping):
        raise PreDecisionError("semiconductor source-health rows are missing")
    registry_ref = feature_health.get("registry_ref")
    scan = bundle.get("scan")
    scan_refs = scan.get("input_refs") if isinstance(scan, Mapping) else None
    # governance-mutation: U4_PREDECISION_FEATURE_HEALTH_IDENTITY
    if (
        not isinstance(registry_ref, Mapping)
        or not isinstance(scan, Mapping)
        or not isinstance(scan_refs, Mapping)
        or registry_ref.get("eligible_universe_hash")
        != scan.get("eligible_universe_hash")
        or positive.get("rows_hash")
        != scan_refs.get("semiconductor_positive_inputs_rows_hash")
    ):
        raise PreDecisionError(
            "feature-store health identity is not bound to the immutable bundle scan"
        )
    try:
        health_generated_at = closure._iso(
            feature_health.get("generated_at"), "feature-store health generated_at"
        )
    except closure.ClosureError as exc:
        raise PreDecisionError(str(exc)) from exc
    # feature_store.v1 has no PENDING source-row contract. An invented PENDING
    # row must not bypass validation of every other field in the health receipt.
    # governance-mutation: U4_PREDECISION_FEATURE_HEALTH_CONTRACT
    try:
        feature_store.validate_health(dict(feature_health))
    except feature_store.FeatureStoreError as exc:
        raise PreDecisionError(f"feature-store health contract failed: {exc}") from exc
    daily_status, daily_missing = _publication_status(sources, DAILY_SOURCES)
    quarterly_status, quarterly_missing = _publication_status(sources, QUARTERLY_SOURCES)
    return {
        "daily_source_status": daily_status,
        "quarterly_source_status": quarterly_status,
        "pending_sources": sorted(set(daily_missing + quarterly_missing)),
        "retry_after_utc": None,
    }, health_generated_at


def _validate_funnel_health(
    health: Mapping[str, Any], bundle: Mapping[str, Any], bundle_path: Path,
) -> Any:
    manifest = bundle["manifest"]
    bundle_health = health.get("bundle")
    if (
        health.get("schema") != "ar.research_funnel_health"
        or health.get("as_of") != manifest.get("as_of")
        or health.get("run_id") != manifest.get("run_id")
        or not isinstance(bundle_health, Mapping)
        or bundle_health.get("immutable") is not True
        or bundle_health.get("bundle_hash") != manifest.get("bundle_hash")
        or bundle_health.get("location")
        != _source_ref(bundle_path, bundle_path.name)
    ):
        raise PreDecisionError("funnel health is not bound to this immutable bundle")
    try:
        health_generated_at = closure._iso(
            health.get("generated_at"), "funnel health generated_at"
        )
    except closure.ClosureError as exc:
        raise PreDecisionError(str(exc)) from exc
    try:
        expected = nightly_funnel.build_health(
            target=str(manifest["as_of"]),
            run_id=str(manifest["run_id"]),
            bundle_dir=bundle_path,
            registry=dict(bundle["registry"]),
            generated_at=str(health["generated_at"]),
        )
        battery_coverage = funnel.validate_candidate_battery(
            bundle["battery"], bundle["candidate_manifest"]
        )
    except (funnel.FunnelError, ValueError) as exc:
        raise PreDecisionError(f"funnel health evidence validation failed: {exc}") from exc
    # governance-mutation: U4_PREDECISION_FUNNEL_HEALTH_DERIVATION
    if any(health.get(key) != value for key, value in expected.items()):
        raise PreDecisionError("funnel health is not derived from the immutable bundle")
    expected_battery_coverage = dict(
        battery_coverage,
        provider_state=bundle["battery"]["provider_state"],
    )
    if health.get("battery_coverage") != expected_battery_coverage:
        raise PreDecisionError("funnel health battery coverage is not derived from U3")
    return health_generated_at


def _validate_stage_receipts(
    bundle: Mapping[str, Any], bundle_path: Path,
) -> tuple[str, dict[str, Any]]:
    top = bundle["manifest"]
    candidate_manifest = bundle["candidate_manifest"]
    battery = bundle["battery"]
    expected = {
        "candidates": (
            set(dag.STAGE1_FILES),
            {"candidate_manifest_hash": candidate_manifest["manifest_hash"]},
        ),
        "battery": (
            set(dag.STAGE2_FILES),
            {
                "candidate_manifest_hash": candidate_manifest["manifest_hash"],
                "battery_rows_hash": battery["rows_hash"],
            },
        ),
        "finalize": (
            set(dag.STAGE3_FILES),
            {
                "candidate_manifest_hash": candidate_manifest["manifest_hash"],
                "battery_rows_hash": battery["rows_hash"],
            },
        ),
    }
    receipts: dict[str, Any] = {}
    for stage, (expected_files, expected_binds) in expected.items():
        receipt_path = bundle_path / f"stage_{stage}.json"
        # governance-mutation: U4_PREDECISION_STAGE_RECEIPT_FILE
        if not receipt_path.is_file() or receipt_path.is_symlink():
            raise PreDecisionError(f"stage receipt must be a regular file: {stage}")
        try:
            receipt, payloads = dag._read_stage(
                bundle_path,
                stage,
                as_of=str(top["as_of"]),
                run_id=str(top["run_id"]),
            )
        except funnel.FunnelError as exc:
            raise PreDecisionError(f"stage receipt validation failed: {exc}") from exc
        # governance-mutation: U4_PREDECISION_STAGE_RECEIPTS
        if (
            set(receipt) != {
                "schema", "schema_version", "rule_version", "stage", "as_of",
                "run_id", "generated_at", "binds", "artifacts", "stage_hash",
            }
            or receipt.get("schema") != "ar.research_funnel_stage"
            or receipt.get("schema_version") != funnel.SCHEMA_VERSION
            or receipt.get("rule_version") != funnel.RULE_VERSION
            or receipt.get("stage") != stage
            or set(payloads) != expected_files
            or receipt.get("binds") != expected_binds
        ):
            raise PreDecisionError(f"stage receipt contract is invalid: {stage}")
        try:
            receipt_generated_at = closure._iso(
                receipt.get("generated_at"), f"{stage} receipt generated_at"
            )
        except closure.ClosureError as exc:
            raise PreDecisionError(str(exc)) from exc
        artifact_times: list[Any] = []
        for name, payload in payloads.items():
            if not isinstance(payload, Mapping) or "generated_at" not in payload:
                continue
            try:
                artifact_times.append(
                    closure._iso(
                        payload.get("generated_at"), f"{stage} artifact generated_at: {name}"
                    )
                )
            except closure.ClosureError as exc:
                raise PreDecisionError(str(exc)) from exc
        # governance-mutation: U4_PREDECISION_STAGE_ARTIFACT_CHRONOLOGY
        if not artifact_times or any(value != receipt_generated_at for value in artifact_times):
            raise PreDecisionError(f"{stage} receipt timestamp is not bound to its artifacts")
        receipts[stage] = receipt
    receipt_times = {
        stage: closure._iso(receipt["generated_at"], f"{stage} receipt generated_at")
        for stage, receipt in receipts.items()
    }
    # governance-mutation: U4_PREDECISION_STAGE_ORDER
    if not (
        receipt_times["candidates"]
        <= receipt_times["battery"]
        <= receipt_times["finalize"]
    ):
        raise PreDecisionError("stage receipts violate candidates -> battery -> finalize order")
    return _sha(receipts), receipt_times


def _red_flags(candidate: Mapping[str, Any], battery_row: Mapping[str, Any]) -> list[str]:
    fundamental = (battery_row.get("dims") or {}).get("基本面") or {}
    result: set[str] = set()
    if "RED_FLAG" in set(candidate.get("flags") or []):
        result.add("E1_EVENT")
    verdict = fundamental.get("红旗闸门")
    if verdict not in {None, "PASS"}:
        result.add("FINANCIAL_RED_FLAG")
    return sorted(result)


def _candidate_rows(bundle: Mapping[str, Any], industry: str, method_version: str) -> list[dict[str, Any]]:
    manifest_codes = set(bundle["candidate_manifest"]["ts_codes"])
    candidates = {
        str(row["ts_code"]): row
        for row in bundle["candidates"]["rows"]
        if str(row["ts_code"]) in manifest_codes and row.get("industry_key") == industry
    }
    registry = {str(row["ts_code"]): row for row in bundle["registry"]["rows"]}
    battery = funnel._battery_rows(bundle["battery"], str(bundle["manifest"]["as_of"]))
    queue = {str(row["ts_code"]): row for row in bundle["queue"]["ready_pool"]}
    rows: list[dict[str, Any]] = []
    for code in sorted(candidates):
        candidate = candidates[code]
        battery_row = battery.get(code)
        projected = queue.get(code)
        registry_row = registry.get(code)
        if battery_row is None or projected is None or registry_row is None:
            raise PreDecisionError(f"candidate evidence row is missing: {code}")
        positive_channels = sorted({
            CHANNEL_MAP.get(str(channel), "OTHER")
            for channel in candidate.get("source_channels") or []
        })
        red_flag_channels = _red_flags(candidate, battery_row)
        completeness = battery_row.get("completeness") or {}
        blocked: set[str] = set()
        if completeness.get("verdict") != "COMPLETE":
            blocked.add("U3_BATTERY_INCOMPLETE")
        if red_flag_channels:
            blocked.add("E1_RED_FLAG_ACTIVE")
        if not positive_channels:
            blocked.add("NO_POSITIVE_CHANNEL")
        if candidate.get("review_status") == "RANDOM_CONTROL":
            blocked.add("RANDOM_CONTROL_NOT_SELECTABLE")
        cohort_id = UNAVAILABLE
        cluster_id = str(candidate.get("cluster_id") or UNAVAILABLE)
        missing: list[str] = []
        if cohort_id == UNAVAILABLE:
            missing.append("cohort_id")
        if cluster_id == UNAVAILABLE:
            missing.append("causal_cluster_id")
        missing.sort()
        allowed = not blocked and projected.get("ready") is True
        if any(code != "E1_RED_FLAG_ACTIVE" for code in blocked):
            quality = "DATA_BLOCKED"
        elif "E1_RED_FLAG_ACTIVE" in blocked:
            quality = "REVISE_REQUIRED"
        elif missing:
            quality = "WARN"
        else:
            quality = "PASS"
        rows.append({
            "ts_code": code,
            "display_name": str(registry_row.get("name") or UNAVAILABLE),
            "candidate_status": str(candidate.get("review_status") or ""),
            "method_version": method_version,
            "cohort_id": cohort_id,
            "cohort_identity_state": "UNAVAILABLE_UNBOUND",
            "causal_cluster_id": cluster_id,
            "causal_cluster_identity_state": (
                "UNAVAILABLE_PENDING" if cluster_id == UNAVAILABLE else "VERIFIED_UPSTREAM"
            ),
            "u2_candidate_row_hash": _sha(candidate),
            "u3_battery_row_hash": _sha(battery_row),
            "positive_channels": positive_channels,
            "red_flag_channels": red_flag_channels,
            "blocked_reasons": sorted(blocked),
            "missing_evidence": missing,
            "quality_status": quality,
            "allowed_for_u4_packet": allowed,
            "question_for_junyan": (
                f"是否将 {registry_row.get('name') or code} ({code}) 纳入离线 workflow-debug 深研？"
                if allowed else None
            ),
        })
    return rows


def _status(publication: Mapping[str, Any], allowed: int) -> str:
    values = {
        str(publication.get("daily_source_status") or ""),
        str(publication.get("quarterly_source_status") or ""),
    }
    # governance-mutation: U4_PREDECISION_GLOBAL_SOURCE_GATE
    if "PENDING" in values:
        return "SOURCE_PUBLICATION_PENDING"
    # governance-mutation: U4_PREDECISION_GLOBAL_DATA_BLOCK
    if values.intersection({"STALE", "DATA_BLOCKED"}):
        return "DATA_BLOCKED"
    if allowed == 0:
        return "BLOCKED_BEFORE_U4"
    return "READY_FOR_JUNYAN_REVIEW"


def build_packet(
    *, bundle_dir: Path, feature_health_path: Path, funnel_health_path: Path,
    diagnostic_ref: str, industry: str, method_version: str, generated_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        packet_generated_at = closure._iso(generated_at, "pre-decision generated_at")
        bundle = closure.load_bundle(bundle_dir)
    except closure.ClosureError as exc:
        raise PreDecisionError(str(exc)) from exc
    if "candidate_manifest" not in bundle or "battery" not in bundle:
        raise PreDecisionError("pre-decision packet requires the final three-stage DAG bundle")
    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}_V[0-9]+", method_version) is None:
        raise PreDecisionError("method_version is invalid")
    feature_health = _load(feature_health_path)
    funnel_health = _load(funnel_health_path)
    funnel_health_generated_at = _validate_funnel_health(
        funnel_health, bundle, bundle_dir
    )
    try:
        bundle_generated_at = closure._iso(
            bundle["manifest"].get("generated_at"), "bundle generated_at"
        )
    except closure.ClosureError as exc:
        raise PreDecisionError(str(exc)) from exc
    stage_receipts_hash, stage_times = _validate_stage_receipts(
        bundle, bundle_dir
    )
    as_of = str(bundle["manifest"]["as_of"])
    publication, feature_health_generated_at = _source_publication(
        feature_health, bundle, as_of
    )
    # governance-mutation: U4_PREDECISION_CAUSAL_CHRONOLOGY
    if not (
        feature_health_generated_at
        <= stage_times["candidates"]
        and stage_times["finalize"]
        <= bundle_generated_at
        <= funnel_health_generated_at
        <= packet_generated_at
    ):
        raise PreDecisionError(
            "evidence violates feature -> candidates -> battery -> finalize -> bundle/health order"
        )
    rows = _candidate_rows(bundle, industry, method_version)
    allowed = sum(row["allowed_for_u4_packet"] is True for row in rows)
    blocked_codes = sorted({code for row in rows for code in row["blocked_reasons"]})
    if publication["daily_source_status"] != "PUBLISHED":
        blocked_codes.append("DAILY_SOURCE_NOT_PUBLISHED")
    if publication["quarterly_source_status"] != "PUBLISHED":
        blocked_codes.append("QUARTERLY_SOURCE_NOT_PUBLISHED")
    diagnostic = {
        "tool": DIAGNOSTIC_TOOL,
        "tool_version": DIAGNOSTIC_VERSION,
        "evidence_rows_checked": len(rows),
        "evidence_rows_hash_verified": True,
        "receipt_self_report_checked": True,
        "red_flag_only_rows": sum(bool(row["red_flag_channels"]) for row in rows),
        "positive_channel_rows": sum(bool(row["positive_channels"]) for row in rows),
        "u3_complete_rows": sum(
            "U3_BATTERY_INCOMPLETE" not in row["blocked_reasons"] for row in rows
        ),
        "u4_ready_rows": allowed,
        "blocker_codes": sorted(set(blocked_codes)),
    }
    refs = {
        "same_day_bundle_ref": _source_ref(bundle_dir, bundle_dir.name),
        "same_day_bundle_hash": _sha(bundle["manifest"]["artifacts"]),
        "u2_candidate_pool_hash": _sha(bundle["candidates"]["rows"]),
        "u3_battery_hash": _sha(bundle["battery"]),
        "feature_store_health_ref": _source_ref(feature_health_path, feature_health_path.name),
        "feature_store_health_hash": _sha(feature_health),
        "funnel_health_ref": _source_ref(funnel_health_path, funnel_health_path.name),
        "funnel_health_hash": _sha(funnel_health),
        "stage_receipts_hash": stage_receipts_hash,
        "diagnostic_report_ref": diagnostic_ref,
        "diagnostic_report_hash": _sha(diagnostic),
    }
    packet: dict[str, Any] = {
        "schema": SCHEMA,
        "packet_version": SCHEMA_VERSION,
        "status": _status(publication, allowed),
        "as_of": as_of,
        "generated_at": generated_at,
        "method_version": method_version,
        "source_refs": refs,
        "source_publication": publication,
        "diagnostic": diagnostic,
        "candidate_rows": rows,
        "packet_summary": {
            "candidate_count": len(rows),
            "allowed_for_review_count": allowed,
            "blocked_count": len(rows) - allowed,
            "red_flag_count": sum(bool(row["red_flag_channels"]) for row in rows),
            "data_blocked_count": sum(row["quality_status"] == "DATA_BLOCKED" for row in rows),
            "same_day_hash": _sha({
                "as_of": as_of,
                "source_refs": refs,
                "source_publication": publication,
                "candidate_rows": rows,
            }),
        },
        "selection_boundary": {
            "allowed_selected_counts": [0, 3, 4, 5],
            "zero_selection_meaning": "NO_TRADE_NO_QUEUE",
            "human_selection_authority": "HUMAN_JUNYAN_ONLY",
            "machine_selection_authority": "NONE",
        },
        "authority": {
            "production_authority": False,
            "trade_authority": False,
            "paper_order_authority": False,
            "claim_allowed": False,
            "no_trade_flag": True,
        },
    }
    packet["packet_hash"] = _sha(_without_hash(packet))
    _validate_packet_receipt(packet)
    return packet, diagnostic


def _validate_packet_receipt(packet: Mapping[str, Any]) -> None:
    _require_exact(packet, PACKET_FIELDS, "pre-decision packet")
    if (
        packet.get("schema") != SCHEMA
        or packet.get("packet_version") != SCHEMA_VERSION
        or packet.get("status") not in PACKET_STATUS
        or re.fullmatch(r"[0-9]{8}", str(packet.get("as_of") or "")) is None
        or re.fullmatch(
            r"[A-Z][A-Z0-9_]{2,63}_V[0-9]+", str(packet.get("method_version") or "")
        ) is None
    ):
        raise PreDecisionError("pre-decision packet identity is invalid")
    try:
        closure._iso(packet.get("generated_at"), "pre-decision generated_at")
    except closure.ClosureError as exc:
        raise PreDecisionError(str(exc)) from exc
    refs = packet.get("source_refs")
    if not isinstance(refs, Mapping):
        raise PreDecisionError("source_refs must be an object")
    _require_exact(refs, SOURCE_FIELDS, "source_refs")
    for key in SOURCE_FIELDS:
        value = refs.get(key)
        if key.endswith("_hash"):
            if re.fullmatch(r"sha256:[0-9a-f]{64}", str(value or "")) is None:
                raise PreDecisionError(f"source digest is invalid: {key}")
        elif not isinstance(value, str) or not value.strip():
            raise PreDecisionError(f"source reference is missing: {key}")
    publication = packet.get("source_publication")
    if not isinstance(publication, Mapping) or set(publication) != {
        "daily_source_status", "quarterly_source_status", "pending_sources", "retry_after_utc"
    }:
        raise PreDecisionError("source publication fields are not exact")
    if (
        publication.get("daily_source_status") not in SOURCE_STATUS
        or publication.get("quarterly_source_status") not in SOURCE_STATUS
        or not isinstance(publication.get("pending_sources"), list)
    ):
        raise PreDecisionError("source publication status is invalid")
    pending_sources = publication["pending_sources"]
    if pending_sources != sorted(set(pending_sources)) or any(
        not isinstance(source, str) or not source.strip() for source in pending_sources
    ):
        raise PreDecisionError("pending source names are invalid")
    all_published = all(
        publication[field] == "PUBLISHED"
        for field in ("daily_source_status", "quarterly_source_status")
    )
    if all_published != (not pending_sources):
        raise PreDecisionError("source publication status and pending_sources disagree")
    rows = packet.get("candidate_rows")
    if not isinstance(rows, list):
        raise PreDecisionError("candidate_rows must be a list")
    codes: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise PreDecisionError("candidate row must be an object")
        _require_exact(row, CANDIDATE_FIELDS, "candidate row")
        code = str(row.get("ts_code") or "")
        codes.append(code)
        if (
            re.fullmatch(r"[0-9A-Z]+\.[A-Z]+", code) is None
            or not str(row.get("display_name") or "").strip()
            or row.get("candidate_status") not in CANDIDATE_STATUS
            or row.get("method_version") != packet.get("method_version")
            or re.fullmatch(r"sha256:[0-9a-f]{64}", str(row.get("u2_candidate_row_hash") or "")) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", str(row.get("u3_battery_row_hash") or "")) is None
        ):
            raise PreDecisionError(f"candidate identity or evidence binding is invalid: {code}")
        positive = row.get("positive_channels")
        red_flags = row.get("red_flag_channels")
        blocked = row.get("blocked_reasons")
        missing = row.get("missing_evidence")
        if not all(isinstance(value, list) for value in (positive, red_flags, blocked, missing)):
            raise PreDecisionError(f"candidate evidence lists are invalid: {code}")
        if (
            any(len(value) != len(set(value)) or value != sorted(value)
                for value in (positive, red_flags, blocked, missing))
            or not set(positive).issubset(POSITIVE_CHANNELS)
            or not set(red_flags).issubset(RED_FLAG_CHANNELS)
        ):
            raise PreDecisionError(f"candidate evidence vocabulary/order is invalid: {code}")
        if not set(blocked).issubset(ROW_BLOCKERS):
            raise PreDecisionError(f"candidate blocker is invalid: {code}")
        # governance-mutation: U4_PREDECISION_COHORT_IDENTITY
        if (
            row.get("cohort_id") != UNAVAILABLE
            or row.get("cohort_identity_state") != "UNAVAILABLE_UNBOUND"
        ):
            raise PreDecisionError(f"cohort identity is not bound: {code}")
        if red_flags and (
            "E1_RED_FLAG_ACTIVE" not in blocked or row.get("allowed_for_u4_packet") is not False
        ):
            raise PreDecisionError(f"red-flag row escaped the U4 stop: {code}")
        # governance-mutation: U4_PREDECISION_NO_POSITIVE_CHANNEL
        if not positive and (
            "NO_POSITIVE_CHANNEL" not in blocked
            or row.get("allowed_for_u4_packet") is not False
        ):
            raise PreDecisionError(f"candidate without positive evidence escaped: {code}")
        # governance-mutation: U4_PREDECISION_RANDOM_CONTROL
        if row.get("candidate_status") == "RANDOM_CONTROL" and (
            "RANDOM_CONTROL_NOT_SELECTABLE" not in blocked
            or row.get("allowed_for_u4_packet") is not False
        ):
            raise PreDecisionError(f"random-control row escaped the U4 stop: {code}")
        if "U3_BATTERY_INCOMPLETE" in blocked and row.get("allowed_for_u4_packet") is not False:
            raise PreDecisionError(f"incomplete U3 row escaped the U4 stop: {code}")
        cluster_id = row.get("causal_cluster_id")
        cluster_state = row.get("causal_cluster_identity_state")
        if cluster_state == "UNAVAILABLE_PENDING":
            # governance-mutation: U4_PREDECISION_CLUSTER_IDENTITY
            if cluster_id != UNAVAILABLE or "causal_cluster_id" not in missing:
                raise PreDecisionError(f"unavailable causal cluster was hidden: {code}")
        elif cluster_state != "VERIFIED_UPSTREAM" or cluster_id == UNAVAILABLE:
            raise PreDecisionError(f"causal cluster identity is invalid: {code}")
        if "cohort_id" not in missing:
            raise PreDecisionError(f"unavailable cohort was hidden: {code}")
        if row.get("allowed_for_u4_packet") is True and blocked:
            raise PreDecisionError(f"blocked candidate was marked reviewable: {code}")
        if row.get("allowed_for_u4_packet") is False and not blocked:
            raise PreDecisionError(f"candidate was blocked without a reason: {code}")
        if row.get("allowed_for_u4_packet") is True and not row.get("question_for_junyan"):
            raise PreDecisionError(f"reviewable candidate lacks the human question: {code}")
        if row.get("allowed_for_u4_packet") is False and row.get("question_for_junyan") is not None:
            raise PreDecisionError(f"blocked candidate carries a review question: {code}")
        # governance-mutation: U4_PREDECISION_COMBINED_QUALITY
        expected_quality = (
            "DATA_BLOCKED" if any(item != "E1_RED_FLAG_ACTIVE" for item in blocked)
            else "REVISE_REQUIRED" if "E1_RED_FLAG_ACTIVE" in blocked
            else "WARN" if missing
            else "PASS"
        )
        if row.get("quality_status") != expected_quality:
            raise PreDecisionError(f"candidate quality is not derived from evidence: {code}")
    if len(codes) != len(set(codes)):
        raise PreDecisionError("candidate rows must be unique")
    summary = packet.get("packet_summary")
    if not isinstance(summary, Mapping):
        raise PreDecisionError("packet_summary must be an object")
    _require_exact(summary, SUMMARY_FIELDS, "packet_summary")
    allowed = sum(row.get("allowed_for_u4_packet") is True for row in rows)
    if (
        summary.get("candidate_count") != len(rows)
        or summary.get("allowed_for_review_count") != allowed
        or summary.get("blocked_count") != len(rows) - allowed
        or summary.get("red_flag_count") != sum(bool(row["red_flag_channels"]) for row in rows)
        or summary.get("data_blocked_count")
        != sum(row["quality_status"] == "DATA_BLOCKED" for row in rows)
        or summary.get("same_day_hash") != _sha({
            "as_of": packet["as_of"],
            "source_refs": refs,
            "source_publication": publication,
            "candidate_rows": rows,
        })
    ):
        raise PreDecisionError("packet summary is not derived from candidate rows")
    expected_status = _status(publication, allowed)
    if packet.get("status") != expected_status:
        raise PreDecisionError("packet status is not derived from source and candidate evidence")
    diagnostic = packet.get("diagnostic")
    if not isinstance(diagnostic, Mapping):
        raise PreDecisionError("diagnostic report is missing")
    _require_exact(diagnostic, DIAGNOSTIC_FIELDS, "diagnostic")
    expected_blockers = sorted({code for row in rows for code in row["blocked_reasons"]})
    if publication["daily_source_status"] != "PUBLISHED":
        expected_blockers.append("DAILY_SOURCE_NOT_PUBLISHED")
    if publication["quarterly_source_status"] != "PUBLISHED":
        expected_blockers.append("QUARTERLY_SOURCE_NOT_PUBLISHED")
    # governance-mutation: U4_PREDECISION_DERIVED_DIAGNOSTIC
    if (
        diagnostic.get("tool") != DIAGNOSTIC_TOOL
        or diagnostic.get("tool_version") != DIAGNOSTIC_VERSION
        or diagnostic.get("evidence_rows_checked") != len(rows)
        or diagnostic.get("evidence_rows_hash_verified") is not True
        or diagnostic.get("receipt_self_report_checked") is not True
        or diagnostic.get("red_flag_only_rows") != sum(bool(row["red_flag_channels"]) for row in rows)
        or diagnostic.get("positive_channel_rows") != sum(bool(row["positive_channels"]) for row in rows)
        or diagnostic.get("u3_complete_rows")
        != sum("U3_BATTERY_INCOMPLETE" not in row["blocked_reasons"] for row in rows)
        or diagnostic.get("u4_ready_rows") != allowed
        or diagnostic.get("blocker_codes") != sorted(set(expected_blockers))
        or refs.get("diagnostic_report_hash") != _sha(diagnostic)
    ):
        raise PreDecisionError("diagnostic report binding is invalid")
    # governance-mutation: U4_PREDECISION_HUMAN_AUTHORITY
    if packet.get("selection_boundary") != {
        "allowed_selected_counts": [0, 3, 4, 5],
        "zero_selection_meaning": "NO_TRADE_NO_QUEUE",
        "human_selection_authority": "HUMAN_JUNYAN_ONLY",
        "machine_selection_authority": "NONE",
    }:
        raise PreDecisionError("selection authority boundary changed")
    if packet.get("authority") != {
        "production_authority": False,
        "trade_authority": False,
        "paper_order_authority": False,
        "claim_allowed": False,
        "no_trade_flag": True,
    }:
        raise PreDecisionError("packet acquired forbidden authority")
    # governance-mutation: U4_PREDECISION_PACKET_HASH
    if packet.get("packet_hash") != _sha(_without_hash(packet)):
        raise PreDecisionError("packet_hash mismatch")
    if funnel.FORBIDDEN_ACTION_KEYS.intersection(funnel._walk_keys(packet)):
        raise PreDecisionError("pre-decision packet contains a forbidden action field")


def validate_packet(
    packet: Mapping[str, Any], *, bundle_dir: Path, feature_health_path: Path,
    funnel_health_path: Path, diagnostic_ref: str, industry: str,
    method_version: str,
) -> None:
    """Reopen authoritative sources and reject a merely self-consistent packet."""
    _validate_packet_receipt(packet)
    if packet.get("method_version") != method_version:
        raise PreDecisionError("packet method_version differs from the frozen request")
    refs = packet.get("source_refs")
    if not isinstance(refs, Mapping) or refs.get("diagnostic_report_ref") != diagnostic_ref:
        raise PreDecisionError("diagnostic report reference differs from the frozen request")
    expected, _diagnostic = build_packet(
        bundle_dir=bundle_dir,
        feature_health_path=feature_health_path,
        funnel_health_path=funnel_health_path,
        diagnostic_ref=diagnostic_ref,
        industry=industry,
        method_version=method_version,
        generated_at=str(packet["generated_at"]),
    )
    actual_rows = {
        str(row["ts_code"]): dict(row) for row in packet["candidate_rows"]
    }
    expected_rows = {
        str(row["ts_code"]): dict(row) for row in expected["candidate_rows"]
    }
    # Derived hashes remain order-sensitive and are checked by the receipt
    # validator. External authority is the unique candidate set and each row's
    # exact evidence, not its display order.
    source_bound_actual = {
        "as_of": packet["as_of"],
        "method_version": packet["method_version"],
        "source_refs": packet["source_refs"],
        "source_publication": packet["source_publication"],
        "candidate_rows": actual_rows,
    }
    source_bound_expected = {
        "as_of": expected["as_of"],
        "method_version": expected["method_version"],
        "source_refs": expected["source_refs"],
        "source_publication": expected["source_publication"],
        "candidate_rows": expected_rows,
    }
    # governance-mutation: U4_PREDECISION_EXTERNAL_EVIDENCE_BINDING
    if source_bound_actual != source_bound_expected:
        raise PreDecisionError("packet differs from reopened immutable evidence")


def _write_outputs(
    scratch_root: Path, packet_path: Path, diagnostic_path: Path,
    packet: Mapping[str, Any], diagnostic: Mapping[str, Any],
    *, protected_paths: Sequence[Path],
) -> None:
    if not scratch_root.is_dir() or scratch_root.is_symlink():
        raise PreDecisionError("scratch root must be one existing regular directory")
    scratch_lexical = Path(os.path.abspath(scratch_root))
    scratch_resolved = scratch_root.resolve()
    # governance-mutation: U4_PREDECISION_STATIC_RUNTIME_BOUNDARY
    protected_roots: set[Path] = {RUNTIME_ROOT.resolve()}
    for protected in protected_paths:
        resolved = protected.resolve()
        protected_roots.add(resolved if resolved.is_dir() else resolved.parent)
        parts = resolved.parts
        for marker in ("data_history", "public"):
            if marker in parts:
                protected_roots.add(Path(*parts[:parts.index(marker)]).resolve())
    # governance-mutation: U4_PREDECISION_SCRATCH_BOUNDARY
    if any(
        scratch_resolved == protected
        or scratch_resolved.is_relative_to(protected)
        or protected.is_relative_to(scratch_resolved)
        for protected in protected_roots
    ):
        raise PreDecisionError("scratch root overlaps an immutable input or production tree")
    if packet_path.resolve(strict=False) == diagnostic_path.resolve(strict=False):
        raise PreDecisionError("packet and diagnostic outputs must be different files")
    for path in (packet_path, diagnostic_path):
        path_lexical = Path(os.path.abspath(path))
        resolved = path.resolve(strict=False)
        if resolved == scratch_resolved or not resolved.is_relative_to(scratch_resolved):
            raise PreDecisionError("output path must remain inside the dedicated scratch root")
        try:
            relative_parent = path_lexical.parent.relative_to(scratch_lexical)
        except ValueError as exc:
            raise PreDecisionError("output path is not lexically inside the scratch root") from exc
        current = scratch_lexical
        for part in relative_parent.parts:
            current /= part
            if current.is_symlink():
                raise PreDecisionError("output path cannot traverse a symbolic link")
        if os.path.lexists(path):
            raise PreDecisionError(f"output already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(diagnostic_path, dict(diagnostic))
    try:
        _atomic_write_json(packet_path, dict(packet))
    except Exception:
        diagnostic_path.unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--feature-health", required=True, type=Path)
    parser.add_argument("--funnel-health", required=True, type=Path)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--packet-output", required=True, type=Path)
    parser.add_argument("--diagnostic-output", required=True, type=Path)
    parser.add_argument("--scratch-root", required=True, type=Path)
    parser.add_argument("--industry", default=DEFAULT_INDUSTRY)
    parser.add_argument("--method-version", default=DEFAULT_METHOD_VERSION)
    args = parser.parse_args(argv)
    try:
        packet, diagnostic = build_packet(
            bundle_dir=args.bundle,
            feature_health_path=args.feature_health,
            funnel_health_path=args.funnel_health,
            diagnostic_ref=args.diagnostic_output.name,
            industry=args.industry,
            method_version=args.method_version,
            generated_at=args.generated_at,
        )
        validate_packet(
            packet,
            bundle_dir=args.bundle,
            feature_health_path=args.feature_health,
            funnel_health_path=args.funnel_health,
            diagnostic_ref=args.diagnostic_output.name,
            industry=args.industry,
            method_version=args.method_version,
        )
        _write_outputs(
            args.scratch_root,
            args.packet_output,
            args.diagnostic_output,
            packet,
            diagnostic,
            protected_paths=(args.bundle, args.feature_health, args.funnel_health),
        )
    except (PreDecisionError, ValueError) as exc:
        print(f"REFUSED: {exc}")
        return 1
    print(json.dumps({
        "status": packet["status"],
        "as_of": packet["as_of"],
        "packet_hash": packet["packet_hash"],
        "candidate_count": packet["packet_summary"]["candidate_count"],
        "allowed_for_review_count": packet["packet_summary"]["allowed_for_review_count"],
    }, ensure_ascii=False, sort_keys=True))
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
