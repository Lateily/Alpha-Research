#!/usr/bin/env python3
"""
overnight_anchor.py — 盘前隔夜锚点 v0.

The A-share AI/semiconductor beta often wakes up with overseas anchors:
NVDA, SOX, TSMC ADR, and A50. This module defines the frame and a strict data
contract. When no local/manual feed is configured, it returns DATA_BLOCKED
instead of inventing prices.

Input options:
  1) experiments/execution_tracker/overnight_anchor_manual.json
  2) --fixture during selftest / manual script use

Expected manual shape:
{
  "as_of": "20260721 08:55",
  "anchors": {
    "NVDA": {"pct_change": 1.2, "source": "manual/yahoo"},
    "SOX": {"pct_change": 0.8, "source": "manual"},
    "TSM": {"pct_change": 1.0, "source": "manual"},
    "A50": {"pct_change": -0.2, "source": "manual"}
  }
}

不是买卖指令；研究信号，human executes。
"""

import argparse
import json
import os
import sys
import time
from nightly_context import bind, target_trade_date

HERE = os.path.dirname(os.path.abspath(__file__))
MANUAL = os.path.join(HERE, "overnight_anchor_manual.json")
OUT = os.path.join(HERE, "overnight_anchor.json")

ANCHORS = [
    ("NVDA", "NVIDIA", "US_AI"),
    ("SOX", "费城半导体指数", "US_SEMI"),
    ("TSM", "台积电 ADR", "FOUNDRY_ADR"),
    ("A50", "富时中国 A50", "CN_BETA"),
]

# 自动抓取:Tushare index_global 实测可用的代码。
# 实测不可用(2026-08-05 探过,不是猜的):
#   · us_daily(NVDA/TSM) —— token 无该接口权限
#   · index_global(SOX)  —— 返回 0 行
#   · stooq              —— 已上 bot 验证
#   · yfinance           —— 被限流
# 所以 NVDA / SOX / TSM 保持 DATA_BLOCKED,不伪造;IXIC 与 TWII 作为**显式标注的
# 代理**(proxy=True)供参考,绝不冒充本尊。
AUTO_SOURCES = {
    "A50":  {"code": "XIN9", "proxy": False, "label": "富时中国A50"},
    "IXIC": {"code": "IXIC", "proxy": False, "label": "纳斯达克综合"},
    "TWII": {"code": "TWII", "proxy": True,  "label": "台湾加权(半导体链代理)",
             "proxy_for": "SOX"},
}
AUTO_ANCHORS = [
    ("IXIC", "纳斯达克综合", "US_AI"),
    ("TWII", "台湾加权(SOX 代理)", "US_SEMI_PROXY"),
]


def fetch_auto_anchors(token=None, today=None):
    """抓 Tushare index_global 的隔夜读数。返回 {key: {pct_change, source, as_of, proxy}}。
    离线或无 token ⇒ 返回 {},由调用方走 DATA_BLOCKED —— 绝不返回编造值。"""
    if os.environ.get("AR_OFFLINE"):
        return {}
    token = token or os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        return {}
    try:
        import tushare as ts
        pro = ts.pro_api(token)
    except Exception:
        return {}
    end = today or time.strftime("%Y%m%d")
    start = time.strftime("%Y%m%d", time.localtime(time.time() - 14 * 86400))
    out = {}
    for key, spec in AUTO_SOURCES.items():
        try:
            df = pro.index_global(ts_code=spec["code"], start_date=start, end_date=end)
            if df is None or not len(df):
                continue
            row = df.sort_values("trade_date").iloc[-1]
            pct = row.get("pct_chg")
            if pct is None or pct != pct:
                continue
            out[key] = {"pct_change": round(float(pct), 2),
                        "source": f"tushare/index_global/{spec['code']}",
                        "as_of": str(row.get("trade_date")),
                        "proxy": spec["proxy"],
                        "proxy_for": spec.get("proxy_for")}
        except Exception:
            continue          # 单条失败不拖垮其余,缺的那条走 DATA_BLOCKED
    return out


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def build_anchor(payload=None, auto=None):
    payload = payload or _load(MANUAL) or {}
    raw = dict(payload.get("anchors") or {})
    # 自动抓取的读数并入(手工文件优先 —— 人工覆盖永远赢自动源)
    auto = fetch_auto_anchors() if auto is None else auto
    for k, v in (auto or {}).items():
        raw.setdefault(k, v)
    rows = []
    blocked = []
    positives = negatives = 0
    for key, label, group in list(ANCHORS) + list(AUTO_ANCHORS):
        r = raw.get(key) or {}
        pct = r.get("pct_change")
        if pct is None:
            rows.append({"key": key, "label": label, "group": group,
                         "status": "DATA_BLOCKED", "pct_change": None,
                         "source": None})
            blocked.append(f"{key}: no pct_change in overnight anchor feed")
            continue
        pct = float(pct)
        if not r.get("proxy"):          # 代理只作背景参考,不替本尊投方向票
            positives += 1 if pct > 0 else 0
            negatives += 1 if pct < 0 else 0
        rows.append({"key": key, "label": label, "group": group,
                     "status": "OK", "pct_change": round(pct, 3),
                     "source": r.get("source") or payload.get("source") or "manual",
                     "as_of": r.get("as_of"),
                     "proxy": bool(r.get("proxy")),
                     "proxy_for": r.get("proxy_for")})

    ok_rows = [r for r in rows if r["status"] == "OK" and not r.get("proxy")]
    # 阈值不放水:方向判读仍要求 ≥3 个**非代理**锚。但"方向不可判"≠"这份产物没数据"。
    # 只要当轮真抓到过读数,internal_status 就是 PARTIAL_OK 而不是 DATA_BLOCKED ——
    # 否则单条 NVDA 抓不到就会把整个盘前帧拖成 STALE_INPUT,发布永远解不开。
    if len(ok_rows) < 3:
        bias = "DATA_BLOCKED" if not ok_rows else "INSUFFICIENT_ANCHORS"
        why = (f"only {len(ok_rows)} non-proxy anchors available (need 3 for a direction read)"
               if ok_rows else "no anchor data at all")
    elif positives >= 3:
        bias = "OVERNIGHT_RISK_ON_BETA"
        why = f"{positives}/{len(ok_rows)} anchors positive"
    elif negatives >= 3:
        bias = "OVERNIGHT_RISK_OFF_BETA"
        why = f"{negatives}/{len(ok_rows)} anchors negative"
    else:
        bias = "MIXED"
        why = f"{positives} positive / {negatives} negative"

    return bind({
        "as_of": f"{target_trade_date()} 09:00",
        "layer": "overnight_anchor_v0",
        "anchors": rows,
        "bias": bias,
        "why": why,
        "data_blocked": blocked,
        # 契约层消费它:有任一真实读数 ⇒ PARTIAL_OK(可用但方向不可判),
        # 一条都没有 ⇒ DATA_BLOCKED。区分"抓不全"和"完全没抓到"。
        "internal_status": ("DATA_BLOCKED" if not ok_rows
                            else ("OK" if len(ok_rows) >= 3 else "PARTIAL_OK")),
        "fetched_count": len(ok_rows),
        "proxy_count": sum(1 for r in rows if r.get("proxy") and r["status"] == "OK"),
        "claim_allowed": False,
        "policy": "盘前第一行;只改变科技 beta 背景读数,不直接生成交易动作。",
        "note": "不是买卖指令；研究信号，human executes。",
    })


