#!/usr/bin/env python3
"""v3_gate_check_helpers.py — Per-gate check functions for v3 hard gate eval.

Each gate is a pure function:
    check_<gate_name>(result_dict, **kwargs) -> GateOutcome

GateOutcome = dict with keys:
    {
      "gate_id": str,            # e.g. "WF1"
      "name": str,               # human label
      "category": str,           # STAT | IMPL | AUDIT | PRE
      "pass": bool,
      "reason": str,             # one line explanation
      "metric": float | None,    # numeric value (optional)
      "threshold": ...,          # what we compared against
      "windows_evaluated": list[str] | None,
    }

Input shape (canonical, see also iter18_b1_b3_walkforward.json):
    {
      "_meta": {...},
      "results": [
        {
          "variant": "b1_b3_4factor_no_atr",
          "window": "wf_2006_2010",
          "audit": {
            "engine_version": ..., "config_hash": ..., "data_hash": ...,
            "git_commit": ..., "max_positions_enforced": ...,
            "avg_gross_pct": ..., "max_gross_pct": ..., "turnover_annual_pct": ...,
            "median_n_positions": ..., "avg_n_positions": ...,
            "n_trade_days": ..., "n_total_trades_actual": ...,
          },
          "alpha": {"raw": {...}, "same_gross": {"point", "lo", "hi", "p_value",
                                                 "direction", "excludes_zero", "n_dates"}},
          "max_drawdown": float (negative),
          "avg_gross": float,
          "median_n_positions": float,
          ...
        }, ...
      ],
      "benchmarks": {...} | None    # optional, see BENCH gate
    }

NOTE: turnover_annual_pct in the existing iter18 audit field is reported as a
RATIO (e.g. 14.06 means 14.06 trades/year, not 14.06% turnover). v2's spec
says ≤ 200% annual = ≤ 2.0 turnover ratio. The gate accepts either an explicit
percent ('turnover_annual_pct_pct') or the existing ratio field and conservatively
uses the highest-magnitude interpretation. See V3D AMBIGUITY #2 in /tmp/v3d_report.md.
"""

from __future__ import annotations

import json
import sys
from typing import List, Optional, Tuple

# -------------------- helpers --------------------

def _get_windows(result: dict) -> List[dict]:
    """Return list of per-window result dicts; supports both:
        {"results": [ {window: ..., ...}, ... ]}    # iter18_b1_b3 shape
        {"per_window": [ ... ]}                     # alt
    """
    if "results" in result and isinstance(result["results"], list):
        return result["results"]
    if "per_window" in result and isinstance(result["per_window"], list):
        return result["per_window"]
    if "_meta" in result and isinstance(result.get("results"), list):
        return result["results"]
    return []


def _same_gross_point(w: dict) -> Optional[float]:
    a = w.get("alpha", {}).get("same_gross", {})
    if "point" in a:
        return float(a["point"])
    if "same_gross_alpha" in w:
        return float(w["same_gross_alpha"])
    return None


def _same_gross_ci(w: dict) -> Optional[Tuple[float, float]]:
    a = w.get("alpha", {}).get("same_gross", {})
    if "lo" in a and "hi" in a:
        return (float(a["lo"]), float(a["hi"]))
    if "ci" in w and len(w["ci"]) == 2:
        return (float(w["ci"][0]), float(w["ci"][1]))
    return None


def _same_gross_p(w: dict) -> Optional[float]:
    a = w.get("alpha", {}).get("same_gross", {})
    if "p_value" in a:
        return float(a["p_value"])
    if "p_value" in w:
        return float(w["p_value"])
    return None


def _audit(w: dict) -> dict:
    return w.get("audit", {}) or {}


def _outcome(gate_id, name, category, passed, reason,
             metric=None, threshold=None, windows=None,
             verdict: Optional[str] = None) -> dict:
    """Build a gate outcome dict.

    verdict (v3 Phase A Junyan ratify #3): explicit lifecycle label.
        PASS  = gate evaluated and condition met
        FAIL  = gate evaluated and condition violated
        NA    = gate not applicable in current bundle (e.g. NOSW with no
                full-sample window present). Reported, but NOT counted as
                FAIL in the overall verdict.
        TRACE = informational mirror (e.g. AUD2 mirrors IMPL1). Reported but
                NOT counted as FAIL in the overall verdict (Junyan ratify #1:
                only IMPL1 is the load-bearing max_positions gate).
    Default: PASS if passed else FAIL.
    """
    if verdict is None:
        verdict = "PASS" if passed else "FAIL"
    return {
        "gate_id": gate_id,
        "name": name,
        "category": category,
        "pass": bool(passed),
        "verdict": verdict,
        "reason": reason,
        "metric": metric,
        "threshold": threshold,
        "windows_evaluated": windows,
    }


# -------------------- Statistical gates --------------------

def check_wf1_walk_forward_3_of_5_pos(result: dict) -> dict:
    """WF1: ≥ 3/5 walk-forward windows have same-gross α point estimate ≥ 0.

    v3 §2.1 line: "Walk-forward 3/5 windows same-gross α ≥ 0 point estimate".
    """
    windows = _get_windows(result)
    wf_windows = [w for w in windows if str(w.get("window", "")).startswith("wf_")]
    if not wf_windows:
        return _outcome("WF1", "walk_forward_3_of_5_pos", "STAT",
                        False, "no wf_* windows found", metric=0,
                        threshold=">=3/5", windows=[])
    pos_windows = []
    for w in wf_windows:
        pt = _same_gross_point(w)
        if pt is not None and pt >= 0:
            pos_windows.append(w.get("window"))
    n_pos = len(pos_windows)
    n_total = len(wf_windows)
    required = max(3, int(round(n_total * 0.6)))  # be strict at 3 of 5 minimum
    if n_total == 5:
        required = 3
    passed = n_pos >= required
    return _outcome(
        "WF1", "walk_forward_3_of_5_pos", "STAT",
        passed,
        f"{n_pos}/{n_total} windows have same_gross α ≥ 0 point estimate; threshold {required}/{n_total}",
        metric=n_pos,
        threshold=f">={required}/{n_total}",
        windows=[w.get("window") for w in wf_windows],
    )


def check_wf2_oos_not_neg_sig(result: dict, oos_window_name: str = "wf_2022_2026") -> dict:
    """WF2: OOS most-recent window same-gross α CI does NOT exclude 0 on NEG side.

    v3 §2.1: "OOS window same-gross α 不能 CI exclude 0 NEG".
    """
    windows = _get_windows(result)
    wf_windows = [w for w in windows if str(w.get("window", "")).startswith("wf_")]
    target = None
    for w in wf_windows:
        if w.get("window") == oos_window_name:
            target = w
            break
    if target is None and wf_windows:
        # fallback: pick lexicographically-latest window
        target = sorted(wf_windows, key=lambda x: str(x.get("window", "")))[-1]
    if target is None:
        return _outcome("WF2", "oos_not_neg_significant", "STAT",
                        False, "no OOS window found", windows=[])
    ci = _same_gross_ci(target)
    p = _same_gross_p(target)
    point = _same_gross_point(target)
    if ci is None:
        return _outcome("WF2", "oos_not_neg_significant", "STAT",
                        False, "no CI on OOS window", windows=[target.get("window")])
    lo, hi = ci
    # NEG-significant if hi < 0 (entire CI is negative) OR p < 0.05 with neg point
    neg_sig = (hi < 0) or (p is not None and p < 0.05 and point is not None and point < 0)
    passed = not neg_sig
    return _outcome(
        "WF2", "oos_not_neg_significant", "STAT",
        passed,
        f"OOS window {target.get('window')} same_gross α point={point}, CI=[{lo:.4f},{hi:.4f}], p={p}; NEG-sig={neg_sig}",
        metric=point,
        threshold="CI hi ≥ 0 AND not (p<0.05 with neg point)",
        windows=[target.get("window")],
    )


def check_mt_by_corrected(result: dict, family_corrected_p: Optional[float] = None,
                          alpha: float = 0.05) -> dict:
    """MT: BH-Yekutieli corrected p across the v3 family < alpha.

    Caller must inject family_corrected_p (the variant's adjusted p value AFTER
    BY correction over the registered v3 family). If None, this gate emits
    PRE_REGISTERED_UNKNOWN status.
    """
    if family_corrected_p is None:
        return _outcome(
            "MT", "by_corrected_p_lt_alpha", "STAT",
            False,
            "family-level BY-corrected p not provided to gate eval; run v3_multi_test_correction.py separately",
            metric=None, threshold=f"<{alpha}", windows=None,
        )
    passed = family_corrected_p < alpha
    return _outcome(
        "MT", "by_corrected_p_lt_alpha", "STAT",
        passed,
        f"BY-corrected family p = {family_corrected_p:.4f}, threshold < {alpha}",
        metric=family_corrected_p, threshold=f"<{alpha}", windows=None,
    )


