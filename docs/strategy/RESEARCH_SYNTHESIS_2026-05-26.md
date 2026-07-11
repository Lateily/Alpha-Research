# Research Synthesis & Iter-8 Plan — 2026-05-26

_Synthesized by Claude T1, drawing on three parallel research streams:_
1. **Textbook pillar**: Guo/Lai/Shek/Wong, "Quantitative Trading" (CRC Press),
   chapters 2.4–2.8 + 3.1 → `research_2026-05-26/textbook_synthesis_lai.md`
2. **Institutional pillar**: AQR / MSCI Barra / Liu-Stambaugh-Yuan / Hou-Xue-Zhang
   / WorldQuant + honest gap-analysis on GS QIS / Two Sigma / BlackRock →
   `research_2026-05-26/institutional_synthesis.md`
3. **XHS inspiration**: 7 posts (Keleve / GS-skill / Huatai-NSGA2 / VIX / Codex /
   vibe-coding warning / Claude-agent) → `research_2026-05-26/xhs_inspiration.md`

**Honest red line preserved**: 宁愿犯错也不愿意找不出来错误在哪. iter-8 is NOT
designed to manufacture alpha. It is designed to **honestly determine whether
any factor in our 5-factor universe has predictive power on A-share monthly
returns,** with proper statistics that previously hid the answer.

---

## I. The most important meta-finding

**The 华泰 NSGA-II case (XHS post 3) is direct empirical vindication of our
PitDataStore PIT firewall.**

Someone replicated a Huatai sell-side high-frequency factor mining report
using NSGA-II multi-objective genetic optimization, got 690% backtest return
(2019-2026, 33% CAGR, Sharpe 2-5 in good years), published it. The community
found a 1-line look-ahead bug: `B_shift_lag = [..., -1, -2, ...]` used FUTURE
data. The entire 690% is contaminated.

Our PitDataStore architecture (refuses to expose data with `ann_date > as_of_T`)
makes this bug class **structurally impossible**. **This is the
highest-confidence ROI of all our 2026-05 infrastructure work.**

**Corollary for iter-8**: do NOT skip the PIT audit when adding new factors.
"Just compute IC on forward returns" is exactly where look-ahead sneaks in
(via centering / smoothing / look-back at future ann_date). Iter-8 must add
an explicit look-ahead unit test (described in Stage 1d below).

---

## II. What each pillar tells us

### Textbook pillar (statistical machinery)

| Method | Verdict | What it ADDS to iter-1..7 |
|--------|---------|---------------------------|
| **Harvey-Liu-Zhu multiple testing + BH-FDR + Deflated Sharpe** | **HIGH** | t-stat > 2 → t-stat > 3.0; raw Sharpe → Deflated; BH-adjusted p-values for our 5 factors |
| **Politis-Romano stationary bootstrap** | **HIGH** | Point estimate "alpha = +0.97%" → "+0.97% [95% CI: ?, ?]" — direct test of whether CI straddles 0 |
| **Ledoit-Wolf covariance shrinkage** | HIGH (when optimizer added) | Replaces sample Σ in any risk model |
| **Bayes-Stein on µ** | MEDIUM-HIGH | Only useful if iter-8 adds MV optimizer |
| **Black-Litterman** | LOW (wrong tool) | Designed for multi-asset macro overlay, NOT cross-sectional equity |
| **NPEB (Lai-Xing-Chen 2011)** | MEDIUM (defer) | >500 lines, defer to iter-9+ |
| **FF-style attribution** | HIGH (diagnostic) | Decompose +0.97% into exotic-beta (compensated factor premia) vs residual |

### Institutional pillar (A-share specific construction)

These OVERRIDE generic factor wisdom for A-share:

1. **A-share universe filter** (Liu-Stambaugh-Yuan 2019 + Li-Rao 2022):
   exclude bottom 30% mcap (shell stocks) — or ESP-probability threshold
   (post-2017 reform). Re-including legitimate small-caps lifts SMB 0.46→0.74%/mo.
2. **E/P, not B/M** for value in A-share (LSY CH3). B/M is dominated by E/P.
3. **HMXZ q-factor finding**: investment factor carries NEGATIVE premium in
   China (opposite of US). Profitability still works but signed differently.
4. **MSCI 2024 China**: HDY + low-vol consistently outperform; momentum does
   NOT lead like global markets (matches our OLS zeroing momentum).
5. **PMO (turnover sentiment)** is the A-share-specific 4th LSY factor.

Concrete factor-construction upgrades (Barra USE4 methodology):
- Winsorize descriptors at ±3σ cross-sectionally per date
- Standardize to cap-weighted mean = 0, equal-weighted std = 1
- Cross-section regress on (country + industries + styles) via WLS √mcap
- Industry-neutralize via residual regression, NOT subtraction
- Multi-horizon IC (h ∈ {21, 63, 126, 252}d) before committing to monthly

