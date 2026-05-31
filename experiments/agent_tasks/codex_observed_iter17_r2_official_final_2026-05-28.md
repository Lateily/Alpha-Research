# Codex Observation - iter-17 R2 Official Backtest Final

Date: 2026-05-28

## Outputs Observed

- `public/data/iter17_r2_backtest_mini1yr.json`
- `public/data/iter17_r2_backtest_10yr.json`
- `public/data/iter17_r2_backtest_20yr.json`
- `/tmp/iter17_r2_mini1yr.log`
- `/tmp/iter17_r2_10yr.log`
- `/tmp/iter17_r2_20yr.log`

## Official R2 Results

| Window | CAGR | Sharpe | Max DD | Avg Gross | Median Pos | Trades | Same-gross Alpha | 95% CI | p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| mini1yr | +2.14% | 0.454 | -3.51% | 19.2% | 8 | 772 | -31.38% | [-51.10%, -3.63%] | 0.0308 |
| 10yr | -2.86% | -0.765 | -25.33% | 4.5% | 0 | 1726 | -1.29% | [-19.53%, +21.81%] | 0.9032 |
| 20yr | -0.22% | 0.024 | -26.10% | 4.7% | 0 | 4172 | +16.05% | [-4.83%, +41.99%] | 0.1422 |

## Gate Read

R2 does not clear the v2 research gate.

- Mini1yr fails decisively versus same-gross benchmark.
- 10yr has negative CAGR, negative Sharpe, and no statistically meaningful same-gross alpha.
- 20yr same-gross point estimate is positive, but the CI crosses zero and the strategy is mostly cash (`avg_gross` 4.7%, median positions 0).
- Max position enforcement passed in all observed windows (`max_positions_reached` 8).
- CSI300/ZZ500/ZZ1000 remain unavailable in the current panel, so official benchmark remains liquid top-500 EW plus same-gross variant.

## Validation Labels

Causal logic is questionable because a low-exposure strategy with median zero positions cannot support a tradable-edge claim without stable same-gross alpha and enough active observations.

Specific numbers are validated against the official local iter-17 R2 JSON outputs observed on 2026-05-28. They are not production-calibrated thresholds.

