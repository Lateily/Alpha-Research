# CORE THESIS FACTORY v1 — RESEARCH-QUALITY TESTING (SPEC, for Junyan review)

> **Status:** draft for ratification (the #51/#60 pattern: ratify the contract BEFORE producing).
> **Date:** 2026-06-10
> **What this is:** the systematic test of **research quality** — Factory A's counterpart to what
> the Quant Factory just did for trading rules (H1 KILL · C1 NO-CLAIM). The question is NOT "does
> the research have alpha" (that is the CORE Alpha Factory's forward-validation job, first verdict
> ~Aug–Nov 2026). The v1 question is prior and cheaper: **is a given single-name research output
> specific, falsifiable, valuation-disciplined, information-additive, and forward-honest — i.e.
> 先证明研究不是空话.**
> **Composes (does NOT reinvent):** `docs/research/THESIS_PROTOCOL.md` (the 8-step skeleton +
> forced JSON schema + QC checklist) · `thesis_queue.json` pre-registration (lock-hash, wrong_if,
> R/R, horizon) · `scripts/thesis_eval.py` (structural auto-scorer) · `scripts/thesis_factcheck.py`
> (claims vs ingested data) · `scripts/core_validation_ledger.py` (forward residual machinery) ·
> the 2026-05-15 human red-team standards (PROVEN|INFERRED|ASSUMED causal tags · citation grades ·
> Rule-X · R/R ≥ 2:1 conviction bar) · `api/research.js` (the 8-step generation pipeline).

---

## 0. What v1 adds (exactly three new things)

1. **The 单票决策书 (Single-Name Decision Sheet) — the product-grade output contract.** The 8-step
   thesis is the research core; the decision sheet wraps it with what the old no-advice regime
   forbade and the pilot now requires: **target range, execution plan, bilingual rendering.**
2. **A research-quality score** — Junyan's five axes, with the C-3 lesson built in (structural
   compliance ≠ investment quality → the auto-score is only a floor; the human red-team score is
   the real measure).
3. **Forward 30/60/90d outcome checkpoints** — does the research say true things ahead of time?
   (Pre-registered; explicitly NOT an alpha claim at this n.)

---

## 1. The Decision Sheet schema v1 (one JSON per name: `public/data/decision_sheets/<ticker>.json`)

Every field group below is REQUIRED for a sheet to count as "qualified output". `[unvalidated]`
labeling and the pilot disclaimer are non-negotiable throughout.

| group | contents | source / rule |
|---|---|---|
| **identity** | ticker · name (zh+en) · market · sector/theme · as_of · sheet_version · provenance refs (thesis run id, factcheck id) | composer |
| **thesis** | variant perception ("market believes X → we believe Y") · first-principles mechanism · direction · horizon_days · conviction tier (e.g. STARTER_CAPPED_UNTIL_E1) | 8-step Steps 1–2, 7–8 |
| **evidence** | items each tagged **[E1/E2]**; every causal link tagged **PROVEN \| INFERRED \| ASSUMED**; citations graded **EDGE_ESTABLISHING / CONSENSUS_CONFIRMING / CROWDING_SIGNAL / DECORATIVE**; explicit **Rule-X check** (is the forward mechanism re-confirmable by issuer disclosure?); contrarian view included | Steps 3–4 + the 5/15–5/17 calibration rules |
| **catalyst calendar** | events + dates + the exact metric to watch + expected sign/rough magnitude | Step 1 + Step 8 |
| **wrong_if** | ≥2 falsifiable triggers, each **mechanized**: metric + threshold + source + check date (machine-checkable where the data exists) | Step 6; Path-B rule: triggers source-bound |
| **valuation + target_range** | method(s) appropriate to the name (PE / EV-EBITDA / rDCF / SOTP) · **base / bull / bear** with the load-bearing assumptions stated per scenario · derived band labeled `basis` + **`calibrated:false`** · computed R/R · the **R/R ≥ 2:1** conviction bar (below it = WATCH, not conviction — the 5/15 大参林 rule) | reuse `multi_method_valuation` / `residual_income_valuation` / `ev_ebitda_valuation` + rDCF |
| **execution plan** | entry reference/zones · staging (starter → add only on confirmation, tied to named evidence) · invalidation = price stop AND thesis wrong_if (both) · **suggested** sizing tier (suggestion only — human executes; never auto) · holding horizon · review dates (=30/60/90 checkpoints) | new in v1; pilot-consistent |
| **risk** | fundamental / policy / valuation / liquidity / **crowding-reflexivity** checklist, each with a one-line specific exposure (no boilerplate) | Step 3 contrarian + 5/15 citation-crowding rule |
| **language** | thesis / why / wrong_if / plan rendered **bilingual (zh + en)** | fixes the English-only gap |
| **disclaimers** | unvalidated pilot · not validated alpha · human executes · `no_trade_flag`-family fields consistent with the product | pilot positioning |

**Qualification rule:** a sheet missing any group, any untagged causal link, an un-mechanized
wrong_if, or a single-point "target price" (instead of an assumption-explicit band) is
**NOT a qualified output** — it fails structurally before quality is even scored.

## 2. Research-quality score v1 (Junyan's five axes, 0–100 each; weights `[unvalidated]`)

