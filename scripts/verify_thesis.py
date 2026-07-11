#!/usr/bin/env python3
"""verify_thesis.py — Bridge 8 outcome verification scaffold

Pairs with follow_thesis.py. Goal: when a paper trade closes (catalyst
date passes / target hit / stop hit), record OUTCOME of the thesis —
did each wrongIf/rightIf condition actually trigger? What was the
realized P&L? What did we learn?

MVP scope:
  - Auto-resolve price-based outcomes from follow_thesis output
  - Detect status transitions (ACTIVE → TARGET_HIT / STOPPED_OUT / EXPIRED)
  - Flag wrongIf/rightIf conditions for HUMAN REVIEW with structured form
  - Write outcomes to public/data/thesis_outcomes/<TICKER>.json
  - Aggregate into outcomes_summary.json (hit rate by direction, by quality)

NOT YET (deferred, larger KRs):
  - NLP parsing of wrongIf conditions to auto-detect "Q2 GM below 15%"
    from new fin_*.json prints
  - Auto-detect news events ("EU tariff +25% confirmed", "Stellantis exits")
  - Cross-check thesis predicted_value vs realized financial metric

Usage:
  python3 scripts/verify_thesis.py --all
  python3 scripts/verify_thesis.py --ticker 002594.SZ

Output:
  public/data/thesis_outcomes/<TICKER_safe>.json
  public/data/thesis_outcomes/summary.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DATA = REPO_ROOT / 'public' / 'data'


def safe_load(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def to_underscore(ticker: str) -> str:
    return ticker.replace('.', '_')


def verify_one(ticker: str, dry_run: bool = False) -> Optional[dict]:
    """Verify outcomes for one ticker's thesis. Returns the outcome record."""
    safe = to_underscore(ticker)
    paper = safe_load(PUBLIC_DATA / 'paper_trades' / f'{safe}.json')
    attr = safe_load(PUBLIC_DATA / 'thesis_attribution' / f'{safe}.json')

    if not paper or not attr:
        return None
    if paper.get('_status') == 'skipped_non_actionable':
        return None

    status = paper.get('current_status')
    catalyst_passed = paper.get('days_to_catalyst') is not None and paper['days_to_catalyst'] < 0

    # Determine outcome category
    outcome_category = None
    if status == 'TARGET_HIT':
        outcome_category = 'WIN — price hit upside target'
    elif status == 'STOPPED_OUT':
        outcome_category = 'LOSS — price hit downside stop'
    elif status == 'EXPIRED' or catalyst_passed:
        outcome_category = 'EXPIRED — catalyst window passed'
    elif status == 'CATALYST_DUE':
        outcome_category = 'PENDING — catalyst due within 14d'
    else:
        outcome_category = 'PENDING — position still active'

    # Build conditions structured for HUMAN review
    # Each condition gets fields: original_text, verification_status, verified_at, verified_by, evidence
    def to_review_form(conditions: list, kind: str) -> list:
        out = []
        for i, c in enumerate(conditions):
            out.append({
                'index': i,
                'kind': kind,
                'original_text': c,
                'verification_status': 'PENDING_HUMAN_REVIEW',
                # KR3 (Junyan 2026-05-15): conditions are now MECHANIZED
                # at generation (metric+op+threshold @ named disclosure
                # event | source | if_not_disclosed). Reviewer resolves to
                # one of these 4 — INSUFFICIENT_DISCLOSURE is distinct from
                # INCONCLUSIVE: the former = company didn't disclose the
                # metric at the catalyst (unjudgeable, itself a signal);
                # the latter = disclosed but ambiguous.
                'verification_vocab': [
                    'TRIGGERED', 'NOT_TRIGGERED',
                    'INSUFFICIENT_DISCLOSURE', 'INCONCLUSIVE',
                ],
                'verified_at': None,
                'verified_by': None,
                'evidence_observed': None,  # to be filled by reviewer
                'auto_signal': None,  # could be price-based hint
            })
        return out

    right_conds = to_review_form(attr.get('rightIf_conditions', []), 'rightIf')
    wrong_conds = to_review_form(attr.get('wrongIf_conditions', []), 'wrongIf')

    # Auto-signal hints: for now, mark whether thesis direction's price-based
    # threshold was hit, which can inform but not REPLACE condition verification
    if status == 'TARGET_HIT':
        for c in right_conds:
            c['auto_signal'] = 'price reached upside target — partial confirmation, but specific condition still needs human verification (e.g., did GM print above 15%? did EPS revise up 5%?)'
    elif status == 'STOPPED_OUT':
        for c in wrong_conds:
            c['auto_signal'] = 'price reached downside stop — partial confirmation that thesis is wrong'

    record = {
        'ticker': ticker,
        'verification_run_at': datetime.now(timezone.utc).isoformat(),
        'thesis_source': attr.get('thesis_source'),
        'thesis_source_commit': attr.get('thesis_source_commit'),
        'thesis_logged_at': attr.get('thesis_logged_at'),
        'direction': paper.get('direction'),
        'entry_date': paper.get('entry_date'),
        'entry_price': paper.get('entry_price'),
        'current_price_at_verification': paper.get('current_price'),
        'return_since_entry_pct': paper.get('return_since_entry_pct'),
        'current_status': status,
        'outcome_category': outcome_category,
        'catalyst_window': paper.get('catalyst_window'),
        'days_to_catalyst': paper.get('days_to_catalyst'),
        'rightIf_verification': right_conds,
        'wrongIf_verification': wrong_conds,
        'what_changes_our_mind': paper.get('what_changes_our_mind'),
        'reviewer_notes': '',  # human-fillable
        'verified_final_outcome': None,  # WIN | LOSS | PARTIAL | UNCLEAR — to be set by reviewer
        '_methodology_note': (
            'MVP scaffold: this record carries the wrongIf/rightIf as PENDING_HUMAN_REVIEW. '
            'KR3 (Junyan 2026-05-15): conditions are MECHANIZED at generation so they are '
            'judgeable at the named disclosure event. When the catalyst occurs (e.g., '
            '2026-08-28 BYD H1 print) a human (Junyan) or future NLP/data pass marks each '
            'condition as one of: TRIGGERED | NOT_TRIGGERED | INSUFFICIENT_DISCLOSURE | '
            'INCONCLUSIVE, with evidence. INSUFFICIENT_DISCLOSURE (issuer did not disclose '
            'the metric) is tracked separately from INCONCLUSIVE (disclosed but ambiguous) '
            'and from a clean TRIGGERED/NOT_TRIGGERED — the split is itself a calibration '
            'signal on how falsifiable our conditions actually were. '
            'Once all conditions resolved, set verified_final_outcome to compute hit rate '
            'into outcomes_summary.'
        ),
    }

    if not dry_run:
        out_path = PUBLIC_DATA / 'thesis_outcomes' / f'{safe}.json'
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str))

    return record


