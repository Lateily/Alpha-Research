# Codex to Claude - R3 Decile/Quintile Read

Date: 2026-05-28

## Decision Read

The negative IC is real as a broad cross-sectional ranking effect, but it is not yet a long-only tradable edge.

20yr pure factor diagnostics show large bottom-vs-top and sector-neutral spreads, especially for reversal momentum, but bottom-tail long-only portfolios do not robustly beat EW liquid A-shares after a simple full round-trip cost assumption.

## Key Results

Source: `experiments/agent_tasks/r3_reversal_decile_study_20yr.md`

| Factor | Horizon | Tail | Bottom-EW Ann | Net Bottom-EW Ann | Sector-Neutral Bottom-Top Ann |
|---|---:|---:|---:|---:|---:|
| momentum_5d | 5d | decile | +9.88% | -5.54% | +56.81% |
| momentum_5d | 5d | quintile | +13.80% | -2.15% | +49.55% |
| momentum_20d | 10d | decile | +11.34% | +3.26% | +45.12% |
| volume_ratio | 5d | decile | +1.76% | -12.53% | +32.59% |

Bootstrap details:

- `momentum_5d`, 5d, decile net bottom-EW: -5.54%, CI [-11.78%, +0.73%], p=0.0965.
- `momentum_5d`, 10d, decile net bottom-EW: -7.30%, CI [-11.82%, -2.55%], p=0.003.
- `momentum_20d`, 10d, decile net bottom-EW: +3.26%, CI [-2.38%, +9.78%], p=0.277.
- Sector-neutral bottom-top spreads are strongly positive across tested factors/horizons, but this is research-only because broad A-share shorting is not available for the intended strategy.

## Interpretation

Causal logic is unestablished: the factor ranking effect could reflect reversal, crash rebound, liquidity/limit mechanics, sector rotation, or microstructure. The decile study establishes monotonicity, not cause.

Specific numbers are validated against the local diagnostic harness and current local panel. They are not production-calibrated thresholds.

## Implication

Option C remains the right direction:

- CORE gets capital priority.
- Swing remains R&D only.
- Iter-18 ablations should focus on translating the broad spread into long-only exposure, not on optimizing an 8-name picker.

