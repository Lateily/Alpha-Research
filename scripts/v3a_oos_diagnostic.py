#!/usr/bin/env python3
"""v3a_oos_diagnostic.py — Diagnose why walk-forward OOS 2022-2026 NEG.

Input:  public/data/rolling_ic_20yr.json  (R1 raw 20yr per-factor IC)
        public/data/iter18_combo_walkforward_summary.json  (5 windows)
        data_history/panel/daily_prices.parquet  (panel for ancillary stats)

Output: public/data/v3a_oos_diagnostic.json
        docs/strategy/V3A_OOS_DIAGNOSTIC_2026-05-28.md

Per Junyan 2026-05-28 PM2:
> 先诊断 2022-2026 为什么显著负,不要直接进入多变体搜索。否则很容易变成更高级的 curve-fit。

Hypotheses to test:
  H1: Factor IC sign flipped 2022+ (regime change post-注册制 / retail composition)
  H2: Factor IC magnitude faded (always negative but smaller → cost-overwhelmed)
  H3: Sector composition drift made aggregate IC misleading (e.g., new sector dominance)
  H4: Liquidity drift: ChiNext/STAR growth changed universe character
  H5: Implementation artifact (gross too low, median_pos=0/1 forces single-bet behavior)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

# Sub-periods matching walk-forward windows
SUB_PERIODS = [
    ("2006-2010", "20060101", "20091231"),
    ("2010-2014", "20100101", "20131231"),
    ("2014-2018", "20140101", "20171231"),
    ("2018-2022", "20180101", "20211231"),
    ("2022-2026", "20220101", "20260525"),
]

FACTORS = ["breakout_20d", "momentum_5d", "limit_up_followup",
            "volume_spike", "macd_cross", "rsi_in_band"]
HORIZONS = [1, 3, 5, 10]


def load_ic():
    return json.load(open(REPO_ROOT / "public" / "data" / "rolling_ic_20yr.json"))


def load_walkforward():
    """Use Codex handoff JSON since we killed our local walk-forward."""
    p_handoff = REPO_ROOT / "experiments" / "agent_tasks" / "codex_to_claude_iter18_walkforward_verdict_2026-05-28.json"
    d = json.load(open(p_handoff))
    # Adapter: convert Codex schema to our shape
    windows = []
    for w in d.get("walk_forward_windows", []):
        sga = {
            "point": w["same_gross_alpha"], "lo": w["ci"][0], "hi": w["ci"][1],
            "p_value": w["p_value"], "direction": w["direction"],
        }
        windows.append({
            "name": w["window"], "start": w["start"], "end": w["end"],
            "cagr": w["cagr"], "sharpe": None,
            "max_dd": w.get("max_dd"),
            "n_trades": w.get("n_trades", None),
            "audit": {
                "avg_gross_pct": w["avg_gross"],
                "median_n_positions": w["median_positions"],
            },
            "same_gross_alpha": sga,
        })
    return {"windows": windows}


def subperiod_ic_table(ic_data):
    """For each (factor, horizon), compute mean IC + t-stat in each sub-period
    using the rolling_252d_ic_path daily values."""
    rows = []
    for f in FACTORS:
        for h in HORIZONS:
            key = f"{f}.{h}d"
            summary = ic_data["summary"].get(key)
            if not summary:
                continue
            path = summary.get("rolling_252d_ic_path", [])
            dates = summary.get("rolling_252d_ic_dates", [])
            # rolling values represent average over the prior 252 days, dated at the end
            for label, start, end in SUB_PERIODS:
                # find IC values within [start, end]
                vals = [v for v, d in zip(path, dates) if start <= d <= end and v is not None]
                if len(vals) < 30:
                    rows.append({"factor": f, "horizon_d": h, "subperiod": label,
                                  "n": len(vals), "mean_ic": None, "std_ic": None,
                                  "t_stat": None})
                    continue
                arr = np.asarray(vals, dtype=float)
                m = float(arr.mean())
                s = float(arr.std(ddof=1))
                t = m / (s / np.sqrt(len(arr))) if s > 0 else None
                rows.append({
                    "factor": f, "horizon_d": h, "subperiod": label,
                    "n": len(vals), "mean_ic": round(m, 4),
                    "std_ic": round(s, 4),
                    "t_stat": round(t, 2) if t is not None else None,
                })
    return rows


def fade_analysis(ic_data, factor, horizon):
    """For one (factor, horizon), compare 2006-2010 mean IC vs 2022-2026 mean IC.
    Return % fade and sign-flip indicator."""
    key = f"{factor}.{horizon}d"
    summary = ic_data["summary"].get(key, {})
    path = summary.get("rolling_252d_ic_path", [])
    dates = summary.get("rolling_252d_ic_dates", [])
    if not path:
        return None
    early = [v for v, d in zip(path, dates) if "20060101" <= d <= "20091231" and v is not None]
    late = [v for v, d in zip(path, dates) if "20220101" <= d <= "20260525" and v is not None]
    if len(early) < 30 or len(late) < 30:
        return None
    e_mean = float(np.mean(early))
    l_mean = float(np.mean(late))
    sign_flip = (e_mean < 0) != (l_mean < 0)
    pct_change = (l_mean - e_mean) / abs(e_mean) * 100 if e_mean != 0 else None
    return {
        "factor": factor, "horizon_d": horizon,
        "early_mean_ic": round(e_mean, 4),
        "late_mean_ic": round(l_mean, 4),
        "sign_flip": sign_flip,
        "pct_change_magnitude": round(pct_change, 1) if pct_change is not None else None,
        "n_early": len(early), "n_late": len(late),
    }


def universe_drift(panel):
    """Per-subperiod stock-count, median ADV, ChiNext/STAR/SH-Main breakdown."""
    rows = []
    # ts_code prefix mapping
    def classify(tk):
        if tk.startswith("60"):    return "SH_main"
        if tk.startswith("68"):    return "STAR"
        if tk.startswith("00"):    return "SZ_main"
        if tk.startswith("30"):    return "ChiNext"
        if tk.startswith("8") or tk.startswith("4"):  return "BJ_north"
        return "other"
    panel = panel.copy()
    panel["board"] = panel["ts_code"].str[:2].map(lambda p: "SH_main" if p == "60"
                                                    else "STAR" if p == "68"
                                                    else "SZ_main" if p == "00"
                                                    else "ChiNext" if p == "30"
                                                    else "BJ_north" if p in ("83", "43", "87")
                                                    else "other")
    for label, start, end in SUB_PERIODS:
        sub = panel[(panel["trade_date"] >= start) & (panel["trade_date"] <= end)]
        n_dates = sub["trade_date"].nunique()
        n_tickers = sub["ts_code"].nunique()
        # Approx ADV per ticker (avg daily amount, in thousand yuan since amount unit)
        adv_by_tk = sub.groupby("ts_code")["amount"].mean()
        med_adv_kyuan = float(adv_by_tk.median()) if len(adv_by_tk) > 0 else None
        # Median ADV in 元 (× 1000)
        med_adv_yuan = med_adv_kyuan * 1000 if med_adv_kyuan else None
        # Board breakdown by ticker count
        board_counts = sub.groupby("board")["ts_code"].nunique().to_dict()
        # New listings: ts_codes whose first trade_date is in this subperiod
        first_date = sub.groupby("ts_code")["trade_date"].min()
        new_listings = (first_date == sub["trade_date"].min()).sum() if not sub.empty else 0
        # Better metric: # of tickers whose absolute first trade_date is within this subperiod
        first_overall = panel.groupby("ts_code")["trade_date"].min()
        new_in_period = ((first_overall >= start) & (first_overall <= end)).sum()
        rows.append({
            "subperiod": label, "n_trade_dates": n_dates,
            "n_unique_tickers": n_tickers,
            "median_adv_yuan": int(med_adv_yuan) if med_adv_yuan else None,
            "board_breakdown": board_counts,
            "new_listings_in_period": int(new_in_period),
        })
    return rows


def main():
    print("Loading IC data...")
    ic_data = load_ic()
    wf_data = load_walkforward()
    print(f"  IC: {len(ic_data['summary'])} (factor, horizon) entries")
    print(f"  WF: {len(wf_data['windows'])} windows")

    print("\nLoading panel for universe drift analysis...")
    panel = pd.read_parquet(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet",
                              columns=["ts_code", "trade_date", "amount"])
    print(f"  Panel: {len(panel):,} rows × {panel['ts_code'].nunique()} tickers")

    print("\n=== 1. Sub-period IC table (using rolling 252d daily values) ===")
    sub_ic = subperiod_ic_table(ic_data)

    print("\n=== 2. Fade analysis 2006-2010 vs 2022-2026 ===")
    fades = []
    for f in FACTORS:
        for h in HORIZONS:
            r = fade_analysis(ic_data, f, h)
            if r:
                fades.append(r)

    print("\n=== 3. Universe drift by sub-period ===")
    drift = universe_drift(panel)

    print("\n=== 4. Walk-forward CAGR & alpha by window ===")
    wf_summary = []
    for w in wf_data["windows"]:
        sga = w.get("same_gross_alpha", {}) or {}
        wf_summary.append({
            "window": w["name"],
            "period": [w["start"], w["end"]],
            "cagr": w["cagr"],
            "sharpe": w["sharpe"],
            "max_dd": w["max_dd"],
            "n_trades": w["n_trades"],
            "audit_avg_gross": (w.get("audit", {}) or {}).get("avg_gross_pct"),
            "audit_median_pos": (w.get("audit", {}) or {}).get("median_n_positions"),
            "same_gross_alpha_point": sga.get("point"),
            "same_gross_alpha_ci": [sga.get("lo"), sga.get("hi")],
            "same_gross_alpha_p": sga.get("p_value"),
            "verdict": sga.get("direction"),
        })

    out = {
        "_meta": {
            "task": "v3a OOS failure diagnostic",
            "junyan_directive": "先诊断 2022-2026 为什么显著负,不要直接进入多变体搜索。否则很容易变成更高级的 curve-fit。",
            "input_files": [
                "public/data/rolling_ic_20yr.json",
                "public/data/iter18_combo_walkforward_summary.json",
                "data_history/panel/daily_prices.parquet",
            ],
        },
        "sub_period_ic_table": sub_ic,
        "fade_analysis": fades,
        "universe_drift": drift,
        "walkforward_summary": wf_summary,
    }

    out_path = REPO_ROOT / "public" / "data" / "v3a_oos_diagnostic.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    print(f"\nWrote {out_path}")

    # Print key tables to console
    print("\n========================================")
    print("KEY FINDING: Sub-period 5d-horizon mean IC")
    print("========================================")
    print(f"{'Factor':<22}{'Sub-period':<15}{'mean_IC':>10}{'t':>8}{'n':>8}")
    for r in sub_ic:
        if r["horizon_d"] != 5:
            continue
        print(f"{r['factor']:<22}{r['subperiod']:<15}"
              f"{r['mean_ic'] or 0:>10.4f}"
              f"{r['t_stat'] or 0:>8.2f}"
              f"{r['n']:>8}")

    print("\n========================================")
    print("KEY FINDING: Fade analysis (early vs late)")
    print("========================================")
    print(f"{'Factor.horizon':<22}{'2006-10 IC':>12}{'2022-26 IC':>12}{'Δ %':>8}{'flip?':>8}")
    for r in fades:
        print(f"{r['factor']+'.'+str(r['horizon_d'])+'d':<22}"
              f"{r['early_mean_ic']:>12.4f}"
              f"{r['late_mean_ic']:>12.4f}"
              f"{(r['pct_change_magnitude'] or 0):>7.1f}%"
              f"{('FLIP!' if r['sign_flip'] else ''):>8}")

    print("\n========================================")
    print("KEY FINDING: Universe drift")
    print("========================================")
    for r in drift:
        print(f"{r['subperiod']}: n_tickers={r['n_unique_tickers']}, "
              f"med_ADV={r['median_adv_yuan']:,d} yuan, "
              f"new_listings={r['new_listings_in_period']}, "
              f"boards={r['board_breakdown']}")


if __name__ == "__main__":
    sys.exit(main() or 0)
