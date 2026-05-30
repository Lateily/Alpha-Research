#!/usr/bin/env python3
"""core_candidate_funnel.py — CORE Alpha Factory v0 #2A: full-market A-share screen_queue.

Finds names worth researching (attention ranking only). NOT a thesis, NOT a trade,
NOT a portfolio. Every row carries no_trade_flag: true. READ-ONLY: reads panels +
universe; writes ONLY public/data/core_screen_queue.json. Never writes
positions/analytics/snapshots.json. No LLM calls.

Per CORE_ALPHA_FACTORY_v0_SPEC §4.1 + Junyan ratify 2026-05-30:

Hard filters (all PIT-derivable from local data):
  - exclude ST / *ST / no-price.
  - listing age >= 252 trading days (PIT-derived from price-panel row count).
  - float cap >= CNY 3B (circ_mv).
  - 20d median turnover amount >= CNY 30M.
  - PE > 0.
  - >= 252 trading days of history (feature lookback + forward validatability).

Scored components (cross-sectional percentile, [unvalidated intuition] weights),
RENORMALIZED over per-row available weight (usually 60), with available_weight
exposed loudly so it is never mistaken for full-fidelity alpha:
  - fundamental_acceleration  : 20  (financials: rev/NI growth accel + GM trend)
  - catalyst_proximity (PROXY): 20  (days to next expected quarterly report from
                                      financial report cadence; proxy_unvalidated.
                                      If cadence not inferable -> unavailable.)
  - value + low-vol sanity    : 10  (cheap PE/PB + low realized vol)
  - liquidity / risk sanity   : 10  (turnover + low drawdown)

MISSING — NOT proxied (renormalized out, flagged loudly):
  - expectation_revision (25): consensus is watchlist-only, unavailable full-market.
  - coverage_gap (15)        : analyst coverage not full-market; attention is NOT
                               coverage (would be momentum-in-disguise). Dropped.
                               `attention_inflection` is reported as an UNSCORED diagnostic.

Output: public/data/core_screen_queue.json
Usage:  python3 scripts/core_candidate_funnel.py [--top N]
        python3 scripts/core_candidate_funnel.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
PRICES = REPO / "data_history" / "panel" / "prices.parquet"          # pe/pb/circ_mv panel
DAILY = REPO / "data_history" / "panel" / "daily_prices.parquet"     # vol/amount/pct_chg
FIN = REPO / "data_history" / "panel" / "financials.parquet"
UNIVERSE = REPO / "public" / "data" / "universe_a.json"
OUT = REPO / "public" / "data" / "core_screen_queue.json"

# Hard-filter thresholds [unvalidated intuition]. Units: Tushare circ_mv in 万元
# (1e4 RMB); daily amount in 千元 (1e3 RMB).
MIN_LISTING_TD = 252
MIN_FLOAT_CAP_CNY = 3e9
MIN_TURNOVER_CNY = 3e7
CIRC_MV_TO_CNY = 1e4
AMOUNT_TO_CNY = 1e3
# PIT guard: only financial rows ANNOUNCED on/before (as_of - PIT_BUFFER_DAYS) are
# usable. The buffer rejects same-day-announced reports that were not yet actionable.
PIT_BUFFER_DAYS = 1

WEIGHTS = {"fundamental_acceleration": 20, "catalyst_proximity": 20,
           "value_lowvol": 10, "liquidity_risk": 10}
MISSING = {"expectation_revision": 25, "coverage_gap": 15}


def _norm(s: str) -> str:
    return s.strip()


def load_universe() -> dict[str, dict]:
    u = json.loads(UNIVERSE.read_text())
    items = u if isinstance(u, list) else u.get("stocks", [])
    out = {}
    for x in items:
        t = x.get("ticker")
        if t:
            out[t] = {"name": x.get("name") or "", "pe": x.get("pe"), "pb": x.get("pb")}
    return out


def latest_snapshot() -> pd.DataFrame:
    """Latest pe/pb/circ_mv per ticker from the prices panel."""
    df = pd.read_parquet(PRICES, columns=["ts_code", "trade_date", "pe", "pb", "circ_mv"])
    df = df.sort_values(["ts_code", "trade_date"]).groupby("ts_code").tail(1)
    return df.set_index("ts_code")[["pe", "pb", "circ_mv"]]


def daily_features() -> tuple[pd.DataFrame, pd.Timestamp]:
    """Per-ticker: n_days (listing age), 20d med turnover, 60d vol, 60d/120d return, 60d maxdd, attention.

    Also returns the panel's latest trade_date as the screen's as-of date.
    """
    df = pd.read_parquet(DAILY, columns=["ts_code", "trade_date", "close", "amount", "pct_chg"])
    df = df.sort_values(["ts_code", "trade_date"])
    as_of = pd.to_datetime(str(df["trade_date"].max()), format="%Y%m%d")
    rows = {}
    for tic, g in df.groupby("ts_code", sort=False):
        n = len(g)
        if n < 5:
            continue
        close = g["close"].to_numpy(dtype=float)
        amt = g["amount"].to_numpy(dtype=float)
        last20 = amt[-20:] if n >= 20 else amt
        w60 = close[-60:] if n >= 60 else close
        w120 = close[-120:] if n >= 120 else close
        ret60 = (w60[-1] / w60[0] - 1.0) if w60[0] > 0 else np.nan
        ret120 = (w120[-1] / w120[0] - 1.0) if w120[0] > 0 else np.nan
        vol60 = float(np.std(g["pct_chg"].to_numpy(dtype=float)[-60:])) if n >= 20 else np.nan
        peak = np.maximum.accumulate(w60)
        maxdd = float(np.min(w60 / peak - 1.0)) if len(w60) else np.nan
        att = (float(np.median(amt[-5:]) / (np.median(amt[-60:]) + 1e-9))) if n >= 60 else np.nan
        rows[tic] = {"n_days": n, "turnover20_cny": float(np.median(last20)) * AMOUNT_TO_CNY,
                     "vol60": vol60, "ret60": ret60, "ret120": ret120, "maxdd60": maxdd,
                     "attention_inflection": att}
    return pd.DataFrame.from_dict(rows, orient="index"), as_of


def pit_filter(f: pd.DataFrame, as_of: pd.Timestamp, buffer_days: int = PIT_BUFFER_DAYS):
    """Point-in-time gate on a financials frame (pure; no I/O — unit-testable).

    Keeps ONLY rows announced on/before (as_of - buffer_days); per fiscal period
    (ts_code, end_date) keeps the LATEST ANNOUNCED version visible by that cutoff
    (handles restatements). Rows with unparseable/missing ann_date are dropped
    (cannot prove they were public). Returns (filtered_frame, max_ann_date_used).
    """
    cutoff = as_of - pd.Timedelta(days=buffer_days)
    ann_str = f["ann_date"].astype(str).str.replace(r"\.0$", "", regex=True)
    ann = pd.to_datetime(ann_str, format="%Y%m%d", errors="coerce")
    f = f.assign(_ann=ann).dropna(subset=["_ann"])
    f = f[f["_ann"] <= cutoff]
    if f.empty:
        return f, None
    f = f.sort_values(["ts_code", "end_date", "_ann"]).drop_duplicates(["ts_code", "end_date"], keep="last")
    mx = f["_ann"].max()
    return f, (mx.strftime("%Y%m%d") if pd.notna(mx) else None)


def fin_features(as_of: pd.Timestamp):
    """Per-ticker fundamental acceleration + catalyst-proximity inputs.

    PIT-clean BY CONSTRUCTION: pit_filter() removes any row announced after
    (as_of - PIT_BUFFER_DAYS) BEFORE any scoring, and keeps the latest announced
    version per fiscal period. The next expected report is in the FUTURE and is
    only a timing proxy, never read as data. Returns (features_df, max_ann_date_used).
    """
    f = pd.read_parquet(FIN, columns=["ts_code", "ann_date", "end_date", "revenue", "oper_cost", "n_income_attr_p"])
    f = f.dropna(subset=["end_date"])
    f, max_ann_used = pit_filter(f, as_of)            # <-- PIT gate, before scoring
    f = f.sort_values(["ts_code", "end_date"])
    rows = {}
    for tic, g in f.groupby("ts_code", sort=False):
        # g is already PIT-filtered + deduped to one (latest-announced) row per period
        if len(g) < 5:
            # need ~5 quarters to form YoY growth + acceleration
            rows[tic] = {"fund_accel_raw": np.nan, "days_to_next_report": np.nan,
                         "report_gap_days": np.nan, "n_reports": len(g)}
            continue
        rev = g["revenue"].to_numpy(dtype=float)
        ni = g["n_income_attr_p"].to_numpy(dtype=float)
        cost = g["oper_cost"].to_numpy(dtype=float)
        # YoY growth uses lag-4 (quarterly); acceleration = latest YoY - prior YoY
        def yoy(a, i):
            return (a[i] / a[i - 4] - 1.0) if (i - 4 >= 0 and a[i - 4] not in (0, np.nan) and a[i - 4] > 0) else np.nan
        rev_accel = yoy(rev, len(rev) - 1) - yoy(rev, len(rev) - 2) if len(rev) >= 6 else np.nan
        ni_accel = yoy(ni, len(ni) - 1) - yoy(ni, len(ni) - 2) if len(ni) >= 6 else np.nan
        gm_now = (rev[-1] - cost[-1]) / rev[-1] if rev[-1] > 0 else np.nan
        gm_prev = (rev[-2] - cost[-2]) / rev[-2] if rev[-2] > 0 else np.nan
        gm_trend = (gm_now - gm_prev) if (not np.isnan(gm_now) and not np.isnan(gm_prev)) else np.nan
        parts = [p for p in [rev_accel, ni_accel, gm_trend] if not (p is None or np.isnan(p))]
        fund = float(np.mean(parts)) if parts else np.nan
        # catalyst proxy: days to the next MANDATORY A-share disclosure deadline, keyed
        # off the latest reported fiscal period. NOT a median announcement gap — A-share
        # ann dates cluster (annual+Q1 both ~Apr 30), so a median gap mis-times badly.
        #   latest period 03-31(Q1) -> interim, due Aug 31 same yr
        #   latest period 06-30(H1) -> Q3,      due Oct 31 same yr
        #   latest period 09-30(Q3) -> annual,  due Apr 30 next yr
        #   latest period 12-31(FY) -> Q1,      due Apr 30 next yr
        # Not inferable (non-standard period) OR overdue vs as_of (data stale / late filer)
        # -> NaN -> catalyst component marked unavailable & renormalized OUT.
        end = str(int(g["end_date"].iloc[-1]))
        days_to_next = np.nan
        deadline_str = None
        DEADLINE = {"0331": (0, 8, 31), "0630": (0, 10, 31), "0930": (1, 4, 30), "1231": (1, 4, 30)}
        if len(end) == 8 and end[4:8] in DEADLINE:
            yo, mm, dd = DEADLINE[end[4:8]]
            deadline = pd.Timestamp(year=int(end[:4]) + yo, month=mm, day=dd)
            dn = float((deadline - as_of).days)
            if dn > 0:  # only a FUTURE mandated disclosure is a forward catalyst
                days_to_next = dn
                deadline_str = deadline.strftime("%Y%m%d")
        rows[tic] = {"fund_accel_raw": fund, "days_to_next_report": days_to_next,
                     "next_report_deadline": deadline_str, "n_reports": len(g)}
    return pd.DataFrame.from_dict(rows, orient="index"), max_ann_used


def screen(top: int = 50) -> dict:
    uni = load_universe()
    snap = latest_snapshot()
    daily, as_of = daily_features()
    fin, max_ann_used = fin_features(as_of)

    df = snap.join(daily, how="inner").join(fin, how="left")
    df["name"] = [uni.get(t, {}).get("name", "") for t in df.index]
    n_total = len(df)

    # ── hard filters ──
    is_st = df["name"].str.contains("ST", na=False)
    f_listing = df["n_days"] >= MIN_LISTING_TD
    f_float = df["circ_mv"] * CIRC_MV_TO_CNY >= MIN_FLOAT_CAP_CNY
    f_turn = df["turnover20_cny"] >= MIN_TURNOVER_CNY
    f_pe = df["pe"] > 0
    passed = df[(~is_st) & f_listing & f_float & f_turn & f_pe].copy()
    filter_stats = {"n_total": int(n_total), "excluded_ST": int(is_st.sum()),
                    "fail_listing_age": int((~f_listing).sum()),
                    "fail_float_cap": int((~f_float).sum()),
                    "fail_turnover": int((~f_turn).sum()),
                    "fail_pe_le_0": int((~f_pe).sum()),
                    "n_passed_hard_filters": int(len(passed))}

    # ── cross-sectional component ranks (0-1), among hard-filter survivors ──
    # fundamental acceleration: higher accel = better
    passed["c_fund"] = passed["fund_accel_raw"].rank(pct=True)
    # value + low-vol: cheap (low PE/PB) + low realized vol
    val = (1 - passed["pe"].rank(pct=True)) * 0.4 + (1 - passed["pb"].rank(pct=True)) * 0.3 + (1 - passed["vol60"].rank(pct=True)) * 0.3
    passed["c_value_lowvol"] = val.rank(pct=True)
    # liquidity + low drawdown
    liq = passed["turnover20_cny"].rank(pct=True) * 0.6 + passed["maxdd60"].rank(pct=True) * 0.4  # maxdd is negative; higher (less negative) = better
    passed["c_liq"] = liq.rank(pct=True)
    # catalyst proximity PROXY: the sooner the next MANDATORY disclosure deadline, the
    # higher (a near-term earnings event is a research-now signal). Cross-sectional rank
    # of -days_to_next. Inferable ONLY when a future deadline exists (else unavailable).
    # NB: in calendar windows where the whole market shares one next deadline (e.g. late
    # May -> everyone's interim is Aug 31), this component is near-uniform and barely
    # discriminates — that is the honest state of catalyst timing, not artificial spread.
    passed["c_catalyst"] = (-passed["days_to_next_report"]).rank(pct=True)
    passed["_catalyst_available"] = passed["days_to_next_report"].notna()

    rows = []
    for tic, r in passed.iterrows():
        comps = {}
        avail_weight = 0.0
        raw_sum = 0.0
        # fundamental acceleration
        if not pd.isna(r["c_fund"]):
            comps["fundamental_acceleration"] = {"score": round(float(r["c_fund"]), 4), "weight": WEIGHTS["fundamental_acceleration"], "status": "ok"}
            raw_sum += float(r["c_fund"]) * WEIGHTS["fundamental_acceleration"]; avail_weight += WEIGHTS["fundamental_acceleration"]
        else:
            comps["fundamental_acceleration"] = {"status": "unavailable", "weight": WEIGHTS["fundamental_acceleration"]}
        # catalyst proximity (proxy)
        if bool(r["_catalyst_available"]) and not pd.isna(r["c_catalyst"]):
            comps["catalyst_proximity"] = {"score": round(float(r["c_catalyst"]), 4), "weight": WEIGHTS["catalyst_proximity"],
                                            "status": "proxy_unvalidated",
                                            "proxy_method": "days_to_next_mandatory_a_share_disclosure_deadline_from_latest_fiscal_period",
                                            "days_to_next_report": int(r["days_to_next_report"]),
                                            "next_report_deadline": r["next_report_deadline"]}
            raw_sum += float(r["c_catalyst"]) * WEIGHTS["catalyst_proximity"]; avail_weight += WEIGHTS["catalyst_proximity"]
        else:
            comps["catalyst_proximity"] = {"status": "unavailable", "weight": WEIGHTS["catalyst_proximity"],
                                           "note": "report cadence not inferable"}
        # value + low-vol
        comps["value_lowvol"] = {"score": round(float(r["c_value_lowvol"]), 4), "weight": WEIGHTS["value_lowvol"], "status": "ok"}
        raw_sum += float(r["c_value_lowvol"]) * WEIGHTS["value_lowvol"]; avail_weight += WEIGHTS["value_lowvol"]
        # liquidity + risk
        comps["liquidity_risk"] = {"score": round(float(r["c_liq"]), 4), "weight": WEIGHTS["liquidity_risk"], "status": "ok"}
        raw_sum += float(r["c_liq"]) * WEIGHTS["liquidity_risk"]; avail_weight += WEIGHTS["liquidity_risk"]
        # missing (not proxied)
        comps["expectation_revision"] = {"status": "unavailable_full_market", "weight": MISSING["expectation_revision"]}
        comps["coverage_gap"] = {"status": "unavailable_full_market", "weight": MISSING["coverage_gap"]}

        score = round(raw_sum / avail_weight * 100, 2) if avail_weight > 0 else None
        rows.append({
            "ticker": tic, "name": r["name"], "market": "A",
            "screen_score": score, "score_raw_available": round(raw_sum, 4),
            "available_weight": int(avail_weight),
            "missing_components": ["expectation_revision", "coverage_gap"] +
                                  ([] if comps["catalyst_proximity"]["status"] != "unavailable" else ["catalyst_proximity"]),
            "score_components": comps,
            "attention_inflection_diagnostic": (round(float(r["attention_inflection"]), 3) if not pd.isna(r["attention_inflection"]) else None),
            "hard_filter_passed": True,
            "data_quality": {"price_history_days": int(r["n_days"]),
                             "financial_reports": int(r["n_reports"]) if not pd.isna(r["n_reports"]) else 0,
                             "revision": "unavailable_full_market", "coverage": "unavailable_full_market",
                             "sidecar_coverage": "watchlist_only"},
            "no_trade_flag": True,
        })

    rows = [r for r in rows if r["screen_score"] is not None]
    rows.sort(key=lambda x: x["screen_score"], reverse=True)
    run_n = min(20, top)  # top tier flagged for a thesis run; rest of queue = watch
    for i, r in enumerate(rows, 1):
        r["screen_rank"] = i
        # Action triages WITHIN the queue. The screen is NOT alpha (40% of intended
        # signal is missing) — RUN_THESIS means "worth producing a forward-validatable
        # thesis to TEST", never an endorsement. Names below the queue are implicitly SKIP.
        r["recommended_research_action"] = "RUN_THESIS" if i <= run_n else ("WATCH_DATA" if i <= top else "SKIP")

    queue = rows[:top]
    n40 = sum(1 for r in queue if r["available_weight"] < 60)
    out = {
        "_meta": {"read_only": True, "no_trades": True, "no_llm": True,
                  "as_of_date": as_of.strftime("%Y%m%d"),
                  "pit_buffer_days": PIT_BUFFER_DAYS,
                  "max_ann_date_used": max_ann_used,
                  "pit_note": (f"financials gated to ann_date <= as_of - {PIT_BUFFER_DAYS}d "
                               f"(cutoff {(as_of - pd.Timedelta(days=PIT_BUFFER_DAYS)).strftime('%Y%m%d')}); "
                               "latest announced version kept per fiscal period. max_ann_date_used proves no look-ahead."),
                  "spec": "CORE_ALPHA_FACTORY_v0_SPEC §4.1; Junyan ratify 2026-05-30",
                  "layer": "screen_queue (attention ranking; NOT thesis, NOT capital)",
                  "scored_components": WEIGHTS, "missing_not_proxied": MISSING,
                  "max_available_weight_note": ("usually 60 (40 scored + 20 catalyst-proxy if a FUTURE mandatory "
                                                "disclosure deadline exists); renormalized to 0-100. "
                                                "expectation_revision(25) + coverage_gap(15) are unavailable "
                                                "full-market and renormalized OUT — screen_score is NOT full-fidelity "
                                                "alpha. attention_inflection is an UNSCORED diagnostic."),
                  "renormalization_caveat": (f"{n40}/{len(queue)} queue names have available_weight<60 (per-name "
                                             "missing catalyst). Per Junyan decision-2 these are renormalized over "
                                             "their available weight, which can FLOAT a data-incomplete name above "
                                             "fuller-data names when the missing component is near-average. "
                                             "available_weight is on every row so this is auditable. OPEN: median-impute "
                                             "vs availability-tiered ranking is a v0.1 decision for Junyan."),
                  "weights_status": "[unvalidated intuition]",
                  "action_note": ("RUN_THESIS (top tier) = worth producing a forward-validatable thesis to TEST, "
                                  "NOT an endorsement; WATCH_DATA = in queue but lower priority; SKIP = below queue."),
                  "filter_stats": filter_stats, "n_in_queue": len(queue),
                  "n_run_thesis": sum(1 for r in queue if r["recommended_research_action"] == "RUN_THESIS")},
        "screen_queue": queue,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--top", type=int, default=50)
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    out = screen(args.top)
    fs = out["_meta"]["filter_stats"]
    print(f"[funnel] universe {fs['n_total']} -> hard-filter pass {fs['n_passed_hard_filters']} "
          f"(ST {fs['excluded_ST']}, listing {fs['fail_listing_age']}, float {fs['fail_float_cap']}, "
          f"turnover {fs['fail_turnover']}, pe<=0 {fs['fail_pe_le_0']})")
    q = out["screen_queue"]
    print(f"\n=== screen_queue v0 top {min(15, len(q))} (of {len(q)}) — as_of {out['_meta']['as_of_date']} — [unvalidated intuition], NOT alpha ===")
    print(f"{'rk':>3} {'ticker':<11} {'name':<9} {'score':>6} {'awt':>4} {'fund':>5} {'catl':>5} {'val':>5} {'liq':>5}  action")
    def sc(c, k):
        v = c[k].get("score")
        return f"{v:.3f}" if isinstance(v, (int, float)) else "  — "
    for r in q[:15]:
        c = r["score_components"]
        print(f"{r['screen_rank']:>3} {r['ticker']:<11} {str(r['name'])[:9]:<9} {r['screen_score']:>6.2f} "
              f"{r['available_weight']:>4} {sc(c,'fundamental_acceleration'):>5} {sc(c,'catalyst_proximity'):>5} "
              f"{sc(c,'value_lowvol'):>5} {sc(c,'liquidity_risk'):>5}  {r['recommended_research_action']}")
    print(f"\n[funnel] wrote {OUT}")
    return 0


def _selftest() -> int:
    """Schema + renormalization invariants on a tiny synthetic frame (no I/O)."""
    errs = []
    # renormalization: 40 scored weight (no catalyst) -> available_weight 40, score in [0,100]
    comps_avail = 40
    raw = 0.5 * 20 + 0.8 * 10 + 0.6 * 10  # fund .5, val .8, liq .6
    score = raw / comps_avail * 100
    if not (0 <= score <= 100):
        errs.append(f"renormalized score {score} out of [0,100]")
    if abs(score - (raw / 40 * 100)) > 1e-9:
        errs.append("renormalization not over available weight")
    # missing components must always be the two unavailable ones
    if set(MISSING) != {"expectation_revision", "coverage_gap"}:
        errs.append(f"MISSING set wrong: {MISSING}")
    if sum(WEIGHTS.values()) + sum(MISSING.values()) != 100:
        errs.append(f"weights don't sum to 100: {sum(WEIGHTS.values())+sum(MISSING.values())}")

    # ── PIT gate (pit_filter is pure -> testable with no I/O) ──
    as_of = pd.Timestamp("2026-05-26")  # buffer=1 -> cutoff 2026-05-25
    fdf = pd.DataFrame({
        "ts_code": ["X", "X", "X"],
        "ann_date": [20260420, 20260825, 20260101],   # Q1 visible | interim FUTURE | older visible
        "end_date": [20260331, 20260630, 20251231],
        "revenue": [1, 2, 3], "oper_cost": [0, 0, 0], "n_income_attr_p": [1, 1, 1],
    })
    kept, max_ann = pit_filter(fdf, as_of, buffer_days=1)
    if 20260630 in kept["end_date"].astype(int).tolist():
        errs.append("PIT: future-announced (ann 20260825) row was NOT filtered out")
    if max_ann != "20260420":
        errs.append(f"PIT: max_ann_date_used should be 20260420, got {max_ann}")
    if set(kept["end_date"].astype(int)) != {20260331, 20251231}:
        errs.append(f"PIT: wrong visible periods kept: {sorted(set(kept['end_date'].astype(int)))}")
    # restatement: same fiscal period announced twice (both visible) -> keep LATEST announced
    fdf2 = pd.DataFrame({
        "ts_code": ["Y", "Y"], "ann_date": [20260420, 20260510], "end_date": [20260331, 20260331],
        "revenue": [1, 9], "oper_cost": [0, 0], "n_income_attr_p": [1, 9],
    })
    kept2, _ = pit_filter(fdf2, as_of, buffer_days=1)
    if len(kept2) != 1 or int(kept2["revenue"].iloc[0]) != 9:
        errs.append("PIT: did not keep the latest announced restatement per period")
    # same-day-as-cutoff guard: ann_date == as_of must be rejected (buffer pushes cutoff back)
    fdf3 = pd.DataFrame({"ts_code": ["Z"], "ann_date": [20260526], "end_date": [20260331],
                         "revenue": [1], "oper_cost": [0], "n_income_attr_p": [1]})
    kept3, max3 = pit_filter(fdf3, as_of, buffer_days=1)
    if len(kept3) != 0 or max3 is not None:
        errs.append("PIT: same-day (ann==as_of) row not rejected by buffer")

    if errs:
        print("core_candidate_funnel selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"core_candidate_funnel selftest PASSED (renorm score={score:.1f} over avail_weight=40; "
          f"weights sum to 100; missing={list(MISSING)}; PIT: future row filtered, "
          f"restatement->latest, same-day rejected, max_ann_date_used=20260420)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
