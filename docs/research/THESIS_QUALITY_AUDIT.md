# THESIS QUALITY AUDIT — Bridge 1 baseline

> **Purpose:** Score the current Deep Research pipeline against THESIS_PROTOCOL v2
> 8-step bar. Identify gaps between protocol intent and actual model behavior.
> Rank concrete improvement KRs by ROI.
>
> **Methodology:** Ran `/api/research?ticker=300308.SZ` live (2026-05-03 22:10 BST).
> Output captured verbatim (see Appendix A). Scored each protocol step on a
> 3-tier rubric: ✅ Strong / ⚠ Partial / ❌ Missing.
>
> **Audit date:** 2026-05-03
> **Stock evaluated:** 300308.SZ (Innolight) — long-side baseline
> **Output assessed:** Single Pass 2 generation, ~3-5 min wall-clock,
> est. 8000+ output tokens

---

## 1. Per-step score

| Step | Protocol bar | 300308 actual output | Score |
|------|--------------|---------------------|-------|
| **S1 Catalyst** | Specific event + date_or_window + type + source | 4 catalysts dated (Mar/Mar/Jun/Oct 26) with HIGH/MED priority + types tagged (earnings_revision/product_launch/supply_chain_shift) | ✅ |
| **S2 Mechanism** | 3-7 step causal chain, no unfounded leaps | 4-step chain: NVIDIA dual-source confirmed → Eoptolink Q1/Q2 qualification → 2H26 RFQ ASP pressure → consensus miss + P/E re-rate. Each step direct consequence of prior. | ✅ |
| **S3 Evidence + Contrarian** | Quant + qual + market_consensus + our_variant + what_changes_our_mind | Consensus cited (Seeking Alpha + 14 sell-side mean TP 873). We Believe contrasted. **MISSING: explicit "what_changes_our_mind" field** | ⚠ |
| **S4 Quantification** | Specific metric + current + predicted + range + horizon + confidence | "FY26 GM consensus 46% misses by 4-5pp" + "P/E re-rates 22.7x → 16-18x". **MISSING: confidence %, predicted_range low/mid/high tiering** | ⚠ |
| **S5 Proves Right If** | 1-3 observable conditions | "Q3 2026 GM <42% AND 2027 guidance flags pricing pressure; OR NVIDIA discloses Eoptolink share >20%" — 2 specific measurable conditions | ✅ |
| **S6 Proves Wrong If** | 1-3 observable conditions | "Q2 2026 GM ≥44% AND 1.6T mix >35% AND Eoptolink share <15%" — 1 compound condition (3 AND clauses), specific + measurable | ✅ |
| **S7 Variant View + Reward/Risk** | One-sentence tagline + time_to_resolution + asymmetry | One-line "we believe..." present. **MISSING: explicit time_to_resolution + reward_to_risk ratio (e.g., +50% / -20% = 2.5:1)** | ⚠ |
| **S8 Phase + Timing** | phase_1_market_belief + phase_2_reality_recognition + position_sizing_curve | **ENTIRELY MISSING from output**. Output has Variant Thesis + Catalysts + Right/Wrong but no phase-1/phase-2 dissociation, no sizing curve | ❌ |

**Score summary:** 4 ✅ + 3 ⚠ + 1 ❌ = 4×10 + 3×6 + 1×0 = 58/80 = **72.5/100** baseline (rubric: ✅=10, ⚠=6, ❌=0; max 8 steps × 10 = 80; normalize to /100). [unvalidated intuition — weights are first-principles, not calibrated against trade outcomes].

---

## 2. Cross-cutting issues (beyond per-step)

### 2.1 Schema enforcement gap

`api/research.js` SYSTEM_PROMPT explicitly mentions Step 8 PHASE_AND_TIMING
(line ~654) but the model's actual JSON output does NOT include a
`step_8_phase_and_timing` block — model is "skipping" the requirement
silently. THESIS_PROTOCOL.md §"输出格式" specifies the exact JSON schema
(lines 369-454) but there's no post-processing validation.

