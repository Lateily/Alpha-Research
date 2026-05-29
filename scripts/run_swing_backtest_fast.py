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
import hashlib
import json
import math
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from swing_risk_manager import (compute_target_weights, evaluate_exits,
                                  check_portfolio_breakers, DEFAULT_CONFIG)
from liquid_universe import compute_liquid_universe
from panel_index import (PanelIndex, fast_60d_return, fast_volume_trend,
                          fast_atr, fast_rsi, fast_macd_bullish_cross)
from quality_universe import apply_quality_filter

# Cost params (carry from backtest_v2 — module-level defaults = baseline 0.40% RT)
COMMISSION = 0.00025
STAMP_DUTY_SELL = 0.0005
SLIPPAGE = 0.0010
DAILY_LIMIT = 0.099


# ───────────── v3 Phase B (Junyan ratify #4): cost scenario dispatch ─────
#
# Three audited scenarios per V3B_COST_AUDIT_2026-05-28.md §5:
#   - optimistic_0.20_RT:  CSI300-class blue chip + top-tier broker (万 1)
#   - baseline_0.40_RT:    industry-average mid-cap (anchor for v3 hard-gate)
#   - pessimistic_0.60_RT: ChiNext/STAR/北交所 heavy + 万 3 commission
#
# Round-trip cost = 2 × COMMISSION + STAMP_DUTY_SELL + 2 × SLIPPAGE.
#   buy_cost  = COMMISSION + SLIPPAGE
#   sell_cost = COMMISSION + STAMP_DUTY_SELL + SLIPPAGE
#   RT = buy + sell = 2 × COMMISSION + STAMP + 2 × SLIPPAGE
#
# v3 Phase B-fix (Junyan PM3 2026-05-28 Bug 4): SLIPPAGE recalibrated so that
# the COMPUTED round-trip exactly matches the scenario label (0.20% / 0.40% /
# 0.60%). Previously the labels were nominal and actual RT was lower (0.17%,
# 0.30%, 0.41%). Math (target RT = T):
#   SLIPPAGE = (T - 2 × COMMISSION - STAMP_DUTY_SELL) / 2
COST_SCENARIOS = {
    "optimistic_0.20_RT": {
        # CSI300 blue chip + top-tier retail broker (万 1).
        "COMMISSION": 0.00010,        # 万 1 retail tier
        "STAMP_DUTY_SELL": 0.00050,   # 0.05% sell-side (post-2023-08 半减)
        # Target RT 0.0020: SLIP = (0.0020 - 2×0.0001 - 0.0005) / 2 = 0.00065
        "SLIPPAGE": 0.00065,
        # Computed RT = 2×0.00010 + 0.00050 + 2×0.00065 = 0.00200 (0.20%) ✓
        "_round_trip_estimate": 0.00200,
        "_nominal_label_rt": 0.0020,
    },
    "baseline_0.40_RT": {
        # Industry-average mid-cap anchor (v3 research baseline).
        "COMMISSION": 0.00025,        # 万 2.5
        "STAMP_DUTY_SELL": 0.00050,
        # Target RT 0.0040: SLIP = (0.0040 - 2×0.00025 - 0.0005) / 2 = 0.00150
        "SLIPPAGE": 0.00150,
        # Computed RT = 2×0.00025 + 0.00050 + 2×0.00150 = 0.00400 (0.40%) ✓
        "_round_trip_estimate": 0.00400,
        "_nominal_label_rt": 0.0040,
    },
    "pessimistic_0.60_RT": {
        # ChiNext/STAR heavy book + 万 3 commission + +50% slip.
        "COMMISSION": 0.00030,        # 万 3
        "STAMP_DUTY_SELL": 0.00050,
        # Target RT 0.0060: SLIP = (0.0060 - 2×0.0003 - 0.0005) / 2 = 0.00245
        "SLIPPAGE": 0.00245,
        # Computed RT = 2×0.00030 + 0.00050 + 2×0.00245 = 0.00600 (0.60%) ✓
        "_round_trip_estimate": 0.00600,
        "_nominal_label_rt": 0.0060,
    },
}


def _cost_constants_for_scenario(scenario: str) -> dict:
    """Resolve cost constants for a named scenario.

    Returns dict with keys COMMISSION, STAMP_DUTY_SELL, SLIPPAGE
    (drop-in for the module-level globals used by trade_cost / fill_price).

    Raises ValueError if scenario is unknown.
    """
    if scenario not in COST_SCENARIOS:
        raise ValueError(
            f"unknown cost_scenario {scenario!r}; "
            f"valid: {sorted(COST_SCENARIOS.keys())}"
        )
    spec = COST_SCENARIOS[scenario]
    return {
        "COMMISSION": spec["COMMISSION"],
        "STAMP_DUTY_SELL": spec["STAMP_DUTY_SELL"],
        "SLIPPAGE": spec["SLIPPAGE"],
        "_round_trip_estimate": spec.get("_round_trip_estimate"),
        "_scenario_label": scenario,
    }


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
    # iter-14: 势能权重加大(Junyan 方法学:swing 抓 2-3 天涨停+突破势能)
    "breakout_20d":     0.30,    # 0.20 → 0.30
    "momentum_5d":      0.25,    # 0.15 → 0.25
    "limit_up_followup": 0.20,   # 0.10 → 0.20
    "volume_spike":     0.15,    # 0.15
    "macd_cross":       0.05,    # 0.10 → 0.05(慢信号降权)
    "rsi_in_band":      0.05,    # 0.10 → 0.05(gate-style 降权)
    # v3 Phase B (Junyan ratify #6/#7): momentum_20d for V3C-α1 (10d horizon).
    # Default weight 0 so existing variants (iter-13..18) are not perturbed;
    # manifest-driven variants override via `signal_weights_override`.
    # See V3A_OOS_DIAGNOSTIC_2026-05-28.md §3 + §6 for the horizon rationale
    # (momentum_5d.10d fade=0% vs momentum_5d.5d fade=47%).
    "momentum_20d":     0.00,
}


def fast_signals_one(idx: PanelIndex, tk: str, as_of: str,
                      signal_weights: Optional[dict] = None,
                      factor_directions: Optional[dict] = None,
                      skip_atr_veto: bool = False,
                      skip_ma50_veto: bool = False) -> Optional[dict]:
    """Returns {composite, factors, vetoes} or None.

    iter-18 extensions(all optional,default behavior unchanged):
      - signal_weights: override DEFAULT_SIGNAL_WEIGHTS per-call
      - factor_directions: dict{factor: +1 / -1 / 0}
          +1 = use factor value directly(high = good)
          -1 = invert (high original = low contribution to composite)
           0 = skip factor entirely
      - skip_atr_veto: True → don't veto on ATR > 8%
      - skip_ma50_veto: True → don't veto on MA50 down trend
    """
    weights = signal_weights or DEFAULT_SIGNAL_WEIGHTS
    directions = factor_directions or {}

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
    if not skip_atr_veto and atr / closes[-1] > 0.08:
        return None   # ATR too high
    ma50 = float(np.mean(closes[-50:])) if len(closes) >= 50 else closes[-1]
    ma50_prev = float(np.mean(closes[-60:-10])) if len(closes) >= 60 else ma50
    if not skip_ma50_veto and closes[-1] < ma50 and ma50 < ma50_prev:
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

    # momentum 20d (v3 Phase B Junyan ratify #6/#7)
    # Per V3A_OOS_DIAGNOSTIC §3 + Codex R3 study:
    #   momentum_5d.10d horizon: 2006-10 IC -0.0514 vs 2022-26 IC -0.0513 → 0% fade
    #   momentum_5d.5d  horizon: 2006-10 IC -0.0964 vs 2022-26 IC -0.0510 → 47% fade
    #   R3 momentum_20d.h10 Q=0.1 Net Bottom-EW = +3.26%/yr POSITIVE after 0.30% cost
    # Use 21-day lookback (T-21 close as reference; close[-1] is T-day close).
    if len(closes) >= 22 and closes[-22] > 0:
        factors["momentum_20d"] = float(closes[-1] / closes[-22] - 1)
    else:
        factors["momentum_20d"] = None

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
    for f, w in weights.items():
        v = factors.get(f)
        if v is None:
            continue
        if w == 0:
            continue   # explicitly zero-weight skip
        # Normalize to [0,1]
        if f == "momentum_5d":
            vv = max(-0.2, min(0.2, v))
            vv = (vv + 0.2) / 0.4
        elif f == "momentum_20d":
            # v3 Phase B: 20d returns are ~2x noisier than 5d; clamp [-0.4,+0.4]
            # (per V3C-α1 manifest design.factor_inputs.normalization).
            vv = max(-0.4, min(0.4, v))
            vv = (vv + 0.4) / 0.8
        else:
            vv = max(0.0, min(1.0, float(v)))
        # Apply per-factor direction(iter-18 ablation)
        direction = directions.get(f, 1)
        if direction == 0:
            continue   # skip
        elif direction == -1:
            vv = 1.0 - vv   # invert
        num += w * vv
        den += w
        have += 1
    if have < 4 or den == 0:
        return None
    return {"composite": round(100 * num / den, 2), "factors": factors, "vetoes": []}


