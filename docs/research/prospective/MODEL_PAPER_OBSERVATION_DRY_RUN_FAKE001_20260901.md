# Model Paper Observation Dry Run - FAKE001.PAPER

Status: `DRY_RUN_ONLY / PAPER_ONLY / PRODUCTION_UNWIRED`

This is a fake operator rehearsal for `MODEL_PAPER_OBSERVATION_V0`. It uses no
real security, no real price, no real U4 decision, and no production data. Its
only purpose is to prove the observation sheet can be filled before the first
real semiconductor paper case appears.

Not trading advice; research signal, human executes.

## Case Header

```text
MODEL_PAPER_OBSERVATION_V0
CASE_ID: DRYRUN_FAKE001_20260901
TICKER: FAKE001.PAPER
NAME: Synthetic Paper Observation Fixture
TARGET_TRADE_DATE: 20260902
U4_DECISION_REF: DRY_RUN_ONLY_NOT_JUNYAN_DECISION
U4_DECISION_HASH: sha256:DRY_RUN_PLACEHOLDER_NOT_A_REAL_HASH
SEALED_CASE_HASH: sha256:DRY_RUN_PLACEHOLDER_NOT_A_REAL_HASH
PAPER_REGISTRATION_PLAN_HASH: sha256:DRY_RUN_PLACEHOLDER_NOT_A_REAL_HASH
PAPER_ORDER_REF: DRY_RUN_PENDING_ORDER_ONLY
METHOD_VERSION: RESEARCH_CLOSED_LOOP_V1_3
COHORT_ID: DRY_RUN_SEMICONDUCTOR_COHORT
CAUSAL_CLUSTER_ID: DRY_RUN_CLUSTER
SAMPLE_PURPOSE: WORKFLOW_DEBUG_ONLY
SAMPLE_ELIGIBLE: false
METHOD_CLAIM_SAMPLE_ELIGIBLE: false
PORTFOLIO_PROMOTION_ELIGIBLE: false
NO_TRADE_FLAG: true
TRADE_AUTHORITY: false
PAPER_ORDER_AUTHORITY: false
```

Because the U4 decision and hashes are dry-run placeholders, this case remains
`STOP_BEFORE_OBSERVATION` for any real workflow. It must never be copied into a
production packet.

## Dry-Run Observation Rows

| horizon | observation_date | settled_bar_ref | bar_hash | source_status | observation_status | operator_note |
|---|---|---|---|---|---|---|
| `T_PLUS_1` | 20260903 | `DRY_RUN_BAR_SOURCE` | `sha256:DRY_RUN_PLACEHOLDER_NOT_A_REAL_HASH` | `DATA_BLOCKED` | `DATA_BLOCKED` | No real settled bar exists; this row only tests the template. |
| `T_PLUS_3` | 20260907 | `DRY_RUN_BAR_SOURCE` | `sha256:DRY_RUN_PLACEHOLDER_NOT_A_REAL_HASH` | `DATA_BLOCKED` | `DATA_BLOCKED` | No official sample can be created from fake data. |
| `T_PLUS_5` | 20260909 | `DRY_RUN_BAR_SOURCE` | `sha256:DRY_RUN_PLACEHOLDER_NOT_A_REAL_HASH` | `DATA_BLOCKED` | `DATA_BLOCKED` | Keep this row in the denominator even though it is blocked. |
| `T_PLUS_10` | 20260916 | `DRY_RUN_BAR_SOURCE` | `sha256:DRY_RUN_PLACEHOLDER_NOT_A_REAL_HASH` | `DATA_BLOCKED` | `DATA_BLOCKED` | No method claim can be made from this dry run. |

## Five-Axis Dry-Run State

| Axis | Status | Reason |
|---|---|---|
| Thesis | `DATA_BLOCKED` | No real sealed thesis. |
| Valuation | `DATA_BLOCKED` | No real normalized EPS or valuation range. |
| Timing | `DATA_BLOCKED` | No real manual SMC ticket. |
| Execution | `DATA_BLOCKED` | No real settled bars or fill. |
| Market beta | `DATA_BLOCKED` | No real market or industry return source. |

## Operator Lessons To Check Before Real Use

- Every real observation row must bind a real U4 decision and paper plan hash.
- Fake placeholder hashes are rejected from real workflow review.
- Intraday notes can describe facts, but cannot become fills or official
  returns.
- A blocked or no-trade case still remains in the denominator.
- The template should make the operator slower at lying, faster at recording.

Not trading advice; research signal, human executes.
