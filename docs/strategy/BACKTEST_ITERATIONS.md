# Backtest Iteration Log — autonomous overnight run (2026-05-25/26)

> Junyan mandate: run ~10 iterations autonomously, each with **honest feedback +
> a systematic improvement method**. Morning 验收.
>
> **Discipline (the red line):** every change has an INDEPENDENT a-priori
> rationale (methodology fix / bug / standard quant practice) — NOT
> parameter-fishing to hit a target. Each change is kept only if it's principled
> AND helps; reverted otherwise. If systematic improvement is exhausted and it
> still doesn't beat the benchmark, "this approach doesn't work" is the honest
> conclusion — no curve-fit rescue.
>
> **Efficiency:** the month-end panel (~800k rows) is fetched ONCE (GHA), then
> iterations run LOCALLY on the fixed panel (seconds each). Only the
> strategy/risk/factor logic changes between iterations; the data is constant.
>
> **Headline metric:** OOS CAGR (2019+) — weights fit in-sample 2006-2018.
> Also track MaxDD, Sharpe, vs-CSI300 excess (once added), turnover.

## Baseline (run 26418580192, raw factor, NO risk, hand-set weights)
- CAGR (full, in-sample-optimistic): **-0.43%** · Sharpe 0.17 · **MaxDD -74.3%**
- Per-regime: 2008 -64% · 2015 +166% · 2018 -34% · 2020 -11% · 2022 -2% · 2024 -2%
- Verdict: FAILING. Chases bubbles, no crash protection. The honest starting point.

## Iteration ledger

