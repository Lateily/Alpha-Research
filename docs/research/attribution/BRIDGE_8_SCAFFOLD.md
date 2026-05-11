# Bridge 8 Scaffold — Paper Trading + Outcome Verification

> **Status:** Scaffold ✓ shipped 2026-05-11. Runs in pipeline daily.
> Outcome semantic verification (NLP parsing of wrongIf conditions) is
> deferred future KR. Real "hit rate" metric requires n≥10 verified
> outcomes — accrue over time.

## Data flow

```
1. Thesis shipped (via /api/research-multi)
       ↓
2. scripts/log_thesis.py extracts catalyst/wrongIf/rightIf/R/R/horizon
       → public/data/thesis_attribution/<TICKER>.json
       ↓
3. scripts/follow_thesis.py (daily in pipeline)
       - reads attribution → entry conditions
       - reads market_data.json → today's price
       - reads ohlc_*.json → entry-date price (closest <=)
       - computes return-since-entry, days-held, days-to-catalyst
       - determines status: ACTIVE | TARGET_HIT | STOPPED_OUT | CATALYST_DUE | EXPIRED
       - appends today's snapshot to daily_log (capped 90 days)
       → public/data/paper_trades/<TICKER>.json
       → public/data/paper_trades/summary.json (aggregate)
       ↓
4. scripts/verify_thesis.py (daily in pipeline)
       - pairs paper_trades with thesis_attribution
       - structures each wrongIf/rightIf for human review:
           {kind, original_text, verification_status: PENDING_HUMAN_REVIEW,
            verified_at, verified_by, evidence_observed, auto_signal}
       - auto_signal: price-based hint only (NOT replacement for review)
       - reviewer_notes / verified_final_outcome fields for human fill
       → public/data/thesis_outcomes/<TICKER>.json
       → public/data/thesis_outcomes/summary.json (hit rate when verified)
```

## Watchlist filter

Both scripts filter by current `watchlist.json`. Legacy theses (e.g.,
700.HK Tencent from old v1.1 watchlist) remain in `thesis_attribution/`
for audit but are NOT paper-traded after the watchlist switch.

## Status definitions

| Status | Trigger |
|---|---|
| ACTIVE | thesis live, no condition triggered yet |
| TARGET_HIT | return reached upside_if_right threshold (parsed from R/R text) |
| STOPPED_OUT | return reached downside_if_wrong threshold (parsed from R/R text) |
| CATALYST_DUE | within 14 days of earliest catalyst date |
| EXPIRED | latest catalyst date passed without trigger |

For SHORT theses: TARGET_HIT means price dropped by upside_if_right %;
STOPPED_OUT means price rose by downside_if_wrong %.

## Direction handling

Theses with `_direction: PASS` or `NEUTRAL` (multi-agent synthesizer
decided no edge) → `_status: skipped_non_actionable`. Recorded in
attribution log for audit but NOT paper-traded.

Currently 2 of 4 watchlist tickers are actionable:
- **002594.SZ BYD** — LONG @ ¥100.02 entry, +25% target / -10% stop, catalyst 2026-07-15 to 08-31
- **603233.SH 大参林** — SHORT @ ¥18.55 entry, +6% short-return target / -5% stop, catalyst Aug 2026

300308.SZ Innolight + 175.HK Geely are PASS — synth honestly said
"no edge" given Bull/Bear data quality.

## What's deferred (future KRs)

### KR: NLP wrongIf/rightIf parsing
Current: condition text stored as free-form ("Q2 GM falls below 15%").
Future: regex-extract structured threshold (metric=GM, op=<, value=15%,
horizon=Q2_2026), then auto-verify against newly-fetched `fin_*.json`
when Q2 prints land.

ETA: 1-2 shifts. Risk: regex over LLM-generated free text is brittle.
Better path may be calling an LLM verifier (e.g., "given thesis claim
and Q2 fin print, did this condition trigger?").

### KR: News-event verification
Some wrongIf conditions reference news ("Stellantis exits China JV").
Need news source integration (Cailianpress / Tushare news_cct) to
auto-flag triggers. Currently human-review.

### KR: Hit-rate calibration
Requires n ≥ 10 verified outcomes. Today we have 2 active (BYD LONG +
大参林 SHORT) + 0 verified. As theses cycle through TARGET_HIT /
STOPPED_OUT / EXPIRED → human fills `verified_final_outcome` →
summary computes hit rate. Calibrate prompt + model assignments based
on results.

### KR: Backtest
Historical backtest is separate from this Bridge-8 forward log. To
backtest, re-run multi-agent on historical data contexts (e.g., what
would multi-agent have said about BYD on 2024-04-22?). Requires
historical market_data + fin snapshots — feasible but costly
(~$1/historical-point × many points).

## How Junyan should interact with this

**Daily flow** (pipeline auto-runs):
- `paper_trades/<TICKER>.json` updated with today's price + return + status
- `thesis_outcomes/<TICKER>.json` updated with condition-review forms

**When a thesis closes** (catalyst passes / price hits target/stop):
- Junyan opens `thesis_outcomes/<TICKER>.json`
- For each wrongIf/rightIf:
  - Set `verification_status: TRIGGERED | NOT_TRIGGERED | INCONCLUSIVE`
  - Fill `evidence_observed: "..."` (URL to news, or specific fin metric)
  - Set `verified_at: ISO8601`, `verified_by: "Junyan"`
- Set top-level `verified_final_outcome: WIN | LOSS | PARTIAL | UNCLEAR`
- Add `reviewer_notes: "..."` with reflection on what worked / didn't

**Quarterly retro**:
- Read `thesis_outcomes/summary.json` for hit rate + avg return by direction
- Identify which agent (Bull / Bear / Synth) made decisive call on wins vs losses
- Iterate on prompts (e.g., "Bull tends to over-confident on consensus-already-priced-in arguments" → tighten Bull SYSTEM_PROMPT)

This is the **feedback loop** that closes Bridge 1 → Bridge 8 → back to Bridge 1.

---

**Author:** T1 Claude (Bridge 8 scaffold wave 2026-05-11)
**Files:**
- `scripts/follow_thesis.py` (~280 LOC)
- `scripts/verify_thesis.py` (~220 LOC)
- `.github/workflows/fetch-data.yml` (added Step 2e.1 + 2e.2 + glob extensions)
