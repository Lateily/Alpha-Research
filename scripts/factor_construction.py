#!/usr/bin/env python3
"""factor_construction.py — Barra USE4-style cross-sectional factor processing.

PURPOSE: replace our raw-then-percentile-rank composite with the standard
institutional pipeline:
  raw factor  →  winsorize ±Nσ  →  cap-weighted standardize  →  industry residualize
                                                                       ↓
                                                              cross-sectionally
                                                              orthogonal exposure

WHY: percentile rank is a non-linear monotone transform — it loses scale
information. Equal-weighted z-score is sensitive to outliers. Cap-weighted
z-score with industry residualization (Barra USE4 methodology) is the
documented institutional standard (see docs/strategy/research_2026-05-26/
institutional_synthesis.md, Section "Technique 1").

DESIGN: pure functions (no I/O, no state). Wired into satellite_strategy as
an OPTIONAL pre-composite step; iter-7 percentile pipeline still works when
this module isn't called.

NUMERICAL DISCIPLINE (per "宁愿犯错也不愿意找不出来错误在哪"):
  - Missing values stay None — never imputed silently.
  - Single-name cross-sections return 0.0 (neutral), not 50.0 fabrication.
  - Industries with <2 names are NOT residualized (preserves their raw z).
  - All-zero columns (degenerate) return 0.0 with a flag.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent


def _finite_float(x) -> Optional[float]:
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def winsorize(values: dict[str, Optional[float]], n_sigma: float = 3.0) -> dict[str, Optional[float]]:
    """Cross-sectional winsorization at ±n_sigma. PRESERVES None.

    Mean and stdev are computed on the FINITE non-None subset; the clipping
    bounds apply only to finite inputs. None stays None.
    """
    finite = {k: v for k, v in values.items() if _finite_float(v) is not None}
    n = len(finite)
    if n < 2:
        return dict(values)  # nothing meaningful to clip
    xs = [_finite_float(v) for v in finite.values()]
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    std = math.sqrt(var)
    if std == 0.0:
        return dict(values)  # constant column — clipping has no effect
    lo = mean - n_sigma * std
    hi = mean + n_sigma * std
    out = {}
    for k, v in values.items():
        f = _finite_float(v)
        if f is None:
            out[k] = None
        else:
            out[k] = max(lo, min(hi, f))
    return out


def cap_weighted_standardize(values: dict[str, Optional[float]],
                             mcap: dict[str, Optional[float]]) -> dict[str, Optional[float]]:
    """Standardize so cap-weighted mean = 0, equal-weighted std = 1 (Barra USE4).

    The asymmetric design is intentional: market-cap-weighted portfolio has
    zero factor exposure (the "neutral" benchmark), and equal-weighted scale
    sets the unit of factor exposure.

    Preserves None. Returns 0.0 for the degenerate cases (single name,
    zero-variance, no cap weights) so downstream rank-and-pick still works.
    """
    # Pair (value, mcap) on finite both
    finite = []
    for k, v in values.items():
        vf = _finite_float(v)
        mf = _finite_float(mcap.get(k))
        if vf is not None and mf is not None and mf > 0:
            finite.append((k, vf, mf))

    out = {k: None for k in values}
    if not finite:
        return out
    if len(finite) == 1:
        out[finite[0][0]] = 0.0
        return out

    total_cap = sum(mf for _, _, mf in finite)
    cap_wtd_mean = sum(vf * mf for _, vf, mf in finite) / total_cap

    # Equal-weighted std of centered values
    centered = [vf - cap_wtd_mean for _, vf, _ in finite]
    n = len(centered)
    var = sum(c ** 2 for c in centered) / (n - 1) if n > 1 else 0.0
    ew_std = math.sqrt(var)

    if ew_std == 0.0:
        for k, vf, _ in finite:
            out[k] = 0.0
        # values with no mcap (excluded from std calc) but with finite value:
        # they get the rebased centering only if we have a sensible scale —
        # without scale, neutral 0.0.
        for k, v in values.items():
            if out[k] is None and _finite_float(v) is not None:
                out[k] = 0.0
        return out

    for k, vf, _ in finite:
        out[k] = (vf - cap_wtd_mean) / ew_std

    # Names with value but no mcap: use the same center/scale (avoids dropping
    # them; their exposure is honest because we don't claim cap weighting for
    # them, but they participate in the equal-weighted scale).
    for k, v in values.items():
        if out[k] is None:
            vf = _finite_float(v)
            if vf is not None:
                out[k] = (vf - cap_wtd_mean) / ew_std

    return out


def industry_neutralize(values: dict[str, Optional[float]],
                        industry: dict[str, Optional[str]]) -> dict[str, Optional[float]]:
    """Residualize cross-sectional exposures vs industry dummies.

    Equivalent to: regress `values ~ industry_dummies` (no intercept other than
    the per-industry mean) and return residuals. Implementation: subtract the
    within-industry mean. Equivalent to OLS residual against a saturated
    industry-dummy regression with no other regressors.

    Industries with only 1 member CANNOT be meaningfully neutralized (residual
    would be 0 mechanically) — we leave their value unchanged (PRESERVES the
    original z-score). Missing industry → leave unchanged.

    Preserves None.
    """
    # Group finite values by industry
    by_ind: dict[str, list[tuple[str, float]]] = {}
    for k, v in values.items():
        f = _finite_float(v)
        if f is None:
            continue
        ind = industry.get(k)
        if ind is None or ind == "" or ind == "未知":
            continue
        by_ind.setdefault(ind, []).append((k, f))

    industry_mean: dict[str, float] = {}
    for ind, items in by_ind.items():
        if len(items) < 2:
            continue  # can't neutralize a 1-name industry
        industry_mean[ind] = sum(f for _, f in items) / len(items)

    out = {}
    for k, v in values.items():
        f = _finite_float(v)
        if f is None:
            out[k] = None
            continue
        ind = industry.get(k)
        m = industry_mean.get(ind) if ind else None
        out[k] = f - m if m is not None else f
    return out


def barra_construct(raw: dict[str, Optional[float]],
                    mcap: dict[str, Optional[float]],
                    industry: dict[str, Optional[str]],
                    *,
                    n_sigma: float = 3.0,
                    do_industry_neutralize: bool = True) -> dict[str, Optional[float]]:
    """Full pipeline: winsorize → cap-weighted standardize → industry residualize.

    Args:
        raw: ticker → raw factor value (or None)
        mcap: ticker → total market cap (or None)
        industry: ticker → industry label (or None)
        n_sigma: winsorize bound in std deviations (default 3.0 per USE4)
        do_industry_neutralize: skip step 3 if False

    Returns:
        dict ticker → Barra-style factor exposure (mean 0 cap-wtd, std 1 EW,
        industry-residual). Missing → None preserved.
    """
    w = winsorize(raw, n_sigma=n_sigma)
    z = cap_weighted_standardize(w, mcap)
    if do_industry_neutralize:
        z = industry_neutralize(z, industry)
    return z


# ───────────────────────── Self-test ────────────────────────────────────────

def _selftest() -> int:
    failures = []

    # 1) Winsorize basic
    vals = {"A": -100.0, "B": -0.5, "C": 0.0, "D": 0.5, "E": 100.0}
    w = winsorize(vals, n_sigma=2.0)
    # std with N=5: mean=0, var = (10000+0.25+0+0.25+10000)/4 ≈ 5000, std ≈ 70.7
    # so bounds are ±141.4 — extreme values DON'T get clipped at 2σ here because
    # they themselves dominate the std. (Known winsorize pathology: when
    # outliers are huge they inflate σ so clipping is ineffective.)
    # Try a different fixture: 99 zeros + 1 huge outlier.
    vals2 = {f"T{i}": 0.0 for i in range(99)}
    vals2["OUT"] = 1000.0
    w2 = winsorize(vals2, n_sigma=3.0)
    # std ≈ 100 (rough), bounds ≈ ±300 → outlier clipped to ~300
    if w2["OUT"] >= 1000.0:
        failures.append(f"winsorize did not clip extreme outlier: {w2['OUT']}")
    if w2["OUT"] < 0:
        failures.append(f"winsorize clipped to wrong sign: {w2['OUT']}")
    # None preserved
    vals3 = {"A": 1.0, "B": None, "C": 2.0}
    w3 = winsorize(vals3)
    if w3["B"] is not None:
        failures.append("winsorize did not preserve None")

    # 2) Cap-weighted standardize: cap-wtd mean should be 0
    v = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0}
    c = {"A": 100.0, "B": 100.0, "C": 100.0, "D": 700.0}  # D dominates → cap-wtd mean ≈ 3.5
    z = cap_weighted_standardize(v, c)
    cap_wtd = sum(z[k] * c[k] for k in v) / sum(c.values())
    if abs(cap_wtd) > 1e-9:
        failures.append(f"cap-weighted mean != 0: {cap_wtd}")
    # Equal-weighted std should be 1 — Barra USE4 convention: second moment
    # AROUND CAP-WEIGHTED ZERO (not around EW mean). This is asymmetric by
    # design: preserves cap-wtd centering, equal-weight scale.
    ew_var = sum(z[k] ** 2 for k in v) / (len(v) - 1)
    if abs(math.sqrt(ew_var) - 1.0) > 1e-9:
        failures.append(f"equal-weighted std (around cap-wtd-zero) != 1: {math.sqrt(ew_var)}")

    # Single-name: returns 0
    z_single = cap_weighted_standardize({"A": 5.0}, {"A": 100.0})
    if z_single["A"] != 0.0:
        failures.append(f"single-name cap-wtd-std != 0: {z_single['A']}")

    # 3) Industry neutralize: residual within industry should sum to 0
    v_ind = {"A": 10.0, "B": 20.0, "C": 5.0, "D": 15.0, "E": 50.0}
    ind = {"A": "tech", "B": "tech", "C": "fin", "D": "fin", "E": "lonely"}
    r = industry_neutralize(v_ind, ind)
    # tech mean = (10+20)/2 = 15 → A=-5, B=+5
    # fin mean = (5+15)/2 = 10 → C=-5, D=+5
    # lonely: 1 member → unchanged
    if abs(r["A"] - (-5)) > 1e-9 or abs(r["B"] - 5) > 1e-9:
        failures.append(f"industry residual wrong (tech): A={r['A']} B={r['B']}")
    if abs(r["C"] - (-5)) > 1e-9 or abs(r["D"] - 5) > 1e-9:
        failures.append(f"industry residual wrong (fin): C={r['C']} D={r['D']}")
    if r["E"] != 50.0:
        failures.append(f"1-name industry should be unchanged: E={r['E']}")

    # 4) Full pipeline determinism + None propagation
    raw = {"A": 1.0, "B": 2.0, "C": None, "D": 4.0, "E": 5.0}
    mc = {"A": 1e9, "B": 1e9, "C": 1e9, "D": 1e9, "E": 1e9}
    indu = {"A": "i1", "B": "i1", "C": "i1", "D": "i2", "E": "i2"}
    out = barra_construct(raw, mc, indu)
    out2 = barra_construct(raw, mc, indu)
    if out != out2:
        failures.append("barra_construct not deterministic")
    if out["C"] is not None:
        failures.append("None did not propagate through pipeline")

    # 5) Edge case: missing mcap should still pass values through (no drop)
    mc_partial = {"A": 1e9, "B": None, "C": 1e9, "D": 1e9, "E": 1e9}
    out3 = barra_construct(raw, mc_partial, indu)
    # B has value but no mcap → expect non-None (preserved via post-centering path)
    if out3["B"] is None and raw["B"] is not None:
        failures.append("missing mcap dropped a name with finite value")

    if failures:
        print("SELFTEST FAILED factor_construction:")
        for f in failures:
            print("  -", f)
        return 1
    print("SELFTEST PASSED factor_construction")
    print("- winsorize clips extreme outliers + preserves None")
    print("- cap-weighted standardize: cap-wtd mean = 0, EW std = 1")
    print("- industry residualize: within-industry mean = 0, 1-name preserved")
    print("- full pipeline: deterministic, None propagates")
    print("- missing mcap does not drop names")
    return 0


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Barra USE4-style factor construction.")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    print("factor_construction: import barra_construct(raw, mcap, industry).",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
