# AI Progress Board Playbook v0

This is the beginner operating guide for the team progress board.

The board is GitHub Issue #164:

https://github.com/Lateily/Alpha-Research/issues/164

## What v0 Means

v0 is not a web app.

v0 is the smallest usable team workflow:

1. Check whether another human or agent is already working on the same task.
2. Generate a standard progress comment.
3. Let a human review it.
4. Paste it into GitHub Issue #164.

The board records work events only. It must not contain API keys, private chat
logs, hidden model reasoning, raw proprietary research prompts, or trading
instructions.

## The Five Comments

Use `CLAIM` before work starts.

Use `UPDATE` while work is moving.

Use `DONE` when work is finished or handed off.

Use `BLOCKED` when work cannot continue without a decision, permission, network,
or another dependency.

Use `RELEASE` when someone stops working before finishing, so the task is free
for another owner.

## Daily Flow

### 1. Open PowerShell In The Repo

Go to the repository folder:

```powershell
cd C:\Users\19463\Documents\Codex\2026-07-28\ar-github-com-lateily-alpha-research\Alpha-Research
```

Confirm the branch:

```powershell
git branch --show-current
```

Never work directly on `main`.

### 2. Check For Collisions

Run the conflict checker before posting a new `CLAIM`:

```powershell
python scripts/llm/progress_conflicts.py scripts/llm/progress_board.example.json
```

Expected safe result:

```text
OK: no active overlapping CLAIMs found.
```

If it reports an overlap, pause. Reply under the earlier claim on Issue #164
instead of starting the same work independently.

### 3. Generate A CLAIM

Example:

```powershell
python scripts/llm/progress_event.py claim `
  --human-owner "Reed" `
  --executor "Codex" `
  --reviewer "Junyan" `
  --task "#164" `
  --branch "feat/ai-progress-board" `
  --files "docs/llm,scripts/llm" `
  --summary "Document the v0 AI Progress Board workflow."
```

Copy the generated block into GitHub Issue #164 after checking it contains no
secrets or private material.

### 4. Generate An UPDATE

Use this after a meaningful step, or every 30 minutes during active work:

```powershell
python scripts/llm/progress_event.py update `
  --human-owner "Reed" `
  --executor "Codex" `
  --reviewer "Junyan" `
  --task "#164" `
  --summary "The v0 workflow guide is drafted and local validation is next." `
  --risk "none"
```

### 5. Generate A DONE

Use this when there is a PR, finished artifact, or handoff:

```powershell
python scripts/llm/progress_event.py done `
  --human-owner "Reed" `
  --executor "Codex" `
  --reviewer "Junyan" `
  --task "#164" `
  --pr "https://github.com/Lateily/Alpha-Research/pull/165" `
  --cost-cny "0" `
  --summary "The v0 progress board workflow is documented." `
  --next "Junyan reviews PR #165."
```

## Human Review Checklist

Before pasting any generated event into Issue #164, check:

- No API key, token, cookie, or password.
- No private chat transcript.
- No hidden model reasoning.
- No raw proprietary research prompt unless approved.
- No buy, sell, hold, position size, or trading action.
- `human_owner`, `executor`, and `reviewer` are correct.
- `branch` and `files` describe the real work scope.
- `cost_cny` is present when an LLM API was called.

## Where The Team Reads Progress

The team reads the latest status in GitHub Issue #164.

The scripts do not replace the issue. They only help create and check comments
for the issue.

Future Agent Console work may render these comments as a page, but v0 is the
GitHub issue plus the two local scripts.

For a local auto-refreshing view of the same events, see
`docs/llm/AI_PROGRESS_WATCHER_V1.md`.
