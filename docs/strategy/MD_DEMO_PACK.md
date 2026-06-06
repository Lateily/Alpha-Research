# MD Demo Pack — UBS MD demo (6/10)

> **Status:** Fulfils **Milestone 4** of `MD_DEMO_MILESTONE_PLAN.md` (ratified 2026-06-01).
> **Doc-only.** The **live Beta + Cockpit** is the demo surface — no demo-mode code
> (Junyan 2026-06-06: add code only if the doc reveals a real demo blocker).
> **Companion docs:** `MD_DEMO_MILESTONE_PLAN.md` (plan) · `USP_VISION.md` (dual-track) ·
> `CORE_ALPHA_FACTORY_v0_SPEC.md` (validation engine) · `TRADE_DECISION_STACK_v0_DESIGN.md` (Cockpit).
> **How to use:** §3 is the live click-path; §4 is the spoken script + guardrails;
> rehearse once against §6 before 6/10.

---

## 0. The one-sentence pitch

> An **auditable, AI-augmented equity-research & decision-support cockpit** for A-share + HK.
> It threads *information → thesis → candidates → portfolio risk → paper P&L → human review*
> into one workflow that surfaces **evidence, structured scores, and risk flags** — and
> **never** emits buy/sell or position sizes. **The human makes every decision.**

---

## 1. Positioning — what it IS / what it is NOT

The #1 institutional risk is *looking like 荐股* (auto recommendations). Foreground the restraint.

| It **IS** | It is **NOT** |
|---|---|
| A **decision-support cockpit** — evidence, signals, structured scores, risk flags | A **stock-picker / 荐股 tool** — no auto buy/sell, no position sizes, no auto-trade |
| **Falsifiable research** — every thesis has catalyst + proves-right-if + **proves-wrong-if** + evidence tier | A **black box** — no unexplained recommendations; the model can't mark its own homework |
| **Auditable** — numbers labeled `[validated]` / `[unvalidated]`; sources cited; thesis↔holdings inconsistency **surfaced** | A **validated-returns product** — paper-only, no live capital, edge not yet proven |
| **Human-in-the-loop** — a daily Human Review Queue is the decision surface | A **backtest hero** — curve-fit numbers are discarded; honest CIs shown |
| **China-context edge** — A-share/HK narrative + information-structuring (the USP) | A **robo-advisor** — it routes judgement to the human, it doesn't replace it |

**Inspiration (credible anchor):** UBS Finance Challenge — 中际旭创 long + Pop Mart short, both validated.

---

## 2. The auditable workflow (architecture)

```
 INFORMATION            THESIS ENGINE             DECISION STACK              HUMAN
 news · capital flows   7-step, evidence-tiered,  candidate board (status     ┌──────────────┐
 filings · universe  →  falsifiable thesis     →  precedence, NO size)      → │   HUMAN      │
 attention screen       (catalyst · wrong-if ·    portfolio risk packet       │   REVIEW     │
                        evidence tier · fact-      (observed exposure = fact;  │   QUEUE      │
                        check vs ingested data)    caps = [unvalidated])       │ → DECIDES    │
                                                   paper P&L / attribution     └──────────────┘
                                       ▲
                        CORE Alpha Factory v0 — pre-register (tamper-evident hash)
                        → forward-validate (multi-testing correction) → cull/promote
                        — ALL read-only · nothing promoted to capital
```

Every arrow is inspectable; the only thing that closes the loop to action is **the human**.

---

## 3. Demo route — 5 scenarios (live click-path + the point)

Open on the **Beta tab** (default landing): *"This is the analyst's daily entry — AI surfaces evidence, the human decides. Five flows."*

### Scenario 1 — Daily Market Tracking · *Browse*
- **Click:** Beta → Task 1 → **Browse**. Show breadth (涨/跌/涨停/跌停 counts), Top movers, capital flows.
- **Say:** *"Note the honesty from screen one — breadth and movers carry a **snapshot-date stamp**, and the **'Live' dot only lights when we're actually receiving quotes**. We never imply data is fresher than it is."*
- **The point:** data honesty is structural, not a footnote.

