# Semiconductor CYQ Publication Repair Plan V0

Status: `DRAFT_REPAIR_PLAN / DOCS_ONLY / NO_PRODUCTION_WRITE`

This plan defines how to repair an already-frozen empty `cyq_perf` source batch
after the forward guard has been fixed. It is a repair contract, not the repair
itself. This document does not run the nightly chain, mutate production data,
select U4 candidates, register a paper cycle, or grant any trade authority.

## Problem Boundary

The semiconductor positive-input path needs `cyq_perf` chip evidence to support
same-day U2/U3 construction. A zero-row same-day `cyq_perf` response should be
treated as `SOURCE_PUBLICATION_PENDING` and remain retryable. Once an empty
response has already been frozen as a successful immutable source batch, an
ordinary retry is no longer enough: the historical artifact itself now has to be
corrected through a separately approved append-only data repair.

This plan covers only that historical correction path. It does not weaken E1
red-flag exclusion, does not fill missing chip data with zeros, and does not
convert a repaired source batch into a U4 selection.

## Non-Goals

- Do not edit, delete, or overwrite the original frozen source batch.
- Do not rewrite already emitted packets or ledgers in place.
- Do not hand-insert semiconductor names into U4.
- Do not treat a repaired `cyq_perf` batch as a paper registration or research
  recommendation.
- Do not touch the production live runtime from this documentation branch.

## Required Preconditions

Before any future migration/data PR may implement this plan, all conditions
below must be true:

1. The forward ingestion guard is merged and verified: future empty same-day
   `cyq_perf` responses become `SOURCE_PUBLICATION_PENDING`, not successful
   immutable batches.
2. Junyan explicitly approves a separate append-only migration/data PR for the
   historical `cyq_perf` batch.
3. The PR owner posts a `CLAIM` to the progress board with the exact file scope,
   branch, reviewer, and no-production-write boundary.
4. The source replacement rows are available from the same authoritative source
   path that the production adapter would use, with a same-day publication
   timestamp or a declared `SOURCE_PUBLICATION_PENDING` stop.
5. The repair run operates on a reviewed copy or staged data artifact first.
   Production deployment remains a separate Junyan-only decision.

If any precondition is missing, the correct state is `DATA_BLOCKED` or
`SOURCE_PUBLICATION_PENDING`, not a partial repair.

## Append-Only Repair Shape

The future migration/data PR should append a repair record that binds both the
bad historical artifact and the replacement artifact. The minimum fields are:

```json
{
  "schema": "ar.semiconductor_source_repair.v0",
  "repair_class": "SOURCE_PUBLICATION_REPAIR",
  "source_name": "cyq_perf",
  "trade_date": "20260824",
  "old_batch_ref": {
    "batch_id": "<existing immutable batch id>",
    "row_count": 0,
    "content_hash": "<existing batch content hash>",
    "ingested_at": "<existing timezone-aware timestamp>"
  },
  "replacement_ref": {
    "row_count": "<positive integer>",
    "content_hash": "<replacement batch content hash>",
    "source_publication_status": "PUBLISHED",
    "source_publication_time": "<timezone-aware timestamp>"
  },
  "repair_reason": "previous empty cyq_perf response was frozen before publication status was modeled",
  "authority": {
    "approved_by": "Junyan",
    "approval_ref": "<GitHub PR review/comment URL>",
    "production_authority": false,
    "trade_authority": false,
    "claim_allowed": false,
    "no_trade_flag": true
  }
}
```

The exact schema may be refined in the implementation PR, but the invariant is
fixed: the old artifact remains visible, and the new artifact supersedes it only
through an append-only, hash-bound record.

## Validation Gates

The repair PR must prove the following before it can be reviewed as mergeable:

1. **Old artifact bound**: the repair record names the exact old batch id,
   row count, content hash, and ingestion timestamp. A mismatched old hash must
   fail closed.
2. **Replacement bound**: replacement rows are hashed from bytes actually used
   by the replay. A self-reported row count is not enough.
3. **Publication status bound**: if the source is not published, the repair must
   stop at `SOURCE_PUBLICATION_PENDING`; it may not synthesize rows.
4. **PIT preserved**: replacement rows must be usable at the repaired trade
   date without look-ahead. Later corrections must be labeled as later facts,
   not same-day evidence.
5. **No zero fill**: a zero-row replacement cannot be treated as success.
6. **Replay clean**: U1/U2/U3 replay must rebuild from the repaired source
   artifacts and report any difference from the pre-repair bundle.
7. **U4 authority unchanged**: the repair cannot create U4 selections, paper
   registrations, simulated orders, or method claims.
8. **Decision denominator preserved**: prior `REJECT`, `DEFER`, `NO_TRADE`,
   `DATA_BLOCKED`, and selected-count rules remain in force.

## Required Negative Tests

The implementation PR should include offline tests for at least these failure
cases:

- old batch hash differs from the repair record;
- replacement row count is zero;
- replacement rows exist but source status remains `SOURCE_PUBLICATION_PENDING`;
- replacement bytes change without content hash changing;
- repaired replay tries to overwrite the original artifact;
- repaired replay creates a U4-ready row carrying an E1 red flag;
- repaired replay attempts to set `production_authority=true`,
  `trade_authority=true`, `claim_allowed=true`, or `no_trade_flag=false`.

