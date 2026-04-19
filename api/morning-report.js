// api/morning-report.js — Autonomous daily morning brief
//
// Called by GitHub Actions at 23:00 UTC (07:00 HKT) every weekday.
// Also callable manually from the UI for on-demand reports.
//
// INPUT (POST body):
// {
//   date           : "2026-04-19",
//   portfolio      : [{ ticker, company, vp, dir, current_price, price_change_pct,
//                        price_at_research, sector, sector_regime,
//                        pulse_status, pulse_reason, variant_brief }],
//   macro_news     : [...],          // top macro articles (last 24h)
//   portfolio_news : [...],          // ticker-specific articles (last 24h)
//   regime_data    : { sectors: [...] },
//   predictions    : [...],          // full prediction_log entries
//   is_github_action: true/false     // controls email HTML generation
// }
//
// OUTPUT:
// {
//   date, generated_at,
//   headline,                        // single sentence: what matters most today
//   macro_summary: { e, z },
//   market_mood: "RISK-ON | NEUTRAL | RISK-OFF",
//   portfolio_flags: [{ ticker, company, status, note_e, note_z, action_required }],
//   top_story: { title, source, impact_e, impact_z, tickers_affected },
//   trade_ideas: [{ ticker, idea_e, idea_z, entry, urgency }],
//   event_radar: [{ event, date, ticker, impact }],
//   prediction_updates: [{ id, ticker, action, reason }],
//   regime_notes: "string",
//   reading_time: "5 min",
//   html_email: "string (full HTML for Resend delivery)"
// }

import Anthropic from '@anthropic-ai/sdk';

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

// ─── DEFAULT PORTFOLIO (used when no portfolio passed in body) ────────────────
const DEFAULT_PORTFOLIO = [
  { ticker: '700.HK',    company: 'Tencent',   sector: 'Internet',   vp: 65, dir: 'LONG' },
  { ticker: '9999.HK',   company: 'NetEase',   sector: 'Gaming',     vp: 58, dir: 'LONG' },
  { ticker: '6160.HK',   company: 'BeiGene',   sector: 'Biotech',    vp: 65, dir: 'LONG' },
  { ticker: '002594.SZ', company: 'BYD',       sector: 'EV/Auto',    vp: 61, dir: 'LONG' },
  { ticker: '300308.SZ', company: 'Innolight', sector: 'AI Infra',   vp: 72, dir: 'LONG' },
];

