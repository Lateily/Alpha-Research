#!/usr/bin/env python3
"""
scripts/residual_income_valuation.py — AHF-2 Method 3: Residual Income
                                        (Edwards-Bell-Ohlson) valuation.

PURPOSE
=======
Third orthogonal estimator in AHF-2 multi-method triangulation. Exits
BOTH the cash-flow assumption space (Method 1 FCF DCF) AND the multiples
regime (Method 2 EV/EBITDA). Frames valuation in book-value terms:

    P = B0 × [1 + (ROE - r_e) × A(n, r_e)]

Where the model asks: "given current price P + book equity B0, what
future ROE does the market implicitly require to justify the spread?"
Compare to actual current ROE for under/overvaluation signal.

This is the third lens for AHF-2 v1. After this KR ships, KR3
(aggregator) takes median-of-3 across {FCF DCF, EV/EBITDA, RI}.

PROVENANCE
==========
AHF_COMPARISON.md Tier 1 A2 — strategic doc recommendation. Locked-in
strategic decisions in `.night-shift/AHF-2_HANDOFF.md` from prior shift
2026-04-30-1532 (KR9 DEFER_C consensus):
  - 3 orthogonal estimators (FCF DCF + EV/EBITDA + Residual Income)
  - Biotech blind spot: Option 1 (Skip) — 6160.HK falls back to
    existing biotech_revenue rdcf model
  - Triangulation: median-of-3 (KR3 pending)
  - Single multi-ticker output file
  - WACC as r_e proxy (Q2 option a)

METHOD (no-growth multistage EBO)
==========
Standard Edwards-Bell-Ohlson 1994 derivation:
  P = B0 + Σ_{t=1}^{∞} RI_t / (1+r_e)^t
  RI_t = (ROE_t - r_e) × B_{t-1}

With constant-ROE no-book-growth assumption (v1 simplification):
  P = B0 + (ROE - r_e) × B0 × A(n, r_e)
  A(n, r) = (1 - (1+r)^-n) / r + 1 / (r × (1+r)^n)
            └────── annuity ──────┘   └─ perpetuity at year n ─┘

Inverting for implied ROE:
  P / B0 = 1 + (ROE - r_e) × A(n, r_e)
  ROE_implied = r_e + (P/B - 1) / A(n, r_e)

Signal classification:
  delta_pp = (current_ROE - implied_ROE) × 100   ← percentage points
  UNDERPRICED if delta_pp > +SIGNAL_THRESHOLD_PP
  OVERPRICED  if delta_pp < -SIGNAL_THRESHOLD_PP
  FAIRLY_VALUED otherwise

UNIT NOTE (per KR3 aggregator forward-compat):
  KR1 EV/EBITDA uses `delta_pct` (percent of market cap, ratio).
  KR2 RI uses `delta_pp` (percentage points of ROE, absolute).
  Different semantics → different field names. KR3 aggregator must
  classify signals from each method WITHOUT cross-comparing the raw
  numerics — only the {UNDERPRICED, FAIRLY_VALUED, OVERPRICED} signal
  enums are unit-comparable.

GRACEFUL DEGRADATION (typed error codes)
==========
- biotech_fallback           — rdcf.model_type == 'biotech_revenue'
                                (early-return BEFORE math)
- hyper_growth_ebo_unstable  — P/B > P_B_HYPER_GROWTH_CEILING (10).
                                Mathematical artifact: implied ROE
                                exceeds 100% which is semantically
                                meaningless. Method 1 + Method 2
                                remain canonical for hyper-growth.
- fundamentals_missing       — market_data fundamentals absent
- roe_missing                — current_roe absent or null
- market_cap_missing         — market_cap absent or non-positive
- book_equity_missing        — fin_*.json balance_sheet absent or
                                Common Stock Equity 0
- negative_book_equity       — common_stock_equity < 0 (defensive)
- wacc_missing               — rdcf wacc_detail.wacc absent
- wacc_anomalous             — wacc < WACC_ANOMALOUS_FLOOR (0.02);
                                would inflate annuity factor and
                                produce unreliable implied ROE

THRESHOLDS [unvalidated intuition]
==========
SIGNAL_THRESHOLD_PP        = 15.0   — cross-method consistency with KR1
                                       EV/EBITDA's ±15% delta. Different
                                       units (pp vs pct) but consistent
                                       magnitude convention.
P_B_HYPER_GROWTH_CEILING   = 10.0   — above this, no-growth EBO produces
                                       implied future ROE >100%. Math is
                                       valid but signal is artifactual.
                                       Future per-sector ceilings could
                                       refine.
WACC_ANOMALOUS_FLOOR       = 0.02   — defensive only. Current universe
                                       has WACC 9-15%, well above floor.
FORECAST_HORIZON_YEARS     = 5      — matches DCF_HORIZON

R_e PROXY: WACC from rdcf wacc_detail (per handoff Q2 option a). For
low-leverage portfolio, WACC ≈ r_e by approximation. Pure ke
(rf + beta×MRP) is a future polish KR.

NOT FOLDED INTO VP COMPOSITE — INVARIANT 3 forbids changing VP weights
without Junyan approval.

Author: Night-shift run 2026-04-30-2323 KR2 (AHF-2 sub-KR 2 of 3-4)
"""

