#!/usr/bin/env python3
"""multiple_testing.py — Stage 2b multiple-testing correction.

PROBLEM: in iter-1..7 we tested 5 factors simultaneously with raw t-stat > 2
thresholds. Under H0 (all factors zero alpha) the probability of ≥1 spurious
t > 2 is ~1 − 0.95⁵ ≈ 23%. With iter-1..7 spec-trial selection on top, the
effective Type-I rate is hopelessly inflated.

INSTITUTIONAL STANDARDS APPLIED:
  - Benjamini-Hochberg-Yekutieli (BH-Y) — controls false-discovery rate under
    arbitrary dependence (our 5 factor t-stats are correlated, so the
    standard BH requires the dependence-robust variant).
  - Harvey-Liu-Zhu (RFS 2016) — meta-study found that for US factor zoo,
    after multiple-testing correction the effective hurdle is t-stat > 3.0
    (not 2.0). Use as a HARDENED reference threshold, not a hard cutoff
    (HLZ is US-calibrated; A-share might calibrate elsewhere).
  - Bailey & López de Prado (JPM 2014) — Deflated Sharpe Ratio adjusts a
    headline Sharpe for (a) number of independent trials and (b) skew /
    kurtosis of the returns. Eliminates "lucky Sharpe" from spec mining.

OUTPUTS per factor:
  - raw p-value (from t-stat under N(0,1) approx)
  - BH-Y adjusted p-value (multi-test corrected)
  - HLZ-reference pass (t-stat > 3.0?)
  - Deflated Sharpe (if Sharpe input provided)
  - composite verdict: PASS / MAYBE / NOISE

We import nothing from scipy — implement the small functions directly.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


# ───────────────────────── Math helpers ──────────────────────────────────────

def _norm_sf(x: float) -> float:
    """Survival function of standard normal: P(Z > x). Uses erfc."""
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def _norm_ppf(p: float) -> float:
    """Inverse CDF (percentile) of standard normal — for the DSR critical value.

    Beasley-Springer-Moro approximation. p in (0, 1) exclusive. Good to ~1e-7
    over (1e-6, 1 - 1e-6).
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"p must be in (0,1), got {p}")
    # Coefficients (Beasley-Springer)
    a = [-3.969683028665376e+01,  2.209460984245205e+02,
         -2.759285104469687e+02,  1.383577518672690e+02,
         -3.066479806614716e+01,  2.506628277459239e+00]
    b = [-5.447609879822406e+01,  1.615858368580409e+02,
         -1.556989798598866e+02,  6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
          4.374664141464968e+00,  2.938163982698783e+00]
    d = [ 7.784695709041462e-03,  3.224671290700398e-01,
          2.445134137142996e+00,  3.754408661907416e+00]
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
               ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q / \
               (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
            ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)


# ───────────────────────── BH-Yekutieli FDR ──────────────────────────────────

def benjamini_hochberg_yekutieli(p_values: list[float]) -> list[float]:
    """Dependence-robust FDR adjustment (Benjamini-Yekutieli 2001).

    Equivalent to multiplying each p by N · H_N / rank, where H_N = Σ 1/i.
    Use when the underlying test statistics may be correlated (our case:
    momentum and value are negatively correlated; this is the safer choice
    over plain BH which assumes positive regression dependence).

    Returns adjusted p-values in the original input order.
    """
    n = len(p_values)
    if n == 0:
        return []
    H_n = sum(1.0 / i for i in range(1, n + 1))
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    adjusted = [0.0] * n
    # Monotone enforcement: walk from largest to smallest
    prev = 1.0
    for rank in range(n, 0, -1):
        idx, p = indexed[rank - 1]
        raw_adj = p * n * H_n / rank
        prev = min(prev, raw_adj)
        adjusted[idx] = min(1.0, prev)
    return adjusted


# ───────────────────────── HLZ reference ────────────────────────────────────

HLZ_T_THRESHOLD = 3.0    # Harvey-Liu-Zhu 2016 RFS table 6 — empirical post-MT cutoff


def hlz_pass(t_stat: float, threshold: float = HLZ_T_THRESHOLD) -> bool:
    """|t| > threshold (HLZ reference; default 3.0 for US-calibration)."""
    return abs(t_stat) > threshold


# ───────────────────────── Deflated Sharpe (Bailey-López 2014) ───────────────

EULER_MASCHERONI = 0.5772156649015329


def expected_max_sharpe_iid(n_trials: int) -> float:
    """E[max_{i ≤ N} SR_i] under H0:SR=0, asymptotic for large N (Bailey-López).

    SR* ≈ (1 - γ) Φ⁻¹(1 - 1/N) + γ Φ⁻¹(1 - 1/(N·e))
    where γ = Euler-Mascheroni. For N=1, returns 0. For N≥2 this is the
    Bonferroni-adjusted expected maximum under i.i.d. Gaussian SR estimators.
    """
    if n_trials < 2:
        return 0.0
    e = math.e
    return ((1 - EULER_MASCHERONI) * _norm_ppf(1.0 - 1.0 / n_trials)
            + EULER_MASCHERONI * _norm_ppf(1.0 - 1.0 / (n_trials * e)))


