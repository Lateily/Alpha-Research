#!/usr/bin/env python3
"""
weekly_recap.py — read-only weekly recap generator (step 2 of Junyan's
fixed sequence, 2026-07-11).

Reads the ledgers, emits the DATA sections of docs/team/WEEKLY_REPORT_TEMPLATE
as markdown to stdout (or --out FILE). NEVER writes any ledger — the whole
point is that the weekly report becomes a mechanical read, not a hand copy.

Rate discipline: every rate line carries {n, claim_allowed}; below the
30-sample project threshold a rate renders as 计数中 (count-in-progress),
never as a claim. closed trades = 0 => the win-rate/expectancy line prints
exactly that prohibition.

Usage:
  python3 weekly_recap.py --start 20260706 --end 20260710
  python3 weekly_recap.py --paper-ledger --start 20260706 --end 20260710
  python3 weekly_recap.py --start 20260706 --end 20260710 --out /tmp/w28.md
  python3 weekly_recap.py --selftest

不是买卖指令；研究信号，human executes。
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FUND_DIR = os.path.join(HERE, "model_fund")
MIN_SAMPLE_FOR_CLAIM = 30


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _in_window(datestr, start, end):
    d = str(datestr or "")[:8]
    return bool(d.isdigit()) and start <= d <= end


def _short(v, n=90):
    s = str(v or "").replace("\n", " ").replace("|", "/")
    return s if len(s) <= n else s[: n - 1] + "…"


def _fmt_num(v):
    if isinstance(v, (int, float)):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return "n/a"


def _fmt_pct(v):
    return f"{v * 100:+.2f}%" if isinstance(v, (int, float)) else "n/a"


def _sample_price_marks(tracker_dir, start, end):
    """Official end-date sample price per ticker, read-only.

    Do not roll old in-window samples forward: stale marks create fake returns.
    """
    marks = {}
    sample_dir = os.path.join(tracker_dir, "samples")
    if not os.path.isdir(sample_dir):
        return marks
    for fn in sorted(os.listdir(sample_dir)):
        if not (fn.endswith(".json") and fn[:8] == end and _in_window(fn[:8], start, end)):
            continue
        snap = _load(os.path.join(sample_dir, fn), {})
        date = str(snap.get("timestamp") or fn[:8])[:8]
        for gate in snap.get("ticker_gates", []):
            ticker, price = gate.get("ticker"), gate.get("price")
            if ticker and isinstance(price, (int, float)):
                marks[ticker] = {"date": date, "price": price}
    return marks


def _order_action(o):
    if o.get("status") == "filled":
        return "PAPER_FILL", o.get("fill_date") or o.get("registered_at")
    if o.get("status") == "cancelled":
        return "CANCEL_ORDER", o.get("cancelled_at") or o.get("registered_at")
    if o.get("status") == "closed":
        return "PAPER_CLOSE", o.get("exit_date") or o.get("registered_at")
    return "REGISTER_ORDER", o.get("registered_at")


def _order_return(o, marks):
    if isinstance(o.get("paper_return"), (int, float)):
        return o["paper_return"], o.get("exit_price") or o.get("fill_price")
    fill = o.get("fill_price")
    if o.get("status") == "closed" and isinstance(fill, (int, float)) and isinstance(o.get("exit_price"), (int, float)):
        return (o["exit_price"] / fill - 1), o["exit_price"]
    mark = marks.get(o.get("ticker"), {}).get("price")
    if o.get("status") == "filled" and isinstance(fill, (int, float)) and isinstance(mark, (int, float)):
        return (mark / fill - 1), mark
    return None, mark


def build_paper_ledger_review(start, end, fund_dir=FUND_DIR, tracker_dir=HERE):
    """Read-only Notion-friendly review table for paper actions and research preregs."""
    orders = _load(os.path.join(fund_dir, "orders.json"), [])
    dlog = _load(os.path.join(fund_dir, "decision_log.json"), [])
    signals = _load(os.path.join(tracker_dir, "paper_signal_log.json"), [])
    marks = _sample_price_marks(tracker_dir, start, end)

    rows = []
    for o in orders:
        action, date = _order_action(o)
        if not _in_window(date, start, end):
            continue
        ret, mark = _order_return(o, marks)
        price = o.get("fill_price") or o.get("entry_review_price")
        outcome = o.get("exit_reason") or o.get("cancel_reason")
        if not outcome:
            if o.get("status") == "filled":
                outcome = "open paper position; not scored as closed trade"
            elif o.get("status") == "pending":
                outcome = "pending trigger; no fill yet"
            else:
                outcome = str(o.get("status") or "pending")
        rows.append({
            "date": str(date or ""),
            "action": action,
            "ticker": o.get("ticker"),
            "name": o.get("name"),
            "setup": o.get("setup"),
            "status": o.get("status"),
            "shares": o.get("shares"),
            "price": price,
            "mark": mark,
            "return": ret,
            "reasoning": o.get("reason"),
            "invalidation": o.get("invalid_if"),
            "outcome": outcome,
            "source": "orders.json",
        })

    order_cancel_tickers = {o.get("ticker") for o in orders if o.get("status") == "cancelled"}
    for d in dlog:
        if not _in_window(d.get("date"), start, end):
            continue
        action = d.get("action")
        if action == "CANCEL_ORDER" and d.get("ticker") in order_cancel_tickers:
            continue
        if action not in ("NO_TRADE_DECISION", "RISK_REVIEW", "CANCEL_ORDER"):
            continue
        rows.append({
            "date": str(d.get("date") or ""),
            "action": action,
            "ticker": d.get("ticker") or d.get("scope"),
            "name": d.get("scope") or d.get("ticker") or "",
            "setup": "discipline_gate",
            "status": "blocked" if action == "NO_TRADE_DECISION" else "review",
            "shares": d.get("shares"),
            "price": d.get("entry") or d.get("price"),
            "mark": None,
            "return": None,
            "reasoning": d.get("reason") or d.get("note"),
            "invalidation": "",
            "outcome": "discipline action logged",
            "source": "decision_log.json",
        })

    for s in signals:
        if s.get("official_sample") is not False or not _in_window(s.get("timestamp"), start, end):
            continue
        rows.append({
            "date": str(s.get("timestamp") or "")[:8],
            "action": "PRE_REGISTRATION",
            "ticker": s.get("ticker"),
            "name": s.get("name"),
            "setup": s.get("setup_type"),
            "status": s.get("outcome_status") or "pending",
            "shares": None,
            "price": s.get("entry_close"),
            "mark": None,
            "return": None,
            "reasoning": s.get("hypothesis") or s.get("forecast_claim"),
            "invalidation": s.get("invalidation"),
            "outcome": "pending; research pre-registration",
            "source": "paper_signal_log.json",
        })

    rows.sort(key=lambda r: (r["date"], str(r["ticker"] or ""), r["action"]))
    lines = [f"## Paper Trading Ledger Review(自动生成 · {start}–{end} · 只读镜像)", ""]
    lines.append("| Date | Action | Ticker | Name | Setup | Status | Shares | Price | Mark | Return | Outcome | Reasoning |")
    lines.append("|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|")
    for r in rows:
        lines.append(
            "| {date} | `{action}` | {ticker} | {name} | {setup} | {status} | {shares} | {price} | {mark} | {ret} | {outcome} | {reasoning} |".format(
                date=r["date"],
                action=r["action"],
                ticker=_short(r["ticker"], 28),
                name=_short(r["name"], 28),
                setup=_short(r["setup"], 28),
                status=_short(r["status"], 18),
                shares=_fmt_num(r["shares"]),
                price=_fmt_num(r["price"]),
                mark=_fmt_num(r["mark"]),
                ret=_fmt_pct(r["return"]),
                outcome=_short(r["outcome"], 72),
                reasoning=_short(r["reasoning"], 110),
            )
        )
    lines.append("")
    lines.append("Generated read-only by weekly_recap.py --paper-ledger; repo ledgers remain source of truth.")
    lines.append("")
    lines.append("不是买卖指令；研究信号，human executes.")
    return "\n".join(lines)


def build_recap(start, end, fund_dir=FUND_DIR, tracker_dir=HERE):
    """Pure function: ledgers -> markdown string. Read-only by construction."""
    fund = _load(os.path.join(fund_dir, "fund.json"), {})
    navh = _load(os.path.join(fund_dir, "nav_history.json"), [])
    orders = _load(os.path.join(fund_dir, "orders.json"), [])
    dlog = _load(os.path.join(fund_dir, "decision_log.json"), [])
    signals = _load(os.path.join(tracker_dir, "paper_signal_log.json"), [])
    nowcasts = _load(os.path.join(tracker_dir, "nowcast_log.json"), [])

    initial = fund.get("initial_capital", 1_000_000)
    week_nav = [n for n in navh if _in_window(n.get("date"), start, end)]
    last = week_nav[-1] if week_nav else (navh[-1] if navh else None)

    lines = [f"## Portfolio Snapshot(自动生成 · {start}–{end} · 非实盘指令)", ""]
    lines += ["| 项 | 值 | 证据 |", "|---|---:|---|"]
    if last:
        cum = last["nav"] / initial - 1
        week_ret = (week_nav[-1]["nav"] / week_nav[0]["nav"] - 1) if len(week_nav) > 1 else None
        lines.append(f"| NAV | ¥{last['nav']:,.0f}({last['date']}) | nav_history.json [validated against ledger] |")
        lines.append(f"| 周内变动 | {week_ret*100:+.2f}% | 同上 |" if week_ret is not None
                     else "| 周内变动 | 单日样本,不计 | 同上 |")
        lines.append(f"| 累计 | {cum*100:+.2f}% | 同上 |")
        lines.append(f"| 现金 | ¥{last.get('cash', 0):,.0f} | fund.json |")
    else:
        lines.append("| NAV | 无本周结算记录 | DATA_BLOCKED |")

    open_pos = [o for o in orders if o.get("status") == "filled"]
    pending = [o for o in orders if o.get("status") == "pending"]
    closed = [o for o in orders if o.get("status") == "closed"]
    for o in open_pos:
        lines.append(f"| 持仓 | {o.get('name')} {o.get('shares')}股 @{o.get('fill_price')}"
                     f"(fill {o.get('fill_date')}),stop {o.get('stop_reference')} | orders.json |")
    for o in pending:
        lines.append(f"| 挂单 | {o.get('name')} 触发线 {o.get('entry_review_price')},"
                     f"stop {o.get('stop_reference')} | orders.json |")
    lines.append(f"| closed trades | {len(closed)} | orders.json |")
    lines.append("")

    # blocked / discipline actions are first-class output
    week_actions = [d for d in dlog if _in_window(d.get("date"), start, end)]
    blocked = [d for d in week_actions
               if d.get("action") in ("CANCEL_ORDER", "NO_TRADE_DECISION", "RISK_REVIEW")]
    lines += ["### 本周被纪律挡下 / 风险复核的动作(必读)", ""]
    if blocked:
        for d in blocked:
            lines.append(f"- {d.get('date')} `{d.get('action')}` {d.get('ticker', '')} — "
                         f"{str(d.get('reason', d.get('note', '')))[:80]}")
    else:
        lines.append("- 本周无(0 条挡下记录本身也是信息)")
    lines.append("")

    # signal ledger summary
    week_sigs = [s for s in signals if _in_window(s.get("timestamp"), start, end)]
    lines += ["## 信号账本(自动生成)", ""]
    lines.append(f"- 正式信号累计 **{len(signals)} 条**,本周新增 {len(week_sigs)} 条"
                 f"(official_sample 本周 {sum(1 for s in week_sigs if s.get('official_sample'))} 条 · "
                 f"研究 pre-registration 本周 {sum(1 for s in week_sigs if not s.get('official_sample'))} 条)。")
    if len(closed) == 0:
        lines.append("- closed trades = 0 → **任何胜率 / expectancy 都不能谈**。")

    scored = [n for n in nowcasts if n.get("scored")]
    hits = [n for n in scored if n.get("flow_hit") is True]
    n = len(scored)
    claim = n >= MIN_SAMPLE_FOR_CLAIM
    rate = (len(hits) / n) if n else None
    lines.append(f"- nowcast 判分池:总 {len(nowcasts)} 条,已判 {n} 条,"
                 + (f"命中 {rate:.3f}" if rate is not None else "命中 n/a")
                 + f",claim_allowed={'true' if claim else 'false'}"
                 + ("" if claim else f"(<{MIN_SAMPLE_FOR_CLAIM},**只是计数,不是能力 claim**)") + "。")
    lines.append("")
    lines.append("Generated read-only by weekly_recap.py — 数字未经手抄。")
    lines.append("")
    lines.append("不是买卖指令；研究信号，human executes.")
    return "\n".join(lines)


# ------------------------------------------------------------------ selftest --
def selftest():
    import hashlib
    import tempfile
    ok = []

    def ck(name, cond):
        ok.append((name, bool(cond)))
        print(("  ✓ " if cond else "  ✗ ") + name)

    with tempfile.TemporaryDirectory() as td:
        fd = os.path.join(td, "model_fund")
        os.makedirs(fd)
        def w(rel, obj, base=td):
            with open(os.path.join(base, rel), "w") as fh:
                json.dump(obj, fh)
        w("model_fund/fund.json", {"initial_capital": 1_000_000, "cash": 706_720}, td)
        w("model_fund/nav_history.json", [
            {"date": "20260703", "nav": 1_000_000, "cash": 1_000_000},
            {"date": "20260708", "nav": 993_547, "cash": 847_720},
            {"date": "20260710", "nav": 995_845, "cash": 706_720}], td)
        w("model_fund/orders.json", [
            {"ticker": "600276.SH", "name": "恒瑞医药", "status": "filled",
             "fill_price": 56.4, "fill_date": "20260707", "stop_reference": 52.2,
             "shares": 2700, "registered_at": "20260706", "setup": "TREND_CONTINUATION",
             "reason": "创新药主线", "invalid_if": "出海订单证伪"},
            {"ticker": "002714.SZ", "name": "牧原股份", "status": "pending",
             "entry_review_price": 39.1, "stop_reference": 36.9, "shares": 0,
             "registered_at": "20260707", "setup": "TRIPLE_CONFIRM_BREAKOUT",
             "reason": "猪价反转", "invalid_if": "猪价回落"}], td)
        w("model_fund/decision_log.json", [
            {"date": "20260707", "action": "CANCEL_ORDER", "ticker": "603993.SH",
             "reason": "WARNING two-day rule"},
            {"date": "20260707", "action": "NO_TRADE_DECISION", "scope": "AI硬件",
             "reason": "sector distributing"},
            {"date": "20260620", "action": "CANCEL_ORDER", "ticker": "OLD.SH",
             "reason": "out of window"}], td)
        w("paper_signal_log.json", [
            {"signal_id": "a1", "timestamp": "20260708 close (official)",
             "official_sample": True},
            {"signal_id": "a2", "timestamp": "20260709 22:50",
             "official_sample": False, "ticker": "MARKET.A", "name": "A股大盘",
             "setup_type": "rotation_hypothesis", "outcome_status": "pending",
             "hypothesis": "churn persists", "invalidation": "two RISK_ON days"}], td)
        w("nowcast_log.json", [
            {"nowcast_id": "n1", "scored": True, "flow_hit": True},
            {"nowcast_id": "n2", "scored": True, "flow_hit": False},
            {"nowcast_id": "n3", "scored": False}], td)
        os.makedirs(os.path.join(td, "samples"))
        w("samples/20260710.json", {"timestamp": "20260710 close (official)",
                                    "ticker_gates": [{"ticker": "600276.SH", "price": 55.75}]}, td)

        md = build_recap("20260706", "20260710", fund_dir=fd, tracker_dir=td)
        ck("NAV row rendered from ledger", "¥995,845" in md and "20260710" in md)
        ck("week return computed inside window only", "+0.23%" in md)  # 993547->995845
        ck("open + pending both rendered", "恒瑞医药" in md and "牧原股份" in md)
        ck("closed=0 prohibition line printed", "任何胜率 / expectancy 都不能谈" in md)
        ck("blocked action inside window listed", "WARNING two-day rule" in md)
        ck("blocked action OUTSIDE window excluded", "OLD.SH" not in md)
        ck("nowcast rate carries claim_allowed=false + 计数 framing",
           "claim_allowed=false" in md and "只是计数" in md)
        ck("signal counts split official vs research",
           "official_sample 本周 1 条" in md and "pre-registration 本周 1 条" in md)
        ck("posture footer present", "不是买卖指令" in md)
        ledger = build_paper_ledger_review("20260706", "20260710", fund_dir=fd, tracker_dir=td)
        ck("paper ledger renders filled order with mark return",
           "PAPER_FILL" in ledger and "-1.15%" in ledger and "TREND_CONTINUATION" in ledger)
        ck("paper ledger includes blocked/no-trade action",
           "NO_TRADE_DECISION" in ledger and "sector distributing" in ledger)
        ck("paper ledger includes research pre-registration",
           "PRE_REGISTRATION" in ledger and "rotation_hypothesis" in ledger)

    # live read-only proof: bytes identical before/after
    paths = [os.path.join(FUND_DIR, x) for x in
             ("fund.json", "nav_history.json", "orders.json", "decision_log.json")] + \
            [os.path.join(HERE, "paper_signal_log.json"), os.path.join(HERE, "nowcast_log.json")]
    def digest():
        h = hashlib.md5()
        for p in paths:
            if os.path.exists(p):
                h.update(open(p, "rb").read())
        return h.hexdigest()
    before = digest()
    build_recap("20260706", "20260710")
    build_paper_ledger_review("20260706", "20260710")
    ck("live ledgers byte-identical after recap (read-only proof)", digest() == before)

    passed = sum(1 for _, c in ok if c)
    print(f"weekly_recap selftest: {passed}/{len(ok)}")
    return passed == len(ok)


def main():
    ap = argparse.ArgumentParser(description="read-only weekly recap generator")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--start", help="YYYYMMDD")
    ap.add_argument("--end", help="YYYYMMDD")
    ap.add_argument("--out", help="write markdown here (never a ledger path)")
    ap.add_argument("--paper-ledger", action="store_true",
                    help="emit Notion-friendly paper trading review table")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    if not (args.start and args.end):
        ap.print_help()
        return
    md = build_paper_ledger_review(args.start, args.end) if args.paper_ledger else build_recap(args.start, args.end)
    if args.out:
        if "model_fund" in args.out or args.out.endswith("_log.json"):
            print("refused: --out must never point at a ledger")
            sys.exit(1)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"written: {args.out}")
    else:
        print(md)


if __name__ == "__main__":
    main()
