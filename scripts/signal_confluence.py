#!/usr/bin/env python3
"""
scripts/signal_confluence.py — Layer 2: Multi-Signal Confidence Scorer

Reads:   public/data/signals_*.json       (from swing_signals.py)
         public/data/regime_config.json   (macro/sector regime)
         public/data/vp_snapshot.json     (VP scores, if available)

Writes:  public/data/confluence.json      (per-ticker confluence scores + rationale)

Architecture role:
  Layer 3 (Strategic) → determines approved universe (which tickers to consider)
  Layer 2 (Tactical)  → THIS SCRIPT: signal confluence → confidence score
  Layer 1 (Execution) → daily_decision.py reads confluence.json to generate trade actions

Design principles:
  1. Signal independence: correlated signals (e.g. GOLDEN_CROSS + BULLISH_ALIGNMENT)
     don't double-count. Each independence group contributes at most 1 full weight signal
     in each direction, subsequent same-direction signals discounted to 40%.
  2. Time decay: signals generated more than N days ago lose weight (per-signal TTL).
  3. Regime gating: RESTRICTIVE regime applies a 0.5× damping multiplier to bullish signals.
  4. Score range: -100 (maximum bearish) to +100 (maximum bullish).
  5. All logic is deterministic — no AI calls. Zero API cost.

Score interpretation:
  +60 to +100  → ENTRY_CANDIDATE   (strong bullish confluence)
  +20 to  +59  → HOLD / ACCUMULATE (moderate bullish)
  -19 to  +19  → NEUTRAL           (wait for clearer signal)
  -59 to  -20  → CAUTION           (moderate bearish, reduce exposure)
  -100 to  -60 → EXIT_SIGNAL       (strong bearish confluence)
"""

import json
import os
import glob
from datetime import datetime, timezone, date
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "public" / "data"


# ── Signal weight matrix ──────────────────────────────────────────────────────
# Weight > 0 = bullish contribution
# Weight < 0 = bearish contribution
# TTL = days after which signal loses all weight (linear decay)
# group = independence group (within group, 2nd+ same-direction signal → 40% weight)

