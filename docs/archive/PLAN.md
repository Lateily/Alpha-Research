# Current Work Plan

> Updated: 2026-04-17 | Platform version: v13.4

## Status: Platform Stable ✅

All core modules deployed and working. Git is clean. Ready for next feature sprint.

---

## Recently Completed (v13 Sprint)

- [x] Multi-Agent Debate — Gemini (Bull) + GPT-4o (Bear) + Claude (Forensic) → CIO synthesis
- [x] Live data accuracy — price/mktcap/financials from `liveData.yahoo[ticker]`, static as fallback
- [x] isDynamic guard — Deep Research stocks hide live-data-dependent sections
- [x] API routing fix — GH Pages always routes to `equity-research-ten.vercel.app`
- [x] Company identity fix — `company` name passed to Claude prompt (solves ticker rename issue)
- [x] Reverse DCF — pure-Python bisection, dual-market WACC, biotech revenue model
- [x] Macro Stress Test — 4 scenarios × 5 stocks × 4 factors (stress_config.json pre-generated)
- [x] Prediction Log v1.1 — 4 resolved predictions, 67% hit rate
- [x] Modern SaaS UI — white cards, #E9EFF9 bg, Inter + JetBrains Mono
- [x] Custom skills — ar-code-reviewer, ar-security-auditor, ar-release-engineer

---

## Active Priorities

### 🔴 Immediate (Next Session)

#### Option A — Swing Trading Signal Module
Add buy/sell zone indicators to Scanner tab based on rule-based signals:
- MA20/MA60 crossover detection
- RSI(14) overbought/oversold zones
- Volume breakout detection
- Output: signal banner per stock (BUY ZONE / SELL ZONE / NEUTRAL), NOT a recommendation

Implementation:
- Compute signals in `fetch_data.py` from OHLC data → `public/data/signals_[ticker].json`
- Add `SwingSignal` component to Scanner tab in Dashboard.jsx
- Use C.green / C.red / C.mid for signal colors

#### Option B — UBS Pitch Framework Integration
Structure Deep Research output in Investment Banking pitch format:
- Situation (business + market context)
- Complication (why now, what's changed)
- Question (the variant view)
- Answer (our thesis)
- Evidence (data points)
- Risk (what proves us wrong)

Modify `api/research.js` prompt to output this structure. Add new section in Research tab.

#### Option C — Daily Auto-Brief (Cowork Scheduled Task)
Every weekday 08:30: auto-generate 5-stock monitoring summary
- VP score changes vs yesterday
- Price vs RDCF implied value gap
- Any threshold triggers (VP > 70, price deviation > 15%)
- Output: Cowork notification + Telegram

#### Option D — BYD + Innolight VP Thesis Refresh
BYD: original thesis exceeded by 2.6× — needs full rebuild with new variant view
Innolight: directionally still valid, needs 2026 data update

---

## Backlog (Phase 3)

- [ ] Claude earnings tone analysis — 6-dimension scoring, ~$0.10/transcript
- [ ] Brinson-Fachler sector attribution — waiting for real P&L data to accumulate
- [ ] VP Score weight calibration — backtest results → optimal engine weights
- [ ] Multi-user collaboration — team sharing (architecture TBD)
- [ ] BeOne Medicines (6160.HK) CELESTIAL Phase 3 — watch for H2 2026 uMRD data

---

## Known Debt

| Item | File | Priority |
|------|------|----------|
| BYD VP thesis stale | prediction_log.json + Research | High |
| Innolight VP thesis needs 2026 update | Research | Medium |
| Northbound flow data | fetch_data.py | Low (China IP required) |
| Dashboard.jsx approaching 4000 lines | src/Dashboard.jsx | Medium (consider splitting) |
