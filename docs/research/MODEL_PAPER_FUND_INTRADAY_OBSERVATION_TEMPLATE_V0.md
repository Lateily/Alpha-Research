# Model Paper Fund Intraday Observation Template v0

Status: `DRAFT_OPERATOR_TEMPLATE / PAPER_ONLY / INTRADAY_OBSERVATION_ONLY`

This template records what Reed sees during the trading day after a research
idea has entered the paper-fund workflow. It is a note-taking surface only. It
does not create an official fill, official exit, official NAV, paper order,
method-validity sample, or real-capital action.

Not trading advice; research signal, human executes.

## Authority Boundary

Every filled template must keep these authority flags:

```text
paper_only=true
no_trade_flag=true
trade_authority=false
production_authority=false
official_fill_status=null
official_exit_status=null
official_nav_status=null
```

If an operator cannot honestly keep those values, the note must stop at
`DATA_BLOCKED` and go back to Junyan before any downstream paper-fund step.

## Required Header

```yaml
observation_type: INTRADAY_OBSERVATION
template_version: MODEL_PAPER_FUND_INTRADAY_OBSERVATION_TEMPLATE_V0
trade_date: YYYYMMDD
checkpoint_time_cn: HH:MM
prepared_by: Reed
review_owner: Junyan
source_scope: SCREEN_OBSERVATION_ONLY
related_u4_packet_hash: null
paper_registration_id: null
ticker: null
security_name: null
method_version: null
cohort_id: null
causal_cluster_id: null
paper_only: true
no_trade_flag: true
trade_authority: false
production_authority: false
official_fill_status: null
official_exit_status: null
official_nav_status: null
```

`related_u4_packet_hash` and `paper_registration_id` stay `null` until the
corresponding reviewed artifacts exist. Do not invent placeholders.

## Observation Status

Choose exactly one:

| Status | Meaning |
|---|---|
| `OBSERVE` | The note records visible facts, with no downstream action. |
| `WAIT_FOR_SETTLED_BAR` | Intraday information is visible, but official paper accounting must wait for settled data. |
| `QUESTION_FOR_JUNYAN` | Reed needs a human research decision or clarification. |
| `RISK_REVIEW_NEEDED` | A red flag, wrong-if clue, or thesis risk needs human review. |
| `DATA_BLOCKED` | Required context is missing, stale, conflicting, or unverifiable. |

## Body Template

```markdown
## Intraday Observation

Status: OBSERVE / WAIT_FOR_SETTLED_BAR / QUESTION_FOR_JUNYAN / RISK_REVIEW_NEEDED / DATA_BLOCKED

### 1. Market And Industry Context
- Index / sector move observed:
- Semiconductor cohort behavior:
- Market breadth / liquidity note:
- Data gaps:

### 2. Thesis Visibility
- Thesis condition visible today:
- Evidence supporting thesis:
- Evidence weakening thesis:
- Wrong-if clue:
- Data gaps:

### 3. SMC Observation
- Higher-timeframe structure:
- Liquidity sweep / BOS / CHOCH:
- POI / discount-premium location:
- Volume or participation clue:
- Reason to wait for settled bar:

### 4. Risk Notes
- Active red flag:
- Stale or missing source:
- Corporate-action or limit-up/limit-down issue:
- Question for Junyan:

### 5. Operator Conclusion
- Conclusion status:
- Why this remains observation only:
- Next allowed step:
```

## Not Allowed

An intraday note must not contain or imply:

- an official paper fill;
- an official paper exit;
- an official paper NAV;
- a new paper order;
- a looser stop than the sealed plan;
- a rewritten thesis after price action;
- a method-validity claim;
- a real-capital instruction.

If the market moves sharply, the correct intraday output is still an observation
or a question for Junyan. Official paper accounting waits for the approved
paper engine path and settled data.

