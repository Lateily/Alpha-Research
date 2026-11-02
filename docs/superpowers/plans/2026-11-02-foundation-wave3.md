# Foundation Wave 3 Implementation Plan

> **For agentic workers:** Use parallel workers with disjoint file scopes. The
> user explicitly defers all behavioral testing until foundation integration.

**Goal:** Implement whole-repository source coverage accounting, immutable local
research-material intake, portable preservation handoffs, and deployment drift
reconciliation without touching installed services or production.

**Architecture:** Extend the existing Python/JSON foundation, not its production
dispatchers. Closed v1 call receipts remain compatible. New broad source inventory
is not evidence that every provider is instrumented or licensed. New material
intake is an isolated immutable artifact store, not a second decision ledger.

**Tech Stack:** Python standard library, existing evidence and backup validators.

**Spec:** Approved AR_ENGINEERING_BLUEPRINT_20261101_V0_1.md (external original at
/Users/years/Desktop/Stock/AR_ENGINEERING_BLUEPRINT_20261101_V0_1.md), sections F/D/P/W;
Junyan's 2026-11-02 direction to complete the four foundation packages.

## Global Constraints

- No tests, builds, mutation runs, browser QA or new feature command execution.
- Static AST/JSON/YAML/diff inspection only; new tests are authored but NOT_RUN.
- No production, shared-service/state, provider, credential, ledger or network actions.
- No push, merge, deployment, remote upload, deletion, approval or rights expansion.
- Every output retains WORKFLOW_DEBUG, NOT_RUN, PENDING and false authorities.
- Missing, dynamic, conflicting and unverified inputs stay explicit; no guessed success.

## Review Focus

1. Unrecognized or dynamic source calls must remain unresolved, not silently covered.
2. Source files, material bytes and lineage hashes must be checked against independent inputs.
3. Material date, identity, version and taxonomy conflicts must not silently merge.
4. A local copy or caller-written receipt must not attest off-machine durability or restore success.
5. Equal repository SHAs must not prove equal running code, schema or approved deployment.

## Task 1: Repository-wide Source Coverage

Files: scripts/llm/foundation_sources.py, config/data-source-inventory.v1.json,
tests/test_foundation_sources.py, docs/engineering/FOUNDATION_SOURCES_V1.md.

Interface: build_source_coverage(repository_root, *, inventory_path=None) -> dict;
load_source_inventory(path=None) -> dict. Scan declared bounded code roots
statically, retaining file/line and file hash for detected network/provider calls.
Use explicit provider and host registration, strip URL query/userinfo, expose
unresolved calls and parse failures. Do not import/execute scanned code. Keep
instrumentation and rights separate from inventory matching. Preserve closed
five-source v1 receipts; broad inventory does not change their meaning.

- [x] Implement catalog/scanner and deferred normal/missing/dynamic/drift tests.
- [x] Static inspect source; do not invoke scanner.
- [ ] Runtime acceptance and independent review DEFERRED.

## Task 2: Isolated Research Material Intake

Files: scripts/llm/foundation_materials.py, tests/test_foundation_materials.py,
docs/engineering/FOUNDATION_MATERIALS_V1.md.

Interfaces: ingest_material(source_root, library_root, manifest) -> dict;
verify_library(library_root, *, expected_library_hash=None) -> dict;
query_library(library_root, *, industry_key=None, trade_date=None, ts_code=None) -> dict.
Manifest explicitly lists source files, expected hashes and metadata: original/
thesis/valuation/case/strategy/review/attribution, run, code, version, taxonomy,
cutoff/availability/publication times and rights. Original bytes are immutable,
registration create-only and content addressed; no recursive arbitrary import.
Library verification returns a deterministic library_hash plus portable files
mapping of relative path -> sha256. Reopen verifies bytes and lineage. Never
auto-approve, infer team/model rights or rewrite historical material versions.

- [x] Implement bounded intake/query/verification and deferred counterexamples.
- [x] Static inspect only; no real materials imported.
- [x] Workbench HTTP and production registration remain unwired.

## Task 3: External Preservation Handoff

Files: scripts/llm/foundation_preservation.py, tests/test_foundation_preservation.py,
docs/engineering/FOUNDATION_PRESERVATION_V1.md.

Interfaces: build_preservation_manifest(packages, *, created_at) -> dict;
verify_preservation_copy(manifest, package_roots, *, expected_preservation_hash) -> dict.
Packages have package_id, kind (SHARED_BACKUP/RESEARCH_LIBRARY), local_root and
independently expected content hash. Reuse existing shared backup validation or
verify_library. Inventory complete package bytes, bind package identity and hashes,
do not upload or create a competing backup engine. An independent destination
read can verify bytes, never prove geographic separation, provider retention,
encryption, licensing or restore success. All such attestations remain pending.

- [x] Implement portable handoff and deferred tamper/missing/identity tests.
- [x] No actual export, upload, external destination verification or restoration.

## Task 4: Deployment Reconciliation And CLI Integration

Files: scripts/llm/foundation_release.py, tests/test_foundation_release.py,
scripts/llm/foundation_cli.py, tests/test_foundation_cli.py,
.github/workflows/python-ci.yml, docs/engineering/FOUNDATION_WAVE3_STATUS.md.

Interface: reconcile_deployments(inventory, release) -> dict. Consume exact
runtime-inventory schema and closed target release contract (target roles, expected
repository SHA, source-tree hash/schema evidence if supplied). Reconcile directory,
dirty state, cached remote, service assertions and independent evidence separately.
Missing/contradictory evidence is BLOCKED/UNKNOWN; emit no shell/install actions.
CLI subcommands sources/material-ingest/materials/preservation/preservation-verify/
reconcile are offline and explicit. Existing commands and dispatch limits unchanged.

- [x] Implement read-only reconciler and CLI request validation.
- [x] Register deferred test commands, author deferred behavior tests.
- [x] Static AST/JSON/YAML/diff check; record IMPLEMENTED_UNTESTED.
- [x] No deployment readiness, independent-review PASS or overall completion claim.