// ─── PROMPT BUILDER ───────────────────────────────────────────────────────────
function buildReportPrompt(body) {
  const {
    date = new Date().toISOString().slice(0, 10),
    portfolio = DEFAULT_PORTFOLIO,
    macro_news = [],
    portfolio_news = [],
    regime_data,
    predictions = [],
  } = body;

  // Format portfolio section
  const portfolioSection = portfolio.map(s => {
    const px    = s.current_price ? `Current: ${s.current_price}` : '';
    const chg   = s.price_change_pct != null ? ` (${s.price_change_pct > 0 ? '+' : ''}${Number(s.price_change_pct).toFixed(1)}%)` : '';
    const pulse = s.pulse_status ? ` | Pulse: ${s.pulse_status}` : '';
    const vb    = s.variant_brief ? `\n    Variant: ${s.variant_brief.slice(0, 120)}` : '';
    return `  ${s.ticker} (${s.company}) — VP${s.vp || '?'} ${s.dir || '—'} | ${s.sector_regime || s.sector || '?'} regime${pulse}\n  ${px}${chg}${vb}`;
  }).join('\n\n');

  // Format news sections (keep it tight — 5 macro, 6 portfolio)
  const macroSection = macro_news.slice(0, 5).map((n, i) =>
    `[M${i+1}] ${n.source ? `[${n.source}] ` : ''}${n.title}`
  ).join('\n') || 'No macro news available.';

  const portfolioSection2 = portfolio_news.slice(0, 6).map((n, i) =>
    `[P${i+1}] ${n.ticker ? `(${n.ticker}) ` : ''}${n.source ? `[${n.source}] ` : ''}${n.title}`
  ).join('\n') || 'No portfolio-specific news.';

  // Format regime
  const regimeSection = regime_data?.sectors
    ? regime_data.sectors.map(s => `${s.name_en}: ${s.regime}`).join(' | ')
    : 'Regime data unavailable.';

  // Open predictions only (most relevant for morning check)
  const openPreds = predictions.filter(p => p.status === 'OPEN' || p.status === 'PENDING');
  const predSection = openPreds.length > 0
    ? openPreds.map(p =>
        `[${p.id}] ${p.ticker} — WE BELIEVE: ${(p.we_believe || '').slice(0, 100)} | Target date: ${p.target_date} | Confidence: ${p.confidence}%`
      ).join('\n')
    : 'No open predictions.';

  return `You are a senior portfolio manager writing a concise morning briefing for ${date}.
This is read over coffee — 5 minutes maximum. Be specific. No generic market commentary.

═══ OUR PORTFOLIO ═══
${portfolioSection}

═══ SECTOR REGIMES ═══
${regimeSection}

═══ MACRO NEWS (last 24h) ═══
${macroSection}

═══ PORTFOLIO-SPECIFIC NEWS (last 24h) ═══
${portfolioSection2}

═══ OPEN PREDICTIONS ═══
${predSection}

═══ INSTRUCTIONS ═══
Write a morning brief that answers: What happened overnight? What do I need to act on today?

RULES:
- Cite specific news items by their reference [M1], [P1] etc. where relevant
- For trade_ideas: only include if there is a specific, actionable entry condition today
- For portfolio_flags: every stock gets a status — CLEAR (no new information), WATCH (monitor closely), ACTION (requires decision today), ALERT (thesis event occurred)
- prediction_updates: only include OPEN predictions that are directly addressed by today's news
- Be bilingual: all narrative fields need both English (e) and Chinese (z)
- market_mood: RISK-ON / NEUTRAL / RISK-OFF based on macro news tone
- headline: single sentence, the most important thing to know this morning

Return ONLY this JSON object:
{
  "headline": "string (1 sentence, most important thing today)",
  "market_mood": "RISK-ON | NEUTRAL | RISK-OFF",
  "macro_summary": {
    "e": "string (2-3 sentences, key macro developments)",
    "z": "string (Chinese translation)"
  },
  "portfolio_flags": [
    {
      "ticker": "string",
      "company": "string",
      "status": "CLEAR | WATCH | ACTION | ALERT",
      "note_e": "string (1 sentence — what changed or why flagged)",
      "note_z": "string",
      "action_required": true/false
    }
  ],
  "top_story": {
    "title": "string",
    "source": "string",
    "impact_e": "string (how this affects our portfolio specifically)",
    "impact_z": "string",
    "tickers_affected": ["string"]
  },
  "trade_ideas": [
    {
      "ticker": "string",
      "idea_e": "string (specific entry thesis)",
      "idea_z": "string",
      "entry": "string (e.g. HK$385-395 on weakness, good for 2-3 weeks)",
      "urgency": "HIGH | MED | LOW"
    }
  ],
  "event_radar": [
    {
      "event": "string (what is happening)",
      "date": "string (when, e.g. Apr 22 or This week)",
      "ticker": "string or null",
      "impact": "HIGH | MED | LOW"
    }
  ],
  "prediction_updates": [
    {
      "id": "string (e.g. pred_001)",
      "ticker": "string",
      "action": "ON-TRACK | VERIFY | FALSIFY | MONITOR",
      "reason": "string (1 sentence, cite news item if relevant)"
    }
  ],
  "regime_notes": "string (any regime changes or signals worth noting, or 'No regime changes today')"
}

No markdown. Return only the JSON object.`;
}

