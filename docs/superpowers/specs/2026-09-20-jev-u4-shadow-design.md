# Jev U4 Shadow Decision Engine Design

**Status:** Proposed for written review  
**Date:** 2026-09-20  
**Owner:** Junyan  
**Engineering scope:** AIOS / research workflow / nonproduction workbench  
**Initial delivery mode:** Offline, simulated, shadow-only  

## 1. Decision

Build a provider-neutral typed decision engine inside the existing AIOS harness,
then use it to run a non-authoritative U4 shadow workflow. The first delivery
does not call TypeSafe, does not require `TYPESAFE_API_KEY`, and does not install
the TypeSafe SDK. It provides:

1. the complete typed-decision interface and orchestration boundary;
2. deterministic offline fixtures for contract and UI testing;
3. policy-only preview for real frozen U4 packets;
4. immutable shadow receipts and a separate comparison artifact;
5. a nonproduction workbench view.

A future TypeSafe/Jev provider may implement the same interface in a separate
approved task. Adding that provider must not change the U4 packet, formal U4
ledger, policy composer, receipt schema, or frontend contract.

## 2. Intended Outcome

The subsystem lets the team test whether typed probabilistic judgments can help
Junyan review U4 candidates without granting a model decision authority. A
reviewer must be able to answer:

- Which deterministic gate stopped a candidate?
- What typed probabilities did the provider return for an eligible candidate?
- Was the result simulated, unavailable, or produced by a real provider?
- Which policy transformed or refused the provider output?
- How did the shadow result differ from the later human U4 decision?
- Can the exact result be reproduced from frozen evidence and versioned rules?

Success is a tested shadow engine and readable workbench view, not evidence that
Jev selects profitable securities or can replace human judgment.

## 3. Non-Goals

The initial delivery will not:

- call TypeSafe or any paid model provider;
- install `typesafe-sdk` or accept a TypeSafe credential;
- alter `ar.u4_pre_decision_packet`, its validators, or source evidence;
- write the formal U4 decision ledger;
- select a formal 0-or-3-to-5 U4 queue;
- register paper orders, create trade instructions, or write production state;
- run from the nightly production chain;
- infer human identity or approval from a browser session, username, or model;
- use shadow results to claim win rate, alpha, or method effectiveness;
- introduce LangChain or a second agent orchestration framework.

## 4. Existing Contracts Preserved

The engine consumes the existing frozen U4 packet and preserves these rules:

- `human_selection_authority = HUMAN_JUNYAN_ONLY`;
- `machine_selection_authority = NONE`;
- `production_authority = false`;
- `trade_authority = false`;
- `paper_order_authority = false`;
- `claim_allowed = false`;
- `no_trade_flag = true`;
- incomplete U3 evidence remains `DATA_BLOCKED`;
- an active E1 red flag remains `REJECT` when it is the mandatory blocker;
- when U3 incompleteness and an E1 red flag coexist, `DATA_BLOCKED` preserves
  both reasons;
- `SELECT` means admission to offline deep research only;
- a formal selected count remains exactly 0 or 3 to 5, but this engine does not
  create that formal selection.

The engine must reopen authoritative packet evidence by using the existing
`u4_pre_decision.validate_packet` path. A merely self-consistent packet is not
sufficient.

## 5. Architecture

```text
Frozen U4 packet and authoritative evidence
                    |
                    v
        Packet Reopen and Input Gate
                    |
                    v
        Deterministic U4 Policy Gate
                    |
          +---------+----------+
          |                    |
     forced stop          eligible row
          |                    |
          |                    v
          |          Typed Decision Provider
          |          - offline cassette now
          |          - TypeSafe/Jev later
          |                    |
          +---------+----------+
                    v
             Policy Composer
                    |
                    v
          Immutable Shadow Receipt
                    |
            +-------+--------+
            |                |
            v                v
       Workbench UI   Human Comparison Evaluator
```

The domain policy and provider transport are separate. Provider code cannot
modify gates, quotas, authority flags, or the formal U4 ledger.

## 6. Components

### 6.1 Packet Reopen and Input Gate

Responsibilities:

- accept only a versioned shadow request with exact fields;
- resolve paths only under an explicitly configured read-only artifact root;
- reject absolute paths, traversal, symlinks, missing evidence, and mixed runs;
- call the existing U4 packet receipt validator and authoritative-source reopen;
- verify packet hash, source bindings, method version, `as_of`, and row hashes;
- emit no provider request until validation succeeds.

Failure result: `SPEC_BLOCKED`, with no receipt that could be mistaken for a
completed shadow judgment.

