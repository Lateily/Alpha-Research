# AIOS-K2 Policy And Context Spec

> Owner: Reed. Reviewer: Junyan. Partner: Jason.
> Status: DRAFT / POLICY GATE V0.
> Scope: A-009 Policy Engine, A-010 Context Builder, A-011 Scheduler contract,
> A-012 Lease/heartbeat/file lock contract.

This document is the handoff contract for K2 implementation. Current code
implements the deterministic Policy Gate only. It does not start production
execution, call model APIs, write GitHub automatically, or change any research
rule.

## 1. Plain-English Goal

K1 answers: "What task exists, what state is it in, and has the declared work
really happened?"

K2 answers: "Is this task allowed to run, what exact context may the Agent read,
and what must be blocked before Router or execution starts?"

In simple terms: K2 is the security guard and briefing officer. It checks the
door, budget, risk, files, network, approvals, and context package before any
Agent is selected.

## 2. Non-Goals

- No Agent execution.
- No Scheduler implementation until Policy/Context tests pass.
- No frontend integration.
- No model API calls.
- No automatic GitHub comments beyond the existing Progress Board protocol.
- No changes to research verdicts, portfolio rules, or Junyan approval gates.

## 3. Inputs

K2 consumes an `ai-task.v1` manifest produced by K1 Task Compiler and confirmed
by K1 Registry/Reconciler.

Required fields from the task manifest:

| Field | Why K2 needs it |
|---|---|
| `task_id` | Stable audit id and idempotency key |
| `objective` | Checks whether the task is specific enough to run |
| `human_owner` | Accountable human |
| `reviewer` | Review and approval owner |
| `file_scope` | Maximum allowed read/write file boundary |
| `forbidden_scope` | Paths that must never be touched |
| `authority_docs` | Documents that define the task contract |
| `acceptance_tests` | Minimum proof expected from execution |
| `risk_level` | Determines gates and reviewer independence |
| `network_policy` | Determines whether network is denied or allowlisted |
| `budget.max_cny` | Hard upper cost bound |
| `approval_gates` | Human gates that must exist before risky execution |
| `created_at` | Freshness and stale-task checks |

Missing, malformed, contradictory, or unsupported required fields produce
`SPEC_BLOCKED`. K2 must not infer missing authority from chat memory.

Current #248 `ai-task.v1` does not yet include `task_type`. Router must not
infer it from prose, branch names, or file paths. Before K2 implementation,
Junyan must approve one authoritative source:

- add `task_type` to `ai-task.v1`; or
- add a deterministic K2 task-classification table whose output is stored in
  the K2 envelope before Router is called.

Until that source exists, any handoff that lacks explicit `task_type` is
`SPEC_BLOCKED`.

When supplied, `task_type` must be a Router-compatible canonical lowercase
token, for example `docs_contract` or `event_tagging`. K2 and Router must not
strip, lowercase, or otherwise repair non-canonical task types at handoff time.

## 4. K2 Output Envelope

K2 produces one envelope. Router may run only when `policy_status` is
`POLICY_ALLOWED` and `context_status` is `CONTEXT_READY`.

```json
{
  "schema": "aios-policy-context-envelope.v1",
  "task_id": "A-009-example",
  "policy_status": "POLICY_ALLOWED",
  "policy_decision_hash": "sha256:...",
  "policy_reasons": [],
  "context_status": "CONTEXT_READY",
  "context_hash": "sha256:...",
  "authority_docs": [
    "AGENTS.md",
    "docs/llm/AI_OS_BUILD_GUIDE.md"
  ],
  "context_manifest": {
    "paths": [],
    "commit_sha": "",
    "loaded_at": "",
    "content_hash": "sha256:...",
    "freshness": "FRESH",
    "excluded_conflicts": []
  },
  "route_request": {
    "task_type": "docs_contract",
    "mode": "SHADOW",
    "required_tools": ["git", "filesystem"],
    "target_paths": ["docs/llm/AIOS_K2_POLICY_CONTEXT_SPEC.md"],
    "network_policy": "deny",
    "risk_level": "LOW",
    "budget_max_cny": "0",
    "reviewer_agent": null
  }
}
```

Allowed `policy_status` values:

- `POLICY_ALLOWED`: Router may be called.
- `POLICY_BLOCKED`: Policy hard gate failed. Router must not be called.
- `SPEC_BLOCKED`: Task contract or authority context is incomplete or
  contradictory. Router must not be called.

Allowed `context_status` values:

- `CONTEXT_READY`: Context package is complete and hashable.
- `CONTEXT_BLOCKED`: Required context is missing, stale, contradictory, or
  outside authority.

## 5. Policy Engine Responsibilities

Policy Engine is deterministic. It should not ask an LLM whether a task is
allowed.

It must check:

