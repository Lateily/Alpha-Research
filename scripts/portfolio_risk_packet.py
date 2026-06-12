#!/usr/bin/env python3
"""portfolio_risk_packet.py — Trade Decision Stack v0, Step 1 (the honest core).

Per docs/strategy/TRADE_DECISION_STACK_v0_DESIGN.md (frozen contract) §3.2.

Read-only composition of already-shipped artifacts into a daily PORTFOLIO RISK view
for human review. It answers "what risk/exposure does the current paper book carry,
and what would entering a registered thesis add" — it does NOT recommend trades.

HARD BOUNDARIES (design §2):
  - NO BUY/SELL, NO recommended position size, NO auto-trade, NO positions mutation.
  - Output is exposure + risk blockers only. Every number [unvalidated intuition].
  - positions/analytics/snapshots.json are PROTECTED — read-only, tripwire-verified.

Composes (read-only): positions.json (paper book) + core_shadow_portfolio.json +
portfolio_thesis_alignment.json (conflicts) + thesis_queue.json (wrong_if/horizon/
theme) + theme_peer_residual.json (theme exposure, WITH stale guard).

Output: public/data/portfolio_risk_packet.json
Usage:  python3 scripts/portfolio_risk_packet.py [--as-of YYYY-MM-DD]
        python3 scripts/portfolio_risk_packet.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
POSITIONS = D / "positions.json"                 # PROTECTED — read only
SHADOW = D / "core_shadow_portfolio.json"
ALIGNMENT = D / "portfolio_thesis_alignment.json"
THESIS_QUEUE = D / "thesis_queue.json"
THEME_RESIDUAL = D / "theme_peer_residual.json"
OUT = D / "portfolio_risk_packet.json"

# [unvalidated intuition] concentration caps — NOT calibrated; flag-only, never advice.
SINGLE_NAME_CAP_PCT = 30.0        # [unvalidated intuition]
THEME_CAP_PCT = 40.0              # [unvalidated intuition]
WRONG_IF_NEAR_DAYS = 30          # [unvalidated intuition] — "near" falsifier window
PNL_STALE_EPS = 0.5              # pp; residual pnl vs current pnl divergence => stale snapshot
DIRECTIONAL = {"LONG", "SHORT", "WATCH_LONG", "WATCH_SHORT"}


def _load(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def theme_of(ticker: str, tq_themes: dict) -> str:
    """Dynamic theme bucket: prefer thesis_queue, then theme_peer_residual basket map;
    unknown -> UNMAPPED (never silently dropped)."""
    if ticker in tq_themes and tq_themes[ticker]:
        return tq_themes[ticker]
    try:
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        from theme_peer_residual import TICKER_BASKET
        bid = TICKER_BASKET.get(ticker)
        if bid:
            return bid.replace("_v0", "").upper()
    except Exception:
        pass
    return "UNMAPPED"


def _dates_in(text: str) -> list[str]:
    return re.findall(r"\d{4}-\d{2}-\d{2}", text or "")


def _days_between(a: str, b: str) -> int | None:
    try:
        ya, ma, da = map(int, a.split("-")); yb, mb, db = map(int, b.split("-"))
        return (date(yb, mb, db) - date(ya, ma, da)).days
    except Exception:
        return None


def _residual_freshness(positions, resid_pos, resid_as_of, as_of_paper):
    """Frozen-design stale guard: WITHOUT an explicit current as_of AND WITHOUT
    comparable pnl_pct for every held position, DEFAULT to theme_residual_stale —
    never treat unverifiable attribution as today's risk. `fresh` requires proof."""
    if not resid_pos:
        return "theme_residual_stale", "theme_peer_residual.json missing/empty"
    if resid_as_of:                                   # future-proof: #3 may add as_of later
        if as_of_paper and str(resid_as_of)[:10] >= str(as_of_paper)[:10]:
            return "fresh", f"explicit residual as_of {str(resid_as_of)[:10]} >= book {str(as_of_paper)[:10]}"
        return "theme_residual_stale", f"residual as_of {resid_as_of} older than book {as_of_paper}"
    held = [p for p in positions if p.get("ticker")]
    if not held:
        return "theme_residual_stale", "no held positions to compare"
    diffs = []
    for p in held:                                    # require comparable pnl for EVERY held name
        r = resid_pos.get(p.get("ticker"))
        rp, pp = (r or {}).get("pnl_pct"), p.get("pnl_pct")
        if r is None or rp is None or pp is None:
            return ("theme_residual_stale",
                    "no comparable pnl/as_of in theme_peer_residual — cannot verify freshness; conservative stale")
        diffs.append(abs(float(rp) - float(pp)))
    if all(d <= PNL_STALE_EPS for d in diffs):
        return "fresh", "residual pnl_pct matches current book for all held positions"
    return "theme_residual_stale", "residual pnl_pct diverges from current book (older snapshot)"