SIGNAL_CONFIG = {
    # ── Trend signals (Group: primary_trend) ──────────────────────────────────
    "GOLDEN_CROSS":         {"weight":  18, "ttl": 15, "group": "primary_trend"},
    "DEATH_CROSS":          {"weight": -18, "ttl": 15, "group": "primary_trend"},
    "BULLISH_ALIGNMENT":    {"weight":  10, "ttl": 10, "group": "primary_trend"},  # MA5>MA20>MA60
    "MACD_GOLDEN_CROSS":    {"weight":  12, "ttl": 10, "group": "primary_trend"},
    "MACD_DEATH_CROSS":     {"weight": -12, "ttl": 10, "group": "primary_trend"},

    # ── Price structure (Group: price_structure) ───────────────────────────────
    "MA20_BOUNCE":          {"weight":  12, "ttl":  5, "group": "price_structure"},
    "MA60_BOUNCE":          {"weight":  16, "ttl":  7, "group": "price_structure"},  # Major support
    "BB_LOWER_BREAK":       {"weight":   8, "ttl":  4, "group": "price_structure"},  # Mean-reversion watch
    "BB_UPPER_BREAK":       {"weight":  -5, "ttl":  3, "group": "price_structure"},  # Extension risk
    "BB_SQUEEZE":           {"weight":   3, "ttl":  5, "group": "volatility"},       # Neutral: breakout imminent

    # ── Momentum oscillators (Group: momentum) ─────────────────────────────────
    # RSI and KDJ measure similar things → independence group discounts 2nd signal
    "RSI_OVERSOLD":         {"weight":  14, "ttl":  5, "group": "momentum"},
    "RSI_OVERBOUGHT":       {"weight": -14, "ttl":  5, "group": "momentum"},
    "RSI_RECOVERING":       {"weight":   7, "ttl":  4, "group": "momentum"},
    "KDJ_GOLDEN_CROSS":     {"weight":  10, "ttl":  4, "group": "momentum"},
    "KDJ_DEATH_CROSS":      {"weight": -10, "ttl":  4, "group": "momentum"},
    "KDJ_OVERSOLD":         {"weight":  12, "ttl":  3, "group": "momentum"},   # J < 0: extreme
    "KDJ_OVERBOUGHT":       {"weight": -12, "ttl":  3, "group": "momentum"},   # J > 100: extreme

    # ── Volume / capital flow (Group: volume_flow) — most independent ──────────
    "VOLUME_BREAKOUT":      {"weight":  18, "ttl":  3, "group": "volume_flow"},
    "VOLUME_SELLOFF":       {"weight": -18, "ttl":  3, "group": "volume_flow"},
    "CONTROLLED_ADVANCE":   {"weight":  10, "ttl":  3, "group": "volume_flow"},  # Low vol +1.5%: MM accumulation
    "CVD_FLOOR_FORMED":     {"weight":  20, "ttl":  5, "group": "cvd"},          # Highest weight: flow confirmed
    "CVD_BEARISH_DIVERGENCE": {"weight": -20, "ttl": 3, "group": "cvd"},         # Price up but flow negative

    # ── Fundamental quality / VP Score (Group: vp_quality) ───────────────────
    # VP is synthesized from vp_snapshot.json — NOT from swing_signals.py.
    # TTL=30 reflects fundamental quality changes slowly (quarterly earnings cadence).
    # Only one VP signal is injected per ticker, so independence discount never fires.
    # Score thresholds:
    #   VP ≥ 75  → STRONG_CONVICTION  (+28)  undervalued + fundamental acceleration
    #   VP 60-74 → GOOD_CONVICTION    (+14)  above-average fundamental profile
    #   VP 40-59 → no signal injected  (0)   neutral band — don't force a view
    #   VP 30-39 → WEAK_CONVICTION    (-14)  below-average, caution warranted
    #   VP < 30  → POOR_CONVICTION    (-28)  poor fundamentals + overvaluation risk
    "VP_STRONG_CONVICTION": {"weight":  28, "ttl": 30, "group": "vp_quality"},
    "VP_GOOD_CONVICTION":   {"weight":  14, "ttl": 30, "group": "vp_quality"},
    "VP_WEAK_CONVICTION":   {"weight": -14, "ttl": 30, "group": "vp_quality"},
    "VP_POOR_CONVICTION":   {"weight": -28, "ttl": 30, "group": "vp_quality"},

    # ── Industry Leading Indicators (Group: leading_indicator) ────────────────
    # Derived from leading_indicators.json (NVDA revenue + hyperscaler CapEx + TSMC).
    # TTL=90 days: quarterly earnings cycle — data stays valid until next quarter.
    # Only injected for tickers with DIRECT relevance in stock_implications.
    # MODERATE signal → no injection (neutral band, same logic as VP 40-59).
    "AI_CAPEX_STRONG_CYCLE": {"weight":  20, "ttl": 90, "group": "leading_indicator"},
    "AI_CAPEX_WEAKENING":    {"weight": -15, "ttl": 90, "group": "leading_indicator"},
}

# ── Independence discount ─────────────────────────────────────────────────────
# Within same group AND same direction, 2nd+ signals receive this multiplier
INDEPENDENCE_DISCOUNT = 0.40

# ── Regime multipliers ────────────────────────────────────────────────────────
REGIME_BULLISH_MULTIPLIER = {
    "PERMISSIVE":  1.20,   # Policy tailwind — amplify bullish signals
    "NEUTRAL":     1.00,   # No adjustment
    "RESTRICTIVE": 0.50,   # Policy headwind — dampen bullish signals
}
REGIME_BEARISH_MULTIPLIER = {
    "PERMISSIVE":  0.80,   # Policy tailwind — dampen bearish signals
    "NEUTRAL":     1.00,
    "RESTRICTIVE": 1.30,   # Policy headwind — amplify bearish signals
}

# ── Score thresholds ──────────────────────────────────────────────────────────
def score_to_action(score):
    if score >= 60:  return "ENTRY_CANDIDATE"
    if score >= 20:  return "HOLD"
    if score > -20:  return "NEUTRAL"
    if score > -60:  return "CAUTION"
    return "EXIT_SIGNAL"