| # | Hypothesis (a-priori rationale) | Change | Result (OOS CAGR / MaxDD / Sharpe) | Kept? | Honest note |
|---|---|---|---|---|---|
| 1 | Risk overlay (drawdown breaker + regime cap) + OLS-calibrated weights should cut the -74% DD and improve risk-adjusted return | risk_monitor wired into loop (FREEZE bug fixed) + calibrate_weights OLS (weights: value 0.57 / low_vol 0.26 / growth 0.17, **momentum & quality zeroed** — OLS confirms A-share monthly mean-reversion) | OOS CAGR 0.0% / IS CAGR -0.9% / **MaxDD -22.5% (was -74%)** / Sharpe -0.09 | partial | DD cut DRAMATICALLY but per-regime: 2008 -22%, all else 0.0 → **strategy went to cash in 2008 and never came back (TO_CASH is one-way, no re-entry).** Structural flaw, not tuning. Kept risk overlay; iter-2 must add re-entry. |
| 2 | Re-entry rule for risk overlay: binary breakers without re-entry = permanent cash trap (standard quant pitfall). Use rolling 24-month peak instead of all-time peak so drawdown resets naturally as market normalizes. | Replaced `peak = max(peak, equity)` with rolling 24mo max in backtest_v2 | **OOS +9.35%** / IS +6.53% / MaxDD -31% / Sharpe +0.67 / final eq 4.28 | ✅ KEPT | **HUGE win.** Principled fix (rolling peak = standard trend-following), unlocked real OOS alpha. Per-regime now sensible (2008 -22% then re-engages, 2015 +181%, 2024 +5%). |
| 3 | Need benchmark to judge if +9.35% is real alpha or just market beta. | EW-universe benchmark + alpha now in results | OOS strat 9.35% / bench 11.90% / **ALPHA -2.55%**. IS strat 6.53% / bench 13.39% / **ALPHA -6.87%** | ✅ KEPT (the reporting) | **CRITICAL honest finding:** we UNDERPERFORM equal-weight buy-and-hold by 2.55%/yr OOS. Without the benchmark we'd have called +9.35% a win. We didn't. |
| 4 | Isolate source of negative alpha: risk or factors? --no-risk + OLS weights ON | --no-risk flag | OOS strat 12.86% / bench 11.90% / **ALPHA +0.97%**. IS strat 6.89% / bench 13.39% / **ALPHA -6.50%**. MaxDD -70% | reverted (for iter-5) | **Diagnostic.** Factors have marginal +1% OOS alpha (could be luck, 7yr) and -6.5% IS alpha (OLS R²=0.001 = noise fit). Risk overlay eats more alpha than the factors generate. **Risk caps are too aggressive.** |
| 5 | Loosen risk caps to standard (regime 0.60, DD -15/-25) — preserve DD protection with less alpha drag | risk_monitor config override | OOS 10.70% / bench 11.90% / **ALPHA -1.20%** / MaxDD -44% / Sharpe 0.58 | partial | Better than iter-2 (alpha -2.55%) but still negative. **Risk overlay consistently NET-NEGATIVE on alpha across all settings.** |
| 6 | Test if OLS overfit-zeroed a real factor: revert to HAND-SET Q30/V20/M25/G15/LV10 (momentum included) | calib renamed → fallback to hand-set | OOS strat 1.41% / bench 11.90% / **ALPHA -10.49%** / MaxDD -54% | reverted | **OLS was RIGHT to zero momentum** — hand-set with momentum 0.25 was massively worse. Confirms A-share monthly mean-reversion. Restored OLS for next iters. |
| 7 | Concentration sensitivity: top-30 vs top-15 (less concentrated = closer to EW with factor tilt) | TOP_N=30 in satellite_strategy.py | OOS 10.09% / bench 11.90% / **ALPHA -1.80%** / MaxDD -42% / Sharpe 0.53 | reverted | More diversification did NOT close the gap; in fact slightly WORSE than top-15 (iter-5 -1.20%). Diversification dilutes the factor tilt without removing the deeper problem — **the factor signal itself is weak**, not the concentration. Restored TOP_N=15. |
| 8a | **Foundation rebuild attempt #1 (full Stage 1):** LSY/Li-Rao 5% mcap filter + E/P-heavy value (0.7/0.3) + Barra USE4 construction. | New: `universe_filter.py`, `factor_construction.py`, `tests/test_pit_no_look_ahead.py` (6/6 PASS — Huatai bug class blocked). Wired via 6 opt-in kwargs on `make_satellite_strategy`. Bug fix: `universe_pit.json` empty stocks=[] → silent flat-equity; now ValueError-guards. | OOS 2.37% / bench 11.90% / **ALPHA -9.53%** / MaxDD -52% / Sharpe 0.28 / final eq 1.69 | **REVERTED in 8b** | Negative shift -8.7pp OOS. **Junyan: "不能达成负优化"** → bisect: |
| 8a-bisect | Decompose iter-8 into 5 isolated variants on full 2006-2026 to pin the killer | Inline scripted bisect | A baseline 10.70%・B +LSY 11.12% (+0.42pp)・C +Barra **2.05%** (-8.65pp)・D +E/P 10.78% (+0.08pp)・E all 2.37% | diagnostic | **Barra alone caused -8.7pp OOS**. Cause: iter-1..7 OLS weights fit on 0-100 percentile inputs; Barra produces ~N(0,1) z-scores → **scale mismatch**. Filter (B) and E/P (D) are neutral-to-mildly-positive. Conclusion: enable filter+E/P in Stage 1; defer Barra to Stage 3 (with weight re-fit). |
| 8b | **Foundation rebuild attempt #2 (Stage 1 final):** LSY/Li-Rao 5% mcap filter + E/P-heavy value. **Barra OFF until Stage 3 weight re-fit.** | `--iter8` no longer turns on Barra by default; `--iter8-barra` for diagnostic. | OOS 10.50% / bench 11.90% / **ALPHA -1.40%** / IS 2.91% / MaxDD -47.14% / Sharpe 0.46 / final eq 2.94 / per-regime 2020 +14% (was +10.5%), 2022 +9.6% (was +8.0%), **2024 +12.0% (was -0.7%)**, 2015 +129% (was +185%) | ACCEPTED (Junyan) | **Mixed result, accepted as net-positive risk-profile shift.** OOS +0.41pp (noise level). Recent regimes (2020/22/24) clearly improved by +3.6/+1.7/+12.7pp. 2015 bubble dependency cut -55pp (good for live deployment). MaxDD -4.84pp worse (acceptance cost). IS down -1.91pp because LSY filter cuts the very small-cap shell-stock-driven 2015 bubble. The methodology improvement is real even when the headline number is noise-level — the cost is the strategy is less bubble-dependent. **Proceeds to Stage 2 IC analysis.** |
| 8c | **Stage 2 IC analysis** — cross-sectional Spearman(factor, fwd_return) per month-end × 4 horizons (1/3/6/12 month), time-series mean + t-stat + ICIR, then BH-Yekutieli FDR + Harvey-Liu-Zhu t>3.0 reference (multiple-testing correction). | New: `ic_analysis.py` (~280 LOC), `multiple_testing.py` (~250 LOC). Bug caught during exec: panel is MONTH-END bars (245 over 20yr), so my initial run with horizons=[21,63,126,252] treated each as MONTH not day → IC at 21-MONTH-forward, hugely inflated t-stats. Re-ran with horizons=[1,3,6,12] for true monthly horizons. | **1-month IC verdict per factor:** **value** mean=+0.055 t=+5.40 ICIR=0.36 → **PASS**; **low_vol** mean=+0.046 t=+4.77 ICIR=0.31 → **PASS**; **momentum** mean=-0.022 t=-2.66 → MAYBE (BH-Y pass, HLZ fail); **quality** mean=-0.011 t=-1.41 → **NOISE**; **growth** mean=+0.009 t=+1.63 → **NOISE**. | DECISIVE | **Honest stage-2 verdict (the heart of iter-8):** at the monthly rebalance horizon, only **value and low_vol** have predictive power that survives both BH-Y FDR adjustment AND the conservative HLZ t>3.0 reference. Quality and growth are statistically indistinguishable from noise. Momentum weakly mean-reverts but fails HLZ. **This confirms our OLS calibration was structurally correct (M=Q=0) but gave growth too much weight (0.17 — should be 0).** Refit recommendation: V≈0.70 / LV≈0.30, drop everything else. 3-month and longer horizons show all factors strengthening — suggests QUARTERLY rebalance would harvest more signal than monthly. |
| 8d | **Stage 3a OLS refit V+LV-only** with LSY filter applied to in-sample window | `calibrate_weights.py --factors value,low_vol --apply-universe-filter` | V=0.8243, LV=0.1757, R²=0.00077 (in-sample 2006-2018, n_obs=265k) | informational | OLS picks Stage 2's surviving factors at ratio close to IC ratio. |
| 8d-bonus | **Stage 3a OLS refit V+LV+G** (3-factor) with LSY filter | `calibrate_weights.py --factors value,low_vol,growth --apply-universe-filter` | V=0.8297, LV=0.1703, **G=0 (zeroed by OLS)** | DECISIVE | **Triple convergence**: IC + multi-test + OLS-with-filter all zero growth. iter-7 G=0.17 came from SHELL-STOCK NOISE in unfiltered calibration. |
| 8e | **Stage 3b 2-factor backtest** (V/LV refit OLS + LSY filter + E/P-heavy) | `--iter8` with calib_weights_stage3.json active | OOS 5.11% / bench 11.90% / **ALPHA -6.8%** / IS 7.89% / MaxDD -39.1% / Sharpe 0.52 / final 3.79 / 2008 -25.5% / 2024 +6.9% | informational (-5.4pp OOS vs Stage 1b) | The 5pp OOS loss vs Stage 1b is OOS LUCK lost — keeping G=0.17 captured shell-noise that happened to deliver in 2019-2026 but was zero in IS-OLS-with-filter. The HONEST signal-only strategy underperforms by an extra 5pp vs the contaminated one. |
| 8f | **Stage 3c Stationary bootstrap** (Politis-Romano 1994, B=10000, block=6mo) on Stage 1b (best candidate, with iter-7 OLS weights + LSY filter) | `stationary_bootstrap.py --strat …stage1b…` | **Full period (2006-2026) ALPHA annualized: point = -9.4% / 95% CI = [-21.3%, +2.2%] / p=0.115 — straddles 0.** **OOS-only (2019+) ALPHA annualized: point = -2.0% / 95% CI = [-11.1%, +8.7%] / p=0.69 — straddles 0.** | DECISIVE | **THE GATE TRIPS — synthesis-doc Verdict A:** at α=0.05, we CANNOT distinguish the strategy from zero-alpha vs EW universe. Both full-period (-9.4% point) and OOS-only (-2.0% point) cross zero. **No statistical evidence of edge.** |
| 8g | **Stage 3d FF attribution** (4-factor OLS regression of strategy returns on MKT/SMB/HML/WML factors built from PIT panel) | `ff_attribution.py --strat …stage1b…` (fixed 2 bugs along the way: SMB percentile-group call, factor-strat date misalignment) | n=225 months. **residual α monthly +0.44%, t=+1.81, p≈0.07 — NOT significant.** **residual α annualized +5.45%**. β_MKT=+0.40 t=+14.6, β_SMB=-0.15 t=-2.4, **β_HML=+0.20 t=+3.65 (significant value tilt)**, **β_WML=-0.23 t=-3.10 (significant anti-momentum tilt)**. R²=0.52. | DIAGNOSTIC | **Refines the bootstrap finding**: the -9.4%/yr "alpha vs EW" is largely β_MKT=0.4 (i.e. only 40% market exposure → miss 60% of market rally). The TRUE residual α after stripping factor exposures is +5.45%/yr but t=1.81 still does NOT clear 1.96. The strategy IS distinct from EW (significant HML + WML exposures = factor product, not alpha). **Institutional reading: this satellite is paid factor exposure, not residual alpha.** Verdict A unchanged: no statistically demonstrable edge BEYOND factor exposures. |
| **9** | **CORE thesis IC pilot** — apply the iter-8 statistical toolkit (Spearman IC + multi-testing) to CORE theses, not factors. The "dual" of iter-8's satellite IC. | New: `scripts/thesis_eval.py` (~330 LOC). Parses 25 thesis JSONs from `docs/research/factcheck/`, extracts `_quality.score`, `_direction`, pipeline version. Pulls forward return per thesis_date from monthly panel. Adds `h_latest` best-effort horizon since the panel only extends 25 days past thesis_date. | **Pipeline mean quality**: 1438BST=90 / GROUNDED=90 / PHASE1.5=84 / MULTIAGENT=77.5 / PHASE2=83 (lower = stricter QC, not regression). **Direction tracking @ ~25 days**: ticker-level n=2: BYD LONG ✗ (-6.8%), 大参林 SHORT ✓ (+9.5%). **Spearman IC quality vs directional return (n=4): -0.77**. | INSUFFICIENT N — INFRA READY | **Cannot reach inferential verdict** with only 2 actionable theses (n=2 collapsed; n=4 with pipeline duplicates). Spearman -0.77 is statistically meaningless at this sample. Honest deliverable: framework ready, re-run quarterly as sample grows toward n≥20. Path-B + Rule-X discipline from 2026-05-15 explicitly designed for slow accumulation — this is the same discipline applied at the EVALUATION layer. Early signal that *higher quality score did not = better forward return* (BYD scored highest but lost; 大参林 scored lower but worked) is provocative but should NOT change action until n grows. |

