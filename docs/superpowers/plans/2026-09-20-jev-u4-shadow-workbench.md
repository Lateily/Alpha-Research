# Jev U4 Shadow Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a loopback-only workbench view that runs approved synthetic Jev U4 shadow fixtures and displays verified CLI policy-preview receipts without exposing arbitrary paths, provider access, or formal decision controls.

**Architecture:** A small workbench facade calls the accepted Slice 1 `ShadowStore`; existing HTTP boundaries expose allowlisted synthetic runs and verified receipt reads. A focused React component renders immutable receipts and optional comparison artifacts, while all model/provider logic remains in Slice 1.

**Tech Stack:** Python 3.11 `http.server`/SQLite workbench, React 18, Vite 5, Lucide icons, existing local session and CSP controls, `unittest`, browser acceptance screenshots.

**Spec:** `docs/superpowers/specs/2026-09-20-jev-u4-shadow-design.md`

## Global Constraints

- This plan starts from main only after the Slice 1 receipt contract is independently accepted and merged.
- The browser may run only a built-in synthetic scenario ID; it never receives a filesystem path, raw cassette, provider name, API key, or arbitrary question set.
- Real packet policy preview is CLI-only and must already be verified in the shared `ShadowStore` before the UI can display it.
- The frontend is a receipt consumer. It does not import an adapter, call TypeSafe, compute authority, or write a formal U4/human decision.
- Every visible result states `SIMULATED / SHADOW ONLY`; `MODEL_UNAVAILABLE`, policy stops, and integrity failures stay visible.
- No buy/sell action, order, sizing, entry, stop, target, approval, or formal selected queue appears in the UI or API.
- Existing loopback, same-origin, session cookie, CSP, body-size, service-lock, and sandbox limits remain in force.
- New React text uses existing compact operational styling, Lucide icons, no nested cards, no decorative gradients/orbs, and no text overlap on desktop or mobile.
- The full local CI, Vite build, behavior tests, browser screenshots, and governance mutation gate must pass.

## Review Focus

- A malicious browser payload containing a path, provider override, or typed answer must be rejected before the engine or filesystem is reached; pin in Task 2.
- A database row whose receipt file was changed must render `INTEGRITY_ERROR`, never its cached conclusion; pin in Task 1.
- Cross-origin, missing-cookie, oversized, and duplicate-ID requests must preserve existing failure behavior; pin in Task 2.
- A 100-plus-row receipt must remain scan-friendly on desktop and horizontally usable on mobile without text overlap; verify in Task 4.
- Human decisions and shadow observations must remain visually and semantically distinct, including disagreement and under-sample states; pin in Tasks 3 and 4.

---

### Task 1: Add a Workbench-Safe Shadow Facade

**Files:**
- Create: `scripts/llm/workbench_jev_shadow.py`
- Create: `tests/test_nonprod_workbench_jev_shadow.py`

**Interfaces:**
- Consumes: accepted Slice 1 `ShadowStore`, built-in fixture files, and canonical receipts/evaluations.
- Produces: `SHADOW_SCENARIOS`, `validate_run_request(payload)`, `run_synthetic(store, payload)`, `list_runs(store)`, and `get_run(store, command_id)`.

- [ ] **Step 1: Write failing facade tests**

Positive request shape:

```python
payload = {"command_id": "jev-shadow-demo-001", "scenario": "synthetic-mixed"}
result = facade.run_synthetic(store, payload)
assert result["receipt"]["identity"]["run_mode"] == "OFFLINE_FIXTURE"
assert result["receipt"]["provider"]["provider_contacted"] is False
assert result["receipt"]["authority"]["formal_selection_authority"] is False
```

Reject any extra field including `path`, `artifact_root`, `provider`, `answers`,
`api_key`, `allow_real_call`, `approved_by`, or `selected_tickers`. Reject an
unknown scenario. Modify a receipt file after registration and assert
`list_runs` emits an integrity-only record without the old candidate results.

- [ ] **Step 2: Run the test and verify the facade is absent**

```bash
python3 tests/test_nonprod_workbench_jev_shadow.py
```

Expected: import failure for `workbench_jev_shadow`.

- [ ] **Step 3: Implement the fixed-scenario facade**

