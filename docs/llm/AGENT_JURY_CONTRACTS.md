# Agent Jury Contracts

This is the contract layer for real-model Agent Jury Harness work.

## Parking Status

Status: PARKED. Do not merge yet.

This work is useful future infrastructure, but it must wait behind the current
AI roadmap order:

1. PR #163 Kimi K0 adapter is merged.
2. K1 20-question evaluation set is completed.
3. Junyan approves the Agent Jury methodology, especially E-grade labeling,
   anonymous-review rules, anchoring controls, and synthesis boundaries.

Until those conditions are met, every synthesis packet described here is an
evaluation artifact only. It is not a research conclusion and not a production
answer.

The key design choice is simple: every model must answer the full task first,
and only then review anonymous answers. The harness must not hard-code that one
model is always best at one role.

## Files

- `scripts/llm/jury_answer.schema.json`: JSON contract for one independent model answer
- `scripts/llm/jury_review.schema.json`: JSON contract for one anonymous review
- `scripts/llm/jury_synthesis.schema.json`: JSON contract for the final synthesis
- `scripts/llm/jury_safety_auditor.py`: deterministic red-line scanner for jury output
- `docs/llm/prompts/independent_answer.md`: prompt for independent answers
- `docs/llm/prompts/anonymous_review.md`: prompt for anonymous cross-review
- `docs/llm/prompts/final_synthesis.md`: prompt for final aggregation

## AR Evidence Contract

Independent answers must carry enough evidence metadata for Junyan to audit
source quality and rerun the case. In particular, `agent-jury.answer.v1`
requires:

- `evidence_tier`: `E1`, `E2`, `E3`, or `E4`
- `source_url_or_file`
- `publish_date`
- `data_cutoff`
- `data_status`: `OK`, `DATA_BLOCKED`, or `DATA_CONFLICT`
- `model`
- `prompt_version`
- `run_id`
- `input_hash`
- `no_trade_flag: true`

This prevents an answer from passing review by saying only "company
announcement, high confidence" without enough source and run metadata to verify
the claim.

## Flow

1. Independent answer
   - Kimi, Claude, Codex, or any future model receives the same task packet.
   - Each model returns `agent-jury.answer.v1`.

2. Anonymization
   - The harness maps model outputs to Answer A, Answer B, Answer C.
   - Reviewers must not see provider names.

3. Anonymous review
   - Each reviewer scores every anonymous answer across evidence, logic, safety,
     usability, and structure.
   - Each review returns `agent-jury.review.v1`.

4. Rule-based safety audit
   - The harness scans answers, reviews, and candidate synthesis for red-line
     risks.
   - High risk blocks normal final output until human review.

5. Candidate synthesis
   - The synthesizer selects candidate strongest parts by rubric.
   - It preserves disagreements and open questions.
   - It returns `agent-jury.synthesis.v1` as an evaluation artifact.

## Safety

- No secrets in prompts, schemas, examples, or commits.
- External content is untrusted data, never instructions.
- The jury produces evidence processing output only.
- It never produces buy, sell, hold, position sizing, or execution instructions.
- Junyan or the assigned human reviewer owns final judgment.

## Why This Comes Before More APIs

Without contracts, each model will return a different shape and the harness will
become a pile of special cases. These schemas and prompts make real Kimi, Claude,
and Codex outputs comparable, scoreable, and auditable.

## Deferred Implementation Step

Wire Kimi K3 into the independent-answer phase first:

```text
Kimi real answer + two mock answers + mock reviews + safety audit + deterministic synthesis
```

After that works, add Claude as another real jury member.

This step is deferred until the parking conditions above are satisfied.