_(appended each iteration)_

## Improvement backlog (principled, ordered)
1. ✅ queued — Risk overlay + OLS calibration (iter 1)
2. Sector-neutralize the factor composite (avoid single-sector loading) — uses universe_pit industry
3. Liquidity/size filter at SELECTION (drop illiquid/micro-cap so returns are tradeable)
4. Benchmark: compute excess return vs CSI300 (alpha, not just absolute) — needs index series
5. Factor IC analysis → drop factors with ~0 predictive power (R²=0.0008 hints noise)
6. Rebalance frequency: monthly vs quarterly (turnover/cost)
7. Factor winsorize / robust z-score (outlier resistance)
8. Full risk-monitor integration (per-position stops + vol targeting, not just gross)
9. Concurrent-positions / concentration robustness (report a range, no cherry-pick)
10. Transaction-cost / T+1 fill-precision realism check

## Iter-8 final verdict (Stage 1+2+3 complete)

### The honest verdict (per `RESEARCH_SYNTHESIS_2026-05-26.md` Decision Gate)

**Verdict A triggers: the satellite has NO statistically demonstrable
edge over EW A-share buy-and-hold over 2006-2026.**

Triple statistical convergence drove the verdict:

1. **IC analysis (Stage 2a)**: at monthly rebalance horizon, only `value`
   (t=+5.40) and `low_vol` (t=+4.77) clear BH-Yekutieli FDR + HLZ t>3.0.
   Momentum / quality / growth all NOISE.

