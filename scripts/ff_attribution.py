#!/usr/bin/env python3
"""ff_attribution.py — Fama-French style return attribution.

PURPOSE: decompose a strategy's monthly returns into a linear combination of
standard A-share style factors (market / SMB / HML / WML) + a residual α.
Answers: "how much of our +X% headline is just compensated factor exposure
(exotic beta) vs genuine active alpha?"

METHOD: at each month-end T, compute long-short factor portfolios from the
PIT panel:
  MKT   = equal-weighted universe excess return (vs hypothetical rf=0)
  SMB   = mean(bottom-30% mcap return) - mean(top-30% mcap return)
  HML   = mean(top-30% E/P return)     - mean(bottom-30% E/P return)
  WML   = mean(top-30% 12-1 momentum)  - mean(bottom-30% 12-1 momentum)

Then OLS regress strategy monthly returns on these 4 factors. Intercept α
is the unexplained "active alpha". β's quantify exotic-beta exposure.

PIT-clean: factor portfolios use price_asof at T and T+1, both within the
PIT contract.

CAVEAT: this is a single-period in-sample regression on ~240 observations.
The α point estimate has wide uncertainty. The bootstrap CI module
(stationary_bootstrap.py) provides honest inference.

OUTPUT: dict with alpha, beta_market, beta_smb, beta_hml, beta_wml, plus
R², factor monthly returns, and per-factor exposure significance (t-stats).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from bisect import bisect_right
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pit_factors                                              # noqa: E402
import universe_filter                                          # noqa: E402
from backtest_v2 import PitDataStore, PitUniverse, _month_ends  # noqa: E402


def _trading_day_at_offset_after(store, ticker, as_of, offset):
    dates = store._px_dates.get(ticker) or []
    idx = bisect_right(dates, as_of) + offset - 1
    if idx < 0 or idx >= len(dates):
        return None
    return dates[idx]


def _forward_1m(store, ticker, t):
    """Forward 1-month return (next bar after T)."""
    p0 = store.price_asof(ticker, t)
    if p0 is None or p0 <= 0:
        return None
    t1 = _trading_day_at_offset_after(store, ticker, t, 1)
    if t1 is None:
        return None
    p1 = store.price_asof(ticker, t1)
    if p1 is None or p1 <= 0:
        return None
    return p1 / p0 - 1.0


def _percentile_group(values_by_ticker: dict, low: float, high: float):
    """Return (bottom_tickers, top_tickers) by percentile of values."""
    finite = [(tk, v) for tk, v in values_by_ticker.items()
              if v is not None and math.isfinite(v)]
    finite.sort(key=lambda x: x[1])
    n = len(finite)
    if n < 10:
        return [], []
    lo_cut = int(n * low)
    hi_cut = int(n * high)
    bottom = [tk for tk, _ in finite[:lo_cut]]
    top = [tk for tk, _ in finite[hi_cut:]]
    return bottom, top


def compute_factor_returns(store: PitDataStore, universe: PitUniverse,
                            start: date, end: date,
                            *,
                            apply_universe_filter: bool = True,
                            universe_filter_config: dict | None = None,
                            quantile: float = 0.3) -> dict:
    """Build the 4-factor return time series (MKT/SMB/HML/WML).

    Returns dict of {factor_name: list[(date, monthly_return)]} keyed by month.
    """
    rdates = _month_ends(start, end)
    out = {"MKT": [], "SMB": [], "HML": [], "WML": []}

    for i in range(len(rdates) - 1):
        T = rdates[i]
        # Convention: forward 1-month return computed at T is the return EARNED
        # over [T, T+1m] = realized AT T+1m (T_next). Label it with the
        # CONTEMPORANEOUS date (T_next), matching the strategy's
        # equity_curve→returns convention (return at curve[i] is earned
        # over [curve[i-1], curve[i]]). Mislabeling here gave β_MKT ≈ 0 in
        # the previous run because strat and factor series were offset 1mo.
        T_next = rdates[i + 1]
        members = universe.members_asof(T)
        if apply_universe_filter:
            members = universe_filter.filter_universe(members, store, T,
                                                       universe_filter_config)
        if not members:
            continue

        # Forward 1-month returns for all members
        fwd = {}
        for tk in members:
            r = _forward_1m(store, tk, T)
            if r is not None and math.isfinite(r):
                fwd[tk] = r
        if len(fwd) < 30:
            continue

        # MKT = equal-weighted mean
        mkt_ret = sum(fwd.values()) / len(fwd)
        out["MKT"].append((T_next, mkt_ret))

        # Sort buckets by mcap, E/P, 12-1 momentum
        factor_data = pit_factors.compute_factors(
            list(fwd.keys()), T, store,
            {"momentum_lookback_td": 12, "momentum_skip_td": 1,
             "vol_window_td": 12, "min_vol_obs": 6},
        )

        mcap = {tk: factor_data.get(tk, {}).get("_raw", {}).get("market_cap")
                for tk in fwd}
        ep = {tk: factor_data.get(tk, {}).get("_raw", {}).get("earnings_yield")
              for tk in fwd}
        mom = {tk: factor_data.get(tk, {}).get("_raw", {}).get("factors", {}).get("momentum")
               for tk in fwd}

        # SMB = small mcap minus large mcap.
        # _percentile_group(low, high) returns (pctl<low, pctl>=high).
        # For bottom 30% small + top 30% large: call (quantile, 1-quantile).
        small, large = _percentile_group(mcap, quantile, 1 - quantile)
        if small and large:
            sm = sum(fwd[tk] for tk in small) / len(small)
            lg = sum(fwd[tk] for tk in large) / len(large)
            out["SMB"].append((T_next, sm - lg))

        # HML = high E/P minus low E/P
        low_ep, high_ep = _percentile_group(ep, quantile, 1 - quantile)
        if low_ep and high_ep:
            hi = sum(fwd[tk] for tk in high_ep) / len(high_ep)
            lo = sum(fwd[tk] for tk in low_ep) / len(low_ep)
            out["HML"].append((T_next, hi - lo))

        # WML = winners minus losers (12-1 momentum)
        losers, winners = _percentile_group(mom, quantile, 1 - quantile)
        if losers and winners:
            w = sum(fwd[tk] for tk in winners) / len(winners)
            l = sum(fwd[tk] for tk in losers) / len(losers)
            out["WML"].append((T_next, w - l))

    return out


def align_series(strat: list[tuple[date, float]],
                 factors: dict) -> tuple[list[date], np.ndarray, np.ndarray]:
    """Align strategy returns with factor returns by date. Returns (dates, X, y)."""
    by_date = {d: r for d, r in strat}
    common = sorted(set(by_date) & set(d for d, _ in factors.get("MKT", [])))
    factor_dicts = {k: dict(v) for k, v in factors.items()}
    rows = []
    ys = []
    dates_kept = []
    for d in common:
        row = []
        ok = True
        for f in ("MKT", "SMB", "HML", "WML"):
            v = factor_dicts.get(f, {}).get(d)
            if v is None:
                ok = False
                break
            row.append(v)
        if ok:
            rows.append(row)
            ys.append(by_date[d])
            dates_kept.append(d)
    return dates_kept, np.array(rows, dtype=float), np.array(ys, dtype=float)


def ols_attribution(X: np.ndarray, y: np.ndarray) -> dict:
    """OLS regress y on [1, X]. Return α (intercept), β's, R², t-stats."""
    n, k = X.shape
    if n < k + 5:
        return {"_status": "insufficient_obs", "n": n}
    design = np.column_stack([np.ones(n), X])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    yhat = design @ coef
    resid = y - yhat
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # SE via standard OLS formula (homoskedastic; not Newey-West — bootstrap
    # module provides robust inference if needed)
    df_resid = max(1, n - k - 1)
    sigma2 = ss_res / df_resid
    try:
        XtX_inv = np.linalg.inv(design.T @ design)
    except np.linalg.LinAlgError:
        XtX_inv = np.linalg.pinv(design.T @ design)
    se = np.sqrt(np.diag(XtX_inv) * sigma2)
    t_stats = coef / se

    return {
        "_status": "ok",
        "n_months": int(n),
        "intercept_alpha_monthly": float(coef[0]),
        "alpha_annualized": float((1 + coef[0]) ** 12 - 1),
        "alpha_t_stat": float(t_stats[0]),
        "beta_MKT": float(coef[1]),
        "beta_MKT_t": float(t_stats[1]),
        "beta_SMB": float(coef[2]),
        "beta_SMB_t": float(t_stats[2]),
        "beta_HML": float(coef[3]),
        "beta_HML_t": float(t_stats[3]),
        "beta_WML": float(coef[4]),
        "beta_WML_t": float(t_stats[4]),
        "r2": float(r2),
        "residual_std_monthly": float(math.sqrt(sigma2)),
    }


