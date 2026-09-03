# Model Paper Fund Frontend Display Audit - 2026-08-30

Status: `PRELAUNCH_AUDIT / PAPER_ONLY / READ_ONLY`

This audit checks whether the public model-portfolio data can be safely used as
the frontend source for the Model Paper Fund go-live view.

Not trading advice; research signal, human executes.

## Checked Files

| File | Result | Use For Model Paper Fund |
|---|---|---|
| `public/data/model_portfolio.json` | `LEGACY_RECOMMENDATION_LANGUAGE_PRESENT` | `NO` |
| `public/data/v2/model_portfolio_state.json` | `PAPER_ONLY_STATE_SOURCE` | `YES` |

## Finding

`public/data/model_portfolio.json` still contains legacy wording and fields that
can look like recommendation output:

- `model_action: LONG`;
- `model_action: SHORT`;
- `model_action: WATCH_SHORT`;
- `Internal model-recommendation pilot`;
- `recommendation -> user execution -> performance attribution`.

This file also includes `no_trade_flag`, but that does not fully neutralize the
old display language. A user can still read `LONG/SHORT/WATCH_SHORT` as a
directional recommendation.

## Current Safe Source

`public/data/v2/model_portfolio_state.json` is the safer display source for the
paper fund because it exposes account state instead of model actions:

- `paper_only: true`;
- official NAV and position state;
- `no_trade_flag: true` on positions/trades;
- generated-at metadata;
- `DATA_BLOCKED` semantics available through the state contract.

`direction: long` may still appear inside order records as execution metadata.
That is different from `model_action: LONG`. The frontend must render it as
paper-ledger metadata, not as an instruction.

## Display Rule

For the Model Paper Fund page:

1. Read `public/data/v2/model_portfolio_state.json` as the primary source.
2. Do not use `public/data/model_portfolio.json` for the paper-fund go-live
   display.
3. Never surface `model_action`, `LONG`, `SHORT`, or `WATCH_SHORT` as current
   portfolio guidance.
4. Show `paper_only`, `no_trade_flag`, `generated_at`, and `DATA_BLOCKED` states
   visibly.
5. If the v2 state source is missing, stale, or malformed, show `DATA_BLOCKED`
   instead of falling back to the legacy model portfolio file.

## Owner Action

Reed owns the product/readiness finding. Better owns frontend rendering changes
if the UI still reads the legacy file. Junyan owns the final decision on whether
the page is allowed to be used in the go-live flow.