Request schema `ar.jev_u4_shadow_request.v1` has exactly these fields:

- `schema`, `command_id`, `task_id`, `mode`, and timezone-aware `observed_at`;
- root-relative `packet_ref`, `bundle_ref`, `feature_health_ref`,
  `funnel_health_ref`, and `diagnostic_ref`;
- `industry`, `method_version`, and nullable `cyclical_flags_ref`;
- nullable `fixture_id`.

The CLI receives the absolute artifact root separately. The absolute path is
never written into the canonical request or receipt. `OFFLINE_FIXTURE` requires
a known `fixture_id`; `POLICY_PREVIEW` requires it to be null. Every reference
must resolve inside the supplied root without traversing a symbolic link.

### 6.2 Deterministic U4 Policy Gate

The gate runs before any provider. It derives one of:

- `FORCED_DATA_BLOCKED` for U3-incomplete evidence;
- `FORCED_REJECT` for a mandatory E1 red flag without U3 incompleteness;
- `POLICY_STOPPED` for another existing non-selectable row;
- `ELIGIBLE_FOR_TYPED_JUDGMENT` only when the packet marks the row reviewable
  and the row has no blocker.

`POLICY_STOPPED` does not invent a human U4 outcome. It records the packet's
blockers and leaves `shadow_outcome` null.

The provider is never called for a forced or stopped row. Provider output may
not clear or weaken a deterministic result.

### 6.3 Candidate State Assembler

For each eligible row, build an exact, minimal state object containing:

- packet hash, `as_of`, method version, and source publication state;
- ticker, display name, candidate status, and causal-cluster identity;
- positive channels, missing evidence, peak-earnings state, and battery display
  verdicts when present;
- U2 and U3 row hashes;
- the registered `question_for_junyan`;
- packet-level diagnostic summary.

It must not include later human U4 decisions, later prices, paper outcomes, or
unfrozen external text. The canonical state hash is stored in the receipt.

### 6.4 Typed Decision Provider Interface

The interface is provider-neutral and owns no U4 policy. It accepts:

- canonical candidate state;
- a versioned question set;
- timeout, network policy, and task identity.

It returns a normalized typed response or a structured failure. The question
set is fixed for version 1:

| Question | Type | Output |
|---|---|---|
| `evidence_sufficient` | Noul | probability of sufficient evidence |
| `research_priority` | Score | bounded score from 0 to 100 |
| `shadow_disposition` | Choice | probability mass over five U4 labels |
| `needs_human_review` | Noul | probability that human review is required |

The five `shadow_disposition` labels are `SELECT_FOR_DEEP_RESEARCH`, `DEFER`,
`REJECT`, `NO_TRADE`, and `DATA_BLOCKED`. They are counterfactual shadow labels,
not formal U4 ledger events.

Normalized probabilities use fixed six-decimal strings. Choice probability
keys must be exact and their mass must equal `1.000000`. Scores must be finite
and within range. Unknown labels, NaN, infinity, missing answers, duplicate
questions, or malformed probability mass are rejected.

### 6.5 Offline Provider

The initial provider is `offline_fixture`:

- `network_policy = deny`;
- `provider_contacted = false`;
- `model = null`;
- `cost_cny = 0`;
- responses come only from committed synthetic cassettes keyed by
  `state_hash + question_set_version`;
- a missing cassette returns `MODEL_UNAVAILABLE`; it never generates or
  guesses a response.

Two run modes are exposed:

1. `OFFLINE_FIXTURE`: accepts only repository synthetic fixtures and can produce
   the complete typed response for engine and UI tests.
2. `POLICY_PREVIEW`: accepts a real frozen packet, evaluates deterministic
   gates, and returns `MODEL_UNAVAILABLE` for eligible rows unless an explicitly
   approved cassette for that exact state exists. Production or historical
   candidate data must not be paired with fabricated probabilities.

Requesting `TYPESAFE_JEV` in the initial release returns
`LIVE_PROVIDER_NOT_INSTALLED` and `SPEC_BLOCKED`. No environment key can bypass
that result.

### 6.6 Policy Composer

The composer combines deterministic gates and a validated provider response.
It produces candidate-level shadow observations, never a formal selected list.

For an eligible row with a provider response it records:

- raw typed answers;
- the top Choice label and probability;
- the second probability and top-two margin;
- provider-declared human-review probability;
- `shadow_outcome_state = OBSERVED_NOT_AUTHORIZED`.

No probability threshold grants authority. Low probability, small margin, or a
high human-review probability remains visible but does not trigger a different
action. The UI may filter uncertainty, but the engine does not silently convert
it into approval or rejection.

