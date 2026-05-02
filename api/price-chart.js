// api/price-chart.js — Real-time OHLCV chart data
//
// 2026-05-02 v2 update (Junyan Phase 2 K-line universe):
//   • A-share tickers (.SZ / .SH) → Tushare 6000-tier paid HTTP API
//     (Yahoo rate-limits Vercel cloud IPs aggressively for A-shares,
//      breaking K-line rendering for any A-share ticker)
//   • HK / US tickers → Yahoo Finance v8 (existing logic preserved)
//   • Tushare branch falls through to Yahoo on failure (defense in depth)
//
// GET /api/price-chart?ticker=300308.SZ&range=1mo
//
// range:    1d | 5d | 1mo | 3mo | 6mo | 1y
// Returns:  { success, ticker, name, currency, current, change_pct,
//             market_state, data: [...], source }
//
// Vercel env vars required:
//   TUSHARE_TOKEN — for A-share data (must be set in Vercel project env;
//                    fallback to Yahoo if missing)
//
// Runs on Vercel serverless (Node 18+). The browser User-Agent bypasses
// the rate-limit Yahoo Finance applies to automated requests from cloud IPs.

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

// Calendar-days lookback per range (for Tushare date math; daily candles only)
const TUSHARE_DAYS_MAP = {
  '1d':   5,    // last 5 calendar days → ~3 trading sessions (covers weekends)
  '5d':   10,   // last 10 calendar days → ~7 sessions
  '1mo':  35,   // last 35 calendar days → ~22-23 sessions
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
  // Convert to Tushare's HK format: 5-digit zero-padded + .HK
  // '700.HK' / '0700.HK' / '00700.HK' → '00700.HK'
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
// Tushare branch (A-share)
// ────────────────────────────────────────────────────────────────────────

async function fetchTushareDaily(ticker, range) {
  const token = process.env.TUSHARE_TOKEN;
  if (!token) {
    console.warn('[price-chart] TUSHARE_TOKEN not set in Vercel env — falling back to Yahoo for', ticker);
    return null;
  }

  const daysBack = TUSHARE_DAYS_MAP[range] || 35;
  const now = new Date();
  const startDate = new Date(now.getTime() - daysBack * 86400000);

  const body = {
    api_name: 'daily',
    token,
    params: {
      ts_code: ticker.trim().toUpperCase(),
      start_date: formatYYYYMMDD(startDate),
      end_date: formatYYYYMMDD(now),
    },
    fields: 'trade_date,open,high,low,close,vol,amount,pct_chg',
  };

  try {
    const resp = await fetch('https://api.tushare.pro', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(12000),
    });

    if (!resp.ok) {
      console.error(`[price-chart-tushare] HTTP ${resp.status} for ${ticker}`);
      return null;
    }

    const json = await resp.json();
    if (json.code !== 0) {
      console.error(`[price-chart-tushare] API error for ${ticker}: ${json.msg}`);
      return null;
    }

    const fields = json.data?.fields || [];
    const items  = json.data?.items  || [];
    if (!items.length) return null;

    const idxOf = (name) => fields.indexOf(name);
    const iDate  = idxOf('trade_date');
    const iOpen  = idxOf('open');
    const iHigh  = idxOf('high');
    const iLow   = idxOf('low');
    const iClose = idxOf('close');
    const iVol   = idxOf('vol');

    // Transform to chartData (sort ascending by date — Tushare returns desc)
    const chartData = items
      .map(row => {
        const dateStr = String(row[iDate]); // YYYYMMDD
        if (!/^\d{8}$/.test(dateStr)) return null;
        const t = Date.UTC(
          +dateStr.slice(0, 4),
          +dateStr.slice(4, 6) - 1,
          +dateStr.slice(6, 8),
          7, 0, 0  // 15:00 CST = 07:00 UTC, A-share market close convention
        );
        const open  = row[iOpen]  != null ? +Number(row[iOpen]).toFixed(4)  : null;
        const high  = row[iHigh]  != null ? +Number(row[iHigh]).toFixed(4)  : null;
        const low   = row[iLow]   != null ? +Number(row[iLow]).toFixed(4)   : null;
        const close = row[iClose] != null ? +Number(row[iClose]).toFixed(4) : null;
        if (close == null) return null;
        // Tushare vol is in 手 (lot of 100 shares). Convert to actual shares.
        const volRaw = row[iVol] != null ? Number(row[iVol]) : 0;
        return {
          time:   t,
          open:   open  ?? close,
          high:   high  ?? close,
          low:    low   ?? close,
          close,
          volume: Math.round(volRaw * 100),
        };
      })
      .filter(Boolean)
      .sort((a, b) => a.time - b.time);

    if (!chartData.length) return null;

    const last      = chartData[chartData.length - 1];
    const prev      = chartData.length > 1 ? chartData[chartData.length - 2] : last;
    const prevClose = prev.close;
    const changePct = prevClose
      ? +((last.close - prevClose) / prevClose * 100).toFixed(2)
      : null;

    return {
      success:      true,
      ticker:       ticker.toUpperCase(),
      name:         ticker.toUpperCase(),  // Tushare daily endpoint doesn't return name; UI gets from universe
      currency:     'CNY',
      exchange:     ticker.endsWith('.SH') || ticker.endsWith('.sh') ? 'SSE' : 'SZSE',
      range,
      interval:     '1d',  // Tushare daily only — no intraday at 6000 tier
      current:      last.close,
      prev_close:   prevClose,
      change_pct:   changePct,
      day_high:     last.high,
      day_low:      last.low,
      volume:       last.volume,
      market_state: 'CLOSED',  // Tushare doesn't expose live market state
      data:         chartData,
      source:       'tushare-6000',
      fetched_at:   new Date().toISOString(),
    };
  } catch (err) {
    console.error(`[price-chart-tushare] ${ticker}: ${err.message}`);
    return null;
  }
}

