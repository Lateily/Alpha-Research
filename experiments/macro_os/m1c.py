#!/usr/bin/env python3
"""Macro OS M1-C: production wiring for M0-B3 -> M1-A -> M1-B.

M1-C runs inside nightly-v4 staging.  It may refresh a due M0-B3 release
schedule, always rebuilds the M1-A/M1-B read-only contracts, and writes one
hash-bound manifest last.  Evidence gaps are published as data quality; only
contract, integrity, or authority violations fail the pipeline.

Calibration remains non-enforceable.  This module cannot emit a trade action,
direct block, formal regime, or automatic order instruction.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.macro_os import collectors, contracts, m0b3, m1a, m1b
from experiments.macro_os.storage import MacroHistoryStore, MacroStoreError


SCHEMA_VERSION = "1.0"
FORMULA_VERSION = "macro-m1c/1.0"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "public" / "data" / "v2" / "macro"
DEFAULT_PORTFOLIO = REPO_ROOT / "public" / "data" / "v2" / "model_portfolio_state.json"
DEFAULT_CALENDAR = DEFAULT_OUTPUT_DIR / "release_calendar.json"
DEFAULT_MARKET_FEATURES = DEFAULT_OUTPUT_DIR / "market_features.json"
DISCLAIMER = "不是买卖指令;研究信号,human executes."
POLICY = {
    "formal_blocking_authority": False,
    "allowed_outputs": ["LABEL", "RISK_BUDGET_CONTEXT", "RESEARCH_PRIORITY"],
    "forbidden_outputs": ["TRADE_ACTION", "DIRECT_BLOCK", "FORMAL_REGIME_CLAIM"],
}
QUALITY = {"COMPLETE": 0, "PARTIAL": 1, "DATA_BLOCKED": 2}
COMPONENTS = ("m0b", "m0b3", "m1a", "m1b")
FORBIDDEN_KEYS = {item.casefold() for item in POLICY["forbidden_outputs"]}


class M1CError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha256_path(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise M1CError("clock must include a timezone")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _iso(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise M1CError(f"{label} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise M1CError(f"{label} is not valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise M1CError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _target_date(value: Any) -> str:
    text = str(value or "")
    if not re.fullmatch(r"[0-9]{8}", text):
        raise M1CError("target_trade_date must be YYYYMMDD")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise M1CError("target_trade_date is not a real date") from exc
    return text


def _walk_authority(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in FORBIDDEN_KEYS:
                raise M1CError(f"forbidden M1-C output field: {key}")
            if str(key) in {"enforceable", "formal_blocking_authority"} and child is not False:
                raise M1CError(f"M1-C calibration authority changed at {key}")
            _walk_authority(child)
    elif isinstance(value, list):
        for child in value:
            _walk_authority(child)


def _aggregate_quality(values: list[str]) -> str:
    if not values or any(value not in QUALITY for value in values):
        raise M1CError("component data quality is invalid")
    states = set(values)
    if states == {"COMPLETE"}:
        return "COMPLETE"
    if states == {"DATA_BLOCKED"}:
        return "DATA_BLOCKED"
    return "PARTIAL"


def _artifact_hashes(root: Path, names: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in names:
        path = root / name
        if not path.is_file():
            raise M1CError(f"declared Macro artifact is missing: {name}")
        result[name] = _sha256_path(path)
    return result


def _component(
    *, status: str, data_quality: str, run_id: str | None, reason: str,
    artifacts: Mapping[str, str],
) -> dict[str, Any]:
    if data_quality not in QUALITY:
        raise M1CError("component quality is invalid")
    return {
        "pipeline_status": "OK",
        "status": status,
        "data_quality": data_quality,
        "run_id": run_id,
        "reason": reason,
        "artifacts": dict(artifacts),
    }


def _m0b_component(
    *, output_dir: Path, db_path: Path, now: datetime, run_id: str,
    transport: collectors.Transport,
) -> dict[str, Any]:
    store = MacroHistoryStore(db_path)
    store.initialize()
    problems = store.verify_integrity()
    if problems:
        raise M1CError(f"macro history integrity failed before M0-B: {problems[:3]}")
    specs = collectors.collection_plan()
    collectors.collect(
        store=store,
        transport=transport,
        specs=specs,
        run_id=run_id + "_m0b",
        now=now,
    )
    health = collectors.build_health(store=store, specs=specs, now=now)
    health_path = output_dir / "source_health.json"
    collectors.write_health(health_path, health)
    problems = store.verify_integrity()
    if problems:
        raise M1CError(f"macro history integrity failed after M0-B: {problems[:3]}")
    return _component(
        status="REFRESHED",
        data_quality=health["report"],
        run_id=run_id,
        reason="M0B_STABLE_SOURCE_CYCLE_COMPLETED",
        artifacts=_artifact_hashes(output_dir, ["source_health.json"]),
    )


def _m0b3_component(
    *, output_dir: Path, db_path: Path, calendar_path: Path, now: datetime,
    run_id: str, force: bool, transport: collectors.Transport,
) -> dict[str, Any]:
    if not calendar_path.is_file():
        return _component(
            status="DATA_BLOCKED",
            data_quality="DATA_BLOCKED",
            run_id=None,
            reason="RELEASE_CALENDAR_NOT_PUBLISHED",
            artifacts={},
        )

    calendar = contracts.load_json(calendar_path)
    rules = m0b3.load_rules()
    store = MacroHistoryStore(db_path)
    store.initialize()
    problems = store.verify_integrity()
    if problems:
        raise M1CError(f"macro history integrity failed before M0-B3: {problems[:3]}")
    m0b3.validate_calendar(calendar, store)

    discovery_path = output_dir / "release_discovery_status.json"
    scheduler_path = output_dir / "scheduler_status.json"
    manifest_path = output_dir / "m0b3_run_manifest.json"
    # Use the exact lock name from the standalone M0-B3 CLI so launchd and the
    # nightly refresh cannot run one discovery cycle concurrently.
    lock_path = db_path.parent / "macro_os.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return _component(
                status="DATA_BLOCKED",
                data_quality="DATA_BLOCKED",
                run_id=None,
                reason="M0B3_REFRESH_ALREADY_RUNNING",
                artifacts={},
            )
        due = m0b3._should_run(
            calendar=calendar,
            rules=rules,
            scheduler_path=scheduler_path,
            discovery_path=discovery_path,
            manifest_path=manifest_path,
            now=now,
            force=force,
        )
        if due:
            manifest = m0b3.run_production_cycle(
                store=store,
                transport=transport,
                calendar=calendar,
                rules=rules,
                now=now,
                run_id=run_id,
                discovery_output=discovery_path,
                scheduler_output=scheduler_path,
                manifest_output=manifest_path,
            )
            status = "REFRESHED"
            reason = "M0B3_DUE_CYCLE_COMPLETED"
        else:
            manifest = contracts.load_json(manifest_path)
            status = "REUSED_NOT_DUE"
            reason = "M0B3_NEXT_CHECK_NOT_DUE"

    artifacts = _artifact_hashes(
        output_dir,
        ["release_discovery_status.json", "scheduler_status.json", "m0b3_run_manifest.json"],
    )
    return _component(
        status=status,
        data_quality=manifest["report"],
        run_id=manifest["run_id"],
        reason=reason,
        artifacts=artifacts,
    )


def _risk_budget_annotation(risk: Mapping[str, Any]) -> dict[str, Any]:
    data = risk.get("data") or {}
    candidate = data.get("candidate_state")
    context = data.get("risk_budget_context")
    reduced = context == "REDUCED_REVIEW_BUDGET"
    return {
        "candidate_state": candidate,
        "source_context": context,
        "new_position_ceiling": "STARTER_CAPPED" if reduced else "UNCHANGED",
        "research_priority": "REVIEW_RISK_FIRST" if reduced else "UNCHANGED",
        "enforceable": False,
        "formal_blocking_authority": False,
        "reason": (
            "CALIBRATION_RISK_BUDGET_ONLY"
            if reduced
            else "CALIBRATION_NO_BUDGET_REDUCTION"
        ),
    }


def _validate_source_health(payload: Any) -> None:
    expected = {
        "schema", "schema_version", "report", "mode", "as_of", "generated_at",
        "source_registry_hash", "policy", "source_health", "data", "disclaimer",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise M1CError("M1-C source_health fields differ from M0-B v1")
    sources = contracts.load_json(contracts.SOURCE_REGISTRY)
    contracts.validate_source_registry(sources)
    if (
        payload["schema"] != "ar.macro.source_health"
        or payload["schema_version"] != "1.0"
        or payload["mode"] != "CALIBRATING"
        or payload["source_registry_hash"] != sources["registry_hash"]
    ):
        raise M1CError("M1-C source_health identity differs from M0-B")
    _iso(payload["as_of"], "source_health.as_of")
    if payload["generated_at"] != payload["as_of"]:
        raise M1CError("M1-C source_health generated_at/as_of mismatch")
    rows = payload["data"]
    if not isinstance(rows, list) or not rows:
        raise M1CError("M1-C source_health has no metric rows")
    statuses = [str(row.get("status") or "") for row in rows if isinstance(row, dict)]
    if len(statuses) != len(rows):
        raise M1CError("M1-C source_health contains a non-object row")
    expected_report = (
        "COMPLETE"
        if statuses and all(status == "OK" for status in statuses)
        else "PARTIAL"
        if any(status in {"OK", "STALE"} for status in statuses)
        else "DATA_BLOCKED"
    )
    if payload["report"] != expected_report:
        raise M1CError("M1-C source_health report differs from metric statuses")
    expected_counts = {
        "ok": sum(status == "OK" for status in statuses),
        "stale": sum(status == "STALE" for status in statuses),
        "blocked_or_failed": sum(status not in {"OK", "STALE"} for status in statuses),
        "total": len(statuses),
    }
    if payload["source_health"] != expected_counts:
        raise M1CError("M1-C source_health counts differ from metric statuses")
    source_policy = payload["policy"]
    if (
        not isinstance(source_policy, dict)
        or source_policy.get("formal_blocking_authority") is not False
        or set(source_policy.get("allowed_outputs") or []) - {"LABEL", "RISK_BUDGET_CONTEXT"}
        or set(source_policy.get("forbidden_outputs") or [])
        != {"TRADE_ACTION", "DIRECT_BLOCK", "REGIME_CLAIM"}
    ):
        raise M1CError("M1-C source_health calibration policy changed")


def validate_run(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir)
    manifest_path = root / "m1c_run_manifest.json"
    payload = contracts.load_json(manifest_path)
    expected = {
        "schema", "schema_version", "report", "data_quality", "pipeline_status",
        "mode", "run_id", "target_trade_date", "as_of", "generated_at",
        "formula_version", "components", "artifacts", "degraded_components",
        "risk_budget_annotation", "policy", "disclaimer",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise M1CError("M1-C manifest fields differ from v1")
    if (
        payload["schema"] != "ar.macro.m1c_run_manifest"
        or payload["schema_version"] != SCHEMA_VERSION
        or payload["pipeline_status"] != "OK"
        or payload["mode"] != "CALIBRATING"
        or payload["formula_version"] != FORMULA_VERSION
        or payload["policy"] != POLICY
        or payload["disclaimer"] != DISCLAIMER
    ):
        raise M1CError("M1-C manifest identity or authority mismatch")
    _target_date(payload["target_trade_date"])
    as_of = _iso(payload["as_of"], "manifest.as_of")
    generated = _iso(payload["generated_at"], "manifest.generated_at")
    if as_of != generated:
        raise M1CError("M1-C generated_at must equal its point-in-time as_of")
    if not isinstance(payload["run_id"], str) or not payload["run_id"]:
        raise M1CError("M1-C manifest lacks run_id")
    if not isinstance(payload["components"], dict) or set(payload["components"]) != set(COMPONENTS):
        raise M1CError("M1-C component set differs from v1")

    component_qualities: list[str] = []
    declared_artifacts: dict[str, str] = {}
    for name in COMPONENTS:
        row = payload["components"][name]
        fields = {"pipeline_status", "status", "data_quality", "run_id", "reason", "artifacts"}
        if not isinstance(row, dict) or set(row) != fields:
            raise M1CError(f"M1-C component {name} fields differ from v1")
        if row["pipeline_status"] != "OK" or row["data_quality"] not in QUALITY:
            raise M1CError(f"M1-C component {name} status is invalid")
        if not isinstance(row["reason"], str) or not row["reason"]:
            raise M1CError(f"M1-C component {name} lacks reason")
        if not isinstance(row["artifacts"], dict):
            raise M1CError(f"M1-C component {name} artifacts are invalid")
        component_qualities.append(row["data_quality"])
        for artifact, expected_hash in row["artifacts"].items():
            if artifact in declared_artifacts:
                raise M1CError(f"M1-C artifact is declared by multiple components: {artifact}")
            if not re.fullmatch(r"[0-9a-f]{64}", str(expected_hash)):
                raise M1CError(f"M1-C artifact hash is invalid: {artifact}")
            declared_artifacts[artifact] = expected_hash

    m0_component = payload["components"]["m0b"]
    if set(m0_component["artifacts"]) != {"source_health.json"}:
        raise M1CError("M1-C M0-B component artifact set differs from v1")
    source_health = contracts.load_json(root / "source_health.json")
    _validate_source_health(source_health)
    if (
        m0_component["status"] != "REFRESHED"
        or m0_component["run_id"] != payload["run_id"]
        or m0_component["data_quality"] != source_health["report"]
    ):
        raise M1CError("M1-C M0-B component differs from source_health")
    expected_m1a_artifacts = {
        "macro_state.json", "macro_risk_gate.json", "macro_events.json", "m1a_run_manifest.json"
    }
    expected_m1b_artifacts = {
        "industry_macro_sensitivity.json", "portfolio_macro_exposure.json",
        "macro_panel.json", "m1b_run_manifest.json",
    }
    if set(payload["components"]["m1a"]["artifacts"]) != expected_m1a_artifacts:
        raise M1CError("M1-C M1-A component artifact set differs from v1")
    if set(payload["components"]["m1b"]["artifacts"]) != expected_m1b_artifacts:
        raise M1CError("M1-C M1-B component artifact set differs from v1")
    m0b3_component = payload["components"]["m0b3"]
    m0b3_expected = {
        "release_discovery_status.json", "scheduler_status.json", "m0b3_run_manifest.json"
    }
    if m0b3_component["artifacts"]:
        if set(m0b3_component["artifacts"]) != m0b3_expected:
            raise M1CError("M1-C M0-B3 component artifact set differs from v1")
        rules = m0b3.load_rules()
        discovery = contracts.load_json(root / "release_discovery_status.json")
        scheduler = contracts.load_json(root / "scheduler_status.json")
        m0b3_manifest = contracts.load_json(root / "m0b3_run_manifest.json")
        m0b3.validate_discovery_status(discovery, rules)
        m0b3.validate_scheduler_status(scheduler)
        if (
            m0b3_manifest.get("run_id") != m0b3_component["run_id"]
            or m0b3_manifest.get("report") != m0b3_component["data_quality"]
            or m0b3_manifest.get("policy") != m0b3.POLICY
            or m0b3_manifest.get("artifacts")
            != {
                "release_discovery_status.json": _sha256_path(root / "release_discovery_status.json"),
                "scheduler_status.json": _sha256_path(root / "scheduler_status.json"),
            }
        ):
            raise M1CError("M1-C M0-B3 component differs from its child manifest")
    elif not (
        m0b3_component["status"] == "DATA_BLOCKED"
        and m0b3_component["data_quality"] == "DATA_BLOCKED"
        and m0b3_component["run_id"] is None
        and m0b3_component["reason"]
        in {"RELEASE_CALENDAR_NOT_PUBLISHED", "M0B3_REFRESH_ALREADY_RUNNING"}
    ):
        raise M1CError("M1-C M0-B3 no-artifact state is invalid")

    expected_quality = _aggregate_quality(component_qualities)
    if payload["report"] != expected_quality or payload["data_quality"] != expected_quality:
        raise M1CError("M1-C report/data_quality do not match component evidence")
    degraded = [name for name in COMPONENTS if payload["components"][name]["data_quality"] != "COMPLETE"]
    if payload["degraded_components"] != degraded:
        raise M1CError("M1-C degraded_components do not match component evidence")
    if payload["artifacts"] != declared_artifacts:
        raise M1CError("M1-C top-level artifact map differs from component declarations")
    for artifact, expected_hash in declared_artifacts.items():
        path = root / artifact
        if not path.is_file() or _sha256_path(path) != expected_hash:
            raise M1CError(f"M1-C artifact is missing or hash-mismatched: {artifact}")

    m1a_manifest = m1a.validate_run(root)
    m1b_manifest = m1b.validate_run(root)
    if m1a_manifest["run_id"] != payload["run_id"] or m1b_manifest["run_id"] != payload["run_id"]:
        raise M1CError("M1-A/M1-B do not belong to the M1-C run")
    if m1a_manifest["as_of"] != payload["as_of"] or m1b_manifest["as_of"] != payload["as_of"]:
        raise M1CError("M1-A/M1-B do not share the M1-C point-in-time snapshot")
    if (
        m1b_manifest["source_m1a_run_id"] != payload["run_id"]
        or m1b_manifest["source_portfolio_run_id"] != payload["run_id"]
    ):
        raise M1CError("M1-B source bundle is not from the current M1-C run")
    if payload["components"]["m1a"]["run_id"] != payload["run_id"]:
        raise M1CError("M1-C M1-A component run_id mismatch")
    if payload["components"]["m1b"]["run_id"] != payload["run_id"]:
        raise M1CError("M1-C M1-B component run_id mismatch")
    risk = contracts.load_json(root / "macro_risk_gate.json")
    if payload["risk_budget_annotation"] != _risk_budget_annotation(risk):
        raise M1CError("M1-C risk-budget annotation differs from M1-A evidence")
    _walk_authority(payload)
    return payload


def run(
    *, db_path: str | Path, output_dir: str | Path, portfolio_path: str | Path,
    calendar_path: str | Path, market_features_path: str | Path | None,
    as_of: datetime, run_id: str, target_trade_date: str,
    force_collection: bool = False,
    transport: collectors.Transport | None = None,
) -> dict[str, Any]:
    if not isinstance(run_id, str) or not run_id:
        raise M1CError("run_id is required")
    target = _target_date(target_trade_date)
    if as_of.tzinfo is None:
        raise M1CError("as_of clock must include a timezone")
    now = as_of.astimezone(timezone.utc)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    portfolio = contracts.load_json(portfolio_path)
    if portfolio.get("run_id") != run_id:
        raise M1CError("portfolio contract is not from the current nightly run")
    if str(portfolio.get("target_trade_date") or "")[:8] != target:
        raise M1CError("portfolio target_trade_date differs from the nightly target")

    selected_transport = transport or collectors.UrllibTransport()
    m0_component = _m0b_component(
        output_dir=output,
        db_path=Path(db_path),
        now=now,
        run_id=run_id,
        transport=selected_transport,
    )
    m0b3_component = _m0b3_component(
        output_dir=output,
        db_path=Path(db_path),
        calendar_path=Path(calendar_path),
        now=now,
        run_id=run_id,
        force=force_collection,
        transport=selected_transport,
    )
    m1a_manifest = m1a.run(
        db_path=db_path,
        rules_path=m1a.RULES_PATH,
        market_features_path=(
            market_features_path
            if market_features_path and Path(market_features_path).is_file()
            else None
        ),
        output_dir=output,
        as_of=now,
        run_id=run_id,
    )
    m1a_names = ["macro_state.json", "macro_risk_gate.json", "macro_events.json", "m1a_run_manifest.json"]
    m1a_component = _component(
        status="GENERATED",
        data_quality=m1a_manifest["report"],
        run_id=run_id,
        reason="M1A_POINT_IN_TIME_CONTRACTS_GENERATED",
        artifacts=_artifact_hashes(output, m1a_names),
    )

    m1b_manifest = m1b.run(
        m1a_dir=output,
        portfolio_path=portfolio_path,
        spec_path=m1b.SPEC_PATH,
        output_dir=output,
        as_of=now,
        run_id=run_id,
    )
    m1b_names = [
        "industry_macro_sensitivity.json",
        "portfolio_macro_exposure.json",
        "macro_panel.json",
        "m1b_run_manifest.json",
    ]
    m1b_component = _component(
        status="GENERATED",
        data_quality=m1b_manifest["report"],
        run_id=run_id,
        reason="M1B_READ_ONLY_CONSUMERS_GENERATED",
        artifacts=_artifact_hashes(output, m1b_names),
    )

    components = {
        "m0b": m0_component,
        "m0b3": m0b3_component,
        "m1a": m1a_component,
        "m1b": m1b_component,
    }
    quality = _aggregate_quality([components[name]["data_quality"] for name in COMPONENTS])
    artifacts = {
        artifact: expected_hash
        for name in COMPONENTS
        for artifact, expected_hash in components[name]["artifacts"].items()
    }
    risk = contracts.load_json(output / "macro_risk_gate.json")
    manifest = {
        "schema": "ar.macro.m1c_run_manifest",
        "schema_version": SCHEMA_VERSION,
        "report": quality,
        "data_quality": quality,
        "pipeline_status": "OK",
        "mode": "CALIBRATING",
        "run_id": run_id,
        "target_trade_date": target,
        "as_of": _utc(now),
        "generated_at": _utc(now),
        "formula_version": FORMULA_VERSION,
        "components": components,
        "artifacts": artifacts,
        "degraded_components": [
            name for name in COMPONENTS if components[name]["data_quality"] != "COMPLETE"
        ],
        "risk_budget_annotation": _risk_budget_annotation(risk),
        "policy": dict(POLICY),
        "disclaimer": DISCLAIMER,
    }
    _walk_authority(manifest)
    m1a.write_json(output / "m1c_run_manifest.json", manifest)
    return validate_run(output)


def selftest() -> None:
    # governance-mutation: MACRO_M1C_CALIBRATION_AUTHORITY
    probe = {
        "policy": dict(POLICY),
        "risk_budget_annotation": {"enforceable": True},
    }
    try:
        _walk_authority(probe)
    except M1CError:
        pass
    else:
        raise M1CError("M1-C calibration authority canary did not fail")
    if _aggregate_quality(["COMPLETE", "PARTIAL"]) != "PARTIAL":
        raise M1CError("M1-C quality aggregation failed")
    print("macro_m1c selftest: 2/2")


def _default_db() -> Path:
    configured = os.environ.get("AR_MACRO_DB", "").strip()
    return Path(configured) if configured else REPO_ROOT / "data_history" / "macro_os.sqlite3"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(_default_db()))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--portfolio", default=str(DEFAULT_PORTFOLIO))
    parser.add_argument("--calendar", default=str(DEFAULT_CALENDAR))
    parser.add_argument("--market-features", default=str(DEFAULT_MARKET_FEATURES))
    parser.add_argument("--as-of")
    parser.add_argument("--run-id")
    parser.add_argument("--target-trade-date")
    parser.add_argument("--force-collection", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.selftest:
            selftest()
            return 0
        if args.validate_only:
            manifest = validate_run(args.output_dir)
        else:
            now = _iso(args.as_of, "as_of") if args.as_of else datetime.now(timezone.utc)
            run_id = args.run_id or os.environ.get("AR_RUN_ID", "").strip()
            target = args.target_trade_date or os.environ.get("AR_TARGET_TRADE_DATE", "").strip()
            manifest = run(
                db_path=args.db,
                output_dir=args.output_dir,
                portfolio_path=args.portfolio,
                calendar_path=args.calendar,
                market_features_path=args.market_features,
                as_of=now,
                run_id=run_id,
                target_trade_date=target,
                force_collection=args.force_collection,
            )
        print(
            f"macro_m1c: pipeline=OK data_quality={manifest['data_quality']} "
            f"mode=CALIBRATING run_id={manifest['run_id']}"
        )
        # A structurally valid DATA_BLOCKED package is publishable evidence, not
        # a process failure.  The nightly artifact validator lifts data_quality.
        return 0
    except (
        M1CError, m0b3.M0B3Error, m1a.M1AError, m1b.M1BError,
        MacroStoreError, contracts.ContractError, OSError, ValueError,
    ) as exc:
        print(f"macro_m1c: REFUSED {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
