# AR Equity Research Platform — Project Context

> This file is auto-loaded at the start of every Claude session. Read it fully before writing any code.
> **Last updated: 2026-04-25** (reflects v12+ system with watchlist, leading indicators, wrongIf monitor)

## What This Project Is

A personal AI-augmented equity research platform built by Junyan (j.liu199@lse.ac.uk). Not SaaS — personal investment tool for systematic buy-side research on A-shares and HK equities. Core philosophy: **AI produces evidence and signals, human makes all investment decisions.**

Inspired by UBS Finance Challenge (中际旭创 long + Pop Mart short both validated). Goal: systematise the hedge fund research process.

---

## Deployment Architecture

```
src/Dashboard.jsx (React 18, Vite 5.4)
    │
    ├── Build: Vite → dist/
    ├── Host: GitHub Pages → https://lateily.github.io/Alpha-Research/
    └── API: Vercel serverless → https://equity-research-ten.vercel.app
              ├── api/research.js  (Claude Sonnet, 8192 tokens)
              └── api/debate.js    (Gemini Bull + GPT-4o Bear + Claude Forensic)

CI/CD: GitHub Actions (runs every weekday 08:30 UTC + 01:00 UTC)
    ├── fetch-data.yml  — Full pipeline (see Pipeline section below)
    └── deploy.yml      — npm ci → vite build → gh-pages
```

**GitHub repo**: `https://github.com/Lateily/Alpha-Research`
**Stable API base**: Always `https://equity-research-ten.vercel.app` for GitHub Pages — never use `VITE_API_BASE_URL` env var for GH Pages routing.

---

## ⚠️ Single Source of Truth: watchlist.json

**`public/data/watchlist.json` is the ONLY place to add/remove tickers.**

All pipeline scripts derive their ticker lists from this file. Adding a ticker here auto-propagates to: financial data fetch, VP scoring, signals, confluence, position sizing, Telegram alerts, and the Dashboard on the next Actions run.

**Do not hardcode tickers in scripts.** Every script has a `_load_watchlist()` function.

---

## Tech Stack

| Layer | Tech | Notes |
|-------|------|-------|
| Frontend | React 18 + Vite 5.4 | Single file: `src/Dashboard.jsx` |
| UI libs | recharts, lucide-react | Already in package.json |
| AI SDK | `@anthropic-ai/sdk` only | OpenAI + Gemini via raw `fetch()` REST — no npm packages |
| Data: A-shares | AKShare | Requires China IP — degrades gracefully on GitHub Actions |
| Data: HK/US stocks | yfinance | Works on GitHub Actions |
| Data: A-shares (planned) | Tushare Pro | User has paid access; add TUSHARE_TOKEN to GitHub Secrets |
| Math | Pure-Python bisection `_bisect()` | No scipy — avoids Actions dep conflicts |
| DB | Supabase (PostgreSQL) | VP score snapshots + OHLCV, 500MB free |
| Alerts | Telegram Bot API | Triggered by `telegram_alert.py` |
| Deploy | GitHub Pages + Vercel | Static frontend + serverless API split |

---

## Design System — Never Deviate From These

```js
const C = {
  blue:   '#3A6FD8',   // primary accent
  green:  '#1E9C5A',   // positive / verified
  red:    '#D94040',   // negative / alert
  gold:   '#D08000',   // warning / pending
  dark:   '#1C2B4A',   // primary text
  mid:    '#6B82A0',   // secondary text
  bg:     '#E9EFF9',   // page background
  card:   '#FFFFFF',   // card background
  border: '#DCE5F3',   // card borders
  soft:   '#F0F5FC',   // subtle backgrounds
}
const SHADOW = '0 2px 12px rgba(50,90,160,0.10)'
const SHADOW_SM = '0 1px 4px rgba(50,90,160,0.08)'
const MONO = "'JetBrains Mono','Courier New',monospace"
// Card standard: borderRadius:12, boxShadow:SHADOW, border:`1px solid ${C.border}`
// Font: Inter for UI, JetBrains Mono for numbers/tickers
```

---

## Current Watchlist (as of 2026-04-25)

| Ticker | Company | VP Score | wrongIf Status |
|--------|---------|----------|---------------|
| 300308.SZ | 中际旭创 Innolight | 79 | MANUAL (1.6T mass production timing) |
| 700.HK | Tencent | 64 | CLEAR |
| 9999.HK | NetEase | 58 | ⚠️ TRIGGERED (earnings_growth -29.2%) |
| 6160.HK | BeiGene (BeOne) | 65 | MANUAL (CELESTIAL Phase 3 data) |
| 002594.SZ | BYD | 52 | ⚠️ TRIGGERED (revenue_growth -13.5%) |

