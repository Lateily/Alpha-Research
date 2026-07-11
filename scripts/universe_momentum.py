#!/usr/bin/env python3
"""Real 12-1 month cross-sectional momentum for the A-share universe.

WHY THIS EXISTS
---------------
The production universe (``public/data/universe_a.json``) is built from a single
-day market snapshot, so the legacy ``momentum`` factor was
``percentile_rank(change_pct)`` — a **1-DAY tape rank**, not academic momentum.
A name that merely closed up on the snapshot day ranked high regardless of its
multi-month trend; a long uptrend that happened to close red ranked low. That
makes the factor close to useless as a trend signal (documented in
``scripts/universe_data_health.py`` and the universe-snapshot trap notes).

This module computes the **real** signal: cumulative HFQ-adjusted return from
``T-252`` to ``T-21`` trading days (skip the most recent ~1 month, measure the
prior ~12 months), matching the existing PIT implementation in
``scripts/pit_factors.py`` (``momentum_lookback_td=252``, ``momentum_skip_td=21``).

WHY IT IS LEAN (no 426MB panel, no committed file, no new workflow step)
-----------------------------------------------------------------------
12-1 momentum is a **two-point return**, and Tushare returns the whole market
for one trade date in a single call. So we need only a handful of by-date
``pro.daily`` + ``pro.adj_factor`` calls — NOT the 20-year backtest panel
(``data_history/panel/daily_prices.parquet`` is gitignored / local-only and is
absent in the GitHub Actions runner).

HFQ-adjusted close = ``close * adj_factor``. Across two dates the ratio cancels
the latest-factor normalisation, so the raw product is sufficient for a return:
``mom = (close_end * adjf_end) / (close_start * adjf_start) - 1``.

HONEST DEGRADATION
------------------
- No token / tushare import / API error  -> ``({}, basis='unavailable')`` and the
  caller falls back to the 1-day tape with an **explicit** label, never silently.
- ``adj_factor`` endpoint unavailable but ``daily`` works -> proceeds unadjusted
  with basis ``12_minus_1_unadjusted`` (still vastly better than a 1-day tape,
  and labelled so the data-health gate can see it).
- A name suspended on the exact anchor date is retried across a small window of
  nearby trade dates; if still missing it is simply absent from the result and
  is neutral-filled downstream (NOT penalised with a bottom rank).

VALIDATION
----------
The 252/21 window and the HFQ-ratio formula are standard and
``[validated against the existing pit_factors.py implementation]``. The
fallback-window width (``+2`` trade dates) is an ``[unvalidated intuition]``
operational prior for suspended-name coverage; runtime per the daily cron is an
``[unvalidated intuition]`` until measured in Actions.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")

# Window definition — kept identical to scripts/pit_factors.py CONFIG.
LOOKBACK_TD = 252   # start anchor: 252 trading days before as_of (~12 months)
SKIP_TD = 21        # end anchor: 21 trading days before as_of (~1 month skip)
FALLBACK_WINDOW = 2  # try this many older trade dates if a name is missing at the anchor


# ──────────────────────────────────────────────────────────────────────────────
# Pure computation (no network — fully unit-testable)
# ──────────────────────────────────────────────────────────────────────────────
def momentum_from_maps(start_map, end_map, ts_codes=None):
    """Compute 12-1 momentum per ticker from two {ts_code: adj_close} maps.

    ``mom = end_adj / start_adj - 1``. A ticker is included only when it has a
    positive adjusted close in BOTH maps (missing -> absent, neutral-filled by
    the caller, never a bottom rank). Returns ``{ts_code: float}``.
    """
    if ts_codes is None:
        ts_codes = set(start_map) & set(end_map)
    out = {}
    for ts in ts_codes:
        a = start_map.get(ts)
        b = end_map.get(ts)
        if a is None or b is None:
            continue
        try:
            a = float(a)
            b = float(b)
        except (TypeError, ValueError):
            continue
        if a <= 0 or b <= 0:
            continue
        out[ts] = b / a - 1.0
    return out


def _merge_prefer_anchor(date_maps):
    """Collapse an ordered list of {ts: adj_close} maps (anchor first) into one,
    preferring the earliest (closest-to-anchor) map that has a value per ticker."""
    merged = {}
    for m in date_maps:
        for ts, v in m.items():
            if ts not in merged and v is not None:
                merged[ts] = v
    return merged


# ──────────────────────────────────────────────────────────────────────────────
# Network fetch (Tushare by trade date — whole market per call)
# ──────────────────────────────────────────────────────────────────────────────
def _make_pro(token=None):
    token = token or TUSHARE_TOKEN
    if not token:
        return None, "no_token"
    try:
        import tushare as ts
    except ImportError:
        return None, "tushare_not_installed"
    try:
        ts.set_token(token)
        return ts.pro_api(), None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def _open_trade_dates_desc(pro, as_of=None, calendar_days=420):
    """Return open A-share trade dates (YYYYMMDD), newest first, up to as_of."""
    end = (as_of or datetime.now()).strftime("%Y%m%d")
    start = ((as_of or datetime.now()) - timedelta(days=calendar_days)).strftime("%Y%m%d")
    cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end, is_open=1)
    if cal is None or cal.empty:
        return []
    dates = sorted((str(d) for d in cal["cal_date"].tolist()), reverse=True)
    return [d for d in dates if d <= end]


def _adj_close_map(pro, trade_date):
    """{ts_code: close * adj_factor} for one trade date. adj_factor degrades to
    1.0 (unadjusted) if that endpoint is unavailable; returns (map, adjusted?)."""
    daily = pro.daily(trade_date=trade_date, fields="ts_code,close")
    if daily is None or daily.empty:
        return {}, True
    close = {str(r["ts_code"]): r["close"] for _, r in daily.iterrows()
             if r.get("close") is not None}
    adjusted = True
    try:
        adj = pro.adj_factor(trade_date=trade_date, fields="ts_code,adj_factor")
        adjf = {str(r["ts_code"]): r["adj_factor"] for _, r in adj.iterrows()} \
            if adj is not None and not adj.empty else {}
        if not adjf:
            adjusted = False
    except Exception:  # noqa: BLE001
        adjf, adjusted = {}, False
    out = {}
    for ts, c in close.items():
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        f = adjf.get(ts)
        try:
            f = float(f) if f is not None else 1.0
        except (TypeError, ValueError):
            f = 1.0
        out[ts] = c * f
    return out, adjusted


def _anchor_adj_map(pro, dates_desc, anchor_idx, fallback_window):
    """Adjusted-close map for an anchor index, retrying nearby (older) trade
    dates for names missing at the anchor. Returns (map, chosen_anchor_date)."""
    idxs = [anchor_idx + k for k in range(fallback_window + 1) if anchor_idx + k < len(dates_desc)]
    maps = []
    chosen = dates_desc[anchor_idx] if anchor_idx < len(dates_desc) else None
    adjusted_all = True
    for j in idxs:
        m, adjusted = _adj_close_map(pro, dates_desc[j])
        adjusted_all = adjusted_all and adjusted
        maps.append(m)
    return _merge_prefer_anchor(maps), chosen, adjusted_all


def compute_universe_momentum(ts_codes=None, pro=None, token=None, as_of=None,
                              lookback_td=LOOKBACK_TD, skip_td=SKIP_TD,
                              fallback_window=FALLBACK_WINDOW):
    """Compute real 12-1 momentum for a universe. Returns (mom_dict, meta).

    meta always carries a ``basis`` describing exactly what was produced so the
    caller and the data-health gate can label the universe honestly.
    """
    meta = {
        "basis": "unavailable", "lookback_td": lookback_td, "skip_td": skip_td,
        "as_of": (as_of or datetime.now()).strftime("%Y%m%d"),
        "start_date": None, "end_date": None, "coverage": 0,
        "n_requested": (len(ts_codes) if ts_codes else None), "adjusted": None,
    }
    if pro is None:
        pro, err = _make_pro(token)
        if pro is None:
            meta["error"] = err
            return {}, meta
    try:
        dates = _open_trade_dates_desc(pro, as_of=as_of)
        if len(dates) <= lookback_td:
            meta["error"] = f"insufficient_trade_dates({len(dates)}<= {lookback_td})"
            return {}, meta
        end_map, end_date, adj_e = _anchor_adj_map(pro, dates, skip_td, fallback_window)
        start_map, start_date, adj_s = _anchor_adj_map(pro, dates, lookback_td, fallback_window)
        mom = momentum_from_maps(start_map, end_map, set(ts_codes) if ts_codes else None)
        adjusted = bool(adj_e and adj_s)
        meta.update({
            "basis": "12_minus_1_trading_day_return" if adjusted else "12_minus_1_unadjusted",
            "start_date": start_date, "end_date": end_date,
            "coverage": len(mom), "adjusted": adjusted,
        })
        return mom, meta
    except Exception as e:  # noqa: BLE001
        meta["error"] = f"{type(e).__name__}: {e}"
        return {}, meta


def enrich_stocks_with_momentum(stocks, ticker_key="ticker", pro=None, token=None,
                                as_of=None):
    """Attach ``momentum_12_1`` to each stock dict (by ts_code). Returns meta.

    Stocks without a computed value are left without the field (score_universe
    neutral-fills them). Safe to call unconditionally; on any failure it returns
    meta.basis == its failure state and attaches nothing (caller logs + falls
    back to the 1-day tape)."""
    ts_codes = [s.get(ticker_key) for s in stocks if s.get(ticker_key)]
    mom, meta = compute_universe_momentum(ts_codes=ts_codes, pro=pro, token=token,
                                          as_of=as_of)
    if mom:
        for s in stocks:
            v = mom.get(s.get(ticker_key))
            if v is not None:
                s["momentum_12_1"] = round(float(v), 6)
    return meta


# ──────────────────────────────────────────────────────────────────────────────
# Selftest (no network)
# ──────────────────────────────────────────────────────────────────────────────
def _selftest():
    ok = True

    def check(cond, msg):
        nonlocal ok
        status = "✓" if cond else "✗ FAIL"
        if not cond:
            ok = False
        print(f"  {status} {msg}")

    # 1. Pure momentum math: end/start - 1.
    start = {"A.SH": 10.0, "B.SZ": 20.0, "C.SH": 5.0, "D.SZ": 8.0}
    end = {"A.SH": 13.0, "B.SZ": 18.0, "C.SH": 5.0}  # D missing at end
    mom = momentum_from_maps(start, end)
    check(abs(mom["A.SH"] - 0.30) < 1e-9, f"A.SH +30% momentum (got {mom.get('A.SH')})")
    check(abs(mom["B.SZ"] - (-0.10)) < 1e-9, f"B.SZ -10% momentum (got {mom.get('B.SZ')})")
    check(abs(mom["C.SH"] - 0.0) < 1e-9, "C.SH flat = 0.0 momentum")
    check("D.SZ" not in mom, "D.SZ missing at end -> absent (neutral-filled downstream, not bottom)")

    # 2. Non-positive / non-numeric prices are dropped, not crashed.
    s2 = {"X.SH": 0.0, "Y.SZ": -3.0, "Z.SH": "n/a", "W.SH": 10.0}
    e2 = {"X.SH": 5.0, "Y.SZ": 5.0, "Z.SH": 5.0, "W.SH": 12.0}
    mom2 = momentum_from_maps(s2, e2)
    check(set(mom2) == {"W.SH"}, f"non-positive/non-numeric dropped -> only W.SH (got {set(mom2)})")
    check(abs(mom2["W.SH"] - 0.20) < 1e-9, "W.SH +20%")

    # 3. _merge_prefer_anchor prefers the earliest (anchor) map per ticker.
    merged = _merge_prefer_anchor([{"A.SH": 1.0}, {"A.SH": 9.9, "B.SZ": 2.0}, {"B.SZ": 9.9}])
    check(merged == {"A.SH": 1.0, "B.SZ": 2.0}, f"anchor preferred over fallback dates (got {merged})")

    # 4. No-token path is graceful + honestly labelled (no network).
    mom4, meta4 = compute_universe_momentum(ts_codes=["A.SH"], token="")
    check(mom4 == {} and meta4["basis"] == "unavailable",
          f"no token -> empty + basis=unavailable (got basis={meta4['basis']})")
    check(meta4.get("error") in ("no_token",) or "error" in meta4,
          "no-token path records an error reason")

    # 5. enrich attaches nothing when unavailable, returns failure meta (no crash).
    stocks = [{"ticker": "A.SH"}, {"ticker": "B.SZ"}]
    meta5 = enrich_stocks_with_momentum(stocks, token="")
    check(all("momentum_12_1" not in s for s in stocks),
          "enrich attaches nothing when unavailable (caller falls back to 1-day tape)")
    check(meta5["basis"] == "unavailable", "enrich returns basis=unavailable on failure")

    # 6. End-to-end orchestration with a mock Tushare — verifies the skip=21 /
    #    lookback=252 trade-date indexing and the adjusted ratio, without a token.
    try:
        import pandas as pd
        from datetime import date as _date, timedelta as _td, datetime as _dt
        as_of = _date(2026, 6, 19)
        dates = [(as_of - _td(days=k)).strftime("%Y%m%d") for k in range(300)]
        end_anchor, start_anchor = dates[SKIP_TD], dates[LOOKBACK_TD]

        class _MockPro:
            def trade_cal(self, exchange, start_date, end_date, is_open):
                ds = [d for d in dates if start_date <= d <= end_date]
                return pd.DataFrame({"cal_date": ds})

            def daily(self, trade_date, fields):
                if trade_date == end_anchor:
                    px = {"A.SH": 110.0, "B.SZ": 90.0}   # A +10%, B -10% over window
                elif trade_date == start_anchor:
                    px = {"A.SH": 100.0, "B.SZ": 100.0}
                else:
                    px = {"A.SH": 105.0, "B.SZ": 95.0}   # fallback dates (ignored)
                return pd.DataFrame({"ts_code": list(px), "close": list(px.values())})

            def adj_factor(self, trade_date, fields):
                return pd.DataFrame({"ts_code": ["A.SH", "B.SZ"], "adj_factor": [1.0, 1.0]})

        mom6, meta6 = compute_universe_momentum(
            ts_codes=["A.SH", "B.SZ"], pro=_MockPro(), as_of=_dt(2026, 6, 19))
        check(abs(mom6.get("A.SH", 0) - 0.10) < 1e-9,
              f"mock: A.SH 12-1 = +10% via skip{SKIP_TD}/lookback{LOOKBACK_TD} (got {mom6.get('A.SH')})")
        check(abs(mom6.get("B.SZ", 0) + 0.10) < 1e-9,
              f"mock: B.SZ 12-1 = -10% (got {mom6.get('B.SZ')})")
        check(meta6["basis"] == "12_minus_1_trading_day_return" and meta6["adjusted"],
              "mock: basis=12_minus_1 + adjusted=True")
        check(meta6["end_date"] == end_anchor and meta6["start_date"] == start_anchor,
              f"mock: anchors end={meta6['end_date']} start={meta6['start_date']}")
    except ImportError:
        print("  (skipped mock-pro orchestration test: pandas unavailable)")

    print("\n  RESULT:", "PASS ✓" if ok else "FAIL ✗")
    return ok


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if _selftest() else 1)
    # Live smoke (requires TUSHARE_TOKEN): print universe momentum coverage.
    mom, meta = compute_universe_momentum()
    print("meta:", meta)
    if mom:
        sample = list(mom.items())[:5]
        print("sample:", sample)