def score_to_label_zh(score):
    if score >= 60:  return "强烈多头信号"
    if score >= 20:  return "温和多头，持有"
    if score > -20:  return "信号中性，等待"
    if score > -60:  return "温和空头，注意"
    return "强烈空头信号"


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def days_since(date_str):
    """Return number of days between date_str (ISO) and today. 0 if today or future."""
    try:
        d = datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
    except Exception:
        try:
            d = date.fromisoformat(date_str[:10])
        except Exception:
            return 0
    return max(0, (date.today() - d).days)


def time_decay_factor(signal_age_days, ttl):
    """Linear decay: 1.0 at age=0, 0.0 at age>=ttl."""
    if ttl <= 0:
        return 1.0
    return max(0.0, 1.0 - signal_age_days / ttl)


# ── Regime loader ─────────────────────────────────────────────────────────────

def get_ticker_regime(ticker, regime_data):
    """
    Find the regime for a given ticker from regime_config.json.
    Returns 'NEUTRAL' if not found.
    """
    sectors = regime_data.get("sectors", [])
    for sector in sectors:
        if ticker in sector.get("tickers", []):
            return sector.get("regime", "NEUTRAL")
    return "NEUTRAL"


# ── VP Score loader ───────────────────────────────────────────────────────────

def get_vp_score(ticker, vp_data):
    """
    Read VP score from vp_snapshot.json.
    Supports two formats:
      Format A (Supabase sync): { "snapshots": [{ "ticker": "300308.SZ", "vp_score": 79 }, ...] }
      Format B (flat):          { "300308.SZ": 79 }  or  { "300308.SZ": { "vp": 79 } }
    Returns float or None.
    """
    if not vp_data:
        return None
    # Format A: snapshots array (current format from supabase_sync.py)
    snapshots = vp_data.get("snapshots")
    if isinstance(snapshots, list):
        for snap in snapshots:
            if snap.get("ticker") == ticker:
                score = snap.get("vp_score") or snap.get("vp") or snap.get("total")
                return float(score) if score is not None else None
    # Format B: flat dict
    val = vp_data.get(ticker)
    if val is None:
        return None
    if isinstance(val, dict):
        score = val.get("vp_score") or val.get("vp") or val.get("total")
        return float(score) if score is not None else None
    if isinstance(val, (int, float)):
        return float(val)
    return None


# ── Leading indicator loader ──────────────────────────────────────────────────

def get_leading_indicator_signal(ticker: str, li_data: dict) -> str | None:
    """
    Return the AI capex signal type to inject for this ticker, or None.

    Rules:
      - Only injects for tickers with 'DIRECT' relevance in stock_implications
      - STRONG_CAPEX_CYCLE → AI_CAPEX_STRONG_CYCLE (+20)
      - MODERATE            → None (neutral band, no injection)
      - WEAKENING           → AI_CAPEX_WEAKENING (-15)
      - INSUFFICIENT_DATA   → None
    """
    if not li_data:
        return None
    impl = li_data.get("stock_implications", {}).get(ticker, {})
    if impl.get("relevance") != "DIRECT":
        return None   # only inject for directly affected tickers
    composite = li_data.get("composite_signal", "")
    if composite == "STRONG_CAPEX_CYCLE":
        return "AI_CAPEX_STRONG_CYCLE"
    if composite == "WEAKENING":
        return "AI_CAPEX_WEAKENING"
    return None   # MODERATE or INSUFFICIENT_DATA → neutral, no injection


# ── Core scoring function ─────────────────────────────────────────────────────

