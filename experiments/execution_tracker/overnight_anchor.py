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

HERE = os.path.dirname(os.path.abspath(__file__))
MANUAL = os.path.join(HERE, "overnight_anchor_manual.json")
OUT = os.path.join(HERE, "overnight_anchor.json")

ANCHORS = [
    ("NVDA", "NVIDIA", "US_AI"),
    ("SOX", "费城半导体指数", "US_SEMI"),
    ("TSM", "台积电 ADR", "FOUNDRY_ADR"),
    ("A50", "富时中国 A50", "CN_BETA"),
]


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def build_anchor(payload=None):
    payload = payload or _load(MANUAL) or {}
    raw = payload.get("anchors") or {}
    rows = []
    blocked = []
    positives = negatives = 0
    for key, label, group in ANCHORS:
        r = raw.get(key) or {}
        pct = r.get("pct_change")
        if pct is None:
            rows.append({"key": key, "label": label, "group": group,
                         "status": "DATA_BLOCKED", "pct_change": None,
                         "source": None})
            blocked.append(f"{key}: no pct_change in overnight anchor feed")
            continue
        pct = float(pct)
        positives += 1 if pct > 0 else 0
        negatives += 1 if pct < 0 else 0
        rows.append({"key": key, "label": label, "group": group,
                     "status": "OK", "pct_change": round(pct, 3),
                     "source": r.get("source") or payload.get("source") or "manual"})

    ok_rows = [r for r in rows if r["status"] == "OK"]
    if len(ok_rows) < 3:
        bias = "DATA_BLOCKED"
        why = "less than 3 anchors available"
    elif positives >= 3:
        bias = "OVERNIGHT_RISK_ON_BETA"
        why = f"{positives}/{len(ok_rows)} anchors positive"
    elif negatives >= 3:
        bias = "OVERNIGHT_RISK_OFF_BETA"
        why = f"{negatives}/{len(ok_rows)} anchors negative"
    else:
        bias = "MIXED"
        why = f"{positives} positive / {negatives} negative"

    return {
        "as_of": payload.get("as_of") or time.strftime("%Y%m%d %H:%M"),
        "layer": "overnight_anchor_v0",
        "anchors": rows,
        "bias": bias,
        "why": why,
        "data_blocked": blocked,
        "claim_allowed": False,
        "policy": "盘前第一行;只改变科技 beta 背景读数,不直接生成交易动作。",
        "note": "不是买卖指令；研究信号，human executes。",
    }


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
    }})
    blocked = build_anchor({"anchors": {"NVDA": {"pct_change": 1.2}}})
    checks = [
        ("risk-on beta when 3/4 positive", rep["bias"] == "OVERNIGHT_RISK_ON_BETA"),
        ("claim disabled", rep["claim_allowed"] is False),
        ("blocked when fewer than 3 anchors", blocked["bias"] == "DATA_BLOCKED"),
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
