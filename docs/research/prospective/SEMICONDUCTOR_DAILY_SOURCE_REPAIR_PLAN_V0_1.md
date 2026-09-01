# Semiconductor Daily Source Publication Repair Plan V0.1

Status: `V0_1_IMPLEMENTATION_CONTRACT / NO_PRODUCTION_WRITE_WITHOUT_EXACT_HASH_APPROVAL`

This plan defines how to repair already-frozen empty or structurally incomplete
daily source batches after the forward guard has been fixed. It is a repair
contract, not the repair itself. This document does not run the nightly chain,
mutate production data, select U4 candidates, register a paper cycle, or grant
any trade authority.

## Problem Boundary

The semiconductor positive-input path needs daily `moneyflow_dc` and `cyq_perf`
evidence to support same-day U2/U3 construction. An empty or under-covered
response from either must-publish source should be treated as
`SOURCE_PUBLICATION_PENDING` and remain retryable. Once such a response has
already been frozen as a successful immutable source batch, an ordinary retry is
no longer enough: the active read projection has to be corrected through a
separately approved append-only data repair while the original remains visible.

This plan covers only that historical correction path. It does not weaken E1
red-flag exclusion, does not fill missing evidence with zeros, and does not
convert a repaired daily source batch into a U4 selection.

## V0.1 Amendments

V0.1 closes two load-bearing omissions from V0:

1. A repair is not effective merely because a record was appended. Every reader
   must resolve `(source_name, as_of)` through a verified supersession chain and
   consume the unique active replacement. Removing that resolver call must make
   a dedicated governance mutation fail.
2. Repair discovery is class-wide. The dry run scans every historical date for
   every source in `DAILY_MUST_PUBLISH_SOURCES`, using the same frozen 95 percent
   coverage policy as merged PR #313. It may not hardcode one source or date.

The reviewed implementation adds four conservative boundaries:

3. A repair input carries the exact staged Tushare response fields, request
   parameters, capture time, collector version, and content hashes. This is an
   auditable capture receipt, not provider-authenticated proof.
4. V0.1 has no independently authenticated publication-time receipt. Therefore
   every accepted repair is `LATE_OBSERVED`; it may improve future diagnostics
   but cannot rewrite the historical U1/U2/U3 evidence window.
5. The production feature-store path and `nightly.lock` are derived from one
   explicit runtime root. The production CLI exposes no independent database or
   lock override.
6. The repair catalog is all-or-nothing. Every repair row must belong to one
   valid committed receipt, and every receipt must bind its exact repair rows,
   before any reader accepts any projection.

The current database has no standalone `batch_id`. The immutable batch identity
is the composite `(source_name, as_of)` plus its stored `source_hash`,
`universe_hash`, row count, missing/conflict sets, and `ingested_at`. V0.1 uses
that real identity instead of inventing an unavailable field.

## Non-Goals

- Do not edit, delete, or overwrite any original frozen source batch.
- Do not rewrite already emitted packets or ledgers in place.
- Do not hand-insert semiconductor names into U4.
- Do not treat a repaired daily source batch as a paper registration or research
  recommendation.
- Do not touch the production live runtime from this documentation branch.

## Required Preconditions

Before any future migration/data PR may implement this plan, all conditions
below must be true:

1. The FF-1b forward ingestion guard is merged and verified in PR #313
   (`3543e8cd`): future empty or under-covered daily must-publish responses
   become `SOURCE_PUBLICATION_PENDING`, not successful immutable batches.
2. Junyan explicitly approves a separate append-only migration/data PR for the
   exact class-wide repair plan and frozen scan hash.
3. The PR owner posts a `CLAIM` to the progress board with the exact file scope,
   branch, reviewer, and no-production-write boundary.
4. The source replacement rows are available from the same authoritative source
   path that the production adapter would use. `observed_at` must be recorded;
   an unavailable source publication timestamp must remain explicitly
   unavailable rather than being inferred from `trade_date`.
5. The repair run operates on a reviewed copy or staged data artifact first.
   Production deployment remains a separate Junyan-only decision.

If any precondition is missing, the correct state is `DATA_BLOCKED` or
`SOURCE_PUBLICATION_PENDING`, not a partial repair.

## Class-Wide Discovery

The implementation PR must derive its scope from a read-only scan, not from a
handwritten list. The scanner must:

