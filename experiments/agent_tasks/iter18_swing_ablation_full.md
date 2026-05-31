# iter-18 Swing Ablation Results

Experimental only. Outputs are under `experiments/agent_tasks/`.

| Variant | Window | CAGR | Sharpe | Max DD | Avg Gross | Median Pos | Trades | Same-gross Alpha | 95% CI | p |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| b1_4factor | mini1yr | +3.26% | 0.5611 | -3.85% | +15.90% | 8 | 768 | -20.61% | [-52.22%, +37.31%] | 0.3882 |
| b1_4factor | 10yr | -2.96% | -0.6693 | -25.73% | +4.15% | 0 | 1804 | -3.28% | [-19.46%, +16.60%] | 0.7223 |
| b1_4factor | 20yr | -0.35% | 0.01532 | -28.88% | +4.97% | 0 | 4478 | +19.73% | [-2.63%, +47.31%] | 0.0877 |
| b2_gross80 | mini1yr | +2.14% | 0.4545 | -3.51% | +19.25% | 8 | 772 | -31.38% | [-51.10%, -3.62%] | 0.0308 |
| b2_gross80 | 10yr | -2.87% | -0.7689 | -25.33% | +4.46% | 0 | 1726 | -1.40% | [-19.61%, +21.73%] | 0.8934 |
| b2_gross80 | 20yr | -0.22% | 0.02513 | -26.03% | +4.71% | 0 | 4172 | +16.25% | [-4.67%, +42.23%] | 0.1376 |
| b3_no_atr_veto | mini1yr | -2.75% | -0.5988 | -3.72% | +15.30% | 8 | 774 | -45.81% | [-66.12%, -14.01%] | 0.0113 |
| b3_no_atr_veto | 10yr | -2.86% | -0.8415 | -25.09% | +4.15% | 0 | 1764 | -5.10% | [-21.90%, +15.46%] | 0.6068 |
| b3_no_atr_veto | 20yr | -0.15% | 0.03139 | -25.62% | +4.89% | 0 | 4704 | +20.57% | [-2.85%, +50.85%] | 0.093 |
| b1_b3_4factor_no_atr | mini1yr | -0.43% | -0.06746 | -4.20% | +13.07% | 8 | 774 | -36.08% | [-59.67%, +3.44%] | 0.0627 |
| b1_b3_4factor_no_atr | 10yr | -2.90% | -0.6611 | -25.23% | +4.30% | 0 | 1982 | -3.44% | [-19.90%, +16.78%] | 0.7146 |
| b1_b3_4factor_no_atr | 20yr | -0.10% | 0.04578 | -26.58% | +7.69% | 1 | 7416 | +37.85% | [+6.63%, +78.68%] | 0.016 |

## Validation Labels

Causal logic is unestablished: these ablations test whether mechanical signal/veto/gross changes improve backtest behavior; they do not prove an economic mechanism.

Specific numbers are validated only against this local ablation run and current local panel; they are not production-calibrated thresholds.
