#!/usr/bin/env python3
"""
scripts/daily_decision.py — Layer 2: Daily Trading Decision Engine

Reads:   public/data/confluence.json      (from signal_confluence.py)
         public/data/positions.json       (current paper trading positions)
         public/data/vp_snapshot.json     (VP scores)
         public/data/regime_config.json   (sector regimes)

Writes:  public/data/daily_decision.json  (actionable trade decisions)

Decision logic (combining PM fundamental layer + quant signal layer):

  FOR POSITIONS WE HOLD:
    - EXIT_SIGNAL score OR wrongIf breach → recommend EXIT
    - CAUTION score + large P&L → recommend TRIM (take partial profit)
    - HOLD score range → HOLD with monitoring notes
    - ENTRY_CANDIDATE score (confluence confirms thesis) → consider ADD

  FOR TICKERS IN APPROVED UNIVERSE (not held):
    - ENTRY_CANDIDATE score + VP >= threshold → BUY_WATCH (pending manual trigger)
    - Others → WATCH

  PORTFOLIO RISK FLAGS:
    - Single position > 40% → concentration warning
    - Single sector > 60% → sector concentration warning
    - Total held < 3 positions → under-diversified
    - P&L on any position > +25% → consider trimming (lock profit)
    - P&L on any position < -10% → review (approach stop loss territory)

Architecture:
  Layer 3 (Strategic/weekly)  → regime_config + VP scores define universe
  Layer 2 (Tactical/daily)    → THIS SCRIPT: confluence + positions → decisions
  Layer 1 (Execution/realtime)→ paper_trading.py executes + tracks

Design: zero AI calls. Pure rule-based logic. Fast, deterministic, free.
"""

import json
import os
import re
from datetime import datetime, timezone, date
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "public" / "data"

# ── Thresholds ────────────────────────────────────────────────────────────────
VP_MIN_FOR_ENTRY    = 60    # Minimum VP score to consider a new entry
SCORE_ENTRY_MIN     = 60    # Confluence score threshold for BUY signal
SCORE_CAUTION_MAX   = -20   # Below this → caution
SCORE_EXIT_MAX      = -60   # Below this → exit signal

PROFIT_TAKE_PCT     = 25.0  # Suggest trim when P&L > this

# ── Signal direction map (for trade_attribution_capsules.json) ────────────────
# Source of truth: bullish flag in scripts/swing_signals.py and scripts/signal_confluence.py.
# If a new signal type is added to either producer, add it here.
SIGNAL_DIRECTION = {
    # Swing signals (swing_signals.py)
    "BB_LOWER_BREAK":         "bullish",
    "BB_SQUEEZE":             "bullish",
    "BB_UPPER_BREAK":         "bullish",
    "BULLISH_ALIGNMENT":      "bullish",
    "CONTROLLED_ADVANCE":     "bullish",
    "CVD_BEARISH_DIVERGENCE": "bearish",
    "CVD_FLOOR_FORMED":       "bullish",
    "DEATH_CROSS":            "bearish",
    "GOLDEN_CROSS":           "bullish",
    "KDJ_DEATH_CROSS":        "bearish",
    "KDJ_GOLDEN_CROSS":       "bullish",
    "KDJ_OVERBOUGHT":         "bearish",
    "KDJ_OVERSOLD":           "bullish",
    "MA20_BOUNCE":            "bullish",
    "MA60_BOUNCE":            "bullish",
    "MACD_DEATH_CROSS":       "bearish",
    "MACD_GOLDEN_CROSS":      "bullish",
    "RSI_OVERBOUGHT":         "bearish",
    "RSI_OVERSOLD":           "bullish",
    "RSI_RECOVERING":         "bullish",
    "VOLUME_BREAKOUT":        "bullish",
    "VOLUME_SELLOFF":         "bearish",
    # VP-quality synthetic signals (signal_confluence.py)
    "VP_STRONG_CONVICTION":   "bullish",
    "VP_GOOD_CONVICTION":     "bullish",
    "VP_WEAK_CONVICTION":     "bearish",
    "VP_POOR_CONVICTION":     "bearish",
    # AI CapEx leading-indicator synthetic signals (signal_confluence.py)
    "AI_CAPEX_STRONG_CYCLE":  "bullish",
    "AI_CAPEX_WEAKENING":     "bearish",
}
STOP_REVIEW_PCT     = -10.0 # Suggest review when P&L < this (not hard stop — human decides)
CONCENTRATION_MAX   = 40.0  # Single position weight % warning threshold
SECTOR_MAX_PCT      = 60.0  # Single sector weight % warning threshold


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def get_confluence(ticker, confluence_data):
    """Return the confluence result for a ticker, or None."""
    for score in confluence_data.get("scores", []):
        if score.get("ticker") == ticker:
            return score
    return None


