#!/usr/bin/env python3
"""
scripts/position_sizing.py — Layer 2: Position Sizing Engine

Computes volatility-adjusted, VP-conviction-weighted position size recommendations
for BUY_WATCH candidates. Output feeds directly into the Trading Desk UI.

Sizing methodology (Fixed-Fraction + ATR Stop):
  1. ATR stop distance  = 2 × ATR_14 (two-ATR trailing stop)
  2. Base risk per trade = RISK_PCT_PER_TRADE × portfolio_value
  3. Raw size in value   = base_risk / stop_distance_pct
  4. VP multiplier       = vp_score / VP_BASE   (VP=70 → 1.0×; VP=85 → 1.21×)
  5. Confluence mult.    = confluence_score / CONF_BASE  (capped 0.5×–1.3×)
  6. Final size % = raw_size_pct × vp_mult × conf_mult, clamped [MIN_PCT, MAX_PCT]

Reads:
  public/data/market_data.json   — ATR_14, current price
  public/data/vp_snapshot.json   — VP scores per ticker
  public/data/confluence.json    — Confluence scores per ticker
  public/data/daily_decision.json — BUY_WATCH candidates
  public/data/positions.json     — Portfolio value (or use default)

Writes:
  public/data/position_sizing.json
"""

import json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "public" / "data"

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_PORTFOLIO_CNY = 1_000_000   # fallback if no positions.json
RISK_PCT_PER_TRADE    = 0.020       # risk 2% of portfolio per trade
ATR_STOP_MULT         = 2.0         # stop placed at 2× ATR
VP_BASE               = 70          # VP=70 → 1.0× multiplier
CONF_BASE             = 70          # confluence 70 → 1.0×
MIN_POSITION_PCT      = 2.0         # never go below 2%
MAX_POSITION_PCT      = 25.0        # never exceed 25%
VP_MULT_FLOOR         = 0.50
VP_MULT_CAP           = 1.50
CONF_MULT_FLOOR       = 0.50
CONF_MULT_CAP         = 1.30

# ATR fallback if technical data missing (% of price as proxy)
DEFAULT_ATR_PCT       = 0.025       # assume 2.5% daily range


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def get_atr_pct(ticker, market_data):
    """Return ATR as % of current price. Falls back to DEFAULT_ATR_PCT."""
    yd = market_data.get("yahoo", {}).get(ticker, {})
    ta = yd.get("technical", {})
    price = yd.get("price", {}).get("last")
    atr   = ta.get("atr_14") or ta.get("atr")

    if price and atr and price > 0:
        return atr / price
    return DEFAULT_ATR_PCT


def get_vp(ticker, vp_data):
    for s in vp_data.get("snapshots", []):
        if s.get("ticker") == ticker:
            return s.get("vp_score") or s.get("vp")
    return None


def get_confluence_score(ticker, confluence_data):
    for s in confluence_data.get("scores", []):
        if s.get("ticker") == ticker:
            return s.get("score", 0), s.get("contributing_signals", [])
    return 0, []


