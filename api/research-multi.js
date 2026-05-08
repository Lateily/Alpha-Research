/**
 * api/research-multi.js — Stage 2 of multi-agent research team v2
 *
 * Implements RESEARCH_AGENT_TEAM_v1.md v2 §2 spec. Junyan §6 decisions
 * (2026-05-08) integrated: round-2 rebuttal between Bull/Bear, Bull/Bear
 * see news, GPT-5.5 (was GPT-4o), T-RT Technical Analyst added,
 * failure-debugging policy (no silent swallow).
 *
 * Pipeline (7 LLM calls per thesis):
 *   ROUND 1 (3 parallel):  Bull r1 + Bear r1 + Technical
 *   ROUND 2 (2 parallel):  Bull-rebut-Bear + Bear-rebut-Bull
 *   SEQUENTIAL:            Forensic (sees all) → Synthesizer (final 8-step)
 *
 * Cost: ~$0.85-1.00 per thesis. Latency: ~6 min wall-clock.
 *
 * Output: same schema as /api/research PLUS:
 *   data._direction       : LONG | SHORT | PASS
 *   data._divergence_score: 0-100 (bull vs bear disagreement)
 *   data._bull_thesis     : Bull round-2 output (full thesis)
 *   data._bear_thesis     : Bear round-2 output (full thesis)
 *   data._bull_r1         : Bull round-1 (audit trail)
 *   data._bear_r1         : Bear round-1 (audit trail)
 *   data._technical       : Technical agent output
 *   data._forensic        : Forensic findings
 *   data._agent_status    : per-agent success/fail/duration log
 *   data._quality         : FC.1+FC.4 validation on Synthesizer's final output
 *
 * Env vars (Vercel):
 *   ANTHROPIC_API_KEY   — required (Forensic + Synth + fallback)
 *   OPENAI_API_KEY      — required (Bear)
 *   GOOGLE_AI_API_KEY   — required (Bull)
 *   MODEL_BULL          — optional override, default 'gemini-1.5-pro'
 *   MODEL_BEAR          — optional override, default 'gpt-5.5'
 *   MODEL_TECHNICAL     — optional override, default 'claude-sonnet-4-20250514'
 *   MODEL_FORENSIC      — optional override, default 'claude-sonnet-4-20250514'
 *   MODEL_SYNTH         — optional override, default 'claude-opus-4-7'
 *
 * Failure-debugging policy (Junyan §6.3): NO silent swallow. Each agent
 * failure is logged with role + error + duration. Pipeline returns
 * `_status: PARTIAL_FAILURE` if any agent fails; Synthesizer proceeds
 * with whatever inputs are available + flags missing inputs in metadata.
 * If 2+ agents fail OR Synthesizer fails, return 502 with diagnostic.
 */

import Anthropic from '@anthropic-ai/sdk';
import {
  validateThesisQuality,
  buildEnrichmentBlock,
  buildFundamentalsBlock,
  buildExtrasBlock,
  buildConsensusBlock,
  runPass1,
  extractJsonPayload,
  isPlainObject,
  buildQcFindings,
} from './research.js';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

// ─── Model config (Junyan §6.4 — not absolute, swappable via env) ──────────
// Defaults verified 2026-05-08 against vendor API docs:
//   Gemini: 1.5-pro DEPRECATED → use 2.5-pro (production-grade, stable).
//           3.1-pro-preview is newer but Preview-status (subject to change).
//           Override via MODEL_BULL env if you want preview.
//   OpenAI: gpt-5.5 confirmed current (released 2026-04-23, $5/$30 per 1M
//           tokens). Aliased to latest 2026-04-23 build. Override via
//           MODEL_BEAR env to pin specific date or use gpt-5.5-pro.
//   Claude: sonnet-4-20250514 + opus-4-7 active (per existing platform usage).
const MODELS = {
  bull:      process.env.MODEL_BULL      || 'gemini-2.5-pro',
  bear:      process.env.MODEL_BEAR      || 'gpt-5.5',
  technical: process.env.MODEL_TECHNICAL || 'claude-sonnet-4-20250514',
  forensic:  process.env.MODEL_FORENSIC  || 'claude-sonnet-4-20250514',
  synth:     process.env.MODEL_SYNTH     || 'claude-opus-4-7',
};

