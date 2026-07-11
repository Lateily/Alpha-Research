#!/usr/bin/env python3
"""Point-in-time factor calculator for historical A-share screening.

This module computes factor exposures as of a decision date T from the raw
data_history/ payloads. The correctness boundary is PitDataStore from
backtest_v2.py: prices and financial statements are only read through as-of
accessors, and daily_basic is attached with the same <= T lookup discipline.

Causal logic is valid for mechanical cross-sectional factor screening because
the factors use only price history and announced financial statements available
at the rebalance date. Specific factor blends, windows, and 0-100 percentile
scores are unvalidated intuitions and must be calibrated later from real trade
history.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

try:
    from scripts.backtest_v2 import PitDataStore, _to_date
except ModuleNotFoundError:  # Running as python3 scripts/pit_factors.py
    from backtest_v2 import PitDataStore, _to_date


REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_HISTORY = REPO_ROOT / "data_history"
RAW_COMPONENT_KEYS = (
    "market_cap",
    "roe",
    "gross_margin",
    "net_margin",
    "leverage",
    "low_leverage",
    "earnings_yield",
    "book_yield",
    "revenue_growth_yoy",
    "net_income_growth_yoy",
)

CONFIG = {
    "momentum_lookback_td": 252,
    "momentum_skip_td": 21,
    "vol_window_td": 120,
    "min_vol_obs": 20,
    # Tushare daily_basic.total_mv is reported in 10k CNY; financial statements
    # are CNY. Override this if a non-Tushare source is used in fixtures.
    "market_cap_multiplier": 10000.0,
    # Value descriptor weights (Liu-Stambaugh-Yuan 2019 finding: in A-share, E/P
    # dominates B/M — change from equal-weight to E/P-heavy. iter-8 default.
    # Set value_ep_weight=0.5 to recover the pre-iter-8 equal-weight blend.)
    "value_ep_weight": 0.7,    # earnings_yield weight
    "value_bp_weight": 0.3,    # book_yield weight (sum should be 1.0)
}

FLOW_FIELDS = ("revenue", "oper_cost", "n_income", "n_income_attr_p")
REVENUE_ALIASES = ("revenue", "total_revenue", "oper_rev")
OPER_COST_ALIASES = ("oper_cost", "total_oper_cost", "biz_cost", "less_oper_cost")
NET_INCOME_ALIASES = ("n_income_attr_p", "n_income", "net_profit", "net_income")
NET_INCOME_PARENT_ALIASES = ("n_income_attr_p", "net_profit_parent_company", "parent_net_profit", "n_income")
EQUITY_ALIASES = (
    "total_hldr_eqy_exc_min_int",
    "total_hldr_eqy_inc_min_int",
    "total_hldr_eqy",
    "total_equity",
)
TOTAL_ASSETS_ALIASES = ("total_assets", "assets_total")
TOTAL_LIAB_ALIASES = ("total_liab", "total_liabilities", "liab_total")
MARKET_CAP_ALIASES = ("total_mv", "market_cap", "total_market_cap")


def _to_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
        if not value or value in {"--", "-", "None", "nan", "NaN", "null"}:
            return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _round_or_none(value, digits=6):
    value = _to_float(value)
    return None if value is None else round(value, digits)


def _first_number(row: dict, aliases: tuple[str, ...]) -> Optional[float]:
    for key in aliases:
        value = _to_float(row.get(key))
        if value is not None:
            return value
    return None


def _safe_div(num, den) -> Optional[float]:
    num = _to_float(num)
    den = _to_float(den)
    if num is None or den is None or den == 0:
        return None
    return num / den


def _avg(values) -> Optional[float]:
    clean = [_to_float(v) for v in values]
    clean = [v for v in clean if v is not None]
    if len(clean) != len(values) or not clean:
        return None
    return sum(clean) / len(clean)


def _date_key(row: dict, *keys) -> Optional[date]:
    for key in keys:
        parsed = _to_date(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _is_non_empty(value) -> bool:
    return value is not None and value != "" and value == value


def _merge_statement_rows(rows: list[dict]) -> list[dict]:
    """Merge income/balance/cashflow rows for the same report period.

    PitDataStore has already filtered rows by ann_date <= T. Merging here is
    PIT-safe because every contributing row is already known as of T; the merged
    row's _ann_date is the max known announcement date among its components.
    """
    grouped: dict[str, dict] = {}
    sorted_rows = sorted(
        rows or [],
        key=lambda r: (
            _date_key(r, "_ann_date", "ann_date", "f_ann_date") or date.min,
            _date_key(r, "end_date", "period", "report_date") or date.min,
        ),
    )
    for idx, row in enumerate(sorted_rows):
        end_date = _date_key(row, "end_date", "period", "report_date")
        ann_date = _date_key(row, "_ann_date", "ann_date", "f_ann_date")
        key = end_date.isoformat() if end_date else f"ann:{ann_date}:{idx}"
        merged = grouped.setdefault(
            key,
            {
                "_end_date": end_date,
                "end_date": end_date.isoformat() if end_date else None,
                "_ann_date": ann_date,
                "ann_date": ann_date.isoformat() if ann_date else None,
                "_source_row_count": 0,
            },
        )
        merged["_source_row_count"] += 1
        if ann_date and (merged.get("_ann_date") is None or ann_date > merged["_ann_date"]):
            merged["_ann_date"] = ann_date
            merged["ann_date"] = ann_date.isoformat()
        for k, v in row.items():
            if k in {"_ann_date", "_end_date"}:
                continue
            if _is_non_empty(v):
                merged[k] = v
    return sorted(
        grouped.values(),
        key=lambda r: (r.get("_end_date") or date.min, r.get("_ann_date") or date.min),
    )


def _financials_asof(store: PitDataStore, ticker: str, as_of: date) -> list[dict]:
    return _merge_statement_rows(store.financials_asof(ticker, as_of))


def _latest_statement(financials: list[dict]) -> Optional[dict]:
    rows = [
        r for r in financials
        if r.get("_end_date") is not None or _date_key(r, "end_date", "period", "report_date")
    ]
    if not rows:
        return None
    return max(
        rows,
        key=lambda r: (
            r.get("_end_date") or _date_key(r, "end_date", "period", "report_date") or date.min,
            r.get("_ann_date") or _date_key(r, "_ann_date", "ann_date", "f_ann_date") or date.min,
        ),
    )


def _quarter_number(d: date) -> Optional[int]:
    if d is None:
        return None
    return {3: 1, 6: 2, 9: 3, 12: 4}.get(d.month) if d.day in {30, 31} else None


def _prev_quarter_end(d: date) -> Optional[date]:
    q = _quarter_number(d)
    if q is None:
        return None
    if q == 1:
        return date(d.year - 1, 12, 31)
    return {2: date(d.year, 3, 31), 3: date(d.year, 6, 30), 4: date(d.year, 9, 30)}[q]


def _flow_snapshot(row: dict) -> dict:
    return {
        "revenue": _first_number(row, REVENUE_ALIASES),
        "oper_cost": _first_number(row, OPER_COST_ALIASES),
        "n_income": _first_number(row, NET_INCOME_ALIASES),
        "n_income_attr_p": _first_number(row, NET_INCOME_PARENT_ALIASES),
    }


def _has_flow(row: dict) -> bool:
    snap = _flow_snapshot(row)
    return all(snap.get(k) is not None for k in FLOW_FIELDS)


def _annual_ttm(financials: list[dict]) -> tuple[Optional[dict], dict]:
    annuals = []
    for row in financials:
        end_date = row.get("_end_date")
        if end_date is None:
            continue
        if end_date.month == 12 and end_date.day == 31 and _has_flow(row):
            annuals.append(row)
    if not annuals:
        return None, {"income_basis": "missing"}
    latest = max(annuals, key=lambda r: (r["_end_date"], r.get("_ann_date") or date.min))
    flows = _flow_snapshot(latest)
    return flows, {
        "income_basis": "annual",
        "income_end_date": latest["_end_date"].isoformat(),
        "income_ann_date": (latest.get("_ann_date") or date.min).isoformat(),
        "ttm_quarter_count": None,
    }


def _quarterly_ttm(financials: list[dict]) -> tuple[Optional[dict], dict]:
    by_end = {
        row["_end_date"]: row
        for row in financials
        if row.get("_end_date") is not None and _quarter_number(row["_end_date"]) is not None
    }
    quarter_flows = []
    for end_date in sorted(by_end):
        row = by_end[end_date]
        if not _has_flow(row):
            continue
        q = _quarter_number(end_date)
        current = _flow_snapshot(row)
        if q == 1:
            discrete = current
        else:
            prev = by_end.get(_prev_quarter_end(end_date))
            if prev is None or not _has_flow(prev):
                continue
            prev_flow = _flow_snapshot(prev)
            discrete = {
                key: current[key] - prev_flow[key]
                for key in FLOW_FIELDS
                if current.get(key) is not None and prev_flow.get(key) is not None
            }
        if len(discrete) == len(FLOW_FIELDS):
            quarter_flows.append({"end_date": end_date, "row": row, "flow": discrete})

    if len(quarter_flows) < 4:
        return None, {"income_basis": "missing"}
    last4 = quarter_flows[-4:]
    expected = [_prev_quarter_end(last4[i]["end_date"]) for i in range(1, 4)]
    actual_prev = [last4[i - 1]["end_date"] for i in range(1, 4)]
    if expected != actual_prev:
        return None, {"income_basis": "missing"}
    flows = {key: sum(q["flow"][key] for q in last4) for key in FLOW_FIELDS}
    return flows, {
        "income_basis": "ttm_quarterly_from_ytd_deltas",
        "income_end_date": last4[-1]["end_date"].isoformat(),
        "income_ann_date": (last4[-1]["row"].get("_ann_date") or date.min).isoformat(),
        "ttm_quarter_count": 4,
        "ttm_quarter_ends": [q["end_date"].isoformat() for q in last4],
    }


def _ttm_flows(financials: list[dict]) -> tuple[Optional[dict], dict]:
    flows, basis = _quarterly_ttm(financials)
    if flows is not None:
        return flows, basis
    return _annual_ttm(financials)


def _same_period_prior(financials: list[dict], latest: dict) -> Optional[dict]:
    end_date = latest.get("_end_date")
    if end_date is None:
        return None
    target = date(end_date.year - 1, end_date.month, end_date.day)
    matches = [r for r in financials if r.get("_end_date") == target]
    if not matches:
        return None
    return max(matches, key=lambda r: r.get("_ann_date") or date.min)


def _growth_raw(financials: list[dict]) -> tuple[Optional[float], dict]:
    latest = _latest_statement(financials)
    if latest is None:
        return None, {"growth_basis": "missing"}
    prior = _same_period_prior(financials, latest)
    if prior is None:
        return None, {"growth_basis": "missing_same_period_prior"}

    rev_now = _first_number(latest, REVENUE_ALIASES)
    rev_prev = _first_number(prior, REVENUE_ALIASES)
    ni_now = _first_number(latest, NET_INCOME_PARENT_ALIASES)
    ni_prev = _first_number(prior, NET_INCOME_PARENT_ALIASES)
    rev_growth = _safe_div(rev_now - rev_prev, rev_prev) if rev_now is not None and rev_prev not in (None, 0) else None
    ni_growth = _safe_div(ni_now - ni_prev, ni_prev) if ni_now is not None and ni_prev not in (None, 0) else None
    growth = _avg([rev_growth, ni_growth])
    return growth, {
        "growth_basis": "same_period_yoy" if growth is not None else "missing",
        "growth_end_date": latest["_end_date"].isoformat() if latest.get("_end_date") else None,
        "growth_prior_end_date": prior["_end_date"].isoformat() if prior.get("_end_date") else None,
        "revenue_growth_yoy": rev_growth,
        "net_income_growth_yoy": ni_growth,
    }


def _ensure_daily_basic_slot(store: PitDataStore):
    if not hasattr(store, "_pit_daily_basic"):
        store._pit_daily_basic = {}


def attach_daily_basic(store: PitDataStore, ticker: str, rows: list[dict]) -> None:
    """Attach daily_basic rows to a PitDataStore with as-of date sorting."""
    _ensure_daily_basic_slot(store)
    pts = []
    for row in rows or []:
        d = _to_date(row.get("trade_date"))
        if d is None:
            continue
        rr = dict(row)
        rr["_trade_date"] = d
        pts.append(rr)
    pts.sort(key=lambda r: r["_trade_date"])
    store._pit_daily_basic[ticker] = pts


def _daily_basic_asof(store: PitDataStore, ticker: str, as_of: date) -> Optional[dict]:
    if hasattr(store, "daily_basic_asof"):
        return store.daily_basic_asof(ticker, as_of)
    rows = getattr(store, "_pit_daily_basic", {}).get(ticker) or []
    dates = [r["_trade_date"] for r in rows]
    idx = bisect_right(dates, as_of) - 1
    if idx < 0:
        return None
    return rows[idx]


def _market_cap_asof(store: PitDataStore, ticker: str, as_of: date, config: dict) -> tuple[Optional[float], dict]:
    row = _daily_basic_asof(store, ticker, as_of)
    if not row:
        return None, {"daily_basic_date": None, "market_cap_basis": "missing_daily_basic"}
    raw = _first_number(row, MARKET_CAP_ALIASES)
    if raw is None or raw <= 0:
        return None, {"daily_basic_date": row["_trade_date"].isoformat(), "market_cap_basis": "missing_total_mv"}
    multiplier = _to_float(config.get("market_cap_multiplier")) or 1.0
    return raw * multiplier, {
        "daily_basic_date": row["_trade_date"].isoformat(),
        "market_cap_basis": "daily_basic.total_mv",
        "market_cap_multiplier": multiplier,
    }


def _trading_day_at_offset(store: PitDataStore, ticker: str, as_of: date, offset: int) -> Optional[date]:
    dates = store._px_dates.get(ticker) or []
    idx = bisect_right(dates, as_of) - 1 - offset
    if idx < 0 or idx >= len(dates):
        return None
    return dates[idx]


def _momentum_raw(store: PitDataStore, ticker: str, as_of: date, config: dict) -> tuple[Optional[float], dict]:
    skip_td = int(config.get("momentum_skip_td", CONFIG["momentum_skip_td"]))
    lookback_td = int(config.get("momentum_lookback_td", CONFIG["momentum_lookback_td"]))
    end_date = _trading_day_at_offset(store, ticker, as_of, skip_td)
    start_date = _trading_day_at_offset(store, ticker, as_of, lookback_td)
    if end_date is None or start_date is None or start_date >= end_date:
        return None, {"momentum_basis": "missing_price_window"}
    p0 = store.price_asof(ticker, start_date)
    p1 = store.price_asof(ticker, end_date)
    if p0 is None or p1 is None or p0 <= 0:
        return None, {"momentum_basis": "missing_price"}
    return p1 / p0 - 1.0, {
        "momentum_basis": "12_minus_1_trading_day_return",
        "momentum_start_date": start_date.isoformat(),
        "momentum_end_date": end_date.isoformat(),
        "momentum_skip_td": skip_td,
        "momentum_lookback_td": lookback_td,
    }


def _low_vol_raw(store: PitDataStore, ticker: str, as_of: date, config: dict) -> tuple[Optional[float], dict]:
    window = int(config.get("vol_window_td", CONFIG["vol_window_td"]))
    min_obs = int(config.get("min_vol_obs", CONFIG["min_vol_obs"]))
    dates = [d for d in (store._px_dates.get(ticker) or []) if d <= as_of]
    returns = []
    for d in dates[-window:]:
        r = store.daily_return(ticker, d)
        # Drop non-finite returns: a NaN/inf (from a blank/suspended bar)
        # crashes statistics.stdev with "'float' has no attribute 'numerator'".
        if r is not None and math.isfinite(r):
            returns.append(r)
    if len(returns) < max(2, min_obs):
        return None, {"low_vol_basis": "insufficient_returns", "return_obs": len(returns)}
    stdev = statistics.stdev(returns)
    return -1.0 * stdev, {
        "low_vol_basis": "negative_stdev_daily_returns",
        "vol_window_td": window,
        "return_obs": len(returns),
        "daily_return_stdev": stdev,
    }


def _value_quality_raw(
    store: PitDataStore,
    ticker: str,
    as_of: date,
    financials: list[dict],
    config: dict,
) -> tuple[Optional[float], Optional[float], dict, dict]:
    ttm, ttm_basis = _ttm_flows(financials)
    latest = _latest_statement(financials)
    basis = dict(ttm_basis)
    if latest and latest.get("_end_date"):
        basis["balance_end_date"] = latest["_end_date"].isoformat()
        basis["balance_ann_date"] = (latest.get("_ann_date") or date.min).isoformat()
    else:
        basis["balance_end_date"] = None
        basis["balance_ann_date"] = None

    market_cap, market_basis = _market_cap_asof(store, ticker, as_of, config)
    basis.update(market_basis)
    raw = {
        "market_cap": market_cap,
        "roe": None,
        "gross_margin": None,
        "net_margin": None,
        "leverage": None,
        "low_leverage": None,
        "earnings_yield": None,
        "book_yield": None,
    }
    if ttm is None or latest is None:
        return None, None, raw, basis

    revenue = ttm.get("revenue")
    oper_cost = ttm.get("oper_cost")
    net_income = ttm.get("n_income")
    parent_income = ttm.get("n_income_attr_p")
    equity = _first_number(latest, EQUITY_ALIASES)
    total_assets = _first_number(latest, TOTAL_ASSETS_ALIASES)
    total_liab = _first_number(latest, TOTAL_LIAB_ALIASES)

    raw["roe"] = _safe_div(parent_income, equity)
    raw["gross_margin"] = _safe_div(revenue - oper_cost, revenue) if revenue is not None and oper_cost is not None else None
    raw["net_margin"] = _safe_div(net_income, revenue)
    raw["leverage"] = _safe_div(total_liab, total_assets)
    raw["low_leverage"] = 1.0 - raw["leverage"] if raw["leverage"] is not None else None
    raw["earnings_yield"] = _safe_div(net_income, market_cap)
    raw["book_yield"] = _safe_div(equity, market_cap)

    quality = _avg([raw["roe"], raw["gross_margin"], raw["net_margin"], raw["low_leverage"]])
    # E/P-heavy value blend per Liu-Stambaugh-Yuan 2019. If either component is
    # None the blend gracefully degrades to whichever is available (matches the
    # previous _avg semantics).
    ep_w = _to_float(config.get("value_ep_weight")) or 0.5
    bp_w = _to_float(config.get("value_bp_weight")) or 0.5
    ep = raw["earnings_yield"]
    bp = raw["book_yield"]
    if ep is not None and bp is not None:
        value = ep_w * ep + bp_w * bp
    elif ep is not None:
        value = ep
    elif bp is not None:
        value = bp
    else:
        value = None
    return value, quality, raw, basis


def _score_factor(raw_by_ticker: dict[str, Optional[float]]) -> tuple[dict[str, Optional[float]], dict[str, str]]:
    valid = [(ticker, value) for ticker, value in raw_by_ticker.items() if value is not None]
    scores = {ticker: None for ticker in raw_by_ticker}
    flags = {
        ticker: "missing_raw_excluded_from_cross_section"
        for ticker, value in raw_by_ticker.items()
        if value is None
    }
    if not valid:
        return scores, flags
    if len(valid) == 1:
        scores[valid[0][0]] = 50.0
        flags[valid[0][0]] = "single_valid_observation_scored_neutral"
        return scores, flags

    ordered = sorted(valid, key=lambda item: (item[1], item[0]))
    n = len(ordered)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0
        score = avg_rank / (n - 1) * 100.0
        for k in range(i, j + 1):
            scores[ordered[k][0]] = score
            flags[ordered[k][0]] = "ranked"
        i = j + 1
    return scores, flags


def compute_factors(tickers, as_of_date, store: PitDataStore, config=None) -> dict:
    """Compute raw PIT factors plus 0-100 cross-sectional scores.

    Top-level factor fields are percentile scores. Raw factor values and
    components are under _raw. Missing data produces None, never fabricated 50s.
    """
    cfg = dict(CONFIG)
    if config:
        cfg.update(config)
    as_of = _to_date(as_of_date)
    if as_of is None:
        raise ValueError("as_of_date must be YYYYMMDD, YYYY-MM-DD, or date")

    tickers = list(tickers or [])
    raw_factors = {
        "momentum": {},
        "low_vol": {},
        "value": {},
        "quality": {},
        "growth": {},
    }
    output = {}

    for ticker in tickers:
        financials = _financials_asof(store, ticker, as_of)
        momentum, momentum_basis = _momentum_raw(store, ticker, as_of, cfg)
        low_vol, low_vol_basis = _low_vol_raw(store, ticker, as_of, cfg)
        value, quality, component_raw, fin_basis = _value_quality_raw(store, ticker, as_of, financials, cfg)
        growth, growth_basis = _growth_raw(financials)

        raw_factor_values = {
            "momentum": momentum,
            "low_vol": low_vol,
            "value": value,
            "quality": quality,
            "growth": growth,
        }
        for factor, value_raw in raw_factor_values.items():
            raw_factors[factor][ticker] = value_raw

        raw_components = dict(component_raw)
        raw_components.update(growth_basis)
        output[ticker] = {
            "momentum": None,
            "low_vol": None,
            "value": None,
            "quality": None,
            "growth": None,
            "_raw": {
                "factors": {k: _round_or_none(v) for k, v in raw_factor_values.items()},
                **{k: _round_or_none(raw_components.get(k)) for k in RAW_COMPONENT_KEYS},
            },
            "_basis": {
                "as_of": as_of.isoformat(),
                "score_method": "cross_sectional_percentile_rank_0_100",
                "missing_policy": "None; excluded from cross-sectional score, never defaulted to 50",
                **momentum_basis,
                **low_vol_basis,
                **fin_basis,
                **{k: v for k, v in growth_basis.items() if k.endswith("_basis") or k.endswith("_date")},
            },
            "_score_flags": {},
        }

    for factor, values in raw_factors.items():
        scores, flags = _score_factor(values)
        for ticker in tickers:
            output[ticker][factor] = _round_or_none(scores.get(ticker), 4)
            output[ticker]["_score_flags"][factor] = flags.get(ticker)

    return output


def _combine_history_financials(payload: dict) -> list[dict]:
    rows = []
    for table in ("income", "balancesheet", "cashflow"):
        for row in payload.get(table) or []:
            rr = dict(row)
            rr["_source_table"] = table
            rows.append(rr)
    return _merge_statement_rows(rows)


def load_store_from_data_history(tickers, data_history_dir=DATA_HISTORY) -> PitDataStore:
    """Load data_history/<ticker>.json into PitDataStore plus daily_basic."""
    store = PitDataStore()
    for ticker in tickers:
        path = Path(data_history_dir) / f"{ticker}.json"
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        financials = _combine_history_financials(payload)
        store.load_ticker(ticker, payload.get("daily") or [], financials)
        attach_daily_basic(store, ticker, payload.get("daily_basic") or [])
    return store


def _daily_rows(start: date, closes: list[float]) -> list[dict]:
    return [
        {"trade_date": (start + timedelta(days=i)).strftime("%Y%m%d"), "close": close}
        for i, close in enumerate(closes)
    ]


def _basic_rows(start: date, count: int, total_mv: float = 10000.0) -> list[dict]:
    return [
        {
            "trade_date": (start + timedelta(days=i)).strftime("%Y%m%d"),
            "total_mv": total_mv,
            "pb": 1.0,
            "pe": 10.0,
        }
        for i in range(count)
    ]


def _annual_fin(
    end_date: str,
    ann_date: str,
    revenue: float,
    oper_cost: float,
    n_income: float,
    equity: float,
    assets: float,
    liabilities: float,
) -> dict:
    return {
        "end_date": end_date,
        "ann_date": ann_date,
        "revenue": revenue,
        "oper_cost": oper_cost,
        "n_income": n_income,
        "n_income_attr_p": n_income,
        "total_hldr_eqy_exc_min_int": equity,
        "total_assets": assets,
        "total_liab": liabilities,
    }


def _build_selftest_store() -> tuple[PitDataStore, date, list[str]]:
    start = date(2021, 1, 1)
    count = 300
    as_of = start + timedelta(days=count - 1)
    store = PitDataStore()

    # Momentum fixture: price doubled from the lookback date to T-21, then
    # stayed flat in the skipped month. It must still score high.
    closes = []
    lookback_idx = count - 1 - CONFIG["momentum_lookback_td"]
    skip_idx = count - 1 - CONFIG["momentum_skip_td"]
    for i in range(count):
        if i <= lookback_idx:
            closes.append(10.0)
        elif i <= skip_idx:
            span = skip_idx - lookback_idx
            closes.append(10.0 + 10.0 * (i - lookback_idx) / span)
        else:
            closes.append(20.0)
    store.load_ticker("MOM.SZ", _daily_rows(start, closes), [])
    attach_daily_basic(store, "MOM.SZ", _basic_rows(start, count))

    flat = [10.0 for _ in range(count)]
    store.load_ticker("FLAT.SZ", _daily_rows(start, flat), [])
    attach_daily_basic(store, "FLAT.SZ", _basic_rows(start, count))

    # A last-month-only jump must not inflate 12-1 momentum.
    jump = [10.0 if i <= skip_idx else 20.0 for i in range(count)]
    store.load_ticker("JUMP.SZ", _daily_rows(start, jump), [])
    attach_daily_basic(store, "JUMP.SZ", _basic_rows(start, count))

    # Look-ahead fixture: a future-announced report is dramatically better. As
    # of T, quality must use only the older announced report.
    look_fin = [
        _annual_fin("20201231", "20210331", 100.0, 60.0, 20.0, 100.0, 200.0, 100.0),
        _annual_fin("20211231", "20220430", 100.0, 10.0, 80.0, 100.0, 120.0, 10.0),
    ]
    store.load_ticker("LOOK.SZ", _daily_rows(start, [10.0 + i * 0.01 for i in range(count)]), look_fin)
    attach_daily_basic(store, "LOOK.SZ", _basic_rows(start, count, total_mv=10000.0))

    high_fin = [_annual_fin("20201231", "20210331", 100.0, 50.0, 30.0, 100.0, 160.0, 40.0)]
    low_fin = [_annual_fin("20201231", "20210331", 100.0, 80.0, 5.0, 100.0, 200.0, 150.0)]
    store.load_ticker("HIGH.SZ", _daily_rows(start, [10.0 + i * 0.02 for i in range(count)]), high_fin)
    store.load_ticker("LOW.SZ", _daily_rows(start, [10.0 + i * 0.005 for i in range(count)]), low_fin)
    attach_daily_basic(store, "HIGH.SZ", _basic_rows(start, count, total_mv=10000.0))
    attach_daily_basic(store, "LOW.SZ", _basic_rows(start, count, total_mv=10000.0))

    store.load_ticker("MISS.SZ", _daily_rows(start, [8.0 for _ in range(count)]), [])
    attach_daily_basic(store, "MISS.SZ", _basic_rows(start, count, total_mv=10000.0))

    tickers = ["MOM.SZ", "FLAT.SZ", "JUMP.SZ", "LOOK.SZ", "HIGH.SZ", "LOW.SZ", "MISS.SZ"]
    return store, as_of, tickers


def _selftest() -> int:
    failures = []
    store, as_of, tickers = _build_selftest_store()
    factors = compute_factors(
        tickers,
        as_of,
        store,
        {"min_vol_obs": 2, "market_cap_multiplier": 1.0},
    )

    mom_raw = factors["MOM.SZ"]["_raw"]["factors"]["momentum"]
    flat_raw = factors["FLAT.SZ"]["_raw"]["factors"]["momentum"]
    jump_raw = factors["JUMP.SZ"]["_raw"]["factors"]["momentum"]
    if mom_raw is None or mom_raw < 0.95 or flat_raw != 0.0 or jump_raw != 0.0:
        failures.append(f"momentum 12-1 skip failed: MOM={mom_raw} FLAT={flat_raw} JUMP={jump_raw}")
    if factors["MOM.SZ"]["momentum"] <= factors["FLAT.SZ"]["momentum"]:
        failures.append("momentum cross-sectional score did not rank prior-year winner above flat stock")
    if factors["MOM.SZ"]["_basis"].get("momentum_skip_td") != 21:
        failures.append("momentum basis did not record 21 trading-day skip")

    look = factors["LOOK.SZ"]["_raw"]
    if abs((look.get("roe") or 0.0) - 0.20) > 1e-9:
        failures.append(f"PIT financial look-ahead: expected old ROE 0.20, saw {look.get('roe')}")
    if abs((look.get("gross_margin") or 0.0) - 0.40) > 1e-9:
        failures.append(f"PIT financial look-ahead: expected old gross margin 0.40, saw {look.get('gross_margin')}")
    if factors["LOOK.SZ"]["_basis"].get("income_end_date") != "2020-12-31":
        failures.append(f"PIT basis used future report: {factors['LOOK.SZ']['_basis'].get('income_end_date')}")

    high_q = factors["HIGH.SZ"]["quality"]
    low_q = factors["LOW.SZ"]["quality"]
    if high_q is None or low_q is None or high_q == low_q or high_q <= low_q:
        failures.append(f"quality scores are constant/wrong: HIGH={high_q} LOW={low_q}")

    if factors["MISS.SZ"]["quality"] is not None:
        failures.append(f"missing financials fabricated quality: {factors['MISS.SZ']['quality']}")
    if factors["MISS.SZ"]["_raw"]["factors"]["quality"] is not None:
        failures.append("missing financials fabricated raw quality")
    if factors["MISS.SZ"]["_score_flags"]["quality"] != "missing_raw_excluded_from_cross_section":
        failures.append(f"missing financial flag wrong: {factors['MISS.SZ']['_score_flags']['quality']}")

    if failures:
        print("SELFTEST FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("SELFTEST PASSED pit_factors")
    print("- momentum uses 12-1 skip")
    print("- financials announced after T are not used")
    print("- quality scores differ when ROE/margins/leverage differ")
    print("- missing financials return None, not 50")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="PIT factor exposure calculator.")
    parser.add_argument("--selftest", action="store_true", help="Run synthetic PIT correctness tests.")
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    print("pit_factors: import compute_factors(tickers, as_of, store, config).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
