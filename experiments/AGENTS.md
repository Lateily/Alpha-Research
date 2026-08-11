# Research Engineering Instructions

These rules apply to `experiments/` in addition to the repository contract.

- Research code may emit evidence, labels, contracts, and scorecards. It may not
  emit or execute trading instructions.
- Preserve point-in-time semantics, registration timestamps, causal-cluster
  identity, direction separation, and explicit evidence grades.
- Treat missing or stale upstream data as a visible degraded state. Never fill it
  with zero or reuse a prior artifact without provenance and freshness checks.
- Production ledger and nightly outputs are single-writer runtime state. Teammate
  work must use temporary fixtures and `AR_OFFLINE=1` unless the task explicitly
  authorizes a production run.
- Every bug fix needs the failing research case as a regression test. Statistical
  claims require the framework's sample and independence gates.
- Do not rewrite historical records. Corrections use the approved append-only
  migration mechanism and Junyan approval.
