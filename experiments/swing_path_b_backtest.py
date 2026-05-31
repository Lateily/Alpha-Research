#!/usr/bin/env python3
"""Experimental Path B weekly inverse swing backtest.

This stays under experiments/ because it is a diagnostic harness, not the
production swing engine. It tests whether the R1 negative IC survives a simple
post-cost portfolio construction loop.
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
from panel_index import PanelIndex, fast_atr  # noqa: E402
from run_swing_backtest_fast import (  # noqa: E402
    _same_gross_benchmark_curve,
    fill_price,
    is_limit_down,
    is_limit_up,
    trade_cost,
)
from stationary_bootstrap import bootstrap_ci, mean as bs_mean  # noqa: E402


def _yyyymmdd(d: str) -> str:
    return d.replace("-", "")[:8]


def _score_path_b(idx: PanelIndex, ticker: str, as_of: str) -> Optional[dict]:
    hist = idx.history(ticker, as_of, n_days_back=80)
    closes = hist.get("close")
    vols = hist.get("vol")
    lows = hist.get("low")
    pct_chg = hist.get("pct_chg")
    if closes is None or vols is None or len(closes) < 21 or len(vols) < 21:
        return None
    close = float(closes[-1])
    if close <= 0:
        return None

    atr = fast_atr(idx, ticker, as_of, 14)
    if atr is None or atr / close > 0.08:
        return None

    # Avoid buying a close-at-limit-down knife; T+1 fill can still reject opens.
    if pct_chg is not None and lows is not None and len(pct_chg) > 0:
        if float(pct_chg[-1]) <= -9.5 and float(closes[-1]) <= float(lows[-1]):
            return None

    mom_5d = close / float(closes[-6]) - 1.0 if len(closes) >= 6 and closes[-6] > 0 else None
    if mom_5d is None or not math.isfinite(mom_5d):
        return None
    inverse_mom = max(-0.20, min(0.20, -mom_5d))
    inverse_mom_norm = (inverse_mom + 0.20) / 0.40

    mean_v20 = float(np.mean(vols[-21:-1]))
    vol_ratio = float(vols[-1]) / max(mean_v20, 1.0)
    no_spike = 1.0 if vol_ratio < 1.20 else 0.0
    composite = 100.0 * (0.50 * inverse_mom_norm + 0.50 * no_spike)
    return {
        "composite": composite,
        "momentum_5d": mom_5d,
        "volume_ratio": vol_ratio,
        "atr_pct": atr / close,
    }


def _daily_return_curve(curve: list[dict], key: str = "nav") -> list[float]:
    vals = [float(row[key]) for row in curve if row.get(key) is not None]
    return [vals[i] / vals[i - 1] - 1.0 for i in range(1, len(vals)) if vals[i - 1] > 0]


def _alpha_ci(strat_curve: list[dict], bench_curve: list[dict]) -> dict:
    sr = _daily_return_curve(strat_curve, "nav")
    br = _daily_return_curve(bench_curve, "equity")
    n = min(len(sr), len(br))
    if n < 20:
        return {"_status": "insufficient_obs", "n": n}
    alpha = [sr[i] - br[i] for i in range(n)]
    ci = bootstrap_ci(alpha, bs_mean, B=2000, p=0.1, seed=1729)
    if ci.get("_status") != "ok":
        return ci
    return {
        "_status": "ok",
        "n": n,
        "daily_point": ci["point_estimate"],
        "daily_ci_lo": ci["ci_lo"],
        "daily_ci_hi": ci["ci_hi"],
        "annualized_point": (1.0 + ci["point_estimate"]) ** 252 - 1.0,
        "annualized_lo": (1.0 + ci["ci_lo"]) ** 252 - 1.0,
        "annualized_hi": (1.0 + ci["ci_hi"]) ** 252 - 1.0,
        "p_value": ci["p_value_h0_zero"],
        "straddles_zero": ci["straddles_zero"],
    }


def run_path_b(
    panel: pd.DataFrame,
    start: str,
    end: str,
    *,
    capital: float = 10_000_000.0,
    liquid_top_n: int = 300,
    max_positions: int = 8,
    gross_cap: float = 0.50,
    hold_days: int = 5,
    rebalance_every: int = 5,
) -> dict:
    start_y = _yyyymmdd(start)
    end_y = _yyyymmdd(end)
    liquid_uni = compute_liquid_universe(panel, top_n=liquid_top_n)
    all_liquid = {tk for names in liquid_uni.values() for tk in names}
    idx = PanelIndex(panel[panel["ts_code"].isin(all_liquid)].reset_index(drop=True))
    dates = [d for d in idx.all_trade_dates() if start_y <= d <= end_y]
    if len(dates) < 30:
        return {"_status": "insufficient_dates", "n_dates": len(dates)}

    cash = capital
    positions: dict[str, dict] = {}
    peak = capital
    equity_curve: list[dict] = []
    bench_curve: list[dict] = []
    trade_log: list[dict] = []
    bench_eq = capital

    for i, date in enumerate(dates[:-1]):
        nav = cash
        for tk, pos in positions.items():
            row = idx.row_at(tk, date)
            if row:
                nav += pos["units"] * row["close"]
        peak = max(peak, nav)
        dd = nav / peak - 1.0 if peak > 0 else 0.0

        next_date = dates[i + 1]
        exits = []
        for tk, pos in positions.items():
            row = idx.row_at(tk, date)
            if not row:
                continue
            mtm = row["close"] / pos["entry_price"] - 1.0 if pos["entry_price"] > 0 else 0.0
            if mtm <= -0.08:
                exits.append((tk, "sell_hard_stop"))
            elif pos.get("days_held", 0) >= hold_days:
                exits.append((tk, "sell_time_stop"))

        for tk, action in exits:
            row = idx.row_at(tk, next_date)
            if not row or is_limit_down(row):
                continue
            pos = positions.get(tk)
            if not pos:
                continue
            price = fill_price(row, "sell")
            if price is None:
                continue
            notional = pos["units"] * price
            cost = trade_cost(notional, "sell")
            cash += notional - cost
            trade_log.append({
                "date": next_date, "ts_code": tk, "side": "sell",
                "action": action, "price": round(price, 4),
                "notional": round(notional, 2), "cost": round(cost, 4),
            })
            positions.pop(tk, None)

        if i % rebalance_every == 0:
            candidates = []
            for tk in liquid_uni.get(date, []):
                if tk in positions:
                    continue
                score = _score_path_b(idx, tk, date)
                if score is not None:
                    candidates.append((score["composite"], tk, score))
            candidates.sort(key=lambda item: (-item[0], item[1]))
            slots = max(0, max_positions - len(positions))
            weight = gross_cap / max_positions if max_positions > 0 else 0.0
            for _, tk, score in candidates[:slots]:
                row = idx.row_at(tk, next_date)
                if not row or is_limit_up(row):
                    continue
                target = nav * weight
                if cash < target * 1.01:
                    continue
                price = fill_price(row, "buy")
                if price is None:
                    continue
                units = target / price
                cost = trade_cost(target, "buy")
                cash -= target + cost
                positions[tk] = {
                    "entry_price": price,
                    "units": units,
                    "days_held": 0,
                    "entry_score": score,
                }
                trade_log.append({
                    "date": next_date, "ts_code": tk, "side": "buy",
                    "action": "open_path_b", "price": round(price, 4),
                    "notional": round(target, 2), "cost": round(cost, 4),
                    "composite": round(score["composite"], 4),
                    "momentum_5d": round(score["momentum_5d"], 6),
                    "volume_ratio": round(score["volume_ratio"], 4),
                })

        for pos in positions.values():
            pos["days_held"] = pos.get("days_held", 0) + 1

        next_nav = cash
        for tk, pos in positions.items():
            row = idx.row_at(tk, next_date)
            if row:
                next_nav += pos["units"] * row["close"]
        gross = (next_nav - cash) / next_nav if next_nav > 0 else 0.0
        equity_curve.append({
            "date": next_date,
            "nav": round(next_nav, 2),
            "cash": round(cash, 2),
            "gross": round(gross, 6),
            "n_positions": len(positions),
            "drawdown": round(next_nav / max(peak, next_nav) - 1.0, 6),
        })

        rets = []
        for tk in liquid_uni.get(next_date, []):
            row = idx.row_at(tk, next_date)
            if row and row.get("pct_chg") is not None and not np.isnan(row["pct_chg"]):
                rets.append(row["pct_chg"] / 100.0)
        if rets:
            bench_eq *= 1.0 + sum(rets) / len(rets)
        bench_curve.append({"date": next_date, "equity": round(bench_eq, 2)})

    eq = [row["nav"] for row in equity_curve]
    daily = _daily_return_curve(equity_curve, "nav")
    n_years = len(eq) / 252.0
    cagr = (eq[-1] / eq[0]) ** (1.0 / n_years) - 1.0 if eq and n_years > 0 else None
    avg = sum(daily) / len(daily) if daily else 0.0
    std = statistics_stdev(daily)
    sharpe = avg / std * math.sqrt(252) if std and std > 0 else None
    max_dd = min((row["drawdown"] for row in equity_curve), default=0.0)
    daily_rf = (1 + 0.02) ** (1 / 252) - 1
    same_gross = _same_gross_benchmark_curve(bench_curve, equity_curve, capital, daily_rf)

    return {
        "_meta": {
            "strategy": "Path B weekly inverse diagnostic",
            "window": [start, end],
            "capital": capital,
            "liquid_top_n": liquid_top_n,
            "max_positions": max_positions,
            "gross_cap": gross_cap,
            "hold_days": hold_days,
            "rebalance_every": rebalance_every,
            "causal_validation": (
                "Causal logic is unestablished: this tests whether R1 negative "
                "IC survives a simple portfolio loop, not why the effect exists."
            ),
            "numbers_validation": (
                "Specific numbers are validated only for this local diagnostic "
                "run and are not production-calibrated thresholds."
            ),
        },
        "cagr": cagr,
        "sharpe_annualized": sharpe,
        "max_drawdown": max_dd,
        "final_nav": eq[-1] if eq else capital,
        "avg_gross": float(np.mean([r["gross"] for r in equity_curve])) if equity_curve else 0.0,
        "max_n_positions": max((r["n_positions"] for r in equity_curve), default=0),
        "n_total_trades": len(trade_log),
        "annualized_trades": len(trade_log) / n_years if n_years > 0 else 0.0,
        "alpha_vs_same_gross_ew": _alpha_ci(equity_curve, same_gross),
        "alpha_vs_raw_ew": _alpha_ci(equity_curve, bench_curve),
        "equity_curve": equity_curve,
        "benchmarks": {
            "ew_500": bench_curve,
            "ew_500_same_gross": same_gross,
        },
        "trade_log_full": trade_log,
    }


def statistics_stdev(xs: list[float]) -> Optional[float]:
    if len(xs) < 2:
        return None
    mean = sum(xs) / len(xs)
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Experimental Path B weekly inverse swing backtest.")
    p.add_argument("--prices", default=str(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet"))
    p.add_argument("--start", default="2025-05-26")
    p.add_argument("--end", default="2026-05-25")
    p.add_argument("--liquid-top-n", type=int, default=300)
    p.add_argument("--hold-days", type=int, default=5)
    p.add_argument("--gross-cap", type=float, default=0.50)
    p.add_argument("--max-positions", type=int, default=8)
    p.add_argument("--out", default=str(REPO_ROOT / "experiments" / "agent_tasks" / "path_b_backtest.json"))
    args = p.parse_args(argv)

    panel = pd.read_parquet(args.prices)
    result = run_path_b(
        panel,
        args.start,
        args.end,
        liquid_top_n=args.liquid_top_n,
        max_positions=args.max_positions,
        gross_cap=args.gross_cap,
        hold_days=args.hold_days,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    alpha = result.get("alpha_vs_same_gross_ew") or {}
    print(
        f"CAGR={result.get('cagr', 0) or 0:+.2%} "
        f"Sharpe={result.get('sharpe_annualized')} "
        f"MaxDD={result.get('max_drawdown', 0):+.2%} "
        f"same_gross_alpha={alpha.get('annualized_point')} "
        f"CI=[{alpha.get('annualized_lo')}, {alpha.get('annualized_hi')}]"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
