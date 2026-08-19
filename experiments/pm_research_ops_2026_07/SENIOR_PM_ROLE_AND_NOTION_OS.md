# Senior PM Role And Notion Operating System

## Role Definition

The senior collaborator should not be another signal generator. The role should
be closer to a part-time project manager plus investment-logic reviewer:

- Keep the weekly research and model-improvement loop organized.
- Challenge weak causal links in theses, especially "data supports thesis"
  claims where the catalyst or mechanism is missing.
- Review whether model changes were actually validated, or just made the story
  more satisfying.
- Surface industry knowledge, blind spots, and new angles that Junyan and the
  agents have not covered.
- Approve nothing as a real-capital action. Junyan remains the only human
  executor.

Other trusted reviewers, including family or mentor reviewers, can read the
weekly report as product/business sanity-checkers. Their best role is to ask
whether the project is becoming clearer, more disciplined, and more useful, not
to critique every market signal.

Causal logic is valid because the biggest historical gap is not raw compute; it
is thesis quality, review discipline, and outcome attribution. Specific division
of labor below is an operating design, not a backtested performance claim.

## RACI

| Workstream | Junyan | Senior PM | Claude | Codex |
|---|---|---|---|---|
| Real capital decisions | Accountable | Consulted | Informed | Informed |
| Weekly priorities | Accountable | Responsible for challenge | Responsible for proposal | Consulted |
| Production code | Approves | Informed | Responsible | Consulted/reviewer |
| Experiments | Approves direction | Consulted | Consulted | Responsible within `experiments/` |
| Thesis logic | Accountable | Responsible for critique | Responsible for draft | Consulted |
| Paper-trading ledger | Accountable | Reviews | Maintains production path | Proposes schema/tests |

## Weekly Cadence

The weekly cadence is an operating choice [unvalidated intuition], not an
empirically optimized schedule.

1. Monday: set the weekly question.
   - Example: "Can the model distinguish sector rotation persistence from
     one-day churn?"
   - Output: one weekly KR, one blocked item, one paper-signal focus.

2. Midweek async review.
   - Senior PM reads the Notion weekly page.
   - He comments only on gaps: missing catalyst, weak mechanism, bad data
     provenance, unvalidated threshold, or unclear outcome metric.

3. Friday or weekend review.
   - Junyan reviews portfolio and paper outcomes.
   - Senior PM gives three comments maximum [unvalidated intuition] to keep the
     feedback actionable.
   - Claude/Codex convert accepted comments into KRs, not vague backlog text.

4. Monthly retrospective.
   - Review paper signals and model changes together.
   - Separate process wins from investment wins.
   - Do not call a model change successful if it avoided losses only by not
     producing signals unless that was the pre-registered objective.

## Notion Workspace

Recommended Notion databases:

1. Weekly Reports
   - Properties: week, date range, market regime, portfolio NAV, drawdown,
     model changes, open questions, reviewer status.

2. Model Iterations
   - Properties: idea, source, affected model layer, implementation artifact,
     validation run, result, decision.
   - Decision values: `ship`, `paper_only`, `revise`, `kill`, `defer`.

3. Paper Signals
   - Properties: signal_id, ticker, sector, setup_type, hypothesis, evidence,
     trigger, invalidation, horizon, human_status, outcome_status.

4. Thesis Queue
   - Properties: ticker, industry, value-chain node, catalyst, mechanism,
     evidence tier, variant view, wrong-if, status.

5. Review Requests
   - Properties: owner, target artifact, question, reviewer comment, decision,
     follow-up KR.

6. Industry Maps
   - Properties: industry, value-chain node, bottleneck type, listed companies,
     evidence tier, update date, open questions.

## Senior PM Review Rubric

Each weekly review should answer:

- What claim is being made?
- What evidence tier supports it: E1, E2, E3, or E4?
- Is the causal chain complete: catalyst -> mechanism -> financial impact ->
  market repricing?
- What would prove the claim wrong?
- Is the model change judged on forward evidence or hindsight explanation?
- What is the one suggestion that would most improve next week's process?

## Non-Technical Reviewer Rubric

For a non-technical reviewer, the weekly page should answer:

- What did the system learn this week?
- What did it avoid doing because of discipline?
- What still cannot be predicted?
- What evidence shows the project is moving toward a product or service?
- What is the next milestone that would make the system more credible?

## What To Avoid

- Do not ask the senior PM to read every file.
- Do not ask him to approve trades.
- Do not frame model updates as "better" unless the evaluation metric is named.
- Do not let Notion become a journal. It should be a decision ledger.

## Weekly Acceptance

A week is accepted only if it has:

- A portfolio/paper snapshot.
- A model-change ledger.
- A research thesis or sector hypothesis pre-registered before outcome.
- At least one explicit reviewer question.
- A next-week KR.

Specific acceptance bullets are unvalidated workflow rules. Causal logic is
valid because each bullet creates an auditable link between idea, action, and
outcome.

不是买卖指令；研究信号，human executes.
