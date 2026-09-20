# Jev U4 Shadow Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline, provider-neutral typed decision engine that validates frozen U4 evidence, preserves deterministic authority gates, emits immutable shadow receipts, and cannot contact TypeSafe or write a formal U4 decision.

**Architecture:** The AIOS adapter layer supplies typed judgments, while `experiments/research_funnel/u4_shadow.py` owns pure U4 gate and receipt semantics. `scripts/llm/jev_u4_shadow.py` reopens authoritative evidence, routes the shadow capability, runs the offline adapter, and persists a canonical receipt through an idempotent sandbox store.

**Tech Stack:** Python 3.11, standard-library `dataclasses`, `decimal`, `hashlib`, `json`, `sqlite3`, existing AIOS `AgentAdapter`/capability router, existing U4 packet validator, `unittest`, governance mutation gate.

**Spec:** `docs/superpowers/specs/2026-09-20-jev-u4-shadow-design.md`

## Global Constraints

- The delivery is offline, simulated, and `SHADOW_ONLY`; no TypeSafe SDK, API key, provider network, nightly registration, production write, formal U4 append, paper registration, or trade authority.
- Reopen the exact packet with `u4_pre_decision.validate_packet`; a self-consistent JSON object is not sufficient.
- Preserve `HUMAN_JUNYAN_ONLY`, `machine_selection_authority=NONE`, U3 `DATA_BLOCKED`, E1 `REJECT`, and combined-blocker semantics.
- Real frozen candidate rows without an exact approved cassette return `MODEL_UNAVAILABLE`; never synthesize probabilities.
- Canonical JSON is ASCII, sorted-key, compact, and rejects non-finite values.
- The canonical receipt contains caller-supplied `observed_at`, never wall-clock time, a random ID, or an absolute path.
- Every new test file must be registered in `.github/workflows/python-ci.yml`; the complete local CI and governance mutation gate must pass.
- All artifacts remain `WORKFLOW_DEBUG` and end-user text retains “不是买卖指令；研究信号，human executes.”

## Review Focus

- A real packet with no cassette must show deterministic gates plus `MODEL_UNAVAILABLE`, never a plausible-looking fabricated response; pin in Task 5.
- A row with both U3 incompleteness and an E1 flag must remain `FORCED_DATA_BLOCKED` while preserving both reasons; pin in Task 4.
- Non-finite, rounded-to-wrong-mass, duplicate, or unknown typed answers must fail before receipt composition; pin in Task 2.
- Concurrent repeats of one command must create one byte-identical receipt, while the same ID with new input must conflict; pin in Task 5.
- A human-ledger comparison with mismatched packet or row hashes must stop instead of reporting agreement; pin in Task 6.

---

### Task 1: Freeze and Compile the AI Task Contract

**Files:**
- Create: `scripts/llm/fixtures/jev_u4_shadow.task.json`

**Interfaces:**
- Consumes: `scripts/llm/schemas/task.schema.json`, the approved design spec, and existing `ai_os/cli.py compile`.
- Produces: a `SPEC_READY` task manifest whose file scope and approval gates bind all later tasks.

- [ ] **Step 1: Write the task manifest**

Create a complete `ai-task.v1` document with these binding values:

