# Semiconductor Prospective Paper Cycle Playbook v0

Status: `WORKFLOW_DEBUG_PLAYBOOK`

This playbook translates the current `main` research contracts into a first
operator guide for 5-10 semiconductor prospective paper cycles. It is not a
model-validity claim, not a production deployment plan, and not a trading
instruction.

The first batch exists to debug evidence binding, U4 decisions, paper
registration, simulated execution, and attribution. It is not eligible for
win-rate, alpha, profitability, or portfolio-promotion claims.

## Authority Boundary

- Junyan owns research methodology, U4 decisions, paper-cycle approval, final
  attribution interpretation, and all real-capital decisions.
- Reed turns the method into contracts, inputs, receipts, logs, and replayable
  operator steps.
- The machine stores accepted and rejected samples, preserves missing data,
  runs offline checks, and emits scorecards. It does not choose securities or
  upgrade a method.
- All outputs keep `no_trade_flag=true` and `production_authority=false` unless
  a later, separate Junyan-approved production contract changes that boundary.

不是买卖指令；研究信号，human executes.

## Current Main Inventory

| Layer | Purpose | Main artifacts | Current role in first batch |
|---|---|---|---|
| U0 | Eligible universe and security identity | `security_registry` | Defines what can be scanned; never silently drops names |
| U1 | Six independent scan channels | `all_market_scan` | Finds evidence by channel; no composite score |
| U2 | Candidate review pool | `candidate_review` | Builds the 100-300 review pool plus reserved/control rows |
| U3 | Six-dimension battery | `battery.json` | Requires visible行情/资金/基本面/技术面/消息面/估值 status |
| U4 | Junyan decision ledger | `u4_decision_ledger.v1` contract | Records `SELECT/REJECT/DEFER/NO_TRADE/DATA_BLOCKED` |
| Closure | Offline U4 replay | `closure_experiment.py` | Builds review packet, seals receipt, verifies closure bundle |
| Method | Thesis, valuation, SMC, expectations | `research_method.py` | Seals method registration and later outcome facts |
| Cycle | U4-to-paper replay | `research_cycle.py` | Seals case, settled bars, outcomes, replay, review |
| Execution | Paper fill realism | `paper_portfolio.py`, `model_paper_fund.py` | Applies paper-only T+1, costs, limits, and no-real-order rules |
| Attribution | Five independent axes | `five_axis_attribution.py` | Separates thesis, valuation, timing, execution, market beta |
| R-035 | Funnel information check | `r035_evaluation.py` | Later compares funnel groups vs controls; not single-trade scoring |

## First Batch Definition

The first semiconductor batch is a workflow-debug wave:

- size: 5-10 prospective semiconductor cases;
- sample purpose: `WORKFLOW_DEBUG`;
- method sample eligible: `false`;
- portfolio promotion eligible: `false`;
- expected result: a set of reviewed evidence bundles and failure cases;
- forbidden result: any statement that the method is profitable, statistically
  valid, or ready for real trading.

The batch can have zero paper registrations if U4, thesis, evidence, timing, or
execution gates honestly stop the flow.

## Operator Flow

```text
same-day U1/U2 bundle
  -> same-day U3 battery
  -> U4 review packet
  -> Junyan U4 decision ledger
  -> verified U4 closure bundle
  -> thesis/factpack/valuation/manual SMC draft
  -> prospective case seal
  -> settled bars and outcome facts arrive later
  -> paper replay
  -> mechanical review
  -> Junyan postmortem confirm/dispute
  -> five-axis attribution
```

### Step 1: Build Or Identify The Same-Day U1-U3 Inputs

Reed prepares the exact input locations:

- immutable U1/U2 funnel bundle directory;
- same-day U3 battery JSON;
- target industry scope: semiconductor;
- data status summary: `COMPLETE/PARTIAL/DATA_BLOCKED/STALE_INPUT`;
- known missing channels and why they are missing.

Do not move a candidate forward because a missing field is convenient. Missing
or stale evidence stays visible.

