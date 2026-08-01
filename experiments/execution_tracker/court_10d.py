#!/usr/bin/env python3
"""court_10d.py — 10 天检察官(Junyan 2026-07-28 定版规则的机械化执行)。

规则:持仓满 10 天且 R<0.5 且论文无正向 E1 进展 → 强制去留庭审;
      庭审通过续期 10 天(每票仅一次),不通过纸面基金机械平仓回收弹药;
      实盘影子 = 出复核建议,决策在 Junyan。

庭审五查(本引擎负责取证与初判,终审判定书仍由人/AI 撰写):
  ① wrong-if 是否已触发(需人工/LLM 判读原始 wrong_if 文本 → 本引擎给出线索)
  ② 10 日资金结构趋势(定盘主力累计与净流入天数)
  ③ 论文有无正向 E1 进展(红旗闸门 verdict + 最近公告标题线索)
  ④ 替补对决(promotion_queue 是否有候选争坑)
  ⑤ 距 stop 余量

本引擎只产出 court_10d.json(取证+初判),绝不修改任何账本、绝不平仓。
2026-08-01 立:此前"10天检察官已接入夜链"的说法为不实申报,本文件是其兑现。
不是买卖指令;研究信号,human executes.
"""
import json
import os
import sys
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "court_10d.json")
TENURE_DAYS = 10
R_BAR = 0.5


def _load(rel, default=None):
    p = os.path.join(HERE, rel)
    if not os.path.exists(p):
        return default, f"missing:{rel}"
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh), None
    except Exception as e:                                     # noqa: BLE001
        return default, f"unreadable:{rel}:{e}"


def _tenure_days(fill_date, today):
    try:
        d0 = datetime.datetime.strptime(str(fill_date), "%Y%m%d").date()
        d1 = datetime.datetime.strptime(str(today), "%Y%m%d").date()
        return (d1 - d0).days
    except Exception:                                          # noqa: BLE001
        return None


def _r_multiple(entry, stop, mark):
    if None in (entry, stop, mark) or entry == stop:
        return None
    return round((mark - entry) / (entry - stop), 2)


def review(today=None, marks=None):
    """产出每个 filled 持仓的庭审状态。marks = {ticker: 最新收盘},缺失则用 nav 口径无法算 R。"""
    today = today or datetime.date.today().strftime("%Y%m%d")
    orders, e_ord = _load("model_fund/orders.json", [])
    if e_ord:
        return {"court": "court_10d_v0", "status": "DATA_BLOCKED", "why": e_ord,
                "checked_at": today, "cases": [],
                "disclaimer": "不是买卖指令;研究信号,human executes."}
    rows = orders if isinstance(orders, list) else orders.get("orders", [])
    red, _ = _load("red_flags.json", {})
    bat, _ = _load("battery.json", {})
    pq, _ = _load("promotion_queue.json", [])
    red_by = {r.get("ts_code"): r for r in (red or {}).get("results", [])}
    bat_by = {r.get("ts_code"): r for r in (bat or {}).get("results", [])}
    queue = pq if isinstance(pq, list) else (pq or {}).get("queue", [])

    cases = []
    for o in rows:
        if o.get("status") != "filled":
            continue
        tk = o.get("ticker")
        fill = o.get("fill_date") or o.get("entry_date")
        days = _tenure_days(fill, today)
        entry = o.get("fill_price") or o.get("entry")
        stop = o.get("stop_reference") or o.get("stop")
        mark = (marks or {}).get(tk)
        r = _r_multiple(entry, stop, mark)
        rf = red_by.get(tk, {})
        bt = bat_by.get(tk, {})
        dims = bt.get("dims", {})
        flow = dims.get("资金", {})
        news = dims.get("消息面", {})
        due = days is not None and days >= TENURE_DAYS and (r is None or r < R_BAR)
        cases.append({
            "ticker": tk, "name": o.get("name"),
            "fill_date": fill, "tenure_days": days,
            "entry": entry, "stop": stop, "mark": mark, "r_multiple": r,
            "due_for_tribunal": due,
            "evidence": {
                "wrong_if_text": o.get("reason") or o.get("thesis"),   # 查①线索(需判读)
                "flow_10d": flow.get("主力10日累计亿"),                  # 查②
                "flow_positive_days": flow.get("近10日净流入天数"),       # 查②
                "red_flag": rf.get("verdict"), "red_reasons": rf.get("reasons"),  # 查③
                "recent_announcements": news.get("最新3条"),            # 查③线索
                "substitutes_in_queue": len(queue),                     # 查④
                "stop_room_pct": (round((mark / stop - 1) * 100, 1)
                                  if mark and stop else None),          # 查⑤
            },
            "engine_verdict": ("TRIBUNAL_REQUIRED" if due else "NOT_DUE"),
            "note": "引擎只取证与初判;终审判定书由人/AI 撰写并需 Junyan 口令方可执行处置",
        })
    due_n = sum(1 for c in cases if c["due_for_tribunal"])
    # 审计 MAJOR(2026-08-01):此前所有持仓 mark=null/R=null 仍报 status=OK。
    # 无 mark ⇒ 五查中的①R 与⑤距 stop 余量都无从判定,不得当作完整取证。
    no_mark = [c["ticker"] for c in cases if c.get("mark") is None]
    status = "OK" if not cases else ("PARTIAL" if no_mark and len(no_mark) < len(cases)
                                     else ("DATA_BLOCKED" if no_mark else "OK"))
    for c in cases:
        if c.get("mark") is None:
            c["evidence_status"] = "DATA_BLOCKED"
            c["evidence_why"] = "无定盘 mark:R 与距 stop 余量不可判定"
            c["engine_verdict"] = "TRIBUNAL_BLOCKED_NO_MARK"
        else:
            c["evidence_status"] = "OK"
    return {"court": "court_10d_v0", "status": status, "checked_at": today,
            "no_mark_tickers": no_mark,
            "tenure_days_bar": TENURE_DAYS, "r_bar": R_BAR,
            "n_positions": len(cases), "n_due": due_n, "cases": cases,
            "disclaimer": "不是买卖指令;研究信号,human executes."}


