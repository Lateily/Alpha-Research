# Phase 1 Data Foundation Validation

Task: `2026-05-25-phase1-data-foundation-validation`

Completed at: `2026-05-24T23:07:12Z`

## Scope

New validation-only scripts were added for a small Tushare backfill probe:

- `scripts/fetch_history_tushare.py`
- `scripts/build_pit_universe.py`

The daily pipeline fetcher and GitHub Actions workflow were not modified.
`data_history/` was added to `.gitignore`, so generated history files stay out
of the repo and GitHub Pages deploy.

## Execution

Commands run:

```bash
python3 -m py_compile scripts/fetch_history_tushare.py
python3 -m py_compile scripts/build_pit_universe.py
python3 scripts/build_pit_universe.py --sleep 0.4
python3 scripts/fetch_history_tushare.py --tickers 600519.SH,000001.SZ,002594.SZ,300104.SZ --years 20 --start 20050101 --sleep 0.4
bin/git-safe.sh diff --stat scripts/fetch_tushare.py .github/workflows/fetch-data.yml
```

Total attempted API calls: `27` [validated against this run]

Wall-clock for Tushare execution: `11.0s` [validated against command output]

Rate-limit hits: `0` [validated against command output and error payloads]

Tushare/API errors: all attempted calls failed before Tushare response because
the sandbox could not resolve `api.waditu.com`.

Representative error:

```text
NameResolutionError: Failed to resolve 'api.waditu.com'
```

## Data Depth Results

Specific numbers are [validated against this failed local run]. They are not
evidence about the 15000-point account entitlement because the process never
reached Tushare.

| Ticker | Status | Daily rows | Daily first | Daily last | Income rows | First financial ann_date | API calls | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 600519.SH | failed | 0 | null | null | 0 | null | 6 | 6 |
| 000001.SZ | failed | 0 | null | null | 0 | null | 6 | 6 |
| 002594.SZ | failed | 0 | null | null | 0 | null | 6 | 6 |
| 300104.SZ | failed | 0 | null | null | 0 | null | 6 | 6 |

Universe output:

| Metric | Value |
|---|---:|
| `counts.L` | 0 |
| `counts.D` | 0 |
| `counts.P` | 0 |
| `stocks` | 0 |
| API calls | 3 |
| Errors | 3 |

## Test Gate Results

| Gate | Result | Evidence |
|---|---|---|
| A depth | FAIL | `600519.SH` daily rows = 0; first date = null |
| B PIT financials | FAIL | `600519.SH` income rows = 0; first ann_date = null |
| C survivorship | FAIL | `counts.D` = 0; `300104.SZ` absent from universe; delisted daily rows = 0 |
| D no daily-pipeline breakage | PASS | `bin/git-safe.sh diff --stat scripts/fetch_tushare.py .github/workflows/fetch-data.yml` returned empty output |

## Validation Labels

Causal logic is valid because PIT financials keyed by `ann_date` / `f_ann_date`
and a universe built from listed + delisted + paused names are the correct
data primitives for removing look-ahead and survivorship bias from the future
backtest.

Specific numbers are [validated against this failed local run] for command
outputs and row counts. The expected 15-year / 20-year depth thresholds are
[unvalidated intuition] as task-gate heuristics until a successful Tushare run
confirms actual trading-day and filing coverage.

## Verdict

Is a 20yr PIT survivorship-safe A-share backtest data layer feasible from this
account - **NO, not proven in this run**.

Evidence: the scripts are implemented and compile, but the validation could not
reach Tushare from this sandbox due DNS resolution failure for `api.waditu.com`.
This is an execution-environment blocker, not evidence that the account lacks
the required entitlement. Re-run the same two commands in an environment with
Tushare network access to produce the actual feasibility verdict.
