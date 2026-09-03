# PR #319 / #322 Acceptance Checklist v0

Status: `DRAFT_REVIEW_CHECKLIST / PAPER_ONLY / NO_MERGE_AUTHORITY`

This checklist separates the two gates needed before the Model Paper Fund can be
used for a new prospective paper cycle.

Not trading advice; research signal, human executes.

## Pipeline Position

```text
same-day U1-U3 evidence
  -> #322 U4 pre-decision packet
  -> Junyan U4 decision ledger
  -> sealed thesis / valuation / manual SMC
  -> #319 paper registration bridge
  -> pending paper order
```

## #322 - U4 Pre-Decision Runtime

Plain meaning: #322 answers whether a candidate packet is safe to show Junyan
before U4. It must never make the U4 choice.

Review checklist:

1. Input is same-day U1-U3 evidence and candidate-battery output.
2. Output is a U4 pre-decision packet for human review.
3. `PENDING`, `STALE`, missing, or conflicting daily/quarterly sources stop
   before U4 or produce explicit `DATA_BLOCKED`.
4. Active E1 red flags propagate into the packet and cannot be offset by
   positive evidence.
5. Candidate rows preserve `method_version`, `cohort_id`,
   `causal_cluster_id`, `blocked_reasons`, and quality status.
6. The packet does not contain Junyan's final U4 decision.
7. The packet does not create a paper order, ledger write, official NAV, model
   call, or real-capital action.
8. CI must run the relevant U4 pre-decision tests on the exact PR head.

Acceptance result options:

- `PASS_FOR_HUMAN_U4_REVIEW`;
- `REVISE_REQUIRED`;
- `BLOCKED_BY_SOURCE_OR_AUTHORITY_GAP`.

## #319 - Paper Registration Bridge

Plain meaning: #319 answers whether a committed Junyan `SELECT` can become a
pending paper order through one governed path. It must never bypass Junyan or
write a real trade.

Review checklist:

1. Input requires a committed U4 `SELECT`, sealed case, valuation, wrong-if,
   manual SMC plan, and fund snapshot.
2. The bridge creates a deterministic plan before writing anything.
3. The plan contains a full `plan_hash`.
4. Human approval is separate from model output and is bound to the full
   `plan_hash`.
5. The bridge records `paper_registration_intent` before any paper ledger
   projection.
6. The bridge writes only the approved paper-fund artifacts, then verifies the
   exact post-state.
7. The bridge records `paper_registration_commit` only after verification.
8. Duplicate orders, stale fund snapshots, missing plan hash, mismatched
   approval, loosened stops, and non-paper authority all fail closed.
9. The result remains `paper_only=true`, `no_trade_flag=true`,
   `trade_authority=false`, and `production_authority=false`.
10. CI and mutation gates must run on the exact PR head.

Acceptance result options:

- `PASS_FOR_PAPER_REGISTRATION_REVIEW`;
- `REVISE_REQUIRED`;
- `BLOCKED_BY_U4_OR_PLAN_GAP`.

## Required Sequence

The safe sequence is:

1. #322 passes or an equivalent reviewed offline U4 pre-decision artifact is
   approved.
2. Junyan makes a U4 decision in the U4 decision ledger.
3. The selected case is sealed.
4. #319 passes or an equivalent reviewed offline registration artifact is
   approved.
5. A plan hash is reviewed.
6. Only then can a pending paper order be created.

If #322 is missing, Reed may prepare evidence but must not ask Junyan to approve
a paper registration. If #319 is missing, Reed may prepare a plan review packet
but must not create a pending paper order.
