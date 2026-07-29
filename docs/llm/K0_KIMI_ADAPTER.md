# K0 Kimi K3 Adapter

This folder contains the K0 smoke adapter for Moonshot Kimi K3.

## What It Does

- Calls the OpenAI-compatible chat completions API at `https://api.moonshot.cn/v1`.
- Uses model `kimi-k3`.
- Reads the API key only from local environment variable `MOONSHOT_API_KEY`.
- Appends token and estimated cost metadata to `scripts/llm/llm_usage.json`.
- Avoids writing prompts or responses to the ledger.

## Tianrui Setup

Do this part yourself. Never paste the API key into code, commits, documents, or chat.

1. Register at `platform.moonshot.cn`.
2. Top up a small amount, for example RMB 10, to unlock API usage.
3. Create your own API key.
4. Set it in your local PowerShell session without echoing the key on screen:

```powershell
$env:MOONSHOT_API_KEY = Read-Host "Paste MOONSHOT_API_KEY"
```

For a persistent Windows user environment variable:

```powershell
$key = Read-Host "Paste MOONSHOT_API_KEY"
[Environment]::SetEnvironmentVariable("MOONSHOT_API_KEY", $key, "User")
Remove-Variable key
```

Open a new terminal after setting the persistent variable.

## Smoke Test

From the repository root:

```powershell
python scripts/llm/smoke_kimi.py
```

Expected result:

- The terminal prints one Kimi K3 answer.
- The terminal prints this call's estimated cost in RMB.
- `scripts/llm/llm_usage.json` contains a new usage record.

## Cost Notes

The adapter estimates cost from returned token usage:

- cached input tokens: USD 0.30 per 1M tokens
- non-cached input tokens: USD 3.00 per 1M tokens
- output tokens: USD 15.00 per 1M tokens

The default USD/CNY estimate is `7.20`. Override it only from the terminal if needed:

```powershell
$env:LLM_USD_CNY = "7.20"
```

## PR Self-Check

- [ ] Smoke question and answer run through `python scripts/llm/smoke_kimi.py`.
- [ ] `scripts/llm/llm_usage.json` contains the new cost record.
- [ ] No API key appears in source code, docs, commits, or chat.
- [ ] All changes stay inside `scripts/llm/` and `docs/llm/`.
- [ ] Output is treated as evidence processing only, not an investment instruction.
