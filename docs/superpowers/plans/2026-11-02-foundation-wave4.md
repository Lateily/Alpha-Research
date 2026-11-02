# Foundation Wave 4 Implementation Plan

**Goal:** Move from provider-family inventory to endpoint observation hooks and
execute a bounded, local-only intake of existing public CNINFO originals, then
bind their query, retention and preservation artifacts.

**Authority:** Junyan's latest three-item request. Unified tests and independent
acceptance remain deferred. Actual local material intake and the necessary byte
reconciliation are now explicitly requested; they are not full acceptance.

**Base:** 9ab7366ff1091a598e236992b3fe57d035717691 in the existing isolated branch.

## Fixed Boundaries

- No production/shared-service/state changes, market/model APIs, network, upload,
  paid services, source permission expansion, ledger, push, merge or deployment.
- Existing public originals are read-only inputs. New data goes to a new private
  isolated library and separate control records, never Git or a source directory.
- Do not invent historical provider call receipts, industry assignments, exact
  publication times, approvals or prospective eligibility.
- New code remains IMPLEMENTED_UNTESTED; unified CI/build/mutation/review NOT_RUN.
- Only actual material intake/query/preservation local operations may run now.

## Packages And Interfaces

### A: Wire Source Readers

Own fund_source.py, tushare_rows.py, tushare_https.py, rotation_panel.py,
run_official_sample.py, data_governance/call_receipts.py,
config/data-source-catalog.v1.json and dedicated deferred tests/docs.

Preserve default behavior. Add explicit opt-in endpoint_session to real HTTPS and
row-reader entrances, forwarding a full RPC response to
`endpoint_session.observe(api_name, params, fields, invoke)` exactly once per
logical call. Reject mixing old v1 context/sink and new session. Do not expand
runtime allowlists or create automatic sessions from environment variables.
Keep v1 compatibility, expanding only known numeric fields needed for the
registered daily_basic/industry/market contracts. Complete the remaining three
first-five adapters as callable opt-in paths; do not claim live invocation.

### B: Endpoint Contracts, Observation And Gaps

Own config/data-endpoint-contracts.v1.json,
experiments/data_governance/endpoints.py, endpoint_calls.py,
tests/test_endpoint_contracts.py, test_endpoint_calls.py and dedicated docs.

API: `EndpointSession(root, *, collector_run_id, target_trade_date, clock=None)`;
`observe(api_name, params, fields, invoke)` returns the raw full RPC response after
recording one logical call. Keep source contracts closed with exact request scope,
required identity/date/numeric fields, units (UNVERIFIED when unknown), expected
freshness/absence policy, paging, consumers and rights. Cover actual first-five
and current central reader endpoints, not fictional endpoints from wildcard IDs.
Use existing immutable receipt patterns; token/request bodies/provider text never
persist. Missing/null/stale/permission/uninstrumented/interrupted states stay
distinct, with bounded backfill proposals only, no automatic provider replay.
New schema is explicit; never relabel old five-source receipts as broad coverage.

### C: Real Material Intake And Preservation (Coordinator)

Own scripts/llm/foundation_intake.py, CLI integration, dedicated deferred tests,
final CI command inventory, task and delivery docs. Read existing CNINFO manifests
and capture records, require independently supplied manifest hashes, check every
selected original against preexisting file hashes. Account for historical manifest
shape differences explicitly. Import only public originals and anchored extracts;
no scripts, tokens, databases or arbitrary directory crawl.

Use existing material/preservation APIs. Retain capture metadata, date-only
publication precision and historical anchors without pretending this is a new
prospective research run. Unknown industry must be UNSPECIFIED rather than a
guessed taxonomy. Keep original PDF versus extracted text identity explicit.
Store an immutable intake receipt, query evidence, retention pin and preservation
manifest outside the library, so the library's exact inventory stays valid.
Retain rejected/blocked originals with precise causes, no silent replacement.

## Deferred Same-Final-Version Acceptance

- Normal/missing/conflicting/historical endpoint inputs, no duplicate invocation,
  permission classification, interrupted calls, immutable history and page limits.
- Mixed v1/v2 observer refusal, exact date/entity selection and original retry bounds.
- Manifest-shape and external-anchor mismatches; original and extract lineage;
  date precision, unknown industry, failed PDF admission and preservation binding.
- Full integrated CI/mutations and independent review at one final SHA, then
  separately authorized rollout and real two-device acceptance.

No PASS is inherited from 99155bd. Operational intake evidence is not code
acceptance, current market collection, human research approval or off-machine backup.