2. **Multiple-testing (Stage 2b)**: 16 / 20 factor-horizon pairs PASS;
   3 NOISE; 1 MAYBE. At the 1-month horizon (the rebalance horizon) only
   V and LV pass — same as Stage 2a.

3. **OLS refit with LSY filter (Stage 3a)**: applying the LSY/Li-Rao
   shell-stock filter during IS calibration → OLS zeroes growth (G=0).
   Compares to iter-7 which had G=0.17 fit on UNFILTERED data. **Triple
   convergence: IC + multi-test + OLS-with-filter all agree the iter-7
   G weight was shell-stock noise**.

4. **Stationary bootstrap on alpha (Stage 3c, Politis-Romano B=10000
   block=6mo)**:
   - Full period 2006-2026 alpha annualized = -9.4% [-21.3%, +2.2%] — straddles 0
   - OOS-only 2019+ alpha annualized = -2.0% [-11.1%, +8.7%] — straddles 0
   - p-value H0:α=0 = 0.69 → cannot reject

5. **FF attribution (Stage 3d)**: residual α (after stripping
   MKT/SMB/HML/WML exposures) = +5.45%/yr, t=+1.81, p≈0.07 — still NOT
   significant at α=0.05. The strategy IS distinct from EW (β_HML=+0.20
   t=+3.7, β_WML=-0.23 t=-3.1) — but that's **factor exposure, not
   alpha**.

