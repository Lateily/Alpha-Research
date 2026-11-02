# Foundation Materials V1

Status: **IMPLEMENTED_UNTESTED**. `sample_purpose=WORKFLOW_DEBUG`,
`testing_status=NOT_RUN`, `human_review=PENDING`. Production, trading and
deployment authority are false. Tests and independent review are deferred.
No materials were ingested during implementation.

## APIs

```python
ingest_material(source_root, library_root, manifest) -> dict
verify_library(library_root, *, expected_library_hash=None) -> dict
query_library(library_root, *, industry_key=None, trade_date=None, ts_code=None) -> dict
```

Only the explicit ingest call writes. The module introduces no own dispatcher or
HTTP registration; the coordinator's `foundation_cli` supplies explicit
`material-ingest` and `materials` routes. There is no import-time activity,
provider fetch, database, decision ledger or service wiring in this module.
Read APIs reopen and stream every registered original, including on a filtered
query. Query filters are exact equality and combine with AND; `None` means no
filter. Dates are `YYYYMMDD`; A-share tickers are six digits plus `.SH/.SZ/.BJ`,
Hong Kong tickers five digits plus `.HK`. A manifest must explicitly use
`ts_code: null` for a non-ticker material.

`verify_library` returns `library_hash`, `files`, `materials`, `registrations`,
`library_id`, labels and limitations. `files` is the **entire** portable mapping
of POSIX relative path to lower-case SHA-256, including `library.json`, every
`registration.json`, and every original byte file. Query retains this entire
inventory and hash, not merely the selected rows. Ingest adds `registration_hash`.
No absolute source path is stored.

The deterministic `library_hash` uses `workbench_evidence.sealed` on:

```json
{"schema":"ar.material-library-inventory.v1","files":{"relative/path":"sha256"}}
```

Canonical JSON sorts keys. `expected_library_hash` must be independently retained
by the caller; without it, `hash_binding=SELF_CONSISTENCY_ONLY`. Self-hashing does
not authenticate a publisher, historical availability, code execution, rights,
or an owner who can rewrite the entire library. An append changes this snapshot
hash. Preservation consumes this exact hash and complete `files` mapping.

## Manifest

Closed schema `ar.material-intake.v1`; unknown fields are rejected. This concrete
shape uses synthetic identifiers and placeholder hashes, not importable evidence:

```json
{
  "schema": "ar.material-intake.v1",
  "library_id": "private-research-001",
  "created_at": "2026-11-02T18:00:00+08:00",
  "materials": [
    {
      "material_id": "issuer-filing-2025",
      "kind": "original",
      "version": "v1",
      "title": "Issuer annual filing",
      "industry_key": "801010",
      "industry_taxonomy": "SW",
      "taxonomy_version": "2021",
      "ts_code": "600000.SH",
      "trade_date": "20261030",
      "run_id": "research-20261030-001",
      "code_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "published_at": "2026-10-29T08:00:00+08:00",
      "available_at": "2026-10-29T09:00:00+08:00",
      "cutoff_at": "2026-10-30T15:00:00+08:00",
      "provenance": {
        "publisher": "Issuer name",
        "provider_id": "issuer-site",
        "source_locator": "https://issuer.example.invalid/filings/2025.pdf",
        "captured_at": "2026-11-02T10:00:00+08:00"
      },
      "original_refs": [],
      "rights": {
        "status": "UNVERIFIED",
        "visibility": "PRIVATE",
        "sharing_allowed": false,
        "model_use_allowed": false
      },
      "files": [
        {
          "source_path": "issuer/2025.pdf",
          "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
          "size_bytes": 123456
        }
      ]
    }
  ]
}
```

Each hash and byte size must come from an external, independently supplied
manifest. The ingester computes actual hashes, never substitutes a computed hash
for a missing expectation. Original bytes are copied without rewriting,
normalization, extraction or redaction. Metadata is normalized to canonical JSON.
Supplied code/run identifiers are retained assertions, not proof of running code.

Allowed kinds: `original`, `thesis`, `valuation`, `case`, `strategy`, `review`,
`attribution`. All rows require the keys in the example. Non-original rows must
set `provenance: null` and provide nonempty `original_refs`: SHA-256 strings
identifying files from `original` rows already registered or in this intake.
Originals must have empty `original_refs` and non-null provenance. This finite
contract does not model arbitrary multi-hop derivation graphs.

Publisher is a nonempty, control-free string of at most 500 characters.
Provider ID, IDs, version, taxonomy name/version and industry key are explicit
1-101 character ASCII identifiers (`[A-Za-z0-9][A-Za-z0-9_.-]*`). No taxonomy or
version is guessed. Locators are at most 2048 characters: credential-free
HTTP(S) URLs without userinfo, query or fragment, or `document:<identifier>` for
an offline publisher document identifier. Credential-shaped values and decoded
control characters are refused, not logged/redacted into apparently complete
provenance. Keep credentials and signed URLs outside the manifest; provide a
stable publisher locator. No locator is fetched or independently validated.

