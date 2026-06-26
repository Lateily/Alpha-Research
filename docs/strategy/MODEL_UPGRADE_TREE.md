# Model Upgrade Tree — 研究 + 执行门 + Paper Portfolio + 前端

> **Status:** Ratified by Junyan 2026-06-26. Standing construction blueprint for
> evolving the model from a *research assistant* into a *daily research + risk +
> paper-trade evaluation system* — while never crossing the line into placing
> real orders or claiming validated alpha.
>
> **This document is the single source of truth for the upgrade roadmap.** It
> exists so the plan does not live only in chat, and so Claude (primary builder)
> and Codex (experiments layer) build against the same layered blueprint.

---

## 0. Prime Directive — Layered, Not Merged

**Each layer ships and is independently verifiable on its own. NEVER bundle the
layers into one "big model upgrade package" — that becomes an unverifiable
mega-project.** A layer is "done" only when its own done-criterion (below) is met
and green. Do not start claiming the value of a later layer before an earlier one
verifies.

---

## 1. The Four Product Layers (the destination)

1. **研究 — Core Thesis Factory**: factpack → thesis → valuation bridge → red-team → court.
2. **执行门 — Execution Gate**: market / sector / fund / technical → posture + levels.
3. **Paper Portfolio**: paper entry / stop / take-profit → daily PnL → win-rate / expectancy.
4. **前端产品化 — Frontend**: Dashboard reads repo JSON (never local files).

---

## 2. Invariant Guardrails (apply to EVERY layer, no exceptions)

- **No real-money buy/sell instruction.** Posture + paper references only. The
  model never tells Junyan to buy/sell/割/加/清 his real book.
- **No alpha / win-rate claim below 30 independent official samples.**
- **Official sample = post-close 定盘 ONLY.** Intraday data NEVER enters the
  statistical sample (even East Money's mid-session daykline lies — proven:
  利通 mid-session +3.72亿 vs true close −11.75亿).
