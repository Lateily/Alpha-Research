#!/usr/bin/env python3
"""
scripts/leading_indicators.py — AI Infrastructure Leading Indicator Engine  v1.0

Tracks UPSTREAM signals that drive demand for Chinese AI infrastructure plays
(optical transceivers, AI servers, components) BEFORE they show up in earnings.

Why this matters:
  Hyperscaler CapEx → order books at Taiwan/US component makers →
  demand at Chinese tier-2 suppliers (光模块/光芯片) → revenue 1-2Q later.
  This 3-6 month lead time is the alpha window.

Indicators tracked:
  1. NVDA quarterly revenue growth     — data center proxy (~85% of revenue)
  2. Hyperscaler CapEx index           — MSFT + GOOGL + META + AMZN combined
  3. TSMC quarterly revenue growth     — semiconductor supply chain health
  4. Hyperscaler price momentum        — real-time market sentiment (weekly)
  5. Manual entries                    — LightCounting reports, policy events

Composite signal → {STRONG_CAPEX_CYCLE / MODERATE / WEAKENING / INSUFFICIENT_DATA}

Reads:   public/data/watchlist.json   (to know which stocks each indicator affects)
Writes:  public/data/leading_indicators.json
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "public" / "data"

# ── Hyperscaler universe ──────────────────────────────────────────────────────
# Each entry: (ticker, display_name, what_we_track, weight_in_capex_index)
HYPERSCALERS = [
    ("MSFT",  "Microsoft",  "capex",   0.30),
    ("GOOGL", "Alphabet",   "capex",   0.25),
    ("META",  "Meta",       "capex",   0.20),
    ("AMZN",  "Amazon",     "capex",   0.25),
]

NVDA_TICKER  = "NVDA"    # primary AI buildout proxy
TSMC_TICKER  = "TSM"     # semiconductor supply chain (NYSE-listed ADR)

# ── Composite weights ─────────────────────────────────────────────────────────
COMPOSITE_WEIGHTS = {
    "nvda_revenue":          0.35,
    "hyperscaler_capex":     0.35,
    "tsmc_revenue":          0.20,
    "price_momentum":        0.10,
}

# ── Scoring tables ────────────────────────────────────────────────────────────
def score_revenue_qoq(pct: float) -> int:
    """Map QoQ revenue growth % → 0-100 score."""
    if   pct >= 40:  return 92
    elif pct >= 25:  return 80
    elif pct >= 15:  return 68
    elif pct >= 5:   return 55
    elif pct >= 0:   return 42
    elif pct >= -10: return 28
    else:             return 15

def score_capex_qoq(pct: float) -> int:
    """Map QoQ CapEx growth % → 0-100 score."""
    if   pct >= 30:  return 90
    elif pct >= 20:  return 78
    elif pct >= 10:  return 65
    elif pct >= 0:   return 50
    elif pct >= -10: return 35
    else:             return 20

def score_price_momentum(pct_3m: float) -> int:
    """Map 3-month price return % → 0-100 score."""
    if   pct_3m >= 40:  return 88
    elif pct_3m >= 20:  return 75
    elif pct_3m >= 10:  return 62
    elif pct_3m >= 0:   return 50
    elif pct_3m >= -15: return 35
    else:                return 20

def composite_to_signal(score: float) -> str:
    if   score >= 70:  return "STRONG_CAPEX_CYCLE"
    elif score >= 55:  return "MODERATE"
    elif score >= 40:  return "WEAKENING"
    else:              return "INSUFFICIENT_DATA"

# ── yfinance helpers ──────────────────────────────────────────────────────────
def _safe_import_yfinance():
    try:
        import yfinance as yf
        return yf
    except ImportError:
        return None

def _get_quarterly_revenue(tk, n_quarters: int = 5) -> list[dict]:
    """
    Return list of {quarter, revenue_bn, qoq_pct} dicts, most-recent first.
    Uses annual income_stmt as fallback if quarterly unavailable.
    """
    records = []
    try:
        df = getattr(tk, "quarterly_income_stmt", None)
        if df is None or df.empty:
            df = getattr(tk, "quarterly_financials", None)
        if df is None or df.empty:
            return records

        rev_row = None
        for candidate in ["Total Revenue", "TotalRevenue", "Revenue"]:
            if candidate in df.index:
                rev_row = df.loc[candidate]
                break
        if rev_row is None:
            return records

        cols = [c for c in rev_row.index if rev_row[c] is not None][:n_quarters]
        values = [float(rev_row[c]) for c in cols if rev_row[c] is not None]

        for i, (col, val) in enumerate(zip(cols, values)):
            qoq = None
            if i + 1 < len(values) and values[i + 1] > 0:
                qoq = round((val / values[i + 1] - 1) * 100, 1)
            records.append({
                "quarter":     str(col)[:10],
                "revenue_bn":  round(val / 1e9, 2),
                "qoq_pct":     qoq,
            })
    except Exception as e:
        print(f"    [revenue] error: {e}")
    return records


def _get_quarterly_capex(tk, n_quarters: int = 5) -> list[dict]:
    """
    Return list of {quarter, capex_bn, qoq_pct} dicts, most-recent first.
    CapEx is negative in cash flow statements → take abs().
    """
    records = []
    try:
        df = getattr(tk, "quarterly_cashflow", None)
        if df is None or df.empty:
            return records

        capex_row = None
        for candidate in ["Capital Expenditure", "CapitalExpenditure",
                           "Purchase Of Plant, Property, Equipment And Intangible Assets",
                           "Purchases of property and equipment"]:
            if candidate in df.index:
                capex_row = df.loc[candidate]
                break
        if capex_row is None:
            return records

        cols   = [c for c in capex_row.index if capex_row[c] is not None][:n_quarters]
        values = [abs(float(capex_row[c])) for c in cols if capex_row[c] is not None]

        for i, (col, val) in enumerate(zip(cols, values)):
            qoq = None
            if i + 1 < len(values) and values[i + 1] > 0:
                qoq = round((val / values[i + 1] - 1) * 100, 1)
            records.append({
                "quarter":  str(col)[:10],
                "capex_bn": round(val / 1e9, 2),
                "qoq_pct":  qoq,
            })
    except Exception as e:
        print(f"    [capex] error: {e}")
    return records


def _get_price_momentum(tk) -> dict:
    """Return current price + 3-month return."""
    try:
        hist = tk.history(period="4mo", interval="1d")
        if hist.empty:
            return {}
        latest = float(hist["Close"].iloc[-1])
        ago_3m = float(hist["Close"].iloc[0]) if len(hist) > 60 else None
        pct_3m = round((latest / ago_3m - 1) * 100, 1) if ago_3m else None
        return {"price": round(latest, 2), "return_3m_pct": pct_3m}
    except Exception as e:
        print(f"    [price] error: {e}")
        return {}


# ── Main data fetch ───────────────────────────────────────────────────────────

def fetch_nvda(yf) -> dict:
    print(f"  Fetching NVDA...")
    tk = yf.Ticker(NVDA_TICKER)
    rev = _get_quarterly_revenue(tk)
    px  = _get_price_momentum(tk)

    latest_qoq = rev[0]["qoq_pct"] if rev and rev[0]["qoq_pct"] is not None else None
    score = score_revenue_qoq(latest_qoq) if latest_qoq is not None else 50

    return {
        "ticker":       NVDA_TICKER,
        "name":         "NVIDIA",
        "role":         "AI compute buildout proxy (~85% data center revenue)",
        "quarters":     rev[:4],
        "price":        px,
        "latest_qoq":   latest_qoq,
        "score":        score,
        "signal":       "ACCELERATING" if (latest_qoq or 0) > 20
                        else "STABLE" if (latest_qoq or 0) > 0
                        else "DECELERATING",
    }


def fetch_hyperscaler_capex(yf) -> dict:
    print("  Fetching hyperscaler CapEx...")
    components = {}
    total_latest = 0
    total_prior  = 0
    all_scores   = []

    for ticker, name, _, weight in HYPERSCALERS:
        try:
            tk   = yf.Ticker(ticker)
            cx   = _get_quarterly_capex(tk, n_quarters=5)
            px   = _get_price_momentum(tk)
            qoq  = cx[0]["qoq_pct"] if cx and cx[0]["qoq_pct"] is not None else None
            sc   = score_capex_qoq(qoq) if qoq is not None else 50
            all_scores.append(sc * weight / sum(w for _, _, _, w in HYPERSCALERS))

            if cx:
                total_latest += cx[0]["capex_bn"] if cx[0]["capex_bn"] else 0
                total_prior  += cx[1]["capex_bn"] if len(cx) > 1 and cx[1]["capex_bn"] else 0

            components[ticker] = {
                "name":         name,
                "quarters":     cx[:4],
                "price":        px,
                "latest_qoq":   qoq,
                "score":        sc,
                "weight":       weight,
            }
            print(f"    {ticker}: CapEx QoQ={qoq}%  score={sc}")
        except Exception as e:
            print(f"    {ticker}: error — {e}")
            components[ticker] = {"name": name, "error": str(e), "score": 50, "weight": weight}
            all_scores.append(50 * weight / sum(w for _, _, _, w in HYPERSCALERS))

    combined_qoq = round((total_latest / total_prior - 1) * 100, 1) if total_prior > 0 else None
    composite_score = round(sum(all_scores) * sum(w for _, _, _, w in HYPERSCALERS), 0)

    return {
        "combined_capex_latest_bn": round(total_latest, 1),
        "combined_capex_qoq_pct":   combined_qoq,
        "score":                    int(composite_score),
        "components":               components,
        "signal":                   "EXPANDING"    if (combined_qoq or 0) > 15
                                    else "STABLE"  if (combined_qoq or 0) > 0
                                    else "CONTRACTING",
    }


def fetch_tsmc(yf) -> dict:
    print(f"  Fetching TSMC (TSM)...")
    tk  = yf.Ticker(TSMC_TICKER)
    rev = _get_quarterly_revenue(tk)
    px  = _get_price_momentum(tk)

    latest_qoq = rev[0]["qoq_pct"] if rev and rev[0]["qoq_pct"] is not None else None
    score = score_revenue_qoq(latest_qoq) if latest_qoq is not None else 50

    return {
        "ticker":       TSMC_TICKER,
        "name":         "TSMC",
        "role":         "Semiconductor supply chain health; HPC/AI chip fab proxy",
        "quarters":     rev[:4],
        "price":        px,
        "latest_qoq":   latest_qoq,
        "score":        score,
        "signal":       "STRONG"   if (latest_qoq or 0) > 15
                        else "MODERATE" if (latest_qoq or 0) > 0
                        else "WEAK",
    }


def fetch_price_momentum_basket(yf) -> dict:
    """3-month price return for hyperscaler basket as real-time capex sentiment proxy."""
    print("  Computing hyperscaler price momentum basket...")
    returns = []
    for ticker, name, _, weight in HYPERSCALERS:
        try:
            tk  = yf.Ticker(ticker)
            px  = _get_price_momentum(tk)
            r3m = px.get("return_3m_pct")
            if r3m is not None:
                returns.append((r3m, weight))
        except Exception:
            pass

    if not returns:
        return {"basket_return_3m_pct": None, "score": 50}

    total_weight  = sum(w for _, w in returns)
    weighted_avg  = sum(r * w for r, w in returns) / total_weight if total_weight else 0
    score = score_price_momentum(weighted_avg)

    return {
        "basket_return_3m_pct": round(weighted_avg, 1),
        "score":                score,
        "signal":               "BULLISH" if weighted_avg > 10
                                else "NEUTRAL" if weighted_avg > -5
                                else "BEARISH",
    }


# ── Implications per watchlist stock ─────────────────────────────────────────

def compute_implications(composite_score: float, composite_signal: str) -> dict:
    """
    Map composite leading indicator signal to per-stock implications.
    Based on watchlist.json macro_sensitivity + industry positioning.
    """
    implications = {
        "300308.SZ": {
            "relevance":  "DIRECT",
            "rationale":  "1.6T optical transceiver demand directly driven by hyperscaler CapEx cycle",
            "direction":  "positive" if composite_score >= 55 else "negative",
            "strength":   "HIGH"     if composite_score >= 70
                          else "MED" if composite_score >= 55
                          else "LOW",
            "lag_months": "1-3",
        },
        "700.HK": {
            "relevance":  "INDIRECT",
            "rationale":  "AI monetisation tailwind; benefits from cloud infrastructure growth",
            "direction":  "positive" if composite_score >= 55 else "neutral",
            "strength":   "LOW",
            "lag_months": "3-6",
        },
        "9999.HK": {
            "relevance":  "INDIRECT",
            "rationale":  "AI features in games/apps; limited direct exposure to capex cycle",
            "direction":  "neutral",
            "strength":   "LOW",
            "lag_months": "6-12",
        },
        "6160.HK": {
            "relevance":  "NONE",
            "rationale":  "Biotech; not driven by AI infrastructure cycle",
            "direction":  "neutral",
            "strength":   "NONE",
            "lag_months": None,
        },
        "002594.SZ": {
            "relevance":  "NONE",
            "rationale":  "EV/automotive; not driven by AI infrastructure cycle",
            "direction":  "neutral",
            "strength":   "NONE",
            "lag_months": None,
        },
    }
    return implications


# ── Manual entries ────────────────────────────────────────────────────────────

def load_manual_entries() -> list:
    """
    Load manually-entered leading indicator events from watchlist.json
    (future: add a 'manual_leading_events' block to watchlist.json).
    Returns empty list until manual entries are added.
    """
    wl_path = DATA_DIR / "watchlist.json"
    try:
        wl = json.loads(wl_path.read_text(encoding="utf-8"))
        return wl.get("manual_leading_events", [])
    except Exception:
        return []


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("[leading_indicators] Fetching AI infrastructure leading indicators...")

    yf = _safe_import_yfinance()
    if yf is None:
        print("  [ERROR] yfinance not available. Writing stub output.")
        stub = {
            "generated_at":      datetime.now(timezone.utc).isoformat(),
            "industry":          "ai_infrastructure",
            "composite_score":   None,
            "composite_signal":  "INSUFFICIENT_DATA",
            "error":             "yfinance not installed",
        }
        with open(DATA_DIR / "leading_indicators.json", "w", encoding="utf-8") as f:
            json.dump(stub, f, ensure_ascii=False, indent=2)
        return

    # ── Fetch all indicators ──────────────────────────────────────────────────
    nvda       = fetch_nvda(yf)
    capex_idx  = fetch_hyperscaler_capex(yf)
    tsmc       = fetch_tsmc(yf)
    momentum   = fetch_price_momentum_basket(yf)
    manual     = load_manual_entries()

    # ── Compute composite score ───────────────────────────────────────────────
    scores = {
        "nvda_revenue":      nvda.get("score",  50),
        "hyperscaler_capex": capex_idx.get("score", 50),
        "tsmc_revenue":      tsmc.get("score",  50),
        "price_momentum":    momentum.get("score", 50),
    }
    composite = sum(scores[k] * COMPOSITE_WEIGHTS[k] for k in COMPOSITE_WEIGHTS)
    composite = round(composite, 1)
    signal    = composite_to_signal(composite)

    print(f"\n[leading_indicators] Composite: {composite:.1f} → {signal}")
    for k, v in scores.items():
        print(f"  {k:30s} score={v}  weight={COMPOSITE_WEIGHTS[k]:.0%}")

    # ── Build output ──────────────────────────────────────────────────────────
    implications = compute_implications(composite, signal)

    output = {
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "industry":          "ai_infrastructure",
        "composite_score":   composite,
        "composite_signal":  signal,
        "interpretation": {
            "STRONG_CAPEX_CYCLE":  "Hyperscalers aggressively expanding AI infrastructure. "
                                   "Order visibility for 300308-type names is 1-2Q ahead.",
            "MODERATE":            "Capex cycle healthy but not accelerating. "
                                   "Existing thesis intact; no incremental urgency.",
            "WEAKENING":           "CapEx growth decelerating. Monitor for order pushouts. "
                                   "Review thesis validity for 300308.",
            "INSUFFICIENT_DATA":   "Data unavailable. Manual check required.",
        }.get(signal, ""),
        "component_scores": scores,
        "indicators": {
            "nvda_revenue":      nvda,
            "hyperscaler_capex": capex_idx,
            "tsmc_revenue":      tsmc,
            "price_momentum":    momentum,
        },
        "stock_implications": implications,
        "manual_entries":     manual,
        "next_update_note":   "Quarterly data updates on NVDA/MSFT/GOOGL/META/AMZN earnings. "
                              "Price momentum updates daily.",
    }

    out_path = DATA_DIR / "leading_indicators.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"[leading_indicators] Done → {out_path}")


if __name__ == "__main__":
    main()
