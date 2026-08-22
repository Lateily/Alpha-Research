# U4 Decision Ledger Specification v1

Status: `SPEC_READY / IMPLEMENTATION_UNWIRED`

This document freezes the second research-closure gate: every reviewed U2/U3
candidate must leave a durable U4 decision, including candidates that Junyan
rejects or cannot decide because evidence is missing. The schema is
`docs/research/contracts/u4_decision_ledger.v1.schema.json`.

This PR is specification only. It does not add a writer, replay engine, API,
CLI, migration, historical backfill, nightly step, or production file.

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

## Evidence Binding

Each event binds one candidate to the exact same-day chain:

`U2 bundle -> U2 candidate row -> U3 six-dimension battery -> U4 review packet`

The event also records `as_of`, `run_id`, industry cohort, and causal-cluster
identity. A future implementation must reject a cross-date, cross-run,
cross-packet, or differently hashed substitution.

## Append-Only Ledger Semantics

The future writer and verifier must implement all of these rules together:

1. Parse strict JSON: duplicate keys, non-finite values, malformed UTF-8, and
   unknown fields fail closed.
2. Append exactly one event at the next `sequence` and bind its
   `previous_event_hash` to the prior event's `record_hash`.
3. Compute `record_hash = sha256(canonical_json(event without record_hash))`.
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

The implementation PR must use deterministic canonical JSON and publish these
formulas without introducing a second interpretation:

```text
decision_id = "u4d_" + sha256(canonical_json({
  u4_packet_hash, ts_code, decision_revision, decision, decided_at
}))[0:32]

record_hash = "sha256:" + sha256(canonical_json(event_without_record_hash))
```

`ledger_id` is `u4-ledger:<as_of>:<first-12-hex-of-u4-packet-hash>`.

## Packet Closure Receipt

The event schema alone cannot prove set equality across a file. The separate
implementation PR must therefore emit a packet-closure receipt containing:

- exact `u4_packet_hash` and reviewed-candidate set hash;
- current decision-id set hash;
- counts by all five decisions;
- zero missing and zero extra candidate IDs;
- ledger tail sequence/hash;
- `claim_allowed=false`, `production_authority=false`, and
  `no_trade_flag=true`.

That receipt is required before a U4 queue is built. It does not exist in this
specification PR.

## Deliberate Non-Backfill

Historical U4 choices are not reconstructed from queues, PR comments, or later
portfolio state. Doing so would fabricate rejected alternatives and decision
timestamps. The ledger starts prospectively after its writer, verifier,
mutation tests, and Junyan deployment approval are delivered.

## Next Gate

A separate implementation PR may add an append-only writer, verifier, replay,
packet closure receipt, negative-path tests, and mutation cases. Production
wiring remains another separately approved step.

不是买卖指令；研究信号，human executes.
