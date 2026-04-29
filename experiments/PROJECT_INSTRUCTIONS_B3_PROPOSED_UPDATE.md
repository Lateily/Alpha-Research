# Proposed `PROJECT_INSTRUCTIONS.md` B3 Update

Status: draft only. Do not edit `PROJECT_INSTRUCTIONS.md` until Junyan approves.

## Replace current B3 block with:

```text
B3  VP SCORE DECOMPOSITION  (show all 5 components always)
    Expectation Gap    25% · AUTO · rDCF delta
    Fundamental Accel  25% · AUTO · fin_*.json
    Narrative Shift    20% · MANUAL · watchlist.json
    Low Coverage       15% · MANUAL · watchlist.json
    Catalyst Prox      15% · MANUAL · watchlist.json

    Expectation Gap mapping:
      delta = our_growth - implied_growth_from_rdcf
      delta <= -0.50 → 10
      delta <= -0.25 → 22
      delta <= -0.10 → 35
      delta <=  0.00 → 48
      delta <= +0.10 → 55
      delta <= +0.25 → 68
      delta <= +0.50 → 78
      delta  > +0.50 → 88

    Validation disclosure:
      Causal logic appears reasonable, but the 25/25/20/15/15 weights and
      mapping thresholds are unvalidated priors unless later calibrated by
      backtest or live paper-trading evidence.
```

## Reason

Current `PROJECT_INSTRUCTIONS.md` says:

- Expectation Gap is 30%.
- Catalyst Proximity is 10%.
- EGS formula is `50 + 50 × tanh(delta / 0.20)`.

Current `CLAUDE.md` and `scripts/vp_engine.py` use:

- VP weights `25/25/20/15/15`.
- Piecewise delta mapping.

