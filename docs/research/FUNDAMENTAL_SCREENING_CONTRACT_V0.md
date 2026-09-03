# Fundamental Screening Contract v0

Status: `DRAFT_OFFLINE_SCREENING_CONTRACT / RESEARCH_ONLY / PRODUCTION_UNWIRED`

This contract turns fundamental screening into a repeatable research intake
step. It does not select securities for Junyan, issue trading instructions, or
authorize paper registration.

Not trading advice; research signal, human executes.
## Why This Exists

The team wants a value-investing workflow, not a purely quantitative stock
picker. The machine should help narrow the all-A-share universe into explainable
research cohorts, while Junyan and Reed still decide what deserves deep
research.

The right output is not:

```text
buy these names
```

The right output is:

```text
these names entered the research pool because the evidence met these explicit
fundamental gates, these names failed for these reasons, and these data gaps
remain visible.
```

## Position In The Research Chain

```text
U0 eligible universe
  -> U1 independent scan channels
  -> fundamental screening contract
  -> U2 candidate pool
  -> U3 six-dimension battery
  -> U4 Junyan decision ledger
  -> thesis / valuation / SMC
  -> prospective paper cycle
```

Fundamental screening is one evidence channel. It cannot overwrite E1 red
flags, cannot replace U3, and cannot force U4 to select any name.

## Scope

V0 applies to all-A-share and industry-specific research intake. The default
universe is full-market U0. Industry ranking can change research priority, but
it cannot silently remove a security from the denominator.

The contract supports two modes:

| Mode | Meaning |
|---|---|
| `FULL_MARKET_RESEARCH_INTAKE` | Build a broad research cohort from all valid U0 securities. |
| `INDUSTRY_FOCUSED_INTAKE` | Apply the same contract inside a named industry such as semiconductor. |

## Threshold Profile

Every run must name a threshold profile. Thresholds are explicit research
assumptions, not hidden global defaults.

The profile reference is machine-checkable, not a free-form label:

```text
threshold_profile_ref pattern: ^[A-Z][A-Z0-9_]{2,63}_V[0-9]+$
example: SEMICONDUCTOR_FUNDAMENTAL_PROFILE_V0
```

The referenced profile object must include:

| Field | Meaning |
|---|---|
| `profile_id` | Versioned id; must equal `threshold_profile_ref`. |
| `method_version` | Research method version using the profile. |
| `universe_scope` | Full-market or named research universe. |
| `industry_scope` | Industry scope or `ALL_A_SHARE`. |
| `approved_by` | Human approver, or `null` while draft. |
| `approval_ref` | Approval anchor, or `null` while draft. |
| `data_cutoff` | Timezone-aware cutoff for the profile source. |
| `thresholds` | Non-empty list of threshold rows. |
| `source_refs` | Evidence sources used by the profile. |
| `missing_policy` | How missing evidence maps to stop/watch/reject. |
| `no_trade_flag` | Always `true`. |

Each threshold must include:

| Field | Meaning |
|---|---|
| `threshold_id` | Stable id, for example `PROFITABILITY_FLOOR`. |
| `metric` | The exact field being checked. |
| `operator` | `>=`, `<=`, `between`, `exists`, or `non_negative`. |
| `value` | Numeric value, range, or explicit existence rule. |
| `unit` | Percent, CNY, ratio, count, date, or `presence`. |
| `lookback_window` | The PIT window used, such as TTM or latest quarter. |
| `industry_adjustment` | Whether the value is absolute or industry-relative. |
| `source_ref` | Filing, exchange, database, or derived-artifact reference. |
| `missing_behavior` | `DATA_BLOCKED`, `REJECT`, or `WATCH_WITH_GAP`. |
| `reason` | Why this threshold matters economically. |

If a threshold cannot name its source and missing-data behavior, it cannot be
used.

The profile must define `DATA_BLOCKED`, `REJECT`, and `WATCH_WITH_GAP` handling
before it can be used in a run.

## Minimum Fundamental Gates

V0 requires these gates to be visible. Junyan may later approve industry-specific
numbers, but the machine may not hide the gate.

| Gate | Question | Allowed status |
|---|---|---|
| `PROFITABILITY_QUALITY` | Is profit real enough to study? | `PASS/WEAK/FAIL/DATA_BLOCKED` |
| `REVENUE_OR_ORDER_GROWTH` | Is demand improving or at least stable? | `PASS/WEAK/FAIL/DATA_BLOCKED` |
| `CASH_FLOW_QUALITY` | Does operating cash support earnings? | `PASS/WEAK/FAIL/DATA_BLOCKED` |
| `BALANCE_SHEET_RISK` | Is leverage, pledge, or liquidity risk tolerable? | `PASS/WEAK/FAIL/DATA_BLOCKED` |
| `VALUATION_CONTEXT` | Is valuation interpretable by scenario, not just cheap/expensive? | `PASS/WEAK/FAIL/DATA_BLOCKED` |
| `INDUSTRY_POSITION` | Does the company have a reason to matter in its chain? | `PASS/WEAK/FAIL/DATA_BLOCKED` |
| `RED_FLAG_INTEGRITY` | Are negative events preserved? | `PASS/FAIL/DATA_BLOCKED` |

No weighted total score may offset a failed `RED_FLAG_INTEGRITY` gate.

## Candidate Row Shape

Every output row must carry these fields before it can enter U2:

| Field | Meaning |
|---|---|
| `ts_code` | Security code from U0. |
| `display_name` | Registry display name. |
| `trade_date` | Same-day trade date for the screen. |
| `data_cutoff` | Timezone-aware cutoff for all inputs. |
| `industry_code` | Industry taxonomy code. |
| `industry_name` | Industry display name. |
| `threshold_profile_ref` | Versioned threshold profile used. |
| `fundamental_gate_status` | Status by minimum gate. |
| `source_refs` | Source files, URLs, or artifacts. |
| `data_status` | `COMPLETE/PARTIAL/STALE_INPUT/DATA_BLOCKED`. |
| `why_in` | Observable reason for entering the research pool. |
| `why_out` | Observable reason for exclusion or `null`. |
| `positive_channels` | Fundamental positives, may be empty. |
| `red_flag_channels` | Active red flags, may be empty. |
| `missing_evidence` | Missing fields, never silently omitted. |
| `method_version` | Research method version or `UNAVAILABLE` with reason. |
| `cohort_id` | Cohort denominator id or `UNAVAILABLE` with reason. |
| `causal_cluster_id` | De-cluster id for the 30-sample rule or `UNAVAILABLE` with reason. |
| `screening_status` | Final screening output state. |
| `allowed_for_u2` | Whether it can be shown in U2 review. |
| `no_trade_flag` | Always `true` in this contract. |

The reason fields are code-first. Free text may explain the code, but cannot
replace it.

| Field | Closed vocabulary |
|---|---|
| `why_in` | `PROFITABILITY_QUALITY_PASS`, `REVENUE_OR_ORDER_GROWTH_PASS`, `CASH_FLOW_QUALITY_PASS`, `BALANCE_SHEET_RISK_ACCEPTABLE`, `VALUATION_CONTEXT_INTERPRETABLE`, `INDUSTRY_POSITION_RELEVANT`, `CONTROL_SAMPLE_INCLUDED`, `OTHER_WITH_NOTE` |
| `why_out` | `E1_RED_FLAG_ACTIVE`, `PIT_SOURCE_TIMING_UNBOUND`, `MISSING_FUNDAMENTAL_FILLED_AS_ZERO`, `PROFITABILITY_QUALITY_FAIL`, `REVENUE_OR_ORDER_GROWTH_FAIL`, `CASH_FLOW_QUALITY_FAIL`, `BALANCE_SHEET_RISK_FAIL`, `VALUATION_CONTEXT_UNINTERPRETABLE`, `INDUSTRY_POSITION_UNCLEAR`, `DENOMINATOR_ROW_NOT_OMITTED`, `OTHER_WITH_NOTE` |
| `missing_evidence` | `PIT_FINANCIAL_SOURCE_MISSING`, `SOURCE_TIMESTAMP_MISSING`, `VALUATION_INPUT_MISSING`, `INDUSTRY_POSITION_EVIDENCE_MISSING`, `CASH_FLOW_DATA_MISSING`, `BALANCE_SHEET_FIELD_MISSING`, `CONTROL_DENOMINATOR_REASON_MISSING`, `NONE`, `OTHER_WITH_NOTE` |

`OTHER_WITH_NOTE` is allowed only when the row carries a non-empty operator or
reviewer note. This keeps unusual cases visible without reopening the whole
contract to unstructured explanations.

## Output States

| State | Meaning |
|---|---|
| `FUNDAMENTAL_RESEARCH_PASS` | Fundamental evidence is good enough to enter U2 review. |
| `FUNDAMENTAL_WATCH_WITH_GAP` | Interesting but missing evidence remains visible. |
| `DATA_BLOCKED` | Required PIT evidence is missing, stale, or unverifiable. |
| `REJECT_RED_FLAG` | Active red flag blocks the row regardless of positives. |
| `REJECT_QUALITY` | Fundamental weakness blocks the row. |
| `CONTROL_SAMPLE` | Random/control denominator row, not selected by quality. |

These states are research-intake states. They are not `BUY`, `SELL`, `LONG`, or
`SHORT`.

## Cohort Design

To avoid reducing the review set to only a few names, V0 keeps four buckets:

| Bucket | Purpose |
|---|---|
| `A_FUNDAMENTAL_PASS_TIMING_NEAR` | Strong enough to study and timing may be close. |
| `B_FUNDAMENTAL_PASS_TIMING_WAIT` | Strong enough to study, timing not ready. |
| `C_REPAIR_OR_REVERSAL_WATCH` | Potential repair, mismatch, or uncertainty case. |
| `D_CONTROL_OR_DENOMINATOR` | Random/control rows for later information-value testing. |

Buckets keep breadth without pretending every name is equally attractive.

## Hard Stops

Stop or mark `DATA_BLOCKED` when:

1. PIT source timing is not bound.
2. A fundamental field is missing and the row treats it as zero.
3. The threshold profile is absent or unversioned.
4. E1 red flags are offset by positive fundamentals.
5. `why_in` or `why_out` is missing.
6. rejected, blocked, watch, or control rows are omitted from the denominator.
7. `method_version`, `cohort_id`, or `causal_cluster_id` is missing without an
   explicit `UNAVAILABLE` reason.
8. any row claims selection, paper order, production, or trade authority.

## How Reed Uses This

Reed may:

- define candidate fields and threshold profiles;
- run offline screens and backtests;
- preserve accepted and rejected rows;
- report gaps, overfit risk, turnover, and cost sensitivity;
- prepare questions for Junyan.

Reed may not:

- select stocks for Junyan;
- weaken thresholds after seeing price action;
- promote a screen because one paper trade made money;
- hide rejected rows;
- turn the screen into a real or paper order.

## Relationship To K-Line / SMC Timing

Fundamentals answer:

```text
Is this company worth studying, and why?
```

SMC timing answers:

```text
Is now a disciplined paper-timing window, or should we wait?
```

A strong fundamental row can still be `WAIT`. A clean timing setup cannot repair
a broken thesis or hidden red flag.

Not trading advice; research signal, human executes.