1. Import the reviewed `DAILY_MUST_PUBLISH_SOURCES` registry and coverage ratio
   from the same implementation used by forward ingestion.
2. Derive the union of historical dates, then emit the complete Cartesian set
   `DAILY_MUST_PUBLISH_SOURCES x historical_dates`. A missing registered
   source/date pair is an explicit `SOURCE_PUBLICATION_PENDING` row; it is never
   omitted from the scan.
3. Rebuild the expected universe from stored source rows plus the declared
   missing-code set, verify `universe_hash`, and recompute the minimum acceptable
   row count with `ceil(expected_rows * 0.95)`.
4. Resolve any existing repair chain before classifying the active batch.
5. Emit one deterministic row per source/date with old and active hashes,
   observed/expected/minimum row counts, and exactly one state:
   `CLEAN_ACTIVE`, `REPAIR_REQUIRED`, `SOURCE_PUBLICATION_PENDING`, or
   `PIT_BLOCKED`.
6. Freeze the complete ordered result as `scan_hash`. The later apply step must
   recompute the scan and refuse if the hash or any bound batch changed.

The read-only audit that motivated V0.1 found more than one affected date and
also found nearby batches above the declared floor. Those observations prove why
the scanner must derive scope instead of hardcoding an instance. Exact production
counts belong in the frozen dry-run artifact reviewed for the migration, not in
this reusable public contract. A later scan may discover more dates or sources
and must report them without silently expanding an already approved apply plan.

## Append-Only Repair Shape

The future migration/data PR should append a repair record that binds both the
bad historical artifact and the replacement artifact. The minimum fields are:

```json
{
  "schema": "ar.semiconductor_source_repair",
  "schema_version": "0.1",
  "repair_id": "<hash-derived immutable id>",
  "repair_class": "SOURCE_PUBLICATION_REPAIR",
  "source_name": "cyq_perf",
  "as_of": "20260824",
  "scan_hash": "<approved class-wide scan hash>",
  "old_batch_ref": {
    "source_name": "cyq_perf",
    "as_of": "20260824",
    "row_count": 0,
    "source_hash": "<existing immutable source hash>",
    "universe_hash": "<existing universe hash>",
    "missing_codes_hash": "<hash of canonical missing-code list>",
    "conflict_codes_hash": "<hash of canonical conflict-code list>",
    "evidence_time": "<existing timezone-aware timestamp>",
    "origin": "ORIGINAL_BATCH",
    "repair_id": null,
    "point_in_time_status": "ORIGINAL_INGESTION"
  },
  "replacement_ref": {
    "row_count": "<positive integer>",
    "source_hash": "<replacement body hash recomputed from canonical bytes>",
    "universe_hash": "<replacement universe hash>",
    "source_publication_status": "PUBLISHED",
    "source_publication_time": "<timezone-aware timestamp or null>",
    "observed_at": "<timezone-aware timestamp>",
    "point_in_time_status": "LATE_OBSERVED"
  },
  "raw_capture": {
    "provider": "TUSHARE_PRO",
    "endpoint": "cyq_perf",
    "request_params": {"trade_date": "20260824"},
    "collector_version": "<reviewed collector version>",
    "captured_at": "<timezone-aware timestamp>",
    "raw_rows_hash": "<hash recomputed from exact staged rows>",
    "evidence_strength": "UNAUTHENTICATED_PROVIDER_CAPTURE_REVIEW_REQUIRED",
    "capture_hash": "<hash of the complete receipt>"
  },
  "supersedes_source_hash": "<old active source hash>",
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

The exact storage tables may be refined in the implementation PR, but the
invariant is fixed: the old artifact remains visible, and the new artifact
supersedes it only through an append-only, hash-bound record. Replacement rows
must live in an append-only repair payload or repair-row table; they may not
collide with or overwrite the original source table primary keys.

## Read-Side Supersession Semantics

This is Validation Gate 0. Every production and replay reader that currently
loads `semiconductor_source_batches` or its source rows must call one shared
resolver before returning evidence:

```text
resolve_active_source(source_name, as_of)
  original = immutable original batch
  head = original.source_hash
  while one committed repair supersedes head:
      recompute and verify the repair payload and replacement source_hash
      head = replacement.source_hash
  reject cycles, forks, dual active heads, missing predecessors, or hash drift
  return the unique verified active batch while preserving original history
