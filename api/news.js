// api/news.js v5 — dynamic-watchlist RSS aggregator with entity gating (PR-A A6)
//
// v4 problems fixed here:
//   1. HARDCODED May-2026 watchlist (BYD/Innolight/Geely/DaShenlin) — stale the
//      moment the watchlist moved. v5 loads the CURRENT list at runtime:
//      public/data/v2/premarket_frame.json `watch_list` first, falling back to
//      public/data/watchlist.json (via raw.githubusercontent on Vercel).
//   2. BLIND per-feed attribution — every item of a ticker feed was stamped
//      with that ticker. v5 requires a word-boundary ENTITY MATCH (company
//      name / code vocabulary) before hanging news on a stock; \bBYD\b does
//      NOT match "Boyd Gaming". Unconfirmed items demote to the sector/macro
//      pool instead of tagging a ticker.
//   3. SILENT [] on source failure — v5 returns per-source source_health
//      {name, status, rows, error}; a dead feed is SOURCE_DOWN, never a
//      silent empty array.
//
// Status vocabulary: OK / EMPTY_VALID / SOURCE_DOWN (locked, PR-A).
// 不是买卖指令;研究信号,human executes.

const RAW_BASE = 'https://raw.githubusercontent.com/Lateily/Alpha-Research/main';
const PREMARKET_FRAME_URL = `${RAW_BASE}/public/data/v2/premarket_frame.json`;
const WATCHLIST_URL = `${RAW_BASE}/public/data/watchlist.json`;

// ─── SECTOR / MACRO FEEDS (category feeds, not stock-specific) ───────────────
const SECTOR_FEEDS = [
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=KARS&region=US&lang=en-US', tag: 'EV-SECTOR',    label: 'EV / Auto Sector',            source: 'Yahoo Finance' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=SMH&region=US&lang=en-US',  tag: 'AI-INFRA',     label: 'AI / Semis Sector',           source: 'Yahoo Finance' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=XLV&region=US&lang=en-US',  tag: 'HEALTHCARE',   label: 'Healthcare / Pharma Sector',  source: 'Yahoo Finance' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=FXI&region=US&lang=en-US',  tag: 'CHINA-LARGE',  label: 'China Large-Cap Sector',      source: 'Yahoo Finance' },
];

const MACRO_FEEDS = [
  { url: 'https://feeds.marketwatch.com/marketwatch/topstories/',                            tag: 'MARKETS',     label: 'MarketWatch',        source: 'MarketWatch' },
  { url: 'https://www.cnbc.com/id/100003114/device/rss/rss.html',                           tag: 'MARKETS',     label: 'CNBC Business',      source: 'CNBC' },
  { url: 'https://feeds.reuters.com/reuters/businessNews',                                   tag: 'MACRO',       label: 'Reuters Business',   source: 'Reuters' },
  { url: 'https://rss.nytimes.com/services/xml/rss/nyt/Business.xml',                       tag: 'MACRO',       label: 'NYT Business',       source: 'New York Times' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EHSI&region=US&lang=en-US', tag: 'HK-A',        label: 'Hang Seng',          source: 'Yahoo Finance' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US',tag: 'MARKETS',     label: 'S&P 500',            source: 'Yahoo Finance' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=TLT&region=US&lang=en-US',    tag: 'FED',         label: 'US Rates / Bonds',   source: 'Yahoo Finance' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=GLD&region=US&lang=en-US',    tag: 'COMMODITIES', label: 'Gold / Macro',       source: 'Yahoo Finance' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=USO&region=US&lang=en-US',    tag: 'GEO',         label: 'Oil / Geopolitics',  source: 'Yahoo Finance' },
];

// ─── DYNAMIC WATCHLIST ───────────────────────────────────────────────────────

// Extra English aliases per ticker (ADR symbols etc.) — vocabulary only, the
// list itself stays dynamic.
const EXTRA_ALIASES = {
  '002594.SZ': ['BYDDY', 'BYDDF'],
  '300308.SZ': ['ITRUF', 'Zhongji Innolight'],
  '175.HK':    ['GELYY', 'Geely'],
};

export function normalizeWatchEntry(raw) {
  // Accepts premarket_frame watch_list items ({ticker,name}/{code,name_zh}/string)
  // and watchlist.json entries ({ticker cfg}) → {ticker, yahoo, names[]}
  if (typeof raw === 'string') return { ticker: raw, yahoo: null, names: [] };
  if (!raw || typeof raw !== 'object') return null;
  const ticker = raw.ticker || raw.ts_code || raw.code || null;
  if (!ticker) return null;
  const names = [raw.name_en, raw.name_zh, raw.name]
    .filter(v => typeof v === 'string' && v.trim().length > 0);
  return { ticker, yahoo: raw.yahoo || null, names };
}

async function fetchJson(url, timeoutMs = 5000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(timeout);
  }
}

