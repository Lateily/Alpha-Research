#!/usr/bin/env python3
"""stationary_bootstrap.py — Politis & Romano (1994) stationary bootstrap.

PURPOSE: compute valid 95% confidence intervals on backtest statistics
(alpha, Sharpe, CAGR) that respect the time-series structure of monthly
factor returns. OLS standard errors assume i.i.d. residuals; monthly equity
factor returns have autocorrelation (vol clustering, momentum reversal)
which understates true uncertainty.

METHOD: stationary bootstrap (Politis-Romano 1994 JASA) resamples blocks of
GEOMETRICALLY-distributed random length p, where E[block] = 1/p. The
resulting pseudo-series:
  - preserves serial dependence at all lags
  - is itself strictly STATIONARY (unlike fixed-block-length bootstrap)
  - has valid CIs for the mean (and approximately valid for smooth functionals)

DEFAULT: p = 1 / L_opt where L_opt ≈ n^(1/3) is the rule-of-thumb optimal
block length. For n=240 months, L_opt ≈ 6.2 → p ≈ 0.16. For more rigor,
Politis-White (2004) gives an automatic block-length selector — we don't
implement it; the rule-of-thumb is fine for our small-sample regime.

DECISION RULE (the honest gate):
  If the 95% CI for alpha INCLUDES 0 → the headline alpha is statistically
  indistinguishable from zero. Junyan's red line: "宁愿犯错也不愿意找不出来
  错误在哪". A CI-straddles-0 result is the honest "no evidence of edge".
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent


# ───────────────────────── Bootstrap engine ─────────────────────────────────

def stationary_bootstrap_indices(n: int, p: float, *, rng: random.Random) -> list[int]:
    """Return n indices sampled via stationary bootstrap with parameter p.

    p in (0, 1]: probability of starting a new block at each step.
      → expected block length = 1/p.
    p=1: i.i.d. bootstrap (degenerate); p=0: single infinite block (degenerate).
    """
    if not 0.0 < p <= 1.0:
        raise ValueError(f"p must be in (0,1], got {p}")
    out = [rng.randrange(0, n)]
    for _ in range(n - 1):
        if rng.random() < p:
            out.append(rng.randrange(0, n))
        else:
            out.append((out[-1] + 1) % n)   # wrap-around (circular)
    return out


def bootstrap_ci(data: list[float], statistic: Callable[[list[float]], float],
                 *, B: int = 10000, p: float | None = None,
                 alpha: float = 0.05, seed: int = 42) -> dict:
    """Generic stationary-bootstrap CI for a statistic of a 1D series.

    Args:
        data: the time series (e.g., monthly return series, or monthly alpha)
        statistic: callable mapping data → scalar (e.g., mean, Sharpe)
        B: number of bootstrap replications (default 10000)
        p: stationary bootstrap parameter; if None, use 1/n^(1/3)
        alpha: significance level (default 0.05 → 95% CI)
        seed: RNG seed for determinism

    Returns dict with point_est, ci_lo, ci_hi, p_value, n, B, p.
    The "p_value" is the bootstrap test of H0:statistic=0 (two-sided).
    """
    n = len(data)
    if n < 10:
        return {"_status": "insufficient_obs", "n": n}
    if p is None:
        # Rule of thumb: L_opt ≈ n^(1/3); p = 1/L
        L_opt = max(2, int(round(n ** (1.0 / 3.0))))
        p = 1.0 / L_opt

    point = statistic(data)
    if not (point is not None and math.isfinite(point)):
        return {"_status": "point_estimate_invalid", "n": n}

    rng = random.Random(seed)
    boot = []
    for _ in range(B):
        idx = stationary_bootstrap_indices(n, p, rng=rng)
        resample = [data[i] for i in idx]
        s = statistic(resample)
        if s is not None and math.isfinite(s):
            boot.append(s)

    boot.sort()
    n_boot = len(boot)
    if n_boot < 100:
        return {"_status": "too_few_valid_replications", "n_boot": n_boot}

    lo_idx = int(math.floor(n_boot * (alpha / 2)))
    hi_idx = int(math.ceil(n_boot * (1 - alpha / 2))) - 1
    lo_idx = max(0, min(lo_idx, n_boot - 1))
    hi_idx = max(0, min(hi_idx, n_boot - 1))

    # Bootstrap two-sided p-value of H0:statistic=0
    # Under H0, the bootstrap distribution of (boot - point) approximates the
    # sampling distribution of (point - 0). So we measure how often the bootstrap
    # *deviation from the point estimate* exceeds the *point estimate itself*.
    # This is the percentile-of-zero-relative-to-centered-bootstrap test.
    n_extreme = sum(1 for b in boot if abs(b - point) >= abs(point))
    p_value = n_extreme / n_boot

    straddles_zero = (boot[lo_idx] <= 0.0 <= boot[hi_idx])

    return {
        "_status": "ok",
        "n": n,
        "B": B,
        "n_boot_valid": n_boot,
        "p_stationary": p,
        "expected_block_length": 1.0 / p,
        "point_estimate": point,
        "ci_lo": boot[lo_idx],
        "ci_hi": boot[hi_idx],
        "alpha": alpha,
        "straddles_zero": straddles_zero,
        "p_value_h0_zero": p_value,
        "median_boot": boot[n_boot // 2],
    }


# ───────────────────────── Standard statistics ──────────────────────────────

def mean(xs: list[float]) -> float | None:
    if not xs:
        return None
    return sum(xs) / len(xs)


def sharpe_annualized(monthly_excess: list[float], rf_per_month: float = 0.0,
                      periods_per_year: int = 12) -> float | None:
    """Annualized Sharpe of monthly excess returns. NO rf already netted (pass
    excess if you've subtracted rf). Sharpe = (mean - rf) / std × √periods."""
    if not monthly_excess or len(monthly_excess) < 2:
        return None
    m = sum(monthly_excess) / len(monthly_excess)
    var = sum((x - m) ** 2 for x in monthly_excess) / (len(monthly_excess) - 1)
    s = math.sqrt(var)
    if s <= 1e-12:                       # FP-tolerant zero check
        return None
    return (m - rf_per_month) / s * math.sqrt(periods_per_year)


def cagr_from_monthly(monthly_returns: list[float]) -> float | None:
    """Compounded annual growth rate from a series of monthly returns."""
    if not monthly_returns:
        return None
    eq = 1.0
    for r in monthly_returns:
        eq *= (1 + r)
    n_months = len(monthly_returns)
    if eq <= 0 or n_months == 0:
        return None
    return eq ** (12.0 / n_months) - 1.0


# ───────────────────────── Equity-curve → monthly returns ───────────────────

def equity_curve_to_monthly_returns(curve: list[dict]) -> list[float]:
    """Convert backtest_v2 equity_curve [{date, equity}, ...] → monthly returns."""
    eqs = [pt["equity"] for pt in curve if pt.get("equity") is not None]
    rets = []
    for i in range(1, len(eqs)):
        prev = eqs[i - 1]
        if prev > 0:
            rets.append(eqs[i] / prev - 1.0)
    return rets


def alpha_series(strat_curve: list[dict], bench_curve: list[dict]) -> list[float]:
    """Per-month excess returns of strategy over benchmark (alpha series)."""
    sr = equity_curve_to_monthly_returns(strat_curve)
    br = equity_curve_to_monthly_returns(bench_curve)
    n = min(len(sr), len(br))
    return [sr[i] - br[i] for i in range(n)]


# ───────────────────────── Self-test ────────────────────────────────────────

def _selftest() -> int:
    failures = []

    # 1) i.i.d. series with zero mean → CI should straddle 0
    rng = random.Random(7)
    iid = [rng.gauss(0, 0.05) for _ in range(240)]
    r = bootstrap_ci(iid, mean, B=2000, seed=123)
    if r["_status"] != "ok":
        failures.append(f"iid: bad status {r['_status']}")
    elif not r["straddles_zero"]:
        failures.append(f"iid zero-mean: CI must straddle 0, got [{r['ci_lo']:.4f}, {r['ci_hi']:.4f}]")

    # 2) i.i.d. series with non-zero mean → CI strictly positive (loud signal)
    rng = random.Random(7)
    signal = [rng.gauss(0.02, 0.04) for _ in range(240)]
    r2 = bootstrap_ci(signal, mean, B=2000, seed=123)
    if r2["_status"] != "ok":
        failures.append(f"signal: bad status {r2['_status']}")
    elif r2["ci_lo"] <= 0:
        failures.append(f"signal mean 0.02 / std 0.04 / n=240 should yield ci_lo>0, got {r2['ci_lo']:.4f}")
    elif r2["p_value_h0_zero"] >= 0.05:
        failures.append(f"signal should reject H0:mean=0, got p={r2['p_value_h0_zero']:.4f}")

    # 3) Stationary bootstrap preserves autocorrelation structure approximately:
    #    on an AR(1) series, the bootstrap variance should EXCEED the i.i.d.
    #    bootstrap variance (we don't test the magnitude, just the direction)
    #    via the SE of the mean.
    rng = random.Random(11)
    ar = [0.0]
    for _ in range(239):
        ar.append(0.8 * ar[-1] + rng.gauss(0, 0.05))
    r_stat = bootstrap_ci(ar, mean, B=2000, p=0.2, seed=123)
    r_iid = bootstrap_ci(ar, mean, B=2000, p=1.0, seed=123)  # iid = no block
    se_stat = (r_stat["ci_hi"] - r_stat["ci_lo"]) / 3.92    # ≈ 2 × 1.96 × SE
    se_iid = (r_iid["ci_hi"] - r_iid["ci_lo"]) / 3.92
    if se_stat <= se_iid:
        failures.append(
            f"AR(1): stationary bootstrap SE ({se_stat:.4f}) should exceed iid SE ({se_iid:.4f})"
        )

    # 4) Sharpe / CAGR sanity
    flat = [0.01] * 12
    s = sharpe_annualized(flat)
    if s is None:
        # zero variance — std=0 → Sharpe undefined; this is the documented behavior
        pass
    else:
        failures.append(f"flat series should give Sharpe=None (std=0), got {s}")
    c = cagr_from_monthly(flat)
    if c is None or abs(c - (1.01 ** 12 - 1)) > 1e-6:
        failures.append(f"CAGR of 1% monthly should be ~12.68%, got {c}")

    # 5) Equity curve → monthly returns
    curve = [{"date": "2020-01-01", "equity": 1.0},
             {"date": "2020-02-01", "equity": 1.10},
             {"date": "2020-03-01", "equity": 1.21}]
    r = equity_curve_to_monthly_returns(curve)
    if len(r) != 2 or abs(r[0] - 0.10) > 1e-9 or abs(r[1] - 0.10) > 1e-9:
        failures.append(f"equity→monthly wrong: {r}")

    if failures:
        print("SELFTEST FAILED stationary_bootstrap:")
        for f in failures:
            print("  -", f)
        return 1
    print("SELFTEST PASSED stationary_bootstrap")
    print("- iid zero-mean: CI correctly straddles 0")
    print("- iid loud signal: CI strictly positive, H0 rejected")
    print("- AR(1): stationary block SE > iid SE (autocorrelation accounted)")
    print("- Sharpe + CAGR + equity→returns helpers work")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Stationary bootstrap CI for backtest stats.")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--strat", help="Path to strategy backtest result JSON (equity_curve)")
    p.add_argument("--bench", help="Path to benchmark backtest result JSON (equity_curve key, optional)")
    p.add_argument("--out", default=str(REPO_ROOT / "public" / "data" / "bootstrap_ci.json"))
    p.add_argument("--B", type=int, default=10000)
    p.add_argument("--block", type=int, default=6, help="Avg block length in months (default 6)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--alpha", type=float, default=0.05)
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()

    if not args.strat:
        print("ERROR: --strat required", file=sys.stderr)
        return 1

    strat = json.load(open(args.strat))
    sr = equity_curve_to_monthly_returns(strat.get("equity_curve", []))
    if not sr:
        print("ERROR: strat has no equity_curve", file=sys.stderr)
        return 1

    p_stat = 1.0 / args.block
    out = {
        "_meta": {
            "strat_input": args.strat,
            "bench_input": args.bench,
            "B": args.B,
            "block_length_months": args.block,
            "p_stationary": p_stat,
            "seed": args.seed,
            "alpha": args.alpha,
            "honesty": "Politis-Romano stationary bootstrap; CI straddling 0 = no edge evidence",
        },
        "strat_n_months": len(sr),
    }

    # Bootstrap CI on strategy mean monthly return, annualized CAGR, Sharpe
    out["strat_mean_monthly"] = bootstrap_ci(sr, mean, B=args.B, p=p_stat,
                                              alpha=args.alpha, seed=args.seed)
    out["strat_cagr"] = bootstrap_ci(sr, lambda x: cagr_from_monthly(x) or 0.0,
                                     B=args.B, p=p_stat, alpha=args.alpha, seed=args.seed)
    out["strat_sharpe"] = bootstrap_ci(sr, lambda x: sharpe_annualized(x) or 0.0,
                                       B=args.B, p=p_stat, alpha=args.alpha, seed=args.seed)

    # If benchmark provided, compute ALPHA series and its CI (THE headline test)
    if args.bench:
        # The benchmark is stored INSIDE the same strat file as market_proxy_curve,
        # so a separate file isn't usually needed. Accept either format.
        bench_curve = None
        if Path(args.bench).exists() and args.bench != args.strat:
            bench = json.load(open(args.bench))
            bench_curve = bench.get("equity_curve") or bench.get("market_proxy_curve")
        if bench_curve is None:
            bench_curve = strat.get("market_proxy_curve")
        if bench_curve:
            ar = alpha_series(strat.get("equity_curve", []), bench_curve)
            if ar:
                out["alpha_series_n"] = len(ar)
                out["alpha_mean_monthly"] = bootstrap_ci(ar, mean, B=args.B, p=p_stat,
                                                          alpha=args.alpha, seed=args.seed)
                # annualize via (1+x)^12 - 1
                out["alpha_annualized"] = bootstrap_ci(
                    ar, lambda x: ((1 + sum(x) / len(x)) ** 12 - 1) if x else 0.0,
                    B=args.B, p=p_stat, alpha=args.alpha, seed=args.seed,
                )

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))

    def _fmt(d: dict) -> str:
        if d.get("_status") != "ok":
            return f"[{d.get('_status')}]"
        return (f"point={d['point_estimate']:+.4f}  "
                f"95%CI=[{d['ci_lo']:+.4f}, {d['ci_hi']:+.4f}]  "
                f"H0=0 p={d['p_value_h0_zero']:.4f}  "
                f"{'straddles 0' if d['straddles_zero'] else 'CI EXCLUDES 0'}")

    print(f"=== Stationary bootstrap CI (B={args.B}, block≈{args.block}mo) ===")
    print(f"  strat mean monthly      {_fmt(out['strat_mean_monthly'])}")
    print(f"  strat annualized CAGR   {_fmt(out['strat_cagr'])}")
    print(f"  strat annualized Sharpe {_fmt(out['strat_sharpe'])}")
    if "alpha_mean_monthly" in out:
        print(f"  ALPHA mean monthly      {_fmt(out['alpha_mean_monthly'])}")
        print(f"  ALPHA annualized        {_fmt(out['alpha_annualized'])}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