def check_bench_multi_benchmark_reported(result: dict) -> dict:
    """BENCH: CSI300 / ZZ500 / CSI1000 / EW-500 / cash-2% same-gross comparison reported.

    v3 §2.1 line: "CSI300 / ZZ500 / EW-500 / cash-2% 同 gross 对比表都要 report
    (不能只看一个 bench)". Any missing → fail.

    Junyan ratify #13 (v3 Phase A 2026-05-28 PM2):
      - REQUIRED: csi300, zz500/csi500, csi1000, ew500, cash2pct.
        SSE50 is OPTIONAL (informational).
        HSI is intentionally ABSENT from this version (cross-market regime
        outside our panel).
      - A benchmark "key present" with a STUB value (e.g. string
        "not_available_in_panel") does NOT count as reported. The curve must
        be a non-empty list of equity points.

    The gate detects benchmarks in three places:
      A. result._meta.benchmarks_reported (list of friendly names)
      B. result.benchmarks (dict of curves; only list-of-points counts)
      C. per-window alpha keys (e.g. alpha.same_gross_vs_csi300)
    """
    required = {"csi300", "zz500", "csi1000", "ew500", "cash2pct"}
    found = set()
    stub_only: dict[str, str] = {}  # benchmarks present as STUB (not list)

    def _classify(name: str) -> Optional[str]:
        n = str(name).lower().replace("-", "").replace("_", "").replace(" ", "")
        if "csi300" in n or "300sh" in n or "000300" in n: return "csi300"
        if ("zz500" in n or "csi500" in n or "000905" in n or "399905" in n
                or ("500" in n and "csi" in n) or n == "ew500samegross"):
            # Disambiguate ew500 vs csi500:
            if "ew" in n or "equalweight" in n: return "ew500"
            return "zz500"
        if "csi1000" in n or "zz1000" in n or "000852" in n or "399852" in n:
            return "csi1000"
        if "ew500" in n or n == "ew" or "equalweight" in n: return "ew500"
        if "cash" in n: return "cash2pct"
        return None

    # Variant B (precedence): top-level benchmarks dict — the curve itself is
    # the source of truth. Must be a non-empty list of points. Stub strings
    # like "not_available_in_panel" do NOT count, even if other places claim it.
    bench_dict = result.get("benchmarks", {})
    if isinstance(bench_dict, dict):
        for key, curve in bench_dict.items():
            cls = _classify(key)
            if cls is None:
                continue
            if isinstance(curve, list) and len(curve) > 0:
                found.add(cls)
            else:
                # stub like "not_available_in_panel" — record but don't credit
                stub_only[cls] = str(curve)[:60]

    # Variant A: meta.benchmarks_reported = [...] (declarative claim — only
    # credit if NOT contradicted by a stub in the benchmarks dict).
    meta = result.get("_meta", {})
    rep = meta.get("benchmarks_reported") or meta.get("benchmarks") or []
    for b in rep:
        cls = _classify(b)
        if cls and cls not in stub_only:
            found.add(cls)

    # Variant C: per-window alpha keys (e.g. alpha.same_gross_vs_csi300).
    # Same rule — declarative; stub in benchmarks dict overrides.
    for w in _get_windows(result):
        a = w.get("alpha", {})
        for key in a.keys():
            cls = _classify(key)
            if cls and cls not in stub_only:
                found.add(cls)

    missing = sorted(required - found)
    passed = not missing
    if passed:
        reason = (
            f"all required benchmarks present as non-empty curves: "
            f"{sorted(found)}"
        )
    else:
        parts = [f"missing={missing}"]
        if stub_only:
            parts.append(f"stub_only={stub_only} (key present but no curve)")
        parts.append(f"found={sorted(found)}")
        reason = "; ".join(parts)
    return _outcome(
        "BENCH", "multi_benchmark_reported", "STAT",
        passed,
        reason,
        metric=len(found),
        threshold="csi300, zz500, csi1000, ew500, cash2pct ALL required as non-empty curves "
                  "(SSE50 optional, HSI absent per Junyan #13)",
        windows=None,
    )


def check_nosw_not_single_window(result: dict) -> dict:
    """NOSW: 不能只靠 20yr 单窗 — full-sample exclude 0 POS 但 wf 3/5 不过 → fail.

    v3 §2.1 last bullet: "不能只靠 20yr full-sample 单窗".
    Defined: if (full-sample same_gross excludes 0 on POS side) but
    (walk-forward 3/5 pos point ≥ 0 fails), this is the bad-pattern and we fail.

    Junyan ratify #3 (v3 Phase A 2026-05-28 PM2):
      Walk-forward-only bundles (no full-sample window present) cannot fail this
      gate AND must not silently pass — the gate condition is undefined. Return
      verdict='NA' (not blocking). Bundle completeness is checked separately via
      check_bundle_completeness (so a CANDIDATE bundle that drops full-sample
      will still get caught).

    v3 Phase B-fix cleanup (Junyan PM4 2026-05-28 NOSW bug):
      Previously the full-sample window detector matched only the exact lower-
      case names ``("20yr", "full", "full_sample")``. The V3C-α1 manifest names
      the full window ``full_20yr`` (e.g. ``full_20yr``, ``full_sample``,
      ``full_2006_2026``), which the exact-match check silently missed. The
      gate then reported NA "no full-sample window present" — incorrect, since
      the bundle did contain a full window. Fix: match by prefix (``full*`` or
      exact ``20yr``), consistent with the IMPL7 detector. Logic spec:
        - FAIL only if (full exists AND full α CI excludes 0 POS) AND
          (walk-forward is present AND < 3/5 pos point ≥ 0).
        - PASS otherwise (including: full present but CI straddles 0, or wf
          passes 3/5 pos).
        - NA only if neither full nor walk-forward windows are present in the
          bundle (gate condition undefined).
    """
    windows = _get_windows(result)
    full = None
    for w in windows:
        wname = str(w.get("window", "")).lower()
        # v3 Phase B-fix: prefix-based detection so 'full_20yr', 'full_sample',
        # 'full_2006_2026' all match (previously only the exact 3 names did).
        if wname.startswith("full") or wname == "20yr":
            full = w
            break
    # Walk-forward count of pos-point windows
    wf = [w for w in windows if str(w.get("window", "")).startswith("wf_")]
    n_wf = len(wf)
    n_pos = sum(1 for w in wf if (_same_gross_point(w) or 0) >= 0)
    if full is None and n_wf == 0:
        # Neither full-sample nor walk-forward windows present → gate condition
        # undefined. NA per Junyan #3 + PM4. Bundle completeness is enforced by
        # check_bundle_completeness (separate gate id BUNDLE) against the
        # manifest's declared test_plan.windows.
        return _outcome(
            "NOSW", "not_single_window_only", "STAT",
            True,
            ("neither full-sample nor walk-forward windows present; NA "
             "(non-blocking). Bundle completeness is checked by gate BUNDLE "
             "against manifest."),
            metric=None,
            threshold="full POS sig REQUIRES wf 3/5 pos (only checked when full present)",
            windows=None,
            verdict="NA",
        )
    if full is None:
        # Walk-forward-only bundle: cherry-pick risk is not exercisable without
        # a full-sample window, so this is non-blocking NA per Junyan #3.
        return _outcome(
            "NOSW", "not_single_window_only", "STAT",
            True,
            (f"no full-sample window present (walk-forward only, {n_wf} wf "
             f"windows, {n_pos} POS); NA (non-blocking). Bundle completeness "
             "is checked by gate BUNDLE against manifest."),
            metric=None,
            threshold="full POS sig REQUIRES wf 3/5 pos (only checked when full present)",
            windows=[w.get("window") for w in wf],
            verdict="NA",
        )
    pt = _same_gross_point(full)
    ci = _same_gross_ci(full)
    full_pos_sig = (ci is not None and ci[0] > 0)  # full CI excludes 0 on POS
    # Phase B-fix PM4: only score wf_3_of_5_ok when wf is actually present.
    wf_3_of_5_ok = (n_wf >= 5 and n_pos >= 3)
    # Bad pattern only triggers when full DOES exclude 0 POS AND wf evidence
    # contradicts it. Full straddling 0 (typical for a not-yet-confirmed
    # signal) gives PASS = no cherry-pick risk on this gate.
    bad_pattern = full_pos_sig and (n_wf >= 5) and (not wf_3_of_5_ok)
    passed = not bad_pattern
    ci_str = f"[{ci[0]:+.4f},{ci[1]:+.4f}]" if ci is not None else "n/a"
    reason = (
        f"full-sample window='{full.get('window')}' "
        f"same_gross α point={pt if pt is None else round(pt, 4)} CI={ci_str} "
        f"POS-sig={full_pos_sig}; walk-forward {n_pos}/{n_wf} POS; "
        f"bad_pattern={bad_pattern}"
    )
    return _outcome(
        "NOSW", "not_single_window_only", "STAT",
        passed,
        reason,
        metric=pt,
        threshold="not (full POS-sig AND wf present AND wf < 3/5 pos)",
        windows=[full.get("window")] + [w.get("window") for w in wf],
    )


