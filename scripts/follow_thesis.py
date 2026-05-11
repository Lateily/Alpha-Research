#!/usr/bin/env python3
"""follow_thesis.py — Bridge 8 paper-trading daily tracker

Reads thesis_attribution/<TICKER>.json (output of log_thesis.py) and tracks
each thesis as a paper trade. Daily run computes return-since-entry, checks
if price hit upside target / downside stop, flags catalyst-window expiry.

Usage:
  # Track ALL theses in attribution log:
  python3 scripts/follow_thesis.py --all

  # Track single ticker:
  python3 scripts/follow_thesis.py --ticker 002594.SZ

  # Dry-run (no file writes):
  python3 scripts/follow_thesis.py --all --dry-run

Output (per ticker):
  public/data/paper_trades/<TICKER_safe>.json — current state + daily_log
  public/data/paper_trades/summary.json — aggregate across all positions

WHAT THIS DOES (MVP scope):
  - Reads thesis_attribution to get entry conditions (direction, R/R, catalyst)
  - Computes entry price by looking up ohlc_*.json for thesis_logged_at date
  - Reads current price from market_data.json yahoo[ticker].price.last
  - Computes return-since-entry, days_held, days_to_catalyst
  - Status: ACTIVE | TARGET_HIT | STOPPED_OUT | CATALYST_DUE | EXPIRED
  - Appends today's snapshot to daily_log
  - wrongIf/rightIf conditions: kept as text, marked _verification_pending
    (semantic parsing is verify_thesis.py's job, future iteration)

WHAT THIS DOES NOT DO (yet):
  - Parse wrongIf/rightIf into structured metric thresholds (future:
    "Q2 GM below 15%" → check fin_*.json once Q2 prints)
  - Auto-detect catalyst events (earnings releases, FDA decisions, etc.)
  - News-event verification (e.g., "Stellantis exits China" — manual flag)
  - Re-rate thesis if data context shifts (separate KR)

Pipeline integration: call this daily in fetch-data.yml AFTER market_data.json
refresh. Append to daily_log produces price-trajectory time series for backtest.
"""

from __future__ import annotations

import argparse
import json
import re
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


def parse_pct(text: Optional[str]) -> Optional[float]:
    """Extract first percentage number from text. '+25% to +35%' → 25.0,
    '-9%' → -9.0, '2.7:1' → None, returns None if no % found."""
    if not text:
        return None
    m = re.search(r'([+-]?\d+(?:\.\d+)?)\s*%', str(text))
    if m:
        return float(m.group(1))
    return None


