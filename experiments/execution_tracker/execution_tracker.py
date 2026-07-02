#!/usr/bin/env python3
"""
experiments/execution_tracker/execution_tracker.py  —  P1 (read-only)

Execution-gate collector + paper-signal logger for the AR Weekly Trading Factory
(Line B). EXPERIMENTS layer: does NOT touch production scripts or public/data.

Discipline (mirrors ~/.codex/skills/ar-weekly-trading-factory):
  * No buy/sell. Output = risk posture + paper signals only. Human executes.
  * Every paper signal carries no_trade_flag = True.
  * All thresholds below are [unvalidated intuition] until >= 30 independent
    paper signals accumulate (then evaluate hit-rate / expectancy before any claim).

This script does NOT fetch live by itself (TradingView is MCP-only; 主力净流 is
东财-only). The agent/human assembles an input dict and passes it in:
  - per ticker: price, change_pct, turnover, turnover_rate, main_flow(亿),
    super_large(亿), small(亿), ohlc_bars (list of {high,low,close}, oldest->newest)
  - index_data: {sh:{chg,main_flow}, sz:{...}, cyb:{...}}   (主力 in 亿)
  - portfolio: list of held tickers + each ticker's sector tag (single-beta check)
The script classifies the 7 gates, builds an execution_gate_snapshot, emits a
paper signal per name (signal_type = posture), and — given later prices —
evaluates T+0/1/3/5/10 outcomes.

Usage:
  python3 execution_tracker.py --selftest
  python3 execution_tracker.py --input snapshot_input.json --log paper_signal_log.json
  python3 execution_tracker.py --evaluate paper_signal_log.json --prices later_prices.json
"""
import argparse
import hashlib
import json
import os
import sys

# ---- enums (must match the skill) ------------------------------------------
MARKET_STATES = ("RISK_ON", "WEAK_REPAIR", "RISK_OFF", "STYLE_ROTATION")
FUND_STRUCTS = ("主力回流", "涨着派发", "跌中承接", "大单卖小单接", "无量修复")
POSTURES = ("RECLAIM_REVIEW", "HOLD_OBSERVE", "WARNING",
            "DE_RISK_REVIEW", "EXIT_REVIEW", "NO_CHASE")

# ---- thresholds — ALL [unvalidated intuition] ------------------------------
UP_MOVE = 1.0          # %  meaningful up move for 涨着派发 vs 价平
HIGH_REFLEX = 4.0      # %  high-reflexivity up move (NO_CHASE if unconfirmed)
ATR_PERIOD = 14


# ---- technical gate --------------------------------------------------------
def _ma(closes, n):
    return round(sum(closes[-n:]) / n, 4) if len(closes) >= n else None


def _atr(bars, n=ATR_PERIOD):
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return round(sum(trs[-n:]) / n, 4)


def compute_technicals(ohlc_bars):
    """ohlc_bars oldest->newest, each {high,low,close}. Returns levels dict."""
    if not ohlc_bars:
        return {k: None for k in ("ma20", "ma60", "ma120", "atr14", "today_high",
                                  "today_low", "prev_high", "prev_low", "high_20d",
                                  "low_20d", "support", "break_level", "reclaim_level")}
    closes = [b["close"] for b in ohlc_bars]
    today, prev = ohlc_bars[-1], (ohlc_bars[-2] if len(ohlc_bars) >= 2 else ohlc_bars[-1])
    win20 = ohlc_bars[-20:]
    ma20 = _ma(closes, 20)
    high_20d = max(b["high"] for b in win20)
    low_20d = min(b["low"] for b in win20)
    # support = max(today_low, prev_low); break = lower of support / MA20; reclaim = prev_high
    support = max(today["low"], prev["low"])
    break_level = min(x for x in (support, ma20) if x is not None)
    reclaim_level = max(today["high"], prev["high"])
    return {
        "ma20": ma20, "ma60": _ma(closes, 60), "ma120": _ma(closes, 120),
        "atr14": _atr(ohlc_bars),
        "today_high": today["high"], "today_low": today["low"],
        "prev_high": prev["high"], "prev_low": prev["low"],
        "high_20d": high_20d, "low_20d": low_20d,
        "support": round(support, 4), "break_level": round(break_level, 4),
        "reclaim_level": round(reclaim_level, 4),
    }