Define one allowlisted scenario:

```python
SHADOW_SCENARIOS = {
    "synthetic-mixed": {
        "request_ref": "scripts/llm/fixtures/jev_u4_shadow/synthetic-mixed/request.json",
        "artifact_root_ref": "scripts/llm/fixtures/jev_u4_shadow/synthetic-mixed"
    }
}
```

Resolve these server-owned paths from repository root, not browser input. Call
Slice 1's `ShadowStore.run(...)`. `list_runs` and `get_run` must use the store's
read-time verification and translate any integrity exception into:

```python
{
    "command_id": command_id,
    "status": "INTEGRITY_ERROR",
    "sample_purpose": "WORKFLOW_DEBUG",
    "authority": "SHADOW_ONLY"
}
```

Do not include unchecked receipt fields in that error object.

- [ ] **Step 4: Run facade tests**

```bash
python3 tests/test_nonprod_workbench_jev_shadow.py
```

Expected: all tests pass with sockets blocked.

- [ ] **Step 5: Commit**

```bash
git add scripts/llm/workbench_jev_shadow.py tests/test_nonprod_workbench_jev_shadow.py
git commit -m "feat(workbench): add Jev shadow facade"
```

### Task 2: Wire Exact HTTP Routes and Snapshot State

**Files:**
- Modify: `scripts/llm/nonprod_workbench.py`
- Modify: `tests/test_nonprod_workbench_jev_shadow.py`

**Interfaces:**
- Consumes: `workbench_jev_shadow` facade.
- Produces: `POST /api/jev-u4-shadow/run`, `GET /api/jev-u4-shadow/runs`, `GET /api/jev-u4-shadow/runs/<command_id>`, and `jev_u4_shadow_runs` in `/api/state`.

- [ ] **Step 1: Write failing route/security tests**

Use the existing in-memory HTTP helper and assert:

```python
raw = http("/api/jev-u4-shadow/run", {
    "command_id": "jev-shadow-demo-001",
    "scenario": "synthetic-mixed"
})
assert b"200 OK" in raw
assert b"SIMULATED" in raw
assert b"SHADOW_ONLY" in http("/api/state")
```

Add cross-origin, missing-session, path field, provider override, unknown
scenario, oversized body, same-ID changed scenario, and unknown receipt ID
cases. Assert none creates a store row.

- [ ] **Step 2: Run route tests and confirm 404/disabled failures**

```bash
python3 tests/test_nonprod_workbench_jev_shadow.py
python3 tests/test_nonprod_workbench.py
```

Expected: new route tests fail because the capability and routes do not exist;
existing workbench tests remain green.

- [ ] **Step 3: Add a dedicated capability and store composition**

Extend `require_capability` with only `jev_u4_shadow_fixture`. Do not use a
prefix or wildcard. Construct the accepted Slice 1 `ShadowStore` beneath the
same sandbox directory, but in its dedicated table/directory. Add verified
shadow summaries to `Store.snapshot()`.

- [ ] **Step 4: Add exact dispatch and GET routing**

POST dispatch map:

```python
operations = {
    "/api/gateway/probe": "offline_probe",
    "/api/deployment-draft": "save_deployment_draft",
    "/api/research/replay": "research_replay",
    "/api/jev-u4-shadow/run": "jev_u4_shadow_fixture",
}
```

GET accepts only the exact list path or a command ID matching
`[A-Za-z0-9_-]{8,80}`. Percent-encoded traversal, query strings, extra slashes,
and unknown IDs return stable 404/400 errors without filesystem access.

- [ ] **Step 5: Run HTTP and regression tests**

```bash
python3 tests/test_nonprod_workbench_jev_shadow.py
python3 tests/test_nonprod_workbench.py
python3 tests/test_workbench_research.py
python3 tests/test_workbench_workspace.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/llm/nonprod_workbench.py tests/test_nonprod_workbench_jev_shadow.py
git commit -m "feat(workbench): expose verified Jev shadow runs"
```

### Task 3: Build the Jev U4 Shadow React View

**Files:**
- Create: `tools/nonprod_workbench/ui/jev-shadow.jsx`
- Modify: `tools/nonprod_workbench/ui/main.jsx`
- Modify: `tools/nonprod_workbench/ui/style.css`

