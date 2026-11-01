# Workbench Data Center V1

This isolated extension consumes the existing shared-input and job contracts. It
does not change input hashes, PUBLIC/BUNDLE allowlists, report seals, source date
gates, queue semantics, current services or production authority.

## Read Contracts

- `ar.input-card.v1`: frozen publication and frozen attempt identities, input hash,
  source hashes, original binding/provenance, execution SHA, missing fields,
  optional governance health. Human review remains PENDING.
- `ar.material-index.v1`: derived from at most 100 registered inputs and verified
  sealed brief jobs. No desktop scan or second database. Max 50,000 projected rows,
  pages of 50, deterministic date-descending/material-id ordering. Unknown industry
  is null, unspecified classification is UNSPECIFIED, different versions stay rows.
- Missing issuer originals/thesis/valuation/case/paper types mean NOT_INDEXED in
  this limited scope, not proof that those files do not exist elsewhere.

Authenticated GETs reuse the exact private identity/Host/Origin/cookie boundary:

```
/api/shared-workspace/input-card/<registered-snapshot-uuid>
/api/shared-workspace/materials?snapshot_id=<uuid>&industry_key=<key>&trade_date=YYYYMMDD&ts_code=<ticker>&page=0
```

Only listed query keys, once each, are accepted. No caller-supplied actor, provider,
filesystem root or URL is used. Every GET reopens and verifies originals; sealed
jobs are verified through the existing job API. Queries do not create tasks,
select a snapshot, rewrite reports or persist indexes. Existing account identity
initialization remains the only permitted read-side initialization.

## Optional Governance Evidence

Default off. `--governance-evidence-v1` requires existing shared+private mode. The
fixed root is `<new-state>/governance-evidence/`, never an HTTP argument. Operator
prepares `registry.json` with schema `ar.governance-attachment-registry.v1`, whose
`bindings` map snapshot UUIDs to independently expected input_hash,
catalog_sha256, health_sha256 and receipt_catalog_hash. Max 100 bindings.

Each UUID directory contains `catalog.json`, `health.json` and receipts in the
existing data-call directory format. The root, registry and attachment entries
must be service-UID owned, non-symlink, not group/other writable. JSON reads retain
existing bounds. Hashes are checked against the external registry, receipt run/day
against the frozen publication, and health is recomputed from validated receipts.
Health cannot attest itself. Old runs without call records stay NOT_ATTACHED;
historical requests are never invented. The original snapshot seal remains intact.

Attachments currently remain operator-managed local evidence, outside the old
backup allowlist. Existing input/report restore tests do not certify attachment
backup or disaster recovery; that is a separate storage slice.

## UI

The existing Common Data view gains Input Card, source/binding details, gap plans
and industry/date/ticker material queries. No new collection, payment, approval
or trade controls. Brief links use existing verified job details. Late responses
from old actors/filters are discarded, stale/disconnected data cannot be shown as
fresh verification, and read retries never submit a job.

## Delivery Gates

Offline tests, browser layout/click checks and independent code review are code
acceptance only. Remote CI/push, existing 8443 upgrade, real two-computer receipts
and production synchronization are separate approvals. UI browser fixtures are
synthetic and are not evidence that source rights or research quality passed.
