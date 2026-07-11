#!/usr/bin/env python3
"""ic_analysis.py — Stage 2 IC analysis for the iter-8 IC backtest.

Computes cross-sectional Spearman rank correlation between each factor's
raw value and the forward return over multiple horizons, at each
month-end T. Then aggregates the time-series of IC into mean, t-stat,
ICIR (Information Coefficient Information Ratio = mean/std). Per the
textbook synthesis doc (research_2026-05-26/textbook_synthesis_lai.md
Section 2.8.5), the OUTPUT of this stage feeds into multiple-testing
correction (Stage 2b, scripts/multiple_testing.py).

WHY: pooled OLS R² = 0.001 in iter-1..7 — but pooled OLS does NOT give
proper time-series inference. Cross-sectional IC each month + time-series
t-stat is the institutional standard (Grinold & Kahn "Active Portfolio
Management"; Alphalens; MSCI Barra IC reports). It answers, for each
factor:
  - Mean IC: average rank-correlation between factor and forward return
  - t-stat: mean / (std / √n) under H0 that mean IC = 0
  - ICIR: mean / std — risk-adjusted IC ("how stable is the signal")
  - Decay across horizons: at what holding period does the signal peak/die

PIT DISCIPLINE: forward returns are computed via store.price_asof at T
and T+h. Both are bounded by the PIT contract (PitDataStore refuses any
data with trade_date > T+h). Look-ahead IS impossible by construction —
re-verified by tests/test_pit_no_look_ahead.py.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pit_factors          # noqa: E402
import universe_filter      # noqa: E402
from backtest_v2 import PitDataStore, PitUniverse   # noqa: E402


FACTORS = ("momentum", "low_vol", "value", "quality", "growth")
DEFAULT_HORIZONS_TD = (21, 63, 126, 252)   # trading days = roughly 1m / 3m / 6m / 12m
MIN_CROSS_SECTION = 100                    # require ≥ 100 paired obs per (T, factor, h)


def _spearman_rank(values: list[float]) -> list[float]:
    """Average-rank for ties; like scipy.stats.rankdata(method='average')."""
    n = len(values)
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-based rank
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank
        i = j + 1
    return ranks


def _pearson(x: list[float], y: list[float]) -> Optional[float]:
    n = len(x)
    if n < 2 or n != len(y):
        return None
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    vx = sum((x[i] - mx) ** 2 for i in range(n))
    vy = sum((y[i] - my) ** 2 for i in range(n))
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def spearman(x: list[float], y: list[float]) -> Optional[float]:
    """Spearman rank correlation, returns None on degenerate inputs."""
    if len(x) != len(y) or len(x) < 2:
        return None
    if not all(math.isfinite(v) for v in x) or not all(math.isfinite(v) for v in y):
        return None
    rx = _spearman_rank(x)
    ry = _spearman_rank(y)
    return _pearson(rx, ry)


def _trading_day_at_offset_after(store: PitDataStore, ticker: str,
                                  as_of: date, offset_td: int) -> Optional[date]:
    """Return the trade-date that is `offset_td` trading days AFTER as_of.

    "after" means strictly after, so this picks the (offset_td)th trading bar
    whose date > as_of. We DO NOT cross over future data — store will refuse
    if no such date exists at audit time.
    """
    dates = store._px_dates.get(ticker) or []
    idx = bisect_right(dates, as_of) + offset_td - 1
    if idx < 0 or idx >= len(dates):
        return None
    return dates[idx]


def forward_return(store: PitDataStore, ticker: str, t: date, horizon_td: int) -> Optional[float]:
    """Compute simple total return from close-of-T to close-of-(T+h trading days).

    PIT-clean: uses price_asof at both T and the future date; no centering,
    no smoothing — just two PIT-queried closes. If either is missing the
    function returns None (the pair is dropped from the cross-section).
    """
    p_t = store.price_asof(ticker, t)
    if p_t is None or p_t <= 0:
        return None
    t_future = _trading_day_at_offset_after(store, ticker, t, horizon_td)
    if t_future is None:
        return None
    p_th = store.price_asof(ticker, t_future)
    if p_th is None or p_th <= 0:
        return None
    return p_th / p_t - 1.0


def month_end_dates(start: date, end: date) -> list[date]:
    """First day of each month from start to end (matches backtest_v2 rebalance
    cadence)."""
    out = []
    y, m = start.year, start.month
    while True:
        d = date(y, m, 1)
        if d > end:
            break
        if d >= start:
            out.append(d)
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def compute_factor_ics(store: PitDataStore, universe: PitUniverse,
                       start: date, end: date,
                       *,
                       horizons_td: tuple = DEFAULT_HORIZONS_TD,
                       factor_config: dict | None = None,
                       apply_universe_filter: bool = True,
                       universe_filter_config: dict | None = None,
                       min_cross_section: int = MIN_CROSS_SECTION,
                       verbose: bool = False) -> dict:
    """Compute per-factor per-horizon IC time series across the window.

    Returns {(factor, horizon_td): list[(date, IC)]}.
    """
    fc = factor_config or {"momentum_lookback_td": 12, "momentum_skip_td": 1,
                            "vol_window_td": 12, "min_vol_obs": 6}
    rebals = month_end_dates(start, end)
    out = {(f, h): [] for f in FACTORS for h in horizons_td}

    for t in rebals:
        members = universe.members_asof(t)
        if apply_universe_filter:
            members = universe_filter.filter_universe(members, store, t,
                                                       universe_filter_config)
        if not members:
            continue

        # Factor RAW values per ticker (we use raw not percentile — IC is
        # invariant to monotone transform but raw is the canonical input)
        factor_table = pit_factors.compute_factors(members, t, store, fc)
        raw_by_factor: dict[str, dict[str, Optional[float]]] = {f: {} for f in FACTORS}
        for tk, info in factor_table.items():
            raw = info.get("_raw", {}).get("factors", {})
            for f in FACTORS:
                raw_by_factor[f][tk] = raw.get(f)

        # For each horizon, compute forward return and IC per factor
        for h in horizons_td:
            fwd = {}
            for tk in members:
                fr = forward_return(store, tk, t, h)
                if fr is not None and math.isfinite(fr):
                    fwd[tk] = fr
            if len(fwd) < min_cross_section:
                continue

            for f in FACTORS:
                xs = []
                ys = []
                for tk, fv in raw_by_factor[f].items():
                    fr = fwd.get(tk)
                    if fv is None or fr is None:
                        continue
                    if not math.isfinite(fv):
                        continue
                    xs.append(float(fv))
                    ys.append(float(fr))
                if len(xs) < min_cross_section:
                    continue
                ic = spearman(xs, ys)
                if ic is not None and math.isfinite(ic):
                    out[(f, h)].append((t, ic))

        if verbose and len(out[(FACTORS[0], horizons_td[0])]) % 12 == 0:
            print(f"  ...processed through {t.isoformat()}", flush=True)

    return out


def summarize_ic_series(series: list[tuple[date, float]]) -> dict:
    """Time-series statistics for an IC series."""
    if not series:
        return {"n": 0, "mean": None, "std": None, "t_stat": None,
                "icir": None, "min": None, "max": None}
    vals = [ic for _, ic in series]
    n = len(vals)
    mean = sum(vals) / n
    if n < 2:
        return {"n": n, "mean": mean, "std": None, "t_stat": None,
                "icir": None, "min": mean, "max": mean}
    std = statistics.stdev(vals)
    t_stat = mean / (std / math.sqrt(n)) if std > 0 else None
    icir = mean / std if std > 0 else None
    return {"n": n, "mean": mean, "std": std, "t_stat": t_stat,
            "icir": icir, "min": min(vals), "max": max(vals),
            "first": series[0][0].isoformat(), "last": series[-1][0].isoformat()}


# ───────────────────────── Self-test ────────────────────────────────────────

def _selftest() -> int:
    failures = []

    # 1) Spearman known values
    sp = spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1])
    if sp is None or abs(sp - (-1.0)) > 1e-9:
        failures.append(f"perfect inverse: expected -1, got {sp}")
    sp = spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
    if sp is None or abs(sp - 1.0) > 1e-9:
        failures.append(f"perfect direct: expected +1, got {sp}")
    sp = spearman([1, 2, 3, 4, 5], [3, 1, 4, 1, 5])
    if sp is None:
        failures.append("ties failed")

    # 2) Ranks
    ranks = _spearman_rank([10, 20, 30, 20])
    # 10→1, 20s tied at avg(2,3)=2.5, 30→4
    if ranks != [1.0, 2.5, 4.0, 2.5]:
        failures.append(f"tie rank wrong: {ranks}")

    # 3) Synthetic factor + return: high factor → high forward return
    import random
    random.seed(42)
    n = 200
    factors = [random.gauss(0, 1) for _ in range(n)]
    # forward return = 0.05 * factor + noise → moderate positive IC
    fwd = [0.05 * factors[i] + random.gauss(0, 0.10) for i in range(n)]
    ic = spearman(factors, fwd)
    if ic is None or ic < 0.10 or ic > 0.80:
        failures.append(f"signal IC out of expected band: {ic}")

    # 4) Summary statistics — series mean (m-6)*0.01 from m=1..12
    # = (-5,-4,-3,-2,-1,0,1,2,3,4,5,6) * 0.01 = sum 6 → mean 0.005
    series = [(date(2020, m, 1), (m - 6) * 0.01) for m in range(1, 13)]
    s = summarize_ic_series(series)
    if s["n"] != 12 or abs(s["mean"] - 0.005) > 1e-9:
        failures.append(f"summary mean wrong: {s}")
    if s["std"] is None or s["std"] <= 0:
        failures.append(f"summary std missing: {s}")

    # 5) PIT-clean forward return integration (synthetic)
    store = PitDataStore()
    base = date(2021, 1, 1)
    daily = [{"trade_date": (base + timedelta(days=i)).strftime("%Y%m%d"),
              "close": round(10.0 * 1.001 ** i, 4)} for i in range(60)]
    store.load_ticker("T.SZ", daily, [])
    fr = forward_return(store, "T.SZ", base + timedelta(days=10), 20)
    if fr is None or fr <= 0:
        failures.append(f"forward_return failed: {fr}")
    fr_too_far = forward_return(store, "T.SZ", base + timedelta(days=10), 200)
    if fr_too_far is not None:
        failures.append(f"forward_return should return None when no future bar: {fr_too_far}")

    if failures:
        print("SELFTEST FAILED ic_analysis:")
        for f in failures:
            print("  -", f)
        return 1
    print("SELFTEST PASSED ic_analysis")
    print("- Spearman correlation: ±1 endpoints + ties + signal recovery")
    print("- summarize: mean/std/t-stat/ICIR computed")
    print("- forward_return PIT-clean (returns None when no future bar)")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="IC analysis (Stage 2a).")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--prices", default=str(REPO_ROOT / "data_history" / "panel" / "prices.parquet"))
    p.add_argument("--financials", default=str(REPO_ROOT / "data_history" / "panel" / "financials.parquet"))
    p.add_argument("--universe", default=str(REPO_ROOT / "data_history" / "universe_pit.json"))
    p.add_argument("--start", default="20060101")
    p.add_argument("--end", default=date.today().strftime("%Y%m%d"))
    p.add_argument("--horizons", default="21,63,126,252")
    p.add_argument("--out", default=str(REPO_ROOT / "public" / "data" / "ic_analysis.json"))
    p.add_argument("--no-filter", action="store_true",
                   help="Disable LSY/Li-Rao universe filter (default ON for iter-8)")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()

    from run_universe_backtest import load_panel
    store, universe = load_panel(Path(args.prices), Path(args.financials),
                                   Path(args.universe) if Path(args.universe).exists() else None)

    def _d(s): return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    horizons = tuple(int(x) for x in args.horizons.split(","))

    print(f"Computing IC for factors={FACTORS} horizons={horizons} from {args.start} to {args.end}",
          flush=True)
    ics = compute_factor_ics(store, universe, _d(args.start), _d(args.end),
                              horizons_td=horizons,
                              apply_universe_filter=(not args.no_filter),
                              universe_filter_config={"mcap_pctl_floor": 0.05},
                              verbose=True)

    # Summarize per (factor, horizon)
    summary = {}
    for (f, h), series in ics.items():
        s = summarize_ic_series(series)
        summary[f"{f}@{h}d"] = s
        print(f"  {f:10s} h={h:3d}d  n={s['n']:3d}  mean={s['mean']:+.4f}  "
              f"t={s['t_stat']:+.3f}  ICIR={s['icir']:+.3f}"
              if s["n"] > 1 and s["t_stat"] is not None and s["icir"] is not None
              else f"  {f:10s} h={h:3d}d  n={s['n']:3d}  INSUFFICIENT",
              flush=True)

    out = {
        "_meta": {
            "generated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat(),
            "window": [args.start, args.end],
            "horizons_td": list(horizons),
            "min_cross_section": MIN_CROSS_SECTION,
            "universe_filter": "LSY/Li-Rao 5% mcap floor" if not args.no_filter else "OFF",
            "honesty": "raw spearman rank corr per month-end; time-series stats; no curve-fit",
        },
        "summary": summary,
        # Trim raw series to (date, IC) — for downstream multiple-testing module
        "raw_series": {f"{f}@{h}d": [(d.isoformat(), round(ic, 6))
                                       for d, ic in series]
                       for (f, h), series in ics.items()},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
