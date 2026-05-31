#!/usr/bin/env python3
"""run_iter18_walkforward_combo.py — Walk-forward OOS for B1+B3 combo.

Per Junyan 2026-05-28 directive (post-Codex B1+B3 finding):
  Codex 's iter-18 combo (b1_b3_4factor_no_atr) showed 20yr same-gross α
  EXCLUDES 0 POS (+37.85% CI [+6.6%, +78.7%] p=0.016). Single-window
  result is fragile — walk-forward 5 × 4-yr windows is v2 §6.4 mandate.

Windows (4 IS + 1 OOS):
  IS1 2006-01-04 → 2009-12-31
  IS2 2010-01-01 → 2013-12-31
  IS3 2014-01-01 → 2017-12-31
  IS4 2018-01-01 → 2021-12-31
  OOS 2022-01-01 → 2026-05-25

Strict v2 §6.4 reading: **OOS window alpha CI MUST exclude 0 POS** for
swing to clear "real edge" gate. IS windows are diagnostic only — they
don't justify shipping if OOS fails.

Combo config: ITER18_B1_CONFIG + skip_atr_veto=True

Usage:
    python3 scripts/run_iter18_walkforward_combo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_swing_backtest_fast import run_swing_backtest_fast
from sector_scorer import load_sector_map
from run_iter18_ablations import ITER18_B1_CONFIG
from run_iter17_r2 import compute_raw_alpha, compute_same_gross_alpha


# B1+B3 combo: B1's factor_directions + signal_weights + B3's skip_atr_veto
ITER18_COMBO_CONFIG = {
    **ITER18_B1_CONFIG,
    "_skip_atr_veto": True,
}


WINDOWS = [
    ("IS1_2006_2009", "2006-01-04", "2009-12-31"),
    ("IS2_2010_2013", "2010-01-01", "2013-12-31"),
    ("IS3_2014_2017", "2014-01-01", "2017-12-31"),
    ("IS4_2018_2021", "2018-01-01", "2021-12-31"),
    ("OOS_2022_2026", "2022-01-01", "2026-05-25"),
]


def run_window(name: str, start: str, end: str, panel: pd.DataFrame,
                sector_map: dict, capital: float, liquid_top_n: int) -> dict:
    print(f"\n=== {name}: {start} → {end} ===")
    res = run_swing_backtest_fast(panel, sector_map, start, end,
                                    capital=capital,
                                    config=ITER18_COMBO_CONFIG,
                                    liquid_top_n=liquid_top_n,
                                    verbose=False)

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

    out_path = REPO_ROOT / "public" / "data" / f"iter18_combo_wf_{name}.json"
    res_with = {**res,
                 "iter18_combo_alpha": {"raw": raw_alpha, "same_gross": sg_alpha},
                 "iter18_combo_config": ITER18_COMBO_CONFIG,
                 "iter18_combo_window": name,
                 "iter18_combo_period": [start, end]}
    out_path.write_text(json.dumps(res_with, indent=2, ensure_ascii=False, default=str))

    return {"name": name, "start": start, "end": end,
            "cagr": res.get("cagr"), "sharpe": res.get("sharpe_annualized"),
            "max_dd": res.get("max_drawdown"), "n_trades": res.get("n_total_trades"),
            "audit": audit,
            "raw_alpha": raw_alpha, "same_gross_alpha": sg_alpha}


def main():
    print("Loading panel + sector map...")
    panel = pd.read_parquet(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet")
    sector_map = load_sector_map(str(REPO_ROOT / "data_history" / "sector_mapping.json"))
    print(f"Panel: {len(panel):,} rows × {panel['ts_code'].nunique()} tickers\n")

    print(f"Combo cfg: B1 factor_directions + signal_weights + B3 skip_atr_veto")
    print(f"factor_directions: {ITER18_COMBO_CONFIG.get('factor_directions')}")
    print(f"signal_weights:    {ITER18_COMBO_CONFIG.get('signal_weights_override')}")
    print(f"max_gross={ITER18_COMBO_CONFIG.get('max_gross')} "
          f"max_pos={ITER18_COMBO_CONFIG.get('max_positions')} "
          f"rebal={ITER18_COMBO_CONFIG.get('rebal_cadence')}d "
          f"time_stop={ITER18_COMBO_CONFIG.get('time_stop_days')}d "
          f"skip_atr_veto={ITER18_COMBO_CONFIG.get('_skip_atr_veto')}\n")

    results = []
    for name, start, end in WINDOWS:
        results.append(run_window(name, start, end, panel, sector_map,
                                   capital=10_000_000, liquid_top_n=500))

    # Summary
    print("\n" + "="*120)
    print(f"{'Window':<22}{'Period':<28}{'CAGR':>10}{'Sharpe':>10}{'MaxDD':>10}"
          f"{'Trades':>10}{'Gross':>8}{'Same-gross α':>16}{'CI':>26}{'Verdict':>10}")
    print("="*120)
    for r in results:
        sg = r["same_gross_alpha"] or {}
        ci = f"[{sg.get('lo','n/a'):+.3f},{sg.get('hi','n/a'):+.3f}]" if sg else "n/a"
        verdict = "✓POS" if (sg and sg.get("excludes_zero") and sg.get("direction") == "POSITIVE") \
                   else ("✗NEG" if (sg and sg.get("excludes_zero") and sg.get("direction") == "NEGATIVE") else "STRAD")
        oos_marker = " ← OOS" if r['name'].startswith("OOS") else ""
        print(f"{r['name']:<22}{r['start']+'→'+r['end']:<28}"
              f"{(r['cagr'] or 0)*100:+9.2f}%"
              f"{(r['sharpe'] or 0):+10.3f}"
              f"{(r['max_dd'] or 0)*100:+9.1f}%"
              f"{r['n_trades']:>10}"
              f"{(r['audit'].get('avg_gross_pct') or 0)*100:>7.1f}%"
              f"{(sg.get('point',0) if sg else 0):+16.4f}"
              f"{ci:>26}"
              f"{verdict:>10}{oos_marker}")
    print("="*120)

    # OOS verdict per v2 §6.4
    oos_result = next((r for r in results if r["name"].startswith("OOS")), None)
    if oos_result:
        sg = oos_result["same_gross_alpha"] or {}
        print(f"\n--- v2 §6.4 OOS Verdict ---")
        if sg.get("excludes_zero") and sg.get("direction") == "POSITIVE":
            print(f"*** OOS PASS: alpha CI {[sg['lo'], sg['hi']]} EXCLUDES 0 POS ***")
            print(f"    Real edge candidate confirmed in 2022-2026 OOS.")
        else:
            print(f"OOS FAIL: alpha CI {[sg.get('lo'), sg.get('hi')]} {sg.get('direction','n/a')}")
            print(f"    Per v2 §6.4 swing concept fails walk-forward → Verdict A stands.")

    sum_path = REPO_ROOT / "public" / "data" / "iter18_combo_walkforward_summary.json"
    sum_path.write_text(json.dumps({"windows": results}, indent=2, ensure_ascii=False, default=str))
    print(f"\nWrote summary to {sum_path}")


if __name__ == "__main__":
    sys.exit(main() or 0)
