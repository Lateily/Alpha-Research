#!/usr/bin/env python3
"""strategy_driver.py — end-to-end wiring: screener -> allocator -> book.

Thin integration layer that turns the verified P2 modules into a single
"what would we hold today" run:
  screen_candidates.json (scripts/screen_universe.py output)
    + thesis overlay (ratified LLM directions, for CORE routing)
    -> portfolio_allocator.allocate()
    -> public/data/proposed_portfolio.json  (dual-track core/satellite book)

This is the SNAPSHOT driver (today's proposed book on current data). The
HISTORICAL backtest path is separate: it needs a PIT factor calculator that
recomputes factor exposures as-of each rebalance date from data_history/
(not the precomputed current snapshot) -> feeds backtest_v2.run_backtest.
That PIT factor calculator is the next build (see STATUS.md P2).

HONEST CAVEATS (red line):
  - The screener's `quality` factor is currently inert (roe/margin 0% in
    universe_a.json) -> the proposed book is provisional until the financial
    backfill revives it. data_history now PROVES income/balancesheet are
    fetchable (GHA 2026-05-25), so reviving quality is unblocked.
  - CORE will be sparse: thesis overlay only covers the 4 researched names,
    and the screener's top-N may not surface them -> most/all picks route
    SATELLITE. That is the honest current state (systematic breadth, thin
    deep-research coverage), not a bug.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DATA = REPO_ROOT / "public" / "data"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import portfolio_allocator  # noqa: E402

# Ratified LLM thesis directions (2026-05-17 Path-B/Rule-X arc) used as the
# CORE-routing overlay. Only these names carry a deep thesis today.
RATIFIED_OVERLAY = {
    "002594.SZ": {"direction": "STARTER_CAPPED", "e1_base": True},   # BYD
    "603233.SH": {"direction": "PASS", "e1_base": False},            # 大参林
    "300308.SZ": {"direction": "PASS", "e1_base": False},            # Innolight
    "175.HK":    {"direction": "PASS", "e1_base": False},            # Geely (not A-share)
}


def load_candidates(path: Path) -> list:
    if not path.exists():
        raise SystemExit(f"ERROR: {path} missing — run scripts/screen_universe.py first.")
    data = json.load(path.open())
    return data.get("candidates", [])


def main(argv=None):
    p = argparse.ArgumentParser(description="Wire screener -> allocator -> proposed book.")
    p.add_argument("--candidates", default=str(PUBLIC_DATA / "screen_candidates.json"))
    p.add_argument("--out", default=str(PUBLIC_DATA / "proposed_portfolio.json"))
    p.add_argument("--no-write", action="store_true", help="Print only, do not write.")
    args = p.parse_args(argv)

    candidates = load_candidates(Path(args.candidates))
    result = portfolio_allocator.allocate(candidates, overlay_map=RATIFIED_OVERLAY)
    summary = result.get("summary", {})

    book = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "driver": "strategy_driver.py snapshot mode",
            "candidates_in": len(candidates),
            "overlay_names": list(RATIFIED_OVERLAY.keys()),
            "caveat": (
                "PROVISIONAL: screener quality factor inert (roe/margin not yet "
                "backfilled); CORE sparse (thesis overlay covers 4 names only). "
                "Not a tradeable recommendation — pipeline-shape demo on current data."
            ),
        },
        "summary": summary,
        "positions": result.get("positions", []),
    }

    print(f"candidates_in={len(candidates)} | "
          f"core={summary.get('core_count')} satellite={summary.get('satellite_count')}")
    print(f"core: {summary.get('core_tickers')}")
    print(f"satellite (first 8): {summary.get('satellite_tickers', [])[:8]}")

    if not args.no_write:
        Path(args.out).write_text(json.dumps(book, indent=2, ensure_ascii=False))
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
