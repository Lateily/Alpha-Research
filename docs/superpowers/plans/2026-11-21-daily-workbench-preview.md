# Daily Workbench Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a clickable five-view daily workbench preview using genuine,
verified historical records without changing any existing service.

**Architecture:** Separate React/Vite entry and a loopback-only read-only server.
The unchanged backend validates a restored archive before its permitted metadata
is sealed for presentation. No provider, live service or task execution is wired.

**Tech Stack:** Existing React 18, Vite, lucide-react, Node tests and Python stdlib.

**Spec:** docs/engineering/DAILY_WORKBENCH_PREVIEW_V1.md

## Global Constraints

- Existing backend and validation files are unchanged.
- Exactly five primary views; evidence details are secondary.
- Missing data, expired reads and pending human review remain visible.
- Read freshness expires at 15,000 ms.
- No synthetic business data or actionable disconnected commands.
- Local isolated preview only; production and private service unchanged.

## Review Focus

- Unknown states must not become usable or approved.
- A successful historical run must not become today's live research.
- Late responses must not override a newer read generation.
- Search cannot claim to query material outside the loaded verified projection.
- Narrow screens and long hashes must not hide the blocked state or main action.

### Task 1: Honest Presentation Contract

**Files:** daily-ui/view.mjs and tests/nonprod-daily-workbench.test.mjs.

- [ ] Add failing behavior tests for states, 15-second expiry and loaded-record filters.
- [ ] Run the tests and observe failure before implementing helpers.
- [ ] Implement pure view/filter functions retaining raw status and evidence IDs.
- [ ] Run positive and negative regression tests.

### Task 2: Clickable Daily Interface

**Files:** tools/nonprod_workbench/daily-ui and daily.vite.config.js.

- [ ] Implement Today, Research, Holdings, Macro and Tests with real projection fields.
- [ ] Implement task details, source drawer, citation pages, metadata download and search.
- [ ] Implement empty/loading/blocked/error/expired states and mobile navigation.
- [ ] Build and run component/SSR checks and existing shared UI regressions.

### Task 3: Isolated Data And Preview Evidence

**Files:** local evidence directory; source remains outside tracked runtime data.

- [ ] Restore an existing verified archive into a new isolated destination.
- [ ] Obtain permitted projections through unchanged backend validators and seal them.
- [ ] Serve only built assets and pinned metadata on an unused loopback port.
- [ ] Test rejected POST, path traversal, changed hash/seal, and foreign origin.
- [ ] Capture and inspect desktop/mobile screenshots and interactive flows.
- [ ] Review the final diff independently and document limits and service non-changes.
