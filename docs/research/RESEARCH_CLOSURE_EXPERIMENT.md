# Offline Research Closure Experiment

## Purpose

This experiment proves that the existing U1-U4 contracts can be replayed as one
evidence chain without touching the production nightly runtime. It does not
measure return performance and does not claim that the funnel is effective or
ineffective.

The replay order is:

`frozen U1/U2 bundle -> random-control verification -> same-day U3 battery -> U4 review packet -> packet-bound review receipt -> U4 queue -> blocked U5 handoff`

## Authority Boundary

- The tool prepares a review packet. It does not select securities.
- A receipt must name Junyan, quote the packet-hash prefix, and remain scoped to
  offline research replay.
- A JSON name is not identity proof. Every packet, receipt, queue, and report
  therefore records identity verification as unavailable and production
  authority as false.
- U5 remains `DATA_BLOCKED` until factpack, decision sheet, wrong-if, and a
  prospective causal cluster have been completed and reviewed.
- Random-control rows never contribute to causal-cluster claim counts.

## Replay Artifacts

`ar.u4_review_packet.v1.0` binds the immutable funnel bundle, U1/U2 hashes,
same-day battery, ready pool, and random-control frame. Its status is always
`AWAITING_JUNYAN_REVIEW`.

`ar.u4_review_receipt.v1.0` binds exactly one packet and three to five ready
securities. Every selection needs a research question and a selection reason.
The receipt is evidence of the supplied text, not cryptographic proof of human
identity.

`ar.research_closure_experiment.v1.0` records the full hash chain and the
expected U5 block. The result bundle preserves the packet, receipt, U4 queue,
report, and a byte-level manifest together. It structurally fixes
`claim_allowed=false`, `no_trade_flag=true`, and `production_authority=false`.

## Commands

Create a review packet from an immutable bundle and same-day battery:

```bash
AR_OFFLINE=1 python3 experiments/research_funnel/closure_experiment.py packet \
  --bundle /tmp/funnel/20260813 \
  --battery /tmp/battery.json \
  --generated-at 2026-08-13T10:00:00+00:00 \
  --output /tmp/u4-review-packet.json
```

After Junyan supplies a packet-bound receipt, run the replay:

```json
{
  "schema": "ar.u4_review_receipt",
  "schema_version": "1.0",
  "receipt_class": "HUMAN_PROVIDED_UNVERIFIED_IDENTITY",
  "decision": "APPROVED_FOR_OFFLINE_RESEARCH_REPLAY",
  "claimed_reviewer": "Junyan",
  "identity_verification": "UNAVAILABLE",
  "production_authority": false,
  "packet_hash": "<exact packet_hash>",
  "reviewed_at": "<timezone-aware ISO-8601>",
  "authorization_text": "批准离线研究回放，绑定 packet_hash <first-12-chars>，不产生生产权限。",
  "selections": [
    {
      "ts_code": "<ready ts_code>",
      "research_question": "<question to answer>",
      "selection_reason": "<why this name enters deep research>"
    }
  ],
  "receipt_hash": "<canonical receipt hash>",
  "disclaimer": "不是买卖指令；研究信号，human executes."
}
```

The receipt must contain three to five selections. The tool never creates this
receipt for the reviewer and never treats the claimed name as identity proof.

Save that human-authored object without `receipt_hash` as a draft, then seal
its canonical fields against the packet:

```bash
AR_OFFLINE=1 python3 experiments/research_funnel/closure_experiment.py receipt \
  --packet /tmp/u4-review-packet.json \
  --draft /tmp/u4-review-receipt-draft.json \
  --output /tmp/u4-review-receipt.json
```

```bash
AR_OFFLINE=1 python3 experiments/research_funnel/closure_experiment.py replay \
  --bundle /tmp/funnel/20260813 \
  --battery /tmp/battery.json \
  --packet /tmp/u4-review-packet.json \
  --receipt /tmp/u4-review-receipt.json \
  --generated-at 2026-08-13T10:06:00+00:00 \
  --output-dir /tmp/research-closure-result
```

The output directory must not already exist. Replays are immutable by default;
a rerun uses a new directory rather than overwriting earlier evidence.

Independently verify every byte and contract in a completed result bundle:

```bash
AR_OFFLINE=1 python3 experiments/research_funnel/closure_experiment.py verify \
  --output-dir /tmp/research-closure-result
```

## Exit Criteria

This offline slice is complete only when:

1. The frozen random draw is reproducible and any draw mutation fails closed.
2. A stale or differently hashed packet cannot reuse a receipt.
3. U4 selections are a three-to-five-name subset of the same-day ready pool.
4. The report can neither unlock a claim nor acquire trading authority.
5. U5 remains visibly blocked instead of being silently skipped.
6. The behavioral suite and governance mutations pass with sockets disabled.

Production funnel observation was deployed separately under PR #269. The
offline closure in this document is not wired to that production runtime.

## Full Offline Paper Cycle

`research_cycle.py` continues from the verified U4 result without changing the
authority of `closure_experiment.py`. The first bundle still ends at a visible
U5 block. A separately authored and prospectively sealed case may clear that
block only when every downstream contract is present.

The replay order is:

