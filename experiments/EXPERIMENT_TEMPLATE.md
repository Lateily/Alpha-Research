# EXP_000_short_name

## Status

Proposed | Designing | Running | Reviewing | Accepted | Rejected | Observing

## Hypothesis

State the model belief being tested.

## Mechanism

Explain the causal chain. Why should this affect forward returns, risk,
confidence, wrongIf status, or position sizing?

## Affected component

- Data quality
- VP Score
- Leading indicators
- Signal confluence
- wrongIf
- Position sizing
- Backtest
- Paper trading
- Dashboard
- Other:

## Required data

List source, freshness, missingness, and reliability concerns.

## Implementation sketch

Describe the experimental code or analysis. Keep production files untouched
unless Junyan explicitly approves.

## Validation metrics

Examples:

- Forward return: 5D, 20D, 60D, 120D.
- Hit rate.
- Max drawdown.
- Sharpe or Sortino.
- IC or rank IC.
- False positive / false negative rate.
- Missing data rate.
- Signal redundancy.

## Success criteria

Define what result would make this worth considering for production.

## Failure criteria

Define what result would reject or weaken the idea.

## Known limitations

Include synthetic history, mock trades, sample size, missing data, and regime
dependence.

## Production readiness

Not ready / ready for Claude review / ready for Junyan approval / implemented.