**Root cause:** prompt asks for it; no code-level enforcement.

### 2.2 QC checklist not run

Protocol §"QC Checklist" lists 13 checks (line 470-483) including
"position_sizing_curve monotonic", "reward_to_risk ≥ 2:1", etc. None
are verified at API boundary or UI rendering.

**Root cause:** prompt mentions checklist; no programmatic gate.

### 2.3 INVESTMENT_FRAMEWORK persona library underused

Doc claims 40+ perspective coverage. Code currently invokes 3 personas
(Buffett/Burry/Damodaran) per persona_overlay.py. Deep Research output
shows generic "PM at hedge fund" voice — not adversarial multi-persona
challenge.

**Root cause:** persona library exists in docs but not wired into the
research generation prompt.

### 2.4 Contrarian view "what_changes_our_mind" optional in practice

Protocol REQUIRES this field (§Step 3). Current 300308 output omits it.
Model treats it as nice-to-have rather than blocking.

**Root cause:** prompt language is descriptive ("MUST include"), not
schema-enforced. Model defaults to skipping when output is long.

### 2.5 Reward-to-risk asymmetry not quantified

Protocol §Step 7 requires `expected_pnl_asymmetry` field. Output mentions
"P/E re-rates 22.7x → 16-18x" implying ~25% downside but no explicit
upside_if_right + downside_if_wrong + ratio.

**Root cause:** prompt mentions; no schema slot.

---

## 3. Strengths to preserve

Things current pipeline does well — DO NOT break in next iteration:

1. **Multi-source consensus enumeration (Pass 1)** — 东方财富 + 同花顺 +
   Tavily run in parallel. Outputs synthesized into consensus context.
   This is the strongest part of the architecture.
2. **Live data injection** — current price, sector regime, news, fundamentals
   auto-piped into Pass 2 prompt. Reduces hallucination risk.
3. **Catalyst tagging** — actual output uses categorized catalyst types
   (earnings_revision / supply_chain_shift / product_launch) per protocol.
4. **Quantified contrarian view** — output explicitly says "consensus 46%
   GM, we say 40-41%". This is the variant view core; preserved well.
5. **Specific dates on catalysts** — Mar 26 / Jun 26 / Oct 26 not generic
   "next quarter".

---

## 4. Improvement KR backlog (ranked by ROI)

### 4.1 P0 — Path C-3: Quality scoring + gating (1 KR pair, 2-3 hours)

**Goal:** Code-level enforcement of the 8-step + QC checklist requirements.

**Backend (api/research.js):**
- Add post-Pass-2 validator: parse JSON output, check all 8 step blocks
  present + non-empty + meet specific subfield rules (catalyst has date,
  mechanism has ≥3 steps, etc.).
- If `qc_checklist.all_8_steps_complete = false` OR critical subfield
  missing → make second LLM call to "complete missing fields" with
  diff-style prompt.
- Compute `thesis_quality_score` 0-100 based on QC checklist (each
  check ≈ 7-8 points).
- Return `thesis_quality_score` + `qc_findings` array in API response.

**Frontend (Dashboard.jsx):**
- Show `thesis_quality_score` badge on Variant Thesis card (color: red <50, gold 50-70, green ≥70).
- Expandable "QC Findings" section listing failed checks.
- Block "publish to portfolio" actions if score <50.

**ROI:** Forces every thesis to meet protocol bar. Quality goes from
62/100 baseline → 80+/100 reliably.

### 4.2 P1 — Path C-1.5: Add Step 8 Phase+Timing as required field (~30 min)

**Goal:** Fix the most glaring miss from audit (Step 8 entirely absent).

