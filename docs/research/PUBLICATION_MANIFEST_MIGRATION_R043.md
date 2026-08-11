# R-043 Publication Manifest Migration

## Boundary

R-043 repairs the byte bindings of an already-published nightly bundle after an
approved data correction. It is separate from:

- R-040: causal-cluster and signal-field migrations;
- R-041: published research scorecard snapshots;
- the normal nightly publisher: new runs must still use the regular publish path.

Merging the tool does not authorize or execute a production migration.

## Transaction

1. `--plan` reads the current run and freezes both manifests, both
   `current_run.json` pointers, `publication_state.json`, artifact bytes,
   evidence, reason and target bytes into `plan_hash`.
2. The approval file binds the exact `plan_hash` to the authorization text
   quoted verbatim from the current session. It must label itself
   `TRANSCRIPT_ONLY_NOT_CRYPTOGRAPHIC`: this is auditable context, not proof of
   the speaker's cryptographic identity.
3. `--apply` acquires the same `nightly.lock` as `run_nightly.py`, rechecks the
   frozen state, bootstraps a durable empty-chain anchor, and appends
   `publication_migration_intent` to the dedicated R-015 ledger. The n=0 anchor
   keeps the first append recoverable if the process stops before anchor advance.
4. Both original manifests are preserved separately. The two manifests and two
   pointers converge through atomic writes, then all artifact hashes are
   reverified.
5. Only after a final verification passes is `publication_migration_commit`
   appended with a content-addressed verification receipt. A recoverable crash
   before commit replays the complete intent. A frozen third-state conflict is
   recorded once as `publication_migration_abort`, freeing the run for a new,
   separately approved plan without erasing the failed attempt.

The dedicated `publication_migration_events.jsonl` is intentionally excluded
from the manifest it governs. Including its own hash would make intent/commit
append operations invalidate the target manifest.

The WAL uses all three R-015 layers: hash chain, anchor and committed-git line
prefix. The git-prefix guarantee begins only after the first migration ledger
has been committed by its separate data PR. Before that commit, chain and anchor
still detect ordinary corruption, but an actor able to rewrite both local files
can erase local history. This boundary must not be described as absolute
immutability.

## Approval Document

The approval file is strict JSON:

```json
{
  "schema": "ar.publication_manifest_migration_approval.v1",
  "decision": "APPROVE",
  "approved_by": "Junyan",
  "approved_at": "2026-08-11T18:00:00+08:00",
  "approval_channel": "session_verbatim",
  "approval_ref": "session:r043-<human-reference>",
  "approval_verbatim": "<the complete authorization text from this session>",
  "evidence_strength": "TRANSCRIPT_ONLY_NOT_CRYPTOGRAPHIC",
  "plan_hash": "<64 hex characters>"
}
```

`approved_at` must not precede the plan's `requested_at` and may be at most 72
hours later. The verifier checks plan binding, channel, verbatim text, reference
shape and timing. It deliberately does **not** claim that `approved_by` proves
identity: a process that can write the approval file can also forge that string.
Production execution therefore still requires a fresh explicit operator command
after the reviewed code has been merged.

## Commands

Planning is read-only:

```bash
python3 experiments/execution_tracker/publication_migration.py \
  --plan --run-id <RUN_ID> \
  --reason "approved correction" \
  --evidence 'et:paper_signal_log.json=PR #241' \
  --evidence 'et:model_fund/nav_history.json=PR #242' \
  --plan-output /path/to/r043-plan.json
```

Apply requires the frozen plan, its hash and the session-verbatim approval file:

```bash
python3 experiments/execution_tracker/publication_migration.py \
  --apply \
  --plan-file /path/to/r043-plan.json \
  --plan-hash <PLAN_HASH> \
  --approval-file /path/to/r043-approval.json
```

Recovery replays only the intent's frozen bytes:

```bash
python3 experiments/execution_tracker/publication_migration.py \
  --recover --run-id <RUN_ID> --plan-hash <PLAN_HASH>
```

## Production Gate

Production may be touched only after the prerequisite PR and #258 are merged,
CI and independent adversarial review pass, the transcript evidence is bound to
the final plan, and the operator explicitly authorizes execution in a new
command. Until then the existing production stop and original manifests remain
unchanged. Local green tests, a pushed branch, or a merged implementation do not
authorize migration by themselves.