1. `target_paths` are inside `file_scope`.
2. `target_paths` are outside `forbidden_scope`.
3. No task touches `experiments/execution_tracker/`.
4. `network_policy` can be safely mapped to Router policy.
5. `budget.max_cny` is present, finite, non-negative, and a string amount.
6. `risk_level` is one of `LOW`, `MEDIUM`, `HIGH`, `CONSTITUTIONAL`.
7. `mode` is explicit: `SHADOW` or `PRODUCTION`.
8. `MEDIUM + PRODUCTION` is blocked until registry-backed reviewer
   capabilities and K2 Human Gate are wired.
9. `HIGH` and `CONSTITUTIONAL` are blocked in all modes until registry-backed
   reviewer capabilities and K2 Human Gate are wired.
10. `CONSTITUTIONAL` tasks have structured Junyan approval evidence with an
    audit anchor before action.
11. Secret-like strings in task inputs are blocked or redacted before context
    construction.
12. External text is marked untrusted and cannot modify system instructions.

Network mapping for Router:

| Task manifest `network_policy` | Router `network_policy` | Meaning |
|---|---|---|
| `OFFLINE` | `deny` | No network during execution |
| `ALLOWLIST` | `provider_only` | Only when structured allowlist evidence names approved endpoints and an audit anchor |
| `LIVE_DATA` | `TBD` | `POLICY_BLOCKED` until Junyan approves the mapping |

Unsupported network values produce `POLICY_BLOCKED`.

## 6. Context Builder Responsibilities

Context Builder creates a reproducible context package. It should not pick a
convenient document when authority conflicts exist.

Required read order:

1. `AGENTS.md` red lines and progress protocol pointer.
2. `docs/llm/AI_OS_BUILD_GUIDE.md`.
3. `docs/llm/AI_OS_ENGINEERING_BACKLOG.md`.
4. Task manifest `authority_docs`.
5. Linked Issue and PR states.
6. Current branch, dirty files, and recent relevant commits.
7. Relevant schemas, fixtures, tests, and latest validation output.
8. Explicitly excluded stale or conflicting documents.

The context manifest must include:

| Field | Meaning |
|---|---|
| `paths` | Files and issue/PR references loaded |
| `commit_sha` | Repository commit used for context |
| `loaded_at` | UTC timestamp |
| `content_hash` | Hash of the package |
| `freshness` | `FRESH`, `STALE`, or `UNKNOWN` |
| `excluded_conflicts` | Documents intentionally excluded and why |

If two authority documents conflict and no human decision exists, K2 returns
`SPEC_BLOCKED`.

## 7. Router Handoff Contract

K2 does not choose the Agent. It only constructs the safe `RouteRequest`.

Router may run only after:

```text
K2 Policy Engine
    -> POLICY_BLOCKED or SPEC_BLOCKED: stop, do not call Router
    -> POLICY_ALLOWED: build context package

K2 Context Builder
    -> CONTEXT_BLOCKED: stop, do not call Router
    -> CONTEXT_READY: send RouteRequest to Router
```

`RouteRequest` fields:

| Field | Source | Required | Rule |
|---|---|---:|---|
| `task_type` | Approved K2 source | Yes | Must be explicit and supported by capability registry |
| `mode` | Policy Engine | Yes | No defaulting; `SHADOW` is not production approval |
| `required_tools` | Context Builder | Yes | Minimum tools only |
| `target_paths` | Context Builder | Yes | Already checked against scope |
| `network_policy` | Policy Engine | Yes | `deny` or `provider_only` |
| `risk_level` | Policy Engine | Yes | Future Router integration requirement; current #246 does not preserve it |
| `budget_max_cny` | Policy Engine | Yes | Finite, non-negative string |
| `reviewer_agent` | Policy Engine | High risk | Must differ from selected executor |

Router must preserve `mode` in `RouteDecision`. It may not infer mode from
branch names or default missing mode to `SHADOW`.

Risk preservation is a K2/K3 integration requirement, not a statement about the
current #246 Router implementation. Current #246 preserves `mode`,
`selected_agent`, and `reasons`; K2 should not require more from #246 until the
Router contract is explicitly expanded.

## 8. Scheduler And Lease Boundary

K2 defines the gate, not the full executor.

Scheduler can consider a task only when:

- K1 state is `SPEC_READY` or a later allowed state.
- K2 returns `POLICY_ALLOWED` and `CONTEXT_READY`.
- Dependencies are merged, completed, or explicitly waived by Junyan.
- No active CLAIM overlaps the same write paths.
- The lease duration and heartbeat owner are known.

Lease/file lock rules:

- Read-only audits may run in parallel.
- Two write tasks with overlapping `target_paths` cannot run in parallel.
- Expired leases can be released only by deterministic replay of CLAIM,
  heartbeat, DONE, BLOCKED, or RELEASE events.
- Re-running the same `task_id + context_hash + target_paths` must be
  idempotent.

## 9. Fail-Closed Test Matrix

K2 implementation must include negative tests before it can move beyond this
spec.

