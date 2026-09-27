# Jev U4 Shadow Authority v1

**Status:** `SHADOW_ONLY / OFFLINE / WORKFLOW_DEBUG`.

This document records the authority boundary of the current Jev U4 shadow
engine. It does not amend the formal U4 decision ledger or approve a live
provider, production run, paper workflow, or trade. The approved design is
`docs/superpowers/specs/2026-09-20-jev-u4-shadow-design.md`; formal U4 rules
remain in `docs/research/U4_DECISION_LEDGER_SPEC_V1.md`.

## What the shadow run may do

- Reopen and validate an existing frozen U4 packet and its authoritative
  evidence, then apply deterministic gates before any typed judgment.
- Preserve U3 incompleteness as `FORCED_DATA_BLOCKED`; when an E1 red flag is
  also present, keep both blocker reasons. An E1 flag without U3
  incompleteness gives `FORCED_REJECT`. Other non-reviewable rows are
  `POLICY_STOPPED` with no invented human outcome.
- On approved synthetic evidence, read an exact offline cassette for an
  eligible state. A policy preview without a cassette reports
  `MODEL_UNAVAILABLE` for eligible rows; it does not manufacture probabilities.
- Emit a canonical `ar.jev_u4_shadow_receipt.v1` under the operator's
  nonproduction sandbox state root. The receipt binds request, packet, row,
  policy, question set, and provider result. Its `sample_purpose` is
  `WORKFLOW_DEBUG`.

The registered capability is `SHADOW_ONLY`, with network policy `deny`, zero
provider cost, and no live model contact. The current CLI does not require or
read a TypeSafe key. `TYPESAFE_JEV` is disabled as
`LIVE_PROVIDER_NOT_INSTALLED`; any future provider requires a separate human
approval and task.

## What it cannot authorize

The receipt fixes `production_authority`, `trade_authority`,
`paper_order_authority`, and `formal_selection_authority` to `false`. Typed
`shadow_disposition` labels and top probabilities are **counterfactual shadow
observations**, not formal `SELECT`, `REJECT`, `DEFER`, `NO_TRADE`, or
`DATA_BLOCKED` ledger events. `OBSERVED_NOT_AUTHORIZED` does not become
approval at any probability or score. A forced shadow label is likewise not a
human decision.

This subsystem cannot append the formal U4 ledger, form a formal 0-or-3-to-5
queue, register paper orders, place trades, or write production state. Formal
U4 selection remains `HUMAN_JUNYAN_ONLY`; machine selection authority is
`NONE`. Even a formal U4 `SELECT` means admission to offline deep research,
not a capital action. A shadow receipt cannot substitute for Junyan's
separately recorded human decision or its evidence checks.

Keep shadow receipts in a local sandbox, never under `~/ar-live` or a formal
ledger path. Do not feed them into the nightly production chain, paper
executor, or automatic experiment. Automatic experiments remain deferred until
2026-09-28; reaching that date does not grant authority to start one. No
production or automatic experiments follow from this document; each requires
separate explicit human approval.

## Offline comparison and claims

`evaluate` can compare a verified shadow receipt with a committed formal U4
decision transaction **copied into the same nonproduction sandbox**. It verifies
the copied ledger chain and anchor from retained bytes, requires the frozen
intent and closure, and writes a separate immutable evaluation beside the
shadow receipt. Never supply a production ledger or production state root.

The shadow receipt and formal decision ledger currently bind different packet
types: `u4_pre_decision` and closure review, respectively. Their packet hashes
must not be equated or normalized away. The bridge retains both original hashes
and checks the shared run, bundle, U2/U3 batch, and exact candidate evidence
hashes. It compares only the shadow subset while demanding a complete human
decision set for the formal review packet.

A discrepancy is evidence for review, not an error to erase or authority to
change a human decision. Fewer than 30 independent causal clusters are labeled
`INSUFFICIENT_INDEPENDENT_SAMPLE`; even at 30+, this descriptive comparison
does not establish method effectiveness, win rate, alpha, or profitability.
No such claim is made by the receipt or evaluation.

不是买卖指令；研究信号，human executes.
