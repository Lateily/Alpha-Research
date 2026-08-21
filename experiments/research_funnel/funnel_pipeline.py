#!/usr/bin/env python3
"""R-033/R-034/R-035 research-funnel contracts and state projection.

The module is deliberately offline and deterministic.  It joins existing U0,
U1-E1, feature-store, rotation, Macro and U3 artifacts, but it does not fetch
data, call a model, write a production ledger, or generate a trade action.
Junyan remains the only authority that can select the weekly U4 queue.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import shutil
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from security_registry import _atomic_write_json, _date8, _sha256, validate_registry


SCAN_SCHEMA = "ar.all_market_scan"
CANDIDATE_SCHEMA = "ar.candidate_review"
QUEUE_SCHEMA = "ar.deep_research_queue"
SCHEMA_VERSION = "1.0"
RULE_VERSION = "research_funnel_v1"
QUALIFICATION_RULE_VERSION = "u0_qualification_v1"
CONTROL_ALGO = "sha256+mt19937+sorted_sample/v1"

CHANNELS = (
    "E1_EVENT",
    "PRICE_VOLUME",
    "FUND_FLOW_CHIPS",
    "FUNDAMENTAL_VALUATION",
    "INDUSTRY_VALUE_CHAIN",
    "MACRO_CROSS_ASSET",
)
VALID_DATA_STATUS = {"COMPLETE", "PARTIAL", "DATA_BLOCKED", "STALE_INPUT"}
FORBIDDEN_AGGREGATE_KEYS = {
    "composite_score",
    "weighted_score",
    "total_score",
    "aggregate_score",
    "cross_channel_rank",
}
FORBIDDEN_ACTION_KEYS = {
    "trade_action",
    "buy",
    "sell",
    "order",
    "position_size",
    "formal_blocking_authority",
}
STAGE_ORDER = {
    "UNSCANNED": 0,
    "SCANNED": 1,
    "CANDIDATE": 2,
    "BATTERY": 3,
    "DEEP_RESEARCH": 4,
    "COURT": 5,
    "PORTFOLIO": 6,
}
DISCLAIMER = "不是买卖指令；研究信号，human executes."


class FunnelError(RuntimeError):
    pass


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _evidence_date(value: Any, field: str) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        raw = raw[:10]
    try:
        # governance-mutation: FUNNEL_EVIDENCE_DATE_NORMALIZATION
        return _date8(raw)
    except Exception as exc:
        raise FunnelError(f"{field} is not a valid evidence date") from exc


def _load_json(path: Path, *, optional: bool = False) -> dict[str, Any] | None:
    if optional and not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FunnelError(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FunnelError(f"JSON root must be an object: {path}")
    return value


def _finite(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key).casefold()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _eligible_rows(registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    validate_registry(dict(registry))
    rows = [
        dict(row)
        for row in registry["rows"]
        if row.get("qualification", {}).get("u1_scan_eligible") is True
    ]
    rows.sort(key=lambda row: row["ts_code"])
    # governance-mutation: FUNNEL_U0_NONEMPTY_ELIGIBLE
    if not rows:
        raise FunnelError("U0 has no U1-eligible securities")
    return rows


def load_feature_snapshot(db_path: Path, trade_date: str) -> dict[str, dict[str, Any]]:
    """Read one immutable feature-store date without creating or mutating the DB."""
    if not db_path.exists():
        return {}
    uri = f"file:{db_path.resolve()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM features_daily WHERE trade_date=? ORDER BY ts_code", (trade_date,)
        ).fetchall()
    except sqlite3.Error as exc:
        raise FunnelError(f"feature store read failed: {exc}") from exc
    finally:
        if "conn" in locals():
            conn.close()
    return {str(row["ts_code"]): dict(row) for row in rows}


def _e1_index(
    payload: Mapping[str, Any] | None, as_of: str, registry: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    if payload is None:
        return {}
    payload_as_of = _evidence_date(payload.get("as_of"), "E1 event layer as_of")
    # governance-mutation: FUNNEL_E1_SCHEMA_ASOF
    if payload.get("schema") != "ar.e1_event_layer" or payload_as_of != as_of:
        raise FunnelError("E1 event layer schema/as_of mismatch")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise FunnelError("E1 event rows must be a list")
    # governance-mutation: FUNNEL_E1_ROWS_HASH
    if payload.get("rows_hash") != _hash(rows):
        raise FunnelError("E1 event rows_hash mismatch")
    registry_ref = payload.get("registry_ref") or {}
    if (
        registry_ref.get("registry_hash") != registry.get("registry_hash")
        or registry_ref.get("eligible_universe_hash") != registry.get("eligible_universe_hash")
    ):
        raise FunnelError("E1 event layer is not bound to this U0 registry")
    codes = [str(row.get("ts_code") or "") for row in rows if isinstance(row, dict)]
    if len(codes) != len(rows) or len(codes) != len(set(codes)):
        raise FunnelError("E1 event rows are invalid or duplicated")
    for row in rows:
        verdict = row.get("verdict")
        latest = row.get("latest_e1_date")
        # governance-mutation: FUNNEL_E1_VERDICT
        if verdict not in {"RED_FLAG", "NO_RED_FLAG_FOUND", "DATA_BLOCKED"}:
            raise FunnelError("E1 event verdict is invalid")
        normalized_latest = _evidence_date(latest, "E1 latest_e1_date")
        # governance-mutation: FUNNEL_E1_EVIDENCE_ASOF
        if normalized_latest is not None and normalized_latest > as_of:
            raise FunnelError("E1 event evidence exceeds scan as_of")
    return {str(row.get("ts_code")): dict(row) for row in rows if isinstance(row, dict)}


def _rotation_index(payload: Mapping[str, Any] | None, as_of: str) -> dict[str, dict[str, Any]]:
    if payload is None:
        return {}
    raw_target = payload.get("target_trade_date") or payload.get("as_of")
    target = _evidence_date(raw_target, "rotation panel date") if raw_target else None
    # governance-mutation: FUNNEL_ROTATION_DATE_BINDING
    if target and target != as_of:
        raise FunnelError("rotation panel is not from the requested trade date")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    indexed: dict[str, dict[str, Any]] = {}
    for bucket in ("inflow_cont", "warming", "flicker"):
        for row in data.get(bucket, []) if isinstance(data, dict) else []:
            if isinstance(row, dict) and row.get("sector"):
                indexed[str(row["sector"])] = dict(row)
    return indexed


def _macro_index(payload: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if payload is None:
        return {}
    if payload.get("schema") != "ar.macro.industry_sensitivity":
        raise FunnelError("Macro industry input schema mismatch")
    # governance-mutation: FUNNEL_MACRO_CALIBRATING
    if payload.get("mode") != "CALIBRATING":
        raise FunnelError("Macro industry input must remain CALIBRATING")
    policy = payload.get("policy") or {}
    # governance-mutation: FUNNEL_MACRO_NO_BLOCK_AUTHORITY
    if policy.get("formal_blocking_authority") is not False:
        raise FunnelError("Macro industry input acquired formal blocking authority")
    rows = (payload.get("data") or {}).get("industries", [])
    return {
        str(row.get("industry")): dict(row)
        for row in rows
        if isinstance(row, dict) and row.get("industry")
    }


def _scan_row(
    *, trade_date: str, code: str, channel: str, feature_values: dict[str, Any],
    triggered: bool, source_as_of: str | None, data_status: str,
    reason_codes: Sequence[str], entry_reasons: Sequence[dict[str, Any]] = (),
    channel_rank: int | None = None,
) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "ts_code": code,
        "channel": channel,
        "feature_version": f"{channel.lower()}_relative_v1_unvalidated",
        "feature_values": feature_values,
        "triggered": bool(triggered),
        "entry_reasons": [dict(row) for row in entry_reasons],
        "channel_rank": channel_rank,
        "source_as_of": source_as_of,
        "data_status": data_status,
        "reason_codes": list(reason_codes),
    }


def build_all_market_scan(
    *, registry: Mapping[str, Any], e1_events: Mapping[str, Any] | None,
    features: Mapping[str, Mapping[str, Any]], rotation: Mapping[str, Any] | None = None,
    macro_industry: Mapping[str, Any] | None = None, trade_date: str,
    generated_at: str | None = None, channel_top_n: int = 40,
) -> dict[str, Any]:
    """Build six independent channel rows; no cross-channel score exists."""
    trade_date = _date8(trade_date)
    generated_at = generated_at or _now_utc()
    if channel_top_n < 1:
        raise FunnelError("channel_top_n must be positive")
    eligible = _eligible_rows(registry)
    eligible_codes = {row["ts_code"] for row in eligible}
    e1_by_code = _e1_index(e1_events, trade_date, registry)
    rotation_by_industry = _rotation_index(rotation, trade_date)
    macro_by_industry = _macro_index(macro_industry)

    usable_price = [
        (code, _finite(row.get("return_20d")))
        for code, row in features.items()
        if code in eligible_codes
        and str(row.get("trade_date")) == trade_date
        and _finite(row.get("return_20d")) is not None
    ]
    usable_price.sort(key=lambda item: (-float(item[1]), item[0]))
    price_rank = {code: rank for rank, (code, _) in enumerate(usable_price, 1)}

    industry_ranked: list[tuple[int, int, str]] = []
    for row in eligible:
        context = rotation_by_industry.get(str(row.get("industry_key") or ""))
        if context and context.get("status") in {"INFLOW_CONT", "WARMING"}:
            priority = 0 if context.get("status") == "INFLOW_CONT" else 1
            industry_ranked.append((priority, -int(context.get("streak") or 0), row["ts_code"]))
    industry_ranked.sort()
    industry_rank = {code: rank for rank, (_, _, code) in enumerate(industry_ranked, 1)}

    rows: list[dict[str, Any]] = []
    blocked = Counter()
    triggered = Counter()
    for security in eligible:
        code = security["ts_code"]
        industry = str(security.get("industry_key") or "UNKNOWN")
        e1 = e1_by_code.get(code)
        if e1 is None:
            row = _scan_row(
                trade_date=trade_date, code=code, channel="E1_EVENT", feature_values={},
                triggered=False, source_as_of=None, data_status="DATA_BLOCKED",
                reason_codes=["E1_ROW_MISSING"],
            )
        else:
            verdict = str(e1.get("verdict") or "DATA_BLOCKED")
            is_red = verdict == "RED_FLAG"
            status = "DATA_BLOCKED" if verdict == "DATA_BLOCKED" else "COMPLETE"
            reasons = list(e1.get("reason_codes") or [])
            row = _scan_row(
                trade_date=trade_date, code=code, channel="E1_EVENT",
                feature_values={"verdict": verdict, "latest_e1_date": e1.get("latest_e1_date")},
                triggered=is_red, source_as_of=e1.get("latest_e1_date"), data_status=status,
                reason_codes=reasons or (["E1_DATA_BLOCKED"] if status == "DATA_BLOCKED" else []),
                entry_reasons=[{
                    "channel": "E1_EVENT", "metric": "red_flag_verdict", "value": verdict,
                    "threshold": "RED_FLAG",
                }] if is_red else [],
            )
        rows.append(row)

        feature = dict(features.get(code) or {})
        rank = price_rank.get(code)
        price_complete = str(feature.get("trade_date") or "") == trade_date and rank is not None
        price_hit = bool(price_complete and rank <= channel_top_n)
        rows.append(_scan_row(
            trade_date=trade_date, code=code, channel="PRICE_VOLUME",
            feature_values={
                key: feature.get(key) for key in (
                    "return_1d", "return_5d", "return_10d", "return_20d",
                    "distance_to_20d_close_high_pct", "turnover_rate", "volume_ratio",
                    "total_mv_cny",
                )
            } if feature else {},
            triggered=price_hit, source_as_of=feature.get("trade_date"),
            data_status="COMPLETE" if price_complete else "DATA_BLOCKED",
            reason_codes=[] if price_complete else ["POINT_IN_TIME_FEATURES_MISSING"],
            entry_reasons=[{
                "channel": "PRICE_VOLUME", "metric": "return_20d_rank",
                "value": rank, "threshold": f"TOP_{channel_top_n}",
            }] if price_hit else [], channel_rank=rank,
        ))

        rows.append(_scan_row(
            trade_date=trade_date, code=code, channel="FUND_FLOW_CHIPS", feature_values={},
            triggered=False, source_as_of=None, data_status="DATA_BLOCKED",
            reason_codes=["FULL_MARKET_FUND_FLOW_SOURCE_UNAVAILABLE"],
        ))
        rows.append(_scan_row(
            trade_date=trade_date, code=code, channel="FUNDAMENTAL_VALUATION",
            feature_values={key: feature.get(key) for key in ("pe_ttm", "pb", "total_mv_cny")}
            if feature else {}, triggered=False, source_as_of=feature.get("trade_date"),
            data_status="DATA_BLOCKED",
            reason_codes=["FINANCIAL_STATEMENT_TREND_NOT_IN_FEATURE_STORE"],
        ))

        sector = rotation_by_industry.get(industry)
        sector_rank = industry_rank.get(code)
        sector_hit = bool(sector_rank and sector_rank <= channel_top_n)
        rows.append(_scan_row(
            trade_date=trade_date, code=code, channel="INDUSTRY_VALUE_CHAIN",
            feature_values={
                "industry_key": industry,
                "rotation_status": sector.get("status") if sector else None,
                "streak": sector.get("streak") if sector else None,
                "sequence": sector.get("seq") if sector else None,
            }, triggered=sector_hit, source_as_of=trade_date if sector else None,
            data_status="COMPLETE" if sector else "DATA_BLOCKED",
            reason_codes=[] if sector else ["EXACT_INDUSTRY_ROTATION_MATCH_MISSING"],
            entry_reasons=[{
                "channel": "INDUSTRY_VALUE_CHAIN", "metric": "rotation_status_rank",
                "value": sector_rank, "threshold": f"TOP_{channel_top_n}",
            }] if sector_hit else [], channel_rank=sector_rank,
        ))

        macro = macro_by_industry.get(industry)
        macro_status = "COMPLETE" if macro and macro.get("context_direction") != "DATA_BLOCKED" else "DATA_BLOCKED"
        rows.append(_scan_row(
            trade_date=trade_date, code=code, channel="MACRO_CROSS_ASSET",
            feature_values={
                "industry_key": industry,
                "context_direction": macro.get("context_direction") if macro else None,
                "review_priority": macro.get("review_priority") if macro else None,
                "mode": "CALIBRATING",
            }, triggered=False, source_as_of=macro_industry.get("as_of") if macro else None,
            data_status=macro_status,
            reason_codes=["MACRO_CONTEXT_NOT_A_SELECTION_SIGNAL"] if macro else ["MACRO_INDUSTRY_CONTEXT_MISSING"],
        ))

    for row in rows:
        if row["data_status"] != "COMPLETE":
            blocked[row["channel"]] += 1
        if row["triggered"]:
            triggered[row["channel"]] += 1
    payload = {
        "schema": SCAN_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "status": "PARTIAL" if blocked else "COMPLETE",
        "as_of": trade_date,
        "generated_at": generated_at,
        "eligible_universe_hash": registry["eligible_universe_hash"],
        "channels": list(CHANNELS),
        "policy": {
            "channel_independence": True,
            "cross_channel_scoring": False,
            "threshold_mode": "PER_CHANNEL_TOP_N_RELATIVE_UNVALIDATED",
            "channel_top_n": channel_top_n,
            "macro_selection_authority": False,
        },
        "coverage": {
            "eligible": len(eligible), "rows": len(rows),
            "expected_rows": len(eligible) * len(CHANNELS),
            "blocked_by_channel": dict(sorted(blocked.items())),
            "triggered_by_channel": dict(sorted(triggered.items())),
        },
        "rows": rows,
        "rows_hash": _hash(rows),
        "disclaimer": DISCLAIMER,
    }
    validate_all_market_scan(payload, registry)
    return payload


def validate_all_market_scan(payload: Mapping[str, Any], registry: Mapping[str, Any]) -> None:
    if payload.get("schema") != SCAN_SCHEMA or payload.get("schema_version") != SCHEMA_VERSION:
        raise FunnelError("all_market_scan schema/version mismatch")
    # governance-mutation: FUNNEL_U1_NO_COMPOSITE_SCORE
    if FORBIDDEN_AGGREGATE_KEYS.intersection(_walk_keys(payload)):
        raise FunnelError("cross-channel aggregate score is forbidden")
    # governance-mutation: FUNNEL_U1_NO_TRADE_AUTHORITY
    if FORBIDDEN_ACTION_KEYS.intersection(_walk_keys(payload)):
        raise FunnelError("trade or blocking authority field is forbidden")
    rows = payload.get("rows")
    if not isinstance(rows, list) or payload.get("rows_hash") != _hash(rows):
        raise FunnelError("all_market_scan rows/hash mismatch")
    eligible = {row["ts_code"] for row in _eligible_rows(registry)}
    as_of = _date8(str(payload.get("as_of") or ""))
    if registry.get("as_of") != as_of:
        raise FunnelError("all_market_scan is not from the U0 registry as_of")
    seen: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        required = {
            "trade_date", "ts_code", "channel", "feature_version", "feature_values",
            "triggered", "entry_reasons", "source_as_of", "data_status", "reason_codes",
        }
        if not isinstance(row, dict) or not required.issubset(row):
            raise FunnelError("all_market_scan row is incomplete")
        if row["ts_code"] not in eligible or row["channel"] not in CHANNELS:
            raise FunnelError("all_market_scan row is outside the eligible/channel contract")
        if row["trade_date"] != as_of:
            raise FunnelError("all_market_scan row date differs from contract as_of")
        source_as_of = row.get("source_as_of")
        normalized_source_as_of = _evidence_date(source_as_of, "scan source_as_of")
        # governance-mutation: FUNNEL_U1_SOURCE_ASOF
        if normalized_source_as_of is not None and normalized_source_as_of > as_of:
            raise FunnelError("all_market_scan source evidence is from the future")
        if row["channel"] in seen[row["ts_code"]]:
            raise FunnelError("duplicate channel row for one security")
        seen[row["ts_code"]].add(row["channel"])
        # governance-mutation: FUNNEL_U1_DATA_STATUS
        if row["data_status"] not in VALID_DATA_STATUS:
            raise FunnelError("invalid channel data_status")
        reasons = row["entry_reasons"]
        if row["triggered"] and (not isinstance(reasons, list) or not reasons):
            raise FunnelError("triggered channel row requires entry_reasons")
        for reason in reasons:
            if set(reason) != {"channel", "metric", "value", "threshold"}:
                raise FunnelError("entry_reason fields are not exact")
            if reason["channel"] != row["channel"]:
                raise FunnelError("entry_reason cannot be borrowed from another channel")
    # governance-mutation: FUNNEL_U1_SIX_CHANNEL_COVERAGE
    if set(seen) != eligible or any(channels != set(CHANNELS) for channels in seen.values()):
        raise FunnelError("every eligible security must have exactly six channel rows")


def _feature_strata(
    registry_rows: Sequence[Mapping[str, Any]], features: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    market_caps = sorted(
        (float(value), code)
        for code, row in features.items()
        if (value := _finite(row.get("total_mv_cny"))) is not None and value > 0
    )
    quantile: dict[str, int] = {}
    for index, (_, code) in enumerate(market_caps):
        quantile[code] = min(4, int(index * 5 / max(1, len(market_caps))))
    registry_by_code = {row["ts_code"]: row for row in registry_rows}
    strata: dict[str, str] = {}
    excluded: list[dict[str, Any]] = []
    for code, row in registry_by_code.items():
        industry = str(row.get("industry_key") or "UNKNOWN")
        if code not in quantile or industry == "UNKNOWN":
            excluded.append({"ts_code": code, "reason": "STRATIFICATION_INPUT_MISSING"})
            continue
        strata[code] = f"MV_Q{quantile[code] + 1}|{industry}"
    return strata, excluded


def _allocate_quotas(
    main_counts: Counter[str], pools: Mapping[str, Sequence[str]], total: int,
) -> dict[str, int]:
    if total <= 0 or not main_counts:
        return {}
    denominator = sum(main_counts.values())
    ideals = {key: total * count / denominator for key, count in main_counts.items() if pools.get(key)}
    quotas = {key: min(len(pools[key]), int(value)) for key, value in ideals.items()}
    remaining = total - sum(quotas.values())
    order = sorted(
        ideals,
        key=lambda key: (-(ideals[key] - int(ideals[key])), key),
    )
    while remaining > 0:
        progressed = False
        for key in order:
            if quotas[key] < len(pools[key]):
                quotas[key] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
        if not progressed:
            break
    return quotas


def _reserved_proxy_candidates(
    features: Mapping[str, Mapping[str, Any]], e1_rows: Mapping[str, Mapping[str, Any]],
    selected: set[str], *, slow_quota: int, contrarian_quota: int,
) -> tuple[list[str], list[str]]:
    """Versioned relative proxies; explicit flags prevent a validated-rule claim."""
    slow: list[tuple[float, float, str]] = []
    contrarian: list[tuple[float, float, str]] = []
    for code, row in features.items():
        if code in selected:
            continue
        e1 = e1_rows.get(code) or {}
        if e1.get("verdict") == "RED_FLAG":
            continue
        r1 = _finite(row.get("return_1d"))
        r5 = _finite(row.get("return_5d"))
        r20 = _finite(row.get("return_20d"))
        volume_ratio = _finite(row.get("volume_ratio"))
        pe = _finite(row.get("pe_ttm"))
        if None not in (r1, r5, r20, volume_ratio) and r20 > 0 and r5 >= 0:
            slow.append((abs(r1), volume_ratio, code))
        if (
            None not in (r5, r20, pe) and r20 < 0 and r5 > r20 / 2
            and pe > 0 and e1.get("verdict") != "RED_FLAG"
        ):
            contrarian.append((pe, -r5, code))
    slow.sort()
    slow_codes = [code for _, _, code in slow[:slow_quota]]
    selected.update(slow_codes)
    contrarian = [row for row in contrarian if row[2] not in selected]
    contrarian.sort()
    return slow_codes, [code for _, _, code in contrarian[:contrarian_quota]]


def build_candidate_review(
    *, registry: Mapping[str, Any], scan: Mapping[str, Any],
    features: Mapping[str, Mapping[str, Any]], trade_date: str,
    generated_at: str | None = None, target_size: int = 200,
    slow_bull_quota: int = 15, contrarian_quota: int = 15, control_quota: int = 10,
) -> dict[str, Any]:
    trade_date = _date8(trade_date)
    generated_at = generated_at or _now_utc()
    validate_all_market_scan(scan, registry)
    if not 100 <= target_size <= 300:
        raise FunnelError("U2 target_size must remain within 100..300")
    if min(slow_bull_quota, contrarian_quota, control_quota) < 0:
        raise FunnelError("reserved quotas cannot be negative")
    reserved_total = slow_bull_quota + contrarian_quota + control_quota
    if reserved_total >= target_size:
        raise FunnelError("reserved quotas leave no main-channel capacity")

    registry_rows = _eligible_rows(registry)
    registry_by_code = {row["ts_code"]: row for row in registry_rows}
    current_features = {
        code: row for code, row in features.items()
        if code in registry_by_code and str(row.get("trade_date") or "") == trade_date
    }
    triggered_by_channel: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_triggered: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scan["rows"]:
        if row["triggered"]:
            triggered_by_channel[row["channel"]].append(row)
            all_triggered[row["ts_code"]].append(row)
    for channel in CHANNELS:
        triggered_by_channel[channel].sort(
            key=lambda row: (row.get("channel_rank") is None, row.get("channel_rank") or 0, row["ts_code"])
        )

    red_flag_codes = {
        code for code, rows in all_triggered.items()
        if any(row["channel"] == "E1_EVENT" for row in rows)
    }
    positive_triggered = {
        code for code, source_rows in all_triggered.items()
        if any(row["channel"] != "E1_EVENT" for row in source_rows)
    }
    # governance-mutation: FUNNEL_U2_QUOTA_FLOOR
    main_capacity = target_size - reserved_total
    # governance-mutation: FUNNEL_U2_RED_FLAG_NOT_POSITIVE
    selected_main: set[str] = set()
    queues = {channel: list(rows) for channel, rows in triggered_by_channel.items() if channel != "E1_EVENT"}
    positions = {channel: 0 for channel in queues}
    while len(selected_main) < main_capacity:
        progressed = False
        for channel in CHANNELS:
            if channel not in queues:
                continue
            queue = queues[channel]
            while positions[channel] < len(queue):
                code = queue[positions[channel]]["ts_code"]
                positions[channel] += 1
                if code in selected_main:
                    continue
                selected_main.add(code)
                progressed = True
                break
            if len(selected_main) >= main_capacity:
                break
        if not progressed:
            break

    e1_rows = {
        row["ts_code"]: {
            "verdict": (row.get("feature_values") or {}).get("verdict"),
        }
        for row in scan["rows"] if row["channel"] == "E1_EVENT"
    }
    selected_all = set(selected_main)
    slow_codes, contrarian_codes = _reserved_proxy_candidates(
        current_features, e1_rows, selected_all,
        slow_quota=slow_bull_quota, contrarian_quota=contrarian_quota,
    )
    selected_all.update(contrarian_codes)
    control_excluded = set(selected_all)

    strata, stratum_excluded = _feature_strata(registry_rows, current_features)
    main_counts = Counter(strata[code] for code in selected_main if code in strata)
    pools: dict[str, list[str]] = defaultdict(list)
    for code in sorted(registry_by_code):
        if code not in selected_all and code in strata:
            pools[strata[code]].append(code)
    universe_codes = sorted(registry_by_code)
    eligible_hash = _hash({"rule_version": QUALIFICATION_RULE_VERSION, "ts_codes": universe_codes})
    seed_hex = hashlib.sha256(
        f"{trade_date}|AR_RANDOM_CONTROL|v1|{eligible_hash}".encode("utf-8")
    ).hexdigest()
    # governance-mutation: FUNNEL_U2_CONTROL_SEED
    rng = random.Random(int(seed_hex[:16], 16))
    quotas = _allocate_quotas(main_counts, pools, control_quota)
    control_codes: list[str] = []
    drawn: list[dict[str, Any]] = []
    for stratum in sorted(quotas):
        picks = rng.sample(sorted(pools[stratum]), k=quotas[stratum])
        for code in picks:
            control_codes.append(code)
            drawn.append({
                "ts_code": code, "stratum": stratum, "drawn_rank": len(drawn) + 1,
            })
    selected_all.update(control_codes)
    excluded_red_flags = red_flag_codes - selected_all - positive_triggered

    rows: list[dict[str, Any]] = []
    category = {code: "MAIN_CHANNEL" for code in selected_main}
    category.update({code: "RESERVED_SLOW_BULL" for code in slow_codes})
    category.update({code: "RESERVED_CONTRARIAN" for code in contrarian_codes})
    category.update({code: "RANDOM_CONTROL" for code in control_codes})
    control_batch_id = f"CTRL_{trade_date}_v1"
    output_codes = selected_all | excluded_red_flags
    for code in sorted(output_codes):
        source_rows = all_triggered.get(code, [])
        source_channels = sorted({row["channel"] for row in source_rows}, key=CHANNELS.index)
        reasons = [reason for row in source_rows for reason in row["entry_reasons"]]
        flags: list[str] = []
        row_category = category.get(code)
        if code in red_flag_codes:
            flags.append("RED_FLAG")
        if row_category and row_category.startswith("RESERVED_"):
            flags.append("UNVALIDATED_RELATIVE_PROXY")
        if row_category == "RANDOM_CONTROL":
            flags.append("NEGATIVE_CONTROL")
        if code in excluded_red_flags:
            review_status = "EXCLUDED_RED_FLAG"
            priority = "RED_FLAG_ARCHIVE"
            exclusion_reason = "E1_RED_FLAG_WITHOUT_POSITIVE_CHANNEL_ENTRY"
            next_action = "E1_REVIEW_ONLY"
        else:
            review_status = row_category
            priority = "RED_FLAG_REVIEW" if code in red_flag_codes else "CHANNEL_INDEPENDENT"
            exclusion_reason = None
            next_action = "U3_BATTERY_REVIEW"
        registry_row = registry_by_code[code]
        rows.append({
            "as_of": trade_date,
            "ts_code": code,
            "industry_key": registry_row.get("industry_key"),
            "source_channels": source_channels,
            "entry_reasons": reasons,
            "cluster_id": None,
            "priority": priority,
            "flags": flags,
            "liquidity_eligibility": bool(
                registry_row.get("qualification", {}).get("u1_scan_eligible") is True
            ),
            "review_status": review_status,
            "exclusion_reason": exclusion_reason,
            "next_action": next_action,
            "control_batch_id": control_batch_id if code in control_codes else None,
            "stratum": strata.get(code),
            "aligned_return": None,
        })

    trigger_excluded = sorted(positive_triggered - selected_main)
    excluded_by_code = {row["ts_code"]: dict(row) for row in stratum_excluded}
    for row in registry["rows"]:
        if row.get("qualification", {}).get("u1_scan_eligible") is not True:
            excluded_by_code[row["ts_code"]] = {
                "ts_code": row["ts_code"],
                "reason": "U0_QUALIFICATION_FAILED",
                "qualification": copy.deepcopy(row.get("qualification") or {}),
            }
    drawn_codes = set(control_codes)
    capacity_codes = set(trigger_excluded)
    for code in sorted(registry_by_code):
        if code in drawn_codes or code in excluded_by_code:
            continue
        if code in control_excluded:
            reason = "MAIN_OR_RESERVED_CANDIDATE"
        elif code in capacity_codes:
            reason = "MAIN_CHANNEL_CAPACITY"
        else:
            reason = "NOT_DRAWN_BY_FIXED_SAMPLE"
        excluded_by_code[code] = {
            "ts_code": code, "reason": reason, "stratum": strata.get(code),
        }
    excluded_with_reason = [excluded_by_code[code] for code in sorted(excluded_by_code)]
    strata_report = []
    for key in sorted(set(main_counts) | set(pools)):
        strata_report.append({
            "stratum": key,
            "main_count": main_counts.get(key, 0),
            "eligible_count": sum(1 for code in registry_by_code if strata.get(code) == key),
            "available_count": len(pools.get(key, [])),
            "quota": quotas.get(key, 0),
            "drawn": sum(1 for row in drawn if row["stratum"] == key),
        })
    quota_actual = {
        "slow_bull": len(slow_codes),
        "contrarian_repair": len(contrarian_codes),
        "random_control": len(control_codes),
    }
    quota_required = {
        "slow_bull": slow_bull_quota,
        "contrarian_repair": contrarian_quota,
        "random_control": control_quota,
    }
    shortfalls = {
        key: quota_required[key] - quota_actual[key]
        for key in quota_required if quota_actual[key] < quota_required[key]
    }
    active_count = len(selected_all)
    target_shortfall = max(0, target_size - active_count)
    target_overflow = max(0, active_count - target_size)
    payload = {
        "schema": CANDIDATE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "status": "PARTIAL" if (
            shortfalls or target_shortfall or target_overflow or scan.get("status") != "COMPLETE"
        ) else "COMPLETE",
        "as_of": trade_date,
        "generated_at": generated_at,
        "policy": {
            "target_size": target_size,
            "selection": "CHANNEL_UNION_EQUAL_ROUND_ROBIN_NO_COMPOSITE_SCORE",
            "reserved_quotas_are_floors": True,
            "proxy_rules": "UNVALIDATED_INITIAL_RELATIVE_RULES",
        },
        "quota": {"required": quota_required, "actual": quota_actual, "shortfalls": shortfalls},
        "coverage": {
            "candidate_rows": active_count,
            "excluded_rows": len(excluded_red_flags),
            "target_shortfall": target_shortfall,
            "target_overflow": target_overflow,
        },
        "control_sampling_frame": {
            "control_batch_id": control_batch_id,
            "as_of": trade_date,
            "eligible_universe_n": len(universe_codes),
            "eligible_universe_hash": eligible_hash,
            "strata": strata_report,
            "quota_per_stratum": quotas,
            "seed_hex": seed_hex,
            "algo": CONTROL_ALGO,
            "drawn": drawn,
            "excluded_with_reason": excluded_with_reason,
        },
        "rows": rows,
        "rows_hash": _hash(rows),
        "disclaimer": DISCLAIMER,
    }
    validate_candidate_review(payload, registry, scan)
    return payload


def validate_candidate_review(
    payload: Mapping[str, Any], registry: Mapping[str, Any], scan: Mapping[str, Any],
) -> None:
    if payload.get("schema") != CANDIDATE_SCHEMA or payload.get("schema_version") != SCHEMA_VERSION:
        raise FunnelError("candidate_review schema/version mismatch")
    if payload.get("as_of") != scan.get("as_of") or payload.get("as_of") != registry.get("as_of"):
        raise FunnelError("candidate_review is not bound to the same U0/U1 as_of")
    if FORBIDDEN_AGGREGATE_KEYS.intersection(_walk_keys(payload)):
        raise FunnelError("candidate_review cannot contain a cross-channel score")
    if FORBIDDEN_ACTION_KEYS.intersection(_walk_keys(payload)):
        raise FunnelError("candidate_review cannot contain trade authority")
    rows = payload.get("rows")
    if not isinstance(rows, list) or payload.get("rows_hash") != _hash(rows):
        raise FunnelError("candidate_review rows/hash mismatch")
    eligible = {row["ts_code"] for row in _eligible_rows(registry)}
    triggered_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for scan_row in scan["rows"]:
        if scan_row["triggered"]:
            triggered_by_code[scan_row["ts_code"]].append(scan_row)
    seen: set[str] = set()
    control_rows: list[dict[str, Any]] = []
    for row in rows:
        required = {
            "as_of", "ts_code", "industry_key", "source_channels", "cluster_id", "priority", "flags",
            "liquidity_eligibility", "review_status", "exclusion_reason", "next_action",
        }
        if not isinstance(row, dict) or not required.issubset(row):
            raise FunnelError("candidate_review row is incomplete")
        code = row["ts_code"]
        if code not in eligible or code in seen:
            raise FunnelError("candidate_review contains duplicate or ineligible security")
        seen.add(code)
        if row["as_of"] != payload.get("as_of"):
            raise FunnelError("candidate row date differs from contract as_of")
        triggered = triggered_by_code.get(code, [])
        expected_channels = sorted({item["channel"] for item in triggered}, key=CHANNELS.index)
        expected_reasons = [reason for item in triggered for reason in item["entry_reasons"]]
        # governance-mutation: FUNNEL_U2_EXACT_EVIDENCE_PROJECTION
        if row.get("source_channels") != expected_channels or row.get("entry_reasons") != expected_reasons:
            raise FunnelError("candidate U1 channel/reason projection is not exact")
        red_flagged = "E1_EVENT" in expected_channels
        positive = any(channel != "E1_EVENT" for channel in expected_channels)
        if ("RED_FLAG" in row.get("flags", [])) is not red_flagged:
            raise FunnelError("candidate RED_FLAG flag differs from U1 evidence")
        if row.get("review_status") == "EXCLUDED_RED_FLAG":
            if not row.get("exclusion_reason") or row.get("next_action") == "U3_BATTERY_REVIEW":
                raise FunnelError("red-flag exclusion semantics are inconsistent")
            if not red_flagged or positive:
                raise FunnelError("only an E1-only red flag may use EXCLUDED_RED_FLAG")
        elif row.get("exclusion_reason") is not None:
            raise FunnelError("active candidate cannot carry an exclusion reason")
        elif red_flagged and not positive and row.get("review_status") != "RANDOM_CONTROL":
            raise FunnelError("an E1-only red flag cannot become an active research candidate")
        if row["review_status"] == "RANDOM_CONTROL":
            control_rows.append(row)
            if row.get("control_batch_id") != payload["control_sampling_frame"]["control_batch_id"]:
                raise FunnelError("random control batch linkage mismatch")
    frame = payload.get("control_sampling_frame") or {}
    # governance-mutation: FUNNEL_U2_CONTROL_ALGORITHM
    if frame.get("algo") != CONTROL_ALGO:
        raise FunnelError("random control algorithm drift")
    if sorted(row["ts_code"] for row in control_rows) != sorted(row["ts_code"] for row in frame.get("drawn", [])):
        raise FunnelError("random control rows differ from sampling frame")
    universe_codes = sorted(eligible)
    expected_universe_hash = _hash({
        "rule_version": QUALIFICATION_RULE_VERSION, "ts_codes": universe_codes,
    })
    if frame.get("eligible_universe_hash") != expected_universe_hash:
        raise FunnelError("random control eligible universe hash mismatch")
    expected_seed = hashlib.sha256(
        f"{payload['as_of']}|AR_RANDOM_CONTROL|v1|{expected_universe_hash}".encode("utf-8")
    ).hexdigest()
    if frame.get("seed_hex") != expected_seed:
        raise FunnelError("random control seed mismatch")
    drawn = frame.get("drawn")
    exclusions = frame.get("excluded_with_reason")
    if not isinstance(drawn, list) or not isinstance(exclusions, list):
        raise FunnelError("random control sampling frame is incomplete")
    drawn_codes = [row.get("ts_code") for row in drawn if isinstance(row, dict)]
    excluded_codes = [row.get("ts_code") for row in exclusions if isinstance(row, dict)]
    if (
        len(drawn_codes) != len(set(drawn_codes))
        or len(excluded_codes) != len(set(excluded_codes))
        or set(drawn_codes).intersection(excluded_codes)
        or set(drawn_codes).union(excluded_codes) != {row["ts_code"] for row in registry["rows"]}
    ):
        raise FunnelError("random control frame does not partition the registered universe")
    pools: dict[str, list[str]] = defaultdict(list)
    for row in [*drawn, *exclusions]:
        if not isinstance(row, dict) or not row.get("stratum"):
            continue
        if row.get("reason") == "MAIN_OR_RESERVED_CANDIDATE":
            continue
        pools[str(row["stratum"])].append(str(row["ts_code"]))
    main_counts = Counter(
        row.get("stratum") for row in rows
        if row.get("review_status") == "MAIN_CHANNEL" and row.get("stratum")
    )
    requested = int((payload.get("quota") or {}).get("required", {}).get("random_control", 0))
    expected_quotas = _allocate_quotas(main_counts, pools, requested)
    if frame.get("quota_per_stratum") != expected_quotas:
        raise FunnelError("random control stratum quotas are not reproducible")
    rng = random.Random(int(expected_seed[:16], 16))
    expected_drawn: list[dict[str, Any]] = []
    for stratum in sorted(expected_quotas):
        for code in rng.sample(sorted(pools[stratum]), k=expected_quotas[stratum]):
            expected_drawn.append({
                "ts_code": code, "stratum": stratum,
                "drawn_rank": len(expected_drawn) + 1,
            })
    if drawn != expected_drawn:
        raise FunnelError("random control draw is not reproducible from its frozen frame")

    policy = payload.get("policy") or {}
    required_quota = (payload.get("quota") or {}).get("required") or {}
    target_size = int(policy.get("target_size") or 0)
    reserved_total = sum(int(required_quota.get(key) or 0) for key in (
        "slow_bull", "contrarian_repair", "random_control",
    ))
    main_count = sum(row.get("review_status") == "MAIN_CHANNEL" for row in rows)
    active_count = sum(row.get("review_status") != "EXCLUDED_RED_FLAG" for row in rows)
    if (
        policy.get("reserved_quotas_are_floors") is not True
        or target_size < 1
        or reserved_total >= target_size
        or main_count > target_size - reserved_total
        or active_count > target_size
    ):
        raise FunnelError("reserved quotas did not preserve main-channel capacity")


def _battery_rows(
    payload: Mapping[str, Any] | None, trade_date: str | None = None,
) -> dict[str, dict[str, Any]]:
    if payload is None:
        return {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    target = str(
        payload.get("target_trade_date")
        or (data.get("checked_at") if isinstance(data, dict) else "")
        or ""
    ).replace("-", "")
    # governance-mutation: FUNNEL_U4_SAME_DAY_BATTERY
    if trade_date is not None and target != _date8(trade_date):
        raise FunnelError("U3 battery is not from the requested trade date")
    rows = data.get("results", []) if isinstance(data, dict) else []
    if not isinstance(rows, list):
        raise FunnelError("U3 battery results must be a list")
    codes = [str(row.get("ts_code") or "") for row in rows if isinstance(row, dict)]
    if len(codes) != len(rows) or len(codes) != len(set(codes)):
        raise FunnelError("U3 battery rows are invalid or duplicated")
    return {str(row.get("ts_code")): dict(row) for row in rows if isinstance(row, dict)}


def build_deep_research_queue(
    *, candidate_review: Mapping[str, Any], battery: Mapping[str, Any] | None,
    selected_tickers: Sequence[str], trade_date: str, generated_at: str | None = None,
    research_questions: Mapping[str, str] | None = None,
    sector_os_industries: Sequence[str] = (),
) -> dict[str, Any]:
    """Create a U4 queue only from an explicit human-selected 3..5 ticker list."""
    generated_at = generated_at or _now_utc()
    trade_date = _date8(trade_date)
    selected = [str(code).strip().upper() for code in selected_tickers if str(code).strip()]
    research_questions = {
        str(code).strip().upper(): str(question).strip()
        for code, question in (research_questions or {}).items()
    }
    sector_os = {str(industry).strip() for industry in sector_os_industries if str(industry).strip()}
    if len(selected) != len(set(selected)):
        raise FunnelError("U4 human selection contains duplicates")
    # governance-mutation: FUNNEL_U4_HUMAN_SELECTION_SIZE
    if selected and not 3 <= len(selected) <= 5:
        raise FunnelError("U4 human selection must contain 3..5 securities")
    missing_questions = [code for code in selected if not research_questions.get(code)]
    # governance-mutation: FUNNEL_U4_RESEARCH_QUESTION
    if missing_questions:
        raise FunnelError(f"U4 selection lacks a clear research question: {missing_questions}")
    candidates = {row["ts_code"]: row for row in candidate_review.get("rows", [])}
    battery_by_code = _battery_rows(battery, trade_date)
    ready_pool: list[dict[str, Any]] = []
    for code in sorted(set(candidates) & set(battery_by_code)):
        candidate = candidates[code]
        battery_row = battery_by_code[code]
        completeness = battery_row.get("completeness") or {}
        blocked = completeness.get("verdict") != "COMPLETE" or "RED_FLAG" in candidate.get("flags", [])
        ready_pool.append({
            "ts_code": code,
            "ready": not blocked,
            "industry_key": candidate.get("industry_key"),
            "sector_os_status": (
                "AVAILABLE" if candidate.get("industry_key") in sector_os else "TASK_REQUIRED"
            ),
            "candidate_status": candidate.get("review_status"),
            "battery_verdict": completeness.get("verdict"),
            "blocked_reasons": (
                (["U3_BATTERY_INCOMPLETE"] if completeness.get("verdict") != "COMPLETE" else [])
                + (["E1_RED_FLAG_REQUIRES_SEPARATE_REVIEW"] if "RED_FLAG" in candidate.get("flags", []) else [])
            ),
        })
    ready = {row["ts_code"] for row in ready_pool if row["ready"]}
    missing = [code for code in selected if code not in ready]
    if missing:
        raise FunnelError(f"U4 selection is not backed by eligible U2+U3 evidence: {missing}")
    rows = []
    for code in selected:
        industry = candidates[code].get("industry_key")
        tasks = [
            "BUILD_E1_FACTPACK",
            "WRITE_CAUSAL_THESIS_AND_VARIANT_VIEW",
            "BUILD_NORMALIZED_VALUATION_BRIDGE",
            "DEFINE_PORTFOLIO_CONTRIBUTION",
            "DEFINE_WRONG_IF_AND_PRIMARY_HORIZON",
            "ASSIGN_PROSPECTIVE_CAUSAL_CLUSTER",
            "RUN_RED_TEAM_REVIEW",
        ]
        if industry not in sector_os:
            tasks.insert(0, "BUILD_OR_UPDATE_SECTOR_OS")
        rows.append({
            "as_of": trade_date,
            "ts_code": code,
            "industry_key": industry,
            "research_question": research_questions.get(code, ""),
            "selection_input": "EXPLICIT_OPERATOR_INPUT",
            "selection_identity_verified": False,
            "source_candidate_hash": _hash(candidates[code]),
            "source_battery_hash": _hash(battery_by_code[code]),
            "sector_os_status": "AVAILABLE" if industry in sector_os else "TASK_REQUIRED",
            "research_tasks": tasks,
            "required_outputs": ["factpack", "decision_sheet", "wrong_if", "cluster_id"],
            "queue_status": "READY_FOR_DEEP_RESEARCH",
            "next_action": "HUMAN_REVIEWED_FACTPACK_WORK",
            "no_trade_flag": True,
        })
    payload = {
        "schema": QUEUE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "status": "COMPLETE" if rows else "PARTIAL",
        "as_of": trade_date,
        "generated_at": generated_at,
        "authority": {
            "auto_selection": False,
            "human_selection_required": True,
            "selection_owner": "Junyan",
            "machine_identity_verification": "UNAVAILABLE",
        },
        "ready_pool": ready_pool,
        "rows": rows,
        "rows_hash": _hash(rows),
        "next_gate": None if rows else "JUNYAN_SELECT_3_TO_5_FROM_READY_POOL",
        "disclaimer": DISCLAIMER,
    }
    validate_deep_research_queue(payload)
    return payload


def validate_deep_research_queue(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != QUEUE_SCHEMA or payload.get("schema_version") != SCHEMA_VERSION:
        raise FunnelError("deep_research_queue schema/version mismatch")
    # governance-mutation: FUNNEL_U4_NO_TRADE_AUTHORITY
    if FORBIDDEN_ACTION_KEYS.intersection(_walk_keys(payload)):
        raise FunnelError("U4 queue cannot contain trade or blocking authority")
    rows = payload.get("rows")
    if not isinstance(rows, list) or payload.get("rows_hash") != _hash(rows):
        raise FunnelError("deep_research_queue rows/hash mismatch")
    if rows and not 3 <= len(rows) <= 5:
        raise FunnelError("a populated U4 queue must contain 3..5 securities")
    authority = payload.get("authority") or {}
    # governance-mutation: FUNNEL_U4_AUTHORITY_BOUNDARY
    if (
        authority.get("auto_selection") is not False
        or authority.get("human_selection_required") is not True
        or authority.get("selection_owner") != "Junyan"
    ):
        raise FunnelError("U4 authority boundary changed")
    if any(
        row.get("no_trade_flag") is not True
        or row.get("selection_input") != "EXPLICIT_OPERATOR_INPUT"
        or row.get("selection_identity_verified") is not False
        or not str(row.get("research_question") or "").strip()
        or row.get("sector_os_status") not in {"AVAILABLE", "TASK_REQUIRED"}
        for row in rows
    ):
        raise FunnelError("U4 queue selection/no-trade boundary is inconsistent")


def advance_registry(
    *, registry: Mapping[str, Any], scan: Mapping[str, Any],
    candidate_review: Mapping[str, Any], battery: Mapping[str, Any] | None,
    deep_queue: Mapping[str, Any], generated_at: str | None = None,
) -> dict[str, Any]:
    """Project monotonic U0 stages from hashable downstream evidence."""
    validate_all_market_scan(scan, registry)
    validate_candidate_review(candidate_review, registry, scan)
    validate_deep_research_queue(deep_queue)
    generated_at = generated_at or _now_utc()
    scanned = {row["ts_code"] for row in scan["rows"]}
    candidates = {
        row["ts_code"] for row in candidate_review["rows"]
        if row.get("review_status") != "EXCLUDED_RED_FLAG"
    }
    battery_by_code = _battery_rows(battery, str(scan["as_of"]))
    battery_codes = set(battery_by_code) & candidates
    deep_codes = {row["ts_code"] for row in deep_queue["rows"]}
    output = copy.deepcopy(dict(registry))
    transitions = Counter()
    for row in output["rows"]:
        code = row["ts_code"]
        current = str(row.get("current_stage") or "UNSCANNED")
        if current not in STAGE_ORDER:
            continue
        target = current
        evidence: list[dict[str, Any]] = []
        if code in scanned:
            target = "SCANNED"
            evidence.append({"stage": "SCANNED", "artifact": SCAN_SCHEMA, "hash": scan["rows_hash"]})
        if code in candidates:
            target = "CANDIDATE"
            evidence.append({"stage": "CANDIDATE", "artifact": CANDIDATE_SCHEMA, "hash": candidate_review["rows_hash"]})
        if code in battery_codes:
            target = "BATTERY"
            evidence.append({"stage": "BATTERY", "artifact": "battery", "hash": _hash(battery_by_code[code])})
        if code in deep_codes:
            target = "DEEP_RESEARCH"
            evidence.append({"stage": "DEEP_RESEARCH", "artifact": QUEUE_SCHEMA, "hash": deep_queue["rows_hash"]})
        if STAGE_ORDER[target] > STAGE_ORDER[current]:
            row["current_stage"] = target
            history = row.setdefault("stage_history", [])
            history.append({
                "from": current, "to": target, "at": generated_at,
                "as_of": scan["as_of"], "evidence": evidence,
            })
            transitions[f"{current}->{target}"] += 1
    output["generated_at"] = generated_at
    output["registry_hash"] = _sha256(output["rows"])
    output["stage_projection"] = {
        "rule_version": RULE_VERSION,
        "source_scan_hash": scan["rows_hash"],
        "source_candidate_hash": candidate_review["rows_hash"],
        "source_queue_hash": deep_queue["rows_hash"],
        "transitions": dict(sorted(transitions.items())),
    }
    validate_registry(output)
    return output


def run_pipeline(
    *, registry_path: Path, e1_path: Path, feature_db: Path,
    output_dir: Path, trade_date: str, rotation_path: Path | None = None,
    macro_industry_path: Path | None = None, battery_path: Path | None = None,
    selected_tickers: Sequence[str] = (), generated_at: str | None = None,
    research_questions: Mapping[str, str] | None = None,
    sector_os_industries: Sequence[str] = (),
) -> dict[str, Path]:
    if os.path.lexists(output_dir):
        raise FunnelError(f"output bundle already exists; refusing overwrite: {output_dir}")
    registry = _load_json(registry_path)
    e1 = _load_json(e1_path)
    rotation = _load_json(rotation_path, optional=True) if rotation_path else None
    macro = _load_json(macro_industry_path, optional=True) if macro_industry_path else None
    battery = _load_json(battery_path, optional=True) if battery_path else None
    assert registry is not None and e1 is not None
    features = load_feature_snapshot(feature_db, _date8(trade_date))
    scan = build_all_market_scan(
        registry=registry, e1_events=e1, features=features, rotation=rotation,
        macro_industry=macro, trade_date=trade_date, generated_at=generated_at,
    )
    candidates = build_candidate_review(
        registry=registry, scan=scan, features=features, trade_date=trade_date,
        generated_at=generated_at,
    )
    queue = build_deep_research_queue(
        candidate_review=candidates, battery=battery, selected_tickers=selected_tickers,
        trade_date=trade_date, generated_at=generated_at,
        research_questions=research_questions, sector_os_industries=sector_os_industries,
    )
    projected = advance_registry(
        registry=registry, scan=scan, candidate_review=candidates, battery=battery,
        deep_queue=queue, generated_at=generated_at,
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    staged_outputs = {
        "scan": staging / "all_market_scan.json",
        "candidates": staging / "candidate_review.json",
        "queue": staging / "deep_research_queue.json",
        "registry": staging / "security_registry_projected.json",
    }
    outputs = {
        "scan": output_dir / "all_market_scan.json",
        "candidates": output_dir / "candidate_review.json",
        "queue": output_dir / "deep_research_queue.json",
        "registry": output_dir / "security_registry_projected.json",
    }
    try:
        for key, payload in (
            ("scan", scan), ("candidates", candidates), ("queue", queue), ("registry", projected)
        ):
            _atomic_write_json(staged_outputs[key], payload)
        manifest = {
            "schema": "ar.research_funnel_bundle",
            "schema_version": SCHEMA_VERSION,
            "rule_version": RULE_VERSION,
            "as_of": _date8(trade_date),
            "generated_at": generated_at or scan["generated_at"],
            "artifacts": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in staged_outputs.values()
            },
        }
        manifest["bundle_hash"] = _hash(manifest["artifacts"])
        _atomic_write_json(staging / "manifest.json", manifest)
        directory_fd = os.open(staging, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        os.replace(staging, output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return outputs


CANDIDATE_MANIFEST_SCHEMA = "ar.research_funnel_candidate_manifest"
BATTERY_U2_SCHEMA = "ar.research_funnel_candidate_battery"
BATTERY_DIMENSIONS = ("行情", "资金", "基本面", "技术面", "消息面", "估值")


def build_candidate_manifest(
    *, candidate_review: Mapping[str, Any], scan: Mapping[str, Any], run_id: str,
) -> dict[str, Any]:
    """U2 之后、电池之前的**不可变候选清单**。

    三段子 DAG 的绑定锚点:funnel_candidates 产出它,candidate_battery 绑定它的
    hash 逐票跑电池,funnel_finalize 校验电池覆盖的集合与它完全相等。
    只列非红旗候选 —— 红旗票不进 U3/U4,自然也不消耗电池配额。
    """
    codes = sorted({
        str(row.get("ts_code") or "")
        for row in candidate_review.get("rows", [])
        if isinstance(row, dict) and row.get("review_status") != "EXCLUDED_RED_FLAG"
    })
    if not codes:
        raise FunnelError("candidate manifest is empty: no non-red-flag candidates to battery")
    if any(not code for code in codes):
        raise FunnelError("candidate manifest contains an empty ts_code")
    payload = {
        "schema": CANDIDATE_MANIFEST_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "as_of": candidate_review["as_of"],
        "run_id": run_id,
        "candidate_rows_hash": candidate_review["rows_hash"],
        "scan_rows_hash": scan["rows_hash"],
        "expected_count": len(codes),
        "ts_codes": codes,
        "policy": {
            "source": "U2_CANDIDATE_REVIEW_SAME_RUN",
            "excludes": ["EXCLUDED_RED_FLAG"],
            "t_minus_1_fallback": "FORBIDDEN",
            "watchlist_fallback": "FORBIDDEN",
        },
        "disclaimer": DISCLAIMER,
    }
    payload["manifest_hash"] = _hash({
        k: v for k, v in payload.items() if k not in ("manifest_hash",)
    })
    return payload


def validate_candidate_manifest(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != CANDIDATE_MANIFEST_SCHEMA or payload.get("schema_version") != SCHEMA_VERSION:
        raise FunnelError("candidate manifest schema/version mismatch")
    codes = payload.get("ts_codes")
    if not isinstance(codes, list) or not codes:
        raise FunnelError("candidate manifest ts_codes must be a non-empty list")
    if codes != sorted(set(codes)):
        raise FunnelError("candidate manifest ts_codes must be sorted and unique")
    # governance-mutation: FUNNEL_MANIFEST_COUNT_FROM_LIST
    if payload.get("expected_count") != len(codes):
        raise FunnelError("candidate manifest expected_count does not match ts_codes")
    policy = payload.get("policy") or {}
    if (
        policy.get("t_minus_1_fallback") != "FORBIDDEN"
        or policy.get("watchlist_fallback") != "FORBIDDEN"
        or policy.get("source") != "U2_CANDIDATE_REVIEW_SAME_RUN"
    ):
        raise FunnelError("candidate manifest fallback policy drift")
    if not str(payload.get("run_id") or "").strip():
        raise FunnelError("candidate manifest lacks run_id")
    body = {k: v for k, v in payload.items() if k != "manifest_hash"}
    if payload.get("manifest_hash") != _hash(body):
        raise FunnelError("candidate manifest hash mismatch")


def validate_candidate_battery(
    battery: Mapping[str, Any], manifest: Mapping[str, Any],
) -> dict[str, int]:
    """U3 完整性:电池覆盖的集合必须与候选清单**完全相等**。

    顺序可以不同,集合不能差一只:缺行 = 静默缺席,多行 = 来源不明。
    每票六维必须齐全 —— 缺数据可以,但必须以 DATA_BLOCKED 出现,不能少一维。
    返回覆盖统计,供 health 上浮。
    """
    if battery.get("schema") != BATTERY_U2_SCHEMA or battery.get("schema_version") != SCHEMA_VERSION:
        raise FunnelError("candidate battery schema/version mismatch")
    # governance-mutation: FUNNEL_BATTERY_MANIFEST_BINDING
    if battery.get("manifest_hash") != manifest.get("manifest_hash"):
        raise FunnelError("candidate battery is not bound to this candidate manifest")
    if battery.get("as_of") != manifest.get("as_of") or battery.get("run_id") != manifest.get("run_id"):
        raise FunnelError("candidate battery as_of/run_id differ from the manifest")
    rows = battery.get("results")
    if not isinstance(rows, list):
        raise FunnelError("candidate battery results must be a list")
    observed = [str(r.get("ts_code") or "") for r in rows if isinstance(r, dict)]
    if len(observed) != len(rows) or len(observed) != len(set(observed)):
        raise FunnelError("candidate battery rows are invalid or duplicated")
    expected = set(manifest["ts_codes"])
    # governance-mutation: FUNNEL_BATTERY_SET_EQUALITY
    if set(observed) != expected:
        missing = sorted(expected - set(observed))
        extra = sorted(set(observed) - expected)
        raise FunnelError(
            f"candidate battery coverage != manifest: missing={missing[:5]} extra={extra[:5]}"
        )
    blocked_rows = 0
    for row in rows:
        # governance-mutation: FUNNEL_BATTERY_ROW_SAME_DAY
        if _date8(str(row.get("checked_at") or "")) != _date8(str(manifest.get("as_of") or "")):
            raise FunnelError(
                f"battery row is not from the manifest trade date: {row.get('ts_code')}"
            )
        dims = row.get("dims")
        if not isinstance(dims, dict):
            raise FunnelError(f"battery row lacks dims: {row.get('ts_code')}")
        # governance-mutation: FUNNEL_BATTERY_SIX_DIMS
        if tuple(dims.keys()) != BATTERY_DIMENSIONS and set(dims.keys()) != set(BATTERY_DIMENSIONS):
            raise FunnelError(
                f"battery row must carry all six dimensions: {row.get('ts_code')} has {sorted(dims)}"
            )
        for name, evidence in dims.items():
            # governance-mutation: FUNNEL_BATTERY_DIMENSION_EVIDENCE
            if not isinstance(evidence, dict) or not evidence:
                raise FunnelError(
                    f"battery dimension lacks evidence: {row.get('ts_code')} {name}"
                )
            status = evidence.get("status")
            # governance-mutation: FUNNEL_BATTERY_DIMENSION_STATUS
            if status is not None and status not in {"DATA_BLOCKED", "NOT_RUN"}:
                raise FunnelError(
                    f"battery dimension has unknown status: {row.get('ts_code')} {name}={status}"
                )
            if status in {"DATA_BLOCKED", "NOT_RUN"} and not str(evidence.get("err") or "").strip():
                raise FunnelError(
                    f"blocked battery dimension lacks a reason: {row.get('ts_code')} {name}"
                )
        completeness = row.get("completeness") or {}
        if completeness.get("of") != 6 or "verdict" not in completeness:
            raise FunnelError(f"battery row completeness stamp is malformed: {row.get('ts_code')}")
        blocked_dims = [
            name for name, evidence in dims.items()
            if isinstance(evidence, dict)
            and evidence.get("status") in {"DATA_BLOCKED", "NOT_RUN"}
        ]
        expected_verdict = "PARTIAL" if blocked_dims else "COMPLETE"
        # governance-mutation: FUNNEL_BATTERY_COMPLETENESS_RECOMPUTED
        if (
            completeness.get("covered") != 6 - len(blocked_dims)
            or set(completeness.get("missing") or []) != set(blocked_dims)
            or completeness.get("verdict") != expected_verdict
        ):
            raise FunnelError(
                f"battery row completeness does not match six dimensions: {row.get('ts_code')}"
            )
        if expected_verdict != "COMPLETE":
            blocked_rows += 1
    if battery.get("rows_hash") != _hash(rows):
        raise FunnelError("candidate battery rows_hash mismatch")
    return {
        "expected": len(expected),
        "observed": len(observed),
        "data_blocked_rows": blocked_rows,
        "complete_rows": len(observed) - blocked_rows,
    }


def _selftest() -> int:
    # The behavioral suite carries the adversarial coverage.  This smoke test
    # keeps the CLI dependency-free and catches import/argument drift.
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "empty.sqlite3"
        path.touch()
        try:
            load_feature_snapshot(path, "20260811")
        except FunnelError:
            pass
        else:
            raise AssertionError("invalid feature DB must fail closed")
    print("research funnel selftest: 1/1")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default="public/data/v2/security_registry.json")
    parser.add_argument("--e1", default="public/data/v2/e1_event_layer.json")
    parser.add_argument("--feature-db", default="data_history/feature_store.sqlite3")
    parser.add_argument("--rotation", default="public/data/v2/rotation_panel.json")
    parser.add_argument("--macro-industry")
    parser.add_argument("--battery", default="public/data/v2/battery.json")
    parser.add_argument("--output-dir", required=False)
    parser.add_argument("--trade-date")
    parser.add_argument("--u4-selection-file")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.output_dir or not args.trade_date:
        parser.error("--output-dir and --trade-date are required")
    root = Path(__file__).resolve().parents[2]
    resolve = lambda value: Path(value) if Path(value).is_absolute() else root / value
    try:
        selection = _load_json(resolve(args.u4_selection_file)) if args.u4_selection_file else {}
        selection_rows = selection.get("selections", []) if selection else []
        if not isinstance(selection_rows, list):
            raise FunnelError("U4 selection file selections must be a list")
        selected_tickers = [str(row.get("ts_code") or "") for row in selection_rows if isinstance(row, dict)]
        research_questions = {
            str(row.get("ts_code") or ""): str(row.get("research_question") or "")
            for row in selection_rows if isinstance(row, dict)
        }
        sector_os_industries = selection.get("sector_os_industries", []) if selection else []
        outputs = run_pipeline(
            registry_path=resolve(args.registry), e1_path=resolve(args.e1),
            feature_db=resolve(args.feature_db), output_dir=resolve(args.output_dir),
            trade_date=args.trade_date,
            rotation_path=resolve(args.rotation) if args.rotation else None,
            macro_industry_path=resolve(args.macro_industry) if args.macro_industry else None,
            battery_path=resolve(args.battery) if args.battery else None,
            selected_tickers=selected_tickers,
            research_questions=research_questions,
            sector_os_industries=sector_os_industries,
        )
    except (FunnelError, ValueError) as exc:
        print(f"REFUSED: {exc}")
        return 1
    print(json.dumps({key: str(path) for key, path in outputs.items()}, ensure_ascii=False))
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