| axis | what it measures | anchors |
|---|---|---|
| **specificity** 具体性 | numbers, dates, named metrics vs vague narrative | 90 = every claim quantified+dated; 50 = direction without magnitude; 10 = 叙事 |
| **falsifiability** 可证伪性 | wrong_if mechanization + Rule-X re-confirmability | 90 = ≥2 machine-checkable triggers w/ disclosure source; 10 = "if fundamentals deteriorate" |
| **valuation discipline** 估值纪律 | assumption-explicit multi-scenario band; R/R honest | 90 = base/bull/bear w/ stated drivers + sensitivity; 10 = single-point target |
| **information increment** 信息增量 | EDGE_ESTABLISHING share; variant-perception sharpness vs consensus/普通研报/AI summary | 90 = a claim the street demonstrably lacks; 10 = repackaged consensus (DECORATIVE-heavy) |
| **risk identification** 风险识别 | specific, name-level risks incl. crowding/reflexivity | 90 = each risk tied to a measurable exposure; 10 = generic checklist |

**Two-layer scoring (the C-3 lesson is load-bearing):**
- **Auto floor** (extend `thesis_eval.py` to the sheet schema): structural presence + tag coverage +
  mechanization checks. Passing the floor means "well-formed", **nothing more**.
- **Human red-team** (Junyan, the 5/15 pattern; optionally Franky): the five axes scored on
  substance. **The human score is the quality measure of record.** Auto ≥ floor AND human ≥ bar
  (bar `[unvalidated]`, propose 70 avg with no axis < 50) ⇒ the sheet may register for forward
  validation and surface in the product.
- Comparison baseline: for ≥1 batch-1 name, score a plain AI summary / 普通研报 of the same name on
  the same rubric — the **information-increment test must beat that baseline**, or the factory adds
  no research value.

## 3. Forward 30/60/90d outcome checkpoints (says-true-things-ahead-of-time, NOT alpha)

- On registration (existing `thesis_queue` lock-hash pattern — sheet content hashed BEFORE any
  outcome), schedule checkpoints at **30/60/90 calendar days**.
- Per checkpoint, record mechanically (extend `core_validation_ledger.py`):
  1. **directional hit** — theme/peer-adjusted residual sign vs the thesis direction (the ledger's
     existing residual machinery);
  2. **target-band traversal** — spot vs the base/bull/bear band (entered? exceeded bear?);
  3. **wrong_if status** — any mechanized trigger fired? (if fired and the sheet wasn't updated →
     an honesty failure, logged);
  4. **catalyst materialization** — did the named event occur on schedule, and did the named metric
     move in the predicted direction?
- **Explicit bound:** with batch-1 n=3–5 these are **case results, not statistics**. They feed the
  CORE Alpha Factory's ≥8-family verdict (~Aug–Nov 2026); v1 claims only "the research was/wasn't
  honest and specific enough to be checkable — and what the checks said."

## 4. Batch-1 (3–5 names) — production plan

- **Sources:** Junyan-given tickers (preferred — the familiar-domain bullshit-detection rule) +
  optionally 1–2 from the screener top candidates (tests generalization beyond the comfort zone).
- **Suggested mix (Junyan decides):** 1 refresh of an existing registered name to the new schema
  (e.g. 002594 — comparable against its 5/15 red-team) · 1–2 fresh Junyan picks · 1 screener name.
- **Pipeline per name:** `api/research.js` 8-step generation → `thesis_factcheck` → compose the
  decision sheet → auto floor → **human red-team** → (if qualified) register + schedule checkpoints
  → product surface.
- **The first full sample:** Junyan gives ticker #1; we run the entire path end-to-end on it before
  batching the rest (single-piece flow first — find the breaks before scaling).

## 5. Product integration (after batch-1 qualifies)

The decision sheet becomes the click-through target from Model Portfolio cards — one complete
单票决策书 instead of scattered tabs (this supersedes the parked "step 4 single-stock sheet" as the
Core Thesis Factory's product surface). UI work is a separate later PR; data contract first.

## 6. Implementation sequence

1. **PR-A** — sheet schema + composer skeleton (`scripts/decision_sheet.py`: compose existing
   thesis/factcheck/valuation data into the schema; `--selftest` enforces the qualification rule).
2. **PR-B** — scoring harness (extend `thesis_eval.py` to the sheet schema = the auto floor; a
   `review_packet` for the human red-team, reusing `thesis_review_packet.py`).
3. **PR-C** — ticker #1 full sample (generation → factcheck → sheet → scores → red-team → register).
4. **PR-D** — 30/60/90 checkpoint wiring (extend `core_validation_ledger.py`).
5. **PR-E** — batch-1 remainder + the baseline-comparison test (vs plain AI summary).
6. **PR-F** — UI decision sheet (last; data contract must be stable first).

## 7. Open decisions for Junyan

1. **Batch-1 composition** — give 3–5 tickers (or approve the suggested mix in §4)? **Ticker #1 =
   the first full sample — your call is the starting gun.**
2. **Target-range visibility** — show the band in the product immediately on qualification, or
   only after the first 30d checkpoint exists? (Lean: immediately, labeled `calibrated:false` —
   the pilot's honesty framing already covers it.)
3. **Human-score bar** — propose avg ≥ 70 with no axis < 50 `[unvalidated]`; adjust?
4. **Reviewer set** — Junyan solo, or Junyan + Franky for batch-1?

> One line: the Quant Factory tests trading rules; **v1 makes research quality testable** — a
> locked product-grade contract, a two-layer score where the human is the measure of record, and a
> 30/60/90 loop that checks whether the research said true things before the market did.