```

At minimum, `_has_batch`, snapshot construction, feature-health projection, and
the class-wide scanner must use this resolver. A repair record that no reader
consumes is not a repair. Removing the resolver call from a production read path
must make a dedicated behavior test and governance mutation fail.

V0.1 cannot emit `PIT_VERIFIED`. A staged response and a self-reported
publication timestamp do not independently prove what was available at the
historical decision cutoff. Every accepted replacement is `LATE_OBSERVED`: the
resolver may expose it for repair verification and future diagnostics, while the
same-date research snapshot remains explicitly `DATA_BLOCKED` with reason
`LATE_OBSERVED_REPAIR`. Already frozen packets, human decisions, paper
registrations, and method claims are never rewritten.

## Validation Gates

The repair PR must prove the following before it can be reviewed as mergeable:

0. **Read-side supersession is load-bearing**: every affected reader resolves the
   unique active source through the verified repair chain. Removing a resolver
   call must fail a dedicated mutation test.
1. **Old artifact bound**: the repair record names the exact composite source/date
   identity, row count, source hash, universe hash, missing/conflict sets, and
   ingestion timestamp. A mismatched old hash must fail closed.
2. **Replacement bound**: replacement rows are hashed from bytes actually used
   by the replay, and the staged raw capture receipt is independently rehashed.
   A self-reported row count or source hash is not enough.
3. **Publication status bound**: if the source is not published, the repair must
   stop at `SOURCE_PUBLICATION_PENDING`; it may not synthesize rows.
4. **PIT preserved**: replacement rows must be usable within the claimed evidence
   window without look-ahead. A later observation without independent publication
   time is labeled `LATE_OBSERVED`, not silently promoted to same-day evidence.
5. **No zero fill**: a zero-row replacement cannot be treated as success.
6. **Replay honest**: U1/U2/U3 replay must keep the repaired historical
   component `DATA_BLOCKED`, preserve every E1 veto, and report any difference
   from the pre-repair bundle. V0.1 may not launder a late capture into a
   same-day positive trigger.
7. **U4 authority unchanged**: the repair cannot create U4 selections, paper
   registrations, simulated orders, or method claims.
8. **Decision denominator preserved**: prior `REJECT`, `DEFER`, `NO_TRADE`,
   `DATA_BLOCKED`, and selected-count rules remain in force.
9. **Class-wide scope bound**: the apply plan is derived from the complete frozen
   scan and names every included repair. A changed scan hash or a newly discovered
   candidate stops the run for renewed approval; it does not expand scope.

## Required Negative Tests

The implementation PR should include offline tests for at least these failure
cases:

- old batch hash differs from the repair record;
- a reader ignores the active supersession resolver;
- two repairs fork from the same predecessor or form a cycle;
- the daily-source registry or historical-date scan is narrowed;
- replacement row count is zero;
- replacement rows exist but source status remains `SOURCE_PUBLICATION_PENDING`;
- replacement bytes change without content hash changing;
- a raw capture hash, request identity, required value, or percentile ordering
  is forged while normalized rows are relabeled;
- repaired replay tries to overwrite the original artifact;
- repaired replay creates a U4-ready row carrying an E1 red flag;
- repaired replay attempts to set `production_authority=true`,
  `trade_authority=true`, `claim_allowed=true`, or `no_trade_flag=false`.

Governance mutations must pin the read-side resolver call, full source/date
Cartesian scan, catalog-wide receipt verification, old-artifact binding,
capture/evidence validation, no-zero-success rule, exact runtime-root lock
binding, pre-commit projection validation, and literal approval check.

## Operator Runbook

The future operator should follow this order:

1. Open a dedicated migration/data branch from latest `origin/main`.
2. Post a progress-board `CLAIM` with the exact repair scope.
3. Run the class-wide scanner over all registered daily must-publish sources and
   all historical dates; freeze its ordered output and `scan_hash`.
4. Build an explicit apply plan from that scan. The plan may include only rows
   approved by Junyan and must not auto-expand if the scan later changes.
5. Load every bound original batch and compute its hashes independently.
6. Fetch or stage replacement rows through the approved source path.
7. Classify an unpublished response as `SOURCE_PUBLICATION_PENDING`; classify
   every accepted V0.1 replacement as `LATE_OBSERVED`. Never infer publication
   time from trade date and never promote self-reported time to PIT proof.
8. Build the append-only repair records and prove the reader resolves them.
9. Replay U1/U2/U3 against the staged active projection.
10. Compare old and repaired bundle summaries.
11. Run offline tests and governance mutation checks.
12. Post a `DONE` comment with scan/plan hashes, replay result, cost, and remaining
   stop conditions.
13. Wait for Junyan's merge/deployment decision.

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
| Class scan complete | registered daily-source set, all dates, ordered rows, scan hash | `CLASS_SCAN_INCOMPLETE` |
| Old batch identified | source/date, row count, source hash, universe hash, ingested_at | `OLD_BATCH_UNBOUND` |
| Apply scope approved | exact repair keys and frozen scan/plan hashes | `UNAPPROVED_SCOPE_DRIFT` |
| Original artifact preserved | byte comparison proves no in-place edit | `ORIGINAL_ARTIFACT_MUTATED` |
| Replacement source published | status, observed_at, and honest publication-time availability | `SOURCE_PUBLICATION_PENDING` |
| Replacement rows non-empty | replacement row count and content hash are recomputed from bytes | `EMPTY_REPLACEMENT_BATCH` |
| PIT boundary holds | replacement facts are usable at the repaired trade date | `LOOKAHEAD_RISK` |
| Universe identity stable | universe hash or explicit universe-change reason is present | `UNIVERSE_UNBOUND` |
| Replay is staged only | output path is outside production live runtime | `PRODUCTION_WRITE_ATTEMPT` |
| Active reader resolves repair | old remains visible and unique verified replacement is active | `REPAIR_NOT_CONSUMED` |
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
  "schema": "ar.semiconductor_source_repair_dry_run.v0.1",
  "status": "BLOCKED_OR_READY_FOR_HUMAN_REVIEW",
  "scan_hash": "<complete ordered class-scan hash>",
  "plan_hash": "<explicit approved apply-plan hash>",
  "daily_sources": ["cyq_perf", "moneyflow_dc"],
  "repair_candidates": [
    {
      "source_name": "cyq_perf",
      "as_of": "20260824",
      "old_batch_ref": {
        "source_hash": "<existing immutable source hash>",
        "universe_hash": "<existing universe hash>",
        "row_count": 0,
        "ingested_at": "<timezone-aware timestamp>"
      },
      "replacement_ref": {
        "row_count": "<positive integer or null>",
        "source_hash": "<recomputed replacement source hash or null>",
        "source_publication_status": "PUBLISHED_OR_SOURCE_PUBLICATION_PENDING",
        "source_publication_time": "<timestamp or null>",
        "observed_at": "<timezone-aware timestamp>",
        "point_in_time_status": "LATE_OBSERVED"
      }
    }
  ],
  "checks": [
    {
      "name": "old_batch_identified",
      "status": "PASS",
      "evidence": "<path or hash>"
    }
  ],
  "would_write": [
    "<append-only repair record or table key>"
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

- the class-wide scan or apply plan changes after approval;
- the source is still unpublished or cannot be verified;
- replacement rows are unavailable, malformed, or not PIT-safe;
- the read-side resolver cannot prove one unique active head;
- the old frozen artifact cannot be identified by hash;
- the replay changes prior human decisions without an explicit supersession
  record;
- E1 red flags are suppressed by positive chip/fundamental evidence;
- any artifact claims production, portfolio, paper, or trade authority;
- GitHub progress-board logging or review binding cannot be completed.

## Junyan Approval Template

The operator may explain the plan in prose, but the write gate accepts exactly
one affirmative line. Negative wording that merely contains Junyan's name and
the hashes is rejected:

```text
批准执行半导体日源迁移；scan_hash=<complete-class-scan-hash>；plan_hash=<exact-plan-hash>
```

The approval record also stores `approved_by=Junyan`, a durable session or
GitHub reference, the timestamp, and
`evidence_strength=TRANSCRIPT_ONLY_NOT_CRYPTOGRAPHIC`. This preserves Junyan's
final authority honestly; it does not claim cryptographic identity proof.

## Current Status

This document is the implementation and migration review checklist. It does not
itself repair any historical batch. Merging the implementation still does not
authorize a production write. Apply remains blocked until a fresh production
read-only scan, staged provider capture, exact plan, independent verification,
and Junyan's literal full-hash approval have all completed. Any drift requires a
new plan and a new approval.

不是买卖指令；研究信号，human executes.
