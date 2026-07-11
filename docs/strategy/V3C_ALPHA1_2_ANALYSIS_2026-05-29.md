# V3C-α1.2 Analysis — turnover compression (rebal 10→20) + strategy-drift finding

**Date**: 2026-05-29
**Variant**: `v3c_alpha1_2_20260529_turnover_compression` (hash `652c4cb6…`)
**Single-variable change**: `rebalance_cadence_days: 10 → 20` (all else frozen from α1.1)
**Verdict**: **FAIL 4/19** — same gate set as α1.1: `[MT, IMPL2, IMPL4, IMPL5]`
**Data**: `public/data/v3c_alpha1_2_bundle.json` · auto-report `/tmp/v3_harness/v3c_alpha1_2_report.md`
**Ran via**: `scripts/v3_harness.py` (unified pipeline; reproduced α1.1's verdict as a regression check before this run)

---

## 1. Headline (and why it must NOT be oversold)

The full_20yr same-gross α rose to **+0.4703, CI [+0.0847, +1.0032], raw p=0.0153** (cost-robust: 0.014–0.016 across the 3 scenarios), and full_20yr turnover fell to **67.9%**. Taken alone this reads like "we found the edge." **It is not.** Three independent reasons:

1. **The honest statistical gate (MT, BY family) still FAILS: p=0.0841 > 0.05.** With α1.2 added, the family is m=3 (α1, α1.1, α1.2); the BY penalty c(m)=1.833 lifts the corrected p to 0.0841. This is *exactly* what the pre-registered manifest predicted ("adding α1.2 makes BY penalty larger… α1.2 will almost certainly still FAIL MT — that is correct, not a bug"). The raw 0.0153 ignores that we have now rolled the dice 3× on the same data.

2. **The full-sample significance is regime-concentrated + long-hold-flattered, and does not survive walk-forward.** Per-window same-gross α: 2006-10 **+1.37**, 2010-14 +0.42, 2014-18 **−0.10**, 2018-22 **−0.20**, 2022-26 (OOS) +0.08. So **3/5 positive points but 2 NEGATIVE, and 0/5 windows individually exclude 0**. The OOS is only +0.082 (p=0.55 — not significant). The +0.47 full-sample number is carried by the 2006-2010 GFC-era inverse-momentum window plus the long-hold compounding effect in §2 below.

3. **The strategy has DRIFTED away from "swing" (the §2 finding).** The +0.47 is substantially a passive low-momentum buy-and-hold tilt's 20-year compounding, not swing-trading skill.

## 2. The strategy-drift finding (most important takeaway)

The full_20yr turnover (67.9%) is **lower than every 4-year sub-window** (145–209%). That is mathematically suspicious, so I decomposed it. It is **not a measurement artifact — it is a real behavioral change**:

| window | turnover | avg holding days | trades/yr | n_total_trades |
|---|---|---|---|---|
| full_20yr | 67.9% | **124.3** | **31.5** | 619 / 19.6yr |
| wf_2006_2010 | 149.0% | 61.3 | 65.3 | 252 / 3.9yr |
| wf_2010_2014 | 205.1% | 49.5 | 94.7 | 364 / 3.9yr |
| wf_2014_2018 | 145.4% | 72.7 | 70.4 | 273 / 3.9yr |
| wf_2018_2022 | 208.8% | 43.5 | 104.1 | 401 / 3.9yr |
| wf_2022_2026 | 179.1% | 58.7 | 83.7 | 352 / 4.2yr |

In the full 20-year run the strategy holds positions **~2.5× longer** (124d vs ~50d) and trades **~half as often per year** (31.5 vs 65–104). The 619 total trades — computed independently of `avg_holding_days` — confirm it: at sub-window hold rates we'd expect ~1,400 trades, not 619.

**Mechanism**: `rebal=20` + `hold_continuation` + `rank_buffer_top_n=20` means a position is kept as long as it stays in the top-20 inverse-score buffer. Over 20 years, chronically-low-momentum names settle into the buffer and become *quasi-permanent holds*. A 4-year window can't accumulate these multi-year holds, so its turnover (and its alpha) reflect genuine periodic rotation; the full run's do not.

**Implication**: rebal=20 didn't find a better swing edge — it quietly converted the swing strategy into a near-static low-momentum portfolio. The full-sample turnover (68%) and alpha (+0.47) are both flattered by this drift. The **sub-window numbers (145–209% turnover, mixed alpha) are the honest steady-state picture.**

## 3. Gate-by-gate vs the pre-registered hypothesis

- **IMPL4 (turnover ≤ 200%) — still FAIL, but partial progress.** 4/6 windows now ≤200% (vs **0/6** under α1.1). The 2 that still fail are barely over: wf_2010_2014 **205.1%**, wf_2018_2022 **208.8%**. The full_20yr "68%" pass is the drift artifact, not a clean win — the steady-state rate is the ~145–209% sub-window band.
- **MT — FAIL (BY p=0.0841).** As pre-registered. Do NOT tune toward 0.05.
- **IMPL2 (gross ≥ 30%) — FAIL (~13.8–17.1%).** Unchanged, out of α1.2 scope (→ α1.3).
- **IMPL5 (MaxDD ≥ −25%) — FAIL, slightly WORSE.** Now fails in 3 windows (full −50.7%, 2006-10 −32.9%, 2014-18 −26.4%) vs 2 under α1.1. Out of α1.2 scope (→ α1.4).
- **WF1 PASS (3/5 positive points)** — but weak: 2 windows negative, none significant.
- **WF2 PASS** — OOS not significantly negative (+0.082, p=0.55); also not positive.
- **NOSW PASS — but now precarious.** Because full-sample is now POS-significant, NOSW only passes because WF1 is *exactly* 3/5. One more negative window (2/5) would trip the "only-the-full-sample-works" guard. The strategy is sitting right on that boundary.

## 4. Verdict & honest read

α1.2 did what the pre-registration said it might: it compressed turnover further (toward, not under, the per-window gate) and **did not kill the alpha** — the point estimate rose. But:
- The strategy gate still **FAILs (4/19)**, the load-bearing MT gate still **FAILs after family correction** (0.0841), and the apparent improvement is explained by **strategy drift + regime concentration**, not a discovered edge.
- This remains a **statistical lead / execution-not-validated**. Path B is still the research battlefield; **no capital-deployment eligibility.** No p-value was tuned; the raw-p improvement is incidental and, on inspection, not the good news it first appears.

## 5. Open decision (Junyan's call)

The pre-stated branch — "conditional rebalance (α1.3) *if* rebal20 kills alpha" — **does not cleanly apply**: rebal20 didn't kill alpha, it *drifted* the strategy. So next is genuinely open. Candidate directions (each needs its own pre-registered manifest; thresholds locked before run):

- **(A) Fix the drift directly** — re-introduce a `max_hold_days` cap so positions can't become permanent. This restores "swing" behavior and makes the full-sample number honest. **Correction (verified empirically 2026-05-29):** the cap *raises* turnover, it does not lower it — on wf_2014_2018, `max_hold_days=60` moved avg-hold 72.7→41.4d and turnover 145.4→**249.6%**. So this is an anti-drift / swing-identity-restoration test, NOT turnover compression; IMPL4 turnover is expected to get WORSE. The PRIMARY question it answers: does α1.2's +0.47 same-gross α survive genuine ≤60d swing-frequency rotation, or was it passive long-hold drift? New single-variable test (α1.3A).

**Decision (Junyan 2026-05-29): proceed with (A), `max_hold_days=60`.** Not (B) conditional-rebalance (likely *increases* drift). Not (C) gross utilization (raising gross amplifies a drifted identity). Causal logic VALID for "drift exists"; QUESTIONABLE/UNESTABLISHED for the 60d threshold (structural assumption, unbacktested). 60d = 3 rebal cycles at rebal=20.

---

# α1.3A result (max_hold_days=60) + α1.x line conclusion

**Verdict: FAIL 5/19** (WF1, MT, IMPL2, IMPL4, IMPL5). Engine `max_hold_days` wired + verified non-no-op before run; manifest hash `2de57039` locked. The 60d cap restored genuine swing behavior (avg hold 124d→~38d everywhere; carry 5.8→2.9; turnover rose to 246–270%).

## The drift test resolved — α1.2's headline was an artifact

| window | α1.2 (drift, 124d holds) | α1.3A (honest swing, 38d holds) |
|---|---|---|
| full_20yr | +0.470 (p=0.015, CI excl 0) | **+0.202 (p=0.20, CI straddles 0)** |
| wf_2006_2010 | +1.372 | +1.390 (p=0.038) ← only window excl 0 |
| wf_2010_2014 | +0.423 | +0.490 (p=0.16) |
| wf_2014_2018 | −0.097 | −0.142 |
| wf_2018_2022 | −0.198 | −0.098 |
| wf_2022_2026 (OOS) | +0.082 | **−0.157** (flipped negative) |
| WF1 (≥3/5 pos point) | PASS 3/5 | **FAIL 2/5** |
| turnover | 68–209% | 246–270% (all > gate) |
| MT BY (family p) | 0.084 (m=3) | 0.562 (m=4) |

**Conclusions (decisive, but bounded to this signal family):**
1. **α1.2's +0.47 was ~half drift.** Honest rotation halved it to +0.20 and killed significance (p 0.015→0.20). Confirmed.
2. **Under honest swing rotation the strategy is net-negative recently.** OOS 2022-2026 flipped +0.082→−0.157; 3 of 5 windows now negative → WF1 fails.
3. **The only real edge is the 2008 GFC crash** (wf_2006_2010 +1.39, p=0.038 — the sole window individually excluding 0, robust even under the cap). Everything post-2010 is weak/negative.
4. **Turnover is structurally ~250%** when traded as genuine swing → IMPL4 unreachable at this rebal/horizon.
5. **MT BY family p = 0.562** (m=4) — nowhere near significant; adding α1.3A also lifted α1.2's own corrected p 0.084→0.128.

**α1.x line (α1 → α1.1 → α1.2 → α1.3A) is now thoroughly characterized: the 4-factor inverse-momentum swing concept has no tradeable standalone edge outside the 2008 crash regime.** The seductive numbers along the way were artifacts (α1's cash-holding; α1.2's long-hold drift). No curve-fit was applied; the gates + walk-forward + drift-decomposition did their job. Path B remains the research battlefield, but this *signal* is exhausted — continuing to α1.4 (MaxDD) / α1.5 (gross) would be polishing a strategy with no validated edge (violates 不能负优化).

**Open (Junyan's call): where next.** (i) Regime-conditional inverse-momentum (only trade in crash/high-vol regimes — the 2008 result suggests this is the real phenomenon); (ii) a genuinely different signal family (non-momentum — α2/α3 as currently specced are the same signal and would likely inherit the dead edge); (iii) step back and reconsider Path B's weight vs the CORE thesis engine given no swing edge is validated. Bounded claim: this falsifies *this signal*, not swing trading in general.
- **(B) α1.3 conditional rebalance** as originally planned (act only when rank-drift exceeds a locked threshold) — but note this may *increase* drift, not reduce it.
- **(C) Declare the turnover lever characterized** (α1.2 = partial pass, drift documented) and move to the next layer — α1.3 gross utilization (IMPL2) — accepting turnover stays ~150–200%.

My lean: **(A)** — the drift finding suggests the turnover problem and the "is this still a swing strategy?" problem are the same problem, and a holding-period cap addresses both. But this is a strategy-shape decision, so it's yours.
