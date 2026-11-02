# Foundation Workflow Catalog V1

Status: IMPLEMENTED_UNTESTED. `sample_purpose=WORKFLOW_DEBUG`,
`testing_status=NOT_RUN`, `human_review=PENDING`. Production, trading and dispatch
authority are all false. This is package P of the approved foundation wave 2;
the user explicitly deferred all test execution until integration.

## Boundary

`config/workflow-catalog.v1.json` is a closed descriptive inventory of the seven
current `workbench_workspace.KINDS`, not a new job registry or dispatch allowlist.
The stdlib-only `scripts/llm/foundation_workflows.py` reads and validates metadata.
It imports no product module and never runs a workflow, provider, subprocess,
queue operation, scheduler, service, or database operation. It writes nothing.
No routing, HTTP, worker, queue, `EXECUTION_FILES`, state or runtime whitelist is
changed. A catalog entry cannot grant access, approve research, or activate work.

| Kind | Availability | Shared Status | Profile |
| --- | --- | --- | --- |
| `observe` | `existing-shared` | `existing-shared` | Existing bounded shared profile |
| `snapshot-brief` | `existing-shared` | `existing-shared` | Existing bounded shared profile |
| `integrity` | `isolated-only` | `not-wired` | null / unspecified |
| `backup` | `isolated-only` | `not-wired` | null / unspecified |
| `research-replay` | `isolated-only` | `not-wired` | null / unspecified |
| `brief-trial` | `isolated-only` | `not-wired` | null / unspecified |
| `earnings-trial` | `isolated-only` | `not-wired` | null / unspecified |

`existing-shared` describes the existing whitelist, not service availability or
permission to submit a job. `isolated-only` describes existing local code paths;
`not-wired` explicitly means there is no shared wiring for that kind. These five
entries do not become shared jobs. The standalone trial renderer's `smc` workflow
is not a workspace job kind and is deliberately not invented as one here.

The shared profile exactly preserves two concurrent slots, two active jobs per
actor, twenty active jobs globally, a 120-second deadline and at most two
attempts. These are observations of the existing bounds, not configurable
permissions. Isolated profiles remain null; no timeout, retry or concurrency
policy is inferred for them. `provider=NONE` and `network_policy=OFFLINE` are
fixed catalog boundaries, not a provider selection interface.

## APIs

- `validate_workflow_catalog(value)` validates the entire V1 catalog, including
  every definition, fixed labels, contracts, profile bounds and content hash.
  Returns a deep copy; raises `ValueError` on unsupported or malformed metadata.
- `load_workflow_catalog(path=None)` defaults to the repository-relative catalog
  resolved from the module location, not the working directory. An explicit
  caller-owned local file is read at most 65,537 bytes and rejected above 65,536.
  Symlink paths/parents, special files, duplicate JSON keys, non-finite values and
  malformed JSON are refused. Ordinary filesystem failures remain errors.
- `get_workflow(kind, catalog=None)` validates the complete supplied catalog, or
  loads the default, then returns an independent labeled definition. Unknown
  kinds fail with `WORKFLOW_KIND_UNKNOWN`; no fallback or dynamic import exists.

Catalogs use `schema=ar.workflow-catalog.v1` and `catalog_version=1.0` (a string).
Definitions returned by lookup use `schema=ar.workflow-definition.v1`. Those are
metadata schemas only; neither names a new workflow output schema. Catalog and
definition outputs always retain WORKFLOW_DEBUG / NOT_RUN / PENDING and explicit
false production, trading and dispatch authority. Validation does not promote
the testing status after checking metadata.

All object shapes are closed. Extra command, shell, argv, provider configuration,
approval, authority or arbitrary source-reference fields are rejected. Duplicate,
missing and unknown kinds are rejected, even when the content hash is recomputed.
Only `NONE` is accepted as the provider. False authority flags must be booleans,
not zero or the string `false`. Shared profile values must be exact integers;
even a smaller limit is not silently treated as a new approved profile.

## Schemas And Evidence

Each input/output reference contains `name`, `schema` and `schema_status`.
`DECLARED` means a schema identifier was found in the referenced existing code;
it does not mean JSON Schema validation or semantic acceptance was performed.
Unversioned isolated job requests and common job-result projections explicitly
use `schema=null`, `schema_status=UNSPECIFIED`. They are not assigned invented
schemas. Named output entries are logical artifact roles, not dispatch paths.

- Observation artifacts: `ar-workbench-observation.v1` from `workbench_evidence`.
- Shared input envelopes: `ar.shared-input.v1`; shared output seals:
  `ar.shared-job-output.v1`. These do not replace the underlying artifact schema.
- Snapshot brief receipt: `ar.workbench-snapshot-brief.v1`. The common job-result
  schema remains unspecified because shared and local projections differ.
- Local backup manifest/data: `ar-workspace-backup.v1` and
  `ar-workspace-data-export.v1`. This job does not describe or authorize the
  separate shared portable-backup operations.
- Fixed synthetic research replay receipt: `ar-workbench-research-receipt.v1`.
- Historical brief/earnings input: `ar.workflow-trial.v1`; artifact and receipt:
  `ar.workflow-trial-result.v1`; review template:
  `ar.workflow-trial-review-template.v1`. A template is never human approval.

Exact `evidence_refs` name repository source paths and symbols inspected for this
candidate. They are descriptive references, not dynamically loaded entrypoints,
source hashes, evidence that code is running, or an attestation of source rights.
Existing output bytes and their older labels are not modified or relabeled.

`catalog_hash` is lowercase SHA256 over the complete catalog except that field,
using UTF-8 JSON with sorted object keys, compact separators, ASCII escaping and
non-finite numbers forbidden. Array order is retained. The hash checks content
consistency only, not authenticity; recomputing it cannot bypass the independent
closed-contract checks. Future kind/schema/profile changes require coordinated
source, catalog and test review, not merely a resealed JSON edit.

## Deferred Verification

`tests/test_foundation_workflows.py` is written but NOT_RUN. It covers valid loads
and lookups, defensive copies, exact shared bounds, unavailable schemas, unknown
and duplicate kinds, missing/extra fields, malformed versions/hashes, resealed
profile/schema/authority changes, fake human approval, unsupported providers,
duplicate JSON keys, non-finite JSON, oversized files, symlinks and missing files.

Only static Python syntax, JSON/content-checksum and diff checks are allowed in
this batch. No test, build, mutation, browser, product import, new CLI, provider or
live-service probe is acceptance evidence here. After integration and an explicit
release of the deferred-test gate, the focused test module and the independent
wave-2 acceptance/review matrix must run against one frozen candidate. This
package does not claim PASS, a service upgrade, deployment or production repair.
