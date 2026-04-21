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
from datetime import datetime, timezone, date
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "public" / "data"

# ── Thresholds ────────────────────────────────────────────────────────────────
VP_MIN_FOR_ENTRY    = 60    # Minimum VP score to consider a new entry
SCORE_ENTRY_MIN     = 60    # Confluence score threshold for BUY signal
SCORE_CAUTION_MAX   = -20   # Below this → caution
SCORE_EXIT_MAX      = -60   # Below this → exit signal

PROFIT_TAKE_PCT     = 25.0  # Suggest trim when P&L > this
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


def decide_watchlist_ticker(ticker, name, conf, vp_score, regime):
    """
    Generate a decision for a ticker in the universe but not currently held.
    Only recommend BUY_WATCH if both fundamental (VP) and technical (confluence) align.
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
        reason_e = (f"PM + Quant aligned: VP {int(vp_score)} ≥ {VP_MIN_FOR_ENTRY} + "
                    f"signal score {score} ≥ {SCORE_ENTRY_MIN}. "
                    f"{rat_e}. Regime: {regime}. Await human confirmation.")
        reason_z = (f"基本面+技术面共振：VP{int(vp_score)}≥{VP_MIN_FOR_ENTRY}，"
                    f"信号评分{score}≥{SCORE_ENTRY_MIN}。{rat_z}。"
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

    return {
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("[daily_decision] Starting Layer 2 decision engine...")

    confluence_data = load_json(DATA_DIR / "confluence.json",    {"scores": []})
    positions_data  = load_json(DATA_DIR / "positions.json",     {"positions": []})
    vp_data         = load_json(DATA_DIR / "vp_snapshot.json",   {"snapshots": []})
    regime_data     = load_json(DATA_DIR / "regime_config.json", {"sectors": []})

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
        vp      = get_vp(ticker, vp_data)
        regime, _ = get_regime(ticker, regime_data)
        # Try to get a name from positions or signals data
        name    = ticker  # default; could enrich later
        dec     = decide_watchlist_ticker(ticker, name, entry, vp, regime)
        decisions.append(dec)
        if dec["action"] == "BUY_WATCH":
            buy_watches.append(dec)
        icon = "🎯" if dec["action"] == "BUY_WATCH" else "👁️"
        print(f"  {icon} {ticker:16s} {dec['action']:12s} "
              f"score={dec['confluence']:+4d}  VP={dec['vp_score']}")

    # ── 3. Portfolio risk ─────────────────────────────────────────────────────
    risk_flags = compute_portfolio_risk(positions, regime_data)

    # ── 4. Market regime summary ──────────────────────────────────────────────
    regime_summary = []
    for sector in regime_data.get("sectors", []):
        regime_summary.append({
            "sector":    sector.get("name_en", ""),
            "sector_zh": sector.get("name_zh", ""),
            "regime":    sector.get("regime", "NEUTRAL"),
            "tickers":   sector.get("tickers", []),
        })

    # ── 5. Build output ───────────────────────────────────────────────────────
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
        "regime_summary":  regime_summary,
        "stats": {
            "positions_held":  len(held_decisions),
            "watchlist_count": len(watch_decisions),
            "buy_watch_count": len(buy_watches),
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


if __name__ == "__main__":
    main()
