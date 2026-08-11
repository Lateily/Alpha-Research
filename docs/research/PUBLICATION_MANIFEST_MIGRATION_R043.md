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
2. A human-side process signs that exact hash with
   `~/.ar_publication_migration_approval_key`. The key must not exist in an
   agent environment and must deny group/other permissions.
3. `--apply` acquires the same `nightly.lock` as `run_nightly.py`, rechecks the
   frozen state, bootstraps a durable empty-chain anchor, and appends
   `publication_migration_intent` to the dedicated R-015 ledger. The n=0 anchor
   keeps the first append recoverable if the process stops before anchor advance.
4. Both original manifests are preserved separately. The two manifests and two
   pointers converge through atomic writes, then all artifact hashes are
   reverified.
5. Only after verification passes is `publication_migration_commit` appended.
   A crash before commit is recovered from the complete intent.

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
  "approval_channel": "device_signature",
  "approval_ref": "device:r043-<human-reference>",
  "plan_hash": "<64 hex characters>",
  "signature": "<HMAC-SHA256 over canonical JSON without signature>"
}
```

`approved_at` must not precede the plan's `requested_at`. A GitHub author name,
an agent comment, or free text does not replace the signature.

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

Apply requires the frozen plan, its hash and an independently signed approval:

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
CI and independent adversarial review pass, the approval is signed outside the
agent environment, and the operator explicitly authorizes execution. Until
then the existing production stop and original manifests remain unchanged.