from __future__ import annotations
import json
import pathlib
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"


# ─────────────────────────────────────────────────────────────────────────
# Constants — [unvalidated intuition]
# ─────────────────────────────────────────────────────────────────────────

# Signal classification threshold [unvalidated intuition]
# ±15 percentage points of ROE delta. Cross-method consistency with KR1
# EV/EBITDA's ±15% delta convention (different units — pp vs pct — but
# consistent magnitude). Per KR2 KR_APPROVAL: "uniformly OVERPRICED"
# outcome on growth-priced portfolio is informative cross-check, not noise.
SIGNAL_THRESHOLD_PP = 15.0

# P/B sanity ceiling [unvalidated intuition]
# Above this, no-growth EBO produces implied future ROE > 100% which is
# mathematical artifact, not valuation signal. Catches Innolight (P/B≈32)
# cleanly without false-positives on Tencent/NetEase/BYD (P/B 3.5-3.8).
P_B_HYPER_GROWTH_CEILING = 10.0

# WACC anomaly floor [unvalidated intuition]
# Defensive only. Below 2%, the annuity factor explodes and implied
# ROE becomes unreliable. Current universe has WACC 9-15%; this floor
# is for future ticker additions.
WACC_ANOMALOUS_FLOOR = 0.02

# Forecast horizon — matches DCF_HORIZON in scripts/fetch_data.py
FORECAST_HORIZON_YEARS = 5

# Typed error codes for graceful degradation
ERR_FUNDAMENTALS_MISSING = "fundamentals_missing"
ERR_ROE_MISSING          = "roe_missing"
ERR_MARKET_CAP_MISSING   = "market_cap_missing"
ERR_BOOK_EQUITY_MISSING  = "book_equity_missing"
ERR_NEGATIVE_BOOK_EQUITY = "negative_book_equity"
ERR_WACC_MISSING         = "wacc_missing"
ERR_WACC_ANOMALOUS       = "wacc_anomalous"

# Biotech fallback rationale template
BIOTECH_FALLBACK_REASON = (
    "Clinical-stage biotech: book-value-regime EBO assumes meaningful ROE "
    "from existing operations; clinical biotech has no recurring earnings "
    "stream. Method 1 rdcf biotech_revenue remains the canonical valuation."
)
BIOTECH_FALLBACK_REASON_Z = (
    "临床期生物科技：账面价值法EBO假设现有经营产生稳定ROE，但临床期生物"
    "科技无经常性盈利。Method 1 rdcf biotech_revenue 仍是该股票的标准"
    "估值方法。"
)


# ─────────────────────────────────────────────────────────────────────────
# Helpers — SOT, JSON load, math
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


def _annuity_factor(n: int, r: float) -> float:
    """A(n, r) for residual income perpetuity model.

    A(n, r) = (1 - (1+r)^-n) / r + 1 / (r × (1+r)^n)
              └─── annuity PV factor ───┘   └─ perpetuity at year n ─┘

    Standard EBO closed form for "constant residual income for n years
    then perpetuity at year n+1." See Edwards-Bell-Ohlson 1994.
    """
    one_plus_r_n = (1.0 + r) ** n
    annuity = (1.0 - 1.0 / one_plus_r_n) / r
    perpetuity = 1.0 / (r * one_plus_r_n)
    return annuity + perpetuity


def _classify_signal(delta_pp: float) -> str:
    """±SIGNAL_THRESHOLD_PP threshold per AHF-2 KR2 decomp."""
    if delta_pp > SIGNAL_THRESHOLD_PP:
        return "UNDERPRICED"
    if delta_pp < -SIGNAL_THRESHOLD_PP:
        return "OVERPRICED"
    return "FAIRLY_VALUED"


# ─────────────────────────────────────────────────────────────────────────
# Core computation
# ─────────────────────────────────────────────────────────────────────────

