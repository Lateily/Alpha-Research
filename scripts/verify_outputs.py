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
    # KR6: rdcf no longer emits `expectation_gap_score`. Canonical piecewise
    # score is in vp_snapshot.json[snapshots[].expectation_gap]; rdcf-side
    # range assertion dropped entirely (not replaced with "field absent" check).
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
          f"δ={delta:+.1%}  WACC={wacc:.1%}")


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
# NONE allowed because KR7 surfaces CLEAR alerts (auto-monitor active,
# threshold not breached) with severity NONE so the dashboard can show
# "✓ monitoring active" instead of silently dropping the row.
ALERT_SEVERITIES = {"HIGH", "MEDIUM", "LOW", "NONE"}
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
        clear_n     = sum(1 for a in alerts if a.get("status") == "CLEAR")
        wt_stat = stats.get("wrongif_triggered")
        wm_stat = stats.get("wrongif_manual")
        wc_stat = stats.get("wrongif_clear")
        if wt_stat != triggered_n:
            print(f"  {FAIL}  stats.wrongif_triggered={wt_stat} != counted TRIGGERED={triggered_n}")
        if wm_stat != manual_n:
            print(f"  {FAIL}  stats.wrongif_manual={wm_stat} != counted MANUAL={manual_n}")
        # wrongif_clear is optional (added in KR7); only check if present
        if wc_stat is not None and wc_stat != clear_n:
            print(f"  {FAIL}  stats.wrongif_clear={wc_stat} != counted CLEAR={clear_n}")
        clear_suffix = f" + {clear_n} CLEAR" if clear_n else ""
        print(f"  {OK}  wrongif alerts: {triggered_n} TRIGGERED + {manual_n} MANUAL{clear_suffix}")

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


# ── Fragility Scores (fragility_*.json) ────────────────────────────────────────
print("\n=== Fragility Scores (fragility_*.json) ===")
FRAG_BANDS = {"FRAGILE", "MODERATE", "ROBUST", "ANTIFRAGILE", "INSUFFICIENT_DATA"}
F2_METHODS = {"fcf_consistency", "cash_runway"}
for ticker in _watchlist_tickers():
    safe_id = ticker.replace(".", "_")
    path = DATA / f"fragility_{safe_id}.json"
    if not path.exists():
        print(f"  {WARN}  {ticker}: file missing (fragility_score.py not yet run for this ticker)")
        continue
    try:
        d = json.loads(path.read_text())
        composite = d.get("composite")
        band = d.get("band", "?")
        comps = d.get("components", {}) or {}
        f2_method = d.get("f2_method", "?")
        biotech = d.get("biotech_mode", False)

        problems = []
        if composite is not None and not (0 <= composite <= 100):
            problems.append(f"composite={composite} out of [0,100]")
        if band not in FRAG_BANDS:
            problems.append(f"band={band} not in enum")
        if f2_method not in F2_METHODS:
            problems.append(f"f2_method={f2_method} not in enum")
        # F6 concentration risk (KR1 this run): separate from composite,
        # MANUAL seed from watchlist.json. Optional — only validate shape if present.
        f6 = d.get("f6_concentration")
        if f6 is not None:
            if not isinstance(f6, dict):
                problems.append("f6_concentration not a dict")
            else:
                f6_score = f6.get("score")
                if f6_score is None or not (0 <= f6_score <= 100):
                    problems.append(f"f6_concentration.score={f6_score} out of [0,100]")
        # Math invariant: band must match composite range
        if isinstance(composite, (int, float)):
            if   composite >= 50: expected_band = "FRAGILE"
            elif composite >= 30: expected_band = "MODERATE"
            elif composite >= 15: expected_band = "ROBUST"
            else:                 expected_band = "ANTIFRAGILE"
            if band != expected_band:
                problems.append(f"band={band} disagrees with composite={composite} (expected {expected_band})")
        # Component sanity
        for k, v in comps.items():
            if v is not None and not (0 <= v <= 100):
                problems.append(f"{k}={v} out of [0,100]")

        icon = OK if not problems else WARN
        comp_str = ", ".join(f"{k.split('_',1)[0]}={v:.0f}" if v is not None else f"{k.split('_',1)[0]}=N/A"
                              for k, v in comps.items())
        biotech_tag = " [biotech]" if biotech else ""
        score_s = f"{composite:.1f}" if composite is not None else "N/A"
        warn_suffix = "  [" + "; ".join(problems) + "]" if problems else ""
        print(f"  {icon}  {ticker:12s}  composite={score_s:>5s}  band={band:<11s}  {comp_str}{biotech_tag}{warn_suffix}")
    except Exception as e:
        print(f"  {FAIL}  {ticker}: exception while validating: {e}")


