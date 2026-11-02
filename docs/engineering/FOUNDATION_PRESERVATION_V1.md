# Foundation Preservation V1

Status: **IMPLEMENTED_UNTESTED**. `sample_purpose: WORKFLOW_DEBUG`,
`testing_status: NOT_RUN`, `human_review: PENDING`. Production, trading, and
deployment authority are all **false**. Behavioral tests and independent review
are deferred by the current human instruction. Static inspection is not runtime
acceptance, backup completion, deployment readiness, or restore evidence.

## Scope

`scripts/llm/foundation_preservation.py` inventories **existing** portable
packages and produces an in-memory handoff manifest. It does not create an
archive, export a database, copy files, upload, download, write a receipt, buy
storage, prune, delete, restore, run workers, or change services or permissions.
It adds no second backup engine and invokes no provider or network API.

Package bytes are data, never executable code or import targets. The existing
backup/material validators remain the semantic boundary. Original evidence
seals, input lineage, degraded states, and `UNBOUND` meanings are not promoted to
research approval, source rights, or trading authority.

## APIs

```python
build_preservation_manifest(packages, *, created_at) -> dict
verify_preservation_copy(manifest, package_roots, *, expected_preservation_hash) -> dict
```

`packages` is a nonempty list or tuple of at most 32 **closed** dictionaries:

| Field | Contract |
| --- | --- |
| `package_id` | Unique ASCII identifier; 1-101 letters, digits, underscores, or hyphens, starting with a letter or digit. Case-fold collisions are refused. |
| `kind` | Exactly `SHARED_BACKUP`, `RESEARCH_LIBRARY` or `QUARANTINED_ORIGINALS`. |
| `local_root` | Existing, caller-selected local directory. A string or `Path`, never a URL or symlink. Used only for reading; not included in the result. |
| `expected_content_hash` | Independently retained, lowercase 64-character SHA-256. No inferred/default hash. |

`created_at` is a caller-supplied valid timezone-aware ISO timestamp with seconds
and an explicit offset or `Z`. Invalid dates, naive times, and invalid offset
minutes are rejected. It is handoff metadata, not an independently attested clock
or proof of when external storage occurred.

Source package roots must be distinct and non-overlapping. Destination roots
must likewise be distinct and non-overlapping. The destination API requires a
dictionary mapping the **exact** package IDs in the manifest to local roots;
missing, extra, renamed, or case-confused IDs are rejected. Destination paths may
differ from source paths. No source path is needed to verify a handoff.

The destination may even be the same root. That is a local reread, not evidence
of a copy or geographic/off-machine separation. The API deliberately makes no
remote-storage assertion in either case.

## Bound Content

The `ar.preservation-manifest.v1` result contains fixed debug/authority labels,
`created_at`, sorted `packages`, fixed `preserved_semantics`, fixed
`requirements`, and `preservation_hash`. Each package binds:

- Its ID, kind, and independently expected `content_hash`.
- The **complete actual file set**, as relative path -> SHA-256, including the
  archive's own `manifest.json`, library registrations, and original bytes.
- The complete relative directory set, including empty directories, and total
  file-byte count. Permissions, ownership, extended attributes, hard-link
  topology, and filesystem timestamps are not preservation promises.
- Validated backup schema, inventory scope, source storage schema, credential
  exclusion, event tail, table counts, artifact inventory, and directory
  semantics, or the existing material-library validation scope.

The handoff manifest is returned in memory, not placed inside a package. Adding
it or a transport receipt to a package changes the exact file set. Store such
handoff metadata separately through a separately approved process.

For `SHARED_BACKUP`, the module externally compares the archive's original
`backup_hash` with `expected_content_hash`, calls
`workbench_backup.read_shared`, checks the validated hash again, and reuses
`workbench_backup.verify_shared`. Legacy `ar-workspace-backup.v1` remains
supported through those validators. Derived legacy metadata is not incorrectly
treated as the original manifest's sealed body. This layer never calls
`backup_shared`, `restore_shared`, or `restore_check`.

For `RESEARCH_LIBRARY`, it calls
`foundation_materials.verify_library(root, expected_library_hash=hash)` and
requires both an exact `library_hash` match and a `files` mapping of relative
path -> SHA-256 equal to the complete independently read package inventory.
An omitted, extra, or changed file is not accepted as a partial preservation.

For `QUARANTINED_ORIGINALS`, the same exact-inventory binding uses
`foundation_quarantine.verify_quarantine` and its independently expected
quarantine_hash. Its fixed disposition remains opaque, unreviewed and barred
from research, rendering, execution or implicit transfer. Byte preservation is
not security clearance, library admission or evidence the PDF is malicious.