def check_bundle_completeness(result: dict, manifest: Optional[dict]) -> dict:
    """BUNDLE: result must contain a window-result for every manifest test_plan window.

    v3 Phase A Junyan ratify #3 (2026-05-28 PM2): NOSW becomes NA when there is
    no full-sample window; we move the "did you actually run full-sample?" check
    here as an independent completeness gate.

    Behavior:
      - If manifest is None, return NA (cannot enforce without a declared
        test_plan). Pre-registration gates already cover the manifest-absent
        case (PRE1 fails) so we do not double-count.
      - For each manifest.test_plan.windows[].name, check the result has a
        matching window key. Any missing → FAIL with the list.
    """
    if manifest is None:
        return _outcome(
            "BUNDLE", "bundle_completeness", "AUDIT",
            True,
            "no manifest provided; bundle completeness check NA "
            "(PRE1 already fails when manifest absent)",
            metric=None,
            threshold="all manifest.test_plan.windows must appear in result",
            windows=None,
            verdict="NA",
        )
    test_plan = (manifest.get("test_plan") or {}) if isinstance(manifest, dict) else {}
    declared = [w.get("name") for w in (test_plan.get("windows") or [])
                if isinstance(w, dict) and w.get("name")]
    if not declared:
        return _outcome(
            "BUNDLE", "bundle_completeness", "AUDIT",
            True,
            "manifest.test_plan.windows empty or missing; no completeness "
            "constraint to enforce",
            metric=None,
            threshold="all declared windows must appear in result",
            windows=None,
            verdict="NA",
        )
    actual_windows = {str(w.get("window", "")) for w in _get_windows(result)}
    missing = [name for name in declared if name not in actual_windows]
    passed = not missing
    if passed:
        reason = (
            f"bundle complete: {len(declared)} declared windows all present "
            f"({sorted(declared)})"
        )
    else:
        reason = (
            f"bundle incomplete: missing window-results for {missing}; "
            f"declared={sorted(declared)}, observed={sorted(actual_windows)}"
        )
    return _outcome(
        "BUNDLE", "bundle_completeness", "AUDIT",
        passed,
        reason,
        metric=f"{len(declared) - len(missing)}/{len(declared)}",
        threshold="all manifest.test_plan.windows present",
        windows=sorted(actual_windows),
    )


# -------------------- Implementation gates --------------------

def check_impl1_max_positions(result: dict) -> dict:
    windows = _get_windows(result)
    if not windows:
        return _outcome("IMPL1", "max_positions_enforced", "IMPL",
                        False, "no windows found", metric=None, threshold=True, windows=[])
    bad = []
    for w in windows:
        a = _audit(w)
        if not a.get("max_positions_enforced", False):
            bad.append(w.get("window"))
    passed = not bad
    return _outcome(
        "IMPL1", "max_positions_enforced", "IMPL",
        passed,
        f"max_positions_enforced=True in all windows" if passed
        else f"failed in: {bad}",
        metric=len(windows) - len(bad), threshold="all windows == True",
        windows=[w.get("window") for w in windows],
    )


def check_impl2_avg_gross_30(result: dict, min_gross: float = 0.30) -> dict:
    windows = _get_windows(result)
    if not windows:
        return _outcome("IMPL2", "avg_gross_min_30pct", "IMPL",
                        False, "no windows", metric=None, threshold=min_gross, windows=[])
    failing = []
    grosses = []
    for w in windows:
        a = _audit(w)
        g = a.get("avg_gross_pct")
        if g is None:
            g = w.get("avg_gross")
        if g is None:
            failing.append((w.get("window"), None))
            continue
        g = float(g)
        grosses.append(g)
        if g < min_gross:
            failing.append((w.get("window"), g))
    passed = not failing
    avg_of_avgs = sum(grosses) / len(grosses) if grosses else None
    return _outcome(
        "IMPL2", "avg_gross_min_30pct", "IMPL",
        passed,
        f"avg_gross OK in all windows (mean of window avgs={avg_of_avgs:.4f})"
        if passed else
        f"failed: {failing}",
        metric=avg_of_avgs, threshold=min_gross,
        windows=[w.get("window") for w in windows],
    )


def check_impl3_median_pos_ge_2(result: dict, min_median: float = 2.0) -> dict:
    """IMPL3: long-term median_n_positions ≥ 2 (anti-single-bet)."""
    windows = _get_windows(result)
    if not windows:
        return _outcome("IMPL3", "median_pos_ge_2", "IMPL",
                        False, "no windows", metric=None, threshold=min_median, windows=[])
    failing = []
    medians = []
    for w in windows:
        a = _audit(w)
        m = a.get("median_n_positions")
        if m is None:
            m = w.get("median_n_positions")
        if m is None:
            failing.append((w.get("window"), None))
            continue
        m = float(m)
        medians.append(m)
        if m < min_median:
            failing.append((w.get("window"), m))
    passed = not failing
    return _outcome(
        "IMPL3", "median_pos_ge_2", "IMPL",
        passed,
        f"median_n_positions ≥ {min_median} in all windows" if passed
        else f"failed: {failing}",
        metric=min(medians) if medians else None, threshold=min_median,
        windows=[w.get("window") for w in windows],
    )


def check_impl4_turnover_le_200(result: dict, max_turnover_ratio: float = 2.0) -> dict:
    """IMPL4: turnover_annual_ratio ≤ 2.0 (= 200% annual book turnover).

    Per Junyan ratify #2 (v3 Phase A 2026-05-28 PM2):
      - Canonical audit field is `turnover_annual_ratio` (unit-less).
      - `turnover_annual_pct` is a DEPRECATED ALIAS holding the SAME ratio value
        (the historical name is misleading; engine v2-audit still emits both).
      - Both are READ AS RATIO. Threshold compare: ratio <= 2.0.
      - Display layer multiplies by 100 to render as "%".

    Compare modes:
      ratio_value     interpretation       display
      0.14            14% annual turnover  "14.0%"
      14.06           1406% (very high)    "1406.0%"
    """
    windows = _get_windows(result)
    if not windows:
        return _outcome("IMPL4", "turnover_le_200pct", "IMPL",
                        False, "no windows", metric=None,
                        threshold=f"{max_turnover_ratio} (= {max_turnover_ratio*100:.0f}%)",
                        windows=[])
    failing = []
    turnovers = []
    field_used: list[str] = []
    for w in windows:
        a = _audit(w)
        # Primary: read canonical _ratio field (engine v3 Phase A onward).
        t = a.get("turnover_annual_ratio")
        if t is not None:
            field_used.append("turnover_annual_ratio")
        else:
            # Fallback: legacy alias. Same numeric value (ratio, NOT percent).
            t = a.get("turnover_annual_pct")
            if t is not None:
                field_used.append("turnover_annual_pct (deprecated alias, read as ratio)")
        if t is None:
            failing.append((w.get("window"), None))
            continue
        t = float(t)
        turnovers.append(t)
        if t > max_turnover_ratio:
            # Display as percent for reader clarity (per Junyan ratify #2 display rule).
            failing.append((w.get("window"), f"{t*100:.1f}%"))
    passed = not failing
    if passed and turnovers:
        max_t = max(turnovers)
        reason = (
            f"turnover ≤ {max_turnover_ratio*100:.0f}% in all windows "
            f"(worst window: {max_t*100:.1f}%)"
        )
    elif passed:
        reason = "no turnover data but no failures (all None)"
    else:
        reason = (
            f"turnover > {max_turnover_ratio*100:.0f}% threshold; "
            f"failed windows (window, observed turnover): {failing}"
        )
    return _outcome(
        "IMPL4", "turnover_le_200pct", "IMPL",
        passed,
        reason,
        metric=max(turnovers) if turnovers else None,
        threshold=f"{max_turnover_ratio} (= {max_turnover_ratio*100:.0f}% annual)",
        windows=[w.get("window") for w in windows],
    )