- **Paper PnL = no look-ahead (P3's first iron law).** Entry triggers are
  *registered with a timestamp BEFORE* the price is hit; fills are recorded only
  when price actually crosses; T+N returns are backfilled from the official
  定盘 close; an entry is **never retro-edited after seeing the day's move**.
  Otherwise the win-rate is fake and we fool ourselves.
- **E1–E4 evidence tiers** on every load-bearing number; **DATA_CONFLICT halts**;
  **primary exchange data > media narrative** (proven: Tushare index_global
  refuted a 财富号 "global meltdown" narrative 2026-06-26).
- **Data boundary (productization):** GitHub Actions / Pages / cloud Claude API
  read ONLY `repo files + GitHub Secrets + external DB/API + request payload`.
  They CANNOT read `~/.claude/skills`, `~/.codex/memories`, `/private/tmp`, or
  Desktop files. **All product logic, prompts, and output schemas must live in
  the repo** or the cloud/frontend cannot see them.

---

## 3. Priority Layers (ratified P0–P4)

### P0 — 必做地基 (Foundation, must land first)

| # | Item | What | Done = | Owner |
|---|------|------|--------|-------|
| P0.1 | **DataSources 规范** (Gate 0 *data layer* — NOT the sentiment gate, see §5 naming) | Tushare定盘/财务/资金/全球/北向 · Tushare SDK `realtime_quote(src='sina')` 盘中 · Tencent/Sina 末级 fallback · **盘中永不进样本**. This is a *contamination rule*, not a feature. | PR merged + `fund_source`/`execution_tracker` selftests green; patch verified in `/private/tmp/ar-gate0-data-sources` (17/17) | **Codex** (worktree ready, PR pending Junyan "开 PR") |
| P0.5 | **纪律层落库** *(Claude-proposed, pending Junyan ratify)* | Move the discipline/prompt/LLM-summary logic out of local `SKILL.md` into the repo (e.g. `experiments/execution_tracker/prompts/` + a summary generator). Today terminal quality = "repo code + local SKILL discipline"; cloud has only repo code → product summaries would be "soulless" (no posture/E1-E4 constraint). | A repo prompt/discipline module the cloud can read | **Claude** |

### P1 — 每日样本与报告主线 (the win-rate engine)

| # | Item | What | Done = | Owner |
|---|------|------|--------|-------|
| P1.1 | **盘后 official sample 自动化** | Daily post-close: Tushare `daily` + `moneyflow_dc` + `index_daily` + `moneyflow_mkt_dc` → 大盘收尾 · portfolio表现 · 个股资金/技术/posture · paper PnL · T+1/3/5/10 回填. **The ONLY source of win-rate / expectancy.** | `run_post_close_report.py` runs daily, appends to `paper_signal_log`, schema stable; **target = accumulate to 30 independent signals** | Claude logic / Codex wiring |
| P1.2 | **盘前/集合竞价 + 开盘30min 观察** | Risk **observation only, NOT a sample**. Output: market-state · portfolio risk · key levels · 是否高反身性 · 是否需 DE_RISK_REVIEW. | `run_premarket_monitor.py` emits observation JSON with `sample_eligible:false` | Claude logic / Codex wiring |

### P2 — 解释力增强 (why, not just what)

| # | Item | What | Done = | Owner |
|---|------|------|--------|-------|
| P2.1 | **Gate 0 全球风险情绪门** (the *brain*) | Explains "why is risk appetite like this pre-open." Inputs: 隔夜美股 AI/半导体 · 纳指/标普 · 日经/KOSPI · 北向 · 政策/新闻**源可靠性**. Output: `GLOBAL_RISK_ON / GLOBAL_WEAK_REPAIR / GLOBAL_RISK_OFF / NEWS_UNRELIABLE`. | Gate emits a daily global-risk state from primary index data; refutes media on conflict | Claude |
| P2.2 | **异动归因层** | Decompose每只涨跌 into 大盘β + 板块β + 个股α + 资金结构 + 事件催化. Post-close report then判断板块带的 / 个股主动强 / 资金假修复, not just "涨了/跌了". | Attribution columns in the daily report | Claude |

### P3 — 风控与 Paper Portfolio

| # | Item | What | Done = | Owner |
|---|------|------|--------|-------|
| P3.1 | **止损/止盈风控层** (paper / review ONLY) | Output is NOT "卖出" — it is `stop_reference / take_profit_reference / invalidation / R_multiple / MFE / MAE / expectancy`. Records daily: "if executed per the model, would it profit?" | `paper_portfolio.json` + `paper_trade_log.json` with the no-look-ahead discipline of §2; expectancy computable once ≥30 | Claude logic / Codex wiring |

### P4 — 暂缓但保留 (parked, kept in long-term scope)

| # | Item | Note |
|---|------|------|
| P4.1 | **Line C 量化** | Long-term scope, not the current main line. 5 families dead → no hard alpha-mining now. Revisit with **low-turnover / execution-overlay** designs only AFTER execution-gate samples accumulate. |
| P4.2 | **Line D SMC** | **Paper schema first** (BOS/CHoCH · liquidity sweep · order block · FVG · premium/discount), then paper-stat. No live trading. |

---

## 4. Not In Scope (explicit — do not build these now)

- ❌ 24h LLM resident summarization. LLM runs **only at fixed checkpoints**
  (08:45 盘前 · 09:25 集合竞价结束 · 10:00 开盘30min · 11:35 午盘 · 15:10 盘后官方样本 ·
  夜间全球风险摘要). A cheap Python collector does the high-frequency tracking.
- ❌ Real automated trading.
- ❌ Any win-rate claim with < 30 independent samples.
- ❌ Intraday fund-flow used in official statistics.
- ❌ Frontend display before the data schema is stable.

---

## 5. Naming — two different "Gate 0"s (do not conflate)

- **DataSources 规范** = the *plumbing* (which source is primary vs fallback). P0.1.
- **Gate 0 全球风险情绪门** = the *brain* (overnight/global → risk state). P2.1.

They are different. Use "DataSources 规范" for the data layer and "Gate 0 全球情绪门"
for the logic gate.

---

## 6. Logic ↔ Scaffold Convergence

The three logic layers designed in the 2026-06-26 session ARE the content that
fills Codex's scaffolds — they are complementary, not two separate efforts.
Scaffolds ship first (basic posture, degrade gracefully); the P2/P3 logic enriches
them later.

| Codex scaffold | Claude logic that fills it |
|---|---|
| `run_post_close_report` (P1.1) | 异动归因层 (P2.2) |
| `run_premarket_monitor` (P1.2) | Gate 0 全球情绪门 (P2.1) |
| `paper_portfolio` (P3.1) | 止损/止盈风控层 (P3.1) |

---

## 7. Build Order (ratified)

1. **Gate 0 DataSources PR** (Codex) ← *do this first; it is the data 地基.*
2. `run_post_close_report.py` (official report + paper PnL).
3. `paper_portfolio.json` / `paper_trade_log.json` (paper entry/stop/take-profit).
4. `run_premarket_monitor.py` (集合竞价 / 开盘30min observation).
5. 全球风险门 + 异动归因 + 止损止盈 logic layers.
6. Frontend panel **last** (experiments → promote to `public/data/execution/` →
   Dashboard reads `latest_report.json`; sections: 今日大盘 · portfolio风险 ·
   paper signals · 胜率/expectancy · 未验证警告 · 数据源状态).

---

## 8. Owners

- **Claude** — production scripts, architecture, strategy docs, gate LOGIC
  (P0.5, P1 logic, P2/P3 logic).
- **Codex** — `experiments/` scaffolding + wiring (P0.1 DataSources, P1/P2/P3
  experiments harness). Writes only to `experiments/` without explicit approval.
- **Junyan** — ratifies each layer before it advances; makes ALL capital decisions.

---

*Outcome target: the model becomes a "daily research + risk-control + paper-trade
evaluation system" that still holds the line — it does not place orders for you,
and it does not claim validated alpha. 不是买卖指令；研究信号，human executes.*