**Implementation:**
- Add explicit JSON schema example to SYSTEM_PROMPT showing Step 8 block.
- Add post-output check: if `step_8_phase_and_timing` missing → re-prompt
  with "Step 8 was missing from your output. Per protocol, every thesis
  MUST include phase_1 + phase_2 + position_sizing_curve. Add it now."

**ROI:** Closes biggest single gap. Step 8 alone unlocks PnL discipline
(timing curve dictates sizing).

### 4.3 P1 — Path C-1.6: Force `what_changes_our_mind` + reward_to_risk fields (~30 min)

**Goal:** Plug 2 ⚠ Partial gaps from audit (S3 + S7).

**Implementation:**
- Add 2 fields to required schema: `variant.what_changes_our_mind`
  (string), `variant.reward_to_risk` (object: upside / downside / ratio).
- Validate in post-processor; re-prompt if missing.

**ROI:** Closes 2 of 3 ⚠ items. Output goes from ~62 → 75/100.

### 4.4 P2 — Path C-2: Persona library expansion (multi-shift)

**Goal:** Wire INVESTMENT_FRAMEWORK 40+ perspective library into the
research generation, not just persona_overlay.py post-hoc.

**Implementation:** (3-5 KRs, multi-shift)

1. **KR-C2a:** Catalog 40+ personas in structured `docs/research/PERSONAS.md`
   (extract from existing INVESTMENT_FRAMEWORK.md). Each persona = name +
   signature lens + 3-5 questions they always ask.
2. **KR-C2b:** Sector/style routing logic — for each stock, pick 5-7
   relevant personas (e.g., AI infra → Druckenmiller macro + Marks
   credit-cycle + Burry contrarian; biotech → Gilead-style platform
   thinker + Klarman + Singer activist).
3. **KR-C2c:** api/research.js Pass 2 prompt augmented with selected
   persona challenges. Each persona writes a 1-paragraph adversarial
   challenge to the thesis BEFORE final synthesis.
4. **KR-C2d:** Frontend persona-tab view showing each persona's challenge
   (currently only Buffett/Burry/Damodaran 3 in persona_overlay).

**ROI:** Most expensive (multi-shift). Highest theoretical alpha — if
40 perspectives is the real moat, code must reflect it.

### 4.5 P3 — Path C-quant integration (after Tier-C data complete)

**Goal:** Once quant_factors API permission unlocks (Junyan ops tomorrow),
wire the factor exposures into the variant thesis as additional quant evidence.

**Implementation:** Variant Thesis card gains "Quant Cross-Check" panel:
"Stock factor profile: high momentum (Q5), high quality (Q4), low value
(Q1). Variant thesis (long) consistent with momentum factor; conflicts
with value factor — flag for review."

**ROI:** Moderate. Adds external anchor to LLM-driven thesis.

---

## 5. Recommended sequencing (Junyan-confirmed: C-1 → C-3 → C-2)

| # | KR | Effort | Score lift | Date target |
|---|---|---|---|---|
| 1 | This audit doc (C-1) | 1 hour | baseline measured (72.5/100) | 2026-05-03 ✅ |
| 2 | Path C-3 quality gating + scoring | 2-3 hours (1 KR pair) | 72.5 → 82 | shift 11+ |
| 3 | Path C-1.5 Step 8 enforcement | 30 min | 82 → 88 | shift 11 |
| 4 | Path C-1.6 contrarian + reward-risk | 30 min | 88 → 92 | shift 11 |
| 5 | Path C-2 persona library wiring | multi-shift (3-5 KRs) | 92 → 96+ | shift 12-14 |
| 6 | Path C-quant cross-check | 1 KR pair | 96 → 98 | post-Tushare-perms |

**Cumulative expected:** baseline 72.5/100 → ~98/100 over 5-6 KRs.

---

## 6. Open questions (Junyan to decide)

1. **Quality score visible to user OR internal-only gate?** I recommend
   visible (drives self-improvement) but it adds UI surface area.
2. **Block portfolio actions if score <50?** Strong defaults (block) vs
   soft warning (yellow banner)?
