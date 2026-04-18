# Platform Roadmap

> Living document — update after each sprint

## Vision

An institutional-grade personal research platform that systematises buy-side equity analysis, reduces manual effort by 80%, and maintains auditable prediction track records with real-outcome verification.

---

## v13.x — Current (Stable)

| Feature | Status |
|---------|--------|
| VP Score (3-engine) | ✅ Live |
| Deep Research (Claude Sonnet) | ✅ Live |
| Multi-Agent Debate (Gemini + GPT-4o + Claude) | ✅ Live |
| Reverse DCF + Expectation Gap | ✅ Live |
| Macro Stress Test (4 scenarios) | ✅ Live |
| Backtest Engine (monthly rebalance) | ✅ Live |
| Prediction Log + Verification | ✅ v1.1 |
| Supabase Snapshots | ✅ Live |
| Telegram Alerts | ✅ Live |
| Paper Trading | ✅ Live |
| Modern SaaS UI (white cards) | ✅ Live |
| Custom Cowork Skills (3) | ✅ Live |

## v13.5 — In Progress / Recently Shipped

| Feature | Status | Notes |
|---------|--------|-------|
| Full market screener (10,461 stocks) | ✅ Built | api/live-quotes.js → Eastmoney push2, Screener tab |
| Real-time price charts | ✅ Built | api/price-chart.js → Yahoo Finance v8, any ticker |
| News Chinese translation | ✅ Built | api/translate.js → Claude Haiku; auto on lang switch |
| Capital flow via Vercel API | ✅ Built | api/capital-flow.js → Eastmoney datacenter (bypasses AKShare) |
| Yahoo Finance UA bypass | ⏳ Pending push | fetch_data.py fix committed locally; user needs to git push |
| AKShare replacement | 🔶 Partial | Capital flow done; universe data still uses AKShare |

### Known Data Pipeline Limitations
- **AKShare is geo-blocked from GitHub Actions (US)**: affects universe_a/hk updates, margin data, dragon tiger
- **Fix options**: (A) HK/SG VPS ~$5/month runs AKShare locally; (B) replace remaining AKShare calls with direct Eastmoney API
- **Recommendation**: Add HK VPS for batch data; keep Vercel for real-time APIs

---

## v14 — Next Sprint

### v14.1 — Swing Trading Signal Module ✅
**Goal**: Rule-based entry/exit zone detection (not AI, deterministic)  
**Signals**: MA20/MA60 crossover, RSI(14) zones, volume breakout, MA bounce  
**Output**: `public/data/signals_[ticker].json` → `SwingSignal` component in Scanner + Research tabs  
**Effort**: ~1 session  
**Shipped**: 2026-04-18

### v14.2 — UBS Pitch Framework
**Goal**: Deep Research outputs in IB pitch structure (Situation/Complication/Question/Answer/Evidence/Risk)  
**Change**: Modify `api/research.js` prompt + add pitch section to Research tab  
**Effort**: ~1 session

### v14.3 — Daily Auto-Brief
**Goal**: Automated 08:30 weekday monitoring summary  
**Output**: Cowork notification + Telegram message  
**Covers**: VP changes, RDCF gap, threshold alerts  
**Effort**: ~0.5 session

---

## v15 — Phase 3 Features

### v15.1 — Claude Earnings Tone Analysis
6-dimension transcript scoring: revenue guidance tone, margin commentary, capex signals, competition acknowledgement, management confidence, forward guidance specificity. ~$0.10/transcript via Claude API.

### v15.2 — Brinson-Fachler Attribution
Sector allocation + stock selection decomposition vs CSI 300 / HSI benchmarks. Requires 3+ months of real paper trading P&L data to accumulate first.

### v15.3 — VP Weight Calibration
Use backtest results to optimise Earnings Surprise / Multiple Expansion / Capital Revaluation weights via grid search. Replace starting weights (30/40/30) with data-driven ones.

### v15.4 — Consensus Estimate Integration
A-shares: `ak.stock_profit_forecast_em()` broker EPS forecasts  
HK: yfinance `.earnings_estimate`  
Goal: automate the consensus beat/miss calculation currently done manually.

---

## Future / Exploratory

- **Multi-user collaboration** — share platform with research team (auth required, architecture TBD)
- **Earnings call audio analysis** — tone/sentiment beyond transcript text
- **Options flow integration** — unusual options activity as a Capital Revaluation signal
- **Macro regime detection automation** — replace manual regime flags with rule-based detection
- **BeOne Medicines CELESTIAL data** — Phase 3 uMRD readout expected H2 2026, major catalyst

---

## Thesis Refresh Queue

These VP theses are outdated and need rebuilding before the next research cycle:

| Ticker | Issue | Priority |
|--------|-------|----------|
| BYD 002594.SZ | Original thesis exceeded by 2.6× — needs full rebuild | High |
| Innolight 300308.SZ | Directionally correct but 2026 data not incorporated | Medium |

---

## Metrics to Track

| Metric | Current | Target |
|--------|---------|--------|
| Prediction hit rate | 67% (2/3) | > 65% at n ≥ 10 |
| VP Score calibration | Starting weights | Backtest-optimised |
| Research coverage | 5 focus + dynamic | 5 focus + 50 watchlist |
| Daily data freshness | ~2 hrs post-market | Real-time (future) |
