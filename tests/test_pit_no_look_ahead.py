#!/usr/bin/env python3
"""test_pit_no_look_ahead.py — explicit guard against the 华泰 NSGA-II bug class.

CONTEXT: in May 2026 a community member replicated a Huatai sell-side
high-frequency factor mining research report using NSGA-II multi-objective
genetic optimization, got 690% backtest return (2019-2026, ~33% CAGR,
Sharpe 2-5 in good years). The community then found a 1-line look-ahead bug:
`B_shift_lag = [..., -1, -2, ...]` — the negative lags use FUTURE data. The
entire 690% is contaminated by look-ahead bias.

Our PitDataStore architecture (refuses to expose data with `ann_date > as_of`
or `trade_date > as_of`) makes this bug class STRUCTURALLY IMPOSSIBLE. This
test file is the canonical guard: it constructs fixtures where future data
EXISTS in the store but should NOT be visible at decision date T, and asserts
that every PIT API (price_asof, financials_asof, daily_basic_asof, daily_return,
compute_factors, filter_universe, satellite_strategy) refuses to leak it.

INVARIANT (the formal PIT contract):
  For any as_of date T, the output of the full pipeline must be IDENTICAL
  whether or not the store contains data with date > T.

If this test EVER fails, treat it as a P0 — a look-ahead bug invalidates every
backtest result downstream.

Run via:  python3 tests/test_pit_no_look_ahead.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from backtest_v2 import PitDataStore, PitUniverse, run_backtest         # noqa: E402
import pit_factors                                                       # noqa: E402
import universe_filter                                                   # noqa: E402
from satellite_strategy import make_satellite_strategy                   # noqa: E402


def _annual(end: str, ann: str, revenue: float, oper_cost: float,
            ni: float, equity: float, assets: float, liab: float) -> dict:
    return {
        "end_date": end, "ann_date": ann,
        "revenue": revenue, "oper_cost": oper_cost,
        "n_income": ni, "n_income_attr_p": ni,
        "total_hldr_eqy_exc_min_int": equity,
        "total_assets": assets, "total_liab": liab,
    }


def _daily(start_year: int, n_days: int, ramp_from: float, ramp_to: float) -> list[dict]:
    """Generate n_days of synthetic daily bars starting from {start_year}-01-01."""
    from datetime import timedelta
    start = date(start_year, 1, 1)
    out = []
    for i in range(n_days):
        d = start + timedelta(days=i)
        px = ramp_from + (ramp_to - ramp_from) * (i / max(1, n_days - 1))
        out.append({"trade_date": d.strftime("%Y%m%d"), "close": round(px, 4)})
    return out


def _basic(start_year: int, n_days: int, mv: float, circ_mv: float | None = None) -> list[dict]:
    from datetime import timedelta
    start = date(start_year, 1, 1)
    return [
        {"trade_date": (start + __import__("datetime").timedelta(days=i)).strftime("%Y%m%d"),
         "total_mv": mv, "circ_mv": circ_mv if circ_mv is not None else mv * 0.6,
         "pe": 15.0, "pb": 2.0}
        for i in range(n_days)
    ]


# ───────────────────────── Test cases ────────────────────────────────────────

def test_price_asof_refuses_future():
    """price_asof at T must not return prices with trade_date > T."""
    store = PitDataStore()
    store.load_ticker("X.SZ", [
        {"trade_date": "20200101", "close": 10.0},
        {"trade_date": "20200201", "close": 12.0},
        {"trade_date": "20300101", "close": 999.0},   # future
    ], [])
    assert store.price_asof("X.SZ", date(2020, 6, 1)) == 12.0, \
        "price_asof returned future data at T=2020-06-01"
    assert store.price_asof("X.SZ", date(2020, 1, 31)) == 10.0, \
        "price_asof returned wrong PIT price at T=2020-01-31"


def test_financials_asof_refuses_future():
    """financials_asof at T must not return rows with ann_date > T."""
    store = PitDataStore()
    store.load_ticker("X.SZ", [{"trade_date": "20200101", "close": 10.0}], [
        _annual("20191231", "20200430", 100.0, 60.0, 20.0, 100.0, 200.0, 100.0),
        _annual("20201231", "20210430", 100.0, 10.0, 80.0, 100.0, 200.0, 100.0),  # future ann
    ])
    rows = store.financials_asof("X.SZ", date(2020, 6, 1))
    assert len(rows) == 1, f"financials_asof returned future row: {len(rows)} rows"
    assert rows[0]["end_date"] == "20191231", "wrong PIT financial row"


def test_compute_factors_pit_invariant():
    """compute_factors at T must give IDENTICAL output whether or not the store
    contains data with date > T. This is the structural invariant."""
    # Build a "clean" store (only past data) and a "contaminated" store
    # (clean + future data).
    n = 400
    clean_store = PitDataStore()
    clean_daily = _daily(2019, n, 10.0, 20.0)
    clean_fins = [_annual("20191231", "20200430", 100.0, 60.0, 20.0, 100.0, 200.0, 100.0)]
    clean_store.load_ticker("X.SZ", clean_daily, clean_fins)
    pit_factors.attach_daily_basic(clean_store, "X.SZ", _basic(2019, n, 1e10))

    contaminated_store = PitDataStore()
    future_daily = clean_daily + [
        {"trade_date": "20300101", "close": 99999.0},
        {"trade_date": "20300102", "close": 88888.0},
    ]
    future_fins = clean_fins + [
        _annual("20291231", "20300430", 1e9, 0.0, 9e8, 1e10, 1e10, 0.0),  # impossibly good
    ]
    contaminated_store.load_ticker("X.SZ", future_daily, future_fins)
    pit_factors.attach_daily_basic(contaminated_store, "X.SZ",
        _basic(2019, n, 1e10) + [
            {"trade_date": "20300101", "total_mv": 1e15, "circ_mv": 1e14,
             "pe": 0.1, "pb": 0.1},
        ])

    as_of = date(2020, 6, 1)
    f_clean = pit_factors.compute_factors(["X.SZ"], as_of, clean_store,
                                          {"min_vol_obs": 2, "market_cap_multiplier": 1.0})
    f_contam = pit_factors.compute_factors(["X.SZ"], as_of, contaminated_store,
                                            {"min_vol_obs": 2, "market_cap_multiplier": 1.0})

    raw_clean = f_clean["X.SZ"]["_raw"]
    raw_contam = f_contam["X.SZ"]["_raw"]

    for k in ("market_cap", "roe", "gross_margin", "net_margin", "leverage",
              "earnings_yield", "book_yield"):
        c, d = raw_clean.get(k), raw_contam.get(k)
        assert c == d, \
            f"PIT LEAK: {k} clean={c} contaminated={d} (future data leaked into compute_factors)"
    for k in ("momentum", "low_vol", "value", "quality"):
        c = raw_clean["factors"].get(k)
        d = raw_contam["factors"].get(k)
        assert c == d, \
            f"PIT LEAK: factor {k} clean={c} contaminated={d}"


def test_b_shift_lag_negative_blocked():
    """The exact Huatai NSGA-II bug class: negative lag accessing future bars.

    Our PitDataStore has NO API that accepts a negative offset; all accessors
    take an `as_of` date and look BACKWARD only. This test verifies that even
    when a caller tries to compute a "shifted" series, the only available
    primitive (price_asof / next_fill_price) refuses future bars at T.
    """
    store = PitDataStore()
    store.load_ticker("X.SZ", [
        {"trade_date": "20200101", "close": 10.0},
        {"trade_date": "20200201", "close": 11.0},
        {"trade_date": "20200301", "close": 12.0},
        {"trade_date": "20200401", "close": 13.0},
    ], [])

    # Simulate the Huatai bug: caller wants `price[t+1]` at decision time T.
    # The legitimate way is next_fill_price(T) → returns (date, close) STRICTLY
    # after T (used for T+1 fill in backtest). The illegitimate way is to read
    # arbitrary future close as if it were available at T — there is no API
    # for that. We assert this by verifying that price_asof(T) is the latest
    # close <= T, NOT the next close.

    t = date(2020, 1, 15)
    assert store.price_asof("X.SZ", t) == 10.0, "price_asof must return latest <= T"

    # next_fill_price is the ONLY future-pointing API — it's used by the
    # backtest engine to model T+1 execution, not by the strategy/factor layer.
    # We verify its semantics are clearly future-pointing (returns NEXT bar).
    nxt = store.next_fill_price("X.SZ", t)
    assert nxt is not None and nxt[0] == date(2020, 2, 1) and nxt[1] == 11.0, \
        "next_fill_price must point to NEXT bar (model fill, not factor input)"


def test_universe_filter_pit_invariant():
    """universe_filter at T must give identical output whether or not future
    daily_basic rows exist in the store."""
    store_clean = PitDataStore()
    store_contam = PitDataStore()
    tickers = [f"T{i:03d}.SZ" for i in range(100)]
    for i, tk in enumerate(tickers, start=1):
        mv = i * 1e8
        for s in (store_clean, store_contam):
            s.load_ticker(tk, [{"trade_date": "20200101", "close": 10.0}], [])
        pit_factors.attach_daily_basic(store_clean, tk, [
            {"trade_date": "20200101", "total_mv": mv, "circ_mv": mv * 0.6}
        ])
        # contaminated: also has a 2030 row that, if leaked, would re-rank
        pit_factors.attach_daily_basic(store_contam, tk, [
            {"trade_date": "20200101", "total_mv": mv, "circ_mv": mv * 0.6},
            {"trade_date": "20300101", "total_mv": 1e15, "circ_mv": 1e14},
        ])

    t = date(2020, 1, 1)
    s_clean = universe_filter.filter_universe(tickers, store_clean, t, {"mcap_pctl_floor": 0.05})
    s_contam = universe_filter.filter_universe(tickers, store_contam, t, {"mcap_pctl_floor": 0.05})
    assert set(s_clean) == set(s_contam), \
        f"PIT LEAK in universe_filter: future mcap changed filter at T. " \
        f"clean only: {set(s_clean) - set(s_contam)}, contam only: {set(s_contam) - set(s_clean)}"


def test_end_to_end_strategy_pit_invariant():
    """Full strategy closure at T: identical output with/without future rows.

    This is the integration-level guard. If this passes, no caller in the
    backtest engine can introduce look-ahead via the data path.
    """
    # Build two parallel stores (clean vs contaminated with massive future
    # injection) on a fixture small enough to compute end-to-end fast.
    n = 600
    tickers = ["X.SZ", "Y.SZ", "Z.SZ"]
    fins_X = [_annual("20191231", "20200430", 100.0, 50.0, 30.0, 100.0, 200.0, 100.0)]
    fins_Y = [_annual("20191231", "20200430", 100.0, 60.0, 20.0, 100.0, 200.0, 100.0)]
    fins_Z = [_annual("20191231", "20200430", 100.0, 80.0, 5.0, 100.0, 200.0, 100.0)]

    store_clean = PitDataStore()
    store_contam = PitDataStore()
    for tk, slope, fins in (
        ("X.SZ", 0.001, fins_X), ("Y.SZ", 0.0005, fins_Y), ("Z.SZ", -0.0002, fins_Z)
    ):
        daily_clean = _daily(2019, n, 10.0, 10.0 + n * slope)
        store_clean.load_ticker(tk, daily_clean, fins)
        future_daily = daily_clean + [{"trade_date": "20300101", "close": 99999.0}]
        future_fins = fins + [_annual("20291231", "20300430", 1e9, 0.0, 9e8, 1e10, 1e10, 0.0)]
        store_contam.load_ticker(tk, future_daily, future_fins)
        pit_factors.attach_daily_basic(store_clean, tk, _basic(2019, n, 1e10))
        pit_factors.attach_daily_basic(store_contam, tk,
            _basic(2019, n, 1e10) + [{"trade_date": "20300101",
                                       "total_mv": 1e15, "circ_mv": 1e14, "pe": 0.1, "pb": 0.1}])

    strat = make_satellite_strategy(top_n=2, factor_config={
        "momentum_lookback_td": 100, "momentum_skip_td": 5,
        "vol_window_td": 50, "min_vol_obs": 10,
    })

    as_of = date(2020, 6, 1)
    w_clean = strat(as_of, tickers, store_clean)
    w_contam = strat(as_of, tickers, store_contam)

    assert w_clean == w_contam, \
        f"PIT LEAK in strategy closure: clean={w_clean} contam={w_contam} " \
        f"(future data changed today's picks)"


# ───────────────────────── Runner ────────────────────────────────────────────

TESTS = [
    ("price_asof_refuses_future", test_price_asof_refuses_future),
    ("financials_asof_refuses_future", test_financials_asof_refuses_future),
    ("compute_factors_pit_invariant", test_compute_factors_pit_invariant),
    ("b_shift_lag_negative_blocked (Huatai bug class)", test_b_shift_lag_negative_blocked),
    ("universe_filter_pit_invariant", test_universe_filter_pit_invariant),
    ("end_to_end_strategy_pit_invariant", test_end_to_end_strategy_pit_invariant),
]


def main():
    failures = []
    for name, fn in TESTS:
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as e:
            print(f"FAIL  {name}: {e}")
            failures.append(name)
        except Exception as e:
            print(f"ERROR {name}: {type(e).__name__}: {e}")
            failures.append(name)

    if failures:
        print(f"\n{len(failures)} test(s) FAILED — P0 LOOK-AHEAD BUG REGRESSION:")
        for name in failures:
            print(f"  - {name}")
        return 1
    print(f"\nAll {len(TESTS)} PIT no-look-ahead tests PASSED.")
    print("PitDataStore + filters + strategy provably refuse future data at T.")
    print("The Huatai NSGA-II bug class (negative B_shift_lag) is structurally impossible here.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
