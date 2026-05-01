#!/usr/bin/env python3
"""
scripts/multi_method_valuation.py — AHF-2 Aggregator: median-of-3
                                    triangulated valuation signal.

PURPOSE
=======
Final synthesis step of the AHF-2 v1 sprint. Combines per-ticker signals
from THREE orthogonal estimators into ONE triangulated signal per ticker:

  Method 1: FCF DCF (cash-flow regime)        — rdcf_<safe>.json `signal`
  Method 2: EV/EBITDA (multiples regime)      — ev_ebitda_valuation.json
  Method 3: Residual Income / EBO (book-value) — residual_income_valuation.json

Each method's `signal` field is in {UNDERPRICED, FAIRLY_VALUED,
OVERPRICED, null}. Aggregator computes median across available methods
and emits per-ticker triangulated signal with explicit
`methods_count` for transparency about confidence.

NOT folded into VP composite (INVARIANT 3 — preserves AHF-1 calibration
anchor + AHF-3 persona-deterministic-only philosophy).

PROVENANCE
==========
AHF_COMPARISON.md Tier 1 A2. Locked-in strategic decisions in
`.night-shift/AHF-2_HANDOFF.md` from prior shift (KR9 DEFER_C):
  - 3 orthogonal estimators
  - Biotech blind spot Option 1 (Skip — 6160.HK falls back to Method 1
    biotech_revenue rdcf as canonical)
  - Triangulation: median-of-3
  - NOT folded into VP composite
  - Single multi-ticker output file

METHOD: median-of-SIGNALS (NOT median-of-deltas)
==========
The three methods produce delta in INCOMPATIBLE units:
  Method 1: raw delta = our_growth - implied_growth (fractional)
  Method 2: delta_pct = (fair_equity / market_cap - 1) × 100 (percent)
  Method 3: delta_pp = (current_roe - implied_roe) × 100 (percentage points)

Cross-comparing the raw numerics is meaningless. Only the categorical
signal enum {UNDERPRICED, FAIRLY_VALUED, OVERPRICED} is unit-comparable.

Algorithm:
  Map: OVERPRICED → -1, FAIRLY_VALUED → 0, UNDERPRICED → +1
  Filter out null signals (degraded methods)
  Variable-N median:
    n=0: INSUFFICIENT_DATA (no methods available)
    n=1: that single method's signal directly
    n=2: CONSENSUS-ONLY rounding (per KR3 KR_APPROVAL P3-ii):
         both agree → that signal
         disagree → FAIRLY_VALUED [unvalidated intuition tie-break]
    n=3: standard median (sorted middle value)
  Inverse-map back to enum.

GRACEFUL DEGRADATION
==========
Per-method skip semantics:

Method 1 (FCF DCF) — SOURCE: rdcf_<safe>.json:
  - rdcf has `error` field set     → M1 skipped
  - rdcf has no `signal` field     → M1 skipped
  - rdcf file missing entirely     → M1 skipped (file-level)
  → skip_reason: "rdcf_error:<code>" / "rdcf_no_signal" / "rdcf_missing"

Method 2 (EV/EBITDA) — SOURCE: ev_ebitda_valuation.json:
  - ev_ebitda_valuation.json file missing → ALL tickers skip M2
  - ticker block missing in file          → that ticker skips M2
  - model_status in M2_SKIP_STATUSES       → that ticker skips M2
  → skip_reason: "ev_ebitda_<status>" / "ev_ebitda_file_missing"

Method 3 (EBO) — SOURCE: residual_income_valuation.json:
  - residual_income_valuation.json file missing → ALL tickers skip M3
  - ticker block missing in file                → that ticker skips M3
  - model_status in M3_SKIP_STATUSES             → that ticker skips M3
  → skip_reason: "ri_<status>" / "ri_file_missing"

Triangulation level:
  - All 3 methods unavailable → triangulated_signal = INSUFFICIENT_DATA
  - 1 method available (typically biotech_fallback case where M2+M3
    skip due to biotech) → output that signal with is_biotech_fallback
    or is_partial flag
  - 2 methods → consensus-only median per (P3-ii)
  - 3 methods → standard median

THRESHOLD CHOICES (each method owns its native — no recomputation)
==========
Method 1: ±0.05 raw delta threshold (existing rdcf engine; SOT respect)
Method 2: ±15% delta_pct threshold (KR1)
Method 3: ±15pp delta_pp threshold (KR2)

The aggregator does NOT recompute classifications; it consumes each
method's `signal` field directly. Each method owns its native threshold
appropriate to its underlying mathematical regime.

THRESHOLDS / CHOICES [unvalidated intuition]
==========
- n=2 tie-break to FAIRLY_VALUED on disagreement (consensus-only,
  conservative, per KR3 KR_APPROVAL P3-ii)
- M1's existing ±0.05 threshold (legacy from rdcf, unchanged)

NOT [unvalidated intuition] (mathematical convention):
- Integer mapping {-1, 0, +1}
- Median computation (sort + middle for odd N; pair handling for even)
- Variable-N handling

Author: Night-shift run 2026-04-30-2323 KR3 (AHF-2 sub-KR 3 of 3-4;
        closes the AHF-2 v1 sprint methodology backbone)
"""

