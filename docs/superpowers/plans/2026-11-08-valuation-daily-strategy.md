# Valuation And Daily Strategy Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; one fresh
> nonauthor whole-branch review. User has opted out of another question round.

**Goal:** Add source-bound normalization diagnostics and the approved daily
sweep/reclaim candidate's reproducible strategy card without imputing gaps.

**Architecture:** Reuse the sealed financial-card consumer and the existing
ce46949 registered daily input validator. Two additive CLI artifacts share the
existing canonical hash/private-output contracts; no online consumer changes.

**Tech Stack:** Python3.12, Decimal, pinned pypdf6.10.0, existing offline tests.

**Spec:** docs/engineering/VALUATION_DAILY_STRATEGY_V1.md

## Global Constraints
- Keep global12MiB/PDF/time/queue limits, raw sources and old sealed reports.
- Do not touch production/shared services, formal ledgers, providers or APIs.
- No new source certification, automatic human approval or profitability claim.
- Existing daily profile/spec pins are unchanged; missing required evidence blocks.

## Review Focus
- A worksheet cannot relabel a reported anchor or arbitrary peer PE as normalized.
- CLI must rederive from externally pinned pack/evidence, not a validation JSON.
- Future confirmations/targets and later context cannot improve an earlier event.
- Tampered/resealed outputs and source races must fail on reopen.
- Long bounded inputs/output amplification must not escape existing size guards.

### Task1: Valuation Evidence
Files: new scripts/llm/research_normalization.py, tests/test_research_normalization.py.
Consumes: content.verify(...), externally pinned exact worksheet, numeric facts.
Produces: create/verify normalization worksheet receipt and readable diagnostics.
- [ ] Write and watch RED missing/typed-period/complete synthetic tests.
- [ ] Implement reported bridges and nullable E4 hypothetical calculation.
- [ ] Run GREEN, real retained source proof and commit.

### Task2: Daily Strategy
Files: port technical_contract.py/technical_profiles.py and their two test files;
new experiments/research_workflows/daily_strategy.py and tests/test_daily_strategy.py.
Consumes: load_registered_pack(registry_path,pack_id,evidence_roots).
Produces: create/verify strategy artifacts bound to the original pack/profile.
- [ ] Port exact ce46949 input code/tests; run126 baseline tests.
- [ ] Write RED event/Wilder/target/prefix/authority/CLI-reopen regressions.
- [ ] Implement with confirmed_pivots reuse; keep the old minute engine intact.
- [ ] Run GREEN, missing real-input proof and commit.

### Task3: Same-Final Acceptance
Files: governance_mutation_gate.py, python-ci.yml, no-network suite, task fixture.
- [ ] Preserve original41 technical pins and add behavior-reaching new pins.
- [ ] Freeze clean SHA; regenerate both real artifacts on that SHA.
- [ ] Full local CI/every mutation and fresh independent review on that SHA.
- [ ] Reopen receipts/legacy reports and verify installed/source/ledger pins.
- [ ] Keep branch/worktree and all failed history; no push/merge/release.

## 2026-11-09 Rejected-Candidate Follow-Up

f39eb7a is retained and rejected: full CI112/113, full mutation baseline failed,
independent review R1-R5. Fix the output directory race with a shared held-fd
artifact writer/read snapshot; enforce event-time indicator/context evidence and
fixed Decimal precision. Repair minimal governance fixtures and the Git-less
in-process artifact identity fixture without disabling real guard requirements.
Keep the four original ce46949 port files byte-identical and every existing pin
ID; only update the two necessary derivation anchors after their read API moves.
Add behavior pins for the new regressions. Freeze a replacement clean SHA and
rerun all gates, retained demonstrations, legacy reopens and independent review.
