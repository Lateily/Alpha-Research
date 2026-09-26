# Jev U4 Shadow Operator v1

**Status:** `SHADOW_ONLY / OFFLINE / WORKFLOW_DEBUG`. This is a local research
workflow, not a formal U4 decision, paper order, or trade instruction. Automatic
experiments remain deferred until 2026-09-28; that date is not approval to run
one. No production or automatic experiment is currently approved.

## Local requirements

- Run from the repository root with CPython 3.11+ and working stdlib SQLite
  `serialize`/`deserialize`. Keep `AR_OFFLINE=1`; no TypeSafe SDK, paid provider,
  network call, or `TYPESAFE_API_KEY` is needed or accepted by this workflow.
- Supply an absolute, non-symlink `--artifact-root` containing the frozen packet
  and all its authoritative evidence. Request refs are **root-relative** paths,
  not absolute paths; `..`, symlinks, missing evidence, and mixed runs fail
  closed. The CLI reopens the packet through `u4_pre_decision.validate_packet`.
- Supply an absolute, non-symlink `--state-root` inside an explicitly chosen
  nonproduction sandbox. Do not point it at `~/ar-live`, a production state
  directory, the formal U4 ledger, or `public/data/v2`. The CLI accepts a root
  argument; choosing an isolated sandbox is the operator's responsibility.
  It writes `jev-u4-shadow/shadow.sqlite3`, `.shadow.lock`, and
  `jev-u4-shadow/<command_id>/receipt.json` below that root. Never commit these
  runtime files as research evidence.

## Offline synthetic fixture

From the repository root, these commands use only the committed synthetic
fixture and a new temporary sandbox:

```bash
export AR_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1
ARTIFACT_ROOT="$PWD/scripts/llm/fixtures/jev_u4_shadow/synthetic-mixed"
STATE_ROOT="$(mktemp -d /private/tmp/jev-u4-shadow.XXXXXX)"
python3 scripts/llm/jev_u4_shadow.py run \
  --request "$ARTIFACT_ROOT/request.json" \
  --artifact-root "$ARTIFACT_ROOT" \
  --state-root "$STATE_ROOT"
python3 scripts/llm/jev_u4_shadow.py verify \
  --state-root "$STATE_ROOT" \
  --command-id jev-u4-shadow-synthetic-mixed-001
```

`run` prints canonical JSON with `disposition` (`CREATED` or `IDEMPOTENT`)
and a receipt. `verify` rereads the store, checks its request and receipt
bindings against the on-disk bytes, and prints the receipt. It does not rerun
the provider or certify a formal U4 decision. An exact replay is idempotent;
use a new command ID for changed inputs.

## Policy preview

The following creates a second, exact-schema request from the synthetic
fixture. It exercises `POLICY_PREVIEW` without a cassette, so eligible rows
report `MODEL_UNAVAILABLE`; deterministic forced/stopped gates remain visible.
It is a preview, not a model judgment.

```bash
python3 - "$ARTIFACT_ROOT/request.json" "$STATE_ROOT/preview-request.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    request = json.load(source)
request.update(
    command_id="jev-u4-shadow-preview-001",
    mode="POLICY_PREVIEW",
    fixture_id=None,
)
with open(sys.argv[2], "w", encoding="utf-8") as destination:
    json.dump(request, destination, ensure_ascii=True, sort_keys=True)
PY
python3 scripts/llm/jev_u4_shadow.py run \
  --request "$STATE_ROOT/preview-request.json" \
  --artifact-root "$ARTIFACT_ROOT" \
  --state-root "$STATE_ROOT"
python3 scripts/llm/jev_u4_shadow.py verify \
  --state-root "$STATE_ROOT" \
  --command-id jev-u4-shadow-preview-001
```

For a real frozen packet, prepare a separate `ar.jev_u4_shadow_request.v1`
JSON file using the fixture request as the field template. Set a fresh
`command_id`, a caller-chosen timezone-aware `observed_at`, `mode` to
`POLICY_PREVIEW`, and `fixture_id` to `null`. Point `packet_ref`, `bundle_ref`,
`feature_health_ref`, `funnel_health_ref`, `diagnostic_ref`, and optional
`cyclical_flags_ref` to the **actual** root-relative evidence under that
packet's artifact root; set its actual `industry` and `method_version`.
Keep the same task ID and schema. Then run the same `run` and `verify` commands
with that request and artifact root, still using an isolated sandbox state
root. Do not pair real or historical candidates with synthetic cassettes or
interpret `MODEL_UNAVAILABLE` as a probability.

## Evaluation: NOT YET IMPLEMENTED

The CLI parses this shape, but it currently refuses it before opening the
ledger or producing an evaluation:

```bash
python3 scripts/llm/jev_u4_shadow.py evaluate \
  --state-root "$STATE_ROOT" \
  --command-id jev-u4-shadow-synthetic-mixed-001 \
  --ledger "$STATE_ROOT/not-used.jsonl"
```

The expected result is exit code 2 with
`{"status":"SPEC_BLOCKED","code":"EVALUATION_NOT_INSTALLED",...}` on
stderr. There is no current shadow-versus-human comparison artifact, agreement
metric, or completed Task 6 flow. Do not treat the accepted `--ledger` argument
as evidence that a ledger was read or verified.

Task 6 cannot simply compare `packet_hash` values. This engine reopens an
`u4_pre_decision` packet with `candidate_rows`; the formal U4 decision ledger
binds a closure review packet with `ready_pool`. These are different schemas
and different hashes. A future evaluator needs an independently reviewed bridge
that proves common run/bundle and exact U2/U3 candidate evidence while retaining
both packet hashes. Until then, `evaluate` must remain disabled.

## Failure meanings

CLI failures are canonical JSON on stderr and exit 2. `run`/`verify` success
is JSON on stdout and exit 0.

| Status / code | Meaning |
| --- | --- |
| `SPEC_BLOCKED / SPEC_BLOCKED` | Bad command/request, unsafe root or ref, missing or mismatched authoritative evidence, or failed shadow validation. No completed receipt should be inferred. |
| `SPEC_BLOCKED / RUNTIME_UNSUPPORTED` | CPython 3.11+ or the SQLite image round trip is unavailable. |
| `SPEC_BLOCKED / LIVE_PROVIDER_NOT_INSTALLED` | `TYPESAFE_JEV` was requested; a key cannot enable it. |
| Candidate `MODEL_UNAVAILABLE` | No cassette for that exact state and question-set version. This is a row-level unavailable result inside a valid receipt, not a CLI error or a synthetic probability. |
| `COMMAND_ID_CONFLICT` | A stored command ID was reused with different request or receipt content. |
| `INTEGRITY_ERROR` | Store, database, receipt, or request binding failed verification; do not consume the result. |
| `SPEC_BLOCKED / EVALUATION_NOT_INSTALLED` | The comparison command is a placeholder. |

All outputs retain `WORKFLOW_DEBUG` purpose. 不是买卖指令；研究信号，human executes.
