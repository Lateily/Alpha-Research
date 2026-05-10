#!/usr/bin/env python3
"""research_data_loader.py — T-RD (Stage 1 of multi-agent research team v1)

Reads all available public/data/* files for a ticker and assembles a single
structured JSON context. NO LLM call. Deterministic. Used by:
  - scripts/run_research.py (single-agent /api/research enrichment)
  - api/research-multi (future) for Bull / Bear / Forensic / Synthesizer

Closes the gap surfaced 2026-05-08: research previously consumed ~10% of
the deployed data layer (yahoo basics + news + sector regime). The other
90% (full Tushare suite, multi-year fin, OHLC trend, VP scores, rDCF)
sat unused → models hallucinated prices/multipliers/numbers from
training data instead of grounding in our ingested reality.

Usage:
  # Print context JSON to stdout
  python3 scripts/research_data_loader.py <ticker>

  # Save to file
  python3 scripts/research_data_loader.py <ticker> --out path/to/context.json

  # As a module
  from scripts.research_data_loader import load_context
  ctx = load_context('700.HK')
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DATA = REPO_ROOT / 'public' / 'data'

# Phase 2.D (2026-05-10): peer-ticker map for cross-section comparison.
# Each focus ticker has 1-3 peers — load_peers() reads their fin / market_data
# IF FILES EXIST (no extra pipeline coordination required for this MVP).
# Pipeline can be extended later to fetch peers automatically.
PEER_TICKERS = {
    '002594.SZ': ['175.HK', '1211.HK'],          # BYD ← Geely Auto + BYD-H share
    '300308.SZ': ['002281.SZ', '300620.SZ'],     # Innolight ← 光迅科技 + 光库科技
    '175.HK':    ['002594.SZ', '1211.HK'],        # Geely ← BYD A + BYD-H
    '603233.SH': ['603883.SH', '002411.SZ', '603939.SH'],  # Da Shenlin ← 老百姓 + 益丰 + 一心堂
}

# Tushare per-ticker directories (most use <TICKER>.json filename)
TUSHARE_DIRS = [
    'chip_distribution', 'consensus_forecast', 'lhb', 'quant_factors',
    'top_inst', 'broker_recommend', 'pledge_stat', 'restricted_shares',
    'holdertrade', 'margin', 'repurchase', 'tushare',
]

# inst_research is special: filename = <TICKER_NO_DOT>.json
INST_RESEARCH_DIR = 'inst_research'

# Multi-year financial data files: fin_<TICKER_UNDERSCORE>.json
UNDERSCORE_FILES = ['fin', 'rdcf', 'fragility', 'eqr', 'ohlc']


def safe_load(path: Path) -> Optional[Any]:
    """Load JSON file or return None if missing / unparseable."""
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def to_underscore(ticker: str) -> str:
    """'300308.SZ' → '300308_SZ' (used by fin_*, rdcf_*, etc.)"""
    return ticker.replace('.', '_')


def to_no_dot(ticker: str) -> str:
    """'300308.SZ' → '300308SZ' (used by inst_research dir)"""
    return ticker.replace('.', '')


def load_yahoo_live(ticker: str) -> dict:
    """Live price + fundamentals + analyst targets from market_data.json."""
    md = safe_load(PUBLIC_DATA / 'market_data.json') or {}
    yahoo_t = md.get('yahoo', {}).get(ticker, {})
    if not yahoo_t:
        return {'_status': 'not_in_market_data', '_note': f'{ticker} missing from market_data.yahoo (ticker spelling? or pipeline did not fetch yet?)'}
    return {
        '_status': 'loaded',
        'price': yahoo_t.get('price', {}),
        'fundamentals': yahoo_t.get('fundamentals', {}),
        'analyst': yahoo_t.get('analyst', {}),
        'meta': yahoo_t.get('meta', {}),
        'price_source': yahoo_t.get('price_source'),
        'technical': yahoo_t.get('technical', {}),
    }


def load_financials(ticker: str) -> dict:
    """Multi-year income statement / balance sheet / cash flow."""
    fin = safe_load(PUBLIC_DATA / f'fin_{to_underscore(ticker)}.json')
    if not fin:
        return {'_status': 'not_available', '_note': f'fin_{to_underscore(ticker)}.json missing'}
    # Trim — only keep most-recent 3 years to bound prompt size
    out = {'_status': 'loaded', 'fetched_at': fin.get('fetched_at')}
    for section in ['income_statement', 'balance_sheet', 'cash_flow']:
        full = fin.get(section, {})
        if not isinstance(full, dict):
            continue
        years = sorted(full.keys(), reverse=True)[:3]
        out[section] = {y: full[y] for y in years}
    return out


def load_ohlc(ticker: str, days: int = 60) -> dict:
    """OHLC history — keep last N days only (default 60 for trend context)."""
    ohlc = safe_load(PUBLIC_DATA / f'ohlc_{to_underscore(ticker)}.json')
    if not ohlc:
        return {'_status': 'not_available'}
    data = ohlc.get('data', [])
    return {
        '_status': 'loaded',
        'fetched_at': ohlc.get('fetched_at'),
        'days_returned': min(days, len(data)),
        'data': data[-days:],
    }


def load_tushare_suite(ticker: str) -> dict:
    """Per-ticker Tushare files across all dirs."""
    out = {}
    # Standard <TICKER>.json files
    for d in TUSHARE_DIRS:
        path = PUBLIC_DATA / d / f'{ticker}.json'
        loaded = safe_load(path)
        if loaded is not None:
            out[d] = loaded
        else:
            out[d] = {'_status': 'not_available'}
    # inst_research uses no-dot filename
    inst_path = PUBLIC_DATA / INST_RESEARCH_DIR / f'{to_no_dot(ticker)}.json'
    inst_loaded = safe_load(inst_path)
    out[INST_RESEARCH_DIR] = inst_loaded if inst_loaded is not None else {'_status': 'not_available'}
    return out


def load_vp_snapshot(ticker: str) -> dict:
    """vp_snapshot structure: {date, snapshots: [{ticker, vp, decomp, ...}]}"""
    vp = safe_load(PUBLIC_DATA / 'vp_snapshot.json')
    if not vp:
        return {'_status': 'not_available'}
    snapshots = vp.get('snapshots', [])
    for snap in snapshots:
        if snap.get('ticker') == ticker:
            return {'_status': 'loaded', 'date': vp.get('date'), **snap}
    return {'_status': 'ticker_not_in_snapshot'}


def load_rdcf(ticker: str) -> dict:
    rdcf = safe_load(PUBLIC_DATA / f'rdcf_{to_underscore(ticker)}.json')
    if not rdcf:
        return {'_status': 'not_available'}
    # File contains rdcf computation result; has 'error' field if failed
    if rdcf.get('error'):
        return {'_status': 'rdcf_failed', 'error': rdcf.get('error'), **{k: v for k, v in rdcf.items() if k != 'error'}}
    return {'_status': 'loaded', **rdcf}


def load_fragility(ticker: str) -> dict:
    frag = safe_load(PUBLIC_DATA / f'fragility_{to_underscore(ticker)}.json')
    if not frag:
        return {'_status': 'not_available'}
    return {'_status': 'loaded', **frag}


def load_persona_overlay(ticker: str) -> dict:
    """persona_overlay structure: {_meta, personas: {<persona>: {<ticker>: {...}}}}.
    We pivot to per-ticker view: {persona_name: {...}, persona_name2: {...}}."""
    persona = safe_load(PUBLIC_DATA / 'persona_overlay.json')
    if not persona:
        return {'_status': 'not_available'}
    personas_block = persona.get('personas', {})
    out = {}
    for pname, ptickers in personas_block.items():
        if isinstance(ptickers, dict) and ticker in ptickers:
            out[pname] = ptickers[ticker]
    if not out:
        return {'_status': 'ticker_not_in_overlay'}
    return {'_status': 'loaded', 'personas': out}


def load_recent_news(ticker: str, days: int = 5) -> list:
    """News articles for this ticker, last N days."""
    news_path = PUBLIC_DATA / 'flow_data.json'
    flow = safe_load(news_path)
    if not flow:
        return []
    articles = flow.get('articles', []) or flow.get('news', []) or []
    cutoff_ms = (datetime.now(timezone.utc).timestamp() - days * 86400) * 1000
    out = []
    for a in articles:
        if a.get('ticker') != ticker:
            continue
        # Keep last N days
        pub = a.get('published_at') or a.get('date')
        if pub:
            try:
                # Best-effort timestamp parse
                pub_dt = datetime.fromisoformat(pub.replace('Z', '+00:00'))
                if pub_dt.timestamp() * 1000 < cutoff_ms:
                    continue
            except (ValueError, AttributeError):
                pass
        out.append({
            'title': a.get('title'),
            'source': a.get('source'),
            'published_at': pub,
            'summary': a.get('summary') or a.get('description'),
        })
    return out[:10]  # cap at 10 most recent


def _peer_summary(peer_ticker: str) -> Optional[dict]:
    """Best-effort load of a peer's fin / valuation summary. Returns None if
    peer's fin file isn't fetched (peer not in pipeline). Phase 2.D: we
    don't auto-fetch peers — pipeline must already have them or skip."""
    fin = safe_load(PUBLIC_DATA / f'fin_{to_underscore(peer_ticker)}.json')
    if not fin:
        return {'ticker': peer_ticker, '_status': 'peer_data_not_loaded'}

    out = {'ticker': peer_ticker, '_status': 'loaded'}

    # Last 2 years revenue + NI from income_statement
    income = fin.get('income_statement', {}) if isinstance(fin, dict) else {}
    years = sorted(income.keys(), reverse=True)[:2] if income else []
    if years:
        latest = income[years[0]]
        prior = income[years[1]] if len(years) > 1 else {}
        out['latest_year'] = years[0][:4]
        ni_latest = latest.get('Net Income') or latest.get('Net Income Common Stockholders')
        ni_prior = prior.get('Net Income') or prior.get('Net Income Common Stockholders')
        out['net_income'] = ni_latest
        if ni_latest is not None and ni_prior is not None and ni_prior != 0:
            out['ni_yoy_pct'] = round((ni_latest / ni_prior - 1) * 100, 1)
        rev_latest = latest.get('Total Revenue') or latest.get('Operating Revenue')
        out['revenue'] = rev_latest
        eps = latest.get('Diluted EPS') or latest.get('Basic EPS')
        out['diluted_eps'] = eps

    # Live market data (price + key valuation)
    md = safe_load(PUBLIC_DATA / 'market_data.json') or {}
    yahoo_t = md.get('yahoo', {}).get(peer_ticker, {})
    if yahoo_t:
        fund = yahoo_t.get('fundamentals', {})
        price = yahoo_t.get('price', {})
        out['live_price'] = price.get('last')
        out['pe_trailing'] = fund.get('pe_trailing')
        out['pe_forward'] = fund.get('pe_forward')
        out['gross_margin'] = fund.get('gross_margin')
        out['operating_margin'] = fund.get('operating_margin')
        out['revenue_growth_ttm'] = fund.get('revenue_growth')
        out['roe'] = fund.get('roe')
        out['market_cap'] = fund.get('market_cap')

    return out


