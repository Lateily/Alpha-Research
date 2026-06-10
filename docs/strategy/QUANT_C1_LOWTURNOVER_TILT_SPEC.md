# QUANT CANDIDATE C1 — LOW-TURNOVER QUALITY+LOW_VOL TILT (SPEC, pre-registration draft)

> **Status: RATIFIED (Junyan 2026-06-10)** — K=20 · claim gate = CSI300 AND EW dual-pass (strict;
> a miss is no-claim, not failure) · family = C1a/C1b/C1c only + random-K control (NO lowvol_only —
> C2 material). **No backtest number exists for C1 yet; the manifest locks at implementation.**
> **Date:** 2026-06-10 · **Pipeline:** the validated Factory B machinery — survivorship gate →
> pre-registered manifest → harness (#54/#56/#57) → 5 benchmarks → bootstrap + BY → 19-gate →
> mechanical verdict (~3.5 min per family).
> **Context:** H1 v0-H1 was KILLED 2026-06-09 (`QUANT_V0_VERDICT_2026-06-09.md`). Technical timing
> is now 3-for-3 dead (inverse-momentum, satellite-as-alpha, H1); the recurring killer is
> **turnover × cost + regime whipsaw**. C1 attacks that directly: it is **structurally low-turnover
> by design**, not by tuning.

---

## 1. Why C1 (the data pointer, stated honestly)

In the v0 verdict, the quality+low_vol tilt baseline was **the only non-dead arm**: vs CSI300
−2.8%/yr (CI straddling 0), **vs EW-liquid +7.5%/yr point** (CI [−4.2, +19.1], straddling 0),
Sharpe 0.29, hit 50%, turnover 3.95×/yr — while every event-timing arm lost 15–23%/yr. It also
independently reproduced the satellite finding: value+low_vol carry the only validated cross-
sectional IC (t > 4.7), but as implemented they are **compensated premia, not demonstrable alpha**.

**C1's falsifiable question:** does engineering the SAME composite into a structurally
low-turnover construction (≤2.0×/yr, the IMPL4 bar) move the post-cost alpha CI off zero — or is
it premia all the way down? **The honest prior is that C1 FAILS the CSI300 bar** (the satellite
already suggests premia-not-alpha). The test is cheap (~3.5 min) and either outcome is informative:
a clean kill closes the factor-tilt question; a pass is the first surviving candidate.

## 2. Hypothesis (to be sha256-locked in the manifest, verbatim)

> C1: on the liquid top-500 A-share universe, an equal-weight top-K portfolio ranked by the
> value(E/P)+low_vol z-composite, rebalanced at low cadence with a rank-exit buffer so annual book
> turnover stays ≤ 2.0×, delivers post-cost same-gross alpha whose bootstrap CI clears zero vs
> **both CSI300 and EW-liquid**, full-sample and walk-forward.

`causal_logic_label: unestablished` — value/low_vol IC is real `[validated against data]`; that a
low-cost tilt converts it into net alpha (rather than premia) is the unproven step.

**Expected failure modes (pre-registered):**
1. **Premia-not-alpha** (most likely): vs-EW CI keeps straddling zero — kill and close the line.
2. **Concentration noise**: top-K too small → idiosyncratic noise swamps the weak IC.
3. **Stale-rank decay**: lower cadence → the composite's information decays before the next rebalance.
4. **Low-vol crowding** post-2017 → the factor's premium thins exactly when measurable.

## 3. Variant family (the BY family; all pre-registered, run together once)

| arm | construction (K = 20, ratified) | turnover intent |
|---|---|---|
| **C1a** | rebal 40td, top-20, full re-rank | ~2.0× |
| **C1b** | rebal 20td + **rank-exit buffer** (sell only when rank > 2×K = 40) | ~1.5–2× (buffer does the work) |
| **C1c** | rebal 60td | ~1.3× |
| control | **random-20 rotation**, same cadence as C1a, seeded — does ANY 20-name EW rotation look like this? | ~2.0× |
| reference | the measured #57 baseline (20td, K=10, 3.95×) — already run, re-reported not re-run | — |

BY multiple-testing across {C1a, C1b, C1c} (m=3; the random control is a control, not a candidate).
**No post-hoc variants:** if all three fail, the family is killed — no threshold nudging (the α1.2
lesson). A revision would be a NEW manifest (C2).

## 4. Everything else inherited unchanged from the v0 spec

Universe (panel-derived survivorship-safe top-500 ADV) · T+1 fills · 0.40% RT baseline + cost grid
on the full window · windows (full_2006_2026 + 5 wf) · 5 benchmarks · stale/delist mark-out ·
**claim gate: `ci_positive_after_cost` vs CSI300 AND EW + WF1 ≥3/5 + OOS `wf_2022_2026`
(exact-name) not sig-neg + 19-gate PASS** (IMPL4 ≤2.0× now binding by design) · read-only, no
capital/paper, `validation_status: unvalidated` until a verdict, human ratifies.

Engine delta required (small, after ratification): parameterize `run_tilt_arm` (rebal_days, rank
buffer, top_k) + a seeded random-rotation arm + a C1 manifest/variant pass in `quant_verdict.py`.

## 5. RATIFIED decisions (Junyan 2026-06-10 — locked into the manifest)

1. **K = 20.** quality/low_vol is a weak premia, not a high-conviction signal — it needs
   diversification to suppress single-name noise / halts / sector drift. The alpha dilution is
   accepted: **dilution is preferable to a false positive.**
2. **Claim gate stays CSI300 AND EW dual-pass — not relaxed.** Beating only CSI300 may be
   small-cap/equal-weight exposure; beating only EW may be beta/style mismatch. The goal is
   deployable edge; **a miss is no-claim, not failure.**
3. **No lowvol_only arm in C1.** Family = C1a (rebal-40) / C1b (rebal-20 + rank-buffer) /
   C1c (rebal-60) + seeded random-K rotation control, exactly. A bigger family = heavier BY +
   muddier interpretation. C1's question is "does the low-turnover quality+lowvol tilt deserve
   promotion?", not factor attribution — `lowvol_only` is C2 material.

**Junyan's posture, recorded:** the real asset is the validation factory, not any single strategy.
C1 most likely does not become alpha directly — its job is to tell us whether the low-turnover
premia line is worth continuing.

> One line: C1 is the cheapest honest test of the only direction the v0 verdict left alive —
> structurally low-turnover by design, one locked family, kill-or-keep in 3.5 minutes, and the
> prior says be ready for another kill.
