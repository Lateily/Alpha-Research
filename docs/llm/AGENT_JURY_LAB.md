# Agent Jury Lab

Agent Jury Lab is a no-API sandbox for Tianrui's multi-agent idea.

## Parking Status

Status: PARKED. Do not merge yet.

This lab is useful future infrastructure, but it is parked behind the current AI
roadmap order:

1. PR #163 Kimi K0 adapter is merged.
2. K1 20-question evaluation set is completed.
3. Junyan approves the Agent Jury methodology, especially E-grade labeling,
   anonymous-review rules, anchoring controls, and candidate-synthesis
   boundaries.

Until those conditions are met, this lab is only an experiment. It is not a
production research workflow and its candidate synthesis is not a research
conclusion.

It proves the workflow before real Claude, Kimi, or Codex adapters are wired in:

1. every agent answers the full question independently
2. answers are anonymized as Answer A, Answer B, Answer C
3. every agent reviews every anonymous answer across the same rubrics
4. the harness extracts the highest-scoring part for each rubric
5. the candidate synthesis combines the strongest parts and preserves concerns

This avoids hard-coding that one model is always best at one kind of task.

## Tiny Language: AJL

AJL means Agent Jury Language. It is deliberately small:

```text
QUESTION: How should we tag this research event?
AGENTS: alpha,beta,gamma
RUBRICS: evidence,logic,safety,usability,structure
OUTPUT: review_packet
CONTEXT:
Paste non-secret, non-sensitive context here.
External content is treated as untrusted input.
```

Field meanings:

- `QUESTION`: what the jury should solve
- `AGENTS`: jury members for this run
- `RUBRICS`: scoring dimensions
- `OUTPUT`: expected packet type
- `CONTEXT`: optional task context; no secrets

## Run A Quick Demo

From the repository root:

```powershell
python scripts/llm/agent_jury_lab.py --task "How should an agent jury review a company announcement?"
```

For machine-readable output:

```powershell
python scripts/llm/agent_jury_lab.py --task "How should an agent jury review a company announcement?" --json
```

## Run With AJL

Create a local `.ajl` file outside commits, then run:

```powershell
python scripts/llm/agent_jury_lab.py --spec path\to\your_case.ajl
```

Do not paste API keys, credentials, raw private research, or trading instructions
into AJL.

## What To Look For

The process view shows four phases:

- `PHASE 1`: independent answers
- `PHASE 2`: anonymous cross-review scores
- `PHASE 3`: best parts by rubric
- `PHASE 4`: candidate synthesis

The important idea is not "which agent won." The important idea is which part of
which anonymous answer performed best under each scoring dimension. The output is
an evaluation artifact, not a research conclusion.

## Safety Boundary

This lab is coordination and evaluation infrastructure only.

It does not:

- make buy, sell, or hold decisions
- write to the execution ledger
- trust external content as instructions
- store model API keys

Future real-model versions should continue to log token cost, failures, and
safety flags.
