# AIOS A-010 Context Builder

Owner: Reed. Reviewer: Junyan. Scope: offline AIOS control plane.

## Purpose

Context Builder turns one compiled `ai-task.v1` manifest into a deterministic
`ai-context.v1` packet. The packet records which authority files were read, in
what order, at which commit, with file hashes and freshness metadata.

This prevents agents from relying on chat memory or reading different context
for the same task.

## Inputs

- A compiled `ai-task.v1` manifest.
- A local repository root.
- Optional `data_cutoff`.
- Optional external input descriptors.

External input text is never stored in the context packet. It is hashed and
marked `UNTRUSTED`.

## Read Order

The v0 read order is fixed and offline:

1. `AGENTS.md`
2. `docs/ARCHITECTURE_MAP.md`
3. `docs/llm/AI_OS_ENGINEERING_BACKLOG.md`
4. Nested authority files implied by scope, such as `scripts/llm/AGENTS.md`
5. Manifest `authority_docs`
6. Manifest `input_contracts`
7. File-like acceptance test paths

Commands in `acceptance_tests` are not treated as files.

## Output

The output schema is `scripts/llm/schemas/context.schema.json`.

Each packet includes:

- `context_hash`
- `task_id`
- `source_hash`
- `commit_sha`
- `loaded_at`
- `data_cutoff`
- `freshness`
- `read_order`
- per-file `content_hash`, `git_blob`, `mtime_utc`, and size
- external input hashes and trust labels

## Fail-Closed Rules

Context Builder returns `SPEC_BLOCKED` when:

- the manifest is malformed;
- an authority or input contract file is missing;
- a referenced path is absolute, encoded, parent-relative, or otherwise unsafe;
- a loaded authority/input file contains Git conflict markers at line start.

## Non-Goals

- It does not call model APIs.
- It does not read GitHub, web pages, market data, or private chats.
- It does not route agents.
- It does not schedule tasks.
- It does not write GitHub comments or mutate repo state.
- It does not decide whether a task is approved.

## Local Commands

Build context from a compiled task manifest:

```powershell
py -3.11 scripts/llm/ai_os/cli.py context --manifest task_manifest.json --repo-root .
```

Run offline verification:

```powershell
py -3.11 tests/test_ai_os_a010_context_offline.py
```

Not a trading instruction; research signal, human executes.