def compute_size(ticker, vp_score, conf_score, atr_pct, portfolio_value):
    """
    Returns dict with sizing recommendation fields.
    """
    # Stop distance as fraction of price
    stop_dist_pct = ATR_STOP_MULT * atr_pct

    # Base risk amount
    risk_cny = portfolio_value * RISK_PCT_PER_TRADE

    # Raw position value = risk / stop_distance_pct
    raw_value   = risk_cny / stop_dist_pct if stop_dist_pct > 0 else 0
    raw_size_pct = (raw_value / portfolio_value * 100) if portfolio_value > 0 else 5.0

    # VP multiplier
    vp_mult = (vp_score / VP_BASE) if vp_score else 0.70
    vp_mult = max(VP_MULT_FLOOR, min(VP_MULT_CAP, vp_mult))

    # Confluence multiplier
    conf_mult = (conf_score / CONF_BASE) if conf_score else 0.70
    conf_mult = max(CONF_MULT_FLOOR, min(CONF_MULT_CAP, conf_mult))

    # Final sizing
    final_pct = raw_size_pct * vp_mult * conf_mult
    final_pct = max(MIN_POSITION_PCT, min(MAX_POSITION_PCT, final_pct))
    final_value = portfolio_value * final_pct / 100

    # Conviction tier
    if final_pct >= 15:
        tier, tier_zh = "HIGH CONVICTION", "高信念"
    elif final_pct >= 8:
        tier, tier_zh = "MEDIUM CONVICTION", "中信念"
    else:
        tier, tier_zh = "STARTER", "试探仓"

    return {
        "recommended_pct":    round(final_pct, 1),
        "recommended_value":  round(final_value, 0),
        "stop_distance_pct":  round(stop_dist_pct * 100, 2),  # as %
        "atr_pct":            round(atr_pct * 100, 2),
        "vp_multiplier":      round(vp_mult, 2),
        "conf_multiplier":    round(conf_mult, 2),
        "risk_cny":           round(risk_cny, 0),
        "conviction_tier":    tier,
        "conviction_tier_zh": tier_zh,
        "rationale_e": (
            f"{tier}: ATR-stop {stop_dist_pct*100:.1f}% · "
            f"VP-mult {vp_mult:.2f}× · conf-mult {conf_mult:.2f}× → "
            f"{final_pct:.1f}% of portfolio (¥{final_value:,.0f})"
        ),
        "rationale_z": (
            f"{tier_zh}：ATR止损{stop_dist_pct*100:.1f}% · "
            f"VP系数{vp_mult:.2f}× · 信号系数{conf_mult:.2f}× → "
            f"仓位{final_pct:.1f}%（¥{final_value:,.0f}）"
        ),
    }


def main():
    print("[position_sizing] Starting sizing engine...")

    market_data   = load_json(DATA_DIR / "market_data.json",    {})
    vp_data       = load_json(DATA_DIR / "vp_snapshot.json",    {"snapshots": []})
    conf_data     = load_json(DATA_DIR / "confluence.json",     {"scores": []})
    decision_data = load_json(DATA_DIR / "daily_decision.json", {"decisions": {}})
    positions_data= load_json(DATA_DIR / "positions.json",      {"summary": {}})

    # Derive portfolio value
    portfolio_value = (
        positions_data.get("summary", {}).get("total_value")
        or DEFAULT_PORTFOLIO_CNY
    )
    print(f"  Portfolio value: ¥{portfolio_value:,.0f}")

    # Collect all tickers with confluence scores
    all_scored = {s["ticker"]: s for s in conf_data.get("scores", [])}
    held_tickers = {
        p["ticker"]
        for p in positions_data.get("positions", [])
    }

    sizing = []
    for ticker, conf_entry in all_scored.items():
        vp_score  = get_vp(ticker, vp_data)
        conf_score, signals = get_confluence_score(ticker, conf_data)
        atr_pct   = get_atr_pct(ticker, market_data)
        is_held   = ticker in held_tickers

        rec = compute_size(ticker, vp_score, conf_score, atr_pct, portfolio_value)
        rec["ticker"]     = ticker
        rec["vp_score"]   = vp_score
        rec["conf_score"] = conf_score
        rec["is_held"]    = is_held
        rec["signals"]    = signals[:5]   # top 5 contributing signals
        sizing.append(rec)

        tier = rec["conviction_tier"]
        print(f"  {ticker:16s}  VP={vp_score}  conf={conf_score:+4d}  "
              f"ATR={atr_pct*100:.1f}%  → {rec['recommended_pct']:.1f}%  [{tier}]")

    output = {
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "date":           datetime.now().strftime("%Y-%m-%d"),
        "portfolio_value": round(portfolio_value, 0),
        "risk_pct_per_trade": RISK_PCT_PER_TRADE,
        "sizing":         sorted(sizing, key=lambda x: -x["recommended_pct"]),
    }

    out_path = DATA_DIR / "position_sizing.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[position_sizing] Done → {out_path}")
    print(f"  {len(sizing)} tickers sized  |  portfolio ¥{portfolio_value:,.0f}")


if __name__ == "__main__":
    main()
