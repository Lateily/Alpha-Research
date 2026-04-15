/**
 * AR Platform — Multi-Agent Research Debate
 *
 * Three AI analysts argue simultaneously:
 *   Bull    → Gemini 1.5 Pro   (finds the strongest investment case)
 *   Bear    → GPT-4o           (finds risks, fraud signals, short thesis)
 *   Forensic→ Claude Sonnet    (three-statement consistency, red flags)
 *
 * Then Claude synthesizes the debate into an actionable verdict.
 */

import Anthropic from '@anthropic-ai/sdk';
import OpenAI    from 'openai';
import { GoogleGenerativeAI } from '@google/generative-ai';

// ── Output schema every analyst must follow ─────────────────────────────────
const ANALYST_SCHEMA = `
Return ONLY valid JSON in this exact shape:
{
  "verdict":       "STRONG_BULL | BULL | NEUTRAL | BEAR | STRONG_BEAR",
  "confidence":    number (0-100),
  "headline":      "string (one punchy sentence)",
  "top_arguments": [
    { "point": "string", "strength": "HIGH|MED|LOW", "evidence": "string (specific data)" }
  ],
  "killer_question": "string (the one question whose answer determines everything)",
  "monitoring":    ["string (specific metric/event to watch)"],
  "key_number":    "string (the single most important quantitative fact)"
}`;

// ── Bull analyst prompt (Gemini) ─────────────────────────────────────────────
const bullPrompt = (ticker, company, context) => `
You are a conviction bull analyst at a top long-only fund.
Your mandate: build the STRONGEST possible investment case for ${ticker}${company ? ` (${company})` : ''}.

Find every reason to own this stock:
- What is the market missing or underpricing?
- What asymmetric upside catalyst exists in the next 12 months?
- Why is the bear case wrong or already priced in?
- What would make this a 2-3x from here?

Context: ${context || 'General screening.'}
${ANALYST_SCHEMA}`;

// ── Bear analyst prompt (GPT-4o) ─────────────────────────────────────────────
const bearPrompt = (ticker, company, context) => `
You are a short-seller and skeptical analyst at an activist fund.
Your mandate: build the STRONGEST possible bear case for ${ticker}${company ? ` (${company})` : ''}.

Hunt for every weakness:
- Is the valuation justified by fundamentals?
- What structural headwinds does the business face?
- Where could earnings disappoint consensus?
- Are there accounting red flags, related-party transactions, or auditor concerns?
- What is the realistic downside scenario?

Context: ${context || 'General screening.'}
${ANALYST_SCHEMA}`;

// ── Forensic analyst prompt (Claude) ─────────────────────────────────────────
const forensicPrompt = (ticker, company, context) => `
You are a forensic accountant and due diligence specialist.
Your mandate: stress-test the integrity of ${ticker}${company ? ` (${company})` : ''}.

Examine systematically:
1. THREE-STATEMENT CONSISTENCY: Does OCF match net income? Is working capital reasonable?
2. REVENUE QUALITY: Are receivables growing faster than revenue? Channel stuffing signals?
3. AUDIT QUALITY: Is the auditor reputable? Any qualifications, restatements, or auditor changes?
4. MANAGEMENT CREDIBILITY: Track record of guidance accuracy. Insider selling patterns.
5. LEGAL/REGULATORY: Any litigation, regulatory investigations, or sanctions?
6. RELATED PARTIES: Unusual transactions with related entities?
7. CAPITAL ALLOCATION: Does management create or destroy value with free cash flow?

Context: ${context || 'General screening.'}

Return ONLY valid JSON:
{
  "verdict":       "CLEAN | CAUTION | RED_FLAG",
  "confidence":    number (0-100),
  "headline":      "string",
  "top_arguments": [
    { "point": "string", "strength": "HIGH|MED|LOW", "evidence": "string" }
  ],
  "killer_question": "string",
  "monitoring":    ["string"],
  "key_number":    "string"
}`;

