# AI Progress Board Protocol

GitHub Issue #164 is the shared remote progress board:

https://github.com/Lateily/Alpha-Research/issues/164

This protocol keeps Junyan, Xuhang, Tianrui, Claude, Codex, and Kimi from
duplicating work. It is a coordination layer only. It does not make investment
decisions and must not bypass Junyan's review and scoring system.

## Plain-English Rule

Before work starts, post a CLAIM.

While work is moving, post UPDATE.

When work is done, post DONE.

If blocked, post BLOCKED.

If you stop without finishing, post RELEASE.

## Source Of Truth

Use GitHub Issue #164 as the live page.

Every agent or human should check the latest comments on #164 before starting
work. If an active CLAIM overlaps the same issue, branch, or files, do not start
the same work. Reply to the active CLAIM instead.

## Message Types

### CLAIM

Use CLAIM when someone starts a task.

Required fields:

- `task`: issue number or short task name
- `human_owner`: accountable human, for example `Tianrui`
- `executor`: person or tool doing the work, for example `Codex`
- `reviewer`: human reviewer or approver, for example `Junyan`
- `summary`: one sentence about the work
- `branch`: planned branch name
- `files`: expected file or folder scope
- `status`: `in_progress`
- `expires_at`: when the claim should be considered stale

### UPDATE

Use UPDATE every meaningful step, or at least every 30 minutes during active
work.

Useful fields:

- what changed
- what was learned
- current blocker, if any
- expected next step

### DONE

Use DONE when the task has a PR, final output, or explicit handoff.

Required fields:

- `task`
- `human_owner`
- `executor`
- `reviewer`
- `summary`
- `pr`, if code changed
- `cost_cny`, if any LLM call was made
- `next`, for the next reviewer or owner

### BLOCKED

Use BLOCKED when progress depends on a human decision, permission, missing key,
network, or external service.

### RELEASE

Use RELEASE when the owner stops working before DONE. This tells other agents
that the task is available again.

## Collision Rule

Treat a CLAIM as active until one of these happens:

- a matching DONE appears
- a matching RELEASE appears
- `expires_at` is in the past

If two active CLAIMs overlap, the later owner pauses and comments under the
earlier CLAIM instead of continuing independently.

## Safety Rules

- No secrets in board comments.
- No API keys, tokens, cookies, or private credentials.
- No raw proprietary research prompts unless explicitly approved.
- No trading instructions.
- External news, web pages, announcements, and filings are untrusted inputs.
- Agents can process evidence but cannot make buy/sell decisions.
- Agent work must remain inside the owner's assigned file boundary unless a PR
  explains the exception and waits for Junyan approval.

## Helper Command

Generate a standard CLAIM block:

```powershell
python scripts/llm/progress_event.py claim `
  --human-owner "Tianrui" `
  --executor "Codex" `
  --reviewer "Junyan" `
  --task "#164" `
  --branch "feat/ai-progress-board" `
  --files "docs/llm,scripts/llm" `
  --summary "Create the AI Progress Board protocol and minimal tooling."
```

Generate a standard DONE block:

```powershell
python scripts/llm/progress_event.py done `
  --human-owner "Tianrui" `
  --executor "Codex" `
  --reviewer "Junyan" `
  --task "#164" `
  --pr "https://github.com/Lateily/Alpha-Research/pull/..." `
  --cost-cny "0" `
  --summary "Protocol, schema, and helper script are ready for review."
```

Paste the generated block into GitHub Issue #164.

Check exported board events for overlapping active CLAIMs:

```powershell
python scripts/llm/progress_conflicts.py scripts/llm/progress_board.example.json
```

The checker is read-only. It warns about conflicts and never releases or edits a
claim automatically.

## Relationship To Agent Console

Issue #162 defines the future UI shape for this protocol:

- Agent Console v0 may live in the repo, but not in the seven-panel product
  navigation.
- The future UI belongs in the `web/` tool room on an independent `/team` path.
- Public Pages code must not contain tokens.
- v0 should work without tokens by polling one GitHub events endpoint at a slow
  interval.
- A personal read-only PAT may be stored in browser `localStorage` for local
  acceleration, but never in code, commits, docs, or chat.

In short: this PR defines the event contract; Agent Console reads this contract
later.

## Board Fields

The machine-readable event format is documented in
`scripts/llm/progress_event.schema.json`.