# ── Persona Overlay (persona_overlay.json) ─────────────────────────────────────
# AHF-3 v1: deterministic Buffett/Burry/Damodaran checklists per ticker.
# Schema validation only — does not assert specific score values (those are
# [unvalidated intuition] and may shift as thresholds are re-calibrated).
print("\n=== Persona Overlay (persona_overlay.json) ===")
PERSONA_NAMES = ("buffett", "burry", "damodaran")  # tuple = stable order
PERSONA_MAX = {"buffett": 6, "burry": 4, "damodaran": 3}
PERSONA_LABEL = {"buffett": "Buf", "burry": "Bur", "damodaran": "Dam"}
KNOWN_ERR_CODES = {
    "fundamentals_missing", "rdcf_missing", "fin_data_missing",
    "market_data_stale", "market_data_missing",
}
# KR7: format hint per criterion. STRICT — required for fresh pipeline output.
# Dashboard has its own soft fallback to "ratio" for backward-compat with
# stale gh-pages JSON, but verify_outputs only validates the current run.
VALID_PERSONA_FORMATS = {"percent", "ratio", "absolute"}
po_path = DATA / "persona_overlay.json"
if not po_path.exists():
    print(f"  {WARN}  persona_overlay.json missing (persona_overlay.py not yet run)")
else:
    try:
        po = json.loads(po_path.read_text())
        personas_block = po.get("personas", {}) or {}
        wl = _watchlist_tickers()
        for ticker in wl:
            block = personas_block.get(ticker)
            if block is None:
                print(f"  {FAIL}  {ticker}: missing from persona_overlay.json")
                continue
            problems = []
            # Graceful-degradation case
            if "error" in block:
                err = block.get("error")
                if err not in KNOWN_ERR_CODES:
                    problems.append(f"unknown error code '{err}'")
                if block.get("scores") is not None:
                    problems.append("error block has non-null scores")
                icon = WARN if not problems else FAIL
                warn_suffix = "  [" + "; ".join(problems) + "]" if problems else ""
                print(f"  {icon}  {ticker:12s}  degraded ({err}){warn_suffix}")
                continue
            # Full-block validation
            line_parts = []
            for pname in PERSONA_NAMES:
                p = block.get(pname)
                if not isinstance(p, dict):
                    problems.append(f"{pname} not a dict")
                    continue
                score = p.get("score")
                pmax  = p.get("max")
                if pmax != PERSONA_MAX[pname]:
                    problems.append(f"{pname}.max={pmax} != {PERSONA_MAX[pname]}")
                if not isinstance(score, int) or not (0 <= score <= PERSONA_MAX[pname]):
                    problems.append(f"{pname}.score={score} out of [0,{PERSONA_MAX[pname]}]")
                criteria = p.get("criteria") or []
                if len(criteria) != PERSONA_MAX[pname]:
                    problems.append(f"{pname} criteria count {len(criteria)} != {PERSONA_MAX[pname]}")
                for c in criteria:
                    if not isinstance(c, dict) or "name" not in c or "passed" not in c:
                        problems.append(f"{pname} criterion shape invalid")
                        break
                    # KR7 STRICT format check — fresh pipeline output must
                    # include format field with valid value.
                    fmt = c.get("format")
                    if fmt is None:
                        problems.append(f"{pname} criterion '{c.get('name')}' missing format field")
                        break
                    if fmt not in VALID_PERSONA_FORMATS:
                        problems.append(f"{pname} criterion '{c.get('name')}' format='{fmt}' not in enum")
                        break
                line_parts.append(f"{PERSONA_LABEL[pname]}={score}/{PERSONA_MAX[pname]}")
            icon = OK if not problems else FAIL
            warn_suffix = "  [" + "; ".join(problems) + "]" if problems else ""
            print(f"  {icon}  {ticker:12s}  " + "  ".join(line_parts) + warn_suffix)
    except Exception as e:
        print(f"  {FAIL}  persona_overlay.json: exception while validating: {e}")


# ── EV/EBITDA Valuation (ev_ebitda_valuation.json) ─────────────────────────────
# AHF-2 Method 2: target-multiple comparison per ticker. Schema validation
# only — does not assert specific delta_pct values (those are
# [unvalidated intuition] and may shift as targets are re-calibrated).
print("\n=== EV/EBITDA Valuation (ev_ebitda_valuation.json) ===")
EV_VALID_SIGNALS = {"UNDERPRICED", "FAIRLY_VALUED", "OVERPRICED"}
EV_VALID_STATUS = {
    "multi_method", "biotech_fallback",
    "fundamentals_missing", "ebitda_missing", "ev_data_missing",
}
ev_path = DATA / "ev_ebitda_valuation.json"
if not ev_path.exists():
    print(f"  {WARN}  ev_ebitda_valuation.json missing (ev_ebitda_valuation.py not yet run)")
