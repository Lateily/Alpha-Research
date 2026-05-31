#!/usr/bin/env python3
"""daily_swing_runner.py — incremental swing paper-trading orchestrator.

State-persistent variant of run_swing_backtest_fast.py.  Reads existing
positions from disk, generates today's signals + tomorrow's trade plan,
reconciles any pending orders from yesterday, writes everything back.

Usage:
    # Initialize a new paper portfolio:
    python3 scripts/daily_swing_runner.py --track A --init --capital 10000000

    # Daily run (after market close + data refresh):
    python3 scripts/daily_swing_runner.py --track A --as-of 2026-05-27
    python3 scripts/daily_swing_runner.py --track B --as-of 2026-05-27

Track A = iter-13 baseline (min_hold=5, sector top-5, balanced weights, no quality filter)
Track B = iter-16 (quality pre-filter + iter-15 structure exit, no forced min_hold)

State files:
    public/data/paper_swing_{A,B}_state.json
        {capital, cash, positions, pending_orders, nav_history, trade_log, last_as_of, config}
    public/data/paper_swing_{A,B}_log.json
        Per-run audit log (signals scanned, exit decisions, entry candidates)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from panel_index import PanelIndex
from liquid_universe import compute_liquid_universe
from quality_universe import apply_quality_filter
from run_swing_backtest_fast import (
    fast_sector_score, fast_signals_batch, DEFAULT_SIGNAL_WEIGHTS,
    is_limit_up, is_limit_down, fill_price, trade_cost,
    COMMISSION, STAMP_DUTY_SELL, SLIPPAGE, DAILY_LIMIT,
)
from swing_risk_manager import DEFAULT_CONFIG, check_portfolio_breakers

# ─────────────────────── Track configs ──────────────────────────────────

# Track A: iter-13 baseline — best historical CAGR on mini1yr (+2.00%) but
# highest turnover.  No entry threshold, no quality filter, sector top-5,
# enforced min_hold=5, take_profit_pct=10% half-sell, balanced signal weights.
TRACK_A_CONFIG = {
    **DEFAULT_CONFIG,
    "min_hold_days": 5,                    # iter-13: 5-day min hold
    "entry_composite_threshold": 0.0,      # iter-13: no entry gate
    "structure_break_threshold": -1.0,     # disabled (negative means never trigger)
    "take_profit_full": 999.0,             # disabled
    "use_quality_filter": False,           # iter-13 baseline
    "_sector_top_k": 5,                    # iter-13: sector top-5
    "_signal_weights": {
        "breakout_20d":     0.20,
        "momentum_5d":      0.15,
        "limit_up_followup": 0.10,
        "volume_spike":     0.15,
        "macd_cross":       0.20,
        "rsi_in_band":      0.20,
    },
}

# Track B: iter-16 — quality pre-filter + iter-15 exits (no forced min_hold).
TRACK_B_CONFIG = {
    **DEFAULT_CONFIG,
    "min_hold_days": 0,                    # iter-15: structure decides
    "entry_composite_threshold": 70.0,     # iter-14: composite ≥ 70 to enter
    "structure_break_threshold": 50.0,     # iter-15: exit when composite drops below
    "take_profit_full": 0.20,              # iter-15: full +20% TP
    "use_quality_filter": True,            # iter-16: G1-G4 quality gates
    "min_quality_universe": 20,
    "quality_require_limitup": True,
    "quality_min_60d_ret": 0.0,
    "quality_dd_floor": 0.80,
    "quality_up_day_min": 10,
    "_sector_top_k": 3,                    # iter-14: sector top-3
    "_signal_weights": dict(DEFAULT_SIGNAL_WEIGHTS),    # iter-14 momentum-heavy
}

TRACK_CONFIGS = {"A": TRACK_A_CONFIG, "B": TRACK_B_CONFIG}


# ─────────────────────── State I/O ──────────────────────────────────────

def state_path(track: str) -> Path:
    return REPO_ROOT / "public" / "data" / f"paper_swing_{track}_state.json"


def log_path(track: str) -> Path:
    return REPO_ROOT / "public" / "data" / f"paper_swing_{track}_log.json"


def load_state(track: str) -> dict:
    p = state_path(track)
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def save_state(track: str, state: dict) -> None:
    p = state_path(track)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str))


def append_log(track: str, entry: dict) -> None:
    p = log_path(track)
    if p.exists():
        log = json.loads(p.read_text())
    else:
        log = []
    log.append(entry)
    # Keep last 90 days only
    log = log[-90:]
    p.write_text(json.dumps(log, indent=2, ensure_ascii=False, default=str))


def init_state(track: str, capital: float, as_of: str) -> dict:
    cfg = TRACK_CONFIGS[track].copy()
    return {
        "track": track,
        "track_description": "iter-13 baseline (min_hold=5, sector top-5, balanced weights)"
            if track == "A" else "iter-16 (quality pre-filter + iter-15 structure exit)",
        "capital": capital,
        "cash": capital,
        "positions": {},                # ticker → {entry_date, entry_price, size_units, peak_price, days_held, entry_composite, entry_sector}
        "pending_orders": [],           # [{side, ticker, target_value, generated_on}]
        "nav_history": [{"date": as_of, "nav": capital, "cash": capital,
                          "n_positions": 0, "drawdown": 0.0}],
        "trade_log": [],
        "peak_equity": capital,
        "last_as_of": as_of,
        "config_keys": {k: v for k, v in cfg.items() if not k.startswith("_")},
        "created_at": datetime.utcnow().isoformat() + "Z",
    }


# ─────────────────────── Daily routine ──────────────────────────────────

def reconcile_pending(state: dict, idx: PanelIndex, T: str, cfg: dict,
                       sector_map: dict) -> dict:
    """Execute T-1's pending orders using T's open price + fill rules.

    Returns events dict for log.
    """
    events = {"sells_executed": [], "buys_executed": [], "skipped": []}
    pending = state.get("pending_orders", [])
    if not pending:
        return events

    # T market data
    for order in pending:
        tk = order["ticker"]
        side = order["side"]
        row = idx.row_at(tk, T)
        if row is None:
            events["skipped"].append({**order, "reason": "no_data_at_T"})
            continue
        # Limit-up/down fill rules
        if side == "sell" and is_limit_down(row):
            events["skipped"].append({**order, "reason": "limit_down_T_open"})
            continue
        if side == "buy" and is_limit_up(row):
            events["skipped"].append({**order, "reason": "limit_up_T_open"})
            continue

        price = fill_price(row, side)
        if price is None:
            events["skipped"].append({**order, "reason": "no_fill_price"})
            continue

        if side == "sell":
            pos = state["positions"].get(tk)
            if not pos:
                events["skipped"].append({**order, "reason": "position_gone"})
                continue
            units = pos["size_units"]
            notional = units * price
            cost = trade_cost(notional, "sell")
            state["cash"] += notional - cost
            tlog_entry = {
                "date": T, "ts_code": tk, "side": "sell",
                "action": order.get("action", "sell"), "units": round(units, 2),
                "price": round(price, 4), "notional": round(notional, 2),
                "cost": round(cost, 4), "entry_price": pos["entry_price"],
                "pnl": round((price - pos["entry_price"]) * units - cost, 2),
                "days_held": pos.get("days_held", 0),
            }
            state["trade_log"].append(tlog_entry)
            events["sells_executed"].append(tlog_entry)
            state["positions"].pop(tk, None)
        else:    # buy
            target_value = order["target_value"]
            if state["cash"] < target_value * 1.01:
                events["skipped"].append({**order, "reason": "insufficient_cash"})
                continue
            units = target_value / price
            cost = trade_cost(target_value, "buy")
            state["cash"] -= target_value + cost
            cur_pos = state["positions"].get(tk)
            entry_sector = sector_map.get(tk, "_unknown")
            tlog_entry = {
                "date": T, "ts_code": tk, "side": "buy",
                "action": "open_or_add", "units": round(units, 2),
                "price": round(price, 4), "notional": round(target_value, 2),
                "cost": round(cost, 4), "sector": entry_sector,
            }
            state["trade_log"].append(tlog_entry)
            events["buys_executed"].append(tlog_entry)
            if cur_pos:
                old_u = cur_pos["size_units"]; old_p = cur_pos["entry_price"]
                new_u = old_u + units
                cur_pos["entry_price"] = (old_u*old_p + units*price) / new_u
                cur_pos["size_units"] = new_u
            else:
                state["positions"][tk] = {
                    "entry_date": T, "entry_price": price, "size_units": units,
                    "peak_price": price, "days_held": 0,
                    "entry_composite": order.get("entry_composite"),
                    "entry_sector": entry_sector,
                }

    state["pending_orders"] = []
    return events


def update_position_meta(state: dict, idx: PanelIndex, T: str) -> None:
    """Increment days_held + update peak_price for each open position."""
    for tk, pos in state["positions"].items():
        pos["days_held"] = pos.get("days_held", 0) + 1
        row = idx.row_at(tk, T)
        if row:
            pos["peak_price"] = max(pos.get("peak_price", pos["entry_price"]),
                                     float(row["close"]))


def mark_nav(state: dict, idx: PanelIndex, T: str) -> dict:
    """Compute NAV at T's close and update nav_history.  Returns the new entry."""
    nav = state["cash"]
    for tk, pos in state["positions"].items():
        row = idx.row_at(tk, T)
        if row:
            nav += pos["size_units"] * float(row["close"])
    state["peak_equity"] = max(state.get("peak_equity", state["capital"]), nav)
    dd = ((nav - state["peak_equity"]) / state["peak_equity"]
          if state["peak_equity"] > 0 else 0.0)
    entry = {"date": T, "nav": round(nav, 2), "cash": round(state["cash"], 2),
             "n_positions": len(state["positions"]), "drawdown": round(dd, 4)}
    state["nav_history"].append(entry)
    return entry


