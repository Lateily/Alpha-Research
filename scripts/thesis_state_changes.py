#!/usr/bin/env python3
"""
thesis_state_changes.py — P1.1 read-only daily state-change table for the forward court.

Tracks STATE DELTAS for the registered forward court (status ACTIVE in the checkpoint ledger)
plus the 002130 deep-thesis candidate (marked candidate_not_registered). It is strictly
read-only and advisory:

  - it NEVER rewrites a thesis, writes the ledger, advances a stance, or emits a trade;
  - a WATCH name is NEVER auto-promoted to STARTER — stance fields are the REGISTERED stance, verbatim;
  - every actionable conclusion is a SIGNAL flag, not a decision.

Per name it surfaces:
  - price vs the valuation band + the band-derived 2:1 research trigger;
  - wrong-if proximity, split by basis:
      * price / market-data based  → auto distance from the current price;
      * disclosure / financial based → pending_human_check_at_date ONLY (never judged on missing data);
  - catalyst countdown (days to the next checkpoint + the next catalyst);
  - data freshness (DATA_BLOCKED-aware: a stale snapshot suppresses every price-based signal);
  - a stance-change SIGNAL (R/R recomputed at the current price vs the 2:1 bar) — a flag, never a change.

Signals: PRICE_ENTERED_RESEARCH_ZONE · RR_CROSSED_2TO1_FLAG · RISK_TRIGGER_NEEDS_HUMAN_CHECK · DATA_BLOCKED.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone, date
from pathlib import Path

from universe_data_health import audit_universe

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "public" / "data"
LEDGER = D / "decision_sheet_checkpoints.json"
UNIVERSE = D / "universe_a.json"
OUT = D / "thesis_state_changes.json"
RR_BAR = 2.0
MAX_AGE_DAYS = 2  # inherited from the DATA_BLOCKED gate (#89/#90)

# metric keywords that make a wrong-if PRICE / market-data based (auto-computable);
# anything else is disclosure/financial → pending_human_check_at_date only.
_PRICE_KEYS = ("price", "股价", "价格", "收盘", "close", "技术位", "均线", "ma(", " ma ",
               "跌破", "突破", "break", "turnover", "成交额", "成交量", "volume", "amplitude")

# The single deep-thesis candidate (NOT registered — excluded from the official ACTIVE count).
# Parameters mirror docs/research/decision_sheets/002130_SZ_DEEP_2026-06-17.md (RED-TEAM PENDING).
CANDIDATES = {
    "002130.SZ": {
        "name": {"zh": "沃尔核材", "en": "Woer"},
        "stance": "WATCH_DEEP_VALUE (candidate, RED-TEAM PENDING)",
        "reference_price": 20.63,
        "band": {"bear": {"low": 13.6, "high": 13.6}, "base": {"low": 20.5, "high": 20.5},
                 "bull": {"low": 31.8, "high": 31.8}},
        "wrong_if": [
            {"metric": "high-speed comms line FY26 revenue", "threshold": "< 12-13亿", "check_date": "2026-08-31"},
            {"metric": "consolidated gross margin", "threshold": "< 31%", "check_date": "2026-08-31"},
            {"metric": "归母净利 YoY", "threshold": "still declining", "check_date": "2026-08-31"},
            {"metric": "CPO/optical substitution of copper interconnect", "threshold": "accelerates", "check_date": "rolling"},
        ],
        "catalysts": [{"date": "2026-08-31", "event": "2026 H1 报告 (high-speed line revenue + consolidated GM)"}],
        "source": "docs/research/decision_sheets/002130_SZ_DEEP_2026-06-17.md",
    }
}


def _to_float(v):
    if v is None or v == "":
        return None
    if isinstance(v, str):
        v = v.replace(",", "").replace("%", "").strip()
        if not v or v in {"--", "-", "None", "nan", "NaN"}:
            return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f


def _load(p: Path, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _days_to(s, as_of: date):
    d = _parse_date(s)
    return (d - as_of).days if d else None


def _band_position(px, band):
    try:
        bl, bh = band["bear"]["low"], band["bear"]["high"]
        sl, sh = band["base"]["low"], band["base"]["high"]
        ul, uh = band["bull"]["low"], band["bull"]["high"]
    except (KeyError, TypeError):
        return "UNKNOWN"
    if px < bl: return "BELOW_BEAR"
    if px <= bh: return "IN_BEAR_BAND"
    if px < sl: return "BEAR_TO_BASE"
    if px <= sh: return "IN_BASE_BAND"
    if px < ul: return "BASE_TO_BULL"
    if px <= uh: return "IN_BULL_BAND"
    return "ABOVE_BULL"


def _rr_and_trigger(band, px):
    """R/R at px + the price where R/R == 2:1 (the band-derived research trigger)."""
    try:
        bull_mid = (band["bull"]["low"] + band["bull"]["high"]) / 2.0
        bear_mid = (band["bear"]["low"] + band["bear"]["high"]) / 2.0
    except (KeyError, TypeError):
        return None, None
    trigger = round((bull_mid + RR_BAR * bear_mid) / (1 + RR_BAR), 2)
    rr = round((bull_mid - px) / (px - bear_mid), 2) if (px is not None and px > bear_mid) else None
    return rr, trigger


def _classify_wrong_if(metric: str) -> str:
    m = (metric or "").lower()
    return "price" if any(k in m for k in _PRICE_KEYS) else "disclosure"


def _state_row(rec, tier, current_px, fresh_verdict, snapshot_date, price_date, as_of):
    blocked = fresh_verdict == "BLOCKED"
    band = rec.get("band") or {}
    ref = _to_float(rec.get("reference_price"))
    signals = []
    if blocked:
        signals.append("DATA_BLOCKED")

    # price-based block — suppressed entirely when the snapshot is stale (untrusted price)
    rr, trigger = _rr_and_trigger(band, current_px)
    if blocked or current_px is None:
        price_block = {"current": current_px, "reference_price": ref, "trusted": False,
                       "note": "price suppressed — stale/blocked universe snapshot" if blocked else "no current price"}
    else:
        entered = trigger is not None and current_px <= trigger
        if entered:
            signals += ["PRICE_ENTERED_RESEARCH_ZONE", "RR_CROSSED_2TO1_FLAG"]
        price_block = {
            "current": current_px, "reference_price": ref,
            "chg_vs_reference_pct": round((current_px - ref) / ref * 100, 1) if ref else None,
            "band_position": _band_position(current_px, band),
            "rr_at_current": rr, "rr_2to1_trigger_price": trigger,
            "entered_research_zone": bool(entered), "trusted": True,
        }

    # wrong-if: split by basis (price → auto distance; disclosure → pending human check)
    wrong_if = []
    for t in (rec.get("wrong_if") or []):
        basis = _classify_wrong_if(t.get("metric", ""))
        item = {"metric": t.get("metric"), "threshold": t.get("threshold"), "basis": basis}
        if basis == "price" and not blocked and current_px is not None:
            thr = _to_float(t.get("threshold"))
            item["distance_pct"] = (round((current_px - thr) / thr * 100, 1)
                                    if thr else None)
            item["note"] = "price-based — auto distance from current price"
        else:
            item["pending_human_check_at_date"] = t.get("check_date") or "pending"
            item["note"] = "disclosure/financial — resolved only by the filed report; not judged on missing data"
            signals.append("RISK_TRIGGER_NEEDS_HUMAN_CHECK")
        wrong_if.append(item)

    # catalyst countdown
    cps = rec.get("checkpoints") or []
    next_cp = next((c.get("due_date") for c in cps if c.get("status") == "PENDING"), None)
    def _future(c):
        d = _days_to(c.get("date"), as_of)
        return d is not None and d >= 0          # next catalyst = nearest FUTURE/today (not a past date)
    cats = [c for c in (rec.get("catalysts") or []) if _future(c)]
    next_cat = min(cats, key=lambda c: _days_to(c.get("date"), as_of), default=None)

    return {
        "ticker": rec.get("ticker"),
        "name": rec.get("name"),
        "tier": tier,                                   # "ACTIVE" | "candidate_not_registered"
        "stance": rec.get("stance_at_registration") or rec.get("stance"),  # REGISTERED stance, verbatim
        "stance_note": "state generator never changes stance — WATCH is never auto-promoted to STARTER",
        "data_freshness": {"verdict": fresh_verdict, "snapshot_date": snapshot_date, "price_date": price_date},
        "price": price_block,
        "wrong_if": wrong_if,
        "catalysts": {
            "next_checkpoint_due": next_cp, "days_to_checkpoint": _days_to(next_cp, as_of),
            "next_catalyst_date": (next_cat or {}).get("date") if next_cat else None,
            "days_to_catalyst": _days_to((next_cat or {}).get("date"), as_of) if next_cat else None,
            "next_catalyst_event": (next_cat or {}).get("event") if next_cat else None,
        },
        "signals": sorted(set(signals)),
    }


def build(ledger: dict, universe: dict, *, as_of: date, max_age_days: int = MAX_AGE_DAYS) -> dict:
    as_of_dt = datetime(as_of.year, as_of.month, as_of.day, tzinfo=timezone.utc)
    health = audit_universe(universe, as_of=as_of_dt, max_age_days=max_age_days, tickers=[])
    fresh_verdict = health.get("verdict")
    snapshot_date = (universe.get("_meta") or {}).get("fetched_at")
    by_ticker = {r.get("ticker"): r for r in (universe.get("stocks") or [])}

    rows, n_active = [], 0
    for rec in (ledger.get("registrations") or []):
        if rec.get("status") != "ACTIVE":
            continue
        n_active += 1
        urow = by_ticker.get(rec.get("ticker")) or {}
        rows.append(_state_row(rec, "ACTIVE", _to_float(urow.get("price")), fresh_verdict,
                               snapshot_date, urow.get("trade_date"), as_of))
    for ticker, cand in CANDIDATES.items():
        urow = by_ticker.get(ticker) or {}
        rec = {"ticker": ticker, **cand}
        rows.append(_state_row(rec, "candidate_not_registered", _to_float(urow.get("price")),
                               fresh_verdict, snapshot_date, urow.get("trade_date"), as_of))

    return {
        "_meta": {
            "tool": "thesis_state_changes.py (P1.1) — read-only daily state deltas; never trades, registers, or changes stance",
            "as_of": as_of.isoformat(),
            "universe_fetched_at": snapshot_date,
            "universe_freshness": fresh_verdict,
            "n_active": n_active,                       # official forward court ONLY (candidates excluded)
            "n_candidates": len(CANDIDATES),
        },
        "rows": rows,
    }


def _render(rep: dict) -> str:
    m = rep["_meta"]
    L = [f"# Forward-court state changes · {m['as_of']}  (universe {m['universe_freshness']})",
         f"- official ACTIVE: {m['n_active']} · candidates (not in court): {m['n_candidates']}", ""]
    for r in rep["rows"]:
        p = r["price"]
        head = f"## {r['ticker']} {((r.get('name') or {}).get('zh') if isinstance(r.get('name'), dict) else r.get('name')) or ''} [{r['tier']}]"
        L.append(head)
        L.append(f"- stance (registered, unchanged): {r['stance']}")
        if p.get("trusted"):
            L.append(f"- price {p['current']} ({p.get('chg_vs_reference_pct')}% vs ref {p['reference_price']}) "
                     f"· {p['band_position']} · R/R {p['rr_at_current']} (2:1 trigger ≤{p['rr_2to1_trigger_price']})")
        else:
            L.append(f"- price: {p.get('note')}")
        cat = r["catalysts"]
        def _fmt(dt, dd):
            return f"{dt} ({dd}d)" if dt else "—"
        L.append(f"- next checkpoint: {_fmt(cat['next_checkpoint_due'], cat['days_to_checkpoint'])} · "
                 f"next catalyst: {_fmt(cat['next_catalyst_date'], cat['days_to_catalyst'])}")
        L.append(f"- signals: {r['signals'] or '—'}")
        L.append("")
    return "\n".join(L)


def _selftest() -> int:
    errs = []
    as_of = date(2026, 6, 19)
    defs = {"field_definitions": {"pe": {"basis": "x"}}, "factor_definitions": {"momentum": {"basis": "12-1"}}}

    def uni(fetched_at, rows):
        return {"_meta": {"fetched_at": fetched_at, "count": len(rows), **defs}, "stocks": rows}

    active = {"ticker": "688008.SH", "status": "ACTIVE", "name": {"zh": "澜起", "en": "M"},
              "stance_at_registration": "WATCH_NOT_CONVICTION",
              "reference_price": 150.0,
              "band": {"bear": {"low": 95, "high": 115}, "base": {"low": 145, "high": 170}, "bull": {"low": 225, "high": 260}},
              "wrong_if": [{"metric": "H1 segment gross margin", "threshold": "≤ 16.5%", "check_date": "2026-08-31"}],
              "catalysts": [{"date": "2026-08-31", "event": "H1"}],
              "checkpoints": [{"due_date": "2026-07-14", "status": "PENDING"}]}
    ledger = {"registrations": [active, {"ticker": "X.SZ", "status": "SUPERSEDED"}]}
    fresh = uni(as_of.isoformat(), [{"ticker": "688008.SH", "price": 150.0, "trade_date": "20260619"},
                                    {"ticker": "002130.SZ", "price": 20.63, "trade_date": "20260619"}])

    rep = build(ledger, fresh, as_of=as_of)
    # (1) ACTIVE name emits a normal row; (2) candidate not in the official count
    if rep["_meta"]["n_active"] != 1:
        errs.append("n_active must count ACTIVE only (1) — SUPERSEDED excluded")
    tickers = {r["ticker"]: r for r in rep["rows"]}
    if "688008.SH" not in tickers or tickers["688008.SH"]["tier"] != "ACTIVE":
        errs.append("ACTIVE name must produce a row")
    if "002130.SZ" not in tickers or tickers["002130.SZ"]["tier"] != "candidate_not_registered":
        errs.append("002130 must appear as candidate_not_registered")
    if rep["_meta"]["n_candidates"] != 1 or rep["_meta"]["n_active"] == 2:
        errs.append("candidate must NOT inflate the official ACTIVE count")
    # (5) disclosure wrong-if → pending_human_check_at_date, never auto-triggered
    wi = tickers["688008.SH"]["wrong_if"][0]
    if wi["basis"] != "disclosure" or wi.get("pending_human_check_at_date") != "2026-08-31" or "distance_pct" in wi:
        errs.append("disclosure wrong-if must be pending_human_check_at_date with NO auto judgment")
    if "RISK_TRIGGER_NEEDS_HUMAN_CHECK" not in tickers["688008.SH"]["signals"]:
        errs.append("a disclosure wrong-if must raise RISK_TRIGGER_NEEDS_HUMAN_CHECK")

    # (4) price enters research zone → signal, stance UNCHANGED
    cheap = uni(as_of.isoformat(), [{"ticker": "688008.SH", "price": 120.0, "trade_date": "20260619"}])
    r2 = build(ledger, cheap, as_of=as_of)["rows"][0]   # 2:1 trigger = (242.5 + 2*105)/3 = 150.83; 120 ≤ it
    if "PRICE_ENTERED_RESEARCH_ZONE" not in r2["signals"]:
        errs.append("a price at/below the 2:1 trigger must raise PRICE_ENTERED_RESEARCH_ZONE")
    if r2["stance"] != "WATCH_NOT_CONVICTION":
        errs.append("stance must stay the registered WATCH — never auto-promoted")

    # (3) stale universe → DATA_BLOCKED and price-based signals suppressed
    stale = uni("2020-01-01T00:00:00", [{"ticker": "688008.SH", "price": 120.0, "trade_date": "20200101"}])
    r3 = build(ledger, stale, as_of=as_of)["rows"][0]
    if "DATA_BLOCKED" not in r3["signals"]:
        errs.append("a stale universe must raise DATA_BLOCKED")
    if r3["price"].get("trusted") is not False or "PRICE_ENTERED_RESEARCH_ZONE" in r3["signals"]:
        errs.append("DATA_BLOCKED must suppress price-based signals (untrusted price)")

    # price-based wrong-if DOES get an auto distance (the split works both ways)
    pb_ledger = {"registrations": [{**active, "wrong_if": [{"metric": "close price break", "threshold": "100", "check_date": "rolling"}]}]}
    rpb = build(pb_ledger, fresh, as_of=as_of)["rows"][0]["wrong_if"][0]
    if rpb["basis"] != "price" or "distance_pct" not in rpb:
        errs.append("a price-based wrong-if must auto-compute distance_pct")

    if errs:
        print("thesis_state_changes selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("thesis_state_changes selftest PASSED (ACTIVE row emitted; candidate_not_registered excluded from "
          "n_active; stale universe → DATA_BLOCKED + price signals suppressed; price ≤ 2:1 trigger → "
          "PRICE_ENTERED_RESEARCH_ZONE signal with stance UNCHANGED; disclosure wrong-if → pending_human_check, "
          "never auto-judged; price-based wrong-if → auto distance)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ledger", default=str(LEDGER))
    ap.add_argument("--universe", default=str(UNIVERSE))
    ap.add_argument("--as-of", help="ISO date; defaults to today UTC")
    ap.add_argument("--output", default=str(OUT))
    ap.add_argument("--md", action="store_true", help="print the human-readable table instead of writing JSON")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    as_of = _parse_date(args.as_of) or datetime.now(timezone.utc).date()
    ledger = _load(Path(args.ledger), {"registrations": []})
    universe = _load(Path(args.universe), {"_meta": {}, "stocks": []})
    rep = build(ledger, universe, as_of=as_of)
    if args.md:
        print(_render(rep))
    else:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
        print(f"[state-changes] wrote {args.output} | {rep['_meta']['n_active']} ACTIVE + "
              f"{rep['_meta']['n_candidates']} candidate(s) | universe {rep['_meta']['universe_freshness']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
