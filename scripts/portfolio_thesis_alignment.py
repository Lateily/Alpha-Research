#!/usr/bin/env python3
"""portfolio_thesis_alignment.py — READ-ONLY thesis↔portfolio consistency marker.

Per Junyan 2026-05-29: the live paper book is LONG Tencent/NetEase/BeiGene while
the engine's research on those names leans SHORT (WATCH_SHORT) — and Tencent is
−21%. This is a research↔position DISCONNECT. This script MARKS that disconnect;
it does NOT trade, does NOT change positions, does NOT auto-close anything. It is
a guardrail/observer that flags conflicts for HUMAN review.

For each paper position it emits:
  position_side               — LONG / SHORT (inferred from quantity sign)
  latest_thesis_direction     — latest-stage reclassified label for the ticker
  directional_for_capital     — thesis is LONG/SHORT (capital-eligible)
  directional_for_validation  — thesis is LONG/SHORT/WATCH_* (forward-track only)
  alignment ∈ {ALIGNED, WATCH_CONFLICT, HARD_CONFLICT, NO_CAPITAL_THESIS, NO_THESIS}
  requires_human_review       — True for any *_CONFLICT

Alignment rules (marking only — see PORTFOLIO_THESIS_ALIGNMENT_RULES.md):
  no thesis record                         → NO_THESIS
  thesis PASS / UNRESOLVED                 → NO_CAPITAL_THESIS
  thesis dir == position side              → ALIGNED   (incl. WATCH same-side)
  thesis dir != side, thesis is WATCH_*    → WATCH_CONFLICT   (soft, review)
  thesis dir != side, thesis is LONG/SHORT → HARD_CONFLICT    (strong, review)

Output: public/data/portfolio_thesis_alignment.json
Usage:  python3 scripts/portfolio_thesis_alignment.py
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
POSITIONS = REPO / "public" / "data" / "positions.json"
BACKFILL = REPO / "public" / "data" / "thesis_direction_backfill.json"
OUT = REPO / "public" / "data" / "portfolio_thesis_alignment.json"

CAPITAL_LABELS = {"LONG", "SHORT"}
VALIDATION_LABELS = {"LONG", "SHORT", "WATCH_LONG", "WATCH_SHORT"}


def latest_thesis_labels() -> dict:
    """ts_code → latest-stage reclassified label (from the backfill artifact)."""
    if not BACKFILL.exists():
        return {}
    data = json.loads(BACKFILL.read_text())
    out = {}
    for r in data.get("latest_rows", []):
        out[r.get("ts_code")] = r.get("reclassified")
    return out


def alignment_of(side: str, label: str | None) -> str:
    if label is None:
        return "NO_THESIS"
    if label in ("PASS", "UNRESOLVED"):
        return "NO_CAPITAL_THESIS"
    thesis_dir = "LONG" if label in ("LONG", "WATCH_LONG") else "SHORT"
    is_watch = label.startswith("WATCH_")
    if side == thesis_dir:
        return "ALIGNED"
    return "WATCH_CONFLICT" if is_watch else "HARD_CONFLICT"


def main() -> int:
    pos = json.loads(POSITIONS.read_text())
    positions = pos.get("positions", [])
    labels = latest_thesis_labels()
    if not labels:
        print(f"[align] WARNING: no backfill labels ({BACKFILL}); run backfill_thesis_direction.py first")

    rows = []
    for p in positions:
        tic = p.get("ticker")
        qty = p.get("quantity")
        side = "LONG" if (qty is None or qty >= 0) else "SHORT"
        label = labels.get(tic)
        algn = alignment_of(side, label)
        rows.append({
            "ts_code": tic, "name": p.get("name"), "weight_pct": p.get("weight_pct"),
            "pnl_pct": p.get("pnl_pct"), "vp_at_entry": p.get("vp_at_entry"),
            "position_side": side,
            "latest_thesis_direction": label,
            "directional_for_capital": label in CAPITAL_LABELS,
            "directional_for_validation": label in VALIDATION_LABELS,
            "alignment": algn,
            "requires_human_review": algn in ("WATCH_CONFLICT", "HARD_CONFLICT"),
        })

    from collections import Counter
    counts = dict(Counter(r["alignment"] for r in rows))
    review = [r for r in rows if r["requires_human_review"]]

    out = {
        "_meta": {
            "read_only": True, "marks_only_no_trades": True,
            "as_of": (pos.get("as_of") or "")[:19],
            "source_positions": str(POSITIONS), "source_backfill": str(BACKFILL),
            "rule_doc": "docs/strategy/PORTFOLIO_THESIS_ALIGNMENT_RULES.md",
            "purpose": ("Mark research↔position disconnects. WATCH_* never auto-trades; "
                        "conflicts flag for HUMAN review; no position is auto-closed."),
        },
        "alignment_counts": counts,
        "n_requires_human_review": len(review),
        "positions": rows,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))

    print("=" * 76)
    print("PORTFOLIO ↔ THESIS ALIGNMENT (read-only marker — no trades)")
    print("=" * 76)
    hdr = f"{'name':<10}{'ticker':<11}{'side':<6}{'thesis':<13}{'pnl%':>8}  alignment"
    print(hdr); print("-" * len(hdr))
    for r in rows:
        flag = "  ⚠ REVIEW" if r["requires_human_review"] else ""
        print(f"{str(r['name'] or '?'):<10}{str(r['ts_code']):<11}{r['position_side']:<6}"
              f"{str(r['latest_thesis_direction']):<13}{(r['pnl_pct'] if r['pnl_pct'] is not None else 0):>+8.1f}  "
              f"{r['alignment']}{flag}")
    print(f"\ncounts: {counts}")
    print(f"requires_human_review: {len(review)} → {[r['ts_code'] for r in review]}")
    print(f"\n[align] wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