# ---- market gate -----------------------------------------------------------
def classify_market(index_data):
    sh, sz, cyb = index_data.get("sh", {}), index_data.get("sz", {}), index_data.get("cyb", {})
    chgs = [d.get("chg") for d in (sh, sz, cyb) if d.get("chg") is not None]
    # 全市场主力净流(亿): prefer explicit `main_flow_total` (moneyflow_mkt_dc);
    # else sum the per-index main_flow.
    total = index_data.get("main_flow_total")
    if total is None:
        flows = [d.get("main_flow") for d in (sh, sz, cyb) if d.get("main_flow") is not None]
        total = sum(flows) if flows else None
    up = chgs and all(c > 0 for c in chgs)
    down = chgs and all(c < 0 for c in chgs)
    mixed_up = chgs and max(chgs) > 0 >= min(chgs)
    inflow = total is not None and total > 0
    outflow = total is not None and total < 0
    growth_weak = (cyb.get("chg") is not None and sh.get("chg") is not None
                   and cyb["chg"] < sh["chg"] - 1.5)
    tot = ("%+.0f亿" % total) if total is not None else "未知"
    if not chgs:
        # 2026-07-02 incident: all three index chg were None (index_daily not yet
        # settled when fetched) and the classifier silently fell through to the
        # WEAK_REPAIR default on what was a -1218亿 RISK_OFF day. Never classify
        # direction without index data — say so explicitly instead.
        return {"state": "INDEX_DATA_MISSING",
                "one_line": ("指数涨跌数据缺失,仅主力净流 " + tot
                             + " — 不判方向(检查 index_daily 是否已结算)"),
                "main_flow_total": total,
                "index": {"sh": sh, "sz": sz, "cyb": cyb}}
    if up and inflow:
        state, note = "RISK_ON", "趋势恢复:指数上行+主力净流入 " + tot
    elif (up or mixed_up) and outflow:
        state, note = "WEAK_REPAIR", "WEAK_REPAIR: 指数上涨但主力净流出 " + tot + "(价格修复非主力确认)"
    elif down and outflow:
        state, note = "RISK_OFF", "继续派发:指数下跌+主力净流出 " + tot
    elif growth_weak:
        state, note = "STYLE_ROTATION", "风格切换:成长/AI流出,价值/资源占优"
    else:
        state, note = "WEAK_REPAIR", "弱修复(资金未确认): 主力 " + tot
    return {"state": state, "one_line": note, "main_flow_total": total,
            "index": {"sh": sh, "sz": sz, "cyb": cyb}}


# ---- fund-flow gate --------------------------------------------------------
def classify_fund_structure(change_pct, main_flow, small):
    if main_flow is None or change_pct is None:
        return "无量修复"
    if main_flow > 0 and change_pct > 0:
        return "主力回流"
    if change_pct >= UP_MOVE and main_flow < 0:
        return "涨着派发"
    if change_pct <= -UP_MOVE and main_flow > 0:
        return "跌中承接"
    if main_flow < 0 and (small or 0) > 0:
        return "大单卖小单接"
    return "无量修复"


# ---- execution posture (priority order: most severe first) -----------------
def execution_posture(price, change_pct, tech, fund_structure, portfolio_single_beta):
    support, break_level, reclaim = tech["support"], tech["break_level"], tech["reclaim_level"]
    main_confirmed = fund_structure in ("主力回流", "跌中承接")
    if price is not None and break_level is not None and price < break_level and not main_confirmed:
        return "EXIT_REVIEW"
    if price is not None and support is not None and price < support and not main_confirmed:
        return "DE_RISK_REVIEW"
    if fund_structure in ("涨着派发", "大单卖小单接"):   # 主力派发(拉高出货 / 机构卖散户接) = WARNING
        return "WARNING"
    if price is not None and reclaim is not None and price >= reclaim and main_confirmed:
        return "RECLAIM_REVIEW"
    if change_pct is not None and change_pct >= HIGH_REFLEX and not main_confirmed:
        return "NO_CHASE"
    return "HOLD_OBSERVE"


