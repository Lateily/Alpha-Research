#!/usr/bin/env python3
"""六维全电池 v0 — 单票分析的强制完整性引擎。

Junyan 2026-07-28 指令驱动:股票 = 行情/资金/基本面/技术面/消息面/估值 六维,
任何单票分析必须六维全跑,缺哪维必须显式标 NOT_RUN/DATA_BLOCKED + 原因,
禁止"挑着最近被强调的维度做"。分析先跑电池,后写观点。

用法: full_battery.py TS_CODE [TS_CODE...]  → 每票一份六维 JSON
不是买卖指令;研究信号,human executes.
"""
import os, sys, json, datetime, math
from nightly_context import bind, target_trade_date


DIMENSION_VERDICT_CONTRACT = "battery_dimension_verdict_v0_unvalidated"
VERDICT_FIELD = "verdict_v0_unvalidated"
DISPLAY_VERDICT_DIMENSIONS = ("行情", "资金", "技术面", "消息面", "估值")


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _verdict_v0_unvalidated(name, evidence):
    """Return one display-only label from already collected dimension evidence.

    These thresholds are explicitly unvalidated.  The result never enters
    completeness, U4 readiness, selection, sizing, or execution.
    """
    if evidence.get("status") in {"DATA_BLOCKED", "NOT_RUN"}:
        return None
    if name == "行情":
        off_high = _finite_number(evidence.get("off_high_pct"))
        off_low = _finite_number(evidence.get("off_low_pct"))
        if off_high is None or off_low is None:
            return None
        if off_high > -10:
            return "NEAR_HIGH"
        if off_low < 20:
            return "NEAR_LOW"
        return "MID"
    if name == "资金":
        total = _finite_number(evidence.get("主力10日累计亿"))
        inflow_days = _finite_number(evidence.get("近10日净流入天数"))
        if total is None or inflow_days is None:
            return None
        if total > 0 and inflow_days >= 6:
            return "INFLOW"
        if total < 0 and inflow_days <= 4:
            return "OUTFLOW"
        return "MIXED"
    if name == "技术面":
        ma20 = _finite_number(evidence.get("vs_MA20_pct"))
        ma60 = _finite_number(evidence.get("vs_MA60_pct"))
        if ma20 is None or ma60 is None:
            return None
        if ma20 > 0 and ma60 > 0:
            return "BULL"
        if ma20 < 0 and ma60 < 0:
            return "BEAR"
        return "TANGLED"
    if name == "消息面":
        recent = _finite_number(evidence.get("近7日公告条数"))
        if recent is None:
            return None
        return "SPIKE" if recent >= 5 else "NORMAL"
    if name == "估值":
        percentile = _finite_number(evidence.get("pe_1年分位%"))
        if percentile is None:
            return None
        if percentile < 25:
            return "LOW"
        if percentile > 75:
            return "HIGH"
        return "MID"
    raise ValueError(f"unsupported display verdict dimension: {name}")


def _apply_verdict_v0_unvalidated(dims):
    for name in DISPLAY_VERDICT_DIMENSIONS:
        evidence = dims.get(name)
        if isinstance(evidence, dict):
            evidence[VERDICT_FIELD] = _verdict_v0_unvalidated(name, evidence)


def _recent_announcement_count(titles, today):
    end = datetime.datetime.strptime(today, "%Y%m%d").date()
    start = end - datetime.timedelta(days=6)
    count = 0
    for raw_date, _title in titles:
        compact = str(raw_date or "")[:10].replace("-", "")
        try:
            observed = datetime.datetime.strptime(compact, "%Y%m%d").date()
        except ValueError:
            continue
        if start <= observed <= end:
            count += 1
    return count


