#!/usr/bin/env python3
"""swing_risk_manager.py — position sizing + exit rules + circuit breakers.

Per SWING_STRATEGY_v1.md §4 (Position sizing + risk).

Three top-level functions:
  compute_target_weights(signal_scores, daily_panel, as_of, sector_mapping, config) -> dict
  evaluate_exits(positions, daily_panel, as_of, current_signals, sector_top_k) -> dict
  check_portfolio_breakers(portfolio_state, market_state) -> dict
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent


DEFAULT_CONFIG = {
    "max_single_name_weight": 0.10,        # 10% cap per stock
    "safety_max_single_name": 0.12,        # absolute hard cap after sizing
    "max_sector_weight": 0.30,             # 30% per sector
    "max_gross": 0.95,                     # 95% gross exposure
    "max_positions": 12,                   # 12 active positions
    "target_portfolio_vol_ann": 0.20,      # 20% target ann. vol
    "vol_per_position": 0.02,              # 2% portfolio vol per name
    "hard_stop_pct": -0.08,                # -8% from entry
    "trailing_stop_pct": -0.05,            # -5% from peak
    "take_profit_pct": 0.10,               # +10% from entry
    "time_stop_days": 7,                   # sell after 7 days
    "composite_decay": 60,                 # legacy iter-13 path (slow engine)
    "min_hold_days": 0,                    # iter-15: disabled — per Junyan, structure decides not forced rule
    "enable_take_profit_half": False,      # iter-13: disabled
    "enable_sector_drop_exit": False,      # iter-13: disabled
    "entry_composite_threshold": 70.0,     # iter-14: 入场最低 composite 分
    "structure_break_threshold": 50.0,     # iter-15: exit when composite drops below this (entry was ≥70)
    "take_profit_full": 0.20,              # iter-15: full take profit at +20% (was 10% half)
    "drawdown_scale_down": -0.15,          # at -15% portfolio DD: reduce gross to 60%
    "drawdown_to_cash": -0.25,             # at -25% DD: flat all + wait 5 days
    "high_vol_regime_threshold": 0.30,     # realized 60d vol > 30% → reduce gross 50%
    # v3 Phase B-fix (Junyan PM3 2026-05-28 Bug 1): disable the permanent
    # drawdown_to_cash breaker for research backtests. The breaker's spec
    # comment claims "wait 5 days re-entry" but that re-entry path was never
    # implemented; once triggered, full_20yr is stuck flat for the remainder
    # of the window (14 years in the V3C-α1 case). Walk-forward sub-windows
    # avoided this because each window starts fresh.
    # Production (paper/capital): leave False until re-entry logic lands.
    # TODO: implement re-entry after N days post drawdown_to_cash trigger
    #       (v4 platform improvement).
    "disable_drawdown_breaker": False,
    "top_n_picks": 8,                      # default 8 active positions
    # iter-16: quality pre-filter knobs (上涨势能 + 故事代理)
    "use_quality_filter": True,            # apply quality_universe filter after liquid top-N
    "min_quality_universe": 20,            # if quality_today < this many, fall back to liquid_today
    "quality_require_limitup": True,       # G4: require ≥1 limit-up day in last 30d (热度代理)
    "quality_min_60d_ret": 0.0,            # G1: 60d return > this
    "quality_dd_floor": 0.80,              # G2: close > 60d_max × this
    "quality_up_day_min": 10,              # G3: 20d up-day count ≥ this
}


# ───────────────────────── ATR-based vol estimate ──────────────────────────

def _atr_vol_ann(group: pd.DataFrame, n: int = 14) -> Optional[float]:
    g = group.sort_values("trade_date").tail(n + 5)
    closes = g["close"].tolist()
    if len(closes) < n + 1:
        return None
    highs = g["high"].tolist() if "high" in g else closes
    lows = g["low"].tolist() if "low" in g else closes
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i] - closes[i-1]))
        trs.append(tr)
    if len(trs) < n:
        return None
    atr = sum(trs[:n]) / n
    for t in trs[n:]:
        atr = (atr * (n - 1) + t) / n
    if closes[-1] <= 0:
        return None
    atr_pct_daily = atr / closes[-1]
    return atr_pct_daily * math.sqrt(252)


# ───────────────────────── Sizing ──────────────────────────────────────────

def compute_target_weights(signal_scores: dict, daily_panel: pd.DataFrame,
                            as_of: date | str, sector_mapping: dict[str, str],
                            config: dict | None = None) -> dict[str, float]:
    """Top-N by composite. Per-position vol-targeted sizing with constraints."""
    cfg = dict(DEFAULT_CONFIG); cfg.update(config or {})
    as_of_str = (as_of.strftime("%Y%m%d") if hasattr(as_of, "strftime")
                 else str(as_of).replace("-", "")[:8])

    # Rank scored stocks
    scored = [(tk, s.get("composite")) for tk, s in signal_scores.items()
              if s and s.get("composite") is not None]
    if not scored:
        return {}
    scored.sort(key=lambda kv: -kv[1])
    top_n = scored[:cfg["top_n_picks"] * 2]   # generate 2x candidates for sector culling

    # Compute ATR vol for sizing
    sliced = daily_panel[daily_panel["trade_date"] <= as_of_str]
    raw_weights = {}
    for tk, score in top_n:
        grp = sliced[sliced["ts_code"] == tk]
        if grp.empty:
            continue
        atr_vol = _atr_vol_ann(grp)
        if atr_vol is None or atr_vol <= 0:
            target = cfg["max_single_name_weight"] * 0.5  # fallback half-size
        else:
            # vol-target: per-position vol = 2% portfolio target / stock_atr_vol
            target = min(cfg["max_single_name_weight"],
                         cfg["vol_per_position"] / atr_vol)
        raw_weights[tk] = target

    # Apply sector cap
    sector_totals: dict[str, float] = {}
    weights: dict[str, float] = {}
    selected = 0
    for tk, _ in scored:
        if tk not in raw_weights:
            continue
        if selected >= cfg["top_n_picks"]:
            break
        sector = sector_mapping.get(tk, "_unknown")
        proposed = raw_weights[tk]
        cur_sector = sector_totals.get(sector, 0.0)
        if cur_sector + proposed > cfg["max_sector_weight"]:
            # Trim to sector cap
            proposed = max(0.0, cfg["max_sector_weight"] - cur_sector)
            if proposed <= 0.005:    # too small to bother
                continue
        weights[tk] = min(proposed, cfg["safety_max_single_name"])
        sector_totals[sector] = cur_sector + weights[tk]
        selected += 1

    # Renormalize if total > max_gross
    total = sum(weights.values())
    if total > cfg["max_gross"]:
        scale = cfg["max_gross"] / total
        weights = {tk: w * scale for tk, w in weights.items()}
    return weights


# ───────────────────────── Exits ───────────────────────────────────────────

def evaluate_exits(positions: dict, daily_panel: pd.DataFrame,
                   as_of: date | str, current_signals: dict,
                   top_k_sectors: list[str] | None = None,
                   sector_mapping: dict[str, str] | None = None,
                   config: dict | None = None) -> dict[str, str]:
    """Return {ts_code: action} where action in:
       'hold' | 'sell_hard_stop' | 'sell_trailing' | 'take_profit_half' |
       'sell_time_stop' | 'sell_sector_drop' | 'sell_composite_decay'
    positions = {ts_code: {entry_date, entry_price, peak_price, entry_composite,
                            days_held, current_size, entry_sector}}
    """
    cfg = dict(DEFAULT_CONFIG); cfg.update(config or {})
    as_of_str = (as_of.strftime("%Y%m%d") if hasattr(as_of, "strftime")
                 else str(as_of).replace("-", "")[:8])
    out = {}
    sliced = daily_panel[daily_panel["trade_date"] <= as_of_str]
    for tk, pos in positions.items():
        grp = sliced[sliced["ts_code"] == tk].sort_values("trade_date")
        if grp.empty:
            out[tk] = "hold"
            continue
        latest_close = grp["close"].iloc[-1]
        entry_price = pos.get("entry_price", latest_close)
        peak_price = max(pos.get("peak_price", entry_price), latest_close)
        mtm_pct = (latest_close - entry_price) / entry_price if entry_price > 0 else 0
        trailing_pct = (latest_close - peak_price) / peak_price if peak_price > 0 else 0

        # 1. Hard stop
        if mtm_pct <= cfg["hard_stop_pct"]:
            out[tk] = "sell_hard_stop"; continue
        # 2. Trailing
        if trailing_pct <= cfg["trailing_stop_pct"]:
            out[tk] = "sell_trailing"; continue
        # 3. Take profit (half)
        if mtm_pct >= cfg["take_profit_pct"] and not pos.get("_tp_taken", False):
            out[tk] = "take_profit_half"; continue
        # 4. Time stop
        if pos.get("days_held", 0) >= cfg["time_stop_days"]:
            out[tk] = "sell_time_stop"; continue
        # 5. Sector dropped out of top-k
        if top_k_sectors and sector_mapping:
            cur_sec = sector_mapping.get(tk, pos.get("entry_sector", "_unknown"))
            if cur_sec not in top_k_sectors:
                out[tk] = "sell_sector_drop"; continue
        # 6. Composite decay
        if current_signals:
            cur_comp = (current_signals.get(tk, {}) or {}).get("composite")
            entry_comp = pos.get("entry_composite")
            if cur_comp is not None and entry_comp is not None:
                if entry_comp - cur_comp >= cfg["composite_decay"]:
                    out[tk] = "sell_composite_decay"; continue
        out[tk] = "hold"
    return out


# ───────────────────────── Circuit breakers ────────────────────────────────

def check_portfolio_breakers(portfolio_state: dict, market_state: dict,
                              config: dict | None = None) -> dict:
    """Return {actions: [...], reason: str, gross_cap: float | None}."""
    cfg = dict(DEFAULT_CONFIG); cfg.update(config or {})
    actions = []
    reasons = []
    gross_cap = cfg["max_gross"]
    dd = portfolio_state.get("drawdown_pct", 0.0)
    if dd <= cfg["drawdown_to_cash"]:
        actions.append("flat_all")
        gross_cap = 0.0
        reasons.append(f"drawdown {dd:.1%} ≤ {cfg['drawdown_to_cash']:.0%} TO_CASH")
    elif dd <= cfg["drawdown_scale_down"]:
        actions.append("scale_down")
        gross_cap = min(gross_cap, 0.60)
        actions.append("block_new")
        reasons.append(f"drawdown {dd:.1%} ≤ {cfg['drawdown_scale_down']:.0%} scale-down")
    vol_60d = market_state.get("realized_vol_60d", 0.0)
    if vol_60d > cfg["high_vol_regime_threshold"]:
        actions.append("scale_down")
        gross_cap = min(gross_cap, 0.50)
        reasons.append(f"realized vol {vol_60d:.1%} > {cfg['high_vol_regime_threshold']:.0%} regime")
    return {"actions": actions, "reason": "; ".join(reasons) if reasons else "no breaker",
            "gross_cap": gross_cap}


# ───────────────────────── Self-test ───────────────────────────────────────

def _selftest() -> int:
    failures = []

    # Synthetic 8 stocks across 2 sectors
    rows = []
    base = pd.Timestamp("2024-01-01")
    sector_mapping = {}
    for sec, tickers in [("Tech", ["T1", "T2", "T3", "T4", "T5"]),
                         ("Fin", ["F1", "F2", "F3"])]:
        for tk in tickers:
            sector_mapping[f"{tk}.SZ"] = sec
            for d in range(40):
                px = 10 + d * 0.05 + (0.5 if tk == "T1" else 0)
                rows.append({"ts_code": f"{tk}.SZ", "trade_date": (base + pd.Timedelta(days=d)).strftime("%Y%m%d"),
                             "open": px, "high": px*1.02, "low": px*0.98, "close": px, "vol": 1e6})
    panel = pd.DataFrame(rows)
    signals = {f"T{i}.SZ": {"composite": 100 - i*5} for i in range(1, 6)}
    signals.update({f"F{i}.SZ": {"composite": 70 - i*2} for i in range(1, 4)})

    weights = compute_target_weights(signals, panel, "20240208", sector_mapping)
    if not weights:
        failures.append("compute_target_weights returned empty")
    else:
        total = sum(weights.values())
        if total > 0.951:
            failures.append(f"total gross > max: {total}")
        tech_total = sum(w for tk, w in weights.items() if sector_mapping[tk] == "Tech")
        if tech_total > 0.301:
            failures.append(f"Tech sector > max 30%: {tech_total}")
        for tk, w in weights.items():
            if w > 0.121:
                failures.append(f"{tk} single-name > 12% cap: {w}")

    # Exits
    positions = {
        "STOP.SZ": {"entry_price": 100, "peak_price": 100, "days_held": 2, "entry_composite": 80,
                    "entry_sector": "Tech"},
        "TRAIL.SZ": {"entry_price": 100, "peak_price": 115, "days_held": 3, "entry_composite": 70,
                     "entry_sector": "Tech"},
        "OK.SZ": {"entry_price": 100, "peak_price": 102, "days_held": 1, "entry_composite": 60,
                  "entry_sector": "Tech"},
        "TP.SZ": {"entry_price": 100, "peak_price": 111, "days_held": 4, "entry_composite": 75,
                  "entry_sector": "Tech"},
        "TIME.SZ": {"entry_price": 100, "peak_price": 102, "days_held": 8, "entry_composite": 65,
                    "entry_sector": "Tech"},
    }
    exit_panel_rows = [
        ("STOP.SZ", 91), ("TRAIL.SZ", 108), ("OK.SZ", 101),
        ("TP.SZ", 111), ("TIME.SZ", 101),
    ]
    panel2 = pd.DataFrame([{"ts_code": tk, "trade_date": "20240210",
                             "open": px, "high": px*1.01, "low": px*0.99,
                             "close": px, "vol": 1e6} for tk, px in exit_panel_rows])
    exits = evaluate_exits(positions, panel2, "20240210",
                           current_signals={tk: {"composite": 60} for tk, _ in exit_panel_rows},
                           top_k_sectors=["Tech"], sector_mapping={tk: "Tech" for tk, _ in exit_panel_rows})
    expected = {"STOP.SZ": "sell_hard_stop", "TRAIL.SZ": "sell_trailing",
                "OK.SZ": "hold", "TP.SZ": "take_profit_half",
                "TIME.SZ": "sell_time_stop"}
    for tk, want in expected.items():
        if exits.get(tk) != want:
            failures.append(f"exit {tk}: want {want}, got {exits.get(tk)}")

    # Circuit breakers
    br = check_portfolio_breakers({"drawdown_pct": -0.18}, {})
    if "scale_down" not in br["actions"] or br["gross_cap"] > 0.61:
        failures.append(f"DD -18% breaker wrong: {br}")
    br2 = check_portfolio_breakers({"drawdown_pct": -0.28}, {})
    if "flat_all" not in br2["actions"]:
        failures.append(f"DD -28% should flat: {br2}")

    if failures:
        print("SELFTEST FAILED swing_risk_manager:")
        for f in failures: print(" -", f)
        return 1
    print("SELFTEST PASSED swing_risk_manager")
    print(f"- sizing: {len(weights)} positions, total={sum(weights.values()):.3f}, tech_sec={tech_total:.3f}")
    print(f"- exits: all 5 expected actions matched")
    print(f"- breakers: DD-15%→scale, DD-25%→flat")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Swing risk manager.")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    print("swing_risk_manager: import compute_target_weights / evaluate_exits / check_portfolio_breakers",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
