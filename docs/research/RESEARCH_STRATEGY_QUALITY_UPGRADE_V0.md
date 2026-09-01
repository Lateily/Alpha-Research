# Research Strategy Quality Upgrade v0

Status: `DRAFT_OFFLINE_QUALITY_PLAN / RESEARCH_ONLY / PRODUCTION_UNWIRED`

This document translates the research-quality goal into an operator plan. It
does not run a screen, select securities, create paper orders, or claim a
tradable strategy.

Not trading advice; research signal, human executes.

## Purpose

The project needs better research precision before it needs more UI. Precision
here means:

- the universe is broad enough to avoid hand-picked winners;
- the fundamental screen explains why a name enters or exits;
- timing is registered before outcomes;
- backtests cannot see the future;
- every accepted, rejected, blocked, and control sample remains countable;
- paper P&L cannot rewrite whether the thesis, valuation, timing, or execution
  was correct.

The goal is a better research production line, not an automatic stock picker.

## Position In The Full Loop

```text
U0 eligible all-A universe
  -> fundamental threshold profile
  -> U1 independent channels
  -> U2 candidate pool with A/B/C/D buckets
  -> U3 six-dimension battery
  -> U4 Junyan decision
  -> thesis / valuation / wrong-if
  -> manual SMC timing ticket
  -> prospective paper registration
  -> paper execution under A-share constraints
  -> T+1/T+3/T+5/T+10 observation
  -> five-axis attribution
  -> method keep / revise / kill
```

The machine can prepare evidence, counters, hashes, diagnostics, and scorecards.
Junyan remains the only U4 and real-capital decision authority.

## Stage 1: Fundamental Precision

The fundamental screen must answer:

```text
Why is this company worth continued research, and what would remove it?
```

It must not answer:

```text
Should we buy this company today?
```

Required outputs:

| Output | Why it improves quality |
|---|---|
| `threshold_profile_ref` | prevents hidden threshold changes after seeing price action |
| `why_in` | forces the machine to name the actual evidence |
| `why_out` | preserves rejected and weak samples |
| `missing_evidence` | prevents missing data from becoming a silent zero |
| `method_version` | keeps future attribution tied to the method actually used |
| `cohort_id` | keeps the denominator visible |
| `causal_cluster_id` | prevents counting one event cluster as many independent samples |

Thresholds are explicit research assumptions. The first approved threshold
profile should be treated as a research hypothesis. It is allowed to be wrong.
It is not allowed to mutate silently.

## Stage 2: Candidate Buckets

Do not let the screen collapse to only a few obvious names. Every run should
keep four buckets:

| Bucket | Meaning | Next step |
|---|---|---|
| `A_FUNDAMENTAL_PASS_TIMING_NEAR` | fundamentals worth study and timing may be close | U3 and U4 review if no blockers |
| `B_FUNDAMENTAL_PASS_TIMING_WAIT` | fundamentals worth study but timing is not ready | watch and revisit |
| `C_REPAIR_OR_REVERSAL_WATCH` | possible repair, contradiction, or turnaround | evidence follow-up |
| `D_CONTROL_OR_DENOMINATOR` | random/control or rejected denominator rows | later information-value testing |

This keeps value research alive while still giving the team enough samples to
learn from.

## Stage 3: Timing Discipline

Manual SMC timing must answer:

```text
Is this a disciplined paper-timing window, or should we wait?
```

Required timing fields:

| Field | Meaning |
|---|---|
| `timing_method_version` | stable SMC rule version |
| `evidence_as_of` | settled evidence cutoff |
| `higher_timeframe_structure` | broad structure before entry |
| `setup_type` | sweep reclaim, BOS retest, CHOCH reclaim, or none |
| `poi_zone` | planned area, not after-the-fact entry explanation |
| `range_location` | discount, equilibrium, premium, or unknown |
| `volume_state` | whether volume confirms |
| `flow_state` | settled flow confirmation or `DATA_BLOCKED` |
| `sector_state` | industry confirmation or `DATA_BLOCKED` |
| `entry_zone` | planned review zone |
| `structure_invalidation` | technical invalidation before the outcome |
| `structure_stop` | paper stop reference, never loosened intraday |
| `target_1` / `target_2` | planned references, not proof of value |
| `wait_reason` | required when timing is not ready |

Timing can only say `PASS`, `WAIT`, or `DATA_BLOCKED`. A strong fundamental case
with weak timing remains `WAIT`.

## Stage 4: Backtest Hygiene

Backtests must measure whether a rule had information before the outcome. They
must not produce a pretty number by leaking the future.

Minimum backtest hygiene:

| Rule | Required behavior |
|---|---|
| Point-in-time sources | use only data available at the decision timestamp |
| Corporate actions | preserve adjusted and raw price lineage |
| A-share constraints | model T+1, price limits, lot size, costs, slippage, and volume participation |
| Same-day leakage | no same-day fill from a registration made after the bar |
| Controls | compare against random/control rows and non-pass cohorts |
| Denominator | include accepted, rejected, deferred, no-trade, blocked, and control rows |
| Sample independence | count by causal cluster, not raw ticker occurrences |
| Overfit check | report parameter count, sample count, turnover, and cost sensitivity |