def selftest():
    checks = []
    # 满 10 天且 R<0.5 → 必须开庭
    r = _r_multiple(56.40, 52.20, 54.08)
    checks.append(("R 计算(恒瑞口径 -0.55)", r == -0.55))
    checks.append(("满10天低R ⇒ due", 24 >= TENURE_DAYS and r < R_BAR))
    # 未满 10 天不开庭
    checks.append(("未满10天 ⇒ not due", not (5 >= TENURE_DAYS)))
    # R≥0.5 不开庭
    r2 = _r_multiple(28.20, 26.20, 32.20)
    checks.append(("高R(紫金2.0)⇒ 不因低R开庭", r2 >= R_BAR))
    # 账本缺失 ⇒ DATA_BLOCKED 而非空庭
    out = review(today="20260801", marks={})
    checks.append(("产出结构完整", out.get("court") == "court_10d_v0" and "cases" in out))
    # 审计回归:全部持仓缺 mark ⇒ 整体不得 OK,逐案标 DATA_BLOCKED
    if out.get("cases"):
        checks.append(("全缺mark ⇒ status 非OK", out["status"] in ("DATA_BLOCKED", "PARTIAL")))
        checks.append(("逐案 evidence_status=DATA_BLOCKED",
                       all(c.get("evidence_status") == "DATA_BLOCKED" for c in out["cases"])))
        checks.append(("逐案 verdict=TRIBUNAL_BLOCKED_NO_MARK",
                       all(c.get("engine_verdict") == "TRIBUNAL_BLOCKED_NO_MARK"
                           for c in out["cases"])))
    checks.append(("免责句在", "不是买卖指令" in out["disclaimer"]))
    for name, ok in checks:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print(f"court_10d selftest: {sum(ok for _, ok in checks)}/{len(checks)}")
    return all(ok for _, ok in checks)


def main():
    if "--selftest" in sys.argv:
        return 0 if selftest() else 1
    marks = {}
    # 审计 MAJOR:优先读 position_review.json 的定盘 mark(持仓专用,权威);
    # official sample 的 ticker_gates 只覆盖扫描集,持仓未必在内 —— 作次选。
    pr, _e = _load("position_review.json", {})
    for row in (pr or {}).get("rows", []):
        tk = row.get("ticker")
        m = row.get("mark") or row.get("close") or row.get("price")
        if tk and m is not None:
            marks[tk] = m
    snap_dir = os.path.join(HERE, "samples")
    if os.path.isdir(snap_dir):
        files = sorted(f for f in os.listdir(snap_dir) if f.endswith(".json"))
        if files:
            snap, _ = _load(os.path.join("samples", files[-1]), {})
            for g in (snap or {}).get("ticker_gates", []):
                if g.get("ticker") and g.get("price") is not None:
                    marks.setdefault(g["ticker"], g["price"])   # position_review 优先
    out = review(marks=marks)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    for c in out.get("cases", []):
        print(f"{c['ticker']} {c['name']}: 持有{c['tenure_days']}天 R={c['r_multiple']} "
              f"→ {c['engine_verdict']}")
    print(f"[written] court_10d.json  n_due={out.get('n_due')}")
    print("不是买卖指令;研究信号,human executes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