### Step 2: Produce A U4 Review Packet

Safe offline command shape:

```bash
AR_OFFLINE=1 python3 experiments/research_funnel/closure_experiment.py packet \
  --bundle <frozen-u1-u2-bundle-dir> \
  --battery <same-day-u3-battery.json> \
  --generated-at <timezone-aware ISO time> \
  --output <u4-review-packet.json>
```

The packet status should remain `AWAITING_JUNYAN_REVIEW`. Reed may prepare the
packet; Reed may not fill in Junyan's decision.

### Step 3: Junyan Makes U4 Decisions

For every reviewed candidate, Junyan chooses exactly one:

- `SELECT`
- `REJECT`
- `DEFER`
- `NO_TRADE`
- `DATA_BLOCKED`

Every rejected, deferred, blocked, and no-trade candidate remains part of the
dataset. This is the anti-cherry-picking core of U4.

This is not a free-form five-way override when packet evidence carries a hard
blocker. A candidate with incomplete same-run U3 battery evidence must remain
`DATA_BLOCKED`. A candidate with an active E1 red flag must remain `REJECT`.
If one row violates those forced outcomes, the batch must refuse to land rather
than silently dropping or rewriting that row.

`SELECT` means deep research may proceed. It does not mean paper registration,
position sizing, buying, selling, or portfolio inclusion.

### Step 4: Seal The U4 Receipt Or Decision Ledger Output

If using the offline closure path, the human-authored receipt must bind the
packet hash and contain 3-5 selected rows. If the correct answer is zero
selections, use the U4 decision ledger semantics instead of forcing a receipt.

Safe offline command shape:

```bash
AR_OFFLINE=1 python3 experiments/research_funnel/closure_experiment.py receipt \
  --packet <u4-review-packet.json> \
  --draft <junyan-authored-receipt-draft.json> \
  --output <u4-review-receipt.json>
```

Then replay and verify:

```bash
AR_OFFLINE=1 python3 experiments/research_funnel/closure_experiment.py replay \
  --bundle <frozen-u1-u2-bundle-dir> \
  --battery <same-day-u3-battery.json> \
  --packet <u4-review-packet.json> \
  --receipt <u4-review-receipt.json> \
  --generated-at <timezone-aware ISO time> \
  --output-dir <research-closure-result-dir>

AR_OFFLINE=1 python3 experiments/research_funnel/closure_experiment.py verify \
  --output-dir <research-closure-result-dir>
```

### Step 5: Draft A Prospectively Sealed Research Case

For each selected semiconductor case, Reed prepares a draft that binds:

- verified U4 closure bundle;
- E1/E2 factpack;
- qualified thesis core;
- red-team result;
- industry valuation adapter:
  `SEMICONDUCTOR_NORMALIZED_EARNINGS`;
- manual SMC timing evidence;
- prospective method registration;
- paper order parameters;
- causal cluster identity.

The semiconductor valuation adapter is:

```text
normalized EPS x fair multiple + net cash per share
```

At minimum, normalized EPS must be registered as a later forecast fact. A
revenue-only forecast cannot validate this adapter.

### Step 6: Seal Case, Bars, Outcomes, Replay

Safe offline command shape:

```bash
AR_OFFLINE=1 python3 experiments/research_funnel/research_cycle.py seal-case \
  --closure-bundle <research-closure-result-dir> \
  --input <research-case-draft.json> \
  --output <research-case.json>
```

Settled bars and outcome facts are later artifacts. They must not be present in
the case draft.

```bash
AR_OFFLINE=1 python3 experiments/research_funnel/research_cycle.py seal-bars \
  --closure-bundle <research-closure-result-dir> \
  --case <research-case.json> \
  --input <settled-bars-draft.json> \
  --output <settled-bars.json>

AR_OFFLINE=1 python3 experiments/research_funnel/research_cycle.py seal-outcomes \
  --closure-bundle <research-closure-result-dir> \
  --case <research-case.json> \
  --input <method-outcomes-draft.json> \
  --output <method-outcomes.json>

AR_OFFLINE=1 python3 experiments/research_funnel/research_cycle.py replay \
  --closure-bundle <research-closure-result-dir> \
  --case <research-case.json> \
  --bars <settled-bars.json> \
  --outcomes <method-outcomes.json> \
  --generated-at <timezone-aware ISO time> \
  --output-dir <research-cycle-result-dir>
```

