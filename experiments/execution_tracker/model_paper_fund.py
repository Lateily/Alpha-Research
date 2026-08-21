#!/usr/bin/env python3
"""
model_paper_fund.py — P6.1: the Model Paper Fund ledger (¥1,000,000 VIRTUAL).

The fund layer on top of paper_portfolio's fill engine — capital, sizing,
portfolio constraints, NAV, decision log, performance. It deliberately REUSES
paper_portfolio._advance (registered → no-fill-on-registration-day → T+1 →
gaps-fill-worse → no same-day sell → later-bar-stop-wins) instead of reimplementing fills: one fill
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
import math
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
WORKFLOW_DEBUG_COST_MODEL = {
    "model_version": "a-share-cost-proxy-v1",
    "commission_rate": 0.0003,
    "minimum_commission_cny": 5.0,
    "transfer_fee_rate": 0.00001,
    "sell_stamp_duty_rate": 0.0005,
    "slippage_bps": 5.0,
    "verification_status": "PROXY_UNVERIFIED",
}
MAX_VOLUME_PARTICIPATION = 0.01


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
def _round_shares(raw, ticker=None):
    """Conservative board-aware A-share quantity rounding.

    STAR names require at least 200 shares; after that the exchange permits
    one-share increments. Main-board/GEM/BSE workflow-debug orders retain the
    existing 100-share block convention.
    """
    code = str(ticker or "").split(".")[0]
    if code.startswith(("688", "689")):
        return int(raw) if raw >= 200 else 0
    return int(raw // LOT) * LOT


def size_order(nav, entry, stop, risk_pct, ticker=None):
    """shares = risk_budget / (entry-stop), lot-rounded, capped by single-name %."""
    risk_pct = max(RISK_PCT_RANGE[0], min(RISK_PCT_RANGE[1], risk_pct))
    risk_cny = nav * risk_pct
    raw = risk_cny / abs(entry - stop)
    shares = _round_shares(raw, ticker)
    max_notional = nav * MAX_NAME_PCT
    if shares * entry > max_notional:
        shares = _round_shares(max_notional / entry, ticker)
    return shares, round(shares * entry, 2), round(risk_cny, 2)


def _validate_cost_model(model):
    if not isinstance(model, dict) or set(model) != set(WORKFLOW_DEBUG_COST_MODEL):
        raise ValueError("paper cost model fields are not exact")
    for field in ("commission_rate", "transfer_fee_rate", "sell_stamp_duty_rate"):
        value = model.get(field)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"paper cost model {field} is invalid")
    if model.get("minimum_commission_cny") != 5.0:
        raise ValueError("paper cost model minimum commission must remain CNY 5")
    if not 0 <= float(model.get("slippage_bps", -1)) <= 50:
        raise ValueError("paper cost model slippage is invalid")
    if model.get("verification_status") != "PROXY_UNVERIFIED":
        raise ValueError("workflow-debug broker cost model must remain explicitly unverified")
    # governance-mutation: PAPER_EXECUTION_COST_MODEL_FROZEN
    if model != WORKFLOW_DEBUG_COST_MODEL:
        raise ValueError("workflow-debug cost model must exactly match the frozen proxy")
    return dict(model)


def transaction_cost(notional, side, model):
    model = _validate_cost_model(model)
    commission = max(
        float(model["minimum_commission_cny"]),
        float(notional) * float(model["commission_rate"]),
    )
    transfer = float(notional) * float(model["transfer_fee_rate"])
    stamp = (
        float(notional) * float(model["sell_stamp_duty_rate"])
        if side == "sell" else 0.0
    )
    # governance-mutation: PAPER_EXECUTION_COSTS_APPLIED
    return round(commission + transfer + stamp, 2)


def _open_orders(orders):
    return [o for o in orders if o["status"] in ("pending", "filled")]


class NavMarksIncomplete(Exception):
    """并非所有 filled 持仓都取到目标日定盘价。**官方 NAV 路径必须拒绝出数。**

    缺一只就回退该只的成本价,会产出「部分市值 + 部分成本」的混合 NAV,
    而它照样以当天日期正式入账 —— 混合口径比缺数据更危险,因为它看起来正常、
    不触发任何告警,且此后再也无法从账本里区分哪一天是混的。
    """

    def __init__(self, missing):
        self.missing = list(missing)
        super().__init__(f"缺目标日定盘价: {self.missing}")


def _usable_mark(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def current_nav(fund, orders, marks=None, *, require_complete_marks=False):
    """cash + Σ filled positions。

    require_complete_marks=True(官方 NAV 路径必须用):任一 filled 持仓缺目标日
    定盘价即抛 NavMarksIncomplete,绝不产出混合口径。
    默认 False 只供 --status 一类的**只读估算**,其结果不得写入 nav_history。
    """
    marks = marks or {}
    valid_marks = {ticker: mark for ticker, raw in marks.items()
                   if (mark := _usable_mark(raw)) is not None}
    missing = [o["ticker"] for o in orders
               if o["status"] == "filled" and o["ticker"] not in valid_marks]
    if require_complete_marks and missing:
        raise NavMarksIncomplete(missing)
    nav = fund["cash"]
    for o in orders:
        if o["status"] == "filled":
            nav += o["shares"] * valid_marks.get(o["ticker"], o["fill_price"])
    return round(nav, 2)


# ---------------------------------------------------------------- register ----
def register_order(fund, orders, decision_log, *, ticker, name, theme, setup,
                   registered_at, entry, stop, target, risk_pct, reason,
                   invalid_if="", gate_state="", marks=None,
                   max_fill_price=None, cost_model=None,
                   max_volume_participation=MAX_VOLUME_PARTICIPATION,
                   execution_mode="LEGACY_DAILY_BAR"):
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

    realistic = execution_mode == pp.EXECUTION_MODEL_VERSION
    if realistic:
        if not isinstance(max_fill_price, (int, float)) or not entry <= max_fill_price < target:
            return refuse("realistic paper order needs entry <= max_fill_price < target")
        if not isinstance(max_volume_participation, (int, float)) or not 0 < max_volume_participation <= 0.01:
            return refuse("realistic paper order participation must be in (0, 1%]")
        try:
            cost_model = _validate_cost_model(cost_model)
        except ValueError as exc:
            return refuse(str(exc))
    sizing_price = float(max_fill_price) if realistic else float(entry)
    shares, notional, risk_cny = size_order(nav, sizing_price, stop, risk_pct, ticker)
    if shares <= 0:
        return refuse("sized to 0 shares (risk budget too small vs stop distance)")
    reserved_fee = transaction_cost(notional, "buy", cost_model) if realistic else 0.0

    # Codex adversarial review of #120 (blocking 2): theme exposure must use CURRENT
    # marks for filled positions — entry-price sums under-count winners and let a
    # theme already past 40% keep adding.
    theme_exposure = notional
    for o in _open_orders(orders):
        if o.get("theme") != theme:
            continue
        if o["status"] == "filled":
            theme_exposure += o["shares"] * (marks or {}).get(o["ticker"], o["fill_price"])
        else:
            theme_exposure += o["notional"]
    if theme_exposure > nav * MAX_THEME_PCT:
        return refuse(f"theme {theme} mark-aware exposure would be {theme_exposure/nav:.0%} > {MAX_THEME_PCT:.0%}")

    # Codex adversarial review of #120 (blocking 1): pending orders RESERVE cash —
    # several pendings can each pass a per-order check yet jointly breach the floor
    # if they all fill.
    reserved_pending = sum(o["notional"] for o in orders if o["status"] == "pending")
    if fund["cash"] - reserved_pending - notional - reserved_fee < nav * MIN_CASH_PCT:
        return refuse(f"cash floor: cash {fund['cash']:,.0f} − pending reserve {reserved_pending:,.0f} "
                      f"− new {notional + reserved_fee:,.0f} would leave < {MIN_CASH_PCT:.0%} NAV")

    order = {
        "entry_id": f"{ticker}_{registered_at}_{setup}",
        "ticker": ticker, "name": name, "theme": theme, "setup": setup,
        "direction": "long", "registered_at": registered_at,
        "entry_review_price": entry, "stop_reference": stop,
        "take_profit_reference": target, "invalid_if": invalid_if,
        "risk_R": round((target - entry) / (entry - stop), 2),
        "risk_budget_cny": risk_cny, "shares": shares, "notional": notional,
        "max_fill_price": max_fill_price if realistic else None,
        "max_volume_participation": max_volume_participation if realistic else None,
        "slippage_bps": cost_model["slippage_bps"] if realistic else 0.0,
        "execution_mode": execution_mode,
        "cost_model": cost_model if realistic else None,
        "entry_gross_cny": None, "entry_fees_cny": None,
        "exit_gross_cny": None, "exit_fees_cny": None,
        "net_pnl_cny": None,
        "reason": reason, "no_trade_flag": True,
        # governance-mutation: PAPER_EXECUTION_DEBUG_NOT_CLAIM_SAMPLE
        "sample_eligible": False if realistic else True,
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
def process_day(fund, orders, decision_log, token, series_fn=None, *,
                require_realistic=False):
    """Advance fills/exits from SETTLED bars via paper_portfolio._advance (the one
    fill engine), then settle cash. Returns list of events."""
    series_fn = series_fn or (
        pp.execution_ohlc_series if require_realistic else pp.qfq_ohlc_series
    )
    events, cache = [], {}
    for o in orders:
        if o["status"] == "closed":
            continue
        if o["ticker"] not in cache:
            cache[o["ticker"]] = series_fn(o["ticker"], token, o["registered_at"])
        was = o["status"]
        changed = pp._advance(
            o, cache[o["ticker"]], require_realistic=require_realistic,
        )
        if not changed:
            continue
        if was == "pending" and o["status"] in ("filled", "closed"):
            gross = round(o["shares"] * o["fill_price"], 2)
            fee = transaction_cost(gross, "buy", o["cost_model"]) if require_realistic else 0.0
            o["entry_gross_cny"] = gross
            o["entry_fees_cny"] = fee
            fund["cash"] = round(fund["cash"] - gross - fee, 2)
            events.append(f"FILL {o['name']} {o['shares']}股 @{o['fill_price']} ({o['fill_date']})")
            decision_log.append({"date": o["fill_date"], "action": "PAPER_FILL",
                                 "ticker": o["ticker"], "price": o["fill_price"],
                                 "shares": o["shares"], "fees_cny": fee,
                                 "no_trade_flag": True})
        if o["status"] == "closed":
            gross = round(o["shares"] * o["exit_price"], 2)
            fee = transaction_cost(gross, "sell", o["cost_model"]) if require_realistic else 0.0
            fund["cash"] = round(fund["cash"] + gross - fee, 2)
            entry_gross = float(o.get("entry_gross_cny") or o["shares"] * o["fill_price"])
            entry_fees = float(o.get("entry_fees_cny") or 0.0)
            pnl = round(gross - fee - entry_gross - entry_fees, 2)
            o["exit_gross_cny"] = gross
            o["exit_fees_cny"] = fee
            o["net_pnl_cny"] = pnl
            o["pnl_cny"] = pnl
            o["paper_return"] = round(pnl / (entry_gross + entry_fees), 6)
            gross_risk = o["shares"] * (o["fill_price"] - o["stop_reference"])
            o["realized_R"] = round(pnl / gross_risk, 3) if gross_risk > 0 else None
            events.append(f"EXIT {o['name']} @{o['exit_price']} [{o['exit_reason']}] "
                          f"PnL {o['pnl_cny']:+,.0f} (R={o['realized_R']})")
            decision_log.append({"date": o["exit_date"], "action": "PAPER_EXIT",
                                 "ticker": o["ticker"], "price": o["exit_price"],
                                 "exit_reason": o["exit_reason"], "fees_cny": fee,
                                 "pnl_cny": o["pnl_cny"],
                                 "realized_R": o["realized_R"], "no_trade_flag": True})
    return events


def execution_realism_receipt(order):
    """Classify a paper order for workflow debugging without granting claims."""
    realistic_mode = order.get("execution_mode") == pp.EXECUTION_MODEL_VERSION
    try:
        _validate_cost_model(order.get("cost_model"))
        cost_model_valid = True
    except ValueError:
        cost_model_valid = False
    checks = {
        "raw_settled_execution_bars": realistic_mode,
        "t_plus_one_sell": realistic_mode,
        "registered_no_chase_limit": (
            isinstance(order.get("max_fill_price"), (int, float))
            and order["max_fill_price"] >= order.get("entry_review_price", math.inf)
        ),
        "price_limit_facts_required": realistic_mode,
        "liquidity_participation_capped": (
            order.get("max_volume_participation") == MAX_VOLUME_PARTICIPATION
        ),
        "costs_recorded": cost_model_valid,
        "workflow_debug_sample_excluded": order.get("sample_eligible") is False,
    }
    all_ready = all(checks.values())
    return {
        "schema": "ar.paper_execution_realism_receipt",
        "schema_version": "1.0",
        "status": "PASS_WORKFLOW_DEBUG" if all_ready else "DATA_BLOCKED",
        "checks": checks,
        "cost_verification_status": (
            (order.get("cost_model") or {}).get("verification_status")
        ),
        "known_residuals": [
            "DAILY_OHLC_HAS_NO_INTRADAY_SEQUENCE",
            "BROKER_COMMISSION_SCHEDULE_NOT_BOUND_TO_STATEMENT",
            "NO_QUEUE_POSITION_MODEL_AT_PRICE_LIMIT",
            "TARGET_TOUCH_ASSUMES_FULL_FILL_AT_REGISTERED_LEVEL",
            "NO_PARTIAL_FILL_MODEL",
        ],
        # governance-mutation: PAPER_EXECUTION_RECEIPT_NO_CLAIM
        "method_claim_sample_eligible": False,
        "portfolio_promotion_eligible": False,
        "no_trade_flag": True,
    }


def update_nav(fund, orders, nav_history, date, marks=None, *,
               require_complete_marks=False):
    nav = current_nav(fund, orders, marks, require_complete_marks=require_complete_marks)
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
    closed_all = [o for o in orders if o["status"] == "closed"]
    # governance-mutation: PAPER_EXECUTION_CLAIM_COUNT_EXCLUDES_DEBUG
    closed = [o for o in closed_all if o.get("sample_eligible") is True]
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
        "n_closed": len(closed_all), "n_claim_eligible": n,
        "n_workflow_debug_closed": len(closed_all) - n,
        "n_open": sum(1 for o in orders if o["status"] == "filled"),
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

    # ---- Codex adversarial probes (#120 review, blocking findings) ----
    # B1: pending orders must RESERVE cash — jointly, not per-order.
    fund4 = init_fund(fund_dir=tempfile.mkdtemp(), date="20260703")
    fund4["cash"] = 400_000.0
    orders4, dlog4 = [], []
    for i in range(3):   # 3 filled positions marked 200k each -> NAV 1M
        orders4.append({"entry_id": f"F{i}", "ticker": f"F{i}.SZ", "name": f"f{i}", "theme": f"th{i}",
                        "status": "filled", "shares": 1000, "fill_price": 200.0,
                        "entry_review_price": 200.0, "notional": 200_000.0})
    marks4 = {f"F{i}.SZ": 200.0 for i in range(3)}
    ck("probe NAV = 1M (400k cash + 600k marks)", current_nav(fund4, orders4, marks4) == 1_000_000.0)
    p1, m1 = register_order(fund4, orders4, dlog4, ticker="P1.SZ", name="p1", theme="新1",
                            setup="S", registered_at="20260703", entry=100.0, stop=95.0,
                            target=115.0, risk_pct=0.01, reason="t", marks=marks4)
    ck("B1: first 150k pending ok (400-0-150=250k >= 200k floor)", p1 is not None)
    p2, m2 = register_order(fund4, orders4, dlog4, ticker="P2.SZ", name="p2", theme="新2",
                            setup="S", registered_at="20260703", entry=100.0, stop=95.0,
                            target=115.0, risk_pct=0.01, reason="t", marks=marks4)
    ck("B1: second pending REFUSED (400-150-150=100k < 200k floor)",
       p2 is None and "pending reserve" in m2)

    # B2: theme cap must use CURRENT marks for filled positions.
    fund5 = init_fund(fund_dir=tempfile.mkdtemp(), date="20260703")
    fund5["cash"] = 1_000_000.0
    orders5, dlog5 = [], []
    for i in range(2):   # 2 AI positions entered @100, now marked 250 -> real AI exposure 500k
        orders5.append({"entry_id": f"A{i}", "ticker": f"A{i}.SZ", "name": f"a{i}", "theme": "AI",
                        "status": "filled", "shares": 1000, "fill_price": 100.0,
                        "entry_review_price": 100.0, "notional": 100_000.0})
    marks5 = {"A0.SZ": 250.0, "A1.SZ": 250.0}
    # NAV = 1M + 500k = 1.5M; cap 40% = 600k; entry-price sum would say only 200k (the old hole)
    p3, m3 = register_order(fund5, orders5, dlog5, ticker="A9.SZ", name="a9", theme="AI",
                            setup="S", registered_at="20260703", entry=100.0, stop=95.0,
                            target=115.0, risk_pct=0.01, reason="t", marks=marks5)
    ck("B2: AI order REFUSED on mark-aware exposure (500k+220k > 600k cap)",
       p3 is None and "mark-aware" in m3)
    p4, m4 = register_order(fund5, orders5, dlog5, ticker="B9.SZ", name="b9", theme="电力",
                            setup="S", registered_at="20260703", entry=100.0, stop=95.0,
                            target=115.0, risk_pct=0.01, reason="t", marks=marks5)
    ck("B2: non-AI theme still accepted (cap is per-theme)", p4 is not None)

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
    ap.add_argument("--daily", action="store_true",
                    help="每日结算:推进成交/退出并按当轮 target 追加 NAV(append-only,一天一条)")
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
    if args.daily:
        # NAV 每日更新此前**没有任何 CLI 入口**,update_nav 定义了却从不被调用 ——
        # 这就是 nav_history 停在 0731、把 model_portfolio_state 拖成 STALE_INPUT 的根因。
        from nightly_context import run_id, target_trade_date
        date = target_trade_date()
        if not date:
            print("DATA_BLOCKED: 无 target_trade_date"); return 1
        fund = load("fund.json", None)
        if not fund:
            print("DATA_BLOCKED: fund.json 未初始化 — 先跑 --init"); return 1
        orders = load("orders.json", [])
        decision_log = load("decision_log.json", [])
        navh = load("nav_history.json", [])
        token = os.environ.get("TUSHARE_TOKEN", "").strip()
        events = []
        if token and not os.environ.get("AR_OFFLINE"):
            try:
                events = process_day(fund, orders, decision_log, token)
            except Exception as e:                      # 行情失败不伪造:只是不推进
                print(f"WARN 推进成交失败(不影响 NAV 标记): {e}")
        marks = None
        if token and not os.environ.get("AR_OFFLINE"):
            marks = {}
            for o in orders:
                if o["status"] != "filled":
                    continue
                try:
                    s = pp.qfq_ohlc_series(o["ticker"], token, o["registered_at"])
                    if not s:
                        continue
                    bar = s[-1]
                    # qfq_ohlc_series 返回的是 **dict** 列表({date,open,high,low,close}),
                    # 不是元组。初版按 s[-1][4] 取值必然拿不到,marks 全空 ⇒ NAV 悄悄
                    # 回退成成本价,产出一个看起来正常的假 NAV。按 dict 取,并要求
                    # 该 bar 的日期就是本轮 target,否则宁可不标也不用旧价。
                    close = bar.get("close") if isinstance(bar, dict) else (
                        bar[4] if isinstance(bar, (list, tuple)) and len(bar) > 4 else None)
                    bar_date = str(bar.get("date") if isinstance(bar, dict) else "")[:8]
                    usable_close = _usable_mark(close)
                    if usable_close is not None and bar_date == date:
                        marks[o["ticker"]] = usable_close
                    elif usable_close is not None:
                        print(f"  WARN {o['ticker']} 最新 bar {bar_date} ≠ target {date},不用于标记")
                except Exception as e:
                    print(f"  WARN {o['ticker']} 取价失败: {str(e)[:50]}")
            marks = {k: v for k, v in marks.items() if v} or None
            if marks:
                print(f"  marks: {marks}")
            else:
                print("  WARN 无可用收盘价 ⇒ NAV 按成本标记(不是市值)")
        try:
            rec = update_nav(fund, orders, navh, date, marks=marks,
                             require_complete_marks=True)
        except NavMarksIncomplete as e:
            # 官方 NAV 宁可不出,也不出混合口径。不写任何账本、非零退出、显式 DATA_BLOCKED。
            print(f"DATA_BLOCKED: {date} 有 filled 持仓未取到目标日定盘价 {e.missing} —— "
                  f"拒绝写入 NAV(不接受部分市值+部分成本的混合口径)")
            print("不是买卖指令；研究信号，human executes。")
            return 1
        save("fund.json", fund); save("orders.json", orders)
        save("decision_log.json", decision_log); save("nav_history.json", navh)
        print(f"[daily] {date} nav={rec['nav']:,.0f} cash={rec['cash']:,.0f} "
              f"n_pos={rec['n_positions']} events={len(events)} run_id={run_id()}")
        for e in events:
            print("  ", e)
        print("不是买卖指令；研究信号，human executes。")
        return 0

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
    # main() 返回 1 表示 DATA_BLOCKED(如缺目标日定盘价);不 sys.exit 的话进程仍退 0,
    # 夜链会把「拒绝写 NAV」当成功。execution_tracker / run_official_sample 早已修过,
    # 这里漏了 —— 而漏掉它的原因是那条测试只检查源码里有没有 `return 1`,没跑进程。
    sys.exit(main() or 0)
