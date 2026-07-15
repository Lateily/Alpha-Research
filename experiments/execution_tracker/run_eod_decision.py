#!/usr/bin/env python3
"""
run_eod_decision.py — P5 尾盘决策窗引擎 v0(影子模式)

决策窗 14:25-14:55(刻意避开 14:57 集合竞价与最后 10 分钟操纵高发段)。
对活跃 execution_gate 信号用实时价核对触发区,只产出:
  REVIEW_CANDIDATE — 价区已打印且未破 invalidation:送人审/结算复核
  PAPER_SIGNAL     — 记录影子判定(与次日触发单机制 A/B 对照)
  NO_ACTION        — 条件未成立
永不成交、永不注册;资金腿在定盘由 setup_promoter 复核(尾盘资金不可得,
显式声明 flow_leg: DEFERRED_TO_SETTLE)。全部输入 sample_eligible: false。
窗外调用 => OFF_WINDOW 声明退出(--force + 注入行情仅供测试)。

不是买卖指令；研究信号，human executes。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "eod_candidates.json")
WIN_LO, WIN_HI = "1425", "1455"


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def in_window(hhmm):
    return WIN_LO <= hhmm <= WIN_HI


def _zone(text):
    import re
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", text or "")
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return (min(lo, hi), max(lo, hi))
    m = re.search(r"(\d+(?:\.\d+)?)\s*±\s*(\d+(?:\.\d+)?)", text or "")
    if m:
        c, d = float(m.group(1)), float(m.group(2))
        return (c - d, c + d)
    return None


def _stop(text):
    import re
    m = re.search(r"收盘\s*[<＜]\s*(\d+(?:\.\d+)?)", text or "")
    return float(m.group(1)) if m else None


def decide(signals, quotes, today, hhmm):
    """纯函数。quotes: {ticker: {'price','low','high'}}(推断,sample_eligible=false)"""
    out, blocked = [], []
    for s in signals:
        t = s.get("ticker") or ""
        if (s.get("official_sample") or s.get("setup_type") != "execution_gate"
                or s.get("outcome_status", "pending") != "pending" or "." not in t):
            continue
        q = quotes.get(t)
        if not q or not q.get("price"):
            blocked.append({"ticker": t, "why": "DATA_BLOCKED: 尾盘行情缺失"})
            continue
        zone, stop = _zone(s.get("trigger_condition")), _stop(s.get("invalidation"))
        if zone is None or stop is None:
            out.append({"ticker": t, "name": s.get("name"), "date": today,
                        "window": hhmm, "verdict": "NO_ACTION",
                        "why": "trigger/invalidation 不可机械解析(人审)",
                        "sample_eligible": False, "no_trade_flag": True})
            continue
        touched = q.get("low", q["price"]) <= zone[1] and q.get("high", q["price"]) >= zone[0]
        holding = q["price"] > stop
        if touched and holding:
            verdict = "REVIEW_CANDIDATE"
            why = (f"尾盘{hhmm}: 价区{zone[0]}-{zone[1]}已打印,现价{q['price']}>"
                   f"invalidation {stop};flow_leg=DEFERRED_TO_SETTLE")
        elif not holding:
            verdict = "NO_ACTION"
            why = f"现价{q['price']} <= invalidation {stop}"
        else:
            verdict = "NO_ACTION"
            why = f"价区{zone[0]}-{zone[1]}未打印(日内低{q.get('low')})"
        out.append({"ticker": t, "name": s.get("name"), "signal_id": s.get("signal_id"),
                    "date": today, "window": hhmm, "verdict": verdict, "why": why,
                    "eod_price": q["price"], "sample_eligible": False,
                    "no_trade_flag": True})
    return {"date": today, "window": hhmm, "candidates": out,
            "data_blocked": blocked,
            "note": "影子判定;永不成交/注册;与次日触发机制A/B对照。不是买卖指令。"}


def append_log(result):
    log = _load(OUT, [])
    seen = {(x.get("date"), x.get("ticker")) for x in log}
    added = [c for c in result["candidates"]
             if (c["date"], c["ticker"]) not in seen]
    log.extend(added)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=1)
    return len(added)


def selftest():
    ok = []

    def ck(name, cond):
        ok.append((name, bool(cond)))
        print(("  ✓ " if cond else "  ✗ ") + name)

    ck("窗口判定 1424 外", not in_window("1424"))
    ck("窗口判定 1430 内", in_window("1430"))
    ck("窗口判定 1456 外(避开尾竞价)", not in_window("1456"))
    sig = {"ticker": "002463.SZ", "name": "沪电", "setup_type": "execution_gate",
           "outcome_status": "pending", "official_sample": False, "signal_id": "a2a40a",
           "trigger_condition": "回踩127-130承接", "invalidation": "收盘<123"}
    q_hit = {"002463.SZ": {"price": 131.0, "low": 128.5, "high": 137.0}}
    r = decide([sig], q_hit, "20260715", "1435")
    ck("区打印+未破 → REVIEW_CANDIDATE", r["candidates"][0]["verdict"] == "REVIEW_CANDIDATE")
    ck("资金腿显式 DEFERRED", "DEFERRED_TO_SETTLE" in r["candidates"][0]["why"])
    ck("sample_eligible=false 强制", r["candidates"][0]["sample_eligible"] is False)
    r2 = decide([sig], {"002463.SZ": {"price": 122.0, "low": 121, "high": 137}},
                "20260715", "1435")
    ck("破 invalidation → NO_ACTION", r2["candidates"][0]["verdict"] == "NO_ACTION")
    r3 = decide([sig], {"002463.SZ": {"price": 136.0, "low": 133, "high": 137}},
                "20260715", "1435")
    ck("区未打印 → NO_ACTION(不追)", r3["candidates"][0]["verdict"] == "NO_ACTION")
    r4 = decide([sig], {}, "20260715", "1435")
    ck("行情缺失 → DATA_BLOCKED", len(r4["data_blocked"]) == 1)
    import tempfile
    global OUT
    old = OUT
    with tempfile.TemporaryDirectory() as td:
        OUT = os.path.join(td, "eod.json")
        n1 = append_log(r)
        n2 = append_log(r)
        ck("append-only + 当日去重", n1 == 1 and n2 == 0)
    OUT = old
    passed = sum(1 for _, c in ok if c)
    print(f"run_eod_decision selftest: {passed}/{len(ok)}")
    return passed == len(ok)


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    import datetime
    now = datetime.datetime.now()
    hhmm = now.strftime("%H%M")
    if not in_window(hhmm) and "--force" not in sys.argv:
        print(f"OFF_WINDOW: 现在 {hhmm},决策窗 {WIN_LO}-{WIN_HI};不产出。")
        return
    sys.path.insert(0, HERE)
    import fund_source as fs
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("DATA_BLOCKED: NO TUSHARE_TOKEN")
        sys.exit(1)
    signals = _load(os.path.join(HERE, "paper_signal_log.json"), [])
    tickers = sorted({s["ticker"] for s in signals
                      if s.get("setup_type") == "execution_gate"
                      and not s.get("official_sample")
                      and s.get("outcome_status", "pending") == "pending"
                      and "." in (s.get("ticker") or "")})
    if not tickers:
        print("今日无活跃 execution_gate 信号;窗内无事。")
        return
    rows = fs.tushare_realtime_quotes(tickers, src="sina")
    quotes = {}
    for r in rows:
        t = r.get("ticker") or ""
        full = t if "." in t else next((x for x in tickers if x.startswith(t)), t)
        quotes[full] = {"price": r.get("price"), "low": r.get("low"), "high": r.get("high")}
    result = decide(signals, quotes, now.strftime("%Y%m%d"), hhmm)
    n = append_log(result)
    print(f"## 尾盘决策窗 {hhmm}(新增 {n} 条)")
    for c in result["candidates"]:
        print(f"  {c['name']} → {c['verdict']} — {c['why']}")
    for b in result["data_blocked"]:
        print(f"  ⛔ {b['ticker']} {b['why']}")
    print("不是买卖指令；研究信号，human executes.")


if __name__ == "__main__":
    main()
