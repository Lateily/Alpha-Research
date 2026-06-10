# QUANT C1 — FAMILY VERDICT (2026-06-10)

> **Run:** full 2006-01-04 → 2026-05-26 + 5 walk-forward windows × 4 arms (3 candidates + seeded
> random control) + per-candidate 3-scenario cost grids, survivorship-gate-passed, manifest
> sha256-locked **before** any run (`5e08e1a1…`), B=10,000 bootstrap, BY m=3, per-candidate 19-gate.
> Elapsed **255 s**. Artifacts: `public/data/quant_c1_verdict.json` + `quant_c1_manifest.json`.
> Spec (ratified): `QUANT_C1_LOWTURNOVER_TILT_SPEC.md` — K=20 · dual-benchmark claim · locked family.
> **Mechanical verdict — the human (Junyan) ratifies. No claim of any kind is made below.**

---

## 1. The numbers (full sample, same-gross, annualized)

| arm | α vs CSI300 (95% CI) | α vs EW-liquid (95% CI) | CAGR | Sharpe | MaxDD | turnover |
|---|---|---|---|---|---|---|
| **c1a** rebal-40 | −2.1% [−8.8, +4.5] | **+8.2%** [−2.5, +18.8] | +4.7% | 0.31 | −76.3% | 2.15 |
| **c1b** rebal-20+buffer | −4.3% [−11.0, +2.3] | +5.9% [−5.2, +17.0] | +2.9% | 0.24 | −79.0% | **1.80** |
| **c1c** rebal-60 | −2.0% [−8.6, +4.5] | **+8.3%** [−2.5, +19.0] | +5.5% | 0.33 | −77.5% | **1.57** |
| random control | **−9.7% [−17.6, −1.8], p=0.013 (sig-NEG)** | −0.0% [−5.0, +4.7] | −4.7% | 0.00 | −93.6% | 5.95 |

Walk-forward (α vs CSI300, point): candidates positive only in 2006–2010 (+2~+10%) and ~flat
2014–2018; **worst in 2018–2022 (−12~−14%)** — the growth/momentum bull where value+low_vol lagged;
**WF1 fails for all three (2/5, 1/5, 2/5)**. BY-adjusted p = **1.0** across the family.
Cost grid: optimistic→pessimistic moves α by only ~0.5pp — **cost is no longer the story** (the
low-turnover design did its job; what remains is simply no CSI300-relative edge).

## 2. Junyan's four-branch decision tree, applied

| branch | test | result |
|---|---|---|
| ① claim gate PASS → paper/product candidate | `ci_positive_after_cost` vs CSI300 **AND** EW + WF1 + OOS + 19-gate | ❌ **no arm passes** — both CIs straddle zero everywhere; WF1 2/5 max; gates FAIL (WF1/MT/IMPL4/IMPL5/IMPL7) |
| ② no-claim but benign → C2 research direction, NOT product | not sig-neg, coherent premia behavior | ✅ **THIS BRANCH.** All three candidates straddle zero on both benchmarks (no `ci_negative_after_cost`); OOS 2022–2026 not sig-neg; behavior is consistent premia |
| ③ sig-neg / collapse → KILL | full-sample sig-neg or wf collapse | ❌ not triggered for any candidate |
| ④ control as good → composite has no information | random ≥ candidates | ❌ **not triggered** — the control is **significantly negative vs CSI300** (−9.7%, p=0.013) and ≈exactly 0 vs EW (a random rotation IS the EW universe minus its own churn, as theory predicts), while all three candidates sit **+6~+8%/yr above it** on the EW-relative point with ~⅓ of its turnover. The composite ordering carries real information over random rotation — **but its premium never reaches significance vs EW** |

## 3. Mechanical recommendation (for Junyan to ratify)

**NO-CLAIM / branch ② — retain the quality+low_vol line as C2-grade research direction; it does
NOT enter the product as a recommendation.** Specifically:

- **What C1 established** `[validated against data]`: the composite is *not* informationless (it
  beats its own random control decisively); the EW-relative premium (+6~+8%/yr point) is consistent
  across all three constructions; **structural low turnover works** (c1b 1.80 / c1c 1.57 full-sample,
  vs the baseline's 3.95) and removes cost as the dominant drag.
- **What C1 falsified**: that low-turnover construction converts the premium into a *claimable*
  edge — it does not. vs CSI300 the point is mildly negative everywhere; vs EW the CI never clears
  zero; the premium is regime-cyclic (dead through 2018–2022), so WF1 fails by construction.
- **Two honest structural notes:** (a) IMPL4 fails on the 2006–2010 sub-window for every arm
  (early-sample churn > 2.0) even where full-sample turnover meets the design bar; (b) **IMPL5
  (MaxDD ≥ −25%) binds structurally for ANY ~100%-gross long-only A-share book** (the candidates
  drew −76~−79%; 2008 alone explains most of it) — that is gate-context, not an excuse: as a
  deployable product a −76% MaxDD tilt is unacceptable regardless, which is itself an argument
  that a raw fully-invested tilt is not a product candidate.
- **C2 directions this points to (research only, new manifests):** regime/trend overlay ON the tilt
  (de-risk the 2018-2022-type windows — but that re-introduces timing, the 3-for-3 graveyard);
  or accept-premia-as-beta positioning (explicitly NOT alpha). Either is a Junyan strategy call,
  not a default next step.

## 4. What must NOT be said

- ❌ "C1 has edge / beats the market" — nothing cleared the claim gate.
- ❌ "+8% vs EW" as a result — the CI is [−2.5, +18.8]; it is a point estimate that straddles zero.
- ❌ Re-running with new variants until something turns green — the family is LOCKED; revisions are
  a NEW pre-registered manifest (C2).

**Factory note:** second full family verdict, 255 seconds, zero capital risked, four-way design
(candidates + control) answered the actual question cleanly. The loop is doing exactly what it was
built to do.
