// api/research.js v4 — Three-source parallel research pipeline
//
// DATA SOURCES (all run in parallel in Pass 1):
//
//   [1] 东方财富 (eastmoney.com) — JSONP research report API
//       → reportapi.eastmoney.com/report/list
//       → Returns: title, broker, rating, date, target price (extracted from title)
//       → Coverage: 100+ Chinese brokers for A-shares + HK stocks
//       → Auth: none needed (public JSONP API used by Futu/Tiger apps)
//
//   [2] 同花顺 (10jqka.com.cn) — JSON research report API
//       → basic.10jqka.com.cn/api/stock/report.json
//       → Returns: title, broker (organ), rating, date
//       → Coverage: major Chinese brokers, complements eastmoney
//       → Auth: none needed for basic report list
//
//   [3] Tavily Search API — international analyst coverage
//       → api.tavily.com/search
//       → Searches: Reuters, Bloomberg, MarketBeat, TipRanks, SCMP, Barron's
//       → Auth: TAVILY_API_KEY env var (optional — free 1000/mo at tavily.com)
//
// PASS 1: All three sources run concurrently (Promise.allSettled)
//         Claude synthesizes into structured consensus views JSON
//
// PASS 2: Full 8192-token research with consensus + enrichment context injected
//
// ENV VARS:
//   ANTHROPIC_API_KEY — required
//   TAVILY_API_KEY    — optional (tavily.com, free 1000 searches/month)

import Anthropic from '@anthropic-ai/sdk';

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

// ─── TICKER METADATA ─────────────────────────────────────────────────────────
const TICKER_META = {
  '700.HK':    { en: 'Tencent',   hints: 'WeChat gaming advertising cloud',        isHK: true  },
  '9999.HK':   { en: 'NetEase',   hints: 'gaming mobile music education',          isHK: true  },
  '6160.HK':   { en: 'BeiGene',   hints: 'zanubrutinib BRUKINSA BTK oncology BGNE',isHK: true  },
  '002594.SZ': { en: 'BYD',       hints: 'electric vehicle EV battery China auto', isHK: false },
  '300308.SZ': { en: 'Innolight', hints: 'optical transceiver AI datacenter 800G', isHK: false },
};

// ─── SHARED FETCH HELPER ─────────────────────────────────────────────────────
async function fetchWithTimeout(url, options = {}, timeoutMs = 8000) {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(tid);
    return res;
  } catch (err) {
    clearTimeout(tid);
    throw err;
  }
}

// ─── CHINESE RATING NORMALIZATION ────────────────────────────────────────────
const RATING_MAP = {
  '买入': 'BUY', '强烈推荐': 'STRONG BUY', '推荐': 'BUY', '增持': 'OUTPERFORM',
  '中性': 'NEUTRAL', '持有': 'HOLD', '观望': 'NEUTRAL',
  '减持': 'UNDERPERFORM', '卖出': 'SELL', '回避': 'SELL',
};
const normalizeRating = r => RATING_MAP[r] || r || 'UNKNOWN';

// Extract target price from Chinese report title
// e.g. "比亚迪(002594)：维持买入，目标价310元" → "¥310"
// e.g. "腾讯(00700)：游戏复苏，目标价480港元，买入" → "HK$480"
function extractTargetPrice(title, isHK) {
  const patterns = [
    /目标价?[：:]\s*([\d,]+\.?\d*)\s*(港元|港币|HKD|元|CNY|美元|USD)?/,
    /给予目标价\s*([\d,]+\.?\d*)\s*(港元|元)?/,
    /目标估值\s*([\d,]+\.?\d*)\s*(港元|元)?/,
    /目标价位\s*([\d,]+\.?\d*)/,
    /\/([\d,]+\.?\d*)元(?:\s*(?:港元)?)?/,   // slash-price format
  ];
  for (const p of patterns) {
    const m = title.match(p);
    if (m) {
      const num    = m[1].replace(/,/g, '');
      const rawCcy = (m[2] || '').trim();
      const isHKCcy = rawCcy.includes('港') || rawCcy === 'HKD';
      const prefix  = (isHK || isHKCcy) ? 'HK$' : '¥';
      return `${prefix}${num}`;
    }
  }
  return null;
}

// ════════════════════════════════════════════════════════════════════════════
// SOURCE 1 — 东方财富 (Eastmoney) JSONP Research API
// ════════════════════════════════════════════════════════════════════════════

