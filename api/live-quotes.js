// api/live-quotes.js — Real-time batch quotes via Eastmoney push2 API
//
// GET /api/live-quotes?codes=1.600000,0.000001,116.00700
//
// Code format: {market}.{code}
//   SH stocks:  1.600000
//   SZ stocks:  0.000001
//   HK stocks: 116.00700   (5-digit, left-padded)
//   BJ stocks:  0.430090
//
// Same data source as AKShare — but called directly from Vercel serverless,
// bypassing the GitHub Actions IP restrictions entirely.
//
// Returns: { quotes: [...], ts: epoch_ms, count: n }
//
// Each quote: { code, market, name, price, change_pct, change_amt,
//               volume, turnover, amplitude, turnover_rate, pe,
//               volume_ratio, high, low, open, prev_close }

const EM_FIELDS = 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18';

const HEADERS = {
  'User-Agent':
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ' +
    'AppleWebKit/537.36 (KHTML, like Gecko) ' +
    'Chrome/124.0.0.0 Safari/537.36',
  'Referer': 'https://quote.eastmoney.com/',
  'Accept':  'application/json, text/plain, */*',
  'Accept-Language': 'zh-CN,zh;q=0.9',
};

function parseVal(v) {
  if (v == null || v === '-' || v === '' || v === 0 && typeof v === 'string') return null;
  const n = Number(v);
  return isNaN(n) ? null : n;
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin',  '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'GET')    return res.status(405).json({ error: 'GET only' });

  const { codes } = req.query;
  if (!codes?.trim()) return res.status(400).json({ error: 'codes is required' });

  // Eastmoney limits: ~800 codes per request is safe
  const codeList = codes.split(',').map(c => c.trim()).filter(Boolean);
  if (codeList.length > 800) {
    return res.status(400).json({ error: 'Max 800 codes per request' });
  }

  const url = `https://push2.eastmoney.com/api/qt/ulist.np/get` +
    `?fltt=2&invt=2&fields=${EM_FIELDS}&secids=${encodeURIComponent(codeList.join(','))}`;

  try {
    const resp = await fetch(url, {
      headers: HEADERS,
      signal:  AbortSignal.timeout(8000),
    });

    if (!resp.ok) throw new Error(`Eastmoney returned HTTP ${resp.status}`);
    const data = await resp.json();

    const diff = data?.data?.diff;
    if (!diff) {
      return res.status(200).json({ quotes: [], ts: Date.now(), count: 0 });
    }

    const arr = Array.isArray(diff) ? diff : Object.values(diff);

    const quotes = arr
      .filter(Boolean)
      .map(q => {
        const mkt = q.f13;
        const vol = parseVal(q.f5);
        return {
          code:          String(q.f12 || '').trim(),
          market:        mkt,               // 1=SH, 0=SZ, 116=HK, 0=BJ
          em_key:        `${mkt}.${q.f12}`, // reconstructed key
          name:          String(q.f14 || '').trim(),
          price:         parseVal(q.f2),
          change_pct:    parseVal(q.f3),    // %
          change_amt:    parseVal(q.f4),
          volume:        vol != null ? vol * 100 : null, // EM returns lots, ×100=shares
          turnover:      parseVal(q.f6),    // CNY / HKD
          amplitude:     parseVal(q.f7),    // %
          turnover_rate: parseVal(q.f8),    // %
          pe:            parseVal(q.f9),
          volume_ratio:  parseVal(q.f10),
          high:          parseVal(q.f15),
          low:           parseVal(q.f16),
          open:          parseVal(q.f17),
          prev_close:    parseVal(q.f18),
        };
      })
      .filter(q => q.code);

    res.setHeader('Cache-Control', 'no-store');
    return res.status(200).json({ quotes, ts: Date.now(), count: quotes.length });

  } catch (err) {
    console.error('[live-quotes]', err.message);
    return res.status(502).json({ error: err.message || 'Eastmoney fetch failed' });
  }
}
