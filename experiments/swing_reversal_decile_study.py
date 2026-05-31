#!/usr/bin/env python3
"""Pure factor portfolio diagnostics for swing reversal research.

This is intentionally lower-level than the swing backtest engine. It asks:
if 5-day momentum has negative IC, do broad bottom-decile/bottom-quintile
portfolios beat equal-weight liquid A-shares before any stock-picker, stop,
or concentration logic is introduced?
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from liquid_universe import compute_liquid_universe  # noqa: E402
from stationary_bootstrap import bootstrap_ci, mean as bs_mean  # noqa: E402


ROUND_TRIP_COST = 2 * 0.0010 + 0.00025 + 0.00025 + 0.0005


def _yyyymmdd(d: str) -> str:
    return d.replace("-", "")[:8]


def _iso(d: str) -> str:
    d = str(d)
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 and d.isdigit() else d


def load_sector_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    tickers = raw.get("tickers", raw)
    out = {}
    for tk, info in tickers.items():
        if isinstance(info, dict):
            out[tk] = str(info.get("industry_sw_l1") or info.get("industry_tushare") or "UNKNOWN")
    return out


def add_factor_columns(df: pd.DataFrame, horizons: tuple[int, ...]) -> pd.DataFrame:
    df = df.sort_values(["ts_code", "trade_date"]).copy()
    g = df.groupby("ts_code", sort=False)
    close = df["close"].astype(float)
    df["momentum_5d"] = close / g["close"].shift(5).astype(float) - 1.0
    df["momentum_20d"] = close / g["close"].shift(20).astype(float) - 1.0
    prev_v20 = g["vol"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    df["volume_ratio"] = df["vol"].astype(float) / prev_v20.astype(float)
    df["no_volume_spike"] = (df["volume_ratio"] < 1.20).astype(float)
    for h in horizons:
        df[f"fwd_{h}d"] = g["close"].shift(-h).astype(float) / close - 1.0
    return df


def _pick_tail(group: pd.DataFrame, factor: str, q: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    ordered = group.sort_values([factor, "ts_code"], ascending=[True, True])
    n = max(1, int(math.floor(len(ordered) * q)))
    return ordered.head(n), ordered.tail(n)


def _mean_or_none(xs: list[float]) -> Optional[float]:
    vals = [float(x) for x in xs if x is not None and math.isfinite(float(x))]
    if not vals:
        return None
    return sum(vals) / len(vals)


def daily_portfolio_rows(
    panel: pd.DataFrame,
    liquid_uni: dict[str, list[str]],
    sector_map: dict[str, str],
    start: str,
    end: str,
    *,
    factor: str,
    horizon: int,
    quantile: float,
    min_names: int,
) -> list[dict]:
    start_y = _yyyymmdd(start)
    end_y = _yyyymmdd(end)
    fwd_col = f"fwd_{horizon}d"
    sub = panel[(panel["trade_date"] >= start_y) & (panel["trade_date"] <= end_y)].copy()
    if sub.empty:
        return []
    sub["sector"] = sub["ts_code"].map(sector_map).fillna("UNKNOWN")
    by_date = {str(d): g for d, g in sub.groupby("trade_date", sort=True)}
    dates = sorted(d for d in by_date if d in liquid_uni)
    scheduled = dates[::horizon]
    rows = []

    for date in scheduled:
        group = by_date[date]
        liquid = set(liquid_uni.get(date, ()))
        group = group[group["ts_code"].isin(liquid)]
        group = group.replace([np.inf, -np.inf], np.nan).dropna(subset=[factor, fwd_col])
        if len(group) < min_names:
            continue

        bottom, top = _pick_tail(group, factor, quantile)
        ew_ret = float(group[fwd_col].mean())
        bottom_ret = float(bottom[fwd_col].mean())
        top_ret = float(top[fwd_col].mean())

        sec_bottom = []
        sec_top = []
        sec_spread = []
        sectors_used = 0
        for _, sg in group.groupby("sector", sort=False):
            if len(sg) < max(10, int(math.ceil(1.0 / quantile))):
                continue
            b, t = _pick_tail(sg, factor, quantile)
            if b.empty or t.empty:
                continue
            b_ret = float(b[fwd_col].mean())
            t_ret = float(t[fwd_col].mean())
            sec_bottom.append(b_ret)
            sec_top.append(t_ret)
            sec_spread.append(b_ret - t_ret)
            sectors_used += 1

        rows.append({
            "date": _iso(date),
            "n_universe": int(len(group)),
            "n_tail": int(len(bottom)),
            "factor": factor,
            "horizon": horizon,
            "quantile": quantile,
            "ew_return": ew_ret,
            "bottom_return": bottom_ret,
            "top_return": top_ret,
            "bottom_minus_ew": bottom_ret - ew_ret,
            "bottom_minus_top": bottom_ret - top_ret,
            "bottom_return_net_full_roundtrip": bottom_ret - ROUND_TRIP_COST,
            "bottom_minus_ew_net_full_roundtrip": bottom_ret - ew_ret - ROUND_TRIP_COST,
            "bottom_minus_top_net_full_roundtrip": bottom_ret - top_ret - 2 * ROUND_TRIP_COST,
            "sector_neutral_bottom_return": _mean_or_none(sec_bottom),
            "sector_neutral_top_return": _mean_or_none(sec_top),
            "sector_neutral_bottom_minus_top": _mean_or_none(sec_spread),
            "n_sectors_used": sectors_used,
        })
    return rows


def summarize_returns(values: list[float], horizon: int) -> dict:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not vals:
        return {"n": 0}
    n = len(vals)
    mean = sum(vals) / n
    std = float(np.std(vals, ddof=1)) if n > 1 else None
    t_stat = mean / (std / math.sqrt(n)) if std and std > 0 else None
    hit_rate = sum(1 for v in vals if v > 0) / n
    years = n * horizon / 252.0
    gross = 1.0
    for v in vals:
        gross *= max(0.000001, 1.0 + v)
    annualized = gross ** (1.0 / years) - 1.0 if years > 0 else None

    ci_payload = {"_status": "insufficient_obs", "n": n}
    if n >= 20:
        ci = bootstrap_ci(vals, bs_mean, B=2000, p=0.1, seed=20260528)
        if ci.get("_status") == "ok":
            ci_payload = {
                "_status": "ok",
                "period_point": ci["point_estimate"],
                "period_lo": ci["ci_lo"],
                "period_hi": ci["ci_hi"],
                "annualized_point": (1.0 + ci["point_estimate"]) ** (252 / horizon) - 1.0,
                "annualized_lo": (1.0 + ci["ci_lo"]) ** (252 / horizon) - 1.0,
                "annualized_hi": (1.0 + ci["ci_hi"]) ** (252 / horizon) - 1.0,
                "p_value": ci["p_value_h0_zero"],
                "straddles_zero": ci["straddles_zero"],
            }

    return {
        "n": n,
        "mean_period_return": mean,
        "std_period_return": std,
        "t_stat": t_stat,
        "hit_rate": hit_rate,
        "annualized_geometric": annualized,
        "bootstrap_mean_ci": ci_payload,
    }


def build_result(
    rows: list[dict],
    start: str,
    end: str,
    liquid_top_n: int,
    factors: tuple[str, ...],
    horizons: tuple[int, ...],
    quantiles: tuple[float, ...],
) -> dict:
    summary = {}
    metrics = (
        "bottom_return",
        "bottom_minus_ew",
        "bottom_minus_top",
        "bottom_return_net_full_roundtrip",
        "bottom_minus_ew_net_full_roundtrip",
        "bottom_minus_top_net_full_roundtrip",
        "sector_neutral_bottom_minus_top",
    )
    for factor in factors:
        summary[factor] = {}
        for horizon in horizons:
            summary[factor][str(horizon)] = {}
            for quantile in quantiles:
                q_rows = [
                    r for r in rows
                    if r["factor"] == factor
                    and int(r["horizon"]) == int(horizon)
                    and abs(float(r["quantile"]) - float(quantile)) < 1e-12
                ]
                payload = {
                    "n_periods": len(q_rows),
                    "avg_n_universe": _mean_or_none([r["n_universe"] for r in q_rows]),
                    "avg_n_tail": _mean_or_none([r["n_tail"] for r in q_rows]),
                    "avg_n_sectors_used": _mean_or_none([r["n_sectors_used"] for r in q_rows]),
                }
                for metric in metrics:
                    payload[metric] = summarize_returns([r.get(metric) for r in q_rows], horizon)
                summary[factor][str(horizon)][str(quantile)] = payload
    return {
        "_meta": {
            "strategy": "pure factor decile/quintile reversal diagnostics",
            "window": [start, end],
            "liquid_top_n": liquid_top_n,
            "factors": list(factors),
            "horizons": list(horizons),
            "quantiles": list(quantiles),
            "rebalance": "non-overlapping; rebalance_every equals horizon",
            "round_trip_cost_assumption": ROUND_TRIP_COST,
            "causal_validation": (
                "Causal logic is unestablished: this tests broad factor "
                "portfolio monotonicity and tradability hints, not an economic mechanism."
            ),
            "numbers_validation": (
                "Specific numbers are validated against this local diagnostic "
                "run and current local panel; they are not calibrated production weights."
            ),
        },
        "summary": summary,
        "daily_rows": rows,
    }


def write_report(result: dict, path: Path) -> None:
    lines = [
        "# Swing Reversal Decile/Quintile Study",
        "",
        f"Window: `{result['_meta']['window'][0]}` to `{result['_meta']['window'][1]}`",
        f"Universe: PIT liquid top `{result['_meta']['liquid_top_n']}`",
        f"Round-trip cost assumption: `{result['_meta']['round_trip_cost_assumption']:.4%}`",
        "",
        "## Summary",
        "",
        "| Factor | H | Q | Bottom ann | Bottom-EW ann | Bottom-Top ann | Net Bottom-EW ann | Sector-neutral spread ann | N |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for factor, by_h in result["summary"].items():
        for h, by_q in by_h.items():
            for q, payload in by_q.items():
                lines.append(
                    "| {factor} | {h} | {q} | {bottom} | {bew} | {bt} | {netbew} | {sec} | {n} |".format(
                        factor=factor,
                        h=h,
                        q=q,
                        bottom=_fmt_ann(payload["bottom_return"]),
                        bew=_fmt_ann(payload["bottom_minus_ew"]),
                        bt=_fmt_ann(payload["bottom_minus_top"]),
                        netbew=_fmt_ann(payload["bottom_minus_ew_net_full_roundtrip"]),
                        sec=_fmt_ann(payload["sector_neutral_bottom_minus_top"]),
                        n=payload["n_periods"],
                    )
                )
    lines += [
        "",
        "## Validation Labels",
        "",
        result["_meta"]["causal_validation"],
        "",
        result["_meta"]["numbers_validation"],
    ]
    path.write_text("\n".join(lines) + "\n")


def _fmt_ann(payload: dict) -> str:
    ci = payload.get("bootstrap_mean_ci", {})
    val = ci.get("annualized_point")
    if val is None:
        val = payload.get("annualized_geometric")
    if val is None:
        return "n/a"
    return f"{float(val):+.2%}"


def selftest() -> int:
    rows = []
    for i in range(20):
        for d in range(15):
            rows.append({
                "ts_code": f"T{i:03d}.SZ",
                "trade_date": f"202401{d + 1:02d}",
                "close": 10 + i + d,
                "vol": 1000 + i,
            })
    df = pd.DataFrame(rows)
    out = add_factor_columns(df, (5,))
    if "momentum_5d" not in out or "fwd_5d" not in out:
        print("SELFTEST FAIL: missing factor columns")
        return 1
    sample = out[(out["ts_code"] == "T000.SZ") & (out["trade_date"] == "20240106")].iloc[0]
    if abs(sample["momentum_5d"] - 0.5) > 1e-12:
        print("SELFTEST FAIL: momentum_5d wrong", sample["momentum_5d"])
        return 1
    result = summarize_returns([0.01, -0.01, 0.02, 0.00] * 10, 5)
    if result["n"] != 40:
        print("SELFTEST FAIL: summary n wrong")
        return 1
    print("SELFTEST PASS swing_reversal_decile_study")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Swing reversal decile/quintile factor study.")
    p.add_argument("--prices", default=str(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet"))
    p.add_argument("--sector-map", default=str(REPO_ROOT / "data_history" / "sector_mapping.json"))
    p.add_argument("--start", default="2006-01-04")
    p.add_argument("--end", default="2026-05-25")
    p.add_argument("--liquid-top-n", type=int, default=500)
    p.add_argument("--factors", default="momentum_5d,momentum_20d,volume_ratio")
    p.add_argument("--horizons", default="5,10")
    p.add_argument("--quantiles", default="0.1,0.2")
    p.add_argument("--min-names", type=int, default=100)
    p.add_argument("--out-json", default=str(REPO_ROOT / "experiments" / "agent_tasks" / "r3_reversal_decile_study.json"))
    p.add_argument("--out-report", default=str(REPO_ROOT / "experiments" / "agent_tasks" / "r3_reversal_decile_study.md"))
    p.add_argument("--no-daily-rows", action="store_true")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        return selftest()

    factors = tuple(x.strip() for x in args.factors.split(",") if x.strip())
    horizons = tuple(int(x.strip()) for x in args.horizons.split(",") if x.strip())
    quantiles = tuple(float(x.strip()) for x in args.quantiles.split(",") if x.strip())

    panel = pd.read_parquet(args.prices)
    liquid_uni = compute_liquid_universe(panel, top_n=args.liquid_top_n)
    all_liquid = {tk for names in liquid_uni.values() for tk in names}
    panel = panel[panel["ts_code"].isin(all_liquid)].reset_index(drop=True)
    panel = add_factor_columns(panel, horizons)
    sector_map = load_sector_map(Path(args.sector_map))

    rows: list[dict] = []
    for factor in factors:
        if factor not in panel.columns:
            raise ValueError(f"unknown factor column: {factor}")
        for horizon in horizons:
            for quantile in quantiles:
                rows.extend(daily_portfolio_rows(
                    panel, liquid_uni, sector_map, args.start, args.end,
                    factor=factor, horizon=horizon, quantile=quantile,
                    min_names=args.min_names,
                ))

    result = build_result(rows, args.start, args.end, args.liquid_top_n,
                          factors, horizons, quantiles)
    json_result = dict(result)
    if args.no_daily_rows:
        json_result["daily_rows"] = []
        json_result["_meta"]["daily_rows_omitted"] = True

    out_json = Path(args.out_json)
    out_report = Path(args.out_report)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(json_result, indent=2, ensure_ascii=False, default=str))
    write_report(result, out_report)
    print(f"wrote {out_json}")
    print(f"wrote {out_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
