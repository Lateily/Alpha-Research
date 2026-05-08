// api/chat.js — combined LLM utility endpoint
//
// Handles two actions via `action` body field (or backward-compat: no field
// = chat). Both actions use Anthropic Claude SDK with different model
// tiers + prompts.
//
// Action: "chat" (default — Article Q&A)
//   POST { action?: 'chat', article, question?, history?, regime_data?, is_auto_analysis? }
//   Response: { role: 'assistant', content, input_tokens, output_tokens }
//   Model: claude-sonnet-4-6
//
// Action: "translate" (financial headline translator)
//   POST { action: 'translate', text, context? }
//   Response: { success: true, translated, tokens_used }
//   Model: claude-haiku-4-5-20251001
//
// MERGE HISTORY (2026-05-08):
//   Vercel Hobby plan limits a deployment to 12 serverless functions.
//   Adding api/research-multi.js (Stage 2 multi-agent endpoint) pushed
//   us to 13 → build failed. Merged api/translate.js into this file
//   to fit the limit without losing functionality. Vercel rewrite
//   from /api/translate → /api/chat preserves the legacy URL.
//
//   Long-term path: Vercel Pro plan (100 functions + Workflows for
//   multi-agent durable execution per RESEARCH_AGENT_TEAM_v1.md v2).

import Anthropic from '@anthropic-ai/sdk';

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

// ─── /api/translate handler (merged 2026-05-08) ────────────────────────
async function handleTranslate(req, res) {
  const { text, context } = req.body || {};
  if (!text?.trim()) return res.status(400).json({ error: 'text is required' });
  if (!process.env.ANTHROPIC_API_KEY)
    return res.status(500).json({ error: 'ANTHROPIC_API_KEY not configured' });

  // Already Chinese (≥30% Chinese chars) — return as-is
  if (/[一-鿿]/.test(text) && text.replace(/[^一-鿿]/g, '').length > text.length * 0.3) {
    return res.status(200).json({ success: true, translated: text, tokens_used: 0 });
  }

  try {
    const contextNote = context ? ` (Context: ${context})` : '';
    const prompt = `You are a financial translator specialising in equity research. Translate this English financial news headline into concise, fluent Simplified Chinese. Preserve all ticker symbols, company names, and financial figures exactly. Return ONLY the Chinese translation, no explanation, no quotation marks.${contextNote}

Headline: ${text.trim()}`;

    const msg = await client.messages.create({
      model:      'claude-haiku-4-5-20251001',
      max_tokens: 200,
      messages:   [{ role: 'user', content: prompt }],
    });

    const translated = msg.content[0]?.text?.trim() || text;
    return res.status(200).json({
      success:     true,
      translated,
      tokens_used: (msg.usage?.input_tokens || 0) + (msg.usage?.output_tokens || 0),
    });
  } catch (err) {
    console.error('[chat:translate]', err);
    if (err.status === 429) return res.status(429).json({ error: 'Rate limited. Retry shortly.' });
    return res.status(500).json({ error: err.message || 'Translation failed' });
  }
}

// ─── /api/chat handler (article Q&A) ───────────────────────────────────
async function handleChat(req, res) {
  const { article, question, history = [], regime_data, is_auto_analysis } = req.body || {};
  if (!article) return res.status(400).json({ error: 'article required' });

  // Watchlist v1.2 (2026-05-08) — 4-ticker focus
  const portfolioCtx = [
    '300308.SZ (Innolight)  — AI Infrastructure, optical transceiver',
    '002594.SZ (BYD)        — EV/Auto, China + global expansion',
    '175.HK   (Geely Auto)  — China auto, multi-brand (Volvo/Polestar/Lotus)',
    '603233.SH (Da Shenlin) — Pharmacy retail, 2000+ stores',
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

  const messages = [
    ...history.map(m => ({ role: m.role, content: m.content })),
  ];

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
    console.error('[chat:chat]', err);
    return res.status(500).json({ error: err.message || 'Internal error' });
  }
}

// ─── Main handler — action discriminator ───────────────────────────────
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin',  '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST')    return res.status(405).json({ error: 'Method not allowed' });

  // Action discriminator. Default = chat (backward compat with existing
  // frontend callers). Vercel rewrite from /api/translate → /api/chat
  // sets action via body discriminator (frontend code adds `action: 'translate'`
  // when calling /api/translate URL after the merge).
  const action = (req.body || {}).action || 'chat';

  if (action === 'translate') {
    return handleTranslate(req, res);
  }
  if (action === 'chat') {
    return handleChat(req, res);
  }

  return res.status(400).json({ error: `Unknown action: ${action}. Use 'chat' or 'translate'.` });
}
