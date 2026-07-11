# Iter-8 Literature Synthesis: Statistical Methods for Factor Backtests

_Source: Guo / Lai / Shek / Wong, "Quantitative Trading: Algorithms, Analytics,
Data, Models, Optimization" (CRC Press; Chinese tr. 高等教育出版社, "应用统计学丛
书 #23"). Targeted chapters 2.4–2.8 and 3.1. Synthesized 2026-05-26 by background
research agent._

## Executive verdict (TL;DR)

iter-1..7 results have three identifiable failure modes that the Lai textbook
chapters address. In order of impact for our specific setup (5 factors, monthly
rebal, 240-month sample, top-15 long-only, R²=0.001):

1. **Multiple-testing inflation (Ch 2.8.5)** — HIGH priority, LOW cost. With 5
   factors we already have ~5× Type-I inflation; with the iter-1..7 spec-trial
   count the effective hurdle is much higher. Adopt **Harvey-Liu-Zhu (2016) + BH
   FDR + Deflated Sharpe Ratio**.
2. **Backtest CI under serial correlation (Ch 2.4.3)** — HIGH priority, LOW
   cost. Our +0.97% alpha has no CI accounting for monthly autocorrelation.
   Adopt **Politis-Romano stationary bootstrap** for alpha/Sharpe CIs.
3. **Estimation error in expected returns (Ch 2.4.2 / 2.5)** — MEDIUM priority,
   MEDIUM cost. OLS-on-pooled-stock-months treats every coefficient as point
   estimate. Adopt **James-Stein/Jorion Bayes-Stein on µ + Ledoit-Wolf on Σ**.
   NPEB is stronger but heavier — defer to iter-9+.

## Master table

| # | Chapter | Method | Canonical paper | Verdict | Cost | What it REPLACES in our pipeline |
|---|---------|--------|-----------------|---------|------|----------------------------------|
| 1 | 2.8.5 | Multiple-testing (HLZ / BH-FDR / Deflated Sharpe) | Harvey-Liu-Zhu 2016 RFS 29(1):5-68; Benjamini-Hochberg 1995 JRSS-B; Bailey & López de Prado 2014 JPM 40(5):94 | **HIGH** | LOW (~80 lines) | t>2 thresholds → t>3.0 (HLZ) or BH-adjusted; raw Sharpe → Deflated Sharpe |
| 2 | 2.4.3 | Stationary bootstrap | Politis & Romano 1994 JASA 89:1303 | **HIGH** | LOW (~100 lines or `arch.bootstrap`) | Point estimate of alpha/Sharpe/CAGR → 95% CI; bootstrap p-value |
| 3 | 2.4.2 | Ledoit-Wolf covariance shrinkage | Ledoit & Wolf 2003 JEF 10:603; 2004 JPM 30(4):110 | **HIGH** | LOW (sklearn one-liner) | Sample Σ → shrunk Σ wherever risk model uses it |
| 4 | 2.4.2 | Bayes-Stein shrinkage of µ | Jorion 1986 JFQA 21(3):279 | **MEDIUM-HIGH** | LOW (~40 lines) | OLS-pooled µ → shrunk-toward-grand-mean µ (only if iter-8 introduces optimizer-based weighting) |
| 5 | 2.4.2 | Black-Litterman | Black & Litterman 1992 FAJ 48(5):28 | **LOW for our setup** | MEDIUM (200+ lines) | Wrong tool for cross-sectional equity factors — see notes |
| 6 | 2.5 / 2.5.3 | NPEB (nonparametric empirical Bayes) | Lai-Xing-Chen 2011 AoAS 5(2A):798 | **MEDIUM (defer to iter-9+)** | HIGH (>500 lines + nonparametric density) | Plug-in µ,Σ → empirical-Bayes-corrected rule |
| 7 | 2.7.2 | IR-on-efficient-frontier | textbook §2.7.2; LXC 2011 | **LOW** | MEDIUM | Sharpe → IR maximization (only if benchmark-relative mandate) |
| 8 | 3.1.2 | Exotic-beta vs active-alpha decomp | Carhart et al. 2014 SSRN 2499728 | **LOW-MEDIUM** (diagnostic only) | MEDIUM | Pure-alpha claim → decomp into (compensated factor premia + residual alpha) |
| 9 | 3.1.3 | Integrated BL + exotic beta + risk parity | Carhart et al. 2014 | **LOW** | HIGH | Designed for multi-asset overlay, not single-equity cross-section |

