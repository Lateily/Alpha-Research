# Runtime And Version Inventory V1

Status: IMPLEMENTED_UNTESTED. Tests are NOT_RUN by the user's explicit direction.
`collect_runtime_inventory(repository_roots, services, *, observed_at,
scheduler_timezone='Europe/London', market_timezone='Asia/Shanghai')` returns
`ar.runtime-inventory.v1` with WORKFLOW_DEBUG, PENDING and false authority labels.

At most 16 caller-provided local repository roles are inspected. Roles are short
identifiers and paths must be local, non-symlink and traversal-free. The module
uses fixed Git argv to read top-level, HEAD, branch, worktree summary and the
locally cached origin/main ref; it never fetches. No file names from status, Git
errors, environment dump, provider data or credentials enter the output.
Missing/non-repository/unavailable roots stay explicitly unavailable. HEAD is
rechecked after reads; a changed HEAD yields UNSTABLE_HEAD rather than a mixture.
Reads remain sequential local observations, not an atomic filesystem snapshot.

Git commands have three-second deadlines and a 64 KiB post-read output bound.
Global/system Git config is excluded, fsmonitor and hooks are disabled, prompts
and optional locks are off. Repositories declaring clean/process filters retain
unknown worktree status rather than running configured filter programs; submodule
worktrees are not traversed. The inventory does not modify a branch, index,
scheduler, service, database or permission. It cannot attest which binary an
already running process serves merely because a repository has that SHA.

At most 32 services may be declared with service_id, optional repository_role,
observed_state (UNKNOWN/RUNNING/STOPPED/FAILED), observed_code_sha and schedule.
A schedule contains only local_time (HH:MM) and weekdays (distinct integers 0-6).
These are caller observations, always NOT_ATTESTED. Matching caller/repository
SHAs is labeled CALLER_ASSERTED_MATCH, not a verified runtime binding. No process
list, launchctl, URL probe or runtime command is called. No next-fire calculation
or market-calendar scheduler is introduced.

The caller timestamp must carry an offset. UTC, scheduler and market views are
derived through IANA zoneinfo rules, including London summer/winter offsets;
the host clock is not changed. `observed_at` is only the caller's clock reference;
`captured_at_utc` separately records when the local reads finished. A past clock
reference does not reconstruct a historical repository or service. Source timestamps, service activity and execution
at a declared schedule remain separate facts. No personal/production paths are
hardcoded in tracked configuration.

Deferred tests cover missing/dirty/cached repos, service declarations, malformed
clocks/profiles and winter/summer conversion. Syntax checks do not prove these
behaviors and are not release acceptance.