// ────────────────────────────────────────────────────────────────────────
// Tushare branch (HK via hk_daily — 6000-tier covers HK 低频行情)
// ────────────────────────────────────────────────────────────────────────

async function fetchTushareHK(ticker, range) {
  const token = process.env.TUSHARE_TOKEN;
  if (!token) {
    console.warn('[price-chart] TUSHARE_TOKEN not set — falling back to Yahoo for HK', ticker);
    return null;
  }

  const tsCode = toTushareHK(ticker);  // e.g. '700.HK' → '00700.HK'
  const daysBack = TUSHARE_DAYS_MAP[range] || 35;
  const now = new Date();
  const startDate = new Date(now.getTime() - daysBack * 86400000);

  const body = {
    api_name: 'hk_daily',
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
      console.error(`[price-chart-tushare-hk] HTTP ${resp.status} for ${tsCode}`);
      return null;
    }

    const json = await resp.json();
    if (json.code !== 0) {
      console.error(`[price-chart-tushare-hk] API error for ${tsCode}: ${json.msg}`);
      return null;
    }

    const fields = json.data?.fields || [];
    const items  = json.data?.items  || [];
    if (!items.length) return null;

    const idxOf = (name) => fields.indexOf(name);
    const iDate  = idxOf('trade_date');
    const iOpen  = idxOf('open');
    const iHigh  = idxOf('high');
    const iLow   = idxOf('low');
    const iClose = idxOf('close');
    const iVol   = idxOf('vol');

    const chartData = items
      .map(row => {
        const dateStr = String(row[iDate]);
        if (!/^\d{8}$/.test(dateStr)) return null;
        // HK market closes ~16:00 HKT = 08:00 UTC
        const t = Date.UTC(
          +dateStr.slice(0, 4),
          +dateStr.slice(4, 6) - 1,
          +dateStr.slice(6, 8),
          8, 0, 0
        );
        const open  = row[iOpen]  != null ? +Number(row[iOpen]).toFixed(4)  : null;
        const high  = row[iHigh]  != null ? +Number(row[iHigh]).toFixed(4)  : null;
        const low   = row[iLow]   != null ? +Number(row[iLow]).toFixed(4)   : null;
        const close = row[iClose] != null ? +Number(row[iClose]).toFixed(4) : null;
        if (close == null) return null;
        // HK Tushare vol is in shares directly (not 手 like A-share)
        const volRaw = row[iVol] != null ? Number(row[iVol]) : 0;
        return {
          time:   t,
          open:   open  ?? close,
          high:   high  ?? close,
          low:    low   ?? close,
          close,
          volume: Math.round(volRaw),
        };
      })
      .filter(Boolean)
      .sort((a, b) => a.time - b.time);

    if (!chartData.length) return null;

    const last      = chartData[chartData.length - 1];
    const prev      = chartData.length > 1 ? chartData[chartData.length - 2] : last;
    const prevClose = prev.close;
    const changePct = prevClose
      ? +((last.close - prevClose) / prevClose * 100).toFixed(2)
      : null;

    return {
      success:      true,
      ticker:       tsCode,
      name:         tsCode,
      currency:     'HKD',
      exchange:     'HKEx',
      range,
      interval:     '1d',
      current:      last.close,
      prev_close:   prevClose,
      change_pct:   changePct,
      day_high:     last.high,
      day_low:      last.low,
      volume:       last.volume,
      market_state: 'CLOSED',
      data:         chartData,
      source:       'tushare-6000-hk',
      fetched_at:   new Date().toISOString(),
    };
  } catch (err) {
    console.error(`[price-chart-tushare-hk] ${tsCode}: ${err.message}`);
    return null;
  }
}

