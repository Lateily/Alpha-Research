# Data Pipeline Integrity Audit — 2026-06-16

## Verdict

`universe_a.json` is useful as a broad research-screening snapshot, but it is
not reliable enough for execution zones, registration-grade valuation, or
medium-term technical claims without a fresh quote and primary reconciliation.

The current committed A-share snapshot on `origin/main` was fetched at
`2026-06-12T05:55:22` with 5,862 names. Audited on `2026-06-16`, it is four
calendar days old and is therefore `BLOCKED` for execution or entry-zone use by
the new `scripts/universe_data_health.py` guard.

This audit was triggered by the six-name AI-infrastructure screen
(`600487.SH`, `002130.SZ`, `601208.SH`, `301526.SZ`, `300620.SZ`,
`301217.SZ`) surfacing inconsistent price, PE, and momentum readings.

## What Is Proven

### 1. Price Freshness Is a Hard Gate

Committed snapshot:

- `_meta.fetched_at`: `2026-06-12T05:55:22.055762`
- Audit date: `2026-06-16`
- Guard result: `BLOCKED`

Implication: snapshot values can still support research triage, but they cannot
be used as current entry levels or official registration reference prices
without a current committed snapshot or an explicitly dated live quote.

### 2. `factors.momentum` Is One-Day Tape, Not 12-1 Month Momentum

The production scorer in `scripts/fetch_data.py` ranks:

```text
momentum = percentile_rank(change_pct)
```

That means `factors.momentum` is the cross-sectional rank of same-day price
change in the fetched quote snapshot. It is not 12-1 month momentum and should
not be cited as medium-term trend evidence.

This explains the apparent contradictions in the six-name research:

- `002130.SZ` can show high `momentum` because it had a positive day, even if
  it is well below a prior high.
- `600487.SH` can show low `momentum` because it had a negative day, even if
  it has already had a large multi-month move.

### 3. `quality` Is Inert in the Current Universe Snapshot

The new guard reports:

```json
"roe": 0.0,
"quality": {"unique": 1, "median": 50.0, "stdev": 0.0}
```

The snapshot has no usable broad ROE coverage. Every scored stock effectively
receives neutral quality. Any output that interprets `factors.quality` as
fundamental quality evidence is overstating the data.

This matches the older warning in `docs/strategy/SYSTEMATIC_STRATEGY_v0.md`:
quality is inert until the financial backfill populates the universe.

### 4. `pe` Is a Provider Multiple, Not a Verified TTM PE

The universe field `pe` comes from quote/universe providers. The pipeline does
not currently attach a validated `pe_basis` such as TTM, forecast, annualized
quarter, or static annual-report PE.

The six-name research found multiple cases where provider PE appeared to be a
single-quarter annualized value or otherwise not comparable to a manually
reconstructed TTM PE. Therefore:

- `pe` is acceptable for rough triage.
- `pe` is not acceptable as registration-grade valuation evidence.
- Deep thesis work must reconcile PE through financial statements, share count,
  and current price.

### 5. Tushare Token/Auth Must Be Treated as a Pipeline Health Item

The six-name research agents reported `40101 token不对` when attempting fresh
Tushare paths. This audit cannot rotate credentials; credential rotation is a
human owner action. The pipeline should surface auth failure as a data-health
state, not silently allow reports to imply that fresh Tushare-backed fields were
available.

## Implemented Guardrails

### `fetch_data.py` Metadata

Future `universe_a.json` and `universe_hk.json` writes now include metadata:

- `field_definitions.price`
- `field_definitions.pe`
- `field_definitions.change_pct`
- `factor_definitions.value`
- `factor_definitions.quality`
- `factor_definitions.momentum`
- `factor_definitions.size`
- `factor_definitions.low_vol`
- `research_use_warning`

The metadata explicitly states:

- `pe` is provider-sourced and not guaranteed TTM or forecast.
- `momentum` is one-day `change_pct` rank.
- `quality` may be inert when ROE coverage is absent.
- universe factors are screening hints only.

### `scripts/universe_data_health.py`

New deterministic local guard:

```bash
python3 scripts/universe_data_health.py \
  --as-of 2026-06-16T00:00:00+00:00 \
  --tickers 002130.SZ,600487.SH,601208.SH,301526.SZ,300620.SZ,301217.SZ
```

It reports:

- freshness verdict: `PASS` / `WARN` / `BLOCKED`
- field coverage
- factor dispersion
- inert quality detection
- missing metadata detection
- PE-basis warning
- short-tape momentum warning
- per-ticker quote/factor echo for reviewed names

Selftest:

```bash
python3 scripts/universe_data_health.py --selftest
```

## 2026-06-16 Guard Output Summary

Current result:

```text
verdict: BLOCKED
error: stale_universe_snapshot
warnings:
  - missing_field_definitions
  - missing_factor_definitions
  - pe_basis_not_registration_grade
  - momentum_is_short_tape
  - quality_factor_inert_or_unbacked
```

Coverage:

| Field | Coverage |
|---|---:|
| price | 94.03% |
| pe | 94.32% |
| pb | 94.32% |
| roe | 0.00% |

Factor summary:

| Factor | Unique values | Median | Stdev | Interpretation |
|---|---:|---:|---:|---|
| value | 899 | 57.5 | 22.21 | usable only as provider-PE/PB triage |
| quality | 1 | 50.0 | 0.00 | inert |
| momentum | 678 | 50.0 | 28.87 | one-day tape rank |
| size | 945 | 50.0 | 28.87 | screen hint |
| low_vol | 665 | 50.0 | 28.87 | one-day amplitude rank |

## Consequences for the Six-Name Research

The six-name research should be treated as quick-to-mid research, not
registration-grade work.

The only name that looks worth deeper research on valuation grounds is
`002130.SZ` (沃尔核材), but upgrading it should wait for:

1. a fresh quote or committed universe snapshot;
2. primary financial reconciliation of FY25 and 1Q26;
3. explicit separation of AI exposure from legacy revenue;
4. a real earnings bridge and five-axis red-team review.

The other five names remain watch/avoid-at-spot unless a fresh thesis shows a
new, priced-right variant. The current universe factors cannot be used to
override their valuation/crowding concerns.

## Next Engineering Steps

1. Add `universe_data_health.py` to the daily pipeline as a non-blocking
   artifact writer after universe fetch.
2. Surface `universe_data_health.json` in the platform cockpit so users can see
   whether a screen is based on fresh, interpretable data.
3. Add a Tushare credential preflight step that distinguishes:
   - missing token,
   - invalid token,
   - tier-locked endpoint,
   - endpoint unavailable,
   - successful fresh fetch.
4. Replace or rename the current one-day `momentum` factor before using it in
   any medium-term research statement:
   - either rename it to `short_momentum_1d`, or
   - compute a real PIT 12-1 month momentum from the historical price panel.
5. Keep `pe` as triage only until a `pe_basis` or statement-derived valuation
   field is added.

## One-Line Rule

No AI-screened stock gets an entry zone, registration price, or medium-term
technical claim from `universe_a.json` unless the universe health guard is
fresh and the relevant field basis is explicit.
