# Foundation Endpoint Contracts V1

State: IMPLEMENTED_UNTESTED. Evidence grade WORKFLOW_DEBUG. Verification NOT_RUN.
Human review PENDING. Provider-call, dispatch, production-write, rights-expansion
and research-approval authorities are all false. No live instrumentation has run.
Unified tests, build, mutation checks and independent acceptance remain DEFERRED.

## Closed Coverage

`config/data-endpoint-contracts.v1.json` is `ar.endpoint-contracts.v1`, separate
from the existing five-source v1 contracts/receipts and 36-family inventory.
It contains these 16 finite, actually referenced reader endpoints only:

| Endpoints | Scope And Freshness |
| --- | --- |
| daily, daily_basic, moneyflow_dc | Stock or explicit market/date window; selected market date |
| moneyflow_ind_dc | Industry identifiers, never stock identifiers; selected market date |
| moneyflow_mkt_dc, moneyflow_hsgt | Market aggregate, no stock parameter; selected market date |
| index_daily | The three domestic index identifiers in run_official_sample; selected market date |
| trade_cal | Exchange/calendar window; future calendar dates are legitimate |
| forecast, express, income, fina_indicator | Stock, announcement date/window plus separate report period |
| anns_d | Stock announcement window; absence is not research clearance |
| index_global | XIN9, IXIC, TWII from overnight_anchor; global calendar/as-of unverified |
| limit_list_d | Stock or explicit market/date window; empty settled-day input remains blocked |
| stock_basic | Current listing directory consumed by momentum_prefilter; historical point-in-time unverified |

Each entry declares allowed parameters, request selection rules, required identity,
date and numeric fields, unit status, source-code provenance, absence/freshness,
local page caps, consumers and unverified rights. These are bounded consumer
contracts, not exhaustive provider schemas or expanded runtime API allowlists.
Unknown units are UNVERIFIED. Existing code's explicit conversion assumptions
are SOURCE_CODE_DECLARED_NOT_REVERIFIED, not independently verified units.
Provider row/page limits are UNVERIFIED; 6000 limit, 100000 offset-plus-limit and
10000 response-row caps are local safety bounds, not provider guarantees.

All other provider families/endpoints remain NOT_INSTRUMENTED. SDK callers that
do not opt into the central reader hooks also remain unobserved. Catalog presence
alone proves neither observation, current access permission nor complete data.

## Fixed Source-Hook Interface

```python
EndpointSession(root, *, collector_run_id, target_trade_date, clock=None)
session.observe(api_name, params, fields, invoke)
```

The callback takes no arguments and supplies the **full raw RPC response**:
`{"code": 0, "data": {"fields": [...], "items": [...]}}`. On a successful RPC
`observe` returns that same response object, not only `data`, rows or a DataFrame.
Missing/null/stale/entity-mismatched data is recorded as degraded dataset quality
but returned unchanged; it is never filled with zero. Invalid response structure,
non-finite JSON, transport failure and nonzero provider codes raise a fixed
`EndpointObservationError` after recording. Provider messages never enter errors
or receipts. The conservative local permission-code mapping is not reverified
provider documentation; unmatched codes remain PROVIDER_ERROR.

Unknown endpoints, unsafe params/fields, wrong domains, future non-calendar
requests and invalid paging fail before callback invocation. Empty/default field
requests are allowed. Existing callers that omit identity/announcement fields
will surface MISSING_FIELDS rather than receive invented scope confirmation.
Unexpected response fields are counted as SCHEMA_DRIFT; only catalog-known field
names are persisted. Numeric strings are not coerced into numeric readings.

There is exactly one callback invocation and no retry in this facility. The
source-hook owner must retain separately authorized transport retry bounds;
transport attempts inside the callback remain NOT_INSTRUMENTED. This package
does not change readers, CLI, CI, network permissions or production services.

## Immutable Receipt Layout

```text
root/
  catalogs/<catalog-sha256>.json
  calls/<logical-call-sha256>/start.json
  calls/<logical-call-sha256>/terminal.json
```

STARTED is durably published before invoke. Logical identity hashes collector
run, target date, endpoint, validated scalar params and normalized/sorted fields.
It deliberately excludes the catalog hash: changing the contract cannot enable
replay of the same call. A new run is a distinct observation, never an implicit
retry authorization. Existing completed, failed, interrupted or partial call
directories refuse replay. No cached raw response is available for replay.

