# R2 Path B Diagnostic Report - 2026-05-28

## Scope

This is an experimental diagnostic for `SWING_STRATEGY_v2` Path B, not a production engine change. The harness lives at `experiments/swing_path_b_backtest.py` and writes only to `experiments/agent_tasks/`.

Strategy tested:

- Weekly inverse 5d momentum selection.
- Volume no-spike filter.
- Long-only A-share basket.
- Gross cap 50%.
- 8 positions baseline, plus one breadth variant with 30 positions.
- Hard stop -8%.
- Time stop 5d or 10d.
- Same-gross equal-weight liquid universe benchmark.

## Main Result

Path B should not be promoted as currently specified. The negative IC found in R1 is real at the rank-diagnostic level, but it does not survive this simple post-cost portfolio loop. Same-gross benchmark comparison is negative in every tested configuration.

| Window | Config | CAGR | Sharpe | Max DD | Avg Gross | Trades/yr | Same-gross Alpha | 95% CI |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| mini1yr | top300, 8 pos, hold 5d | -0.03% | 0.08 | -17.29% | 48.8% | 807 | -21.52% | [-36.98%, -2.39%] |
| mini1yr | top300, 8 pos, hold 10d | +2.44% | 0.23 | -15.95% | 48.2% | 435 | -19.76% | [-33.51%, -2.27%] |
| mini1yr | top500, 30 pos, hold 5d | +6.00% | 0.48 | -10.23% | 48.8% | 3026 | -16.55% | [-28.39%, -3.90%] |
| 10yr | top300, 8 pos, hold 5d | -16.89% | -0.72 | -86.74% | 47.2% | 784 | -11.18% | [-19.49%, -1.71%] |
| 10yr | top300, 8 pos, hold 10d | -18.69% | -0.86 | -88.31% | 46.6% | 423 | -12.80% | [-19.94%, -5.54%] |
| 10yr | top500, 30 pos, hold 5d | -14.23% | -0.86 | -80.59% | 47.7% | 2964 | -9.53% | [-13.97%, -4.96%] |
| 20yr | top300, 8 pos, hold 5d | -8.35% | -0.08 | -92.66% | 46.0% | 766 | -4.40% | [-11.49%, +3.57%] |
| 20yr | top300, 8 pos, hold 10d | -11.78% | -0.18 | -95.20% | 45.6% | 418 | -7.87% | [-14.85%, -0.17%] |
| 20yr | top500, 30 pos, hold 5d | -7.36% | -0.25 | -91.10% | 46.0% | 2874 | -7.63% | [-11.80%, -3.05%] |

## Trade Diagnostics

| Window | Config | Round Trips | Avg Trade Return | Win Rate | Hard Stops |
|---|---:|---:|---:|---:|---:|
| mini1yr | top300, 8 pos, hold 5d | 382 | +0.13% | 46.1% | 44 |
| mini1yr | top300, 8 pos, hold 10d | 204 | +0.40% | 42.6% | 55 |
| mini1yr | top500, 30 pos, hold 5d | 1432 | +0.38% | 44.7% | 148 |
| 10yr | top300, 8 pos, hold 5d | 3915 | -0.59% | 42.4% | 494 |
| 10yr | top300, 8 pos, hold 10d | 2111 | -1.36% | 39.2% | 664 |
| 10yr | top500, 30 pos, hold 5d | 14804 | -0.47% | 43.2% | 1782 |
| 20yr | top300, 8 pos, hold 5d | 7520 | -0.19% | 46.3% | 1072 |
| 20yr | top300, 8 pos, hold 10d | 4104 | -0.73% | 41.7% | 1254 |
| 20yr | top500, 30 pos, hold 5d | 28204 | -0.16% | 46.6% | 3805 |

## Interpretation

Causal logic is questionable: R1 shows a statistically reliable inverse rank relationship, but that only proves the current factor surface has negative rank IC. It does not prove that an 8-name or 30-name long-only weekly reversal basket can monetize it after fills, stops, concentration, and turnover.

Specific numbers are validated against this local diagnostic harness and the current local panel. They are not production-calibrated thresholds and should be treated as a reject/smoke-test result, not as final research.

## Recommendation

Do not run Path B as the next production candidate. If continuing reversal research, shift from "pick extreme losers" to a broader, lower-turnover factor portfolio experiment:

- decile or quintile portfolio returns before any stock-picking engine;
- market/sector-neutral long-short paper study if shorting is only for research diagnostics;
- breadth first, then execution constraints;
- explicit turnover and cost budget gate before optimizing scores.

