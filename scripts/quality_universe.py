#!/usr/bin/env python3
"""quality_universe.py — daily quality pre-filter (iter-16).

Per Junyan methodology: pre-filter is the bottleneck.  Liquid top-500 still
admits low-quality momentum stocks (overheated meme, junk in a hot sector).
Filter universe DOWN to "quality candidates" BEFORE sector ranking + composite
scoring.

Definition of quality (proxies; built from OHLCV panel only — no extra API):
  G1  60d cumulative return > 0           [上涨势能 — actually trending up]
  G2  close > 60d_max × 0.80              [上涨势能 — not in deep drawdown]
  G3  20d up-day count ≥ 10               [上涨势能 — recent strength]
  G4  30d limit-up day count ≥ 1          [故事/热度 — proxy for theme/story]

All checks use PanelIndex with point-in-time slicing (no look-ahead).

Usage:
    from quality_universe import apply_quality_filter
    quality_today = apply_quality_filter(idx, liquid_today, as_of)

This is meant to be inserted between liquid top-N and sector ranking in
run_swing_backtest_fast.py.
"""

from __future__ import annotations

import numpy as np
from typing import Optional

from panel_index import PanelIndex


def quality_pass(idx: PanelIndex, tk: str, as_of: str,
                 require_g4_limitup: bool = True,
                 min_60d_ret: float = 0.0,
                 dd_floor: float = 0.80,
                 up_day_min: int = 10,
                 limitup_threshold_pct: float = 9.5) -> bool:
    """Return True if tk passes all quality gates as of `as_of`.

    Gates:
      G1: 60d cumulative return > `min_60d_ret`
      G2: close > 60d_max × `dd_floor`
      G3: 20d up-day count ≥ `up_day_min`
      G4: 30d limit-up day count ≥ 1 (only if require_g4_limitup=True)
    """
    h = idx.history(tk, as_of, n_days_back=60)
    closes = h.get("close")
    if closes is None or len(closes) < 60:
        return False

    # G1: 60d return > min_60d_ret
    if closes[0] <= 0:
        return False
    ret60 = closes[-1] / closes[0] - 1
    if ret60 <= min_60d_ret:
        return False

    # G2: not in deep drawdown from 60d high
    c60_max = float(np.max(closes))
    if c60_max <= 0:
        return False
    if closes[-1] / c60_max < dd_floor:
        return False

    # G3: 20d up-day count
    pct_chg = h.get("pct_chg")
    if pct_chg is not None and len(pct_chg) >= 20:
        # filter NaN safely
        recent_pct = pct_chg[-20:]
        valid = ~np.isnan(recent_pct)
        up_days = int(np.sum((recent_pct > 0) & valid))
    else:
        # Derive up-days from closes
        if len(closes) < 21:
            return False
        last21 = closes[-21:]
        rets20 = np.diff(last21) / np.maximum(last21[:-1], 1e-9)
        up_days = int(np.sum(rets20 > 0))
    if up_days < up_day_min:
        return False

    # G4: 30d limit-up (close ≥ +9.5% day) count ≥ 1
    if require_g4_limitup:
        if pct_chg is not None and len(pct_chg) >= 30:
            recent_pct30 = pct_chg[-30:]
            valid30 = ~np.isnan(recent_pct30)
            limitups = int(np.sum((recent_pct30 >= limitup_threshold_pct) & valid30))
            if limitups < 1:
                return False
        else:
            # No pct_chg data — derive from closes
            if len(closes) < 31:
                return False
            last31 = closes[-31:]
            rets30 = np.diff(last31) / np.maximum(last31[:-1], 1e-9) * 100
            limitups = int(np.sum(rets30 >= limitup_threshold_pct))
            if limitups < 1:
                return False

    return True


def apply_quality_filter(idx: PanelIndex, tickers: list[str], as_of: str,
                         **kwargs) -> list[str]:
    """Return subset of `tickers` that pass quality gates as of `as_of`."""
    return [tk for tk in tickers if quality_pass(idx, tk, as_of, **kwargs)]


# ───────────────────────── Self-test ───────────────────────────────────────