def get_vp(ticker, vp_data):
    snapshots = vp_data.get("snapshots", [])
    for s in snapshots:
        if s.get("ticker") == ticker:
            return s.get("vp_score") or s.get("vp")
    return None


def get_regime(ticker, regime_data):
    for sector in regime_data.get("sectors", []):
        if ticker in sector.get("tickers", []):
            return sector.get("regime", "NEUTRAL"), sector.get("name_en", "")
    return "NEUTRAL", ""


def get_wrongif(ticker, vp_data):
    """Return wrongIf strings for a ticker from vp_snapshot.json."""
    for s in vp_data.get("snapshots", []):
        if s.get("ticker") == ticker:
            return s.get("wrongIf_e", ""), s.get("wrongIf_z", "")
    return "", ""


# ── wrongIf monitor ───────────────────────────────────────────────────────────
# Lightweight pattern-matching against observable market indicators.
# Binary events (clinical trial data, regulatory announcements) are flagged as
# "manual check required" — we can't automate those.

_NUMERIC_PATTERNS = [
    # (regex, group_idx_for_threshold, indicator_key, direction)
    # direction: 'above' = alert if indicator > threshold
    #            'below' = alert if indicator < threshold
    (r"rsi\s+(?:above|over|>)\s*(\d+(?:\.\d+)?)",         1, "rsi_14",          "above"),
    (r"rsi\s+(?:below|under|<)\s*(\d+(?:\.\d+)?)",         1, "rsi_14",          "below"),
    (r"dau\s+(?:drops?\s+below|falls?\s+below|<)\s*(\d+(?:\.\d+)?[MmBb]?)",
                                                            1, "dau_proxy",       "below"),
    (r"mau\s+miss(?:es)?\s+(\d+(?:\.\d+)?[MmBb]?)",       1, "mau_proxy",       "below"),
    (r"(?:capex|capital expenditure)\s+cut\s*>?\s*(\d+)%", 1, "capex_cut",       "above"),
    (r"tariff[s]?\s+(?:above|over|>|exceed[s]?)\s*(\d+)%", 1, "tariff_pct",      "above"),
    (r"pe\s+(?:above|over|>)\s*(\d+)",                     1, "pe_forward",       "above"),
    (r"(?:price\s+)?(?:drops?\s+below|falls?\s+below)\s*(\d+(?:\.\d+)?)",
                                                            1, "price",           "below"),
    # Revenue / earnings decline proxies (observable from yfinance fundamentals)
    (r"revenue.{0,30}(?:miss|declin|contract|shrink|negativ|weaken)",
                                                            0, "revenue_growth",  "below_zero"),
    (r"(?:sales|revenue).{0,30}cut\s*>?\s*(\d+)%",        1, "revenue_growth",  "below"),
    (r"(?:earnings?|ni|net income|profit).{0,30}(?:miss|declin|fall|negativ)",
                                                            0, "earnings_growth", "below_zero"),
    (r"(?:macro\s+)?consumption\s+weakens",                0, "revenue_growth",  "below_zero"),
    # Tariff / trade impact proxy → revenue growth as downstream signal
    (r"tariff|local content|import duty|trade restriction", 0, "revenue_growth",  "below_zero"),
    # DAU/MAU miss proxy → earnings growth as downstream signal (gaming cos)
    (r"dau|mau|daily active|monthly active",               0, "earnings_growth", "below_zero"),
]

_BINARY_KEYWORDS = [
    "phase 3", "phase iii", "pivotal", "nda", "maa", "fda", "nmpa",
    "approval", "data readout", "topline", "interim analysis",
    "qualification", "slips", "misses", "disappoints", "superior pfs",
    "uMRD", "celest", "pirtobrutinib", "clinical",
]