Inventories are reread around semantic validation. Concurrent changes fail
closed when observed; this is not a filesystem lock or an atomic snapshot of
multiple mutable packages. Supply immutable archives/libraries.

## Independent Verification

`preservation_hash` is SHA-256 of canonical JSON excluding only that field:
ASCII JSON, sorted keys, compact separators, and no non-finite values, matching
the existing evidence helpers. The independent `expected_preservation_hash` is
mandatory and must come from a separately retained trusted handoff record, not
be adopted from the untrusted manifest being checked.

Destination verification checks the closed shape, fixed labels/requirements,
self-hash **and** independent expected hash. It then reconstructs the handoff
from every named destination root with the original independent content hashes,
reopening the original validators, and compares the complete canonical result.
A caller-resealed manifest or archive does not replace those external anchors.
The API cannot establish the provenance of an anchor supplied by its caller.

The result schema is `ar.preservation-copy-verification.v1`. `package_bytes:
MATCH` and `verified_package_ids` describe only the local reads that the API
performed if eventually executed successfully. `status` remains
`IMPLEMENTED_UNTESTED`, with `testing_status: NOT_RUN`, `human_review: PENDING`,
and all three authorities false. A byte match is not runtime acceptance of this
new implementation. There is no optional remote receipt or input that can grant
`PASS`, storage authority, or restore authority.

These requirements are fixed in both outputs:

| Requirement | Value |
| --- | --- |
| Off-machine storage; geographic separation | `NOT_ATTESTED` |
| Encryption; access controls | `NOT_ATTESTED` |
| Source rights; provider retention | `NOT_ATTESTED` |
| Restore | `NOT_ATTESTED` |
| Transmission approval; restore approval | `PENDING` |

The original packages retain any more restrictive rights metadata. The manifest
neither grants transmission rights nor determines whether even transmitting
the manifest is permitted. A human must approve the destination, access,
encryption, source rights, retention policy, and transfer separately. Off-machine
durability and actual scratch restoration need separately authorized evidence.

## Bounds And Refusals

Read-only traversal uses directory descriptors with `O_NOFOLLOW`, validates
regular files before opening them, opens files nonblocking to avoid FIFO hangs,
and checks file/directory identities and modification metadata during reads.
Symlink roots/ancestors/members, dangling links, sockets, FIFOs, and devices are
refused. Internal portable paths are bounded ASCII components; traversal,
absolute paths, reserved device names, trailing dots, and case-fold collisions
are refused. Hard links are read as regular file bytes and are not durability
evidence.

The bound is 16,384 total entries and 1 GiB total file bytes across at most 32
packages, with a 256 MiB per-file streaming limit. Shared-backup metadata and
backup validation retain the existing evidence helper's 12 MiB file limit. Internal
paths are at most 2,048 characters/24 components. Returned manifest JSON is at
most 4 MiB, with a depth bound of 24 and 300,000 visited JSON nodes. Cyclic,
non-JSON, overly large/deep inputs, non-finite JSON, and duplicate parsed JSON
keys are rejected. Package dictionaries are closed, and additional manifest
fields (including remote receipts) are rejected. Exceptions are refusals, not
partial successful reports; paths must not be logged as public receipts.

## Deferred Evidence

`tests/test_foundation_preservation.py` is authored but **NOT_RUN**. It covers
synthetic shared and legacy backup handoffs, portable exact-file inventories,
local-copy non-attestation, original observation seals/`UNBOUND`, file tampering,
missing/extra files/directories, archive/handoff self-resealing, wrong independent
hashes, package/root confusion, symlinks/FIFOs, duplicates, malformed timestamps,
closed inputs, bounds, and authority-promotion refusals.

One mixed backup/library test uses a contract double only for
`foundation_materials.verify_library`; actual files and destination re-reads
remain real. It checks exact library hash/catalog delegation and refuses a
changed library file, incomplete catalog, and wrong library hash. A second
authored integration test uses real `ingest_material` -> mixed-package ->
destination verification and material-library reopening, checking original
bytes and restrictive rights metadata. Neither test has been executed.

Remaining acceptance gaps: all behavioral and negative tests, including the
authored real mixed-library integration; filesystem interruption/race exercises and platform portability;
same-HEAD integration/CI and independent human review. No actual external
transfer, external destination check, provider retention attestation,
cryptographic custody attestation, or restoration has occurred or is authorized
by this change.