```json
{
  "schema": "ai-task.v1",
  "task_id": "JEV-U4-SHADOW-ENGINE-001",
  "source_issue": null,
  "architecture_block": ["aios-harness", "u4-shadow-decision"],
  "objective": "Build an offline provider-neutral typed U4 shadow engine with deterministic evidence gates and immutable receipts.",
  "non_goals": [
    "Do not call TypeSafe or any paid model provider",
    "Do not read TYPESAFE_API_KEY or install typesafe-sdk",
    "Do not write the formal U4 decision ledger",
    "Do not create a formal U4 selection, paper order, or trade action",
    "Do not register the engine in the production nightly chain",
    "Do not claim method effectiveness, win rate, alpha, or profitability"
  ],
  "human_owner": "Junyan",
  "reviewer": "Junyan",
  "executor_candidates": ["Codex"],
  "dependencies": [
    "ar.u4_pre_decision_packet",
    "U4_DECISION_LEDGER_V1",
    "AIOS AgentAdapter",
    "AIOS capability router"
  ],
  "authority_docs": [
    "AGENTS.md",
    "scripts/llm/AGENTS.md",
    "experiments/AGENTS.md",
    "docs/superpowers/specs/2026-09-20-jev-u4-shadow-design.md",
    "docs/research/U4_DECISION_LEDGER_V1.md"
  ],
  "file_scope": [
    "scripts/llm/typed_decision.py",
    "scripts/llm/adapters/jev_shadow.py",
    "scripts/llm/jev_u4_shadow.py",
    "scripts/llm/fixtures/jev_u4_shadow.task.json",
    "scripts/llm/fixtures/jev_u4_shadow",
    "experiments/research_funnel/u4_shadow.py",
    "tests/test_typed_decision.py",
    "tests/test_jev_u4_shadow.py",
    "scripts/governance_mutation_gate.py",
    ".github/workflows/python-ci.yml",
    "docs/llm/JEV_U4_SHADOW_OPERATOR_V1.md",
    "docs/research/JEV_U4_SHADOW_AUTHORITY_V1.md"
  ],
  "forbidden_scope": [
    "/Users/years/ar-live",
    "experiments/execution_tracker/run_nightly.py",
    "experiments/execution_tracker/event_ledger.jsonl",
    "experiments/research_funnel/u4_decision_ledger.py",
    "public/data/v2"
  ],
  "input_contracts": ["ar.u4_pre_decision_packet", "ar.jev_u4_shadow_request.v1"],
  "output_artifacts": ["ar.jev_u4_shadow_receipt.v1", "ar.jev_u4_shadow_evaluation.v1"],
  "acceptance_tests": [
    "python3 tests/test_typed_decision.py",
    "python3 tests/test_jev_u4_shadow.py",
    "python3 scripts/governance_mutation_gate.py",
    "python3 scripts/llm/ai_os/cli.py compile --input scripts/llm/fixtures/jev_u4_shadow.task.json",
    "python3 /Users/years/Desktop/Stock/e2e-twin/twin-20260902/tools/ci_local.py",
    "git diff --check"
  ],
  "risk_level": "MEDIUM",
  "network_policy": "OFFLINE",
  "budget": {"max_cny": "0", "max_minutes": 240},
  "approval_gates": ["PR_REVIEW", "JUNYAN_MERGE", "SEPARATE_LIVE_PROVIDER_APPROVAL"],
  "created_at": "2026-09-20T00:00:00+01:00"
}
```

- [ ] **Step 2: Compile the manifest and confirm `SPEC_READY`**

Run:

```bash
python3 scripts/llm/ai_os/cli.py compile --input scripts/llm/fixtures/jev_u4_shadow.task.json
```

Expected: `SPEC_READY` and task ID `JEV-U4-SHADOW-ENGINE-001`.

- [ ] **Step 3: Commit the contract**

```bash
git add scripts/llm/fixtures/jev_u4_shadow.task.json
git commit -m "chore(aios): freeze Jev U4 shadow task"
```

### Task 2: Implement Exact Typed Decision Contracts

**Files:**
- Create: `scripts/llm/typed_decision.py`
- Create: `tests/test_typed_decision.py`

**Interfaces:**
- Consumes: JSON-compatible provider payloads.
- Produces: `QUESTION_SET_VERSION`, `QUESTION_SET_V1`, `TypedDecisionError`, `question_set_payload()`, `normalize_typed_response(payload)`, and `canonical_hash(value)`.

- [ ] **Step 1: Write failing schema and adversarial tests**

Cover exact questions, a valid response, probability mass, six-decimal strings, score bounds, duplicate IDs, unknown labels, NaN/infinity, booleans-as-numbers, and unknown fields. The core positive test should assert:

