#!/usr/bin/env python3
"""胜率归因审计 — 任何胜率数字必须按方向分列报告(2026-07-28 归因铁律)。

用法: attribution_audit.py [--bench 000300.SH]
输出: 执行线方向性判断按 constructive/cautious 分桶的裸命中率与超额命中率。
背景: 2026-07-28 首次审计结论 — constructive 0.18 / cautious 0.64,
系统已证实的能力是防守判断,进攻端无统计证据。claim_allowed 只属于防守端。
不是买卖指令;研究信号,human executes.
"""
import os, sys, json, statistics, collections

SIGN = {"constructive": 1, "cautious": -1}


def audit(sigs, idx_fwd):
    rows = []
    for s in sigs:
        call = s.get("directional_call"); r = s.get("returns")
        if call in SIGN and isinstance(r, dict):
            d0 = str(s.get("timestamp", "")).split()[0]
            for h, key in ((3, "3d"), (1, "1d")):
                v = r.get(key)
                if isinstance(v, (int, float)):
                    stock = v * 100
                    bench = idx_fwd(d0, h)
                    rows.append({"call": call, "raw": SIGN[call] * stock,
                                 "excess": SIGN[call] * (stock - bench * 100) if bench is not None else None})
                    break
    out = {}
    byc = collections.defaultdict(list)
    for x in rows:
        byc[x["call"]].append(x)
    for c, vs in byc.items():
        raw = [v["raw"] for v in vs]; exc = [v["excess"] for v in vs if v["excess"] is not None]
        out[c] = {"n": len(raw),
                  "hit_raw": round(sum(1 for v in raw if v > 0) / len(raw), 2) if raw else None,
                  "hit_excess": round(sum(1 for v in exc if v > 0) / len(exc), 2) if exc else None,
                  "mean_excess_pct": round(statistics.mean(exc), 2) if exc else None}
    return out


def main():
    import tushare as ts
    pro = ts.pro_api(os.environ["TUSHARE_TOKEN"])
    bench = sys.argv[sys.argv.index("--bench") + 1] if "--bench" in sys.argv else "000300.SH"
    log = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_signal_log.json")))
    sigs = log if isinstance(log, list) else log.get("signals", [])
    ts0 = sorted(str(s.get("timestamp", "")).split()[0] for s in sigs if s.get("timestamp"))
    idx = pro.index_daily(ts_code=bench, start_date=ts0[0], end_date="20991231",
                          fields="trade_date,close").sort_values("trade_date")
    dates = list(idx.trade_date); closes = list(idx.close); dpos = {d: i for i, d in enumerate(dates)}

    def idx_fwd(d0, h):
        i = dpos.get(d0)
        return None if i is None or i + h >= len(closes) else closes[i + h] / closes[i] - 1

    res = audit(sigs, idx_fwd)
    print(json.dumps({"audit": "directional_attribution_v1", "bench": bench, "buckets": res,
                      "rule": "胜率必须分方向列报告;claim_allowed 只属于防守端(2026-07-28)。不是买卖指令。"},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
