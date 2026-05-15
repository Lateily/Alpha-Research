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


def _classify_region(item: str) -> str:
    """Bucket a fina_mainbz 分地区 bz_item label into domestic/overseas/other.
    Heuristic — Chinese issuers label inconsistently. When ambiguous we
    return 'other' rather than guessing (honest > clever)."""
    if not item:
        return 'other'
    s = str(item)
    overseas_kw = ('境外', '海外', '国外', '出口', '国际', 'Overseas', 'Oversea',
                   'Export', 'Abroad', 'Foreign', 'International', '欧洲', '美洲',
                   '亚洲（不含', '其他国家', '外销')
    domestic_kw = ('境内', '国内', '中国大陆', '大陆', 'Domestic', 'PRC', 'China',
                   'Mainland', '内销', '中国境内')
    if any(k in s for k in overseas_kw):
        return 'overseas'
    if any(k in s for k in domestic_kw):
        return 'domestic'
    return 'other'


def _seg_margin(row: dict) -> dict:
    """Compute gross margin for one fina_mainbz row. Returns gm (true GM
    from bz_sales-bz_cost) when bz_cost disclosed, else gp_margin proxy
    from bz_profit. NEVER fabricates — missing inputs → None + reason."""
    sales = row.get('bz_sales')
    cost = row.get('bz_cost')
    profit = row.get('bz_profit')
    out = {'bz_sales': sales, 'bz_cost': cost, 'bz_profit': profit,
           'gm': None, 'gm_basis': None}
    try:
        s = float(sales) if sales is not None else None
    except (TypeError, ValueError):
        s = None
    if not s:
        out['gm_basis'] = 'no_sales_disclosed'
        return out
    try:
        c = float(cost) if cost is not None else None
    except (TypeError, ValueError):
        c = None
    try:
        p = float(profit) if profit is not None else None
    except (TypeError, ValueError):
        p = None
    if c is not None:
        out['gm'] = round((s - c) / s * 100, 2)
        out['gm_basis'] = 'true_gm (bz_sales - bz_cost)'
    elif p is not None:
        out['gm'] = round(p / s * 100, 2)
        out['gm_basis'] = 'PROXY gp_margin (bz_profit/bz_sales — NOT true GM, bz_cost not disclosed)'
    else:
        out['gm_basis'] = 'no_cost_no_profit_disclosed'
    return out


