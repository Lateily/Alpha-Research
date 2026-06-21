#!/usr/bin/env python3
"""Cyclical-normalization flag for the A-share universe (screen v1.1).

WHY THIS EXISTS
---------------
After #99 (real 12-1 momentum) and #100 (clean TTM PE / ROE-TTM) the universe
factors are clean — but the first clean whole-market screen surfaced a NEW noise
source: commodity/cyclical names (铝 / 煤 / 化肥 / 航运 / 钢) that look cheap on a
*correct* TTM PE **because their trailing earnings sit at a cycle peak**. High
current ROE/margin → low PE → "假便宜" of a different kind: a value trap, not a
data error. Clean factors fixed the data; they cannot see peak-cycle economics.

This does NOT remove cyclicals. It LABELS them so (a) the screen can demote
"cheap-only-because-peak" names instead of letting 铝/煤/化肥/航运 dominate, and
(b) any deep thesis on a cyclical is forced to build a NORMALIZED earnings bridge
rather than extrapolating peak TTM.

WHAT IT COMPUTES (per name)
---------------------------
  cyclical_sector          : industry ∈ a curated commodity/cyclical set
  roe_median_5y / gm_median_5y : median of the last ≤5 fiscal-year ROE / gross margin
  roe_ttm_vs_median        : current TTM ROE / 5y-median ROE  (>1 = above own history)
  gm_ttm_vs_median         : current TTM GM  / 5y-median GM
  peak_earnings_risk       : cyclical AND current profitability >> its OWN 5y median
  needs_normalized_bridge  : True for every cyclical name (a cyclical deep thesis
                             must normalize earnings, regardless of where in the cycle)

The peak test is RELATIVE TO THE COMPANY'S OWN HISTORY (is this firm's current
ROE high vs its own 5y median), not an absolute cutoff — so a structurally
high-ROE quality cyclical is not mislabelled, only one running hot vs itself.

LEAN: 5 fiscal-year income + balancesheet via the same *_vip by-period endpoints
as #100 (~10 calls, whole market per call), reusing universe_financials helpers.
HONEST: no history → medians None → peak_earnings_risk stays False (never cry
"peak" without evidence); no token / API error → attaches nothing.

VALIDATION: the median-vs-current peak test is a standard cyclical-normalization
heuristic; the sector list and the 1.25× / 1.10× thresholds are
``[unvalidated intuition]`` operational priors, to be calibrated against forward
checkpoint outcomes.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime

# Reuse the proven by-period fetch + helpers from the #100 financials module.
try:
    from universe_financials import _make_pro, _period_map, _f, _deadline
except ImportError:  # pragma: no cover - allows standalone import in odd layouts
    _make_pro = _period_map = _f = _deadline = None

TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")

FY_INCOME_FIELDS = "ts_code,ann_date,end_date,revenue,oper_cost,n_income_attr_p"
FY_BALANCE_FIELDS = "ts_code,ann_date,end_date,total_hldr_eqy_exc_min_int"

# Curated commodity/cyclical industries (universe `industry` taxonomy). A LABEL,
# not a kill-list. Inclusive of clear cyclicals where TTM earnings can sit at a
# cycle peak. 汽车整车 is intentionally included (flags 宇通-type export-cycle
# names for a normalized bridge, which is exactly what we want).
CYCLICAL_SECTORS = {
    "铝", "铜", "铅锌", "小金属", "黄金", "稀有金属", "有色金属",
    "普钢", "特种钢", "钢加工", "钢铁",
    "煤炭开采", "焦炭加工",
    "石油开采", "石油加工", "石油贸易", "火力发电",
    "化工原料", "化学原料", "农药化肥", "化纤", "塑料", "橡胶",
    "玻璃", "水泥", "玻璃纤维",
    "水运", "港口", "航运",
    "饲料", "养殖业", "农牧饲渔",
    "工程机械", "汽车整车",
}

PEAK_ROE_RATIO = 1.25   # current TTM ROE >= 125% of its own 5y median → running hot
PEAK_GM_RATIO = 1.15    # or current GM >= 115% of its own 5y median
MIN_YEARS_FOR_MEDIAN = 3


# ──────────────────────────────────────────────────────────────────────────────
# Pure computation (no network — fully unit-testable)
# ──────────────────────────────────────────────────────────────────────────────
def _median(vals):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    n = len(v)
    m = n // 2
    return v[m] if n % 2 else (v[m - 1] + v[m]) / 2.0


def cyclical_flag_for(industry, roe_ttm, gm_ttm, pe_ttm, roe_median_5y, gm_median_5y):
    """Pure flag logic for one name. Returns the annotation dict."""
    cyclical = (industry or "") in CYCLICAL_SECTORS

    def ratio(cur, med):
        if cur is None or med is None or med == 0:
            return None
        return round(cur / med, 3)

    roe_vs = ratio(roe_ttm, roe_median_5y)
    gm_vs = ratio(gm_ttm, gm_median_5y)

    # Peak test is RELATIVE TO OWN HISTORY: current profitability >> own 5y median.
    peak = bool(cyclical and (
        (roe_vs is not None and roe_vs >= PEAK_ROE_RATIO) or
        (gm_vs is not None and gm_vs >= PEAK_GM_RATIO)
    ))
    # cheap-on-elevated: low TTM PE while running above own history → value-trap shape
    cheap_on_elevated = bool(
        cyclical and pe_ttm is not None and pe_ttm < 15 and (
            (roe_vs is not None and roe_vs >= 1.10) or
            (gm_vs is not None and gm_vs >= 1.10)
        )
    )
    return {
        "cyclical_sector": cyclical,
        "roe_median_5y": roe_median_5y,
        "gm_median_5y": gm_median_5y,
        "roe_ttm_vs_median": roe_vs,
        "gm_ttm_vs_median": gm_vs,
        "peak_earnings_risk": peak or cheap_on_elevated,
        # Any cyclical deep thesis must normalize earnings — independent of where the
        # cycle currently is — so this is sector-driven, not peak-driven.
        "needs_normalized_bridge": cyclical,
    }


def build_medians(fy_income_maps, fy_balance_maps):
    """From per-FY {ts: {field}} maps, compute per-ticker 5y-median ROE and GM.
    Returns {ts: {'roe_median_5y':.., 'gm_median_5y':.., 'years':n}}."""
    tickers = set()
    for m in fy_income_maps.values():
        tickers |= set(m)
    out = {}
    for ts in tickers:
        roes, gms = [], []
        for period, inc in fy_income_maps.items():
            row = inc.get(ts) or {}
            rev = _f(row.get("revenue")); cost = _f(row.get("oper_cost"))
            ni = _f(row.get("n_income_attr_p"))
            bal = (fy_balance_maps.get(period) or {}).get(ts) or {}
            eq = _f(bal.get("total_hldr_eqy_exc_min_int"))
            if rev is not None and rev > 0 and cost is not None:
                gms.append((rev - cost) / rev * 100.0)
            if ni is not None and eq is not None and eq > 0:
                roes.append(ni / eq * 100.0)
        rec = {}
        if len(roes) >= MIN_YEARS_FOR_MEDIAN:
            rec["roe_median_5y"] = round(_median(roes), 4)
        if len(gms) >= MIN_YEARS_FOR_MEDIAN:
            rec["gm_median_5y"] = round(_median(gms), 4)
        if rec:
            rec["years"] = max(len(roes), len(gms))
            out[ts] = rec
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Network fetch (5 fiscal years via *_vip by period)
# ──────────────────────────────────────────────────────────────────────────────
def fiscal_year_ends(as_of, n=5):
    """The last n fiscal-year ends (YYYYMMDD) whose full-report deadline has passed."""
    if isinstance(as_of, datetime):
        as_of = as_of.date()
    ends = []
    y = as_of.year
    while len(ends) < n and y > as_of.year - n - 3:
        fy = date(y, 12, 31)
        if fy <= as_of and (_deadline(fy) <= as_of if _deadline else True):
            ends.append(fy.strftime("%Y%m%d"))
        y -= 1
    return ends


def compute_cyclical_flags(stocks, pro=None, token=None, as_of=None):
    """Compute the cyclical flag per stock. ``stocks`` is the list of universe
    dicts (needs ticker/industry + #100's roe_ttm/gross_margin_ttm/pe_ttm_clean).
    Returns (flags_dict, meta)."""
    as_of_dt = as_of or datetime.now()
    meta = {"basis": "unavailable", "as_of": as_of_dt.strftime("%Y%m%d"),
            "fy_ends": None, "n_cyclical": 0, "n_peak": 0}
    if _make_pro is None:
        meta["error"] = "universe_financials_helpers_unavailable"
        return {}, meta
    if pro is None:
        pro, err = _make_pro(token)
        if pro is None:
            meta["error"] = err
            return {}, meta
    try:
        fy_ends = fiscal_year_ends(as_of_dt, n=5)
        if not fy_ends:
            meta["error"] = "no_fiscal_years"
            return {}, meta
        as_of_str = as_of_dt.strftime("%Y%m%d")
        fy_income, fy_balance = {}, {}
        for p in fy_ends:
            fy_income[p] = _period_map(pro, "income", p, FY_INCOME_FIELDS, as_of_str)
            fy_balance[p] = _period_map(pro, "balancesheet", p, FY_BALANCE_FIELDS, as_of_str)
        medians = build_medians(fy_income, fy_balance)

        flags = {}
        n_cyc = n_peak = 0
        for s in stocks:
            ts = s.get("ticker")
            if not ts:
                continue
            med = medians.get(ts, {})
            flag = cyclical_flag_for(
                s.get("industry"), _f(s.get("roe_ttm")), _f(s.get("gross_margin_ttm")),
                _f(s.get("pe_ttm_clean")), med.get("roe_median_5y"), med.get("gm_median_5y"))
            flags[ts] = flag
            n_cyc += flag["cyclical_sector"]
            n_peak += flag["peak_earnings_risk"]
        meta.update({"basis": "filings_5y_median", "fy_ends": fy_ends,
                     "n_cyclical": n_cyc, "n_peak": n_peak,
                     "median_coverage": len(medians)})
        return flags, meta
    except Exception as e:  # noqa: BLE001
        meta["error"] = f"{type(e).__name__}: {e}"
        return {}, meta


def enrich_stocks_with_cyclical_flag(stocks, pro=None, token=None, as_of=None):
    """Attach ``cyclical_flag`` to each stock dict. Returns meta. Safe to call
    unconditionally; on failure attaches nothing."""
    flags, meta = compute_cyclical_flags(stocks, pro=pro, token=token, as_of=as_of)
    if flags:
        for s in stocks:
            f = flags.get(s.get("ticker"))
            if f is not None:
                s["cyclical_flag"] = f
    return meta


# ──────────────────────────────────────────────────────────────────────────────
# Selftest (no network)
# ──────────────────────────────────────────────────────────────────────────────
def _selftest():
    ok = True

    def check(c, m):
        nonlocal ok
        if not c:
            ok = False
        print(f"  {'✓' if c else '✗ FAIL'} {m}")

    # 1. Median.
    check(_median([10, 20, 30]) == 20, "median odd = middle")
    check(_median([10, 20, 30, 40]) == 25, "median even = mean of middle two")
    check(_median([]) is None, "median empty → None")

    # 2. A cyclical running HOT vs its own history → peak_earnings_risk.
    hot = cyclical_flag_for("铝", roe_ttm=22.0, gm_ttm=28.0, pe_ttm=9.0,
                            roe_median_5y=10.0, gm_median_5y=18.0)
    check(hot["cyclical_sector"] and hot["peak_earnings_risk"],
          f"铝 ROE 22 vs 5y-median 10 (2.2x) → peak_earnings_risk (got {hot['peak_earnings_risk']})")
    check(hot["needs_normalized_bridge"], "cyclical → needs_normalized_bridge True")
    check(hot["roe_ttm_vs_median"] == 2.2, f"roe_ttm_vs_median = 2.2 (got {hot['roe_ttm_vs_median']})")

    # 3. A cyclical at/below its own median → NOT a peak (cheap may be genuine).
    norm = cyclical_flag_for("铝", roe_ttm=9.0, gm_ttm=17.0, pe_ttm=9.0,
                             roe_median_5y=10.0, gm_median_5y=18.0)
    check(norm["cyclical_sector"] and not norm["peak_earnings_risk"],
          "铝 at its own median → cyclical but NOT peak (not mislabelled)")

    # 4. A structurally high-ROE quality cyclical (high but in line with own history)
    #    is NOT flagged peak — peak is relative to OWN median, not absolute.
    quality = cyclical_flag_for("汽车整车", roe_ttm=35.0, gm_ttm=25.0, pe_ttm=11.0,
                                roe_median_5y=32.0, gm_median_5y=24.0)
    check(not quality["peak_earnings_risk"],
          "ROE 35 but 5y-median 32 (1.09x) → not peak (structurally high ≠ peak)")
    check(quality["needs_normalized_bridge"], "汽车整车 still flagged needs_normalized_bridge")

    # 5. A NON-cyclical name is never flagged.
    soft = cyclical_flag_for("游戏", roe_ttm=40.0, gm_ttm=92.0, pe_ttm=18.0,
                             roe_median_5y=10.0, gm_median_5y=80.0)
    check(not soft["cyclical_sector"] and not soft["peak_earnings_risk"]
          and not soft["needs_normalized_bridge"],
          "non-cyclical (游戏) never flagged, even with high ROE-vs-median")

    # 6. No median (insufficient history) → no peak call, but cyclical still needs bridge.
    nohist = cyclical_flag_for("煤炭开采", roe_ttm=30.0, gm_ttm=40.0, pe_ttm=8.0,
                               roe_median_5y=None, gm_median_5y=None)
    check(not nohist["peak_earnings_risk"] and nohist["needs_normalized_bridge"],
          "no 5y history → never cry peak, but cyclical still needs normalized bridge")

    # 7. build_medians over FY maps + a mock end-to-end.
    fy_inc = {
        "20251231": {"A.SH": {"revenue": 1000.0, "oper_cost": 600.0, "n_income_attr_p": 200.0}},
        "20241231": {"A.SH": {"revenue": 900.0, "oper_cost": 600.0, "n_income_attr_p": 100.0}},
        "20231231": {"A.SH": {"revenue": 800.0, "oper_cost": 560.0, "n_income_attr_p": 80.0}},
    }
    fy_bal = {
        "20251231": {"A.SH": {"total_hldr_eqy_exc_min_int": 1000.0}},  # roe 20
        "20241231": {"A.SH": {"total_hldr_eqy_exc_min_int": 1000.0}},  # roe 10
        "20231231": {"A.SH": {"total_hldr_eqy_exc_min_int": 1000.0}},  # roe 8
    }
    med = build_medians(fy_inc, fy_bal)
    check(med["A.SH"]["roe_median_5y"] == 10.0, f"5y-median ROE of [20,10,8] = 10 (got {med['A.SH'].get('roe_median_5y')})")
    # GM = [40, 33.33, 30] → median 33.33
    check(abs(med["A.SH"]["gm_median_5y"] - 33.3333) < 1e-3, f"5y-median GM ≈ 33.33 (got {med['A.SH'].get('gm_median_5y')})")

    try:
        import pandas as pd
        class _MockPro:
            def _df(self, rows, cols):
                return pd.DataFrame(rows, columns=cols)
            def income_vip(self, period, fields):
                d = {"20251231": (1000.0, 600.0, 200.0), "20241231": (900.0, 600.0, 100.0),
                     "20231231": (800.0, 560.0, 80.0), "20221231": (700.0, 520.0, 60.0),
                     "20211231": (600.0, 470.0, 40.0)}[period]
                return self._df([{"ts_code": "CYC.SH", "ann_date": "20260301", "end_date": period,
                                  "revenue": d[0], "oper_cost": d[1], "n_income_attr_p": d[2]}],
                                ["ts_code", "ann_date", "end_date", "revenue", "oper_cost", "n_income_attr_p"])
            def balancesheet_vip(self, period, fields):
                return self._df([{"ts_code": "CYC.SH", "ann_date": "20260301", "end_date": period,
                                  "total_hldr_eqy_exc_min_int": 1000.0}],
                                ["ts_code", "ann_date", "end_date", "total_hldr_eqy_exc_min_int"])
        stocks = [{"ticker": "CYC.SH", "industry": "铝", "roe_ttm": 25.0,
                   "gross_margin_ttm": 42.0, "pe_ttm_clean": 9.0}]
        flags, meta = compute_cyclical_flags(stocks, pro=_MockPro(), as_of=datetime(2026, 6, 21))
        fl = flags.get("CYC.SH", {})
        # 5 FY ROE = [20,10,8,6,4] → median 8 ; current 25 vs 8 = 3.1x → peak
        check(fl.get("roe_median_5y") == 8.0 and fl.get("peak_earnings_risk"),
              f"mock: 5y-median ROE 8, current 25 → peak (got median={fl.get('roe_median_5y')}, peak={fl.get('peak_earnings_risk')})")
        check(meta["basis"] == "filings_5y_median" and meta["n_peak"] == 1,
              "mock meta basis=filings_5y_median + n_peak counted")
    except ImportError:
        print("  (skipped mock E2E: pandas unavailable)")

    print("\n  RESULT:", "PASS ✓" if ok else "FAIL ✗")
    return ok


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if _selftest() else 1)
    print("cyclical_flag: import-only module; run --selftest or call from fetch_data.")
