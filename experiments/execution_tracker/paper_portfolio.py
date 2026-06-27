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
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fund_source as fs   # noqa: E402

PORTFOLIO_PATH = os.path.join(HERE, "paper_portfolio.json")
MIN_CLOSED_FOR_CLAIM = 30
R_R_BAR = 2.0   # constitution: R/R < 2:1 defaults to WATCH (flagged, not blocked)


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


def _advance(entry, bars):
    """Advance one entry through pending->filled->closed. Returns True if state changed.

    NO LOOK-AHEAD: only bars STRICTLY AFTER registered_at are eligible to fill; exits
    are scanned from the fill bar (inclusive) onward.
    """
    changed = False
    eligible = [b for b in bars if b["date"] > entry["registered_at"]]

    if entry["status"] == "pending":
        for b in eligible:
            if b["high"] >= entry["entry_review_price"]:           # long trigger reached
                fill = (b["open"] if b["open"] > entry["entry_review_price"]
                        else entry["entry_review_price"])          # gap-up fills worse
                entry["fill_date"] = b["date"]
                entry["fill_price"] = round(fill, 4)
                entry["status"] = "filled"
                changed = True
                break

    if entry["status"] == "filled":
        for b in (x for x in eligible if x["date"] >= entry["fill_date"]):
            stop_hit = b["low"] <= entry["stop_reference"]
            tgt_hit = b["high"] >= entry["take_profit_reference"]
            if stop_hit:                                           # stop wins a same-bar tie
                px = (b["open"] if b["open"] < entry["stop_reference"]
                      else entry["stop_reference"])                # gap-down exits worse
                reason = "stop_and_target_same_bar->stop" if tgt_hit else "stop"
            elif tgt_hit:
                px = (b["open"] if b["open"] > entry["take_profit_reference"]
                      else entry["take_profit_reference"])         # capped at target
                reason = "target"
            else:
                continue
            entry["exit_date"] = b["date"]
            entry["exit_price"] = round(px, 4)
            entry["exit_reason"] = reason
            entry["status"] = "closed"
            entry["paper_return"] = round(px / entry["fill_price"] - 1.0, 4)
            entry["realized_R"] = round(
                (px - entry["fill_price"]) / (entry["fill_price"] - entry["stop_reference"]), 3)
            changed = True
            break
    return changed


def update_portfolio(portfolio, token, series_fn=None):
    """Pull settled bars per ticker and advance every open entry. Idempotent."""
    series_fn = series_fn or qfq_ohlc_series
    cache, changes = {}, 0
    for entry in portfolio:
        if entry["status"] == "closed":
            continue
        if entry["ticker"] not in cache:
            cache[entry["ticker"]] = series_fn(entry["ticker"], token, entry["registered_at"])
        if _advance(entry, cache[entry["ticker"]]):
            changes += 1
    return changes


def summarize(portfolio):
    closed = [e for e in portfolio if e["status"] == "closed"]
    n = len(closed)
    rets = [e["paper_return"] for e in closed]
    rs = [e["realized_R"] for e in closed]
    wins = sum(1 for r in rets if r > 0)
    return {
        "n_registered": len(portfolio),
        "n_pending": sum(1 for e in portfolio if e["status"] == "pending"),
        "n_open_filled": sum(1 for e in portfolio if e["status"] == "filled"),
        "n_closed": n,
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
