# Backtest Iteration Log — autonomous overnight run (2026-05-25/26)

> Junyan mandate: run ~10 iterations autonomously, each with **honest feedback +
> a systematic improvement method**. Morning 验收.
>
> **Discipline (the red line):** every change has an INDEPENDENT a-priori
> rationale (methodology fix / bug / standard quant practice) — NOT
> parameter-fishing to hit a target. Each change is kept only if it's principled
> AND helps; reverted otherwise. If systematic improvement is exhausted and it
> still doesn't beat the benchmark, "this approach doesn't work" is the honest
> conclusion — no curve-fit rescue.
>
> **Efficiency:** the month-end panel (~800k rows) is fetched ONCE (GHA), then
> iterations run LOCALLY on the fixed panel (seconds each). Only the
> strategy/risk/factor logic changes between iterations; the data is constant.
>
> **Headline metric:** OOS CAGR (2019+) — weights fit in-sample 2006-2018.
> Also track MaxDD, Sharpe, vs-CSI300 excess (once added), turnover.

## Baseline (run 26418580192, raw factor, NO risk, hand-set weights)
- CAGR (full, in-sample-optimistic): **-0.43%** · Sharpe 0.17 · **MaxDD -74.3%**
- Per-regime: 2008 -64% · 2015 +166% · 2018 -34% · 2020 -11% · 2022 -2% · 2024 -2%
- Verdict: FAILING. Chases bubbles, no crash protection. The honest starting point.

## Iteration ledger

| # | Hypothesis (a-priori rationale) | Change | Result (OOS CAGR / MaxDD / Sharpe) | Kept? | Honest note |
|---|---|---|---|---|---|
| 1 | Risk overlay (drawdown breaker + regime cap) + OLS-calibrated weights should cut the -74% DD and improve risk-adjusted return | risk_monitor wired into loop (FREEZE bug fixed) + calibrate_weights OLS (weights: value 0.57 / low_vol 0.26 / growth 0.17, **momentum & quality zeroed** — OLS confirms A-share monthly mean-reversion) | OOS CAGR 0.0% / IS CAGR -0.9% / **MaxDD -22.5% (was -74%)** / Sharpe -0.09 | partial | DD cut DRAMATICALLY but per-regime: 2008 -22%, all else 0.0 → **strategy went to cash in 2008 and never came back (TO_CASH is one-way, no re-entry).** Structural flaw, not tuning. Kept risk overlay; iter-2 must add re-entry. |
| 2 | Re-entry rule for risk overlay: binary breakers without re-entry = permanent cash trap (standard quant pitfall). Use rolling 24-month peak instead of all-time peak so drawdown resets naturally as market normalizes. | Replaced `peak = max(peak, equity)` with rolling 24mo max in backtest_v2 | **OOS +9.35%** / IS +6.53% / MaxDD -31% / Sharpe +0.67 / final eq 4.28 | ✅ KEPT | **HUGE win.** Principled fix (rolling peak = standard trend-following), unlocked real OOS alpha. Per-regime now sensible (2008 -22% then re-engages, 2015 +181%, 2024 +5%). |
| 3 | Need benchmark to judge if +9.35% is real alpha or just market beta. | EW-universe benchmark + alpha now in results | OOS strat 9.35% / bench 11.90% / **ALPHA -2.55%**. IS strat 6.53% / bench 13.39% / **ALPHA -6.87%** | ✅ KEPT (the reporting) | **CRITICAL honest finding:** we UNDERPERFORM equal-weight buy-and-hold by 2.55%/yr OOS. Without the benchmark we'd have called +9.35% a win. We didn't. |
| 4 | Isolate the source of negative alpha: risk overlay or factors? Run with risk_overlay=OFF + OLS weights ON → factor alpha alone. If factor-only also underperforms EW → factors aren't adding value. | Add --no-risk CLI flag to run_universe_backtest | _running_ | — | — |

_(appended each iteration)_

## Improvement backlog (principled, ordered)
1. ✅ queued — Risk overlay + OLS calibration (iter 1)
2. Sector-neutralize the factor composite (avoid single-sector loading) — uses universe_pit industry
3. Liquidity/size filter at SELECTION (drop illiquid/micro-cap so returns are tradeable)
4. Benchmark: compute excess return vs CSI300 (alpha, not just absolute) — needs index series
5. Factor IC analysis → drop factors with ~0 predictive power (R²=0.0008 hints noise)
6. Rebalance frequency: monthly vs quarterly (turnover/cost)
7. Factor winsorize / robust z-score (outlier resistance)
8. Full risk-monitor integration (per-position stops + vol targeting, not just gross)
9. Concurrent-positions / concentration robustness (report a range, no cherry-pick)
10. Transaction-cost / T+1 fill-precision realism check

## Morning summary
_(filled at the end: what helped, what didn't, the honest final verdict + the
best honestly-validated config, and whether it beats buy-and-hold CSI300.)_
