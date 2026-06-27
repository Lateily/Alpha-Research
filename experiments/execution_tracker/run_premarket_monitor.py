#!/usr/bin/env python3
"""
run_premarket_monitor.py — P1.2 of MODEL_UPGRADE_TREE.

集合竞价 (09:15-09:25) + 开盘 30min (09:30-10:00) RISK OBSERVATION for the portfolio.
Reads INTRADAY realtime (Tushare SDK realtime_quote:sina via fund_source) — gap %,
高开低走 (gap-up then fade), intraday range, single-beta amplification — and classifies
the opening into one of:
  PREMARKET_RISK / OPENING_FADE / OPENING_CONFIRM / HIGH_REFLEXIVITY / NEUTRAL.

DISCIPLINE — OBSERVATION ONLY (the whole point of this layer):
  - Everything is `sample_eligible: false`. This NEVER appends to paper_signal_log or
    samples/. Intraday data lies for the statistical sample (利通 +3.72亿 mid-session vs
    −11.75亿 true close) — it is for risk-control observation, NOT win-rate sampling.
  - `no_trade_flag: true`. Posture / levels only, never an order.

Thresholds (GAP_RISK / GAP_AMPLIFY / RANGE_REFLEX) are [unvalidated intuition] until
calibrated against observed openings.

  python3 run_premarket_monitor.py --selftest   # offline unit test
  python3 run_premarket_monitor.py --run        # live intraday (needs TUSHARE_TOKEN)
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fund_source as fs   # noqa: E402

# [unvalidated intuition] thresholds
GAP_RISK = 0.02       # avg basket gap <= -2% + all-down -> PREMARKET_RISK
GAP_AMPLIFY = 0.02    # all-same-direction + |avg gap| >= 2% -> single-beta amplified
RANGE_REFLEX = 0.06   # intraday (high-low)/pre_close >= 6% -> reflexive tape
CONFIRM_GAP = 0.005   # avg gap must clear +0.5% to call OPENING_CONFIRM (else NEUTRAL)

PORTFOLIO = [("300502.SZ", "新易盛"), ("300475.SZ", "香农芯创"),
             ("603629.SH", "利通电子"), ("300308.SZ", "中际旭创")]
INDICES = [("000001.SH", "上证"), ("399006.SZ", "创业板")]


def read_quote(q):
    """Turn a normalized realtime row into an opening read. No look-ahead concern —
    intraday is observation-only and never sample-eligible."""
    price, pre, op = q.get("price"), q.get("pre_close"), q.get("open")
    hi, lo = q.get("high"), q.get("low")
    gap = (price / pre - 1) if (price and pre) else ((q.get("pct_chg") or 0) / 100.0)
    has_open = bool(op)
    gapped_up = bool(has_open and pre and op > pre)
    faded = bool(has_open and price is not None and price < op)         # came off the open
    recovered = bool(has_open and price is not None and price > op)
    rng = ((hi - lo) / pre) if (hi and lo and pre) else None
    return {
        "ticker": q.get("ticker"), "name": q.get("name"), "price": price,
        "gap": round(gap, 4),
        "open": op, "from_open": round(price / op - 1, 4) if (has_open and price) else None,
        "gapped_up": gapped_up, "faded": faded, "recovered": recovered,
        "intraday_range": round(rng, 4) if rng is not None else None,
        "sample_eligible": False,
    }


def classify(reads):
    gaps = [r["gap"] for r in reads]
    if not gaps:
        return {"state": "NO_DATA", "reason": "no quotes", "avg_gap": None,
                "single_beta_amplified": False, "high_reflexivity": False}
    avg_gap = sum(gaps) / len(gaps)
    all_down = all(g < 0 for g in gaps)
    all_up = all(g > 0 for g in gaps)
    single_beta = all_down or all_up
    amplified = single_beta and abs(avg_gap) >= GAP_AMPLIFY
    with_open = [r for r in reads if r["open"]]
    n_fade = sum(1 for r in with_open if r["gapped_up"] and r["faded"])
    n_reco = sum(1 for r in with_open if r["recovered"])
    big_range = any(r["intraday_range"] and r["intraday_range"] >= RANGE_REFLEX for r in reads)

    if all_down and avg_gap <= -GAP_RISK:
        state = "PREMARKET_RISK"
        reason = f"全篮子低开 avg {avg_gap:+.1%},单一beta向下"
    elif with_open and n_fade >= max(1, len(with_open) // 2):
        state = "OPENING_FADE"
        reason = f"{n_fade}/{len(with_open)} 高开低走"
    elif with_open and n_reco >= max(1, len(with_open) // 2) and avg_gap >= CONFIRM_GAP:
        state = "OPENING_CONFIRM"
        reason = f"{n_reco}/{len(with_open)} 守住开盘,avg {avg_gap:+.1%}"
    elif amplified or big_range:
        state = "HIGH_REFLEXIVITY"
        reason = " ".join(x for x in [("单一beta放大" if amplified else ""),
                                      ("振幅大" if big_range else "")] if x)
    else:
        state = "NEUTRAL"
        reason = f"avg gap {avg_gap:+.1%}"
    return {"state": state, "reason": reason, "avg_gap": round(avg_gap, 4),
            "single_beta_same_direction": single_beta,
            "single_beta_amplified": amplified,
            "high_reflexivity": state == "HIGH_REFLEXIVITY" or big_range or amplified}


def monitor(token, portfolio=PORTFOLIO, indices=INDICES, quote_fn=None):
    """Pull realtime, read, classify. Returns an OBSERVATION dict (never sample-eligible)."""
    quote_fn = quote_fn or (lambda tickers: fs.tushare_realtime_quotes(tickers, src="sina"))
    name_map = dict(portfolio)
    quotes = quote_fn([t for t, _ in portfolio])
    for q in quotes:
        if not q.get("name"):
            q["name"] = name_map.get(q.get("ticker"))
    reads = [read_quote(q) for q in quotes]
    idx_reads = []
    try:
        idx_reads = [read_quote(q) for q in quote_fn([t for t, _ in indices])]
    except Exception:                                          # noqa: BLE001
        pass
    cls = classify(reads)
    return {
        "layer": "P1.2_premarket_monitor",
        "sample_eligible": False, "no_trade_flag": True, "observation_only": True,
        "market_state": cls["state"], "reason": cls["reason"],
        "avg_portfolio_gap": cls["avg_gap"],
        "single_beta_amplified": cls["single_beta_amplified"],
        "high_reflexivity": cls["high_reflexivity"],
        "holdings": reads, "indices": idx_reads,
        "thresholds_note": "GAP_RISK/GAP_AMPLIFY/RANGE_REFLEX are [unvalidated intuition]",
    }


# ---------------------------------------------------------------- selftest ----
def _q(ticker, name, price, pre, op, hi, lo):
    return {"ticker": ticker, "name": name, "price": price, "pre_close": pre,
            "open": op, "high": hi, "low": lo, "pct_chg": round((price / pre - 1) * 100, 2),
            "sample_eligible": False}


def selftest():
    checks = []

    def ck(n, c):
        checks.append((n, bool(c)))

    # PREMARKET_RISK: whole basket gaps down ~-3%
    risk = [_q("A.SZ", "a", 97, 100, 97, 98, 96), _q("B.SZ", "b", 96, 100, 96, 97, 95)]
    c = classify([read_quote(x) for x in risk])
    ck("PREMARKET_RISK on all-down -3%", c["state"] == "PREMARKET_RISK")
    ck("PREMARKET_RISK flags single-beta amplified", c["single_beta_amplified"] is True)

    # OPENING_FADE: gapped up (open>pre) then faded (price<open)
    fade = [_q("A.SZ", "a", 102, 100, 106, 107, 101), _q("B.SZ", "b", 103, 100, 107, 108, 102)]
    c = classify([read_quote(x) for x in fade])
    ck("OPENING_FADE on 高开低走", c["state"] == "OPENING_FADE")

    # OPENING_CONFIRM: gapped up + held above open + positive avg
    conf = [_q("A.SZ", "a", 108, 100, 105, 109, 104), _q("B.SZ", "b", 106, 100, 104, 107, 103)]
    c = classify([read_quote(x) for x in conf])
    ck("OPENING_CONFIRM on held-open", c["state"] == "OPENING_CONFIRM")

    # HIGH_REFLEXIVITY: mixed direction (not single-beta) but a huge intraday range
    reflex = [_q("A.SZ", "a", 101, 100, 100, 108, 99), _q("B.SZ", "b", 99, 100, 100, 101, 92)]
    c = classify([read_quote(x) for x in reflex])
    ck("HIGH_REFLEXIVITY on big range", c["state"] == "HIGH_REFLEXIVITY")
    ck("high_reflexivity flag set", c["high_reflexivity"] is True)

    # NEUTRAL: tiny mixed gaps, small ranges
    neutral = [_q("A.SZ", "a", 100.3, 100, 100, 100.5, 99.8), _q("B.SZ", "b", 99.8, 100, 100, 100.2, 99.6)]
    c = classify([read_quote(x) for x in neutral])
    ck("NEUTRAL on tiny mixed", c["state"] == "NEUTRAL")

    # read_quote derives gap + 高开低走 + range correctly
    r = read_quote(_q("A.SZ", "a", 102, 100, 106, 107, 101))
    ck("gap +2%", abs(r["gap"] - 0.02) < 1e-9)
    ck("gapped_up True", r["gapped_up"] is True)
    ck("faded True (102<106)", r["faded"] is True)
    ck("intraday_range = 6%", abs(r["intraday_range"] - 0.06) < 1e-9)

    # OBSERVATION ONLY: monitor output never sample-eligible, never an order
    out = monitor(token=None, portfolio=[("A.SZ", "a"), ("B.SZ", "b")], indices=[],
                  quote_fn=lambda ts: [_q(t, t, 96, 100, 96, 97, 95) for t in ts])
    ck("monitor sample_eligible False", out["sample_eligible"] is False)
    ck("monitor no_trade_flag True", out["no_trade_flag"] is True)
    ck("every holding read sample_eligible False", all(h["sample_eligible"] is False for h in out["holdings"]))
    ck("monitor classifies PREMARKET_RISK", out["market_state"] == "PREMARKET_RISK")

    passed = sum(1 for _, ok in checks if ok)
    for n, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}")
    print(f"\nselftest: {passed}/{len(checks)} passed")
    return passed == len(checks)


def main():
    ap = argparse.ArgumentParser(description="P1.2 premarket/opening risk monitor (observation only)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", action="store_true", help="live intraday observation (needs TUSHARE_TOKEN)")
    ap.add_argument("--save", action="store_true", help="also write observations/<date>_<time>.json")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    if args.run:
        token = os.environ.get("TUSHARE_TOKEN", "").strip()
        if not token:
            print("NO TUSHARE_TOKEN — run `source ~/.zprofile` first"); sys.exit(1)
        obs = monitor(token)
        print(f"\n=== PREMARKET / OPENING OBSERVATION (sample_eligible=false) ===")
        print(f"state : {obs['market_state']} | {obs['reason']}")
        print(f"avg portfolio gap : {obs['avg_portfolio_gap']:+.2%} | single-beta amplified: {obs['single_beta_amplified']}")
        for h in obs["holdings"]:
            print(f"  {h['name']} 价{h['price']} gap{h['gap']:+.2%} "
                  f"{'高开低走' if h['gapped_up'] and h['faded'] else ('守开' if h['recovered'] else '')}")
        if args.save:
            t = (obs["holdings"][0].get("ticker") and "obs") or "obs"  # avoid Date.now in code
            obs_dir = os.path.join(HERE, "observations")
            os.makedirs(obs_dir, exist_ok=True)
            ts = (obs["holdings"][0] or {}).get("time") if obs["holdings"] else None
            fn = f"observation_{ts or 'latest'}.json".replace(":", "").replace(" ", "_")
            with open(os.path.join(obs_dir, fn), "w") as fh:
                json.dump(obs, fh, ensure_ascii=False, indent=2)
            print(f"saved observations/{fn} (NOT a sample)")
        print("不是买卖指令；研究信号，human executes。")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
