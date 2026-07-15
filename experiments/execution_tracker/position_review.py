#!/usr/bin/env python3
"""
position_review.py — P1 每日仓位纪律引擎 + P2 R 阶梯(paper/review 输出)

每晚定盘后对基金账本逐仓复审,输出 review(不自动动仓;--apply-tighten 仅执行
"只紧不松"的保本位上移,这是预批准的安全方向):

  持仓:浮动% · 权重% · R 倍数 · stop 距离 · R 阶梯建议
       R>=1 → RECOMMEND_BREAKEVEN(stop 上移至成本,tighten-only)
       R>=2 → RECOMMEND_HALF_EXIT_REVIEW(减半复核 + 余仓结构位跟踪)
  挂单:账龄 >= 5 自然日 → STALE_REVIEW(过期复核)
  组合:现金% · 主题敞口 vs 40% 上限 · 单β标记 · 风险 flag

R 阶梯参数 [unvalidated intuition],paper 先行,30 样本后再谈校准。
不是买卖指令；研究信号，human executes。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FUND_DIR = os.path.join(HERE, "model_fund")
OUT = os.path.join(HERE, "position_review.json")

THEME_CAP = 0.40
CASH_FLOOR = 0.20
STALE_DAYS = 5


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _daydiff(d1, d2):
    """YYYYMMDD strings -> calendar days (d2 - d1)."""
    from datetime import date
    a = date(int(d1[:4]), int(d1[4:6]), int(d1[6:8]))
    b = date(int(d2[:4]), int(d2[4:6]), int(d2[6:8]))
    return (b - a).days


def review(fund, orders, marks, today):
    """纯函数。marks: {ticker: settle_close};缺 mark => DATA_BLOCKED 行。"""
    rows, flags, blocked = [], [], []
    nav_est = fund.get("cash", 0.0)
    for o in orders:
        if o.get("status") == "filled" and o["ticker"] in marks:
            nav_est += o["shares"] * marks[o["ticker"]]
    theme_val = {}
    for o in orders:
        st = o.get("status")
        t = o["ticker"]
        if st == "filled":
            m = marks.get(t)
            if m is None:
                blocked.append({"ticker": t, "why": "DATA_BLOCKED: 无定盘 mark"})
                continue
            fp, stop = o["fill_price"], o["stop_reference"]
            risk_ps = fp - stop
            r_mult = (m - fp) / risk_ps if risk_ps > 0 else 0.0
            ladder = None
            if r_mult >= 2:
                ladder = "RECOMMEND_HALF_EXIT_REVIEW(>=2R:减半复核+余仓结构位跟踪)"
            elif r_mult >= 1:
                ladder = "RECOMMEND_BREAKEVEN(>=1R:stop上移至成本,tighten-only)"
            w = o["shares"] * m / nav_est if nav_est else 0
            theme_val[o.get("theme", "?")] = theme_val.get(o.get("theme", "?"), 0) + o["shares"] * m
            rows.append({"ticker": t, "name": o.get("name"), "kind": "filled",
                         "pnl_pct": round((m / fp - 1) * 100, 2),
                         "weight_pct": round(w * 100, 1),
                         "r_mult": round(r_mult, 2),
                         "stop": stop, "stop_dist_pct": round((stop / m - 1) * 100, 2),
                         "ladder": ladder,
                         "wrong_if": o.get("invalid_if") or o.get("reason", "")[:60]})
        elif st == "pending":
            age = _daydiff(str(o.get("registered_at", today))[:8], today)
            rows.append({"ticker": t, "name": o.get("name"), "kind": "pending",
                         "entry": o.get("entry_review_price"), "age_days": age,
                         "stale": age >= STALE_DAYS,
                         "ladder": "STALE_REVIEW(挂单过期复核)" if age >= STALE_DAYS else None})
            if age >= STALE_DAYS:
                flags.append(f"STALE_PENDING: {o.get('name')} 挂单 {age} 天未触发 → 复核")
    cash_pct = fund.get("cash", 0) / nav_est if nav_est else 1.0
    if cash_pct < CASH_FLOOR:
        flags.append(f"CASH_FLOOR: 现金 {cash_pct*100:.0f}% < {CASH_FLOOR*100:.0f}%")
    for th, v in theme_val.items():
        if nav_est and v / nav_est > THEME_CAP:
            flags.append(f"THEME_CAP: {th} 敞口 {v/nav_est*100:.0f}% > {THEME_CAP*100:.0f}%")
    themes = [th for th in theme_val]
    if len([r for r in rows if r["kind"] == "filled"]) >= 2 and len(set(themes)) == 1:
        flags.append("SINGLE_BETA: 全部持仓同主题")
    return {"as_of": today, "nav_est": round(nav_est, 0),
            "cash_pct": round(cash_pct * 100, 1), "rows": rows,
            "flags": flags, "data_blocked": blocked,
            "note": "review输出;--apply-tighten 仅执行tighten-only保本位。不是买卖指令。"}


def apply_tighten(result, orders, decision_log, today):
    """R>=1 的保本位建议 → 实际执行 tighten(只紧不松,paper 账本内)。"""
    import model_paper_fund as mpf
    done = []
    for r in result["rows"]:
        if r["kind"] == "filled" and r.get("ladder", "") and "BREAKEVEN" in (r["ladder"] or ""):
            o = next(x for x in orders if x["ticker"] == r["ticker"] and x["status"] == "filled")
            okk, msg = mpf.tighten_stop(orders, decision_log, r["ticker"],
                                        o["fill_price"], today,
                                        "R>=1 ladder: stop→breakeven (position_review)")
            done.append(f"{r['name']}: {msg}")
    return done


def render(res):
    L = [f"## 仓位复审({res['as_of']} · NAV≈¥{res['nav_est']:,.0f} · 现金 {res['cash_pct']}%)", ""]
    for r in res["rows"]:
        if r["kind"] == "filled":
            L.append(f"- {r['name']} 浮{r['pnl_pct']:+.2f}% 权重{r['weight_pct']}% "
                     f"R={r['r_mult']} stop距离{r['stop_dist_pct']}% "
                     f"{'→ ' + r['ladder'] if r['ladder'] else ''}")
        else:
            L.append(f"- {r['name']} [挂单] 账龄{r['age_days']}天"
                     f"{' → ' + r['ladder'] if r['ladder'] else ''}")
    for f in res["flags"]:
        L.append(f"- ⚠ {f}")
    for b in res["data_blocked"]:
        L.append(f"- ⛔ {b['ticker']} {b['why']}")
    L.append("\n不是买卖指令；研究信号，human executes.")
    return "\n".join(L)


def selftest():
    ok = []

    def ck(name, cond):
        ok.append((name, bool(cond)))
        print(("  ✓ " if cond else "  ✗ ") + name)

    fund = {"cash": 200_000.0}   # nav≈459k, 药主题 230k ≈ 50% > 40% cap
    orders = [
        {"ticker": "A.SH", "name": "一倍R", "status": "filled", "fill_price": 100.0,
         "stop_reference": 90.0, "shares": 1000, "theme": "药", "registered_at": "20260701",
         "invalid_if": "wrongif-A"},
        {"ticker": "B.SH", "name": "两倍R", "status": "filled", "fill_price": 50.0,
         "stop_reference": 45.0, "shares": 2000, "theme": "药", "registered_at": "20260701"},
        {"ticker": "C.SH", "name": "水下", "status": "filled", "fill_price": 30.0,
         "stop_reference": 27.0, "shares": 1000, "theme": "金", "registered_at": "20260701"},
        {"ticker": "D.SH", "name": "老挂单", "status": "pending", "entry_review_price": 39.1,
         "shares": 0, "theme": "猪", "registered_at": "20260707"},
        {"ticker": "E.SH", "name": "无mark", "status": "filled", "fill_price": 10.0,
         "stop_reference": 9.0, "shares": 100, "theme": "?", "registered_at": "20260701"},
    ]
    marks = {"A.SH": 110.0, "B.SH": 60.0, "C.SH": 29.0}
    res = review(fund, orders, marks, "20260715")
    by = {r["ticker"]: r for r in res["rows"]}
    ck("R=1.0 → BREAKEVEN 建议", "BREAKEVEN" in (by["A.SH"]["ladder"] or ""))
    ck("R=2.0 → HALF_EXIT 复核建议", "HALF_EXIT" in (by["B.SH"]["ladder"] or ""))
    ck("水下仓无阶梯动作", by["C.SH"]["ladder"] is None)
    ck("挂单 8 天 → STALE_REVIEW", by["D.SH"]["stale"] is True)
    ck("无 mark → DATA_BLOCKED 不静默", any(b["ticker"] == "E.SH" for b in res["data_blocked"]))
    ck("主题敞口 flag(药 > 40%)", any("THEME_CAP" in f and "药" in f for f in res["flags"]))
    ck("review 默认只读(orders 未被改)", orders[0]["stop_reference"] == 90.0)
    md = render(res)
    ck("渲染含免责行", "不是买卖指令" in md)
    passed = sum(1 for _, c in ok if c)
    print(f"position_review selftest: {passed}/{len(ok)}")
    return passed == len(ok)


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    sys.path.insert(0, HERE)
    import datetime
    import paper_portfolio as pp
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("DATA_BLOCKED: NO TUSHARE_TOKEN")
        sys.exit(1)
    today = datetime.date.today().strftime("%Y%m%d")
    fund = _load(os.path.join(FUND_DIR, "fund.json"), {})
    orders = _load(os.path.join(FUND_DIR, "orders.json"), [])
    dlog = _load(os.path.join(FUND_DIR, "decision_log.json"), [])
    marks = {}
    for o in orders:
        if o.get("status") == "filled":
            s = pp.qfq_ohlc_series(o["ticker"], token, o.get("registered_at", "20260601"))
            if s:
                marks[o["ticker"]] = s[-1]["close"]
    res = review(fund, orders, marks, today)
    print(render(res))
    if "--apply-tighten" in sys.argv:
        done = apply_tighten(res, orders, dlog, today)
        with open(os.path.join(FUND_DIR, "orders.json"), "w", encoding="utf-8") as fh:
            json.dump(orders, fh, ensure_ascii=False, indent=2)
        with open(os.path.join(FUND_DIR, "decision_log.json"), "w", encoding="utf-8") as fh:
            json.dump(dlog, fh, ensure_ascii=False, indent=2)
        for d in done:
            print("tighten:", d)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    print(f"[written] {OUT}")


if __name__ == "__main__":
    main()
