# Execution Gate Data Sources — Gate 0

> Purpose: lock the data-source hierarchy for Line B execution gates and paper
> signals. This prevents intraday feeds from polluting official win-rate,
> return, MFE/MAE, and expectancy samples.
>
> Core rule: **Tushare is the official close/settlement source and the default
> intraday quote wrapper. Tencent/Sina direct calls are same-feed fallbacks only.**

## 1. Source Hierarchy

| Use case | Allowed source | Sample eligibility |
|---|---|---|
| Official paper samples | **Tushare close/settlement**: `daily`, `moneyflow_dc`, `index_daily`, `moneyflow_mkt_dc` | ✅ Eligible |
| Financials / forecasts / corporate data | **Tushare Pro** | ✅ Eligible if PIT-safe |
| Global indices / northbound | **Tushare Pro** (`index_global`, `moneyflow_hsgt`) | ✅ Eligible for context |
| Intraday price / quote observation | **Tushare SDK** `realtime_quote(src='sina')`, then `get_realtime_quotes`; Tencent/Sina direct calls only as last-resort same-feed fallback | ❌ Not sample-eligible |
| Intraday fund-flow observation | Any realtime fund-flow feed | ❌ Not sample-eligible |
| Manual screenshots / user-entered fund flow | Manual fallback only; source must be explicit | ⚠ Eligible only if close/settlement and source-tagged |

## 2. Official Sample Rule

An official execution-gate sample must satisfy all conditions:

1. It is generated after the market close.
2. Price/OHLC comes from Tushare `daily`.
3. Stock fund flow comes from Tushare `moneyflow_dc`.
4. Market/index state comes from Tushare `index_daily` and `moneyflow_mkt_dc`.
5. Every signal has `official_sample: true`.
6. Every signal has `no_trade_flag: true`.
7. Every signal stores its `data_source`.

If any close/settlement source is unavailable, the correct state is
`DATA_SOURCE_BLOCKED` or `manual_required`, not an invented value.

## 3. Intraday Rule

Intraday feeds are allowed only for risk observation:

- quote direction
- current high/low
- reclaim/support/break watch
- HIGH_REFLEXIVITY warnings
- market/sector watch

Intraday feeds must not create or settle official paper signals.

Default implementation path:

```python
ts.realtime_quote(src="sina")
```

Allowed fallback order:

1. `ts.get_realtime_quotes()`
2. direct Tencent/Sina same-feed quote call
3. `DATA_SOURCE_BLOCKED`

Do not use Tushare SDK realtime quotes as if they were Tushare Pro settlement
data. They are live quote wrappers and remain non-sample-eligible.

### Why this is non-negotiable

On 2026-06-25, 利通电子 provided the failure example:

- Intraday/unstable Eastmoney day-kline probe suggested apparent inflow.
- Official Tushare `moneyflow_dc` close showed **main flow -11.75亿**, with
  small orders absorbing the sell pressure.

That direction flip would have polluted the first official sample if intraday
fund flow had been allowed into the paper log.

## 4. Implementation Contract

The official daily runner is:

```bash
source ~/.zprofile
python3 experiments/execution_tracker/run_official_sample.py
```

It must:

- use Tushare HTTPS API only for official sample data;
- write the daily sample under `experiments/execution_tracker/samples/`;
- append to `experiments/execution_tracker/paper_signal_log.json`;
- never write to `public/data`;
- never emit buy/sell instructions.

For intraday observation helpers, use Tushare SDK realtime quotes first and label
the output `sample_eligible: false`.

## 5. Prompt Contract

When running the TradingView execution gate:

- Say explicitly whether the output is **intraday observation** or
  **official close sample**.
- For intraday observation, do not write paper samples.
- For official samples, use only Tushare close/settlement data.
- If a user asks for “real-time”, use Tushare SDK `realtime_quote(src="sina")`
  first, and label it non-sample-eligible.

## 6. Current Validation Status

Validated:

- Tushare `daily`
- Tushare `moneyflow_dc`
- Tushare `index_daily`
- Tushare `moneyflow_mkt_dc`
- Tushare SDK `realtime_quote(src='sina')` for intraday quote observation

Still unvalidated for official execution-gate expansion:

- market-wide sector/industry flow details
- SMC-specific intraday structure extraction
- signal expectancy before 30 independent official samples
