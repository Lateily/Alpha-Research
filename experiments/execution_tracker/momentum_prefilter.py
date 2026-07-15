#!/usr/bin/env python3
"""
momentum_prefilter.py — 全市场价格动量雷达 v0(大参林 miss 根因修订)

价格维度与资金维度并行:主力净流≈0 的慢牛(机构慢吸/北向/算法拆单不打大单
签名)在资金雷达上隐形——大参林 10 日 +30.9% 而主力日净流 <±0.2 亿就是标本。
本雷达只看价格通道,不看资金,产出**复核候选**送 Stage A/Registered Court,
永远不直接选股、不给 posture。

预注册过滤器(改参数 = 提 PR):
  收盘 >= 5 元 · 非 ST/退 · 10日涨幅 ∈ [12%, 60%](上限剔除纯妖股)·
  收盘 >= 20日最高价 × 0.97(贴近新高 = 通道完好)· 样本天数 >= 21

不是买卖指令；研究信号，human executes。
"""

import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "momentum_prefilter.json")

MIN_PRICE = 5.0
RET10_LO, RET10_HI = 0.12, 0.60
NEAR_HIGH = 0.97
TOP_N = 30


def _api(name, token, **params):
    body = json.dumps({"api_name": name, "token": token,
                       "params": params, "fields": ""}).encode()
    req = urllib.request.Request("https://api.tushare.pro", body,
                                 {"Content-Type": "application/json"})
    for _ in range(4):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=45))
            if r.get("code") == 0:
                d = r["data"]
                return [dict(zip(d["fields"], row)) for row in d["items"]]
        except Exception:                              # noqa: BLE001
            pass
        time.sleep(1.5)
    return []


def screen_panel(panel, names):
    """panel: {ts_code: [(date, close, high), ...] 升序} names: {ts_code: (name, industry)}
    纯函数,离线可测。返回过滤+排序后的候选列表。"""
    out = []
    for code, bars in panel.items():
        if len(bars) < 21:
            continue
        nm, ind = names.get(code, ("?", "?"))
        if any(t in nm for t in ("ST", "退")):
            continue
        closes = [b[1] for b in bars]
        highs = [b[2] for b in bars]
        last = closes[-1]
        if last < MIN_PRICE:
            continue
        ret10 = last / closes[-11] - 1
        if not (RET10_LO <= ret10 <= RET10_HI):
            continue
        h20 = max(highs[-20:])
        if last < h20 * NEAR_HIGH:
            continue
        out.append({"ts_code": code, "name": nm, "industry": ind,
                    "ret10": round(ret10 * 100, 1),
                    "ret20": round((last / closes[-21] - 1) * 100, 1),
                    "close": last, "dist_high20": round((last / h20 - 1) * 100, 1)})
    out.sort(key=lambda r: -r["ret10"])
    return out[:TOP_N]


def run(token):
    cal = _api("trade_cal", token, exchange="SSE", is_open="1",
               start_date="20260501", end_date="20301231")
    import datetime
    today = datetime.date.today().strftime("%Y%m%d")
    days = [r["cal_date"] for r in sorted(cal, key=lambda x: x["cal_date"])
            if r["cal_date"] < today][-21:]
    if len(days) < 21:
        print("DATA_BLOCKED: 交易日历不足 21 日")
        return None
    basic = _api("stock_basic", token, list_status="L")
    if not basic:
        print("DATA_BLOCKED: stock_basic 无数据")
        return None
    names = {r["ts_code"]: (r.get("name") or "?", r.get("industry") or "?")
             for r in basic}
    panel = {}
    for d in days:
        rows = _api("daily", token, trade_date=d)
        if not rows:
            print(f"DATA_BLOCKED: daily {d} 无数据")
            return None
        for r in rows:
            panel.setdefault(r["ts_code"], []).append(
                (d, float(r.get("close") or 0), float(r.get("high") or 0)))
        time.sleep(0.3)
    for code in panel:
        panel[code].sort()
    cands = screen_panel(panel, names)
    result = {"as_of": days[-1], "universe": len(panel), "candidates": cands,
              "filters": {"min_price": MIN_PRICE, "ret10": [RET10_LO, RET10_HI],
                          "near_high20": NEAR_HIGH, "top_n": TOP_N},
              "note": "价格雷达只送复核,不选股不给posture;资金隐形慢牛的安全网。"
                      "不是买卖指令。"}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(f"## 动量雷达 v0(as_of {days[-1]},全市场 {len(panel)} 只)")
    print("| 代码 | 名字 | 行业 | 10日% | 20日% | 距20日高 |")
    print("|---|---|---|---|---|---|")
    for c in cands:
        print(f"| {c['ts_code']} | {c['name']} | {c['industry']} "
              f"| {c['ret10']:+.1f}% | {c['ret20']:+.1f}% | {c['dist_high20']:+.1f}% |")
    print(f"\n[written] {OUT}\n不是买卖指令；研究信号，human executes.")
    return result


def selftest():
    ok = []

    def ck(name, cond):
        ok.append((name, bool(cond)))
        print(("  ✓ " if cond else "  ✗ ") + name)

    def mk(closes):
        return [(f"d{i:02d}", c, c * 1.01) for i, c in enumerate(closes)]

    # 大参林标本:15.4 -> 19.7 慢牛(约+28%/10日),贴近新高;雷达无资金输入
    slow_bull = mk([15.4, 15.4, 14.8, 15.5, 15.0, 15.2, 15.3, 15.4, 15.5, 15.3,
                    15.4, 16.1, 16.3, 17.1, 17.2, 17.5, 17.8, 17.6, 17.6, 18.1, 19.7])
    crazy = mk([10 * (1.11 ** i) for i in range(21)])          # 10日 +18x% 妖股
    flat = mk([20.0] * 21)
    dipper = mk([30] * 15 + [36, 35, 33, 31, 30, 29])          # 涨过但已远离新高
    cheap = mk([2.0] * 10 + [2.0 * (1.03 ** i) for i in range(11)])  # <5元
    panel = {"603233.SH": slow_bull, "MANIA.SZ": crazy, "FLAT.SZ": flat,
             "DIP.SZ": dipper, "CHEAP.SZ": cheap, "STX.SZ": slow_bull}
    names = {"603233.SH": ("大参林", "医药商业"), "MANIA.SZ": ("妖股", "?"),
             "FLAT.SZ": ("横盘", "?"), "DIP.SZ": ("回落", "?"),
             "CHEAP.SZ": ("低价", "?"), "STX.SZ": ("ST标本", "?")}
    out = screen_panel(panel, names)
    got = {c["ts_code"] for c in out}
    ck("大参林型慢牛被捕获(零资金输入)", "603233.SH" in got)
    ck("10日>60% 妖股剔除", "MANIA.SZ" not in got)
    ck("横盘剔除(动量不足)", "FLAT.SZ" not in got)
    ck("远离20日高剔除(通道破坏)", "DIP.SZ" not in got)
    ck("低价票剔除", "CHEAP.SZ" not in got)
    ck("ST 剔除", "STX.SZ" not in got)
    ck("按10日动量降序", all(out[i]["ret10"] >= out[i+1]["ret10"]
                            for i in range(len(out)-1)))
    passed = sum(1 for _, c in ok if c)
    print(f"momentum_prefilter selftest: {passed}/{len(ok)}")
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