// ─── HTML EMAIL BUILDER ───────────────────────────────────────────────────────
function buildEmailHtml(report, date) {
  const moodColor   = { 'RISK-ON': '#22c55e', 'NEUTRAL': '#6b7280', 'RISK-OFF': '#ef4444' }[report.market_mood] || '#6b7280';
  const statusColor = { CLEAR:'#22c55e', WATCH:'#eab308', ACTION:'#f97316', ALERT:'#ef4444' };
  const urgColor    = { HIGH:'#ef4444',  MED:'#eab308',   LOW:'#22c55e' };

  const flagRows = (report.portfolio_flags || []).map(f => {
    const sc = statusColor[f.status] || '#6b7280';
    return `
      <tr>
        <td style="padding:8px 12px; border-bottom:1px solid #f0f0f0; font-family:monospace; font-size:12px; color:#1a1a1a; white-space:nowrap">${f.ticker}</td>
        <td style="padding:8px 12px; border-bottom:1px solid #f0f0f0; font-size:11px; color:#444">${f.company}</td>
        <td style="padding:8px 12px; border-bottom:1px solid #f0f0f0">
          <span style="display:inline-block; padding:2px 8px; border-radius:3px; font-size:9px; font-weight:700; background:${sc}20; color:${sc}">${f.status}</span>
        </td>
        <td style="padding:8px 12px; border-bottom:1px solid #f0f0f0; font-size:11px; color:#444; line-height:1.5">${f.note_e}<br><span style="color:#888; font-size:10px">${f.note_z || ''}</span></td>
      </tr>`;
  }).join('');

  const tradeRows = (report.trade_ideas || []).map(t => {
    const uc = urgColor[t.urgency] || '#6b7280';
    return `
      <div style="margin-bottom:12px; padding:12px; background:#f8f9fa; border-left:3px solid ${uc}; border-radius:0 6px 6px 0">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px">
          <span style="font-family:monospace; font-size:12px; font-weight:700; color:#1a1a1a">${t.ticker}</span>
          <span style="font-size:9px; padding:1px 6px; background:${uc}20; color:${uc}; border-radius:3px; font-weight:700">${t.urgency}</span>
        </div>
        <div style="font-size:11px; color:#333; line-height:1.5; margin-bottom:4px">${t.idea_e}</div>
        <div style="font-size:10px; color:#888; margin-bottom:4px">${t.idea_z || ''}</div>
        ${t.entry ? `<div style="font-size:10px; color:#2563eb; font-weight:600">📍 ${t.entry}</div>` : ''}
      </div>`;
  }).join('');

  const eventRows = (report.event_radar || []).map(e => {
    const ic = { HIGH:'#ef4444', MED:'#eab308', LOW:'#22c55e' }[e.impact] || '#888';
    return `<tr>
      <td style="padding:6px 10px; border-bottom:1px solid #f0f0f0; font-size:10px; color:#888; white-space:nowrap">${e.date || '—'}</td>
      <td style="padding:6px 10px; border-bottom:1px solid #f0f0f0; font-size:11px; color:#333">${e.event}</td>
      <td style="padding:6px 10px; border-bottom:1px solid #f0f0f0; font-size:10px; font-family:monospace; color:#1a1a1a">${e.ticker || '—'}</td>
      <td style="padding:6px 10px; border-bottom:1px solid #f0f0f0">
        <span style="font-size:9px; font-weight:700; color:${ic}">${e.impact}</span>
      </td>
    </tr>`;
  }).join('');

  const predRows = (report.prediction_updates || []).map(p => {
    const ac = { 'ON-TRACK':'#22c55e', VERIFY:'#22c55e', FALSIFY:'#ef4444', MONITOR:'#eab308' }[p.action] || '#888';
    return `<div style="display:flex; gap:8px; align-items:flex-start; margin-bottom:6px; font-size:11px">
      <span style="font-size:9px; padding:2px 7px; border-radius:3px; font-weight:700; background:${ac}20; color:${ac}; white-space:nowrap; margin-top:1px">${p.action}</span>
      <span style="font-family:monospace; font-size:11px; font-weight:700; white-space:nowrap">${p.ticker}</span>
      <span style="color:#444; line-height:1.5">${p.reason}</span>
    </div>`;
  }).join('');

  return `<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0; padding:0; background:#f5f5f5; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<div style="max-width:680px; margin:0 auto; padding:24px 16px">

  <!-- Header -->
  <div style="background:#1a1a2e; border-radius:10px 10px 0 0; padding:20px 24px; margin-bottom:2px">
    <div style="display:flex; align-items:center; justify-content:space-between">
      <div>
        <div style="font-size:10px; color:#8b8fc7; font-weight:600; letter-spacing:0.1em; text-transform:uppercase">AR Platform · Morning Report</div>
        <div style="font-size:22px; font-weight:800; color:#ffffff; margin-top:4px; line-height:1.2">${report.headline || 'Morning Brief'}</div>
      </div>
      <div style="text-align:right">
        <div style="font-size:10px; color:#8b8fc7">${date}</div>
        <div style="font-size:11px; font-weight:700; padding:3px 10px; background:${moodColor}25; color:${moodColor}; border-radius:4px; margin-top:4px; display:inline-block">${report.market_mood || 'NEUTRAL'}</div>
      </div>
    </div>
  </div>

  <!-- Macro Summary -->
  <div style="background:#ffffff; border:1px solid #e5e7eb; padding:16px 24px; margin-bottom:2px">
    <div style="font-size:10px; font-weight:700; color:#6b7280; letter-spacing:0.08em; text-transform:uppercase; margin-bottom:8px">📰 Macro Overview</div>
    <div style="font-size:12px; color:#1a1a1a; line-height:1.7">${report.macro_summary?.e || '—'}</div>
    <div style="font-size:11px; color:#888; margin-top:6px; line-height:1.6">${report.macro_summary?.z || ''}</div>
    ${report.top_story ? `
    <div style="margin-top:12px; padding:10px 14px; background:#f0f4ff; border-left:3px solid #2563eb; border-radius:0 6px 6px 0">
      <div style="font-size:11px; font-weight:700; color:#2563eb">${report.top_story.source || ''} — ${report.top_story.title || ''}</div>
      <div style="font-size:11px; color:#333; margin-top:4px; line-height:1.5">${report.top_story.impact_e || ''}</div>
      ${report.top_story.tickers_affected?.length ? `<div style="font-size:10px; color:#6b7280; margin-top:4px">Affects: ${report.top_story.tickers_affected.join(', ')}</div>` : ''}
    </div>` : ''}
  </div>

  <!-- Portfolio Status -->
  <div style="background:#ffffff; border:1px solid #e5e7eb; padding:16px 24px; margin-bottom:2px">
    <div style="font-size:10px; font-weight:700; color:#6b7280; letter-spacing:0.08em; text-transform:uppercase; margin-bottom:12px">📊 Portfolio Status</div>
    <table style="width:100%; border-collapse:collapse">
      <thead>
        <tr style="background:#f9fafb">
          <th style="padding:6px 12px; text-align:left; font-size:9px; color:#9ca3af; font-weight:600; text-transform:uppercase">Ticker</th>
          <th style="padding:6px 12px; text-align:left; font-size:9px; color:#9ca3af; font-weight:600; text-transform:uppercase">Company</th>
          <th style="padding:6px 12px; text-align:left; font-size:9px; color:#9ca3af; font-weight:600; text-transform:uppercase">Status</th>
          <th style="padding:6px 12px; text-align:left; font-size:9px; color:#9ca3af; font-weight:600; text-transform:uppercase">Note</th>
        </tr>
      </thead>
      <tbody>${flagRows}</tbody>
    </table>
  </div>

  ${tradeRows ? `
  <!-- Trade Ideas -->
  <div style="background:#ffffff; border:1px solid #e5e7eb; padding:16px 24px; margin-bottom:2px">
    <div style="font-size:10px; font-weight:700; color:#6b7280; letter-spacing:0.08em; text-transform:uppercase; margin-bottom:12px">💡 Today's Trade Ideas</div>
    ${tradeRows}
  </div>` : ''}

  ${eventRows ? `
  <!-- Event Radar -->
  <div style="background:#ffffff; border:1px solid #e5e7eb; padding:16px 24px; margin-bottom:2px">
    <div style="font-size:10px; font-weight:700; color:#6b7280; letter-spacing:0.08em; text-transform:uppercase; margin-bottom:12px">📅 Event Radar</div>
    <table style="width:100%; border-collapse:collapse">
      <thead><tr style="background:#f9fafb">
        <th style="padding:5px 10px; text-align:left; font-size:9px; color:#9ca3af; font-weight:600">Date</th>
        <th style="padding:5px 10px; text-align:left; font-size:9px; color:#9ca3af; font-weight:600">Event</th>
        <th style="padding:5px 10px; text-align:left; font-size:9px; color:#9ca3af; font-weight:600">Ticker</th>
        <th style="padding:5px 10px; text-align:left; font-size:9px; color:#9ca3af; font-weight:600">Impact</th>
      </tr></thead>
      <tbody>${eventRows}</tbody>
    </table>
  </div>` : ''}

  ${predRows ? `
  <!-- Prediction Updates -->
  <div style="background:#ffffff; border:1px solid #e5e7eb; padding:16px 24px; margin-bottom:2px">
    <div style="font-size:10px; font-weight:700; color:#6b7280; letter-spacing:0.08em; text-transform:uppercase; margin-bottom:12px">🎯 Prediction Log Updates</div>
    ${predRows}
  </div>` : ''}

  <!-- Footer -->
  <div style="background:#f9fafb; border:1px solid #e5e7eb; border-radius:0 0 10px 10px; padding:14px 24px; display:flex; justify-content:space-between; align-items:center">
    <div style="font-size:10px; color:#9ca3af">AR Platform · Autonomous Research Agent</div>
    <div style="font-size:10px; color:#9ca3af">Generated ${new Date().toLocaleString('en-HK', { timeZone:'Asia/Hong_Kong', hour12:false })} HKT</div>
  </div>

</div>
</body>
</html>`;
}

