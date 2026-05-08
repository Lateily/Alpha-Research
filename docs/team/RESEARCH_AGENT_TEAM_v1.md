# Research Agent Team v2 — Architecture Proposal (Junyan §6 decisions integrated)

> **Status:** v1 proposed → v2 approved (Junyan answered all 5 §6 open
> questions on 2026-05-08). Stage 1 (T-RD data loader) shipped.
> Stage 2 (multi-agent endpoint) builds against THIS spec.
> **Date:** 2026-05-08 (v1) → 2026-05-08 (v2 update)
> **Author:** T1 Claude
> **Related:** AGENT_ORCHESTRATION.md (covers code-side T1/T2/T3); this
> doc covers RESEARCH-side production. Junyan-direct ask 2026-05-08:
> "在产出报告上也需要多 agent 合作 ... 我们要搭建一个体系成熟的 agent team".

---

## v2 changes (Junyan §6 decisions)

1. **Bull/Bear see news + each other's output** — both. Junyan: "bull 跟 bear
   才是更需要看信息面的 ... 经过讨论和质疑之后的决策质量才会高". Round 2
   rebuttal pass added.
2. **Agent failure handling** — debug each failure mode rather than swallow.
   Junyan: "确保 agent fail 的原因 然后根据每次失败的原因去修复和优化".
   No silent fallback to single-agent on failure; surface the cause.
3. **Model assignments not absolute + GPT-5.5** — flexible, mix and match.
   Update GPT-4o → GPT-5.5 (released 2025-Q4 per Junyan). Default
   assignment stays as a starting point but room to swap based on what
   each model is best at empirically.
4. **NEW Technical agent (T-RT)** — Junyan: "round 2 review 那就是每一个 agent
   都全面 scan 一下 ... 分析技术面". Adds technical analyst role
   reading OHLC + chart pattern + momentum + support/resistance.
5. **Round 2 review packet integration** — packets get sections per agent
   perspective. Each section asks the agent (or a human) to do a full
   scan based on all info. Goes beyond passive template.

---

## 0. Why this exists

**Existing setup:**
- Code-side: T1 (Claude main) + T2 (Claude reviewer) + T3 (Codex codegen) + T4 (design watcher)
- Research-side: ONE LLM call per thesis (`/api/research` Pass 1 consensus + Pass 2 single-Claude generation) — no role separation, no adversarial check, no fact-grounding loop
- Existing `/api/debate.js` (Bull/Bear/Forensic) does role separation but: (a) doesn't follow 8-step thesis protocol, (b) doesn't consume our deployed data layer (Tushare/yfinance/etc.), (c) outputs verdict-summary not full thesis

**The gap:** thesis production is single-agent + ungrounded → hallucinations (price HK$715 vs actual HK$473 on 700.HK 5/5), one-sided framings, no contradiction-detection. Junyan's bullshit-detection currently catches these manually. The fact-check stack (FC.1+FC.2 shipped) catches some structurally; multi-agent + grounding closes more.

---

## 1. Architectural principle

**Separate role-specific cognition + adversarial cross-check + grounded data layer.**

| Layer | Function | Mechanism |
|---|---|---|
| Data | Load real ingested data | Python script (deterministic, no LLM) |
| Position-taking | Build the 2 strongest opposing theses | Bull + Bear LLM agents, parallel |
| Verification | Detect hallucinations, contradictions, math errors against data | Forensic LLM agent + automated FC.1/FC.2 |
| Synthesis | Weight bull/bear, decide LONG / SHORT / PASS, calibrate confidence | Synthesizer LLM (highest-tier model) |
| Attribution | Log shipped thesis for outcome tracking | Bridge-8 log_thesis.py (existing) |

No agent's output is "the" thesis until Synthesizer produces it. Bull's thesis ≠ committed, Bear's ≠ committed. Final variant is the Synthesizer's call.

---

## 2. Role spec — 6 research-side agents (5 LLM + 1 deterministic) — v2

**v2 changes vs v1:** Bull/Bear see each other in round 2; Bull/Bear
both get full data context including news; ADDED Technical Analyst
(T-RT). Now 5 LLM agents (was 3).

