# U4 Complete-Decision Ledger v1

## Purpose

The U4 ledger records the complete review outcome for one frozen
`ar.u4_review_packet.v1.0`. It closes the survivorship gap created when only
selected names continue into deep research and rejected or deferred names
disappear.

The ledger is offline and append-only. It does not select securities, verify a
human identity, create an order, grant portfolio authority, or count a method
sample.

The authority contract is
`docs/research/U4_DECISION_LEDGER_SPEC_V1.md`. This implementation records a
packet-level sealed batch so U4 can close the full reviewed candidate set in
one append-only event; it does not replace the spec's authority, decision
enum, no-trade boundary, or future packet-closure receipt requirements.

## Decision Set

Every row in the packet `ready_pool` appears exactly once in the sealed batch.

| Packet state | Decision source | Allowed outcome |
|---|---|---|
| `ready=false` | Frozen U2/U3 machine gate | Deterministic `REJECT` only |
| `ready=true` | Junyan-authored draft | `SELECT`, `REJECT`, or `DEFER` |

Machine-gate rejection reasons are copied exactly from `blocked_reasons` and
cannot be omitted, changed, or overridden. A human decision records a stable
reason code, verbatim reason text, and a research question for every `SELECT`.

The selected count must be either:

- zero: batch outcome is `NO_TRADE`, and no U4 review receipt is produced; or
- three to five: batch outcome is `SELECTED_FOR_OFFLINE_RESEARCH`, and the
  selected rows deterministically project the existing packet-bound
  `ar.u4_review_receipt.v1.0`.

One or two selections are invalid. This keeps the ledger aligned with the
existing U4 review contract instead of creating a parallel selection rule.

## Integrity Model

One packet hash may have one decision batch.

- The event kind is `u4_decision`.
- The event id is the packet hash.
- The event payload contains the full packet and full sealed batch.
- The batch carries `method_version` so workflow-debug observations and later
  frozen methods cannot be mixed in attribution.
- The batch carries `registration_source=R015_EVENT_LEDGER_TS`; the durable
  registration time is the outer event-ledger timestamp, not caller text.
- An exact retry is idempotent.
- A different batch for the same packet is a refused rewrite.
- The event-ledger timestamp is the registration boundary and cannot predate
  the self-reported `reviewed_at` value.
- The dedicated verifier rejects foreign event kinds, malformed payloads,
  duplicate packet ids, chain damage, and anchor damage.

The implementation reuses the R-015 event ledger for flock locking, canonical
serialization, hash chaining, atomic replace, and local anchor checks. Readers
take a shared lock on that same lock file while verifying the chain, anchor,
and event rows as one snapshot; they cannot classify the short interval between
ledger replacement and anchor commit as corruption. The CLI requires an
explicit `--ledger` path and has no production default.

## Honest Boundaries

`claimed_reviewer=Junyan` is recorded with
`identity_verification=UNAVAILABLE`. The local JSON document does not prove who
typed it. A future authenticated Human Gate may strengthen that evidence, but
v1 must not claim it already exists.

`reviewed_at` is also human-supplied. It must fall between the packet timestamp
and the event-ledger registration timestamp, but the durable event timestamp is
the evidence of when the platform first recorded the decision. Downstream
prospective scoring must use that registration boundary rather than treating
the self-reported review time as proof.

The append-only chain and anchor raise the cost of local history rewriting;
they are not an absolute tamper-proof system. A third durable publication
layer remains necessary for stronger historical guarantees.

Rejected and deferred rows are opportunity-cost evidence. They are not paper
orders, closed cycles, or eligible method samples. In particular:

- `method_sample_eligible=false`
- `claim_allowed=false`
- `production_authority=false`
- `no_trade_flag=true`

The first 5-10 semiconductor cycles remain workflow-debug observations. No win
rate, alpha, profitability, or method-validity claim is permitted before 30
genuinely independent, de-clustered closed samples.

## Offline CLI

```bash
python3 experiments/research_funnel/u4_decision_ledger.py \
  --packet /path/to/review_packet.json \
  --draft /path/to/junyan_decision_draft.json \
  --ledger /path/to/offline_u4_decisions.jsonl \
  --receipt /path/to/projected_review_receipt.json
```

`--receipt` is optional. A `NO_TRADE` batch never writes a receipt. A failed
validation exits nonzero and does not append an event.

Not trading advice; research signal, human executes.