def _parse_threshold(val_str):
    """Convert '2M', '200M', '1.5B', '35' to a float."""
    s = val_str.strip().upper()
    mult = 1
    if s.endswith('B'):
        mult = 1e9
        s = s[:-1]
    elif s.endswith('M'):
        mult = 1e6
        s = s[:-1]
    elif s.endswith('K'):
        mult = 1e3
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def check_wrongif(ticker, wrongif_text, market_data):
    """
    Lightweight check of wrongIf string against live data.
    Returns list of alert dicts:
      { status: 'TRIGGERED'|'CLEAR'|'MANUAL', indicator, threshold, actual, text }
    """
    if not wrongif_text:
        return []

    alerts = []
    text_lower = wrongif_text.lower()

    # Extract observable numeric indicators from market_data
    yd   = market_data.get("yahoo", {}).get(ticker, {})
    fund = yd.get("fundamentals", {})
    tech = yd.get("technical", {})
    px   = yd.get("price", {})

    # revenue_growth / earnings_growth: yfinance returns as decimal (0.14 = 14%)
    rev_g = fund.get("revenue_growth")
    ear_g = fund.get("earnings_growth")

    live = {
        "rsi_14":          tech.get("rsi_14"),
        "price":           px.get("last"),
        "pe_forward":      fund.get("pe_forward"),
        "revenue_growth":  rev_g * 100 if rev_g is not None else None,   # convert to %
        "earnings_growth": ear_g * 100 if ear_g is not None else None,
        # proxy indicators — require external data not in yfinance
        "dau_proxy":   None,
        "mau_proxy":   None,
        "capex_cut":   None,
        "tariff_pct":  None,
    }

    matched_any_numeric = False
    for pattern, grp, indicator, direction in _NUMERIC_PATTERNS:
        m = re.search(pattern, text_lower)
        if not m:
            continue

        # below_zero patterns use group 0 (whole match) — no numeric threshold needed
        if direction == "below_zero":
            threshold = 0
        else:
            threshold = _parse_threshold(m.group(grp))
            if threshold is None:
                continue

        actual = live.get(indicator)
        matched_any_numeric = True

        # below_zero: triggered if actual < 0 (no threshold needed)
        if direction == "below_zero":
            if actual is None:
                alerts.append({
                    "status": "MANUAL", "indicator": indicator,
                    "threshold": 0, "actual": None, "text": wrongif_text,
                    "note_e": f"Cannot auto-verify '{indicator}' — manual check required.",
                    "note_z": f"无法自动核验「{indicator}」——需人工检查。",
                })
            else:
                triggered = actual < 0
                sign = "▼" if triggered else "▲"
                alerts.append({
                    "status":    "TRIGGERED" if triggered else "CLEAR",
                    "indicator": indicator,
                    "threshold": 0,
                    "actual":    round(actual, 1),
                    "text":      wrongif_text,
                    "note_e":    f"{'⚠️ PROXY TRIGGERED' if triggered else '✅ Clear'}: "
                                 f"{indicator} = {actual:+.1f}% {sign}",
                    "note_z":    f"{'⚠️ 代理指标触发' if triggered else '✅ 正常'}: "
                                 f"{indicator} = {actual:+.1f}% {sign}",
                })
            continue

        if actual is None:
            alerts.append({
                "status":    "MANUAL",
                "indicator": indicator,
                "threshold": threshold,
                "actual":    None,
                "text":      wrongif_text,
                "note_e":    f"Cannot auto-verify '{indicator}' — manual check required.",
                "note_z":    f"无法自动核验「{indicator}」——需人工检查。",
            })
        else:
            triggered = (direction == "above" and actual > threshold) or \
                        (direction == "below" and actual < threshold)
            alerts.append({
                "status":    "TRIGGERED" if triggered else "CLEAR",
                "indicator": indicator,
                "threshold": threshold,
                "actual":    round(actual, 1),
                "text":      wrongif_text,
                "note_e":    (
                    f"⚠️ WRONGIF TRIGGERED: {indicator} = {actual:.1f} "
                    f"{'>' if direction=='above' else '<'} {threshold:.1f}"
                ) if triggered else (
                    f"✅ Clear: {indicator} = {actual:.1f} (threshold {threshold:.1f})"
                ),
                "note_z":    (
                    f"⚠️ wrongIf触发：{indicator} = {actual:.1f} "
                    f"{'>' if direction=='above' else '<'} {threshold:.1f}"
                ) if triggered else (
                    f"✅ 正常：{indicator} = {actual:.1f}（阈值{threshold:.1f}）"
                ),
            })

    # Binary event keywords — always flag as manual
    binary_matches = [kw for kw in _BINARY_KEYWORDS if kw in text_lower]
    if binary_matches and not matched_any_numeric:
        alerts.append({
            "status":    "MANUAL",
            "indicator": "binary_event",
            "threshold": None,
            "actual":    None,
            "text":      wrongif_text,
            "note_e":    f"Binary event condition — manual monitoring required: {wrongif_text[:80]}",
            "note_z":    f"二元事件条件——需人工监控：{wrongif_text[:80]}",
        })
    elif binary_matches:
        # Mixed: some numeric + binary
        alerts.append({
            "status":    "MANUAL",
            "indicator": "binary_event",
            "threshold": None,
            "actual":    None,
            "text":      wrongif_text,
            "note_e":    f"Binary component requires manual check: {', '.join(binary_matches[:3])}",
            "note_z":    f"含二元事件条件，需人工核查：{', '.join(binary_matches[:3])}",
        })

    if not alerts:
        alerts.append({
            "status":    "MANUAL",
            "indicator": "unstructured",
            "threshold": None,
            "actual":    None,
            "text":      wrongif_text,
            "note_e":    f"Unstructured condition — monitor manually: {wrongif_text[:80]}",
            "note_z":    f"非结构化条件——需人工监控：{wrongif_text[:80]}",
        })

    return alerts


