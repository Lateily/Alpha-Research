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
  // GPT-5.x and newer require `max_completion_tokens` instead of `max_tokens`.
  // GPT-4.x still accepts `max_tokens`. Detect by model name prefix and route.
  // 2026-05-08: GPT-5.5 returned 400 "Unsupported parameter: 'max_tokens'"
  // confirming the breaking change. Sending both for forward-compat is NOT
  // allowed by OpenAI API ("only one of max_tokens or max_completion_tokens").
  // GPT-5.x and o-series have additional API restrictions:
  // - max_completion_tokens (not max_tokens)
  // - temperature MUST be default (1); 0.6 → 400 "unsupported_value"
  // - top_p / presence_penalty / frequency_penalty likely similar — omit for safety
  // Older GPT-4.x and 3.5 still accept the legacy parameters.
  const isModernModel = /^(gpt-5|gpt-6|o[0-9])/i.test(model);
  const tokenField = isModernModel ? 'max_completion_tokens' : 'max_tokens';

  const body = {
    model,
    messages: [
      { role: 'system', content: system },
      { role: 'user', content: user },
    ],
    [tokenField]: maxTokens,
  };

  // Only set temperature for legacy models (GPT-5+ rejects non-default values)
  if (!isModernModel) {
    body.temperature = 0.6;
  }

  const r = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${process.env.OPENAI_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
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
  "step_5_proves_right_if": ["MECHANIZED conditions 3-5 — each a single string in the EXACT template: '<metric> <op ≥/≤/>/</=> <numeric threshold + unit> @ <named catalyst/disclosure event> | source: <exact doc + line/field, e.g. 2026 H1 报告 合并利润表 营业成本> | if_not_disclosed: INSUFFICIENT_DISCLOSURE'"],
  "step_6_proves_wrong_if": ["MECHANIZED conditions 3-5 — same template as step_5. Soft conditions are rejected (see FALSIFIABILITY DIRECTIVE)"],
  "step_7_variant_view": {
    "variant_view_one_sentence": "Market believes X → We believe Y → Mechanism is Z",
    "core_causal_link": {
      "link_sentence": "the ONE if-false-thesis-dies causal step",
      "evidence_tier": "E1:direct | E2:proxy | E3:narrative | E4:crowding",
      "tier_justification": "which exact DATA CONTEXT line supports this tier; if not E1, explicitly say what primary data would be needed to make it E1"
    },
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

═══════════════════════════════════════════════════════════════════════
FALSIFIABILITY DIRECTIVE (KR3 — Junyan verdict 2026-05-15) — applies to step_5 & step_6
═══════════════════════════════════════════════════════════════════════
Junyan's BYD critique: conditions like "overseas sales continued
sequential growth consistent with broker language" / "price sustainably
breaks and holds" / "May/June export sales maintain Q1 momentum" are
TOO SOFT — at the catalyst print nobody can objectively say if they
triggered. EVERY step_5 / step_6 condition MUST be judgeable, at the
named disclosure event, into EXACTLY one of:
  TRIGGERED | NOT_TRIGGERED | INSUFFICIENT_DISCLOSURE
(INSUFFICIENT_DISCLOSURE = the company did not disclose the metric at
that event, so the condition is unjudgeable — distinct from a triggered
or not-triggered verdict, and itself a learning signal.)

Each condition string MUST contain, in order:
  1. a SPECIFIC metric (e.g. "2026 H1 consolidated gross margin",
     "2026 H1 汽车业务 segment revenue YoY", NOT "momentum"/"strength")
  2. an explicit operator + NUMERIC threshold with unit
     (≥17.2% / <15% / >+30% YoY / ≤ ¥95 — NEVER "sustainably"/"strong"/
     "consistent with broker language"/"maintains")
  3. "@ <named catalyst/disclosure event>" (e.g. "@ 2026 H1 报告 2026-08-28")
  4. "| source: <exact statement + line/field>" naming WHERE the number
     will be read (e.g. "合并利润表: 营业收入/营业成本"; "经营数据公告: 海外销量")
  5. "| if_not_disclosed: INSUFFICIENT_DISCLOSURE"
A condition that cannot be written this way is NOT falsifiable — drop it
or replace it. Vague conditions will be rejected in review.

Return ONLY valid JSON, no commentary outside.`;

// ─── Round 1 prompts ──────────────────────────────────────────────────────

// ════════════════════════════════════════════════════════════════════
// CONTRARIAN VIEW REQUIREMENTS — Junyan §6 directive 2026-05-08
// ════════════════════════════════════════════════════════════════════
// After hand-reviewing the 2026-05-08 BYD multi-agent thesis, Junyan
// flagged: theses are "valuation-pitch dressed as research" — they
// compare numbers (P/E low → cheap → upside) but never articulate
// WHY consensus is wrong via business mechanism. Brokers/inst surveys/
// 龙虎榜 detail are now in the data context (Phase 1 of the fix); this
// instruction tells agents to USE them.
const CONTRARIAN_VIEW_REQUIREMENT = `
═══════════════════════════════════════════════════════════════════════
CONTRARIAN VIEW REQUIREMENT — non-negotiable, applies to step_3_evidence.contrarian_view.our_variant + step_2_mechanism.mechanism_chain
═══════════════════════════════════════════════════════════════════════

Your variant view MUST articulate a BUSINESS MECHANISM, not a VALUATION OBSERVATION.

THE FOLLOWING ARE NOT ACCEPTABLE AS A CONTRARIAN VIEW:
  ✗ "P/E is low so pessimism is priced in"
  ✗ "DCF model says it's cheap"
  ✗ "Stock is at 55% of 52W range"
  ✗ "Forward multiple discount reflects priced-in normalization"
  ✗ "The market is anchored to lagging indicators"
  ✗ Any argument whose ENTIRE CHAIN reduces to "valuation is attractive"

WHAT THE CONTRARIAN VIEW MUST CONTAIN:
  ✓ A SPECIFIC competitive/regulatory/capacity/demand/management mechanism that the market has under-modeled
  ✓ EXPLICIT reference to specific data points in your data context — broker reports (TUSHARE — BROKER RECOMMENDATIONS), institutional research visits (TUSHARE — INSTITUTIONAL RESEARCH VISITS), 龙虎榜 activity, holder transactions, news, management commentary
  ✓ A timeline for when the mechanism plays out + which print/event would prove it true / false
  ✓ The variant view sentence must follow the form:
      "Market believes X (because of Y consensus narrative) → We believe Z (specific mechanism: e.g., 'Q1 海外销量+85% per 华创证券 report contradicts the bear's tariff thesis') → This is unpriced because [specific data signal]"

EXAMPLES OF VALID BUSINESS MECHANISMS (illustrative):
  ✓ "Market priced in 关税 -25% impact on EU sales BUT 华创证券 Q1 review reports 海外销量增长势头强劲, suggesting 'tariff already absorbed' is a real Q1 datapoint"
  ✓ "Inst research visits in last 30d (Value Partners + 国寿资产) show 持续 buy-side 关注 vs sell-side 'broken growth' narrative — this divergence between buy-side and sell-side narratives is signal"
  ✓ "Broker target_price 119.2 (华创证券 强推) reflects 海外销量 driver while consensus avg 119.55 reflects domestic stagnation — variance suggests domestic-vs-overseas thesis split"
  ✓ "Mgmt commentary in 4-09 inst survey emphasized 国内门店扩张 to 1500, vs analyst notes focusing on EU tariffs — mgmt's local-China narrative is unpriced"

IF YOU CANNOT ARTICULATE A BUSINESS MECHANISM FROM THE DATA CONTEXT:
  Emit \`step_7_variant_view.variant_view_one_sentence\` = "INSUFFICIENT_BUSINESS_SIGNAL — data context contains valuation arrows + technical data but no broker/inst/news narrative supporting a specific contrarian mechanism. Recommend deferring thesis pending news/sector context."
  Set \`step_7_variant_view.expected_pnl_asymmetry.reward_to_risk\` = "PASS — no edge"
  This is a VALID and PREFERRED output over a forced valuation-only pitch.

CHECK BEFORE EMITTING JSON:
  1. Does my mechanism_chain mention at least ONE specific broker name + report title from BROKER RECOMMENDATIONS section? (If no, mechanism is just data-comparison, not narrative-grounded.)
  2. Does my our_variant cite a specific event/announcement/visit from inst_research, lhb, holdertrade, OR news?
  3. Could my mechanism_chain be applied to ANY cheap-looking stock by swapping ticker symbols? (If yes, it's generic — rewrite with ticker-specific business specifics.)
═══════════════════════════════════════════════════════════════════════
`;

const BULL_ROLE_SYSTEM = `You are the LONG-thesis advocate at a hedge fund. Your role is to build the strongest possible BULLISH case for ${'$ticker'} using the data context provided. You argue LONG. You may NOT argue SHORT — that's a different agent's job.

Discipline:
- Every numeric claim must be grounded in the data context (cite the field where possible)
- If the data context lacks a number, write "not available in our data" not a guess
- catalyst_date must be FUTURE relative to today (data context "TEMPORAL CONTEXT" line)
- Be specific with R/R numbers, target multiples, and falsifiability conditions
${CONTRARIAN_VIEW_REQUIREMENT}

Follow THESIS_PROTOCOL v2 — 8 steps. Output JSON per schema.`;

const BEAR_ROLE_SYSTEM = `You are the SHORT-thesis advocate at a hedge fund. Your role is to build the strongest possible BEARISH case for ${'$ticker'} using the data context provided. You argue SHORT (or NEUTRAL if data genuinely doesn't support a short — but bias toward identifying contrarian short angle).

Discipline:
- Every numeric claim must be grounded in the data context (cite the field where possible)
- If the data context lacks a number, write "not available in our data" not a guess
- catalyst_date must be FUTURE relative to today
- Hunt for: accounting red flags, competitive threats, valuation excess, narrative crowding
${CONTRARIAN_VIEW_REQUIREMENT}

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

// Hard directive that forces the model to cite specific narrative data.
// Inserted into every Bull/Bear/Synth task prompt. Without this, LLMs
// (especially Gemini) tend to ignore the rich Tushare sections and
// default to valuation-arithmetic. Junyan §6 directive 2026-05-08.
const HARD_CITATION_DIRECTIVE = `
═══════════════════════════════════════════════════════
HARD CITATION RULES — your output WILL BE REJECTED if violated
═══════════════════════════════════════════════════════

1. step_2_mechanism.mechanism_chain MUST quote at least 2 of the
   following from the DATA CONTEXT above:
   (a) A specific report title from "TUSHARE — BROKER RECOMMENDATIONS"
       (e.g., "华创证券 '比亚迪 26Q1 海外销量增长势头强劲'")
   (b) An institutional visit from "TUSHARE — INSTITUTIONAL RESEARCH VISITS"
       (e.g., "Value Partners 4-09 phone survey")
   (c) A 龙虎榜 event from "TUSHARE — 龙虎榜 LHB APPEARANCES"
   (d) A holder transaction from "TUSHARE — INSIDER/大股东 ACTIVITY"
   (e) A specific news event from "RECENT NEWS" (last 5-7 days, source-tagged)
   (f) A peer comparison from "PEER CROSS-SECTION COMPARISON" (e.g.,
       "BYD GM 17.2% vs 175.HK Geely GM 13.5% = +370bps integration premium")

2. step_3_evidence.contrarian_view.our_variant MUST reference at least
   ONE specific item from (a)-(e). Format:
   "Per [broker name] [report date] '[exact title quote]', [business
   mechanism]. This contradicts the consensus narrative because
   [specific reason citing data context]."

3. If TUSHARE — BROKER RECOMMENDATIONS / INSTITUTIONAL RESEARCH VISITS /
   龙虎榜 / news sections are EMPTY for this ticker, emit:
     variant_view_one_sentence = "INSUFFICIENT_NARRATIVE_DATA — data
     context lacks broker reports, inst visits, 龙虎榜, and news.
     Cannot articulate a business-mechanism contrarian view; only
     valuation arithmetic available which is insufficient. PASS."
   This is a VALID and PREFERRED output.

4. Forbidden mechanism_chain content (these will fail review):
   ✗ "Market is anchored to lagging indicators" (generic)
   ✗ "DCF model says cheap" (valuation arithmetic)
   ✗ "Forward P/E discount reflects priced-in normalization" (circular)
   ✗ "55% of 52W range" (technical, not contrarian view)
   ✗ Any chain that could apply to ANY cheap-looking stock

5. Required mechanism_chain content (these pass review):
   ✓ "Per 华创证券 2026-05-07 report '海外销量增长势头强劲', Q1 export
     volume +85% suggests EU tariff already absorbed in Q4 2025
     pricing — bear's tariff thesis is reading lagging data"
   ✓ "Inst research visits in last 30d (Value Partners + 国寿资产)
     concentrated questions on 国内门店 expansion to 1500 by FY2026,
     vs sell-side focus on EU tariff — buy-side is forward-looking,
     sell-side anchored on Q1 lagging concern"
═══════════════════════════════════════════════════════

`;

// ════════════════════════════════════════════════════════════════════
// EVIDENCE TIERING DIRECTIVE — Junyan verdict 2026-05-15 (KR2)
// ════════════════════════════════════════════════════════════════════
// Junyan's BYD critique: the thesis IMPLIED "vertical integration →
// export margin uplift" was proven, when the data only showed
// co-occurrence (company-level GM up + exports up) — no region-level
// export GM. And ~half the citations proved "everyone is watching this
// story" (crowding), not "we understood earlier than the market" (edge).
// This directive forces every claim to wear its evidence strength on
// its sleeve so a PROXY/NARRATIVE/CROWDING claim can never masquerade
// as a PROVEN one.
const EVIDENCE_TIERING_DIRECTIVE = `
═══════════════════════════════════════════════════════════════════════
EVIDENCE TIERING — MANDATORY inline tag on EVERY claim. Output rejected if missing.
═══════════════════════════════════════════════════════════════════════

Tag EVERY item in step_2_mechanism.mechanism_chain, step_3_evidence
(evidence_quantitative, evidence_qualitative), and
step_3_evidence.contrarian_view.our_variant with ONE prefix:

  [E1:direct]  — the DATA CONTEXT contains the EXACT primary metric that
                 proves this specific claim. e.g. SEGMENT ECONOMICS shows
                 true_gm overseas 22% vs domestic 16% → "exports are
                 higher-margin" is [E1:direct].
  [E2:proxy]   — only an INDIRECT / AGGREGATE / co-occurrence number
                 exists; the causal step is INFERRED not measured. e.g.
                 "company-level GM rose AND exports rose, therefore
                 exports are margin-accretive" is [E2:proxy] — the link
                 is not measured at segment level.
  [E3:narrative] — a broker / analyst / news report ASSERTS it but we
                 hold no primary data confirming it. e.g. "国联民生 says
                 Q1 GM improved on export mix" with no segment print.
  [E4:crowding]  — inst-visit / 龙虎榜 / momentum / target-price-cluster
                 signal showing ATTENTION or CONSENSUS, not a fundamental
                 mechanism. "Value Partners + 高盛 visited" is [E4:crowding]
                 — it proves the story is watched, NOT that we are early.

HARD RULES:
1. The SINGLE most load-bearing link of your variant view — the one
   sentence that, if false, kills the thesis — name it explicitly in
   step_7_variant_view as "core_causal_link" and state its tier.
2. If core_causal_link is [E2]/[E3]/[E4] you MUST NOT phrase it as
   established fact. Use "inferred", "not yet measured", "asserted by
   X but unconfirmed in our data". Stating a non-E1 link as proven is
   the exact overselling failure this directive exists to kill.
3. A pile of [E3]/[E4] does NOT sum to [E1]. Ten brokers repeating the
   same story is still [E3] (consensus), not direct proof — and is
   itself evidence the edge may already be priced.
4. Citations: when you cite a broker/inst/news item, ask "does this
   ESTABLISH the mechanism (→ E1/E2) or merely show the crowd is
   watching it (→ E3/E4)?" Tag honestly. Junyan will check this.
═══════════════════════════════════════════════════════════════════════
`;

function bullR1Prompt(ticker, dataContextBlock) {
  return `${BULL_ROLE_SYSTEM.replace('$ticker', ticker)}

═══════════════════════════════════════════════════════
DATA CONTEXT (use this — don't fabricate)
═══════════════════════════════════════════════════════
${dataContextBlock}

${HARD_CITATION_DIRECTIVE}
${EVIDENCE_TIERING_DIRECTIVE}

═══════════════════════════════════════════════════════
TASK: Produce the strongest LONG thesis for ${ticker}.
═══════════════════════════════════════════════════════

Before emitting JSON, INTERNALLY CHECK:
  - Does mechanism_chain[0] or [1] cite a specific broker name + report title?
  - Does our_variant reference an institutional visit OR specific business event?
  - If NO to either → revise OR emit INSUFFICIENT_NARRATIVE_DATA per rule 3.

${THESIS_SCHEMA_INSTRUCTION}`;
}

function bearR1Prompt(ticker, dataContextBlock) {
  return `${BEAR_ROLE_SYSTEM.replace('$ticker', ticker)}

═══════════════════════════════════════════════════════
DATA CONTEXT (use this — don't fabricate)
═══════════════════════════════════════════════════════
${dataContextBlock}

${HARD_CITATION_DIRECTIVE}
${EVIDENCE_TIERING_DIRECTIVE}

═══════════════════════════════════════════════════════
TASK: Produce the strongest SHORT thesis for ${ticker}.
═══════════════════════════════════════════════════════

Before emitting JSON, INTERNALLY CHECK:
  - Does mechanism_chain[0] or [1] cite a specific broker name + report title?
  - Does our_variant reference an institutional visit OR specific business event?
  - If NO to either → revise OR emit INSUFFICIENT_NARRATIVE_DATA per rule 3.

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

${HARD_CITATION_DIRECTIVE}
${EVIDENCE_TIERING_DIRECTIVE}

CHECK BEFORE EMITTING: your round-2 mechanism_chain MUST cite specific
broker reports / inst visits / 龙虎榜 / news from data context (rule 1),
AND every claim must carry its [E1/E2/E3/E4] evidence tier. If round 1
didn't, this is your chance to fix it — especially: is your
core_causal_link really [E1:direct], or were you overselling an [E2]?

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

${HARD_CITATION_DIRECTIVE}
${EVIDENCE_TIERING_DIRECTIVE}

CHECK BEFORE EMITTING: your round-2 mechanism_chain MUST cite specific
broker reports / inst visits / 龙虎榜 / news from data context (rule 1),
AND every claim must carry its [E1/E2/E3/E4] evidence tier. If round 1
didn't, this is your chance to fix it — especially: is your
core_causal_link really [E1:direct], or were you overselling an [E2]?

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
  "bull_contrarian_quality": "BUSINESS_MECHANISM | VALUATION_ONLY | GENERIC — does Bull cite specific broker reports / inst visits / 龙虎榜 / news / mgmt commentary, or just compare numbers?",
  "bear_contrarian_quality": "BUSINESS_MECHANISM | VALUATION_ONLY | GENERIC",
  "bull_core_link_tier_audit": {
    "agent_self_tier": "the evidence_tier Bull assigned its core_causal_link",
    "your_independent_tier": "E1:direct | E2:proxy | E3:narrative | E4:crowding — YOUR call from the data context, ignoring Bull's self-rating",
    "verdict": "AGREE | OVERSTATED (claimed stronger than data supports — the overselling failure) | UNDERSTATED",
    "evidence": "which exact DATA CONTEXT line justifies your tier; if SEGMENT ECONOMICS shows the gap is PROXY/BLENDED, an export-margin core link claimed [E1] is OVERSTATED"
  },
  "bear_core_link_tier_audit": { "...same shape as bull..." },
  "citations_edge_vs_crowding": "of the broker/inst/news items each side cites, estimate how many ESTABLISH the mechanism (edge) vs merely show the crowd is watching (crowding/consensus). Junyan: 'many citations prove everyone is watching this story, not that we understood earlier.'",
  "verdict_on_grounding": "BULL_BETTER_GROUNDED | BEAR_BETTER_GROUNDED | BOTH_HALLUCINATED | EVENLY_GROUNDED | BOTH_VALUATION_ONLY | CORE_LINK_OVERSTATED_BOTH",
  "verdict_rationale": "1-2 sentences why"
}

NOTE: BOTH_VALUATION_ONLY — neither side articulated a business-level
contrarian mechanism (both essentially "P/E low so cheap"). Signals PASS.
NOTE: CORE_LINK_OVERSTATED_BOTH — both sides' load-bearing causal link
is really E2/E3/E4 but was asserted as proven. This is the exact BYD
failure mode (Junyan 2026-05-15). Signals Synthesizer should PASS or
heavily down-confidence + restate the link as inferred-not-proven.`;
}

// ─── Synthesizer prompt ──────────────────────────────────────────────────

function synthPrompt(ticker, dataContextBlock, bullR2, bearR2, technical, forensic) {
  return `You are the Chief Investment Officer synthesizing a multi-agent debate on ${ticker}. Your job: weight the inputs and produce a SINGLE canonical 8-step thesis with a clear direction (LONG / SHORT / PASS).

Weight the inputs by:
- Forensic's verdict_on_grounding (which side is better-grounded?)
- Technical alignment (does technical AGREE with bull or bear?)
- Bull and Bear's round-2 arguments (post-rebuttal — are there points still standing on each side?)
- BUSINESS-MECHANISM RIGOR: does either side's variant view cite specific broker reports, inst research visits, 龙虎榜 activity, mgmt commentary, OR is it pure valuation arithmetic? Side with stronger business-mechanism wins (per CONTRARIAN VIEW REQUIREMENT in role prompts).

CORE-LINK DECISION GATE (KR2 + Path-B recalibration — Junyan 2026-05-16):
read Forensic's bull/bear_core_link_tier_audit. First distinguish TWO
situations that are NOT the same — do not conflate them:

  ① OVERSTATEMENT (the BYD 5/15 failure — forbidden): the agent claimed
    [E1] but the data only supports [E2]/[E3]/[E4] — it misrepresented
    evidence strength. Dishonest. You MUST restate the link at its true
    tier + lower confidence, OR (if nothing tradeable remains) PASS.
    You may NEVER silently keep an overstated [E1] phrasing.

  ② HONEST FORWARD INFERENCE (legitimate, tradeable): the agent
    CORRECTLY labels the link [E2:proxy] because it is a FORWARD claim
    not measurable until a future print — but it rests on an [E1:direct]
    historical/structural base. This is NOT overstatement. Investment
    research means taking positions BEFORE the catalyst; requiring the
    forward leg to already be [E1] would make this a post-event
    verification engine, not a pre-catalyst research engine.

A correctly-labeled [E2:proxy] FORWARD core link does NOT force PASS.
Emit a tradeable LONG/SHORT (TIER-SCALED) when ALL hold:
  (a) the historical/structural BASE is [E1:direct] AND it measures the
      SAME causal mechanism the forward leg claims (e.g. BYD 2025
      overseas GM 19.46% vs domestic 16.66% = +280bps, segment-disclosed
      — the base IS overseas-margin, the forward leg IS overseas-margin
      persistence: same mechanism, future H1 segment disclosure directly
      re-measures it);
  (b) the forward uncertainty is EXPLICITLY labeled [E2:proxy] — the
      unknown is named, not hidden (no overstatement);
  (c) step_5/step_6 KR3 triggers are mechanized + source-bound (a
      specific named future print resolves the forward leg);
  (d) reward:risk is favorable (asymmetric payoff toward the thesis);
  (e) sizing is TIER-SCALED: position_sizing_curve = starter/small size
      NOW, scale up ONLY after the [E1] confirmation print.
If ANY of (a)-(e) fails → PASS with the correct _pass_reason.

RULE X (Junyan 2026-05-17 ruling — boundary condition exposed by Geely):
Peer-relative valuation, peer-relative revenue growth, peer-relative
ROE, or peer-relative margin MAY be [E1:direct] FACTS, but they do NOT
qualify as the [E1:direct] STRUCTURAL BASE for E2-forward tradeability
UNLESS the SAME forward causal mechanism can be DIRECTLY CONFIRMED by
future issuer disclosure. If the proposed mechanism is
segment/mix/brand/powertrain-driven and the issuer does NOT disclose
that segment/mix economics (so the forward causal claim can never be
re-measured — only company-level co-movement can), this is a
valuation/peer-relative thesis smuggled in as a business-mechanism
thesis → emit PASS / INSUFFICIENT_DATA. (Geely: Rev/ROE/P/E vs BYD are
E1 facts, but the hybrid-mix causal claim is unconfirmable because
segment economics are not_available → PASS, NOT tradeable. BYD passes
Rule X because overseas-segment GM IS disclosed and re-measured at H1.)

HARD CONSTRAINT — for such a tradeable-but-capped thesis your
_synthesizer_rationale AND step_7_variant_view MUST state, in substance:
  "Tradeable, but not proven. Historical base is [E1:direct] (<what>);
   forward persistence is [E2:proxy] (<what>); size is capped until the
   <named H1/Q2 print> confirms."
That is the target output: honest uncertainty + pre-catalyst position
sizing — NEITHER a pretty-packaged false [E1] NOR a reflexive PASS.

PASS TAXONOMY (KR4 — Junyan 2026-05-15): if _direction = PASS you MUST
also set "_pass_reason" to EXACTLY one of, and fill "_pass_reason_detail":
  • NO_EDGE_DESPITE_DATA — data context is adequate, both sides argued
    it, but no asymmetric edge exists (efficiently priced). Forensic
    BOTH_VALUATION_ONLY with full data → this.
  • INSUFFICIENT_DATA — our data packet lacks the business signal needed
    to judge (missing broker/inst/news/segment). NOT "market has no
    edge" — WE cannot see one. (Geely 175.HK is THIS, not no-edge —
    Junyan's explicit correction. Upstream INSUFFICIENT_BUSINESS_SIGNAL
    / INSUFFICIENT_NARRATIVE_DATA map here.)
  • BALANCED_RISK_REWARD — a real mechanism exists but reward:risk is
    inadequate (< 2:1) / symmetric. (大参林-type: thesis fine, R:R 1.5:1.)
  • CATALYST_NOT_YET_OBSERVABLE — mechanism plausible but there is NO
    [E1:direct] structural/historical BASE to act on yet, AND the
    deciding observable has not printed. (Innolight-type: 1.6T margin
    claim is [E3:narrative] with no E1 base.) Path-B GUARD: do NOT use
    this merely because the FORWARD leg is [E2] — if an [E1] base exists
    + (a)-(e) of the CORE-LINK DECISION GATE hold, that is a tradeable-
    but-capped LONG/SHORT, NOT a pass. Forward-leg-is-E2 is normal
    pre-catalyst research, not a reason to pass.
_pass_reason_detail must name the specific missing data / R:R number /
unresolved observable. "INSUFFICIENT_DATA" with no named gap is rejected.

The final thesis you produce MUST itself comply with CONTRARIAN VIEW
REQUIREMENT — your variant_view_one_sentence and step_2_mechanism.mechanism_chain
must articulate business mechanism with specific data-context references
(broker name, inst visit, news event, mgmt commentary, etc.), NOT valuation
arithmetic. If you cannot articulate this from the upstream agent outputs +
data context, emit PASS with the correct _pass_reason — that is a valid,
PREFERRED output over a forced or oversold thesis.

═══════════════════════════════════════════════════════
DATA CONTEXT for ${ticker}:
${dataContextBlock}

BULL ROUND 2: ${JSON.stringify(bullR2).slice(0, 6000)}
BEAR ROUND 2: ${JSON.stringify(bearR2).slice(0, 6000)}
TECHNICAL: ${JSON.stringify(technical).slice(0, 2000)}
FORENSIC: ${JSON.stringify(forensic).slice(0, 4000)}
═══════════════════════════════════════════════════════

${EVIDENCE_TIERING_DIRECTIVE}

OUTPUT REQUIREMENTS:

1. Produce ONE canonical 8-step thesis JSON per the schema below. Your
   step_7_variant_view.core_causal_link MUST carry an honest evidence_tier
   reconciled with Forensic's tier audit (do NOT inherit an OVERSTATED
   tier). Every mechanism_chain / evidence item carries its [E1-E4] tag.
