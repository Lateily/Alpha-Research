# Commit-Scope Plan — CORE Guardrail Productionization Audit (2026-05-29)

**Read-only audit. No commits made.** This is the recommendation; Junyan decides what lands.
**Hard boundaries**: no position changes, no auto-trade, no commit, no push. `positions.json` / `analytics.json` / `snapshots.json` are paper state — NOT part of any guardrail bundle.

## Two findings that shape everything

1. **`data_history/` is gitignored** (`.gitignore:16`). So `hk_prices.parquet` + `hk_prices_meta.json` and the price panel are **local-only, never committed**. Consequence: the daily pipeline must **fetch** HK data (run `fetch_hk_prices.py`), it cannot read a committed parquet. Bundle E commits the *script only*.
2. **`run_swing_backtest_fast.py` is +1,161 / −50 lines vs HEAD** — my `max_hold_days` edit is ~15 lines; the other ~1,145 are **prior uncommitted v3 engine infrastructure** (R0 audit, same-gross α, turnover mechanics, cost scenarios). The whole multi-day engine arc was never committed. `swing_risk_manager.py` = +25 prior. So commits MUST be dependency-ordered: engine → tooling → research → CORE → alignment → UI.

## State summary

- **Staged (prior session, NOT by me)**: `CODEX_FINDINGS.md`, `analytics.json`, `positions.json`, `snapshots.json`, `run_swing_backtest_fast.py`, `swing_risk_manager.py`. The staged engine snapshot is stale (predates my `max_hold` edit); re-add before committing.
- **Modified unstaged**: `morning-report.yml`, `morning-report.js`, `Dashboard.jsx` (mine) + the dual-staged files above.
- **Untracked**: 22 scripts, 18 docs, 51 experiments/, 127 public/data JSONs.
- **Verified NOT mine**: `positions.json` / `analytics.json` / `snapshots.json` modifications predate this session (no script I ran writes them — contract check, Phase 4).

## Commit bundles (dependency order)

| # | Bundle | Files | Recommend |
|---|---|---|---|
| **A** | **Engine + risk infra** (foundational) | `scripts/run_swing_backtest_fast.py` (prior v3 infra + my `max_hold_days`), `scripts/swing_risk_manager.py` (prior) | **Commit first.** ⚠ split-or-not is Junyan's call: the file mixes a large prior arc + my 15-line `max_hold`. Recommend ONE commit ("v3 engine: audit/same-gross/turnover-mechanics + max_hold cap") since the prior arc was never landed and my edit builds on it. |
| **B** | **v3 gate + harness tooling** | `scripts/{v3_harness,v3_gate_eval,v3_gate_check_helpers,v3_manifest_hash,v3_multi_test_correction,v3_bench_loader,v3a_oos_diagnostic,v3c_regime_diagnostic,run_v3c_alpha1,run_v3c_alpha1_1}.py` + `experiments/agent_tasks/variant_manifests/` (4 manifests + template + README + .gitkeep) | **Commit** (depends on A). Reusable research machine — Junyan's "保留 harness 和 gates". |
| **C** | **Path B verdict + diagnostics (docs)** | `docs/strategy/{SWING_STRATEGY_v2,SWING_STRATEGY_v3,SWING_BACKTEST_AUDIT_2026-05-28,V3A_OOS_DIAGNOSTIC_2026-05-28,V3B_COST_AUDIT_2026-05-28,V3C_ALPHA1_2_ANALYSIS_2026-05-29,V3C_ALPHA1_LINE_VERDICT_2026-05-29}.md` + `docs/strategy/v3c_alpha1_line_reports/` (9 reports) | **Commit.** Durable record of the α1.x STOP verdict. |
| **D** | **CORE validation** | `scripts/{core_validation_ledger,backfill_thesis_direction}.py` + `docs/strategy/CORE_VALIDATION_PLAN_2026-05-29.md` + `public/data/{core_validation_ledger,thesis_direction_backfill}.json` | **Commit** (depends on A/B). |
| **E** | **HK data fetch** | `scripts/fetch_hk_prices.py` **only** (parquet is gitignored → pipeline fetches) | **Commit script.** Pipeline regen, not data. |
| **F** | **Alignment guardrail + UI wiring** | `scripts/portfolio_thesis_alignment.py`, `docs/strategy/PORTFOLIO_THESIS_ALIGNMENT_RULES.md`, `public/data/portfolio_thesis_alignment.json` (**must commit — daily report reads it**), `src/Dashboard.jsx`, `api/morning-report.js`, `.github/workflows/morning-report.yml` | **Commit** (depends on D). The guardrail + its UI/report surfaces. |
| **G** | **Experiment artifacts** | 79 `public/data/v3c_alpha1*` per-window JSONs + 40 `iter1X`/`path_b` JSONs; `experiments/agent_tasks/*.{json,md}`; `experiments/*.py`; prior scripts (`iter16_attribution`, `daily_swing_runner`, `quality_universe`, `rolling_ic_20yr`, `run_iter17_r2`, `run_iter18_*`, `swing_factor_diagnostics`) | **Hold / decide.** Bulky intermediate research data. Options: (i) commit BUNDLES only (`v3c_alpha1*_bundle.json` ×4) + gitignore per-window JSONs; (ii) bulk-commit to a research-data area; (iii) gitignore `public/data/v3c_alpha1*_wf_*`/`*_full_*`. Recommend (i). |
| **X** | **DO NOT COMMIT** | `public/data/positions.json`, `analytics.json`, `snapshots.json` | Paper state, updated by the paper pipeline — never part of guardrail commits (Junyan rule + not mine). Unstage if needed before bundling. |