def build(as_of_ref: str | None = None) -> dict:
    pos_doc = _load(POSITIONS, {}) or {}
    positions = pos_doc.get("positions", [])
    as_of_paper = (pos_doc.get("as_of") or "")[:19]
    ref_date = as_of_ref or (as_of_paper[:10] if as_of_paper else "")

    tq = (_load(THESIS_QUEUE, {}) or {}).get("thesis_queue", [])
    tq_themes = {r.get("ticker"): r.get("theme_bucket") for r in tq}
    shadow = _load(SHADOW, {}) or {}
    align = (_load(ALIGNMENT, {}) or {}).get("positions", [])
    align_by = {r.get("ts_code"): r.get("alignment") for r in align}
    residual = _load(THEME_RESIDUAL, {}) or {}
    resid_pos = {r.get("ticker"): r for r in residual.get("positions", [])}

    # ── current paper-book exposure (FACTS, not recommendations) ──
    gross = round(sum(abs(p.get("weight_pct") or 0.0) for p in positions), 3)
    net = round(sum((p.get("weight_pct") or 0.0) * (1 if (p.get("quantity") or 0) >= 0 else -1)
                    for p in positions), 3)
    theme_exposure: dict[str, float] = {}
    for p in positions:
        t = theme_of(p.get("ticker"), tq_themes)
        theme_exposure[t] = round(theme_exposure.get(t, 0.0) + (p.get("weight_pct") or 0.0), 3)

    # ── theme_residual STALE GUARD — frozen design: DEFAULT STALE unless provably fresh ──
    resid_as_of = (residual.get("_meta") or {}).get("as_of")   # #3 currently emits none -> None
    resid_status, resid_reason = _residual_freshness(positions, resid_pos, resid_as_of, as_of_paper)
    resid_note = ("theme_peer_residual.json has NO explicit as_of; freshness derived from "
                  "per-ticker pnl vs current book. v0.1: add as_of to #3 output. Panel-coupled "
                  "(CODEX_FINDINGS 2026-05-31-A) — frequently stale vs the daily book; that is honest.")

    # ── thesis conflicts (paper position vs registered thesis direction) ──
    div = shadow.get("divergence", {})
    thesis_conflicts = []
    for tic in (div.get("hard_conflict", []) + div.get("watch_conflict", [])):
        thesis_conflicts.append({"ticker": tic, "kind": align_by.get(tic, "CONFLICT"),
                                 "note": "paper position direction opposes the registered thesis"})

    # ── wrong_if near trigger (DATE proximity only; metric-proximity needs data, deferred) ──
    wrong_if_near = []
    held_tickers = {p.get("ticker") for p in positions}
    for r in tq:
        if r.get("ticker") not in held_tickers:
            continue
        for w in (r.get("wrong_if") or []):
            for dt in _dates_in(w):
                dd = _days_between(ref_date, dt) if ref_date else None
                if dd is not None and 0 <= dd <= WRONG_IF_NEAR_DAYS:
                    wrong_if_near.append({"ticker": r.get("ticker"), "falsifier_date": dt,
                                          "days_away": dd, "falsifier": w[:120],
                                          "basis": "date proximity only [unvalidated]; metric-proximity needs live data"})

    # ── stale data blockers ──
    stale_blockers = []
    if ref_date and as_of_paper and _days_between(as_of_paper[:10], ref_date) and _days_between(as_of_paper[:10], ref_date) > 1:
        stale_blockers.append({"source": "positions.json", "as_of": as_of_paper,
                               "note": f"paper book {as_of_paper[:10]} older than ref {ref_date}"})
    if resid_status == "theme_residual_stale":
        stale_blockers.append({"source": "theme_peer_residual.json", "note": resid_reason})

    # ── over-concentration flags ([unvalidated] caps; exposure facts, not advice) ──
    conc = []
    for p in positions:
        w = p.get("weight_pct") or 0.0
        if w > SINGLE_NAME_CAP_PCT:
            conc.append({"kind": "single_name", "ticker": p.get("ticker"), "weight_pct": round(w, 2),
                         "cap_pct": SINGLE_NAME_CAP_PCT, "cap_status": "[unvalidated intuition]"})
    for t, w in theme_exposure.items():
        if w > THEME_CAP_PCT:
            conc.append({"kind": "theme", "theme": t, "exposure_pct": round(w, 2),
                         "cap_pct": THEME_CAP_PCT, "cap_status": "[unvalidated intuition]"})

    # ── per-candidate incremental (SIZE-FREE: direction + theme it would load + conflict) ──
    per_candidate = []
    for r in tq:
        d = r.get("direction_label")
        if d not in DIRECTIONAL:
            continue
        tic = r.get("ticker")
        th = theme_of(tic, tq_themes)
        per_candidate.append({
            "ticker": tic, "direction": d,
            "theme_it_would_load": th,
            "current_theme_exposure_pct": theme_exposure.get(th, 0.0),
            "currently_held": tic in held_tickers,
            "existing_position_conflict": align_by.get(tic, "none" if tic in held_tickers else "not_held"),
            # NO size field — v0 emits no recommended position size (design §2); see top-level _omitted.
        })

    # ── aggregate risk blockers ──
    risk_blockers = []
    risk_blockers += [f"HARD_CONFLICT {c['ticker']}" for c in thesis_conflicts if c["kind"] == "HARD_CONFLICT"]
    risk_blockers += [f"stale:{s['source']}" for s in stale_blockers]
    risk_blockers += [f"over_concentration:{c.get('ticker') or c.get('theme')}" for c in conc]

    return {
        "_meta": {
            "read_only": True, "no_trades": True, "no_size": True, "no_buy_sell": True, "no_position_mutation": True,
            "spec": "TRADE_DECISION_STACK_v0_DESIGN §3.2; frozen 2026-05-31",
            "layer": "Trade Decision Stack v0 Step 1 — portfolio risk packet (exposure + blockers, NOT sizing)",
            "all_numbers": "[unvalidated intuition] unless directly observed paper-book exposure/P&L",
            "ref_date": ref_date,
        },
        "as_of_paper": as_of_paper,
        "theme_residual_status": resid_status,
        "theme_residual_as_of": resid_as_of,        # null when #3 emits no as_of (current state)
        "theme_residual_reason": resid_reason,
        "theme_residual_note": resid_note,
        "book": {"gross_pct": gross, "net_pct": net, "theme_exposure": theme_exposure},
        "per_candidate_incremental": per_candidate,
        "thesis_conflicts": thesis_conflicts,
        "wrong_if_near_trigger": wrong_if_near,
        "stale_data_blockers": stale_blockers,
        "over_concentration_flags": conc,
        "risk_blockers": sorted(set(risk_blockers)),
        "_omitted": "recommended_position_size — intentionally NOT emitted in v0 (ratified)",
        "no_trade_flag": True,
    }


