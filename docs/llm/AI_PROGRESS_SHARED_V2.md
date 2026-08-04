# AI Progress Board Shared v2

This document defines the approved shared path for the team Progress Board.

GitHub Issue #164 remains the only source of truth. The shared page and API
render existing `ai-progress.v2` comments. v2.1 can optionally post one standard
progress comment back to #164 through a server-only endpoint.

## What v2 Adds

v2 adds a server-side read endpoint:

```text
GET /api/team-progress
```

The endpoint reads GitHub Issue #164 comments, extracts fenced
`ai-progress.v2` JSON events, and returns the same snapshot shape used by the
local watcher:

```json
{
  "schema": "ai-progress.snapshot.v1",
  "contract_version": "1.5"
}
```

The snapshot contract stays at `1.5` because the UI data shape is unchanged.
`v2` is the deployment mode: shared HTTPS read access.

## Safety Boundary

The board must stay inside the progress-log boundary.

- No model API.
- No private chat ingestion.
- No frontend GitHub token.
- No free-form bot output posting.
- No buy, sell, hold, or position sizing output.

The repository is public, so the preferred read path is no token plus CDN
caching. If GitHub authentication is needed for rate limits or write access,
the token must be fine-grained and must live only in server environment
variables:

```text
PROGRESS_GITHUB_TOKEN
```

`GITHUB_TOKEN` is accepted only as a fallback for existing deployment setups.

Do not put either value in code, docs, commits, screenshots, GitHub comments,
or chat.

The browser must never receive or store a GitHub token.

## v2.1 Team Write Path

v2.1 adds an optional server-side write endpoint:

```text
POST /api/team-progress-event
```

The endpoint posts one standard `ai-progress.v2` comment to GitHub Issue #164.
It is for team progress logs only. It must not accept free-form bot output,
private chat transcripts, model API calls, or research conclusions.

Required server environment variables:

```text
PROGRESS_GITHUB_TOKEN
PROGRESS_WRITE_KEY
```

`PROGRESS_GITHUB_TOKEN` is a fine-grained GitHub token with the minimum
repository permission needed to create issue comments. It must live only in the
hosting provider's server environment variables.

`PROGRESS_WRITE_KEY` is a separate team posting passphrase. Teammates can enter
this key in the Progress Board UI when posting a progress event. It is not a
GitHub token and can be rotated without changing GitHub permissions.

The frontend sends:

```text
X-Progress-Write-Key: <team posting passphrase>
```

The frontend never receives `PROGRESS_GITHUB_TOKEN`.

The write endpoint accepts only:

```text
CLAIM / UPDATE / DONE / BLOCKED / RELEASE
```

and validates the same team fields used by the read-only board:

```text
task, human_owner, executor, reviewer, summary, branch, files, pr, next,
cost_cny, risk
```

`CLAIM` requires `branch` and at least one repository-relative file or folder
scope. File scopes cannot be absolute paths and cannot contain `..`.

## Cache Floor

The read endpoint sets:

```text
Cache-Control: s-maxage=30, stale-while-revalidate=60
```

Do not lower `s-maxage` below 30 seconds. This protects GitHub rate limits and
keeps the v2 trial on the free or lowest-cost hosting path.

The write endpoint sets:

```text
Cache-Control: no-store
```

## Configuration

Defaults:

```text
PROGRESS_REPO=Lateily/Alpha-Research
PROGRESS_ISSUE=164
```

Optional cross-origin UI access:

```text
PROGRESS_ALLOWED_ORIGINS=https://example-team-ui.vercel.app
```

Use a comma-separated list for multiple approved UI origins. Local Vite origins
`http://localhost:5173` and `http://127.0.0.1:5173` are allowed for development.

## Xuhang UI Handoff

Xuhang's page should read:

```text
GET /api/team-progress
```

and render:

- `summary`
- `active_claims`
- `conflicts`
- `timeline`

Refresh no faster than every 30 seconds.

If `ok=false`, show the `error` field and keep the page usable for viewing the
last successful state if one exists.

The `/team` route in the Vite frontend reads `GET /api/team-progress` from the
same origin. It can submit standard progress events through
`POST /api/team-progress-event`, but it does not read GitHub directly, hold a
GitHub token, or call model APIs.

Contract fixtures:

- success snapshot: `docs/llm/AI_PROGRESS_SNAPSHOT.example.json`
- full event/conflict snapshot: `docs/llm/AI_PROGRESS_SNAPSHOT.fixture.json`
- error snapshot: `docs/llm/AI_PROGRESS_SNAPSHOT.error.example.json`

## Junyan Trial Conditions

Junyan approved v2 as a two-week trial. The trial clock starts when the v2 UI is
actually online for the team, not when this data-layer PR is opened.

Junyan's dated review checkpoint is 2026-08-14: keep or destroy. Cost must stay
on the free or lowest-cost hosting path and be reported in the weekly note.

v2.1 write access is optional and can be disabled by omitting
`PROGRESS_WRITE_KEY` or `PROGRESS_GITHUB_TOKEN`.

## Local Validation

Syntax-check the endpoints:

```powershell
node --check api/team-progress.js
node --check api/team-progress-event.js
```

Run the zero-network handler tests:

```powershell
node tests/team-progress-api.test.mjs
node tests/team-progress-event-api.test.mjs
```

Build the app:

```powershell
npm.cmd run build
```