def compute_exits(state: dict, signals: dict, idx: PanelIndex, T: str,
                   cfg: dict) -> dict:
    """For each open position decide hold or sell."""
    actions = {}
    sb_threshold = cfg.get("structure_break_threshold", 50.0)
    tp_full = cfg.get("take_profit_full", 0.20)
    tp_pct = cfg.get("take_profit_pct", 0.10)
    hard_stop = cfg["hard_stop_pct"]
    trail_stop = cfg["trailing_stop_pct"]
    min_hold = cfg.get("min_hold_days", 0)
    time_stop = cfg.get("time_stop_days", 7)
    enable_half = cfg.get("enable_take_profit_half", False)

    for tk, pos in state["positions"].items():
        row = idx.latest_row(tk, T)
        if row is None:
            actions[tk] = {"action": "hold", "reason": "no_data"}; continue
        entry_p = pos["entry_price"]
        cur = float(row["close"])
        mtm = (cur - entry_p) / entry_p if entry_p > 0 else 0
        peak = pos.get("peak_price", entry_p)
        trail = (cur - peak) / peak if peak > 0 else 0
        days = pos.get("days_held", 0)
        cur_comp = (signals.get(tk) or {}).get("composite")

        # Capital-preservation overrides
        if mtm <= hard_stop:
            actions[tk] = {"action": "sell_hard_stop", "mtm": mtm}
        elif trail <= trail_stop:
            actions[tk] = {"action": "sell_trailing", "trail": trail}
        # Track A: time-stop + half take-profit (iter-13)
        elif cfg.get("_use_iter13_exits"):
            if mtm >= tp_pct and enable_half and not pos.get("_tp_taken"):
                actions[tk] = {"action": "take_profit_half", "mtm": mtm}
            elif days >= time_stop:
                actions[tk] = {"action": "sell_time_stop", "days": days}
            else:
                actions[tk] = {"action": "hold"}
        # Track B: structure-based (iter-15)
        elif mtm >= tp_full:
            actions[tk] = {"action": "sell_take_profit_full", "mtm": mtm}
        elif sb_threshold > 0 and cur_comp is not None and cur_comp < sb_threshold:
            if days >= min_hold:
                actions[tk] = {"action": "sell_structure_break", "composite": cur_comp}
            else:
                actions[tk] = {"action": "hold", "reason": "below_min_hold"}
        else:
            # Track A backup time-stop if min_hold elapsed
            if min_hold > 0 and days >= time_stop:
                actions[tk] = {"action": "sell_time_stop", "days": days}
            else:
                actions[tk] = {"action": "hold"}
    return actions