def check_impl5_max_dd_floor(result: dict, dd_floor: float = -0.25) -> dict:
    """IMPL5: per-window max_drawdown >= floor (= ≥ -25% — i.e. no -30% windows)."""
    windows = _get_windows(result)
    if not windows:
        return _outcome("IMPL5", "max_dd_floor_25pct", "IMPL",
                        False, "no windows", metric=None, threshold=dd_floor, windows=[])
    failing = []
    dds = []
    for w in windows:
        dd = w.get("max_drawdown")
        if dd is None:
            failing.append((w.get("window"), None))
            continue
        dd = float(dd)
        dds.append(dd)
        if dd < dd_floor:
            failing.append((w.get("window"), dd))
    passed = not failing
    return _outcome(
        "IMPL5", "max_dd_floor_25pct", "IMPL",
        passed,
        f"max_dd >= {dd_floor} in all windows" if passed
        else f"failed: {failing}",
        metric=min(dds) if dds else None, threshold=dd_floor,
        windows=[w.get("window") for w in windows],
    )


def check_impl6_sample_size(result: dict, min_dates: int = 250) -> dict:
    """IMPL6: ≥ 250 trade dates per window."""
    windows = _get_windows(result)
    if not windows:
        return _outcome("IMPL6", "sample_size_250", "IMPL",
                        False, "no windows", metric=None, threshold=min_dates, windows=[])
    failing = []
    n_dates_list = []
    for w in windows:
        a = _audit(w)
        n = a.get("n_trade_days")
        if n is None:
            n = w.get("alpha", {}).get("same_gross", {}).get("n_dates")
        if n is None:
            failing.append((w.get("window"), None))
            continue
        n = int(n)
        n_dates_list.append(n)
        if n < min_dates:
            failing.append((w.get("window"), n))
    passed = not failing
    return _outcome(
        "IMPL6", "sample_size_250", "IMPL",
        passed,
        f"all windows ≥ {min_dates} trade dates" if passed
        else f"failed: {failing}",
        metric=min(n_dates_list) if n_dates_list else None, threshold=min_dates,
        windows=[w.get("window") for w in windows],
    )


def check_impl7_post_cost_alpha_positive(result: dict,
                                         baseline_cost_rt: float = 0.0040,
                                         optimistic_cost_rt: float = 0.0020,
                                         pessimistic_cost_rt: float = 0.0060,
                                         manifest: Optional[dict] = None,
                                         stage: str = "R&D") -> dict:
    """IMPL7: post-cost α positive — reads the multi-cost backtest grid.

    v3 Phase B-fix (Junyan PM3 2026-05-28 Bug 2 + Bug 3):

    Bug 2 (window selection): previously this gate searched `results` for
    windows named '20yr' / 'full' / 'full_sample' but the V3C-α1 manifest
    declares the full-sample window as 'full_20yr'. The lower-case `in (...)`
    check missed it, then fell back to `wf_2022_2026` (the OOS walk-forward
    window) and used the OOS α as if it were the full-sample α. Now we match
    any window whose name starts with 'full' OR is exactly '20yr' (case-
    insensitive).

    Bug 3 (double cost count): previously this gate computed
        net = same_gross_α - cost_rt × turnover × n_years
    But the engine's same_gross_α is ALREADY net of cost (fill loop deducts
    COMMISSION + STAMP + SLIPPAGE on every trade). Multiplying turnover by
    cost_rt and subtracting again double-counts cost. The new logic reads
    each cost scenario's REAL same_gross_α from result.cost_scenario_runs
    (3 backtests, 1 per cost scenario, all already net of their respective
    cost). PASS if baseline > 0 (R&D stage) or baseline AND pessimistic > 0
    (paper/capital promotion stage).

    Result-side schema expected:
      - result.cost_scenario_runs: list of per-(window,scenario) dicts; each
        has `window`, `cost_scenario`, `alpha.same_gross.point` (already net).
      - manifest.test_plan.cost_scenarios: declared scenarios (validates we
        ran what we said we'd run).

    Backward compat: if cost_scenario_runs absent we emit FAIL with a clear
    message (no silent fallback to the old double-count formula).

    stage = "R&D" | "paper_promotion" | "capital_promotion"
    """
    windows = _get_windows(result)

    # ── Bug 2 fix: identify the full-sample window using the manifest as
    # the source of truth when available, falling back to name-matching.
    full_window_name = None
    if manifest:
        plan = (manifest.get("test_plan") or {})
        declared_windows = plan.get("windows") or []
        for w in declared_windows:
            name = str(w.get("name", ""))
            # Manifest test_plan.windows[0] is the full-sample by convention,
            # but we identify it explicitly by name prefix to avoid coupling.
            if (name.lower().startswith("full")
                    or name.lower() in ("20yr", "full", "full_sample")):
                full_window_name = name
                break
    # If no manifest, scan result windows for a full-sample match.
    if full_window_name is None:
        for w in windows:
            wname = str(w.get("window", "")).lower()
            if (wname.startswith("full")
                    or wname in ("20yr", "full", "full_sample")):
                full_window_name = w.get("window")
                break
    if full_window_name is None:
        return _outcome("IMPL7", "post_cost_alpha_positive", "IMPL",
                        False,
                        "no full-sample window declared in manifest or present "
                        "in result (looking for 'full_*' / '20yr' / 'full_sample')",
                        metric=None, threshold=0.0, windows=[])

    # ── Bug 3 fix: read the multi-cost backtest grid directly. No analytic
    # double-deduction. Each scenario's same_gross.point is ALREADY net of
    # that scenario's cost vector (engine fill loop).
    cost_runs = result.get("cost_scenario_runs") or []
    if not isinstance(cost_runs, list) or not cost_runs:
        return _outcome(
            "IMPL7", "post_cost_alpha_positive", "IMPL",
            False,
            ("result.cost_scenario_runs missing or empty; cannot evaluate "
             "post-cost α without the per-scenario backtest grid. v3 Phase B "
             "engine emits 3 backtests per window (optimistic / baseline / "
             "pessimistic) — re-run with multi-cost dispatch."),
            metric=None, threshold=0.0, windows=[full_window_name],
        )

    # Build {scenario_name: same_gross_α_point} for the full-sample window.
    full_by_scenario: dict[str, dict] = {}
    for row in cost_runs:
        if str(row.get("window", "")) == str(full_window_name):
            scenario = row.get("cost_scenario")
            if scenario:
                full_by_scenario[scenario] = row

    # Manifest-vs-result cost-scenario cross-check. Per Junyan #4 we report
    # 3 scenarios and require baseline always, pessimistic at promotion.
    manifest_scenarios = None
    if manifest:
        plan = (manifest.get("test_plan") or {})
        manifest_scenarios = plan.get("cost_scenarios")
    scenarios_cross = ""
    if manifest_scenarios:
        missing_scenarios = [s for s in manifest_scenarios
                             if s not in full_by_scenario]
        if missing_scenarios:
            return _outcome(
                "IMPL7", "post_cost_alpha_positive", "IMPL",
                False,
                (f"manifest declares cost_scenarios={manifest_scenarios} but "
                 f"full_window='{full_window_name}' is missing scenarios "
                 f"{missing_scenarios} in result.cost_scenario_runs. Cannot "
                 f"compare baseline / pessimistic / optimistic α without all "
                 f"three. Re-run with multi-cost dispatch."),
                metric=None, threshold=0.0, windows=[full_window_name],
            )

    # ── Per-scenario α extraction (each already net of that scenario's cost).
    def _alpha_for(scenario_key: str) -> Optional[float]:
        row = full_by_scenario.get(scenario_key)
        if not row:
            return None
        a = (row.get("alpha") or {}).get("same_gross") or {}
        pt = a.get("point")
        return float(pt) if pt is not None else None

    alpha_opt = _alpha_for("optimistic_0.20_RT")
    alpha_base = _alpha_for("baseline_0.40_RT")
    alpha_pess = _alpha_for("pessimistic_0.60_RT")

    # If any required scenario missing α (e.g. insufficient_data), FAIL clearly.
    missing_alpha = []
    if alpha_base is None:
        missing_alpha.append("baseline_0.40_RT")
    if alpha_opt is None:
        missing_alpha.append("optimistic_0.20_RT")
    if alpha_pess is None:
        missing_alpha.append("pessimistic_0.60_RT")
    if missing_alpha:
        return _outcome(
            "IMPL7", "post_cost_alpha_positive", "IMPL",
            False,
            (f"missing same_gross.point on full_window='{full_window_name}' "
             f"for cost scenarios: {missing_alpha}"),
            metric=alpha_base, threshold=0.0, windows=[full_window_name],
        )

    # ── R&D: baseline > 0. paper/capital: baseline AND pessimistic > 0.
    passed = alpha_base > 0
    if stage in ("paper_promotion", "capital_promotion"):
        passed = passed and (alpha_pess > 0)

    reason = (
        f"window={full_window_name}; same_gross α (already net of cost) by scenario: "
        f"optimistic 0.20% RT={alpha_opt:+.4f}; "
        f"baseline 0.40% RT={alpha_base:+.4f}; "
        f"pessimistic 0.60% RT={alpha_pess:+.4f}; "
        f"stage={stage}{scenarios_cross}"
    )
    return _outcome(
        "IMPL7", "post_cost_alpha_positive", "IMPL",
        passed,
        reason,
        metric=alpha_base, threshold=0.0,
        windows=[full_window_name],
    )


