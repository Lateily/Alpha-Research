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

## Canonical Preflight

After Junyan approves this checklist, this document is the canonical preflight
for the next semiconductor same-day U1-U3 rerun. PR #303 / NEXT_RUN_PREFLIGHT is
background context only unless Junyan explicitly reassigns authority back to it.

When the two documents disagree, stop and follow this checklist. Do not average
the two documents, copy the easier command, or treat #303 as an alternate pass
path. Any future checklist replacement must name the document it supersedes and
must carry a new review reference.

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

## Execution Environments

The reviewed feature-store copy is produced on the production Mac because the
live store lives there. Windows workstations may inspect a reviewed copy after it
has been produced, but they must not point this checklist at a live production
database path.

The copy step is a read-only source operation and a local-copy write operation.
It does not repair production data and does not grant permission to run nightly,
apply a source repair, or write an order. If the production Mac lacks the files
needed to make a reviewed copy, stop with `DATA_BLOCKED`.

### Production Mac: make reviewed feature-store copy

Run this on the production Mac from a reviewed shell. Use plain backslash line
continuations; do not use zsh backticks.

```bash
cd <alpha-research-repo>
REVIEW_DIR="<local-reviewed-copy-dir>/semiconductor-rerun-YYYYMMDD"
mkdir -p "$REVIEW_DIR"
sqlite3 "/Users/years/ar-live/data_history/feature_store.sqlite3" \
  ".backup '$REVIEW_DIR/feature_store-review.sqlite3'"
sqlite3 "$REVIEW_DIR/feature_store-review.sqlite3" \
  "PRAGMA journal_mode=DELETE; PRAGMA integrity_check;"
```

The `journal_mode=DELETE` conversion is applied only to the reviewed copy. It
prevents a detached WAL copy from failing under read-only scan. If
`integrity_check` does not return `ok`, stop.

### Production Mac: scan reviewed copy

```bash
cd <alpha-research-repo>
python3 experiments/research_funnel/semiconductor_source_repair.py scan \
  --db "<local-reviewed-copy-dir>/semiconductor-rerun-YYYYMMDD/feature_store-review.sqlite3" \
  --output "<local-reviewed-copy-dir>/semiconductor-rerun-YYYYMMDD/source-scan.json"
```

### Windows review station: scan transferred reviewed copy

Use this only after the reviewed copy exists locally. This is the Reed-side
shape; it is not the production Mac shape.

```powershell
py -3.11 .\experiments\research_funnel\semiconductor_source_repair.py scan `
  --db <reviewed-feature-store-copy.sqlite> `
  --output <local-scan.json>
```

## Operator Packet

Before any same-day U1-U3 rerun, Reed prepares one operator packet. The packet
is a preflight cover sheet, not the rerun output. It must be written before the
rerun starts and must bind the evidence that makes the rerun allowed.

The packet must contain:

| Field | Required content |
|---|---|
| `packet_id` | Stable local identifier such as `semiconductor-rerun-YYYYMMDD-preflight` |
| `prepared_by` | Human owner, expected `Reed` |
| `prepared_at_utc` | Timezone-aware UTC timestamp |
| `origin_main_sha` | Full SHA from `git rev-parse origin/main` after fetch |
| `worktree_status` | `CLEAN` or explicit dirty-file list and owner |
| `source_scan_ref` | Local scan output path and `scan_hash` |
| `source_scan_status` | `CLEAN`, `REPAIR_REQUIRED`, or `DATA_BLOCKED` |
| `repair_approval_ref` | Exact Junyan approval reference when repair is required; otherwise `null` |
| `diagnostic_ref` | Local diagnostic output path and blocker codes |
| `same_day_bundle_ref` | U1/U2 bundle path, recomputed hash, `as_of`, and run identity |
| `u3_battery_ref` | U3 battery path, recomputed hash, `as_of`, and row count |
| `handoff_intent` | `STOP_BEFORE_RERUN` or `ALLOW_U1_U3_RERUN` |
| `stop_conditions` | Exact stop condition numbers triggered, or an empty list |
| `next_action` | The next human action; never a trade instruction |
| `authority` | `HUMAN_JUNYAN_ONLY`, `no_trade_flag=true`, and all machine authorities false |