### Step 7: Human Postmortem And Five-Axis Attribution

After mechanical review reaches `REVIEW_READY` or `NO_TRADE`, Junyan may confirm
or dispute the machine thesis/timing label with evidence.

Seal the human postmortem receipt against the cycle bundle. This command uses
`--cycle-bundle`, not `--closure-bundle`:

```bash
AR_OFFLINE=1 python3 experiments/research_funnel/research_cycle.py seal-review \
  --cycle-bundle <research-cycle-result-dir> \
  --input <junyan-postmortem-draft.json> \
  --output <junyan-postmortem-receipt.json>
```

Finalize and verify the reviewed cycle:

```bash
AR_OFFLINE=1 python3 experiments/research_funnel/research_cycle.py finalize-review \
  --closure-bundle <research-closure-result-dir> \
  --cycle-bundle <research-cycle-result-dir> \
  --receipt <junyan-postmortem-receipt.json> \
  --output-dir <reviewed-cycle-result-dir>

AR_OFFLINE=1 python3 experiments/research_funnel/research_cycle.py verify-final \
  --closure-bundle <research-closure-result-dir> \
  --cycle-bundle <research-cycle-result-dir> \
  --output-dir <reviewed-cycle-result-dir>
```

The final five-axis report must keep separate:

- thesis;
- valuation;
- timing;
- execution;
- market beta.

P&L cannot rewrite any axis. A profitable paper result can still have a wrong
thesis or a wrong timing call.

## Reed Checklist

Before asking Junyan to review a batch, Reed must provide:

- input bundle path and hashes;
- semiconductor cohort / industry mapping note;
- U1/U2/U3 status summary;
- list of U4 candidates and why each entered;
- explicit missing evidence list;
- proposed output directory names;
- commands actually run;
- all `DATA_BLOCKED`, `WAIT`, `NO_TRADE`, and failed cases;
- no claim of profitability, win rate, or alpha.

## Junyan Checklist

Junyan must explicitly provide or approve:

- U4 decision for every candidate;
- research question for every `SELECT`;
- whether a case may enter deep research;
- thesis, valuation, wrong-if, and SMC judgment;
- postmortem confirmation or dispute;
- any later promotion from workflow debug to method sample eligibility.

## Stop Conditions

Stop and report instead of continuing when:

- `py -3.11` or workspace doctor is unavailable and no approved substitute is
  documented;
- input bundle or battery is missing, stale, mutable, or not hash-bound;
- U3 battery lacks visible six-dimension status;
- Junyan has not made an explicit U4 decision;
- selected count is outside the contract path being used;
- factpack lacks load-bearing E1 evidence;
- semiconductor valuation does not register normalized EPS;
- manual SMC evidence is missing or contradicts timing ticket fields;
- settled bars are future, intraday, adjusted, or not bound to source;
- output directory already exists;
- any artifact tries to create real trade authority.

## What This Unlocks

If this playbook is followed, the team can start the first semiconductor
workflow-debug cycles without pretending the method is already proven. The
project gains:

1. a repeatable path from research candidate to paper case;
2. preserved rejected and blocked samples;
3. clean separation between thesis, timing, execution, and market beta;
4. a concrete source of future eval cases for Reed/Jason AIOS work;
5. a bridge from Junyan's investment method to product-facing evidence cards.

## Still Missing Before Method Claims

- at least 30 independent, de-clustered prospective causal clusters;
- approved source adapters for outcome facts;
- calibrated SMC sample evidence;
- broker-bound execution cost assumptions;
- production wiring approval;
- portfolio construction approval.

Until those exist, the correct status is workflow debug, not method proof.

不是买卖指令；研究信号，human executes.
