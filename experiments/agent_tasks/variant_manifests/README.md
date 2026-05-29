# v3 Variant Manifests — Pre-registration Protocol

> Per `docs/strategy/SWING_STRATEGY_v3.md` §3.4 (v3d) + Junyan §8.1 ratification:
> **Every v3 variant must have a pre-registered manifest BEFORE its backtest runs.**

## Why pre-registration?

The v3 hard gate suite (§2 of the spec) implements BH-Yekutieli multi-test correction
across the v3 variant family. If we let ourselves register a variant *after* seeing
its backtest result, we'd be cherry-picking from a much larger implicit family and
the multi-test correction would be meaningless.

The fix (Junyan, 2026-05-28): **every variant is registered immutably before backtest
runs**. The manifest declares the hypothesis, expected failure modes, and locked
config. The backtest cannot change which variants are in the family after the fact.

## Protocol

### 1. Author the manifest

Copy `experiments/agent_tasks/v3_variant_manifest_template.json` and fill in:

- `variant.variant_id` — short, dated, unique. Convention: `v3c_YYYYMMDD_short_name`.
- `variant.registered_at` — UTC ISO 8601 timestamp (`YYYY-MM-DDTHH:MM:SSZ`).
- `variant.registered_by` — `Claude` | `Codex` | `Junyan`.
- `variant.status` — `pre_registered`.
- `variant.hypothesis` — one sentence stating why this should improve post-cost α.
- `variant.causal_logic_label` — `Causal logic is unestablished/questionable/valid because ...`
- `variant.expected_failure_modes` — list 2-4 honest failure modes.
- `variant.hypothesis_lock_hash` — sha256 of the rest of `variant.*` (manual or scripted).
- `design.*` — full factor inputs, universe, portfolio, risk, cost model.
- `test_plan.*` — windows, benchmarks, family, multi-test method.
- `hard_gates.*` — gate thresholds (copy from template unless an exception is being declared).

Save to `experiments/agent_tasks/variant_manifests/<variant_id>.json`.

### 2. Commit the manifest

Manifest commit MUST land BEFORE the backtest run. The audit field `created_at`
on the backtest result must be strictly greater than `manifest.variant.registered_at`.

```
git add experiments/agent_tasks/variant_manifests/<variant_id>.json
git commit -m "register v3 variant <variant_id>"
```

### 3. Run the backtest

The backtest must:
- Emit `audit.created_at` ISO 8601 timestamp per window (or top-level `_meta.created_at`).
- Include all gates' input fields per `experiments/agent_tasks/v3_variant_manifest_template.json` → `hard_gates`.

### 4. Run the gate evaluation

```
python3 scripts/v3_gate_eval.py \
    --variant <variant_id> \
    --result <path_to_backtest_result.json> \
    --manifest experiments/agent_tasks/variant_manifests/<variant_id>.json \
    --family-corrected-p <BY-corrected p from v3_multi_test_correction.py>
```

Exit code 0 = PASS all gates. Exit code 1 = any gate failed.

### 5. Multi-test correction

After all currently-registered variants have run, compute BY-corrected p-values:

```
python3 scripts/v3_multi_test_correction.py --input /tmp/v3_family.json
```

Where `/tmp/v3_family.json` =
```json
{
  "alpha": 0.05,
  "variants": [
    {"variant_id": "v3c_horizon10",   "p_value": 0.012},
    {"variant_id": "v3c_main_board",  "p_value": 0.045},
    {"variant_id": "v3c_sector_neut", "p_value": 0.180}
  ]
}
```

Use each variant's adjusted_p in step 4 above. **Calibrate set** = the variants that
were registered AT the time of the multi-test computation. Variants registered AFTER
the run cannot retro-fit the correction.

## Immutability

Once a manifest is committed, its `variant.*` block is **immutable**. Specifically:
- `hypothesis` cannot be reworded after seeing results.
- `expected_failure_modes` cannot be revised after seeing results.
- `design.*` cannot be tweaked after seeing results.
- `hard_gates.*` thresholds cannot be relaxed after seeing results.

If a re-run is needed with changed config, **register a new variant_id**
(e.g. `v3c_horizon10_v2`). The old manifest stays in the family.

Enforcement is via:
1. Git (manifest commit log is auditable).
2. `hypothesis_lock_hash` field — recompute and compare on every gate eval.
3. PRE3 gate in `scripts/v3_gate_eval.py` (checks lock_hash is declared).

## Calibrate-set boundary (Junyan red line)

> "BH-Yekutieli 跨全部 v3 variant family, but calibrate set 由 manifest registered_at
> 决定 (防过晚 register variant 后倒退 multi-test correction)"

> "Multi-test correction 中, 不能把 iter-13~18 之前的 22 个 backtest '回溯加入'
> calibrate set (那是过去的事; v3 重新开始)"

In plain English: the v3 family starts fresh. The 22+ pre-v3 backtests are NOT in
the BY family. Each new v3 variant joins the calibrate set the moment its manifest
is registered — not before, not after.

## Carry-over red lines (from `~/.claude/projects/-Users-years/memory/MEMORY.md`)

- **Oversell discipline** — `causal_logic_label` defaults to `unestablished` unless
  pre-existing per-factor IC + cost data make it `questionable` or `valid`.
- **Verify Codex output landed** — manifest registration MUST be committed before
  running; verify with `git log experiments/agent_tasks/variant_manifests/`.
- **Tushare 3-API DEFERRED** — manifest `factor_inputs` cannot list any factor from
  `stk_factor_pro` / `top_list` / `moneyflow_cnt` (not in current 15000-tier scope).

---

**Last updated**: 2026-05-28 (v3d framework spawn — Codex T3).
**Related docs**:
- `docs/strategy/SWING_STRATEGY_v3.md` §2 (gates) + §3.4 (v3d framework spec)
- `docs/strategy/V3A_OOS_DIAGNOSTIC_2026-05-28.md` (why these gates exist)
- `experiments/agent_tasks/v3_variant_manifest_template.json` (schema source)
