#!/usr/bin/env python3
"""Offline U1-U5 research-closure replay with a human-bound U4 packet.

This module never fetches data, writes a production ledger, or creates trading
authority.  It verifies a frozen U1/U2 bundle, replays the preregistered random
control, prepares a U4 review packet, and accepts only a receipt bound to that
packet.  The receipt remains honest about the local identity boundary: a name
inside JSON is not proof that Junyan supplied it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from . import funnel_pipeline as funnel
    from .security_registry import _atomic_write_json, validate_registry
except ImportError:  # Direct CLI execution adds this file's directory to sys.path.
    import funnel_pipeline as funnel
    from security_registry import _atomic_write_json, validate_registry


PACKET_SCHEMA = "ar.u4_review_packet"
RECEIPT_SCHEMA = "ar.u4_review_receipt"
REPORT_SCHEMA = "ar.research_closure_experiment"
SCHEMA_VERSION = "1.0"
BUNDLE_ARTIFACTS = {
    "all_market_scan.json",
    "candidate_review.json",
    "deep_research_queue.json",
    "security_registry_projected.json",
}
DAG_BUNDLE_ARTIFACTS = BUNDLE_ARTIFACTS | {
    "candidate_manifest.json",
    "candidate_battery.json",
}
BUNDLE_MANIFEST_FIELDS = {
    "schema", "schema_version", "rule_version", "as_of", "generated_at",
    "artifacts", "bundle_hash",
}
DAG_BUNDLE_MANIFEST_FIELDS = BUNDLE_MANIFEST_FIELDS | {"run_id", "dag"}
RESULT_ARTIFACTS = {
    "review_packet.json",
    "review_receipt.json",
    "deep_research_queue.json",
    "closure_report.json",
    "frozen_battery.json",
    "frozen_funnel_bundle/manifest.json",
    "frozen_funnel_bundle/all_market_scan.json",
    "frozen_funnel_bundle/candidate_review.json",
    "frozen_funnel_bundle/deep_research_queue.json",
    "frozen_funnel_bundle/security_registry_projected.json",
}
RESULT_MANIFEST_FIELDS = {
    "schema", "schema_version", "as_of", "mode", "artifacts", "bundle_hash",
    "production_authority", "claim_allowed", "disclaimer",
}
RECEIPT_DECISION = "APPROVED_FOR_OFFLINE_RESEARCH_REPLAY"
RECEIPT_CLASS = "HUMAN_PROVIDED_UNVERIFIED_IDENTITY"
BATTERY_DIMENSIONS = {"行情", "资金", "基本面", "技术面", "消息面", "估值"}
PACKET_SOURCE_REF_FIELDS = {
    "run_id", "bundle_hash", "scan_rows_hash", "candidate_rows_hash",
    "battery_hash", "ready_pool_hash",
}
PACKET_READY_ROW_FIELDS = {
    "ts_code", "ready", "industry_key", "sector_os_status", "candidate_status",
    "battery_verdict", "blocked_reasons", "display_name", "cohort_id",
    "causal_cluster_id", "u2_candidate_row_hash", "u3_battery_row_hash",
}
DISCLAIMER = "不是买卖指令；研究信号，human executes."


class ClosureError(RuntimeError):
    pass


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        # governance-mutation: FUNNEL_CLOSURE_DUPLICATE_JSON_KEYS
        if key in value:
            raise ClosureError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicates,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ClosureError(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ClosureError(f"JSON root must be an object: {path}")
    return value


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _without_hash(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != field}


def _require_exact_keys(payload: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(payload) != expected:
        raise ClosureError(f"{label} fields are not exact")


def _iso(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ClosureError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ClosureError(f"{label} must be timezone-aware")
    return parsed


def load_bundle(bundle_dir: Path) -> dict[str, dict[str, Any]]:
    """Load and contract-check one immutable research-funnel bundle."""
    if not bundle_dir.is_dir() or bundle_dir.is_symlink():
        raise ClosureError("bundle_dir must be a real directory")
    manifest_path = bundle_dir / "manifest.json"
    manifest = _load_object(manifest_path)
    artifacts = manifest.get("artifacts")
    is_dag_bundle = manifest.get("dag") is not None
    expected_manifest_fields = (
        DAG_BUNDLE_MANIFEST_FIELDS if is_dag_bundle else BUNDLE_MANIFEST_FIELDS
    )
    expected_artifacts = DAG_BUNDLE_ARTIFACTS if is_dag_bundle else BUNDLE_ARTIFACTS
    if (
        set(manifest) != expected_manifest_fields
        or manifest.get("schema") != "ar.research_funnel_bundle"
        or manifest.get("schema_version") != funnel.SCHEMA_VERSION
        or not isinstance(artifacts, dict)
        or set(artifacts) != expected_artifacts
    ):
        raise ClosureError("bundle manifest schema/artifact set is invalid")
    # governance-mutation: FUNNEL_CLOSURE_BUNDLE_HASH
    if manifest.get("bundle_hash") != funnel._hash(artifacts):
        raise ClosureError("bundle manifest bundle_hash mismatch")
    for name, expected_hash in artifacts.items():
        path = bundle_dir / name
        if not path.is_file() or path.is_symlink() or _sha256_path(path) != expected_hash:
            raise ClosureError(f"bundle artifact hash mismatch: {name}")

    registry = _load_object(bundle_dir / "security_registry_projected.json")
    scan = _load_object(bundle_dir / "all_market_scan.json")
    candidates = _load_object(bundle_dir / "candidate_review.json")
    queue = _load_object(bundle_dir / "deep_research_queue.json")
    try:
        validate_registry(registry)
        funnel.validate_all_market_scan(scan, registry)
        funnel.validate_candidate_review(candidates, registry, scan)
        funnel.validate_deep_research_queue(queue)
        if is_dag_bundle:
            candidate_manifest = _load_object(bundle_dir / "candidate_manifest.json")
            candidate_battery = _load_object(bundle_dir / "candidate_battery.json")
            funnel.validate_candidate_manifest(candidate_manifest)
            funnel.validate_candidate_battery(candidate_battery, candidate_manifest)
            dag = manifest.get("dag") or {}
            # governance-mutation: FUNNEL_CLOSURE_DAG_EVIDENCE_BINDING
            if (
                manifest.get("run_id") != candidate_manifest.get("run_id")
                or dag.get("candidate_manifest_hash")
                != candidate_manifest.get("manifest_hash")
                or dag.get("battery_rows_hash") != candidate_battery.get("rows_hash")
                or candidate_manifest.get("candidate_rows_hash") != candidates.get("rows_hash")
                or candidate_manifest.get("scan_rows_hash") != scan.get("rows_hash")
            ):
                raise ClosureError("DAG bundle evidence is not bound to its final manifest")
    except (ValueError, funnel.FunnelError) as exc:
        raise ClosureError(f"bundle contract validation failed: {exc}") from exc
    as_of = str(manifest.get("as_of") or "")
    if any(payload.get("as_of") != as_of for payload in (registry, scan, candidates, queue)):
        raise ClosureError("bundle artifacts do not share manifest as_of")
    # A review packet must start before any U4 selection is materialized.
    if queue.get("rows"):
        raise ClosureError("review packet source bundle already contains a U4 selection")
    result = {
        "manifest": manifest,
        "registry": registry,
        "scan": scan,
        "candidates": candidates,
        "queue": queue,
    }
    if is_dag_bundle:
        result["candidate_manifest"] = candidate_manifest
        result["battery"] = candidate_battery
    return result


def validate_battery_evidence(battery: Mapping[str, Any], as_of: str) -> None:
    try:
        rows = funnel._battery_rows(battery, as_of)
    except funnel.FunnelError as exc:
        raise ClosureError(f"U3 battery validation failed: {exc}") from exc
    for code, row in rows.items():
        completeness = row.get("completeness") or {}
        verdict = completeness.get("verdict")
        if verdict not in {"COMPLETE", "PARTIAL"}:
            raise ClosureError(f"U3 battery verdict is invalid: {code}")
        if verdict != "COMPLETE":
            continue
        dims = row.get("dims")
        # governance-mutation: FUNNEL_CLOSURE_U3_FULL_BATTERY
        if (
            not isinstance(dims, dict)
            or set(dims) != BATTERY_DIMENSIONS
            or completeness.get("covered") != 6
            or completeness.get("of") != 6
            or completeness.get("missing") != []
            or any(
                not isinstance(value, dict)
                or value.get("status") in {"DATA_BLOCKED", "NOT_RUN"}
                for value in dims.values()
            )
        ):
            raise ClosureError(f"U3 battery claims COMPLETE without six complete dimensions: {code}")


def build_review_packet(
    *, bundle_dir: Path, battery: Mapping[str, Any] | None, generated_at: str,
) -> dict[str, Any]:
    bundle = load_bundle(bundle_dir)
    as_of = str(bundle["manifest"]["as_of"])
    bundled_battery = bundle.get("battery")
    if bundled_battery is not None:
        if battery is not None and dict(battery) != bundled_battery:
            raise ClosureError("external U3 battery differs from the immutable DAG bundle")
        battery = bundled_battery
    if battery is None:
        raise ClosureError("review packet requires U3 battery evidence")
    validate_battery_evidence(battery, as_of)
    try:
        waiting_queue = funnel.build_deep_research_queue(
            candidate_review=bundle["candidates"],
            battery=battery,
            selected_tickers=(),
            trade_date=as_of,
            generated_at=generated_at,
        )
    except funnel.FunnelError as exc:
        raise ClosureError(f"cannot build U4 ready pool: {exc}") from exc
    run_id = str(
        battery.get("run_id")
        or ((battery.get("data") or {}).get("run_id") if isinstance(battery.get("data"), dict) else "")
        or ""
    ).strip()
    # governance-mutation: FUNNEL_CLOSURE_PACKET_RUN_ID
    if not run_id:
        raise ClosureError("U4 review packet requires the exact U3 run_id")
    candidate_by_code = {
        str(row["ts_code"]): row for row in bundle["candidates"]["rows"]
    }
    registry_by_code = {
        str(row["ts_code"]): row for row in bundle["registry"]["rows"]
    }
    battery_by_code = funnel._battery_rows(battery, as_of)
    ready_pool: list[dict[str, Any]] = []
    for projected in waiting_queue["ready_pool"]:
        code = str(projected["ts_code"])
        candidate = candidate_by_code.get(code)
        registry_row = registry_by_code.get(code)
        battery_row = battery_by_code.get(code)
        if candidate is None or registry_row is None or battery_row is None:
            raise ClosureError(f"U4 packet evidence row is missing: {code}")
        enriched = dict(projected)
        enriched.update({
            # governance-mutation: FUNNEL_CLOSURE_PACKET_CANDIDATE_EVIDENCE
            "display_name": str(registry_row.get("name") or "UNAVAILABLE"),
            "cohort_id": str(candidate.get("industry_key") or "UNAVAILABLE"),
            "causal_cluster_id": str(candidate.get("cluster_id") or "UNAVAILABLE"),
            "u2_candidate_row_hash": funnel._hash(candidate),
            "u3_battery_row_hash": funnel._hash(battery_row),
        })
        ready_pool.append(enriched)
    control_frame = bundle["candidates"]["control_sampling_frame"]
    packet: dict[str, Any] = {
        "schema": PACKET_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "mode": "OFFLINE_RESEARCH_REPLAY",
        "status": "AWAITING_JUNYAN_REVIEW",
        "as_of": as_of,
        "generated_at": generated_at,
        "source_refs": {
            "run_id": run_id,
            "bundle_hash": bundle["manifest"]["bundle_hash"],
            "scan_rows_hash": bundle["scan"]["rows_hash"],
            "candidate_rows_hash": bundle["candidates"]["rows_hash"],
            "battery_hash": funnel._hash(battery),
            "ready_pool_hash": funnel._hash(ready_pool),
        },
        "random_control": {
            "control_batch_id": control_frame["control_batch_id"],
            "eligible_universe_hash": control_frame["eligible_universe_hash"],
            "seed_hex": control_frame["seed_hex"],
            "algo": control_frame["algo"],
            "drawn_hash": funnel._hash(control_frame["drawn"]),
            "replay_verified": True,
        },
        "authority": {
            "selection_owner": "Junyan",
            "identity_verification": "UNAVAILABLE",
            "production_authority": False,
            "required_selection_size": {"min": 3, "max": 5},
        },
        "ready_pool": ready_pool,
        "claim_allowed": False,
        "next_gate": "JUNYAN_REVIEW_RECEIPT_BOUND_TO_PACKET_HASH",
        "disclaimer": DISCLAIMER,
    }
    packet["packet_hash"] = funnel._hash(packet)
    validate_review_packet(packet)
    return packet


def validate_review_packet(packet: Mapping[str, Any]) -> None:
    expected = {
        "schema", "schema_version", "mode", "status", "as_of", "generated_at",
        "source_refs", "random_control", "authority", "ready_pool", "claim_allowed",
        "next_gate", "disclaimer", "packet_hash",
    }
    _require_exact_keys(packet, expected, "review packet")
    if packet.get("schema") != PACKET_SCHEMA or packet.get("schema_version") != SCHEMA_VERSION:
        raise ClosureError("review packet schema/version mismatch")
    if packet.get("mode") != "OFFLINE_RESEARCH_REPLAY" or packet.get("status") != "AWAITING_JUNYAN_REVIEW":
        raise ClosureError("review packet mode/status is invalid")
    refs = packet.get("source_refs")
    if not isinstance(refs, dict) or set(refs) != PACKET_SOURCE_REF_FIELDS:
        raise ClosureError("review packet source references are not exact")
    if not str(refs.get("run_id") or "").strip():
        raise ClosureError("review packet run_id is missing")
    if any(
        not isinstance(refs.get(key), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(refs[key])) is None
        for key in PACKET_SOURCE_REF_FIELDS - {"run_id"}
    ):
        raise ClosureError("review packet source digest is invalid")
    ready_pool = packet.get("ready_pool")
    if not isinstance(ready_pool, list):
        raise ClosureError("review packet ready_pool must be a list")
    for row in ready_pool:
        if not isinstance(row, dict) or set(row) != PACKET_READY_ROW_FIELDS:
            raise ClosureError("review packet ready row fields are not exact")
        if any(
            not isinstance(row.get(key), str) or not str(row[key]).strip()
            for key in ("display_name", "cohort_id", "causal_cluster_id")
        ):
            raise ClosureError("review packet candidate provenance is missing")
        if any(
            re.fullmatch(r"[0-9a-f]{64}", str(row.get(key) or "")) is None
            for key in ("u2_candidate_row_hash", "u3_battery_row_hash")
        ):
            raise ClosureError("review packet candidate evidence digest is invalid")
    # governance-mutation: FUNNEL_CLOSURE_PACKET_HASH
    if packet.get("packet_hash") != funnel._hash(_without_hash(packet, "packet_hash")):
        raise ClosureError("review packet hash mismatch")
    authority = packet.get("authority") or {}
    if (
        authority.get("selection_owner") != "Junyan"
        or authority.get("identity_verification") != "UNAVAILABLE"
        or authority.get("production_authority") is not False
        or authority.get("required_selection_size") != {"min": 3, "max": 5}
    ):
        raise ClosureError("review packet authority boundary changed")
    control = packet.get("random_control") or {}
    if (
        control.get("algo") != funnel.CONTROL_ALGO
        or control.get("replay_verified") is not True
        or not str(control.get("control_batch_id") or "").startswith("CTRL_")
    ):
        raise ClosureError("review packet random-control evidence is invalid")
    if packet.get("claim_allowed") is not False:
        raise ClosureError("offline review packet cannot unlock a research claim")


def validate_review_receipt(receipt: Mapping[str, Any], packet: Mapping[str, Any]) -> None:
    validate_review_packet(packet)
    expected = {
        "schema", "schema_version", "receipt_class", "decision", "claimed_reviewer",
        "identity_verification", "production_authority", "packet_hash", "reviewed_at",
        "authorization_text", "selections", "receipt_hash", "disclaimer",
    }
    _require_exact_keys(receipt, expected, "review receipt")
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("schema_version") != SCHEMA_VERSION:
        raise ClosureError("review receipt schema/version mismatch")
    # governance-mutation: FUNNEL_CLOSURE_RECEIPT_PACKET_BINDING
    if receipt.get("packet_hash") != packet.get("packet_hash"):
        raise ClosureError("review receipt is not bound to this packet")
    # governance-mutation: FUNNEL_CLOSURE_RECEIPT_AUTHORITY
    if (
        receipt.get("decision") != RECEIPT_DECISION
        or receipt.get("claimed_reviewer") != "Junyan"
        or receipt.get("identity_verification") != "UNAVAILABLE"
        or receipt.get("production_authority") is not False
        or receipt.get("receipt_class") != RECEIPT_CLASS
    ):
        raise ClosureError("review receipt authority boundary changed")
    authorization = str(receipt.get("authorization_text") or "")
    if (
        len(authorization.strip()) < 20
        or str(packet["packet_hash"])[:12] not in authorization
        or not ("离线" in authorization or "offline" in authorization.casefold())
    ):
        raise ClosureError("review receipt authorization text is not packet-bound and offline-scoped")
    reviewed_at = _iso(receipt.get("reviewed_at"), "review receipt reviewed_at")
    packet_at = _iso(packet.get("generated_at"), "review packet generated_at")
    if reviewed_at < packet_at:
        raise ClosureError("review receipt must be timezone-aware and no earlier than its packet")
    selections = receipt.get("selections")
    if not isinstance(selections, list) or not 3 <= len(selections) <= 5:
        raise ClosureError("review receipt must select 3..5 securities")
    ready = {row["ts_code"] for row in packet.get("ready_pool", []) if row.get("ready") is True}
    codes: list[str] = []
    for row in selections:
        if not isinstance(row, dict) or set(row) != {"ts_code", "research_question", "selection_reason"}:
            raise ClosureError("review receipt selection fields are not exact")
        code = str(row.get("ts_code") or "").strip().upper()
        if (
            code not in ready
            or not str(row.get("research_question") or "").strip()
            or not str(row.get("selection_reason") or "").strip()
        ):
            raise ClosureError("review receipt selection is not backed by the ready pool")
        codes.append(code)
    if len(codes) != len(set(codes)):
        raise ClosureError("review receipt selections are duplicated")
    if receipt.get("receipt_hash") != funnel._hash(_without_hash(receipt, "receipt_hash")):
        raise ClosureError("review receipt hash mismatch")


def seal_review_receipt(draft: Mapping[str, Any], packet: Mapping[str, Any]) -> dict[str, Any]:
    """Hash canonical human-authored fields without supplying or inferring choices."""
    if "receipt_hash" in draft:
        raise ClosureError("review receipt draft must not predeclare receipt_hash")
    receipt = dict(draft)
    receipt["receipt_hash"] = funnel._hash(receipt)
    validate_review_receipt(receipt, packet)
    return receipt


def run_offline_replay(
    *, bundle_dir: Path, battery: Mapping[str, Any], packet: Mapping[str, Any],
    receipt: Mapping[str, Any], generated_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = load_bundle(bundle_dir)
    expected_packet = build_review_packet(
        bundle_dir=bundle_dir,
        battery=battery,
        generated_at=str(packet.get("generated_at") or ""),
    )
    # governance-mutation: FUNNEL_CLOSURE_PACKET_REBUILD
    if packet != expected_packet:
        raise ClosureError("review packet is not the deterministic projection of replay inputs")
    validate_review_receipt(receipt, packet)
    if packet["source_refs"] != {
        "run_id": str(
            battery.get("run_id")
            or ((battery.get("data") or {}).get("run_id") if isinstance(battery.get("data"), dict) else "")
            or ""
        ).strip(),
        "bundle_hash": bundle["manifest"]["bundle_hash"],
        "scan_rows_hash": bundle["scan"]["rows_hash"],
        "candidate_rows_hash": bundle["candidates"]["rows_hash"],
        "battery_hash": funnel._hash(battery),
        "ready_pool_hash": funnel._hash(packet["ready_pool"]),
    }:
        raise ClosureError("review packet source references do not match replay inputs")
    replay_at = _iso(generated_at, "replay generated_at")
    reviewed_at = _iso(receipt.get("reviewed_at"), "review receipt reviewed_at")
    # governance-mutation: FUNNEL_CLOSURE_REPLAY_CHRONOLOGY
    if replay_at < reviewed_at:
        raise ClosureError("replay generated_at cannot predate its review receipt")
    selections = receipt["selections"]
    selected = [row["ts_code"] for row in selections]
    questions = {row["ts_code"]: row["research_question"] for row in selections}
    try:
        queue = funnel.build_deep_research_queue(
            candidate_review=bundle["candidates"],
            battery=battery,
            selected_tickers=selected,
            trade_date=bundle["manifest"]["as_of"],
            generated_at=generated_at,
            research_questions=questions,
        )
    except funnel.FunnelError as exc:
        raise ClosureError(f"U4 replay failed: {exc}") from exc

    control = bundle["candidates"]["control_sampling_frame"]
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "mode": "OFFLINE_FIXTURE_REPLAY",
        "status": "PARTIAL",
        "experiment_verdict": "OFFLINE_REPLAY_COMPLETE_U5_BLOCKED",
        "as_of": bundle["manifest"]["as_of"],
        "generated_at": generated_at,
        "source_refs": {
            "bundle_hash": bundle["manifest"]["bundle_hash"],
            "packet_hash": packet["packet_hash"],
            "receipt_hash": receipt["receipt_hash"],
            "u4_rows_hash": queue["rows_hash"],
        },
        "u1_u2_discovery": {
            "status": "REPLAY_VERIFIED",
            "control_batch_id": control["control_batch_id"],
            "algo": control["algo"],
            "seed_hex": control["seed_hex"],
            "drawn_hash": funnel._hash(control["drawn"]),
            "statistical_verdict": "NOT_TESTED_OUTCOME_WINDOW_NOT_SUPPLIED",
        },
        "u3_battery": {
            "status": "SAME_DAY_COMPLETE_FOR_SELECTED_ROWS",
            "battery_hash": funnel._hash(battery),
            "selected_count": len(selected),
        },
        "u4_review": {
            "status": "READY_FOR_HUMAN_REVIEWED_FACTPACK_WORK",
            "selected_count": len(queue["rows"]),
            "selection_identity_verified": False,
            "production_authority": False,
        },
        "u5_handoff": {
            "status": "DATA_BLOCKED",
            "missing_outputs": ["factpack", "decision_sheet", "wrong_if", "cluster_id"],
            "next_gate": "JUNYAN_REVIEW_OF_COMPLETED_DEEP_RESEARCH",
        },
        "claim_allowed": False,
        "no_trade_flag": True,
        "disclaimer": DISCLAIMER,
    }
    report["report_hash"] = funnel._hash(report)
    validate_closure_report(report, packet, receipt, queue)
    return queue, report


def validate_closure_report(
    report: Mapping[str, Any], packet: Mapping[str, Any], receipt: Mapping[str, Any],
    queue: Mapping[str, Any],
) -> None:
    expected = {
        "schema", "schema_version", "mode", "status", "experiment_verdict", "as_of",
        "generated_at", "source_refs", "u1_u2_discovery", "u3_battery", "u4_review",
        "u5_handoff", "claim_allowed", "no_trade_flag", "disclaimer", "report_hash",
    }
    _require_exact_keys(report, expected, "closure report")
    if report.get("schema") != REPORT_SCHEMA or report.get("schema_version") != SCHEMA_VERSION:
        raise ClosureError("closure report schema/version mismatch")
    # governance-mutation: FUNNEL_CLOSURE_REPORT_HASH
    if report.get("report_hash") != funnel._hash(_without_hash(report, "report_hash")):
        raise ClosureError("closure report hash mismatch")
    refs = report.get("source_refs") or {}
    discovery = report.get("u1_u2_discovery") or {}
    u3 = report.get("u3_battery") or {}
    u4 = report.get("u4_review") or {}
    packet_control = packet.get("random_control") or {}
    # governance-mutation: FUNNEL_CLOSURE_REPORT_EVIDENCE
    if (
        refs.get("bundle_hash") != (packet.get("source_refs") or {}).get("bundle_hash")
        or refs.get("packet_hash") != packet.get("packet_hash")
        or refs.get("receipt_hash") != receipt.get("receipt_hash")
        or refs.get("u4_rows_hash") != queue.get("rows_hash")
        or discovery.get("control_batch_id") != packet_control.get("control_batch_id")
        or discovery.get("algo") != packet_control.get("algo")
        or discovery.get("seed_hex") != packet_control.get("seed_hex")
        or discovery.get("drawn_hash") != packet_control.get("drawn_hash")
        or u3.get("battery_hash") != (packet.get("source_refs") or {}).get("battery_hash")
        or u3.get("selected_count") != len(queue.get("rows") or [])
        or u4.get("selected_count") != len(queue.get("rows") or [])
    ):
        raise ClosureError("closure report evidence chain is broken")
    # governance-mutation: FUNNEL_CLOSURE_NO_CLAIM_OR_AUTHORITY
    if (
        report.get("claim_allowed") is not False
        or report.get("no_trade_flag") is not True
        or report.get("status") != "PARTIAL"
        or (report.get("u5_handoff") or {}).get("status") != "DATA_BLOCKED"
        or (report.get("u4_review") or {}).get("production_authority") is not False
        or funnel.FORBIDDEN_ACTION_KEYS.intersection(funnel._walk_keys(report))
    ):
        raise ClosureError("offline closure report acquired claim or trading authority")


def verify_result_bundle(output_dir: Path) -> dict[str, Any]:
    """Independently verify one immutable offline-closure result bundle."""
    if not output_dir.is_dir() or output_dir.is_symlink():
        raise ClosureError("result bundle must be a real directory")
    manifest = _load_object(output_dir / "manifest.json")
    artifacts = manifest.get("artifacts")
    frozen_bundle_dir = output_dir / "frozen_funnel_bundle"
    if not frozen_bundle_dir.is_dir() or frozen_bundle_dir.is_symlink():
        raise ClosureError("result bundle frozen source must be a real directory")
    entries = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file()
    }
    if any(path.is_symlink() for path in output_dir.rglob("*")):
        raise ClosureError("result bundle cannot contain symlinks")
    # governance-mutation: FUNNEL_CLOSURE_RESULT_MANIFEST_FIELDS
    if set(manifest) != RESULT_MANIFEST_FIELDS:
        raise ClosureError("result bundle manifest fields are not exact")
    if (
        manifest.get("schema") != "ar.research_closure_bundle"
        or manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("mode") != "OFFLINE_FIXTURE_REPLAY"
        or not isinstance(artifacts, dict)
        or set(artifacts) != RESULT_ARTIFACTS
        or entries != RESULT_ARTIFACTS | {"manifest.json"}
        or manifest.get("production_authority") is not False
        or manifest.get("claim_allowed") is not False
    ):
        raise ClosureError("result bundle manifest is invalid")
    # governance-mutation: FUNNEL_CLOSURE_RESULT_BUNDLE_HASH
    if manifest.get("bundle_hash") != funnel._hash(artifacts):
        raise ClosureError("result bundle_hash mismatch")
    for name, expected_hash in artifacts.items():
        path = output_dir / name
        # governance-mutation: FUNNEL_CLOSURE_RESULT_ARTIFACT_HASH
        if not path.is_file() or path.is_symlink() or _sha256_path(path) != expected_hash:
            raise ClosureError(f"result artifact hash mismatch: {name}")

    packet = _load_object(output_dir / "review_packet.json")
    receipt = _load_object(output_dir / "review_receipt.json")
    queue = _load_object(output_dir / "deep_research_queue.json")
    report = _load_object(output_dir / "closure_report.json")
    battery = _load_object(output_dir / "frozen_battery.json")
    frozen_bundle = load_bundle(frozen_bundle_dir)
    expected_packet = build_review_packet(
        bundle_dir=frozen_bundle_dir,
        battery=battery,
        generated_at=str(packet.get("generated_at") or ""),
    )
    expected_queue, expected_report = run_offline_replay(
        bundle_dir=frozen_bundle_dir,
        battery=battery,
        packet=packet,
        receipt=receipt,
        generated_at=str(report.get("generated_at") or ""),
    )
    # governance-mutation: FUNNEL_CLOSURE_RESULT_DETERMINISTIC
    if packet != expected_packet or queue != expected_queue or report != expected_report:
        raise ClosureError("result bundle is not the deterministic projection of frozen evidence")
    if (
        manifest.get("as_of") != report.get("as_of")
        or manifest.get("as_of") != frozen_bundle["manifest"].get("as_of")
    ):
        raise ClosureError("result bundle as_of does not match closure report")
    return {
        "status": "VERIFIED",
        "as_of": report["as_of"],
        "bundle_hash": manifest["bundle_hash"],
        "u4_rows": len(queue["rows"]),
        "u5_status": report["u5_handoff"]["status"],
        "claim_allowed": False,
        "production_authority": False,
    }


def _write_replay_outputs(
    output_dir: Path, source_bundle_dir: Path, battery: Mapping[str, Any],
    packet: Mapping[str, Any], receipt: Mapping[str, Any], queue: Mapping[str, Any],
    report: Mapping[str, Any],
) -> None:
    if os.path.lexists(output_dir):
        raise ClosureError(f"output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        load_bundle(source_bundle_dir)
        frozen_bundle_dir = staging / "frozen_funnel_bundle"
        frozen_bundle_dir.mkdir()
        for name in sorted(BUNDLE_ARTIFACTS | {"manifest.json"}):
            shutil.copyfile(source_bundle_dir / name, frozen_bundle_dir / name)
        _atomic_write_json(staging / "frozen_battery.json", dict(battery))
        payloads = {
            "review_packet.json": dict(packet),
            "review_receipt.json": dict(receipt),
            "deep_research_queue.json": dict(queue),
            "closure_report.json": dict(report),
        }
        for name, payload in payloads.items():
            _atomic_write_json(staging / name, payload)
        artifacts = {name: _sha256_path(staging / name) for name in sorted(RESULT_ARTIFACTS)}
        manifest = {
            "schema": "ar.research_closure_bundle",
            "schema_version": SCHEMA_VERSION,
            "as_of": report["as_of"],
            "mode": "OFFLINE_FIXTURE_REPLAY",
            "artifacts": artifacts,
            "bundle_hash": funnel._hash(artifacts),
            "production_authority": False,
            "claim_allowed": False,
            "disclaimer": DISCLAIMER,
        }
        _atomic_write_json(staging / "manifest.json", manifest)
        verify_result_bundle(staging)
        directory_fd = os.open(staging, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        os.replace(staging, output_dir)
        parent_fd = os.open(output_dir.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    packet_parser = subparsers.add_parser("packet")
    packet_parser.add_argument("--bundle", required=True)
    packet_parser.add_argument("--battery", required=True)
    packet_parser.add_argument("--generated-at", required=True)
    packet_parser.add_argument("--output", required=True)
    receipt_parser = subparsers.add_parser("receipt")
    receipt_parser.add_argument("--packet", required=True)
    receipt_parser.add_argument("--draft", required=True)
    receipt_parser.add_argument("--output", required=True)
    replay_parser = subparsers.add_parser("replay")
    replay_parser.add_argument("--bundle", required=True)
    replay_parser.add_argument("--battery", required=True)
    replay_parser.add_argument("--packet", required=True)
    replay_parser.add_argument("--receipt", required=True)
    replay_parser.add_argument("--generated-at", required=True)
    replay_parser.add_argument("--output-dir", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            receipt = verify_result_bundle(Path(args.output_dir))
            print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
            print(DISCLAIMER)
            return 0
        if args.command == "receipt":
            packet = _load_object(Path(args.packet))
            draft = _load_object(Path(args.draft))
            receipt = seal_review_receipt(draft, packet)
            output = Path(args.output)
            if os.path.lexists(output):
                raise ClosureError(f"output already exists: {output}")
            _atomic_write_json(output, receipt)
            print(DISCLAIMER)
            return 0
        battery = _load_object(Path(args.battery))
        if args.command == "packet":
            packet = build_review_packet(
                bundle_dir=Path(args.bundle), battery=battery, generated_at=args.generated_at,
            )
            output = Path(args.output)
            if os.path.lexists(output):
                raise ClosureError(f"output already exists: {output}")
            _atomic_write_json(output, packet)
        else:
            packet = _load_object(Path(args.packet))
            receipt = _load_object(Path(args.receipt))
            queue, report = run_offline_replay(
                bundle_dir=Path(args.bundle), battery=battery, packet=packet,
                receipt=receipt, generated_at=args.generated_at,
            )
            _write_replay_outputs(
                Path(args.output_dir), Path(args.bundle), battery,
                packet, receipt, queue, report,
            )
    except (ClosureError, ValueError) as exc:
        print(f"REFUSED: {exc}")
        return 1
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