def derive_segment_economics(ticker: str) -> dict:
    """KR1 (2026-05-15, Junyan verdict follow-up). Derive region-level &
    product-level gross margin from Tushare fina_mainbz, to attack the
    BYD critique: 'vertical-integration → export-margin' was only
    company-level co-occurrence, no region GM proof.

    Returns honest structure. The CALLER / prompt must treat a
    proxy/blended result as PROXY evidence, not proof — _limitation
    states exactly why."""
    tj = safe_load(PUBLIC_DATA / 'tushare' / f'{ticker}.json')
    if not tj or not isinstance(tj, dict):
        return {'_status': 'not_available',
                '_note': f'tushare/{ticker}.json missing (HK/US ticker or not fetched)'}
    data = tj.get('data', {}) if isinstance(tj.get('data'), dict) else {}
    region_blk = data.get('fina_mainbz_region', {})
    product_blk = data.get('fina_mainbz_product', {})
    region_rows = region_blk.get('rows') or []
    product_rows = product_blk.get('rows') or []

    if not region_rows and not product_rows:
        status = region_blk.get('_status') or product_blk.get('_status') or 'not_available'
        return {'_status': 'no_segment_disclosure',
                '_note': f'fina_mainbz returned no rows (_status={status}). '
                         f'Issuer may not break out segments, or tier-locked.'}

    def _latest_period(rows: list):
        periods = sorted({r.get('end_date') for r in rows if r.get('end_date')}, reverse=True)
        return periods[0] if periods else None

    out = {'_status': 'loaded', 'source': 'tushare fina_mainbz',
           '_methodology': 'GM = (bz_sales - bz_cost)/bz_sales when bz_cost '
                           'disclosed; else PROXY = bz_profit/bz_sales. '
                           'Region buckets via label heuristic.'}
    limitations = []

    # ── By region (the critical one for the BYD export-margin question) ──
    rperiod = _latest_period(region_rows)
    if rperiod:
        buckets = {'domestic': [], 'overseas': [], 'other': []}
        for r in region_rows:
            if r.get('end_date') != rperiod:
                continue
            buckets[_classify_region(r.get('bz_item'))].append(r)

        def _agg(rows):
            if not rows:
                return None
            tot_s = tot_c = tot_p = 0.0
            have_c = have_p = False
            items = []
            for r in rows:
                m = _seg_margin(r)
                items.append({'bz_item': r.get('bz_item'), **m})
                try:
                    tot_s += float(r.get('bz_sales') or 0)
                except (TypeError, ValueError):
                    pass
                if r.get('bz_cost') is not None:
                    have_c = True
                    try:
                        tot_c += float(r.get('bz_cost'))
                    except (TypeError, ValueError):
                        pass
                if r.get('bz_profit') is not None:
                    have_p = True
                    try:
                        tot_p += float(r.get('bz_profit'))
                    except (TypeError, ValueError):
                        pass
            agg_gm = None
            basis = None
            if have_c and tot_s:
                agg_gm = round((tot_s - tot_c) / tot_s * 100, 2)
                basis = 'true_gm'
            elif have_p and tot_s:
                agg_gm = round(tot_p / tot_s * 100, 2)
                basis = 'PROXY gp_margin'
            return {'agg_sales': tot_s, 'agg_gm_pct': agg_gm,
                    'agg_gm_basis': basis, 'items': items}

        dom = _agg(buckets['domestic'])
        ovs = _agg(buckets['overseas'])
        out['by_region'] = {'period': rperiod, 'domestic': dom,
                            'overseas': ovs,
                            'other': _agg(buckets['other'])}
        if dom and ovs and dom.get('agg_gm_pct') is not None and ovs.get('agg_gm_pct') is not None:
            gap = round(ovs['agg_gm_pct'] - dom['agg_gm_pct'], 2)
            out['overseas_minus_domestic_gm_bps'] = int(gap * 100)
            if 'PROXY' in (str(dom.get('agg_gm_basis')) + str(ovs.get('agg_gm_basis'))):
                limitations.append(
                    'overseas/domestic GM gap is PROXY (bz_profit-based, '
                    'bz_cost not disclosed) — directional only, NOT audited true GM')
        else:
            limitations.append(
                'cannot compute overseas-vs-domestic GM gap: one or both '
                'region buckets lack disclosed cost/profit OR not split by 境内/境外')
        # blended-business caveat (BYD-specific risk Junyan flagged)
        if ovs:
            for it in (ovs.get('items') or []):
                lbl = str(it.get('bz_item') or '')
                if any(k in lbl for k in ('电子', '手机', '部件', '代工', '组装')):
                    limitations.append(
                        f'overseas bucket contains non-auto line "{lbl}" — '
                        f'export GM is BLENDED with handset/electronics; does '
                        f'NOT isolate auto-export unit economics (this is '
                        f'exactly the residual gap in Junyan 2026-05-15 verdict)')
                    break
    else:
        limitations.append('no 分地区 (region) segment rows — cannot address export-margin question from this source')

    # ── By product (汽车 vs 电池 vs 手机部件) — supporting context ──
    pperiod = _latest_period(product_rows)
    if pperiod:
        prod = []
        for r in product_rows:
            if r.get('end_date') != pperiod:
                continue
            prod.append({'bz_item': r.get('bz_item'), **_seg_margin(r)})
        out['by_product'] = {'period': pperiod, 'segments': prod}
    else:
        limitations.append('no 分产品 (product) segment rows')

    out['_limitation'] = limitations or ['none — true GM by region disclosed and isolable']
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
        'segment_economics': derive_segment_economics(ticker),  # KR1 2026-05-15
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
