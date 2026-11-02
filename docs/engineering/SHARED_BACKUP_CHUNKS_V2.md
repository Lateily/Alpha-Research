# Shared Portable Backup V2

Approved scope: Junyan's 2026-11-02 instruction to repair the observed capacity
failure with chunked export and complete restore, preserving history, hashes,
seals and the global 12 MiB file limit. No formal production changes or merge.

## Format

Small exports retain `ar-shared-workspace-backup.v1` byte semantics. Oversized
exports use `ar-shared-workspace-backup.v2`. Its bounded `data.json` is a
`ar-shared-workspace-data-index.v2` index, not a monolithic table payload.
Each registered table has ordered row chunks under `data-chunks/`; an empty
table has zero chunks. Every descriptor binds its table, ordinal, starting row,
row count, raw byte count and SHA256. Every chunk also carries its own seal.
The existing backup manifest seals the index, all chunks, artifact inventory,
table counts and event tail. Hashes prove consistency, not source authenticity.

Chunk target is 4 MiB; an individual row may occupy a larger standalone chunk
only if the sealed chunk still fits the existing 12 MiB limit. Aggregate table
export is bounded at 256 MiB, 1024 chunks and 100000 rows. These are local backup
format bounds, not changes to global file acceptance. Oversized individual rows
remain explicit refusals; no truncation, compression or implicit history pruning.

## Read And Restore

`read_shared` continues returning normalized fixed-table rows to existing
consumers. Before restoring it checks exact table/chunk sets, types, ordering,
contiguous row spans, counts, byte sizes, file hashes, chunk seals, duplicate
primary identities and aggregate bounds. Existing credential, event-chain,
frozen-input, report, governance and queue validators still run.

Export index/chunks are archive metadata, not application artifacts: they are
not copied into live state. The existing migration uses the validated rows,
parameterized inserts, fresh staging, source-bound intent, complete artifact
verification and atomic promotion. Old complete v1 archives remain restorable;
limited legacy archives retain their existing migration refusal.

Generated migration receipts are bounded too, including their escaped database
row representation for subsequent backups. If a v1 receipt would exceed either
file bound, `ar.shared-migration.v2` binds the complete restored event projection
and source artifact inventory by count/head/hash references instead of copying
job results into a second large field. Original table rows, historical receipts
and report bytes remain unchanged. Restore rederives these references from the
validated archive; coherent edits to both receipt file and database still fail.
Existing valid v1 receipts retain their original representation on verification.

## Release

No alternate physical SQLite-copy path. No deleting or rewriting old history.
Reproduce the actual-size failure first. Test corruption even after outer hashes
are recomputed, inject restore interruptions, and verify all original table rows
and artifact bytes. Freeze a new final SHA, run the complete offline CI, mutation
gate, independent review and remote CI. Then back up actual old isolated state,
verify a fresh restore, and switch only the existing private shared workbench
with old code/state retained for rollback. Real two-device acceptance is separate.