// ────────────────────────────────────────────────────────────────────────
// Yahoo Finance branch (US / HK fallback)
// ────────────────────────────────────────────────────────────────────────

async function fetchYahooChart(ticker, range) {
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
        console.error(`[price-chart-yahoo] ${url} → ${resp.status}`);
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
      const changePct = prevClose
        ? +((lastClose - prevClose) / prevClose * 100).toFixed(2)
        : null;

      return {
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
        market_state: meta.marketState || 'CLOSED',
        data:         chartData,
        source:       'yahoo-v8',
        fetched_at:   new Date().toISOString(),
      };
    } catch (err) {
      console.error(`[price-chart-yahoo] ${url}: ${err.message}`);
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

  // ── Branch 1: A-share via Tushare 6000 ─────────────────────────────────
  if (isAShare(ticker)) {
    const tushareResult = await fetchTushareDaily(ticker, range);
    if (tushareResult) {
      res.setHeader('Cache-Control', 'public, s-maxage=43200, stale-while-revalidate=86400');
      return res.status(200).json(tushareResult);
    }
    console.warn('[price-chart] Tushare A failed for', ticker, '— falling back to Yahoo');
  }

  // ── Branch 2: HK via Tushare 6000 hk_daily (Yahoo rate-limits HK from
  //              Vercel cloud IPs same as A-share) ────────────────────────
  if (isHK(ticker)) {
    const tushareHKResult = await fetchTushareHK(ticker, range);
    if (tushareHKResult) {
      res.setHeader('Cache-Control', 'public, s-maxage=43200, stale-while-revalidate=86400');
      return res.status(200).json(tushareHKResult);
    }
    console.warn('[price-chart] Tushare HK failed for', ticker, '— falling back to Yahoo');
  }

  // ── Branch 3: US / fallback for failed A-share + HK via Yahoo ──────────
  const yahooResult = await fetchYahooChart(ticker, range);
  if (yahooResult) {
    res.setHeader('Cache-Control', 'public, s-maxage=60, stale-while-revalidate=30');
    return res.status(200).json(yahooResult);
  }

  let errMsg = `Failed to fetch price data for "${ticker}". `;
  if (isAShare(ticker))      errMsg += 'Tushare A + Yahoo both failed.';
  else if (isHK(ticker))     errMsg += 'Tushare HK + Yahoo both failed.';
  else                       errMsg += 'Yahoo Finance unavailable.';
  return res.status(502).json({ error: errMsg });
}
