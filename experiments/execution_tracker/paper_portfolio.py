#!/usr/bin/env python3
"""
paper_portfolio.py — P3 of MODEL_UPGRADE_TREE: the paper-portfolio record layer.

This is the compliant landing for "给入场价" (giving an entry price). It is NOT a
trade instruction: every entry carries no_trade_flag. It records, as PAPER, what the
model proposed — `entry_review_price / stop_reference / take_profit_reference` — and
then measures, from settled 定盘 bars, whether acting on it would have paid off.

Lifecycle: register -> (no-lookahead fill) -> (stop/target exit) -> realized paper PnL.

IRON LAWS (enforced in code + selftest):
  - NO LOOK-AHEAD. A pending entry can fill ONLY on a settled bar whose date is
    STRICTLY AFTER registered_at (you register at the close of day T; the earliest
    possible fill is T+1). Exits are scanned only from the fill bar onward. An entry's
    registered_at / entry_review_price are never re-stamped after the fact.
  - GAPS FILL WORSE. A gap-up through the long entry fills at the open (worse than the
    trigger); a gap-down through the stop exits at the open (worse than the stop);
    target exits are capped at the target. No optimistic fills.
  - SAME-BAR stop+target -> assume STOP (conservative).
  - NO win-rate / PnL CLAIM below 30 closed paper trades (`claim_allowed`).

Long-only v1 (A-share). Needs TUSHARE_TOKEN for --update (`source ~/.zprofile`).
  python3 paper_portfolio.py --selftest
  python3 paper_portfolio.py --register --ticker 300502.SZ --name 新易盛 \
      --setup RELATIVE_STRENGTH_RECLAIM --date 20260625 \
      --entry 591 --stop 550 --target 680
  python3 paper_portfolio.py --update     # advance fills/exits from settled bars
  python3 paper_portfolio.py --summary
"""
import argparse
import datetime as dt
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fund_source as fs   # noqa: E402

PORTFOLIO_PATH = os.path.join(HERE, "paper_portfolio.json")
MIN_CLOSED_FOR_CLAIM = 30
R_R_BAR = 2.0   # constitution: R/R < 2:1 defaults to WATCH (flagged, not blocked)
EXECUTION_MODEL_VERSION = "a-share-daily-realism-v1"
REALISTIC_BAR_FIELDS = {
    "date", "open", "high", "low", "close", "pre_close",
    "up_limit", "down_limit", "volume_shares", "amount_cny",
    "suspended", "settled", "price_basis", "source",
}
PRICE_CHAIN_REL_TOL = 1e-4
PRICE_CHAIN_ABS_TOL = 0.01


def load_portfolio(path=PORTFOLIO_PATH):
    return json.load(open(path)) if os.path.exists(path) else []


def save_portfolio(portfolio, path=PORTFOLIO_PATH):
    with open(path, "w") as fh:
        json.dump(portfolio, fh, ensure_ascii=False, indent=2)


def register_entry(portfolio, *, ticker, name, setup, registered_at,
                   entry_review_price, stop_reference, take_profit_reference,
                   position_posture="paper_small"):
    """Register a PAPER long entry. Refuses a mutilated setup (need stop<entry<target)."""
    if not (stop_reference < entry_review_price < take_profit_reference):
        raise ValueError(
            f"mutilated long setup: need stop < entry < target, got "
            f"stop={stop_reference} entry={entry_review_price} target={take_profit_reference}")
    entry_id = f"{ticker}_{registered_at}_{setup}"
    if any(e["entry_id"] == entry_id for e in portfolio):
        raise ValueError(f"duplicate entry_id {entry_id}")
    risk_r = round((take_profit_reference - entry_review_price) /
                   (entry_review_price - stop_reference), 2)
    entry = {
        "entry_id": entry_id, "ticker": ticker, "name": name, "setup": setup,
        "direction": "long", "registered_at": registered_at,
        "entry_review_price": entry_review_price, "stop_reference": stop_reference,
        "take_profit_reference": take_profit_reference, "risk_R": risk_r,
        "rr_below_2to1": risk_r < R_R_BAR,
        "position_posture": position_posture,
        "no_trade_flag": True, "sample_eligible": True,
        "status": "pending",
        "fill_date": None, "fill_price": None,
        "exit_date": None, "exit_price": None, "exit_reason": None,
        "paper_return": None, "realized_R": None,
    }
    portfolio.append(entry)
    return entry


