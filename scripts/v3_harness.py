#!/usr/bin/env python3
"""v3_harness.py — unified pre-registered-variant pipeline for SWING_STRATEGY_v3.

One entry point that replaces the per-variant hand-written `run_v3c_alpha1_*.py`
runners (Codex 2026-05-29 directive). Given a locked manifest it runs the whole
chain deterministically:

    manifest (hash-verified)
      → run 6 windows × 3 cost scenarios  (reuses the α1.1 config mapping verbatim)
      → aggregate bundle                  (v3_gate_eval shape)
      → BY family correction              (over ALL registered+run v3 variants)
      → v3_gate_eval                       (with the TRUE family-corrected p)
      → markdown report + before/after vs parent

Design notes / red lines honored:
  - `_config_from_manifest` is imported VERBATIM from run_v3c_alpha1_1 — it is the
    risk-bearing manifest→engine-knob mapping that α1.1 already validated. Reusing
    it (not re-implementing) guarantees α1.2+ run through identical config logic.
  - BY family = every public/data/*_bundle.json that carries `_meta.variant_id`
    (i.e. a v3 harness/α-runner bundle). One p per variant = full_20yr baseline
    same-gross α p_value. This is the honest reading of v3 §2
    ("BH-Yekutieli 跨全部 backtest variants"); it is MORE conservative as the
    family grows, which is the correct anti-curve-fit direction. The module
    `v3_multi_test_correction.correct_family` is the math; this harness is the
    caller that decides the family (per that module's contract).
  - The harness NEVER tunes anything. It runs the manifest as-locked and reports
    whatever the gates say. `--skip-run` reuses an existing bundle (for re-eval /
    validation); it never regenerates numbers.

Usage:
    python3 scripts/v3_harness.py --manifest <path>
    python3 scripts/v3_harness.py --manifest <path> --skip-run      # re-eval existing bundle
    python3 scripts/v3_harness.py --manifest <path> --baseline-variant v3c_alpha1_1
    python3 scripts/v3_harness.py --selftest

Exit codes:
    0 = harness ran OK (gate verdict may still be FAIL — that is an honest result,
        not a harness error)
    1 = harness-side error (missing/tampered manifest, no baseline rows, etc.)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_swing_backtest_fast import COST_SCENARIOS, DEFAULT_SIGNAL_WEIGHTS  # noqa: E402
from v3_manifest_hash import compute_hash  # noqa: E402
from v3_multi_test_correction import correct_family  # noqa: E402
# The risk-bearing manifest→engine mapping + date normalizer, imported verbatim
# from the α1.1 runner that already validated them.
from run_v3c_alpha1_1 import _config_from_manifest, _normalize_window_dates  # noqa: E402

DATA_DIR = REPO_ROOT / "public" / "data"
GATE_EVAL = REPO_ROOT / "scripts" / "v3_gate_eval.py"
DEFAULT_ALPHA = 0.05


# ───────────────────────── helpers ─────────────────────────

def _derive_short_name(manifest: dict) -> str:
    """variant.short_name if present, else parse variant_id up to the date token."""
    v = manifest.get("variant", {}) or {}
    sn = v.get("short_name")
    if sn:
        return str(sn)
    vid = str(v.get("variant_id", "variant"))
    toks = vid.split("_")
    out = []
    for t in toks:
        if len(t) == 8 and t.isdigit():  # YYYYMMDD date token marks the end
            break
        out.append(t)
    return "_".join(out) if out else vid


def _verify_manifest_hash(manifest: dict) -> tuple[bool, str, str]:
    stored = (manifest.get("variant", {}) or {}).get("hypothesis_lock_hash", "") or ""
    computed = compute_hash(manifest)
    return (bool(stored) and stored == computed), stored, computed


def _full20_baseline_p(bundle: dict) -> float | None:
    """full_20yr baseline same-gross α p_value from a bundle's `results` list."""
    for r in bundle.get("results", []) or []:
        if r.get("window") in ("full_20yr", "20yr", "full"):
            sg = (r.get("alpha") or {}).get("same_gross") or {}
            p = sg.get("p_value")
            return float(p) if p is not None else None
    return None


