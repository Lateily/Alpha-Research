# Model Paper Fund Dry-Run Rehearsal - 2026-08-30

Status: `DRAFT_REHEARSAL / PAPER_ONLY / OFFLINE_FIXTURE_ONLY`

This rehearsal proves that the team can walk through the intended paper-fund
handoff shape before live market data arrives. It uses a fake security and does
not write `experiments/execution_tracker/model_fund/*`.

Not trading advice; research signal, human executes.

## Dry-Run Scope

The rehearsal covers this path:

```text
U4 SELECT
  -> sealed case
  -> paper registration plan
  -> pending paper order
```

The rehearsal does not cover:

- live market data;
- source repair apply;
- U1-U3 rerun;
- real U4 choice;
- official paper ledger write;
- real trade action.

## Fixture

The machine-readable fixture is:

```text
docs/research/fixtures/model_paper_fund_dry_run_v0.json
```

It intentionally uses `FAKE001.PAPER` and `OFFLINE_FIXTURE_ONLY`. No real ticker
or real company is used.

## Pass Criteria

The dry-run is considered structurally ready only if all of the following are
true:

1. The stages appear in this exact order:
   `U4_SELECT`, `SEALED_CASE`, `PAPER_REGISTRATION_PLAN`, `PENDING_ORDER`.
2. `paper_only=true`, `no_trade_flag=true`, `trade_authority=false`, and
   `production_authority=false`.
3. The U4 decision is attributed to Junyan.
4. The selected case has thesis, valuation, wrong-if, and manual SMC fields.
5. The plan contains a 64-character `plan_hash`.
6. The pending order is marked as `PENDING_DRY_RUN`.
7. The fixture says `ledger_write_mode=OFFLINE_FIXTURE_ONLY`.
8. The fixture does not contain a real ticker-like A-share, HK, or US symbol.

## Interpretation

Passing this dry-run only means the handoff shape is understandable. It does not
authorize a new paper order. The real path still requires #322 for the U4
pre-decision packet and #319 for the governed U4-to-paper registration bridge,
or an explicit reviewed offline artifact approved by Junyan.