```python
normalized = typed.normalize_typed_response({
    "question_set_version": "JEV_U4_SHADOW_QUESTIONS_V1",
    "answers": [
        {"question_id": "evidence_sufficient", "kind": "NOUL", "probability_true": "0.700000"},
        {"question_id": "research_priority", "kind": "SCORE", "score": "63.500000"},
        {"question_id": "shadow_disposition", "kind": "CHOICE", "probabilities": {
            "SELECT_FOR_DEEP_RESEARCH": "0.500000",
            "DEFER": "0.200000",
            "REJECT": "0.100000",
            "NO_TRADE": "0.100000",
            "DATA_BLOCKED": "0.100000"
        }},
        {"question_id": "needs_human_review", "kind": "NOUL", "probability_true": "0.800000"}
    ]
})
assert normalized["answers"][2]["probabilities"]["SELECT_FOR_DEEP_RESEARCH"] == "0.500000"
```

- [ ] **Step 2: Run the test and verify it fails because the module is absent**

```bash
python3 tests/test_typed_decision.py
```

Expected: import failure for `typed_decision`.

- [ ] **Step 3: Implement the minimal typed contract**

Define immutable questions and strict normalization:

```python
QUESTION_SET_VERSION = "JEV_U4_SHADOW_QUESTIONS_V1"
CHOICE_LABELS = (
    "SELECT_FOR_DEEP_RESEARCH", "DEFER", "REJECT", "NO_TRADE", "DATA_BLOCKED"
)

def _decimal6(value: object, field: str) -> Decimal:
    if not isinstance(value, str) or re.fullmatch(r"(?:0|[1-9][0-9]*)\.[0-9]{6}", value) is None:
        raise TypedDecisionError(f"{field} must be a fixed six-decimal string")
    parsed = Decimal(value)
    if not parsed.is_finite():
        raise TypedDecisionError(f"{field} must be finite")
    return parsed

def canonical_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True,
                     separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

Require exact answer fields per kind. Require one answer for every question, in question-set order. Require each Noul probability in `[0,1]`, the Score in `[0,100]`, exact Choice keys, and Choice mass exactly `1.000000`.

- [ ] **Step 4: Run the typed-contract tests**

```bash
python3 tests/test_typed_decision.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/llm/typed_decision.py tests/test_typed_decision.py
git commit -m "feat(aios): add typed decision contracts"
```

### Task 3: Add the Offline Fixture and Disabled Live Adapters

**Files:**
- Create: `scripts/llm/adapters/jev_shadow.py`
- Modify: `tests/test_typed_decision.py`
- Create: `scripts/llm/fixtures/jev_u4_shadow/synthetic-mixed/request.json`
- Create: `scripts/llm/fixtures/jev_u4_shadow/synthetic-mixed/u4-pre-decision.json`
- Create: `scripts/llm/fixtures/jev_u4_shadow/synthetic-mixed/u4_pre_decision_diagnostic.json`
- Create: `scripts/llm/fixtures/jev_u4_shadow/synthetic-mixed/cassettes.json`
- Create: `scripts/llm/fixtures/jev_u4_shadow/synthetic-mixed/public/data/v2/feature_store_health.json`
- Create: `scripts/llm/fixtures/jev_u4_shadow/synthetic-mixed/public/data/v2/funnel_health.json`
- Create: `scripts/llm/fixtures/jev_u4_shadow/synthetic-mixed/data_history/funnel/<as_of>/<run_id>/` (the complete immutable synthetic bundle)

**Interfaces:**
- Consumes: `AgentRequest.input_payload` with exact keys `state`, `state_hash`, `question_set`.
- Produces: `OfflineFixtureDecisionAdapter(cassettes)`, `DisabledTypeSafeJevAdapter()`, and provider-neutral `AdapterOutput` or structured `AdapterExecutionError`.

- [ ] **Step 1: Add failing adapter tests**

Tests must prove:

```python
adapter = OfflineFixtureDecisionAdapter({
    f"{state_hash}:JEV_U4_SHADOW_QUESTIONS_V1": valid_response
})
result = run_adapter(adapter, request, run_id_factory=lambda: "typed_test_run")
assert result.status.value == "SUCCEEDED"
assert result.provider == "offline_fixture"
assert result.model is None
assert result.usage.status.value == "NOT_APPLICABLE"
```

Also patch `socket.socket`, `socket.create_connection`, and
`socket.getaddrinfo`, and replace the environment mapping with a trap that
raises on `TYPESAFE_API_KEY` lookup through `[]`, `.get(...)`, or membership;
assert no socket and no key read. Missing cassette must yield
`MODEL_UNAVAILABLE`. `DisabledTypeSafeJevAdapter` must always yield
`LIVE_PROVIDER_NOT_INSTALLED` even when a fake key is otherwise present.

- [ ] **Step 2: Run tests and observe adapter failures**

```bash
python3 tests/test_typed_decision.py
```

Expected: failures for missing adapter classes.

- [ ] **Step 3: Implement adapters without TypeSafe imports**

Use the existing envelope:

```python
class OfflineFixtureDecisionAdapter(AgentAdapter):
    provider = "offline_fixture"
    model = None

    def __init__(self, cassettes: Mapping[str, Mapping[str, Any]]) -> None:
        self._cassettes = dict(cassettes)

    def execute(self, request: AgentRequest) -> AdapterOutput:
        if request.network_policy != "deny":
            raise AdapterExecutionError(code="NETWORK_POLICY_REFUSED", message="offline fixture requires deny", retryable=False)
        payload = request.input_payload
        key = f"{payload['state_hash']}:{payload['question_set']['version']}"
        if key not in self._cassettes:
            raise AdapterExecutionError(code="MODEL_UNAVAILABLE", message="no cassette for exact state", retryable=False, usage=Usage.not_applicable())
        output = normalize_typed_response(self._cassettes[key])
        return AdapterOutput(output=output, usage=Usage.not_applicable(), evidence_refs=(f"offline-cassette:{key}",))
