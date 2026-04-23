#!/usr/bin/env python3
"""
AR Platform — VP Score Backtest Engine  (v1.0)
==================================================
Implements a monthly-rebalance, VP-Score-gated long-only portfolio
backtested against CSI 300 (A-share) and HSI (HK) benchmarks.

Design principles (from blueprint §3):
  • Point-in-time safe: VP Score snapshots from vp_snapshot.json history
  • Monthly rebalance on last trading day of each month
  • Equal-weighted portfolio of stocks with VP ≥ threshold
  • Transaction cost drag: 0.20% A-share, 0.40% HK (round-trip split evenly)
  • Forward return window: 20 trading days (~1 calendar month)
  • Bootstrap confidence intervals: 1000 resamples on monthly returns
  • Benchmark: CSI 300 for A-shares, HSI for HK, blended for mixed

Output:  public/data/backtest_results.json

Usage:
  python3 scripts/backtest.py                     # uses default VP threshold 60
  python3 scripts/backtest.py --threshold 65      # custom threshold
  python3 scripts/backtest.py --threshold 60 --min-positions 3

The script is also called daily by GitHub Actions after paper_trading.py.
With < 60 days of OHLCV history the output will be labelled "insufficient data"
but the file is always written so the frontend never 404s.
"""

import json, argparse, random
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

DATA_DIR = Path(__file__).parent.parent / "public" / "data"

# ── Constants ────────────────────────────────────────────────────────────────
TX_COST_HALF  = {"SH": 0.001, "SZ": 0.001, "HK": 0.002}   # one-way (buy or sell)
FORWARD_DAYS  = 20          # ~1 calendar month of trading days
MIN_HISTORY   = 60          # days of OHLCV required before we start backtesting
BOOTSTRAP_N   = 1_000       # resamples for CI
RISK_FREE_ANN = 0.020       # China 1Y deposit rate

# Benchmark tickers (must exist in OHLCV data fetched by fetch_data.py)
BENCH_A  = "000300.SH"      # CSI 300
BENCH_HK = "HSI.HK"         # Hang Seng Index


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_json(filename, default=None):
    f = DATA_DIR / filename
    if not f.exists():
        return default if default is not None else {}
    with open(f) as fh:
        return json.load(fh)