### Scenario 2 — Core Thesis Path · *Research (300308 中际旭创 Innolight)*
- **Click:** **Research** → 300308. Walk the 7-step thesis: catalyst (1.6T mass-production timing) → mechanism → evidence + contrarian → quantification → **proves-right-if** → **proves-wrong-if** → variant view. Open the **fact-check panel** + evidence tier.
- **Say:** *"Every thesis is falsifiable. Here's the catalyst, here's exactly what would **prove us wrong**, and here's the evidence-quality rating. The fact-check panel cross-checks the model's numeric claims against ingested filings/market data and flags mismatches — **the model doesn't grade its own homework.**"*
- **The point:** falsifiable, auditable research — not a tip.

### Scenario 3 — Trade Decision Cockpit · *Cockpit*
- **Click:** **Cockpit**. Human Review Queue (Review today · Risk blockers · Thesis conflicts · Need more research) → Candidate Board (status precedence `RISK_BLOCKED > HUMAN_REVIEW_REQUIRED > RESEARCH_REQUIRED > WATCH > NO_ACTION`) → Portfolio Risk packet.
- **Say:** *"This is the daily decision surface. Critically — **it never says buy or sell.** It tells the human **where judgement is needed**: what to review, what's risk-blocked, where theses conflict. Status-only. Caps and thresholds are labeled `[unvalidated]`."*
- **The point:** decision-support, structurally not 荐股.

### Scenario 4 — Portfolio Risk / P&L Attribution · *Portfolio + Cockpit risk* (the honesty showpiece)
- **Click:** **Portfolio** (paper P&L / attribution) → **Cockpit** risk: theme exposure (Innolight / CPO concentration); the **alignment guardrail** — HK names **paper-LONG vs registered WATCH_SHORT**; shadow book shows only **~3.7%** of the paper book is backed by an *aligned* directional thesis.
- **Say:** *"Here's the institutional kicker: the platform surfaces **its own inconsistencies** — it flags that some holdings are paper-LONG while our registered research says WATCH_SHORT, and that only a small fraction of the book is thesis-backed. A 荐股 tool hides this; **an auditable research system shows it.**"*
- **The point:** auditability = surfacing your own research-vs-holdings gaps.

### Scenario 5 — Validation Discipline · *Tracker + talk-through*
- **Click:** **Tracker** — prediction log (2/3 decidable correct: 700.HK ✅, BYD ✅, BeiGene ❌, NetEase ~inconclusive); thesis outcomes / wrongIf monitoring.
- **Say:** *"And we're honest about edge. The pure-systematic 'satellite' has **no statistically demonstrable edge** — the alpha confidence interval **straddles zero**, and we say so. The intended alpha is the **thesis-driven CORE** track; its forward-validation window is **Aug–Nov 2026** — not yet proven. Every uncalibrated weight is `[unvalidated]`. The CORE Alpha Factory **pre-registers** theses with a tamper-evident hash, then **forward-validates** with multiple-testing correction before any edge claim. **Nothing is promoted to capital.**"*
- **The point:** *we tell you what we don't know* — that restraint is the moat.

> **Close:** return to Beta → the **feedback loop** (issue-type capture). *"The system is built to be corrected by its users — human-in-the-loop, all the way down."*

---

## 4. Talking points, Q&A, and what NOT to claim

**Three key messages (repeat them):**
1. **AI produces evidence; humans decide.** (compliance, accountability, no black-box 荐股)
2. **Falsifiable + auditable + `[unvalidated]`-labeled** = institutional credibility.
3. **The honesty *is* the differentiator** vs the 1d/3d 荐股 terminals.

**Anticipated Q&A (bounded, honest answers):**
- *"Does it make money / what's the track record?"* → Paper-only, no live capital. Satellite has **no demonstrable edge** (CI straddles zero). The edge thesis is **CORE thesis-driven research**, forward-validation **pending (Aug–Nov 2026)**. Prediction log **2/3 decidable**. **We do not claim validated returns.**
- *"Is this 荐股 / a robo-advisor?"* → No. **Structurally** no buy/sell, no sizing, no auto-trade. Decision-support.
- *"Moat vs Bloomberg / Wind / AI-quant terminals?"* → China-context narrative + information-structuring edge; falsifiable-thesis discipline; auditability (surfaces own inconsistencies); the **dual-track** (research + forward-validated quant).
- *"Why trust the AI?"* → You don't have to — **the human decides**; every claim is evidence-rated, fact-checked, and falsifiable.