def compute_confluence(ticker, signals_data, regime, vp_score, li_data=None):
    """
    Compute the confluence score for a single ticker.

    Returns dict with:
      score          : int -100 to +100
      action         : str  (ENTRY_CANDIDATE / HOLD / NEUTRAL / CAUTION / EXIT_SIGNAL)
      contributing   : list of signal contributions (for transparency)
      rationale_e    : str English plain-language explanation
      rationale_z    : str Chinese plain-language explanation
      signal_types   : list of raw signal type strings
      regime_applied : str regime that was applied
      vp_score       : float or None
    """
    signals_raw = list(signals_data.get("signals", []))
    generated   = signals_data.get("generated_at", date.today().isoformat())
    zone        = signals_data.get("zone", "NEUTRAL")
    indicators  = signals_data.get("indicators", {})

    # ── Synthesize VP signal (fundamental quality group) ──────────────────────
    # VP is a continuous 0-100 score; we map it to a categorical signal that
    # participates in the same independence/decay/regime framework as all other
    # signals.  Using today as the signal date so TTL=30 doesn't decay it.
    vp_synthetic_type = None
    if vp_score is not None:
        if   vp_score >= 75:  vp_synthetic_type = "VP_STRONG_CONVICTION"
        elif vp_score >= 60:  vp_synthetic_type = "VP_GOOD_CONVICTION"
        elif vp_score < 30:   vp_synthetic_type = "VP_POOR_CONVICTION"
        elif vp_score < 40:   vp_synthetic_type = "VP_WEAK_CONVICTION"
        # 40-59 neutral band: no signal injected

    if vp_synthetic_type:
        signals_raw.append({
            "type":    vp_synthetic_type,
            "bullish": vp_synthetic_type in ("VP_STRONG_CONVICTION", "VP_GOOD_CONVICTION"),
            "date":    str(date.today()),
            "_synthetic": True,
        })

    # ── Synthesize AI CapEx leading indicator signal ──────────────────────────
    # Only fires for tickers with DIRECT upstream exposure to AI capex cycle.
    # Current DIRECT: 300308.SZ (1.6T optical transceivers).
    # TTL=90d because it's quarterly data; date = today so decay starts fresh.
    li_signal_type = get_leading_indicator_signal(ticker, li_data or {})
    if li_signal_type:
        signals_raw.append({
            "type":    li_signal_type,
            "bullish": li_signal_type == "AI_CAPEX_STRONG_CYCLE",
            "date":    str(date.today()),
            "_synthetic": True,
            "_source":  "leading_indicators",
        })

    signals = signals_raw

    # Age of signal file (days since generated_at)
    file_age = days_since(str(generated)[:10])

    # If signal file is >3 days old, apply global staleness discount
    staleness_factor = 1.0 if file_age <= 1 else (0.7 if file_age <= 3 else 0.4)

    # Regime multipliers for this ticker
    bull_mult = REGIME_BULLISH_MULTIPLIER.get(regime, 1.0)
    bear_mult = REGIME_BEARISH_MULTIPLIER.get(regime, 1.0)

    # Track per-group, per-direction usage (for independence discount)
    # { (group, direction): count_used }
    group_usage = {}

    contributions = []
    raw_score = 0.0

    for sig in signals:
        sig_type = sig.get("type", "")
        bullish  = sig.get("bullish", True)
        sig_date = sig.get("date", str(generated)[:10])

        cfg = SIGNAL_CONFIG.get(sig_type)
        if cfg is None:
            continue  # unknown signal type, skip

        base_weight = cfg["weight"]
        ttl         = cfg["ttl"]
        group       = cfg["group"]

        # Direction label for independence check
        direction = "bull" if base_weight > 0 else "bear"
        group_key = (group, direction)

        # Time decay (use signal's own date if available, else file date)
        age = days_since(sig_date)
        decay = time_decay_factor(age, ttl)

        # Independence discount
        usage_count = group_usage.get(group_key, 0)
        independence_factor = 1.0 if usage_count == 0 else INDEPENDENCE_DISCOUNT
        group_usage[group_key] = usage_count + 1

        # Regime multiplier
        regime_mult = bull_mult if base_weight > 0 else bear_mult

        # Final contribution
        contribution = (base_weight * decay * independence_factor
                        * regime_mult * staleness_factor)
        raw_score += contribution

        contributions.append({
            "type":                sig_type,
            "base_weight":         base_weight,
            "decay":               round(decay, 2),
            "independence_factor": round(independence_factor, 2),
            "regime_mult":         round(regime_mult, 2),
            "staleness":           round(staleness_factor, 2),
            "final_contribution":  round(contribution, 1),
        })

    # Clamp to [-100, +100]
    # VP is now a full participant in raw_score via the synthetic VP signal above —
    # no separate vp_adj needed.
    score = max(-100, min(100, int(round(raw_score))))
    action = score_to_action(score)

    # ── Rationale generation ──────────────────────────────────────────────────
    positive = [c for c in contributions if c["final_contribution"] > 0]
    negative = [c for c in contributions if c["final_contribution"] < 0]
    positive.sort(key=lambda x: -x["final_contribution"])
    negative.sort(key=lambda x: x["final_contribution"])

    rsi_val    = indicators.get("rsi14")
    pma20_val  = indicators.get("price_vs_ma20")
    cvd_slope  = indicators.get("cvd_slope_5d")

    def fmt_signal(s):
        return s["type"].replace("_", " ").title()

    # English rationale
    parts_e = []
    if positive:
        top_bull = ", ".join(fmt_signal(s) for s in positive[:2])
        parts_e.append(f"Bullish: {top_bull}")
    if negative:
        top_bear = ", ".join(fmt_signal(s) for s in negative[:2])
        parts_e.append(f"Bearish: {top_bear}")
    if rsi_val is not None:
        parts_e.append(f"RSI {rsi_val:.0f}")
    if pma20_val is not None:
        parts_e.append(f"Price vs MA20 {pma20_val:+.1f}%")
    if cvd_slope is not None:
        cvd_dir = "↑" if cvd_slope > 0 else "↓"
        parts_e.append(f"CVD slope {cvd_dir}")
    if regime != "NEUTRAL":
        parts_e.append(f"Regime: {regime}")
    if vp_score is not None:
        parts_e.append(f"VP {int(vp_score)}")
    rationale_e = " | ".join(parts_e) if parts_e else "No active signals"

    # Chinese rationale
    parts_z = []
    SIGNAL_ZH = {
        "GOLDEN_CROSS": "黄金交叉", "DEATH_CROSS": "死亡交叉",
        "BULLISH_ALIGNMENT": "均线多头排列", "MACD_GOLDEN_CROSS": "MACD金叉",
        "MACD_DEATH_CROSS": "MACD死叉", "MA20_BOUNCE": "MA20支撑反弹",
        "MA60_BOUNCE": "MA60强支撑反弹", "RSI_OVERSOLD": "RSI超卖",
        "RSI_OVERBOUGHT": "RSI超买", "RSI_RECOVERING": "RSI回升",
        "KDJ_GOLDEN_CROSS": "KDJ金叉", "KDJ_DEATH_CROSS": "KDJ死叉",
        "KDJ_OVERSOLD": "KDJ极度超卖(J<0)", "KDJ_OVERBOUGHT": "KDJ极度超买(J>100)",
        "VOLUME_BREAKOUT": "放量突破", "VOLUME_SELLOFF": "放量下跌",
        "CONTROLLED_ADVANCE": "缩量上涨(主力控盘)", "CVD_FLOOR_FORMED": "CVD底部形成(资金承接)",
        "CVD_BEARISH_DIVERGENCE": "CVD背离(价涨资金撤)",
        "BB_LOWER_BREAK": "布林下轨支撑", "BB_UPPER_BREAK": "布林上轨压力",
        "BB_SQUEEZE": "布林收口(蓄势)",
        "VP_STRONG_CONVICTION": "VP强烈信念(基本面加速+低估值)",
        "VP_GOOD_CONVICTION":   "VP良好信念(基本面偏强)",
        "VP_WEAK_CONVICTION":   "VP偏弱(基本面中性偏差)",
        "VP_POOR_CONVICTION":   "VP信念差(基本面恶化或高估)",
        "AI_CAPEX_STRONG_CYCLE":"AI资本开支强周期(NVDA+超大规模厂商CapEx加速)",
        "AI_CAPEX_WEAKENING":   "AI资本开支减速(超大规模厂商CapEx放缓)",
    }
    if positive:
        top_bull_z = "、".join(SIGNAL_ZH.get(s["type"], s["type"]) for s in positive[:2])
        parts_z.append(f"多头：{top_bull_z}")
    if negative:
        top_bear_z = "、".join(SIGNAL_ZH.get(s["type"], s["type"]) for s in negative[:2])
        parts_z.append(f"空头：{top_bear_z}")
    if rsi_val is not None:
        parts_z.append(f"RSI {rsi_val:.0f}")
    if pma20_val is not None:
        parts_z.append(f"距MA20 {pma20_val:+.1f}%")
    if cvd_slope is not None:
        cvd_dir = "向上" if cvd_slope > 0 else "向下"
        parts_z.append(f"CVD斜率{cvd_dir}")
    REGIME_ZH = {"PERMISSIVE": "政策顺风", "NEUTRAL": "政策中性", "RESTRICTIVE": "政策逆风"}
    if regime != "NEUTRAL":
        parts_z.append(REGIME_ZH.get(regime, regime))
    if vp_score is not None:
        parts_z.append(f"VP {int(vp_score)}")
    rationale_z = " | ".join(parts_z) if parts_z else "暂无有效信号"

    # Simplified signal list for position_sizing.py consumption
    contributing_signals = [
        {"type": c["type"], "contribution": c["final_contribution"]}
        for c in sorted(contributions, key=lambda x: -abs(x["final_contribution"]))[:8]
    ]

    return {
        "ticker":               ticker,
        "score":                score,
        "action":               action,
        "action_zh":            score_to_label_zh(score),
        "zone":                 zone,
        "regime":               regime,
        "vp_score":             vp_score,
        "vp_signal_type":       vp_synthetic_type,   # which VP signal was injected
        "vp_adjustment":        None,                 # deprecated — VP now in signal pool
        "staleness_factor":     round(staleness_factor, 2),
        "signal_count":         {"bullish": len(positive), "bearish": len(negative)},
        "contributing":         contributions,           # full detail
        "contributing_signals": contributing_signals,    # compact alias for position_sizing.py
        "rationale_e":          rationale_e,
        "rationale_z":          rationale_z,
        "signal_types":         [s.get("type") for s in signals],
        "computed_at":          datetime.now(timezone.utc).isoformat(),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("[confluence] Starting signal confluence scoring...")

    # Load supporting data
    regime_data = load_json(DATA_DIR / "regime_config.json",      {"sectors": []})
    vp_data     = load_json(DATA_DIR / "vp_snapshot.json",        {})
    li_data     = load_json(DATA_DIR / "leading_indicators.json", {})

    if li_data.get("composite_signal"):
        print(f"[confluence] Leading indicator: {li_data['composite_signal']} "
              f"(score={li_data.get('composite_score')})")

    # Find all signal files
    signal_files = sorted(glob.glob(str(DATA_DIR / "signals_*.json")))
    if not signal_files:
        print("[confluence] No signal files found — exiting.")
        return

    results = []
    for fpath in signal_files:
        fname   = os.path.basename(fpath)
        # Derive ticker from filename: signals_300308_SZ.json → 300308.SZ
        stem    = fname.replace("signals_", "").replace(".json", "")  # 300308_SZ
        # Re-assemble ticker: last segment is exchange suffix
        parts   = stem.rsplit("_", 1)
        ticker  = f"{parts[0]}.{parts[1]}" if len(parts) == 2 else stem

        signals_data = load_json(fpath, {})
        if not signals_data:
            print(f"[confluence] Skipping {fname} — empty or unreadable")
            continue

        regime   = get_ticker_regime(ticker, regime_data)
        vp_score = get_vp_score(ticker, vp_data)

        result = compute_confluence(ticker, signals_data, regime, vp_score, li_data)
        results.append(result)

        direction = "▲" if result["score"] > 0 else ("▼" if result["score"] < 0 else "─")
        print(f"  {ticker:16s} score={result['score']:+4d}  action={result['action']:18s} "
              f"regime={regime:11s} {direction}  {result['rationale_e'][:60]}")

    # Sort by score descending (strongest buy candidates first)
    results.sort(key=lambda x: -x["score"])

    # Build summary
    entry_candidates = [r for r in results if r["action"] == "ENTRY_CANDIDATE"]
    exit_signals     = [r for r in results if r["action"] == "EXIT_SIGNAL"]
    caution          = [r for r in results if r["action"] == "CAUTION"]

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tickers_scored": len(results),
        "summary": {
            "entry_candidates": [r["ticker"] for r in entry_candidates],
            "exit_signals":     [r["ticker"] for r in exit_signals],
            "caution":          [r["ticker"] for r in caution],
        },
        "scores": results,
    }

    out_path = DATA_DIR / "confluence.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[confluence] Done. {len(results)} tickers scored → {out_path}")
    print(f"  Entry candidates: {[r['ticker'] for r in entry_candidates]}")
    print(f"  Exit signals:     {[r['ticker'] for r in exit_signals]}")
    print(f"  Caution:          {[r['ticker'] for r in caution]}")


if __name__ == "__main__":
    main()
