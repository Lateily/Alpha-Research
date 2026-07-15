#!/usr/bin/env python3
"""
sector_keys.py — canonical sector alias helpers for execution_tracker.

Purpose: remove fragile text joins such as "PCB/AI硬件" vs "印制电路板" vs
"元件". The mapping only helps engines decide what needs review; it never
upgrades a signal by itself.

不是买卖指令；研究信号，human executes。
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_PATH = os.path.join(HERE, "sector_key_map.json")


def load_map(path=MAP_PATH):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def aliases_for(text, mapping=None):
    if not text:
        return set()
    mapping = mapping or load_map()
    hits = {text}
    for key, spec in mapping.get("keys", {}).items():
        aliases = set(spec.get("aliases", []))
        label = spec.get("label", key)
        candidates = aliases | {label, key}
        if any(a and (a in text or text in a) for a in candidates):
            hits |= aliases | {label, key}
    return {x for x in hits if x}


def sector_match(left, right, mapping=None):
    if not left or not right:
        return False
    if left in right or right in left:
        return True
    la = aliases_for(left, mapping)
    ra = aliases_for(right, mapping)
    return bool(la & ra)


def best_streak(signal_sector, sector_streaks, mapping=None):
    best = 0
    best_sector = None
    for sector, streak in sector_streaks.items():
        if sector_match(signal_sector, sector, mapping):
            if streak > best:
                best = streak
                best_sector = sector
    return best, best_sector


def group_label(text, mapping=None):
    mapping = mapping or load_map()
    for key, spec in mapping.get("keys", {}).items():
        if sector_match(text, spec.get("label", key), mapping):
            return spec.get("label", key)
    return "其他"


def selftest():
    m = load_map()
    checks = [
        ("PCB aliases match", sector_match("PCB/AI硬件", "印制电路板", m)),
        ("pharma aliases match", sector_match("医药商业", "零售药房", m)),
        ("unrelated sectors do not match", not sector_match("医药商业", "油田服务", m)),
        ("best streak returns matched sector", best_streak("PCB/AI硬件", {"印制电路板": 3, "油田服务": 5}, m) == (3, "印制电路板")),
        ("group label returns pharma", group_label("中药Ⅲ", m) == "医药"),
    ]
    for name, ok in checks:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print(f"sector_keys selftest: {sum(ok for _, ok in checks)}/{len(checks)}")
    return all(ok for _, ok in checks)


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
