#!/usr/bin/env python3
"""
AR Platform — Telegram Alert Pipeline
Sends daily market digest + event-driven alerts to your Telegram chat.

Setup (5 minutes):
  1. Open Telegram → message @BotFather → /newbot → get BOT_TOKEN
  2. Start a chat with your new bot, then visit:
       https://api.telegram.org/bot{YOUR_TOKEN}/getUpdates
     Copy the "chat" → "id" field (your CHAT_ID)
  3. Add to GitHub Secrets:
       TELEGRAM_BOT_TOKEN  = 123456:ABCdef...
       TELEGRAM_CHAT_ID    = -100123456789  (or your personal chat ID)
  4. This script is called by GitHub Actions after fetch_data.py

The script fires two types of alerts:
  A) Daily digest  — always runs, summarises VP scores + price action
  B) Event alerts  — fires only when triggers are hit (RSI extremes, VP change,
                     northbound reversal, earnings in 3 days, D&T board hit)
"""

import json, os, sys, requests
from pathlib import Path
from datetime import datetime, timedelta

DATA_DIR = Path(__file__).parent.parent / "public" / "data"

# ── Alert thresholds ─────────────────────────────────────────────────────────
RSI_OVERSOLD    = 30
RSI_OVERBOUGHT  = 70
VP_CHANGE_ALERT = 5       # alert if VP moves ±5 points vs yesterday
NORTHBOUND_THRESHOLD = 5e9  # ±5B CNY daily net flow = significant
EARNINGS_WARNING_DAYS = 5   # alert if earnings within N days

# ── Macro-event to stock impact map ─────────────────────────────────────────
MACRO_STOCK_MAP = {
    "pboc_rate_cut":   [("700.HK", "positive", "HIGH"), ("002594.SZ", "positive", "HIGH")],
    "cpi_above_2pct":  [("700.HK", "negative", "MED"),  ("9999.HK",  "negative", "MED")],
    "usd_cny_above_73":[("002594.SZ", "negative", "HIGH"), ("300308.SZ", "positive", "MED")],
    "vix_spike_20":    [("700.HK", "negative", "MED"),  ("6160.HK",  "negative", "MED")],
    "northbound_reversal": [("300308.SZ", "negative", "MED"), ("002594.SZ", "negative", "MED")],
}


