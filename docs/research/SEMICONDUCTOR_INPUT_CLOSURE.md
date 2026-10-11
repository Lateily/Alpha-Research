# Semiconductor Input Closure

Status: `OFFLINE_SUPPLEMENT`, not production wiring or method approval.

## Delivered In This Change

`experiments/research_funnel/semiconductor_macro_context.py` projects the
registered M1-B semiconductor subsector into a separate research supplement.
It does not reseal a funnel bundle, update a U4 packet, rank candidates, select
stocks, grant formal blocking authority, or write any files.

The caller must first verify the frozen source manifest and pass the artifact's
byte SHA256 from that manifest. `expected_sha256` must not be obtained from the
untrusted artifact itself. Existing `m1b.validate_run()` checks a full M1-B
directory before this projection is used. The projector additionally validates
the industry's contract, run, China operational date, current registered spec,
and exact `(industry, subsector)` mapping. It never substitutes the electronics
parent row for the semiconductor row.

Quality is derived from the validated relation evidence: all current is
`COMPLETE`, none current is `DATA_BLOCKED`, and mixed evidence is `PARTIAL`.
This describes source coverage, not validation of the mapping's predictive
value. `CALIBRATING`, `UNVALIDATED_V0`, source dates, factor hashes, and blocked
factors remain visible. The upstream composite display score is not exposed as
a research ranking score. A supplement can be verified only by rebuilding it
from the same externally hash-bound source.

## Remaining Closure Gates

These are separate deliverables, not satisfied by this module's tests.

| Gap | Evidence required to close it | Must not happen |
| --- | --- | --- |
| Price-volume input | Confirm the actual provider response; distinguish unavailable fields from collection/derivation defects; preserve declared ratio semantics; any correction of a committed batch uses approved append-only migration | Substituting a different ratio, zero fill, overwriting the historical batch, or making an optional research field veto business publication |
| Issuer supply-chain nodes | Dated issuer-to-node registrations, primary source references, review status, and PIT-valid identity bindings | Treating a sector label or an undated company list as issuer evidence |
| Macro production integration | A separately reviewed same-run input binding and end-to-end research quality propagation test | Claiming this offline supplement repaired the current production funnel |
| Thesis | Current human SELECT, sourced case facts, causal links, falsifiable positive claims and one-to-one wrong-if claims with deadlines | Inventing facts or carrying a previous packet's approval into a new one |
| Normalized valuation | An explicit operational bridge into normalized EPS, justified assumptions and scenarios, and the existing forecast fact/arithmetic validation | Calling EPS-times-multiple arithmetic a completed normalization study |
| Manual SMC | Human-reviewed structure, settled evidence and levels, or a truthful WAIT/NONE | Fabricating a chart structure merely to satisfy required numeric fields |
| Paper execution | Separately approved sealed case and plan; explicit T+10 exit-attempt policy, trading-calendar clock, unsuccessful-exit handling, and replay tests | Equating an observation at T+10 with an exit order, or guaranteeing a fill |
| Attribution | Thesis, valuation, timing, execution and market-beta results, retaining rejected/unfilled/deferred cases and unresolved facts | Restricting process accounting to profitable or closed cases |

## Current Rule Precedence

Human SELECT authorizes deep research, not paper registration. Research and
paper rules require the separate human approval already enforced by the
registration bridge. A pre-decision packet and the ledger's review packet are
different contracts: use the existing closure/review-packet path and reconcile
source identities, never relabel one schema or reuse another packet's approval.

`WORKFLOW_DEBUG` records remain ineligible for formal method evaluation forever.
Register a new prospective experiment before its observations; do not promote
historical debug records. The older playbook's suggestion of later promotion is
an explicitly recorded documentation conflict, not authority to do so.

Thirty independent causal clusters are a minimum discussion gate, not proof of
profitability. No stock selection, numerical valuation, trading rule approval,
or method-effectiveness claim is supplied by this engineering change.

Not a trading instruction; research signals, human executes.