# ---- snapshot builder ------------------------------------------------------
def build_snapshot(index_data, tickers_data, portfolio, timestamp):
    market = classify_market(index_data)
    sectors = [t.get("sector") for t in tickers_data]
    held = [t for t in tickers_data if t["ticker"] in set(portfolio)]
    held_sectors = {t.get("sector") for t in held}
    single_beta = len(held) >= 2 and len(held_sectors) == 1
    gates = []
    for t in tickers_data:
        tech = compute_technicals(t.get("ohlc_bars", []))
        fund = classify_fund_structure(t.get("change_pct"), t.get("main_flow"), t.get("small"))
        posture = execution_posture(t.get("price"), t.get("change_pct"), tech, fund, single_beta)
        relative_strength = fund == "主力回流" and market["state"] in ("WEAK_REPAIR", "RISK_OFF")
        gates.append({
            "ticker": t["ticker"], "name": t.get("name"), "sector": t.get("sector"),
            "price": t.get("price"), "change_pct": t.get("change_pct"),
            "main_flow": t.get("main_flow"), "super_large": t.get("super_large"),
            "small": t.get("small"),
            "fund_structure": fund, "technical": tech,
            "posture": posture, "relative_strength": relative_strength,
        })
    portfolio_gate = {
        "single_beta_exposure": single_beta,
        "held_sectors": sorted(s for s in held_sectors if s),
        "portfolio_posture": "DE_RISK_REVIEW" if single_beta else "HOLD_OBSERVE",
        "note": ("组合=单一 beta 暴露,先看组合风险再看个股强弱" if single_beta
                 else "组合分散度尚可"),
    }
    self_audit = {
        "rebound_as_reversal": market["state"] in ("WEAK_REPAIR", "RISK_OFF"),
        "any_price_strong_but_flow_out": any(g["posture"] == "WARNING" for g in gates),
        "high_reflexivity_book": single_beta,
        "no_buy_sell_instruction": True,
    }
    return {
        "schema": "execution_gate_snapshot/v1",
        "timestamp": timestamp,
        "market_gate": market,
        "sector_single_beta": single_beta,
        "ticker_gates": gates,
        "portfolio_gate": portfolio_gate,
        "self_audit": self_audit,
        "disclaimer": "不是买卖指令；研究信号，human executes。thresholds=[unvalidated intuition]",
    }


# ---- paper signals ---------------------------------------------------------
def make_paper_signals(snapshot):
    out = []
    ms = snapshot["market_gate"]["state"]
    sb = snapshot["sector_single_beta"]
    for g in snapshot["ticker_gates"]:
        tech = g["technical"]
        sid = hashlib.sha1(
            f"{g['ticker']}|{snapshot['timestamp']}|{g['posture']}".encode()
        ).hexdigest()[:12]
        out.append({
            "signal_id": sid, "ticker": g["ticker"], "name": g.get("name"),
            "timestamp": snapshot["timestamp"], "line": "execution",
            "market_state": ms, "sector_single_beta": sb,
            "market_main_flow_total": snapshot["market_gate"].get("main_flow_total"),
            "setup_type": g["posture"], "fund_structure": g["fund_structure"],
            "relative_strength": g.get("relative_strength", False),
            "main_flow": g.get("main_flow"),
            "trigger_price": g["price"],
            "support": tech["support"], "reclaim": tech["reclaim_level"],
            "invalidation": tech["break_level"], "atr14": tech["atr14"],
            "horizon": ["intraday", "1d", "3d", "5d", "10d"],
            "no_trade_flag": True,
        })
    return out


def append_log(log_path, signals):
    log = []
    if os.path.exists(log_path):
        with open(log_path) as f:
            log = json.load(f)
    seen = {s["signal_id"] for s in log}
    added = [s for s in signals if s["signal_id"] not in seen]
    log.extend(added)
    with open(log_path, "w") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    return len(added), len(log)


