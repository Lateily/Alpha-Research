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

## Night Shift — Completed (2026-04-29 → 2026-04-30)

Two shifts shipped Tier 1 protocol-drift items + the entire v15 sprint:

| Task | Status | Commit |
|------|--------|--------|
| PROJECT_INSTRUCTIONS.md B3 — VP weights 25/25/20/15/15 + piecewise EGS | ✅ Shipped | 3c923c3 |
| verify_outputs.py — v14 module coverage (signals/confluence/daily_decision/leading_indicators) | ✅ Shipped | 2930471 |
| catalyst_prox canonicalization across pipeline + Supabase boundary | ✅ Shipped | 1892b3a |

---

## v15 — Sprint Complete (Shipped 2026-04-30)

All five v15 items are live in production. Tagged `v15.0`.

### v15.1 — Signal Attribution ✅ Shipped (commit b16b9d0)
trades.json carries full `signal_attribution` schema (name/weight/direction
per contributing signal). `daily_decision.py` emits a per-pipeline-run
`trade_attribution_capsules.json` so new trades can be entered with the
exact attribution snapshot pinned to today's confluence state. SIGNAL_DIRECTION
covers 25 signal types from swing_signals.py + signal_confluence.py.

### v15.2 — wrongIf Auto-Monitor ✅ Shipped (commit 6f73792, follow-up 7f09a01)
`daily_decision.py:check_wrongif()` auto-fires alerts against live yfinance
fundamentals + leading_indicators basket data:
- 300308.SZ NVDA+MSFT+GOOGL collective drawdown (vs 25% threshold)
- 9999.HK earnings_growth < -30% (post-7f09a01 below_neg pattern)
- 002594.SZ revenue_growth/earnings_growth thresholds
- 6160.HK / 700.HK binary-event clauses → MANUAL flag
F2 stale-wrongIf-in-snapshot bug fixed as side benefit (vp_engine now
refreshes wrongIf strings from watchlist on each run).

### v15.3 — Signal Quality Engine ✅ Shipped (commit 6c8873c on top of pre-existing)
`scripts/signal_quality.py` is in the fetch-data.yml pipeline + read by
Dashboard.jsx. Computes by_signal/by_conviction/vp_buckets/by_ticker
aggregations. Current portfolio (5 attributed positions): 100% win rate,
+18.0% avg P&L, GOLDEN_CROSS leads at 100% win rate across 3 trades.

### v15.4 — Position Sizing Calculator ✅ Shipped (was already live)
`scripts/position_sizing.py` (206 lines, ATR-stop + VP-mult + conf-mult)
runs in fetch-data.yml. Dashboard.jsx renders `recommended_pct`,
`conviction_tier`, `risk_cny`, etc. (lines 3430-3459).

### v15.5 — Mock Portfolio Seed ✅ Shipped (was already live)
trades.json has 5 attributed entries (one per watchlist ticker, dated
2026-03-10 through 2026-04-01). positions.json has 5 corresponding live
positions with full P&L tracking and signal attribution.

### Post-v15 follow-ups (queued, partially shipped)

| # | Item | Status | Notes |
|---|------|--------|-------|
| KR4 | `<indicator> < -X%` wrongif pattern | ✅ Shipped (7f09a01) | Restores 9999.HK auto-monitoring, surfaces 2 extra 002594.SZ triggers |
| KR5 | Drawdown-aware leader insight phrasing | 📦 In stash | Reviewer timed out; awaiting user review |
| KR6 | Tighten price-drop regex (gross_margin false-fire) | 📦 In stash | Reviewer timed out; awaiting user review |
| KR7 | Surface CLEAR alerts in wrongif_alerts (UX gap) | ⏳ Queued | Mentioned in 2 reviews; promote to next shift |
| KR8 | Dedupe redundant `(ticker, indicator)` alerts | ⏳ Queued | KR4 review P3 |

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
| Signal attribution | Per-signal win rate live (v15.3) | n ≥ 10 attributed closed trades |
| Research coverage | 5 focus stocks | 5 focus + expand when pipeline stable |
| wrongIf monitoring | Automated (v15.2) for 4 of 5 tickers | All 5 + history-aware persistence |
