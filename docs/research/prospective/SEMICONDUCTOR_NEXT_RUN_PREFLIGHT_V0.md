# Semiconductor Next-Run Preflight v0

Status: `DRAFT_OPERATOR_MAP / OFFLINE_ONLY`

This note prepares the next semiconductor workflow-debug attempt. It maps the
current repository artifacts to the pre-U4 questions Reed must answer before
asking Junyan for a new U4 decision. It does not run the nightly chain, select
securities, register a paper case, or produce a trade instruction.

The immediate prior attempt,
`SEMICONDUCTOR_WORKFLOW_DEBUG_001_20260820`, stopped honestly at
`BLOCKED_BEFORE_U4`: 25 semiconductor U2 rows existed, all 25 were E1 red-flag
only, zero reached the same-run candidate manifest, zero received a U3 battery,
and zero were U4 ready.

After the positive-input work, the next run must also distinguish a genuinely
published source from a retryable publication gap. In particular, an empty
same-day `cyq_perf` response must be `SOURCE_PUBLICATION_PENDING` with
`retryable=true`, not a successful zero-row batch. The already-frozen
`20260824` empty `cyq_perf` batch is historical bad input and requires a
separately approved append-only migration or data PR before it can be repaired.

不是买卖指令；研究信号，human executes.

## Goal For The Next Attempt

The next attempt should answer one narrow operational question:

```text
Can the same-day U1-U3 evidence establish an admissible semiconductor U4
review pool without weakening red flags, inventing positive evidence, or
manually inserting names?
```

Possible honest outcomes:

- `BLOCKED_BEFORE_U4`: evidence is still insufficient or invalid;
- `U4_PACKET_READY_ZERO_SELECTION_ALLOWED`: a valid packet exists, but Junyan
  may still choose zero;
- `U4_PACKET_READY_FOR_JUNYAN`: valid packet exists and Junyan may choose
  exactly zero or three to five names;
- `SOURCE_PUBLICATION_PENDING`: at least one same-day source is not publishable
  yet and must remain retryable;
- `DATA_BLOCKED`: required input was absent, stale, or unverifiable.

No outcome in this preflight can imply method validity, alpha, win-rate,
profitability, portfolio promotion, or real-capital authority.

## Current Artifact Map

| Layer | Current source | Role | Preflight question |
|---|---|---|---|
| U0 registry | `experiments/research_funnel/security_registry.py` | Eligible A-share identity and qualification | Is the semiconductor universe visible and not silently dropped? |
| U1/U2/U3 funnel | `experiments/research_funnel/funnel_pipeline.py` | Six-channel scan, candidate review, manifest, battery, queue projection | Do semiconductor rows have positive-channel evidence or explicit blockers? |
| Semiconductor source inputs | `experiments/research_funnel/semiconductor_inputs.py` | Same-day price/flow/chip/fundamental source ingestion | Are empty same-day source responses retryable-pending instead of frozen as successful zero evidence? |
| Nightly isolated wrapper | `experiments/research_funnel/nightly_funnel.py` | Production observation wrapper and health summary | Is there a complete same-day bundle to inspect? Do not run from this PR. |
| Industry cohort | `experiments/research_funnel/industry_cohort.py` | Research refresh priority and representatives | Are semiconductor representatives only research anchors, not U4 selections? |
| U4 ledger | `experiments/research_funnel/u4_decision_ledger.py` | Durable human decision WAL after a valid packet exists | Is every packet row decided, including rejects and blockers? |
| Closure replay | `experiments/research_funnel/closure_experiment.py` | Offline packet/receipt/replay verification | Can packet, receipt, and queue be rebuilt from frozen inputs? |
| Research cycle | `experiments/research_funnel/research_cycle.py` | Sealed thesis/timing/paper replay after U4 | Not reached before committed U4 closure. |
| Execution realism | `experiments/execution_tracker/paper_execution_audit.py` | Paper engine realism receipt | Not reached before prospective paper registration. |
| Five-axis attribution | `experiments/research_funnel/five_axis_attribution.py` | Thesis/valuation/timing/execution/beta attribution | Not reached before a closed paper cycle. |

## Evidence Coverage Questions

The prior intake showed the important gap: E1 red flags worked, but positive
channels were too blocked to distinguish "no positive evidence" from "missing
evidence." The next preflight must make that distinction explicit.

| Evidence area | Minimum check | Stop if |
|---|---|---|
| E1 red flags | Red-flag rows remain visible with reason codes and source dates | Red flags are dropped, relabeled as positive, or used to satisfy selection pressure |
| Price/volume | `PRICE_VOLUME` has fresh same-day evidence or explicit `DATA_BLOCKED` | stale bars or absent bars are treated as neutral |
| Fund flow/chips | `FUND_FLOW_CHIPS` has fresh evidence or explicit `DATA_BLOCKED` | missing flow is interpreted as zero flow |
| Fundamental/valuation | `FUNDAMENTAL_VALUATION` has current evidence or explicit `DATA_BLOCKED` | absent valuation is interpreted as cheap/expensive |
| Industry/value chain | `INDUSTRY_VALUE_CHAIN` has semiconductor-specific evidence or explicit `DATA_BLOCKED` | industry rank or relative evidence is treated as company-level U4 readiness |
| Macro/cross-asset | `MACRO_CROSS_ASSET` is present as context or explicit `DATA_BLOCKED` | macro context is used to select a security or authorize action |

## Next-Run Readiness Checklist

Reed should answer these in order.

1. **Latest usable bundle**
   - Identify the latest `COMPLETE` or honest `PARTIAL` funnel bundle.
   - Reject any failed newer run with missing `target_trade_date`, incomplete
     publication, or runtime failure.
   - Record `trade_date`, `run_id`, `bundle_hash`, and bundle location.

