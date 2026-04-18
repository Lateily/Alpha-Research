// api/research-pulse.js — Lightweight daily thesis integrity check
//
// PURPOSE: Run every morning for each focus stock. ~400 tokens per call.
// Answers three questions about a held research thesis without regenerating it.
//
// INPUT (POST body):
// {
//   ticker          : "700.HK",
//   company         : "Tencent",
//   stored_research : { ...full research JSON from ar_research_{ticker}... },
//   current_price   : 395.2,
//   price_at_research: 380.5,
//   price_change_pct : 3.9,          // % change since research generated
//   days_since_research: 14,
//   recent_news     : [...],         // last 48h articles for this ticker
//   sector_regime   : "NEUTRAL",
//   active_predictions: [...]        // open predictions for this ticker
// }
//
// OUTPUT:
// {
//   ticker, pulse_date,
//   variant_status  : "INTACT | WATCH | REVIEW | BROKEN",
//   variant_reason  : "string (1 sentence)",
//   entry_status    : "VALID | ADJUSTED | STALE",
//   entry_note      : "string (1 sentence)",
//   adjusted_entry  : "string or null",
//   headline_risk   : "LOW | MED | HIGH",
//   headline_note   : "string (1 sentence)",
//   prediction_updates: [{ id, action: "VERIFY|FALSIFY|MONITOR", reason }],
//   thesis_age_flag : true/false   (>30 days → auto-flag for regeneration)
//   tokens_used     : number
// }
//
// COST: ~400-600 tokens/call. 5 stocks × daily = ~2500 tokens/day.
// Compare to full research regeneration: 8192 tokens per stock.

import Anthropic from '@anthropic-ai/sdk';

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

// Status definitions surfaced in the UI
const STATUS_LOGIC = {
  variant: {
    INTACT:  { color: 'green', label: '论点完整',    labelEn: 'Thesis intact'      },
    WATCH:   { color: 'gold',  label: '需要关注',    labelEn: 'Watch closely'      },
    REVIEW:  { color: 'orange',label: '建议复核',    labelEn: 'Review recommended' },
    BROKEN:  { color: 'red',   label: '论点受损',    labelEn: 'Thesis broken'      },
  },
  entry: {
    VALID:    { color: 'green', label: '进场区间有效', labelEn: 'Entry zone valid'   },
    ADJUSTED: { color: 'gold',  label: '进场区间需调整',labelEn: 'Entry needs update' },
    STALE:    { color: 'red',   label: '进场区间过期', labelEn: 'Entry zone stale'  },
  },
};

