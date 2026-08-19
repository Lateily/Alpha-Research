# Weekly Research Report Template

Use this as the weekly Notion page or repo report. It is designed for Junyan,
the senior PM, and other trusted reviewers.

## Header

- Week:
- Date range:
- Prepared by:
- Reviewers:
- Market regime:
- One-line verdict:

## 1. Executive Summary

Write the week in five lines or fewer [unvalidated intuition as a readability
rule]:

- What changed in the market?
- What changed in the portfolio or paper book?
- What changed in the model?
- What did we learn that was falsifiable?
- What is next week's single KR?

### Non-Technical Reviewer Brief

Use this short block for reviewers who are not reading the full technical
ledger:

- What we built:
- What improved:
- What we learned:
- What is still not reliable:
- What we will test next:

## 2. Portfolio Snapshot

This section describes exposure and risk posture only. It is not a real-capital
instruction.

| Item | Value | Evidence | Notes |
|---|---:|---|---|
| NAV |  | broker / ledger |  |
| Weekly return |  | ledger |  |
| Cash weight |  | ledger |  |
| Largest exposure |  | ledger |  |
| Active risk flags |  | model / human |  |

Required notes:

- List current holdings and pending paper signals separately.
- State what the model did not do if non-action was the key result.
- Label every material number as `validated against ledger`, `E3 market data`,
  or `unvalidated estimate`.

## 3. Trade And Paper-Signal Ledger

Every real or paper-adjacent decision needs an audit row. Include non-trades
when the gate blocked a candidate.

| ID | Ticker | Real/Paper | Setup | Reasoning | Gate | Outcome | Review |
|---|---|---|---|---|---|---|---|
|  |  |  |  | catalyst/mechanism/evidence | watch/risk/paper | PnL or pending | keep/revise/kill |

Reasoning must include:

- Market state.
- Sector state.
- Flow fact.
- Forecast claim, if any.
- Invalidation or wrong-if.
- Horizon.

Do not write "model liked it". Write the specific causal chain.

## 4. Model Iterations

| Change | User idea | Implementation | Validation | Result | Decision |
|---|---|---|---|---|---|
|  |  | file / PR / experiment | command / sample / test |  | ship/paper/kill |

Required framing:

- What pain did this change address?
- What did it improve in measurable terms?
- What did it not prove?
- What data is still missing?

## 5. Capability, Practice, Target

This is the clearest way to show progress to an outside reviewer.

### Capability

What the model can do today.

Example:

- Distinguish positive flow facts from forward entry predictions in churn
  markets.

### Practice

What the model actually did this week.

Example:

- Quarantined positive-flow-only entries in CHURN_MODE.

### Target

What the model should be able to do next.

Example:

- Pre-register sector-rotation hypotheses and score them at future horizons.

## 6. Research Frontier

Use this for the two research upgrades:

- Sector rotation research: what data was added, what hypotheses were tested,
  what failed.
- Industry value-chain research: what industry map was built, what bottleneck
  nodes were identified, what listed companies need deeper thesis work.

## 7. Reviewer Questions

Ask the senior PM a small number of focused questions [unvalidated intuition].

Good:

- "Does the semiconductor value-chain map miss an upstream bottleneck?"
- "Is the catalyst specific enough to support a variant view?"
- "Which assumption would a real buy-side PM attack first?"

Bad:

- "What do you think?"
- "Any suggestions?"

## 8. Decisions And Next KRs

| Decision | Owner | Artifact | Due | Status |
|---|---|---|---|---|
|  |  |  |  |  |

Status values: `accepted`, `rejected`, `deferred`, `needs_data`,
`needs_review`.

## 9. Validation Footer

Causal logic is [valid/questionable/unestablished] because:

Specific numbers are [validated against data / unvalidated intuitions /
calibrated from X] because:

DATA_BLOCKED / DATA_CONFLICT flags:

Conclusion posture:

Next gate:

Self-audit:

- Did we give a real buy/sell instruction?
- Did we call an unvalidated strategy alpha?
- Did we confuse flow facts with positive destination prediction?
- Did we ignore sector/index confirmation?
- Did we explain outcome after the fact without a pre-registered claim?

不是买卖指令；研究信号，human executes.