def get_sizing(ticker, sizing_data):
    """Return sizing recommendation for a ticker, or None."""
    for s in sizing_data.get("sizing", []):
        if s.get("ticker") == ticker:
            return s
    return None


# ── Decision logic ────────────────────────────────────────────────────────────

def decide_held_position(pos, conf, vp_score):
    """
    Generate a decision for a ticker we currently hold.
    pos  : position dict from positions.json
    conf : confluence dict from confluence.json (may be None)
    """
    ticker   = pos["ticker"]
    pnl_pct  = pos.get("pnl_pct", 0.0)
    weight   = pos.get("weight_pct", 0.0)
    days     = pos.get("holding_days", 0)
    name     = pos.get("name", ticker)

    score    = conf["score"]    if conf else 0
    action_q = conf["action"]   if conf else "NEUTRAL"
    rat_e    = conf["rationale_e"] if conf else "No signal data"
    rat_z    = conf["rationale_z"] if conf else "无信号数据"

    # ── Decision tree ─────────────────────────────────────────────────────────
    if score <= SCORE_EXIT_MAX:
        action     = "EXIT"
        priority   = "HIGH"
        reason_e   = (f"Strong bearish confluence (score {score}). "
                      f"Signal: {rat_e}. P&L: {pnl_pct:+.1f}%.")
        reason_z   = (f"强烈空头信号（评分{score}）。{rat_z}。"
                      f"当前盈亏：{pnl_pct:+.1f}%。")
        entry_target = None
        exit_trigger = f"Confluence score {score} ≤ {SCORE_EXIT_MAX} → EXIT recommended"

    elif score <= SCORE_CAUTION_MAX and pnl_pct >= 15.0:
        action     = "TRIM"
        priority   = "MEDIUM"
        reason_e   = (f"Bearish drift (score {score}) with unrealised gain {pnl_pct:+.1f}%. "
                      f"Consider locking partial profit. {rat_e}.")
        reason_z   = (f"信号走弱（评分{score}），浮盈{pnl_pct:+.1f}%，"
                      f"建议部分减仓锁定利润。{rat_z}。")
        entry_target = None
        exit_trigger = f"Score {score} ≤ {SCORE_CAUTION_MAX} + profit > 15% → TRIM suggested"

    elif pnl_pct >= PROFIT_TAKE_PCT:
        action     = "REVIEW_TRIM"
        priority   = "MEDIUM"
        reason_e   = (f"Large unrealised gain {pnl_pct:+.1f}% after {days}d. "
                      f"Signal still {action_q} (score {score}). "
                      f"Consider partial trim to protect profit.")
        reason_z   = (f"浮盈{pnl_pct:+.1f}%（持有{days}天），"
                      f"信号{score}仍属{conf['action_zh'] if conf else '中性'}，"
                      f"可考虑部分减仓保护利润。")
        entry_target = None
        exit_trigger = f"P&L > {PROFIT_TAKE_PCT}% → review trim opportunity"

    elif pnl_pct <= STOP_REVIEW_PCT:
        action     = "REVIEW_STOP"
        priority   = "HIGH"
        reason_e   = (f"Position in drawdown {pnl_pct:+.1f}%. "
                      f"Signal: {action_q} (score {score}). "
                      f"Review thesis — is the wrongIf condition still intact?")
        reason_z   = (f"亏损{pnl_pct:+.1f}%，信号评分{score}。"
                      f"建议复核投资逻辑，检查wrongIf条件是否触发。")
        entry_target = None
        exit_trigger = f"P&L {pnl_pct:.1f}% ≤ {STOP_REVIEW_PCT}% → thesis review required"

    elif score >= SCORE_ENTRY_MIN:
        action     = "ADD"
        priority   = "LOW"
        reason_e   = (f"Strong bullish confluence (score {score}) confirms thesis. "
                      f"P&L {pnl_pct:+.1f}% — consider adding on next technical pullback.")
        reason_z   = (f"多头信号强烈（评分{score}），thesis得到验证，"
                      f"浮盈{pnl_pct:+.1f}%，可考虑回踩时加仓。")
        entry_target = "Next MA20 or support test"
        exit_trigger = f"Score drops below {SCORE_CAUTION_MAX} OR P&L breaches stop"

    else:
        action     = "HOLD"
        priority   = "LOW"
        reason_e   = (f"Signal neutral (score {score}). "
                      f"P&L {pnl_pct:+.1f}% after {days}d. Hold — no new entry/exit trigger. "
                      f"{rat_e}.")
        reason_z   = (f"信号中性（评分{score}），浮盈{pnl_pct:+.1f}%，持有{days}天，"
                      f"无新触发条件。{rat_z}。")
        entry_target = None
        exit_trigger = f"Score ≤ {SCORE_EXIT_MAX} OR P&L ≤ {STOP_REVIEW_PCT}%"

    return {
        "ticker":       ticker,
        "name":         name,
        "status":       "HELD",
        "action":       action,
        "priority":     priority,
        "confidence":   abs(score),
        "pnl_pct":      round(pnl_pct, 2),
        "holding_days": days,
        "weight_pct":   round(weight, 1),
        "vp_score":     vp_score,
        "confluence":   score,
        "reason_e":     reason_e,
        "reason_z":     reason_z,
        "entry_target": entry_target,
        "exit_trigger": exit_trigger,
    }


