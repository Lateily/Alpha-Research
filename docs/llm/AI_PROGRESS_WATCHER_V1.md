# AI Progress Watcher v1

This is the local live display layer for the AI Progress Board.

It does not replace GitHub Issue #164. The issue remains the source of truth.

## What It Does

`scripts/llm/progress_watch.py` starts a local read-only page:

```text
http://127.0.0.1:8765
```

The page refreshes itself and shows:

- active `CLAIM` events
- recent timeline events
- `DONE`, `BLOCKED`, and `RELEASE` counts
- active file-scope conflicts

The watcher does not post comments, does not read private model chats, does not
call model APIs, and does not store tokens.

## v1.5 UI Contract

The `/events` endpoint now returns a versioned snapshot:

```json
{
  "schema": "ai-progress.snapshot.v1",
  "contract_version": "1.5"
}
```

The display-layer contract is documented in:

```text
docs/llm/AI_PROGRESS_UI_CONTRACT_V1_5.md
```

The machine-readable snapshot schema is:

```text
scripts/llm/progress_snapshot.schema.json
```

For frontend integration details, local CORS, fixture data, and `/team` handoff
checks, use the v1.5 UI contract.

## First Run With Local Example Data

Open PowerShell in the repository:

```powershell
cd C:\Users\19463\Documents\Codex\2026-07-28\ar-github-com-lateily-alpha-research\Alpha-Research
```

Run:

```powershell
python scripts/llm/progress_watch.py
```

Open:

```text
http://127.0.0.1:8765
```

Stop it with `Ctrl+C`.

## One-Time Check

To print one JSON snapshot without starting the page:

```powershell
python scripts/llm/progress_watch.py --once
```

To export the same snapshot to a file:

```powershell
python scripts/llm/progress_snapshot.py `
  --output docs/llm/AI_PROGRESS_SNAPSHOT.example.json
```

To run a fixture with all five event types and one conflict:

```powershell
python scripts/llm/progress_watch.py --source scripts/llm/progress_board.fixture.json
```

## Reading GitHub Issue #164

For the real board, run:

```powershell
python scripts/llm/progress_watch.py --repo Lateily/Alpha-Research --issue 164
```

For a private repository, log in with GitHub CLI first:

```powershell
gh auth login -h github.com
```

The watcher will use `gh api` when no token environment variable is present.
That is the preferred local workflow because it avoids pasting tokens.

If GitHub CLI is unavailable, set a token only in an environment variable.
Never paste it into code, docs, commits, or chat.

PowerShell example:

```powershell
$env:GITHUB_TOKEN = Read-Host "GitHub token"
python scripts/llm/progress_watch.py --repo Lateily/Alpha-Research --issue 164
```

Close that PowerShell window when done if you do not want to keep the temporary
token in the process environment.

## Local Frontend Reads

The watcher supports read-only browser access to `/events` from explicit local
development origins:

- `http://localhost:5173`
- `http://127.0.0.1:5173`
- `http://localhost:8765`
- `http://127.0.0.1:8765`

Only `GET` and `OPTIONS` are supported. The watcher has no write endpoint.

For another local Vite or dev-server port, pass an explicit origin:

```powershell
python scripts/llm/progress_watch.py `
  --repo Lateily/Alpha-Research `
  --issue 164 `
  --cors-origin http://localhost:3000
```

Do not use wildcard CORS. Public team sharing needs a Junyan-approved
server-side HTTPS proxy; it must not put GitHub tokens in browser code.

## Boundary

This is a Tianrui-side local coordination tool. It belongs to the AI/tooling
layer for now.

Future Agent Console or `/team` work may render the same protocol in the
product frontend, but this watcher is not the product UI.
