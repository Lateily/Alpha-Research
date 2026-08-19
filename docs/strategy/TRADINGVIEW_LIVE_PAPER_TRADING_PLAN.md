# TradingView Live Execution Gate + Paper-Trade Tracking Plan v0.1

> Purpose: convert the research factory into a long-running live observation
> loop that measures signal quality, win rate, and paper P&L before any real
> capital action. This is a research and paper-trading system, not an automated
> trading bot. Junyan executes all real trades.

## 0. Current Status

The prompt layer is now specified in:

- `docs/research/WEEKLY_RESEARCH_FACTORY_PROMPT.md`
- this file

What is not yet built:

- no persistent TradingView daemon
- no paper signal database for execution-gate signals
- no live dashboard panel for these signals
- no automated win-rate / expectancy report for the execution layer

## 1. Philosophy

The system must learn whether its execution signals help or hurt the research
factory. It should answer:

1. Does `RECLAIM_REVIEW` actually lead to positive forward returns?
2. Does `WARNING` correctly identify failed breakouts / distribution?
3. Does `DE_RISK_REVIEW` reduce drawdown?
4. Which signals work only in `RISK_ON` and fail in `WEAK_REPAIR`?
5. Which tickers are too reflexive for fundamental research to drive timing?

Until enough paper outcomes exist, all execution thresholds are unvalidated
heuristics.

## 2. Execution Gate Prompt

Use this for intraday or post-close monitoring.

```text
You are Junyan's A-share execution gate and paper-trading analyst.

Hard rules:
- You are not a licensed investment adviser.
- You cannot issue buy/sell/cut/add instructions.
- You output evidence, risk posture, execution gates, and paper signals only.
- Human executes all real trades.

Inputs:
- ticker list / holdings
- position context if provided: cost, size, thesis posture
- current time: pre-open, intraday, close, post-close

Step 1: Market gate
- Pull Shanghai Composite, Shenzhen Component, ChiNext.
- Pull main-force net flow for each index if available.
- Classify:
  RISK_ON / WEAK_REPAIR / RISK_OFF / STYLE_ROTATION.
- One sentence: trend restoration, weak repair, continued distribution, or
  style rotation.

Step 2: Sector gate
- Identify the relevant sector chain.
- For AI/optical/compute, always check at least:
  中际旭创, 新易盛, 天孚通信, 工业富联, 沪电/胜宏.
- If only one stock is strong while anchors are weak, classify as
  single-stock rebound, not sector repair.

Step 3: Fund-flow gate
For each ticker:
- current price, pct change, amount, turnover
- main net flow
- super-large, large, medium, small order flows where available
- classify:
  main inflow / rising distribution / dip absorption /
  big-money sell-small-money buy / low-volume repair

Step 4: Technical gate
For each ticker:
- today high/low
- yesterday high/low
- MA20/60/120
- ATR14
- 20-day high/low
- reclaim level
- support/acceptance zone
- break level

Do not invent technical levels. Use TradingView/OHLC data.

Step 5: Execution posture
Allowed postures:
- NO_CHASE: price extended, confirmation absent
- HOLD_OBSERVE: support holding but confirmation absent
- WARNING: price strong but fund flow not confirming
- RECLAIM_REVIEW: price reclaims level and main flow confirms
- DE_RISK_REVIEW: support breaks or single-beta exposure is excessive
- EXIT_REVIEW: break level + main outflow + thesis/wrong-if deterioration

Step 6: Portfolio concentration gate
- Identify common beta across holdings.
- If holdings are concentrated in one theme, assess portfolio-level risk before
  single-name excitement.

Step 7: Paper signal, not trade instruction
If a posture changes, create a paper signal:
- signal_id
- ticker
- timestamp
- market_state
- sector_state
- signal_type
- trigger_price
- support
- reclaim
- break_level
- ATR14
- invalidation
- horizon: intraday / 1d / 3d / 5d / 10d
- no_trade_flag: true

Step 8: Self-audit
- Did I treat a rebound as a reversal?
- Did I look at price without fund flow?
- Did I ignore sector confirmation?
- Did I treat HIGH_REFLEXIVITY as low risk?
- Did I issue a real buy/sell instruction?
```