def _protected_hash() -> str:
    """Tripwire over protected paper-state — this generator must NEVER mutate it."""
    h = hashlib.sha256()
    for f in (POSITIONS, D / "analytics.json", D / "snapshots.json"):
        try:
            h.update(f.read_bytes())
        except Exception:
            pass
    return h.hexdigest()


def run(as_of_ref=None) -> dict:
    before = _protected_hash()                       # protected paper-state tripwire
    out = build(as_of_ref)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    if _protected_hash() != before:
        raise SystemExit("FATAL: portfolio_risk_packet mutated protected paper-state — must be read-only")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", default=None, help="reference date YYYY-MM-DD (default: positions as_of)")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    out = run(args.as_of)
    b = out["book"]
    print("=" * 76)
    print("PORTFOLIO RISK PACKET (read-only; exposure + blockers; NO size/BUY/SELL)")
    print("=" * 76)
    print(f"as_of_paper {out['as_of_paper']}  |  theme_residual: {out['theme_residual_status']} ({out['theme_residual_reason']})")
    print(f"book: gross {b['gross_pct']}%  net {b['net_pct']}%")
    print(f"theme_exposure: {b['theme_exposure']}")
    print(f"thesis_conflicts: {[(c['ticker'],c['kind']) for c in out['thesis_conflicts']] or 'none'}")
    print(f"wrong_if_near_trigger: {[(w['ticker'],w['days_away']) for w in out['wrong_if_near_trigger']] or 'none'}")
    print(f"over_concentration: {[(c.get('ticker') or c.get('theme'), c.get('weight_pct') or c.get('exposure_pct')) for c in out['over_concentration_flags']] or 'none'}")
    print(f"risk_blockers: {out['risk_blockers'] or 'none'}")
    print(f"\n[risk-packet] wrote {OUT}")
    return 0


