# Shared Research Cards Implementation Plan

> Execute inline using superpowers:executing-plans and TDD. One whole-slice
> nonauthor review at the end; preserve rejected candidates and all old pins.

Goal: connect the latest frozen content/basis cards to an isolated shared-task
and query page while preserving input/seal/rights and historical boundaries.
Architecture: distinct registered envelope and queue kind; metadata-only output
archive and versioned API, not a replacement for legacy earnings results.
Tech stack: existing Python/SQLite/React/lucide and source-only bounded worker.
Spec: docs/engineering/SHARED_RESEARCH_CARDS_V1.md.
Base: 6c254d053e3d7cb5cf38b1ed966c67f8c9648461; prerequisite core-gap final
review/gates must be accepted before this slice can claim completion.

## Constraints And Review Focus

No current service/production/ledger/ACL/schedule writes, provider, new dependency,
push or merge. Two-human acceptance deferred. Per-file12MiB and existing global
bounds remain. Legacy workflow, schema and mutation records remain compatible.
Test wrong external pins before writes, source change during copying, partial
registration, stale workspace/code submissions, kind confusion, forged output,
permission leakage, as-of dates and cold-reopen equality. Scope-valid engineering
does not certify financial semantics or source authenticity.

## Tasks

1. Add scripts/llm/workbench_shared_cards.py and focused tests. snapshot(library,
   pack,content,basis,*,expected_library_hash,expected_pack_hash,
   expected_content_hash,expected_basis_hash) delegates existing verifiers.
   envelope, copy_input, verify_input, register, render, verify_output and detail
   use distinct schemas, fixed inventory, conservative metadata projection and
   manifest-last archive. Watch absent-module/pin/tamper/rights tests RED->GREEN.
2. Wire the new schema/kind through FrozenInputs, SharedJobQueue, bounded worker,
   SharedWorkspace, opt-in HTTP flag, backup PDF provenance and retention. Keep
   all original guards/pins unchanged; add exact behavior regressions for queue,
   identity, default-off, recovery, archive and cold backup/restore.
   Extend workbench_recovery.py and workbench_runtime.py with explicit recovery-v2
   feature opt-in, preserving the exact old-v1 profile and all its mutation pins.
3. Add closed versioned card inputs/library endpoints. Query exact industry,
   taxonomy/version/research-date/security AND filters. Add a separate React
   card panel and pure contract parser; bind login/workspace/code/request epoch,
   invalidate stale details and preserve missing/BREAK. Do not display prose or
   values denied by rights. BrowserQA desktop/mobile uses only an isolated server.
4. Append new behavior mutations and versioned CI/task compilation; freeze final
   SHA. Register retained historical real cards and run one isolated deterministic
   task, reopen same job/input/producer/consumer/output/archive, query positives
   and mismatches, backup/cold restore. Full same-SHA CI/mutations and independent
   review; no existing shared upgrade. Retain failures and report exact limits.