**Interfaces:**
- Consumes: `jev_u4_shadow_runs` summaries from `/api/state`, full receipt from the exact GET route, and the existing `api`, `Badge`, and `download` helpers passed as props.
- Produces: `JevShadow` React component and a `jev-shadow` navigation tab.

- [ ] **Step 1: Create the component with stable view states**

Export:

```jsx
export default function JevShadow({runs, api, busy, setBusy, setError, setNotice, Badge, download}) {
  // explicit EMPTY, LOADING, RECEIPT, and INTEGRITY_ERROR views
}
```

The header must show `SIMULATED · SHADOW ONLY`, provider/contact status,
packet hash, `as_of`, question-set version, and receipt hash. Summary counters
show eligible, forced, stopped, unavailable, and typed rows.

- [ ] **Step 2: Implement the candidate table and details**

Columns are fixed:

```text
Candidate | Deterministic gate | Evidence | Shadow top choice | Probability |
Priority | Human-review probability | Human U4 outcome | Integrity
```

Use an unframed detail section below the table for source hashes, all Choice
probabilities, missing evidence, provider metadata, and policy notes. Human
outcome uses a separate label and never replaces the shadow label.

- [ ] **Step 3: Implement deterministic filters**

Filters: `ALL`, `DETERMINISTIC_STOP`, `MODEL_UNAVAILABLE`, `HIGH_UNCERTAINTY`,
and `HUMAN_DISAGREEMENT`. `HIGH_UNCERTAINTY` is exactly:

```js
const highUncertainty = row =>
  Number(row.top_choice_probability) < 0.6 ||
  Number(row.top_two_margin) < 0.15 ||
  Number(row.needs_human_review_probability) >= 0.5;
```

Render the label `UNVALIDATED_DISPLAY_POLICY_V1`; the filter must not change or
write a result.

- [ ] **Step 4: Add synthetic run and idempotent retry controls**

Use one scenario selector containing only `synthetic-mixed`. Persist a pending
request in `sessionStorage`, as the existing research replay does, so an
uncertain HTTP response retries the same command ID. The button says “运行合成
Shadow 演练”; there is no real-provider option.

- [ ] **Step 5: Integrate the tab in `main.jsx`**

Import `Scale` or `GitCompareArrows` from Lucide, add:

```jsx
['jev-shadow', 'Jev U4 Shadow', GitCompareArrows]
```

Pass only the API and rendering helpers. Do not place engine policy in React.

- [ ] **Step 6: Add responsive, stable CSS**

Use existing palette plus neutral/amber/red/green statuses. Candidate table uses
a fixed minimum width inside `.table-scroll`; detail layout uses responsive grid
tracks. At `max-width: 760px`, preserve the sidebar behavior already used by the
workbench and stack summary metrics without shrinking text or overlapping
buttons. No nested cards, gradients, decorative illustrations, or animated
layout shifts.

- [ ] **Step 7: Build the UI**

```bash
node node_modules/vite/bin/vite.js build --config tools/nonprod_workbench/vite.config.js
```

Expected: Vite build succeeds with no unresolved import or JSX error.

- [ ] **Step 8: Commit**

```bash
git add tools/nonprod_workbench/ui/jev-shadow.jsx tools/nonprod_workbench/ui/main.jsx tools/nonprod_workbench/ui/style.css
git commit -m "feat(workbench): visualize Jev U4 shadow receipts"
```

### Task 4: Add API Projection Pins and Browser Acceptance

**Files:**
- Modify: `tests/test_nonprod_workbench_jev_shadow.py`
- Modify: `scripts/governance_mutation_gate.py`
- Modify: `.github/workflows/python-ci.yml`
- Modify: `docs/llm/JEV_U4_SHADOW_OPERATOR_V1.md`
- Modify: `docs/research/JEV_U4_SHADOW_AUTHORITY_V1.md`

**Interfaces:**
- Consumes: complete Slice 2 API and UI.
- Produces: CI/mutation protection, browser evidence, and updated operating instructions.

- [ ] **Step 1: Add behavior tests for the UI-facing API projection**