def compute_entries(state: dict, signals: dict, idx: PanelIndex, T: str,
                     cfg: dict, sector_map: dict) -> list[dict]:
    """Generate ranked entry candidates with vol-targeted sizing."""
    entry_threshold = cfg.get("entry_composite_threshold", 0.0)
    scored = [(tk, s.get("composite")) for tk, s in signals.items()
              if s and s.get("composite") is not None
              and s["composite"] >= entry_threshold]
    scored.sort(key=lambda kv: -kv[1])

    nav = state["nav_history"][-1]["nav"] if state["nav_history"] else state["capital"]
    target_weights = {}
    sector_totals: dict[str, float] = {}
    selected = 0
    for tk, score in scored:
        if selected >= cfg["top_n_picks"]:
            break
        # already a position? skip (we don't add to winners in paper sim — simpler)
        if tk in state["positions"]:
            continue
        atr_val = (signals[tk]["factors"].get("_atr") or 0)
        row = idx.latest_row(tk, T)
        if row is None:
            continue
        close_val = float(row["close"])
        atr_vol_ann = (atr_val / close_val) * math.sqrt(252) if close_val > 0 else 0
        target = (min(cfg["max_single_name_weight"], cfg["vol_per_position"] / atr_vol_ann)
                   if atr_vol_ann > 0 else cfg["max_single_name_weight"] * 0.5)
        sector = sector_map.get(tk, "_unknown")
        cur_sec = sector_totals.get(sector, 0.0)
        if cur_sec + target > cfg["max_sector_weight"]:
            target = max(0.0, cfg["max_sector_weight"] - cur_sec)
            if target <= 0.005:
                continue
        target = min(target, cfg["safety_max_single_name"])
        target_weights[tk] = target
        sector_totals[sector] = cur_sec + target
        selected += 1
    tot = sum(target_weights.values())
    if tot > cfg["max_gross"]:
        scale = cfg["max_gross"] / tot
        target_weights = {tk: w*scale for tk, w in target_weights.items()}

    candidates = []
    for tk, w in target_weights.items():
        candidates.append({
            "ticker": tk, "target_weight": round(w, 4),
            "target_value": round(nav * w, 2),
            "entry_composite": (signals.get(tk) or {}).get("composite"),
        })
    return candidates


