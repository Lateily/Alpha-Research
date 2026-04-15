/**
 * AR Platform — Multi-Agent Research Debate
 *
 * Three AI analysts argue simultaneously via REST APIs (no extra npm packages):
 *   Bull     → Gemini 1.5 Pro   (strongest investment case)
 *   Bear     → GPT-4o           (risks, fraud signals, short thesis)
 *   Forensic → Claude Sonnet    (three-statement integrity check)
 *
 * Claude then synthesizes all three into a CIO verdict.
 */

import Anthropic from '@anthropic-ai/sdk';

// ── Shared output schema ─────────────────────────────────────────────────────
const SCHEMA = `Return ONLY valid JSON:
{
  "verdict":       "STRONG_BULL|BULL|NEUTRAL|BEAR|STRONG_BEAR",
  "confidence":    0-100,
  "headline":      "one punchy sentence",
  "top_arguments": [{"point":"string","strength":"HIGH|MED|LOW","evidence":"specific data"}],
  "killer_question":"the one question whose answer determines everything",
  "monitoring":    ["specific metric or event to watch"],
  "key_number":    "the single most important quantitative fact"
}`;

const FORENSIC_SCHEMA = `Return ONLY valid JSON:
{
  "verdict":       "CLEAN|CAUTION|RED_FLAG",
  "confidence":    0-100,
  "headline":      "one sentence summary",
  "top_arguments": [{"point":"string","strength":"HIGH|MED|LOW","evidence":"specific data"}],
  "killer_question":"string",
  "monitoring":    ["string"],
  "key_number":    "string"
}`;

// ── Prompts ──────────────────────────────────────────────────────────────────
const bullPrompt = (ticker, company, ctx) =>
`You are a conviction bull analyst at a top long-only fund.
Build the STRONGEST investment case for ${ticker}${company?` (${company})`:''}.
Find what the market is missing. Identify asymmetric upside catalysts in 12 months.
Explain why the bear case is wrong or already priced in.
Context: ${ctx||'General screening.'}
${SCHEMA}`;

const bearPrompt = (ticker, company, ctx) =>
`You are a short-seller and skeptical analyst.
Build the STRONGEST bear case for ${ticker}${company?` (${company})`:''}.
Hunt for: accounting red flags, competitive threats, earnings disappointment risk, valuation excess.
Context: ${ctx||'General screening.'}
${SCHEMA}`;

const forensicPrompt = (ticker, company, ctx) =>
`You are a forensic accountant doing due diligence on ${ticker}${company?` (${company})`:''}.
Examine: (1) OCF vs net income consistency, (2) receivables vs revenue growth,
(3) auditor quality and changes, (4) management guidance track record,
(5) related party transactions, (6) litigation/regulatory risks, (7) capital allocation quality.
Context: ${ctx||'General screening.'}
${FORENSIC_SCHEMA}`;

const synthesisPrompt = (ticker, company, bull, bear, forensic) =>
`You are the CIO synthesizing a three-analyst debate on ${ticker}${company?` (${company})`:''}.

BULL (Gemini): ${JSON.stringify(bull)}
BEAR (GPT-4o): ${JSON.stringify(bear)}
FORENSIC (Claude): ${JSON.stringify(forensic)}

Return ONLY valid JSON:
{
  "balance":         "BULL|NEUTRAL|BEAR",
  "conviction":      0-100,
  "summary":         "2-3 sentences on what the debate reveals",
  "agreements":      ["things all analysts agree on"],
  "disagreements":   ["unresolved tensions"],
  "decisive_factor": "the one thing that determines who is right",
  "must_monitor":    ["3-5 specific things to watch in 90 days"],
  "action":          "what a rational investor should do with this information"
}`;

// ── REST callers (no SDK for OpenAI / Gemini) ─────────────────────────────────
async function callGemini(prompt) {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key=${process.env.GOOGLE_AI_API_KEY}`;
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: { temperature: 0.7, maxOutputTokens: 2048 },
    }),
  });
  if (!r.ok) throw new Error(`Gemini ${r.status}: ${await r.text()}`);
  const d = await r.json();
  const text = d.candidates?.[0]?.content?.parts?.[0]?.text || '';
  const m = text.match(/\{[\s\S]*\}/);
  return JSON.parse(m ? m[0] : text);
}

async function callOpenAI(prompt) {
  const r = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${process.env.OPENAI_API_KEY}`,
      'Content-Type':  'application/json',
    },
    body: JSON.stringify({
      model: 'gpt-4o',
      messages: [{ role: 'user', content: prompt }],
      max_tokens: 2048,
      temperature: 0.7,
    }),
  });
  if (!r.ok) throw new Error(`OpenAI ${r.status}: ${await r.text()}`);
  const d = await r.json();
  const text = d.choices?.[0]?.message?.content || '';
  const m = text.match(/\{[\s\S]*\}/);
  return JSON.parse(m ? m[0] : text);
}

async function callClaude(prompt) {
  const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
  const msg = await client.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 2048,
    messages: [{ role: 'user', content: prompt }],
  });
  const text = msg.content[0].text;
  const m = text.match(/\{[\s\S]*\}/);
  return JSON.parse(m ? m[0] : text);
}

// ── Handler ───────────────────────────────────────────────────────────────────
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST')   return res.status(405).json({ error: 'Method not allowed' });

  const { ticker, company, context } = req.body;
  if (!ticker) return res.status(400).json({ error: 'ticker required' });

  const missing = [];
  if (!process.env.ANTHROPIC_API_KEY) missing.push('ANTHROPIC_API_KEY');
  if (!process.env.OPENAI_API_KEY)    missing.push('OPENAI_API_KEY');
  if (!process.env.GOOGLE_AI_API_KEY) missing.push('GOOGLE_AI_API_KEY');
  if (missing.length) return res.status(500).json({
    error: `Missing Vercel env vars: ${missing.join(', ')}`,
  });

  try {
    // All three analysts run in parallel
    const [bR, beR, fR] = await Promise.allSettled([
      callGemini(bullPrompt(ticker, company, context)).then(d => ({ ...d, role:'BULL',     model:'gemini-1.5-pro' })),
      callOpenAI(bearPrompt(ticker, company, context)).then(d => ({ ...d, role:'BEAR',     model:'gpt-4o' })),
      callClaude(forensicPrompt(ticker, company, context)).then(d => ({ ...d, role:'FORENSIC', model:'claude-sonnet' })),
    ]);

    const bull     = bR.status  === 'fulfilled' ? bR.value  : { role:'BULL',     error: bR.reason?.message  };
    const bear     = beR.status === 'fulfilled' ? beR.value : { role:'BEAR',     error: beR.reason?.message };
    const forensic = fR.status  === 'fulfilled' ? fR.value  : { role:'FORENSIC', error: fR.reason?.message  };

    // Synthesize if at least 2 analysts succeeded
    let synthesis = null;
    const ok = [bull, bear, forensic].filter(a => !a.error);
    if (ok.length >= 2) {
      synthesis = await callClaude(synthesisPrompt(ticker, company, bull, bear, forensic));
    }

    return res.status(200).json({
      ticker,
      company: company || ticker,
      generated_at: new Date().toISOString(),
      analysts: { bull, bear, forensic },
      synthesis,
    });

  } catch (err) {
    console.error('Debate error:', err);
    return res.status(500).json({ error: err.message });
  }
}