Publication reuses the existing v1 durable `_directory`, `_fsync`, `_write_new`
helpers: exclusive reservation, bounded canonical JSON, fsync and hard-link
publication, no overwrites, private new files and symlink refusal. Existing v1
files/schemas are not edited or relabeled. Missing terminal projects INTERRUPTED;
abandoned reservation/partial publication requires human reconciliation. A
callback interrupt records a fixed terminal when possible and propagates a
message-free interrupt. Recording failure never triggers another invocation.
The store is bounded to 1000 calls/catalog snapshots, 64 KiB per call record,
256 KiB per catalog and 4 MiB finite in-memory response hashing.

Receipts keep only safe params, known field names, hashes, counts, dates, gap
codes, time and fixed errors. No token, request body, provider message, raw row,
result cell, announcement title, URL or exception text is persisted. A complete
catalog snapshot is a static contract, not a provider result. Hashes bind the
start and catalog; they are not signatures and do not replace trusted storage.

## Reading And Gaps

Public read/validation APIs in `endpoints.py`:

- `load_catalog(path)`, `validate_catalog(value)`, `catalog_hash(catalog)`.
- `validate_request(catalog, api_name, params, fields, target_trade_date)`.
- `project_endpoint_health(catalog, receipts, *, target_trade_date)`.
- `propose_backfills(health, *, max_proposals=32, max_attempts=2, catalog=None)`.

Public receipt APIs in `endpoint_calls.py`:

- `read_endpoint_receipts(root)` validates each receipt against its own snapshot.
- `validate_receipt(row, *, catalog=None)` validates a read projection again.
- `EndpointSession` and `EndpointObservationError` as described above.

Request status (SUCCEEDED/FAILED/INTERRUPTED), dataset quality and research
readiness are independent. Research readiness is always NOT_RUN. All projections
retain WORKFLOW_DEBUG, NOT_RUN, human_review PENDING and false authorities.
Successful single pages never imply whole-market coverage. Counts stay scoped
to exact params/fields/run; old catalog hashes and other targets are counted
separately, not relabeled as current evidence. An unobserved endpoint is
NOT_INSTRUMENTED, not a zero-row success.

`target_date_rows` applies to an explicitly selected trade_date (even if that
date precedes the session target) or the current market target. Historical
bounded windows, announcement windows, calendars, global indices and listing
directories use null, not zero. Financial freshness uses ann_date, never
end_date/report period as a stand-in for a market trade_date. Calendar future
dates are not market future-data errors. Global trading calendars, publication
time precision, report completeness and statutory filing freshness require
separate research evaluation.

Reopen/health validation constrains date counts using observed first/last dates
and `_request_date_bounds`. A single row on the selected target cannot claim
zero target rows; extrema excluding it cannot claim any. Counts and flags for
target absence, staleness, future dates and out-of-request dates must agree with
all conclusions justified by the extrema, without inventing interior dates.

Backfill proposals merge identical endpoint/params/fields/target gaps across
observed runs and count logical attempts. They are capped at 32 proposals and
two attempt observations, with omitted-gap counts. Permission, interruption,
schema/evidence and uninstrumented gaps block dispatch. Even an otherwise
eligible proposal is human-review-only; dispatch and same-call replay are false.
No endpoint permission expansion, scheduler, provider replay or repair is run.

## Deferred Acceptance And Gaps

Authored, NOT_RUN: actual callback/full-response identity, STARTED-before-invoke,
no replay, missing/empty/null/stale/negative/entity/date/permission cases, finite
JSON, page caps/boundaries, safe secrets/errors, calendar and financial date
semantics, interrupts/terminal-write failure, symlinks/reservation refusal,
history snapshots and tampering. Required known-lesson cases include actual
historical selected-date entry and reopened, reserialized metadata contradicting
target/future/outside extrema and gap flags.

Still DEFERRED: execution of all these tests; unified same-final-version
integration/build/mutation checks; independent human review; filesystem
crash/concurrency acceptance; provider schema/unit/permission re-verification;
live call observation; wider endpoint/family instrumentation; research readiness,
rollout and two-device acceptance. Static AST/JSON inspection is not acceptance.
The package is frozen for coordinator handoff; no commits or pushes are made.
