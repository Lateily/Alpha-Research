# U4 Decision Ledger v1 Implementation

Status: `DELIVERED_UNWIRED / OFFLINE_ONLY`

The normative contract is
`docs/research/U4_DECISION_LEDGER_SPEC_V1.md` and
`docs/research/contracts/u4_decision_ledger.v1.schema.json`. This document only
describes the implementation added by PR #292. It does not redefine #295.

## Durable Shape

The ledger no longer stores a whole review batch inside one opaque event.
Instead it uses R-015 as a three-stage append-only WAL:

1. one outer `u4_decision_intent` freezes the complete review packet and the
   complete normalized decision draft before any candidate event is written;
2. each candidate becomes one outer `u4_decision` event whose payload is an
   exact `ar.u4_decision_event.v1` object;
3. `registered_at` is stamped under the R-015 lock from that outer event's
   timestamp and cannot
   be supplied by the decision draft;
4. after every frozen packet candidate has its exact intended event, one outer
   `u4_decision_closure` event commits the packet revision;
5. only a committed closure may project the existing packet-bound U4 review
   receipt to a deterministic packet-specific sidecar beside the explicit
   offline ledger.

The intent carries the complete parsed packet object, exact packet candidate set and hash,
ready-pool hash, method version, revision, and all candidate intents. The
closure references that intent id/hash and contains the reviewed-candidate set
hash, current-decision-id set hash, counts for all five outcomes, selected
count, missing/extra sets, and the inner U4 decision-chain tail. A
self-consistent subset can therefore never close a larger packet. A partial WAL
with no closure is visible as a pending packet and is resumed only when the
entire submitted intent matches byte for byte.

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
closure. A same-revision retry with different content, including a change to a
candidate not yet written when the process stopped, is refused. An exact retry
also finds its already committed historical closure even after unrelated
packets have advanced the shared R-015 tail. The U4
transaction holds a dedicated packet lock while every individual append still
uses R-015's own exclusive lock, chain verification, anchor verification,
atomic replace, and fsync.

Readers take the shared R-015 lock while reading the event file and anchor so
they cannot observe the interval between ledger replacement and anchor commit.
Unrelated R-015 event kinds may coexist in the same shared chain; the U4 replay
filters its own three kinds after verifying the complete outer chain.

The projected review receipt is not an authority source. Its path is derived
from the explicit ledger path and full packet digest; callers cannot redirect
it. Every exact retry reconciles it from the committed closure. This repairs a
crash after closure commit but before projection write, and removes an older
selected receipt when a later committed revision selects zero candidates.

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
  --ledger /path/to/offline_r015_events.jsonl
```

The optional projection is written beside the ledger as
`<ledger>.u4-<full-packet-sha256>.receipt.json`. There is no production default
path. The implementation is not imported by the nightly runner and has not
been deployed to `~/ar-live`.

不是买卖指令；研究信号，human executes.