def qfq_ohlc_series(ticker, token, start_date):
    """Ordered [{date,open,high,low,close}] 前复权 from start_date. Settled bars only."""
    daily = fs._tushare_call("daily", token, {"ts_code": ticker, "start_date": start_date},
                             "trade_date,open,high,low,close")
    adj = fs._tushare_call("adj_factor", token, {"ts_code": ticker, "start_date": start_date},
                           "trade_date,adj_factor")
    fields = daily.get("fields", [])
    rows = sorted((dict(zip(fields, it)) for it in daily.get("items", [])),
                  key=lambda r: r["trade_date"])
    amap = {it[0]: it[1] for it in adj.get("items", [])}
    if not rows:
        return []
    latest_adj = amap.get(rows[-1]["trade_date"]) or 1.0
    out = []
    for r in rows:
        f = (amap.get(r["trade_date"]) or latest_adj) / latest_adj
        out.append({"date": r["trade_date"], "open": r["open"] * f, "high": r["high"] * f,
                    "low": r["low"] * f, "close": r["close"] * f})
    return out


def execution_ohlc_series(ticker, token, start_date):
    """Raw settled A-share bars with explicit execution facts.

    Registered entry/stop/target levels are authored in contemporaneous raw-price
    space, so adjusted history is not a valid execution surface. Tushare ``vol``
    is reported in hands and ``amount`` in thousand CNY; normalize both here so
    downstream participation checks never need to guess units.
    """
    daily = fs._tushare_call(
        "daily", token, {"ts_code": ticker, "start_date": start_date},
        "trade_date,open,high,low,close,pre_close,vol,amount",
    )
    limits = fs._tushare_call(
        "stk_limit", token, {"ts_code": ticker, "start_date": start_date},
        "trade_date,up_limit,down_limit",
    )
    fields = daily.get("fields", [])
    limit_fields = limits.get("fields", [])
    limit_rows = {
        str(row.get("trade_date")): row
        for item in limits.get("items", [])
        for row in (dict(zip(limit_fields, item)),)
    }
    rows = []
    for item in daily.get("items", []):
        row = dict(zip(fields, item))
        trade_date = str(row.get("trade_date"))
        limit = limit_rows.get(trade_date) or {}
        rows.append({
            "date": trade_date,
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "pre_close": row.get("pre_close"),
            "up_limit": limit.get("up_limit"),
            "down_limit": limit.get("down_limit"),
            "volume_shares": float(row.get("vol") or 0) * 100.0,
            "amount_cny": float(row.get("amount") or 0) * 1000.0,
            "suspended": False,
            "settled": True,
            "price_basis": "RAW_UNADJUSTED",
            "source": "TUSHARE_DAILY_STK_LIMIT",
        })
    return sorted(rows, key=lambda row: row["date"])


def _number(value):
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _execution_date(value):
    value = str(value or "")
    if len(value) != 8 or not value.isdigit():
        raise ValueError("execution date must be YYYYMMDD")
    try:
        dt.datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("execution date must be a real calendar date") from exc
    return value


def validate_realistic_bar(bar):
    if not isinstance(bar, dict) or set(bar) != REALISTIC_BAR_FIELDS:
        raise ValueError("realistic execution bar fields are not exact")
    # governance-mutation: PAPER_EXECUTION_RAW_SETTLED_BARS
    if bar.get("price_basis") != "RAW_UNADJUSTED" or bar.get("settled") is not True:
        raise ValueError("execution bar must be raw, unadjusted, and settled")
    if bar.get("source") not in {"TUSHARE_DAILY_STK_LIMIT", "OFFLINE_FIXTURE_SETTLED_V2"}:
        raise ValueError("execution bar source is not approved")
    _execution_date(bar.get("date"))
    if not isinstance(bar.get("suspended"), bool):
        raise ValueError("execution bar suspended flag must be boolean")
    required_prices = ("open", "high", "low", "close", "pre_close", "up_limit", "down_limit")
    if any(not _number(bar.get(key)) or float(bar[key]) <= 0 for key in required_prices):
        raise ValueError("execution bar contains invalid price facts")
    if any(not _number(bar.get(key)) or float(bar[key]) < 0 for key in ("volume_shares", "amount_cny")):
        raise ValueError("execution bar contains invalid liquidity facts")
    if not bar["suspended"] and (bar["volume_shares"] <= 0 or bar["amount_cny"] <= 0):
        raise ValueError("tradable execution bar lacks positive liquidity facts")
    if bar["high"] < max(bar["open"], bar["low"], bar["close"]):
        raise ValueError("execution bar high is impossible")
    if bar["low"] > min(bar["open"], bar["high"], bar["close"]):
        raise ValueError("execution bar low is impossible")
    return bar


