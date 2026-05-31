# Swing Reversal Decile/Quintile Study

Window: `2006-01-04` to `2026-05-25`
Universe: PIT liquid top `500`
Round-trip cost assumption: `0.3000%`

## Summary

| Factor | H | Q | Bottom ann | Bottom-EW ann | Bottom-Top ann | Net Bottom-EW ann | Sector-neutral spread ann | N |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| momentum_5d | 5 | 0.1 | +7.03% | +9.88% | +53.42% | -5.54% | +56.81% | 988 |
| momentum_5d | 5 | 0.2 | +10.85% | +13.80% | +47.79% | -2.15% | +49.55% | 988 |
| momentum_5d | 10 | 0.1 | -1.96% | -0.01% | +25.96% | -7.30% | +33.74% | 494 |
| momentum_5d | 10 | 0.2 | +1.88% | +3.91% | +22.77% | -3.66% | +27.20% | 494 |
| momentum_20d | 5 | 0.1 | +12.38% | +15.38% | +62.54% | -0.79% | +56.11% | 986 |
| momentum_20d | 5 | 0.2 | +9.67% | +12.60% | +39.98% | -3.19% | +43.98% | 986 |
| momentum_20d | 10 | 0.1 | +9.16% | +11.34% | +48.74% | +3.26% | +45.12% | 493 |
| momentum_20d | 10 | 0.2 | +6.85% | +8.99% | +31.26% | +1.07% | +35.10% | 493 |
| volume_ratio | 5 | 0.1 | -0.88% | +1.76% | +31.43% | -12.53% | +32.59% | 988 |
| volume_ratio | 5 | 0.2 | +2.60% | +5.33% | +26.54% | -9.45% | +27.35% | 988 |
| volume_ratio | 10 | 0.1 | -6.28% | -4.41% | +10.75% | -11.39% | +15.74% | 494 |
| volume_ratio | 10 | 0.2 | -3.17% | -1.24% | +8.33% | -8.45% | +11.94% | 494 |

## Validation Labels

Causal logic is unestablished: this tests broad factor portfolio monotonicity and tradability hints, not an economic mechanism.

Specific numbers are validated against this local diagnostic run and current local panel; they are not calibrated production weights.