### What this VALIDATES

**The USP_VISION dual-track architecture (2026-05-25 lock):**
- **SATELLITE = systematic breadth** (this is what we just measured —
  it provides factor exposure, not alpha; per institutional finding
  factor-tilted indexes ARE paid factor risk-premia, NOT alpha).
- **CORE = thesis-driven, hedge-fund-logic, LLM-curated** (the alpha source).
- Stage 3 confirms: the moat must be in CORE, not SATELLITE.

### What we ship from iter-8 (substantive permanent improvements)

| Artifact | Purpose |
|----------|---------|
| `tests/test_pit_no_look_ahead.py` (6/6 PASS) | Huatai-NSGA2 bug class structurally impossible. P0 regression guard. |
| `scripts/universe_filter.py` | LSY/Li-Rao 5% mcap shell-stock filter |
| `scripts/factor_construction.py` | Barra USE4 (disabled in prod; preserved for Stage 3 re-fit if revisited) |
| `scripts/ic_analysis.py` | Cross-sectional IC + time-series t-stat + multi-horizon decay |
| `scripts/multiple_testing.py` | BH-Y FDR + HLZ + Deflated Sharpe |
| `scripts/stationary_bootstrap.py` | Politis-Romano 1994 CI; primary inference tool going forward |
| `scripts/ff_attribution.py` | 4-factor decomposition; separates exotic-beta from residual α |
| E/P-heavy value blend (`pit_factors.CONFIG`) | LSY 2019 finding incorporated |
| `docs/strategy/RESEARCH_SYNTHESIS_2026-05-26.md` | The plan we executed against |
| `docs/strategy/research_2026-05-26/{textbook,institutional,xhs}_synthesis.md` | The three pillars of background reading |

### What we do NOT claim

- The satellite has any specific OOS CAGR — the CI straddles benchmark
- iter-7 OOS 10.09% is "real" — it's a POINT inside a CI that crosses zero
- Growth has predictive power — triple-rejected
- iter-1..7 backtests "prove" anything beyond "infrastructure works"

### What's next

Stop tuning satellite parameters. **Redirect dev to the CORE thesis
engine** (per USP_VISION.md). The honest-statistics toolkit from iter-8
(IC + multi-test + bootstrap + FF) is reusable for evaluating CORE
thesis quality — already a positive externality.

The "宁愿犯错也不愿意找不出来错误在哪" discipline produced an
auditable, defensible NO-ALPHA verdict in 8 iterations + 4 stages of
formal statistics. That is the deliverable.

---

## Old morning summary — pre-Stage 2/3 (iters 1-7 only)

### The headline finding (honest)
**The current systematic factor strategy does NOT have reliable alpha vs equal-weight A-share buy-and-hold.**

Across 7 iterations with principled, independent variations:
- Best OOS absolute: iter-2 (+9.35%) and iter-4 (+12.86%) sounded good — but the **EW universe returned 11.90% OOS**.
- Best OOS *alpha*: iter-4 (no risk, OLS) at **+0.97%/yr over 7 years** — small-sample, borderline noise (R²=0.001).
- Every other variant: NEGATIVE OOS alpha (-1.20% to -10.49%).
- **In-sample alpha is brutally negative across ALL variants** (-6.50% to -10.49%) — the factor approach itself didn't add value over EW in 2006-2018.
- **Concentration sensitivity (iter-7):** top-30 (more diversified) was slightly WORSE than top-15 — alpha -1.80% vs -1.20%. The problem is signal weakness, not portfolio construction.