def parse_dates_in_window(window: Optional[str]) -> list:
    """Extract date-like strings from a catalyst window. Returns list of
    ISO-format dates if parseable. Examples:
      '2026-07-15 to 2026-08-31' → ['2026-07-15', '2026-08-31']
      '2026-08-25 (±2 weeks)' → ['2026-08-25']
      'August 2026' → ['2026-08-31'] (best-effort, end of month)
      'August 2026 [external estimate]' → ['2026-08-31']
    """
    if not window:
        return []
    out = []
    # ISO dates yyyy-mm-dd
    iso = re.findall(r'(\d{4}-\d{2}-\d{2})', window)
    if iso:
        for s in iso:
            try:
                datetime.fromisoformat(s)
                out.append(s)
            except ValueError:
                pass
    if out:
        return out
    # Month + year fallback
    mon_year = re.search(
        r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b',
        window, re.IGNORECASE,
    )
    if mon_year:
        months = {'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,'july':7,'august':8,'september':9,'october':10,'november':11,'december':12}
        m = months[mon_year.group(1).lower()]
        y = int(mon_year.group(2))
        # End of month (28-31; use 28 as safe approximation)
        out.append(f'{y:04d}-{m:02d}-28')
    return out


def lookup_entry_price(ticker: str, entry_date: str) -> Optional[float]:
    """Look up OHLC close for ticker on entry_date. Falls back to nearest
    earlier trading day if exact date missing (weekends, holidays)."""
    ohlc_data = safe_load(PUBLIC_DATA / f'ohlc_{to_underscore(ticker)}.json')
    if not ohlc_data:
        return None
    records = ohlc_data.get('data', [])
    if not records:
        return None
    # Sort by date desc
    sorted_recs = sorted(records, key=lambda r: r.get('date', ''))
    entry_dt = datetime.fromisoformat(entry_date).date()
    best = None
    for r in sorted_recs:
        rec_date_str = r.get('date', '')
        if not rec_date_str:
            continue
        try:
            rec_date = datetime.fromisoformat(rec_date_str).date()
        except ValueError:
            continue
        if rec_date <= entry_dt:
            best = r  # keep updating to closest <= entry_date
        else:
            break
    return best.get('close') if best else None


def current_price(ticker: str) -> Optional[float]:
    """Live price from market_data.json yahoo[ticker].price.last."""
    md = safe_load(PUBLIC_DATA / 'market_data.json')
    if not md:
        return None
    return md.get('yahoo', {}).get(ticker, {}).get('price', {}).get('last')


def compute_status(direction: str, return_pct: Optional[float],
                   upside_pct: Optional[float], downside_pct: Optional[float],
                   catalyst_dates: list, today_iso: str) -> str:
    """ACTIVE | TARGET_HIT | STOPPED_OUT | CATALYST_DUE | EXPIRED"""
    today_dt = date.fromisoformat(today_iso)

    # Catalyst window check
    if catalyst_dates:
        try:
            latest_catalyst = max(date.fromisoformat(d) for d in catalyst_dates)
            if today_dt > latest_catalyst:
                return 'EXPIRED'  # Catalyst window passed without trigger
        except ValueError:
            pass

    if return_pct is None or upside_pct is None or downside_pct is None:
        return 'ACTIVE'

    if direction == 'LONG':
        if return_pct >= upside_pct:
            return 'TARGET_HIT'
        if return_pct <= -abs(downside_pct):
            return 'STOPPED_OUT'
    elif direction == 'SHORT':
        # SHORT: negative return is GOOD (price down → short wins)
        if return_pct <= -abs(upside_pct):  # price down by upside_if_right %
            return 'TARGET_HIT'
        if return_pct >= abs(downside_pct):  # price up = short stopped
            return 'STOPPED_OUT'

    # Catalyst due in next 14d → flag
    if catalyst_dates:
        try:
            earliest_catalyst = min(date.fromisoformat(d) for d in catalyst_dates)
            days_to = (earliest_catalyst - today_dt).days
            if 0 <= days_to <= 14:
                return 'CATALYST_DUE'
        except ValueError:
            pass

    return 'ACTIVE'


def track_one(ticker: str, dry_run: bool = False) -> Optional[dict]:
    """Track one thesis. Returns the trade-state dict or None if no thesis."""
    attr = safe_load(PUBLIC_DATA / 'thesis_attribution' / f'{to_underscore(ticker)}.json')
    if not attr:
        print(f'  WARN: no thesis_attribution for {ticker}', file=sys.stderr)
        return None

    # Parse direction (from synth output or default NEUTRAL)
    # log_thesis.py doesn't capture _direction; need to re-load source thesis
    thesis_source = attr.get('thesis_source', '')
    direction = None
    if thesis_source:
        source_path = REPO_ROOT / thesis_source
        source_data = safe_load(source_path)
        if source_data:
            data = source_data.get('data', source_data)
            direction = data.get('_direction') or data.get('dir')
    if not direction:
        # Heuristic from variant view sentence
        vs = attr.get('variant_view_one_sentence', '')
        if 'SHORT' in vs.upper() or 'short the' in vs.lower():
            direction = 'SHORT'
        elif 'LONG' in vs.upper():
            direction = 'LONG'
        else:
            direction = 'NEUTRAL'

    # Skip non-actionable directions
    if direction in ('PASS', 'NEUTRAL'):
        print(f'  {ticker} direction={direction} — non-actionable, skipping paper trade', file=sys.stderr)
        return {
            'ticker': ticker,
            'direction': direction,
            '_status': 'skipped_non_actionable',
            'thesis_logged_at': attr.get('thesis_logged_at'),
        }

    entry_date = (attr.get('thesis_logged_at') or '')[:10]
    entry_price = lookup_entry_price(ticker, entry_date)
    cur_price = current_price(ticker)

    pnl = attr.get('expected_pnl_asymmetry', {})
    upside_pct = parse_pct(pnl.get('upside_if_right'))
    downside_pct = parse_pct(pnl.get('downside_if_wrong'))

    return_pct = None
    if entry_price and cur_price and entry_price > 0:
        return_pct = round((cur_price - entry_price) / entry_price * 100, 2)

    catalyst_window = attr.get('catalyst', {}).get('date_or_window', '')
    catalyst_dates = parse_dates_in_window(catalyst_window)

    today_iso = date.today().isoformat()
    today_dt = date.today()
    entry_dt = date.fromisoformat(entry_date) if entry_date else None
    days_held = (today_dt - entry_dt).days if entry_dt else 0
    days_to_catalyst = None
    if catalyst_dates:
        try:
            earliest = min(date.fromisoformat(d) for d in catalyst_dates)
            days_to_catalyst = (earliest - today_dt).days
        except ValueError:
            pass

    status = compute_status(direction, return_pct, upside_pct, downside_pct,
                            catalyst_dates, today_iso)

    # Load existing daily_log to append
    out_path = PUBLIC_DATA / 'paper_trades' / f'{to_underscore(ticker)}.json'
    existing = safe_load(out_path) or {}
    daily_log = existing.get('daily_log', [])
    today_entry = {
        'date': today_iso,
        'price': cur_price,
        'return_pct': return_pct,
        'status': status,
    }
    # Replace if today already logged
    daily_log = [d for d in daily_log if d.get('date') != today_iso] + [today_entry]
    daily_log.sort(key=lambda x: x.get('date', ''))

    state = {
        'ticker': ticker,
        'thesis_source': thesis_source,
        'thesis_source_commit': attr.get('thesis_source_commit'),
        'thesis_logged_at': attr.get('thesis_logged_at'),
        'direction': direction,
        'entry_date': entry_date,
        'entry_price': entry_price,
        'current_price': cur_price,
        'current_date': today_iso,
        'days_held': days_held,
        'return_since_entry_pct': return_pct,
        'expected_pnl': pnl,
        'upside_target_pct': upside_pct,
        'downside_stop_pct': downside_pct,
        'catalyst_window': catalyst_window,
        'catalyst_dates_parsed': catalyst_dates,
        'days_to_catalyst': days_to_catalyst,
        'current_status': status,
        'wrongIf_conditions': attr.get('wrongIf_conditions', []),
        'rightIf_conditions': attr.get('rightIf_conditions', []),
        'what_changes_our_mind': attr.get('what_changes_our_mind'),
        'daily_log': daily_log[-90:],  # cap at 90 days history
        '_verification_pending': True,
        '_note': 'wrongIf/rightIf conditions kept as text — semantic verification deferred to verify_thesis.py',
    }

    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str))

    return state


