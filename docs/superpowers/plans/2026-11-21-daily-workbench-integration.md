# Daily Workbench Integration Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; independent nonauthor source and release review are required before conditional activation.

**Goal:** Complete the existing frozen research workflow inside the approved daily UI.

**Architecture:** New private React entry, reused presentation primitives and exact
existing API validators; no backend changes. Independent single-flight resources
bind their own freshness, actor, workspace, version and filter/selection generations.

**Tech Stack:** Existing React 18, Vite 5, lucide-react, Node offline tests and Python backend.

**Spec:** `docs/engineering/DAILY_WORKBENCH_INTEGRATION_V1.md`

## Global Constraints

- Exact 15,000 ms expiry, click-time checks and unchanged backend gates.
- No network except loopback/private QA and code/synthetic GitHub CI.
- Original dates, source rights, DATA_BLOCKED and human PENDING remain authoritative.
- No merge or formal nightly/ledger/schedule/trading changes.
- Private upgrade only after all acceptance gates; preserve newest tasks/comments.

## Review Focus

- Held or failed detail/review GET cannot borrow freshness from context polling.
- Actor/version/filter change must reject late reads and retained callbacks.
- Uncertain POST stays attached to the same command; reload does not silently resubmit.
- Granted review packet must match selected research; no identity-derived approval.
- Rollback and interrupted activation must preserve the newest state generation.

### Task 1: Live Contract Adapter And Actions

Files: `live-ui/live-state.mjs`, `tests/nonprod-daily-live.test.mjs`.
- [ ] Write failing freshness/generation/contract and uncertain-command tests.
- [ ] Implement independent resource snapshots, existing validated reads and idempotent actions.
- [ ] Prove stale retained handlers and contract/identity tampering are rejected.

### Task 2: Five-Entry Real Workflow

Files: `live-ui/*.jsx`, `live-ui/*.css`, `live-ui/index.html`, existing daily primitives,
`vite.config.js`, `tests/nonprod-daily-live-component.test.mjs` and UI workflow.
- [ ] Actual-component RED tests for submit, task details, AND query and comments.
- [ ] Reuse the approved layout and existing strict producer-contract validators.
- [ ] Persist uncertain commands; show archive/steps/citations/rights and degraded state.
- [ ] Desktop/mobile real restored-state browser flow and legacy regression/build.

### Task 3: Same-Version Acceptance And Conditional Release

Local evidence only; code and synthetic fixtures only go to Git.
- [ ] Full CI-equivalent tests/mutations and independent source review on final candidate.
- [ ] Draft PR and same-version required remote Python/UI checks.
- [ ] Independently review pinned release/backup/rollback helpers before any stop.
- [ ] Latest-state cold pair, fenced stop, stopped-latest backup and private cutover.
- [ ] Post-live c71 evidence/queries and preservation; expose residual human/research gates.
