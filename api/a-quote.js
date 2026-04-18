// api/a-quote.js — Real-time A-share + HK quotes via Sina Finance (unofficial)
//
// GET /api/a-quote?codes=sh300308,sz002594,hk00700
//
// Code format:
//   A-share SH: sh{6-digit code}   e.g. sh600519
//   A-share SZ: sz{6-digit code}   e.g. sz002594
//   HK stocks:  hk{5-digit code}   e.g. hk00700  (zero-padded to 5 digits)
//   BJ stocks:  bj{6-digit code}   e.g. bj430090
//
// Returns: { quotes: [...], source: "sina"|"tencent", ts: epoch_ms }
//
// Each quote:
//   { code, exchange, name, price, prev_close, change_pct, change_amt,
//     open, high, low, volume, amount, date, time, currency }
//
// Data source: Sina Finance hq.sinajs.cn (primary), qt.gtimg.cn (fallback)
// No API key required. No geo-restriction from Vercel.
// These are the same feeds used by most Chinese retail brokerage apps.

const SINA_URL  = 'https://hq.sinajs.cn/list=';
const TENCENT_URL = 'https://qt.gtimg.cn/q=';

const HEADERS_SINA = {
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
  'Referer':    'https://finance.sina.com.cn/',
  'Accept':     '*/*',
};
const HEADERS_TENCENT = {
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
  'Referer':    'https://finance.qq.com/',
  'Accept':     '*/*',
};

// ── Sina parser ────────────────────────────────────────────────────────────
// Response: var hq_str_sh300308="Innolight,open,prev,curr,high,low,bid,ask,vol,amount,...,date,time,";
// Fields (0-indexed):
//   0:name 1:open 2:prev_close 3:current 4:high 5:low
//   8:volume(手) 9:amount(元) 30:date 31:time
// HK fields differ slightly: 0:name 1:open 2:prev 3:curr 4:high 5:low 8:vol 9:amount

function parseSina(raw) {
  const quotes = [];
  const lineRe  = /var hq_str_([a-z]+)(\d+)="([^"]*)"/g;
  let m;
  while ((m = lineRe.exec(raw)) !== null) {
    const prefix = m[1];   // 'sh', 'sz', 'hk', 'bj'
    const codeNum = m[2];
    const body   = m[3];
    if (!body || body === '0') continue;  // suspended / not found

    const f = body.split(',');
    if (f.length < 10) continue;

    const curr = parseFloat(f[3]);
    const prev = parseFloat(f[2]);
    const open = parseFloat(f[1]);
    const high = parseFloat(f[4]);
    const low  = parseFloat(f[5]);
    const vol  = parseFloat(f[8]) * 100;   // Sina returns lots (手), ×100 = shares
    const amt  = parseFloat(f[9]);

    if (!curr || isNaN(curr)) continue;

    const changePct = prev ? +((curr - prev) / prev * 100).toFixed(3) : null;
    const changeAmt = prev ? +(curr - prev).toFixed(3) : null;

    const exchange = prefix === 'sh' ? 'SH'
                   : prefix === 'sz' ? 'SZ'
                   : prefix === 'hk' ? 'HK'
                   : prefix === 'bj' ? 'BJ'
                   : prefix.toUpperCase();

    quotes.push({
      code:       codeNum,
      full_code:  `${prefix}${codeNum}`,   // e.g. sh300308
      exchange,
      name:       f[0] || '',
      price:      curr,
      prev_close: prev,
      change_pct: changePct,
      change_amt: changeAmt,
      open:       isNaN(open) ? null : open,
      high:       isNaN(high) ? null : high,
      low:        isNaN(low)  ? null : low,
      volume:     isNaN(vol)  ? null : vol,
      amount:     isNaN(amt)  ? null : amt,
      date:       f[30] || null,
      time:       f[31] || null,
      currency:   exchange === 'HK' ? 'HKD' : 'CNY',
    });
  }
  return quotes;
}

