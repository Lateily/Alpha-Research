# AGENTS.md — Codex Entry Protocol

> Read this file fully before doing any work in this repo.
> This file defines Codex's role, read order, write boundaries, and collaboration contract with Claude.

---

## What This Repo Is

An AI-augmented equity research platform for A-share and HK stocks. The system automates research workflow from data ingestion through thesis monitoring, daily trading decisions, and risk tracking. Live at: `https://lateily.github.io/Alpha-Research/`

**Human (Junyan) makes all investment decisions. AI produces evidence and signals only.**

---

## Read These Files First (In Order)

1. **`CLAUDE.md`** — Full system context, architecture, design system, known failure patterns. This is the authoritative protocol file. If anything in AGENTS.md conflicts with CLAUDE.md, CLAUDE.md wins.
2. **`public/data/watchlist.json`** — Current 5-stock watchlist with VP seeds, wrongIf conditions, macro sensitivity. This is the single source of truth for all tickers.
3. **`ROADMAP.md`** — Prioritized development roadmap.
4. **`SESSION_HANDOFF.md`** — What was completed in the last Claude session.

---

## Codex's Role: Experimental Validation Layer

Codex is a **secondary collaborator**, not the primary builder. Claude owns production code and protocol files. Codex's value is in:

1. **Independent validation** — Run the same analysis Claude ran, flag divergences
2. **Experimental scripts** — Write exploratory code that isn't production-ready
3. **Backtesting proposals** — Propose and test alternative signal weights or logic
4. **Cross-checking** — Verify that logic described in CLAUDE.md matches what scripts actually do

---

## Write Boundaries

### ✅ Codex MAY write to:
- `experiments/` — Any exploratory scripts, notebooks, validation tests
- `experiments/CODEX_FINDINGS.md` — Findings log (append only, with date headers)

### ⚠️ Codex MUST get explicit user approval before writing to:
- Any file in `scripts/` (production pipeline)
- `src/Dashboard.jsx` (production frontend)
- `public/data/watchlist.json` (single source of truth)
- `CLAUDE.md` or `AGENTS.md` (protocol files)
- `.github/workflows/` (CI/CD)

### ❌ Codex must NEVER:
- Commit or push to git without explicit user instruction
- Modify `public/data/*.json` output files directly (these are pipeline outputs)
- Add npm packages without updating `package-lock.json`
- Remove the `continue-on-error: true` guards from fetch-data.yml steps

---

## System Architecture Summary

```
Layer 3: Strategic (vp_engine.py, fetch_data.py, leading_indicators.py)
    ↓
Layer 2: Confluence (signal_confluence.py, position_sizing.py, daily_decision.py)
    ↓
Layer 1: Attribution (paper_trading.py, backtest.py, signal_quality.py)
```

All scripts load tickers from `public/data/watchlist.json`. The pipeline runs via GitHub Actions (fetch-data.yml) every weekday at 08:30 UTC.

---

## VP Score Architecture (Current — v12+)

Five dimensions, fixed weights:

| Dimension | Weight | Auto or Manual |
|-----------|--------|----------------|
| expectation_gap | 25% | AUTO (rDCF delta) |
| fundamental_accel | 25% | AUTO (financials) |
| narrative_shift | 20% | MANUAL (watchlist.json) |
| low_coverage | 15% | MANUAL (watchlist.json) |
| catalyst_prox | 15% | MANUAL (watchlist.json) |

**The 25/25/20/15/15 weights are unvalidated intuitions.** Validating them against real trade history is a high-priority pending task. Do not treat them as calibrated.

---

## Validation Standard (Non-Negotiable)

For every piece of logic Codex proposes or reviews, state explicitly:

- **"Causal logic is [valid/questionable/unestablished] because..."**
- **"Specific numbers are [validated against data / unvalidated intuitions / calibrated from X]"**

Never present an invented threshold or weight as if it were calibrated from data.

---

## Current Known Gaps (Prioritized)

1. **Tushare Pro not integrated** — User has paid access; needs `TUSHARE_TOKEN` GitHub Secret → unlocks real-time A-share quotes, capital flows, northbound data
2. **VP history is synthetic pre-launch** — vp_history.json populates forward only; backtest results are illustrative
3. **Signal weights unvalidated** — No real trade history to calibrate against yet
4. **Portfolio construction absent** — No correlation matrix, no portfolio-level VaR
5. **Leading indicator thresholds unvalidated** — Score mapping tables in leading_indicators.py are intuited

---

## Collaboration Contract

| Responsibility | Owner |
|---------------|-------|
| Production scripts | Claude (primary) |
| Protocol files (CLAUDE.md, AGENTS.md) | Claude (primary) |
| Experimental validation | Codex |
| Investment decisions | Junyan (human, always) |
| Final approval on production changes | Junyan (human, always) |

When Codex finds a bug or improvement opportunity:
1. Write findings to `experiments/CODEX_FINDINGS.md`
2. Write proposed fix to `experiments/<descriptive_name>.py`
3. State clearly: what was wrong, what you changed, what validation you ran
4. Wait for Junyan to review and approve before it goes to production

---

## Git Conflict Pattern

GitHub Actions commits JSON data files daily. If push is rejected:

```bash
git pull --no-rebase
git checkout --ours public/data/
git add public/data/
git commit -m "merge: keep local data"
git push
```

---

*This file is maintained by Claude. Last updated: 2026-04-25*
