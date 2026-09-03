# Model Paper Fund Post-Close Report Template v0

Status: `DRAFT_OPERATOR_TEMPLATE / PAPER_ONLY / SETTLED_BAR_REQUIRED`

This template is used after the market has closed and settled bars are available.
It records the paper fund's official daily state only through the approved paper
engine outputs. It must show gaps honestly instead of mixing complete marks with
cost marks or intraday observations.

Not trading advice; research signal, human executes.

## Authority Boundary

Every filled report must keep these authority flags:

```text
paper_only=true
no_trade_flag=true
trade_authority=false
production_authority=false
real_capital_authority=false
```

Junyan owns all U4 and real-capital decisions. The system records paper evidence,
paper status, and review questions.

## Required Header

```yaml
report_type: POST_CLOSE_REPORT
template_version: MODEL_PAPER_FUND_POST_CLOSE_REPORT_TEMPLATE_V0
trade_date: YYYYMMDD
generated_at_cn: YYYY-MM-DD HH:MM
prepared_by: Reed
review_owner: Junyan
settled_bar_status: PUBLISHED / PENDING / DATA_BLOCKED
fund_snapshot_hash: null
orders_hash: null
decision_log_hash: null
nav_history_hash: null
position_review_hash: null
court_10d_hash: null
watch_dynamic_hash: null
paper_only: true
no_trade_flag: true
trade_authority: false
production_authority: false
real_capital_authority: false
```

If any hash is unavailable, keep it `null` and explain the gap. Do not invent a
hash to make the report look complete.

## Required Engine Order

```text
settled bars available
  -> model_paper_fund daily advance
  -> official NAV only when all required marks are complete
  -> position_review
  -> court_10d when a checkpoint is due
  -> watch_dynamic refresh when applicable
  -> post-close report
```

If settled bars are not available, the report status must be `DATA_BLOCKED` or
`PENDING`. The report must not create an official NAV from partial marks.

## Body Template

```markdown
## Post-Close Paper Fund Report

Status: COMPLETE / PARTIAL / PENDING / DATA_BLOCKED

### 1. Source Status
- settled_bar_status:
- missing symbols:
- stale symbols:
- blocked reason:

### 2. Paper Execution State
- new paper fills:
- new paper exits:
- no-fill orders:
- blocked fills or exits:
- corporate-action freezes:

### 3. Official NAV State
- official_nav_status:
- latest NAV:
- cash:
- open positions:
- closed trades:
- why NAV is DATA_BLOCKED if blocked:

### 4. Position Review
- position_review status:
- risk review items:
- stale pending orders:
- theme/cash concentration notes:
- questions for Junyan:

### 5. T Checkpoints
- T+1:
- T+3:
- T+5:
- T+10:
- DATA_BLOCKED checkpoint evidence:

### 6. Five-Axis Notes
- thesis:
- valuation:
- timing / SMC:
- execution:
- market / industry beta:
- paper P&L note:

### 7. Next Allowed Step
- next paper-only action:
- required human review:
- unresolved gaps:
```

## Stop Rules

Stop and report `DATA_BLOCKED` when:

- any filled position lacks a target-date settled mark;
- some positions use target-date marks while others fall back to cost marks;
- a paper execution event lacks a reproducible engine output;
- a T+ checkpoint lacks the required thesis, valuation, timing, execution, or
  market evidence;
- a report attempts to count the first 5-10 semiconductor cycles as
  method-validity samples;
- a report implies live trading promotion before at least 30 independent,
  de-clustered closed samples and cross-industry replication.