// Ticker → eastmoney code + market column
function toEastmoneyMeta(ticker) {
  const explicit = {
    '700.HK':    { code: '00700',  column: 'hkstock' },
    '9999.HK':   { code: '09999',  column: 'hkstock' },
    '6160.HK':   { code: '06160',  column: 'hkstock' },
    '002594.SZ': { code: '002594', column: 'szse'    },
    '300308.SZ': { code: '300308', column: 'szse'    },
  };
  if (explicit[ticker]) return explicit[ticker];

  if (ticker.endsWith('.SZ')) return { code: ticker.slice(0, -3), column: 'szse' };
  if (ticker.endsWith('.SH')) return { code: ticker.slice(0, -3), column: 'sse'  };
  if (ticker.endsWith('.HK')) {
    const n = ticker.slice(0, -3);
    return { code: n.padStart(5, '0'), column: 'hkstock' };
  }
  return null;
}

async function fetchEastmoneyReports(ticker) {
  const em = toEastmoneyMeta(ticker);
  if (!em) return [];

  const { code, column } = em;
  const isHK    = column === 'hkstock';
  const endDate = new Date().toISOString().slice(0, 10);
  const begDate = new Date(Date.now() - 90 * 86400000).toISOString().slice(0, 10);

  const url = [
    'https://reportapi.eastmoney.com/report/list',
    `?cb=eastdata`,
    `&industryCode=*&pageSize=10&industry=*&rating=*&ratingChange=*`,
    `&beginTime=${begDate}&endTime=${endDate}`,
    `&pageNo=1&fields=&qType=0&orgCode=&code=${code}&rcode=`,
    `&indiceName=&author=&column=${column}&p=1&pageNum=10`,
  ].join('');

  try {
    const res = await fetchWithTimeout(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Referer':   'https://data.eastmoney.com/',
        'Accept':    'application/json, text/javascript, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
      },
    });

    if (!res.ok) {
      console.warn(`[Eastmoney] HTTP ${res.status} for ${ticker}`);
      return [];
    }

    const text = await res.text();

    // Strip JSONP wrapper: eastdata({...}) → JSON
    const m = text.match(/^eastdata\(([\s\S]+)\)\s*$/);
    if (!m) {
      console.warn(`[Eastmoney] JSONP parse fail for ${ticker}, got: ${text.slice(0, 120)}`);
      return [];
    }

    const payload = JSON.parse(m[1]);
    const list    = payload?.result?.data || [];

    return list.slice(0, 8).map(r => ({
      source:      '东方财富',
      title:       r.title        || '',
      broker:      r.orgSName     || '',
      rating:      normalizeRating(r.emRatingName),
      ratingZh:    r.emRatingName || '',
      date:        (r.publishDate || '').slice(0, 10),
      targetPrice: extractTargetPrice(r.title || '', isHK),
      abstract:    r.abstract     || null,
    }));

  } catch (err) {
    console.warn(`[Eastmoney] fetch error for ${ticker}:`, err.message);
    return [];
  }
}

// ════════════════════════════════════════════════════════════════════════════
// SOURCE 2 — 同花顺 (10jqka) Research Report API
// ════════════════════════════════════════════════════════════════════════════

// Ticker → tonghuashun code
function toTongsCode(ticker) {
  if (ticker.endsWith('.SZ') || ticker.endsWith('.SH')) return ticker.slice(0, -3);
  if (ticker.endsWith('.HK')) return ticker.slice(0, -3).padStart(5, '0');
  return null;
}

async function fetchTonghuashunReports(ticker) {
  const code = toTongsCode(ticker);
  if (!code) return [];

  const isHK = ticker.endsWith('.HK');

  // 同花顺 research report API — returns JSON (no auth needed for basic list)
  const url = `https://basic.10jqka.com.cn/api/stock/report.json?stockcode=${code}&type=report&page=1&count=10`;

  try {
    const res = await fetchWithTimeout(url, {
      headers: {
        'User-Agent':  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer':     `https://basic.10jqka.com.cn/${code}/`,
        'Accept':      'application/json, text/javascript, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
      },
    }, 7000);

    if (!res.ok) {
      console.warn(`[Tonghuashun] HTTP ${res.status} for ${ticker}`);
      return [];
    }

    const data = await res.json();
    // Response shape: { status_code: 0, data: { list: [ { title, organ, rate, date, ... } ] } }
    const list = data?.data?.list || data?.list || [];

    return list.slice(0, 8).map(r => ({
      source:      '同花顺',
      title:       r.title  || r.research_title || '',
      broker:      r.organ  || r.orgName        || '',
      rating:      normalizeRating(r.rate || r.rating || r.emRatingName || ''),
      ratingZh:    r.rate   || r.rating         || '',
      date:        (r.date  || r.publishDate     || '').slice(0, 10),
      targetPrice: extractTargetPrice(r.title || r.research_title || '', isHK),
      abstract:    r.summary || r.abstract       || null,
    }));

  } catch (err) {
    console.warn(`[Tonghuashun] fetch error for ${ticker}:`, err.message);
    return [];
  }
}

