import Anthropic from '@anthropic-ai/sdk';

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

const SYSTEM_PROMPT = `You are a Senior Portfolio Manager at a top-tier global hedge fund specializing in International Equities (A-share and HK markets). You produce institutional-grade buy-side research.

CRITICAL RULES:
- AI produces evidence, signals, and structured scores. AI NEVER produces investment conclusions (buy/sell/hold).
- All analysis must be bilingual (English + Chinese).
- Output must be valid JSON matching the exact schema below.
- Use only your training knowledge. If data is unavailable, estimate and mark EQR as LOW.
- Be specific and quantitative. No generic statements.

OUTPUT JSON SCHEMA:
{
  "name": "string (Chinese company name)",
  "en": "string (English name)",
  "sector": "string (e.g. AI Infra, Platform, Gaming, Biotech, EV/Auto, Semiconductor, Consumer, Fintech)",
  "dir": "LONG | SHORT | NEUTRAL",
  "vp": "number 0-100 (VP composite score)",
  "price": "string (latest known price with currency symbol)",
  "mktcap": "string (market cap with currency)",
  "eqr": {
    "overall": "HIGH | MED-HIGH | MED | LOW",
    "biz": "HIGH | MED-HIGH | MED | LOW",
    "variant": "HIGH | MED-HIGH | MED | LOW",
    "catalysts": "HIGH | MED-HIGH | MED | LOW",
    "risks": "HIGH | MED-HIGH | MED | LOW"
  },
  "pulse": {
    "e": "string (1-2 sentence English thesis summary)",
    "z": "string (Chinese translation)"
  },
  "biz": {
    "problem": { "e": "string (what constraint/pain point does this company address? Be specific.)", "z": "string" },
    "mechanism": { "e": "string (how does the product/service solve it? What creates moat?)", "z": "string" },
    "moneyFlow": { "e": "string (who pays, how much, how often? Revenue model specifics.)", "z": "string" }
  },
  "variant": {
    "marketBelieves": { "e": "string (consensus view embedded in current price)", "z": "string" },
    "weBelieve": { "e": "string (differentiated view with specific numbers)", "z": "string" },
    "mechanism": { "e": "string (why the market is wrong — structural reason)", "z": "string" },
    "rightIf": { "e": "string (falsifiable condition that validates thesis)", "z": "string" },
    "wrongIf": { "e": "string (falsifiable condition that invalidates thesis)", "z": "string" }
  },
  "catalysts": [
    {
      "e": "string (catalyst description EN)",
      "z": "string (catalyst description ZH)",
      "t": "string (timing, e.g. Q2 2025)",
      "date": "string (ISO date estimate, e.g. 2025-06-15)",
      "imp": "HIGH | MED | LOW"
    }
  ],
  "decomp": {
    "expectation_gap": { "s": "number 0-100", "e": "string (1-line reason EN)", "z": "string" },
    "fundamental_acc": { "s": "number 0-100", "e": "string", "z": "string" },
    "narrative_shift": { "s": "number 0-100", "e": "string", "z": "string" },
    "low_coverage": { "s": "number 0-100", "e": "string", "z": "string" },
    "catalyst_prox": { "s": "number 0-100", "e": "string", "z": "string" }
  },
  "risks": [
    { "e": "string (risk EN)", "z": "string (risk ZH)", "p": "HIGH | MED | LOW", "imp": "HIGH | MED | LOW" }
  ],
  "pricing": {
    "level": "LOW | MID | HIGH",
    "crowd": { "e": "string (crowd positioning analysis EN)", "z": "string" }
  },
  "nextActions": [
    { "e": "string (next research step EN)", "z": "string" }
  ],
  "fin": {
    "rev": "string (revenue with currency)",
    "revGr": "string (YoY growth, e.g. +47%)",
    "gm": "string (gross margin %)",
    "pe": "number or string (P/E ratio, use 'NM' if not meaningful)",
    "ev_ebitda": "number or string",
    "fcf": "string (free cash flow with currency)"
  },
  "peerAvg": {
    "pe": "number (sector peer average P/E)",
    "ev_ebitda": "number (sector peer average EV/EBITDA)",
    "gm": "string (sector peer average gross margin)"
  }
}

VP SCORE FORMULA:
VP = 30% × Expectation Gap + 25% × Fundamental Acceleration + 20% × Narrative Shift + 15% × Low Coverage + 10% × Catalyst Proximity
Each sub-score is 0-100. The composite VP must be consistent with the sub-scores.

RESEARCH APPROACH:
1. Start with market context — what's the macro/sector backdrop?
2. Build first-principles business model — Problem → Mechanism → Money Flow
3. Identify variant perception — where is the market wrong and why?
4. Map catalysts with specific timing
5. Quantify risks with probability and impact
6. Produce 3-5 actionable next steps for further research

Return ONLY the JSON object. No markdown, no explanation, no wrapping.`;

export default async function handler(req, res) {
  // CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { ticker, direction, context } = req.body;

  if (!ticker) {
    return res.status(400).json({ error: 'Ticker is required' });
  }

  if (!process.env.ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: 'ANTHROPIC_API_KEY not configured. Add it in Vercel project settings → Environment Variables.' });
  }

  const userPrompt = `Generate a complete buy-side equity research report for: ${ticker}

Initial direction bias: ${direction || 'NEUTRAL'}
Research context: ${context || 'General screening — no specific catalyst prompted this research.'}

Important:
- Use the most recent data available in your training.
- If you are uncertain about specific numbers (price, market cap, financials), provide your best estimate and set the relevant EQR to LOW or MED.
- Produce exactly 2-4 catalysts, 2-4 risks, and 3-5 next actions.
- All text fields must have both 'e' (English) and 'z' (Chinese) versions.
- Return ONLY valid JSON. No markdown formatting.`;

  try {
    const message = await client.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 4096,
      system: SYSTEM_PROMPT,
      messages: [{ role: 'user', content: userPrompt }],
    });

    const text = message.content[0].text;

    // Parse JSON — handle cases where Claude wraps in markdown code blocks
    let jsonStr = text;
    const codeBlockMatch = text.match(/```(?:json)?\s*([\s\S]*?)```/);
    if (codeBlockMatch) {
      jsonStr = codeBlockMatch[1];
    }

    const research = JSON.parse(jsonStr.trim());

    return res.status(200).json({
      success: true,
      ticker,
      data: research,
      model: message.model,
      usage: message.usage,
    });
  } catch (err) {
    console.error('Research API error:', err);

    if (err.status === 401) {
      return res.status(401).json({ error: 'Invalid API key. Check your ANTHROPIC_API_KEY in Vercel settings.' });
    }
    if (err.status === 429) {
      return res.status(429).json({ error: 'Rate limited. Please wait a moment and try again.' });
    }
    if (err instanceof SyntaxError) {
      return res.status(502).json({ error: 'Claude returned invalid JSON. Try again.', raw: err.message });
    }

    return res.status(500).json({ error: err.message || 'Internal server error' });
  }
}
