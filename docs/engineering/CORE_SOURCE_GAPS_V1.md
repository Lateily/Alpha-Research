# Core Source Gap Closure V1

Authority: Junyan's2026-11-09 ordered recovery/core-gap/card implementation.
Recovery dependency4e91a30 has scoped real-backup/HTTP/process evidence,
nonauthor recheck,115/115 local CI steps and1625/1625 declared mutation kills.
No production/shared/source schedule change or new provider request is implied.

## Finite Scope

Consume existing EndpointSession START/terminal/catalog evidence only. First
scope is daily(close,trade_date,ts_code) and moneyflow_dc(net_amount,trade_date,
ts_code), one exact security/day per logical request. Those fields are not full
OHLC or full money-flow coverage. Other endpoints/fields stay OUT_OF_SCOPE.
No secret, arbitrary provider, browser path, command or dispatcher is accepted.

An append-only local ledger freezes the original evidence files by an external
inventory SHA256, verifies the existing catalog and summaries, and appends one
hash-chained event per new batch. All writes require the expected current head;
Ledger roots, including precreated private empty directories, must be outside
all Git ancestors. Source evidence may be retained inside an artifact checkout.
duplicate logical calls with changed evidence refuse. Copies, failed drafts and
old failures are retained, never edited into success. Each projection reopens
source bytes and the chain against an independently supplied head hash.

## State And Time

Scope identity is API/security/requested day/exact fields, never merely industry
or today's date. A newer day's success cannot close an older day's gap. Record
request status, data quality, fixed reasons, logical-call ID, evidence hash and
observation time separately from research readiness and rights.

For temporary failures, propose a human recheck no earlier than15minutes after
the completed observation, with at most2 observed attempts before further
reconciliation. Permission, invalid evidence, interruption and out-of-scope are
distinct blockers; missing completed time never becomes a fabricated timestamp.
These are operator proposal defaults, not approved automatic retries or market
availability schedules. dispatch_allowed and automatic_retry always remain false.
Valid later evidence for the exact same scope can show RECOVERED_SCOPE_OBSERVED;
the original failure and observation chronology stay visible. Equal-time
contradictory results remain blocked, and a late older observation cannot
overwrite a newer one. Scope-valid data is not research/model/human approval.
Equal-time successful responses with different response hashes are conservatively
conflicting even if their row count and quality flags match; identical response
bytes do not false-block. No raw values or provider message is stored here.

## Public API

core_source_gaps.evidence(root) returns a verified evidence_hash and calls.
ingest(root,source_root,*,expected_evidence_hash,expected_head) freezes/records.
view(root,*,expected_head,observed_at) derives bounded status and recheck plans.
Standalone CLI uses only these APIs and closed JSON requests. There is no real
source invoke path in this slice. Junyan separately approved one historical
603629.SH/20261030 moneyflow_dc three-field recheck. A supplemental isolated
script reserved a new one-use global grant before START/transport; it returned
OBSERVED_SCOPE_VALID once. The grant is consumed; no retry is authorized.
The old20261104 grant and10/30 nightly failure remain unchanged. A late receipt
does not retroactively accept that run or create a prospective sample.

## Acceptance

TDD covers real EndpointSession-generated failure/success fixtures; permission,
interruption, missing/old/future/wrong entity, exact field/date identity, chronology,
CAS conflicts, tampering, durable reopen, duplicate logical calls and exhaustion.
Preserve original catalogs, hashes, bounds and all existing mutation records.
Use one final SHA for full offline CI/mutations, retained20261104 evidence ingest,
same-scope synthetic recovery and independent engineering review. Real historical
recheck/production hook adoption/shared UI publication remain separately scoped.
