#!/usr/bin/env python3
"""
court_wakeup.py — Registered Court 唤醒机制 v0

病根(2026-07-15 大参林复盘):在册 thesis 是死水——大参林 5 月入庭
(R/R 1.5:1 WATCH)后 +30% 无人复核。本机制每日扫描 registered_court.json,
触发任一条件即产出 WAKE_RESCAN 复核单(送人审,不改 posture、不选股):

  W1 价格移动:20 日涨跌幅绝对值 >= 15%
  W2 板块唤醒:所属板块在 rotation_panel.json 中 streak >= 3
  W3 checkpoint 到期:任一 checkpoint 日期 <= 今天且未标记 done

不是买卖指令；研究信号，human executes。
"""

import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
COURT = os.path.join(HERE, "registered_court.json")
PANEL = os.path.join(HERE, "rotation_panel.json")
OUT = os.path.join(HERE, "court_wakeup.json")

MOVE_BAR = 0.15


def _api(name, token, **params):
    body = json.dumps({"api_name": name, "token": token,
                       "params": params, "fields": ""}).encode()
    req = urllib.request.Request("https://api.tushare.pro", body,
                                 {"Content-Type": "application/json"})
    for _ in range(4):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=30))
            if r.get("code") == 0:
                d = r["data"]
                return [dict(zip(d["fields"], row)) for row in d["items"]]
        except Exception:                              # noqa: BLE001
            pass
        time.sleep(1.5)
    return []


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def evaluate(court, moves20, panel_inflow_sectors, today):
    """纯函数,离线可测。
    court: [{ticker,name,sector_key,thesis_oneline,checkpoints:[{date,done}]}]
    moves20: {ticker: pct(float, 0.30 = +30%)} — None 值代表数据缺失
    panel_inflow_sectors: {sector_key,...}(streak>=3)
    """
    wakes, blocked = [], []
    for e in court:
        t = e["ticker"]
        reasons = []
        mv = moves20.get(t)
        if mv is None:
            blocked.append({"ticker": t, "name": e.get("name"),
                            "why": "DATA_BLOCKED: 20日行情缺失"})
        elif abs(mv) >= MOVE_BAR:
            reasons.append(f"W1 价格移动 {mv*100:+.1f}%(|x|>={MOVE_BAR*100:.0f}%)")
        if e.get("sector_key") in panel_inflow_sectors:
            reasons.append(f"W2 板块唤醒:{e['sector_key']} streak>=3")
        for cp in e.get("checkpoints", []):
            if not cp.get("done") and cp.get("date", "99999999") <= today:
                reasons.append(f"W3 checkpoint 到期:{cp['date']} {cp.get('what','')}")
        if reasons:
            wakes.append({"ticker": t, "name": e.get("name"),
                          "thesis": e.get("thesis_oneline", ""),
                          "reasons": reasons,
                          "action": "WAKE_RESCAN(送人审复核,不改posture)"})
    return {"as_of": today, "court_size": len(court),
            "wakes": wakes, "data_blocked": blocked,
            "note": "唤醒=复核请求,非信号非posture。不是买卖指令。"}


def run(token, today):
    court = _load(COURT, [])
    if not court:
        print(f"DATA_BLOCKED: {COURT} 缺失或为空(先播种在册名单)")
        return None
    panel = _load(PANEL, {})
    inflow = {r["sector"] for r in panel.get("inflow_cont", [])}
    # sector_key 用包含匹配(court 里存粗粒度键,面板是东财名)
    def sector_hit(key):
        return any(key in s or s in key for s in inflow) if key else False
    moves = {}
    for e in court:
        rows = _api("daily", token, ts_code=e["ticker"],
                    start_date="20260601", end_date=today)
        rows = sorted(rows, key=lambda r: r["trade_date"])
        closes = [float(r["close"]) for r in rows if r.get("close")]
        moves[e["ticker"]] = (closes[-1] / closes[-21] - 1) if len(closes) >= 21 else None
        time.sleep(0.2)
    hit_sectors = {e.get("sector_key") for e in court if sector_hit(e.get("sector_key"))}
    result = evaluate(court, moves, hit_sectors, today)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(f"## Court 唤醒扫描({today} · 在册 {result['court_size']})")
    for w in result["wakes"]:
        print(f"  ⏰ {w['name']} {w['ticker']} — {' | '.join(w['reasons'])}")
    if not result["wakes"]:
        print("  (今日无唤醒)")
    for b in result["data_blocked"]:
        print(f"  ⛔ {b['name']}: {b['why']}")
    print(f"[written] {OUT}\n不是买卖指令；研究信号，human executes.")
    return result


def selftest():
    ok = []

    def ck(name, cond):
        ok.append((name, bool(cond)))
        print(("  ✓ " if cond else "  ✗ ") + name)

    court = [
        {"ticker": "603233.SH", "name": "大参林", "sector_key": "医药商业",
         "thesis_oneline": "药房集中度提升", "checkpoints": []},
        {"ticker": "002594.SZ", "name": "比亚迪", "sector_key": "汽车",
         "thesis_oneline": "出海GM", "checkpoints": [{"date": "20260710", "what": "30d读数", "done": False}]},
        {"ticker": "300308.SZ", "name": "中际旭创", "sector_key": "算力",
         "thesis_oneline": "1.6T", "checkpoints": [{"date": "20260830", "what": "分部", "done": False}]},
        {"ticker": "688120.SH", "name": "华海清科", "sector_key": "半导体设备",
         "thesis_oneline": "CMP", "checkpoints": [{"date": "20260712", "what": "batch-1", "done": True}]},
        {"ticker": "600276.SH", "name": "恒瑞", "sector_key": "创新药",
         "thesis_oneline": "license-out", "checkpoints": []},
    ]
    moves = {"603233.SH": 0.309, "002594.SZ": -0.02, "300308.SZ": 0.01,
             "688120.SH": None, "600276.SH": 0.05}
    r = evaluate(court, moves, {"医药商业"}, "20260715")
    by = {w["ticker"]: w for w in r["wakes"]}
    ck("大参林 W1+W2 双触发", "603233.SH" in by and len(by["603233.SH"]["reasons"]) == 2)
    ck("BYD checkpoint 过期 W3 触发", "002594.SZ" in by
       and any("W3" in x for x in by["002594.SZ"]["reasons"]))
    ck("旭创未到期不唤醒", "300308.SZ" not in by)
    ck("done checkpoint 不重复唤醒", "688120.SH" not in by)
    ck("行情缺失走 DATA_BLOCKED 不静默", any(b["ticker"] == "688120.SH"
                                            for b in r["data_blocked"]))
    ck("恒瑞 5% 移动不达 15% bar 不唤醒", "600276.SH" not in by)
    ck("唤醒动作是复核不是posture", all("送人审" in w["action"] for w in r["wakes"]))
    passed = sum(1 for _, c in ok if c)
    print(f"court_wakeup selftest: {passed}/{len(ok)}")
    return passed == len(ok)


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("DATA_BLOCKED: NO TUSHARE_TOKEN")
        sys.exit(1)
    import datetime
    run(token, datetime.date.today().strftime("%Y%m%d"))


if __name__ == "__main__":
    main()
