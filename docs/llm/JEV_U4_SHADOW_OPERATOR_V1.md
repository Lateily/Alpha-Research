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

### Loopback workbench view

Build the existing nonproduction UI and start the workbench with a dedicated
local state directory. The workbench remains bound to `127.0.0.1`; its browser
session is not human identity or an approval signature.

```bash
npm ci --ignore-scripts --no-audit --no-fund
node node_modules/vite/bin/vite.js build --config tools/nonprod_workbench/vite.config.js
python3 -B scripts/llm/nonprod_workbench.py --port 8771 --state-root /private/tmp/ar-jev-workbench
```

Open `http://127.0.0.1:8771/` and select **Jev U4 Shadow**. The only browser
scenario is `synthetic-mixed`. The browser sends a command ID and scenario ID,
not paths, provider settings, answers, keys, or approval fields. An uncertain
response retries the same command ID. The run list and detail reread and
verify the immutable shadow receipt; a changed receipt displays
`INTEGRITY_ERROR` without its prior conclusion. The UI can filter shadow
observations and download a verified receipt, but cannot evaluate a real
packet or record a formal U4 decision. `MODEL_UNAVAILABLE` is displayed as
missing model evidence, never as a synthetic probability.

The workbench does not authenticate team members and is not a remote service.
Do not expose it through a tunnel, grant team access, or use its synthetic
output as a production or research record. The fixed fixture contacts no
provider and incurs no model cost.

The UI deliberately does not show human U4 comparisons yet. The engine can
write a separate evaluation, but the workbench has no verified read contract
for that artifact. "未接入" means unavailable, not zero disagreement.

A `POLICY_PREVIEW` produced by the CLI under the **same nonproduction state
root** is not automatically displayed. An operator may register its command
ID server-side after the CLI `run` and `verify` steps succeed:

```bash
python3 scripts/llm/workbench_jev_shadow.py register-preview \
  --state-root /private/tmp/ar-jev-workbench \
  --command-id '<verified-preview-command-id>'
```

Registration rereads the immutable receipt through `ShadowStore` and requires
`POLICY_PREVIEW` mode. It does not run a provider or accept an evidence path.
The browser has no registration route. A real frozen packet preview is shown
as `POLICY_PREVIEW / SHADOW_ONLY`, not `SIMULATED` and not an investment signal.

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

## Offline human-decision comparison

Supply a **sandbox copy** of the formal U4 decision ledger and its matching
`.anchor.json` as direct files under `STATE_ROOT`. Never point this command at
the production ledger or set `STATE_ROOT` to a production directory. The reader
uses retained file descriptors and does not create a formal ledger lock. The requested
formal packet hash is the bare 64-character hash from the committed closure,
not the shadow pre-decision packet hash.

```bash
python3 scripts/llm/jev_u4_shadow.py evaluate \
  --state-root "$STATE_ROOT" \
  --command-id jev-u4-shadow-synthetic-mixed-001 \
  --ledger "$STATE_ROOT/sandbox-u4.jsonl" \
  --review-packet-hash '<committed-formal-review-packet-hash>'
```

The command verifies the R-015 chain and anchor, requires a committed closure,
reads its frozen review packet and current human decisions, then writes a
separate immutable `jev-u4-shadow/<command_id>/evaluation.json`. Exact replay
is idempotent; changed evaluation bytes for the same command ID conflict. A
missing or invalid sandbox ledger, or one changed during reading, fails closed.

The shadow `u4_pre_decision` packet and formal closure review packet have
different schemas and hashes. The bridge keeps both hashes and requires the
same run, bundle, U2 pool, U3 battery, and exact U2/U3 row hashes for each
shadow candidate. It compares the industry shadow subset against the complete
formal human decision set. Agreement is descriptive only; under 30 distinct
causal clusters the claim status is `INSUFFICIENT_INDEPENDENT_SAMPLE`, and no
sample count here grants a method-effectiveness, win-rate, alpha, paper, or
trading claim. This command does not start an automatic experiment.

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
| `SPEC_BLOCKED / SPEC_BLOCKED` during evaluate | Ledger is outside the sandbox root, missing, uncommitted, corrupt, or its formal packet/evidence does not bind to the shadow receipt. |

All outputs retain `WORKFLOW_DEBUG` purpose. 不是买卖指令；研究信号，human executes.
