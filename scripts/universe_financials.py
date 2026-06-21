#!/usr/bin/env python3
"""Clean TTM financial factors for the A-share universe (PE-TTM / ROE / OCF-NI / GM).

WHY THIS EXISTS
---------------
After PR #99 fixed momentum, the universe still carried two DIRTY factors that the
data-health gate flags:

  * ``pe`` — a provider valuation multiple, often single-quarter-annualised, NOT
    trailing-twelve-month. It makes cyclicals look "cheap" in a good quarter
    (东材 "PE 83" was really ~164x TTM). This is the single worst source of
    "假便宜" names in the whole-market screen.
  * ``quality`` — ranks ROE, but the universe has ~0% ROE coverage, so the factor
    collapses to a constant 50 (inert, contributes nothing).

This module computes the REAL signals market-wide and attaches them so
score_universe can rank clean value (PE-TTM) and clean quality (ROE-TTM):

  * ``pe_ttm_clean``      = market_cap / trailing-12-month net-income-attr-parent
  * ``roe_ttm``           = TTM net income / average equity              (percent)
  * ``ocf_to_ni``         = TTM operating cash flow / TTM net income  (earnings quality)
  * ``gross_margin_ttm``  = (TTM revenue - TTM operating cost) / TTM revenue (percent)

WHY IT IS LEAN (no per-name loop, no committed panel, ~8 calls)
---------------------------------------------------------------
Chinese statements are YTD-cumulative, so a TTM flow is a 3-point identity:

    TTM = latest_YTD + prior_full_year - prior_year_same_period_YTD     (Q1/Q2/Q3)
    TTM = latest_value                                                  (Q4 = full year)

Tushare's ``*_vip(period=...)`` endpoints return the whole market for one report
period in a single call, so the entire universe needs only the periods involved
in that identity: income+cashflow at {latest, prior_FY, prior_same} (3 each) and
balancesheet at {latest, prior_same} for average equity — ~8 calls total. No
426MB panel, no committed file, no new workflow step.

HONEST DEGRADATION (never a silent wrong number)
------------------------------------------------
- No token / import / API error -> ``({}, basis='unavailable')``; the caller keeps
  the provider ``pe`` and the inert quality, the data-health gate keeps warning.
- A name missing any leg of its TTM identity -> that ratio is simply absent and is
  neutral-filled downstream (NOT a fabricated number, NOT a penalising rank).
- PIT-safe: only statement rows with ``ann_date <= as_of`` are used.
- pe_ttm_clean is None when TTM net income <= 0 (a negative-earnings PE is
  meaningless); such names are neutral-filled in the value factor, not shown cheap.

VALIDATION
----------
The TTM-from-cumulative identity and the four ratio formulae are standard and
``[validated against the issuer-filing reconciliation used in deep theses]``. The
~50-day reporting-lag deadlines used to pick the latest reported quarter are an
``[unvalidated intuition]`` operational prior (regulatory deadlines: Q1 0430 /
H1 0831 / Q3 1031 / FY 0430-next-year); per-run cost is unmeasured until Actions.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime

TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")

INCOME_FIELDS = "ts_code,ann_date,end_date,revenue,oper_cost,n_income_attr_p"
CASHFLOW_FIELDS = "ts_code,ann_date,end_date,n_cashflow_act"
BALANCE_FIELDS = "ts_code,ann_date,end_date,total_hldr_eqy_exc_min_int"

# A name needs at least this fraction of the universe carrying a ratio before the
# caller treats that factor as clean (mirrors score_universe's own threshold).
MIN_COVERAGE_FRAC = 0.30


def _f(v):
    try:
        if v is None:
            return None
        v = float(v)
        return None if v != v else v   # drop NaN
    except (TypeError, ValueError):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Pure computation (no network — fully unit-testable)
# ──────────────────────────────────────────────────────────────────────────────
def quarter_of(period):
    """1/2/3/4 from a YYYYMMDD period end-date string (0331→1 … 1231→4)."""
    mmdd = str(period)[4:8]
    return {"0331": 1, "0630": 2, "0930": 3, "1231": 4}.get(mmdd)


def ttm_flow(latest_val, latest_quarter, prior_fy_val, prior_same_val):
    """Trailing-12-month value of a cumulative (YTD) flow item.

    FY period (quarter 4) is already a full year -> return it directly. Otherwise
    TTM = latest_YTD + prior_full_year - prior_year_same_period_YTD; any missing
    leg -> None (we never guess a TTM)."""
    if latest_quarter == 4:
        return latest_val
    if latest_val is None or prior_fy_val is None or prior_same_val is None:
        return None
    return latest_val + prior_fy_val - prior_same_val


def clean_ratios(ttm_ni, ttm_rev, ttm_cost, ttm_ocf, equity_avg, market_cap):
    """The four clean factors from TTM aggregates. Each is None unless its inputs
    make it meaningful (positive denominator / positive earnings where required)."""
    out = {"pe_ttm_clean": None, "roe_ttm": None, "ocf_to_ni": None,
           "gross_margin_ttm": None}

    # PE-TTM: only meaningful for positive trailing earnings.
    if ttm_ni is not None and ttm_ni > 0 and market_cap is not None and market_cap > 0:
        out["pe_ttm_clean"] = round(market_cap / ttm_ni, 4)

    # ROE-TTM (percent): TTM earnings over average equity.
    if ttm_ni is not None and equity_avg is not None and equity_avg > 0:
        out["roe_ttm"] = round(ttm_ni / equity_avg * 100.0, 4)

    # OCF / NI (earnings quality): only where earnings are positive.
    if ttm_ocf is not None and ttm_ni is not None and ttm_ni > 0:
        out["ocf_to_ni"] = round(ttm_ocf / ttm_ni, 4)

    # Gross margin (percent): needs positive revenue.
    if ttm_rev is not None and ttm_rev > 0 and ttm_cost is not None:
        out["gross_margin_ttm"] = round((ttm_rev - ttm_cost) / ttm_rev * 100.0, 4)

    return out


def _deadline(qend):
    """Full-report regulatory deadline for an A-share quarter-end date."""
    m, d = qend.month, qend.day
    if (m, d) == (3, 31):
        return date(qend.year, 4, 30)
    if (m, d) == (6, 30):
        return date(qend.year, 8, 31)
    if (m, d) == (9, 30):
        return date(qend.year, 10, 31)
    return date(qend.year + 1, 4, 30)   # 12,31 → next-year Apr 30


def reporting_periods(as_of):
    """The three report periods of the TTM identity for the latest *reported*
    quarter as of ``as_of``. Returns dict with YYYYMMDD strings + quarter, or None
    if nothing is reportable yet."""
    if isinstance(as_of, datetime):
        as_of = as_of.date()
    latest = None
    for y in range(as_of.year, as_of.year - 3, -1):
        for (m, d) in [(12, 31), (9, 30), (6, 30), (3, 31)]:
            qe = date(y, m, d)
            if qe <= as_of and _deadline(qe) <= as_of:
                latest = qe
                break
        if latest:
            break
    if latest is None:
        return None
    prior_fy = date(latest.year - 1, 12, 31)
    prior_same = date(latest.year - 1, latest.month, latest.day)
    fmt = lambda x: x.strftime("%Y%m%d")
    return {"latest": fmt(latest), "prior_fy": fmt(prior_fy),
            "prior_same": fmt(prior_same), "quarter": quarter_of(fmt(latest))}


def build_financials(period_maps, market_caps, periods):
    """Pure TTM assembly: from per-period {ts_code: {field: value}} maps, compute
    the four ratios per ticker. ``period_maps`` keyed by period string.

    This is the unit-testable heart — ``compute_universe_financials`` just feeds it
    Tushare data. Returns {ts_code: ratios_dict} (only tickers with >=1 ratio)."""
    latest, prior_fy, prior_same = periods["latest"], periods["prior_fy"], periods["prior_same"]
    q = periods["quarter"]
    lm = period_maps.get(latest, {})
    fm = period_maps.get(prior_fy, {})
    sm = period_maps.get(prior_same, {})

    out = {}
    for ts in lm:
        def leg(field, m):
            row = m.get(ts) or {}
            return _f(row.get(field))

        ttm_ni = ttm_flow(leg("n_income_attr_p", lm), q, leg("n_income_attr_p", fm),
                          leg("n_income_attr_p", sm))
        ttm_rev = ttm_flow(leg("revenue", lm), q, leg("revenue", fm), leg("revenue", sm))
        ttm_cost = ttm_flow(leg("oper_cost", lm), q, leg("oper_cost", fm), leg("oper_cost", sm))
        ttm_ocf = ttm_flow(leg("n_cashflow_act", lm), q, leg("n_cashflow_act", fm),
                           leg("n_cashflow_act", sm))

        eq_latest = leg("total_hldr_eqy_exc_min_int", lm)
        eq_prior = leg("total_hldr_eqy_exc_min_int", sm)
        if eq_latest is not None and eq_prior is not None:
            equity_avg = (eq_latest + eq_prior) / 2.0
        else:
            equity_avg = eq_latest if eq_latest is not None else eq_prior

        ratios = clean_ratios(ttm_ni, ttm_rev, ttm_cost, ttm_ocf, equity_avg,
                              _f(market_caps.get(ts)))
        if any(v is not None for v in ratios.values()):
            out[ts] = ratios
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Network fetch (Tushare *_vip by report period — whole market per call)
# ──────────────────────────────────────────────────────────────────────────────
def _make_pro(token=None):
    token = token or TUSHARE_TOKEN
    if not token:
        return None, "no_token"
    try:
        import tushare as ts
    except ImportError:
        return None, "tushare_not_installed"
    try:
        ts.set_token(token)
        return ts.pro_api(), None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def _fetch_statement(pro, endpoint, period, fields):
    """Whole-market statement for one period: try the bulk *_vip endpoint, fall
    back to the per-period regular endpoint. Returns a DataFrame (possibly empty)."""
    for name in (endpoint + "_vip", endpoint):
        fn = getattr(pro, name, None)
        if fn is None:
            continue
        try:
            df = fn(period=period, fields=fields)
            if df is not None and not df.empty:
                return df
        except Exception:  # noqa: BLE001
            continue
    return None


def _period_map(pro, endpoint, period, fields, as_of_str):
    """{ts_code: {field: value}} for one period, PIT-filtered to ann_date<=as_of
    and de-duplicated to the latest ann_date per ticker (handles restatements)."""
    df = _fetch_statement(pro, endpoint, period, fields)
    if df is None or df.empty:
        return {}
    cols = [c for c in df.columns if c not in ("ts_code", "ann_date", "end_date")]
    out = {}
    best_ann = {}
    for _, r in df.iterrows():
        ts = str(r.get("ts_code", "")).strip()
        if not ts:
            continue
        ann = str(r.get("ann_date") or "")
        if ann and as_of_str and ann > as_of_str:
            continue  # announced after as_of → not yet known (PIT)
        if ts in best_ann and ann < best_ann[ts]:
            continue  # keep the most recent (restatement) row
        best_ann[ts] = ann
        out[ts] = {c: r.get(c) for c in cols}
    return out


def compute_universe_financials(ts_codes=None, market_caps=None, pro=None, token=None,
                                as_of=None):
    """Clean TTM factors for the universe. Returns (factors_dict, meta).

    meta.basis is 'clean_ttm_filings' on success or a failure reason; meta carries
    the periods used + per-field coverage so the caller/gate can label honestly."""
    market_caps = market_caps or {}
    as_of_dt = as_of or datetime.now()
    meta = {"basis": "unavailable", "as_of": as_of_dt.strftime("%Y%m%d"),
            "periods": None, "coverage": {}, "n_requested": (len(ts_codes) if ts_codes else None)}
    if pro is None:
        pro, err = _make_pro(token)
        if pro is None:
            meta["error"] = err
            return {}, meta
    try:
        periods = reporting_periods(as_of_dt)
        if periods is None:
            meta["error"] = "no_reported_period"
            return {}, meta
        meta["periods"] = periods
        as_of_str = as_of_dt.strftime("%Y%m%d")
        wanted = {periods["latest"], periods["prior_fy"], periods["prior_same"]}

        period_maps = {}
        for p in wanted:
            inc = _period_map(pro, "income", p, INCOME_FIELDS, as_of_str)
            cfs = _period_map(pro, "cashflow", p, CASHFLOW_FIELDS, as_of_str)
            bal = _period_map(pro, "balancesheet", p, BALANCE_FIELDS, as_of_str)
            merged = {}
            for ts in set(inc) | set(cfs) | set(bal):
                row = {}
                row.update(inc.get(ts, {}))
                row.update(cfs.get(ts, {}))
                row.update(bal.get(ts, {}))
                merged[ts] = row
            period_maps[p] = merged

        factors = build_financials(period_maps, market_caps, periods)
        if ts_codes is not None:
            keep = set(ts_codes)
            factors = {k: v for k, v in factors.items() if k in keep}

        for field in ("pe_ttm_clean", "roe_ttm", "ocf_to_ni", "gross_margin_ttm"):
            meta["coverage"][field] = sum(1 for v in factors.values() if v.get(field) is not None)
        meta["basis"] = "clean_ttm_filings"
        return factors, meta
    except Exception as e:  # noqa: BLE001
        meta["error"] = f"{type(e).__name__}: {e}"
        return {}, meta


def enrich_stocks_with_financials(stocks, ticker_key="ticker", cap_key="market_cap",
                                  pro=None, token=None, as_of=None):
    """Attach pe_ttm_clean / roe_ttm / ocf_to_ni / gross_margin_ttm to each stock
    dict (by ts_code). Also mirrors roe_ttm into 'roe' when 'roe' is empty so the
    quality factor + data-health gate see broad ROE coverage. Returns meta. Safe to
    call unconditionally; on failure attaches nothing and the caller keeps the
    provider pe + inert quality (gate keeps warning)."""
    ts_codes = [s.get(ticker_key) for s in stocks if s.get(ticker_key)]
    market_caps = {s.get(ticker_key): s.get(cap_key) for s in stocks if s.get(ticker_key)}
    factors, meta = compute_universe_financials(ts_codes=ts_codes, market_caps=market_caps,
                                                pro=pro, token=token, as_of=as_of)
    if factors:
        for s in stocks:
            f = factors.get(s.get(ticker_key))
            if not f:
                continue
            for k, v in f.items():
                if v is not None:
                    s[k] = v
            # keep raw provider roe if present; otherwise expose clean ROE-TTM as roe
            if f.get("roe_ttm") is not None and s.get("roe") is None:
                s["roe"] = f["roe_ttm"]
    return meta


# ──────────────────────────────────────────────────────────────────────────────
# Selftest (no network) — covers TTM PE / ROE / OCF-NI / GM + fallback + mock E2E
# ──────────────────────────────────────────────────────────────────────────────
def _selftest():
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
        print(f"  {'✓' if cond else '✗ FAIL'} {msg}")

    # 1. TTM-from-cumulative identity.
    check(ttm_flow(30, 1, 100, 25) == 105, "TTM(Q1) = latest 30 + priorFY 100 - priorSame 25 = 105")
    check(ttm_flow(120, 4, 100, 25) == 120, "TTM(Q4=FY) = latest 120 (annual, no subtraction)")
    check(ttm_flow(30, 2, None, 25) is None, "TTM with a missing leg → None (never guessed)")

    # 2. The four ratio algorithms.
    r = clean_ratios(ttm_ni=200.0, ttm_rev=1000.0, ttm_cost=600.0, ttm_ocf=240.0,
                     equity_avg=1600.0, market_cap=3000.0)
    check(r["pe_ttm_clean"] == 15.0, f"PE-TTM = mktcap 3000 / TTM-NI 200 = 15 (got {r['pe_ttm_clean']})")
    check(r["roe_ttm"] == 12.5, f"ROE-TTM = 200/1600*100 = 12.5% (got {r['roe_ttm']})")
    check(r["ocf_to_ni"] == 1.2, f"OCF/NI = 240/200 = 1.2 (got {r['ocf_to_ni']})")
    check(r["gross_margin_ttm"] == 40.0, f"GM = (1000-600)/1000*100 = 40% (got {r['gross_margin_ttm']})")

    # 3. Coverage / fallback: negative earnings → no PE/OCF; zero revenue → no GM;
    #    missing equity → no ROE. Nothing crashes; meaningless ratios stay None.
    rn = clean_ratios(ttm_ni=-50.0, ttm_rev=0.0, ttm_cost=10.0, ttm_ocf=5.0,
                      equity_avg=None, market_cap=1000.0)
    check(rn["pe_ttm_clean"] is None, "negative TTM earnings → PE-TTM None (not a cheap-looking number)")
    check(rn["ocf_to_ni"] is None, "negative earnings → OCF/NI None")
    check(rn["gross_margin_ttm"] is None, "zero revenue → GM None")
    check(rn["roe_ttm"] is None, "missing equity → ROE None")
    check(clean_ratios(None, None, None, None, None, None) ==
          {"pe_ttm_clean": None, "roe_ttm": None, "ocf_to_ni": None, "gross_margin_ttm": None},
          "all-missing inputs → all-None, no crash")

    # 4. reporting_periods picks the latest *reported* quarter (deadline-aware).
    p = reporting_periods(date(2026, 6, 20))   # Q1 reported (Apr30), H1 not yet (Aug31)
    check(p["latest"] == "20260331" and p["quarter"] == 1,
          f"2026-06-20 latest reported = 2026Q1 (got {p['latest']})")
    check(p["prior_fy"] == "20251231" and p["prior_same"] == "20250331",
          f"TTM periods: priorFY 20251231 + priorSame 20250331 (got {p['prior_fy']}/{p['prior_same']})")
    p2 = reporting_periods(date(2026, 9, 15))   # H1 reported (Aug31), Q3 not yet (Oct31)
    check(p2["latest"] == "20260630" and p2["quarter"] == 2,
          f"2026-09-15 latest reported = 2026H1 (got {p2['latest']})")

    # 5. End-to-end mock (no token): full universe build through Tushare-shaped maps.
    periods = reporting_periods(date(2026, 6, 20))
    class _MockPro:
        def _df(self, rows, cols):
            import pandas as pd
            return pd.DataFrame(rows, columns=cols)
        def income_vip(self, period, fields):
            # AAA.SH: Q1 ni 30 / FY 100 / same 25 → TTM 105 ; rev/cost likewise
            data = {
                "20260331": [("AAA.SH", "20260420", 30.0, 60.0, 300.0),
                             # FUT.SH's Q1 is announced 2026-07-20, AFTER as_of → must be PIT-excluded
                             ("FUT.SH", "20260720", 99.0, 10.0, 200.0)],
                "20251231": [("AAA.SH", "20260301", 100.0, 200.0, 1000.0)],
                "20250331": [("AAA.SH", "20250420", 25.0, 50.0, 250.0)],
            }[period]
            return self._df([{"ts_code": t, "ann_date": a, "end_date": period,
                              "n_income_attr_p": ni, "oper_cost": oc, "revenue": rv}
                             for (t, a, ni, oc, rv) in data],
                            ["ts_code", "ann_date", "end_date", "n_income_attr_p", "oper_cost", "revenue"])
        def cashflow_vip(self, period, fields):
            data = {"20260331": 36.0, "20251231": 120.0, "20250331": 30.0}[period]
            return self._df([{"ts_code": "AAA.SH", "ann_date": "20260420",
                              "end_date": period, "n_cashflow_act": data}],
                            ["ts_code", "ann_date", "end_date", "n_cashflow_act"])
        def balancesheet_vip(self, period, fields):
            eq = {"20260331": 1700.0, "20251231": 1600.0, "20250331": 1500.0}[period]
            return self._df([{"ts_code": "AAA.SH", "ann_date": "20260420",
                              "end_date": period, "total_hldr_eqy_exc_min_int": eq}],
                            ["ts_code", "ann_date", "end_date", "total_hldr_eqy_exc_min_int"])
    try:
        import pandas  # noqa: F401
        facts, meta = compute_universe_financials(
            ts_codes=["AAA.SH", "FUT.SH"], market_caps={"AAA.SH": 3150.0, "FUT.SH": 1000.0},
            pro=_MockPro(), as_of=datetime(2026, 6, 20))
        a = facts.get("AAA.SH", {})
        # TTM NI = 30+100-25 = 105 ; PE = 3150/105 = 30
        check(a.get("pe_ttm_clean") == 30.0, f"mock PE-TTM = 3150/105 = 30 (got {a.get('pe_ttm_clean')})")
        # TTM rev = 300+1000-250 = 1050 ; cost = 60+200-50 = 210 ; GM = (1050-210)/1050 = 80%
        check(a.get("gross_margin_ttm") == 80.0, f"mock GM = 80% (got {a.get('gross_margin_ttm')})")
        # TTM OCF = 36+120-30 = 126 ; OCF/NI = 126/105 = 1.2
        check(a.get("ocf_to_ni") == 1.2, f"mock OCF/NI = 126/105 = 1.2 (got {a.get('ocf_to_ni')})")
        # avg equity = (1700+1500)/2 = 1600 ; ROE = 105/1600*100 = 6.5625
        check(abs(a.get("roe_ttm") - 6.5625) < 1e-6, f"mock ROE-TTM = 6.5625% (got {a.get('roe_ttm')})")
        check(meta["basis"] == "clean_ttm_filings" and meta["coverage"]["pe_ttm_clean"] == 1,
              "mock meta basis=clean_ttm_filings + coverage counted")
        # PIT safety: FUT.SH's Q1 was announced 2026-07-20 (> as_of 2026-06-20) so it
        # must NEVER appear — proves we never use a row published after the as_of date.
        check("FUT.SH" not in facts,
              "PIT: a row announced AFTER as_of is excluded, never used (no look-ahead)")
    except ImportError:
        print("  (skipped mock E2E: pandas unavailable)")

    # 6. No-token path is graceful + honest.
    f6, m6 = compute_universe_financials(ts_codes=["A.SH"], token="")
    check(f6 == {} and m6["basis"] == "unavailable", "no token → empty + basis=unavailable")
    stocks = [{"ticker": "A.SH", "market_cap": 1e9, "roe": None}]
    m7 = enrich_stocks_with_financials(stocks, token="")
    check("pe_ttm_clean" not in stocks[0] and m7["basis"] == "unavailable",
          "enrich attaches nothing when unavailable (caller keeps provider pe / inert quality)")

    print("\n  RESULT:", "PASS ✓" if ok else "FAIL ✗")
    return ok


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if _selftest() else 1)
    facts, meta = compute_universe_financials()
    print("meta:", meta)
    if facts:
        print("sample:", list(facts.items())[:3])
