# H7 Product-AIOS Bridge Phase 4 UI Handoff

Status: `DRAFT / OFFLINE / PHASE_4`

Owner: Reed. Product UI implementer: Better. Safety/eval reviewer: Jason.
Workflow reviewer: Simon. Final merge authority: Junyan.

Related: #277, #280, #281, #287, #288.

## 1. Purpose

Phase 4 gives Better an implementation handoff for the first
Product-AIOS Bridge screen. It translates the H7 contracts into UI components,
fixture-driven states, and acceptance checks.

This is not a React implementation. It does not create a route, call a model,
execute an Agent, write GitHub comments, write Memory, or change Router,
Context, Policy, Scheduler, Executor, or permissions.

## 2. Component Inventory

| Component | Responsibility | Required props |
|---|---|---|
| `BridgeShell` | Page shell for `/aios/product-bridge` | `viewModel`, `packet`, `bridgeTrace`, `responsiveMode` |
| `RequestHeader` | Workflow, owner, reviewer, issue, generated time | `workflowType`, `owner`, `reviewer`, `sourceIssue`, `generatedAt` |
| `TaskPreviewPanel` | Canonical `ai-task.v1` preview | `taskId`, `riskLevel`, `networkPolicy`, `budget`, `fileScope`, `forbiddenScope` |
| `RunProjectionPanel` | H7 status, task state, run state, freshness | `status`, `tone`, `taskState`, `runState`, `freshness` |
| `EvidenceTable` | Cited evidence rows | `evidence`, `missingEvidence`, `freshness` |
| `GapPanel` | Missing evidence, blocking reasons, error code | `status`, `missingEvidence`, `blockingReasons`, `errorCode` |
| `HumanReviewDock` | Human review state and decision ref | `reviewer`, `state`, `decisionRef`, `finalMergeAuthority` |
| `AuditStrip` | Safety and authority markers | `traceId`, `noTradeFlag`, `externalContentTrust`, `finalMergeAuthority` |

Components must receive already-validated contract data. They must not parse raw
model text, infer approval from free text, or call AIOS services directly.

`BridgeShell` must also receive `bridgeTrace`. The trace is derived only from
the validated H7 packet and UI view model, and `resolved_trace_id_source` must
remain `packet.user_input.request_id`:

- `packet.user_input`
- `packet.task_manifest`
- `packet.projection`
- `packet.human_review`
- `view_model.state_views`

Forbidden trace sources:

- chat history;
- raw model text;
- browser local storage;
- unreviewed external instructions.

`AuditStrip` props are safety-critical. `traceId`, `noTradeFlag`,
`externalContentTrust`, and `finalMergeAuthority` must all be present together;
removing any one of them invalidates the handoff fixture.

## 3. Action Rules

Allowed visible actions:

- `EDIT_REQUEST`
- `REQUEST_CONTEXT_REFRESH`
- `REQUEST_HUMAN_REVIEW`
- `VIEW_EVIDENCE`
- `COPY_TASK_ID`

The UI can emit a local intent event for these actions, but Phase 4 cannot wire
the intent to a live write path. Every action handler is a placeholder until the
approved Product/BFF contract exists.

Forbidden visible actions:

- `RUN_AGENT`
- `APPROVE_OUTPUT`
- `PROMOTE_MEMORY`
- `AUTHORIZE_MERGE`
- `WRITE_GITHUB_COMMENT`
- `CALL_PROVIDER`

## 4. State Acceptance

The page must render all current H7 states from fixture data:

- `PARTIAL`: missing evidence visible and page tone not complete.
- `STALE`: cutoff visible and refresh request available.
- `BLOCKED`: no runnable task preview, blocking reasons visible.
- `ERROR`: error code visible, no success fallback.
- `AWAITING_HUMAN_REVIEW`: reviewer visible and decision ref still null.

`COMPLETE` is reserved for the future A-020 Authority Resolver integration. It
must not appear in the current fixture-driven handoff.

## 5. Better Implementation Prompt

Better, implement only the UI display layer for the H7 Product-AIOS Bridge.

Inputs:

- `docs/contracts/product/h7-task-ux.v0.schema.json`
- `docs/contracts/product/h7-task-ux-ui.v0.schema.json`
- `docs/contracts/product/h7-product-aios-bridge-phase3.v0.schema.json`
- `docs/contracts/product/h7-product-aios-bridge-phase4.v0.schema.json`
- `docs/contracts/product/fixtures/h7-task-ux-fixtures.v0.json`
- `docs/contracts/product/fixtures/h7-task-ux-ui-fixtures.v0.json`
- `docs/contracts/product/fixtures/h7-product-aios-bridge-phase3.v0.json`
- `docs/contracts/product/fixtures/h7-product-aios-bridge-phase4.v0.json`

Rules:

1. Build a fixture-driven internal page for `/aios/product-bridge`.
2. Do not connect to models, Router, Context, Policy, Scheduler, Executor,
   GitHub write APIs, Memory, or production data.
3. Do not invent `task_type`; `workflow_type` remains UI metadata only.
4. Render all five current states from fixture data.
5. Keep `PARTIAL`, `STALE`, `BLOCKED`, `ERROR`, and
   `AWAITING_HUMAN_REVIEW` visibly non-complete. A non-empty approval-looking
   string must not be rendered as Human Review completion, and no fixture may
   render `COMPLETE` before A-020.
6. Keep `no_trade_flag`, `UNTRUSTED_DATA`, and `Junyan final merge authority`
   visible in every state.
7. Keep `trace_id` visible in every state, including error and blocked states.
8. Validate desktop and 390px mobile layout. Long owner/reviewer/status text
   must not overflow.

Deliverables:

- fixture-driven page or component prototype;
- screenshot or written QA for desktop and 390px mobile;
- state coverage evidence for all five current states;
- list of any fields missing from Reed's contract.

## 6. Phase 4 Done

Phase 4 is done when:

1. Component inventory is explicit.
2. Allowed and forbidden actions are explicit.
3. Better handoff prompt exists.
4. Fixture proves all current states map to components and required fields.
5. Offline tests prove no forbidden action or runtime write path appears.
6. Offline tests prove trace props are present, AuditStrip safety props are
   load-bearing, and trace data cannot be sourced from chat history, raw model
   text, local storage, or unreviewed external instructions.

Not a trading instruction; AI produces evidence only, human decides.