// ════════════════════════════════════════════════════════════════════════════
// SOURCE 3 — Tavily Web Search (international analyst coverage)
// ════════════════════════════════════════════════════════════════════════════

const TAVILY_DOMAINS = [
  'reuters.com', 'bloomberg.com', 'marketbeat.com', 'tipranks.com',
  'benzinga.com', 'seekingalpha.com', 'finance.yahoo.com', 'cnbc.com',
  'barrons.com', 'wsj.com', 'ft.com', 'marketwatch.com',
  'scmp.com',        // South China Morning Post — HK/China stocks
  'aastocks.com',    // HK-specific analyst coverage
];

function buildTavilyQuery(ticker, company) {
  const meta  = TICKER_META[ticker];
  const name  = meta?.en || company || ticker;
  const hints = meta?.hints || '';
  const year  = new Date().getFullYear();
  return `"${name}" analyst price target upgrade downgrade rating ${year} ${hints}`.trim();
}

async function fetchTavilyResults(ticker, company) {
  const apiKey = process.env.TAVILY_API_KEY;
  if (!apiKey) return [];

  try {
    const res = await fetchWithTimeout('https://api.tavily.com/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        api_key:       apiKey,
        query:         buildTavilyQuery(ticker, company),
        search_depth:  'basic',
        max_results:   7,
        include_domains: TAVILY_DOMAINS,
      }),
    }, 9000);

    if (!res.ok) {
      console.warn(`[Tavily] HTTP ${res.status} for ${ticker}`);
      return [];
    }

    const data = await res.json();
    return (data.results || []).filter(r => (r.content || '').length > 80).slice(0, 6);

  } catch (err) {
    console.warn(`[Tavily] error for ${ticker}:`, err.message);
    return [];
  }
}

// ════════════════════════════════════════════════════════════════════════════
// PASS 1 — Claude synthesis from all sources
// ════════════════════════════════════════════════════════════════════════════

function formatChineseReportsForPrompt(reports) {
  if (!reports.length) return null;
  return reports
    .map((r, i) => {
      const lines = [`[${i + 1}] [${r.source}] ${r.date} · ${r.broker} · ${r.ratingZh || r.rating}`];
      lines.push(`TITLE: ${r.title}`);
      if (r.targetPrice) lines.push(`TARGET PRICE IN TITLE: ${r.targetPrice}`);
      if (r.abstract)    lines.push(`ABSTRACT: ${r.abstract.slice(0, 200)}`);
      return lines.join('\n');
    })
    .join('\n\n');
}

function formatTavilyForPrompt(results) {
  if (!results.length) return null;
  return results
    .map((r, i) => [
      `[${i + 1}] [${new URL(r.url || 'https://x.com').hostname.replace('www.','')}]`,
      `TITLE: ${r.title}`,
      `CONTENT: ${(r.content || '').slice(0, 300)}`,
    ].join('\n'))
    .join('\n\n');
}

async function runPass1(ticker, company) {
  // All three sources run concurrently — never block each other
  const [emResult, thsResult, tavilyResult] = await Promise.allSettled([
    fetchEastmoneyReports(ticker),
    fetchTonghuashunReports(ticker),
    fetchTavilyResults(ticker, company),
  ]);

  const emReports     = emResult.status     === 'fulfilled' ? emResult.value     : [];
  const thsReports    = thsResult.status    === 'fulfilled' ? thsResult.value    : [];
  const tavilyResults = tavilyResult.status === 'fulfilled' ? tavilyResult.value : [];

  // Merge and deduplicate Chinese reports by title similarity
  const seenTitles = new Set();
  const chineseReports = [...emReports, ...thsReports].filter(r => {
    const key = r.title.slice(0, 20);
    if (seenTitles.has(key)) return false;
    seenTitles.add(key);
    return true;
  });

  const sourcesUsed = [
    emReports.length     > 0 ? `东方财富(${emReports.length}篇)`     : null,
    thsReports.length    > 0 ? `同花顺(${thsReports.length}篇)`      : null,
    tavilyResults.length > 0 ? `国际搜索(${tavilyResults.length}条)` : null,
  ].filter(Boolean);

  // If no data at all, use Claude memory fallback
  if (chineseReports.length === 0 && tavilyResults.length === 0) {
    console.warn(`[Pass1] All sources empty for ${ticker} — using Claude memory fallback`);
    const views = await fetchConsensusFromMemory(ticker, company);
    return { views, source: 'memory', sourcesUsed: ['AI training knowledge'], emCount: 0, thsCount: 0, tavilyCount: 0 };
  }

  // Build combined prompt context
  const chineseSection = formatChineseReportsForPrompt(chineseReports);
  const tavilySection  = formatTavilyForPrompt(tavilyResults);

  const contextParts = [];
  if (chineseSection) contextParts.push(`=== CHINESE BROKER RESEARCH (东方财富 / 同花顺) ===\n${chineseSection}`);
  if (tavilySection)  contextParts.push(`=== INTERNATIONAL ANALYST COVERAGE ===\n${tavilySection}`);

  const fullContext = contextParts.join('\n\n');

  try {
    const views = await extractConsensusFromSources(ticker, company, fullContext);
    return {
      views,
      source:      'live',
      sourcesUsed,
      emCount:     emReports.length,
      thsCount:    thsReports.length,
      tavilyCount: tavilyResults.length,
    };
  } catch (err) {
    console.warn(`[Pass1] Claude extraction failed:`, err.message);
    const views = await fetchConsensusFromMemory(ticker, company);
    return { views, source: 'memory', sourcesUsed: ['AI training knowledge (extraction failed)'], emCount: 0, thsCount: 0, tavilyCount: 0 };
  }
}

