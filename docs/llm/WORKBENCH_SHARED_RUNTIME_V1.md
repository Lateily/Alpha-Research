# Shared Workbench V1 Operator Guide

This is S4 preparation, not a deployment or acceptance receipt. No current URL
has been swapped, no Windows acceptance is claimed, and no private entry or
production replacement is authorized here. The controller still owns final
same-HEAD full tests, remote CI, UI checks and independent whole-branch review.
The immutable [specification](../superpowers/specs/2026-10-13-shared-workbench-v1-design.md)
and [acceptance matrix](../team/SHARED_WORKBENCH_V1_ACCEPTANCE.md) remain the
approval contract, not a record of passed tests.

## Runtime And Authority

One central Mac runs the Python API, SQLite, frozen input store and two renderer
slots. Browsers do not run research engines or call market/model providers.
The host must remain awake and connected for remote access and synchronization.
There is one service lifetime lock per state root, not one service per user.
The existing production scheduler remains the sole production writer.

Verified Serve identity supplies the actor. Each actor has a persistent,
server-generated workspace ID and separate task/attempt output directories.
My Tasks filters ownership; Team Results permits both approved members to read
both users' sealed results. This is write isolation, not confidentiality from
the other approved member. Unknown historical actors remain
`LEGACY_UNATTRIBUTED`; migration does not assign them to the operator.
OWNER and MEMBER are access roles, not human approval signatures.

Shared V1 accepts only `observe` and `snapshot-brief`. Both use registered,
frozen inputs; observe does not launch collection. No scheduling, new research
engine, model/provider, paid call, arbitrary path/URL/SQL, deployment, U4, case,
paper or trading operation is granted. All new artifacts remain
`WORKFLOW_DEBUG`, `human_review=PENDING`, with production/trading authority
false. `SUCCEEDED` means verified rendering, not research quality approval.
This is not formal U4, paper or trade permission.

## Paths And Explicit Startup

All identities and paths below are placeholders. Substitute only separately
approved local configuration; never commit credentials, real member identities,
production contents or private routing configuration. Keep `RELEASE`,
`STATE_ROOT`, `SOURCE_ROOT`, backup and scratch roots separate and disjoint.
State must survive code-release replacement and must not sit inside the source
tree being observed. Do not reuse an in-use state for a fresh-state trial.

The actual entry point is `scripts/llm/nonprod_workbench.py`. The following is a
future operator example only, after explicit private shared-trial/entry approval,
on an unused loopback port and an approved clean, built release:

```bash
RELEASE=/absolute/approved/release
STATE_ROOT=/absolute/isolated/shared-state
SOURCE_ROOT=/absolute/approved/read-only-source
ALLOWLIST=/absolute/outside-repositories/private-allowlist.json
cd "$RELEASE"
AR_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/llm/nonprod_workbench.py \
  --host 127.0.0.1 --port 18766 \
  --state-root "$STATE_ROOT" \
  --private-origin https://workbench.example-tail.ts.net:8443 \
  --owner-login owner@example.invalid \
  --private-allowlist "$ALLOWLIST" \
  --shared-workspace-v1 \
  --read-only-source-root "$SOURCE_ROOT" \
  --read-only-auto-sync
```

`--shared-workspace-v1` is default-off and requires private access.
`--read-only-auto-sync` is separately default-off and requires shared mode,
private access and the fixed `--read-only-source-root`. It checks at startup
then every 60 seconds; neither browser nor HTTP can enable/configure it.
For explicit one-time import instead, omit the auto-sync flag and use
`--shared-import-once "$SOURCE_ROOT"`; that does not start a poller. Do not
confuse the legacy brief/earnings pack options with shared V1 task kinds.

The allowlist is a regular owner-UID-owned mode-0600 file outside every Git
repository, with no symlink parents, at most 4096 bytes. Shape only:
`{"members":["member@example.invalid"]}`. Do not list the owner as a member.
This guide does not grant any new membership or ACL change. The existing Serve
proxy must preserve exact external Host and trusted `Tailscale-User-Login` from
loopback. Exact Origin and identity-bound Secure/HttpOnly/SameSite cookie checks
remain required; duplicate/ambiguous headers or fields are rejected. Never
spoof identity headers, expose a public listener/Funnel, disable TLS verification,
or expand firewall/ACL rules to make a trial pass. Host administrator and
same-UID processes are trusted, not adversaries this service claims to defeat.

