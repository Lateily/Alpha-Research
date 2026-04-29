# Platform Roadmap

> Living document — update after each sprint.
> Last updated: 2026-04-29

## Vision

An institutional-grade personal research platform that systematises buy-side equity analysis, reduces manual effort by 80%, and maintains auditable prediction track records with real-outcome verification.

---

## Current State — v14.3 (Shipped as of 2026-04-25)

All features below are live in production:

| Feature | Status |
|---------|--------|
| VP Score — 5 dimensions (25/25/20/15/15) [unvalidated intuition] | ✅ Live |
| watchlist.json as single source of truth | ✅ Live |
| fetch_data.py loads tickers/seeds from watchlist.json | ✅ Fixed 2026-04-25 |
| Deep Research (Claude Sonnet, UBS pitch framework) | ✅ Live |
| Multi-Agent Debate (Gemini + GPT-4o + Claude) | ✅ Live |
| Reverse DCF + Expectation Gap (piecewise mapping) | ✅ Live |
| Macro Stress Test (4 scenarios) | ✅ Live |
| Backtest Engine (monthly rebalance, bootstrap CI) | ✅ Live |
| Paper Trading (trades.json) | ✅ Live |
| Swing Trading Signals (swing_signals.py, SwingSignalBadge) | ✅ Live |
| Signal Confluence (signal_confluence.py) | ✅ Live |
| Daily Decision Engine + wrongIf alerts (daily_decision.py) | ✅ Live |
| Leading Indicators — NVDA/hyperscaler/TSMC composite | ✅ Live |
| Supabase Snapshots + Telegram Alerts | ✅ Live |
| Full market screener (10,461 stocks via Eastmoney) | ✅ Live |
| Prediction Log + Verification (hit rate: 67%) | ✅ v1.1 |
| Custom Skills (ar-code-reviewer, ar-security-auditor, ar-release-engineer, neat-freak, night-shift) | ✅ Live |

---

## Night Shift — Active (2026-04-29)

Currently running. Tier 1 objectives:

| Task | Status |
|------|--------|
| PROJECT_INSTRUCTIONS.md B3 — update VP weights (30→25, 10→15) and EGS formula (tanh→piecewise) | 🔄 In progress |
| verify_outputs.py — extend to v14 modules (signals, confluence, daily_decision, leading_indicators) | 🔄 In progress |
| catalyst_prox naming — canonicalize across pipeline | 🔄 In progress |

---

## v15 — Next Sprint (after Night Shift completes)

### v15.1 — Signal Attribution [HIGH PRIORITY]
**Goal**: Record which signals triggered each paper trade entry in trades.json
**Why**: Without attribution, signal_quality.py cannot compute per-signal win rates
**Changes**: `scripts/daily_decision.py` → write `triggered_signals` array to each trade
**Output**: `public/data/trades.json` updated schema
**Effort**: ~1 session
**Upstream dependency**: None

### v15.2 — wrongIf Auto-Monitor [HIGH PRIORITY]
**Goal**: `daily_decision.py` checks wrongIf conditions against live data each run
**Why**: Currently wrongIf status is updated manually; should auto-trigger when condition breached
**Specific**: 300308.SZ monitors NVDA+MSFT+GOOGL price drop; 9999.HK monitors earnings_growth
**Output**: Telegram alert when wrongIf fires
**Effort**: ~1 session

### v15.3 — Signal Quality Engine [HIGH PRIORITY]
**Goal**: `scripts/signal_quality.py` — per-signal win rate and P&L attribution
**Why**: Without this, signal weights remain [unvalidated intuition] forever
**Input**: trades.json (requires v15.1 attribution first)
**Output**: `public/data/signal_quality.json` → feeds back into confluence weights
**Effort**: ~1 session
**Upstream dependency**: v15.1 must ship first

### v15.4 — Position Sizing Calculator
**Goal**: ATR-based, VP-weighted position size recommendations in Trading Desk
**Changes**: `scripts/position_sizing.py` + fetch-data.yml step + Dashboard UI
**Output**: `public/data/position_sizing.json`
**Effort**: ~1 session

### v15.5 — Mock Portfolio Seed
**Goal**: Seed trades.json with 5-stock mock portfolio + signal attribution
**Why**: paper_trading.py and backtest need historical entries to compute meaningful P&L
**Effort**: ~0.5 session

---

## v16 — Phase 3 (Deferred — needs real trade history first)

### v16.1 — Claude Earnings Tone Analysis
6-dimension transcript scoring: revenue guidance tone, margin commentary, capex signals, competition acknowledgement, management confidence, forward guidance specificity. ~$0.10/transcript. Implement after data pipeline stabilises.

### v16.2 — Brinson-Fachler Attribution
Sector allocation + stock selection decomposition vs CSI 300 / HSI benchmarks. Requires 3+ months real paper trading P&L.

### v16.3 — VP Weight Calibration
Replace [unvalidated intuition] weights (25/25/20/15/15) with backtest-optimised values via grid search. Requires signal_quality.py output (v15.3) first.

### v16.4 — Tushare Pro Integration
User has paid access. Add TUSHARE_TOKEN to GitHub Secrets → unlocks real-time A-share quotes, capital flows, northbound data, margin data. Currently using AKShare (geo-blocked from GitHub Actions).

### v16.5 — Consensus Estimate Integration
A-shares: ak.stock_profit_forecast_em() broker EPS forecasts
HK: yfinance .earnings_estimate
Goal: automate consensus beat/miss calculation.

---

## Thesis Refresh Queue

| Ticker | Issue | Priority |
|--------|-------|----------|
| BYD 002594.SZ | wrongIf TRIGGERED (revenue_growth -13.5%) — needs full thesis rebuild | High |
| Innolight 300308.SZ | Directionally valid but 2026 1.6T mass production timing needs update | Medium |
| BeiGene 6160.HK | VP=65 computed with old weights — re-verify against 25/25/20/15/15 | Medium |

---

## Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Prediction hit rate | 67% (2/3 decidable) | > 65% at n ≥ 10 |
| VP Score calibration | [unvalidated intuition] | Backtest-validated (v16.3) |
| Signal attribution | Not yet tracked | Per-signal win rate (v15.3) |
| Research coverage | 5 focus stocks | 5 focus + expand when pipeline stable |
| wrongIf monitoring | Manual | Automated (v15.2) |