**Adjacent methods worth adopting** (not in Lai TOC but same priority window):
- **Harvey-Liu (2021) "Lucky Factors"** JFE 141(2):413 — JFE-published refinement
  of HLZ specifically for factor screening via bootstrap with
  H0:no-cross-sectional-power. Direct successor; consider in lieu of HLZ 2016.
- **White's Reality Check (2000) / Hansen SPA (2005) / Romano-Wolf stepwise
  (2005)** — multiple-testing-aware backtest evaluation across competing model
  variants. Relevant since we've tried >1 spec per factor across iter-1..7.

## Why each verdict, in detail

### 2.8.5 Multiple testing — adopt FIRST

OLS reports each factor's t-stat in isolation. With 5 factors and ~240 monthly
obs, P(≥1 spurious t>2 under H0) ≈ 1 − 0.95⁵ ≈ 23%. With the iter-1..7
spec-trial count, the effective Type-I rate is hopelessly inflated. **Our
+0.97% alpha with R²=0.001 is exactly the scale of result expected under H0 +
selection bias.**

Adopt all three: BH-adjusted p-values for 5 factors; HLZ t>3.0 hurdle check;
Deflated Sharpe with N = total spec-trials across iter-1..7.

Caveats:
- HLZ t>3 calibrated on US 1967-2014; conservative-by-design reference, not
  A-share law. Use as sanity check, not definitive cutoff.
- BH-FDR assumes independence / positive regression dependence; our 5 factor
  t-stats are correlated (value-momentum). Use **BH-Yekutieli** (dependence-robust
  version) to be safe.

### 2.4.3 Stationary bootstrap — adopt SECOND

OLS SEs on alpha assume i.i.d. residuals. Monthly equity factor returns have
autocorrelation (momentum reversal, vol clustering) → OLS understates true
uncertainty. Newey-West HAC partially fixes but gives point estimates only — no
CI on CAGR or max-DD.

Adopt: stationary bootstrap with avg block length L ≈ n^(1/3) ≈ 6 months for
n=240 (or Politis-White 2004 automatic selector). Resample B=10,000 paths.
Report 95% CI on alpha, Sharpe, CAGR, max-DD. **If CI on alpha straddles 0, we
have honest confirmation of no-alpha.**

Caveats:
- Bootstrap CIs for max-DD are notoriously biased (drawdown is a tail
  functional, bootstrap underestimates extreme quantiles). Don't oversell.
- Stationarity assumption marginally satisfied by A-share 2006-2025 (2007
  bubble, 2015 crash, 2020 reform). Report results with AND without the
  2007-2008 / 2015 subsamples.

### 2.4.2 Shrinkage trio (Ledoit-Wolf, Bayes-Stein, Black-Litterman)

- **Ledoit-Wolf** = HIGH adopt. One-liner. Replaces sample Σ in any risk model.
- **Bayes-Stein on µ** = MEDIUM-HIGH adopt. Replaces OLS-pooled µ. Most useful
  if iter-8 adds MV optimizer — current top-15-on-composite-score doesn't use µ
  directly, so marginal value depends on portfolio construction change.
- **Black-Litterman** = LOW for our problem. **BL was designed for multi-asset
  allocation where market-cap-weighted implied returns are a natural neutral
  prior and the investor has a small number of discretionary views. Neither
  holds here.** Our "views" ARE the 5 factor signals (already the prior). A
  market-cap A-share prior contains ~0 independent info about cross-sectional
  factor returns. **The textbook association BL ↔ factor strategies is a
  category error if your "views" are themselves systematic.** Use James-Stein
  or NPEB instead.

### 2.5 / 2.5.3 NPEB — defer to iter-9

Lai-Xing-Chen 2011 treats unknown µ,Σ as random draws from unknown
distribution G; estimates G nonparametrically from panel via empirical Bayes;
integrates portfolio rule over posterior. Better OOS Sharpe vs plug-in /
Bayes-Stein / BL on Fama-French portfolios.

But: requires nonparametric density estimation + Monte Carlo integration over
posterior + hyperparameter selection. >500 lines for ~1-2× Sharpe gain in the
paper.

**Verdict:** defer. iter-8 gets higher marginal return from multiple-testing +
bootstrap; revisit NPEB once we've established (via 1 & 2) whether there IS any
alpha to recover.

### 2.7.2 IR-on-frontier — LOW

