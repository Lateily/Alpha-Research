# Model Paper Fund Go-Live Runbook v0

Status: `DRAFT_OPERATOR_RUNBOOK / PAPER_ONLY / PRODUCTION_UNWIRED`

This runbook is the first operating bridge for the Model Paper Fund. It exists
so the team can use the paper account after a candidate passes research review,
while preserving the boundary that only Junyan can make U4 selections and real
capital decisions.

It is not an automatic stock picker, not a trading instruction system, and not a
claim that the method is profitable.

不是买卖指令；研究信号，human executes.

## Goal

The paper fund records what happens after a research idea survives review:

```text
candidate evidence
  -> Junyan U4 decision
  -> sealed thesis / valuation / SMC plan
  -> paper registration
  -> simulated fill and exit under A-share constraints
  -> T+1/T+3/T+5/T+10 observation
  -> five-axis attribution
```

The goal is to measure process quality. A profitable paper result does not prove
the thesis was correct, and a losing paper result does not automatically prove
the research was wrong.

## Current Main State

The core paper ledger already exists under:

```text
experiments/execution_tracker/model_fund/
```

The current committed historical ledger is paper-only and contains inherited
orders. Those inherited records are marked as unverified simulation history and
must not be counted as method-validity samples.

The realistic execution layer is already part of main. It enforces settled-bar
execution, no same-day fill, A-share T+1 sell discipline, price limits, volume
participation, cost/slippage proxies, and corporate-action freezes.

## Required Before First New Paper Registration

All items below must be true before a new semiconductor paper registration is
created:

1. The local repository is based on the latest `origin/main`.
2. The worktree is clean or every dirty file is named with owner, purpose, and
   plan.
3. The same-day U1-U3 preflight packet is available.
4. The U4 pre-decision packet is not blocked by stale, pending, or missing
   sources unless Junyan explicitly approves carrying `DATA_BLOCKED`.
5. Junyan has committed a U4 decision through the U4 decision ledger.
6. The selected case has a sealed thesis, valuation, wrong-if, and manual SMC
   timing plan.
7. The paper registration plan hash is reviewed before any write.
8. The approval artifact is separate from model output and contains the full
   plan hash.
9. All outputs keep `no_trade_flag=true`, `trade_authority=false`, and
   `production_authority=false`.

If any item is missing, the correct result is `STOP_BEFORE_PAPER_REGISTRATION`.

## Paper Admission Acceptance Gate

Plain meaning: a security is not "admitted" to the Model Paper Fund when it
looks interesting. It is admitted only when the full U4-to-paper packet is
complete, reviewable, and still paper-only.

Every new admission packet must carry these fields before a pending paper order
can be created:

| Field | Required value or meaning |
|---|---|
| `ticker` | the security identity used by the paper engine |
| `security_name` | human-readable name for review only |
| `target_trade_date` | the trade date this paper plan is allowed to use |
| `u4_decision_ref` | committed U4 decision-ledger artifact |
| `u4_decision_actor` | `Junyan` |
| `u4_decision` | `SELECT` only; `REJECT`, `DEFER`, `NO_TRADE`, and `DATA_BLOCKED` must stop |
| `source_packet_ref` | same-day preflight or U4 pre-decision packet reference |
| `source_packet_hash` | hash of the exact evidence packet reviewed |
| `evidence_hash` | hash binding the evidence used for thesis and timing |
| `method_version` | method version attached before the outcome |
| `cohort_id` | denominator cohort for later review |
| `causal_cluster_id` | de-clustering key for the 30 independent-sample rule |
| `thesis_ref` | sealed thesis artifact |
| `thesis_hash` | hash of the sealed thesis |
| `valuation_ref` | sealed valuation artifact |
| `valuation_hash` | hash of the sealed valuation |
| `wrong_if` | pre-outcome invalidation condition |
| `manual_smc_ref` | sealed manual SMC timing artifact |
| `manual_smc_hash` | hash of the timing artifact |
| `timing_state` | `PASS`; `WAIT` and `DATA_BLOCKED` must stop before paper registration |
| `entry_zone` | planned paper review zone, not an after-the-fact fill |
| `structure_stop` | pre-outcome technical invalidation reference |
| `target_1` / `target_2` | planned paper references, not proof of value |
| `fund_snapshot_ref` | paper-fund state reviewed before plan creation |
| `fund_snapshot_hash` | hash of the exact fund snapshot |
| `paper_registration_plan_hash` | full plan hash shown to the human approver |
| `human_approval_ref` | approval artifact separate from model output and bound to the full plan hash |
| `observation_schedule` | `T+1`, `T+3`, `T+5`, and `T+10` checkpoints |
| `paper_only` | `true` |
| `no_trade_flag` | `true` |
| `trade_authority` | `false` |
| `production_authority` | `false` |
| `sample_eligible` | `false` for the first 5-10 semiconductor workflow-debug cycles |
| `method_claim_sample_eligible` | `false` until the 30 independent de-clustered sample gate is met |

The admission gate must stop before a pending order when any of these are true:

- the U4 decision is missing, not committed, not by Junyan, or not `SELECT`;
- the source packet is stale, pending, missing, or not hash-bound;
- an active E1 red flag is present;
- thesis, valuation, wrong-if, or manual SMC is unsealed;
- `timing_state` is `WAIT` or `DATA_BLOCKED`;
- the plan was created after seeing the target price path;
- `human_approval_ref` is model text, chat text, or not bound to the full `paper_registration_plan_hash`;
- the paper fund snapshot is missing, stale, or not hash-bound;
- any authority field attempts to grant real trading, production, or paper-order
  authority outside the reviewed bridge;
