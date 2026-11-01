# Foundation Retention Pins V1

Implementation status: **IMPLEMENTED_UNTESTED**. All tests are **NOT_RUN** by
explicit wave-2 instruction. Syntax inspection is not behavioral acceptance.
Human review is **PENDING**. There is no production or trading authority.

## Boundary

`scripts/llm/foundation_retention.py` describes selected historical evidence in an
existing portable local backup. It does not create a backup, copy artifacts,
restore state, introduce a database, contact a provider, or change a registry.
The backup itself remains the retention unit; a pin is not a copy of its bytes.

The caller must supply an independently retained `expected_backup_hash`. Reading
that value from an untrusted archive immediately before pinning does not establish
independence. An internally resealed archive cannot substitute for the caller's
expected archive identity.

Build and verification reuse `workbench_backup.read_shared` and `verify_shared`.
Those boundaries validate tables, inventory, event chains, registered frozen
inputs and successful shared-job seals. Selected snapshots additionally reopen
through `FrozenInputs.verify_registered`. No alternate verification or copy
engine is introduced. These operations use the backup verifier's existing
in-memory validation image, not a new persistent state database or restore.

## Library Interfaces

```python
build_retention_pin(backup_root, *, expected_backup_hash, snapshot_ids,
                    job_ids, case_refs=(), created_at) -> dict
verify_retention_pin(pin, backup_root, *, expected_backup_hash) -> dict
write_retention_pin(pin_root, pin) -> dict
```

The request fields pass through directly from coordinator JSON. `backup_root`
and `pin_root` are explicit local string/Path roots. Relative roots are anchored
to the caller's current directory without expanding `~`. Symlink roots and
ancestors, traversal, control characters and URL roots are refused.

`snapshot_ids` and `job_ids` are lists or tuples, at most 100 of each, with no
duplicates. At least one registered snapshot or job is required; notes alone
cannot create a pin. Snapshot IDs are canonical UUID strings. Jobs must be real
registered shared queue rows or legacy event-projected jobs, not names inferred
from orphan artifact directories. Ambiguous identities are refused. An older
registered snapshot is allowed; current source pointers are never consulted.

`case_refs` defaults to an empty sequence. Each is a bounded relative logical
reference, for example `cases/review-note-001`, without traversal, a URL, or an
absolute machine path. Every reference remains `verification=NOT_VERIFIED` and
`case_authority=false`. It is not case/plan approval or evidence of access rights.

`created_at` is a caller-provided, timezone-aware ISO timestamp with seconds
and `Z` or an explicit offset. It is preserved, not inferred from the machine
clock, and is not a trusted timestamp or current-data attestation.

The pin is a closed JSON object, bounded to 1 MiB, depth 16 and 50,000 nodes.
Nonfinite values, non-JSON objects, cycles, secret-shaped content, unknown fields,
duplicate selections and malformed hashes are refused. Portable references are
limited to eight components and 1,024 characters. Original evidence is not
rewritten or sanitized into a new truth.

## Pin Fields

The artifact schema is `ar.retention-pin.v1`. Every pin carries
`sample_purpose=WORKFLOW_DEBUG`, `testing_status=NOT_RUN`, `human_review=PENDING`,
`production_authority=false` and `trading_authority=false`.

| Field | Meaning |
| --- | --- |
| `created_at` | Exact caller timestamp; no trusted time claim |
| `backup` | Independently expected `backup_hash`, archive schema and inventory scope, `manifest_ref=manifest.json`, `data_ref=data.json`, `credentials_included=false` |
| `snapshots` | Sorted selected registered snapshot descriptors, unchanged input/publication/attempt/snapshot hashes, run/date/scope and relative frozen references |
| `snapshots[].records` | Original per-record `status`, `binding` and `source_sha256`; `UNBOUND`, optional absence and unavailable hashes stay degraded |
| `jobs` | Sorted registered IDs, registration table/event origin, `registry_hash`, original kind/status, identity binding, original result and relative artifact references |
| `case_refs` | Sorted unverified logical notes, never case authorization |
| `limitations` | `off_machine_retention=NOT_ATTESTED`, `source_rights=NOT_ATTESTED`, `case_authorization=NOT_VERIFIED`, `deletion_authority=false` |
| `pin_hash` | Existing canonical SHA-256 seal of every other field |

For shared jobs, `registry_hash` is SHA-256 of the original exported job-body
UTF-8 bytes. For legacy jobs, it is the canonical seal of the original matching
events. A legacy started job retains the existing backup projection's
`INTERRUPTED` status and `LEGACY_UNATTRIBUTED` actor; a missing shared snapshot
identity is not invented. Successful legacy artifacts receive the existing
backup verifier's checks, not a newly invented shared seal. Original successful
shared results retain their `seal_hash` and all original result hashes.

Verification first checks shape, fixed labels and the pin self-hash, then
rebuilds the pin from the independently expected backup and compares all fields.
It does not trust pin-supplied status, run identity, file references, result
hashes or seals. It reopens successful job outputs on every verification.

## Explicit Local Write

Writing validates the pin's shape and self-hash and calls the existing durable
`workbench_backup.write_new` once for `<pin_root>/<pin_hash>.json`. Duplicate
files, including byte-identical retries, and destination symlinks are refused.
The existing atomic no-replacement publisher handles concurrent publication;
errors propagate, and failed temporary write evidence can remain. This module
does not delete pins, backups or failed evidence, overwrite history, prune
sources, schedule work, upload remotely, or implement a retention/deletion gate.

The JSON-serializable receipt has schema `ar.retention-pin-write.v1`, the same
five workflow/review/authority labels, `status=LOCAL_PIN_WRITTEN`, `pin_hash`,
relative `pin_ref=<pin_hash>.json`, `archive_reverified=false`,
`off_machine_retention=NOT_ATTESTED`, `source_rights=NOT_ATTESTED`,
`case_authorization=NOT_VERIFIED` and `deletion_authority=false`. It never
contains an absolute output path. `pin_root` is not inferred from the backup;
callers should use a separate local output directory so the archive remains
unchanged and its exact inventory remains verifiable.

The writer has no backup-root or independently expected hash parameter, so it
does **not** verify archive availability or bindings. Use a freshly built or
verified pin before writing; for received pins, call `verify_retention_pin`
first. A write receipt is not a backup verification result.

## Limitations And Deferred Gate

Pins do not attest off-machine storage, replication, availability after the
check, encryption, retention duration, legal hold, ownership, source licenses,
or rights to retain/use data. They grant no trading, execution, deletion or
production authority and require no owner credentials or live service.

The self-hash is an integrity checksum, not a signature: an actor can reseal a
different legitimate selection, case-note set or caller timestamp. The external
expected backup hash binds archive evidence but does not authenticate those
caller choices. Independently authenticate a pin hash if that distinction is
required. Multi-file backup verification is not a filesystem snapshot against
hostile concurrent writers; use a stable, access-controlled archive and keep its
independent expected hash.

Deferred regressions in `tests/test_foundation_retention.py` cover historical
inputs and degraded bindings, expected-hash mismatch, unknown IDs, resealed and
tampered archives/pins, successful output/seal failures, symlinks, duplicate
writes, notes/authority refusal, bounded inputs and portable reopening without
the original source/state or credentials. They are written but **NOT_RUN**.
No test, build, mutation, browser, CLI, provider or live probe was executed in
this implementation batch. Integration and behavioral acceptance remain pending
on one frozen candidate SHA, with independent review before any separate
production/service authorization.
