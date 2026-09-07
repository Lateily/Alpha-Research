# Read-Only Migration Inventory

`scripts/migration_inventory.py` registers source artifacts. It does not migrate,
publish, approve research, open production databases, or grant team access.
The revised `ar.migration_inventory.v1` receipt carries
`consistency=PER_FILE_INVENTORY_NOT_A_SNAPSHOT`, `migration_ready=false`, and
`production_authority=false`.

## Revision And Output Discipline

- Every invocation requires a **new output directory**, outside every scan root.
- An existing directory is refused, even when empty. Existing inventories are
  never refreshed in place. Keep the original 20260907 inventory as revision 1.
- Output files are exclusively created relative to an opened directory handle;
  existing leaf symlinks/hardlinks are refused, never truncated.
- Source file reads do not follow symlink components. Links are separate
  `SYMLINK` records requiring review, not files to automatically restore.
- File changes during inspection cause refusal. Across files this remains a
  live inventory, not a transactionally consistent migration snapshot.

Example (operator supplies approved roots and a fresh output directory):

```sh
python3 scripts/migration_inventory.py \
  --root old-platform=/approved/read-only/source \
  --out /approved/audit/inventory-revision-2
```

The current safety implementation requires POSIX `O_NOFOLLOW` and directory-
relative IO (macOS/Linux). A host without these primitives refuses execution;
do not remove the guard to make it run on Windows. Reed's Windows material
remains a separately declared inventory gap until independently collected with
equivalent protection. This PR does not claim Windows execution acceptance.

## What The Classifications Mean

| Classification | Handling |
| --- | --- |
| `MIGRATE` | Preserve bytes and origin; includes untracked/ignored/filesystem code and documents, not just JSON data. |
| `GIT_RECOVERABLE` | Tracked content at recorded local HEAD. The referenced objects must still be proven recoverable at the destination; a local SHA alone does not prove remote availability. |
| `APPLY_TOMBSTONE` | Explicit working-tree deletion, including the source of a rename; do not resurrect it when overlaying a recovered Git tree. |
| `REVIEW_LINK_NO_FOLLOW` | Preserve link metadata for human review, without reading or automatically copying the target. |
| `NOT_MIGRATED` | Path-classified secrets, transient locks/shared memory, or new-platform state not being treated as old-system history. |

Physical deduplication may share a blob, but must retain every original path,
source root, run/version and purpose. Unknown files remain visible for triage.
Git child processes disable optional index writes, fsmonitor and network/lazy
fetch. Missing local Git objects are not silently fetched from GitHub.

## SQLite Is A Consistency Unit

The tool does **not** connect to source SQLite databases, even with `mode=ro`.
It records main files and recovery components and emits `SNAPSHOT_REQUIRED`,
`row_counts=null`, `integrity_verified=false`. No source checkpoint, schema
migration or journal-mode change is run.

WAL and rollback journals are not disposable caches: they may contain committed
or recovery-critical state. They remain in the inventory even when zero bytes.
Do not restore these independently or combine files taken at unrelated times.
SHM and lock files remain classified as transient.

Row counts and integrity are next-stage checks on an approved consistent
snapshot. Only after that snapshot proves the WAL/journal state has been
incorporated may the import omit its separate recovery components. Never use
`immutable=1` to ignore a live WAL and call the resulting older state complete.

## Legacy History Scope Approved By Junyan

The old platform's parquet panels and `data_history/sector_mapping.json` belong
in the data center's **read-only legacy namespace**, not in an active producer.
Each inventory entry carries:

- `category=LEGACY_HISTORY`;
- `quality=LEGACY_UNVALIDATED` (this inventory performs no financial/PIT validation);
- `read_only=true`, `active_research_input=false`;
- original root/path, available checkout HEAD, byte hash and path-derived version hint.

These are inventory labels and an import requirement, **not a claim that storage
ACLs have already been deployed**. Activation requires separate source licensing,
PIT/adjustment/units validation, contract acceptance and human approval. Merely
importing old panels cannot change screening, U4, paper rules or claim eligibility.

## Pointers, Credentials And Missing Scope

ET and public publication pointers resolve in their own namespaces. Missing,
malformed or unsafe targets are separately recorded; no missing manifest is
fabricated. PRESENT means a regular target exists, not that a publication is
fully verified.

Path-classified credentials are not read from either the working tree or HEAD.
The filename classifier is **not** a general secret detector. An archive or
ordinary filename can contain sensitive material; inventory and hashing do not
authorize upload. Sensitive-content review and data-license review are separate.

An inventory of named roots is not a whole-team inventory. Missing roots,
root-external backups, teammate files and unclassified entries must remain
explicit. Production sync, data transfer, cutover, cloud spending, paid inference
and team access each require their own human authorization.

## Acceptance

Run the behavior suite, registered mutation pins, and every local offline CI step:

```sh
python3 tests/test_migration_inventory.py
python3 scripts/governance_mutation_gate.py
python3 /Users/years/Desktop/Stock/e2e-twin/twin-20260902/tools/ci_local.py
```

Tests use only synthetic roots and local repositories. No acceptance command in
this PR scans `~/ar-live` or regenerates the first inventory.

不是买卖指令;研究信号,human executes.