def run_one_day(track: str, as_of: str, panel: pd.DataFrame,
                 sector_map: dict, verbose: bool = False) -> dict:
    """Single daily orchestrator step.

    Returns a summary dict with: nav, n_positions, executed_sells, executed_buys,
    pending_orders_for_next, exit_decisions, entry_candidates.
    """
    state = load_state(track)
    if not state:
        raise FileNotFoundError(f"state file for track {track} missing — run --init first")

    cfg = TRACK_CONFIGS[track]
    last_as_of = state["last_as_of"]
    if as_of <= last_as_of:
        raise ValueError(f"as_of {as_of} ≤ last_as_of {last_as_of}; refusing to rewind")

    # Build PanelIndex on the last 100 days for fast slicing
    cutoff = (datetime.strptime(as_of, "%Y%m%d") - pd.Timedelta(days=140)).strftime("%Y%m%d")
    sub = panel[(panel["trade_date"] >= cutoff) & (panel["trade_date"] <= as_of)]
    if verbose:
        print(f"  panel slice: {len(sub):,} rows", flush=True)
    idx = PanelIndex(sub)

    # Step 1: Reconcile yesterday's pending orders using T's open
    pending_events = reconcile_pending(state, idx, as_of, cfg, sector_map)

    # Step 2: Update position meta (days_held + peak)
    update_position_meta(state, idx, as_of)

    # Step 3: Build liquid universe (need 20d ADV — use last 30 days)
    liquid_uni = compute_liquid_universe(sub, top_n=500)
    liquid_today = liquid_uni.get(as_of, [])

    if not liquid_today:
        # Holiday or no data — mark NAV and return
        entry = mark_nav(state, idx, as_of)
        state["last_as_of"] = as_of
        save_state(track, state)
        append_log(track, {
            "as_of": as_of, "track": track, "nav": entry["nav"],
            "status": "no_liquid_universe (holiday?)",
        })
        return {"nav": entry["nav"], "status": "skipped_holiday"}

    # Step 4: Quality filter (track B only)
    if cfg.get("use_quality_filter"):
        quality_today = apply_quality_filter(idx, liquid_today, as_of,
                                              require_g4_limitup=cfg.get("quality_require_limitup", True),
                                              min_60d_ret=cfg.get("quality_min_60d_ret", 0.0),
                                              dd_floor=cfg.get("quality_dd_floor", 0.80),
                                              up_day_min=cfg.get("quality_up_day_min", 10))
        min_qu = cfg.get("min_quality_universe", 20)
        scan_pool = quality_today if len(quality_today) >= min_qu else liquid_today
    else:
        scan_pool = liquid_today

    # Step 5: Sector ranking
    top_k = cfg.get("_sector_top_k", 3)
    top_sectors, universe = fast_sector_score(idx, sector_map, scan_pool, as_of,
                                                lookback_days=60, top_k=top_k)
    if not universe:
        universe = scan_pool[:200]

    # Step 6: Signal scan (universe ∪ open positions for exit eval)
    scan_set = list(set(universe) | set(state["positions"].keys()))
    signals = fast_signals_batch(idx, scan_set, as_of)

    # Step 7: Exit decisions (informational — actual sells become pending for tomorrow)
    if cfg.get("min_hold_days", 0) > 0:
        cfg = {**cfg, "_use_iter13_exits": True}
    exit_decisions = compute_exits(state, signals, idx, as_of, cfg)

    # Step 8: Entry candidates
    entry_candidates = compute_entries(state, signals, idx, as_of, cfg, sector_map)

    # Step 9: NAV at T close
    entry = mark_nav(state, idx, as_of)

    # Step 10: Build pending_orders for T+1
    next_pending = []
    for tk, decision in exit_decisions.items():
        if decision["action"].startswith("sell") or decision["action"].startswith("take_profit"):
            next_pending.append({
                "side": "sell", "ticker": tk, "action": decision["action"],
                "target_value": 0.0, "generated_on": as_of,
                "decision_meta": decision,
            })
    for c in entry_candidates:
        next_pending.append({
            "side": "buy", "ticker": c["ticker"],
            "target_value": c["target_value"],
            "entry_composite": c["entry_composite"],
            "generated_on": as_of,
        })
    state["pending_orders"] = next_pending
    state["last_as_of"] = as_of
    save_state(track, state)

    log_entry = {
        "as_of": as_of, "track": track, "nav": entry["nav"],
        "n_positions": len(state["positions"]),
        "scan_pool_size": len(scan_pool),
        "quality_filter_active": bool(cfg.get("use_quality_filter")),
        "top_sectors": top_sectors,
        "signals_scanned": len(signals),
        "executed_sells": len(pending_events["sells_executed"]),
        "executed_buys": len(pending_events["buys_executed"]),
        "skipped_pending": len(pending_events["skipped"]),
        "next_pending_sells": sum(1 for o in next_pending if o["side"] == "sell"),
        "next_pending_buys": sum(1 for o in next_pending if o["side"] == "buy"),
        "entry_candidates_top5": [{"ticker": c["ticker"],
                                    "weight": c["target_weight"],
                                    "composite": c["entry_composite"]}
                                   for c in entry_candidates[:5]],
        "exit_decisions_active": [{"ticker": tk, **d}
                                   for tk, d in exit_decisions.items()
                                   if d["action"] != "hold"],
    }
    append_log(track, log_entry)
    return {
        "nav": entry["nav"], "status": "ok",
        "exit_decisions": exit_decisions,
        "entry_candidates": entry_candidates,
        "executed_sells": pending_events["sells_executed"],
        "executed_buys": pending_events["buys_executed"],
        "skipped": pending_events["skipped"],
    }