def _selftest() -> int:
    errs = []
    # synthetic: 2 positions, 1 theme over cap, 1 single-name over cap, residual pnl mismatch -> stale
    tq_themes = {"AAA.SZ": "AI_CPO", "BBB.HK": "EV"}
    # theme_of: known via thesis_queue, unknown -> UNMAPPED
    if theme_of("AAA.SZ", tq_themes) != "AI_CPO":
        errs.append("theme_of: known theme not resolved")
    if theme_of("ZZZ.SZ", {}) != "UNMAPPED":
        errs.append("theme_of: unknown ticker must be UNMAPPED, not dropped")
    # date proximity
    if _days_between("2026-05-28", "2026-06-10") != 13:
        errs.append("days_between wrong")
    if _dates_in("GM ≤ 16.5% @ 2026 H1 报告 2026-08-31 | src") != ["2026-08-31"]:
        errs.append("date extraction wrong")
    # build invariants on the real data (must be read-only + size-free)
    out = build()
    if out["no_trade_flag"] is not True:
        errs.append("no_trade_flag missing")
    # Blocker-2: NO `size` field at all in per_candidate (not even a string — the field
    # name alone invites UI mis-render as a sizing surface).
    if any("size" in c for c in out.get("per_candidate_incremental", [])):
        errs.append("a per_candidate carries a 'size' field (must be absent entirely)")
    if "recommended_position_size" in out.get("book", {}):
        errs.append("book carries a recommended_position_size field")
    if any(k for k in out if "recommended" in k and "size" in k):
        errs.append("output carries a recommended-size field")
    if not out["_meta"]["no_size"] or "size" not in out["_omitted"]:
        errs.append("no-size discipline not asserted in _meta/_omitted")
    # theme_exposure must include every position's theme (UNMAPPED allowed, none dropped)
    npos = len(_load(POSITIONS, {}).get("positions", []))
    covered = sum(1 for p in _load(POSITIONS, {}).get("positions", [])
                  if theme_of(p.get("ticker"), {r.get("ticker"): r.get("theme_bucket") for r in _load(THESIS_QUEUE, {}).get("thesis_queue", [])}) in out["book"]["theme_exposure"])
    if npos and covered != npos:
        errs.append(f"theme coverage: {covered}/{npos} positions mapped (some silently dropped)")
    # stale guard must be one of the allowed states
    if out["theme_residual_status"] not in ("fresh", "theme_residual_stale"):
        errs.append(f"bad theme_residual_status: {out['theme_residual_status']}")
    # ── stale-guard cases (frozen design: DEFAULT stale unless provably fresh) ──
    pos2 = [{"ticker": "AAA.SZ", "pnl_pct": 10.0}, {"ticker": "BBB.HK", "pnl_pct": -2.0}]
    no_pnl = {"AAA.SZ": {"total_return": 1.1}, "BBB.HK": {"total_return": 0.98}}   # the REAL #3 shape (no pnl_pct)
    if _residual_freshness(pos2, no_pnl, None, "2026-05-28")[0] != "theme_residual_stale":
        errs.append("stale guard: residual WITHOUT pnl_pct/as_of must default STALE (this was the blocker)")
    mismatch = {"AAA.SZ": {"pnl_pct": 10.0}, "BBB.HK": {"pnl_pct": 5.0}}
    if _residual_freshness(pos2, mismatch, None, "2026-05-28")[0] != "theme_residual_stale":
        errs.append("stale guard: pnl mismatch must be stale")
    match = {"AAA.SZ": {"pnl_pct": 10.0}, "BBB.HK": {"pnl_pct": -2.0}}
    if _residual_freshness(pos2, match, None, "2026-05-28")[0] != "fresh":
        errs.append("stale guard: pnl match (all held) must be fresh")
    if _residual_freshness(pos2, no_pnl, "2026-05-29", "2026-05-28")[0] != "fresh":
        errs.append("stale guard: explicit current as_of must be fresh")
    if _residual_freshness(pos2, no_pnl, "2026-05-20", "2026-05-28")[0] != "theme_residual_stale":
        errs.append("stale guard: older as_of must be stale")
    if _residual_freshness(pos2, {}, None, "2026-05-28")[0] != "theme_residual_stale":
        errs.append("stale guard: empty residual must be stale")
    if errs:
        print("portfolio_risk_packet selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("portfolio_risk_packet selftest PASSED (theme_of dynamic+UNMAPPED; date proximity; "
          "NO size field in per_candidate; theme coverage total; stale-guard: missing-pnl/as_of->STALE, "
          "mismatch->STALE, match->fresh, as_of paths, empty->STALE)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
