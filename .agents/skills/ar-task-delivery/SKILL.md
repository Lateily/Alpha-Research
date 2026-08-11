---
name: ar-task-delivery
description: Execute an AR repository implementation or bug-fix task from a complete ai-task.v1 contract through code, tests, and a reviewable PR. Use for concrete build work; do not use for brainstorming-only requests.
---

# AR Task Delivery

1. Run `python3 scripts/team_ai_workspace.py doctor` from the repo root.
2. Read root and nearest module `AGENTS.md` files.
3. Compile the task source with `scripts/llm/ai_os/cli.py compile`.
   Stop on `SPEC_BLOCKED`; do not invent missing scope or approval.
4. Inspect current code, contracts, tests, and branch state before editing.
5. Implement only the declared file scope. Preserve unrelated dirty work.
6. Add the failure case as a regression test. For a governance guard, prove
   weakening the guard makes the designated test fail.
7. Run declared acceptance commands plus `git diff --check`.
8. Report changed files, commands and meaningful results, residual risk, and
   whether work is merely delivered, merged, deployed, or production-verified.
9. Prepare a PR for Junyan. Never infer merge approval.

Completion requires artifacts and evidence, not a conversational claim.