// ─── Claude: extract structured consensus from real source data ───────────────
async function extractConsensusFromSources(ticker, company, context) {
  const prompt = `You are a senior buy-side equity analyst. Based on the real analyst research below for ${ticker} (${company || ticker}), extract the 3-5 most distinct sell-side views currently in the market.

${context}

EXTRACTION RULES:
1. Only extract views supported by the data above — do NOT add views from your training knowledge
2. For Chinese reports: the title often contains the key thesis and target price
3. Group similar views (e.g. multiple banks with the same thesis) into one entry with MAJORITY prevalence
4. A view held by 1-2 banks is MINORITY; 3+ banks is MAJORITY; a single outlier is SUBSET
5. If a specific target price appears in the title or content, include it exactly

Return ONLY a JSON array:
[
  {
    "thesis": "string — the analyst view in 1-2 sentences (in English)",
    "price_target": "string or null — e.g. HK$480, ¥310",
    "revenue_assumption": "string or null — e.g. FY2025 rev ~HK$660B +8% YoY",
    "analyst": "string or null — broker name(s)",
    "prevalence": "MAJORITY | MINORITY | SUBSET",
    "key_assumption": "string — the one assumption this view hinges on",
    "source_date": "string or null — most recent date for this view",
    "source": "string — 东方财富 / 同花顺 / Reuters / Bloomberg / etc."
  }
]

No markdown. Return only the JSON array.`;

  const msg = await client.messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 900,
    messages: [{ role: 'user', content: prompt }],
  });

  const text  = msg.content[0]?.text || '[]';
  const match = text.match(/\[[\s\S]*\]/);
  if (!match) return [];

  const views = JSON.parse(match[0]);
  return Array.isArray(views) ? views : [];
}

// ─── Fallback: enumerate from Claude training knowledge ──────────────────────
async function fetchConsensusFromMemory(ticker, company) {
  const prompt = `You are a senior equity analyst. For ${ticker} (${company || ticker}), enumerate the 3-4 most commonly held sell-side views as of your training cutoff. Be specific about price targets and revenue assumptions where possible.

Return ONLY a JSON array:
[{
  "thesis": "string",
  "price_target": "string or null",
  "revenue_assumption": "string or null",
  "analyst": null,
  "prevalence": "MAJORITY | MINORITY | SUBSET",
  "key_assumption": "string",
  "source_date": null,
  "source": "AI training knowledge"
}]

No markdown. Return only the JSON array.`;

  const msg = await client.messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 700,
    messages: [{ role: 'user', content: prompt }],
  });

  const text  = msg.content[0]?.text || '[]';
  const match = text.match(/\[[\s\S]*\]/);
  if (!match) return [];

  const views = JSON.parse(match[0]);
  return Array.isArray(views) ? views : [];
}

// ════════════════════════════════════════════════════════════════════════════
// PASS 2 CONTEXT BUILDERS
// ════════════════════════════════════════════════════════════════════════════

