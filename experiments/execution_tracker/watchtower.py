#!/usr/bin/env python3
"""
watchtower.py — P6.2-Watchtower v0: the continuous intraday event daemon.

The "不停歇" layer Junyan asked for: a cheap Python daemon polls the market every
POLL_SECONDS during trading hours, watches the Model Paper Fund's orders/positions
plus a watch list, fires DESKTOP/TELEGRAM alerts the moment an event rule trips —
no human ping needed. The LLM reasoning layer stays event/checkpoint-driven per the
constitution (no 24h LLM); this daemon is the eyes, not the brain.

Event rules (v0, all thresholds [unvalidated intuition]):
  ENTRY_CROSSED    pending order's entry crossed intraday (fill registers at settle, T+1 rules)
  STOP_CROSSED     filled position at/under stop_reference  -> DE_RISK alert
  STOP_PROXIMITY   filled position within 1% of stop
  TARGET_PROXIMITY filled position within 1% of take-profit
  NOWCAST_FLIP     a watch name's nowcast state changed (conf >= 0.6)
  INDEX_MOVE       上证/创业板 intraday move beyond ±1.5%

Discipline: alerts are OBSERVATIONS (sample_eligible:false, no_trade_flag:true) —
the daemon never fills, never edits the ledger; settle processing stays post-close.
Each event fires ONCE per (rule, key, day). Alert log is append-only.

Channels: macOS notification (zero-config, default) + Telegram (auto-enabled when
TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are set in the environment).

  python3 watchtower.py --selftest        # offline rule tests
  python3 watchtower.py --once            # single poll (smoke)
  python3 watchtower.py --daemon          # poll until 15:05 (launchd entry point)
Install as launchd job: see launchd/com.ar.watchtower.plist
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fund_source as fs                          # noqa: E402
from run_premarket_monitor import (               # noqa: E402
    read_quote, nowcast_from_read, is_market_open_now)

POLL_SECONDS = 120
STOP_PROX = 0.01
TARGET_PROX = 0.01
INDEX_MOVE = 0.015
NOWCAST_MIN_CONF = 0.6
SESSION_END = "150500"

STATE_PATH = os.path.join(HERE, "watchtower_state.json")
ALERT_LOG = os.path.join(HERE, "watchtower_log.json")
FUND_ORDERS = os.path.join(HERE, "model_fund", "orders.json")

WATCH = [("300502.SZ", "新易盛"), ("300475.SZ", "香农芯创"), ("603629.SH", "利通电子"),
         ("300308.SZ", "中际旭创"), ("002130.SZ", "沃尔核材")]
INDICES = [("000001.SH", "上证"), ("399006.SZ", "创业板")]


# ---------------------------------------------------------------- channels ----
def notify_mac(title, body):
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{body}" with title "{title}" sound name "Glass"'],
                       capture_output=True, timeout=5)
        return True
    except Exception:                              # noqa: BLE001
        return False


def notify_telegram(title, body):
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not tok or not chat:
        return False
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": f"{title}\n{body}"}).encode()
        urllib.request.urlopen(
            urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data),
            timeout=8)
        return True
    except Exception:                              # noqa: BLE001
        return False


def notify(title, body, dry=False):
    if dry:
        return {"mac": False, "telegram": False, "dry": True}
    return {"mac": notify_mac(title, body), "telegram": notify_telegram(title, body)}


# ------------------------------------------------------------------ events ----
def load_json(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


def evaluate_events(quotes, orders, state, today, nowcast_sink=None):
    """Pure rule engine: (quotes, fund orders, dedup state) -> new alert dicts.
    quotes: {ticker: normalized realtime row}. Offline-testable.
    nowcast_sink: optional callable(read_dict) — receives each CONFIDENT
    nowcast flip so callers can log it into the scoring pool; None keeps
    this function pure/offline."""
    alerts = []
    fired = state.setdefault("fired", {})

    def fire(rule, key, title, body):
        k = f"{today}|{rule}|{key}"
        if k in fired:
            return
        fired[k] = True
        alerts.append({"date": today, "rule": rule, "key": key, "title": title,
                       "body": body, "sample_eligible": False, "no_trade_flag": True})

    for o in orders:
        q = quotes.get(o["ticker"])
        if not q or not q.get("price"):
            continue
        px, hi = q["price"], q.get("high") or q["price"]
        if o["status"] == "pending" and hi >= o["entry_review_price"]:
            fire("ENTRY_CROSSED", o["ticker"], f"⚡ {o['name']} 触发 entry",
                 f"日高{hi} ≥ entry {o['entry_review_price']} — 收盘结算时按T+1规则成交 "
                 f"({o['shares']}股, stop {o['stop_reference']} / target {o['take_profit_reference']})")
        if o["status"] == "filled":
            if px <= o["stop_reference"]:
                fire("STOP_CROSSED", o["ticker"], f"🛑 {o['name']} 触及止损",
                     f"现价{px} ≤ stop {o['stop_reference']} — DE_RISK,收盘结算出场")
            elif px <= o["stop_reference"] * (1 + STOP_PROX):
                fire("STOP_PROXIMITY", o["ticker"], f"⚠ {o['name']} 逼近止损",
                     f"现价{px} 距 stop {o['stop_reference']} <1%")
            if px >= o["take_profit_reference"] * (1 - TARGET_PROX):
                fire("TARGET_PROXIMITY", o["ticker"], f"🎯 {o['name']} 逼近止盈",
                     f"现价{px} 距 target {o['take_profit_reference']} <1%")

    last_nc = state.setdefault("nowcast", {})
    for ticker, q in quotes.items():
        if ticker.startswith(("000001.SH", "399")):
            continue
        r = read_quote(q)
        nc = nowcast_from_read(r)
        if nc and nc[0] != "DATA_INSUFFICIENT" and nc[1] >= NOWCAST_MIN_CONF:
            prev = last_nc.get(ticker)
            if prev != nc[0]:
                last_nc[ticker] = nc[0]
                fire("NOWCAST_FLIP", f"{ticker}|{nc[0]}", f"🔮 {q.get('name') or ticker} nowcast → {nc[0]}",
                     f"conf {nc[1]:.2f} gap{(r.get('gap') or 0)*100:+.1f}% 距开{(r.get('from_open') or 0)*100:+.1f}% "
                     f"(推断,收盘判分)")
                if nowcast_sink:
                    # PR-M2 wiring: flips also enter the nowcast_log scoring
                    # pool (sample_eligible=false) so the evaluator can grade
                    # them post-close — previously they died in the alert log.
                    read = dict(r)
                    read["ticker"] = ticker
                    read["name"] = q.get("name") or ticker
                    nowcast_sink(read)

    for code, name in INDICES:
        q = quotes.get(code)
        if q and q.get("price") and q.get("pre_close"):
            chg = q["price"] / q["pre_close"] - 1
            if abs(chg) >= INDEX_MOVE:
                fire("INDEX_MOVE", f"{code}|{'up' if chg > 0 else 'down'}",
                     f"📊 {name} {chg:+.1%}", "指数波动超±1.5% — 组合风险复核")
    return alerts


def poll_once(token, dry=False):
    """One live poll: fetch quotes, evaluate rules, notify + log."""
    import datetime
    today = datetime.datetime.now().strftime("%Y%m%d")
    orders = load_json(FUND_ORDERS, [])
    tickers = sorted({o["ticker"] for o in orders if o["status"] in ("pending", "filled")}
                     | {t for t, _ in WATCH} | {c for c, _ in INDICES})
    rows = fs.tushare_realtime_quotes(tickers, src="sina")
    quotes = {}
    name_map = dict(WATCH); name_map.update({c: n for c, n in INDICES})
    name_map.update({o["ticker"]: o["name"] for o in orders})
    for r in rows:
        t = r.get("ticker") or ""
        full = t if "." in t else next((x for x in tickers if x.startswith(t)), t)
        r["name"] = r.get("name") or name_map.get(full)
        quotes[full] = r
    state = load_json(STATE_PATH, {})

    def nowcast_sink(read):
        """Flip → nowcast_log scoring pool via the ONE existing writer
        (run_premarket_monitor.log_nowcasts: dedup + no retro-edit).
        Non-fatal by design — the daemon never dies from logging."""
        try:
            from run_premarket_monitor import log_nowcasts
            hhmm = datetime.datetime.now().strftime("%H%M")
            added = log_nowcasts([read], today, f"wt{hhmm}")
            if added:
                print(f"  [nowcast→pool] {read.get('name')} logged (wt{hhmm})")
        except Exception as e:                     # noqa: BLE001
            print("nowcast sink error:", str(e)[:80])

    alerts = evaluate_events(quotes, orders, state, today, nowcast_sink=nowcast_sink)
    log = load_json(ALERT_LOG, [])
    for a in alerts:
        a["sent"] = notify(a["title"], a["body"], dry=dry)
        log.append(a)
        print(f"  [{a['rule']}] {a['title']} — {a['body']}")
    json.dump(state, open(STATE_PATH, "w"), ensure_ascii=False, indent=2)
    json.dump(log, open(ALERT_LOG, "w"), ensure_ascii=False, indent=2)
    return alerts


def daemon(token):
    import datetime
    print(f"watchtower daemon up @{datetime.datetime.now().strftime('%H:%M:%S')} "
          f"(poll {POLL_SECONDS}s until {SESSION_END})")
    notify("AR Watchtower", "盯盘守护进程已启动")
    while datetime.datetime.now().strftime("%H%M%S") < SESSION_END:
        open_now, why = is_market_open_now(token)
        if open_now:
            try:
                poll_once(token)
            except Exception as e:                 # noqa: BLE001
                print("poll error:", str(e)[:100])
        time.sleep(POLL_SECONDS)
    notify("AR Watchtower", "收盘,守护进程退出(定盘结算走盘后流程)")
    print("session end.")


# ---------------------------------------------------------------- selftest ----
def _q(t, name, price, pre, op, hi, lo):
    return {"ticker": t, "name": name, "price": price, "pre_close": pre, "open": op,
            "high": hi, "low": lo, "pct_chg": round((price / pre - 1) * 100, 2)}


def selftest():
    checks = []

    def ck(n, c):
        checks.append((n, bool(c)))

    orders = [
        {"ticker": "A.SH", "name": "甲", "status": "pending", "entry_review_price": 28.2,
         "stop_reference": 26.2, "take_profit_reference": 32.2, "shares": 5000},
        {"ticker": "B.SH", "name": "乙", "status": "filled", "fill_price": 55.5,
         "entry_review_price": 55.5, "stop_reference": 52.2, "take_profit_reference": 62.1,
         "shares": 2700},
    ]
    state = {}
    quotes = {
        "A.SH": _q("A.SH", "甲", 28.3, 27.8, 27.9, 28.4, 27.7),      # crossed entry
        "B.SH": _q("B.SH", "乙", 52.6, 53.0, 53.0, 53.2, 52.5),      # within 1% of stop 52.2? 52.2*1.01=52.72 -> yes
        "000001.SH": _q("000001.SH", "上证", 3930.0, 4000.0, 3990.0, 3995.0, 3925.0),  # -1.75%
    }
    alerts = evaluate_events(quotes, orders, state, "20260707")
    rules = {a["rule"] for a in alerts}
    ck("ENTRY_CROSSED fires", "ENTRY_CROSSED" in rules)
    ck("STOP_PROXIMITY fires", "STOP_PROXIMITY" in rules)
    ck("INDEX_MOVE fires on -1.75%", "INDEX_MOVE" in rules)
    ck("alerts carry no_trade_flag", all(a["no_trade_flag"] for a in alerts))
    ck("alerts never sample-eligible", all(a["sample_eligible"] is False for a in alerts))

    again = evaluate_events(quotes, orders, state, "20260707")
    ck("dedup: same poll fires nothing new", len(again) == 0)

    quotes["B.SH"] = _q("B.SH", "乙", 52.1, 53.0, 53.0, 53.2, 52.0)   # now AT/under stop
    a3 = evaluate_events(quotes, orders, state, "20260707")
    ck("STOP_CROSSED escalates after proximity", any(x["rule"] == "STOP_CROSSED" for x in a3))

    quotes["B.SH"] = _q("B.SH", "乙", 61.9, 53.0, 53.0, 62.0, 52.0)   # near target 62.1
    a4 = evaluate_events(quotes, orders, state, "20260707")
    ck("TARGET_PROXIMITY fires", any(x["rule"] == "TARGET_PROXIMITY" for x in a4))

    # nowcast flip: gap-down sinking -> DISTRIBUTION_PROBABLE (conf>=0.6 path)
    quotes["C.SZ"] = _q("C.SZ", "丙", 96.0, 100.0, 98.0, 98.5, 95.8)   # gap -4%, from_open -2%
    a5 = evaluate_events(quotes, orders, state, "20260707")
    ck("NOWCAST_FLIP fires on state change", any(x["rule"] == "NOWCAST_FLIP" for x in a5))
    a6 = evaluate_events(quotes, orders, state, "20260707")
    ck("NOWCAST same state does not re-fire", not any(x["rule"] == "NOWCAST_FLIP" for x in a6))

    # PR-M2 wiring: confident flips reach the nowcast sink (offline capture)
    captured = []
    quotes["D.SZ"] = _q("D.SZ", "丁", 91.0, 95.0, 93.0, 93.5, 90.8)   # deep fade
    evaluate_events(quotes, orders, state, "20260707", nowcast_sink=captured.append)
    ck("sink receives the flip read with ticker+name",
       len(captured) == 1 and captured[0]["ticker"] == "D.SZ"
       and captured[0]["name"] == "丁")
    evaluate_events(quotes, orders, state, "20260707", nowcast_sink=captured.append)
    ck("sink NOT called when state unchanged", len(captured) == 1)
    ck("sink=None keeps evaluate_events pure (no crash path)",
       isinstance(evaluate_events(quotes, orders, state, "20260707"), list))

    # new day resets dedup
    a7 = evaluate_events(quotes, orders, state, "20260708")
    ck("new day re-fires", any(x["rule"] == "ENTRY_CROSSED" for x in a7))

    passed = sum(1 for _, okk in checks if okk)
    for n, okk in checks:
        print(f"  [{'PASS' if okk else 'FAIL'}] {n}")
    print(f"\nselftest: {passed}/{len(checks)} passed")
    return passed == len(checks)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="AR Watchtower daemon (observation only)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--once", action="store_true", help="single live poll (smoke)")
    ap.add_argument("--daemon", action="store_true", help="poll until 15:05")
    ap.add_argument("--dry", action="store_true", help="evaluate but do not send notifications")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("NO TUSHARE_TOKEN — run `source ~/.zprofile` first"); sys.exit(1)
    if args.once:
        alerts = poll_once(token, dry=args.dry)
        print(f"poll done: {len(alerts)} new alerts")
        return
    if args.daemon:
        daemon(token)
        return
    ap.print_help()


if __name__ == "__main__":
    main()
