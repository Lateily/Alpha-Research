# Predictive Research Upgrade Plan

## Problem Statement

The current platform is strong at collecting facts and enforcing execution
gates. It is weaker at buy-side-style forward research: identifying why a
sector or company may rerate before the move becomes obvious.

The correct answer is not to pretend that next-day capital destination is
predictable. The upgrade is to change the prediction object:

- from "where will money go tomorrow?"
- to "what conditions make a sector rotation more likely, more persistent, or
  more fragile?"
- and "which companies sit at value-chain bottlenecks where future earnings
  revisions can be reasoned from first principles?"

Causal logic is valid because prediction quality improves when the target is a
mechanism with observable precursors rather than a one-day flow destination.
Specific feature weights and thresholds below are unvalidated intuitions until
backtested or forward paper-scored.

## Research Line 1: A-Share Sector Rotation Lab

Goal: build a sector-rotation atlas from recent A-share behavior. The first
working windows should be three months and six months [user-requested window,
not a calibrated optimum].

### Data Panel

Use point-in-time daily data where possible:

- Sector/concept returns.
- Sector/concept turnover and volume acceleration.
- Limit-up, limit-down, open-board, and failed-board counts.
- Main-force flow by sector/concept if available.
- Northbound flow and margin balance where relevant.
- Dragon-stock returns and breadth within each sector.
- Index state: CSI 300, ChiNext, STAR 50, broad A-share breadth.
- Global risk proxies: US rates, Nasdaq/SOX, USD/CNY, commodities, major
  geopolitical shock flags.
- Calendar variables: earnings windows, policy meetings, industry events.

Evidence tiers:

- E1: exchange/issuer/official data.
- E2: broker/media/channel inference.
- E3: price, volume, fund-flow, technical data.
- E4: assumptions and analyst judgment.

### Labels

Pre-register labels before testing:

- Next-day sector excess return [horizon choice unvalidated intuition].
- Three-day sector excess return [horizon choice unvalidated intuition].
- Five-day sector excess return [horizon choice unvalidated intuition].
- Ten-day sector excess return [horizon choice unvalidated intuition].
- Sector drawdown after a crowded advance.
- Leader continuation vs leader failure.
- Rotation persistence half-life.

These labels are not alpha by themselves. They are measurement targets.

### Hypotheses To Test

1. Sector rotations persist only when leader breadth confirms.
   - Mechanism: if only one dragon stock moves, the sector has not repriced.
   - Causal logic: valid but unproven in this dataset.

2. Limit-up clusters predict attention, not necessarily return.
   - Mechanism: board clusters reveal crowd attention and liquidity demand.
   - Risk: they may also signal exhaustion.

3. Negative distribution signatures are more persistent than positive
   accumulation signatures in churn markets.
   - Mechanism: trapped holders and failed breakout supply create inertia.
   - This matches the July 2026 qualitative observation, but needs more sample.

4. Global-tech confirmation matters for semiconductor/AI chain persistence.
   - Mechanism: A-share semiconductor risk appetite is partly gated by global
     AI hardware sentiment and SOX/Nasdaq liquidity.

5. A sector with improving value-chain fundamentals and still-cold flow is a
   better research candidate than a sector already at heat extremes.
   - Mechanism: the predictive edge should come before obvious flow.

### Method

- Build sector-day observations.
- Rank each feature cross-sectionally each day to avoid level drift.
- Use event studies around sector breakouts, limit-up clusters, and flow
  reversals.
- Run transition matrices: today sector state -> future sector state.
- Estimate decay/continuation with survival-style analysis.
- Separate market regimes: risk-on, risk-off, style rotation, churn.
- Use negative controls: random sector labels and lag-shuffled features.
- Use walk-forward splits. Do not tune on the same window used for evaluation.
- Correct for multiple testing before calling anything useful.

### Outputs

- Weekly Sector Rotation Map:
  - hottest sectors
  - improving but not crowded sectors
  - crowded/unwind-risk sectors
  - failed-breakout sectors
  - research candidates for value-chain work

- Rotation Hypothesis Cards:
  - sector
  - state
  - evidence
  - mechanism
  - expected horizon
  - wrong-if
  - paper signal ID

