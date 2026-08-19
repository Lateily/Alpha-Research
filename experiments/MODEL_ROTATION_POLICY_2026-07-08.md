# Model Rotation Policy v0 - 2026-07-08

Status: Ready for Claude review, not production.

## Problem

The current execution model treats several positive flow observations as if they
can support next-step prediction. That worked during June's more persistent
trend regime, but it breaks in a one-day rotation regime.

Observed scorecard from Junyan's closed test:

- positive destination / nowcast: 14 scored, hit rate 0.50
- negative escape / distribution calls: judged useful across 利通, 深科技,
  中际, 新易盛 examples

## Model State Change

Effective experimental state:

```text
where money is now              -> FACT, high fidelity
where money is escaping from    -> FACT, high fidelity
negative continuation           -> RISK EDGE CANDIDATE
where money goes next           -> NO EDGE / OBSERVE ONLY in churn
```

## Mechanical Policy

1. Split `fact_state` from `forecast_state`.
   `main inflow`, `controlled advance`, `CVD floor`, and `reclaim attempt` are
   facts. They do not become entry evidence unless their setup type has forward
   paper evidence.

2. Positive-flow predictive use is quarantined in churn.
   In `STYLE_ROTATION | CHURN | RISK_OFF`, or when recent nowcast hit rate is
   near coin-flip, positive flow signals get `predictive_weight_multiplier = 0`.
   They may be displayed, logged, and scored later, but cannot clear an entry
   gate.

3. Negative-flow signatures stay active as risk gates.
   `DISTRIBUTION_PROBABLE`, `FAKE_STRENGTH`, `OPENING_FADE`,
   `CVD_BEARISH_DIVERGENCE`, and failed-reclaim patterns may trigger
   `DE_RISK_REVIEW` or `WARNING` posture when paired with support break,
   failed reclaim, or sector-anchor weakness.

4. Persistence filter becomes mandatory for positive continuation.
   Positive-flow setups need 2-3 week persistence, sector-anchor confirmation,
   close-held reclaim/breakout, no distribution signature, and n>=30 scored
   forward samples before being promoted above `PAPER_REVIEW_ONLY`.

5. Replace "prediction of destination" with "condition of unwind".
   The model should forecast crowding failure conditions: extreme crowding,
   failed breakout, one-day reversal, retail/large-order divergence, and sector
   anchor distribution. This is a risk-control problem, not a route-planning
   problem.

## Production Translation

Recommended production changes, pending approval:

- `scripts/signal_confluence.py`
  - add `FLOW_ROLE` metadata per signal: `fact_positive`, `risk_negative`,
    `other`
  - add `model_state: CHURN_MODE | NORMAL_OBSERVATION_MODE`
  - in `CHURN_MODE`, set positive-flow entry contribution to zero while keeping
    display and paper logging
  - keep negative-flow signals eligible for risk-review contribution

- `scripts/daily_decision.py`
  - remove recommended size language from `BUY_WATCH` reason text until the
    Trade Decision Stack no-size boundary is reconciled
  - add `OBSERVE_ONLY` / `WARNING` / `DE_RISK_REVIEW` posture output parallel to
    legacy actions
  - prevent `BUY_WATCH` when the only bullish evidence is positive flow nowcast
    in churn

- new paper-signal ledger
  - persist every execution posture change with `setup_type`, `market_state`,
    `sector_state`, `horizon`, and `no_trade_flag: true`
  - score at T+0/T+1/T+3/T+5/T+10
  - report by setup type and regime

## Causal / Numeric Status

Causal logic is valid for the risk-control overlay because distribution,
trapped supply, failed reclaim, and inventory overhang can persist after the
first signal.

Causal logic is questionable for positive-flow prediction because, in churn,
main-force observation and price movement are nearly simultaneous and do not
commit to next-day continuation.

Specific numbers are unvalidated intuitions unless explicitly marked as scored
sample data. The 14-sample nowcast hit rate is observed but still below the
n>=30 bar for an alpha claim; it is enough to quarantine predictive use, not
enough to calibrate a replacement threshold.

## Validation Run

```bash
python3 experiments/flow_regime_policy.py --selftest
python3 experiments/flow_regime_policy.py
```

Expected default output: `ACCUMULATION_PROBABLE` with n=14 / hit_rate=0.50 in
`STYLE_ROTATION` returns `OBSERVE_ONLY` and positive-flow entry weight `0.0`.

## Production Readiness

Not ready. This is an experimental policy shim for Claude/Junyan review before
any production script change.