| Case | Expected result |
|---|---|
| Missing `authority_docs` | `SPEC_BLOCKED` |
| Conflicting authority docs | `SPEC_BLOCKED` |
| Missing `acceptance_tests` | `SPEC_BLOCKED` |
| `target_paths` outside `file_scope` | `POLICY_BLOCKED` |
| `target_paths` inside `forbidden_scope` | `POLICY_BLOCKED` |
| `experiments/execution_tracker/` target | `POLICY_BLOCKED` |
| `budget.max_cny` missing | `SPEC_BLOCKED` |
| `budget.max_cny` is `NaN`, `Infinity`, negative, or numeric | `SPEC_BLOCKED` |
| Missing explicit `mode` | `SPEC_BLOCKED` |
| Unsupported `mode` | `SPEC_BLOCKED` |
| Unsupported `network_policy` | `POLICY_BLOCKED` |
| `ALLOWLIST` without endpoint and approval evidence | `POLICY_BLOCKED` |
| Secret-like fixture appears in task input | `POLICY_BLOCKED` |
| External text includes "ignore previous instructions" | Mark untrusted, ignore instruction |
| `MEDIUM + PRODUCTION` before reviewer capabilities | `POLICY_BLOCKED` |
| Any `HIGH` or `CONSTITUTIONAL` task before reviewer capabilities | `POLICY_BLOCKED` |
| Name-only reviewer difference is supplied | Must not produce `POLICY_ALLOWED` for high-risk routing |
| `POLICY_BLOCKED` task attempts Router call | Test must fail |
| Stale context package | `CONTEXT_BLOCKED` |
| Context hash changes after package creation | `CONTEXT_BLOCKED` |
| Active overlapping CLAIM exists | Scheduler blocked |
| Circular dependency exists | Scheduler blocked |

## 10. Reed And Jason Split

Reed owns K2 Policy/Context:

- Task policy envelope.
- Context manifest and authority hash.
- Fail-closed fixtures.
- Scheduler and lease contract.

Jason owns Router integration:

- Capability records.
- RouteRequest consumption.
- Agent selection rules.
- Router negative tests from #246 review.

The handoff line is strict: K2 says whether Router is allowed to run and gives a
validated `RouteRequest`. Router picks the Agent only inside that boundary.

## 11. Implementation Sequence

K2 should move in small, reviewable steps. This avoids building against an
unstable K1 contract or silently expanding Router authority.

This PR is now A-009 Policy Gate Phase 1:

- Document the Policy/Context envelope.
- Record Jason's Router-side constraints.
- Add `scripts/llm/ai_os/policy_engine.py`.
- Add offline fail-closed tests for budget, risk, mode, network, path scope,
  forbidden scope, secret-like strings, and external-instruction handling.
- Keep `LIVE_DATA` blocked until Junyan chooses a mapping.
- Keep `ALLOWLIST` blocked until a trusted provider allowlist registry is wired.
- Bind each decision to `task_id` with a stable `policy_decision_hash`.
- Register critical K2 gates in the governance mutation gate.
- Keep the branch free of model calls, GitHub writes, Router calls, scheduler
  execution, and production data mutation.

Later phases stay separate PRs:

- A-010 Context Builder builds hashable context packets from authority docs,
  task manifests, relevant issue/PR state, schemas, fixtures, and validation
  output.
- A-011 Scheduler blocks tasks with unfinished dependencies, stale context,
  policy/spec failures, or dependency cycles.
- A-012 Lease/heartbeat/file lock prevents overlapping write execution and
  releases expired leases safely.

Phase 3 connects to Router after #246 is merged and its contract is stable:

- Construct `RouteRequest` only from K2-approved fields.
- Preserve `mode`; do not infer missing `task_type`.
- Treat `risk_level` preservation as a future Router contract expansion unless
  #246 adds it first.

## 12. Open Decisions For Junyan

1. Whether K2 v0 may include Scheduler/Lease implementation, or whether those
   stay as spec until Policy/Context tests pass.
2. Whether `LIVE_DATA` maps to Router `provider_only`, becomes a separate
   Router policy, or remains blocked for K2 v0.
3. Whether `HIGH` risk reviewer independence must be agent-name level for v0, or
   provider-level from day one.
4. Whether K2 can auto-comment `POLICY_BLOCKED` findings to #164, or must remain
   local-only until K4 Human Gate exists.

## 13. Acceptance For This A-009 Policy Gate PR

- The document stays under Reed's boundary `docs/llm/`.
- The deterministic Policy Gate implementation stays under `scripts/llm/ai_os/`.
- The output contract is documented under `scripts/llm/schemas/`.
- Offline tests cover required manifest fields, budget, mode, network, path
  scope, forbidden scope, unsafe scope definitions, secret-like input, external
  instruction handling, risk gates, approval evidence, and decision hashing.
- Critical K2 gates are registered in the governance mutation gate.
- It does not execute Agents, call Router, call any model, read live data, write
  GitHub, or modify production data.
- It does not contain secrets or production credentials.
- It preserves Junyan as the approval owner for risky gates.

不是买卖指令;研究信号,human executes.