## Research Line 2: Industry Value-Chain Variant Research

Goal: make the platform act less like a flow dashboard and more like a buy-side
research process.

### Core Idea

A strong long-term candidate should sit at an intersection:

- value-chain bottleneck
- visible catalyst
- earnings translation
- customer/order evidence
- consensus gap
- manageable balance-sheet and concentration risk
- market attention not already fully saturated

This is not a formula yet. It is a research funnel.

### Industry Map Schema

For each industry:

- Industry name.
- Demand driver.
- Supply-chain stages.
- Bottleneck nodes.
- Listed companies per node.
- Key customers and suppliers.
- Pricing power indicators.
- Technology transition.
- Policy exposure.
- Catalyst calendar.
- Evidence tier per claim.
- Open questions.

### Bottleneck Node Score

Possible components, all unvalidated intuitions:

- Scarcity of capability.
- Customer switching cost.
- Margin expansion potential.
- Order visibility.
- Domestic substitution importance.
- Capex/technology cycle proximity.
- Consensus misunderstanding.
- Financial statement translation.

Do not calculate a final score until the components have data definitions.
The first version should be a qualitative map with evidence tags.

### Semiconductor Example Scope

The first industry map should cover semiconductor and AI hardware chain because
the current market question is live and Junyan already has intuition here.

Suggested nodes:

- Design/IP/EDA.
- Wafer fabrication.
- Semiconductor equipment.
- Materials and chemicals.
- Advanced packaging.
- Testing.
- Power/analog/memory where relevant.
- Optical modules and AI interconnect.
- PCB/copper-clad laminate.
- Data-center power/cooling as adjacent infrastructure.

For each node, ask:

- Is this a true bottleneck or just a hot theme?
- Which listed companies have real exposure?
- Is exposure material to revenue and margin?
- Is there E1 or E2 evidence of orders, capex, pricing, or customer wins?
- What would make the thesis wrong?

### Variant Report Standard

Each candidate must pass the eight-step thesis protocol:

1. catalyst
2. mechanism
3. evidence plus contrarian view
4. quantification
5. proves-right-if
6. proves-wrong-if
7. variant view
8. phase and timing

The candidate cannot enter the paper book without:

- a pre-registered catalyst
- a mechanism chain
- a wrong-if
- a future evaluation horizon
- a paper_signal_id

## New Full-Market Screen Workflow

The weekly screen should become two-stage:

### Stage A: Attention And Risk Screen

This uses flow, price, breadth, and heat. It answers:

- Where is the market looking?
- Where is the market crowded?
- Where is distribution risk high?
- Which sectors deserve research attention?

It does not answer:

- What should be bought?
- Where money must go next?

### Stage B: Variant Research Screen

This uses industry maps and thesis logic. It answers:

- Which sectors have value-chain catalysts not yet fully reflected?
- Which companies sit at bottleneck nodes?
- Which candidates deserve full variant reports?

### Stage C: Paper Registration

Only pre-registered candidates enter the one-month paper tracker.

## Four-Week Implementation Plan

Week one [unvalidated operating cadence]:

- Build the Notion/repo weekly report loop.
- Start paper tracker.
- Define sector-rotation dataset schema.
- Pick semiconductor as the first value-chain map.

Week two [unvalidated operating cadence]:

- Generate first three-month and six-month sector-rotation descriptive report.
- Produce semiconductor value-chain map v0.
- Register first batch of rotation and value-chain paper hypotheses.

Week three [unvalidated operating cadence]:

- Score first T+5 or T+10 outcomes where available [horizon choices
  unvalidated intuitions].
- Add failure-mode taxonomy.
- Expand value-chain map to one more industry.

Week four [unvalidated operating cadence]:

- Publish first monthly learning memo.
- Decide which signals deserve production migration, paper-only status, or kill.

## Validation Standard

Causal logic is valid if it specifies catalyst -> mechanism -> measurable
financial or market impact -> falsification.

Causal logic is questionable if it only says "funds are flowing" or "theme is
hot".

Causal logic is unestablished if the reason can only be written after the price
move has happened.

Specific numbers are unvalidated until they are forward-scored in the paper
tracker or tested in a point-in-time historical panel.

不是买卖指令；研究信号，human executes.