### XHS pillar (inspiration / warnings)

- **Keleve 7-Tier**: multi-trigger exit factorization (5 independent triggers
  vs our 1 DD breaker)
- **GS skill framework**: multi-decade comparison + multi-source triangulation
  + narrative-title chart structure — for CORE thesis output, not satellite
- **华泰 NSGA-II**: PIT firewall vindication (see meta-finding above)
- **VIX 鞋童**: contrarian sentiment regime signals (A-share equivalents:
  iVX + retail account opening)
- **Codex 复盘**: daily operational HTML dashboard pattern (we have JSON only)
- **vibe-coding warning**: "UI pretty, data shaky" trap — reinforces honest
  discipline as differentiator

---

## III. Iter-8 execution plan (concrete, 5 stages)

### Stage 0: Pre-flight

- **Lock iter-7 state**: ALL files committed (already done in 5f4e37c).
- **Read this doc**: confirm scope.
- **Branch off**: iter-8 work happens on a fresh branch — `iter-8/ic-analysis`.

### Stage 1: Foundation rebuild (must precede statistical work)

Order matters — universe filter changes panel size, which changes z-score
percentiles, which changes everything downstream.

**1a. A-share universe filter (LSY-style proxy)**
- Implementation: in `scripts/universe_filter.py` (new), exclude stocks where:
  - bottom 5% market cap cross-sectionally per date, AND
  - turnover > 2× cross-sectional median (shell proxy from Li-Rao)
- Optionally compute ESP score per stock if data permits.
- Effect: panel drops from ~5000 to ~4500 names; size factor cleans up.

**1b. Value factor: B/M → E/P primary**
- Modify `scripts/pit_factors.py::_value`:
  - Change descriptor from book/price to earnings/price (or composite both
    with 70/30 weight per LSY evidence).
  - Use trailing-4Q E/P, not single-quarter.

**1c. Barra-style factor construction (replace raw z-score)**
- New module `scripts/factor_construction.py`:
  - `winsorize(x, lo=0.01, hi=0.99)` — or ±3σ
  - `cap_weighted_standardize(x, mcap)` — mean-zero in cap-weighted space,
    std-1 in equal-weighted space
  - `industry_neutralize(x, industry)` — residual from
    `x ~ industry_dummy` cross-sectional regression
- Modify `satellite_strategy.py` to call this pipeline before composite.

**1d. PIT firewall re-audit + explicit look-ahead unit test**
- Add `tests/test_pit_no_look_ahead.py`:
  - Construct fixture with known future-data injection at T+1.
  - Confirm `PitDataStore.get(...as_of=T)` REFUSES the future data.
  - Confirm `pit_factors.compute_factors(as_of=T)` produces SAME output
    whether or not T+1 data exists in store.
  - This directly tests the 华泰 NSGA-II bug class.

**Stage 1 verification gate**: re-run iter-7 backtest with new panel. Expect
results to **shift, not necessarily improve**. Document the shift in
`BACKTEST_ITERATIONS.md` as iter-7.5 (sanity check).

### Stage 2: The actual IC analysis (the headline iter-8 work)

**2a. Per-factor multi-horizon IC**

New module `stats/ic_analysis.py`:
- For each factor F ∈ {value(E/P), quality, momentum, growth, low_vol}:
  - At each month-end T in [2006, 2026]:
    - Compute cross-sectional Spearman rank correlation:
      `IC[F, T, h] = spearman(F[T], fwd_return[T → T+h])`
      for h ∈ {21, 63, 126, 252} trading days.
  - Time series of IC across T.
  - Statistics per factor × horizon:
    - mean IC
    - std IC
    - **t-stat** = mean / (std / √n)
    - **ICIR** = mean / std
    - decay profile across horizons

**Output**: a 5×4 table (factors × horizons) of (mean IC, t-stat, ICIR).

**2b. Multiple-testing correction**

New module `stats/multiple_testing.py`:
- For the 5 factor t-stats at their MAX-IC horizon:
  - Compute raw p-values
  - Apply Benjamini-Hochberg-Yekutieli (dependence-robust FDR) → adjusted p-values
  - Apply Harvey-Liu-Zhu reference: is raw t-stat > 3.0?
  - Apply Bailey-López de Prado Deflated Sharpe Ratio with
    N = (iter-1..7 spec-trials) ≈ 7+ → adjusted Sharpe
- Per-factor verdict:
  - **PASS** = BH-adjusted p < 0.05 AND HLZ t > 3.0 AND DSR > 0
  - **MAYBE** = passes one but not all
  - **NOISE** = fails all three

**2c. Decision per factor**: kept (PASS or MAYBE with strong domain reason) /
dropped (NOISE).

### Stage 3: Honest CI on the surviving strategy

