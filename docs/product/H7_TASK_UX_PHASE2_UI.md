# H7 Task UX Phase 2 UI Contract

Status: `DRAFT / OFFLINE / PHASE_2`

Owner: Reed. Product UI implementer: Better. Workflow reviewer: Simon.
Safety/eval reviewer: Jason. Final merge authority: Junyan.

Related: #277, #280, #281, #287, #288.

## 1. Purpose

Phase 1 defined the product-to-`ai-task.v1` packet. Phase 2 defines how a
front-end surface should render that packet without inventing AIOS behavior.

The UI contract is a view model only:

`H7 packet -> status projection -> evidence surface -> Human Review controls`

It does not call a model, dispatch an Agent, approve a task, write Memory,
write production data, or change Router, Context, Policy, Scheduler, Runtime,
or permission logic.

## 2. First Screen

The first usable H7 screen is an internal task workbench, not a landing page.
It must show the current task request and the AIOS result state in the same
viewport:

1. Request summary: workflow, owner, reviewer, budget, cutoff, source issue.
2. Canonical task preview: task id, risk, network policy, file scope, forbidden
   scope, budget, acceptance checks.
3. AIOS state: one of the five current H7 statuses from Phase 1.
4. Evidence table: source, tier, publish date, data cutoff, fact, verification.
5. Missing or blocked items: visible for every current state.
6. Human Review dock: pending, approved, revise, or rejected. Human approval is
   never inferred from model text or comments.
7. Audit strip: no trade flag, untrusted external content, generated time,
   prompt version, and final merge authority.

## 3. State Rendering Rules

| H7 status | UI tone | Primary user action | Must stay visible |
|---|---|---|---|
| `PARTIAL` | `warning` | Fill missing evidence | missing_evidence |
| `STALE` | `stale` | Refresh context before review | data cutoff and stale warning |
| `BLOCKED` | `blocked` | Edit request | blocking_reasons; no runnable task |
| `ERROR` | `error` | Inspect error and retry after fix | error_code |
| `AWAITING_HUMAN_REVIEW` | `review` | Request or perform human review | pending reviewer and no decision_ref |

The UI must not color `PARTIAL`, `STALE`, `BLOCKED`, `ERROR`, or
`AWAITING_HUMAN_REVIEW` as success. HTTP 200, file existence, or non-empty model
text is not enough to show `COMPLETE`. `COMPLETE` is a future A-020 state and
is not present in the Phase 2 fixtures.

## 4. Allowed Controls

The UI may expose only these Phase 2 controls:

- `CREATE_TASK_PREVIEW`: compile a preview from already-entered fields.
- `EDIT_REQUEST`: return to the product input form.
- `REFRESH_CONTEXT_REQUEST`: ask the approved Context layer to refresh later.
- `REQUEST_HUMAN_REVIEW`: create a visible human-review request later.
- `VIEW_EVIDENCE`: open or expand evidence rows.
- `COPY_TASK_ID`: copy the task id only.

None of these controls may:

- call a provider model directly;
- write GitHub comments;
- approve Human Review automatically;
- write Memory;
- write production data;
- authorize final merge;
- hide missing evidence or stale context.

## 5. Handoff Boundaries

| Boundary | Phase 2 rule |
|---|---|
| Product input | H7 owns labels, required fields, disabled states, and user copy. |
| Task compiler | H7 may preview compiler output but does not change compiler rules. |
| Context | H7 shows freshness and source metadata; Context retrieval remains owned elsewhere. |
| Policy | H7 shows risk, budget, and network policy; it does not make policy decisions. |
| Router | H7 does not send a Router request. `workflow_type` is UI metadata only. |
| Executor | H7 shows output state; it does not run Agents. |
| Human Gate | H7 renders review controls; explicit human decision is required. |
| Memory | H7 shows whether output is promotable; promotion is outside Phase 2. |

## 6. Acceptance

1. Five UI state fixtures exist, exactly matching the current Phase 1 statuses.
2. Every fixture references a Phase 1 packet status and preserves
   `no_trade_flag=true`.
3. Current states cannot expose a `success` tone or hide the reason they are
   not complete.
4. Human Review controls cannot create final merge authorization.
5. All controls are offline view-model controls: no provider call, no GitHub
   write, no production write, no Memory write.
6. Secret-like values are rejected from labels, messages, and control metadata
   without echoing the supplied value.

Not a trading instruction; AI produces evidence only, human decides.