def _record_block(entry, bar, reason):
    block = {"date": bar["date"], "reason": reason}
    blocks = entry.setdefault("execution_blocks", [])
    if block not in blocks:
        blocks.append(block)
    entry["last_execution_blocker"] = reason


def _price_chain_breaks(bars, registered_at):
    """Map post-registration bars whose raw-price chain is discontinuous."""
    breaks = {}
    for previous, current in zip(bars, bars[1:]):
        if current["date"] <= registered_at:
            continue
        prior_close = float(previous["close"])
        current_pre_close = float(current["pre_close"])
        if not math.isclose(
            current_pre_close,
            prior_close,
            rel_tol=PRICE_CHAIN_REL_TOL,
            abs_tol=PRICE_CHAIN_ABS_TOL,
        ):
            breaks[current["date"]] = {
                "previous_date": previous["date"],
                "previous_close": prior_close,
                "current_pre_close": current_pre_close,
            }
    return breaks


def _freeze_on_corporate_action_break(entry, bar, price_chain_breaks):
    detail = price_chain_breaks.get(bar["date"])
    # governance-mutation: PAPER_EXECUTION_CORPORATE_ACTION_FREEZE
    if detail is not None:
        _record_block(entry, bar, "CORPORATE_ACTION_BREAK")
        entry["execution_frozen"] = True
        entry["execution_freeze_reason"] = "CORPORATE_ACTION_BREAK"
        entry["execution_freeze_date"] = bar["date"]
        entry["execution_freeze_evidence"] = detail
        return True
    return False


def _one_price_at(bar, field):
    level = float(bar[field])
    return all(abs(float(bar[key]) - level) <= 1e-8 for key in ("open", "high", "low", "close"))


def _participation_ok(entry, bar):
    shares = entry.get("shares")
    cap = entry.get("max_volume_participation")
    if not _number(shares) or not _number(cap) or not (0 < float(cap) <= 0.01):
        raise ValueError("realistic execution needs shares and max participation <= 1%")
    return float(shares) <= float(bar["volume_shares"]) * float(cap)


