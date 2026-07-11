#!/usr/bin/env python3
"""quant_c1_verdict.py — C1 family verdict orchestrator (low-turnover quality+low_vol tilt).

Implements docs/strategy/QUANT_C1_LOWTURNOVER_TILT_SPEC.md (Junyan-RATIFIED 2026-06-10:
K=20 · claim gate = CSI300 AND EW dual-pass · family = C1a/C1b/C1c + random control, exactly).
Reuses the validated Factory B machinery verbatim (quant_verdict helpers + quant_backtest engine).

Family (locked; NO post-hoc variants — all-fail => family killed; revisions = a NEW manifest C2):
  c1a_rebal40        rebal 40td, top-20, full re-rank
  c1b_rebal20_buffer rebal 20td, top-20, rank-exit buffer 2xK (sell only when rank > 40)
  c1c_rebal60        rebal 60td, top-20
  random_control     rebal 40td, top-20, seeded-random ranking over the SAME eligible pool
BY multiple-testing across {c1a,c1b,c1c} (m=3; the control is a control).

Discipline: survivorship gate FIRST; manifest sha256-locked BEFORE any run; per-candidate-arm
19-gate runs (incl. the 3-scenario cost grid each); claim per arm = ci_positive_after_cost vs
CSI300 AND EW + WF1 >=3/5 + exact-name OOS (wf_2022_2026) not sig-neg + gates PASS. The honest
prior (in the manifest): most likely outcome is premia-not-alpha => no-claim/kill.

Local/backtest-only. Output: public/data/quant_c1_verdict.json + quant_c1_manifest.json.
Usage: python3 scripts/quant_c1_verdict.py [--selftest]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import quant_backtest as qb                                  # noqa: E402
import survivorship_gate                                     # noqa: E402
from v3_gate_eval import run_all_gates                       # noqa: E402
from quant_verdict import (                                  # noqa: E402
    by_adjust, _alpha_block, _point_only_alpha, _index_curve, _cash_curve,
    _ew_returns, _ew_curve, _slice_benches, _window_entry, _select_oos_window,
    _now, _git_commit, _md5_file, _engine_version,
    WINDOWS, COST_SCENARIOS, BENCH_INDEX, OOS_WINDOW_NAME,
)

OUT = D / "quant_c1_verdict.json"
MANIFEST_OUT = D / "quant_c1_manifest.json"
VARIANT_ID = "quant_c1_lowturnover_tilt"
TOP_K = 20                                  # Junyan-ratified
RANDOM_CONTROL_SEED = 42

ARMS = {                                    # the LOCKED family — exactly these, nothing post-hoc
    "c1a_rebal40":        {"rebal_days": 40, "top_k": TOP_K},
    "c1b_rebal20_buffer": {"rebal_days": 20, "top_k": TOP_K, "rank_buffer_mult": 2.0},
    "c1c_rebal60":        {"rebal_days": 60, "top_k": TOP_K},
    "random_control":     {"rebal_days": 40, "top_k": TOP_K, "random_seed": RANDOM_CONTROL_SEED},
}
CANDIDATES = ["c1a_rebal40", "c1b_rebal20_buffer", "c1c_rebal60"]   # BY family m=3

HYPOTHESIS = ("C1: on the liquid top-500 A-share universe, an equal-weight top-20 portfolio ranked "
              "by the value(E/P)+low_vol z-composite, rebalanced at low cadence with a rank-exit "
              "buffer so annual book turnover stays <= 2.0x, delivers post-cost same-gross alpha "
              "whose bootstrap CI clears zero vs BOTH CSI300 and EW-liquid, full-sample and "
              "walk-forward.")
EXPECTED_FAILURE_MODES = [
    "premia-not-alpha (most likely): vs-EW CI keeps straddling zero -> kill and close the line",
    "concentration noise: top-K idiosyncratic noise swamps the weak IC",
    "stale-rank decay: lower cadence -> composite information decays before the next rebalance",
    "low_vol crowding post-2017 -> the premium thins exactly when measurable",
]


def run_c1() -> dict:
    import pandas as pd
    t0 = time.time()
    gate = survivorship_gate.require_pass()             # HARD PRECONDITION
    print(f"[c1] survivorship gate PASS ({time.time()-t0:.0f}s)")

    lock = hashlib.sha256((HYPOTHESIS + json.dumps(ARMS, sort_keys=True)
                           + f"K={TOP_K}").encode()).hexdigest()
    manifest = {
        "schema": "v3_variant_manifest",
        "variant": {"variant_id": VARIANT_ID, "registered_at": _now(),
                    "hypothesis": HYPOTHESIS,
                    "causal_logic_label": ("unestablished — value/low_vol IC is real [validated "
                                           "against data]; that a low-cost tilt converts it into "
                                           "net alpha (not premia) is the unproven step"),
                    "expected_failure_modes": EXPECTED_FAILURE_MODES,
                    "hypothesis_lock_hash": lock},
        "test_plan": {"windows": [{"name": n, "start": s, "end": e} for n, s, e in WINDOWS],
                      "cost_scenarios": list(COST_SCENARIOS.keys()),
                      "benchmarks": ["csi300", "zz500", "csi1000", "ew500", "cash2pct"],
                      "arms": ARMS, "family_for_multiple_testing": CANDIDATES,
                      "claim_gate": ("ci_positive_after_cost vs CSI300 AND EW + WF1 + exact-name OOS "
                                     "not sig-neg + 19-gate PASS (Junyan-ratified, strict)")},
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"[c1] manifest pre-registered -> {MANIFEST_OUT.name} lock={lock[:12]}")

    panel = pd.read_parquet(qb.PANEL, columns=["ts_code", "trade_date", "open", "high", "low",
                                               "close", "vol", "amount", "pre_close"])
    panel = panel[panel["ts_code"].map(lambda t: isinstance(t, str) and t.endswith((".SZ", ".SH")))]
    panel["trade_date"] = panel["trade_date"].astype(str)
    trade_dates = sorted(panel["trade_date"].unique())
    idx = qb.PanelIndex(panel)
    qb._IND_CACHE.clear()
    liquid = qb.compute_liquid_universe(panel, top_n=qb.TOP_N_ADV, lookback_days=qb.LOOKBACK,
                                        min_dollar_vol=qb.MIN_DVOL)
    print(f"[c1] panel {len(panel):,} rows / universe built ({time.time()-t0:.0f}s)")

    full_name, full_start, full_end = WINDOWS[0]
    full_win = [d for d in trade_dates if full_start <= d <= full_end]
    ew_ret = _ew_returns(panel, liquid)
    bench_full = {
        "csi300": _index_curve(BENCH_INDEX["csi300"], full_win, qb.CAPITAL),
        "zz500": _index_curve(BENCH_INDEX["zz500"], full_win, qb.CAPITAL),
        "csi1000": _index_curve(BENCH_INDEX["csi1000"], full_win, qb.CAPITAL),
        "ew500": _ew_curve(ew_ret, full_win, qb.CAPITAL),
        "cash2pct": _cash_curve(full_win, qb.CAPITAL),
    }
    hashes = {"config_hash": lock, "data_hash": _md5_file(qb.PANEL),
              "git_commit": _git_commit(), "engine_version": _engine_version()}
    print(f"[c1] 5 benchmarks built ({time.time()-t0:.0f}s)")

    def _run(arm, start, end, cost=None):
        p = ARMS[arm]
        return qb.run_tilt_arm(panel, idx, liquid, trade_dates, start, end, cost=cost,
                               rebal_days=p["rebal_days"], top_k=p["top_k"],
                               rank_buffer_mult=p.get("rank_buffer_mult"),
                               random_seed=p.get("random_seed"))

    arms_results, cost_scenario_runs = {}, {}
    full_res_by_arm = {}
    for arm in ARMS:
        entries = []
        for name, s, e in WINDOWS:
            ts = time.time()
            win = [d for d in trade_dates if s <= d <= e]
            res = _run(arm, s, e)
            if name == full_name:
                full_res_by_arm[arm] = res
            benches_w = _slice_benches(bench_full, win)
            entries.append(_window_entry(name, res, benches_w, qb.CAPITAL, hashes,
                                         wf_light=name.startswith("wf_")))
            print(f"[c1] {arm:<19} {name:<15} {len(win)}d trades={len(res['trades'])} "
                  f"turn={entries[-1]['audit']['turnover_annual_ratio']} "
                  f"({time.time()-ts:.0f}s; total {time.time()-t0:.0f}s)")
        arms_results[arm] = entries
    # cost grids (IMPL7) per CANDIDATE arm on the full window
    for arm in CANDIDATES:
        runs = []
        for key, cost in COST_SCENARIOS.items():
            if key == "baseline_0.40_RT":
                a = arms_results[arm][0]["alpha"]["same_gross"]
                runs.append({"window": full_name, "cost_scenario": key,
                             "alpha": {"same_gross": {"point": a.get("point")}}})
                continue
            ts = time.time()
            res = _run(arm, full_start, full_end, cost=cost)
            pa = _point_only_alpha(res["equity_curve"], bench_full["csi300"], qb.CAPITAL)
            runs.append({"window": full_name, "cost_scenario": key,
                         "alpha": {"same_gross": {"point": pa["point"]}}})
            print(f"[c1] {arm} cost-grid {key} point={pa['point']} ({time.time()-ts:.0f}s)")
        cost_scenario_runs[arm] = runs

    # BY across the candidate family (full-sample p vs CSI300 same-gross)
    fam_p = {a: (arms_results[a][0]["alpha"]["same_gross"] or {}).get("p_value") for a in CANDIDATES}
    fam_adj = by_adjust(fam_p)

    # per-candidate 19-gate + criteria + claim
    per_arm = {}
    for arm in CANDIDATES:
        same_gross_bench_curves = {}
        for k in ("csi300", "zz500", "csi1000", "ew500"):
            same_gross_bench_curves[k + "_same_gross"] = qb._same_gross_curve(
                bench_full[k], full_res_by_arm[arm]["equity_curve"], qb.CAPITAL)
        same_gross_bench_curves["cash2pct"] = bench_full["cash2pct"]
        result_for_gates = {
            "_meta": {"created_at": _now(),
                      "benchmarks_reported": ["csi300", "zz500", "csi1000", "ew500", "cash2pct"]},
            "results": arms_results[arm],
            "benchmarks": same_gross_bench_curves,
            "cost_scenario_runs": cost_scenario_runs[arm],
        }
        gates = run_all_gates(result_for_gates, manifest, VARIANT_ID,
                              family_corrected_p=fam_adj.get(arm), stage="R&D")
        full = arms_results[arm][0]["alpha"]
        wf = [w for w in arms_results[arm] if w["window"].startswith("wf_")]
        wf_pos = sum(1 for w in wf if (w["alpha"]["same_gross"].get("point") or 0) >= 0)
        oos = _select_oos_window(wf)
        crit = {
            "ci_positive_after_cost_vs_csi300": bool(full["same_gross"].get("ci_positive_after_cost")),
            "ci_positive_after_cost_vs_ew500": bool((full.get("same_gross_vs_ew500") or {}).get("ci_positive_after_cost")),
            "wf1_3of5_positive": bool(wf_pos >= 3 and len(wf) >= 5),
            "oos_2022_2026_not_sig_neg": bool(oos and not (oos["alpha"]["same_gross"].get("ci_negative_after_cost"))),
            "gates_overall_pass": gates.get("verdict") == "PASS",
            "by_family_adjusted_p": fam_adj.get(arm),
        }
        per_arm[arm] = {"criteria": crit,
                        "claim_permitted": all(v for k, v in crit.items() if isinstance(v, bool)),
                        "wf_positive_windows": f"{wf_pos}/{len(wf)}",
                        "gates": {"verdict": gates.get("verdict"),
                                  "failed_gate_ids": gates.get("failed_gate_ids"),
                                  "gate_outcomes": gates.get("gate_outcomes")}}

    any_claim = any(per_arm[a]["claim_permitted"] for a in CANDIDATES)
    all_sig_neg = all((arms_results[a][0]["alpha"]["same_gross"] or {}).get("ci_negative_after_cost")
                      for a in CANDIDATES)
    if any_claim:
        rec = "CLAIM-CANDIDATE — at least one arm passed the full gate (pending Junyan ratification)"
    elif all_sig_neg:
        rec = "KILL — every candidate arm significantly negative"
    else:
        rec = ("NO-CLAIM — no arm clears the dual-benchmark claim gate; the low-turnover premia "
               "line's answer per the spec (kill/iterate is Junyan's call)")

    report = {
        "_meta": {"layer": "Quant Strategy Factory — C1 family FORMAL verdict run",
                  "spec": "docs/strategy/QUANT_C1_LOWTURNOVER_TILT_SPEC.md",
                  "generated_at": _now(), "elapsed_sec": round(time.time() - t0, 1),
                  "universe_source": "panel_derived_compute_liquid_universe",
                  "universe_pit_used": False,
                  "survivorship_gate": {"passed": gate.get("passed")},
                  "benchmarks_reported": ["csi300", "zz500", "csi1000", "ew500", "cash2pct"],
                  "disclaimer": ("UNVALIDATED unless an arm's claim_permitted=true AND Junyan "
                                 "ratifies. Family is LOCKED — no post-hoc variants; revisions are "
                                 "a NEW manifest (C2).")},
        "manifest_hash": lock,
        "arms": arms_results,
        "cost_scenario_runs": cost_scenario_runs,
        "by_multiple_testing": {"family": CANDIDATES, "raw_p": fam_p, "adjusted_p": fam_adj},
        "per_arm_verdict": per_arm,
        "family_verdict": {"any_claim_permitted": bool(any_claim), "recommendation": rec},
        "validation_status": "unvalidated" if not any_claim else "claim_candidate_pending_human",
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"[c1] wrote {OUT} ({time.time()-t0:.0f}s total)")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    rep = run_c1()
    print("=" * 78)
    print(f"C1 FAMILY VERDICT (any_claim={rep['family_verdict']['any_claim_permitted']})")
    print("=" * 78)
    for arm in rep["arms"]:
        f = rep["arms"][arm][0]
        a_, ew = f["alpha"]["same_gross"], f["alpha"].get("same_gross_vs_ew500", {})
        pv = rep["per_arm_verdict"].get(arm, {})
        print(f"  [{arm:<19}] vs CSI300: {a_.get('point')} CI=[{a_.get('lo')},{a_.get('hi')}] p={a_.get('p_value')}")
        print(f"  {'':<21} vs EW:     {ew.get('point')} CI=[{ew.get('lo')},{ew.get('hi')}] | "
              f"turn={f['audit']['turnover_annual_ratio']} MaxDD={f['max_drawdown']:.3f} "
              f"trades={f['n_total_trades']}"
              + (f" | wf+ {pv.get('wf_positive_windows')} gates={pv.get('gates', {}).get('verdict')} "
                 f"claim={pv.get('claim_permitted')}" if pv else " | (control)"))
    print(f"  RECOMMENDATION: {rep['family_verdict']['recommendation']}")
    return 0


def _selftest() -> int:
    errs = []
    # family contract: exactly the ratified arms, K=20 everywhere, control seeded
    if set(ARMS) != {"c1a_rebal40", "c1b_rebal20_buffer", "c1c_rebal60", "random_control"}:
        errs.append("C1 family must be exactly the ratified 3 candidates + random control")
    if any(p["top_k"] != 20 for p in ARMS.values()):
        errs.append("K=20 is Junyan-ratified for every arm")
    if ARMS["c1b_rebal20_buffer"].get("rank_buffer_mult") != 2.0:
        errs.append("C1b rank buffer must be 2.0xK")
    if ARMS["random_control"].get("random_seed") is None:
        errs.append("random control must be seeded (deterministic)")
    if CANDIDATES != ["c1a_rebal40", "c1b_rebal20_buffer", "c1c_rebal60"]:
        errs.append("BY family must be the 3 candidates only (control excluded)")
    # cost-scenario + OOS contracts (reuse the trap-tested helpers)
    if set(COST_SCENARIOS) != {"optimistic_0.20_RT", "baseline_0.40_RT", "pessimistic_0.60_RT"}:
        errs.append("cost scenario keys must match the IMPL7 gate strings")
    sel = _select_oos_window([{"window": "wf_2018_2022"}, {"window": OOS_WINDOW_NAME}])
    if not sel or sel["window"] != OOS_WINDOW_NAME:
        errs.append("OOS selection must be exact-name (regression)")
    # engine: rank-buffer + random-control determinism on a tiny synthetic
    import pandas as pd
    dates = [f"D{i:03d}" for i in range(140)]
    rows = []
    for i, dt in enumerate(dates):
        for j in range(8):
            sm = j < 4                                # 4 smooth names, 4 volatile names
            base = 10.0 + j
            px = base + (0.01 * i if sm else (1.5 if i % 2 else -1.5) + 0.01 * i)
            rows.append({"ts_code": f"{'SM' if sm else 'VO'}{j:02d}.SZ", "trade_date": dt,
                         "open": px, "high": px * 1.01, "low": px * 0.99, "close": px,
                         "vol": 1000.0, "amount": px * 1000.0 / 100.0, "pre_close": px})
    panel = pd.DataFrame(rows)
    idx = qb.PanelIndex(panel)
    liquid = qb.compute_liquid_universe(panel, top_n=8, lookback_days=10, min_dollar_vol=0)
    qb._IND_CACHE.clear()
    r1 = qb.run_tilt_arm(panel, idx, liquid, dates, dates[0], dates[-1], rebal_days=20, top_k=2,
                         random_seed=7)
    r2 = qb.run_tilt_arm(panel, idx, liquid, dates, dates[0], dates[-1], rebal_days=20, top_k=2,
                         random_seed=7)
    if [t["ticker"] for t in r1["trades"]] != [t["ticker"] for t in r2["trades"]]:
        errs.append("random control must be deterministic for the same seed")
    rb = qb.run_tilt_arm(panel, idx, liquid, dates, dates[0], dates[-1], rebal_days=20, top_k=2,
                         rank_buffer_mult=4.0)   # buffer covers the whole 8-name pool -> NO rebalance sells
    if any(t["reason"] == "rebalance_exit" for t in rb["trades"]):
        errs.append("a rank buffer covering the full pool must produce zero rebalance sells")
    nb = qb.run_tilt_arm(panel, idx, liquid, dates, dates[0], dates[-1], rebal_days=20, top_k=2)
    if not (len(rb["trades"]) <= len(nb["trades"])):
        errs.append("rank buffer must not INCREASE trade count vs no-buffer")
    if errs:
        print("quant_c1_verdict selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("quant_c1_verdict selftest PASSED (ratified family contract: 3 candidates + seeded control, "
          "K=20, C1b buffer 2xK, BY excludes the control; cost/OOS gate contracts; engine: random "
          "control deterministic per seed; full-pool rank buffer -> zero rebalance sells, buffer "
          "never increases trades)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
