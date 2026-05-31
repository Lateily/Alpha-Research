#!/usr/bin/env python3
"""iter16_attribution.py — ablation analysis on iter-16 mini1yr.

5 single-variable ablations + per-factor IC:

  A0 baseline    iter-16 unchanged
  A1 zero_cost   COMMISSION = STAMP_DUTY = SLIPPAGE = 0
  A2 invert      pick BOTTOM composite (no threshold gate)
  A3 ew_500      equal-weight top-50 liquid daily, full rebal each day
  A4 hold_only   only time_stop=7d exit (no hard_stop / trail / structure / TP)

  + per-factor IC over mini1yr window:
    6 factors × forward 1d/3d/5d/10d × Spearman cross-sectional IC daily
    → mean IC + t-stat (Newey-West-lite)

Output:
  public/data/iter16_attribution.json
  public/data/iter16_factor_ic.json

Usage:
  python3 scripts/iter16_attribution.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import run_swing_backtest_fast as engine
from run_swing_backtest_fast import run_swing_backtest_fast, fast_signals_one
from sector_scorer import load_sector_map
from swing_risk_manager import DEFAULT_CONFIG
from panel_index import PanelIndex
from liquid_universe import compute_liquid_universe
from stationary_bootstrap import bootstrap_ci, mean as bs_mean

START, END = "2025-05-26", "2026-05-25"
CAPITAL = 10_000_000

ITER16_CFG = {
    **DEFAULT_CONFIG,
    "min_hold_days": 0,
    "entry_composite_threshold": 70.0,
    "structure_break_threshold": 50.0,
    "take_profit_full": 0.20,
    "use_quality_filter": True,
    "quality_require_limitup": True,
    "quality_dd_floor": 0.80,
    "quality_up_day_min": 10,
}


# ─────────────────────── Ablation runner ────────────────────────────────

def alpha_ci(equity_curve, bench_curve):
    eqs = [pt["nav"] for pt in equity_curve]
    drs = [eqs[k]/eqs[k-1]-1 for k in range(1, len(eqs)) if eqs[k-1] > 0]
    bs = [pt["equity"] for pt in bench_curve]
    brs = [bs[k]/bs[k-1]-1 for k in range(1, len(bs)) if bs[k-1] > 0]
    n = min(len(drs), len(brs))
    if n < 5:
        return None
    alpha = [drs[i] - brs[i] for i in range(n)]
    ra = bootstrap_ci(alpha, bs_mean, B=10000, p=1/10, seed=42)
    ann = (1 + ra["point_estimate"]) ** 252 - 1
    lo = (1 + ra["ci_lo"]) ** 252 - 1
    hi = (1 + ra["ci_hi"]) ** 252 - 1
    direction = "POSITIVE" if ra["ci_lo"] > 0 else ("NEGATIVE" if ra["ci_hi"] < 0 else "STRADDLES")
    return {"point": ann, "lo": lo, "hi": hi, "p_value": ra["p_value_h0_zero"],
            "direction": direction, "excludes_zero": not ra["straddles_zero"]}


def run_one(name, panel, sector_map, cfg_overrides=None, zero_cost=False):
    """Run one ablation with optional cost zeroing."""
    saved = (engine.COMMISSION, engine.STAMP_DUTY_SELL, engine.SLIPPAGE)
    if zero_cost:
        engine.COMMISSION = 0.0
        engine.STAMP_DUTY_SELL = 0.0
        engine.SLIPPAGE = 0.0
    try:
        cfg = {**ITER16_CFG, **(cfg_overrides or {})}
        print(f"  running {name}...", flush=True)
        res = run_swing_backtest_fast(panel, sector_map, START, END,
                                       capital=CAPITAL, config=cfg, liquid_top_n=500)
        a = alpha_ci(res["equity_curve"], res["bench_curve"])
        return {
            "name": name,
            "cagr": res["cagr"], "sharpe": res["sharpe_annualized"],
            "max_dd": res["max_drawdown"], "trades": res["n_total_trades"],
            "final_nav": res["final_nav"], "alpha": a,
            "cfg_overrides": cfg_overrides,
            "zero_cost": zero_cost,
        }
    finally:
        engine.COMMISSION, engine.STAMP_DUTY_SELL, engine.SLIPPAGE = saved


# ─────────────────────── Per-factor IC ──────────────────────────────────

def per_factor_ic(panel, start, end, liquid_top_n=500,
                   horizons=(1, 3, 5, 10)):
    """Daily cross-sectional Spearman IC: factor → forward returns at horizon."""
    s_yyyymmdd = start.replace("-", "")
    e_yyyymmdd = end.replace("-", "")

    print("  computing liquid universe...", flush=True)
    liquid_uni = compute_liquid_universe(panel, top_n=liquid_top_n)
    all_liquid = set()
    for v in liquid_uni.values():
        all_liquid.update(v)
    sub = panel[panel["ts_code"].isin(all_liquid)]
    print(f"  panel sub: {len(sub):,} rows × {sub['ts_code'].nunique()} tickers", flush=True)
    idx = PanelIndex(sub)
    all_dates = idx.all_trade_dates()
    trade_dates = [d for d in all_dates if s_yyyymmdd <= d <= e_yyyymmdd]
    print(f"  IC trade dates: {len(trade_dates)} ({trade_dates[0]} → {trade_dates[-1]})",
          flush=True)

    factor_names = ["breakout_20d", "momentum_5d", "limit_up_followup",
                     "volume_spike", "macd_cross", "rsi_in_band"]
    horizons = list(horizons)
    daily_ic = {f: {h: [] for h in horizons} for f in factor_names}
    max_h = max(horizons)

    def spearmanr(xs, ys):
        """Spearman rank correlation (numpy-only, naive ties)."""
        xs = np.asarray(xs, dtype=float); ys = np.asarray(ys, dtype=float)
        n = len(xs)
        if n < 3:
            return (float("nan"), None)
        rx = np.argsort(np.argsort(xs)).astype(float)
        ry = np.argsort(np.argsort(ys)).astype(float)
        mx, my = rx.mean(), ry.mean()
        num = np.mean((rx - mx) * (ry - my))
        sx = rx.std(); sy = ry.std()
        if sx == 0 or sy == 0:
            return (float("nan"), None)
        return (float(num / (sx * sy)), None)

    for T_idx, T in enumerate(trade_dates):
        if T_idx + max_h >= len(trade_dates):
            break
        liquid_today = liquid_uni.get(T, [])
        if not liquid_today:
            continue

        # Compute factor values for all liquid_today tickers
        factor_values = {f: {} for f in factor_names}
        close_today = {}
        for tk in liquid_today:
            row = idx.row_at(tk, T)
            if row is None or row["close"] <= 0:
                continue
            close_today[tk] = row["close"]
            sig = fast_signals_one(idx, tk, T)
            if sig is None:
                continue
            for f in factor_names:
                v = sig["factors"].get(f)
                if v is not None and not (isinstance(v, float) and np.isnan(v)):
                    factor_values[f][tk] = float(v)

        # Forward returns at each horizon
        for h in horizons:
            T_future = trade_dates[T_idx + h]
            fwd_rets = {}
            for tk, c0 in close_today.items():
                row_future = idx.row_at(tk, T_future)
                if row_future is None or c0 <= 0:
                    continue
                fwd_rets[tk] = row_future["close"] / c0 - 1.0

            for f in factor_names:
                common = list(set(factor_values[f]) & set(fwd_rets))
                if len(common) < 30:
                    continue
                xs = np.array([factor_values[f][tk] for tk in common])
                ys = np.array([fwd_rets[tk] for tk in common])
                if len(np.unique(xs)) < 2 or len(np.unique(ys)) < 2:
                    continue
                rho, _ = spearmanr(xs, ys)
                if not np.isnan(rho):
                    daily_ic[f][h].append(float(rho))

        if T_idx % 50 == 0:
            print(f"    IC progress: {T_idx}/{len(trade_dates)} dates", flush=True)

    # Aggregate
    summary = {}
    for f in factor_names:
        summary[f] = {}
        for h in horizons:
            ics = daily_ic[f][h]
            if len(ics) < 5:
                summary[f][h] = None
                continue
            mean_ic = float(np.mean(ics))
            std_ic = float(np.std(ics, ddof=1))
            n = len(ics)
            se = std_ic / math.sqrt(n) if n > 1 else None
            t_stat = mean_ic / se if (se and se > 0) else None
            summary[f][h] = {
                "mean_ic": mean_ic, "std_ic": std_ic, "n_dates": n,
                "t_stat": t_stat,
                "ic_ir": mean_ic / std_ic if std_ic > 0 else None,
                "p_two_sided": (2 * (1 - 0.5 * (1 + math.erf(abs(t_stat) / math.sqrt(2)))))
                               if t_stat is not None else None,
            }
    return summary


# ─────────────────────── Pretty print ───────────────────────────────────

def print_table(ablations):
    print()
    print("="*92)
    print(f"{'Name':<14}{'CAGR':>10}{'Sharpe':>10}{'MaxDD':>10}{'Trades':>9}{'Alpha α':>12}{'CI':>26}")
    print("="*92)
    for r in ablations:
        a = r.get("alpha")
        if a:
            ci = f"[{a['lo']:+.3f},{a['hi']:+.3f}]"
            direction = a["direction"]
            ann = a["point"]
        else:
            ci = "n/a"; direction = "n/a"; ann = 0
        print(f"{r['name']:<14}{r['cagr']*100:+9.2f}%{r['sharpe'] or 0:+10.2f}"
              f"{r['max_dd']*100:+9.1f}%{r['trades']:>9}{ann:+11.3f}{ci:>26}")
    print("="*92)


def print_ic_table(ic_summary):
    print()
    print("="*70)
    print(f"{'Factor':<22}" + "".join(f"{f'IC_{h}d':>10}" for h in (1, 3, 5, 10))
          + "".join(f"{f't_{h}d':>8}" for h in (1, 3, 5, 10)))
    print("="*70)
    for f, by_h in ic_summary.items():
        row = f"{f:<22}"
        for h in (1, 3, 5, 10):
            d = by_h.get(h)
            row += f"{d['mean_ic']:+10.4f}" if d else f"{'n/a':>10}"
        for h in (1, 3, 5, 10):
            d = by_h.get(h)
            row += f"{d['t_stat']:+8.2f}" if d and d['t_stat'] is not None else f"{'n/a':>8}"
        print(row)
    print("="*70)
    print("(positive IC + |t|>2 ≈ significant predictive; negative IC = anti-predictive)")


# ─────────────────────── Main ──────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--ic-only", action="store_true",
                    help="Skip ablations, run only per-factor IC analysis.")
    args = p.parse_args()

    print("Loading panel...", flush=True)
    panel = pd.read_parquet(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet")
    sector_map = load_sector_map(str(REPO_ROOT / "data_history" / "sector_mapping.json"))
    print(f"Panel: {len(panel):,} rows × {panel['ts_code'].nunique()} tickers", flush=True)
    print(f"Window: {START} → {END}", flush=True)

    out_path = REPO_ROOT / "public" / "data" / "iter16_attribution.json"
    if args.ic_only:
        print("--ic-only: skipping ablations (reading prior results)")
        if out_path.exists():
            prior = json.loads(out_path.read_text())
            ablations = prior.get("ablations", [])
        else:
            ablations = []
    else:
        print("===== Running 5 ablations =====", flush=True)
        ablations = []
        def _save():
            out_path.write_text(json.dumps({"window": [START, END],
                                              "capital": CAPITAL,
                                              "ablations": ablations},
                                             indent=2, default=str))
        ablations.append(run_one("A0_baseline", panel, sector_map)); _save()
        ablations.append(run_one("A1_zero_cost", panel, sector_map, zero_cost=True)); _save()
        ablations.append(run_one("A2_invert", panel, sector_map, cfg_overrides={
            "_invert_signal": True,
            "entry_composite_threshold": 0.0,
        })); _save()
        ablations.append(run_one("A3_ew_500", panel, sector_map, cfg_overrides={
            "_ew_500": True, "_ew_n": 50,
            "use_quality_filter": False,
            "entry_composite_threshold": 0.0,
            "top_n_picks": 50,
        })); _save()
        ablations.append(run_one("A4_hold_only_7d", panel, sector_map, cfg_overrides={
            "_only_time_stop": True,
            "time_stop_days": 7,
            "hard_stop_pct": -99.0,
            "trailing_stop_pct": -99.0,
            "take_profit_full": 999.0,
            "structure_break_threshold": -1.0,
        })); _save()
        print_table(ablations)
        print(f"\nWrote {out_path}")
    if ablations:
        print_table(ablations)

    print("\n===== Per-factor IC =====", flush=True)
    ic = per_factor_ic(panel, START, END)
    print_ic_table(ic)
    out_path_ic = REPO_ROOT / "public" / "data" / "iter16_factor_ic.json"
    out_path_ic.write_text(json.dumps({"window": [START, END],
                                         "ic": ic}, indent=2, default=str))
    print(f"Wrote {out_path_ic}")


if __name__ == "__main__":
    sys.exit(main() or 0)
