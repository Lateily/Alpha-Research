#!/usr/bin/env python3
"""
rotation_panel.py — 轮动面板 v0(合同 v1.1 的 Stage A 机械产出)

半衰期 doctrine:连续性 > 单日强度。本面板按 streak(连续净流入天数)组织
板块视图,streak>=3 的板块无条件单列,不被 5 日规模排序淹没(2026-07-15
大参林/医药 miss 根因修订)。

输出:连续性优先表 + FLICKER(交替)表 + 连续流出表,写 rotation_panel.json。
只描述状态,不选股、不给 posture 之外的任何结论。
数据缺失 => DATA_BLOCKED,绝不静默跳过。

不是买卖指令；研究信号，human executes。
"""

import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "rotation_panel.json")


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


def recent_trade_dates(token, n=5):
    rows = _api("trade_cal", token, exchange="SSE", is_open="1",
                start_date="20260601", end_date="20301231")
    dates = sorted(r["cal_date"] for r in rows)
    import datetime
    today = datetime.date.today().strftime("%Y%m%d")
    past = [d for d in dates if d < today]             # 只用已定盘日
    return past[-n:]


def classify(seq):
    """direction_seq like '+-+++' -> status. Pre-registered rules, no tuning."""
    streak = 0
    for ch in reversed(seq):
        if ch == "+":
            streak += 1
        else:
            break
    neg_streak = 0
    for ch in reversed(seq):
        if ch == "-":
            neg_streak += 1
        else:
            break
    if streak >= 3:
        return streak, "INFLOW_CONT"       # 连续流入 >= 3 日
    if neg_streak >= 3:
        return -neg_streak, "OUTFLOW_CONT"
    tail = seq[-4:]
    if len(tail) >= 3 and all(tail[i] != tail[i + 1] for i in range(len(tail) - 1)):
        return streak, "FLICKER"           # 严格交替 = churn 签名
    if streak == 2:
        return streak, "WARMING"
    return streak if streak else -neg_streak, "NEUTRAL"


def build_panel(flows_by_sector, days):
    """flows_by_sector: {name: {date: (net_amount, pct_change)}} -> panel dict.
    纯函数,离线可测。"""
    rows = []
    for nm, dd in flows_by_sector.items():
        missing = [d for d in days if d not in dd]
        if missing:
            continue                        # 板块缺日:不猜,不进面板
        seq = "".join("+" if dd[d][0] > 0 else "-" for d in days)
        streak, status = classify(seq)
        rows.append({"sector": nm, "seq": seq, "streak": streak,
                     "status": status, "last_pct": round(dd[days[-1]][1], 2),
                     "last_sign": "+" if dd[days[-1]][0] > 0 else "-"})
    cont = sorted([r for r in rows if r["status"] == "INFLOW_CONT"],
                  key=lambda r: -r["streak"])
    out_c = sorted([r for r in rows if r["status"] == "OUTFLOW_CONT"],
                   key=lambda r: r["streak"])
    flick = [r for r in rows if r["status"] == "FLICKER"]
    warm = [r for r in rows if r["status"] == "WARMING"]
    return {"days": days, "n_sectors": len(rows),
            "inflow_cont": cont, "warming": warm,
            "flicker": flick, "outflow_cont": out_c,
            "note": "连续性优先视图;绝对金额 ordinal-only 不入表。"
                    "描述性状态,非选股结论。不是买卖指令。"}


def render(panel):
    L = [f"## 轮动面板 v0(连续性优先 · {panel['days'][0]}–{panel['days'][-1]}"
         f" · {panel['n_sectors']} 板块)", ""]
    L.append("### ① 连续流入 streak≥3(无条件单列,规模排序不得淹没)")
    L.append("| 板块 | 方向序列 | streak | 末日% |")
    L.append("|---|---|---|---|")
    for r in panel["inflow_cont"] or []:
        L.append(f"| {r['sector']} | `{r['seq']}` | {r['streak']} | {r['last_pct']:+.2f}% |")
    if not panel["inflow_cont"]:
        L.append("| (本期无 streak≥3 板块 — 本身是 churn 证据) | | | |")
    L.append("")
    L.append(f"### ② WARMING(streak=2):{', '.join(r['sector'] for r in panel['warming']) or '无'}")
    L.append(f"### ③ FLICKER(严格交替=churn 签名):{len(panel['flicker'])} 个板块")
    L.append(f"### ④ 连续流出 streak≤-3:{', '.join(r['sector'] for r in panel['outflow_cont']) or '无'}")
    L.append("")
    L.append("不是买卖指令；研究信号，human executes.")
    return "\n".join(L)


def run(token, n_days=5):
    days = recent_trade_dates(token, n_days)
    if len(days) < n_days:
        print(f"DATA_BLOCKED: 交易日历不足({len(days)}/{n_days})")
        return None
    flows = {}
    for d in days:
        rows = _api("moneyflow_ind_dc", token, trade_date=d)
        if not rows:
            print(f"DATA_BLOCKED: moneyflow_ind_dc {d} 无数据")
            return None
        for r in rows:
            nm = r.get("name")
            flows.setdefault(nm, {})[d] = (float(r.get("net_amount") or 0),
                                           float(r.get("pct_change") or 0))
        time.sleep(0.25)
    panel = build_panel(flows, days)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(panel, fh, ensure_ascii=False, indent=1)
    print(render(panel))
    print(f"\n[written] {OUT}")
    return panel


def selftest():
    ok = []

    def ck(name, cond):
        ok.append((name, bool(cond)))
        print(("  ✓ " if cond else "  ✗ ") + name)

    days = ["d1", "d2", "d3", "d4", "d5"]
    fx = {
        "医药服务":  {d: (0.5, 1.0) for d in days},                    # +++++ streak5
        "AI巨量":   {"d1": (99, 2), "d2": (-99, -2), "d3": (99, 2),
                    "d4": (-99, -2), "d5": (99, 2)},                   # 交替,规模巨大
        "温和二日":  {"d1": (-1, 0), "d2": (-1, 0), "d3": (-1, 0),
                    "d4": (1, 1), "d5": (1, 1)},                       # streak2
        "连续流出":  {d: (-2, -1) for d in days},
        "缺日板块":  {"d1": (1, 0), "d5": (1, 0)},                     # 缺 d2-d4
    }
    p = build_panel(fx, days)
    ck("streak>=3 进连续性单列", any(r["sector"] == "医药服务" and r["streak"] == 5
                                    for r in p["inflow_cont"]))
    ck("巨量交替板块被判 FLICKER 而非置顶",
       any(r["sector"] == "AI巨量" for r in p["flicker"])
       and all(r["sector"] != "AI巨量" for r in p["inflow_cont"]))
    ck("streak=2 判 WARMING", any(r["sector"] == "温和二日" for r in p["warming"]))
    ck("连续流出判 OUTFLOW_CONT", any(r["sector"] == "连续流出" for r in p["outflow_cont"]))
    ck("缺日板块被剔除(不猜数据)", p["n_sectors"] == 4)
    md = render(p)
    ck("渲染含连续性单列表头与免责行", "无条件单列" in md and "不是买卖指令" in md)
    ck("classify 边界: '++-++' streak=2", classify("++-++") == (2, "WARMING"))
    ck("classify 边界: '-+-+-' FLICKER", classify("-+-+-")[1] == "FLICKER")
    passed = sum(1 for _, c in ok if c)
    print(f"rotation_panel selftest: {passed}/{len(ok)}")
    return passed == len(ok)


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("DATA_BLOCKED: NO TUSHARE_TOKEN")
        sys.exit(1)
    run(token)


if __name__ == "__main__":
    main()
