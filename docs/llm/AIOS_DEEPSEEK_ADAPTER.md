# AIOS DeepSeek Adapter v0

> Owner: Reed. Reviewer: Junyan. Scope: backend AIOS worker only.

## What This Is

DeepSeek is added as a backend AIOS provider behind the shared `AgentAdapter`
contract. The frontend page is only a test console. It never receives the
DeepSeek API key and it does not decide which model is allowed in production.

## Runtime Boundary

```text
Frontend /aios/deepseek
  -> POST /api/aios-deepseek
    -> server gate checks mode, key, size, cost reporting
      -> DeepSeek provider call only when explicitly allowed
```

Default mode is `dry_run`, which makes no provider call and costs `0`.

`live` mode requires all of these:

- `DEEPSEEK_API_KEY` set on the server only.
- `AIOS_DEEPSEEK_RUN_KEY` set on the server only.
- Matching `X-AIOS-Run-Key` header from an approved operator.
- Provider response must include usage tokens, otherwise the request fails.

## Local Test Window

Open:

```text
/aios/deepseek
```

Use `dry_run` for unlimited UI and backend gate testing. Use `live` only after
Junyan approves the server environment and cost window.

## Cost And Safety Rules

- Frontend must never contain provider API keys.
- External text in prompts is untrusted data.
- Output always carries `no_trade_flag: true`.
- Missing usage is not treated as zero cost; it fails closed.
- This adapter does not grant DeepSeek production status. Capability routing
  still depends on later AIOS evaluation and policy gates.

## Offline Verification

```bash
python tests/test_agent_adapter_offline.py
node tests/aios-deepseek-api.test.mjs
npm run build
```

These tests use no real DeepSeek calls and spend `0`.
