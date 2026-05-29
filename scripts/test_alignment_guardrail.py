#!/usr/bin/env python3
"""test_alignment_guardrail.py — contract checks for the thesis↔portfolio guardrail.

Encodes the HARD BOUNDARIES (Junyan 2026-05-29) that make the guardrail safe to
ship. Runnable standalone and in CI. Exit 0 = all contracts hold; 1 = violation.

Contracts:
  C1  alignment_of() marker logic is correct for all 5 cases.
  C2  WATCH_CONFLICT / HARD_CONFLICT ⇒ requires_human_review; ALIGNED / NO_* ⇒ not.
  C3  STATIC: no guardrail-chain script writes positions.json / analytics.json /
      snapshots.json (scan for write ops on protected files).
  C4  STATIC: no trade-execution / order / auto-close calls in the chain
      (place_order/submit_order/execute_trade/close_position/...).
  C5  RUNTIME: running the full chain (backfill→alignment→ledger) leaves
      positions.json / analytics.json / snapshots.json byte-for-byte UNCHANGED.
  C6  The alignment output is marker-only: marks_only_no_trades flag set, every
      position carries requires_human_review, and no auto-action field exists.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

PROTECTED = ["positions.json", "analytics.json", "snapshots.json"]
CHAIN = ["portfolio_thesis_alignment.py", "backfill_thesis_direction.py",
         "core_validation_ledger.py", "fetch_hk_prices.py"]
TRADE_PATTERNS = [r"place_order", r"submit_order", r"execute_trade", r"close_position",
                  r"\.buy\(", r"\.sell\(", r"create_order", r"send_order", r"cancel_order"]
WRITE_HINTS = [".write_text(", ".write(", "json.dump(", ".to_parquet(", ".to_json(",
               ".to_csv(", "open("]


def _sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def c1_logic() -> list[str]:
    from portfolio_thesis_alignment import alignment_of
    cases = [
        ("LONG", "LONG", "ALIGNED"), ("SHORT", "SHORT", "ALIGNED"),
        ("LONG", "WATCH_LONG", "ALIGNED"),               # same-side watch
        ("LONG", "WATCH_SHORT", "WATCH_CONFLICT"),       # opposite watch
        ("SHORT", "WATCH_LONG", "WATCH_CONFLICT"),
        ("LONG", "SHORT", "HARD_CONFLICT"),              # opposite capital
        ("SHORT", "LONG", "HARD_CONFLICT"),
        ("LONG", "PASS", "NO_CAPITAL_THESIS"),
        ("LONG", "UNRESOLVED", "NO_CAPITAL_THESIS"),
        ("LONG", None, "NO_THESIS"),
    ]
    errs = []
    for side, label, expect in cases:
        got = alignment_of(side, label)
        if got != expect:
            errs.append(f"C1 alignment_of({side},{label}) = {got}, expected {expect}")
    return errs


def c3_c4_static() -> list[str]:
    errs = []
    for fn in CHAIN:
        p = REPO / "scripts" / fn
        if not p.exists():
            errs.append(f"C3/C4 chain script missing: {fn}")
            continue
        for i, line in enumerate(p.read_text().splitlines(), 1):
            low = line.strip()
            if low.startswith("#"):
                continue
            # C3: protected file on a line that also looks like a write
            for prot in PROTECTED:
                if prot in line and any(h in line for h in WRITE_HINTS):
                    # allow read: open(..., ) without 'w'; .read_text(); json.loads
                    is_write = ("'w'" in line or '"w"' in line or "'a'" in line
                                or ".write" in line or "json.dump(" in line
                                or ".to_parquet(" in line or ".to_json(" in line)
                    if is_write:
                        errs.append(f"C3 {fn}:{i} writes protected {prot}: {low[:80]}")
            # C4: trade-execution call
            for pat in TRADE_PATTERNS:
                if re.search(pat, line):
                    errs.append(f"C4 {fn}:{i} trade-execution pattern /{pat}/: {low[:80]}")
    return errs


def c5_runtime() -> list[str]:
    """Run the full chain; protected paper-state files must be byte-identical after."""
    errs = []
    paths = {f: REPO / "public" / "data" / f for f in PROTECTED}
    before = {f: _sha(p) for f, p in paths.items()}
    for script in ["backfill_thesis_direction.py", "portfolio_thesis_alignment.py",
                   "core_validation_ledger.py"]:
        r = subprocess.run([sys.executable, str(REPO / "scripts" / script)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            errs.append(f"C5 {script} exited {r.returncode}: {r.stderr.strip()[:120]}")
    after = {f: _sha(p) for f, p in paths.items()}
    for f in PROTECTED:
        if before[f] != after[f]:
            errs.append(f"C5 VIOLATION: {f} changed after running the chain (guardrail must not touch paper state)")
    return errs


def c2_c6_contract() -> list[str]:
    errs = []
    p = REPO / "public" / "data" / "portfolio_thesis_alignment.json"
    if not p.exists():
        return ["C6 alignment JSON missing (run portfolio_thesis_alignment.py)"]
    d = json.loads(p.read_text())
    meta = d.get("_meta", {})
    if not meta.get("marks_only_no_trades"):
        errs.append("C6 _meta.marks_only_no_trades is not True")
    forbidden_keys = {"order", "action", "trade", "execute", "auto_close", "auto_trade"}
    for pos in d.get("positions", []):
        if "requires_human_review" not in pos:
            errs.append(f"C6 position {pos.get('ts_code')} missing requires_human_review")
        bad = forbidden_keys & set(pos.keys())
        if bad:
            errs.append(f"C6 position {pos.get('ts_code')} has auto-action key(s) {bad}")
        # C2 semantics
        algn = pos.get("alignment")
        rhr = pos.get("requires_human_review")
        if algn in ("WATCH_CONFLICT", "HARD_CONFLICT") and not rhr:
            errs.append(f"C2 {pos.get('ts_code')} {algn} must require review")
        if algn in ("ALIGNED", "NO_CAPITAL_THESIS", "NO_THESIS") and rhr:
            errs.append(f"C2 {pos.get('ts_code')} {algn} must NOT require review")
    return errs


def main() -> int:
    checks = [("C1 marker logic", c1_logic), ("C3/C4 static write+trade scan", c3_c4_static),
              ("C5 runtime paper-state invariance", c5_runtime),
              ("C2/C6 marker-only contract", c2_c6_contract)]
    all_errs = []
    for name, fn in checks:
        errs = fn()
        status = "PASS" if not errs else f"FAIL ({len(errs)})"
        print(f"  [{status}] {name}")
        all_errs += errs
    print()
    if all_errs:
        print("GUARDRAIL CONTRACT VIOLATIONS:")
        for e in all_errs:
            print(f"  ✗ {e}")
        return 1
    print("✓ ALL GUARDRAIL CONTRACTS HOLD — marker-only, no trades, paper state untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
