#!/usr/bin/env python3
"""run_research.py — W3 (2026-05-08, post-shift-13)

Server-side replication of the frontend's `enrichment_context`-building
logic. Closes the gap that ALL my earlier curl-based audit / multi-ticker
testing used 0% of the deployed data layer (the model was running on
training data only → hallucinated prices like 700.HK at HK$715 vs actual
HK$473).

Pipeline:
  1. scripts/research_data_loader.load_context(ticker)
     → assembles structured data context from public/data/*
  2. Build enrichment_context payload matching frontend schema
     (Dashboard.jsx ~line 7005-7070) PLUS an `extras` block carrying
     the rich Tushare/multi-year-fin/OHLC data not yet in the
     frontend's enrichment schema (W4 will teach api/research.js to
     consume `extras` server-side)
  3. POST to /api/research
  4. Save response

Usage:
  # Default Vercel endpoint (production)
  python3 scripts/run_research.py 002594.SZ

  # Custom endpoint (e.g., localhost during dev)
  python3 scripts/run_research.py 002594.SZ --endpoint http://localhost:3000/api/research

  # Save to specific path
  python3 scripts/run_research.py 002594.SZ --out /tmp/thesis.json

  # Specify direction bias / context
  python3 scripts/run_research.py 002594.SZ --direction LONG --context "Q1 earnings preview"

  # Dry run — print what would be sent without calling
  python3 scripts/run_research.py 002594.SZ --dry-run

  # Inject coverage gating: don't call API if data context is too thin
  python3 scripts/run_research.py 002594.SZ --require-yahoo --require-fin
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Import T-RD data loader from sibling script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_data_loader import load_context  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENDPOINT = 'https://equity-research-ten.vercel.app/api/research'


def fetch_recent_news(ticker: str, endpoint_base: str, days: int = 7, timeout_sec: int = 20) -> list:
    """Fetch ticker-specific news from /api/news?tab=portfolio.

    Phase 2.B (2026-05-10): /api/news already aggregates Yahoo Finance
    per-ticker RSS feeds. Frontend Dashboard.jsx uses it; run_research.py
    didn't. → recent_news_5d enrichment field was always empty in CLI runs
    → Bull/Bear had no news context to cite. This fetches + filters.

    Returns list of {title, source, published_at, summary} dicts, last N days,
    matching ticker.
    """
    news_url = f'{endpoint_base.rstrip("/")}/api/news?tab=portfolio'
    try:
        req = urllib.request.Request(news_url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f'WARN: /api/news fetch failed: {e}', file=sys.stderr)
        return []

    articles = data.get('articles', []) or data.get('news', []) or []
    cutoff_ms = (datetime.now(timezone.utc).timestamp() - days * 86400) * 1000
    out = []
    for a in articles:
        # Match by ticker tag
        if a.get('ticker') != ticker:
            continue
        # Time filter
        pub = a.get('published_at')
        if pub:
            try:
                pub_dt = datetime.fromisoformat(pub.replace('Z', '+00:00'))
                if pub_dt.timestamp() * 1000 < cutoff_ms:
                    continue
            except (ValueError, AttributeError):
                pass
        out.append({
            'title': a.get('title'),
            'source': a.get('source'),
            'published_at': pub,
            'summary': (a.get('summary') or '')[:300],
        })
    return out[:10]  # cap at 10 most recent


def build_enrichment_context(ctx: dict, news: Optional[list] = None) -> Optional[dict]:
    """Map T-RD output into the enrichment_context schema /api/research expects.

    Mirrors Dashboard.jsx lines 7005-7070 (frontend's enrichment build).
    Adds `extras` field with richer data (Tushare suite, multi-year fin,
    OHLC trend) which the SERVER currently ignores but W4 will consume.

    `news` parameter (Phase 2.B): if provided, overrides ctx's empty
    recent_news_5d. Caller fetches via fetch_recent_news() before calling.
    """
    yahoo = ctx.get('yahoo_live', {})
    if yahoo.get('_status') != 'loaded':
        return None  # No yahoo data → can't ground; skip enrichment

    price_block = yahoo.get('price', {})
    fund_block = yahoo.get('fundamentals', {})
    analyst_block = yahoo.get('analyst', {})

    live_price = price_block.get('last')
    live_change_pct = price_block.get('change_pct')

    # Frontend-compatible fundamentals subset (don't change shape — server uses these)
    fundamentals = None
    if fund_block or analyst_block or price_block:
        fundamentals = {
            'pe_trailing':      fund_block.get('pe_trailing'),
            'pe_forward':       fund_block.get('pe_forward'),
            'ev_ebitda':        fund_block.get('ev_ebitda'),
            'gross_margin':     fund_block.get('gross_margin'),
            'operating_margin': fund_block.get('operating_margin'),
            'roe':              fund_block.get('roe'),
            'revenue_growth':   fund_block.get('revenue_growth'),
            'target_mean':      analyst_block.get('target_mean'),
            'target_low':       analyst_block.get('target_low'),
            'target_high':      analyst_block.get('target_high'),
            'num_analysts':     analyst_block.get('num_analysts'),
            'low_52w':          price_block.get('low_52w'),
            'high_52w':         price_block.get('high_52w'),
        }
        # Drop entirely if all None
        if all(v is None for v in fundamentals.values()):
            fundamentals = None

    sector_regime_block = ctx.get('sector_regime', {})
    sector_regime = sector_regime_block.get('regime') if sector_regime_block.get('_status') == 'loaded' else None

    enrichment = {
        'live_price': f'{live_price:.2f}' if live_price is not None else None,
        'live_change_pct': live_change_pct,
        'recent_news': news if news is not None else ctx.get('recent_news_5d', []),
        'sector_regime': sector_regime,
        'prior_predictions': [],  # populated later when prediction_log integration ready
        'fundamentals': fundamentals,
        # NEW: rich data the server doesn't yet consume but will after W4.
        # Naming with `extras` to clearly separate from frontend-canonical fields.
        'extras': {
            'context_version': ctx.get('context_version'),
            'context_built_at': ctx.get('context_built_at'),
            'watchlist_meta': ctx.get('watchlist_meta', {}),
            'financials_annual': ctx.get('financials_annual', {}),
            'ohlc_recent': ctx.get('ohlc_recent', {}),
            'tushare_suite': ctx.get('tushare_suite', {}),
            'vp_snapshot': ctx.get('vp_snapshot', {}),
            'rdcf': ctx.get('rdcf', {}),
            'fragility': ctx.get('fragility', {}),
            'persona_overlay': ctx.get('persona_overlay', {}),
            'peer_comparison': ctx.get('peer_comparison', []),  # Phase 2.D 2026-05-10
            'segment_economics': ctx.get('segment_economics', {}),  # KR1 2026-05-15
            '_coverage_summary': ctx.get('_coverage_summary', {}),
            '_tushare_coverage': ctx.get('_tushare_coverage', {}),
        },
    }
    return enrichment


def coverage_gates(ctx: dict, requires: dict) -> list[str]:
    """Check requested data-availability gates. Returns list of failed gates."""
    failed = []
    if requires.get('yahoo'):
        if ctx.get('yahoo_live', {}).get('_status') != 'loaded':
            failed.append('yahoo (--require-yahoo): yahoo_live not loaded for this ticker')
    if requires.get('fin'):
        if ctx.get('financials_annual', {}).get('_status') != 'loaded':
            failed.append('fin (--require-fin): financials_annual not loaded')
    if requires.get('tushare'):
        ts = ctx.get('_tushare_coverage', {})
        ok_count = sum(1 for v in ts.values() if v == 'ok')
        if ok_count < 3:
            failed.append(f'tushare (--require-tushare): only {ok_count} dirs have ok status')
    return failed


def call_research_api(endpoint: str, ticker: str, company: Optional[str],
                      direction: str, context: Optional[str],
                      enrichment_context: Optional[dict],
                      timeout_sec: int = 360) -> dict:
    """POST to /api/research and return parsed JSON."""
    body = {
        'ticker': ticker,
        'direction': direction,
    }
    if company:
        body['company'] = company
    if context:
        body['context'] = context
    if enrichment_context:
        body['enrichment_context'] = enrichment_context

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    started = datetime.now(timezone.utc)
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            payload = resp.read().decode('utf-8')
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            print(f'HTTP {resp.status} | {len(payload)} bytes | {elapsed:.1f}s', file=sys.stderr)
            return json.loads(payload)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode('utf-8', errors='replace')
        print(f'HTTP error {e.code}: {body_text[:500]}', file=sys.stderr)
        raise


def main():
    p = argparse.ArgumentParser(description='Run /api/research with proper data context.')
    p.add_argument('ticker', help='Ticker (e.g., 002594.SZ, 175.HK)')
    p.add_argument('--company', help='Company name hint (e.g., "BYD")')
    p.add_argument('--direction', default='NEUTRAL',
                   choices=['LONG', 'SHORT', 'NEUTRAL'],
                   help='Initial direction bias (default: NEUTRAL)')
    p.add_argument('--context', help='Research context string')
    p.add_argument('--endpoint', default=DEFAULT_ENDPOINT,
                   help=f'API endpoint (default: {DEFAULT_ENDPOINT})')
    p.add_argument('--out', help='Save full response to this path')
    p.add_argument('--timeout', type=int, default=360,
                   help='Client HTTP timeout sec. Multi-agent (/api/research-multi) '
                        'runs 7 LLM calls ~6-10min; use 780 (just under Vercel '
                        'maxDuration 800) so the client does not abort while the '
                        'server keeps billing LLM calls. Default 360 = single-agent.')
    p.add_argument('--dry-run', action='store_true',
                   help='Print payload without calling API')
    p.add_argument('--require-yahoo', action='store_true',
                   help='Fail if yahoo_live data not loaded')
    p.add_argument('--require-fin', action='store_true',
                   help='Fail if financials_annual not loaded')
    p.add_argument('--require-tushare', action='store_true',
                   help='Fail if Tushare coverage <3 ok dirs')
    p.add_argument('--no-enrichment', action='store_true',
                   help='Skip enrichment_context (call with empty body — for hallucination baseline)')
    args = p.parse_args()

    # 1. Build context from public/data/*
    ctx = load_context(args.ticker)

    # 1b. Fetch recent news from /api/news (Phase 2.B 2026-05-10).
    # /api/news aggregates per-ticker Yahoo RSS — Dashboard frontend uses it
    # but CLI script didn't. Without this, enrichment.recent_news = empty,
    # so Bull/Bear can't cite news in mechanism chain.
    news_endpoint_base = args.endpoint.replace('/api/research-multi', '').replace('/api/research', '')
    if args.no_enrichment:
        news = []
    else:
        print(f'Fetching news from {news_endpoint_base}/api/news?tab=portfolio...', file=sys.stderr)
        news = fetch_recent_news(args.ticker, news_endpoint_base, days=7)
        print(f'  → {len(news)} articles for {args.ticker} (last 7d)', file=sys.stderr)

    # 2. Coverage gating
    requires = {
        'yahoo': args.require_yahoo,
        'fin': args.require_fin,
        'tushare': args.require_tushare,
    }
    failed = coverage_gates(ctx, requires)
    if failed:
        print('Coverage gates failed:', file=sys.stderr)
        for f in failed:
            print(f'  - {f}', file=sys.stderr)
        sys.exit(2)

    # 3. Build enrichment payload
    enrichment = None if args.no_enrichment else build_enrichment_context(ctx, news=news)
    if enrichment is None and not args.no_enrichment:
        print('WARN: enrichment_context could not be built (yahoo data missing). '
              'Call will proceed without enrichment (hallucination risk).', file=sys.stderr)

    # 4. Dry-run summary
    if args.dry_run:
        coverage = ctx.get('_coverage_summary', {})
        ts_coverage = ctx.get('_tushare_coverage', {})
        print(f'=== Dry run for {args.ticker} ===')
        print(f'Endpoint: {args.endpoint}')
        print(f'Direction: {args.direction}')
        print(f'Company: {args.company or "(not set)"}')
        print(f'Context: {args.context or "(not set)"}')
        print(f'\nLayer coverage:')
        for k, v in coverage.items():
            print(f'  {k:25s} {v}')
        print(f'\nTushare sub-coverage:')
        for k, v in ts_coverage.items():
            print(f'  {k:25s} {v}')
        print(f'\nEnrichment built: {bool(enrichment)}')
        if enrichment:
            print(f'  live_price: {enrichment.get("live_price")}')
            print(f'  fundamentals fields: {sum(1 for v in (enrichment.get("fundamentals") or {}).values() if v is not None)}')
            print(f'  recent_news count: {len(enrichment.get("recent_news") or [])}')
            print(f'  sector_regime: {enrichment.get("sector_regime")}')
            print(f'  extras layers: {list((enrichment.get("extras") or {}).keys())}')
        return

    # 5. Call API
    print(f'Calling {args.endpoint} for {args.ticker}...', file=sys.stderr)
    if enrichment is None:
        print(f'(NO ENRICHMENT — model uses training data only, expect hallucinations)', file=sys.stderr)
    else:
        print(f'(Enrichment: live_price={enrichment.get("live_price")}, '
              f'fundamentals fields={sum(1 for v in (enrichment.get("fundamentals") or {}).values() if v is not None)}, '
              f'extras: {list((enrichment.get("extras") or {}).keys())})', file=sys.stderr)

    response = call_research_api(
        endpoint=args.endpoint,
        ticker=args.ticker,
        company=args.company,
        direction=args.direction,
        context=args.context,
        enrichment_context=enrichment,
        timeout_sec=args.timeout,
    )

    # 6. Quick quality summary
    quality = response.get('data', {}).get('_quality', {})
    print(f'\n=== Result ===', file=sys.stderr)
    print(f'success: {response.get("success")}', file=sys.stderr)
    print(f'_quality.score: {quality.get("score")} severity: {quality.get("severity")}', file=sys.stderr)
    qc = quality.get('qcChecklistResults', {})
    fc1 = qc.get('step_1_catalyst_date_in_future')
    print(f'FC.1 step_1_catalyst_date_in_future: {fc1}', file=sys.stderr)
    print(f'enrichment_used: {response.get("enrichment_used")}', file=sys.stderr)
    print(f'fundamentals_used: {response.get("fundamentals_used")}', file=sys.stderr)
    print(f'usage tokens: input={response.get("usage", {}).get("input_tokens")} output={response.get("usage", {}).get("output_tokens")}', file=sys.stderr)

    # 7. Save / print
    payload = json.dumps(response, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(payload)
        print(f'\nSaved to: {args.out}', file=sys.stderr)
    else:
        print(payload)


if __name__ == '__main__':
    main()
