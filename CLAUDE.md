# AR Equity Research Platform — Project Context

> This file is auto-loaded at the start of every session. Read it fully before writing any code.

## What This Project Is

A personal AI-augmented equity research platform built by Junyan (j.liu199@lse.ac.uk). Not SaaS — personal investment tool for systematic buy-side research on A-shares and HK equities. Core philosophy: **AI produces evidence and signals, human makes all investment decisions.**

Inspired by UBS Finance Challenge experience (中际旭创 long + Pop Mart short both validated by market). Goal: systematise the hedge fund research process.

---

## Deployment Architecture

```
src/Dashboard.jsx (React 18, ~4000 lines)
    │
    ├── Build: Vite 5.4 → dist/
    ├── Host: GitHub Pages → https://lateily.github.io/Alpha-Research/
    └── API: Vercel serverless → https://equity-research-ten.vercel.app
              ├── api/research.js  (Claude Sonnet, 8192 tokens)
              └── api/debate.js    (Gemini Bull + GPT-4o Bear + Claude Forensic)

CI/CD: GitHub Actions
    ├── fetch-data.yml  — cron 08:30 + 01:00 UTC weekdays → fetch_data.py → commit JSON
    └── deploy.yml      — on push to main → npm ci → vite build → gh-pages
```

**GitHub repo**: `https://github.com/Lateily/Alpha-Research`  
**Stable API base**: Always `https://equity-research-ten.vercel.app` for GitHub Pages — never use `VITE_API_BASE_URL` env var for GH Pages routing.

---

## Tech Stack

| Layer | Tech | Notes |
|-------|------|-------|
| Frontend | React 18 + Vite 5.4 | Single file: `src/Dashboard.jsx` |
| UI libs | recharts, lucide-react | Already in package.json |
| AI SDK | `@anthropic-ai/sdk` only | OpenAI + Gemini via raw `fetch()` REST — no npm packages |
| Data: A-shares | AKShare | Requires China IP — degrades gracefully on GitHub Actions |
| Data: HK stocks | yfinance | Works on GitHub Actions |
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

## Focus Stocks (5 Core Positions)

| Ticker | Company | Market | VP Score | Thesis Status |
|--------|---------|--------|----------|---------------|
| 700.HK | Tencent | HK | — | Active |
| 9999.HK | NetEase | HK | — | Active |
| 6160.HK | BeOne Medicines (前BiTE) | HK | 65 | Rebuilt Apr 2026 — ZS combo thesis |
| 002594.SZ | BYD | A | — | ⚠️ Needs VP refresh (exceeded 2.6×) |
| 300308.SZ | 中际旭创 (Innolight) | A | — | ⚠️ Needs VP refresh |

**Dynamic stocks**: Any stock researched via Deep Research that is NOT in the 5 above.
```js
const isDynamic = !STOCKS[ticker] && !!allStocks[ticker]
// isDynamic stocks: hide TA/K-line/Statements/CompanyProfile tabs
// Show AI-estimated data instead
```

---

## VP Score Architecture

Three independent engines, each scored independently then weighted:

| Engine | Max Score | Key Inputs |
|--------|-----------|-----------|
| Earnings Surprise | 30 | Consensus beat/miss magnitude |
| Multiple Expansion | 40 | PE/EV-EBITDA vs sector, FCF yield |
| Capital Revaluation | 30 | Buybacks, special divs, governance changes |

Total = weighted sum, 0–100. Modulated by policy regime detection.  
**VP is NOT a single formula** — it's three independent assessments combined.

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

// Price display
const fmtPrice = livePx?.last != null
  ? `${curr}${livePx.last.toFixed(2)}`
  : s.price  // s = STOCKS[ticker] static fallback

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

**Always check these before pushing any Dashboard.jsx change:**

1. **JSX trailing comment after closing tag** → build crash
   ```jsx
   // ❌ </div>{/* end app */}   ✅ </div>
   ```

2. **Duplicate JSX props** → silent logic bug
   ```jsx
   // ❌ onFocus={a} onFocus={b}   ✅ onFocus={e=>{a(e);b(e);}}
   ```

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

## GitHub Actions Data Pipeline

| Script | What it does | Failure mode |
|--------|-------------|-------------|
| `fetch_data.py` | Prices, fundamentals, RDCF, stress test | yfinance flaky — has retry logic |
| `paper_trading.py` | Track paper positions | `continue-on-error: true` |
| `backtest.py` | Monthly rebalance backtest | Writes `"insufficient_data"` if < 60 days |
| `supabase_sync.py` | Push snapshots to Supabase | `continue-on-error: true` |
| `telegram_alert.py` | Send VP/price alerts | `continue-on-error: true` |

AKShare northbound/southbound APIs require China IP — these always fail on GitHub Actions and degrade gracefully.

---

## Vercel API Endpoints

| Endpoint | Function | Required env vars |
|----------|---------|-------------------|
| `POST /api/research` | Claude deep research, 8192 tokens | `ANTHROPIC_API_KEY` ✓ |
| `POST /api/debate` | 3-agent debate (Gemini+GPT-4o+Claude) | `ANTHROPIC_API_KEY` ✓, `OPENAI_API_KEY` ✓, `GOOGLE_AI_API_KEY` ✓ |

---

## Analysis Output Standards (Non-Negotiable)

1. Business model = first-principles (physical mechanism → money flow), not marketing description
2. Variant view = ONE precise thesis: "Market believes X → We believe Y → Proves right if A → Proves wrong if B"
3. AI never outputs buy/sell conclusions — only evidence, signals, structured scores
4. Every section needs evidence quality rating + AI limitations disclosure
5. EQR rating uses mandatory degradation waterfall based on data age

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