# ---- evaluator -------------------------------------------------------------
def evaluate(log, later_prices):
    """later_prices: {signal_id: {t1,t3,t5,t10}} forward % returns (signed,
    long-perspective). Aggregates only signals that have outcomes."""
    rows = []
    for s in log:
        px = later_prices.get(s["signal_id"])
        if not px:
            continue
        rows.append({"setup_type": s["setup_type"], "market_state": s["market_state"], **px})
    if not rows:
        return {"n": 0, "note": "no outcomes yet (need forward prices)"}

    def agg(subset):
        if not subset:
            return None
        rets = [r.get("t5") for r in subset if r.get("t5") is not None]
        if not rets:
            return None
        wins = [r for r in rets if r > 0]
        avg = sum(rets) / len(rets)
        avg_win = (sum(wins) / len(wins)) if wins else 0.0
        losses = [r for r in rets if r <= 0]
        avg_loss = (sum(losses) / len(losses)) if losses else 0.0
        hit = len(wins) / len(rets)
        expectancy = hit * avg_win + (1 - hit) * avg_loss
        return {"n": len(rets), "hit_rate": round(hit, 3),
                "avg_return_t5": round(avg, 3),
                "win_loss": round(abs(avg_win / avg_loss), 3) if avg_loss else None,
                "expectancy_t5": round(expectancy, 3)}

    by_setup = {p: agg([r for r in rows if r["setup_type"] == p]) for p in POSTURES}
    by_market = {m: agg([r for r in rows if r["market_state"] == m]) for m in MARKET_STATES}
    return {
        "n": len(rows),
        "overall": agg(rows),
        "by_setup_type": {k: v for k, v in by_setup.items() if v},
        "by_market_state": {k: v for k, v in by_market.items() if v},
        "warn_below_30": len(rows) < 30,
        "note": "win-rate NOT claimable below 30 independent signals [unvalidated]",
    }


# ---- selftest: reproduce today's 4-holding read ----------------------------
def _mock_bars(closes, pad_to=25):
    """Build {high,low,close} bars; left-pad with a ramp to >= pad_to bars so
    MA20 computes (real TV pulls supply ~25 daily bars)."""
    if len(closes) < pad_to:
        base = closes[0]
        n_pad = pad_to - len(closes)
        ramp = [round(base * (0.55 + 0.45 * (i + 1) / (n_pad + 1)), 2) for i in range(n_pad)]
        closes = ramp + closes
    return [{"high": round(c * 1.015, 2), "low": round(c * 0.985, 2), "close": c} for c in closes]


