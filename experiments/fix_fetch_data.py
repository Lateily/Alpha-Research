#!/usr/bin/env python3
"""
Experimental draft: generate a reviewable proposal for making scripts/fetch_data.py
load FOCUS_TICKERS and VP_SCORES from public/data/watchlist.json.

This script does NOT modify production files. It reads:

  - scripts/fetch_data.py
  - public/data/watchlist.json

and writes a proposed transformed file to:

  - experiments/fetch_data.watchlist_proposed.py

Run from repo root:

  python3 experiments/fix_fetch_data.py

Production migration still requires Junyan approval and Claude review.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FETCH_DATA = ROOT / "scripts" / "fetch_data.py"
WATCHLIST = ROOT / "public" / "data" / "watchlist.json"
OUT = ROOT / "experiments" / "fetch_data.watchlist_proposed.py"


LOADER_BLOCK = r'''
def _load_watchlist():
    """
    Load focus tickers and VP seed values from public/data/watchlist.json.

    watchlist.json is the single source of truth. This helper keeps fetch_data.py
    aligned with vp_engine.py, signal_confluence.py, position_sizing.py, and the
    dashboard pipeline.

    Returns:
      (focus_tickers, vp_scores)

    focus_tickers:
      {
        "300308.SZ": {
          "yahoo": "300308.SZ",
          "akshare": "300308",
          "exchange": "SZ",
          "name_en": "Innolight",
          "name_zh": "中际旭创"
        }
      }

    vp_scores:
      {
        "300308.SZ": {
          "vp": 79,
          "expectation_gap": 72,
          "fundamental_accel": 80,
          "narrative_shift": 72,
          "low_coverage": 50,
          "catalyst_prox": 80,
          "last_updated": "2026-04-24",
          "wrongIf_e": "...",
          "wrongIf_z": "..."
        }
      }
    """
    wl_path = OUTPUT_DIR / "watchlist.json"
    with open(wl_path, encoding="utf-8") as f:
        wl = json.load(f)

    focus_tickers = {}
    vp_scores = {}

    for ticker, cfg in wl.get("tickers", {}).items():
        seed = cfg.get("vp_seed", {})
        focus_tickers[ticker] = {
            "yahoo": cfg.get("yahoo", ticker),
            "akshare": cfg.get("akshare"),
            "exchange": cfg.get("exchange"),
            "name_en": cfg.get("name_en", ticker),
            "name_zh": cfg.get("name_zh", ticker),
        }
        vp_scores[ticker] = {
            "vp": seed.get("vp", 50),
            "expectation_gap": seed.get("expectation_gap", 50),
            "fundamental_accel": seed.get("fundamental_accel", 50),
            "narrative_shift": seed.get("narrative_shift", 50),
            "low_coverage": seed.get("low_coverage", 50),
            "catalyst_prox": seed.get("catalyst_prox", 50),
            "last_updated": seed.get("last_updated", wl.get("_meta", {}).get("last_updated", "")),
            "wrongIf_e": seed.get("wrongIf_e", ""),
            "wrongIf_z": seed.get("wrongIf_z", ""),
        }

    return focus_tickers, vp_scores


# watchlist.json is the single source of truth.
FOCUS_TICKERS, VP_SCORES = _load_watchlist()
'''


def find_block_end(lines: list[str], start_idx: int) -> int:
    """Return the index after a top-level dict assignment block."""
    brace_depth = 0
    started = False
    for i in range(start_idx, len(lines)):
        line = lines[i]
        brace_depth += line.count("{")
        brace_depth -= line.count("}")
        if "{" in line:
            started = True
        if started and brace_depth == 0:
            return i + 1
    raise RuntimeError(f"Could not find block end from line {start_idx + 1}")


def replace_hardcoded_blocks(src: str) -> str:
    lines = src.splitlines(keepends=True)

    focus_start = next(i for i, line in enumerate(lines) if line.startswith("FOCUS_TICKERS = {"))
    vp_start = next(i for i, line in enumerate(lines) if line.startswith("VP_SCORES = {"))
    vp_end = find_block_end(lines, vp_start)

    # Include the comments immediately above FOCUS_TICKERS and VP_SCORES so the
    # proposal replaces the whole duplicated seed section with one loader.
    section_start = focus_start
    while section_start > 0 and (
        lines[section_start - 1].startswith("#")
        or not lines[section_start - 1].strip()
    ):
        section_start -= 1

    new_lines = lines[:section_start] + [LOADER_BLOCK.strip() + "\n"] + lines[vp_end:]
    proposed = "".join(new_lines)

    # Canonical field should be catalyst_prox. During a production migration, the
    # full chain should be updated together. This proposal keeps a compatibility
    # alias in vp_snapshot only if reviewers decide Dashboard/downstream scripts
    # still require catalyst_proximity temporarily.
    proposed = proposed.replace(
        '"catalyst_proximity":prev.get("catalyst_proximity",seed["catalyst_prox"]),',
        '"catalyst_prox":       prev.get("catalyst_prox", prev.get("catalyst_proximity", seed["catalyst_prox"])),\n'
        '            # temporary alias for current downstream compatibility; remove after full-chain migration\n'
        '            "catalyst_proximity":prev.get("catalyst_proximity", prev.get("catalyst_prox", seed["catalyst_prox"])),',
    )
    return proposed


def main() -> None:
    if not WATCHLIST.exists():
        raise SystemExit(f"Missing watchlist: {WATCHLIST}")
    if not FETCH_DATA.exists():
        raise SystemExit(f"Missing fetch_data.py: {FETCH_DATA}")

    # Validate watchlist shape before producing proposal.
    wl = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    tickers = wl.get("tickers", {})
    if not tickers:
        raise SystemExit("watchlist.json has no tickers")
    for ticker, cfg in tickers.items():
        if "vp_seed" not in cfg:
            raise SystemExit(f"{ticker} missing vp_seed")

    src = FETCH_DATA.read_text(encoding="utf-8")
    proposed = replace_hardcoded_blocks(src)
    OUT.write_text(proposed, encoding="utf-8")

    print(f"Wrote proposal: {OUT}")
    print(f"Watchlist tickers loaded: {len(tickers)}")
    print("No production files were modified.")


if __name__ == "__main__":
    main()
