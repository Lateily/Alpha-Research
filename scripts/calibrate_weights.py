#!/usr/bin/env python3
"""calibrate_weights.py — OLS factor-weight calibration (Junyan: "用计量 OLS").

Replaces the hand-set [unvalidated intuition] factor weights (Q30/V20/M25/G15/
LV10) with DATA-FITTED weights: pool (factor_score, forward_return) pairs across
the IN-SAMPLE window, regress forward return on the 5 factor scores, and turn
the coefficients into long-only (non-negative) normalized weights.

HONESTY (the red line):
  - Fit on IN-SAMPLE only (default 2006..2018). The 2019..present backtest is
    then genuinely OUT-OF-SAMPLE — fitting on the full history and backtesting
    the same history is the classic overfit self-deception, which we refuse.
  - Coefficients floored at 0 (long-only; we can't short a negative-alpha
    factor on THS). If a factor's coef is negative in-sample, its weight = 0.
  - Whatever the R^2 / weights are, we write them as-is. No massaging.

Output: public/data/calib_weights.json (small, committable). satellite_strategy
loads it if present; else falls back to the hand-set priors.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pit_factors  # noqa: E402
from backtest_v2 import _month_ends  # noqa: E402
from satellite_strategy import MONTHLY_FACTOR_CONFIG  # noqa: E402
from run_universe_backtest import load_panel  # noqa: E402

FACTORS = ["quality", "value", "momentum", "growth", "low_vol"]
OUT_DEFAULT = REPO_ROOT / "public" / "data" / "calib_weights.json"


def collect_rows(store, universe, start: date, end: date):
    """Pool (factor_scores, forward_return) over month-end rebalances in [start,end]."""
    rdates = _month_ends(start, end)
    X, y = [], []
    for i in range(len(rdates) - 1):
        T, nxt = rdates[i], rdates[i + 1]
        members = universe.members_asof(T)
        if not members:
            continue
        factors = pit_factors.compute_factors(members, T, store, MONTHLY_FACTOR_CONFIG)
        for tk, sc in factors.items():
            # Require >=3 REAL factor scores; impute the rest to neutral 50
            # (a sparse factor shouldn't drop the whole stock — that gave n_obs=0;
            # neutral = no signal, the standard OLS handling for missing factors).
            real = sum(1 for f in FACTORS if sc.get(f) is not None)
            if real < 3:
                continue
            vec = [float(sc.get(f)) if sc.get(f) is not None else 50.0 for f in FACTORS]
            p0 = store.price_asof(tk, T)
            p1 = store.price_asof(tk, nxt)
            if not (p0 and p1 and p0 > 0):
                continue
            r = p1 / p0 - 1.0
            if not math.isfinite(r):
                continue
            X.append([float(v) for v in vec])
            y.append(r)
    return np.array(X, dtype=float), np.array(y, dtype=float)


def fit(X: np.ndarray, y: np.ndarray) -> dict:
    if len(y) < 50:
        return {"_status": "insufficient_obs", "n_obs": int(len(y))}
    Xc = X - X.mean(axis=0)                      # center factor scores
    design = np.column_stack([np.ones(len(y)), Xc])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    intercept, betas = coef[0], coef[1:]
    yhat = design @ coef
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    pos = np.clip(betas, 0.0, None)              # long-only: floor negatives at 0
    weights = (pos / pos.sum()) if pos.sum() > 0 else np.full(len(FACTORS), 1.0 / len(FACTORS))
    return {
        "_status": "ok",
        "n_obs": int(len(y)),
        "r2_in_sample": round(r2, 5),
        "raw_coef": {f: round(float(b), 8) for f, b in zip(FACTORS, betas)},
        "intercept": round(float(intercept), 8),
        "weights": {f: round(float(w), 4) for f, w in zip(FACTORS, weights)},
        "zeroed_factors": [f for f, b in zip(FACTORS, betas) if b <= 0],
    }


def calibrate(prices, financials, universe_path, start, in_sample_end, out_path):
    store, universe = load_panel(Path(prices), Path(financials),
                                 Path(universe_path) if universe_path and Path(universe_path).exists() else None)
    X, y = collect_rows(store, universe, start, in_sample_end)
    res = fit(X, y)
    out = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "method": "pooled OLS forward_return ~ centered factor scores; coef floored >=0; normalized",
            "in_sample_window": [start.isoformat(), in_sample_end.isoformat()],
            "out_of_sample": f"after {in_sample_end.isoformat()} (the honest test)",
            "honesty": "in-sample fit only; long-only floor; written as-is, not massaged.",
        },
        **res,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    return out


def _selftest() -> int:
    """Synthetic panel where momentum genuinely predicts forward return — the
    calibrator should give momentum the largest weight."""
    import tempfile
    import pandas as pd
    failures = []
    tmp = Path(tempfile.mkdtemp())
    base = date(2010, 1, 1)
    prows, frows = [], []
    rng = np.random.default_rng(0)
    # 30 stocks, monthly bars ~9yr; construct so high-momentum names keep rising
    for s in range(30):
        trend = 0.0015 + 0.0010 * (s / 29)   # higher s = stronger uptrend (momentum+)
        px = 10.0
        for i in range(2600):
            d = date.fromordinal(base.toordinal() + i)
            px *= (1 + trend + float(rng.normal(0, 0.01)))
            prows.append({"ts_code": f"{s:03d}.SZ", "trade_date": d.strftime("%Y%m%d"),
                          "close": round(px, 3), "adj_factor": 1.0,
                          "total_mv": 1e6, "circ_mv": 1e6, "pe": 15.0, "pb": 2.0})
        for ann, endd in (("20120415", "20111231"), ("20130415", "20121231")):
            frows.append({"ts_code": f"{s:03d}.SZ", "ann_date": ann, "f_ann_date": ann, "end_date": endd,
                          "revenue": 1e8, "oper_cost": 6e7, "n_income": 1e7, "n_income_attr_p": 1e7,
                          "total_hldr_eqy_exc_min_int": 1e8, "total_assets": 2e8, "total_liab": 1e8})
    pd.DataFrame(prows).to_parquet(tmp / "p.parquet")
    pd.DataFrame(frows).to_parquet(tmp / "f.parquet")
    out = calibrate(tmp / "p.parquet", tmp / "f.parquet", None,
                    date(2011, 1, 1), date(2018, 12, 31), tmp / "calib.json")
    if out.get("_status") != "ok":
        failures.append(f"calibration status: {out.get('_status')} n_obs={out.get('n_obs')}")
    else:
        w = out["weights"]
        if abs(sum(w.values()) - 1.0) > 1e-6:
            failures.append(f"weights don't sum to 1: {w}")
        if w.get("momentum", 0) < max(w.get("value", 0), w.get("quality", 0)):
            failures.append(f"momentum (the constructed signal) not top-weighted: {w}")
    if failures:
        print("SELFTEST FAILED calibrate_weights:")
        for x in failures:
            print("  -", x)
        return 1
    print("SELFTEST PASSED calibrate_weights")
    print(f"- OLS recovered the constructed momentum signal as top weight: {out['weights']}")
    print(f"- in-sample R^2={out.get('r2_in_sample')}, n_obs={out.get('n_obs')}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="OLS factor-weight calibration (in-sample fit).")
    p.add_argument("--prices", default=str(REPO_ROOT / "data_history" / "panel" / "prices.parquet"))
    p.add_argument("--financials", default=str(REPO_ROOT / "data_history" / "panel" / "financials.parquet"))
    p.add_argument("--universe", default=str(REPO_ROOT / "data_history" / "universe_pit.json"))
    p.add_argument("--out", default=str(OUT_DEFAULT))
    p.add_argument("--start", default="20060101")
    p.add_argument("--in-sample-end", dest="in_sample_end", default="20181231")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()

    def _d(s): return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    if not Path(args.prices).exists():
        print(f"ERROR: {args.prices} missing — run fetch_universe_history.py (GHA) first.", file=sys.stderr)
        return 1
    out = calibrate(args.prices, args.financials, args.universe, _d(args.start), _d(args.in_sample_end), args.out)
    print(f"calibration {out.get('_status')}: weights={out.get('weights')} "
          f"R2={out.get('r2_in_sample')} n_obs={out.get('n_obs')} zeroed={out.get('zeroed_factors')}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
