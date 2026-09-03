# Research Closed Loop V1.4

Status: `FROZEN_OFFLINE_WORKFLOW_DEBUG / PRODUCTION_UNWIRED`

Revision 1.4 keeps every V1 authority, eligibility, denominator, and promotion
boundary unchanged. It adds the missing governed bridge between a current U4
`SELECT` and the Model Paper Fund: an exact plan, verbatim human approval,
shared R-015 intent/commit WAL, same-nightly-lock exclusion, idempotent
projection, crash recovery, and a paper-only receipt. It does not create an
automated selection path or a real order.

Revision 1.1 revised the screening evidence assembly: the
semiconductor cohort now consumes same-date point-in-time price-volume,
fund-flow/chip, and fundamental-valuation evidence. Industry value-chain
evidence remains `PARTIAL` and non-triggering until an issuer-node mapping is
registered. E1 red flags override every positive channel and remain excluded
from both active candidates and random controls.

Revision 1.2 added the append-only daily-source repair projection. It preserves
every original batch, verifies one catalog-wide supersession chain, and binds
the writable store and nightly lock to one runtime root. Because V0.1 has no
independently authenticated publication-time receipt, repaired historical
evidence remains `LATE_OBSERVED` and same-date research snapshots stay
`DATA_BLOCKED`; a repair cannot retroactively create a positive trigger.

Revision 1.3 hardens that immutable boundary. Class-wide scans reject orphan
raw dates, original source tables reject duplicate insertion and
`INSERT OR REPLACE`, the repair JSON boundary rejects non-standard numeric
constants, and the manifest freezes the exact artifact set. It changes no
research method output or authority and supersedes the V1.2 assembly identity.

## What V1 Freezes

V1.4 is the assembly contract for the research blocks already delivered in this
repository. It does not create another screener, thesis engine, fill engine, or
attribution engine. The machine-readable fact source is
`docs/research/contracts/research_closed_loop.v1.json`; it pins the exact
contract and implementation bytes that make up this version.

```mermaid
flowchart LR
    U1["U1 independent channels"] --> U2["U2 candidate bundle"]
    U2 --> U3["U3 battery or DATA_BLOCKED"]
    U3 --> U4["U4 complete human decision ledger"]
    U4 --> R["Factpack + thesis + valuation + manual SMC"]
    R --> P["Exact plan + verbatim human paper approval"]
    P --> W["R-015 intent/commit + idempotent paper projection"]
    W --> E["One realistic paper execution engine"]
    E --> O["T+1/3/5/10 later facts and settled bars"]
    O --> A["Five independent attribution axes"]
    A --> L["Human review and future-only method learning"]
```

Every arrow is hash-bound. A downstream green state cannot repair an upstream
failure. Profit cannot make a false thesis true; good timing cannot repair a
missing E1 fact; and a correct thesis cannot excuse an execution violation.

## The Eight Blocks

1. **Screening** preserves separate U1 channels. Every U2 candidate receives a
   same-run six-dimension U3 row or explicit `DATA_BLOCKED`. Semiconductor
   positive evidence is evaluated relative to its same-date industry cohort;
   no composite score is created and an E1 red flag always wins.
2. **U4 decision** retains `SELECT`, `REJECT`, `DEFER`, `NO_TRADE`, and
   `DATA_BLOCKED`. Junyan alone selects zero or three to five names for deep
   research. A selected name is not an order.
3. **Research registration** freezes the point-in-time factpack, falsifiable
   thesis, industry valuation adapter, red-team result, manual settled-E3 SMC
   ticket, causal cluster, and wrong-if conditions before outcomes exist.
4. **Paper registration** recomputes the current U4 `SELECT`, sealed research
   case, settled marks, and portfolio snapshot into one exact plan. Junyan's
   verbatim approval must bind the full plan hash. The shared R-015 ledger then
   records one replayable intent and one commit while the nightly lock excludes
   concurrent mutation. A selected name still is not a real order.
5. **Paper execution** uses the single Model Paper Fund path. It enforces T+1,
   conservative gaps, one-price limits, execution costs, volume participation,
   corporate-action breaks, and four-ledger reconciliation.
6. **Outcome scoring** binds later facts and settled bars to the prospective
   registration and scores thesis, valuation, timing, execution, portfolio
   compliance, and paper P&L independently.
7. **Five-axis attribution** separates thesis, valuation, timing, execution,
   and market beta. Relative return is diagnostic and is never called alpha.
8. **Method learning** preserves both machine and human attribution. Any rule
   change applies only to future registrations; history is never rewritten to
   make a method look better.

## Frozen Authority

- U4 selection and paper registration remain `HUMAN_JUNYAN_ONLY`.
- All V1.4 artifacts keep `no_trade_flag=true`, `trade_authority=false`,
  `production_authority=false`, and `claim_allowed=false`.
- Rejections and missing-data decisions remain in the decision denominator.
- The five inherited paper orders are `UNVERIFIED_SIMULATION`; they remain in
  historical audit totals but do not enter win-rate, method, or portfolio
  promotion denominators.
- Git merge is not production deployment. This V1 adds no nightly step and
  writes no runtime state.

## First-Wave Policy

The first five to ten semiconductor prospective cycles are workflow-debug
cases. They exercise every block and expose missing evidence, but they are
fixed to:

- `sample_eligible=false`;
- `method_claim_sample_eligible=false`;
- `portfolio_promotion_eligible=false`;
- `claim_allowed=false`.

No method claim is allowed before 30 independent, causal-cluster-deduplicated
closed samples. Portfolio construction additionally requires the method to
reproduce across industries. Neither threshold can be relaxed by a good-looking
single case or aggregate paper P&L.

## Honest Completion

A cycle is complete when it reaches a valid terminal state with its evidence
preserved. `REJECT`, `DEFER`, `NO_TRADE`, `DATA_BLOCKED`, `NO_FILL`,
`CORPORATE_ACTION_BREAK`, `UNRESOLVED`, and a closed reviewed paper cycle are
all honest outcomes. Only recording successful selections would make the
research process unscorable and is forbidden.

## Change Control

Any change to the ordered blocks, authority constants, first-wave eligibility,
30-cluster threshold, cross-industry promotion gate, or bound implementation
bytes requires a new reviewed manifest revision. Revision 1.4 is such a
reviewed revision; it does not rewrite the historical V1 registration or any
existing paper order. A PR
may repair an implementation, but it cannot silently keep an existing method
label while changing the frozen assembly.

不是买卖指令；研究信号，human executes.
