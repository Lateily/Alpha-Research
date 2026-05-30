# Codex Findings Log

> Append only. Use `## YYYY-MM-DD` date headers.
> Format: **Finding** → **Proposed fix** → **Validation run** → **Status**

---

*No entries yet. Codex: start here when you find something worth logging.*

## 2026-04-25 — Four architecture divergences found during Codex intake

**Scope**

Files checked:

- `scripts/fetch_data.py`
- `scripts/vp_engine.py`
- `public/data/watchlist.json`
- `CLAUDE.md`
- `AGENTS.md`
- `PROJECT_INSTRUCTIONS.md`

**Finding 1 — `fetch_data.py` does not load `watchlist.json`**

`grep -n "_load_watchlist" scripts/fetch_data.py` returned no output.

Evidence:

- `scripts/fetch_data.py:34` defines hardcoded `FOCUS_TICKERS`.
- `scripts/fetch_data.py:51` defines hardcoded `VP_SCORES`.
- `scripts/fetch_data.py:503`, `1050`, `1084`, `1104`, `1132`, `1175`, `1875`, `1878`, `2092`, `2169`, `2193`, `2275` continue to read from `FOCUS_TICKERS`.
- `scripts/fetch_data.py:2320` writes `vp_snapshot.json` by iterating over `VP_SCORES`.

Declared behavior in `CLAUDE.md` and `AGENTS.md`: `public/data/watchlist.json` is the single source of truth for ticker coverage and VP seed state. Actual behavior in `fetch_data.py`: ticker and seed state remain duplicated in Python dictionaries.

**Why it matters**

Adding or changing a ticker in `watchlist.json` will not fully propagate into the first pipeline step. This can silently break data fetch, rDCF generation, financial output, market data, and the initial `vp_snapshot.json` write.

**Causal status**

Causal logic is valid: a single source of truth reduces ticker divergence across scripts. The implementation is incomplete because `fetch_data.py` still has a separate ticker and VP seed source.

**Numeric status**

Specific numbers are unvalidated and duplicated. The conflict is implementation correctness, not model calibration.

**Proposed next step**

Use `experiments/fix_fetch_data.py` as a reviewable draft for replacing hardcoded `FOCUS_TICKERS` and `VP_SCORES` with values loaded from `public/data/watchlist.json`.

**Production impact**

High.

**Status**

Fixed in production on 2026-04-25. `scripts/fetch_data.py` now loads `FOCUS_TICKERS` and `VP_SCORES` from `public/data/watchlist.json`.

## 2026-04-25 — Runtime alignment check after role clarification

**Scope**

Junyan clarified Codex's main job: align ideas produced with Claude against code, deployment, and runtime behavior so that features are actually shippable and runnable.

Files/commands checked:

- `npm run build`
- `python3 scripts/verify_outputs.py`
- `src/Dashboard.jsx`
- `scripts/swing_signals.py`
- `scripts/signal_confluence.py`
- `.github/workflows/fetch-data.yml`
- `.github/workflows/deploy.yml`
- `public/data/signals_*.json`
- `public/data/confluence.json`
- `public/data/daily_decision.json`
- `public/data/position_sizing.json`
- `api/*.js`

**Finding 1 — Production build currently passes**

`npm run build` completed successfully with Vite. No JSX parse failure, dependency-lock failure, or static build blocker was observed.

Build output:

- `dist/index.html`
- `dist/assets/index-B12LWtoz.js`

There is a Vite chunk-size warning because the main bundle is ~829 kB minified / ~238 kB gzip. This is not a deployment blocker, but it confirms `Dashboard.jsx` is becoming large enough that code splitting may eventually matter.

**Status**

Passed.

**Finding 2 — v14.1 Swing Trading Signals appear wired end-to-end**

Evidence:

- `scripts/swing_signals.py` writes `public/data/signals_{safe_id}.json`.
- `.github/workflows/fetch-data.yml` runs `python scripts/swing_signals.py`.
- `.github/workflows/fetch-data.yml` commits `public/data/signals_*.json`.
- `public/data/` currently contains signal files for all five watchlist tickers.
- `src/Dashboard.jsx` defines `SwingSignalBadge`, `SwingSignalCompact`, and `SwingSignalDetail`.
- `src/Dashboard.jsx` fetches `data/signals_${id}.json` through `DATA_BASE` and maps by `ticker`.
- `scripts/signal_confluence.py` reads `public/data/signals_*.json`.

**Why it matters**

The shipped roadmap claim for v14.1 is materially supported by code, data artifacts, pipeline, and frontend consumption. This looks deployed as an actual feature rather than just a document entry.

**Causal status**

Causal logic appears valid: OHLC-derived tactical signals are generated before confluence and then rendered in the dashboard.

**Numeric status**

Specific trading thresholds remain unvalidated priors unless backed by later signal-quality history. Runtime wiring is validated; model calibration is not.

**Status**

Passed with calibration caveat.

**Finding 3 — Verification coverage has not caught up with v14.1/v13.5 modules**

`scripts/verify_outputs.py` currently checks:

- rDCF files
- stress test output
- EQR files
- prediction log

It does not yet validate:

- `signals_*.json` schema/coverage
- `confluence.json` ticker count and action schema
- `position_sizing.json` schema
- `daily_decision.json` wrongIf alert shape
- `leading_indicators.json` composite fields
- Vercel API endpoint presence for features referenced by the frontend

**Why it matters**

The platform can build while a newly shipped feature silently fails at runtime because its JSON shape changed or one pipeline step stopped writing. This is exactly the class of issue Codex should guard against.

**Proposed next step**

Add an experimental validator under `experiments/` that checks v14 output schemas and frontend/API endpoint consistency. If useful, promote that validator into `scripts/verify_outputs.py` after Junyan approval.

**Production impact**

Medium.

**Status**

Fixed in production on 2026-04-25. The stale hardcoded `VP_SCORES` block was removed from `scripts/fetch_data.py`; seeds now come from `watchlist.json`.

**Finding 4 — API base naming is inconsistent but not currently blocking GitHub Pages**

Evidence:

- `.github/workflows/deploy.yml` exports `VITE_API_BASE_URL`.
- `src/Dashboard.jsx` reads `import.meta.env.VITE_API_BASE` in some components.
- Most production API calls hardcode `https://equity-research-ten.vercel.app` or switch to it on `github.io`.
- `CLAUDE.md` says GitHub Pages should always use `https://equity-research-ten.vercel.app`.

**Why it matters**

Because the dashboard mostly hardcodes the stable Vercel base, GitHub Pages should work. But the env var mismatch means the deploy secret is misleading and any future code using `VITE_API_BASE_URL` may not affect the actual runtime.

**Proposed next step**

Standardize one helper such as `getApiBase()` in `Dashboard.jsx`, or at minimum standardize env naming/documentation. Production behavior should remain: GitHub Pages uses `https://equity-research-ten.vercel.app`.

**Production impact**

Low to medium. Not a current build blocker, but easy to create future runtime drift.

**Status**

Partially fixed in production on 2026-04-25. `scripts/fetch_data.py` now writes both `catalyst_prox` and the existing downstream-compatible `catalyst_proximity`. Full canonicalization across the pipeline remains open.

**Validation run**

- `npm run build` passed.
- `python3 scripts/verify_outputs.py` passed for its current covered outputs.
- Manual search confirmed frontend/API/pipeline references for swing signals and Vercel endpoints.

**Validation run**

- `grep -n "_load_watchlist" scripts/fetch_data.py` returned no output.
- `rg -n "FOCUS_TICKERS|VP_SCORES|catalyst_prox|catalyst_proximity|watchlist" scripts/fetch_data.py` confirmed hardcoded ticker and VP seed usage.
- `python3 experiments/fix_fetch_data.py` generated `experiments/fetch_data.watchlist_proposed.py` from 5 watchlist tickers without modifying production files.
- `PYTHONPYCACHEPREFIX=/tmp/codex_pycache python3 -m py_compile experiments/fix_fetch_data.py experiments/fetch_data.watchlist_proposed.py` passed. A first compile attempt without `PYTHONPYCACHEPREFIX` failed because macOS Python tried to write bytecode under `/Users/years/Library/Caches`, which is outside the allowed write area.