# -------------------- Audit gates (R0 carry) --------------------

def check_aud1_audit_fields_present(result: dict) -> dict:
    """AUD1: audit fields exist: config_hash, data_hash, git_commit, engine_version."""
    required = ["config_hash", "data_hash", "git_commit", "engine_version"]
    windows = _get_windows(result)
    if not windows:
        return _outcome("AUD1", "audit_fields_present", "AUDIT",
                        False, "no windows", metric=None,
                        threshold=required, windows=[])
    failing = []
    for w in windows:
        a = _audit(w)
        missing = [k for k in required if not a.get(k)]
        if missing:
            failing.append((w.get("window"), missing))
    passed = not failing
    return _outcome(
        "AUD1", "audit_fields_present", "AUDIT",
        passed,
        f"all required audit fields present" if passed else f"missing: {failing}",
        metric=len(windows) - len(failing), threshold=required,
        windows=[w.get("window") for w in windows],
    )


def check_aud2_max_positions_enforced(result: dict) -> dict:
    """AUD2: audit.max_positions_enforced == True (R0 carry, dup of IMPL1 for traceability)."""
    return check_impl1_max_positions(result) | {"gate_id": "AUD2", "category": "AUDIT"}


def check_aud3_trade_log_full(result: dict) -> dict:
    """AUD3: trade_log_full exists (not only last 200).

    Per iter17 audit gates pattern, look for either explicit 'trade_log_full' key
    or n_total_trades_actual reaching the audited number.
    """
    windows = _get_windows(result)
    if not windows:
        return _outcome("AUD3", "trade_log_full", "AUDIT",
                        False, "no windows", metric=None,
                        threshold="trade_log_full present", windows=[])
    failing = []
    for w in windows:
        # detect explicit flag if present
        if "trade_log_full" in w:
            if not w["trade_log_full"]:
                failing.append((w.get("window"), "trade_log_full=False"))
            continue
        a = _audit(w)
        n_actual = a.get("n_total_trades_actual")
        n_total = w.get("n_total_trades")
        if n_actual is None and n_total is None:
            failing.append((w.get("window"), "no trade count audit"))
            continue
        if n_actual is not None and n_total is not None and abs(int(n_actual) - int(n_total)) > 0:
            failing.append((w.get("window"), f"trade count mismatch: actual={n_actual} vs reported={n_total}"))
    passed = not failing
    return _outcome(
        "AUD3", "trade_log_full", "AUDIT",
        passed,
        f"trade-log accounting consistent" if passed else f"failures: {failing}",
        metric=len(windows) - len(failing), threshold="n_total_trades_actual == n_total_trades",
        windows=[w.get("window") for w in windows],
    )


# -------------------- Pre-registration gates --------------------

def check_pre1_manifest_present(manifest: Optional[dict],
                                variant_id: Optional[str] = None) -> dict:
    """PRE1: manifest file present and matches schema v3_variant_manifest."""
    if manifest is None:
        return _outcome("PRE1", "manifest_present", "PRE",
                        False, "no manifest provided / file not found",
                        metric=None, threshold="schema=v3_variant_manifest", windows=None)
    schema = manifest.get("schema")
    if schema != "v3_variant_manifest":
        return _outcome("PRE1", "manifest_present", "PRE",
                        False, f"schema mismatch: {schema}",
                        metric=None, threshold="v3_variant_manifest", windows=None)
    m_variant = manifest.get("variant", {})
    if variant_id is not None and m_variant.get("variant_id") != variant_id:
        return _outcome("PRE1", "manifest_present", "PRE",
                        False,
                        f"manifest variant_id={m_variant.get('variant_id')!r}, expected {variant_id!r}",
                        metric=None, threshold=variant_id, windows=None)
    required_fields = ["registered_at", "hypothesis", "causal_logic_label",
                       "expected_failure_modes"]
    missing = [k for k in required_fields if not m_variant.get(k)]
    if missing:
        return _outcome("PRE1", "manifest_present", "PRE",
                        False, f"manifest missing required fields: {missing}",
                        metric=None, threshold=required_fields, windows=None)
    return _outcome("PRE1", "manifest_present", "PRE",
                    True, f"manifest schema OK; variant_id={m_variant.get('variant_id')}",
                    metric=None, threshold="schema+fields", windows=None)


def check_pre2_registered_before_run(manifest: Optional[dict],
                                     result: dict) -> dict:
    """PRE2: manifest.registered_at < earliest backtest created_at."""
    if manifest is None:
        return _outcome("PRE2", "registered_before_run", "PRE",
                        False, "no manifest", metric=None,
                        threshold="manifest.registered_at < audit.created_at",
                        windows=None)
    registered_at = (manifest.get("variant", {}) or {}).get("registered_at")
    if not registered_at:
        return _outcome("PRE2", "registered_before_run", "PRE",
                        False, "manifest.variant.registered_at missing",
                        metric=None, threshold="ISO timestamp", windows=None)
    windows = _get_windows(result)
    created_ats = []
    for w in windows:
        a = _audit(w)
        ts = a.get("created_at") or a.get("run_at") or result.get("_meta", {}).get("created_at")
        if ts:
            created_ats.append(ts)
    if not created_ats:
        return _outcome("PRE2", "registered_before_run", "PRE",
                        False,
                        "no audit.created_at on any window; cannot prove pre-registration ordering",
                        metric=None, threshold="audit.created_at required",
                        windows=[w.get("window") for w in windows])
    earliest = min(created_ats)
    passed = registered_at < earliest
    return _outcome(
        "PRE2", "registered_before_run", "PRE",
        passed,
        f"registered_at={registered_at} vs earliest_run={earliest}",
        metric=None, threshold="registered_at < created_at",
        windows=[w.get("window") for w in windows],
    )


def check_pre3_hypothesis_immutable(manifest: Optional[dict]) -> dict:
    """PRE3: hypothesis_lock_hash present and matches manifest body hash.

    Caller is expected to populate hypothesis_lock_hash at registration time;
    we just verify it's been declared (immutability enforced via git/branch,
    not by this module).
    """
    if manifest is None:
        return _outcome("PRE3", "hypothesis_immutable", "PRE",
                        False, "no manifest", metric=None,
                        threshold="hypothesis_lock_hash declared", windows=None)
    v = manifest.get("variant", {}) or {}
    locked_hash = v.get("hypothesis_lock_hash")
    declared = bool(locked_hash)
    if not declared:
        return _outcome("PRE3", "hypothesis_immutable", "PRE",
                        False, "manifest.variant.hypothesis_lock_hash not declared",
                        metric=None, threshold="non-empty sha256 string", windows=None)
    return _outcome(
        "PRE3", "hypothesis_immutable", "PRE",
        True,
        f"hypothesis_lock_hash declared (immutability enforced via git/branch)",
        metric=None, threshold="declared", windows=None,
    )


# -------------------- selftest --------------------

