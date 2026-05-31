#!/usr/bin/env python3
"""swing_factor_diagnostics.py — robustness diagnostics for swing factors.

Computes daily cross-sectional factor IC over the A-share daily panel, then
summarizes stability by full sample, calendar year, and quarter. Outputs are
written under experiments/agent_tasks by default, never public/data.

Notes:
  - Spearman IC is tie-aware via average ranks. SciPy is intentionally not
    required.
  - Default factor values reuse run_swing_backtest_fast.fast_signals_one to
    match the current swing engine's factor definitions and veto behavior.
  - Decile spread is reported only when the daily cross-section has enough
    observations and at least 10 distinct factor values; binary factors usually
    report binary active-minus-inactive spread instead.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from liquid_universe import compute_liquid_universe  # noqa: E402
from panel_index import PanelIndex  # noqa: E402
from run_swing_backtest_fast import fast_signals_one  # noqa: E402


FACTOR_NAMES = (
    "breakout_20d",
    "momentum_5d",
    "limit_up_followup",
    "volume_spike",
    "macd_cross",
    "rsi_in_band",
)
DEFAULT_HORIZONS = (1, 3, 5, 10)
DEFAULT_MIN_CROSS_SECTION = 30


def _to_yyyymmdd(d: str) -> str:
    return d.replace("-", "")[:8]


def _iso_date(d: str) -> str:
    d = str(d)
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d


def _norm_sf(x: float) -> float:
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def two_sided_p_from_t(t_stat: Optional[float]) -> Optional[float]:
    if t_stat is None or not math.isfinite(t_stat):
        return None
    return 2.0 * _norm_sf(abs(t_stat))


def average_ranks(values: list[float]) -> list[float]:
    """Average rank for ties; equivalent to scipy.stats.rankdata(..., average)."""
    n = len(values)
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg
        i = j + 1
    return ranks


def pearson(x: list[float], y: list[float]) -> Optional[float]:
    n = len(x)
    if n < 2 or n != len(y):
        return None
    mx = sum(x) / n
    my = sum(y) / n
    vx = sum((v - mx) ** 2 for v in x)
    vy = sum((v - my) ** 2 for v in y)
    if vx <= 0 or vy <= 0:
        return None
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    return cov / math.sqrt(vx * vy)


def spearman_tie_aware(x: list[float], y: list[float]) -> Optional[float]:
    if len(x) != len(y) or len(x) < 2:
        return None
    if not all(math.isfinite(v) for v in x + y):
        return None
    return pearson(average_ranks(x), average_ranks(y))


def bh_adjust(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg FDR adjustment."""
    n = len(p_values)
    if n == 0:
        return []
    indexed = sorted(enumerate(p_values), key=lambda item: item[1])
    out = [1.0] * n
    prev = 1.0
    for rank in range(n, 0, -1):
        idx, p = indexed[rank - 1]
        prev = min(prev, p * n / rank)
        out[idx] = min(1.0, prev)
    return out


def by_adjust(p_values: list[float]) -> list[float]:
    """Benjamini-Yekutieli FDR adjustment; robust to arbitrary dependence."""
    n = len(p_values)
    if n == 0:
        return []
    harmonic = sum(1.0 / i for i in range(1, n + 1))
    indexed = sorted(enumerate(p_values), key=lambda item: item[1])
    out = [1.0] * n
    prev = 1.0
    for rank in range(n, 0, -1):
        idx, p = indexed[rank - 1]
        prev = min(prev, p * n * harmonic / rank)
        out[idx] = min(1.0, prev)
    return out


def summarize_series(values: list[float]) -> dict:
    vals = [float(v) for v in values if v is not None and math.isfinite(v)]
    if not vals:
        return {"n": 0, "mean": None, "std": None, "t_stat": None,
                "p_two_sided": None, "min": None, "max": None,
                "positive_frac": None}
    n = len(vals)
    mean = sum(vals) / n
    if n < 2:
        return {"n": n, "mean": mean, "std": None, "t_stat": None,
                "p_two_sided": None, "min": mean, "max": mean,
                "positive_frac": 1.0 if mean > 0 else 0.0}
    std = statistics.stdev(vals)
    t_stat = mean / (std / math.sqrt(n)) if std > 0 else None
    return {
        "n": n,
        "mean": mean,
        "std": std,
        "t_stat": t_stat,
        "p_two_sided": two_sided_p_from_t(t_stat),
        "min": min(vals),
        "max": max(vals),
        "positive_frac": sum(1 for v in vals if v > 0) / n,
    }


