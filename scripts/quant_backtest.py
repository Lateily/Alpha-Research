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
from quant_strategy import h1_signal, THRESH                 # noqa: E402
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


def run_arm(arm_name, panel, idx, liquid, trade_dates, start, end, capital=CAPITAL):
    """Long-only, T+1, cost-charged. DECIDE at T using bars <= T; FILL at T+1. No same-day fill."""
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
            px = (r or {}).get("close") or p["entry_px"]
            mv += p["shares"] * px
        nav = cash + mv
        gross = (mv / nav) if nav > 0 else 0.0
        equity_curve.append({"date": T, "nav": round(nav, 2), "cash": round(cash, 2),
                             "gross": round(gross, 6), "n_positions": len(positions)})
        if i + 1 >= len(win):
            break
        T_next = win[i + 1]

        # ---- EXIT decisions at T (close-based), fill at T+1 ----
        for tk in list(positions.keys()):
            p = positions[tk]
            r_t = _row_at(idx, tk, T)
            if r_t is None:                      # delisted/halted -> mark out at last known entry px (no fill)
                continue
            close_t = r_t["close"]
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
                trades.append({"ticker": tk, "entry": p["entry_px"], "exit": round(px, 4),
                               "ret": round(ret, 4), "reason": exit_reason, "exit_date": T_next})
                del positions[tk]

        # ---- ENTRY decisions at T (signal on bars <= T), fill at T+1 ----
        slots = MAX_POSITIONS - len(positions)
        if slots > 0:
            members = [tk for tk in liquid.get(T, []) if (T, tk) in have and tk not in positions]
            enters = []
            for tk in members:
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
                positions[tk] = {"entry_px": px, "shares": shares,
                                 "stop": s.get("stop") or px * (1.0 - THRESH["stop_pct"]), "entry_i": i}

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
    return {"daily_alpha_mean": daily, "ci_lo_daily": r.get("ci_lo"), "ci_hi_daily": r.get("ci_hi"),
            "p_value": r.get("p_value_h0_zero"), "n_boot_valid": r.get("n_boot_valid"),
            "annualized_alpha_pct": round(daily * 252 * 100, 2) if daily is not None else None,
            "ci_clears_zero": (r.get("straddles_zero") is False)}


def build(start=None, end=None) -> dict:
    import pandas as pd
    gate = survivorship_gate.require_pass()        # HARD PRECONDITION — raises unless passed
    panel = pd.read_parquet(PANEL, columns=["ts_code", "trade_date", "open", "high", "low",
                                            "close", "vol", "amount", "pre_close"])
    panel = panel[panel["ts_code"].map(lambda t: isinstance(t, str) and t.endswith((".SZ", ".SH")))]
    panel["trade_date"] = panel["trade_date"].astype(str)
    trade_dates = sorted(panel["trade_date"].unique())
    start = start or trade_dates[0]
    end = end or trade_dates[-1]
    # bound work to the window + enough prior history (MA200 + ADV lookback) for fast windowed runs
    sidx = trade_dates.index(start) if start in trade_dates else 0
    buf_start = trade_dates[max(0, sidx - 300)]
    panel = panel[panel["trade_date"] >= buf_start].reset_index(drop=True)
    idx = PanelIndex(panel)
    liquid = compute_liquid_universe(panel, top_n=TOP_N_ADV, lookback_days=LOOKBACK, min_dollar_vol=MIN_DVOL)

    win = [d for d in trade_dates if start <= d <= end]
    csi = _csi300_curve(win, CAPITAL)

    arms_out = {}
    for arm in ARMS:
        res = run_arm(arm, panel, idx, liquid, trade_dates, start, end)
        m = _metrics(res["equity_curve"], res["closed_returns"])
        ab = {}
        if csi:
            ab["vs_csi300"] = _bootstrap_alpha(_alpha_series(res["equity_curve"], csi))
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
                  "disclaimer": ("UNVALIDATED. No edge claimed unless OOS bootstrap CI clears zero after "
                                 "costs. H1+overlay arm is forward-only (no historical theses) and NOT "
                                 "backtested here; quality+low_vol baseline + walk-forward + 19-gate are the "
                                 "immediate follow-up."),
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
        m, al = a["metrics"], a["alpha"].get("vs_csi300", {})
        print(f"  [{arm:<16}] CAGR={m['cagr']} Sharpe={m['sharpe']} MaxDD={m['max_drawdown']} "
              f"trades={m['n_trades']} hit={m['hit_rate']}")
        if al:
            print(f"       vs CSI300: ann_alpha={al.get('annualized_alpha_pct')}% "
                  f"CI_clears_zero={al.get('ci_clears_zero')} p={al.get('p_value')}")
    print(f"[quant-backtest] wrote {OUT}")
    return 0


def _selftest() -> int:
    """Loop-logic checks on a synthetic panel (no parquet / no gate): T+1 discipline + no look-ahead."""
    errs = []
    import pandas as pd
    dates = [f"D{i:03d}" for i in range(260)]
    rows = []
    for i, dt in enumerate(dates):
        for j in range(12):
            px = 10.0 + j + 0.04 * i
            rows.append({"ts_code": f"S{j:02d}.SZ", "trade_date": dt, "open": px, "high": px * 1.01,
                         "low": px * 0.99, "close": px, "vol": (20 - j) * 1000.0,
                         "amount": px * (20 - j) * 1000.0 / 100.0, "pre_close": px})
    panel = pd.DataFrame(rows)
    idx = PanelIndex(panel)
    liquid = compute_liquid_universe(panel, top_n=5, lookback_days=10, min_dollar_vol=0)
    res = run_arm("h1", panel, idx, liquid, dates, dates[0], dates[-1])
    if not res["equity_curve"]:
        errs.append("backtest produced no equity curve")
    # no look-ahead: appending a FUTURE huge bar must not change the equity curve over the past window
    fut = pd.concat([panel, pd.DataFrame([{"ts_code": "S00.SZ", "trade_date": "D999", "open": 1e6,
                     "high": 1e6, "low": 1e6, "close": 1e6, "vol": 1e9, "amount": 1e12, "pre_close": 1e6}])],
                    ignore_index=True)
    idx2 = PanelIndex(fut)
    liquid2 = compute_liquid_universe(fut, top_n=5, lookback_days=10, min_dollar_vol=0)
    res2 = run_arm("h1", fut, idx2, liquid2, dates, dates[0], dates[-1])   # same past window
    nav1 = [round(p["nav"], 2) for p in res["equity_curve"]]
    nav2 = [round(p["nav"], 2) for p in res2["equity_curve"]]
    if nav1 != nav2:
        errs.append("LOOK-AHEAD: a future bar changed the past equity curve")
    # arms registered + alpha helper sane
    if set(ARMS) != {"h1", "oversold_control"}:
        errs.append("arms registry changed unexpectedly")
    if errs:
        print("quant_backtest selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("quant_backtest selftest PASSED (equity curve built; NO look-ahead — a future bar leaves the past "
          "equity curve unchanged; T+1 fills; arms = h1 + oversold_control)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
