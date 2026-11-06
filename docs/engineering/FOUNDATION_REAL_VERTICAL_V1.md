# Foundation Real Vertical V1

Approved scope: finite endpoint observation, local preservation and one registered
earnings-material task through the existing shared queue. Implementation and
acceptance are isolated; production and the running shared service are unchanged.

## Contracts

- Operator-only observation: Tushare daily and moneyflow_dc, 603629.SH,
  20261104, one HTTP POST each, no automatic retry, redirects or fallback.
  Existing endpoint catalog and immutable START/terminal receipts remain the
  authority for format and date validation. Provider error text and tokens are
  never persisted. A gap is not a zero and a successful request is not research
  approval. Retry requires a new exact grant referencing the failed call.
- Local preservation: new immutable generation on this Mac; originals,
  quarantine, research outputs and a read-only trust-line snapshot have separate
  pins. Verify before copying and after cold recovery. Never delete history,
  increase global limits, restore credentials or claim off-machine preservation.
- Material task: operator registers an existing sealed pack. Browser chooses
  only its registered identifier. Existing actor/workspace/idempotency, queue,
  lease, subprocess deadline, output seal and recovery rules apply. Material
  input is a separate schema, never a market publication or current market input.
- Earnings output is WORKFLOW_DEBUG, UNRESOLVED and human_review=PENDING.
  Immutable per-job archive is published with its sealed output. Queries reopen
  the original validators; no mutable parallel research ledger is introduced.
- Rights remain UNVERIFIED. Shared pages expose metadata and citation locations,
  not PDF/report full text. No AI review is a human signature.
- New earnings submissions carry expected workspace ID and code SHA. Retention
  references the original job seal (which binds the complete deep archive),
  keeping the existing global path-depth and file-size limits unchanged.
- Repeated PDF extraction may reuse a bounded eight-entry pure derivation memo,
  keyed by actual PDF bytes, physical pages and extractor-source hash. Each call
  receives a new result dictionary. File inventories, independent pins, quotes,
  cutoff checks and output seals are still checked on every reopening; no seal,
  permission, registry validation or human review status is cached.
- The nested extractor bootstraps cache bypass and source-only imports before
  importing project helpers. Parent guards are not assumed to cross interpreters.
- Uncommitted material pools/attempts can be backed up before registration retry
  when retained originals independently verify against the intent's library pin.
  Recovery preserves bytes without adding registry rows or making them runnable.
  Unknown or unverifiable binary data still blocks acceptance; an intent's own
  resealed inventory cannot authorize a different library.
- Shared task downloads retain their object URL until the queued browser
  navigation has consumed it, then release it. Client acceptance must re-open
  actual downloaded bytes and compare the job/input/output bindings; clicking
  the button alone is not download acceptance.

## Release Gates

Normal, missing, stale, conflicting, tampered, interrupted and historical inputs
must be tested at their actual boundaries. Run targeted tests first, then the
complete suite on a clean final SHA and fresh nonauthor review. Actual calls run
only once on that final candidate. Failed live calls produce evidence, not a
retry. External preservation and two-human testing remain deferred. No push,
merge, current-service cutover, U4, paper or trade authority is implied.
