#!/usr/bin/env python3
"""run_iter17_r2.py — Path B weekly inverse backtest (iter-17 R2).

Per SWING_STRATEGY_v2.md §3:
- Weekly rebal(rebal_cadence=5)
- Invert composite signal(_invert_signal=True → pick LOWEST composite)
- Simple exits: hard_stop -8% + time_stop 5 day (only)
- Gross cap 50%, max 8 positions
- Sector filter expanded(_sector_top_k=99 → include all 31 SW L1)
- Quality filter disabled(G1-G4 are momentum-based → conflict with inverse)

Bench (post-R0 engine): EW-500 daily rebal + cash 2%
Same-gross alpha computed from same_gross_curve.

Usage:
    python3 scripts/run_iter17_r2.py --window mini1yr
    python3 scripts/run_iter17_r2.py --window 10yr
    python3 scripts/run_iter17_r2.py --window 20yr
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_swing_backtest_fast import run_swing_backtest_fast
from sector_scorer import load_sector_map
from swing_risk_manager import DEFAULT_CONFIG
from stationary_bootstrap import bootstrap_ci, mean as bs_mean


# ─────────────────────── iter-17 R2 config ──────────────────────────────

ITER17_R2_CONFIG = {
    **DEFAULT_CONFIG,
    # Direction: inverse(R1 confirms 5/6 factor 长尺度 anti-edge)
    "_invert_signal": True,
    "entry_composite_threshold": 0.0,    # no threshold; sort ascending picks bottom
    # Rebal cadence: weekly
    "rebal_cadence": 5,
    # Exits: only hard_stop + time_stop
    "_only_time_stop": True,            # disables structure_break / trailing
    "time_stop_days": 5,                 # weekly hold
    "hard_stop_pct": -0.08,
    "trailing_stop_pct": -99.0,         # disabled
    "take_profit_full": 999.0,           # disabled
    "take_profit_pct": 999.0,            # disabled
    "structure_break_threshold": -1.0,   # disabled
    # Sizing(v2 §3.4 + §3.7): conservative
    "max_positions": 8,
    "top_n_picks": 8,
    "max_gross": 0.50,                   # 50% gross cap, vs v1's 95%
    "max_single_name_weight": 0.08,      # 8% per position
    "safety_max_single_name": 0.10,
    "vol_per_position": 0.02,
    "max_sector_weight": 0.30,
    # Universe(v2 §3.2): no quality filter, all sectors
    "use_quality_filter": False,
    "_sector_top_k": 99,                 # 31 SW L1 all included
    # Liquid top-N(v2: 300 → 跑 mini1yr 用 500 跟现有 baseline 一致;后期可下调)
}


# ─────────────────────── Alpha CI helpers ───────────────────────────────

def compute_same_gross_alpha(equity_curve, bench_curve, gross_floor=0.05):
    """Per spec: scale strat daily return by (1 / max(gross_pct, floor)) before alpha."""
    eqs = [pt["nav"] for pt in equity_curve]
    grosses = [pt.get("gross", 0) for pt in equity_curve]
    drs = []
    for k in range(1, len(eqs)):
        if eqs[k-1] <= 0:
            continue
        raw_ret = eqs[k] / eqs[k-1] - 1
        # Use yesterday's gross to scale (PIT: today's gross unknown at start of T)
        g = max(grosses[k-1] or 0, gross_floor)
        drs.append(raw_ret / g)

    bs = [pt["equity"] for pt in bench_curve]
    brs = [bs[k]/bs[k-1] - 1 for k in range(1, len(bs)) if bs[k-1] > 0]
    n = min(len(drs), len(brs))
    if n < 5:
        return None
    alpha = [drs[i] - brs[i] for i in range(n)]
    ra = bootstrap_ci(alpha, bs_mean, B=10000, p=1/10, seed=42)
    ann = (1 + ra["point_estimate"]) ** 252 - 1
    lo = (1 + ra["ci_lo"]) ** 252 - 1
    hi = (1 + ra["ci_hi"]) ** 252 - 1
    direction = ("POSITIVE" if ra["ci_lo"] > 0 else
                  "NEGATIVE" if ra["ci_hi"] < 0 else "STRADDLES")
    return {"point": ann, "lo": lo, "hi": hi, "p_value": ra["p_value_h0_zero"],
            "direction": direction, "excludes_zero": not ra["straddles_zero"],
            "n_dates": n, "gross_floor": gross_floor}


def compute_raw_alpha(equity_curve, bench_curve):
    """Plain daily(strat) - daily(bench) — for compat with iter-13~16 numbers."""
    eqs = [pt["nav"] for pt in equity_curve]
    drs = [eqs[k]/eqs[k-1] - 1 for k in range(1, len(eqs)) if eqs[k-1] > 0]
    bs = [pt["equity"] for pt in bench_curve]
    brs = [bs[k]/bs[k-1] - 1 for k in range(1, len(bs)) if bs[k-1] > 0]
    n = min(len(drs), len(brs))
    if n < 5:
        return None
    alpha = [drs[i] - brs[i] for i in range(n)]
    ra = bootstrap_ci(alpha, bs_mean, B=10000, p=1/10, seed=42)
    ann = (1 + ra["point_estimate"]) ** 252 - 1
    lo = (1 + ra["ci_lo"]) ** 252 - 1
    hi = (1 + ra["ci_hi"]) ** 252 - 1
    direction = ("POSITIVE" if ra["ci_lo"] > 0 else
                  "NEGATIVE" if ra["ci_hi"] < 0 else "STRADDLES")
    return {"point": ann, "lo": lo, "hi": hi, "p_value": ra["p_value_h0_zero"],
            "direction": direction, "excludes_zero": not ra["straddles_zero"]}


# ─────────────────────── Run ────────────────────────────────────────────

WINDOWS = {
    "mini1yr": ("2025-05-26", "2026-05-25"),
    "10yr":    ("2016-05-26", "2026-05-25"),
    "20yr":    ("2006-01-04", "2026-05-25"),
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--window", choices=list(WINDOWS), required=True)
    p.add_argument("--capital", type=float, default=10_000_000)
    p.add_argument("--liquid-top-n", type=int, default=500)
    p.add_argument("--out-dir", default=str(REPO_ROOT / "public" / "data"))
    args = p.parse_args()

    start, end = WINDOWS[args.window]

    print(f"=== iter-17 R2 (Path B weekly inverse) — {args.window} ===")
    print(f"Window: {start} → {end}")
    print(f"Capital: ¥{args.capital:,.0f}")
    print(f"Liquid top-N: {args.liquid_top_n}")
    print()

    print("Loading panel + sector map...")
    panel = pd.read_parquet(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet")
    sector_map = load_sector_map(str(REPO_ROOT / "data_history" / "sector_mapping.json"))

    print(f"Panel: {len(panel):,} rows × {panel['ts_code'].nunique()} tickers")
    print(f"Sector map: {len(sector_map)} mappings\n")

    print("Running backtest...")
    res = run_swing_backtest_fast(panel, sector_map, start, end,
                                    capital=args.capital,
                                    config=ITER17_R2_CONFIG,
                                    liquid_top_n=args.liquid_top_n,
                                    verbose=False)

    # Summary metrics
    cagr = res.get("cagr", 0)
    sharpe = res.get("sharpe_annualized")
    max_dd = res.get("max_drawdown", 0)
    final_nav = res.get("final_nav", 0)
    n_trades = res.get("n_total_trades", 0)
    audit = res.get("audit", {})

    print()
    print(f"=== RESULT iter-17 R2 {args.window} ===")
    print(f"CAGR: {cagr*100:+.2f}%")
    print(f"Sharpe: {sharpe if sharpe is None else f'{sharpe:.3f}'}")
    print(f"MaxDD: {max_dd*100:+.1f}%")
    print(f"Final NAV: ¥{final_nav:,.0f}")
    print(f"Total trades: {n_trades}")
    print()
    print(f"--- Audit gates ---")
    print(f"max_positions_cfg:      {audit.get('max_positions_cfg')}")
    print(f"max_positions_reached:  {audit.get('max_positions_reached')}")
    print(f"max_positions_enforced: {audit.get('max_positions_enforced')}")
    print(f"avg_n_positions:        {audit.get('avg_n_positions'):.2f}" if audit.get('avg_n_positions') is not None else "avg_n_positions: n/a")
    print(f"avg_gross_pct:          {(audit.get('avg_gross_pct') or 0)*100:.1f}%")
    print(f"max_gross_pct:          {(audit.get('max_gross_pct') or 0)*100:.1f}%")
    print(f"turnover_annual_pct:    {audit.get('turnover_annual_pct')}%" if audit.get('turnover_annual_pct') is not None else "turnover_annual_pct: n/a")
    print(f"avg_holding_days:       {audit.get('avg_holding_days')}")
    print(f"config_hash:            {audit.get('config_hash')}")
    print(f"data_hash:              {audit.get('data_hash')}")
    print(f"git_commit:             {audit.get('git_commit')}")
    print()

    # Alpha CI — raw + same-gross
    bench_curve = res.get("bench_curve") or []
    if not bench_curve and "benchmarks" in res:
        bench_curve = res["benchmarks"].get("ew_500", [])

    raw_alpha = compute_raw_alpha(res["equity_curve"], bench_curve)
    sg_alpha = compute_same_gross_alpha(res["equity_curve"], bench_curve, gross_floor=0.05)

    print(f"--- Alpha vs EW-500 bench ---")
    if raw_alpha:
        print(f"RAW ALPHA (annualized):       {raw_alpha['point']:+.4f} "
              f"CI [{raw_alpha['lo']:+.4f}, {raw_alpha['hi']:+.4f}] "
              f"p={raw_alpha['p_value']:.4f} {raw_alpha['direction']}")
    if sg_alpha:
        print(f"SAME-GROSS ALPHA (annualized): {sg_alpha['point']:+.4f} "
              f"CI [{sg_alpha['lo']:+.4f}, {sg_alpha['hi']:+.4f}] "
              f"p={sg_alpha['p_value']:.4f} {sg_alpha['direction']}")
        if sg_alpha["excludes_zero"]:
            print(f"*** SAME-GROSS ALPHA EXCLUDES 0 ON {sg_alpha['direction']} side ***")

    # Save
    out_path = Path(args.out_dir) / f"iter17_r2_backtest_{args.window}.json"
    res_with_alpha = {
        **res,
        "iter17_r2_alpha": {"raw": raw_alpha, "same_gross": sg_alpha},
        "iter17_r2_config": ITER17_R2_CONFIG,
        "iter17_r2_window": args.window,
    }
    out_path.write_text(json.dumps(res_with_alpha, indent=2, ensure_ascii=False, default=str))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    sys.exit(main() or 0)
