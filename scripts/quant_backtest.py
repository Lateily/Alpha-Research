#!/usr/bin/env python3
"""quant_backtest.py — Quant Strategy Factory v0 backtest harness (PR3).

Drives the H1 signal (and a negative control) through a survivorship-safe, PIT-clean,
T+1, cost-charged long-only backtest, then measures same-gross alpha vs CSI300 + EW
with a stationary-bootstrap CI. NO edge is claimed unless the OOS bootstrap CI clears
zero after costs.

HARD PRECONDITION (Junyan): require_pass() — the survivorship_integrity gate — runs FIRST.
No backtest number is produced unless the gate passes. Universe is panel-derived
(compute_liquid_universe over daily_prices.parquet); universe_pit.json is NOT used.

Reuses the PROVEN engine primitives (no reinvention):
  - liquid_universe.compute_liquid_universe  — survivorship-safe per-date universe (.shift(1) PIT)
  - panel_index.PanelIndex.history           — per-ticker bars <= as_of (no look-ahead)
  - run_swing_backtest_fast.{fill_price,trade_cost,is_limit_up,is_limit_down}  — T+1 fills + cost
  - backtest_v2.{cagr,sharpe,max_drawdown}   — metrics
  - stationary_bootstrap.bootstrap_ci        — Politis-Romano CI (B=10000, p=1/10)
  - quant_strategy.h1_signal                 — the live H1 signal (exact)

Arms (this increment): H1 (default) + oversold_reversion (NEGATIVE CONTROL — no uptrend
filter; we expect it to NOT beat H1). The quality+low_vol periodic-tilt baseline, the
forward-only Core-Thesis overlay arm, walk-forward windows, and the full 19-gate wiring
are the immediate follow-up (flagged in the report).

Read-only. Local/backtest-only (needs the gitignored parquet). Output: public/data/quant_backtest_report.json
Usage: python3 scripts/quant_backtest.py [--start YYYYMMDD --end YYYYMMDD] [--selftest]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
PANEL = REPO / "data_history" / "panel" / "daily_prices.parquet"
INDEX = REPO / "data_history" / "panel" / "index_prices.parquet"
OUT = D / "quant_backtest_report.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from liquid_universe import compute_liquid_universe          # noqa: E402
from panel_index import PanelIndex                           # noqa: E402
from stationary_bootstrap import bootstrap_ci, mean as bs_mean  # noqa: E402
from quant_strategy import h1_signal, THRESH, _sma as _qsma, _rsi as _qrsi  # noqa: E402
import survivorship_gate                                     # noqa: E402

# Execution primitives + metrics inlined VERBATIM from the proven engine
# (run_swing_backtest_fast.py / backtest_v2.py) — copied rather than imported because
# run_swing_backtest_fast hard-imports quality_universe etc. that aren't all on main.
# Same cost model (slippage in price, commission+stamp separate — no double-count).
COMMISSION, STAMP_DUTY_SELL, SLIPPAGE, DAILY_LIMIT = 0.00025, 0.0005, 0.0010, 0.099


def is_limit_up(row):
    pre = row.get("pre_close")
    return bool(pre and pre > 0 and (row.get("open", 0) / pre - 1) >= DAILY_LIMIT)


def is_limit_down(row):
    pre = row.get("pre_close")
    return bool(pre and pre > 0 and (row.get("open", 0) / pre - 1) <= -DAILY_LIMIT)


def fill_price(row, side, slippage=SLIPPAGE):
    open_p = row.get("open") or row.get("close")
    if not open_p or open_p <= 0:
        return None
    blend = (row.get("high", open_p) + row.get("low", open_p) + row.get("close", open_p)) / 3.0
    raw = (open_p + blend) / 2.0
    return raw * (1 + slippage) if side == "buy" else raw * (1 - slippage)


def trade_cost(notional, side, commission=COMMISSION, stamp_duty_sell=STAMP_DUTY_SELL):
    return notional * (commission + (stamp_duty_sell if side == "sell" else 0.0))


def cagr(equity, ppy):
    if len(equity) < 2 or equity[0] <= 0:
        return None
    yrs = (len(equity) - 1) / ppy
    return (equity[-1] / equity[0]) ** (1 / yrs) - 1 if yrs > 0 else None


def max_drawdown(equity):
    peak, mdd = -1e18, 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


def sharpe(returns, ppy, rf=0.0):
    rs = [r for r in returns if r is not None]
    if len(rs) < 2:
        return None
    m = sum(rs) / len(rs)
    var = sum((r - m) ** 2 for r in rs) / (len(rs) - 1)
    sd = var ** 0.5
    return (m - rf / ppy) / sd * (ppy ** 0.5) if sd else None

CSI300 = "000300.SH"
CAPITAL = 1_000_000.0
MAX_POSITIONS = 10            # [unvalidated]
STALE_EXIT_DAYS = 5           # [unvalidated] force mark-out a held name after N consecutive no-bar (halt/delist) days
DAILY_RF = 0.0
TOP_N_ADV = THRESH["top_n_adv"]
LOOKBACK = THRESH["adv_n"]
MIN_DVOL = 1e7
MIN_BARS = THRESH["ma_long_n"] + THRESH["ma_long_rise_lookback"] + 2   # H1 needs ~212


# ───────────────────────── signal arms (pluggable) ──────────────────────────
def arm_h1(closes, vols):
    """v0-H1 default: quality-filtered pullback-in-uptrend (the live signal)."""
    return h1_signal(closes, vols)


def arm_oversold_control(closes, vols):
    """NEGATIVE CONTROL: buy oversold REGARDLESS of trend (the falsified inverse-momentum
    neighborhood). No MA200 uptrend filter. We expect this to NOT beat H1 — if it does, H1's
    uptrend filter adds nothing."""
    if len(closes) < MIN_BARS:
        return {"action": "INSUFFICIENT_DATA"}
    from quant_strategy import _rsi
    rsi = _rsi(closes, THRESH["rsi_n"])
    r = rsi[-1]
    action = "ENTER" if (r is not None and r < 30.0 and closes[-1] > closes[-2]) else "NO_SETUP"
    return {"action": action, "rsi": r, "price": closes[-1],
            "stop": closes[-1] * (1.0 - THRESH["stop_pct"]) if action == "ENTER" else None}


ARMS = {"h1": arm_h1, "oversold_control": arm_oversold_control}


# ───────────────────────── the backtest loop ────────────────────────────────
def _row_at(idx: PanelIndex, tk: str, date_str: str):
    """The single bar for (tk, date_str) as a dict, or None (delisted / no bar that day).
    PanelIndex.history returns numpy arrays -> check with len(), never truthiness."""
    h = idx.history(tk, date_str, n_days_back=1)
    td = h.get("dates")                       # PanelIndex.history returns the date key as "dates"
    if td is None or len(td) == 0 or str(td[-1]) != date_str:
        return None
    def _last(k):
        v = h.get(k)
        return v[-1] if (v is not None and len(v)) else None
    return {k: _last(k) for k in ("open", "high", "low", "close", "pre_close")}


def _norm_date(s):
    """Accept YYYY-MM-DD or YYYYMMDD."""
    return s.replace("-", "") if isinstance(s, str) else s


# ── Vectorized indicator cache (PR3b-1): compute each ticker's rolling indicators ONCE over its
# full series with the EXACT live-signal _sma/_rsi, then per-day signals are O(1) lookups instead of
# an O(bars) recompute per (ticker, day). _sma is seed-independent => MA200/MA20/MA5/volMA match the
# per-window path EXACTLY. _rsi (Wilder) seeded from bar 0 differs from the per-day 242-window reseed
# by ~1e-7 after ~228 convergence steps — immaterial to RSI<40 / RSI-turning decisions (verified by
# running fast vs slow; selftest asserts bit-identical when the window covers bar 0).
_IND_CACHE = {}


def _indicators(idx, tk, full_to):
    C = _IND_CACHE.get(tk)
    if C is not None:
        return C
    h = idx.history(tk, full_to, n_days_back=None)
    dates = [str(d) for d in (h.get("dates") if h.get("dates") is not None else [])]
    closes = [float(x) for x in (h.get("close") if h.get("close") is not None else [])]
    vlist = [float(x) for x in (h.get("vol") if h.get("vol") is not None else [])]
    vols = vlist or None
    C = {"close": closes, "vol": vols,
         "ma200": _qsma(closes, THRESH["ma_long_n"]), "ma20": _qsma(closes, THRESH["ma_mid_n"]),
         "ma5": _qsma(closes, THRESH["ma_short_n"]), "rsi": _qrsi(closes, THRESH["rsi_n"]),
         "volma": _qsma(vols, THRESH["vol_ma_n"]) if vols else None,
         "date_to_i": {d: i for i, d in enumerate(dates)}}
    _IND_CACHE[tk] = C
    return C


def _h1_fast(C, i):
    closes, ma200, ma20, ma5, rsi = C["close"], C["ma200"], C["ma20"], C["ma5"], C["rsi"]
    vols, volma = C["vol"], C["volma"]
    price, rb = closes[i], THRESH["ma_long_rise_lookback"]
    uptrend = (ma200[i] is not None and price >= ma200[i]
               and i - rb >= 0 and ma200[i - rb] is not None and ma200[i] >= ma200[i - rb])
    win = THRESH["rsi_pullback_window"]
    recent = [r for r in rsi[max(0, i - win + 1):i + 1] if r is not None]
    pulled = bool(recent) and min(recent) <= THRESH["rsi_pullback_max"]
    turning = rsi[i] is not None and rsi[i - 1] is not None and rsi[i] > rsi[i - 1]
    setup = uptrend and pulled and turning
    up_day = closes[i] > closes[i - 1]
    vol_ok = (volma is None) or (volma[i] is None) or (vols[i] >= THRESH["vol_confirm_mult"] * volma[i])
    reclaim = ma5[i] is not None and price >= ma5[i]
    confirm = up_day and vol_ok and reclaim
    action = "ENTER" if (setup and confirm) else ("WAIT" if setup else "NO_SETUP")
    return {"action": action, "stop": price * (1.0 - THRESH["stop_pct"]) if action == "ENTER" else None}


def _oversold_fast(C, i):
    r, closes = C["rsi"][i], C["close"]
    action = "ENTER" if (r is not None and r < 30.0 and closes[i] > closes[i - 1]) else "NO_SETUP"
    return {"action": action, "stop": closes[i] * (1.0 - THRESH["stop_pct"]) if action == "ENTER" else None}


_FAST = {"h1": _h1_fast, "oversold_control": _oversold_fast}


def run_arm(arm_name, panel, idx, liquid, trade_dates, start, end, capital=CAPITAL, fast=True):
    """Long-only, T+1, cost-charged. DECIDE at T using bars <= T; FILL at T+1. No same-day fill.
    Held names with no bar (halt/delist) are marked at last close and force-exited after
    STALE_EXIT_DAYS; a name exited this round is barred from same-day re-entry.
    fast=True uses the precomputed indicator cache (O(1)/day); fast=False is the per-day recompute
    reference (#54). Identical decision logic; verified equal on 2023-H1."""
    signal_fn = ARMS[arm_name]
    have = set(zip(panel["trade_date"].astype(str), panel["ts_code"]))
    win = [d for d in trade_dates if start <= d <= end]
    cash = capital
    positions = {}            # tk -> {entry_px, shares, stop, entry_i}
    equity_curve, trades = [], []
    closed_returns = []

    for i, T in enumerate(win):
        # mark-to-market on T close (<= T, no look-ahead)
        mv = 0.0
        for tk, p in positions.items():
            r = _row_at(idx, tk, T)
            c = (r or {}).get("close")
            if c:
                p["last_px"] = c          # mark at the latest REAL close (never frozen at entry)
            px = p.get("last_px", p["entry_px"])
            mv += p["shares"] * px
        nav = cash + mv
        gross = (mv / nav) if nav > 0 else 0.0
        equity_curve.append({"date": T, "nav": round(nav, 2), "cash": round(cash, 2),
                             "gross": round(gross, 6), "n_positions": len(positions)})
        if i + 1 >= len(win):
            break
        T_next = win[i + 1]

        # ---- EXIT decisions at T (close-based), fill at T+1. Track exits to bar same-day re-entry. ----
        exited = set()
        for tk in list(positions.keys()):
            p = positions[tk]
            r_t = _row_at(idx, tk, T)
            if r_t is None:                       # halt/delist: no bar at T
                p["missing"] = p.get("missing", 0) + 1
                if p["missing"] >= STALE_EXIT_DAYS:   # delist policy: force mark-out at last known close
                    px = p["last_px"]
                    proceeds = p["shares"] * px
                    cash += proceeds - trade_cost(proceeds, "sell")
                    closed_returns.append(px / p["entry_px"] - 1.0)
                    trades.append({"ticker": tk, "entry": p["entry_px"], "entry_date": p["entry_date"],
                                   "exit": round(px, 4), "ret": round(px / p["entry_px"] - 1.0, 4),
                                   "reason": "delist_stale_markout", "exit_date": T})
                    exited.add(tk)
                    del positions[tk]
                continue
            p["missing"] = 0
            close_t = r_t["close"]
            p["last_px"] = close_t
            hist = idx.history(tk, T, n_days_back=THRESH["ma_mid_n"] + 2)
            hc = hist.get("close")
            hc = list(hc) if hc is not None else []
            ma20 = (sum(hc[-THRESH["ma_mid_n"]:]) / THRESH["ma_mid_n"]
                    if len(hc) >= THRESH["ma_mid_n"] else None)
            held = i - p["entry_i"]
            exit_reason = None
            if close_t <= p["stop"]:
                exit_reason = "stop"
            elif ma20 is not None and close_t < ma20:
                exit_reason = "trend_break"
            elif held >= THRESH["time_stop_days"]:
                exit_reason = "time_stop"
            if exit_reason:
                r_next = _row_at(idx, tk, T_next)
                if r_next is None or is_limit_down(r_next):
                    continue                      # can't sell into a locked-down/absent bar; retry next day
                px = fill_price(r_next, "sell")
                if px is None:
                    continue
                proceeds = p["shares"] * px
                cash += proceeds - trade_cost(proceeds, "sell")
                ret = px / p["entry_px"] - 1.0
                closed_returns.append(ret)
                trades.append({"ticker": tk, "entry": p["entry_px"], "entry_date": p["entry_date"],
                               "exit": round(px, 4), "ret": round(ret, 4), "reason": exit_reason,
                               "exit_date": T_next})
                exited.add(tk)
                del positions[tk]

        # ---- ENTRY decisions at T (signal on bars <= T), fill at T+1 ----
        slots = MAX_POSITIONS - len(positions)
        if slots > 0:
            members = [tk for tk in liquid.get(T, [])
                       if (T, tk) in have and tk not in positions and tk not in exited]  # no same-day re-entry
            enters = []
            for tk in members:
                if fast:
                    C = _indicators(idx, tk, trade_dates[-1])
                    i_ = C["date_to_i"].get(T)
                    if i_ is None or (i_ + 1) < MIN_BARS:
                        continue
                    s = _FAST[arm_name](C, i_)
                else:
                    h = idx.history(tk, T, n_days_back=MIN_BARS + 30)
                    hc = h.get("close")
                    closes = list(hc) if hc is not None else []
                    hv = h.get("vol")
                    vols = list(hv) if (hv is not None and len(hv)) else None
                    if len(closes) < MIN_BARS:
                        continue
                    s = signal_fn(closes, vols)
                if s.get("action") == "ENTER":
                    enters.append((tk, s))
            enters.sort(key=lambda kv: kv[0])     # deterministic; equal-weight (no signal-strength ranking in v0)
            budget_each = (cash / slots) if slots else 0.0
            for tk, s in enters[:slots]:
                r_next = _row_at(idx, tk, T_next)
                if r_next is None or is_limit_up(r_next):
                    continue                      # can't buy into a locked-up/absent bar
                px = fill_price(r_next, "buy")
                if px is None or px <= 0:
                    continue
                budget = min(budget_each, cash)
                shares = int(budget / px / 100) * 100   # A-share 100-share lots
                if shares <= 0:
                    continue
                notional = shares * px
                cost = trade_cost(notional, "buy")
                if notional + cost > cash:
                    continue
                cash -= notional + cost
                positions[tk] = {"entry_px": px, "shares": shares, "entry_date": T,
                                 "stop": s.get("stop") or px * (1.0 - THRESH["stop_pct"]), "entry_i": i,
                                 "last_px": px, "missing": 0}

    return {"equity_curve": equity_curve, "trades": trades, "closed_returns": closed_returns}


# ───────────────────────── benchmarks + alpha ───────────────────────────────
def _csi300_curve(win, capital):
    import pandas as pd
    if not INDEX.exists():
        return None
    ix = pd.read_parquet(INDEX, columns=["ts_code", "trade_date", "close"])
    ix = ix[ix["ts_code"] == CSI300].sort_values("trade_date")
    by = {str(d): float(c) for d, c in zip(ix["trade_date"], ix["close"])}
    curve, eq, prev = [], capital, None
    for T in win:
        c = by.get(T)
        if c is not None and prev is not None and prev > 0:
            eq *= c / prev
        if c is not None:
            prev = c
        curve.append({"date": T, "equity": round(eq, 2)})
    return curve


def _daily_returns(curve, key="nav"):
    out, prev = [], None
    for pt in curve:
        v = pt.get(key, pt.get("equity"))
        if prev is not None and prev > 0:
            out.append(v / prev - 1.0)
        prev = v
    return out


def _alpha_series(strat_curve, bench_curve):
    """Same-length per-period alpha = strategy daily ret − benchmark daily ret."""
    sr = _daily_returns(strat_curve, "nav")
    br = _daily_returns(bench_curve, "equity")
    n = min(len(sr), len(br))
    return [sr[i] - br[i] for i in range(n)]


def _same_gross_curve(bench_curve, strat_curve, capital, daily_rf=0.0):
    """Scale the benchmark by the strategy's daily GROSS exposure (cash portion earns rf) so the
    comparison is like-for-like when the strategy is partly in cash — the rigorous same-gross alpha
    (mirrors run_swing_backtest_fast._same_gross_benchmark_curve)."""
    gross_by = {p["date"]: float(p.get("gross", 0.0) or 0.0) for p in strat_curve}
    out, prev, eq = [], None, capital
    for row in bench_curve:
        b = row["equity"]
        bret = (b / prev - 1.0) if (prev and prev > 0) else 0.0
        prev = b
        g = max(0.0, min(1.0, gross_by.get(row["date"], 0.0)))
        eq *= 1.0 + g * bret + (1.0 - g) * daily_rf
        out.append({"date": row["date"], "equity": eq})
    return out


def _metrics(curve, closed_returns):
    eqs = [pt["nav"] for pt in curve]
    rets = _daily_returns(curve, "nav")
    wins = [r for r in closed_returns if r > 0]
    return {
        "cagr": cagr(eqs, 252.0), "sharpe": sharpe(rets, 252.0), "max_drawdown": max_drawdown(eqs),
        "n_trades": len(closed_returns),
        "hit_rate": round(len(wins) / len(closed_returns), 4) if closed_returns else None,
        "avg_trade_ret": round(sum(closed_returns) / len(closed_returns), 4) if closed_returns else None,
        "final_nav": round(eqs[-1], 2) if eqs else None, "days": len(eqs),
    }


def _bootstrap_alpha(alpha):
    if len(alpha) < 30:
        return {"_status": "too_few_obs", "n": len(alpha)}
    r = bootstrap_ci(alpha, bs_mean, B=10000, p=1 / 10, seed=42)
    if r.get("_status") != "ok":
        return r
    daily = r.get("point_estimate")
    # Compute from the float CI bounds — do NOT use `straddles_zero is False` (it's numpy.bool_, so
    # identity always fails and the gate is silently stuck False even when the CI is fully below zero).
    lo = float(r["ci_lo"]) if r.get("ci_lo") is not None else None
    hi = float(r["ci_hi"]) if r.get("ci_hi") is not None else None
    ci_positive = (lo is not None and lo > 0.0)        # the ALPHA-CLAIM gate: CI fully ABOVE zero
    ci_negative = (hi is not None and hi < 0.0)        # significantly NEGATIVE (useful for the neg control)
    return {"daily_alpha_mean": float(daily) if daily is not None else None,
            "ci_lo_daily": lo, "ci_hi_daily": hi,
            "p_value": r.get("p_value_h0_zero"), "n_boot_valid": r.get("n_boot_valid"),
            "annualized_alpha_pct": round(daily * 252 * 100, 2) if daily is not None else None,
            "ci_excludes_zero": bool(ci_positive or ci_negative),
            "ci_positive_after_cost": bool(ci_positive),   # TRUE => a positive alpha claim is permitted
            "ci_negative_after_cost": bool(ci_negative)}   # TRUE => significantly negative


def build(start=None, end=None) -> dict:
    import pandas as pd
    _IND_CACHE.clear()                             # fresh indicator cache per run (no cross-window staleness)
    gate = survivorship_gate.require_pass()        # HARD PRECONDITION — raises unless passed
    panel = pd.read_parquet(PANEL, columns=["ts_code", "trade_date", "open", "high", "low",
                                            "close", "vol", "amount", "pre_close"])
    panel = panel[panel["ts_code"].map(lambda t: isinstance(t, str) and t.endswith((".SZ", ".SH")))]
    panel["trade_date"] = panel["trade_date"].astype(str)
    trade_dates = sorted(panel["trade_date"].unique())
    start = _norm_date(start) or trade_dates[0]    # accept YYYY-MM-DD or YYYYMMDD
    end = _norm_date(end) or trade_dates[-1]
    # bound work to the window + enough prior history (MA200 + ADV lookback) for fast windowed runs
    sidx = trade_dates.index(start) if start in trade_dates else 0
    buf_start = trade_dates[max(0, sidx - 300)]
    panel = panel[panel["trade_date"] >= buf_start].reset_index(drop=True)
    idx = PanelIndex(panel)
    liquid = compute_liquid_universe(panel, top_n=TOP_N_ADV, lookback_days=LOOKBACK, min_dollar_vol=MIN_DVOL)

    win = [d for d in trade_dates if start <= d <= end]
    if not win:                                    # fail-fast: never write an empty 0-day report
        raise SystemExit(f"empty backtest window: no trading days in [{start}, {end}] "
                         f"(panel covers {trade_dates[0]}..{trade_dates[-1]}; use YYYYMMDD or YYYY-MM-DD).")
    csi = _csi300_curve(win, CAPITAL)

    arms_out = {}
    for arm in ARMS:
        res = run_arm(arm, panel, idx, liquid, trade_dates, start, end)
        m = _metrics(res["equity_curve"], res["closed_returns"])
        ab = {}
        if csi:
            sg = _same_gross_curve(csi, res["equity_curve"], CAPITAL)   # scale CSI300 by strategy gross
            ab["vs_csi300_same_gross"] = _bootstrap_alpha(_alpha_series(res["equity_curve"], sg))
        arms_out[arm] = {"metrics": m, "alpha": ab, "n_equity_pts": len(res["equity_curve"])}

    manifest = {"strategy": "quant_v0", "arms": list(ARMS), "max_positions": MAX_POSITIONS,
                "universe": f"top{TOP_N_ADV}_adv_liquid", "thresholds": THRESH,
                "costs": {"commission": 0.00025, "stamp_sell": 0.0005, "slippage": 0.0010}}
    return {
        "_meta": {"layer": "Quant Strategy Factory v0 — backtest harness (PR3)",
                  "generated_at": (datetime.now(timezone.utc)).isoformat(),
                  "window": {"start": start, "end": end, "trading_days": len(win)},
                  "universe_source": "panel_derived_compute_liquid_universe",
                  "universe_pit_used": False,
                  "survivorship_gate": {"passed": gate.get("passed"), "checks":
                                        [c["check"] for c in gate.get("checks", [])]},
                  "read_only": True,
                  "disclaimer": ("UNVALIDATED. A positive edge is claimed ONLY when ci_positive_after_cost "
                                 "(OOS bootstrap CI lower bound > 0 after costs); ci_negative_after_cost means "
                                 "significantly negative. H1+overlay arm is forward-only (no historical theses) "
                                 "and NOT backtested here; quality+low_vol baseline + walk-forward + 19-gate "
                                 "are the immediate follow-up."),
                  "arms_note": "h1 = quality-filtered pullback-in-uptrend; oversold_control = NEGATIVE CONTROL "
                               "(oversold, no uptrend filter) — H1 should not be beaten by it."},
        "manifest_hash": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
        "arms": arms_out,
        "validation_status": "unvalidated",
    }


def run(start=None, end=None) -> dict:
    out = build(start, end)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    out = run(args.start, args.end)
    w = out["_meta"]["window"]
    print("=" * 78)
    print("QUANT v0 BACKTEST (panel-derived survivorship-safe; T+1; cost-charged; UNVALIDATED)")
    print("=" * 78)
    print(f"window {w['start']}..{w['end']} ({w['trading_days']}d)  gate={out['_meta']['survivorship_gate']['passed']}")
    for arm, a in out["arms"].items():
        m, al = a["metrics"], a["alpha"].get("vs_csi300_same_gross", {})
        print(f"  [{arm:<16}] CAGR={m['cagr']} Sharpe={m['sharpe']} MaxDD={m['max_drawdown']} "
              f"trades={m['n_trades']} hit={m['hit_rate']}")
        if al:
            print(f"       vs CSI300 (same-gross): ann_alpha={al.get('annualized_alpha_pct')}% "
                  f"alpha_claim(ci>0)={al.get('ci_positive_after_cost')} "
                  f"sig_neg(ci<0)={al.get('ci_negative_after_cost')} p={al.get('p_value')}")
    print(f"[quant-backtest] wrote {OUT}")
    return 0


def _selftest() -> int:
    """Loop-logic checks on a synthetic panel (no parquet / no gate): T+1 discipline + no look-ahead."""
    errs = []
    import pandas as pd
    dates = [f"D{i:03d}" for i in range(260)]
    # WIN.SZ: engineered uptrend -> pullback -> bounce (fires an H1 ENTER) then drift-down (trend-break exit)
    win_c = [50.0 + 0.20 * k for k in range(231)]
    win_c += [win_c[-1] - 3.0 * (k + 1) for k in range(6)]      # 6-bar dip -> RSI < 40
    win_c += [win_c[-1] + 2.0, win_c[-1] + 5.0]                 # 2-bar bounce -> reclaim MA5, up day -> ENTER
    win_c += [win_c[-1] - 1.0 * (k + 1) for k in range(13)]     # drift down -> trend-break exit
    while len(win_c) < len(dates):
        win_c.append(win_c[-1] - 0.5)
    rows = []
    for i, dt in enumerate(dates):
        for j in range(12):
            px = 10.0 + j + 0.04 * i
            rows.append({"ts_code": f"S{j:02d}.SZ", "trade_date": dt, "open": px, "high": px * 1.01,
                         "low": px * 0.99, "close": px, "vol": (20 - j) * 1000.0,
                         "amount": px * (20 - j) * 1000.0 / 100.0, "pre_close": px})
        wc = win_c[i]
        rows.append({"ts_code": "WIN.SZ", "trade_date": dt, "open": wc, "high": wc * 1.01, "low": wc * 0.99,
                     "close": wc, "vol": 90000.0, "amount": wc * 90000.0 / 100.0,
                     "pre_close": win_c[i - 1] if i else wc})
    panel = pd.DataFrame(rows)
    idx = PanelIndex(panel)
    liquid = compute_liquid_universe(panel, top_n=5, lookback_days=10, min_dollar_vol=0)
    _IND_CACHE.clear()
    res = run_arm("h1", panel, idx, liquid, dates, dates[0], dates[-1])           # fast (cached)
    if not res["equity_curve"]:
        errs.append("backtest produced no equity curve")
    # PR3b-1: fast (cached) vs slow (per-day recompute) must be IDENTICAL on this synthetic
    # (the 242-window covers bar 0 here, so even the Wilder-RSI seed matches exactly).
    res_slow = run_arm("h1", panel, idx, liquid, dates, dates[0], dates[-1], fast=False)
    if [round(p["nav"], 2) for p in res["equity_curve"]] != [round(p["nav"], 2) for p in res_slow["equity_curve"]]:
        errs.append("fast vs slow equity curves differ on the synthetic (vectorization changed the logic)")
    if len(res["trades"]) != len(res_slow["trades"]):
        errs.append(f"fast vs slow trade counts differ ({len(res['trades'])} vs {len(res_slow['trades'])})")
    # no look-ahead: appending a FUTURE huge bar must not change the equity curve over the past window
    fut = pd.concat([panel, pd.DataFrame([{"ts_code": "S00.SZ", "trade_date": "D999", "open": 1e6,
                     "high": 1e6, "low": 1e6, "close": 1e6, "vol": 1e9, "amount": 1e12, "pre_close": 1e6}])],
                    ignore_index=True)
    idx2 = PanelIndex(fut)
    liquid2 = compute_liquid_universe(fut, top_n=5, lookback_days=10, min_dollar_vol=0)
    _IND_CACHE.clear()                                                            # rebuild cache from fut
    res2 = run_arm("h1", fut, idx2, liquid2, dates, dates[0], dates[-1])   # same past window
    nav1 = [round(p["nav"], 2) for p in res["equity_curve"]]
    nav2 = [round(p["nav"], 2) for p in res2["equity_curve"]]
    if nav1 != nav2:
        errs.append("LOOK-AHEAD: a future bar changed the past equity curve")
    # arms registered + alpha helper sane
    if set(ARMS) != {"h1", "oversold_control"}:
        errs.append("arms registry changed unexpectedly")
    # a real ENTER->EXIT round-trip must execute (proves T+1 fills + exits, not just an empty loop)
    if len(res["trades"]) < 1:
        errs.append("no trade executed on the engineered WIN.SZ case — T+1 fill/exit path broken")
    # no same-day round-trip (entry strictly before exit) — guards the no-same-day-re-entry rule
    if any(t.get("entry_date") and t.get("exit_date") and t["entry_date"] >= t["exit_date"]
           for t in res["trades"]):
        errs.append("a trade has entry_date >= exit_date (same-day round-trip / re-entry leak)")
    if errs:
        print("quant_backtest selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"quant_backtest selftest PASSED ({len(res['trades'])} real trade(s) executed; NO look-ahead — a "
          "future bar leaves the past equity curve unchanged; T+1 fills; entry<exit (no same-day round-trip); "
          "arms = h1 + oversold_control)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
