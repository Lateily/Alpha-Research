#!/usr/bin/env python3
"""R-036: batch E1 event triage for every U0-listed A-share security.

The layer is a red-flag detector, not a stock selector.  It uses issuer guidance,
earnings express, and filed income statements.  ``NO_RED_FLAG_FOUND`` only means
that the locked checks found no negative event in the available E1 evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .security_registry import (
        RegistryError,
        _atomic_write_json,
        _load_json,
        _sha256,
        _tushare_call,
        validate_registry,
    )
except ImportError:  # direct script execution
    from security_registry import (  # type: ignore
        RegistryError,
        _atomic_write_json,
        _load_json,
        _sha256,
        _tushare_call,
        validate_registry,
    )


SCHEMA = "ar.e1_event_layer"
SCHEMA_VERSION = "1.0"
RULE_VERSION = "R036_E1_RULES_V1"
NEGATIVE_GUIDANCE_TYPES = {"首亏", "预亏", "预减", "略减", "续亏"}
EXPRESS_YOY_NET_PROFIT_THRESHOLD_PCT = -30.0
VERDICTS = {"RED_FLAG", "NO_RED_FLAG_FOUND", "DATA_BLOCKED"}
ENDPOINTS = ("forecast_vip", "express_vip", "income_vip")

FORECAST_FIELDS = (
    "ts_code,ann_date,end_date,type,p_change_min,p_change_max,"
    "net_profit_min,net_profit_max,summary,change_reason"
)
EXPRESS_FIELDS = (
    "ts_code,ann_date,end_date,revenue,n_income,yoy_net_profit,"
    "yoy_dedu_np,diluted_eps,perf_summary"
)
INCOME_FIELDS = "ts_code,ann_date,end_date,report_type,n_income_attr_p"
UNAVAILABLE_DIMENSIONS = (
    {
        "dimension": "formal_announcements",
        "endpoint": "anns_d",
        "status": "DATA_BLOCKED",
        "reason": "separate Tushare permission is not available; E2 news is not an E1 substitute",
    },
)


class E1LayerError(RuntimeError):
    pass


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _date8(value: str) -> str:
    raw = str(value or "").replace("-", "")
    try:
        datetime.strptime(raw, "%Y%m%d")
    except ValueError as exc:
        raise E1LayerError(f"invalid YYYYMMDD date: {value!r}") from exc
    return raw


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else _repo_root() / path


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _recent_periods(as_of: str, count: int = 4) -> list[str]:
    point = datetime.strptime(_date8(as_of), "%Y%m%d").date()
    periods: list[str] = []
    for year in range(point.year, point.year - 4, -1):
        for suffix in ("1231", "0930", "0630", "0331"):
            period = f"{year}{suffix}"
            if period <= as_of:
                periods.append(period)
    return sorted(set(periods), reverse=True)[:count]


def _eligible_registry_rows(registry: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        validate_registry(registry)
    except RegistryError as exc:
        raise E1LayerError(f"U0 registry refused: {exc}") from exc
    if registry.get("status") == "PARTIAL":
        coverage = registry.get("coverage") or {}
        source = registry.get("source") or {}
        if source.get("errors") or coverage.get("preserved_missing_from_source"):
            raise E1LayerError(
                "U0 PARTIAL is not liquidity-only; source/presence gaps block the E1 join"
            )
        if not coverage.get("liquidity_data_blocked"):
            raise E1LayerError("U0 PARTIAL has no recognized liquidity-only reason")
    rows = [
        row
        for row in registry["rows"]
        if row.get("qualification", {}).get("u1_scan_eligible") is True
    ]
    rows.sort(key=lambda row: row["ts_code"])
    if not rows:
        raise E1LayerError("U0 registry has no U1-eligible securities")
    if registry.get("coverage", {}).get("listed") != len(rows):
        raise E1LayerError("U0 listed count does not match U1-eligible rows")
    return rows


def fetch_e1_batches(
    token: str, periods: list[str]
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]], list[dict[str, Any]]]:
    rows_by_endpoint: dict[str, list[dict[str, Any]]] = {name: [] for name in ENDPOINTS}
    errors: list[dict[str, str]] = []
    calls: list[dict[str, Any]] = []
    fields = {
        "forecast_vip": FORECAST_FIELDS,
        "express_vip": EXPRESS_FIELDS,
        "income_vip": INCOME_FIELDS,
    }
    for endpoint in ENDPOINTS:
        for period in periods:
            try:
                rows = _tushare_call(token, endpoint, {"period": period}, fields[endpoint])
                rows_by_endpoint[endpoint].extend(rows)
                calls.append(
                    {"endpoint": endpoint, "period": period, "status": "OK", "rows": len(rows)}
                )
            except RegistryError as exc:
                message = str(exc)
                errors.append({"endpoint": endpoint, "period": period, "error": message})
                calls.append(
                    {"endpoint": endpoint, "period": period, "status": "DATA_BLOCKED", "rows": 0}
                )
    return rows_by_endpoint, errors, calls


def _valid_event_row(row: dict[str, Any], eligible: set[str], as_of: str) -> bool:
    code = str(row.get("ts_code") or "")
    ann_date = str(row.get("ann_date") or "")
    return code in eligible and len(ann_date) == 8 and ann_date.isdigit() and ann_date <= as_of


def _latest_events(
    rows: list[dict[str, Any]], eligible: set[str], as_of: str
) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not _valid_event_row(row, eligible, as_of):
            continue
        code = str(row["ts_code"])
        key = (
            str(row.get("end_date") or ""),
            str(row.get("ann_date") or ""),
            _sha256(row),
        )
        previous = latest.get(code)
        previous_key = (
            str(previous.get("end_date") or ""),
            str(previous.get("ann_date") or ""),
            _sha256(previous),
        ) if previous else ("", "", "")
        if key > previous_key:
            latest[code] = row
    return latest


def _income_by_ticker(
    rows: list[dict[str, Any]], eligible: set[str], as_of: str
) -> dict[str, dict[str, dict[str, Any]]]:
    selected: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        if not isinstance(row, dict) or not _valid_event_row(row, eligible, as_of):
            continue
        if str(row.get("report_type") or "") != "1":
            continue
        code = str(row["ts_code"])
        period = str(row.get("end_date") or "")
        if len(period) != 8 or not period.isdigit() or _number(row.get("n_income_attr_p")) is None:
            continue
        current = selected[code].get(period)
        if current is None or str(row.get("ann_date")) > str(current.get("ann_date")):
            selected[code][period] = row
    return dict(selected)


def _previous_period(period: str) -> str | None:
    year = int(period[:4])
    suffix = period[4:]
    return {
        "0331": f"{year - 1}1231",
        "0630": f"{year}0331",
        "0930": f"{year}0630",
        "1231": f"{year}0930",
    }.get(suffix)


def _standalone_quarters(period_rows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    values = {
        period: _number(row.get("n_income_attr_p"))
        for period, row in period_rows.items()
    }
    quarters: list[dict[str, Any]] = []
    for period in sorted(period_rows, reverse=True):
        cumulative = values.get(period)
        previous = _previous_period(period)
        if cumulative is None:
            continue
        if period[4:] == "0331":
            standalone = cumulative
        elif previous and values.get(previous) is not None:
            standalone = cumulative - float(values[previous])
        else:
            continue
        quarters.append(
            {
                "period": period,
                "ann_date": str(period_rows[period].get("ann_date") or ""),
                "standalone_net_profit_cny": round(standalone, 2),
                "derivation": "cumulative" if period[4:] == "0331" else f"cumulative_minus_{previous}",
            }
        )
    return quarters


def _forecast_evidence(row: dict[str, Any] | None) -> tuple[dict[str, Any] | None, bool]:
    if not row:
        return None, False
    guidance_type = str(row.get("type") or "")
    low = _number(row.get("net_profit_min"))
    high = _number(row.get("net_profit_max"))
    negative = guidance_type in NEGATIVE_GUIDANCE_TYPES or (high is not None and high < 0)
    evidence = {
        "kind": "ISSUER_GUIDANCE",
        "source": "tushare.forecast_vip",
        "evidence_grade": "E1",
        "ann_date": str(row.get("ann_date") or ""),
        "period": str(row.get("end_date") or ""),
        "observed": {
            "type": guidance_type or None,
            "net_profit_min_cny": None if low is None else round(low * 10_000.0, 2),
            "net_profit_max_cny": None if high is None else round(high * 10_000.0, 2),
            "p_change_min_pct": _number(row.get("p_change_min")),
            "p_change_max_pct": _number(row.get("p_change_max")),
        },
        "triggered": negative,
        "rule": "latest guidance type in locked negative set or net-profit upper bound below zero",
    }
    return evidence, negative


def _express_evidence(
    row: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, bool, bool]:
    if not row:
        return None, False, True
    current_profit = _number(row.get("n_income"))
    prior_profit = _number(row.get("yoy_net_profit"))
    official_yoy_pct = _number(row.get("yoy_dedu_np"))
    yoy_pct = official_yoy_pct
    yoy_source = "tushare.express_vip.yoy_dedu_np"
    if yoy_pct is None and current_profit is not None and prior_profit not in (None, 0.0):
        yoy_pct = (current_profit - prior_profit) / abs(prior_profit) * 100.0
        yoy_source = "computed_from_n_income_and_yoy_net_profit/v1"
    scorable = yoy_pct is not None
    negative = scorable and yoy_pct < EXPRESS_YOY_NET_PROFIT_THRESHOLD_PCT
    evidence = {
        "kind": "EARNINGS_EXPRESS",
        "source": "tushare.express_vip",
        "evidence_grade": "E1",
        "ann_date": str(row.get("ann_date") or ""),
        "period": str(row.get("end_date") or ""),
        "observed": {
            "net_profit_yoy_pct": None if yoy_pct is None else round(yoy_pct, 6),
            "net_profit_yoy_pct_source": yoy_source if scorable else None,
            "prior_year_adjusted_net_profit_cny": prior_profit,
            "net_profit_cny": current_profit,
            "revenue_cny": _number(row.get("revenue")),
        },
        "triggered": negative,
        "rule": (
            "latest active express net-profit YoY metric < "
            f"{EXPRESS_YOY_NET_PROFIT_THRESHOLD_PCT:g}%"
        ),
    }
    return evidence, negative, scorable


def _income_evidence(quarters: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, bool]:
    if len(quarters) < 2:
        return None, False
    latest, previous = quarters[0], quarters[1]
    latest_value = float(latest["standalone_net_profit_cny"])
    previous_value = float(previous["standalone_net_profit_cny"])
    negative = latest_value < 0 and latest_value < previous_value
    evidence = {
        "kind": "FILED_INCOME_TREND",
        "source": "tushare.income_vip",
        "evidence_grade": "E1",
        "ann_date": latest["ann_date"],
        "period": latest["period"],
        "observed": {
            "latest_standalone_net_profit_cny": latest_value,
            "previous_period": previous["period"],
            "previous_standalone_net_profit_cny": previous_value,
        },
        "triggered": negative,
        "rule": "latest standalone attributable profit < 0 and below previous quarter",
    }
    return evidence, negative


def _classify_row(
    registry_row: dict[str, Any],
    forecast: dict[str, Any] | None,
    express: dict[str, Any] | None,
    income_periods: dict[str, dict[str, Any]],
    source_complete: bool,
) -> dict[str, Any]:
    quarters = _standalone_quarters(income_periods)
    latest_filed_period = max(income_periods, default="")
    forecast_superseded = bool(
        forecast
        and latest_filed_period
        and str(forecast.get("end_date") or "") <= latest_filed_period
    )
    express_superseded = bool(
        express
        and latest_filed_period
        and str(express.get("end_date") or "") <= latest_filed_period
    )
    active_forecast = None if forecast_superseded else forecast
    active_express = None if express_superseded else express
    forecast_ev, forecast_flag = _forecast_evidence(active_forecast)
    express_ev, express_flag, express_scorable = _express_evidence(active_express)
    income_ev, income_flag = _income_evidence(quarters)
    evaluated_evidence = [
        item for item in (forecast_ev, express_ev, income_ev) if item is not None
    ]
    evidence = [item for item in evaluated_evidence if item["triggered"]]
    reason_codes: list[str] = []
    if forecast_flag:
        reason_codes.append("NEGATIVE_ISSUER_GUIDANCE")
    if express_flag:
        reason_codes.append("EXPRESS_NET_PROFIT_DROP_GT_30PCT")
    if income_flag:
        reason_codes.append("NEGATIVE_AND_WORSENING_QUARTER_PROFIT")

    if reason_codes:
        verdict = "RED_FLAG"
    elif not source_complete:
        verdict = "DATA_BLOCKED"
        reason_codes.append("E1_SOURCE_PARTIAL")
    elif not express_scorable:
        verdict = "DATA_BLOCKED"
        reason_codes.append("EXPRESS_YOY_METRIC_MISSING")
    elif len(quarters) < 2:
        verdict = "DATA_BLOCKED"
        reason_codes.append("INSUFFICIENT_FILED_QUARTER_HISTORY")
    else:
        verdict = "NO_RED_FLAG_FOUND"

    dates = [str(item.get("ann_date") or "") for item in evaluated_evidence]
    latest_e1_date = max([value for value in dates if value], default=None)
    return {
        "ts_code": registry_row["ts_code"],
        "name": registry_row["name"],
        "industry_key": registry_row["industry_key"],
        "verdict": verdict,
        "reason_codes": sorted(reason_codes),
        "latest_e1_date": latest_e1_date,
        "evidence_coverage": {
            "forecast": (
                "SUPERSEDED"
                if forecast_superseded
                else "PRESENT"
                if forecast_ev
                else "EMPTY_VALID"
            ),
            "express": (
                "SUPERSEDED"
                if express_superseded
                else "PRESENT"
                if express_ev and express_scorable
                else "DATA_BLOCKED"
                if express_ev
                else "EMPTY_VALID"
            ),
            "filed_quarters": len(quarters),
            "income": "COMPLETE" if len(quarters) >= 2 else "DATA_BLOCKED",
            "formal_announcements": "DATA_BLOCKED",
        },
        "evidence": evidence,
    }


def build_event_layer(
    registry: dict[str, Any],
    rows_by_endpoint: dict[str, list[dict[str, Any]]],
    *,
    as_of: str,
    generated_at: str | None = None,
    periods: list[str] | None = None,
    source_errors: list[dict[str, str]] | None = None,
    source_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    as_of = _date8(as_of)
    generated_at = generated_at or _now_utc()
    periods = periods or _recent_periods(as_of)
    source_errors = list(source_errors or [])
    source_calls = list(source_calls or [])
    registry_rows = _eligible_registry_rows(registry)
    eligible = {row["ts_code"] for row in registry_rows}

    forecast = _latest_events(rows_by_endpoint.get("forecast_vip", []), eligible, as_of)
    express = _latest_events(rows_by_endpoint.get("express_vip", []), eligible, as_of)
    incomes = _income_by_ticker(rows_by_endpoint.get("income_vip", []), eligible, as_of)
    source_complete = not source_errors
    output_rows = [
        _classify_row(
            row,
            forecast.get(row["ts_code"]),
            express.get(row["ts_code"]),
            incomes.get(row["ts_code"], {}),
            source_complete=source_complete,
        )
        for row in registry_rows
    ]
    counts = {verdict: sum(row["verdict"] == verdict for row in output_rows) for verdict in VERDICTS}
    unavailable_dimensions = [dict(item) for item in UNAVAILABLE_DIMENSIONS]
    status = (
        "PARTIAL"
        if source_errors or counts["DATA_BLOCKED"] or unavailable_dimensions
        else "COMPLETE"
    )
    outside_occurrences = [
        str(row.get("ts_code") or "")
        for endpoint_rows in rows_by_endpoint.values()
        for row in endpoint_rows
        if str(row.get("ts_code") or "") not in eligible
    ]
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "status": status,
        "as_of": as_of,
        "generated_at": generated_at,
        "registry_ref": {
            "schema_version": registry["schema_version"],
            "as_of": registry["as_of"],
            "status": registry["status"],
            "registry_hash": registry["registry_hash"],
            "eligible_universe_hash": registry["eligible_universe_hash"],
            "eligible_count": len(registry_rows),
            "accepted_partial_dimensions": (
                ["liquidity"] if registry["status"] == "PARTIAL" else []
            ),
        },
        "source": {
            "provider": "Tushare Pro",
            "endpoints": list(ENDPOINTS),
            "periods": periods,
            "calls": source_calls,
            "errors": source_errors,
            "unavailable_dimensions": unavailable_dimensions,
        },
        "policy": {
            "negative_guidance_types": sorted(NEGATIVE_GUIDANCE_TYPES),
            "express_net_profit_yoy_threshold_pct": EXPRESS_YOY_NET_PROFIT_THRESHOLD_PCT,
            "express_yoy_metric": (
                "prefer tushare.express_vip.yoy_dedu_np; otherwise compute "
                "(n_income-yoy_net_profit)/abs(yoy_net_profit)*100 from official amounts"
            ),
            "event_lifecycle": (
                "prefer the latest report period, then announcement date; a filed income "
                "statement supersedes guidance/express for the same or an earlier period"
            ),
            "income_rule": "latest standalone attributable profit < 0 and below previous quarter",
            "no_red_flag_semantics": "absence of a locked red flag, not research approval or a selection signal",
            "row_evidence_semantics": (
                "rows retain detailed evidence only for triggered red flags; coverage states "
                "and latest_e1_date prove which non-triggering dimensions were evaluated"
            ),
            "source_documentation": {
                "forecast": "https://tushare.pro/document/2?doc_id=45",
                "express": "https://tushare.pro/document/2?doc_id=46",
            },
            "evidence_grade": "E1",
            "rows_hash_algorithm": "sha256(canonical_json(rows))/v1",
        },
        "coverage": {
            "registry_eligible": len(registry_rows),
            "rows": len(output_rows),
            "red_flag": counts["RED_FLAG"],
            "no_red_flag_found": counts["NO_RED_FLAG_FOUND"],
            "data_blocked": counts["DATA_BLOCKED"],
            "forecast_latest_rows": len(forecast),
            "forecast_active_rows": sum(
                row["evidence_coverage"]["forecast"] == "PRESENT" for row in output_rows
            ),
            "forecast_superseded_rows": sum(
                row["evidence_coverage"]["forecast"] == "SUPERSEDED" for row in output_rows
            ),
            "express_latest_rows": len(express),
            "express_active_rows": sum(
                row["evidence_coverage"]["express"] == "PRESENT" for row in output_rows
            ),
            "express_superseded_rows": sum(
                row["evidence_coverage"]["express"] == "SUPERSEDED" for row in output_rows
            ),
            "income_tickers": len(incomes),
            "formal_announcements": "DATA_BLOCKED",
            "source_row_occurrences_outside_u0": len(outside_occurrences),
            "source_tickers_outside_u0": len(set(outside_occurrences)),
        },
        "rows_hash": _sha256(output_rows),
        "rows": output_rows,
        "disclaimer": (
            "Financial E1 red-flag triage only. Formal announcements are DATA_BLOCKED. "
            "NO_RED_FLAG_FOUND is not research approval, a ranking, or a trading action."
        ),
    }


def validate_event_layer(payload: dict[str, Any]) -> None:
    if payload.get("schema") != SCHEMA or payload.get("schema_version") != SCHEMA_VERSION:
        raise E1LayerError("event-layer schema/version mismatch")
    if payload.get("rule_version") != RULE_VERSION:
        raise E1LayerError("event-layer rule version mismatch")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise E1LayerError("event-layer rows must be a non-empty list")
    if payload.get("rows_hash") != _sha256(rows):
        raise E1LayerError("event-layer rows_hash mismatch")
    codes = [str(row.get("ts_code") or "") for row in rows if isinstance(row, dict)]
    if len(codes) != len(rows) or len(codes) != len(set(codes)):
        raise E1LayerError("event-layer contains invalid or duplicate rows")
    if codes != sorted(codes):
        raise E1LayerError("event-layer rows must be sorted by ts_code")
    if any(row.get("verdict") not in VERDICTS for row in rows):
        raise E1LayerError("event-layer contains an invalid verdict")
    if any(row.get("verdict") == "PASS" for row in rows):
        raise E1LayerError("PASS is forbidden; use NO_RED_FLAG_FOUND")
    as_of = str(payload.get("as_of") or "")
    for row in rows:
        evidence = row.get("evidence")
        if not isinstance(evidence, list) or any(
            not isinstance(item, dict) or item.get("triggered") is not True
            for item in evidence
        ):
            raise E1LayerError("row evidence must contain triggered E1 records only")
        if row["verdict"] == "RED_FLAG" and not evidence:
            raise E1LayerError("RED_FLAG row has no triggered evidence")
        if row["verdict"] != "RED_FLAG" and evidence:
            raise E1LayerError("non-red row contains triggered evidence")
        latest = row.get("latest_e1_date")
        if latest is not None and (not isinstance(latest, str) or latest > as_of):
            raise E1LayerError("row latest_e1_date exceeds contract as_of")
    registry_ref = payload.get("registry_ref") or {}
    if registry_ref.get("eligible_count") != len(rows):
        raise E1LayerError("event-layer row count differs from U0 eligible count")
    coverage = payload.get("coverage") or {}
    expected = {
        "rows": len(rows),
        "red_flag": sum(row["verdict"] == "RED_FLAG" for row in rows),
        "no_red_flag_found": sum(row["verdict"] == "NO_RED_FLAG_FOUND" for row in rows),
        "data_blocked": sum(row["verdict"] == "DATA_BLOCKED" for row in rows),
        "forecast_active_rows": sum(
            row["evidence_coverage"]["forecast"] == "PRESENT" for row in rows
        ),
        "forecast_superseded_rows": sum(
            row["evidence_coverage"]["forecast"] == "SUPERSEDED" for row in rows
        ),
        "express_active_rows": sum(
            row["evidence_coverage"]["express"] == "PRESENT" for row in rows
        ),
        "express_superseded_rows": sum(
            row["evidence_coverage"]["express"] == "SUPERSEDED" for row in rows
        ),
    }
    mismatches = {
        key: {"declared": coverage.get(key), "computed": value}
        for key, value in expected.items()
        if coverage.get(key) != value
    }
    if mismatches:
        raise E1LayerError(f"event-layer coverage mismatch: {mismatches}")
    source = payload.get("source") or {}
    periods = source.get("periods") or []
    calls = source.get("calls") or []
    if len(calls) != len(ENDPOINTS) * len(periods):
        raise E1LayerError("event-layer source call matrix is incomplete")
    if coverage.get("forecast_latest_rows") != (
        expected["forecast_active_rows"] + expected["forecast_superseded_rows"]
    ):
        raise E1LayerError("forecast lifecycle coverage does not reconcile")
    express_blocked = sum(
        row["evidence_coverage"]["express"] == "DATA_BLOCKED" for row in rows
    )
    if coverage.get("express_latest_rows") != (
        expected["express_active_rows"]
        + expected["express_superseded_rows"]
        + express_blocked
    ):
        raise E1LayerError("express lifecycle coverage does not reconcile")
    if coverage.get("formal_announcements") != "DATA_BLOCKED":
        raise E1LayerError("formal-announcement coverage must remain explicit")
    source_errors = source.get("errors") or []
    unavailable_dimensions = source.get("unavailable_dimensions") or []
    expected_status = (
        "PARTIAL"
        if source_errors or unavailable_dimensions or expected["data_blocked"]
        else "COMPLETE"
    )
    if payload.get("status") != expected_status:
        raise E1LayerError(
            f"event-layer status mismatch: declared={payload.get('status')} computed={expected_status}"
        )


def _fixture_registry(as_of: str) -> dict[str, Any]:
    from security_registry import build_registry  # type: ignore

    source_rows = []
    liquidity: dict[str, list[float]] = {}
    for index in range(1, 6):
        code = f"60000{index}.SH"
        source_rows.append(
            {
                "ts_code": code,
                "symbol": code[:6],
                "name": f"测试{index}",
                "area": "上海",
                "industry": "测试行业",
                "market": "主板",
                "exchange": "SSE",
                "list_status": "L",
                "list_date": "20200101",
                "delist_date": "",
            }
        )
        liquidity[code] = [30_000_000.0] * 10
    return build_registry(
        source_rows,
        as_of=as_of,
        generated_at="2026-08-05T08:00:00+00:00",
        liquidity_by_code=liquidity,
        traded_as_of=set(liquidity),
    )


def _selftest() -> int:
    as_of = "20260805"
    registry = _fixture_registry(as_of)
    income_rows: list[dict[str, Any]] = []
    for index in range(1, 5):
        code = f"60000{index}.SH"
        values = {"20250930": 80.0, "20251231": 100.0, "20260331": 30.0}
        if index == 4:
            values["20260331"] = -10.0
        for period, value in values.items():
            income_rows.append(
                {
                    "ts_code": code,
                    "ann_date": "20260430" if period == "20260331" else "20260331",
                    "end_date": period,
                    "report_type": "1",
                    "n_income_attr_p": value,
                }
            )
    income_rows.append(
        {
            "ts_code": "600005.SH",
            "ann_date": "20260430",
            "end_date": "20260331",
            "report_type": "1",
            "n_income_attr_p": 10.0,
        }
    )
    forecast_rows = [
        {
            "ts_code": "600001.SH",
            "ann_date": "20260120",
            "end_date": "20251231",
            "type": "首亏",
            "net_profit_min": -20.0,
            "net_profit_max": -10.0,
        },
        {
            "ts_code": "600001.SH",
            "ann_date": "20260710",
            "end_date": "20260630",
            "type": "预增",
            "net_profit_min": 20.0,
            "net_profit_max": 30.0,
        },
        {
            "ts_code": "600001.SH",
            "ann_date": "20260806",
            "end_date": "20260630",
            "type": "首亏",
            "net_profit_min": -20.0,
            "net_profit_max": -10.0,
        },
        {
            "ts_code": "600002.SH",
            "ann_date": "20260711",
            "end_date": "20260630",
            "type": "首亏",
            "net_profit_min": -20.0,
            "net_profit_max": -10.0,
        },
    ]
    express_rows = [
        {
            "ts_code": "600003.SH",
            "ann_date": "20260720",
            "end_date": "20260630",
            "yoy_net_profit": 20.0,
            "n_income": 10.0,
            "revenue": 100.0,
        }
    ]
    fixture_periods = ["20260331", "20251231", "20250930"]
    fixture_calls = [
        {"endpoint": endpoint, "period": period, "status": "OK", "rows": 0}
        for endpoint in ENDPOINTS
        for period in fixture_periods
    ]
    payload = build_event_layer(
        registry,
        {
            "forecast_vip": forecast_rows,
            "express_vip": express_rows,
            "income_vip": income_rows,
        },
        as_of=as_of,
        generated_at="2026-08-05T09:00:00+00:00",
        periods=fixture_periods,
        source_calls=fixture_calls,
    )
    validate_event_layer(payload)
    rows = {row["ts_code"]: row for row in payload["rows"]}
    period_first = _latest_events(
        [
            {
                "ts_code": "600001.SH",
                "ann_date": "20260801",
                "end_date": "20251231",
            },
            {
                "ts_code": "600001.SH",
                "ann_date": "20260701",
                "end_date": "20260630",
            },
        ],
        {"600001.SH"},
        as_of,
    )
    stale_forecast = _classify_row(
        registry["rows"][0],
        {
            "ts_code": "600001.SH",
            "ann_date": "20260420",
            "end_date": "20251231",
            "type": "首亏",
            "net_profit_max": -10.0,
        },
        None,
        {
            row["end_date"]: row
            for row in income_rows
            if row["ts_code"] == "600001.SH"
        },
        source_complete=True,
    )
    checks = [
        (len(rows) == 5, "every U0-listed security retained"),
        (rows["600001.SH"]["verdict"] == "NO_RED_FLAG_FOUND", "latest valid guidance wins"),
        (rows["600002.SH"]["verdict"] == "RED_FLAG", "negative issuer guidance flagged"),
        ("NEGATIVE_ISSUER_GUIDANCE" in rows["600002.SH"]["reason_codes"], "guidance reason coded"),
        (rows["600003.SH"]["verdict"] == "RED_FLAG", "express decline flagged"),
        (rows["600004.SH"]["verdict"] == "RED_FLAG", "negative worsening quarter flagged"),
        (rows["600005.SH"]["verdict"] == "DATA_BLOCKED", "insufficient income history blocked"),
        (payload["status"] == "PARTIAL", "row DATA_BLOCKED surfaces top-level PARTIAL"),
        (all(row["verdict"] != "PASS" for row in payload["rows"]), "PASS vocabulary forbidden"),
        (payload["rows_hash"] == _sha256(payload["rows"]), "rows hash valid"),
        (
            period_first["600001.SH"]["end_date"] == "20260630",
            "latest report period outranks a later old-period announcement",
        ),
        (
            stale_forecast["verdict"] == "NO_RED_FLAG_FOUND"
            and stale_forecast["evidence_coverage"]["forecast"] == "SUPERSEDED",
            "filed statements retire same-period and older guidance",
        ),
        (
            payload["source"]["unavailable_dimensions"][0]["endpoint"] == "anns_d"
            and payload["coverage"]["formal_announcements"] == "DATA_BLOCKED",
            "formal-announcement permission gap is explicit",
        ),
    ]
    amount_not_percentage = _express_evidence(
        {
            "ts_code": "920038.BJ",
            "ann_date": "20260720",
            "end_date": "20260630",
            "yoy_net_profit": -74_400_964.91,
            "n_income": -55_846_879.39,
        }
    )
    checks.append(
        (
            amount_not_percentage[1] is False
            and amount_not_percentage[0]["observed"]["prior_year_adjusted_net_profit_cny"]
            == -74_400_964.91,
            "prior-year profit amount is never interpreted as a percentage",
        )
    )
    missing_express_metric = build_event_layer(
        registry,
        {
            "forecast_vip": forecast_rows,
            "express_vip": [
                {
                    "ts_code": "600003.SH",
                    "ann_date": "20260720",
                    "end_date": "20260630",
                    "yoy_net_profit": 20.0,
                }
            ],
            "income_vip": income_rows,
        },
        as_of=as_of,
    )
    missing_row = next(row for row in missing_express_metric["rows"] if row["ts_code"] == "600003.SH")
    checks.append(
        (
            missing_row["verdict"] == "DATA_BLOCKED"
            and "EXPRESS_YOY_METRIC_MISSING" in missing_row["reason_codes"],
            "missing all scorable express inputs blocks a clean verdict",
        )
    )
    source_failed = build_event_layer(
        registry,
        {"forecast_vip": [], "express_vip": [], "income_vip": income_rows},
        as_of=as_of,
        source_errors=[{"endpoint": "forecast_vip", "period": "20260630", "error": "blocked"}],
    )
    checks.append(
        (
            source_failed["status"] == "PARTIAL"
            and all(row["verdict"] in {"RED_FLAG", "DATA_BLOCKED"} for row in source_failed["rows"]),
            "source failure cannot yield clean verdict",
        )
    )
    unsafe_registry = json.loads(json.dumps(registry))
    unsafe_registry["status"] = "PARTIAL"
    unsafe_registry["source"]["errors"] = ["stock_basic failed"]
    try:
        build_event_layer(
            unsafe_registry,
            {"forecast_vip": [], "express_vip": [], "income_vip": income_rows},
            as_of=as_of,
        )
        checks.append((False, "non-liquidity U0 PARTIAL rejected"))
    except E1LayerError:
        checks.append((True, "non-liquidity U0 PARTIAL rejected"))
    corrupt = json.loads(json.dumps(payload))
    corrupt["coverage"]["red_flag"] += 1
    try:
        validate_event_layer(corrupt)
        checks.append((False, "coverage drift rejected"))
    except E1LayerError:
        checks.append((True, "coverage drift rejected"))
    corrupt = json.loads(json.dumps(payload))
    corrupt["rows"][0]["verdict"] = "PASS"
    corrupt["rows_hash"] = _sha256(corrupt["rows"])
    try:
        validate_event_layer(corrupt)
        checks.append((False, "legacy PASS rejected"))
    except E1LayerError:
        checks.append((True, "legacy PASS rejected"))
    corrupt = json.loads(json.dumps(payload))
    corrupt["rows"] = list(reversed(corrupt["rows"]))
    corrupt["rows_hash"] = _sha256(corrupt["rows"])
    try:
        validate_event_layer(corrupt)
        checks.append((False, "row-order drift rejected"))
    except E1LayerError:
        checks.append((True, "row-order drift rejected"))
    corrupt = json.loads(json.dumps(payload))
    red = next(row for row in corrupt["rows"] if row["verdict"] == "RED_FLAG")
    red["evidence"][0]["triggered"] = False
    corrupt["rows_hash"] = _sha256(corrupt["rows"])
    try:
        validate_event_layer(corrupt)
        checks.append((False, "non-triggering evidence rejected"))
    except E1LayerError:
        checks.append((True, "non-triggering evidence rejected"))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "e1.json"
        _atomic_write_json(path, payload)
        validate_event_layer(_load_json(path))
        checks.append((True, "atomic round trip"))

    for ok, name in checks:
        print(("PASS" if ok else "FAIL"), name)
    passed = sum(ok for ok, _ in checks)
    print(f"SELFTEST {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the full-market U0-linked E1 event layer")
    parser.add_argument("--as-of", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--registry", default="public/data/v2/security_registry.json")
    parser.add_argument("--output", default="public/data/v2/e1_event_layer.json")
    parser.add_argument("--input", help="offline JSON containing endpoint rows/errors/calls")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()

    as_of = _date8(args.as_of)
    periods = _recent_periods(as_of)
    registry = _load_json(_resolve(args.registry))
    if args.input:
        fixture = _load_json(_resolve(args.input))
        rows_by_endpoint = fixture.get("rows_by_endpoint") or {}
        source_errors = fixture.get("source_errors") or []
        source_calls = fixture.get("source_calls") or []
    else:
        token = os.environ.get("TUSHARE_TOKEN", "").strip()
        if not token:
            raise E1LayerError("TUSHARE_TOKEN is required for live E1 event build")
        rows_by_endpoint, source_errors, source_calls = fetch_e1_batches(token, periods)
    payload = build_event_layer(
        registry,
        rows_by_endpoint,
        as_of=as_of,
        periods=periods,
        source_errors=source_errors,
        source_calls=source_calls,
    )
    validate_event_layer(payload)
    output = _resolve(args.output)
    _atomic_write_json(output, payload)
    coverage = payload["coverage"]
    print(
        f"[written] {output} status={payload['status']} rows={coverage['rows']} "
        f"red={coverage['red_flag']} clear={coverage['no_red_flag_found']} "
        f"blocked={coverage['data_blocked']}"
    )
    print("E1 red-flag triage only; no research approval or trading action.")
    return 0 if payload["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (E1LayerError, RegistryError) as exc:
        print(f"E1_LAYER_REFUSED: {exc}")
        raise SystemExit(2)