def fast_signals_batch(idx: PanelIndex, tickers: list[str], as_of: str,
                        **kwargs) -> dict:
    """Pass-through any iter-18 kwargs to fast_signals_one."""
    out = {}
    for tk in tickers:
        s = fast_signals_one(idx, tk, as_of, **kwargs)
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


def fill_price(row: dict, side: str, slippage: Optional[float] = None) -> Optional[float]:
    """v3 Phase B: slippage now optional parameter for cost_scenario dispatch.

    Default = module-level SLIPPAGE (0.0010 baseline) for backward compat.
    """
    if slippage is None:
        slippage = SLIPPAGE
    open_p = row.get("open") or row.get("close")
    if not open_p or open_p <= 0:
        return None
    blend = (row.get("high", open_p) + row.get("low", open_p) + row.get("close", open_p)) / 3
    raw = (open_p + blend) / 2
    return raw * (1 + slippage) if side == "buy" else raw * (1 - slippage)


def trade_cost(notional: float, side: str,
               commission: Optional[float] = None,
               stamp_duty_sell: Optional[float] = None) -> float:
    """v3 Phase B: commission + stamp_duty_sell now optional for cost_scenario dispatch.

    Default = module-level constants for backward compat.
    """
    if commission is None:
        commission = COMMISSION
    if stamp_duty_sell is None:
        stamp_duty_sell = STAMP_DUTY_SELL
    return notional * (commission + (stamp_duty_sell if side == "sell" else 0))


def _active_position_limit(cfg: dict) -> int:
    """Total desired holdings cap. Existing holdings consume slots first."""
    max_positions = int(cfg.get("max_positions", cfg.get("top_n_picks", 0)) or 0)
    top_n_picks = int(cfg.get("top_n_picks", max_positions) or 0)
    limits = [n for n in (max_positions, top_n_picks) if n > 0]
    return min(limits) if limits else 0


def _cap_scored_to_available_slots(scored: list[tuple[str, float]],
                                   positions: dict[str, dict],
                                   exit_actions: dict[str, str],
                                   cfg: dict) -> tuple[list[tuple[str, float]], dict]:
    """Keep existing non-exiting holdings first; allow new buys only into open slots.

    This deliberately does not force-sell over-limit books. If inherited holdings
    exceed the configured cap, the engine blocks new names until normal exits
    bring the book back under the cap.
    """
    limit = _active_position_limit(cfg)
    if limit <= 0:
        return [], {"active_limit": limit, "existing_kept": 0, "new_slots": 0,
                    "new_candidates_allowed": 0}

    existing_kept = {tk for tk in positions
                     if exit_actions.get(tk, "hold") == "hold"}
    new_slots = max(0, limit - len(existing_kept))
    allowed_new = 0
    existing_scored = []
    new_scored = []
    seen_new = set()
    for tk, score in scored:
        if tk in existing_kept:
            existing_scored.append((tk, score))
            continue
        if tk in seen_new:
            continue
        if allowed_new >= new_slots:
            continue
        new_scored.append((tk, score))
        seen_new.add(tk)
        allowed_new += 1

    return existing_scored + new_scored, {"active_limit": limit,
                                          "existing_kept": len(existing_kept),
                                          "new_slots": new_slots,
                                          "new_candidates_allowed": allowed_new}


def _portfolio_gross(idx: PanelIndex, positions: dict[str, dict],
                     as_of: str, nav: float) -> float:
    if nav <= 0:
        return 0.0
    gross = 0.0
    for tk, pos in positions.items():
        row = idx.row_at(tk, as_of)
        if row:
            gross += pos["size_units"] * row["close"]
    return gross / nav


def _audit_gates(cfg: dict, max_n_positions: int,
                 annualized_trades: float) -> dict:
    max_positions = int(cfg.get("max_positions", 0) or 0)
    top_n_picks = int(cfg.get("top_n_picks", 0) or 0)
    active_limit = _active_position_limit(cfg)
    turnover_limit = (
        cfg.get("max_annualized_trades")
        or cfg.get("annualized_trades_cap")
        or cfg.get("max_turnover_trades_per_year")
    )
    turnover_violation = (
        bool(turnover_limit is not None and annualized_trades > float(turnover_limit))
    )
    turnover_status = "pass" if turnover_limit is not None and not turnover_violation else (
        "fail" if turnover_violation else "not_specified"
    )
    return {
        "max_positions_violation": bool(max_positions > 0 and max_n_positions > max_positions),
        "top_n_picks_total_holdings_violation": bool(top_n_picks > 0 and max_n_positions > top_n_picks),
        "position_limit_used": active_limit,
        "turnover_spec_feasibility": {
            "status": turnover_status,
            "violation": turnover_violation,
            "annualized_trades": round(annualized_trades, 4),
            "configured_limit": turnover_limit,
            "note": ("No calibrated turnover cap is present in config; "
                     "annualized_trades is exposed for audit only.")
                    if turnover_limit is None else "",
        },
    }


