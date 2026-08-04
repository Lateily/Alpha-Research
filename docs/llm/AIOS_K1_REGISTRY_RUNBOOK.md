# AIOS K1 Registry Runbook

> Owner: Reed. Status: Draft seed, stacked on PR #219.

Not a trading instruction; research signal only, human executes.

## Purpose

The registry turns append-only `ai-progress.v2` comments into one current state per task. It is read-only and deterministic.

Example:

- `CLAIM` starts an active task.
- `UPDATE` keeps the task active and refreshes the latest summary.
- `DONE` makes the task inactive with status `done`.
- `BLOCKED` makes the task inactive with status `blocked`.
- `RELEASE` makes the task inactive with status `released`.

## Local Fixture Check

```powershell
C:\Users\19463\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe scripts\llm\ai_registry.py docs\llm\examples\ai-progress.registry.fixture.json --json
```

Expected behavior:

- returns `schema=ai-task-registry.v1`
- returns 3 tasks
- returns 1 done, 1 blocked, 1 released

## GitHub Comments Response Shape

The registry also accepts the same wrapper shape returned by `gh issue view --comments --json comments`:

```json
{
  "comments": [
    {
      "body": "<!-- ai-progress:v2 -->..."
    }
  ]
}
```

Fixture check:

```powershell
C:\Users\19463\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe scripts\llm\ai_registry.py docs\llm\examples\ai-progress.registry.comments-response.fixture.json --json
```

## Real #164 Dry Run

Use a temporary file, not a committed artifact:

```powershell
$json = gh issue view 164 --repo Lateily/Alpha-Research --comments --json comments
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText("$env:TEMP\ai-progress-164-comments.json", $json, $utf8NoBom)
C:\Users\19463\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe scripts\llm\ai_registry.py "$env:TEMP\ai-progress-164-comments.json" --json
```

Do not commit the real #164 snapshot. The registry output is a derived view; GitHub Issue #164 remains the source of truth.

## Current Limits

- This seed only replays `ai-progress.v2`.
- It does not yet compile arbitrary Issues or PRs into `ai-task.v1`.
- It does not write GitHub comments.
- It does not perform reconciliation findings such as orphan PRs or premature DONE.
- It does not call model APIs.

## Reconciler v0

The reconciler is the first read-only "task accountant" on top of the registry.
It turns the current task states into actionable findings.

Local fixture check:

```powershell
C:\Users\19463\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe scripts\llm\ai_reconciler.py docs\llm\examples\ai-progress.reconciler.fixture.json --now 2026-08-04T06:00:00Z --json
```

v0 checks:

- active tasks past `expires_at`
- active tasks missing `branch` or `files`
- `DONE` tasks missing `pr` or `cost_cny`
- `BLOCKED` tasks missing `blocked_by` or `next`
- unexpired active tasks that claim overlapping file scopes

Optional strict history mode:

- progress events that appear before any `CLAIM`

Run strict history mode only when auditing a clean v2-only board. It is disabled
by default because #164 contains legacy pre-v2 records that would otherwise
create noisy false positives.

Boundary:

- It is read-only and offline.
- It does not write #164 comments.
- It does not call model APIs.
- It reports coordination problems; humans still decide whether to update, release,
  or keep working.

