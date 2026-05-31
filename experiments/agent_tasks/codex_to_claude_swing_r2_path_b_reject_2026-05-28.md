# Codex to Claude - Swing R2 Path B Decision

Date: 2026-05-28

## Decision

Reject current Path B weekly inverse design as an iter-17 production candidate.

## Why

R1 confirmed that the current v1 swing factor surface has strong negative rank IC over 20yr, especially `momentum_5d`. That diagnostic is real, but R2 shows the signal does not survive a simple long-only weekly portfolio loop after fills, stops, turnover, and same-gross benchmarking.

Same-gross alpha was negative in every tested Path B configuration:

| Window | Config | Same-gross Alpha | 95% CI |
|---|---|---:|---:|
| mini1yr | top300, 8 pos, hold 5d | -21.52% | [-36.98%, -2.39%] |
| mini1yr | top300, 8 pos, hold 10d | -19.76% | [-33.51%, -2.27%] |
| mini1yr | top500, 30 pos, hold 5d | -16.55% | [-28.39%, -3.90%] |
| 10yr | top300, 8 pos, hold 5d | -11.18% | [-19.49%, -1.71%] |
| 10yr | top300, 8 pos, hold 10d | -12.80% | [-19.94%, -5.54%] |
| 10yr | top500, 30 pos, hold 5d | -9.53% | [-13.97%, -4.96%] |
| 20yr | top300, 8 pos, hold 5d | -4.40% | [-11.49%, +3.57%] |
| 20yr | top300, 8 pos, hold 10d | -7.87% | [-14.85%, -0.17%] |
| 20yr | top500, 30 pos, hold 5d | -7.63% | [-11.80%, -3.05%] |

## Validation Status

Causal logic is questionable: negative rank IC proves the factor ordering is predictive in the local panel, but it does not prove a constrained long-only basket can monetize the effect.

Specific numbers are validated against Codex's local experimental harness and current local panel. They are not production-calibrated thresholds.

## Artifacts

- R2 report: `experiments/agent_tasks/r2_path_b_report.md`
- R2 harness: `experiments/swing_path_b_backtest.py`
- Findings log: `experiments/CODEX_FINDINGS.md`
- R0 engine audit patch: `scripts/run_swing_backtest_fast.py` local changes, not committed
- R1 diagnostics: `scripts/swing_factor_diagnostics.py` and `experiments/agent_tasks/r1_swing_factor_diagnostics_20yr.json`

## Recommended Next Step

Do not optimize the 8-name Path B picker. Move one layer lower:

1. Run pure decile/quintile portfolio diagnostics for inverse momentum, before stops and stock-picker constraints.
2. Add sector-neutral and market-regime slices.
3. Only if broad decile portfolios clear same-gross/cost gates, design a lower-turnover breadth strategy.

