# Runtime And Publication Source Closeout V1

Implements Junyan's 2026-11-04 request. Existing production, the running private
workbench, Tailscale and GitHub schedules are forbidden operational targets.
The previously approved foundation blueprint and project overview are the scope.
The user has opted out of another design-question round: preserve Python,
SQLite, Vite assets and the existing persistent shared queue.

## Responsibilities

The Mac nightly publisher owns formal model snapshots under public/data/v2 and
their pointer/manifest/run bindings. The latest attempt is not the publication.
GitHub daily-market-data owns a separate review branch, not the formal snapshot;
its workflow success and unmerged data never replace a nightly publication.
The shared workbench is a read-only consumer and isolated task/output owner.
Research and candidate branches do not acquire publication or trading authority.
This policy is enforced by a closed source-selection function, not a new writer.
No existing scheduled workflow, collector or publication guard is changed.

Version inventory compares each role with its own explicitly expected version;
intentional isolation is not repaired by making every directory the same SHA.
Missing, dirty, mismatched and merely caller-asserted observations remain distinct.
Local cached refs are not fresh remote evidence. A policy match is not installed
runtime, successful nightly execution, research readiness or release approval.

## Runtime

Use a new CPython 3.12 virtual environment with system-site-packages disabled.
Keep the current pypdf 6.10.0 version; bind its wheel and the pip bootstrap wheel
to independent SHA256 values. Builds use only a prepopulated wheelhouse, no index,
no dependency resolution, no inherited provider secrets or Python paths. Do not
reuse the historical validation venv. A fresh interpreter installation remains
an explicit host prerequisite; the environment is not a bundled OS or Python.

Never replace an existing environment. A failed build remains inspectable and
cannot be accepted without its final manifest. Verify an independently supplied
manifest pin, exact environment inventory and base interpreter before execution.
Two clean builds need equivalent interpreter/dependency identities, not identical
absolute-path-bearing venv bytes. Do not delete failed evidence or history.

## Isolated Service And Recovery

The new launcher is operator CLI only, not an HTTP endpoint. Its closed profile
is independently pinned, code/environment/assets are rechecked before every
start, and roots are private, disjoint and explicit. It starts only the existing
nonprod shared workbench on loopback in the reserved 18000-18999 test range.
Use synthetic example.com actors and a synthetic ts.net origin; no real member
allowlist, production source, automatic synchronizer, provider or formal ledger.
The launcher can signal only children it created, never a caller-supplied PID.

A foreground supervisor holds an exclusive lock, bounds unexpected restarts to
two, and records immutable bounded lifecycle receipts. Its own termination stops
its child and preserves state. Restart reuses the same state and existing queue
recovery; completed output seals and identity/input ownership remain unchanged.
Prepare a launchd template for this isolated profile only; do not load it. Process
restart and a simulated cold supervisor restart are not a physical Mac reboot.

## Choices And Non-goals

Chosen: additive policy/role inventory, offline pinned environment and bounded
isolated supervisor. Rewriting the workbench/queue or moving production now would
expand scope and invalidate the already accepted service. Merely updating prose
would not prove rebuilding or persistence, so actual isolated restarts are required.

No merge, push, production synchronization, shared rollout, external data upload,
market/model request, methodology change, new research workflow or source license.
Private real two-computer acceptance remains deferred. This work may prepare a
later deployment but cannot claim it occurred.

## Acceptance

Normal, missing, conflicting and historical contracts at real CLI/API boundaries;
legacy data refused as formal source; stale/cross-run/hash failures retained;
wrong pins, modified environments/assets, unsafe roots and duplicate supervisors
refused. Build twice offline; start the actual shared server in the new runtime,
submit a synthetic frozen-input job, kill its own child, recover and requery the
same job/workspace/output hash, then cold-restart the supervisor and requery.
Cover retained RUNNING recovery through the existing queue, bounded crash loops,
clean shutdown and original-state preservation. A generated template is not an
installed service. Freeze one final SHA; full offline CI, all behavior mutations,
fresh nonauthor review and the isolated lifecycle receipt must name that SHA.
