# Shared Backup Capacity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Implement task-by-task; use an independent final-SHA reviewer.

**Goal:** Restore the complete existing shared history without exceeding a single-file limit.
**Architecture:** Preserve v1 for small archives; version oversized exports as sealed ordered row chunks. Normalize both formats through the existing validators and migration.
**Tech Stack:** Python standard library, SQLite backup API, current evidence validators.
**Spec:** `docs/engineering/SHARED_BACKUP_CHUNKS_V2.md`.

## Global Constraints

- Global file limit stays 12 MiB; chunk target 4 MiB, table export aggregate 256 MiB, 1024 chunks, 100000 rows.
- No history deletion, physical-copy substitute, production write, merge or access expansion.
- Same final SHA for full acceptance, independent review and remote CI; old PASS does not carry forward.

## Review Focus

- Rehashed missing/reordered/duplicated chunks must fail before state promotion.
- Oversized rows and aggregate overflow must remain bounded failures.
- Restore must not treat export metadata as application artifacts.
- Old v1, retained recovery evidence and byte-identical reports must survive repeated restores.
- Credential-shaped rows and false frozen/governance bindings remain rejected.

### Task 1: Chunk Codec And Roundtrip

Files: `workbench_backup_chunks.py`, `workbench_backup.py`, `workbench_shared_state.py`, `tests/test_workbench_backup_chunks.py` under existing scripts/tests roots.

Interfaces: codec `encode(tables) -> dict[path, bytes]`, `decode(root, index, catalog, columns) -> tables`; backup `is_export_file(manifest, name) -> bool`; public backup/restore signatures unchanged.

- [x] Add a >21 MiB valid synthetic history with successful reports; observe current backup failure.
- [x] Implement bounded chunk index/seals and decode validation; preserve v1 small format.
- [x] Exclude export metadata from restored artifact files; retain existing semantic validators.
- [x] Test missing/extra/tamper/reorder/duplicate/span/type/count/size/aggregate/credential failures, full rows/artifacts and interrupted restore.

### Task 2: Consumer And Mutation Integration

Files: `foundation_retention.py`, execution identity tuple, mutation gate and Python CI.

- [x] Retention/preservation must reopen v2 and preserve original backup identity.
- [x] Include codec bytes in execution source identity.
- [x] Add behavior-assertion mutations for chunk bounds, ordering and seals.
- [ ] Run focused old and new suites; document actual-size isolated backup/restore evidence without sharing data.

### Task 3: Final Acceptance And Conditional Release

- [ ] Commit/freeze new clean SHA; run full offline CI, full mutation gate, UI build and doctor.
- [ ] Independent review final SHA; any code change invalidates final gate and requires rerun.
- [ ] Push pure code/synthetic tests to existing Draft #405; exact-SHA Python/UI remote CI required.
- [ ] Verify actual isolated backup and fresh complete restore; retain old service/state for rollback.
- [ ] Upgrade only isolated 8443 backend; confirm code, hashes, private identity and read-only sync.
- [ ] Request actual Junyan/Reed two-device receipts; do not invent human PASS.
