# Foundation Source Hooks V1

Evidence grade: WORKFLOW_DEBUG. Implementation: IMPLEMENTED_UNTESTED.
Verification: NOT_RUN. Unified tests/build/mutations/browser/live calls: NOT_RUN.
human_review: PENDING. All authorities are false, including provider-call,
dispatch, production-write, research-approval and rights-expansion authority.
This document describes source support, not executed instrumentation.

## Explicit Interfaces

An operator may explicitly inject a duck-typed session created with worker B's
`EndpointSession(root, *, collector_run_id, target_trade_date, clock=None)`.
Its `observe(api_name, params, fields, invoke)` returns the full raw RPC response.
The target-aware convenience readers also use its public `target_trade_date`.
There is no environment-created observer, production-main activation, new
endpoint, extra provider request, or credential in observation parameters.

| Entry | Optional API and behavior |
| --- | --- |
| `fund_source._tushare_call` | `endpoint_session=None`; one observation around the existing transport invocation; rejects mixing v1 context/sink and session |
| `fund_source.tushare_daily` | `endpoint_session=None`, or v1 context/sink; target/entity selection, no future OHLC bars in observer mode |
| `fund_source.tushare_stock_fund` | Same observer choices; exact target/entity and finite amounts, never missing-to-zero in observer mode |
| `fund_source.get_stock_fund/get_many` | Forward explicit session; observer failure propagates without fallback or manual-required conversion |
| `fund_source.tushare_daily_basic` | `(token, params=None, fields="", *, observation_context=None, receipt_sink=None, endpoint_session=None)`; raw data, one existing call |
| `TushareHTTPS` | Constructor-only `endpoint_session=None`; query forwards its instance session; daily_basic uses the source helper |
| `tushare_rows.fetch_rows` | `endpoint_session=None`; one observation surrounds the complete existing retry sequence |
| `rotation_panel._api/recent_trade_dates/run` | Same explicit session on calendar and industry requests; exact session target and requested industry dates instead of silent prior-date substitution |
| `run_official_sample._market_main_flow` | `endpoint_session=None`; exact session target in observer mode, legacy latest-row behavior otherwise |

The old v1 `_tushare_call` hook now accepts exactly the catalog's first five
sources. Stock daily_basic requests entering that new v1 adapter must match their
context entity. Historical receipt validation is not tightened retroactively.
The catalog remains first-five only. `OPT_IN_LOGICAL_CALL` means a reachable
optional hook, never proof of live invocation or a production receipt.
The remaining source scripts named as consumers have not been migrated wholesale.

## Preserved Boundaries

Defaults retain the existing request parameters, field strings, return shapes,
legacy ordering and failure semantics. In particular, the HTTPS transport keeps
three transient attempts, its 12-second default timeout and 0.5/1.0 backoff.
The default row reader keeps its existing configured attempts, timeout, pause and
retries of provider/shape/transport failures. Observed mode retains transport and
shape retries, but returns the first nonzero full RPC to the session immediately.
It rethrows typed HTTP 401/403 and PermissionError without retry or generic-error
conversion, preserving the session's PERMISSION_DENIED classification. An observer
neither repeats that sequence nor creates a fallback request. Row conversion
remains inside the retry sequence so legacy conversion failures retain their
original retry/failure behavior.
The existing row/DataFrame offline guards and the new low-level session guard
refuse before provider/observer invocation. Direct low-level legacy and v1 calls
retain their historical offline policy; only the new session mode adds an
offline guard there. The existing `TushareHTTPS.READ_APIS` is unchanged.

Session/recording exceptions propagate as the bounded
`ENDPOINT_OBSERVATION_FAILED`, without raw provider/recorder messages, tokens or
chained public exception context. The session owns precise persisted error
classification. Provider/shape failures after a duck-typed observer returns also
use bounded error codes. No observer failure is swallowed as unavailable data,
retried through another source, or converted into a success receipt by adapters.

The v1 safe field set adds only `pe`, `pe_ttm`, `pb`, `total_mv` and sector `name`.
`pct_change` was already allowed. `name` is not treated as numeric; all numeric
finite/type guards and receipt/date-count checks remain. No receipt schema,
logical-call identity, immutable-write, replay or historical catalog-hash rule
changes. Current calls bind the current catalog hash; old receipts keep theirs.

Official `main`, `build`, settlement retries/budgets/deadlines, writes and
eligibility flags are unchanged. No unified session is auto-created for those
production paths. All source rights remain UNVERIFIED.

## Deferred Acceptance And Gaps

`tests/test_source_observation_hooks.py` is authored but NOT_RUN. It exercises
concrete low-level, transport, row, helper, DataFrame, rotation and market entries
using synthetic responses and socket refusal. Cases include one logical call,
mixed observers, retries/timeouts, start/finish recording failure, safe errors,
offline refusal, target/entity absence, legacy behavior, v1 numeric/date guards
and historical receipt readability. No test, import-based smoke or live source
call was executed while implementing this package.

Deferred integration must use the final worker-B session implementation and one
frozen integrated candidate, not infer behavior from static parsing. Its dataset
quality gaps are not necessarily exceptions: raw RPC success alone is not full
data quality or research readiness. Callers selecting narrow fields without
identity fields (including the unchanged full_battery daily_basic request) may
record missing-identity gaps; hooks do not invent provider identity cells.

The existing out-of-scope `tests/test_data_source_catalog.py` asserts daily_basic
is NOT_INSTRUMENTED. The coordinator must reconcile that stale expectation with
the now-reachable opt-in support before the deferred unified test run.
No CI/CLI/material/worker-B files were edited here. No doctor, compiler, tests,
build, mutation, browser, feature operation, provider/network request, Git
operation, production/shared state, ledger, secret, permission or service action
was run. Static AST/JSON inspection is not acceptance or deployment evidence.

## Frozen Handoff

Package A is frozen at source delivery, not accepted or deployed. Static AST/JSON
and scope/whitespace inspection only; 37 deferred test methods are authored, all
NOT_RUN. The worker-B constructor, observe signature and public target property
were inspected as source, not invoked. Integration, unified acceptance and human
review remain deferred/PENDING; all authorities remain false.
The bounded classification repair includes deferred one-attempt typed HTTP 401,
HTTP 403, PermissionError and nonzero RPC denial cases against the real session,
plus unchanged default retry/failure cases. These are authored, not executed.
