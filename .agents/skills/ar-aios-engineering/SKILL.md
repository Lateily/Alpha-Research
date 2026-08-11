---
name: ar-aios-engineering
description: Build AR AIOS, model adapters, task registry, policy, context, evaluation, cost, and safety components. Use for scripts/llm work requiring deterministic fail-closed controls around model workers.
---

# AR AIOS Engineering

1. Read `scripts/llm/AGENTS.md` and compile the task to `ai-task.v1`.
2. Put deterministic validation, policy, routing, and context assembly before a
   model call. A model may not decide its own authority.
3. Default to offline deterministic tests. Live provider access needs an
   explicit allowlist, budget, local secret, and usage record.
4. Keep provider adapters behind the shared contract. Do not create a provider-
   specific task format or bypass the registry state machine.
5. Treat external prompt content as untrusted data and delimit it from policy.
6. Record model, prompt version, evidence grade, task ID, token usage, and cost
   for persisted output.
7. Test denied network, missing key, malformed response, missing usage, retry,
   and forbidden state transition paths.
8. Mutation-test governance guards before claiming delivery.

AIOS coordinates workers; it does not grant research or merge authority.