- the observation schedule is missing any of `T+1`, `T+3`, `T+5`, or `T+10`;
- the first 5-10 semiconductor workflow-debug cycles are marked as
  method-validity samples.

The stop result remains `STOP_BEFORE_PAPER_REGISTRATION`. A stopped packet is
still useful: it records exactly why a promising research idea was not admitted
to the paper fund.

## Morning Checklist

Before market open, Reed prepares the paper fund view:

```powershell
git status --short
git branch --show-current
git fetch --prune origin
git rev-parse origin/main
```

Then read the paper fund status only:

```powershell
py -3.11 .\experiments\execution_tracker\model_paper_fund.py --status
```

On Windows, set UTF-8 process output before running local selftests that print
Chinese text or check marks:

```powershell
$env:PYTHONIOENCODING="utf-8"
```

Do not run `--daily`, `--init`, production nightly, source repair `apply`, or a
paper registration apply from this checklist without the separate approval that
names the exact scope.

## U4 To Paper Registration

The registration bridge is expected to be the only V1 path from a U4 `SELECT` to
a pending paper order:

```text
settled marks + committed U4 SELECT + sealed prospective case + fund snapshot
  -> deterministic plan
  -> human approval containing the full plan_hash
  -> paper_registration_intent
  -> orders.json and decision_log.json projection
  -> exact post-state verification
  -> paper_registration_commit
```

Until the bridge is merged into main and approved for use, Reed may prepare
draft artifacts and review checklists, but must not create a new paper order
through an alternate manual path.

## Intraday Observation

Intraday work is observation only. It may update a watch/review note, but it
must not create fills, exits, official NAV, or method-validity samples.

Use `MODEL_PAPER_FUND_INTRADAY_OBSERVATION_TEMPLATE_V0.md` for every intraday
operator note so the authority fields and forbidden outputs stay visible.

Allowed observation outputs:

- visible thesis status;
- SMC structure notes;
- catalyst and wrong-if observations;
- data gaps;
- risk-review notes;
- questions for Junyan.

Forbidden intraday outputs:

- official fills;
- official exits;
- official NAV;
- real order language;
- moving a stop looser;
- rewriting the original thesis after seeing price action.

## Post-Close Checklist

After settled bars are available, the paper account may be advanced only through
the official paper engine path.

Use `MODEL_PAPER_FUND_POST_CLOSE_REPORT_TEMPLATE_V0.md` for the daily report
after the engine outputs are available.

The expected daily order is:

```text
settled bars available
  -> process paper fills/exits
  -> update official NAV only with complete marks
  -> run position review
  -> run 10-day review when applicable
  -> write daily observation summary
```

If a filled position lacks a target-date settled mark, the official NAV must be
`DATA_BLOCKED`. The system must not mix target-date marks for some positions
with cost marks for others.

## Observation Schedule

Every new paper registration should create these checkpoints:

| Checkpoint | Purpose |
|---|---|
| T+1 | Did the entry condition actually become fillable under settled-bar rules? |
| T+3 | Did the thesis/timing setup start to confirm or fail? |
| T+5 | Is the trade drifting, blocked, or still within the planned structure? |
| T+10 | Does the position need a formal hold/exit review? |

Each checkpoint records:

- price and return from simulated fill when available;
- R multiple when stop and fill are known;
- thesis evidence update;
- valuation evidence update;
- timing/SMC evidence update;
- execution evidence update;
- market/industry beta context;
- `DATA_BLOCKED` when any required evidence is missing.

## Scoring Boundary

The first 5-10 semiconductor paper cycles are workflow-debug samples only:

- `sample_eligible=false`;
- `method_claim_sample_eligible=false`;
- `portfolio_promotion_eligible=false`;
- no win-rate claim;
- no alpha claim;
- no live trading promotion.

At least 30 independent, de-clustered closed samples and cross-industry
replication are required before the team can discuss method validity.

## Tomorrow Readiness List

For the paper fund to be usable tomorrow, the team needs exactly this:

1. U4 pre-decision runtime available on main or explicitly approved as a
   reviewed offline artifact.
2. Paper registration bridge available on main or explicitly approved as a
   reviewed offline artifact.
3. A same-day preflight packet for the target trade date.
4. A clear `STOP_BEFORE_RERUN` or `ALLOW_U1_U3_RERUN` result.
5. A Junyan U4 decision if any candidate is allowed forward.
6. A sealed research case before any paper registration.
7. A reviewed plan hash before any paper ledger write.
8. A post-close routine for settled-bar advance and T+ checkpoint logging.

If items 1-2 are not approved by market open, the safe fallback is to run
research preflight and U4 preparation only, without creating a new paper order.

## Prelaunch Companion Artifacts

The following companion artifacts keep the launch sequence auditable:

- `MODEL_PAPER_FUND_FRONTEND_DISPLAY_AUDIT_20260830.md` checks that the paper
  fund display reads the paper-only v2 state instead of legacy recommendation
  fields.
- `MODEL_PAPER_FUND_DRY_RUN_20260830.md` and
  `fixtures/model_paper_fund_dry_run_v0.json` rehearse the U4-to-pending-order
  handoff with fake data only.
- `PR319_PR322_ACCEPTANCE_CHECKLIST_V0.md` separates the #322 U4
  pre-decision gate from the #319 paper registration bridge gate.
