#!/usr/bin/env python3
"""quant_verdict.py — Quant Strategy Factory v0 FORMAL VERDICT orchestrator (PR3b).

Runs the full multi-year, multi-arm, walk-forward backtest through the survivorship gate,
the cost-scenario grid, 5 benchmarks, stationary-bootstrap CIs, BY multiple-testing
correction, and the existing 19-gate suite (v3_gate_eval.run_all_gates) — then emits a
mechanical verdict per Junyan's criteria. THE HUMAN DECIDES; this only computes.

Discipline:
  - survivorship_gate.require_pass() FIRST (no number without it).
  - PRE-REGISTRATION: the manifest (hypothesis + thresholds + test plan, sha256-locked)
    is written BEFORE any run; PRE2 verifies registered_at < every window's created_at.
  - ALPHA-CLAIM GATE: ci_positive_after_cost (bootstrap CI lower bound > 0, after costs)
    vs BOTH CSI300 and EW — plus WF1 (>=3/5 windows positive), OOS-2022-2026 not
    significantly negative, and the 19-gate suite. Anything less => NO edge claim.

Arms:
  h1                 — the candidate (quality-filtered pullback-in-uptrend; live signal)
  quality_lowvol     — periodic-tilt BASELINE (the honest 'dumb tilt' H1 must beat)
  oversold_control   — NEGATIVE CONTROL (no uptrend filter; the dead family's neighborhood)
  h1_thesis_overlay  — H1 + Core-Thesis veto. Theses registered 2026-05-30 > panel end
                       2026-05-26 => IDENTICAL to h1 historically BY CONSTRUCTION; we run
                       its full window once to PROVE equality, not assume it. Forward-only.

Windows: full_2006_2026 + wf_2006_2010 / wf_2010_2014 / wf_2014_2018 / wf_2018_2022 / wf_2022_2026.
Cost grid (IMPL7, h1 full window): optimistic_0.20_RT (×0.5) / baseline_0.40_RT / pessimistic_0.60_RT (×1.5).

Local/backtest-only (gitignored parquet). Output: public/data/quant_v0_verdict.json (+ manifest).
Usage:  python3 scripts/quant_verdict.py [--quick] [--selftest]
        --quick = plumbing test (short windows, B=500). NOT a verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import quant_backtest as qb                     # noqa: E402  (the blessed engine)
from quant_strategy import THRESH               # noqa: E402
from v3_gate_eval import run_all_gates          # noqa: E402
import survivorship_gate                        # noqa: E402

OUT = D / "quant_v0_verdict.json"
MANIFEST_OUT = D / "quant_v0_manifest.json"
VARIANT_ID = "quant_v0_h1"

WINDOWS = [
    ("full_2006_2026", "20060104", "20260526"),
    ("wf_2006_2010", "20060104", "20091231"),
    ("wf_2010_2014", "20100101", "20131231"),
    ("wf_2014_2018", "20140101", "20171231"),
    ("wf_2018_2022", "20180101", "20211231"),
    ("wf_2022_2026", "20220101", "20260526"),
]
WINDOWS_QUICK = [                                  # plumbing test ONLY — never a verdict
    ("full_2022_2023", "20220104", "20231229"),
    ("wf_2022_2022", "20220104", "20221230"),
    ("wf_2023_2023", "20230103", "20231229"),
]

# Cost grid: scale the baseline cost vector (slippage/commission; stamp fixed by law).
# Labels MUST match the IMPL7 gate strings exactly. Approximate RT bands [unvalidated].
COST_SCENARIOS = {
    "optimistic_0.20_RT": {"slippage": qb.SLIPPAGE * 0.5, "commission": qb.COMMISSION * 0.5, "stamp": qb.STAMP_DUTY_SELL},
    "baseline_0.40_RT": {"slippage": qb.SLIPPAGE, "commission": qb.COMMISSION, "stamp": qb.STAMP_DUTY_SELL},
    "pessimistic_0.60_RT": {"slippage": qb.SLIPPAGE * 1.5, "commission": qb.COMMISSION * 1.5, "stamp": qb.STAMP_DUTY_SELL},
}
BENCH_INDEX = {"csi300": "000300.SH", "zz500": "000905.SH", "csi1000": "000852.SH"}
FAMILY = ["h1", "quality_lowvol", "oversold_control"]   # BY multiple-testing family (m=3)
CASH_RATE = 0.02


# ───────────────────────── helpers ─────────────────────────
def _now():
    return datetime.now(timezone.utc).isoformat()


def _git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                              capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _md5_file(p: Path):
    h = hashlib.md5()
    try:
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return "unavailable"


def _engine_version():
    h = hashlib.sha256()
    for f in ("quant_backtest.py", "quant_verdict.py", "quant_strategy.py"):
        try:
            h.update((Path(__file__).parent / f).read_bytes())
        except Exception:
            pass
    return h.hexdigest()[:12]


def by_adjust(pvals: dict) -> dict:
    """Benjamini–Yekutieli adjusted p-values. pvals: {name: p}. Returns {name: p_adj}."""
    items = [(k, v) for k, v in pvals.items() if v is not None]
    if not items:
        return {}
    m = len(items)
    c_m = sum(1.0 / i for i in range(1, m + 1))
    items.sort(key=lambda kv: kv[1])
    raw = [min(1.0, p * m * c_m / rank) for rank, (_, p) in enumerate(items, start=1)]
    # enforce monotone non-decreasing from the largest rank down
    for i in range(len(raw) - 2, -1, -1):
        raw[i] = min(raw[i], raw[i + 1])
    return {items[i][0]: raw[i] for i in range(len(items))}


def _ann(x):
    return None if x is None else round(float(x) * 252, 6)


def _index_curve(code: str, win, capital):
    import pandas as pd
    ix = pd.read_parquet(qb.INDEX, columns=["ts_code", "trade_date", "close"])
    ix = ix[ix["ts_code"] == code].sort_values("trade_date")
    by = {str(d): float(c) for d, c in zip(ix["trade_date"], ix["close"])}
    curve, eq, prev = [], capital, None
    for T in win:
        c = by.get(T)
        if c is not None and prev is not None and prev > 0:
            eq *= c / prev
        if c is not None:
            prev = c
        curve.append({"date": T, "equity": round(eq, 2)})
    return curve


def _cash_curve(win, capital, rate=CASH_RATE):
    eq, out = capital, []
    for T in win:
        eq *= 1.0 + rate / 252.0
        out.append({"date": T, "equity": round(eq, 2)})
    return out


def _ew_returns(panel, liquid):
    """EW daily return of each date's liquid members (close/pre_close - 1). {date: ret}."""
    import pandas as pd
    pairs = set()
    for T, tks in liquid.items():
        for tk in tks:
            pairs.add((str(T), tk))
    midx = pd.MultiIndex.from_arrays([panel["trade_date"], panel["ts_code"]])
    sub = panel[midx.isin(pairs)]
    sub = sub[(sub["pre_close"].notna()) & (sub["pre_close"] > 0)]
    r = (sub["close"] / sub["pre_close"] - 1.0)
    g = r.groupby(sub["trade_date"]).mean()
    return {str(k): float(v) for k, v in g.items()}