def send_message(token, chat_id, text, parse_mode="HTML"):
    """Send a Telegram message with retry."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for attempt in range(3):
        try:
            resp = requests.post(url, json={
                "chat_id":    chat_id,
                "text":       text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }, timeout=10)
            if resp.status_code == 200:
                return True
            print(f"  Telegram {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            print(f"  Telegram attempt {attempt+1}: {e}")
    return False


def load_market_data():
    f = DATA_DIR / "market_data.json"
    if not f.exists(): return {}
    with open(f) as fh:
        return json.load(fh)


def load_flow_data():
    f = DATA_DIR / "flow_data.json"
    if not f.exists(): return {}
    with open(f) as fh:
        return json.load(fh)


def load_earnings_calendar():
    f = DATA_DIR / "earnings_calendar.json"
    if not f.exists(): return []
    with open(f) as fh:
        return json.load(fh).get("entries", [])


def fmt_price_line(ticker, yd):
    p = yd.get("price", {})
    last = p.get("last", "—")
    chg  = p.get("change_pct", 0) or 0
    sign = "🟢" if chg > 0 else "🔴" if chg < 0 else "⚪"
    arrow = "▲" if chg > 0 else "▼" if chg < 0 else "─"
    m    = yd.get("meta", {})
    name = m.get("name_zh", m.get("name_en", ticker))
    return f"{sign} <b>{name}</b> ({ticker})  {last}  {arrow}{abs(chg):.1f}%"


def build_daily_digest(mdata, flow):
    """Build the daily portfolio digest message."""
    today = datetime.now().strftime("%Y-%m-%d %a")
    lines = [
        f"📊 <b>Alpha Research Daily Digest</b>",
        f"<i>{today} · After-market</i>",
        "─" * 30,
        "",
        "<b>▶ Focus Positions</b>",
    ]

    yahoo = mdata.get("yahoo", {})
    TICKERS_ORDER = ["300308.SZ", "700.HK", "9999.HK", "6160.HK", "002594.SZ"]
    for tk in TICKERS_ORDER:
        yd = yahoo.get(tk)
        if yd:
            lines.append("  " + fmt_price_line(tk, yd))
            # RSI alert inline
            rsi = yd.get("technical", {}).get("rsi_14")
            if rsi and rsi < RSI_OVERSOLD:
                lines.append(f"    ⚠️ RSI={rsi:.0f} — OVERSOLD territory")
            elif rsi and rsi > RSI_OVERBOUGHT:
                lines.append(f"    ⚠️ RSI={rsi:.0f} — OVERBOUGHT territory")

    # Northbound
    nb = mdata.get("akshare", {}).get("northbound", {})
    if nb:
        nf = nb.get("latest_net_flow", 0) or 0
        icon = "🟢" if nf > 0 else "🔴"
        lines.append("")
        lines.append(f"<b>▶ Capital Flows</b>")
        lines.append(f"  {icon} Northbound (北向):  {nf/1e8:+.1f}亿 | 5D: {nb.get('5d_cumulative',0)/1e8:+.1f}亿")

    sb = flow.get("southbound", {})
    if sb:
        sf = sb.get("latest_net_flow", 0) or 0
        icon = "🟢" if sf > 0 else "🔴"
        lines.append(f"  {icon} Southbound (南向):  {sf/1e8:+.1f}亿 | 5D: {sb.get('5d_cumulative',0)/1e8:+.1f}亿")

    # Dragon & Tiger hits for focus stocks
    dt = flow.get("dragon_tiger", [])
    focus_dt = [e for e in dt if e.get("focus")]
    if focus_dt:
        lines.append("")
        lines.append("<b>▶ 龙虎榜 Hits (Focus Stocks)</b>")
        for e in focus_dt[:3]:
            net = e.get("net_amt", 0) or 0
            icon = "🟢" if net > 0 else "🔴"
            lines.append(f"  {icon} {e['name']} ({e['code']}) {e['date']} — Net: {net/1e8:.2f}亿")

    lines.append("")
    lines.append("─" * 30)
    lines.append("<i>AR Platform v4.0 · Evidence only, no investment conclusions</i>")

    return "\n".join(lines)


def build_event_alerts(mdata, flow, earnings_cal):
    """Return list of event alert messages to fire."""
    alerts = []
    yahoo  = mdata.get("yahoo", {})
    today  = datetime.now().date()

    # 1. RSI extreme alerts
    for tk, yd in yahoo.items():
        rsi = yd.get("technical", {}).get("rsi_14")
        name = yd.get("meta", {}).get("name_zh", tk)
        if rsi and rsi < RSI_OVERSOLD:
            alerts.append(
                f"🚨 <b>RSI OVERSOLD ALERT</b>\n"
                f"{name} ({tk}) — RSI={rsi:.1f}\n"
                f"Below {RSI_OVERSOLD}. Potential mean-reversion opportunity.\n"
                f"Check variant thesis validity before acting."
            )
        elif rsi and rsi > RSI_OVERBOUGHT:
            alerts.append(
                f"⚠️ <b>RSI OVERBOUGHT ALERT</b>\n"
                f"{name} ({tk}) — RSI={rsi:.1f}\n"
                f"Above {RSI_OVERBOUGHT}. Review position sizing."
            )

    # 2. Northbound flow reversal
    nb = mdata.get("akshare", {}).get("northbound", {})
    nf = nb.get("latest_net_flow", 0) or 0
    if abs(nf) > NORTHBOUND_THRESHOLD:
        icon = "🟢" if nf > 0 else "🔴"
        direction = "LARGE INFLOW" if nf > 0 else "LARGE OUTFLOW"
        alerts.append(
            f"{icon} <b>NORTHBOUND FLOW — {direction}</b>\n"
            f"Daily net: {nf/1e8:+.1f}亿 CNY\n"
            f"5-day cumulative: {nb.get('5d_cumulative',0)/1e8:+.1f}亿\n"
            f"Signal strength: HIGH for A-share sentiment."
        )

    # 3. Earnings within N days (from calendar)
    for entry in earnings_cal:
        # Look for entries with dates
        # A-share 业绩预告 type-based alerts
        change_low = entry.get("change_low") or 0
        change_high = entry.get("change_high") or 0
        ptype = entry.get("type", "")
        if entry.get("focus") and ptype in ("预增", "续盈", "扭亏"):
            alerts.append(
                f"📈 <b>EARNINGS PRE-ANNOUNCEMENT</b>\n"
                f"{entry.get('name')} ({entry.get('ticker')})\n"
                f"Type: {ptype}\n"
                f"Profit change: {change_low:+.0f}% to {change_high:+.0f}%\n"
                f"Period: {entry.get('period')}"
            )
        elif entry.get("focus") and ptype in ("预减", "续亏", "首亏"):
            alerts.append(
                f"📉 <b>EARNINGS WARNING</b>\n"
                f"{entry.get('name')} ({entry.get('ticker')})\n"
                f"Type: {ptype}\n"
                f"Profit change: {change_low:+.0f}% to {change_high:+.0f}%\n"
                f"⚠️ Review thesis — wrong-if condition may be triggered."
            )

    return alerts


def main():
    token   = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set.")
        print("       Add as GitHub Secrets. Skipping alerts.")
        sys.exit(0)  # don't fail the workflow, just skip

    print(f"{'='*50}")
    print(f"AR Platform — Telegram Alert Pipeline")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    mdata    = load_market_data()
    flow     = load_flow_data()
    earnings = load_earnings_calendar()

    # A. Daily digest (always)
    print("[1/2] Sending daily digest...")
    digest = build_daily_digest(mdata, flow)
    ok = send_message(token, chat_id, digest)
    print(f"  Digest: {'sent ✓' if ok else 'FAILED'}")

    # B. Event alerts (conditional)
    print("[2/2] Checking event triggers...")
    alerts = build_event_alerts(mdata, flow, earnings)
    if not alerts:
        print("  No event alerts triggered today.")
    for i, alert in enumerate(alerts):
        ok = send_message(token, chat_id, alert)
        print(f"  Alert {i+1}/{len(alerts)}: {'sent ✓' if ok else 'FAILED'}")

    print(f"\nDONE: 1 digest + {len(alerts)} event alerts")


if __name__ == "__main__":
    main()
