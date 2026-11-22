# Platform Operations Implementation Plan

> For agentic workers: implement locally with executing-plans; use a fresh
> nonauthor reviewer for the complete final branch.

**Goal:** Rehearse platform runtime safeguards without installing or switching.

**Architecture:** Add an operator around the unchanged isolated recovery
verifier/child. Reuse the existing backup/restore path. Keep external observation
as a durable offline handoff with no sender or inferred human acceptance.

**Tech Stack:** Python stdlib, SQLite, launchd plist generation, existing AR seals.

**Spec:** docs/engineering/PLATFORM_OPERATIONS_V1.md.

## Global Constraints

- Baseline a57be7b; no running-service, production, schedule or rights changes.
- No host sleep/reboot, launchd installation or actual phone/network delivery.
- Preserve old recovery commands, 15000ms protection, hashes and seals.
- Fresh restore roots only; all newest tasks/comments/events retained.

## Review Focus

- Operator death between durable reservation and process creation.
- Relaunch after crash budget exhaustion; duplicate supervisors and unsafe pins.
- A new task/comment after an earlier backup must survive rollback rehearsal.
- Stale/future/replayed heartbeat must not hide host loss.
- Queued/sent/synthetic alert evidence must not become human/phone acceptance.

## Steps

- [x] Compile ai-task.v1 and record SPEC_READY.
- [x] Write failing operations/observer behavior tests, then implement minimal APIs.
- [x] Add new negative guard mutations without changing existing pins.
- [ ] Exercise owned-child restart, persistent fencing, cold restore and outbox.
- [x] Write Junyan/Reed/24-hour field checklist and separate pending approvals.
- [ ] Commit candidate; run full existing offline CI/mutations on exact SHA.
- [ ] Fresh independent review; repair findings and rerun on final SHA.
- [ ] Deliver diff, evidence and unexecuted real-world gates; no deployment.

## Review Correction Record

The first a7bdbf2 candidate was rejected by independent review. Retain its tests
and evidence, but do not transfer its acceptance. Fix-before-final: authenticate
the complete committed source closure before imports; bind one journal root to
the capsule; retain an overdue observation gap before accepting a new pulse.
The backup helper remains consistent-snapshot-only, not stopped-writer proof.
