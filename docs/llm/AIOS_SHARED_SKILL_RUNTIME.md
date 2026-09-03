# AIOS Shared Skill Runtime

Status: provider-neutral offline slice. Code delivery does not grant merge,
deployment, provider, research, or trading authority.

## Boundary

`run_adapter()` is the existing Agent Harness entrypoint. A caller may attach a
`RepositorySkillSelection` containing ordered Skill IDs and the authoritative
executor role. The repository root is pinned from the Harness code location and
cannot be supplied by the request. Before `AgentAdapter.execute()` can run, the
harness:

1. validates the ordinary `AgentRequest`;
2. loads the selection through `ai_os.skill_registry`;
3. enforces canonical paths, hashes, role policy, reserved delimiters, and an
   `OFFLINE` Skill network ceiling;
4. rejects a rendered Skill context above 60,000 characters;
5. prepends the verified Skill blocks as the first system message;
6. records Skill, prompt, content, reference, and rendered-context provenance;
7. computes the result input hash from the derived payload, including the
   verified Skill receipts.

Any failure before step 5 returns `SPEC_BLOCKED` with error code
`SKILL_CONTEXT_BLOCKED`. The public error is deliberately generic and the
worker/provider is not called.

## Trusted Diagnostics

Callers may provide `skill_diagnostic_sink` to `run_adapter()` when an approved
control-plane or operations boundary needs to distinguish blocked gates. The
sink receives one immutable `RepositorySkillDiagnostic` containing only:

- `run_id`;
- `blocked_gate`.

Stable gates are `SELECTION`, `REGISTRY`, `UNREGISTERED`, `ROLE`, `NETWORK`,
`PATH`, `HASH`, `DELIMITER`, `RESERVED_FIELD`, `INPUT`, `BUDGET`, and
`INTERNAL`. The event never contains task IDs, Skill content, user task text,
paths, hashes, registry entries, or exception text. The trusted `run_id` is the
only correlation key. The public `AgentResult` remains the same generic
`SKILL_CONTEXT_BLOCKED` response.

The sink is best-effort: if it raises, the exception is discarded and the run
remains blocked. A diagnostic transport cannot reopen the request, call the
provider, or turn a blocked run into an infrastructure failure. This slice does
not install a global logger, persist events, or select a telemetry backend.

## Example

```python
from adapters import RepositorySkillSelection, run_adapter

result = run_adapter(
    adapter,
    request,
    skill_selection=RepositorySkillSelection(
        skill_ids=("ar-architecture-map",),
        executor_role="aios-worker",
    ),
    skill_diagnostic_sink=trusted_diagnostic_sink,
)
```

The adapter's own `network_policy` still governs provider access. It never
raises the Skill/tool network ceiling: this slice accepts only Registry Skills
declared `OFFLINE`, including when the adapter itself has provider-only access.
The executor role is a control-plane assertion that must come from the
Router/Scheduler or equivalent trusted harness configuration; it must never be
copied from model output or untrusted task text.

## Compatibility And Non-goals

This slice does not create `ai-context.v1`, alter `ai-task.v1`, select Skills
automatically, or wire Router/Scheduler. It is intentionally downstream of a
future A-010 context producer: that producer may choose ordered Skill IDs, while
this runtime remains the final deterministic verification and binding point
immediately before adapter execution.

Direct calls to provider wrapper internals are outside the Agent Harness
contract. AIOS callers must use `run_adapter()` so request validation, Skill
preflight, failure envelopes, usage, and provenance remain uniform.
