# v3 Hard-Gate Evaluation — v3c_alpha1_3a_20260529_anti_drift_maxhold60

**Verdict**: **FAIL**  (stage: `R&D`)

| Field | Value |
|---|---|
| variant_id | v3c_alpha1_3a_20260529_anti_drift_maxhold60 |
| total gates | 19 |
| failed gates | 5 (['WF1', 'MT', 'IMPL2', 'IMPL4', 'IMPL5']) |
| NA gates | 0 ([]) |
| TRACE gates | 1 (['AUD2']) |
| result_json | /Users/years/Desktop/Stock/ar-platform/public/data/v3c_alpha1_3a_bundle.json |
| manifest_json | experiments/agent_tasks/variant_manifests/v3c_alpha1_3a_20260529.json |
| family_corrected_p | 0.561944 |

## Gate outcomes

Verdict column lifecycle (v3 Phase A Junyan ratify #1/#3):
`PASS` = condition met. `FAIL` = condition violated (blocking).
`NA` = not applicable in this bundle (not blocking; e.g. NOSW when no
full-sample window). `TRACE` = informational mirror (not blocking;
e.g. AUD2 mirrors IMPL1).

| Gate | Category | Verdict | Metric | Threshold | Reason |
|---|---|---|---|---|---|
| PRE1 | PRE | PASS | — | schema+fields | manifest schema OK; variant_id=v3c_alpha1_3a_20260529_anti_drift_maxhold60 |
| PRE2 | PRE | PASS | — | registered_at < created_at | registered_at=2026-05-29T10:31:26Z vs earliest_run=2026-05-29T10:38:16.138860Z |
| PRE3 | PRE | PASS | — | declared | hypothesis_lock_hash declared (immutability enforced via git/branch) |
| WF1 | STAT | **FAIL** | 2 | >=3/5 | 2/5 windows have same_gross α ≥ 0 point estimate; threshold 3/5 |
| WF2 | STAT | PASS | -0.1570 | CI hi ≥ 0 AND not (p<0.05 with neg point) | OOS window wf_2022_2026 same_gross α point=-0.15697770679513856, CI=[-0.3601,0.1169], p=0.2298; NEG-sig=False |
| MT | STAT | **FAIL** | 0.5619 | <0.05 | BY-corrected family p = 0.5619, threshold < 0.05 |
| BENCH | STAT | PASS | 5 | csi300, zz500, csi1000, ew500, cash2pct ALL required as non-empty curves (SSE50 optional, HSI absent per Junyan #13) | all required benchmarks present as non-empty curves: ['cash2pct', 'csi1000', 'csi300', 'ew500', 'zz500'] |
| NOSW | STAT | PASS | 0.2024 | not (full POS-sig AND wf present AND wf < 3/5 pos) | full-sample window='full_20yr' same_gross α point=0.2024 CI=[-0.0953,+0.6000] POS-sig=False; walk-forward 2/5 POS; bad_pattern=False |
| IMPL1 | IMPL | PASS | 6 | all windows == True | max_positions_enforced=True in all windows |
| IMPL2 | IMPL | **FAIL** | 0.1425 | 0.3 | failed: [('full_20yr', 0.13723955696969697), ('wf_2006_2010', 0.13335302261048307), ('wf_2010_2014', 0.14365944891640867), ('wf_2014_2018', 0.1468091821903787), ('wf_2018_2022', 0.14052633882595264), ('wf_2022_2026', 0.15363472452830187)] |
| IMPL3 | IMPL | PASS | 7.0000 | 2.0 | median_n_positions ≥ 2.0 in all windows |
| IMPL4 | IMPL | **FAIL** | 2.6991 | 2.0 (= 200% annual) | turnover > 200% threshold; failed windows (window, observed turnover): [('full_20yr', '254.6%'), ('wf_2006_2010', '246.2%'), ('wf_2010_2014', '269.9%'), ('wf_2014_2018', '249.6%'), ('wf_2018_2022', '256.2%'), ('wf_2022_2026', '263.1%')] |
| IMPL5 | IMPL | **FAIL** | -0.4778 | -0.25 | failed: [('full_20yr', -0.4778)] |
| IMPL6 | IMPL | PASS | 969 | 250 | all windows ≥ 250 trade dates |
| IMPL7 | IMPL | PASS | 0.2024 | 0.0 | window=full_20yr; same_gross α (already net of cost) by scenario: optimistic 0.20% RT=+0.2275; baseline 0.40% RT=+0.2024; pessimistic 0.60% RT=+0.1862; stage=R&D |
| AUD1 | AUDIT | PASS | 6 | ['config_hash', 'data_hash', 'git_commit', 'engine_version'] | all required audit fields present |
| AUD3 | AUDIT | PASS | 6 | n_total_trades_actual == n_total_trades | trade-log accounting consistent |
| BUNDLE | AUDIT | PASS | 6/6 | all manifest.test_plan.windows present | bundle complete: 6 declared windows all present (['full_20yr', 'wf_2006_2010', 'wf_2010_2014', 'wf_2014_2018', 'wf_2018_2022', 'wf_2022_2026']) |
| AUD2 | AUDIT | _TRACE_ | 6 | all windows == True | max_positions_enforced=True in all windows |

## Methodology notes

- Gates derived from `docs/strategy/SWING_STRATEGY_v3.md` §2 + §3.4.
- Manifest schema: `experiments/agent_tasks/v3_variant_manifest_template.json`.
- BY (Benjamini-Yekutieli) family p must be computed separately via
  `scripts/v3_multi_test_correction.py` and injected via `--family-corrected-p`.
- Per v3 red line: missing fields default to FAIL (better a false fail than a silent pass).
- v3 Phase A Junyan ratify (2026-05-28 PM2):
  - **#1 AUD2 vs IMPL1**: AUD2 is TRACE (audit mirror), IMPL1 is the load-bearing gate.
  - **#2 turnover semantic**: IMPL4 reads `audit.turnover_annual_ratio` (canonical);
    `turnover_annual_pct` is a deprecated alias holding the SAME ratio value.
    Threshold 2.0 = 200% annual book turnover. Display layer × 100.
  - **#3 NOSW NA**: walk-forward-only bundles return NA (not blocking).
    Bundle completeness is enforced separately by the BUNDLE audit gate.
  - **#4 IMPL7 cost scenarios**: research baseline 0.40% RT (must pass).
    Optimistic 0.20% + pessimistic 0.60% reported but only enforced at
    `paper_promotion` / `capital_promotion` stage.
  - **#5 PRE3 hash**: `hypothesis_lock_hash` declared at manifest registration.
    See `scripts/v3_manifest_hash.py` for compute/inject helper.
  - **#13 multi-bench**: csi300, zz500, csi1000, ew500, cash2pct ALL required as
    non-empty curves. SSE50 optional. HSI intentionally absent.

---

Generated by `scripts/v3_gate_eval.py`
