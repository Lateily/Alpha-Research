// api/price-chart.js — OHLCV chart data via Tushare paid API + US fallback
//
// 2026-05-02 v5: multi-timeframe support (interval param: 1m/5m/15m/30m/60m + 1d/1w/1mo)
//   • A + HK route through Tushare paid API; 6000-tier covers daily, 15000-tier unlocks intraday/extended candles
//   • US branch keeps Yahoo Finance v8 fallback because Tushare us_daily 6000-tier is limited to 5 req/day
//   • Cleaner code, single point of debugging, paid SLA >99.9% for Tushare-covered markets
//   • Multi-timeframe schema is forward-compatible: tier-locked data returns success=true + data=[]
//
// GET /api/price-chart?ticker=300308.SZ&range=1mo&interval=1d
// GET /api/price-chart?ticker=700.HK&interval=5m
// GET /api/price-chart?ticker=NVDA&range=1y&interval=1w
//
// range:    1d | 5d | 1mo | 3mo | 6mo | 1y  (lookback duration)
// interval: 1m | 5m | 15m | 30m | 60m | 1d | 1w | 1mo
// Returns:  { success, ticker, name, currency, current, change_pct,
//             market_state, data: [...], source }
//
// Vercel env vars required:
//   TUSHARE_TOKEN — Tushare paid token (set in project env)

// Calendar-days lookback per range for legacy daily candle callers.
const TUSHARE_DAYS_MAP = {
  '1d':   5,    // last 5 calendar days → ~3 trading sessions (covers weekends)
  '5d':   10,
  '1mo':  35,
  '3mo':  95,
  '6mo':  185,
  '1y':   370,
};

const ALLOWED_INTERVALS = ['1m', '5m', '15m', '30m', '60m', '1d', '1w', '1mo'];

