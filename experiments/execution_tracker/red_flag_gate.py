#!/usr/bin/env python3
"""红旗闸门 v0 — 任何名单产出前的强制 E1 最低核查。

失败案例驱动:2026-07-27 赛力斯(601127.SH)带着 8 天前的中报首亏预告
(-15~-18亿)被放进 ✅核心 名单。本闸门的回归测试就是这个案例。

规则:
  RED_FLAG  = 最新业绩预告为负面类型(首亏/预亏/预减/略减/续亏),或
              最近两个已披露季度归母净利连续环比恶化且最新季 <0,或
              最新快报净利同比 < -30%
  PASS      = 无上述红旗
  DATA_BLOCKED = 关键数据取不到(缺数据≠通过)

红旗≠禁入:逆向/复活候选可以带旗出现,但必须亮旗,且不得佩戴 ✅核心 层级。
名单模板必须携带本闸门的 stamp(时间戳+结果+最新E1日期),无戳名单=违宪。
不是买卖指令;研究信号,human executes.
"""
import os, sys, json, datetime

NEG_TYPES = {"首亏", "预亏", "预减", "略减", "续亏"}


def check_ticker(pro, ts_code, today):
    out = {"ts_code": ts_code, "verdict": "PASS", "reasons": [],
           "latest_e1_date": None, "checked_at": today}
    try:
        fc = pro.forecast(ts_code=ts_code, start_date="20250101", end_date=today,
                          fields="ann_date,end_date,type,net_profit_min,net_profit_max")
        if fc is not None and len(fc):
            fc = fc.sort_values("ann_date")
            last = fc.iloc[-1]
            out["latest_e1_date"] = str(last["ann_date"])
            if str(last["type"]) in NEG_TYPES:
                lo = last.get("net_profit_min")
                out["verdict"] = "RED_FLAG"
                out["reasons"].append(
                    f"最新预告[{last['type']}] {last['ann_date']} 期末{last['end_date']}"
                    + (f" 净利下限{float(lo)/1e4:.1f}亿" if lo == lo and lo is not None else ""))
    except Exception as e:
        out["verdict"] = "DATA_BLOCKED"; out["reasons"].append(f"forecast:{e}"); return out
    try:
        ex = pro.express(ts_code=ts_code, start_date="20250101", end_date=today,
                         fields="ann_date,end_date,yoy_net_profit")
        if ex is not None and len(ex):
            ex = ex.sort_values("ann_date"); last = ex.iloc[-1]
            out["latest_e1_date"] = max(out["latest_e1_date"] or "0", str(last["ann_date"]))
            y = last.get("yoy_net_profit")
            if y == y and y is not None and float(y) < -30:
                out["verdict"] = "RED_FLAG"
                out["reasons"].append(f"最新快报净利同比{float(y):.0f}% ({last['ann_date']})")
    except Exception:
        pass  # express 缺失不算 BLOCKED(多数公司不发快报)
    try:
        inc = pro.income(ts_code=ts_code, start_date="20240601", end_date=today,
                         fields="end_date,report_type,n_income_attr_p")
        inc = inc[inc.report_type == "1"].drop_duplicates("end_date").sort_values("end_date")
        if len(inc) >= 3:
            cum = list(inc["n_income_attr_p"])[-3:]
            q_last = cum[-1] - cum[-2] if str(inc.end_date.iloc[-1])[4:6] != "03" else cum[-1]
            q_prev = cum[-2] - cum[-3] if str(inc.end_date.iloc[-2])[4:6] != "03" else cum[-2]
            if q_last < 0 and q_last < q_prev:
                out["verdict"] = "RED_FLAG"
                out["reasons"].append(
                    f"最近季度归母{q_last/1e8:.1f}亿为负且环比恶化(前季{q_prev/1e8:.1f}亿)")
    except Exception as e:
        if out["verdict"] == "PASS":
            out["verdict"] = "DATA_BLOCKED"; out["reasons"].append(f"income:{e}")
    return out


def main():
    import tushare as ts
    pro = ts.pro_api(os.environ["TUSHARE_TOKEN"])
    today = datetime.date.today().strftime("%Y%m%d")
    tickers = sys.argv[1:] or []
    if not tickers:
        print("usage: red_flag_gate.py TS_CODE [TS_CODE...]"); return 1
    results = [check_ticker(pro, t, today) for t in tickers]
    stamp = {"gate": "red_flag_gate_v0", "checked_at": today, "results": results,
             "disclaimer": "红旗≠禁入,但必须亮旗;无戳名单=违宪。不是买卖指令。"}
    print(json.dumps(stamp, ensure_ascii=False, indent=1))
    # 回归测试:赛力斯 0713 首亏必须被抓住
    if "601127.SH" in tickers:
        s = next(r for r in results if r["ts_code"] == "601127.SH")
        assert s["verdict"] == "RED_FLAG", "回归测试失败:赛力斯首亏未被抓住!"
        print("[selftest] 赛力斯 20260713 首亏 → RED_FLAG ✓", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
