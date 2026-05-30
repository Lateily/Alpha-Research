# CORE Alpha Factory v0 Spec

Date: 2026-05-30
Status: PRE-IMPLEMENTATION SPEC
Scope: produce, pre-register, validate, and cull CORE thesis candidates.

This document is the contract for the next CORE build. It is not a trading
system. It creates a research and validation factory that can produce more
directional samples without weakening the statistical discipline built during
the Path B audit.

## 1. Problem

The current platform has a strong validation machine but weak input flow:

- Existing CORE theses are young and sparse.
- Most historical thesis records were filed as PASS, even when the text held a
  weaker directional view suitable for forward validation.
- Current paper P&L is concentrated in one name and is not proof of repeatable
  thesis skill.
- Path B inverse-momentum has been retired; the useful asset from that work is
  the validation discipline, not the signal.

The factory fixes the input side:

```text
screen candidates -> generate thesis -> pre-register hypothesis -> track forward
returns -> score theme-adjusted residual -> cull or promote
```

## 2. Hard Boundaries

- No auto-trading.
- No auto-closing.
- No position sizing changes.
- Every generated candidate and every shadow book carries `no_trade_flag: true`.
- Human review is required before any portfolio action.
- WATCH labels are validation labels only. They are not capital-directional
  orders.
- `screen_queue` may scan outside `watchlist.json` because discovery is the
  factory's purpose. This is a conscious exception to the current
  watchlist-only production ticker rule. It does not add names to the live
  trading universe.
- Peer baskets may hardcode attribution-only tickers. They are benchmark
  definitions, not pipeline ticker additions, not tradeable candidates, and not
  a replacement for `watchlist.json`.

Causal logic is valid because the previous guardrail found an actual process
failure: research direction and portfolio direction can diverge invisibly unless
the system marks the divergence. Specific future alpha numbers are unvalidated.

## 3. Factory Discipline

The factory increases hypothesis count. Without a matching gate, it becomes a
false-positive machine.

Hard rules:

1. Every thesis candidate must be pre-registered before forward returns accrue.
2. Every registered thesis gets:
   - `hypothesis_family_id`
   - `hypothesis_lock_hash`
   - `registered_at`
   - `direction_label`
   - `horizon_days`
   - `catalyst`
   - `wrong_if`
   - `benchmark_basket_id`
   - `theme_bucket`
   - `evidence_tier`
   - `no_trade_flag: true`
3. Validation uses theme/peer-adjusted residual, not raw return and not only
   broad-index alpha.
4. Family-level verdicts use BY-family correction across all pre-registered
   thesis families whose forward data has resolved at the evaluated horizon.
5. A positive single-name or single-regime point estimate is not enough for a
   capital verdict.
6. Fundamental inputs used by screening or validation must be PIT-safe:
   announced fundamentals only, lagged by announcement date plus an explicit
   buffer. No forward-filled future financial data may enter a historical
   screen, thesis validation, or residual attribution.

Specific thresholds in this spec are v0 operating rules and are unvalidated
intuitions unless explicitly marked otherwise.

## 3.1 Cull / Promote Rule

v0 does not promote any family to capital.

All thesis families remain `PENDING` until enough forward data matures. The
first meaningful review window is expected around the 60d to 120d horizons of
the first registered batch, roughly August to November 2026 for a late-May 2026
start.

Until that sample matures:

- no family is promoted to capital,
- no family is retired solely because an early 5d/20d print is weak,
- no positive early print is treated as validated alpha.

Future cull/promote criteria must be written before the first mature sample is
judged. The criteria must include:

- sample-size minimum,
- theme/peer residual threshold,
- BY-family corrected significance or explicit "insufficient statistical
  power" status,
- hit-rate / IC consistency,
- wrong-if resolution handling,
- and a retirement path for families that repeatedly fail after enough samples.

This is the CORE equivalent of the Path B alpha1.x STOP discipline.

## 4. Two-Layer Funnel

### 4.1 `screen_queue`

Purpose: find names worth researching.

Allowed source: full-market A-share data and existing watchlist/HK names.

This layer does not require a generated thesis and does not enter validation.
It is attention ranking only.

Minimum hard filters:

- Exclude ST, *ST, delisting, and suspended/no-price names.
- Listing age >= 252 trading days. If `list_date` is unavailable, derive it
  from the first available `trade_date` in the PIT price panel.
- Float market cap >= CNY 3B.
- 20d median turnover amount >= CNY 30M.
- PE > 0 unless explicitly tagged `event_exception`. v0 treats
  `event_exception` as a manual override and defaults to exclusion.
- Enough price history for 20d, 60d, and 120d forward validation.

Score v0:

