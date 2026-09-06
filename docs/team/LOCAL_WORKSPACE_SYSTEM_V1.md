# AR Local Workspace System V1

Status: LOCAL_NONPRODUCTION / WORKFLOW_DEBUG. This is not a cloud deployment or a
replacement for the production nightly writer. Final authority remains Junyan.

## What Exists

The workbench is a local Python service and a built React interface. GitHub keeps
source/review history; it is not needed to execute an installed local release.
There is no required cloud subscription, model payment, or external database.

```text
Browser on the owner's Mac
  -> loopback HTTP service, exact Host/Origin/session checks
     -> workspace command service
        -> SQLite: append-only events, revisions, observations, job receipts
        -> fixed offline research child process
           -> U1-U4 / closure / paper engine / five-axis / review artifacts
        -> fixed local evidence reader
           -> existing AR public contracts, read-only
        -> local periodic scheduler, disabled plans until owner enables them
        -> private backup + fresh-directory restore verification
```

The new state directory should be separate from the code release and from the
old production root. One process owns a state directory, enforced by a lifetime
flock. Two computers must not share this SQLite file through file synchronization.
Remote/team access is deliberately disabled, not simulated by a role dropdown.

## Screens

| Screen | Actual functionality | Important boundary |
| --- | --- | --- |
| Research overview | Last observed publication, latest attempted nightly, freshness, review queue, audit events | A successful old publication cannot hide a newer failed attempt |
| Nightly and schedules | Read-only step status; offline observe/check/replay/backup jobs; persisted paused/enabled schedules | Does not run the old nightly writer or live collectors |
| Macro and data | CN/US four-axis source contracts, missing files, legacy context separately, semiconductor input health | CALIBRATING; no formal blocking or trading authority |
| Models and methods | Actual engine file hashes and the existing 23 reviewed knowledge cards, collector coverage | REVIEWED is not VALIDATED; no autonomous rule promotion |
| Candidate evidence | Search/filter/paginate actual candidate and exclusion rows; export observations | Not a recommendation or U4 selection interface |
| Research drafts | Human-authored thesis, valuation, timing, invalidation, sources; version history | Does not invent research or replace the sealed-case qualification contract |
| Submission and review | Freeze a draft; accept, reject, or request changes for an exact revision/hash | Local document review is not formal U4/paper-registration approval |
| Paper and attribution | Historical NAV, positions/trades, actual isolated engine replay | Historical orders retain their eligibility flags; no performance claim |
| Data and audit | Source hashes/gaps, event history, integrity checks, exports, backup/restore receipts | Hash chains are not tamper-proof against a host administrator |
| DeepSeek and deployment | Existing fixed offline stub, draft configuration, cutover checklist | No provider contacted, no account provisioned, no team grants |

## Start Locally

The currently supported server hosts are macOS and Linux with Python 3.11+.
Windows team access will use a separately authorized private browser endpoint;
this POSIX/flock server is not advertised as a native Windows deployment.

Build in the code checkout, using its installed Node dependencies:

```sh
node node_modules/vite/bin/vite.js build --config tools/nonprod_workbench/vite.config.js
```

Run from an accepted code release. Choose a dedicated, private local state path:

```sh
python3 -B scripts/llm/nonprod_workbench.py \
  --port 8768 \
  --state-root /absolute/nonproduction-runtime/state \
  --read-only-source-root /absolute/old-ar-root
```

The source argument is optional. Without it, evidence jobs stop with
`READ_ONLY_SOURCE_NOT_CONFIGURED`; no sample production data is substituted.
The browser cannot supply filesystem paths, shell commands, provider URLs, API
keys, or arbitrary replay drafts. Source/state overlap is rejected before the
state constructor writes anything. Never expose this server via a public proxy,
port forward, LAN bind, or tunnel.

## Owner's First Session

1. Open the loopback URL and inspect the overview.
2. Read the local artifacts. Check the data date, latest attempt, missing files,
   and per-file hash bindings. A snapshot is observation, not publication approval.
3. Set a unique local administrator password in Submission and Review. The human
   sets it; the agent must not choose or register a password for the real workspace.
4. Create a human research draft. Blank fields may be saved but not submitted.
   `WAIT`, unknown evidence, and the human's decision not to proceed remain valid
   content; the workbench does not supply investment judgments.
5. Submit the saved version. Review with the local password and a reason.
   A submitted or accepted version is frozen; a changes-requested version may
   receive a new revision. All previous revisions and rejections remain recorded.
6. Create a paused plan. Enter the local password again to enable it. Start with
   local observation/integrity checks; fixed replay is synthetic, not a new
   prospective research sample.
7. Run Backup and Restore Check. Keep the private backup directory and its hash.

