// api/news.js v4 — Source-specific RSS aggregator
// Root cause of v3 bug: Google News RSS rate-limits from Vercel shared IPs,
// returning identical cached responses regardless of query.
//
// Fix: dedicated RSS feeds per source. Portfolio = per-ticker Yahoo Finance.
// Macro = CNBC + MarketWatch + Reuters + Yahoo Finance index/ETF feeds.
// These are structurally different feeds → zero overlap between tabs.

// ─── PORTFOLIO FEEDS ─────────────────────────────────────────────────────────
// Per-stock Yahoo Finance RSS + sector ETFs. Updated every ~15min by Yahoo.
const PORTFOLIO_FEEDS = [
  // Focus stocks
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=0700.HK&region=US&lang=en-US',   ticker: '700.HK',       label: 'Tencent' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=9999.HK&region=US&lang=en-US',   ticker: '9999.HK',      label: 'NetEase' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=6160.HK&region=US&lang=en-US',   ticker: '6160.HK',      label: 'BeOne Medicines' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=BYDDY&region=US&lang=en-US',     ticker: '002594.SZ',    label: 'BYD' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=ITRUF&region=US&lang=en-US',     ticker: '300308.SZ',    label: 'Innolight' },
  // Sector proxies
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=SMH&region=US&lang=en-US',       ticker: 'AI-INFRA',     label: 'AI / Semis Sector' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=XBI&region=US&lang=en-US',       ticker: 'BIOTECH',      label: 'Biotech / Pharma Sector' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=KWEB&region=US&lang=en-US',      ticker: 'CHINA-INTERNET', label: 'China Internet Sector' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=KARS&region=US&lang=en-US',      ticker: 'EV-SECTOR',    label: 'EV / Auto Sector' },
];

// ─── MACRO FEEDS ─────────────────────────────────────────────────────────────
// Distinct from portfolio: financial news outlets + index/macro ETF feeds.
const MACRO_FEEDS = [
  // Financial news outlets (structurally different from Yahoo ticker RSS)
  { url: 'https://feeds.marketwatch.com/marketwatch/topstories/',                              tag: 'MARKETS',     label: 'MarketWatch', source: 'MarketWatch' },
  { url: 'https://www.cnbc.com/id/100003114/device/rss/rss.html',                             tag: 'MARKETS',     label: 'CNBC Business', source: 'CNBC' },
  { url: 'https://feeds.reuters.com/reuters/businessNews',                                     tag: 'MACRO',       label: 'Reuters Business', source: 'Reuters' },
  { url: 'https://rss.nytimes.com/services/xml/rss/nyt/Business.xml',                         tag: 'MACRO',       label: 'NYT Business', source: 'New York Times' },
  // Macro market proxies via Yahoo Finance index feeds (news about rates, gold, FX)
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EHSI&region=US&lang=en-US',   tag: 'HK-A',        label: 'Hang Seng', source: 'Yahoo Finance' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US',  tag: 'MARKETS',     label: 'S&P 500', source: 'Yahoo Finance' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=TLT&region=US&lang=en-US',      tag: 'FED',         label: 'US Rates / Bonds', source: 'Yahoo Finance' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=GLD&region=US&lang=en-US',      tag: 'COMMODITIES', label: 'Gold / Macro', source: 'Yahoo Finance' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=USO&region=US&lang=en-US',      tag: 'GEO',         label: 'Oil / Geopolitics', source: 'Yahoo Finance' },
];

// ─── RSS PARSER ──────────────────────────────────────────────────────────────
function parseRSS(xmlText, meta) {
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

    // Skip empty or placeholder items
    if (!title || title.length < 12) continue;

    // Source: use meta.source if provided, else fall back to domain
    let source = meta.source || '';
    if (!source && link) {
      try { source = new URL(link).hostname.replace('www.', ''); } catch {}
    }

    // Build stable ID: category + ticker/tag + title fingerprint
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

// ─── FETCH ONE FEED ──────────────────────────────────────────────────────────
async function fetchFeed(meta) {
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
    if (!res.ok) return [];
    const xml = await res.text();
    return parseRSS(xml, meta);
  } catch {
    clearTimeout(timeout);
    return [];
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
  // NO caching — always return fresh data
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  res.setHeader('Pragma', 'no-cache');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });

  try {
    const macroWithCat   = MACRO_FEEDS.map(f => ({ ...f, category: 'MACRO' }));
    const portfolioWithCat = PORTFOLIO_FEEDS.map(f => ({ ...f, category: 'PORTFOLIO' }));

    // Fetch both categories in parallel
    const [macroResults, portfolioResults] = await Promise.all([
      Promise.allSettled(macroWithCat.map(fetchFeed)),
      Promise.allSettled(portfolioWithCat.map(fetchFeed)),
    ]);

    const macroRaw     = macroResults.flatMap(r => r.status === 'fulfilled' ? r.value : []);
    const portfolioRaw = portfolioResults.flatMap(r => r.status === 'fulfilled' ? r.value : []);

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
    });
  } catch (err) {
    console.error('news.js error:', err);
    return res.status(500).json({ error: err.message });
  }
}
