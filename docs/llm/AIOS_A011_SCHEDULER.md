# AIOS A-011 Scheduler

Owner: Reed. Reviewer: Junyan. Scope: offline AIOS control plane.

## Purpose

Scheduler decides whether compiled AIOS tasks are ready to enter the Harness.
It does not execute agents. It only returns a schedule report that separates
ready tasks from blocked tasks with explicit reasons.

## Inputs

- Compiled `ai-task.v1` manifests.
- A read-only registry snapshot.
- Policy decision records supplied by A-009.
- Context packet records supplied by A-010.

## Output

The output schema is `scripts/llm/schemas/schedule.schema.json`.

Each report includes:

- `ready`: tasks allowed to move toward dispatch.
- `blocked`: tasks that must not enter Router or Harness.
- `invalid_inputs`: malformed scheduler inputs.

## Fail-Closed Rules

Scheduler blocks a task when:

- a dependency is missing or not `DONE`;
- two tasks depend on each other in a cycle;
- the policy decision is missing or not `POLICY_ALLOWED`;
- the context packet is missing or not `CONTEXT_READY`;
- the context is not `PINNED`;
- the context is older than the configured freshness window;
- the manifest is malformed.

`POLICY_BLOCKED` and `SPEC_BLOCKED` do not enter Router.

## Non-Goals

- It does not call model APIs.
- It does not call Router.
- It does not execute Agents.
- It does not write GitHub comments.
- It does not modify production data.
- It does not approve, merge, or deploy tasks.

## Local Commands

Build a schedule from a fixture:

```powershell
py -3.11 scripts/llm/ai_os/cli.py schedule --input schedule_fixture.json
```

Run offline verification:

```powershell
py -3.11 tests/test_ai_os_a011_scheduler_offline.py
```

Not a trading instruction; research signal, human executes.