```

`DisabledTypeSafeJevAdapter.execute()` raises the non-retryable live-provider error before inspecting environment variables.

- [ ] **Step 4: Add a truthful mixed synthetic fixture**

Generate the committed fixture from the existing deterministic helper in
`tests/test_u4_pre_decision_runtime.py`: call `_build(root, red_flag=True)` in a
one-off test/setup script, then serialize the returned packet and diagnostic
without editing either. Preserve the helper's complete evidence tree under the
fixture root, including:

```text
data_history/funnel/<as_of>/<run_id>/
  all_market_scan.json
  candidate_review.json
  candidate_manifest.json
  candidate_battery.json
  deep_research_queue.json
  security_registry_projected.json
  scan_receipt.json
  battery_receipt.json
  finalize_receipt.json
  manifest.json
public/data/v2/feature_store_health.json
public/data/v2/funnel_health.json
u4_pre_decision_diagnostic.json
u4-pre-decision.json
```

This is required because `u4_pre_decision.validate_packet` must reopen the
authoritative bundle and health evidence; a standalone packet is not a valid
fixture. The request file binds only root-relative refs, uses
`mode=OFFLINE_FIXTURE`, the packet's exact industry/method identity, and a fixed
tz-aware `observed_at`. The cassette file contains a response for exactly one
eligible row; another eligible row is deliberately absent so the full run
exercises `MODEL_UNAVAILABLE`. Forced U3/red-flag behavior is covered by the
pure copied-row tests in Task 4 rather than by mutating the authoritative
fixture. All fixture identities and values are synthetic, with
`sample_purpose=WORKFLOW_DEBUG`; no real ticker or market data is allowed.

- [ ] **Step 5: Run tests**

```bash
python3 tests/test_typed_decision.py
```

Expected: all tests pass with sockets blocked.

- [ ] **Step 6: Commit**

```bash
git add scripts/llm/adapters/jev_shadow.py tests/test_typed_decision.py scripts/llm/fixtures/jev_u4_shadow
git commit -m "feat(aios): add offline Jev shadow adapter"
```

### Task 4: Implement Pure U4 Gate, State, and Receipt Semantics

**Files:**
- Create: `experiments/research_funnel/u4_shadow.py`
- Create: `tests/test_jev_u4_shadow.py`

**Interfaces:**
- Consumes: an already reopened U4 packet, one candidate row, and validated provider result metadata.
- Produces: `derive_gate(row)`, `assemble_candidate_state(packet, row)`, `compose_candidate_result(...)`, `build_receipt(...)`, and `verify_receipt(receipt)`.

- [ ] **Step 1: Write failing pure-domain tests**

Use copied dictionaries from the synthetic packet and assert:

```python
gate = shadow.derive_gate({
    **ready_row,
    "blocked_reasons": ["E1_RED_FLAG_ACTIVE", "U3_BATTERY_INCOMPLETE"],
    "red_flag_channels": ["E1_EVENT"],
    "allowed_for_u4_packet": False,
})
assert gate == {
    "state": "FORCED_DATA_BLOCKED",
    "forced_shadow_outcome": "DATA_BLOCKED",
    "reason_codes": ["E1_RED_FLAG_ACTIVE", "U3_BATTERY_INCOMPLETE"],
}
```

Add tests that pure red flag gives `FORCED_REJECT`, another blocked row gives
`POLICY_STOPPED` with null outcome, ready rows are eligible, provider fields
cannot introduce action keys, receipt authority is fixed false, and changing any
source/question/provider field invalidates `receipt_hash`. Run the same
validated adapter output through two `AgentResult` envelopes with different
operational run IDs, wall-clock timestamps, and durations; assert the canonical
receipt bytes are identical because transport metadata is excluded.

- [ ] **Step 2: Run tests and verify missing domain functions**

```bash
python3 tests/test_jev_u4_shadow.py
```

Expected: import or attribute failures.

- [ ] **Step 3: Implement deterministic policy before typed composition**

Use the existing blocker vocabulary, preserve sorted unique reasons, and mark the load-bearing branches:

```python
# governance-mutation: JEV_U4_U3_PRECEDENCE
if "U3_BATTERY_INCOMPLETE" in blocked:
    return _gate("FORCED_DATA_BLOCKED", "DATA_BLOCKED", blocked)
