#!/usr/bin/env python3
"""
scripts/fragility_score.py — Taleb-style fragility / antifragility scoring (AHF-1)

Per AHF_COMPARISON.md (KR9 from run 2026-04-29-2241): our 5 VP dimensions are
all upside-edge metrics (expectation_gap, fundamental_accel, narrative_shift,
low_coverage, catalyst_prox). None of them measure how fragile a position is.
A high-VP position can still blow up if the underlying business is fragile.

This script fills that gap with a 5-component composite, 0-100 (higher = more
fragile), inspired by Nassim Taleb's antifragility framework as implemented
in virattt/ai-hedge-fund's nassim_taleb.py agent. Implementation is original
(not vendored); thresholds are independently chosen [unvalidated intuition]
for A-share/HK universe.

WHAT THIS METRIC MEASURES (and what it does NOT)
-------------------------------------------------
This is FINANCIAL fragility: leverage, liquidity-of-survival, return-
distribution tails, vol regime, drawdown experience. It captures
"what does the income statement / balance sheet / price tape say about
this name's robustness to financial stress?"

It is NOT business-model fragility. Concretely, it does NOT measure:
- Single-asset / concentration risk (e.g. one drug = 80% of pipeline)
- Regulatory binary outcomes (e.g. CELESTIAL Phase 3 readout)
- Customer concentration (e.g. one client = 50% of revenue)
- Competitive moat erosion timeline
- Geographic / political concentration

A name can score "ROBUST" here while having severe business-model tail
risk. 6160.HK BeOne is the canonical example: post-Brukinsa-launch
financial profile is genuinely robust (cash-positive, low D/E, moderate
vol), so this metric scores it at the ROBUST band. But its single-asset
clinical exposure + the upcoming CELESTIAL Phase 3 binary make its
business-model fragility much higher than the score suggests. The
wrongIf monitor (in daily_decision.py) catches the binary-event tail;
this score complements it on the financial side.

Read this metric as: "given that the business model holds, how robust
is the financial structure?" Pair it with:
- wrongIf monitor for binary-event tail risk
- VP composite for upside-edge
- (Future KR) F6 concentration-risk dimension for single-asset / customer
  / geographic concentration

Reads:
  public/data/watchlist.json    — single source of truth for ticker list
  public/data/fin_*.json        — financial history (5 years)
  public/data/ohlc_*.json       — daily OHLCV (~122 candles available today;
                                  more history would improve F3/F5 — see
                                  "Open scoping notes" below)

Writes:
  public/data/fragility_<safe_id>.json  per watchlist ticker

Composite (equal-weight average of 5 components, all 0-100, higher = more fragile):

  F1 LEVERAGE          — D/E ratio. ≥2.0 → 100; ≤0.3 → 0; linear.
                         [unvalidated intuition] thresholds from Taleb literature
                         (D/E < 0.3 = robust per "Antifragile" framing).

  F2 LIQUIDITY-OF-SURVIVAL — bifurcates on biotech detection:
    Standard mode (FCF positive >= 40% of last 5 years):
      % of last 5y with positive Free Cash Flow. ≤40% → 100; ≥80% → 0.
    Biotech / loss-making mode (FCF positive < 40% historically):
      Cash runway in quarters = current_cash / |latest_quarterly_burn|.
      ≥8 quarters (2 years) → 0; ≤2 quarters (6 months) → 100.
    Detection heuristic: if 5y FCF history shows ≥60% negative years,
    treat as loss-making. Avoids structural penalty against clinical-
    stage names that hold cash to fund pipeline (e.g. early-stage 6160.HK).

  F3 TAIL RISK         — excess kurtosis of daily returns. ≥5 → 100; ≤0 → 0.
                         Higher kurtosis = fatter tails = more fragility.

  F4 VOL REGIME        — annualised vol from daily returns × √252.
                         ≥60% → 100; ≤20% → 0.

  F5 MAX DRAWDOWN      — peak-to-trough on close prices. ≥60% → 100; ≤15% → 0.

NOT folded into VP composite (INVARIANT 3 requires explicit Junyan approval
to change VP weights 25/25/20/15/15). Output is a separate file consumed by
Dashboard as a "Fragility" pill alongside the existing VP score.

Open scoping notes:
1. Equal-weight averaging puts F4 (market vol) at 20% of composite; for
   stable-fundamental high-vol names like Innolight (300308.SZ), F4=100
   dominates despite stellar F1+F2. A future variant could tilt toward
   fundamentals (F1+F2 weighted 60-70%). Default ships equal-weight per
   AHF_COMPARISON_CALIBRATION.md decision; flagged [unvalidated intuition].
2. Thresholds are Taleb-literature priors. A-share/HK calibration would
   need n>>5 tickers + closed trades. [unvalidated intuition].
3. Price history limited to ~122 days (current fetch_data window).
   Lengthening to 250+ days would improve F3 kurtosis + F5 drawdown
   stability. Out of scope for this KR; track in fetch_data widening
   future KR.
"""