If Stage 2 leaves ≥1 factor with edge:
- Refit weights using OLS / Bayes-Stein on the surviving factors only.
- Re-run backtest → "iter-8 candidate".
- **Stationary bootstrap** with B = 10,000 paths, block length L = 6 months:
  - 95% CI on full-period alpha
  - 95% CI on Sharpe
  - 95% CI on CAGR
- **Verdict gate**: if 95% CI on alpha straddles zero → halt + ACKNOWLEDGE
  satellite has no edge as currently built. Do NOT cherry-pick subsample.

### Stage 4: Attribution

Regardless of Stage 3 outcome:

**FF-style return attribution** in `stats/ff_attribution.py`:
- Regress iter-8 portfolio monthly returns on:
  - Market (CSI300 excess over rf)
  - SMB (A-share size factor, computed in-panel)
  - HML (A-share value factor, computed in-panel)
  - WML (A-share momentum factor)
  - QMJ (A-share quality factor, optional)
- Report alpha + factor loadings + t-stats.

**This answers**: how much of headline +0.97% (or whatever iter-8 produces)
is **exotic beta** (compensated factor risk premium — NOT alpha) vs **residual
active alpha**.

### Stage 5: Honest verdict + document

Update `BACKTEST_ITERATIONS.md` with iter-8 ledger row. Update `STATUS.md`.

Two possible verdicts (both legitimate):

**Verdict A** (likely): No factor passes Stage 2 multi-test, OR Stage 3 CI
straddles zero, OR Stage 4 attribution shows residual alpha is statistically
indistinguishable from zero. → **"Satellite has no edge as currently built;
redirect to CORE thesis engine."**

**Verdict B** (possible but lower-probability per priors): one or more
factors clear all hurdles → **"Statistically supported alpha = X% [95% CI
{lo, hi}], with FF-attribution {α: Y%, market: β1, SMB: β2, ...}."** Keep
those factors; drop others; refit.

**Either way, the iter-8 deliverable is auditable statistics, not a number.**

---

## IV. What's explicitly REJECTED for iter-8 (defer/skip)

To avoid scope-creep and curve-fitting risk, these are NOT in iter-8:

- **Black-Litterman**: wrong tool for cross-sectional equity (see textbook pillar)
- **NPEB**: too heavy (>500 lines, density estimation + Monte Carlo)
- **NSGA-II / GA factor mining**: high overfitting risk + 华泰 bug case warns
  against this class without rigorous look-ahead audit
- **WorldQuant 101 alphas**: signal-zoo expansion — defer to iter-10+ after
  honest verdict on current 5
- **Daily HTML dashboard (Codex-style)**: nice-to-have but doesn't change
  whether alpha exists — defer to post-iter-8
- **5-trigger exit factorization**: extension of risk_monitor — defer; iter-8
  is about FACTORS not EXITS
- **iVX / retail-account sentiment regime**: defer (TBD whether Tushare exposes
  these — current 15000-tier might not include)

---

## V. Effort estimate + execution mode

| Stage | LOC est. | Time est. | Mode |
|-------|----------|-----------|------|
| 1a universe filter | ~60 | 30 min | T1 self |
| 1b E/P value | ~30 | 20 min | T1 self |
| 1c Barra construction | ~150 | 1 h | T1 self |
| 1d PIT look-ahead test | ~80 | 30 min | T1 self |
| **1 verification gate** | — | 15 min (1 backtest run) | T1 verify |
| 2a multi-horizon IC | ~200 | 2 h | T1 self / can delegate to T3 |
| 2b multiple testing | ~150 | 1 h | T1 self |
| 2c per-factor decisions | — | 30 min | Junyan + T1 |
| 3 bootstrap CI | ~100 | 1 h | T1 self |
| 4 FF attribution | ~80 | 1 h | T1 self |
| 5 document | — | 30 min | T1 self |

**Total: ~850 LOC, ~7-9 hours T1 effort.** Can run in one extended session;
the user previously did 7 iterations overnight, so this fits in similar window.

---

## VI. Open questions for Junyan

1. **Universe filter strictness**: LSY 30% bottom vs Li-Rao 5% bottom + turnover
   proxy vs full ESP score? (We don't have shareholder-structure data for full
   ESP; recommend the 5% + turnover proxy.)
2. **Value descriptor**: pure E/P, or composite (E/P + B/M, weighted)? (LSY
   says E/P dominates, but a 70/30 blend is conservative.)
3. **Industry classification source**: we have CITICS industry in
   `universe_pit`; OK to use?
4. **Bootstrap subsample treatment**: A-share 2006-2025 covers 2007 bubble,
   2015 crash, 2020 reform. Recommend running bootstrap **including** these
   AND a sub-bootstrap **excluding** 2007-2008 + 2015 — report both.
5. **Decision threshold**: HLZ t>3.0 is US-calibrated, conservative. Junyan
   wants stricter or looser?

These can be defaulted (recommendations above) and overridden later if Junyan
disagrees — should NOT block start of Stage 1.
