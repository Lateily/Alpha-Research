# Paid-model route gate (AR_LLM_ROUTE_KEY)

Status: introduced by `fix/v1-llm-route-auth` (2026-09-29). Source of the problem:
2026-09-25 re-review, P1 #7. Seven Vercel routes accepted anonymous POSTs from any
origin (`Access-Control-Allow-Origin: *`) and spent the owner's Anthropic, OpenAI
and Gemini keys. The repo is public and the production host is committed.

## Routes behind the gate

`api/research-multi.js`, `api/research.js`, `api/chat.js` (and its `/api/translate`
rewrite), `api/debate.js`, `api/macro.js`, `api/morning-report.js`,
`api/research-pulse.js`. Each handler calls `guardLlmRoute()` from
`api/_lib/llm-route-guard.js` as its first statement.

The free data proxies (`news`, `live-quotes`, `a-quote`, `capital-flow`,
`price-chart`) are not paid-model routes and are unchanged.

## What the gate checks, in order

| Check | Response | Notes |
|---|---|---|
| `OPTIONS` preflight | 204 for an allowed Origin, else 403 | |
| Origin header present and not allow-listed | 403 `LLM_ORIGIN_FORBIDDEN` | No Origin = server-to-server; the key decides |
| Method is not `POST` | 405 | |
| `AR_LLM_ROUTE_KEY` missing or shorter than 32 chars | 503 `LLM_ROUTE_KEY_NOT_CONFIGURED` | Fails closed |
| `X-AR-LLM-Key` header is not an exact match | 401 `LLM_ROUTE_UNAUTHORIZED` | SHA-256 digests compared with `timingSafeEqual` |
| Per-IP burst over the route limit (10 minute window) | 429 + `Retry-After` | research-multi 3, research 10, debate 10, morning-report 5, research-pulse 30, macro 20, chat 60 |

All rejections happen before any provider SDK or `fetch` call.

The Origin allowlist is `https://equity-research-ten.vercel.app` and
`https://lateily.github.io`, plus a comma list in `AR_LLM_ALLOWED_ORIGINS`
(`*` and `null` are ignored). It only stops drive-by browser use: a non-browser
client can forge Origin, so the key is the real control.

The rate limit is in-memory per warm serverless instance, the same caveat as
`api/team-progress-event.js`. A durable cap needs Vercel Firewall rules or a
shared store, and provider-side spend limits.

## Setting it up (human steps, not done by this PR)

1. Generate a key of at least 32 characters, e.g. `openssl rand -hex 32`.
2. Vercel project env: `AR_LLM_ROUTE_KEY=<key>` (Production, plus Preview if
   previews should work). Optionally `AR_LLM_ALLOWED_ORIGINS`. Redeploy.
3. GitHub Actions secret `AR_LLM_ROUTE_KEY` with the same value. It is used by
   `.github/workflows/morning-report.yml`.
4. Local CLI: `export AR_LLM_ROUTE_KEY=...` before `scripts/run_research.py`.

Until step 2 is done, every paid-model route returns 503. That is intended.

## Callers

| Caller | How it sends the key |
|---|---|
| `.github/workflows/morning-report.yml` | Secret mapped into the step's `env`; Python reads `os.environ` and sends `X-AR-LLM-Key`. The secret is never template-interpolated into the script or printed. The step exits 1 if the secret is missing. |
| `scripts/run_research.py` | Reads `AR_LLM_ROUTE_KEY` from the environment. Without it, it raises `MissingLlmRouteKey` before any HTTP request (exit code 2). |
| `src/Dashboard.jsx` (11 call sites) | Through `src/llmRouteClient.js`. Off by default: the build must set `VITE_AR_LLM_BROWSER_ROUTES=1`, and the operator then types the key into the header control for that tab. The key stays in module memory only, is never a build variable, and is forgotten on a 401 or a reload. While locked, no request is made, so public page loads spend nothing. |

A shared secret typed into a browser tab is still a shared secret. For any use
beyond the owner's own browser, replace it with real per-user auth, such as
Vercel deployment protection or an identity provider, before turning the flag on.

## Tests and pins

- `node tests/llm-route-guard.test.mjs`: guard, all seven handlers, browser
  client and static no-key-in-bundle checks. Offline.
- `python3 tests/test_llm_route_guard.py`: node runners per property, the CLI
  caller and the workflow wiring.
- `scripts/governance_mutation_gate.py`: `LLM_ROUTE_*`, `LLM_BROWSER_LOCKED_WITHOUT_KEY`
  and `LLM_CALLER_RUN_RESEARCH_REQUIRES_KEY` (13 pins).

不是买卖指令；研究信号，human executes。
