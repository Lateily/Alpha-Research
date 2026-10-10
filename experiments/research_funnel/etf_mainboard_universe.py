#!/usr/bin/env python3
"""Freeze a main-board-only union of approved ETF tracking-index constituents.

The manifest is a research scope, not a recommendation or selection.  It binds
the provider snapshots to the same-day security registry and keeps every
exclusion explicit so a board, listing, ST, or identity gap cannot disappear.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from security_registry import (
    ST_RE,
    TS_CODE_RE,
    _atomic_write_json,
    _date8,
    _tushare_call,
    fetch_stock_basic,
    validate_registry,
)


SCHEMA = "ar.etf_mainboard_universe"
SCHEMA_VERSION = "1.0"
INDEX_CODES = ("399976.SZ", "930997.CSI")
SOURCE = "tushare.index_weight"
SOURCE_SCHEMA = "ar.etf_mainboard_universe_source"
SOURCE_SCHEMA_VERSION = "1.0"
MAX_SNAPSHOT_AGE_DAYS = 45
DISCLAIMER = "研究范围，不是买卖指令；human selects at U3/U4."


class UniverseError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _normalized_snapshot(
    index_code: str, rows: Sequence[Mapping[str, Any]], target: str,
) -> tuple[str, list[dict[str, Any]]]:
    if index_code not in INDEX_CODES:
        raise UniverseError(f"unsupported tracking index: {index_code}")
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise UniverseError(f"{index_code}: index row is not an object")
        row_index = str(raw.get("index_code") or index_code).strip().upper()
        if row_index != index_code:
            raise UniverseError(f"{index_code}: row belongs to another index")
        code = str(raw.get("con_code") or "").strip().upper()
        trade_date = _date8(str(raw.get("trade_date") or ""))
        try:
            weight = float(raw.get("weight"))
        except (TypeError, ValueError) as exc:
            raise UniverseError(f"{index_code}: invalid weight for {code}") from exc
        if not code or not math.isfinite(weight) or weight < 0:
            raise UniverseError(f"{index_code}: invalid constituent row")
        if trade_date <= target:
            normalized.append({
                "index_code": index_code,
                "con_code": code,
                "trade_date": trade_date,
                "weight": weight,
            })
    if not normalized:
        raise UniverseError(f"{index_code}: no constituent snapshot on or before {target}")
    snapshot_date = max(row["trade_date"] for row in normalized)
    snapshot = sorted(
        (row for row in normalized if row["trade_date"] == snapshot_date),
        key=lambda row: row["con_code"],
    )
    codes = [row["con_code"] for row in snapshot]
    if len(codes) != len(set(codes)):
        raise UniverseError(f"{index_code}: duplicate constituent in frozen snapshot")
    return snapshot_date, snapshot


def _normalized_identity_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise UniverseError("stock_basic source row is not an object")
        code = str(raw.get("ts_code") or "").strip().upper()
        if not TS_CODE_RE.fullmatch(code) or code in seen:
            raise UniverseError(f"stock_basic source identity is invalid or duplicated: {code}")
        seen.add(code)
        status = str(raw.get("list_status") or "").strip().upper()
        if status not in {"L", "D", "P"}:
            raise UniverseError(f"stock_basic list status is invalid: {code}")
        normalized.append({
            "ts_code": code,
            "name": str(raw.get("name") or "").strip(),
            "market": str(raw.get("market") or "").strip(),
            "exchange": str(raw.get("exchange") or code.split(".")[-1]).strip().upper(),
            "list_status": status,
            "delist_date": str(raw.get("delist_date") or "").strip() or None,
        })
    return sorted(normalized, key=lambda row: row["ts_code"])


def _normalized_daily_rows(
    rows: Sequence[Mapping[str, Any]], target: str,
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise UniverseError("daily source row is not an object")
        code = str(raw.get("ts_code") or "").strip().upper()
        trade_date = _date8(str(raw.get("trade_date") or ""))
        if not TS_CODE_RE.fullmatch(code) or code in seen or trade_date != target:
            raise UniverseError(f"daily source identity/date is invalid or duplicated: {code}")
        seen.add(code)
        normalized.append({"ts_code": code, "trade_date": trade_date})
    return sorted(normalized, key=lambda row: row["ts_code"])


def build_source_evidence(
    *,
    index_rows_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    stock_basic_rows: Sequence[Mapping[str, Any]],
    daily_rows: Sequence[Mapping[str, Any]],
    target_trade_date: str,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    target = _date8(target_trade_date)
    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    target_day = datetime.strptime(target, "%Y%m%d").date()
    snapshots: list[dict[str, Any]] = []
    for index_code in INDEX_CODES:
        snapshot_date, rows = _normalized_snapshot(
            index_code, index_rows_by_code.get(index_code) or [], target,
        )
        age_days = (target_day - datetime.strptime(snapshot_date, "%Y%m%d").date()).days
        if age_days > MAX_SNAPSHOT_AGE_DAYS:
            raise UniverseError(
                f"{index_code}: latest constituent snapshot is stale ({age_days} days)"
            )
        snapshots.append({
            "index_code": index_code,
            "constituent_trade_date": snapshot_date,
            "age_days": age_days,
            "rows": rows,
            "rows_hash": canonical_hash(rows),
        })
    identities = _normalized_identity_rows(stock_basic_rows)
    daily = _normalized_daily_rows(daily_rows, target)
    payload: dict[str, Any] = {
        "schema": SOURCE_SCHEMA,
        "schema_version": SOURCE_SCHEMA_VERSION,
        "target_trade_date": target,
        "fetched_at": fetched_at,
        "provider": "Tushare Pro",
        "endpoints": ["index_weight", "stock_basic", "daily"],
        "index_snapshots": snapshots,
        "identity_rows": identities,
        "identity_rows_hash": canonical_hash(identities),
        "daily_rows": daily,
        "daily_rows_hash": canonical_hash(daily),
    }
    payload["source_hash"] = canonical_hash(payload)
    validate_source_evidence(payload)
    return payload


def validate_source_evidence(payload: Mapping[str, Any]) -> None:
    if (
        payload.get("schema") != SOURCE_SCHEMA
        or payload.get("schema_version") != SOURCE_SCHEMA_VERSION
    ):
        raise UniverseError("universe source schema/version mismatch")
    target = _date8(str(payload.get("target_trade_date") or ""))
    if payload.get("source_hash") != canonical_hash({
        key: value for key, value in payload.items() if key != "source_hash"
    }):
        raise UniverseError("universe source hash mismatch")
    snapshots = payload.get("index_snapshots")
    if (
        not isinstance(snapshots, list)
        or [row.get("index_code") for row in snapshots] != list(INDEX_CODES)
    ):
        raise UniverseError("universe source index snapshots are incomplete")
    target_day = datetime.strptime(target, "%Y%m%d").date()
    for snapshot in snapshots:
        index_code = snapshot["index_code"]
        snapshot_date, normalized = _normalized_snapshot(
            index_code, snapshot.get("rows") or [], target,
        )
        age_days = (target_day - datetime.strptime(snapshot_date, "%Y%m%d").date()).days
        if age_days > MAX_SNAPSHOT_AGE_DAYS:
            raise UniverseError(f"{index_code}: constituent source is stale")
        if (
            snapshot.get("constituent_trade_date") != snapshot_date
            or snapshot.get("age_days") != age_days
            or snapshot.get("rows") != normalized
            or snapshot.get("rows_hash") != canonical_hash(normalized)
        ):
            raise UniverseError(f"{index_code}: constituent source rows/hash mismatch")
    identities = payload.get("identity_rows")
    if not isinstance(identities, list):
        raise UniverseError("universe identity source rows are missing")
    normalized_identities = _normalized_identity_rows(identities)
    if identities != normalized_identities or payload.get("identity_rows_hash") != canonical_hash(identities):
        raise UniverseError("universe identity source rows/hash mismatch")
    daily = payload.get("daily_rows")
    if not isinstance(daily, list):
        raise UniverseError("universe daily source rows are missing")
    normalized_daily = _normalized_daily_rows(daily, target)
    if daily != normalized_daily or payload.get("daily_rows_hash") != canonical_hash(daily):
        raise UniverseError("universe daily source rows/hash mismatch")


def _eligibility_reasons(
    identity: Mapping[str, Any] | None,
    registry_row: Mapping[str, Any] | None,
    daily_codes: set[str],
) -> list[str]:
    if identity is None:
        return ["IDENTITY_SOURCE_ROW_MISSING"]
    reasons: list[str] = []
    code = str(identity.get("ts_code") or "")
    exchange = str(identity.get("exchange") or "").upper()
    board = str(identity.get("market") or "")
    status = str(identity.get("list_status") or "")
    name = str(identity.get("name") or "")
    expected_is_st = bool(ST_RE.search(name.upper()))
    expected_is_bse = exchange == "BSE" or code.endswith(".BJ") or "北交" in board
    expected_u1 = status == "L" and not code.startswith("T")
    expected_has_bar = code in daily_codes
    if registry_row is None:
        reasons.append("REGISTRY_ROW_MISSING")
        qualification: Mapping[str, Any] = {}
    else:
        qualification = (
            registry_row.get("qualification")
            if isinstance(registry_row.get("qualification"), Mapping)
            else {}
        )
        expected_projection = {
            "ts_code": code,
            "name": name or "UNKNOWN",
            "board": board,
            "exchange": exchange,
            "list_status": status,
            "delist_date": identity.get("delist_date"),
            "is_st": expected_is_st,
            "is_bse": expected_is_bse,
            "u1_scan_eligible": expected_u1,
            "has_daily_bar_on_as_of": expected_has_bar if status == "L" else None,
        }
        actual_projection = {
            "ts_code": registry_row.get("ts_code"),
            "name": registry_row.get("name"),
            "board": registry_row.get("board"),
            "exchange": registry_row.get("exchange"),
            "list_status": registry_row.get("list_status"),
            "delist_date": registry_row.get("delist_date"),
            "is_st": qualification.get("is_st"),
            "is_bse": qualification.get("is_bse"),
            "u1_scan_eligible": qualification.get("u1_scan_eligible"),
            "has_daily_bar_on_as_of": qualification.get("has_daily_bar_on_as_of"),
        }
        if actual_projection != expected_projection:
            reasons.append("REGISTRY_IDENTITY_MISMATCH")
    if expected_is_bse:
        reasons.append("BSE_NOT_ALLOWED")
    if exchange not in {"SSE", "SZSE"}:
        reasons.append("NON_SH_SZ_EXCHANGE")
    if board != "主板":
        reasons.append("NON_MAIN_BOARD")
    if status != "L" or identity.get("delist_date"):
        reasons.append("NOT_CURRENTLY_LISTED")
    if expected_is_st:
        reasons.append("ST_NOT_ALLOWED")
    if not expected_u1:
        reasons.append("U1_NOT_ELIGIBLE")
    if status == "L" and not expected_has_bar:
        reasons.append("NO_DAILY_BAR_ON_TARGET")
    return reasons


def build_manifest(
    *,
    source_evidence: Mapping[str, Any],
    registry: Mapping[str, Any],
    target_trade_date: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    target = _date8(target_trade_date)
    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    validate_registry(dict(registry))
    validate_source_evidence(source_evidence)
    if registry.get("as_of") != target:
        raise UniverseError("scope registry is not from the target trade date")
    if source_evidence.get("target_trade_date") != target:
        raise UniverseError("scope source is not from the target trade date")

    payload = _build_manifest_unchecked(
        source_evidence=source_evidence,
        registry=registry,
        target=target,
        generated_at=generated_at,
    )
    validate_manifest(payload, registry, source_evidence)
    return payload


def _build_manifest_unchecked(
    *,
    source_evidence: Mapping[str, Any],
    registry: Mapping[str, Any],
    target: str,
    generated_at: str,
) -> dict[str, Any]:
    snapshot_by_index = {
        row["index_code"]: row for row in source_evidence["index_snapshots"]
    }

    memberships: dict[str, list[dict[str, Any]]] = {}
    snapshots: list[dict[str, Any]] = []
    for index_code in INDEX_CODES:
        source_snapshot = snapshot_by_index[index_code]
        snapshot_date = source_snapshot["constituent_trade_date"]
        rows = source_snapshot["rows"]
        snapshots.append({
            "index_code": index_code,
            "constituent_trade_date": snapshot_date,
            "age_days": source_snapshot["age_days"],
            "count": len(rows),
            "rows_hash": canonical_hash(rows),
        })
        for row in rows:
            memberships.setdefault(row["con_code"], []).append({
                "index_code": index_code,
                "constituent_trade_date": snapshot_date,
                "weight": row["weight"],
            })

    registry_by_code = {str(row["ts_code"]): row for row in registry["rows"]}
    identity_by_code = {
        str(row["ts_code"]): row for row in source_evidence["identity_rows"]
    }
    daily_codes = {str(row["ts_code"]) for row in source_evidence["daily_rows"]}
    included_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    for code in sorted(memberships):
        source_memberships = sorted(memberships[code], key=lambda row: row["index_code"])
        registry_row = registry_by_code.get(code)
        identity = identity_by_code.get(code)
        reasons = _eligibility_reasons(identity, registry_row, daily_codes)
        if "REGISTRY_IDENTITY_MISMATCH" in reasons:
            raise UniverseError(f"registry identity differs from provider source: {code}")
        projection = {
            "ts_code": code,
            "name": identity.get("name") if identity else None,
            "board": identity.get("market") if identity else None,
            "exchange": identity.get("exchange") if identity else None,
            "index_memberships": source_memberships,
        }
        if reasons:
            excluded_rows.append({**projection, "reason_codes": reasons})
        else:
            included_rows.append(projection)

    included_codes = [row["ts_code"] for row in included_rows]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "target_trade_date": target,
        "generated_at": generated_at,
        "source": SOURCE,
        "index_codes": list(INDEX_CODES),
        "index_snapshots": snapshots,
        "registry_ref": {
            "as_of": registry["as_of"],
            "registry_hash": registry["registry_hash"],
            "eligible_universe_hash": registry["eligible_universe_hash"],
        },
        "source_ref": {
            "source_hash": source_evidence["source_hash"],
            "identity_rows_hash": source_evidence["identity_rows_hash"],
            "daily_rows_hash": source_evidence["daily_rows_hash"],
        },
        "policy": {
            "membership": "UNION_OF_LATEST_SNAPSHOT_ON_OR_BEFORE_TARGET",
            "boards": ["SSE_MAIN", "SZSE_MAIN"],
            "st_allowed": False,
            "bse_allowed": False,
            "human_selection_required_after_u3": True,
        },
        "included_codes": included_codes,
        "included_rows": included_rows,
        "excluded_rows": excluded_rows,
        "coverage": {
            "union": len(memberships),
            "included": len(included_rows),
            "excluded": len(excluded_rows),
        },
        "universe_hash": canonical_hash(included_codes),
        "rows_hash": canonical_hash({
            "included_rows": included_rows, "excluded_rows": excluded_rows,
        }),
        "disclaimer": DISCLAIMER,
    }
    payload["manifest_hash"] = canonical_hash(payload)
    return payload


def validate_manifest(
    payload: Mapping[str, Any],
    registry: Mapping[str, Any],
    source_evidence: Mapping[str, Any],
) -> None:
    try:
        validate_registry(dict(registry))
    except Exception as exc:
        raise UniverseError(f"scope registry is invalid: {exc}") from exc
    validate_source_evidence(source_evidence)
    if payload.get("schema") != SCHEMA or payload.get("schema_version") != SCHEMA_VERSION:
        raise UniverseError("scope schema/version mismatch")
    if payload.get("source") != SOURCE or payload.get("index_codes") != list(INDEX_CODES):
        raise UniverseError("scope source/index contract changed")
    target = _date8(str(payload.get("target_trade_date") or ""))
    registry_ref = payload.get("registry_ref")
    expected_ref = {
        "as_of": registry.get("as_of"),
        "registry_hash": registry.get("registry_hash"),
        "eligible_universe_hash": registry.get("eligible_universe_hash"),
    }
    if target != registry.get("as_of") or registry_ref != expected_ref:
        raise UniverseError("scope is not bound to the same target registry")
    if source_evidence.get("target_trade_date") != target:
        raise UniverseError("scope source target date mismatch")
    expected = _build_manifest_unchecked(
        source_evidence=source_evidence,
        registry=registry,
        target=target,
        generated_at=str(payload.get("generated_at") or ""),
    )
    if dict(payload) != expected:
        raise UniverseError("scope manifest differs from source evidence or registry")


def _fetch_index_rows(index_code: str, target: str, token: str) -> list[dict[str, Any]]:
    try:
        import tushare as ts
    except ImportError as exc:
        raise UniverseError("tushare package is required for live constituent fetch") from exc
    end = datetime.strptime(target, "%Y%m%d")
    start = end - timedelta(days=400)
    frame = ts.pro_api(token).index_weight(
        index_code=index_code,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )
    if frame is None:
        return []
    return frame.to_dict("records")


def _fetch_daily_rows(target: str, token: str) -> list[dict[str, Any]]:
    return _tushare_call(
        token,
        "daily",
        {"trade_date": target},
        "ts_code,trade_date",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-trade-date", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--source-output", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    target = _date8(args.target_trade_date)
    token = str(os.environ.get("TUSHARE_TOKEN") or "").strip()
    if not token:
        raise UniverseError("TUSHARE_TOKEN is required")
    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    rows = {index: _fetch_index_rows(index, target, token) for index in INDEX_CODES}
    source_evidence = build_source_evidence(
        index_rows_by_code=rows,
        stock_basic_rows=fetch_stock_basic(token),
        daily_rows=_fetch_daily_rows(target, token),
        target_trade_date=target,
    )
    manifest = build_manifest(
        source_evidence=source_evidence, registry=registry, target_trade_date=target,
    )
    _atomic_write_json(Path(args.source_output), source_evidence)
    _atomic_write_json(Path(args.output), manifest)
    print(json.dumps({
        "target_trade_date": target,
        "included": manifest["coverage"]["included"],
        "excluded": manifest["coverage"]["excluded"],
        "source_hash": source_evidence["source_hash"],
        "manifest_hash": manifest["manifest_hash"],
    }, ensure_ascii=False))
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