Batch output contains counts and distributions only. It must not contain
`selected_tickers`, `orders`, position sizes, entry levels, stops, or targets.

### 6.7 Immutable Shadow Receipt

Receipt schema: `ar.jev_u4_shadow_receipt.v1`.

Required top-level sections:

- identity: task ID, command ID, run mode, sample purpose;
- source binding: packet hash, packet file hash, run identity, evidence refs;
- engine: engine, policy, and question-set versions;
- provider: provider name, model, model revision, contacted flag, network policy,
  usage, and cost;
- authority: all production, trade, paper, and formal-selection authority false;
- candidate results: exact row binding, gate result, state hash, typed answers,
  composer observation, and failure when applicable;
- batch summary: totals by gate/result, with no formal queue;
- receipt hash over all preceding fields.

Canonical JSON is ASCII, sorted-key, compact, and rejects non-finite numbers.
The request carries a timezone-aware `observed_at` chosen by the caller. The
canonical receipt uses that frozen value and contains no wall-clock timestamp,
random run ID, or process-specific path. The AIOS transport envelope may retain
operational timing, but it is not part of the canonical receipt. An idempotent
rerun of the same command and inputs therefore returns the same receipt bytes.
Changing a command ID's inputs is a conflict, not a second result.

Receipts live only under the nonproduction workspace state root. They are not
committed research evidence and are never copied to a formal ledger by this
subsystem.

### 6.8 Human Comparison Evaluator

Evaluation is a separate artifact so the original shadow receipt remains
immutable and free of later outcomes.

Schema: `ar.jev_u4_shadow_evaluation.v1`.

It binds:

- shadow receipt hash;
- verified formal U4 ledger receipt hash;
- exact candidate identity and evidence hashes;
- question-set and policy versions.

It may report coverage, abstention, candidate-level agreement, a confusion
table, and probability calibration. It must not call disagreement an error and
must not modify either source artifact. With fewer than 30 independent causal
clusters it reports `INSUFFICIENT_INDEPENDENT_SAMPLE` and makes no method,
win-rate, alpha, or profitability claim.

## 7. AIOS Harness Integration

Register an AIOS capability with:

- `task_type = u4_shadow_decision`;
- `mode = SHADOW`;
- `risk_level = MEDIUM`;
- `status = SHADOW_ONLY`;
- no tools beyond reading the allowlisted artifact root and writing the sandbox
  receipt root;
- `network_access = deny`;
- deterministic true for `offline_fixture`;
- known failure `LIVE_PROVIDER_NOT_INSTALLED`.

The engine uses the existing `AgentRequest`, adapter result envelope, capability
router, usage record, and evidence metadata. It does not create an autonomous
agent loop. One validated batch causes at most one provider execution per
eligible candidate; failure terminates that candidate and returns control to a
human.

A future TypeSafe/Jev capability must be a distinct record with
`network_access = provider_only`, deterministic false, a task-specific eval
version, finite budget, server-side credential, and separate approval. It may
not replace or mutate the offline capability record.

## 8. Workbench Visualization

Add a `Jev U4 Shadow` view to the existing loopback nonproduction workbench.
The frontend remains a read-only consumer of versioned receipts.

The view contains:

- a fixed header showing `SIMULATED / SHADOW ONLY`, provider mode, packet hash,
  trade date, engine version, and receipt integrity;
- compact summary counters for eligible, forced, stopped, unavailable, and
  typed-judgment rows;
- a stable candidate table with gate, evidence status, top Choice label,
  probability, priority score, human-review probability, and later human U4
  outcome when a separate evaluation artifact exists;
- filters for all, deterministic stops, model unavailable, high uncertainty,
  and human disagreement;
- a candidate detail panel with source hashes, complete probability mass,
  policy notes, missing evidence, and provider metadata;
- receipt JSON download.

The page does not show buy/sell controls, order actions, position controls, or
language implying approval. A human outcome is visually distinct from a shadow
observation.

The browser may run only built-in synthetic scenarios. Real packet preview is
performed by the local CLI against an allowlisted artifact root; the workbench
may then display the resulting receipt. Browser payloads never contain arbitrary
filesystem paths.

For display filtering only, `high uncertainty` means any of:

- top Choice probability below `0.600000`;
- top-two Choice margin below `0.150000`;
- `needs_human_review` probability at or above `0.500000`.

These frozen UI thresholds have no authority effect and are labeled
`UNVALIDATED_DISPLAY_POLICY_V1`.

## 9. Workbench API and Persistence

Add these nonproduction capabilities:

