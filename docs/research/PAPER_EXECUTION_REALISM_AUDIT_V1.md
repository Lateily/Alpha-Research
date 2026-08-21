# Paper Execution Realism Audit v1

Status: `PASS_WORKFLOW_DEBUG / METHOD_CLAIM_BLOCKED`

This audit defines the maximum honest use of the first semiconductor
prospective paper cycles. They may debug state transitions, evidence binding,
attribution, and operational review. They are not part of the 30 independent
method samples and cannot support win-rate, alpha, profitability, or portfolio
promotion claims.

## Findings Before The Fix

The inherited daily-bar engine already prevented registration-day fills,
penalized adverse gaps, and resolved later same-bar stop/target ambiguity
conservatively. It still had six load-bearing realism gaps:

1. It scanned exits on the fill date, allowing an A-share cash-equity purchase
   and sale on the same day.
2. It compared prospectively registered raw levels with forward-adjusted bars.
3. It treated a one-price limit-up as an available buy and a one-price
   limit-down as an available stop exit.
4. It had no settled-volume participation bound.
5. It could chase any gap above the registered entry trigger.
6. Cash and P&L were gross of commission, transfer fee, stamp duty, and
   slippage.

Any one of these can make a paper result look better or more executable than
the evidence permits. They were blockers for the first cycle batch.

## v1 Execution Contract

Every workflow-debug execution bar is exact and carries:

- raw, unadjusted settled OHLC;
- previous close and official up/down limits;
- normalized volume in shares and amount in CNY;
- explicit suspension, settlement, source, and price-basis facts.

The fill engine then enforces:

- registration on T, earliest buy fill after T;
- no sell on the buy-fill date;
- no fill on a one-price limit-up and no exit on a one-price limit-down;
- order size at or below 1% of settled daily share volume;
- no fill above the prospectively registered SMC entry-zone high;
- adverse entry/stop slippage and a declared cost proxy;
- STAR quantity minimum of 200 shares, with one-share increments thereafter;
- later same-bar stop/target ambiguity resolves to stop.

The cost proxy uses 0.03% broker commission with a CNY 5 minimum, 0.001%
transfer fee on both sides, 0.05% sell-side stamp duty, and 5 bps adverse
slippage. Stamp duty and exchange/transfer references are based on the current
official notices from the tax authority and the Shanghai/Shenzhen exchanges.
The broker commission and slippage assumptions are not bound to Junyan's actual
broker statement and therefore remain `PROXY_UNVERIFIED`.

Primary references:

- https://shanghai.chinatax.gov.cn/zcfw/zcfgk/yhs/202308/t468451.html
- https://one.sse.com.cn/onething/gptz/
- https://www.szse.cn/marketServices/deal/payFees/index.html
- https://www.sse.com.cn/lawandrules/sselawsrules2025/fund/trading/c/c_20260424_10817739.shtml

## Residuals

The receipt must preserve all five residuals:

- `DAILY_OHLC_HAS_NO_INTRADAY_SEQUENCE`
- `BROKER_COMMISSION_SCHEDULE_NOT_BOUND_TO_STATEMENT`
- `NO_QUEUE_POSITION_MODEL_AT_PRICE_LIMIT`
- `TARGET_TOUCH_ASSUMES_FULL_FILL_AT_REGISTERED_LEVEL`
- `NO_PARTIAL_FILL_MODEL`

These residuals are why the receipt says `PASS_WORKFLOW_DEBUG` instead of
`REALISTIC_EXECUTION_VALIDATED`.

## Sample Policy

The first 5–10 semiconductor cycles must carry:

- `sample_eligible=false`;
- `method_claim_sample_eligible=false`;
- `portfolio_promotion_eligible=false`;
- `no_trade_flag=true`.

Their purpose is to expose workflow and attribution failures. The later
30-sample gate starts only after a separate approval binds actual broker costs,
confirms independence and de-clustering, and registers which execution model
version is eligible.

不是买卖指令；研究信号，human executes.
