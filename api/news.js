// api/news.js — Dual-category market news aggregator
// Sources: Google News RSS (aggregates FT · WSJ · Bloomberg · Reuters · CNBC · Economist · SCMP)
// No API key required — works from Vercel US servers
// Returns: { macro: Article[], portfolio: Article[], fetched_at }

// ─── MACRO FEEDS ────────────────────────────────────────────────────────────
// Global macro events: central banks, geopolitics, commodities, trade policy
const MACRO_FEEDS = [
  { query: 'Federal Reserve interest rate monetary policy inflation CPI', label: 'Fed / Central Banks', tag: 'FED' },
  { query: 'China economy PBOC stimulus GDP trade surplus yuan', label: 'China Macro', tag: 'CHINA-MACRO' },
  { query: 'US Iran geopolitical tension Middle East oil supply OPEC', label: 'Geopolitics', tag: 'GEO' },
  { query: 'global stock market equity correction bull bear risk', label: 'Global Markets', tag: 'MARKETS' },
  { query: 'oil gold dollar bond yield commodity futures', label: 'Commodities / FX', tag: 'COMMODITIES' },
  { query: 'Hong Kong Hang Seng China A-share stock market', label: 'HK / A-Share Market', tag: 'HK-A' },
  { query: 'trade tariff WTO deal sanctions economic agreement M&A', label: 'Trade / Policy', tag: 'TRADE' },
];

// ─── PORTFOLIO FEEDS ─────────────────────────────────────────────────────────
// Company-specific + sector impact
const PORTFOLIO_FEEDS = [
  { query: 'Tencent WeChat gaming advertising AI earnings revenue', label: 'Tencent', ticker: '700.HK' },
  { query: 'BYD electric vehicle EV sales exports solid state battery', label: 'BYD', ticker: '002594.SZ' },
  { query: 'NetEase gaming mobile Japan Blizzard revenue ARPU', label: 'NetEase', ticker: '9999.HK' },
  { query: 'BeiGene BeOne Medicines Brukinsa zanubrutinib BTK lymphoma', label: 'BeOne Medicines', ticker: '6160.HK' },
  { query: 'Innolight optical transceiver 800G 1.6T AI data center Nvidia', label: 'Innolight', ticker: '300308.SZ' },
  { query: 'China AI semiconductor Huawei Nvidia ban technology policy', label: 'AI Infra Sector', ticker: 'AI-INFRA' },
  { query: 'China biotech NMPA drug approval oncology clinical trial BD deal', label: 'Biotech Sector', ticker: 'BIOTECH' },
  { query: 'China EV Europe tariff battery supply chain solid state export', label: 'EV / Auto Sector', ticker: 'EV-SECTOR' },
];

// Known publishers and their brand colors (for badge rendering on frontend)
const SOURCE_META = {
  'Financial Times': { short: 'FT',        bg: '#FFF1E5', color: '#C9400A' },
  'Wall Street Journal': { short: 'WSJ',   bg: '#1A1A1A', color: '#fff' },
  'Bloomberg': { short: 'BBG',             bg: '#000',    color: '#FF6F0F' },
  'Reuters': { short: 'Reuters',           bg: '#FF6F0F', color: '#fff' },
  'CNBC': { short: 'CNBC',                 bg: '#0F0F0F', color: '#FFD700' },
  'The Economist': { short: 'Econ',        bg: '#E3120B', color: '#fff' },
  'South China Morning Post': { short: 'SCMP', bg: '#003366', color: '#fff' },
  'Caixin Global': { short: 'Caixin',      bg: '#0066CC', color: '#fff' },
  'Nikkei Asia': { short: 'Nikkei',        bg: '#D82B2B', color: '#fff' },
  'MarketWatch': { short: 'MW',            bg: '#16C784', color: '#fff' },
  'Barron\'s': { short: "Barron's",        bg: '#1D1D1B', color: '#E8C96A' },
  'Seeking Alpha': { short: 'SA',          bg: '#3C7ABF', color: '#fff' },
  'Yahoo Finance': { short: 'Yahoo',       bg: '#6001D2', color: '#fff' },
};

// Build Google News RSS URL
function gnRSS(query) {
  const encoded = encodeURIComponent(query);
  return `https://news.google.com/rss/search?q=${encoded}&hl=en-US&gl=US&ceid=US:en`;
}