def decide_watchlist_ticker(ticker, name, conf, vp_score, regime, sizing=None):
    """
    Generate a decision for a ticker in the universe but not currently held.
    Only recommend BUY_WATCH if both fundamental (VP) and technical (confluence) align.
    sizing: dict from position_sizing.json or None
    """
    score    = conf["score"]    if conf else 0
    rat_e    = conf["rationale_e"] if conf else "No signal data"
    rat_z    = conf["rationale_z"] if conf else "无信号数据"

    vp_ok    = vp_score is not None and vp_score >= VP_MIN_FOR_ENTRY
    sig_ok   = score >= SCORE_ENTRY_MIN
    regime_ok = regime != "RESTRICTIVE"

    if sig_ok and vp_ok and regime_ok:
        action   = "BUY_WATCH"
        priority = "MEDIUM"
        size_note_e = (
            f" Suggested size: {sizing['recommended_pct']:.1f}% "
            f"(¥{sizing['recommended_value']:,.0f}) [{sizing['conviction_tier']}]."
        ) if sizing else ""
        size_note_z = (
            f" 建议仓位：{sizing['recommended_pct']:.1f}%"
            f"（¥{sizing['recommended_value']:,.0f}）[{sizing['conviction_tier_zh']}]。"
        ) if sizing else ""
        reason_e = (f"PM + Quant aligned: VP {int(vp_score)} ≥ {VP_MIN_FOR_ENTRY} + "
                    f"signal score {score} ≥ {SCORE_ENTRY_MIN}. "
                    f"{rat_e}. Regime: {regime}.{size_note_e} Await human confirmation.")
        reason_z = (f"基本面+技术面共振：VP{int(vp_score)}≥{VP_MIN_FOR_ENTRY}，"
                    f"信号评分{score}≥{SCORE_ENTRY_MIN}。{rat_z}。{size_note_z}"
                    f"等待人工确认后建仓。")
    elif sig_ok and not vp_ok:
        action   = "WATCH"
        priority = "LOW"
        reason_e = (f"Technical entry signal (score {score}) but VP {vp_score} below threshold. "
                    f"Run DeepResearch to update VP before entering.")
        reason_z = (f"技术信号达标（{score}分）但VP{vp_score}低于门槛，"
                    f"建议先更新DeepResearch再考虑建仓。")
    elif vp_ok and not sig_ok:
        action   = "WATCH"
        priority = "LOW"
        reason_e = (f"VP {int(vp_score)} is strong but no technical entry yet (score {score}). "
                    f"Wait for signal confirmation: MA bounce, oversold, or volume breakout.")
        reason_z = (f"VP{int(vp_score)}较强但技术面未就位（{score}分），"
                    f"等待均线支撑/超卖/放量突破等技术确认。")
    elif not regime_ok:
        action   = "PASS"
        priority = "LOW"
        reason_e = f"Regime RESTRICTIVE — not entering despite VP {vp_score} / score {score}."
        reason_z = f"政策逆风（RESTRICTIVE），暂不考虑建仓（VP{vp_score}，信号{score}）。"
    else:
        action   = "WATCH"
        priority = "LOW"
        reason_e = f"No entry trigger. Score {score}, VP {vp_score}. {rat_e}."
        reason_z = f"无进场信号。评分{score}，VP{vp_score}。{rat_z}。"

    result = {
        "ticker":       ticker,
        "name":         name,
        "status":       "WATCHLIST",
        "action":       action,
        "priority":     priority,
        "confidence":   abs(score),
        "pnl_pct":      None,
        "holding_days": None,
        "weight_pct":   0,
        "vp_score":     vp_score,
        "confluence":   score,
        "reason_e":     reason_e,
        "reason_z":     reason_z,
        "entry_target": "Await BUY_WATCH confirmation" if action == "BUY_WATCH" else None,
        "exit_trigger": None,
    }

    # Attach sizing recommendation for BUY_WATCH candidates
    if action == "BUY_WATCH" and sizing:
        result["sizing"] = {
            "recommended_pct":   sizing["recommended_pct"],
            "recommended_value": sizing["recommended_value"],
            "stop_distance_pct": sizing["stop_distance_pct"],
            "conviction_tier":   sizing["conviction_tier"],
            "conviction_tier_zh":sizing["conviction_tier_zh"],
            "rationale_e":       sizing["rationale_e"],
            "rationale_z":       sizing["rationale_z"],
        }

    return result


