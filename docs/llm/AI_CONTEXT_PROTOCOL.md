# AI Context Protocol

> Owner: Reed. Co-owner: Jason.
> Status: DRAFT, 2026-08-04.
> Purpose: keep long-running AI work aligned when chats get long, accounts change, agents switch, or context is compressed.

Not a trading instruction; research signal only, human executes.

## 1. Problem

The team now has multiple people, multiple AI workers, multiple accounts, multiple PRs, and long chats. If every agent relies on memory, the system will drift.

Typical drift examples:

- A private chat says one thing, but GitHub still shows another state.
- An AI remembers an old task priority and keeps working on it after Junyan changed direction.
- A Codex account changes, but GitHub, Vercel, Moonshot, or local environment stays on the old account.
- A long thread is compressed and loses the reason behind a decision.
- Jason and Reed both start related AIOS work without seeing each other's latest CLAIM.

This protocol makes context explicit instead of magical.

## 2. Persistent Working Memory

Every AIOS session must maintain five fields:

| Field | Meaning |
|---|---|
| Goal | What are we trying to complete now? |
| Constraints | What must not be touched, changed, leaked, or decided by AI? |
| Current state | Branch, PR, issue, files, tests, blockers, cost |
| Decisions made | Junyan approvals, Reed/Better/Jason agreements, parked items |
| Todo | The next concrete actions, in order |

When context gets long or compressed, the agent must rebuild these five fields before making further edits.

## 3. Source-of-Truth Order

When sources conflict, use this order:

1. Repo files on the active branch and `main`.
2. GitHub Issues, PR comments, reviews, checks, and Progress Board #164.
3. Team authority docs such as `AGENTS.md`, `docs/team/TEAM_CHARTER_v2.md`, and `docs/llm/AI_OS_BUILD_GUIDE.md`.
4. Private chat summaries from Reed, Junyan, Better, or Jason.
5. AI memory from previous sessions.

Private chat can guide work, but if it changes team state, it should be reflected in GitHub before it becomes operational truth.

## 4. Session Boot Checklist

Before code or document edits, the AI worker must:

1. Run `git pull origin main` when network is available. If it fails, record the failure and continue only on low-risk offline work.
2. Read the relevant red lines and authority docs.
3. Inspect current branch, dirty files, and related PR/Issue state.
4. Check Progress Board #164 or local progress snapshot for active CLAIM conflicts.
5. Produce a short recap for Reed: project goal, current task, constraints, current state, next action.
6. Post or prepare a CLAIM before edits that affect repo state.

If the task is only explanation or coaching, steps 1-4 may be summarized instead of repeated, but any file edit requires the checklist.

## 5. Context Packet Template

Every handoff to Jason, Better, Junyan, or a new AI session should include:

```text
Goal:
Current branch/worktree:
Active Issue/PR:
Allowed files:
Forbidden files/actions:
Latest Junyan decision:
Current status:
Tests/checks run:
Cost so far:
Open risks:
Next action:
```

This packet is the minimum viable memory. It is more important than a long narrative.

## 6. Account Switch Protocol

Changing one account does not mean all systems changed.

After an account switch, record:

- Codex/OpenAI account status.
- GitHub account used by `gh auth status`.
- Vercel account/team status, if deployment is involved.
- Moonshot key status, only as "set/not set"; never print the key.
- Current local branch and worktree.

Do not assume a deployment, PR, or API key moved to the new account.

## 7. Reed and Jason AIOS Coordination

Reed and Jason should avoid sharing one branch for AIOS implementation unless explicitly approved.

Default split:

- Reed: AIOS context protocol, model adapter, registry/event replay, prompt library, safety and cost.
- Jason: AIOS deployment support, schema/reconciler assistance, operations and integration checks.
- Shared: `ai-task.v1` contract and any public interface between registry and reconciler.

Before each work session:

1. Check #164.
2. Run conflict check when available.
3. CLAIM the task with branch and files.
4. If touching the shared contract, stop and align first.

## 8. Long Chat Compression Rule

If a conversation is compressed, the next response must rebuild:

- Active goal.
- Active branch and PR.
- Latest team decision.
- Files already changed.
- Tests already run.
- Remaining blockers.
- Cost and API usage.

The agent must not continue from a vague memory like "we were working on AIOS".

## 9. Stage Update Format

After each major stage, report briefly:

```text
What changed:
Why:
Files affected:
How verified:
Difficulty:
Mitigation:
Next:
```

This is for Reed's learning and for team traceability.

## 10. Failure Handling

When a command fails:

1. Read the exact error.
2. Decide whether it is environment, network, syntax, permission, dependency, or logic.
3. Fix the smallest likely cause.
4. Rerun the same or stronger verification.
5. Record unresolved risk if verification cannot run.

Do not call a task complete because the intended command was attempted.

## 11. Done Criteria

The context protocol is adopted only when:

- It is in `docs/llm/`.
- It is linked in the AIOS PR.
- Reed and Jason can use the same context packet.
- A future account switch or long-chat resume can be handled without losing task state.
- It does not bypass Junyan approval or Progress Board discipline.