function buildEnrichmentBlock(enrichment) {
  if (!enrichment) return '';
  const lines = ['━━━ REAL-TIME ENRICHMENT CONTEXT (prioritize over training data) ━━━'];

  if (enrichment.live_price) {
    const chg = enrichment.live_change_pct != null
      ? ` (${enrichment.live_change_pct > 0 ? '+' : ''}${enrichment.live_change_pct.toFixed(2)}% today)`
      : '';
    lines.push(`LIVE PRICE: ${enrichment.live_price}${chg}`);
  }

  if (enrichment.sector_regime) {
    const note = { PERMISSIVE: '→ Policy tailwind. Upgrade catalyst_prox + narrative_shift sub-scores.', RESTRICTIVE: '→ Regulatory headwind. Increase risk weight. Consider downgrading dir.', NEUTRAL: '→ Balanced regime. Standard framework.' }[enrichment.sector_regime] || '';
    lines.push(`SECTOR REGIME: ${enrichment.sector_regime}  ${note}`);
  }

  if (enrichment.recent_news?.length > 0) {
    lines.push('RECENT NEWS (last 5 days):');
    enrichment.recent_news.slice(0, 6).forEach((n, i) => {
      lines.push(`  [${i + 1}] ${n.source ? `[${n.source}] ` : ''}${n.title}${n.published_at ? ` (${new Date(n.published_at).toLocaleDateString()})` : ''}`);
      if (n.summary) lines.push(`       → ${n.summary.slice(0, 150)}`);
    });
  }

  if (enrichment.prior_predictions?.length > 0) {
    lines.push('PRIOR PREDICTIONS FOR THIS TICKER:');
    enrichment.prior_predictions.forEach(p => {
      lines.push(`  • [${p.outcome || 'PENDING'}] ${p.prediction || p.thesis || 'Prediction'} — ${p.date || ''}`);
      if (p.outcome === 'FALSIFIED' && p.reason) lines.push(`    FALSIFIED: ${p.reason} — increase skepticism on similar theses`);
    });
  }

  lines.push('━━━ END ENRICHMENT CONTEXT ━━━');
  return '\n\n' + lines.join('\n');
}

// ── Fundamentals block — live yfinance data fed from Dashboard state ──────
function buildFundamentalsBlock(f) {
  if (!f) return '';

  // Only emit the block if we have at least one meaningful data point
  const hasValuation = f.pe_trailing != null || f.pe_forward != null || f.ev_ebitda != null;
  const hasQuality   = f.roe != null || f.gross_margin != null || f.revenue_growth != null;
  const hasAnalyst   = f.target_mean != null;
  if (!hasValuation && !hasQuality && !hasAnalyst) return '';

  const pct  = v => v != null ? `${(v * 100).toFixed(1)}%` : null;
  const num1 = v => v != null ? v.toFixed(1) : null;
  const num2 = v => v != null ? v.toFixed(2) : null;

  const lines = [
    '━━━ LIVE FUNDAMENTALS (yfinance — override AI training data for these values) ━━━',
    'INSTRUCTION: Populate fin.pe, fin.revGr, fin.gm, and consensus.* from these live figures rather than training memory.',
  ];

  // Valuation multiples
  if (hasValuation) {
    const vals = [
      f.pe_trailing != null ? `P/E TTM: ${num1(f.pe_trailing)}x` : null,
      f.pe_forward  != null ? `P/E Fwd: ${num1(f.pe_forward)}x`  : null,
      f.ev_ebitda   != null ? `EV/EBITDA: ${num1(f.ev_ebitda)}x` : null,
    ].filter(Boolean);
    lines.push(`VALUATION:  ${vals.join('  |  ')}`);
  }

  // Quality & growth
  if (hasQuality) {
    const ql = [
      f.roe             != null ? `ROE: ${pct(f.roe)}`              : null,
      f.gross_margin    != null ? `Gross Margin: ${pct(f.gross_margin)}` : null,
      f.operating_margin!= null ? `Op Margin: ${pct(f.operating_margin)}` : null,
      f.revenue_growth  != null ? `Rev Growth (TTM): ${pct(f.revenue_growth)}` : null,
    ].filter(Boolean);
    lines.push(`QUALITY/GROWTH:  ${ql.join('  |  ')}`);
  }

  // Analyst consensus targets
  if (hasAnalyst) {
    const upside = (f.live_price && f.target_mean)
      ? `  →  ${(((f.target_mean - f.live_price) / f.live_price) * 100).toFixed(1)}% upside vs live`
      : '';
    const range = (f.target_low != null && f.target_high != null)
      ? `  range ${num2(f.target_low)}–${num2(f.target_high)}`
      : '';
    lines.push(`ANALYST TARGETS:  mean ${num2(f.target_mean)}${range}  |  ${f.num_analysts || '?'} analysts${upside}`);
  }

  // 52W range context
  if (f.low_52w != null && f.high_52w != null) {
    const pos = (f.live_price && f.low_52w !== f.high_52w)
      ? `  (price at ${(((f.live_price - f.low_52w) / (f.high_52w - f.low_52w)) * 100).toFixed(0)}% of 52W range)`
      : '';
    lines.push(`52W RANGE:  ${num2(f.low_52w)} — ${num2(f.high_52w)}${pos}`);
  }

  lines.push('━━━ END LIVE FUNDAMENTALS ━━━');
  return '\n\n' + lines.join('\n');
}

