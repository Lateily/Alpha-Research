#!/usr/bin/env python3
"""
model_paper_fund.py — P6.1: the Model Paper Fund ledger (¥1,000,000 VIRTUAL).

The fund layer on top of paper_portfolio's fill engine — capital, sizing,
portfolio constraints, NAV, decision log, performance. It deliberately REUSES
paper_portfolio._advance (registered → no-fill-on-registration-day → T+1 →
gaps-fill-worse → same-bar-stop-wins) instead of reimplementing fills: one fill
engine, no divergence.

Policy: docs/strategy/MODEL_PAPER_FUND_POLICY.md. All thresholds
[unvalidated intuition]. Everything paper: every order no_trade_flag:true.
No win-rate/expectancy claim below 30 closed trades.

Ledger dir (append-only JSON): experiments/execution_tracker/model_fund/
  fund.json · orders.json · nav_history.json · decision_log.json

  python3 model_paper_fund.py --selftest
  python3 model_paper_fund.py --init
  python3 model_paper_fund.py --status
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paper_portfolio as pp   # noqa: E402 — the ONE fill engine

FUND_DIR = os.path.join(HERE, "model_fund")

# ---- policy constants (v0, [unvalidated intuition]) ----
INITIAL_CAPITAL = 1_000_000.0
MAX_NAME_PCT = 0.15
MAX_THEME_PCT = 0.40
MAX_POSITIONS = 5
RISK_PCT_RANGE = (0.005, 0.010)
MIN_CASH_PCT = 0.20
LOT = 100
MIN_CLOSED_FOR_CLAIM = 30
NO_NEW_ORDER_STATES = {"NO_CHASE", "FAKE_STRENGTH"}


# ------------------------------------------------------------------ ledger ----
def _path(name, fund_dir=None):
    return os.path.join(fund_dir or FUND_DIR, name)


def load(name, default, fund_dir=None):
    p = _path(name, fund_dir)
    return json.load(open(p)) if os.path.exists(p) else default


def save(name, obj, fund_dir=None):
    os.makedirs(fund_dir or FUND_DIR, exist_ok=True)
    with open(_path(name, fund_dir), "w") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)


def init_fund(fund_dir=None, capital=INITIAL_CAPITAL, date="init"):
    fund = {"initial_capital": capital, "cash": capital, "created": date,
            "policy": "MODEL_PAPER_FUND_POLICY.md v0", "paper_only": True}
    save("fund.json", fund, fund_dir)
    save("orders.json", [], fund_dir)
    save("nav_history.json", [], fund_dir)
    save("decision_log.json", [], fund_dir)
    return fund


# ------------------------------------------------------------------ sizing ----
def size_order(nav, entry, stop, risk_pct):
    """shares = risk_budget / (entry-stop), lot-rounded, capped by single-name %."""
    risk_pct = max(RISK_PCT_RANGE[0], min(RISK_PCT_RANGE[1], risk_pct))
    risk_cny = nav * risk_pct
    raw = risk_cny / abs(entry - stop)
    shares = int(raw // LOT) * LOT
    max_notional = nav * MAX_NAME_PCT
    if shares * entry > max_notional:
        shares = int(max_notional / entry // LOT) * LOT
    return shares, round(shares * entry, 2), round(risk_cny, 2)


def _open_orders(orders):
    return [o for o in orders if o["status"] in ("pending", "filled")]


def current_nav(fund, orders, marks=None):
    """cash + Σ filled positions marked at `marks` (fallback: fill price)."""
    nav = fund["cash"]
    for o in orders:
        if o["status"] == "filled":
            px = (marks or {}).get(o["ticker"], o["fill_price"])
            nav += o["shares"] * px
    return round(nav, 2)


# ---------------------------------------------------------------- register ----
def register_order(fund, orders, decision_log, *, ticker, name, theme, setup,
                   registered_at, entry, stop, target, risk_pct, reason,
                   invalid_if="", gate_state="", marks=None):
    """Pre-register a PAPER order under all policy constraints. Refusals are
    logged too — a refused order is itself a decision. Returns (order|None, msg)."""
    nav = current_nav(fund, orders, marks)

    def refuse(why):
        decision_log.append({"date": registered_at, "action": "REFUSED_ORDER",
                             "ticker": ticker, "reason": why, "no_trade_flag": True})
        return None, f"REFUSED: {why}"

    if gate_state in NO_NEW_ORDER_STATES:
        return refuse(f"gate/nowcast={gate_state} 禁止开新单 (no-chase rule)")
    if not (stop < entry < target):
        return refuse(f"mutilated setup stop/entry/target={stop}/{entry}/{target}")
    if len(_open_orders(orders)) >= MAX_POSITIONS:
        return refuse(f"max positions {MAX_POSITIONS} reached")
    if any(o["ticker"] == ticker for o in _open_orders(orders)):
        return refuse(f"{ticker} already open (adds need profit + fresh signal — v0 refuses)")

    shares, notional, risk_cny = size_order(nav, entry, stop, risk_pct)
    if shares <= 0:
        return refuse("sized to 0 shares (risk budget too small vs stop distance)")
    theme_notional = sum(o["shares"] * o["entry_review_price"] for o in _open_orders(orders)
                         if o.get("theme") == theme) + notional
    if theme_notional > nav * MAX_THEME_PCT:
        return refuse(f"theme {theme} would be {theme_notional/nav:.0%} > {MAX_THEME_PCT:.0%}")
    if fund["cash"] - notional < nav * MIN_CASH_PCT:
        return refuse(f"cash floor: fill would leave {(fund['cash']-notional)/nav:.0%} < {MIN_CASH_PCT:.0%}")

    order = {
        "entry_id": f"{ticker}_{registered_at}_{setup}",
        "ticker": ticker, "name": name, "theme": theme, "setup": setup,
        "direction": "long", "registered_at": registered_at,
        "entry_review_price": entry, "stop_reference": stop,
        "take_profit_reference": target, "invalid_if": invalid_if,
        "risk_R": round((target - entry) / (entry - stop), 2),
        "risk_budget_cny": risk_cny, "shares": shares, "notional": notional,
        "reason": reason, "no_trade_flag": True, "sample_eligible": True,
        "status": "pending", "fill_date": None, "fill_price": None,
        "exit_date": None, "exit_price": None, "exit_reason": None,
        "paper_return": None, "realized_R": None, "pnl_cny": None,
    }
    orders.append(order)
    decision_log.append({"date": registered_at, "action": "REGISTER_ORDER",
                         "ticker": ticker, "shares": shares, "notional": notional,
                         "entry": entry, "stop": stop, "target": target,
                         "risk_budget_cny": risk_cny, "reason": reason,
                         "no_trade_flag": True})
    return order, "registered"


def tighten_stop(orders, decision_log, ticker, new_stop, date, why):
    """Stops move TIGHTER only — loosening is how paper accounts lie to themselves."""
    for o in orders:
        if o["ticker"] == ticker and o["status"] in ("pending", "filled"):
            if new_stop <= o["stop_reference"]:
                return False, f"refused: new stop {new_stop} not tighter than {o['stop_reference']}"
            o["stop_reference"] = new_stop
            decision_log.append({"date": date, "action": "TIGHTEN_STOP", "ticker": ticker,
                                 "new_stop": new_stop, "reason": why, "no_trade_flag": True})
            return True, "tightened"
    return False, "no open order for ticker"


# ------------------------------------------------------------- process day ----
def process_day(fund, orders, decision_log, token, series_fn=None):
    """Advance fills/exits from SETTLED bars via paper_portfolio._advance (the one
    fill engine), then settle cash. Returns list of events."""
    series_fn = series_fn or pp.qfq_ohlc_series
    events, cache = [], {}
    for o in orders:
        if o["status"] == "closed":
            continue
        if o["ticker"] not in cache:
            cache[o["ticker"]] = series_fn(o["ticker"], token, o["registered_at"])
        was = o["status"]
        changed = pp._advance(o, cache[o["ticker"]])
        if not changed:
            continue
        if was == "pending" and o["status"] in ("filled", "closed"):
            fund["cash"] = round(fund["cash"] - o["shares"] * o["fill_price"], 2)
            events.append(f"FILL {o['name']} {o['shares']}股 @{o['fill_price']} ({o['fill_date']})")
            decision_log.append({"date": o["fill_date"], "action": "PAPER_FILL",
                                 "ticker": o["ticker"], "price": o["fill_price"],
                                 "shares": o["shares"], "no_trade_flag": True})
        if o["status"] == "closed":
            fund["cash"] = round(fund["cash"] + o["shares"] * o["exit_price"], 2)
            o["pnl_cny"] = round(o["shares"] * (o["exit_price"] - o["fill_price"]), 2)
            events.append(f"EXIT {o['name']} @{o['exit_price']} [{o['exit_reason']}] "
                          f"PnL {o['pnl_cny']:+,.0f} (R={o['realized_R']})")
            decision_log.append({"date": o["exit_date"], "action": "PAPER_EXIT",
                                 "ticker": o["ticker"], "price": o["exit_price"],
                                 "exit_reason": o["exit_reason"], "pnl_cny": o["pnl_cny"],
                                 "realized_R": o["realized_R"], "no_trade_flag": True})
    return events


def update_nav(fund, orders, nav_history, date, marks=None):
    nav = current_nav(fund, orders, marks)
    prev = nav_history[-1]["nav"] if nav_history else fund["initial_capital"]
    rec = {"date": date, "nav": nav, "cash": fund["cash"],
           "n_positions": sum(1 for o in orders if o["status"] == "filled"),
           "daily_return": round(nav / prev - 1, 5),
           "cum_return": round(nav / fund["initial_capital"] - 1, 5)}
    if not any(x["date"] == date for x in nav_history):     # append-only, one per day
        nav_history.append(rec)
    return rec


# -------------------------------------------------------------- performance ----
def compute_performance(fund, orders, nav_history):
    closed = [o for o in orders if o["status"] == "closed"]
    wins = [o for o in closed if (o["paper_return"] or 0) > 0]
    rs = [o["realized_R"] for o in closed if o.get("realized_R") is not None]
    navs = [x["nav"] for x in nav_history] or [fund["initial_capital"]]
    peak, max_dd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    n = len(closed)
    return {
        "nav": navs[-1], "cum_return": round(navs[-1] / fund["initial_capital"] - 1, 5),
        "max_drawdown": round(max_dd, 5),
        "n_closed": n, "n_open": sum(1 for o in orders if o["status"] == "filled"),
        "n_pending": sum(1 for o in orders if o["status"] == "pending"),
        "win_rate": round(len(wins) / n, 3) if n else None,
        "avg_R": round(sum(rs) / len(rs), 3) if rs else None,
        "expectancy_R": round(sum(rs) / len(rs), 3) if rs else None,
        "min_required": MIN_CLOSED_FOR_CLAIM,
        "claim_allowed": n >= MIN_CLOSED_FOR_CLAIM,
        "unvalidated_warning": (f"paper stats NOT claimable: {n}/{MIN_CLOSED_FOR_CLAIM} closed — descriptive only"
                                 if n < MIN_CLOSED_FOR_CLAIM else
                                 f"{n} closed — threshold met; still paper, not real-money validated"),
    }


def compare_human_shadow(nav_history, human_history):
    """human_history: [{date, nav}] Junyan-logged. Aligned daily comparison."""
    h = {x["date"]: x["nav"] for x in human_history}
    out = []
    for rec in nav_history:
        if rec["date"] in h and human_history:
            h0 = human_history[0]["nav"]
            out.append({"date": rec["date"], "model_cum": rec["cum_return"],
                        "human_cum": round(h[rec["date"]] / h0 - 1, 5),
                        "model_minus_human": round(rec["cum_return"] - (h[rec["date"]] / h0 - 1), 5)})
    return out


# ---------------------------------------------------------------- selftest ----
def selftest():
    checks = []

    def ck(n, c):
        checks.append((n, bool(c)))

    import tempfile
    d = tempfile.mkdtemp()
    fund = init_fund(fund_dir=d, date="20260703")
    orders, dlog, navh = [], [], []
    ck("init capital 1,000,000", fund["cash"] == 1_000_000.0 and fund["paper_only"] is True)

    # sizing: 1% risk, entry100 stop95 -> 10000/5=2000股; notional 200k > 15% cap -> 1500股
    sh, notional, risk = size_order(1_000_000, 100.0, 95.0, 0.01)
    ck("sizing caps at 15% single name (1500股)", sh == 1500 and notional == 150_000)
    ck("lot rounding to 100", sh % 100 == 0)

    o1, msg = register_order(fund, orders, dlog, ticker="A.SZ", name="甲", theme="黄金",
                             setup="RECLAIM", registered_at="20260703", entry=100.0,
                             stop=95.0, target=115.0, risk_pct=0.01, reason="test")
    ck("order registered", o1 is not None and o1["status"] == "pending")
    ck("order is paper (no_trade_flag)", o1["no_trade_flag"] is True)
    ck("risk_R computed 3.0", o1["risk_R"] == 3.0)

    # no-chase refusal
    oX, msg = register_order(fund, orders, dlog, ticker="X.SZ", name="乙", theme="黄金",
                             setup="S", registered_at="20260703", entry=10, stop=9, target=12,
                             risk_pct=0.01, reason="t", gate_state="NO_CHASE")
    ck("NO_CHASE refused + logged", oX is None and dlog[-1]["action"] == "REFUSED_ORDER")
    # duplicate ticker refused
    oD, _ = register_order(fund, orders, dlog, ticker="A.SZ", name="甲", theme="黄金",
                           setup="S2", registered_at="20260703", entry=101, stop=96, target=110,
                           risk_pct=0.01, reason="t")
    ck("duplicate open ticker refused", oD is None)
    # theme cap: A.SZ 黄金 150k; add 黄金 orders until >40% NAV -> third big one refused
    o2, _ = register_order(fund, orders, dlog, ticker="B.SZ", name="乙", theme="黄金",
                           setup="S", registered_at="20260703", entry=100.0, stop=95.0,
                           target=115.0, risk_pct=0.01, reason="t")
    o3, m3 = register_order(fund, orders, dlog, ticker="C.SZ", name="丙", theme="黄金",
                            setup="S", registered_at="20260703", entry=100.0, stop=95.0,
                            target=115.0, risk_pct=0.01, reason="t")
    ck("theme cap 40% refuses 3rd 15% gold name", o3 is None and "theme" in m3)
    # max positions: fill up to 5 with other themes then refuse 6th
    for i, th in enumerate(["电力", "医药", "存储"]):
        register_order(fund, orders, dlog, ticker=f"T{i}.SZ", name=th, theme=th,
                       setup="S", registered_at="20260703", entry=100.0, stop=95.0,
                       target=115.0, risk_pct=0.01, reason="t")
    o6, m6 = register_order(fund, orders, dlog, ticker="Z.SZ", name="子", theme="汽车",
                            setup="S", registered_at="20260703", entry=100, stop=95, target=115,
                            risk_pct=0.01, reason="t")
    ck("max 5 positions enforced", o6 is None and "max positions" in m6)
    ck("mutilated setup refused",
       register_order(fund, orders, dlog, ticker="M.SZ", name="m", theme="m", setup="S",
                      registered_at="20260703", entry=100, stop=105, target=110,
                      risk_pct=0.01, reason="t")[0] is None)

    # process_day with synthetic bars: registration day trigger must NOT fill; T+1 fills
    bars = {
        "A.SZ": [{"date": "20260703", "open": 100, "high": 120, "low": 99, "close": 119},   # reg day: ignored
                 {"date": "20260706", "open": 99, "high": 101, "low": 98, "close": 100.5},  # fill @100
                 {"date": "20260707", "open": 100, "high": 116, "low": 99, "close": 114}],  # target 115 hit
    }
    fund2 = init_fund(fund_dir=tempfile.mkdtemp(), date="20260703")
    orders2, dlog2, navh2 = [], [], []
    oa, _ = register_order(fund2, orders2, dlog2, ticker="A.SZ", name="甲", theme="黄金",
                           setup="RECLAIM", registered_at="20260703", entry=100.0,
                           stop=95.0, target=115.0, risk_pct=0.01, reason="t")
    ev = process_day(fund2, orders2, dlog2, token=None,
                     series_fn=lambda t, tok, start: bars.get(t, []))
    ck("registration-day trigger did NOT fill on reg day", oa["fill_date"] == "20260706")
    ck("fill at entry 100 (no gap)", oa["fill_price"] == 100)
    ck("target exit at 115 capped", oa["exit_price"] == 115 and oa["exit_reason"] == "target")
    ck("cash settles: 1M -1500*100 +1500*115 = 1,022,500", fund2["cash"] == 1_022_500.0)
    ck("pnl recorded +22,500", oa["pnl_cny"] == 22_500.0)
    rec = update_nav(fund2, orders2, navh2, "20260707")
    ck("NAV = cash (all closed) 1,022,500", rec["nav"] == 1_022_500.0)
    ck("cum_return +2.25%", abs(rec["cum_return"] - 0.0225) < 1e-9)
    update_nav(fund2, orders2, navh2, "20260707")
    ck("nav append-only one-per-day", len(navh2) == 1)

    perf = compute_performance(fund2, orders2, navh2)
    ck("performance counts 1 closed win", perf["n_closed"] == 1 and perf["win_rate"] == 1.0)
    ck("claim NOT allowed (<30)", perf["claim_allowed"] is False)
    ck("avg_R = 3.0", perf["avg_R"] == 3.0)

    # tighten-only stops
    fund3 = init_fund(fund_dir=tempfile.mkdtemp(), date="20260703")
    orders3, dlog3 = [], []
    register_order(fund3, orders3, dlog3, ticker="S.SZ", name="s", theme="s", setup="S",
                   registered_at="20260703", entry=100, stop=95, target=115, risk_pct=0.01, reason="t")
    okt, _ = tighten_stop(orders3, dlog3, "S.SZ", 97, "20260706", "trail")
    ck("tighten stop allowed", okt and orders3[0]["stop_reference"] == 97)
    okl, _ = tighten_stop(orders3, dlog3, "S.SZ", 94, "20260706", "loosen attempt")
    ck("loosen stop REFUSED", okl is False and orders3[0]["stop_reference"] == 97)

    # human shadow comparison (baseline = human's FIRST logged nav)
    cmp_ = compare_human_shadow(
        [{"date": "20260707", "nav": 1_022_500, "cum_return": 0.0225}],
        [{"date": "20260703", "nav": 1_000_000}, {"date": "20260707", "nav": 1_010_000}])
    ck("human shadow aligns (model +2.25% vs human +1.0% -> +1.25%)",
       cmp_ and abs(cmp_[0]["model_minus_human"] - 0.0125) < 1e-9)

    passed = sum(1 for _, okk in checks if okk)
    for n, okk in checks:
        print(f"  [{'PASS' if okk else 'FAIL'}] {n}")
    print(f"\nselftest: {passed}/{len(checks)} passed")
    return passed == len(checks)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Model Paper Fund v0 (paper only, no real trading)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--init", action="store_true", help="create the ¥1,000,000 virtual ledger")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    if args.init:
        if os.path.exists(_path("fund.json")):
            print("fund.json already exists — refusing to re-init (append-only ledger)")
            sys.exit(1)
        import datetime
        fund = init_fund(date=datetime.datetime.now().strftime("%Y%m%d"))
        print(f"Model Paper Fund initialized: ¥{fund['initial_capital']:,.0f} (VIRTUAL) at {FUND_DIR}")
        print("不是买卖指令；研究信号，human executes。")
        return
    if args.status:
        fund = load("fund.json", None)
        if not fund:
            print("not initialized — run --init"); return
        orders = load("orders.json", [])
        navh = load("nav_history.json", [])
        print(json.dumps(compute_performance(fund, orders, navh), ensure_ascii=False, indent=2))
        print("不是买卖指令；研究信号，human executes。")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
