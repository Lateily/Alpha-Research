# Institutional Quant Research Brief (for Iter-8+)

_Synthesized 2026-05-26 by background research agent. ~50 min of public-source
search. **Honest top finding**: GS QIS / Two Sigma / Bridgewater publish
marketing-grade material; actionable institutional methodology lives in **AQR
papers, MSCI Barra USE4/CNE5 docs, Liu-Stambaugh-Yuan + Hou-Xue-Zhang academic
papers, and the Huatai sell-side replication corpus on GitHub**. Plan around
those._

## 1. Per-firm framework summary

| Firm | Public framework | Concrete methodology? | Best public substitute |
|------|------------------|----------------------|------------------------|
| **Goldman Sachs QIS** | "QIS Equity Factor Investing" (brochure) | **NO** — promotional only | **MSCI Barra USE4** = documented analog of GS-tier risk model |
| **AQR Capital** | Style Premia, QMJ, Value/Mom Everywhere, BAB, Craftsmanship Alpha | **YES** — heavy paper library on aqr.com/Insights/Research | Primary source |
| **Two Sigma** | Two Sigma Factor Lens (18 factors, 4 categories) | PARTIAL — principles published, math sealed | 2018 lens whitepaper + 2019 follow-up + Venn FAQ |
| **BlackRock/iShares** | A-share Systematic Fund exists | **NO** public A-share factor methodology PDF | MSCI A-share factor research |
| **JPM Kolanovic** | Big Data & AI Strategies primer (2017) | YES — leaked PDFs widely available | The 2017 ML primer |
| **Man Group / Man AHL** | Oxford-Man Institute papers (academic) | PARTIAL — co-authored academic only | Oxford-Man arXiv papers |
| **Bridgewater** | "All Weather Story", "Engineering Targeted Returns" (2011) | YES but **not factor-relevant** | Skip for factor work |
| **Huatai 华泰** | 25+ sell-side reports replicated on QuantsPlaybook GitHub | **YES** — most actionable A-share material we found | Primary source |
| **CITIC 中信** | "多因子量化选股系列" (intraday) | PARTIAL — via aggregator sites | BigQuant aggregations |
| **CICC 中金** | 量化多因子系列(7):价量因子手册 (2022) | PARTIAL | Sina Finance published series |
| **WorldQuant 101 Alphas** | Kakushadze 2015 (arXiv:1601.00991) | YES — full formulas | Primary source |
| **Liu-Stambaugh-Yuan CH3** | NBER w24458 / JFE 2019 | YES — A-share specific | Primary source |
| **Hou-Xue-Zhang q-factor** | global-q.org factor data + papers | YES | Primary source |

## 2. Five A-share-specific findings that override generic factor wisdom

THESE ARE THE TOP CALIBRATION PRIORITIES FOR ITER-8:

1. **MSCI 2024 A-share research**: in China, **high-dividend-yield and low-vol
   consistently outperform**; **momentum does NOT lead like global markets**.
   [→ this matches our OLS finding: momentum coef was negative, we zeroed it.]

2. **Liu-Stambaugh-Yuan CH3 (2019)**: **exclude the bottom 30% of market-cap**
   because they trade as **shell stocks** for reverse-merger arbitrage,
   contaminating size-factor inference. Use **E/P as value** factor (not B/M —
   B/M is dominated by E/P in A-share).

3. **Li & Rao (2022) revision**: post-2017 IPO reform made the LSY bottom-30%
   rule **overestimate alpha**. Replace blunt exclusion with **Expected Shell
   Probability (ESP)** threshold at 1%. Re-including legitimate small-caps
   lifts SMB from 0.46%/mo → 0.74%/mo.

4. **LSY CH4 fourth factor**: turnover-based **PMO (pessimistic-minus-optimistic)** —
   abnormal-turnover sentiment factor specific to A-share retail dominance.
   `past-month-turnover ÷ past-year-turnover`.

5. **q-factor finding (HMXZ 2019)**: investment factor carries a **NEGATIVE
   premium in China** (opposite of US). ROE/profitability still works but
   signed differently from FF5 expectation.

## 3. Five concrete factor-construction upgrades for iter-8

### Technique 1 — Three-stage cross-sectional standardization (Barra USE4)

Per MSCI Barra USE4 Methodology Notes (2011):
1. Compute descriptors per factor (Value: B/P, E/P, CF/P, S/P)
2. **Winsorize each descriptor at ±3σ cross-sectionally per date**
3. Standardize to **cap-weighted mean = 0** and **equal-weighted std = 1**
   (asymmetric — market-weight portfolio has zero exposure, vol preserved)
