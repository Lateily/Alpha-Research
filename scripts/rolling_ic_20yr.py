#!/usr/bin/env python3
"""rolling_ic_20yr.py — 20-year rolling IC for 6 swing factors.

GOAL (Junyan 2026-05-28 review):
  Mini1yr (2025-05-26 → 2026-05-25) per-factor IC says 4 of 6 factors are
  significantly ANTI-PREDICTIVE (volume_spike t_5d=-6.2, momentum_5d t_5d=-4.2,
  macd_cross |t|>2 all horizons NEG, limit_up_followup 5-10d NEG). But 10yr
  alpha is stable +0.076 across iters → maybe long-run is different. We need to
  decide: is the mini1yr anti-edge a *regime* phenomenon or a *long-run truth*?

WHAT THIS DOES:
  20yr (2006-01-04 → 2026-05-25) daily cross-sectional Spearman IC for each
  (factor, horizon) ∈ {breakout_20d, momentum_5d, limit_up_followup,
  volume_spike, macd_cross, rsi_in_band} × {1d, 3d, 5d, 10d}.

  Per-date pipeline:
    1. liquid_today = top-500 by 20d ADV at T (already PIT-clean)
    2. factor values: fast_signals_one(idx, tk, T)['factors']  (same as engine)
    3. forward return: close[T+h] / close[T] - 1
    4. tie-aware Spearman (fractional ranking) over common tickers
    5. decile long-short spread: mean(fwd_ret | top-10%) - mean(fwd_ret | bot-10%)
    6. sector-neutral IC: demean factor within SW L1 sector, then Spearman

OUTPUTS:
  - public/data/rolling_ic_20yr.json
  - prints a markdown summary table at the end (long-run vs mini1yr)

NOTES:
  - All factor compute is reused from run_swing_backtest_fast.fast_signals_one
    so factors are EXACTLY the same definition as the trading engine — apples
    to apples with iter16_factor_ic.json.
  - tie-aware Spearman uses fractional_rank (ties get average rank) — needed
    because volume_spike / breakout_20d / limit_up_followup / macd_cross /
    rsi_in_band are 0/1 binary factors with MANY ties. Naive np.argsort
    breaks ties arbitrarily and biases the correlation toward 0.

PIT discipline:
  - PanelIndex.history uses np.searchsorted(side='right') for strict ≤ as_of
  - forward return uses idx.row_at(T_future) — only present in panel if real
  - sector demean uses sector_map (static metadata; no future leak)

NOT COMMITTED. Junyan reviews before merge.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from panel_index import PanelIndex
from liquid_universe import compute_liquid_universe
from run_swing_backtest_fast import fast_signals_one
from sector_scorer import load_sector_map

WINDOW_START = "20060104"
WINDOW_END = "20260525"
LIQUID_TOP_N = 500
FACTOR_NAMES = ["breakout_20d", "momentum_5d", "limit_up_followup",
                 "volume_spike", "macd_cross", "rsi_in_band"]
HORIZONS = (1, 3, 5, 10)
MIN_COMMON_TICKERS = 30   # min sample size per (date, factor, horizon) for IC
ROLLING_WINDOW_DAYS = 252   # ≈ 1 trade year, for the rolling 252d mean IC path

# Decile cuts: top 10% vs bottom 10%
DECILE_TOP_PCT = 0.10
DECILE_BOT_PCT = 0.10

# Min sector size for sector-neutralization (else skip sector demean for that
# group; if member count < this, demean within sector is too noisy).
MIN_SECTOR_MEMBERS = 5


# ─────────────────────── Tie-aware fractional ranking ────────────────────

def fractional_rank(x: np.ndarray) -> np.ndarray:
    """Tie-aware ranking — ties get the average rank (1-indexed).

    Equivalent to scipy.stats.rankdata(x, method='average') but pure-numpy.

    Example: x=[1, 2, 2, 3] → ranks=[1.0, 2.5, 2.5, 4.0]
             x=[5, 1, 1, 1] → ranks=[4.0, 2.0, 2.0, 2.0]
    """
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n == 0:
        return np.empty(0, dtype=float)
    order = np.argsort(x, kind="mergesort")   # stable
    ranks = np.empty(n, dtype=float)
    sorted_x = x[order]
    i = 0
    while i < n:
        j = i + 1
        while j < n and sorted_x[j] == sorted_x[i]:
            j += 1
        # positions order[i..j-1] all tied → average rank = ((i+1) + j) / 2
        avg = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[order[k]] = avg
        i = j
    return ranks


def tie_aware_spearman(xs: np.ndarray, ys: np.ndarray) -> float:
    """Spearman rank correlation with tie-aware fractional ranking.

    Returns NaN if n<3, or either column has zero variance after ranking.
    """
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    n = len(xs)
    if n < 3:
        return float("nan")
    rx = fractional_rank(xs)
    ry = fractional_rank(ys)
    mx = rx.mean()
    my = ry.mean()
    cov = np.mean((rx - mx) * (ry - my))
    sx = rx.std()
    sy = ry.std()
    if sx == 0 or sy == 0:
        return float("nan")
    return float(cov / (sx * sy))


# ─────────────────────── Decile long-short spread ─────────────────────────

def decile_long_short(factor_vals: np.ndarray,
                       fwd_rets: np.ndarray,
                       top_pct: float = DECILE_TOP_PCT,
                       bot_pct: float = DECILE_BOT_PCT) -> float:
    """top decile mean(fwd) - bottom decile mean(fwd). NaN if insufficient."""
    if len(factor_vals) < 20:
        return float("nan")
    # Need to handle ties in factor_vals (e.g., binary 0/1 factors).
    # Use np.quantile cuts; if many ties at the cut, we just pick what falls.
    hi_cut = float(np.quantile(factor_vals, 1.0 - top_pct))
    lo_cut = float(np.quantile(factor_vals, bot_pct))
    if hi_cut <= lo_cut:
        # not enough spread (typical: factor is 0/1 and >90% are 0)
        # fall back to "factor==1 vs factor==0" if it's binary
        unique = np.unique(factor_vals)
        if len(unique) == 2:
            top_mask = factor_vals == unique[1]
            bot_mask = factor_vals == unique[0]
        else:
            return float("nan")
    else:
        top_mask = factor_vals >= hi_cut
        bot_mask = factor_vals <= lo_cut
    top_n = int(top_mask.sum())
    bot_n = int(bot_mask.sum())
    if top_n < 3 or bot_n < 3:
        return float("nan")
    return float(fwd_rets[top_mask].mean() - fwd_rets[bot_mask].mean())


# ─────────────────────── Sector-neutral demean ────────────────────────────

def sector_demeaned(factor_vals: dict[str, float],
                     sector_map: dict[str, str]) -> dict[str, float]:
    """For each ticker in factor_vals, subtract mean of factor across its
    SW L1 sector. Sectors with < MIN_SECTOR_MEMBERS members fall back to
    global mean (no demean). Result preserves dict shape."""
    # Group by sector
    by_sector: dict[str, list[tuple[str, float]]] = {}
    no_sector = []
    for tk, v in factor_vals.items():
        s = sector_map.get(tk)
        if s is None:
            no_sector.append((tk, v))
        else:
            by_sector.setdefault(s, []).append((tk, v))
    out = {}
    # Global mean as fallback
    all_vals = [v for vs in by_sector.values() for _, v in vs]
    all_vals.extend(v for _, v in no_sector)
    if not all_vals:
        return {}
    global_mean = float(np.mean(all_vals))
    for sec, items in by_sector.items():
        if len(items) >= MIN_SECTOR_MEMBERS:
            sec_mean = float(np.mean([v for _, v in items]))
        else:
            sec_mean = global_mean
        for tk, v in items:
            out[tk] = v - sec_mean
    # Tickers without sector → use global mean
    for tk, v in no_sector:
        out[tk] = v - global_mean
    return out


# ─────────────────────── Self-test ────────────────────────────────────────

def _selftest() -> int:
    failures = []

    # 1. fractional_rank ties
    r = fractional_rank(np.array([1, 2, 2, 3]))
    if not np.allclose(r, [1.0, 2.5, 2.5, 4.0]):
        failures.append(f"fractional_rank([1,2,2,3]) = {r.tolist()}, expected [1, 2.5, 2.5, 4]")
    r = fractional_rank(np.array([5, 1, 1, 1]))
    if not np.allclose(r, [4.0, 2.0, 2.0, 2.0]):
        failures.append(f"fractional_rank([5,1,1,1]) = {r.tolist()}, expected [4, 2, 2, 2]")
    r = fractional_rank(np.array([7.0]))
    if not np.allclose(r, [1.0]):
        failures.append(f"fractional_rank single = {r.tolist()}")
    r = fractional_rank(np.array([3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]))
    # sorted: [1,1,2,3,4,5,6,9] → ranks at sorted pos: 1.5, 1.5, 3, 4, 5, 6, 7, 8
    # back to original: [4, 1.5, 5, 1.5, 6, 8, 3, 7]
    expected = [4.0, 1.5, 5.0, 1.5, 6.0, 8.0, 3.0, 7.0]
    if not np.allclose(r, expected):
        failures.append(f"fractional_rank mixed = {r.tolist()}, expected {expected}")

    # 2. tie_aware_spearman known
    # Perfect monotonic
    rho = tie_aware_spearman(np.array([1, 2, 3, 4, 5]),
                              np.array([10, 20, 30, 40, 50]))
    if not (rho > 0.999):
        failures.append(f"perfect monotonic spearman = {rho}, expected ≈ 1")
    # Perfect anti
    rho = tie_aware_spearman(np.array([1, 2, 3, 4, 5]),
                              np.array([50, 40, 30, 20, 10]))
    if not (rho < -0.999):
        failures.append(f"perfect anti spearman = {rho}, expected ≈ -1")
    # All ties on one side → zero variance → NaN
    rho = tie_aware_spearman(np.array([1, 1, 1, 1, 1]), np.array([1, 2, 3, 4, 5]))
    if not math.isnan(rho):
        failures.append(f"zero-var spearman = {rho}, expected NaN")
    # Binary factor (0/1) with positive edge: 1s have higher fwd ret on avg
    np.random.seed(42)
    binary = np.array([0, 0, 0, 0, 1, 1, 1, 1, 0, 1])
    rets = np.array([0.0, -0.01, 0.005, 0.0, 0.02, 0.03, 0.04, 0.025, 0.0, 0.05])
    rho_bin = tie_aware_spearman(binary, rets)
    if rho_bin <= 0:
        failures.append(f"binary positive-edge spearman = {rho_bin}, expected > 0")

    # 3. decile_long_short on monotonic signal
    factor = np.arange(100, dtype=float)
    fwd = np.arange(100, dtype=float) * 0.001   # positive edge
    spread = decile_long_short(factor, fwd)
    # top 10 (vals 90..99) - bot 10 (vals 0..9): (94.5 - 4.5) × 0.001 = 0.090
    if not (0.08 < spread < 0.10):
        failures.append(f"decile_long_short monotonic = {spread}, expected ≈ 0.09")
    # Binary factor fallback (need ≥ 20 elements)
    factor_bin = np.concatenate([np.zeros(90), np.ones(10)])
    fwd_bin = np.concatenate([np.zeros(90), np.ones(10)])
    spread_bin = decile_long_short(factor_bin, fwd_bin)
    if not (abs(spread_bin - 1.0) < 1e-9):
        failures.append(f"decile_long_short binary = {spread_bin}, expected 1.0")
    # Edge case: factor binary with very few 1s — fallback to unique-value path
    factor_bin2 = np.concatenate([np.zeros(95), np.ones(5)])
    fwd_bin2 = np.concatenate([np.zeros(95), np.ones(5)])
    spread_bin2 = decile_long_short(factor_bin2, fwd_bin2)
    if not (abs(spread_bin2 - 1.0) < 1e-9):
        failures.append(f"decile_long_short binary-95/5 = {spread_bin2}, expected 1.0")

    # 4. sector_demeaned reduces within-sector mean to 0
    factor_vals = {"A": 1.0, "B": 3.0, "C": 5.0,    # sector S1 mean=3
                    "D": 10.0, "E": 12.0, "F": 14.0,   # sector S2 mean=12
                    "G": 100.0, "H": 102.0, "I": 104.0, "J": 106.0, "K": 108.0}
    sector_map = {"A": "S1", "B": "S1", "C": "S1", "D": "S1", "E": "S1",  # 5 members
                   "F": "S2", "G": "S2", "H": "S2", "I": "S2", "J": "S2", "K": "S2"}
    # S1 = [A=1, B=3, C=5, D=10, E=12] mean=6.2 → demean
    # S2 = [F=14, G=100, H=102, I=104, J=106, K=108] mean=89 → demean
    demeaned = sector_demeaned(factor_vals, sector_map)
    s1_vals = [demeaned["A"], demeaned["B"], demeaned["C"], demeaned["D"], demeaned["E"]]
    if not (abs(np.mean(s1_vals)) < 1e-9):
        failures.append(f"sector S1 demean residual mean = {np.mean(s1_vals)}, expected 0")
    s2_vals = [demeaned["F"], demeaned["G"], demeaned["H"], demeaned["I"], demeaned["J"], demeaned["K"]]
    if not (abs(np.mean(s2_vals)) < 1e-9):
        failures.append(f"sector S2 demean residual mean = {np.mean(s2_vals)}, expected 0")

    if failures:
        print("SELFTEST FAILED rolling_ic_20yr:")
        for f in failures:
            print(" -", f)
        return 1
    print("SELFTEST PASSED rolling_ic_20yr")
    print("- fractional_rank ties → average rank ✓")
    print("- tie_aware_spearman: monotonic / anti / NaN / binary edge ✓")
    print("- decile_long_short: monotonic ≈ 0.09 / binary 1.0 ✓")
    print("- sector_demeaned: within-sector residual mean = 0 ✓")
    return 0


# ─────────────────────── Main computation ────────────────────────────────

def _git_head_sha() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown"


def _data_hash(panel_path: Path, n_rows: int) -> str:
    """Cheap hash of panel: file mtime + row count. Stable across runs as long
    as the underlying panel file hasn't been re-downloaded."""
    mtime = int(panel_path.stat().st_mtime)
    s = f"{panel_path.name}:{mtime}:{n_rows}"
    return hashlib.md5(s.encode()).hexdigest()[:16]