---

## VP Score Architecture (v12+, CURRENT)

The VP Score is a 0-100 composite on **five** dimensions:

| Dimension | Weight | Source |
|-----------|--------|--------|
| expectation_gap | 25% | AUTO — rDCF delta (our_growth − implied_growth), continuous mapping |
| fundamental_accel | 25% | AUTO — fin_*.json (NI/Rev ratio, GM trend, FCF quality) |
| narrative_shift | 20% | MANUAL — synced from watchlist.json each run |
| low_coverage | 15% | MANUAL — synced from watchlist.json each run |
| catalyst_prox | 15% | MANUAL — synced from watchlist.json each run |

**expectation_gap is delta-based (NOT binary OVERPRICED/UNDERPRICED):**
```
delta = our_growth − implied_growth_from_rdcf
≤ -0.50 → 10 | ≤ -0.25 → 22 | ≤ -0.10 → 35 | ≤ 0 → 48
≤ +0.10 → 55 | ≤ +0.25 → 68 | ≤ +0.50 → 78 | >+0.50 → 88
```

**⚠️ Validation status:** Causal logic is real. Specific weights (25/25/20/15/15) are unvalidated intuitions. Never present them as calibrated.

---

## Three-Layer Pipeline Architecture

```
Layer 3: Strategic / Research
  ├── fetch_data.py          — OHLC, financials, rDCF
  ├── leading_indicators.py  — NVDA/hyperscaler CapEx/TSMC composite
  └── vp_engine.py           — VP Score + vp_history accumulation

Layer 2: Confluence / Decision
  ├── signal_confluence.py   — Multi-signal aggregation (including AI capex signals)
  ├── position_sizing.py     — Position weight suggestions
  └── daily_decision.py      — Trading decisions + wrongIf auto-monitor

Layer 1: Execution / Attribution
  ├── paper_trading.py       — P&L tracking
  ├── backtest.py            — VP threshold historical validation
  └── signal_quality.py      — Signal attribution feedback loop
```

**GitHub Actions pipeline execution order (fetch-data.yml):**
1. fetch_data.py → 2. paper_trading.py → 3. backtest.py → 4. swing_signals.py →
5. leading_indicators.py → 6. vp_engine.py → 7. signal_confluence.py →
8. position_sizing.py → 9. daily_decision.py → 10. signal_quality.py →
11. supabase_sync.py → 12. git commit → 13. telegram_alert.py → 14. deploy.yml

---

## AI Infrastructure Leading Indicators

Tracks upstream signals 3-6 months ahead of 中际旭创 earnings:
- NVDA quarterly revenue (weight: 35%)
- Hyperscaler CapEx index: MSFT+GOOGL+META+AMZN (weight: 35%)
- TSMC revenue growth (weight: 20%)
- Hyperscaler price momentum 3-month (weight: 10%)

Composite: STRONG_CAPEX_CYCLE (≥70) → injects +20 into 300308.SZ confluence.

**Output:** `public/data/leading_indicators.json`

---

## Live Data Flow

```js
// Always prefer live data, use static STOCKS as fallback only
const live   = liveData?.yahoo?.[ticker]
const livePx = live?.price
const liveFn = live?.fundamentals

// Currency by market
const isHK = ticker.endsWith('.HK')
const curr = isHK ? 'HK$' : '¥'

// Market cap (T/B threshold at 1000B)
const fmtMktCap = (() => {
  const mc = liveFn?.market_cap
  if (!mc) return s.mktcap
  const b = mc / 1e9
  return b >= 1000 ? `${curr}${(mc/1e12).toFixed(2)}T` : `${curr}${b.toFixed(1)}B`
})()
```

---

## Known Production Failure Patterns

**Always check before pushing any Dashboard.jsx change:**

1. **JSX trailing comment after closing tag** → build crash
   ```jsx
   // ❌ </div>{/* end app */}   ✅ </div>
   ```
2. **Duplicate JSX props** → silent logic bug
3. **New npm package without lock file update** → `npm ci` fails in Actions
4. **Hardcoded prices** → stale data immediately
5. **Missing isDynamic guard** → Deep Research stocks show empty data sections
6. **Wrong API routing** → `VITE_API_BASE_URL` overrides hardcoded Vercel URL for GH Pages
7. **Currency symbol mismatch** → HK$ vs ¥

