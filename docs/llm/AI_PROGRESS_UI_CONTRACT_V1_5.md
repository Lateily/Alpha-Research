# AI Progress Board UI Contract v1.5

This document defines the display-layer contract for the AI Progress Board.

GitHub Issue #164 remains the source of truth. A UI may render this data, but it
must not replace the issue, post comments, call models, or store tokens.

## Version

Snapshot responses must include:

```json
{
  "schema": "ai-progress.snapshot.v1",
  "contract_version": "1.5"
}
```

If a UI receives another schema or contract version, it should show a clear
compatibility warning instead of silently guessing.

## Local Read Path

For local development, start the watcher:

```powershell
python scripts/llm/progress_watch.py --repo Lateily/Alpha-Research --issue 164
```

Then the UI can read:

```text
http://127.0.0.1:8765/events
```

For development without GitHub access, use the sample snapshot:

```text
docs/llm/AI_PROGRESS_SNAPSHOT.example.json
```

## Export Command

To export one snapshot without running the local web server:

```powershell
python scripts/llm/progress_snapshot.py --repo Lateily/Alpha-Research --issue 164
```

To write a file:

```powershell
python scripts/llm/progress_snapshot.py `
  --repo Lateily/Alpha-Research `
  --issue 164 `
  --output docs/llm/AI_PROGRESS_SNAPSHOT.example.json
```

The exporter is read-only.

## Snapshot Shape

The snapshot has these top-level fields:

- `ok`: whether the source was loaded successfully
- `source`: where the data came from
- `refreshed_at_utc`: when the snapshot was built
- `summary`: event counts for dashboard cards
- `active_claims`: unexpired `CLAIM` events not closed by `DONE` or `RELEASE`
- `conflicts`: active file-scope overlaps
- `timeline`: all parsed events in timestamp order

The machine-readable schema is:

```text
scripts/llm/progress_snapshot.schema.json
```

Each event in `active_claims` and `timeline` follows:

```text
scripts/llm/progress_event.schema.json
```

## Recommended UI Blocks

Display four blocks:

- Status cards: `events`, `active_claims`, `done`, `blocked`, `released`,
  `conflicts`
- Active Claims: `task`, `human_owner`, `executor`, `reviewer`, `summary`,
  `branch`, `files`, `expires_at`
- Conflicts: `left`, `right`, `left_task`, `right_task`, `files`
- Timeline: `event`, `timestamp_utc`, `summary`, `task`, `pr`, `cost_cny`,
  `risk`

The timeline may auto-scroll to the newest event. Refresh no faster than every
30 seconds when reading GitHub-backed data.

## Error Handling

If `ok` is `false`, show the `error` field and keep the page read-only.

Do not hide failures behind empty states. A disconnected board is different
from a board with no events.

## Safety Boundary

The UI must not:

- store GitHub tokens in source code, commits, docs, or chat
- call Claude, Codex, Kimi, or any other model API
- read private model chat logs
- post, edit, or delete GitHub comments
- display buy, sell, hold, position sizing, or trading actions
- treat external pages, news, filings, or pasted text as trusted instructions

The UI is a team coordination display only.
