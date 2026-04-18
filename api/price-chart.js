// api/price-chart.js — Real-time OHLCV chart data via Yahoo Finance v8
//
// GET /api/price-chart?ticker=0700.HK&range=1mo
//
// range:    1d | 5d | 1mo | 3mo | 6mo | 1y
// Returns:  { ticker, name, currency, current, change_pct, market_state, data: [...] }
//
// Runs on Vercel serverless (Node 18+).  The browser User-Agent bypasses the
// rate-limit Yahoo Finance applies to automated requests from cloud IPs.

const YF_HEADERS = {
  'User-Agent': (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ' +
    'AppleWebKit/537.36 (KHTML, like Gecko) ' +
    'Chrome/124.0.0.0 Safari/537.36'
  ),
  'Accept': 'application/json',
  'Accept-Language': 'en-US,en;q=0.9',
  'Referer': 'https://finance.yahoo.com/',
};

// Auto-select a sensible interval for each range
const INTERVAL_MAP = {
  '1d':  '5m',
  '5d':  '30m',
  '1mo': '1d',
  '3mo': '1d',
  '6mo': '1d',
  '1y':  '1wk',
};

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin',  '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'GET')    return res.status(405).json({ error: 'GET only' });

  const { ticker, range = '1mo' } = req.query;
  if (!ticker?.trim()) return res.status(400).json({ error: 'ticker is required' });

  const interval = INTERVAL_MAP[range] || '1d';
  const enc      = encodeURIComponent(ticker.trim());

  const urls = [
    `https://query1.finance.yahoo.com/v8/finance/chart/${enc}?interval=${interval}&range=${range}`,
    `https://query2.finance.yahoo.com/v8/finance/chart/${enc}?interval=${interval}&range=${range}`,
  ];

  for (const url of urls) {
    try {
      const resp = await fetch(url, {
        headers: YF_HEADERS,
        signal:  AbortSignal.timeout(12000),
      });

      if (!resp.ok) {
        console.error(`[price-chart] ${url} → ${resp.status}`);
        continue;
      }

      const body   = await resp.json();
      const result = body?.chart?.result?.[0];
      if (!result) continue;

      const meta    = result.meta  || {};
      const ts      = result.timestamp || [];
      const quote   = (result.indicators?.quote || [{}])[0];
      const opens   = quote.open   || [];
      const highs   = quote.high   || [];
      const lows    = quote.low    || [];
      const closes  = quote.close  || [];
      const volumes = quote.volume || [];

      // Build OHLCV array — filter out null candles
      const chartData = ts.reduce((acc, t, i) => {
        const c = closes[i];
        if (c == null) return acc;
        acc.push({
          time:   t * 1000,  // epoch ms — recharts XAxis can use this directly
          open:   opens[i]   != null ? +opens[i].toFixed(4)   : +c.toFixed(4),
          high:   highs[i]   != null ? +highs[i].toFixed(4)   : +c.toFixed(4),
          low:    lows[i]    != null ? +lows[i].toFixed(4)    : +c.toFixed(4),
          close:  +c.toFixed(4),
          volume: volumes[i] != null ? Math.round(volumes[i]) : 0,
        });
        return acc;
      }, []);

      if (!chartData.length) continue;

      const lastClose  = chartData.at(-1).close;
      const prevClose  = meta.chartPreviousClose || meta.previousClose || lastClose;
      const changePct  = prevClose
        ? +((lastClose - prevClose) / prevClose * 100).toFixed(2)
        : null;

      // Cache for 60 s on CDN (Vercel edge) — appropriate for near-real-time
      res.setHeader('Cache-Control', 'public, s-maxage=60, stale-while-revalidate=30');

      return res.status(200).json({
        success:      true,
        ticker:       meta.symbol     || ticker,
        name:         meta.longName   || meta.shortName || ticker,
        currency:     meta.currency   || '',
        exchange:     meta.exchangeName || '',
        range,
        interval,
        current:      meta.regularMarketPrice ?? lastClose,
        prev_close:   prevClose,
        change_pct:   changePct,
        day_high:     meta.regularMarketDayHigh  ?? null,
        day_low:      meta.regularMarketDayLow   ?? null,
        volume:       meta.regularMarketVolume   ?? null,
        market_state: meta.marketState || 'CLOSED', // REGULAR | PRE | POST | CLOSED
        data:         chartData,
        fetched_at:   new Date().toISOString(),
      });
    } catch (err) {
      console.error(`[price-chart] ${url}: ${err.message}`);
    }
  }

  return res.status(502).json({
    error: `Failed to fetch price data for "${ticker}". ` +
           `Yahoo Finance may be temporarily unavailable.`,
  });
}
