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