Construction of efficient frontier in (tracking-error, active-return) space.
Only relevant if we adopt benchmark-relative mandate (e.g., enhanced CSI 300).
Our current top-15-long-only is more naturally Sharpe-evaluated.

### 3.1.2 / 3.1.3 Exotic beta + integrated allocation

Carhart et al. 2014 decompose returns into market + exotic betas (style premia)
+ residual active alpha. Useful as **post-hoc diagnostic** for iter-7: how
much of +0.97% is compensated factor premium (= NOT alpha) vs residual? If
mostly exotic beta, the "alpha" is by construction the equity premium delivered
through factor exposure.

But this is essentially what a **Fama-French regression** already gives us.
Integrated BL framework adds heavyweight machinery without changing the answer
for cross-sectional equity. **Verdict:** LOW-MEDIUM as diagnostic (do a
FF-style regression of our portfolio returns on market/SMB/HML/MOM — that's
~30 lines). LOW as predictor.

## Concrete iter-8 implementation order

1. **`stats/multiple_testing.py`** (~80 lines): BH/BY p-value adjustment, HLZ
   t-statistic reference, Deflated Sharpe Ratio. Apply to 5 factor t-stats AND
   to iter-1..7 spec-trials count.
2. **`stats/stationary_bootstrap.py`** (~100 lines or `arch.bootstrap.StationaryBootstrap`):
   95% CI for alpha, Sharpe, CAGR. Apply to iter-7 best result; **if CI
   straddles 0, halt and consult Junyan.**
3. **`risk/shrinkage.py`** (~30 lines): Ledoit-Wolf via sklearn;
   Jorion Bayes-Stein on µ. Replace sample Σ everywhere.
4. **`stats/fama_french_attribution.py`** (~50 lines): regress portfolio returns
   on market + size + value + mom factors (A-share). Quantify how much "alpha"
   is exotic beta. This is the iter-7 honest post-mortem.
5. Run iter-8 with (1)+(2)+(3)+(4). Defer NPEB, BL, IR-frontier.

## Honest caveats (per "宁愿犯错也不愿意找不出来错误在哪")

- **None of these methods will manufacture alpha that isn't there.** If iter-7
  alpha is +0.97% with R²=0.001, the most likely result of doing all of
  (1)+(2)+(3)+(4) is a 95% bootstrap CI on alpha that **straddles zero AND** a
  Deflated Sharpe that **fails to reject H0**. That is the honest answer the
  loop is converging toward. Value of adopting = CONFIRM that conclusion with
  auditable statistics, not overturn it.
- HLZ t>3 is US-data-calibrated; not A-share law.
- Bootstrap CIs for max-DD are unreliable — don't report as such.
- BL is the wrong tool for cross-sectional equity factors.
- NPEB benchmarks in LXC 2011 used FF portfolios as asset universe, not
  individual stocks with monthly rebal + top-15 selection. Translation cost
  non-trivial.
- **Survivorship and look-ahead are still dominant risks. Statistical
  sophistication doesn't fix data-side bugs.** Re-audit PIT compliance before
  crediting any iter-8 improvement to method changes.

## Sources

- Harvey, Liu & Zhu (2016) RFS — "...and the Cross-Section of Expected Returns":
  https://academic.oup.com/rfs/article/29/1/5/1843824
- Harvey & Liu (2021) JFE — "Lucky Factors":
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2528780
- Black & Litterman (1992) FAJ (overview):
  https://en.wikipedia.org/wiki/Black%E2%80%93Litterman_model
- Lai, Xing, Chen (2011) AoAS — NPEB:
  https://projecteuclid.org/euclid.aoas/1310562206
- Politis & Romano (1994) JASA — The Stationary Bootstrap:
  https://www.tandfonline.com/doi/abs/10.1080/01621459.1994.10476870
- Jorion (1986) JFQA — Bayes-Stein:
  https://ideas.repec.org/a/cup/jfinqa/v21y1986i03p279-292_01.html
- Ledoit & Wolf (2004) JPM — Honey, I Shrunk the Sample Covariance Matrix:
  http://www.ledoit.net/honey.pdf
- Bailey & López de Prado (2014) JPM — The Deflated Sharpe Ratio:
  https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
- White (2000) Econometrica — Reality Check for Data Snooping:
  https://users.ssc.wisc.edu/~bhansen/718/White2000.pdf
- Romano & Wolf (2005) Econometrica — Stepwise Multiple Testing
- Carhart et al. (2014) SSRN — Exotic Beta Revisited:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2499728