// Parse Google News RSS XML → article array
function parseGoogleNewsRSS(xmlText, meta) {
  const items = [];
  const itemRegex = /<item>([\s\S]*?)<\/item>/g;
  let m;
  while ((m = itemRegex.exec(xmlText)) !== null) {
    const block = m[1];

    // Extract text content, stripping CDATA wrappers
    const get = (tag) => {
      const r = block.match(
        new RegExp(`<${tag}(?:[^>]*)>(?:<!\\[CDATA\\[)?([\\s\\S]*?)(?:\\]\\]>)?<\\/${tag}>`)
      );
      return r ? r[1].replace(/<[^>]+>/g, '').trim() : '';
    };

    // Google News <source url="...">Publisher Name</source>
    const sourceMatch = block.match(/<source[^>]*>([^<]+)<\/source>/);
    const publisher = sourceMatch ? sourceMatch[1].trim() : 'Unknown';
    const sourceMeta = SOURCE_META[publisher] || { short: publisher.split(' ')[0], bg: '#3A6FD8', color: '#fff' };

    // Title sometimes appended with " - Publisher"
    let title = get('title');
    title = title.replace(new RegExp(`\\s*-\\s*${publisher.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*$`), '').trim();

    const pubDate = get('pubDate');
    const link = get('link') || block.match(/https?:\/\/[^\s<"]+/)?.[0] || '';

    if (!title || title.length < 10) continue;

    const id = `${meta.ticker || meta.tag}-${Buffer.from(title.slice(0, 40)).toString('base64').slice(0, 16)}`;

    items.push({
      id,
      title,
      summary: '',                // Google News doesn't provide summaries
      source: publisher,
      source_meta: sourceMeta,
      url: link,
      published_at: pubDate ? new Date(pubDate).toISOString() : new Date().toISOString(),
      ticker: meta.ticker || null,
      tag: meta.tag || null,
      label: meta.label,
      category: meta.category || 'PORTFOLIO',
    });
  }
  return items;
}

// Fetch one feed with 5s timeout
async function fetchFeed(feedMeta) {
  const url = gnRSS(feedMeta.query);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const res = await fetch(url, {
      signal: controller.signal,
      headers: { 'User-Agent': 'Mozilla/5.0 (compatible; MarketIntelligenceBot/1.0)' },
    });
    clearTimeout(timeout);
    if (!res.ok) return [];
    const xml = await res.text();
    return parseGoogleNewsRSS(xml, feedMeta);
  } catch {
    clearTimeout(timeout);
    return [];
  }
}

// Deduplicate by normalised title prefix
function dedupe(articles) {
  const seen = new Set();
  return articles.filter(a => {
    const key = a.title.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 50);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });
  res.setHeader('Cache-Control', 'public, max-age=120, stale-while-revalidate=60');

  try {
    const macroFeeds   = MACRO_FEEDS.map(f => ({ ...f, category: 'MACRO' }));
    const portfolioFeeds = PORTFOLIO_FEEDS.map(f => ({ ...f, category: 'PORTFOLIO' }));

    // Fetch all feeds in parallel
    const [macroResults, portfolioResults] = await Promise.all([
      Promise.allSettled(macroFeeds.map(fetchFeed)),
      Promise.allSettled(portfolioFeeds.map(fetchFeed)),
    ]);

    const macroAll     = macroResults.flatMap(r => r.status === 'fulfilled' ? r.value : []);
    const portfolioAll = portfolioResults.flatMap(r => r.status === 'fulfilled' ? r.value : []);

    const sortByDate = arr => [...arr].sort((a, b) => new Date(b.published_at) - new Date(a.published_at));

    const macro     = sortByDate(dedupe(macroAll)).slice(0, 30);
    const portfolio = sortByDate(dedupe(portfolioAll)).slice(0, 30);

    return res.status(200).json({
      macro,
      portfolio,
      // Flat combined for backwards compat
      articles: [...macro, ...portfolio],
      fetched_at: new Date().toISOString(),
      macro_count: macro.length,
      portfolio_count: portfolio.length,
    });
  } catch (err) {
    console.error('news.js error:', err);
    return res.status(500).json({ error: err.message });
  }
}
