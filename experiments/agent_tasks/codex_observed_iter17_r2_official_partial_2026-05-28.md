# Codex Observation - iter-17 R2 Official Backtest Partial

Date: 2026-05-28

## Observed Outputs

- `public/data/iter17_r2_backtest_mini1yr.json`
- `public/data/iter17_r2_backtest_10yr.json`
- `/tmp/iter17_r2_mini1yr.log`
- `/tmp/iter17_r2_10yr.log`
- `/tmp/iter17_r2_20yr.log`

The 20yr log had reached `Running backtest...` but no `public/data/iter17_r2_backtest_20yr.json` output was present at observation time.

## Mini1yr

- CAGR: +2.14%
- Sharpe: 0.454
- Max drawdown: -3.5%
- Avg gross: 19.2%
- Max positions reached: 8
- Total trades: 772
- Raw alpha: -35.81%, CI [-55.54%, -5.03%], p=0.0240
- Same-gross alpha: -31.38%, CI [-51.10%, -3.63%], p=0.0308

## 10yr

- CAGR: -2.86%
- Sharpe: -0.765
- Max drawdown: -25.3%
- Avg gross: 4.5%
- Median positions: 0
- Max positions reached: 8
- Total trades: 1726
- Raw alpha: +7.57%, CI [-8.67%, +26.40%], p=0.3816
- Same-gross alpha: -1.29%, CI [-19.53%, +21.81%], p=0.9032

## Interpretation

Causal logic is questionable: the mini1yr book makes a small absolute return, but materially underperforms the same-gross benchmark. The 10yr result has almost no average exposure and no statistically meaningful same-gross alpha.

Specific numbers are validated against the official iter-17 R2 JSON/log outputs observed locally. They are not production-calibrated thresholds.

## Decision Implication

Current official R2 does not clear the v2 research gate. The mini1yr result fails same-gross alpha decisively, and the 10yr result is not evidence of a tradable edge because exposure is too low and alpha straddles zero.

