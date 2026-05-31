# iter-18 Swing Ablation Results

Experimental only. Outputs are under `experiments/agent_tasks/`.

| Variant | Window | CAGR | Sharpe | Max DD | Avg Gross | Median Pos | Trades | Same-gross Alpha | 95% CI | p |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| b1_b3_4factor_no_atr | wf_2006_2010 | +5.73% | 0.4077 | -17.40% | +13.71% | 8 | 2760 | +127.53% | [-3.44%, +447.10%] | 0.0631 |
| b1_b3_4factor_no_atr | wf_2010_2014 | -4.82% | -0.2981 | -21.66% | +16.75% | 8 | 2914 | +25.93% | [-16.70%, +91.52%] | 0.267 |
| b1_b3_4factor_no_atr | wf_2014_2018 | -4.50% | -0.4485 | -26.47% | +12.44% | 8 | 2502 | -11.70% | [-46.67%, +48.26%] | 0.6382 |
| b1_b3_4factor_no_atr | wf_2018_2022 | -4.67% | -0.6602 | -17.21% | +14.04% | 8 | 3051 | -14.50% | [-35.19%, +12.68%] | 0.2685 |
| b1_b3_4factor_no_atr | wf_2022_2026 | -4.99% | -0.9642 | -22.99% | +12.63% | 8 | 3368 | -28.44% | [-46.03%, -5.94%] | 0.0161 |

## Validation Labels

Causal logic is unestablished: these ablations test whether mechanical signal/veto/gross changes improve backtest behavior; they do not prove an economic mechanism.

Specific numbers are validated only against this local ablation run and current local panel; they are not production-calibrated thresholds.
