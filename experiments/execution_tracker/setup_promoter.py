#!/usr/bin/env python3
"""
setup_promoter.py — P3 晋级桥(定盘后跑;只出 PROMOTION_REVIEW,不注册不成交)

对每条 pending 判分的 execution_gate 个股信号,机械核对三条件门 + 两票制,
产出晋级复核单写入 promotion_queue.json。**注册动作留给人审后的结算流程**——
本模块消灭的是"信号注册了、没人升级"的缝隙,不是人审本身。

三条件门(v1.1):
  G1 regime:最新官方样本 market_state ∈ {RISK_ON, WEAK_REPAIR}
  G2 板块连续:信号 sector 在轮动面板 streak >= 2(WARMING 及以上)
  G3 触发区打印:当日 bar 触及 trigger 区且收盘未破 invalidation 价

不是买卖指令；研究信号，human executes。
"""

import json
import os
import re
import sys

import sector_keys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "promotion_queue.json")
RISK_PCT = 0.0075          # 提案风险预算 0.75% NAV [unvalidated intuition]

# ── P0-B 质检消费闸门:红旗/电池/新鲜度真正控晋级 ──
QC_MAX_AGE_H = 26          # 质检输入超龄线(mtime 超此 → 过期)
RED_FLAGS_FILE = "red_flags.json"
BATTERY_FILE = "battery.json"
PANEL_FILE = "rotation_panel.json"


class QcUnavailable(RuntimeError):
    """缺文件/坏schema/面板过期 → 无法裁决;调用方打 DATA_BLOCKED 末行并 exit 1。"""


def _prev_trading_day(day):
    """近似前一交易日:回退1天并跳过周末(节假日误差由 mtime 26h 线兜底)。"""
    import datetime as _dt
    d = _dt.datetime.strptime(day, "%Y%m%d").date() - _dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= _dt.timedelta(days=1)
    return d.strftime("%Y%m%d")


def _freshness(path, checked_at, now):
    """FRESH / STALE_FILE(mtime>26h) / STALE_CHECKED_AT(内部戳非当日/前一交易日)。"""
    import time as _t
    age_h = (now - os.path.getmtime(path)) / 3600.0
    if age_h > QC_MAX_AGE_H:
        return f"STALE_FILE(mtime {age_h:.1f}h>{QC_MAX_AGE_H}h)"
    today = _t.strftime("%Y%m%d", _t.localtime(now))
    if str(checked_at) not in (today, _prev_trading_day(today)):
        return f"STALE_CHECKED_AT({checked_at})"
    return "FRESH"


def load_qc_context(here=None, now=None):
    """运行开始时读取 red_flags/battery/rotation_panel 的内容与 mtime。
    缺文件/坏schema、或轮动面板缺失/过期(G2 无法裁决)→ QcUnavailable;
    红旗/电池文件过期是可裁决状态 → 记 freshness,由 qc_decide 判 BLOCKED_STALE_INPUT。"""
    import time as _t
    here = here or HERE
    now = _t.time() if now is None else now
    ctx = {}
    for key, fn in (("red", RED_FLAGS_FILE), ("bat", BATTERY_FILE)):
        p = os.path.join(here, fn)
        if not os.path.exists(p):
            raise QcUnavailable(f"{fn} 缺失(红旗闸门/六维电池未跑,晋级无法裁决)")
        try:
            data = json.load(open(p, encoding="utf-8"))
            results = data["results"]
            assert isinstance(results, list)
        except Exception as e:
            raise QcUnavailable(f"{fn} 坏schema: {e}")
        ctx[key] = {"results": results, "fresh": _freshness(p, data.get("checked_at"), now)}
    panel = os.path.join(here, PANEL_FILE)
    if not os.path.exists(panel):
        raise QcUnavailable(f"{PANEL_FILE} 缺失(G2 板块连续无法裁决)")
    try:
        json.load(open(panel, encoding="utf-8"))
    except Exception as e:
        raise QcUnavailable(f"{PANEL_FILE} 坏schema: {e}")
    panel_age_h = (now - os.path.getmtime(panel)) / 3600.0
    if panel_age_h > QC_MAX_AGE_H:
        raise QcUnavailable(
            f"{PANEL_FILE} 过期(mtime {panel_age_h:.1f}h>{QC_MAX_AGE_H}h,G2 无法裁决)")
    red_by = {r["ts_code"]: r.get("verdict") for r in ctx["red"]["results"] if r.get("ts_code")}
    bat_by = {}
    for r in ctx["bat"]["results"]:
        if not r.get("ts_code"):
            continue
        dims = r.get("dims") or {}
        bat_by[r["ts_code"]] = {
            "verdict": (r.get("completeness") or {}).get("verdict"),
            "blocked_dims": [k for k, v in dims.items()
                             if isinstance(v, dict) and v.get("status") == "DATA_BLOCKED"]}
    return {"red_by": red_by, "red_fresh": ctx["red"]["fresh"],
            "bat_by": bat_by, "bat_fresh": ctx["bat"]["fresh"]}


