# Isolated Runtime And Source Operator V1

No step below updates production, shared8443, Tailscale, schedules or real access.
Do not use a live state directory, change this profile to real identities, or
install its launchd template. This version is deliberately a bounded test runner,
not the approved replacement for the current shared service.

## Publication And Versions

`config/publication-authority.v1.json` is the fixed source policy. Formal model
snapshots come from Mac nightly `public/data/v2/current_run.json`; the old
`automation/daily-market-data` GitHub branch is review data only. The workbench
consumes publications and owns isolated tasks, never the formal publisher.
Latest attempt, last publication and displayed snapshot remain separate IDs.
No old workflow is disabled by this change. Its eventual retirement needs a
separate approved operational change after reconciliation of retained data.

Use `foundation_cli.py control --request <absolute JSON>` with
`expected_versions` (main/production/shared/candidate/github_legacy SHA per role)
and `observations` (role/code_sha/dirty/scope). Scope is LOCAL_DIRECTORY,
REMOTE_REF or CALLER_ASSERTED. The command evaluates supplied observations;
it does not fetch GitHub or remotely attest a process. Cached refs must not be
labelled fresh remote observations. MATCH_METADATA_ONLY is not runtime approval.

## Rebuild

Host prerequisite: independently installed CPython3.12 and `/usr/bin/git`.
No old project venv is a prerequisite. Obtain the two exact official wheels
listed in `config/shared-runtime.lock.json` and independently check their hashes.
Package provisioning is separate; the builder has no download path or index.

```sh
<host-python3.12> -I -B <code>/scripts/llm/workbench_runtime.py build \
  --root <new-runtime-directory> --wheelhouse <verified-wheelhouse>
```

Retain returned runtime_hash outside that directory. Build again in another new
root; compare interpreter version, lock_hash and dependencies. Venv paths differ,
so tree hashes need not match. The builder copies verified wheel bytes privately,
uses no system-site-packages and never overwrites an existing root. An interrupted
build has no final runtime.json and is not accepted. Preserve failures for review.
Manifest covers exact files/modes including any bytecode; unknown files fail.
Host stdlib/OS remain prerequisites, not a bundled or cross-OS image.

## Isolated Start And Recovery

Build the existing workbench assets with the repository's pinned Node toolchain.
Commit a clean candidate before preparing a profile. Use a new private directory
outside all code/environment directories and outside any Git checkout.

```sh
<host-python3.12> -I -B <code>/scripts/llm/workbench_runtime.py prepare \
  --root <new-profile-directory> --code <clean-candidate> \
  --environment <new-runtime-directory> --environment-pin <runtime_hash> --port 18341
<new-runtime-directory>/venv/bin/python3 -I -B <code>/scripts/llm/workbench_runtime.py verify \
  --profile <new-profile-directory>/profile.json --pin <profile_hash>
<new-runtime-directory>/venv/bin/python3 -I -B <code>/scripts/llm/workbench_runtime.py serve \
  --profile <new-profile-directory>/profile.json --pin <profile_hash> --seconds 300
```

The synthetic HTTPS origin is only a header contract in a loopback test. It is
not a working Tailscale URL or real remote access proof. Only synthetic
owner@example.com/member@example.com are accepted. No production source, library,
auto-sync, provider or arbitrary command flags exist. The supervisor rechecks
code/environment/assets and fixed allowlist before every start, holds a lifetime
lock, writes new lifecycle events, and bounds unexpected restarts to2. Failed
children exhausted of retries return a failing CLI status. Each invocation lasts
at most300seconds plus bounded owned-child shutdown; this is not 24/7 operation.

Stop with Ctrl-C or signal only the supervisor process returned by your own
launcher. Do not infer authority from a PID in an old receipt. The supervisor
signals only its own Popen child; an orphan child notices parent loss and exits.
Job workers retain their existing120second deadline and token/seal recovery.
Restart using the same pinned profile to preserve state and completed outputs.
A duplicate supervisor is refused; no automatic live takeover or force-unlock.

`launchd.NOT_INSTALLED.plist` is an inspectable isolated template only. It has not
been loaded and is not a production reboot policy. A process crash/cold supervisor
restart is not a physical host reboot, outage tolerance or two-computer acceptance.

## Required Evidence

Keep candidate SHA; independent runtime/profile pins; two clean build receipts;
same-job workspace/input/output/seal comparisons after owned-child and supervisor
restart; retained RUNNING task recovery; duplicate/changed-code/asset refusal;
full same-HEAD local CI, all behavior mutations and fresh nonauthor review.
Record original production/shared identities unchanged. Remote CI, merging,
shared cutover, host reboot and human research approval require separate evidence.