def load_peers(ticker: str) -> list:
    """Load peer comparison data (Phase 2.D 2026-05-10). Returns list of
    {ticker, fin_summary, valuation, _status} dicts for each peer mapped
    to this ticker. Peer must already have fin_*.json fetched (else
    _status='peer_data_not_loaded')."""
    peer_list = PEER_TICKERS.get(ticker, [])
    if not peer_list:
        return []
    return [_peer_summary(p) for p in peer_list]


def load_sector_regime(ticker: str) -> dict:
    """Sector regime (PERMISSIVE/NEUTRAL/RESTRICTIVE) if available."""
    regime = safe_load(PUBLIC_DATA / 'regime_data.json') or safe_load(PUBLIC_DATA / 'regime.json')
    if not regime:
        return {'_status': 'not_available'}
    # Match ticker → sector → regime
    for sector in regime.get('sectors', []):
        if ticker in (sector.get('tickers') or []):
            return {
                '_status': 'loaded',
                'sector_name': sector.get('name'),
                'regime': sector.get('regime'),
                'rationale': sector.get('rationale'),
            }
    return {'_status': 'ticker_not_in_regime'}


def load_watchlist_meta(ticker: str) -> dict:
    """Per-ticker entry from watchlist.json (vp_seed, wrongIf, rationales)."""
    wl = safe_load(PUBLIC_DATA / 'watchlist.json')
    if not wl:
        return {'_status': 'not_available'}
    entry = wl.get('tickers', {}).get(ticker)
    if not entry:
        return {'_status': 'ticker_not_in_watchlist'}
    return {'_status': 'loaded', **entry}