def _advance(entry, bars, *, require_realistic=False):
    """Advance one entry through pending->filled->closed. Returns True if state changed.

    NO LOOK-AHEAD: only bars STRICTLY AFTER registered_at are eligible to fill;
    A-share exits are scanned strictly after the fill date.
    """
    changed = False
    if require_realistic:
        # governance-mutation: PAPER_EXECUTION_FROZEN_STAYS_FROZEN
        if entry.get("execution_frozen") is True:
            return False
        for bar in bars:
            validate_realistic_bar(bar)
        dates = [bar["date"] for bar in bars]
        # governance-mutation: PAPER_EXECUTION_DATE_SEQUENCE
        if dates != sorted(set(dates)):
            raise ValueError("realistic execution bars must be strictly ordered and unique")
        _execution_date(entry.get("registered_at"))
        price_chain_breaks = _price_chain_breaks(bars, entry["registered_at"])
    else:
        price_chain_breaks = {}
    eligible = [b for b in bars if b["date"] > entry["registered_at"]]

    if entry["status"] == "pending":
        for b in eligible:
            if require_realistic and _freeze_on_corporate_action_break(
                entry, b, price_chain_breaks,
            ):
                return True
            if require_realistic and b["suspended"]:
                _record_block(entry, b, "SUSPENDED")
                continue
            if b["high"] >= entry["entry_review_price"]:           # long trigger reached
                # governance-mutation: PAPER_EXECUTION_LIMIT_UP_NO_BUY
                if require_realistic and _one_price_at(b, "up_limit"):
                    _record_block(entry, b, "ONE_PRICE_LIMIT_UP_NO_BUY")
                    continue
                # governance-mutation: PAPER_EXECUTION_LIQUIDITY_CAP
                if require_realistic and not _participation_ok(entry, b):
                    _record_block(entry, b, "LIQUIDITY_PARTICIPATION_EXCEEDED")
                    continue
                base_fill = (b["open"] if b["open"] > entry["entry_review_price"]
                             else entry["entry_review_price"])
                slippage = float(entry.get("slippage_bps") or 0) / 10_000.0
                fill = min(float(b["high"]), float(base_fill) * (1.0 + slippage))
                max_fill = entry.get("max_fill_price")
                # The registered ceiling includes modeled slippage. Checking only
                # the pre-slippage price lets a nominally legal fill exceed both
                # the frozen SMC zone and the cash reserved at registration.
                # governance-mutation: PAPER_EXECUTION_NO_CHASE_LIMIT
                if require_realistic and (not _number(max_fill) or fill > float(max_fill)):
                    _record_block(entry, b, "FILL_ABOVE_REGISTERED_ENTRY_LIMIT")
                    continue
                entry["fill_date"] = b["date"]
                entry["fill_price"] = round(fill, 4)
                entry["fill_execution_quality"] = (
                    EXECUTION_MODEL_VERSION if require_realistic else "LEGACY_DAILY_BAR"
                )
                entry["status"] = "filled"
                changed = True
                break

    if entry["status"] == "filled":
        # A-share cash equities bought on T cannot be sold on T. This strict
        # comparison is the sell-side half of T+1; the old inclusive scan could
        # manufacture an impossible fill-and-exit on the same daily bar.
        # governance-mutation: PAPER_EXECUTION_T1_SELL
        for b in (x for x in eligible if x["date"] > entry["fill_date"]):
            if require_realistic and _freeze_on_corporate_action_break(
                entry, b, price_chain_breaks,
            ):
                return True
            if require_realistic and b["suspended"]:
                _record_block(entry, b, "SUSPENDED")
                continue
            stop_hit = b["low"] <= entry["stop_reference"]
            tgt_hit = b["high"] >= entry["take_profit_reference"]
            if stop_hit:                                           # stop wins a same-bar tie
                # governance-mutation: PAPER_EXECUTION_LIMIT_DOWN_NO_SELL
                if require_realistic and _one_price_at(b, "down_limit"):
                    _record_block(entry, b, "ONE_PRICE_LIMIT_DOWN_NO_SELL")
                    continue
                px = (b["open"] if b["open"] < entry["stop_reference"]
                      else entry["stop_reference"])                # gap-down exits worse
                if require_realistic:
                    slippage = float(entry.get("slippage_bps") or 0) / 10_000.0
                    px = max(float(b["low"]), float(px) * (1.0 - slippage))
                reason = "stop_and_target_same_bar->stop" if tgt_hit else "stop"
            elif tgt_hit:
                # CAPPED AT TARGET even when price gaps above it — taking the open on a
                # gap-up would be an optimistic fill, violating the module's own iron
                # law (line caught by Codex review of #120: code deviated from doc).
                px = entry["take_profit_reference"]
                reason = "target"
            else:
                continue
            entry["exit_date"] = b["date"]
            entry["exit_price"] = round(px, 4)
            entry["exit_reason"] = reason
            entry["exit_execution_quality"] = (
                EXECUTION_MODEL_VERSION if require_realistic else "LEGACY_DAILY_BAR"
            )
            entry["status"] = "closed"
            entry["paper_return"] = round(px / entry["fill_price"] - 1.0, 4)
            entry["realized_R"] = round(
                (px - entry["fill_price"]) / (entry["fill_price"] - entry["stop_reference"]), 3)
            changed = True
            break
    return changed


def update_portfolio(portfolio, token, series_fn=None, *, require_realistic=False):
    """Pull settled bars per ticker and advance every open entry. Idempotent."""
    series_fn = series_fn or (
        execution_ohlc_series if require_realistic else qfq_ohlc_series
    )
    cache, changes = {}, 0
    for entry in portfolio:
        if entry["status"] == "closed":
            continue
        if entry["ticker"] not in cache:
            cache[entry["ticker"]] = series_fn(entry["ticker"], token, entry["registered_at"])
        if _advance(entry, cache[entry["ticker"]], require_realistic=require_realistic):
            changes += 1
    return changes


