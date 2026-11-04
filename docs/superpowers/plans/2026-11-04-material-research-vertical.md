# Real Materials To Earnings Tasks Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for this bounded continuation of the approved foundation blueprint. Preserve final nonauthor review.

**Goal:** Prepare an independently pinned historical earnings input from admitted PDF originals, then run the existing earnings-trial job without modifying the shared service or production.

**Architecture:** Keep foundation_materials as the source of admitted immutable bytes. A local-only material-research adapter selects explicit documents/pages and verifies author-supplied quotations against deterministic PDF extraction. It produces the existing earnings pack plus a complete sealed provenance inventory, which the existing earnings job verifies against an operator-supplied external hash.

**Tech Stack:** Existing Python/SQLite/workbench/trial code; installed pypdf 6.10.0 for bounded selected-page extraction. No new research engine, provider or network transport.

**Spec:** Approved AR_ENGINEERING_BLUEPRINT_20261101_V0_1.md G1/D04-D05/R06; user direction on 2026-11-04 prioritizes the real-material vertical before two-human-device acceptance.

## Global Constraints

- Existing 8443 service, ar-live, official ledgers and historical originals are read-only references; no upgrade or merge.
- Use only admitted library originals. Quarantine stays unavailable. No public/team document serving or external model transmission; source rights remain unchanged.
- Historical replay only. Questions are newly authored drafts, never invented historical thesis registrations. Assessments remain UNRESOLVED and human review PENDING.
- Original PDF hash, physical page, extracted-page hash, line span, quoted bytes, source publication/capture/cutoff and pack hash must be traceable.
- Keep the global 12 MiB file bound. Max 8 PDFs, 32 selected pages in total, 16 questions, 64 MiB pack; no OCR, active/encrypted PDFs or silent empty extraction.
- Reuse earnings-trial job and existing local UI. Shared/private whitelist remains observe/snapshot-brief only. Two-machine acceptance is explicitly deferred, not waived.
- Native worktree tool rejected the external sourceRoot; fallback git worktree is inside the existing AR product container. Base9889b0c is a declared dependency, not main; main reconciliation remains a separate release gate.

## Review Focus

- A coherent re-seal must not evade the independently supplied pack hash.
- Replacing a page text or its PDF, changing company/date, or selecting quarantined/unregistered content must fail before a task succeeds.
- New questions cannot acquire false historical publication or registration identity.
- A crash cannot leave an incomplete pack that later verifies as complete, nor overwrite an existing root.
- Added preparation must not enable private/shared earnings jobs, provider calls or document-sharing rights.

## Task 1: Sealed Local Research Pack

Files: scripts/llm/foundation_research.py; tests/test_foundation_research.py; scripts/llm/foundation_cli.py.

- [x] Write real minimal PDF fixtures and failing tests for prepare/verify and citation validation.
- [x] Run RED at the actual CLI/API boundaries.
- [x] Implement prepare_research_pack(library_root, request, output_root) and verify_research_pack(pack_root, expected_pack_hash), with closed schemas and exact inventory.
- [x] Add research-pack and research-pack-verify offline CLI commands; reuse bounded source/root primitives.
- [x] Exercise normal/missing/conflicting/date/size/path/corruption/partial-write/old-library cases; ensure no ledger/model/network operations.

## Task 2: Existing Earnings Job Binding

Files: scripts/llm/workbench_earnings_trial.py; scripts/llm/workbench_workspace.py; scripts/llm/nonprod_workbench.py; scripts/llm/workbench_shared_workspace.py; tests/test_foundation_research.py.

- [x] Write failing job tests for external pack hash, original bytes, quote derivation, restart/retry and private-mode denial.
- [x] Add --earnings-pack-hash and matching Workspace/run parameter, preserving legacy packs without the new marker.
- [x] Require a pin for every material research pack and reverify before and after rendering; return binding metadata in existing result.
- [x] Include new executing source modules in source identity; do not expand shared kinds or permissions.

## Task 3: Acceptance And Real Historical Demonstration

Files: .github/workflows/python-ci.yml; scripts/governance_mutation_gate.py; docs/engineering/MATERIAL_RESEARCH_VERTICAL_V1.md; scripts/llm/fixtures/material_research_vertical.task.json.

- [x] Pin pypdf dependency for CI and register the focused suite and behavior mutation targets.
- [ ] Freeze final source, run relevant old/new suites, complete offline CI execution steps and mutations on that same SHA, then nonauthor review.
- [ ] Using a new private output root, select one admitted historical company's filing(s), prepare cited draft questions, freeze and run earnings-trial; independently reopen input/output hashes and original-page quotes.
- [ ] Reuse the local workbench UI for an isolated demonstration when its source/assets are ready. No 8443 switch; no human acceptance claim.
- [ ] Deliver code/acceptance evidence, readable report, exact remaining shared/rights/production gates. Keep two-human-device acceptance deferred.

## Execution Notes

- Baseline140 tests PASS with the same physical TMPDIR=/private/tmp convention as previous accepted runs. The first default macOS /var-alias run failed no-follow source guards; no product guard was changed to accommodate the alias.
- Task1/2 RED cases reproduced missing preparation, missing CLI/job pin and false draft backdating;18 focused tests now PASS. The combined old/new materials, CLI, workspace and trial set is212 PASS.
- Ruling: use the existing local earnings job first, not a new shared kind. This respects fixed no-sharing rights and proves real-original lineage before a future separately approved shared adapter; it does not deliver team research execution yet.
- Ruling: record actual preparation/consumer execution identity, including original trial modules, rather than letting source hashes imply which code ran. The synthetic fixture supplies a controlled identity; the real operation must use a clean committed source.
- Independent83f30a8 review found one P1 (partial pack legacy downgrade) and three P2 (asserted historical dates, UTC boundary, escaped active PDF names). Four real-entry regression cases reproduced them before fixes. The replacement candidate writes intent first, records observed preparation time separately, normalizes/preflights the trial, and scans decoded PDF object names.22 focused cases pass; full final acceptance and new nonauthor review are still required. Superseded partial83f30a8 acceptance/mutation runs were cancelled and retained, not reused as final evidence.
