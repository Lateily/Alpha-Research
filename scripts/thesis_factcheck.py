#!/usr/bin/env python3
"""thesis_factcheck.py — KR-FC.2 (2026-05-05)

Cross-check numerical multiplier claims in a thesis JSON against ingested
live data (public/data/market_data.json).

Closes the structurally-invisible failure mode surfaced in
docs/research/factcheck/700HK_pilot_2026-05-05.md §A2: thesis emits
"current ~17x forward P/E" but yahoo's pe_forward = 12.16x (the 17x
is actually trailing). Structural validator (api/research.js
validateThesisQuality) does not cross-check multiplier claims against
live data.

Usage:
  python3 scripts/thesis_factcheck.py <ticker> <thesis_json_path>

  # Examples:
  python3 scripts/thesis_factcheck.py 700.HK \
    docs/research/factcheck/700HK_thesis_2026-05-05_1255BST.json

Exit code: 0 = no MISMATCH found; 1 = at least 1 MISMATCH.
Side effect: writes JSON report to public/data/thesis_factcheck/<TICKER>_<DATE>.json.

WHAT THIS DOES NOT DO (intentional scope discipline):
- Does NOT check non-multiplier claims (segment revenue, GM, growth rate).
  Those need quarterly/segment data not currently ingested for HK tickers
  — see pilot doc §3 systemic gap analysis.
- Does NOT check temporal validity. That is FC.1 in api/research.js
  validateThesisQuality.
- Does NOT produce a composite "fact-check score". Per pilot README §"What
  the pilot is NOT", composite scoring would create a new Goodhart target.
  Output is per-claim status (MATCH / MISMATCH / UNVERIFIABLE).
- Does NOT auto-fetch from /api/research. Save the thesis JSON locally
  first (curl / API console / manual export) — keeps API-token spending
  intentional and the input artifact reproducible.
"""

from __future__ import annotations  # PEP 563 — defer type-hint evaluation for Python 3.9 compat (`X | None` syntax)

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DATA = REPO_ROOT / 'public' / 'data'
TOLERANCE_PCT = 5.0  # ±5% tolerance for MATCH (numeric noise + FX margin)

# Multiplier claim patterns (priority-ordered: most specific first).
# Each entry: (regex, ground_truth_field_in_yahoo_fundamentals, human_label).
# Patterns operate inside a single string node; consumed character spans
# are tracked to avoid double-matching (e.g., "17x forward P/E" should match
# pe_forward only, not also pe_trailing).
MULTIPLIER_PATTERNS = [
    (r'\b(\d+(?:\.\d+)?)\s*[xX]\s+forward\s+P/?E\b', 'pe_forward', 'forward P/E'),
    (r'\b(\d+(?:\.\d+)?)\s*[xX]\s+EV\s*/\s*EBITDA\b', 'ev_ebitda', 'EV/EBITDA'),
    (r'\b(\d+(?:\.\d+)?)\s*[xX]\s+P\s*/\s*S\b', 'ps_ratio', 'P/S'),
    (r'\b(\d+(?:\.\d+)?)\s*[xX]\s+(?:current\s+|trailing\s+|TTM\s+)?P/?E\b',
     'pe_trailing', 'P/E (trailing)'),
]


def load_thesis(path: Path) -> dict:
    """Accept either raw thesis (top-level step_1_catalyst etc.) or the full
    /api/research response (wrapped in .data)."""
    with path.open() as f:
        d = json.load(f)
    return d.get('data', d) if isinstance(d, dict) else d


def load_ground_truth(ticker: str) -> tuple[dict, dict]:
    """Return (fundamentals, price) from market_data.yahoo[ticker]."""
    md_path = PUBLIC_DATA / 'market_data.json'
    if not md_path.exists():
        sys.exit(f'ERROR: missing {md_path} — run pipeline fetch_data.py first')
    with md_path.open() as f:
        md = json.load(f)
    yahoo_t = md.get('yahoo', {}).get(ticker, {})
    if not yahoo_t:
        sys.exit(f'ERROR: no yahoo data for {ticker} in {md_path}')
    return yahoo_t.get('fundamentals', {}), yahoo_t.get('price', {})


def extract_claims(thesis: dict) -> list[dict]:
    """Walk all string nodes in thesis, extract multiplier claims with context.
    Tracks consumed char spans per node so most-specific pattern wins."""
    claims = []

    def walk(node, path):
        if isinstance(node, str):
            consumed_spans = []  # list of (start, end)
            for pattern, gt_field, label in MULTIPLIER_PATTERNS:
                for m in re.finditer(pattern, node, flags=re.IGNORECASE):
                    if any(s <= m.start() < e or s < m.end() <= e
                           for s, e in consumed_spans):
                        continue  # overlap — skip
                    val = float(m.group(1))
                    snippet = node[max(0, m.start() - 40):m.end() + 40].strip()
                    claims.append({
                        'thesis_path': path,
                        'matched_text': m.group(0).strip(),
                        'claimed_value': val,
                        'gt_field': gt_field,
                        'label': label,
                        'context_snippet': snippet,
                    })
                    consumed_spans.append((m.start(), m.end()))
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, f'{path}.{k}' if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f'{path}[{i}]')

    walk(thesis, '')
    return claims