## Suggested commit sequence (when Junyan approves)

1. A (engine) → 2. B (tooling+manifests) → 3. C (Path B docs) → 4. D (CORE validation) → 5. E (HK fetch) → 6. F (alignment+UI). G decided separately; X never.

Each bundle is independently buildable on its predecessors (the harness imports the engine; the ledger imports the harness's config-mapping + alignment; the UI reads the JSONs). No bundle commits `positions.json`.

## Productionization results (Phases 2–4, this audit)

- **Phase 2 — chain verified.** Ran backfill → alignment → ledger fresh; cross-link check: all 5 positions agree on label across all three artifacts (backfill latest == alignment dir == ledger dir; alignment == ledger alignment). End-to-end consistent.
- **Phase 3 — daily GHA regen added.** `morning-report.yml` gains a `Regenerate thesis alignment marker` step (stdlib-only, `continue-on-error`) before report generation: regenerates `portfolio_thesis_alignment.json` from committed factcheck records + `positions.json`, so the email's human-review queue is always fresh and never skips on a missing file. `permissions: contents: read` → regen is transient, no commit.
- **Phase 4 — contract tests added.** `scripts/test_alignment_guardrail.py` (add to Bundle F) — all PASS:
  - C1 marker logic (10 cases); C2 review semantics; C3 no protected-file writes; C4 no trade-execution code; **C5 runtime: running the full chain leaves positions/analytics/snapshots.json byte-for-byte UNCHANGED**; C6 marker-only output (no auto-action keys).

**Bundle F additions**: `scripts/test_alignment_guardrail.py`, `morning-report.yml` regen step. **This doc** (`COMMIT_SCOPE_PLAN_2026-05-29.md`) → Bundle C (docs).

## Dashboard freshness (Junyan caveat, resolved 2026-05-29)

The morning-report regen only fed the *email*; the **Dashboard reads the committed static `portfolio_thesis_alignment.json`**, which would go stale. Fixed by wiring regen into the **committing** data pipeline `fetch-data.yml` (`contents: write`):
- New `Regenerate thesis alignment marker` step runs `backfill_thesis_direction.py` + `portfolio_thesis_alignment.py` AFTER `paper_trading.py` (so `positions.json` is final), before the commit step. stdlib-only, `continue-on-error`.
- The commit file-list now includes `portfolio_thesis_alignment.json` + `thesis_direction_backfill.json` → committed daily → Dashboard always fresh.
- `fetch-data.yml` added to **Bundle F**. Both surfaces now fed: Dashboard ← committed JSON (daily), morning report ← transient regen.

## Junyan's ratified decisions (2026-05-29)
1. **Bundle A = one engine commit, no split** — msg `engine: add v3 swing audit gates and hold cap`.
2. **Bundle G = canonical `*_bundle.json` + verdicts/reports only**; the 100+ raw per-window / iter JSONs → **gitignore** (added patterns below), not mainline.
3. **Branch** = `feature/core-guardrail-productionization-20260529`; create branch first, stage by bundle order; **no commit/push until explicit go**.

`.gitignore` additions (Bundle G raw artifacts kept out of mainline; canonical bundles + CORE/alignment JSONs NOT matched):
```
public/data/v3c_alpha1*_wf_*.json
public/data/v3c_alpha1*_full_*.json
public/data/iter1*_backtest_*.json
public/data/iter1*_bootstrap_*.json
```

## Open decisions for Junyan
- **Bundle A split**: one engine commit, or separate the prior arc from `max_hold`? (Recommend one — the prior arc is unlanded and my edit depends on it.)
- **Bundle G**: which experiment artifacts (if any) enter mainline vs gitignore. (Recommend: bundles only.)
- **Branch**: `git log` shows we're on `main`. Per house rule, productionization commits should go on a feature branch, not `main` directly.
