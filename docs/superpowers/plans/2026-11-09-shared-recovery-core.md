# Shared Recovery Core Implementation

Base: dca5b6807e7f5eedcd947d77a5c3e5e3e8dbad4e.
Spec: docs/engineering/SHARED_RECOVERY_CORE_V1.md.
Execution: inline implementation, one fresh nonauthor whole-branch review.

## Task 1: Pinned restore capsule

Add scripts/llm/workbench_recovery.py and tests/test_workbench_recovery.py.
Interface: prepare(root, backup_root, backup_hash, code_root, environment_root,
environment_hash, port, *, source_root=None, library_root=None, library_hash=None).
Output: profile.json/external profile_hash, restoration receipt, fixed allowlist,
NOT_INSTALLED launchd template. Verify source backup before creating root;
restore_shared into root/state; use existing committed-byte/runtime/asset checks.
No existing file is overwritten. Unknown profile fields and resource mismatches
fail. Test valid restore and external-pin rejection RED then GREEN; add path,
pin, field, resource and credential counterexamples.

## Task 2: Full isolated service lifecycle

Extend only the trusted operator CLI with recovery-prepare/recovery-verify/
recovery-serve/recovery-child. Original runtime commands/guards remain unchanged.
New supervisor uses exact capsule-generated arguments, exclusive ownership lock,
max two unexpected restarts, 300-second maximum and own-child stop/parent watcher.
Reverify immutable pins at each start. Add and watch failing boundary tests,
then run the targeted original and new runtime/backup/queue suites.

## Task 3: Freeze and demonstrate

Add behavior mutations without modifying existing records; wire focused tests
into offline CI. Commit one candidate. In a new private scratch root restore the
existing c4db2102... backup, build/reuse a verified independent runtime, bind
frozen resources, and demonstrate original jobs/hash/seal retention plus actual
isolated process restart and a safe interrupted-attempt fixture. Preserve all
failed attempts. Run complete same-SHA offline CI/mutations; fresh nonauthor
review the whole delta and revalidate fixes on the final SHA. No live rollout.

## Review Focus

- Pin check must precede destination or credential creation.
- Restore verification must not reject legitimately evolving state or accept a
  forged restoration receipt.
- Resource directories cannot alias code/environment/state/backup or hide files.
- Rehearsal must never signal a PID it did not spawn or use existing live ports.
- New CLI/profile must not provide arbitrary subprocess flags or widen v1 guards.
