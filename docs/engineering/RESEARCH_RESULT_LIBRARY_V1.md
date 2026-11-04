# Research Result Library V1

Continuation of the approved foundation blueprint and the accepted d330f3e
material-to-task slice. This slice is local operator CLI/API work, not an upgrade
of either running workbench. Two-human-device acceptance remains deferred.

## Contract

Reuse foundation_materials, not another database. Admit only an externally pinned
material-pack and the matching, externally pinned COMPLETED_HISTORICAL_EARNINGS
result. Verify the admitted source library, exact case inventory, renderer output
hashes, citations, pending review and false authorities before creating a staging
package. Copy selected original PDF bytes and all input/output artifacts into the
result library; deduplicate identical bytes, not independent research samples.
The captured input inventory is checked against the external pack pin again:
an earlier path verification is not proof of the bytes subsequently copied.
Both admission and stored-query use the same captured-byte binding check.

An intake is explicit. No automatic job hook, shared dispatcher kind, provider,
network transport, approval, schedule, paper or production write is introduced.
The original source library, pack and completed case are never edited. Existing
8443 and the prior8792 preview remain unchanged. Source rights stay private and
UNVERIFIED; publisher authenticity remains unattested.

The result record binds input pack hash, source library hash, output artifact
inventory, full result hash (report bytes reconstructed from stored artifacts),
recorded producer/consumer identities, observed importer identity/time and
authorship. Original source IDs are preserved in the provenance record; selected
PDF copies receive explicit content-addressed local IDs. No prior approval or
prior thesis registration is invented. All responses remain UNRESOLVED and
human_review=PENDING. Import success is storage success only.

## Publication And Query

Staging roots are exclusive and retained on interruption. No historical file or
global limit is deleted/increased. The existing library publishes registration
metadata last. First intake requires a new destination; append requires an
independently retained destination library hash, checked again under its writer
lock. Concurrent stale appenders refuse rather than overwrite another intake.
An exact same material/version/result retry returns ALREADY_IMPORTED without
writing. A conflicting retry fails. Content deduplication is not sample counting;
the task event store remains the source for individual execution attempts.
Selected PDFs use original rows; result-record rows and auxiliary blob rows are
published in the same registration. Auxiliary rows keep the unchanged16-file
material limit. Full input/output packages, including receipt and SHA256SUMS,
can be reopened without the former source-pack or case directories. Existing
library JSON/text/credential/content bounds still govern admission; an otherwise
valid earnings case can be refused by that stricter storage profile. Staging is
retained as evidence, never labeled an imported result on such a refusal.

Query requires an external library hash and verifies the entire registered byte
inventory before filtering. Industry, taxonomy/version, research date and ticker
are exact AND filters. Research date means the frozen new-question as_of date,
not source publication day, market trading day or ingestion day. Rows expose
those other clocks separately. Empty matches are EMPTY, not a quality PASS.
Query verifies stored record/result/receipt bindings without rerunning research
or writing temporary projections. Legacy generic review rows are not silently
promoted into this result namespace.

## Interfaces

`foundation_results.ingest_result(source_library_root, pack_root, artifact_root,
result_library_root, staging_root, request)` creates local storage only.
`query_results(result_library_root, *, expected_library_hash, industry_key=None,
industry_taxonomy=None, taxonomy_version=None, research_date=None, ts_code=None)`
is read only. foundation_cli supplies research-result-ingest and research-results.
Paths come from explicit operator configuration, never HTTP or artifact content.
The current UI does not consume this new query contract in this slice.

The source result is a recorded assertion, not remote execution attestation.
Importer code identity is separate; historical d330f3e results may be admitted
without relabeling their producer as the new importer. Only the existing bounded
earnings/material-pack v1 format is supported; other workflows require adapters.

## Acceptance

Normal, empty, combined-filter, historical-version, wrong pin, tampered output,
authority escalation, taxonomy conflict, duplicate/retry, stale append, link and
every write-interruption counterexamples must exercise the actual public entry.
New mutation targets must fail by behavioral assertions, not test errors.
Freeze one final candidate, obtain independent review, then run full offline CI
and all mutations on that SHA. Demonstrate a real admitted original -> task ->
library -> industry/date query without changing either running service or ar-live.
Remote CI, integration and service upgrades remain separate authorized steps.