The password is stored as a salted PBKDF2-SHA256 derivation, never plaintext.
Five failed local review authentications in five minutes are rate-limited in
the service process. This identifies a local account, not Junyan's legal identity.
First-owner setup trusts possession of the machine; it is not suitable for a
shared unauthenticated server. No recovery/backdoor endpoint resets the owner.

## Data Semantics

Source reads are a fixed allowlist: the current public pointer, its declared
manifest, versioned public products, a bound dated/run-specific funnel directory,
and a projection of the nightly report. No environment file, raw provider
response, token, or unrestricted path is read. Every path component is opened
without following links. Files are size-bounded; duplicate keys and nonfinite
JSON values are refused. The pointer is reread after capture to reject a concurrent
publication switch.

The observation contains actual byte hashes and binding status. It is **not** the
platform's full `verify_committed_publication` acceptance. Missing manifests,
unbound files, and mismatches stay visible. The UI's calendar freshness threshold
is three days, in the operational +08:00 timezone; it does not pretend to be a
trading-session calendar or endpoint-specific macro freshness model.

Nightly stdout/tails are not retained because they can contain sensitive text.
Only explicit operational fields are copied. Observation records become visible
as latest only after their job's successful completion event. A process crash
after writing an observation does not silently promote an orphan.

## Jobs And Recovery

The job allowlist is `observe`, `integrity`, `research-replay`, `backup`.
There is no live-provider, production-nightly, generic-shell, grant-team, register,
or paid-inference route. Schedules persist as events with optimistic revisions.
Claims are transactional and unique per schedule revision/time slot. A pause or
revision change is rechecked inside the claim transaction. Missed slots are not
backfilled in a burst; at most the current slot is considered after restarting.

Jobs have `STARTED -> SUCCEEDED | STOP` events. An interrupted `STARTED` job is
not automatically retried. Its status remains visible for manual investigation;
retrying its command ID returns the original claim instead of executing twice.
The operator can deliberately create a new command after examining old artifacts.
Replay directories are immutable and capped by the existing replay service.

The scheduler lives in the Python process. Closing it, powering off, or putting
the laptop to sleep stops scheduling. No launchd job, autostart, always-on cloud
machine, or 24-hour availability is claimed or installed by this change.

## Backup Scope

Backups contain all workspace data tables and completed replay files, with a
sealed file catalog. No SQL text is executed on restore. The verification creates
a fresh temporary state directory, inserts parameterized rows into fixed tables,
restores artifacts, and reruns integrity checks. Existing restore destinations
are refused. The backup is retained, while the scratch restore is discarded.

Local account credentials are intentionally excluded. A future authorized live
restore must establish the owner's credentials separately. A backup is a
point-in-time snapshot: its own still-running backup job can appear as STARTED.
It does not claim to have captured its later completion event. Backups and data
exports are private; they are not cloud uploads or team shares.

Bounds: 10,000 workspace events, 100 observation records, 30 backup directories,
12 MiB per source/export file, and the existing 100 replay-directory cap. Reaching
a bound produces a visible refusal. Nothing silently rotates/deletes research
history. Export/retention policy changes require a separate reviewed operation.

## Accepted Direction And Remaining Gates

Alibaba is the approved eventual carrier; `cn-hongkong` is approved for
nonproduction network/data-license validation only. This local phase has a zero
new cloud/model spend ceiling, no production transfer destination, and no resource
purchase. It can run before paying for cloud storage.

The following are not completed by a local UI:

- Live data collection and production nightly cutover, with secret injection,
  provider allowlists, network/data-license tests and explicit operational approval.
- Private team identity, member roles, remote access and authenticated Junyan
  approval integration. Team grants remain empty until the human assigns them.
- Formal U4/registered paper bridge from this interface. The existing specialized
  contracts remain authoritative; local draft acceptance cannot bypass them.
- Cloud service/worker deployment, heartbeat alerts, externally anchored audit
  storage, disaster recovery, and autonomous availability independent of a laptop.
- Paid DeepSeek inference. The configured adapter is exercised only with its fixed
  offline completion stub. Prompt/model/cost provenance must be retained when a
  separately approved live provider route is added.

These are explicit next deployment gates, not missing buttons to be enabled by
changing frontend state. Existing production writers were not stopped or changed.

## Acceptance

Run the actual offline suites and mutation gate before a Draft PR:

```sh
python3 tests/test_workbench_workspace.py
python3 tests/test_nonprod_workbench.py
python3 tests/test_workbench_research.py
python3 scripts/governance_mutation_gate.py
python3 /Users/years/Desktop/Stock/e2e-twin/twin-20260902/tools/ci_local.py
```

Browser acceptance uses a disposable state directory, not the human's account:
real read-only snapshot, stale/failed-run distinction, 24-step observation,
candidate filtering, save/submit/freeze, wrong password refusal,
changes-requested/revise/resubmit/accept, paused schedule, historical chart pixels,
audit download, reload persistence, and desktop/mobile overflow checks.

不是买卖指令;研究信号,human executes.
