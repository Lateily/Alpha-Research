# AR SMC/ICT V1 - Offline Rule Contract

Status: `WORKFLOW_DEBUG / PRODUCTION_UNWIRED / METHOD_UNVALIDATED`.

## Purpose And Authority

This version computes reproducible, evidence-bound SMC/ICT observations and
paper-strategy proposals. It neither selects U4 names nor registers paper
orders, writes production ledgers, sends orders, or claims a profitable method.
The existing research and human paper approval gates remain separate. Every
historical case may enter the experience library; cases visible during rule
design are not blind validation samples. A challenger may be proposed at any
time but cannot replace an approved version or rewrite prior receipts.

The engine is invoked on a frozen JSON input with
`python3 -m experiments.research_workflows.smc_ict_engine --input INPUT.json`.
It prints a receipt to stdout and writes no files. The receipt's SHA-256 is a
tamper check, not proof that the source provider told the truth; a verifier
must rederive the full receipt from the same frozen input. The module does not
fetch data or schedule itself. The minute feed adapter, entitlement check,
TradingView display, U4 consumption, and paper-order adapter are **unwired**.

## Canonical Inputs

- A frozen, SHA-256-bound ticker identity, settled 1-minute raw OHLCV bars,
  settled daily bars, point-in-time adjustment factors, a declared exchange
  calendar, and evidence-gate states.
- The declared minute calendar is checked against the independent, offline
  2026 SSE session table, including holidays; it cannot attest to its own
  completeness. V1 requires at least two consecutive exchange sessions of
  minutes and contiguous settled daily context through the as-of session.
  A missing whole day or stale daily context is `DATA_BLOCKED` even when the
  input hashes are internally consistent. Outside the independently covered
  2026 dates, the engine blocks rather than guessing an exchange calendar.
- Minute timestamps denote **bar end** in Asia/Shanghai. Normal sessions end
  at 09:31..11:30 and 13:01..15:00, yielding 240 expected bars per open day.
  A source adapter must establish this convention; raw provider timestamps
  cannot be silently relabelled. A missing, duplicate, future, nonfinite, or
  contradictory bar blocks the affected run.
- 5-, 15-, and 60-minute bars aggregate complete 1-minute bars without
  crossing the lunch break. Only closed bars can confirm a signal. Daily
  context must be settled. Original raw prices are the paper execution basis;
  point-in-time factors normalize older structure prices into the current
  as-of raw-price basis. A factor or corporate-action mismatch blocks levels.
  The V1 strategy receipt is produced only when `as_of` equals the close of a
  complete five-minute bucket. A partial bucket returns
  `FIVE_MINUTE_CUTOFF_MISMATCH`; it does not reuse the preceding proposal.
- TradingView may display and aid human review. It is not the canonical signal
  or execution feed. A minute bar does not prove the sequence of prints inside
  that minute. Intrabar ordering is `AMBIGUOUS_BAR`, not a fabricated fill.

## Atomic Evidence Catalogue

The engine records each detector independently, with source bar IDs and rule
parameters: confirmed HH/HL/LH/LL swings, BOS/CHOCH/MSS, equal-high/low pools,
liquidity sweeps and reclaim, displacement, bullish/bearish three-bar FVG,
pre-displacement opposing-candle order blocks and mitigation, premium/discount
range with equilibrium, OTE retracement zone, exchange-session bucket, and
cross-asset SMT divergence when a bound benchmark is available. `DATA_BLOCKED`
is an explicit detector result, never zero or `PASS`. The local numeric defaults
are *annotation/debug parameters*, not calibrated trading parameters.
The V1 detector rejects custom parameter maps rather than returning a default
rule hash for a changed configuration. A challenger uses a separately
versioned contract and cannot relabel old V1 receipts.
The consumed-objective and opposing-break correction uses `AR-SMC-ICT-DEBUG-2`;
receipts produced under `AR-SMC-ICT-DEBUG-1` retain their original rule identity.

Definitions that matter for replay:

- A pivot needs two strictly lower/higher closed neighbours on both sides;
  it only becomes known when the second right-hand bar closes. Equal extrema
  do not become pivots.
