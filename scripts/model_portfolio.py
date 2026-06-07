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
PILOT_START_DATE = "2026-06-08"                   # next trading session: Mon 2026-06-08 (no A/H holiday until Dragon Boat 6/19–6/21)

DIRECTIONAL = ("LONG", "SHORT", "WATCH_SHORT")
# Fields that would mean a LEGACY paper position leaked into a fresh-pilot card.
# The selftest asserts NONE of these ever appear on a candidate.
LEGACY_FIELDS = ("entry_price", "current_price", "upside_target_pct",
                 "downside_stop_pct", "days_held", "return_since_entry_pct")

# Short-term (swing) sleeve inputs: per-ticker technical signals (swing_signals.py)
# + the watchlist universe (single source of truth, CLAUDE.md).
WATCHLIST = D / "watchlist.json"
STRENGTH_W = {"strong": 2.0, "moderate": 1.0, "weak": 0.5}


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


def _safe_id(tk: str) -> str:
    return (tk or "").replace(".", "_")


def _signal_lean(sig: dict) -> float:
    """Strength-weighted bull(+)/bear(-) lean across the fired technical signals."""
    lean = 0.0
    for s in (sig.get("signals") or []):
        w = STRENGTH_W.get(str(s.get("strength", "")).lower(), 1.0)
        lean += w if s.get("bullish") else -w
    return lean


def _bias(sig: dict) -> str:
    """Honest swing bias: strength-weighted signal lean combined with the zone.
    Signal-lean vs zone disagree -> 'mixed'; no signal + neutral zone -> 'neutral'."""
    lean = _signal_lean(sig)
    zone = (sig.get("zone") or "").upper()
    zsign = 1 if zone == "BULLISH" else (-1 if zone == "BEARISH" else 0)
    lsign = 1 if lean > 0 else (-1 if lean < 0 else 0)
    if lsign == 0 and zsign == 0:
        return "neutral"
    if lsign == 0:
        return "bullish" if zsign > 0 else "bearish"
    if zsign == 0 or lsign == zsign:
        return "bullish" if lsign > 0 else "bearish"
    return "mixed"


def _setup_type(sig: dict) -> str:
    types = [str(s.get("type", "")).lower() for s in (sig.get("signals") or []) if s.get("type")]
    return " / ".join(types) if types else "no_signal"


def _risk_rule(bias: str, ind: dict) -> str:
    ma20, ma60 = ind.get("ma20"), ind.get("ma60")
    if bias == "bullish":
        return f"Setup invalidated on a decisive close below MA20 ({ma20}); loss of MA60 ({ma60}) ends it."
    if bias == "bearish":
        return f"Bearish read negated on a volume-backed reclaim of MA20 ({ma20})."
    if bias == "mixed":
        return f"Unresolved between MA20 ({ma20}) and MA60 ({ma60}) — wait for a decisive close before any read."
    return f"No setup yet — watch MA20 ({ma20}) / MA60 ({ma60}) for the first directional signal."


def _trigger(bias: str, ind: dict) -> str:
    vr = ind.get("vol_ratio")
    base = "confluence upgrade to non-neutral"
    if bias == "bullish":
        return f"{base}, or a volume-confirmed breakout (current vol_ratio {vr})."
    if bias == "bearish":
        return f"{base}, or a volume-confirmed breakdown (current vol_ratio {vr})."
    if bias == "mixed":
        return f"{base}; the setup is unresolved (signals and zone disagree)."
    return f"{base}; no technical signal firing yet."


def _setup_watch_item(tk: str, sig: dict, conf_action, name, market) -> dict:
    """A radar item — what the model is watching — explicitly NOT a trade call."""
    ind = sig.get("indicators") or {}
    bias = _bias(sig)
    fired = [{"type": s.get("type"), "strength": s.get("strength"), "bullish": s.get("bullish"),
              "desc": (s.get("description") or {}).get("e")} for s in (sig.get("signals") or [])]
    return {
        "ticker": tk,
        "name": name,
        "market": market,
        "sleeve": "quant_swing",
        "state": "SETUP_WATCH",            # radar item, NOT an executable model trade
        "signal_class": "no_trade_signal",
        "setup_type": _setup_type(sig),
        "bias": bias,                      # bullish / bearish / mixed / neutral — NOT a LONG/SHORT call
        "why_not_active": f"confluence verdict is {conf_action or 'NEUTRAL'} — no active swing trade today",
        "trigger_to_activate": _trigger(bias, ind),
        "risk_rule": _risk_rule(bias, ind),
        "technical": {
            "zone": sig.get("zone"),
            "entry_zone": sig.get("entry_zone"),
            "exit_zone": sig.get("exit_zone"),
            "signal_count": sig.get("signal_count"),
            "key_indicators": {k: ind.get(k) for k in
                               ("rsi14", "macd_hist", "price_vs_ma20", "price_vs_ma60", "change_5d", "vol_ratio")},
            "signals": fired,
        },
        "as_of": sig.get("generated_at"),
        "validation_status": "unvalidated_pilot",
        "no_trade_flag": True,
    }