def summarize(portfolio):
    closed_all = [e for e in portfolio if e["status"] == "closed"]
    # Workflow-debug fills remain useful execution evidence, but they cannot
    # leak into the method-claim denominator.
    closed = [e for e in closed_all if e.get("sample_eligible") is True]
    n = len(closed)
    rets = [e["paper_return"] for e in closed]
    rs = [e["realized_R"] for e in closed]
    wins = sum(1 for r in rets if r > 0)
    return {
        "n_registered": len(portfolio),
        "n_pending": sum(1 for e in portfolio if e["status"] == "pending"),
        "n_open_filled": sum(1 for e in portfolio if e["status"] == "filled"),
        "n_closed": len(closed_all),
        "n_claim_eligible": n,
        "n_workflow_debug_closed": len(closed_all) - n,
        "win_rate": round(wins / n, 3) if n else None,
        "avg_paper_return": round(sum(rets) / n, 4) if n else None,
        "avg_realized_R": round(sum(rs) / n, 3) if n else None,
        "sum_paper_return": round(sum(rets), 4) if n else None,
        "min_required": MIN_CLOSED_FOR_CLAIM,
        "claim_allowed": n >= MIN_CLOSED_FOR_CLAIM,
        "unvalidated_warning": (
            f"paper PnL NOT claimable: {n}/{MIN_CLOSED_FOR_CLAIM} closed trades — descriptive only"
            if n < MIN_CLOSED_FOR_CLAIM else
            f"{n} closed — threshold met; still provisional, not validated alpha"),
    }


# ---------------------------------------------------------------- selftest ----
def selftest():
    checks = []

    def ck(n, c):
        checks.append((n, bool(c)))

    pf = []
    e = register_entry(pf, ticker="T.SZ", name="测试", setup="RECLAIM",
                       registered_at="20260101", entry_review_price=110,
                       stop_reference=105, take_profit_reference=130)
    ck("registers pending", e["status"] == "pending")
    ck("risk_R = 4.0 ((130-110)/(110-105))", e["risk_R"] == 4.0)
    ck("rr_below_2to1 False", e["rr_below_2to1"] is False)
    ck("no_trade_flag True", e["no_trade_flag"] is True)

    # mutilated setup refused
    try:
        register_entry(pf, ticker="X.SZ", name="x", setup="BAD", registered_at="20260101",
                       entry_review_price=100, stop_reference=110, take_profit_reference=130)
        ck("mutilated setup refused", False)
    except ValueError:
        ck("mutilated setup refused", True)

    # NO LOOK-AHEAD: a bar ON registered_at that reaches the trigger must NOT fill
    bars_same_day_only = [{"date": "20260101", "open": 100, "high": 120, "low": 99, "close": 119}]
    update_portfolio(pf[:1], token=None, series_fn=lambda *_: bars_same_day_only)
    ck("no-look-ahead: registration-day trigger does NOT fill", pf[0]["status"] == "pending")

    # fills on a LATER bar, at the trigger (no gap)
    bars_fill_then_stop = [
        {"date": "20260101", "open": 100, "high": 104, "low": 99, "close": 103},   # ignored (reg day)
        {"date": "20260102", "open": 108, "high": 115, "low": 107, "close": 112},  # fill @110
        {"date": "20260103", "open": 107, "high": 108, "low": 100, "close": 101},  # low<=105 -> stop @105
    ]
    pf2 = []
    register_entry(pf2, ticker="T.SZ", name="测试", setup="RECLAIM", registered_at="20260101",
                   entry_review_price=110, stop_reference=105, take_profit_reference=130)
    update_portfolio(pf2, token=None, series_fn=lambda *_: bars_fill_then_stop)
    ck("fills on T+1 not reg day", pf2[0]["fill_date"] == "20260102")
    ck("fill at trigger 110 (no gap)", pf2[0]["fill_price"] == 110)
    ck("stop exit closed", pf2[0]["status"] == "closed")
    ck("exit at stop 105", pf2[0]["exit_price"] == 105)
    ck("stop reason", pf2[0]["exit_reason"] == "stop")
    ck("paper_return ~ -0.0455", abs(pf2[0]["paper_return"] + 0.0455) < 1e-3)
    ck("realized_R = -1.0", pf2[0]["realized_R"] == -1.0)

    # gap-up fill is WORSE (at open), target hit caps at target
    bars_gap_then_target = [
        {"date": "20260101", "open": 100, "high": 104, "low": 99, "close": 103},
        {"date": "20260102", "open": 113, "high": 118, "low": 112, "close": 117},  # gap-up: fill @113
        {"date": "20260103", "open": 128, "high": 135, "low": 127, "close": 134},  # high>=130 -> target @130
    ]
    pf3 = []
    register_entry(pf3, ticker="T.SZ", name="测试", setup="RECLAIM", registered_at="20260101",
                   entry_review_price=110, stop_reference=105, take_profit_reference=130)
    update_portfolio(pf3, token=None, series_fn=lambda *_: bars_gap_then_target)
    ck("gap-up fill at open 113 (worse than 110)", pf3[0]["fill_price"] == 113)
    ck("target exit at 130 (capped)", pf3[0]["exit_price"] == 130)
    ck("target reason", pf3[0]["exit_reason"] == "target")

    # gap ABOVE target must still exit AT the target (no optimistic fills) —
    # regression for the code-vs-doc deviation caught in the #120 review
    bars_gap_above_target = [
        {"date": "20260101", "open": 100, "high": 104, "low": 99, "close": 103},
        {"date": "20260102", "open": 109, "high": 112, "low": 108, "close": 111},  # fill @110
        {"date": "20260103", "open": 135, "high": 140, "low": 133, "close": 138},  # open>130 target
    ]
    pf4 = []
    register_entry(pf4, ticker="T.SZ", name="测试", setup="RECLAIM", registered_at="20260101",
                   entry_review_price=110, stop_reference=105, take_profit_reference=130)
    update_portfolio(pf4, token=None, series_fn=lambda *_: bars_gap_above_target)
    ck("gap ABOVE target still exits at 130 (no optimistic fill)", pf4[0]["exit_price"] == 130)

    # idempotent: re-running update does nothing to closed entries
    ck("idempotent on closed", update_portfolio(pf3, token=None, series_fn=lambda *_: bars_gap_then_target) == 0)

    # summary + <30 guard
    s = summarize(pf2 + pf3)
    ck("summary counts 2 closed", s["n_closed"] == 2)
    ck("summary win_rate 0.5", s["win_rate"] == 0.5)
    ck("claim NOT allowed (<30)", s["claim_allowed"] is False)
    ck("warning present", "NOT claimable" in s["unvalidated_warning"])

    passed = sum(1 for _, ok in checks if ok)
    for n, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}")
    print(f"\nselftest: {passed}/{len(checks)} passed")
    return passed == len(checks)