def cross_check(claim: dict, fundamentals: dict) -> tuple[str, float | None, float | None]:
    """Diff claim vs ground truth. Returns (status, diff_pct, gt_value)."""
    gt = fundamentals.get(claim['gt_field'])
    if gt is None or gt == 0:
        return 'UNVERIFIABLE', None, None
    diff_pct = (claim['claimed_value'] - gt) / gt * 100
    if abs(diff_pct) <= TOLERANCE_PCT:
        return 'MATCH', diff_pct, gt
    return 'MISMATCH', diff_pct, gt


def main():
    if len(sys.argv) != 3 or sys.argv[1] in ('-h', '--help'):
        sys.exit(__doc__)

    ticker = sys.argv[1]
    thesis_path = Path(sys.argv[2]).resolve()
    if not thesis_path.exists():
        sys.exit(f'ERROR: thesis file not found: {thesis_path}')

    thesis = load_thesis(thesis_path)
    fundamentals, price = load_ground_truth(ticker)
    claims = extract_claims(thesis)

    # ── Report header ───────────────────────────────────────────────────
    print(f'═══ Thesis Fact-Check (multiplier cross-check) — {ticker} ═══')
    print(f'Thesis source:        {thesis_path}')
    print(f'Ground truth source:  public/data/market_data.json yahoo.{ticker}.fundamentals')
    print(f'Live price (last):    {price.get("last", "N/A")}  (52w {price.get("low_52w", "N/A")}–{price.get("high_52w", "N/A")})')
    print(f'Tolerance:            ±{TOLERANCE_PCT}%')
    print(f'Multiplier claims:    {len(claims)} found')
    print()

    if not claims:
        print('No multiplier claims matched. Either the thesis avoids multiples')
        print('or MULTIPLIER_PATTERNS needs expansion. Patterns currently covered:')
        for _, gt_field, label in MULTIPLIER_PATTERNS:
            print(f'  - {label:20s} → fundamentals.{gt_field}')
        sys.exit(0)

    # ── Per-claim cross-check ───────────────────────────────────────────
    summary = {'MATCH': 0, 'MISMATCH': 0, 'UNVERIFIABLE': 0}
    results = []
    for c in claims:
        status, diff_pct, gt = cross_check(c, fundamentals)
        c['status'] = status
        c['diff_pct'] = diff_pct
        c['gt_value'] = gt
        results.append(c)
        summary[status] += 1

    # ── Print table ─────────────────────────────────────────────────────
    marker = {'MATCH': '✓', 'MISMATCH': '✗', 'UNVERIFIABLE': '?'}
    for r in results:
        diff_str = f'{r["diff_pct"]:+.1f}%' if r['diff_pct'] is not None else 'N/A'
        gt_str = f'{r["gt_value"]:.2f}' if r['gt_value'] is not None else 'N/A'
        print(f'  [{marker[r["status"]]}] {r["label"]:18s} | claimed: {r["claimed_value"]:6.2f}x | actual: {gt_str:>7s}x | Δ {diff_str:>8s} | {r["status"]}')
        print(f'      context:  ...{r["context_snippet"][:120]}...')
        print(f'      path:     {r["thesis_path"]}')
        print()

    print(f'Summary: {summary["MATCH"]} MATCH / {summary["MISMATCH"]} MISMATCH / {summary["UNVERIFIABLE"]} UNVERIFIABLE')

    # ── Save report ─────────────────────────────────────────────────────
    # Two files written:
    # 1. <TICKER>.json — "latest" pointer (frontend reads this; no date guessing)
    # 2. <TICKER>_<DATE>.json — date-stamped audit trail (git history serves
    #    as multi-day archive). On same-day re-runs the date-stamped file is
    #    overwritten; differences across days remain in git log.
    out_dir = PUBLIC_DATA / 'thesis_factcheck'
    out_dir.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    ticker_safe = ticker.replace('.', '_')
    out_file_latest = out_dir / f'{ticker_safe}.json'
    out_file_dated = out_dir / f'{ticker_safe}_{today}.json'
    report = {
        'ticker': ticker,
        'fact_checked_at': datetime.now(timezone.utc).isoformat(),
        'thesis_source': str(thesis_path.relative_to(REPO_ROOT)) if str(thesis_path).startswith(str(REPO_ROOT)) else str(thesis_path),
        'ground_truth_source': 'public/data/market_data.json',
        'tolerance_pct': TOLERANCE_PCT,
        'live_price': price.get('last'),
        'results': results,
        'summary': summary,
    }
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    out_file_latest.write_text(payload)
    out_file_dated.write_text(payload)
    print(f'\nReports saved:')
    print(f'  latest: {out_file_latest.relative_to(REPO_ROOT)}')
    print(f'  dated:  {out_file_dated.relative_to(REPO_ROOT)}')
    print(f'Exit code: {1 if summary["MISMATCH"] > 0 else 0} ({"MISMATCH found" if summary["MISMATCH"] > 0 else "no mismatch"})')

    # ── Exit code ───────────────────────────────────────────────────────
    sys.exit(1 if summary['MISMATCH'] > 0 else 0)


if __name__ == '__main__':
    main()
