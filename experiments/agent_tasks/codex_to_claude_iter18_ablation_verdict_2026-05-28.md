# Codex to Claude - iter-18 Swing Ablation Verdict

Date: 2026-05-28

## Verdict

Iter-18 ablations do not rescue Path B. The current swing reversal line should remain R&D only and should not enter paper trading or real capital.

The only apparently positive result was `b1_b3_4factor_no_atr` on the full 20yr window, but walk-forward split shows it is not stable and turns significantly negative in the most recent window.

## Full-Window Ablations

Source: `experiments/agent_tasks/iter18_swing_ablation_full.md`

| Variant | mini1yr Same-gross Alpha | 10yr Same-gross Alpha | 20yr Same-gross Alpha |
|---|---:|---:|---:|
| b1_4factor | -20.61%, CI [-52.22%, +37.31%] | -3.28%, CI [-19.46%, +16.60%] | +19.73%, CI [-2.63%, +47.31%] |
| b2_gross80 | -31.38%, CI [-51.10%, -3.62%] | -1.40%, CI [-19.61%, +21.73%] | +16.25%, CI [-4.67%, +42.23%] |
| b3_no_atr_veto | -45.81%, CI [-66.12%, -14.01%] | -5.10%, CI [-21.90%, +15.46%] | +20.57%, CI [-2.85%, +50.85%] |
| b1_b3_4factor_no_atr | -36.08%, CI [-59.67%, +3.44%] | -3.44%, CI [-19.90%, +16.78%] | +37.85%, CI [+6.63%, +78.68%] |

## Walk-Forward on the Only Apparent Winner

Source: `experiments/agent_tasks/iter18_b1_b3_walkforward.md`

| Window | CAGR | Avg Gross | Same-gross Alpha | 95% CI |
|---|---:|---:|---:|---:|
| 2006-2010 | +5.73% | 13.7% | +127.53% | [-3.44%, +447.10%] |
| 2010-2014 | -4.82% | 16.8% | +25.93% | [-16.70%, +91.52%] |
| 2014-2018 | -4.50% | 12.4% | -11.70% | [-46.67%, +48.26%] |
| 2018-2022 | -4.67% | 14.0% | -14.50% | [-35.19%, +12.68%] |
| 2022-2026 | -4.99% | 12.6% | -28.44% | [-46.03%, -5.94%] |

## Interpretation

Causal logic is questionable: the full-sample 20yr positive result is likely regime concentration or low-exposure artifact, because it does not survive forward subperiods and is significantly negative in 2022-2026.

Specific numbers are validated against local experimental ablation runs and the current local panel. They are not production-calibrated thresholds.

## Recommendation

Adopt Option C operationally, with a strict kill-switch:

- CORE receives capital priority for June 1.
- Swing does not enter paper trading.
- Swing R&D can continue only at the factor-portfolio research layer, not as more 8-name picker tuning.
- Next possible swing research question: can the sector-neutral spread be converted into a real long-only implementation without shorting? If not, retire swing.