2. **Source publication status**
   - Record daily sources `moneyflow_dc` and `cyq_perf` as `PUBLISHED`,
     `SOURCE_PUBLICATION_PENDING`, or `DATA_BLOCKED`.
   - Record quarterly `fina_indicator_pit` as `PUBLISHED`, `PARTIAL`,
     `STALE_INPUT`, or `DATA_BLOCKED`; it must not use
     `SOURCE_PUBLICATION_PENDING`.
   - Stop if an empty same-day `cyq_perf` response is represented as a
     successful zero-row batch.
   - Stop if the run depends on the frozen `20260824` empty `cyq_perf` batch
     without a separately approved append-only migration or data PR.
   - If `cyq_perf` is `SOURCE_PUBLICATION_PENDING`, do not rerun at the same
     publication window. Wait for the post-close retry window, then run the
     source publication check again before any U4 packet is generated.

3. **Semiconductor cohort visibility**
   - Count all semiconductor U2 rows.
   - Separate non-red-flag candidates, red-flag-only rows, relative-research
     anchors, and random/control rows.
   - Record whether the cohort source is whole-market U2, Industry Cohort OS,
     or both.

4. **Same-run U3 coverage**
   - For every semiconductor row admitted to review, bind a U3 battery row hash
     or explicit `DATA_BLOCKED`.
   - Do not create a U4 packet from U2-only rows.

5. **Positive-channel evidence**
   - List which rows entered through independent positive U1 channels.
   - Do not allow E1 red flags, industry rank, macro context, or manual urgency
     to substitute for a positive company channel.

6. **Diagnostic cross-check**
   - Run the merged U1-U3 diagnostic before any U4 packet handoff:

```powershell
python3 experiments/research_funnel/semiconductor_evidence_diagnostic.py --intake <intake-receipt> --output <diagnostic-output>
```

   - The diagnostic output must bind the same intake receipt, recompute counts
     from `evidence_rows`, verify `evidence_rows_hash`, and report
     `BLOCKED_BEFORE_U4`, `SOURCE_PUBLICATION_PENDING`, `DATA_BLOCKED`, or a
     U4-ready state without manual recounting.

7. **U3 red-flag propagation**
   - Check that U3-level fundamental or valuation red flags remain visible in
     the candidate packet.
   - Stop if positive evidence, source repair, industry rank, or manual urgency
     hides a red flag propagated from U3 to U4.

8. **U4 packet eligibility**
   - Generate a packet only if source hashes, row hashes, and battery hashes are
     bound.
   - The packet status remains `AWAITING_JUNYAN_REVIEW`.
   - Junyan may choose exactly zero or three to five names.

9. **Post-U4 boundary**
   - A `SELECT` means offline deep research only.
   - It does not authorize paper registration, order creation, model claims, or
     production wiring.

## Retry Timetable For Pending Daily Sources

`SOURCE_PUBLICATION_PENDING` is a stop state, not a soft pass. Use this retry
discipline before a same-day rerun:

| Source | First check | Retry window | Required proof before rerun |
|---|---|---|---|
| `moneyflow_dc` | Same-day post-close source window | One bounded retry after transport or publication delay | Non-empty publication metadata or explicit `DATA_BLOCKED` reason |
| `cyq_perf` | Same-day post-close source window | Later post-close retry window; do not retry at the original 16:04-like window | `PUBLISHED` status, non-frozen source batch, and no dependency on unrepaired frozen `20260824/20260825` batches |

If a retry still returns `SOURCE_PUBLICATION_PENDING`, the correct output is a
blocked preflight packet. Do not freeze it as a successful zero-row batch.

## Forbidden Shortcuts

- Do not run production nightly or `~/ar-live` from this preparation PR.
- Do not reuse an incomplete newer nightly output because it has a newer date.
- Do not turn a retryable source publication gap into `COMPLETE`, zero
  evidence, or an immutable successful source batch.
- Do not repair the frozen `20260824` `cyq_perf` anomaly without a separately
  approved append-only migration or data PR.
- Do not lower U4 selection count to one or two.
- Do not insert a manual semiconductor name to make a first cycle happen.
- Do not treat Industry Cohort representatives as U4-ready rows.
- Do not treat relative price evidence as absolute company evidence.
- Do not use paper P&L language before a prospective paper registration and
  closed review exist.
- Do not call a model or external data source from this preflight document.

## Suggested Human Handoff Packet

When the next same-day bundle is available, Reed should send Junyan a packet
with this outline:

```text
Semiconductor next-run preflight

Source:
- trade_date:
- run_id:
- bundle_hash:
- candidate_review rows:
- candidate_manifest semiconductor rows:
- candidate_battery semiconductor rows:
- source publication status:
- historical frozen-batch dependency:

Channel status:
- E1_EVENT:
- PRICE_VOLUME:
- FUND_FLOW_CHIPS:
- FUNDAMENTAL_VALUATION:
- INDUSTRY_VALUE_CHAIN:
- MACRO_CROSS_ASSET:

Counts:
- semiconductor U2 rows:
- red-flag-only rows:
- positive-channel rows:
- same-run U3 rows:
- U4-ready rows:
- DATA_BLOCKED rows:

Diagnostic:
- diagnostic command:
- diagnostic output path:
- diagnostic status:
- evidence_rows_hash verified:
- U3 red flags propagated to U4:

Decision boundary:
- Junyan may choose zero or exactly 3-5.
- SELECT authorizes offline deep research only.
- no_trade_flag=true.
```

If the U4-ready row count is zero, the correct handoff is a blocked intake
receipt, not a request to relax the rules.
