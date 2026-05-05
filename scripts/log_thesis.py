#!/usr/bin/env python3
"""log_thesis.py — Bridge 8 attribution scaffold (2026-05-05)

Extract the falsifiable structure from a thesis JSON and log it to
public/data/thesis_attribution/<TICKER>_<DATE>.json. This is the SCAFFOLD
for Bridge 8 (backtest attribution) — it captures what the thesis claimed
at ship time so that AT HORIZON we can check whether wrongIf / rightIf
conditions actually resolved as predicted. Without this log, attribution
post-hoc requires reading every old thesis JSON, parsing fields, and
hoping the model emitted reproducible structure.

Usage:
  python3 scripts/log_thesis.py <ticker> <thesis_json_path>

  # Examples:
  python3 scripts/log_thesis.py 700.HK \
    docs/research/factcheck/700HK_thesis_2026-05-05_1438BST.json

WHAT THIS DOES:
  - Reads thesis JSON (raw thesis or full /api/research response)
  - Extracts step_1_catalyst, step_5_proves_right_if, step_6_proves_wrong_if,
    step_7_variant_view.expected_pnl_asymmetry, step_4_quantification
  - Records git HEAD commit so the thesis-shipping context is reproducible
  - Writes audit log file (latest pointer + dated artifact, same dual-output
    pattern as scripts/thesis_factcheck.py)
  - Leaves outcomes_recorded_at = null and outcomes = [] for future
    population by a separate (not yet built) outcome-tracker.

WHAT THIS DOES NOT DO:
  - Does NOT verify outcomes. That requires news/data integration to detect
    when wrongIf/rightIf conditions actually fire. Future KR.
  - Does NOT compute attribution scores. n=0 trades attributed today; need
    n≥10 with paired outcomes before any hit-rate metric is meaningful.
  - Does NOT auto-fetch a fresh thesis. Same discipline as
    scripts/thesis_factcheck.py — log only theses that exist on disk.
  - Does NOT update the prediction_log.json that already lives at the
    project root (CLAUDE.md §"Prediction Log Track Record"). That log is
    maintained manually for high-conviction predictions only. This new
    attribution log is meant to capture EVERY thesis automatically
    so we eventually have n large enough for backtest. Two complementary
    surfaces; future work merges them.

OUTPUT SCHEMA:

  {
    "ticker": "700.HK",
    "thesis_logged_at": "2026-05-05T14:50:00+00:00",
    "thesis_source": "docs/research/factcheck/700HK_thesis_2026-05-05_1438BST.json",
    "thesis_source_commit": "aefc16b",
    "thesis_protocol_version": "v2",
    "catalyst": {
      "event": "...",
      "date_or_window": "2026-03-19 (...)",
      "type": "earnings_revision",
      "source": "..."
    },
    "rightIf_conditions": [...],         // step_5_proves_right_if
    "wrongIf_conditions": [...],         // step_6_proves_wrong_if
    "what_changes_our_mind": "...",      // step_3_evidence.contrarian_view.what_changes_our_mind
    "expected_pnl_asymmetry": {
      "upside_if_right": "...",
      "downside_if_wrong": "...",
      "reward_to_risk": "..."
    },
    "quantification": {
      "metric_target": "...",
      "predicted_value": "...",
      "predicted_range": {"low": "...", "mid": "...", "high": "..."},
      "predicted_horizon": "...",
      "confidence": 0.62
    },
    "outcomes_recorded_at": null,  // populated later by outcome-tracker
    "outcomes": []                  // each: {condition, met_at, met_status, evidence}
  }
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DATA = REPO_ROOT / 'public' / 'data'


def get(d: Any, *path: str, default: Any = None) -> Any:
    """Safe dotted-path getter."""
    for p in path:
        if isinstance(d, dict) and p in d:
            d = d[p]
        else:
            return default
    return d


def load_thesis(path: Path) -> dict:
    with path.open() as f:
        d = json.load(f)
    return d.get('data', d) if isinstance(d, dict) else d


def get_git_head() -> Optional[str]:
    """Return short git HEAD SHA, or None if not in a git repo / git unavailable."""
    try:
        out = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def extract_attribution(thesis: dict) -> dict:
    """Pull the falsifiable structure out of a thesis JSON."""
    catalyst = get(thesis, 'step_1_catalyst', default={})
    return {
        'thesis_protocol_version': thesis.get('thesis_protocol_version', 'unknown'),
        'catalyst': {
            'event': catalyst.get('catalyst_event'),
            'date_or_window': catalyst.get('catalyst_date_or_window'),
            'type': catalyst.get('catalyst_type'),
            'source': catalyst.get('catalyst_source'),
        },
        'mechanism_chain_length': len(get(thesis, 'step_2_mechanism', 'mechanism_chain', default=[])),
        'rightIf_conditions': get(thesis, 'step_5_proves_right_if', default=[]),
        'wrongIf_conditions': get(thesis, 'step_6_proves_wrong_if', default=[]),
        'what_changes_our_mind': get(thesis, 'step_3_evidence', 'contrarian_view', 'what_changes_our_mind'),
        'variant_view_one_sentence': get(thesis, 'step_7_variant_view', 'variant_view_one_sentence'),
        'time_to_resolution': get(thesis, 'step_7_variant_view', 'time_to_resolution'),
        'expected_pnl_asymmetry': get(thesis, 'step_7_variant_view', 'expected_pnl_asymmetry', default={}),
        'quantification': get(thesis, 'step_4_quantification', default={}),
        'qc_quality_at_log_time': get(thesis, '_quality', default={}),
    }


def main():
    if len(sys.argv) != 3 or sys.argv[1] in ('-h', '--help'):
        sys.exit(__doc__)

    ticker = sys.argv[1]
    thesis_path = Path(sys.argv[2]).resolve()
    if not thesis_path.exists():
        sys.exit(f'ERROR: thesis file not found: {thesis_path}')

    thesis = load_thesis(thesis_path)
    if thesis.get('ticker') and thesis.get('ticker') != ticker:
        print(f'WARN: thesis JSON ticker={thesis.get("ticker")} != argv ticker={ticker}', file=sys.stderr)

    attribution = extract_attribution(thesis)
    out_dir = PUBLIC_DATA / 'thesis_attribution'
    out_dir.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    ticker_safe = ticker.replace('.', '_')
    out_file_latest = out_dir / f'{ticker_safe}.json'
    out_file_dated = out_dir / f'{ticker_safe}_{today}.json'

    record = {
        'ticker': ticker,
        'thesis_logged_at': datetime.now(timezone.utc).isoformat(),
        'thesis_source': str(thesis_path.relative_to(REPO_ROOT)) if str(thesis_path).startswith(str(REPO_ROOT)) else str(thesis_path),
        'thesis_source_commit': get_git_head(),
        **attribution,
        # Future-population fields — left null/empty for outcome tracker.
        'outcomes_recorded_at': None,
        'outcomes': [],
    }

    payload = json.dumps(record, indent=2, ensure_ascii=False)
    out_file_latest.write_text(payload)
    out_file_dated.write_text(payload)

    # ── Console summary ────────────────────────────────────────────────
    print(f'═══ Thesis Attribution Log — {ticker} ═══')
    print(f'Thesis source: {thesis_path}')
    print(f'Logged at:     {record["thesis_logged_at"]}')
    print(f'Git HEAD:      {record["thesis_source_commit"] or "unknown"}')
    print()
    print(f'Catalyst:       "{(record["catalyst"]["event"] or "")[:80]}"')
    print(f'Window:         "{record["catalyst"]["date_or_window"] or "—"}"')
    print(f'rightIf:        {len(record["rightIf_conditions"])} conditions')
    print(f'wrongIf:        {len(record["wrongIf_conditions"])} conditions')
    print(f'what changes:   "{(record["what_changes_our_mind"] or "")[:80]}"')
    rr = record['expected_pnl_asymmetry']
    print(f'reward_to_risk: {rr.get("reward_to_risk", "—")}')
    print(f'time_to_resol:  {record["time_to_resolution"] or "—"}')
    print()
    print(f'Files written:')
    print(f'  latest: {out_file_latest.relative_to(REPO_ROOT)}')
    print(f'  dated:  {out_file_dated.relative_to(REPO_ROOT)}')
    print()
    print('Outcome tracking: NOT YET BUILT. outcomes_recorded_at=null,')
    print('outcomes=[]. Future KR will check wrongIf/rightIf at horizon.')


if __name__ == '__main__':
    main()