def deflated_sharpe(sharpe: float, n_obs: int, n_trials: int,
                    skew: float = 0.0, kurt: float = 3.0) -> dict:
    """Deflated Sharpe Ratio per Bailey & López de Prado (JPM 2014).

    Args:
        sharpe: the headline Sharpe (annualized OK; treated as a point est)
        n_obs: number of return observations the Sharpe was computed on
        n_trials: number of strategy specs / variants tried (selection bias)
        skew, kurt: 3rd / 4th moments of the returns (default normal: 0, 3)

    Returns dict with sr_star (the H0 expected max), z_dsr, p_value, pass_flag.
    DSR > 0.95 corresponds to ~2σ confidence that the Sharpe is real after
    accounting for selection + non-normality.
    """
    if n_obs < 8:
        return {"sr_star": None, "z": None, "p_value": None, "pass": False,
                "reason": f"n_obs={n_obs} < 8 — undefined"}
    sr_star = expected_max_sharpe_iid(n_trials)
    # Variance of Sharpe accounting for non-normality (Mertens 2002 / Lo 2002)
    var_sr = (1.0 - skew * sharpe + (kurt - 1) / 4.0 * sharpe ** 2) / (n_obs - 1)
    if var_sr <= 0:
        return {"sr_star": sr_star, "z": None, "p_value": None, "pass": False,
                "reason": "variance non-positive (degenerate moments)"}
    z = (sharpe - sr_star) / math.sqrt(var_sr)
    p_value = _norm_sf(z)
    return {"sr_star": sr_star, "z": z, "p_value": p_value,
            "pass": p_value < 0.05}


# ───────────────────────── Per-factor verdict ────────────────────────────────

def factor_verdict(t_stat: float, p_bhy: float,
                   hlz_threshold: float = HLZ_T_THRESHOLD,
                   bhy_alpha: float = 0.05) -> str:
    """Combine BH-Y + HLZ into PASS / MAYBE / NOISE.

    PASS  = BH-Y adjusted p < 0.05 AND |t| > HLZ threshold
    MAYBE = one of the two passes
    NOISE = neither passes
    """
    bhy_pass = (p_bhy < bhy_alpha)
    hlz_p = hlz_pass(t_stat, hlz_threshold)
    if bhy_pass and hlz_p:
        return "PASS"
    if bhy_pass or hlz_p:
        return "MAYBE"
    return "NOISE"


def t_to_p(t_stat: float) -> float:
    """Two-sided p-value from a t-statistic (N(0,1) approximation, n large)."""
    return 2.0 * _norm_sf(abs(t_stat))


# ───────────────────────── Self-test ────────────────────────────────────────

