# Xiaohongshu Inspiration Layer (7 posts, 2026-05-26)

_The user shared 7 XHS posts as inspiration — NOT for forced adoption.
Synthesized 2026-05-26 by reading via Claude in Chrome + image OCR._

## Per-post extraction

### 1. 个人量化+OpenClaw+因子动态更新 — Keleve

**Architecture**: 7-Tier Workflow (US-stock + HK-stock, intraday/short-horizon).
Key designs:
- Multi-trigger exit factors (5 independent):
  - `stop_if_drawdown_exceeds`: 15%
  - `stop_if_daily_loss_exceeds`: 8%
  - `stop_if_behind_target_by`: 10%
  - `max_consecutive_losses`: 3
  - `max_position_holding_days`: 7
- Macro regime multipliers (low/normal/high vol → 0.6 / 1.0 / 0.6 position cap)
- Leverage controls (`max_leverage`, `margin_multiplier=3`, `margin_lower_bound=50%`)
- Correlation-grouped factor clusters (AI semis / AI growth / meme / China tech)
- Self-Learning iteration loop ("认知进化")
- OpenClaw automated execution + dry-run testing mode
- "Champion learning curve replication" — distill from top performers

**Transferable to us** (honest):
- **HIGH**: multi-trigger exit factorization (we have only 1 DD breaker)
- **MEDIUM**: dry-run mode as engineering hygiene
- **MEDIUM**: regime multiplier finer granularity
- **LOW**: factor specifics + leverage (US-stock specific, intraday)
- **NO**: specific tickers / margin configuration

### 2. 高盛的顶级投研框架,被我做成 skill 了

**Content**: Real Goldman Sachs Global Investment Research charts (Exhibit 2:
oil & gasoline 1970s vs 2021-22 vs current; Exhibit 3: supply disruptions
comparison). **Framework signature** (what the poster turned into an AI skill):
- **Multi-decade historical comparison** (1970s ↔ 2021-22 ↔ current)
- **Multi-source data triangulation** (Commerce Dept + Energy Dept)
- **Comparative side-by-side panels** in every Exhibit
- **Explicit Source: line** at the bottom (forensic-trail discipline)
- **Narrative title** that frames the comparison (not just "GDP chart")

Poster's method: "feed cherished research reports to AI, extract framework or
modeling method, combine with your own thesis material, create a skill in
Alice". The methodology lives in the **structure**, not the specific factor
formulas.

**Transferable** (this is what Junyan explicitly asked for):
- **HIGH**: adopt GS-style chart structure for CORE track research output
  (multi-period comparison + multi-source + narrative title)
- **HIGH**: this is the **agent skill pattern** for our LLM thesis engine
- **MEDIUM**: forensic source-trail discipline (already partially in our
  citation-grading rule from 2026-05-15)

### 3. 研报复现-华泰证券-高频特征分钟级因子挖掘

**Content**: Multi-objective genetic algorithm (NSGA-II) for high-frequency
factor mining. Uses Das-Dennis method for Pareto reference points + non-dominated
sorting (visible in code screenshots).

**Backtest claim**: Total Return 690.83% (2019-2026, ~33% CAGR). Sharpe 2.14
(2019) / 5.07 (2020) / 4.00 (2021) — looks god-tier. But 2023 Sharpe 0.14,
2024 Sharpe -0.28 (58% MaxDD), 2025-2026 recovered.

**Critical bug identified in comments**: `B_shift_lag = [0, 1, -1, 2, -2]` —
the **negative lags (-1, -2) use future data**. Look-ahead bias. The 690% is
contaminated.

**Vindication** (this is the MOST IMPORTANT lesson):
- **Our PIT firewall (PitDataStore) prevents exactly this bug class** by
  design. The `B_shift_lag` pattern is impossible in our architecture because
  PitDataStore refuses to expose data with `ann_date > as_of_T`.
- The lesson is meta: don't trust headline backtest numbers — **always audit
  for look-ahead BEFORE celebrating**.
- For iter-8: when computing forward returns for IC analysis, make sure
  forward return at month T uses prices AFTER T (close-of-T → close-of-T+1),
  NOT centered or backward.

**Transferable**:
- **MEDIUM**: NSGA-II / multi-objective optimization for factor weight search
  — could replace our OLS (different objective handling)
- **HIGH (meta-lesson)**: re-audit our PIT firewall before crediting iter-8
  results

### 4. VIX>30 抄底真的行吗?我跑了 26 年数据

**Content**: CBOE Volatility Index chart 2023-2026 (current 18.71, 52-wk range
13.38-35.30, 5Y view shows spikes to ~45). Backtest testing the rule "buy when
VIX > 30".

**Comments contain key insight**: "鞋童理论" — when even Japanese housewives /
Korean pension funds / Chinese retail investors all know to buy NASDAQ, it's
the top.

**Transferable to A-share**:
- **MEDIUM**: equivalent VIX = 中证波动率指数 / iVX (300ETF期权 implied vol);
  could add as panic-buy signal in risk overlay
