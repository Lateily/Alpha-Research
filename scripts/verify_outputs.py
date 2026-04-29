#!/usr/bin/env python3
"""
Local output verification script — run after fetch_data.py to sanity-check
all generated JSON files.

Usage: python scripts/verify_outputs.py
"""

import json, sys
from pathlib import Path

DATA = Path("public/data")

OK   = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m⚠\033[0m"

def check(label, condition, msg=""):
    icon = OK if condition else FAIL
    print(f"  {icon}  {label}" + (f"  [{msg}]" if msg else ""))
    return condition


def _watchlist_tickers():
    p = DATA / "watchlist.json"
    if not p.exists():
        return []
    try:
        wl = json.loads(p.read_text())
        return list(wl.get("tickers", {}).keys())
    except Exception:
        return []


# ── RDCF ──────────────────────────────────────────────────────────────────────
print("\n=== Reverse DCF (rdcf_*.json) ===")
rdcf_tickers = ["300308_SZ", "700_HK", "9999_HK", "6160_HK", "002594_SZ"]
for safe_id in rdcf_tickers:
    path = DATA / f"rdcf_{safe_id}.json"
    if not path.exists():
        print(f"  {FAIL}  {safe_id}: FILE MISSING")
        continue
    d = json.loads(path.read_text())
    ticker = d.get("ticker", safe_id)
    err = d.get("error")
    if err:
        print(f"  {WARN}  {ticker}: error={err}")
        continue
    model = d.get("model_type", "?")
    signal = d.get("signal", "?")
    delta  = d.get("delta")
    score  = d.get("expectation_gap_score")
    wacc   = d.get("wacc_detail", {}).get("wacc")

    if model == "standard_fcf":
        impl  = d.get("implied_fcf_growth")
        our   = d.get("our_fcf_growth")
        g_label = "FCF"
    else:
        impl  = d.get("implied_rev_growth")
        our   = d.get("our_rev_growth")
        g_label = "Rev"

    print(f"  {OK}  {ticker:12s}  signal={signal:13s}  "
          f"implied {g_label}={impl:.1%}  our={our:.1%}  "
          f"δ={delta:+.1%}  gap={score:.0f}/100  WACC={wacc:.1%}")


# ── Stress test ────────────────────────────────────────────────────────────────
print("\n=== Stress Test (stress_test.json) ===")
st_path = DATA / "stress_test.json"
if st_path.exists():
    st = json.loads(st_path.read_text())
    worst   = st.get("worst_scenario", "?")
    exp_ret = st.get("expected_portfolio_return", 0)
    print(f"  {OK}  Expected portfolio return: {exp_ret:+.1%}")
    for k, v in st.get("scenarios", {}).items():
        ret = v["portfolio_return"]
        icon = "⬆" if ret > 0 else "⬇"
        print(f"       {icon} {k:22s}: {ret:+.1%}  (p={v['probability']:.0%})")
    print(f"       Worst case: {worst}")
else:
    print(f"  {FAIL}  stress_test.json missing")


# ── EQR ───────────────────────────────────────────────────────────────────────
print("\n=== EQR Ratings (eqr_*.json) ===")
eqr_ids = ["300308_SZ", "700_HK", "9999_HK", "6160_HK", "002594_SZ"]
for safe_id in eqr_ids:
    path = DATA / f"eqr_{safe_id}.json"
    if not path.exists():
        print(f"  {FAIL}  {safe_id}: FILE MISSING")
        continue
    d = json.loads(path.read_text())
    overall = d.get("overall", "?")
    gen_at  = d.get("generated_at", "")[:10]
    print(f"  {OK}  {d.get('ticker', safe_id):12s}  overall={overall:8s}  generated={gen_at}")


# ── Prediction log ─────────────────────────────────────────────────────────────
print("\n=== Prediction Log (prediction_log.json) ===")
pl_path = DATA / "prediction_log.json"
if pl_path.exists():
    pl = json.loads(pl_path.read_text())
    preds = pl.get("predictions", [])
    resolved = [p for p in preds if p["status"] in ("VERIFIED","FALSIFIED","INCONCLUSIVE")]
    open_p   = [p for p in preds if p["status"] == "OPEN"]
    if resolved:
        hits = sum(1 for p in resolved if p["status"] == "VERIFIED")
        rate = hits / len(resolved) * 100
        print(f"  {OK}  Hit rate: {hits}/{len(resolved)} = {rate:.0f}%")
    else:
        print(f"  {WARN}  No resolved predictions yet")
    for p in preds:
        icon = {"OPEN":"○","VERIFIED":OK,"FALSIFIED":FAIL,"INCONCLUSIVE":"?"}.get(p["status"],"?")
        print(f"       {icon}  {p['id']}  {p['ticker']:12s}  {p['status']:12s}  target={p['target_date']}")
else:
    print(f"  {FAIL}  prediction_log.json missing")


# ── Swing Signals (signals_*.json) ─────────────────────────────────────────────
print("\n=== Swing Signals (signals_*.json) ===")
SIGNAL_ZONES = {"OVERSOLD", "OVERBOUGHT", "BULLISH", "BEARISH", "NEUTRAL"}
for ticker in _watchlist_tickers():
    safe_id = ticker.replace(".", "_")
    path = DATA / f"signals_{safe_id}.json"
    if not path.exists():
        print(f"  {FAIL}  {ticker}: FILE MISSING")
        continue
    try:
        d = json.loads(path.read_text())
        rep_ticker = d.get("ticker", "?")
        zone       = d.get("zone", "?")
        signals    = d.get("signals", []) or []
        sc         = d.get("signal_count", {}) or {}
        ind        = d.get("indicators", {}) or {}
        rsi        = ind.get("rsi14")
        price      = d.get("price")

        problems = []
        if rep_ticker != ticker:
            problems.append(f"ticker mismatch ({rep_ticker})")
        if zone not in SIGNAL_ZONES:
            problems.append(f"zone={zone} not in enum")  # WARN-style
        for k in ("entry_zone", "exit_zone"):
            v = d.get(k)
            if not isinstance(v, bool):
                problems.append(f"{k}={v!r} not bool")
        if isinstance(sc.get("total"), int) and sc["total"] != len(signals):
            problems.append(f"signal_count.total={sc['total']} != len(signals)={len(signals)}")
        if rsi is not None and not (0 <= rsi <= 100):
            problems.append(f"rsi14={rsi} out of [0,100]")
        if price is None or price <= 0:
            problems.append(f"price={price} not > 0")

        icon = OK if not problems else WARN
        warn_suffix = "  [" + "; ".join(problems) + "]" if problems else ""
        rsi_str = f"{rsi:.0f}" if isinstance(rsi, (int, float)) else "—"
        price_str = f"{price:.2f}" if isinstance(price, (int, float)) else "—"
        print(f"  {icon}  {ticker:12s}  zone={zone:<10s}  signals={len(signals):>2d}  rsi={rsi_str:>4s}  px={price_str}{warn_suffix}")
    except Exception as e:
        print(f"  {FAIL}  {ticker}: exception while validating: {e}")


# ── Signal Confluence (confluence.json) ────────────────────────────────────────
print("\n=== Signal Confluence (confluence.json) ===")
CONF_ACTIONS = {"ENTRY_CANDIDATE", "HOLD", "NEUTRAL", "CAUTION", "EXIT_SIGNAL"}
cf_path = DATA / "confluence.json"
if not cf_path.exists():
    print(f"  {FAIL}  confluence.json missing")
else:
    try:
        cf = json.loads(cf_path.read_text())
        wl = _watchlist_tickers()
        ts = cf.get("tickers_scored")
        scores = cf.get("scores", []) or []
        summary = cf.get("summary", {}) or {}

        if ts != len(wl):
            print(f"  {FAIL}  tickers_scored={ts} != len(watchlist)={len(wl)}")
        else:
            print(f"  {OK}  tickers_scored={ts} matches watchlist")

        if len(scores) != ts:
            print(f"  {FAIL}  len(scores)={len(scores)} != tickers_scored={ts}")

        for k in ("entry_candidates", "exit_signals", "caution"):
            if k not in summary:
                print(f"  {WARN}  summary.{k} missing")

        for s in scores:
            tk = s.get("ticker", "?")
            sc = s.get("score")
            ac = s.get("action", "?")
            re_ = (s.get("rationale_e") or "").strip()
            rz_ = (s.get("rationale_z") or "").strip()

            problems = []
            if not isinstance(sc, (int, float)) or not (-100 <= sc <= 100):
                problems.append(f"score={sc} out of [-100,100]")
            if ac not in CONF_ACTIONS:
                problems.append(f"action={ac} not in enum")
            if not re_:
                problems.append("rationale_e empty")
            if not rz_:
                problems.append("rationale_z empty")
            icon = OK if not problems else WARN
            warn_suffix = "  [" + "; ".join(problems) + "]" if problems else ""
            sc_str = f"{sc:+d}" if isinstance(sc, int) else (f"{sc:+.1f}" if isinstance(sc, float) else "?")
            print(f"       {icon}  {tk:12s}  score={sc_str:>5s}  action={ac}{warn_suffix}")
    except Exception as e:
        print(f"  {FAIL}  exception while validating confluence.json: {e}")


# ── Daily Decision (daily_decision.json) ───────────────────────────────────────
print("\n=== Daily Decision (daily_decision.json) ===")
DEC_PRIORITIES   = {"LOW", "MEDIUM", "HIGH"}
ALERT_STATUSES   = {"TRIGGERED", "MANUAL", "CLEAR"}
ALERT_SEVERITIES = {"HIGH", "MEDIUM", "LOW"}
dd_path = DATA / "daily_decision.json"
if not dd_path.exists():
    print(f"  {FAIL}  daily_decision.json missing")
else:
    try:
        dd = json.loads(dd_path.read_text())
        decisions = dd.get("decisions", {}) or {}
        held  = decisions.get("held", []) or []
        watch = decisions.get("watchlist", []) or []
        alerts = dd.get("wrongif_alerts", []) or []
        stats = dd.get("stats", {}) or {}

        ph = stats.get("positions_held")
        if ph != len(held):
            print(f"  {FAIL}  stats.positions_held={ph} != len(decisions.held)={len(held)}")
        else:
            print(f"  {OK}  positions_held={ph} matches decisions.held; watchlist={len(watch)}")

        for d in held:
            tk = d.get("ticker", "?")
            pri = d.get("priority", "?")
            conf = d.get("confidence")
            problems = []
            if pri not in DEC_PRIORITIES:
                problems.append(f"priority={pri} not in enum")
            if conf is not None and not (0 <= conf <= 100):
                problems.append(f"confidence={conf} out of [0,100]")
            if problems:
                print(f"       {WARN}  {tk:12s}  " + "; ".join(problems))

        triggered_n = sum(1 for a in alerts if a.get("status") == "TRIGGERED")
        manual_n    = sum(1 for a in alerts if a.get("status") == "MANUAL")
        wt_stat = stats.get("wrongif_triggered")
        wm_stat = stats.get("wrongif_manual")
        if wt_stat != triggered_n:
            print(f"  {FAIL}  stats.wrongif_triggered={wt_stat} != counted TRIGGERED={triggered_n}")
        if wm_stat != manual_n:
            print(f"  {FAIL}  stats.wrongif_manual={wm_stat} != counted MANUAL={manual_n}")
        print(f"  {OK}  wrongif alerts: {triggered_n} TRIGGERED + {manual_n} MANUAL")

        for a in alerts:
            tk  = a.get("ticker", "?")
            st  = a.get("status", "?")
            sev = a.get("severity", "?")
            wif = (a.get("wrongIf_e") or "")[:80]
            problems = []
            if st not in ALERT_STATUSES:
                problems.append(f"status={st}")
            if sev not in ALERT_SEVERITIES:
                problems.append(f"severity={sev}")
            if st == "TRIGGERED":
                if a.get("actual") is None:
                    problems.append("triggered but actual=None")
                if a.get("threshold") is None:
                    problems.append("triggered but threshold=None")
            icon = "⚠" if problems else "·"
            warn_suffix = "  [" + "; ".join(problems) + "]" if problems else ""
            print(f"       {icon}  {tk:12s}  {st:9s}  {sev:6s}  {wif}{warn_suffix}")
    except Exception as e:
        print(f"  {FAIL}  exception while validating daily_decision.json: {e}")


# ── Leading Indicators (leading_indicators.json) ───────────────────────────────
print("\n=== Leading Indicators (leading_indicators.json) ===")
LI_SIGNALS    = {"STRONG_CAPEX_CYCLE", "MODERATE", "WEAKENING", "INSUFFICIENT_DATA"}
LI_RELEVANCE  = {"DIRECT", "INDIRECT", "NONE"}
LI_DIRECTION  = {"positive", "negative", "neutral"}
li_path = DATA / "leading_indicators.json"
if not li_path.exists():
    print(f"  {FAIL}  leading_indicators.json missing")
else:
    try:
        li = json.loads(li_path.read_text())
        score  = li.get("composite_score")
        signal = li.get("composite_signal", "?")
        impl   = li.get("stock_implications", {}) or {}

        problems = []
        if not isinstance(score, (int, float)) or not (0 <= score <= 100):
            problems.append(f"composite_score={score} out of [0,100]")
        if signal not in LI_SIGNALS:
            problems.append(f"composite_signal={signal} not in enum")
        # Math invariant: signal must match band
        if isinstance(score, (int, float)):
            if   score >= 70: expected = "STRONG_CAPEX_CYCLE"
            elif score >= 55: expected = "MODERATE"
            elif score >= 40: expected = "WEAKENING"
            else:             expected = "INSUFFICIENT_DATA"
            if signal != expected:
                problems.append(f"composite_signal={signal} disagrees with score={score} band (expected {expected})")
        icon = OK if not problems else FAIL
        score_str = f"{score:.1f}" if isinstance(score, (int, float)) else "?"
        print(f"  {icon}  composite={score_str}  signal={signal}" + ("  [" + "; ".join(problems) + "]" if problems else ""))

        wl = set(_watchlist_tickers())
        if not isinstance(impl, dict):
            print(f"  {FAIL}  stock_implications is not a dict (type={type(impl).__name__})")
        else:
            unknown = [tk for tk in impl.keys() if tk not in wl]
            if unknown:
                print(f"  {WARN}  stock_implications has tickers not in watchlist: {unknown}")
            for tk, info in impl.items():
                if not isinstance(info, dict):
                    print(f"       {FAIL}  {tk}: implication is not a dict")
                    continue
                rel = info.get("relevance", "?")
                dirn = info.get("direction")
                problems = []
                if rel not in LI_RELEVANCE:
                    problems.append(f"relevance={rel}")
                if dirn is not None and dirn not in LI_DIRECTION:
                    problems.append(f"direction={dirn}")
                icon = "·" if not problems else WARN
                warn_suffix = "  [" + "; ".join(problems) + "]" if problems else ""
                dirn_str = dirn if dirn is not None else "—"
                print(f"       {icon}  {tk:12s}  rel={rel:<8s}  dir={dirn_str}{warn_suffix}")
    except Exception as e:
        print(f"  {FAIL}  exception while validating leading_indicators.json: {e}")


print("\n" + "="*60)
print("Tip: fields to use in rdcf JSON:")
print("  implied growth : implied_fcf_growth  (standard) / implied_rev_growth (biotech)")
print("  our estimate   : our_fcf_growth       (standard) / our_rev_growth      (biotech)")
print("  gap            : delta (float), expectation_gap_score (0-100)")
print("  WACC           : wacc_detail.wacc")
print("  NO scipy needed: pure-Python bisection is built-in")
