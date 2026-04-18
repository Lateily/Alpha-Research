// api/capital-flow.js — Real-time northbound/southbound HSGT capital flow
//
// GET /api/capital-flow
//
// Returns: {
//   northbound: { today_net, 5d_net, 20d_net, trend, updated },
//   southbound: { today_net, 5d_net, 20d_net, trend, updated },
//   history: [{ date, north_net, south_net }, ...],   // last 20 trading days
//   source: string,
//   ts: epoch_ms
// }
//
// Data source priority:
//   1. Eastmoney datacenter-web HSGT statistics (primary)
//   2. Eastmoney push2 real-time kamt (today only, fallback)
//
// All amounts in 亿 CNY (100 million CNY).
// Accessible from Vercel — no AKShare, no geo-restriction.

const HEADERS = {
  'User-Agent':
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ' +
    'AppleWebKit/537.36 (KHTML, like Gecko) ' +
    'Chrome/124.0.0.0 Safari/537.36',
  'Referer':        'https://data.eastmoney.com/',
  'Accept':         'application/json, text/plain, */*',
  'Accept-Language':'zh-CN,zh;q=0.9',
};

// ── Eastmoney datacenter: 20-day HSGT history ─────────────────────────────
// Field map: TRADE_DATE, NORTH_MONEY (北向净额亿), SOUTH_MONEY (南向净额亿)
// NORTH_MONEY = net SH + SZ inflow from HK; negative = outflow
async function fetchHistoricalHSGT() {
  const url =
    'https://datacenter-web.eastmoney.com/api/data/v1/get' +
    '?reportName=RPT_MUTUAL_MARKET_HSGT_STATISTIC' +
    '&columns=TRADE_DATE,NORTH_MONEY,SOUTH_MONEY' +
    '&pageSize=20&sortTypes=-1&sortColumns=TRADE_DATE' +
    '&source=WEB&client=WEB';

  const resp = await fetch(url, {
    headers: HEADERS,
    signal: AbortSignal.timeout(8000),
  });
  if (!resp.ok) throw new Error(`datacenter-web HTTP ${resp.status}`);
  const data = await resp.json();

  const rows = data?.result?.data;
  if (!Array.isArray(rows) || rows.length === 0) throw new Error('no rows');

  // rows are newest-first
  const history = rows.map(r => ({
    date:      r.TRADE_DATE?.slice(0, 10) || '',
    north_net: r.NORTH_MONEY != null ? +Number(r.NORTH_MONEY).toFixed(2) : null,
    south_net: r.SOUTH_MONEY != null ? +Number(r.SOUTH_MONEY).toFixed(2) : null,
  })).filter(r => r.date);

  return history;
}

// ── Eastmoney push2: today's real-time running total ──────────────────────
// kamt endpoint: f62 = today northbound net (元), f184 = today southbound net (元)
async function fetchTodayRealtime() {
  const url =
    'https://push2.eastmoney.com/api/qt/kamt/get' +
    '?fields1=f1,f2,f3,f4,f5,f6' +
    '&fields2=f51,f52,f53,f54,f55,f56,f57,f58' +
    '&ut=b2884a393a59ad64002292a3e90d46a5' +
    '&cb=';          // empty cb = raw JSON, not JSONP

  const resp = await fetch(url, {
    headers: { ...HEADERS, Referer: 'https://quote.eastmoney.com/' },
    signal: AbortSignal.timeout(6000),
  });
  if (!resp.ok) throw new Error(`push2 HTTP ${resp.status}`);
  const data = await resp.json();

  // f62 = north net today (元), f184 = south net today (元)
  const north = data?.data?.f62;
  const south = data?.data?.f184;
  if (north == null && south == null) throw new Error('no kamt data');

  return {
    north_today_yi: north != null ? +(north / 1e8).toFixed(2) : null,
    south_today_yi: south != null ? +(south / 1e8).toFixed(2) : null,
  };
}

function buildSummary(history, todayRt) {
  if (!history.length) return { northbound: {}, southbound: {} };

  // Use today's real-time figure if available and market is open
  // Otherwise fall back to first row of history
  const northArr  = history.map(r => r.north_net).filter(v => v != null);
  const southArr  = history.map(r => r.south_net).filter(v => v != null);

  const todayN = todayRt?.north_today_yi ?? northArr[0] ?? null;
  const todayS = todayRt?.south_today_yi ?? southArr[0] ?? null;

  const sum5N  = northArr.slice(0, 5).reduce((a, b) => a + b, 0);
  const sum20N = northArr.slice(0, 20).reduce((a, b) => a + b, 0);
  const sum5S  = southArr.slice(0, 5).reduce((a, b) => a + b, 0);
  const sum20S = southArr.slice(0, 20).reduce((a, b) => a + b, 0);

  return {
    northbound: {
      today_net:      todayN != null ? +todayN.toFixed(2) : null,
      '5d_net':       +sum5N.toFixed(2),
      '20d_net':      +sum20N.toFixed(2),
      latest_net_flow: todayN != null ? todayN * 1e8 : null,  // keep legacy field (元)
      '5d_cumulative':  sum5N  * 1e8,
      '20d_cumulative': sum20N * 1e8,
      trend:          sum5N > 0 ? 'inflow' : 'outflow',
      updated:        history[0]?.date || '',
    },
    southbound: {
      today_net:      todayS != null ? +todayS.toFixed(2) : null,
      '5d_net':       +sum5S.toFixed(2),
      '20d_net':      +sum20S.toFixed(2),
      latest_net_flow: todayS != null ? todayS * 1e8 : null,
      '5d_cumulative':  sum5S  * 1e8,
      '20d_cumulative': sum20S * 1e8,
      trend:          sum5S > 0 ? 'inflow' : 'outflow',
      updated:        history[0]?.date || '',
    },
  };
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin',  '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'GET')    return res.status(405).json({ error: 'GET only' });

  const errors = [];
  let history = [];
  let todayRt = null;
  let source  = '';

  // ── 1. Try historical HSGT data ──────────────────────────────────────────
  try {
    history = await fetchHistoricalHSGT();
    source = 'eastmoney-datacenter';
  } catch (e) {
    errors.push(`datacenter: ${e.message}`);
    console.warn('[capital-flow] datacenter failed:', e.message);
  }

  // ── 2. Try real-time today top-up ────────────────────────────────────────
  try {
    todayRt = await fetchTodayRealtime();
    source += source ? '+push2' : 'push2-only';
  } catch (e) {
    errors.push(`push2: ${e.message}`);
    console.warn('[capital-flow] push2 failed:', e.message);
  }

  if (!history.length && !todayRt) {
    // Both sources failed — return structured empty response with error info
    return res.status(200).json({
      northbound: {},
      southbound: {},
      history:    [],
      available:  false,
      reason:     'Both Eastmoney endpoints failed (possible geo-restriction from this server)',
      errors,
      ts: Date.now(),
    });
  }

  const { northbound, southbound } = buildSummary(history, todayRt);

  // 60-second CDN cache — capital flow updates every minute during market hours
  res.setHeader('Cache-Control', 'public, s-maxage=60, stale-while-revalidate=30');

  return res.status(200).json({
    northbound,
    southbound,
    history,           // array of { date, north_net, south_net } in 亿
    available:  true,
    source,
    errors:     errors.length ? errors : undefined,
    ts:         Date.now(),
  });
}