def build_by_family(alpha: float = DEFAULT_ALPHA, data_dir: Path = DATA_DIR) -> tuple[list[dict], dict]:
    """Scan public/data/*_bundle.json → BY family over registered+run v3 variants.

    Returns (family_rows, corrected) where:
      family_rows = [{"variant_id", "p_value", "bundle"} ...] (dedup by variant_id,
                    latest mtime wins)
      corrected   = v3_multi_test_correction.correct_family(...) output
    A bundle qualifies iff it has `_meta.variant_id` (only v3 harness/α-runner
    bundles do) AND a non-None full_20yr baseline same-gross p_value.
    """
    seen: dict[str, dict] = {}
    mtimes: dict[str, float] = {}
    for bf in sorted(data_dir.glob("*_bundle.json")):
        try:
            b = json.loads(bf.read_text())
        except Exception:
            continue
        vid = (b.get("_meta") or {}).get("variant_id")
        if not vid:
            continue
        p = _full20_baseline_p(b)
        if p is None:
            continue
        mt = bf.stat().st_mtime
        if vid in seen and mtimes.get(vid, 0) >= mt:
            continue
        seen[vid] = {"variant_id": vid, "p_value": float(p), "bundle": bf.name}
        mtimes[vid] = mt
    family = sorted(seen.values(), key=lambda r: r["variant_id"])
    corrected = correct_family(
        [{"variant_id": f["variant_id"], "p_value": f["p_value"]} for f in family],
        alpha=alpha,
    )
    return family, corrected


# ───────────────────────── run grid ─────────────────────────

def _run_one(short_name: str, wname: str, start: str, end: str, cost_scenario: str,
             panel, sector_map, capital: float, liquid_top_n: int,
             manifest: dict, out_dir: Path) -> dict | None:
    from run_swing_backtest_fast import run_swing_backtest_fast
    from run_iter17_r2 import compute_raw_alpha, compute_same_gross_alpha

    e_start, e_end = _normalize_window_dates(start, end)
    cfg = _config_from_manifest(manifest, cost_scenario)

    t0 = time.time()
    res = run_swing_backtest_fast(
        panel, sector_map, e_start, e_end,
        capital=capital, config=cfg, verbose=False, liquid_top_n=liquid_top_n,
    )
    elapsed = time.time() - t0
    if res.get("_status") == "insufficient_data":
        print(f"  ! {wname}/{cost_scenario}: insufficient_data — skipping")
        return None

    bench_curve = res.get("bench_curve") or (res.get("benchmarks", {}).get("ew_500", []))
    raw_alpha = compute_raw_alpha(res["equity_curve"], bench_curve)
    sg_alpha = compute_same_gross_alpha(res["equity_curve"], bench_curve, gross_floor=0.05)
    audit = res.get("audit", {})

    sg_str = f"{sg_alpha['point']:+.4f}" if sg_alpha else "n/a"
    print(f"  {wname}/{cost_scenario}: CAGR={res.get('cagr',0)*100:+6.2f}% "
          f"DD={res.get('max_drawdown',0)*100:+5.1f}% "
          f"gross={(audit.get('avg_gross_pct') or 0)*100:5.1f}% "
          f"turn={(audit.get('turnover_annual_ratio') or 0)*100:7.1f}% "
          f"untch={audit.get('untouched_carry_over_avg',0):.2f} "
          f"fullref={(audit.get('full_refresh_rate') or 0)*100:5.1f}% "
          f"sg_α={sg_str} [{elapsed:.1f}s]")

    out_path = out_dir / f"{short_name}_{wname}_{cost_scenario}.json"
    out_path.write_text(json.dumps(
        {**res, "_window": wname, "_cost_scenario": cost_scenario,
         "_period": [e_start, e_end], "alpha": {"raw": raw_alpha, "same_gross": sg_alpha}},
        indent=2, ensure_ascii=False, default=str))

    return {
        "variant": short_name, "window": wname, "cost_scenario": cost_scenario,
        "period": [e_start, e_end],
        "cagr": res.get("cagr"), "sharpe_annualized": res.get("sharpe_annualized"),
        "max_drawdown": res.get("max_drawdown"),
        "avg_gross": res.get("avg_gross"), "median_gross": res.get("median_gross"),
        "avg_n_positions": res.get("avg_n_positions"),
        "median_n_positions": res.get("median_n_positions"),
        "max_n_positions": res.get("max_n_positions"),
        "n_total_trades": res.get("n_total_trades"),
        "annualized_trades": res.get("annualized_trades"),
        "audit": audit, "alpha": {"raw": raw_alpha, "same_gross": sg_alpha},
    }