# governance-mutation: JEV_U4_RED_FLAG_PRECEDENCE
if "E1_RED_FLAG_ACTIVE" in blocked or red_flags:
    return _gate("FORCED_REJECT", "REJECT", blocked)
if blocked or row.get("allowed_for_u4_packet") is not True:
    return _gate("POLICY_STOPPED", None, blocked)
return _gate("ELIGIBLE_FOR_TYPED_JUDGMENT", None, [])
```

The state assembler uses exact packet and row fields from the spec. The receipt
builder accepts `observed_at` from the request and rejects forbidden action keys.

- [ ] **Step 4: Implement receipt verification**

`verify_receipt` must require exact top-level and nested fields, recompute every
candidate state hash, recompute summary counts, require all authority flags
false, validate typed answers through `typed_decision`, and recompute the final
hash.

- [ ] **Step 5: Run pure-domain tests**

```bash
python3 tests/test_jev_u4_shadow.py
```

Expected: all domain tests pass without filesystem or network access.

- [ ] **Step 6: Commit**

```bash
git add experiments/research_funnel/u4_shadow.py tests/test_jev_u4_shadow.py
git commit -m "feat(research): add pure U4 shadow policy"
```

### Task 5: Orchestrate Reopened Evidence, Capability Routing, CLI, and Store

**Files:**
- Create: `scripts/llm/jev_u4_shadow.py`
- Modify: `tests/test_jev_u4_shadow.py`

**Interfaces:**
- Consumes: `ar.jev_u4_shadow_request.v1`, an absolute read-only artifact root supplied outside the request, and a sandbox state root.
- Produces: `validate_request(payload)`, `safe_ref(root, ref)`, `offline_capability_registry()`, `run_shadow(...)`, `ShadowStore`, CLI `run`, CLI `verify`, and CLI `evaluate` entry points.

- [ ] **Step 1: Add failing request/path/reopen tests**

Build a temporary artifact tree with packet, bundle, feature health, funnel
health, and diagnostic. Patch `u4_pre_decision.validate_packet` to record exact
arguments in the positive test. Add failures for unknown fields, absolute paths,
`..`, symlink roots/files, mixed method version, and modified packet bytes.

- [ ] **Step 2: Add the real-packet no-cassette test**

The test uses `POLICY_PREVIEW`, a reviewable row, and an empty cassette map:

```python
receipt = engine.run_shadow(request, artifact_root=root, state_root=state, adapter=OfflineFixtureDecisionAdapter({}))
ready = next(row for row in receipt["candidate_results"] if row["gate"]["state"] == "ELIGIBLE_FOR_TYPED_JUDGMENT")
assert ready["provider_result"]["status"] == "MODEL_UNAVAILABLE"
assert ready["typed_answers"] is None
assert ready["shadow_outcome"] is None
assert receipt["provider"]["provider_contacted"] is False
```

- [ ] **Step 3: Add capability and disabled-live tests**

Assert the router selects the deterministic `SHADOW_ONLY` offline capability for
`mode=SHADOW`, `risk_level=MEDIUM`, `network_policy=deny`, sandbox paths, and no
tools. An input request with `mode=TYPESAFE_JEV` must return the stable
`LIVE_PROVIDER_NOT_INSTALLED`/`SPEC_BLOCKED` result before path resolution,
routing, or any adapter call; an extra `provider` field is rejected by the exact
request schema. Assert `PRODUCTION`, `provider_only`, or an out-of-scope path is
also `SPEC_BLOCKED` before an adapter call.

- [ ] **Step 4: Implement request validation and safe resolution**

Require the exact request fields in the spec. Resolve each relative path under
the supplied root by checking every path component with `lstat`; reject symlinks
before calling `resolve()`. Do not place the absolute root in the request or
receipt.

- [ ] **Step 5: Implement one-pass orchestration**

The sequence is fixed:

```python
payload = validate_request(raw_request)
paths = resolve_request_paths(artifact_root, payload)
packet = load_exact_json(paths.packet)
u4_pre_decision.validate_packet(packet, bundle_dir=paths.bundle, feature_health_path=paths.feature_health,
                                funnel_health_path=paths.funnel_health, diagnostic_ref=payload["diagnostic_ref"],
                                industry=payload["industry"], method_version=payload["method_version"],
                                cyclical_flags_path=paths.cyclical_flags)
