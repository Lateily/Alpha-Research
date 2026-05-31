# iter-18 Swing Ablation Results

Experimental only. Outputs are under `experiments/agent_tasks/`.

| Variant | Window | CAGR | Sharpe | Max DD | Avg Gross | Median Pos | Trades | Same-gross Alpha | 95% CI | p |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| b1_4factor | mini1yr | +3.26% | 0.5611 | -3.85% | +15.90% | 8 | 768 | -20.61% | [-52.22%, +37.31%] | 0.3882 |

## Validation Labels

Causal logic is unestablished: these ablations test whether mechanical signal/veto/gross changes improve backtest behavior; they do not prove an economic mechanism.

Specific numbers are validated only against this local ablation run and current local panel; they are not production-calibrated thresholds.
