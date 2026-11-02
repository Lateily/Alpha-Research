# Deployment Reconciliation V1

Status: IMPLEMENTED_UNTESTED. All behavioral acceptance and independent runtime
review are deferred. This module does not synchronize, install or restart anything.

## Inputs

`foundation_release.reconcile_deployments(inventory, release)` consumes a saved
`ar.runtime-inventory.v1` object and a closed `ar.release-target.v1` object:

```json
{
  "schema": "ar.release-target.v1",
  "release_id": "candidate-1",
  "created_at": "2026-11-02T10:00:00Z",
  "target_code_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "target_source_tree_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "target_state_schemas": {"shared": "ar.shared-workspace.v1"},
  "repository_roles": ["candidate", "production", "shared"],
  "service_ids": ["nightly", "workbench"],
  "expected_inventory_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
}
```

These are synthetic values, not an approved release. The expected inventory hash
is the SHA256 of canonical inventory JSON, obtained independently of a submitted
inventory replacement. An inventory collected today is not a reconstruction of
its caller-supplied reference time. Both timestamps are retained in the report.

## Meaning Of The Report

- Missing/partial observation, code drift and dirty worktree are distinct.
- A clean directory with the requested SHA is LOCAL_METADATA_MATCH only.
- Cached origin/main is explicitly LOCAL_CACHED_NOT_FETCHED, never current remote main.
- Service state and code remain caller assertions, not observed process identity.
- Current inventory does not attest installed source-tree bytes or state schemas;
  their expected values are retained but their observation remains NOT_OBSERVED.
- Acceptance, rollback and approval receipts are not provided or verified here.

Consequently deployment_readiness stays BLOCKED_UNVERIFIED, even when all directory
SHAs match. The report is a drift checklist, not a release permission or a claim
that the running service was upgraded. A later separately approved deployment
must collect running-code/state evidence and same-version acceptance before use.

CLI (deferred, not executed in this batch):

```bash
python3 -B scripts/llm/foundation_cli.py reconcile --request /path/to/reconciliation.json
```

The request has exactly `inventory` and `release` fields. It is a local read-only
comparison. Output includes inventory_hash, release_hash and reconciliation_hash.
No command strings, Git mutation, service probe, install or rollback actions run.

## Read-Only Directory Observation On 2026-11-02

The coordinator separately read these Git references, without invoking the new
reconciler and without fetching any remote:

| Role | Observed reference | Scope |
| --- | --- | --- |
| Production directory | 333632910357baddcfbd9137ad5f01d666b9a912 | Local directory HEAD only |
| Existing shared workbench source | c72fe1e6b3292260930d35095a9c7a3a8dd3a146 | Local directory HEAD only |
| Local cached origin/main | 0ebde2fb0aa2ad04db1ab2d58b7d49bb3099b92a | Not fetched; not current remote proof |
| Foundation baseline | a5db0e846ffc984da07103d75f8026dca342154a | New wave3 edits not yet accepted |

Different roles intentionally remain on different versions. This engineering
request does not authorize aligning them. No running-process or remote-main
attestation follows from these four read-only Git observations.
