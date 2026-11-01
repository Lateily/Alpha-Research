# Foundation Wave 2 Implementation Plan

**Goal:** Continue the approved F/D/P platform foundation in parallel while
preserving the accepted B6 commit. User explicitly deferred test execution until
the foundation is integrated. This batch is IMPLEMENTED_UNTESTED, never PASS.

**Architecture:** Reuse Python, the existing verified shared backup and existing
job boundaries. Three new modules have disjoint ownership; the coordinator adds
one offline CLI and future CI registration. No new database, provider, service or
runtime whitelist is introduced.

**Spec:** Approved AR_ENGINEERING_BLUEPRINT_20261101_V0_1.md, F01/F04, P01, D05/F05.
Source base: 99155bd034811b6c7fa3ddf517b1a7a89ae210e6.

## Global Constraints

- OFFLINE, no provider calls, no production/current service/state edits.
- No test, mutation, build, browser or new-feature execution this batch. Writing
  deferred tests is allowed; only syntax/JSON/diff static checks are performed.
- No push, merge, deployment, new permissions, scheduler changes or deletion.
- Preserve existing hashes, seals, identity, queue and approval boundaries.
- Existing profiles stay two slots/per-actor two/global twenty/120s/two attempts.
- Current shared job whitelist remains observe + snapshot-brief. A catalog entry
  does not grant execution authority or turn disabled research workflows on.
- No new research strategy, real market data, minute/news collection or model API.
- Unknown facts stay unknown. Cached Git refs are not fetched remote facts;
  repository SHA is not proof of the process currently serving that code.

## Shared Contracts

All outputs carry schema, sample_purpose=WORKFLOW_DEBUG, testing_status=NOT_RUN,
human_review=PENDING, production_authority=false and trading_authority=false.
Runtime inventory is read-only. Workflow catalog is descriptive, not dispatch
authority. Retention pins refer to an independently expected verified backup;
they neither alter old artifacts nor attest source rights or off-machine storage.

## Parallel Packages

### F: Runtime And Version Inventory

Files: scripts/llm/foundation_runtime.py, tests/test_foundation_runtime.py,
docs/engineering/FOUNDATION_RUNTIME_V1.md.

Interface: collect_runtime_inventory(repository_roots: dict, services: list, *,
observed_at: str, scheduler_timezone='Europe/London', market_timezone='Asia/Shanghai').
Return ar.runtime-inventory.v1. Read local Git SHA/branch/dirty metadata only via
fixed subprocess argv. Missing roots/refs remain explicit. No fetch, launchctl,
process mutation, environment dump or secret reads. Service observations are
caller-supplied and NOT_ATTESTED; market/scheduler clocks remain distinct and use
IANA zones/DST rather than fixed offsets. No production paths in tracked config.

Deferred tests: missing repo, dirty state, cached refs, unobserved service,
London winter/summer conversion, malformed time/zone input.

### P: Declarative Workflow Catalog

Files: scripts/llm/foundation_workflows.py, config/workflow-catalog.v1.json,
tests/test_foundation_workflows.py, docs/engineering/FOUNDATION_WORKFLOWS_V1.md.

Interfaces: validate_workflow_catalog(value), load_workflow_catalog(path=None),
get_workflow(kind, catalog=None). Closed metadata shapes over actual current
workflow kinds/schemas and bounded shared profile. All definitions are reference
contracts; unknown/unavailable output schemas are explicit, not invented. No
queue, HTTP, EXECUTION_FILES or worker changes. No arbitrary shell/provider fields.
Render availability as existing-shared versus isolated-only versus not-wired,
never as newly authorized dispatch.

Deferred tests: unknown kind, duplicate definition, unauthorized profile widening,
extra command/provider fields, malformed version/hash and fake human approval.

### D: Retention Pins Over Verified Portable Backups

Files: scripts/llm/foundation_retention.py, tests/test_foundation_retention.py,
docs/engineering/FOUNDATION_RETENTION_V1.md.

Interfaces: build_retention_pin(backup_root, *, expected_backup_hash, snapshot_ids,
job_ids, case_refs=(), created_at); verify_retention_pin(pin, backup_root, *,
expected_backup_hash); write_retention_pin(pin_root, pin). Reuse backup.read_shared,
verify_shared and durable write_new, do not create a second state DB or copy engine.
Validate selected registered inputs/jobs against verified backup tables and seals.
Write only an explicit new local pin file, no overwrite. Case refs are user notes,
not verified case/plan authorization. All retention/deletion proposals remain
non-dispatchable; no delete, source pruning or remote upload implementation.

Deferred tests: expected hash mismatch, unknown snapshot/job, resealed/tampered
archive or pin, symlink, duplicate pin, retained old run, no owner credentials.

## Coordinator Integration

Files: scripts/llm/foundation_cli.py; tests/test_foundation_cli.py; Python CI
registration; docs/engineering/FOUNDATION_WAVE2_STATUS.md. Do not edit workers'
files while they own them. CLI commands: inventory --config JSON, workflows
[--catalog JSON] [--kind KIND], pin --request JSON [--write-root PATH]. Inventory
config has repositories/services/time zones/observed_at; pin request maps the D
interface exactly. Default stdout only; pin writes need the explicit write-root.
No CLI command is run in this implementation-only batch.

## Deferred Acceptance Gate

1. Integrate all three modules and freeze one candidate SHA.
2. Run focused normal/missing/conflicting/historical matrices, then full CI,
   mutation and independent final review on that same SHA.
3. Only then ask separately for remote CI, isolated service upgrade and two-device
   testing. No inherited B6 PASS applies to this new batch.
