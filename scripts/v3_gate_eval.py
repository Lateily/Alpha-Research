#!/usr/bin/env python3
"""v3_gate_eval.py — Hard-gate evaluator for SWING_STRATEGY_v3 (§2 full suite).

Usage:
    python3 scripts/v3_gate_eval.py --variant <variant_id> --result <path_to_result.json>
        [--manifest <path_to_manifest.json>]
        [--family-corrected-p <float>]
        [--out-md <path>] [--out-json <path>]
    python3 scripts/v3_gate_eval.py --selftest

Exit codes:
    0  = ALL gates PASS
    1  = ANY gate FAIL (or input error)

Outputs:
    <variant_id>_gate_eval.md
    <variant_id>_gate_eval.json

Per SWING_STRATEGY_v3.md §2 + §3.4:
    - Statistical gates: WF1, WF2, MT, BENCH, NOSW
    - Implementation gates: IMPL1..IMPL7
    - Audit gates: AUD1, AUD2, AUD3
    - Pre-registration gates: PRE1, PRE2, PRE3

Caller responsibility:
    1. Pre-register manifest in experiments/agent_tasks/variant_manifests/.
    2. Run backtest, get result JSON.
    3. (Optional) Run v3_multi_test_correction.py over current v3 family,
       extract this variant's adjusted_p, pass via --family-corrected-p.
    4. Run this script; on PASS, queue Junyan review.

Per Junyan red-line: "宁愿犯错也不愿意找不出来错误在哪." This tool errs on the
side of FAIL when fields are missing — better a false-fail than a silent pass.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

# Try absolute import (when run from repo root), then sibling import.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from v3_gate_check_helpers import (  # noqa: E402
    check_wf1_walk_forward_3_of_5_pos,
    check_wf2_oos_not_neg_sig,
    check_mt_by_corrected,
    check_bench_multi_benchmark_reported,
    check_nosw_not_single_window,
    check_bundle_completeness,
    check_impl1_max_positions,
    check_impl2_avg_gross_30,
    check_impl3_median_pos_ge_2,
    check_impl4_turnover_le_200,
    check_impl5_max_dd_floor,
    check_impl6_sample_size,
    check_impl7_post_cost_alpha_positive,
    check_aud1_audit_fields_present,
    check_aud3_trade_log_full,
    check_pre1_manifest_present,
    check_pre2_registered_before_run,
    check_pre3_hypothesis_immutable,
)

# Order matters — printed in this order in the report.
# v3 Phase A (Junyan ratify #1/#3): AUD2 is a TRACE mirror of IMPL1; NOSW can be
# NA when no full-sample window present; BUNDLE separately enforces manifest
# completeness. Only PASS/FAIL count toward the overall verdict (NA/TRACE skip).
STAT_GATES = [
    ("WF1", check_wf1_walk_forward_3_of_5_pos),
    ("WF2", check_wf2_oos_not_neg_sig),
    ("MT",  check_mt_by_corrected),
    ("BENCH", check_bench_multi_benchmark_reported),
    ("NOSW", check_nosw_not_single_window),
]
IMPL_GATES = [
    ("IMPL1", check_impl1_max_positions),
    ("IMPL2", check_impl2_avg_gross_30),
    ("IMPL3", check_impl3_median_pos_ge_2),
    ("IMPL4", check_impl4_turnover_le_200),
    ("IMPL5", check_impl5_max_dd_floor),
    ("IMPL6", check_impl6_sample_size),
    ("IMPL7", check_impl7_post_cost_alpha_positive),
]
AUDIT_GATES = [
    ("AUD1", check_aud1_audit_fields_present),
    ("AUD3", check_aud3_trade_log_full),
    # BUNDLE is its own audit gate: completeness against manifest test_plan.
    ("BUNDLE", check_bundle_completeness),
]


def run_all_gates(result: dict,
                  manifest: Optional[dict],
                  variant_id: str,
                  family_corrected_p: Optional[float],
                  stage: str = "R&D") -> dict:
    outcomes = []

    # Pre-registration gates first (manifest hygiene).
    outcomes.append(check_pre1_manifest_present(manifest, variant_id=variant_id))
    outcomes.append(check_pre2_registered_before_run(manifest, result))
    outcomes.append(check_pre3_hypothesis_immutable(manifest))

    # Statistical gates.
    for gate_id, fn in STAT_GATES:
        if gate_id == "MT":
            outcomes.append(fn(result, family_corrected_p=family_corrected_p))
        else:
            outcomes.append(fn(result))

    # Implementation gates. IMPL7 supports manifest + stage parameters.
    for gate_id, fn in IMPL_GATES:
        if gate_id == "IMPL7":
            outcomes.append(fn(result, manifest=manifest, stage=stage))
        else:
            outcomes.append(fn(result))

    # Audit gates. BUNDLE takes manifest.
    for gate_id, fn in AUDIT_GATES:
        if gate_id == "BUNDLE":
            outcomes.append(fn(result, manifest))
        else:
            outcomes.append(fn(result))

    # AUD2 = a labeled TRACE mirror of IMPL1 (Junyan ratify #1: NOT counted
    # as a blocking gate; IMPL1 is the single load-bearing max_positions gate).
    impl1 = next(o for o in outcomes if o["gate_id"] == "IMPL1")
    aud2 = dict(impl1)
    aud2["gate_id"] = "AUD2"
    aud2["category"] = "AUDIT"
    aud2["name"] = "max_positions_enforced_audit_mirror"
    aud2["verdict"] = "TRACE"   # mirror, never blocks
    outcomes.append(aud2)

    # Verdict: only gates with verdict == "FAIL" block. NA and TRACE skip.
    # Backward-compat: outcomes that lack 'verdict' fall back to !pass == fail.
    def _is_blocking_fail(o: dict) -> bool:
        v = o.get("verdict")
        if v is None:
            return not o.get("pass", False)
        return v == "FAIL"
    fails = [o for o in outcomes if _is_blocking_fail(o)]
    nas = [o for o in outcomes if o.get("verdict") == "NA"]
    traces = [o for o in outcomes if o.get("verdict") == "TRACE"]
    verdict = "PASS" if not fails else "FAIL"
    return {
        "variant_id": variant_id,
        "verdict": verdict,
        "stage": stage,
        "n_gates_total": len(outcomes),
        "n_gates_failed": len(fails),
        "n_gates_na": len(nas),
        "n_gates_trace": len(traces),
        "failed_gate_ids": [o["gate_id"] for o in fails],
        "na_gate_ids": [o["gate_id"] for o in nas],
        "trace_gate_ids": [o["gate_id"] for o in traces],
        "gate_outcomes": outcomes,
    }


# -------------------- Report rendering --------------------

def render_md(verdict: dict, family_corrected_p: Optional[float],
              result_path: str, manifest_path: Optional[str]) -> str:
    lines = []
    lines.append(f"# v3 Hard-Gate Evaluation — {verdict['variant_id']}")
    lines.append("")
    lines.append(f"**Verdict**: **{verdict['verdict']}**  (stage: `{verdict.get('stage','R&D')}`)")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| variant_id | {verdict['variant_id']} |")
    lines.append(f"| total gates | {verdict['n_gates_total']} |")
    lines.append(f"| failed gates | {verdict['n_gates_failed']} ({verdict.get('failed_gate_ids')}) |")
    lines.append(f"| NA gates | {verdict.get('n_gates_na', 0)} ({verdict.get('na_gate_ids')}) |")
    lines.append(f"| TRACE gates | {verdict.get('n_gates_trace', 0)} ({verdict.get('trace_gate_ids')}) |")
    lines.append(f"| result_json | {result_path} |")
    lines.append(f"| manifest_json | {manifest_path or '(none)'} |")
    lines.append(f"| family_corrected_p | {family_corrected_p if family_corrected_p is not None else '(not injected)'} |")
    lines.append("")
    lines.append("## Gate outcomes")
    lines.append("")
    lines.append("Verdict column lifecycle (v3 Phase A Junyan ratify #1/#3):")
    lines.append("`PASS` = condition met. `FAIL` = condition violated (blocking).")
    lines.append("`NA` = not applicable in this bundle (not blocking; e.g. NOSW when no")
    lines.append("full-sample window). `TRACE` = informational mirror (not blocking;")
    lines.append("e.g. AUD2 mirrors IMPL1).")
    lines.append("")
    lines.append("| Gate | Category | Verdict | Metric | Threshold | Reason |")
    lines.append("|---|---|---|---|---|---|")
    for o in verdict["gate_outcomes"]:
        v = o.get("verdict") or ("PASS" if o.get("pass") else "FAIL")
        if v == "FAIL":
            status = "**FAIL**"
        elif v == "PASS":
            status = "PASS"
        elif v == "NA":
            status = "_NA_"
        elif v == "TRACE":
            status = "_TRACE_"
        else:
            status = v
        metric = o.get("metric")
        metric_str = "—" if metric is None else (f"{metric:.4f}" if isinstance(metric, float) else str(metric))
        thresh = o.get("threshold")
        thresh_str = "—" if thresh is None else str(thresh)
        # Truncate reason to keep one line.
        reason = o.get("reason", "")
        if len(reason) > 240:
            reason = reason[:237] + "..."
        # Pipe-escape
        reason = reason.replace("|", "\\|")
        thresh_str = thresh_str.replace("|", "\\|")
        lines.append(f"| {o['gate_id']} | {o['category']} | {status} | {metric_str} | {thresh_str} | {reason} |")
    lines.append("")
    lines.append("## Methodology notes")
    lines.append("")
    lines.append("- Gates derived from `docs/strategy/SWING_STRATEGY_v3.md` §2 + §3.4.")
    lines.append("- Manifest schema: `experiments/agent_tasks/v3_variant_manifest_template.json`.")
    lines.append("- BY (Benjamini-Yekutieli) family p must be computed separately via")
    lines.append("  `scripts/v3_multi_test_correction.py` and injected via `--family-corrected-p`.")
    lines.append("- Per v3 red line: missing fields default to FAIL (better a false fail than a silent pass).")
    lines.append("- v3 Phase A Junyan ratify (2026-05-28 PM2):")
    lines.append("  - **#1 AUD2 vs IMPL1**: AUD2 is TRACE (audit mirror), IMPL1 is the load-bearing gate.")
    lines.append("  - **#2 turnover semantic**: IMPL4 reads `audit.turnover_annual_ratio` (canonical);")
    lines.append("    `turnover_annual_pct` is a deprecated alias holding the SAME ratio value.")
    lines.append("    Threshold 2.0 = 200% annual book turnover. Display layer × 100.")
    lines.append("  - **#3 NOSW NA**: walk-forward-only bundles return NA (not blocking).")
    lines.append("    Bundle completeness is enforced separately by the BUNDLE audit gate.")
    lines.append("  - **#4 IMPL7 cost scenarios**: research baseline 0.40% RT (must pass).")
    lines.append("    Optimistic 0.20% + pessimistic 0.60% reported but only enforced at")
    lines.append("    `paper_promotion` / `capital_promotion` stage.")
    lines.append("  - **#5 PRE3 hash**: `hypothesis_lock_hash` declared at manifest registration.")
    lines.append("    See `scripts/v3_manifest_hash.py` for compute/inject helper.")
    lines.append("  - **#13 multi-bench**: csi300, zz500, csi1000, ew500, cash2pct ALL required as")
    lines.append("    non-empty curves. SSE50 optional. HSI intentionally absent.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Generated by `scripts/v3_gate_eval.py`")
    return "\n".join(lines) + "\n"


# -------------------- selftest --------------------

def _selftest() -> int:
    """Drive run_all_gates on synthetic_pass and iter18-shaped synthetic data."""
    from v3_gate_check_helpers import _synthetic_pass, _synthetic_iter18_like

    errors = []

    # synthetic_pass with good manifest and family_p=0.01 -> PASS
    good_manifest = {
        "schema": "v3_variant_manifest",
        "variant": {
            "variant_id": "v3c_synth_pass",
            "registered_at": "2026-05-29T00:00:00Z",
            "hypothesis": "test pass",
            "causal_logic_label": "Causal logic is unestablished: synth.",
            "expected_failure_modes": ["test"],
            "hypothesis_lock_hash": "sha256:abc",
        },
    }
    sp = _synthetic_pass()
    v = run_all_gates(sp, good_manifest, "v3c_synth_pass",
                      family_corrected_p=0.01)
    if v["verdict"] != "PASS":
        fails = [o for o in v["gate_outcomes"] if not o["pass"]]
        errors.append(f"synthetic_pass expected PASS, got FAIL; failed gates: "
                      f"{[(o['gate_id'], o['reason']) for o in fails]}")

    # iter18-like with NO manifest and NO family_p -> FAIL (PRE1/2/3 + MT + WF1 + WF2 + IMPL2 + BENCH)
    iter18 = _synthetic_iter18_like()
    v = run_all_gates(iter18, None, "iter18_demo",
                      family_corrected_p=None)
    if v["verdict"] != "FAIL":
        errors.append("iter18-like expected FAIL, got PASS")
    failed_ids = {o["gate_id"] for o in v["gate_outcomes"] if not o["pass"]}
    expected_failed = {"PRE1", "PRE2", "PRE3", "MT", "WF1", "WF2", "BENCH", "IMPL2"}
    missing_expected = expected_failed - failed_ids
    if missing_expected:
        errors.append(f"iter18-like expected to fail at least {expected_failed}, "
                      f"missing: {missing_expected}; all failed: {failed_ids}")

    # Render MD doesn't crash
    md = render_md(v, family_corrected_p=None, result_path="(synthetic)", manifest_path=None)
    if "v3 Hard-Gate Evaluation" not in md or "Gate outcomes" not in md:
        errors.append("render_md output missing required sections")

    if errors:
        print("v3_gate_eval selftest FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("v3_gate_eval selftest PASSED")
    print("  synthetic_pass + good manifest -> PASS")
    print("  iter18-like + no manifest -> FAIL (PRE1/2/3, MT, WF1, WF2, BENCH, IMPL2)")
    return 0


# -------------------- CLI --------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="v3 hard-gate evaluator (per SWING_STRATEGY_v3.md §2)",
    )
    parser.add_argument("--variant", type=str, help="variant_id (e.g. v3c_horizon10)")
    parser.add_argument("--result", type=str, help="path to backtest result JSON")
    parser.add_argument("--manifest", type=str,
                        help="path to variant manifest JSON (per "
                             "experiments/agent_tasks/v3_variant_manifest_template.json)")
    parser.add_argument("--family-corrected-p", type=float, default=None,
                        help="BY-corrected p over v3 family (from "
                             "scripts/v3_multi_test_correction.py)")
    parser.add_argument("--out-md", type=str, help="output report MD path")
    parser.add_argument("--out-json", type=str, help="output report JSON path")
    parser.add_argument("--selftest", action="store_true", help="Run built-in selftest")
    args = parser.parse_args()

    if args.selftest:
        return _selftest()

    if not args.variant or not args.result:
        parser.error("--variant and --result required (or use --selftest)")

    result_path = Path(args.result)
    if not result_path.exists():
        print(f"ERROR: result file not found: {result_path}", file=sys.stderr)
        return 1
    with open(result_path) as f:
        result = json.load(f)

    manifest = None
    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.exists():
            print(f"ERROR: manifest file not found: {manifest_path}", file=sys.stderr)
            return 1
        with open(manifest_path) as f:
            manifest = json.load(f)
    else:
        # Try to auto-locate manifest by convention.
        conventional = REPO_ROOT / "experiments" / "agent_tasks" / "variant_manifests" / f"{args.variant}.json"
        if conventional.exists():
            with open(conventional) as f:
                manifest = json.load(f)
            print(f"INFO: auto-loaded manifest from {conventional}", file=sys.stderr)

    verdict = run_all_gates(result, manifest, args.variant,
                            family_corrected_p=args.family_corrected_p)

    out_md = Path(args.out_md) if args.out_md else (Path.cwd() / f"{args.variant}_gate_eval.md")
    out_json = Path(args.out_json) if args.out_json else (Path.cwd() / f"{args.variant}_gate_eval.json")

    with open(out_md, "w") as f:
        f.write(render_md(verdict,
                          family_corrected_p=args.family_corrected_p,
                          result_path=str(result_path),
                          manifest_path=args.manifest))
    with open(out_json, "w") as f:
        json.dump(verdict, f, indent=2)

    print(f"verdict: {verdict['verdict']} ({verdict['n_gates_failed']}/{verdict['n_gates_total']} fails)")
    print(f"wrote {out_md}")
    print(f"wrote {out_json}")

    return 0 if verdict["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
