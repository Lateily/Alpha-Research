# Task Plan — AR Equity Research Platform

> ⚡ ALWAYS read this file at the start of every session and before any significant code change.
> Core principle: context window = RAM (volatile) → write everything important to files = disk (persistent)

---

## Current Phase: v14 Feature Sprint

**Platform state**: Stable at v13.4. Git clean. All core modules deployed.  
**Next action**: Choose one of the four directions below and execute.

---

## Phase Status

### ✅ Phase 1 — Foundation (COMPLETE)
- [x] React dashboard (Dashboard.jsx) with 5-tab layout
- [x] VP Score (3-engine: Earnings Surprise / Multiple Expansion / Capital Revaluation)
- [x] GitHub Pages + Vercel deployment
- [x] GitHub Actions daily data pipeline

### ✅ Phase 2 — Data & Quant (COMPLETE)
- [x] AKShare + yfinance dual data pipeline
- [x] Supabase snapshots + Telegram alerts
- [x] Backtest engine (monthly rebalance, Bootstrap CI)
- [x] Paper trading JSON workflow
- [x] Reverse DCF (pure-Python bisection, dual-market WACC)
- [x] Macro Stress Test (4 scenarios × 5 stocks × 4 factors)

### ✅ Phase 3 — AI Features (COMPLETE)
- [x] Deep Research (Claude Sonnet, 8192 tokens)
- [x] Multi-Agent Debate (Gemini Bull + GPT-4o Bear + Claude Forensic → CIO synthesis)
- [x] Prediction Log v1.1 (4 resolved, 67% hit rate)
- [x] Modern SaaS UI (white cards, Inter + JetBrains Mono)

### ✅ Phase 4 — Context Engineering (COMPLETE, this session)
- [x] CLAUDE.md — project context auto-loaded every session
- [x] PLAN.md — current work priorities
- [x] DECISIONS.md — architectural decision log (10 decisions recorded)
- [x] ROADMAP.md — feature roadmap v14/v15
- [x] task_plan.md — this file (Manus-style planning)
- [x] findings.md — research and discovery log
- [x] progress.md — session log
- [x] Custom skills: ar-code-reviewer, ar-security-auditor, ar-release-engineer

### 🔄 Phase 5 — v14 Feature Sprint (NEXT)

Choose ONE to start:

- [ ] **A. Swing Trading Signals** — MA/RSI rule engine → signal banners in Scanner
- [ ] **B. UBS Pitch Framework** — IB-format Deep Research output
- [ ] **C. Daily Auto-Brief** — Cowork Scheduled Task, 08:30 weekday summary
- [ ] **D. BYD + Innolight VP Refresh** — Rebuild stale thesis documents

---

## Decision Log (Quick Reference)
Full details in DECISIONS.md.

| ID | Decision | Reason |
|----|----------|--------|
| D-001 | Pure Python bisection (no scipy) | Actions dep conflict |
| D-002 | OpenAI/Gemini via raw fetch() | npm lock conflict |
| D-003 | GH Pages + Vercel split | Free tier optimisation |
| D-004 | Supabase over Firebase | Free PostgreSQL + SQL |
| D-005 | Custom pandas backtest | Overkill frameworks avoided |
| D-006 | Single file Dashboard.jsx | AI context simplicity |
| D-007 | AI outputs evidence only | UBS framework principle |
| D-008 | Resend over SendGrid | SendGrid killed free tier |
| D-009 | isDynamic pattern | Clean UX for dynamic stocks |
| D-010 | 3-engine VP (not formula) | Independent calibration |

---

## Critical Rules (Never Forget)
1. JSX: no trailing comments after root `</div>`
2. New npm packages MUST update package-lock.json
3. Live data from `liveData.yahoo[ticker]` — static STOCKS is fallback only
4. GH Pages always routes to `equity-research-ten.vercel.app` — ignore VITE_API_BASE_URL
5. isDynamic guard on all data-dependent sections
6. AI never outputs buy/sell conclusions