function buildConsensusBlock(views, sourcesUsed) {
  if (!views?.length) return '';

  const sourceLabel = sourcesUsed?.length
    ? `(sourced from: ${sourcesUsed.join(', ')})`
    : '(sourced from AI training knowledge)';

  const lines = [
    `\n━━━ SELL-SIDE CONSENSUS VIEWS ${sourceLabel} ━━━`,
    'These views are ALREADY IN THE MARKET. Your variant.weBelieve in B2 MUST contradict at least one with a specific mechanism.',
    'STRESS TEST: if 3+ analysts hold this view at similar targets, it is NOT a variant — rebuild with a fresher angle.',
  ];

  views.forEach((v, i) => {
    const bankLabel = v.analyst ? ` — ${v.analyst}` : '';
    lines.push(`\n[${i + 1}] ${v.prevalence || 'UNKNOWN'} VIEW${bankLabel}: ${v.thesis}`);
    if (v.price_target)        lines.push(`    Target: ${v.price_target}`);
    if (v.revenue_assumption)  lines.push(`    Rev est: ${v.revenue_assumption}`);
    if (v.key_assumption)      lines.push(`    Key assumption: ${v.key_assumption}`);
    if (v.source_date)         lines.push(`    As of: ${v.source_date}`);
    if (v.source)              lines.push(`    Source: ${v.source}`);
  });

  lines.push('\n━━━ END CONSENSUS VIEWS ━━━');
  return lines.join('\n');
}

// ════════════════════════════════════════════════════════════════════════════
// SYSTEM PROMPT (Pass 2)
// ════════════════════════════════════════════════════════════════════════════