| Component | Weight | Validation Status |
|---|---:|---|
| expectation / revision signal | 25 | unvalidated intuition |
| fundamental acceleration | 20 | unvalidated intuition |
| catalyst proximity | 20 | unvalidated intuition |
| coverage gap / attention inflection | 15 | unvalidated intuition |
| value + low-vol sanity | 10 | unvalidated intuition |
| liquidity / risk sanity | 10 | unvalidated intuition |

`screen_queue` output schema:

```json
{
  "ticker": "300308.SZ",
  "name": "Innolight",
  "market": "A",
  "screen_rank": 1,
  "screen_score": 78.2,
  "score_components": {},
  "hard_filter_passed": true,
  "data_quality": {
    "price_history_days": 5000,
    "financial_history_rows": 40,
    "sidecar_coverage": "watchlist_only | full_market | missing"
  },
  "recommended_research_action": "RUN_THESIS | WATCH_DATA | SKIP",
  "no_trade_flag": true
}
```

### 4.2 `thesis_queue`

Purpose: hold forward-validatable hypotheses after thesis generation.

Only this layer enters validation families.

Required schema:

```json
{
  "ticker": "300308.SZ",
  "name": "Innolight",
  "registered_at": "2026-05-30T00:00:00Z",
  "hypothesis_family_id": "core_factory_v0_cpo_20260530",
  "hypothesis_lock_hash": "sha256-of-canonical-hypothesis-json",
  "direction_label": "LONG | SHORT | WATCH_LONG | WATCH_SHORT | PASS | UNRESOLVED",
  "horizon_days": 60,
  "catalyst": "specific named event/window",
  "wrong_if": ["specific falsifier 1", "specific falsifier 2"],
  "benchmark_basket_id": "cpo_optical_v0",
  "theme_bucket": "CPO_OPTICAL",
  "evidence_tier": "E1 | E2 | E3 | E4",
  "validation_status": "PENDING | RESOLVED | EXPIRED",
  "no_trade_flag": true
}
```

## 5. WATCH Emission Taxonomy

Implementation target: keep legacy `_direction` and add
`_validation_direction`.

Legacy field:

```json
"_direction": "LONG | SHORT | PASS"
```

New field:

```json
"_validation_direction": "LONG | SHORT | WATCH_LONG | WATCH_SHORT | PASS | UNRESOLVED"
```

Capital `LONG` / `SHORT` requires all of:

- E1 structural base.
- Forward claim honestly tiered E1/E2.
- Named catalyst and named wrong-if.
- Reward:risk >= 2:1.
- Confidence >= 60.
- Rule X passes.
- No evidence-tier overstatement.

`WATCH_LONG` / `WATCH_SHORT` requires all of:

- One-sided business mechanism exists.
- Required fields present: catalyst, horizon, proves_right_if, proves_wrong_if,
  confidence, evidence, numeric reward:risk.
- Numeric reward:risk >= 1.5:1.
- Evidence mostly E1/E2, but missing at least one requirement for capital
  `LONG` / `SHORT`.
- Explicit `[unvalidated forward candidate]` note.
- `no_trade_flag: true`.

`UNRESOLVED` if:

- Direction is ambiguous.
- Both-sided conditional is symmetric.
- Required fields are missing.
- Numeric reward:risk exists but direction language is not one-sided.

`PASS` if:

- no edge despite data,
- insufficient data,
- balanced risk/reward,
- catalyst not yet observable,
- or explicit no-position / capital-preservation logic.

The generation-side rule must stay consistent with
`scripts/backfill_thesis_direction.py`, so historical backfilled records and
future native records land in the same validation taxonomy.

## 6. Peer / Theme Residual Attribution

Purpose: separate thesis skill from broad market and theme beta.

The v0 peer definitions are explicit white lists. They are
`[unvalidated peer definition]` and are attribution-only, never selection rules.

If fewer than 4 usable peers have prices, emit:

```json
"benchmark_status": "proxy_or_missing"
```

No silent fallback.

### 6.1 Baskets

| Basket ID | Theme | Tickers |
|---|---|---|
| `cpo_optical_v0` | CPO / optical module | `300308.SZ`, `300394.SZ`, `300502.SZ`, `002281.SZ`, `000988.SZ`, `300548.SZ`, `300570.SZ`, `301205.SZ`, `688205.SH`, `688498.SH` |
| `hk_internet_gaming_v0` | HK internet / gaming | `700.HK`, `9999.HK`, `9988.HK`, `3690.HK`, `1024.HK`, `9618.HK`, `9626.HK`, `0777.HK`, `2400.HK` |
| `auto_ev_v0` | Auto / EV | `002594.SZ`, `175.HK`, `1211.HK`, `2015.HK`, `9866.HK`, `9868.HK`, `000625.SZ`, `601633.SH`, `600104.SH`, `601127.SH` |
| `pharmacy_retail_v0` | Pharmacy retail | `603233.SH`, `603939.SH`, `603883.SH`, `002727.SZ`, `605266.SH`, `000705.SZ` |
| `hk_biotech_v0` | HK biotech | `6160.HK`, `1177.HK`, `2269.HK`, `2359.HK`, `1877.HK`, `9969.HK`, `2696.HK` |

