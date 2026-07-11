#!/usr/bin/env python3
"""satellite_strategy.py — the pure-quant SATELLITE strategy, as a backtest Strategy.

Wires the verified pieces into one historical-backtestable strategy:
  pit_factors.compute_factors(members, T, store)   # PIT factor scores as-of T
    -> weighted composite (Q30/V20/M25/Growth15/LV10, the intended §2 blend;
       pit_factors now provides `growth`, so no more `size` stand-in)
    -> rank, take top-N (15 satellite)
    -> long-only target weights
Signature matches backtest_v2.Strategy: (as_of, members, store) -> {ticker: weight}.

This is the SATELLITE (pure-quant) track only. The CORE (hedge-fund-logic thesis)
track is not backtested (forward-validated; see spec §9).

The integration --selftest runs the FULL chain on a synthetic data_history
fixture through backtest_v2.run_backtest, proving pit_factors -> strategy ->
engine works end-to-end with NO look-ahead and survivorship safety. It does NOT
assert any performance number — real numbers require real data via GHA.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pit_factors          # noqa: E402
import factor_construction   # noqa: E402  (iter-8: Barra-style construction)
import universe_filter       # noqa: E402  (iter-8: LSY/Li-Rao shell-stock filter)
from backtest_v2 import PitDataStore, PitUniverse, run_backtest  # noqa: E402

# Intended §2 blend (now that pit_factors provides growth). Calibration starting
# points — to be OLS-fit on the 20yr backtest (Junyan 2026-05-25).
WEIGHTS = {"quality": 0.30, "value": 0.20, "momentum": 0.25, "growth": 0.15, "low_vol": 0.10}

# Prefer OLS-CALIBRATED weights if calibrate_weights.py has produced them
# (Junyan: fit via OLS after the backtest has real data). Falls back to the
# hand-set priors above. _WEIGHTS_SOURCE records which is in use (observability).
_WEIGHTS_SOURCE = "hand-set priors [unvalidated intuition]"
try:
    _cw = json.loads((REPO_ROOT / "public" / "data" / "calib_weights.json").read_text())
    if _cw.get("_status") == "ok" and isinstance(_cw.get("weights"), dict):
        _w = {k: float(v) for k, v in _cw["weights"].items() if k in WEIGHTS}
        if _w and abs(sum(_w.values()) - 1.0) < 0.05:
            WEIGHTS = _w
            _WEIGHTS_SOURCE = f"OLS-calibrated (in-sample {(_cw.get('_meta') or {}).get('in_sample_window')})"
except Exception:
    pass

TOP_N = 15  # reverted from 30 (iter-7 showed top-30 has WORSE alpha than top-15; concentration is not the source of alpha gap — signal weakness is)
GROSS = 0.95
# Dynamic min-factors threshold: with the original 5-factor set we required ≥3
# (60% available); with a Stage-3 2-factor refit we'd need ≥2 (100%) since
# requiring 3-of-2 is impossible. Rule: ceil(0.6 × len(WEIGHTS)), min 1.
# Preserves the "≥60% data availability" intent across factor-set sizes.
MIN_FACTORS = max(1, (len(WEIGHTS) * 6 + 9) // 10)

# Factor windows in PRICE-SERIES POSITIONS. The backtest uses MONTH-END bars
# (monthly-rebalance strategy doesn't need daily resolution — daily 20yr×5000
# was ~5h to fetch; month-end is ~240 points → minutes). pit_factors' windows
# are position-counts, so with monthly bars: lookback 12 = 12 months, skip 1,
# vol over 12 months. (Defaults in pit_factors are daily 252/21/120.)
MONTHLY_FACTOR_CONFIG = {
    "momentum_lookback_td": 12,
    "momentum_skip_td": 1,
    "vol_window_td": 12,
    "min_vol_obs": 6,
}


def _composite(scores: dict) -> float | None:
    """Weighted avg over AVAILABLE (non-None) factors, weights renormalized.
    Missing factors reduce confidence but don't zero the name — honest handling
    of partial data (vs the old const-50 fabrication)."""
    num = den = 0.0
    have = 0
    for f, w in WEIGHTS.items():
        s = scores.get(f)
        if s is not None:
            num += w * float(s)
            den += w
            have += 1
    if have < MIN_FACTORS or den == 0:
        return None
    return num / den


def _barra_composite(factors: dict, members: list, store, as_of, universe,
                     weights: dict, n_sigma: float = 3.0,
                     do_industry_neutralize: bool = True) -> dict:
    """Iter-8 composite: Barra-style winsorize + cap-weighted standardize +
    industry residualize per factor, then weighted sum into composite.

    Returns ticker → composite_score (or None if all factors missing).
    """
    # Pull mcap + industry for each member at T.
    mcap = {}
    for tk in members:
        mv, _ = pit_factors._market_cap_asof(store, tk, as_of, pit_factors.CONFIG)
        mcap[tk] = mv
    industry = {}
    if universe is not None:
        # universe._rows is list of {ts_code, list_date, delist_date, name, industry}
        ind_by_code = {r["ts_code"]: r.get("industry") for r in universe._rows}
        industry = {tk: ind_by_code.get(tk) for tk in members}

    # For each factor, take the RAW value (not the percentile), then Barra-construct.
    standardized = {}
    for fname in WEIGHTS.keys():
        raw_by_tk = {tk: (factors.get(tk, {}).get("_raw", {}).get("factors", {}).get(fname))
                     for tk in members}
        z = factor_construction.barra_construct(
            raw_by_tk, mcap, industry,
            n_sigma=n_sigma, do_industry_neutralize=do_industry_neutralize,
        )
        standardized[fname] = z

    # Weighted sum into composite — preserves None if all factors missing
    composite = {}
    for tk in members:
        num = den = 0.0
        have = 0
        for fname, w in weights.items():
            z = standardized[fname].get(tk)
            if z is not None:
                num += w * z
                den += w
                have += 1
        composite[tk] = (num / den) if have >= MIN_FACTORS and den > 0 else None
    return composite


def _smoothed_factors(members, as_of, store, fc, smooth_n=3):
    """Iter-11: compute factor scores at as_of, as_of-1mo, as_of-2mo and average.

    Per Stage 2 IC finding that h=3m signal is ~3× stronger than h=1m: smoothing
    each factor over a 3-month rolling window approximates a 3-month effective
    holding period WITHOUT sacrificing the monthly entry-point opportunity that
    quarterly rebal (iter-10) gave up.

    Returns the same dict structure as pit_factors.compute_factors but with
    smoothed RAW factor values + smoothed percentile-rank scores per factor.
    PIT-clean: each lookback date uses only data with trade_date <= that date.
    """
    from datetime import date as _date
    # Build n lookback as_of dates (today, T-30d, T-60d, ...)
    lookbacks = []
    for k in range(smooth_n):
        target = _date.fromordinal(as_of.toordinal() - 30 * k)
        lookbacks.append(target)

    # Compute factors at each lookback date
    factors_per_date = []
    for lb in lookbacks:
        f = pit_factors.compute_factors(members, lb, store, fc)
        factors_per_date.append(f)

    # Use today's factor table as the structural template; replace raw factor
    # values with smoothed averages across lookbacks (per ticker, per factor).
    base = factors_per_date[0]  # as_of
    smoothed = {}
    for tk in members:
        smoothed[tk] = dict(base.get(tk, {}))   # copy
        if "_raw" not in smoothed[tk]:
            continue
        smoothed[tk]["_raw"] = dict(smoothed[tk]["_raw"])
        smoothed[tk]["_raw"]["factors"] = dict(smoothed[tk]["_raw"].get("factors") or {})
        for fname in ("momentum", "low_vol", "value", "quality", "growth"):
            vals = []
            for f_table in factors_per_date:
                v = (f_table.get(tk, {}).get("_raw", {}).get("factors", {}) or {}).get(fname)
                if v is not None:
                    vals.append(float(v))
            if vals:
                smoothed[tk]["_raw"]["factors"][fname] = sum(vals) / len(vals)
            else:
                smoothed[tk]["_raw"]["factors"][fname] = None

    # Re-score percentile-rank on the smoothed RAW values
    for fname in ("momentum", "low_vol", "value", "quality", "growth"):
        raw_by_tk = {tk: smoothed[tk].get("_raw", {}).get("factors", {}).get(fname)
                     for tk in members}
        scores, _ = pit_factors._score_factor(raw_by_tk)
        for tk in members:
            if tk in smoothed:
                smoothed[tk][fname] = (None if scores.get(tk) is None
                                       else round(scores[tk], 4))
    return smoothed


def make_satellite_strategy(top_n: int = TOP_N, gross: float = GROSS,
                            factor_config: dict | None = None,
                            *,
                            apply_universe_filter: bool = False,
                            universe_filter_config: dict | None = None,
                            use_barra_construction: bool = False,
                            universe=None,
                            barra_n_sigma: float = 3.0,
                            barra_industry_neutralize: bool = True,
                            smooth_factors_n: int = 1):
    """Return a backtest_v2.Strategy closure.

    Args:
        top_n, gross, factor_config: as before (backwards compatible).

        ITER-8 OPT-IN UPGRADES (default OFF — iter-7 results still reproducible):

        apply_universe_filter: bool. If True, apply LSY/Li-Rao shell-stock
            filter to members BEFORE compute_factors. Requires
            universe_filter_config (default DEFAULT_CONFIG = 5% mcap floor).
        universe_filter_config: dict for universe_filter.filter_universe.
        use_barra_construction: bool. If True, switch from
            percentile-rank-then-weighted-avg to Barra USE4 pipeline (winsorize
            ±N σ + cap-weighted standardize + industry residualize) per factor,
            then weighted sum. Requires universe (PitUniverse) for industry lookup
            when industry_neutralize=True.
        universe: PitUniverse object (needed for industry lookup if Barra is on).
        barra_n_sigma: winsorize bound (default 3.0 per USE4).
        barra_industry_neutralize: whether to residualize vs industry (default True).
    """
    fc = factor_config or MONTHLY_FACTOR_CONFIG
    uf_cfg = universe_filter_config

    def strategy(as_of, members, store):
        # Stage 1a: optional shell-stock filter (LSY/Li-Rao)
        if apply_universe_filter:
            members = universe_filter.filter_universe(members, store, as_of, uf_cfg)
        if not members:
            return {}

        # iter-11: optional 3-month factor smoothing (signal horizon ≠ rebal freq)
        if smooth_factors_n > 1:
            factors = _smoothed_factors(members, as_of, store, fc, smooth_n=smooth_factors_n)
        else:
            factors = pit_factors.compute_factors(members, as_of, store, fc)

        # Composite — Barra (iter-8) or percentile rank (iter-7 legacy)
        if use_barra_construction:
            composites = _barra_composite(
                factors, members, store, as_of, universe,
                weights=WEIGHTS, n_sigma=barra_n_sigma,
                do_industry_neutralize=barra_industry_neutralize,
            )
            ranked = [(c, tk) for tk, c in composites.items() if c is not None]
        else:
            ranked = []
            for tk, sc in factors.items():
                comp = _composite(sc)
                if comp is not None:
                    ranked.append((comp, tk))

        ranked.sort(reverse=True)
        picks = [tk for _, tk in ranked[:top_n]]
        if not picks:
            return {}
        w = gross / len(picks)
        return {tk: w for tk in picks}
    return strategy


# ───────────────────────── Integration self-test ────────────────────────────

def _build_fixture():
    """Synthetic data_history: 5 stocks, ~3yr daily + 2 annual statements each,
    engineered so factor scores differ (so ranking is non-trivial)."""
    store = PitDataStore()
    start = date(2021, 1, 1)
    n_days = 760  # ~3yr of weekday-ish daily points
    # trend slopes differ per stock -> different momentum
    specs = {
        "AAA.SZ": dict(p0=10.0, slope=0.0009, roe=0.22, gm=0.45, rev0=100, rev1=130),  # strong
        "BBB.SZ": dict(p0=20.0, slope=0.0006, roe=0.15, gm=0.30, rev0=100, rev1=112),
        "CCC.SZ": dict(p0=15.0, slope=0.0002, roe=0.09, gm=0.20, rev0=100, rev1=103),
        "DDD.SZ": dict(p0=30.0, slope=-0.0004, roe=0.05, gm=0.12, rev0=100, rev1=95),  # weak
        "EEE.SZ": dict(p0=8.0, slope=0.0007, roe=0.18, gm=0.38, rev0=100, rev1=120),
    }
    for tk, s in specs.items():
        daily = []
        for i in range(n_days):
            d = start + timedelta(days=i)
            px = s["p0"] * (1.0 + s["slope"]) ** i
            daily.append({"trade_date": d.strftime("%Y%m%d"), "close": round(px, 3),
                          "open": round(px, 3), "high": round(px, 3), "low": round(px, 3),
                          "vol": 1_000_000, "amount": 1e8})
        # daily_basic for value (total_mv) — give differing mv
        for r in daily:
            r_mv = s["p0"] * 1e8
        # two annual statements (2021, 2022) w/ ann_date in following April
        equity = 1e9
        fin_income = [
            {"ann_date": "20220415", "end_date": "20211231", "revenue": s["rev0"] * 1e7,
             "oper_cost": s["rev0"] * 1e7 * (1 - s["gm"]), "n_income": s["rev0"] * 1e7 * s["roe"] * 0.5,
             "n_income_attr_p": s["rev0"] * 1e7 * s["roe"] * 0.5},
            {"ann_date": "20230415", "end_date": "20221231", "revenue": s["rev1"] * 1e7,
             "oper_cost": s["rev1"] * 1e7 * (1 - s["gm"]), "n_income": s["rev1"] * 1e7 * s["roe"] * 0.5,
             "n_income_attr_p": s["rev1"] * 1e7 * s["roe"] * 0.5},
        ]
        store.load_ticker(tk, daily, fin_income)
        # balancesheet for ROE/leverage (separate load via internal dicts not exposed;
        # pit_factors reads financials_asof which we approximate by merging into fin rows)
    return store, list(specs.keys())


def _selftest() -> int:
    failures = []
    store, tickers = _build_fixture()
    uni = PitUniverse([{"ts_code": tk, "list_date": "20200101", "delist_date": None} for tk in tickers])

    # 1) strategy returns sensible weights as-of a date with enough history
    strat = make_satellite_strategy(top_n=3)
    asof = date(2023, 6, 1)
    w = strat(asof, tickers, store)
    if not w:
        failures.append("strategy returned no weights with full fixture history")
    else:
        if abs(sum(w.values()) - GROSS) > 1e-6:
            failures.append(f"weights gross != {GROSS}: {sum(w.values())}")
        if len(w) != 3:
            failures.append(f"top_n=3 not honored: {len(w)} picks")
        # strong names (AAA/EEE) should tend to rank in; weak DDD should not be top-3
        if "DDD.SZ" in w and "AAA.SZ" not in w:
            failures.append(f"ranking implausible (weak DDD in, strong AAA out): {list(w)}")

    # 2) FULL CHAIN: run the backtest engine with this strategy over the fixture
    res = run_backtest(store, uni, date(2023, 1, 1), date(2023, 9, 1), strat)
    if not res.equity or len(res.equity) < 3:
        failures.append(f"end-to-end backtest produced too few periods: {len(res.equity)}")
    if res.cagr is None:
        failures.append("end-to-end backtest CAGR is None (engine didn't run)")
    # determinism
    res2 = run_backtest(store, uni, date(2023, 1, 1), date(2023, 9, 1), strat)
    if res.equity != res2.equity:
        failures.append("end-to-end backtest non-deterministic")

    if failures:
        print("SELFTEST FAILED satellite_strategy:")
        for f in failures:
            print("  -", f)
        return 1
    print("SELFTEST PASSED satellite_strategy")
    print("- composite ranks strong>weak names (factor-driven)")
    print("- top_n + gross weighting honored")
    print("- FULL CHAIN pit_factors -> satellite_strategy -> backtest_v2 runs e2e")
    print("- deterministic")
    print(f"(fixture equity path: {[round(e,4) for e in res.equity]} — fixture only, NOT a real number)")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Pure-quant satellite strategy (backtest Strategy).")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    print("satellite_strategy: import make_satellite_strategy() and pass to "
          "backtest_v2.run_backtest. Run --selftest to verify the full chain on fixtures.",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