def _aggregate_bundle(short_name: str, rows: list[dict], manifest: dict,
                      manifest_path: Path, bundle_path: Path) -> dict:
    baseline_rows = [r for r in rows if r.get("cost_scenario") == "baseline_0.40_RT"]
    if not baseline_rows:
        raise RuntimeError("No baseline_0.40_RT rows; cannot build bundle.")

    bench_source = next((r for r in baseline_rows
                         if r.get("window") in ("full_20yr", "20yr", "full")),
                        baseline_rows[0])
    bench_dict = {}
    bench_file = bundle_path.parent / f"{short_name}_{bench_source['window']}_{bench_source['cost_scenario']}.json"
    if bench_file.exists():
        bench_dict = json.loads(bench_file.read_text()).get("benchmarks", {})

    variant_meta = manifest.get("variant", {}) or {}
    bundle = {
        "_meta": {
            "variant_id": variant_meta.get("variant_id"),
            "short_name": short_name,
            "manifest_path": str(manifest_path),
            "manifest_hash": variant_meta.get("hypothesis_lock_hash", ""),
            "created_at": rows[0]["audit"].get("created_at") if rows else None,
            "n_windows_baseline": len(baseline_rows),
            "n_runs_total": len(rows),
            "cost_scenarios_run": sorted({r["cost_scenario"] for r in rows}),
            "causal_validation": variant_meta.get("causal_logic_label", ""),
            "harness": "scripts/v3_harness.py",
            "numbers_validation": (
                "Numbers reported AS-RUN; no curve-fit. v3 §2 hard gates evaluated "
                "via scripts/v3_gate_eval.py with BY-corrected family p computed over "
                "ALL registered+run v3 variants (scripts/v3_multi_test_correction.py)."
            ),
        },
        "results": baseline_rows,
        "cost_scenario_runs": rows,
        "cost_scenario": "baseline_0.40_RT",
        "benchmarks": bench_dict,
    }
    bundle_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False, default=str))
    return bundle


# ───────────────────────── report ─────────────────────────

def _mechanics_eval(bundle: dict, manifest: dict) -> list[dict]:
    """Evaluate the manifest's α-mechanics sanity gates per window (runner-side)."""
    mg = (manifest.get("hard_gates", {}) or {}).get("mechanics_gates", {}) or {}
    turn_max = mg.get("mechanics_turnover_max")
    sdr_max = mg.get("mechanics_same_day_rebuy_max")
    carry_min = mg.get("mechanics_untouched_carry_over_min")
    fullref_max = mg.get("mechanics_full_refresh_rate_max")
    out = []
    for r in bundle.get("results", []):
        a = r.get("audit", {})
        turn = a.get("turnover_annual_ratio")
        sdr = a.get("same_day_rebuy_count", a.get("same_day_rebuy_executed", 0))
        carry = a.get("untouched_carry_over_avg")
        fullref = a.get("full_refresh_rate")
        checks = {
            "turnover≤%.1f" % turn_max if turn_max is not None else "turnover": (turn is not None and turn_max is not None and turn <= turn_max),
            "sdrebuy≤%d" % sdr_max if sdr_max is not None else "sdrebuy": (sdr is not None and sdr_max is not None and sdr <= sdr_max),
            "carry≥%.1f" % carry_min if carry_min is not None else "carry": (carry is not None and carry_min is not None and carry >= carry_min),
            "fullref≤%.2f" % fullref_max if fullref_max is not None else "fullref": (fullref is not None and fullref_max is not None and fullref <= fullref_max),
        }
        out.append({"window": r.get("window"), "turnover": turn, "sdrebuy": sdr,
                    "carry": carry, "fullref": fullref,
                    "pass": all(checks.values()), "checks": checks})
    return out