const SYSTEM_PROMPT = `You are a Senior Portfolio Manager at a top-tier global hedge fund specializing in International Equities (A-share and HK markets). You produce institutional-grade buy-side research.

CRITICAL RULES:
- AI produces evidence, signals, and structured scores. AI NEVER produces investment conclusions (buy/sell/hold).
- All analysis must be bilingual (English + Chinese).
- Output must be valid JSON matching the exact schema below.
- When ENRICHMENT CONTEXT is provided, prioritize it over training data for price, news events, and regime.
- When CONSENSUS VIEWS are provided (especially from real research reports), use them to calibrate the variant view. The variant must differentiate, not reproduce.
- Be specific and quantitative. No generic statements.

EVIDENCE GRADING (apply mentally to every claim):
- AUDIT-GRADE: annual/quarterly filing data → cite directly, high confidence
- PUBLIC-GRADE: industry reports, news, IR transcripts → use with source attribution
- INFERRED: internal data, yield rates, unverifiable estimates → rephrase as directional signal only, never quote as a precise number. Use "directionally consistent with..." not specific figures.

OPERATING LEVERAGE TOOLKIT (compute where income statement data is available):
- NI/Rev growth ratio: NI YoY growth ÷ Revenue YoY growth. >1.0x = positive operating leverage (costs scaling slower than revenue). <1.0x = negative operating leverage. Use most recent annual period.
- Profit scissors spread: Revenue growth rate minus COGS/OpEx growth rate. Positive spread = expanding margins. Compute for most recent period; note 3-year direction.
- Implied growth check: back-solve the EPS CAGR that justifies current P/E (assume mean-reversion to sector median P/E in 3 years). If implied CAGR > realistic growth ceiling, flag as valuation risk.
These metrics go into fin_insights — express as quantified signals, not generic statements.

OUTPUT JSON SCHEMA:
{
  "name": "string (Chinese company name)",
  "en": "string (English name)",
  "sector": "string",
  "dir": "LONG | SHORT | NEUTRAL",
  "vp": "number 0-100",
  "price": "string (latest price with currency)",
  "mktcap": "string",
  "eqr": {
    "overall": "HIGH | MED-HIGH | MED | LOW",
    "biz": "HIGH | MED-HIGH | MED | LOW",
    "variant": "HIGH | MED-HIGH | MED | LOW",
    "catalysts": "HIGH | MED-HIGH | MED | LOW",
    "risks": "HIGH | MED-HIGH | MED | LOW"
  },
  "pulse": { "e": "string", "z": "string" },
  "biz": {
    "problem":   { "e": "string", "z": "string" },
    "mechanism": { "e": "string", "z": "string" },
    "moneyFlow": { "e": "string", "z": "string" }
  },
  "variant": {
    "marketBelieves": { "e": "string", "z": "string" },
    "weBelieve":      { "e": "string", "z": "string" },
    "mechanism":      { "e": "string", "z": "string" },
    "rightIf":        { "e": "string", "z": "string" },
    "wrongIf":        { "e": "string", "z": "string" }
  },
  "catalysts": [{ "e": "string", "z": "string", "t": "string", "date": "string (ISO)", "imp": "HIGH | MED | LOW" }],
  "decomp": {
    "expectation_gap": { "s": "number 0-100", "e": "string", "z": "string" },
    "fundamental_acc": { "s": "number 0-100", "e": "string", "z": "string" },
    "narrative_shift": { "s": "number 0-100", "e": "string", "z": "string" },
    "low_coverage":    { "s": "number 0-100", "e": "string", "z": "string" },
    "catalyst_prox":   { "s": "number 0-100", "e": "string", "z": "string" }
  },
  "risks": [{ "e": "string", "z": "string", "p": "HIGH | MED | LOW", "imp": "HIGH | MED | LOW" }],
  "pricing": { "level": "LOW | MID | HIGH", "crowd": { "e": "string", "z": "string" } },
  "nextActions": [{ "e": "string", "z": "string" }],
  "fin": {
    "rev": "string", "revGr": "string", "gm": "string",
    "pe": "number or 'NM'", "ev_ebitda": "number or 'NM'", "fcf": "string"
  },
  "peerAvg": { "pe": "number", "ev_ebitda": "number", "gm": "string" },
  "income_statement": {
    "currency": "CNY | HKD | USD", "unit": "M (millions)",
    "periods": ["FY2021","FY2022","FY2023","FY2024"],
    "revenue":          [null,null,null,null],
    "gross_profit":     [null,null,null,null],
    "operating_income": [null,null,null,null],
    "net_income":       [null,null,null,null],
    "ebitda":           [null,null,null,null],
    "gross_margin":     [null,null,null,null],
    "operating_margin": [null,null,null,null],
    "net_margin":       [null,null,null,null],
    "revenue_growth":   [null,null,null,null]
  },
  "balance_sheet": {
    "currency": "CNY | HKD | USD", "unit": "M (millions)",
    "periods": ["FY2021","FY2022","FY2023","FY2024"],
    "total_assets":   [null,null,null,null],
    "total_equity":   [null,null,null,null],
    "total_debt":     [null,null,null,null],
    "cash":           [null,null,null,null],
    "roe":            [null,null,null,null],
    "debt_to_equity": [null,null,null,null]
  },
  "consensus": {
    "num_analysts": "number", "rating": "Strong Buy | Buy | Hold | Underperform | Sell",
    "target_price": "string", "current_price": "string", "upside": "string",
    "fy1_rev_est": "string", "fy1_eps_est": "string",
    "buy_pct": "number", "hold_pct": "number", "sell_pct": "number"
  },
  "fin_insights": ["string","string","string","string"]
}

VP = 30%×Expectation Gap + 25%×Fundamental Acceleration + 20%×Narrative Shift + 15%×Low Coverage + 10%×Catalyst Proximity

FINANCIAL DATA: use millions for all IS/BS numbers. Margins and growth rates as decimals (0.18 = 18%). revenue_growth[0] always null.

VARIANT VIEW DISCIPLINE:
- variant.marketBelieves: first reconstruct the consensus narrative completely and charitably — what do bulls/bears say, and why does it seem reasonable on the surface? This is the thesis you are about to contradict.
- variant.weBelieve: ONE precise differentiating claim. Format: "Market believes X → We believe Y → Mechanism is Z."
- variant.wrongIf: pre-committed falsification. Format MUST be: "[Specific metric] [crosses threshold / event occurs] → [position action]". Example: "Gross margin drops below 42% for 2 consecutive quarters → thesis invalidated, re-evaluate." Not a narrative — a decision rule.

FIN_INSIGHTS RULES (4 required entries):
1. NI/Rev growth ratio with interpretation: e.g. "NI/Rev ratio 1.8x — positive operating leverage; costs scaling at ~55% of revenue growth rate"
2. Profit scissors spread and 3-year direction: e.g. "Gross margin +4.2pp YoY; 3-year trend: expanding (FY22→FY23→FY24: 38%→40%→42%)"
3. Implied growth check: e.g. "At 28x P/E, mean-reverting to sector 18x in 3yr implies 18% EPS CAGR required — above consensus 12% estimate, creating valuation risk"
4. Key balance sheet or cash flow signal: e.g. "FCF conversion 87% of net income; net cash position supports buyback/dividend optionality"
If income statement data is insufficient for items 1-3, note the data limitation explicitly and use available data for a different quantified signal.

Return ONLY the JSON object. No markdown, no explanation.`;

