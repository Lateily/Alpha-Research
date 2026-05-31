#!/usr/bin/env python3
"""trade_candidate_board.py — Trade Decision Stack v0, Step 2.

Per docs/strategy/TRADE_DECISION_STACK_v0_DESIGN.md (frozen contract) §3.1.

Read-only composition of candidate sources into a daily trade_candidate board for
human review. Assigns each name a STATUS (no BUY/SELL, no size) using the frozen
precedence, and pulls per-name risk blockers from the Step-1 portfolio_risk_packet.

STATUS PRECEDENCE (frozen §3.1): when several apply, the highest wins —
  RISK_BLOCKED > HUMAN_REVIEW_REQUIRED > RESEARCH_REQUIRED > WATCH > NO_ACTION

HARD BOUNDARIES (design §2): read-only, no BUY/SELL, no recommended size, no
auto-trade, no positions mutation; status-only; every number [unvalidated intuition].
positions/analytics/snapshots.json are PROTECTED — read-only, tripwire-verified.

Composes (read-only): core_screen_queue.json + thesis_queue.json + watchlist.json
+ portfolio_risk_packet.json (Step 1, for risk_blockers).

Output: public/data/trade_candidate_board.json
Usage:  python3 scripts/trade_candidate_board.py
        python3 scripts/trade_candidate_board.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
SCREEN = D / "core_screen_queue.json"
THESIS_QUEUE = D / "thesis_queue.json"
WATCHLIST = D / "watchlist.json"
RISK_PACKET = D / "portfolio_risk_packet.json"
POSITIONS = D / "positions.json"                 # PROTECTED — read only
OUT = D / "trade_candidate_board.json"

PRECEDENCE = ["RISK_BLOCKED", "HUMAN_REVIEW_REQUIRED", "RESEARCH_REQUIRED", "WATCH", "NO_ACTION"]
DIRECTIONAL = {"LONG", "SHORT", "WATCH_LONG", "WATCH_SHORT"}


def _load(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _watchlist_tickers(wl) -> list[str]:
    """watchlist.json is {_meta, tickers}; tickers may be strings or dicts."""
    if not isinstance(wl, dict):
        return []
    out = []
    for t in wl.get("tickers", []):
        if isinstance(t, str):
            out.append(t)
        elif isinstance(t, dict):
            out.append(t.get("ticker") or t.get("ts_code") or t.get("code"))
    return [t for t in out if t]


def _risk_blocked_tickers(risk_packet) -> set[str]:
    """Extract tickers from risk_packet.risk_blockers ('over_concentration:300308.SZ',
    'HARD_CONFLICT 700.HK', ...). Non-ticker blockers (stale:source) are ignored."""
    pat = re.compile(r"\b(\d{6}\.(?:SZ|SH)|\d{3,5}\.HK)\b")
    s = set()
    for b in (risk_packet or {}).get("risk_blockers", []):
        s.update(pat.findall(str(b)))
    return s


def status_for(ticker: str, reg: dict | None, screen_action: str | None, risk_blocked: set) -> tuple[str, str | None]:
    """Apply the frozen precedence; return (status, current_blocker_reason)."""
    states, blocker = {"NO_ACTION"}, None
    if ticker in risk_blocked:
        states.add("RISK_BLOCKED")
        blocker = "in portfolio_risk_packet.risk_blockers (e.g. over-concentration / hard conflict)"
    if reg and reg.get("direction_label") in DIRECTIONAL and reg.get("counts_toward_validation"):
        states.add("HUMAN_REVIEW_REQUIRED")   # registered directional thesis -> human capital decision
    if screen_action == "RUN_THESIS" and (not reg or reg.get("direction_label") in ("PASS", "UNRESOLVED", None)):
        states.add("RESEARCH_REQUIRED")
        blocker = blocker or "screen RUN_THESIS but no registered directional thesis -> research needed"
    if screen_action == "WATCH_DATA" or (reg and reg.get("direction_label") in ("PASS", "UNRESOLVED")):
        states.add("WATCH")
    for s in PRECEDENCE:
        if s in states:
            return s, blocker
    return "NO_ACTION", blocker


def build() -> dict:
    screen = (_load(SCREEN, {}) or {})
    sq = screen.get("screen_queue", [])
    screen_as_of = (screen.get("_meta", {}) or {}).get("as_of_date")
    screen_by = {r.get("ticker"): r for r in sq}

    tqd = _load(THESIS_QUEUE, {}) or {}
    tq = tqd.get("thesis_queue", [])
    reg_by = {r.get("ticker"): r for r in tq}

    wl_tickers = set(_watchlist_tickers(_load(WATCHLIST, {})))
    risk_packet = _load(RISK_PACKET, {}) or {}
    risk_blocked = _risk_blocked_tickers(risk_packet)
    resid_status = risk_packet.get("theme_residual_status", "unknown")
    names = {r.get("ticker"): r.get("name") for r in sq}
    for r in tq:
        names.setdefault(r.get("ticker"), r.get("name"))

    universe = set(screen_by) | set(reg_by) | wl_tickers
    rows = []
    for tic in universe:
        reg = reg_by.get(tic)
        sc = screen_by.get(tic)
        screen_action = (sc or {}).get("recommended_research_action")
        status, blocker = status_for(tic, reg, screen_action, risk_blocked)
        sources = []
        if tic in wl_tickers: sources.append("watchlist")
        if tic in screen_by: sources.append("screen_queue")
        if tic in reg_by: sources.append("thesis_queue")
        direction = (reg or {}).get("direction_label") or "UNRESOLVED"
        catalyst = (reg or {}).get("catalyst")
        rows.append({
            "ticker": tic, "name": names.get(tic) or "",
            "market": "HK" if str(tic).endswith(".HK") else "A",
            "status": status,
            "direction": direction,
            "thesis_summary": (f"{direction} — {str(catalyst)[:80]}" if reg and direction in DIRECTIONAL else None),
            "catalyst": catalyst,
            "wrong_if": (reg or {}).get("wrong_if"),
            "horizon_days": (reg or {}).get("horizon_days"),
            "evidence_tier": (reg or {}).get("evidence_tier") or "UNSPECIFIED",
            "screen_score": (sc or {}).get("screen_score"),
            "data_freshness": {"screen_as_of": screen_as_of,
                               "thesis_registered_at": (reg or {}).get("registered_at"),
                               "theme_residual": resid_status},
            "current_blocker": blocker,
            "source": sources,
            "no_trade_flag": True,
        })

    prec_idx = {s: i for i, s in enumerate(PRECEDENCE)}
    rows.sort(key=lambda r: (prec_idx[r["status"]], -(r["screen_score"] or 0)))
    from collections import Counter
    counts = dict(Counter(r["status"] for r in rows))

    return {
        "_meta": {
            "read_only": True, "no_trades": True, "no_size": True, "no_buy_sell": True, "no_position_mutation": True,
            "spec": "TRADE_DECISION_STACK_v0_DESIGN §3.1; frozen 2026-05-31",
            "layer": "Trade Decision Stack v0 Step 2 — trade_candidate board (status only, no size)",
            "status_precedence": PRECEDENCE,
            "all_numbers": "[unvalidated intuition]",
            "sources": ["core_screen_queue", "thesis_queue", "watchlist", "portfolio_risk_packet (risk_blockers)"],
            "n_candidates": len(rows), "status_counts": counts,
            "note": "STATUS only — never a BUY/SELL or a size. RISK_BLOCKED/HUMAN_REVIEW_REQUIRED are human-review flags.",
        },
        "trade_candidate_board": rows,
    }


def _protected_hash() -> str:
    h = hashlib.sha256()
    for f in (POSITIONS, D / "analytics.json", D / "snapshots.json"):
        try:
            h.update(f.read_bytes())
        except Exception:
            pass
    return h.hexdigest()


def run() -> dict:
    before = _protected_hash()
    out = build()
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    if _protected_hash() != before:
        raise SystemExit("FATAL: trade_candidate_board mutated protected paper-state — must be read-only")
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
    print("TRADE CANDIDATE BOARD (read-only; STATUS only; NO size/BUY/SELL)")
    print("=" * 78)
    print(f"{m['n_candidates']} candidates | status: {m['status_counts']}")
    print(f"{'ticker':<11}{'status':<24}{'dir':<13}{'tier':<6}{'score':>6}  blocker/source")
    for r in out["trade_candidate_board"][:18]:
        print(f"{r['ticker']:<11}{r['status']:<24}{str(r['direction']):<13}{str(r['evidence_tier']):<6}"
              f"{(r['screen_score'] if r['screen_score'] is not None else 0):>6.0f}  "
              f"{r['current_blocker'] or ('/'.join(r['source']))}")
    print(f"\n[candidate-board] wrote {OUT}")
    return 0


def _selftest() -> int:
    errs = []
    rb = _risk_blocked_tickers({"risk_blockers": ["over_concentration:300308.SZ", "HARD_CONFLICT 700.HK", "stale:theme_peer_residual.json"]})
    if rb != {"300308.SZ", "700.HK"}:
        errs.append(f"risk-blocked ticker extraction wrong: {rb}")
    # precedence: RISK_BLOCKED wins even if also directional + screen
    reg_dir = {"direction_label": "LONG", "counts_toward_validation": True}
    if status_for("X", reg_dir, "RUN_THESIS", {"X"})[0] != "RISK_BLOCKED":
        errs.append("precedence: RISK_BLOCKED must win")
    # directional registered (not blocked) -> HUMAN_REVIEW_REQUIRED
    if status_for("X", reg_dir, "RUN_THESIS", set())[0] != "HUMAN_REVIEW_REQUIRED":
        errs.append("directional registered must be HUMAN_REVIEW_REQUIRED")
    # screen RUN_THESIS, no thesis -> RESEARCH_REQUIRED
    if status_for("X", None, "RUN_THESIS", set())[0] != "RESEARCH_REQUIRED":
        errs.append("screen RUN_THESIS w/o thesis must be RESEARCH_REQUIRED")
    # PASS thesis -> WATCH (not human-review)
    if status_for("X", {"direction_label": "PASS"}, "WATCH_DATA", set())[0] != "WATCH":
        errs.append("PASS/WATCH_DATA must be WATCH")
    # nothing -> NO_ACTION
    if status_for("X", None, None, set())[0] != "NO_ACTION":
        errs.append("empty must be NO_ACTION")
    # build invariants on real data
    out = build()
    if out["_meta"]["status_precedence"] != PRECEDENCE:
        errs.append("precedence not frozen order")
    if any("size" in r for r in out["trade_candidate_board"]):
        errs.append("a candidate carries a 'size' field (must be absent)")
    if not all(r["no_trade_flag"] is True for r in out["trade_candidate_board"]):
        errs.append("no_trade_flag missing on a candidate")
    if not all(r["status"] in PRECEDENCE for r in out["trade_candidate_board"]):
        errs.append("a candidate has an out-of-enum status")
    # board must be sorted by precedence
    idx = [PRECEDENCE.index(r["status"]) for r in out["trade_candidate_board"]]
    if idx != sorted(idx):
        errs.append("board not sorted by status precedence")
    if errs:
        print("trade_candidate_board selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("trade_candidate_board selftest PASSED (risk-blocked extraction; precedence "
          "RISK_BLOCKED>HUMAN_REVIEW>RESEARCH>WATCH>NO_ACTION; no size field; no_trade_flag; "
          "enum-valid statuses; sorted by precedence)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
