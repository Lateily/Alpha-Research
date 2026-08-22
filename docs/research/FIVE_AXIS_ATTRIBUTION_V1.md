# Five-Axis Paper-Cycle Attribution v1

## Purpose

This offline layer answers five different questions after one prospective paper
cycle closes:

1. **Thesis**: did the prospectively registered factual expectations occur?
2. **Valuation**: did the registered forecast variables land inside their
   declared ranges?
3. **Timing**: did the registered entry structure reach its target or
   invalidation, and what were MFE/MAE in registered risk units?
4. **Execution**: did the replay preserve registered levels, and is there a
   bound execution-realism receipt for the exact paper order?
5. **Market beta**: how much of gross paper return is mechanically associated
   with a point-in-time beta estimate and the same-window market move?

The five axes remain independent. There is no composite score and P&L cannot
rewrite any method verdict.

## Position In The Workflow

```text
verified prospective cycle bundle
  + method scorecard
  + bound execution-realism receipt
  + same-window market and industry evidence
  + pre-registered beta sample window
        |
        v
ar.paper_cycle_five_axis_attribution.v1.0
```

The module replays `research_cycle.verify_cycle_bundle()` before reading any
axis. It accepts only a `REVIEW_READY` cycle with exactly one closed paper
order. Open, unfilled, rejected, or no-trade cases remain in their existing
cycle records and do not receive a terminal five-axis receipt.

## Evidence Contracts

### Market Evidence

`ar.paper_cycle_market_evidence.v1.0` is bound to:

- the exact research-cycle ID and immutable bundle hash;
- the exact registration hash;
- the hash of the closed paper order;
- the order's actual fill date, exit date, fill price, exit price, and net
  paper return.

Market and industry price legs must cover the exact fill-to-exit dates. A
complete leg requires positive settled prices, an E1/E2 evidence grade, a
source reference, and an evidence hash. Missing legs carry no prices and must
state explicit `reason_codes`.

### Point-In-Time Beta

A complete beta estimate carries at least 60 unique, ordered daily return
observations. The lookback ends no later than the registered method's as-of
date. The beta evidence cannot be registered before its final sample or after
the method's as-of date. The samples are bound to the cycle ticker and
registered benchmark. The module recomputes OLS beta from the frozen asset and
benchmark return samples and rejects a declared beta that differs from the
recomputed value. Existing method registration timestamps have trading-day
precision, so this contract does not claim to prove ordering between two events
inside the same day.

The beta evidence is still an offline, evidence-bound diagnostic. Source
identity is not independently authenticated by this contract, so the sealed
market evidence fixes `identity_verification=UNAVAILABLE`.

### Execution Evidence

`ar.paper_cycle_execution_evidence.v1.0` freezes the full
`ar.paper_execution_realism_receipt.v1.0`, hashes it, and binds the wrapper to
the exact cycle and order. The wrapper does not accept a caller-authored list of
passed checks. It also does not authenticate the producer of that source
receipt, so the sealed wrapper fixes `identity_verification=UNAVAILABLE`.

The only accepted positive state in v1 is `PASS_WORKFLOW_DEBUG`. It remains
ineligible for method claims and portfolio promotion. If the source receipt is
missing, blocked, unbound, or internally inconsistent, the execution axis is
`DATA_BLOCKED`.

## Market-Beta Math

For the closed paper order:

```text
gross_stock_return       = exit_price / fill_price - 1
market_return            = market_end_close / market_start_close - 1
industry_return          = industry_end_close / industry_start_close - 1
market_beta_contribution = registered_beta * market_return
beta_residual_return     = gross_stock_return - market_beta_contribution
market_excess_return     = gross_stock_return - market_return
industry_excess_return   = gross_stock_return - industry_return
```

The benchmark and industry legs use settled closes on the fill and exit dates,
while the stock return starts at the modeled fill. That basis difference is a
known diagnostic limitation.

`beta_residual_return`, `market_excess_return`, and `industry_excess_return`
are **not alpha**. They are one-cycle diagnostics without statistical
significance, transaction-model completeness, or causal identification.

## Status Rules

- Missing market, industry, beta, or execution evidence remains
  `DATA_BLOCKED`.
- Prospectively unresolved thesis, valuation, or timing remains `UNRESOLVED`.
- A method miss remains visible even when paper P&L is positive.
- A complete first-wave receipt is `WORKFLOW_DEBUG_COMPLETE`, not a valid
  method sample.
- Every v1 receipt has `sample_purpose=WORKFLOW_DEBUG`,
  `method_sample_eligible=false`, `claim_allowed=false`,
  `production_authority=false`, and `no_trade_flag=true`.

The first 5-10 semiconductor cycles exercise the workflow and attribution
boundaries only. They do not enter the 30-independent-cluster method gate.

## Honest Boundary

This PR does not fetch market data, estimate beta from production data, write a
production ledger, select U4 names, create paper orders, or change the nightly
chain. A later producer may generate the two evidence contracts, but it must
preserve these same point-in-time and binding rules.

不是买卖指令；研究信号，human executes.
