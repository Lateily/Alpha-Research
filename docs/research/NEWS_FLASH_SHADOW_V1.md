# News Flash Shadow V1

This is an offline evidence replay, not a live news service. It cannot select
U4 candidates, register paper plans, block Macro/Funnel, or issue trade actions.

## Source Status, 2026-09-30

- Tushare `news` is the short-flash interface (a separate entitlement, at most
  1500 rows per request). One five-minute, read-only probe with the existing
  local token returned `ACCESS_DENIED`. No content was printed or stored.
- Tushare `major_news` is long-form news (at most 400 rows per request). The
  existing GitHub-driven collector and old web consumer are not a substitute
  for a real-time feed or an audited production source.
- The public Tushare service agreement describes a personal, non-transferable
  license. The current account's team redistribution rights have not been
  verified. This module therefore has no provider call or team projection.

Official interface and terms: https://tushare.pro/document/2?doc_id=143,
https://tushare.pro/document/2?doc_id=195,
https://tushare.pro/document/1?doc_id=290,
https://tushare.pro/document/1?doc_id=405.

## Replay Contract

Input is an `ar.news-flash-cassette.v1` JSON file marked `WORKFLOW_DEBUG`.
The code accepts only a 15-minute window, explicit source status, and rows
within the frozen window. Provider timestamps are interpreted in Asia/Shanghai;
the output uses UTC. A denied or down source has no rows and cannot be
represented as an empty successful source. A 1500-row response is `PARTIAL`
because the provider may have truncated it. Collection more than five minutes
late is also `PARTIAL`. Identical duplicates collapse; changed content under
the same event identity is refused.

The output remains `UNVERIFIED_CASSETTE` with `licensed_team_display=false`.
Each item is `E2_UNVERIFIED`, has no automatic entity mapping, and carries a
null original URL: the documented `news` fields do not include one. Hashes
bind bytes, not source truth. External text is untrusted and must never be
inserted as prompt instructions.

Capture requires `AR_OFFLINE=1` and an existing sandbox root. The output must
be a new direct child directory of that root. `source.json`, `news_flash.json`,
and `manifest.json` are written once; the manifest is last, so an incomplete
directory cannot verify. Verification re-normalizes the source, checks the
file set and exact canonical bytes, and returns a receipt.

```bash
AR_OFFLINE=1 python3 experiments/research_workflows/news_flash_shadow.py capture \
  --input /path/to/synthetic-cassette.json \
  --sandbox-root /path/to/existing-sandbox \
  --output-dir /path/to/existing-sandbox/batch-001
AR_OFFLINE=1 python3 experiments/research_workflows/news_flash_shadow.py verify \
  --output-dir /path/to/existing-sandbox/batch-001
```

## Separate Release Gates

1. Obtain explicit provider entitlement and written terms for team display.
   Do not share the current personal token or raw content through the workbench.
2. Add a bounded live adapter in a separate PR. Its receipt must distinguish
   access denied, DNS/TLS failure, empty-valid, possible truncation, and late
   arrival. Use overlapping bounded windows, immutable batches, a durable
   cursor, and replay tests for crash/retry and duplicate delivery.
3. Add an independent read-only workbench projection only after licensing and
   citation policy are settled. Display latest attempt, last good batch, source
   publication time, collection lag, gaps, and human review state separately.
4. Validate shadow runs before any scheduler or nightly connection. News stays
   E2 context; an official filing may be promoted to E1 only through a separate
   original-source verification path. U4 and paper retain human gates.
