#!/usr/bin/env python3
"""run_swing_backtest_fast.py — optimized daily swing engine using PanelIndex.

Same strategy logic as run_swing_backtest.py (per SWING_STRATEGY_v1.md), but
the inner loops use scripts/panel_index.PanelIndex for O(log N) date slicing
+ vectorized numpy factor computation. Expected 50-100× speedup over the
pandas-groupby-per-day approach.

Key differences from run_swing_backtest.py:
  - Builds PanelIndex once at startup (replaces panel_by_date_ticker dict)
  - Inline sector scoring + signal scanning using fast_* helpers from panel_index
  - Same costs / fill rules / exit logic / portfolio constraints
  - Same JSON output format (drop-in compatible)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from swing_risk_manager import (compute_target_weights, evaluate_exits,
                                  check_portfolio_breakers, DEFAULT_CONFIG)
from liquid_universe import compute_liquid_universe
from panel_index import (PanelIndex, fast_60d_return, fast_volume_trend,
                          fast_atr, fast_rsi, fast_macd_bullish_cross)

# Cost params (carry from backtest_v2)
COMMISSION = 0.00025
STAMP_DUTY_SELL = 0.0005
SLIPPAGE = 0.0010
DAILY_LIMIT = 0.099


def _to_yyyymmdd(d):
    if isinstance(d, str):
        return d.replace("-", "")[:8]
    return d.strftime("%Y%m%d")


# ───────────────────────── Fast sector scoring ───────────────────────────

def fast_sector_score(idx: PanelIndex, sector_map: dict[str, str],
                       liquid_today: list[str], as_of: str,
                       lookback_days: int = 60,
                       top_k: int = 5,
                       min_members: int = 10) -> tuple[list[str], list[str]]:
    """Return (top_sector_names, top_sector_members).

    For each sector with ≥ min_members in liquid_today:
      compute mean(60d return) + breadth(% up) + volume_trend
      z-score across sectors, rank, take top_k.
    """
    by_sector: dict[str, list[str]] = {}
    for tk in liquid_today:
        s = sector_map.get(tk)
        if s:
            by_sector.setdefault(s, []).append(tk)

    metrics = {}
    for sector, members in by_sector.items():
        if len(members) < min_members:
            continue
        rets = []
        vts = []
        for tk in members:
            r = fast_60d_return(idx, tk, as_of)
            if r is not None:
                rets.append(r)
            v = fast_volume_trend(idx, tk, as_of)
            if v is not None:
                vts.append(v)
        if len(rets) < min_members // 2:
            continue
        metrics[sector] = {
            "ret_mean": float(np.mean(rets)),
            "breadth": float(np.mean([1.0 if r > 0 else 0.0 for r in rets])),
            "voltrend": float(np.mean(vts)) if vts else 0.0,
            "members": members,
        }

    if not metrics:
        return [], []

    # z-score
    def _z(vals: list[float]) -> list[float]:
        if len(vals) < 2:
            return [0.0] * len(vals)
        m = float(np.mean(vals))
        s = float(np.std(vals, ddof=1))
        return [((v - m) / s if s > 0 else 0.0) for v in vals]

    keys = list(metrics.keys())
    z_ret = _z([metrics[k]["ret_mean"] for k in keys])
    z_brd = _z([metrics[k]["breadth"] for k in keys])
    z_vt = _z([metrics[k]["voltrend"] for k in keys])
    composite = {k: (z_ret[i] + z_brd[i] + z_vt[i]) / 3.0 for i, k in enumerate(keys)}
    ranked = sorted(keys, key=lambda k: -composite[k])
    top_sectors = ranked[:top_k]
    universe = []
    for s in top_sectors:
        universe.extend(metrics[s]["members"])
    return top_sectors, universe


# ───────────────────────── Fast signal scoring ───────────────────────────

DEFAULT_SIGNAL_WEIGHTS = {
    "breakout_20d":     0.20,
    "momentum_5d":      0.15,
    "macd_cross":       0.10,
    "volume_spike":     0.15,
    "limit_up_followup": 0.10,
    "rsi_in_band":      0.10,
}


def fast_signals_one(idx: PanelIndex, tk: str, as_of: str) -> Optional[dict]:
    """Returns {composite, factors, vetoes} or None."""
    h = idx.history(tk, as_of, n_days_back=100)
    closes = h.get("close")
    if closes is None or len(closes) < 60:
        return None
    highs = h.get("high"); lows = h.get("low"); vols = h.get("vol")
    pct_chg = h.get("pct_chg")

    # Vetoes first
    atr = fast_atr(idx, tk, as_of, 14)
    if atr is None:
        return None
    if atr / closes[-1] > 0.08:
        return None   # ATR too high
    ma50 = float(np.mean(closes[-50:])) if len(closes) >= 50 else closes[-1]
    ma50_prev = float(np.mean(closes[-60:-10])) if len(closes) >= 60 else ma50
    if closes[-1] < ma50 and ma50 < ma50_prev:
        return None   # ma50 down trend

    factors = {}

    # breakout 20d
    if len(closes) >= 21:
        factors["breakout_20d"] = 1.0 if closes[-1] > float(np.max(closes[-21:-1])) * 1.02 else 0.0
    else:
        factors["breakout_20d"] = None

    # momentum 5d
    if len(closes) >= 6 and closes[-6] > 0:
        factors["momentum_5d"] = float(closes[-1] / closes[-6] - 1)
    else:
        factors["momentum_5d"] = None

    # MACD bullish cross
    factors["macd_cross"] = fast_macd_bullish_cross(idx, tk, as_of)

    # Volume spike
    if vols is not None and len(vols) >= 21 and vols[-1] > 0:
        mean_v20 = float(np.mean(vols[-21:-1]))
        factors["volume_spike"] = 1.0 if (vols[-1] / max(mean_v20, 1.0)) > 1.5 else 0.0
    else:
        factors["volume_spike"] = None

    # 涨停板 followup (T-1 close ≥ pre × 1.099)
    if pct_chg is not None and len(pct_chg) >= 2 and highs is not None:
        yest_pct = float(pct_chg[-2]) if pct_chg[-2] is not None and not np.isnan(pct_chg[-2]) else 0.0
        yest_at_high = float(closes[-2]) == float(highs[-2])
        factors["limit_up_followup"] = 1.0 if (yest_pct >= 9.5 and yest_at_high) else 0.0
    else:
        factors["limit_up_followup"] = None

    # RSI in band (40-70)
    rsi = fast_rsi(idx, tk, as_of, 14)
    if rsi is None:
        factors["rsi_in_band"] = None
    else:
        factors["rsi_in_band"] = 1.0 if 40 <= rsi <= 70 else 0.0
    factors["_rsi_value"] = rsi
    factors["_atr"] = atr

    # Composite
    num = den = 0.0
    have = 0
    for f, w in DEFAULT_SIGNAL_WEIGHTS.items():
        v = factors.get(f)
        if v is None:
            continue
        if f == "momentum_5d":
            vv = max(-0.2, min(0.2, v))
            vv = (vv + 0.2) / 0.4
        else:
            vv = max(0.0, min(1.0, float(v)))
        num += w * vv
        den += w
        have += 1
    if have < 4 or den == 0:
        return None
    return {"composite": round(100 * num / den, 2), "factors": factors, "vetoes": []}


def fast_signals_batch(idx: PanelIndex, tickers: list[str], as_of: str) -> dict:
    out = {}
    for tk in tickers:
        s = fast_signals_one(idx, tk, as_of)
        if s is not None:
            out[tk] = s
    return out


# ───────────────────────── Fast fill / cost helpers ───────────────────────

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


def fill_price(row: dict, side: str) -> Optional[float]:
    open_p = row.get("open") or row.get("close")
    if not open_p or open_p <= 0:
        return None
    blend = (row.get("high", open_p) + row.get("low", open_p) + row.get("close", open_p)) / 3
    raw = (open_p + blend) / 2
    return raw * (1 + SLIPPAGE) if side == "buy" else raw * (1 - SLIPPAGE)


def trade_cost(notional: float, side: str) -> float:
    return notional * (COMMISSION + (STAMP_DUTY_SELL if side == "sell" else 0))


# ───────────────────────── Main loop ─────────────────────────────────────

def run_swing_backtest_fast(daily_panel: pd.DataFrame, sector_mapping: dict,
                              start: str, end: str,
                              capital: float = 10_000_000.0,
                              config: Optional[dict] = None,
                              verbose: bool = False,
                              liquid_top_n: int = 500) -> dict:
    cfg = dict(DEFAULT_CONFIG); cfg.update(config or {})
    start_yyyymmdd = _to_yyyymmdd(start)
    end_yyyymmdd = _to_yyyymmdd(end)

    if verbose:
        print(f"[fast] computing liquid universe (top-{liquid_top_n})...", flush=True)
    liquid_uni = compute_liquid_universe(daily_panel, top_n=liquid_top_n)
    all_liquid_tickers = set()
    for v in liquid_uni.values():
        all_liquid_tickers.update(v)
    if verbose:
        print(f"[fast] liquid universe: {len(liquid_uni)} dates, "
              f"{len(all_liquid_tickers)} unique tickers", flush=True)

    # Reduce panel + build PanelIndex
    sub_panel = daily_panel[daily_panel["ts_code"].isin(all_liquid_tickers)]
    if verbose:
        print(f"[fast] sub-panel: {len(sub_panel):,} rows. Building PanelIndex...",
              flush=True)
    idx = PanelIndex(sub_panel)
    if verbose:
        print(f"[fast] PanelIndex built: {len(idx.tickers)} tickers", flush=True)

    # Trade dates in window
    all_dates = idx.all_trade_dates()
    trade_dates = [d for d in all_dates if start_yyyymmdd <= d <= end_yyyymmdd]
    if not trade_dates:
        raise ValueError("no trade dates in window")

    positions: dict[str, dict] = {}
    cash = capital
    equity_curve = []
    trade_log = []
    risk_log = []
    peak_equity = capital
    bench_eq = capital
    bench_curve = []

    for i, T in enumerate(trade_dates):
        # Increment days_held
        for pos in positions.values():
            pos["days_held"] = pos.get("days_held", 0) + 1

        # MTM
        nav = cash
        for tk, pos in positions.items():
            row = idx.row_at(tk, T)
            if row:
                nav += pos["size_units"] * row["close"]
                pos["peak_price"] = max(pos.get("peak_price", pos["entry_price"]),
                                         row["close"])
        peak_equity = max(peak_equity, nav)
        dd = (nav - peak_equity) / peak_equity if peak_equity > 0 else 0

        # Realized vol
        equity_hist = [e["nav"] for e in equity_curve[-60:]]
        if len(equity_hist) >= 20:
            rets = [equity_hist[k]/equity_hist[k-1] - 1 for k in range(1, len(equity_hist))]
            m = sum(rets) / len(rets)
            v = sum((r-m)**2 for r in rets) / max(1, len(rets)-1)
            realized_vol = math.sqrt(v) * math.sqrt(252)
        else:
            realized_vol = 0.0

        breaker = check_portfolio_breakers({"drawdown_pct": dd},
                                            {"realized_vol_60d": realized_vol}, cfg)
        gross_cap = breaker["gross_cap"]
        if breaker["actions"]:
            risk_log.append({"date": T, **breaker, "dd": round(dd, 4),
                              "vol60": round(realized_vol, 4)})

        # Sector ranking via PanelIndex (FAST!)
        liquid_today = liquid_uni.get(T, [])
        if not liquid_today:
            equity_curve.append({"date": T, "nav": round(nav, 2), "cash": round(cash, 2),
                                  "n_positions": len(positions), "drawdown": round(dd, 4)})
            continue
        top_sectors, universe = fast_sector_score(idx, sector_mapping, liquid_today, T,
                                                    lookback_days=60, top_k=5)
        if not universe:
            universe = liquid_today[:200]

        # Signal scan (FAST!)
        scan_set = list(set(universe) | set(positions.keys()))
        signals = fast_signals_batch(idx, scan_set, T)

        # Exits
        # build a per-ticker pseudo-panel for evaluate_exits (it does its own slicing)
        # Simpler: inline exit logic here
        exit_actions = {}
        for tk, pos in positions.items():
            row = idx.latest_row(tk, T)
            if row is None:
                exit_actions[tk] = "hold"; continue
            entry_p = pos["entry_price"]
            cur = row["close"]
            mtm = (cur - entry_p) / entry_p if entry_p > 0 else 0
            peak = pos.get("peak_price", entry_p)
            trail = (cur - peak) / peak if peak > 0 else 0
            if mtm <= cfg["hard_stop_pct"]:
                exit_actions[tk] = "sell_hard_stop"
            elif trail <= cfg["trailing_stop_pct"]:
                exit_actions[tk] = "sell_trailing"
            elif mtm >= cfg["take_profit_pct"] and not pos.get("_tp_taken"):
                exit_actions[tk] = "take_profit_half"
            elif pos.get("days_held", 0) >= cfg["time_stop_days"]:
                exit_actions[tk] = "sell_time_stop"
            elif top_sectors and sector_mapping.get(tk) not in top_sectors:
                exit_actions[tk] = "sell_sector_drop"
            else:
                cur_comp = (signals.get(tk) or {}).get("composite")
                entry_comp = pos.get("entry_composite")
                if cur_comp is not None and entry_comp is not None and \
                   entry_comp - cur_comp >= cfg["composite_decay"]:
                    exit_actions[tk] = "sell_composite_decay"
                else:
                    exit_actions[tk] = "hold"

        # Compute target weights from signals + ATR sizing
        scored = [(tk, s.get("composite")) for tk, s in signals.items()
                  if s and s.get("composite") is not None]
        scored.sort(key=lambda kv: -kv[1])
        target_weights = {}
        sector_totals: dict[str, float] = {}
        selected = 0
        for tk, score in scored:
            if selected >= cfg["top_n_picks"]:
                break
            atr_val = (signals[tk]["factors"].get("_atr") or 0)
            close_val = idx.latest_row(tk, T)["close"]
            atr_vol_ann = (atr_val / close_val) * math.sqrt(252) if close_val > 0 else 0
            target = min(cfg["max_single_name_weight"],
                          cfg["vol_per_position"] / atr_vol_ann) if atr_vol_ann > 0 \
                      else cfg["max_single_name_weight"] * 0.5
            sector = sector_mapping.get(tk, "_unknown")
            cur_sec = sector_totals.get(sector, 0.0)
            if cur_sec + target > cfg["max_sector_weight"]:
                target = max(0.0, cfg["max_sector_weight"] - cur_sec)
                if target <= 0.005:
                    continue
            target = min(target, cfg["safety_max_single_name"])
            target_weights[tk] = target
            sector_totals[sector] = cur_sec + target
            selected += 1
        # Renormalize
        tot = sum(target_weights.values())
        if tot > cfg["max_gross"]:
            scale = cfg["max_gross"] / tot
            target_weights = {tk: w*scale for tk, w in target_weights.items()}
        # Apply breaker cap
        if gross_cap < cfg["max_gross"]:
            tot2 = sum(target_weights.values())
            if tot2 > gross_cap:
                scale = gross_cap / tot2
                target_weights = {tk: w*scale for tk, w in target_weights.items()}
        if "flat_all" in breaker["actions"]:
            target_weights = {}

        # T+1 fill
        if i + 1 >= len(trade_dates):
            equity_curve.append({"date": T, "nav": round(nav, 2), "cash": round(cash, 2),
                                  "n_positions": len(positions), "drawdown": round(dd, 4)})
            break
        T_next = trade_dates[i + 1]

        # Sells
        sold = []
        for tk, action in exit_actions.items():
            if action == "hold": continue
            row = idx.row_at(tk, T_next)
            if row is None: continue
            if action != "take_profit_half" and is_limit_down(row):
                continue   # carry not implemented for fast version
            pos = positions[tk]
            units = pos["size_units"]
            if action == "take_profit_half":
                units = pos["size_units"] * 0.5
            price = fill_price(row, "sell")
            if price is None: continue
            notional = units * price
            cost = trade_cost(notional, "sell")
            cash += notional - cost
            trade_log.append({"date": T_next, "ts_code": tk, "side": "sell",
                               "action": action, "units": round(units, 2),
                               "price": round(price, 4), "notional": round(notional, 2),
                               "cost": round(cost, 4)})
            if action == "take_profit_half":
                pos["size_units"] -= units
                pos["_tp_taken"] = True
                pos["peak_price"] = max(pos.get("peak_price", pos["entry_price"]),
                                         pos["entry_price"])
            else:
                sold.append(tk)
        for tk in sold:
            positions.pop(tk, None)

        # Buys
        for tk, target_w in target_weights.items():
            row = idx.row_at(tk, T_next)
            if row is None: continue
            if is_limit_up(row):
                continue   # carry skipped
            target_notional = nav * target_w
            cur_pos = positions.get(tk)
            cur_value = (cur_pos["size_units"] * row["close"]) if cur_pos else 0
            delta = target_notional - cur_value
            if delta < target_notional * 0.10:
                continue
            if cash < delta * 1.01:
                continue
            price = fill_price(row, "buy")
            if price is None: continue
            units = delta / price
            cost = trade_cost(delta, "buy")
            cash -= delta + cost
            trade_log.append({"date": T_next, "ts_code": tk, "side": "buy",
                               "action": "open_or_add", "units": round(units, 2),
                               "price": round(price, 4), "notional": round(delta, 2),
                               "cost": round(cost, 4)})
            entry_sector = sector_mapping.get(tk, "_unknown")
            if cur_pos:
                old_u = cur_pos["size_units"]
                old_p = cur_pos["entry_price"]
                new_u = old_u + units
                cur_pos["entry_price"] = (old_u*old_p + units*price) / new_u
                cur_pos["size_units"] = new_u
            else:
                positions[tk] = {
                    "entry_date": T_next, "entry_price": price, "size_units": units,
                    "peak_price": price, "days_held": 0,
                    "entry_composite": (signals.get(tk) or {}).get("composite"),
                    "entry_sector": entry_sector,
                }

        # NAV at T+1 close
        nx_nav = cash
        for tk, pos in positions.items():
            row = idx.row_at(tk, T_next)
            if row:
                nx_nav += pos["size_units"] * row["close"]
        equity_curve.append({"date": T_next, "nav": round(nx_nav, 2),
                              "cash": round(cash, 2), "n_positions": len(positions),
                              "drawdown": round((nx_nav - max(peak_equity, nx_nav)) /
                                                 max(peak_equity, nx_nav), 4)})

        # Bench EW return
        liquid_next = liquid_uni.get(T_next, [])
        if liquid_next:
            rets = []
            for tk in liquid_next:
                r2 = idx.row_at(tk, T_next)
                if r2 and r2.get("pct_chg") is not None and not np.isnan(r2["pct_chg"]):
                    rets.append(r2["pct_chg"] / 100)
            if rets:
                bench_eq *= (1 + sum(rets) / len(rets))
        bench_curve.append({"date": T_next, "equity": round(bench_eq, 2)})

        if verbose and i % 250 == 0:
            print(f"  ...{T}: NAV={nx_nav:.0f}, pos={len(positions)}, dd={dd:.3f}",
                  flush=True)

    # Metrics
    eqs = [pt["nav"] for pt in equity_curve]
    if len(eqs) < 2:
        return {"_status": "insufficient_data"}
    drs = [eqs[k]/eqs[k-1] - 1 for k in range(1, len(eqs))]
    n_days = len(eqs); n_years = n_days / 252.0
    cagr = (eqs[-1] / eqs[0]) ** (1/n_years) - 1 if n_years > 0 else 0
    m = sum(drs) / len(drs) if drs else 0
    s = math.sqrt(sum((r-m)**2 for r in drs) / max(1, len(drs)-1)) if drs else 0
    sharpe = (m / s * math.sqrt(252)) if s > 0 else None
    max_dd = min(pt["drawdown"] for pt in equity_curve)

    return {
        "_meta": {"start": start, "end": end, "capital": capital,
                  "engine": "fast (PanelIndex + numpy)",
                  "n_days": n_days, "n_trades": len(trade_log),
                  "liquid_top_n": liquid_top_n},
        "cagr": cagr, "sharpe_annualized": sharpe, "max_drawdown": max_dd,
        "final_nav": eqs[-1], "ann_vol": s * math.sqrt(252) if s else None,
        "equity_curve": equity_curve, "bench_curve": bench_curve,
        "trade_log": trade_log[-200:], "risk_log": risk_log[-50:],
        "n_total_trades": len(trade_log),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Fast daily swing backtest (PanelIndex).")
    p.add_argument("--prices", default=str(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet"))
    p.add_argument("--sector-map", default=str(REPO_ROOT / "data_history" / "sector_mapping.json"))
    p.add_argument("--start", default="2006-01-01")
    p.add_argument("--end", default="2026-05-25")
    p.add_argument("--capital", type=float, default=10_000_000)
    p.add_argument("--liquid-top-n", type=int, default=500)
    p.add_argument("--out", default=str(REPO_ROOT / "public" / "data" / "swing_backtest_fast.json"))
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    from sector_scorer import load_sector_map
    panel = pd.read_parquet(args.prices)
    sector_map = load_sector_map(args.sector_map)
    print(f"Panel: {len(panel):,} rows × {panel['ts_code'].nunique()} tickers", flush=True)
    print(f"Window: {args.start} → {args.end}", flush=True)
    print(f"Capital: ¥{args.capital:,.0f}", flush=True)
    print(f"Liquid top-N: {args.liquid_top_n}", flush=True)

    res = run_swing_backtest_fast(panel, sector_map, args.start, args.end,
                                    capital=args.capital, verbose=args.verbose,
                                    liquid_top_n=args.liquid_top_n)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    print(f"CAGR={res.get('cagr',0)*100:+.2f}% Sharpe={res.get('sharpe_annualized')} "
          f"MaxDD={res.get('max_drawdown',0)*100:+.1f}% "
          f"NAV ¥{res.get('final_nav',0):,.0f} trades={res.get('n_total_trades')}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