def _synthetic_pass() -> dict:
    """Build a synthetic backtest result that passes every gate.

    Updated for v3 Phase A (Junyan ratify #13): benchmarks must be non-empty
    curves, not just key presence. Includes csi1000 (mandatory) and a 20yr
    full-sample window so NOSW can evaluate (not NA).

    Updated for v3 Phase B-fix (Junyan PM3 Bug 2 + Bug 3): includes a
    `full_20yr` window AND `cost_scenario_runs` with 3 cost scenarios on
    the full window so the rewritten IMPL7 can evaluate.
    """
    _curve = [
        {"date": f"2024010{d}", "equity": 10_000_000.0 * (1 + 0.01 * d)}
        for d in range(1, 6)
    ]
    wf_windows = [
        {
            "variant": "synthetic_pass",
            "window": w,
            "max_drawdown": -0.1,
            "avg_gross": 0.40,
            "median_n_positions": 8.0,
            "n_total_trades": 1000,
            "audit": {
                "engine_version": "fast-v2-audit",
                "config_hash": "deadbeef",
                "data_hash": "cafebabe",
                "git_commit": "abc123",
                "max_positions_enforced": True,
                "avg_gross_pct": 0.40,
                "median_n_positions": 8.0,
                "turnover_annual_ratio": 1.5,
                "n_trade_days": 970,
                "n_total_trades_actual": 1000,
                "n_years": 4.0,
                "created_at": "2026-06-02T00:00:00Z",
            },
            "alpha": {
                "raw": {"point": 0.10, "lo": 0.05, "hi": 0.15,
                        "p_value": 0.01, "excludes_zero": True},
                "same_gross": {"point": 0.15, "lo": 0.05, "hi": 0.25,
                               "p_value": 0.01,
                               "excludes_zero": True, "n_dates": 970},
            },
        }
        for w in ("wf_2006_2010", "wf_2010_2014", "wf_2014_2018",
                  "wf_2018_2022", "wf_2022_2026")
    ]
    # Full-sample window (so IMPL7 can find it).
    full_window = {
        "variant": "synthetic_pass",
        "window": "full_20yr",
        "max_drawdown": -0.15,
        "avg_gross": 0.40,
        "median_n_positions": 8.0,
        "n_total_trades": 5000,
        "audit": {
            "engine_version": "fast-v2-audit",
            "config_hash": "deadbeef",
            "data_hash": "cafebabe",
            "git_commit": "abc123",
            "max_positions_enforced": True,
            "avg_gross_pct": 0.40,
            "median_n_positions": 8.0,
            "turnover_annual_ratio": 1.5,
            "n_trade_days": 4900,
            "n_total_trades_actual": 5000,
            "n_years": 20.0,
            "created_at": "2026-06-02T00:00:00Z",
        },
        "alpha": {
            "raw": {"point": 0.10, "lo": 0.05, "hi": 0.15,
                    "p_value": 0.01, "excludes_zero": True},
            "same_gross": {"point": 0.20, "lo": 0.10, "hi": 0.30,
                           "p_value": 0.01,
                           "excludes_zero": True, "n_dates": 4900},
        },
    }
    return {
        "_meta": {
            "benchmarks_reported": [
                "EW-500 same-gross",
                "CSI300 same-gross",
                "ZZ500 same-gross",
                "CSI1000 same-gross",
                "cash_2pct",
            ],
            "created_at": "2026-06-01T00:00:00Z",
        },
        "benchmarks": {
            "ew_500": _curve,
            "csi300": _curve,
            "zz500": _curve,
            "csi1000": _curve,
            "cash_2pct": _curve,
        },
        "results": wf_windows + [full_window],
        # v3 Phase B-fix: IMPL7 reads cost_scenario_runs (3 per window).
        "cost_scenario_runs": [
            {"window": "full_20yr", "cost_scenario": "optimistic_0.20_RT",
             "alpha": {"same_gross": {"point": 0.25}}},
            {"window": "full_20yr", "cost_scenario": "baseline_0.40_RT",
             "alpha": {"same_gross": {"point": 0.20}}},
            {"window": "full_20yr", "cost_scenario": "pessimistic_0.60_RT",
             "alpha": {"same_gross": {"point": 0.15}}},
        ],
    }


def _synthetic_iter18_like() -> dict:
    """Build a synthetic result mirroring iter18 b1_b3 walkforward (expected FAIL)."""
    return {
        "_meta": {
            "benchmarks_reported": ["EW-500 same-gross"],
            "created_at": "2026-05-28T00:00:00Z",
        },
        "results": [
            {
                "variant": "iter18_like", "window": "wf_2006_2010",
                "max_drawdown": -0.174, "avg_gross": 0.137, "median_n_positions": 8.0,
                "n_total_trades": 2760,
                "audit": {
                    "engine_version": "fast-v2-audit",
                    "config_hash": "x", "data_hash": "y", "git_commit": "z",
                    "max_positions_enforced": True,
                    "avg_gross_pct": 0.137, "median_n_positions": 8.0,
                    "turnover_annual_ratio": 14.06,
                    "n_trade_days": 973, "n_total_trades_actual": 2760,
                    "n_years": 3.86,
                    "created_at": "2026-05-28T12:00:00Z",
                },
                "alpha": {
                    "raw": {"point": -0.26, "lo": -0.54, "hi": 0.19, "p_value": 0.21},
                    "same_gross": {"point": 1.275, "lo": -0.034, "hi": 4.471,
                                   "p_value": 0.063, "n_dates": 961,
                                   "excludes_zero": False},
                },
            },
            {
                "variant": "iter18_like", "window": "wf_2022_2026",
                "max_drawdown": -0.23, "avg_gross": 0.126, "median_n_positions": 8.0,
                "n_total_trades": 3368,
                "audit": {
                    "engine_version": "fast-v2-audit",
                    "config_hash": "x", "data_hash": "y", "git_commit": "z",
                    "max_positions_enforced": True,
                    "avg_gross_pct": 0.126, "median_n_positions": 8.0,
                    "turnover_annual_ratio": 12.65,
                    "n_trade_days": 1060, "n_total_trades_actual": 3368,
                    "n_years": 4.21,
                    "created_at": "2026-05-28T12:00:00Z",
                },
                "alpha": {
                    "raw": {"point": 0.034, "lo": -0.19, "hi": 0.31, "p_value": 0.78},
                    "same_gross": {"point": -0.284, "lo": -0.46, "hi": -0.059,
                                   "p_value": 0.016, "n_dates": 1058,
                                   "excludes_zero": True,
                                   "direction": "NEGATIVE"},
                },
            },
        ],
    }