def _selftest() -> int:
    failures = []

    # 1) BH-Y monotonicity + bounds
    ps = [0.001, 0.01, 0.04, 0.20, 0.50]
    adj = benjamini_hochberg_yekutieli(ps)
    if any(a < p or a > 1.0 for a, p in zip(adj, ps)):
        failures.append(f"BH-Y bounds violated: {adj}")
    # adjusted must be non-decreasing in the original sort order... NO actually
    # it must be non-decreasing in the SORTED-by-p order, which we have.
    sorted_adj = [adj[i] for i in sorted(range(len(ps)), key=lambda j: ps[j])]
    if any(sorted_adj[i + 1] < sorted_adj[i] - 1e-9 for i in range(len(sorted_adj) - 1)):
        failures.append(f"BH-Y not monotone after sort: {sorted_adj}")

    # 2) HLZ threshold
    if hlz_pass(3.5) is not True:
        failures.append("HLZ |3.5|>3.0 should pass")
    if hlz_pass(2.5) is True:
        failures.append("HLZ |2.5|>3.0 should fail")
    if hlz_pass(-3.5) is not True:
        failures.append("HLZ |-3.5|>3.0 should pass (two-sided)")

    # 3) DSR sanity
    # No trials selection (n_trials=1) → sr_star=0, DSR just checks if SR/√(var/N) > 0
    d = deflated_sharpe(sharpe=1.5, n_obs=120, n_trials=1)
    if d["sr_star"] != 0.0:
        failures.append(f"DSR sr_star with N=1 expected 0, got {d['sr_star']}")
    # Big trial count → sr_star grows → harder to pass
    d2 = deflated_sharpe(sharpe=1.5, n_obs=120, n_trials=100)
    if d2["sr_star"] is None or d2["sr_star"] <= 0:
        failures.append(f"DSR sr_star with N=100 should grow: {d2}")
    if d2["z"] is None or d2["z"] >= d["z"]:
        failures.append(f"DSR z should be lower for higher trials: d.z={d['z']} d2.z={d2['z']}")

    # 4) Norm SF / PPF round trip
    for p in [0.01, 0.05, 0.50, 0.95, 0.99]:
        z = _norm_ppf(p)
        p_back = 1.0 - _norm_sf(z)
        if abs(p_back - p) > 1e-5:
            failures.append(f"PPF/SF round trip {p}: got {p_back}")

    # 5) Verdicts
    if factor_verdict(t_stat=4.0, p_bhy=0.001) != "PASS":
        failures.append("strong factor should PASS")
    if factor_verdict(t_stat=2.5, p_bhy=0.10) != "NOISE":
        failures.append("weak factor should NOISE")
    if factor_verdict(t_stat=3.5, p_bhy=0.20) != "MAYBE":
        failures.append("split factor should MAYBE")

    # 6) t→p
    if abs(t_to_p(1.96) - 0.05) > 0.01:
        failures.append(f"t→p at 1.96 expected ~0.05, got {t_to_p(1.96)}")

    if failures:
        print("SELFTEST FAILED multiple_testing:")
        for f in failures:
            print("  -", f)
        return 1
    print("SELFTEST PASSED multiple_testing")
    print("- BH-Yekutieli monotone + bounded")
    print("- HLZ threshold (3.0 default)")
    print("- Deflated Sharpe: sr_star grows with trials, z drops")
    print("- norm PPF/SF round trip")
    print("- Verdicts: PASS / MAYBE / NOISE")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Multiple-testing correction for IC analysis.")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--ic-input", default=str(REPO_ROOT / "public" / "data" / "ic_analysis.json"))
    p.add_argument("--out", default=str(REPO_ROOT / "public" / "data" / "ic_verdict.json"))
    p.add_argument("--n-trials", type=int, default=8,
                   help="Number of spec-trials (iter-1..7 + iter-8 ≈ 8)")
    p.add_argument("--hlz-threshold", type=float, default=HLZ_T_THRESHOLD)
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()

    if not Path(args.ic_input).exists():
        print(f"ERROR: {args.ic_input} missing — run ic_analysis.py first.", file=sys.stderr)
        return 1

    ic_data = json.load(open(args.ic_input))
    summary = ic_data.get("summary", {})

    # For each factor × horizon, extract t-stat and apply BH-Y
    keys = sorted(summary.keys())
    ts = [summary[k].get("t_stat") for k in keys]
    ns = [summary[k].get("n") or 0 for k in keys]

    # Use only items with valid t-stat for BH-Y
    valid = [(k, t, n) for k, t, n in zip(keys, ts, ns) if t is not None and n >= 12]
    raw_p = [t_to_p(t) for _, t, _ in valid]
    bhy_p = benjamini_hochberg_yekutieli(raw_p)

    verdicts = {}
    for (k, t, n), rp, ap in zip(valid, raw_p, bhy_p):
        v = factor_verdict(t, ap, hlz_threshold=args.hlz_threshold)
        verdicts[k] = {
            "t_stat": round(t, 4),
            "n_months": n,
            "raw_p": round(rp, 6),
            "bhy_adjusted_p": round(ap, 6),
            "hlz_pass": hlz_pass(t, args.hlz_threshold),
            "verdict": v,
            "mean_ic": round(summary[k].get("mean") or 0.0, 6),
            "icir": round(summary[k].get("icir") or 0.0, 4) if summary[k].get("icir") is not None else None,
        }

    # Also compute Deflated Sharpe — but we don't have per-factor Sharpe here.
    # Skip; DSR is for the strategy-level headline Sharpe, applied separately.

    # Headline counts
    counts = {"PASS": 0, "MAYBE": 0, "NOISE": 0}
    for v in verdicts.values():
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1

    out = {
        "_meta": {
            "generated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat(),
            "n_trials": args.n_trials,
            "hlz_threshold": args.hlz_threshold,
            "bhy_alpha": 0.05,
            "honesty": "BH-Y on raw t-stats from time-series IC; HLZ reference; no curve-fit",
        },
        "counts": counts,
        "verdicts": verdicts,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"=== Multiple-testing verdict ===")
    for k in sorted(verdicts.keys()):
        v = verdicts[k]
        print(f"  {k:20s}  t={v['t_stat']:+.3f}  n={v['n_months']:3d}  "
              f"raw_p={v['raw_p']:.4f}  BH-Y_p={v['bhy_adjusted_p']:.4f}  "
              f"HLZ={'Y' if v['hlz_pass'] else 'N'}  → {v['verdict']}")
    print(f"\nCounts: PASS={counts.get('PASS',0)}  MAYBE={counts.get('MAYBE',0)}  NOISE={counts.get('NOISE',0)}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