def main():
    ap = argparse.ArgumentParser(description="P3 paper-portfolio record layer (no trade instructions)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--register", action="store_true")
    ap.add_argument("--ticker"); ap.add_argument("--name", default="")
    ap.add_argument("--setup", default="MANUAL"); ap.add_argument("--date", help="registered_at YYYYMMDD")
    ap.add_argument("--entry", type=float); ap.add_argument("--stop", type=float); ap.add_argument("--target", type=float)
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(0 if selftest() else 1)

    portfolio = load_portfolio()
    if args.register:
        for need in ("ticker", "date", "entry", "stop", "target"):
            if getattr(args, need) is None:
                print(f"--register needs --{need}"); sys.exit(1)
        e = register_entry(portfolio, ticker=args.ticker, name=args.name, setup=args.setup,
                           registered_at=args.date, entry_review_price=args.entry,
                           stop_reference=args.stop, take_profit_reference=args.target)
        save_portfolio(portfolio)
        print(f"registered {e['entry_id']} | risk_R={e['risk_R']}"
              f"{'  ⚠ R/R<2:1' if e['rr_below_2to1'] else ''} | status=pending | no_trade_flag=true")
        return
    if args.update:
        token = os.environ.get("TUSHARE_TOKEN", "").strip()
        if not token:
            print("NO TUSHARE_TOKEN — run `source ~/.zprofile` first"); sys.exit(1)
        ch = update_portfolio(portfolio, token)
        save_portfolio(portfolio)
        print(f"updated: {ch} entries changed state.")
    if args.update or args.summary:
        s = summarize(portfolio)
        print(json.dumps(s, ensure_ascii=False, indent=2))
        print("不是买卖指令；研究信号，human executes。")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