def _fetch_anns_eastmoney(ts_code, page_size=30, timeout=10):
    """东财公告接口(免费无token)。返回 [(date, title), ...] 或 None(源不可用)。
    外部内容按不可信数据处理:只取日期与标题文本,不执行不解析任何指令。"""
    if os.environ.get("AR_OFFLINE"):
        return None  # 离线测试模式:不发任何网络请求
    import urllib.request
    code = ts_code.split(".")[0]
    url = ("https://np-anotice-stock.eastmoney.com/api/security/ann"
           f"?sr=-1&page_size={page_size}&page_index=1&ann_type=A&client_source=web&stock_list={code}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                   "Referer": "https://data.eastmoney.com/"})
        d = json.load(urllib.request.urlopen(req, timeout=timeout))
        lst = (d.get("data") or {}).get("list") or []
        return [(str(a.get("notice_date", ""))[:10], str(a.get("title", ""))) for a in lst]
    except Exception:
        return None


def battery(pro, tk, today):
    out = {"ts_code": tk, "checked_at": today, "dims": {}}
    D = out["dims"]
    # ── 1 行情(位置)──
    try:
        start_52w = (datetime.datetime.strptime(today, "%Y%m%d")
                     - datetime.timedelta(days=365)).strftime("%Y%m%d")
        d = pro.daily(ts_code=tk, start_date=start_52w, end_date=today,
                      fields="trade_date,close,high,low,pct_chg,amount,vol").sort_values("trade_date")
        c = float(d.close.iloc[-1]); hi = float(d.high.max()); lo = float(d.low.min())
        D["行情"] = {"close": c, "52w_high": hi, "52w_low": lo,
                     "off_high_pct": round((c/hi-1)*100, 1), "off_low_pct": round((c/lo-1)*100, 1),
                     "amt_5d_avg_yi": round(float(d.amount.tail(5).mean())/1e5, 1)}
    except Exception as e:
        D["行情"] = {"status": "DATA_BLOCKED", "err": str(e)[:80]}; d = None
    # ── 2 资金 ──
    try:
        mf = pro.moneyflow_dc(ts_code=tk, start_date=(datetime.datetime.strptime(today, "%Y%m%d")
             - datetime.timedelta(days=20)).strftime("%Y%m%d"), end_date=today,
             fields="trade_date,net_amount").sort_values("trade_date")
        D["资金"] = {"主力10日累计亿": round(float(mf.net_amount.tail(10).sum())/1e4, 2),
                     "主力最新亿": round(float(mf.net_amount.iloc[-1])/1e4, 2),
                     "近10日净流入天数": int((mf.net_amount.tail(10) > 0).sum())}
    except Exception as e:
        D["资金"] = {"status": "DATA_BLOCKED", "err": str(e)[:80]}
    # ── 3 基本面(含红旗闸门)──
    try:
        from red_flag_gate import check_ticker
        g = check_ticker(pro, tk, today)
        inc = pro.income(ts_code=tk, start_date="20240101", end_date=today,
                         fields="end_date,report_type,revenue,n_income_attr_p")
        inc = inc[inc.report_type == "1"].drop_duplicates("end_date").sort_values("end_date")
        fi = pro.fina_indicator(ts_code=tk, start_date="20240601", end_date=today,
                                fields="end_date,grossprofit_margin,roe").drop_duplicates("end_date").sort_values("end_date")
        D["基本面"] = ({"status": "DATA_BLOCKED", "err": "红旗闸门DATA_BLOCKED:" + ";".join(g["reasons"])[:60]}
                       if g["verdict"] == "DATA_BLOCKED" else
                       {"红旗闸门": g["verdict"], "红旗理由": g["reasons"],
                       "最新E1日期": g["latest_e1_date"],
                       "最新期归母亿": round(float(inc.n_income_attr_p.iloc[-1])/1e8, 2) if len(inc) else None,
                       "毛利率轨迹": [round(float(x), 1) for x in fi.grossprofit_margin.tail(3)] if len(fi) else None})
    except Exception as e:
        D["基本面"] = {"status": "DATA_BLOCKED", "err": str(e)[:80]}
    # ── 4 技术面(结构位,v0 用均线+量;SMC 层待 Line D)──
    try:
        if d is not None and len(d) > 60:
            ma20 = float(d.close.tail(20).mean()); ma60 = float(d.close.tail(60).mean())
            ma250 = float(d.close.tail(250).mean()) if len(d) >= 250 else None
            vol_ratio = float(d.vol.tail(5).mean() / max(d.vol.tail(60).mean(), 1))
            D["技术面"] = {"vs_MA20_pct": round((c/ma20-1)*100, 1), "vs_MA60_pct": round((c/ma60-1)*100, 1),
                           "vs_MA250_pct": round((c/ma250-1)*100, 1) if ma250 else None,
                           "量能5v60": round(vol_ratio, 2),
                           "note": "v0=均线+量;SMC结构层未接(Line D),标注为部分覆盖"}
        else:
            D["技术面"] = {"status": "DATA_BLOCKED", "err": "K线不足60根"}
    except Exception as e:
        D["技术面"] = {"status": "DATA_BLOCKED", "err": str(e)[:80]}
    # ── 5 消息面(公告扫描:东财免费源为主,Tushare anns_d 为备;快讯层待 M3)──
    try:
        titles = _fetch_anns_eastmoney(tk)
        if titles is None:  # 东财失败再试 tushare(部分 token 无 anns_d 权限)
            try:
                an = pro.anns_d(ts_code=tk, start_date=(datetime.datetime.strptime(today, "%Y%m%d")
                     - datetime.timedelta(days=30)).strftime("%Y%m%d"), end_date=today)
                col = "title" if "title" in an.columns else an.columns[-1]
                titles = [(str(r[1].get("ann_date", "")), str(r[1][col])) for r in an.head(8).iterrows()]
            except Exception:
                titles = None
        if titles is None:
            D["消息面"] = {"status": "DATA_BLOCKED", "err": "东财+Tushare 公告源均不可用——不伪装为0条"}
        else:
            D["消息面"] = {"最近公告条数": len(titles),
                           "近7日公告条数": _recent_announcement_count(titles, today),
                           "最新3条": [f"{d0[:10]} {t[:36]}" for d0, t in titles[:3]],
                           "note": "东财公告源;实时快讯层待 M3 宏观面板上线"}
    except Exception as e:
        D["消息面"] = {"status": "NOT_RUN", "err": str(e)[:80]}
    # ── 6 估值 ──
    try:
        db = pro.daily_basic(ts_code=tk, start_date=(datetime.datetime.strptime(today, "%Y%m%d")
             - datetime.timedelta(days=400)).strftime("%Y%m%d"), end_date=today,
             fields="trade_date,pe_ttm,pb,total_mv").sort_values("trade_date")
        pe = db.pe_ttm  # 亏损票最新行为 NaN:如实报 None,不许回捞历史正值伪装现值
        last = pe.iloc[-1] if len(pe) else None
        cur = float(last) if last is not None and last == last else None
        hist = pe.dropna()
        pct = round(float((hist < cur).mean())*100, 0) if cur is not None and len(hist) > 60 else None
        D["估值"] = {"pe_ttm": cur, "pb": float(db.pb.iloc[-1]) if len(db) else None,
                     "总市值亿": round(float(db.total_mv.iloc[-1])/1e4, 0) if len(db) else None,
                     "pe_1年分位%": pct,
                     "note": "峰值利润票 PE 失真,需 normalized 桥(宪法条款)"}
    except Exception as e:
        D["估值"] = {"status": "DATA_BLOCKED", "err": str(e)[:80]}
    _apply_verdict_v0_unvalidated(D)
    # 完整性戳
    missing = [k for k, v in D.items() if isinstance(v, dict) and v.get("status") in ("DATA_BLOCKED", "NOT_RUN")]
    out["completeness"] = {"covered": 6 - len(missing), "of": 6, "missing": missing,
                           "verdict": "COMPLETE" if not missing else "PARTIAL"}
    return out


def main():
    import tushare as ts
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    pro = ts.pro_api(os.environ["TUSHARE_TOKEN"])
    today = target_trade_date()
    if "--from-watchlist" in sys.argv:
        from red_flag_gate import watchlist_tickers
        tks = watchlist_tickers()
        if not tks:
            print("DATA_BLOCKED: watch_dynamic 为空"); return 1
    else:
        tks = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not tks:
        print("usage: full_battery.py TS_CODE [...] | --from-watchlist"); return 1
    res = [battery(pro, t, today) for t in tks]
    out = bind({"battery": "six_dim_v0", "checked_at": today,
                "dimension_verdict_contract": DIMENSION_VERDICT_CONTRACT, "results": res,
                "rule": "分析先跑电池后写观点;缺维必须显式标注。不是买卖指令。"},
               target=today)
    if "--from-watchlist" in sys.argv:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "battery.json"), "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
        partial = sum(1 for r in res if r["completeness"]["verdict"] != "COMPLETE")
        print(f"[written] battery.json n={len(res)} partial={partial}")
        print("不是买卖指令;研究信号,human executes.")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