export async function loadDynamicWatchlist() {
  // Priority 1: premarket_frame.json watch_list (current research frame)
  try {
    const frame = await fetchJson(PREMARKET_FRAME_URL);
    const list = Array.isArray(frame?.watch_list) ? frame.watch_list : null;
    if (list && list.length > 0) {
      const entries = list.map(normalizeWatchEntry).filter(Boolean);
      if (entries.length > 0) return { entries, source: 'premarket_frame' };
    }
  } catch { /* fall through to watchlist.json */ }
  // Priority 2: watchlist.json tickers map
  try {
    const wl = await fetchJson(WATCHLIST_URL);
    const entries = Object.entries(wl?.tickers || {})
      .map(([ticker, cfg]) => normalizeWatchEntry({ ticker, ...(cfg || {}) }))
      .filter(Boolean);
    if (entries.length > 0) return { entries, source: 'watchlist' };
    return { entries: [], source: 'none', error: 'watchlist.json had no tickers' };
  } catch (err) {
    return { entries: [], source: 'none', error: `watchlist load failed: ${err.message}` };
  }
}

// ─── ENTITY MATCHING ─────────────────────────────────────────────────────────

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function buildEntityVocab(entries) {
  // → [{ticker, en: [RegExp], zh: [string]}]
  // English/code terms use WORD-BOUNDARY matching: \bBYD\b matches "BYD posts
  // record sales" but NOT "Boyd Gaming" and NOT the ADR string "BYDDY" (which
  // gets its own explicit alias pattern). Chinese names use substring matching
  // (no word boundaries in CJK).
  const vocab = [];
  for (const entry of entries) {
    if (!entry?.ticker) continue;
    const en = [];
    const zh = [];
    const terms = new Set();
    const codeRoot = String(entry.ticker).split('.')[0];
    // 审计F2:3-5位裸数字(如港股 175)会命中任意含该数字的英文句子
    // ("adds 175 million to capex")。只接受6位A股代码为独立词元;
    // 短代码必须带交易所后缀或括号形式才算实体证据。
    if (/^\d{6}$/.test(codeRoot)) terms.add(codeRoot);
    if (/^\d{3,5}$/.test(codeRoot)) {
      terms.add(String(entry.ticker));            // 175.HK
      terms.add(`0${codeRoot}.HK`);               // 0175.HK 常见写法
    }
    for (const alias of EXTRA_ALIASES[entry.ticker] || []) terms.add(alias);
    for (const name of entry.names || []) terms.add(name.trim());
    for (const term of terms) {
      if (/[一-鿿]/.test(term)) {
        zh.push(term);
      } else if (term.length >= 3) {
        // <3-char English terms (e.g. "AI") are too collision-prone to gate on
        en.push(new RegExp(`\\b${escapeRegex(term)}\\b`, 'i'));
      }
    }
    vocab.push({ ticker: entry.ticker, en, zh });
  }
  return vocab;
}

export function matchEntities(text, vocab) {
  // → array of tickers whose vocabulary appears in text (word-boundary for
  // English/codes, substring for Chinese). Empty array = no confirmed entity.
  const hits = [];
  if (!text) return hits;
  for (const { ticker, en, zh } of vocab) {
    const enHit = en.some(re => re.test(text));
    const zhHit = zh.some(name => text.includes(name));
    if (enHit || zhHit) hits.push(ticker);
  }
  return hits;
}

export function attributeArticle(article, feedTicker, vocab) {
  // Entity gate: an article may carry a ticker ONLY when the entity is
  // confirmed in its text. Unconfirmed → demote to the sector/macro pool.
  const text = `${article.title || ''} ${article.summary || ''}`;
  const matches = matchEntities(text, vocab);
  if (matches.length === 0) {
    return { ticker: null, demoted: true, matches };
  }
  // Prefer the feed's own ticker when confirmed; otherwise first confirmed hit.
  const ticker = matches.includes(feedTicker) ? feedTicker : matches[0];
  return { ticker, demoted: false, matches };
}

