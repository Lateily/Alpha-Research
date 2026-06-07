#!/usr/bin/env python3
"""model_portfolio.py — Daily Model Portfolio Pilot generator (read-only).

Produces one daily PILOT RUN of the model portfolio: turns the registered
core-thesis directional candidates + quant confluence signals into a structured
"today's model recommendation" object, split into a mid/long-term (core-thesis)
sleeve and a short-term (quant swing) sleeve, plus research / watch pools.

PILOT discipline (Junyan 2026-06-07 — fix-forward of PR #39):
  - FRESH start: this run does NOT inherit the legacy paper_trades positions.
    No old entry / target / stop bound to an existing position. `target_range`
    is thesis-derived and explicitly NOT calibrated; `entry_reference` pends the
    next market sync.
  - Live execution-return tracking begins from the next trading-day pilot run
    (today 2026-06-07 is a non-trading day; A/H closed).
  - UNVALIDATED model output — not validated alpha, not external advice. The
    edge is the loop: recommendation -> user execution -> attribution -> improvement.
  - Read-only: no BUY/SELL conclusion, no recommended size, no auto-trade, no
    positions mutation. positions/analytics/snapshots.json are PROTECTED.

Composes (read-only): trade_candidate_board.json + thesis_queue.json + confluence.json
Output: public/data/model_portfolio.json
Usage:  python3 scripts/model_portfolio.py
        python3 scripts/model_portfolio.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
BOARD = D / "trade_candidate_board.json"
THESES = D / "thesis_queue.json"
CONF = D / "confluence.json"
POSITIONS = D / "positions.json"                 # PROTECTED — read only
OUT = D / "model_portfolio.json"

# Pilot anchor: live execution-return tracking starts from the first trading-day
# run on/after this date. Today 2026-06-07 (Sun) is a non-trading day (A/H closed).
PILOT_START_DATE = "2026-06-09"                   # next A-share trading session (Mon)

DIRECTIONAL = ("LONG", "SHORT", "WATCH_SHORT")
# Fields that would mean a LEGACY paper position leaked into a fresh-pilot card.
# The selftest asserts NONE of these ever appear on a candidate.
LEGACY_FIELDS = ("entry_price", "current_price", "upside_target_pct",
                 "downside_stop_pct", "days_held", "return_since_entry_pct")


def _load(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _construction_plan(direction: str, tier, conviction) -> str:
    """Staging logic only — NOT a price target, NOT a size. Thesis-derived."""
    if conviction and "STARTER" in str(conviction).upper():
        return ("Starter only, capped until E1 confirmation; scale on the E1 print "
                "at the catalyst. Pending calibration to a live entry.")
    if direction == "LONG":
        return "Starter entry, staged; add only on thesis confirmation. Pending calibration."
    if direction in ("SHORT", "WATCH_SHORT"):
        return "Directional bearish view — watch only (no retail-executable short); no entry."
    return "Pending calibration."


def _core_card(r: dict, th: dict, cf: dict) -> dict:
    direction = r.get("direction")
    return {
        "ticker": r.get("ticker"),
        "name": r.get("name"),
        "market": r.get("market"),
        "sleeve": "core_thesis",
        "model_action": direction,                # directional VIEW, NOT a buy order
        "horizon_days": r.get("horizon_days") or th.get("horizon_days"),
        "evidence_tier": r.get("evidence_tier"),
        "why": r.get("catalyst") or th.get("catalyst"),
        # FRESH PILOT: thesis-derived band, NOT calibrated, NOT bound to a live entry.
        "target_range": {
            "basis": "thesis_derived",
            "calibrated": False,
            "entry_reference": "pending_next_market_sync",
            "reward_to_risk": th.get("reward_to_risk"),
            "note": "Thesis-derived band — not yet calibrated to a live entry.",
        },
        "construction_plan": _construction_plan(
            direction, r.get("evidence_tier"), th.get("validation_role") or th.get("conviction_state")),
        "risk_rules": {
            "invalidation": (r.get("wrong_if") or th.get("wrong_if") or [])[:3],
            "current_blocker": r.get("current_blocker"),
        },
        "source_signals": {
            "core_thesis": {
                "family_id": th.get("hypothesis_family_id"),
                "validation_status": th.get("validation_status"),
                "evidence_tier": r.get("evidence_tier"),
                "screen_score": r.get("screen_score"),
            },
            "quant_confluence": ({"action": cf.get("action"), "score": cf.get("score"),
                                  "rationale": cf.get("rationale_e")} if cf else None),
        },
        "validation_status": th.get("validation_status") or "unvalidated_pilot",
        "counts_toward_validation": bool(th.get("counts_toward_validation", False)),
        "no_trade_flag": True,
    }


def build(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    run_date = now.date().isoformat()
    bd = _load(BOARD, {}) or {}
    rows = bd.get("trade_candidate_board", [])
    theses = {t.get("ticker"): t for t in (_load(THESES, {}) or {}).get("thesis_queue", [])}
    scores = (_load(CONF, {}) or {}).get("scores", [])
    conf = {s.get("ticker"): s for s in scores}

    core, research_pool, watch_pool = [], [], []
    for r in rows:
        st = r.get("status")
        direction = r.get("direction")
        th = theses.get(r.get("ticker"), {})
        if direction in DIRECTIONAL:
            core.append(_core_card(r, th, conf.get(r.get("ticker"), {})))
        elif st == "RESEARCH_REQUIRED":
            research_pool.append({"ticker": r.get("ticker"), "name": r.get("name"),
                                  "gap": "screened, no registered directional thesis yet"})
        elif st == "WATCH":
            watch_pool.append({"ticker": r.get("ticker"), "name": r.get("name")})

    # short-term quant sleeve: confluence non-neutral signals (today typically empty)
    swing = []
    for s in scores:
        act = (s.get("action") or "").upper()
        if act and "NEUTRAL" not in act and "WAIT" not in act:
            swing.append({
                "ticker": s.get("ticker"),
                "sleeve": "quant_swing",
                "model_action": s.get("action"),
                "target_range": {"basis": "quant_signal", "calibrated": False,
                                 "entry_reference": "pending_next_market_sync",
                                 "note": "Quant-signal idea — not yet calibrated to a live entry."},
                "source_signals": {"quant_confluence": {"action": s.get("action"), "score": s.get("score"),
                                                        "rationale": s.get("rationale_e")}},
                "validation_status": "unvalidated_pilot",
                "no_trade_flag": True,
            })

    core.sort(key=lambda x: ({"LONG": 0, "SHORT": 1, "WATCH_SHORT": 2}.get(x["model_action"], 9), x["ticker"]))
    swing.sort(key=lambda x: x["ticker"])
    research_pool.sort(key=lambda x: x["ticker"])
    watch_pool.sort(key=lambda x: x["ticker"])

    return {
        "_meta": {
            "layer": ("Daily Model Portfolio Pilot — generator v0 (read-only; idea/status only; "
                      "no size, no BUY/SELL, no auto-trade)"),
            "read_only": True, "no_trades": True, "no_size": True, "no_buy_sell": True, "no_position_mutation": True,
            "run_date": run_date,
            "pilot_start_date": PILOT_START_DATE,
            "generated_at": now.isoformat(),
            "fresh_pilot": True,
            "legacy_paper_positions_inherited": False,
            "sources": ["trade_candidate_board", "thesis_queue", "confluence"],
            "disclaimer": ("Internal model-recommendation pilot. UNVALIDATED model output — not validated alpha, "
                           "and not external investment advice. Target ranges are thesis-derived and NOT calibrated; "
                           "entry references pend the next market sync. Live execution-return tracking begins from "
                           "the next trading-day pilot run. The product edge is the loop: recommendation -> user "
                           "execution -> performance attribution -> model improvement."),
            "counts": {"core_thesis": len(core), "quant_swing": len(swing),
                       "research_pool": len(research_pool), "watch_pool": len(watch_pool)},
        },
        "candidates": core + swing,
        "research_pool": research_pool,
        "watch_pool": watch_pool,
        # User decisions (Follow/Modify/Reject/Watch + actual trades) are captured client-side
        # (localStorage) and merged in later (PR #41); empty at generation time.
        "user_decisions": [],
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
        raise SystemExit("FATAL: model_portfolio mutated protected paper-state — must be read-only")
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
    print("DAILY MODEL PORTFOLIO — PILOT (read-only; idea only; NO size/BUY/SELL)")
    print("=" * 78)
    print(f"run_date={m['run_date']}  pilot_start={m['pilot_start_date']}  counts={m['counts']}")
    for c in out["candidates"][:10]:
        tr = c.get("target_range", {})
        print(f"  [{c['sleeve']:<11}] {c['ticker']:<11} {str(c.get('model_action','')):<12} "
              f"tgt={'calibrated' if tr.get('calibrated') else 'thesis-derived/uncal'} "
              f"why={str(c.get('why') or '')[:60]}")
    print(f"  research_pool={len(out['research_pool'])}  watch_pool={len(out['watch_pool'])}")
    print(f"[model-portfolio] wrote {OUT}")
    return 0


def _selftest() -> int:
    errs = []
    fixed = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)
    out = build(now=fixed)
    cands = out["candidates"]

    # 1) FRESH PILOT: no candidate may carry a legacy paper-position field
    for c in cands:
        leaked = [k for k in LEGACY_FIELDS if k in c] + [k for k in LEGACY_FIELDS if k in (c.get("target_range") or {})]
        if leaked:
            errs.append(f"{c.get('ticker')} leaked legacy position field(s): {leaked}")
    # 2) target ranges are explicitly NOT calibrated (thesis/quant-derived only)
    for c in cands:
        if (c.get("target_range") or {}).get("calibrated") is not False:
            errs.append(f"{c.get('ticker')} target_range.calibrated must be False")
    # 3) discipline flags
    if out.get("no_trade_flag") is not True:
        errs.append("no_trade_flag must be True")
    if out["_meta"].get("legacy_paper_positions_inherited") is not False:
        errs.append("_meta.legacy_paper_positions_inherited must be False")
    if not out["_meta"].get("pilot_start_date"):
        errs.append("pilot_start_date missing")
    if "UNVALIDATED" not in out["_meta"]["disclaimer"] or "not validated alpha" not in out["_meta"]["disclaimer"]:
        errs.append("disclaimer must state UNVALIDATED / not validated alpha")
    # 4) no recommended-size field anywhere on a candidate
    for c in cands:
        if any("size" in k or "shares" in k or "weight" in k for k in c):
            errs.append(f"{c.get('ticker')} carries a sizing field (must be absent)")
    # 5) core sleeve == the board's directional names (nothing dropped/added)
    board = (_load(BOARD, {}) or {}).get("trade_candidate_board", [])
    board_dir = sorted(r["ticker"] for r in board if r.get("direction") in DIRECTIONAL)
    core_tics = sorted(c["ticker"] for c in cands if c["sleeve"] == "core_thesis")
    if core_tics != board_dir:
        errs.append(f"core sleeve != board directional names: core={core_tics} board={board_dir}")
    # 6) determinism: build twice with the same clock -> identical candidate order
    out2 = build(now=fixed)
    if [c["ticker"] for c in out2["candidates"]] != [c["ticker"] for c in cands]:
        errs.append("non-deterministic candidate ordering")

    if errs:
        print("model_portfolio selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("model_portfolio selftest PASSED (fresh pilot: no legacy position fields; target_range never "
          "calibrated; no_trade_flag + legacy_paper_positions_inherited=False + pilot_start_date; disclaimer "
          "states UNVALIDATED/not-validated-alpha; no sizing field; core sleeve == board directional names; "
          "deterministic order)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
