# Paper Settlement Publication

The nightly records two distinct times: a fill/exit/freeze event keeps its actual
`date`; its order receipt records the current `target_trade_date` and `run_id`.
This repairs catch-up after missed runs without relabeling historical events.

## Receipt And Replay

`model_paper_fund --daily` advances on private copies. A failure does not partially
mutate the caller's fund, orders or decision log, and the CLI returns nonzero
before NAV or projection writes. It cannot publish a successful mark after
silently skipping settlement. Changed orders retain a closed
`paper-settlement/v1` receipt with recording context, the original-order hash,
captured bar inputs and their hash. New automatic decisions reference that order
hash. The bars must have valid ordered unique dates, no dates beyond this run's
cutoff, and finite JSON values.

Before publication, the publisher reopens the protected pre-run order and replays
the existing settlement engine against those captured bars, with no network. It
compares the entire resulting order and exact event list, including fees and P&L.
Duplicate, missing or altered events refuse. Replay-derived cash deltas are
checked even if cash was left unchanged. Both fee-free legacy and cost-bearing
workflow-debug modes keep their existing fill rules.

Only those replayed automatic events may have a date older than the run target.
Other appended decisions, NAV and human-shadow rows retain the existing date
rules. Existing ledger prefixes remain immutable. Removing both a receipt and
its event does not conceal a newly historical order transition.

## Boundaries

- A bar hash proves which bytes were consumed, not that a vendor quote is true.
- This is not a historical realism audit. Legacy adjusted-price samples do not
  become claim-eligible; no sample labels, thresholds or trading rules change.
- The source snapshot and staging code are trusted inputs of publication. This
  contract does not authenticate a hostile producer able to replace all inputs.
- Standalone in-memory `process_day` callers retain the old default behavior.
  Nightly opts into the recording contract explicitly at its CLI call site.
- This PR does not authorize production sync, migration, registration or canary.
  Acceptance outputs are isolated `WORKFLOW_DEBUG`, not official research records.

## Verification

`tests/test_paper_settlement_publication.py` exercises the real settlement engine
and publisher. It is registered in offline CI and runs under the no-network guard.
`PAPER_SETTLEMENT_*` mutations target the recording, replay and publication gates.
Frozen research-contract hashes change only to acknowledge the revised engine
bytes; no contract identity, artifact set or authority gate is relaxed.