def _ew_curve(ew_ret, win, capital):
    eq, out = capital, []
    for T in win:
        eq *= 1.0 + ew_ret.get(T, 0.0)
        out.append({"date": T, "equity": round(eq, 2)})
    return out


def _alpha_block(strat_curve, bench_curve, capital, B=10000):
    """Same-gross alpha vs a benchmark curve: point/lo/hi annualized + p + claim gates."""
    sg = qb._same_gross_curve(bench_curve, strat_curve, capital)
    series = qb._alpha_series(strat_curve, sg)
    if len(series) < 30:
        return {"point": None, "n_dates": len(series), "_status": "too_few_obs"}
    from stationary_bootstrap import bootstrap_ci, mean as bs_mean
    r = bootstrap_ci(series, bs_mean, B=B, p=1 / 10, seed=42)
    if r.get("_status") != "ok":
        return {"point": None, "n_dates": len(series), "_status": r.get("_status")}
    lo, hi = float(r["ci_lo"]), float(r["ci_hi"])
    pt = float(r["point_estimate"])
    return {"point": _ann(pt), "lo": _ann(lo), "hi": _ann(hi),
            "p_value": r.get("p_value_h0_zero"), "n_dates": len(series),
            "ci_positive_after_cost": bool(lo > 0), "ci_negative_after_cost": bool(hi < 0)}


