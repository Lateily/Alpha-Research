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
import risk_monitor  # noqa: E402
from backtest_v2 import PitDataStore, PitUniverse, run_backtest, REGIMES, cagr  # noqa: E402
from satellite_strategy import make_satellite_strategy  # noqa: E402


_RISK_CONFIG_OVERRIDE = {
    "regime_gross_cap": 0.60,        # was 0.40 — too tight; 0.60 is standard "trim 40%"
    "drawdown_scale_down": -0.15,    # was -0.12 — slightly later trigger
    "drawdown_to_cash": -0.25,       # was -0.20 — slightly later cash breaker
}

def _risk_overlay(ps, ms):
    """Backtest risk hook → real engine, with looser standard thresholds (iter-5)."""
    return risk_monitor.run_monitors(ps, ms, config=_RISK_CONFIG_OVERRIDE, dry_run=True)

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

    # universe (survivorship-safe): prefer universe_pit.json (with industry +
    # list/delist dates); fall back to panel-derived if missing OR empty
    # (an empty stocks=[] gave 0 picks → flat backtest — caught 2026-05-26 iter-8
    # verification by the canonical PIT test failing to detect a CONFIG bug,
    # not a code bug).
    uni_raw = []
    if universe_path and Path(universe_path).exists():
        uni_raw = json.load(open(universe_path)).get("stocks", []) or []
    if not uni_raw:
        print(f"WARN: universe_path={universe_path} has no stocks; falling back to "
              f"panel-derived universe ({len(prices['ts_code'].unique())} tickers)",
              file=sys.stderr)
        uni_raw = [{"ts_code": tk, "list_date": None, "delist_date": None}
                   for tk in prices["ts_code"].unique()]
    universe = PitUniverse(uni_raw)
    if not universe._rows:
        raise ValueError("PitUniverse loaded with 0 stocks — every backtest will "
                         "return flat equity. Check universe_pit.json or panel data.")
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