decision = route(offline_capability_registry(), route_request(payload))
if decision.status is not RouteStatus.SELECTED:
    raise ShadowRunError("SPEC_BLOCKED")
receipt = execute_candidates_once(packet, payload, adapter)
verify_receipt(receipt)
```

Blocked rows do not call `run_adapter`. Eligible rows call it at most once.
The accepted v1 request modes are only `OFFLINE_FIXTURE` and `POLICY_PREVIEW`.
`TYPESAFE_JEV` is an explicit unsupported-mode error, not a selectable
capability. `DisabledTypeSafeJevAdapter` exists only as a negative provider
interface contract and is never selected by v1 routing.

- [ ] **Step 6: Add failing store concurrency and integrity tests**

Use `ThreadPoolExecutor` to issue 12 identical requests. Assert one `CREATED`, 11
`IDEMPOTENT`, one receipt row, and identical canonical bytes. Reuse the command
ID with changed `observed_at` and assert `COMMAND_ID_CONFLICT`. Modify the disk
receipt and assert `INTEGRITY_ERROR` on read. Add injected failures after the
receipt file is published but before SQLite insert/commit; retrying the same
request must converge to one row and the same bytes, while different bytes at
that path must fail closed.

- [ ] **Step 7: Implement `ShadowStore` and CLI**

Use a dedicated SQLite file/table, `BEGIN IMMEDIATE`, a primary key on
`command_id`, stored request hash, canonical receipt bytes, and a separate
receipt file under `<state_root>/jev-u4-shadow/<command_id>/receipt.json`.
Publish the receipt bytes atomically with no replace and `fsync` before inserting
the SQLite row; commit the row only after the final file is visible. A retry may
adopt an orphaned final file only when its exact bytes and receipt hash equal the
newly recomputed result. It must never delete or overwrite a conflicting file.
Refuse symlinked roots, directories, database, or receipt files. Verify stored
request hash, database canonical bytes, disk bytes, and receipt hash on every
read. Failure cleanup may remove only private temporary files.

CLI commands:

```bash
python3 scripts/llm/jev_u4_shadow.py run --request REQUEST.json --artifact-root ROOT --state-root STATE
python3 scripts/llm/jev_u4_shadow.py verify --state-root STATE --command-id COMMAND_ID
python3 scripts/llm/jev_u4_shadow.py evaluate --state-root STATE --command-id COMMAND_ID --ledger LEDGER.jsonl
```

All JSON output is canonical and all errors use stable codes on stderr with
nonzero exit.

- [ ] **Step 8: Run orchestration tests**

```bash
python3 tests/test_jev_u4_shadow.py
python3 tests/test_typed_decision.py
```

Expected: all tests pass, no socket call, no production write.

- [ ] **Step 9: Commit**

```bash
git add scripts/llm/jev_u4_shadow.py tests/test_jev_u4_shadow.py
git commit -m "feat(aios): orchestrate U4 shadow receipts"
```

### Task 6: Add Human-Decision Comparison Without Contaminating Receipts

**Files:**
- Modify: `experiments/research_funnel/u4_shadow.py`
- Modify: `scripts/llm/jev_u4_shadow.py`
- Modify: `tests/test_jev_u4_shadow.py`

**Interfaces:**
- Consumes: verified shadow receipt, `verify_decision_ledger(path)`, `current_packet_decisions(path, packet_hash)`, and a hash of the verified ledger closure/projection.
- Produces: `build_evaluation(shadow_receipt, human_decisions, ledger_receipt_hash)` returning `ar.jev_u4_shadow_evaluation.v1`.

- [ ] **Step 1: Write failing comparison tests**

Cover matching packet/row hashes, disagreement, provider abstention, a missing
human row, mismatched packet hash, mismatched candidate evidence hash, and fewer
than 30 distinct clusters. Assert the under-sample result:

```python
assert evaluation["claim_status"] == "INSUFFICIENT_INDEPENDENT_SAMPLE"
assert evaluation["method_effectiveness_claim"] is None
assert evaluation["win_rate_claim"] is None
assert evaluation["alpha_claim"] is None
```

- [ ] **Step 2: Run tests and verify the evaluator is absent**

```bash
python3 tests/test_jev_u4_shadow.py
```

Expected: failure for missing `build_evaluation`.

- [ ] **Step 3: Implement immutable evaluation**

Verify the shadow receipt first. Require ledger packet hash to equal the shadow
source binding. Require exact candidate set and row hashes for rows eligible for
comparison. Compute counts, candidate agreement, confusion cells, abstentions,
and independent cluster count. Never mutate or rewrite either input.

- [ ] **Step 4: Wire the CLI to verified ledger readers**

Call `verify_decision_ledger` before `current_packet_decisions`. Hash the verified
closure/projection bytes that supplied the human result, then write evaluation
beside the shadow receipt as a separate immutable file. A second different
evaluation for the same shadow receipt is a conflict.

- [ ] **Step 5: Run tests**

```bash
python3 tests/test_jev_u4_shadow.py
```

Expected: all evaluator tests pass, including mismatch failures.

- [ ] **Step 6: Commit**

```bash
git add experiments/research_funnel/u4_shadow.py scripts/llm/jev_u4_shadow.py tests/test_jev_u4_shadow.py
git commit -m "feat(research): compare shadow and human U4 decisions"
```

### Task 7: Pin Governance, Register CI, Document Operation, and Verify Slice 1

**Files:**
- Modify: `scripts/governance_mutation_gate.py`
- Modify: `.github/workflows/python-ci.yml`
- Create: `docs/llm/JEV_U4_SHADOW_OPERATOR_V1.md`
- Create: `docs/research/JEV_U4_SHADOW_AUTHORITY_V1.md`
- Modify: `scripts/llm/fixtures/jev_u4_shadow.task.json` only if acceptance commands need exact correction

**Interfaces:**
- Consumes: all Slice 1 code and tests.
- Produces: behavior-level mutation coverage, CI registration, operator instructions, authority statement, and reviewable Draft PR evidence.

- [ ] **Step 1: Add governance markers and mutation cases**

Create dedicated cases for at least:

```text
JEV_U4_PACKET_REOPEN
JEV_U4_U3_PRECEDENCE
JEV_U4_RED_FLAG_PRECEDENCE
JEV_U4_BLOCKED_NO_PROVIDER
JEV_U4_NO_FAKE_REAL_PROBABILITIES
JEV_U4_LIVE_PROVIDER_DISABLED
JEV_U4_TYPED_RESPONSE_EXACT
JEV_U4_AUTHORITY_FALSE
JEV_U4_NO_FORMAL_QUEUE
JEV_U4_RECEIPT_HASH
JEV_U4_READ_VERIFY
JEV_U4_UNDER_30_NO_CLAIM
```

Each case must target one named test method and die by assertion failure, not
import error, syntax error, `KeyError`, or an unrelated failing test.

- [ ] **Step 2: Prove each new mutation pin bites**

Run the targeted cases or temporarily empty each named test in a disposable
copy and confirm the exact mutation ID reports `SURVIVED`. Restore the test and
confirm it reports `KILLED`.

- [ ] **Step 3: Register a dedicated CI step**

Add after the existing Agent adapter step:

```yaml
      - name: Jev U4 shadow engine contracts (offline)
        run: |
          python3 tests/test_typed_decision.py
          python3 tests/test_jev_u4_shadow.py
          python3 scripts/llm/ai_os/cli.py compile --input scripts/llm/fixtures/jev_u4_shadow.task.json