from __future__ import annotations
import json
import pathlib
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"


# ─────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────

SIGNAL_TO_INT = {"OVERPRICED": -1, "FAIRLY_VALUED": 0, "UNDERPRICED": 1}
INT_TO_SIGNAL = {-1: "OVERPRICED", 0: "FAIRLY_VALUED", 1: "UNDERPRICED"}
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# Method 2 model_status values that indicate "method unavailable for triangulation"
M2_SKIP_STATUSES = {
    "biotech_fallback",
    "fundamentals_missing",
    "ebitda_missing",
    "ev_data_missing",
}

# Method 3 model_status values that indicate "method unavailable for triangulation"
M3_SKIP_STATUSES = {
    "biotech_fallback",
    "hyper_growth_ebo_unstable",
    "fundamentals_missing",
    "roe_missing",
    "market_cap_missing",
    "book_equity_missing",
    "negative_book_equity",
    "wacc_missing",
    "wacc_anomalous",
}


# ─────────────────────────────────────────────────────────────────────────
# Helpers — SOT, JSON load
# ─────────────────────────────────────────────────────────────────────────

def _load_json(name: str, default: Any = None) -> Any:
    p = DATA / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_watchlist_tickers() -> list[str]:
    """Single source of truth — never hardcode tickers."""
    wl = _load_json("watchlist.json", {})
    return list(wl.get("tickers", {}).keys())


def _safe_id(ticker: str) -> str:
    return ticker.replace(".", "_")


# ─────────────────────────────────────────────────────────────────────────
# Core triangulation logic
# ─────────────────────────────────────────────────────────────────────────

def _triangulate_signals(signals: list) -> str:
    """Median-of-signals with variable-N support + n=2 consensus-only.

    Args:
        signals: list of length 3 with values in {UNDERPRICED, FAIRLY_VALUED,
                 OVERPRICED, None}. None means method unavailable for this
                 ticker.

    Returns:
        Triangulated signal enum: UNDERPRICED, FAIRLY_VALUED, OVERPRICED,
        or INSUFFICIENT_DATA.

    Algorithm:
        n=0: INSUFFICIENT_DATA
        n=1: that single signal directly
        n=2: consensus-only (both agree → that signal; disagree → FAIRLY_VALUED)
        n=3: standard median (sorted middle value)
    """
    valid = [s for s in signals if s is not None]
    n = len(valid)
    if n == 0:
        return INSUFFICIENT_DATA
    if n == 1:
        return valid[0]
    numeric = sorted([SIGNAL_TO_INT[s] for s in valid])
    if n == 2:
        # Consensus-only rounding (P3-ii from KR3 KR_APPROVAL):
        # both agree → that signal; disagree → FAIRLY_VALUED [unvalidated intuition]
        if numeric[0] == numeric[1]:
            return INT_TO_SIGNAL[numeric[0]]
        return INT_TO_SIGNAL[0]  # FAIRLY_VALUED
    # n == 3: standard median (middle of sorted values)
    return INT_TO_SIGNAL[numeric[1]]


