# AI Progress Board Shared Read-Only v2

This document defines the approved shared read path for the team Progress Board.

GitHub Issue #164 remains the only source of truth. The shared page and API only
render existing `ai-progress.v2` comments.

## What v2 Adds

v2 adds a server-side read-only endpoint:

```text
/api/team-progress
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
`v2` is the deployment mode: shared HTTPS read-only access.

## Safety Boundary

The endpoint must remain read-only.

- No GitHub write API.
- No model API.
- No private chat ingestion.
- No frontend token.
- No buy, sell, hold, or position sizing output.

If GitHub authentication is needed for rate limits, the token must live only in
server environment variables:

```text
GITHUB_TOKEN
```

or:

```text
PROGRESS_GITHUB_TOKEN
```

Do not put either value in code, docs, commits, screenshots, or chat.

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

If `ok=false`, show the `error` field and keep the page read-only.

## Junyan Trial Conditions

Junyan approved v2 as a trial through 2026-08-14.

Keep or destroy will be reviewed after the trial. Cost must stay on the free or
lowest-cost hosting path and be reported in the weekly note.

## Local Validation

Syntax-check the endpoint:

```powershell
node --check api/team-progress.js
```

Run the zero-network handler test:

```powershell
node tests/team-progress-api.test.mjs
```

Build the app:

```powershell
npm.cmd run build
```