def forward_return(idx: PanelIndex, tk: str, as_of: str, horizon_td: int) -> Optional[float]:
    """Close-to-close return from as_of to the ticker's +h trading bar."""
    dates = idx._dates.get(tk)  # PanelIndex internals; no public offset API yet.
    closes = idx._arr.get(tk, {}).get("close")
    if dates is None or closes is None:
        return None
    pos = int(np.searchsorted(dates, as_of, side="left"))
    if pos >= len(dates) or str(dates[pos]) != as_of:
        return None
    fut = pos + horizon_td
    if fut >= len(dates):
        return None
    c0 = float(closes[pos])
    c1 = float(closes[fut])
    if c0 <= 0 or c1 <= 0 or not math.isfinite(c0) or not math.isfinite(c1):
        return None
    return c1 / c0 - 1.0


def spread_stats(pairs: list[tuple[float, float]]) -> dict:
    """Daily factor spread diagnostics from (factor_value, forward_return)."""
    clean = [(float(x), float(y)) for x, y in pairs
             if math.isfinite(float(x)) and math.isfinite(float(y))]
    n = len(clean)
    if n < DEFAULT_MIN_CROSS_SECTION:
        return {"n": n, "decile_spread": None, "binary_spread": None,
                "unique_values": None}
    xs = [x for x, _ in clean]
    unique_values = len(set(xs))

    decile_spread = None
    if n >= 100 and unique_values >= 10:
        ordered = sorted(clean, key=lambda item: item[0])
        bucket = max(1, n // 10)
        bottom = [r for _, r in ordered[:bucket]]
        top = [r for _, r in ordered[-bucket:]]
        decile_spread = sum(top) / len(top) - sum(bottom) / len(bottom)

    binary_spread = None
    if unique_values == 2:
        inactive = [r for x, r in clean if x <= 0]
        active = [r for x, r in clean if x > 0]
        if inactive and active:
            binary_spread = sum(active) / len(active) - sum(inactive) / len(inactive)

    return {"n": n, "decile_spread": decile_spread,
            "binary_spread": binary_spread, "unique_values": unique_values}


def compute_diagnostics(panel: pd.DataFrame,
                        start: str,
                        end: str,
                        *,
                        horizons: tuple[int, ...] = DEFAULT_HORIZONS,
                        liquid_top_n: int = 500,
                        min_cross_section: int = DEFAULT_MIN_CROSS_SECTION,
                        verbose: bool = False) -> dict:
    start_yyyymmdd = _to_yyyymmdd(start)
    end_yyyymmdd = _to_yyyymmdd(end)

    liquid_uni = compute_liquid_universe(panel, top_n=liquid_top_n)
    all_liquid = set()
    for tickers in liquid_uni.values():
        all_liquid.update(tickers)
    sub = panel[panel["ts_code"].isin(all_liquid)].reset_index(drop=True)
    idx = PanelIndex(sub)
    trade_dates = [d for d in idx.all_trade_dates() if start_yyyymmdd <= d <= end_yyyymmdd]
    if not trade_dates:
        raise ValueError(f"no trade dates in {start} -> {end}")

    daily_records = []
    max_h = max(horizons)
    usable_dates = trade_dates[:-max_h] if max_h < len(trade_dates) else []

    for date_i, as_of in enumerate(usable_dates):
        liquid_today = liquid_uni.get(as_of, [])
        if not liquid_today:
            continue

        factors_by_ticker = {}
        for tk in liquid_today:
            sig = fast_signals_one(idx, tk, as_of)
            if sig is None:
                continue
            vals = {}
            for f in FACTOR_NAMES:
                v = sig.get("factors", {}).get(f)
                if v is not None and math.isfinite(float(v)):
                    vals[f] = float(v)
            if vals:
                factors_by_ticker[tk] = vals

        for h in horizons:
            fwd = {}
            for tk in factors_by_ticker:
                fr = forward_return(idx, tk, as_of, h)
                if fr is not None and math.isfinite(fr):
                    fwd[tk] = fr

            for f in FACTOR_NAMES:
                pairs = []
                for tk, vals in factors_by_ticker.items():
                    if f in vals and tk in fwd:
                        pairs.append((vals[f], fwd[tk]))
                if len(pairs) < min_cross_section:
                    continue
                xs = [x for x, _ in pairs]
                ys = [y for _, y in pairs]
                if len(set(xs)) < 2 or len(set(ys)) < 2:
                    continue
                ic = spearman_tie_aware(xs, ys)
                if ic is None or not math.isfinite(ic):
                    continue
                spreads = spread_stats(pairs)
                daily_records.append({
                    "date": _iso_date(as_of),
                    "year": int(as_of[:4]),
                    "quarter": f"{as_of[:4]}Q{((int(as_of[4:6]) - 1) // 3) + 1}",
                    "factor": f,
                    "horizon": h,
                    "ic": ic,
                    **spreads,
                })

        if verbose and (date_i % 50 == 0 or date_i == len(usable_dates) - 1):
            print(f"processed {date_i + 1}/{len(usable_dates)} dates through {_iso_date(as_of)}",
                  flush=True)

    return build_output(daily_records, start, end, horizons, liquid_top_n,
                        min_cross_section, len(sub), sub["ts_code"].nunique())


def build_output(daily_records: list[dict],
                 start: str,
                 end: str,
                 horizons: tuple[int, ...],
                 liquid_top_n: int,
                 min_cross_section: int,
                 panel_rows: int,
                 panel_tickers: int) -> dict:
    by_test: dict[tuple[str, int], list[dict]] = {}
    for rec in daily_records:
        by_test.setdefault((rec["factor"], int(rec["horizon"])), []).append(rec)

    aggregate = {}
    tests_for_mt = []
    for factor in FACTOR_NAMES:
        aggregate[factor] = {}
        for horizon in horizons:
            rows = by_test.get((factor, horizon), [])
            ic_summary = summarize_series([r["ic"] for r in rows])
            decile_summary = summarize_series([
                r["decile_spread"] for r in rows if r.get("decile_spread") is not None
            ])
            binary_summary = summarize_series([
                r["binary_spread"] for r in rows if r.get("binary_spread") is not None
            ])
            payload = {
                **ic_summary,
                "mean_decile_spread": decile_summary["mean"],
                "n_decile_days": decile_summary["n"],
                "mean_binary_spread": binary_summary["mean"],
                "n_binary_days": binary_summary["n"],
            }
            aggregate[factor][str(horizon)] = payload
            if payload["p_two_sided"] is not None:
                tests_for_mt.append((factor, horizon, payload))

    p_values = [payload["p_two_sided"] for _, _, payload in tests_for_mt]
    bh_q = bh_adjust(p_values)
    by_q = by_adjust(p_values)
    mt = []
    for i, (factor, horizon, payload) in enumerate(tests_for_mt):
        payload["bh_q"] = bh_q[i]
        payload["by_q"] = by_q[i]
        payload["bh_05"] = bh_q[i] <= 0.05
        payload["by_05"] = by_q[i] <= 0.05
        mt.append({
            "factor": factor,
            "horizon": horizon,
            "mean_ic": payload["mean"],
            "t_stat": payload["t_stat"],
            "p_two_sided": payload["p_two_sided"],
            "bh_q": bh_q[i],
            "by_q": by_q[i],
            "bh_05": bh_q[i] <= 0.05,
            "by_05": by_q[i] <= 0.05,
        })
    mt.sort(key=lambda r: (r["by_q"], r["factor"], r["horizon"]))

    windows = {"year": {}, "quarter": {}}
    for window_key in ("year", "quarter"):
        buckets = sorted({str(r[window_key]) for r in daily_records})
        for bucket in buckets:
            windows[window_key][bucket] = {}
            for factor in FACTOR_NAMES:
                windows[window_key][bucket][factor] = {}
                for horizon in horizons:
                    rows = [r for r in daily_records
                            if str(r[window_key]) == bucket
                            and r["factor"] == factor
                            and int(r["horizon"]) == int(horizon)]
                    ic_summary = summarize_series([r["ic"] for r in rows])
                    decile_summary = summarize_series([
                        r["decile_spread"] for r in rows
                        if r.get("decile_spread") is not None
                    ])
                    binary_summary = summarize_series([
                        r["binary_spread"] for r in rows
                        if r.get("binary_spread") is not None
                    ])
                    windows[window_key][bucket][factor][str(horizon)] = {
                        **ic_summary,
                        "mean_decile_spread": decile_summary["mean"],
                        "n_decile_days": decile_summary["n"],
                        "mean_binary_spread": binary_summary["mean"],
                        "n_binary_days": binary_summary["n"],
                    }

    return {
        "_meta": {
            "window": [start, end],
            "horizons_td": list(horizons),
            "liquid_top_n": liquid_top_n,
            "min_cross_section": min_cross_section,
            "panel_rows_after_liquid_union": panel_rows,
            "panel_tickers_after_liquid_union": panel_tickers,
            "rank_correlation": "tie-aware Spearman using local average ranks; scipy not required",
            "factor_source": "run_swing_backtest_fast.fast_signals_one, including its veto behavior",
            "artifact_policy": "diagnostic output only; not written to public/data",
        },
        "aggregate": aggregate,
        "multiple_testing": mt,
        "windows": windows,
        "daily_records": daily_records,
    }


def write_markdown_report(result: dict, path: Path) -> None:
    meta = result["_meta"]
    agg = result["aggregate"]
    mt = result["multiple_testing"]
    lines = [
        "# R1 Swing Factor Robustness Diagnostics",
        "",
        f"Window: `{meta['window'][0]}` to `{meta['window'][1]}`",
        f"Universe: liquid top `{meta['liquid_top_n']}` by PIT 20d ADV",
        f"Rank correlation: {meta['rank_correlation']}",
        f"Factor source: {meta['factor_source']}",
        "",
        "## Aggregate IC",
        "",
        "| Factor | H | Mean IC | t | p | BH q | BY q | BH 5% | BY 5% | Decile spread | Binary spread | N |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---:|",
    ]
    for factor in FACTOR_NAMES:
        for h, row in agg[factor].items():
            lines.append(
                "| {factor} | {h} | {mean} | {t} | {p} | {bh} | {by} | {bhf} | {byf} | {dec} | {bin} | {n} |".format(
                    factor=factor,
                    h=h,
                    mean=_fmt(row.get("mean")),
                    t=_fmt(row.get("t_stat")),
                    p=_fmt(row.get("p_two_sided")),
                    bh=_fmt(row.get("bh_q")),
                    by=_fmt(row.get("by_q")),
                    bhf="Y" if row.get("bh_05") else "N",
                    byf="Y" if row.get("by_05") else "N",
                    dec=_fmt(row.get("mean_decile_spread")),
                    bin=_fmt(row.get("mean_binary_spread")),
                    n=row.get("n", 0),
                )
            )

    lines += [
        "",
        "## Strongest Multi-Test Adjusted Results",
        "",
        "| Factor | H | Mean IC | t | p | BH q | BY q |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in mt[:12]:
        lines.append(
            f"| {row['factor']} | {row['horizon']} | {_fmt(row['mean_ic'])} | "
            f"{_fmt(row['t_stat'])} | {_fmt(row['p_two_sided'])} | "
            f"{_fmt(row['bh_q'])} | {_fmt(row['by_q'])} |"
        )

    lines += [
        "",
        "## Year Summary",
        "",
        "| Year | Factor | H | Mean IC | t | N |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for year, by_factor in result["windows"]["year"].items():
        for factor in FACTOR_NAMES:
            for h, row in by_factor[factor].items():
                lines.append(
                    f"| {year} | {factor} | {h} | {_fmt(row.get('mean'))} | "
                    f"{_fmt(row.get('t_stat'))} | {row.get('n', 0)} |"
                )

    lines += [
        "",
        "## Quarter Summary",
        "",
        "| Quarter | Factor | H | Mean IC | t | N |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for quarter, by_factor in result["windows"]["quarter"].items():
        for factor in FACTOR_NAMES:
            for h, row in by_factor[factor].items():
                lines.append(
                    f"| {quarter} | {factor} | {h} | {_fmt(row.get('mean'))} | "
                    f"{_fmt(row.get('t_stat'))} | {row.get('n', 0)} |"
                )

    lines += [
        "",
        "## Validation Labels",
        "",
        "Causal logic is unestablished because cross-sectional IC measures whether "
        "today's factor ranks align with future returns; it does not prove the "
        "economic mechanism or tradability after costs, fills, capacity, and "
        "portfolio constraints.",
        "",
        "Specific numbers are validated against this local daily panel run for "
        "the stated window, horizons, factor definitions, and liquid universe. "
        "They are not calibrated thresholds or validated production weights.",
    ]
    path.write_text("\n".join(lines) + "\n")


def _fmt(v: object) -> str:
    if v is None:
        return "n/a"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not math.isfinite(f):
        return "n/a"
    return f"{f:.4g}"


def selftest() -> int:
    failures = []
    ranks = average_ranks([10, 20, 30, 20])
    if ranks != [1.0, 2.5, 4.0, 2.5]:
        failures.append(f"average_ranks ties wrong: {ranks}")
    rho = spearman_tie_aware([1, 2, 3], [3, 2, 1])
    if rho is None or abs(rho + 1.0) > 1e-12:
        failures.append(f"inverse Spearman expected -1, got {rho}")
    q = bh_adjust([0.01, 0.02, 0.20])
    if any(q[i] > q[i + 1] + 1e-12 for i in range(len(q) - 1)):
        failures.append(f"BH q not monotone for sorted p-values: {q}")
    by = by_adjust([0.01, 0.02, 0.20])
    if any(by_i < bh_i - 1e-12 for by_i, bh_i in zip(by, q)):
        failures.append(f"BY should be >= BH: bh={q} by={by}")
    if failures:
        print("SELFTEST FAILED swing_factor_diagnostics:")
        for failure in failures:
            print(" -", failure)
        return 1
    print("SELFTEST PASSED swing_factor_diagnostics")
    print("- tie-aware average ranks")
    print("- BH and BY multiple-testing adjustment")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Swing factor robustness diagnostics.")
    p.add_argument("--prices", default=str(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet"))
    p.add_argument("--start", default="2025-05-26")
    p.add_argument("--end", default="2026-05-25")
    p.add_argument("--horizons", default="1,3,5,10",
                   help="Comma-separated trading-day horizons.")
    p.add_argument("--liquid-top-n", type=int, default=500)
    p.add_argument("--min-cross-section", type=int, default=DEFAULT_MIN_CROSS_SECTION)
    p.add_argument("--output-dir", default=str(REPO_ROOT / "experiments" / "agent_tasks"))
    p.add_argument("--output-prefix", default="r1_swing_factor_diagnostics")
    p.add_argument("--no-daily-records", action="store_true",
                   help="Omit daily_records from JSON to reduce file size.")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        return selftest()

    horizons = tuple(int(x.strip()) for x in args.horizons.split(",") if x.strip())
    panel = pd.read_parquet(args.prices)
    result = compute_diagnostics(
        panel,
        args.start,
        args.end,
        horizons=horizons,
        liquid_top_n=args.liquid_top_n,
        min_cross_section=args.min_cross_section,
        verbose=args.verbose,
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{args.output_prefix}.json"
    report_path = output_dir / "r1_factor_diagnostics_report.md"
    json_result = dict(result)
    if args.no_daily_records:
        json_result["daily_records"] = []
        json_result["_meta"]["daily_records_omitted"] = True
    json_path.write_text(json.dumps(json_result, indent=2, ensure_ascii=False, default=str))
    write_markdown_report(result, report_path)

    print(f"wrote {json_path}")
    print(f"wrote {report_path}")
    for row in result["multiple_testing"][:8]:
        print(
            f"{row['factor']:>18} h={row['horizon']:>2} "
            f"IC={row['mean_ic']:+.4f} t={row['t_stat']:+.2f} "
            f"BH={row['bh_q']:.4g} BY={row['by_q']:.4g}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
