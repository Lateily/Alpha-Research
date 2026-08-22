# H7 Product-AIOS Bridge Phase 3

Status: `DRAFT / OFFLINE / PHASE_3`

Owner: Reed. Product UI implementer: Better. Safety/eval reviewer: Jason.
Workflow reviewer: Simon. Final merge authority: Junyan.

Related: #277, #280, #281, #287, #288.

## 1. Purpose

Phase 3 turns the H7 contract into a concrete product page handoff. It defines
the first Product-AIOS Bridge page that can show this path:

`Product request -> AIOS Task preview -> Agent output packet -> Human Review -> Page display`

This is still an offline product acceptance slice. It does not implement a
React route, call a model, execute an Agent, write GitHub comments, write
Memory, or change Router, Context, Policy, Scheduler, Executor, or permission
logic.

## 2. Page Definition

Canonical page candidate: `/aios/product-bridge`

The page is an internal workbench. Its job is to let a human inspect whether a
product request has become a safe AIOS task and whether the returned evidence is
ready for human review.

It is not a research conclusion page and not a trading page.

## 3. Required Regions

| Region | Purpose | Required states |
|---|---|---|
| Request Header | Identify workflow, owner, reviewer, source issue, generated time | partial, stale, blocked |
| Task Preview | Show canonical `ai-task.v1` fields without inventing Router fields | ready, blocked |
| Run Projection | Show AIOS task/run/freshness status from the H7 packet | partial, stale, blocked, error, review |
| Evidence Table | Show cited facts, tiers, source dates, cutoffs, verification | partial, stale, review |
| Gap Panel | Keep missing evidence, blocking reasons, and error codes visible | partial, stale, blocked, error |
| Human Review Dock | Show reviewer, pending/approved/revise/rejected state, decision ref | pending, approved, revise, rejected |
| Audit Strip | Show no-trade flag, untrusted-data flag, final merge authority | always |

## 4. Product Decisions

The UI may guide a human, but it cannot make an AIOS decision by itself.

Allowed product decisions:

- `EDIT_REQUEST`: the human changes product input.
- `REQUEST_CONTEXT_REFRESH`: the human requests a future context refresh.
- `REQUEST_HUMAN_REVIEW`: the human asks the named reviewer to inspect output.
- `MARK_UI_FEEDBACK`: the human records a product feedback case.

Disallowed product decisions:

- approving Human Review from model output;
- marking Memory promotion complete;
- authorizing final merge;
- hiding stale or partial evidence behind a green state;
- sending `workflow_type` to Router as a fake `task_type`;
- using external announcement text as system instruction.

## 5. Bridge Acceptance Matrix

Each acceptance case binds one H7 packet status to one visible user outcome:

| Case | Input status | Expected user outcome |
|---|---|---|
| `missing_amount` | `PARTIAL` | Missing evidence remains visible; no complete tone |
| `expired_cutoff` | `STALE` | Refresh request is available; review remains blocked |
| `bad_request` | `BLOCKED` | No runnable task preview; edit request is primary |
| `projection_failed` | `ERROR` | Error code is visible; no success fallback |
| `needs_review` | `AWAITING_HUMAN_REVIEW` | Reviewer and missing decision ref are visible |

`COMPLETE` is excluded from the current acceptance matrix until A-020 Authority
Resolver provides a trusted Human Gate receipt. A reviewed-looking string or a
locally constructed receipt must not become a complete product state.

## 6. Bridge Trace Contract

Every case must render one continuous, versioned `bridge_trace`:

`product_request -> ai_task_preview -> agent_output_packet -> human_review -> page_display`

The trace id comes from `packet.user_input.request_id`. The UI may display a
short copyable id, but it must not generate a new id from chat history, raw
model text, browser local storage, or unreviewed external instructions.

Each trace stage binds the visible stage name to a concrete artifact:

- `artifact_id`
- `artifact_hash`
- `source_contract`
- `parent_artifact_hash`
- `receipt_id` when the stage is backed by a Human Gate receipt

The hash must bind the loaded contract artifact, not a stage label. Changing
the agent output packet, human review receipt, or page display fixture must make
the trace invalid until the fixture is regenerated and reviewed.

Trace guards:

- `COMPLETE` cannot be shown in this phase.
- `PARTIAL`, `STALE`, `BLOCKED`, `ERROR`, and `AWAITING_HUMAN_REVIEW` must keep
  `can_show_complete=false`.
- No case can authorize final merge.
- No case can promote Memory.
- Every case must preserve `UNTRUSTED_DATA` and `no_trade_flag=true`.

## 7. Responsive Acceptance

Desktop view:

- request header, task preview, and run projection are visible without opening a
  modal;
- evidence table keeps source, tier, fact, publish date, and cutoff readable;
- audit strip remains visible below the primary work area.

390px mobile view:

- no horizontal text overflow for workflow, owner, reviewer, and status labels;
- evidence rows collapse into stacked facts rather than shrinking into
  unreadable columns;
- primary action stays below the current state, not above the evidence;
- audit strip remains visible before any Human Review action.

## 8. Phase 3 Done

Phase 3 is done when:

1. A Product-AIOS Bridge page contract exists.
2. Five acceptance cases cover the current H7 states.
3. Every case visibly explains why it is not complete.
4. Human Review and final merge authority remain human-only.
5. Responsive acceptance is stated for desktop and 390px mobile.
6. Offline tests prove the fixture cannot silently turn partial/stale/blocked
   cases into success.
7. Offline tests prove every case preserves the same Product-AIOS trace id,
   binds every stage to an artifact hash, rejects packet tampering, and cannot
   bind trace data from chat history or raw model output.

Not a trading instruction; AI produces evidence only, human decides.