### 6.2 Data Readiness

Verified before implementation:

- A-share basket peers are covered in local price panel:
  - CPO: 10/10
  - Pharmacy: 6/6
  - Auto A-share peers: 5/5
- HK basket peers require extending `scripts/fetch_hk_prices.py`.
- Current `concept_membership.json` does not provide enough direct CPO,
  gaming, pharmacy, or biotech coverage for v0 basket construction.

## 7. Candidate Data Readiness

Verified before implementation:

- `data_history/panel/daily_prices.parquet`: A-share daily price/volume panel.
- `data_history/panel/financials.parquet`: PIT-style financial rows.
- `data_history/panel/hk_prices.parquet`: current HK focus set, not full HK
  peer universe.
- `public/data/universe_a.json`: 5,850 A-share names, but `roe` and
  `gross_margin` are currently empty in the snapshot. Quality must be derived
  from financials, not this snapshot.
- Sidecars are watchlist-only today: consensus, broker, inst, quant factors,
  top-inst-like files cover roughly the watchlist set, not full market.

Consequence: v0 can build a full-market A-share `screen_queue`, but the enriched
`thesis_queue` must start from names that have generated thesis records or must
trigger a research run before validation.

## 8. Validation Metrics

For every registered thesis:

- raw return over 20d / 60d / 120d,
- broad-index alpha,
- theme/peer residual,
- hit rate by direction,
- rank IC by thesis quality score versus residual,
- bootstrap confidence intervals where sample size allows,
- BY-family corrected p-value over all pre-registered thesis families whose
  forward data has resolved at the evaluated horizon.

Minimum reporting rule:

- If n < 8 resolved directional theses, emit `INSUFFICIENT_SAMPLE`.
- If theme benchmark is missing, emit `BENCHMARK_INCOMPLETE`.
- If BY-family correction is not available, emit `STAT_GATE_INCOMPLETE`.
- If any fundamental input lacks PIT-lag proof, emit `PIT_GATE_INCOMPLETE`.

## 9. Implementation Sequence

Branch: `feature/core-alpha-factory-v0`

1. Spec doc only. This file.
2. WATCH emission in `api/research-multi.js`.
3. Peer-basket residual attribution:
   - A-share baskets first.
   - Extend HK fetch list before HK basket attribution.
4. Candidate queue:
   - `screen_queue` first.
   - `thesis_queue` only after research generation/pre-registration.
5. Shadow thesis-aligned portfolio:
   - read-only,
   - no trade actions,
   - compare current paper, thesis-aligned, equal-weight candidates, and
     benchmarks.

## 10. Acceptance Gates

Spec gate:

- This document is reviewed and ratified before code changes.

WATCH gate:

- `_validation_direction` is emitted without breaking existing `_direction`.
- Backfill taxonomy and future-native taxonomy produce compatible labels.
- WATCH outputs include `[unvalidated forward candidate]`.

Residual gate:

- At least all A-share baskets emit theme residuals.
- HK baskets emit either valid residuals or explicit `proxy_or_missing`.
- No benchmark silently falls back to a broad index without status.

Factory gate:

- Every `thesis_queue` item has `hypothesis_lock_hash`.
- Every output has `no_trade_flag: true`.
- No script writes `positions.json`, `analytics.json`, or `snapshots.json`.

Stat gate:

- Verdicts use theme/peer residual as the primary metric.
- BY-family correction spans all pre-registered thesis families whose forward
  data has resolved at the evaluated horizon.
- Small-n outputs are marked insufficient instead of interpreted as alpha.
- All fundamental inputs are PIT-lagged by announcement date plus buffer; no
  look-ahead fundamentals enter screen or validation.

## 11. Open Issues

1. Whether HK peer prices should be fetched by expanding
   `scripts/fetch_hk_prices.py` or by adding a separate `fetch_hk_peer_prices.py`.
2. Whether screen weights should remain fixed v0 intuitions or be learned only
   after the first 60-120d forward sample matures.
3. Whether `candidate_queue.json` belongs in `public/data` or a non-public
   research artifact path.
4. Whether peer baskets should later be generated from concept/industry data
   once a cleaner taxonomy source is available.