4. Combine descriptors into style factor with equal/fitness weights
5. **Cross-section regress returns on (country + 60 industries + 12 styles)
   via WLS, weighted by √(market cap)**

vs current "raw factor → z-score": fixes outlier dominance + removes
industry/cap correlation contamination.

### Technique 2 — Industry-neutralize via residual regression (not subtraction)

For each style factor f_i at time t:
- `f_i = α + Σ β_j · industry_dummy_j + ε`
- Use **ε (residual)** as the neutralized factor.

For **long-only** (our case), Harvey "Is Sector Neutrality a Mistake?" finds
it's a wash → test both versions, pick by OOS Sharpe. Don't assume.

### Technique 3 — Signal IC decomposition at multiple horizons

Run Alphalens-style rolling IC at **h = {21, 63, 126, 252}d** for each factor
before committing to monthly:
- Momentum half-life ≈ 3-6 months → ≤monthly rebalance
- Value half-life ≈ 18-24 months → quarterly is enough
- Quality half-life ≈ 12-18 months → semi-annual enough

vs current monthly-uniform-rebal: over-trading value/quality, possibly
under-trading momentum.

### Technique 4 — Signal blending: integrated vs portfolio-mix by TE budget

Ghayur-Heaney-Platt (FAJ 2018) + AQR Craftsmanship Alpha (Israel-Jiang-Ross
2017):
- **Low TE (<4%)** → **portfolio blending** (separate sleeves, mix at portfolio
  level). Higher IR.
- **High TE (>6%)** → **signal blending / integrated** (sum z-scores, sort
  once). Keeps balanced-positive names.

vs current "single composite": choose deliberately by TE budget.

### Technique 5 — Factor crowding monitor (Finominal / MSCI integrated)

Daily 5-metric crowding score per factor:
1. **Valuation spread**: P/B of long leg ÷ P/B of short leg
2. **Pair-wise correlation** with peer factors
3. **Realized volatility** of factor return
4. **Dispersion** across stocks
5. **12mo momentum** of factor itself

Equal-weight z-scored; **reduce exposure when score > +1σ**. arXiv 2512.11913:
mechanical factors (momentum, reversal) crowd faster than judgment (value,
quality); crowded reversal has 1.7-1.8× higher crash probability.

## 4. WorldQuant 101 Alphas (Kakushadze 2015) — signal-zoo expansion

Properties:
- Avg pair-wise correlation = **15.9%** (low — diversified set, not redundant)
- Avg holding period = 0.6-6.4 days (short-horizon, price-volume; can layer
  ON TOP of monthly fundamental factors)
- Operators: `rank`, `ts_rank`, `decay_linear`, `correlation`, `delta`,
  `ts_argmin/argmax`, `scale`, `signedpower`
- Strongly correlated with vol → vol-target before blending
- NOT dependent on turnover → capacity > expected

Iter-8 use: pick 5-10 alphas with cleanest operator stacks, compute on Tushare
daily price-volume, rank-correlate against fundamental composite. If
corr < 0.3, **orthogonal alpha — layer in**.

## 5. Honest gaps (what was NOT findable publicly)

1. **GS QIS factor methodology** — public materials are marketing brochures.
   **Substitute**: MSCI Barra USE4 + CNE5.
2. **BlackRock iShares A-share factor primer** — does not exist publicly.
   **Substitute**: MSCI A-share research + Liu-Stambaugh-Yuan.
3. **Two Sigma's actual factor math** — only 4 principles + 4-category
   structure published, not equations.
4. **Citic/CICC primary PDFs** — paywalled behind brokerage CRM. Substitute:
   `hugo2046/QuantsPlaybook` GitHub (25+ replicated reports).
5. **Barra USE4 / CNE5 PDFs in full** — methodology summary above is
   reconstructed from secondary sources; download originals manually:
   - https://www.msci.com/documents/10199/242721/Barra_US_Equity_Model_USE4.pdf
   - https://www.msci.com/documents/10199/0b7d7b9d-34d3-4d20-9f37-b1b41d976f6f

## 6. Recommended iter-8 priority order (5 concrete upgrades)

If burn-limited to one round:

