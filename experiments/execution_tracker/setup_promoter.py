#!/usr/bin/env python3
"""
setup_promoter.py — P3 晋级桥(定盘后跑;只出 PROMOTION_REVIEW,不注册不成交)

对每条 pending 判分的 execution_gate 个股信号,机械核对三条件门 + 两票制,
产出晋级复核单写入 promotion_queue.json。**注册动作留给人审后的结算流程**——
本模块消灭的是"信号注册了、没人升级"的缝隙,不是人审本身。

三条件门(v1.1):
  G1 regime:最新官方样本 market_state ∈ {RISK_ON, WEAK_REPAIR}
  G2 板块连续:信号 sector 在轮动面板 streak >= 2(WARMING 及以上)
  G3 触发区打印:当日 bar 触及 trigger 区且收盘未破 invalidation 价

不是买卖指令；研究信号，human executes。
"""

import json
import os
import re
import sys

import sector_keys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "promotion_queue.json")
RISK_PCT = 0.0075          # 提案风险预算 0.75% NAV [unvalidated intuition]


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _zone_from_trigger(text):
    """从 trigger_condition 里抽第一个 'a-b' 或 'x±y' 价区;抽不出→None(人审)。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", text or "")
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return (min(lo, hi), max(lo, hi))
    m = re.search(r"(\d+(?:\.\d+)?)\s*±\s*(\d+(?:\.\d+)?)", text or "")
    if m:
        c, d = float(m.group(1)), float(m.group(2))
        return (c - d, c + d)
    return None


def _stop_from_invalidation(text):
    m = re.search(r"收盘\s*[<＜]\s*(\d+(?:\.\d+)?)", text or "")
    return float(m.group(1)) if m else None


def evaluate(signals, market_state, sector_streaks, bars_by_ticker, nav):
    """纯函数。bars_by_ticker: {ticker: {'low','high','close'}} 当日定盘 bar。"""
    queue, blocked = [], []
    for s in signals:
        if (s.get("official_sample") or s.get("setup_type") != "execution_gate"
                or s.get("outcome_status", "pending") != "pending"
                or "." not in (s.get("ticker") or "")):
            continue
        t = s["ticker"]
        checks = {}
        checks["G1_regime"] = market_state in ("RISK_ON", "WEAK_REPAIR")
        streak, matched_sector = sector_keys.best_streak(s.get("sector"), sector_streaks)
        checks["G2_sector_streak>=2"] = streak >= 2
        zone = _zone_from_trigger(s.get("trigger_condition"))
        stop = _stop_from_invalidation(s.get("invalidation"))
        bar = bars_by_ticker.get(t)
        if bar is None:
            blocked.append({"ticker": t, "why": "DATA_BLOCKED: 当日bar缺失"})
            continue
        if zone is None or stop is None:
            queue.append({"ticker": t, "name": s.get("name"),
                          "signal_id": s.get("signal_id"),
                          "verdict": "MANUAL_REVIEW",
                          "why": "trigger/invalidation 无法机械解析,送人审",
                          "matched_sector": matched_sector,
                          "checks": checks})
            continue
        touched = bar["low"] <= zone[1] and bar["high"] >= zone[0]
        held = bar["close"] > stop
        checks["G3_zone_printed_and_held"] = bool(touched and held)
        ready = all(checks.values())
        entry_ref = round((zone[0] + zone[1]) / 2, 2)
        shares = int(nav * RISK_PCT / max(entry_ref - stop, 1e-9) // 100 * 100) if ready else 0
        queue.append({"ticker": t, "name": s.get("name"), "signal_id": s.get("signal_id"),
                      "verdict": "PROMOTE_REVIEW_READY" if ready else "NOT_READY",
                      "matched_sector": matched_sector,
                      "checks": checks,
                      "proposal": ({"entry_review": entry_ref, "stop": stop,
                                    "shares": shares, "risk_pct_nav": RISK_PCT,
                                    "note": "提案仅供人审;注册走结算流程"} if ready else None)})
    return {"market_state": market_state, "queue": queue, "data_blocked": blocked,
            "note": "晋级复核单;不注册不成交。不是买卖指令。"}


def selftest():
    ok = []

    def ck(name, cond):
        ok.append((name, bool(cond)))
        print(("  ✓ " if cond else "  ✗ ") + name)

    sig = {"ticker": "002463.SZ", "name": "沪电", "setup_type": "execution_gate",
           "outcome_status": "pending", "official_sample": False, "sector": "PCB/AI硬件",
           "signal_id": "a2a40a", "trigger_condition": "回踩127-130承接",
           "invalidation": "收盘<123(swing低)或回踩日主力净流出>5亿"}
    sig_sector = dict(sig, ticker="SECTOR.X", signal_id="x")
    sig_fuzzy = dict(sig, signal_id="fz", trigger_condition="盘感觉不错就进")
    bars = {"002463.SZ": {"low": 128.0, "high": 136.0, "close": 131.0}}
    r = evaluate([sig, sig_sector, sig_fuzzy], "RISK_ON", {"印制电路板": 3, "PCB": 3},
                 bars, nav=1_000_000)
    by = {q["signal_id"]: q for q in r["queue"]}
    ck("三门全过 → READY + 提案", by["a2a40a"]["verdict"] == "PROMOTE_REVIEW_READY"
       and by["a2a40a"]["proposal"]["shares"] > 0)
    ck("提案股数为整百", by["a2a40a"]["proposal"]["shares"] % 100 == 0)
    ck("板块级信号不进桥", "x" not in by)
    ck("模糊 trigger → MANUAL_REVIEW 不硬解析", by["fz"]["verdict"] == "MANUAL_REVIEW")
    r2 = evaluate([sig], "RISK_OFF", {"PCB": 3}, bars, 1_000_000)
    ck("G1 regime 不过 → NOT_READY", r2["queue"][0]["verdict"] == "NOT_READY")
    r3 = evaluate([sig], "RISK_ON", {"PCB": 1}, bars, 1_000_000)
    ck("G2 streak<2 → NOT_READY", r3["queue"][0]["verdict"] == "NOT_READY")
    r4 = evaluate([sig], "RISK_ON", {"PCB": 3},
                  {"002463.SZ": {"low": 131, "high": 140, "close": 138}}, 1_000_000)
    ck("G3 区未打印 → NOT_READY", r4["queue"][0]["verdict"] == "NOT_READY")
    r5 = evaluate([sig], "RISK_ON", {"PCB": 3}, {}, 1_000_000)
    ck("bar 缺失 → DATA_BLOCKED", len(r5["data_blocked"]) == 1)
    passed = sum(1 for _, c in ok if c)
    print(f"setup_promoter selftest: {passed}/{len(ok)}")
    return passed == len(ok)


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    sys.path.insert(0, HERE)
    import glob
    import paper_portfolio as pp
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("DATA_BLOCKED: NO TUSHARE_TOKEN")
        sys.exit(1)
    samples = sorted(glob.glob(os.path.join(HERE, "samples", "*.json")))
    if not samples:
        print("DATA_BLOCKED: 无官方样本")
        sys.exit(1)
    snap = _load(samples[-1], {})
    market_state = (snap.get("market_gate") or {}).get("state", "?")
    panel = _load(os.path.join(HERE, "rotation_panel.json"), {})
    streaks = {r["sector"]: r["streak"] for r in
               panel.get("inflow_cont", []) + panel.get("warming", [])}
    signals = _load(os.path.join(HERE, "paper_signal_log.json"), [])
    fund = _load(os.path.join(HERE, "model_fund", "fund.json"), {})
    navh = _load(os.path.join(HERE, "model_fund", "nav_history.json"), [])
    nav = navh[-1]["nav"] if navh else fund.get("initial_capital", 1_000_000)
    bars = {}
    for s in signals:
        t = s.get("ticker") or ""
        if (s.get("setup_type") == "execution_gate" and "." in t
                and s.get("outcome_status", "pending") == "pending"
                and not s.get("official_sample")):
            ser = pp.qfq_ohlc_series(t, token, "20260701")
            if ser:
                b = ser[-1]
                bars[t] = {"low": b["low"], "high": b["high"], "close": b["close"]}
    result = evaluate(signals, market_state, streaks, bars, nav)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(f"## 晋级桥(regime={market_state})")
    for q in result["queue"]:
        print(f"  {q['name']} {q['verdict']} checks={q['checks']}")
        if q.get("proposal"):
            print(f"    提案(人审): entry~{q['proposal']['entry_review']} "
                  f"stop {q['proposal']['stop']} {q['proposal']['shares']}股")
    for b in result["data_blocked"]:
        print(f"  ⛔ {b['ticker']} {b['why']}")
    print(f"[written] {OUT}\n不是买卖指令；研究信号，human executes.")


if __name__ == "__main__":
    main()