If a backtest cannot prove these conditions, its result is `DATA_BLOCKED`, not
strategy evidence.

## Stage 5: Five-Axis Learning

Each closed paper cycle must be attributed on five separate axes:

| Axis | Question |
|---|---|
| Thesis | Did the registered business thesis happen? |
| Valuation | Did the valuation assumptions land inside the registered range? |
| Timing | Did the SMC/timing setup work as registered? |
| Execution | Did the paper engine fill/exit under realistic constraints? |
| Market beta | How much of the result came from market or industry movement? |

P&L is recorded, but it cannot rewrite any axis. This is how the team learns
whether the method is improving instead of simply celebrating winning trades.

## Sample And Claim Gate

Method quality is counted by independent causal clusters, not raw ticker rows.
The same issuer event, restatement, catalyst chain, or supply-chain shock cannot
be counted many times just because it appears in multiple securities or dates.

Counting rules:

| Rule | Meaning |
|---|---|
| Count by `causal_cluster_id` | One cluster counts once, even if it contains many rows. |
| Keep the full denominator | `SELECT`, `REJECT`, `DEFER`, `NO_TRADE`, `DATA_BLOCKED`, and controls stay visible. |
| Exclude workflow-debug cycles | The first 5-10 semiconductor cycles test the process and do not count toward the 30-cluster method threshold. |
| Exclude blocked rows from success claims | `DATA_BLOCKED` and `NO_TRADE` rows stay in the denominator but cannot be called method wins. |
| Require cross-industry replication | A method that only works in one industry cannot move to portfolio construction. |

Before at least 30 independent closed causal clusters and cross-industry
replication, the only allowed claims are:

```text
workflow_debug_observation
process_quality_issue
data_gap_report
```

Blocked claims before that threshold:

```text
alpha_claim
profitability_claim
method_validity_claim
portfolio_promotion_claim
```

If a report tries to make one of those blocked claims early, the result is
`METHOD_CLAIM_BELOW_30_INDEPENDENT_CLUSTERS`.

## Pre-Registration Failure Modes

Paper registration review must fail before any plan is treated as usable when:

| Failure mode | Meaning |
|---|---|
| `THESIS_NOT_SEALED` | The business thesis is missing or mutable. |
| `VALUATION_RANGE_NOT_SEALED` | Bear/base/bull valuation is missing or mutable. |
| `WRONG_IF_NOT_SEALED` | The invalidation condition is missing or mutable. |
| `TIMING_TICKET_NOT_PRE_OUTCOME` | Timing evidence was written after the outcome window began. |
| `MANUAL_SMC_STATUS_NOT_PASS` | SMC timing is `WAIT`, `DATA_BLOCKED`, or otherwise not pass. |
| `ACTIVE_E1_RED_FLAG` | A red flag is active and cannot be offset. |
| `SOURCE_DATA_BLOCKED` | Required evidence is missing, stale, or unverifiable. |
| `U4_SELECT_MISSING_OR_UNTRUSTED` | Junyan has not issued a trusted U4 `SELECT`. |
| `PLAN_HASH_UNBOUND` | The paper plan is not bound by a stable full hash. |
| `AUTHORITY_ESCALATION` | The artifact claims production, paper-order, or trade authority. |

## Near-Term Work Order

1. Keep #325 as the research go/no-go and fundamental-screening contract.
2. Add a Junyan-approved threshold profile before any full-market screen claims
   to be "using the method".
3. Add a timing-ticket intake template before any paper registration plan is
   reviewed.
4. Add a backtest hygiene checklist before publishing any win-rate, alpha, or
   strategy result.
5. Run the first 5-10 semiconductor cycles as workflow-debug only.
6. Exclude those workflow-debug cycles from the 30-cluster method denominator.
7. Wait for at least 30 independent, de-clustered closed samples before method
   claims.

## Stop Conditions

Stop and report instead of continuing when:

- a threshold profile has no approval reference;
- a data field is missing but treated as zero or neutral;
- E1 red flags are offset by positive fundamentals or timing;
- timing evidence is registered after the price outcome;
- selected and rejected samples are not both retained;
- a method claim is made below 30 independent closed causal clusters;
- a one-name or two-name review pool is forced into U4 selection;
- paper P&L is used to claim thesis quality;
- a result claims production, trade, paper-order, alpha, or profitability
  authority.

## What This Unlocks

If this plan is followed, Reed and Junyan can improve the system in the right
order:

```text
better evidence intake
  -> better candidate quality
  -> better timing discipline
  -> cleaner paper records
  -> more useful attribution
  -> safer strategy iteration
```

The next product value is not a prettier page. It is a research engine that can
explain why it stopped, why it advanced, and what it learned.

Not trading advice; research signal, human executes.