def _same_gross_benchmark_curve(
    bench_curve: list[dict],
    equity_curve: list[dict],
    capital: float,
    daily_rf: float,
) -> list[dict]:
    """Apply strategy gross exposure to the EW benchmark return stream.

    This makes the benchmark comparable when the strategy is mostly in cash.
    The non-gross portion earns the configured cash rate.
    """
    gross_by_date = {
        row["date"]: float(row.get("gross", 0.0) or 0.0)
        for row in equity_curve
    }
    out = []
    prev_bench = capital
    same_gross_eq = capital
    for row in bench_curve:
        bench_eq = float(row.get("equity", prev_bench) or prev_bench)
        if prev_bench <= 0:
            bench_ret = 0.0
        else:
            bench_ret = bench_eq / prev_bench - 1.0
        gross = max(0.0, min(1.0, gross_by_date.get(row.get("date"), 0.0)))
        same_gross_eq *= 1.0 + gross * bench_ret + (1.0 - gross) * daily_rf
        out.append({
            "date": row.get("date"),
            "equity": round(same_gross_eq, 2),
            "gross": round(gross, 6),
            "ew_500_return": round(bench_ret, 8),
        })
        prev_bench = bench_eq
    return out


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

    # v3 Phase B (Junyan ratify #4): cost_scenario dispatch.
    # Default = baseline 0.40% RT (research anchor per V3B_COST_AUDIT §5.2).
    # cfg.cost_scenario must be one of COST_SCENARIOS keys (validated).
    cost_scenario = cfg.get("cost_scenario", "baseline_0.40_RT")
    cost_consts = _cost_constants_for_scenario(cost_scenario)
    _cost_commission = cost_consts["COMMISSION"]
    _cost_stamp = cost_consts["STAMP_DUTY_SELL"]
    _cost_slippage = cost_consts["SLIPPAGE"]
    if verbose:
        rt = 2 * (_cost_commission + _cost_slippage) + _cost_stamp
        print(f"[fast] cost_scenario={cost_scenario} → "
              f"comm={_cost_commission*100:.3f}% slip={_cost_slippage*100:.3f}% "
              f"stamp={_cost_stamp*100:.3f}% RT≈{rt*100:.3f}%", flush=True)

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
    # v3 Phase B α1.1: turnover mechanics audit accumulator.
    #
    # Tracks per-rebal-day records: existing-holding set going in, replaced /
    # carry_over / hard_stop_exits / untouched. Used at metrics time to compute
    # untouched_carry_over_avg, full_refresh_rate, replacement_count_per_rebal,
    # same_day_rebuy_count. Empty in α1 (and any cfg without
    # hold_continuation_enabled) because we never populate it on the legacy path.
    rebal_audit_records: list[dict] = []
    # Across-loop same-day rebuy counter (per (date, ticker) pair where the
    # ticker was sold and a buy was *attempted*; the buy may be blocked by
    # same_day_rebuy=False but we still tally the avoided event).
    same_day_rebuy_blocked = 0
    same_day_rebuy_executed = 0

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
        # v3 Phase B-fix (Junyan PM3 2026-05-28 Bug 1): if research mode has
        # disabled the drawdown breaker, strip the `flat_all` action and
        # restore the gross_cap to the configured max_gross. The breaker's
        # spec comment claims "wait 5 days re-entry" but the re-entry logic
        # was never implemented; once triggered, the strategy is stuck flat
        # for the remainder of the window. Walk-forward sub-windows avoid
        # this because each window starts fresh. This flag is a research
        # short-term fix; production paper trading should leave it False
        # until re-entry logic lands.
        if cfg.get("disable_drawdown_breaker", False):
            if "flat_all" in breaker.get("actions", []):
                breaker["actions"] = [a for a in breaker["actions"] if a != "flat_all"]
                breaker["reason"] = (
                    (breaker.get("reason") or "") +
                    " [v3 research: flat_all suppressed by disable_drawdown_breaker]"
                )
                # Restore gross_cap to max_gross (the flat_all branch had set it to 0).
                breaker["gross_cap"] = max(
                    breaker.get("gross_cap", 0.0),
                    cfg.get("max_gross", 0.95),
                )
        gross_cap = breaker["gross_cap"]
        if breaker["actions"]:
            risk_log.append({"date": T, **breaker, "dd": round(dd, 4),
                              "vol60": round(realized_vol, 4)})

        # Sector ranking via PanelIndex (FAST!)
        liquid_today = liquid_uni.get(T, [])
        if not liquid_today:
            gross = _portfolio_gross(idx, positions, T, nav)
            equity_curve.append({"date": T, "nav": round(nav, 2), "cash": round(cash, 2),
                                  "gross": round(gross, 6),
                                  "n_positions": len(positions), "drawdown": round(dd, 4)})
            continue
        # iter-16: quality pre-filter (上涨势能 + 故事 + 行业)
        # Per Junyan: liquid top-500 still admits low-quality stocks.
        # Gate by: 60d ret > 0, close > 0.80×60dHigh, 20d up-days ≥ 10, 30d limit-up ≥ 1.
        # Falls back to liquid_today if filter is too aggressive (< min_quality_universe).
        use_qf = cfg.get("use_quality_filter", True)
        min_qu = cfg.get("min_quality_universe", 20)
        if use_qf:
            quality_today = apply_quality_filter(idx, liquid_today, T,
                                                  require_g4_limitup=cfg.get("quality_require_limitup", True),
                                                  min_60d_ret=cfg.get("quality_min_60d_ret", 0.0),
                                                  dd_floor=cfg.get("quality_dd_floor", 0.80),
                                                  up_day_min=cfg.get("quality_up_day_min", 10))
            scan_pool = quality_today if len(quality_today) >= min_qu else liquid_today
        else:
            scan_pool = liquid_today
        # iter-14: sector top-5 → top-3(更挑,集中在最热行业)
        # iter-17 R2: sector ranking is momentum-based → for inverse strategy,
        # expand top_k via cfg to include all sectors (effectively disable filter).
        sector_top_k = int(cfg.get("_sector_top_k", 3))
        top_sectors, universe = fast_sector_score(idx, sector_mapping, scan_pool, T,
                                                    lookback_days=60, top_k=sector_top_k)
        if not universe:
            universe = scan_pool[:200]

        # Signal scan (FAST!)
        scan_set = list(set(universe) | set(positions.keys()))
        signals = fast_signals_batch(
            idx, scan_set, T,
            signal_weights=cfg.get("signal_weights_override"),
            factor_directions=cfg.get("factor_directions"),
            skip_atr_veto=cfg.get("_skip_atr_veto", False),
            skip_ma50_veto=cfg.get("_skip_ma50_veto", False),
        )

        # Exits
        # build a per-ticker pseudo-panel for evaluate_exits (it does its own slicing)
        # iter-15: STRUCTURE-BASED EXIT (per Junyan methodology)
        # 不强制 min_hold / time_stop。每只股票自己的 signal structure 决定持仓:
        #   - hard stop -8%: capital preservation (overrides all)
        #   - trailing -5% from peak: risk-off after gain
        #   - composite drops below "structure_break_threshold" (default 50):
        #     entry composite was ≥ 70, drop to ≤ 50 means signal weakened by ≥ 20 points → 出
        #   - take_profit +20%: let winners run (was 10% with half-sell, now full 20%)
        # NO time_stop / NO sector_drop / NO min_hold / NO take_profit_half.
        sb_threshold = cfg.get("structure_break_threshold", 50.0)
        tp_full = cfg.get("take_profit_full", 0.20)
        exit_actions = {}
        # ATTRIBUTION (iter-16 ablation):
        #   _only_time_stop=True → ignore all exits except time_stop_days
        #   _ew_500=True         → daily full rebal (sell EVERYTHING, re-buy from pool)
        only_time = cfg.get("_only_time_stop", False)
        ew_rebal = cfg.get("_ew_500", False)
        time_stop = cfg.get("time_stop_days", 7)
        # v3 Phase B α1.1 (Junyan 2026-05-28 PM5 ratify): hold_continuation +
        # rank_buffer + turnover_budget. On rebal days, positions whose rank
        # falls outside the top-N buffer are candidates for replacement, but
        # at most `turnover_budget_per_rebal` swaps occur per rebal. Hard-stop
        # exits fire daily and do NOT count against the budget. Time_stop is
        # disabled. Same-day rebuy is blocked separately in the buy loop.
        hold_continuation_enabled = bool(cfg.get("hold_continuation_enabled", False))
        for tk, pos in positions.items():
            row = idx.latest_row(tk, T)
            if row is None:
                exit_actions[tk] = "hold"; continue
            if ew_rebal:
                # daily full sell — re-buy fresh from pool
                exit_actions[tk] = "sell_ew_rebal"; continue
            days = pos.get("days_held", 0)
            if hold_continuation_enabled:
                # Daily: hard_stop fires; optional max_hold_days cap forces
                # rotation. Time_stop is disabled. Rank-out replacement decision
                # is taken later in the rebal block (lines after `scored` is
                # built), and replaces at most turnover_budget_per_rebal per rebal.
                entry_p = pos["entry_price"]
                cur = row["close"]
                mtm = (cur - entry_p) / entry_p if entry_p > 0 else 0
                max_hold = cfg.get("max_hold_days")
                if mtm <= cfg.get("hard_stop_pct", -0.08):
                    exit_actions[tk] = "sell_hard_stop"
                elif max_hold is not None and days >= int(max_hold):
                    # v3 α1.3A anti-drift cap (Junyan 2026-05-29): prevent a
                    # position squatting in the top-N rank buffer indefinitely
                    # (α1.2 drift = 124d avg hold over 20yr). Forced exit; the
                    # freed slot refills at the next rebal, NOT against budget
                    # (treated like hard_stop). same_day_rebuy=False still blocks
                    # re-buying THIS ticker today.
                    exit_actions[tk] = "sell_max_hold"
                else:
                    exit_actions[tk] = "hold"
                continue
            if only_time:
                exit_actions[tk] = "sell_time_stop" if days >= time_stop else "hold"
                continue
            entry_p = pos["entry_price"]
            cur = row["close"]
            mtm = (cur - entry_p) / entry_p if entry_p > 0 else 0
            peak = pos.get("peak_price", entry_p)
            trail = (cur - peak) / peak if peak > 0 else 0
            cur_comp = (signals.get(tk) or {}).get("composite")

            if mtm <= cfg["hard_stop_pct"]:
                exit_actions[tk] = "sell_hard_stop"
            elif trail <= cfg["trailing_stop_pct"]:
                exit_actions[tk] = "sell_trailing"
            elif mtm >= tp_full:
                exit_actions[tk] = "sell_take_profit_20"
            elif cur_comp is not None and cur_comp < sb_threshold:
                exit_actions[tk] = "sell_structure_break"
            else:
                exit_actions[tk] = "hold"

        # Compute target weights from signals + ATR sizing
        # iter-14: 入场严格化 — 必须 composite ≥ entry_composite_threshold(70)才进场
        # ATTRIBUTION (iter-16 ablation):
        #   _invert_signal=True → pick LOWEST composite (anti-edge test)
        #   _ew_500=True        → equal-weight liquid_today[:N], skip composite scoring
        entry_threshold = cfg.get("entry_composite_threshold", 0.0)
        if cfg.get("_ew_500"):
            # A3: equal-weight liquid pool, no scoring
            ew_pool = liquid_today[:cfg.get("_ew_n", 500)]
            scored = [(tk, 50.0) for tk in ew_pool]    # dummy composite for sizing path
        elif cfg.get("_invert_signal"):
            # A2: take bottom-N composite (no threshold gate)
            scored = [(tk, s.get("composite")) for tk, s in signals.items()
                      if s and s.get("composite") is not None]
            scored.sort(key=lambda kv: kv[1])    # ascending: low composite first
        else:
            scored = [(tk, s.get("composite")) for tk, s in signals.items()
                      if s and s.get("composite") is not None
                      and s["composite"] >= entry_threshold]
            scored.sort(key=lambda kv: -kv[1])
        # ATTRIBUTION (iter-17 R2): rebal_cadence gates NEW entries to once per N days.
        # Exits (hard_stop / time_stop) still trigger daily; only buy-side throttles.
        rebal_cadence = int(cfg.get("rebal_cadence", 1) or 1)
        is_rebal_day = (i % rebal_cadence == 0)
        if not is_rebal_day:
            scored = []   # skip entries today; exits still happen

        # v3 Phase B α1.1 (Junyan 2026-05-28 PM5 ratify): turnover mechanics
        # rebal-day budget + rank-buffer.
        #
        # Spec:
        #   On a rebal day, when hold_continuation_enabled=True:
        #     1. Compute composite rank for each ticker (already in `scored`).
        #     2. For each existing position still alive (not already marked
        #        sell_hard_stop earlier), find its rank in `scored`.
        #     3. Mark "rank-out" if rank > rank_buffer_top_n (= 20 in α1.1).
        #     4. Apply budget: at most turnover_budget_per_rebal swaps.
        #        - Sell the WORST rank-out holding (highest rank #, weakest signal).
        #        - Buy the TOP scored new candidate (not currently held).
        #     5. Empty slots (from previous hard_stop / from bootstrap):
        #        fill with top-ranked NEW candidates. This is NOT counted
        #        against the budget; the spec says "hard_stop exits do not
        #        count against budget; re-entry waits until next rebalance"
        #        — i.e. the next rebal fills the slot freely.
        #     6. Existing positions still in the buffer → hold; don't re-buy.
        rank_buf = cfg.get("rank_buffer_top_n")
        turnover_budget = cfg.get("turnover_budget_per_rebal")
        if (hold_continuation_enabled and is_rebal_day
                and rank_buf is not None and turnover_budget is not None):
            rank_buf_n = int(rank_buf)
            budget_n = int(turnover_budget)
            target_n_holdings = int(
                cfg.get("top_n_picks", cfg.get("max_positions", 0)) or 0
            )

            # Build a stable rank map from the FULL scored list (composite desc).
            # Ranks are 1-indexed; ties broken by sort order.
            rank_map: dict[str, int] = {}
            for rank_i, (cand_tk, cand_sc) in enumerate(scored, start=1):
                rank_map.setdefault(cand_tk, rank_i)

            # Per Junyan PM5: "keep existing holdings unless they fall outside
            # top-{rank_buf_n} inverse-score candidate buffer".
            still_holding = [tk for tk, act in exit_actions.items()
                             if act == "hold"]
            n_hard_stop = sum(1 for a in exit_actions.values() if a == "sell_hard_stop")

            # Rank-out = no signal today OR rank > rank_buf_n.
            rank_out = []
            for tk in still_holding:
                r = rank_map.get(tk)
                if r is None or r > rank_buf_n:
                    rank_out.append((tk, r if r is not None else 10**9))
            rank_out.sort(key=lambda kv: -kv[1])   # worst first

            # New-candidate queue: scored MINUS currently held tickers.
            held_set = set(positions.keys())
            new_candidates = [(tk, sc) for tk, sc in scored if tk not in held_set]
            new_iter = iter(new_candidates)

            # ── Step A: Empty-slot fills (NOT counted against budget).
            # Empty slots = target - (# still holding) - (# replacements queued).
            # We fill these from the top of new_candidates.
            # n_after_hard_stop = positions remaining after sells (still_holding).
            n_empty_slots = max(0, target_n_holdings - len(still_holding))
            new_picks: list[tuple[str, float]] = []
            for _ in range(n_empty_slots):
                try:
                    new_picks.append(next(new_iter))
                except StopIteration:
                    break

            # ── Step B: Apply replacement budget for rank-out holdings.
            n_replaced = 0
            replaced_tickers = []
            for k in range(min(budget_n, len(rank_out))):
                worst_tk, worst_rank = rank_out[k]
                try:
                    top_new_tk, top_new_sc = next(new_iter)
                except StopIteration:
                    break
                exit_actions[worst_tk] = "sell_rank_out"
                replaced_tickers.append((worst_tk, worst_rank, top_new_tk))
                new_picks.append((top_new_tk, top_new_sc))
                n_replaced += 1

            # Restrict scored to the budget-allocated new picks. Existing
            # holdings (not marked sell_rank_out) will be kept by
            # _cap_scored_to_available_slots since their exit_action == "hold".
            scored = new_picks

            rebal_audit_records.append({
                "date": T,
                "n_holdings_in": len(still_holding) + n_hard_stop,
                "n_holdings_still_hold_pre_swap": len(still_holding),
                "n_hard_stop_exits": n_hard_stop,
                "n_empty_slots_filled": min(n_empty_slots, len(new_picks) - n_replaced),
                "n_rank_out_candidates": len(rank_out),
                "n_replaced": n_replaced,
                "replaced_tickers": [t[0] for t in replaced_tickers],
                "new_picks": [t[0] for t in new_picks],
                "rank_buffer_n": rank_buf_n,
                "turnover_budget": budget_n,
            })
        elif hold_continuation_enabled and is_rebal_day:
            # Configured for continuation but missing knobs → record empty rebal.
            still_holding = [tk for tk, act in exit_actions.items() if act == "hold"]
            rebal_audit_records.append({
                "date": T,
                "n_holdings_in": len(positions),
                "n_holdings_still_hold_pre_swap": len(still_holding),
                "n_hard_stop_exits": sum(
                    1 for a in exit_actions.values() if a == "sell_hard_stop"
                ),
                "n_empty_slots_filled": 0,
                "n_rank_out_candidates": None,
                "n_replaced": 0,
                "replaced_tickers": [],
                "new_picks": [],
                "rank_buffer_n": None,
                "turnover_budget": None,
            })

        scored, _position_gate = _cap_scored_to_available_slots(
            scored, positions, exit_actions, cfg
        )
        target_weights = {}
        sector_totals: dict[str, float] = {}
        # ATTRIBUTION A3: equal-weight bypass — no signals lookup, uniform sizing.
        if cfg.get("_ew_500"):
            if scored:
                w = cfg.get("max_gross", 0.95) / len(scored)
                target_weights = {tk: w for tk, _ in scored}
            # apply gross cap below, but skip ATR/sector sizing loop
            scored = []   # skip the for-loop below
        for tk, score in scored:
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
            gross = _portfolio_gross(idx, positions, T, nav)
            equity_curve.append({"date": T, "nav": round(nav, 2), "cash": round(cash, 2),
                                  "gross": round(gross, 6),
                                  "n_positions": len(positions), "drawdown": round(dd, 4)})
            break
        T_next = trade_dates[i + 1]

        # Sells
        sold = []
        # v3 Phase B α1.1: track which tickers were sold today so the buy loop
        # can block same-day rebuys when cfg.same_day_rebuy=False.
        sold_today_local: set[str] = set()
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
            price = fill_price(row, "sell", slippage=_cost_slippage)
            if price is None: continue
            notional = units * price
            cost = trade_cost(notional, "sell",
                              commission=_cost_commission,
                              stamp_duty_sell=_cost_stamp)
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
                sold_today_local.add(tk)
        for tk in sold:
            positions.pop(tk, None)

        # Buys
        # Spec §4.3: max 12 active positions concurrently.
        # SELL loop above has already removed today's exits, so len(positions) here
        # reflects NET surviving positions. Buy-loop respects the cap by skipping
        # any NEW ticker once at capacity — existing positions may still add.
        # v3 Phase B α1.1: when same_day_rebuy=False, block any buy of a ticker
        # that was sold today. Default True preserves legacy behavior.
        allow_same_day_rebuy = bool(cfg.get("same_day_rebuy", True))
        max_pos = cfg.get("max_positions", 12)
        for tk, target_w in target_weights.items():
            if not allow_same_day_rebuy and tk in sold_today_local:
                # α1.1: post-hard-stop slot waits until next rebal day, AND
                # any other same-day rebuy is also blocked. Count for audit.
                same_day_rebuy_blocked += 1
                continue
            # Enforce spec max_positions: if already at cap, only allow adds to existing.
            if len(positions) >= max_pos and tk not in positions:
                continue
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
            price = fill_price(row, "buy", slippage=_cost_slippage)
            if price is None: continue
            units = delta / price
            cost = trade_cost(delta, "buy",
                              commission=_cost_commission,
                              stamp_duty_sell=_cost_stamp)
            cash -= delta + cost
            trade_log.append({"date": T_next, "ts_code": tk, "side": "buy",
                               "action": "open_or_add", "units": round(units, 2),
                               "price": round(price, 4), "notional": round(delta, 2),
                               "cost": round(cost, 4)})
            # v3 Phase B α1.1: detect same-day rebuy events that *executed*
            # (only possible when same_day_rebuy=True or buyer hit cur_pos add).
            if tk in sold_today_local:
                same_day_rebuy_executed += 1
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
        nx_gross = _portfolio_gross(idx, positions, T_next, nx_nav)
        equity_curve.append({"date": T_next, "nav": round(nx_nav, 2),
                              "cash": round(cash, 2), "gross": round(nx_gross, 6),
                              "n_positions": len(positions),
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
    gross_values = [float(pt.get("gross", 0.0) or 0.0) for pt in equity_curve]
    n_position_values = [int(pt.get("n_positions", 0) or 0) for pt in equity_curve]
    avg_gross = float(np.mean(gross_values)) if gross_values else 0.0
    median_gross = float(np.median(gross_values)) if gross_values else 0.0
    max_gross = float(max(gross_values)) if gross_values else 0.0
    avg_n_positions = float(np.mean(n_position_values)) if n_position_values else 0.0
    median_n_positions = float(np.median(n_position_values)) if n_position_values else 0.0
    max_n_positions = int(max(n_position_values)) if n_position_values else 0
    annualized_trades = (len(trade_log) / n_years) if n_years > 0 else 0.0
    audit_gates = _audit_gates(cfg, max_n_positions, annualized_trades)

    # ─────────────── R0 Step 2: Engine audit metrics ────────────────────
    # Honest reporting of spec compliance + execution stats. Junyan red line:
    # "宁愿犯错也不愿意找不出来错误在哪" — surface everything.
    total_notional = sum(float(t.get("notional", 0.0) or 0.0) for t in trade_log)
    avg_nav = float(np.mean(eqs)) if eqs else capital
    # v3 Phase A Junyan ratify #2 (2026-05-28 PM2): the historical audit field is
    # a unit-less ratio (total notional / avg NAV / years). v3 §2 IMPL4 threshold
    # is "turnover_annual_ratio <= 2.0" (= 200%). We expose the ratio as the
    # canonical field. turnover_annual_pct kept as deprecated alias for legacy
    # consumers (same numeric value; report layer should multiply by 100 for %).
    turnover_annual_ratio = (
        (total_notional / avg_nav / n_years) if (avg_nav > 0 and n_years > 0) else 0.0
    )
    # deprecated: turnover_annual_pct is misleadingly named — value is a ratio,
    # not a percentage. Use turnover_annual_ratio.
    turnover_annual_pct = turnover_annual_ratio

    # Holding days reconstructed from FIFO buy→sell pairing in full trade_log
    # (engine does not record days_held on the sell event).
    from datetime import datetime as _dt
    holding_days_list: list[int] = []
    open_buys: dict[str, list] = {}
    for t in trade_log:
        tk = t.get("ts_code"); side = t.get("side")
        d_str = str(t.get("date", "")).replace("-", "")[:8]
        if not d_str.isdigit() or len(d_str) != 8:
            continue
        if side == "buy":
            open_buys.setdefault(tk, []).append([d_str, float(t.get("units", 0))])
        elif side == "sell":
            need = float(t.get("units", 0))
            queue = open_buys.get(tk, [])
            while need > 1e-6 and queue:
                buy_d, buy_u = queue[0]
                take = min(need, buy_u)
                try:
                    bd = _dt.strptime(buy_d, "%Y%m%d")
                    sd = _dt.strptime(d_str, "%Y%m%d")
                    diff = (sd - bd).days
                except Exception:
                    diff = 0
                holding_days_list.append(diff)
                buy_u -= take
                need -= take
                if buy_u <= 1e-6:
                    queue.pop(0)
                else:
                    queue[0][1] = buy_u
    avg_holding_days = (
        float(np.mean(holding_days_list)) if holding_days_list else 0.0
    )

    # Reproducibility hashes
    try:
        cfg_hash = hashlib.md5(
            json.dumps(cfg, sort_keys=True, default=str).encode()
        ).hexdigest()
    except Exception:
        cfg_hash = "unhashable"
    try:
        data_sig = f"{len(daily_panel)}r-{daily_panel['ts_code'].nunique()}t"
        data_hash = hashlib.md5(data_sig.encode()).hexdigest()
    except Exception:
        data_hash = "unhashable"
    try:
        git_commit = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).strip().decode()
    except Exception:
        git_commit = "unknown"

    max_positions_cfg = int(cfg.get("max_positions", 12))

    # ─────────────── v3 Phase B α1.1 turnover mechanics audit ───────────────
    # Per Junyan 2026-05-28 PM5 ratify, report on the new audit fields:
    #   - untouched_carry_over_avg: positions per rebal that continue to next rebal unchanged
    #   - same_day_rebuy_count: total executed + blocked
    #   - full_refresh_rate: trade dates with |trades_today| >= 0.5 * top_n_picks
    #   - replacement_count_per_rebal: distribution
    #
    # For α1 (legacy), rebal_audit_records will be empty and same_day_rebuy_*
    # counters will be 0; the fields surface as 0/None. The diagnostic
    # baseline (Task 70) showed α1: 89.8% full-refresh, 0.81 untouched/rebal.
    top_n_picks_cfg = int(cfg.get("top_n_picks", max_positions_cfg) or max_positions_cfg)
    # Untouched per rebal: holdings continuing into next rebal without trade.
    # = still_hold_pre_swap (= positions w/ exit_action == "hold")
    #   - replaced (= rank_out swaps that triggered both sell + new buy)
    # Note: hard_stop exits are already excluded from still_hold_pre_swap.
    untouched_per_rebal: list[int] = []
    replacements_per_rebal: list[int] = []
    for rec in rebal_audit_records:
        still_hold = int(rec.get("n_holdings_still_hold_pre_swap") or 0)
        n_replaced = int(rec.get("n_replaced") or 0)
        untouched_per_rebal.append(max(0, still_hold - n_replaced))
        replacements_per_rebal.append(n_replaced)
    untouched_carry_over_avg = (
        float(np.mean(untouched_per_rebal)) if untouched_per_rebal else 0.0
    )
    # Full-refresh-like: trade dates where #trades(today) >= 0.5 * top_n_picks.
    # Per-date trade counts from trade_log.
    trades_per_date: dict[str, int] = {}
    for t in trade_log:
        d = str(t.get("date", ""))
        trades_per_date[d] = trades_per_date.get(d, 0) + 1
    full_refresh_threshold = 0.5 * top_n_picks_cfg
    n_active_trade_dates = sum(1 for c in trades_per_date.values() if c > 0)
    n_full_refresh_dates = sum(
        1 for c in trades_per_date.values() if c >= full_refresh_threshold
    )
    full_refresh_rate = (
        n_full_refresh_dates / n_active_trade_dates if n_active_trade_dates > 0
        else 0.0
    )
    same_day_rebuy_count_total = int(same_day_rebuy_executed + same_day_rebuy_blocked)
    replacement_dist = {
        "mean": float(np.mean(replacements_per_rebal)) if replacements_per_rebal else 0.0,
        "median": float(np.median(replacements_per_rebal)) if replacements_per_rebal else 0.0,
        "min": int(min(replacements_per_rebal)) if replacements_per_rebal else 0,
        "max": int(max(replacements_per_rebal)) if replacements_per_rebal else 0,
        "p25": float(np.percentile(replacements_per_rebal, 25)) if replacements_per_rebal else 0.0,
        "p75": float(np.percentile(replacements_per_rebal, 75)) if replacements_per_rebal else 0.0,
        "n_rebal_days": len(replacements_per_rebal),
    }

    audit = {
        "engine_version": "fast-v3-audit",   # v3 Phase B engine extensions
        "config_hash": cfg_hash,
        "data_hash": data_hash,
        "git_commit": git_commit,
        # v3 Phase B (Junyan ratify #5): audit.created_at proves PRE2 ordering.
        # ISO-8601 UTC with Z suffix so PRE2 lexicographic compare vs
        # manifest.variant.registered_at is unambiguous.
        "created_at": datetime.utcnow().isoformat() + "Z",
        # spec compliance — SWING_STRATEGY_v1.md §4.3
        "max_positions_cfg": max_positions_cfg,
        "max_positions_reached": max_n_positions,
        "max_positions_enforced": bool(max_n_positions <= max_positions_cfg),
        "avg_n_positions": avg_n_positions,
        "median_n_positions": median_n_positions,
        # gross exposure
        "avg_gross_pct": avg_gross,
        "max_gross_pct": max_gross,
        # activity
        # v3 Phase A: turnover_annual_ratio is the canonical field (per Junyan
        # ratify #2). turnover_annual_pct is a deprecated alias — same value,
        # misleadingly named. v3 IMPL4 reads turnover_annual_ratio first.
        "turnover_annual_ratio": float(turnover_annual_ratio),
        "turnover_annual_pct": float(turnover_annual_pct),
        "avg_holding_days": float(avg_holding_days),
        "n_holding_periods_observed": len(holding_days_list),
        "n_total_trades_actual": len(trade_log),
        # window
        "n_trade_days": n_days,
        "n_years": n_years,
        # v3 Phase B α1.1 turnover mechanics audit (Junyan 2026-05-28 PM5)
        "untouched_carry_over_avg": float(untouched_carry_over_avg),
        "same_day_rebuy_count": same_day_rebuy_count_total,
        "same_day_rebuy_executed": int(same_day_rebuy_executed),
        "same_day_rebuy_blocked": int(same_day_rebuy_blocked),
        "full_refresh_rate": float(full_refresh_rate),
        "full_refresh_threshold_trades": float(full_refresh_threshold),
        "n_full_refresh_dates": int(n_full_refresh_dates),
        "n_active_trade_dates": int(n_active_trade_dates),
        "replacement_count_per_rebal": replacement_dist,
        "n_rebal_days_observed": len(rebal_audit_records),
        "hold_continuation_enabled": bool(cfg.get("hold_continuation_enabled", False)),
        "rank_buffer_top_n": cfg.get("rank_buffer_top_n"),
        "turnover_budget_per_rebal": cfg.get("turnover_budget_per_rebal"),
        "same_day_rebuy_allowed": bool(cfg.get("same_day_rebuy", True)),
    }

    # ─────────────── R0 Step 3: Same-gross curve ────────────────────────
    # Per-day gross_pct emitted so caller (bootstrap script) can compute
    #   scaled_strat_ret = daily_strat_ret / max(yesterday_gross_pct, 0.05)
    #   same_gross_alpha = scaled_strat_ret - bench_ret
    # Engine does NOT mutate cagr/alpha — caller does the math.
    gross_exposure_curve = []
    for e in equity_curve:
        gp = e.get("gross")
        if gp is None:
            gp = ((e["nav"] - e["cash"]) / e["nav"]) if e.get("nav", 0) > 0 else 0.0
        gross_exposure_curve.append({
            "date": e["date"],
            "nav": e["nav"],
            "cash": e["cash"],
            "gross_pct": round(float(gp), 6),
        })

    # ─────────────── R0 Step 4 + v3 Phase B: Multi-benchmark dict ───────
    # v3 Phase B (Junyan ratify #13): index curves now sourced from the audited
    # `data_history/panel/index_prices.parquet` via `v3_bench_loader`, not from
    # the stock panel. This replaces the Phase A stubs ("not_available_in_panel")
    # with real csi300/zz500/csi1000 same-gross-comparable curves.
    #
    # Required curves (BENCH gate):
    #   - ew_500             (R0 carry — equal-weight liquid top-N strategy bench)
    #   - ew_500_same_gross  (R0 carry — gross-matched strategy comparison)
    #   - csi300             (v3 Phase B — from index parquet)
    #   - zz500 / csi500     (v3 Phase B — from index parquet)
    #   - csi1000 / zz1000   (v3 Phase B — from index parquet)
    #   - cash_2pct          (R0 carry — 2% risk-free baseline)
    cash_curve = []
    cash_eq = capital
    daily_rf = (1 + 0.02) ** (1 / 252) - 1
    for d in trade_dates:
        cash_eq *= (1 + daily_rf)
        cash_curve.append({"date": d, "equity": round(cash_eq, 2)})
    ew_500_same_gross_curve = _same_gross_benchmark_curve(
        bench_curve, equity_curve, capital, daily_rf
    )

    # v3 Phase B index benchmark loading (per task brief B2.2).
    # Window: backtest [start, end] inclusive.
    # If parquet missing OR index unavailable in window → emit empty list and
    # record warning under benchmarks._warnings for caller diagnosis.
    bench_warnings = []
    benchmarks = {
        "ew_500": bench_curve,    # equal-weight liquid top-500 (existing)
        "ew_500_same_gross": ew_500_same_gross_curve,
        "cash_2pct": cash_curve,
    }
    try:
        from v3_bench_loader import load_named_benchmark
        for _bench_name in ("csi300", "zz500", "csi1000"):
            try:
                curve = load_named_benchmark(
                    _bench_name, start=start_yyyymmdd, end=end_yyyymmdd,
                    capital=capital,
                )
                if curve:
                    benchmarks[_bench_name] = curve
                else:
                    benchmarks[_bench_name] = []
                    bench_warnings.append(
                        f"{_bench_name}: empty curve for [{start_yyyymmdd}, {end_yyyymmdd}]"
                    )
            except (KeyError, FileNotFoundError) as _e:
                benchmarks[_bench_name] = []
                bench_warnings.append(f"{_bench_name}: {type(_e).__name__}: {str(_e)[:80]}")
    except ImportError as _e:
        # Defensive: should never happen because v3_bench_loader is in scripts/.
        bench_warnings.append(f"v3_bench_loader import failed: {str(_e)[:80]}")
        for _bench_name in ("csi300", "zz500", "csi1000"):
            benchmarks[_bench_name] = []
    if bench_warnings:
        benchmarks["_warnings"] = bench_warnings
    benchmark_availability = {
        name: ("available" if (isinstance(curve, list) and len(curve) > 0) else "empty_or_warning")
        for name, curve in benchmarks.items() if name != "_warnings"
    }

    return {
        "_meta": {"start": start, "end": end, "capital": capital,
                  "engine": "fast (PanelIndex + numpy)",
                  "n_days": n_days, "n_trades": len(trade_log),
                  "liquid_top_n": liquid_top_n,
                  "benchmark": "liquid_top_n_equal_weight",
                  "benchmark_description": (
                      f"Daily equal-weight return of liquid top-{liquid_top_n}; "
                      "fully invested, not CSI300."
                  ),
                  "cash_adjusted_alpha_inputs": {
                      "strategy_gross_series": "equity_curve[].gross",
                      "benchmark_curve": "bench_curve[].equity",
                      "same_gross_benchmark_daily": "benchmarks.ew_500_same_gross",
                      "cash_curve": "benchmarks.cash_2pct",
                      "method": ("same_gross_return = strategy_gross * ew_500_return "
                                 "+ (1 - strategy_gross) * cash_2pct_daily_return"),
                  }},
        "cagr": cagr, "sharpe_annualized": sharpe, "max_drawdown": max_dd,
        "avg_gross": avg_gross, "median_gross": median_gross,
        "max_gross": max_gross,
        "avg_n_positions": avg_n_positions,
        "median_n_positions": median_n_positions,
        "max_n_positions": max_n_positions,
        "annualized_trades": annualized_trades,
        "audit_gates": audit_gates,
        "final_nav": eqs[-1], "ann_vol": s * math.sqrt(252) if s else None,
        "equity_curve": equity_curve, "bench_curve": bench_curve,
        "trade_log": trade_log[-200:], "risk_log": risk_log[-50:],
        "n_total_trades": len(trade_log),
        # ── R0 new audit-quality fields (engine v2-audit) ─────────────
        "audit": audit,
        "trade_log_full": trade_log,
        "gross_exposure_curve": gross_exposure_curve,
        "same_gross_curve": ew_500_same_gross_curve,
        "benchmarks": benchmarks,
        "benchmark_availability": benchmark_availability,
        # v3 Phase B (Junyan ratify #4): cost_scenario emit for gate eval.
        "cost_scenario": cost_scenario,
        "cost_constants": {
            "COMMISSION": _cost_commission,
            "STAMP_DUTY_SELL": _cost_stamp,
            "SLIPPAGE": _cost_slippage,
            "round_trip_estimate": cost_consts.get("_round_trip_estimate"),
        },
        # v3 Phase B α1.1 (Junyan 2026-05-28 PM5): rebal-day audit records.
        # One row per rebal day; empty when hold_continuation_enabled=False.
        "rebal_audit_records": rebal_audit_records,
    }


def _selftest() -> int:
    failures = []

    cfg = {"max_positions": 4, "top_n_picks": 3}
    positions = {"A": {}, "B": {}}
    exit_actions = {"A": "hold", "B": "hold"}
    scored = [("N1", 90.0), ("A", 85.0), ("N2", 80.0), ("N3", 75.0), ("B", 70.0)]
    capped, gate = _cap_scored_to_available_slots(scored, positions, exit_actions, cfg)
    capped_names = [tk for tk, _ in capped]
    if capped_names != ["A", "B", "N1"]:
        failures.append(f"expected one new plus two existing, got {capped_names}")
    if gate["active_limit"] != 3 or gate["new_candidates_allowed"] != 1:
        failures.append(f"unexpected position gate metadata: {gate}")

    over_positions = {f"P{i}": {} for i in range(6)}
    over_exits = {tk: "hold" for tk in over_positions}
    over_scored = [(f"N{i}", 90.0 - i) for i in range(3)] + [("P1", 80.0)]
    capped_over, gate_over = _cap_scored_to_available_slots(
        over_scored, over_positions, over_exits, cfg
    )
    capped_over_names = [tk for tk, _ in capped_over]
    if capped_over_names != ["P1"]:
        failures.append(f"over-limit book should block new buys, got {capped_over_names}")
    if gate_over["new_slots"] != 0:
        failures.append(f"over-limit book should expose zero new slots: {gate_over}")

    gates = _audit_gates(cfg, max_n_positions=6, annualized_trades=123.4)
    if not gates["max_positions_violation"]:
        failures.append("audit gate did not flag max_positions_violation")
    if not gates["top_n_picks_total_holdings_violation"]:
        failures.append("audit gate did not flag top_n_picks_total_holdings_violation")
    if gates["turnover_spec_feasibility"]["status"] != "not_specified":
        failures.append(f"unexpected turnover status: {gates['turnover_spec_feasibility']}")

    gates_with_turnover = _audit_gates(
        {**cfg, "max_annualized_trades": 100}, max_n_positions=3,
        annualized_trades=123.4
    )
    if not gates_with_turnover["turnover_spec_feasibility"]["violation"]:
        failures.append("audit gate did not flag configured turnover violation")

    same_gross = _same_gross_benchmark_curve(
        [
            {"date": "20240102", "equity": 110.0},
            {"date": "20240103", "equity": 121.0},
        ],
        [
            {"date": "20240102", "gross": 0.5},
            {"date": "20240103", "gross": 0.0},
        ],
        100.0,
        0.0,
    )
    if round(same_gross[0]["equity"], 4) != 105.0:
        failures.append(f"same-gross first step wrong: {same_gross}")
    if round(same_gross[1]["equity"], 4) != 105.0:
        failures.append(f"same-gross zero-gross step should stay flat: {same_gross}")

    # v3 Phase A turnover_annual_ratio synthetic check:
    # 1 trade @ ¥1M notional in ¥10M avg NAV over 1 year -> ratio = 0.10
    # (i.e. one round-trip leg = 10% of book turned over per year).
    # Validates the formula total_notional / avg_nav / n_years (engine v2-audit).
    _trade_notional = 1_000_000.0
    _avg_nav_test = 10_000_000.0
    _n_years_test = 1.0
    _expected_ratio = _trade_notional / _avg_nav_test / _n_years_test
    if round(_expected_ratio, 6) != 0.1:
        failures.append(
            f"turnover_annual_ratio formula expectation wrong: "
            f"got {_expected_ratio}, expected 0.1 (¥1M / ¥10M / 1yr)"
        )
    # Edge: zero-nav guard returns 0 not NaN/inf
    _zero_ratio = (
        (_trade_notional / 0.0 / 1.0) if False else 0.0  # mirrors engine guard
    )
    if _zero_ratio != 0.0:
        failures.append(f"turnover ratio zero-NAV guard mishandled: {_zero_ratio}")
    # Two-trade case: 2 trades @ ¥500k in ¥10M / 1yr -> ratio = 0.10 (same)
    _two_total = 2 * 500_000.0
    _two_ratio = _two_total / _avg_nav_test / _n_years_test
    if round(_two_ratio, 6) != 0.1:
        failures.append(
            f"two-trade ratio expectation wrong: got {_two_ratio}, expected 0.1"
        )

    # ──────────── v3 Phase B selftests (Junyan ratify #6/#7) ─────────────
    # B1 momentum_20d factor + normalization sanity check.
    # B2 audit.created_at + multi-bench dispatch ist tested in B2 selftest below.
    # B3 cost scenario dispatch.
    #
    # B1 selftest: synthetic 60-day linear rising stock.
    # Day i close = 100 * (1 + 0.001 * i) for i in [0..60). At index t=-1 (day 59)
    # close = 100 * 1.059 = 105.9. At t=-22 (day 37) close = 100 * 1.037 = 103.7.
    # Expected momentum_20d = 105.9 / 103.7 - 1 ≈ +0.0212 (about +2.12%).
    # Normalization: vv = (0.0212 + 0.4) / 0.8 ≈ 0.5265 → in [0,1] ✓.
    _expected_m20_raw = 105.9 / 103.7 - 1
    _expected_m20_norm = (_expected_m20_raw + 0.4) / 0.8
    if not (0.0 <= _expected_m20_norm <= 1.0):
        failures.append(
            f"momentum_20d norm out of [0,1]: got {_expected_m20_norm} from raw {_expected_m20_raw}"
        )
    if not (0.0150 < _expected_m20_raw < 0.0250):
        failures.append(
            f"momentum_20d formula sanity wrong: expected ~+2.12%, got {_expected_m20_raw*100:.2f}%"
        )
    # Edge: with clamp [-0.4,+0.4], a 0% gain → norm 0.5 (mid).
    _zero_norm = (0.0 + 0.4) / 0.8
    if abs(_zero_norm - 0.5) > 1e-9:
        failures.append(f"momentum_20d zero-gain norm should be 0.5, got {_zero_norm}")
    # Edge: extreme +50% gain clamps to +0.4 → norm 1.0
    _hi_clamp_norm = (min(0.4, 0.5) + 0.4) / 0.8
    if abs(_hi_clamp_norm - 1.0) > 1e-9:
        failures.append(f"momentum_20d +50% clamp should hit 1.0, got {_hi_clamp_norm}")
    # Edge: extreme -50% loss clamps to -0.4 → norm 0.0
    _lo_clamp_norm = (max(-0.4, -0.5) + 0.4) / 0.8
    if abs(_lo_clamp_norm - 0.0) > 1e-9:
        failures.append(f"momentum_20d -50% clamp should hit 0.0, got {_lo_clamp_norm}")
    # momentum_20d is in DEFAULT_SIGNAL_WEIGHTS with weight 0 (does not perturb).
    if DEFAULT_SIGNAL_WEIGHTS.get("momentum_20d", None) != 0.0:
        failures.append(
            f"DEFAULT_SIGNAL_WEIGHTS['momentum_20d'] expected 0.0 (no default impact), got "
            f"{DEFAULT_SIGNAL_WEIGHTS.get('momentum_20d')}"
        )

    # B2 selftest: audit.created_at + benchmark loader integration tests.
    # The audit.created_at field is checked at engine run time (downstream of
    # run_swing_backtest_fast); we sanity-check the import and the helper here.
    try:
        from datetime import datetime as _dt_check
        from v3_bench_loader import (load_named_benchmark, RECOMMENDED_INDEX_MAP)
        # Quick smoke: load 1 month of csi300 (only if parquet available).
        from pathlib import Path as _P
        _parquet_path = REPO_ROOT / "data_history" / "panel" / "index_prices.parquet"
        if _parquet_path.exists():
            _curve = load_named_benchmark("csi300", start="2024-01-02",
                                          end="2024-01-31", capital=10_000_000.0)
            if not _curve or not isinstance(_curve, list):
                failures.append("B2: load_named_benchmark('csi300') returned empty/non-list")
            elif "equity" not in _curve[0]:
                failures.append(f"B2: csi300 curve point missing 'equity' key: {_curve[0]}")
        # created_at field shape sanity (ISO-8601 with Z suffix).
        _now_iso = _dt_check.utcnow().isoformat() + "Z"
        if not _now_iso.endswith("Z") or "T" not in _now_iso:
            failures.append(f"B2: audit.created_at ISO format wrong: {_now_iso}")
    except ImportError as e:
        failures.append(f"B2: cannot import v3_bench_loader: {e}")

    # B3 selftest: cost_scenario param dispatch.
    # v3 Phase B-fix (Junyan PM3 Bug 4): SLIPPAGE recalibrated so the COMPUTED
    # RT matches the scenario label exactly. Previously label was nominal and
    # actual RT was 15-30% lower (0.17% / 0.30% / 0.41%).
    #   - "optimistic_0.20_RT"  → actual RT 0.0020 (0.20%) ✓ exact label
    #   - "baseline_0.40_RT"    → actual RT 0.0040 (0.40%) ✓ exact label
    #   - "pessimistic_0.60_RT" → actual RT 0.0060 (0.60%) ✓ exact label
    # The envelope check is tight (±0.0001) to catch silent regressions.
    _cost_specs = _cost_constants_for_scenario("optimistic_0.20_RT")
    _rt_opt = 2 * (_cost_specs["COMMISSION"] + _cost_specs["SLIPPAGE"]) + _cost_specs["STAMP_DUTY_SELL"]
    if not (0.00195 < _rt_opt < 0.00205):
        failures.append(f"B3: optimistic RT cost out of envelope: {_rt_opt} not in (0.00195, 0.00205) — label was 0.20%")
    _cost_specs = _cost_constants_for_scenario("baseline_0.40_RT")
    _rt_base = 2 * (_cost_specs["COMMISSION"] + _cost_specs["SLIPPAGE"]) + _cost_specs["STAMP_DUTY_SELL"]
    if not (0.00395 < _rt_base < 0.00405):
        failures.append(f"B3: baseline RT cost out of envelope: {_rt_base} not in (0.00395, 0.00405) — label was 0.40%")
    _cost_specs = _cost_constants_for_scenario("pessimistic_0.60_RT")
    _rt_pess = 2 * (_cost_specs["COMMISSION"] + _cost_specs["SLIPPAGE"]) + _cost_specs["STAMP_DUTY_SELL"]
    if not (0.00595 < _rt_pess < 0.00605):
        failures.append(f"B3: pessimistic RT cost out of envelope: {_rt_pess} not in (0.00595, 0.00605) — label was 0.60%")
    # Monotonic: optimistic < baseline < pessimistic
    if not (_rt_opt < _rt_base < _rt_pess):
        failures.append(
            f"B3: cost RT not monotonic: opt={_rt_opt} base={_rt_base} pess={_rt_pess}"
        )
    # Unknown scenario should raise ValueError
    try:
        _cost_constants_for_scenario("nonexistent_scenario")
        failures.append("B3: unknown cost_scenario should raise ValueError")
    except ValueError:
        pass

    if failures:
        print("SELFTEST FAIL")
        for msg in failures:
            print(f" - {msg}")
        return 1
    print("SELFTEST PASS")
    return 0


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
    p.add_argument("--selftest", action="store_true",
                   help="Run deterministic position-gate/audit selftest and exit.")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()

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
