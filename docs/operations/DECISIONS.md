# Architectural Decisions Log

> Why we built things the way we did. Read before suggesting architecture changes.

---

## D-001 — Pure Python bisection instead of scipy
**Date**: April 2026  
**Decision**: Implement `_bisect(f, lo, hi, tol, maxiter)` from scratch instead of `scipy.brentq`  
**Why**: scipy caused dependency conflicts in GitHub Actions. The platform only needs root-finding for Reverse DCF — a 15-line bisection is sufficient and eliminates the dependency entirely.  
**Trade-off**: Slightly slower convergence than Brentq, but for DCF (single calculation, not batch) this is imperceptible.

---

## D-002 — OpenAI + Gemini via raw fetch(), not npm packages
**Date**: April 2026  
**Decision**: Call OpenAI and Google APIs via native `fetch()` REST, not `openai` or `@google/generative-ai` npm packages  
**Why**: Adding those packages to `package.json` without updating `package-lock.json` caused `npm ci` to fail in GitHub Actions. The Vercel serverless environment has `fetch` built in — no packages needed.  
**Trade-off**: More verbose code in `api/debate.js`, but zero lock file conflicts.

---

## D-003 — GitHub Pages (static) + Vercel (API) split
**Date**: April 2026  
**Decision**: Frontend on GitHub Pages, serverless API on Vercel — two separate deployments  
**Why**: GitHub Pages is free, permanent, and zero-maintenance for static assets. Vercel handles serverless functions with env var management. Mixing them would require either full Vercel (costs money at scale) or full GitHub Pages (can't run server-side code).  
**Trade-off**: Two deployment targets to manage. Solved by hardcoding `equity-research-ten.vercel.app` as the API base for GH Pages — no dynamic URL resolution needed.

---

## D-004 — Supabase over Firebase/MongoDB
**Date**: April 2026  
**Decision**: Supabase for VP score snapshots and OHLCV storage  
**Why**: Free 500MB PostgreSQL with auto-REST API. SQL is better for time-series financial data than document stores. Firebase free tier was too restrictive; MongoDB requires more setup.  
**Trade-off**: Supabase free tier has 500MB limit and pauses after 1 week of inactivity.

---

## D-005 — Custom pandas backtest, not zipline/backtesting.py
**Date**: April 2026  
**Decision**: `scripts/backtest.py` uses a manual pandas monthly-rebalance loop  
**Why**: zipline and backtesting.py are designed for hundreds of stocks with tick-level data. We have 5–15 stocks and need monthly-level analysis. A custom loop is 100 lines, fully controllable, and avoids heavy framework dependencies.  
**Trade-off**: No built-in slippage model or advanced order types. Acceptable for buy-side research (not execution).

---

## D-006 — Single file Dashboard.jsx (~4000 lines)
**Date**: April 2026  
**Decision**: All React components in one file  
**Why**: Easier to share full context with AI (no multi-file coordination), easier to audit, no import resolution complexity. The platform is a personal tool — not a product with multiple developers.  
**Trade-off**: File is approaching maintainability limits. Consider splitting at 5000+ lines.  
**Split plan (when needed)**: Extract `DebatePanel`, `MacroStressTest`, `ReverseDCF`, `PredictionLog` into separate files under `src/components/`.

---

## D-007 — AI outputs evidence only, never conclusions
**Date**: April 2026 (from UBS Challenge learnings)  
**Decision**: All AI-generated analysis outputs structured evidence and scores — never "buy", "sell", "overweight"  
**Why**: Investment decisions require human judgment that accounts for portfolio context, risk tolerance, and information AI cannot access. AI-generated investment conclusions create false confidence. This is also the UBS AI Analyst framework we adopted as a design principle.  
**Trade-off**: More effort to interpret outputs. The trade-off is intentional.

---

## D-008 — Resend.com over SendGrid for email
**Date**: April 2026  
**Decision**: Resend.com for email digests  
**Why**: SendGrid cancelled its free tier in May 2025. Resend offers 3,000 emails/month free with a clean API.  
**Trade-off**: Less mature than SendGrid, but sufficient for personal daily digests.

---

## D-009 — isDynamic pattern for Deep Research stocks
**Date**: April 2026  
**Decision**: `const isDynamic = !STOCKS[ticker] && !!allStocks[ticker]` to detect non-focus stocks  
**Why**: Deep Research can analyse any stock, but fetch_data.py only runs for the 5 focus stocks. Dynamic stocks have no OHLC/TA/Statements data — showing empty sections is confusing. isDynamic hides those sections and shows AI-estimated data instead.  
**Trade-off**: Code branching in Research component. Worth it for clean UX.

---

## D-010 — VP Score as three independent engines, not one formula
**Date**: April 2026  
**Decision**: VP = Earnings Surprise (max 30) + Multiple Expansion (max 40) + Capital Revaluation (max 30), each scored independently  
**Why**: A single formula with arbitrary weights cannot capture the qualitative differences between thesis types. A capital revaluation thesis (buyback + governance) is fundamentally different from an earnings surprise thesis. Three engines allow each to be calibrated independently.  
**Trade-off**: More complex to compute and explain. Starting weights are estimates — must be calibrated against backtest results (Phase 3).