def selftest():
    checks = []

    def ck(name, cond):
        checks.append((name, bool(cond)))

    # market gate: 上证-0.25 / 深成+0.33 / 创业板+0.42, all 主力 net out => WEAK_REPAIR
    idx = {"sh": {"chg": -0.25, "main_flow": -7.26}, "sz": {"chg": 0.33, "main_flow": -8.48},
           "cyb": {"chg": 0.42, "main_flow": -4.39}}
    mk = classify_market(idx)
    ck("market=WEAK_REPAIR", mk["state"] == "WEAK_REPAIR")

    # fund-structure (today @12:56)
    ck("利通=涨着派发", classify_fund_structure(5.98, -1.01, 1.09) == "涨着派发")
    ck("香农=大单卖小单接", classify_fund_structure(-0.30, -4.80, 3.88) == "大单卖小单接")
    ck("中际=无量修复", classify_fund_structure(0.15, -8.20, None) == "无量修复")
    ck("新易盛=主力回流", classify_fund_structure(0.54, 4.41, None) == "主力回流")

    # full snapshot on the 4 holdings (synthetic parabolic bars consistent w/ levels)
    tickers = [
        {"ticker": "603629.SH", "name": "利通电子", "sector": "AI/光模块", "price": 214.0,
         "change_pct": 5.98, "main_flow": -1.01, "small": 1.09,
         "ohlc_bars": _mock_bars([165, 176.58, 194.24, 201.93, 210])},
        {"ticker": "300475.SZ", "name": "香农芯创", "sector": "AI/光模块", "price": 282.66,
         "change_pct": -0.30, "main_flow": -4.80, "small": 3.88,
         "ohlc_bars": _mock_bars([245.29, 254.87, 287.8, 283.51, 283])},
        {"ticker": "300308.SZ", "name": "中际旭创", "sector": "AI/光模块", "price": 1311.92,
         "change_pct": 0.15, "main_flow": -8.20, "small": None,
         "ohlc_bars": _mock_bars([1276, 1367.88, 1382.33, 1310.01, 1312])},
        {"ticker": "300502.SZ", "name": "新易盛", "sector": "AI/光模块", "price": 555.0,
         "change_pct": 0.54, "main_flow": 4.41, "small": None,
         "ohlc_bars": _mock_bars([557.88, 581.48, 579.97, 552, 553])},
    ]
    portfolio = ["603629.SH", "300475.SZ", "300308.SZ", "300502.SZ"]
    snap = build_snapshot(idx, tickers, portfolio, timestamp="2026-06-24T12:56:00+08:00")
    pg = {g["ticker"]: g for g in snap["ticker_gates"]}
    ck("利通 posture=WARNING", pg["603629.SH"]["posture"] == "WARNING")
    ck("香农 posture=WARNING (大单卖小单接)", pg["300475.SZ"]["posture"] == "WARNING")
    ck("中际 posture=HOLD_OBSERVE", pg["300308.SZ"]["posture"] == "HOLD_OBSERVE")
    # market gate: up indices + total main_flow out -> WEAK_REPAIR citing the total
    mk2 = classify_market({"sh": {"chg": 0.23}, "sz": {"chg": 1.82}, "cyb": {"chg": 2.84},
                           "main_flow_total": -214.4})
    ck("market up+outflow=WEAK_REPAIR", mk2["state"] == "WEAK_REPAIR")
    ck("market one_line cites -214", "-214" in mk2["one_line"])
    # 2026-07-02 regression: all index chg None + big outflow must NOT silently
    # default to WEAK_REPAIR — it must say INDEX_DATA_MISSING.
    mk3 = classify_market({"sh": {"chg": None}, "sz": {}, "cyb": {},
                           "main_flow_total": -1218.0})
    ck("no-index-data -> INDEX_DATA_MISSING (not fake WEAK_REPAIR)",
       mk3["state"] == "INDEX_DATA_MISSING")
    ck("INDEX_DATA_MISSING still cites the flow", "-1218" in mk3["one_line"])
    ck("新易盛 relative_strength", pg["300502.SZ"]["relative_strength"] is True)
    ck("组合=单一 beta DE_RISK", snap["portfolio_gate"]["portfolio_posture"] == "DE_RISK_REVIEW")
    ck("技术门 MA20 present(利通)", pg["603629.SH"]["technical"]["ma20"] is not None)

    # paper signals: all no_trade_flag, deterministic ids
    sigs = make_paper_signals(snap)
    ck("4 paper signals", len(sigs) == 4)
    ck("all no_trade_flag", all(s["no_trade_flag"] for s in sigs))
    ck("deterministic id", make_paper_signals(snap)[0]["signal_id"] == sigs[0]["signal_id"])

    # evaluator gates below-30 sample
    ev = evaluate(sigs, {sigs[0]["signal_id"]: {"t1": 1.2, "t3": -0.5, "t5": 2.1, "t10": 3.0}})
    ck("evaluator warns <30", ev["warn_below_30"] is True)

    passed = sum(1 for _, ok in checks if ok)
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"\nselftest: {passed}/{len(checks)} passed")
    return passed == len(checks)


# ---- cli -------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="P1 execution-gate collector (read-only, no_trade)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--input", help="snapshot input JSON (index_data + tickers + portfolio + timestamp)")
    ap.add_argument("--log", default="paper_signal_log.json", help="paper signal log path")
    ap.add_argument("--evaluate", help="evaluate an existing paper_signal_log.json")
    ap.add_argument("--prices", help="later_prices.json {signal_id:{t1,t3,t5,t10}}")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(0 if selftest() else 1)

    if args.evaluate:
        with open(args.evaluate) as f:
            log = json.load(f)
        later = {}
        if args.prices and os.path.exists(args.prices):
            with open(args.prices) as f:
                later = json.load(f)
        print(json.dumps(evaluate(log, later), ensure_ascii=False, indent=2))
        return

    if args.input:
        with open(args.input) as f:
            inp = json.load(f)
        snap = build_snapshot(inp["index_data"], inp["tickers"], inp.get("portfolio", []),
                              inp.get("timestamp", "UNSTAMPED"))
        sigs = make_paper_signals(snap)
        added, total = append_log(args.log, sigs)
        snap_out = (os.path.splitext(args.log)[0].replace("paper_signal_log", "execution_gate_snapshot")
                    + ".json")
        with open(snap_out, "w") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        print(f"snapshot -> {snap_out}")
        print(f"paper signals: +{added} (log total {total}) -> {args.log}")
        print("不是买卖指令；研究信号，human executes。")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
