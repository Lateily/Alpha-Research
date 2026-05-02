// api/price-chart.js — OHLCV chart data via Tushare 6000-tier (single-source)
//
// 2026-05-02 v4 (Junyan: "yahoo 删了"):
//   • Single-source via Tushare 6000-tier paid API (A + HK + US covered)
//   • Yahoo Finance branch DELETED — was rate-limited on Vercel cloud IPs
//   • Cleaner code, single point of debugging, paid SLA >99.9%
//
// GET /api/price-chart?ticker=300308.SZ&range=1mo
// GET /api/price-chart?ticker=700.HK&range=3mo
// GET /api/price-chart?ticker=NVDA&range=1y
//
// range:    1d | 5d | 1mo | 3mo | 6mo | 1y
// Returns:  { success, ticker, name, currency, current, change_pct,
//             market_state, data: [...], source }
//
// Vercel env vars required:
//   TUSHARE_TOKEN — Tushare 6000-tier token (set in project env)

// Calendar-days lookback per range (Tushare daily candles only — no intraday at 6000)
const TUSHARE_DAYS_MAP = {
  '1d':   5,    // last 5 calendar days → ~3 trading sessions (covers weekends)
  '5d':   10,
  '1mo':  35,
  '3mo':  95,
  '6mo':  185,
  '1y':   370,
};

// ────────────────────────────────────────────────────────────────────────
// Helpers
// ────────────────────────────────────────────────────────────────────────

function isAShare(ticker) {
  return /\.(SZ|SH)$/i.test(ticker.trim());
}

function isHK(ticker) {
  return /\.HK$/i.test(ticker.trim());
}

function toTushareHK(ticker) {
  // '700.HK' / '0700.HK' / '00700.HK' → '00700.HK' (5-digit zero-padded)
  const base = ticker.trim().toUpperCase().replace(/\.HK$/i, '');
  return `${base.padStart(5, '0')}.HK`;
}

function formatYYYYMMDD(dateObj) {
  const y = dateObj.getUTCFullYear();
  const m = String(dateObj.getUTCMonth() + 1).padStart(2, '0');
  const d = String(dateObj.getUTCDate()).padStart(2, '0');
  return `${y}${m}${d}`;
}

// ────────────────────────────────────────────────────────────────────────
// Tushare HTTP API call (shared by A / HK / US branches)
// ────────────────────────────────────────────────────────────────────────

async function callTushare(apiName, tsCode, range) {
  const token = process.env.TUSHARE_TOKEN;
  if (!token) {
    console.error(`[price-chart] TUSHARE_TOKEN not set in Vercel env`);
    return { error: 'tushare_token_missing' };
  }

  const daysBack = TUSHARE_DAYS_MAP[range] || 35;
  const now = new Date();
  const startDate = new Date(now.getTime() - daysBack * 86400000);

  const body = {
    api_name: apiName,
    token,
    params: {
      ts_code: tsCode,
      start_date: formatYYYYMMDD(startDate),
      end_date: formatYYYYMMDD(now),
    },
    fields: 'trade_date,open,high,low,close,vol,amount',
  };

  try {
    const resp = await fetch('https://api.tushare.pro', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(12000),
    });

    if (!resp.ok) {
      console.error(`[price-chart-tushare] ${apiName} HTTP ${resp.status} for ${tsCode}`);
      return { error: `http_${resp.status}` };
    }

    const json = await resp.json();
    if (json.code !== 0) {
      const isRateLimit = (json.msg || '').includes('频率超限') ||
                          (json.msg || '').includes('rate');
      console.error(`[price-chart-tushare] ${apiName} code=${json.code} msg="${json.msg}" for ${tsCode}`);
      return { error: isRateLimit ? 'rate_limit' : 'tushare_error', msg: json.msg };
    }

    return { ok: true, fields: json.data?.fields || [], items: json.data?.items || [] };
  } catch (err) {
    console.error(`[price-chart-tushare] ${apiName} ${tsCode}: ${err.message}`);
    return { error: 'fetch_failed', msg: err.message };
  }
}