**❌ WHAT NOT TO CLAIM (anti-oversell guardrail — bounded claims only):**
- ❌ "validated / proven alpha or returns" — satellite CI straddles zero; CORE unproven.
- ❌ "the AI picks winners" — it surfaces evidence; **humans decide**.
- ❌ "calibrated weights / thresholds" — they are `[unvalidated intuition]`.
- ❌ "it never gets stuck / it's always right" — **structural compliance ≠ investment quality**; bounded claims only.
- ✅ Use: *decision-support · evidence and signals · honest about what's unvalidated · forward-validation in progress.*

> This guardrail **is** the anti-oversell discipline the platform enforces internally. Embody it live — the credibility comes from the restraint, not the claims.

---

## 5. Validation status (honest snapshot)

| Component | Status | Honest read |
|---|---|---|
| Satellite (pure systematic) | Bootstrap alpha **CI straddles zero** (OOS point −2.0%, 95% CI [−11.1%, +8.7%]; p≈0.69) | **No demonstrable edge** — say so |
| CORE (thesis-driven) | Forward-validation window **~2026-08 → 11** | Intended alpha source; **not yet proven** |
| CORE Alpha Factory v0 | Live, **read-only**; produce→pre-register→validate→shadow→cull | Nothing promoted to capital |
| Prediction log | **2/3** decidable correct | Small n; honest track |
| VP weights (25/25/20/15/15) | `[unvalidated intuition]` | Causal logic real; weights uncalibrated |
| Paper book ↔ registered thesis | ~**3.7%** aligned (alignment guardrail) | Inconsistency **surfaced, not hidden** |

---

## 6. Pre-demo readiness checklist (6/8 → 6/10)

- [ ] **Deploy green** — gh-pages live; latest `fetch-data.yml` data committed; morning-report not red.
- [ ] **Data freshness** — universe snapshot date recent; "Live" dot behaves; no stale prices on demo tickers.
- [ ] **No-advice banners present** — Cockpit, **Beta**, Morning, Desk all show the "decision support, not advice" line.
- [ ] **`[unvalidated]` labels visible** — caps/weights/thresholds.
- [ ] **Beta is the default landing** (shipped #30) — opens on the guided entry.
- [ ] **Mobile works** (P3b #28 + P2 #29) — can demo on a phone if asked.
- [ ] **Demo tickers populated:** 300308.SZ (中际旭创) · 700.HK · 9999.HK · 6160.HK · 002594.SZ.
- [ ] **Know which tabs to skip** — don't open half-built/experimental surfaces live.
- [ ] **Feedback flow ready** — can show capture + Copy/Download JSON.
- [ ] **Rehearse the 5-scenario path once** end-to-end (~8–10 min).

---

## 7. Roadmap teaser (parked post-demo — present as direction, NOT as shipped)

- **Dual-track** (`USP_VISION.md`): buy-side **falsifiable theses** + a **~30% systematic Path-B quant sleeve** (A-share long-only), human-allocated with explicit reasoning — same end-shape as the 荐股 terminals but deeper and **honestly framed**.
- Candidate **state / flow / sentiment** factors (the China information-structuring edge) route through the **CORE factory: pre-register → forward-validate** before any edge claim. **Plausible-but-unestablished — do NOT present as validated.** (The falsified inverse-momentum Path-B stays dead.)
- Near-term: more forward samples accrue (first CORE validation verdict ~Aug–Nov 2026); deepen the human-review workflow.

---

## 8. One-line close

> *"This is not an AI stock-picker. It's an **auditable decision-support cockpit** that makes a human analyst faster and more disciplined — and it's honest about exactly what it has and hasn't proven. That restraint is the institutional moat."*
