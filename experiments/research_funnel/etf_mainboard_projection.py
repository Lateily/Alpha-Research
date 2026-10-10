#!/usr/bin/env python3
"""Project a canonical full-market funnel onto a frozen ETF/main-board scope.

This module is intentionally outside the frozen Research Closed Loop V1.5
implementation.  It never changes a channel rule or recomputes a market rank:
it validates the full-market result, filters exact rows, and hands the existing
U2/U3 code a smaller derived registry inside an isolated workflow checkout.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import etf_mainboard_universe as scope_contract
import funnel_pipeline as fp
import semiconductor_inputs as semiconductor_evidence
from security_registry import _atomic_write_json, _date8, _sha256, validate_registry


SCHEMA_VERSION = "1.0"
RANK_BASIS = "FULL_REGISTRY_ELIGIBLE_THEN_SCOPE_FILTER"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise fp.FunnelError(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise fp.FunnelError(f"JSON root must be an object: {path}")
    return value


def _required_path(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise fp.FunnelError(f"required environment variable is missing: {name}")
    return Path(value)


def _registry_coverage(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "registry_rows": len(rows),
        "listed": sum(row.get("list_status") == "L" for row in rows),
        "delisted": sum(row.get("list_status") == "D" for row in rows),
        "prelisted": sum(row.get("list_status") == "P" for row in rows),
        "st_labeled": sum(row["qualification"].get("is_st") is True for row in rows),
        "bse_labeled": sum(row["qualification"].get("is_bse") is True for row in rows),
        "low_liquidity_labeled": sum(
            row["qualification"].get("liquidity_label") == "LOW" for row in rows
        ),
        "liquidity_data_blocked": sum(
            row["qualification"].get("liquidity_label") == "DATA_BLOCKED" for row in rows
        ),
        "preserved_missing_from_source": sum(
            row.get("source_presence") == "MISSING_PRESERVED" for row in rows
        ),
    }


def build_scoped_registry(
    *, registry: Mapping[str, Any], manifest: Mapping[str, Any],
    source_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive the exact scope registry without changing any issuer row."""
    full_registry = copy.deepcopy(dict(registry))
    validate_registry(full_registry)
    try:
        scope_contract.validate_manifest(manifest, full_registry, source_evidence)
    except scope_contract.UniverseError as exc:
        raise fp.FunnelError(f"ETF main-board scope is invalid: {exc}") from exc
    if manifest.get("target_trade_date") != full_registry.get("as_of"):
        raise fp.FunnelError("ETF main-board scope and registry dates differ")

    scope_codes = list(manifest.get("included_codes") or [])
    if len(scope_codes) != len(set(scope_codes)) or not scope_codes:
        raise fp.FunnelError("ETF main-board scope code set is empty or duplicated")
    by_code = {row["ts_code"]: row for row in full_registry["rows"]}
    missing = sorted(set(scope_codes) - set(by_code))
    if missing:
        raise fp.FunnelError(f"ETF main-board scope is absent from registry: {missing[:5]}")
    rows = [copy.deepcopy(by_code[code]) for code in sorted(scope_codes)]
    coverage = _registry_coverage(rows)
    source = copy.deepcopy(full_registry.get("source") or {})
    requires_partial = bool(
        source.get("errors")
        or coverage["preserved_missing_from_source"]
        or coverage["liquidity_data_blocked"]
    )
    eligible_codes = sorted(
        row["ts_code"] for row in rows
        if row["qualification"].get("u1_scan_eligible") is True
    )
    scoped = copy.deepcopy(full_registry)
    scoped.update({
        "status": "PARTIAL" if requires_partial else "COMPLETE",
        "coverage": coverage,
        "rows": rows,
        "registry_hash": _sha256(rows),
        "eligible_universe_hash": _sha256(eligible_codes),
    })
    validate_registry(scoped)
    return scoped


