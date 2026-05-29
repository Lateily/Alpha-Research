# V3 Harness Report — v3c_alpha1_1_20260528_turnover_mechanics

- **manifest**: `/Users/years/Desktop/Stock/ar-platform/experiments/agent_tasks/variant_manifests/v3c_alpha1_1_20260528.json`
- **hash**: `a40ee6a0f85a8e3a21ec22a774ea9b70b06efbde6098e4e90291cf5afff8306c`
- **registered_at**: 2026-05-28T17:47:06Z by Codex T3
- **bundle**: `public/data/v3c_alpha1_1_bundle.json`

## Verdict: **FAIL**  (4 fail: ['MT', 'IMPL2', 'IMPL4', 'IMPL5'])

MT family-corrected p used = **0.4764** (BY over m=2 variants, c(m)=1.5000)

## Gate outcomes

| Gate | Verdict | Metric | Threshold | Reason |
|---|---|---|---|---|
| PRE1 | PASS | None | schema+fields | manifest schema OK; variant_id=v3c_alpha1_1_20260528_turnover_mechanics |
| PRE2 | PASS | None | registered_at < created_at | registered_at=2026-05-28T17:47:06Z vs earliest_run=2026-05-28T17:56:54.955878Z |
| PRE3 | PASS | None | declared | hypothesis_lock_hash declared (immutability enforced via git/branch) |
| WF1 | PASS | 3 | >=3/5 | 3/5 windows have same_gross α ≥ 0 point estimate; threshold 3/5 |
| WF2 | PASS | -0.0034278601122020858 | CI hi ≥ 0 AND not (p<0.05 with neg point) | OOS window wf_2022_2026 same_gross α point=-0.0034278601122020858, CI=[-0.1921,0.2329],… |
| MT | **FAIL** | 0.4764 | <0.05 | BY-corrected family p = 0.4764, threshold < 0.05 |
| BENCH | PASS | 5 | csi300, zz500, csi1000, ew500, cash2pct ALL required as non-empty curves (SSE50 optional, HSI absent per Junyan #13) | all required benchmarks present as non-empty curves: ['cash2pct', 'csi1000', 'csi300', … |
| NOSW | PASS | 0.21874550896385836 | not (full POS-sig AND wf present AND wf < 3/5 pos) | full-sample window='full_20yr' same_gross α point=0.2187 CI=[-0.0728,+0.6143] POS-sig=F… |
| IMPL1 | PASS | 6 | all windows == True | max_positions_enforced=True in all windows |
| IMPL2 | **FAIL** | 0.15778590318717198 | 0.3 | failed: [('full_20yr', 0.1562036113131313), ('wf_2006_2010', 0.15883233607399794), ('wf… |
| IMPL3 | PASS | 8.0 | 2.0 | median_n_positions ≥ 2.0 in all windows |
| IMPL4 | **FAIL** | 3.219021203094093 | 2.0 (= 200% annual) | turnover > 200% threshold; failed windows (window, observed turnover): [('full_20yr', '… |
| IMPL5 | **FAIL** | -0.5434 | -0.25 | failed: [('full_20yr', -0.5434), ('wf_2010_2014', -0.2785)] |
| IMPL6 | PASS | 969 | 250 | all windows ≥ 250 trade dates |
| IMPL7 | PASS | 0.21874550896385836 | 0.0 | window=full_20yr; same_gross α (already net of cost) by scenario: optimistic 0.20% RT=+… |
| AUD1 | PASS | 6 | ['config_hash', 'data_hash', 'git_commit', 'engine_version'] | all required audit fields present |
| AUD3 | PASS | 6 | n_total_trades_actual == n_total_trades | trade-log accounting consistent |
| BUNDLE | PASS | 6/6 | all manifest.test_plan.windows present | bundle complete: 6 declared windows all present (['full_20yr', 'wf_2006_2010', 'wf_2010… |
| AUD2 | TRACE | 6 | all windows == True | max_positions_enforced=True in all windows |

## Per-window metrics (baseline 0.40% RT)

| window | turnover | gross | carry | full-ref | MaxDD | same-gross α | p |
|---|---|---|---|---|---|---|---|
| full_20yr | 246.4% | 15.6% | 5.34 | 21.7% | -54.3% | +0.2187 | 0.1588 |
| wf_2006_2010 | 234.3% | 15.9% | 5.15 | 16.4% | -22.0% | +1.1846 | 0.1012 |
| wf_2010_2014 | 321.9% | 15.3% | 4.96 | 22.8% | -27.9% | +0.2382 | 0.4267 |
| wf_2014_2018 | 225.5% | 15.9% | 5.46 | 21.9% | -23.8% | +0.1069 | 0.7365 |
| wf_2018_2022 | 273.9% | 15.3% | 5.18 | 23.1% | -12.4% | -0.0154 | 0.8913 |
| wf_2022_2026 | 265.3% | 16.7% | 5.36 | 21.0% | -20.0% | -0.0034 | 0.9764 |

## Mechanics sanity gates (runner-side, inherited)

| window | turnover | sdrebuy | carry | full-ref | mechanics PASS |
|---|---|---|---|---|---|
| full_20yr | 246.4% | 0 | 5.34 | 21.7% | ✅ |
| wf_2006_2010 | 234.3% | 0 | 5.15 | 16.4% | ✅ |
| wf_2010_2014 | 321.9% | 0 | 4.96 | 22.8% | ❌ |
| wf_2014_2018 | 225.5% | 0 | 5.46 | 21.9% | ✅ |
| wf_2018_2022 | 273.9% | 0 | 5.18 | 23.1% | ✅ |
| wf_2022_2026 | 265.3% | 0 | 5.36 | 21.0% | ✅ |

## Before/after vs parent (v3c_alpha1)

| window | turnover v3c_alpha1→v3c_alpha1_1 | gross | carry | sg-α point |
|---|---|---|---|---|
| full_20yr | 852.0%→246.4% | 16.9%→15.6% | n/a→5.34 | +0.094→+0.219 |
| wf_2006_2010 | 805.8%→234.3% | 15.6%→15.9% | n/a→5.15 | +0.878→+1.185 |
| wf_2010_2014 | 958.6%→321.9% | 18.7%→15.3% | n/a→4.96 | +0.368→+0.238 |
| wf_2014_2018 | 832.9%→225.5% | 16.5%→15.9% | n/a→5.46 | -0.099→+0.107 |
| wf_2018_2022 | 834.9%→273.9% | 16.7%→15.3% | n/a→5.18 | -0.025→-0.015 |
| wf_2022_2026 | 883.3%→265.3% | 17.7%→16.7% | 0.00→5.36 | -0.099→-0.003 |

## BY family (multi-test correction)

alpha=0.05, m=2, c(m)=1.5000, k*=0

| variant_id | raw p | rank | adjusted p (BY) | reject@0.05 |
|---|---|---|---|---|
| v3c_alpha1_1_20260528_turnover_mechanics **← this variant** | 0.1588 | 1 | 0.4764 | False |
| v3c_alpha1_20260528_horizon10_4factor_no_rsi  | 0.4758 | 2 | 0.7137 | False |

## Cost-scenario robustness (full_20yr, same-gross α)

| scenario | same-gross α | CI | p |
|---|---|---|---|
| baseline_0.40_RT | +0.2187 | [-0.0728, +0.6143] | 0.1588 |
| optimistic_0.20_RT | +0.2691 | [-0.0407, +0.6873] | 0.0977 |
| pessimistic_0.60_RT | +0.1783 | [-0.1086, +0.5603] | 0.2448 |

---
Generated by `scripts/v3_harness.py`