**Finding 2 — `VP_SCORES` seed values diverge from `watchlist.json`**

Evidence:

- `scripts/fetch_data.py:53` has `300308.SZ` `narrative_shift=65`, `low_coverage=55`, `catalyst_prox=85`.
- `public/data/watchlist.json:26-28` has `300308.SZ` `narrative_shift=72`, `low_coverage=50`, `catalyst_prox=80`.
- `scripts/fetch_data.py:55` has stale `300308.SZ` wrongIf text: `1.6T qualification slips to Q4 2025 OR hyperscaler CapEx cut >20%`.
- `public/data/watchlist.json:30` has current `300308.SZ` wrongIf text: `1.6T mass production delayed beyond Q3 2026 OR NVDA+MSFT+GOOGL stock prices collectively drop >25% from ATH within 1 quarter`.
- `scripts/fetch_data.py:2320-2352` writes snapshot fields from `VP_SCORES` if existing snapshot values are not preserved.

**Why it matters**

`fetch_data.py` runs before `vp_engine.py`. If `vp_engine.py` fails, partially runs, or does not overwrite every field, stale seeds and wrongIf strings can enter `vp_snapshot.json` and downstream outputs.

**Causal status**

Causal logic is valid: stale seed inputs can propagate into model outputs when upstream pipeline steps write snapshots before later correction steps.

**Numeric status**

Specific score differences are unvalidated duplicated state. The issue is silent data drift between two supposed sources of truth.

**Proposed next step**

Eliminate `VP_SCORES` as a separate hardcoded source. Load `vp_seed` from `watchlist.json` in `fetch_data.py`.

**Production impact**

High.

**Status**

Open.

## 2026-05-30 — Alpha Factory v0 Screen Queue Review

**Finding 2026-05-30-A — `core_candidate_funnel.py` does not enforce the PIT ann_date buffer gate**

Evidence:

- `docs/strategy/CORE_ALPHA_FACTORY_v0_SPEC.md` requires fundamental inputs to be "announced fundamentals only, lagged by announcement date plus an explicit buffer."
- `scripts/core_candidate_funnel.py` reads `financials.parquet` and groups by ticker, but does not filter financial rows by `ann_date <= as_of - buffer`.
- Current local data happens to have no rows with `ann_date > as_of` (`as_of=20260526`, max `ann_date=20260521`), so the current output is not contaminated by future announcements. The implementation is still missing the required hard gate.

Why it matters:

The screen is intended to become a repeatable pipeline. Without an explicit PIT filter and buffer, a future data refresh or historical rerun can silently include financial data that would not have been tradable at the screen date.

Causal logic is valid because unfiltered announcement dates are a direct look-ahead risk for any fundamental acceleration score.

Specific numbers are validated against the local panel for this run only: future-announcement rows are currently zero. The missing buffer is a schema/gate correctness issue, not a calibrated threshold.

Proposed fix:

In `fin_features(as_of)`, parse `ann_date`, apply `ann_date <= as_of - PIT_BUFFER_DAYS`, sort by `ts_code/end_date/ann_date`, and keep the latest announced row per fiscal period. Expose `pit_buffer_days` and `max_ann_date_used` in output metadata or `data_quality`; add a selftest where a future-announced financial row is ignored.

Production impact: High for correctness, low implementation cost.

**Resolution (Claude, 2026-05-30) — fix applied, awaiting re-review:**

