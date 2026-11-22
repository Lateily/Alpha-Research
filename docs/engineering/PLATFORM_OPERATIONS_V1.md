# Platform Operations v1

Baseline: a57be7b. Scope: isolated preparation and rehearsal, not deployment.

## Approved boundary

Reuse Python, SQLite, the existing sealed shared-backup format and the existing
isolated recovery verifier. Do not change the running private service, production,
the 15000ms UI guard, hash/seal/rights checks or old 300-second recovery commands.
No installation, sleep, reboot, ingress changes or real notification calls.

## Runtime

A new operator module supervises only the verified recovery-child that it
creates. It holds the existing capsule supervisor lock and a separate durable
operations journal. Every attempt is reserved durably before Popen. Two
unexpected restarts are permitted, including across operator crashes; success
does not silently reset the budget. Abandoned reservations are counted as
crashes. A stopped/fenced operator never authorizes another process takeover.
Signals target only the retained Popen child. The old stop/drain behavior is
reused; this is not the separately approved #411 nightly timeout mechanism.

The operator writes a launchd template only. A user LaunchAgent starts after
login, not before login. System-daemon deployment, a dedicated non-admin user,
FileVault unlock, power/network policy and physical reboot need field approval.
Persistent fencing prevents launchd from clearing a crash loop by relaunching.
Generated templates and cold process recovery are not startup attestation.

## Retention and rollback

Use existing consistent SQLite/WAL export, chunked backup, manifest/artifact
checks and new-root restore. A rehearsal takes the capsule lock and refuses an
active owned generation. Restore the newest archive into a new root and verify
all tables, events and original artifacts. Do not overwrite or prune history;
do not restore credentials. Code/environment/source/library resources remain
separately pinned prerequisites, not implicitly included in the state archive.
Actual rollback needs fence/drain, stopped-writer proof, a new stopped-latest
backup, old-code compatibility verification and only then an approved switch.

## Observation and alerts

A separate offline observer journal validates ordered heartbeat sequences,
source/observer identities and time bounds. After 300 seconds without a valid
heartbeat it queues an idempotent loss alert. Health failures queue a separate
safe code; no report/source text, token, raw exception or URL enters alerts.
An outbox entry is not phone delivery or human acknowledgement. A channel receipt
and subsequent named acknowledgement are separate records. Local simulations
cannot assert external-host detection. Polling cadence is 60 seconds; mobile
delivery, on-call primary/backup and escalation remain pending confirmation.
No network sender is implemented or invoked before the channel is approved.

## Field gates

The companion field checklist distinguishes software rehearsal from host startup,
two-human operation, mobile delivery, independent recovery and uninterrupted
24-hour observation. Missing evidence stays PENDING/NOT_ATTESTED. A caller's
username or a prepared approval template is never approval. Research remains
WORKFLOW_DEBUG/DATA_BLOCKED/PENDING where applicable; no trading authority.

Report labels: model=Codex; prompt_version=platform-operations-20261122.v1;
evidence_grade=engineering preparation, not field or research approval.
