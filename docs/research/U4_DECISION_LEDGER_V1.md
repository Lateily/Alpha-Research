# U4 Decision Ledger v1 Implementation

Status: `DELIVERED_UNWIRED / OFFLINE_ONLY`

The normative contract is
`docs/research/U4_DECISION_LEDGER_SPEC_V1.md` and
`docs/research/contracts/u4_decision_ledger.v1.schema.json`. This document only
describes the implementation added by PR #292. It does not redefine #295.

## Durable Shape

The ledger no longer stores a whole review batch inside one opaque event.
Instead it uses R-015 as an append-only WAL:

1. each candidate becomes one outer `u4_decision` event whose payload is an
   exact `ar.u4_decision_event.v1` object;
2. `registered_at` is stamped from that outer R-015 event timestamp and cannot
   be supplied by the decision draft;
3. after every packet candidate has a current event, one outer
   `u4_decision_closure` event commits the packet revision;
4. only a committed closure may project the existing packet-bound U4 review
   receipt.

The closure contains the reviewed-candidate set hash, current-decision-id set
hash, counts for all five outcomes, selected count, missing/extra sets, and the
inner U4 decision-chain tail. A partial WAL with no closure is visible as a
pending packet and is resumed idempotently on exact retry.

## Complete Decision Denominator

Every candidate in the frozen review packet must appear. The closed decision
set is:

- `SELECT`
- `REJECT`
- `DEFER`
- `NO_TRADE`
- `DATA_BLOCKED`

An incomplete U3 battery must remain explicit `DATA_BLOCKED`. An active E1 red
flag must remain an explicit `REJECT`. Neither may be silently omitted or used
to fill the selected quota.

The selected count is exactly `0`, `3`, `4`, or `5`. Zero commits
`NO_TRADE_NO_QUEUE` and creates no queue receipt. Three to five may project the
existing offline U4 receipt. One, two, or more than five fail closed.

## Revision And Retry Semantics

One packet submission uses one coherent `decision_revision` across all packet
candidates. Revision 1 has no predecessor. Revision N must name the exact
current decision id for every subject. A correction appends a full new packet
revision; it never updates or deletes old events.

An exact retry reuses already-written candidate events and commits a missing
closure. A same-revision retry with different content is refused. The U4
transaction holds a dedicated packet lock while every individual append still
uses R-015's own exclusive lock, chain verification, anchor verification,
atomic replace, and fsync.

Readers take the shared R-015 lock while reading the event file and anchor so
they cannot observe the interval between ledger replacement and anchor commit.
Unrelated R-015 event kinds may coexist in the same shared chain; the U4 replay
filters its own two kinds after verifying the complete outer chain.

## Evidence Mapping Boundary

The frozen `ar.u4_review_packet.v1.0` does not expose a production `run_id`, a
display name, a cohort id, or a causal-cluster id. This implementation does not
pretend otherwise:

- `source.run_id` is a deterministic offline id,
  `u4-review-<packet-hash-prefix>`;
- `u2_candidate_row_hash` binds the exact frozen ready-pool projection visible
  to this reviewer;
- display name, cohort id, and causal-cluster id are explicit decision-draft
  fields, bound immutably after validation;
- industry code must equal the packet row's `industry_key`.

A later upstream contract may expose richer production provenance. That is a
separate schema revision, not grounds for filling v1 with invented values.

## Authority Boundary

The draft records `claimed_decision_owner=Junyan` and
`identity_verification=UNAVAILABLE`, plus verbatim authorization text and an
external evidence reference. This is preserved evidence, not authenticated
identity.

All candidate events and closure receipts fix:

- `u4_selection_authority=HUMAN_JUNYAN_ONLY`
- `production_authority=false`
- `trade_authority=false`
- `claim_allowed=false`
- `no_trade_flag=true`

`SELECT` means admission to offline deep research only. Rejections and defers
are opportunity-cost evidence, not performance samples. No outcome in this
ledger is a real-capital action.

## Offline CLI

```bash
python3 experiments/research_funnel/u4_decision_ledger.py \
  --packet /path/to/review_packet.json \
  --draft /path/to/u4_decisions.json \
  --ledger /path/to/offline_r015_events.jsonl \
  --receipt /path/to/projected_u4_receipt.json
```

There is no production default path. The implementation is not imported by
the nightly runner and has not been deployed to `~/ar-live`.

不是买卖指令；研究信号，human executes.