## 3. Paper Signal Rules

These are paper-trading labels only.

### 3.1 Paper Long Candidate

Create `PAPER_RECLAIM_LONG` only when all are true:

1. market state is `RISK_ON` or improving `WEAK_REPAIR`
2. sector anchor confirms or at least stops bleeding
3. ticker closes or trades above reclaim level
4. main flow turns positive or outflow materially narrows
5. support is nearby enough that ATR-defined risk is measurable

### 3.2 Paper Risk Reduction Candidate

Create `PAPER_DERISK` when any are true:

1. price breaks support and stays below
2. price strength is paired with persistent main outflow
3. sector anchors continue distribution
4. single-theme portfolio exposure is too concentrated
5. thesis wrong-if or catalyst deterioration appears

### 3.3 Paper Exit Review Candidate

Create `PAPER_EXIT_REVIEW` only when technical break and evidence deterioration
coincide. Technical weakness alone is not enough to falsify a deep thesis.

## 4. Measurement

Every paper signal must be scored at:

- same day close
- T+1
- T+3
- T+5
- T+10

Track:

- hit rate
- average return
- average win / average loss
- expectancy
- max adverse excursion (MAE)
- max favorable excursion (MFE)
- false-breakout rate
- drawdown avoided after `PAPER_DERISK`
- performance by market state
- performance by signal type
- performance by sector

No live-capital claim until at least:

- 30 independent paper signals
- multiple market states
- no single ticker/theme dominates the sample

## 5. 24-Hour Monitoring Design

A-share trading is not 24 hours. The correct loop is event-driven:

### 5.1 A-share session

- 09:15-09:25: pre-open/auction snapshot
- 09:30-11:30: poll every 3-5 minutes
- 13:00-15:00: poll every 3-5 minutes
- 15:00-15:30: close report and paper-signal settlement

### 5.2 Off-hours

- US AI chain / Nasdaq / SOX / NVDA / hyperscaler capex names
- commodities and FX if relevant
- company announcements
- broker/media events marked E2 unless issuer-confirmed

### 5.3 Token discipline

Do not call an LLM every poll. Use scripts for raw state and call the model only
when:

- posture changes
- support/reclaim/break is crossed
- fund-flow regime flips
- sector anchor flips
- end-of-day report is due

## 6. Dashboard Panel v0

The frontend panel should eventually show:

1. Market state card
2. Sector state card
3. Holdings execution table
4. Paper signal log
5. Signal performance by type
6. Current single-beta concentration
7. Alerts requiring Junyan review

No order buttons. No automated trading.

## 7. Implementation Roadmap

### P0 — Prompt Landing

- Canonical weekly research prompt
- Canonical execution gate prompt
- Paper-signal rule definitions

Status: specified in docs.

### P1 — Data Capture

Build a read-only collector:

- TradingView/OHLC technicals
- Eastmoney fund flow
- index state
- sector anchors
- current universe factors

Output JSON:

- `public/data/execution_gate_snapshot.json`
- `public/data/paper_signal_log.json`

### P2 — Paper Signal Evaluator

Evaluate every signal at T+0/T+1/T+3/T+5/T+10.

Output:

- `public/data/paper_signal_performance.json`

### P3 — Dashboard

Add an Execution Gate panel to `Dashboard.jsx`.

### P4 — Daily Report

Generate:

- pre-open plan
- midday update
- close report
- weekly execution review

### P5 — Review Gate

Only after sufficient paper data:

- review hit rate and expectancy
- decide whether any rule deserves real-capital consideration
- revise or kill weak rules

## 8. Current Known Constraints

- TradingView CDP can be unavailable and may need restart.
- A-share TradingView feed is delayed and may be daily/intraday-limited.
- Main-force fund flow currently comes from Eastmoney-like sources, not
  TradingView.
- Live monitoring needs a background service; a chat session alone cannot
  guarantee 24-hour persistence.
- All trading conclusions remain unvalidated until paper outcomes accumulate.