- BOS uses a **close** beyond the last already-confirmed swing in the current
  direction; CHOCH is the first contrary close; MSS requires contrary close
  plus a displacement candle. A wick alone is not a structure break.
- An equal-high/low pool is a pair of confirmed swings no farther apart than
  one exchange tick. A sweep crosses the known pool or pivot by at least one
  tick and reclaims within three closed bars **of the same exchange session**.
  Its label is dated at reclaim, not retroactively at the sweep. The recorded
  extreme is the most adverse price across the whole breach-to-reclaim window,
  and its bar ID remains attached to any resulting stop proposal. A high and
  a low reference on the same outside candle are spent independently.
- FVG is a three-bar gap confined to one exchange session, with at least one
  tick of width. An order block is the last opposing closed candle preceding
  a displacement-backed structure break. Mitigation and invalidation inspect
  only bars available by the receipt as-of.
- OTE is the 62%-79% retracement of a confirmed range. Session buckets are
  an A-share adaptation, not a claim about New York ICT killzones.
- SMT compares a bound benchmark on the same day's closed 15-minute bars.
  A bar breaking both high and low against a non-confirming benchmark is
  `CONFLICT`, not arbitrarily bullish or bearish.
  An intraday receipt cannot reuse yesterday's completed SMT bar before the
  current session has enough closed 15-minute benchmark bars.
  Missing benchmark evidence remains visible but is optional for a long
  template; a confirmed bearish or contradictory SMT observation vetoes one.
  A current opposing high sweep likewise makes all long templates `WAIT`.

## Strategy Proposal Templates

`SWEEP_RECLAIM`, `BOS_FVG_RETEST`, and `CHOCH_OB_RETEST` are separate registered
compositions. No single detector issues a strategy. Levels must cite source
bars: entry from confirmation/retest structure, stop below structural
invalidation with a frozen ATR14 buffer, target at identifiable opposing
liquidity. Include order type and raw-price conversion. If no objective target
exists, after-cost reward/risk is below 2, an input is blocked, or long and
short evidence conflicts, output `WAIT`, `NO_SETUP`, or `DATA_BLOCKED`, never
invent a percentage target. FVG/OB retest is a *limit-retest* proposal; the
current paper fill engine does not gain that execution mode through this PR.
Each template finds its nearest confirmed, still-unbreached opposing high from
its own rounded entry reference. A later high above a pivot consumes that
objective; when none remains, the template waits rather than reusing it. A
stop-trigger entry cannot choose a limit-retest objective.
The break confirming a retest must be tied by source bar ID to the FVG's
displacement/third bar or the OB's recorded break bar; an older unrelated
same-direction event is insufficient. A later opposing 5-minute structure
break also invalidates that earlier retest authorization. V1 proposes **long-only A-share**
references; bearish concepts are observations or conflicts, not short orders.
The V1 offline proposal checks 10 bps entry friction and 10 bps exit friction
and compares the nearest confirmed opposing high with a stop buffered by
0.5 times the latest 5-minute ATR14. These are unvalidated debug assumptions,
not an approved fee schedule or fill model. A reference entry/stop/target is
not a claim that an order could be filled at that price or that an intrabar
stop/target sequence is known.

All proposals are `WORKFLOW_DEBUG`, `no_trade_flag=true`,
`production_authority=false`, `paper_registration_allowed=false`, and
`claim_allowed=false`. The currently approved `manual-smc-v1` case contract
remains unchanged. Linking this engine to U4, manual case sealing, paper
registration, nightly, or live data requires separate reviewed work.

## Acceptance

Offline fixtures prove bar-grid completeness, point-in-time swing timing,
corporate-action blocking, deterministic detection and levels, source-hash
binding, negative and contradictory inputs, and no-network/no-production
behavior. An independent implementation must reproduce the same signal bar,
labels, and levels before the method is promoted. Runtime rights to historical
and real-time minute data are checked separately on the target host. Neither
a complete code catalogue nor a green replay proves a live feed or alpha.