## Clocks And Authority

All timestamps require explicit offsets, seconds and valid calendar values.
`created_at` cannot be in the future at ingest. Source publication, original
availability and retrieval are distinct assertions:

- Every row: `published_at <= available_at <= created_at`, `cutoff_at <= created_at`.
- Original: `available_at <= cutoff_at` and `available_at <= captured_at <= created_at`.
- Derived: artifact publication/availability may be **after** the frozen cutoff.
- A cutoff's UTC+08 calendar date cannot exceed its row's `trade_date`.
- Every referenced original must be available by the derived row's cutoff and
  artifact availability. Missing originals and known-after-cutoff sources fail.

Late retrieval is allowed for retrospective research. On reopen each returned
row derives `point_in_time_capture_status=RETROSPECTIVE_CAPTURE` when its original
or any referenced original was captured after that row's cutoff. Otherwise it is
`CAPTURED_BY_CUTOFF_NOT_INDEPENDENTLY_ATTESTED`. Retrieval never replaces original
availability. Neither classification attests historical/PIT eligibility:
`artifact_pit_use=NOT_ATTESTED` and `prospective_sample_eligible=false` always.
Source availability remains caller asserted, not independently verified.

Rights may be omitted and default to the exact restrictive object above. Rights
expansion or conflicting authority labels fail; this v1 does not approve grants.
All stored envelopes/rows and returned reports retain debug/unreviewed labels.
Case/review registration is not formal approval. Private storage does not grant
sharing, team access, model use, trading or deployment permission.

## Publication And Bounds

The explicit library root must be new/empty or an exact recognized library.
An existing repository, database/state root, or other populated root is refused
before writing. The parent must already exist. Ingest requires an effective-user
owned root with no group/world write bits; a new root is mode 0700. Source and
library roots must be disjoint, with neither an ancestor of the other.

Layout:

```text
library.json
registrations/<registration_hash>/registration.json
registrations/<registration_hash>/files/<original_sha256>.<allowed-extension>
```

Registration hashes seal the normalized manifest and fixed labels. Directories
and original files use exclusive creation, never replacement or source hardlinks.
Metadata reuses `workbench_backup.write_new`; originals use bounded streaming
because the existing 12 MiB evidence reader is too small for original PDFs.
Every path component is opened with no-follow directory descriptors; special
files, symlinks, hardlinked files, executable files and read-time changes fail.
Cooperating readers/writers lock the directory descriptor using Unix `flock`.
This is a Unix local-filesystem contract, not protection against a hostile owner
or non-cooperating writer racing directory renames.

Registration metadata is published last, after file and directory fsyncs. Any
partial registration, extra file/directory or interrupted metadata temp file
blocks the entire library as quarantined/unrecognized. Partial bytes are retained;
there is no automatic cleanup, replacement or retry-overwrite. Human inspection
and a separately authorized fresh destination are required. Duplicate material
ID/version pairs, file hashes and batch source paths fail. Versions may append
new bytes; the same material ID must retain kind, ticker and exact industry
taxonomy/key/version. A changed taxonomy requires a new material ID. No history
is silently merged. Appending must not race a preservation export.

Limits: 256 materials/registrations per library, 16 files per material, 1024
original files, 256 MiB per file, 1 GiB total original bytes. Each JSON envelope is
at most 4 MiB, depth 16, 100,000 nodes, 10,000 entries/container, 16,384 characters
per string; titles at most 500 characters. Streaming uses 512 KiB chunks.
Paths are portable ASCII, at most eight components and 1024 characters, with
credential-shaped names and traversal refused. Only `.pdf/.txt/.md/.csv/.tsv/.json`
are accepted; JSON originals must be bounded objects. Text must be UTF-8 without
binary controls. PDFs require a PDF header; recognized active/encrypted PDF
features, executable/archive magic and obvious credentials are refused.

Credential inspection is heuristic, including a bounded overlapping window.
Compressed/encoded PDF content, malware and binary credentials are **not**
completely detected. No PDF parser, antivirus or content-safety certification is
claimed. No original is opened/rendered/executed. False positives may require a
separately reviewed import path; do not disable guards to force intake.

## Deferred Evidence

`tests/test_foundation_materials.py` authors normal, post-cutoff derived,
retrospective-capture, known-after-cutoff, expected-hash, metadata/original tamper,
duplicate/version/taxonomy, provenance, rights, links, limits and interruption
counterexamples. **NOT_RUN**. No runtime acceptance, build, mutation run, browser
QA, ingestion, export, network action or independent-review PASS occurred.
Remaining: execute these tests under an authorized integration window, validate
cross-package CLI/preservation behavior, exercise large original PDFs and crash/
concurrent/filesystem failure cases, and obtain human security/rights review.