def compute_for_ticker(ticker: str, market_data: dict) -> dict:
    """Compute Residual Income / EBO valuation for one ticker.

    Detection order (per decomp Q2 — fail-fast on data presence before
    mathematical computation):
      1. biotech_fallback (rdcf.model_type == 'biotech_revenue') — early
         return before any math
      2. fundamentals_missing
      3. roe_missing
      4. market_cap_missing
      5. book_equity_missing / negative_book_equity (from fin_*.json)
      6. hyper_growth_ebo_unstable (P/B > 10) — needs P/B computed first
      7. wacc_missing / wacc_anomalous
      8. compute EBO + classify signal
    """
    # 1. Load rdcf for biotech detection + WACC
    rdcf = _load_json(f"rdcf_{_safe_id(ticker)}.json", {}) or {}
    rdcf_model = rdcf.get("model_type")

    # Biotech early-return — same pattern as KR1 EV/EBITDA
    if rdcf_model == "biotech_revenue":
        return {
            "ticker":       ticker,
            "model_status": "biotech_fallback",
            "signal":       None,
            "delta_pp":     None,
            "reason":       BIOTECH_FALLBACK_REASON,
            "reason_z":     BIOTECH_FALLBACK_REASON_Z,
        }

    # 2. Fundamentals presence
    yahoo = ((market_data or {}).get("yahoo") or {}).get(ticker) or {}
    fund = yahoo.get("fundamentals") or {}
    if not fund:
        return {
            "ticker":       ticker,
            "model_status": ERR_FUNDAMENTALS_MISSING,
            "signal":       None,
            "delta_pp":     None,
            "reason":       "market_data.json fundamentals block missing for ticker",
        }

    # 3. ROE presence
    current_roe = fund.get("roe")
    if current_roe is None:
        return {
            "ticker":       ticker,
            "model_status": ERR_ROE_MISSING,
            "signal":       None,
            "delta_pp":     None,
            "reason":       "fund.roe missing or null",
        }

    # 4. Market cap presence
    market_cap = fund.get("market_cap")
    if not market_cap or market_cap <= 0:
        return {
            "ticker":       ticker,
            "model_status": ERR_MARKET_CAP_MISSING,
            "signal":       None,
            "delta_pp":     None,
            "reason":       "fund.market_cap missing or non-positive",
        }

    # 5. Book equity from fin_*.json balance sheet (latest year)
    fin = _load_json(f"fin_{_safe_id(ticker)}.json", {}) or {}
    bs = (fin.get("balance_sheet") or {})
    if not bs:
        return {
            "ticker":       ticker,
            "model_status": ERR_BOOK_EQUITY_MISSING,
            "signal":       None,
            "delta_pp":     None,
            "reason":       "fin_*.json balance_sheet missing",
        }
    try:
        latest_year = max(bs.keys())
    except Exception:
        return {
            "ticker":       ticker,
            "model_status": ERR_BOOK_EQUITY_MISSING,
            "signal":       None,
            "delta_pp":     None,
            "reason":       "fin_*.json balance_sheet has no usable years",
        }
    book_equity = bs.get(latest_year, {}).get("Common Stock Equity")
    if book_equity is None or book_equity == 0:
        return {
            "ticker":       ticker,
            "model_status": ERR_BOOK_EQUITY_MISSING,
            "signal":       None,
            "delta_pp":     None,
            "reason":       "Common Stock Equity missing or zero in latest balance sheet",
        }
    if book_equity < 0:
        return {
            "ticker":       ticker,
            "model_status": ERR_NEGATIVE_BOOK_EQUITY,
            "signal":       None,
            "delta_pp":     None,
            "book_equity":  round(book_equity, 0),
            "reason":       "Common Stock Equity is negative; EBO methodology not applicable (firm has accumulated losses exceeding paid-in capital)",
        }

    # 6. P/B hyper-growth check (mathematical artifact prevention)
    p_b = market_cap / book_equity
    if p_b > P_B_HYPER_GROWTH_CEILING:
        return {
            "ticker":       ticker,
            "model_status": "hyper_growth_ebo_unstable",
            "signal":       None,
            "delta_pp":     None,
            "p_b_observed": round(p_b, 2),
            "book_equity":  round(book_equity, 0),
            "market_cap":   round(market_cap, 0),
            "reason":       (
                f"P/B {p_b:.2f} > sanity ceiling {P_B_HYPER_GROWTH_CEILING:.0f}; "
                f"no-growth EBO produces implied future ROE >100% which is "
                f"mathematical artifact, not valuation signal. Method 1 rdcf "
                f"FCF DCF + Method 2 EV/EBITDA remain canonical."
            ),
            "reason_z":     (
                f"P/B {p_b:.2f} > 合理上限 {P_B_HYPER_GROWTH_CEILING:.0f}；"
                f"无增长EBO产生隐含未来ROE>100%，属数学伪影非估值信号。"
                f"Method 1 rdcf FCF DCF + Method 2 EV/EBITDA 仍是标准估值。"
            ),
        }

    # 7. WACC presence + anomaly check
    wacc = (rdcf.get("wacc_detail") or {}).get("wacc")
    if wacc is None:
        return {
            "ticker":       ticker,
            "model_status": ERR_WACC_MISSING,
            "signal":       None,
            "delta_pp":     None,
            "reason":       "rdcf.wacc_detail.wacc missing",
        }
    if wacc < WACC_ANOMALOUS_FLOOR:
        return {
            "ticker":         ticker,
            "model_status":   ERR_WACC_ANOMALOUS,
            "signal":         None,
            "delta_pp":       None,
            "wacc_observed":  round(wacc, 4),
            "reason":         f"WACC {wacc:.4f} below anomaly floor {WACC_ANOMALOUS_FLOOR:.2f}; would inflate annuity factor and produce unreliable implied ROE",
        }

    # 8. Compute EBO + classify
    a_factor = _annuity_factor(FORECAST_HORIZON_YEARS, wacc)
    implied_future_roe = wacc + (p_b - 1.0) / a_factor
    delta_pp = round((current_roe - implied_future_roe) * 100, 2)
    signal = _classify_signal(delta_pp)

    rationale_e = (
        f"P/B {p_b:.2f} → market implies forward ROE "
        f"{implied_future_roe*100:.1f}% over {FORECAST_HORIZON_YEARS}y; "
        f"current ROE {current_roe*100:.1f}%; "
        f"delta {delta_pp:+.1f}pp → {signal}"
    )
    rationale_z = (
        f"P/B {p_b:.2f} → 市场隐含未来{FORECAST_HORIZON_YEARS}年ROE "
        f"{implied_future_roe*100:.1f}%；当前ROE {current_roe*100:.1f}%；"
        f"delta {delta_pp:+.1f}pp → {signal}"
    )

    return {
        "ticker":                   ticker,
        "model_status":             "multi_method",
        "signal":                   signal,
        "delta_pp":                 delta_pp,
        "current_roe_pct":          round(current_roe * 100, 2),
        "implied_future_roe_pct":   round(implied_future_roe * 100, 2),
        "p_b_observed":             round(p_b, 2),
        "annuity_factor":           round(a_factor, 4),
        "wacc_used_as_re":          round(wacc, 4),
        "book_equity":              round(book_equity, 0),
        "market_cap":               round(market_cap, 0),
        "rationale_e":              rationale_e,
        "rationale_z":              rationale_z,
    }


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main() -> int:
    print("[residual_income_valuation] AHF-2 Method 3 — Edwards-Bell-Ohlson EBO...")
    tickers = _load_watchlist_tickers()
    if not tickers:
        print("[residual_income_valuation] No watchlist tickers; exiting.")
        return 0

    market_data = _load_json("market_data.json", {}) or {}
    if not market_data:
        print("[residual_income_valuation] WARN: market_data.json missing; emitting empty output.")

    results = {}
    for t in tickers:
        block = compute_for_ticker(t, market_data)
        results[t] = block
        status = block["model_status"]
        if status == "multi_method":
            print(f"  {t:<12}: {block['signal']:<14}  delta={block['delta_pp']:+6.1f}pp  "
                  f"(P/B {block['p_b_observed']:.2f} → implied ROE {block['implied_future_roe_pct']:.1f}% vs current {block['current_roe_pct']:.1f}%)")
        elif status == "biotech_fallback":
            print(f"  {t:<12}: biotech_fallback (no recurring earnings stream)")
        elif status == "hyper_growth_ebo_unstable":
            print(f"  {t:<12}: hyper_growth_ebo_unstable (P/B={block['p_b_observed']:.2f} > {P_B_HYPER_GROWTH_CEILING:.0f})")
        else:
            print(f"  {t:<12}: degraded ({status})")

    out = {
        "_meta": {
            "generated_at":              datetime.now(timezone.utc).isoformat(),
            "schema_version":            1,
            "thresholds_status":         "[unvalidated intuition]",
            "method":                    "residual_income_no_growth_ebo",
            "forecast_horizon_years":    FORECAST_HORIZON_YEARS,
            "signal_threshold_pp":       SIGNAL_THRESHOLD_PP,
            "p_b_hyper_growth_ceiling":  P_B_HYPER_GROWTH_CEILING,
            "wacc_anomalous_floor":      WACC_ANOMALOUS_FLOOR,
            "r_e_proxy":                 "wacc_from_rdcf_wacc_detail",
            "delta_unit":                "pp (percentage points of ROE)",
            "note": (
                "AHF-2 Method 3. NOT folded into VP composite (INVARIANT 3). "
                "WACC used as r_e proxy (handoff Q2 option a; cleaner pure ke "
                "computation deferred to future polish KR). KR3 aggregator "
                "must NOT cross-compare delta_pp (this method) vs delta_pct "
                "(KR1 EV/EBITDA) — only the {UNDERPRICED, FAIRLY_VALUED, "
                "OVERPRICED} signal enums are unit-comparable."
            ),
        },
        "tickers": results,
    }
    DATA.joinpath("residual_income_valuation.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[residual_income_valuation] Done. Wrote {len(results)} ticker entries to residual_income_valuation.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