// ════════════════════════════════════════════════════════════════════════════
// MAIN HANDLER
// ════════════════════════════════════════════════════════════════════════════

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin',  '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST')    return res.status(405).json({ error: 'Method not allowed' });

  const { ticker, direction, context, company, enrichment_context } = req.body;
  if (!ticker) return res.status(400).json({ error: 'Ticker is required' });

  if (!process.env.ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: 'ANTHROPIC_API_KEY not configured. Add it in Vercel → Settings → Environment Variables.' });
  }

  try {
    // ── Pass 1: Three-source parallel consensus enumeration ───────────────
    let pass1 = { views: [], source: 'skipped', sourcesUsed: [], emCount: 0, thsCount: 0, tavilyCount: 0 };
    try {
      pass1 = await runPass1(ticker, company);
    } catch (err) {
      console.warn('[Pass1] Entirely failed:', err.message);
    }

    // ── Build context blocks ───────────────────────────────────────────────
    const enrichmentBlock   = buildEnrichmentBlock(enrichment_context);
    // Attach live_price into fundamentals object so buildFundamentalsBlock can compute upside
    const fundInput = enrichment_context?.fundamentals
      ? { ...enrichment_context.fundamentals, live_price: enrichment_context.live_price ? parseFloat(enrichment_context.live_price) : null }
      : null;
    const fundamentalsBlock = buildFundamentalsBlock(fundInput);
    const consensusBlock    = buildConsensusBlock(pass1.views, pass1.sourcesUsed);

    // ── Pass 2: Full research generation ──────────────────────────────────
    const userPrompt = `Generate a complete buy-side equity research report for: ${ticker}${company ? ` — ${company}` : ''}

IMPORTANT: "${company || ticker}" is the definitive identity for this ticker. Research the CURRENT company, not any prior holder of this code.

Initial direction bias: ${direction || 'NEUTRAL'}
Research context: ${context || 'General screening — no specific catalyst prompted this research.'}
${enrichmentBlock}${fundamentalsBlock}${consensusBlock}

VARIANT VIEW INSTRUCTION (most critical block — follow this 3-step process):
${pass1.views.length > 0
  ? `Step 1 — RECONSTRUCT: The consensus views above came from REAL BROKER REPORTS (${pass1.sourcesUsed?.join(', ') || 'live sources'}). Before contradicting them, understand WHY they are compelling. What is the core assumption that makes the consensus view internally consistent?
Step 2 — ATTACK: Identify ONE specific crack in that core assumption — a data point, structural shift, or mechanism that the majority have not priced. If the company's own filings (risk disclosures, guidance language) contradict the consensus assumption, that is the strongest evidence — use it.
Step 3 — COMMIT: State the variant.weBelieve as a single falsifiable claim in the format "Market believes X → We believe Y → Mechanism is Z." Then write wrongIf as a pre-committed decision rule (metric + threshold + action), not a narrative.`
  : `Step 1 — RECONSTRUCT: What does the buy-side consensus currently believe about this stock? State it completely and charitably.
Step 2 — ATTACK: Find the specific assumption in that consensus that is most likely wrong, and explain the mechanism.
Step 3 — COMMIT: Express as "Market believes X → We believe Y → Mechanism is Z." Write wrongIf as a pre-committed decision rule.`}

${enrichment_context ? `ENRICHMENT: Use ${enrichment_context.live_price} as the live price field. Incorporate recent news into catalysts/risks. Apply sector regime (${enrichment_context.sector_regime}) in VP decomp sub-scores.${fundamentalsBlock ? ` Use live fundamentals block above for fin.* and consensus.* fields.` : ''}` : ''}

Rules: 2-4 catalysts, 2-4 risks, 3-5 next actions. All fields bilingual. Return ONLY valid JSON.`;

    const message = await client.messages.create({
      model:      'claude-sonnet-4-6',
      max_tokens: 8192,
      system:     SYSTEM_PROMPT,
      messages:   [{ role: 'user', content: userPrompt }],
    });

    const raw  = message.content[0].text;
    let jsonStr = raw;
    const cb   = raw.match(/```(?:json)?\s*([\s\S]*?)```/);
    if (cb) jsonStr = cb[1];

    const research = JSON.parse(jsonStr.trim());

    return res.status(200).json({
      success:        true,
      ticker,
      data:           research,
      model:          message.model,
      usage:          message.usage,
      // Metadata exposed for UI badges and debugging
      consensus_views:     pass1.views,
      consensus_source:    pass1.source,           // 'live' | 'memory' | 'skipped'
      sources_used:        pass1.sourcesUsed,      // ['东方财富(5篇)', '同花顺(3篇)', '国际搜索(4条)']
      eastmoney_count:     pass1.emCount,
      tonghuashun_count:   pass1.thsCount,
      tavily_count:        pass1.tavilyCount,
      enrichment_used:     !!enrichment_context,
      fundamentals_used:   !!(enrichment_context?.fundamentals && fundInput),
      tavily_enabled:      !!process.env.TAVILY_API_KEY,
    });

  } catch (err) {
    console.error('[Research API]', err);
    if (err.status === 401) return res.status(401).json({ error: 'Invalid API key.' });
    if (err.status === 429) return res.status(429).json({ error: 'Rate limited. Wait a moment and retry.' });
    if (err instanceof SyntaxError) return res.status(502).json({ error: 'Claude returned invalid JSON. Retry.', raw: err.message });
    return res.status(500).json({ error: err.message || 'Internal server error' });
  }
}