| # | Change | Source | Expected impact |
|---|--------|--------|-----------------|
| **1** | **Apply LSY/Li-Rao A-share universe filter** — exclude high-ESP shells (or proxy: bottom 5% mcap AND turnover > 2× median) | LSY 2019, Li-Rao 2022 | HIGH — fixes A-share-specific contamination |
| **2** | **Replace raw z-score with Barra-style: winsorize ±3σ + cap-weighted std + industry residualize** | USE4 methodology | HIGH — cleans factor exposure |
| **3** | **Replace B/M with E/P as primary value descriptor** (or blend) | LSY CH3 | MEDIUM-HIGH |
| **4** | **IC@{21,63,126,252}d for each factor BEFORE committing to monthly** — pick rebal period per factor | Decay literature | MEDIUM |
| **5** | **Crowding monitor** (vol spread + factor vol + 12mo momentum) — de-risk when > +1σ | MSCI/Finominal | MEDIUM — protects vs factor decay during live |

## Key citations

**AQR canonical**:
- Asness/Frazzini/Pedersen "Quality Minus Junk" — http://www.econ.yale.edu/~shiller/behfin/2013_04-10/asness-frazzini-pedersen.pdf
- Asness/Moskowitz/Pedersen "Value and Momentum Everywhere" — https://w4.stern.nyu.edu/facdir/lpederse/papers/ValMomEverywhere.pdf
- Frazzini/Pedersen "Betting Against Beta" — https://pages.stern.nyu.edu/~lpederse/papers/BettingAgainstBeta.pdf
- Israel/Jiang/Ross "Craftsmanship Alpha" — https://www.aqr.com/-/media/AQR/Documents/Insights/Working-Papers/AQR--Craftsmanship-Alpha.pdf
- AQR datasets — https://www.aqr.com/Insights/Datasets

**China-specific**:
- Liu/Stambaugh/Yuan "Size and Value in China" — https://www.nber.org/papers/w24458
- Li & Rao 2022 revised CH-3 — https://www.sciencedirect.com/science/article/abs/pii/S0264999322002425
- MSCI China A-share factor research — https://www.msci.com/research-and-insights/paper/are-you-really-capturing-the-right-factors-unlocking-deeper-insights-in-china-a-share-factor-investing
- QuantPedia: Evaluating Factor Models in China — https://quantpedia.com/evaluating-factor-models-in-china/

**Risk model**:
- MSCI Barra USE4 — https://www.top1000funds.com/wp-content/uploads/2011/09/USE4_Methodology_Notes_August_2011.pdf
- MSCI Barra CNE5 — https://www.msci.com/documents/10199/0b7d7b9d-34d3-4d20-9f37-b1b41d976f6f

**Q-factor**:
- HMXZ 2019 "Which Factors?" — https://theinvestmentcapm.com/uploads/1/2/2/6/122679606/houmoxuezhang2019rf.pdf
- HXZ 2020 "Replicating Anomalies" — https://global-q.org/uploads/1/2/2/6/122679606/houxuezhang2020rfs.pdf
- global-q.org factor data — http://global-q.org/factors.html

**WorldQuant 101 alphas**: https://arxiv.org/abs/1601.00991

**Two Sigma**:
- Factor Lens 2018 — https://www.twosigma.com/wp-content/uploads/Introducing-the-Two-Sigma-Factor-Lens.10.18.pdf
- Forecasting Factor Returns — https://www.twosigma.com/wp-content/uploads/Forecasting-Factor-Returns.FINAL_-2.pdf
- Strategy Decay — https://www.tandfonline.com/doi/full/10.1080/14697688.2022.2098810

**Crowding**:
- arXiv 2512.11913 "Not All Factors Crowd Equally" — https://arxiv.org/html/2512.11913v1
- MSCI Integrated Factor Crowding — http://info.msci.com/MSCI-Integrated-Factor-Crowding-Model
- Finominal — https://insights.finominal.com/research-factor-crowding-model/

**Signal blending**:
- Ghayur/Heaney/Platt 2018 FAJ — https://www.tandfonline.com/doi/full/10.2469/faj.v74.n3.5
- Asness et al. arXiv 1810.08384 "Portfolio Construction Matters" — https://arxiv.org/pdf/1810.08384
- Harvey "Is Sector Neutrality a Mistake?" — https://people.duke.edu/~charvey/Research/Published_Papers/P165_Is_sector_neutrality.pdf

**Chinese sell-side replication**:
- hugo2046/QuantsPlaybook — https://github.com/hugo2046/QuantsPlaybook
- CICC 量化多因子系列 — https://finance.sina.cn/2022-08-10/detail-imizirav7498837.d.html

**Tools**:
- Alphalens — https://github.com/quantopian/alphalens