const INTERVAL_LOOKBACK_DAYS_MAP = {
  '1m':   1,
  '5m':   5,
  '15m':  15,
  '30m':  30,
  '60m':  60,
  '1d':   35,
  '1w':   365,
  '1mo':  1825,
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

function firstQueryValue(value) {
  return Array.isArray(value) ? value[0] : value;
}

function normalizeInterval(value) {
  return String(value || '1d').trim().toLowerCase();
}

function isAllowedInterval(interval) {
  return ALLOWED_INTERVALS.includes(interval);
}

function isMinuteInterval(interval) {
  return intervalToTushareFreq(interval) != null;
}

function intervalToTushareFreq(interval) {
  return {
    '1m':  '1min',
    '5m':  '5min',
    '15m': '15min',
    '30m': '30min',
    '60m': '60min',
  }[interval] || null;
}

function tushareApiNameFor(market, interval) {
  if (market === 'A') {
    if (interval === '1d')  return 'daily';
    if (interval === '1w')  return 'weekly';
    if (interval === '1mo') return 'monthly';
    if (isMinuteInterval(interval)) return 'stk_mins';
  }

  if (market === 'HK') {
    if (interval === '1d')  return 'hk_daily';
    if (interval === '1w')  return 'hk_weekly';
    if (interval === '1mo') return 'hk_monthly';
    if (isMinuteInterval(interval)) return 'hk_mins';
  }

  return null;
}

function tushareLookbackDays(range, interval) {
  if (range && interval === '1d') return TUSHARE_DAYS_MAP[range] || 35;
  return INTERVAL_LOOKBACK_DAYS_MAP[interval] || 35;
}

function isTierLockedMsg(msg) {
  return /权限|permission|tier/i.test(String(msg || ''));
}

function marketMetaFor(market, ticker) {
  if (market === 'A') {
    const tsCode = ticker.trim().toUpperCase();
    return {
      currency: 'CNY',
      exchange: tsCode.endsWith('.SH') ? 'SSE' : 'SZSE',
    };
  }
  if (market === 'HK') return { currency: 'HKD', exchange: 'HKEx' };
  if (market === 'US') return { currency: 'USD', exchange: 'NYSE/NASDAQ' };
  return { currency: 'USD', exchange: 'UNKNOWN' };
}

function parseTushareTradeTime(value) {
  const raw = String(value || '').trim();
  const match = raw.match(/^(\d{4})[-/]?(\d{2})[-/]?(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (!match) return null;
  const [, y, m, d, hh, mm, ss = '0'] = match;
  return Date.UTC(+y, +m - 1, +d, +hh, +mm, +ss);
}

// ────────────────────────────────────────────────────────────────────────
// Tushare HTTP API call (shared by A / HK / US branches)
// ────────────────────────────────────────────────────────────────────────

async function callTushare(apiName, tsCode, range, interval = '1d', freq = null) {
  const token = process.env.TUSHARE_TOKEN;
  if (!token) {
    console.error(`[price-chart] TUSHARE_TOKEN not set in Vercel env`);
    return { error: 'tushare_token_missing' };
  }

  const daysBack = tushareLookbackDays(range, interval);
  const now = new Date();
  const startDate = new Date(now.getTime() - daysBack * 86400000);
  const params = {
    ts_code: tsCode,
    start_date: formatYYYYMMDD(startDate),
    end_date: formatYYYYMMDD(now),
  };
  if (freq) params.freq = freq;

  const body = {
    api_name: apiName,
    token,
    params,
    fields: freq
      ? 'trade_time,open,high,low,close,vol,amount'
      : 'trade_date,open,high,low,close,vol,amount',
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
      const msg = String(json.msg || '');
      const isRateLimit = msg.includes('频率超限') || /rate/i.test(msg);
      console.error(`[price-chart-tushare] ${apiName} code=${json.code} msg="${json.msg}" for ${tsCode}`);
      if (isTierLockedMsg(msg)) return { error: 'tier_locked', msg, code: json.code };
      return { error: isRateLimit ? 'rate_limit' : 'tushare_error', msg, code: json.code };
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
  const iTradeTime = idxOf('trade_time');
  const iDate  = idxOf('trade_date');
  const iOpen  = idxOf('open');
  const iHigh  = idxOf('high');
  const iLow   = idxOf('low');
  const iClose = idxOf('close');
  const iVol   = idxOf('vol');
  const hasTradeTime = iTradeTime >= 0;
  const numAt = (row, idx) => (idx >= 0 && row[idx] != null ? Number(row[idx]) : null);
  const round4 = (value) => (value != null && Number.isFinite(value) ? +value.toFixed(4) : null);

  return items
    .map(row => {
      let t;
      if (hasTradeTime) {
        t = parseTushareTradeTime(row[iTradeTime]);
      } else {
        const dateStr = String(row[iDate]);
        if (!/^\d{8}$/.test(dateStr)) return null;
        t = Date.UTC(
          +dateStr.slice(0, 4),
          +dateStr.slice(4, 6) - 1,
          +dateStr.slice(6, 8),
          marketCloseUTCHour, 0, 0
        );
      }
      if (t == null) return null;

      const open  = round4(numAt(row, iOpen));
      const high  = round4(numAt(row, iHigh));
      const low   = round4(numAt(row, iLow));
      const close = round4(numAt(row, iClose));
      if (close == null) return null;
      const volRaw = numAt(row, iVol) ?? 0;
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

function buildResponse(chartData, ticker, currency, exchange, range, interval, source) {
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
    range:        range ?? null,
    interval,
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

function emptyCompatibleResponse(ticker, range, interval, market, status, extras = {}) {
  const meta = marketMetaFor(market, ticker);
  return {
    success:      true,
    ticker,
    name:         ticker,
    currency:     meta.currency,
    exchange:     meta.exchange,
    range:        range ?? null,
    interval,
    current:      null,
    prev_close:   null,
    change_pct:   null,
    day_high:     null,
    day_low:      null,
    volume:       null,
    market_state: 'UNKNOWN',
    data:         [],
    source:       extras.source || null,
    _status:      status,
    fetched_at:   new Date().toISOString(),
    ...extras,
  };
}

function tierLockedResponse(ticker, range, interval, market, attemptedEndpoint, errMsg) {
  return emptyCompatibleResponse(ticker, range, interval, market, 'tier_locked', {
    source:              `tushare-${interval}-${market.toLowerCase()}`,
    _need_tier:          15000,
    _attempted_endpoint: attemptedEndpoint,
    _tushare_msg:        errMsg || null,
  });
}

function unsupportedIntervalResponse(ticker, range, interval, market) {
  return emptyCompatibleResponse(ticker, range, interval, market, 'unsupported_interval', {
    _allowed_intervals: ALLOWED_INTERVALS,
  });
}

// ────────────────────────────────────────────────────────────────────────
// Per-market fetchers
// ────────────────────────────────────────────────────────────────────────

async function fetchA(ticker, range, interval) {
  const tsCode = ticker.trim().toUpperCase();
  const apiName = tushareApiNameFor('A', interval);
  if (!apiName) return unsupportedIntervalResponse(tsCode, range, interval, 'A');

  const freq = intervalToTushareFreq(interval);
  const r = await callTushare(apiName, tsCode, range, interval, freq);
  if (r.error === 'tier_locked') {
    return tierLockedResponse(tsCode, range, interval, 'A', apiName, r.msg);
  }
  if (!r.ok) return null;
  // A-share daily/weekly/monthly vol is in 手 (lot of 100 shares); minute vol is usually shares.
  const volMultiplier = ['1d', '1w', '1mo'].includes(interval) ? 100 : 1;
  const chartData = transformToChartData(r.fields, r.items, 7, volMultiplier);
  // 15:00 CST market close = 07:00 UTC
  return buildResponse(
    chartData, tsCode, 'CNY',
    tsCode.endsWith('.SH') ? 'SSE' : 'SZSE',
    range, interval, `tushare-${interval}-a`
  );
}

async function fetchHK(ticker, range, interval) {
  const tsCode = toTushareHK(ticker);
  const apiName = tushareApiNameFor('HK', interval);
  if (!apiName) return unsupportedIntervalResponse(tsCode, range, interval, 'HK');

  const freq = intervalToTushareFreq(interval);
  const r = await callTushare(apiName, tsCode, range, interval, freq);
  if (r.error === 'tier_locked') {
    return tierLockedResponse(tsCode, range, interval, 'HK', apiName, r.msg);
  }
  if (!r.ok) return null;
  // HK Tushare vol is in shares directly (no 手 conversion)
  const chartData = transformToChartData(r.fields, r.items, 8, 1);
  // 16:00 HKT market close = 08:00 UTC
  return buildResponse(chartData, tsCode, 'HKD', 'HKEx', range, interval, `tushare-${interval}-hk`);
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
  '1m':  '1m',
  '5m':  '5m',
  '15m': '15m',
  '30m': '30m',
  '60m': '60m',
  '1d':  '1d',
  '1w':  '1wk',
  '1mo': '1mo',
};

const YF_RANGE_DAYS_MAP = {
  '1d':  1,
  '5d':  5,
  '1mo': 30,
  '3mo': 90,
  '6mo': 180,
  '1y':  365,
};

const YF_MAX_LOOKBACK_DAYS = {
  '1m':  7,
  '5m':  60,
  '15m': 60,
  '30m': 60,
  '60m': 60,
  '1d':  3650,
  '1w':  3650,
  '1mo': 3650,
};

function yfinanceRangeFor(range, interval) {
  const requestedDays = range
    ? (YF_RANGE_DAYS_MAP[range] || INTERVAL_LOOKBACK_DAYS_MAP[interval] || 30)
    : (INTERVAL_LOOKBACK_DAYS_MAP[interval] || 30);
  const cappedDays = Math.min(requestedDays, YF_MAX_LOOKBACK_DAYS[interval] || requestedDays);

  if (cappedDays >= 1825) return '5y';
  if (cappedDays >= 730) return '2y';
  if (cappedDays >= 365) return '1y';
  if (cappedDays >= 180) return '6mo';
  if (cappedDays >= 90)  return '3mo';
  if (cappedDays >= 30)  return '1mo';
  if (cappedDays >= 5)   return '5d';
  return '1d';
}

async function fetchUS(ticker, range, interval) {
  const tk = ticker.trim().toUpperCase();
  const yfInterval = YF_INTERVAL_MAP[interval];
  if (!yfInterval) return unsupportedIntervalResponse(tk, range, interval, 'US');
  const yfRange = yfinanceRangeFor(range, interval);
  const enc = encodeURIComponent(tk);
  const urls = [
    `https://query1.finance.yahoo.com/v8/finance/chart/${enc}?interval=${yfInterval}&range=${yfRange}`,
    `https://query2.finance.yahoo.com/v8/finance/chart/${enc}?interval=${yfInterval}&range=${yfRange}`,
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
        range:        range ?? null,
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

  const ticker = firstQueryValue(req.query.ticker);
  const rawRange = firstQueryValue(req.query.range);
  const interval = normalizeInterval(firstQueryValue(req.query.interval));
  const range = rawRange || (interval === '1d' ? '1mo' : undefined);
  if (!ticker?.trim()) return res.status(400).json({ error: 'ticker is required' });
  if (!isAllowedInterval(interval)) {
    return res.status(400).json({
      error: `unsupported interval "${interval}". Allowed intervals: ${ALLOWED_INTERVALS.join(', ')}`,
    });
  }

  let result = null;
  let market;
  if (isAShare(ticker)) {
    market = 'A';
    result = await fetchA(ticker, range, interval);
  } else if (isHK(ticker)) {
    market = 'HK';
    result = await fetchHK(ticker, range, interval);
  } else {
    market = 'US';
    result = await fetchUS(ticker, range, interval);
  }

  if (result) {
    // Minute candles refresh quickly; daily/weekly/monthly retain the 12-hour edge cache.
    const maxAge = isMinuteInterval(interval) ? 60 : 43200;
    res.setHeader('Cache-Control', `public, s-maxage=${maxAge}, stale-while-revalidate=86400`);
    return res.status(200).json(result);
  }

  return res.status(502).json({
    error: `Failed to fetch price data for "${ticker}" (market=${market}). ` +
           `Tushare 6000-tier API failed. Check TUSHARE_TOKEN env var or rate limits.`,
  });
}
