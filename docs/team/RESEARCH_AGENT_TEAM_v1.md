# Research Agent Team v1 — Architecture Proposal

> **Status:** PROPOSAL pending Junyan approval
> **Date:** 2026-05-08
> **Author:** T1 Claude
> **Related:** AGENT_ORCHESTRATION.md (covers code-side T1/T2/T3); this
> doc covers RESEARCH-side production. Junyan-direct ask 2026-05-08:
> "在产出报告上也需要多 agent 合作 ... 我们要搭建一个体系成熟的 agent team".

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

## 2. Role spec — 5 research-side agents (3 LLM + 2 deterministic)

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

### T-RB — Research Bull (LLM: Gemini 1.5 Pro)
**Owner:** `/api/research-multi` `bullPrompt(data_context)`
**Input:** T-RD output + 8-step protocol prompt
**Job:** Produce strongest **LONG** thesis using ONLY the supplied data (no training-data hallucination — explicit "if a number is not in data context, do NOT use it; instead say 'not available in our data'").
**Output:** Full 8-step JSON (matches existing `/api/research` schema). Direction = LONG.
**Cost estimate:** ~$0.05 (Gemini Pro 1.5 cheaper than Opus)

### T-RBR — Research Bear (LLM: GPT-4o)
**Owner:** Same endpoint, `bearPrompt(data_context)`
**Input:** T-RD output + 8-step protocol prompt
**Job:** Produce strongest **SHORT** thesis (or "consensus is right, no contrarian view" if data doesn't support short).
**Output:** Full 8-step JSON. Direction = SHORT or NEUTRAL.
**Cost estimate:** ~$0.05

Bull and Bear run in parallel (Promise.allSettled). Each is a contained role —
Bull doesn't see Bear's output and vice versa. Independence preserves the
adversarial value.

### T-RF — Research Forensic (LLM: Claude Sonnet)
**Owner:** Same endpoint, `forensicPrompt(data_context, bull_output, bear_output)`
**Input:** T-RD output + Bull thesis + Bear thesis (sees BOTH)
**Job:** Cross-check both theses' factual claims against the data context. Specifically:
- For every numeric claim in Bull / Bear thesis, verify it exists in data context
- Flag price-anchoring discrepancies (live_price vs claimed price)
- Run FC.2 multiplier-pattern logic on both (P/E forward / EV/EBITDA claims vs yahoo `fundamentals`)
- Identify shared-assumption risks (both bull + bear depend on the same untested premise)
- List logical contradictions WITHIN each thesis
**Output:** structured findings JSON:
```json
{
  "bull_findings": [{"claim": "...", "data_match": "MATCH|MISMATCH|UNVERIFIABLE", "evidence": "..."}],
  "bear_findings": [...],
  "shared_assumptions_at_risk": [...],
  "verdict_on_grounding": "BULL_BETTER_GROUNDED | BEAR_BETTER_GROUNDED | BOTH_HALLUCINATED | EVENLY_GROUNDED"
}
```
**Cost estimate:** ~$0.05

### T-RS — Research Synthesizer (LLM: Claude Opus 4.7)
**Owner:** Same endpoint, `synthPrompt(data_context, bull, bear, forensic_findings)`
**Input:** All of above
**Job:**
1. Weight Bull vs Bear by Forensic's grounding verdict
2. Decide final direction: LONG / SHORT / PASS (PASS = neither side has edge, don't trade)
3. Produce final 8-step thesis (single canonical output, replaces what `/api/research` currently produces)
4. Emit divergence_score (how much bull and bear disagree on key metrics — high disagreement = high uncertainty)
5. Attach forensic_findings as `_forensic` metadata
**Output:** Full 8-step JSON with extra fields:
- `_direction` = LONG / SHORT / PASS
- `_divergence_score` = 0-100
- `_forensic` = T-RF output
- `_bull_thesis` = T-RB output (for downstream review)
- `_bear_thesis` = T-RBR output (for downstream review)
- existing `_quality` (FC.1+FC.4 validator on synthesizer's output)
**Cost estimate:** ~$0.50 (Opus, longer context including all upstream outputs)

### T-RA — Research Attribution (existing — Bridge-8)
**Owner:** `scripts/log_thesis.py` (already shipped)
**Input:** Final synthesizer thesis
**Job:** Log wrongIf / rightIf / expected_pnl / catalyst at ship time.
**Output:** `public/data/thesis_attribution/<TICKER>.json` (existing).

---

## 3. Wire diagram

```
                       ┌────────────────────────────────┐
                       │ T-RD Data Loader (Python)       │
                       │ Reads public/data/* for ticker  │
                       │ Output: data_context JSON       │
                       └───────────┬────────────────────┘
                                   │
            ┌──────────────────────┼──────────────────────┐
            │ (parallel)           │                      │
            ▼                      ▼                      ▼
    ┌─────────────┐         ┌─────────────┐       ┌─────────────┐
    │ T-RB Bull    │         │ T-RBR Bear  │       │  (T-RF waits) │
    │ Gemini Pro   │         │ GPT-4o      │       │              │
    │ → 8-step     │         │ → 8-step    │       └─────────────┘
    │   LONG       │         │   SHORT     │
    └──────┬──────┘         └──────┬──────┘
           │                       │
           └─────────────┬─────────┘
                         ▼
                 ┌─────────────┐
                 │ T-RF Forensic│
                 │ Claude Sonnet│
                 │ Sees both    │
                 │ Cross-checks │
                 │ vs data ctx  │
                 │ → findings   │
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐
                 │T-RS Synthesizer│
                 │ Claude Opus  │
                 │ Final thesis │
                 │ + direction  │
                 │ + divergence │
                 │ + forensic   │
                 │   metadata   │
                 └──────┬──────┘
                        │
            ┌───────────┼──────────┐
            ▼           ▼          ▼
    ┌─────────────┐ ┌─────────┐ ┌─────────────┐
    │ FC.1+FC.4   │ │T-RA log │ │ Frontend    │
    │ validator   │ │thesis to │ │ Variant     │
    │ on _quality │ │attrib    │ │ Thesis card │
    └─────────────┘ └─────────┘ └─────────────┘
```

---

## 4. Cost / latency budget

| Path | Cost | Wall-clock |
|---|---|---|
| Existing `/api/research` (single Opus) | ~$1.00 | ~2.5 min |
| Proposed `/api/research-multi` (5 agents) | ~$0.65 | ~5 min |

Multi-agent is **cheaper** (smaller models for narrower roles) but **slower** (sequential synthesis after parallel bull/bear/forensic).

**Trade-off:** trade 2 minutes of wait for 4-way independent verification + cheaper unit cost. Worth it if research quality matters more than latency for the user.

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

## 6. Open design decisions (need Junyan input)

1. **Should Bull see news / Bear see news, or only Forensic?**
   - Pro for both seeing news: each can build a more current thesis.
   - Pro for only Forensic: news is "ground truth check" rather than thesis input.
   - **My recommendation:** All 3 see data context (incl. news). Forensic uses it for cross-check.

2. **Should we let Bull and Bear see EACH OTHER's output (round 2)?**
   - Pro: classic adversarial debate where each side rebuts.
   - Con: doubles cost + latency, may converge to mush.
   - **My recommendation:** v1 = no rebuttal. v2 (later) can add if value clear.

3. **What if Bull / Bear LLM call FAILS?**
   - Existing `/api/debate` uses Promise.allSettled and returns partial results.
   - **My recommendation:** if 1 of 3 (Bull/Bear/Forensic) fails, Synthesizer proceeds with available inputs + flags `_partial=true`. If 2 fail, return error.

4. **Model assignments — which model to which role?**
   - Current proposal: Bull=Gemini, Bear=GPT-4o, Forensic=Claude Sonnet, Synth=Claude Opus.
   - Rationale: 3 different model families = real cognitive diversity. Synth=Opus because final thesis needs reasoning weight.
   - Alternative: all Claude, just different prompts. Cheaper to debug but less model-diversity.
   - **My recommendation:** Multi-vendor as proposed. Worth the API key management cost for genuine independence.

5. **How does this connect to Junyan's hand-review packets?**
   - Round 2 review packets currently render single thesis. With multi-agent, packets would render: Final + (collapsed) Bull + (collapsed) Bear + Forensic findings inline.
   - **My recommendation:** packet generator script auto-detects multi vs single and renders appropriately.

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

## 9. Junyan decision needed

- [ ] Approve overall architecture (Section 2 role spec)
- [ ] Approve rollout sequence (Section 5 stages)
- [ ] Resolve open decisions (Section 6 — 5 questions)
- [ ] Confirm Vercel env vars for OpenAI + Google AI (Section 8 prereq 4)

After approval, Stage 1 (data loader) starts immediately. Stages 2+3 are next-shift work.

---

**Author:** T1 Claude (post-shift-13, watchlist v1.2 wave)
**Awaiting:** Junyan review + decision on §6 open questions
