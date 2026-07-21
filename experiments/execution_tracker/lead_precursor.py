#!/usr/bin/env python3
"""
lead_precursor.py — L0.5 前兆层 v0.

Purpose: stop treating half-life-one-day market reversals as surprises. This
module turns four "repair precursor" ideas into explicit, backtestable lights
using only point-in-time settle data already stored in rotation_history.json.

Important boundary:
  - This is calibration / attention routing only.
  - It never creates orders and never claims alpha.
  - Two inputs from the original lesson are not in rotation_history: individual
    leader "no new low" and overnight US/ADR/A50 anchors. They are marked as
    DATA_LIMITED / DATA_BLOCKED instead of being faked.

不是买卖指令；研究信号，human executes。
"""

import json
import os
import random
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "rotation_history.json")
OUT = os.path.join(HERE, "lead_precursor.json")
NOWCAST_LOG = os.path.join(HERE, "nowcast_log.json")

TECH_PARENT = ["电子"]
TECH_NEIGHBORS = [
    "半导体", "半导体设备", "半导体材料", "第四代半导体", "集成电路",
    "消费电子", "品牌消费电子", "元件", "被动元件", "印制电路板",
    "光学元件", "光通信模块", "通信设备", "通信技术", "通信终端",
    "计算机", "计算机设备", "其他计算机设备", "服务器",
]
DEFENSE_CROWDING = ["电力", "火力发电", "水力发电", "公用事业", "电能综合服务"]
TECH_NAMES = [
    "新易盛", "中际旭创", "沪电股份", "胜宏科技", "生益科技", "深南电路",
    "华海清科", "鼎龙股份", "中微公司", "北方华创", "澜起", "紫光",
    "浪潮", "瑞芯微", "星宸科技", "利通电子", "香农芯创",
]


