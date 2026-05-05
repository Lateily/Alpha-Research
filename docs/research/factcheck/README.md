# Thesis Fact-Check — Pilot Series

> **Purpose:** First attempt at investment-quality validation that
> `THESIS_QUALITY_AUDIT_RERUN_2026-05-05.md` §8 flagged as the
> deferred work. Structural validator (api/research.js
> `validateThesisQuality`) checks schema compliance — it does NOT
> cross-check claims against ingested data. This dir contains
> the manual cross-check pilots.

## Method (single ticker pilot)

1. `curl POST /api/research` for one ticker — capture full thesis JSON
   (Pass-2 output) including `data._quality` from the structural
   validator.
2. Save the raw thesis JSON next to the report: `<ticker>_thesis_<date>_<time>.json`
   (auditable artifact).
3. Extract numerical claims by traversing the thesis schema. Categorise
   each: `VERIFIABLE` against connected data, `UNVERIFIABLE` from
   current sources.
4. For `VERIFIABLE` claims, cross-check against:
   - `public/data/fin_<TICKER>.json` (yfinance annual income / balance / cash flow)
   - `public/data/market_data.json` (yahoo live price + fundamentals)
   - `public/data/consensus_forecast/<TICKER>.json` (Tushare consensus, A-share only)
   - `public/data/edgar_<TICKER>.json` (US filings, US tickers only)
5. Compute Δ% (where applicable) + assign `MATCH` (within ±5%) /
   `MISMATCH` (>5%) / `ANOMALY` (categorical, e.g. wrong sign or wrong
   temporal direction) / `UNVERIFIABLE`.
6. Document findings: per-claim table + systemic gaps surfaced.

## What the pilot is NOT

- NOT a tool. This is manual cross-check. Building a script
  (`scripts/thesis_factcheck.py`) is a future KR scoped from pilot
  findings, not from speculation.
- NOT exhaustive. A pilot examines ONE thesis on ONE ticker at ONE
  point in time. Generalisable findings need ≥ 5 pilots.
- NOT investment-quality validation by itself. It surfaces
  factual-correctness issues that are NECESSARY but NOT SUFFICIENT
  for investment quality. Mechanism logic / contrarian-ness /
  variant-view truthfulness are still expert-review territory.
- NOT auto-scored. Avoid producing a single "fact-check score"
  that would create a new Goodhart target. Output is per-claim
  status, surface-area findings, no composite.

## Pilots in this directory

| File | Ticker | Date | Outcome |
|---|---|---|---|
| [700HK_pilot_2026-05-05.md](700HK_pilot_2026-05-05.md) | 700.HK (Tencent) | 2026-05-05 | 4 VERIFIED + 2 ANOMALY + 4 UNVERIFIABLE; structural validator scored 90/100 PASS but did not catch temporal anomaly nor "trailing P/E mislabelled as forward" |

## Why this exists in `docs/`, not `scripts/`

This is investigation, not production code. When findings stabilise
across N≥3 pilots and the methodology is robust, then promote the
common path into `scripts/thesis_factcheck.py` and integrate into
the pipeline. Until then, manual is the right pace — matches Junyan's
"don't build for building's sake" principle.