function buildPulsePrompt(body) {
  const {
    ticker, company,
    stored_research: r,
    current_price, price_at_research, price_change_pct, days_since_research,
    recent_news = [],
    sector_regime,
    active_predictions = [],
  } = body;

  // Extract the most relevant fields from stored research
  const variantView   = r?.variant?.weBelieve?.e   || 'Not available';
  const marketBelieves= r?.variant?.marketBelieves?.e || 'Not available';
  const wrongIf       = r?.variant?.wrongIf?.e     || 'Not available';
  const vpScore       = r?.vp                      || '—';
  const dir           = r?.dir                     || '—';

  // Pull entry zone from nextActions (look for action mentioning entry/buy)
  const entryAction = (r?.nextActions || []).find(a =>
    /entry|enter|buy|add|initiat/i.test(a.e || '')
  );
  const entryNote = entryAction?.e || 'Not specified in original research';

  // Format news for prompt
  const newsSection = recent_news.length > 0
    ? recent_news.slice(0, 5).map((n, i) =>
        `[${i+1}] ${n.source ? `[${n.source}] ` : ''}${n.title}${n.published_at ? ` (${new Date(n.published_at).toLocaleDateString()})` : ''}`
      ).join('\n')
    : 'No recent news available for this ticker.';

  // Format predictions
  const predSection = active_predictions.length > 0
    ? active_predictions.map(p =>
        `• [ID:${p.id || '?'}] ${p.thesis || p.prediction || 'Prediction'} — Target: ${p.target || '?'}, Deadline: ${p.deadline || '?'}`
      ).join('\n')
    : 'No active predictions.';

  const priceMove = price_change_pct != null
    ? `${price_change_pct > 0 ? '+' : ''}${Number(price_change_pct).toFixed(1)}% since research`
    : 'change unknown';

  return `You are a portfolio manager reviewing a held position. Answer THREE questions about this thesis based on today's information. Be concise — one sentence per answer.

═══ ORIGINAL THESIS (generated ${days_since_research ?? '?'} days ago, price was ${price_at_research ?? '?'}) ═══
Ticker: ${ticker} (${company || ticker})
Direction: ${dir} | VP Score: ${vpScore}
Market believes: ${marketBelieves}
WE believe (variant): ${variantView}
This thesis is WRONG if: ${wrongIf}
Original entry zone: ${entryNote}

═══ TODAY'S SITUATION ═══
Current price: ${current_price ?? '?'} (${priceMove})
Sector regime: ${sector_regime || 'Unknown'}
Days since research generated: ${days_since_research ?? '?'}

═══ RECENT NEWS (last 48h) ═══
${newsSection}

═══ ACTIVE PREDICTIONS FOR THIS TICKER ═══
${predSection}

═══ ANSWER THESE THREE QUESTIONS ═══

Q1 — VARIANT INTEGRITY: Does today's news directly challenge or confirm the variant view above?
- INTACT: News is neutral or mildly supportive. Thesis unchanged.
- WATCH: News introduces a new risk or data point worth monitoring. Not yet thesis-breaking.
- REVIEW: News materially challenges a KEY assumption in the variant view. Recommend re-examining.
- BROKEN: News directly triggers the "wrong if" condition or falsifies the thesis.

Q2 — ENTRY VALIDITY: Is the original entry zone still appropriate given price movement?
- VALID: Price within or approaching original entry zone. No change needed.
- ADJUSTED: Price has moved significantly; provide an updated entry zone.
- STALE: Price has moved so far from original zone that the entry thesis no longer applies.

Q3 — PREDICTION UPDATES: For each active prediction, does today's news trigger any action?
- VERIFY: News directly confirms the prediction is on track.
- FALSIFY: News directly contradicts or invalidates the prediction.
- MONITOR: News is relevant but not conclusive — keep watching.
(Only flag predictions where news is directly relevant. Skip unrelated ones.)

Q4 — HEADLINE RISK: Overall risk level from today's news?
- LOW: No material news. Business as usual.
- MED: Some relevant news worth tracking but not thesis-breaking.
- HIGH: Material news that requires immediate attention.

Return ONLY this JSON object:
{
  "variant_status": "INTACT | WATCH | REVIEW | BROKEN",
  "variant_reason": "string (1 sentence explaining why)",
  "entry_status": "VALID | ADJUSTED | STALE",
  "entry_note": "string (1 sentence)",
  "adjusted_entry": "string (new entry zone, e.g. HK$385-395) or null if VALID/STALE",
  "headline_risk": "LOW | MED | HIGH",
  "headline_note": "string (1 sentence summary of most important news item)",
  "prediction_updates": [
    { "id": "string (prediction id)", "action": "VERIFY | FALSIFY | MONITOR", "reason": "string (1 sentence)" }
  ]
}

No markdown. Return only the JSON object.`;
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin',  '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST')   return res.status(405).json({ error: 'Method not allowed' });

  const {
    ticker, company,
    stored_research,
    current_price, price_at_research, price_change_pct,
    days_since_research,
    recent_news,
    sector_regime,
    active_predictions,
  } = req.body || {};

  // Validate required fields
  if (!ticker) return res.status(400).json({ error: 'ticker is required' });
  if (!stored_research) return res.status(400).json({ error: 'stored_research is required' });

  if (!process.env.ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: 'ANTHROPIC_API_KEY not configured' });
  }

  // Auto-flag stale research (>30 days)
  const thesisAgeFlag = (days_since_research ?? 0) > 30;

  // Large price move flag (>15% since research → recommend refresh)
  const largeMoveFlag = Math.abs(price_change_pct ?? 0) > 15;

  try {
    const prompt = buildPulsePrompt(req.body);

    const message = await client.messages.create({
      model:      'claude-sonnet-4-6',
      max_tokens: 700,
      messages:   [{ role: 'user', content: prompt }],
    });

    const text = message.content[0]?.text || '{}';

    // Parse JSON — handle potential markdown wrapping
    let jsonStr = text;
    const cb    = text.match(/```(?:json)?\s*([\s\S]*?)```/);
    if (cb) jsonStr = cb[1];

    let pulse;
    try {
      pulse = JSON.parse(jsonStr.trim());
    } catch {
      // Return a safe default if parsing fails
      pulse = {
        variant_status:     'WATCH',
        variant_reason:     'Pulse analysis unavailable — JSON parse error. Review manually.',
        entry_status:       'VALID',
        entry_note:         'No update available.',
        adjusted_entry:     null,
        headline_risk:      'LOW',
        headline_note:      'Could not parse pulse response.',
        prediction_updates: [],
      };
    }

    // Enrich with metadata not computed by Claude
    const result = {
      ticker,
      company:          company || ticker,
      pulse_date:       new Date().toISOString().slice(0, 10),
      pulse_timestamp:  new Date().toISOString(),

      // Core Claude outputs
      variant_status:     pulse.variant_status     || 'WATCH',
      variant_reason:     pulse.variant_reason     || '—',
      entry_status:       pulse.entry_status        || 'VALID',
      entry_note:         pulse.entry_note          || '—',
      adjusted_entry:     pulse.adjusted_entry      || null,
      headline_risk:      pulse.headline_risk       || 'LOW',
      headline_note:      pulse.headline_note       || '—',
      prediction_updates: pulse.prediction_updates  || [],

      // Computed flags
      thesis_age_flag:  thesisAgeFlag,  // >30 days since research → suggest refresh
      large_move_flag:  largeMoveFlag,  // >15% price move → suggest refresh
      days_since_research: days_since_research ?? null,
      price_change_pct: price_change_pct ?? null,
      current_price:    current_price ?? null,
      price_at_research: price_at_research ?? null,

      // UI display metadata
      status_meta: {
        variant: STATUS_LOGIC.variant[pulse.variant_status] || STATUS_LOGIC.variant.WATCH,
        entry:   STATUS_LOGIC.entry[pulse.entry_status]     || STATUS_LOGIC.entry.VALID,
      },

      // Token usage
      tokens_used:   message.usage?.input_tokens + message.usage?.output_tokens,
      input_tokens:  message.usage?.input_tokens,
      output_tokens: message.usage?.output_tokens,
    };

    return res.status(200).json({ success: true, ...result });

  } catch (err) {
    console.error('[research-pulse]', err);
    if (err.status === 429) return res.status(429).json({ error: 'Rate limited. Retry in a moment.' });
    return res.status(500).json({ error: err.message || 'Internal error' });
  }
}