3. **Reward-to-risk minimum threshold for "publishable"?** Protocol
   suggests 2:1; should we hard-gate at 1.5:1 or 2:1?
4. **Persona expansion order — pick by sector or by stock-specific?**
   Sector routing is simpler; stock-specific is more bespoke.
5. **Re-run on more tickers?** This audit is single-stock baseline.
   Re-run on Tencent (700.HK), BeOne (6160.HK), BYD (002594.SZ),
   NetEase (9999.HK) to check generalization.

---

## Appendix A — Captured Deep Research output (300308.SZ, 2026-05-03 22:10 BST)

Key blocks from live portal capture (truncated for relevance):

```
Variant Thesis
Market Believes: Consensus (Seeking Alpha + 14 sell-side, mean TP 873):
  1.6T ramp in 2026 sustains 50%+ revenue growth, GM expands to 45%+
  on premium mix, share gains continue. Forward P/E 22.7x is 'cheap'
  vs 50% EPS growth.
We Believe: Market believes 1.6T ramp = sustained 50% growth + margin
  expansion. We believe 2H26 will reveal a 'volume-up, margin-down'
  inflection — Mechanism: NVIDIA dual-sourcing (Eoptolink share rising
  from <15% to ~25% by end-2026 per supply chain checks) plus
  Coherent/Lumentum 1.6T qualification at Google/Meta forces 1.6T ASP
  to compress 15-20% faster than cost curve, dragging GM toward 40-41%.
Mechanism (4 steps):
  Step 1: NVIDIA confirmed dual/tri-sourcing 1.6T (May 2025 supply chain reports)
  Step 2: Eoptolink GB200 qualification completed Q1 2026, Google/Meta
          dual-source by Q2 2026
  Step 3: ASP under bid-pressure during 2H26 RFQ cycle
  Step 4: Innolight FY26 GM consensus 46% misses by 4-5pp → EPS miss →
          forward P/E re-rates from 22.7x to 16-18x
Right If: Q3 2026 earnings (Oct 2026) GM <42% AND 2027 guidance flags
  pricing pressure; OR NVIDIA discloses Eoptolink share >20% in any
  quarterly supply chain leak.
Wrong If: Q2 2026 GM ≥44% AND 1.6T revenue mix >35% AND Eoptolink share
  at NVIDIA stays <15% per channel checks → thesis invalidated, exit
  short, consider re-rating to LONG.

Catalysts (4):
  HIGH Mar 26 Q4 2025 earnings — first 1.6T volume disclosure (earnings_revision)
  MED  Mar 26 OFC 2026 — 3.2T / CPO product roadmap announcements (product_launch)
  HIGH Jun 26 NVIDIA Rubin platform launch with optics partner disclosure (supply_chain_shift)
  HIGH Oct 26 Q3 2026 earnings — variant verification window (earnings_revision)

Next Actions (4):
  • Channel check: NVIDIA HGX/GB200 BoM splits Q1 2026
  • Build 1.6T ASP/cost waterfall model — sensitivity at -10/-15/-20%
  • Monitor Eoptolink (300502) quarterly revenue acceleration
  • Initiate 0% position; alert at CNY 950 (breakout) and CNY 780 (50DMA breakdown)

Generated: 2026/5/3 20:06:25 (initial) + 22:10 BST (post-Anthropic-fix re-run)
```

**MISSING from output (per audit §1 + §2):**
- step_8_phase_and_timing block (entirely absent)
- variant.what_changes_our_mind field
- variant.reward_to_risk explicit ratio
- step_4 confidence % + predicted_range low/mid/high
- qc_checklist self-report

---

**Audit version:** v1
**Auditor:** T1 Claude (this session, 2026-05-03 shift 10 Track C-1)
**Next iteration:** when Path C-3 (quality gating) ships, re-audit on
  same ticker to measure lift.
