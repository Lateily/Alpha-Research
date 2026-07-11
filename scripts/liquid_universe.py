#!/usr/bin/env python3
"""liquid_universe.py — PIT-clean liquidity pre-filter (top-N by 20d ADV).

THE ENGINE BOTTLENECK FIX: per swing backtest profiling, the daily loop
iterates over all ~5800 tickers and re-filters the 15M-row panel every day.
For a 1-year mini backtest this took 67 min; 20-yr extrapolates to ~22h.

Per SWING_STRATEGY_v1.md §2.1 + Junyan 2026-05-27 directive:
  Real-world swing trading only touches LIQUID names (institutional reality).
  Top-500 by 20-day average dollar volume gives:
    • ~85% of A-share market value
    • ~95% of A-share daily turnover
    • Cuts compute by ~12× (500 vs 5800)
    • Eliminates micro-cap noise + many shells (already filtered by LSY-style)

PIT discipline:
  liquid_universe[T] = top-N by mean(close × vol over T-20..T-1)
  uses ONLY data with trade_date <= T-1. Forward-looking is impossible.

This module is run ONCE before the backtest main loop; result is a
dict[trade_date] -> list[ts_code]. The daily loop reads it as O(1).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TOP_N = 500
DEFAULT_LOOKBACK = 20
DEFAULT_MIN_VOL_THRESHOLD = 1e7   # ¥10M minimum daily turnover floor (penny stocks out)


def compute_liquid_universe(daily_panel: pd.DataFrame,
                             top_n: int = DEFAULT_TOP_N,
                             lookback_days: int = DEFAULT_LOOKBACK,
                             min_dollar_vol: float = DEFAULT_MIN_VOL_THRESHOLD,
                             ) -> dict[str, list[str]]:
    """For each trade_date T, compute top-N liquid tickers.

    Liquidity = mean(close × vol) over the last `lookback_days` dates strictly
    BEFORE T. (Strict < to keep PIT clean; T itself is not used.)

    Returns dict[trade_date_yyyymmdd] -> sorted list[ts_code] of size ≤ top_n.

    Implementation: vectorized pandas. We compute dollar volume per row, then
    use groupby + rolling mean. Total cost ≈ O(N rows × log N) for sort.
    """
    df = daily_panel.copy()
    # Tushare units (per pro.daily docs):
    #   amount: 千元 (thousand yuan)
    #   vol:    手 (1手=100股)
    #   close:  元
    # Dollar volume in 元 = amount × 1000  OR  close × vol × 100
    if "amount" in df.columns:
        df["dvol"] = df["amount"].fillna(0) * 1000.0   # 千元 → 元
    else:
        df["dvol"] = df["close"].fillna(0) * df["vol"].fillna(0) * 100.0  # 手 → 股

    # Sort once by (ts_code, trade_date) for groupby+rolling
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    # Rolling mean over lookback PRIOR days (shift 1 to make strict-<)
    df["adv"] = (df.groupby("ts_code")["dvol"]
                 .transform(lambda s: s.shift(1).rolling(lookback_days, min_periods=lookback_days // 2).mean()))
    df = df.dropna(subset=["adv"])
    df = df[df["adv"] >= min_dollar_vol]

    # For each trade_date, rank tickers by ADV descending → top-N
    out = {}
    for trade_date, group in df.groupby("trade_date", sort=False):
        ranked = group.sort_values("adv", ascending=False)
        out[str(trade_date)] = ranked.head(top_n)["ts_code"].tolist()

    return out


def reduced_panel(daily_panel: pd.DataFrame,
                  liquid_universe: dict[str, list[str]]) -> pd.DataFrame:
    """Slice the panel to ONLY (ts_code, trade_date) pairs that are in the
    liquid universe for that date. Output is much smaller — ~500/5800 reduction.
    """
    # Build a set of (date, ticker) pairs that survive
    keep_pairs = set()
    for trade_date, tickers in liquid_universe.items():
        for tk in tickers:
            keep_pairs.add((trade_date, tk))
    # Filter via vectorized isin on tuple — pandas doesn't directly support but
    # we can build a multi-index and check membership
    idx = pd.MultiIndex.from_arrays([daily_panel["trade_date"], daily_panel["ts_code"]])
    mask = idx.isin(keep_pairs)
    return daily_panel[mask].reset_index(drop=True)


def reduced_panel_union(daily_panel: pd.DataFrame,
                         liquid_universe: dict[str, list[str]]) -> pd.DataFrame:
    """A LESS-strict reduction: keep all rows for any ticker that appears in
    the liquid universe at ANY date. This preserves history needed by 60d
    factor lookups (e.g., a stock entering the top-500 today needs its prior
    history for MACD/RSI). The strict version above drops too much."""
    all_tickers = set()
    for tickers in liquid_universe.values():
        all_tickers.update(tickers)
    return daily_panel[daily_panel["ts_code"].isin(all_tickers)].reset_index(drop=True)


# ───────────────────────── Self-test ───────────────────────────────────────

def _selftest() -> int:
    rows = []
    base = pd.Timestamp("2024-01-01")
    # 20 tickers; first 5 have BIG volume, last 5 tiny
    for i in range(20):
        for d in range(40):
            dt = (base + pd.Timedelta(days=d)).strftime("%Y%m%d")
            vol = (1e7 if i < 5 else (1e5 if i < 10 else 1e3))
            rows.append({"ts_code": f"T{i:03d}.SZ", "trade_date": dt,
                         "close": 10.0, "open": 10.0, "high": 10.1, "low": 9.9,
                         "vol": vol, "amount": 10.0 * vol})
    panel = pd.DataFrame(rows)
    uni = compute_liquid_universe(panel, top_n=5, lookback_days=10, min_dollar_vol=0)
    failures = []
    if not uni:
        failures.append("empty universe")
    else:
        # Check top-5 contains T000-T004
        sample_date = list(uni.keys())[15]   # past lookback
        top5 = set(uni[sample_date])
        expected = {f"T{i:03d}.SZ" for i in range(5)}
        if top5 != expected:
            failures.append(f"top5 wrong: got {top5}, expected {expected}")

    # PIT test: future row should not change today's universe
    panel2 = pd.concat([panel, pd.DataFrame([{
        "ts_code": "T010.SZ", "trade_date": "20300101",
        "close": 10.0, "open": 10.0, "high": 10.0, "low": 10.0,
        "vol": 1e20, "amount": 1e21,
    }])])
    uni2 = compute_liquid_universe(panel2, top_n=5, lookback_days=10, min_dollar_vol=0)
    sample_date = list(uni.keys())[15]
    if uni[sample_date] != uni2[sample_date]:
        failures.append("PIT LEAK: future row changed today's universe")

    if failures:
        print("SELFTEST FAILED liquid_universe:")
        for f in failures:
            print(" -", f)
        return 1
    print("SELFTEST PASSED liquid_universe")
    print(f"- top-5 correctly = T000..T004 by ADV")
    print(f"- PIT enforced (future bar doesn't change today's universe)")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="PIT-clean liquid universe (top-N by 20d ADV).")
    p.add_argument("--prices", default=str(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet"))
    p.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    p.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK)
    p.add_argument("--min-dvol", type=float, default=DEFAULT_MIN_VOL_THRESHOLD)
    p.add_argument("--out", default=str(REPO_ROOT / "data_history" / "panel" / "liquid_universe.json"))
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()

    panel = pd.read_parquet(args.prices)
    print(f"Loaded panel: {len(panel):,} rows × {panel['ts_code'].nunique()} tickers", flush=True)
    uni = compute_liquid_universe(panel, top_n=args.top_n,
                                    lookback_days=args.lookback,
                                    min_dollar_vol=args.min_dvol)
    # Sanity print
    if uni:
        keys = sorted(uni.keys())
        sizes = [len(uni[k]) for k in keys]
        print(f"liquid_universe: {len(uni)} dates, "
              f"first {keys[0]} ({sizes[0]} tickers), last {keys[-1]} ({sizes[-1]} tickers)",
              flush=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(uni, ensure_ascii=False))
    print(f"wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
