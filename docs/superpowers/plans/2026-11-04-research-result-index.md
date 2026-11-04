# Research Result Intake And Query Implementation Plan

> Execute inline with superpowers:executing-plans and a final fresh-context reviewer.

**Goal:** Preserve completed real-material earnings results in the existing local
material library and retrieve them by explicit industry and research date.
**Architecture:** A bounded result adapter validates pinned source/pack/result,
stages immutable content-addressed files, and calls the existing material ingester.
**Tech Stack:** Existing Python, material library, earnings renderer and offline CLI.
**Spec:** docs/engineering/RESEARCH_RESULT_LIBRARY_V1.md; approved foundation blueprint.

## Global Constraints

- No production, original/shared service, source library, existing pack or case edits.
- No provider/network/paid model, research verdict, human signature or ledger write.
- Existing byte limits, no-follow guards, hashes/seals and historical records stay.
- This is stacked on acceptedd330f3e, not represented as current main.
- Native worktree tool rejected the external sourceRoot; authorized fallback stays
  inside the existing AR/product worktree container. Prior preview is untouched.
- Follow the user's direct execution instruction; no new design approval stall.

## Review Focus

- Copying a SUCCEEDED label cannot hide a changed report or missing citation file.
- An old producer is never relabeled as the current importer or a human reviewer.
- Empty/combined date filters cannot expose source or ingestion day as research date.
- Two stale writers cannot corrupt or silently merge a result-library snapshot.
- Partial staging/registration and duplicate outputs cannot become new samples.

## Task 1: Bound Result Intake

Files: foundation_results.py, foundation_materials.py, tests/test_foundation_results.py.
- [x] Write failing real pack -> earnings -> result intake tests and refusal matrix.
- [x] Add optional locked expected-library pin/new-destination guards to ingester;
  preserve legacy calls. Add focused normal/stale/race counterexamples.
- [x] Implement create-only staging, complete source/output provenance, byte dedup,
  restrictive labels and idempotent same-result handling. Verify all before publish.
- [x] Run focused existing/new tests; ledger result and commit task scope only.

## Task 2: Read-Only Query And CLI

Files: foundation_results.py, foundation_cli.py, tests/test_foundation_results.py.
- [x] Write failing exact AND industry/taxonomy/date/ticker, empty, pin and tamper tests.
- [x] Implement pinned read-only result views and CLI commands; no new HTTP surface.
- [x] Add importer source to execution identity; author task fixture, CI step and
  behavior mutations. Run each new mutation before freezing.

## Task 3: Final Acceptance And Real Demonstration

- [ ] Freeze clean source and obtain independent scoped P1/P2 review. Fix only
  reproduced findings; any changed final code needs fresh review, no old PASS reuse.
- [ ] After review passes, run full offline CI and mutation gate on that exact SHA.
- [ ] Run a fresh real-material task on final code, archive it locally, query by
  semiconductor/date and ticker, reopen all hashes; preserve historical d330 case.
- [ ] Deliver exact code, scope, evidence, remaining foundation/UI/release gates.

## Ledger

Ruling: Use the existing material library and local CLI first, not shared HTTP or
automatic post-job writes. This keeps source rights/private service boundaries
unchanged; the UI consumer remains a later slice.

Task1/2 verification:74 focused/adjacent cases PASS (22 new result cases plus52
existing material/pack/CLI cases). Ten new mutation targets each produced one
behavioral assertion failure and zero unittest errors in the target-only smoke.
The four-page positive case exposed the unchanged16-files/material bound before
implementation; split blob ownership fixes it without increasing limits. A first
mutation smoke survived the three-page case, so the positive fixture was expanded
to four distinct pages; no gate was weakened. Tests also pin historical consumer
identity, stale-writer fencing, source/output corruption, CLI forwarding and every
metadata/file write interruption. Full final gates remain pending.

Author boundary check: a non-string report field raised AttributeError instead
of a bounded refusal. Its actual-entry regression failed before the one-line
type guard and passed afterward. Updated focused/adjacent suite75 PASS (23 new),
all11 new behavior mutation targets killed by failures, zero errors. The real
5956c64 intake/query demonstration is retained under that SHA and is not reused
as final evidence after the amendment. Independent review will name the new HEAD.
