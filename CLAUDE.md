# AR Equity Research Platform — Project Context

> This file is auto-loaded at the start of every Claude session. It is PROJECT CONTEXT AND HISTORY.
> **Last updated: 2026-09-14.** Authority order is set by `AGENTS.md`, not by this file: live human request, then `AGENTS.md` and the nearest nested one, then the compiled `ai-task.v1` manifest, then the architecture and constitution docs it names. Where this file conflicts with `AGENTS.md` or `docs/research/UNIFIED_RESEARCH_OS.md`, those win.

> **⚠ 2026-06-07 PIVOT NOTICE — SUPERSEDED 2026-08-03. Retained as history; do not act on it.**
> Current rule: AI outputs evidence, tiering and a research posture only. No buy/sell instruction, no target price presented as a recommendation, no win-rate or alpha claim below 30 independent causal clusters. The ¥1,000,000 model fund is virtual and every order carries `no_trade_flag: true`. See `docs/research/UNIFIED_RESEARCH_OS.md` §7 and `docs/strategy/MODEL_PAPER_FUND_POLICY.md`.
>
> 原文(已失效,仅存档): The product pivoted to an **internal model-recommendation pilot** (Daily Model Portfolio). As of 2026-06-07, the pilot **may output explicitly-labeled UNVALIDATED model recommendations / target ranges / construction logic** — **not** validated alpha, **not** external advice, and **no auto-trade or sizing without human execution**. The **human still makes the final decision** (executes the trade). This *supplements*, does not delete, the "human makes all investment decisions" philosophy and Analysis Output Standard #3 below. Full reconciliation deferred post-demo. See **`STATUS.md` top block (2026-06-07)** for the full pilot positioning + the recommendation→execution→attribution→improvement loop.

## ⚡ PRE-FLIGHT (before any work)

**Read in this order:**

1. `AGENTS.md` (root) plus the nearest nested one in `experiments/`, `scripts/llm/` or `web/` — the operating contract. **REQUIRED.**
2. `docs/ARCHITECTURE_MAP.md` — the single progress source: eight blocks, owners, completion, and the current week's real state.
3. Runtime state, read-only: `experiments/execution_tracker/nightly_run.json` for the last run, `public/data/v2/meta.json` for what is published.
4. This file — project background and design history.
5. Research work also needs `docs/research/UNIFIED_RESEARCH_OS.md` (v1.5, the六条机器可执行规则) and `docs/research/WEEKLY_RESEARCH_FACTORY.md` (posture ladder, E1–E4, two human gates).

`STATUS.md` is FROZEN as of 2026-07-29 and is archive only. It is no longer a pre-flight requirement; anything it says about current state is stale by design.

After pre-flight, answer one sentence: which block in ARCHITECTURE_MAP does today's task belong to, and which gate does it move? If neither, it is not the task.

## What This Project Is

A personal AI-augmented equity research platform built by Junyan (j.liu199@lse.ac.uk). Not SaaS — personal investment tool for systematic buy-side research on A-shares and HK equities. Core philosophy: **AI produces evidence and signals, human makes all investment decisions.** *(2026-06-07: supplemented for the internal model-recommendation pilot — the AI now also outputs explicitly-labeled UNVALIDATED recommendations / target ranges; the human still makes the final decision. See the PIVOT NOTICE at top.)*

Inspired by UBS Finance Challenge (中际旭创 long + Pop Mart short both validated). Goal: systematise the hedge fund research process.

---

## Deployment Architecture

**现行(2026-09):** 生产运行时是本机 `~/ar-live`,由 launchd 驱动夜链 v4(周一至周五 20:30)、EOD(14:26)与哨兵(09:14)。
引擎产物经 `export_contracts.py` 写入 `public/data/v2/` 的只读契约,消费入口有两个:对外的 GitHub Pages 旧 Dashboard,
以及本机只读工作台(Tailscale 私有地址,仅 owner,team/paid/production 三个开关全部 DENY)。`web/` 新前端尚未开工。
下面这张部署图是 2026-04 至 06 产品期的历史记录,Vercel API 按架构图标注为停用。

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

> **历史段落。** 现行证券域是 U0 永久注册表(`security_registry.json`,约 5,558 个代码),观察名单在 `run_official_sample.py` 内;`watchlist.json` 属旧管道。

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

### Limit-only color exceptions (Junyan 2026-05-02 §4.4 Option C)

