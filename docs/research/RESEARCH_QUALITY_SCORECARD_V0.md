# Research Quality Scorecard V0

Status: `DRAFT_OFFLINE_QUALITY_GATE / PRODUCTION_UNWIRED`

This contract gives the team one repeatable way to judge whether a research
artifact is good enough to move to the next offline stage. It measures research
quality, not investment correctness, paper P&L, alpha, or trade readiness.

The machine may prepare the scorecard. Junyan remains the authority for U4
selection, paper registration, thesis interpretation, and real-capital
decisions.

## Why This Exists

The semiconductor closed loop now has enough structure to run from U1/U3
evidence into U4, thesis, valuation, timing, paper simulation, and five-axis
attribution. The next risk is not that the system lacks a path. The risk is
that weak research moves through the path because it looks complete on the
surface.

This scorecard is the preflight quality meter. It asks:

- Are the facts complete enough to reason from?
- Is the thesis actually different from market consensus?
- Can the thesis be proven wrong by future facts?
- Is the valuation tied to explicit assumptions?
- Is timing registered before outcomes exist?
- Can another reviewer replay and audit the evidence chain?

If the answer is no, the honest output is `REVISE_REQUIRED`, `DATA_BLOCKED`, or
`KILL`, not a prettier research note.

## Scope

This V0 applies to:

- U4 review packets before human selection;
- selected-name research case drafts;
- prospective paper registration drafts;
- post-cycle review packets.

It does not replace:

- U1/U2/U3 screening;
- Junyan's U4 decision ledger;
- manual SMC judgment;
- paper execution;
- five-axis outcome attribution;
- R-035 funnel information evaluation.

## The Six Quality Axes

Each axis is scored from 0 to 100. The score must cite evidence from the
artifact being reviewed. A long answer gets no credit unless the required
evidence is present.

| Axis | Question | High-quality evidence |
|---|---|---|
| `FACT_COMPLETENESS` | Do we know what facts the research depends on? | Source tier, source date, data cutoff, issuer/exchange facts, missing fields, and confidence are explicit. |
| `VARIANT_THESIS` | Is there a real market disagreement? | The artifact states what the market believes, what we believe instead, and why the difference exists. |
| `FALSIFIABILITY` | Can the thesis be proven wrong? | Every important claim has an observable metric, threshold, source, due date, and `wrong_if`. |
| `VALUATION_DISCIPLINE` | Is valuation anchored instead of decorative? | Bear/base/bull scenarios, load-bearing variables, current implied case, and downside are named. |
| `TIMING_REGISTRATION` | Is timing separated from value? | SMC/timing evidence, `WAIT` state, entry reference, stop logic, and invalidation are recorded before outcomes. |
| `REVIEWABILITY` | Can another reviewer replay the chain? | Hashes, input paths, rejected samples, blocked samples, commands, and reviewer notes are preserved. |

## Scoring Discipline

V0 uses this gate:

- `QUALITY_PASS`: average score is at least 70, no axis is below 50, and no
  blocker is present.
- `REVISE_REQUIRED`: the artifact is reviewable but one or more axes fail the
  bar.
- `DATA_BLOCKED`: the artifact cannot be scored because load-bearing evidence
  is missing, stale, unverifiable, or unpublished.
- `KILL`: the artifact violates a hard boundary such as suppressed E1 red
  flags, invented facts, or trade authority.

The score is a quality signal only. It cannot authorize U4 selection, paper
registration, production deployment, or any real order.

## Hard Blockers

The scorecard must stop before scoring if any blocker appears:

1. E1 red flag is hidden, downgraded, or offset by positive evidence.
2. Missing data is filled with zero, old data, or inferred data.
3. Thesis has no concrete `wrong_if`.
4. Valuation has no scenario assumptions or no current implied case.
5. Timing evidence appears after the claimed registration time.
6. P&L is used to rewrite thesis, valuation, timing, or execution quality.
7. Rejected, deferred, no-trade, or data-blocked samples are omitted.
8. The artifact claims `production_authority=true`,
   `trade_authority=true`, `claim_allowed=true`, or `no_trade_flag=false`.

## Output Shape

```json
{
  "schema": "ar.research_quality_scorecard.v0",
  "status": "QUALITY_PASS",
  "artifact_ref": {
    "kind": "RESEARCH_CASE_DRAFT",
    "path": "docs/research/prospective/example.json",
    "hash": "sha256:<artifact hash>"
  },
  "axes": [
    {
      "axis": "FACT_COMPLETENESS",
      "score": 80,
      "status": "PASS",
      "evidence_refs": ["issuer filing date and source tier are present"],
      "gaps": []
    }
  ],
  "average_score": 78.3,
  "blockers": [],
  "next_state": "READY_FOR_HUMAN_REVIEW",
  "authority": {
    "u4_selection_authority": "HUMAN_JUNYAN_ONLY",
    "paper_registration_authority": "HUMAN_JUNYAN_ONLY",
    "production_authority": false,
    "trade_authority": false,
    "claim_allowed": false,
    "no_trade_flag": true
  },
  "disclaimer": "不是买卖指令；研究信号，human executes."
}
```

## How Reed Uses This

Before asking Junyan to review a semiconductor case, Reed should attach:

1. the U1/U2/U3 input hashes;
2. the U4 candidate state and stop reason if blocked;
3. one scorecard over the research artifact;
4. explicit `DATA_BLOCKED` gaps;
5. whether the next requested action is review, revision, or no action.

The useful question is not "is this a good stock?" The useful question is
"is this research artifact strong enough for the next human decision?"

## Relationship To Five-Axis Attribution

This scorecard runs before or during research preparation. Five-axis attribution
runs after later facts and paper execution exist. They answer different
questions:

- quality scorecard: "Was the research artifact disciplined before the result?"
- five-axis attribution: "After the result, which part of the registered method
  worked or failed?"

Paper P&L is not an input to this quality score. A profitable case can still
have a weak or wrong thesis, and a losing case can still have high-quality
research.

## Current Status

V0 is intentionally offline and unwired. It freezes the research-quality
language and machine-readable contract so later code can implement scorecard
generation without changing the authority boundary.

不是买卖指令；研究信号，human executes.