- Added pure helper `pit_filter(f, as_of, buffer_days=PIT_BUFFER_DAYS)` (`PIT_BUFFER_DAYS=1`): parses `ann_date` (robust to int/float/str), keeps only `ann_date <= as_of - buffer`, sorts `[ts_code, end_date, _ann]` and `drop_duplicates(["ts_code","end_date"], keep="last")` → latest announced version per fiscal period (restatement-correct); rows with unparseable/missing `ann_date` are dropped (can't prove public). Returns `(filtered_frame, max_ann_date_used)`.
- `fin_features(as_of)` now calls `pit_filter` BEFORE any scoring and returns `max_ann_used`; `screen()` surfaces `pit_buffer_days`, `max_ann_date_used`, and a `pit_note` in `_meta`.
- `--selftest` adds 4 PIT cases: (1) future-announced row (ann 20260825 > cutoff) filtered out; (2) `max_ann_date_used` correct; (3) restatement → latest announced kept; (4) same-day `ann==as_of` rejected by the buffer.
- Verified wired (not vacuous): `fin_features` at as_of {20240101, 20250101, 20260526} → `max_ann_date_used` {20231231, 20241231, 20260521}, all ≤ cutoff. Output on current (already-clean) data byte-identical → guard, not behavior change. Protected paper-state byte-unchanged.

Resolution observed 2026-05-30:

- `scripts/core_candidate_funnel.py` now applies `pit_filter()` before any financial scoring.
- `PIT_BUFFER_DAYS=1`, `pit_buffer_days`, `max_ann_date_used`, and `pit_note` are exposed in output metadata.
- Selftest covers future-announced rows, same-day rejection, and restatement/latest-announced selection.
- Re-review showed `max_ann_date_used=20260521` with `as_of=20260526` and cutoff `20260525`; protected files remained unchanged.

Status: Resolved locally; pending integration commit.

**Finding 2026-05-30-B — `core_thesis_queue.py` stable identity ignores catalyst/wrong_if edits**

Evidence:

- `scripts/core_thesis_queue.py` hashes `catalyst` and `wrong_if` in `HASH_FIELDS`.
- Its append-only dedup identity (`ID_FIELDS`) excludes `catalyst`, `wrong_if`, and `benchmark_basket_id`.
- Constructed test: an existing 700.HK hypothesis with `catalyst=old/wrong_if=old` and a new same ticker/date/pipeline/direction hypothesis with `catalyst=NEW/wrong_if=new` produce different `hypothesis_lock_hash` values, but the same `stable_identity`; `merge_append_only()` keeps length 1 and adds 0.

Why it matters:

If a structured thesis is corrected or materially edited under the same source date/pipeline, the registry silently treats it as already registered instead of appending a new locked hypothesis. That violates the append-only pre-registration discipline.

Causal logic is valid because a changed catalyst/wrong-if changes the hypothesis being tested. The registry must not discard such changes as a no-op.

Specific numbers are validated by a local constructed unit case; no investment thresholds are involved.

Proposed fix:

Define stable identity as the canonical hash input excluding only `registered_at` (and excluding `hypothesis_lock_hash` itself). At minimum include `catalyst`, `wrong_if`, `benchmark_basket_id`, and `theme_bucket` in `ID_FIELDS`. Add a selftest where edited catalyst/wrong_if appends a second entry.

Production impact: High for registry correctness, low implementation cost.

**Resolution (Claude, 2026-05-30) — fix applied, awaiting re-review:**
`ID_FIELDS` is now defined as `[f for f in HASH_FIELDS if f != "registered_at"]` — i.e. the full hashed content minus only the timestamp. catalyst, wrong_if, benchmark_basket_id, theme_bucket (and the new tier/BY fields) are all part of stable identity now, so a materially edited hypothesis under the same ticker/date/pipeline/direction yields a new identity and APPENDS as a new locked hypothesis. `--selftest` adds: edited `catalyst` → len 2 / added 1; edited `wrong_if` → len 2 / added 1. Verified on the real registry. Idempotence preserved (same-content rerun still byte-identical across dates).

Status: Resolved locally; pending re-review + integration commit.

**Finding 2026-05-30-C — validation/BY sample membership is mutable without hash failure**

Evidence:

- `scripts/core_thesis_queue.py` uses `counts_toward_validation` and `validation_role` to decide whether a thesis enters the BY family sample.
- These fields are not in `HASH_FIELDS`.
- Constructed test: toggling an existing queue row from `counts_toward_validation=true` / `directional` to false / `observer_control` leaves `verify(row)` returning true.

Why it matters:

The pre-registration hash protects the hypothesis content, but not the statistical sample membership. A post-hoc edit could change BY `m` or include/exclude an observer entry without tripping tamper detection.

Causal logic is valid because validation membership directly controls multiple-testing correction and verdict eligibility.

Specific numbers are validated by a local constructed unit case; no investment thresholds are involved.

Proposed fix:

Include `counts_toward_validation`, `validation_role`, and preferably `evidence_tier` in the locked canonical record. Add selftests that toggling validation membership or evidence tier breaks `verify()`.

Production impact: High for validation integrity, low implementation cost.

**Resolution (Claude, 2026-05-30) — fix applied, awaiting re-review:**
`counts_toward_validation`, `validation_role`, and `evidence_tier` are now in `HASH_FIELDS`, so BY-sample membership and tier are inside the lock. Toggling any of them post-hoc breaks `verify()`. `--selftest` tamper coverage extended from 6 → 9 fields (adds the three above); verified on the real registry that toggling `counts_toward_validation` / `validation_role` / `evidence_tier` each returns `verify=False`. Note: because the lock definition changed, pre-existing registry rows were regenerated once under the new definition (nothing was committed yet).

Status: Resolved locally; pending re-review + integration commit.

---

## 2026-05-28 - Swing Backtest R0/R1/R2 Findings

### Finding 1 - v1 10yr alpha was a cash-adjusted benchmark artifact

Evidence:

- Recomputed audit fields show iter-13 10yr avg gross around 3.1%, iter-16 10yr avg gross around 1.9%, and iter-16 20yr avg gross around 2.4%.
- The benchmark was effectively 100% invested equal-weight liquid universe, while the strategy was mostly cash.
- The apparent 10yr alpha came from avoiding a weak benchmark, not from stock selection.

Causal logic is valid: comparing a mostly-cash strategy with a fully invested equity benchmark can make low exposure look like alpha during weak benchmark regimes.

Specific numbers are validated against the local backtest outputs inspected on 2026-05-28. They are diagnostic, not investment-calibrated.

Status: confirmed.

### Finding 2 - v1 position cap was not enforcing total holdings

Evidence:

- iter-13 mini1yr reached 37 positions while the spec cap was 12.
- The engine capped new picks, but did not cap total active holdings after prior positions carried forward.
- `scripts/run_swing_backtest_fast.py --selftest` now includes a max-position invariant.

Causal logic is valid: if carried positions do not consume new-pick slots, the book can exceed its intended risk and diversification constraints.

Specific numbers are validated against local output files and the selftest. The fix is implementation-level, not a calibrated strategy parameter.

Status: fixed locally in `scripts/run_swing_backtest_fast.py`, not committed.

### Finding 3 - R1 negative IC is real as a diagnostic, but not directly tradable

Evidence:

- R1 20yr diagnostics show negative 5d IC across the current v1 factor surface:
  - `momentum_5d`: mean IC -0.0636, t -27.99.
  - `volume_spike`: mean IC -0.0406, t -25.33.
  - `breakout_20d`: mean IC -0.0350, t -23.76.
  - `rsi_in_band`: mean IC +0.0135, t +8.63.
- `momentum_5d`, `breakout_20d`, `volume_spike`, and `limit_up_followup` had negative 5d yearly sign in 21 of 21 years.

Causal logic is unestablished: rank IC says the factor ordering is predictive in-sample over the available panel, but it does not identify the economic cause or guarantee a portfolio can monetize it after constraints.

Specific numbers are validated by `scripts/swing_factor_diagnostics.py` outputs under `experiments/agent_tasks/`. Sector-neutral diagnostics are still missing.

Status: confirmed diagnostic, not a trading rule.

### Finding 4 - Path B weekly inverse should be rejected in current form

Evidence:

- Experimental harness: `experiments/swing_path_b_backtest.py`.
- Report: `experiments/agent_tasks/r2_path_b_report.md`.
- Same-gross alpha was negative in every tested configuration:
  - mini1yr, top300, 8 positions, hold 5d: -21.52%, CI [-36.98%, -2.39%].
  - 10yr, top300, 8 positions, hold 5d: -11.18%, CI [-19.49%, -1.71%].
  - 20yr, top300, 8 positions, hold 5d: -4.40%, CI [-11.49%, +3.57%].
  - 10yr, top500, 30 positions, hold 5d: -9.53%, CI [-13.97%, -4.96%].

Causal logic is questionable: inverse 5d momentum has strong negative rank IC, but selecting extreme losers into a concentrated long-only weekly basket loses to a same-gross liquid benchmark after execution, stops, and turnover.

Specific numbers are validated against the local experimental harness and current local panel. They are not production-calibrated thresholds.

Status: reject current Path B; next research should start from decile/quintile portfolio diagnostics and turnover-aware breadth, not stock-picking optimization.

### Finding 5 - Official iter-17 R2 also fails the v2 gate

Evidence:

- Official outputs observed:
  - `public/data/iter17_r2_backtest_mini1yr.json`
  - `public/data/iter17_r2_backtest_10yr.json`
  - `public/data/iter17_r2_backtest_20yr.json`
- Mini1yr: CAGR +2.14%, same-gross alpha -31.38%, CI [-51.10%, -3.63%], p=0.0308.
- 10yr: CAGR -2.86%, avg gross 4.5%, median positions 0, same-gross alpha -1.29%, CI [-19.53%, +21.81%].
- 20yr: CAGR -0.22%, avg gross 4.7%, median positions 0, same-gross alpha +16.05%, CI [-4.83%, +41.99%].
- Position cap gate passed in observed runs: max positions reached 8 against config 8.

Causal logic is questionable because a mostly-cash strategy with median zero positions cannot be treated as a robust tradable edge without stable same-gross alpha and sufficient active exposure.

Specific numbers are validated against official local iter-17 R2 JSON outputs observed on 2026-05-28. They are not production-calibrated thresholds.

Status: official R2 reject; continue with lower-level decile/quintile diagnostics.

### Finding 6 - Reversal exists as a spread, not yet as long-only alpha

Evidence:

- R3 pure factor study: `experiments/agent_tasks/r3_reversal_decile_study_20yr.md`.
- `momentum_5d`, 5d decile:
  - bottom-EW annualized +9.88% before cost.
  - net bottom-EW annualized -5.54%, CI [-11.78%, +0.73%].
  - sector-neutral bottom-top spread +56.81%, CI [+40.21%, +75.50%].
- `momentum_20d`, 10d decile:
  - bottom-EW annualized +11.34% before cost.
  - net bottom-EW annualized +3.26%, CI [-2.38%, +9.78%].
  - sector-neutral bottom-top spread +45.12%, CI [+29.16%, +64.34%].

Causal logic is unestablished because the broad spread may come from reversal, sector rotation, limit mechanics, or crash rebound dynamics. It does not prove a long-only implementation can harvest the effect.

Specific numbers are validated against the local R3 decile/quintile harness and current local panel. They are not production-calibrated thresholds.

Status: keep swing as R&D; test whether iter-18 ablations can convert spread into long-only same-gross alpha.

### Finding 7 - iter-18 ablations do not rescue Path B

Evidence:

- Full ablation report: `experiments/agent_tasks/iter18_swing_ablation_full.md`.
- Walk-forward report: `experiments/agent_tasks/iter18_b1_b3_walkforward.md`.
- B1 4-factor did not pass:
  - mini1yr same-gross alpha -20.61%, CI [-52.22%, +37.31%].
  - 10yr same-gross alpha -3.28%, CI [-19.46%, +16.60%].
  - 20yr same-gross alpha +19.73%, CI [-2.63%, +47.31%].
- B2 gross80 did not pass:
  - mini1yr same-gross alpha -31.38%, CI [-51.10%, -3.62%].
  - 10yr same-gross alpha -1.40%, CI [-19.61%, +21.73%].
  - 20yr same-gross alpha +16.25%, CI [-4.67%, +42.23%].
- B3 no ATR veto did not pass:
  - mini1yr same-gross alpha -45.81%, CI [-66.12%, -14.01%].
  - 10yr same-gross alpha -5.10%, CI [-21.90%, +15.46%].
  - 20yr same-gross alpha +20.57%, CI [-2.85%, +50.85%].
- B1+B3 was the only full-window positive:
  - 20yr same-gross alpha +37.85%, CI [+6.63%, +78.68%].
  - But mini1yr alpha -36.08%, CI [-59.67%, +3.44%].
  - 10yr alpha -3.44%, CI [-19.90%, +16.78%].
- Walk-forward on B1+B3 failed:
  - 2006-2010 and 2010-2014 positive point estimates but CI crossed zero.
  - 2014-2018 and 2018-2022 negative point estimates.
  - 2022-2026 same-gross alpha -28.44%, CI [-46.03%, -5.94%], p=0.0161.

Causal logic is questionable because the only full-sample positive result does not survive subperiod validation and is significantly negative in the most recent window.

Specific numbers are validated against local iter-18 ablation outputs and current local panel. They are not production-calibrated thresholds.

Status: reject Path B as a strategy candidate; keep only lower-level factor R&D if desired.

**Finding 3 — `catalyst_prox` and `catalyst_proximity` are both active field names**

Evidence:

- `public/data/watchlist.json:12` documents `catalyst_prox`.
- `public/data/watchlist.json:28`, `53`, `79`, `103`, `127` use `catalyst_prox` in `vp_seed`.
- `scripts/fetch_data.py:53`, `58`, `63`, `68`, `73` use `catalyst_prox` in `VP_SCORES`.
- `scripts/fetch_data.py:2346` writes `catalyst_proximity` into `vp_snapshot.json`.
- `scripts/vp_engine.py:37` uses `catalyst_proximity` in `VP_WEIGHTS`.
- `scripts/vp_engine.py:74`, `98` translate watchlist `catalyst_prox` into snapshot `catalyst_proximity`.

**Why it matters**

The current bridge works only because scripts manually translate between two names. Any new script or dashboard component can easily read the wrong field and default to 50 or stale data.

**Causal status**

Causal logic is valid: duplicated field names create schema drift risk and can silently alter VP Score if one side is missing.

**Numeric status**

Specific numbers are unvalidated. The field-name issue is schema correctness.

**Proposed next step**

Choose one canonical field name. Claude's current proposed direction is `catalyst_prox` across the chain, with a temporary backward-compatible alias only if needed during migration.

**Production impact**

Medium.

**Status**

Open.

**Finding 4 — `PROJECT_INSTRUCTIONS.md` still describes old VP math**

Evidence:

- `PROJECT_INSTRUCTIONS.md:147` begins B3 VP decomposition.
- `PROJECT_INSTRUCTIONS.md:148-150` says `Expectation Gap 30%`, `Fundamental Accel 25%`, `Narrative Shift 20%`, `Low Coverage 15%`, `Catalyst Proximity 10%`.
- `PROJECT_INSTRUCTIONS.md:151` says `EGS formula: 50 + 50 × tanh(delta / 0.20)`.
- Current authoritative context in `CLAUDE.md:100-108` says VP Score uses `25/25/20/15/15`.
- Current implementation in `scripts/vp_engine.py:32-38` uses weights `0.25`, `0.25`, `0.20`, `0.15`, `0.15`.
- Current implementation in `scripts/vp_engine.py:249-304` maps rDCF delta through a piecewise table, not the tanh formula.

**Why it matters**

`PROJECT_INSTRUCTIONS.md` is a prompt/protocol artifact. If Claude or another agent uses it for analysis, it can produce VP calculations and explanations that disagree with production logic.

**Causal status**

Causal logic is valid: prompt drift can produce analysis drift. The production engine and project instructions disagree.

**Numeric status**

Specific numbers in `PROJECT_INSTRUCTIONS.md` are stale. Current production numbers are still unvalidated priors, but the documentation should match implementation.

**Proposed next step**

Draft an update to B3 under `experiments/` and only edit `PROJECT_INSTRUCTIONS.md` after Junyan approval.

**Production impact**

Medium.

**Status**

Open.
