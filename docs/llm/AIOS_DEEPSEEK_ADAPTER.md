# AIOS DeepSeek Adapter v0

> Owner: Reed. Reviewer: Junyan. Scope: backend AIOS worker only.

## What This Is

DeepSeek is added as a backend AIOS provider behind the shared `AgentAdapter`
contract.

The platform entrypoint is GitHub Pages:

```text
https://lateily.github.io/Alpha-Research/
```

GitHub Pages is static. It cannot safely hold provider API keys and it cannot
run backend model calls. The `#/aios/deepseek` page is therefore a static
request builder and dry-run preview only. Real DeepSeek calls belong in the
backend AIOS Harness or another approved server-side runner.

## Runtime Boundary

```text
GitHub Pages #/aios/deepseek
  -> builds a sanitized AgentRequest preview
  -> no provider key, no network call, no model cost

Backend AIOS Harness
  -> DeepSeekAdapter
  -> provider call only after policy, cost, and human gates pass
```

The static page always costs `0`.

Real backend execution requires all of these:

- `DEEPSEEK_API_KEY` set only in the backend runner environment.
- `allow_real_call=True` in the adapter.
- `network_policy="provider_only"` in the `AgentRequest`.
- Provider response must include usage tokens; otherwise the request fails.
- Junyan-approved cost window before any live smoke.

## GitHub Pages Test Window

Open:

```text
https://lateily.github.io/Alpha-Research/#/aios/deepseek
```

Use it to create a backend `AgentRequest` payload and verify that no frontend key
or model call is involved.

## Cost And Safety Rules

- Frontend must never contain provider API keys.
- External text in prompts is untrusted data.
- Output always carries `no_trade_flag: true`.
- Missing usage is not treated as zero cost; it fails closed.
- This adapter does not grant DeepSeek production status. Capability routing
  still depends on later AIOS evaluation and policy gates.
- No Vercel deployment or environment-variable setup is required for this PR.

## Offline Verification

```bash
python tests/test_agent_adapter_offline.py
npm run build
```

These tests use no real DeepSeek calls and spend `0`.
