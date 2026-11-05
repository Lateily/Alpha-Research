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

## Release Gates

Normal, missing, stale, conflicting, tampered, interrupted and historical inputs
must be tested at their actual boundaries. Run targeted tests first, then the
complete suite on a clean final SHA and fresh nonauthor review. Actual calls run
only once on that final candidate. Failed live calls produce evidence, not a
retry. External preservation and two-human testing remain deferred. No push,
merge, current-service cutover, U4, paper or trade authority is implied.
