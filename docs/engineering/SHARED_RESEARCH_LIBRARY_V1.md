# Shared Research Library V1

Continuation of the approved foundation blueprint. The user requested shared-page
integration after local acceptance of a27d407; implementation proceeds directly
under the earlier opt-out from repeated design approval. This is not permission
to merge, write production, broaden the member allowlist or distribute contents.

## Scope And Choices

Use the existing private shared workbench and a separate read-only research-library
view. Do not merge research dates into the market-material index: those dates have
different meanings. Do not add a second database or a generic filesystem browser.
Only an operator-supplied root and externally retained library hash are allowed.
Revalidate the entire library and stored result seals on every request, including
empty queries. A changed library requires an explicit new operator pin/restart.

The immutable library has rights UNVERIFIED/PRIVATE/sharing_allowed=false. This
release shares an index only: company, industry/taxonomy, research date, original
cutoff/publication/capture clocks, producer/importer identity, hashes, UNRESOLVED
assessments and PENDING human status. It never serves original files, excerpts,
questions, reports, citations text or arbitrary paths. Content sharing stays
denied even to the owner in this shared HTTP view. Metadata integration is not a
source-rights attestation. No task kind or write operation is added.

## Contracts

Default off. Paired --research-library-root/--research-library-hash flags require
private shared mode, an operator-owned valid existing library and disjoint state
and read-only production roots. They do not change the existing allowlist.

GET /api/shared-workspace/research-library accepts only single occurrences of
industry_key, industry_taxonomy, taxonomy_version, research_date, ts_code, page.
All nonempty filters are exact AND filters. Page size50, page0..999; invalid input
is400, invalid library evidence409, unauthorized access403. No configuration
returns NOT_CONFIGURED, not EMPTY or PASS. Missing/corrupt evidence never yields a
cached success. Responses carry requesting identity, consumer code SHA, library
pin, explicit content-sharing denial and false U4/paper/production authorities.

The shared page offers the separate Research Library view, filters and an inline
metadata detail. Display research date and source cutoff separately. React text
rendering only, no HTML injection or raw-content links. Requests are serialized;
late/out-of-order responses cannot leak another login/filter context. Refresh
failure makes retained data stale; switching context clears it. Manual refresh
and parent refresh trigger a fresh verification, not a write or research run.

## Release And Acceptance

Tests cover owner/member parity, unknown identities and cookies, default-off and
invalid flags, exact/empty/date filters, strict URL parsing, pagination, hash/seal
tampering and changes after a previous success, no raw-content paths or payloads,
actor/context mismatch and refresh disposal. New guard mutations require actual
behavioral assertion failures. Freeze one final SHA; run full offline CI, all
mutations, UI build/desktop-mobile browser QA and independent nonauthor review.
Pure code/synthetic tests only may go to a Draft PR for remote CI; no merge.

Only after all final-version gates pass, cold-backup the isolated shared state,
restore into a new state directory and independently compare records and artifact
bytes. Start candidate on a free loopback port, preserve old code/state/config,
then change only the existing Tailscale8443 target. Keep Junyan/Reed allowlist and
the production read-only source unchanged. No production code, launchd, official
ledger, paid/model/market API or formal research approval is touched. Two-human
device acceptance stays deferred until the foundation is complete; browser QA
by AI is not a human sign-off.