- `POST /api/jev-u4-shadow/run` for built-in synthetic scenario IDs only;
- `GET /api/jev-u4-shadow/runs` for verified local shadow receipts;
- `GET /api/jev-u4-shadow/runs/<command_id>` for one verified receipt.

All routes inherit loopback host, same-origin cookie, body-size, CSP, service
lock, and receipt-count guards. The store adds a dedicated table and directory;
it does not reuse deployment probes or formal research-run tables.

The CLI and workbench use one `ShadowStore` abstraction. The CLI may register a
policy-preview receipt only while holding the store transaction/lock and only
when its output root is the configured workbench shadow directory. The browser
cannot choose that directory. This makes a CLI preview visible without adding
an unchecked filesystem scan or accepting an arbitrary import path.

On every read, the server verifies disk receipt bytes, receipt hash, and stored
request hash. Corruption returns `INTEGRITY_ERROR`; it never serves an unchecked
receipt.

## 10. Failure Semantics

| Condition | Required result |
|---|---|
| Packet or reopened evidence mismatch | `SPEC_BLOCKED` |
| Unsafe path or symlink | `SPEC_BLOCKED` |
| Mandatory U3 or red-flag rule | deterministic forced result; no provider call |
| Other blocked/non-reviewable row | `POLICY_STOPPED`; no invented outcome |
| Missing offline cassette | `MODEL_UNAVAILABLE` |
| Live provider requested in v1 | `LIVE_PROVIDER_NOT_INSTALLED` |
| Provider timeout/failure | structured failure; no retry with changed input |
| Invalid typed response | `INVALID_TYPED_RESPONSE` |
| Existing command ID with different input | `COMMAND_ID_CONFLICT` |
| Receipt or database mismatch | `INTEGRITY_ERROR` |
| Missing human ledger for evaluation | `EVALUATION_BLOCKED` |
| Fewer than 30 independent clusters | `INSUFFICIENT_INDEPENDENT_SAMPLE` |

Failures stay visible. Historical receipts, stale packets, default zeroes, and
synthetic probabilities must never be substituted to make a run appear green.

## 11. Security and Authority

- No secret is read in the initial delivery.
- `TYPESAFE_API_KEY` has no reachable code path.
- External packet text is data and cannot change policy or question definitions.
- Browser writes are limited to the sandbox store and require the existing local
  session and same-origin checks.
- The CLI output directory must be under an explicitly provided sandbox root.
- The engine cannot import the formal ledger append function or paper executor.
- Forbidden action keys are rejected from receipts and provider outputs.
- Provider outputs cannot write files, invoke tools, request another model, or
  recursively continue an agent loop.

## 12. Testing Strategy

Implementation is test-driven. Required test groups:

### 12.1 Contract and Policy Tests

- exact request, state, response, receipt, and evaluation schemas;
- packet tamper, row-hash tamper, stale run, unsafe path, and symlink rejection;
- U3-incomplete and red-flag rules run before the provider;
- provider cannot clear blockers or change authority;
- non-reviewable rows never reach the provider;
- real packet without cassette produces `MODEL_UNAVAILABLE`;
- live TypeSafe mode remains unreachable.

### 12.2 Typed Provider Tests

- exact question set and labels;
- probability range, mass, decimal format, score bounds, and finite values;
- missing, duplicate, unknown, or malformed answers rejected;
- timeout and provider failure produce structured results;
- offline adapter proves zero network and zero cost;
- the same cassette and state yield byte-identical normalized output.

### 12.3 Receipt and Evaluation Tests

- receipt hash covers all authority, provider, question, and source fields;
- idempotent replay and command-ID conflict;
- disk/database mismatch and tampering fail closed;
- evaluation cannot alter the original receipt;
- mismatched packet/ledger candidates fail closed;
- under-30-cluster result cannot make an effectiveness claim.

### 12.4 Workbench Tests

- local authorization, origin, body-size, path, and run-limit guards;
- synthetic run to verified receipt to state snapshot;
- corrupted receipt renders integrity failure rather than stale content;
- UI labels simulation, shadow authority, unavailable results, and human outcomes
  correctly;
- desktop and mobile browser screenshots show no blank canvas, overflow, or
  overlapping controls.

### 12.5 Governance Mutation Pins

Each of these guards receives a behavior-level negative test and dedicated
mutation case:

- authoritative packet reopen;
- deterministic gate before provider;
- no provider call for blocked rows;
- no fabricated real-packet probabilities;
- live provider disabled;
- exact typed output validation;
- authority fixed false;
- no formal queue or action fields;
- receipt hash binding;
- read-time receipt verification;
- under-30-cluster claim block;
- frontend simulation/shadow labeling.

