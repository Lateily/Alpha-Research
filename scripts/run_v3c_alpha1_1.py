#!/usr/bin/env python3
"""run_v3c_alpha1_1.py — V3C-α1.1 backtest runner (v3 Phase B α1.1).

Per `experiments/agent_tasks/variant_manifests/v3c_alpha1_1_20260528.json`:
  - 6 windows: full_20yr + wf_2006_2010..wf_2022_2026
  - 3 cost scenarios: optimistic_0.20_RT / baseline_0.40_RT / pessimistic_0.60_RT
  - Total 18 backtests
  - Engine cfg derived FROM manifest design (inherits α1 signal hypothesis
    + adds α1.1 turnover_mechanics block: hold_continuation + rank_buffer + budget=1).

This runner mirrors `scripts/run_v3c_alpha1.py` (Junyan ratify #2/#13: cost
scenario dispatch + multi-bench bundle). The key addition is the
`turnover_mechanics` block in manifest.design.portfolio that maps to engine
knobs `hold_continuation_enabled`, `turnover_budget_per_rebal`,
`rank_buffer_top_n`, `same_day_rebuy` (introduced in
`scripts/run_swing_backtest_fast.py` for the v3 Phase B α1.1 milestone).

Per Junyan 2026-05-28 PM5 success criteria:
  Mechanics pass (α1.1's own milestone) — audit.turnover_annual_ratio ≤ 3.0
                                          + audit.same_day_rebuy_count ≈ 0
                                          + audit.untouched_carry_over_avg > 2.0
                                          + audit.full_refresh_rate < 0.30
  Strategy gate pass (v3 §2 unchanged)   — IMPL4 turnover_annual_ratio ≤ 2.0
                                          + all WF/IMPL/AUD gates
  If mechanics pass but strategy fail → verdict = mechanics-only-progress,
                                        NOT paper. Transition to α1.2 turnover
                                        compression.

Usage:
    python3 scripts/run_v3c_alpha1_1.py
        [--manifest <path>]
        [--out-dir <path>]
        [--liquid-top-n N]
        [--skip-eval]

Exit codes:
    0 = runner OK (gate eval may still report FAIL — honest result)
    1 = runner-side error (file/spec/hash inconsistency)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_swing_backtest_fast import (run_swing_backtest_fast, COST_SCENARIOS,
                                       DEFAULT_SIGNAL_WEIGHTS)
from sector_scorer import load_sector_map
from run_iter17_r2 import compute_raw_alpha, compute_same_gross_alpha
from v3_manifest_hash import compute_hash


MANIFEST_DEFAULT = (REPO_ROOT / "experiments" / "agent_tasks"
                    / "variant_manifests" / "v3c_alpha1_1_20260528.json")


def _normalize_window_dates(start: str, end: str) -> tuple[str, str]:
    """Normalize YYYY-MM-DD or YYYYMMDD → return (yyyy-mm-dd, yyyy-mm-dd)."""
    def _norm(d: str) -> str:
        s = str(d).strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        return s
    return _norm(start), _norm(end)


def _config_from_manifest(manifest: dict, cost_scenario: str) -> dict:
    """Map manifest.design + cost_scenario → engine cfg dict (α1.1 path).

    Mirrors run_v3c_alpha1._config_from_manifest but adds the α1.1
    turnover_mechanics block (hold_continuation_enabled / rank_buffer_top_n /
    turnover_budget_per_rebal / same_day_rebuy) and disables time_stop by
    sentinel (engine prefers hold_continuation rank check when enabled).
    """
    design = manifest.get("design", {})
    factor_inputs = design.get("factor_inputs", [])
    portfolio = design.get("portfolio", {})
    risk = design.get("risk_rules", {})

    # Build factor_directions + signal_weights_override from factor_inputs.
    DIR_MAP = {"inverse": -1, "direct": +1, "neutral": 0, "skip": 0}
    factor_directions = {}
    signal_weights = {}
    for fi in factor_inputs:
        name = fi["name"]
        direction = DIR_MAP.get(fi.get("direction", "neutral").lower(), 0)
        weight = float(fi.get("weight", 0.0))
        factor_directions[name] = direction
        signal_weights[name] = weight

    # α1.1 turnover mechanics block — engine knobs.
    tm = portfolio.get("turnover_mechanics", {}) or {}

    cfg = {
        # Cost dispatch.
        "cost_scenario": cost_scenario,

        # v3 Phase B-fix: disable permanent drawdown breaker for research.
        "disable_drawdown_breaker": bool(risk.get("disable_drawdown_breaker", True)),

        # Factor wiring.
        "factor_directions": factor_directions,
        "signal_weights_override": signal_weights,
        "_invert_signal": False,
        "entry_composite_threshold": 50.0,

        # Rebal + hold cadence (α1 inheritance).
        "rebal_cadence": int(portfolio.get("rebalance_cadence_days", 10)),

        # α1.1 mechanics: hold_continuation supersedes time_stop. Engine still
        # accepts time_stop_days but the hold_continuation branch never
        # consults it. Sentinel 9999 documents that fact.
        "time_stop_days": int(portfolio.get("holding_period_days", 10))
                          if not tm.get("hold_continuation_enabled") else 9999,
        "_only_time_stop": False,             # α1.1: defer to hold_continuation
        "hard_stop_pct": float(risk.get("hard_stop_pct", -0.08)),
        "trailing_stop_pct": -99.0,
        "take_profit_full": 999.0,
        "take_profit_pct": 999.0,
        "structure_break_threshold": -1.0,

        # α1.1 turnover mechanics (Junyan 2026-05-28 PM5 ratify).
        "hold_continuation_enabled": bool(tm.get("hold_continuation_enabled", False)),
        "turnover_budget_per_rebal": int(tm.get("turnover_budget_per_rebal", 1))
                                      if tm.get("turnover_budget_per_rebal") is not None else None,
        "rank_buffer_top_n": int(tm.get("rank_buffer_top_n", 20))
                              if tm.get("rank_buffer_top_n") is not None else None,
        "same_day_rebuy": bool(tm.get("same_day_rebuy", True)),
        # v3 α1.3A anti-drift cap (Junyan 2026-05-29): force-exit a position held
        # ≥ max_hold_days, preventing the α1.2 quasi-buy-and-hold drift. None
        # (α1/α1.1/α1.2) = no cap → behavior unchanged (backward-compatible).
        "max_hold_days": (int(tm["max_hold_days"])
                          if tm.get("max_hold_days") is not None else None),

        # Sizing (per manifest portfolio).
        "max_positions": int(portfolio.get("max_positions", 8)),
        "top_n_picks": int(portfolio.get("target_positions", 8)),
        "max_gross": float(portfolio.get("max_gross", 0.50)),
        "max_single_name_weight": float(portfolio.get("max_single_name_weight", 0.08)),
        "safety_max_single_name": float(portfolio.get("max_single_name_weight", 0.08)) * 1.25,
        "vol_per_position": 0.02,
        "max_sector_weight": float(portfolio.get("max_sector_weight", 0.30)),

        # Universe.
        "use_quality_filter": False,
        "_sector_top_k": 99,
    }
    return cfg


def _run_one(window_name: str, start: str, end: str, cost_scenario: str,
             panel: pd.DataFrame, sector_map: dict, capital: float,
             liquid_top_n: int, manifest: dict, out_dir: Path) -> dict:
    """Run one (window, cost_scenario) backtest."""
    e_start, e_end = _normalize_window_dates(start, end)
    cfg = _config_from_manifest(manifest, cost_scenario)

    t0 = time.time()
    res = run_swing_backtest_fast(
        panel, sector_map, e_start, e_end,
        capital=capital, config=cfg,
        verbose=False, liquid_top_n=liquid_top_n,
    )
    elapsed = time.time() - t0
    if res.get("_status") == "insufficient_data":
        print(f"  ! {window_name}/{cost_scenario}: insufficient_data — skipping")
        return None

    bench_curve = res.get("bench_curve") or (res.get("benchmarks", {}).get("ew_500", []))
    raw_alpha = compute_raw_alpha(res["equity_curve"], bench_curve)
    sg_alpha = compute_same_gross_alpha(res["equity_curve"], bench_curve, gross_floor=0.05)

    audit = res.get("audit", {})
    sg_point_str = f"{sg_alpha['point']:+.4f}" if sg_alpha else "n/a"
    print(f"  {window_name}/{cost_scenario}: CAGR={res.get('cagr',0)*100:+6.2f}% "
          f"DD={res.get('max_drawdown',0)*100:+5.1f}% "
          f"gross={(audit.get('avg_gross_pct') or 0)*100:5.1f}% "
          f"turnover={audit.get('turnover_annual_ratio',0)*100:7.1f}% "
          f"trades={res.get('n_total_trades')} "
          f"untch={audit.get('untouched_carry_over_avg',0):.2f} "
          f"full_ref={audit.get('full_refresh_rate',0)*100:5.1f}% "
          f"sg_α_point={sg_point_str} "
          f"[{elapsed:.1f}s]")

    out_path = out_dir / f"v3c_alpha1_1_{window_name}_{cost_scenario}.json"
    res_with = {
        **res,
        "v3c_alpha1_1_window": window_name,
        "v3c_alpha1_1_cost_scenario": cost_scenario,
        "v3c_alpha1_1_period": [e_start, e_end],
        "alpha": {"raw": raw_alpha, "same_gross": sg_alpha},
    }
    out_path.write_text(json.dumps(res_with, indent=2, ensure_ascii=False, default=str))

    bundle_row = {
        "variant": "v3c_alpha1_1",
        "window": window_name,
        "cost_scenario": cost_scenario,
        "period": [e_start, e_end],
        "cagr": res.get("cagr"),
        "sharpe_annualized": res.get("sharpe_annualized"),
        "max_drawdown": res.get("max_drawdown"),
        "avg_gross": res.get("avg_gross"),
        "median_gross": res.get("median_gross"),
        "avg_n_positions": res.get("avg_n_positions"),
        "median_n_positions": res.get("median_n_positions"),
        "max_n_positions": res.get("max_n_positions"),
        "n_total_trades": res.get("n_total_trades"),
        "annualized_trades": res.get("annualized_trades"),
        "audit": audit,
        "alpha": {"raw": raw_alpha, "same_gross": sg_alpha},
    }
    return bundle_row


def _aggregate_bundle(rows: list[dict], manifest: dict, manifest_path: Path,
                      bundle_path: Path) -> dict:
    """Aggregate per-(window,scenario) rows into the v3_gate_eval bundle shape."""
    baseline_rows = [r for r in rows if r.get("cost_scenario") == "baseline_0.40_RT"]
    if not baseline_rows:
        raise RuntimeError("No baseline_0.40_RT rows produced; cannot build bundle.")

    bench_source = None
    for r in baseline_rows:
        if r.get("window") in ("full_20yr", "20yr", "full"):
            bench_source = r
            break
    if bench_source is None:
        bench_source = baseline_rows[0]

    bench_dict = {}
    bench_file = (bundle_path.parent
                  / f"v3c_alpha1_1_{bench_source['window']}_{bench_source['cost_scenario']}.json")
    if bench_file.exists():
        with open(bench_file) as f:
            full_res = json.load(f)
        bench_dict = full_res.get("benchmarks", {})

    manifest_hash = manifest.get("variant", {}).get("hypothesis_lock_hash", "")

    bundle = {
        "_meta": {
            "variant_id": manifest.get("variant", {}).get("variant_id"),
            "manifest_path": str(manifest_path),
            "manifest_hash": manifest_hash,
            "created_at": rows[0]["audit"].get("created_at") if rows else None,
            "n_windows_baseline": len(baseline_rows),
            "n_runs_total": len(rows),
            "cost_scenarios_run": sorted({r["cost_scenario"] for r in rows}),
            "benchmarks_reported": ["EW-500 same-gross", "CSI300", "CSI500",
                                     "CSI1000", "cash_2pct"],
            "causal_validation": manifest.get("variant", {}).get("causal_logic_label", ""),
            "numbers_validation": (
                "Specific numbers reported AS-RUN; no curve-fit. v3 §2 hard "
                "gates evaluated separately via scripts/v3_gate_eval.py. "
                "α1.1 mechanics gates (turnover ≤ 3.0, untouched > 2.0, "
                "full_refresh < 0.30, same_day_rebuy = 0) are evaluated in "
                "the runner report — they are NOT enforced by v3_gate_eval."
            ),
        },
        "results": baseline_rows,
        "cost_scenario_runs": rows,
        "cost_scenario": "baseline_0.40_RT",
        "benchmarks": bench_dict,
    }
    bundle_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False, default=str))
    return bundle


def _verify_manifest_hash(manifest: dict) -> bool:
    stored = manifest.get("variant", {}).get("hypothesis_lock_hash", "")
    if not stored:
        return False
    return stored == compute_hash(manifest)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="V3C-α1.1 backtest runner (turnover mechanics).",
    )
    parser.add_argument("--manifest", type=str, default=str(MANIFEST_DEFAULT))
    parser.add_argument("--prices", type=str,
                        default=str(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet"))
    parser.add_argument("--sector-map", type=str,
                        default=str(REPO_ROOT / "data_history" / "sector_mapping.json"))
    parser.add_argument("--out-dir", type=str,
                        default=str(REPO_ROOT / "public" / "data"))
    parser.add_argument("--capital", type=float, default=10_000_000.0)
    parser.add_argument("--liquid-top-n", type=int, default=None)
    parser.add_argument("--windows", type=str, default=None)
    parser.add_argument("--cost-scenarios", type=str, default=None)
    parser.add_argument("--skip-eval", action="store_true")
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    with open(manifest_path) as f:
        manifest = json.load(f)

    if not _verify_manifest_hash(manifest):
        stored = manifest.get("variant", {}).get("hypothesis_lock_hash", "")
        computed = compute_hash(manifest)
        print(f"ERROR: manifest hash mismatch — manifest tampered", file=sys.stderr)
        print(f"  stored:   {stored}", file=sys.stderr)
        print(f"  computed: {computed}", file=sys.stderr)
        return 1
    print(f"[runner] manifest hash verified: {manifest['variant']['hypothesis_lock_hash']}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    test_plan = manifest.get("test_plan", {})
    all_windows = test_plan.get("windows", [])
    if args.windows:
        wanted = set(args.windows.split(","))
        windows = [w for w in all_windows if w.get("name") in wanted]
    else:
        windows = all_windows
    all_scenarios = test_plan.get("cost_scenarios", list(COST_SCENARIOS.keys()))
    if args.cost_scenarios:
        wanted = set(args.cost_scenarios.split(","))
        scenarios = [s for s in all_scenarios if s in wanted]
    else:
        scenarios = all_scenarios

    for s in scenarios:
        if s not in COST_SCENARIOS:
            print(f"ERROR: unknown cost_scenario {s!r}; valid: "
                  f"{sorted(COST_SCENARIOS.keys())}", file=sys.stderr)
            return 1

    print(f"[runner] panel: {args.prices}")
    print(f"[runner] sector_map: {args.sector_map}")
    print(f"[runner] capital: ¥{args.capital:,.0f}")
    print(f"[runner] windows ({len(windows)}): {[w['name'] for w in windows]}")
    print(f"[runner] scenarios ({len(scenarios)}): {scenarios}")
    print(f"[runner] total runs: {len(windows) * len(scenarios)}")

    # α1.1 mechanics confirmation print.
    tm = (manifest.get("design", {}).get("portfolio", {}).get("turnover_mechanics") or {})
    print(f"[runner] α1.1 turnover_mechanics:")
    print(f"           hold_continuation_enabled = {tm.get('hold_continuation_enabled')}")
    print(f"           rank_buffer_top_n         = {tm.get('rank_buffer_top_n')}")
    print(f"           turnover_budget_per_rebal = {tm.get('turnover_budget_per_rebal')}")
    print(f"           same_day_rebuy            = {tm.get('same_day_rebuy')}")
    print()

    liquid_top_n = args.liquid_top_n
    if liquid_top_n is None:
        liquid_top_n = int(
            manifest.get("design", {}).get("universe", {}).get("liquid_top_n", 500)
        )

    if "momentum_20d" not in DEFAULT_SIGNAL_WEIGHTS:
        print("ERROR: engine missing momentum_20d in DEFAULT_SIGNAL_WEIGHTS",
              file=sys.stderr)
        return 1

    print(f"[runner] loading panel...")
    panel = pd.read_parquet(args.prices)
    sector_map = load_sector_map(args.sector_map)
    print(f"[runner] panel: {len(panel):,} rows × "
          f"{panel['ts_code'].nunique()} tickers")
    print()

    rows = []
    grid_start = time.time()
    for w_def in windows:
        wname = w_def["name"]
        start = w_def["start"]
        end = w_def["end"]
        print(f"\n=== window {wname} ({start} → {end}) ===")
        for s in scenarios:
            row = _run_one(wname, start, end, s, panel, sector_map,
                           args.capital, liquid_top_n, manifest, out_dir)
            if row is not None:
                rows.append(row)
    grid_elapsed = time.time() - grid_start
    print(f"\n[runner] {len(rows)} backtests completed in {grid_elapsed:.1f}s "
          f"({grid_elapsed/max(len(rows),1):.1f}s/run avg)")

    bundle_path = out_dir / "v3c_alpha1_1_bundle.json"
    bundle = _aggregate_bundle(rows, manifest, manifest_path, bundle_path)
    print(f"[runner] wrote bundle: {bundle_path}")

    # Summary table.
    print("\n=== V3C-α1.1 baseline-cost summary ===")
    print(f"{'Window':<14}{'CAGR':>9}{'MaxDD':>9}{'Gross':>8}{'Turn':>10}"
          f"{'Untch':>8}{'FullRef':>9}{'SameDay':>9}"
          f"{'Trades':>8}{'sg_α point':>14}")
    print("-" * 110)
    for r in bundle["results"]:
        sg = (r.get("alpha") or {}).get("same_gross") or {}
        a = r.get("audit") or {}
        print(f"{r['window']:<14}"
              f"{(r.get('cagr') or 0)*100:+8.2f}%"
              f"{(r.get('max_drawdown') or 0)*100:+8.1f}%"
              f"{(r.get('avg_gross') or 0)*100:+7.1f}%"
              f"{(a.get('turnover_annual_ratio') or 0)*100:+9.1f}%"
              f"{(a.get('untouched_carry_over_avg') or 0):>+8.2f}"
              f"{(a.get('full_refresh_rate') or 0)*100:+8.1f}%"
              f"{a.get('same_day_rebuy_count', 0):>+9d}"
              f"{r.get('n_total_trades',0):>8}"
              f"{(sg.get('point',0) if sg else 0):+14.4f}")
    print()

    print("=== V3C-α1.1 full_20yr across cost scenarios ===")
    print(f"{'Scenario':<22}{'CAGR':>9}{'MaxDD':>9}{'Turn':>9}"
          f"{'sg_α point':>14}")
    print("-" * 65)
    full_rows = [r for r in rows if r["window"] in ("full_20yr", "20yr", "full")]
    for r in sorted(full_rows, key=lambda x: x["cost_scenario"]):
        sg = (r.get("alpha") or {}).get("same_gross") or {}
        a = r.get("audit") or {}
        print(f"{r['cost_scenario']:<22}"
              f"{(r.get('cagr') or 0)*100:+8.2f}%"
              f"{(r.get('max_drawdown') or 0)*100:+8.1f}%"
              f"{(a.get('turnover_annual_ratio') or 0)*100:+8.1f}%"
              f"{(sg.get('point',0) if sg else 0):+14.4f}")
    print()

    if args.skip_eval:
        print("[runner] --skip-eval set; not invoking v3_gate_eval.")
        return 0

    print("=== Invoking v3_gate_eval ===")
    import subprocess
    cmd = [
        sys.executable, str(REPO_ROOT / "scripts" / "v3_gate_eval.py"),
        "--variant", "v3c_alpha1_1_20260528_turnover_mechanics",
        "--manifest", str(manifest_path),
        "--result", str(bundle_path),
        "--out-md", "/tmp/v3c_gate/v3c_alpha1_1_gate_eval.md",
        "--out-json", "/tmp/v3c_gate/v3c_alpha1_1_gate_eval.json",
    ]
    Path("/tmp/v3c_gate").mkdir(parents=True, exist_ok=True)
    print("  $ " + " ".join(cmd))
    rc = subprocess.run(cmd).returncode
    print(f"[runner] v3_gate_eval exit={rc} "
          f"({'PASS' if rc == 0 else 'FAIL (gates) — see report'})")

    eval_md = Path("/tmp/v3c_gate/v3c_alpha1_1_gate_eval.md")
    if eval_md.exists():
        print()
        print("=== v3_gate_eval markdown ===")
        print(eval_md.read_text())

    return 0


if __name__ == "__main__":
    sys.exit(main())