import json
import math
from pathlib import Path
from datetime import datetime, timezone
from statistics import mean, stdev

DATA_DIR = Path(__file__).parent.parent / "public" / "data"


# ── Load helpers ──────────────────────────────────────────────────────────────

def _load_json(name, default=None):
    p = DATA_DIR / name
    if not p.exists():
        return default if default is not None else {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def _load_watchlist_tickers():
    """Single source of truth — never hardcode tickers."""
    wl = _load_json("watchlist.json", {})
    return list(wl.get("tickers", {}).keys())


def _load_concentration_seed(ticker):
    """F6 single-asset/concentration risk seed from watchlist.json (MANUAL).

    Returns dict {score, rationale_e, rationale_z} or None if not seeded.

    F6 is NOT folded into the composite (would change band semantics
    without Junyan approval per INVARIANT 3-style conservatism).
    Reported as a separate field in fragility_*.json output. Surfaces
    in the Dashboard pill tooltip alongside F1-F5.

    Why MANUAL (not auto-derived from financials): single-asset /
    customer / geographic / business-line concentration is judgment-
    call data. Not reliably extractable from yfinance segment reports
    or fin_*.json line items. Hand-seeded in watchlist.json (similar
    to narrative_shift, catalyst_prox).
    """
    wl = _load_json("watchlist.json", {})
    seed = (wl.get("tickers", {}) or {}).get(ticker, {}).get("vp_seed", {}) or {}
    cs = seed.get("concentration_seed")
    if not isinstance(cs, dict):
        return None
    score = cs.get("score")
    if score is None:
        return None
    return {
        "score":       score,
        "rationale_e": cs.get("rationale_e", ""),
        "rationale_z": cs.get("rationale_z", ""),
    }


# ── Component computations ───────────────────────────────────────────────────

def _f1_leverage(de_ratio):
    """D/E ratio → fragility 0-100. [unvalidated intuition] thresholds."""
    if de_ratio is None:
        return None
    if de_ratio >= 2.0:
        return 100.0
    if de_ratio <= 0.3:
        return 0.0
    return round((de_ratio - 0.3) / (2.0 - 0.3) * 100, 1)


def _f2_fcf_consistency(fcf_positive_pct):
    """% positive FCF years → fragility (inverted). [unvalidated intuition]."""
    if fcf_positive_pct is None:
        return None
    if fcf_positive_pct <= 40:
        return 100.0
    if fcf_positive_pct >= 80:
        return 0.0
    return round((80 - fcf_positive_pct) / (80 - 40) * 100, 1)


def _f2_cash_runway(cash, latest_fcf_annual):
    """Cash runway in quarters → fragility (biotech mode).
    [unvalidated intuition]: ≥8 quarters (2y) = robust, ≤2 = highly fragile.
    Treats annual FCF as 4× quarterly burn for simplicity."""
    if cash is None or latest_fcf_annual is None:
        return None
    if latest_fcf_annual >= 0:
        # Not actually burning cash this year — no fragility on this dim
        return 0.0
    quarterly_burn = abs(latest_fcf_annual) / 4
    if quarterly_burn <= 0 or cash <= 0:
        return 100.0
    runway = cash / quarterly_burn
    if runway >= 8:
        return 0.0
    if runway <= 2:
        return 100.0
    return round((8 - runway) / (8 - 2) * 100, 1)


def _f3_tail_risk(excess_kurtosis):
    """Excess kurtosis of daily returns → fragility. [unvalidated intuition]."""
    if excess_kurtosis is None:
        return None
    if excess_kurtosis >= 5:
        return 100.0
    if excess_kurtosis <= 0:
        return 0.0
    return round(excess_kurtosis / 5 * 100, 1)


def _f4_vol_regime(annual_vol):
    """Annualised vol → fragility. [unvalidated intuition]."""
    if annual_vol is None:
        return None
    if annual_vol >= 0.60:
        return 100.0
    if annual_vol <= 0.20:
        return 0.0
    return round((annual_vol - 0.20) / (0.60 - 0.20) * 100, 1)


def _f5_max_drawdown(max_dd):
    """Max drawdown → fragility. [unvalidated intuition]."""
    if max_dd is None:
        return None
    if max_dd >= 0.60:
        return 100.0
    if max_dd <= 0.15:
        return 0.0
    return round((max_dd - 0.15) / (0.60 - 0.15) * 100, 1)


# ── Data extractors ──────────────────────────────────────────────────────────

def _extract_fin_metrics(ticker):
    """Pull fragility-relevant fundamentals from fin_<safe>.json."""
    safe = ticker.replace(".", "_")
    fin = _load_json(f"fin_{safe}.json", {})
    inc = fin.get("income_statement", {}) or {}
    cf = fin.get("cash_flow", {}) or {}
    bs = fin.get("balance_sheet", {}) or {}

    years = sorted(inc.keys(), reverse=True)[:5]
    if not years:
        return None

    # FCF consistency (% positive years)
    fcf_vals = [(cf.get(y, {}) or {}).get("Free Cash Flow") for y in years]
    fcf_vals = [v for v in fcf_vals if v is not None]
    fcf_positive_pct = round(sum(1 for v in fcf_vals if v > 0) / len(fcf_vals) * 100, 1) if fcf_vals else None

    # Latest year balance sheet
    latest_bs = bs.get(years[0], {}) or {}
    cash = (
        latest_bs.get("Cash And Cash Equivalents")
        or latest_bs.get("Cash Cash Equivalents And Short Term Investments")
        or latest_bs.get("Cash")
    )
    total_debt = latest_bs.get("Total Debt")
    if total_debt is None:
        long_debt = latest_bs.get("Long Term Debt") or 0
        curr_debt = latest_bs.get("Current Debt") or 0
        total_debt = long_debt + curr_debt
    equity = (
        latest_bs.get("Total Stockholder Equity")
        or latest_bs.get("Stockholders Equity")
        or latest_bs.get("Common Stock Equity")
        or latest_bs.get("Total Equity")
    )
    de_ratio = (total_debt / equity) if (equity and equity > 0) else None

    # Operating margin trend (used for biotech detection + future use)
    op_margins = []
    for y in years:
        rev = (inc.get(y, {}) or {}).get("Total Revenue") or (inc.get(y, {}) or {}).get("Operating Revenue")
        op_inc = (inc.get(y, {}) or {}).get("Operating Income") or (inc.get(y, {}) or {}).get("EBIT")
        if rev and op_inc and rev > 0:
            op_margins.append(op_inc / rev)
    op_margin_mean = mean(op_margins) if op_margins else None
    op_margin_cv = (stdev(op_margins) / mean(op_margins)) if (len(op_margins) >= 2 and mean(op_margins) > 0) else None

    # Latest annual FCF (for biotech-mode runway calc)
    latest_fcf = (cf.get(years[0], {}) or {}).get("Free Cash Flow")

    return {
        "years_available":   len(years),
        "fcf_positive_pct":  fcf_positive_pct,
        "latest_cash":       cash,
        "latest_fcf_annual": latest_fcf,
        "de_ratio":          de_ratio,
        "op_margin_mean":    op_margin_mean,
        "op_margin_cv":      op_margin_cv,
    }


def _extract_price_metrics(ticker):
    """Pull return-distribution metrics from ohlc_<safe>.json. Uses whatever
    history is available (currently ~122 days; more history would improve
    F3/F5 stability — see header note)."""
    safe = ticker.replace(".", "_")
    ohlc = _load_json(f"ohlc_{safe}.json", {})
    candles = ohlc.get("data", []) or []
    if len(candles) < 60:
        return None
    closes = [c.get("close") for c in candles if c.get("close")]
    if len(closes) < 60:
        return None

    returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
    if len(returns) < 60:
        return None

    mu = mean(returns)
    sigma = stdev(returns) if len(returns) > 1 else 0
    if sigma == 0:
        return None

    n = len(returns)
    skew = (1/n) * sum((r - mu) ** 3 for r in returns) / (sigma ** 3)
    excess_kurtosis = (1/n) * sum((r - mu) ** 4 for r in returns) / (sigma ** 4) - 3

    annual_vol = sigma * math.sqrt(252)

    # Max drawdown over the available window
    peak = closes[0]
    max_dd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        if peak > 0:
            dd = (peak - c) / peak
            if dd > max_dd:
                max_dd = dd

    return {
        "n_returns":       n,
        "annual_vol":      round(annual_vol, 4),
        "skew":            round(skew, 3),
        "excess_kurtosis": round(excess_kurtosis, 3),
        "max_drawdown":    round(max_dd, 4),
    }


# ── Composite ────────────────────────────────────────────────────────────────

def _is_loss_making_history(fin_m):
    """Detect whether the 5-year history is loss-making/biotech-style.

    Heuristic (CONJUNCTIVE — tightened in KR2):
      op_margin_mean < 0  AND  fcf_positive_pct < 40

    Both conditions required:
      (a) op_margin_mean < 0 — structural state of the business is loss-
          making at the operating line.
      (b) fcf_positive_pct < 40 — cash flow has been historically
          negative (i.e. the company has been burning cash, not just
          intermittently FCF-negative).

    Why conjunctive AND:
      - (b) alone is too LOOSE — catches deep-cyclicals in downturns
        (e.g. a commodity producer with 3 of 5 bad FCF years would
        flip into biotech mode even though it's profitable on average).
      - (a) alone is too TIGHT — misses biotechs that just turned
        op-margin-positive but are still flipping FCF sign (rare
        transition window).
      - (a) AND (b) is the discriminating filter: rules out cyclicals
        via (a), keeps structurally-loss-making businesses (clinical
        biotech, early-stage growth burning to revenue) which trip
        both conditions.

    Verified on current watchlist 2026-04-30:
      BeOne 6160.HK   op_margin -45.5%, FCF positive 25%  → both TRUE  → biotech-mode
      Innolight       op_margin +24.3%, FCF positive 100% → (a) FALSE  → standard
      Tencent         op_margin +28.1%, FCF positive 100% → (a) FALSE  → standard
      NetEase         op_margin +26.8%, FCF positive 100% → (a) FALSE  → standard
      BYD             op_margin  +5.9%, FCF positive 75%  → (a) FALSE  → standard

    Uses cash-runway F2 instead of FCF-consistency F2 when this fires.
    """
    if not fin_m:
        return False
    fcf_pos = fin_m.get("fcf_positive_pct")
    op_margin_mean = fin_m.get("op_margin_mean")
    if fcf_pos is None or op_margin_mean is None:
        return False
    return op_margin_mean < 0 and fcf_pos < 40


def compute_fragility(ticker):
    """Compute full fragility breakdown for a ticker. Returns None if data missing."""
    fin_m = _extract_fin_metrics(ticker)
    price_m = _extract_price_metrics(ticker)
    if not fin_m and not price_m:
        return None

    biotech_mode = _is_loss_making_history(fin_m)

    # F1 leverage
    f1 = _f1_leverage(fin_m.get("de_ratio")) if fin_m else None

    # F2 — bifurcates
    if biotech_mode:
        f2 = _f2_cash_runway(fin_m.get("latest_cash"), fin_m.get("latest_fcf_annual"))
        f2_method = "cash_runway"
    else:
        f2 = _f2_fcf_consistency(fin_m.get("fcf_positive_pct")) if fin_m else None
        f2_method = "fcf_consistency"

    # F3, F4, F5 from price metrics
    f3 = _f3_tail_risk(price_m.get("excess_kurtosis")) if price_m else None
    f4 = _f4_vol_regime(price_m.get("annual_vol")) if price_m else None
    f5 = _f5_max_drawdown(price_m.get("max_drawdown")) if price_m else None

    components = {"F1_leverage": f1, "F2_liquidity_survival": f2, "F3_tail_risk": f3,
                  "F4_vol_regime": f4, "F5_max_drawdown": f5}

    valid = [v for v in components.values() if v is not None]
    composite = round(mean(valid), 1) if valid else None

    # F6 single-asset/concentration risk — MANUAL seed from watchlist.json,
    # NOT folded into composite (separate dimension, judgment-call data,
    # would change band semantics without explicit approval). Reported as
    # standalone field for Dashboard pill tooltip + handoff doc reference.
    f6 = _load_concentration_seed(ticker)

    return {
        "ticker":              ticker,
        "composite":           composite,
        "components":          components,
        "f6_concentration":    f6,  # separate from composite — see note above
        "biotech_mode":        biotech_mode,
        "f2_method":           f2_method,
        "fundamentals":        fin_m,
        "price_metrics":       price_m,
        "label":               "[unvalidated intuition]",
        "valid_components":    len(valid),
    }


def _band(score):
    """Map composite score to band label. [unvalidated intuition] thresholds."""
    if score is None:
        return "INSUFFICIENT_DATA"
    if score >= 50:
        return "FRAGILE"
    if score >= 30:
        return "MODERATE"
    if score >= 15:
        return "ROBUST"
    return "ANTIFRAGILE"


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("[fragility_score] Computing Taleb-style fragility scores per watchlist ticker...")

    tickers = _load_watchlist_tickers()
    if not tickers:
        print("  [ERROR] no watchlist tickers loaded")
        return

    summary = []
    for ticker in tickers:
        result = compute_fragility(ticker)
        if not result:
            print(f"  {ticker:12s}: skipped (insufficient data)")
            continue

        comps = result["components"]
        c_str = ", ".join(f"{k.split('_',1)[0]}={v:.0f}" if v is not None else f"{k.split('_',1)[0]}=N/A"
                          for k, v in comps.items())
        mode_tag = " [biotech-mode]" if result["biotech_mode"] else ""
        composite = result["composite"]
        composite_str = f"{composite:5.1f}" if composite is not None else "  N/A"
        band = _band(composite)
        f6 = result.get("f6_concentration")
        f6_str = f"  F6={f6['score']:.0f}" if f6 else "  F6=N/A"
        print(f"  {ticker:12s}: composite={composite_str}  band={band:<13s}  {c_str}{f6_str}{mode_tag}")

        # Per-ticker file output
        safe = ticker.replace(".", "_")
        f6 = result.get("f6_concentration")
        out = {
            "generated_at":     datetime.now(timezone.utc).isoformat(),
            "ticker":           ticker,
            "composite":        composite,
            "band":             band,
            "components":       comps,
            "f6_concentration": f6,   # MANUAL seed from watchlist.json; NOT in composite
            "biotech_mode":     result["biotech_mode"],
            "f2_method":        result["f2_method"],
            "valid_components": result["valid_components"],
            "fundamentals":     result["fundamentals"],
            "price_metrics":    result["price_metrics"],
            "label":            "[unvalidated intuition] — composite measures FINANCIAL fragility (leverage, liquidity, return-distribution tails, vol, drawdown). Does NOT measure business-model fragility — that lives in the SEPARATE f6_concentration field below (MANUAL seed from watchlist.json, NOT folded into composite). For clinical-stage biotech with single-asset exposure, read composite + f6 together: a 'ROBUST' composite + high f6 score still implies elevated overall tail risk. Pair with wrongIf monitor for binary-event coverage. Thresholds are Taleb-literature priors, not validated against A-share/HK trade history.",
            "weighting":      "equal-weight (F1..F5 each 20%) — fundamentals-tilted variant deferred per AHF_COMPARISON_CALIBRATION.md open question Q1",
            "history_window": "ohlc length used for F3/F5/vol; longer window (250+ days) would improve stability — current fetch_data limits to ~122 days",
        }
        out_path = DATA_DIR / f"fragility_{safe}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

        summary.append({"ticker": ticker, "composite": composite, "band": band})

    print(f"\n[fragility_score] Done. {len(summary)} files written.")
    if summary:
        # Sorted-most-fragile-first summary
        summary.sort(key=lambda s: -(s["composite"] if s["composite"] is not None else -1))
        print("\nFragility ranking (most fragile first):")
        for s in summary:
            score = f"{s['composite']:.1f}" if s["composite"] is not None else "N/A"
            print(f"  {s['ticker']:12s}: {score:>5}  {s['band']}")


if __name__ == "__main__":
    main()