def build_summary(states: list, dry_run: bool = False) -> dict:
    """Build aggregate paper_trades_summary.json across all positions."""
    summary = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'total_theses': len(states),
        'active_positions': [],
        'closed_positions': [],
        'skipped': [],
        'hit_rate': None,
        'avg_return_pct': None,
    }
    active = []
    closed = []
    skipped = []
    for s in states:
        if not s:
            continue
        if s.get('_status') == 'skipped_non_actionable':
            skipped.append({'ticker': s['ticker'], 'direction': s.get('direction'), 'thesis_logged_at': s.get('thesis_logged_at')})
            continue
        info = {
            'ticker': s['ticker'],
            'direction': s.get('direction'),
            'entry_date': s.get('entry_date'),
            'entry_price': s.get('entry_price'),
            'current_price': s.get('current_price'),
            'return_since_entry_pct': s.get('return_since_entry_pct'),
            'upside_target_pct': s.get('upside_target_pct'),
            'downside_stop_pct': s.get('downside_stop_pct'),
            'days_held': s.get('days_held'),
            'days_to_catalyst': s.get('days_to_catalyst'),
            'current_status': s.get('current_status'),
        }
        if s.get('current_status') in ('TARGET_HIT', 'STOPPED_OUT', 'EXPIRED'):
            closed.append(info)
        else:
            active.append(info)
    summary['active_positions'] = active
    summary['closed_positions'] = closed
    summary['skipped'] = skipped

    if closed:
        wins = sum(1 for c in closed if c['current_status'] == 'TARGET_HIT')
        summary['hit_rate'] = round(wins / len(closed) * 100, 1)
        summary['avg_return_pct'] = round(sum(c['return_since_entry_pct'] or 0 for c in closed) / len(closed), 2)

    out_path = PUBLIC_DATA / 'paper_trades' / 'summary.json'
    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return summary


