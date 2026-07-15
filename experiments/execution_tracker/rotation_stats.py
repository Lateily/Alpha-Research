#!/usr/bin/env python3
"""
rotation_stats.py — rotation lab statistical layer v0.

This is the first statistical layer above rotation_panel.py. It does three
things without making an alpha claim:
1) builds an in-window one-day transition matrix from each sector's 5-day flow
   sequence;
2) measures leader breadth from momentum_prefilter top names;
3) flags concentration/crowding patterns for review.

Important: the transition matrix is descriptive until enough daily snapshots are
saved and scored forward. It is not a tradable edge.

不是买卖指令；研究信号，human executes。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "rotation_stats.json")

from rotation_panel import classify  # noqa: E402
import sector_keys  # noqa: E402


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def state_for_seq(seq):
    if len(seq) < 3:
        return "DATA_BLOCKED"
    return classify(seq)[1]


def build_transition(panel):
    matrix = {}
    counts = {}
    rows = []
    for bucket in ("inflow_cont", "warming", "flicker", "outflow_cont"):
        for r in panel.get(bucket, []):
            seq = r.get("seq", "")
            if len(seq) < 5:
                continue
            prev_state = state_for_seq(seq[:-1])
            next_state = state_for_seq(seq[1:])
            matrix.setdefault(prev_state, {})
            matrix[prev_state][next_state] = matrix[prev_state].get(next_state, 0) + 1
            counts[prev_state] = counts.get(prev_state, 0) + 1
            rows.append({"sector": r["sector"], "seq": seq, "from": prev_state, "to": next_state})
    probs = {}
    for src, dests in matrix.items():
        total = sum(dests.values())
        probs[src] = {dst: round(n / total, 3) for dst, n in sorted(dests.items())}
    return {"counts": counts, "matrix_counts": matrix, "matrix_prob": probs, "examples": rows[:20]}


def build_leader_breadth(momentum, mapping=None):
    mapping = mapping or sector_keys.load_map()
    cands = momentum.get("candidates") or []
    groups = {}
    for rank, c in enumerate(cands, 1):
        label = sector_keys.group_label(c.get("industry") or c.get("name") or "", mapping)
        g = groups.setdefault(label, {"count": 0, "top10": 0, "names": [], "ret10_sum": 0.0})
        g["count"] += 1
        g["top10"] += 1 if rank <= 10 else 0
        g["ret10_sum"] += float(c.get("ret10") or 0.0)
        if len(g["names"]) < 8:
            g["names"].append(f"{c.get('name')}({c.get('ret10')}%)")
    out = []
    total = len(cands) or 1
    for label, g in groups.items():
        out.append({"group": label, "count": g["count"], "share_top30": round(g["count"] / total, 3),
                    "top10_count": g["top10"], "avg_ret10": round(g["ret10_sum"] / g["count"], 1),
                    "examples": g["names"]})
    out.sort(key=lambda r: (-r["count"], -r["top10_count"], r["group"]))
    return out


def build_stats(panel, momentum, mapping=None):
    blocked = []
    if not panel.get("days"):
        blocked.append("DATA_BLOCKED: rotation_panel.json missing days")
    if not momentum.get("candidates"):
        blocked.append("DATA_BLOCKED: momentum_prefilter.json missing candidates")
    trans = build_transition(panel)
    breadth = build_leader_breadth(momentum, mapping)
    dominant = [r for r in breadth if r["share_top30"] >= 0.30]
    return {"as_of": (momentum.get("as_of") or (panel.get("days") or ["?"])[-1]),
            "panel_days": panel.get("days", []),
            "transition": trans,
            "leader_breadth": breadth,
            "dominant_groups": dominant,
            "data_blocked": blocked,
            "claim_allowed": False,
            "note": "描述统计层;需要后续多日快照才能校准前瞻概率。不是买卖指令。"}


def render(stats):
    lines = [f"## 轮动实验室统计层 v0({stats['as_of']})", ""]
    lines.append("### 转移矩阵(窗口内描述统计,非 alpha)")
    for src, dests in sorted(stats["transition"]["matrix_prob"].items()):
        lines.append(f"- {src}: {dests}")
    lines.append("")
    lines.append("### 龙头广度 / 动量集中度")
    for row in stats["leader_breadth"][:8]:
        lines.append(f"- {row['group']}: top30 {row['count']} 席, top10 {row['top10_count']} 席, "
                     f"avg10d {row['avg_ret10']}%, 例: {', '.join(row['examples'][:4])}")
    if stats["data_blocked"]:
        lines.append("")
        lines.extend(f"- {x}" for x in stats["data_blocked"])
    lines.append("")
    lines.append("不是买卖指令；研究信号，human executes.")
    return "\n".join(lines)


def selftest():
    panel = {"days": ["d1", "d2", "d3", "d4", "d5"],
             "inflow_cont": [{"sector": "医药服务", "seq": "-++++"}],
             "warming": [{"sector": "PCB", "seq": "---++"}],
             "flicker": [{"sector": "AI", "seq": "+-+-+"}],
             "outflow_cont": [{"sector": "军工", "seq": "-----"}]}
    momentum = {"as_of": "d5", "candidates": [
        {"name": "A药", "industry": "化学制药", "ret10": 30},
        {"name": "B药", "industry": "中药", "ret10": 20},
        {"name": "C油", "industry": "石油开采", "ret10": 18},
    ]}
    s = build_stats(panel, momentum)
    checks = [
        ("transition matrix has states", bool(s["transition"]["matrix_counts"])),
        ("pharma breadth grouped", s["leader_breadth"][0]["group"] == "医药"),
        ("claim remains disabled", s["claim_allowed"] is False),
        ("render has disclaimer", "不是买卖指令" in render(s)),
    ]
    for name, ok in checks:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print(f"rotation_stats selftest: {sum(ok for _, ok in checks)}/{len(checks)}")
    return all(ok for _, ok in checks)


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    panel = _load(os.path.join(HERE, "rotation_panel.json"), {})
    momentum = _load(os.path.join(HERE, "momentum_prefilter.json"), {})
    stats = build_stats(panel, momentum)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=1)
    print(render(stats))
    print(f"[written] {OUT}")


if __name__ == "__main__":
    main()