Two hex literals are NOT in the `C` palette but are documented exceptions
for **limit-up / limit-down ONLY** indication on A-share stocks. They
must NEVER be reused for any other purpose.

| Literal   | Indication                    | Where used                                                           |
|-----------|-------------------------------|----------------------------------------------------------------------|
| `#EF4444` | 涨停 (upper price limit hit)  | Browse slim live bar count chip, FBtn direction chip                 |
| `#9333EA` | 跌停 (lower price limit hit)  | Browse slim live bar count chip, FBtn direction chip, **row left-border accent (Phase 4)** |

**Asymmetry note:** the 涨停 row left-border accent uses `C.red` (the
palette token), NOT `#EF4444`. The 跌停 row accent uses `#9333EA` because
no purple token exists in `C` to substitute. This asymmetry is intentional
per design-001 §3.4 and §4.4 — `C.X` tokens are preferred wherever
substitutable; the literals are kept ONLY where the palette has no
equivalent (跌停 = purple) or where backwards-compat with already-shipped
inline chips matters (the slim-bar count + FBtn).

These two colors are **categorically different from up/down** (`C.green` /
`C.red`) — they signal a limit-state event, not a magnitude. That's why
they live outside the regular palette.

**Reuse policy:** any new code that needs to represent 涨停/跌停 may
reference these literals (don't introduce a third variant). Any new code
that does NOT represent 涨停/跌停 must use `C.X` tokens, not these.

If you find yourself wanting to use `#EF4444` for "very negative" or
`#9333EA` for "highlighted purple", STOP — that's exactly the drift this
exception was designed to prevent. Use `C.red` / `C.gold` / `C.blue`
respectively.

---

## Current Watchlist (as of 2026-04-25)

> **历史段落,勿作当前持仓或关注池使用。** 当前模拟盘 0 持仓,深研对象由 U4 闸门逐批选定。

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
3. AI never outputs buy/sell conclusions — only evidence, tiering, and a posture on the ladder *(the 2026-06-07 recommendation-pilot supplement was superseded on 2026-08-03; posture-only is the rule again)*
4. Every section needs evidence quality rating + AI limitations disclosure
5. **After every feature: explicitly state what's causally validated vs numerically unvalidated**
6. Never present invented weights as if they were calibrated

---

## Session Behaviour — Non-Negotiable Patterns

### 1. End-of-session action block (ALWAYS)

Every work session must end with a `你现在需要做的操作` block containing exact terminal commands. No exceptions, even for documentation-only sessions. Format:

```
你现在需要做的操作：
1. cd ~/ar-live  # 2026-07-29 起唯一运行时(旧 ar-platform 已退役)
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
| `neat-freak` | End of every session — aligns CLAUDE.md, docs/, memory. Trigger: `/neat`, `整理一下`, `sync up` |
| `auto-work-mode` | Autonomous continuous work mode (renamed 2026-05-01 from `night-shift`; directory `.shifts/` renamed 2026-05-02 from `.night-shift/`) — **requires Claude Code CLI** (`--dangerously-skip-permissions`), does NOT run in Cowork. Runs any time of day until interrupted. Triggers: `/auto`, `开始工作`, `工作`, `go ahead`. |

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

## Collaborator Protocol (2026-09)

- **Junyan (human)**: sole decision maker. Owns both human gates: U4 SELECT authorises deep research only, and a separate verbatim, plan-hash-bound approval is required before any paper order. Only he merges PRs.
- **Claude**: builder and independent reviewer. Owns the nightly chain, production scripts, ops and most R-items; reviews Codex PRs and records verdicts. Works in isolated worktrees, never pushes to main, never `git add .`.
- **Codex**: work-order implementer, one order per branch per PR, file scope named in the order and a mutation pin per PR. Scope is set by the work order, not limited to `experiments/`; the 2026-09 orders include `api/`, `scripts/` and `experiments/`.
- **Reed**: AI engineering and the Windows/WSL counterpart. Must not run production apply, must not touch `~/ar-live`, must not run the nightly.
- **学长 / PM**: part-time PM and investment-logic challenger per `docs/team/PM_OPERATING_SYSTEM.md`. Reviews and challenges; has no real-money approval right. The weekly cadence has been stalled since 2026-W31.

Shared rules: secrets never enter code, commits or chat; degraded data stays visible as DATA_BLOCKED or PARTIAL and is never turned into zero or a stale value presented as current.

不是买卖指令;研究信号,human executes.
