# Paper Trading System Audit — 2026-07-11

Source of truth checked: `/Users/years/ar-live` at commit `89dd229`
(`feat(tracker): paper tracker v1`). Current workspace
`/Users/years/Desktop/Stock/ar-platform` is stale and was not used as the
ledger source.

## Status

The paper trading system is operational but not yet complete as a weekly
production loop.

Completed:

- Model Paper Fund ledger exists: `model_fund/{fund,orders,nav_history,decision_log}.json`.
- Research/paper signals extend the same `paper_signal_log.json`; no third
  ledger was created.
- `paper_tracker.py --selftest` passed 12/12.
- `model_paper_fund.py --selftest` passed 30/30.
- `watchtower.py --selftest` passed 14/14.
- `nowcast_evaluator.py --report` reads the nowcast pool and gates any claim at
  n >= 30.

Not complete:

- No 2026-07-10 settled sample or ledger PR was found. The official settled
  fund book currently stops at 2026-07-09.
- There is not yet a single weekly recap command that joins fund/order/decision
  log, paper signal rollup, and nowcast scoring into one review artifact.
- Human shadow NAV is still missing, so model-vs-human comparison is blocked.

## Model Fund Snapshot

Evidence: `model_fund/fund.json`, `orders.json`, `nav_history.json`,
`decision_log.json` [validated against ledger].

| Metric | Value |
|---|---:|
| Initial capital | RMB 1,000,000 |
| Latest settled date | 2026-07-09 |
| Latest NAV | RMB 997,867 |
| Cumulative return | -0.213% |
| Max drawdown | -0.645% |
| Cash | RMB 847,720 |
| Open positions | 1 |
| Pending orders | 2 |
| Closed trades | 0 |
| Claim allowed | false, 0/30 closed trades |

## W28 Order Ledger

| Date | Ticker | Name | Setup | Status | Evidence |
|---|---|---|---|---|---|
| 2026-07-06 | 601899.SH | 紫金矿业 | DEFENSE_BREAKOUT | pending through 2026-07-09; 2026-07-10 Watchtower says entry crossed, pending official settle | orders + watchtower log |
| 2026-07-06 | 603259.SH | 药明康德 | ROTATION_LEADER | cancelled 2026-07-07 by two-day WARNING rule | decision_log |
| 2026-07-06 | 600900.SH | 长江电力 | DEFENSE_DIVIDEND | cancelled 2026-07-07 by v3 three-factor denial | decision_log |
| 2026-07-06 | 600276.SH | 恒瑞医药 | TREND_CONTINUATION | filled 2026-07-07 at 56.4; open as of 2026-07-09 | orders |
| 2026-07-07 | 002714.SZ | 牧原股份 | TRIPLE_CONFIRM_BREAKOUT | pending through 2026-07-09 | orders |

Non-action records:

- 2026-07-06: AI hardware scope no-trade decision due to EXIT_REVIEW/WARNING
  posture and sector outflow.
- 2026-07-07: 药明康德 risk review before final cancellation.

## Paper Signal Ledger

Evidence: `paper_signal_log.json` [validated against ledger].

- Total signals: 58.
- Line: all 58 are `execution`.
- Market states: RISK_OFF 30, WEAK_REPAIR 24, RISK_ON 4.
- Setup types: HOLD_OBSERVE 30, EXIT_REVIEW 11, WARNING 10,
  DE_RISK_REVIEW 6, RECLAIM_REVIEW 1.
- All rollup rates are `claim_allowed=false`; no win-rate claim is allowed.

Key interpretation:

- The ledger is usable as a descriptive count table.
- It is not yet a performance proof because no group clears the n >= 30
  validation gate.

## Nowcast Pool

Evidence: `nowcast_log.json`, `/tmp/ar-watchtower.log` [validated against local
log].

- Total nowcasts in pool: 20.
- Scored: 14.
- Overall flow hit rate shown by the evaluator: 0.50, but claim_allowed=false.
- 2026-07-10 added 6 unscored Watchtower nowcasts after #130 wiring.

Important 2026-07-10 events:

- Watchtower started at 09:27:28, not 09:14; likely machine wake timing needs
  separate operational review.
- Nowcasts were successfully written to the pool: 紫金、沃尔、牧原、中际、新易盛、利通.
- 紫金矿业 `ENTRY_CROSSED` was logged intraday, but no official settled order
  update exists yet. It must remain "pending official settle".

## System Gaps To Close

1. 2026-07-10 settle gap:
   - Need official sample + model fund ledger update for 2026-07-10.
   - Until then W28 weekly report cannot be finalized.

2. Weekly recap artifact:
   - Add a read-only weekly recap generator that joins:
     `model_fund/*`, `paper_signal_log.json`, `nowcast_log.json`,
     `watchtower_log.json`, and samples.
   - It should fail closed when a trade day has watchtower events but no
     official settled sample.

3. Human shadow:
   - Need Junyan-provided daily human NAV or position summary to enable
     `compare_human_shadow`.

4. Research pre-registration:
   - No `rotation_hypothesis` or `value_chain_thesis` records are registered
     yet. The tracker can accept them, but the research loop has not started.

## Research Methodology Adjustment

The value-chain method should not be semiconductor-specific. Semiconductor is a
possible first case, not the method itself.

The distilled method is:

1. Identify a value-chain node.
2. Test whether it has a capability bottleneck with E1/E2 evidence.
3. Test whether the bottleneck translates into cash flow with E1 evidence.
4. Map relationship edges: customers, suppliers, JV, co-development, capex.
5. Define a dated catalyst and a wrong-if.
6. Register as a paper signal before outcome.

This method can apply to semiconductor, pharma, energy, agriculture, consumer,
or any sector. Sector choice should be driven by evidence quality and catalyst
clarity, not by the recent hottest theme.

## Validation Footer

Causal logic is valid because every conclusion above maps to a local ledger,
log, or selftest. Specific return and hit-rate numbers are descriptive only and
not validated performance claims. The system is ready for paper-data
collection, not for alpha claims.

不是买卖指令；研究信号，human executes.