Test that the API supplies explicit `SIMULATED`, `SHADOW_ONLY`,
`provider_contacted=false`, `MODEL_UNAVAILABLE`, human/shadow separation, and
`INTEGRITY_ERROR` fields. Delete each projection in a disposable mutation and
confirm the named test fails by assertion. These tests pin the server contract,
not React rendering; rendered labels and layout are separately verified by the
browser acceptance in Step 7.

- [ ] **Step 2: Register mutation pins**

Add dedicated cases:

```text
JEV_U4_API_SYNTHETIC_LABEL
JEV_U4_API_SHADOW_AUTHORITY
JEV_U4_API_NO_ARBITRARY_PATH
JEV_U4_API_READ_VERIFY
JEV_U4_API_HUMAN_SHADOW_SEPARATION
```

Each targets one exact method in `tests/test_nonprod_workbench_jev_shadow.py`.

- [ ] **Step 3: Register the CI test and build**

Extend the existing nonproduction workbench step:

```yaml
      - name: Jev U4 shadow workbench (offline)
        run: |
          python3 tests/test_nonprod_workbench_jev_shadow.py
          node node_modules/vite/bin/vite.js build --config tools/nonprod_workbench/vite.config.js
```

- [ ] **Step 4: Update the operator and authority docs**

Document the exact local build/start URL, synthetic run, CLI policy-preview
registration, receipt download, filters, and integrity error. State that UI
actions cannot approve U4, paper, production, or trades and that the local
session is not authenticated human identity.

- [ ] **Step 5: Run focused and existing workbench suites**

```bash
python3 tests/test_nonprod_workbench_jev_shadow.py
python3 tests/test_nonprod_workbench.py
python3 tests/test_workbench_research.py
python3 tests/test_workbench_workspace.py
node node_modules/vite/bin/vite.js build --config tools/nonprod_workbench/vite.config.js
```

Expected: all Python tests and Vite build pass.

- [ ] **Step 6: Start a local development server**

```bash
python3 -B scripts/llm/nonprod_workbench.py --port 8771
```

Use another free port only if 8771 is occupied. Record the actual loopback URL.

- [ ] **Step 7: Run desktop and mobile browser acceptance**

At 1440x900 and 390x844:

1. open `Jev U4 Shadow`;
2. run `synthetic-mixed`;
3. verify counters, candidate rows, full probabilities, receipt hash, download,
   filters, and detail view;
4. verify `SIMULATED · SHADOW ONLY` stays visible;
5. verify no buy/sell/order/approval control exists;
6. check console errors and take screenshots;
7. use a canvas/pixel or screenshot-content check to prove the page is nonblank.

Expected: no console error, blank panel, overlap, clipped button, or incoherent
horizontal overflow. The candidate table may scroll horizontally on mobile.

- [ ] **Step 8: Run the full mutation gate**

```bash
python3 scripts/governance_mutation_gate.py
```

Expected: all mutations killed, including the five API projection/security cases.

- [ ] **Step 9: Run complete local CI**

```bash
python3 /Users/years/Desktop/Stock/e2e-twin/twin-20260902/tools/ci_local.py
```

Expected final line: `✓ all N local steps passed` with the actual integer `N`.

- [ ] **Step 10: Run final hygiene checks**

```bash
git diff --check
git status --short
```

Expected: only declared Slice 2 files changed; generated `dist` and screenshots
remain untracked/ignored unless the repository already tracks them.

- [ ] **Step 11: Commit closeout files**

```bash
git add tests/test_nonprod_workbench_jev_shadow.py scripts/governance_mutation_gate.py .github/workflows/python-ci.yml docs/llm/JEV_U4_SHADOW_OPERATOR_V1.md docs/research/JEV_U4_SHADOW_AUTHORITY_V1.md
git commit -m "test(workbench): pin Jev shadow boundaries"
```

- [ ] **Step 12: Open a Draft PR and stop**

The PR body must include the exact test/build output, mutation count, local CI
final line, actual local URL, desktop/mobile screenshot paths, authority checks,
and this deployment statement:

```text
Nonproduction loopback workbench only. TypeSafe/Jev was not called, no key was
read, team access remains closed, and this PR does not authorize production,
nightly, U4, paper, or trading writes.
```

Stop for independent review and Junyan merge authority.