def build_outcomes_summary(records: list, dry_run: bool = False) -> dict:
    """Aggregate outcome summary across all verified theses."""
    summary = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'total_theses_tracked': len(records),
        'by_status': {},
        'by_direction': {},
        'verified_outcomes': [],
        'pending_outcomes': [],
        'hit_rate': None,
        'avg_return_pct': None,
    }
    for r in records:
        if not r:
            continue
        st = r.get('current_status', 'UNKNOWN')
        d = r.get('direction', 'UNKNOWN')
        summary['by_status'][st] = summary['by_status'].get(st, 0) + 1
        summary['by_direction'][d] = summary['by_direction'].get(d, 0) + 1

        if r.get('verified_final_outcome'):
            summary['verified_outcomes'].append({
                'ticker': r['ticker'],
                'direction': d,
                'outcome': r['verified_final_outcome'],
                'return_pct': r.get('return_since_entry_pct'),
                'thesis_logged_at': r.get('thesis_logged_at'),
            })
        else:
            summary['pending_outcomes'].append({
                'ticker': r['ticker'],
                'direction': d,
                'status': st,
                'days_to_catalyst': r.get('days_to_catalyst'),
                'thesis_logged_at': r.get('thesis_logged_at'),
            })

    closed = [v for v in summary['verified_outcomes']]
    if closed:
        wins = sum(1 for c in closed if c['outcome'] == 'WIN')
        summary['hit_rate'] = round(wins / len(closed) * 100, 1)
        returns = [c['return_pct'] for c in closed if c['return_pct'] is not None]
        if returns:
            summary['avg_return_pct'] = round(sum(returns) / len(returns), 2)

    out_path = PUBLIC_DATA / 'thesis_outcomes' / 'summary.json'
    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return summary


def main():
    p = argparse.ArgumentParser(description='Bridge-8 thesis outcome verification scaffold.')
    p.add_argument('--ticker', help='Verify single ticker')
    p.add_argument('--all', action='store_true', help='Verify all tracked theses')
    p.add_argument('--dry-run', action='store_true', help='No file writes')
    args = p.parse_args()

    if not args.ticker and not args.all:
        p.error('Specify --ticker OR --all')

    paper_dir = PUBLIC_DATA / 'paper_trades'

    if args.all:
        tickers = []
        if paper_dir.exists():
            for f in sorted(paper_dir.iterdir()):
                if f.name == 'summary.json' or not f.name.endswith('.json'):
                    continue
                if '_' in f.stem:
                    parts = f.stem.rsplit('_', 1)
                    if len(parts) == 2:
                        tickers.append(f'{parts[0]}.{parts[1]}')
    else:
        tickers = [args.ticker]

    print(f'=== Bridge-8 outcome verifier ===', file=sys.stderr)
    print(f'Verifying {len(tickers)} ticker(s): {tickers}', file=sys.stderr)
    print(file=sys.stderr)

    records = []
    for t in tickers:
        rec = verify_one(t, dry_run=args.dry_run)
        if rec:
            records.append(rec)
            print(f'  {t}: {rec["direction"]} entry {rec["entry_date"]} @ {rec["entry_price"]}, current return {rec["return_since_entry_pct"]}%, status {rec["current_status"]}', file=sys.stderr)
            print(f'    outcome category: {rec["outcome_category"]}', file=sys.stderr)
            print(f'    conditions awaiting verification: {len(rec["rightIf_verification"])} rightIf + {len(rec["wrongIf_verification"])} wrongIf', file=sys.stderr)

    summary = build_outcomes_summary(records, dry_run=args.dry_run)
    print(file=sys.stderr)
    print(f'=== Summary ===', file=sys.stderr)
    print(f'Total tracked: {summary["total_theses_tracked"]}', file=sys.stderr)
    print(f'By status: {summary["by_status"]}', file=sys.stderr)
    print(f'By direction: {summary["by_direction"]}', file=sys.stderr)
    print(f'Verified outcomes: {len(summary["verified_outcomes"])}, Pending: {len(summary["pending_outcomes"])}', file=sys.stderr)
    if summary.get('hit_rate') is not None:
        print(f'Hit rate (n={len(summary["verified_outcomes"])}): {summary["hit_rate"]}% | Avg return: {summary["avg_return_pct"]}%', file=sys.stderr)


if __name__ == '__main__':
    main()
