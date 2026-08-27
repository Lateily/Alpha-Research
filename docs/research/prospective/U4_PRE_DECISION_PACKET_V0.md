# U4 Pre-Decision Packet v0

Status: `DRAFT_OFFLINE / PRODUCTION_UNWIRED`

This document defines the packet Reed prepares before Junyan makes a U4
decision. It is a bridge from same-day U1-U3 evidence to human review. It does
not choose stocks, create a paper order, or grant production authority.

Schema:
`docs/research/contracts/u4_pre_decision_packet.v0.schema.json`.

## Purpose

The packet answers one operational question:

```text
Which same-day candidates are reviewable by Junyan, and exactly why are the
others blocked before U4?
```

It is not a recommendation list. It is an evidence table with gates attached.
`SELECT`, `REJECT`, `DEFER`, `NO_TRADE`, and `DATA_BLOCKED` still belong to the
U4 decision ledger after Junyan acts.

## Required Inputs

Every packet must bind these inputs:

| Input | Why it is required |
|---|---|
| Same-day U1-U3 bundle hash | Prevents later ticket swapping |
| U2 candidate-pool hash | Shows the pool Junyan is reviewing |
| U3 battery hash and candidate row hash | Proves each row has the same-day battery context |
| Three-stage receipt hash | Proves candidate, battery, and finalize receipts were rechecked against their actual bytes and DAG binds |
| `u4_pre_decision.py` diagnostic report | Confirms evidence rows were cross-checked against the immutable bundle, feature health, and funnel health |
| Source publication status | Prevents pending daily data from being treated as published |
| Packet `generated_at` and self-hash | Makes same-day rebuilds distinguishable and tamper-evident |
| `method_version` | Keeps workflow-debug samples separate from future production methods |
| `cohort_id` and `causal_cluster_id` | Lets later sample counts de-cluster correctly |

If a required source is absent, stale, or unverifiable, the packet status must be
`DATA_BLOCKED`, `SOURCE_PUBLICATION_PENDING`, or `BLOCKED_BEFORE_U4`. Missing
data cannot be filled with zero or guessed.

`cohort_id=UNAVAILABLE` or `causal_cluster_id=UNAVAILABLE` remains visible as a
row warning. In line with the merged U4 decision-ledger contract, it does not by
itself prevent offline U4 research, but it blocks U5 promotion and contribution
to de-clustered method claims until the identity is assigned and verified.

## Candidate Row

Each candidate row must include:

- `ts_code` and `display_name`
- `candidate_status` (main, reserved, or random control)
- `method_version`
- `cohort_id` and `cohort_identity_state`
- `causal_cluster_id` and `causal_cluster_identity_state`
- `u2_candidate_row_hash`
- `u3_battery_row_hash`
- `positive_channels`
- `red_flag_channels`
- `blocked_reasons`
- `missing_evidence`
- `quality_status`
- `allowed_for_u4_packet`
- `question_for_junyan`

`allowed_for_u4_packet=true` means only that the row may be shown to Junyan for
review. It is not permission to select, register, simulate, or trade.

In v0, `cohort_id` must be `UNAVAILABLE` with
`cohort_identity_state=UNAVAILABLE_UNBOUND`, because this packet does not bind a
frozen Industry Cohort OS artifact. A causal cluster is either copied from the
hash-bound upstream candidate with `VERIFIED_UPSTREAM`, or remains
`UNAVAILABLE` with `UNAVAILABLE_PENDING`. The packet cannot invent either
identity.

## Hard Stops

The packet must stop before U4 when any of these are true:

- daily source is `PENDING`, `STALE`, or `DATA_BLOCKED`;
- quarterly source is `PENDING`, `STALE`, or `DATA_BLOCKED`;
- U3 six-dimension battery is incomplete without explicit `DATA_BLOCKED`;
- an active E1 red flag is present;
- no independent positive channel exists;
- the row is a random-control observation rather than a research candidate;
- `method_version` is missing or invalid;
- quality gate output is missing or unverifiable;
- diagnostic evidence hash or receipt self-report cross-check fails;
- any authority field claims production, trade, paper-order, or model selection
  power.

E1 red flags remain one-vote vetoes. Positive evidence can explain why a name
is interesting, but it cannot cover a red flag.

The packet-level source gate is stronger than row-level readiness. Rows may
remain visible as otherwise reviewable while the packet itself is
`DATA_BLOCKED`; Junyan must not make a U4 decision until the missing same-day
source is published and the packet is rebuilt.

JSON Schema validation is necessary but not sufficient. Before review, the
offline packet validator must reopen the immutable U2/U3 evidence, require
exact candidate-set equality, recompute row hashes, packet status, summary
counts, diagnostic counts, the same-day digest, the diagnostic digest, and the
packet self-hash. Packet-supplied rows or caller-supplied evidence are not an
authority source. A consumer must reject a packet that has only passed
structural Schema validation.

## Selection Boundary

The only legal selected counts after Junyan review are:

```text
0, 3, 4, 5
```

Zero means `NO_TRADE_NO_QUEUE`. Three to five means Junyan may create the next
U4 decision-ledger step. Machines cannot lower the floor to one or two names
just to make the run look productive.

## Authority Boundary

This packet is permanently offline until a separate production wiring approval
exists:

- `human_selection_authority=HUMAN_JUNYAN_ONLY`
- `machine_selection_authority=NONE`
- `production_authority=false`
- `trade_authority=false`
- `paper_order_authority=false`
- `claim_allowed=false`
- `no_trade_flag=true`

This document is not a buy, sell, hold, or paper-order instruction. It is a
research-preparation contract. Human executes.

## Current Use

For the first semiconductor prospective cycles, Reed uses this packet as an
operator checklist after source preflight and before asking Junyan for U4
decisions:

```text
U1/U2/U3 same-day rerun
-> source/preflight diagnostic
-> U4 pre-decision packet
-> Junyan U4 decision ledger
-> factpack / thesis / valuation / SMC
-> prospective paper cycle
```

The first 5-10 semiconductor cycles are workflow-debug samples only. They do
not count as method win-rate evidence. At least 30 independent, de-clustered
closed-loop samples are required before method evaluation.

不是买卖指令；研究信号，human executes.
