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
| 1 | Risk overlay (drawdown breaker + regime cap) + OLS-calibrated weights should cut the -74% DD and improve risk-adjusted return | risk_monitor wired into loop (FREEZE bug fixed) + calibrate_weights OLS | _pending run 26422660747_ | — | — |

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