def main():
    p = argparse.ArgumentParser(description='Bridge-8 daily paper-trade tracker.')
    p.add_argument('--ticker', help='Track single ticker (e.g., 002594.SZ)')
    p.add_argument('--all', action='store_true', help='Track all theses in thesis_attribution/')
    p.add_argument('--dry-run', action='store_true', help='No file writes')
    args = p.parse_args()

    if not args.ticker and not args.all:
        p.error('Specify --ticker OR --all')

    attr_dir = PUBLIC_DATA / 'thesis_attribution'
    # Load current watchlist to filter — only track theses for tickers
    # we ACTIVELY follow. Legacy thesis_attribution files persist after
    # watchlist switches (e.g., 700.HK from old v1.1 watchlist remains
    # logged but shouldn't be paper-traded after removal).
    wl = safe_load(PUBLIC_DATA / 'watchlist.json')
    active_tickers = set((wl or {}).get('tickers', {}).keys())

    if args.all:
        tickers = []
        for f in sorted(attr_dir.iterdir()):
            if f.name.endswith('.json') and not re.match(r'.+_\d{4}-\d{2}-\d{2}\.json$', f.name):
                # Take only latest pointers (no date suffix)
                if '_' in f.stem:
                    parts = f.stem.rsplit('_', 1)
                    if len(parts) == 2:
                        ticker = f'{parts[0]}.{parts[1]}'
                    else:
                        ticker = f.stem
                else:
                    ticker = f.stem
                # Filter: only active watchlist
                if active_tickers and ticker not in active_tickers:
                    print(f'  SKIP {ticker} (not in current watchlist v1.2)', file=sys.stderr)
                    continue
                tickers.append(ticker)
    else:
        tickers = [args.ticker]

    print(f'=== Bridge-8 paper-trade tracker ===', file=sys.stderr)
    print(f'Tracking {len(tickers)} ticker(s): {tickers}', file=sys.stderr)
    print(f'Today: {date.today().isoformat()}', file=sys.stderr)
    print(file=sys.stderr)

    states = []
    for t in tickers:
        print(f'--- {t} ---', file=sys.stderr)
        s = track_one(t, dry_run=args.dry_run)
        if s:
            states.append(s)
            if s.get('_status') != 'skipped_non_actionable':
                print(f'  entry: {s.get("entry_date")} @ {s.get("entry_price")}, current: {s.get("current_price")}, return: {s.get("return_since_entry_pct")}%, status: {s.get("current_status")}', file=sys.stderr)

    summary = build_summary(states, dry_run=args.dry_run)
    print(file=sys.stderr)
    print(f'=== Summary ===', file=sys.stderr)
    print(f'Active: {len(summary["active_positions"])}, Closed: {len(summary["closed_positions"])}, Skipped: {len(summary["skipped"])}', file=sys.stderr)
    if summary.get('hit_rate') is not None:
        print(f'Hit rate (n={len(summary["closed_positions"])}): {summary["hit_rate"]}% | Avg return: {summary["avg_return_pct"]}%', file=sys.stderr)
    else:
        print(f'Hit rate: not enough closed positions yet', file=sys.stderr)


if __name__ == '__main__':
    main()
