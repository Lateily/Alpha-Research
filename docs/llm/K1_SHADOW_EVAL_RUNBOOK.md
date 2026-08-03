# K1 Shadow Eval Runbook

Owner: Reed.
Reviewer: Junyan.

This runbook starts only after the question-only pack is approved. It prepares
the K1 shadow evaluation without leaking answer keys or model names.

## Hard Gates

- Use only `docs/llm/EVAL_SET_v1_QUESTION_ONLY.md` as model input.
- Do not give `docs/llm/EVAL_SET_v1.md` to any model arm.
- Do not run Kimi until Junyan's approval is visible on GitHub.
- Keep Kimi cost within the approved `¥5` cap.
- Store Kimi cost in the LLM usage ledger.
- Do not write any investment conclusion from this run.

## Prepare The Run Folder

```powershell
python scripts/llm/k1_shadow_eval.py prepare `
  --run-dir outputs/llm/k1_shadow_eval
```

This creates:

- `model_inputs/kimi.md`
- `model_inputs/claude.md`
- `model_inputs/codex.md`
- `model_outputs/kimi.md`
- `model_outputs/claude.md`
- `model_outputs/codex.md`
- `private/unblind_map.json`

The three model input files are intentionally equivalent. Model identity stays
outside the prompt.

## Fill Model Outputs

After approval:

1. Run Kimi with `model_inputs/kimi.md`.
2. Ask Claude with `model_inputs/claude.md`.
3. Ask Codex with `model_inputs/codex.md`.
4. Paste each complete answer into its matching file under `model_outputs/`.

Do not edit `private/unblind_map.json`.

## Build The Blind Packet

```powershell
python scripts/llm/k1_shadow_eval.py build-blind `
  --run-dir outputs/llm/k1_shadow_eval
```

Send only this file to blind reviewers:

```text
outputs/llm/k1_shadow_eval/blind/K1_BLIND_REVIEW_PACKET.md
```

Keep this file private until scores are locked:

```text
outputs/llm/k1_shadow_eval/private/unblind_map.json
```

## Validate

```powershell
python scripts/llm/k1_shadow_eval.py validate `
  --run-dir outputs/llm/k1_shadow_eval
```

The validation checks that model inputs do not contain teacher-only fields and
the blind packet does not leak `kimi`, `claude`, or `codex`.

Not investment advice; evidence processing only; human executes.
