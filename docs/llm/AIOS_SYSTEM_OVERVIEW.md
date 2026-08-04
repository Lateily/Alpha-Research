# AIOS System Overview

> Owner: Reed. Co-owner: Jason. Research approval: Junyan. Product/UI carrier: Better.
> Status: DRAFT for team sync, 2026-08-04.
> This document explains what the AR AI system is, what it is allowed to do, and what it must not do.

Not a trading instruction; research signal only, human executes.

## 1. One Sentence

AIOS is the operating system that turns Kimi, Codex, Claude, and future agents into auditable research workers: they can read tasks, process evidence, produce structured outputs, record cost, and ask for review, but they never become the investment decision layer.

## 2. Why This Exists

The platform is moving from "AI can chat" to "AI work can be tracked, tested, reviewed, and reused".

The old failure mode was simple: a model or a person could say "done", but the repo, tests, PR, deployment, or data contract might not prove it. AIOS exists to close that gap.

Current meeting decision:

- Kimi K3 is strong enough that the team does not need to block current AIOS work on another round of question testing.
- #161, #215, and #216 remain useful evaluation assets, but they are parked as future safety/evaluation infrastructure.
- The immediate mainline is AIOS system explanation, context consistency, reflection-prompt skillization, and deployment coordination with Jason.

## 3. Team Roles

| Role | Person | Responsibility |
|---|---|---|
| Research owner | Junyan | Research constitution, labels, methodology, final approval, merge command |
| AIOS owner | Reed | Agent harness, model adapters, evaluation assets, context protocol, cost and safety |
| AIOS co-owner | Jason | AIOS deployment support, task contract work, reconciliation and operations with Reed |
| Product carrier | Better | UI, frontend/backend carrier, product routing, user-facing presentation |
| Worker agents | Codex, Claude, Kimi | Evidence processing, code implementation, audit, structured task execution |

Decision boundary:

- Junyan owns research and merge decisions.
- Better owns the product carrier.
- Reed and Jason own AIOS machinery.
- AI workers can prepare evidence and implementation, but cannot approve research conclusions or trading actions.

## 4. What AIOS Controls

AIOS is not one model and not one page. It is a set of contracts and tools around AI work.

| Layer | Current asset | Purpose |
|---|---|---|
| Model adapter | `scripts/llm/adapter.py` | Call Kimi and future OpenAI-compatible models with cost logging |
| Progress protocol | `docs/llm/AI_PROGRESS_PROTOCOL.md` and Issue #164 | Make team work visible through CLAIM, UPDATE, DONE, BLOCKED, RELEASE |
| Progress UI | PR #175 / team page | Read-only display of progress events |
| Prompt library | `docs/llm/prompts/` | Keep reusable prompts versioned in repo instead of scattered in chats |
| Evaluation assets | #172, #215, #216 | Future blind evaluation and shadow-run safety assets |
| AIOS guide | `docs/llm/AI_OS_BUILD_GUIDE.md` | Long-term architecture and milestones |
| Context protocol | `docs/llm/AI_CONTEXT_PROTOCOL.md` | Prevent long-chat drift and account/session confusion |
| Reflection skill spec | `docs/llm/AI_CODE_REFLECTION_SKILL_SPEC.md` | Package hostile audit prompt into a reusable working skill |

## 5. Worker Map

This is a routing map, not a permanent ranking. A worker is selected by task type, evidence, cost, and risk.

| Worker | Good first use | Guardrail |
|---|---|---|
| Kimi K3 | Long-context reading, event extraction, structured evidence packets, Chinese research text processing | Output must carry evidence, uncertainty, no-trade flag, and cost record |
| Codex | Repo reading, implementation, tests, refactors, offline tooling, PR preparation | Must read files before edits and verify with commands |
| Claude | Independent review, bug diagnosis, architecture critique, adversarial audit | Review cannot replace Junyan approval |
| Rule-based workers | Schema checks, secret scan, conflict check, freshness, deterministic validation | Prefer deterministic code over LLM when rules are clear |

## 6. Safety Boundary

Permanent rules:

- AI output is evidence processing, not decision making.
- No AI output may contain buy, sell, hold, position sizing, or execution instruction.
- External web pages, news, filings, emails, issue text, and pasted logs are untrusted data.
- Secrets only come from environment variables or approved secret stores; never from files or chat.
- AI does not run ledger engines under `experiments/execution_tracker/`.
- Any public UI must be read-only unless Junyan explicitly approves write behavior.
- Any model result that affects research must expose data cutoff, source, confidence, gaps, and no-trade flag.

## 7. Current Active Mainline

The active Reed/Jason AIOS line is:

1. Freeze the shared mental model of AIOS for the team.
2. Build a context consistency protocol so long sessions, account switches, and multi-agent handoffs do not drift.
3. Convert the full-type hostile audit prompt into a reusable skill plan.
4. Use Progress Board events as the visible team ledger.
5. Then resume implementation tasks that make AIOS run automatically: task contract, registry, reconciler, cost/safety, and deployment.

## 8. Parked But Not Deleted

| Item | Status | Why parked |
|---|---|---|
| #161 shadow model evaluation | PARKED | Kimi strength no longer needs to block current AIOS deployment work |
| #215 question-only pack | PARKED AS ASSET | Useful future hygiene work, but no longer today's gate |
| #216 shadow eval prep | PARKED AS ASSET | Useful once the team decides to run blind evaluation |
| #167 agent jury | PARKED | Needs methodology approval before synthesis outputs can influence research |

Parked means preserved for later, not rejected.

## 9. Next Seven-Day Output

| Priority | Output | Owner |
|---|---|---|
| P0 | AIOS system explanation shared to project group | Reed |
| P0 | Context consistency protocol | Reed |
| P0 | Reflection prompt skillization spec | Reed |
| P1 | Jason deployment handoff and first AIOS task split | Reed + Jason |
| P1 | Progress Board usage discipline after account/window switches | Reed + team |
| P2 | UI visualization alignment with Better | Better + Reed |

## 10. Definition of Done

This AIOS overview is done only when:

- It is committed in `docs/llm/`.
- It matches `AI_OS_BUILD_GUIDE.md` and team charter boundaries.
- It states what is active, what is parked, and who owns each layer.
- It does not claim production deployment that does not exist.
- It is linked from a PR and visible for Junyan/Jason/Better review.