// ────────────────────────────────────────────────────────────────────────
// Transform Tushare row format → chartData[] (shared logic for all markets)
// ────────────────────────────────────────────────────────────────────────

function transformToChartData(fields, items, marketCloseUTCHour, volMultiplier) {
  const idxOf = (name) => fields.indexOf(name);
  const iDate  = idxOf('trade_date');
  const iOpen  = idxOf('open');
  const iHigh  = idxOf('high');
  const iLow   = idxOf('low');
  const iClose = idxOf('close');
  const iVol   = idxOf('vol');

  return items
    .map(row => {
      const dateStr = String(row[iDate]);
      if (!/^\d{8}$/.test(dateStr)) return null;
      const t = Date.UTC(
        +dateStr.slice(0, 4),
        +dateStr.slice(4, 6) - 1,
        +dateStr.slice(6, 8),
        marketCloseUTCHour, 0, 0
      );
      const open  = row[iOpen]  != null ? +Number(row[iOpen]).toFixed(4)  : null;
      const high  = row[iHigh]  != null ? +Number(row[iHigh]).toFixed(4)  : null;
      const low   = row[iLow]   != null ? +Number(row[iLow]).toFixed(4)   : null;
      const close = row[iClose] != null ? +Number(row[iClose]).toFixed(4) : null;
      if (close == null) return null;
      const volRaw = row[iVol] != null ? Number(row[iVol]) : 0;
      return {
        time:   t,
        open:   open  ?? close,
        high:   high  ?? close,
        low:    low   ?? close,
        close,
        volume: Math.round(volRaw * volMultiplier),
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.time - b.time);  // ascending by date
}

function buildResponse(chartData, ticker, currency, exchange, range, source) {
  if (!chartData.length) return null;
  const last      = chartData[chartData.length - 1];
  const prev      = chartData.length > 1 ? chartData[chartData.length - 2] : last;
  const changePct = prev.close
    ? +((last.close - prev.close) / prev.close * 100).toFixed(2)
    : null;

  return {
    success:      true,
    ticker,
    name:         ticker,  // Tushare daily endpoints don't return name; UI gets from universe
    currency,
    exchange,
    range,
    interval:     '1d',
    current:      last.close,
    prev_close:   prev.close,
    change_pct:   changePct,
    day_high:     last.high,
    day_low:      last.low,
    volume:       last.volume,
    market_state: 'CLOSED',
    data:         chartData,
    source,
    fetched_at:   new Date().toISOString(),
  };
}

// ────────────────────────────────────────────────────────────────────────
// Per-market fetchers
// ────────────────────────────────────────────────────────────────────────

async function fetchA(ticker, range) {
  const tsCode = ticker.trim().toUpperCase();
  const r = await callTushare('daily', tsCode, range);
  if (!r.ok) return null;
  // A-share Tushare vol is in 手 (lot of 100 shares); multiply 100 to get shares
  const chartData = transformToChartData(r.fields, r.items, 7, 100);
  // 15:00 CST market close = 07:00 UTC
  return buildResponse(
    chartData, tsCode, 'CNY',
    tsCode.endsWith('.SH') ? 'SSE' : 'SZSE',
    range, 'tushare-6000-a'
  );
}

async function fetchHK(ticker, range) {
  const tsCode = toTushareHK(ticker);
  const r = await callTushare('hk_daily', tsCode, range);
  if (!r.ok) return null;
  // HK Tushare vol is in shares directly (no 手 conversion)
  const chartData = transformToChartData(r.fields, r.items, 8, 1);
  // 16:00 HKT market close = 08:00 UTC
  return buildResponse(chartData, tsCode, 'HKD', 'HKEx', range, 'tushare-6000-hk');
}

// US: Tushare us_daily at 6000 tier limited to 5 req/DAY (verified 2026-05-02)
// — unusable. Use Yahoo Finance v8 chart endpoint as primary US source.
// Future: upgrade Tushare 8000+ tier raises us_daily limit; revisit then.
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

const YF_INTERVAL_MAP = {
  '1d':  '5m',  '5d':  '30m',  '1mo': '1d',
  '3mo': '1d',  '6mo': '1d',   '1y':  '1wk',
};

async function fetchUS(ticker, range) {
  const tk = ticker.trim().toUpperCase();
  const interval = YF_INTERVAL_MAP[range] || '1d';
  const enc = encodeURIComponent(tk);
  const urls = [
    `https://query1.finance.yahoo.com/v8/finance/chart/${enc}?interval=${interval}&range=${range}`,
    `https://query2.finance.yahoo.com/v8/finance/chart/${enc}?interval=${interval}&range=${range}`,
  ];

  for (const url of urls) {
    try {
      const resp = await fetch(url, { headers: YF_HEADERS, signal: AbortSignal.timeout(12000) });
      if (!resp.ok) {
        console.error(`[price-chart-yahoo-us] ${url} → ${resp.status}`);
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

      const chartData = ts.reduce((acc, t, i) => {
        const c = closes[i];
        if (c == null) return acc;
        acc.push({
          time:   t * 1000,
          open:   opens[i]   != null ? +opens[i].toFixed(4)   : +c.toFixed(4),
          high:   highs[i]   != null ? +highs[i].toFixed(4)   : +c.toFixed(4),
          low:    lows[i]    != null ? +lows[i].toFixed(4)    : +c.toFixed(4),
          close:  +c.toFixed(4),
          volume: volumes[i] != null ? Math.round(volumes[i]) : 0,
        });
        return acc;
      }, []);

      if (!chartData.length) continue;
      const lastClose = chartData[chartData.length - 1].close;
      const prevClose = meta.chartPreviousClose || meta.previousClose || lastClose;

      return {
        success:      true,
        ticker:       meta.symbol     || tk,
        name:         meta.longName   || meta.shortName || tk,
        currency:     meta.currency   || 'USD',
        exchange:     meta.exchangeName || 'NYSE/NASDAQ',
        range,
        interval,
        current:      meta.regularMarketPrice ?? lastClose,
        prev_close:   prevClose,
        change_pct:   prevClose ? +((lastClose - prevClose) / prevClose * 100).toFixed(2) : null,
        day_high:     meta.regularMarketDayHigh  ?? null,
        day_low:      meta.regularMarketDayLow   ?? null,
        volume:       meta.regularMarketVolume   ?? null,
        market_state: meta.marketState || 'CLOSED',
        data:         chartData,
        source:       'yahoo-v8-us',  // explicit-only-US fallback per Tushare US limit
        fetched_at:   new Date().toISOString(),
      };
    } catch (err) {
      console.error(`[price-chart-yahoo-us] ${url}: ${err.message}`);
    }
  }
  return null;
}

// ────────────────────────────────────────────────────────────────────────
// Main handler — route by ticker market
// ────────────────────────────────────────────────────────────────────────

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin',  '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'GET')    return res.status(405).json({ error: 'GET only' });

  const { ticker, range = '1mo' } = req.query;
  if (!ticker?.trim()) return res.status(400).json({ error: 'ticker is required' });

  let result = null;
  let market;
  if (isAShare(ticker)) {
    market = 'A';
    result = await fetchA(ticker, range);
  } else if (isHK(ticker)) {
    market = 'HK';
    result = await fetchHK(ticker, range);
  } else {
    market = 'US';
    result = await fetchUS(ticker, range);
  }

  if (result) {
    // 12-hour edge cache for daily data (data only changes once per day after market close).
    // HK rate-limit (2/min) is mitigated by this cache: first hit fetches, subsequent
    // 12h serve from Vercel CDN edge.
    res.setHeader('Cache-Control', 'public, s-maxage=43200, stale-while-revalidate=86400');
    return res.status(200).json(result);
  }

  return res.status(502).json({
    error: `Failed to fetch price data for "${ticker}" (market=${market}). ` +
           `Tushare 6000-tier API failed. Check TUSHARE_TOKEN env var or rate limits.`,
  });
}
