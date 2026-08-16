# AIOS-K1 Task Contract And Read-Only Registry

Owner: Reed. Reviewer: Junyan. Scope: offline AIOS control plane.

## What This Adds

AIOS-K1 turns AI work from chat memory into three deterministic records:

- `task_compiler.py`: turns a complete source record into `ai-task.v1`.
- `registry.py`: replays append-only state events into current task state.
- `reconciler.py`: reports gaps such as orphan tasks, stale claims, unlinked PRs,
  oversold DONE events, and delivered-but-unwired work.

This layer is source-system read-only. It does not write GitHub comments, call
model APIs, run ledger engines, mutate repo facts, or change research decisions.
The CLI may write an explicit local `--output` report path chosen by the user.

## Why It Matters

Before multi-model work can be trusted, every AI task needs a machine-readable
contract:

- who owns it;
- what files it may touch;
- what it must prove;
- what it must not do;
- what budget and network policy apply;
- who approves the result.

Without this contract, adding more models only makes the work faster to become
messy.

Every compiled task carries two distinct digests:

- `source_hash` identifies the original task source before compiler defaults and
  whitespace normalization. It cannot be recomputed from the compiled manifest.
- `manifest_hash` identifies the canonical compiled `ai-task.v1` fields. Downstream
  control-plane components call `validate_compiled_manifest()` and fail closed if
  those fields drift without a matching digest update.

The repository does not persist pre-A-010 compiled manifests. This contract
upgrade therefore has no stored-manifest migration in Phase 1; downstream tools
must consume freshly compiled manifests.

`manifest_hash` is an integrity checksum, not a signature or human approval.
Later Evidence and Human Gates must bind the manifest hash to task ID, commit SHA,
reviewer identity, and the approved decision record.

## Local Commands

Compile one task source JSON:

```powershell
python scripts/llm/ai_os/cli.py compile --input task_source.json --output task_manifest.json
```

Replay state events:

```powershell
python scripts/llm/ai_os/cli.py replay --events events.json --output registry_snapshot.json
```

Run read-only reconciliation:

```powershell
python scripts/llm/ai_os/cli.py reconcile --input reconcile_fixture.json --output ai_os_reconciliation.json
```

On Reed's Windows machine, use the bundled Python if `python` is not available:

```powershell
C:\Users\19463\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe tests\test_ai_os_k1_offline.py
```

## Fail-Closed Rules

- Missing objective, owner, file scope, acceptance tests, budget, or approval gate
  returns `SPEC_BLOCKED`.
- Unsupported risk or network policy returns `SPEC_BLOCKED`.
- Registry replay rejects forbidden shortcuts such as `RUNNING -> DONE`.
- `DONE` requires evidence references.
- Reconciler only reports findings; it never deletes, merges, comments, or edits
  external systems.

## Current Offline Verification

```text
ALL AIOS K1 OFFLINE TESTS PASS (25 tests, 0 network calls)
ALL AGENT ADAPTER OFFLINE TESTS PASS (56 tests, 0 network calls)
```

Not a trading instruction; research signal, human executes.
