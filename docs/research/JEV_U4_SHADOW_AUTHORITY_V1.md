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

## Comparison and claims: NOT YET IMPLEMENTED

Task 6 comparison/evaluation is not present in the current CLI. `evaluate`
returns `SPEC_BLOCKED / EVALUATION_NOT_INSTALLED` before reading the supplied
ledger. There is no verified shadow-to-human comparison, evaluation artifact,
agreement result, or completed Task 6 claim to report.

The approved *future* comparison design requires a verified formal ledger,
matching packet and candidate evidence hashes, and a separate immutable
evaluation artifact. A discrepancy is evidence for review, not an error to
erase or authority to change a human decision. Fewer than 30 independent
causal clusters cannot support a method-effectiveness, win-rate, alpha, or
profitability claim. No such claim is made by the present receipts, regardless
of sample size.

不是买卖指令；研究信号，human executes.