def _selftest() -> int:
    import pandas as pd
    failures = []

    # Build a synthetic 5-ticker panel × 80 days, with different profiles:
    #   UP   : +0.5%/day steady uptrend, no limit-ups
    #   DOWN : -0.5%/day steady downtrend
    #   FLAT : 0%/day flat
    #   STORY: -0.5%/day, BUT 2× limit-up days in last 30d (story/heat proxy)
    #   GREAT: +0.5%/day uptrend + 2× limit-up days in last 30d
    rows = []
    base = pd.Timestamp("2024-01-01")
    profiles = {
        "UP.SZ":    {"slope": 0.005, "spike_days": []},
        "DOWN.SZ":  {"slope": -0.005, "spike_days": []},
        "FLAT.SZ":  {"slope": 0.0, "spike_days": []},
        "STORY.SZ": {"slope": -0.005, "spike_days": [55, 75]},
        "GREAT.SZ": {"slope": 0.005, "spike_days": [55, 75]},
    }

    for tk, prof in profiles.items():
        px = 10.0
        for d in range(80):
            dt = (base + pd.Timedelta(days=d)).strftime("%Y%m%d")
            if d in prof["spike_days"]:
                ret = 0.0999    # ~10% limit up
            else:
                ret = prof["slope"]
            new_px = px * (1 + ret)
            rows.append({
                "ts_code": tk, "trade_date": dt,
                "open": px, "high": new_px * 1.01, "low": px * 0.99,
                "close": new_px, "vol": 1000, "amount": new_px * 1000,
                "pre_close": px, "pct_chg": ret * 100,
            })
            px = new_px

    panel = pd.DataFrame(rows)
    idx = PanelIndex(panel)

    as_of = "20240319"  # day 79 — gives 60d window back

    # Expected:
    #   UP    → fails G4 (no limit-up days)         → False
    #   DOWN  → fails G1 (60d return < 0)            → False
    #   FLAT  → fails G1 (60d return = 0, not > 0)   → False
    #   STORY → fails G1 (down)                      → False
    #   GREAT → passes all 4 gates                   → True

    results = {tk: quality_pass(idx, tk, as_of) for tk in profiles}
    expected = {"UP.SZ": False, "DOWN.SZ": False, "FLAT.SZ": False,
                "STORY.SZ": False, "GREAT.SZ": True}

    for tk, exp in expected.items():
        got = results.get(tk)
        if got != exp:
            failures.append(f"{tk}: expected {exp}, got {got}")

    # Test apply_quality_filter
    out = apply_quality_filter(idx, list(profiles.keys()), as_of)
    if set(out) != {"GREAT.SZ"}:
        failures.append(f"apply_quality_filter returned {out}, expected ['GREAT.SZ']")

    # Test require_g4_limitup=False loosens story gate
    out2 = apply_quality_filter(idx, list(profiles.keys()), as_of,
                                 require_g4_limitup=False)
    # Without G4, UP also passes (uptrend, not in DD, enough up-days)
    if "UP.SZ" not in out2 or "GREAT.SZ" not in out2:
        failures.append(f"without G4, UP/GREAT should pass, got {out2}")

    # PIT check: future bar must not affect as_of decision
    future_panel = pd.concat([panel, pd.DataFrame([{
        "ts_code": "UP.SZ", "trade_date": "20300101",
        "open": 1, "high": 1, "low": 1, "close": 1, "vol": 0,
        "amount": 0, "pre_close": 1, "pct_chg": -99,
    }])])
    idx2 = PanelIndex(future_panel)
    r1 = quality_pass(idx, "UP.SZ", as_of)
    r2 = quality_pass(idx2, "UP.SZ", as_of)
    if r1 != r2:
        failures.append(f"PIT LEAK: UP.SZ at {as_of} flipped {r1}→{r2} when future bar added")

    if failures:
        print("SELFTEST FAILED quality_universe:")
        for f in failures:
            print(" -", f)
        return 1
    print("SELFTEST PASSED quality_universe")
    print(f"- 4 quality gates: G1(60d>0), G2(close>0.8×60dHigh), G3(20d up≥10), G4(30d limit-up≥1)")
    print(f"- PIT-safe (future bar does not change as_of decision)")
    print(f"- 5 synthetic profiles → only GREAT (uptrend + limit-up) passes all 4")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