- **MEDIUM**: 鞋童理论 ≈ retail-account-opening growth / 散户入市数月环比 —
  contrarian sentiment indicator. We could implement as factor.
- This validates our existing `risk_monitor` regime detection direction —
  add another regime signal (vol-index) beyond drawdown.

### 5. 让 Codex 写了一个股票基金复盘系统 — H 师傅

**Content**: Operational dashboard built by Codex. Features:
- Watchlist Metrics Board with multiple A-share stocks (银行/快递/etc)
- Session 0.6 Asset Base, 0.8 Dividend Sector Mix, 0.85 Upcoming Dividend Events
- 仓位 / 布林带 / ATR alerts (specifically for 红利股)
- Market direction monitoring (volume, NASDAQ tech, gold, oil)
- Off-market fund distribution + position-reduce alerts

**Transferable**:
- **HIGH**: build a daily operational dashboard for our system — we currently
  output JSON only; missing the human-readable daily view
- **MEDIUM**: 红利股 watchlist + dividend events tracker — fits A-share where
  HDY consistently outperforms (per MSCI 2024 finding in institutional doc)
- **MEDIUM**: Cross-market direction signals (US/HK/Commodities) as
  macro-regime input

### 6. 炒股人终于学会 vibe coding 的终极用法

**Content**: AI 选股 dashboard with A-share stock cards (浙商证券/南京化纤/中信
集团/天风/四川双马/etc), backtest period 04-24 → 04-30, color-coded
recommendations.

**Comments** (this is the value, not the app):
> "胜率五五开,买都买不完"
> "数据是哪里来的?为什么不用同花顺?"
> "像抽签 / 摇骰子"
> "策略展示看起来完整,但实盘和数据来源仍不透明,多数人观望或怀疑"

**This is the warning, not the inspiration.** It's the canonical 散户 vibe-coding
trap: pretty UI + plausible-looking strategy + opaque data + no honest
performance proof.

**Reinforces our discipline**:
- **HIGH (reinforcing)**: our "宁愿犯错也不愿意找不出来错误在哪" + survivorship-safe
  PIT + honest benchmark + honest "no alpha" verdict is exactly the antidote
  to this trap. Iter-1..7 was honest in this way; iter-8 must continue.
- Concrete rule extracted: **never publish an "AI 选股" dashboard without
  bootstrap CI on alpha, IC t-stat, and a multiple-testing correction.**

### 7. 降智无所谓!Claude 还在高强度输出 — 莱纳德陈

**Content**: Cover image "Claude 发布金融 Agent 分析师去往何处" (Claude releases
financial agent, where do analysts go?). Article admires Claude productivity
(1.5 min → working webpage with viz/KPI/interpretation, cost $0.51 tokens).

**Transferable**: nothing factor-actionable. Reinforces that agent-driven
workflow is being normalized in finance. Our T1/T2/T3 architecture is in line.

## Master inspiration ledger

| # | Post | Key insight | Iter-8 action |
|---|------|-------------|---------------|
| 1 | Keleve OpenClaw | Multi-trigger exit factorization (5 independent triggers) | Extend `risk_monitor.py` from 1 DD breaker to 5 exit conditions |
| 2 | 高盛 framework | Multi-decade comparison + multi-source triangulation + narrative titles | Adopt as **CORE thesis output template** (NOT for satellite) |
| 3 | 华泰 NSGA-II | LOOK-AHEAD BUG in B_shift_lag — confirms our PIT firewall is the moat | **Re-audit PIT firewall before crediting iter-8 results** (selftest must include look-ahead test cases) |
| 4 | VIX 抄底 26yr | Equivalent for A-share: iVX (300ETF期权 IV) + retail account growth | Add 2 sentiment regime signals to risk_monitor (optional) |
| 5 | Codex 复盘 H师傅 | Daily operational dashboard with cross-asset/macro panels | Add daily HTML report next to JSON output |
| 6 | vibe coding 散户 | The "UI pretty, data shaky" trap; honest discipline = antidote | Reinforces: no public "AI 选股" deliverable without proper stats |
| 7 | 莱纳德陈 Claude | Agent-driven finance is being normalized | (No direct action — confirms architecture) |

## Most important meta-finding

**The 华泰 NSGA-II case (post 3) is direct empirical vindication of our
2026-05 infrastructure work.** Someone else replicated a Huatai sell-side
report with a sophisticated multi-objective algorithm, got 690% backtest,
published it, and the community found a look-ahead bug in 1 line of code that
invalidates the entire result. Our PitDataStore architecture makes that bug
class impossible. **This is the highest-confidence ROI of all the work since
2026-05-15.**

The corollary: do NOT skip the PIT audit when adding new factors in iter-8.
The temptation to "just compute IC on forward returns" can sneak look-ahead
in via centering/smoothing. Iter-8 must add an explicit look-ahead unit test.
