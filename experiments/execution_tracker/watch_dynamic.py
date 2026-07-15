#!/usr/bin/env python3
"""
watch_dynamic.py — P4 动态盯盘名单(watchlist 不再静态)

名单来源(去重,上限 20,超限按优先级截断并显式声明):
  1 基金持仓/挂单(最高优先,永不截断)
  2 pending 判分中的个股研究信号(execution_gate/risk_warning/distribution_warning)
  3 Registered Court 在册
  4 动量雷达 TOP5(momentum_prefilter.json)
输出 watch_dynamic.json;watchtower 若见此文件则用之,否则回退硬编码名单。

不是买卖指令；研究信号，human executes。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "watch_dynamic.json")
CAP = 20


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def build(orders, signals, court, momentum, cap=CAP):
    """纯函数。返回 (watch_list, truncated_list)。"""
    seen, out = set(), []

    def add(ticker, name, why, prio):
        if not ticker or "." not in ticker or ticker.startswith("SECTOR"):
            return
        if ticker in seen:
            return
        seen.add(ticker)
        out.append({"ticker": ticker, "name": name or ticker, "why": why, "prio": prio})

    for o in orders:
        if o.get("status") in ("filled", "pending"):
            add(o["ticker"], o.get("name"), f"基金{o['status']}", 1)
    for s in signals:
        if (not s.get("official_sample")
                and s.get("outcome_status", "pending") == "pending"
                and s.get("setup_type") in ("execution_gate", "risk_warning",
                                            "distribution_warning")):
            add(s.get("ticker"), s.get("name"), f"信号{s.get('signal_id','')[:6]}", 2)
    for e in court:
        add(e.get("ticker"), e.get("name"), "在册thesis", 3)
    for c in (momentum.get("candidates") or [])[:5]:
        add(c.get("ts_code"), c.get("name"), f"动量雷达{c.get('ret10')}%", 4)

    out.sort(key=lambda r: r["prio"])
    kept, cut = out[:cap], out[cap:]
    return kept, cut


def selftest():
    ok = []

    def ck(name, cond):
        ok.append((name, bool(cond)))
        print(("  ✓ " if cond else "  ✗ ") + name)

    orders = [{"ticker": "600276.SH", "name": "恒瑞", "status": "filled"},
              {"ticker": "002714.SZ", "name": "牧原", "status": "pending"},
              {"ticker": "603259.SH", "name": "药明", "status": "cancelled"}]
    signals = [
        {"ticker": "002463.SZ", "name": "沪电", "setup_type": "execution_gate",
         "outcome_status": "pending", "signal_id": "a2a40a749c6b"},
        {"ticker": "SECTOR.MIL", "name": "军工", "setup_type": "rotation_hypothesis",
         "outcome_status": "pending", "signal_id": "260ac4"},
        {"ticker": "002185.SZ", "name": "华天", "setup_type": "execution_gate",
         "outcome_status": "invalidated", "signal_id": "7a45c7"},
        {"ticker": "600276.SH", "name": "恒瑞", "setup_type": "risk_warning",
         "outcome_status": "pending", "signal_id": "dup"},
    ]
    court = [{"ticker": "603233.SH", "name": "大参林"},
             {"ticker": "002594.SZ", "name": "比亚迪"}]
    momentum = {"candidates": [{"ts_code": f"30000{i}.SZ", "name": f"M{i}", "ret10": 20 + i}
                               for i in range(8)]}
    kept, cut = build(orders, signals, court, momentum, cap=9)
    tick = [k["ticker"] for k in kept]
    ck("持仓+挂单在列,撤单不在", "600276.SH" in tick and "002714.SZ" in tick
       and "603259.SH" not in tick)
    ck("pending 信号在列(沪电)", "002463.SZ" in tick)
    ck("已 invalidated 信号不在(华天)", "002185.SZ" not in tick)
    ck("SECTOR.* 排除", all(not t.startswith("SECTOR") for t in tick))
    ck("去重(恒瑞只一条)", tick.count("600276.SH") == 1)
    ck("court 在列", "603233.SH" in tick)
    ck("动量只取TOP5且被cap截断可见", len(kept) == 9 and len(cut) >= 1)
    ck("持仓优先级排最前", kept[0]["prio"] == 1)
    passed = sum(1 for _, c in ok if c)
    print(f"watch_dynamic selftest: {passed}/{len(ok)}")
    return passed == len(ok)


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    orders = _load(os.path.join(HERE, "model_fund", "orders.json"), [])
    signals = _load(os.path.join(HERE, "paper_signal_log.json"), [])
    court = _load(os.path.join(HERE, "registered_court.json"), [])
    momentum = _load(os.path.join(HERE, "momentum_prefilter.json"), {})
    if not orders and not signals:
        print("DATA_BLOCKED: 账本为空,无法构建名单")
        sys.exit(1)
    kept, cut = build(orders, signals, court, momentum)
    import datetime
    payload = {"generated_at": datetime.datetime.now().strftime("%Y%m%d %H:%M"),
               "watch": kept,
               "truncated": [c["ticker"] for c in cut],
               "note": "动态盯盘名单;来源=持仓/信号/在册/动量雷达。不是买卖指令。"}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print(f"## 动态名单({len(kept)} 名,截断 {len(cut)})")
    for k in kept:
        print(f"  {k['ticker']} {k['name']} — {k['why']}")
    if cut:
        print(f"  [显式截断] {', '.join(c['ticker'] for c in cut)}")
    print(f"[written] {OUT}")


if __name__ == "__main__":
    main()
