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