**Quick JSX balance check:**
```bash
python3 -c "
import re
c=open('src/Dashboard.jsx').read()
print(f'div balance: {len(re.findall(r\"<div[\s>]\",c)) - len(re.findall(r\"</div>\",c))}')
"
# Must output: div balance: 0
```

---

## Known Pipeline Issues

| Issue | Status |
|-------|--------|
| AKShare fails from GitHub US IPs | Mitigation: `continue-on-error: true`; all scripts gracefully degrade |
| Tushare Pro not yet integrated | User has paid access; needs `TUSHARE_TOKEN` GitHub Secret |
| VP history pre-launch is synthetic | vp_history.json populates forward from first live run |
| Signal weights unvalidated | Require real trade history to calibrate — deferred |

---

## Git Conflict Pattern (Recurring)

GitHub Actions commits data JSONs daily while you push code changes. If `git push` is rejected:

```bash
git pull --no-rebase
git checkout --ours public/data/
git add public/data/
git commit -m "merge: keep local data"
git push
```

---

## Vercel API Endpoints

| Endpoint | Function | Required env vars |
|----------|---------|-------------------|
| `POST /api/research` | Claude deep research, 8192 tokens | `ANTHROPIC_API_KEY` ✓ |
| `POST /api/debate` | 3-agent debate (Gemini+GPT-4o+Claude) | All three API keys ✓ |

---

## Analysis Output Standards (Non-Negotiable)

1. Business model = first-principles (physical mechanism → money flow), not marketing description
2. Variant view = ONE precise thesis: "Market believes X → We believe Y → Proves right if A → Proves wrong if B"
3. AI never outputs buy/sell conclusions — only evidence, signals, structured scores
4. Every section needs evidence quality rating + AI limitations disclosure
5. **After every feature: explicitly state what's causally validated vs numerically unvalidated**
6. Never present invented weights as if they were calibrated

---

## Session Behaviour — Non-Negotiable Patterns

### 1. End-of-session action block (ALWAYS)

Every work session must end with a `你现在需要做的操作` block containing exact terminal commands. No exceptions, even for documentation-only sessions. Format:

```
你现在需要做的操作：
1. cd ~/Desktop/Stock/ar-platform
2. git add <specific files only — never git add .>
3. git commit -m "..."
4. git push
```

If there is nothing to push, still close with the block and note "nothing to commit — session was analysis only."

### 2. Numerical validation labelling (ALWAYS)

Every number, weight, threshold, or formula in analysis, code comments, and documentation must carry one of two labels:
- `[validated against data]` — tested against real trade history or external benchmark
- `[unvalidated intuition]` — reasonable prior, not yet back-tested

Current VP weights (25/25/20/15/15) are **[unvalidated intuition]**. Never upgrade this label without an explicit backtest. Never omit the label.

### 3. Git conflict resolution (recurring pattern)

GitHub Actions commits data JSONs daily. When `git push` is rejected:

```bash
git pull --no-rebase
git checkout --ours public/data/
git add public/data/
git commit -m "merge: keep local data"
git push
```

Do not use `git pull --rebase` on data directories — Actions commits do not have conflict markers that rebase can resolve cleanly.

---

## Custom Skills (in Stock/.claude/skills/)

| Skill | Use when |
|-------|---------|
| `ar-code-reviewer` | Any code review request, before push |
| `ar-security-auditor` | Reviewing API/secrets/Vercel functions |
| `ar-release-engineer` | Before git push, diagnosing CI failures |

---

## Prediction Log Track Record (v1.1)

| ID | Ticker | Thesis | Verdict |
|----|--------|--------|---------|
| pred_002 | 700.HK | Ads revenue > RMB 1,450B | ✅ VERIFIED |
| pred_003 | 9999.HK | Japan MAU > 500万 | ~ INCONCLUSIVE |
| pred_004 | 6160.HK | Brukinsa quarterly > $380M | ❌ FALSIFIED |
| pred_005 | 002594.SZ | NEV sales > 350万/yr | ✅ VERIFIED |

Hit rate: 67% (2/3 decidable predictions correct)

---

## Collaborator Protocol

- **Claude (this file)**: Primary builder. Reads CLAUDE.md on every session start. Owns all production scripts and Dashboard.jsx.
- **Codex**: Experimental validation layer. Reads AGENTS.md on entry. Writes only to `experiments/` — never directly modifies production scripts without explicit user approval.
- **Human (Junyan)**: Makes all investment decisions. Approves any production changes proposed by either AI.