def _load(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _sector_rows(flows, aliases, exact=False):
    rows = []
    for name, val in flows.items():
        if exact:
            matched = name in aliases
        else:
            matched = any(a and (a in name or name in a) for a in aliases)
        if matched:
            rows.append((name, float(val[0] or 0), float(val[1] or 0)))
    return rows


def _sector_value(flows, aliases, exact=False):
    rows = _sector_rows(flows, aliases, exact=exact)
    if not rows:
        return None
    net = sum(r[1] for r in rows)
    pct = sum(r[2] for r in rows) / len(rows)
    return {"net": net, "pct": pct, "matched": [r[0] for r in rows[:8]], "n": len(rows)}


def _pct_series(hist, aliases, end_idx, lookback, exact=False):
    days = hist.get("days", [])
    vals = []
    for i in range(max(0, end_idx - lookback + 1), end_idx + 1):
        row = _sector_value(hist.get("flows", {}).get(days[i], {}), aliases, exact=exact)
        if row:
            vals.append(row["pct"])
    return vals


def _flow_series(hist, aliases, end_idx, lookback, exact=False):
    days = hist.get("days", [])
    vals = []
    for i in range(max(0, end_idx - lookback + 1), end_idx + 1):
        row = _sector_value(hist.get("flows", {}).get(days[i], {}), aliases, exact=exact)
        if row:
            vals.append(row["net"])
    return vals


def _limit_count(limit_row, aliases):
    total = 0
    matched = {}
    for name, n in (limit_row or {}).items():
        if any(a and (a in name or name in a) for a in aliases):
            total += int(n or 0)
            matched[name] = int(n or 0)
    return total, matched


def _median(values):
    return round(statistics.median(values), 3) if values else None


def _safe_rate(k, n):
    return round(k / n, 3) if n else None


def _is_tech_name(text):
    return bool(text and any(x in text for x in TECH_NAMES))


def _nowcast_evidence_for(date, log_path=NOWCAST_LOG):
    log = _load(log_path, []) or []
    positive, negative = [], []
    for rec in log:
        if rec.get("date") != date:
            continue
        name = rec.get("name") or rec.get("ticker") or ""
        if not _is_tech_name(name):
            continue
        state = rec.get("state")
        item = {"name": name, "state": state, "confidence": rec.get("confidence"),
                "features": rec.get("features") or {}}
        if state in ("ACCUMULATION_PROBABLE", "RECLAIM_ATTEMPT"):
            positive.append(item)
        elif state in ("DISTRIBUTION_PROBABLE", "OPENING_FADE", "FAKE_STRENGTH"):
            negative.append(item)

    def dedup(rows):
        best = {}
        for r in rows:
            key = (r["name"], r["state"])
            if key not in best or (r.get("confidence") or 0) > (best[key].get("confidence") or 0):
                best[key] = r
        return sorted(best.values(), key=lambda r: (r.get("confidence") or 0), reverse=True)

    return {"date": date, "positive": dedup(positive), "negative": dedup(negative),
            "source": "nowcast_log observation_only"}


def detect_day(hist, idx, nowcast_evidence=None):
    days = hist.get("days", [])
    day = days[idx]
    flows = hist.get("flows", {}).get(day, {})
    parent = _sector_value(flows, TECH_PARENT, exact=True)
    if parent is None or idx < 5:
        return {
            "date": day,
            "lights": [],
            "light_count": 0,
            "posture": "DATA_LIMITED",
            "features": {},
            "data_limits": ["DATA_LIMITED: history shorter than 6 days or parent sector missing"],
        }

    parent_flows5 = _flow_series(hist, TECH_PARENT, idx, 5, exact=True)
    parent_pcts5 = _pct_series(hist, TECH_PARENT, idx, 5, exact=True)
    prev_parent_pcts = _pct_series(hist, TECH_PARENT, idx - 1, 4, exact=True)
    neighbors = _sector_rows(flows, TECH_NEIGHBORS)
    positive_neighbors = [r for r in neighbors if r[1] > 0 and r[2] > 0]
    neighbor_net = sum(r[1] for r in neighbors)
    neighbor_best = sorted(positive_neighbors, key=lambda r: (r[1], r[2]), reverse=True)[:8]
    limit_n, limit_matched = _limit_count(hist.get("limit_up_by_industry", {}).get(day, {}),
                                          DEFENSE_CROWDING)
    nowcast_evidence = nowcast_evidence or {"positive": [], "negative": []}
    positive_nowcasts = nowcast_evidence.get("positive") or []
    nowcast_positive_count = len(positive_nowcasts)

    lights = []
    data_limits = [
        "DATA_LIMITED: 个股龙头是否不再创新低不在 rotation_history,这里用板块跌幅边际收窄做代理",
        "DATA_LIMITED: 龙头背离只能用邻域/子板块代理,不能替代新易盛/旭创等个股读数",
        "DATA_BLOCKED: 隔夜 NVDA/SOX/TSMC ADR/A50 不在本历史文件,由 overnight_anchor.py 单独处理",
    ]

    outflow_streak = sum(1 for x in parent_flows5 if x < 0)
    parent_pct = parent["pct"]
    prior_trough = min(prev_parent_pcts) if prev_parent_pcts else None
    sell_pressure_eases = bool(
        outflow_streak >= 4
        and parent["net"] < 0
        and prior_trough is not None
        and parent_pct >= prior_trough
    )
    if sell_pressure_eases:
        lights.append({
            "key": "outflow_exhaustion",
            "label": "流出衰竭",
            "why": "电子连续流出但跌幅未继续创近4日新低,卖压边际收窄",
        })

    neighborhood_new_money = bool(
        parent["net"] < 0
        and (len(positive_neighbors) >= 3 or neighbor_net > 0 or nowcast_positive_count >= 3)
    )
    if neighborhood_new_money:
        why = "电子仍流出,但科技邻域已有多条子线正流入/收正"
        if nowcast_positive_count >= 3 and len(positive_neighbors) < 3 and neighbor_net <= 0:
            why = "电子仍流出,但 watch/nowcast 中多个科技锚出现积累/修复观察"
        lights.append({
            "key": "neighborhood_new_money",
            "label": "邻域新钱",
            "why": why,
        })

    defense_crowding = bool(limit_n >= 3)
    if defense_crowding:
        lights.append({
            "key": "defense_crowding",
            "label": "防御拥挤",
            "why": f"防御/电力相关涨停 {limit_n} 家,防御交易可能拥挤",
        })

    leader_divergence_proxy = bool(
        parent["net"] < 0
        and (positive_neighbors or nowcast_positive_count)
        and (parent_pct < 0 or len(positive_neighbors) >= 2 or nowcast_positive_count >= 2)
    )
    if leader_divergence_proxy:
        why = "母板块仍弱,但科技邻域最强子线已经率先转正"
        if nowcast_positive_count:
            examples = " / ".join(f"{x['name']}:{x['state']}" for x in positive_nowcasts[:4])
            why = f"母板块弱,但个股观察已有正向 nowcast: {examples}"
        lights.append({
            "key": "leader_divergence_proxy",
            "label": "龙头背离代理",
            "why": why,
        })

    count = len(lights)
    if count >= 3:
        posture = "ALLOW_SMALL_TEST_ONLY"
    elif count >= 2:
        posture = "FREEZE_CURRENT_HOT_SIDE"
    elif count == 1:
        posture = "WATCH_REPAIR_SETUPS"
    else:
        posture = "NO_PRECURSOR"

    return {
        "date": day,
        "lights": lights,
        "light_count": count,
        "posture": posture,
        "features": {
            "parent": {"net": round(parent["net"], 1), "pct": round(parent["pct"], 2),
                       "matched": parent["matched"]},
            "parent_outflow_days_5": outflow_streak,
            "prior_parent_pct_trough_4d": round(prior_trough, 2) if prior_trough is not None else None,
            "tech_neighbor_positive_count": len(positive_neighbors),
            "tech_neighbor_net": round(neighbor_net, 1),
            "tech_neighbor_best": [{"sector": r[0], "net": round(r[1], 1), "pct": round(r[2], 2)}
                                   for r in neighbor_best],
            "tech_positive_nowcasts": positive_nowcasts[:8],
            "tech_negative_nowcasts": (nowcast_evidence.get("negative") or [])[:8],
            "defense_limit_up_count": limit_n,
            "defense_limit_up_matched": limit_matched,
        },
        "data_limits": data_limits,
    }


def _future_parent_pct(hist, idx, horizon):
    days = hist.get("days", [])
    if idx + horizon >= len(days):
        return None
    vals = []
    for j in range(idx + 1, idx + horizon + 1):
        row = _sector_value(hist.get("flows", {}).get(days[j], {}), TECH_PARENT, exact=True)
        if row is None:
            return None
        vals.append(row["pct"])
    return sum(vals)


def evaluate_history(hist, seed=17, include_latest_nowcast=True):
    days = hist.get("days", [])
    reads = [detect_day(hist, i) for i in range(len(days))]
    scored = []
    all_fwd1 = []
    all_fwd2 = []
    for i, r in enumerate(reads):
        f1 = _future_parent_pct(hist, i, 1)
        f2 = _future_parent_pct(hist, i, 2)
        if f1 is not None:
            all_fwd1.append(f1)
        if f2 is not None:
            all_fwd2.append(f2)
        if r["light_count"] and f1 is not None:
            rec = dict(r)
            rec["fwd1_parent_pct"] = round(f1, 2)
            rec["fwd2_parent_pct"] = round(f2, 2) if f2 is not None else None
            scored.append(rec)

    by_threshold = {}
    rng = random.Random(seed)
    for k in (1, 2, 3, 4):
        subset = [r for r in scored if r["light_count"] >= k]
        f1s = [r["fwd1_parent_pct"] for r in subset if r.get("fwd1_parent_pct") is not None]
        f2s = [r["fwd2_parent_pct"] for r in subset if r.get("fwd2_parent_pct") is not None]
        n = len(f1s)
        rand_medians = []
        rand_pos = []
        pool = list(range(len(all_fwd1)))
        for _ in range(200):
            if not n or len(pool) < n:
                break
            picks = rng.sample(pool, n)
            vals = [all_fwd1[p] for p in picks]
            rand_medians.append(statistics.median(vals))
            rand_pos.append(sum(1 for v in vals if v > 0) / len(vals))
        by_threshold[f"lights>={k}"] = {
            "n": n,
            "fwd1_pos_rate": _safe_rate(sum(1 for v in f1s if v > 0), len(f1s)),
            "fwd1_median_pct": _median(f1s),
            "fwd2_pos_rate": _safe_rate(sum(1 for v in f2s if v > 0), len(f2s)),
            "fwd2_median_pct": _median(f2s),
            "random_fwd1_pos_rate_mean": round(sum(rand_pos) / len(rand_pos), 3) if rand_pos else None,
            "random_fwd1_median_mean": round(sum(rand_medians) / len(rand_medians), 3) if rand_medians else None,
        }

    latest = reads[-1] if reads else {}
    if include_latest_nowcast and days:
        ev = _nowcast_evidence_for(days[-1])
        latest = detect_day(hist, len(days) - 1, nowcast_evidence=ev)
        latest["scope"] = "sector_settle + nowcast_observation_only"
        latest["nowcast_evidence_source"] = ev["source"]
    return {
        "as_of": days[-1] if days else "?",
        "history_days": len(days),
        "latest": latest,
        "calibration": by_threshold,
        "recent_reads": reads[-8:],
        "scored_examples": scored[-12:],
        "claim_allowed": False,
        "sample_policy": "n<30 independent forward episodes => no alpha/win-rate language; use only as calibration.",
        "action_policy": {
            "lights>=2": "停止在当前热边继续加仓;观察被卖主题的结构位",
            "lights>=3": "只允许小仓条款单进入人工复核;确认日禁止追涨",
            "always": "每批必须有失效线;前兆信号自身继续判分",
        },
        "data_limits": [
            "rotation_history provides sector settle flow/pct and limit-up industry counts only",
            "latest read may include nowcast observation data; historical calibration remains sector-only",
            "leader price structure and overnight anchors require separate feeds",
        ],
        "note": "L0.5 前兆层;只做注意力/仓位节奏校准。不是买卖指令。",
    }


def render(report):
    latest = report.get("latest", {})
    lines = [f"## L0.5 前兆层 v0({report.get('as_of')})", ""]
    lines.append(f"最新: {latest.get('posture')} · 亮灯 {latest.get('light_count', 0)}")
    for light in latest.get("lights", []):
        lines.append(f"- {light['label']}: {light['why']}")
    if not latest.get("lights"):
        lines.append("- 无前兆灯。")
    lines.append("")
    lines.append("### 历史校准(只用 rotation_history,claim_allowed=false)")
    for k, row in report.get("calibration", {}).items():
        lines.append(
            f"- {k}: n={row['n']}, T+1>0 {row['fwd1_pos_rate']}, "
            f"T+1中位 {row['fwd1_median_pct']}%, 随机中位 {row['random_fwd1_median_mean']}%"
        )
    lines.append("")
    for item in report.get("data_limits", []):
        lines.append(f"- DATA_LIMITED: {item}")
    lines.append("")
    lines.append("不是买卖指令；研究信号，human executes.")
    return "\n".join(lines)


def selftest():
    hist = {
        "days": ["d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8"],
        "flows": {
            "d1": {"电子": [-10, -1], "计算机": [-1, -1], "光通信模块": [-1, -1]},
            "d2": {"电子": [-12, -2], "计算机": [-1, -1], "光通信模块": [-1, -1]},
            "d3": {"电子": [-13, -3], "计算机": [-1, -1], "光通信模块": [-1, -1]},
            "d4": {"电子": [-14, -4], "计算机": [-1, -1], "光通信模块": [-1, -1]},
            "d5": {"电子": [-15, -5], "计算机": [-1, -1], "光通信模块": [-1, -1]},
            "d6": {"电子": [-11, -3], "计算机": [4, 1.2], "光通信模块": [5, 2.0],
                   "印制电路板": [3, 1.0]},
            "d7": {"电子": [8, 2], "计算机": [2, 1], "光通信模块": [1, 1]},
            "d8": {"电子": [-4, -1], "计算机": [-1, -1], "光通信模块": [-1, -1]},
        },
        "limit_up_by_industry": {"d6": {"电力": 3}},
    }
    import tempfile
    tmp = tempfile.mktemp(suffix=".json")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump([{"date": "d8", "name": "新易盛", "state": "ACCUMULATION_PROBABLE",
                    "confidence": 0.8}], fh)
    ev = _nowcast_evidence_for("d8", log_path=tmp)
    os.remove(tmp)
    rep = evaluate_history(hist, include_latest_nowcast=False)
    latest_d6 = detect_day(hist, 5)
    latest_d8 = detect_day(hist, 7, nowcast_evidence=ev)
    checks = [
        ("d6 lights >=3", latest_d6["light_count"] >= 3),
        ("posture allows only small test", latest_d6["posture"] == "ALLOW_SMALL_TEST_ONLY"),
        ("nowcast evidence can light leader divergence",
         any(x["key"] == "leader_divergence_proxy" for x in latest_d8["lights"])),
        ("claim disabled", rep["claim_allowed"] is False),
        ("render disclaimer", "不是买卖指令" in render(rep)),
        ("data limits explicit", bool(rep["data_limits"])),
    ]
    for name, ok in checks:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print(f"lead_precursor selftest: {sum(ok for _, ok in checks)}/{len(checks)}")
    return all(ok for _, ok in checks)


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    hist = _load(HIST, {})
    report = evaluate_history(hist)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print(render(report))
    print(f"[written] {OUT}")


if __name__ == "__main__":
    main()