# ─────────────────────────────────────────────────────────────────────────
# Per-method signal extraction (P3-ii from decomp)
# ─────────────────────────────────────────────────────────────────────────

def _extract_method1(rdcf: dict) -> tuple:
    """Method 1 (FCF DCF) signal extraction from rdcf JSON.

    Three skip paths:
      - rdcf has `error` field set → skip with reason "rdcf_error:<code>"
      - rdcf has no `signal` field → skip with reason "rdcf_no_signal"
      - rdcf is empty (file missing or unparseable) → skip with reason "rdcf_missing"
    """
    if not rdcf:
        return None, "rdcf_missing", None
    err = rdcf.get("error")
    if err:
        return None, f"rdcf_error:{err}", rdcf.get("delta")
    sig = rdcf.get("signal")
    if sig is None:
        return None, "rdcf_no_signal", rdcf.get("delta")
    return sig, None, rdcf.get("delta")


def _extract_method2(m2_data: dict, ticker: str) -> tuple:
    """Method 2 (EV/EBITDA) signal extraction.

    Three skip paths:
      - file missing entirely → skip with reason "ev_ebitda_file_missing"
      - ticker block missing → skip with reason "ev_ebitda_ticker_missing"
      - model_status in M2_SKIP_STATUSES → skip with reason "ev_ebitda_<status>"
    """
    if not m2_data:
        return None, "ev_ebitda_file_missing", None
    block = (m2_data.get("tickers") or {}).get(ticker)
    if block is None:
        return None, "ev_ebitda_ticker_missing", None
    status = block.get("model_status")
    if status in M2_SKIP_STATUSES:
        return None, f"ev_ebitda_{status}", block.get("delta_pct")
    sig = block.get("signal")
    return sig, None, block.get("delta_pct")


def _extract_method3(m3_data: dict, ticker: str) -> tuple:
    """Method 3 (EBO) signal extraction.

    Three skip paths:
      - file missing entirely → skip with reason "ri_file_missing"
      - ticker block missing → skip with reason "ri_ticker_missing"
      - model_status in M3_SKIP_STATUSES → skip with reason "ri_<status>"
    """
    if not m3_data:
        return None, "ri_file_missing", None
    block = (m3_data.get("tickers") or {}).get(ticker)
    if block is None:
        return None, "ri_ticker_missing", None
    status = block.get("model_status")
    if status in M3_SKIP_STATUSES:
        return None, f"ri_{status}", block.get("delta_pp")
    sig = block.get("signal")
    return sig, None, block.get("delta_pp")


# ─────────────────────────────────────────────────────────────────────────
# Rationale text builder (per Q5 polish — avoid "default" framing)
# ─────────────────────────────────────────────────────────────────────────