# ───────────────────────── Self-test ────────────────────────────────────────

def _selftest() -> int:
    failures = []

    # Synthetic: y = 0.005 + 1.2 * X1 + 0.3 * X2 + noise
    rng = np.random.default_rng(7)
    n = 200
    X = rng.normal(0, 0.05, size=(n, 4))
    y = 0.005 + 1.2 * X[:, 0] + 0.3 * X[:, 1] + 0.0 * X[:, 2] + 0.0 * X[:, 3] \
        + rng.normal(0, 0.02, size=n)
    res = ols_attribution(X, y)
    if res["_status"] != "ok":
        failures.append(f"OLS status: {res['_status']}")
    else:
        # α should be ~0.005
        if abs(res["intercept_alpha_monthly"] - 0.005) > 0.01:
            failures.append(f"α recovery: expected ~0.005, got {res['intercept_alpha_monthly']}")
        if abs(res["beta_MKT"] - 1.2) > 0.15:
            failures.append(f"β_MKT recovery: expected ~1.2, got {res['beta_MKT']}")
        if abs(res["beta_SMB"] - 0.3) > 0.15:
            failures.append(f"β_SMB recovery: expected ~0.3, got {res['beta_SMB']}")
        if res["r2"] < 0.5:
            failures.append(f"R² too low: {res['r2']}")

    if failures:
        print("SELFTEST FAILED ff_attribution:")
        for f in failures:
            print("  -", f)
        return 1
    print("SELFTEST PASSED ff_attribution")
    print("- OLS recovers intercept α + β's on a known generating process")
    print(f"  α={res['intercept_alpha_monthly']:.4f}  β_MKT={res['beta_MKT']:.3f} "
          f"β_SMB={res['beta_SMB']:.3f} R²={res['r2']:.3f}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Fama-French attribution.")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--strat", help="Strategy backtest result JSON")
    p.add_argument("--prices", default=str(REPO_ROOT / "data_history" / "panel" / "prices.parquet"))
    p.add_argument("--financials", default=str(REPO_ROOT / "data_history" / "panel" / "financials.parquet"))
    p.add_argument("--universe", default=str(REPO_ROOT / "data_history" / "universe_pit.json"))
    p.add_argument("--start", default="20060101")
    p.add_argument("--end", default=date.today().strftime("%Y%m%d"))
    p.add_argument("--out", default=str(REPO_ROOT / "public" / "data" / "ff_attribution.json"))
    p.add_argument("--no-filter", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()

    if not args.strat:
        print("ERROR: --strat required", file=sys.stderr); return 1

    from run_universe_backtest import load_panel
    store, universe = load_panel(Path(args.prices), Path(args.financials),
                                   Path(args.universe) if Path(args.universe).exists() else None)

    def _d(s): return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    print("Computing factor returns (MKT/SMB/HML/WML)...", flush=True)
    fr = compute_factor_returns(store, universe, _d(args.start), _d(args.end),
                                  apply_universe_filter=(not args.no_filter),
                                  universe_filter_config={"mcap_pctl_floor": 0.05})

    strat = json.load(open(args.strat))
    curve = strat.get("equity_curve", [])
    strat_rets = []
    for i in range(1, len(curve)):
        d = date.fromisoformat(curve[i]["date"])
        prev_eq = curve[i - 1]["equity"]
        cur_eq = curve[i]["equity"]
        if prev_eq > 0:
            strat_rets.append((d, cur_eq / prev_eq - 1.0))

    print(f"Strategy returns: {len(strat_rets)} months", flush=True)
    print(f"Factor returns:  MKT={len(fr['MKT'])} SMB={len(fr['SMB'])} "
          f"HML={len(fr['HML'])} WML={len(fr['WML'])}", flush=True)

    dates_kept, X, y = align_series(strat_rets, fr)
    print(f"Aligned: {len(dates_kept)} months", flush=True)

    res = ols_attribution(X, y)

    res["_meta"] = {
        "strat_input": args.strat,
        "window_aligned": [dates_kept[0].isoformat() if dates_kept else None,
                            dates_kept[-1].isoformat() if dates_kept else None],
        "n_factors": 4,
        "factors_used": ["MKT", "SMB", "HML", "WML"],
        "universe_filter": "LSY/Li-Rao 5% mcap floor" if not args.no_filter else "OFF",
        "method": "OLS with homoskedastic SEs; use stationary_bootstrap.py for robust CIs",
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2, ensure_ascii=False))

    print(f"\n=== FF Attribution (n={res.get('n_months')} months) ===")
    if res.get("_status") == "ok":
        print(f"  alpha (monthly):     {res['intercept_alpha_monthly']:+.4f}  t={res['alpha_t_stat']:+.3f}")
        print(f"  alpha (annualized):  {res['alpha_annualized']:+.4f}")
        print(f"  beta MKT: {res['beta_MKT']:+.3f}  t={res['beta_MKT_t']:+.2f}")
        print(f"  beta SMB: {res['beta_SMB']:+.3f}  t={res['beta_SMB_t']:+.2f}")
        print(f"  beta HML: {res['beta_HML']:+.3f}  t={res['beta_HML_t']:+.2f}")
        print(f"  beta WML: {res['beta_WML']:+.3f}  t={res['beta_WML_t']:+.2f}")
        print(f"  R² = {res['r2']:.3f}   residual σ monthly = {res['residual_std_monthly']:.4f}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
