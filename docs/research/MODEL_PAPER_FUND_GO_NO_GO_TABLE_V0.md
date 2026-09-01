# Model Paper Fund Go/No-Go Table v0

Status: `DRAFT_OFFLINE_OPERATOR_TABLE / PAPER_ONLY / PRODUCTION_UNWIRED`

This table is the pre-open control sheet for the model paper fund. It answers
one question:

```text
Can today's research result move to the next paper-only stage, or must it stop?
```

It is not a stock recommendation list, not a U4 decision, not a paper order, and
not a real-capital trading instruction.

Not trading advice; research signal, human executes.
## Current Default

Until the same-day packet is filled and reviewed, the default state is:

```yaml
handoff_intent: STOP_BEFORE_RERUN
reason:
  - same-day preflight packet is not bound to the target trade date
  - daily source status must be verified before U1-U3
  - U4 pre-decision packet hash is not yet bound
  - U4-to-paper registration plan hash is not yet bound
authority:
  u4_selection_authority: HUMAN_JUNYAN_ONLY
  paper_registration_authority: HUMAN_JUNYAN_ONLY
  production_authority: false
  trade_authority: false
  paper_order_authority: false
  no_trade_flag: true
```

Stopping is a valid result. A stopped day preserves the denominator and prevents
false confidence.

## Go/No-Go Matrix

| Layer | Question | Required evidence | If missing |
|---|---|---|---|
| Repo | Is the operator using the latest reviewed code? | `git fetch --prune origin`, full `origin/main` SHA, clean worktree or named dirty files | `STOP_BEFORE_RERUN` |
| Source copy | Is the feature-store copy reviewed and intact? | reviewed copy path, checksum, `integrity_check=ok` | `DATA_BLOCKED` |
| Source scan | Are daily sources clean or explicitly blocked? | scan output, `scan_hash`, `source_scan_status` | `STOP_BEFORE_RERUN` |
| Daily publication | Are must-publish daily sources available? | `moneyflow_dc`, `cyq_perf`, and other required source status | `STOP_BEFORE_RERUN` |
| U1/U2 | Does the candidate pool preserve positive, negative, and blocked rows? | immutable bundle hash, same-day `as_of`, row counts by channel | `STOP_BEFORE_U4_REVIEW` |
| U3 | Does every candidate have a same-run battery row or explicit gap? | U3 battery hash, row count, `DATA_BLOCKED` rows | `STOP_BEFORE_U4_REVIEW` |
| Red flags | Did E1 vetoes propagate? | active E1 rows cannot be `allowed_for_u4_packet=true` | `STOP_BEFORE_U4_REVIEW` |
| U4 packet | Can Junyan review a hash-bound packet? | U4 pre-decision packet hash and blocker list | `STOP_BEFORE_U4_REVIEW` |
| Human U4 | Has Junyan committed a U4 decision? | ledger/receipt reference, selected count `0/3/4/5` | `STOP_BEFORE_PAPER_REGISTRATION` |
| Sealed case | Is the research case prospectively sealed? | thesis, valuation, wrong-if, manual SMC, causal cluster | `STOP_BEFORE_PAPER_REGISTRATION` |
| Paper bridge | Is paper registration governed by the approved bridge? | reviewed plan hash and bridge output | `STOP_BEFORE_PAPER_REGISTRATION` |
| Display | Is the public view paper-only? | v2 state with `paper_only=true` and `no_trade_flag=true` | `DATA_BLOCKED` |

## Current 2026-08-30 Baseline

The current operator baseline is preparation-only:

| Item | Current state | Meaning |
|---|---|---|
| Main baseline | `origin/main` contains the current research-chain contracts | code baseline can be named |
| Paper fund ledger | historical paper-only ledger exists | old records are not new semiconductor method samples |
| Public v2 state | last visible state is dated `20260806` | stale for the next paper cycle |
| Legacy public state | `public/data/model_portfolio.json` still contains `model_action` style fields | must not be used as the go-live paper source |
| U4 pre-decision | pending review path | no U4 handoff until packet is approved or separately authorized |
| Paper registration bridge | pending review path | no new paper order through a manual shortcut |
| Same-day source status | must be verified on the target trade date | default remains `STOP_BEFORE_RERUN` |

## Status Outputs

Use one of these outputs:

| Status | Meaning |
|---|---|
| `STOP_BEFORE_RERUN` | Do not start same-day U1-U3. Prepare or repair inputs. |
| `ALLOW_U1_U3_RERUN` | Same-day source gates pass; U1-U3 may run under the approved offline path. |
| `STOP_BEFORE_U4_REVIEW` | U1-U3 exists, but the packet is not fit for Junyan review. |
| `ALLOW_U4_REVIEW` | A hash-bound packet may be shown to Junyan. |
| `STOP_BEFORE_PAPER_REGISTRATION` | Junyan has not selected, or the case/bridge is incomplete. |
| `ALLOW_PAPER_REGISTRATION_PLAN_REVIEW` | A paper plan may be reviewed; it is not an order yet. |
| `DATA_BLOCKED` | Required evidence is missing, stale, unverifiable, or unpublished. |

No status may authorize real capital, live orders, or automatic security
selection.

## Morning Fill Template

```text
MODEL_PAPER_FUND_GO_NO_GO_V0
TARGET_TRADE_DATE:
PREPARED_BY: Reed
REVIEW_OWNER: Junyan
ORIGIN_MAIN_SHA:
WORKTREE_STATUS:
FEATURE_STORE_COPY_STATUS:
SOURCE_SCAN_HASH:
SOURCE_SCAN_STATUS:
DAILY_SOURCE_STATUS:
U1_U2_BUNDLE_HASH:
U3_BATTERY_HASH:
U4_PACKET_HASH:
U4_DECISION_REF:
SEALED_CASE_HASH:
PAPER_REGISTRATION_PLAN_HASH:
DISPLAY_SOURCE_STATUS:
HANDOFF_INTENT:
STOP_CONDITIONS:
NEXT_ALLOWED_ACTION:
AUTHORITY: HUMAN_JUNYAN_ONLY
PRODUCTION_AUTHORITY: false
TRADE_AUTHORITY: false
PAPER_ORDER_AUTHORITY: false
NO_TRADE_FLAG: true
```

## Display Source Rule

The paper-fund display must read a paper-only v2 state source. It must not fall
back to legacy recommendation-like fields from `public/data/model_portfolio.json`
such as `model_action`, `LONG`, `SHORT`, or `WATCH_SHORT`.

If the v2 state is missing, stale, malformed, or lacks `no_trade_flag=true`, the
display state is `DATA_BLOCKED`.

## Relationship To Research Quality

This table only decides whether a workflow may advance. It does not score the
research. Research quality is evaluated by `RESEARCH_QUALITY_SCORECARD_V0`;
later outcomes are evaluated by five-axis attribution.

Not trading advice; research signal, human executes.