def _selftest() -> int:
    errors = []

    # Test pass set on synthetic_pass.
    sp = _synthetic_pass()
    for fn, expected_pass, gate_id in [
        (check_wf1_walk_forward_3_of_5_pos, True, "WF1"),
        (check_wf2_oos_not_neg_sig, True, "WF2"),
        (check_bench_multi_benchmark_reported, True, "BENCH"),
        (check_nosw_not_single_window, True, "NOSW"),
        (check_impl1_max_positions, True, "IMPL1"),
        (check_impl2_avg_gross_30, True, "IMPL2"),
        (check_impl3_median_pos_ge_2, True, "IMPL3"),
        (check_impl5_max_dd_floor, True, "IMPL5"),
        (check_impl6_sample_size, True, "IMPL6"),
        (check_aud1_audit_fields_present, True, "AUD1"),
        (check_aud3_trade_log_full, True, "AUD3"),
    ]:
        out = fn(sp)
        if out["pass"] != expected_pass:
            errors.append(f"{gate_id} on synthetic_pass: got pass={out['pass']}, "
                          f"expected {expected_pass}; reason={out['reason']}")

    # IMPL4 turnover=1.5 -> pass.
    out = check_impl4_turnover_le_200(sp)
    if not out["pass"]:
        errors.append(f"IMPL4 on synthetic_pass: got fail; reason={out['reason']}")

    # IMPL4 alias path: if a result only has turnover_annual_pct (legacy) the
    # gate must still read it as ratio (Junyan ratify #2).
    alias_sp = json.loads(json.dumps(sp))   # deep copy via json
    for w in alias_sp["results"]:
        w["audit"].pop("turnover_annual_ratio", None)
        w["audit"]["turnover_annual_pct"] = 1.5   # legacy field, same numeric value
    out = check_impl4_turnover_le_200(alias_sp)
    if not out["pass"]:
        errors.append(
            f"IMPL4 alias fallback (turnover_annual_pct=1.5 read as ratio) should pass; "
            f"reason={out['reason']}"
        )
    # And alias > 2.0 must FAIL (anti-regression: don't divide by 100).
    alias_fail = json.loads(json.dumps(sp))
    for w in alias_fail["results"]:
        w["audit"].pop("turnover_annual_ratio", None)
        w["audit"]["turnover_annual_pct"] = 14.06   # iter18 actual value
    out = check_impl4_turnover_le_200(alias_fail)
    if out["pass"]:
        errors.append(
            f"IMPL4 alias=14.06 should FAIL (it is 1406% turnover); reason={out['reason']}"
        )

    # IMPL7 (v3 Phase B-fix Bug 2 + Bug 3): now reads per-scenario backtest α
    # from result.cost_scenario_runs; no analytic double-deduction.
    # synthetic_pass HAS a full_20yr window + cost_scenario_runs with all 3
    # scenarios > 0 → PASS R&D and paper.
    manifest_for_impl7 = {
        "test_plan": {
            "windows": [{"name": "full_20yr"}, {"name": "wf_2006_2010"},
                        {"name": "wf_2010_2014"}, {"name": "wf_2014_2018"},
                        {"name": "wf_2018_2022"}, {"name": "wf_2022_2026"}],
            "cost_scenarios": ["optimistic_0.20_RT", "baseline_0.40_RT",
                               "pessimistic_0.60_RT"],
        }
    }
    out = check_impl7_post_cost_alpha_positive(sp, manifest=manifest_for_impl7)
    if not out["pass"]:
        errors.append(
            f"IMPL7 on synthetic_pass (baseline +0.20) should PASS; "
            f"reason={out['reason']}"
        )
    if "0.20%" not in out["reason"] or "0.40%" not in out["reason"] or "0.60%" not in out["reason"]:
        errors.append(
            f"IMPL7 reason must report all three scenarios (0.20/0.40/0.60% RT); "
            f"got: {out['reason']}"
        )
    out_paper = check_impl7_post_cost_alpha_positive(sp,
                                                      manifest=manifest_for_impl7,
                                                      stage="paper_promotion")
    if not out_paper["pass"]:
        errors.append(
            f"IMPL7 paper stage with all 3 scenarios > 0 should PASS; "
            f"reason={out_paper['reason']}"
        )

    # Borderline: baseline > 0 but pessimistic < 0 → R&D PASS, paper FAIL.
    sp_borderline = json.loads(json.dumps(sp))
    sp_borderline["cost_scenario_runs"] = [
        {"window": "full_20yr", "cost_scenario": "optimistic_0.20_RT",
         "alpha": {"same_gross": {"point": 0.05}}},
        {"window": "full_20yr", "cost_scenario": "baseline_0.40_RT",
         "alpha": {"same_gross": {"point": 0.02}}},
        {"window": "full_20yr", "cost_scenario": "pessimistic_0.60_RT",
         "alpha": {"same_gross": {"point": -0.03}}},
    ]
    out_b_rd = check_impl7_post_cost_alpha_positive(sp_borderline,
                                                     manifest=manifest_for_impl7,
                                                     stage="R&D")
    if not out_b_rd["pass"]:
        errors.append(
            f"IMPL7 borderline R&D should PASS (baseline +0.02); reason={out_b_rd['reason']}"
        )
    out_b_pp = check_impl7_post_cost_alpha_positive(sp_borderline,
                                                     manifest=manifest_for_impl7,
                                                     stage="paper_promotion")
    if out_b_pp["pass"]:
        errors.append(
            f"IMPL7 borderline paper should FAIL (pessimistic -0.03); reason={out_b_pp['reason']}"
        )

    # Baseline α < 0 → both stages FAIL.
    sp_neg = json.loads(json.dumps(sp))
    sp_neg["cost_scenario_runs"] = [
        {"window": "full_20yr", "cost_scenario": "optimistic_0.20_RT",
         "alpha": {"same_gross": {"point": -0.01}}},
        {"window": "full_20yr", "cost_scenario": "baseline_0.40_RT",
         "alpha": {"same_gross": {"point": -0.05}}},
        {"window": "full_20yr", "cost_scenario": "pessimistic_0.60_RT",
         "alpha": {"same_gross": {"point": -0.10}}},
    ]
    out_neg = check_impl7_post_cost_alpha_positive(sp_neg,
                                                    manifest=manifest_for_impl7)
    if out_neg["pass"]:
        errors.append(
            f"IMPL7 negative baseline α should FAIL R&D; reason={out_neg['reason']}"
        )

    # Missing cost_scenario_runs → FAIL with explicit message.
    sp_no_runs = json.loads(json.dumps(sp))
    sp_no_runs.pop("cost_scenario_runs", None)
    out_no = check_impl7_post_cost_alpha_positive(sp_no_runs,
                                                   manifest=manifest_for_impl7)
    if out_no["pass"]:
        errors.append("IMPL7 with no cost_scenario_runs should FAIL")
    if "cost_scenario_runs" not in out_no["reason"]:
        errors.append(
            f"IMPL7 missing-runs failure should mention cost_scenario_runs; "
            f"reason={out_no['reason']}"
        )

    # Missing one scenario → FAIL.
    sp_partial = json.loads(json.dumps(sp))
    sp_partial["cost_scenario_runs"] = [
        r for r in sp["cost_scenario_runs"]
        if r["cost_scenario"] != "pessimistic_0.60_RT"
    ]
    out_partial = check_impl7_post_cost_alpha_positive(sp_partial,
                                                        manifest=manifest_for_impl7)
    if out_partial["pass"]:
        errors.append("IMPL7 with partial cost_scenario_runs should FAIL")
    if "pessimistic_0.60_RT" not in out_partial["reason"]:
        errors.append(
            f"IMPL7 partial-runs failure should name the missing scenario; "
            f"reason={out_partial['reason']}"
        )

    # No full-sample window in result → FAIL with clear msg.
    sp_no_full = json.loads(json.dumps(sp))
    sp_no_full["results"] = [r for r in sp_no_full["results"]
                              if not str(r.get("window", "")).startswith("full")]
    # Without manifest hint, gate can't find a full window — and we keep wf_*
    # only, so it must FAIL.
    out_no_full = check_impl7_post_cost_alpha_positive(sp_no_full)
    if out_no_full["pass"]:
        errors.append("IMPL7 with no full window and no manifest should FAIL")
    if "no full-sample window" not in out_no_full["reason"]:
        errors.append(
            f"IMPL7 no-full-window failure should explain missing window; "
            f"reason={out_no_full['reason']}"
        )

    # NOSW: synthetic_pass HAS a full_20yr window now (Phase B-fix). It also
    # has wf 5/5 POS, so bad_pattern = (full POS-sig) AND (wf < 3/5) is FALSE
    # → NOSW PASS, verdict=PASS not NA.
    out_nosw = check_nosw_not_single_window(sp)
    if not out_nosw["pass"]:
        errors.append(f"NOSW on synthetic_pass should PASS (wf 5/5 ≥ 3/5); reason={out_nosw['reason']}")
    if out_nosw.get("verdict") != "PASS":
        errors.append(
            f"NOSW on synthetic_pass should be verdict=PASS not NA; "
            f"got {out_nosw.get('verdict')}; reason={out_nosw['reason']}"
        )

    # Walk-forward-only bundle (no full window) → NOSW returns NA.
    sp_wf_only = json.loads(json.dumps(sp))
    sp_wf_only["results"] = [r for r in sp_wf_only["results"]
                              if not str(r.get("window", "")).startswith("full")]
    out_nosw_wf = check_nosw_not_single_window(sp_wf_only)
    if out_nosw_wf.get("verdict") != "NA":
        errors.append(
            f"NOSW on wf-only bundle should be verdict=NA, "
            f"got verdict={out_nosw_wf.get('verdict')}; reason={out_nosw_wf['reason']}"
        )
    if not out_nosw_wf["pass"]:
        errors.append(f"NOSW NA semantics should still report pass=True (non-blocking)")

    # v3 Phase B-fix PM4 regression: Junyan diagnosed that the old detector
    # missed window name 'full_20yr' (prefix-match wasn't implemented), so a
    # bundle that DID contain a full-sample window was silently NA'd. Anti-
    # regression: a synthetic with full_20yr CI that STRADDLES 0 and walk-
    # forward 2/5 POS must verdict=PASS (no cherry-pick risk, because full
    # alone doesn't prove signal).
    sp_straddle = json.loads(json.dumps(sp))
    # Walk-forward: 2/5 pos (the other 3 windows go neg).
    flip_neg = ("wf_2014_2018", "wf_2018_2022", "wf_2022_2026")
    for w in sp_straddle["results"]:
        if w["window"] in flip_neg:
            w["alpha"]["same_gross"]["point"] = -0.05
    # Full window: CI straddles 0 (lo<0<hi), p=0.48 — like V3C-α1.
    for w in sp_straddle["results"]:
        if w["window"] == "full_20yr":
            w["alpha"]["same_gross"]["point"] = 0.09
            w["alpha"]["same_gross"]["lo"] = -0.14
            w["alpha"]["same_gross"]["hi"] = 0.40
            w["alpha"]["same_gross"]["p_value"] = 0.48
            w["alpha"]["same_gross"]["excludes_zero"] = False
            break
    out_nosw_straddle = check_nosw_not_single_window(sp_straddle)
    if not out_nosw_straddle["pass"]:
        errors.append(
            f"NOSW on full-straddles-0 + wf 2/5 should PASS "
            f"(no cherry-pick risk if full also straddles 0); "
            f"reason={out_nosw_straddle['reason']}"
        )
    if out_nosw_straddle.get("verdict") != "PASS":
        errors.append(
            f"NOSW on full-straddles-0 must verdict=PASS not NA "
            f"(full window IS present, just doesn't exclude 0 POS); "
            f"got {out_nosw_straddle.get('verdict')}; reason={out_nosw_straddle['reason']}"
        )
    if "full_20yr" not in out_nosw_straddle["reason"]:
        errors.append(
            f"NOSW reason should report which full window was identified; "
            f"reason={out_nosw_straddle['reason']}"
        )

    # NOSW positive case: full CI excludes 0 POS but wf 2/5 → FAIL (cherry-pick).
    sp_cherry = json.loads(json.dumps(sp_straddle))
    for w in sp_cherry["results"]:
        if w["window"] == "full_20yr":
            # Full CI excludes 0 POS (lo > 0).
            w["alpha"]["same_gross"]["point"] = 0.18
            w["alpha"]["same_gross"]["lo"] = 0.03
            w["alpha"]["same_gross"]["hi"] = 0.30
            w["alpha"]["same_gross"]["p_value"] = 0.02
            w["alpha"]["same_gross"]["excludes_zero"] = True
            break
    out_nosw_cherry = check_nosw_not_single_window(sp_cherry)
    if out_nosw_cherry["pass"]:
        errors.append(
            f"NOSW on full POS-sig + wf 2/5 must FAIL (cherry-pick); "
            f"reason={out_nosw_cherry['reason']}"
        )
    if out_nosw_cherry.get("verdict") != "FAIL":
        errors.append(
            f"NOSW on cherry-pick pattern must verdict=FAIL; "
            f"got {out_nosw_cherry.get('verdict')}; "
            f"reason={out_nosw_cherry['reason']}"
        )

    # NOSW: detect alternate full names (anti-regression for the PM4 bug —
    # 'full_sample' / 'FULL_20yr' / '20yr' should all be recognized).
    for alt_name in ("full_sample", "FULL_20yr", "20yr", "full_2006_2026"):
        sp_alt = json.loads(json.dumps(sp))
        for w in sp_alt["results"]:
            if w["window"] == "full_20yr":
                w["window"] = alt_name
                break
        out_alt = check_nosw_not_single_window(sp_alt)
        if out_alt.get("verdict") == "NA":
            errors.append(
                f"NOSW window-detector failed to recognize '{alt_name}' as a "
                f"full-sample window (regression for PM4 bug); "
                f"reason={out_alt['reason']}"
            )

    # BUNDLE: no manifest -> NA (pass=True).
    out_bundle_nomanifest = check_bundle_completeness(sp, None)
    if out_bundle_nomanifest.get("verdict") != "NA":
        errors.append(
            f"BUNDLE without manifest should be NA; "
            f"got verdict={out_bundle_nomanifest.get('verdict')}"
        )
    # BUNDLE: manifest declares wf_* matching synthetic_pass → PASS.
    bundle_manifest_match = {
        "schema": "v3_variant_manifest",
        "variant": {"variant_id": "x"},
        "test_plan": {
            "windows": [
                {"name": "wf_2006_2010"}, {"name": "wf_2010_2014"},
                {"name": "wf_2014_2018"}, {"name": "wf_2018_2022"},
                {"name": "wf_2022_2026"},
            ]
        },
    }
    out_bundle_ok = check_bundle_completeness(sp, bundle_manifest_match)
    if not out_bundle_ok["pass"]:
        errors.append(
            f"BUNDLE matching manifest should pass; reason={out_bundle_ok['reason']}"
        )
    # BUNDLE: manifest declares 20yr in addition → MUST FAIL (incomplete).
    bundle_manifest_missing = {
        "schema": "v3_variant_manifest",
        "variant": {"variant_id": "x"},
        "test_plan": {
            "windows": [
                {"name": "20yr"}, {"name": "wf_2006_2010"}, {"name": "wf_2010_2014"},
                {"name": "wf_2014_2018"}, {"name": "wf_2018_2022"},
                {"name": "wf_2022_2026"},
            ]
        },
    }
    out_bundle_miss = check_bundle_completeness(sp, bundle_manifest_missing)
    if out_bundle_miss["pass"]:
        errors.append(
            f"BUNDLE missing 20yr should FAIL; reason={out_bundle_miss['reason']}"
        )
    if "20yr" not in out_bundle_miss["reason"]:
        errors.append(
            f"BUNDLE failure should call out the missing window name; "
            f"reason={out_bundle_miss['reason']}"
        )

    # BENCH: synthetic_pass has all 5 required curves → PASS.
    out_bench = check_bench_multi_benchmark_reported(sp)
    if not out_bench["pass"]:
        errors.append(
            f"BENCH on synthetic_pass should pass; reason={out_bench['reason']}"
        )
    # BENCH: stub-only (string sentinel) must FAIL.
    sp_stub = json.loads(json.dumps(sp))
    sp_stub["benchmarks"]["csi300"] = "not_available_in_panel"
    out_bench_stub = check_bench_multi_benchmark_reported(sp_stub)
    if out_bench_stub["pass"]:
        errors.append(
            f"BENCH with csi300=stub should FAIL; reason={out_bench_stub['reason']}"
        )
    if "stub_only" not in out_bench_stub["reason"]:
        errors.append(
            f"BENCH stub failure should mention stub_only; "
            f"reason={out_bench_stub['reason']}"
        )
    # BENCH: missing csi1000 (was added by Junyan #13) must FAIL.
    sp_nokc = json.loads(json.dumps(sp))
    sp_nokc["benchmarks"].pop("csi1000", None)
    sp_nokc["_meta"]["benchmarks_reported"] = [
        b for b in sp_nokc["_meta"]["benchmarks_reported"] if "1000" not in b
    ]
    out_bench_nokc = check_bench_multi_benchmark_reported(sp_nokc)
    if out_bench_nokc["pass"]:
        errors.append(
            f"BENCH without csi1000 should FAIL; reason={out_bench_nokc['reason']}"
        )

    # Test fail-set on iter18-like.
    iter18 = _synthetic_iter18_like()
    expected_failures = [
        # Only 1/2 of wf windows are pos point (wf_2006_2010 = +1.27, wf_2022_2026 = -0.28)
        # With 2 windows it's 1/2; in our gate (n_total==5 forces required=3; for n_total<5
        # we use max(3, ceil(0.6*n)) which for n=2 -> max(3,2)=3, so requires 3 pos -> impossible.
        # The right behavior here: small synthetic count of 2 wf windows -> required=3, fail.
        (check_wf1_walk_forward_3_of_5_pos, "WF1"),
        (check_wf2_oos_not_neg_sig, "WF2"),         # OOS NEG-sig p=0.016
        (check_impl2_avg_gross_30, "IMPL2"),         # gross 12-14% < 30%
    ]
    for fn, gate_id in expected_failures:
        out = fn(iter18)
        if out["pass"]:
            errors.append(f"{gate_id} on iter18_like: got PASS but expected FAIL; reason={out['reason']}")

    # Pre-registration gates: manifest absent -> PRE1/2/3 all fail.
    out = check_pre1_manifest_present(None)
    if out["pass"]:
        errors.append("PRE1 no-manifest should fail")
    out = check_pre2_registered_before_run(None, sp)
    if out["pass"]:
        errors.append("PRE2 no-manifest should fail")
    out = check_pre3_hypothesis_immutable(None)
    if out["pass"]:
        errors.append("PRE3 no-manifest should fail")

    # Pre-registration with good manifest -> pass.
    good_manifest = {
        "schema": "v3_variant_manifest",
        "variant": {
            "variant_id": "v3c_test",
            "registered_at": "2026-05-29T00:00:00Z",
            "hypothesis": "test",
            "causal_logic_label": "Causal logic is unestablished: test variant.",
            "expected_failure_modes": ["test"],
            "hypothesis_lock_hash": "sha256:abc",
        },
    }
    sp_recent_run = _synthetic_pass()
    # sp's created_at = 2026-06-02; good_manifest.registered_at = 2026-05-29 -> PRE2 pass
    out = check_pre1_manifest_present(good_manifest, variant_id="v3c_test")
    if not out["pass"]:
        errors.append(f"PRE1 with good manifest should pass; reason={out['reason']}")
    out = check_pre2_registered_before_run(good_manifest, sp_recent_run)
    if not out["pass"]:
        errors.append(f"PRE2 with good manifest+run should pass; reason={out['reason']}")
    out = check_pre3_hypothesis_immutable(good_manifest)
    if not out["pass"]:
        errors.append(f"PRE3 with locked-hash manifest should pass; reason={out['reason']}")

    # MT gate without injection -> fail (PRE_REGISTERED_UNKNOWN).
    out = check_mt_by_corrected(sp, family_corrected_p=None)
    if out["pass"]:
        errors.append("MT with no family p should fail")
    out = check_mt_by_corrected(sp, family_corrected_p=0.01)
    if not out["pass"]:
        errors.append("MT with p=0.01 should pass")
    out = check_mt_by_corrected(sp, family_corrected_p=0.10)
    if out["pass"]:
        errors.append("MT with p=0.10 should fail at alpha=0.05")

    if errors:
        print("v3_gate_check_helpers selftest FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("v3_gate_check_helpers selftest PASSED")
    print("  Tested STAT/IMPL/AUDIT/PRE gates on synthetic pass/fail fixtures")
    return 0


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="v3 hard-gate check helper functions")
    parser.add_argument("--selftest", action="store_true", help="Run built-in selftest")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