def _point_only_alpha(strat_curve, bench_curve, capital):
    sg = qb._same_gross_curve(bench_curve, strat_curve, capital)
    series = qb._alpha_series(strat_curve, sg)
    if not series:
        return {"point": None, "n_dates": 0}
    return {"point": _ann(sum(series) / len(series)), "n_dates": len(series)}


def _audit_fields(res, win_dates, hashes):
    curve = res["equity_curve"]
    grosses = [float(p.get("gross", 0.0) or 0.0) for p in curve]
    npos = sorted(int(p.get("n_positions", 0) or 0) for p in curve)
    navs = [p["nav"] for p in curve]
    yrs = max(len(curve) / 252.0, 1e-9)
    mean_nav = (sum(navs) / len(navs)) if navs else 0.0
    turn = (res.get("total_buy_notional", 0.0) / mean_nav / yrs) if mean_nav else None
    return {
        "created_at": _now(),
        "config_hash": hashes["config_hash"], "data_hash": hashes["data_hash"],
        "git_commit": hashes["git_commit"], "engine_version": hashes["engine_version"],
        "max_positions_enforced": True,
        "avg_gross_pct": round(sum(grosses) / len(grosses), 6) if grosses else None,
        "max_gross_pct": round(max(grosses), 6) if grosses else None,
        "median_n_positions": npos[len(npos) // 2] if npos else None,
        "turnover_annual_ratio": round(turn, 4) if turn is not None else None,
        "n_trade_days": len(curve),
        "n_total_trades_actual": len(res["trades"]),
    }


def _window_entry(name, res, benches, capital, hashes, wf_light=False):
    """One gate-contract window dict: alpha.same_gross (vs CSI300) + ew + audit + metrics."""
    m = qb._metrics(res["equity_curve"], res["closed_returns"])
    B = 10000
    a_csi = _alpha_block(res["equity_curve"], benches["csi300"], capital, B=B)
    a_ew = (_point_only_alpha(res["equity_curve"], benches["ew500"], capital) if wf_light
            else _alpha_block(res["equity_curve"], benches["ew500"], capital, B=B))
    return {
        "window": name,
        "alpha": {"same_gross": a_csi,                       # PRIMARY: vs CSI300 same-gross
                  "same_gross_vs_ew500": a_ew},
        "metrics": m,
        "max_drawdown": m["max_drawdown"],
        "n_total_trades": len(res["trades"]),
        "audit": _audit_fields(res, None, hashes),
    }


def _slice_benches(bench_full, win):
    """Per-window benchmark curves re-based to the window (start from capital again)."""
    out = {}
    dset = set(win)
    for k, curve in bench_full.items():
        pts = [p for p in curve if p["date"] in dset]
        if not pts:
            out[k] = []
            continue
        base = pts[0]["equity"]
        out[k] = [{"date": p["date"], "equity": round(qb.CAPITAL * p["equity"] / base, 2)} for p in pts]
    return out


def _thesis_veto():
    """Core-Thesis overlay veto set: SHORT/WATCH_SHORT/RISK_BLOCKED names, active from each
    thesis's registered_at (YYYYMMDD). Registered 2026-05-30 > panel end => no historical effect."""
    rows = (qb._load(qb.BOARD, {}) if hasattr(qb, "_load") else {})
    try:
        board = json.loads((D / "trade_candidate_board.json").read_text())
    except Exception:
        return {}
    reg = {}
    try:
        tq = json.loads((D / "thesis_queue.json").read_text())
        for t in tq.get("thesis_queue", []):
            ra = (t.get("registered_at") or "")[:10].replace("-", "")
            if t.get("ticker") and ra:
                reg[t["ticker"]] = ra
    except Exception:
        pass
    veto = {}
    for r in board.get("trade_candidate_board", []):
        tk, d, st = r.get("ticker"), (r.get("direction") or "").upper(), (r.get("status") or "").upper()
        if tk and ("SHORT" in d or st == "RISK_BLOCKED"):
            veto[tk] = reg.get(tk, "20260530")
    return veto


# ───────────────────────── the verdict run ─────────────────────────
def run_verdict(quick=False) -> dict:
    import pandas as pd
    t0 = time.time()
    windows = WINDOWS_QUICK if quick else WINDOWS
    B_label = "QUICK-PLUMBING-TEST (NOT a verdict)" if quick else "FORMAL"

    gate = survivorship_gate.require_pass()         # HARD PRECONDITION
    print(f"[verdict] survivorship gate PASS ({time.time()-t0:.0f}s)")

    # ---- PRE-REGISTRATION: manifest BEFORE any run ----
    hypothesis = ("H1: in a liquid quality-filtered A-share universe, buying confirmed pullbacks "
                  "inside established uptrends (close>=MA200 rising; RSI dip<=40 turning up; volume-"
                  "confirmed reclaim of MA5) with stop/trend-break/time-stop exits produces post-cost "
                  "same-gross alpha vs CSI300 and EW at the 20d horizon.")
    lock = hashlib.sha256((hypothesis + json.dumps(THRESH, sort_keys=True)).encode()).hexdigest()
    manifest = {
        "schema": "v3_variant_manifest",
        "variant": {
            "variant_id": VARIANT_ID,
            "registered_at": _now(),
            "hypothesis": hypothesis,
            "causal_logic_label": "unestablished (structured falsifiable prior; NOT a known edge)",
            "expected_failure_modes": [
                "turnover x 0.40% RT cost dominates the signal (the proven killer)",
                "pullback-in-uptrend is just momentum beta in disguise -> dies post-2015 like momentum",
                "uptrend filter lags regime turns -> whipsaw entries at tops",
                "alpha confined to one regime window (2006-2010), like the dead inverse-momentum",
            ],
            "hypothesis_lock_hash": lock,
        },
        "test_plan": {
            "windows": [{"name": n, "start": s, "end": e} for n, s, e in windows],
            "cost_scenarios": list(COST_SCENARIOS.keys()),
            "benchmarks": ["csi300", "zz500", "csi1000", "ew500", "cash2pct"],
            "family_for_multiple_testing": FAMILY,
            "claim_gate": "ci_positive_after_cost vs CSI300 AND EW + WF1 + OOS-not-sig-neg + 19-gate",
        },
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"[verdict] manifest pre-registered -> {MANIFEST_OUT.name} lock={lock[:12]}")

    # ---- load panel + universe ONCE ----
    panel = pd.read_parquet(qb.PANEL, columns=["ts_code", "trade_date", "open", "high", "low",
                                               "close", "vol", "amount", "pre_close"])
    panel = panel[panel["ts_code"].map(lambda t: isinstance(t, str) and t.endswith((".SZ", ".SH")))]
    panel["trade_date"] = panel["trade_date"].astype(str)
    trade_dates = sorted(panel["trade_date"].unique())
    idx = qb.PanelIndex(panel)
    qb._IND_CACHE.clear()
    liquid = qb.compute_liquid_universe(panel, top_n=qb.TOP_N_ADV, lookback_days=qb.LOOKBACK,
                                        min_dollar_vol=qb.MIN_DVOL)
    print(f"[verdict] panel {len(panel):,} rows / universe built ({time.time()-t0:.0f}s)")

    full_name, full_start, full_end = windows[0]
    full_win = [d for d in trade_dates if full_start <= d <= full_end]
    ew_ret = _ew_returns(panel, liquid)
    bench_full = {
        "csi300": _index_curve(BENCH_INDEX["csi300"], full_win, qb.CAPITAL),
        "zz500": _index_curve(BENCH_INDEX["zz500"], full_win, qb.CAPITAL),
        "csi1000": _index_curve(BENCH_INDEX["csi1000"], full_win, qb.CAPITAL),
        "ew500": _ew_curve(ew_ret, full_win, qb.CAPITAL),
        "cash2pct": _cash_curve(full_win, qb.CAPITAL),
    }
    print(f"[verdict] 5 benchmarks built ({time.time()-t0:.0f}s)")

    hashes = {"config_hash": lock, "data_hash": _md5_file(qb.PANEL),
              "git_commit": _git_commit(), "engine_version": _engine_version()}

    # ---- arm runner ----
    def _run(arm, start, end, cost=None, veto=None):
        if arm == "quality_lowvol":
            return qb.run_tilt_arm(panel, idx, liquid, trade_dates, start, end, cost=cost)
        return qb.run_arm(arm if arm != "h1_thesis_overlay" else "h1",
                          panel, idx, liquid, trade_dates, start, end,
                          fast=True, cost=cost, veto_from=veto)

    veto = _thesis_veto()
    arms_results = {}
    cost_scenario_runs = []
    for arm in ["h1", "quality_lowvol", "oversold_control"]:
        entries = []
        for name, s, e in windows:
            ts = time.time()
            win = [d for d in trade_dates if s <= d <= e]
            res = _run(arm, s, e)
            benches_w = _slice_benches(bench_full, win)
            entries.append(_window_entry(name, res, benches_w, qb.CAPITAL, hashes,
                                         wf_light=name.startswith("wf_")))
            print(f"[verdict] {arm:<17} {name:<15} {len(win)}d trades={len(res['trades'])} "
                  f"({time.time()-ts:.0f}s; total {time.time()-t0:.0f}s)")
        arms_results[arm] = entries
    # h1 cost grid on the full window (IMPL7): optimistic + pessimistic (baseline already run)
    for key, cost in COST_SCENARIOS.items():
        if key == "baseline_0.40_RT":
            a = arms_results["h1"][0]["alpha"]["same_gross"]
            cost_scenario_runs.append({"window": full_name, "cost_scenario": key,
                                       "alpha": {"same_gross": {"point": a.get("point")}}})
            continue
        ts = time.time()
        res = _run("h1", full_start, full_end, cost=cost)
        pa = _point_only_alpha(res["equity_curve"], bench_full["csi300"], qb.CAPITAL)
        cost_scenario_runs.append({"window": full_name, "cost_scenario": key,
                                   "alpha": {"same_gross": {"point": pa["point"]}}})
        print(f"[verdict] h1 cost-grid {key} point={pa['point']} ({time.time()-ts:.0f}s)")

    # overlay arm: full window once; PROVE identity to h1 (no historical theses)
    ts = time.time()
    res_ov = _run("h1_thesis_overlay", full_start, full_end, veto=veto)
    res_h1_full = _run("h1", full_start, full_end)   # cached: cheap re-run for the equality proof
    nav_ov = [p["nav"] for p in res_ov["equity_curve"]]
    nav_h1 = [p["nav"] for p in res_h1_full["equity_curve"]]
    overlay_identical = (nav_ov == nav_h1)
    print(f"[verdict] overlay identical_to_h1={overlay_identical} ({time.time()-ts:.0f}s)")

    # ---- BY multiple-testing across the family (full-sample p vs CSI300 same-gross) ----
    fam_p = {arm: (arms_results[arm][0]["alpha"]["same_gross"] or {}).get("p_value") for arm in FAMILY}
    fam_adj = by_adjust(fam_p)
    h1_adj_p = fam_adj.get("h1")

    # ---- 19-gate suite on the H1 candidate ----
    same_gross_bench_curves = {}
    h1_full_curve = None
    # benchmarks dict for the BENCH gate: full-window same-gross curves (h1 gross) + cash
    res_h1_for_bench = res_h1_full
    for k in ("csi300", "zz500", "csi1000", "ew500"):
        same_gross_bench_curves[k + "_same_gross"] = qb._same_gross_curve(
            bench_full[k], res_h1_for_bench["equity_curve"], qb.CAPITAL)
    same_gross_bench_curves["cash2pct"] = bench_full["cash2pct"]

    h1_result_for_gates = {
        "_meta": {"created_at": _now(),
                  "benchmarks_reported": ["csi300", "zz500", "csi1000", "ew500", "cash2pct"]},
        "results": arms_results["h1"],
        "benchmarks": same_gross_bench_curves,
        "cost_scenario_runs": cost_scenario_runs,
    }
    gates = run_all_gates(h1_result_for_gates, manifest, VARIANT_ID,
                          family_corrected_p=h1_adj_p, stage="R&D")
    gates_overall = gates.get("verdict")            # "PASS" | "FAIL" (NA/TRACE don't block)

    # ---- verdict per Junyan's criteria (mechanical; the human decides) ----
    h1_full = arms_results["h1"][0]["alpha"]
    wf_entries = [w for w in arms_results["h1"] if w["window"].startswith("wf_")]
    wf_pos = sum(1 for w in wf_entries if (w["alpha"]["same_gross"].get("point") or 0) >= 0)
    oos = next((w for w in wf_entries if "2022" in w["window"]), None)
    oos_not_sig_neg = bool(oos and not (oos["alpha"]["same_gross"].get("ci_negative_after_cost")))
    crit = {
        "ci_positive_after_cost_vs_csi300": bool(h1_full["same_gross"].get("ci_positive_after_cost")),
        "ci_positive_after_cost_vs_ew500": bool((h1_full.get("same_gross_vs_ew500") or {}).get("ci_positive_after_cost")),
        "wf1_3of5_positive": bool(wf_pos >= 3 and len(wf_entries) >= 5) if not quick else None,
        "oos_2022_2026_not_sig_neg": oos_not_sig_neg,
        "gates_overall_pass": gates_overall == "PASS",
        "by_family_adjusted_p_h1": h1_adj_p,
    }
    claim = all(v for k, v in crit.items() if isinstance(v, bool))
    sig_neg_full = bool(h1_full["same_gross"].get("ci_negative_after_cost"))
    if claim:
        rec = "KEEP — claim gate satisfied (pending Junyan ratification)"
    elif sig_neg_full or (len(wf_entries) >= 5 and wf_pos <= 1):
        rec = "KILL — significantly negative or walk-forward collapse"
    else:
        rec = "NO-CLAIM / ITERATE — no demonstrable edge; CI does not clear zero"

    report = {
        "_meta": {"layer": f"Quant Strategy Factory v0 — {B_label} verdict run",
                  "generated_at": _now(), "elapsed_sec": round(time.time() - t0, 1),
                  "universe_source": "panel_derived_compute_liquid_universe",
                  "universe_pit_used": False,
                  "survivorship_gate": {"passed": gate.get("passed")},
                  "benchmarks_reported": ["csi300", "zz500", "csi1000", "ew500", "cash2pct"],
                  "quick_mode": quick,
                  "disclaimer": ("UNVALIDATED unless claim_permitted=true AND Junyan ratifies. A positive "
                                 "edge claim requires ci_positive_after_cost vs CSI300 AND EW + WF1 + OOS "
                                 "not significantly negative + 19-gate PASS.")},
        "manifest_hash": manifest["variant"]["hypothesis_lock_hash"],
        "arms": {arm: entries for arm, entries in arms_results.items()},
        "h1_thesis_overlay": {"identical_to_h1": overlay_identical,
                              "note": ("no historical theses exist (registered 2026-05-30 > panel end "
                                       "2026-05-26); overlay arm verified IDENTICAL to h1 over the panel — "
                                       "it is a forward-only variant"),
                              "veto_set": sorted(veto.keys())},
        "cost_scenario_runs": cost_scenario_runs,
        "by_multiple_testing": {"family": FAMILY, "raw_p": fam_p, "adjusted_p": fam_adj},
        "gates": gates,
        "verdict": {"criteria": crit, "claim_permitted": bool(claim), "recommendation": rec,
                    "wf_positive_windows": f"{wf_pos}/{len(wf_entries)}"},
        "validation_status": "unvalidated" if not claim else "claim_candidate_pending_human",
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"[verdict] wrote {OUT} ({time.time()-t0:.0f}s total)")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="plumbing test only — NOT a verdict")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    rep = run_verdict(quick=a.quick)
    v = rep["verdict"]
    print("=" * 78)
    print(f"QUANT v0 {'QUICK PLUMBING' if rep['_meta']['quick_mode'] else 'FORMAL'} VERDICT "
          f"(claim_permitted={v['claim_permitted']})")
    print("=" * 78)
    for arm, entries in rep["arms"].items():
        f = entries[0]
        a_ = f["alpha"]["same_gross"]
        print(f"  [{arm:<17}] full: ann_alpha_vs_csi300={a_.get('point')} CI=[{a_.get('lo')},{a_.get('hi')}] "
              f"p={a_.get('p_value')} | MaxDD={f['max_drawdown']:.3f} trades={f['n_total_trades']}")
    print(f"  WF positive: {v['wf_positive_windows']} | criteria: { {k: w for k, w in v['criteria'].items()} }")
    print(f"  RECOMMENDATION: {v['recommendation']}")
    return 0


