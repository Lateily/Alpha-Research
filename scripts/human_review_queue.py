#!/usr/bin/env python3
"""human_review_queue.py — Trade Decision Stack v0, Step 4A.

Per docs/strategy/TRADE_DECISION_STACK_v0_DESIGN.md (frozen contract) §3.4.

Read-only composition of the Step-2 trade_candidate_board + Step-1
portfolio_risk_packet into a daily HUMAN REVIEW WORKFLOW — "what should the team
inspect today?" — split into four buckets:

  review_required    must look today: RISK_BLOCKED / HUMAN_REVIEW_REQUIRED, or any
                     name carrying a risk-packet trigger (thesis conflict, wrong_if
                     near, stale-data blocker)
  need_more_research screen says interesting but no registered directional thesis
                     (RESEARCH_REQUIRED — the screen->thesis gap #2C exposes)
  candidate_review   WATCH + a registered thesis — discussion / reference only,
                     NOT auto-promoted; v0 implies NO starting position (the thesis
                     is non-directional/watch; a directional one would be HUMAN_REVIEW)
  can_ignore         visible (watchlist/screen) but no action signal today

Each board name lands in EXACTLY ONE bucket (priority mirrors the shipped status
precedence; the four buckets PARTITION the board universe — nothing dropped).

HARD BOUNDARIES (design §2): read-only, no BUY/SELL, no recommended size, no
auto-trade, no positions mutation; status-only; NO new numbers (any ordering is
the already-shipped status precedence — [unvalidated intuition], not a calibrated
priority). positions/analytics/snapshots.json are PROTECTED — read-only, tripwire-verified.

Composes (read-only): trade_candidate_board.json + portfolio_risk_packet.json
Output: public/data/human_review_queue.json
Usage:  python3 scripts/human_review_queue.py
        python3 scripts/human_review_queue.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
BOARD = D / "trade_candidate_board.json"
RISK_PACKET = D / "portfolio_risk_packet.json"
POSITIONS = D / "positions.json"                 # PROTECTED — read only
OUT = D / "human_review_queue.json"

PRECEDENCE = ["RISK_BLOCKED", "HUMAN_REVIEW_REQUIRED", "RESEARCH_REQUIRED", "WATCH", "NO_ACTION"]
TICKER_RE = re.compile(r"\b(\d{6}\.(?:SZ|SH)|\d{3,5}\.HK)\b")


def _load(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _tickers_in(items) -> set[str]:
    """Tickers referenced in a risk-packet list. Entries may be dicts {ticker:..}
    or strings ('700.HK: falsifier X is 12 days away'). Deterministic set."""
    s = set()
    for it in (items or []):
        if isinstance(it, dict) and it.get("ticker"):
            s.add(it["ticker"])
        else:
            s.update(TICKER_RE.findall(str(it)))
    return s


def _reasons_for(tic: str, row: dict, risk: dict) -> tuple[str, str]:
    """All applicable review reasons + what-to-check for a must-look name. Pure
    composition of shipped signals; introduces no new numbers."""
    reasons, checks = [], []
    if tic in _tickers_in(risk.get("thesis_conflicts")):
        reasons.append("thesis conflict (paper position vs registered thesis direction)")
        checks.append("reconcile the paper direction against the registered thesis")
    if tic in _tickers_in(risk.get("wrong_if_near_trigger")):
        reasons.append("falsifier near (a wrong_if trigger is approaching)")
        checks.append("evaluate the wrong_if condition — the thesis may be invalidated")
    if tic in _tickers_in(risk.get("stale_data_blockers")):
        reasons.append("data too stale to act on")
        checks.append("refresh the stale source before relying on this name")
    st = row.get("status")
    if st == "RISK_BLOCKED" and not reasons:
        reasons.append(row.get("current_blocker") or "in portfolio_risk_packet.risk_blockers")
        checks.append("confirm the risk block (e.g. an [unvalidated] concentration cap) and decide")
    if st == "HUMAN_REVIEW_REQUIRED":
        reasons.append("registered directional thesis — human capital decision")
        checks.append("review thesis + catalyst + wrong_if; decide whether to act (system will not size or trade)")
    if not reasons:
        reasons.append("flagged for review")
        checks.append("inspect the candidate-board row")
    return "; ".join(reasons), "; ".join(checks)


def build() -> dict:
    bd = _load(BOARD, {}) or {}
    rows = bd.get("trade_candidate_board", [])
    risk = _load(RISK_PACKET, {}) or {}

    # any name with a risk-packet trigger is "must look today" regardless of board status
    triggered = (_tickers_in(risk.get("thesis_conflicts"))
                 | _tickers_in(risk.get("wrong_if_near_trigger"))
                 | _tickers_in(risk.get("stale_data_blockers")))

    review_required, need_more_research, candidate_review, can_ignore = [], [], [], []
    for row in rows:
        tic = row.get("ticker")
        st = row.get("status")
        has_thesis = "thesis_queue" in (row.get("source") or [])
        if st in ("RISK_BLOCKED", "HUMAN_REVIEW_REQUIRED") or tic in triggered:
            reason, check = _reasons_for(tic, row, risk)
            review_required.append({"ticker": tic, "reason": reason, "what_to_check": check})
        elif st == "RESEARCH_REQUIRED":
            need_more_research.append({
                "ticker": tic,
                "gap": "passed the attention screen but has no registered directional thesis (screen->thesis gap)"})
        elif st == "WATCH" and has_thesis:
            candidate_review.append({
                "ticker": tic,
                "note": f"WATCH + registered thesis (source: {'/'.join(row.get('source') or ['-'])}); "
                        "discussion / reference only, NOT auto-promoted; v0 implies NO starting position"})
        else:
            can_ignore.append({
                "ticker": tic,
                "why": f"visible ({'/'.join(row.get('source') or ['-'])}) but no action signal today (status {st})"})

    # deterministic order within each bucket: by shipped status precedence, then ticker
    pos = {r.get("ticker"): (PRECEDENCE.index(r.get("status")) if r.get("status") in PRECEDENCE else 99)
           for r in rows}
    for bucket in (review_required, need_more_research, candidate_review, can_ignore):
        bucket.sort(key=lambda x: (pos.get(x["ticker"], 99), x["ticker"]))

    return {
        "_meta": {
            "read_only": True, "no_trades": True, "no_size": True, "no_buy_sell": True, "no_position_mutation": True,
            "spec": "TRADE_DECISION_STACK_v0_DESIGN §3.4; frozen 2026-05-31",
            "layer": "Trade Decision Stack v0 Step 4A — human_review_queue (daily review workflow; status only, no size)",
            "all_numbers": "[unvalidated intuition]; ordering is the shipped status precedence, NOT a calibrated priority",
            "sources": ["trade_candidate_board", "portfolio_risk_packet"],
            "buckets": {"review_required": len(review_required), "need_more_research": len(need_more_research),
                        "candidate_review": len(candidate_review), "can_ignore": len(can_ignore)},
            "note": "The four buckets PARTITION the candidate board — every name lands in exactly one, nothing "
                    "dropped. candidate_review is a discussion/reference list, NOT a buy and NOT a position.",
        },
        "review_required": review_required,
        "need_more_research": need_more_research,
        "candidate_review": candidate_review,
        "can_ignore": can_ignore,
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


def run() -> dict:
    before = _protected_hash()
    out = build()
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    if _protected_hash() != before:
        raise SystemExit("FATAL: human_review_queue mutated protected paper-state — must be read-only")
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
    print("HUMAN REVIEW QUEUE (read-only; daily workflow; NO size/BUY/SELL)")
    print("=" * 78)
    print(f"buckets: {m['buckets']}")
    for b, label in (("review_required", "REVIEW TODAY"), ("need_more_research", "NEED RESEARCH"),
                     ("candidate_review", "DISCUSS (not trade)"), ("can_ignore", "ignore")):
        items = out[b]
        print(f"\n[{label}] ({len(items)})")
        for it in items[:8]:
            tail = it.get("reason") or it.get("gap") or it.get("note") or it.get("why") or ""
            print(f"  {it['ticker']:<11} {str(tail)[:88]}")
        if len(items) > 8:
            print(f"  … +{len(items) - 8} more")
    print(f"\n[human-review-queue] wrote {OUT}")
    return 0


def _selftest() -> int:
    errs = []
    # _tickers_in handles dicts + strings; ignores non-ticker noise
    ti = _tickers_in([{"ticker": "300308.SZ"}, "700.HK: falsifier 12d away", "stale:theme_peer_residual.json"])
    if ti != {"300308.SZ", "700.HK"}:
        errs.append(f"_tickers_in wrong: {ti}")
    # _reasons_for surfaces a conflict for a name in thesis_conflicts
    r, c = _reasons_for("700.HK", {"status": "WATCH"}, {"thesis_conflicts": [{"ticker": "700.HK"}]})
    if "conflict" not in r or not c:
        errs.append("_reasons_for did not surface a thesis conflict")
    # a non-flagged empty name still gets a fallback reason (never blank)
    if not _reasons_for("X", {"status": "WATCH"}, {})[0]:
        errs.append("_reasons_for returned a blank reason")

    out = build()
    board = (_load(BOARD, {}) or {}).get("trade_candidate_board", [])
    board_tics = [r["ticker"] for r in board]
    buckets = ["review_required", "need_more_research", "candidate_review", "can_ignore"]
    bucket_tics = [it["ticker"] for b in buckets for it in out[b]]
    # PARTITION: exactly one bucket per board name — nothing dropped, nothing duplicated
    if sorted(bucket_tics) != sorted(board_tics):
        errs.append("buckets do not partition the board universe (drop or mismatch)")
    if len(bucket_tics) != len(set(bucket_tics)):
        errs.append("a ticker appears in more than one bucket")
    # review_required must contain every RISK_BLOCKED/HUMAN_REVIEW name ...
    rr = {it["ticker"] for it in out["review_required"]}
    must = {r["ticker"] for r in board if r["status"] in ("RISK_BLOCKED", "HUMAN_REVIEW_REQUIRED")}
    if not must.issubset(rr):
        errs.append("review_required missing a RISK_BLOCKED/HUMAN_REVIEW name")
    # ... and every on-board risk-packet-triggered name (the override)
    risk = _load(RISK_PACKET, {}) or {}
    triggered = (_tickers_in(risk.get("thesis_conflicts")) | _tickers_in(risk.get("wrong_if_near_trigger"))
                 | _tickers_in(risk.get("stale_data_blockers")))
    on_board = {t for t in triggered if t in set(board_tics)}
    if not on_board.issubset(rr):
        errs.append("review_required missing a risk-packet-triggered name (override failed)")
    # no size field anywhere; no_trade_flag true; buckets present
    for b in buckets:
        if any("size" in it for it in out[b]):
            errs.append(f"{b} item carries a 'size' field (must be absent)")
    if out.get("no_trade_flag") is not True:
        errs.append("no_trade_flag must be True")
    # determinism: build twice -> identical bucket orders (stable committed product)
    out2 = build()
    for b in buckets:
        if [x["ticker"] for x in out[b]] != [x["ticker"] for x in out2[b]]:
            errs.append(f"non-deterministic ordering in {b}")

    if errs:
        print("human_review_queue selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("human_review_queue selftest PASSED (ticker extraction dicts+strings; conflict reasons + non-blank "
          "fallback; 4 buckets partition the board with no drop/dup; review_required ⊇ RISK_BLOCKED/HUMAN_REVIEW "
          "+ risk-triggered names; no size field; no_trade_flag; deterministic order)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