def qc_decide(qc, ticker):
    """逐票 QC 裁决(在原 G1/G2/G3 之前)。返回 (blocked_verdict|None, qc留痕)。
    顺序:①红旗 → ②数据质量(电池PARTIAL/任一维阻断/未覆盖/红旗DATA_BLOCKED,
    缺数据≠通过)→ ③输入新鲜度。全过才进原 G 门。"""
    red = qc["red_by"].get(ticker)
    bat = qc["bat_by"].get(ticker)
    fresh = ("FRESH" if qc["red_fresh"] == "FRESH" and qc["bat_fresh"] == "FRESH"
             else f"red={qc['red_fresh']};battery={qc['bat_fresh']}")
    trace = {"red_flag": red or "MISSING",
             "battery": (bat or {}).get("verdict") or "MISSING",
             "freshness": fresh, "decided_by": "qc_gate_v1"}
    if red == "RED_FLAG":
        return "BLOCKED_RED_FLAG", trace
    if (red is None or red == "DATA_BLOCKED" or bat is None
            or bat.get("verdict") != "COMPLETE" or bat.get("blocked_dims")):
        return "BLOCKED_DATA_QUALITY", trace
    if fresh != "FRESH":
        return "BLOCKED_STALE_INPUT", trace
    return None, dict(trace, decided_by="qc_gate_v1+G1G2G3")


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _zone_from_trigger(text):
    """从 trigger_condition 里抽第一个 'a-b' 或 'x±y' 价区;抽不出→None(人审)。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", text or "")
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return (min(lo, hi), max(lo, hi))
    m = re.search(r"(\d+(?:\.\d+)?)\s*±\s*(\d+(?:\.\d+)?)", text or "")
    if m:
        c, d = float(m.group(1)), float(m.group(2))
        return (c - d, c + d)
    return None


def _stop_from_invalidation(text):
    m = re.search(r"收盘\s*[<＜]\s*(\d+(?:\.\d+)?)", text or "")
    return float(m.group(1)) if m else None


def evaluate(signals, market_state, sector_streaks, bars_by_ticker, nav, qc=None):
    """纯函数。bars_by_ticker: {ticker: {'low','high','close'}} 当日定盘 bar。
    qc(load_qc_context 产物)非 None 时,逐票先过质检闸门再进 G1/G2/G3;
    qc=None 仅限旧 selftest/直接调用路径,留痕 decided_by=G1G2G3_only。"""
    queue, blocked = [], []
    qc_stats = {}
    for s in signals:
        if (s.get("official_sample") or s.get("setup_type") != "execution_gate"
                or s.get("outcome_status", "pending") != "pending"
                or "." not in (s.get("ticker") or "")):
            continue
        t = s["ticker"]
        if qc is not None:
            bv, qtrace = qc_decide(qc, t)
            if bv:
                qc_stats[bv] = qc_stats.get(bv, 0) + 1
                queue.append({"ticker": t, "name": s.get("name"),
                              "signal_id": s.get("signal_id"), "verdict": bv,
                              "why": "质检闸门拦截(红旗/电池/新鲜度),禁止晋级复核",
                              "qc": qtrace})
                continue
        else:
            qtrace = {"red_flag": "NOT_EVALUATED", "battery": "NOT_EVALUATED",
                      "freshness": "NOT_EVALUATED", "decided_by": "G1G2G3_only"}
        checks = {}
        checks["G1_regime"] = market_state in ("RISK_ON", "WEAK_REPAIR")
        streak, matched_sector = sector_keys.best_streak(s.get("sector"), sector_streaks)
        checks["G2_sector_streak>=2"] = streak >= 2
        zone = _zone_from_trigger(s.get("trigger_condition"))
        stop = _stop_from_invalidation(s.get("invalidation"))
        bar = bars_by_ticker.get(t)
        if bar is None:
            blocked.append({"ticker": t, "why": "DATA_BLOCKED: 当日bar缺失"})
            continue
        if zone is None or stop is None:
            queue.append({"ticker": t, "name": s.get("name"),
                          "signal_id": s.get("signal_id"),
                          "verdict": "MANUAL_REVIEW",
                          "why": "trigger/invalidation 无法机械解析,送人审",
                          "matched_sector": matched_sector,
                          "checks": checks, "qc": qtrace})
            continue
        touched = bar["low"] <= zone[1] and bar["high"] >= zone[0]
        held = bar["close"] > stop
        checks["G3_zone_printed_and_held"] = bool(touched and held)
        ready = all(checks.values())
        entry_ref = round((zone[0] + zone[1]) / 2, 2)
        shares = int(nav * RISK_PCT / max(entry_ref - stop, 1e-9) // 100 * 100) if ready else 0
        queue.append({"ticker": t, "name": s.get("name"), "signal_id": s.get("signal_id"),
                      "verdict": "PROMOTE_REVIEW_READY" if ready else "NOT_READY",
                      "matched_sector": matched_sector,
                      "checks": checks, "qc": qtrace,
                      "proposal": ({"entry_review": entry_ref, "stop": stop,
                                    "shares": shares, "risk_pct_nav": RISK_PCT,
                                    "note": "提案仅供人审;注册走结算流程"} if ready else None)})
    return {"market_state": market_state, "queue": queue, "data_blocked": blocked,
            "qc_blocked_stats": qc_stats,
            "note": "晋级复核单;不注册不成交。不是买卖指令。"}


def selftest():
    ok = []

    def ck(name, cond):
        ok.append((name, bool(cond)))
        print(("  ✓ " if cond else "  ✗ ") + name)

    sig = {"ticker": "002463.SZ", "name": "沪电", "setup_type": "execution_gate",
           "outcome_status": "pending", "official_sample": False, "sector": "PCB/AI硬件",
           "signal_id": "a2a40a", "trigger_condition": "回踩127-130承接",
           "invalidation": "收盘<123(swing低)或回踩日主力净流出>5亿"}
    sig_sector = dict(sig, ticker="SECTOR.X", signal_id="x")
    sig_fuzzy = dict(sig, signal_id="fz", trigger_condition="盘感觉不错就进")
    bars = {"002463.SZ": {"low": 128.0, "high": 136.0, "close": 131.0}}
    r = evaluate([sig, sig_sector, sig_fuzzy], "RISK_ON", {"印制电路板": 3, "PCB": 3},
                 bars, nav=1_000_000)
    by = {q["signal_id"]: q for q in r["queue"]}
    ck("三门全过 → READY + 提案", by["a2a40a"]["verdict"] == "PROMOTE_REVIEW_READY"
       and by["a2a40a"]["proposal"]["shares"] > 0)
    ck("提案股数为整百", by["a2a40a"]["proposal"]["shares"] % 100 == 0)
    ck("板块级信号不进桥", "x" not in by)
    ck("模糊 trigger → MANUAL_REVIEW 不硬解析", by["fz"]["verdict"] == "MANUAL_REVIEW")
    r2 = evaluate([sig], "RISK_OFF", {"PCB": 3}, bars, 1_000_000)
    ck("G1 regime 不过 → NOT_READY", r2["queue"][0]["verdict"] == "NOT_READY")
    r3 = evaluate([sig], "RISK_ON", {"PCB": 1}, bars, 1_000_000)
    ck("G2 streak<2 → NOT_READY", r3["queue"][0]["verdict"] == "NOT_READY")
    r4 = evaluate([sig], "RISK_ON", {"PCB": 3},
                  {"002463.SZ": {"low": 131, "high": 140, "close": 138}}, 1_000_000)
    ck("G3 区未打印 → NOT_READY", r4["queue"][0]["verdict"] == "NOT_READY")
    r5 = evaluate([sig], "RISK_ON", {"PCB": 3}, {}, 1_000_000)
    ck("bar 缺失 → DATA_BLOCKED", len(r5["data_blocked"]) == 1)
    # ── P0-B 质检闸门 ──
    qc_ok = {"red_by": {"002463.SZ": "PASS"}, "red_fresh": "FRESH",
             "bat_by": {"002463.SZ": {"verdict": "COMPLETE", "blocked_dims": []}},
             "bat_fresh": "FRESH"}
    r6 = evaluate([sig], "RISK_ON", {"PCB": 3}, bars, 1_000_000, qc=qc_ok)
    ck("QC全过 → 原G门照常 READY(留痕qc_gate_v1+G1G2G3)",
       r6["queue"][0]["verdict"] == "PROMOTE_REVIEW_READY"
       and r6["queue"][0]["qc"]["decided_by"] == "qc_gate_v1+G1G2G3")
    r7 = evaluate([sig], "RISK_ON", {"PCB": 3}, bars, 1_000_000,
                  qc={**qc_ok, "red_by": {"002463.SZ": "RED_FLAG"}})
    ck("红旗 → BLOCKED_RED_FLAG 永不READY", r7["queue"][0]["verdict"] == "BLOCKED_RED_FLAG"
       and r7["qc_blocked_stats"] == {"BLOCKED_RED_FLAG": 1})
    r8 = evaluate([sig], "RISK_ON", {"PCB": 3}, bars, 1_000_000,
                  qc={**qc_ok, "red_fresh": "STALE_FILE(mtime 30.0h>26h)"})
    ck("质检输入过期 → BLOCKED_STALE_INPUT", r8["queue"][0]["verdict"] == "BLOCKED_STALE_INPUT")
    # R-002 验收第四类:电池 PARTIAL / 任一维阻断,均不得 READY
    r9 = evaluate([sig], "RISK_ON", {"PCB": 3}, bars, 1_000_000,
                  qc={**qc_ok, "bat_by": {"002463.SZ": {"verdict": "PARTIAL",
                                                        "blocked_dims": ["资金"]}}})
    ck("电池PARTIAL → 不得READY", r9["queue"][0]["verdict"] != "PROMOTE_REVIEW_READY")
    r10 = evaluate([sig], "RISK_ON", {"PCB": 3}, bars, 1_000_000,
                   qc={**qc_ok, "bat_by": {}})       # 该票未被电池覆盖
    ck("电池未覆盖 → 不得READY", r10["queue"][0]["verdict"] != "PROMOTE_REVIEW_READY")
    passed = sum(1 for _, c in ok if c)
    print(f"setup_promoter selftest: {passed}/{len(ok)}")
    return passed == len(ok)


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    sys.path.insert(0, HERE)
    import glob
    import paper_portfolio as pp
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("DATA_BLOCKED: NO TUSHARE_TOKEN")
        sys.exit(1)
    samples = sorted(glob.glob(os.path.join(HERE, "samples", "*.json")))
    if not samples:
        print("DATA_BLOCKED: 无官方样本")
        sys.exit(1)
    # P0-B:运行开始即读质检输入;缺文件/坏schema/面板过期 = 无法裁决 → DATA_BLOCKED
    try:
        qc = load_qc_context()
    except QcUnavailable as e:
        print("## 晋级桥:质检输入无法裁决,本轮不产出晋级复核单")
        print(f"DATA_BLOCKED: {e}")
        sys.exit(1)
    snap = _load(samples[-1], {})
    market_state = (snap.get("market_gate") or {}).get("state", "?")
    panel = _load(os.path.join(HERE, "rotation_panel.json"), {})
    streaks = {r["sector"]: r["streak"] for r in
               panel.get("inflow_cont", []) + panel.get("warming", [])}
    signals = _load(os.path.join(HERE, "paper_signal_log.json"), [])
    fund = _load(os.path.join(HERE, "model_fund", "fund.json"), {})
    navh = _load(os.path.join(HERE, "model_fund", "nav_history.json"), [])
    nav = navh[-1]["nav"] if navh else fund.get("initial_capital", 1_000_000)
    bars = {}
    for s in signals:
        t = s.get("ticker") or ""
        if (s.get("setup_type") == "execution_gate" and "." in t
                and s.get("outcome_status", "pending") == "pending"
                and not s.get("official_sample")):
            if qc_decide(qc, t)[0]:
                continue  # QC 拦截票不必取 bar(evaluate 会给出 BLOCKED_* 裁决)
            ser = pp.qfq_ohlc_series(t, token, "20260701")
            if ser:
                b = ser[-1]
                bars[t] = {"low": b["low"], "high": b["high"], "close": b["close"]}
    result = evaluate(signals, market_state, streaks, bars, nav, qc=qc)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(f"## 晋级桥(regime={market_state})")
    if result["qc_blocked_stats"]:
        print("  质检拦截统计: " + ", ".join(
            f"{k}={v}" for k, v in sorted(result["qc_blocked_stats"].items())))
    for q in result["queue"]:
        print(f"  {q['name']} {q['verdict']}"
              + (f" checks={q['checks']}" if q.get("checks") else f" qc={q.get('qc')}"))
        if q.get("proposal"):
            print(f"    提案(人审): entry~{q['proposal']['entry_review']} "
                  f"stop {q['proposal']['stop']} {q['proposal']['shares']}股")
    for b in result["data_blocked"]:
        print(f"  ⛔ {b['ticker']} {b['why']}")
    print(f"[written] {OUT}\n不是买卖指令；研究信号，human executes.")


if __name__ == "__main__":
    main()