def compute_rolling_ic(panel: pd.DataFrame,
                        sector_map: dict[str, str],
                        window_start: str,
                        window_end: str,
                        liquid_top_n: int = LIQUID_TOP_N,
                        verbose: bool = True) -> dict:
    """Returns dict matching the output JSON schema."""
    if verbose:
        print("[1/4] computing liquid universe...", flush=True)
    t0 = time.time()
    liquid_uni = compute_liquid_universe(panel, top_n=liquid_top_n)
    if verbose:
        print(f"    {len(liquid_uni)} dates ({time.time()-t0:.1f}s)", flush=True)

    all_liquid = set()
    for v in liquid_uni.values():
        all_liquid.update(v)
    sub = panel[panel["ts_code"].isin(all_liquid)]
    if verbose:
        print(f"[2/4] reduced panel: {len(sub):,} rows / {sub['ts_code'].nunique()} tickers — building PanelIndex...",
              flush=True)
    t1 = time.time()
    idx = PanelIndex(sub)
    if verbose:
        print(f"    PanelIndex built ({time.time()-t1:.1f}s)", flush=True)

    # Trade dates in window (intersection of panel dates and liquid_uni keys)
    all_dates = idx.all_trade_dates()
    trade_dates = [d for d in all_dates
                    if window_start <= d <= window_end and d in liquid_uni]
    if verbose:
        print(f"[3/4] {len(trade_dates)} trade dates in window "
              f"({trade_dates[0]} → {trade_dates[-1]})", flush=True)
    max_h = max(HORIZONS)

    # Storage: per-date IC by (factor, horizon, kind)
    # kinds: 'raw' (vanilla tie-aware Spearman),
    #         'sect' (sector-neutral Spearman: demean factor within sector),
    #         'spread' (top-decile minus bottom-decile mean fwd_ret).
    daily_records = {
        f: {h: {"raw": [], "sect": [], "spread": []} for h in HORIZONS}
        for f in FACTOR_NAMES
    }
    # Date stamps so the rolling 252d series is well-defined.
    daily_record_dates = {
        f: {h: {"raw": [], "sect": [], "spread": []} for h in HORIZONS}
        for f in FACTOR_NAMES
    }

    if verbose:
        print(f"[4/4] running daily IC scan (~{len(trade_dates)} dates)...", flush=True)
    t_scan = time.time()

    skip_no_signal = 0
    skip_insufficient = 0

    for T_idx, T in enumerate(trade_dates):
        if T_idx + max_h >= len(trade_dates):
            break
        liquid_today = liquid_uni.get(T, [])
        if not liquid_today:
            continue

        # Compute factor values for all liquid_today tickers
        factor_values: dict[str, dict[str, float]] = {f: {} for f in FACTOR_NAMES}
        close_today: dict[str, float] = {}
        for tk in liquid_today:
            row = idx.row_at(tk, T)
            if row is None or row["close"] <= 0:
                continue
            close_today[tk] = row["close"]
            sig = fast_signals_one(idx, tk, T)
            if sig is None:
                skip_no_signal += 1
                continue
            for f in FACTOR_NAMES:
                v = sig["factors"].get(f)
                if v is None:
                    continue
                # filter NaN
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    continue
                factor_values[f][tk] = float(v)

        # For each horizon, compute forward returns + 3 metrics per factor
        for h in HORIZONS:
            T_future = trade_dates[T_idx + h]
            fwd_rets: dict[str, float] = {}
            for tk, c0 in close_today.items():
                row_future = idx.row_at(tk, T_future)
                if row_future is None:
                    continue
                cf = row_future.get("close")
                if cf is None or c0 <= 0:
                    continue
                r = cf / c0 - 1.0
                if math.isnan(r) or math.isinf(r):
                    continue
                fwd_rets[tk] = r

            for f in FACTOR_NAMES:
                common = list(set(factor_values[f].keys()) & set(fwd_rets.keys()))
                if len(common) < MIN_COMMON_TICKERS:
                    skip_insufficient += 1
                    continue
                xs = np.array([factor_values[f][tk] for tk in common], dtype=float)
                ys = np.array([fwd_rets[tk] for tk in common], dtype=float)
                if np.unique(xs).size < 2 or np.unique(ys).size < 2:
                    continue

                # 1. raw tie-aware Spearman
                rho = tie_aware_spearman(xs, ys)
                if not math.isnan(rho):
                    daily_records[f][h]["raw"].append(rho)
                    daily_record_dates[f][h]["raw"].append(T)

                # 2. decile long-short spread
                spread = decile_long_short(xs, ys)
                if not math.isnan(spread):
                    daily_records[f][h]["spread"].append(spread)
                    daily_record_dates[f][h]["spread"].append(T)

                # 3. sector-neutral IC
                fv_dict = {tk: factor_values[f][tk] for tk in common}
                fv_demeaned = sector_demeaned(fv_dict, sector_map)
                if fv_demeaned:
                    xs_n = np.array([fv_demeaned[tk] for tk in common], dtype=float)
                    if np.unique(xs_n).size >= 2:
                        rho_sect = tie_aware_spearman(xs_n, ys)
                        if not math.isnan(rho_sect):
                            daily_records[f][h]["sect"].append(rho_sect)
                            daily_record_dates[f][h]["sect"].append(T)

        if verbose and T_idx % 250 == 0:
            elapsed = time.time() - t_scan
            done = T_idx + 1
            rate = done / max(1e-9, elapsed)
            eta = (len(trade_dates) - done) / max(1e-9, rate)
            print(f"    {done}/{len(trade_dates)} ({100*done/len(trade_dates):.1f}%) "
                  f"date={T} elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)

    if verbose:
        print(f"    scan done in {time.time()-t_scan:.1f}s "
              f"(skips: no_signal={skip_no_signal}, insufficient={skip_insufficient})",
              flush=True)

    # ────────────── Aggregate per (factor, horizon) ──────────────────────
    summary: dict[str, dict] = {}
    for f in FACTOR_NAMES:
        for h in HORIZONS:
            key = f"{f}.{h}d"
            raw = np.array(daily_records[f][h]["raw"], dtype=float)
            sect = np.array(daily_records[f][h]["sect"], dtype=float)
            spread = np.array(daily_records[f][h]["spread"], dtype=float)
            raw_dates = daily_record_dates[f][h]["raw"]

            entry = {
                "factor": f, "horizon_days": h,
                "n_dates_raw": int(len(raw)),
                "n_dates_sect": int(len(sect)),
                "n_dates_spread": int(len(spread)),
            }

            if len(raw) >= 5:
                mu = float(np.mean(raw))
                sd = float(np.std(raw, ddof=1))
                n = len(raw)
                se = sd / math.sqrt(n) if n > 1 else float("nan")
                t = mu / se if (se and se > 0) else float("nan")
                entry["long_run_mean_ic"] = mu
                entry["long_run_std_ic"] = sd
                entry["long_run_t_stat"] = t
                entry["long_run_ic_ir"] = float(mu / sd) if sd > 0 else float("nan")

                # Rolling 252d mean IC path
                rolling = []
                for i in range(len(raw)):
                    lo = max(0, i + 1 - ROLLING_WINDOW_DAYS)
                    rolling.append(float(np.mean(raw[lo:i + 1])))
                entry["rolling_252d_ic_path"] = [round(x, 6) for x in rolling]
                entry["rolling_252d_ic_dates"] = raw_dates

                # Sign changes in rolling series
                sign_changes = 0
                prev_sign = None
                for x in rolling:
                    if x > 0:
                        cur_sign = 1
                    elif x < 0:
                        cur_sign = -1
                    else:
                        cur_sign = 0
                    if prev_sign is not None and cur_sign != 0 and prev_sign != 0 \
                       and cur_sign != prev_sign:
                        sign_changes += 1
                    if cur_sign != 0:
                        prev_sign = cur_sign
                entry["ic_sign_changes_count"] = sign_changes

                # Quarterly bucketed mean
                quarterly = _quarterly_aggregate(raw_dates, raw)
                entry["quarterly_ic"] = [
                    {"quarter": q, "mean_ic": round(v, 6), "n_dates": n}
                    for (q, v, n) in quarterly
                ]
            else:
                entry["long_run_mean_ic"] = None
                entry["long_run_t_stat"] = None
                entry["rolling_252d_ic_path"] = []
                entry["rolling_252d_ic_dates"] = []
                entry["ic_sign_changes_count"] = 0
                entry["quarterly_ic"] = []

            if len(sect) >= 5:
                mu_s = float(np.mean(sect))
                sd_s = float(np.std(sect, ddof=1))
                n_s = len(sect)
                se_s = sd_s / math.sqrt(n_s) if n_s > 1 else float("nan")
                t_s = mu_s / se_s if (se_s and se_s > 0) else float("nan")
                entry["sector_neutral_ic_mean"] = mu_s
                entry["sector_neutral_t_stat"] = t_s
            else:
                entry["sector_neutral_ic_mean"] = None
                entry["sector_neutral_t_stat"] = None

            if len(spread) >= 5:
                mu_d = float(np.mean(spread))
                sd_d = float(np.std(spread, ddof=1))
                n_d = len(spread)
                se_d = sd_d / math.sqrt(n_d) if n_d > 1 else float("nan")
                t_d = mu_d / se_d if (se_d and se_d > 0) else float("nan")
                entry["ic_decile_spread_mean"] = mu_d
                entry["ic_decile_spread_t_stat"] = t_d
            else:
                entry["ic_decile_spread_mean"] = None
                entry["ic_decile_spread_t_stat"] = None

            summary[key] = entry

    return {
        "window": [window_start, window_end],
        "n_trade_dates": len(trade_dates),
        "factors": FACTOR_NAMES,
        "horizons": list(HORIZONS),
        "liquid_top_n": liquid_top_n,
        "summary": summary,
    }


def _quarterly_aggregate(dates: list[str], values: np.ndarray) -> list[tuple[str, float, int]]:
    """Bucket daily IC values by calendar quarter (YYYYQn) and return mean."""
    buckets: dict[str, list[float]] = {}
    order: list[str] = []
    for d, v in zip(dates, values):
        # YYYYMMDD → YYYYQn
        try:
            year = int(d[:4])
            month = int(d[4:6])
        except Exception:
            continue
        q = (month - 1) // 3 + 1
        key = f"{year}Q{q}"
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(float(v))
    return [(k, float(np.mean(buckets[k])), len(buckets[k])) for k in order]


# ─────────────────────── Mini1yr comparison + table ──────────────────────

def load_mini1yr_ic() -> dict:
    p = REPO_ROOT / "public" / "data" / "iter16_factor_ic.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def print_markdown_table(result: dict) -> str:
    mini = load_mini1yr_ic()
    mini_ic = (mini or {}).get("ic", {})
    lines = []
    lines.append("")
    lines.append(f"# Rolling IC 20yr — long-run summary")
    lines.append("")
    lines.append(f"Window: **{result['window'][0]} → {result['window'][1]}** "
                  f"({result['n_trade_dates']} trade dates, liquid top-{result['liquid_top_n']})")
    lines.append("")
    lines.append("## Long-run mean IC vs mini1yr (per factor × horizon)")
    lines.append("")
    lines.append("| Factor | Horizon | Long IC | Long t | Mini1yr IC | Mini1yr t | Sign match? | Spread | Sect-neut IC | Sign chg |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")

    for f in FACTOR_NAMES:
        for h in HORIZONS:
            key = f"{f}.{h}d"
            ent = result["summary"].get(key, {})
            long_ic = ent.get("long_run_mean_ic")
            long_t = ent.get("long_run_t_stat")
            mini_d = (mini_ic.get(f) or {}).get(str(h))
            mini_ic_v = (mini_d or {}).get("mean_ic")
            mini_t = (mini_d or {}).get("t_stat")

            def fmt(x, fmt_str=".4f", default="n/a"):
                if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
                    return default
                return format(x, fmt_str)

            # sign match: both negative, both positive, or one is 0
            sign_match = "n/a"
            if long_ic is not None and mini_ic_v is not None:
                if long_ic == 0 or mini_ic_v == 0:
                    sign_match = "0?"
                elif (long_ic > 0) == (mini_ic_v > 0):
                    sign_match = "SAME"
                else:
                    sign_match = "FLIP"

            spread = ent.get("ic_decile_spread_mean")
            sect = ent.get("sector_neutral_ic_mean")
            sign_chg = ent.get("ic_sign_changes_count", 0)

            lines.append(
                f"| {f} | {h}d | {fmt(long_ic)} | {fmt(long_t, '.2f')} | "
                f"{fmt(mini_ic_v)} | {fmt(mini_t, '.2f')} | {sign_match} | "
                f"{fmt(spread)} | {fmt(sect)} | {sign_chg} |"
            )
    lines.append("")
    lines.append("**Legend.** Long IC = 20yr mean of daily Spearman IC (tie-aware). Mini1yr from `iter16_factor_ic.json`. "
                 "Sign match SAME = same direction long-run vs mini1yr (real anti-edge if NEG/NEG, real positive edge if POS/POS); "
                 "FLIP = regime-switching (long-run is one direction, mini1yr the other). "
                 "Spread = top-decile minus bottom-decile mean forward return, daily mean across 20yr. "
                 "Sect-neut IC = Spearman using factor demeaned within SW L1 sector. "
                 "Sign chg = # of times the 252d-rolling IC mean flipped sign across 20yr "
                 "(high = regime-switching, low = stable direction).")
    return "\n".join(lines)


# ─────────────────────── Main ─────────────────────────────────────────────

def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="20yr rolling IC (tie-aware Spearman + decile spread + sector-neutral).")
    p.add_argument("--prices",
                    default=str(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet"))
    p.add_argument("--sector-map",
                    default=str(REPO_ROOT / "data_history" / "sector_mapping.json"))
    p.add_argument("--start", default=WINDOW_START)
    p.add_argument("--end", default=WINDOW_END)
    p.add_argument("--top-n", type=int, default=LIQUID_TOP_N)
    p.add_argument("--out",
                    default=str(REPO_ROOT / "public" / "data" / "rolling_ic_20yr.json"))
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--report-md",
                    default="/tmp/r1_report.md",
                    help="Where to write the markdown report (for T1 review).")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()

    verbose = not args.quiet

    if verbose:
        print(f"Loading panel from {args.prices}...", flush=True)
    panel_path = Path(args.prices)
    panel = pd.read_parquet(panel_path)
    if verbose:
        print(f"  {len(panel):,} rows × {panel['ts_code'].nunique()} tickers "
              f"({panel['trade_date'].min()} → {panel['trade_date'].max()})", flush=True)

    sector_map = load_sector_map(args.sector_map)
    if verbose:
        print(f"  sector_map: {len(sector_map)} tickers", flush=True)

    # Normalize window args to YYYYMMDD
    s = args.start.replace("-", "")[:8]
    e = args.end.replace("-", "")[:8]

    t0 = time.time()
    result = compute_rolling_ic(panel, sector_map, s, e,
                                 liquid_top_n=args.top_n, verbose=verbose)
    elapsed = time.time() - t0

    result["_meta"] = {
        "engine_version": "ic-v1",
        "data_hash": _data_hash(panel_path, len(panel)),
        "git_commit": _git_head_sha(),
        "panel_path": str(panel_path),
        "sector_map_path": args.sector_map,
        "computed_at_utc": pd.Timestamp.utcnow().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "rolling_window_days": ROLLING_WINDOW_DAYS,
        "decile_pcts": {"top": DECILE_TOP_PCT, "bot": DECILE_BOT_PCT},
        "min_common_tickers_per_date": MIN_COMMON_TICKERS,
        "min_sector_members_for_demean": MIN_SECTOR_MEMBERS,
        "factor_compute_source": "run_swing_backtest_fast.fast_signals_one (same as live engine)",
        "spearman_method": "tie-aware fractional ranking (scipy-equivalent average method)",
        "assumptions": [
            "Window start clipped to panel min trade_date (2006-01-04).",
            "Per-day pool = liquid top-N by 20d ADV (PIT-clean).",
            "Forward return uses raw close/close-1 (NOT total-return adj). "
            "For 20yr cross-sectional rank, ex-div drift is small but real.",
            "Sector mapping is the *current* SW L1 (snapshot, not as-of historical). "
            "Some tickers may have re-classified sectors — sector-neutral IC has this leak.",
            "Composite veto gates (ATR/close > 0.08 and MA50 down trend) apply via fast_signals_one. "
            "A ticker that fails the veto returns no factor values, so its sample size shrinks.",
            "30-ticker minimum per date filters out the earliest 2006 sub-population days "
            "when liquid top-N hadn't fully populated.",
        ],
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False,
                                          default=str, indent=2))
    if verbose:
        print(f"\nWrote {args.out} ({Path(args.out).stat().st_size/1024:.0f} KB)", flush=True)

    # Print + save markdown report
    md = print_markdown_table(result)
    print(md)

    # Compose the longer report with comparison summary
    report = _compose_full_report(result, elapsed)
    Path(args.report_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report_md).write_text(report)
    if verbose:
        print(f"\nWrote report {args.report_md}", flush=True)

    return 0


