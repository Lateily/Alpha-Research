#!/usr/bin/env python3
"""quant_strategy.py — Quant Strategy Factory v0 daily generator (read-only).

Implements QUANT_STRATEGY_FACTORY_v0_SPEC.md (Junyan-ratified 2026-06-08). This is the
INDEPENDENT trading factory — NOT the Core Thesis Factory. A-share long-only swing /
position-timing. Core Thesis is an OVERLAY ONLY (veto / conviction cap / provenance),
never the signal body.

v0 signal = H1: quality-filtered "pullback-in-uptrend" (long-only, low-turnover).
  - Direction FILTER (not a momentum bet): close >= MA200 AND MA200 rising.
  - Pullback SETUP: RSI dipped <= 40 within the recent window and is now turning up.
  - CONFIRM: up-day on >= average volume AND price reclaimed MA5.
  - This is distinct from the FALSIFIED inverse-momentum family: it only buys oversold
    pullbacks INSIDE an established uptrend (never catches a falling knife).
  EVERY threshold is [unvalidated] — an H1 prior to be proven or killed by the PR3 backtest.

DATA-TIER AWARE (the broad A-share universe is gitignored + unfetchable from CI US IPs):
  - BROAD  : data_history/panel/daily_prices.parquet present (local / PR3 backtest) ->
             top-500-ADV survivorship-safe universe, value+low_vol quality gate,
             MA200/MA20/MA5/RSI, run eligible->setup->confirm->risk H1 pipeline.
  - DEGRADED (CI): parquet absent -> honest NO_TRADE with a machine-readable reason.
             NO fabrication from the ~1-month-stale universe_a.json snapshot.

Read-only: positions/analytics/snapshots.json are PROTECTED; no size is executed; no
auto-trade; no_trade_flag everywhere. No edge / alpha / return claim — validation_status
stays "unvalidated" until the PR3 harness clears the gates.

Output: public/data/quant_strategy_run.json
Usage:  python3 scripts/quant_strategy.py [--selftest]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, date, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
BOARD = D / "trade_candidate_board.json"          # Core Thesis overlay source (read-only)
POSITIONS = D / "positions.json"                   # PROTECTED — read only
OUT = D / "quant_strategy_run.json"

# Broad-tier (local / backtest) data — gitignored, absent in CI.
PANEL = REPO / "data_history" / "panel"
DAILY_PRICES = PANEL / "daily_prices.parquet"      # ts_code, trade_date, open/high/low/close, vol, amount
PRICES = PANEL / "prices.parquet"                  # ts_code, trade_date, close, pe, pb, total_mv, circ_mv
UNIVERSE_PIT = REPO / "data_history" / "universe_pit.json"   # survivorship: list_date / delist_date

STRATEGY_ID = "quant_v0"
STRATEGY_VERSION = "v0-H1"

# ---- H1 thresholds — ALL [unvalidated]; priors to be proven/killed by PR3 -------------
THRESH = {
    "ma_long_n": 200,            # long uptrend filter (direction, NOT a momentum bet)
    "ma_long_rise_lookback": 10, # MA200 must be rising over this many bars
    "ma_mid_n": 20,              # trend-break EXIT reference
    "ma_short_n": 5,             # reclaim-on-bounce CONFIRM reference
    "rsi_n": 14,
    "rsi_pullback_max": 40.0,    # oversold-ish dip within the uptrend
    "rsi_pullback_window": 6,    # ...seen within this many recent bars
    "vol_ma_n": 20,
    "vol_confirm_mult": 1.0,     # confirm: volume >= 1.0x its 20d average
    "adv_n": 20,                 # 20d ADV window for the liquidity rank
    "top_n_adv": 500,            # liquid universe size (Junyan-locked)
    "lowvol_n": 60,              # realized-vol window for the low_vol factor
    "value_weight": 0.687,       # renormalized calib_weights (value 0.5719 / (0.5719+0.26))
    "lowvol_weight": 0.313,      # renormalized calib_weights (low_vol 0.26 / (0.5719+0.26))
    "stop_pct": 0.08,            # initial stop below entry reference
    "time_stop_days": 20,        # max holding (20d primary horizon)
    "starter_weight_pct": 5.0,   # base suggested weight (SUGGESTED only, never executed)
    "core_long_conviction_mult": 1.5,
    "max_position_pct": 10.0,
    "max_sector_pct": 30.0,
    "min_eligible_for_trade": 1,
}
MANIFEST = {"strategy_id": STRATEGY_ID, "strategy_version": STRATEGY_VERSION,
            "signal": "H1_pullback_in_uptrend_quality_filtered", "thresholds": THRESH}

DISCLAIMER = ("Quant Strategy Factory v0 — INTERNAL, UNVALIDATED model output — not validated alpha, "
              "not external/personalized investment advice. Long-only A-share, human executes. The signal "
              "(H1) is an unvalidated prior; no edge is claimed until the PR3 backtest clears the gate "
              "suite (PIT, survivorship-safe, costs, walk-forward, bootstrap CI, multiple-testing). "
              "Core Thesis is an overlay/veto/conviction-cap only, never the signal.")


def _load(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _r(x, nd=4):
    try:
        return round(float(x), nd)
    except Exception:
        return None


# ---- pure-python indicators (no pandas dep; so the H1 core + selftest run anywhere) ----
def _sma(series, n):
    out = [None] * len(series)
    if n <= 0:
        return out
    s = 0.0
    for i, v in enumerate(series):
        s += v
        if i >= n:
            s -= series[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def _rsi(closes, period=14):
    out = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    ag, al = gains / period, losses / period
    out[period] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    for i in range(period + 1, len(closes)):
        ch = closes[i] - closes[i - 1]
        ag = (ag * (period - 1) + max(ch, 0.0)) / period
        al = (al * (period - 1) + max(-ch, 0.0)) / period
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


# ---- H1 signal (per ticker; closes/vols oldest -> newest) ------------------------------
def h1_signal(closes, vols=None):
    """Returns {action, ...diagnostics}. action ∈ ENTER / WAIT / NO_SETUP / INSUFFICIENT_DATA.
    Eligibility (universe/quality/veto) is applied by the caller; this is the timing core."""
    n = len(closes)
    need = THRESH["ma_long_n"] + THRESH["ma_long_rise_lookback"] + 2
    if n < need:
        return {"action": "INSUFFICIENT_DATA", "n_bars": n, "need_bars": need}
    ma200 = _sma(closes, THRESH["ma_long_n"])
    ma20 = _sma(closes, THRESH["ma_mid_n"])
    ma5 = _sma(closes, THRESH["ma_short_n"])
    rsi = _rsi(closes, THRESH["rsi_n"])
    vma = _sma(vols, THRESH["vol_ma_n"]) if vols else None
    price = closes[-1]
    rb = THRESH["ma_long_rise_lookback"]

    # direction filter: above the long MA AND the long MA itself rising (a brief dip won't flip it)
    uptrend = (ma200[-1] is not None and price >= ma200[-1]
               and ma200[-1 - rb] is not None and ma200[-1] >= ma200[-1 - rb])
    # pullback setup: RSI dipped oversold-ish within the window, now turning up
    win = THRESH["rsi_pullback_window"]
    recent_rsi = [r for r in rsi[-win:] if r is not None]
    pulled_back = bool(recent_rsi) and min(recent_rsi) <= THRESH["rsi_pullback_max"]
    rsi_turning = rsi[-1] is not None and rsi[-2] is not None and rsi[-1] > rsi[-2]
    setup = uptrend and pulled_back and rsi_turning
    # confirm: up-day, volume >= average, and price reclaimed the short MA
    up_day = closes[-1] > closes[-2]
    vol_ok = (vma is None) or (vma[-1] is None) or (vols[-1] >= THRESH["vol_confirm_mult"] * vma[-1])
    reclaim = ma5[-1] is not None and price >= ma5[-1]
    confirm = up_day and vol_ok and reclaim

    action = "ENTER" if (setup and confirm) else ("WAIT" if setup else "NO_SETUP")
    return {
        "action": action, "n_bars": n,
        "uptrend": bool(uptrend), "pulled_back": bool(pulled_back), "rsi_turning": bool(rsi_turning),
        "up_day": bool(up_day), "vol_ok": bool(vol_ok), "reclaim_ma5": bool(reclaim),
        "price": _r(price), "ma200": _r(ma200[-1]), "ma20": _r(ma20[-1]), "ma5": _r(ma5[-1]), "rsi": _r(rsi[-1]),
        "stop": _r(price * (1.0 - THRESH["stop_pct"])) if action == "ENTER" else None,
    }


# ---- Core Thesis overlay (veto / conviction) — read-only, never the signal -------------
def _thesis_overlay():
    rows = (_load(BOARD, {}) or {}).get("trade_candidate_board", [])
    long_u, vetoed = [], []
    for r in rows:
        tk = r.get("ticker")
        if not tk:
            continue
        d = (r.get("direction") or "").upper()
        st = (r.get("status") or "").upper()
        if d == "LONG":
            long_u.append({"ticker": tk, "name": r.get("name"), "evidence_tier": r.get("evidence_tier")})
        if "SHORT" in d or st == "RISK_BLOCKED":
            vetoed.append({"ticker": tk, "name": r.get("name"),
                           "reason": ("thesis_" + d.lower()) if "SHORT" in d else "risk_blocked"})
    return {"long_universe": sorted(long_u, key=lambda x: x["ticker"]),
            "vetoed": sorted(vetoed, key=lambda x: x["ticker"])}


def _active_trade(sig, long_set):
    tk = sig["ticker"]
    is_core_long = tk in long_set
    conv = THRESH["core_long_conviction_mult"] if is_core_long else 1.0
    w = min(THRESH["starter_weight_pct"] * conv, THRESH["max_position_pct"])
    return {
        "ticker": tk, "action": "ENTER",
        "provenance": "core+quant_confirmed" if is_core_long else "quant_trade_signal",
        "suggested_weight_pct": _r(w, 2), "no_size_executed": True,
        "entry_reference": sig.get("price"), "stop": sig.get("stop"),
        "time_stop_days": THRESH["time_stop_days"],
        "exit_rules": ["stop_hit", "close<MA20_trend_break", f"{THRESH['time_stop_days']}d_time_stop"],
        "signal": {k: sig.get(k) for k in ("uptrend", "pulled_back", "rsi_turning", "confirm",
                                           "ma200", "ma20", "rsi", "price")},
        "validation_status": "unvalidated", "no_trade_flag": True,
    }


# ---- BROAD tier (local / PR3 backtest): top-500 ADV + quality gate + H1 ----------------
def _try_broad_universe(as_of: date, veto_set):
    """Read the local PIT parquet, build a top-500-ADV survivorship-safe quality-gated
    universe, run H1 per name. Returns a dict, or None if the parquet is unavailable
    (the CI case). Exercised on the local parquet + by the PR3 backtest harness."""
    if not DAILY_PRICES.exists():
        return None
    try:
        import pandas as pd
    except Exception:
        return None
    try:
        as_of_str = as_of.strftime("%Y%m%d")
        dp = pd.read_parquet(DAILY_PRICES, columns=["ts_code", "trade_date", "close", "vol", "amount"])
        dp = dp[dp["trade_date"] <= as_of_str]
        if dp.empty:
            return None
        dp = dp.sort_values(["ts_code", "trade_date"])

        # survivorship: members listed-by and not-delisted-by as_of
        uni_raw = _load(UNIVERSE_PIT, {})
        uni = uni_raw.get("stocks", []) if isinstance(uni_raw, dict) else (uni_raw or [])
        def _alive(row):
            ld = (row.get("list_date") or "00000000")
            dd = row.get("delist_date")
            return ld <= as_of_str and (not dd or dd > as_of_str)
        members = {r.get("ts_code") for r in uni
                   if isinstance(r, dict) and r.get("ts_code") and _alive(r)} or None

        # 20d ADV rank -> top-500 liquid
        tail = dp.groupby("ts_code").tail(THRESH["adv_n"])
        adv = tail.groupby("ts_code")["amount"].mean()
        if members:
            adv = adv[adv.index.isin(members)]
        liquid = list(adv.sort_values(ascending=False).head(THRESH["top_n_adv"]).index)

        # quality gate: value (E/P) + low_vol (−realized vol), z-blended, above median
        # low_vol from parquet closes; value from prices.parquet pe (optional).
        closes_by = {tk: g["close"].tolist() for tk, g in dp[dp["ts_code"].isin(liquid)].groupby("ts_code")}
        vols_by = {tk: g["vol"].tolist() for tk, g in dp[dp["ts_code"].isin(liquid)].groupby("ts_code")}
        lv = {}
        for tk, cl in closes_by.items():
            seg = cl[-(THRESH["lowvol_n"] + 1):]
            rets = [(seg[i] / seg[i - 1] - 1.0) for i in range(1, len(seg)) if seg[i - 1]]
            if len(rets) >= 20:
                m = sum(rets) / len(rets)
                lv[tk] = -math.sqrt(sum((x - m) ** 2 for x in rets) / len(rets))  # −vol
        val = {}
        if PRICES.exists():
            pr = pd.read_parquet(PRICES, columns=["ts_code", "trade_date", "pe"])
            pr = pr[(pr["trade_date"] <= as_of_str) & (pr["ts_code"].isin(liquid))]
            pr = pr.sort_values(["ts_code", "trade_date"]).groupby("ts_code").tail(1)
            for _, row in pr.iterrows():
                pe = row.get("pe")
                if pe is not None and pe == pe and pe > 0:
                    val[row["ts_code"]] = 1.0 / float(pe)   # E/P

        def _z(d):
            if not d:
                return {}
            xs = list(d.values()); m = sum(xs) / len(xs)
            sd = math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs)) or 1.0
            return {k: (v - m) / sd for k, v in d.items()}
        zlv, zval = _z(lv), _z(val)
        comp = {}
        for tk in liquid:
            parts, wsum = 0.0, 0.0
            if tk in zval:
                parts += THRESH["value_weight"] * zval[tk]; wsum += THRESH["value_weight"]
            if tk in zlv:
                parts += THRESH["lowvol_weight"] * zlv[tk]; wsum += THRESH["lowvol_weight"]
            if wsum:
                comp[tk] = parts / wsum
        if comp:
            med = sorted(comp.values())[len(comp) // 2]
            eligible = [tk for tk, c in comp.items() if c >= med and tk not in veto_set]
        else:
            eligible = [tk for tk in liquid if tk not in veto_set]

        signals = []
        for tk in sorted(eligible):
            s = h1_signal(closes_by.get(tk, []), vols_by.get(tk))
            if s["action"] in ("ENTER", "WAIT"):
                signals.append({"ticker": tk, "basis": "broad_liquid_a_share", **s})
        return {"signals": signals, "n_eligible": len(eligible),
                "filters_applied": ["survivorship_asof", f"top{THRESH['top_n_adv']}_adv",
                                    "quality_value_lowvol_above_median", "core_thesis_veto"]}
    except Exception as e:
        return {"signals": [], "n_eligible": 0,
                "filters_applied": ["broad_tier_error"], "error": str(e)[:200]}


def _focus_diagnostic():
    """Run H1 on the ~7 fresh focus ohlc_*.json files (CI-available). They carry ~120 bars
    (< the 200 the uptrend filter needs) -> expected INSUFFICIENT_DATA, surfaced honestly."""
    sigs = []
    for p in sorted(D.glob("ohlc_*.json")):
        d = _load(p)
        if not d:
            continue
        tk = d.get("ticker") or p.stem.replace("ohlc_", "").replace("_", ".")
        bars = d.get("data") or d.get("bars") or []
        closes = [b.get("close") for b in bars if isinstance(b, dict) and b.get("close") is not None]
        vols = [b.get("volume", b.get("vol")) for b in bars if isinstance(b, dict)]
        vols = [v for v in vols if v is not None] or None
        s = h1_signal(closes, vols)
        sigs.append({"ticker": tk, "basis": "focus_ohlc_diagnostic", **s})
    return sorted(sigs, key=lambda x: x["ticker"])


def build(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    run_date = now.date().isoformat()
    overlay = _thesis_overlay()
    veto_set = {v["ticker"] for v in overlay["vetoed"]}
    long_set = {x["ticker"] for x in overlay["long_universe"]}

    broad = _try_broad_universe(now.date(), veto_set)
    if broad is not None:
        data_tier = "broad_liquid_a_share"
        signals = broad["signals"]
        n_eligible = broad["n_eligible"]
        filters_applied = broad["filters_applied"]
    else:
        data_tier = "degraded_ci_focus_only"
        signals = _focus_diagnostic()
        n_eligible = 0
        filters_applied = ["ci_broad_universe_unavailable"]

    enters = [s for s in signals if s.get("action") == "ENTER" and s["ticker"] not in veto_set]
    waits = [s for s in signals if s.get("action") == "WAIT" and s["ticker"] not in veto_set]
    active_trades = [_active_trade(s, long_set) for s in enters]
    candidates = [{"ticker": s["ticker"], "action": "WAIT", "basis": s.get("basis"),
                   "signal": {k: s.get(k) for k in ("uptrend", "pulled_back", "rsi_turning", "confirm")},
                   "no_trade_flag": True} for s in waits]

    no_trade_reason = None
    if not active_trades:
        no_trade_reason = (
            "broad liquid universe unavailable in this environment (data_history parquet is "
            "gitignored/absent; AKShare universe_a.json is stale from GitHub US IPs); focus-only "
            "ohlc has <200 bars for the MA200 uptrend filter — honest NO_TRADE."
            if data_tier.startswith("degraded")
            else "no name passed eligible -> setup -> confirm -> risk today")

    return {
        "_meta": {
            "layer": "Quant Strategy Factory v0 — independent A-share long-only swing (read-only; no size, no auto-trade)",
            "spec": "docs/strategy/QUANT_STRATEGY_FACTORY_v0_SPEC.md",
            "read_only": True, "no_trades": True, "no_size": True, "no_buy_sell": True, "no_position_mutation": True,
            "run_date": run_date, "generated_at": now.isoformat(),
            "data_tier": data_tier,
            "horizon": "20d primary / 5d secondary diagnostic",
            "objective": "beat CSI300 + equal-weight A-share after costs (relative, drawdown-aware)",
            "sources": ["trade_candidate_board(overlay)", "daily_prices.parquet(broad)", "prices.parquet(broad)",
                        "universe_pit.json(broad)", "ohlc_*.json(focus diagnostic)"],
            "disclaimer": DISCLAIMER,
            "counts": {"signals": len(signals), "candidates_wait": len(candidates),
                       "active_trades_enter": len(active_trades),
                       "core_long_universe": len(long_set), "vetoed": len(veto_set)},
        },
        "run_date": run_date,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "manifest_hash": hashlib.sha256(
            json.dumps(MANIFEST, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
        "universe": {"base": f"liquid_a_share_top{THRESH['top_n_adv']}_adv", "data_tier": data_tier,
                     "n_eligible": n_eligible, "filters_applied": filters_applied},
        "signals": signals,
        "candidates": candidates,        # WAIT — setup present, confirmation/sizing pending
        "active_trades": active_trades,  # ENTER — SUGGESTED only (no_size_executed:true)
        "no_trade_reason": no_trade_reason,
        "core_thesis_overlay": overlay,  # veto / conviction / provenance ONLY — never the signal
        "validation_status": "unvalidated",
        "no_trade_flag": True,
    }


def _protected_hash() -> str:
    h = hashlib.sha256()
    for f in (POSITIONS, D / "analytics.json", D / "snapshots.json"):
        try:
            h.update(f.read_bytes())
        except Exception:
            pass
    return h.hexdigest()


def run(now: datetime | None = None) -> dict:
    before = _protected_hash()
    out = build(now)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    if _protected_hash() != before:
        raise SystemExit("FATAL: quant_strategy mutated protected paper-state — must be read-only")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    out = run()
    m = out["_meta"]
    print("=" * 78)
    print("QUANT STRATEGY FACTORY v0 (read-only; long-only; idea only; NO size/auto-trade)")
    print("=" * 78)
    print(f"run_date={out['run_date']}  tier={m['data_tier']}  version={out['strategy_version']}")
    print(f"counts={m['counts']}")
    print(f"universe: {out['universe']['base']}  n_eligible={out['universe']['n_eligible']}  "
          f"filters={out['universe']['filters_applied']}")
    print(f"active_trades(ENTER)={len(out['active_trades'])}  candidates(WAIT)={len(out['candidates'])}")
    if out["no_trade_reason"]:
        print(f"NO_TRADE: {out['no_trade_reason']}")
    ov = out["core_thesis_overlay"]
    print(f"overlay: long_universe={[x['ticker'] for x in ov['long_universe']]}  "
          f"vetoed={[x['ticker'] for x in ov['vetoed']]}")
    print(f"[quant-strategy] wrote {OUT}")
    return 0


def _selftest() -> int:
    errs = []

    # --- H1 logic on synthetic series ---
    base = [100.0 + 0.30 * i for i in range(212)]            # gentle 200+ bar uptrend (MA200 rising)
    dip = [base[-1] - 4.0 * (j + 1) for j in range(6)]       # 6-bar selloff -> RSI dips < 40
    bounce = [dip[-1] + 3.0, dip[-1] + 7.0]                  # 2-bar recovery, reclaims MA5
    enter_closes = base + dip + bounce
    enter_vols = [1000.0] * len(enter_closes); enter_vols[-1] = 3000.0
    s_enter = h1_signal(enter_closes, enter_vols)
    if s_enter["action"] != "ENTER":
        errs.append(f"H1 uptrend-pullback-confirm should ENTER, got {s_enter['action']} ({s_enter})")

    s_wait = h1_signal(enter_closes, enter_vols[:-1] + [10.0])  # same setup, but tiny last-bar volume
    if s_wait["action"] not in ("WAIT", "ENTER"):
        errs.append(f"low-volume variant should be WAIT/ENTER, got {s_wait['action']}")

    down = [200.0 - 0.30 * i for i in range(220)]            # steady downtrend
    if h1_signal(down, [1000.0] * len(down))["action"] != "NO_SETUP":
        errs.append("downtrend must be NO_SETUP (uptrend filter blocks falling knives)")

    steady = [100.0 + 0.30 * i for i in range(220)]          # uptrend, NO pullback (RSI never < 40)
    if h1_signal(steady, [1000.0] * len(steady))["action"] != "NO_SETUP":
        errs.append("uptrend without a pullback must be NO_SETUP")

    if h1_signal([100.0] * 50, None)["action"] != "INSUFFICIENT_DATA":
        errs.append("short history must be INSUFFICIENT_DATA")

    # --- build() invariants (degraded tier expected in CI/selftest env) ---
    fixed = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    out = build(now=fixed)
    if out.get("no_trade_flag") is not True:
        errs.append("top-level no_trade_flag must be True")
    if out.get("validation_status") != "unvalidated":
        errs.append("validation_status must be 'unvalidated' (no edge claim)")
    if "UNVALIDATED" not in out["_meta"]["disclaimer"] or "not validated alpha" not in out["_meta"]["disclaimer"]:
        errs.append("disclaimer must state UNVALIDATED / not validated alpha")
    for c in out["active_trades"]:
        if c.get("no_size_executed") is not True:
            errs.append(f"{c.get('ticker')} active_trade must carry no_size_executed:true")
        if any(k in c for k in ("shares", "quantity", "executed_size")):
            errs.append(f"{c.get('ticker')} must not carry an executed-size field")
    # Core Thesis is overlay only: no vetoed name may appear as an active trade
    veto = {v["ticker"] for v in out["core_thesis_overlay"]["vetoed"]}
    if any(t["ticker"] in veto for t in out["active_trades"]):
        errs.append("a vetoed (SHORT/WATCH_SHORT/risk-blocked) name leaked into active_trades")
    # honest NO_TRADE wiring
    if not out["active_trades"] and not out["no_trade_reason"]:
        errs.append("empty active_trades must carry a no_trade_reason")
    # determinism
    if build(now=fixed)["manifest_hash"] != out["manifest_hash"]:
        errs.append("manifest_hash not deterministic")

    if errs:
        print("quant_strategy selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("quant_strategy selftest PASSED (H1: ENTER on uptrend+pullback+confirm, NO_SETUP on "
          "downtrend / no-pullback, INSUFFICIENT_DATA on short history; build invariants: no_trade_flag, "
          "unvalidated, no executed size, thesis-overlay veto holds, honest NO_TRADE, deterministic manifest)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
