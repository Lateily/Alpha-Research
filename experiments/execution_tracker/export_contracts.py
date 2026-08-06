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
from nightly_context import run_id, target_trade_date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
V2 = os.path.join(REPO, "public", "data", "v2")
DISCLAIMER = "不是买卖指令;研究信号,human executes."


STALE_HOURS = 20  # 审查F5:超过一个交易日的引擎产出不许当新鲜货导出

# 事件驱动账本:无交易时**不变才是正确的**,拿 mtime 判陈旧是误判。
# 它们的新鲜度由内容判(nav_history 末条日期必须==target),不由文件时间判。
# fund.json 是静态配置(初始资金/政策),根本没有日期维度。
EVENT_DRIVEN = {"model_fund/fund.json", "model_fund/orders.json",
                "model_fund/decision_log.json", "model_fund/human_shadow.json"}
# 必须每日更新的账本:末条日期不等于本轮 target 即陈旧
DAILY_SERIES = {"model_fund/nav_history.json": "date"}


def _internal_meta(obj):
    """读产物内部的时间戳与自报状态(如 overnight_anchor 的 bias=DATA_BLOCKED)。"""
    meta = {}
    if isinstance(obj, dict):
        for k in ("as_of", "checked_at", "generated_at", "timestamp", "date"):
            v = obj.get(k)
            if isinstance(v, str) and v[:8].isdigit():
                meta["as_of"] = v[:8]
                break
        # 产物**显式自报**的 internal_status 优先(overnight_anchor 用它区分
        # "抓不全 PARTIAL_OK" 与 "完全没抓到 DATA_BLOCKED")。
        self_reported = str(obj.get("internal_status") or "")
        if self_reported in ("DATA_BLOCKED", "PARTIAL_OK", "OK"):
            meta["internal_status"] = self_reported
        else:
            for k in ("status", "bias", "verdict"):
                if str(obj.get(k, "")).startswith("DATA_BLOCKED"):
                    meta["internal_status"] = "DATA_BLOCKED"
        # 产物自报的 target_trade_date 与本轮不符 ⇒ 陈旧,不看 mtime 也能判
        tgt = target_trade_date()
        got = str(obj.get("target_trade_date") or meta.get("as_of") or "")[:8]
        if tgt and got and got != tgt:
            meta["stale"] = True
            meta["stale_why"] = f"target_trade_date {got} ≠ 本轮 {tgt}"
    return meta


def _load(relpath):
    """读引擎产出 → (obj, err, meta);meta 含 age_hours/as_of/internal_status/stale。"""
    p = os.path.join(HERE, relpath)
    if not os.path.exists(p):
        return None, f"missing:{relpath}", {}
    try:
        with open(p, encoding="utf-8") as fh:
            obj = json.load(fh)
    except Exception as e:  # 损坏文件 = 显式 BLOCKED,不吞
        return None, f"unreadable:{relpath}:{e}", {}
    meta = _internal_meta(obj)
    meta["age_hours"] = round((time.time() - os.path.getmtime(p)) / 3600.0, 1)
    if relpath in EVENT_DRIVEN:
        meta["cadence"] = "event_driven"          # 无变动即正确,不按 mtime 判陈旧
    elif relpath in DAILY_SERIES:
        meta["cadence"] = "daily_series"
        key = DAILY_SERIES[relpath]
        tgt = target_trade_date()
        last = str((obj[-1] or {}).get(key) or "")[:8] if isinstance(obj, list) and obj else ""
        meta["last_entry"] = last
        if tgt and last != tgt:
            meta["stale"] = True
            meta["stale_why"] = f"末条 {last or '无'} ≠ 本轮 {tgt}"
    elif meta["age_hours"] > STALE_HOURS:
        meta["stale"] = True
    return obj, None, meta


