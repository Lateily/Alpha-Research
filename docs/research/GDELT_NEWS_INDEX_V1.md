# GDELT News Index V1 (Nonproduction)

This is a near-real-time **news index**, not a seconds-level newswire. Its
output is `WORKFLOW_DEBUG` context only. It cannot select U4, block a research
pipeline, approve paper, or instruct trades.

## Source And Rights Decision, 2026-09-30

- A bounded read-only probe of the existing Tushare `news` token returned
  `ACCESS_DENIED`. The `news` interface requires separate entitlement. The
  Tushare service agreement describes the ordinary license as personal,
  non-transferable, non-commercial, and for personal viewing. Do not expose
  that token or its content to a five-person workbench without written terms.
- GDELT says its released datasets can be used and redistributed for commercial
  or noncommercial purposes if GDELT is cited and linked. This module uses only
  the DOC 2.0 ArticleList index: title, URL, source metadata, and **GDELT index
  time**. It does not fetch or republish publisher article bodies, certify the
  original article, or claim company identity matching.
- GDELT's DOC API supports precise UTC windows, JSON ArticleList output, and
  up to 250 rows. It is a near-real-time global index, not a licensed Chinese
  flash wire. A returned 250 rows may be truncated and is therefore `PARTIAL`.
- One HTTPS connectivity probe from this Mac timed out. No successful live
  GDELT ingestion is claimed, and no scheduler or production route is enabled.

Source documentation: https://tushare.pro/document/2?doc_id=143,
https://tushare.pro/document/1?doc_id=405,
https://gdeltproject.org/about.html,
https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/.

## Contract

The collector writes only under an operator-supplied nonproduction sandbox,
in its `gdelt-news/current.json` state. The snapshot carries a SHA-256 seal,
provider, attribution URL, query identity, last attempt, last good window,
committed cursor, bounded recent event list, source-health status, and explicit
false authority flags. The workbench reads and verifies that file; it never
calls GDELT or updates the cursor.

Polling queries a bounded window. After the first 15-minute window, each new
window overlaps the previous one by five minutes. Article URL is the stable
duplicate identity. A conflicting update of the same URL is visible as
`BAD_PROVIDER_PAYLOAD`, without moving the cursor. DNS/HTTP failure, malformed
data, 250 returned rows, and event-buffer saturation also leave the cursor in
place. A later retry uses the same window. The existing last-good entries are
kept but always shown separately from the latest attempt.

Only the GDELT DOC endpoint is allowed for the opt-in network call. Redirects
are refused, the response is capped at 2 MiB, and the timeout is 10 seconds.
The collector never opens article URLs. External titles are untrusted text;
the workbench renders them as escaped text and external links.

## Offline Acceptance

The sandbox directory must already exist. The response file must be a frozen
synthetic `{"articles": [...]}` DOC ArticleList shape.

```bash
AR_OFFLINE=1 python3 experiments/research_workflows/gdelt_news_index.py \
  --sandbox-root /private/tmp/ar-news-sandbox \
  --query-id semiconductor --query semiconductor \
  --offline-response /private/tmp/gdelt-synthetic-response.json

python3 scripts/llm/nonprod_workbench.py \
  --state-root /private/tmp/ar-workbench-state \
  --news-index-snapshot /private/tmp/ar-news-sandbox/gdelt-news/current.json
```

The `--network` option additionally requires `AR_GDELT_NETWORK=1` and must not
be used with `AR_OFFLINE=1`; the CLI rejects an unapproved attempt before
creating state. No recurring job is registered here. Before a
real source run, an operator must confirm the GDELT metadata choice, network
reachability, rate/terms, and nonproduction destination. Live results require
their own source canary; fixture tests do not prove live connectivity.

## Remaining Gates

1. Independent PR review and Junyan merge approval.
2. A successful bounded GDELT live probe on the intended host, including
   observed response shape and timestamp semantics.
3. Explicit approval for an unattended poll schedule and its rate/alert budget.
4. Separate production and team identity checks. Tushare short-flash content
   remains disabled until its own entitlement and written team-display rights
   are obtained.
