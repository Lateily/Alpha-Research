# Runtime Source Closeout Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans in this session, followed by one fresh nonauthor whole-branch review. Steps use checkbox syntax for tracking.

**Goal:** Prove publication-source separation, independent offline environment rebuilding and persistent service recovery in isolation only.

**Architecture:** Add closed policy and role-version reconciliation beside existing foundation inventory. Build a sealed private venv from pinned official wheels; an operator-only bounded supervisor starts only the existing shared server with synthetic identities and state on a reserved loopback port. Reuse the existing queue, rendering and recovery semantics unchanged.

**Tech Stack:** CPython 3.12, stdlib venv/subprocess/SQLite, pypdf 6.10.0, official pip 25.0.1 wheel bootstrap, existing Vite assets.

**Spec:** `docs/engineering/RUNTIME_SOURCE_CLOSEOUT_V1.md`.

## Global Constraints

- Production, current shared service/state, Tailscale, real allowlist and scheduled GitHub workflows remain untouched.
- No merge, push, provider/market request or trading/research approval.
- Package provisioning may read exact official PyPI metadata/wheels; all builds and runtime checks are offline.
- New runtime/profile roots only; no deletion, global upgrade, unbounded retry or arbitrary shell/command.
- Preserve old evidence and v1 contracts. Shared source remains 1a9f46d until separately approved.

## Review Focus

- Resealed policy or stale version metadata must not promote the legacy pipeline to formal publication.
- Caller-resealed environment/profile cannot bypass independently retained hashes or a changed wheel/binary/file set.
- Build or start interruption leaves explicit incomplete evidence, never overwrites an old environment.
- Unexpected child death and cold supervisor restart preserve task ownership/input/result seals; only owned children may be signalled.
- Dirty code, changed assets, foreign state/ports, duplicate supervisors and crash loops fail boundedly without touching active services.

## Task 1 Publication Responsibilities And Version Matrix

Files: create `config/publication-authority.v1.json`, `scripts/llm/foundation_control.py`, `tests/test_foundation_control.py`; extend existing `foundation_cli.py` with read-only `control`.

Interface: `load_policy(path=None)`, `select_publication(source_id, role, policy=None)`, `reconcile_versions(policy, observations)`; closed roles and exact identity/hash metadata, no runtime/acceptance promotion.

- [x] Write real CLI/unit cases: formal-nightly accepted only for its fixed role, GitHub/unknown refused, source-role substitution and resealed policy rejected; separate expected SHAs permit intentional isolation, missing/dirty/current-vs-cached stay visible.
- [x] Run RED, implement minimal parser/projection and CLI, run GREEN and adjacent foundation tests.
- [x] Register behavior mutations for policy promotion, version drift and missing evidence. Commit all additive runtime/CI wiring together as a coherent candidate; mutation execution remains a final gate below.

## Task 2 Independent Offline Runtime Environment

Files: create `config/shared-runtime.lock.json`, `scripts/llm/workbench_runtime_env.py`, `tests/test_workbench_runtime_env.py`.

Interface: `load_lock()`, `build_environment(destination, wheelhouse)`, `verify_environment(root, expected_hash)`; fixed CPython/pypdf/bootstrap identities, exclusive new root, final externally pinned manifest and exact inventory.

- [x] Write RED cases for wrong/missing wheel, self-resealed manifest, modified/extra files, symlinks/overlap/existing root and interrupted build. Only known official wheels may be executed.
- [x] Implement offline venv-without-pip plus verified pip-wheel bootstrap, fixed no-index/no-deps/hash-only install; minimal environment, bounded commands, no cleanup of failed output.
- [ ] Run GREEN and behavior mutation proofs. Rebuild twice in scratch during final operation; compare dependency/interpreter equivalence, not absolute-path-specific tree hashes.
- [ ] Commit module/lock/tests.

## Task 3 Isolated Supervisor And Full Acceptance

Files: create `scripts/llm/workbench_runtime_service.py`, `scripts/llm/workbench_runtime.py`, `tests/test_workbench_runtime_service.py`, `docs/engineering/RUNTIME_SOURCE_RUNBOOK_V1.md`; extend Python CI, mutation gate and task fixture.

Interface: `prepare_profile(workspace, code_root, environment_hash, port)`, `verify_profile(profile_path, expected_hash)`, `serve_profile(profile_path, expected_hash)`; all write roots under one new private workspace, fixed synthetic actors/origin, no production source/sync. Fixed loopback ports18000-18999; maximum2 unexpected restarts; exclusive lifetime lock; immutable lifecycle receipts. Generate, never load, a launchd template.

- [x] RED cases for profile tampering, changed code/assets/env, unsafe roots or real identities/ports, arbitrary arguments and duplicate supervisor. Actual subprocess operation remains the next gate.
- [x] Implement fixed argv/env, pre-start revalidation, existing queue recovery and bounded lifecycle. No new workbench/queue hooks or job kinds.
- [ ] Commit candidate, then run actual new-runtime synthetic shared server: frozen input → task → sealed output; owned child crash → same task/output; cold supervisor restart → same workspace and retained pending-task recovery. Preserve source/old runtime inventories.
- [ ] Freeze final HEAD; run complete local offline CI, all behavior mutations and fresh independent whole-branch review. Any fix changes HEAD and requires final evidence again. Do not merge, push or deploy.
- [ ] Save final operation, review and acceptance receipts with limits: synthetic/isolated, not physical reboot, real two-machine or production acceptance.