def _build_rationales(ticker, triangulated, methods_count, methods_used,
                      is_biotech_fallback, m1_signal, m2_signal, m3_signal):
    """Construct rationale text reflecting the precise triangulation logic.

    Avoids "default" framing. For n=3 with full range (UNDER/FAIR/OVER),
    explicitly identifies which method sits at the median.
    """
    methods_str = " + ".join(methods_used) if methods_used else "none"

    if triangulated == INSUFFICIENT_DATA:
        return (
            "All three methods unavailable; cannot triangulate.",
            "三种方法均不可用；无法三角验证。",
        )

    if is_biotech_fallback:
        return (
            f"Biotech_fallback path: M2 (EV/EBITDA) and M3 (EBO) inapplicable to "
            f"clinical-stage biotech. Method 1 (FCF DCF biotech_revenue) signal = "
            f"{triangulated}, used as canonical.",
            f"生物科技回退路径：M2 (EV/EBITDA) 与 M3 (EBO) 不适用于临床期生物科技。"
            f"Method 1 (FCF DCF biotech_revenue) 信号 = {triangulated}，作为标准。",
        )

    if methods_count == 1:
        method = methods_used[0]
        return (
            f"Only Method {method} available; methods_count=1. Triangulated signal = {triangulated}.",
            f"仅 {method} 可用；methods_count=1。三角信号 = {triangulated}。",
        )

    if methods_count == 2:
        if m1_signal is not None and m2_signal is not None and m3_signal is None:
            paired = f"{m1_signal} (FCF DCF) and {m2_signal} (EV/EBITDA)"
        elif m1_signal is not None and m3_signal is not None and m2_signal is None:
            paired = f"{m1_signal} (FCF DCF) and {m3_signal} (EBO)"
        elif m2_signal is not None and m3_signal is not None and m1_signal is None:
            paired = f"{m2_signal} (EV/EBITDA) and {m3_signal} (EBO)"
        else:
            paired = "two methods"
        if m1_signal == m2_signal == m3_signal:
            verdict = "consensus"
        elif (m1_signal == m2_signal or m1_signal == m3_signal or m2_signal == m3_signal):
            verdict = "consensus among available"
        else:
            verdict = "disagreement → tie-break to FAIRLY_VALUED"
        return (
            f"2 of 3 methods available ({paired}); {verdict} → triangulated {triangulated}.",
            f"3种方法中2种可用（{paired}）；{verdict} → 三角信号 {triangulated}。",
        )

    # n == 3: full method coverage
    sigs = {"FCF_DCF": m1_signal, "EV_EBITDA": m2_signal, "Residual_Income_EBO": m3_signal}
    distinct = set(sigs.values())
    if len(distinct) == 1:
        return (
            f"3 of 3 methods agree {triangulated} (cash-flow + multiples + book-value lenses converge). Strongest possible signal.",
            f"3种方法一致 {triangulated}（现金流+倍数+账面价值三个角度收敛）。最强信号。",
        )
    if len(distinct) == 3:
        # full range UNDER+FAIR+OVER → middle method is the median
        for mname, msig in sigs.items():
            if msig == triangulated:
                method_at_median = mname
                break
        return (
            f"3 methods span full range (UNDER, FAIR, OVER); {method_at_median} sits at median = {triangulated}.",
            f"3种方法覆盖全范围（低估、合理、高估）；{method_at_median} 处于中位 = {triangulated}。",
        )
    # 2 methods agree, 1 disagrees
    agree_count = max(sum(1 for v in sigs.values() if v == s) for s in distinct)
    return (
        f"2 of 3 methods agree {triangulated}; remaining method differs but median resolves to {triangulated}.",
        f"3种方法中2种一致 {triangulated}；剩余1种有分歧但中位数为 {triangulated}。",
    )


# ─────────────────────────────────────────────────────────────────────────
# Per-ticker computation
# ─────────────────────────────────────────────────────────────────────────

