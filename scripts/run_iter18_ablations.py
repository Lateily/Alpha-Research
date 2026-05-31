#!/usr/bin/env python3
"""run_iter18_ablations.py — iter-18 single-variable ablations on R2 baseline.

Per Junyan Option C 2026-05-28:
  R2 baseline (iter-17 weekly inverse) showed mini1yr -0.31 same-gross α / 10yr ~0 /
  20yr +0.16 point-pos but CI straddles 0. v2 §5.3 strict reading = Verdict A;
  hybrid (Option C) = test 3 single-variable changes to see if any pass CI gate.

Ablations:
  B1 — 4-factor surgical: invert momentum/macd/breakout, keep rsi positive,
       skip volume_spike/limit_up (sector confound per R1 sector-neutral IC)
  B2 — max_gross 0.50 → 0.80
  B3 — disable ATR > 8% veto (kill of oversold rebounds)

Run on mini1yr/10yr/20yr each = 9 backtests. Each ~30-70s + bootstrap ~30s.

Usage:
    python3 scripts/run_iter18_ablations.py --ablation B1 --window mini1yr
    python3 scripts/run_iter18_ablations.py --ablation all --window all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_swing_backtest_fast import run_swing_backtest_fast
from sector_scorer import load_sector_map
from swing_risk_manager import DEFAULT_CONFIG
from run_iter17_r2 import (ITER17_R2_CONFIG, WINDOWS,
                            compute_raw_alpha, compute_same_gross_alpha)


# ─────────────────────── Ablation configs ────────────────────────────────

# B1: surgical 4-factor — invert 3 anti-edge factors + keep rsi positive
# Reasoning (per R1 20yr IC + sector-neutral):
#   momentum_5d:   sector-neutral IC -0.061 → real stock-level anti-edge → INVERT
#   macd_cross:    sector-neutral IC -0.019 → persistent → INVERT
#   breakout_20d:  sector-neutral IC -0.012 → mild → INVERT
#   rsi_in_band:   long-run POS +0.014 (only positive factor) → KEEP positive
#   volume_spike:  sector-neutral IC -0.016 (2/3 sector effect) → SKIP
#   limit_up_followup: sector-neutral IC near 0 → SKIP
ITER18_B1_CONFIG = {
    **ITER17_R2_CONFIG,
    "_invert_signal": False,    # don't globally invert — use factor_directions instead
    "factor_directions": {
        "momentum_5d": -1,    # invert
        "macd_cross": -1,
        "breakout_20d": -1,
        "rsi_in_band": +1,    # keep as is (high RSI in [40,70] = good)
        "volume_spike": 0,    # skip
        "limit_up_followup": 0,
    },
    "signal_weights_override": {
        "momentum_5d": 0.40,    # main anti-edge signal
        "macd_cross": 0.20,
        "breakout_20d": 0.20,
        "rsi_in_band": 0.20,
        "volume_spike": 0,      # weight 0 = effectively excluded
        "limit_up_followup": 0,
    },
    # Now we pick TOP composite (not bottom). composite_high = momentum LOW + ...
    "entry_composite_threshold": 50.0,    # composite ≥ 50 entry gate
}

# B2: same as R2 but higher gross cap
ITER18_B2_CONFIG = {
    **ITER17_R2_CONFIG,
    "max_gross": 0.80,    # 0.50 → 0.80
}

# B3: same as R2 but no ATR veto
ITER18_B3_CONFIG = {
    **ITER17_R2_CONFIG,
    "_skip_atr_veto": True,
}

ABLATIONS = {
    "B1": ("4-factor surgical (mom/macd/brk invert + rsi pos)", ITER18_B1_CONFIG),
    "B2": ("max_gross 0.80",                                       ITER18_B2_CONFIG),
    "B3": ("disable ATR veto",                                      ITER18_B3_CONFIG),
}


# ─────────────────────── Run one ablation × window ───────────────────────

def run_one(ablation: str, window: str, panel: pd.DataFrame, sector_map: dict,
             capital: float, liquid_top_n: int, out_dir: Path) -> dict:
    desc, cfg = ABLATIONS[ablation]
    start, end = WINDOWS[window]

    print(f"\n=== iter-18 {ablation} ({desc}) — {window} {start}→{end} ===")
    res = run_swing_backtest_fast(panel, sector_map, start, end,
                                    capital=capital, config=cfg,
                                    liquid_top_n=liquid_top_n, verbose=False)

    audit = res.get("audit", {})
    bench_curve = res.get("bench_curve") or (res.get("benchmarks", {}).get("ew_500", []))
    raw_alpha = compute_raw_alpha(res["equity_curve"], bench_curve)
    sg_alpha = compute_same_gross_alpha(res["equity_curve"], bench_curve, gross_floor=0.05)

    print(f"  CAGR={res.get('cagr',0)*100:+.2f}% "
          f"Sharpe={res.get('sharpe_annualized')} "
          f"MaxDD={res.get('max_drawdown',0)*100:+.1f}% "
          f"trades={res.get('n_total_trades')}")
    print(f"  audit: max_pos={audit.get('max_positions_reached')}/{audit.get('max_positions_cfg')} "
          f"avg_gross={(audit.get('avg_gross_pct') or 0)*100:.1f}% "
          f"turnover={audit.get('turnover_annual_pct')}%")
    if raw_alpha:
        print(f"  RAW α: {raw_alpha['point']:+.4f} CI [{raw_alpha['lo']:+.4f}, {raw_alpha['hi']:+.4f}] {raw_alpha['direction']}")
    if sg_alpha:
        marker = " *** EXCLUDES 0 POS ***" if (sg_alpha["excludes_zero"] and sg_alpha["direction"] == "POSITIVE") else ""
        print(f"  SAME-GROSS α: {sg_alpha['point']:+.4f} CI [{sg_alpha['lo']:+.4f}, {sg_alpha['hi']:+.4f}] {sg_alpha['direction']}{marker}")

    out_path = out_dir / f"iter18_{ablation}_backtest_{window}.json"
    res_with = {**res,
                "iter18_alpha": {"raw": raw_alpha, "same_gross": sg_alpha},
                "iter18_config": cfg, "iter18_ablation": ablation,
                "iter18_window": window, "iter18_description": desc}
    out_path.write_text(json.dumps(res_with, indent=2, ensure_ascii=False, default=str))
    print(f"  → {out_path.name}")

    return {
        "ablation": ablation, "window": window, "description": desc,
        "cagr": res.get("cagr"), "sharpe": res.get("sharpe_annualized"),
        "max_dd": res.get("max_drawdown"), "n_trades": res.get("n_total_trades"),
        "audit": audit,
        "raw_alpha": raw_alpha, "same_gross_alpha": sg_alpha,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ablation", choices=list(ABLATIONS) + ["all"], required=True)
    p.add_argument("--window",   choices=list(WINDOWS) + ["all"],   required=True)
    p.add_argument("--capital", type=float, default=10_000_000)
    p.add_argument("--liquid-top-n", type=int, default=500)
    p.add_argument("--out-dir", default=str(REPO_ROOT / "public" / "data"))
    args = p.parse_args()

    print("Loading panel + sector map...")
    panel = pd.read_parquet(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet")
    sector_map = load_sector_map(str(REPO_ROOT / "data_history" / "sector_mapping.json"))
    print(f"Panel: {len(panel):,} rows × {panel['ts_code'].nunique()} tickers\n")

    ablations_to_run = list(ABLATIONS) if args.ablation == "all" else [args.ablation]
    windows_to_run   = list(WINDOWS)   if args.window   == "all" else [args.window]
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for ab in ablations_to_run:
        for w in windows_to_run:
            results.append(run_one(ab, w, panel, sector_map,
                                    args.capital, args.liquid_top_n, out_dir))

    # Summary
    print("\n" + "="*100)
    print(f"{'Ablation':<10}{'Window':<10}{'CAGR':>10}{'Sharpe':>10}{'MaxDD':>10}"
          f"{'Trades':>10}{'Gross':>8}{'Same-gross α':>16}{'CI':>26}")
    print("="*100)
    for r in results:
        sg = r["same_gross_alpha"] or {}
        ci = f"[{sg.get('lo','n/a'):+.3f},{sg.get('hi','n/a'):+.3f}]" if sg else "n/a"
        excl = "✓POS" if (sg and sg.get("excludes_zero") and sg.get("direction") == "POSITIVE") else ""
        print(f"{r['ablation']:<10}{r['window']:<10}"
              f"{(r['cagr'] or 0)*100:+9.2f}%"
              f"{(r['sharpe'] or 0):+10.3f}"
              f"{(r['max_dd'] or 0)*100:+9.1f}%"
              f"{r['n_trades']:>10}"
              f"{(r['audit'].get('avg_gross_pct') or 0)*100:>7.1f}%"
              f"{(sg.get('point',0) if sg else 0):+16.4f}"
              f"{ci:>26}{excl:>6}")
    print("="*100)

    sum_path = out_dir / "iter18_ablations_summary.json"
    sum_path.write_text(json.dumps({"ablations": results}, indent=2, ensure_ascii=False, default=str))
    print(f"\nWrote summary to {sum_path}")


if __name__ == "__main__":
    sys.exit(main() or 0)
