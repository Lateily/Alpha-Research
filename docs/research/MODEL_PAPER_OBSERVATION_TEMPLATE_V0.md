# Model Paper Observation Template v0

Status: `DRAFT_OFFLINE_OBSERVATION_TEMPLATE / PAPER_ONLY / PRODUCTION_UNWIRED`

This template defines how Reed records the first semiconductor model paper
fund observations after Junyan has made a U4 decision and a paper registration
plan has passed the approved bridge. It is an observation and learning sheet,
not a stock recommendation, not an order router, and not a proof that the
method works.

Not trading advice; research signal, human executes.

## Purpose

The model paper fund needs one boring habit before it needs more automation:
each paper case must be watched the same way after registration. The template
keeps the team from changing the meaning of a result after seeing the price
path.

It records:

- what was known before the paper registration;
- whether a fill was realistic under A-share constraints;
- what happened at T+1, T+3, T+5, and T+10;
- whether thesis, valuation, timing, execution, or market beta explains the
  result;
- whether any missing data, stale source, or corporate-action break blocks the
  observation.

The first 5-10 semiconductor cycles remain `WORKFLOW_DEBUG_ONLY`. They may
debug the workflow, but they do not count toward method validity, alpha,
profitability, or portfolio-promotion claims.

## When This Template Can Be Used

All of the following must be true before a row can be opened:

| Gate | Required evidence | If missing |
|---|---|---|
| U4 decision | Junyan-authored `SELECT` in the U4 decision ledger | `STOP_BEFORE_OBSERVATION` |
| Sealed case | thesis, valuation range, wrong-if, manual SMC, causal cluster | `STOP_BEFORE_OBSERVATION` |
| Paper plan | reviewed plan hash and paper-only authority block | `STOP_BEFORE_OBSERVATION` |
| Execution model | `a-share-daily-realism-v1` or later approved paper-only model | `DATA_BLOCKED` |
| Data source | settled daily bars, raw price basis, source date, no corporate-action break | `DATA_BLOCKED` |

This template cannot create a paper order. It only observes an already
registered paper plan.

## Case Header

Every observed case must carry:

```text
MODEL_PAPER_OBSERVATION_V0
CASE_ID:
TICKER:
NAME:
TARGET_TRADE_DATE:
U4_DECISION_REF:
U4_DECISION_HASH:
SEALED_CASE_HASH:
PAPER_REGISTRATION_PLAN_HASH:
PAPER_ORDER_REF:
METHOD_VERSION:
COHORT_ID:
CAUSAL_CLUSTER_ID:
SAMPLE_PURPOSE: WORKFLOW_DEBUG_ONLY
SAMPLE_ELIGIBLE: false
METHOD_CLAIM_SAMPLE_ELIGIBLE: false
PORTFOLIO_PROMOTION_ELIGIBLE: false
NO_TRADE_FLAG: true
TRADE_AUTHORITY: false
PAPER_ORDER_AUTHORITY: false
```

## Daily Observation Row

Use one row per target horizon.

| Field | Meaning |
|---|---|
| `horizon` | One of `T_PLUS_1`, `T_PLUS_3`, `T_PLUS_5`, `T_PLUS_10` |
| `observation_date` | Actual settled bar date used for the horizon |
| `settled_bar_ref` | Path or artifact id for the raw settled bar source |
| `bar_hash` | Hash of the bar data used for this mark |
| `mark_price` | Settled close or explicit `DATA_BLOCKED` |
| `entry_reference` | Registered entry reference, never edited after outcome |
| `paper_return_pct` | Paper-only return from the registered plan, if computable |
| `relative_industry_return_pct` | Optional industry-relative return; if absent, mark `DATA_BLOCKED` |
| `thesis_axis_status` | `PASS`, `FAIL`, `MIXED`, `WAIT`, or `DATA_BLOCKED` |
| `valuation_axis_status` | Same five states, separate from P&L |
| `timing_axis_status` | Same five states, separate from thesis |
| `execution_axis_status` | Same five states, based on fill realism |
| `market_beta_axis_status` | Same five states, based on market/industry context |
| `source_status` | `COMPLETE`, `PARTIAL`, `STALE_INPUT`, or `DATA_BLOCKED` |
| `observation_status` | `OBSERVE`, `DATA_BLOCKED`, `EXIT_REVIEW`, `STOPPED`, or `CLOSED` |
| `operator_note` | Short factual note; no buy/sell/hold instruction |

P&L is recorded, but it cannot rewrite any axis. A profitable row can still
have a failed thesis or bad timing. A losing row can still have a correct thesis
and bad execution.

## Intraday Notes

Intraday watching is allowed only as a note stream. It may record market
structure, volume behavior, red-flag news, and SMC changes. It cannot create a
fill, official sample, official return, or method claim.

Allowed intraday note fields:

```text
NOTE_TIME:
SOURCE:
OBSERVED_FACT:
SMC_STRUCTURE_NOTE:
RISK_OR_RED_FLAG_NOTE:
FOLLOW_UP_NEEDED:
NO_TRADE_FLAG: true
```

## Stop Conditions

Stop and report instead of filling an observation when:

- the U4 decision is missing or not Junyan-authored;
- the paper plan hash is missing or does not match the reviewed plan;
- settled bars are missing, intraday-only, adjusted, stale, or not hash-bound;
- the entry, stop, target, or no-chase ceiling changed after registration;
- a corporate-action break appears and no manual re-registration exists;
- a note tries to loosen a stop after the outcome;
- P&L is used to relabel thesis, valuation, timing, or execution;
- any field grants production, trading, paper-order, or selection authority.

## Relationship To Go-Live

Before #319 and the go-live runbook are both on `main`, this template remains a
preparation artifact. It can make tomorrow's work faster, but it cannot bypass
registration, Junyan review, or the paper-only launch gate.

The correct launch sequence remains:

```text
U4 SELECT
-> sealed case
-> paper registration plan review
-> paper-only pending order
-> settled bar observation
-> T+1/T+3/T+5/T+10 rows
-> five-axis attribution
-> method keep/revise/kill only after enough independent samples
```

Not trading advice; research signal, human executes.