else:
    try:
        ev = json.loads(ev_path.read_text())
        ev_blocks = ev.get("tickers", {}) or {}
        wl = _watchlist_tickers()
        for ticker in wl:
            block = ev_blocks.get(ticker)
            if block is None:
                print(f"  {FAIL}  {ticker}: missing from ev_ebitda_valuation.json")
                continue
            problems = []
            status = block.get("model_status")
            if status not in EV_VALID_STATUS:
                problems.append(f"unknown model_status '{status}'")

            signal = block.get("signal")
            delta_pct = block.get("delta_pct")

            if status == "multi_method":
                if signal not in EV_VALID_SIGNALS:
                    problems.append(f"signal='{signal}' not in enum")
                if not isinstance(delta_pct, (int, float)):
                    problems.append(f"delta_pct={delta_pct} not numeric")
                elif not (-100 <= delta_pct <= 500):
                    problems.append(f"delta_pct={delta_pct} out of [-100, +500]")
            elif status == "biotech_fallback":
                if signal is not None:
                    problems.append(f"biotech_fallback should have signal=null, got '{signal}'")
                if delta_pct is not None:
                    problems.append(f"biotech_fallback should have delta_pct=null, got {delta_pct}")
            else:
                # degraded states (fundamentals_missing etc.)
                if signal is not None or delta_pct is not None:
                    problems.append(f"degraded state should have signal=null and delta_pct=null")

            icon = OK if not problems else FAIL
            warn_suffix = "  [" + "; ".join(problems) + "]" if problems else ""
            if status == "multi_method":
                line = f"signal={signal:<13s}  delta={delta_pct:+6.1f}%  current={block.get('current_ev_ebitda', 0):.2f}x"
            elif status == "biotech_fallback":
                line = f"biotech_fallback (current ev_ebitda={block.get('current_ev_ebitda', 0):.2f}x)"
            else:
                line = f"degraded ({status})"
            print(f"  {icon}  {ticker:12s}  {line}{warn_suffix}")
    except Exception as e:
        print(f"  {FAIL}  ev_ebitda_valuation.json: exception while validating: {e}")


# ── Residual Income Valuation (residual_income_valuation.json) ────────────────
# AHF-2 Method 3: Edwards-Bell-Ohlson book-value-regime valuation.
# Schema validation only — does not assert specific delta_pp values
# (those are [unvalidated intuition] and may shift as targets are
# re-calibrated).
print("\n=== Residual Income Valuation (residual_income_valuation.json) ===")
RI_VALID_SIGNALS = {"UNDERPRICED", "FAIRLY_VALUED", "OVERPRICED"}
RI_VALID_STATUS = {
    "multi_method", "biotech_fallback", "hyper_growth_ebo_unstable",
    "fundamentals_missing", "book_equity_missing", "negative_book_equity",
    "roe_missing", "market_cap_missing", "wacc_missing", "wacc_anomalous",
}
ri_path = DATA / "residual_income_valuation.json"
if not ri_path.exists():
    print(f"  {WARN}  residual_income_valuation.json missing (residual_income_valuation.py not yet run)")
else:
    try:
        ri = json.loads(ri_path.read_text())
        ri_blocks = ri.get("tickers", {}) or {}
        wl = _watchlist_tickers()
        for ticker in wl:
            block = ri_blocks.get(ticker)
            if block is None:
                print(f"  {FAIL}  {ticker}: missing from residual_income_valuation.json")
                continue
            problems = []
            status = block.get("model_status")
            if status not in RI_VALID_STATUS:
                problems.append(f"unknown model_status '{status}'")

            signal = block.get("signal")
            delta_pp = block.get("delta_pp")

            if status == "multi_method":
                if signal not in RI_VALID_SIGNALS:
                    problems.append(f"signal='{signal}' not in enum")
                if not isinstance(delta_pp, (int, float)):
                    problems.append(f"delta_pp={delta_pp} not numeric")
                elif not (-200 <= delta_pp <= 200):
                    problems.append(f"delta_pp={delta_pp} out of [-200, +200]pp")
            else:
                # All non-multi_method (biotech_fallback, hyper_growth, errors)
                if signal is not None or delta_pp is not None:
                    problems.append(f"degraded state '{status}' should have signal=null and delta_pp=null")

            icon = OK if not problems else FAIL
            warn_suffix = "  [" + "; ".join(problems) + "]" if problems else ""
            if status == "multi_method":
                line = (f"signal={signal:<13s}  delta={delta_pp:+6.1f}pp  "
                        f"P/B={block.get('p_b_observed', 0):.2f}  "
                        f"impROE={block.get('implied_future_roe_pct', 0):.1f}%  "
                        f"curROE={block.get('current_roe_pct', 0):.1f}%")
            elif status == "hyper_growth_ebo_unstable":
                line = f"hyper_growth_ebo_unstable (P/B={block.get('p_b_observed', 0):.2f})"
            elif status == "biotech_fallback":
                line = "biotech_fallback (no recurring earnings stream)"
            else:
                line = f"degraded ({status})"
            print(f"  {icon}  {ticker:12s}  {line}{warn_suffix}")
    except Exception as e:
        print(f"  {FAIL}  residual_income_valuation.json: exception while validating: {e}")


print("\n" + "="*60)
print("Tip: fields to use in rdcf JSON:")
print("  implied growth : implied_fcf_growth  (standard) / implied_rev_growth (biotech)")
print("  our estimate   : our_fcf_growth       (standard) / our_rev_growth      (biotech)")
print("  gap            : delta (float)  — canonical piecewise score in vp_snapshot.json[snapshots[].expectation_gap]")
print("  WACC           : wacc_detail.wacc")
print("  NO scipy needed: pure-Python bisection is built-in")