def compute_for_ticker(ticker: str, m2_data: dict, m3_data: dict) -> dict:
    """Compute triangulated valuation signal for one ticker."""
    rdcf = _load_json(f"rdcf_{_safe_id(ticker)}.json", {})

    m1_signal, m1_skip, m1_delta     = _extract_method1(rdcf)
    m2_signal, m2_skip, m2_delta_pct = _extract_method2(m2_data, ticker)
    m3_signal, m3_skip, m3_delta_pp  = _extract_method3(m3_data, ticker)

    signals = [m1_signal, m2_signal, m3_signal]
    triangulated = _triangulate_signals(signals)

    methods_used = [name for name, sig in [
        ("FCF_DCF",            m1_signal),
        ("EV_EBITDA",          m2_signal),
        ("Residual_Income_EBO",m3_signal),
    ] if sig is not None]

    methods_skipped = [{"method": name, "reason": reason} for name, reason in [
        ("FCF_DCF",            m1_skip),
        ("EV_EBITDA",          m2_skip),
        ("Residual_Income_EBO",m3_skip),
    ] if reason is not None]

    methods_count = len(methods_used)

    # is_biotech_fallback: M2 AND M3 both skipped due to biotech_fallback
    is_biotech_fallback = (
        m2_skip == "ev_ebitda_biotech_fallback"
        and m3_skip == "ri_biotech_fallback"
    )

    # is_partial: methods_count < 3 AND not biotech_fallback
    is_partial = (methods_count < 3) and not is_biotech_fallback

    rationale_e, rationale_z = _build_rationales(
        ticker, triangulated, methods_count, methods_used,
        is_biotech_fallback, m1_signal, m2_signal, m3_signal,
    )

    return {
        "ticker":              ticker,
        "triangulated_signal": triangulated,
        "methods_count":       methods_count,
        "methods_used":        methods_used,
        "methods_skipped":     methods_skipped,
        "is_biotech_fallback": is_biotech_fallback,
        "is_partial":          is_partial,
        "method_signals": {
            "FCF_DCF": {
                "signal":      m1_signal,
                "delta":       m1_delta,
                "skip_reason": m1_skip,
            },
            "EV_EBITDA": {
                "signal":      m2_signal,
                "delta_pct":   m2_delta_pct,
                "skip_reason": m2_skip,
            },
            "Residual_Income_EBO": {
                "signal":      m3_signal,
                "delta_pp":    m3_delta_pp,
                "skip_reason": m3_skip,
            },
        },
        "rationale_e": rationale_e,
        "rationale_z": rationale_z,
    }


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main() -> int:
    print("[multi_method_valuation] AHF-2 Aggregator — median-of-3 triangulation...")
    tickers = _load_watchlist_tickers()
    if not tickers:
        print("[multi_method_valuation] No watchlist tickers; exiting.")
        return 0

    # Load Method 2 + Method 3 data files (file-level graceful degradation)
    m2_data = _load_json("ev_ebitda_valuation.json", {})
    m3_data = _load_json("residual_income_valuation.json", {})
    if not m2_data:
        print("[multi_method_valuation] WARN: ev_ebitda_valuation.json missing; M2 unavailable for all tickers.")
    if not m3_data:
        print("[multi_method_valuation] WARN: residual_income_valuation.json missing; M3 unavailable for all tickers.")

    results = {}
    for t in tickers:
        block = compute_for_ticker(t, m2_data, m3_data)
        results[t] = block
        used = "+".join(m[:3] for m in block["methods_used"]) if block["methods_used"] else "—"
        flag = " [biotech]" if block["is_biotech_fallback"] else (" [partial]" if block["is_partial"] else "")
        print(f"  {t:<12}: {block['triangulated_signal']:<16}  "
              f"n={block['methods_count']}  methods=[{used}]{flag}")

    out = {
        "_meta": {
            "generated_at":    datetime.now(timezone.utc).isoformat(),
            "schema_version":  1,
            "method":          "median_of_3_signals_aggregator",
            "tie_break_rule":  "n2_consensus_only",
            "input_methods": [
                {"id": 1, "name": "FCF_DCF",            "source": "rdcf_<safe>.json",          "delta_unit": "raw"},
                {"id": 2, "name": "EV_EBITDA",          "source": "ev_ebitda_valuation.json",  "delta_unit": "pct"},
                {"id": 3, "name": "Residual_Income_EBO","source": "residual_income_valuation.json", "delta_unit": "pp"},
            ],
            "thresholds_status": "[unvalidated intuition for n=2 tie-break and inherited per-method thresholds]",
            "note": (
                "AHF-2 v1 final aggregator. Median-of-signals (NOT median-of-deltas; "
                "delta units are incompatible across methods — see input_methods.delta_unit). "
                "Each method owns its native classification threshold (M1: ±0.05, M2: ±15%, "
                "M3: ±15pp). NOT folded into VP composite (INVARIANT 3 — preserves AHF-1 "
                "calibration anchor + AHF-3 persona-deterministic-only philosophy)."
            ),
        },
        "tickers": results,
    }
    DATA.joinpath("multi_method_valuation.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[multi_method_valuation] Done. Wrote {len(results)} ticker entries to multi_method_valuation.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
