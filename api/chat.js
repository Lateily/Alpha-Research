// api/chat.js — Article Q&A powered by Claude
// POST { article, question, history, regime_data }
// Returns { response, role: 'assistant' }

import Anthropic from '@anthropic-ai/sdk';

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { article, question, history = [], regime_data, is_auto_analysis } = req.body || {};
  if (!article) return res.status(400).json({ error: 'article required' });

  const portfolioCtx = [
    '300308.SZ (Innolight) — AI Infrastructure, PERMISSIVE regime',
    '002594.SZ (BYD)       — EV/Auto, PERMISSIVE regime',
    '700.HK   (Tencent)    — Internet/Platform, NEUTRAL regime',
    '9999.HK  (NetEase)    — Internet/Platform, NEUTRAL regime',
    '6160.HK  (BeOne Medicines) — Biotech, NEUTRAL regime',
  ].join('\n');

  const regimeCtx = regime_data
    ? (regime_data.sectors || []).map(s => `${s.name_en}: ${s.regime}`).join(' | ')
    : 'Sector regimes not available';

  const systemPrompt = `You are a buy-side equity analyst at an institutional fund focused on A-shares and Hong Kong equities.

PORTFOLIO:
${portfolioCtx}

CURRENT SECTOR REGIMES:
${regimeCtx}

ARTICLE UNDER DISCUSSION:
Title: ${article.title}
Source: ${article.source} | Published: ${article.published_at}
Ticker tag: ${article.ticker}
Summary: ${article.summary || 'No summary available'}

YOUR ROLE:
- Analyse this news through the lens of our specific portfolio above
- Connect macro developments to individual position impact
- Be specific: name tickers, price implications, timeline
- Never say BUY/SELL — describe positioning implications instead
- Be concise (3-5 sentences per response unless asked to elaborate)
- Respond in the same language as the user's question (Chinese question → Chinese answer)
- Use financial shorthand where appropriate (e.g. "re-rates the multiple", "consensus needs to reset")`;

  // Build conversation history for Claude
  const messages = [
    ...history.map(m => ({ role: m.role, content: m.content })),
  ];

  // Auto-analysis on first open (no user question yet)
  if (is_auto_analysis) {
    messages.push({
      role: 'user',
      content: 'Briefly analyse the portfolio impact of this news in 3-4 sentences. Which position is most affected and how?',
    });
  } else {
    if (!question) return res.status(400).json({ error: 'question required' });
    messages.push({ role: 'user', content: question });
  }

  try {
    const message = await client.messages.create({
      model: 'claude-sonnet-4-6',
      max_tokens: 500,
      system: systemPrompt,
      messages,
    });

    const response = message.content[0]?.text || '';
    return res.status(200).json({
      role: 'assistant',
      content: response,
      input_tokens: message.usage?.input_tokens,
      output_tokens: message.usage?.output_tokens,
    });
  } catch (err) {
    console.error('chat.js error:', err);
    return res.status(500).json({ error: err.message || 'Internal error' });
  }
}
