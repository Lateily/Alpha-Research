// api/translate.js — Lightweight financial headline translator
//
// POST body: { text: "Headline in English", context?: "optional ticker/sector" }
// Response:  { success: true, translated: "中文标题", tokens_used: 80 }
//
// Uses claude-haiku for minimal cost — ~80-120 tokens per headline.
// ~1000 translations ≈ $0.04

import Anthropic from '@anthropic-ai/sdk';

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin',  '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST')   return res.status(405).json({ error: 'Method not allowed' });

  const { text, context } = req.body || {};
  if (!text?.trim()) return res.status(400).json({ error: 'text is required' });
  if (!process.env.ANTHROPIC_API_KEY)
    return res.status(500).json({ error: 'ANTHROPIC_API_KEY not configured' });

  // Already Chinese — return as-is
  if (/[\u4e00-\u9fff]/.test(text) && text.replace(/[^\u4e00-\u9fff]/g, '').length > text.length * 0.3)
    return res.status(200).json({ success: true, translated: text, tokens_used: 0 });

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
    console.error('[translate]', err);
    if (err.status === 429) return res.status(429).json({ error: 'Rate limited. Retry shortly.' });
    return res.status(500).json({ error: err.message || 'Translation failed' });
  }
}