def _resolve_status(blocked, sources_meta):
    """**两个正交维度**,不许把其中一个写成另一个:

      pipeline_status —— 本轮流水线是否成功产出并可发布(OK / STALE_INPUT / DATA_BLOCKED)
      data_quality    —— 信息是否完整(COMPLETE / PARTIAL / BLOCKED)

    此前只有一个 status:隔夜锚 PARTIAL_OK 被包装成顶层 OK,meta.report 进而
    COMPLETE —— 下游只读顶层就会误以为宏观数据完整。
    「成功发布」不等于「信息完整」。
    返回 (pipeline_status, data_quality, degraded_sources)。
    """
    degraded = []
    if blocked:
        return "DATA_BLOCKED", "BLOCKED", degraded
    has_blocked = False
    has_stale = False
    has_partial = False
    for name, m in (sources_meta or {}).items():
        internal = m.get("internal_status")
        stale = bool(m.get("stale"))
        if internal == "DATA_BLOCKED" or stale:
            has_blocked = has_blocked or internal == "DATA_BLOCKED"
            has_stale = has_stale or stale
            degraded.append({"source": name, "internal_status": internal,
                             "stale": stale,
                             "why": m.get("stale_why")})
        elif internal == "PARTIAL_OK":
            has_partial = True
            degraded.append({"source": name, "internal_status": "PARTIAL_OK"})
    # Aggregate after scanning every source. Mutating the verdict in iteration order
    # made DATA_BLOCKED -> stale yield PARTIAL while the reverse order yielded BLOCKED.
    pipeline = "STALE_INPUT" if has_blocked or has_stale else "OK"
    quality = "BLOCKED" if has_blocked else (
        "PARTIAL" if has_stale or has_partial else "COMPLETE"
    )
    return pipeline, quality, degraded


def _contract(name, data, sources, blocked=None, sources_meta=None):
    pipeline, quality, degraded = _resolve_status(blocked, sources_meta)
    return {"contract": name, "schema_version": "v2.2",
            "generated_at": time.strftime("%Y%m%d %H:%M:%S"),
            "run_id": run_id(), "target_trade_date": target_trade_date(),
            "sources": sources,
            "sources_meta": sources_meta or {},
            # status 保留为 pipeline_status 的别名(向后兼容),但**新消费方应读
            # data_quality** —— 只读 status 会把「发布成功」误解成「信息完整」。
            "status": pipeline,
            "pipeline_status": pipeline,
            "data_quality": quality,
            "degraded_sources": degraded,
            "blocked_why": blocked, "data": data, "disclaimer": DISCLAIMER}


def build_model_portfolio_state():
    fund, e1, m1 = _load("model_fund/fund.json")
    nav, e2, m2 = _load("model_fund/nav_history.json")
    orders, e3, m3 = _load("model_fund/orders.json")
    smeta = {"fund.json": m1, "nav_history.json": m2, "orders.json": m3}
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
                "win_rate_note": (f"closed n={len(closed)} < 30,胜率语言免谈"
                                  if len(closed) < 30 else
                                  f"closed n={len(closed)} ≥ 30,可按判分协议讨论胜率(仍需独立性审查)")}
    return _contract("model_portfolio_state", data,
                     ["model_fund/fund.json", "model_fund/nav_history.json",
                      "model_fund/orders.json"], blocked, smeta)


def _make_card(o, drows):
    """单卡组装。字段名以真实 orders.json 为准(审查F1):
    realized_R / stop_reference / take_profit_reference / fill_price / shares。"""
    tk = o.get("ticker")
    return {
        "ticker": tk, "name": o.get("name"), "status": o.get("status"),
        "fill_date": o.get("fill_date") or o.get("entry_date"),
        "entry": o.get("fill_price") or o.get("entry"),
        "qty": o.get("shares") or o.get("qty"),
        "stop": o.get("stop_reference") or o.get("stop"),
        "target": o.get("take_profit_reference") or o.get("target"),
        "exit_date": o.get("exit_date") or o.get("close_date"),
        "exit_price": o.get("exit_price") or o.get("close_price"),
        "realized_r": o.get("realized_R") or o.get("realized_r") or o.get("r_mult"),
        "reasoning_trail": [d for d in drows if d.get("ticker") == tk][-6:],
        "month": (str(o.get("fill_date") or "")[:6] or None),
    }


