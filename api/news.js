// api/news.js — Market news aggregator
// Sources: Yahoo Finance RSS (no API key required)
// Covers: 0700.HK, 9999.HK, 6160.HK, BYD, general HK/China market

const RSS_FEEDS = [
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=0700.HK&region=US&lang=en-US', ticker: '700.HK' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=9999.HK&region=US&lang=en-US', ticker: '9999.HK' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=6160.HK&region=US&lang=en-US', ticker: '6160.HK' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=BYDDY&region=US&lang=en-US',   ticker: '002594.SZ' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=ILIGHT&region=US&lang=en-US',  ticker: '300308.SZ' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EHSI&region=US&lang=en-US',  ticker: 'HSI' },
  { url: 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=FXI&region=US&lang=en-US',     ticker: 'CHINA' },
];

// Simple XML → item array parser (no external deps)
function parseRSS(xmlText, sourceTicker) {
  const items = [];
  const itemRegex = /<item>([\s\S]*?)<\/item>/g;
  let m;
  while ((m = itemRegex.exec(xmlText)) !== null) {
    const block = m[1];
    const get = (tag) => {
      const r = block.match(
        new RegExp(`<${tag}[^>]*>(?:<!\\[CDATA\\[)?([\\s\\S]*?)(?:\\]\\]>)?<\\/${tag}>`)
      );
      return r ? r[1].replace(/<[^>]+>/g, '').trim() : '';
    };
    const raw = get('link') || '';
    // Yahoo RSS sometimes puts the URL in a <link> text node before the element — grab the last URL
    const linkMatch = block.match(/https?:\/\/[^\s<"]+/);
    const link = linkMatch ? linkMatch[0] : raw;
    const title = get('title');
    const pubDate = get('pubDate');
    const description = get('description').slice(0, 300);
    if (!title) continue;
    items.push({
      id: `${sourceTicker}-${Buffer.from(title).toString('base64').slice(0, 16)}`,
      title,
      summary: description,
      source: 'Yahoo Finance',
      url: link,
      published_at: pubDate ? new Date(pubDate).toISOString() : new Date().toISOString(),
      ticker: sourceTicker,
      category: sourceTicker === 'HSI' || sourceTicker === 'CHINA' ? 'MACRO' : 'STOCK',
    });
  }
  return items;
}

// Fetch one feed with 4s timeout
async function fetchFeed(feed) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 4000);
  try {
    const res = await fetch(feed.url, {
      signal: controller.signal,
      headers: { 'User-Agent': 'Mozilla/5.0 (compatible; RSS-reader)' },
    });
    clearTimeout(timeout);
    if (!res.ok) return [];
    const xml = await res.text();
    return parseRSS(xml, feed.ticker);
  } catch {
    clearTimeout(timeout);
    return [];
  }
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });

  // Cache header: browsers/CDN can cache for 2 min
  res.setHeader('Cache-Control', 'public, max-age=120, stale-while-revalidate=60');

  try {
    const results = await Promise.allSettled(RSS_FEEDS.map(fetchFeed));
    const all = results.flatMap(r => r.status === 'fulfilled' ? r.value : []);

    // Deduplicate by normalised title
    const seen = new Set();
    const deduped = all.filter(a => {
      const key = a.title.toLowerCase().slice(0, 60);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });

    // Sort newest-first
    deduped.sort((a, b) => new Date(b.published_at) - new Date(a.published_at));

    return res.status(200).json({
      articles: deduped.slice(0, 25),
      fetched_at: new Date().toISOString(),
      sources: RSS_FEEDS.length,
      total_raw: all.length,
    });
  } catch (err) {
    console.error('news.js error:', err);
    return res.status(500).json({ error: err.message });
  }
}
