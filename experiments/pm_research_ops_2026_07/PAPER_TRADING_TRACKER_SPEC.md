# Paper Trading Tracker Spec

## Purpose

For the next one month [user-requested measurement window, unvalidated as a
statistical sample size], the system should record every research-adjacent
signal before outcome. The goal is not to prove alpha. The goal is to create
the first clean sample of:

- what the model believed
- why it believed it
- what gate allowed or blocked it
- what happened afterward
- what should be changed

## Boundary

This tracker records research signals and human-executed outcomes. It does not
issue buy/sell instructions.

Real capital actions, if any, should be recorded as human decisions after the
fact. The model's role is evidence, gate, risk posture, and attribution.

## Signal Types

Use these initial setup types [unvalidated taxonomy]:

- `rotation_hypothesis`
- `value_chain_thesis`
- `execution_gate`
- `risk_warning`
- `watch_only`
- `blocked_by_regime`
- `distribution_warning`

## Core Schema

Each signal should have:

```json
{
  "signal_id": "YYYYMMDD-HHMM-<ticker>-<short_setup>",
  "created_at": "ISO-8601 timestamp",
  "created_by": "Junyan | Claude | Codex | Senior PM",
  "ticker": "optional for sector-level signal",
  "name": "",
  "sector": "",
  "setup_type": "",
  "market_state": "RISK_ON | WEAK_REPAIR | RISK_OFF | STYLE_ROTATION | CHURN",
  "sector_state": "",
  "hypothesis": "",
  "variant_view": "",
  "catalyst": "",
  "mechanism_chain": [],
  "evidence": [
    {
      "claim": "",
      "tier": "E1 | E2 | E3 | E4",
      "source": "",
      "status": "verified | inferred | assumption"
    }
  ],
  "flow_fact": "",
  "forecast_claim": "",
  "entry_gate": "OBSERVE_ONLY | PAPER_REVIEW | WARNING | DE_RISK_REVIEW | EXIT_REVIEW",
  "trigger_condition": "",
  "invalidation": "",
  "horizon": "intraday | 1d | 3d | 5d | 10d | 20d | 60d",
  "no_trade_flag": true,
  "human_status": "not_executed | executed_by_human | explicitly_skipped",
  "human_notes": "",
  "prices": {
    "trigger_price": null,
    "close_t0": null,
    "close_t1": null,
    "close_t3": null,
    "close_t5": null,
    "close_t10": null
  },
  "outcome": {
    "status": "pending | hit | miss | invalidated | blocked_success | blocked_false_negative",
    "mfe": null,
    "mae": null,
    "return_t1": null,
    "return_t3": null,
    "return_t5": null,
    "return_t10": null,
    "postmortem": ""
  }
}
```

Horizons such as `1d`, `3d`, `5d`, and `10d` are project paper-signal
conventions [unvalidated intuition]. They become useful only after enough
forward samples accumulate.

## Daily Workflow

1. Morning:
   - record market regime
   - carry forward active paper signals
   - note which signals are blocked by CHURN_MODE or other gates

2. Intraday:
   - log any new nowcast or execution-gate signal as `sample_eligible:false`
     if it uses intraday inferred data
   - do not score it as truth until settle data arrives

3. Post-close:
   - update prices and outcomes
   - classify gate success/failure
   - append one-line postmortem only after outcome is known

4. Weekly:
   - summarize by setup_type, market_state, sector, and gate
   - keep hit-rate claims out of the report unless sample size clears the
     project validation threshold

## Thought Log

Every signal needs a short thought log:

| Time | Author | Thought | Changed action? | Why |
|---|---|---|---|---|
|  |  |  | yes/no |  |

Purpose: record model reasoning evolution without rewriting the original
hypothesis.

## Minimum One-Month Metrics

At the end of one month [user-requested window, unvalidated sample size], report:

- number of pre-registered signals
- number of triggered signals
- number blocked by gates
- gate success rate
- hit rate by setup_type if sample is large enough
- average return by horizon
- MFE/MAE by setup_type
- false-breakout rate
- negative-signal continuation rate
- positive-flow continuation rate

Do not claim stable expectancy if the sample is small or regime-specific.

## Production Migration Notes

Likely production destinations, pending Junyan approval:

- `scripts/paper_trading.py` for ledger update logic.
- `public/data/trades.json` or a new append-only paper-signal file for output.
- Dashboard tracker tab for visualization.
- `signal_quality.py` for outcome aggregation.

Codex should not edit those production paths without explicit approval.

## Validation Footer

Causal logic is valid because pre-registration and post-outcome scoring reduce
hindsight bias. Specific schemas, setup types, and horizons are unvalidated
workflow priors until enough paper samples are recorded.

不是买卖指令；研究信号，human executes.
