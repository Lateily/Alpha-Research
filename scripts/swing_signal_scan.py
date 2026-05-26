#!/usr/bin/env python3
"""swing_signal_scan.py — per-stock technical+microstructure composite for swing.

Per SWING_STRATEGY_v1.md §3 (Signal layer). Pure-Python (no scipy).

Factors:
  breakout_20d:     close > max(close[-20:-1]) * 1.02   (binary)
  momentum_5d:      5d total return (continuous, z-score later)
  rsi_14:           Wilder RSI(14); gate to [40, 70]
  macd_cross:       MACD(12,26,9) > signal AND signal increasing 3d (binary)
  volume_spike:     vol / mean(vol[-20:]) > 1.5 (binary)
  atr_pos:          (close - low_band) / (high_band - low_band) ∈ [0,1]
  limit_up_followup: T-1 涨停 AND T-1 close == high (binary)
  (microstructure factors gated on Tushare 3-API which is not opened — stubbed)

Vetoes (gates that override composite to None):
  ma50_trend_down:  close < MA50 AND MA50 slope < 0
  atr_too_high:     ATR(14)/close > 0.08
  suspended_recent_3d: NaN close in last 3 trade dates

PIT discipline: all windows look back from as_of strictly. No forward look.
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


DEFAULT_WEIGHTS = {
    "breakout_20d":     0.20,
    "momentum_5d":      0.15,
    "rsi_14":           0.10,
    "macd_cross":       0.10,
    "volume_spike":     0.15,
    "atr_pos":          0.05,
    "limit_up_followup": 0.10,
    # 0.15 reserved for microstructure when 3-API lands
}

MIN_FACTORS_REQUIRED = 4   # of 7 → at least 4 non-None to score


# ───────────────────────── Pure-Python TA helpers ──────────────────────────

def _ema(values: list[float], n: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (n + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(alpha * v + (1 - alpha) * ema[-1])
    return ema


def _wilder_rsi(closes: list[float], n: int = 14) -> Optional[float]:
    if len(closes) < n + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, n + 1):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain, avg_loss = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain, loss = max(diff, 0), max(-diff, 0)
        avg_gain = (avg_gain * (n - 1) + gain) / n
        avg_loss = (avg_loss * (n - 1) + loss) / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    if len(closes) < slow + signal:
        return None, None
    ef = _ema(closes, fast)
    es = _ema(closes, slow)
    macd_line = [a - b for a, b in zip(ef[-len(es):], es)]
    sig = _ema(macd_line, signal)
    return macd_line, sig


def _atr(highs: list[float], lows: list[float], closes: list[float],
         n: int = 14) -> Optional[float]:
    if len(closes) < n + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < n:
        return None
    atr = sum(trs[:n]) / n
    for t in trs[n:]:
        atr = (atr * (n - 1) + t) / n
    return atr


# ───────────────────────── Per-stock factor computation ────────────────────

def compute_factors_one_stock(group: pd.DataFrame, as_of_yyyymmdd: str) -> dict:
    """group is sorted ascending by trade_date. Returns factor dict."""
    g = group[group["trade_date"] <= as_of_yyyymmdd].sort_values("trade_date")
    if len(g) < 60:   # need at least 60 bars for stable indicators
        return {"_status": "insufficient_history", "_n_bars": len(g)}
    closes = g["close"].tolist()
    opens = g["open"].tolist() if "open" in g else closes
    highs = g["high"].tolist() if "high" in g else closes
    lows = g["low"].tolist() if "low" in g else closes
    vols = g["vol"].tolist() if "vol" in g else [0.0] * len(closes)
    pct_chg = g["pct_chg"].tolist() if "pct_chg" in g else [0.0] * len(closes)
    if any((c is None or (isinstance(c, float) and math.isnan(c))) for c in closes[-3:]):
        return {"_status": "suspended_recent", "_n_bars": len(g)}

    out = {"_status": "ok", "_n_bars": len(closes)}

    # breakout_20d: close[-1] > max(close[-21:-1]) * 1.02
    if len(closes) >= 21:
        window = closes[-21:-1]
        out["breakout_20d"] = 1.0 if closes[-1] > max(window) * 1.02 else 0.0
    else:
        out["breakout_20d"] = None

    # momentum_5d
    if closes[-6] > 0 and len(closes) >= 6:
        out["momentum_5d"] = closes[-1] / closes[-6] - 1.0
    else:
        out["momentum_5d"] = None

    # RSI(14)
    rsi = _wilder_rsi(closes[-100:], 14)
    out["rsi_14"] = rsi
    out["_rsi_in_band"] = (rsi is not None and 40 <= rsi <= 70)

    # MACD cross
    macd, sig = _macd(closes[-60:], 12, 26, 9)
    if macd and sig and len(sig) >= 4:
        macd_above = macd[-1] > sig[-1]
        sig_rising = sig[-1] > sig[-2] > sig[-3]
        out["macd_cross"] = 1.0 if (macd_above and sig_rising) else 0.0
    else:
        out["macd_cross"] = None

    # volume spike
    vols20 = [v for v in vols[-20:] if v and v > 0]
    if vols20 and vols[-1]:
        mean_v = sum(vols20) / len(vols20)
        out["volume_spike"] = 1.0 if (vols[-1] / mean_v > 1.5) else 0.0
    else:
        out["volume_spike"] = None

    # ATR position (within 2*ATR band around mean)
    atr14 = _atr(highs[-30:], lows[-30:], closes[-30:], 14)
    out["_atr"] = atr14
    if atr14 and atr14 > 0:
        low_band = closes[-1] - 2 * atr14
        high_band = closes[-1] + 2 * atr14
        # crude proxy: where is close in (close - 2ATR, close + 2ATR)?
        # Use last 5d range to project
        recent_low = min(lows[-5:])
        recent_high = max(highs[-5:])
        if recent_high > recent_low:
            out["atr_pos"] = (closes[-1] - recent_low) / (recent_high - recent_low)
        else:
            out["atr_pos"] = 0.5
    else:
        out["atr_pos"] = None

    # 涨停板 followup: T-1 close ≥ pre_close * 1.099 AND close == high
    # we use pct_chg if available; else last day's close/prev_close
    if len(closes) >= 2 and closes[-2] > 0:
        prev_pct = pct_chg[-1] if pct_chg[-1] not in (None, 0) else (closes[-1] / closes[-2] - 1) * 100
        # NOTE: this measures CURRENT day's gain; for true T-1 followup we'd need T-2 data
        # Approximation: was yesterday a 涨停 + closed at high?
        yest_pct = pct_chg[-2] if len(pct_chg) >= 2 and pct_chg[-2] is not None else (
            (closes[-2] / closes[-3] - 1) * 100 if len(closes) >= 3 and closes[-3] > 0 else 0
        )
        yest_at_high = (closes[-2] == highs[-2]) if len(highs) >= 2 else False
        out["limit_up_followup"] = 1.0 if (yest_pct >= 9.5 and yest_at_high) else 0.0
    else:
        out["limit_up_followup"] = None

    # Vetoes
    out["_veto_atr_too_high"] = (atr14 is not None and atr14 / closes[-1] > 0.08)
    if len(closes) >= 50:
        ma50 = sum(closes[-50:]) / 50
        ma50_prev = sum(closes[-60:-10]) / 50 if len(closes) >= 60 else ma50
        out["_veto_ma50_down"] = closes[-1] < ma50 and ma50 < ma50_prev
    else:
        out["_veto_ma50_down"] = False
    out["_veto_suspended"] = False  # already checked at top

    return out


def composite_score(factors: dict, weights: dict = DEFAULT_WEIGHTS) -> Optional[float]:
    """Weighted sum over AVAILABLE factors. Returns 0-100 score or None."""
    if factors.get("_status") != "ok":
        return None
    if factors.get("_veto_atr_too_high") or factors.get("_veto_ma50_down") or \
       factors.get("_veto_suspended"):
        return None
    # rsi_14 is a gate, not a continuous factor
    if not factors.get("_rsi_in_band", False):
        # still let it score, but heavily down-weight rsi component
        rsi_contrib = 0.0
    else:
        rsi_contrib = 1.0
    factor_values = {
        "breakout_20d": factors.get("breakout_20d"),
        "momentum_5d": factors.get("momentum_5d"),
        "rsi_14": rsi_contrib,
        "macd_cross": factors.get("macd_cross"),
        "volume_spike": factors.get("volume_spike"),
        "atr_pos": factors.get("atr_pos"),
        "limit_up_followup": factors.get("limit_up_followup"),
    }
    avail = sum(1 for v in factor_values.values() if v is not None)
    if avail < MIN_FACTORS_REQUIRED:
        return None
    num = den = 0.0
    for f, w in weights.items():
        v = factor_values.get(f)
        if v is None:
            continue
        # Normalize: binary 0/1 → 0/1; continuous like momentum_5d → tanh-rescale
        if f == "momentum_5d":
            vv = max(-0.2, min(0.2, v))   # cap
            vv = (vv + 0.2) / 0.4         # 0..1
        elif f == "atr_pos":
            vv = max(0.0, min(1.0, v))
        else:
            vv = max(0.0, min(1.0, float(v)))
        num += w * vv
        den += w
    if den == 0:
        return None
    return round(100 * num / den, 2)


def compute_swing_signals(daily_panel: pd.DataFrame, as_of: date | str,
                          members: list[str],
                          weights: dict = DEFAULT_WEIGHTS) -> dict[str, dict]:
    """Top-level: for each member, compute factor dict + composite."""
    as_of_str = (as_of.strftime("%Y%m%d") if hasattr(as_of, "strftime")
                 else str(as_of).replace("-", "")[:8])
    sliced = daily_panel[daily_panel["trade_date"] <= as_of_str]
    if "ts_code" not in sliced.columns:
        return {}
    members_set = set(members)
    sliced = sliced[sliced["ts_code"].isin(members_set)]
    out = {}
    for tk, grp in sliced.groupby("ts_code", sort=False):
        factors = compute_factors_one_stock(grp, as_of_str)
        score = composite_score(factors, weights)
        out[tk] = {
            "composite": score,
            "factors": {k: v for k, v in factors.items() if not k.startswith("_") or k in ("_atr", "_rsi_in_band")},
            "vetoes": [k for k in ("_veto_atr_too_high", "_veto_ma50_down", "_veto_suspended")
                       if factors.get(k)],
        }
    return out


# ───────────────────────── Self-test ───────────────────────────────────────

def _selftest() -> int:
    failures = []
    rows = []
    base = pd.Timestamp("2024-01-01")
    # 4 stocks: BREAK (clean breakout), FLAT, DECAY, NOISE
    specs = {
        "BREAK.SZ": lambda d: 10 * (1.001 ** d) if d < 60 else 10 * (1.001 ** 60) * (1.02 ** (d - 60)),
        "FLAT.SZ":  lambda d: 10 + 0.001 * d,
        "DECAY.SZ": lambda d: 10 * (0.998 ** d),
        "NOISE.SZ": lambda d: 10 + (-1) ** d * 0.5,
    }
    for tk, fn in specs.items():
        for d in range(80):
            dt = (base + pd.Timedelta(days=d)).strftime("%Y%m%d")
            px = fn(d)
            rows.append({"ts_code": tk, "trade_date": dt,
                         "open": px, "high": px * 1.005, "low": px * 0.995,
                         "close": px, "vol": 1000 + d * 10,
                         "amount": px * 1000, "pre_close": px,
                         "pct_chg": 0.1})
    panel = pd.DataFrame(rows)
    signals = compute_swing_signals(panel, "20240320", list(specs.keys()))

    # BREAK should score highest, DECAY lowest
    scores = {tk: (s.get("composite") or 0) for tk, s in signals.items()}
    if scores.get("BREAK.SZ", 0) <= scores.get("DECAY.SZ", 0):
        failures.append(f"BREAK should beat DECAY: {scores}")
    if scores.get("BREAK.SZ", 0) <= 0:
        failures.append(f"BREAK should have positive score: {scores}")

    # PIT: future bar must not change signal at as_of
    panel2 = pd.concat([panel,
                        pd.DataFrame([{"ts_code": "BREAK.SZ", "trade_date": "20300101",
                                       "open": 9999, "high": 9999, "low": 9999,
                                       "close": 9999, "vol": 1e9, "amount": 1e15,
                                       "pre_close": 9999, "pct_chg": 0}])])
    signals2 = compute_swing_signals(panel2, "20240320", list(specs.keys()))
    if signals.get("BREAK.SZ", {}).get("composite") != signals2.get("BREAK.SZ", {}).get("composite"):
        failures.append("PIT LEAK: future bar changed BREAK composite at as_of")

    if failures:
        print("SELFTEST FAILED swing_signal_scan:")
        for f in failures: print(" -", f)
        return 1
    print("SELFTEST PASSED swing_signal_scan")
    print(f"- BREAK.SZ composite={scores.get('BREAK.SZ')}, DECAY.SZ composite={scores.get('DECAY.SZ')}")
    print("- PIT enforced (future bar does not change signal at as_of)")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Swing technical signal scanner.")
    p.add_argument("--prices", default=str(REPO_ROOT / "data_history" / "panel" / "daily_prices.parquet"))
    p.add_argument("--universe", default=str(REPO_ROOT / "public" / "data" / "sector_rank.json"))
    p.add_argument("--as-of", default=None)
    p.add_argument("--out", default=str(REPO_ROOT / "public" / "data" / "swing_signals.json"))
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()

    panel = pd.read_parquet(args.prices)
    as_of = args.as_of or panel["trade_date"].max()
    uni_data = json.load(open(args.universe))
    members = uni_data.get("universe") or list(panel["ts_code"].unique())

    signals = compute_swing_signals(panel, as_of, members)
    scored = {tk: s for tk, s in signals.items() if s.get("composite") is not None}
    ranked = sorted(scored.items(), key=lambda kv: -kv[1]["composite"])
    out = {
        "_meta": {"as_of": str(as_of), "n_universe": len(members),
                  "n_scored": len(scored)},
        "signals": signals,
        "ranking": [{"ts_code": tk, "composite": s["composite"]}
                    for tk, s in ranked],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    print(f"as_of={as_of} scanned={len(members)}, scored={len(scored)}")
    print("top 10:")
    for tk, s in ranked[:10]:
        print(f"  {tk}: {s['composite']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
