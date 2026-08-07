# AIOS-K2 Policy And Context Spec

> Owner: Reed. Reviewer: Junyan. Partner: Jason.
> Status: DRAFT / SPEC ONLY.
> Scope: A-009 Policy Engine, A-010 Context Builder, A-011 Scheduler contract,
> A-012 Lease/heartbeat/file lock contract.

This document is the handoff contract before K2 implementation. It does not
start production execution, call model APIs, write GitHub automatically, or
change any research rule.

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
- No Scheduler implementation until K1 is merged and reviewed.
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
| `task_type` | Selects policy, context recipe, and Router candidate class |
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

## 4. K2 Output Envelope

K2 produces one envelope. Router may run only when `policy_status` is
`POLICY_ALLOWED` and `context_status` is `CONTEXT_READY`.

```json
{
  "schema": "aios-policy-context-envelope.v1",
  "task_id": "A-009-example",
  "policy_status": "POLICY_ALLOWED",
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
8. `HIGH` and `CONSTITUTIONAL` tasks include an independent `reviewer_agent`.
9. `CONSTITUTIONAL` tasks have explicit Junyan approval evidence before action.
10. Secret-like strings in task inputs are blocked or redacted before context
    construction.
11. External text is marked untrusted and cannot modify system instructions.

Network mapping for Router:

| Task manifest `network_policy` | Router `network_policy` | Meaning |
|---|---|---|
| `OFFLINE` | `deny` | No network during execution |
| `ALLOWLIST` | `provider_only` | Only approved provider or source endpoints |
| `LIVE_DATA` | `provider_only` | Allowed only with explicit task-level source list |

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
| `task_type` | K1/K2 task contract | Yes | Must be supported by capability registry |
| `mode` | Policy Engine | Yes | No defaulting; `SHADOW` is not production approval |
| `required_tools` | Context Builder | Yes | Minimum tools only |
| `target_paths` | Context Builder | Yes | Already checked against scope |
| `network_policy` | Policy Engine | Yes | `deny` or `provider_only` |
| `risk_level` | Policy Engine | Yes | Preserved into decision record |
| `budget_max_cny` | Policy Engine | Yes | Finite, non-negative string |
| `reviewer_agent` | Policy Engine | High risk | Must differ from selected executor |

Router must preserve `mode` in `RouteDecision`. It may not infer mode from
branch names or default missing mode to `SHADOW`.

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
| Secret-like fixture appears in task input | `POLICY_BLOCKED` |
| External text includes "ignore previous instructions" | Mark untrusted, ignore instruction |
| `HIGH` task lacks `reviewer_agent` | `POLICY_BLOCKED` |
| `reviewer_agent` equals selected executor | Router must reject |
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

## 11. Open Decisions For Junyan

1. Whether K2 v0 may include Scheduler/Lease implementation, or whether those
   stay as spec until Policy/Context tests pass.
2. Whether `ALLOWLIST` and `LIVE_DATA` both map to Router `provider_only`, or
   whether `LIVE_DATA` should be a separate Router policy.
3. Whether `HIGH` risk reviewer independence must be agent-name level for v0, or
   provider-level from day one.
4. Whether K2 can auto-comment `POLICY_BLOCKED` findings to #164, or must remain
   local-only until K4 Human Gate exists.

## 12. Acceptance For This Spec PR

- The document is added under Reed's boundary `docs/llm/`.
- It defines K2 input, output, block states, Router handoff, and tests.
- It does not implement execution.
- It does not call any model or external data source.
- It does not contain secrets or production credentials.
- It preserves Junyan as the approval owner for risky gates.

不是买卖指令;研究信号,human executes.