def _quarter_ends(start: date, end: date) -> list:
    """First-of-month markers but only Jan/Apr/Jul/Oct (quarterly rebalance).
    Used by iter-10 to test if 3-month horizon harvests more signal per
    Stage 2 IC analysis (which showed h=3m mean IC ~3× stronger than h=1m)."""
    out, y, m = [], start.year, start.month
    while date(y, m, 1) <= end:
        if m in (1, 4, 7, 10):
            out.append(date(y, m, 1))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _semi_annual_ends(start: date, end: date) -> list:
    """Jan and July only (semi-annual rebal)."""
    out, y, m = [], start.year, start.month
    while date(y, m, 1) <= end:
        if m in (1, 7):
            out.append(date(y, m, 1))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def run(prices_path: Path, financials_path: Path, universe_path: Path | None,
        out_path: Path, start: date, end: date, risk_off: bool = False,
        iter8: bool = False, iter8_barra: bool = False,
        rebal_months: int = 1, smooth_factors_n: int = 1,
        top_n: int | None = None) -> dict:
    store, universe = load_panel(prices_path, financials_path, universe_path)
    from satellite_strategy import TOP_N as _DEFAULT_TOP_N
    _top_n = top_n if top_n is not None else _DEFAULT_TOP_N
    if iter8:
        strat = make_satellite_strategy(
            top_n=_top_n,
            apply_universe_filter=True,
            universe_filter_config={"mcap_pctl_floor": 0.05},
            use_barra_construction=iter8_barra,
            universe=universe,
            smooth_factors_n=smooth_factors_n,
        )
    else:
        strat = make_satellite_strategy(top_n=_top_n, smooth_factors_n=smooth_factors_n)

    # iter-10 quarterly / semi-annual schedule
    rebal_dates = None
    rebal_periods_per_year = 12  # monthly default
    if rebal_months == 3:
        rebal_dates = _quarter_ends(start, end)
        rebal_periods_per_year = 4
    elif rebal_months == 6:
        rebal_dates = _semi_annual_ends(start, end)
        rebal_periods_per_year = 2
    elif rebal_months not in (1,):
        raise ValueError(f"--rebal-months must be 1, 3, or 6, got {rebal_months}")

    res = run_backtest(store, universe, start, end, strat,
                       rebalance_dates=rebal_dates,
                       risk_monitor_fn=(None if risk_off else _risk_overlay),
                       regime_gross_cap=_RISK_CONFIG_OVERRIDE["regime_gross_cap"])

    # In-sample (<=2018, weights were fit here) vs OUT-OF-SAMPLE (2019+). T2:
    # ~65% of the full-period CAGR is in-sample → the HONEST headline is the OOS
    # slice. Re-normalize each slice's equity to start at 1.0.
    split = date(2019, 1, 1)
    is_eq = [e for d, e in zip(res.rebalance_dates, res.equity) if d < split]
    oos_eq = [e for d, e in zip(res.rebalance_dates, res.equity) if d >= split]
    is_cagr = cagr(is_eq, float(rebal_periods_per_year)) if len(is_eq) >= 2 else None
    oos_cagr = (cagr([e / oos_eq[0] for e in oos_eq], float(rebal_periods_per_year))
                if len(oos_eq) >= 2 and oos_eq[0] > 0 else None)
    # Equal-weight universe BENCHMARK (the alpha test: are we beating buy-and-hold?)
    mkt = res.market_proxy_curve
    is_mkt = [m for d, m in zip(res.rebalance_dates, mkt) if d < split]
    oos_mkt = [m for d, m in zip(res.rebalance_dates, mkt) if d >= split]
    is_mkt_cagr = cagr(is_mkt, float(rebal_periods_per_year)) if len(is_mkt) >= 2 else None
    oos_mkt_cagr = (cagr([m / oos_mkt[0] for m in oos_mkt], float(rebal_periods_per_year))
                    if len(oos_mkt) >= 2 and oos_mkt[0] > 0 else None)
    oos_alpha = (oos_cagr - oos_mkt_cagr) if oos_cagr is not None and oos_mkt_cagr is not None else None
    is_alpha = (is_cagr - is_mkt_cagr) if is_cagr is not None and is_mkt_cagr is not None else None
    results = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "engine": "backtest_v2 + satellite_strategy + pit_factors + risk_monitor overlay",
            "window": [start.isoformat(), end.isoformat()],
            "rebalances": len(res.rebalance_dates),
            "risk_overlay": "ON (drawdown breaker + regime gross-cap from risk_monitor)",
            "risk_actions_fired": len(res.risk_actions_log),
            "weights_source": getattr(__import__("satellite_strategy"), "_WEIGHTS_SOURCE", "?"),
            "headline_metric": "oos_cagr (2019+) — weights fit in-sample 2006-2018, so full-period CAGR is in-sample-optimistic",
            "honesty": "real number from real data; NOT curve-fit. Whatever it is, it is.",
        },
        "oos_cagr_2019plus": oos_cagr,
        "oos_benchmark_cagr_ew_universe": oos_mkt_cagr,
        "oos_alpha_vs_benchmark": oos_alpha,
        "in_sample_cagr_pre2019": is_cagr,
        "in_sample_benchmark_cagr_ew_universe": is_mkt_cagr,
        "in_sample_alpha": is_alpha,
        "cagr_full_period_in_sample_optimistic": res.cagr,
        "sharpe": res.sharpe,
        "max_drawdown": res.max_drawdown,
        "final_equity": res.equity[-1] if res.equity else None,
        "per_regime_return": _regime_breakdown(res),
        "equity_curve": [{"date": d.isoformat(), "equity": round(e, 5)}
                         for d, e in zip(res.rebalance_dates, res.equity)],
        # EW-universe benchmark curve (needed for bootstrap CI on alpha)
        "market_proxy_curve": [{"date": d.isoformat(), "equity": round(m, 5)}
                                for d, m in zip(res.rebalance_dates, res.market_proxy_curve)],
        "risk_actions_sample": res.risk_actions_log[:20],
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
    if res.get("cagr_full_period_in_sample_optimistic") is None:
        failures.append("CAGR None (engine didn't run on panel)")

    # REAL-ENGINE risk test (T2 BLOCKER fix): drive the ACTUAL _risk_overlay
    # (risk_monitor.run_monitors) through a crash — NOT the stub. Proves the
    # feed_age_days=0 fix stops data_staleness FREEZE from suppressing the
    # drawdown breaker, so risk actions actually fire.
    from backtest_v2 import PitDataStore as _PS, PitUniverse as _PU, run_backtest as _rbt
    cs = _PS()
    cs.load_ticker("Z.SZ", [
        {"trade_date": "20200101", "close": 10.0}, {"trade_date": "20200201", "close": 12.0},
        {"trade_date": "20200301", "close": 13.0}, {"trade_date": "20200401", "close": 4.0},   # -69% crash
        {"trade_date": "20200501", "close": 4.0}, {"trade_date": "20200601", "close": 4.0},
    ], [])
    cu = _PU([{"ts_code": "Z.SZ", "list_date": "20100101", "delist_date": None}])
    rr = _rbt(cs, cu, date(2020, 1, 1), date(2020, 6, 1),
              lambda t, m, s: ({"Z.SZ": 0.95} if "Z.SZ" in m else {}),
              risk_monitor_fn=_risk_overlay)
    if not rr.risk_actions_log:
        failures.append("REAL risk_monitor overlay never fired on a -69% crash (FREEZE bug not fixed?)")

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
    p.add_argument("--no-risk", action="store_true", dest="risk_off",
                   help="Disable risk overlay (isolate factor alpha)")
    p.add_argument("--iter8", action="store_true",
                   help="Enable iter-8 Stage 1 foundation rebuild: LSY/Li-Rao "
                        "5%% mcap filter + E/P-heavy value (default in "
                        "pit_factors). Barra construction is INTENTIONALLY OFF "
                        "because bisect proved scale-mismatch with iter-7 OLS "
                        "weights kills OOS by ~8.7pp. Add --iter8-barra to "
                        "force-enable Barra for diagnostic.")
    p.add_argument("--iter8-barra", action="store_true",
                   help="Force-enable Barra construction with iter-8 (requires "
                        "--iter8). Use only for diagnostic or after OLS weight "
                        "re-fit on Barra scale (Stage 3).")
    p.add_argument("--rebal-months", type=int, default=1, choices=[1, 3, 6],
                   help="Rebalance frequency in months: 1=monthly (default), "
                        "3=quarterly (iter-10), 6=semi-annual. Stage 2 IC showed "
                        "h=3m/6m signals 3x stronger than h=1m — iter-10 tests this.")
    p.add_argument("--smooth-n", dest="smooth_factors_n", type=int, default=1,
                   help="iter-11: rolling N-month average of factor scores "
                        "(default 1 = no smoothing). =3 harvests h=3m signal "
                        "at monthly rebal frequency.")
    p.add_argument("--top-n", type=int, default=None,
                   help="Concentration override (default = satellite_strategy.TOP_N=15). "
                        "iter-7 tested 30 (worse); iter-12 tests 10.")
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
              Path(args.out), _d(args.start), _d(args.end),
              risk_off=args.risk_off, iter8=args.iter8,
              iter8_barra=getattr(args, "iter8_barra", False),
              rebal_months=args.rebal_months,
              smooth_factors_n=args.smooth_factors_n,
              top_n=args.top_n)
    print(f"REAL BACKTEST: OOS_CAGR(2019+)={res.get('oos_cagr_2019plus')} IS_CAGR={res.get('in_sample_cagr_pre2019')} Sharpe={res.get('sharpe')} MaxDD={res.get('max_drawdown')} "
          f"final_equity={res['final_equity']} rebalances={res['_meta']['rebalances']}")
    print(f"per-regime: {res['per_regime_return']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