# ── Portfolio risk checker ────────────────────────────────────────────────────

def compute_portfolio_risk(positions, regime_data):
    """Return a list of risk flag strings."""
    flags = []
    if not positions:
        return ["No positions held — portfolio is fully in cash."]

    total_value = sum(p.get("market_value", 0) for p in positions)
    if total_value == 0:
        return []

    # Single position concentration
    for p in positions:
        w = p.get("weight_pct", 0)
        if w > CONCENTRATION_MAX:
            flags.append(
                f"⚠️ CONCENTRATION: {p['ticker']} ({p.get('name','')}) = "
                f"{w:.0f}% of portfolio — above {CONCENTRATION_MAX}% limit"
            )

    # Sector concentration (use sector_sw field)
    from collections import defaultdict
    sector_weight = defaultdict(float)
    for p in positions:
        sector = p.get("sector_sw", "Unknown")
        sector_weight[sector] += p.get("weight_pct", 0)
    for sector, w in sector_weight.items():
        if w > SECTOR_MAX_PCT:
            flags.append(
                f"⚠️ SECTOR RISK: {sector} = {w:.0f}% of portfolio "
                f"— above {SECTOR_MAX_PCT}% limit"
            )

    # Under-diversified
    if len(positions) == 1:
        flags.append("⚠️ SINGLE STOCK: Portfolio has only 1 position — extreme concentration risk")
    elif len(positions) < 3:
        flags.append(f"ℹ️ Under-diversified: {len(positions)} positions (target: 3-5)")

    # Large winners — flag for review
    for p in positions:
        pnl = p.get("pnl_pct", 0)
        if pnl >= PROFIT_TAKE_PCT:
            flags.append(
                f"💰 PROFIT REVIEW: {p['ticker']} +{pnl:.1f}% — "
                f"consider partial trim to lock gains"
            )
        if pnl <= STOP_REVIEW_PCT:
            flags.append(
                f"🔴 DRAWDOWN REVIEW: {p['ticker']} {pnl:.1f}% — "
                f"review thesis and wrongIf conditions"
            )

    if not flags:
        flags.append("✅ Portfolio risk within acceptable parameters")

    return flags


# ── Trade attribution capsules (v15.1) ────────────────────────────────────────