```

- [ ] **Step 4: Write operator and authority documents**

Operator doc must show exact offline fixture, policy preview, verify, and
evaluation commands; stable error meanings; sandbox path requirement; and no
TypeSafe key. Authority doc must state that shadow labels are counterfactual,
cannot write the formal ledger, and cannot authorize paper or trading.

- [ ] **Step 5: Run focused tests**

```bash
python3 tests/test_typed_decision.py
python3 tests/test_jev_u4_shadow.py
python3 scripts/llm/ai_os/cli.py compile --input scripts/llm/fixtures/jev_u4_shadow.task.json
```

Expected: all pass and compiler prints `SPEC_READY`.

- [ ] **Step 6: Run the full mutation gate**

```bash
python3 scripts/governance_mutation_gate.py
```

Expected: every mutation killed; no invalid kill.

- [ ] **Step 7: Run the complete local CI**

```bash
python3 /Users/years/Desktop/Stock/e2e-twin/twin-20260902/tools/ci_local.py
```

Expected final line: `✓ all N local steps passed` with the actual integer `N`.

- [ ] **Step 8: Run hygiene checks**

```bash
git diff --check
git status --short
```

Expected: no whitespace error and only declared task files changed.

- [ ] **Step 9: Commit closeout files**

```bash
git add scripts/governance_mutation_gate.py .github/workflows/python-ci.yml docs/llm/JEV_U4_SHADOW_OPERATOR_V1.md docs/research/JEV_U4_SHADOW_AUTHORITY_V1.md scripts/llm/fixtures/jev_u4_shadow.task.json
git commit -m "test(aios): pin Jev U4 shadow authority"
```

- [ ] **Step 10: Open a Draft PR and stop**

The PR body must include the exact focused-test output, compiler result, full
mutation count, local CI final line, no-network/no-key evidence, changed-file
scope, residual risk, and this deployment statement:

```text
Code delivery only. TypeSafe/Jev was not called, no credential was read,
~/ar-live and the nightly chain were not touched, and production deployment is
not authorized.
```

Stop for independent review and Junyan merge authority. Do not begin Slice 2
until the receipt contract is accepted.