def _active_swing_card(s: dict, name, market) -> dict:
    """An ACTIVE short-term idea — only built when confluence is non-neutral."""
    return {
        "ticker": s.get("ticker"),
        "name": name,
        "market": market,
        "sleeve": "quant_swing",
        "model_action": s.get("action"),          # reached only when confluence is non-neutral
        "horizon_days": 5,
        "evidence_tier": "quant_confluence",
        "why": s.get("rationale_e"),
        "target_range": {"basis": "quant_signal", "calibrated": False,
                         "entry_reference": "pending_next_market_sync", "reward_to_risk": None,
                         "note": "Quant-signal idea — not yet calibrated to a live entry."},
        "construction_plan": ("Confluence-confirmed short-term idea; stage entry on the next session "
                              "— pending calibration. No size, no auto-trade."),
        "risk_rules": {"invalidation": [], "current_blocker": None},
        "source_signals": {"quant_confluence": {"action": s.get("action"), "score": s.get("score"),
                                                "rationale": s.get("rationale_e"), "regime": s.get("regime")}},
        "validation_status": "unvalidated_pilot",
        "no_trade_flag": True,
    }


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

    # ---- short-term quant (swing) sleeve: honest-first (Junyan 2026-06-07) ----
    # name/market lookup: board rows first, then the watchlist (single source of truth).
    wl = (_load(WATCHLIST, {}) or {}).get("tickers", {}) or {}
    board_nm = {r.get("ticker"): (r.get("name"), r.get("market")) for r in rows}

    def _nm(tk: str):
        if board_nm.get(tk) and board_nm[tk][0]:
            return board_nm[tk][0], board_nm[tk][1]
        w = wl.get(tk) or {}
        mk = "HK" if str(tk).endswith(".HK") else ("A" if str(tk).endswith((".SZ", ".SH")) else None)
        return (w.get("name_zh") or w.get("name_en") or tk), mk

    # active = STRICTLY confluence-gated (non-neutral). Today all NEUTRAL -> [].
    # We do NOT translate a raw technical pattern into an executable trade.
    active = []
    for s in scores:
        act = (s.get("action") or "").upper()
        if act and "NEUTRAL" not in act and "WAIT" not in act:
            nm, mk = _nm(s.get("ticker"))
            active.append(_active_swing_card(s, nm, mk))
    # setup_watch = the real per-ticker technical setups (radar, NOT trades) so users
    # can see what the model is watching even when there is no active swing trade.
    # Universe = watchlist names + every tracked board name; surface any that has a
    # signals_{id}.json (today: the 7 focus names with a technical-signal file).
    swing_universe = sorted(set(wl.keys()) | {r.get("ticker") for r in rows if r.get("ticker")})
    setup_watch = []
    for tk in swing_universe:
        sig = _load(D / f"signals_{_safe_id(tk)}.json")
        if not sig:
            continue
        nm, mk = _nm(tk)
        setup_watch.append(_setup_watch_item(tk, sig, (conf.get(tk) or {}).get("action"), nm, mk))
    quant_swing = {"active": active, "setup_watch": setup_watch}

    core.sort(key=lambda x: ({"LONG": 0, "SHORT": 1, "WATCH_SHORT": 2}.get(x["model_action"], 9), x["ticker"]))
    active.sort(key=lambda x: x["ticker"])
    setup_watch.sort(key=lambda x: x["ticker"])
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
            "sources": ["trade_candidate_board", "thesis_queue", "confluence", "signals_{ticker}", "watchlist"],
            "swing_policy": ("Short-term sleeve is honest-first: active swing trades are STRICTLY gated on a "
                             "non-neutral confluence verdict (today: none — all tracked names NEUTRAL). The "
                             "setup_watch radar surfaces the real per-ticker technical setups so users see what "
                             "the model is watching; radar items are NOT executable trades (no LONG/SHORT, no size)."),
            "disclaimer": ("Internal model-recommendation pilot. UNVALIDATED model output — not validated alpha, "
                           "and not external investment advice. Target ranges are thesis-derived and NOT calibrated; "
                           "entry references pend the next market sync. Live execution-return tracking begins from "
                           "the next trading-day pilot run. The product edge is the loop: recommendation -> user "
                           "execution -> performance attribution -> model improvement."),
            "counts": {"core_thesis": len(core),
                       "quant_swing_active": len(active), "quant_swing_setup_watch": len(setup_watch),
                       "research_pool": len(research_pool), "watch_pool": len(watch_pool)},
        },
        "candidates": core,
        "quant_swing": quant_swing,
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
    qs = out.get("quant_swing", {})
    print(f"  quant_swing.active={len(qs.get('active') or [])}  setup_watch={len(qs.get('setup_watch') or [])}")
    for sw in (qs.get('setup_watch') or [])[:10]:
        print(f"  [setup_watch ] {sw['ticker']:<11} bias={str(sw.get('bias','')):<8} "
              f"type={str(sw.get('setup_type',''))[:30]:<30} {sw.get('why_not_active','')[:30]}")
    print(f"  research_pool={len(out['research_pool'])}  watch_pool={len(out['watch_pool'])}")
    print(f"[model-portfolio] wrote {OUT}")
    return 0


