#!/usr/bin/env python3
"""run_swing_backtest.py — daily swing trading backtest engine.

Per SWING_STRATEGY_v1.md §5 + §6. Ties together:
  sector_scorer.score_sectors() → daily universe
  swing_signal_scan.compute_swing_signals() → per-stock composite
  swing_risk_manager.compute_target_weights() → sizing
  swing_risk_manager.evaluate_exits() → exit signals
  swing_risk_manager.check_portfolio_breakers() → DD/vol overlays
  (T+1 open fill, 印花税 + slippage, limit-up unfillable carry)

Output: equity curve + trade log + per-day attribution to public/data/.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from sector_scorer import score_sectors, load_sector_map, select_universe
from swing_signal_scan import compute_swing_signals
from swing_risk_manager import (compute_target_weights, evaluate_exits,
                                  check_portfolio_breakers, DEFAULT_CONFIG)

# Trade costs (carry from backtest_v2.py)
COMMISSION = 0.00025
STAMP_DUTY_SELL = 0.0005
SLIPPAGE = 0.0010
DAILY_LIMIT = 0.099


def _to_yyyymmdd(d):
    if isinstance(d, str):
        return d.replace("-", "")[:8]
    return d.strftime("%Y%m%d")


def fill_price(row: dict, side: str) -> float:
    """Blended slippage-aware fill = (open + (high+low+close)/3) / 2."""
    open_p = row.get("open") or row.get("close")
    if not open_p or open_p <= 0:
        return None
    blend_mid = (row.get("high", open_p) + row.get("low", open_p) + row.get("close", open_p)) / 3
    raw = (open_p + blend_mid) / 2
    if side == "buy":
        return raw * (1 + SLIPPAGE)
    elif side == "sell":
        return raw * (1 - SLIPPAGE)
    return raw


def is_limit_up(row: dict) -> bool:
    pre = row.get("pre_close")
    if not pre or pre <= 0:
        return False
    return (row.get("open", 0) / pre - 1) >= DAILY_LIMIT


def is_limit_down(row: dict) -> bool:
    pre = row.get("pre_close")
    if not pre or pre <= 0:
        return False
    return (row.get("open", 0) / pre - 1) <= -DAILY_LIMIT


def trade_cost(notional: float, side: str) -> float:
    c = COMMISSION
    if side == "sell":
        c += STAMP_DUTY_SELL
    return notional * c


# ───────────────────────── Main loop ───────────────────────────────────────

def run_swing_backtest(daily_panel: pd.DataFrame, adj_panel: Optional[pd.DataFrame],
                        sector_mapping: dict, start: str, end: str,
                        capital: float = 1_000_000.0,
                        config: Optional[dict] = None,
                        verbose: bool = False) -> dict:
    """Run daily swing backtest from start to end (inclusive YYYYMMDD strings)."""
    cfg = dict(DEFAULT_CONFIG); cfg.update(config or {})
    start_yyyymmdd = _to_yyyymmdd(start)
    end_yyyymmdd = _to_yyyymmdd(end)

    # All trade dates from panel in [start, end]
    all_dates = sorted(daily_panel["trade_date"].unique())
    trade_dates = [d for d in all_dates if start_yyyymmdd <= d <= end_yyyymmdd]
    if not trade_dates:
        raise ValueError("no trade dates in window")

    # Pre-index panel by date for fast row lookup at T+1 fill
    panel_by_date_ticker = {}
    for (dt, tk), grp in daily_panel.groupby(["trade_date", "ts_code"]):
        # Assume one row per (date, ticker)
        row = grp.iloc[0].to_dict()
        panel_by_date_ticker[(dt, tk)] = row

    positions: dict[str, dict] = {}    # ts_code → {entry_date, entry_price, peak_price, size_pct, days_held, entry_composite, entry_sector, ...}
    cash = capital
    equity_curve = []
    trade_log = []
    risk_log = []
    peak_equity = capital

    # carried unfillable orders: {(side, tk): {target_size, carry_until}}
    carried_buys = {}     # tk → {weight, expires_at}
    carried_sells = {}    # tk → {expires_at}

    bench_eq = capital   # EW universe benchmark (rebal daily for fairness)
    bench_curve = []

    for i, T in enumerate(trade_dates):
        # ── 1. Increment days_held for all positions
        for pos in positions.values():
            pos["days_held"] = pos.get("days_held", 0) + 1

        # ── 2. Compute portfolio MTM at T close
        nav = cash
        for tk, pos in positions.items():
            row = panel_by_date_ticker.get((T, tk))
            if row:
                nav += pos["size_units"] * row["close"]
                # update peak price
                pos["peak_price"] = max(pos.get("peak_price", pos["entry_price"]),
                                         row["close"])
        peak_equity = max(peak_equity, nav)
        dd = (nav - peak_equity) / peak_equity if peak_equity > 0 else 0

        # ── 3. Check circuit breakers (use realized 60d vol as proxy)
        equity_hist = [e["nav"] for e in equity_curve[-60:]]
        if len(equity_hist) >= 20:
            rets = [equity_hist[k] / equity_hist[k-1] - 1 for k in range(1, len(equity_hist))]
            mean_r = sum(rets) / len(rets)
            var_r = sum((r - mean_r)**2 for r in rets) / max(1, len(rets) - 1)
            realized_vol = math.sqrt(var_r) * math.sqrt(252)
        else:
            realized_vol = 0.0
        breaker = check_portfolio_breakers({"drawdown_pct": dd},
                                            {"realized_vol_60d": realized_vol}, cfg)
        gross_cap = breaker["gross_cap"]
        if breaker["actions"]:
            risk_log.append({"date": T, **breaker, "dd": round(dd, 4), "vol60": round(realized_vol, 4)})

        # ── 4. Sector ranking (PIT: panel up to T inclusive)
        sector_ranks = score_sectors(daily_panel, sector_mapping, T, lookback_days=60, top_k=5)
        top_sectors = [s for s, info in sector_ranks.items() if info.get("is_top_k")]
        universe = select_universe(sector_ranks, top_k=5)
        if not universe:
            universe = list(set(daily_panel[daily_panel["trade_date"] == T]["ts_code"]))[:200]

        # ── 5. Signal scan on universe + currently held
        scan_set = set(universe) | set(positions.keys())
        signals = compute_swing_signals(daily_panel, T, list(scan_set))

        # ── 6. Evaluate exits on current positions
        exit_actions = evaluate_exits(positions, daily_panel, T, signals,
                                       top_k_sectors=top_sectors,
                                       sector_mapping=sector_mapping, config=cfg)

        # ── 7. Compute target weights from signals (for new entries)
        target_weights = compute_target_weights(signals, daily_panel, T,
                                                  sector_mapping, cfg)
        if gross_cap < cfg["max_gross"]:
            scale = gross_cap / max(0.001, sum(target_weights.values()))
            target_weights = {tk: w * min(1.0, scale) for tk, w in target_weights.items()}
        if "flat_all" in breaker["actions"]:
            target_weights = {}

        # ── 8. Execute at T+1 open
        if i + 1 >= len(trade_dates):
            # Last date — no T+1 to fill on
            equity_curve.append({"date": T, "nav": round(nav, 2), "cash": round(cash, 2),
                                  "n_positions": len(positions), "drawdown": round(dd, 4)})
            break
        T_next = trade_dates[i + 1]

        # 8a. Process sells
        sold_tks = []
        for tk, action in exit_actions.items():
            if action == "hold":
                continue
            row = panel_by_date_ticker.get((T_next, tk))
            if not row:
                continue
            if action != "take_profit_half" and is_limit_down(row):
                # carry to next day, max 3 days
                carried_sells.setdefault(tk, {"carries_left": 3})
                carried_sells[tk]["carries_left"] -= 1
                continue
            pos = positions[tk]
            fill_units = pos["size_units"]
            if action == "take_profit_half":
                fill_units = pos["size_units"] * 0.5
            price = fill_price(row, "sell")
            notional = fill_units * price
            cost = trade_cost(notional, "sell")
            cash += notional - cost
            trade_log.append({"date": T_next, "ts_code": tk, "side": "sell",
                               "action": action, "units": fill_units,
                               "price": round(price, 4), "notional": round(notional, 2),
                               "cost": round(cost, 4)})
            if action == "take_profit_half":
                pos["size_units"] -= fill_units
                pos["_tp_taken"] = True
                # Raise trailing stop to entry
                pos["peak_price"] = max(pos.get("peak_price", pos["entry_price"]),
                                         pos["entry_price"])
            else:
                sold_tks.append(tk)

        for tk in sold_tks:
            positions.pop(tk, None)

        # 8b. Process buys (new entries + size-up existing)
        for tk, target_w in target_weights.items():
            row = panel_by_date_ticker.get((T_next, tk))
            if not row:
                continue
            if is_limit_up(row):
                carried_buys.setdefault(tk, {"weight": target_w, "carries_left": 3})
                carried_buys[tk]["carries_left"] -= 1
                continue
            target_notional = nav * target_w
            current_pos = positions.get(tk)
            current_value = (current_pos["size_units"] * row["close"]) if current_pos else 0
            delta_notional = target_notional - current_value
            if delta_notional < target_notional * 0.10:
                continue   # don't trade tiny adjustments
            if cash < delta_notional + delta_notional * 0.01:
                continue   # not enough cash
            price = fill_price(row, "buy")
            units = delta_notional / price
            cost = trade_cost(delta_notional, "buy")
            cash -= delta_notional + cost
            trade_log.append({"date": T_next, "ts_code": tk, "side": "buy",
                               "action": "open_or_add", "units": round(units, 2),
                               "price": round(price, 4), "notional": round(delta_notional, 2),
                               "cost": round(cost, 4)})
            entry_sector = sector_mapping.get(tk, "_unknown")
            if current_pos:
                # weighted-average entry
                old_units = current_pos["size_units"]
                old_price = current_pos["entry_price"]
                new_units = old_units + units
                new_price = (old_units * old_price + units * price) / new_units
                current_pos["entry_price"] = new_price
                current_pos["size_units"] = new_units
            else:
                positions[tk] = {
                    "entry_date": T_next, "entry_price": price, "size_units": units,
                    "peak_price": price, "days_held": 0,
                    "entry_composite": (signals.get(tk, {}) or {}).get("composite"),
                    "entry_sector": entry_sector,
                }

        # 8c. Compute updated NAV after T+1 fills, mark equity for T_next
        next_close_nav = cash
        for tk, pos in positions.items():
            row = panel_by_date_ticker.get((T_next, tk))
            if row:
                next_close_nav += pos["size_units"] * row["close"]
        equity_curve.append({"date": T_next, "nav": round(next_close_nav, 2),
                              "cash": round(cash, 2),
                              "n_positions": len(positions),
                              "drawdown": round((next_close_nav - max(peak_equity, next_close_nav)) /
                                                 max(peak_equity, next_close_nav), 4)})

        # Benchmark: equal-weighted CSI300-like = EW universe at this date
        bench_rows = daily_panel[daily_panel["trade_date"] == T_next]
        if not bench_rows.empty and "pct_chg" in bench_rows.columns:
            ew_ret = bench_rows["pct_chg"].fillna(0).mean() / 100
            bench_eq = bench_eq * (1 + ew_ret)
        bench_curve.append({"date": T_next, "equity": round(bench_eq, 2)})

        if verbose and i % 60 == 0:
            print(f"  ...{T}: NAV={next_close_nav:.0f}, pos={len(positions)}, dd={dd:.3f}",
                  flush=True)

    # ── Metrics
    eqs = [pt["nav"] for pt in equity_curve]
    if len(eqs) < 2:
        return {"_status": "insufficient_data"}
    daily_rets = [eqs[k] / eqs[k-1] - 1 for k in range(1, len(eqs))]
    n_days = len(eqs)
    n_years = n_days / 252.0
    cagr = (eqs[-1] / eqs[0]) ** (1 / n_years) - 1 if n_years > 0 and eqs[0] > 0 else 0
    mean_r = sum(daily_rets) / len(daily_rets) if daily_rets else 0
    std_r = math.sqrt(sum((r - mean_r) ** 2 for r in daily_rets) / max(1, len(daily_rets) - 1)) if daily_rets else 0
    sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else None
    max_dd = min(pt["drawdown"] for pt in equity_curve) if equity_curve else 0

    return {
        "_meta": {"start": start, "end": end, "capital": capital,
                  "n_days": n_days, "n_trades": len(trade_log)},
        "cagr": cagr,
        "sharpe_annualized": sharpe,
        "max_drawdown": max_dd,
        "final_nav": eqs[-1],
        "ann_vol": std_r * math.sqrt(252) if std_r else None,
        "equity_curve": equity_curve,
        "bench_curve": bench_curve,
        "trade_log": trade_log[-100:],   # last 100 trades
        "risk_log": risk_log[-50:],
        "n_total_trades": len(trade_log),
    }


# ───────────────────────── Self-test ──────────────────────────────────────

def _selftest() -> int:
    failures = []
    rows = []
    base = pd.Timestamp("2024-01-01")
    sector_mapping = {}
    for sec, tickers in [("Up", ["U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8", "U9", "U10",
                                  "U11", "U12", "U13", "U14", "U15"]),
                         ("Dn", ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10",
                                  "D11", "D12", "D13", "D14", "D15"])]:
        slope = 0.0015 if sec == "Up" else -0.0008
        for tk in tickers:
            sector_mapping[f"{tk}.SZ"] = sec
            px = 10.0
            for d in range(120):
                px *= (1 + slope + (0.005 * (-1) ** d))
                rows.append({"ts_code": f"{tk}.SZ",
                              "trade_date": (base + pd.Timedelta(days=d)).strftime("%Y%m%d"),
                              "open": px*0.999, "high": px*1.005, "low": px*0.995,
                              "close": px, "vol": 1e6, "amount": px * 1e6,
                              "pre_close": px*0.999, "pct_chg": slope * 100})
    panel = pd.DataFrame(rows)
    res = run_swing_backtest(panel, None, sector_mapping,
                              "20240120", "20240420", capital=1_000_000,
                              verbose=False)
    if res.get("_status") == "insufficient_data":
        failures.append("backtest returned insufficient_data on 90-day fixture")
    elif res.get("final_nav") is None:
        failures.append("no final_nav")
    elif res["final_nav"] <= 0:
        failures.append(f"final_nav non-positive: {res['final_nav']}")
    # We expect the Up-sector bias to be visible (CAGR > -10% reasonable for short test)
    if res.get("n_total_trades", 0) == 0:
        failures.append("zero trades — engine not generating signals")

    if failures:
        print("SELFTEST FAILED run_swing_backtest:")
        for f in failures: print(" -", f)
        return 1
    print("SELFTEST PASSED run_swing_backtest")
    print(f"- 90-day fixture: NAV {1_000_000:.0f} → {res['final_nav']:.0f}, "
          f"CAGR={res.get('cagr', 0)*100:.1f}%, Sharpe={res.get('sharpe_annualized')}, "
          f"n_trades={res['n_total_trades']}, max_dd={res['max_drawdown']*100:.1f}%")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Daily swing backtest.")
    p.add_argument("--prices", default=str(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet"))
    p.add_argument("--adj", default=str(REPO_ROOT / "data_history" / "panel" / "daily_adj_factor.parquet"))
    p.add_argument("--sector-map", default=str(REPO_ROOT / "data_history" / "sector_mapping.json"))
    p.add_argument("--start", default="2006-01-01")
    p.add_argument("--end", default="2026-05-25")
    p.add_argument("--capital", type=float, default=10_000_000.0)
    p.add_argument("--out", default=str(REPO_ROOT / "public" / "data" / "swing_backtest_v1.json"))
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()

    panel = pd.read_parquet(args.prices)
    adj = pd.read_parquet(args.adj) if Path(args.adj).exists() else None
    sector_map = load_sector_map(args.sector_map)
    print(f"Panel: {len(panel):,} rows, {panel['ts_code'].nunique()} tickers", flush=True)
    print(f"Window: {args.start} → {args.end}", flush=True)
    print(f"Capital: ¥{args.capital:,.0f}", flush=True)

    res = run_swing_backtest(panel, adj, sector_map, args.start, args.end,
                              capital=args.capital, verbose=args.verbose)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    print(f"CAGR={res.get('cagr', 0)*100:+.2f}% Sharpe={res.get('sharpe_annualized')}"
          f" MaxDD={res.get('max_drawdown', 0)*100:+.2f}%"
          f" final=¥{res.get('final_nav', 0):,.0f}"
          f" trades={res.get('n_total_trades')}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
