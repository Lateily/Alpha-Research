# DEEP THESIS FACTORY v0 — FROM THEME SCAN TO A VALIDATED BUY LIST (SPEC, for Junyan review)

> **Status:** draft for ratification (the #51/#62 pattern: ratify the contract BEFORE building the pipeline).
> **Date:** 2026-06-14
> **What this is:** the production system that takes the CORE Thesis Factory from "we can hand-craft
> one deep thesis per round" to "we can deep-do 2–3 per batch without losing the audit standard," and
> — crucially — defines the **state machine that turns a deep thesis into a buy candidate**. It is the
> honest answer to Junyan's question *"如何稳定地生产已验证的买入名单"*: you do NOT pre-validate every
> stock and then buy; you **validate the research PROCESS**, then grant a small-starter permission to
> future theses that pass the bar, and let forward checkpoints decide add/hold/exit.
> **What this is NOT:** a machine that batch-writes 20 full decision sheets (that collapses quality into
> "deep-looking summaries"); an auto-trader; an alpha claim. The human red-team stays the measure of record.
> **Composes (does NOT reinvent):** `CORE_THESIS_FACTORY_v1_SPEC.md` (the 单票决策书 contract + five axes
> + 30/60/90 checkpoints) · `scripts/decision_sheet.py` (composer + `qualify()` gate + content_lock) ·
> `scripts/sheet_checkpoints.py` (registration + forward court) · `docs/research/decision_sheets/FIVE_AXIS_RUBRIC.md`
> (blind-scoring harness) · `docs/strategy/STRATEGY_LAB_AGENT.md` (forward-paper-is-the-real-court discipline) ·
> `docs/research/serenity/SCAN_1_AI_SEMIS.md` (the discovery layer) · the standing no-validated-alpha discipline
> (`CLAUDE.md` Analysis Output Standard #3 + the pilot disclaimer) and the "每日计划 = research-object daily STATE,
> not a new-buy list" product rule.

---

## 0. The problem (Junyan's diagnosis, ratified 2026-06-14)

The bottleneck of a high-quality report is **NOT model capability**. It is four costs that do not parallelize for free:
**(a) evidence depth** (line-by-line E1 primary disclosure), **(b) valuation modeling** (a real earnings bridge —
the quick-screen valuation-discipline blind score is only **55.2**; 澜起/拓荆 reached **84/88** *because* of the bridge),
**(c) human red-team**, **(d) forward-registration cost**.

Two empirical facts set the design:
- **Quick screens CAN batch** — #76 produced 9 AI-semi structured screens in half a day, blind avg **77.3**.
- **Deep theses CANNOT be naively batched** — each is a per-ticker model (E1 line-by-line + product split +
  consensus + earnings bridge + source appendix + red team). The two deep upgrades (澜起 89.6 / 拓荆 91.8) also
  **corrected the quick screens' WRONG numbers** (澜起 static PE 108→116-119; 拓荆 mcap understated **40%**, 388→645).
  → one-pass E2 web facts are unreliable; **depth corrects accuracy, not just persuasiveness.**

So the correct division of labour is three layers, not one batch.

---

## 1. The three-tier product ladder

| tier | cadence / breadth | quality band (blind-anchored) | what it is FOR | what it is NOT |
|---|---|---|---|---|
| **quick_screen** | batch, 20–30 names/theme | ~77 (auto-floor + blind) | discovery: which to deepen, which to downgrade, key triggers, "how the model says no" | a buy list; registered; an investment decision |
| **deep_thesis** | 1–3 names/round | 88–92 (human red-team) | investment-grade research: is this name *qualified to enter the investment discussion* | a buy order; an alpha claim |
| **registered_thesis** | only red-team-PASS deep theses | n/a (forward court) | the falsifiable forward record (30/60/90) that eventually validates the process | statistics (n<15); proof of alpha |

**Quality ladder, all blind-anchored:** plain AI summary **~62** → quick screen **~77** → full deep sheet **88–92**
(PR-B proved deep sheets beat plain summaries by **+26.2**, concentrated in falsifiability + valuation discipline).

**Promotion is per-name, on Junyan's pick** — a quick_screen never auto-promotes; the human chooses which 1–3 to deepen.

---

## 2. Full-sheet hard gates (a deep_thesis is not "qualified" unless ALL pass)

Extends `decision_sheet.py qualify()` with the depth requirements Junyan ratified. Auto-checks are the FLOOR only.

1. **E1 source 落库** — every load-bearing claim cites a primary disclosure (年报/季报/公告/IR记录 PDF), and the
   **source appendix lives IN the artifact** (not in a session draft). Media/sell-side are E2; weak sources are `lead` and excluded from load-bearing.
2. **Earnings bridge 必填** — a 3-scenario bridge (营收 → GM → opex → 归母 → EPS × forward PE → target), every multiple
   `[unvalidated intuition]` with a stated anchor. For profit-quality names, **DUAL-VIEW** (表观 reported vs 清洁扣非 clean).
3. **R/R 必填** — computed from the band + the registration price vs the 2:1 conviction bar; the stance follows the R/R, never the narrative.
4. **wrong_if 绑定可披露字段** — ≥2 mechanized triggers (metric + threshold + **issuer-disclosure source** + check_date);
   un-disclosable legs use the `if_not_disclosed → INSUFFICIENT_DISCLOSURE` protocol, never a guess.
5. **价格 / 股本 / 市值 实时复核** — the headline price, share count, and market cap are reconciled against primary/committed data
   BEFORE the bridge runs (this is the gate the two quick screens failed; see §5 extraction fidelity).
6. **自评 ≠ 红队** — the auto/blind score is a floor and a triage signal only; **registration requires the human five-axis red-team** (FIVE_AXIS_RUBRIC.md is the harness, Junyan is the adjudicator).

---

## 3. Three institutional rules ratified by PR-E (#79)

These three were decided live during the 澜起/拓荆 registration and are now binding factory rules.

### 3.1 Committed-price registration rule
The **registration reference price MUST come from committed data** (`ohlc_<ticker>.json`) **or an explicit, dated
live-snapshot artifact** (`universe_a.json` `_meta.fetched_at`). **A web-hand-typed price is forbidden as the registration price.**
*(澜起 registered at the committed 229.28, not the deep thesis's web 228; 拓荆 at 664.42, not 645 — auditable input, same verdict.)*
The deep narrative MAY quote a live web price for context, but it must be labeled and is never what the checkpoint locks against.

### 3.2 Dual-artifact source-of-record division
Two artifacts per registered name, with **fixed roles**:
- **`<ticker>_..._DEEP_<date>.md`** = the human-readable narrative / **the red-team basis** (what Junyan scores).
- **composer render `<ticker>_<date>.md` + `public/data/decision_sheets/<ticker>.json`** = the **machine-structured registration artifact** /
  the checkpoint's source of truth (committed price, computed R/R, content_lock). The `.json` is what `register()` reads.
- The composer render's `provenance.research_core_lineage` MUST point back to the DEEP narrative. Neither is deleted; their roles do not blur.

### 3.3 Red-team status must not be stale
A composer artifact may **never** display `human red-team PENDING` once the red-team is bound and the sheet is registered.
- **v0 (done in #79):** the render reads `quality.human_red_team` instead of hardcoding PENDING; the two registered sheets were stamped PASS (lock invariant — the lock payload excludes `_meta` + `quality`).
- **v0.1 (this spec → implement in PR-G):** `register()` AUTO-STAMPS `quality.human_red_team = PASS(...)` and re-renders the composer MD as part of registration, so no future sheet can go stale and the 3 earlier sheets (BYD/华海/鼎龙) get corrected on their next touch.

---

## 4. The output STATE MACHINE — how a thesis becomes a buy candidate

This section is the answer to *"if our research process is validated, shouldn't we be able to give a buy list directly,
instead of waiting for each stock to be validated (= timeless/after-the-fact trading)?"*

**The resolution: we validate the PROCESS, not each stock.** Once the process is shown to discriminate, a *new* thesis
that clears the bar earns a **small-starter permission**; checkpoints then decide add/hold/exit. You are not waiting for
a stock to be proven before buying it — you are requiring the *method* to be proven before granting it entry rights.

### 4.1 The stances (every deep_thesis carries exactly one)

| stance | meaning | gate to enter |
|---|---|---|
| `NOT_ADVANCED` | not worth deepening / rejected for upgrade | quick-screen judgment (story > evidence, non-bottleneck, extreme crowding) |
| `WATCH_ONLY` | thesis holds, but **price/odds insufficient** (R/R < 2:1) | red-team PASS + R/R < 2:1 |
| `STARTER_CANDIDATE` | thesis holds **AND R/R ≥ 2:1 AND no wrong_if fired AND not at bull-case / not extreme-crowding / no stale price** | the §4.2 promotion gate |
| `ADD_CANDIDATE` | after a starter, a catalyst/disclosure confirmed and the band re-rated up | a printed wrong_if-clearing E1 event |
| `REDUCE / EXIT` | a wrong_if fired, or price reached the bull band, or valuation broke | mechanized invalidation |

**The buy-candidate list = only `STARTER_CANDIDATE` ∪ `ADD_CANDIDATE`.** Not every PASS thesis.
*Why are 澜起/拓荆 not on a buy list? Not because the research is unfinished — because R/R is 0.11 / −0.06. The system
identifying good companies at bad prices and saying WATCH **is the system working**, not failing.*

### 4.2 The STARTER_CANDIDATE promotion gate (all required)
`red-team PASS` ∧ `R/R ≥ 2:1 on the committed-price band` ∧ `no wrong_if fired` ∧ `not inside the bull band` ∧
`not extreme-crowding (per the serenity crowding read)` ∧ `price is committed/live, not stale`.

### 4.3 Phased starter permission (the process-validation gate)
- **Phase A — NOW.** WATCH only; **no systematic starter.** Reason: the process has **0 closed checkpoints** (first read 2026-07-10).
  The honest product today = discovery lists + WATCH-tier research + the forward court. *(Pairs with `product_daily_plan_reanchor`:
  the daily plan is the STATE of these objects, not a new-buy list.)*
- **Phase B — after initial process validation** (see 4.4). Small starter allowed: **0.5–1% / name**, ONLY on a `STARTER_CANDIDATE`,
  wrong_if disclosure-bound, a 30/60-day structural exit if the catalyst doesn't print. Every starter is a *shadow* entry first (§4.5).
- **Phase C — after sustained process validity.** A formal model portfolio: **3–8 names, 1–3% / name, sector caps, max-drawdown rule,
  weekly state update**, every buy bound to a thesis content_lock + exit conditions. *(This is where the Daily Model Portfolio pilot reconnects.)*

### 4.4 What unlocks Phase B (the process-validation criteria — pre-registered, not post-hoc)
A meaningful sample, not each stock: **≥15–30 deep theses** each with a stance, registration price, band, and mechanized wrong_if;
**≥ the 30/60/90 reads closed** on a meaningful subset; and a demonstrated ability to **discriminate** — WATCH calls that avoided
drawdowns, wrong_if that fired when it should have, and (the missing ingredient today) at least a handful of `STARTER_CANDIDATE`
names whose forward path the band actually called. Until then, Phase A holds.

### 4.5 Shadow model portfolio (runs during Phase A/B — records, does not trade)
Every would-be starter is logged the day its stance becomes `STARTER_CANDIDATE`: entry price, thesis content_lock, band,
30/60/90 return, wrong_if outcome. This produces the closed-outcome evidence that 4.4 needs **without risking capital**, and is the
honest bridge from "research" to "buy list." No auto-trade, no auto-size; `human_executes`.

---

## 5. The pipeline (PR-G / PR-H / PR-I) — and why extraction fidelity is the whole game

The pipeline industrializes the **mechanical** steps so the human spends scarce attention on the **analytical** steps.

### 5.1 Make-or-break = extraction fidelity (NOT orchestration)
Steps 1, 4, 6 (pull filings, write appendix, triage-score) are easy. **Steps 2–3 (auto-extract financials → auto-bridge)
are where the quick screens went WRONG** (澜起 PE; 拓荆 −40% mcap). If the extractor can't match hand-verified primary numbers,
the pipeline mass-produces "deep-looking wrong summaries" — the exact failure to avoid. So the core design constraint is fidelity, with two gates:

- **一手对账门 (primary-reconciliation gate):** auto-extracted 利润表 / 现金流 / 分部 / 股本 / price must reconcile line-by-line against
  the primary PDF; a mismatch beyond tolerance **flags or refuses**, never silently feeds the bridge.
- **Golden regression set:** **澜起 (688008) + 拓荆 (688072)** — the only two fully hand-verified + human-red-teamed sheets — are the
  ground truth. The extractor MUST reproduce their numbers (price/shares/mcap/扣非/合同负债/bridge inputs) before it is allowed to run a new name.

### 5.2 PR-G — `scripts/deep_thesis_prepare.py` (the extractor)
Input: a ticker. Output: a 素材包 (research pack): committed/live **price · market cap · PE**; **年报/季报/公告 links**;
**利润表 / 现金流 key fields**; **sell-side consensus**; a **source-appendix skeleton**. Gated by §5.1. Kills the "price wrong by 40%" class.

### 5.3 PR-H — earnings-bridge JSON schema
A unified schema `{revenue, gross_margin, opex, non_operating, net_income, eps, pe_multiple, target_band, reward_to_risk}` × 3 scenarios,
DUAL-VIEW capable (表观 / 扣非). Every deep_thesis exports a structured bridge; the band/R-R/wrong_if all derive from it mechanically.

### 5.4 PR-I — batch upgrade queue (2–3 names/round, quality gate stays the human)
From a theme's quick_screen pool, pick 2–3 to deepen per round. **Scan ORTHOGONAL themes** — AI-semi is crowded (Scan #1 zero T1,
all 5 registered names WATCH_ONLY because price ran to the bull case), so to find `STARTER_CANDIDATE` names (good thesis + **good price**)
the queue must widen: 创新药出海 / 电力·电网瓶颈 / 消费·周期低估修复 / 设备·材料 non-crowded layers. Next AI-semi candidates if continued: 中微 / 安集.

---

## 6. Honest scope + what is still missing for a stable buy list

**The pipeline industrializes the mechanical ~70%** (pull, extract, bridge arithmetic, appendix, triage-score).
**It does NOT remove the analytical ~30%** (variant perception, scenario assumptions, the human red-team). The win is real
(1–2/round → 3–5/batch) but bounded, and entirely gated on solving extraction fidelity first.

What is missing today for "stable validated buy lists" (Junyan's own list, recorded):
1. **Sample size** — 5 ACTIVE, far from the 15–30 the process gate needs.
2. **Closed outcomes** — 0 today; the first 30/60/90 reads start **2026-07-10**.
3. **R/R-qualifying names** — every high-quality deep thesis so far is too expensive (澜起 0.11 / 拓荆 −0.06 / 华海 / 鼎龙 all WATCH_ONLY).
   The process can find good companies; it has **not yet found a good price**. This is the real next frontier, and it is a *scanning-breadth* problem (§5.4), not a depth problem.
4. **Portfolio / risk rules** — per-name cap, sector cap, max-drawdown, add/exit, cash rules (the Phase-C scaffold).

**The one-sentence honest state:** we can do *theme scan → quick screen → deep-do 1–3 → red-team → register a forward checkpoint*.
We **cannot yet** stably emit a validated buy list — because we have neither a closed process-validation sample nor an R/R-qualifying name.
The next real work is **not** to write hot good-companies even deeper; it is to **widen the scan to find the good-thesis ∩ good-price intersection.**

---

## 7. Implementation sequence
1. **PR-F (this doc)** — ratify the contract. *(no code)*
2. **PR-G** — `deep_thesis_prepare.py` extractor + §5.1 reconciliation gate + golden-regression test (reproduce 澜起/拓荆) + the §3.3 v0.1 `register()` auto-stamp.
3. **PR-H** — earnings-bridge JSON schema + composer export.
4. **PR-I** — batch upgrade queue, orthogonal-theme first; emit per-name stance from the §4.1 state machine.
5. **(later)** shadow model portfolio (§4.5) once a `STARTER_CANDIDATE` first appears.

## 8. Open decisions for Junyan
1. **State machine (§4) ratify?** Are the five stances + the STARTER_CANDIDATE gate + the Phase A/B/C permission ladder the right shape — in particular the Phase-B unlock criteria (§4.4: ≥15–30 theses + closed reads + demonstrated discrimination)?
2. **Phase B sizing** — is 0.5–1%/name the right starter size, and do you want the shadow portfolio (§4.5) to start logging *now* (Phase A) so the closed-outcome sample accrues before any real starter?
3. **PR-I theme order** — confirm orthogonal-first (创新药出海 recommended for forward-test independence from semis beta) over continuing AI-semi (中微/安集). The goal of the next scan is explicitly to find an R/R-qualifying name, not another WATCH.
4. **Extractor scope (PR-G)** — committed-data + filing-PDF only, or also a live-quote fetch (with the §3.1 labeling) so the reconciliation gate has a second source?