def _selftest() -> int:
    errs = []
    # BY math: m=3, c(3)=1+1/2+1/3=1.8333; p=[0.01,0.03,0.04] ->
    # rank1: .01*3*1.8333/1=.055; rank2: .03*3*1.8333/2=.0825; rank3: .04*3*1.8333/3=.0733
    # monotone from end: rank2 -> min(.0825,.0733)=.0733
    adj = by_adjust({"a": 0.01, "b": 0.03, "c": 0.04})
    exp = {"a": 0.055, "b": 0.0733, "c": 0.0733}
    for k, v in exp.items():
        if abs(adj[k] - v) > 0.001:
            errs.append(f"BY adjust {k}: got {adj[k]:.4f}, expected ~{v}")
    # gate-contract strings: cost scenario keys + window name prefixes
    if set(COST_SCENARIOS) != {"optimistic_0.20_RT", "baseline_0.40_RT", "pessimistic_0.60_RT"}:
        errs.append("cost scenario keys must match the IMPL7 gate strings exactly")
    names = [n for n, _, _ in WINDOWS]
    if not names[0].startswith("full_") or not all(n.startswith("wf_") for n in names[1:]):
        errs.append("window naming contract broken (full_* + wf_*)")
    if len([n for n in names if n.startswith("wf_")]) != 5:
        errs.append("need exactly 5 wf_ windows for WF1 (3/5)")
    # fake windows through the real gate helpers (shape contract)
    from v3_gate_check_helpers import check_wf1_walk_forward_3_of_5_pos, check_nosw_not_single_window
    fake = {"results": (
        [{"window": "full_x", "alpha": {"same_gross": {"point": 0.1, "lo": 0.01, "hi": 0.2, "p_value": 0.01}}}] +
        [{"window": f"wf_{i}", "alpha": {"same_gross": {"point": 0.1 if i < 4 else -0.1,
                                                        "lo": -0.1, "hi": 0.3, "p_value": 0.5}}} for i in range(5)])}
    wf1 = check_wf1_walk_forward_3_of_5_pos(fake)
    if not wf1.get("pass"):
        errs.append(f"WF1 on 4/5-positive fake should PASS: {wf1.get('reason')}")
    nosw = check_nosw_not_single_window(fake)
    if not nosw.get("pass"):
        errs.append(f"NOSW on (full-sig-pos + wf-4/5) fake should PASS: {nosw.get('reason')}")
    if errs:
        print("quant_verdict selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("quant_verdict selftest PASSED (BY math exact; cost-scenario + window-name gate contracts; "
          "fake windows accepted by the real WF1/NOSW helpers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