def _compose_full_report(result: dict, elapsed: float) -> str:
    mini = load_mini1yr_ic()
    mini_ic = (mini or {}).get("ic", {})
    summary = result["summary"]

    def fmt(x, fmt_str=".4f", default="n/a"):
        if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
            return default
        return format(x, fmt_str)

    lines = []
    lines.append("# R1: Rolling IC 20yr — long-run vs mini1yr regime check")
    lines.append("")
    lines.append(f"**Task.** Verify whether mini1yr (2025-05 → 2026-05) per-factor anti-edge "
                  f"is *regime-specific* or a *long-run truth* across 20yr.")
    lines.append("")
    lines.append("## Compute summary")
    lines.append("")
    lines.append(f"- Window: {result['window'][0]} → {result['window'][1]}")
    lines.append(f"- Trade dates: {result['n_trade_dates']:,}")
    lines.append(f"- Liquid pool/day: top-{result['liquid_top_n']} by 20d ADV (PIT-clean)")
    lines.append(f"- Strategy: full daily scan (no skip), tie-aware fractional ranking Spearman")
    lines.append(f"- Wall time: {elapsed:.0f} sec ({elapsed/60:.1f} min)")
    lines.append(f"- Engine: PanelIndex (O(log N) date slicing) + fast_signals_one (same as live engine)")
    lines.append("")
    lines.append("## Per-factor comparison (long-run 20yr vs mini1yr)")
    lines.append("")
    lines.append("| Factor.Horizon | 20yr mean IC | 20yr t | mini1yr IC | mini1yr t | Sign | Spread | Sect-neut IC | 252d sign chg |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    same_signs = []
    flipped = []
    for f in FACTOR_NAMES:
        for h in HORIZONS:
            key = f"{f}.{h}d"
            ent = summary.get(key, {})
            long_ic = ent.get("long_run_mean_ic")
            long_t = ent.get("long_run_t_stat")
            mini_d = (mini_ic.get(f) or {}).get(str(h))
            mini_ic_v = (mini_d or {}).get("mean_ic")
            mini_t = (mini_d or {}).get("t_stat")

            sign = "n/a"
            if long_ic is not None and mini_ic_v is not None and long_ic != 0 and mini_ic_v != 0:
                if (long_ic > 0) == (mini_ic_v > 0):
                    sign = "SAME"
                    same_signs.append((key, long_ic, mini_ic_v, long_t, mini_t))
                else:
                    sign = "FLIP"
                    flipped.append((key, long_ic, mini_ic_v, long_t, mini_t))

            lines.append(
                f"| {key} | {fmt(long_ic)} | {fmt(long_t, '.2f')} | "
                f"{fmt(mini_ic_v)} | {fmt(mini_t, '.2f')} | {sign} | "
                f"{fmt(ent.get('ic_decile_spread_mean'))} | "
                f"{fmt(ent.get('sector_neutral_ic_mean'))} | "
                f"{ent.get('ic_sign_changes_count', 0)} |"
            )
    lines.append("")
    lines.append("## Diagnosis")
    lines.append("")
    lines.append(f"- **SAME sign (long-run agrees with mini1yr)**: {len(same_signs)} cells")
    lines.append(f"- **FLIP (regime-switching)**: {len(flipped)} cells")
    lines.append("")

    # Focus on momentum_5d.5d and volume_spike.5d
    focus_keys = ["momentum_5d.5d", "volume_spike.5d", "macd_cross.5d",
                   "limit_up_followup.5d", "breakout_20d.5d", "rsi_in_band.5d"]
    lines.append("### Headline factors @ 5d (mini1yr's worst horizon)")
    lines.append("")
    lines.append("| Factor.Horizon | 20yr IC | 20yr t | mini1yr IC | mini1yr t | Verdict |")
    lines.append("|---|---|---|---|---|---|")
    for k in focus_keys:
        ent = summary.get(k, {})
        long_ic = ent.get("long_run_mean_ic")
        long_t = ent.get("long_run_t_stat")
        f, hpart = k.rsplit(".", 1)
        h_str = hpart.replace("d", "")
        mini_d = (mini_ic.get(f) or {}).get(h_str)
        mini_ic_v = (mini_d or {}).get("mean_ic")
        mini_t = (mini_d or {}).get("t_stat")

        verdict = "n/a"
        if long_ic is not None and mini_ic_v is not None:
            if long_ic < 0 and mini_ic_v < 0:
                if long_t is not None and long_t < -2:
                    verdict = "STRUCTURAL ANTI-EDGE (long-run NEG significant)"
                else:
                    verdict = "Long-run NEG but weak; same sign as mini1yr"
            elif long_ic > 0 and mini_ic_v < 0:
                verdict = "REGIME-SWITCH (long-run POS, mini1yr NEG)"
            elif long_ic < 0 and mini_ic_v > 0:
                verdict = "REGIME-SWITCH (long-run NEG, mini1yr POS — rare)"
            elif long_ic > 0 and mini_ic_v > 0:
                verdict = "Stable POS edge"
        lines.append(
            f"| {k} | {fmt(long_ic)} | {fmt(long_t, '.2f')} | "
            f"{fmt(mini_ic_v)} | {fmt(mini_t, '.2f')} | {verdict} |"
        )
    lines.append("")

    # Free-text decision call
    lines.append("### Decision call")
    lines.append("")
    mom_5d = summary.get("momentum_5d.5d", {})
    vol_5d = summary.get("volume_spike.5d", {})
    if mom_5d.get("long_run_mean_ic") is not None and vol_5d.get("long_run_mean_ic") is not None:
        mom = mom_5d["long_run_mean_ic"]
        vol = vol_5d["long_run_mean_ic"]
        if mom < 0 and vol < 0:
            lines.append(
                "Both **momentum_5d** and **volume_spike** at 5d horizon are NEG on the "
                "20yr long-run mean IC, agreeing with mini1yr direction. This is consistent "
                "with the hypothesis that the swing factors are *structurally anti-edge* in "
                "Chinese A-shares (mean-reversion at short horizons), not merely a 2025-26 "
                "regime artifact."
            )
        elif mom > 0 and vol > 0:
            lines.append(
                "Both **momentum_5d** and **volume_spike** at 5d horizon are POS on the "
                "20yr long-run mean IC. The mini1yr NEG is a REGIME-SWITCH — the long-run "
                "evidence supports a momentum/volume edge."
            )
        else:
            lines.append(
                "Mixed result: momentum_5d.5d=" + fmt(mom) + " vs volume_spike.5d=" + fmt(vol) +
                ". Need deeper read of the rolling 252d path before concluding."
            )
    lines.append("")

    lines.append("## Assumptions / data anomalies")
    lines.append("")
    for a in (result.get("_meta", {}).get("assumptions") or []):
        lines.append(f"- {a}")
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- JSON output: `public/data/rolling_ic_20yr.json` "
                  f"({result.get('_meta', {}).get('elapsed_seconds')}s wall time)")
    lines.append(f"- Comparison baseline: `public/data/iter16_factor_ic.json` (mini1yr)")
    lines.append(f"- Engine: `scripts/run_swing_backtest_fast.fast_signals_one` (factor compute)")
    lines.append(f"- PanelIndex: `scripts/panel_index.PanelIndex` (PIT-clean O(log N))")
    lines.append("")
    lines.append("*NOT committed. Junyan reviews before merge.*")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