def write_attribution_capsules(confluence_data, vp_data):
    """
    Snapshot per-ticker signal attribution at decision time.

    Provides a stable copy-paste source for new trade entries: confluence.json
    regenerates daily and its `contributing[]` values can shift between today's
    decision and the moment Junyan adds a trade. Pinning the snapshot at
    decision time keeps the attribution honest.

    Output: public/data/trade_attribution_capsules.json
    Schema matches the `signal_attribution` shape in trades.json (name/weight/
    direction), so the capsule can be copy-pasted into a new trade entry.
    """
    capsules = {}
    now = datetime.now(timezone.utc).isoformat()

    for entry in confluence_data.get("scores", []) or []:
        ticker = entry.get("ticker")
        if not ticker:
            continue

        contributing_signals = []
        for sig in entry.get("contributing", []) or []:
            sig_type = sig.get("type")
            if not sig_type:
                continue
            contributing_signals.append({
                "name":        sig_type,
                "weight":      round(sig.get("final_contribution", sig.get("base_weight", 0)), 1),
                "base_weight": sig.get("base_weight", 0),
                "direction":   SIGNAL_DIRECTION.get(sig_type, "neutral"),
            })

        # Pull VP + wrongIf from snapshot for this ticker
        vp_at_capture = None
        wrongif_at_capture_e = ""
        wrongif_at_capture_z = ""
        for snap in vp_data.get("snapshots", []) or []:
            if snap.get("ticker") == ticker:
                vp_at_capture = snap.get("vp_score")
                wrongif_at_capture_e = snap.get("wrongIf_e", "") or ""
                wrongif_at_capture_z = snap.get("wrongIf_z", "") or ""
                break

        capsules[ticker] = {
            "confluence_score":     entry.get("score"),
            "action":               entry.get("action"),
            "zone":                 entry.get("zone"),
            "contributing_signals": contributing_signals,
            "vp_at_capture":        vp_at_capture,
            "wrongIf_at_capture_e": wrongif_at_capture_e,
            "wrongIf_at_capture_z": wrongif_at_capture_z,
            "captured_at":          now,
        }

    output = {
        "generated_at": now,
        "date":         date.today().isoformat(),
        "note":         "Per-ticker attribution snapshot for new-trade entry. Schema matches trades.json signal_attribution shape. Pin to today's decision; do not regenerate after entering a trade.",
        "capsules":     capsules,
    }

    out_path = DATA_DIR / "trade_attribution_capsules.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    return out_path, len(capsules)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("[daily_decision] Starting Layer 2 decision engine...")

    confluence_data = load_json(DATA_DIR / "confluence.json",       {"scores": []})
    positions_data  = load_json(DATA_DIR / "positions.json",        {"positions": []})
    vp_data         = load_json(DATA_DIR / "vp_snapshot.json",      {"snapshots": []})
    regime_data     = load_json(DATA_DIR / "regime_config.json",    {"sectors": []})
    sizing_data     = load_json(DATA_DIR / "position_sizing.json",  {"sizing": []})
    market_data     = load_json(DATA_DIR / "market_data.json",      {})

    positions = positions_data.get("positions", [])
    held_tickers = {p["ticker"] for p in positions}

    decisions   = []
    buy_watches = []

    # ── 1. Decisions for held positions ──────────────────────────────────────
    print("\n[Held positions]")
    for pos in positions:
        ticker = pos["ticker"]
        conf   = get_confluence(ticker, confluence_data)
        vp     = get_vp(ticker, vp_data)
        dec    = decide_held_position(pos, conf, vp)
        decisions.append(dec)
        action_icon = {"EXIT": "🚨", "TRIM": "⬇️", "REVIEW_TRIM": "💰",
                       "REVIEW_STOP": "🔴", "ADD": "📈", "HOLD": "✅"}.get(dec["action"], "─")
        print(f"  {action_icon} {ticker:16s} {dec['action']:12s} "
              f"score={dec['confluence']:+4d}  P&L={dec['pnl_pct']:+.1f}%  "
              f"VP={dec['vp_score']}")

    # ── 2. Watchlist decisions (scored tickers not held) ──────────────────────
    print("\n[Watchlist universe]")
    # Collect all tickers that have confluence scores
    all_scored = confluence_data.get("scores", [])
    # Map regime info
    for entry in all_scored:
        ticker = entry["ticker"]
        if ticker in held_tickers:
            continue  # already handled above
        vp        = get_vp(ticker, vp_data)
        regime, _ = get_regime(ticker, regime_data)
        sizing    = get_sizing(ticker, sizing_data)
        # Try to get a name from positions or signals data
        name    = ticker  # default; could enrich later
        dec     = decide_watchlist_ticker(ticker, name, entry, vp, regime, sizing)
        decisions.append(dec)
        if dec["action"] == "BUY_WATCH":
            buy_watches.append(dec)
        icon = "🎯" if dec["action"] == "BUY_WATCH" else "👁️"
        sz_note = f"  size={dec['sizing']['recommended_pct']:.1f}%" if dec.get("sizing") else ""
        print(f"  {icon} {ticker:16s} {dec['action']:12s} "
              f"score={dec['confluence']:+4d}  VP={dec['vp_score']}{sz_note}")

    # ── 3. wrongIf monitor ───────────────────────────────────────────────────
    print("\n[wrongIf monitor]")
    wrongif_alerts = []
    all_tickers = list(held_tickers) + [e["ticker"] for e in all_scored if e["ticker"] not in held_tickers]
    for ticker in all_tickers:
        wi_e, wi_z = get_wrongif(ticker, vp_data)
        if not wi_e:
            continue
        alerts = check_wrongif(ticker, wi_e, market_data)
        triggered = [a for a in alerts if a["status"] == "TRIGGERED"]
        manual    = [a for a in alerts if a["status"] == "MANUAL"]

        if triggered:
            for a in triggered:
                wrongif_alerts.append({
                    "ticker":   ticker,
                    "severity": "HIGH",
                    "status":   "TRIGGERED",
                    "wrongIf_e": wi_e,
                    "wrongIf_z": wi_z,
                    "note_e":   a["note_e"],
                    "note_z":   a["note_z"],
                    "indicator":a["indicator"],
                    "actual":   a.get("actual"),
                    "threshold":a.get("threshold"),
                })
                print(f"  🚨 {ticker}: {a['note_e']}")
        elif manual:
            for a in manual[:1]:   # one manual alert per ticker is enough
                wrongif_alerts.append({
                    "ticker":   ticker,
                    "severity": "LOW",
                    "status":   "MANUAL",
                    "wrongIf_e": wi_e,
                    "wrongIf_z": wi_z,
                    "note_e":   a["note_e"],
                    "note_z":   a["note_z"],
                    "indicator":a["indicator"],
                    "actual":   None,
                    "threshold":None,
                })
                print(f"  👁️ {ticker}: manual check — {wi_e[:60]}…")

    if not wrongif_alerts:
        print("  No wrongIf alerts.")

    # ── 4. Portfolio risk ─────────────────────────────────────────────────────
    risk_flags = compute_portfolio_risk(positions, regime_data)

    # ── 5. Market regime summary ──────────────────────────────────────────────
    regime_summary = []
    for sector in regime_data.get("sectors", []):
        regime_summary.append({
            "sector":    sector.get("name_en", ""),
            "sector_zh": sector.get("name_zh", ""),
            "regime":    sector.get("regime", "NEUTRAL"),
            "tickers":   sector.get("tickers", []),
        })

    # ── 6. Build output ───────────────────────────────────────────────────────
    # Sort: held positions first (by priority), then watchlist
    held_decisions  = [d for d in decisions if d["status"] == "HELD"]
    watch_decisions = [d for d in decisions if d["status"] == "WATCHLIST"]

    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    held_decisions.sort(key=lambda x: priority_order.get(x["priority"], 3))
    watch_decisions.sort(key=lambda x: -x["confluence"])

    # One-line morning brief
    action_counts = {}
    for d in held_decisions:
        action_counts[d["action"]] = action_counts.get(d["action"], 0) + 1
    brief_parts = []
    if buy_watches:
        brief_parts.append(f"{len(buy_watches)} BUY WATCH")
    for act in ["EXIT", "TRIM", "REVIEW_TRIM", "REVIEW_STOP", "ADD"]:
        if action_counts.get(act, 0) > 0:
            brief_parts.append(f"{action_counts[act]} {act}")
    if not brief_parts:
        brief_parts.append(f"{len(held_decisions)} HOLD")
    brief_e = " | ".join(brief_parts)
    brief_z_map = {
        "BUY WATCH": "关注建仓", "EXIT": "建议离场",
        "TRIM": "建议减仓", "REVIEW_TRIM": "考虑减仓",
        "REVIEW_STOP": "复核止损", "ADD": "考虑加仓", "HOLD": "持有"
    }
    brief_z = " | ".join(
        f"{v}{brief_z_map.get(k.replace(f'{v} ','').strip(), k)}"
        for k, v in [p.split(" ", 1) if " " in p else (p, "") for p in brief_parts]
    ) or "全部持有"

    output = {
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "date":            date.today().isoformat(),
        "brief_e":         brief_e,
        "brief_z":         brief_z,
        "decisions": {
            "held":      held_decisions,
            "watchlist": watch_decisions,
        },
        "buy_watches":     [d["ticker"] for d in buy_watches],
        "portfolio_risk":  risk_flags,
        "wrongif_alerts":  wrongif_alerts,
        "regime_summary":  regime_summary,
        "stats": {
            "positions_held":    len(held_decisions),
            "watchlist_count":   len(watch_decisions),
            "buy_watch_count":   len(buy_watches),
            "wrongif_triggered": sum(1 for a in wrongif_alerts if a["status"] == "TRIGGERED"),
            "wrongif_manual":    sum(1 for a in wrongif_alerts if a["status"] == "MANUAL"),
        },
    }

    out_path = DATA_DIR / "daily_decision.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[daily_decision] Done → {out_path}")
    print(f"  Brief: {brief_e}")
    print(f"  Risk flags:")
    for flag in risk_flags:
        print(f"    {flag}")

    # ── 7. Trade attribution capsules (v15.1) ────────────────────────────────
    cap_path, cap_count = write_attribution_capsules(confluence_data, vp_data)
    print(f"\n[daily_decision] Attribution capsules → {cap_path}  ({cap_count} tickers)")


if __name__ == "__main__":
    main()