2. The thesis you produce should reflect the BEST-grounded view, with
   core-link tier capping CONFIDENCE + SIZING, not killing direction:
   an [E2:proxy] FORWARD link with an [E1:direct] base is a tradeable-
   but-capped LONG/SHORT per the CORE-LINK DECISION GATE (starter size,
   scale on the E1 print) — NOT an automatic PASS. Only an E3/E4 core
   link with NO E1 structural base is usually a PASS.
3. Add these EXTRA fields to your output:
   "_direction": "LONG" | "SHORT" | "PASS",
   "_divergence_score": 0-100 (how much Bull and Bear disagreed on key metrics — high = high uncertainty),
   "_synthesizer_rationale": "2-3 sentences explaining why this direction over the other",
   "_evidence_profile": { "core_link_tier": "E1|E2|E3|E4", "counts": {"E1": n, "E2": n, "E3": n, "E4": n}, "overstatement_corrected": true|false (did you have to down-tier vs the winning agent's self-rating?) },
   "_pass_reason": "NO_EDGE_DESPITE_DATA | INSUFFICIENT_DATA | BALANCED_RISK_REWARD | CATALYST_NOT_YET_OBSERVABLE | null (null ONLY when _direction is LONG or SHORT)",
   "_pass_reason_detail": "specific named gap / R:R figure / unresolved observable — required when _direction = PASS, else null",
   "_conviction_state": "FULL | STARTER_CAPPED_UNTIL_E1 | null (STARTER_CAPPED_UNTIL_E1 when _direction is LONG/SHORT but core link is an honest [E2:proxy] forward on an [E1] base per the CORE-LINK DECISION GATE; FULL when core link is itself [E1:direct]; null when PASS)",
   "_tradeable_not_proven_statement": "REQUIRED when _conviction_state = STARTER_CAPPED_UNTIL_E1 — the explicit sentence: 'Tradeable, but not proven. Historical base is [E1:direct] (<what>); forward persistence is [E2:proxy] (<what>); size capped until <named H1/Q2 print> confirms.' null otherwise"

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
