# Paid-model route gate (AR_LLM_ROUTE_KEY / AR_LLM_BROWSER_ROUTE_KEY)

Status: introduced by `fix/v1-llm-route-auth` (2026-09-29). Source of the problem:
2026-09-25 re-review, P1 #7. Seven Vercel routes accepted anonymous POSTs from any
origin (`Access-Control-Allow-Origin: *`) and spent the owner's Anthropic, OpenAI
and Gemini keys. The repo is public and the production host is committed.

## Routes behind the gate

`api/research-multi.js`, `api/research.js`, `api/chat.js` (and its `/api/translate`
rewrite), `api/debate.js`, `api/macro.js`, `api/morning-report.js`,
`api/research-pulse.js`. Each handler calls `guardLlmRoute()` from
`api/_lib/llm-route-guard.js` as its first statement.

## Production is not running this code yet

Vercel builds of `main` have failed since about 2026-09-20 with
`invalid maxDuration for plan` (Vercel commit status on `77049a169`, `1e2779988`,
`eae0b8050`; last success `f58c82f54`, 2026-09-07). The live Production
deployment is still the 2026-09-09 build `e64e3cdd6`, which has the old
anonymous, wildcard-CORS handlers. `vercel.json` has not changed since
2026-07-11 (`api/research-multi.js` maxDuration 800; research, debate and
morning-report 300), so the plan limit most likely changed, not the file.

Merging this gate deploys nothing until that is fixed. Editing the Vercel
project env does not help either: env changes apply only to new deployments, and
every new deployment currently fails (a redeploy of `e64e3cdd6` most likely fails
too, because it carries the same `vercel.json`). The stop-gaps that work without a
deploy are:

1. Revoke or rotate `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `GOOGLE_AI_API_KEY`
   at each provider's own console (Anthropic, OpenAI, Google AI). This kills the
   keys baked into the running 9/09 build. Then put the new values in the Vercel
   env so later deployments use them.
2. A Vercel Firewall custom rule that blocks or challenges `/api/*`; firewall
   rules apply without a deploy.

Deployment protection may cover only preview URLs, not the production alias, on
the current plan, so do not rely on it. Check each provider's usage log for
unexplained traffic.

The free data proxies (`news`, `live-quotes`, `a-quote`, `capital-flow`,
`price-chart`) are not paid-model routes and are unchanged.

## What the gate checks, in order

| Check | Response | Notes |
|---|---|---|
| `OPTIONS` preflight | 204 for an allowed Origin, else 403 | |
| Origin header present and not allow-listed | 403 `LLM_ORIGIN_FORBIDDEN` | No Origin = server-to-server; the key decides |
| Method is not `POST` | 405 | |
| The caller class's key is missing, shorter than 32 chars, or has leading/trailing whitespace | 503 `LLM_ROUTE_KEY_NOT_CONFIGURED` | Fails closed. No Origin header: `AR_LLM_ROUTE_KEY`. Allowed Origin (browser): `AR_LLM_BROWSER_ROUTE_KEY`. A value pasted with a trailing newline would otherwise 401 forever |
| Browser request and `AR_LLM_BROWSER_ROUTE_KEY` equals `AR_LLM_ROUTE_KEY` | 503 `LLM_BROWSER_KEY_NOT_SEPARATE` | Keeps the two keys independently rotatable |
| `X-AR-LLM-Key` header is not an exact match for that key | 401 `LLM_ROUTE_UNAUTHORIZED` | SHA-256 digests compared with `timingSafeEqual`. The server key never unlocks a browser request and the browser key never unlocks a server-to-server one |
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

Rollout order matters. The morning-report step exits 1 when its secret is
missing, so the GitHub secret must exist before this PR merges, or the 07:00
email breaks even while production still runs the old ungated build.

1. Generate the server key, e.g. `openssl rand -hex 32` (at least 32 chars).
   Paste it without a trailing newline: `printf %s "$KEY" | vercel env add ...`,
   not `echo`.
2. GitHub Actions secret `AR_LLM_ROUTE_KEY` = the server key. Used only by
   `.github/workflows/morning-report.yml`. Do this before merging.
3. Vercel project env `AR_LLM_ROUTE_KEY` = the same server key (Production, plus
   Preview if previews should work). Optionally `AR_LLM_ALLOWED_ORIGINS`.
4. Only if the owner wants browser LLM calls: a second, different key in Vercel
   env `AR_LLM_BROWSER_ROUTE_KEY`, and a build with `VITE_AR_LLM_BROWSER_ROUTES=1`.
   Leave it unset otherwise; browser requests then get 503.
5. Local CLI: `export AR_LLM_ROUTE_KEY=...` before `scripts/run_research.py`.
6. Fix the Vercel deploy blocker (plan limit vs `maxDuration`, see above) as its
   own reviewed change. Steps 2 and 3 must be done before the first successful
   deploy that contains this gate.

Until step 3 is done and deployed, every paid-model route returns 503. That is
intended.

## Callers

| Caller | How it sends the key |
|---|---|
| `.github/workflows/morning-report.yml` | Secret mapped into the step's `env`; Python reads `os.environ` and sends `X-AR-LLM-Key`. The secret is never template-interpolated into the script or printed. The step exits 1 if the secret is missing. |
| `scripts/run_research.py` | Reads `AR_LLM_ROUTE_KEY` from the environment. Without it, it raises `MissingLlmRouteKey` before any HTTP request (exit code 2). |
| `src/Dashboard.jsx` (11 call sites) | Through `src/llmRouteClient.js`. Off by default: the build must set `VITE_AR_LLM_BROWSER_ROUTES=1`, and the operator then types the browser key (`AR_LLM_BROWSER_ROUTE_KEY`'s value, not the server key) into the header control for that tab. The key stays in module memory only, is never a build variable, and is forgotten on a 401 or a reload; the header control re-locks when that happens. While locked, no request is made, so public page loads spend nothing. If the page-load macro insight failed only because the tab was locked, unlocking retries it once. |

A shared secret typed into a browser tab is still a shared secret. Separate keys
limit the damage of a browser-side leak (XSS, a malicious dependency in the public
build) to the browser key, which can be rotated without touching the automation.
For any use beyond the owner's own browser, replace it with real per-user auth,
such as Vercel deployment protection or an identity provider, before turning the
flag on.

## Tests and pins

Node 20.6 or later (or 18.19+) is required: the tests stub the Anthropic SDK with
`node:module` `register()` and data: URL hooks. CI pins Node 20 with
`actions/setup-node` in the offline-tests and governance-mutation-gate jobs.

- `node tests/llm-route-guard.test.mjs`: guard, all seven handlers, browser
  client and static no-key-in-bundle checks. Offline.
- `python3 tests/test_llm_route_guard.py`: node runners per property, the exact
  constant-time compare, the CLI caller and the workflow wiring (including the
  fail-fast exit).
- `scripts/governance_mutation_gate.py`: `LLM_ROUTE_*`, `LLM_BROWSER_LOCKED_WITHOUT_KEY`,
  `LLM_CALLER_RUN_RESEARCH_REQUIRES_KEY` and `LLM_CALLER_MORNING_REPORT_FAILS_FAST`
  (18 pins).

不是买卖指令；研究信号，human executes。