// ─── MAIN HANDLER ─────────────────────────────────────────────────────────────
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin',  '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST')   return res.status(405).json({ error: 'Method not allowed' });

  if (!process.env.ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: 'ANTHROPIC_API_KEY not configured' });
  }

  const body = req.body || {};
  const date = body.date || new Date().toISOString().slice(0, 10);

  try {
    const prompt = buildReportPrompt(body);

    const message = await client.messages.create({
      model:      'claude-sonnet-4-6',
      max_tokens: 2500,
      messages:   [{ role: 'user', content: prompt }],
    });

    const text = message.content[0]?.text || '{}';
    let jsonStr = text;
    const cb = text.match(/```(?:json)?\s*([\s\S]*?)```/);
    if (cb) jsonStr = cb[1];

    let report;
    try {
      report = JSON.parse(jsonStr.trim());
    } catch {
      return res.status(502).json({ error: 'Claude returned invalid JSON', raw: text.slice(0, 300) });
    }

    // Build HTML email
    const htmlEmail = buildEmailHtml(report, date);

    const result = {
      date,
      generated_at: new Date().toISOString(),
      ...report,
      html_email:    htmlEmail,
      tokens_used:   (message.usage?.input_tokens || 0) + (message.usage?.output_tokens || 0),
    };

    return res.status(200).json({ success: true, report: result });

  } catch (err) {
    console.error('[morning-report]', err);
    if (err.status === 429) return res.status(429).json({ error: 'Rate limited.' });
    return res.status(500).json({ error: err.message || 'Internal error' });
  }
}
