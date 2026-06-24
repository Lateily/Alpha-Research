# Execution Tracker — P1 (experiments, read-only)

Line B of the AR Weekly Trading Factory. A **read-only** execution-gate collector +
paper-signal logger. It does **not** trade, does **not** touch production scripts or
`public/data`, and emits no buy/sell — only risk posture + paper signals. Human executes.

> All thresholds are `[unvalidated intuition]` until ≥ 30 independent paper signals
> accumulate. No win-rate / expectancy claim before then.

## Why it takes input instead of fetching

The two data sources can't both be reached by a standalone script:
- **TradingView** (price + MA/ATR/levels) is **MCP-only** → the agent pulls it
  (`tv_launch` → per-symbol `chart_set_symbol` → `quote_get` + `data_get_ohlcv`; the
  delayed `_DLY` daily bars are fine for levels).
- **主力净流 / 超大单 / 小单** are **东财-only** → Junyan feeds them.

So the agent/human assembles an input JSON and passes it in; the script is the
deterministic **gate logic + schema + evaluator**.

## Input shape (`--input snapshot_input.json`)

```json
{
  "timestamp": "2026-06-24T12:56:00+08:00",
  "index_data": {
    "sh":  {"chg": -0.25, "main_flow": -7.26},
    "sz":  {"chg":  0.33, "main_flow": -8.48},
    "cyb": {"chg":  0.42, "main_flow": -4.39}
  },
  "portfolio": ["603629.SH", "300475.SZ", "300308.SZ", "300502.SZ"],
  "tickers": [
    {"ticker": "603629.SH", "name": "利通电子", "sector": "AI/光模块",
     "price": 214.0, "change_pct": 5.98, "main_flow": -1.01, "super_large": -4.11,
     "small": 1.09, "ohlc_bars": [{"high": .., "low": .., "close": ..}, ...]}
  ]
}
```
`ohlc_bars` = oldest→newest daily {high,low,close} (≥20 for MA20, ≥120 for MA120).

## The 7 gates (mirrors the skill)

1. **市场门** `classify_market` → `RISK_ON / WEAK_REPAIR / RISK_OFF / STYLE_ROTATION`
2. **板块门** single-beta check over held sectors (个股反抽 ≠ 板块修复)
3. **资金门** `classify_fund_structure` → `主力回流 / 涨着派发 / 跌中承接 / 大单卖小单接 / 无量修复`
4. **技术门** `compute_technicals` → MA20/60/120, ATR14, 今/昨高低, 20日高低, 承接/破坏/上攻位
5. **执行门** `execution_posture` → `RECLAIM_REVIEW / HOLD_OBSERVE / WARNING / DE_RISK_REVIEW / EXIT_REVIEW / NO_CHASE`
6. **组合门** single-beta → portfolio `DE_RISK_REVIEW`
7. **自审** flags baked into the snapshot

## Usage

```bash
python3 execution_tracker.py --selftest                       # 15 checks, reproduces today's 4-holding read
python3 execution_tracker.py --input in.json --log paper_signal_log.json
python3 execution_tracker.py --evaluate paper_signal_log.json --prices later.json
```

Outputs (written next to `--log`, never to `public/data`):
- `execution_gate_snapshot.json` — the 7-gate snapshot
- `paper_signal_log.json` — append-only, deterministic `signal_id`, `no_trade_flag: true`

## Evaluator

Given forward returns per `signal_id` (`{t1,t3,t5,t10}`), aggregates hit-rate /
avg-return / win-loss / expectancy, sliced by `setup_type` and `market_state`.
Answers: does `RECLAIM_REVIEW` lead to positive forward returns? does `WARNING`
catch failed breakouts? does `DE_RISK_REVIEW` cut drawdown? It **refuses to claim**
below 30 signals.

## Validated against today (selftest)

利通 → WARNING (涨着派发) · 香农 → HOLD_OBSERVE (大单卖小单接) · 中际 → HOLD_OBSERVE
(无量修复) · 新易盛 → relative_strength (主力回流) · 组合 → DE_RISK_REVIEW (单一 beta) ·
market → WEAK_REPAIR. Matches Junyan's 12:56 manual read.

## Boundaries (P1)

No daemon, no auto-fetch, no public/data write, no front-end, no real orders.
Next (P2): wire a polling loop + forward-price backfill; only after paper signals
prove positive expectancy does anything graduate to `public/data` + a panel.
