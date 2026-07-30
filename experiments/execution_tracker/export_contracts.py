#!/usr/bin/env python3
"""export_contracts.py — 引擎产出 → 前端契约层(public/data/v2/)。

章程接口:引擎写、前端读,单向流动;每份契约带 schema_version / generated_at /
staleness 来源戳 / 免责句。字段说明见 docs/contracts/。缺上游文件 = 该契约标
DATA_BLOCKED 并照常落盘(前端显式展示缺什么,永不伪装)。

用法: export_contracts.py [--selftest]
不是买卖指令;研究信号,human executes.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
V2 = os.path.join(REPO, "public", "data", "v2")
DISCLAIMER = "不是买卖指令;研究信号,human executes."


def _load(relpath):
    """读引擎产出;缺文件返回 (None, why)。"""
    p = os.path.join(HERE, relpath)
    if not os.path.exists(p):
        return None, f"missing:{relpath}"
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh), None
    except Exception as e:  # 损坏文件 = 显式 BLOCKED,不吞
        return None, f"unreadable:{relpath}:{e}"


def _contract(name, data, sources, blocked=None):
    return {"contract": name, "schema_version": "v2.0",
            "generated_at": time.strftime("%Y%m%d %H:%M:%S"),
            "sources": sources,
            "status": "DATA_BLOCKED" if blocked else "OK",
            "blocked_why": blocked, "data": data, "disclaimer": DISCLAIMER}


def build_model_portfolio_state():
    fund, e1 = _load("model_fund/fund.json")
    nav, e2 = _load("model_fund/nav_history.json")
    orders, e3 = _load("model_fund/orders.json")
    blocked = e1 or e2 or e3
    data = None
    if not blocked:
        rows = orders if isinstance(orders, list) else orders.get("orders", [])
        open_pos = [o for o in rows if o.get("status") == "filled"]
        closed = [o for o in rows if o.get("status") == "closed"]
        data = {"paper_only": bool(fund.get("paper_only", True)),
                "initial_capital": fund.get("initial_capital"),
                "cash": fund.get("cash"),
                "nav_series": nav,
                "nav_latest": nav[-1] if nav else None,
                "open_positions": open_pos,
                "closed_trades": closed,
                "closed_trades_n": len(closed),
                "win_rate_note": f"closed n={len(closed)} < 30,胜率语言免谈"}
    return _contract("model_portfolio_state", data,
                     ["model_fund/fund.json", "model_fund/nav_history.json",
                      "model_fund/orders.json"], blocked)


def build_trade_cards():
    orders, e1 = _load("model_fund/orders.json")
    dlog, e2 = _load("model_fund/decision_log.json")
    blocked = e1  # decision_log 缺失可降级
    cards = None
    if not blocked:
        rows = orders if isinstance(orders, list) else orders.get("orders", [])
        drows = (dlog if isinstance(dlog, list) else (dlog or {}).get("log", [])) if not e2 else []
        cards = []
        for o in rows:
            tk = o.get("ticker")
            cards.append({
                "ticker": tk, "name": o.get("name"), "status": o.get("status"),
                "fill_date": o.get("fill_date") or o.get("entry_date"),
                "entry": o.get("fill_price") or o.get("entry"),
                "qty": o.get("qty") or o.get("shares"),
                "stop": o.get("stop"), "target": o.get("target"),
                "exit_date": o.get("exit_date") or o.get("close_date"),
                "exit_price": o.get("exit_price") or o.get("close_price"),
                "realized_r": o.get("realized_r") or o.get("r_mult"),
                "reasoning_trail": [d for d in drows if d.get("ticker") == tk][-6:],
                "week": (str(o.get("fill_date") or "")[:6] or None),
            })
    return _contract("trade_cards", cards,
                     ["model_fund/orders.json", "model_fund/decision_log.json"], blocked)


def build_premarket_frame():
    anchor, e1 = _load("overnight_anchor.json")
    lights, e2 = _load("lead_precursor.json")
    watch, e3 = _load("watch_dynamic.json")
    parts, blocked_parts = {}, {}
    for key, obj, err in (("overnight_anchor", anchor, e1),
                          ("precursor_lights", lights, e2),
                          ("watch_list", watch, e3)):
        if err:
            blocked_parts[key] = err
        else:
            parts[key] = obj
    blocked = None if parts else "; ".join(blocked_parts.values())
    if blocked_parts and parts:
        parts["_partial_blocked"] = blocked_parts  # 部分缺失也要显式说
    return _contract("premarket_frame", parts or None,
                     ["overnight_anchor.json", "lead_precursor.json",
                      "watch_dynamic.json"], blocked)


def build_passthrough(name, relpath):
    obj, err = _load(relpath)
    return _contract(name, obj, [relpath], err)


BUILDERS = [
    ("model_portfolio_state.json", build_model_portfolio_state),
    ("trade_cards.json", build_trade_cards),
    ("premarket_frame.json", build_premarket_frame),
    ("rotation_panel.json", lambda: build_passthrough("rotation_panel", "rotation_panel.json")),
    ("red_flags.json", lambda: build_passthrough("red_flags", "red_flags.json")),
    ("battery.json", lambda: build_passthrough("battery", "battery.json")),
    ("position_review.json", lambda: build_passthrough("position_review", "position_review.json")),
]


def export_all(v2dir=None):
    v2dir = v2dir or V2
    os.makedirs(v2dir, exist_ok=True)
    meta = {"generated_at": time.strftime("%Y%m%d %H:%M:%S"),
            "contracts": {}, "disclaimer": DISCLAIMER}
    for fname, builder in BUILDERS:
        c = builder()
        with open(os.path.join(v2dir, fname), "w", encoding="utf-8") as fh:
            json.dump(c, fh, ensure_ascii=False, indent=1)
        meta["contracts"][fname] = {"status": c["status"], "blocked_why": c["blocked_why"]}
    meta["report"] = ("COMPLETE" if all(v["status"] == "OK" for v in meta["contracts"].values())
                      else "PARTIAL")
    with open(os.path.join(v2dir, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    return meta


def selftest():
    import tempfile
    ok = []
    with tempfile.TemporaryDirectory() as td:
        meta = export_all(td)
        files = set(os.listdir(td))
        ok.append(("meta.json written", "meta.json" in files))
        ok.append(("all contracts written", all(f in files for f, _ in BUILDERS)))
        one = json.load(open(os.path.join(td, "model_portfolio_state.json")))
        ok.append(("disclaimer present", one["disclaimer"] == DISCLAIMER))
        ok.append(("schema version", one["schema_version"] == "v2.0"))
        ok.append(("status field honest", one["status"] in ("OK", "DATA_BLOCKED")))
        ok.append(("meta report honest", meta["report"] in ("COMPLETE", "PARTIAL")))
    for name, passed in ok:
        print(("  ✓ " if passed else "  ✗ ") + name)
    print(f"export_contracts selftest: {sum(p for _, p in ok)}/{len(ok)}")
    return all(p for _, p in ok)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    meta = export_all()
    for k, v in meta["contracts"].items():
        print(f"{k}: {v['status']}" + (f" ({v['blocked_why']})" if v["blocked_why"] else ""))
    print(f"[report] {meta['report']}  → public/data/v2/")
    print(DISCLAIMER)