The packet must not contain raw production credentials, unreviewed live database
paths, model outputs, chat history, or any field that asks an agent to decide
which securities to select. A packet that cannot name its hashes and stop
conditions is `BLOCKED`, even if the market session is urgent.

The machine-readable v0 packet builder is
`experiments/research_funnel/semiconductor_preflight_packet.py`. It assembles the
same packet from a source scan, intake diagnostic, same-day bundle artifact, and
U3 battery artifact. It recomputes artifact hashes from readable local files,
checks the target-date rows per daily source, and treats CLI-provided git facts
as equality cross-checks only. It may generate `STOP_BEFORE_RERUN` packets when
inputs are missing or pending; it must not run source repair, U1-U3, U4 selection, paper orders, or production nightly jobs.

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

```bash
cd <alpha-research-repo>
python3 experiments/research_funnel/semiconductor_evidence_diagnostic.py \
  --intake "<committed-intake-receipt.json>" \
  --output "<local-diagnostic.json>"
```

Do not run `apply`, production nightly, or feature-store live collection from
this checklist. Those require a separate Junyan approval with exact scope and
hashes.

## Pending Daily Source Retry Schedule

`SOURCE_PUBLICATION_PENDING` is a stop, not a soft warning. A rerun may not start
from a pending daily source just because an operator wants same-day output.

For daily sources such as `moneyflow_dc` and `cyq_perf`, use this retry rule
until a source-specific publication calendar exists:

1. If the first scan happens before the post-publication window, record
   `SOURCE_PUBLICATION_PENDING` and do not run U1-U3.
2. The first same-day retry window is after `17:30 Asia/Shanghai`.
3. If the source is still pending after that window, run one final same-day
   verification after `20:30 Asia/Shanghai`.
4. If the final verification is still pending, stop for that trade date and
   carry the blocker into the next operator packet.
5. A later observation without publication-time proof remains `LATE_OBSERVED`
   and cannot be treated as same-day evidence.

Quarterly or non-daily sources do not inherit this schedule. They must name their
own publication basis or stop as `DATA_BLOCKED`.

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
7. U1/U2 has no positive semiconductor channel rows, or diagnostic counts
   contradict the diagnostic's ready self-report.
8. Any U4-ready row carries an active E1 red flag.
9. Any U2 candidate lacks a same-run U3 battery row or explicit `DATA_BLOCKED`.
10. The U4-ready pool contains one or two names; legal handoff counts remain
    zero or three to five.
11. A same-day bundle or U3 battery ref is missing, unreadable, has a hash
    mismatch, or carries an `as_of` outside the target trade date.
12. `method_version`, `cohort_id`, or `causal_cluster_id` is missing from rows
    that will later be used for sample accounting.
13. Any output claims `production_authority=true`, `trade_authority=true`,
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

## Operator Packet Template

```text
SEMICONDUCTOR_RERUN_OPERATOR_PACKET_V0
PACKET_ID:
PREPARED_BY: Reed
PREPARED_AT_UTC:
ORIGIN_MAIN_SHA:
WORKTREE_STATUS: CLEAN / DIRTY_WITH_OWNER_LIST
SOURCE_SCAN_REF:
SOURCE_SCAN_HASH:
SOURCE_SCAN_STATUS: CLEAN / REPAIR_REQUIRED / DATA_BLOCKED
REPAIR_APPROVAL_REF: null / Junyan exact approval reference
DIAGNOSTIC_REF:
DIAGNOSTIC_BLOCKER_CODES:
SAME_DAY_BUNDLE_REF:
SAME_DAY_BUNDLE_HASH:
SAME_DAY_AS_OF:
SAME_DAY_RUN_ID:
U3_BATTERY_REF:
U3_BATTERY_HASH:
U3_BATTERY_AS_OF:
U3_ROW_COUNT:
HANDOFF_INTENT: STOP_BEFORE_RERUN / ALLOW_U1_U3_RERUN
STOP_CONDITIONS:
NEXT_ACTION:
AUTHORITY: HUMAN_JUNYAN_ONLY
PRODUCTION_AUTHORITY: false
TRADE_AUTHORITY: false
PAPER_ORDER_AUTHORITY: false
CLAIM_ALLOWED: false
NO_TRADE_FLAG: true
```

不是买卖指令；研究信号，human executes.