## Jobs And Recovery

The authenticated browser uses `POST /api/workspace/job` with exactly:

```json
{"command_id":"guide-r1-brief-001","kind":"snapshot-brief","snapshot_id":"<R1_SNAPSHOT_ID>"}
```

Replace the snapshot placeholder with a server-registered ID, not a path.
The API returns 202 with persistent `job_id`; poll
`GET /api/shared-workspace/jobs/<JOB_ID>` and the shared view at
`GET /api/shared-workspace`. The detail contains verified report/citations;
the UI downloads these bytes and the task receipt. No separate backup or cancel
HTTP endpoint is provided. Never submit actor, workspace, source, provider or
execution-code overrides. Same actor/command/content returns the original job;
changed content or another actor reusing the command ID yields 409. A reconnect
queries the original job ID, not a new submission. STOP is not revived by retry;
a deliberate new attempt needs a new command ID and retains the prior failure.

For `SUBMISSION_UNCONFIRMED`, first reconnect and use the normal GET-only
reconciliation. If delivery is still unknown, My Tasks shows each retained
command, kind and frozen snapshot with an explicit `重试原提交` action (accessible
name: `重试原提交 <original command_id>`). This action checks the current verified
workspace, then queries an accepted original or deliberately retries the exact
original command/kind/snapshot. It does not choose the newest input or mint a new
command ID. Merely reloading or reconnecting never POSTs unknown deliveries.

FIFO dispatch has at most two running slots, two unfinished jobs per actor and
20 globally; excess is 429. Each renderer has a 120-second hard deadline and
process-group cleanup, including descendants. Its environment is restricted to
local offline rendering, frozen originals and its own attempt directory, not
the source root, database or credentials. Input hash, snapshot ID, actor,
workspace, code SHA and execution-tree hash bind at enqueue and do not drift
while queued or recovering. Same input/code can produce equal report bytes
while job IDs and actor envelopes remain distinct.

An attempt seal alone is not success: it must reopen and verify before the
unique terminal database commit. Generation tokens fence late workers. On
restart, compatible QUEUED work resumes with its old binding; a complete seal
may converge without rerendering. Interrupted incomplete work gets at most
one automatic retry, two total attempts per job; another interruption stops as
`INTERRUPTED`. Missing/corrupt inputs, contradictory seals or code/schema drift
become `RECOVERY_REQUIRED`, never a run on new input/code. Old STARTED records
without sufficient binding remain `LEGACY_NOT_RECOVERABLE`, not guessed success.

Execution identity comes from committed execution files. Dirty execution code
is refused. A running process that sees a different committed execution identity
refuses new jobs with `EXECUTION_CODE_CHANGED_RESTART_REQUIRED`; restart does
not authorize recovery of an old job under incompatible code. Preserve the
original release for diagnosis; never relabel old job metadata to force replay.

## Shared Data And Quality

Common Data separates latest attempt, last published data and currently selected
frozen input. A failed newer attempt does not replace a valid old publication.
Capture verifies the scoped pointer/manifest, file hash/run/date bindings and
bundle coverage, stages originals, reopens them and rechecks the source before
registration and selection. `SourcePrefixNoFollow` means every configured root
ancestor and relative path component is opened without following symlinks
(`workbench_evidence.read_local`, `O_NOFOLLOW`); regular/readable files only,
12 MiB maximum per file. No production SQLite engine or credentials are opened.
Pointer/file changes including ABA are refusal cases, not permission to edit
the source. Unsafe diagnostic/secret-shaped content must not enter the archive.

Verification is `SCOPED_SNAPSHOT_NOT_FULL_NIGHTLY_ACCEPTANCE`, not the complete
24-step, dual-pointer, full-nightly gate. Preserve `PARTIAL`, `DATA_BLOCKED`,
`NOT_EVALUATED` and explicit Macro/Funnel/NAV gaps. COMPLETE transport or a valid
hash cannot invent missing values, source verification or issuer-original review.

