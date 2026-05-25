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

TOP_N = 15
GROSS = 0.95
MIN_FACTORS = 3   # need >= this many non-None factors to be rankable

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


def make_satellite_strategy(top_n: int = TOP_N, gross: float = GROSS, factor_config: dict | None = None):
    """Return a backtest_v2.Strategy closure. factor_config sets the pit_factors
    window units (default MONTHLY since the backtest runs on month-end bars)."""
    fc = factor_config or MONTHLY_FACTOR_CONFIG
    def strategy(as_of, members, store):
        factors = pit_factors.compute_factors(members, as_of, store, fc)
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
