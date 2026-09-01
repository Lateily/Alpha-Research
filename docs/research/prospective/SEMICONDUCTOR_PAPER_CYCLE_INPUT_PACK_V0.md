# Semiconductor Paper Cycle Input Pack v0

Status: `DRAFT_OPERATOR_TEMPLATE / OFFLINE_ONLY`

This template prepares the next semiconductor prospective paper-cycle attempt
after `SEMICONDUCTOR_WORKFLOW_DEBUG_001_20260820` stopped before U4. It is an
input checklist, not a selected stock list, research thesis, paper order, or
method-validity claim.

The template exists so Reed can assemble the same-day evidence package before
Junyan decides whether any names enter U4. It must not weaken the red-flag
gate, manually insert names, reuse stale nightly descendants, or relabel a
blocked intake as a registered cycle.

All outputs keep:

- `sample_eligible=false`;
- `method_claim_sample_eligible=false`;
- `portfolio_promotion_eligible=false`;
- `production_authority=false`;
- `trade_authority=false`;
- `claim_allowed=false`;
- `no_trade_flag=true`.

不是买卖指令；研究信号，human executes.

## Why This Exists

The first real-data semiconductor intake found 25 U2 rows, but all 25 entered
through `E1_EVENT` red flags alone. The same run had broad gaps in positive
channels and produced zero semiconductor U3 rows, zero U4-ready rows, and zero
prospective cases.

The next attempt therefore needs a stricter intake pack:

1. prove that the same-day U1-U3 bundle is complete enough to distinguish
   positive evidence from missing data;
2. preserve every rejected, deferred, no-trade, and data-blocked row;
3. present Junyan with a hash-bound U4 packet only after U2 and U3 evidence
   are visible;
4. stop honestly if the result is again zero selected names.

## Required Source Pack

Reed must fill this section before asking for U4 review.

| Field | Required value | Filled value |
|---|---|---|
| `trade_date` | Same-day A-share trade date, `YYYYMMDD` | `TODO` |
| `run_id` | Immutable funnel run id | `TODO` |
| `method_version` | Registered research workflow version, or `UNAVAILABLE` with reason | `TODO` |
| `bundle_dir` | Read-only immutable bundle path | `TODO` |
| `bundle_hash` | Hash from bundle manifest | `TODO` |
| `candidate_review_sha256` | Hash of U2 review artifact | `TODO` |
| `candidate_manifest_hash` | Hash of candidate manifest | `TODO` |
| `candidate_battery_hash` | Hash of full U3 battery artifact | `TODO` |
| `u4_packet_hash` | Hash-bound U4 packet, if generated | `TODO / NOT_GENERATED` |
| `u4_packet_status` | `AWAITING_JUNYAN_REVIEW` or stop reason | `TODO` |
| `data_cutoff` | Timezone-aware ISO-8601 cutoff | `TODO` |
| `source_scope` | `PRODUCTION_RUNTIME_READ_ONLY` or offline fixture path | `TODO` |
| `source_publication_status` | `PUBLISHED/SOURCE_PUBLICATION_PENDING/DATA_BLOCKED` per source | `TODO` |

Do not copy production runtime state into a PR unless a separate contract
explicitly approves that evidence transfer. A PR may record hashes, counts,
and material decision facts.

Hash fields must preserve the exact format emitted by the source artifact. If
the upstream artifact emits a bare 64-character SHA-256 hex string, keep it
bare. If it emits a prefixed value such as `sha256:<hex>`, keep the prefix.
Do not convert between formats while filling this pack.

## Source Publication Gate

Before filling candidate rows, Reed must prove each required same-day source is
published, retryable-pending, or explicitly blocked. A same-day empty source
response is not evidence that every issuer is missing.

| Source | Required state | Stop if |
|---|---|---|
| `moneyflow_dc` | `PUBLISHED` or explicit transport/data blocker | Missing flow is treated as zero flow |
| `cyq_perf` | `PUBLISHED` or `SOURCE_PUBLICATION_PENDING` with `retryable=true` | Empty same-day response is frozen as a successful zero-row batch |
| `fina_indicator_pit` | `PUBLISHED/PARTIAL/STALE_INPUT` or explicit filing-window blocker | Absent fundamentals are treated as neutral valuation |

If `cyq_perf` is `SOURCE_PUBLICATION_PENDING`, do not generate a U4 packet from
that run. Wait for a later retry or record `DATA_BLOCKED`. The previously
frozen `20260824` empty `cyq_perf` batch cannot be repaired by ordinary retry;
it needs a separately approved append-only migration or data PR.

## Channel Coverage Gate

The next attempt must show whether the semiconductor cohort has evidence in
the six independent U1 channels. Channels do not offset each other, and red
flags cannot be canceled by price strength or flow.

| Channel | Required state | Filled state | Notes |
|---|---|---|---|
| `E1_EVENT` | `COMPLETE/PARTIAL/STALE_INPUT/DATA_BLOCKED` | `TODO` | Red flags stay visible |
| `PRICE_VOLUME` | `COMPLETE/PARTIAL/STALE_INPUT/DATA_BLOCKED` | `TODO` | No stale bars as fresh evidence |
| `FUND_FLOW_CHIPS` | `COMPLETE/PARTIAL/STALE_INPUT/DATA_BLOCKED` | `TODO` | Missing flow is not zero flow |
| `FUNDAMENTAL_VALUATION` | `COMPLETE/PARTIAL/STALE_INPUT/DATA_BLOCKED` | `TODO` | No absent valuation as cheap/expensive |
| `INDUSTRY_VALUE_CHAIN` | `COMPLETE/PARTIAL/STALE_INPUT/DATA_BLOCKED` | `TODO` | Semiconductor cohort evidence required |
| `MACRO_CROSS_ASSET` | `COMPLETE/PARTIAL/STALE_INPUT/DATA_BLOCKED` | `TODO` | Context only; no automatic trade action |