// ── Synthesis prompt (Claude) ─────────────────────────────────────────────────
const synthesisPrompt = (ticker, company, bull, bear, forensic) => `
You are the Chief Investment Officer synthesizing a three-way analyst debate on ${ticker}${company ? ` (${company})` : ''}.

BULL ANALYST SAID:
${JSON.stringify(bull, null, 2)}

BEAR ANALYST SAID:
${JSON.stringify(bear, null, 2)}

FORENSIC ANALYST SAID:
${JSON.stringify(forensic, null, 2)}

Synthesize into a balanced verdict. Where do they agree? What are the unresolved tensions?
What is the one thing that will determine who is right?

Return ONLY valid JSON:
{
  "balance":          "BULL | NEUTRAL | BEAR",
  "conviction":       number (0-100, how confident you are in the balance call),
  "summary":          "string (2-3 sentences, what the debate reveals)",
  "agreements":       ["string (things all three analysts agree on)"],
  "disagreements":    ["string (key unresolved tensions between analysts)"],
  "decisive_factor":  "string (the one thing that determines who is right)",
  "must_monitor":     ["string (3-5 specific things to watch in next 90 days)"],
  "action":           "string (what a rational investor should do with this information)"
}`;

// ── Model runners ─────────────────────────────────────────────────────────────
async function runBull(ticker, company, context) {
  const genAI = new GoogleGenerativeAI(process.env.GOOGLE_AI_API_KEY);
  const model = genAI.getGenerativeModel({ model: 'gemini-1.5-pro' });
  const result = await model.generateContent(bullPrompt(ticker, company, context));
  const text = result.response.text();
  const match = text.match(/\{[\s\S]*\}/);
  const json = JSON.parse(match ? match[0] : text);
  return { ...json, model: 'gemini-1.5-pro', role: 'BULL' };
}

async function runBear(ticker, company, context) {
  const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  const resp = await openai.chat.completions.create({
    model: 'gpt-4o',
    messages: [{ role: 'user', content: bearPrompt(ticker, company, context) }],
    max_tokens: 2048,
    temperature: 0.7,
  });
  const text = resp.choices[0].message.content;
  const match = text.match(/\{[\s\S]*\}/);
  const json = JSON.parse(match ? match[0] : text);
  return { ...json, model: 'gpt-4o', role: 'BEAR' };
}

async function runForensic(ticker, company, context) {
  const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
  const msg = await client.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 2048,
    messages: [{ role: 'user', content: forensicPrompt(ticker, company, context) }],
  });
  const text = msg.content[0].text;
  const match = text.match(/\{[\s\S]*\}/);
  const json = JSON.parse(match ? match[0] : text);
  return { ...json, model: 'claude-sonnet', role: 'FORENSIC' };
}

async function runSynthesis(ticker, company, bull, bear, forensic) {
  const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
  const msg = await client.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 1024,
    messages: [{ role: 'user', content: synthesisPrompt(ticker, company, bull, bear, forensic) }],
  });
  const text = msg.content[0].text;
  const match = text.match(/\{[\s\S]*\}/);
  return JSON.parse(match ? match[0] : text);
}

// ── Handler ───────────────────────────────────────────────────────────────────
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { ticker, company, context } = req.body;
  if (!ticker) return res.status(400).json({ error: 'Ticker required' });

  // Check API keys
  const missing = [];
  if (!process.env.ANTHROPIC_API_KEY) missing.push('ANTHROPIC_API_KEY');
  if (!process.env.OPENAI_API_KEY)    missing.push('OPENAI_API_KEY');
  if (!process.env.GOOGLE_AI_API_KEY) missing.push('GOOGLE_AI_API_KEY');
  if (missing.length > 0) {
    return res.status(500).json({ error: `Missing API keys: ${missing.join(', ')}. Add them in Vercel → Settings → Environment Variables.` });
  }

  try {
    // Run all three analysts in parallel
    const [bullRes, bearRes, forensicRes] = await Promise.allSettled([
      runBull(ticker, company, context),
      runBear(ticker, company, context),
      runForensic(ticker, company, context),
    ]);

    const bull     = bullRes.status     === 'fulfilled' ? bullRes.value     : { role:'BULL',     error: bullRes.reason?.message };
    const bear     = bearRes.status     === 'fulfilled' ? bearRes.value     : { role:'BEAR',     error: bearRes.reason?.message };
    const forensic = forensicRes.status === 'fulfilled' ? forensicRes.value : { role:'FORENSIC', error: forensicRes.reason?.message };

    // Only synthesize if at least two analysts succeeded
    const succeeded = [bull, bear, forensic].filter(a => !a.error);
    let synthesis = null;
    if (succeeded.length >= 2) {
      synthesis = await runSynthesis(ticker, company, bull, bear, forensic);
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