def project_scan(
    *, full_scan: Mapping[str, Any], full_registry: Mapping[str, Any],
    scoped_registry: Mapping[str, Any], manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Filter validated full-market rows; never recompute rank or triggers."""
    fp.validate_all_market_scan(full_scan, full_registry)
    validate_registry(copy.deepcopy(dict(scoped_registry)))
    if full_scan.get("as_of") != manifest.get("target_trade_date"):
        raise fp.FunnelError("full-market scan and ETF scope dates differ")
    manifest_codes = set(manifest.get("included_codes") or [])
    registry_codes = {row["ts_code"] for row in scoped_registry["rows"]}
    if manifest_codes != registry_codes:
        raise fp.FunnelError("scoped registry differs from the ETF manifest")
    eligible_codes = {
        row["ts_code"] for row in scoped_registry["rows"]
        if row["qualification"].get("u1_scan_eligible") is True
    }
    rows = [
        copy.deepcopy(row) for row in full_scan["rows"]
        if row["ts_code"] in eligible_codes
    ]
    seen = Counter((row["ts_code"], row["channel"]) for row in rows)
    expected_pairs = {(code, channel) for code in eligible_codes for channel in fp.CHANNELS}
    if set(seen) != expected_pairs or any(count != 1 for count in seen.values()):
        raise fp.FunnelError(
            "ETF projection requires exactly six canonical rows per eligible security"
        )
    blocked = Counter(
        row["channel"] for row in rows if row.get("data_status") != "COMPLETE"
    )
    triggered = Counter(row["channel"] for row in rows if row.get("triggered") is True)
    projected = copy.deepcopy(dict(full_scan))
    projected.update({
        "status": "PARTIAL" if blocked else "COMPLETE",
        "eligible_universe_hash": scoped_registry["eligible_universe_hash"],
        "coverage": {
            "eligible": len(eligible_codes),
            "rows": len(rows),
            "expected_rows": len(eligible_codes) * len(fp.CHANNELS),
            "blocked_by_channel": dict(sorted(blocked.items())),
            "triggered_by_channel": dict(sorted(triggered.items())),
        },
        "rows": rows,
        "rows_hash": fp._hash(rows),
    })
    fp.validate_all_market_scan(projected, scoped_registry)
    return projected


def build_projection_receipt(
    *, full_registry: Mapping[str, Any], scoped_registry: Mapping[str, Any],
    manifest: Mapping[str, Any], source_evidence: Mapping[str, Any],
    full_scan: Mapping[str, Any], scoped_scan: Mapping[str, Any], run_id: str,
) -> dict[str, Any]:
    receipt = {
        "schema": "ar.etf_mainboard_funnel_projection_receipt",
        "schema_version": SCHEMA_VERSION,
        "target_trade_date": scoped_scan["as_of"],
        "run_id": run_id,
        "rank_basis": RANK_BASIS,
        "scope": {
            "tracking_indices": list(manifest.get("tracking_indices") or []),
            "market": "SSE_AND_SZSE_MAIN_BOARD_ONLY",
            "included_count": len(manifest.get("included_codes") or []),
        },
        "bindings": {
            "full_registry_hash": full_registry["registry_hash"],
            "scoped_registry_hash": scoped_registry["registry_hash"],
            "scope_manifest_hash": manifest["manifest_hash"],
            "scope_source_hash": source_evidence["source_hash"],
            "full_scan_rows_hash": full_scan["rows_hash"],
            "scoped_scan_rows_hash": scoped_scan["rows_hash"],
        },
        "authority": {
            "u4_selection": False,
            "paper_registration": False,
            "paper_order": False,
            "production_publication": False,
            "real_trade": False,
        },
        "disclaimer": fp.DISCLAIMER,
    }
    receipt["receipt_hash"] = fp._hash(receipt)
    return receipt


def run_candidates() -> int:
    import funnel_dag as dag

    target, run_id, _root, bundle_dir, public_v2 = dag._context()
    if os.path.lexists(bundle_dir):
        raise fp.FunnelError(f"isolated funnel bundle already exists: {bundle_dir}")
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    feature_db = Path(os.environ.get("AR_FEATURE_STORE_DB") or dag.REPO_ROOT / "data_history" / "feature_store.sqlite3")
    full_registry = _load_json(public_v2 / "security_registry.json")
    e1 = _load_json(public_v2 / "e1_event_layer.json")
    rotation_path = public_v2 / "rotation_panel.json"
    rotation = _load_json(rotation_path) if rotation_path.is_file() else None
    manifest = _load_json(_required_path("AR_FUNNEL_UNIVERSE_MANIFEST"))
    source_evidence = _load_json(_required_path("AR_FUNNEL_UNIVERSE_SOURCE"))
    features = fp.load_feature_snapshot(feature_db, target)

    has_semiconductor_scope = any(
        row.get("industry_key") == semiconductor_evidence.SEMICONDUCTOR_INDUSTRY_KEY
        and row.get("qualification", {}).get("u1_scan_eligible") is True
        for row in full_registry["rows"]
    )
    try:
        semiconductor_inputs = (
            semiconductor_evidence.build_snapshot(feature_db, full_registry, target)
            if has_semiconductor_scope else None
        )
    except semiconductor_evidence.SemiconductorInputError as exc:
        raise fp.FunnelError(f"semiconductor positive inputs are invalid: {exc}") from exc
    taxonomy = _load_json(dag.INDUSTRY_TAXONOMY_PATH) if has_semiconductor_scope else None
    full_scan = fp.build_all_market_scan(
        registry=full_registry, e1_events=e1, features=features,
        rotation=rotation, macro_industry=None,
        semiconductor_inputs=semiconductor_inputs, industry_taxonomy=taxonomy,
        trade_date=target, generated_at=generated_at,
    )
    scoped_registry = build_scoped_registry(
        registry=full_registry, manifest=manifest, source_evidence=source_evidence,
    )
    scoped_scan = project_scan(
        full_scan=full_scan, full_registry=full_registry,
        scoped_registry=scoped_registry, manifest=manifest,
    )
    candidates = fp.build_candidate_review(
        registry=scoped_registry, scan=scoped_scan, features=features,
        trade_date=target, generated_at=generated_at, target_size=100,
    )
    candidate_manifest = fp.build_candidate_manifest(
        candidate_review=candidates, scan=scoped_scan, run_id=run_id,
    )
    fp.validate_candidate_manifest(candidate_manifest)
    receipt = build_projection_receipt(
        full_registry=full_registry, scoped_registry=scoped_registry,
        manifest=manifest, source_evidence=source_evidence,
        full_scan=full_scan, scoped_scan=scoped_scan, run_id=run_id,
    )

    dag._write_stage(
        bundle_dir, "candidates",
        {
            "all_market_scan.json": scoped_scan,
            "candidate_review.json": candidates,
            "candidate_manifest.json": candidate_manifest,
        },
        as_of=target, run_id=run_id, generated_at=generated_at,
        binds={"candidate_manifest_hash": candidate_manifest["manifest_hash"]},
    )
    _atomic_write_json(_required_path("AR_FUNNEL_SCOPE_REGISTRY"), scoped_registry)
    _atomic_write_json(_required_path("AR_FUNNEL_FULL_SCAN"), full_scan)
    _atomic_write_json(_required_path("AR_FUNNEL_PROJECTION_RECEIPT"), receipt)
    dag._write_stage_receipt(
        public_v2, "candidates", bundle_dir,
        as_of=target, run_id=run_id, generated_at=generated_at,
    )
    print(json.dumps({
        "step": "etf_mainboard_projection_candidates",
        "target_trade_date": target,
        "run_id": run_id,
        "full_market_eligible": full_scan["coverage"]["eligible"],
        "scope_registry_rows": scoped_registry["coverage"]["registry_rows"],
        "scope_eligible": scoped_scan["coverage"]["eligible"],
        "candidate_rows": candidate_manifest["expected_count"],
        "projection_receipt_hash": receipt["receipt_hash"],
    }, ensure_ascii=False))
    print(fp.DISCLAIMER)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("candidates",))
    args = parser.parse_args(argv)
    if args.command == "candidates":
        return run_candidates()
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