# ─────────────────────── CLI ────────────────────────────────────────────

def main(argv=None):
    p = argparse.ArgumentParser(description="Daily swing paper-trading orchestrator.")
    p.add_argument("--track", choices=["A", "B"], required=True)
    p.add_argument("--init", action="store_true",
                    help="Initialize a new paper portfolio (will REFUSE if state exists).")
    p.add_argument("--force-init", action="store_true",
                    help="DANGEROUS: overwrite existing state on init.")
    p.add_argument("--as-of", required=True,
                    help="Date YYYY-MM-DD or YYYYMMDD")
    p.add_argument("--capital", type=float, default=10_000_000.0,
                    help="Initial cash (--init mode only)")
    p.add_argument("--prices", default=str(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet"))
    p.add_argument("--sector-map", default=str(REPO_ROOT / "data_history" / "sector_mapping.json"))
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    as_of = args.as_of.replace("-", "")

    if args.init:
        existing = load_state(args.track)
        if existing and not args.force_init:
            print(f"ERROR: state for track {args.track} exists "
                  f"(last_as_of={existing.get('last_as_of')}, "
                  f"nav={existing.get('nav_history', [{}])[-1].get('nav')}).",
                  file=sys.stderr)
            print(f"Use --force-init to overwrite (loses history).", file=sys.stderr)
            return 1
        state = init_state(args.track, args.capital, as_of)
        save_state(args.track, state)
        append_log(args.track, {
            "as_of": as_of, "track": args.track, "event": "INIT",
            "capital": args.capital,
        })
        print(f"INIT: track {args.track} initialized with ¥{args.capital:,.0f} at {as_of}")
        print(f"  config: {state['track_description']}")
        print(f"  state file: {state_path(args.track)}")
        return 0

    # Daily run
    from sector_scorer import load_sector_map
    if args.verbose:
        print(f"loading panel from {args.prices}...", flush=True)
    panel = pd.read_parquet(args.prices)
    sector_map = load_sector_map(args.sector_map)

    res = run_one_day(args.track, as_of, panel, sector_map, verbose=args.verbose)
    print(f"track {args.track} as-of {as_of}: NAV=¥{res['nav']:,.0f}  status={res.get('status')}")
    if res.get("status") == "ok":
        print(f"  executed: {len(res['executed_sells'])} sells, {len(res['executed_buys'])} buys, "
              f"{len(res.get('skipped', []))} skipped")
        actives = [(tk, d) for tk, d in res["exit_decisions"].items()
                   if d["action"] != "hold"]
        print(f"  exit decisions (active): {len(actives)}")
        for tk, d in actives[:5]:
            print(f"    {tk}: {d['action']}")
        print(f"  entry candidates: {len(res['entry_candidates'])}")
        for c in res["entry_candidates"][:5]:
            print(f"    {c['ticker']}: weight={c['target_weight']:.3f} "
                  f"composite={c['entry_composite']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
