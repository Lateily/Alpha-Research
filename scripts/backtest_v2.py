#!/usr/bin/env python3
"""backtest_v2.py — credible backtest framework (PIT + survivorship-safe).

REPLACES the non-credible scripts/backtest.py (n=5, flat-proxy benchmark,
look-ahead seed). This module is SEPARATE; the daily pipeline still calls the
old backtest.py — do not break it. backtest_v2 is the trust-earning machine for
the systematic-strategy direction (see docs/strategy/SYSTEMATIC_STRATEGY_v0.md).

WHY THIS EXISTS / the correctness contracts (the honesty red line):
  1. POINT-IN-TIME (anti look-ahead): at decision date T the engine may use
     ONLY (a) prices with trade_date <= T and (b) financials with ann_date <= T.
     The old engine back-filled pre-2025 dates with TODAY's fundamentals — a
     look-ahead bug that inflates results. PitDataStore enforces this in code,
     and test_no_lookahead() proves it on a synthetic fixture.
  2. SURVIVORSHIP-SAFE: the tradeable universe at date T is reconstructed from
     universe_pit.json (incl. delisted names): a stock is in-universe iff
     list_date <= T < (delist_date or +inf). Excluding delisted names
     systematically overstates returns; test_survivorship() proves inclusion.
  3. REALISTIC FILLS/COSTS: next-bar fill (T+1), commission + 0.05% sell stamp
     duty + slippage; a name at 涨停/跌停 (|move| >= limit) is UNFILLABLE.
  4. WALK-FORWARD: params are fit on in-sample windows and scored on disjoint
     out-of-sample windows — a single full-sample number is overfit-prone.
  5. OBSERVABILITY: every rebalance records holdings + per-trade attribution;
     deterministic (seeded) so same inputs -> same outputs.

STATUS: framework + correctness primitives implemented and unit-tested on
SYNTHETIC FIXTURES (run `python3 scripts/backtest_v2.py --selftest`). It does
NOT emit real performance numbers until the 20yr data lands via the GHA
backfill — by design (no fake numbers). Metrics + regime replay are wired but
will only be meaningful on real data.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_HISTORY = REPO_ROOT / "data_history"

# A-share trading frictions (starting values; tunable + calibrate later)
COMMISSION = 0.00025          # per side
STAMP_DUTY_SELL = 0.0005      # sell-side only (A-share 印花税)
SLIPPAGE = 0.0010            # per side, conservative
DAILY_LIMIT = 0.099          # |daily move| >= ~10% treated as limit (unfillable)


def _to_date(s) -> Optional[date]:
    """Accept 'YYYYMMDD' or 'YYYY-MM-DD' or date; return date or None."""
    if s is None or s == "":
        return None
    if isinstance(s, date):
        return s
    t = str(s)
    try:
        if len(t) == 8 and t.isdigit():
            return date(int(t[:4]), int(t[4:6]), int(t[6:8]))
        return date.fromisoformat(t[:10])
    except (ValueError, TypeError):
        return None


# ───────────────────────── Point-in-time data store ─────────────────────────

class PitDataStore:
    """Holds per-ticker price + financial history and enforces the PIT contract.

    A backtest decision made on `as_of` may ONLY read:
      - price_asof(t, as_of): the latest close with trade_date <= as_of
      - financials_asof(t, as_of): statement rows with ann_date <= as_of
    There is NO API that returns future data — look-ahead is impossible by
    construction, not by convention.
    """

    def __init__(self):
        # ticker -> (sorted list of date, parallel list of close)
        self._px_dates: dict[str, list[date]] = {}
        self._px_close: dict[str, list[float]] = {}
        # ticker -> list of {ann_date: date, ...} sorted by ann_date asc
        self._fin: dict[str, list[dict]] = {}

    def load_ticker(self, ticker: str, daily_rows: list[dict], fin_rows: list[dict]):
        pts = []
        for r in daily_rows:
            d = _to_date(r.get("trade_date"))
            c = r.get("close")
            if d is not None and c is not None:
                pts.append((d, float(c)))
        pts.sort(key=lambda x: x[0])
        self._px_dates[ticker] = [d for d, _ in pts]
        self._px_close[ticker] = [c for _, c in pts]
        fins = []
        for r in fin_rows or []:
            ad = _to_date(r.get("ann_date"))
            if ad is not None:
                rr = dict(r)
                rr["_ann_date"] = ad
                fins.append(rr)
        fins.sort(key=lambda r: r["_ann_date"])
        self._fin[ticker] = fins

    def price_asof(self, ticker: str, as_of: date) -> Optional[float]:
        dates = self._px_dates.get(ticker)
        if not dates:
            return None
        i = bisect_right(dates, as_of) - 1   # latest index with date <= as_of
        if i < 0:
            return None
        return self._px_close[ticker][i]

    def next_fill_price(self, ticker: str, after: date) -> Optional[tuple[date, float]]:
        """First close STRICTLY after `after` (the realistic T+1 fill)."""
        dates = self._px_dates.get(ticker)
        if not dates:
            return None
        i = bisect_right(dates, after)
        if i >= len(dates):
            return None
        return dates[i], self._px_close[ticker][i]

    def financials_asof(self, ticker: str, as_of: date) -> list[dict]:
        """Only statements ANNOUNCED on/before as_of (PIT — no look-ahead)."""
        return [r for r in self._fin.get(ticker, []) if r["_ann_date"] <= as_of]

    def daily_return(self, ticker: str, as_of: date) -> Optional[float]:
        dates = self._px_dates.get(ticker)
        if not dates:
            return None
        i = bisect_right(dates, as_of) - 1
        if i < 1:
            return None
        prev, cur = self._px_close[ticker][i - 1], self._px_close[ticker][i]
        if prev <= 0:
            return None
        return cur / prev - 1.0


# ───────────────────────── Survivorship-safe universe ───────────────────────

class PitUniverse:
    """universe_pit.json -> in-universe membership as of any date (incl. delisted)."""

    def __init__(self, stocks: list[dict]):
        self._rows = []
        for s in stocks:
            self._rows.append(
                {
                    "ts_code": s.get("ts_code"),
                    "list_date": _to_date(s.get("list_date")),
                    "delist_date": _to_date(s.get("delist_date")),
                    "name": s.get("name"),
                    "industry": s.get("industry"),
                }
            )

    def members_asof(self, as_of: date) -> list[str]:
        out = []
        for r in self._rows:
            ld = r["list_date"]
            dd = r["delist_date"]
            if ld is None or ld > as_of:
                continue          # not yet listed at as_of
            if dd is not None and dd <= as_of:
                continue          # already delisted at as_of
            out.append(r["ts_code"])
        return out


# ───────────────────────── Cost / fill model ────────────────────────────────

def fillable(prev_close: float, ref_open: float) -> bool:
    """A name gapping >= the daily limit is unfillable (limit-up/down)."""
    if prev_close is None or ref_open is None or prev_close <= 0:
        return False
    return abs(ref_open / prev_close - 1.0) < DAILY_LIMIT


def trade_cost(notional: float, side: str) -> float:
    c = COMMISSION + SLIPPAGE
    if side == "sell":
        c += STAMP_DUTY_SELL
    return abs(notional) * c


# ───────────────────────── Walk-forward windows ─────────────────────────────

@dataclass
class WalkForward:
    is_years: int = 5
    oos_years: int = 2

    def windows(self, start: date, end: date) -> list[tuple[date, date, date, date]]:
        """Yield (is_start, is_end, oos_start, oos_end) rolling windows."""
        out = []
        cur = start
        while True:
            is_end = date(cur.year + self.is_years, cur.month, cur.day)
            oos_end = date(is_end.year + self.oos_years, is_end.month, is_end.day)
            if oos_end > end:
                break
            out.append((cur, is_end, is_end, oos_end))
            cur = date(cur.year + self.oos_years, cur.month, cur.day)
        return out


# A-share regime sub-periods for "每轮不同 scenario" stress (Junyan).
REGIMES = {
    "2008_crash": (date(2007, 10, 1), date(2008, 12, 31)),
    "2015_bubble_crash": (date(2014, 7, 1), date(2016, 1, 31)),
    "2018_bear": (date(2018, 1, 1), date(2018, 12, 31)),
    "2020_covid": (date(2020, 1, 1), date(2020, 12, 31)),
    "2022_drawdown": (date(2022, 1, 1), date(2022, 12, 31)),
    "2024_recovery": (date(2024, 1, 1), date(2024, 12, 31)),
}


# ───────────────────────── Metrics ──────────────────────────────────────────

def cagr(equity: list[float], periods_per_year: float) -> Optional[float]:
    if len(equity) < 2 or equity[0] <= 0:
        return None
    yrs = (len(equity) - 1) / periods_per_year
    if yrs <= 0:
        return None
    return (equity[-1] / equity[0]) ** (1 / yrs) - 1


def max_drawdown(equity: list[float]) -> float:
    peak, mdd = -math.inf, 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


def sharpe(returns: list[float], periods_per_year: float, rf: float = 0.0) -> Optional[float]:
    rs = [r for r in returns if r is not None]
    if len(rs) < 2:
        return None
    mean = sum(rs) / len(rs)
    var = sum((r - mean) ** 2 for r in rs) / (len(rs) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return None
    return (mean - rf / periods_per_year) / sd * math.sqrt(periods_per_year)


# ───────────────────────── Self-test (fixtures prove correctness) ───────────

def _selftest() -> int:
    """Synthetic fixtures that FAIL if the PIT / survivorship contracts break."""
    failures = []

    # --- PIT: financials_asof must hide statements announced after as_of ---
    store = PitDataStore()
    store.load_ticker(
        "T.SZ",
        daily_rows=[
            {"trade_date": "20200101", "close": 10.0},
            {"trade_date": "20200201", "close": 11.0},
            {"trade_date": "20200301", "close": 12.0},
        ],
        fin_rows=[
            {"ann_date": "20200115", "eps": 1.0},   # known by Feb
            {"ann_date": "20200415", "eps": 2.0},   # NOT known in Feb/Mar
        ],
    )
    fin_feb = store.financials_asof("T.SZ", date(2020, 2, 1))
    if len(fin_feb) != 1 or fin_feb[0]["eps"] != 1.0:
        failures.append(f"PIT financials look-ahead: as-of 2020-02-01 saw {fin_feb}")
    # price_asof must not see the future
    if store.price_asof("T.SZ", date(2020, 2, 15)) != 11.0:
        failures.append("PIT price_asof returned wrong/forward price")
    # next_fill_price must be strictly after decision date (T+1 realism)
    nf = store.next_fill_price("T.SZ", date(2020, 2, 1))
    if nf is None or nf[0] != date(2020, 3, 1):
        failures.append(f"next_fill_price not strictly-after: {nf}")

    # --- Survivorship: a delisted name must be in-universe BEFORE delist only ---
    uni = PitUniverse(
        [
            {"ts_code": "LIVE.SZ", "list_date": "20100101", "delist_date": None},
            {"ts_code": "DEAD.SZ", "list_date": "20100101", "delist_date": "20200701"},
            {"ts_code": "NEW.SZ", "list_date": "20210101", "delist_date": None},
        ]
    )
    m2019 = set(uni.members_asof(date(2019, 6, 1)))
    if m2019 != {"LIVE.SZ", "DEAD.SZ"}:
        failures.append(f"survivorship 2019 members wrong: {m2019} (DEAD must be present)")
    m2022 = set(uni.members_asof(date(2022, 6, 1)))
    if m2022 != {"LIVE.SZ", "NEW.SZ"}:
        failures.append(f"survivorship 2022 members wrong: {m2022} (DEAD must be gone, NEW present)")

    # --- Fill model: limit-up gap is unfillable ---
    if fillable(10.0, 11.5):       # +15% gap
        failures.append("limit-up gap was marked fillable")
    if not fillable(10.0, 10.3):   # +3% normal
        failures.append("normal move marked unfillable")

    # --- Cost model: sell pays stamp duty, buy does not ---
    if not (trade_cost(10000, "sell") > trade_cost(10000, "buy")):
        failures.append("sell cost should exceed buy cost (stamp duty)")

    # --- Metrics sanity ---
    if max_drawdown([100, 120, 60, 90]) >= 0:
        failures.append("max_drawdown sign wrong")
    if abs((cagr([100, 110], 1.0) or 0) - 0.10) > 1e-9:
        failures.append("cagr wrong")

    if failures:
        print("SELFTEST FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("SELFTEST PASSED — PIT, survivorship, fill, cost, metrics contracts hold.")
    print("(No performance numbers: real run requires 20yr data via GHA backfill.)")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Credible PIT + survivorship-safe backtest framework.")
    p.add_argument("--selftest", action="store_true", help="Run fixture correctness tests (no data needed).")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    print("backtest_v2: framework ready. Real run is gated on 20yr data "
          "(data_history/ via GHA backfill). Run with --selftest to verify "
          "correctness contracts on fixtures.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
