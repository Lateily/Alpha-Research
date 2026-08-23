# U4 Decision Ledger Specification v1

Status: `DELIVERED_UNWIRED / OFFLINE_ONLY`

This document freezes the second research-closure gate: every reviewed U2/U3
candidate must leave a durable U4 decision, including candidates that Junyan
rejects or cannot decide because evidence is missing. The schema is
`docs/research/contracts/u4_decision_ledger.v1.schema.json`.

PR #295 froze this specification. PR #292 implements its offline writer,
verifier, replay, closure receipt, and CLI without adding a nightly step,
production default path, migration, or historical backfill.

## Decision Set

The decision enum is closed:

| Decision | Meaning | Downstream effect |
|---|---|---|
| `SELECT` | Junyan admits the candidate to U4 deep research | May appear in a later U4 queue; still no order authority |
| `REJECT` | The candidate should not enter this U4 research batch | Retained as a negative decision sample |
| `DEFER` | Decision postponed for priority, capacity, or non-terminal evidence reasons | Retained and may be superseded by a later revision |
| `NO_TRADE` | Research may be useful, but no paper setup should advance now | Complete research outcome; retained, not treated as failure |
| `DATA_BLOCKED` | Required evidence is absent, stale, invalid, or unverifiable | Must list at least one `missing_evidence` code |

No other string is valid. `SELECT` requires a non-empty research question and
an empty `missing_evidence` list. Every decision requires at least one
closed-world reason code and a free-text note.

## Authority Boundary

- `claimed_decision_owner` is exactly `Junyan`.
- v1 records `identity_verification=UNAVAILABLE`. A JSON name is not proof of
  identity; the original authorization text and its external evidence reference
  are preserved for human review.
- `u4_selection_authority=HUMAN_JUNYAN_ONLY`.
- `production_authority=false`, `trade_authority=false`,
  `claim_allowed=false`, and `no_trade_flag=true` are constants.
- `SELECT` authorizes deep research only. It cannot register, size, submit, or
  recommend an order.
- `human_decision.decided_at` is a claimed decision time. It is not the
  prospective anchor.
- `registered_at` is stamped from the outer R-015 event-ledger timestamp and
  must be no earlier than `human_decision.decided_at`. Downstream prospective
  scoring uses `registered_at`, never the claimed time by itself.

## Evidence Binding

Each event binds one candidate to the exact same-day chain:

`U2 bundle -> U2 candidate row -> U3 six-dimension battery -> U4 review packet`

The writer enforces the complete point-in-time order before any WAL append:
every frozen bundle artifact `generated_at` must be no later than the packet
`generated_at`; the human `decided_at` must be no earlier than the packet; and
the R-015 `registered_at` must be no earlier than the decision. Rebuilding a
packet with a caller-supplied timestamp that predates its evidence is refused.

`source.u3_battery_hash` binds the complete frozen U3 battery artifact, while
`source.u3_battery_row_hash` binds that candidate's row inside the artifact.
The typed R-015 append boundary must receive and revalidate the immutable
bundle for every intent, decision, and closure append; internal hashes alone
are not source evidence.

The event also records `as_of`, `run_id`, industry cohort, causal-cluster
identity, and `method_version`. Method version is mandatory so workflow-debug
observations and every later frozen method version can be counted separately.
The v1.1 review packet is required at the decision-ledger boundary; previously
emitted v1.0 packets remain valid for their original offline replay but do not
carry enough provenance to enter this ledger. The implementation rejects a
cross-date, cross-run, cross-packet, or differently hashed substitution.

The current six-artifact funnel DAG does not freeze the separately produced
Industry Cohort OS artifact. Therefore this offline implementation records
`cohort_id=UNAVAILABLE`; it must not copy the raw U2 `industry_key` into that
field. Such an event may support offline deep-research workflow debugging, but
it cannot enter a cohort-specific denominator or support a method claim. A
future packet version may replace the sentinel only after it binds the exact
point-in-time cohort artifact and canonical cohort identity.

At U4 admission time the prospective causal cluster may still be
`UNAVAILABLE`, because assigning it is one of the deep-research outputs after
selection. That explicit pending value does not prevent admission to offline
deep research. It does prevent the candidate from entering U5 registration,
independent-cluster denominators, or any claim until a reviewed prospective
cluster object exists. The ledger never invents a cluster id.

## Append-Only Ledger Semantics

The writer and verifier implement all of these rules together:

1. Parse strict JSON: duplicate keys, non-finite values, malformed UTF-8, and
   unknown fields fail closed.
2. Append exactly one event at the next `sequence` and bind its
   `previous_event_hash` to the prior event's `record_hash`.
3. Compute `record_hash = sha256(canonical_json(event without record_hash))`.
   Canonical JSON must reuse R-015's key-sorted UTF-8 serialization with
   `separators=(",", ":")`, non-finite values refused, and its existing float
   normalization. A second canonicalization is not permitted.
4. Require globally unique `decision_id` and a contiguous sequence.
5. Use `(u4_packet_hash, ts_code)` as the decision subject. Revision 1 has no
   predecessor. Revision N must be N-1 plus one and must name the exact prior
   `decision_id` in `supersedes_decision_id`.
6. Never update or delete an earlier event. A correction is a new revision;
   replay preserves both the original and current decision.
7. A packet can be marked review-complete only when the current-event subject
   set equals the reviewed candidate set. Missing candidates and extra
   candidates both fail closed.
8. Replay may send only current `SELECT` decisions to a later U4 queue. It must
   retain `REJECT`, `DEFER`, `NO_TRADE`, and `DATA_BLOCKED` in the decision
   dataset and in U4 decision-funnel denominator accounting. These decisions
   never enter a performance, win-rate, or alpha denominator by themselves.
9. A later queue must independently revalidate ready-pool eligibility and the
   U4 packet hash. The ledger is evidence of a human decision, not evidence
   that market or battery facts are still current.

## Identity And Hash Formulas

The implementation uses deterministic canonical JSON and publishes these
formulas without introducing a second interpretation:

```text
decision_id = "u4d_" + sha256(canonical_json({
  u4_packet_hash, ts_code, method_version, decision_revision, decision,
  decided_at, registered_at
}))[0:32]

record_hash = "sha256:" + sha256(canonical_json(event_without_record_hash))
```

`ledger_id` is `u4-ledger:<as_of>:<first-12-hex-of-u4-packet-hash>`.

## Packet Closure Receipt

The event schema alone cannot prove set equality across a file. The
implementation therefore emits a packet-closure receipt containing:

- exact `u4_packet_hash` and reviewed-candidate set hash;
- current decision-id set hash;
- counts by all five decisions;
- `selected_count` exactly in `{0, 3, 4, 5}`. Zero means `NO_TRADE` and no U4
  queue; three to five may project the existing packet-bound U4 review receipt;
- zero missing and zero extra candidate IDs;
- ledger tail sequence/hash;
- `claim_allowed=false`, `production_authority=false`, and
  `no_trade_flag=true`.

That receipt is required before a U4 queue is built.

## Deliberate Non-Backfill

Historical U4 choices are not reconstructed from queues, PR comments, or later
portfolio state. Doing so would fabricate rejected alternatives and decision
timestamps. The ledger starts prospectively after its writer, verifier,
mutation tests, and Junyan deployment approval are delivered.

## Next Gate

Production wiring remains a separately approved step. Before wiring, an
independent review must confirm the offline implementation, R-015 binding,
concurrency behavior, and mutation coverage on the exact merged commit.

不是买卖指令；研究信号，human executes.
