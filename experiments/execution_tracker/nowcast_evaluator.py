#!/usr/bin/env python3
"""
nowcast_evaluator.py — P4: post-close scoring of intraday main-force nowcasts.

The pair rule: a nowcast broadcaster without a scorer is exactly the unverifiable
thing this platform refuses to ship. Every nowcast logged by run_premarket_monitor
(--nowcast) is scored here after settle:

  1. FLOW SCORE — predicted_flow_dir vs the ACTUAL settle main flow
     (Tushare moneyflow_dc, the only truth). |main| < FLAT_EPS 亿 counts as flat
     and is excluded from hit-rate (too small to call a direction).
  2. NEXT-DAY RETURN — qfq close(T+1)/close(T) − 1 per nowcast state, filled only
     once T+1 has settled (no look-ahead; never retro-edited).

Aggregation: per-state hit rate + n, overall hit rate, avg next-day return by
state. NO accuracy claim below 30 scored nowcasts (claim_allowed=false).
Calibration reminder baked into the report: flow accuracy != return edge
(20260701 利通: settle confirmed +4.95亿 inflow; next day limit-down).

  python3 nowcast_evaluator.py --selftest        # offline, injected fetchers
  python3 nowcast_evaluator.py --score           # score unscored records (needs TUSHARE_TOKEN)
  python3 nowcast_evaluator.py --report          # aggregate only
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fund_source as fs                    # noqa: E402
import run_post_close_report as rpc         # noqa: E402

NOWCAST_LOG = os.path.join(HERE, "nowcast_log.json")
MIN_SCORED_FOR_CLAIM = 30
FLAT_EPS = 0.1        # |settle main| < 0.1亿 -> flat, excluded from hit-rate [unvalidated intuition]


def _settle_main(ticker, date, token):
    """Actual settle main flow (亿) via moneyflow_dc; None if not yet published."""
    try:
        f = fs.tushare_stock_fund(ticker, token, trade_date=date)
        return f.get("main") if f.get("date") == date else None
    except Exception:                                     # noqa: BLE001
        return None


def _next_day_return(ticker, date, token):
    """qfq close(T+1)/close(T) - 1; None until T+1 settles (no look-ahead)."""
    try:
        series = rpc.qfq_close_series(ticker, token, date)
        dates = [d for d, _ in series]
        if date not in dates:
            return None
        i = dates.index(date)
        if i + 1 >= len(series):
            return None
        return round(series[i + 1][1] / series[i][1] - 1.0, 4)
    except Exception:                                     # noqa: BLE001
        return None


def score_log(log, token, settle_fn=None, ret_fn=None):
    """Fill flow scores + next-day returns for unscored/unfilled records.
    Idempotent; state/features are NEVER retro-edited. Returns (n_flow, n_ret)."""
    settle_fn = settle_fn or (lambda t, d: _settle_main(t, d, token))
    ret_fn = ret_fn or (lambda t, d: _next_day_return(t, d, token))
    n_flow = n_ret = 0
    for rec in log:
        if rec.get("predicted_flow_dir") is None:          # DATA_INSUFFICIENT etc.
            continue
        if not rec.get("scored"):
            main = settle_fn(rec["ticker"], rec["date"])
            if main is not None:
                rec["actual_main_flow"] = round(main, 4)
                if abs(main) < FLAT_EPS:
                    rec["flow_hit"] = None                 # flat — direction uncallable
                else:
                    rec["flow_hit"] = (main > 0) == (rec["predicted_flow_dir"] > 0)
                rec["scored"] = True
                n_flow += 1
        if rec.get("scored") and "next_day_return" not in rec:
            r = ret_fn(rec["ticker"], rec["date"])
            if r is not None:
                rec["next_day_return"] = r
                n_ret += 1
    return n_flow, n_ret


def aggregate(log):
    """Per-state + overall hit rates, next-day return by state, <30 claim gate."""
    by_state = {}
    for rec in log:
        if not rec.get("scored"):
            continue
        s = by_state.setdefault(rec["state"], {"n": 0, "hits": 0, "flat": 0, "rets": []})
        if rec.get("flow_hit") is None:
            s["flat"] += 1
        else:
            s["n"] += 1
            s["hits"] += 1 if rec["flow_hit"] else 0
        if rec.get("next_day_return") is not None:
            s["rets"].append(rec["next_day_return"])
    out, total_n, total_hits = {}, 0, 0
    for state, s in sorted(by_state.items()):
        total_n += s["n"]; total_hits += s["hits"]
        out[state] = {
            "n_scored": s["n"], "n_flat": s["flat"],
            "flow_hit_rate": round(s["hits"] / s["n"], 3) if s["n"] else None,
            "avg_next_day_return": round(sum(s["rets"]) / len(s["rets"]), 4) if s["rets"] else None,
        }
    return {
        "by_state": out,
        "total_scored": total_n,
        "overall_flow_hit_rate": round(total_hits / total_n, 3) if total_n else None,
        "min_required": MIN_SCORED_FOR_CLAIM,
        "claim_allowed": total_n >= MIN_SCORED_FOR_CLAIM,
        "calibration_note": "flow accuracy != return edge (20260701 利通: settle +4.95亿 inflow -> next day limit-down)",
    }


# ---------------------------------------------------------------- selftest ----
def selftest():
    checks = []

    def ck(n, c):
        checks.append((n, bool(c)))

    log = [
        {"nowcast_id": "a", "ticker": "A.SZ", "date": "20260702", "state": "DISTRIBUTION_PROBABLE",
         "predicted_flow_dir": -1, "scored": False},
        {"nowcast_id": "b", "ticker": "B.SZ", "date": "20260702", "state": "ACCUMULATION_PROBABLE",
         "predicted_flow_dir": 1, "scored": False},
        {"nowcast_id": "c", "ticker": "C.SZ", "date": "20260702", "state": "RECLAIM_ATTEMPT",
         "predicted_flow_dir": 1, "scored": False},
        {"nowcast_id": "d", "ticker": "D.SZ", "date": "20260702", "state": "FAKE_STRENGTH",
         "predicted_flow_dir": -1, "scored": False},
        {"nowcast_id": "e", "ticker": "E.SZ", "date": "20260702", "state": "DATA_INSUFFICIENT",
         "predicted_flow_dir": None, "scored": False},
        {"nowcast_id": "f", "ticker": "F.SZ", "date": "20260702", "state": "OPENING_FADE",
         "predicted_flow_dir": -1, "scored": False},
    ]
    settle = {"A.SZ": -7.37, "B.SZ": 2.04, "C.SZ": -10.0, "D.SZ": -16.67, "F.SZ": 0.05}
    rets = {"A.SZ": -0.06, "B.SZ": 0.01, "C.SZ": -0.10, "D.SZ": -0.10, "F.SZ": 0.0}
    n_flow, n_ret = score_log(log, token=None,
                              settle_fn=lambda t, d: settle.get(t),
                              ret_fn=lambda t, d: rets.get(t))
    ck("scores all records with settle (5)", n_flow == 5)
    ck("DISTRIBUTION vs -7.37 = HIT", log[0]["flow_hit"] is True)
    ck("ACCUMULATION vs +2.04 = HIT", log[1]["flow_hit"] is True)
    ck("RECLAIM vs -10.0 = MISS", log[2]["flow_hit"] is False)
    ck("FAKE_STRENGTH vs -16.67 = HIT", log[3]["flow_hit"] is True)
    ck("DATA_INSUFFICIENT never scored", log[4].get("scored") is False)
    ck("flat |0.05|<0.1 -> flow_hit None (excluded)", log[5]["flow_hit"] is None)
    ck("next-day returns filled", n_ret == 5 and log[0]["next_day_return"] == -0.06)

    # idempotent: second pass fills nothing new, edits nothing
    before = json.dumps(log, sort_keys=True)
    n2, r2 = score_log(log, token=None, settle_fn=lambda t, d: settle.get(t),
                       ret_fn=lambda t, d: rets.get(t))
    ck("idempotent re-score = 0", n2 == 0 and r2 == 0)
    ck("no retro-edit on re-score", json.dumps(log, sort_keys=True) == before)

    # settle not yet published -> stays unscored (no look-ahead / no guess)
    pend = [{"nowcast_id": "p", "ticker": "P.SZ", "date": "20260703",
             "state": "OPENING_FADE", "predicted_flow_dir": -1, "scored": False}]
    score_log(pend, token=None, settle_fn=lambda t, d: None, ret_fn=lambda t, d: None)
    ck("unsettled stays unscored", pend[0]["scored"] is False)

    agg = aggregate(log)
    ck("aggregate counts 4 directional (flat excluded)", agg["total_scored"] == 4)
    ck("overall hit rate 3/4", agg["overall_flow_hit_rate"] == 0.75)
    ck("per-state present", agg["by_state"]["RECLAIM_ATTEMPT"]["flow_hit_rate"] == 0.0)
    ck("claim NOT allowed (<30)", agg["claim_allowed"] is False)
    ck("calibration note present", "return edge" in agg["calibration_note"])

    passed = sum(1 for _, okk in checks if okk)
    for n, okk in checks:
        print(f"  [{'PASS' if okk else 'FAIL'}] {n}")
    print(f"\nselftest: {passed}/{len(checks)} passed")
    return passed == len(checks)


def main():
    ap = argparse.ArgumentParser(description="P4 nowcast evaluator (post-close scoring)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--score", action="store_true", help="score unscored nowcasts (needs TUSHARE_TOKEN)")
    ap.add_argument("--report", action="store_true", help="print the aggregate only")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    if not os.path.exists(NOWCAST_LOG):
        print("no nowcast_log.json yet — run run_premarket_monitor.py --run --nowcast first")
        sys.exit(0)
    log = json.load(open(NOWCAST_LOG))
    if args.score:
        token = os.environ.get("TUSHARE_TOKEN", "").strip()
        if not token:
            print("NO TUSHARE_TOKEN — run `source ~/.zprofile` first"); sys.exit(1)
        n_flow, n_ret = score_log(log, token)
        with open(NOWCAST_LOG, "w") as fh:
            json.dump(log, fh, ensure_ascii=False, indent=2)
        print(f"scored {n_flow} flow / filled {n_ret} next-day returns")
    if args.score or args.report:
        print(json.dumps(aggregate(log), ensure_ascii=False, indent=2))
        print("不是买卖指令；研究信号，human executes。")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
