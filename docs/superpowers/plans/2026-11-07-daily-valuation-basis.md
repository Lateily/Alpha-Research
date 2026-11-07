# Daily Input And Valuation Basis Implementation

Spec: docs/engineering/DAILY_VALUATION_BASIS_V1.md
Base: 608b6ce75a51164c86f1b0b3f510bf059374d17c
Execution: inline, one independent whole-branch review at the end.

## Task 1: Strict Daily Adapter

Write failing tests for exact float64 reconstruction and malformed provenance,
dates, OHLC and factors. Implement a bounded retained-observation adapter using
the existing daily parser and raw ATR/confirmed-pivot primitives. Keep raw input
and conversion traces. No global parser or producer changes.

## Task 2: Financial Basis

Write failing tests for signed nonrecurring reconciliation, period/unit binding
and incomplete cash/debt coverage. Add typed fact references and honest missing
normalization/multiple inputs. Integrate opt-in request/cards v2, preserving v1
and existing output derivation seals. Add behavioral mutation pins and CI.

## Task 3: Real Isolated Example And Final Verification

Use only retained Nov5 daily context and admitted Oct4-cutoff financial PDFs.
Prepare a NEW bounded pack with the full nonrecurring bridge and balance/cash
notes. Annual PDF object-limit refusal stays a gap; do not bypass guards.
Demonstrate exact-tail adaptation and financial bridge on real stored bytes.
Freeze final SHA; run all CI/mutations and fresh independent review. Any review
fix requires regression RED/GREEN and same-final rerun. Keep evidence local.

Dependencies: Task 2 consumes Task 1's immutable adapter receipt; Task 3 consumes
the v2 request/card contract and newly pinned pack. Source ownership and dates
are explicit at each boundary. Production/shared services are forbidden scope.
