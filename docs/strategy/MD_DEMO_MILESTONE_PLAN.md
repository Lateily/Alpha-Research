# MD Demo Milestone Plan — internal Beta (6/8) → UBS MD demo (6/10)

> **Status: RATIFIED by Junyan 2026-06-01.** This is the follow-up plan that
> governs the next ~10 days. Shift from *continuous building* to **milestone
> delivery + an auditable narrative + demo stability**. Junyan will personally
> red-team the whole model (~6/2–6/4) before final assembly. **No blind feature
> expansion** — every new change goes via isolated worktree + explicit PR.

## 0. Positioning (the bar we hold everything to)

Do **not** package this as a "stock-picking model." For an audience at UBS MD
level the strongest, most credible framing is restrained and auditable:

> An **AI-augmented equity research & trade decision-support platform**. It
> threads information flow → thesis → candidates → portfolio risk → paper P&L →
> human review queue into one **auditable workflow**. It outputs **trade
> reference and risk flags — NOT automatic buy/sell, NOT position sizes.**

Main narrative for 6/10: **auditable decision support + risk discipline +
human-in-the-loop**, not auto stock-picking. The #1 institutional risk is the
platform *looking* like 荐股 (auto recommendations); the milestones below
foreground "decision support, not advice" structurally.

## 1. Scope freeze (Milestone 0 — now → 6/2)

**Goal:** stop blind expansion; keep only demo-relevant deliverables.

**Paused (do NOT build before the demo unless they block it):**
- New engines.
- `#2C` LLM screen→thesis generation (token spend; paused on purpose).
- `forward_evidence_tier` build (design frozen; deferred).
- **Strategy Checklist (Step 4B)** — has value, but it pulls us back toward the
  "trade advice" boundary; do it **after** the main entry point is stable.
- GitHub Actions Node bump — **not running**; only a stale `ci/bump-actions-node24`
  branch remains (no PR, inert). Clean the remote branch *later*; do not let it
  interrupt the main line.

**Process:** all new work via isolated worktree + explicit allowlist + scoped PR;
protected paper-state (`positions`/`analytics`/`snapshots.json`) read-only,
tripwire-verified; no merge until review (doc-only refreshes may self-merge).

**Deliverable (DONE):** Trade Decision Stack v0 backend complete on `main` —
`portfolio_risk_packet` (#12) · `trade_candidate_board` (#13) · read-only Cockpit
(#14) · `human_review_queue` (#16).

## 2. Milestones

### Milestone 1 — 6/2 → 6/4: Cockpit as the main entry point
**Goal:** an internal user opens the platform and immediately knows *what to look
at today*.
- Wire `human_review_queue.json` into the Cockpit.
- Cockpit top section shows: **Review Today · Risk Blockers · Thesis Conflicts ·
  Need More Research**.
- Research / Watch stay collapsible.
- Language holds the line: no BUY/SELL · no size · observed exposure = fact ·
  caps / thresholds / strategy logic = `[unvalidated]`.
- **Not now:** recommended size · auto position construction · strategy execution triggers.

### Milestone 2 — 6/4 → 6/6: internal Beta usability
**Goal:** internal users can run all five main flows end-to-end.
- Beta page connects to the Cockpit as the **acceptance harness**.
- Each of the five flows gets one explicit task.
- Keep the feedback form.
- One visual-QA pass: desktop + mobile basically don't break.

The five main flows:
1. Daily market tracking.
2. Indicators tracking.
3. Paper P&L / 操盘收益率 / attribution.
4. Quant trading / backtest / strategy evidence.
5. Information flow → thesis → portfolio-risk linkage.

### Milestone 3 — 6/6 → 6/8: internal trial
**Goal:** collect real usage feedback; stop changing architecture.
- Invite internal users to trial.
- Record: which module is confusing · which data isn't trustworthy · which labels
  read like 荐股 and need downgrading · where the flow stalls.
- Fix **blockers only** each day; do not add features.

**Success criteria:**
- ≥ 3–5 internal users complete the main flow.
- 15–20 actionable feedback items collected.
- deploy / data / morning-report not red.
- Cockpit stably shows the review queue.

### Milestone 4 — 6/8 → 6/10: MD Demo Pack
**Goal:** not a feature parade — explain the model's **institutional value**.
Prepare a short doc/deck (what it is · what it is **not** · architecture · demo
path · validation status · next roadmap) plus five demo scenarios:

1. **Daily Market Tracking** — how the market moved today; which names to look at.
2. **Core Thesis Path** — one ticker's thesis, catalyst, wrong-if, evidence tier.
3. **Trade Decision Cockpit** — Candidate Board + Risk Packet + Human Review
   Queue; show that the system never says buy/sell — it tells the human *where
   judgement is needed*.
4. **Portfolio Risk / P&L Attribution** — e.g. Innolight/CPO concentration, HK
   names paper-LONG vs registered WATCH_SHORT; the platform surfaces
   research-vs-holdings inconsistency.
5. **Validation Discipline** — cull/promote gate · BY correction · no auto-trade ·
   pending forward samples (~Aug–Nov) · all unvalidated numbers clearly labeled.

This is far stronger than "we have an AI stock-picker."

## 3. Execution order

1. **PR #16 `human_review_queue`** — merged (929ebe8). ✅
2. **Cockpit integration** — put the review queue at the top of the Cockpit (the
   most important screen for the 6/8 internal Beta).
3. **Beta harness** — Beta page routes users into the Cockpit; internal users test
   the five flows.
4. **MD Demo Pack** — the short doc/deck + the five scenarios above.

**Do NOT do Strategy Checklist 4B yet** — it's valuable but ranks below
Cockpit + Review Queue + demo narrative, and it easily drifts back into
trade-advice boundary risk. Revisit once the main entry point is stable.

## 4. One-line summary

For the next 48 hours: don't expand the model — finish **Cockpit + Human Review
Queue + Beta harness** into a stable, demoable *investment decision workbench*.
On 6/10 the story for the UBS MD is **auditable decision support + risk
discipline + human-in-the-loop**, not auto stock-picking.
