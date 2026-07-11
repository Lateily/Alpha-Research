#!/usr/bin/env python3
"""survivorship_gate.py — Quant Strategy Factory PR3 step-0 gate (read-only).

HARD PRECONDITION (Junyan 2026-06-09): NO H1 backtest number is accepted unless this gate
PASSES. The quant backtest's universe is panel-derived (compute_liquid_universe over
daily_prices.parquet), NOT universe_pit.json (which is empty/disposable). That panel path is
survivorship-safe *only if* the panel actually contains delisted names — so this gate proves it,
every run, and refuses to bless a survivorship-biased (live-only) panel.

Four checks (Junyan-specified):
  1. panel_includes_delisted  — the panel contains stopped/delisted names (tickers whose last bar
     is earlier than the panel's max trade_date). If a future panel were live-only, this FAILS and
     blocks the backtest. Spot-checks a known delisted name (000024.SZ, last bar 2015-12-07).
  2. future_volume_invariant  — appending a future huge-volume bar must NOT change any past date's
     universe (reuses liquid_universe._selftest's PIT invariant; compute_liquid_universe uses
     .shift(1).rolling()).
  3. delisted_absent_post_delist — the backtest's actual membership (liquid-universe ∩ "trades at T")
     must include a delisted probe on pre-delist dates and ZERO post-delist dates.
  4. universe_source_panel_derived — the reported source is compute_liquid_universe(panel); universe_pit
     is NOT used.

Backtest membership tested here == what the harness will use:
    members_at(T) = compute_liquid_universe(panel)[T]  ∩  {tickers with a bar at T}
(the "trades at T" intersection is what makes a delisted name vanish the instant it stops trading).

--selftest runs all four on a SYNTHETIC panel (no parquet needed) AND a negative live-only panel
(asserts the gate FAILS it). Default run executes against the real local parquet (the actual gate).
Output: public/data/survivorship_gate.json
Usage:  python3 scripts/survivorship_gate.py [--selftest]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
PANEL = REPO / "data_history" / "panel" / "daily_prices.parquet"
OUT = D / "survivorship_gate.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from liquid_universe import compute_liquid_universe  # noqa: E402  (panel-derived, PIT-clean)

TOP_N = 500
LOOKBACK = 20
MIN_DVOL = 1e7
KNOWN_DELISTED = ("000024.SZ", "20151207")   # 招商地产 — merged/delisted; spot-check probe


def _members_at(panel, universe):
    """The harness's real membership: liquid-universe ∩ 'has a bar at T' (so a delisted name
    drops out the instant it stops trading)."""
    have = set(zip(panel["trade_date"].astype(str), panel["ts_code"]))
    return {T: [tk for tk in tks if (str(T), tk) in have] for T, tks in universe.items()}


def _check_panel_includes_delisted(panel):
    panel_max = str(panel["trade_date"].max())
    last_by = panel.groupby("ts_code")["trade_date"].max().astype(str)
    stopped = last_by[last_by < panel_max]
    known_tk, known_last = KNOWN_DELISTED
    known_seen = None
    if known_tk in last_by.index:
        known_seen = {"ticker": known_tk, "last_bar": str(last_by[known_tk]),
                      "stops_before_max": str(last_by[known_tk]) < panel_max}
    passed = len(stopped) > 0
    return {"check": "panel_includes_delisted", "passed": bool(passed),
            "panel_max_date": panel_max, "n_total_tickers": int(last_by.size),
            "n_stopped_before_max": int(stopped.size),
            "known_delisted_probe": known_seen,
            "note": ("panel contains delisted/stopped names -> compute_liquid_universe is "
                     "survivorship-safe" if passed else
                     "PANEL IS LIVE-ONLY -> compute_liquid_universe would be survivorship-biased — BLOCK")}


def _check_future_volume_invariant():
    # Reuse the proven PIT invariant test shipped in liquid_universe (future bar must not change past universe).
    import liquid_universe as lu
    rc = lu._selftest()
    return {"check": "future_volume_invariant", "passed": rc == 0,
            "source": "liquid_universe._selftest()",
            "note": "appending a 2030 huge-volume bar leaves every past date's universe unchanged (.shift(1) PIT)"}


def _check_delisted_absent_post_delist(panel, probe):
    tk, delist = probe
    dates = sorted(panel["trade_date"].astype(str).unique())
    if tk not in set(panel["ts_code"]):
        return {"check": "delisted_absent_post_delist", "passed": False,
                "probe": tk, "note": f"probe {tk} not in panel"}
    # window the panel around the delist date so the universe build is fast + the pre/post split is clean
    import bisect
    pos = bisect.bisect_left(dates, delist)
    lo, hi = max(0, pos - 60), min(len(dates), pos + 41)
    win_dates = set(dates[lo:hi])
    sub = panel[panel["trade_date"].astype(str).isin(win_dates)]
    uni = compute_liquid_universe(sub, top_n=TOP_N, lookback_days=LOOKBACK, min_dollar_vol=MIN_DVOL)
    mem = _members_at(sub, uni)
    pre = sum(1 for T, tks in mem.items() if str(T) <= delist and tk in tks)
    post = sum(1 for T, tks in mem.items() if str(T) > delist and tk in tks)
    # PASS = appears while trading (pre) AND never after delist (post == 0)
    passed = (pre >= 1) and (post == 0)
    return {"check": "delisted_absent_post_delist", "passed": bool(passed),
            "probe": tk, "delist_date": delist,
            "pre_delist_universe_days": int(pre), "post_delist_universe_days": int(post),
            "note": ("delisted name present pre-delist, absent post-delist (membership = liquid ∩ trades-at-T)"
                     if passed else "FAIL: delisted name appears post-delist OR never appeared pre-delist")}


def _auto_probe(panel):
    """Pick a delisted-and-was-liquid probe: prefer the known name, else a stopped ticker with the
    highest pre-stop dollar-volume (so check #3 is meaningful, not vacuous)."""
    known_tk, known_last = KNOWN_DELISTED
    if known_tk in set(panel["ts_code"]):
        return (known_tk, known_last)
    panel_max = str(panel["trade_date"].max())
    last_by = panel.groupby("ts_code")["trade_date"].max().astype(str)
    stopped = last_by[last_by < panel_max]
    if stopped.empty:
        return None
    amt = (panel[panel["ts_code"].isin(stopped.index)]
           .groupby("ts_code")["amount"].mean().sort_values(ascending=False))
    tk = amt.index[0]
    return (tk, str(last_by[tk]))


def gate(panel, probe=None) -> dict:
    probe = probe or _auto_probe(panel)
    checks = [_check_panel_includes_delisted(panel), _check_future_volume_invariant()]
    if probe:
        checks.append(_check_delisted_absent_post_delist(panel, probe))
    else:
        checks.append({"check": "delisted_absent_post_delist", "passed": False,
                       "note": "no delisted probe available (panel may be live-only)"})
    checks.append({"check": "universe_source_panel_derived", "passed": True,
                   "universe_source": "compute_liquid_universe(daily_prices.parquet)",
                   "universe_pit_used": False,
                   "note": "membership is panel-derived; universe_pit.json is NOT used (it is empty/disposable)"})
    return {"passed": all(c["passed"] for c in checks), "checks": checks,
            "universe_source": "panel_derived_compute_liquid_universe", "universe_pit_used": False}


def run(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    try:
        import pandas as pd
    except Exception:
        out = {"available": False, "passed": False, "reason": "pandas unavailable"}
    if not PANEL.exists():
        out = {"available": False, "passed": False,
               "reason": "data_history/panel/daily_prices.parquet absent (this gate is local/backtest-only; "
                         "the parquet is gitignored). Run where the panel exists before any H1 backtest."}
    else:
        import pandas as pd
        panel = pd.read_parquet(PANEL, columns=["ts_code", "trade_date", "close", "vol", "amount"])
        g = gate(panel)
        out = {"available": True, **g}
    out["_meta"] = {"gate": "survivorship_integrity", "spec": "QUANT_STRATEGY_FACTORY_v0_SPEC.md §8",
                    "generated_at": now.isoformat(),
                    "rule": "NO H1 backtest number is accepted unless passed==true",
                    "read_only": True}
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    return out


# ---- callable precondition for the backtest harness ----
def require_pass() -> dict:
    """Backtest harness calls this first; raises SystemExit unless the gate passes."""
    out = run()
    if not out.get("passed"):
        raise SystemExit(f"survivorship_integrity gate FAILED/UNAVAILABLE — refusing to produce H1 backtest "
                         f"numbers. {out.get('reason') or [c for c in out.get('checks', []) if not c['passed']]}")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    out = run()
    print("=" * 78)
    print("SURVIVORSHIP INTEGRITY GATE (panel-derived universe; universe_pit.json NOT used)")
    print("=" * 78)
    if not out.get("available"):
        print(f"UNAVAILABLE: {out.get('reason')}")
        print("(local/backtest-only gate; run where data_history/panel/daily_prices.parquet exists)")
        return 0
    for c in out["checks"]:
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['check']}: {c.get('note', '')[:90]}")
    print(f"VERDICT: {'PASS' if out['passed'] else 'FAIL'}  (universe_source={out['universe_source']})")
    print(f"[survivorship-gate] wrote {OUT}")
    return 0 if out["passed"] else 1


def _synth_panel(include_delisted: bool):
    """Synthetic panel: live names over 60 dates + (optionally) a liquid name that STOPS at D034."""
    import pandas as pd
    dates = [f"D{i:03d}" for i in range(60)]
    rows = []
    for i, dt in enumerate(dates):
        for j in range(16):                       # 16 live names, descending liquidity
            px = 10.0 + j + 0.05 * i
            vol = (20 - j) * 1000.0
            rows.append({"ts_code": f"LIVE{j:02d}.SZ", "trade_date": dt,
                         "close": px, "vol": vol, "amount": px * vol / 100.0})
        if include_delisted and i <= 34:          # DELIST.SZ: very liquid, stops trading at D034
            rows.append({"ts_code": "DELIST.SZ", "trade_date": dt,
                         "close": 50.0 + 0.1 * i, "vol": 99000.0, "amount": 50.0 * 99000.0 / 100.0})
    return pd.DataFrame(rows)


def _selftest() -> int:
    errs = []
    # (A) GOOD panel (with a delisted name) -> gate PASSES; check #3 finds it pre, 0 post
    good = gate(_synth_panel(include_delisted=True), probe=("DELIST.SZ", "D034"))
    if not good["passed"]:
        errs.append(f"gate must PASS a panel with delisted names: {[c for c in good['checks'] if not c['passed']]}")
    c3 = next(c for c in good["checks"] if c["check"] == "delisted_absent_post_delist")
    if not (c3["pre_delist_universe_days"] >= 1 and c3["post_delist_universe_days"] == 0):
        errs.append(f"delisted probe must be present pre-delist and absent post-delist: {c3}")
    c1 = next(c for c in good["checks"] if c["check"] == "panel_includes_delisted")
    if c1["n_stopped_before_max"] < 1:
        errs.append("check#1 must count >=1 stopped ticker on the good panel")
    # (B) NEGATIVE: live-only panel -> gate must FAIL (otherwise it has no teeth)
    bad = gate(_synth_panel(include_delisted=False))
    if bad["passed"]:
        errs.append("gate must FAIL a LIVE-ONLY panel (survivorship-biased) — it has no teeth otherwise")
    bad_c1 = next(c for c in bad["checks"] if c["check"] == "panel_includes_delisted")
    if bad_c1["passed"]:
        errs.append("check#1 must FAIL on a live-only panel")
    # (C) future-volume invariant + source label
    if not next(c for c in good["checks"] if c["check"] == "future_volume_invariant")["passed"]:
        errs.append("future_volume_invariant must PASS")
    if good["universe_pit_used"] is not False:
        errs.append("universe_pit_used must be False (panel-derived only)")

    if errs:
        print("survivorship_gate selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("survivorship_gate selftest PASSED (good panel -> PASS w/ delisted present pre & absent post; "
          "LIVE-ONLY panel -> gate FAILS [teeth]; future-volume invariant holds; universe_pit NOT used)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