def load_context(ticker: str) -> dict:
    """Top-level: assemble full context. Returns dict with all per-ticker data
    layers + metadata. Missing layers return {_status: 'not_available'} rather
    than being omitted, so downstream prompts can explicitly say
    'data not available' instead of pretending.
    """
    context = {
        'ticker': ticker,
        'context_built_at': datetime.now(timezone.utc).isoformat(),
        'context_version': 'v1.0 (2026-05-08, T-RD)',
        'watchlist_meta': load_watchlist_meta(ticker),
        'yahoo_live': load_yahoo_live(ticker),
        'financials_annual': load_financials(ticker),
        'ohlc_recent': load_ohlc(ticker, days=60),
        'tushare_suite': load_tushare_suite(ticker),
        'vp_snapshot': load_vp_snapshot(ticker),
        'rdcf': load_rdcf(ticker),
        'fragility': load_fragility(ticker),
        'persona_overlay': load_persona_overlay(ticker),
        'recent_news_5d': load_recent_news(ticker, days=5),
        'sector_regime': load_sector_regime(ticker),
        'peer_comparison': load_peers(ticker),  # Phase 2.D 2026-05-10
    }

    # Coverage summary — quick visibility into what's available vs missing
    coverage = {}
    for k, v in context.items():
        if k in ('ticker', 'context_built_at', 'context_version', 'recent_news_5d'):
            continue
        if isinstance(v, dict):
            coverage[k] = v.get('_status', 'unknown')
        elif isinstance(v, list):
            coverage[k] = f'{len(v)} items' if v else 'empty'
        else:
            coverage[k] = type(v).__name__
    context['_coverage_summary'] = coverage

    # Tushare sub-coverage (separate visibility)
    tushare_coverage = {
        d: context['tushare_suite'].get(d, {}).get('_status', 'unknown')
        for d in TUSHARE_DIRS + [INST_RESEARCH_DIR]
    }
    context['_tushare_coverage'] = tushare_coverage

    return context


def main():
    p = argparse.ArgumentParser(description='Build research data context for a ticker.')
    p.add_argument('ticker', help='Ticker (e.g., 002594.SZ, 700.HK, 175.HK)')
    p.add_argument('--out', help='Write JSON to this path (default: stdout)')
    p.add_argument('--summary', action='store_true', help='Print coverage summary only')
    args = p.parse_args()

    ctx = load_context(args.ticker)

    if args.summary:
        print(f'=== Coverage for {args.ticker} ===')
        print(f'Built at: {ctx["context_built_at"]}')
        print()
        print('Layer status:')
        for k, v in ctx['_coverage_summary'].items():
            print(f'  {k:25s} {v}')
        print()
        print('Tushare sub-status:')
        for k, v in ctx['_tushare_coverage'].items():
            print(f'  {k:25s} {v}')
        return

    payload = json.dumps(ctx, indent=2, ensure_ascii=False, default=str)
    if args.out:
        Path(args.out).write_text(payload)
        print(f'Wrote {len(payload)} chars to {args.out}', file=sys.stderr)
    else:
        print(payload)


if __name__ == '__main__':
    main()