The complete governance mutation gate and every step in `python-ci.yml` must
pass before a Draft PR is reviewable.

## 13. Delivery Slices

### Slice 1: Engine and Receipts

- compile an `ai-task.v1` manifest;
- add provider-neutral typed contracts;
- add the offline fixture provider;
- add U4 input gate, policy composer, receipt, and evaluator;
- add synthetic fixtures, negative tests, and mutation pins;
- expose a sandbox-only CLI;
- no frontend change.

### Slice 2: Workbench Visualization

- consume Slice 1's versioned receipt;
- add isolated API/store support;
- add the workbench view and browser verification;
- add no provider network access.

The slices use separate branches and PRs so the decision engine can be reviewed
without frontend noise. Slice 2 starts only after Slice 1's receipt contract is
accepted. Neither slice authorizes deployment to `ar-live` or production.

### Future Slice: TypeSafe/Jev Provider

This is not part of the approved initial build. It requires a separate task and
explicit approval covering:

- legal access and `TYPESAFE_API_KEY` storage;
- SDK/version pinning;
- provider-only network allowlist;
- per-run and monthly call/cost limits;
- timeout and rate-limit policy;
- target-domain evaluation dataset and minimum acceptance metrics;
- audit of logged fields and data sent to the provider;
- canary and rollback.

## 14. Planned File Boundaries

Slice 1 may add or change only:

- `scripts/llm/typed_decision.py`;
- `scripts/llm/adapters/jev_shadow.py`;
- `scripts/llm/jev_u4_shadow.py`;
- `scripts/llm/fixtures/jev_u4_shadow.task.json`;
- `scripts/llm/fixtures/jev_u4_shadow/` synthetic packet and cassette files;
- `experiments/research_funnel/u4_shadow.py`;
- `tests/test_typed_decision.py`;
- `tests/test_jev_u4_shadow.py`;
- `scripts/governance_mutation_gate.py`;
- `.github/workflows/python-ci.yml`;
- `docs/llm/JEV_U4_SHADOW_OPERATOR_V1.md`;
- `docs/research/JEV_U4_SHADOW_AUTHORITY_V1.md`.

Slice 2 may add or change only:

- `scripts/llm/nonprod_workbench.py`;
- `scripts/llm/workbench_jev_shadow.py`;
- `tools/nonprod_workbench/ui/main.jsx`;
- `tools/nonprod_workbench/ui/jev-shadow.jsx`;
- `tools/nonprod_workbench/ui/style.css`;
- `tests/test_nonprod_workbench_jev_shadow.py`;
- `scripts/governance_mutation_gate.py`;
- `.github/workflows/python-ci.yml`;
- the two operator/authority documents above when the UI changes their usage
  instructions.

Moving responsibility across these boundaries requires a spec revision before
implementation. In particular, `experiments/research_funnel/u4_shadow.py` stays
pure and cannot import a provider SDK or initiate network access.

Forbidden scope:

- `~/ar-live` and production runtime data;
- formal U4 ledger contents;
- nightly step registration;
- paper registration/execution;
- real provider credentials or paid calls;
- trading authority and portfolio construction.

## 15. Acceptance Criteria

The initial subsystem is accepted only when:

1. a committed synthetic packet completes an offline typed shadow run and
   produces a byte-stable verified receipt;
2. a real frozen packet can run in policy-preview mode without network access,
   and eligible rows with no approved cassette display `MODEL_UNAVAILABLE`;
3. all mandatory U4 blockers are derived from existing packet evidence and
   cannot be cleared by provider output;
4. the formal U4 ledger and packet remain byte-identical before and after;
5. requesting TypeSafe/Jev is visibly `SPEC_BLOCKED`;
6. the workbench displays the synthetic result and policy preview with explicit
   `SIMULATED / SHADOW ONLY` labeling;
7. receipt corruption, packet tampering, and command-ID reuse with different
   input are rejected;
8. all new tests, full offline CI, and the governance mutation gate pass;
9. the PR reports code delivery separately from production deployment;
10. no outcome is described as a buy/sell instruction or method-performance
    claim.

## 16. References

- Existing AR provider-neutral adapter: `scripts/llm/adapters/base.py`
- Existing AR capability router: `scripts/llm/capability.py`
- Existing U4 packet: `experiments/research_funnel/u4_pre_decision.py`
- Existing U4 authority contract: `docs/research/U4_DECISION_LEDGER_V1.md`
- TypeSafe Jev overview: <https://typesafe.ai/blog/introducing-system-one-models-and-jev>
- TypeSafe Python SDK: <https://github.com/typesafe-ai/typesafe-sdk-python>

不是买卖指令；研究信号，human executes.