def render(rep):
    lines = [f"## 隔夜锚点({rep['as_of']})", ""]
    lines.append(f"bias: {rep['bias']} · {rep['why']}")
    for r in rep["anchors"]:
        val = "DATA_BLOCKED" if r["pct_change"] is None else f"{r['pct_change']:+.2f}%"
        lines.append(f"- {r['key']} {r['label']}: {val}")
    if rep["data_blocked"]:
        lines.append("")
        lines.extend(f"- DATA_BLOCKED: {x}" for x in rep["data_blocked"])
    lines.append("")
    lines.append("不是买卖指令；研究信号，human executes。")
    return "\n".join(lines)


def selftest():
    rep = build_anchor({"as_of": "20260721 08:55", "anchors": {
        "NVDA": {"pct_change": 1.2}, "SOX": {"pct_change": 0.8},
        "TSM": {"pct_change": 1.0}, "A50": {"pct_change": -0.2},
    }}, auto={})
    # 自动源必须显式关掉,否则 selftest 会打网络、结果随行情漂
    partial = build_anchor({"anchors": {"NVDA": {"pct_change": 1.2}}}, auto={})
    blocked = build_anchor({"anchors": {}}, auto={})
    proxy_only = build_anchor({"anchors": {}},
                              auto={"TWII": {"pct_change": 1.0, "proxy": True,
                                             "source": "t", "proxy_for": "SOX"}})
    checks = [
        ("risk-on beta when 3/4 positive", rep["bias"] == "OVERNIGHT_RISK_ON_BETA"),
        ("claim disabled", rep["claim_allowed"] is False),
        # 阈值不变(方向判读仍需 ≥3 个非代理锚),但要区分"抓不全"与"完全没抓到"——
        # 混为一谈会让单条 NVDA 缺失把整个盘前帧拖成 STALE_INPUT。
        ("partial: 1 anchor ⇒ INSUFFICIENT_ANCHORS 而非 DATA_BLOCKED",
         partial["bias"] == "INSUFFICIENT_ANCHORS" and partial["internal_status"] == "PARTIAL_OK"),
        ("empty: 0 anchor ⇒ DATA_BLOCKED",
         blocked["bias"] == "DATA_BLOCKED" and blocked["internal_status"] == "DATA_BLOCKED"),
        ("proxy 不替本尊投票:只有代理仍判 DATA_BLOCKED",
         proxy_only["bias"] == "DATA_BLOCKED" and proxy_only["fetched_count"] == 0
         and proxy_only["proxy_count"] == 1),
        ("render disclaimer", "不是买卖指令" in render(rep)),
    ]
    for name, ok in checks:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print(f"overnight_anchor selftest: {sum(ok for _, ok in checks)}/{len(checks)}")
    return all(ok for _, ok in checks)


def main():
    ap = argparse.ArgumentParser(description="Premarket overnight beta anchor frame")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--print", action="store_true", dest="do_print")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    rep = build_anchor()
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1)
    if args.do_print:
        print(render(rep))
    print(f"[written] {OUT}")


if __name__ == "__main__":
    main()