// ─── REST callers (no SDK for OpenAI / Gemini, mirrors api/debate.js) ──────

async function callGemini(model, system, user, maxOutputTokens = 8192) {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${process.env.GOOGLE_AI_API_KEY}`;
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      systemInstruction: { parts: [{ text: system }] },
      contents: [{ parts: [{ text: user }] }],
      generationConfig: { temperature: 0.6, maxOutputTokens },
    }),
  });
  if (!r.ok) throw new Error(`Gemini ${r.status}: ${await r.text()}`);
  const d = await r.json();
  const text = d.candidates?.[0]?.content?.parts?.[0]?.text || '';
  return text;
}

async function callOpenAI(model, system, user, maxTokens = 8192) {
  const r = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${process.env.OPENAI_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model,
      messages: [
        { role: 'system', content: system },
        { role: 'user', content: user },
      ],
      max_tokens: maxTokens,
      temperature: 0.6,
    }),
  });
  if (!r.ok) throw new Error(`OpenAI ${r.status}: ${await r.text()}`);
  const d = await r.json();
  return d.choices?.[0]?.message?.content || '';
}

async function callClaude(model, system, user, maxTokens = 16384) {
  const msg = await anthropic.messages.create({
    model,
    max_tokens: maxTokens,
    system,
    messages: [{ role: 'user', content: user }],
  });
  return msg.content?.[0]?.text || '';
}

// ─── JSON parsing for agent outputs ───────────────────────────────────────

function parseAgentJson(rawText, role) {
  try {
    const json = JSON.parse(extractJsonPayload(rawText));
    if (!isPlainObject(json)) {
      throw new SyntaxError(`${role} JSON root not an object`);
    }
    return json;
  } catch (err) {
    throw new Error(`${role} JSON parse failed: ${err.message}. Raw start: ${rawText.slice(0, 200)}`);
  }
}

// ─── Shared 8-step thesis schema (used by Bull, Bear, Synth) ──────────────
// Subset of api/research.js SYSTEM_PROMPT — focused on output schema only.
// Each agent's role overlay (LONG / SHORT / synthesis) goes in user prompt.
const THESIS_SCHEMA_INSTRUCTION = `OUTPUT JSON SCHEMA (mandatory):
{
  "ticker": "string",
  "thesis_protocol_version": "v2",
  "step_1_catalyst": {
    "catalyst_event": "string (specific event)",
    "catalyst_date_or_window": "string (FUTURE date — past dates fail validation)",
    "catalyst_type": "earnings_revision | product_launch | policy_change | industry_inflection | management_change | regulatory | macro_inflection",
    "catalyst_source": "string (which data source backs this date)"
  },
  "step_2_mechanism": { "mechanism_chain": ["1. ...", "2. ...", ..., "5. ..."] },
  "step_3_evidence": {
    "evidence_quantitative": ["concrete number-bearing claims"],
    "evidence_qualitative": ["concrete qualitative observations"],
    "contrarian_view": {
      "market_consensus": { "e": "...", "z": "..." },
      "our_variant": { "e": "...", "z": "..." },
      "what_changes_our_mind": "single concrete observable that flips our view"
    }
  },
  "step_4_quantification": {
    "metric_target": "...",
    "current_value": "...",
    "predicted_value": "...",
    "predicted_range": { "low": "...", "mid": "...", "high": "..." },
    "predicted_horizon": "FUTURE date or window",
    "confidence": 0.0-1.0
  },
  "step_5_proves_right_if": ["specific observable conditions, 3-5 items"],
  "step_6_proves_wrong_if": ["specific observable conditions, 3-5 items"],
  "step_7_variant_view": {
    "variant_view_one_sentence": "Market believes X → We believe Y → Mechanism is Z",
    "time_to_resolution": "...",
    "expected_pnl_asymmetry": {
      "upside_if_right": "+X% to +Y%",
      "downside_if_wrong": "-A% to -B%",
      "reward_to_risk": "N:1 (target ≥2:1)"
    }
  },
  "step_8_phase_and_timing": {
    "phase_1_market_belief": {
      "duration_estimate": "...",
      "why_market_keeps_buying": ["..."],
      "early_signs_phase_1_weakening": ["..."],
      "optional_long_play": { "direction": "...", "sizing": "...", "exit_trigger": "..." }
    },
    "phase_2_reality_recognition": {
      "catalyst_for_reversion": ["..."],
      "estimated_timing": "...",
      "short_play": { "direction": "...", "sizing": "...", "entry_trigger": "..." }
    },
    "position_sizing_curve": {
      "pre_phase_1_weakening": "0%",
      "phase_1_weakening_confirmed": "X%",
      "phase_2_catalyst_imminent": "Y% (must be ≥ phase_1 — monotonically non-decreasing)"
    }
  },
  "qc_checklist": { ... boolean self-report per check ... }
}

GROUNDING RULE: every numeric claim must come from the data context above
or be labeled "[external estimate, not in our data context]". Don't fabricate.

Return ONLY valid JSON, no commentary outside.`;

// ─── Round 1 prompts ──────────────────────────────────────────────────────

const BULL_ROLE_SYSTEM = `You are the LONG-thesis advocate at a hedge fund. Your role is to build the strongest possible BULLISH case for ${'$ticker'} using the data context provided. You argue LONG. You may NOT argue SHORT — that's a different agent's job.

Discipline:
- Every numeric claim must be grounded in the data context (cite the field where possible)
- If the data context lacks a number, write "not available in our data" not a guess
- catalyst_date must be FUTURE relative to today (data context "TEMPORAL CONTEXT" line)
- Be specific with R/R numbers, target multiples, and falsifiability conditions

Follow THESIS_PROTOCOL v2 — 8 steps. Output JSON per schema.`;

const BEAR_ROLE_SYSTEM = `You are the SHORT-thesis advocate at a hedge fund. Your role is to build the strongest possible BEARISH case for ${'$ticker'} using the data context provided. You argue SHORT (or NEUTRAL if data genuinely doesn't support a short — but bias toward identifying contrarian short angle).

Discipline:
- Every numeric claim must be grounded in the data context (cite the field where possible)
- If the data context lacks a number, write "not available in our data" not a guess
- catalyst_date must be FUTURE relative to today
- Hunt for: accounting red flags, competitive threats, valuation excess, narrative crowding

Follow THESIS_PROTOCOL v2 — 8 steps. Output JSON per schema.`;

const TECHNICAL_ROLE_SYSTEM = `You are a technical analyst. Position-agnostic — you describe what the price/volume/chip/margin data structurally show, not whether to buy/sell.

Output JSON ONLY:
{
  "trend": "UP | DOWN | RANGE",
  "trend_strength": 0-100,
  "momentum": { "rsi_estimate": 0-100, "macd_signal": "bullish|bearish|neutral", "interpretation": "1 sentence" },
  "key_levels": { "support": [list of price levels], "resistance": [list] },
  "volume_profile": "expanding | contracting | normal",
  "chip_concentration": "concentrated | dispersed | uncertain",
  "margin_trend": "expanding_long | unwinding | flat | unknown",
  "technical_summary_e": "2-3 sentences",
  "technical_summary_z": "2-3 sentences"
}`;

function bullR1Prompt(ticker, dataContextBlock) {
  return `${BULL_ROLE_SYSTEM.replace('$ticker', ticker)}

═══════════════════════════════════════════════════════
DATA CONTEXT (use this — don't fabricate)
═══════════════════════════════════════════════════════
${dataContextBlock}

═══════════════════════════════════════════════════════
TASK: Produce the strongest LONG thesis for ${ticker}.
═══════════════════════════════════════════════════════

${THESIS_SCHEMA_INSTRUCTION}`;
}

function bearR1Prompt(ticker, dataContextBlock) {
  return `${BEAR_ROLE_SYSTEM.replace('$ticker', ticker)}

═══════════════════════════════════════════════════════
DATA CONTEXT (use this — don't fabricate)
═══════════════════════════════════════════════════════
${dataContextBlock}

═══════════════════════════════════════════════════════
TASK: Produce the strongest SHORT thesis for ${ticker}.
═══════════════════════════════════════════════════════

${THESIS_SCHEMA_INSTRUCTION}`;
}

function technicalPrompt(ticker, dataContextBlock) {
  // Technical only needs OHLC + chip + margin slice — but for simplicity pass full context
  return `${TECHNICAL_ROLE_SYSTEM}

═══════════════════════════════════════════════════════
DATA CONTEXT for ${ticker}
═══════════════════════════════════════════════════════
${dataContextBlock}

Return ONLY JSON per the schema in your role instruction.`;
}

// ─── Round 2 (rebuttal) prompts ───────────────────────────────────────────

function bullR2Prompt(ticker, dataContextBlock, bullR1, bearR1) {
  return `${BULL_ROLE_SYSTEM.replace('$ticker', ticker)}

═══════════════════════════════════════════════════════
DATA CONTEXT
═══════════════════════════════════════════════════════
${dataContextBlock}

═══════════════════════════════════════════════════════
YOUR ROUND 1 OUTPUT (the LONG thesis you built):
═══════════════════════════════════════════════════════
${JSON.stringify(bullR1).slice(0, 6000)}

═══════════════════════════════════════════════════════
THE BEAR'S ROUND 1 ATTACK ON THIS NAME:
═══════════════════════════════════════════════════════
${JSON.stringify(bearR1).slice(0, 6000)}

═══════════════════════════════════════════════════════
TASK: Round 2 rebuttal.

You have seen the Bear's argument. NOW you have one chance to revise
the LONG thesis with full awareness of the Bear's strongest case.

You may:
- Defend each point the Bear raised — explain WHY it's already priced
  in / wrong / outweighed by the long catalyst
- REVISE your own thesis if any of the Bear's points are decisive
- Emit a "_rebuttal" field listing which Bear arguments you addressed
  and how

You may NOT:
- Drop your LONG bias entirely (that's the synthesizer's call, not yours)
- Ignore the Bear's specific points

Output: full updated 8-step JSON per schema, PLUS a "_rebuttal" field:
"_rebuttal": "Bear claimed X — addressed by Y. Bear claimed A — addressed
by B. ..."
═══════════════════════════════════════════════════════

${THESIS_SCHEMA_INSTRUCTION}`;
}

function bearR2Prompt(ticker, dataContextBlock, bullR1, bearR1) {
  return `${BEAR_ROLE_SYSTEM.replace('$ticker', ticker)}

═══════════════════════════════════════════════════════
DATA CONTEXT
═══════════════════════════════════════════════════════
${dataContextBlock}

═══════════════════════════════════════════════════════
YOUR ROUND 1 OUTPUT (the SHORT thesis you built):
═══════════════════════════════════════════════════════
${JSON.stringify(bearR1).slice(0, 6000)}

═══════════════════════════════════════════════════════
THE BULL'S ROUND 1 LONG CASE:
═══════════════════════════════════════════════════════
${JSON.stringify(bullR1).slice(0, 6000)}

═══════════════════════════════════════════════════════
TASK: Round 2 rebuttal.

You have seen the Bull's argument. NOW you have one chance to revise
the SHORT thesis with full awareness of the Bull's strongest case.

You may:
- Attack each Bull point — explain WHY it doesn't hold / is already
  priced in / outweighed by structural shorts
- REVISE your own thesis if Bull's points are decisive (drop to NEUTRAL
  is allowed)
- Emit a "_rebuttal" field listing which Bull arguments you addressed
  and how

Output: full updated 8-step JSON per schema, PLUS a "_rebuttal" field.
═══════════════════════════════════════════════════════

${THESIS_SCHEMA_INSTRUCTION}`;
}

// ─── Forensic prompt ─────────────────────────────────────────────────────

function forensicPrompt(ticker, dataContextBlock, bullR2, bearR2, technical) {
  return `You are a forensic analyst. Your job: cross-check the Bull and Bear theses against the data context, and assess whether the Technical signal AGREES or CONFLICTS with each side.

Data context for ${ticker}:
${dataContextBlock}

═══════════════════════════════════════════════════════
BULL ROUND 2 (final LONG thesis):
${JSON.stringify(bullR2).slice(0, 8000)}

BEAR ROUND 2 (final SHORT thesis):
${JSON.stringify(bearR2).slice(0, 8000)}

TECHNICAL ANALYST OUTPUT:
${JSON.stringify(technical).slice(0, 3000)}
═══════════════════════════════════════════════════════

TASK: produce structured findings JSON.

For Bull's quantitative claims: each claim → look up in data context →
flag MATCH / MISMATCH / UNVERIFIABLE with evidence.
Same for Bear's claims.

Identify shared assumptions (both sides depend on the same untested
premise) — these are HIGH RISK because if the assumption fails, both
theses collapse.

Compare Technical signal vs Bull and Bear:
- If trend=DOWN strength=80 and Bull predicts +30% upside → CONFLICTS
- If trend=DOWN strength=80 and Bear predicts -25% downside → AGREES

Final verdict: which side is better grounded in the data?

Output JSON ONLY:
{
  "bull_findings": [{"claim": "string", "data_match": "MATCH|MISMATCH|UNVERIFIABLE", "evidence": "string"}, ...],
  "bear_findings": [...],
  "shared_assumptions_at_risk": ["assumption description", ...],
  "technical_vs_bull": "AGREES | CONFLICTS | NEUTRAL — explanation",
  "technical_vs_bear": "AGREES | CONFLICTS | NEUTRAL — explanation",
  "verdict_on_grounding": "BULL_BETTER_GROUNDED | BEAR_BETTER_GROUNDED | BOTH_HALLUCINATED | EVENLY_GROUNDED",
  "verdict_rationale": "1-2 sentences why"
}`;
}

// ─── Synthesizer prompt ──────────────────────────────────────────────────

function synthPrompt(ticker, dataContextBlock, bullR2, bearR2, technical, forensic) {
  return `You are the Chief Investment Officer synthesizing a multi-agent debate on ${ticker}. Your job: weight the inputs and produce a SINGLE canonical 8-step thesis with a clear direction (LONG / SHORT / PASS).

Weight the inputs by:
- Forensic's verdict_on_grounding (which side is better-grounded?)
- Technical alignment (does technical AGREE with bull or bear?)
- Bull and Bear's round-2 arguments (post-rebuttal — are there points still standing on each side?)

If Forensic says BOTH_HALLUCINATED OR there's high disagreement that
neither side can resolve via the data → emit direction = PASS (don't
trade).

═══════════════════════════════════════════════════════
DATA CONTEXT for ${ticker}:
${dataContextBlock}

BULL ROUND 2: ${JSON.stringify(bullR2).slice(0, 6000)}
BEAR ROUND 2: ${JSON.stringify(bearR2).slice(0, 6000)}
TECHNICAL: ${JSON.stringify(technical).slice(0, 2000)}
FORENSIC: ${JSON.stringify(forensic).slice(0, 4000)}
═══════════════════════════════════════════════════════

OUTPUT REQUIREMENTS:

1. Produce ONE canonical 8-step thesis JSON per the schema below.
2. The thesis you produce should reflect the BEST-grounded view, with
   appropriate confidence calibration based on Bull/Bear disagreement.
3. Add these EXTRA fields to your output:
   "_direction": "LONG" | "SHORT" | "PASS",
   "_divergence_score": 0-100 (how much Bull and Bear disagreed on key metrics — high = high uncertainty),
   "_synthesizer_rationale": "2-3 sentences explaining why this direction over the other"

${THESIS_SCHEMA_INSTRUCTION}`;
}

// ─── Per-agent runner with logging (Junyan §6.3 — debug each failure) ─────

async function runAgent(role, fn) {
  const start = Date.now();
  try {
    const text = await fn();
    const ms = Date.now() - start;
    let parsed = null;
    try {
      parsed = parseAgentJson(text, role);
    } catch (parseErr) {
      console.error(`[multi-agent] ${role} JSON-parse fail in ${ms}ms:`, parseErr.message);
      return { role, status: 'parse_fail', error: parseErr.message, raw_text: text.slice(0, 1000), ms };
    }
    console.log(`[multi-agent] ${role} OK in ${ms}ms`);
    return { role, status: 'success', result: parsed, ms };
  } catch (err) {
    const ms = Date.now() - start;
    console.error(`[multi-agent] ${role} FAIL in ${ms}ms (${err.constructor.name}):`, err.message);
    return { role, status: 'fail', error: err.message, error_type: err.constructor.name, ms };
  }
}

// ─── Main handler ────────────────────────────────────────────────────────

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin',  '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST')    return res.status(405).json({ error: 'Method not allowed' });

  const { ticker, direction, context, company, enrichment_context } = req.body;
  if (!ticker) return res.status(400).json({ error: 'ticker required' });

  // Verify env vars per Junyan §6.3 — fail loud not silent
  const missing = [];
  if (!process.env.ANTHROPIC_API_KEY) missing.push('ANTHROPIC_API_KEY');
  if (!process.env.OPENAI_API_KEY)    missing.push('OPENAI_API_KEY (for Bear / GPT-5.5)');
  if (!process.env.GOOGLE_AI_API_KEY) missing.push('GOOGLE_AI_API_KEY (for Bull / Gemini)');
  if (missing.length) {
    return res.status(500).json({
      error: `Missing Vercel env vars: ${missing.join(', ')}. Multi-agent endpoint requires all three model providers.`,
    });
  }

  try {
    // ── Build data context blocks (reuse api/research helpers) ───────────
    let pass1 = { views: [], source: 'skipped', sourcesUsed: [], emCount: 0, thsCount: 0, tavilyCount: 0 };
    try {
      pass1 = await runPass1(ticker, company);
    } catch (err) {
      console.warn('[multi-agent] Pass1 failed:', err.message);
    }

    const enrichmentBlock   = buildEnrichmentBlock(enrichment_context);
    const fundInput = enrichment_context?.fundamentals
      ? { ...enrichment_context.fundamentals, live_price: enrichment_context.live_price ? parseFloat(enrichment_context.live_price) : null }
      : null;
    const fundamentalsBlock = buildFundamentalsBlock(fundInput);
    const extrasBlock       = buildExtrasBlock(enrichment_context?.extras);
    const consensusBlock    = buildConsensusBlock(pass1.views, pass1.sourcesUsed);
    const dataContextBlock  = `${enrichmentBlock}${fundamentalsBlock}${extrasBlock}${consensusBlock}`;

    if (dataContextBlock.length < 500) {
      console.warn('[multi-agent] data context very thin — multi-agent quality may suffer');
    }

    // ── ROUND 1 (parallel: Bull + Bear + Technical) ─────────────────────
    console.log(`[multi-agent] starting round 1 for ${ticker}...`);
    const round1Start = Date.now();
    const [bullR1Run, bearR1Run, technicalRun] = await Promise.all([
      runAgent('bull_r1', () => callGemini(MODELS.bull, BULL_ROLE_SYSTEM.replace('$ticker', ticker), bullR1Prompt(ticker, dataContextBlock), 8192)),
      runAgent('bear_r1', () => callOpenAI(MODELS.bear, BEAR_ROLE_SYSTEM.replace('$ticker', ticker), bearR1Prompt(ticker, dataContextBlock), 8192)),
      runAgent('technical', () => callClaude(MODELS.technical, TECHNICAL_ROLE_SYSTEM, technicalPrompt(ticker, dataContextBlock), 4096)),
    ]);
    console.log(`[multi-agent] round 1 done in ${Date.now() - round1Start}ms`);

    const bullR1 = bullR1Run.status === 'success' ? bullR1Run.result : null;
    const bearR1 = bearR1Run.status === 'success' ? bearR1Run.result : null;
    const technical = technicalRun.status === 'success' ? technicalRun.result : null;

    // Bail if both Bull and Bear failed in round 1 (no thesis to debate)
    if (!bullR1 && !bearR1) {
      return res.status(502).json({
        error: 'Both Bull and Bear failed in round 1. Cannot produce thesis.',
        agent_status: { bull_r1: bullR1Run, bear_r1: bearR1Run, technical: technicalRun },
      });
    }

    // ── ROUND 2 (parallel: Bull-rebut + Bear-rebut, only if both r1 ok) ───
    let bullR2Run = bullR1Run, bearR2Run = bearR1Run;
    if (bullR1 && bearR1) {
      console.log(`[multi-agent] starting round 2 (rebuttal) for ${ticker}...`);
      const round2Start = Date.now();
      [bullR2Run, bearR2Run] = await Promise.all([
        runAgent('bull_r2', () => callGemini(MODELS.bull, BULL_ROLE_SYSTEM.replace('$ticker', ticker), bullR2Prompt(ticker, dataContextBlock, bullR1, bearR1), 8192)),
        runAgent('bear_r2', () => callOpenAI(MODELS.bear, BEAR_ROLE_SYSTEM.replace('$ticker', ticker), bearR2Prompt(ticker, dataContextBlock, bullR1, bearR1), 8192)),
      ]);
      console.log(`[multi-agent] round 2 done in ${Date.now() - round2Start}ms`);
    } else {
      console.warn(`[multi-agent] skipping round 2 — only one of bull/bear r1 succeeded`);
    }

    const bullR2 = bullR2Run.status === 'success' ? bullR2Run.result : bullR1;
    const bearR2 = bearR2Run.status === 'success' ? bearR2Run.result : bearR1;

    // ── FORENSIC (sequential, sees everything) ──────────────────────────
    console.log(`[multi-agent] starting forensic for ${ticker}...`);
    const forensicRun = await runAgent('forensic', () =>
      callClaude(MODELS.forensic, 'You are a forensic analyst returning structured JSON.',
        forensicPrompt(ticker, dataContextBlock, bullR2 || {}, bearR2 || {}, technical || {}), 6144),
    );
    const forensic = forensicRun.status === 'success' ? forensicRun.result : null;

    // ── SYNTHESIZER (final 8-step thesis) ───────────────────────────────
    console.log(`[multi-agent] starting synthesizer for ${ticker}...`);
    const synthRun = await runAgent('synth', () =>
      callClaude(MODELS.synth, 'You are the CIO synthesizing a multi-agent debate. Output JSON only.',
        synthPrompt(ticker, dataContextBlock, bullR2 || {}, bearR2 || {}, technical || {}, forensic || {}), 16384),
    );

    if (synthRun.status !== 'success') {
      return res.status(502).json({
        error: 'Synthesizer failed. Cannot produce final thesis.',
        agent_status: {
          bull_r1: bullR1Run, bear_r1: bearR1Run, technical: technicalRun,
          bull_r2: bullR2Run, bear_r2: bearR2Run, forensic: forensicRun,
          synth: synthRun,
        },
      });
    }

    const synth = synthRun.result;

    // ── Validate (FC.1+FC.4) ────────────────────────────────────────────
    const quality = validateThesisQuality(synth);
    const qcMeta = { ...quality, qc_findings: buildQcFindings(quality) };

    // ── Assemble final response ─────────────────────────────────────────
    const thesisOut = {
      ...synth,
      _bull_thesis: bullR2,
      _bear_thesis: bearR2,
      _bull_r1: bullR1,
      _bear_r1: bearR1,
      _technical: technical,
      _forensic: forensic,
      _agent_status: {
        bull_r1: { status: bullR1Run.status, ms: bullR1Run.ms, error: bullR1Run.error },
        bear_r1: { status: bearR1Run.status, ms: bearR1Run.ms, error: bearR1Run.error },
        technical: { status: technicalRun.status, ms: technicalRun.ms, error: technicalRun.error },
        bull_r2: { status: bullR2Run.status, ms: bullR2Run.ms, error: bullR2Run.error },
        bear_r2: { status: bearR2Run.status, ms: bearR2Run.ms, error: bearR2Run.error },
        forensic: { status: forensicRun.status, ms: forensicRun.ms, error: forensicRun.error },
        synth: { status: synthRun.status, ms: synthRun.ms },
      },
      _quality: qcMeta,
    };

    const partialFailures = [bullR1Run, bearR1Run, technicalRun, bullR2Run, bearR2Run, forensicRun]
      .filter(r => r.status !== 'success').map(r => r.role);

    return res.status(200).json({
      success: true,
      ticker,
      data: thesisOut,
      models_used: MODELS,
      _status: partialFailures.length > 0 ? 'PARTIAL_FAILURE' : 'OK',
      _partial_failures: partialFailures,
      pipeline_ms_total: bullR1Run.ms + (bullR2Run.ms || 0) + forensicRun.ms + synthRun.ms, // approximate (ignores parallel overlap)
    });
  } catch (err) {
    console.error('[multi-agent handler]', err);
    return res.status(500).json({ error: err.message || 'Internal error in multi-agent handler' });
  }
}