### T-RD — Research Data Loader (deterministic, not LLM)
**Owner:** `scripts/research_data_loader.py` (NEW)
**Input:** ticker
**Output:** structured JSON context containing:
- yahoo: live price + fundamentals + analyst targets + 52w range
- yfinance: 5y annual income / balance / cash flow (`fin_*.json`)
- ohlc: 120-day daily OHLCV (`ohlc_*.json`)
- Tushare suite (per-ticker): `chip_distribution`, `consensus_forecast`, `lhb` (龙虎榜), `quant_factors`, `inst_research`, `top_inst`, `broker_recommend`, `pledge_stat`, `restricted_shares`, `holdertrade`, `margin`, `repurchase`
- VP scores + dimensions (from `vp_snapshot.json`)
- rDCF (`rdcf_*.json`), fragility (`fragility_*.json`), persona overlay
- Sector regime
- Recent news (5d window from `flow_data.json`)

**No LLM call.** Fast (<2s). Used as input by Bull / Bear / Forensic in parallel.

**Output schema reference:** `docs/team/RESEARCH_DATA_CONTEXT_SCHEMA.md` (NEW, follows this proposal)

### T-RB — Research Bull (LLM: default Gemini 1.5 Pro, swappable)
**Owner:** `/api/research-multi` `bullPrompt(data_context)`
**Round 1 input:** T-RD output (FULL — including news) + 8-step protocol prompt
**Round 1 job:** Produce strongest **LONG** thesis using ONLY the supplied data (no training-data hallucination — explicit "if a number is not in data context, do NOT use it; instead say 'not available in our data'").
**Round 1 output:** Full 8-step JSON. Direction = LONG.
**Round 2 input:** Round 1 own output + Bear's round 1 output + same data context
**Round 2 job:** Rebuttal — defend or revise the LONG thesis after seeing Bear's strongest case. Allowed to drop to NEUTRAL if Bear's case proves decisive. Must explicitly address each of Bear's specific points.
**Round 2 output:** Updated 8-step JSON + `_rebuttal` block listing which Bear arguments were addressed and how.
**Cost estimate:** ~$0.05 round 1 + ~$0.05 round 2 = ~$0.10
**Why news included:** Junyan §6.2 — "bull 跟 bear 才是更需要看信息面的". The
information surface is exactly what bull/bear need to argue from. Forensic
already sees data; without news bull/bear miss the catalyst landscape.

