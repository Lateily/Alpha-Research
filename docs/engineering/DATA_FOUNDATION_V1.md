# Data Foundation V1: First Offline Slice

## Boundary

This candidate starts the approved G0 blueprint. It is not a production update,
an active shared-workbench upgrade, or evidence of improved investment results.
Junyan owns decisions; the assistant implements the engineering. No teammate
availability is a development prerequisite. Final independent code review remains.

The catalog covers exactly five endpoints. Only opt-in `fund_source` daily and
moneyflow_dc calls have adapters. The other three are NOT_INSTRUMENTED. Existing
default call paths, settlement date gates, retry budgets and calculations remain.
Recorded units are source-code declarations, not freshly verified vendor rules;
unknown units and all rights remain UNVERIFIED. Catalog entries never grant API,
team-display, external-model, or redistribution permissions.

The two instrumented paths are per-stock: context and actual request must name
the same ticker. Whole-market entity coverage needs a separate later contract.
The opt-in fund adapter selects the unique requested target row, not provider
array order; the uninstrumented legacy path is unchanged.

## Components

- `config/data-source-catalog.v1.json`: endpoint/date/consumer/unit/rights inventory.
- `experiments/data_governance/catalog.py`: strict schema, duplicate-key and
  non-finite rejection, canonical content hash, exact call context.
- `call_receipts.py`: bounded immutable STARTED/terminal files. Records logical
  provider calls, not HTTP attempts. No raw result rows, provider messages or keys
  are persisted. A response hash is not evidence that its contents are true.
- `health.py`: per-run/per-ticker freshness, missing instrumentation and safe error
  classes. Old target days are listed out of scope, not used to fill today's gaps.
  Different runs stay separate; tied timestamps conservatively retain failures.
- Backfill projection: stable gap IDs and actual failure evidence; no dispatcher,
  network client or automatically consumed attempt. Interrupted calls require
  reconciliation. Two failed logical calls exhaust the default local plan.

## Failure Semantics

| Boundary | Result |
| --- | --- |
| Invalid context/secret-bearing params | Refuse before invocation |
| STARTED cannot be persisted | CALL_RECORDING_INCOMPLETE; invoke count 0 |
| Duplicate logical ID | CALL_ALREADY_STARTED; never invoke twice |
| Call fails | Safe terminal code; original provider text not stored |
| Terminal cannot be persisted | CALL_RECORDING_INCOMPLETE; invoke count 1 |
| Process stops after STARTED | Read-only INTERRUPTED projection; no recovery request |
| Partial file / abandoned reservation | Evidence retained; fail closed, operator investigation |
| Old/missing/future result day | STALE or DATA_BLOCKED; no old-value fallback |
| Catalog-only source | NOT_RUN / NOT_INSTRUMENTED |

The file root is operator-owned, private local state, never an HTTP-supplied path.
Limits are 1,000 logical call directories and 65,536 bytes per JSON record. Invalid
or orphan entries are not deleted to make room. A start reservation serializes
capacity checks; a process crash can intentionally leave it blocked. No automated
repair or historical rewrite is offered in this version.

Before/after start and terminal publication crashes are tested across new sink
instances. A retained partial blocks another publication rather than accumulating
more files. FIFO inputs are opened nonblocking and rejected before reading.
Invocation time cannot exceed the measured start, and reopened terminals must
complete after invocation; unsafe timestamp errors never echo raw input.
HTTP 401/403 is a permission block, not an outage eligible for a retry plan.

## Verification And Next Slices

Run the three `tests/test_data_*` suites registered in Python CI, plus existing
`test_fund_source_transport.py` and `test_official_settlement_offline.py`.
Sixteen DG behavior mutations are registered in the existing mutation gate. New
receipt/health suites block socket creation and DNS. Synthetic dates/tickers are
fixtures, not a replay of actual 10/30 provider responses.

Remaining: verified input cards/material index (B4), authenticated read-only API/UI
(B5), whole vertical acceptance/remote CI/isolated deployment/two-device receipts
(B6). Historical production runs have no new call receipts; do not fabricate them
or attach an unrelated current health report. Source rights and the PR stack must
be reconciled independently before any real deployment.

All outputs are WORKFLOW_DEBUG; human review stays PENDING. Production, U4, paper
and real-trading authorization are separate and unchanged.

## G0 Local Baseline

The isolated candidate branches from c72fe1e6b3292260930d35095a9c7a3a8dd3a146.
Local cached origin/main is 0ebde2fb0aa2ad04db1ab2d58b7d49bb3099b92a and is an
ancestor with 24 later workbench commits. This is a known stack, not evidence
that those PRs are merged. Remote main/CI was not refreshed for this offline task.
The B1-B3 data commit has no runtime dependency on the workbench changes; its
later integration target must be reconciled before pushing or deploying.

Read-only production baseline on 2026-11-01:

- Installed SHA: 333632910357baddcfbd9137ad5f01d666b9a912.
- Latest attempt: 20261030_203005_1793392205839825000_bd166ee2,
  INCOMPLETE / DATA_BLOCKED, target_trade_date null.
- Last publication: 20261029_203005_1793305805455839000_250527db, date 20261029.
- The existing runtime still listens on loopback 8773; no restart or state action.
- The observed 10/30 cause is one moneyflow date lag, not DNS or FRED. Only the
  analogous synthetic scenario was exercised; no market request proved recovery.
- Final Reed task/download/peer-query/reconnect evidence remains uncollected.

Local build-ready does not mean production repaired, full G0 remote clearance,
remote CI green, source rights verified, or two-machine acceptance passed.