def _selftest() -> int:
    errs = []
    fixed = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)
    out = build(now=fixed)
    cands = out["candidates"]
    qs = out.get("quant_swing") or {}
    active = qs.get("active") or []
    setup = qs.get("setup_watch") or []

    # 1) FRESH PILOT: no card may carry a legacy paper-position field
    for c in cands + active:
        leaked = [k for k in LEGACY_FIELDS if k in c] + [k for k in LEGACY_FIELDS if k in (c.get("target_range") or {})]
        if leaked:
            errs.append(f"{c.get('ticker')} leaked legacy position field(s): {leaked}")
    # 2) target ranges (core + active) are explicitly NOT calibrated
    for c in cands + active:
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
    # 4) no recommended-size field anywhere on any card (core + active + setup_watch)
    for c in cands + active + setup:
        if any("size" in k or "shares" in k or "weight" in k for k in c):
            errs.append(f"{c.get('ticker')} carries a sizing field (must be absent)")
    # 5) core sleeve == the board's directional names (nothing dropped/added)
    board = (_load(BOARD, {}) or {}).get("trade_candidate_board", [])
    board_dir = sorted(r["ticker"] for r in board if r.get("direction") in DIRECTIONAL)
    core_tics = sorted(c["ticker"] for c in cands if c["sleeve"] == "core_thesis")
    if core_tics != board_dir:
        errs.append(f"core sleeve != board directional names: core={core_tics} board={board_dir}")
    # 6) ACTIVE swing sleeve is STRICTLY confluence-gated (non-neutral verdict only)
    confq = {s.get("ticker"): s for s in (_load(CONF, {}) or {}).get("scores", [])}
    for c in active:
        act = (confq.get(c.get("ticker"), {}).get("action") or "").upper()
        if (not act) or "NEUTRAL" in act or "WAIT" in act:
            errs.append(f"active swing {c.get('ticker')} not backed by a non-neutral confluence verdict")
    # 7) SETUP_WATCH radar is honest — a watch item, NEVER a LONG/SHORT trade call
    valid_bias = {"bullish", "bearish", "mixed", "neutral"}
    for sw in setup:
        if sw.get("state") != "SETUP_WATCH":
            errs.append(f"setup {sw.get('ticker')} state must be SETUP_WATCH")
        if sw.get("signal_class") != "no_trade_signal":
            errs.append(f"setup {sw.get('ticker')} signal_class must be no_trade_signal")
        if sw.get("no_trade_flag") is not True:
            errs.append(f"setup {sw.get('ticker')} no_trade_flag must be True")
        if "model_action" in sw or sw.get("bias") in DIRECTIONAL:
            errs.append(f"setup {sw.get('ticker')} must NOT carry a LONG/SHORT model_action")
        if sw.get("bias") not in valid_bias:
            errs.append(f"setup {sw.get('ticker')} bias must be one of {sorted(valid_bias)}")
        for req in ("why_not_active", "trigger_to_activate", "risk_rule", "setup_type"):
            if not sw.get(req):
                errs.append(f"setup {sw.get('ticker')} missing {req}")
    # 8) setup_watch covers exactly the tracked names (watchlist + board) with a signals file
    wl = (_load(WATCHLIST, {}) or {}).get("tickers", {}) or {}
    board_all = (_load(BOARD, {}) or {}).get("trade_candidate_board", [])
    universe = set(wl.keys()) | {r.get("ticker") for r in board_all if r.get("ticker")}
    have_sig = sorted(tk for tk in universe if (D / f"signals_{_safe_id(tk)}.json").exists())
    setup_order = [sw["ticker"] for sw in setup]
    if sorted(setup_order) != have_sig:
        errs.append(f"setup_watch != tracked names with a signals file: setup={sorted(setup_order)} have_sig={have_sig}")
    # 9) determinism: build twice -> identical core + setup_watch ordering
    out2 = build(now=fixed)
    if [c["ticker"] for c in out2["candidates"]] != [c["ticker"] for c in cands]:
        errs.append("non-deterministic candidate ordering")
    if [s["ticker"] for s in (out2.get("quant_swing") or {}).get("setup_watch", [])] != setup_order:
        errs.append("non-deterministic setup_watch ordering")

    if errs:
        print("model_portfolio selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("model_portfolio selftest PASSED (fresh pilot: no legacy fields; target_range never calibrated; "
          "discipline flags; no sizing field; core sleeve == board directional; ACTIVE swing strictly "
          "confluence-gated; SETUP_WATCH radar = no_trade_signal, never LONG/SHORT, covers the watchlist "
          "signal files; deterministic core + setup order)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