### T-RBR — Research Bear (LLM: default GPT-5.5, swappable)
**Owner:** Same endpoint, `bearPrompt(data_context)`
**Model update:** GPT-4o → **GPT-5.5** (Junyan §6.4 directive 2026-05-08).
**Round 1 input/job/output:** Same as Bull but argues SHORT (or NEUTRAL if data doesn't support short — explicit "consensus is right, no edge here").
**Round 2 input:** Round 1 own output + Bull's round 1 output + same data context
**Round 2 job:** Rebut Bull. Allowed to drop to NEUTRAL if Bull's case proves decisive.
**Cost estimate:** ~$0.10 (1+1)

Bull and Bear in round 1 run in PARALLEL (Promise.allSettled).
Bull and Bear in round 2 also PARALLEL (each sees the other's round-1 output).
Independence within each round preserves adversarial value; cross-pollination
between rounds delivers Junyan's "经过讨论和质疑之后的决策质量才会高" requirement.

### T-RT — Research Technical Analyst (NEW v2, LLM: Claude Sonnet)
**Owner:** Same endpoint, `technicalPrompt(data_context)`
**Input:** T-RD output (specifically: `ohlc_recent` 60-day OHLCV +
`tushare_suite.chip_distribution` cost levels + `tushare_suite.margin`
balance trend + `tushare_suite.holdertrade` net buy/sell)
**Job:** Read pure technical signal — chart pattern, trend strength, momentum,
volume profile, support/resistance levels, chip-cost concentration, margin
trend. Position-agnostic (NOT bull/bear; just what the price/volume/chip
data say structurally).
**Output:** structured technical JSON:
```json
{
  "trend": "UP | DOWN | RANGE",
  "trend_strength": 0-100,
  "momentum": {"rsi": ..., "macd_signal": ..., "interpretation": "..."},
  "key_levels": {"support": [...], "resistance": [...]},
  "volume_profile": "expanding | contracting | normal",
  "chip_concentration": "concentrated | dispersed | uncertain",
  "margin_trend": "expanding_long | unwinding | flat",
  "technical_summary_e": "2-3 sentences summary",
  "technical_summary_z": "2-3 sentences summary"
}
```
**Cost estimate:** ~$0.05
**Why Sonnet not Opus:** technical pattern-recognition is rule-based / template-able; doesn't need full Opus reasoning weight.

### T-RF — Research Forensic (LLM: Claude Sonnet, runs LAST before Synthesizer)
**Owner:** Same endpoint, `forensicPrompt(data_context, bull_round2, bear_round2, technical)`
**Input:** T-RD output + Bull round-2 thesis + Bear round-2 thesis + Technical analyst output
**Job:** Cross-check all upstream theses' factual claims against the data context. Specifically:
- For every numeric claim in Bull / Bear thesis, verify it exists in data context (programmatic FC.2 logic)
- Flag price-anchoring discrepancies (live_price vs claimed price)
- Run FC.2 multiplier-pattern logic on both (P/E forward / EV/EBITDA / P/S claims vs yahoo `fundamentals`)
- Identify shared-assumption risks (both bull + bear depend on the same untested premise — high risk)
- List logical contradictions WITHIN each thesis
- Cross-check whether Technical signals AGREE or CONFLICT with Bull or Bear's thesis (e.g., bull says +30% upside but technical shows down-trend strength 80 — disagreement worth flagging)
**Output:** structured findings JSON:
```json
{
  "bull_findings": [{"claim": "...", "data_match": "MATCH|MISMATCH|UNVERIFIABLE", "evidence": "..."}],
  "bear_findings": [...],
  "shared_assumptions_at_risk": [...],
  "technical_vs_bull": "AGREES | CONFLICTS | NEUTRAL — explanation",
  "technical_vs_bear": "AGREES | CONFLICTS | NEUTRAL — explanation",
  "verdict_on_grounding": "BULL_BETTER_GROUNDED | BEAR_BETTER_GROUNDED | BOTH_HALLUCINATED | EVENLY_GROUNDED"
}
```
**Cost estimate:** ~$0.05

### T-RS — Research Synthesizer (LLM: Claude Opus 4.7, runs LAST)
**Owner:** Same endpoint, `synthPrompt(data_context, bull_r2, bear_r2, technical, forensic_findings)`
**Input:** All of above
**Job:**
1. Weight Bull vs Bear by Forensic's grounding verdict + Technical alignment
2. Decide final direction: LONG / SHORT / PASS (PASS = neither side has edge, don't trade)
3. Produce final 8-step thesis (single canonical output, replaces what `/api/research` currently produces)
4. Emit divergence_score (how much bull and bear disagree on key metrics — high disagreement = high uncertainty)
5. Attach forensic_findings + technical as `_forensic` and `_technical` metadata
6. If Forensic says "BOTH_HALLUCINATED" or all 4 agents disagreed wildly, emit `_synthesizer_recommendation: "PASS — too much disagreement to commit a thesis"`
**Output:** Full 8-step JSON with extra fields:
- `_direction` = LONG / SHORT / PASS
- `_divergence_score` = 0-100
- `_forensic` = T-RF output
- `_technical` = T-RT output
- `_bull_thesis` = T-RB round-2 output (for downstream review)
- `_bear_thesis` = T-RBR round-2 output (for downstream review)
- `_bull_r1` / `_bear_r1` = round-1 (pre-rebuttal) outputs (audit trail)
- existing `_quality` (FC.1+FC.4 validator on synthesizer's output)
**Cost estimate:** ~$0.50 (Opus, longer context including all upstream outputs)

### T-RA — Research Attribution (existing — Bridge-8)
**Owner:** `scripts/log_thesis.py` (already shipped)
**Input:** Final synthesizer thesis
**Job:** Log wrongIf / rightIf / expected_pnl / catalyst at ship time.
**Output:** `public/data/thesis_attribution/<TICKER>.json` (existing).

---

## 3. Wire diagram (v2)

```
                          ┌────────────────────────────────┐
                          │ T-RD Data Loader (Python, T-RD) │
                          │ Reads public/data/* for ticker  │
                          │ Output: data_context (incl. news)│
                          └───────────┬────────────────────┘
                                      │
   ─── ROUND 1 (parallel; bull+bear independent, both see news+full data) ───
                                      │
            ┌─────────────────────────┼─────────────────────┐
            ▼                         ▼                     ▼
    ┌──────────────┐         ┌──────────────┐       ┌──────────────┐
    │ T-RB Bull r1  │         │ T-RBR Bear r1 │       │ T-RT Technical│
    │ (Gemini Pro)  │         │ (GPT-5.5)    │       │ (Sonnet)      │
    │ → 8-step LONG │         │ → 8-step SHORT│       │ → tech signal │
    └──────┬───────┘         └──────┬───────┘       └──────┬──────-─┘
           │                         │                     │
   ─── ROUND 2 (parallel; bull rebuts bear, bear rebuts bull) ─────────
           │                         │                     │
           ▼                         ▼                     │
    ┌──────────────┐         ┌──────────────┐              │
    │ T-RB Bull r2  │         │ T-RBR Bear r2 │              │
    │ sees Bear r1  │         │ sees Bull r1  │              │
    │ rebuts/revises│         │ rebuts/revises│              │
    │ → updated     │         │ → updated     │              │
    └──────┬───────┘         └──────┬───────┘              │
           │                         │                     │
           └─────────────┬───────────┘                     │
                         │                                 │
   ─── FORENSIC (sees Bull r2 + Bear r2 + Technical + data) ──────
                         │                                 │
                         ▼                                 │
                 ┌──────────────┐                          │
                 │ T-RF Forensic │  ◄────────── data context
                 │ (Sonnet)      │  ◄────────── (also Tech ───┘
                 │ Cross-checks  │                 vs bull/bear)
                 │ + tech align  │
                 └──────┬───────┘
                        │
                        ▼
                 ┌──────────────┐
                 │ T-RS Synth    │
                 │ (Opus)        │  ◄── all upstream
                 │ Final thesis  │
                 │ + direction   │
                 │ (LONG/SHORT/  │
                 │  PASS)        │
                 │ + divergence  │
                 │ + all metadata│
                 └──────┬───────┘
                        │
            ┌───────────┼──────────┐
            ▼           ▼          ▼
    ┌─────────────┐ ┌─────────┐ ┌─────────────┐
    │ FC.1+FC.4   │ │T-RA log │ │ Frontend    │
    │ validator   │ │thesis to │ │ Variant     │
    │ on _quality │ │attrib    │ │ Thesis card │
    └─────────────┘ └─────────┘ └─────────────┘
```

**Total LLM calls per thesis:** Bull r1 + Bear r1 + Technical (3 parallel)
+ Bull r2 + Bear r2 (2 parallel) + Forensic + Synth = 7 LLM calls.

---

## 4. Cost / latency budget (v2)

| Path | Cost | Wall-clock |
|---|---|---|
| Existing `/api/research` (single Opus, ungrounded) | ~$1.00 | ~2.5 min |
| Existing `/api/research` + extras (W4 grounded — current) | ~$1.00 | ~2.5 min |
| **Proposed `/api/research-multi` (v2 — 7 LLM calls)** | **~$0.85** | **~6 min** |

Per-agent cost breakdown (multi v2):
- T-RB Bull round 1: ~$0.05
- T-RBR Bear round 1: ~$0.05
- T-RT Technical: ~$0.05
- T-RB Bull round 2 (rebuttal): ~$0.05
- T-RBR Bear round 2 (rebuttal): ~$0.05
- T-RF Forensic: ~$0.05
- T-RS Synthesizer (Opus, sees everything): ~$0.55
- **Total: ~$0.85 per thesis**

Latency: round 1 parallel (~2 min) → round 2 parallel (~2 min) → Forensic
sequential (~1 min) → Synth sequential (~1 min) ≈ 6 min total.

**Trade-off:** ~3.5 extra minutes + ~$0.15 cheaper than ungrounded single-call,
in exchange for: 2-round adversarial debate + technical analysis +
factual cross-check + grounded data layer.

---

## 5. Implementation rollout (3 stages)

### Stage 1 — Data Loader (no LLM, T-RD only)
Ship: `scripts/research_data_loader.py` + `docs/team/RESEARCH_DATA_CONTEXT_SCHEMA.md`
This is W3-W4 in the current shift's plan.
Independently useful: lets `scripts/run_research.py` (non-multi-agent) properly inject data into existing `/api/research` for curl-based testing.
**ETA:** 2-3 hours. NO LLM cost.

### Stage 2 — Multi-agent endpoint (`/api/research-multi`)
Ship: new Vercel function combining Bull + Bear + Forensic + Synthesizer.
Frontend: add toggle "single (fast, $1) vs multi-agent (rigorous, $0.65)".
Existing `/api/research` stays untouched as fast-path.
**ETA:** 1 shift (~3-4 hours including frontend toggle + first end-to-end test).

### Stage 3 — Comparative quality measurement
Run BOTH `/api/research` and `/api/research-multi` on the same 4 tickers.
Compare:
- Hallucination rate (FC.2 mismatch count)
- Same-day stability (do 3 runs of each, see direction-flip frequency)
- Forensic verdict distribution (does multi-agent more often correctly say "BOTH_HALLUCINATED" → Junyan can stop wasting review time)
**ETA:** 1 shift + ~$10 in API spend.

---

## 6. Open decisions — RESOLVED 2026-05-08 by Junyan

### ✅ Q1 — Bull/Bear see news?
**Junyan:** "bull 跟 bear 才是更需要看信息面的".
**Decision:** Both Bull and Bear receive FULL data context including
recent_news. Forensic also sees data (for cross-check). Technical agent
gets OHLC + volume + chip data subset.

### ✅ Q2 — Bull/Bear see each other (round 2 rebuttal)?
**Junyan:** "经过讨论和质疑之后的决策质量才会高".
**Decision:** YES — round 2 added. After parallel round-1 outputs, each
side gets the other's output and rebuts/revises. Cost +$0.10 per thesis
(extra Bull-r2 + Bear-r2 calls). v2 ships with rebuttal pass; not deferred.

### ✅ Q3 — Failure handling?
**Junyan:** "确保 agent fail 的原因 然后根据每次失败的原因去修复和优化".
**Decision:** Don't silently swallow failures. Each agent failure is
logged with full error + which input caused it. Pipeline does NOT
fall back to single-agent on partial failure — instead returns
`_status: "PARTIAL_FAILURE"` with detail for debugging. Eventually
build a `failure_modes.md` doc cataloguing each observed failure type
+ fix.

### ✅ Q4 — Model assignments?
**Junyan:** "不是绝对的 ... GPT 用 5.5".
**Decision:** Default mapping below, but config-driven so we can swap
per-role:
- Bull: Gemini 1.5 Pro (default) — swappable
- Bear: **GPT-5.5** (UPDATED from GPT-4o) — swappable
- Technical: Claude Sonnet
- Forensic: Claude Sonnet
- Synthesizer: Claude Opus 4.7
The config goes in `MODEL_ASSIGNMENTS` env var or a JSON file so swap
doesn't need code change.

### ✅ Q5 — Round 2 review packet integration?
**Junyan:** "round 2 review 那就是每一个 agent 都全面 scan 一下 并且
基于所有信息面去审视和批判 分析技术面等".
**Decision:** Review packets become MULTI-AGENT-CRITIQUE artifacts,
not just human-template. Each packet has sections per agent perspective:
- BULL SCAN — what argument does the bull build from this thesis?
- BEAR SCAN — what argument does the bear build?
- TECHNICAL SCAN — chart pattern / momentum / chip analysis
- FORENSIC SCAN — facts / numbers / logical contradictions
- SYNTHESIZER VERDICT — final weighting + LONG/SHORT/PASS
Plus SECTIONS for human (Junyan) annotations on top of each agent's scan
(reviewer can disagree / flag / override per agent's output).

These all fall out of the `/api/research-multi` output naturally — the
packet just renders the JSON in human-readable form.

---

## 7. What this does NOT solve

- **Hand review still needed.** Forensic catches numeric/factual issues. Mechanism causal soundness, variant-view contrarian-ness, and qualitative arguments still need Junyan + (eventually) Franky.
- **Outcome tracking not addressed.** Bridge-8 outcome tracker is independent of this proposal.
- **Auto-screening not addressed.** This is per-ticker thesis production. Screening (which tickers warrant deep research) is a separate Bridge.

---

## 8. Pre-requisites before Stage 2 ships

1. Stage 1 must complete (data loader producing context JSON)
2. Watchlist v1.2 stable (4-ticker focus locked in)
3. At least 1 round of single-agent grounded thesis (W4-W6 from current shift) so we have BASELINE quality measurement to compare against
4. Vercel env vars confirmed: ANTHROPIC_API_KEY (have), OPENAI_API_KEY (Junyan to confirm), GOOGLE_AI_API_KEY (Junyan to confirm — same key as `/api/debate`?)

---

## 9. Junyan decision status — v2

- [x] Approve overall architecture (Section 2 role spec) — v2 modified per §6 answers
- [x] Approve rollout sequence (Section 5 stages) — Stage 1 ✓ shipped
- [x] Resolve open decisions (Section 6 — 5 questions) — all RESOLVED 2026-05-08
- [ ] Confirm Vercel env vars for OpenAI (GPT-5.5) + Google AI (Section 8 prereq 4) — TBD before Stage 2 ships

Stage 1 (data loader T-RD) shipped 2026-05-08 (commit 3b84ac7).
Stage 2 (multi-agent endpoint) starts next shift, gated on Vercel env confirmation.

---

**Author:** T1 Claude (v1 + v2 update post Junyan §6 resolution)
**v2 changes:** integrated Junyan's 5 §6 answers — round 2 rebuttal,
news to bull/bear, GPT-5.5 model bump, T-RT Technical Analyst added,
failure-debugging policy, multi-agent-critique review packet structure.
