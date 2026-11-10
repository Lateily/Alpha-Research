# Shared Review Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Permit the original Junyan/Reed private audience to read an admitted
derived review sample and submit immutable version-bound comments.

**Architecture:** Reuse the shared identity, workspace event chain and complete
backup. Operator-only packet admission pins derivative and separate audience
grant. Add default-off API/page integration without raw-source distribution.

**Tech Stack:** Existing Python stdlib/SQLite, React/lucide, offline unittest/Node.

**Spec:** docs/engineering/SHARED_REVIEW_PORTAL_V1.md

## Global Constraints

No production, merge, raw PDF/source-text distribution, provider/paid calls,
global-limit increase or deletion of history. Real packet data remains local.
Same final SHA for every release gate. Existing guards/mutation pins retained.

## Review Focus

- Correct file hash paired with a forged audience grant must still be rejected.
- Browser identity/refresh races must fence retained submit callbacks.
- Lost POST responses must not produce duplicate or misattributed comments.
- A valid event hash with invalid semantic comment binding must not survive restore.
- Restart/rollback must retain comments added after upgrade, not swap an old DB.

### Task 1: Admission And Append-Only Review Domain

Files: create scripts/llm/workbench_review_portal.py and
tests/test_workbench_review_portal.py; modify backup artifact/binding validation.
Interfaces: register(view, packet_root, manifest_pin, grant, grant_pin),
ReviewPortal(view).list(actor), .detail(packet_hash, actor), .submit(payload, actor).

- [ ] Write focused synthetic tests for pins/audience/tamper/context/idempotency,
  watch RED, implement schema validation and existing event-chain storage, GREEN.
- [ ] Add semantic backup validation and full cold-reopen test, RED then GREEN.
- [ ] Append relevant mutation pins without changing existing declarations.

### Task 2: Default-Off API And Shared Page

Files: nonprod_workbench.py, workbench_shared_workspace.py,
tools/nonprod_workbench/ui/{review-portal.jsx,review-portal-view.mjs,shared-workspace.jsx},
tests/test_workbench_review_portal.py, Node view/component tests.

- [ ] Add API authorization/body/CSRF/off-mode regressions, RED then GREEN.
- [ ] Add client context, stale-callback and lost-response retry regressions,
  RED then GREEN; use item/status/severity controls and literal text rendering.
- [ ] Wire explicit private flag and execution inventory, leave old modes intact.
- [ ] Add focused tests to versioned CI; compile task and record focused results.

### Task 3: Exact-SHA Release Evidence And Conditional Rollout

- [ ] Freeze candidate, run all local CI and mutation gates; independent whole
  diff review and relevant repair RED/GREEN, restart gates if final bytes change.
- [ ] Admit retained real derivative under the exact two-person grant in scratch;
  actual isolated browser comment/retry/reload/permission/layout checks.
- [ ] Complete backup/cold restore and independently compare original records,
  admitted packet and comments; preserve source hash/rights and original state.
- [ ] Push only code/synthetic tests; Draft PR, exact-HEAD remote CI all green.
- [ ] Fence/drain existing isolated service, retain cold backup, prepare new
  state/runtime, verify and switch 8443 only. Preserve rollback and new work.
- [ ] Report actual installed SHA, UI evidence, remaining human/source limits.
