# Data Foundation Independent Review And Acceptance

Scope: first offline G0/B1-B3 delivery, based on c72fe1e. Not B4-B6, a production
release, current remote-main acceptance, source rights clearance or human QA.

## Review Matrix

| Finding | Reproduced failure | Repair | Regression |
| --- | --- | --- | --- |
| Future invocation hides failure | 2099 success masks a 2026 timeout | Bind invocation to measured start and validate reopened completion order | future invocation + reopened health conflict |
| Provider order returns stale row | First row old, later target row current; health was OK | Opt-in consumes unique target; reject duplicate stock dates before success; old ambiguous receipts blocked | adapter/files/health chain + historical ambiguity |
| Unsafe timestamp exception | Raw fake secret echoed by datetime parser | Fixed error code, suppressed cause | assert secret absent from exception |
| HTTP denial misclassified | 401/403 treated as outage | Safe typed HTTP permission classification | HTTP-shaped denials, not only PermissionError |
| Unbounded terminal remnants | Repeated finish failures create more partial files | Reconciliation required after retained partial | eight retry attempts keep one partial |
| FIFO input blocks | Reader waits before checking regular file | Nonblocking open then fstat rejection | child process with two-second deadline |
| Catalog changes bypass CI | Config-only PR misses path filter | Register exact catalog trigger and suite commands | workflow-registration test |

Two additional pre-review failures were fixed: an incomplete start directory could
be reused, and a per-stock context could omit ticker binding in actual params.
The crash matrix covers before/after STARTED and terminal hard-link publication,
then a new recorder instance. No external request is replayed on ambiguous IDs.

## Evidence Boundary

All provider replies, timestamps, credentials, source failures and FIFO fixtures
are synthetic. The live 10/30 missing row was not fetched or repaired. The old
settlement gates and legacy default transport behavior remain intact.

The first review reported seven P2 findings; all received failing regressions.
The follow-up retained the duplicate-target portion of original finding 2, then
the adapter/receipt/health regression was added and repaired. Final review outcome
and final commands belong in the separate delivery receipt, not inferred here.

## Remaining Gates

- B4: verified input cards and bounded industry/date material index.
- B5: authenticated read-only API/UI and scoped attachment verification.
- B6: entire vertical suite, remote CI, separately authorized isolated deployment,
  and actual Junyan/Reed task/download/peer-query/reconnect receipts.
- Reconcile the unmerged workbench stack with current remote main before push.
- Legal data-use/team-display evidence, source instrumentation expansion, real
  backfill requests and production acceptance remain separate.

No push, merge, service upgrade, ar-live write, scheduled collection, formal U4,
paper registration or trading authority is part of this delivery.
