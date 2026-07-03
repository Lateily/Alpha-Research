# Model Paper Fund — Policy v0 (P6.0)

> **What this is.** A ¥1,000,000 VIRTUAL account managed by the model's own research
> (Research Decision Pack + Execution Gate + Nowcast/post-close signals), run as an
> auditable paper ledger and compared daily against Junyan's human+AI account.
> **What this is not:** real trading. No real buy/sell instruction ever; every order
> is a pre-registered PAPER order (`no_trade_flag: true`). The point is to measure
> whether the model's research has positive expectancy — 目标是数它,不是信它.
>
> Status of every threshold below: **[unvalidated intuition]** until calibrated.

## 1. Account

| Item | Value |
|---|---|
| Initial capital | ¥1,000,000 (virtual) |
| Instruments | A-share equities, long-only v0, 100-share lots |
| Ledger | `experiments/execution_tracker/model_fund/` (append-only JSON) |
| Engine | fills/exits via `paper_portfolio.py` mechanics (registered→T+1 fill→stop/target) |

## 2. Portfolio construction rules (v0, conservative)

| Rule | v0 value |
|---|---|
| Max single-name notional | **15% of NAV** |
| Max single-theme notional | **40% of NAV** (theme = declared per order: 光模块/存储/黄金/电力/医药/...) |
| Max simultaneous positions (pending+filled) | **5** |
| Per-trade risk budget | **0.5%–1.0% of NAV** (risk = entry − stop) |
| Min cash floor | **20% of NAV** (an order that would breach it is refused) |
| Adds | only if the existing paper trade is in profit AND a fresh signal confirms |
| No-chase | no new order on a name whose gate is `NO_CHASE` or nowcast `FAKE_STRENGTH` |
| Exits | stop_reference / wrong-if trigger / `EXIT_REVIEW` posture / R-multiple target |

**Sizing:** `shares = floor(risk_budget_cny / (entry − stop) / 100) × 100`, then
notional capped by the single-name limit, then re-checked against theme cap and
cash floor. If any constraint refuses the order, the refusal + reason is logged —
a refused order is itself a decision-log entry.

## 3. Execution rules (no-lookahead, inherited from paper_portfolio)

1. Every order **pre-registered with timestamp BEFORE the trigger** — no retro-edits
   of entry/stop/target, ever.
2. **No fill on registration day**; earliest fill T+1, only when the settled bar
   actually crosses the entry.
3. **Gaps fill worse**: gap-up through entry fills at open; gap-down through stop
   exits at open; target exits capped at target.
4. Same-bar stop+target → **stop wins** (conservative).
5. Marks/fills/exits use **settled Tushare bars only** (定盘). Intraday is
   observation/nowcast, never a fill source.

## 4. Posture → allowed fund action

| Gate / nowcast state | Allowed action |
|---|---|
| NO_CHASE / FAKE_STRENGTH | no new order on that name |
| HOLD_OBSERVE | hold; no add |
| WARNING / DISTRIBUTION_PROBABLE | risk review; tighten stop_reference allowed (only TIGHTER, never looser) |
| RECLAIM_REVIEW / RECLAIM_ATTEMPT | may register a new order (pending, T+1 rules) |
| DE_RISK_REVIEW | reduce review — model must state trim plan in decision log |
| EXIT_REVIEW | exit review — model must state exit plan in decision log |

Stops may be moved **tighter only** (trailing); loosening a stop is forbidden
(that is how paper accounts lie to themselves).

## 5. Daily cycle & broadcast contract (what Junyan sees, and when)

- **盘前 (~09:00):** market state + portfolio risk + today's pending orders +
  any NEW registrations, each with reasoning (variant view / catalyst / risk) —
  the model may also declare "今天不动,因为…" (a no-trade day is a decision).
- **盘中 (checkpoints):** nowcast states + paper risk reviews only. No fills, no
  official samples from intraday data.
- **盘后 (settle):** fills/exits processed from settled bars → NAV update →
  daily report: 今日动作 + reasoning · 持仓 PnL · NAV/收益率 · 风险暴露 ·
  昨日判断判分 · vs human+AI account · 明日观察点.
- LLM runs at fixed checkpoints only (no 24h resident loop, per constitution).

## 6. Scoring & comparison

- Per closed trade: paper_return, realized_R, holding days, exit reason.
- Fund: NAV curve, daily/cumulative return, max drawdown, win rate, avg R,
  expectancy, turnover, AI-beta exposure.
- **No win-rate / expectancy / alpha claim below 30 closed trades**
  (`claim_allowed=false` until then).
- **Human+AI shadow:** Junyan logs his account's daily NAV (manual JSON v0);
  weekly comparison = total return · max DD · win rate · expectancy · avg R ·
  turnover · hit-rate by setup · missed winners · avoided losers. The goal is not
  who wins a week — it is WHERE each side is stronger (market state, setup type,
  discretion vs discipline).

## 7. Forbidden

- Real buy/sell instructions, real order routing, real capital of any kind.
- Retro-editing entries/stops/targets; loosening stops; filling from intraday prices.
- Claiming validated alpha (< 30 closed trades, and even after — claims follow the
  bidirectional honesty rules).

**不是买卖指令；研究信号，human executes。**