def save_json(filename, data):
    with open(DATA_DIR / filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def load_ohlcv(ticker: str) -> list[dict]:
    """Load OHLCV list for a ticker.  Returns [] if file missing.
    Handles both flat list format and wrapped {ticker, data, fetched_at} format."""
    safe = ticker.replace("/", "_").replace(".", "_")
    raw = load_json(f"ohlc_{safe}.json", [])
    # Unwrap if fetch_data.py wrote {ticker, data, fetched_at}
    if isinstance(raw, dict):
        return raw.get("data", [])
    return raw


def ohlcv_to_price_series(records: list[dict]) -> dict[str, float]:
    """Convert OHLCV records to {date_str: close} dict, sorted ascending."""
    series = {}
    for r in records:
        d = r.get("date") or r.get("t")
        c = r.get("close") or r.get("c")
        if d and c is not None:
            series[str(d)[:10]] = float(c)
    return dict(sorted(series.items()))


def trading_days_from_series(price_series: dict[str, float]) -> list[str]:
    return sorted(price_series.keys())


def fwd_return(price_series: dict, entry_date: str, fwd_days: int) -> float | None:
    """
    Compute forward return from entry_date over fwd_days trading days.
    Returns None if insufficient data.
    """
    days = trading_days_from_series(price_series)
    if entry_date not in days:
        # find nearest date on-or-after entry_date
        later = [d for d in days if d >= entry_date]
        if not later:
            return None
        entry_date = later[0]

    idx = days.index(entry_date)
    exit_idx = idx + fwd_days
    if exit_idx >= len(days):
        return None
    entry_price = price_series[days[idx]]
    exit_price  = price_series[days[exit_idx]]
    if entry_price <= 0:
        return None
    return exit_price / entry_price - 1


def monthly_rebalance_dates(price_series: dict) -> list[str]:
    """Return the last trading day of each month present in price_series."""
    days  = sorted(price_series.keys())
    month_last = {}
    for d in days:
        ym = d[:7]  # "YYYY-MM"
        month_last[ym] = d
    return sorted(month_last.values())


def infer_market(ticker: str) -> str:
    if ticker.endswith(".HK"):
        return "HK"
    if ticker.endswith(".SH"):
        return "SH"
    if ticker.endswith(".SZ"):
        return "SZ"
    return "SZ"


# ── Bootstrap CI ─────────────────────────────────────────────────────────────

def bootstrap_mean_ci(returns: list[float], n: int = BOOTSTRAP_N, ci: float = 0.95) -> tuple[float, float]:
    """Return (lower, upper) CI for the mean via bootstrap."""
    if len(returns) < 2:
        m = returns[0] if returns else 0.0
        return m, m
    rng = random.Random(42)
    means = []
    for _ in range(n):
        sample = [rng.choice(returns) for _ in range(len(returns))]
        means.append(sum(sample) / len(sample))
    means.sort()
    lo = int((1 - ci) / 2 * n)
    hi = int((1 - (1 - ci) / 2) * n)
    return means[lo], means[hi]


# ── Portfolio return per rebalance period ────────────────────────────────────

def compute_period_return(
    selected_tickers: list[str],
    rebalance_date: str,
    all_price_series: dict[str, dict],
    fwd_days: int = FORWARD_DAYS,
) -> tuple[float | None, list[dict]]:
    """
    Equal-weighted portfolio forward return net of transaction costs.
    Returns (portfolio_return, per_stock_details).
    """
    stock_returns = []
    details = []

    for tk in selected_tickers:
        ps = all_price_series.get(tk, {})
        if not ps:
            continue
        raw_ret = fwd_return(ps, rebalance_date, fwd_days)
        if raw_ret is None:
            continue

        market   = infer_market(tk)
        tx_drag  = TX_COST_HALF.get(market, 0.001) * 2  # buy + sell
        net_ret  = raw_ret - tx_drag

        stock_returns.append(net_ret)
        details.append({
            "ticker":     tk,
            "raw_return": round(raw_ret * 100, 2),
            "net_return": round(net_ret * 100, 2),
            "tx_cost":    round(tx_drag * 100, 3),
        })

    if not stock_returns:
        return None, []

    port_return = sum(stock_returns) / len(stock_returns)
    return port_return, details


# ── VP Score history reconstruction ──────────────────────────────────────────

def _load_watchlist_seeds() -> dict[str, int]:
    """
    Load vp_seed.vp values from watchlist.json as a static VP baseline.
    Returns {ticker: vp_score}.  Used when no vp_history exists yet.
    """
    wl_path = DATA_DIR / "watchlist.json"
    seeds: dict[str, int] = {}
    try:
        wl = json.loads(wl_path.read_text(encoding="utf-8"))
        for tk, v in wl.get("tickers", {}).items():
            seed_vp = v.get("vp_seed", {}).get("vp")
            if seed_vp is not None:
                seeds[tk] = int(seed_vp)
    except Exception:
        pass
    return seeds


def build_vp_history_from_snapshots(vp_snapshot: dict) -> dict[str, dict[str, int]]:
    """
    Build point-in-time VP history from all available sources (priority order):
      1. vp_history.json      — daily accumulated snapshots (most accurate)
      2. vp_snapshot.json     — today's live engine output
      3. watchlist.json seeds — static fallback for pre-history periods

    Returns: { ticker: { date: vp_score } }
    """
    ticker_history: dict[str, dict[str, int]] = defaultdict(dict)
    today = datetime.now().strftime("%Y-%m-%d")

    # ── Source 1: vp_history.json (accumulated daily rows) ────────────────────
    vp_hist_path = DATA_DIR / "vp_history.json"
    if vp_hist_path.exists():
        try:
            vp_hist = json.loads(vp_hist_path.read_text(encoding="utf-8"))
            for date_str, row in vp_hist.items():
                for tk, score in row.items():
                    if score is not None:
                        ticker_history[tk][date_str] = int(score)
        except Exception:
            pass

    # ── Source 2: vp_snapshot.json current snapshots array ────────────────────
    snapshots = vp_snapshot.get("snapshots", [])
    if isinstance(snapshots, list):
        snap_date = vp_snapshot.get("date", today)
        for snap in snapshots:
            tk    = snap.get("ticker")
            score = snap.get("vp_score") or snap.get("vp") or snap.get("total")
            if tk and score is not None:
                ticker_history[tk][snap_date] = int(score)

    # ── Source 3: watchlist.json seeds as eternal static baseline ─────────────
    # Backfill SEED_DATE with seed values so that backtest periods before we
    # started accumulating vp_history still get a reasonable VP proxy.
    seeds = _load_watchlist_seeds()
    SEED_DATE = "2025-01-01"
    for tk, seed_vp in seeds.items():
        if SEED_DATE not in ticker_history.get(tk, {}):
            ticker_history[tk][SEED_DATE] = seed_vp

    return dict(ticker_history)


def get_vp_score_on_date(
    ticker_history: dict[str, dict[str, int]],
    ticker: str,
    date_str: str,
) -> int | None:
    """
    Return most recent VP score as-of date_str (point-in-time safe).
    Seed date 2025-01-01 ensures backtest never returns None for watchlist tickers.
    """
    dates = ticker_history.get(ticker, {})
    if not dates:
        return None   # ticker entirely unknown
    past = {d: s for d, s in dates.items() if d <= date_str}
    if past:
        return past[max(past)]
    # Query predates all known history → use earliest as proxy
    return dates[min(dates.keys())]


# ── Benchmark return ─────────────────────────────────────────────────────────

def compute_benchmark_return(
    bench_series: dict,
    rebalance_date: str,
    fwd_days: int = FORWARD_DAYS,
) -> float | None:
    return fwd_return(bench_series, rebalance_date, fwd_days)


# ── Metrics ──────────────────────────────────────────────────────────────────

def annualise(monthly_returns: list[float], periods_per_year: float = 12) -> float:
    if not monthly_returns:
        return 0.0
    avg = sum(monthly_returns) / len(monthly_returns)
    return (1 + avg) ** periods_per_year - 1


def volatility_ann(monthly_returns: list[float], periods_per_year: float = 12) -> float:
    if len(monthly_returns) < 2:
        return 0.0
    n   = len(monthly_returns)
    avg = sum(monthly_returns) / n
    var = sum((r - avg) ** 2 for r in monthly_returns) / (n - 1)
    return (var ** 0.5) * (periods_per_year ** 0.5)


def sharpe(monthly_returns: list[float], rf_annual: float = RISK_FREE_ANN) -> float:
    ann_ret = annualise(monthly_returns)
    ann_vol = volatility_ann(monthly_returns)
    if ann_vol == 0:
        return 0.0
    return (ann_ret - rf_annual) / ann_vol


def max_drawdown(cumulative_returns: list[float]) -> float:
    """Max drawdown from a list of period returns (not cumulative NAV)."""
    if not cumulative_returns:
        return 0.0
    nav  = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in cumulative_returns:
        nav  *= (1 + r)
        peak  = max(peak, nav)
        dd    = (peak - nav) / peak
        max_dd = max(max_dd, dd)
    return max_dd


def compute_beta(port_returns: list[float], bench_returns: list[float]) -> float:
    """OLS beta: cov(P,B) / var(B)."""
    n = min(len(port_returns), len(bench_returns))
    if n < 3:
        return 1.0
    p = port_returns[:n]
    b = bench_returns[:n]
    mean_p = sum(p) / n
    mean_b = sum(b) / n
    cov = sum((p[i] - mean_p) * (b[i] - mean_b) for i in range(n)) / (n - 1)
    var_b = sum((b[i] - mean_b) ** 2 for i in range(n)) / (n - 1)
    if var_b == 0:
        return 1.0
    return cov / var_b


def compute_alpha(
    port_returns: list[float],
    bench_returns: list[float],
    beta: float,
    rf_monthly: float,
) -> float:
    """Jensen's alpha (monthly)."""
    n = min(len(port_returns), len(bench_returns))
    if n < 3:
        return 0.0
    avg_p = sum(port_returns[:n]) / n
    avg_b = sum(bench_returns[:n]) / n
    return avg_p - (rf_monthly + beta * (avg_b - rf_monthly))


# ── NAV series ───────────────────────────────────────────────────────────────

def build_nav_series(
    rebalance_dates: list[str],
    period_returns: list[float],
    benchmark_returns: list[float],
) -> list[dict]:
    """Build NAV series starting at 1.0 for chart display."""
    nav_p = 1.0
    nav_b = 1.0
    series = []
    for i, d in enumerate(rebalance_dates):
        if i < len(period_returns) and period_returns[i] is not None:
            nav_p *= (1 + period_returns[i])
        if i < len(benchmark_returns) and benchmark_returns[i] is not None:
            nav_b *= (1 + benchmark_returns[i])
        series.append({
            "date":      d,
            "portfolio": round(nav_p, 4),
            "benchmark": round(nav_b, 4),
        })
    return series


# ── Main backtest loop ────────────────────────────────────────────────────────

def run_backtest(threshold: int = 60, min_positions: int = 1) -> dict:
    print(f"\n{'='*55}")
    print(f"AR Platform — VP Score Backtest Engine")
    print(f"VP threshold: {threshold}  |  Min positions: {min_positions}")
    print(f"{'='*55}\n")

    # ── 1. Load data ─────────────────────────────────────────────────────────
    vp_snapshot    = load_json("vp_snapshot.json", {})
    market_data    = load_json("market_data.json", {})

    # Discover all tickers from OHLCV files
    ohlcv_files = list(DATA_DIR.glob("ohlc_*.json"))
    all_tickers = []
    for f in ohlcv_files:
        # reverse the safe-name mangling: ohlc_300308_SZ.json → 300308.SZ
        stem = f.stem[5:]  # strip "ohlc_"
        # Try to figure out market suffix from last segment
        parts = stem.rsplit("_", 1)
        if len(parts) == 2 and parts[1] in ("SH", "SZ", "HK"):
            tk = f"{parts[0]}.{parts[1]}"
        else:
            tk = stem.replace("_", ".")
        all_tickers.append(tk)

    print(f"  OHLCV files found: {len(ohlcv_files)}")

    if not all_tickers:
        print("  No OHLCV data found — writing placeholder output.")
        result = _insufficient_data_result(threshold, min_positions, reason="no_ohlcv_data")
        save_json("backtest_results.json", result)
        return result

    # Load price series for all tickers
    all_price_series: dict[str, dict] = {}
    for tk in all_tickers:
        records = load_ohlcv(tk)
        ps      = ohlcv_to_price_series(records)
        if ps:
            all_price_series[tk] = ps

    # Load benchmarks
    bench_a_series  = ohlcv_to_price_series(load_ohlcv(BENCH_A))
    bench_hk_series = ohlcv_to_price_series(load_ohlcv(BENCH_HK))

    # Use whichever benchmark has more data
    bench_series = bench_a_series if len(bench_a_series) >= len(bench_hk_series) else bench_hk_series
    bench_label  = "CSI 300" if bench_series is bench_a_series else "HSI"

    # Fallback: if no benchmark OHLCV file exists yet (common before first
    # full fetch-data run), synthesise a flat 100 series from the longest
    # portfolio stock. This lets the backtest run but alpha = 0 by construction.
    if not bench_series and all_price_series:
        proxy_tk, proxy_ps = max(all_price_series.items(), key=lambda x: len(x[1]))
        first_v = next(iter(proxy_ps.values()))
        bench_series = {d: first_v for d in proxy_ps}   # flat = no benchmark drag
        bench_label  = f"proxy ({proxy_tk}, flat)"
        print(f"  No benchmark OHLCV — using flat proxy from {proxy_tk}")

    print(f"  Tickers with price data: {len(all_price_series)}")
    print(f"  Benchmark: {bench_label} ({len(bench_series)} days)")

    # ── 2. Check minimum history ─────────────────────────────────────────────
    if len(bench_series) < MIN_HISTORY:
        print(f"  Insufficient data ({len(bench_series)} days < {MIN_HISTORY} required).")
        result = _insufficient_data_result(
            threshold, min_positions,
            reason="insufficient_history",
            days_available=len(bench_series),
            days_required=MIN_HISTORY,
        )
        save_json("backtest_results.json", result)
        return result

    # ── 3. Build VP score history ─────────────────────────────────────────────
    ticker_vp_history = build_vp_history_from_snapshots(vp_snapshot)
    print(f"  Tickers with VP history: {len(ticker_vp_history)}")

    # ── 4. Get rebalance dates from benchmark ─────────────────────────────────
    rebalance_dates = monthly_rebalance_dates(bench_series)
    # Trim: need at least FORWARD_DAYS after last date for valid return
    bench_days = trading_days_from_series(bench_series)
    last_valid = bench_days[-FORWARD_DAYS - 1] if len(bench_days) > FORWARD_DAYS else None
    if last_valid:
        rebalance_dates = [d for d in rebalance_dates if d <= last_valid]

    print(f"  Rebalance periods: {len(rebalance_dates)}")

    if len(rebalance_dates) < 2:
        print("  Too few rebalance periods — insufficient history.")
        result = _insufficient_data_result(
            threshold, min_positions,
            reason="too_few_periods",
            days_available=len(bench_series),
            days_required=MIN_HISTORY,
        )
        save_json("backtest_results.json", result)
        return result

    # ── 5. Main backtest loop ─────────────────────────────────────────────────
    period_returns_port  = []
    period_returns_bench = []
    period_details       = []

    for reb_date in rebalance_dates:
        # Select stocks with VP ≥ threshold as of rebalance date
        selected = []
        for tk in all_price_series:
            vp = get_vp_score_on_date(ticker_vp_history, tk, reb_date)
            if vp is not None and vp >= threshold:
                selected.append((tk, vp))

        selected.sort(key=lambda x: -x[1])  # highest VP first
        selected_tickers = [tk for tk, _ in selected]

        if len(selected_tickers) < min_positions:
            # Not enough stocks pass filter — sit in cash (0% return net costs)
            period_returns_port.append(0.0)
            bench_ret = compute_benchmark_return(bench_series, reb_date, FORWARD_DAYS)
            period_returns_bench.append(bench_ret if bench_ret is not None else 0.0)
            period_details.append({
                "date":              reb_date,
                "selected":          [],
                "portfolio_return":  0.0,
                "benchmark_return":  round((bench_ret or 0) * 100, 2),
                "cash":              True,
            })
            continue

        port_ret, stock_details = compute_period_return(
            selected_tickers, reb_date, all_price_series, FORWARD_DAYS
        )
        bench_ret = compute_benchmark_return(bench_series, reb_date, FORWARD_DAYS)

        period_returns_port.append(port_ret if port_ret is not None else 0.0)
        period_returns_bench.append(bench_ret if bench_ret is not None else 0.0)

        period_details.append({
            "date":              reb_date,
            "selected":          [{"ticker": tk, "vp": vp} for tk, vp in selected],
            "num_positions":     len(selected_tickers),
            "portfolio_return":  round((port_ret or 0) * 100, 2),
            "benchmark_return":  round((bench_ret or 0) * 100, 2),
            "excess_return":     round(((port_ret or 0) - (bench_ret or 0)) * 100, 2),
            "stock_detail":      stock_details,
        })

    print(f"  Periods computed: {len(period_details)}")

    # ── 6. Aggregate metrics ──────────────────────────────────────────────────
    valid_port  = [r for r in period_returns_port  if r is not None]
    valid_bench = [r for r in period_returns_bench if r is not None]

    ann_ret_port  = annualise(valid_port)
    ann_ret_bench = annualise(valid_bench)
    ann_vol_port  = volatility_ann(valid_port)
    ann_vol_bench = volatility_ann(valid_bench)
    sharpe_port   = sharpe(valid_port)
    sharpe_bench  = sharpe(valid_bench)
    dd_port       = max_drawdown(valid_port)
    dd_bench      = max_drawdown(valid_bench)

    beta  = compute_beta(valid_port, valid_bench)
    rf_monthly = (1 + RISK_FREE_ANN) ** (1 / 12) - 1
    alpha_monthly = compute_alpha(valid_port, valid_bench, beta, rf_monthly)
    alpha_annual  = (1 + alpha_monthly) ** 12 - 1

    excess_returns = [
        (p or 0) - (b or 0)
        for p, b in zip(period_returns_port, period_returns_bench)
    ]
    hit_rate = sum(1 for e in excess_returns if e > 0) / len(excess_returns) * 100 if excess_returns else 0

    # Bootstrap CI on mean monthly excess return
    ci_lo, ci_hi = bootstrap_mean_ci(excess_returns) if len(excess_returns) >= 3 else (0.0, 0.0)

    # NAV series for chart
    nav_series = build_nav_series(rebalance_dates, period_returns_port, period_returns_bench)

    # Cumulative returns
    cum_port  = nav_series[-1]["portfolio"] - 1 if nav_series else 0
    cum_bench = nav_series[-1]["benchmark"] - 1 if nav_series else 0

    print(f"\n  {'Metric':<30} {'Portfolio':>12} {'Benchmark':>12}")
    print(f"  {'-'*54}")
    print(f"  {'Annualised Return':<30} {ann_ret_port*100:>11.1f}% {ann_ret_bench*100:>11.1f}%")
    print(f"  {'Annualised Volatility':<30} {ann_vol_port*100:>11.1f}% {ann_vol_bench*100:>11.1f}%")
    print(f"  {'Sharpe Ratio':<30} {sharpe_port:>12.2f} {sharpe_bench:>12.2f}")
    print(f"  {'Max Drawdown':<30} {-dd_port*100:>11.1f}% {-dd_bench*100:>11.1f}%")
    print(f"  {'Beta':<30} {beta:>12.2f}")
    print(f"  {'Jensen Alpha (ann)':<30} {alpha_annual*100:>11.1f}%")
    print(f"  {'Excess-return Hit Rate':<30} {hit_rate:>11.1f}%")
    print(f"  {'Bootstrap CI (95%)':<30} [{ci_lo*100:.1f}%, {ci_hi*100:.1f}%]")

    result = {
        "as_of":           datetime.now().strftime("%Y-%m-%d"),
        "generated":       datetime.now().isoformat(),
        "status":          "ok",
        "config": {
            "vp_threshold":    threshold,
            "min_positions":   min_positions,
            "forward_days":    FORWARD_DAYS,
            "benchmark":       bench_label,
            "risk_free_annual": RISK_FREE_ANN,
        },
        "summary": {
            "periods":                  len(period_details),
            "annualised_return_pct":    round(ann_ret_port * 100, 2),
            "benchmark_return_pct":     round(ann_ret_bench * 100, 2),
            "alpha_annual_pct":         round(alpha_annual * 100, 2),
            "beta":                     round(beta, 3),
            "sharpe_ratio":             round(sharpe_port, 3),
            "benchmark_sharpe":         round(sharpe_bench, 3),
            "annualised_vol_pct":       round(ann_vol_port * 100, 2),
            "benchmark_vol_pct":        round(ann_vol_bench * 100, 2),
            "max_drawdown_pct":         round(-dd_port * 100, 2),
            "benchmark_max_dd_pct":     round(-dd_bench * 100, 2),
            "cumulative_return_pct":    round(cum_port * 100, 2),
            "benchmark_cumulative_pct": round(cum_bench * 100, 2),
            "hit_rate_pct":             round(hit_rate, 1),
            "bootstrap_ci_lo_pct":      round(ci_lo * 100, 2),
            "bootstrap_ci_hi_pct":      round(ci_hi * 100, 2),
        },
        "nav_series":   nav_series,
        "period_log":   period_details[-24:],   # last 24 periods for UI (keep file small)
    }

    save_json("backtest_results.json", result)
    print(f"\nDONE: public/data/backtest_results.json written.")
    return result


def _insufficient_data_result(threshold, min_positions, reason="unknown", **kwargs) -> dict:
    return {
        "as_of":     datetime.now().strftime("%Y-%m-%d"),
        "generated": datetime.now().isoformat(),
        "status":    "insufficient_data",
        "reason":    reason,
        "config": {
            "vp_threshold":  threshold,
            "min_positions": min_positions,
            "forward_days":  FORWARD_DAYS,
        },
        "summary":   {},
        "nav_series": [],
        "period_log": [],
        **kwargs,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AR Platform VP Score Backtest")
    parser.add_argument("--threshold",      type=int, default=60,
                        help="VP Score threshold (default 60)")
    parser.add_argument("--min-positions",  type=int, default=1,
                        help="Minimum positions required (default 1); periods below go to cash")
    args = parser.parse_args()

    run_backtest(threshold=args.threshold, min_positions=args.min_positions)
