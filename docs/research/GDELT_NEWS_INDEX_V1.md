# GDELT News Index V2 (Nonproduction)

This is a near-real-time **news index**, not a seconds-level newswire. Its
output is `WORKFLOW_DEBUG` context only. It cannot select U4, block a research
pipeline, approve paper, or instruct trades.

## Source And Rights Decision, 2026-09-30

- A bounded read-only probe of the existing Tushare `news` token returned
  `ACCESS_DENIED`. The `news` interface requires separate entitlement. The
  Tushare service agreement describes the ordinary license as personal,
  non-transferable, non-commercial, and for personal viewing. Do not expose
  that token or its content to a five-person workbench without written terms.
- GDELT says its released datasets can be used and redistributed with GDELT
  attribution. This module uses only GDELT's GAL RSS index: title, article URL,
  RSS date, and feed HTTP `Last-Modified`. It does not fetch or republish
  publisher bodies, verify original articles, or match company identities.
- The original DOC API host resolved but TLS timed out from the target Mac.
  `data.gdeltproject.org/gdeltv3/gal/feed.rss` was reachable with verified TLS;
  this is a different host and protocol, not a retry that hid the DOC failure.
- GDELT describes the GAL RSS as updating around every minute and covering a
  rolling 15-minute window. Actual source cadence/latency is not guaranteed:
  a 2026-09-30 probe observed a feed 11 minutes old. A later bounded read at
  16:34:13 UTC returned 6,883 items, two local semiconductor-title matches,
  and a valid hash-bound `OK` snapshot. Neither result proves a seconds-level
  Chinese newswire or full-market Chinese company coverage.

Source documentation: https://tushare.pro/document/2?doc_id=143,
https://tushare.pro/document/1?doc_id=405,
https://gdeltproject.org/about.html,
https://blog.gdeltproject.org/announcing-the-gdelt-article-list-rss-feed/,
https://blog.gdeltproject.org/new-gdelt-article-list-rss-feeds-images-links-social-media-and-mobile-urls/.

## Contract

The collector writes only under an operator-supplied nonproduction sandbox,
in its `gdelt-news/current.json` state. The snapshot carries a SHA-256 seal,
provider, attribution URL, query identity, last attempt, last good feed update,
committed cursor, bounded recent event list, source-health status, and explicit
false authority flags. The workbench reads and verifies that file; it never
calls GDELT or updates the cursor.

Polling fetches the fixed RSS URL and filters *titles locally* by a frozen
comma-separated term list. The committed cursor is the feed's HTTP
`Last-Modified`, not the RSS item's `pubDate`. GDELT says `pubDate` may be an
article's original publication date or its first-seen date; neither proves
when a particular article was indexed. Event `indexed_at` is the feed update
timestamp proxy, and `article_date_or_seen` preserves RSS `pubDate` separately.
No result should be described as an event that just happened.

The first observation cannot establish earlier completeness. If the committed
feed updates jump by over 15 minutes, `POSSIBLE_15M_FEED_GAP` remains visible.
Feed age over 10 minutes is `SOURCE_DELAYED` (metadata retained with warning);
age over 30 minutes or a future timestamp is `STALE_SOURCE` and does not
advance. Article URL is the stable duplicate identity. Changed title/date at
one URL is a conflict. DNS/HTTP failure, malformed XML, 250 or more matching
titles, and event-buffer saturation also leave the cursor in place. Missing
RSS item fields are counted as `PARTIAL_METADATA` rather than silently filled.
Committed event metadata older than two days is pruned on the next successful
feed update; the collector does not retain a full news archive.

Only the GDELT GAL RSS endpoint is allowed for the opt-in network call. Redirects
are refused, the response is capped at 8 MiB / 50,000 items, and the timeout is
10 seconds. XML DTD/entities are refused. A single poll still transfers roughly
1.7-1.8 MiB today; an unattended polling interval needs a separate bandwidth
and rate-limit decision.
The collector never opens article URLs. External titles are untrusted text;
the workbench renders them as escaped text and external links.

## Offline Acceptance

The sandbox directory must already exist. The response file must be frozen RSS
and its HTTP `Last-Modified` must be recorded separately; do not invent it from
local wall time.

```bash
AR_OFFLINE=1 python3 experiments/research_workflows/gdelt_news_index.py \
  --sandbox-root /private/tmp/ar-news-sandbox \
  --query-id semiconductor --query 'semiconductor,半导体,芯片' \
  --offline-response /private/tmp/gdelt-frozen-feed.rss \
  --offline-last-modified '2026-09-30T16:34:13+00:00'

python3 scripts/llm/nonprod_workbench.py \
  --state-root /private/tmp/ar-workbench-state \
  --news-index-snapshot /private/tmp/ar-news-sandbox/gdelt-news/current.json
```

The `--network` option additionally requires `AR_GDELT_NETWORK=1` and must not
be used with `AR_OFFLINE=1`; the CLI rejects an unapproved attempt before
creating state. No recurring job is registered here. A successful bounded
live canary exists only in `/private/tmp`, not in production or the team's
current workbench. Its data remain `E3_UNVERIFIED_NEWS_INDEX`.

## Remaining Gates

1. Independent PR review and Junyan merge approval.
2. Explicit approval for an unattended poll schedule and its rate/alert budget.
3. A separate licensed feed if a seconds-level, Chinese-language flash product
   is still required; GAL RSS does not meet that latency/coverage contract.
4. Separate production and team identity checks. Tushare short-flash content
   remains disabled until its own entitlement and written team-display rights
   are obtained.
