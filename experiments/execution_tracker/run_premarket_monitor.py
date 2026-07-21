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
OVERNIGHT_ANCHOR = os.path.join(HERE, "overnight_anchor.json")


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
        "from_high": round(price / hi - 1, 4) if (hi and price) else None,
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


def load_overnight_anchor(path=OVERNIGHT_ANCHOR):
    """Read the premarket overseas beta frame if present. Missing data is an
    explicit frame, not a silent omission."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {"layer": "overnight_anchor_v0", "bias": "DATA_BLOCKED",
                "why": "overnight_anchor.json missing; run overnight_anchor.py or provide manual feed",
                "anchors": [], "data_blocked": ["overnight anchor frame missing"],
                "claim_allowed": False}


# ---------------------------------------------------------------- nowcast ----
# Intraday main-force NOWCAST (P3 of the output-contract initiative). A nowcast is
# a PREDICTION of the settle main-flow direction, never a statement of fact; every
# record is append-only, sample_eligible:false, and scored post-close by
# nowcast_evaluator.py against Tushare moneyflow_dc (P4). All thresholds
# [unvalidated intuition]. Calibration reminder: flow accuracy != return edge.
NOWCAST_LOG = os.path.join(HERE, "nowcast_log.json")
NOWCAST_PREDICTS = {          # state -> predicted settle main-flow direction
    "ACCUMULATION_PROBABLE": 1, "RECLAIM_ATTEMPT": 1,
    "DISTRIBUTION_PROBABLE": -1, "OPENING_FADE": -1, "FAKE_STRENGTH": -1,
}


def nowcast_from_read(r):
    """Map one intraday read -> (state, confidence) or None when no pattern fires.
    Priority order matters: data guard -> fake strength -> fades -> reclaim -> accum."""
    if r.get("price") is None or not r.get("open") or r.get("from_open") is None:
        return ("DATA_INSUFFICIENT", 0.0)
    gap, fo = r.get("gap") or 0.0, r["from_open"]
    fh = r.get("from_high")
    if gap >= 0.02 and fh is not None and fh <= -0.04:
        return ("FAKE_STRENGTH", min(0.9, 0.5 + abs(fh) * 5))      # up big but sold off the high
    if r.get("gapped_up") and r.get("faded") and fo <= -0.01:
        return ("OPENING_FADE", min(0.9, 0.5 + abs(fo) * 10))
    if gap <= -0.005 and fo <= -0.015:
        return ("DISTRIBUTION_PROBABLE", min(0.9, 0.5 + abs(fo) * 8))   # gap-down, still sinking
    if gap <= -0.01 and fo >= 0.015:
        return ("RECLAIM_ATTEMPT", min(0.9, 0.5 + fo * 8))         # gap-down being bought back
    if gap >= 0.005 and fo >= 0 and fh is not None and fh >= -0.015:
        return ("ACCUMULATION_PROBABLE", min(0.9, 0.5 + gap * 8))  # steady bid, near day high
    return None                                                     # quiet tape -> no nowcast


def log_nowcasts(reads, date, checkpoint, log_path=NOWCAST_LOG):
    """Append nowcasts for the given reads. Append-only + dedup on
    (ticker,date,checkpoint) — a record is NEVER retro-edited (no-lookahead DNA).
    Returns the list of newly appended records."""
    import hashlib
    log = json.load(open(log_path)) if os.path.exists(log_path) else []
    seen = {(x["ticker"], x["date"], x["checkpoint"]) for x in log}
    added = []
    for r in reads:
        nc = nowcast_from_read(r)
        if nc is None:
            continue
        state, conf = nc
        key = (r.get("ticker"), date, checkpoint)
        if key[0] is None or key in seen:
            continue
        rec = {
            "nowcast_id": hashlib.md5(f"{key[0]}|{date}|{checkpoint}|{state}".encode()).hexdigest()[:12],
            "ticker": r.get("ticker"), "name": r.get("name"),
            "date": date, "checkpoint": checkpoint,
            "state": state, "confidence": round(conf, 2),
            "predicted_flow_dir": NOWCAST_PREDICTS.get(state),   # None for DATA_INSUFFICIENT
            "features": {k: r.get(k) for k in ("gap", "from_open", "from_high", "intraday_range")},
            "sample_eligible": False, "no_trade_flag": True, "scored": False,
        }
        log.append(rec); seen.add(key); added.append(rec)
    with open(log_path, "w") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=2)
    return added


def is_market_open_now(token=None, now=None):
    """Trading-session guard. Incident (2026-06 weekend run): the monitor pulled
    STALE last-session quotes while the market was closed and classified them as
    HIGH_REFLEXIVITY. Never classify stale data — check session time + trade_cal.
    Returns (open: bool, reason: str)."""
    import datetime
    now = now or datetime.datetime.now()
    hm = now.strftime("%H%M")
    if not ("0910" <= hm <= "1505"):                     # auction 09:15 .. close 15:00, small slack
        return False, f"当前 {now.strftime('%H:%M')} 不在交易时段(09:10-15:05)"
    date = now.strftime("%Y%m%d")
    try:
        d = fs._tushare_call("trade_cal", token or os.environ.get("TUSHARE_TOKEN", ""),
                             {"exchange": "SSE", "start_date": date, "end_date": date},
                             "cal_date,is_open")
        items = d.get("items") or []
        if items and not items[0][1]:
            return False, f"{date} 非交易日(trade_cal)"
        return True, "open"
    except Exception:                                     # noqa: BLE001 — trade_cal unreachable
        if now.weekday() >= 5:
            return False, f"{date} 周末(trade_cal 不可达,按 weekday 判)"
        return True, "open(trade_cal 不可达,按 weekday 判)"


def monitor(token, portfolio=PORTFOLIO, indices=INDICES, quote_fn=None, market_open=None):
    """Pull realtime, read, classify. Returns an OBSERVATION dict (never sample-eligible)."""
    if market_open is None:
        market_open, why = is_market_open_now(token)
    else:
        why = "injected"
    if not market_open:
        return {"layer": "P1.2_premarket_monitor",
                "sample_eligible": False, "no_trade_flag": True, "observation_only": True,
                "market_state": "MARKET_CLOSED", "reason": why,
                "avg_portfolio_gap": None, "single_beta_amplified": False,
                "high_reflexivity": False, "holdings": [], "indices": [],
                "overnight_anchor": load_overnight_anchor(),
                "note": "闭市/非交易时段 — 拒绝对 stale 行情分类(--force 可覆盖)"}
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
        "overnight_anchor": load_overnight_anchor(),
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
                  quote_fn=lambda ts: [_q(t, t, 96, 100, 96, 97, 95) for t in ts],
                  market_open=True)                       # injected: keep selftest offline/deterministic
    ck("monitor sample_eligible False", out["sample_eligible"] is False)
    ck("monitor no_trade_flag True", out["no_trade_flag"] is True)
    ck("every holding read sample_eligible False", all(h["sample_eligible"] is False for h in out["holdings"]))
    ck("monitor classifies PREMARKET_RISK", out["market_state"] == "PREMARKET_RISK")
    ck("monitor carries overnight anchor frame", out["overnight_anchor"]["bias"] in
       ("DATA_BLOCKED", "OVERNIGHT_RISK_ON_BETA", "OVERNIGHT_RISK_OFF_BETA", "MIXED"))

    # MARKET_CLOSED guard (2026-06 weekend incident: stale quotes classified as
    # HIGH_REFLEXIVITY). Closed -> refuse to classify; no quote_fn ever called.
    closed = monitor(token=None, portfolio=[("A.SZ", "a")], indices=[],
                     quote_fn=lambda ts: (_ for _ in ()).throw(AssertionError("quote_fn must not be called when closed")),
                     market_open=False)
    ck("closed -> MARKET_CLOSED", closed["market_state"] == "MARKET_CLOSED")
    ck("closed -> no holdings classified", closed["holdings"] == [])
    ck("closed -> still sample_eligible False", closed["sample_eligible"] is False)
    ck("closed -> still carries overnight anchor", "overnight_anchor" in closed)
    import datetime as _dt
    ok_evening, why_evening = is_market_open_now(token="", now=_dt.datetime(2026, 7, 2, 20, 0))
    ck("20:00 -> closed (time window, offline)", ok_evening is False and "不在交易时段" in why_evening)
    ok_early, _ = is_market_open_now(token="", now=_dt.datetime(2026, 7, 2, 8, 0))
    ck("08:00 -> closed (time window, offline)", ok_early is False)

    # ---- nowcast layer (P3): state mapping + append-only log ----
    def _r(gap, fo, fh, gapped_up=False, faded=False):
        return {"ticker": "T.SZ", "name": "t", "price": 100.0, "open": 100.0,
                "gap": gap, "from_open": fo, "from_high": fh,
                "gapped_up": gapped_up, "faded": faded, "intraday_range": 0.03}
    ck("FAKE_STRENGTH (up big, sold off high)",
       nowcast_from_read(_r(0.03, -0.02, -0.05))[0] == "FAKE_STRENGTH")
    ck("OPENING_FADE", nowcast_from_read(_r(0.02, -0.02, -0.02, True, True))[0] == "OPENING_FADE")
    ck("DISTRIBUTION_PROBABLE (gap-down sinking)",
       nowcast_from_read(_r(-0.02, -0.02, -0.03))[0] == "DISTRIBUTION_PROBABLE")
    ck("RECLAIM_ATTEMPT (gap-down bought back)",
       nowcast_from_read(_r(-0.02, 0.02, -0.005))[0] == "RECLAIM_ATTEMPT")
    ck("ACCUMULATION_PROBABLE (steady bid near high)",
       nowcast_from_read(_r(0.015, 0.005, -0.01))[0] == "ACCUMULATION_PROBABLE")
    ck("quiet tape -> no nowcast", nowcast_from_read(_r(0.001, 0.0, -0.02)) is None)
    ck("missing open -> DATA_INSUFFICIENT",
       nowcast_from_read({"price": 1.0, "open": None, "from_open": None})[0] == "DATA_INSUFFICIENT")
    ck("direction map: fade predicts outflow", NOWCAST_PREDICTS["OPENING_FADE"] == -1)
    ck("direction map: reclaim predicts inflow", NOWCAST_PREDICTS["RECLAIM_ATTEMPT"] == 1)

    import tempfile
    tmp = tempfile.mktemp(suffix=".json")
    try:
        reads = [_r(-0.02, -0.02, -0.03), _r(0.001, 0.0, -0.02)]   # 1 signal + 1 quiet
        added = log_nowcasts(reads, "20260703", "1030", log_path=tmp)
        ck("log appends only pattern-firing reads", len(added) == 1)
        ck("logged record sample_eligible false", added[0]["sample_eligible"] is False)
        ck("logged record carries predicted dir", added[0]["predicted_flow_dir"] == -1)
        ck("logged record starts unscored", added[0]["scored"] is False)
        again = log_nowcasts(reads, "20260703", "1030", log_path=tmp)
        ck("dedup on (ticker,date,checkpoint)", len(again) == 0)
        ck("log persisted", len(json.load(open(tmp))) == 1)
    finally:
        os.path.exists(tmp) and os.remove(tmp)

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
    ap.add_argument("--force", action="store_true", help="override the MARKET_CLOSED guard (testing only)")
    ap.add_argument("--nowcast", action="store_true",
                    help="also log per-ticker main-force nowcasts (append-only, scored post-close)")
    ap.add_argument("--checkpoint", default=None, help="checkpoint label for the nowcast log, e.g. 1030")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    if args.run:
        token = os.environ.get("TUSHARE_TOKEN", "").strip()
        if not token:
            print("NO TUSHARE_TOKEN — run `source ~/.zprofile` first"); sys.exit(1)
        obs = monitor(token, market_open=True if args.force else None)
        print(f"\n=== PREMARKET / OPENING OBSERVATION (sample_eligible=false) ===")
        oa = obs.get("overnight_anchor") or {}
        print(f"overnight anchor : {oa.get('bias')} | {oa.get('why')}")
        print(f"state : {obs['market_state']} | {obs['reason']}")
        if obs["market_state"] == "MARKET_CLOSED":
            print(obs["note"]); print("不是买卖指令；研究信号，human executes。"); return
        if args.nowcast:
            import datetime
            now = datetime.datetime.now()
            cp = args.checkpoint or now.strftime("%H%M")
            added = log_nowcasts(obs["holdings"], now.strftime("%Y%m%d"), cp)
            print(f"nowcast: +{len(added)} logged @checkpoint {cp} (prediction-not-truth, scored post-close)")
            for a in added:
                print(f"  {a['name']}: {a['state']} conf{a['confidence']} predict_flow={'+' if a['predicted_flow_dir']==1 else '-' if a['predicted_flow_dir']==-1 else '?'}")
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
