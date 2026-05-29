#!/usr/bin/env python3
"""v3_multi_test_correction.py — Benjamini-Yekutieli FDR correction over v3 variants.

Per SWING_STRATEGY_v3.md §2:
  "Multi-test correction: BH-Yekutieli 跨全部 backtest variants (目前 22+), corrected p < 0.05"

Why BY (not BH)?
  BH assumes independence or positive regression dependency. v3 variants share
  the same panel + same factor library + same universe; they are NOT independent.
  BY (Benjamini-Yekutieli) controls FDR under ARBITRARY dependency at the cost
  of a c(m) = sum(1/i for i in 1..m) penalty factor.

Method:
  Sort p-values ascending: p_(1) ≤ p_(2) ≤ ... ≤ p_(m).
  Compute c(m) = sum(1/i for i = 1..m).
  Rejection threshold k* = largest k s.t. p_(k) ≤ (k / (m * c(m))) * alpha.
  Adjusted p-value (BY) = min_{j ≥ k}(p_(j) * m * c(m) / j), capped at 1.0.

Carry-over red lines:
  - calibrate set comes from v3 variant manifests' registered_at — not from
    "all 22 backtests run before v3". v3 is a fresh start.
  - We DO NOT retro-fit. Inputs to this module are explicit (variant_id, p) tuples.
  - The CALLER decides which variants to include in the family. This module
    just applies the math.

Usage:
  python3 scripts/v3_multi_test_correction.py --selftest
  python3 scripts/v3_multi_test_correction.py --input /tmp/v3_family.json
    where /tmp/v3_family.json = {"alpha": 0.05, "variants": [{"variant_id": "...", "p_value": 0.03}, ...]}

Output JSON shape:
  {
    "alpha": 0.05,
    "m": <int>,
    "c_m": <float>,                  # BY penalty factor
    "by_threshold_at_k": <float>,    # critical value at k* (or 0 if none reject)
    "k_star": <int>,                 # number of rejected hypotheses
    "results": [
      {"variant_id": "...", "p_value": ..., "rank": ..., "adjusted_p": ..., "reject": bool}
    ]
  }
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable, List, Sequence


def by_penalty(m: int) -> float:
    """c(m) = sum_{i=1..m}(1/i). Used by BY for arbitrary dependence."""
    if m <= 0:
        return 0.0
    return float(sum(1.0 / i for i in range(1, m + 1)))


def by_correct(p_values: Sequence[float], alpha: float = 0.05) -> dict:
    """Benjamini-Yekutieli FDR correction.

    Args:
        p_values: raw p-values in ORIGINAL order.
        alpha: target FDR level (default 0.05).

    Returns:
        Dict with adjusted_p_values (in original order), reject flags, and metadata.

    Notes:
        - Adjusted p_(j) = p_(j) * m * c(m) / j  (raw step-up form)
        - We then enforce monotonicity: adjusted_p_(j) = min_{k≥j} adjusted_p_(k)
          so that a smaller raw p never gets a larger adjusted p.
        - All adjusted values capped at 1.0.
    """
    if alpha <= 0 or alpha >= 1:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    m = len(p_values)
    if m == 0:
        return {
            "alpha": alpha, "m": 0, "c_m": 0.0,
            "by_threshold_at_k_star": 0.0,
            "k_star": 0,
            "rank": [], "sorted_p_values": [], "adjusted_p_values": [],
            "reject": [],
        }

    for p in p_values:
        if not (0.0 <= p <= 1.0):
            raise ValueError(f"p_value must be in [0, 1], got {p}")

    c_m = by_penalty(m)

    # Sort by p ascending, keep original index for inverse mapping.
    order = sorted(range(m), key=lambda i: p_values[i])
    sorted_p = [p_values[i] for i in order]

    # Raw step-up adjusted p_(j) = p_(j) * m * c(m) / j
    raw_adj = [min(1.0, sorted_p[j - 1] * m * c_m / j) for j in range(1, m + 1)]

    # Enforce monotonicity: walking from largest j back to smallest,
    # adjusted_p_(j) = min(adjusted_p_(j), adjusted_p_(j+1)).
    monotone_adj = list(raw_adj)
    for j in range(m - 2, -1, -1):
        monotone_adj[j] = min(monotone_adj[j], monotone_adj[j + 1])

    # Determine k_star: largest k such that sorted_p[k-1] ≤ k*alpha/(m*c_m).
    k_star = 0
    by_threshold_at_k_star = 0.0
    for k in range(m, 0, -1):
        thresh_k = k * alpha / (m * c_m)
        if sorted_p[k - 1] <= thresh_k:
            k_star = k
            by_threshold_at_k_star = thresh_k
            break

    reject_sorted = [j <= k_star for j in range(1, m + 1)]

    # Map back to original order.
    adjusted_p_values = [0.0] * m
    reject = [False] * m
    rank_original = [0] * m
    for sorted_idx, orig_idx in enumerate(order):
        adjusted_p_values[orig_idx] = monotone_adj[sorted_idx]
        reject[orig_idx] = reject_sorted[sorted_idx]
        rank_original[orig_idx] = sorted_idx + 1

    return {
        "alpha": alpha,
        "m": m,
        "c_m": c_m,
        "by_threshold_at_k_star": by_threshold_at_k_star,
        "k_star": k_star,
        "rank": rank_original,
        "sorted_p_values": sorted_p,
        "adjusted_p_values": adjusted_p_values,
        "reject": reject,
    }


def correct_family(variants: List[dict], alpha: float = 0.05) -> dict:
    """Variants = list of {'variant_id': str, 'p_value': float}.

    Returns:
        {
          "alpha": float, "m": int, "c_m": float,
          "by_threshold_at_k_star": float, "k_star": int,
          "results": [
            {"variant_id": str, "p_value": float, "rank": int,
             "adjusted_p": float, "reject": bool}, ...]
        }
    """
    if not variants:
        return {
            "alpha": alpha, "m": 0, "c_m": 0.0,
            "by_threshold_at_k_star": 0.0, "k_star": 0,
            "results": [],
        }
    p_values = [v["p_value"] for v in variants]
    result = by_correct(p_values, alpha=alpha)
    out_results = []
    for i, v in enumerate(variants):
        out_results.append({
            "variant_id": v["variant_id"],
            "p_value": v["p_value"],
            "rank": result["rank"][i],
            "adjusted_p": result["adjusted_p_values"][i],
            "reject": result["reject"][i],
        })
    return {
        "alpha": result["alpha"],
        "m": result["m"],
        "c_m": result["c_m"],
        "by_threshold_at_k_star": result["by_threshold_at_k_star"],
        "k_star": result["k_star"],
        "results": out_results,
    }


# -------------------- selftest --------------------

def _approx(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _selftest() -> int:
    """Selftest cases for BY correction.

    Test 1: c(m) for m=1..5 matches harmonic sum.
    Test 2: m=1, p=0.04, alpha=0.05 -> reject; adjusted p = 0.04.
    Test 3: m=10 with one p=0.001 (others 0.5..0.99) -> only the small one
            should reject, adjusted_p of small one = 0.001 * 10 * c(10).
    Test 4: monotonicity — after correction, sorted-by-raw-p adjusted is
            non-decreasing.
    Test 5: cap at 1.0 — large raw p never produces adjusted > 1.
    Test 6: variant adapter preserves variant_id<->p_value mapping
            after sort+inverse.
    Test 7: empty input is safe.
    """
    errors = []

    # Test 1: harmonic sums.
    expected = {1: 1.0, 2: 1.5, 3: 11.0 / 6.0, 5: 1 + 0.5 + 1/3 + 0.25 + 0.2}
    for m, ref in expected.items():
        got = by_penalty(m)
        if not _approx(got, ref, tol=1e-12):
            errors.append(f"by_penalty({m}) = {got}, expected {ref}")

    # Test 2: m=1.
    res = by_correct([0.04], alpha=0.05)
    if res["k_star"] != 1:
        errors.append(f"Test 2 k_star: got {res['k_star']}, expected 1")
    if not _approx(res["adjusted_p_values"][0], 0.04, tol=1e-12):
        errors.append(f"Test 2 adj_p: got {res['adjusted_p_values'][0]}, expected 0.04")
    if not res["reject"][0]:
        errors.append("Test 2: expected reject=True")

    # Test 3: m=10 with mostly large p.
    p_vals = [0.001, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.92, 0.95, 0.99]
    res = by_correct(p_vals, alpha=0.05)
    c10 = by_penalty(10)
    if res["k_star"] != 1:
        errors.append(f"Test 3 k_star: got {res['k_star']}, expected 1")
    expected_adj_smallest = min(1.0, 0.001 * 10 * c10 / 1)
    if not _approx(res["adjusted_p_values"][0], expected_adj_smallest, tol=1e-12):
        errors.append(
            f"Test 3 adj_p_smallest: got {res['adjusted_p_values'][0]}, "
            f"expected {expected_adj_smallest}"
        )
    if not res["reject"][0]:
        errors.append("Test 3: expected reject[0]=True (p=0.001 should pass)")
    if any(res["reject"][i] for i in range(1, len(p_vals))):
        errors.append("Test 3: expected only first variant to reject")

    # Test 4: monotonicity in sorted order.
    raw = [0.001, 0.003, 0.01, 0.02, 0.04, 0.06, 0.10, 0.20, 0.40, 0.80]
    res = by_correct(raw, alpha=0.05)
    # adjusted in sort order should be non-decreasing.
    order = sorted(range(len(raw)), key=lambda i: raw[i])
    adj_sorted = [res["adjusted_p_values"][i] for i in order]
    for j in range(1, len(adj_sorted)):
        if adj_sorted[j] + 1e-12 < adj_sorted[j - 1]:
            errors.append(
                f"Test 4 monotonicity violated at j={j}: "
                f"{adj_sorted[j-1]} > {adj_sorted[j]}"
            )

    # Test 5: cap at 1.0.
    res = by_correct([0.9, 0.95, 0.99], alpha=0.05)
    for adj in res["adjusted_p_values"]:
        if adj > 1.0 + 1e-12:
            errors.append(f"Test 5 cap violated: adj_p={adj}")
    if res["k_star"] != 0:
        errors.append(f"Test 5 k_star: got {res['k_star']}, expected 0")

    # Test 6: variant adapter.
    variants = [
        {"variant_id": "v3c_alpha2", "p_value": 0.04},
        {"variant_id": "v3c_alpha1", "p_value": 0.001},
        {"variant_id": "v3c_alpha3", "p_value": 0.20},
    ]
    fam = correct_family(variants, alpha=0.05)
    by_id = {r["variant_id"]: r for r in fam["results"]}
    if not _approx(by_id["v3c_alpha1"]["p_value"], 0.001):
        errors.append("Test 6: mapping lost p_value")
    if by_id["v3c_alpha1"]["rank"] != 1:
        errors.append(f"Test 6 rank: got {by_id['v3c_alpha1']['rank']}, expected 1")
    if not by_id["v3c_alpha1"]["reject"]:
        errors.append("Test 6: smallest p should be rejected at m=3")
    if by_id["v3c_alpha3"]["reject"]:
        errors.append("Test 6: largest p (0.20) should NOT be rejected at m=3 BY")

    # Test 7: empty.
    fam_empty = correct_family([], alpha=0.05)
    if fam_empty["m"] != 0 or fam_empty["results"] != []:
        errors.append("Test 7: empty input not handled cleanly")

    # Test 8: iter-18 single variant scenario (the b1_b3 OOS p=0.0161).
    # In a 1-variant family, BY should reject at alpha=0.05.
    res = by_correct([0.0161], alpha=0.05)
    if not res["reject"][0]:
        errors.append("Test 8: single-variant p=0.0161 should reject at alpha=0.05")

    if errors:
        print("v3_multi_test_correction selftest FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("v3_multi_test_correction selftest PASSED")
    print(f"  Tested c(m) for m in (1,2,3,5)")
    print(f"  Tested m=1, m=3 (variants), m=10 (extreme spread), monotonicity, cap-at-1")
    return 0


# -------------------- CLI --------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="BH-Yekutieli FDR correction over v3 variants.")
    parser.add_argument("--selftest", action="store_true", help="Run built-in selftest.")
    parser.add_argument("--input", type=str, help="JSON file with {'alpha': float, 'variants': [...]}")
    parser.add_argument("--output", type=str, help="Output JSON path (defaults to stdout).")
    args = parser.parse_args()

    if args.selftest:
        return _selftest()

    if not args.input:
        parser.error("--input or --selftest required")

    with open(args.input) as f:
        payload = json.load(f)
    alpha = float(payload.get("alpha", 0.05))
    variants = payload["variants"]
    result = correct_family(variants, alpha=alpha)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Wrote {args.output}")
    else:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
