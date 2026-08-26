# Semiconductor Same-Day Rerun Checklist v0

Status: `DRAFT_OFFLINE_OPERATOR_CHECKLIST / PRODUCTION_UNWIRED`

This checklist is the operator gate before the next semiconductor same-day
U1-U3 rerun. It prepares the rerun. It does not run the production nightly,
repair production data, select U4 names, register a paper cycle, or create a
trade instruction.

## Purpose

The checklist answers one question:

```text
Is today's semiconductor rerun allowed to start, or must it stop before U1-U3?
```

It exists because the first real semiconductor attempt stopped before U4: the
visible rows were red-flag-only and the positive input channels were either
absent or not yet trustworthy enough. The next rerun must prove that the data
and review gates are ready before any candidate is handed to Junyan.

## Operator Inputs

The operator must name these artifacts before a rerun is treated as ready:

| Artifact | Required evidence |
|---|---|
| Latest `origin/main` SHA | `git fetch --prune origin` succeeded and `git rev-parse origin/main` recorded |
| Working branch/worktree | `git status --short` is empty before rerun preparation |
| Source repair scan | `semiconductor_source_repair.py scan --db <copy> --output <scan.json>` run on a reviewed copy |
| Source repair approval | If any repair is required, Junyan approval binds the exact scan hash before apply |
| Intake diagnostic | `semiconductor_evidence_diagnostic.py --intake <receipt.json> --output <diagnostic.json>` |
| Same-day U1-U3 bundle | Candidate pool and U3 battery share the same `as_of` and run identity |
| U4 handoff packet | Only built after sources, diagnostics, and red-flag propagation pass |

Any unavailable artifact is a stop, not a warning to ignore.

## Allowed Local Checks

These checks are read-only or write only local scratch outputs:

```powershell
git status --short
git branch --show-current
git fetch --prune origin
git rev-parse origin/main
```

```powershell
py -3.11 .\experiments\research_funnel\semiconductor_source_repair.py scan `
  --db <reviewed-feature-store-copy.sqlite> `
  --output <local-scan.json>
```

```powershell
py -3.11 .\experiments\research_funnel\semiconductor_evidence_diagnostic.py `
  --intake <committed-intake-receipt.json> `
  --output <local-diagnostic.json>
```

Do not run `apply`, production nightly, or feature-store live collection from
this checklist. Those require a separate Junyan approval with exact scope and
hashes.

## Stop Conditions

Stop before rerun when any condition below is true:

1. The worktree is dirty and the dirty files are not explained.
2. The branch is not based on current `origin/main`.
3. The source repair scan reports `REPAIR_REQUIRED` and no exact Junyan
   approval exists for the scan hash.
4. A daily must-publish source is `SOURCE_PUBLICATION_PENDING`, `STALE`, or
   `DATA_BLOCKED`.
5. A source repair is `LATE_OBSERVED` and the operator tries to treat it as
   same-day evidence.
6. The diagnostic fails `evidence_rows_hash` or `RECEIPT_SELF_REPORT_MISMATCH`.
7. U1/U2 has no positive semiconductor channel rows.
8. Any U4-ready row carries an active E1 red flag.
9. Any U2 candidate lacks a same-run U3 battery row or explicit `DATA_BLOCKED`.
10. The U4-ready pool contains one or two names; legal handoff counts remain
    zero or three to five.
11. `method_version`, `cohort_id`, or `causal_cluster_id` is missing from rows
    that will later be used for sample accounting.
12. Any output claims `production_authority=true`, `trade_authority=true`,
    `claim_allowed=true`, or `no_trade_flag=false`.

The correct result for a stopped rerun is an explicit blocked report. It is not
a failed research day. It preserves the denominator and prevents false
confidence.

## Pass Conditions

The rerun may proceed to same-day U1-U3 only when all conditions hold:

1. Local repo state is synchronized and clean.
2. Source repair scan is either clean or an approved repair has already been
   applied and verified on the approved copy.
3. Daily must-publish sources are published for the rerun date.
4. The diagnostic reads original evidence rows, verifies the evidence hash, and
   cross-checks receipt counts.
5. E1 red-flag vetoes propagate into U3/U4 blockers.
6. Every candidate has a same-run U3 battery row or explicit `DATA_BLOCKED`.
7. The handoff packet exposes blocked rows, missing evidence, positive
   channels, red-flag channels, method version, cohort, and causal cluster.
8. The machine grants no selection, paper-order, production, or trade authority.

## Handoff Shape

If the checklist passes, Reed prepares a packet for Junyan with:

- source status and scan hash;
- diagnostic status and blocker codes;
- candidate rows with positive and blocked evidence separated;
- U3 battery status and missing evidence;
- red-flag propagation status;
- `method_version`, `cohort_id`, and `causal_cluster_id`;
- legal selected-count reminder: `0, 3, 4, 5`;
- authority constants: `HUMAN_JUNYAN_ONLY`, `no_trade_flag=true`.

Junyan may then choose zero or three to five names through the U4 decision
ledger. The machine cannot select names because the ready pool is small, the
team is impatient, or the market feels urgent.

## Reporting Template

```text
SEMICONDUCTOR_RERUN_PREFLIGHT: PASS / BLOCKED / PASS_WITH_GAPS
OWNER:
ORIGIN_MAIN_SHA:
WORKTREE_STATUS:
SOURCE_SCAN_HASH:
SOURCE_SCAN_STATUS:
INTAKE_DIAGNOSTIC_STATUS:
U2_ROWS:
POSITIVE_CHANNEL_ROWS:
U3_ROWS:
U4_READY_ROWS:
RED_FLAG_BLOCKED_ROWS:
DATA_BLOCKED_ROWS:
METHOD_VERSION:
COHORT_STATUS:
CAUSAL_CLUSTER_STATUS:
STOP_CONDITIONS:
NEXT:
NO_TRADE_FLAG: true
```

不是买卖指令；研究信号，human executes.