### What we learned (each iteration earned its keep)
1. **Risk overlay is consistently a NET DRAG on alpha** (3.5% at tight caps, 2.2% at loose, +1% only with risk OFF). It cuts MaxDD dramatically (-74% → -31%) but at meaningful return cost. It's a TAIL HEDGE not an alpha source.
2. **Rolling 24-month peak (iter-2) was THE big methodology fix** — without it, the strategy goes to cash in 2008 and never re-engages.
3. **OLS calibration > hand-set priors**, but only because it correctly zeroed momentum + quality (iter-6 proved hand-set is much worse).
4. **A-share monthly momentum is ANTI-PREDICTIVE** (OLS coef negative). Academic mean-reversion finding confirmed empirically.
5. **Benchmark reporting (iter-3) is non-negotiable** — without it, +9.35% looks like a win; with it, it's a -2.55% alpha LOSS.
6. **Concentration is not the problem (iter-7)** — going from top-15 to top-30 hurt alpha. Adding more names dilutes the (already weak) factor tilt without removing the underlying signal weakness.

### What's NOT yet tested (clear next-session path)
**The most informative next step is NOT another strategy variant — it's STATISTICAL RIGOR on whether the factors have predictive power at all:**

**iter-8 (recommended): IC analysis** — for each factor, compute cross-sectional Spearman rank correlation (factor_score, fwd_return) at each month-end → time-series mean IC + t-stat + ICIR + decay. This DIRECTLY tells us whether each factor has any predictive power, with proper statistical inference (the R²=0.001 from pooled OLS hid this). If momentum IC t-stat < 1 → confirms OLS-zero was right. If any factor has IC t-stat > 2 → it's a real edge worth keeping.

**iter-9: Fama-MacBeth + Ridge regression** — proper t-stats on factor returns (pooled OLS got SEs wrong). Ridge handles factor correlation in small samples.

**iter-10: Walk-forward rolling calibration** — every 3yr refit on trailing 5yr instead of single-window. Robust to regime shifts.

### The deeper honest finding
**Better statistics will give better INFERENCE about how weak the factors are; they will not create alpha that isn't there.** The USP_VISION.md hypothesis was always that the moat comes from the *双层认知* depth (policy decoding + narrative-gap + multi-framework convergence), NOT from a linear factor model on monthly A-share data. This backtest evidence supports that — pure quant factors on A-share month-end don't beat EW. The hedge-fund-logic CORE track (thesis-driven research with E1 evidence, per the Path-B arc) was always supposed to be the alpha source; the satellite track was supposed to be systematic breadth. The honest backtest says: **the satellite, as currently built, doesn't add alpha; ship the CORE first.**

### What I'd do next if continuing
1. iter-8 IC analysis (above) — definitive factor-by-factor verdict.
2. If any factor IC t-stat > 2 → keep it, drop others, refit.
3. If no factor has real IC → **acknowledge the satellite track has no edge as currently built**, redirect effort to CORE (the LLM thesis engine) which has different signal.
4. Consider alternative factor families (analyst revisions, retail-sentiment from 雪球/东财 per USP_VISION — these are the moats that linear factors can't replicate).

### Files / commits (clean handoff state)
- All code committed to `main` (latest: `352dad6` iters 1-3 + earlier `fe7c7ea`/`ae70ded` for risk/calib).
- Iteration log: `docs/strategy/BACKTEST_ITERATIONS.md` (this file, iters 1-7 complete).
- Result JSONs: `public/data/backtest_results_v2.json` (last = iter-7), `public/data/backtest_results_iter{4,5,6,7}.json`.
- Local panel: `data_history/panel/{prices,financials}.parquet` (38MB, gitignored).
- Calibrated weights: `public/data/calib_weights.json` (OLS: value 0.57 / low_vol 0.26 / growth 0.17, momentum & quality zeroed).
- STATUS.md current.

A fresh session can read STATUS.md + this file and pick up at "iter-8 IC analysis."