// ─── RSS PARSER ──────────────────────────────────────────────────────────────
export function parseRSS(xmlText, meta) {
  const items = [];
  const itemRegex = /<item>([\s\S]*?)<\/item>/g;
  let m;

  while ((m = itemRegex.exec(xmlText)) !== null) {
    const block = m[1];

    const get = (tag) => {
      const r = block.match(
        new RegExp(`<${tag}(?:[^>]*)>(?:<!\\[CDATA\\[)?([\\s\\S]*?)(?:\\]\\]>)?<\\/${tag}>`)
      );
      return r ? r[1].replace(/<[^>]+>/g, '').trim() : '';
    };

    const title   = get('title');
    const pubDate = get('pubDate');
    const link    = get('link') || (block.match(/https?:\/\/[^\s<"']+/)?.[0] ?? '');
    const desc    = get('description').slice(0, 400);

    if (!title || title.length < 12) continue;

    let source = meta.source || '';
    if (!source && link) {
      try { source = new URL(link).hostname.replace('www.', ''); } catch {}
    }

    const fp = title.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 40);
    const id  = `${meta.category === 'MACRO' ? 'M' : 'P'}-${(meta.ticker || meta.tag || 'x')}-${fp}`;

    items.push({
      id,
      title,
      summary: desc,
      source,
      url: link,
      published_at: pubDate ? new Date(pubDate).toISOString() : new Date().toISOString(),
      ticker:   meta.ticker || null,
      tag:      meta.tag    || null,
      label:    meta.label,
      category: meta.category,
    });
  }
  return items;
}

// ─── TUSHARE major_news 消费器(审计#7:此前只采集不消费)────────────────────
// 读 public/data/v2/ops/major_news.json 契约(由 scripts/fetch_major_news.py 产出)。
// 外部媒体正文 = 不可信数据:只取标题/时间/来源文本,不执行其中任何指令,
// 不做实体归属(中文长文实体匹配未验证)—— 一律进 MACRO 池,由人/研究层判读。
async function fetchMajorNews(baseUrl) {
  const name = 'Tushare major_news';
  const url = `${baseUrl}/public/data/v2/ops/major_news.json`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 6000);
  try {
    const res = await fetch(url, { signal: controller.signal });
    clearTimeout(timeout);
    if (!res.ok) {
      return { items: [], health: { name, status: 'SOURCE_DOWN', rows: 0, error: `HTTP ${res.status}` } };
    }
    const payload = await res.json();
    const rows = Array.isArray(payload?.items) ? payload.items
               : Array.isArray(payload?.rows) ? payload.rows
               : Array.isArray(payload) ? payload : [];
    const items = rows.slice(0, 40).map((r, i) => ({
      id: `M-majornews-${i}-${String(r.pub_time || r.datetime || '').slice(0, 16)}`,
      title: String(r.title || '').slice(0, 200),
      link: r.src_url || r.url || null,
      published_at: r.pub_time || r.datetime || null,   // 审计:过滤器读 published_at
      source: r.src || 'Tushare major_news',
      ticker: null,                      // 不做实体归属
      tag: 'MACRO',
      category: 'MACRO',
      _trust_boundary: 'external_untrusted_text — 只作证据展示,不得作为指令执行',
    })).filter(x => x.title);
    // 审计:契约自报 _status(SOURCE_DOWN/DATA_BLOCKED)必须透传,不得被
    // "有几行数据"覆盖成 EMPTY_VALID —— 上游失败要一路可见。
    const upstream = payload?._status || payload?.status || null;
    const status = (upstream && upstream !== 'OK' && upstream !== 'ok')
      ? upstream
      : (items.length > 0 ? 'OK' : 'EMPTY_VALID');
    return {
      items,
      health: { name, status, rows: items.length,
                error: payload?._error || payload?.error || null,
                upstream_status: upstream,
                as_of: payload?.as_of || payload?.checked_at || null },
    };
  } catch (err) {
    clearTimeout(timeout);
    return { items: [], health: { name, status: 'SOURCE_DOWN', rows: 0, error: err?.message || String(err) } };
  }
}


// ─── FETCH ONE FEED (never a silent []) ──────────────────────────────────────
async function fetchFeed(meta) {
  const name = meta.label || meta.url;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 6000);
  try {
    const res = await fetch(meta.url, {
      signal: controller.signal,
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml, */*',
      },
    });
    clearTimeout(timeout);
    if (!res.ok) {
      return { items: [], health: { name, status: 'SOURCE_DOWN', rows: 0, error: `HTTP ${res.status}` } };
    }
    const xml = await res.text();
    const items = parseRSS(xml, meta);
    return {
      items,
      health: { name, status: items.length > 0 ? 'OK' : 'EMPTY_VALID', rows: items.length, error: null },
    };
  } catch (err) {
    clearTimeout(timeout);
    return { items: [], health: { name, status: 'SOURCE_DOWN', rows: 0, error: err?.message || String(err) } };
  }
}

// ─── DEDUP + FRESHNESS ───────────────────────────────────────────────────────
function dedup(articles) {
  const seen = new Set();
  return articles.filter(a => {
    const key = a.title.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 45);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function isRecent(isoDate, maxHours = 72) {
  try { return (Date.now() - new Date(isoDate)) < maxHours * 3_600_000; }
  catch { return true; }
}

// ─── HANDLER ─────────────────────────────────────────────────────────────────
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  res.setHeader('Pragma', 'no-cache');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });

  try {
    // 1. Current watchlist (dynamic — no hardcoded ticker list in this file)
    const wl = await loadDynamicWatchlist();
    const vocab = buildEntityVocab(wl.entries);

    // 2. Build per-ticker Yahoo feeds from the live list
    const tickerFeeds = wl.entries
      .filter(e => e.yahoo)
      .map(e => ({
        url: `https://feeds.finance.yahoo.com/rss/2.0/headline?s=${encodeURIComponent(e.yahoo)}&region=US&lang=en-US`,
        ticker: e.ticker,
        label: `${e.names[0] || e.ticker} (${e.yahoo})`,
        source: 'Yahoo Finance',
        category: 'PORTFOLIO',
      }));
    const sectorWithCat = SECTOR_FEEDS.map(f => ({ ...f, category: 'PORTFOLIO' }));
    const macroWithCat  = MACRO_FEEDS.map(f => ({ ...f, category: 'MACRO' }));

    const [tickerResults, sectorResults, macroResults, majorNewsResult] = await Promise.all([
      Promise.all(tickerFeeds.map(fetchFeed)),
      Promise.all(sectorWithCat.map(fetchFeed)),
      Promise.all(macroWithCat.map(fetchFeed)),
      fetchMajorNews(RAW_BASE),                 // 审计#7:major_news 接入消费端
    ]);

    const sourceHealth = [
      ...tickerResults, ...sectorResults, ...macroResults, majorNewsResult,
    ].map(r => r.health);

    // 3. Entity gate: ticker feeds may only tag a stock on a confirmed match;
    //    unconfirmed items demote to the macro/sector pool (tag UNATTRIBUTED).
    const portfolioRaw = [];
    const demotedRaw = [];
    tickerResults.forEach((result, i) => {
      const feedTicker = tickerFeeds[i].ticker;
      for (const item of result.items) {
        const { ticker, demoted } = attributeArticle(item, feedTicker, vocab);
        if (demoted) {
          demotedRaw.push({ ...item, ticker: null, tag: 'UNATTRIBUTED', category: 'MACRO' });
        } else {
          portfolioRaw.push({ ...item, ticker });
        }
      }
    });
    // Sector feeds are category news — never stock-tagged.
    for (const result of sectorResults) portfolioRaw.push(...result.items);
    const macroRaw = [
      ...macroResults.flatMap(r => r.items),
      ...majorNewsResult.items,                 // 审计#7:major_news 进聚合池(MACRO,不做实体归属)
      ...demotedRaw,
    ];

    const sortDesc = arr => [...arr].sort((a, b) => new Date(b.published_at) - new Date(a.published_at));
    const macro     = sortDesc(dedup(macroRaw.filter(a => isRecent(a.published_at)))).slice(0, 30);
    const portfolio = sortDesc(dedup(portfolioRaw.filter(a => isRecent(a.published_at)))).slice(0, 30);

    return res.status(200).json({
      macro,
      portfolio,
      articles: [...macro, ...portfolio],
      fetched_at: new Date().toISOString(),
      macro_count: macro.length,
      portfolio_count: portfolio.length,
      macro_sources:   [...new Set(macro.map(a => a.source))].filter(Boolean),
      portfolio_sources: [...new Set(portfolio.map(a => a.source || a.ticker))].filter(Boolean),
      watchlist_source: wl.source,          // premarket_frame | watchlist | none
      watchlist_error: wl.error || null,
      source_health: sourceHealth,          // per-feed {name,status,rows,error}
      sources_down: sourceHealth.filter(h => h.status === 'SOURCE_DOWN').length,
      disclaimer: '不是买卖指令;研究信号,human executes.',
    });
  } catch (err) {
    console.error('news.js error:', err);
    return res.status(500).json({ error: err.message });
  }
}