def write_report(report_path: Path, short_name: str, manifest: dict, bundle: dict,
                 gate_json: dict, family: list[dict], corrected: dict,
                 corrected_p_used: float, baseline_bundle: dict | None,
                 baseline_short: str | None) -> None:
    v = manifest.get("variant", {}) or {}
    L = []
    L.append(f"# V3 Harness Report — {v.get('variant_id', short_name)}")
    L.append("")
    L.append(f"- **manifest**: `{bundle.get('_meta',{}).get('manifest_path','')}`")
    L.append(f"- **hash**: `{v.get('hypothesis_lock_hash','')}`")
    L.append(f"- **registered_at**: {v.get('registered_at','')} by {v.get('registered_by','')}")
    if v.get("single_variable_change"):
        L.append(f"- **single-variable change**: {v['single_variable_change']}")
    L.append(f"- **bundle**: `public/data/{short_name}_bundle.json`")
    L.append("")

    verdict = gate_json.get("verdict", "?")
    fails = gate_json.get("failed_gate_ids") or [g["gate_id"] for g in gate_json.get("gate_outcomes", []) if g.get("verdict") == "FAIL"]
    L.append(f"## Verdict: **{verdict}**  ({len(fails)} fail: {fails})")
    L.append("")
    L.append(f"MT family-corrected p used = **{corrected_p_used:.4f}** "
             f"(BY over m={corrected.get('m')} variants, c(m)={corrected.get('c_m'):.4f})")
    L.append("")

    # Gate table
    L.append("## Gate outcomes")
    L.append("")
    L.append("| Gate | Verdict | Metric | Threshold | Reason |")
    L.append("|---|---|---|---|---|")
    for g in gate_json.get("gate_outcomes", []):
        vd = g.get("verdict", "?")
        vd_disp = f"**{vd}**" if vd == "FAIL" else vd
        reason = str(g.get("reason", "")).replace("|", "\\|")
        if len(reason) > 90:
            reason = reason[:87] + "…"
        L.append(f"| {g.get('gate_id')} | {vd_disp} | {g.get('metric')} | {g.get('threshold')} | {reason} |")
    L.append("")

    # Per-window metrics
    L.append("## Per-window metrics (baseline 0.40% RT)")
    L.append("")
    L.append("| window | turnover | gross | carry | full-ref | MaxDD | same-gross α | p |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in bundle.get("results", []):
        a = r.get("audit", {})
        sg = (r.get("alpha") or {}).get("same_gross") or {}
        L.append("| {w} | {to:.1f}% | {gr:.1f}% | {ca:.2f} | {fr:.1f}% | {dd:.1f}% | {pt:+.4f} | {p:.4f} |".format(
            w=r.get("window"),
            to=(a.get("turnover_annual_ratio") or 0) * 100,
            gr=(a.get("avg_gross_pct") or 0) * 100,
            ca=(a.get("untouched_carry_over_avg") or 0),
            fr=(a.get("full_refresh_rate") or 0) * 100,
            dd=(r.get("max_drawdown") or 0) * 100,
            pt=(sg.get("point") or 0), p=(sg.get("p_value") or 0)))
    L.append("")

    # Mechanics sanity gates
    mech = _mechanics_eval(bundle, manifest)
    if mech:
        L.append("## Mechanics sanity gates (runner-side, inherited)")
        L.append("")
        L.append("| window | turnover | sdrebuy | carry | full-ref | mechanics PASS |")
        L.append("|---|---|---|---|---|---|")
        for m in mech:
            L.append("| {w} | {to} | {sd} | {ca} | {fr} | {ok} |".format(
                w=m["window"],
                to=(f"{m['turnover']*100:.1f}%" if m["turnover"] is not None else "n/a"),
                sd=m["sdrebuy"],
                ca=(f"{m['carry']:.2f}" if m["carry"] is not None else "n/a"),
                fr=(f"{m['fullref']*100:.1f}%" if m["fullref"] is not None else "n/a"),
                ok=("✅" if m["pass"] else "❌")))
        L.append("")

    # Before/after vs parent
    if baseline_bundle is not None:
        L.append(f"## Before/after vs parent ({baseline_short})")
        L.append("")
        L.append(f"| window | turnover {baseline_short}→{short_name} | gross | carry | sg-α point |")
        L.append("|---|---|---|---|---|")
        base_by_win = {r.get("window"): r for r in baseline_bundle.get("results", [])}

        def _arrow(parent_val, cur_val, scale=1.0, fmt="{:.1f}", suffix=""):
            """Render 'parent→cur'; parent shows 'n/a' if the field was absent
            (None), so an un-instrumented parent is never displayed as a measured 0."""
            cur_s = (fmt.format(cur_val * scale) + suffix) if cur_val is not None else "n/a"
            par_s = (fmt.format(parent_val * scale) + suffix) if parent_val is not None else "n/a"
            return f"{par_s}→{cur_s}"

        for r in bundle.get("results", []):
            w = r.get("window")
            br = base_by_win.get(w)
            a = r.get("audit", {})
            sg = (r.get("alpha") or {}).get("same_gross") or {}
            if br:
                ba = br.get("audit", {})
                bsg = (br.get("alpha") or {}).get("same_gross") or {}
                L.append("| {w} | {to} | {gr} | {ca} | {al} |".format(
                    w=w,
                    to=_arrow(ba.get("turnover_annual_ratio"), a.get("turnover_annual_ratio"), 100, "{:.1f}", "%"),
                    gr=_arrow(ba.get("avg_gross_pct"), a.get("avg_gross_pct"), 100, "{:.1f}", "%"),
                    ca=_arrow(ba.get("untouched_carry_over_avg"), a.get("untouched_carry_over_avg"), 1.0, "{:.2f}"),
                    al=_arrow(bsg.get("point"), sg.get("point"), 1.0, "{:+.3f}")))
            else:
                L.append(f"| {w} | (no parent row) | | | |")
        L.append("")

    # BY family
    L.append("## BY family (multi-test correction)")
    L.append("")
    L.append(f"alpha={corrected.get('alpha')}, m={corrected.get('m')}, "
             f"c(m)={corrected.get('c_m'):.4f}, k*={corrected.get('k_star')}")
    L.append("")
    L.append("| variant_id | raw p | rank | adjusted p (BY) | reject@0.05 |")
    L.append("|---|---|---|---|---|")
    for r in corrected.get("results", []):
        mark = "**← this variant**" if r["variant_id"] == v.get("variant_id") else ""
        L.append(f"| {r['variant_id']} {mark} | {r['p_value']:.4f} | {r['rank']} | {r['adjusted_p']:.4f} | {r['reject']} |")
    L.append("")

    # Cost robustness
    L.append("## Cost-scenario robustness (full_20yr, same-gross α)")
    L.append("")
    L.append("| scenario | same-gross α | CI | p |")
    L.append("|---|---|---|---|")
    for r in sorted([r for r in bundle.get("cost_scenario_runs", [])
                     if r.get("window") in ("full_20yr", "20yr", "full")],
                    key=lambda x: x.get("cost_scenario", "")):
        sg = (r.get("alpha") or {}).get("same_gross") or {}
        L.append("| {s} | {pt:+.4f} | [{lo:+.4f}, {hi:+.4f}] | {p:.4f} |".format(
            s=r.get("cost_scenario"), pt=(sg.get("point") or 0),
            lo=(sg.get("lo") or 0), hi=(sg.get("hi") or 0), p=(sg.get("p_value") or 0)))
    L.append("")
    L.append("---")
    L.append("Generated by `scripts/v3_harness.py`")
    report_path.write_text("\n".join(L))


# ───────────────────────── main ─────────────────────────

def run_pipeline(manifest_path: Path, baseline_variant: str | None, skip_run: bool,
                 skip_eval: bool, capital: float, liquid_top_n: int | None,
                 out_dir: Path, report_dir: Path) -> int:
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text())

    ok, stored, computed = _verify_manifest_hash(manifest)
    if not ok:
        print(f"ERROR: manifest hash mismatch — refusing to run.\n"
              f"  stored:   {stored}\n  computed: {computed}", file=sys.stderr)
        return 1
    short_name = _derive_short_name(manifest)
    variant_id = (manifest.get("variant", {}) or {}).get("variant_id")
    print(f"[harness] variant_id={variant_id}  short_name={short_name}")
    print(f"[harness] hash verified: {stored}")

    out_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = out_dir / f"{short_name}_bundle.json"

    if skip_run:
        if not bundle_path.exists():
            print(f"ERROR: --skip-run but no bundle at {bundle_path}", file=sys.stderr)
            return 1
        print(f"[harness] --skip-run: reusing {bundle_path}")
        bundle = json.loads(bundle_path.read_text())
    else:
        import pandas as pd
        from sector_scorer import load_sector_map
        if "momentum_20d" not in DEFAULT_SIGNAL_WEIGHTS:
            print("ERROR: engine missing momentum_20d in DEFAULT_SIGNAL_WEIGHTS", file=sys.stderr)
            return 1
        test_plan = manifest.get("test_plan", {})
        windows = test_plan.get("windows", [])
        scenarios = test_plan.get("cost_scenarios", list(COST_SCENARIOS.keys()))
        for s in scenarios:
            if s not in COST_SCENARIOS:
                print(f"ERROR: unknown cost_scenario {s!r}", file=sys.stderr)
                return 1
        if liquid_top_n is None:
            liquid_top_n = int(manifest.get("design", {}).get("universe", {}).get("liquid_top_n", 500))

        print(f"[harness] windows={[w['name'] for w in windows]} scenarios={scenarios} "
              f"({len(windows)*len(scenarios)} runs) liquid_top_n={liquid_top_n}")
        print(f"[harness] loading panel...")
        panel = pd.read_parquet(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet")
        sector_map = load_sector_map(str(REPO_ROOT / "data_history" / "sector_mapping.json"))
        print(f"[harness] panel: {len(panel):,} rows × {panel['ts_code'].nunique()} tickers")

        rows = []
        t0 = time.time()
        for w in windows:
            print(f"\n=== window {w['name']} ({w['start']} → {w['end']}) ===")
            for s in scenarios:
                row = _run_one(short_name, w["name"], w["start"], w["end"], s,
                               panel, sector_map, capital, liquid_top_n, manifest, out_dir)
                if row:
                    rows.append(row)
        print(f"\n[harness] {len(rows)} backtests in {time.time()-t0:.1f}s")
        bundle = _aggregate_bundle(short_name, rows, manifest, manifest_path, bundle_path)
        print(f"[harness] wrote bundle: {bundle_path}")

    # BY family correction over all registered+run variants (includes this one).
    family, corrected = build_by_family(alpha=DEFAULT_ALPHA, data_dir=out_dir)
    print(f"\n[harness] BY family (m={corrected['m']}, c(m)={corrected['c_m']:.4f}):")
    cur = None
    for r in corrected["results"]:
        tag = "  ← THIS" if r["variant_id"] == variant_id else ""
        print(f"    {r['variant_id']:<48} raw={r['p_value']:.4f} adj={r['adjusted_p']:.4f} reject={r['reject']}{tag}")
        if r["variant_id"] == variant_id:
            cur = r
    if cur is None:
        print(f"WARNING: current variant {variant_id} not in BY family "
              f"(no full_20yr baseline p?). Falling back to raw p.", file=sys.stderr)
        corrected_p_used = _full20_baseline_p(bundle) or 1.0
    else:
        corrected_p_used = cur["adjusted_p"]
    print(f"[harness] MT family-corrected p for this variant = {corrected_p_used:.4f}")

    # Gate eval with the TRUE family-corrected p.
    gate_md = report_dir / f"{short_name}_gate_eval.md"
    gate_js = report_dir / f"{short_name}_gate_eval.json"
    gate_json: dict = {}
    if skip_eval:
        print("[harness] --skip-eval set; not invoking v3_gate_eval.")
    else:
        cmd = [sys.executable, str(GATE_EVAL),
               "--variant", str(variant_id),
               "--manifest", str(manifest_path),
               "--result", str(bundle_path),
               "--family-corrected-p", f"{corrected_p_used:.6f}",
               "--out-md", str(gate_md), "--out-json", str(gate_js)]
        print("[harness] $ " + " ".join(cmd))
        rc = subprocess.run(cmd).returncode
        print(f"[harness] v3_gate_eval exit={rc}")
        if gate_js.exists():
            gate_json = json.loads(gate_js.read_text())

    # Before/after vs parent.
    baseline_short = baseline_variant
    if baseline_short is None:
        parent = (manifest.get("variant", {}) or {}).get("parent_variant")
        if parent:
            # parent is a variant_id; map to short_name by finding its bundle
            for bf in out_dir.glob("*_bundle.json"):
                try:
                    b = json.loads(bf.read_text())
                except Exception:
                    continue
                if (b.get("_meta") or {}).get("variant_id") == parent:
                    baseline_short = (b.get("_meta") or {}).get("short_name") or bf.name.replace("_bundle.json", "")
                    break
    baseline_bundle = None
    if baseline_short:
        bpath = out_dir / f"{baseline_short}_bundle.json"
        if bpath.exists():
            baseline_bundle = json.loads(bpath.read_text())
        else:
            print(f"[harness] note: baseline bundle {bpath} not found; skipping before/after.")

    # Report.
    report_path = report_dir / f"{short_name}_report.md"
    write_report(report_path, short_name, manifest, bundle, gate_json,
                 family, corrected, corrected_p_used, baseline_bundle, baseline_short)
    print(f"[harness] wrote report: {report_path}")
    if gate_json:
        fails = gate_json.get("failed_gate_ids") or [g["gate_id"] for g in gate_json.get("gate_outcomes", []) if g.get("verdict") == "FAIL"]
        print(f"[harness] VERDICT: {gate_json.get('verdict')} ({len(fails)} fail: {fails})")
    return 0


def _selftest() -> int:
    """Validate harness plumbing WITHOUT running backtests.

    1. short_name derivation (field + fallback parse).
    2. BY family build over existing bundles → m≥1, current variants present.
    3. _full20_baseline_p extraction round-trips on an existing bundle.
    """
    errors = []

    # 1. short_name
    m_field = {"variant": {"variant_id": "x_20260529_y", "short_name": "v3c_alpha1_2"}}
    if _derive_short_name(m_field) != "v3c_alpha1_2":
        errors.append("short_name field not honored")
    m_parse = {"variant": {"variant_id": "v3c_alpha1_1_20260528_turnover_mechanics"}}
    if _derive_short_name(m_parse) != "v3c_alpha1_1":
        errors.append(f"short_name parse wrong: {_derive_short_name(m_parse)}")
    m_parse2 = {"variant": {"variant_id": "v3c_alpha1_20260528"}}
    if _derive_short_name(m_parse2) != "v3c_alpha1":
        errors.append(f"short_name parse2 wrong: {_derive_short_name(m_parse2)}")

    # 2. BY family over existing bundles
    family, corrected = build_by_family()
    if corrected["m"] < 1:
        errors.append("BY family empty — expected ≥1 existing v3 bundle")
    # monotonic adjusted p in sorted order
    res_sorted = sorted(corrected["results"], key=lambda r: r["p_value"])
    for i in range(1, len(res_sorted)):
        if res_sorted[i]["adjusted_p"] + 1e-9 < res_sorted[i-1]["adjusted_p"]:
            errors.append("BY adjusted p not monotonic")
            break
    print(f"  [selftest] BY family m={corrected['m']}: "
          f"{[(r['variant_id'][:20], round(r['p_value'],4), round(r['adjusted_p'],4)) for r in corrected['results']]}")

    # 3. full20 extraction
    a11 = DATA_DIR / "v3c_alpha1_1_bundle.json"
    if a11.exists():
        p = _full20_baseline_p(json.loads(a11.read_text()))
        if p is None:
            errors.append("α1.1 full_20yr baseline p extraction returned None")
        else:
            print(f"  [selftest] α1.1 full_20yr baseline p = {p:.4f}")

    if errors:
        print("v3_harness selftest FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("v3_harness selftest PASSED")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Unified v3 pre-registered-variant pipeline.")
    p.add_argument("--manifest", type=str)
    p.add_argument("--baseline-variant", type=str, default=None,
                   help="short_name of parent variant for before/after table "
                        "(default: manifest.variant.parent_variant)")
    p.add_argument("--skip-run", action="store_true", help="reuse existing bundle (re-eval only)")
    p.add_argument("--skip-eval", action="store_true")
    p.add_argument("--capital", type=float, default=10_000_000.0)
    p.add_argument("--liquid-top-n", type=int, default=None)
    p.add_argument("--out-dir", type=str, default=str(DATA_DIR))
    p.add_argument("--report-dir", type=str, default="/tmp/v3_harness")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.manifest:
        p.error("--manifest required (or --selftest)")
    return run_pipeline(
        Path(args.manifest), args.baseline_variant, args.skip_run, args.skip_eval,
        args.capital, args.liquid_top_n, Path(args.out_dir), Path(args.report_dir),
    )


if __name__ == "__main__":
    sys.exit(main())