`verified U4 bundle -> E1/E2 factpack -> qualified thesis core -> hash-bound red-team PASS -> thesis ticket -> timing ticket -> Decision Pack -> existing Model Paper Fund fill engine -> mechanical outcome review -> hash-bound human postmortem`

The orchestrator validates supplied research; it does not write the facts,
thesis, timing judgment, U4 choice, or postmortem attribution. The simulated
fund remains paper-only and the single existing fill engine remains the source
of T+1, gap, stop, and target semantics.

### Cycle Identity And Legal States

One deterministic `research_cycle_id` binds the U4 closure hashes, ticker, and
prospective case hash. Every transition carries its sequence, timestamp, and
evidence hash. A successful closed example advances through:

`U4_SELECTED -> FACTPACK_READY -> THESIS_REVIEWED -> TIMING_REVIEWED -> PAPER_REGISTERED -> FILLED -> CLOSED -> REVIEW_READY -> REVIEWED`

`WAIT`, portfolio refusal, or another execution gate may instead end at
`NO_TRADE`. That is a complete and honest result, not a failed replay.

### Prospectively Sealed Inputs

The research case is sealed before outcome bars are supplied. It must bind:

- the exact U4 closure bundle, review receipt, and queue hash;
- a COMPLETE factpack with at least one validated E1 item and no post-U4 fact;
- a Core Thesis Factory core that passes `decision_sheet.qualify`;
- a five-axis red-team PASS bound to the exact core hash;
- a `STARTER_CANDIDATE` thesis ticket with R/R at least 2:1;
- a same-day timing ticket whose market, sector, settled flow, structure, and
  portfolio gates all support `RECLAIM_REVIEW`;
- an existing eight-section Research Decision Pack;
- one prospective causal-cluster object, marked non-counting for this offline
  replay;
- a paper risk budget inside the Model Paper Fund policy range.

Outcome bars are a second, later artifact. Any pre-registration, duplicate,
unordered, malformed, or differently hashed bar is rejected. Intraday evidence
remains non-sample-eligible; official replay changes state only through settled
bars.

### Commands

Seal an analyst-authored prospective case against a verified U4 result:

```bash
AR_OFFLINE=1 python3 experiments/research_funnel/research_cycle.py seal-case \
  --closure-bundle /tmp/research-closure-result \
  --input /tmp/research-case-draft.json \
  --output /tmp/research-case.json
```

After settled bars exist, seal them separately and replay the paper cycle:

```bash
AR_OFFLINE=1 python3 experiments/research_funnel/research_cycle.py seal-bars \
  --closure-bundle /tmp/research-closure-result \
  --case /tmp/research-case.json \
  --input /tmp/settled-bars-draft.json \
  --output /tmp/settled-bars.json

AR_OFFLINE=1 python3 experiments/research_funnel/research_cycle.py replay \
  --closure-bundle /tmp/research-closure-result \
  --case /tmp/research-case.json \
  --bars /tmp/settled-bars.json \
  --generated-at 2026-08-17T16:10:00+00:00 \
  --output-dir /tmp/research-cycle-result
```

The result directory is immutable and independently rebuildable from its
prospective case and settled bars. It contains the transition trace, paper fund
snapshot, NAV/P&L, T+1/3/5/10 windows, and an `AWAITING_HUMAN_REVIEW` mechanical
review.

The postmortem is authored only after that result exists. Its text must quote
the mechanical review hash and choose one attribution from `PROCESS_OK`,
`THESIS_ERROR`, `TIMING_ERROR`, `SIZING_ERROR`, `MARKET_SHOCK`, or `DATA_GAP`.
Rule-change proposals are recorded but become effective only for future cases.

```bash
AR_OFFLINE=1 python3 experiments/research_funnel/research_cycle.py seal-review \
  --cycle-bundle /tmp/research-cycle-result \
  --input /tmp/postmortem-draft.json \
  --output /tmp/postmortem.json

AR_OFFLINE=1 python3 experiments/research_funnel/research_cycle.py finalize-review \
  --closure-bundle /tmp/research-closure-result \
  --cycle-bundle /tmp/research-cycle-result \
  --receipt /tmp/postmortem.json \
  --output-dir /tmp/research-cycle-reviewed
```

All result directories are built in a staging directory, fully verified, and
then atomically published. The sealed case, settled bars, review receipt, and
result directories all refuse overwrite; a rerun must use new paths. JSON
inputs also reject duplicate keys and non-finite constants instead of silently
normalizing them.

### Full-Cycle Exit Criteria

1. One positive fixture reaches `REVIEWED` through the existing paper fill
   engine, with no registration-day fill.
2. One valid `WAIT` fixture ends at `NO_TRADE` with zero fund orders.
3. A factpack without E1, an unqualified thesis, a mismatched red-team PASS, or
   diverging dual-ticket levels fails before paper registration.
4. Pre-registration outcome bars fail closed.
5. Self-consistently rehashed output tampering is caught by deterministic
   rebuild, not only by byte hashes.
6. A postmortem cannot predate or detach from its mechanical outcome.
7. All artifacts keep `claim_allowed=false`, `production_authority=false`, and
   `no_trade_flag=true`.
8. Every load-bearing gate has a mutation test and the complete suite passes
   with sockets disabled.

This proves orchestration and evidence continuity only. It does not prove that
the research method makes money, deploy a production writer, or authorize a
real trade.

不是买卖指令；研究信号，human executes.
