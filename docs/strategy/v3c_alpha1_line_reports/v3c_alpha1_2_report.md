# V3 Harness Report — v3c_alpha1_2_20260529_turnover_compression

- **manifest**: `experiments/agent_tasks/variant_manifests/v3c_alpha1_2_20260529.json`
- **hash**: `652c4cb624f4c00e82bcb94d497daf96efe2909d11425fb0683bff8a165f1da1`
- **registered_at**: 2026-05-29T02:58:28Z by Claude T1
- **single-variable change**: design.portfolio.rebalance_cadence_days: 10 → 20 (all other knobs frozen from α1.1)
- **bundle**: `public/data/v3c_alpha1_2_bundle.json`

## Verdict: **FAIL**  (4 fail: ['MT', 'IMPL2', 'IMPL4', 'IMPL5'])

MT family-corrected p used = **0.0841** (BY over m=3 variants, c(m)=1.8333)

## Gate outcomes

| Gate | Verdict | Metric | Threshold | Reason |
|---|---|---|---|---|
| PRE1 | PASS | None | schema+fields | manifest schema OK; variant_id=v3c_alpha1_2_20260529_turnover_compression |
| PRE2 | PASS | None | registered_at < created_at | registered_at=2026-05-29T02:58:28Z vs earliest_run=2026-05-29T03:18:50.810099Z |
| PRE3 | PASS | None | declared | hypothesis_lock_hash declared (immutability enforced via git/branch) |
| WF1 | PASS | 3 | >=3/5 | 3/5 windows have same_gross α ≥ 0 point estimate; threshold 3/5 |
| WF2 | PASS | 0.08201242673716247 | CI hi ≥ 0 AND not (p<0.05 with neg point) | OOS window wf_2022_2026 same_gross α point=0.08201242673716247, CI=[-0.1768,0.4075], p=… |
| MT | **FAIL** | 0.08415 | <0.05 | BY-corrected family p = 0.0842, threshold < 0.05 |
| BENCH | PASS | 5 | csi300, zz500, csi1000, ew500, cash2pct ALL required as non-empty curves (SSE50 optional, HSI absent per Junyan #13) | all required benchmarks present as non-empty curves: ['cash2pct', 'csi1000', 'csi300', … |
| NOSW | PASS | 0.4703472870050456 | not (full POS-sig AND wf present AND wf < 3/5 pos) | full-sample window='full_20yr' same_gross α point=0.4703 CI=[+0.0847,+1.0032] POS-sig=T… |
| IMPL1 | PASS | 6 | all windows == True | max_positions_enforced=True in all windows |
| IMPL2 | **FAIL** | 0.15593795084005013 | 0.3 | failed: [('full_20yr', 0.1535844381818182), ('wf_2006_2010', 0.16706208427543678), ('wf… |
| IMPL3 | PASS | 7.0 | 2.0 | median_n_positions ≥ 2.0 in all windows |
| IMPL4 | **FAIL** | 2.087684277312401 | 2.0 (= 200% annual) | turnover > 200% threshold; failed windows (window, observed turnover): [('wf_2010_2014'… |
| IMPL5 | **FAIL** | -0.5069 | -0.25 | failed: [('full_20yr', -0.5069), ('wf_2006_2010', -0.3292), ('wf_2014_2018', -0.264)] |
| IMPL6 | PASS | 969 | 250 | all windows ≥ 250 trade dates |
| IMPL7 | PASS | 0.4703472870050456 | 0.0 | window=full_20yr; same_gross α (already net of cost) by scenario: optimistic 0.20% RT=+… |
| AUD1 | PASS | 6 | ['config_hash', 'data_hash', 'git_commit', 'engine_version'] | all required audit fields present |
| AUD3 | PASS | 6 | n_total_trades_actual == n_total_trades | trade-log accounting consistent |
| BUNDLE | PASS | 6/6 | all manifest.test_plan.windows present | bundle complete: 6 declared windows all present (['full_20yr', 'wf_2006_2010', 'wf_2010… |
| AUD2 | TRACE | 6 | all windows == True | max_positions_enforced=True in all windows |

## Per-window metrics (baseline 0.40% RT)

| window | turnover | gross | carry | full-ref | MaxDD | same-gross α | p |
|---|---|---|---|---|---|---|---|
| full_20yr | 67.9% | 15.4% | 5.79 | 6.7% | -50.7% | +0.4703 | 0.0153 |
| wf_2006_2010 | 149.0% | 16.7% | 4.65 | 19.2% | -32.9% | +1.3722 | 0.0788 |
| wf_2010_2014 | 205.1% | 14.7% | 4.16 | 25.0% | -21.1% | +0.4235 | 0.2030 |
| wf_2014_2018 | 145.4% | 15.9% | 4.78 | 22.4% | -26.4% | -0.0971 | 0.7040 |
| wf_2018_2022 | 208.8% | 13.8% | 3.78 | 23.5% | -19.9% | -0.1977 | 0.1075 |
| wf_2022_2026 | 179.1% | 17.1% | 4.62 | 21.9% | -16.3% | +0.0820 | 0.5543 |

## Mechanics sanity gates (runner-side, inherited)

| window | turnover | sdrebuy | carry | full-ref | mechanics PASS |
|---|---|---|---|---|---|
| full_20yr | 67.9% | 0 | 5.79 | 6.7% | ✅ |
| wf_2006_2010 | 149.0% | 0 | 4.65 | 19.2% | ✅ |
| wf_2010_2014 | 205.1% | 0 | 4.16 | 25.0% | ✅ |
| wf_2014_2018 | 145.4% | 0 | 4.78 | 22.4% | ✅ |
| wf_2018_2022 | 208.8% | 0 | 3.78 | 23.5% | ✅ |
| wf_2022_2026 | 179.1% | 0 | 4.62 | 21.9% | ✅ |

## Before/after vs parent (v3c_alpha1_1)

| window | turnover v3c_alpha1_1→v3c_alpha1_2 | gross | carry | sg-α point |
|---|---|---|---|---|
| full_20yr | 246.4%→67.9% | 15.6%→15.4% | 5.34→5.79 | +0.219→+0.470 |
| wf_2006_2010 | 234.3%→149.0% | 15.9%→16.7% | 5.15→4.65 | +1.185→+1.372 |
| wf_2010_2014 | 321.9%→205.1% | 15.3%→14.7% | 4.96→4.16 | +0.238→+0.424 |
| wf_2014_2018 | 225.5%→145.4% | 15.9%→15.9% | 5.46→4.78 | +0.107→-0.097 |
| wf_2018_2022 | 273.9%→208.8% | 15.3%→13.8% | 5.18→3.78 | -0.015→-0.198 |
| wf_2022_2026 | 265.3%→179.1% | 16.7%→17.1% | 5.36→4.62 | -0.003→+0.082 |

## BY family (multi-test correction)

alpha=0.05, m=3, c(m)=1.8333, k*=0

| variant_id | raw p | rank | adjusted p (BY) | reject@0.05 |
|---|---|---|---|---|
| v3c_alpha1_1_20260528_turnover_mechanics  | 0.1588 | 2 | 0.4367 | False |
| v3c_alpha1_20260528_horizon10_4factor_no_rsi  | 0.4758 | 3 | 0.8723 | False |
| v3c_alpha1_2_20260529_turnover_compression **← this variant** | 0.0153 | 1 | 0.0841 | False |

## Cost-scenario robustness (full_20yr, same-gross α)

| scenario | same-gross α | CI | p |
|---|---|---|---|
| baseline_0.40_RT | +0.4703 | [+0.0847, +1.0032] | 0.0153 |
| optimistic_0.20_RT | +0.4790 | [+0.0914, +1.0149] | 0.0140 |
| pessimistic_0.60_RT | +0.4631 | [+0.0802, +0.9945] | 0.0164 |

---
Generated by `scripts/v3_harness.py`