If any hard-required channel is unavailable, the pack must say
`DATA_BLOCKED` and name the missing source. It must not fill the gap with `0`,
old data, or analyst memory.

## Candidate Intake Row Template

Every semiconductor row admitted to the U2 review or rejection cohort should be
recorded with this shape before U4 review.

| Field | Meaning | Value |
|---|---|---|
| `ts_code` | Security code | `TODO` |
| `display_name` | Registry display name | `TODO` |
| `semiconductor_segment` | Equipment/materials/design/foundry/packaging/etc. | `TODO` |
| `cohort_id` | Same-day cohort id, or `UNAVAILABLE` with reason | `TODO` |
| `causal_cluster_id` | De-cluster id for independent-sample counting, or `UNAVAILABLE` with reason | `TODO` |
| `u2_row_hash` | Hash of the exact U2 row | `TODO` |
| `u3_battery_row_hash` | Hash of the same-run U3 row, or `DATA_BLOCKED` | `TODO` |
| `primary_channel` | Main U1 entry channel | `TODO` |
| `positive_channels` | List, may be empty | `TODO` |
| `red_flag_channels` | List, may be empty | `TODO` |
| `review_status` | `U3_BATTERY_REVIEW/EXCLUDED_RED_FLAG/DATA_BLOCKED/...` | `TODO` |
| `blocked_reasons` | Closed list from the packet, may be empty only when unblocked | `TODO` |
| `missing_evidence` | Closed list of missing evidence codes | `TODO` |
| `why_in` | Observable reason for entering review | `TODO` |
| `why_out` | Observable reason for exclusion, if excluded | `TODO` |
| `question_for_junyan` | Research question if U4-ready | `TODO / NOT_READY` |
| `allowed_for_u4_packet` | `true/false` | `TODO` |

`allowed_for_u4_packet=true` is not a selection. It only means the row may be
shown to Junyan in the packet. Junyan may still decide `SELECT`, `REJECT`,
`DEFER`, `NO_TRADE`, or `DATA_BLOCKED`.

That freedom applies only to candidates without packet-level blockers. Rows
with `U3_BATTERY_INCOMPLETE` must remain `DATA_BLOCKED`; rows with active E1
red flags must remain `REJECT` with the red-flag reason preserved. If one row
violates those forced meanings, the whole decision batch must refuse to land.

## Pre-U4 Stop Conditions

Stop before U4 if any of these is true:

1. the bundle is not immutable or lacks a manifest hash;
2. the run is not the same-day source for both U2 and U3;
3. semiconductor rows have no same-run U3 battery and no explicit
   `DATA_BLOCKED`;
4. E1 red flags are present but not preserved in candidate reason codes;
5. positive-channel gaps are silently treated as no signal;
6. the U4 packet cannot bind exact U2 row hashes and U3 row hashes;
7. a failed or incomplete newer nightly output is being reused as if fresh;
8. any required source is `SOURCE_PUBLICATION_PENDING` but the packet treats it
   as `PUBLISHED`, `COMPLETE`, or zero evidence;
9. the historical `20260824` empty `cyq_perf` batch is used without a separately
   approved append-only migration or data repair;
10. the review set would force one or two selections instead of exactly zero or
   three to five;
11. any artifact claims trading, production, alpha, win-rate, or profitability
   authority.

An honest zero-selection result is valid. Lowering the threshold to make the
project produce a first paper case is not valid.

## U4 Handoff Checklist

Before sending to Junyan, Reed should provide:

- the source pack table above;
- the channel coverage table above;
- the source publication status for `moneyflow_dc`, `cyq_perf`, and
  `fina_indicator_pit`;
- a candidate intake table for all semiconductor rows in scope;
- `method_version`, `cohort_id`, `causal_cluster_id`, and `blocked_reasons`
  visibility, using `UNAVAILABLE` only with an explicit reason;
- count totals for U2 rows, U3 rows, U4-ready rows, red-flag exclusions, and
  `DATA_BLOCKED` rows;
- the U4 packet hash if one exists;
- explicit statement that Junyan may choose zero or exactly three to five
  names;
- explicit statement that a `SELECT` only authorizes offline deep research,
  not a paper order;
- `no_trade_flag=true`.

## After U4

Only after a committed U4 decision ledger closure may a selected name move to
the next offline steps:

```text
U4_SELECTED
  -> factpack and thesis draft
  -> valuation adapter and wrong-if
  -> manual settled-E3 SMC timing ticket
  -> prospective case seal
  -> later settled bars and outcome facts
  -> paper replay
  -> mechanical replay verification
  -> Junyan postmortem confirm/dispute
  -> five-axis attribution
```

`WAIT`, `NO_TRADE`, `NO_FILL`, `CORPORATE_ACTION_BREAK`, `UNRESOLVED`, and
`DATA_BLOCKED` are all valid workflow-debug outcomes. None of them may be
hidden to make the first batch look cleaner.

## Current Owner Split

| Owner | Responsibility |
|---|---|
| Junyan | Research method, U4 decisions, paper-cycle approval, final attribution interpretation, real-capital authority |
| Reed | Contracts, source tables, evidence hashes, missing-data visibility, offline replay preparation, paper logs and review tables |
| Machine system | Preserve accepted and rejected samples, enforce no-look-ahead boundaries, run paper-only checks, emit scorecards |

The machine system does not select securities, upgrade a method, or issue a
trade instruction.