The current funnel producer's `ar.research_funnel_bundle/1.0` manifest seals its
six child-file hash catalog as `bundle_hash`; the catalog deliberately excludes
the manifest itself. Intake recomputes that seal, matches the health catalog and
run/date/schema/rule identity, and retains the manifest's observed byte hash.
Its binding remains `UNBOUND`, with explicit provenance
`BUNDLE_CATALOG_BOUND_NOT_MANIFEST_BYTE_HASH`, never a fabricated byte-hash MATCH.
Only the existing four consumed child originals and manifest are frozen/reopened.
The catalog entries `all_market_scan.json` and `security_registry_projected.json`
are explicitly `unread_catalog_paths`: their bytes are not read, frozen or claimed
verified by this scoped intake. The fixed whitelist and 12 MiB file limit remain.
Legacy inputs with an explicit manifest-byte hash retain that older binding path.

Current selection persists as append-only `SHARED_INPUT_SELECTED` events by
`SYSTEM_READ_ONLY_SYNC`, bound to registered originals. Restart restores the
verified selected cursor, not the newest insertion. Identical selection adds
no event; selecting an already registered older input can add a new bound event.
Backup/restore verifies that binding. Failure keeps the last-good selected
snapshot/date visible with `SYNC_FAILED` or `CAPACITY_BLOCKED` and a safe error;
it is not current success. The UI polls every five seconds and must show stale
or disconnected status. Startup/60-second checks target visibility within
120 seconds for normal acceptance fixtures, not a proven Windows SLA. Host
sleep/offline recovery reads the latest available data with `NO_BACKFILL`; it
does not reconstruct every missed publication.

For the R1/R2 trial, record actual descriptors once and reuse their exact IDs:

| Label | Source Run / Date | Frozen Snapshot / Input Hash |
| --- | --- | --- |
| R1 | `<R1_RUN_ID>` / `<R1_TRADE_DATE>` | `<R1_SNAPSHOT_ID>` / `<R1_INPUT_HASH>` |
| R2 | `<R2_RUN_ID>` / `<R2_TRADE_DATE>` | `<R2_SNAPSHOT_ID>` / `<R2_INPUT_HASH>` |

Submit both actors' R1 jobs using the same `<R1_SNAPSHOT_ID>` and record separate
job IDs at the same `<CODE_SHA>`. When complete R2 appears, both common views
must identify the table's R2, but those queued R1 jobs must retain the table's
R1 input hash/run/date. Test dedup selection R1 -> R2 -> R1 and restart/source
failure using the same recorded IDs, not renamed or newly synthesized R1 bytes.
These are synthetic trial placeholders, not review finding IDs or evidence
that actual production/Windows acceptance occurred.

The 100-observation/frozen-history gates count linked identities once and include
failed, staged and orphan evidence. Audit capacity is 10000 append-only events;
accepted jobs reserve terminal slots so sync/login cannot spend them. On reaching
capacity, stop new work/imports with explicit errors; never delete history or
silently raise limits. At reserved/full event capacity, a verified entry page
can still renew its cookie without appending a login event and reports
`EVENT_CAPACITY_EXHAUSTED` via login audit. Read-only access is not extra task
capacity. Expansion/archive is a separately reviewed migration.

## Stop, Backup And Scratch Restore

`nonprod_workbench.service_lock()` holds `service.lock` for the service lifetime.
`ReadOnlySync.start()` separately holds an exclusive nonblocking flock on
`read-only-sync.lock`; a second poller is refused. The presence of a lock file
alone is not an active lease; do not unlink it to bypass a running holder.
Graceful foreground Ctrl-C takes the actual `finally` path: stop new worker
claims, join workers, stop/join the sync poller, close the server, then release
the lifetime lock. `SharedWorker.stop()` drains current bounded attempts; it is
not immediate job cancellation. `ReadOnlySync.stop()` waits for any in-progress
tick and then releases its lease. Forced termination is crash recovery, not a
graceful backup procedure. Do not infer a SIGTERM drain contract from Ctrl-C.

For an authorized state operation, first stop the isolated service gracefully
and confirm it exited, with no active worker/poller or other state writers.
Do not restart until backup completes. The backup API does not acquire either
lifetime lease, stop the service, or stop synchronization. Its
`sqlite_snapshot()` uses `BEGIN IMMEDIATE` to freeze cooperative SQLite writers,
then SQLite's backup API (including WAL) into an integrity-checked image.
Worker terminal commits can wait/retry while that writer lock is held; file
capture outside the database is not globally frozen by it. Quiescing prevents
those races. Technical lock files are intentionally excluded from the archive.

There is no backup/restore CLI in this release. Run the actual Python functions
from the approved release, against the stopped isolated state only:

