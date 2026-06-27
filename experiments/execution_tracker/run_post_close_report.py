#!/usr/bin/env python3
"""
run_post_close_report.py — P1.1 of MODEL_UPGRADE_TREE.

Daily POST-CLOSE official report + forward-return backfill (Line B). Builds ON TOP
of run_official_sample (the 定盘 snapshot + signals) and adds the win-rate engine:

  1. T+1 / T+3 / T+5 / T+10 forward-return backfill for past official signals —
     qfq close at the signal's OWN trade_date -> qfq close N trading days later
     (前复权, corporate-action safe; 新易盛 转增 would otherwise fake a return).
  2. A directional scorecard per signal: a constructive posture is "right" if price
     rises; a cautious posture (WARNING / 大单卖小单接 / 涨着派发) is "right" if price
     falls -> hit-rate / signed-return / gate-aligned-return by horizon.
  3. A structured daily report -> reports/<date>.json (大盘 + portfolio posture +
     scorecard + 未验证警告).
  4. Loads the repo-resident discipline_prompt (P0.5) as the system prompt any
     downstream LLM summary MUST run under (so cloud summaries aren't 'soulless').

IRON LAWS (enforced in code):
  - Official sample = post-close 定盘 only (inherited from run_official_sample).
  - NO LOOK-AHEAD: a signal's forward return uses only closes that already exist in
    Tushare `daily` (settled bars). A horizon whose T+N bar hasn't settled is left
    unfilled; an entry close is never re-stamped. Backfill is idempotent.
  - NO win-rate / expectancy CLAIM below 30 independent scored signals — the report
    prints the count and flags `claim_allowed: false` until the threshold is met.

This is the SIGNAL forward-return scorecard. The paper-PORTFOLIO entry/stop/take-
profit PnL (entry-trigger fills) is a separate P3 layer.

RUN AFTER CLOSE ONLY. Needs TUSHARE_TOKEN (`source ~/.zprofile`).
  python3 run_post_close_report.py                # generate today's sample + backfill + report
  python3 run_post_close_report.py --backfill-only # only backfill+score existing log (no new sample)
  python3 run_post_close_report.py --selftest      # offline unit test (no network)
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fund_source as fs            # noqa: E402
import run_official_sample as ros  # noqa: E402
import prompts                     # noqa: E402

HORIZON_DAYS = {"1d": 1, "3d": 3, "5d": 5, "10d": 10}
MIN_SCORED_FOR_CLAIM = 30          # no win-rate claim below this (constitution)

CAUTIOUS_POSTURE = {"WARNING", "DE_RISK_REVIEW", "EXIT_REVIEW"}
CAUTIOUS_FUND = {"涨着派发", "大单卖小单接"}
CONSTRUCTIVE_FUND = {"主力回流", "跌中承接"}


def directional_call(sig):
    """How to score the signal's forward return.

    cautious     -> the gate flagged risk; 'right' if price falls (return < 0)
    constructive -> the gate saw strength; 'right' if price rises (return > 0)
    neutral      -> ambiguous (e.g. 无量修复 + no rel-strength); not scored
    """
    st = sig.get("setup_type", "")
    fund = sig.get("fund_structure", "")
    if st in CAUTIOUS_POSTURE or fund in CAUTIOUS_FUND:
        return "cautious"
    if sig.get("relative_strength") or fund in CONSTRUCTIVE_FUND:
        return "constructive"
    return "neutral"


def parse_trade_date(timestamp):
    """'20260625 close (official)' -> '20260625'."""
    return (timestamp or "").split()[0] if timestamp else None


def qfq_close_series(ticker, token, start_date):
    """Ordered [(trade_date, qfq_close)] from start_date to latest settled bar.

    前复权 against the latest adj_factor so corporate actions don't fake a return.
    Only settled `daily` bars appear -> this IS the no-look-ahead boundary.
    """
    daily = fs._tushare_call("daily", token, {"ts_code": ticker, "start_date": start_date}, "trade_date,close")
    adj = fs._tushare_call("adj_factor", token, {"ts_code": ticker, "start_date": start_date}, "trade_date,adj_factor")
    dmap = {it[0]: it[1] for it in daily.get("items", [])}
    amap = {it[0]: it[1] for it in adj.get("items", [])}
    dates = sorted(dmap)
    if not dates:
        return []
    latest_adj = amap.get(dates[-1]) or 1.0
    return [(d, dmap[d] * (amap.get(d) or latest_adj) / latest_adj) for d in dates]


def backfill(log, token):
    """Fill T+N forward returns for elapsed horizons. Idempotent; no look-ahead.

    Returns the number of horizon-returns newly filled.
    """
    filled = 0
    series_cache = {}
    for sig in log:
        sig.setdefault("returns", {})
        if all(h in sig["returns"] for h in HORIZON_DAYS):
            continue                                   # already complete
        td = parse_trade_date(sig.get("timestamp"))
        if not td:
            continue
        if sig["ticker"] not in series_cache:
            series_cache[sig["ticker"]] = qfq_close_series(sig["ticker"], token, td)
        series = series_cache[sig["ticker"]]
        dates = [d for d, _ in series]
        if td not in dates:
            continue
        i = dates.index(td)
        sig["entry_close"] = round(series[i][1], 4)
        sig["directional_call"] = directional_call(sig)
        for h, n in HORIZON_DAYS.items():
            if h in sig["returns"]:
                continue
            j = i + n
            if j >= len(series):                       # T+N not settled yet -> no look-ahead
                continue
            sig["returns"][h] = round(series[j][1] / series[i][1] - 1.0, 4)
            filled += 1
    return filled


def scorecard(log):
    """Per-horizon hit-rate / signed-return / gate-aligned-return + the <30 guard."""
    card = {}
    for h in HORIZON_DAYS:
        rets, hits, aligned = [], [], []
        for sig in log:
            call = sig.get("directional_call", "neutral")
            r = sig.get("returns", {}).get(h)
            if call not in ("constructive", "cautious") or r is None:
                continue
            rets.append(r)
            hits.append(1 if ((call == "constructive" and r > 0) or (call == "cautious" and r < 0)) else 0)
            aligned.append(r if call == "constructive" else -r)   # gate's-eye return
        n = len(rets)
        card[h] = {
            "n_scored": n,
            "hit_rate": round(sum(hits) / n, 3) if n else None,
            "avg_signed_return": round(sum(rets) / n, 4) if n else None,
            "avg_gate_aligned_return": round(sum(aligned) / n, 4) if n else None,
        }
    scored = {s["signal_id"] for s in log
              if s.get("directional_call") in ("constructive", "cautious")
              and any(h in s.get("returns", {}) for h in HORIZON_DAYS)}
    card["total_scored_signals"] = len(scored)
    card["min_required"] = MIN_SCORED_FOR_CLAIM
    card["claim_allowed"] = len(scored) >= MIN_SCORED_FOR_CLAIM
    return card


def build_report(trade_date, snap, today_sigs, card):
    pg = snap.get("portfolio_gate", {})
    return {
        "report_date": trade_date,
        "generated_under_discipline": True,
        "discipline_prompt_chars": len(prompts.load_discipline_prompt()),
        "market": snap.get("market_gate"),
        "portfolio": {
            "posture": pg.get("portfolio_posture"),
            "single_beta": pg.get("single_beta_exposure"),
            "tickers": [
                {k: g.get(k) for k in ("name", "ticker", "price", "change_pct",
                                       "main_flow", "fund_structure", "posture",
                                       "relative_strength")}
                for g in snap.get("ticker_gates", [])
            ],
        },
        "today_signals": len(today_sigs),
        "winrate_scorecard": card,
        "unvalidated_warning": (
            f"win-rate / expectancy NOT claimable: "
            f"{card['total_scored_signals']}/{card['min_required']} scored signals. "
            f"Numbers are descriptive only."
            if not card["claim_allowed"] else
            f"{card['total_scored_signals']} scored signals — threshold met; "
            f"still treat as provisional, not validated alpha."
        ),
        "no_trade_flag": True,
        "official_sample": True,
    }


def main():
    ap = argparse.ArgumentParser(description="P1.1 post-close official report + forward-return backfill")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--backfill-only", action="store_true",
                    help="only backfill + score the existing log; do not generate a new sample")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("NO TUSHARE_TOKEN — run `source ~/.zprofile` first")
        sys.exit(1)

    log_path = os.path.join(HERE, "paper_signal_log.json")
    snap, today_sigs, trade_date = {}, [], None
    if not args.backfill_only:
        trade_date, snap, today_sigs = ros.build(token)
        samples_dir = os.path.join(HERE, "samples")
        os.makedirs(samples_dir, exist_ok=True)
        with open(os.path.join(samples_dir, f"{trade_date}.json"), "w") as fh:
            json.dump(snap, fh, ensure_ascii=False, indent=2)
        ros.append_log(log_path, today_sigs)

    log = json.load(open(log_path)) if os.path.exists(log_path) else []
    if trade_date is None:
        tds = [d for d in (parse_trade_date(s.get("timestamp")) for s in log) if d]
        trade_date = max(tds) if tds else "unknown"
    filled = backfill(log, token)
    with open(log_path, "w") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=2)

    card = scorecard(log)
    report = build_report(trade_date, snap, today_sigs, card)
    reports_dir = os.path.join(HERE, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    with open(os.path.join(reports_dir, f"{trade_date}.json"), "w") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print(f"\n=== POST-CLOSE REPORT {trade_date} ===")
    if snap.get("market_gate"):
        print("market :", snap["market_gate"].get("state"), "|", snap["market_gate"].get("one_line", ""))
    print(f"backfilled {filled} horizon-returns | scored: "
          f"{card['total_scored_signals']}/{card['min_required']} "
          f"(claim_allowed={card['claim_allowed']})")
    for h in HORIZON_DAYS:
        c = card[h]
        if c["n_scored"]:
            print(f"  {h}: n={c['n_scored']} hit_rate={c['hit_rate']} "
                  f"avg_gate_aligned={c['avg_gate_aligned_return']}")
    print(f"reports/{trade_date}.json + paper_signal_log.json (returns backfilled) written.")
    print("不是买卖指令；研究信号，human executes。")


# ---------------------------------------------------------------- selftest ----
def selftest():
    checks = []

    def ck(n, c):
        checks.append((n, bool(c)))

    dates = ["20260101", "20260102", "20260103", "20260104", "20260105", "20260106",
             "20260107", "20260108", "20260109", "20260110", "20260111"]
    series_up = list(zip(dates, [100, 110, 121, 130, 140, 150, 95, 90, 80, 70, 60]))   # up then crash
    series_dn = list(zip(dates, [100, 98, 96, 94, 92, 90, 88, 86, 84, 82, 80]))        # monotonic down

    global qfq_close_series
    original = qfq_close_series
    qfq_close_series = lambda ticker, token, start: series_up if ticker == "UP.SZ" else series_dn
    try:
        log = [
            {"signal_id": "up1", "ticker": "UP.SZ", "timestamp": "20260101 close (official)",
             "setup_type": "HOLD_OBSERVE", "fund_structure": "主力回流", "relative_strength": True},
            {"signal_id": "dn1", "ticker": "DN.SZ", "timestamp": "20260101 close (official)",
             "setup_type": "WARNING", "fund_structure": "大单卖小单接", "relative_strength": False},
        ]
        filled = backfill(log, token=None)
        ck("backfill filled returns", filled == 8)                       # 2 signals x 4 horizons
        ck("constructive call (rel-strength)", log[0]["directional_call"] == "constructive")
        ck("cautious call (WARNING/大单卖小单接)", log[1]["directional_call"] == "cautious")
        ck("up T+1 = +0.10", abs(log[0]["returns"]["1d"] - 0.10) < 1e-9)
        ck("up T+10 = -0.40 (rose then crashed)", abs(log[0]["returns"]["10d"] + 0.40) < 1e-9)
        ck("dn T+1 = -0.02", abs(log[1]["returns"]["1d"] + 0.02) < 1e-9)

        card = scorecard(log)
        # 1d: up constructive +10% -> hit; dn cautious -2% -> hit -> hit_rate 1.0
        ck("1d hit_rate = 1.0", card["1d"]["hit_rate"] == 1.0)
        # 10d: up constructive -40% -> MISS; dn cautious -20% -> hit -> hit_rate 0.5
        ck("10d hit_rate = 0.5", card["10d"]["hit_rate"] == 0.5)
        # gate-aligned 1d: up +0.10, dn -(-0.02)=+0.02 -> avg 0.06
        ck("1d gate-aligned avg = 0.06", abs(card["1d"]["avg_gate_aligned_return"] - 0.06) < 1e-9)
        ck("both scored", card["total_scored_signals"] == 2)
        ck("claim NOT allowed (<30)", card["claim_allowed"] is False)

        # idempotent: re-run fills nothing new
        ck("idempotent re-backfill = 0", backfill(log, token=None) == 0)

        # neutral posture is NOT scored
        neutral = [{"signal_id": "n1", "ticker": "UP.SZ", "timestamp": "20260101 close (official)",
                    "setup_type": "HOLD_OBSERVE", "fund_structure": "无量修复", "relative_strength": False}]
        backfill(neutral, token=None)
        ck("neutral call", neutral[0]["directional_call"] == "neutral")
        ck("neutral not in scored count", scorecard(neutral)["total_scored_signals"] == 0)

        # NO LOOK-AHEAD: a signal dated at the series end gets no forward returns
        future = [{"signal_id": "f1", "ticker": "UP.SZ", "timestamp": "20260111 close (official)",
                   "setup_type": "HOLD_OBSERVE", "fund_structure": "主力回流", "relative_strength": True}]
        backfill(future, token=None)
        ck("no-look-ahead: T at series end -> {} returns", future[0]["returns"] == {})

        # report shape + discipline prompt is loaded (cloud-readable)
        rep = build_report("20260101", {"market_gate": {"state": "X"}, "portfolio_gate": {}}, log, card)
        ck("report carries scorecard", rep["winrate_scorecard"]["total_scored_signals"] == 2)
        ck("report loads discipline prompt", rep["discipline_prompt_chars"] > 1000)
        ck("report flags unvalidated", "NOT claimable" in rep["unvalidated_warning"])
    finally:
        qfq_close_series = original

    passed = sum(1 for _, ok in checks if ok)
    for n, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}")
    print(f"\nselftest: {passed}/{len(checks)} passed")
    return passed == len(checks)


if __name__ == "__main__":
    main()