At least one governance mutation should pin the old-artifact binding, and one
should pin the no-zero-success rule.

## Operator Runbook

The future operator should follow this order:

1. Open a dedicated migration/data branch from latest `origin/main`.
2. Post a progress-board `CLAIM` with the exact repair scope.
3. Load the existing frozen batch and compute its hash independently.
4. Fetch or stage replacement `cyq_perf` rows through the approved source path.
5. Build the append-only repair record.
6. Replay U1/U2/U3 against the staged repair.
7. Compare old and repaired bundle summaries.
8. Run offline tests and governance mutation checks.
9. Post a `DONE` comment with hashes, replay result, cost, and remaining
   stop conditions.
10. Wait for Junyan's merge/deployment decision.

No step in this runbook allows a direct production write from an unreviewed
branch.

## Dry-Run Checklist

Before the migration/data PR writes any repair artifact, the operator must run
a dry-run and preserve its report in the PR. The dry-run is a proof exercise:
it reads staged artifacts, recomputes identities, and stops before any
production write.

The dry-run report should answer each question below with `PASS`, `BLOCKED`, or
`NOT_APPLICABLE` plus evidence paths:

| Check | Required evidence | Fail-closed result |
|---|---|---|
| Old batch identified | existing batch id, row count, content hash, ingested_at | `OLD_BATCH_UNBOUND` |
| Old batch is the known empty batch | `source_name=cyq_perf`, `trade_date=20260824`, `row_count=0` | `WRONG_BATCH_SCOPE` |
| Original artifact preserved | byte comparison proves no in-place edit | `ORIGINAL_ARTIFACT_MUTATED` |
| Replacement source published | publication status and timestamp are bound | `SOURCE_PUBLICATION_PENDING` |
| Replacement rows non-empty | replacement row count and content hash are recomputed from bytes | `EMPTY_REPLACEMENT_BATCH` |
| PIT boundary holds | replacement facts are usable at the repaired trade date | `LOOKAHEAD_RISK` |
| Universe identity stable | universe hash or explicit universe-change reason is present | `UNIVERSE_UNBOUND` |
| Replay is staged only | output path is outside production live runtime | `PRODUCTION_WRITE_ATTEMPT` |
| E1 veto survives | red-flagged rows cannot become U4-ready | `E1_VETO_BYPASS` |
| U4 authority unchanged | no selection, paper registration, claim, or trade authority appears | `AUTHORITY_ESCALATION` |

The dry-run must also print the exact commands it would run in the later
approved migration, but it must not execute those commands against production.
If the dry-run cannot name a deterministic output path and every input hash, it
is not ready for review.

## Dry-Run Output Shape

The recommended dry-run report is a small JSON object checked into the future
migration/data PR or attached as a review artifact:

```json
{
  "schema": "ar.semiconductor_source_repair_dry_run.v0",
  "status": "BLOCKED_OR_READY",
  "source_name": "cyq_perf",
  "trade_date": "20260824",
  "old_batch_ref": {
    "batch_id": "<existing immutable batch id>",
    "row_count": 0,
    "content_hash": "<existing batch content hash>"
  },
  "replacement_ref": {
    "row_count": "<positive integer or null>",
    "content_hash": "<replacement batch content hash or null>",
    "source_publication_status": "PUBLISHED_OR_SOURCE_PUBLICATION_PENDING"
  },
  "checks": [
    {
      "name": "old_batch_identified",
      "status": "PASS",
      "evidence": "<path or hash>"
    }
  ],
  "would_write": [
    "<append-only repair record path>"
  ],
  "production_write_performed": false,
  "authority": {
    "production_authority": false,
    "trade_authority": false,
    "claim_allowed": false,
    "no_trade_flag": true
  }
}
```

`status=READY` only means the repair PR is ready for human review. It does not
mean the repair is deployed, the source is production-corrected, or any
candidate may enter U4.

## Stop Conditions

Stop and report instead of repairing if:

- the source is still unpublished or cannot be verified;
- replacement rows are unavailable, malformed, or not PIT-safe;
- the old frozen artifact cannot be identified by hash;
- the replay changes prior human decisions without an explicit supersession
  record;
- E1 red flags are suppressed by positive chip/fundamental evidence;
- any artifact claims production, portfolio, paper, or trade authority;
- GitHub progress-board logging or review binding cannot be completed.

## Junyan Approval Template

```text
Junyan, please review the proposed historical cyq_perf publication repair.

Scope:
- source: cyq_perf
- trade_date: 20260824
- repair mode: append-only migration/data PR
- old artifact: bound by batch id, row_count, content hash, and ingested_at
- replacement artifact: bound by row_count, content hash, and publication status

Requested decision:
- APPROVE preparing the migration/data PR under this plan; or
- BLOCK and keep the historical batch as DATA_BLOCKED/SOURCE_PUBLICATION_PENDING.

Boundaries:
- no production write from the planning PR
- no U4 selection
- no paper registration
- no model call
- no external trading or portfolio authority
- E1 red flags remain one-vote veto
```

## Current Status

This document is ready to be used as the review checklist for the future repair
PR. It does not itself repair `cyq_perf|20260824`; that remains blocked until
Junyan approves a separate append-only migration/data PR and its exact replay
evidence.

不是买卖指令；研究信号，human executes.
