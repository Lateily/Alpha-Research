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

Production observation remains a separate approval and deployment task under
PR #269.

不是买卖指令；研究信号，human executes.
