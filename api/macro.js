import Anthropic from '@anthropic-ai/sdk';

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

export default async function handler(req, res) {
  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    return res.status(200).end();
  }
  res.setHeader('Access-Control-Allow-Origin', '*');

  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { regime_data, macro_snapshot, portfolio_context } = req.body || {};

  if (!regime_data) return res.status(400).json({ error: 'regime_data required' });

  // Build regime summary
  const regimeSummary = (regime_data.sectors || [])
    .map(s => `${s.name_en}: ${s.regime} — ${s.rationale_en}`)
    .join('\n');

  const macroCtx = macro_snapshot
    ? `Current macro snapshot:\n${JSON.stringify(macro_snapshot, null, 2)}`
    : 'No real-time macro data available — use qualitative reasoning.';

  const portfolioCtx = portfolio_context
    ? `Portfolio context: ${portfolio_context}`
    : 'Focus stocks: 300308.SZ (Innolight), 002594.SZ (BYD), 700.HK (Tencent), 9999.HK (NetEase), 6160.HK (BeOne Medicines)';

  const systemPrompt = `You are the Macro Intelligence function of an institutional buy-side equity research platform focused on A-shares and Hong Kong equities.

Your role is to generate ONE exclusive, non-consensus macro insight. This is the most important section of the daily brief.

STRICT FORMAT — output valid JSON only, no markdown, no preamble:
{
  "market_reads": "The consensus interpretation of the most significant recent macro development (1-2 sentences, specific)",
  "we_think": "Our non-consensus interpretation — what the market is missing (1-2 sentences, specific number or mechanism)",
  "mechanism": "The causal chain explaining WHY the market reading is incomplete (2-3 sentences)",
  "implication": "Specific implication for our portfolio or sector positioning (1-2 sentences, name specific tickers or sectors)",
  "watch_for": "The one leading indicator to monitor in the next 5-10 trading days that will confirm or deny our view",
  "confidence": "MEDIUM",
  "horizon": "5-10 trading days"
}

RULES:
- Be genuinely non-consensus. If you cannot form a differentiated view, say "insufficient signal" in market_reads and explain why.
- Never say "BUY" or "SELL". Describe implications for positioning, not decisions.
- Be specific. "Tech sector" is too vague. "300308.SZ optical transceivers" is specific.
- The confidence field must be HIGH, MEDIUM, or LOW based on how much evidence supports your non-consensus view.
- This is for a sophisticated single investor — do not add disclaimers or hedging language.`;

  const userPrompt = `Current sector regime classifications:
${regimeSummary}

${macroCtx}

${portfolioCtx}

Generate the Exclusive Insight for today's macro brief. Focus on what the consensus is missing about the interaction between current macro conditions and our specific sector exposures.`;

  try {
    const message = await client.messages.create({
      model: 'claude-sonnet-4-6',
      max_tokens: 800,
      system: systemPrompt,
      messages: [{ role: 'user', content: userPrompt }]
    });

    const raw = message.content[0]?.text || '';

    // Parse JSON from response
    let insight;
    try {
      // Strip any markdown fences if present
      const cleaned = raw.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();
      insight = JSON.parse(cleaned);
    } catch {
      // If parsing fails, return structured error
      insight = {
        market_reads: 'Failed to parse AI response.',
        we_think: raw.slice(0, 200),
        mechanism: '',
        implication: '',
        watch_for: '',
        confidence: 'LOW',
        horizon: 'N/A'
      };
    }

    return res.status(200).json({
      insight,
      generated_at: new Date().toISOString(),
      model: 'claude-sonnet-4-6',
      input_tokens: message.usage?.input_tokens,
      output_tokens: message.usage?.output_tokens
    });

  } catch (err) {
    console.error('macro.js error:', err);
    return res.status(500).json({ error: err.message || 'Internal error' });
  }
}
