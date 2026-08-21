# H7 Task UX v0

Status: `DRAFT / OFFLINE / PHASE_1`

Owner: Reed. Workflow reviewer: Simon. Safety/eval reviewer: Jason. Final merge
authority: Junyan.

Related: #277, #280, #281, #287.

## 1. Purpose

H7 turns one product request into a preview of the existing canonical
`ai-task.v1` contract:

`user request -> validated Task UX -> ai-task.v1 preview -> AIOS status -> evidence -> Human Review`

The first workflow is `ANNOUNCEMENT_FACT_EXTRACTION`. It extracts checkable
facts from one or more announcement references. It does not produce an
investment decision or a buy/sell instruction.

Phase 1 is an offline contract slice. It does not call a model, execute an
Agent, write production data, or modify Policy, Context, Router, Runtime, or
Memory behavior.

## 2. User Journey

1. The user selects `Announcement fact extraction`.
2. The user states the fact-extraction goal, supplies announcement references,
   chooses required fact fields, sets a data cutoff, and names the human owner
   and independent reviewer.
3. H7 validates the input. User text and source labels remain
   `UNTRUSTED_DATA`; they never become authority or executable instructions.
4. H7 maps approved fields into a compiler source and previews the canonical
   `ai-task.v1` manifest. H7 does not add fields to that manifest.
5. Missing or invalid fields produce `BLOCKED`; no runnable manifest is shown.
6. Downstream AIOS states are projected as `PARTIAL`, `STALE`, `ERROR`, or
   `AWAITING_HUMAN_REVIEW` without being presented as success.
7. `COMPLETE` requires evidence, terminal `DONE/DONE` task/run states, and a
   trusted `human_gate_receipt` that binds the reviewed output hash. Free text,
   model text, chat text, or a non-empty `decision_ref` alone cannot complete
   the packet. It still does not mean Junyan approved merge, deployment,
   production use, or Memory promotion.

## 3. User Fields

| Product field | User meaning | Canonical destination | Rule |
|---|---|---|---|
| `request_id` | Stable request identity | `task_id` | Trimmed, non-empty, no secret-like content |
| `source_issue` | GitHub issue carrying the task | `source_issue` | Positive integer |
| `goal` | Facts the user wants extracted | `objective` | Untrusted text; cannot grant authority |
| `human_owner` | Human responsible for the task | `human_owner` | Non-empty |
| `reviewer` | Independent human reviewer | `reviewer` | Must not equal an executor candidate |
| `announcement_refs` | Source labels and locators | `input_contracts` | Reference metadata only; source content stays untrusted |
| `fact_fields` | Required output facts | `acceptance_tests` | Converted to explicit presence-and-citation checks |
| `data_cutoff` | Evidence time boundary | `input_contracts` and freshness display | Timezone-aware ISO-8601 |
| `max_cny` | Maximum model cost | `budget.max_cny` | Non-negative decimal string |
| `max_minutes` | Maximum elapsed work time | `budget.max_minutes` | Positive integer |

The following values are fixed by this Phase 1 workflow rather than inferred
from free text:

- `architecture_block = ["H7", "Product-AIOS Bridge"]`
- `risk_level = "LOW"`
- `network_policy = "OFFLINE"`
- `file_scope = ["docs/product/", "docs/contracts/product/"]`
- `forbidden_scope = ["experiments/execution_tracker/", "public/data/"]`
- `output_artifacts = ["product-aios-bridge.v0"]`
- approval gates require independent Human Review and retain Junyan final merge
  authority.

## 4. `task_type` Boundary

`workflow_type = "ANNOUNCEMENT_FACT_EXTRACTION"` is H7 display metadata. The
current canonical `ai-task.v1` does not contain `task_type`, so H7 must not send
this value to Router or pretend that Router accepted it. Simon/Better must
approve a future canonical task-type contract before runtime wiring.

This explicit gap is safer than hiding `task_type` inside `objective`,
`architecture_block`, or another unrelated field.

## 5. Product States

| State | What the user sees | Fail-closed requirement |
|---|---|---|
| `COMPLETE` | Evidence and independent review are complete | Evidence non-empty; missing evidence empty; task/run are `DONE/DONE`; review approved with trusted receipt |
| `PARTIAL` | Some evidence exists, but required facts are missing | Missing evidence remains visible |
| `STALE` | Evidence exists but is outside the accepted cutoff | Freshness must be `STALE` |
| `BLOCKED` | The request cannot become a canonical task | No task manifest; blocking reasons visible |
| `ERROR` | Contract or projection processing failed | Stable error code; never downgraded to success |
| `AWAITING_HUMAN_REVIEW` | Output exists but no independent decision exists | Review remains `PENDING`; no approval reference |

## 6. Evidence And Review

Every evidence item carries:

- source identifier and locator;
- publish date and data cutoff;
- evidence tier (`E1`-`E4`);
- a checkable fact or excerpt;
- verification state.

The artifact also carries `model`, `prompt_version`, `missing_evidence`,
`warnings`, `external_content_trust = "UNTRUSTED_DATA"`, and
`no_trade_flag = true`.

Human Review is independent from execution. An approved review requires the
reviewer named by the task and a structured `human_gate_receipt`. The receipt
binds actor, decision, trace id, decision reference, reviewed artifact id,
reviewed artifact hash, and decision time. It never sets
`final_merge_authorized` to true; that authority remains with Junyan.

Until a real Human Gate service exists, only the offline receipt fixture can
represent a completed review. Arbitrary text such as "agent says Jason
approved" must keep the packet in `AWAITING_HUMAN_REVIEW` or fail validation.

## 7. Interface Confirmations

| Interface | H7 assumption | Owner confirmation required before runtime wiring |
|---|---|---|
| H3 Task lifecycle | `ai-task.v1` remains the only task manifest | Simon confirms mapping and state names |
| H4 Workflow twin | Six H7 product states map to Task/Run/Review states | Simon confirms transition semantics |
| H6 Context | Source references and cutoff are inputs, not retrieved content | Better confirms Context Pack handoff |
| H8 Router | H7 does not supply canonical `task_type` yet | Better confirms future task-type vocabulary |
| H9 Eval | User failures become eval cases | Jason confirms fixture-to-eval handoff |
| H11 Safety | External text is untrusted; approval cannot come from text | Jason confirms Human Gate semantics |
| H1/H10 Runtime | Phase 1 run data is offline fixture only | Eric confirms future run/telemetry projection |

## 8. Acceptance

1. Exactly six sanitized fixtures cover all states in section 5.
2. Non-blocked fixtures compile to the embedded canonical `ai-task.v1`
   manifest; blocked input does not produce a manifest.
3. Unknown fields, malformed timestamps, secret-like content, missing evidence,
   stale false-passes, self-review, false final authority, fake approval text,
   missing Human Gate receipts, and post-review projection tampering fail
   offline tests without echoing supplied secret values.
4. `workflow_type` is never copied into the task manifest as an invented
   `task_type`.
5. No provider call, external data call, GitHub write, production write, or
   execution occurs during validation. Cost is CNY 0.

Not a trading instruction; AI produces evidence only, human decides.