def build_trade_cards():
    orders, e1, m1 = _load("model_fund/orders.json")
    dlog, e2, m2 = _load("model_fund/decision_log.json")
    smeta = {"orders.json": m1, "decision_log.json": m2}
    blocked = e1  # decision_log 缺失可降级
    cards = None
    if not blocked:
        rows = orders if isinstance(orders, list) else orders.get("orders", [])
        drows = (dlog if isinstance(dlog, list) else (dlog or {}).get("log", [])) if not e2 else []
        cards = [_make_card(o, drows) for o in rows]
    return _contract("trade_cards", cards,
                     ["model_fund/orders.json", "model_fund/decision_log.json"], blocked, smeta)


def build_premarket_frame():
    anchor, e1, m1 = _load("overnight_anchor.json")
    lights, e2, m2 = _load("lead_precursor.json")
    watch, e3, m3 = _load("watch_dynamic.json")
    smeta = {"overnight_anchor.json": m1, "lead_precursor.json": m2,
             "watch_dynamic.json": m3}
    parts, blocked_parts = {}, {}
    for key, obj, err, m in (("overnight_anchor", anchor, e1, m1),
                             ("precursor_lights", lights, e2, m2),
                             ("watch_list", watch, e3, m3)):
        # 审查F5:内部自报 blocked 或超龄的部件,进 blocked 区而不是伪装新鲜
        why = err or ("internal:DATA_BLOCKED" if m.get("internal_status") == "DATA_BLOCKED"
                      else ("stale:%sh" % m.get("age_hours") if m.get("stale") else None))
        if why:
            blocked_parts[key] = why
        else:
            parts[key] = obj
    blocked = None if parts else "; ".join(str(v) for v in blocked_parts.values())
    if blocked_parts and parts:
        parts["_partial_blocked"] = blocked_parts
    return _contract("premarket_frame", parts or None,
                     ["overnight_anchor.json", "lead_precursor.json",
                      "watch_dynamic.json"], blocked, smeta)


def build_passthrough(name, relpath):
    obj, err, meta = _load(relpath)
    return _contract(name, obj, [relpath], err, {relpath: meta})


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
            "run_id": run_id(), "target_trade_date": target_trade_date(),
            "contracts": {}, "disclaimer": DISCLAIMER}
    for fname, builder in BUILDERS:
        c = builder()
        with open(os.path.join(v2dir, fname), "w", encoding="utf-8") as fh:
            json.dump(c, fh, ensure_ascii=False, indent=1)
        meta["contracts"][fname] = {"status": c["status"],
                                    "pipeline_status": c["pipeline_status"],
                                    "data_quality": c["data_quality"],
                                    "degraded_sources": c["degraded_sources"],
                                    "blocked_why": c["blocked_why"]}
    vals = list(meta["contracts"].values())
    # report = 流水线是否全部成功(可发布);data_quality = 信息是否完整。
    # 两者必须分开报 —— 否则 PARTIAL 的宏观数据会被 COMPLETE 掩盖。
    meta["report"] = "COMPLETE" if all(v["pipeline_status"] == "OK" for v in vals) else "PARTIAL"
    meta["data_quality"] = ("COMPLETE" if all(v["data_quality"] == "COMPLETE" for v in vals)
                            else ("BLOCKED" if any(v["data_quality"] == "BLOCKED" for v in vals)
                                  else "PARTIAL"))
    meta["degraded_sources"] = sorted({d["source"] for v in vals for d in v["degraded_sources"]})
    # 口径:业务契约 = BUILDERS 产出的那些;meta.json / current_run.json 是**控制文件**,
    # 不计入契约数(此前对外说「9 份契约」是把控制文件也算进去了)。
    meta["business_contract_count"] = len(vals)
    meta["control_files"] = ["meta.json", "current_run.json"]
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
        with open(os.path.join(td, "model_portfolio_state.json"), encoding="utf-8") as fh:
            one = json.load(fh)
        ok.append(("disclaimer present", one["disclaimer"] == DISCLAIMER))
        ok.append(("schema version v2.2(新增 pipeline_status/data_quality)",
                   one["schema_version"] == "v2.2"))
        ok.append(("status 保留为 pipeline_status 别名(向后兼容)",
                   one["status"] == one["pipeline_status"]))
        ok.append(("data_quality 与 pipeline_status 正交",
                   one["data_quality"] in ("COMPLETE", "PARTIAL", "BLOCKED")))
        ok.append(("sources_meta present", "sources_meta" in one))
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
