#!/usr/bin/env python3
"""
scripts/ev_ebitda_valuation.py — AHF-2 Method 2: EV/EBITDA target-multiple valuation.

PURPOSE
=======
Cross-check valuation lens for the AHF-2 multi-method triangulation.
Compares each ticker's current EV/EBITDA multiple against a per-market
target multiple, computing implied "fair equity value" → delta vs market
cap → UNDERPRICED / FAIRLY_VALUED / OVERPRICED signal.

This is one of three orthogonal estimators in AHF-2 v1:
  - Method 1: FCF DCF (existing, in scripts/fetch_data.py rdcf engine)
  - Method 2: EV/EBITDA target-multiple (this script)
  - Method 3: Residual Income / Edwards-Bell-Ohlson (KR2 next)

Triangulation aggregator (KR3 pending) takes median of 3 signals per
ticker. NOT folded into VP composite (INVARIANT 3 — preserves AHF-1
calibration anchor + KR3 persona-deterministic-only philosophy).

PROVENANCE
==========
AHF_COMPARISON.md Tier 1 A2 — strategic doc recommendation. Locked-in
strategic decisions in `.night-shift/AHF-2_HANDOFF.md` from prior shift
2026-04-30-1532 (KR9 DEFER_C consensus):
  - 3 orthogonal estimators
  - Biotech blind spot: Option 1 (Skip) — 6160.HK falls back to
    existing biotech_revenue rdcf model
  - Triangulation: median-of-3
  - Single multi-ticker output file (matches AHF-3 persona_overlay)

METHOD
======
For each non-biotech ticker:
    fair_ev    = current_ebitda × target_multiple
    fair_equity = fair_ev - net_debt
    delta_pct  = (fair_equity / market_cap - 1.0) × 100
    signal     = UNDERPRICED if delta > +15
                 OVERPRICED  if delta < -15
                 FAIRLY_VALUED otherwise

For 6160.HK (biotech): emit `model_status: biotech_fallback` with
`signal: null`. Method 1 rdcf biotech_revenue remains its valuation.

THRESHOLD RATIONALE [unvalidated intuition]
==========
**Per-market target multiples:**
  A-share: 15x  (CSI300 historical median ~12-18x; 15x = top of fair range)
  HK:      12x  (HSI historical median ~10-15x; 12x = mid range)
Single-multiple-per-market is v1 simplification. Per-sector calibration
(e.g., Tech 25x, mature consumer 12x) is a future KR — same shape as
the AHF-1 SECTOR_BETA_DEFAULTS work pending.

**±15% signal threshold:** multiple-analysis convention. Persona
Damodaran's ±5% is for story-vs-numbers DCF input precision — different
framework, different precision needs. Multiple-comparison's ±15% reflects
typical "within noise band for blunt-multiple comparison."

NOT FOLDED INTO VP COMPOSITE — INVARIANT 3 forbids changing VP weights
without Junyan approval.

Author: Night-shift run 2026-04-30-2323 KR1 (AHF-2 sub-KR 1 of 3-4)
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

# Per-market target EV/EBITDA multiples [unvalidated intuition]
# A-share: 15x  (CSI300 historical median ~12-18x)
# HK:      12x  (HSI historical median ~10-15x)
# Per-sector calibration is a future KR.
TARGET_MULTIPLES = {"A": 15.0, "HK": 12.0}

# Signal classification threshold [unvalidated intuition]
# ±15% delta from fair value follows multiple-analysis convention.
# Different from persona Damodaran's ±5% (DCF input precision is a
# different framework with different precision needs).
SIGNAL_THRESHOLD_PCT = 15.0

# Biotech fallback rationale template
BIOTECH_FALLBACK_REASON = (
    "Clinical-stage biotech: EV/EBITDA at {ev_ebitda:.2f}x is a structural "
    "artifact of negative-or-near-zero EBITDA, not a valuation signal. "
    "Method 1 rdcf biotech_revenue remains the canonical valuation "
    "for this ticker."
)
BIOTECH_FALLBACK_REASON_Z = (
    "临床期生物科技：EV/EBITDA = {ev_ebitda:.2f}x 是负值或近零EBITDA的"
    "结构性产物，非估值信号。Method 1 rdcf biotech_revenue 仍是该股票"
    "的标准估值方法。"
)

# Typed error codes for graceful degradation (per decomp P3-ii)
ERR_FUNDAMENTALS_MISSING = "fundamentals_missing"
ERR_EBITDA_MISSING       = "ebitda_missing"
ERR_EV_DATA_MISSING      = "ev_data_missing"


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
# Core computation
# ─────────────────────────────────────────────────────────────────────────

def _classify_signal(delta_pct: float) -> str:
    """±15% threshold per AHF-2 KR1 decomp Resolution β."""
    if delta_pct > SIGNAL_THRESHOLD_PCT:
        return "UNDERPRICED"
    if delta_pct < -SIGNAL_THRESHOLD_PCT:
        return "OVERPRICED"
    return "FAIRLY_VALUED"


def compute_for_ticker(ticker: str, market_data: dict) -> dict:
    """Compute EV/EBITDA valuation for one ticker.

    Returns a dict with `model_status` indicating success or graceful
    degradation. Detection order (per decomp P3 #2):
      1. Biotech detection (rdcf.model_type == 'biotech_revenue') →
         model_status='biotech_fallback', signal=null
      2. Fundamentals presence check
      3. EBITDA derivation: direct → fallback → typed error
      4. Market cap presence check
      5. Compute fair value, classify signal
    """
    # Step 1: load rdcf for biotech detection + market identification + net_debt
    rdcf = _load_json(f"rdcf_{_safe_id(ticker)}.json", {}) or {}
    rdcf_model = rdcf.get("model_type")

    # Step 1: biotech early-return BEFORE EBITDA derivation
    if rdcf_model == "biotech_revenue":
        fund_for_ev = ((market_data or {}).get("yahoo") or {}).get(ticker, {}).get("fundamentals") or {}
        observed = fund_for_ev.get("ev_ebitda") or 0
        return {
            "ticker":             ticker,
            "model_status":       "biotech_fallback",
            "signal":             None,
            "delta_pct":          None,
            "current_ev_ebitda":  observed,
            "reason":             BIOTECH_FALLBACK_REASON.format(ev_ebitda=observed),
            "reason_z":           BIOTECH_FALLBACK_REASON_Z.format(ev_ebitda=observed),
        }

    # Step 2: fundamentals presence
    yahoo = ((market_data or {}).get("yahoo") or {}).get(ticker) or {}
    fund = yahoo.get("fundamentals") or {}
    if not fund:
        return {
            "ticker":       ticker,
            "model_status": ERR_FUNDAMENTALS_MISSING,
            "signal":       None,
            "delta_pct":    None,
            "reason":       "market_data.json fundamentals block missing for ticker",
        }

    # Step 3: EBITDA derivation chain (per P3-iii from approval)
    ebitda = fund.get("ebitda")
    if ebitda is None or ebitda == 0:
        ev_for_calc = fund.get("enterprise_value")
        ev_ebitda_ratio = fund.get("ev_ebitda")
        if ev_for_calc and ev_ebitda_ratio and ev_ebitda_ratio > 0:
            ebitda = ev_for_calc / ev_ebitda_ratio
        else:
            return {
                "ticker":       ticker,
                "model_status": ERR_EBITDA_MISSING,
                "signal":       None,
                "delta_pct":    None,
                "reason":       "Both fund.ebitda and (enterprise_value / ev_ebitda) derivation failed",
            }

    # Step 4: market_cap presence
    market_cap = fund.get("market_cap")
    if not market_cap or market_cap <= 0:
        return {
            "ticker":       ticker,
            "model_status": ERR_EV_DATA_MISSING,
            "signal":       None,
            "delta_pct":    None,
            "reason":       "fund.market_cap missing or non-positive",
        }

    # Step 5: compute fair value + classify
    market = (rdcf.get("wacc_detail") or {}).get("market") or "HK"  # default HK if rdcf missing
    target = TARGET_MULTIPLES.get(market, TARGET_MULTIPLES["HK"])
    net_debt = rdcf.get("net_debt") or 0  # positive when net debt; negative when net cash
    current_ev_ebitda = fund.get("ev_ebitda")

    fair_ev = ebitda * target
    fair_equity = fair_ev - net_debt
    delta_pct = round((fair_equity / market_cap - 1.0) * 100, 2)
    signal = _classify_signal(delta_pct)

    rationale_e = (
        f"EV/EBITDA {current_ev_ebitda:.2f}x vs {market}-target {target:.0f}x; "
        f"fair_equity {fair_equity/1e9:+.1f}B vs market_cap {market_cap/1e9:.1f}B; "
        f"delta {delta_pct:+.1f}% → {signal}"
    )
    rationale_z = (
        f"EV/EBITDA {current_ev_ebitda:.2f}x，{market}市场目标{target:.0f}x；"
        f"公允股权 {fair_equity/1e9:+.1f}B vs 市值 {market_cap/1e9:.1f}B；"
        f"delta {delta_pct:+.1f}% → {signal}"
    )

    return {
        "ticker":            ticker,
        "model_status":      "multi_method",
        "signal":            signal,
        "delta_pct":         delta_pct,
        "current_ev_ebitda": current_ev_ebitda,
        "current_ebitda":    round(ebitda, 0),
        "target_multiple":   target,
        "fair_ev":           round(fair_ev, 0),
        "fair_equity":       round(fair_equity, 0),
        "market_cap":        round(market_cap, 0),
        "net_debt":          round(net_debt, 0),
        "market":            market,
        "rationale_e":       rationale_e,
        "rationale_z":       rationale_z,
    }


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main() -> int:
    print("[ev_ebitda_valuation] AHF-2 Method 2 — target-multiple comparison...")
    tickers = _load_watchlist_tickers()
    if not tickers:
        print("[ev_ebitda_valuation] No watchlist tickers; exiting.")
        return 0

    market_data = _load_json("market_data.json", {}) or {}
    if not market_data:
        print("[ev_ebitda_valuation] WARN: market_data.json missing; emitting empty output.")

    results = {}
    for t in tickers:
        block = compute_for_ticker(t, market_data)
        results[t] = block
        if block["model_status"] == "multi_method":
            print(f"  {t:<12}: {block['signal']:<14}  delta={block['delta_pct']:+.1f}%  "
                  f"({block['market']}-target {block['target_multiple']:.0f}x vs current {block['current_ev_ebitda']:.2f}x)")
        elif block["model_status"] == "biotech_fallback":
            print(f"  {t:<12}: biotech_fallback (ev_ebitda={block.get('current_ev_ebitda', 0):.2f}x — artifact)")
        else:
            print(f"  {t:<12}: degraded ({block['model_status']})")

    out = {
        "_meta": {
            "generated_at":         datetime.now(timezone.utc).isoformat(),
            "schema_version":       1,
            "thresholds_status":    "[unvalidated intuition]",
            "method":               "ev_ebitda_target_multiple",
            "target_multiples":     TARGET_MULTIPLES,
            "signal_threshold_pct": SIGNAL_THRESHOLD_PCT,
            "note": (
                "AHF-2 Method 2. NOT folded into VP composite (INVARIANT 3). "
                "Triangulated with FCF DCF (Method 1) + Residual Income "
                "(Method 3, KR2 pending) by KR3 aggregator (pending). "
                "Per-market single-multiple is v1; per-sector targets "
                "deferred to future KR."
            ),
        },
        "tickers": results,
    }
    DATA.joinpath("ev_ebitda_valuation.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[ev_ebitda_valuation] Done. Wrote {len(results)} ticker entries to ev_ebitda_valuation.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
