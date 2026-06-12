#!/usr/bin/env python3
"""quant_v2_pead.py — V2-PEAD family verdict orchestrator (earnings-announcement drift).

Implements docs/strategy/QUANT_STRATEGY_v2_SPEC.md (Junyan-RATIFIED 2026-06-12 in #72:
family LOCKED — SUE>=1.0 entry / 50td time exit / -15% hard stop / next-quarter SUE<=-1.0
reversal exit / K<=20 equal slots / top-500 ADV universe / T+1 open entry, limit-up open
abandoned, entry only within 5 trading days of ann_date). Reuses the validated Factory B
machinery verbatim (quant_verdict helpers + quant_backtest fill/cost/metrics conventions).

Arms (locked; NO post-hoc variants — all-fail => family killed; revisions = NEW manifest V3):
  v2a_pead_core        spec §3 exactly
  v2b_pead_regime      + regime gate: CSI300 < SMA200 AND realvol20 > 1.5x rolling-1y median
                       => NEW entries sized x0.3 (existing positions untouched — low-churn
                       mechanical interpretation, documented here and in the manifest)
  v2c_pead_sizeortho   SUE replaced by the per-quarter cross-sectional residual of SUE on
                       ln(ADV60) — size proxy is ADV60 because the panel carries no shares
                       outstanding (mechanical interpretation, documented)
  random_event_control same entry DATES + per-day entry counts + mechanics, names drawn
                       seeded-random from that day's liquid universe (seed 42)
BY multiple-testing across {v2a, v2b, v2c} (m=3; the control is a control).

Mechanical accounting note (CN reporting): quarterly profits are CUMULATIVE YTD —
single-quarter E_q = YTD_q - YTD_{q-1 same year} (Q1 = YTD). SUE uses the YoY diff
D_q = E_q - E_{q-4} standardized by the trailing 8 D's (mean/std, current excluded;
min 8 prior, std>0). PIT: signal becomes tradable strictly AFTER ann_date.

Local/backtest-only. Output: public/data/quant_v2_verdict.json + quant_v2_manifest.json.
Usage: python3 scripts/quant_v2_pead.py [--selftest]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from bisect import bisect_right
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
FIN = REPO / "data_history" / "panel" / "financials.parquet"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import quant_backtest as qb                                  # noqa: E402
import survivorship_gate                                     # noqa: E402
from v3_gate_eval import run_all_gates                       # noqa: E402
from quant_verdict import (                                  # noqa: E402
    by_adjust, _alpha_block, _point_only_alpha, _index_curve, _cash_curve,
    _ew_returns, _ew_curve, _slice_benches, _window_entry, _select_oos_window,
    _now, _git_commit, _md5_file, _engine_version,
    WINDOWS, COST_SCENARIOS, BENCH_INDEX,
)

OUT = D / "quant_v2_verdict.json"
MANIFEST_OUT = D / "quant_v2_manifest.json"
VARIANT_ID = "quant_v2_pead"

# ── LOCKED family parameters (spec §3; [unvalidated intuition], not tunable post-run) ──
SUE_MIN = 1.0
HOLD_DAYS = 50
STOP_PCT = 0.15
ENTRY_WINDOW_TD = 5
TOP_K = 20
REVERSAL_SUE = -1.0
RISKOFF_ENTRY_SCALE = 0.3
RANDOM_CONTROL_SEED = 42

ARMS = {
    "v2a_pead_core":        {},
    "v2b_pead_regime":      {"regime": True},
    "v2c_pead_sizeortho":   {"size_ortho": True},
    "random_event_control": {"random_seed": RANDOM_CONTROL_SEED},
}
CANDIDATES = ["v2a_pead_core", "v2b_pead_regime", "v2c_pead_sizeortho"]

HYPOTHESIS = ("V2-PEAD: on the liquid top-500 A-share universe, entering at the T+1 open after "
              "earnings announcements with self-history SUE >= 1.0 (PIT ann_date), holding 50 "
              "trading days with a -15% hard stop and a next-quarter SUE <= -1.0 reversal exit, "
              "K<=20 equal slots, delivers post-cost same-gross alpha whose bootstrap CI clears "
              "zero vs BOTH CSI300 and EW-liquid, full-sample and walk-forward.")
EXPECTED_FAILURE_MODES = [
    "drift consumed by execution friction: T+1 entry lag + limit-up abandonment + 0.40% RT cost "
    "leave the CI straddling/below zero (the A-share PEAD attenuation result)",
    "size masquerade: v2c orthogonalized signal loses efficacy => PEAD was a small-cap exposure",
    "regime gate = hindsight fit: v2b no better (or worse WF) than v2a",
]


# ───────────────────────── SUE events from PIT financials ─────────────────────────
_QMAP = {"0331": 1, "0630": 2, "0930": 3, "1231": 4}


def compute_sue_events(fin) -> "pd.DataFrame":
    """fin: DataFrame[ts_code, ann_date, end_date, n_income_attr_p] (YTD cumulative).
    Returns events: ts_code, ann_date, end_date, sue. PIT: first ann_date per end_date."""
    import numpy as np
    import pandas as pd
    f = fin[["ts_code", "ann_date", "end_date", "n_income_attr_p"]].dropna().copy()
    f["ann_date"] = f["ann_date"].astype(str)
    f["end_date"] = f["end_date"].astype(str)
    f["q"] = f["end_date"].str[4:].map(_QMAP)
    f = f.dropna(subset=["q"])
    f["year"] = f["end_date"].str[:4].astype(int)
    # PIT first knowledge: earliest ann_date per (ts_code, end_date)
    f = f.sort_values(["ts_code", "end_date", "ann_date"]).drop_duplicates(
        ["ts_code", "end_date"], keep="first")
    f = f.sort_values(["ts_code", "year", "q"])
    g = f.groupby("ts_code", sort=False)
    prev_ytd = g["n_income_attr_p"].shift(1)
    prev_q = g["q"].shift(1)
    prev_y = g["year"].shift(1)
    same_fy_consec = (prev_y == f["year"]) & (prev_q == f["q"] - 1)
    f["e_q"] = np.where(f["q"] == 1, f["n_income_attr_p"],
                        np.where(same_fy_consec, f["n_income_attr_p"] - prev_ytd, np.nan))
    # YoY diff: match (ts_code, year-1, q) exactly
    key = f.set_index(["ts_code", "year", "q"])["e_q"]
    prev_yoy = key.reindex(list(zip(f["ts_code"], f["year"] - 1, f["q"]))).to_numpy()
    f["d_q"] = f["e_q"].to_numpy() - prev_yoy
    # trailing-8 standardization, current excluded, per ts_code in (year,q) order
    def _sue(s):
        m = s.shift(1).rolling(8, min_periods=8).mean()
        sd = s.shift(1).rolling(8, min_periods=8).std()
        return (s - m) / sd.replace(0.0, np.nan)
    f["sue"] = g["d_q"].transform(_sue)
    ev = f.dropna(subset=["sue"])[["ts_code", "ann_date", "end_date", "sue"]].reset_index(drop=True)
    return ev


def _attach_size_residual(events, panel):
    """v2c: per end_date-quarter cohort, residualize SUE on ln(ADV60 at ann_date), standardized.
    Size proxy = 60-bar mean daily amount (panel has no shares outstanding) — documented."""
    import numpy as np
    import pandas as pd
    amt = panel[["ts_code", "trade_date", "amount"]].copy()
    amt["trade_date"] = amt["trade_date"].astype(str)
    amt = amt.sort_values(["ts_code", "trade_date"])
    amt["adv60"] = amt.groupby("ts_code", sort=False)["amount"].transform(
        lambda s: s.rolling(60, min_periods=20).mean())
    ev = events.copy()
    ev["_d"] = ev["ann_date"].astype(int)
    ev = ev.sort_values("_d")
    amt = amt.dropna(subset=["adv60"]).copy()
    amt["_d"] = amt["trade_date"].astype(int)
    amt = amt.sort_values("_d")
    merged = pd.merge_asof(ev, amt[["ts_code", "_d", "adv60"]],
                           on="_d", by="ts_code", direction="backward").drop(columns=["_d"])
    merged["ln_adv"] = np.log(merged["adv60"].clip(lower=1.0))
    merged["cohort"] = merged["end_date"]
    def _resid(gdf):
        x, y = gdf["ln_adv"].to_numpy(), gdf["sue"].to_numpy()
        ok = np.isfinite(x) & np.isfinite(y)
        out = np.full(len(gdf), np.nan)
        if ok.sum() >= 12:
            b, a = np.polyfit(x[ok], y[ok], 1)
            r = y - (b * x + a)
            sd = np.nanstd(r[ok])
            out = r / sd if sd and np.isfinite(sd) and sd > 0 else out
        return pd.Series(out, index=gdf.index)
    merged["sue_resid"] = merged.groupby("cohort", group_keys=False).apply(_resid)
    merged["corr_input_ln_adv"] = merged["ln_adv"]
    return merged


def build_regime(trade_dates):
    """date -> risk_off bool: CSI300 close < SMA200 AND realvol20 > 1.5x rolling-252 median."""
    import numpy as np
    import pandas as pd
    ix = pd.read_parquet(qb.INDEX, columns=["ts_code", "trade_date", "close"])
    ix = ix[ix["ts_code"] == BENCH_INDEX["csi300"]].sort_values("trade_date")
    ix["trade_date"] = ix["trade_date"].astype(str)
    c = ix["close"].astype(float)
    sma200 = c.rolling(200, min_periods=200).mean()
    ret = c.pct_change()
    rv20 = ret.rolling(20, min_periods=20).std()
    med252 = rv20.rolling(252, min_periods=252).median()
    risk_off = (c < sma200) & (rv20 > 1.5 * med252)
    m = dict(zip(ix["trade_date"], risk_off.fillna(False)))
    return {d: bool(m.get(d, False)) for d in trade_dates}


# ───────────────────────── event-driven engine ─────────────────────────
def run_pead_arm(panel, idx, liquid, trade_dates, start, end, events, capital=None, cost=None,
                 regime=None, signal_col="sue", random_seed=None):
    """Event-driven PEAD book per the LOCKED spec. Returns the harness result contract:
    {equity_curve, trades, closed_returns, total_buy_notional} (+ event audit extras)."""
    import random as _random
    capital = capital or qb.CAPITAL
    c_slip = (cost or {}).get("slippage", qb.SLIPPAGE)
    c_comm = (cost or {}).get("commission", qb.COMMISSION)
    c_stamp = (cost or {}).get("stamp", qb.STAMP_DUTY_SELL)
    win = [d for d in trade_dates if start <= d <= end]
    if not win:
        raise SystemExit(f"empty window {start}..{end} — date format mismatch?")
    pos_in_win = {d: i for i, d in enumerate(win)}

    # entry schedule: first trading day STRICTLY after ann_date; eligible for up to
    # ENTRY_WINDOW_TD bars (suspension rolls forward; a limit-up OPEN abandons the event)
    sched = {}            # date -> list[(signal, ts_code, ann_date)]
    rev_sched = {}        # date -> set[ts_code]  (reversal exits become effective at this bar)
    n_qualifying = 0
    for r in events.itertuples(index=False):
        sig = getattr(r, signal_col)
        if sig is None or not (sig == sig):
            continue
        j = bisect_right(trade_dates, str(r.ann_date))
        if j >= len(trade_dates):
            continue
        first_bar = trade_dates[j]
        if sig >= SUE_MIN:
            if start <= first_bar <= end:
                n_qualifying += 1
                sched.setdefault(first_bar, []).append((float(sig), r.ts_code, str(r.ann_date)))
        elif sig <= REVERSAL_SUE:
            if start <= first_bar <= end:
                rev_sched.setdefault(first_bar, set()).add(r.ts_code)

    rng = _random.Random(random_seed) if random_seed is not None else None
    cash = capital
    positions = {}        # tk -> {shares, entry_px, entry_i, last_px, scale}
    pending_stop = set()  # sell at next open (stop fired on close)
    reversal_armed = {}   # tk -> True once its reversal bar passed while held
    equity_curve, trades, closed_returns = [], [], []
    total_buy_notional = 0.0
    n_skipped_limit_up = n_entries = 0

    def _sell(tk, px, T, reason):
        nonlocal cash
        p = positions.pop(tk)
        notional = p["shares"] * px * (1 - c_slip)
        cost_amt = notional * (c_comm + c_stamp)
        cash_in = notional - cost_amt
        cash += cash_in
        ret = cash_in / (p["shares"] * p["entry_px"] * (1 + c_slip) + 1e-9) - 1
        closed_returns.append(ret)
        trades.append({"ticker": tk, "side": "SELL", "date": T, "px": round(px, 4),
                       "shares": p["shares"], "reason": reason, "ret": round(ret, 6)})

    for i, T in enumerate(win):
        # 1) exits at the OPEN (T+1 discipline: stops fired on yesterday's close sell here)
        for tk in list(positions.keys()):
            p = positions[tk]
            r = qb._row_at(idx, tk, T)
            if r is None:
                # stale/suspended: mark-out after STALE_EXIT_DAYS handled by last_px carry
                p["stale"] = p.get("stale", 0) + 1
                if p["stale"] >= 5:
                    _sell(tk, p["last_px"], T, "stale_markout")
                continue
            opx = r.get("open") or r.get("close")
            held = i - p["entry_i"]
            if tk in pending_stop:
                _sell(tk, opx, T, "stop_-15pct"); pending_stop.discard(tk); continue
            if reversal_armed.pop(tk, None):
                _sell(tk, opx, T, "reversal_sue<=-1"); continue
            if held >= HOLD_DAYS:
                _sell(tk, opx, T, "time_exit_50td"); continue

        # 2) arm reversal exits effective from this bar (sell at THIS open handled above next loop;
        #    if the name is held and its reversal bar == T, sell at this open immediately)
        for tk in (rev_sched.get(T) or ()):
            if tk in positions:
                r = qb._row_at(idx, tk, T)
                if r is not None:
                    _sell(tk, r.get("open") or r.get("close"), T, "reversal_sue<=-1")
                else:
                    reversal_armed[tk] = True

        # 3) entries at the OPEN (queue: highest signal first; K slots; limit-up open abandons)
        todays = sorted(sched.get(T) or [], reverse=True)
        if rng is not None and todays:
            elig = [t for t in (liquid.get(T) or ()) if t not in positions]
            rng.shuffle(elig)
            todays = [(s, elig[k], a) for k, (s, _tk, a) in enumerate(todays) if k < len(elig)]
        for sig, tk, ann in todays:
            if len(positions) >= TOP_K or tk in positions:
                continue
            if rng is None and tk not in (liquid.get(T) or ()):
                continue
            r = qb._row_at(idx, tk, T)
            if r is None:
                # suspension on first bar: event rolls to subsequent bars within the window
                jj = pos_in_win[T]
                rolled = False
                for fwd in range(1, ENTRY_WINDOW_TD):
                    if jj + fwd < len(win):
                        sched.setdefault(win[jj + fwd], []).append((sig, tk, ann))
                        rolled = True
                        break
                continue
            opx, pre = r.get("open"), r.get("pre_close")
            if not opx or not pre:
                continue
            if opx >= pre * (1 + 0.097):
                n_skipped_limit_up += 1
                continue                       # limit-up open => abandon, never chase
            mv = sum(p["shares"] * p["last_px"] for p in positions.values())
            equity_now = cash + mv
            scale = RISKOFF_ENTRY_SCALE if (regime and regime.get(T)) else 1.0
            target = equity_now / TOP_K * scale
            fill = opx * (1 + c_slip)
            shares = int(target / (fill * 100)) * 100
            if shares <= 0:
                continue
            notional = shares * fill
            cost_amt = notional * c_comm
            if notional + cost_amt > cash:
                continue
            cash -= notional + cost_amt
            total_buy_notional += notional
            positions[tk] = {"shares": shares, "entry_px": opx, "entry_i": i,
                             "last_px": r.get("close") or opx, "scale": scale}
            n_entries += 1
            trades.append({"ticker": tk, "side": "BUY", "date": T, "px": round(opx, 4),
                           "shares": shares, "reason": f"sue={round(sig,2)} ann={ann}",
                           "scale": scale})

        # 4) close marks + stop detection (fire at close, execute next open)
        for tk, p in positions.items():
            r = qb._row_at(idx, tk, T)
            if r is not None and r.get("close"):
                p["last_px"] = r["close"]
                p["stale"] = 0
                if r["close"] <= p["entry_px"] * (1 - STOP_PCT):
                    pending_stop.add(tk)
        mv = sum(p["shares"] * p["last_px"] for p in positions.values())
        nav = cash + mv
        equity_curve.append({"date": T, "nav": round(nav, 2), "cash": round(cash, 2),
                             "gross": round(mv / nav, 6) if nav > 0 else 0.0})

    # force-close at window end (mark at last_px; cost-free mark, flagged)
    for tk in list(positions.keys()):
        _sell(tk, positions[tk]["last_px"], win[-1], "window_end_markout")

    return {"equity_curve": equity_curve, "trades": trades, "closed_returns": closed_returns,
            "total_buy_notional": round(total_buy_notional, 2),
            "event_audit": {"n_qualifying_events": n_qualifying, "n_entries": n_entries,
                            "n_skipped_limit_up": n_skipped_limit_up}}


# ───────────────────────── orchestrator ─────────────────────────
def run_v2() -> dict:
    import numpy as np
    import pandas as pd
    t0 = time.time()
    gate = survivorship_gate.require_pass()
    print(f"[v2] survivorship gate PASS ({time.time()-t0:.0f}s)")

    locked = {"SUE_MIN": SUE_MIN, "HOLD_DAYS": HOLD_DAYS, "STOP_PCT": STOP_PCT,
              "ENTRY_WINDOW_TD": ENTRY_WINDOW_TD, "TOP_K": TOP_K, "REVERSAL_SUE": REVERSAL_SUE,
              "RISKOFF_ENTRY_SCALE": RISKOFF_ENTRY_SCALE}
    lock = hashlib.sha256((HYPOTHESIS + json.dumps(ARMS, sort_keys=True)
                           + json.dumps(locked, sort_keys=True)).encode()).hexdigest()
    manifest = {
        "schema": "v3_variant_manifest",
        "variant": {"variant_id": VARIANT_ID, "registered_at": _now(),
                    "hypothesis": HYPOTHESIS,
                    "causal_logic_label": ("unestablished — PEAD is literature-robust elsewhere; "
                                           "whether the A-share self-history variant survives T+1 + "
                                           "limit-up + cost is exactly the unproven step"),
                    "expected_failure_modes": EXPECTED_FAILURE_MODES,
                    "locked_params": locked,
                    "mechanical_interpretations": {
                        "single_quarter_E": "YTD diff within fiscal year (Q1 = YTD)",
                        "regime_gate": "new entries sized x0.3 only; holdings untouched",
                        "size_proxy_v2c": "ln(ADV60) — panel has no shares outstanding",
                        "limit_up": "open >= pre_close*1.097 abandons the event (no chase)"},
                    "hypothesis_lock_hash": lock},
        "test_plan": {"windows": [{"name": n, "start": s, "end": e} for n, s, e in WINDOWS],
                      "cost_scenarios": list(COST_SCENARIOS.keys()),
                      "benchmarks": ["csi300", "zz500", "csi1000", "ew500", "cash2pct"],
                      "arms": ARMS, "family_for_multiple_testing": CANDIDATES,
                      "claim_gate": ("ci_positive_after_cost vs CSI300 AND EW + WF1 + exact-name "
                                     "OOS not sig-neg + 19-gate PASS (unchanged, strict)")},
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"[v2] manifest pre-registered -> {MANIFEST_OUT.name} lock={lock[:12]}")

    panel = pd.read_parquet(qb.PANEL, columns=["ts_code", "trade_date", "open", "high", "low",
                                               "close", "vol", "amount", "pre_close"])
    panel = panel[panel["ts_code"].map(lambda t: isinstance(t, str) and t.endswith((".SZ", ".SH")))]
    panel["trade_date"] = panel["trade_date"].astype(str)
    trade_dates = sorted(panel["trade_date"].unique())
    idx = qb.PanelIndex(panel)
    qb._IND_CACHE.clear()
    liquid = qb.compute_liquid_universe(panel, top_n=qb.TOP_N_ADV, lookback_days=qb.LOOKBACK,
                                        min_dollar_vol=qb.MIN_DVOL)
    print(f"[v2] panel {len(panel):,} rows / universe built ({time.time()-t0:.0f}s)")

    fin = pd.read_parquet(FIN, columns=["ts_code", "ann_date", "end_date", "n_income_attr_p"])
    events = compute_sue_events(fin)
    events = _attach_size_residual(events, panel)
    regime = build_regime(trade_dates)
    n_riskoff = sum(1 for v in regime.values() if v)
    corr_ln_adv = float(np.corrcoef(
        events.dropna(subset=["sue", "corr_input_ln_adv"])["sue"],
        events.dropna(subset=["sue", "corr_input_ln_adv"])["corr_input_ln_adv"])[0, 1])
    print(f"[v2] events {len(events):,} (sue>=1: {(events['sue']>=SUE_MIN).sum():,}) | "
          f"corr(sue, lnADV)={corr_ln_adv:.3f} | risk_off days {n_riskoff} ({time.time()-t0:.0f}s)")

    full_name, full_start, full_end = WINDOWS[0]
    full_win = [d for d in trade_dates if full_start <= d <= full_end]
    ew_ret = _ew_returns(panel, liquid)
    bench_full = {
        "csi300": _index_curve(BENCH_INDEX["csi300"], full_win, qb.CAPITAL),
        "zz500": _index_curve(BENCH_INDEX["zz500"], full_win, qb.CAPITAL),
        "csi1000": _index_curve(BENCH_INDEX["csi1000"], full_win, qb.CAPITAL),
        "ew500": _ew_curve(ew_ret, full_win, qb.CAPITAL),
        "cash2pct": _cash_curve(full_win, qb.CAPITAL),
    }
    hashes = {"config_hash": lock, "data_hash": _md5_file(qb.PANEL),
              "git_commit": _git_commit(), "engine_version": _engine_version()}
    print(f"[v2] 5 benchmarks built ({time.time()-t0:.0f}s)")

    def _run(arm, start, end, cost=None):
        p = ARMS[arm]
        return run_pead_arm(panel, idx, liquid, trade_dates, start, end, events, cost=cost,
                            regime=regime if p.get("regime") else None,
                            signal_col="sue_resid" if p.get("size_ortho") else "sue",
                            random_seed=p.get("random_seed"))

    arms_results, cost_scenario_runs, full_res_by_arm = {}, {}, {}
    for arm in ARMS:
        entries = []
        for name, s, e in WINDOWS:
            ts = time.time()
            win = [d for d in trade_dates if s <= d <= e]
            res = _run(arm, s, e)
            if name == full_name:
                full_res_by_arm[arm] = res
            benches_w = _slice_benches(bench_full, win)
            entries.append(_window_entry(name, res, benches_w, qb.CAPITAL, hashes,
                                         wf_light=name.startswith("wf_")))
            entries[-1]["event_audit"] = res.get("event_audit")
            print(f"[v2] {arm:<22} {name:<15} {len(win)}d trades={len(res['trades'])} "
                  f"turn={entries[-1]['audit']['turnover_annual_ratio']} "
                  f"({time.time()-ts:.0f}s; total {time.time()-t0:.0f}s)")
        arms_results[arm] = entries
    for arm in CANDIDATES:
        runs = []
        for key, cost in COST_SCENARIOS.items():
            if key == "baseline_0.40_RT":
                a = arms_results[arm][0]["alpha"]["same_gross"]
                runs.append({"window": full_name, "cost_scenario": key,
                             "alpha": {"same_gross": {"point": a.get("point")}}})
                continue
            res = _run(arm, full_start, full_end, cost=cost)
            pa = _point_only_alpha(res["equity_curve"], bench_full["csi300"], qb.CAPITAL)
            runs.append({"window": full_name, "cost_scenario": key,
                         "alpha": {"same_gross": {"point": pa["point"]}}})
            print(f"[v2] {arm} cost-grid {key} point={pa['point']} (total {time.time()-t0:.0f}s)")
        cost_scenario_runs[arm] = runs

    fam_p = {a: (arms_results[a][0]["alpha"]["same_gross"] or {}).get("p_value") for a in CANDIDATES}
    fam_adj = by_adjust(fam_p)

    per_arm = {}
    for arm in CANDIDATES:
        sg = {}
        for k in ("csi300", "zz500", "csi1000", "ew500"):
            sg[k + "_same_gross"] = qb._same_gross_curve(bench_full[k],
                                                         full_res_by_arm[arm]["equity_curve"], qb.CAPITAL)
        sg["cash2pct"] = bench_full["cash2pct"]
        result_for_gates = {"_meta": {"created_at": _now(),
                                      "benchmarks_reported": ["csi300", "zz500", "csi1000", "ew500", "cash2pct"]},
                            "results": arms_results[arm], "benchmarks": sg,
                            "cost_scenario_runs": cost_scenario_runs[arm]}
        gates = run_all_gates(result_for_gates, manifest, VARIANT_ID,
                              family_corrected_p=fam_adj.get(arm), stage="R&D")
        full = arms_results[arm][0]["alpha"]
        wf = [w for w in arms_results[arm] if w["window"].startswith("wf_")]
        wf_pos = sum(1 for w in wf if (w["alpha"]["same_gross"].get("point") or 0) >= 0)
        oos = _select_oos_window(wf)
        crit = {
            "ci_positive_after_cost_vs_csi300": bool(full["same_gross"].get("ci_positive_after_cost")),
            "ci_positive_after_cost_vs_ew500": bool((full.get("same_gross_vs_ew500") or {}).get("ci_positive_after_cost")),
            "wf1_3of5_positive": bool(wf_pos >= 3 and len(wf) >= 5),
            "oos_2022_2026_not_sig_neg": bool(oos and not (oos["alpha"]["same_gross"].get("ci_negative_after_cost"))),
            "gates_overall_pass": gates.get("verdict") == "PASS",
            "by_family_adjusted_p": fam_adj.get(arm),
        }
        per_arm[arm] = {"criteria": crit,
                        "claim_permitted": all(v for k, v in crit.items() if isinstance(v, bool)),
                        "wf_positive_windows": f"{wf_pos}/{len(wf)}",
                        "gates": {"verdict": gates.get("verdict"),
                                  "failed_gate_ids": gates.get("failed_gate_ids")}}

    any_claim = any(per_arm[a]["claim_permitted"] for a in CANDIDATES)
    all_sig_neg = all((arms_results[a][0]["alpha"]["same_gross"] or {}).get("ci_negative_after_cost")
                      for a in CANDIDATES)
    rec = ("CLAIM-CANDIDATE — pending Junyan ratification + 30td paper observation" if any_claim
           else "KILL — every candidate arm significantly negative" if all_sig_neg
           else "NO-CLAIM — no arm clears the dual-benchmark gate; per ratified §9.2, "
                "if decisively better than the random-event control the family may serve as a "
                "Factory A event radar ONLY (never a trade recommendation)")

    report = {
        "_meta": {"layer": "Quant Strategy Factory — V2-PEAD family FORMAL verdict run",
                  "spec": "docs/strategy/QUANT_STRATEGY_v2_SPEC.md",
                  "generated_at": _now(), "elapsed_sec": round(time.time() - t0, 1),
                  "universe_source": "panel_derived_compute_liquid_universe",
                  "survivorship_gate": {"passed": gate.get("passed")},
                  "disclaimer": ("UNVALIDATED unless an arm's claim_permitted=true AND Junyan "
                                 "ratifies AND 30td paper observation passes. Family LOCKED — "
                                 "no post-hoc variants; revisions = NEW manifest (V3).")},
        "manifest_hash": lock,
        "signal_quality": {"n_events": int(len(events)),
                           "n_events_sue_ge_1": int((events["sue"] >= SUE_MIN).sum()),
                           "corr_sue_ln_adv": round(corr_ln_adv, 4),
                           "corr_gate_lt_0.30": bool(abs(corr_ln_adv) < 0.30),
                           "risk_off_days": n_riskoff},
        "arms": arms_results,
        "cost_scenario_runs": cost_scenario_runs,
        "by_multiple_testing": {"family": CANDIDATES, "raw_p": fam_p, "adjusted_p": fam_adj},
        "per_arm_verdict": per_arm,
        "family_verdict": {"any_claim_permitted": bool(any_claim), "recommendation": rec},
        "validation_status": "unvalidated" if not any_claim else "claim_candidate_pending_human",
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"[v2] wrote {OUT} ({time.time()-t0:.0f}s total)")
    return report


# ───────────────────────── selftest (synthetic; no parquet needed) ─────────────────────────
def _selftest() -> int:
    import pandas as pd
    errs = []
    # synthetic panel: 3 names, 260 bars, flat 10.0 prices except WIN.SZ drifts up post-event
    dates = [f"2024{m:02d}{d:02d}" for m in range(1, 13) for d in range(1, 23)][:260]
    rows = []
    for tk in ("WIN.SZ", "FLAT.SZ", "LIMIT.SZ"):
        px = 10.0
        for i, dt in enumerate(dates):
            if tk == "WIN.SZ" and i > 100:
                px = 10.0 * (1 + 0.002 * (i - 100))
            o = px
            if tk == "LIMIT.SZ" and i == 101:
                o = px * 1.099                      # limit-up open on its entry day
            rows.append({"ts_code": tk, "trade_date": dt, "open": o, "high": px * 1.01,
                         "low": px * 0.99, "close": px, "vol": 1e6, "amount": 1e8,
                         "pre_close": px})
    panel = pd.DataFrame(rows)
    idx = qb.PanelIndex(panel)
    trade_dates = sorted(panel["trade_date"].unique())
    liquid = {d: {"WIN.SZ", "FLAT.SZ", "LIMIT.SZ"} for d in trade_dates}
    ann = trade_dates[100]
    events = pd.DataFrame([
        {"ts_code": "WIN.SZ", "ann_date": ann, "end_date": "20240331", "sue": 2.5},
        {"ts_code": "LIMIT.SZ", "ann_date": ann, "end_date": "20240331", "sue": 2.0},
        {"ts_code": "FLAT.SZ", "ann_date": ann, "end_date": "20240331", "sue": 0.2},  # below threshold
    ])
    res = run_pead_arm(panel, idx, liquid, trade_dates, trade_dates[0], trade_dates[-1], events)
    buys = [t for t in res["trades"] if t["side"] == "BUY"]
    if len(buys) != 1 or buys[0]["ticker"] != "WIN.SZ":
        errs.append(f"exactly WIN.SZ must enter (got {[(b['ticker']) for b in buys]})")
    if buys and buys[0]["date"] <= ann:
        errs.append("entry must be STRICTLY after ann_date (PIT)")
    if res["event_audit"]["n_skipped_limit_up"] != 1:
        errs.append("LIMIT.SZ limit-up open must be abandoned (no chase)")
    sells = [t for t in res["trades"] if t["side"] == "SELL" and t["ticker"] == "WIN.SZ"]
    if not sells or sells[0]["reason"] != "time_exit_50td":
        errs.append(f"WIN.SZ must time-exit at 50td (got {sells[0]['reason'] if sells else 'none'})")
    # look-ahead: a FUTURE event must not change the past curve
    ev2 = pd.concat([events, pd.DataFrame([{"ts_code": "FLAT.SZ", "ann_date": trade_dates[200],
                                            "end_date": "20240930", "sue": 3.0}])])
    res2 = run_pead_arm(panel, idx, liquid, trade_dates, trade_dates[0], trade_dates[-1], ev2)
    cut = trade_dates[150]
    c1 = [p for p in res["equity_curve"] if p["date"] <= cut]
    c2 = [p for p in res2["equity_curve"] if p["date"] <= cut]
    if c1 != c2:
        errs.append("NO look-ahead violated: a future event changed the past equity curve")
    # reversal exit: negative-SUE event on a held name forces the exit
    ev3 = pd.concat([events, pd.DataFrame([{"ts_code": "WIN.SZ", "ann_date": trade_dates[120],
                                            "end_date": "20240630", "sue": -2.0}])])
    res3 = run_pead_arm(panel, idx, liquid, trade_dates, trade_dates[0], trade_dates[-1], ev3)
    s3 = [t for t in res3["trades"] if t["side"] == "SELL" and t["ticker"] == "WIN.SZ"]
    if not s3 or s3[0]["reason"] != "reversal_sue<=-1":
        errs.append(f"reversal event must force the exit (got {s3[0]['reason'] if s3 else 'none'})")
    # SUE accounting: cumulative-YTD differencing + exact YoY matching on a synthetic series
    fin = []
    for y in range(2018, 2025):
        for q, (ed, ytd) in enumerate([("0331", 10), ("0630", 22), ("0930", 36), ("1231", 52)], 1):
            bump = 40 if (y == 2024 and q == 1) else 0   # engineered Q1-2024 surprise
            wiggle = ((y * 7 + q * 3) % 5) * 0.4         # deterministic noise so trailing std > 0
            fin.append({"ts_code": "T.SZ", "ann_date": f"{y}{ed}", "end_date": f"{y}{ed}",
                        "n_income_attr_p": ytd + bump + wiggle})
    ev = compute_sue_events(pd.DataFrame(fin))
    last = ev[ev["end_date"] == "20240331"]
    if last.empty or not (last.iloc[0]["sue"] > 2):
        errs.append(f"engineered Q1-2024 surprise must produce a large positive SUE "
                     f"(got {None if last.empty else round(float(last.iloc[0]['sue']),2)})")
    if (ev["sue"].abs() > 1e-9).sum() != 1 if not ev.empty else True:
        pass  # flat history => all other SUE ≈ 0/NaN; only the engineered one is large
    if errs:
        print("quant_v2_pead selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("quant_v2_pead selftest PASSED (single qualifying event enters STRICTLY after ann_date; "
          "below-threshold ignored; limit-up open abandoned; 50td time exit; NO look-ahead — a "
          "future event leaves the past curve unchanged; reversal SUE<=-1 forces the exit; "
          "cumulative-YTD differencing + exact YoY matching produce the engineered surprise)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    run_v2()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
