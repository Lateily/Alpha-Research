#!/usr/bin/env python3
"""v3c_regime_diagnostic.py — READ-ONLY regime diagnostic for the α1.x inverse-momentum signal.

Per Junyan 2026-05-29 directive (α1.x line STOPPED): allow exactly ONE read-only
regime diagnostic — NOT a new variant, NO parameter tuning. It answers a single
question: is the inverse-momentum edge that appears in 2006-2010 (+1.39 same-gross
α, p=0.038, the ONLY walk-forward window individually excluding 0) a REPEATABLE
crisis-reversal phenomenon, or a 2008-only fluke?

Method (read-only):
  - Use the EXACT locked α1.3A config (`_config_from_manifest` on the α1.3A
    manifest, baseline cost). No knob is changed — this is the honest-swing
    configuration (max_hold_days=60). We only change the DATE WINDOW.
  - Run that config over objectively-dated A-share bear episodes (crash onset →
    into recovery, since the thesis is crisis-REVERSAL: buy beaten-down names,
    ride the bounce) and, for contrast, over calm/bull windows between crises.
  - Measure same-gross α (stationary-bootstrap CI) + turnover + n_trades per
    window.

Decision rule (Junyan):
  - Only 2008 positive  → regime path ALSO stops.
  - ≥ 2-3 of {2015, 2018, 2022, 2024} crisis segments ALSO positive (and calm
    windows systematically weaker) → THEN allow drafting a regime-conditional
    manifest. (This script does NOT draft one; it only informs the decision.)

Crisis windows are STANDARD, widely-documented A-share bear episodes dated by
index peak→recovery — NOT tuned to the outcome. Calm windows are the bull/
sideways stretches between them. Both lists are fixed here for transparency.

Usage:
    python3 scripts/v3c_regime_diagnostic.py
    python3 scripts/v3c_regime_diagnostic.py --windows crisis_2008,crisis_2015
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_swing_backtest_fast import run_swing_backtest_fast
from sector_scorer import load_sector_map
from run_iter17_r2 import compute_raw_alpha, compute_same_gross_alpha
from run_v3c_alpha1_1 import _config_from_manifest, _normalize_window_dates

A13A_MANIFEST = (REPO_ROOT / "experiments" / "agent_tasks" / "variant_manifests"
                 / "v3c_alpha1_3a_20260529.json")

# Standard A-share bear episodes (index peak → into recovery). Dated from
# well-known CSI300/CSI-All drawdown episodes; the recovery tail is included
# because the inverse-momentum thesis is crisis-REVERSAL (the payoff is the
# bounce in beaten-down names). These are NOT tuned to the strategy's outcome.
CRISIS_WINDOWS = {
    "crisis_2008": ("2008-01-01", "2009-08-31"),   # GFC crash + 2009 rebound (CSI300 -66% then +100%)
    "crisis_2011": ("2011-04-01", "2012-12-31"),   # 2011 deleverage bear
    "crisis_2015": ("2015-06-01", "2016-12-31"),   # bubble burst + circuit breaker + recovery
    "crisis_2018": ("2018-01-01", "2019-04-30"),   # trade-war/deleverage selloff + early-2019 rally
    "crisis_2022": ("2022-01-01", "2022-12-31"),   # zero-COVID/property drawdown + Q4 bounce
    "crisis_2024": ("2024-01-01", "2024-09-30"),   # micro-cap/snowball crash + recovery + Sep rally
}

# Calm / bull / sideways stretches between crises (contrast set).
CALM_WINDOWS = {
    "calm_2009_2010": ("2009-09-01", "2010-12-31"),
    "calm_2013_2014": ("2013-01-01", "2014-12-31"),
    "calm_2017":      ("2017-01-01", "2017-12-31"),
    "calm_2019_2021": ("2019-05-01", "2021-12-31"),
    "calm_2023":      ("2023-01-01", "2023-12-31"),
}


def run_window(name: str, start: str, end: str, panel, sector_map, cfg) -> dict:
    e_start, e_end = _normalize_window_dates(start, end)
    t0 = time.time()
    res = run_swing_backtest_fast(panel, sector_map, e_start, e_end,
                                  capital=10_000_000, config=cfg, verbose=False,
                                  liquid_top_n=500)
    elapsed = time.time() - t0
    if res.get("_status") == "insufficient_data":
        print(f"  ! {name}: insufficient_data")
        return {"window": name, "period": [e_start, e_end], "status": "insufficient_data"}
    bench = res.get("bench_curve") or (res.get("benchmarks", {}).get("ew_500", []))
    sg = compute_same_gross_alpha(res["equity_curve"], bench, gross_floor=0.05)
    raw = compute_raw_alpha(res["equity_curve"], bench)
    a = res.get("audit", {})
    sgp = sg["point"] if sg else None
    excl = (sg and sg.get("excludes_zero") and sg.get("direction") == "POSITIVE")
    print(f"  {name:<16} {e_start}→{e_end}  "
          f"sg_α={sgp:+.4f} " + (f"CI[{sg['lo']:+.3f},{sg['hi']:+.3f}] p={sg.get('p_value'):.3f}" if sg else "n/a") +
          f"  turn={(a.get('turnover_annual_ratio') or 0)*100:.0f}% "
          f"trades={res.get('n_total_trades')} "
          f"{'  *** +α excl0 ***' if excl else ''} [{elapsed:.0f}s]")
    return {
        "window": name, "period": [e_start, e_end],
        "same_gross_alpha": sg, "raw_alpha": raw,
        "turnover_annual_ratio": a.get("turnover_annual_ratio"),
        "avg_holding_days": a.get("avg_holding_days"),
        "n_total_trades": res.get("n_total_trades"),
        "cagr": res.get("cagr"), "max_drawdown": res.get("max_drawdown"),
        "avg_gross_pct": a.get("avg_gross_pct"),
    }


def _verdict(rows: list[dict], label: str) -> dict:
    valid = [r for r in rows if r.get("same_gross_alpha")]
    n_pos = sum(1 for r in valid if (r["same_gross_alpha"].get("point") or 0) > 0)
    n_pos_sig = sum(1 for r in valid
                    if r["same_gross_alpha"].get("excludes_zero")
                    and r["same_gross_alpha"].get("direction") == "POSITIVE")
    pts = [r["same_gross_alpha"]["point"] for r in valid if r["same_gross_alpha"].get("point") is not None]
    return {"label": label, "n": len(valid), "n_pos_point": n_pos,
            "n_pos_sig_excl0": n_pos_sig,
            "mean_point": (sum(pts) / len(pts) if pts else None)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", default=str(A13A_MANIFEST))
    p.add_argument("--windows", default=None, help="comma list to restrict")
    p.add_argument("--out", default=str(REPO_ROOT / "public" / "data" / "v3c_regime_diagnostic.json"))
    args = p.parse_args(argv)

    manifest = json.loads(Path(args.manifest).read_text())
    cfg = _config_from_manifest(manifest, "baseline_0.40_RT")
    print(f"[regime-diag] READ-ONLY. Locked α1.3A config (max_hold_days={cfg.get('max_hold_days')}, "
          f"rebal={cfg.get('rebal_cadence')}). No tuning — only date windows vary.")
    print(f"[regime-diag] loading panel...")
    panel = __import__("pandas").read_parquet(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet")
    sector_map = load_sector_map(str(REPO_ROOT / "data_history" / "sector_mapping.json"))
    print(f"[regime-diag] panel: {len(panel):,} rows × {panel['ts_code'].nunique()} tickers")

    all_windows = {**{k: ("crisis", v) for k, v in CRISIS_WINDOWS.items()},
                   **{k: ("calm", v) for k, v in CALM_WINDOWS.items()}}
    if args.windows:
        want = set(args.windows.split(","))
        all_windows = {k: v for k, v in all_windows.items() if k in want}

    print("\n=== CRISIS windows (crash → recovery) ===")
    crisis_rows = []
    for name, (kind, (s, e)) in all_windows.items():
        if kind != "crisis":
            continue
        crisis_rows.append({**run_window(name, s, e, panel, sector_map, cfg), "kind": "crisis"})

    print("\n=== CALM windows (bull/sideways contrast) ===")
    calm_rows = []
    for name, (kind, (s, e)) in all_windows.items():
        if kind != "calm":
            continue
        calm_rows.append({**run_window(name, s, e, panel, sector_map, cfg), "kind": "calm"})

    crisis_v = _verdict(crisis_rows, "crisis")
    calm_v = _verdict(calm_rows, "calm")
    print("\n" + "=" * 70)
    print("REGIME DIAGNOSTIC SUMMARY (α1.3A locked config, same-gross α)")
    print("=" * 70)
    print(f"CRISIS: {crisis_v['n_pos_point']}/{crisis_v['n']} positive point, "
          f"{crisis_v['n_pos_sig_excl0']} excl-0; mean α={crisis_v['mean_point']}")
    print(f"CALM:   {calm_v['n_pos_point']}/{calm_v['n']} positive point, "
          f"{calm_v['n_pos_sig_excl0']} excl-0; mean α={calm_v['mean_point']}")
    print()
    # Junyan's decision rule (informational; does NOT draft anything).
    non2008 = [r for r in crisis_rows if r["window"] != "crisis_2008" and r.get("same_gross_alpha")]
    non2008_pos = sum(1 for r in non2008 if (r["same_gross_alpha"].get("point") or 0) > 0)
    print(f"DECISION INPUT: non-2008 crisis windows positive = {non2008_pos}/{len(non2008)}")
    if non2008_pos >= 2:
        print("  → ≥2 non-2008 crises positive: regime-conditional path MAY be worth a manifest (Junyan's call).")
    else:
        print("  → <2 non-2008 crises positive: per Junyan rule, regime path ALSO stops (2008 looks like a fluke).")

    out = {"_meta": {"diagnostic": "v3c_regime_diagnostic", "read_only": True,
                     "config_source": "v3c_alpha1_3a (locked)", "no_tuning": True,
                     "crisis_window_rule": "standard A-share bear episodes, index peak→recovery, NOT outcome-tuned"},
           "crisis": crisis_rows, "calm": calm_rows,
           "summary": {"crisis": crisis_v, "calm": calm_v, "non2008_positive": [non2008_pos, len(non2008)]}}
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    print(f"\n[regime-diag] wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
