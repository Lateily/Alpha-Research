# Shared Research Library Implementation Plan

> Execute inline using executing-plans, TDD and a fresh independent final review.

**Goal:** Make the accepted pinned research-result metadata query available to the
two existing private-workbench users without distributing restricted contents.
**Architecture:** Existing foundation_results -> private SharedWorkspace read-only
adapter -> closed GET route -> separate React view, not another storage system.
**Tech:** Existing Python/SQLite identity, React/lucide/Vite, Node pure-view tests.
**Spec:** docs/engineering/SHARED_RESEARCH_LIBRARY_V1.md.

## Task1: Private Metadata Query

- [x] Write failing public HTTP/adapter tests for owner/member, exact/empty/date,
  unconfigured, malformed URL/identity, changed pin and content-denial invariants.
- [x] Add paired operator flags and fixed-root validation. Add private read-only
  query projection with pagination; do not add file/report/download/write routes.
- [x] Run focused adjacent tests and record RED/GREEN evidence.

## Task2: Shared Page

- [x] Write Node tests for query encoding, closed response/actor/rights bindings,
  single-flight refresh and disposed/stale context isolation.
- [x] Add separate research-library tab, responsive filters, metadata table/detail
  and visible missing/denied/PENDING statuses in existing visual conventions.
- [ ] Add CI coverage and targeted behavior mutations. Build and browser-test
  desktop/mobile plus empty/error/stale states on an isolated local candidate.

## Task3: Exact Candidate And Private Rollout

- [ ] Commit clean final code. Independent scoped review; repair reproduced P1/P2
  then re-review the changed final SHA, never reuse old PASS.
- [ ] Run same-final full106-step offline CI and full mutation gate; UI build/QA.
- [ ] Pure-code Draft PR remote CI; no merge. Preserve separate Vercel status.
- [ ] Final gates only: chunked cold backup -> fresh-state restore -> record/byte
  comparison -> loopback candidate -> switch existing8443 target, retain rollback.
- [ ] Verify both existing identities without impersonating human acceptance;
  deliver receipts and exact deployed SHA. Production remains untouched.

## Rulings And Ledger

- Ruling: Reuse the existing non-running linked worktree and create a new branch
  from a27d407. Preserve old branch/operation artifacts and both running services.
- Ruling: Share metadata only; immutable rights prohibit distributing real
  source/report contents. User request does not silently rewrite those rights.
- Ruling: No new earnings task kind/automatic intake; that is a separate executor
  scope. This slice exposes the already accepted local query on the shared page.
- Baseline: a27d407 clean;24 existing result tests PASS before source changes.
- Task1/2: the real shared GET returned404 before implementation (assertion
  failure, zero errors), then the13 new boundary cases passed. The24 existing
  result-library cases and24 adjacent shared-workspace cases passed. Five Node
  view tests passed after their missing-entry assertions were observed failing.
- Six new targeted mutations each failed by behavioral assertions, errors0,
  skips0. This is not the full mutation gate. Vite build passed using the existing
  root node_modules via an ignored symlink, with no dependency installation.
- Browser plugin startup failed its installed native binding; use the documented
  existing-browser fallback. Native desktop is locked, so prefer browser extension
  operations; do not modify system/browser settings or bypass safety prompts.
- Independent2b69c47 review found P2: the shared header refresh did not invalidate
  the child research index, and parent recovery could unmark stale without its
  own verification. Actual-component hook regression reproduced0 new library
  reads after header refresh. Added parent refresh revision and independent
  verification epochs; disposed outage reads cannot make recovered data fresh.
  Component/header/recovery and epoch counterexamples passed RED->GREEN. The
  initial-error hash label now stays UNAVAILABLE, not a false NOT_CONFIGURED.
- Component hook tests bundle actual JSX with existing esbuild in the UI CI job;
  Python/mutation CI remains dependency-free Node helpers. The UI test includes
  a behavior-level parent-binding mutation, not merely a source-string match.
