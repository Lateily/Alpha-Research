# A-035 Harness Evals - Phase 1

Status: implemented on a feature branch; not merged or production-wired.

## Scope

Phase 1 provides a deterministic evaluation contract for receipts produced by
future Authority, Context, P5, and DONE gates. It detects:

- false pass and false reject;
- a correct decision attributed to the wrong reason;
- an allow receipt backed by a stale head SHA;
- an allow receipt signed by the executor as reviewer; and
- a denial that happened only after a side effect.

The committed matrix is versioned and covers normal and negative cases across
all four domains. Matrix and receipt validation fail closed as `SPEC_BLOCKED`.
Unknown fields are rejected. Reports bind `matrix_version`, a canonical
`matrix_hash`, and a canonical `observations_hash`; evaluation findings are
machine-readable and use stable reason codes.

## Boundary

This slice evaluates deterministic receipts. It does not claim that the
Authority Resolver, Context Broker, P5 system, Runtime, model judge, or full
Harness is wired. In particular, open PRs #250 and #265 are not imported or
modified by this work. Each producer still needs a later adapter that emits the
receipt fields defined here.

`executor_id` and `reviewer_id` are control-plane principal IDs. Phase 1 accepts
only canonical lowercase `github:<username>` identities and rejects unknown
schemes. GitHub subject comparison is case-safe, so a casing alias cannot act as
an independent reviewer. Display names, model labels, and arbitrary aliases are
not proof of reviewer independence.

No model API, external network, live data, or production ledger is used. Cost
for the offline suite is CNY 0.

## Contracts

The matrix uses `ai-harness-eval-matrix.v1`. Every case contains:

- `case_id` and one of `AUTHORITY`, `CONTEXT`, `P5`, or `DONE`;
- an expected `ALLOW` or `DENY` decision and exact reason code;
- the current 40-character Git head SHA; and
- whether an independent reviewer is required.

An observation receipt contains:

- `case_id`, observed decision, and reason;
- `evidence_head`;
- `executor_id` and `reviewer_id`; and
- `side_effect_count`.

`DONE + ALLOW` always requires an independent reviewer. This is an evaluator
invariant, not a matrix option: changing the fixture flag cannot turn it off.

## Verification

Run:

```bash
python3 tests/test_ai_os_a035_harness_eval_offline.py
python3 tests/test_governance_mutation_gate.py
python3 -u scripts/governance_mutation_gate.py
```

The governance mutation gate must prove that removing each load-bearing A-035
guard makes its designated behavioral regression fail by assertion.

## Known gaps

- Producer adapters for Authority, Context, P5, Runtime, and Review are not in
  this slice.
- Phase 1 compares canonical GitHub principal IDs but does not prove that two
  different accounts, providers, or models are controlled by different
  underlying actors. Cross-account/provider/model identity resolution must come
  from the future Authority identity registry before production use.
- The matrix uses deterministic golden expectations; an LLM judge is neither
  required nor treated as final authority.
- Capability admission, production evaluation, and human calibration remain
  separate later work.