```python
import sys
from pathlib import Path
sys.path.insert(0, "/absolute/approved/release/scripts/llm")
from nonprod_workbench import Store
from workbench_backup import backup_shared, verify_shared, restore_shared

state = Path("/absolute/isolated/shared-state")
archive = Path("/absolute/archives/new-complete-backup")
scratch = Path("/absolute/scratch/new-restore")
receipt = backup_shared(Store(state, shared_v1=True), archive)
manifest = verify_shared(archive)
restored = restore_shared(archive, scratch)
assert receipt["status"] == "LOCAL_SHARED_BACKUP_VERIFIED"
assert manifest["integrity_check"] == "ok"
assert restored["status"] == "LOCAL_SHARED_RESTORE_VERIFIED"
```

Targets must be new, disjoint, non-symlink paths, never live state or an existing
backup. `backup_shared` validates fixed tables, audit chain/tail/counts, all safe
isolated artifact roots (including STOP/STARTED/orphans and migration history),
frozen inputs, job output seals and selected-cursor binding. It writes a hashed
manifest, verifies it and automatically performs an additional temporary scratch
restore. Archive inventory must be `ISOLATED_STATE_ARTIFACT_ROOTS`. Credentials,
owner secrets, allowlist/cookies, raw SQLite/WAL and technical leases are not
exported; do not substitute a filesystem copy of a live SQLite file.

Retain worker crash files: only `.write-<32 lowercase hex>.partial` directly in
`shared-jobs/<workspace UUID>/<job UUID>/attempts/<attempt UUID>/` is recognized
as worker temporary evidence. The inventory lists these under `recovery_evidence`;
backup and scratch restore preserve their exact bytes, including empty or
incomplete writes, with normal type/no-follow/size/credential checks. Other dot
paths still require review. Do not delete partials to make a backup pass.

For an approved legacy migration, replace `Store(state, shared_v1=True)` above
with `Store(legacy_state)` for old local storage, or use `shared_v1=True` only
with the exact compatible S1 release for an S1 store. Do not open old storage
with new shared flags expecting implicit migration. Then use the actual API:

```python
from workbench_shared_state import migrate_legacy
migration = migrate_legacy(archive, Path("/absolute/isolated/new-migrated-state"))
assert migration["status"] == "SHARED_MIGRATION_VERIFIED"
```

The latest `backup_shared` can inventory supported source schemas through a
compatible Store. Migration accepts complete archives only; successful-only
legacy exports cannot prove orphan/history completeness and are refused.
`restore_shared` delegates to `migrate_legacy`, preserving original audit bytes,
unknown actors and old artifacts in new storage
`ar.shared-workspace-storage.v2`. Interrupted staging remains bound to the same
backup hash; retry `migrate_legacy` with that exact archive/target for validated
convergence. Do not use `restore_shared` on an already-existing scratch path,
remove staging, mix archives or manually repair/reseal contradictory evidence.
Escalate corruption for review. No migration source or prior output is overwritten.

## Rollback And Separate Acceptance

Keep the original release, original isolated state and complete verified archive
intact. Old binaries must refuse new shared storage/schema; UI rollback is not
storage downgrade. Do not restore an old backup over newly accepted tasks.
Rollback requires a separately approved, compatible release/state pairing in a
new root, while preserving and inventorying every later task/output and its
failed evidence. Repointing an entry is a separate operator approval, not an
automatic fallback. Restored credentials/access configuration need separate
approved provisioning; they do not come from the archive.

Before any private entry switch, require explicit approval plus controller
evidence at the same final HEAD: complete offline/regression/mutation gates,
all remote required Python/UI checks, independent review, and fresh-state local
UI at 1440/768/375/320. Prepare verified backup/scratch restore and rollback
pairing without touching the old service. Then obtain separately approved shared
trial deployment and actual two-device D01-D07 receipts: distinct approved
actors/jobs, matching code and R1/R2 descriptors, both independently recomputed
download hashes, Windows reconnect to the original job, new real-publication
visibility, source read-only proof and prior-output preservation. Do not fill
Windows receipts from two Mac browsers or synthetic fixtures. Report code,
LOCAL_QA, TWO_DEVICE_PENDING, SHARED_DEPLOYMENT and PRODUCTION_AUTHORITY
separately; none implies formal U4/paper/research or trading approval.
