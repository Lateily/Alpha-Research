# V3 Harness Report — v3c_alpha1_3a_20260529_anti_drift_maxhold60

- **manifest**: `experiments/agent_tasks/variant_manifests/v3c_alpha1_3a_20260529.json`
- **hash**: `2de57039d35625b8cb7897e9ca1c4630974c567444bef1108cb7baacd95cc441`
- **registered_at**: 2026-05-29T10:31:26Z by Claude T1
- **single-variable change**: design.portfolio.turnover_mechanics.max_hold_days: null → 60 (all other knobs frozen from α1.2, incl. rebalance_cadence_days=20)
- **bundle**: `public/data/v3c_alpha1_3a_bundle.json`

## Verdict: **FAIL**  (5 fail: ['WF1', 'MT', 'IMPL2', 'IMPL4', 'IMPL5'])

MT family-corrected p used = **0.5619** (BY over m=4 variants, c(m)=2.0833)

## Gate outcomes

| Gate | Verdict | Metric | Threshold | Reason |
|---|---|---|---|---|
| PRE1 | PASS | None | schema+fields | manifest schema OK; variant_id=v3c_alpha1_3a_20260529_anti_drift_maxhold60 |
| PRE2 | PASS | None | registered_at < created_at | registered_at=2026-05-29T10:31:26Z vs earliest_run=2026-05-29T10:38:16.138860Z |
| PRE3 | PASS | None | declared | hypothesis_lock_hash declared (immutability enforced via git/branch) |
| WF1 | **FAIL** | 2 | >=3/5 | 2/5 windows have same_gross α ≥ 0 point estimate; threshold 3/5 |
| WF2 | PASS | -0.15697770679513856 | CI hi ≥ 0 AND not (p<0.05 with neg point) | OOS window wf_2022_2026 same_gross α point=-0.15697770679513856, CI=[-0.3601,0.1169], p… |
| MT | **FAIL** | 0.561944 | <0.05 | BY-corrected family p = 0.5619, threshold < 0.05 |
| BENCH | PASS | 5 | csi300, zz500, csi1000, ew500, cash2pct ALL required as non-empty curves (SSE50 optional, HSI absent per Junyan #13) | all required benchmarks present as non-empty curves: ['cash2pct', 'csi1000', 'csi300', … |
| NOSW | PASS | 0.2024280095453297 | not (full POS-sig AND wf present AND wf < 3/5 pos) | full-sample window='full_20yr' same_gross α point=0.2024 CI=[-0.0953,+0.6000] POS-sig=F… |
| IMPL1 | PASS | 6 | all windows == True | max_positions_enforced=True in all windows |
| IMPL2 | **FAIL** | 0.142537045673537 | 0.3 | failed: [('full_20yr', 0.13723955696969697), ('wf_2006_2010', 0.13335302261048307), ('w… |
| IMPL3 | PASS | 7.0 | 2.0 | median_n_positions ≥ 2.0 in all windows |
| IMPL4 | **FAIL** | 2.6990785364055716 | 2.0 (= 200% annual) | turnover > 200% threshold; failed windows (window, observed turnover): [('full_20yr', '… |
| IMPL5 | **FAIL** | -0.4778 | -0.25 | failed: [('full_20yr', -0.4778)] |
| IMPL6 | PASS | 969 | 250 | all windows ≥ 250 trade dates |
| IMPL7 | PASS | 0.2024280095453297 | 0.0 | window=full_20yr; same_gross α (already net of cost) by scenario: optimistic 0.20% RT=+… |
| AUD1 | PASS | 6 | ['config_hash', 'data_hash', 'git_commit', 'engine_version'] | all required audit fields present |
| AUD3 | PASS | 6 | n_total_trades_actual == n_total_trades | trade-log accounting consistent |
| BUNDLE | PASS | 6/6 | all manifest.test_plan.windows present | bundle complete: 6 declared windows all present (['full_20yr', 'wf_2006_2010', 'wf_2010… |
| AUD2 | TRACE | 6 | all windows == True | max_positions_enforced=True in all windows |

## Per-window metrics (baseline 0.40% RT)

| window | turnover | gross | carry | full-ref | MaxDD | same-gross α | p |
|---|---|---|---|---|---|---|---|
| full_20yr | 254.6% | 13.7% | 2.94 | 30.0% | -47.8% | +0.2024 | 0.2023 |
| wf_2006_2010 | 246.2% | 13.3% | 2.81 | 34.1% | -18.7% | +1.3899 | 0.0385 |
| wf_2010_2014 | 269.9% | 14.4% | 2.88 | 29.7% | -21.0% | +0.4896 | 0.1616 |
| wf_2014_2018 | 249.6% | 14.7% | 3.00 | 30.5% | -22.5% | -0.1421 | 0.6043 |
| wf_2018_2022 | 256.2% | 14.1% | 2.90 | 25.4% | -18.3% | -0.0984 | 0.4697 |
| wf_2022_2026 | 263.1% | 15.4% | 3.08 | 27.2% | -19.1% | -0.1570 | 0.2298 |

## Mechanics sanity gates (runner-side, inherited)

| window | turnover | sdrebuy | carry | full-ref | mechanics PASS |
|---|---|---|---|---|---|
| full_20yr | 254.6% | 0 | 2.94 | 30.0% | ✅ |
| wf_2006_2010 | 246.2% | 0 | 2.81 | 34.1% | ❌ |
| wf_2010_2014 | 269.9% | 0 | 2.88 | 29.7% | ✅ |
| wf_2014_2018 | 249.6% | 0 | 3.00 | 30.5% | ❌ |
| wf_2018_2022 | 256.2% | 0 | 2.90 | 25.4% | ✅ |
| wf_2022_2026 | 263.1% | 0 | 3.08 | 27.2% | ✅ |

## Before/after vs parent (v3c_alpha1_2)

| window | turnover v3c_alpha1_2→v3c_alpha1_3a | gross | carry | sg-α point |
|---|---|---|---|---|
| full_20yr | 67.9%→254.6% | 15.4%→13.7% | 5.79→2.94 | +0.470→+0.202 |
| wf_2006_2010 | 149.0%→246.2% | 16.7%→13.3% | 4.65→2.81 | +1.372→+1.390 |
| wf_2010_2014 | 205.1%→269.9% | 14.7%→14.4% | 4.16→2.88 | +0.424→+0.490 |
| wf_2014_2018 | 145.4%→249.6% | 15.9%→14.7% | 4.78→3.00 | -0.097→-0.142 |
| wf_2018_2022 | 208.8%→256.2% | 13.8%→14.1% | 3.78→2.90 | -0.198→-0.098 |
| wf_2022_2026 | 179.1%→263.1% | 17.1%→15.4% | 4.62→3.08 | +0.082→-0.157 |

## BY family (multi-test correction)

alpha=0.05, m=4, c(m)=2.0833, k*=0

| variant_id | raw p | rank | adjusted p (BY) | reject@0.05 |
|---|---|---|---|---|
| v3c_alpha1_1_20260528_turnover_mechanics  | 0.1588 | 2 | 0.5619 | False |
| v3c_alpha1_20260528_horizon10_4factor_no_rsi  | 0.4758 | 4 | 0.9912 | False |
| v3c_alpha1_2_20260529_turnover_compression  | 0.0153 | 1 | 0.1275 | False |
| v3c_alpha1_3a_20260529_anti_drift_maxhold60 **← this variant** | 0.2023 | 3 | 0.5619 | False |

## Cost-scenario robustness (full_20yr, same-gross α)

| scenario | same-gross α | CI | p |
|---|---|---|---|
| baseline_0.40_RT | +0.2024 | [-0.0953, +0.6000] | 0.2023 |
| optimistic_0.20_RT | +0.2275 | [-0.0742, +0.6204] | 0.1520 |
| pessimistic_0.60_RT | +0.1862 | [-0.1100, +0.5801] | 0.2430 |

---
Generated by `scripts/v3_harness.py`