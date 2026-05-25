#!/usr/bin/env python3
"""run_universe_backtest.py — load parquet panel → PitDataStore → real backtest.

The ② orchestrator (T1). Wires the proven pieces into the run that produces the
FIRST REAL backtest number:
  data_history/panel/{prices,financials}.parquet  (from fetch_universe_history.py, GHA)
    -> load_panel(): per-ticker PitDataStore + daily_basic attach + PitUniverse
    -> backtest_v2.run_backtest(satellite_strategy) over the full window
    -> public/data/backtest_results_v2.json (equity, CAGR/Sharpe/MaxDD, per-regime)

Honesty: this script does NOT fabricate. Without a real parquet panel it does
nothing but --selftest (synthetic panel). The real number only appears when run
on the GHA-fetched full-universe panel. Whatever CAGR comes out is reported as-is.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pit_factors  # noqa: E402
from backtest_v2 import PitDataStore, PitUniverse, run_backtest, REGIMES  # noqa: E402
from satellite_strategy import make_satellite_strategy  # noqa: E402

PANEL_DIR = REPO_ROOT / "data_history" / "panel"

# financials columns threaded into store fin_rows (income + balancesheet merged)
FIN_COLS = ["ann_date", "f_ann_date", "end_date", "revenue", "oper_cost",
            "n_income", "n_income_attr_p", "total_hldr_eqy_exc_min_int",
            "total_assets", "total_liab"]
DB_COLS = ["trade_date", "total_mv", "circ_mv", "pe", "pb"]


def load_panel(prices_path: Path, financials_path: Path,
               universe_path: Path | None) -> tuple[PitDataStore, PitUniverse]:
    """Build a PitDataStore + PitUniverse from the columnar parquet panel."""
    prices = pd.read_parquet(prices_path)
    fins = pd.read_parquet(financials_path) if Path(financials_path).exists() else pd.DataFrame()
    store = PitDataStore()

    fin_by = {tk: g for tk, g in fins.groupby("ts_code")} if len(fins) else {}
    for tk, g in prices.groupby("ts_code"):
        daily_rows = [{"trade_date": r.trade_date, "close": r.close}
                      for r in g.itertuples(index=False)]
        fg = fin_by.get(tk)
        fin_rows = []
        if fg is not None:
            for r in fg.itertuples(index=False):
                fin_rows.append({c: getattr(r, c, None) for c in FIN_COLS if hasattr(r, c)})
        store.load_ticker(tk, daily_rows, fin_rows)
        # attach daily_basic (total_mv etc.) for the value factor (pit_factors API)
        db_rows = [{c: getattr(r, c, None) for c in DB_COLS if hasattr(r, c)}
                   for r in g.itertuples(index=False)]
        pit_factors.attach_daily_basic(store, tk, db_rows)

    # universe (survivorship-safe): prefer universe_pit.json; else derive from panel
    if universe_path and Path(universe_path).exists():
        uni_raw = json.load(open(universe_path)).get("stocks", [])
    else:
        uni_raw = [{"ts_code": tk, "list_date": None, "delist_date": None}
                   for tk in prices["ts_code"].unique()]
    universe = PitUniverse(uni_raw)
    return store, universe


def _regime_breakdown(res) -> dict:
    """Equity return within each named A-share regime window (per-scenario stress)."""
    out = {}
    dates = res.rebalance_dates
    eq = res.equity
    for name, (a, b) in REGIMES.items():
        idx = [i for i, d in enumerate(dates) if a <= d <= b]
        if len(idx) >= 2:
            out[name] = round(eq[idx[-1]] / eq[idx[0]] - 1.0, 4)
    return out


def run(prices_path: Path, financials_path: Path, universe_path: Path | None,
        out_path: Path, start: date, end: date) -> dict:
    store, universe = load_panel(prices_path, financials_path, universe_path)
    strat = make_satellite_strategy()
    res = run_backtest(store, universe, start, end, strat)
    results = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "engine": "backtest_v2 + satellite_strategy + pit_factors",
            "window": [start.isoformat(), end.isoformat()],
            "rebalances": len(res.rebalance_dates),
            "honesty": "real number from real data; NOT curve-fit. Whatever it is, it is.",
        },
        "cagr": res.cagr,
        "sharpe": res.sharpe,
        "max_drawdown": res.max_drawdown,
        "final_equity": res.equity[-1] if res.equity else None,
        "per_regime_return": _regime_breakdown(res),
        "equity_curve": [{"date": d.isoformat(), "equity": round(e, 5)}
                         for d, e in zip(res.rebalance_dates, res.equity)],
        "turnover_sample": res.trade_log[-12:],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    return results


def _selftest() -> int:
    """End-to-end on a SYNTHETIC parquet panel: proves load→factors→backtest, and
    that value/quality now COMPUTE (non-None) because total_mv + balancesheet are
    threaded (the gap the earlier fixture left open)."""
    import tempfile
    failures = []
    tmp = Path(tempfile.mkdtemp())
    # 4 stocks, ~3yr daily, differing trends + ROE/margin + market cap
    specs = {"AAA.SZ": (10, 0.0010, 0.22, 0.45, 8e9), "BBB.SZ": (20, 0.0006, 0.15, 0.30, 2e10),
             "CCC.SZ": (15, 0.0001, 0.08, 0.18, 5e10), "DDD.SZ": (30, -0.0003, 0.04, 0.10, 1e11)}
    prows, frows = [], []
    base = date(2021, 1, 1)
    for tk, (p0, slope, roe, gm, mv) in specs.items():
        for i in range(760):
            d = base.toordinal() + i
            dd = date.fromordinal(d).strftime("%Y%m%d")
            px = round(p0 * (1 + slope) ** i, 3)
            prows.append({"ts_code": tk, "trade_date": dd, "close": px,
                          "adj_factor": 1.0, "total_mv": mv / 1e4, "circ_mv": mv / 1e4,
                          "pe": 15.0, "pb": 2.0})
        for ann, end_d, rev in (("20220415", "20211231", 100), ("20230415", "20221231", 120)):
            frows.append({"ts_code": tk, "ann_date": ann, "f_ann_date": ann, "end_date": end_d,
                          "revenue": rev * 1e7, "oper_cost": rev * 1e7 * (1 - gm),
                          "n_income": rev * 1e7 * roe * 0.5, "n_income_attr_p": rev * 1e7 * roe * 0.5,
                          "total_hldr_eqy_exc_min_int": 1e9, "total_assets": 2e9, "total_liab": 1e9})
    pp, fp = tmp / "prices.parquet", tmp / "financials.parquet"
    pd.DataFrame(prows).to_parquet(pp)
    pd.DataFrame(frows).to_parquet(fp)

    store, uni = load_panel(pp, fp, None)
    # value + quality must now be NON-None (total_mv + balancesheet threaded)
    f = pit_factors.compute_factors(list(specs), date(2023, 6, 1), store)
    aaa = f.get("AAA.SZ", {})
    if aaa.get("quality") is None:
        failures.append("quality is None after loader (balancesheet not threaded)")
    if aaa.get("value") is None:
        failures.append("value is None after loader (total_mv not threaded)")
    # full backtest runs + produces a curve
    res = run(pp, fp, None, tmp / "out.json", date(2023, 1, 1), date(2023, 9, 1))
    if not res.get("equity_curve"):
        failures.append("no equity curve from end-to-end run")
    if res.get("cagr") is None:
        failures.append("CAGR None (engine didn't run on panel)")

    if failures:
        print("SELFTEST FAILED run_universe_backtest:")
        for x in failures:
            print("  -", x)
        return 1
    print("SELFTEST PASSED run_universe_backtest")
    print("- parquet panel -> PitDataStore loads (price + daily_basic + financials)")
    print("- value + quality factors now COMPUTE non-None (total_mv + balancesheet threaded)")
    print("- end-to-end load -> pit_factors -> satellite_strategy -> backtest produces equity + CAGR")
    print(f"(synthetic CAGR={res.get('cagr')} — FIXTURE ONLY, not a real number)")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Load parquet panel and run the real backtest.")
    p.add_argument("--prices", default=str(PANEL_DIR / "prices.parquet"))
    p.add_argument("--financials", default=str(PANEL_DIR / "financials.parquet"))
    p.add_argument("--universe", default=str(REPO_ROOT / "data_history" / "universe_pit.json"))
    p.add_argument("--out", default=str(REPO_ROOT / "public" / "data" / "backtest_results_v2.json"))
    p.add_argument("--start", default="20060101")
    p.add_argument("--end", default=date.today().strftime("%Y%m%d"))
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()

    def _d(s): return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    if not Path(args.prices).exists():
        print(f"ERROR: {args.prices} missing — run fetch_universe_history.py (GHA) first.", file=sys.stderr)
        return 1
    res = run(Path(args.prices), Path(args.financials),
              Path(args.universe) if Path(args.universe).exists() else None,
              Path(args.out), _d(args.start), _d(args.end))
    print(f"REAL BACKTEST: CAGR={res['cagr']} Sharpe={res['sharpe']} MaxDD={res['max_drawdown']} "
          f"final_equity={res['final_equity']} rebalances={res['_meta']['rebalances']}")
    print(f"per-regime: {res['per_regime_return']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