// ── Tencent parser ─────────────────────────────────────────────────────────
// Response: v_sh300308="51~Innolight~300308~curr~prev~open~vol~buy~sell~bid1~...";
// Fields (0-indexed after split by '~'):
//   1:name 2:code 3:curr 4:prev 5:open 6:vol 7:buyvol 8:sellvol
//   33:high 34:low 37:amount 38:turnover 44:pe 45:pb 46:market_cap
// Note: some fields vary; treat conservatively.
function parseTencent(raw, requestedCodes) {
  const quotes = [];
  const lineRe  = /v_([a-z]+)(\d+)="([^"]*)"/g;
  let m;
  while ((m = lineRe.exec(raw)) !== null) {
    const prefix = m[1];
    const codeNum = m[2];
    const body   = m[3];
    if (!body) continue;

    const f = body.split('~');
    if (f.length < 10) continue;

    const curr = parseFloat(f[3]);
    const prev = parseFloat(f[4]);
    const open = parseFloat(f[5]);
    const vol  = parseFloat(f[6]) * 100;
    const high = f.length > 33 ? parseFloat(f[33]) : null;
    const low  = f.length > 34 ? parseFloat(f[34]) : null;
    const amt  = f.length > 37 ? parseFloat(f[37]) * 10000 : null;  // Tencent uses 万

    if (!curr || isNaN(curr)) continue;

    const changePct = prev ? +((curr - prev) / prev * 100).toFixed(3) : null;
    const changeAmt = prev ? +(curr - prev).toFixed(3) : null;

    const exchange = prefix === 'sh' ? 'SH'
                   : prefix === 'sz' ? 'SZ'
                   : prefix === 'hk' ? 'HK'
                   : prefix.toUpperCase();

    quotes.push({
      code:       codeNum,
      full_code:  `${prefix}${codeNum}`,
      exchange,
      name:       f[1] || '',
      price:      curr,
      prev_close: prev,
      change_pct: changePct,
      change_amt: changeAmt,
      open:       isNaN(open) ? null : open,
      high:       (!high || isNaN(high)) ? null : high,
      low:        (!low  || isNaN(low))  ? null : low,
      volume:     isNaN(vol)  ? null : vol,
      amount:     (!amt || isNaN(amt))   ? null : amt,
      date:       null,
      time:       null,
      currency:   exchange === 'HK' ? 'HKD' : 'CNY',
    });
  }
  return quotes;
}

// ── TextDecoder helper (GBK) ───────────────────────────────────────────────
// Vercel Edge runtime has TextDecoder; Node runtime also has it.
async function decodeGBK(buffer) {
  try {
    return new TextDecoder('gbk').decode(buffer);
  } catch {
    return new TextDecoder('utf-8').decode(buffer);
  }
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin',  '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'GET')    return res.status(405).json({ error: 'GET only' });

  const { codes } = req.query;
  if (!codes?.trim()) return res.status(400).json({ error: 'codes required (e.g. sh300308,sz002594,hk00700)' });

  const codeList = codes.split(',').map(c => c.trim().toLowerCase()).filter(Boolean);
  if (codeList.length > 200) return res.status(400).json({ error: 'Max 200 codes per request' });

  const joined = codeList.join(',');
  let quotes = [];
  let source  = '';

  // ── 1. Try Sina Finance ────────────────────────────────────────────────
  try {
    const resp = await fetch(SINA_URL + joined, {
      headers: HEADERS_SINA,
      signal:  AbortSignal.timeout(7000),
    });
    if (resp.ok) {
      const buf = await resp.arrayBuffer();
      const txt = await decodeGBK(new Uint8Array(buf));
      quotes = parseSina(txt);
      source = 'sina';
    }
  } catch (e) {
    console.warn('[a-quote] Sina failed:', e.message);
  }

  // ── 2. Tencent fallback if Sina returned nothing ───────────────────────
  if (!quotes.length) {
    try {
      const resp = await fetch(TENCENT_URL + joined, {
        headers: HEADERS_TENCENT,
        signal:  AbortSignal.timeout(7000),
      });
      if (resp.ok) {
        const buf = await resp.arrayBuffer();
        const txt = await decodeGBK(new Uint8Array(buf));
        quotes = parseTencent(txt, codeList);
        source = 'tencent';
      }
    } catch (e) {
      console.warn('[a-quote] Tencent failed:', e.message);
    }
  }

  if (!quotes.length) {
    return res.status(502).json({
      error: 'Both Sina and Tencent Finance APIs failed. They may be geo-restricted from this server.',
      quotes: [],
      ts: Date.now(),
    });
  }

  res.setHeader('Cache-Control', 'no-store');
  return res.status(200).json({ quotes, source, count: quotes.length, ts: Date.now() });
}
