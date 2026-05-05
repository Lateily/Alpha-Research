# Thesis Attribution — Bridge 8 Scaffold

> **Purpose:** Capture the falsifiable structure of every shipped thesis at
> ship-time so we can attribute outcomes when wrongIf/rightIf conditions
> resolve. This is the data layer for Bridge 8 (backtest attribution).
>
> **Status:** SCAFFOLD ONLY — captures structure, no outcome tracking yet.

## Why this exists

`THESIS_QUALITY_AUDIT_RERUN_2026-05-05.md` §8.4 listed 4 things needed for
real investment-quality validation:

1. **Bridge 8 backtest attribution** — n ≥ 10 thesis-driven trades with
   tracked entry / exit / outcome, then hit-rate by thesis-quality bucket.
   *(THIS DIR — scaffold only)*
2. Franky expert manual review *(REVIEW_REQUEST.md, separate channel)*
3. Cross-fact-check thesis numerics vs filings *(FC.1 + FC.2 — partial coverage)*
4. wrongIf condition tracking — for each shipped thesis, log the exact
   wrongIf condition and check at horizon whether it triggered.
   *(THIS DIR captures the conditions; outcome-tracker is future work)*

Items 3 and 4 share infrastructure. We have it for FC.1+FC.2; this dir
adds it for #4.

## What's in here

```
public/data/thesis_attribution/
  ├── <TICKER>.json                ← latest pointer (frontend / future tools read this)
  └── <TICKER>_<DATE>.json         ← date-stamped audit artifact
```

Each file contains:
- `ticker`, `thesis_logged_at`, `thesis_source`, `thesis_source_commit`
- `catalyst` block (event + date_or_window + type + source)
- `mechanism_chain_length` (how many causal steps the thesis used)
- `rightIf_conditions` (list — from `step_5_proves_right_if`)
- `wrongIf_conditions` (list — from `step_6_proves_wrong_if`)
- `what_changes_our_mind` (single string — from contrarian view)
- `variant_view_one_sentence`, `time_to_resolution`
- `expected_pnl_asymmetry` (upside / downside / reward_to_risk)
- `quantification` (metric_target + predicted range + horizon + confidence)
- `qc_quality_at_log_time` (snapshot of `_quality` from `/api/research`)
- `outcomes_recorded_at: null` ← populated later by outcome-tracker
- `outcomes: []` ← populated later: `{condition, met_at, met_status, evidence}`

## How to populate

Manual today:

```bash
python3 scripts/log_thesis.py <ticker> <thesis_json_path>
# Writes both <TICKER>.json and <TICKER>_<DATE>.json
```

## What's NOT built (deferred work)

1. **Outcome tracker** — separate script that, given an attribution log,
   periodically checks whether wrongIf/rightIf conditions have fired
   based on actual data (e.g., parsing earnings releases against the
   exact metric thresholds in the conditions). Requires structured
   condition-parsing (regex over "Q3 2026 GM ≥ 44%" type strings) +
   data-source integration. NOT a small KR.

2. **Auto-log on thesis generation** — currently log_thesis.py is manual.
   Auto-trigger could either (a) be invoked by `/api/research` server-side
   after Pass 2 completes, OR (b) run via pipeline daily on any newly-
   committed thesis JSON. Both have tradeoffs (server-side is realtime
   but adds latency to user requests; pipeline is batched but lags).
   Architectural KR for later.

3. **Hit-rate computation** — once outcomes are tracked, compute thesis
   hit rate by quality bucket (PASS/WARN), by sector, by ticker. Need
   n ≥ 10 with paired outcomes before any number is meaningful.

4. **Frontend surface** — no UI for attribution today. When outcomes
   start flowing in, a "Thesis track record" tab would show per-ticker
   hit rate. Out of scope for current scaffold.

5. **Reconciliation with `prediction_log.json`** — root-level
   `prediction_log.json` already has 4 manually-curated high-conviction
   predictions (CLAUDE.md §"Prediction Log Track Record"). Future work
   merges that surface with this auto-log so we have one source of
   truth for thesis outcomes.

## Discipline (matches Bridge 1 framing)

- Attribution is NECESSARY but NOT SUFFICIENT for investment quality.
  Mechanism logic / contrarian-ness still need expert review.
- Don't auto-score "attribution score" — that becomes a Goodhart target.
  Hit rate is the right metric, but it's not computable until n is large.
- The capture step is cheap; the outcome step is hard. Most of the work
  is still ahead.

---

**Created:** 2026-05-05 (post-shift-13, second wave)
**Author:** T1 Claude
**Initial population:** 4 watchlist tickers (002594.SZ / 700.HK / 9999.HK
  / 6160.HK), all logged from theses generated 2026-05-05 14:38 BST
  (commit aefc16b). 16 wrongIf/rightIf conditions captured total. Zero
  outcomes recorded — that requires future infra.
