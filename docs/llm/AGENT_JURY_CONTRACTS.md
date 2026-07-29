# Agent Jury Contracts

This is the contract layer for real-model Agent Jury Harness work.

The key design choice is simple: every model must answer the full task first,
and only then review anonymous answers. The harness must not hard-code that one
model is always best at one role.

## Files

- `scripts/llm/jury_answer.schema.json`: JSON contract for one independent model answer
- `scripts/llm/jury_review.schema.json`: JSON contract for one anonymous review
- `scripts/llm/jury_synthesis.schema.json`: JSON contract for the final synthesis
- `docs/llm/prompts/independent_answer.md`: prompt for independent answers
- `docs/llm/prompts/anonymous_review.md`: prompt for anonymous cross-review
- `docs/llm/prompts/final_synthesis.md`: prompt for final aggregation

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

4. Final synthesis
   - The synthesizer selects the strongest parts by rubric.
   - It preserves disagreements and open questions.
   - It returns `agent-jury.synthesis.v1`.

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

## Next Implementation Step

Wire Kimi K3 into the independent-answer phase first:

```text
Kimi real answer + two mock answers + mock reviews + deterministic synthesis
```

After that works, add Claude as another real jury member.
