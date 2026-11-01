"""Closed, offline workflow metadata. This catalog is never dispatch authority."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from pathlib import Path

SCHEMA = "ar.workflow-catalog.v1"
DEFINITION_SCHEMA = "ar.workflow-definition.v1"
CATALOG_VERSION = "1.0"
DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[2] / "config/workflow-catalog.v1.json"
MAX_CATALOG_BYTES = 65536

_LABELS = {
    "sample_purpose": "WORKFLOW_DEBUG",
    "testing_status": "NOT_RUN",
    "human_review": "PENDING",
    "production_authority": False,
    "trading_authority": False,
    "dispatch_authority": False,
    "provider": "NONE",
    "network_policy": "OFFLINE",
}
_SHARED_PROFILE = {"slots": 2, "per_actor_limit": 2, "global_limit": 20,
                   "timeout_seconds": 120, "max_attempts": 2}
_ROOT_FIELDS = set(_LABELS) | {"schema", "catalog_version", "catalog_hash", "workflows"}
_DEFINITION_FIELDS = set(_LABELS) | {
    "schema", "kind", "availability", "shared_status", "profile",
    "inputs", "outputs", "evidence_refs",
}
_WORKSPACE = "scripts/llm/workbench_workspace.py#Workspace."


def _contracts(items):
    return [{"name": name, "schema": schema,
             "schema_status": "UNSPECIFIED" if schema is None else "DECLARED"}
            for name, schema in items]


# These are source-inspected reference contracts, not a worker/router registry.
# The unversioned job result is distinct from any versioned artifact it refers to.
_DEFINITIONS = {
    "observe": {
        "availability": "existing-shared",
        "inputs": _contracts((("isolated-job-request", None),
                              ("shared-input", "ar.shared-input.v1"))),
        "outputs": _contracts((("job-result", None),
                               ("observation", "ar-workbench-observation.v1"),
                               ("shared-output-seal", "ar.shared-job-output.v1"))),
        "evidence_refs": [
            _WORKSPACE + "observe", "scripts/llm/workbench_evidence.py#capture",
            "scripts/llm/workbench_shared_inputs.py#FrozenInputs",
            "scripts/llm/workbench_shared_worker.py#_output_result",
        ],
    },
    "snapshot-brief": {
        "availability": "existing-shared",
        "inputs": _contracts((("isolated-job-request", None),
                              ("shared-input", "ar.shared-input.v1"),
                              ("observation", "ar-workbench-observation.v1"))),
        "outputs": _contracts((("job-result", None),
                               ("brief-receipt", "ar.workbench-snapshot-brief.v1"),
                               ("shared-output-seal", "ar.shared-job-output.v1"))),
        "evidence_refs": [
            _WORKSPACE + "start_job", "scripts/llm/workbench_snapshot_brief.py#run",
            "scripts/llm/workbench_snapshot_brief.py#run_frozen",
            "scripts/llm/workbench_shared_worker.py#verify_seal",
        ],
    },
    "integrity": {
        "availability": "isolated-only",
        "inputs": _contracts((("isolated-job-request", None),)),
        "outputs": _contracts((("job-result", None),)),
        "evidence_refs": [_WORKSPACE + "verify_all"],
    },
    "backup": {
        "availability": "isolated-only",
        "inputs": _contracts((("isolated-job-request", None),)),
        "outputs": _contracts((("job-result", None),
                               ("backup-manifest", "ar-workspace-backup.v1"),
                               ("data-export", "ar-workspace-data-export.v1"))),
        "evidence_refs": [_WORKSPACE + "start_job", "scripts/llm/workbench_backup.py#create"],
    },
    "research-replay": {
        "availability": "isolated-only",
        "inputs": _contracts((("isolated-job-request", None),)),
        "outputs": _contracts((("job-result", None),
                               ("replay-receipt", "ar-workbench-research-receipt.v1"))),
        "evidence_refs": [
            _WORKSPACE + "start_job", "scripts/llm/nonprod_workbench.py#Store.replay",
            "scripts/llm/workbench_research.py#perform",
        ],
    },
    "brief-trial": {
        "availability": "isolated-only",
        "inputs": _contracts((("isolated-job-request", None),
                              ("frozen-trial-request", "ar.workflow-trial.v1"))),
        "outputs": _contracts((("job-result", None),
                               ("trial-artifact", "ar.workflow-trial-result.v1"),
                               ("trial-receipt", "ar.workflow-trial-result.v1"),
                               ("review-template", "ar.workflow-trial-review-template.v1"))),
        "evidence_refs": [
            _WORKSPACE + "start_job", "scripts/llm/workbench_brief_trial.py#run",
            "experiments/research_workflows/trial.py#build",
        ],
    },
    "earnings-trial": {
        "availability": "isolated-only",
        "inputs": _contracts((("isolated-job-request", None),
                              ("frozen-trial-request", "ar.workflow-trial.v1"))),
        "outputs": _contracts((("job-result", None),
                               ("trial-artifact", "ar.workflow-trial-result.v1"),
                               ("trial-receipt", "ar.workflow-trial-result.v1"),
                               ("review-template", "ar.workflow-trial-review-template.v1"))),
        "evidence_refs": [
            _WORKSPACE + "start_job", "scripts/llm/workbench_earnings_trial.py#run",
            "experiments/research_workflows/trial.py#build",
        ],
    },
}


def _exact(value, fields, code):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(code)


def _labels(value, schema):
    for field, expected in {"schema": schema, **_LABELS}.items():
        if type(value[field]) is not type(expected) or value[field] != expected:
            raise ValueError("WORKFLOW_LABELS_INVALID")


def _validate_contracts(value, expected):
    if not isinstance(value, list):
        raise ValueError("WORKFLOW_CONTRACT_INVALID")
    for item in value:
        _exact(item, {"name", "schema", "schema_status"}, "WORKFLOW_CONTRACT_INVALID")
    if value != expected:
        raise ValueError("WORKFLOW_CONTRACT_INVALID")


def validate_workflow_catalog(value):
    """Validate a complete V1 catalog and return an independent metadata copy.

    Raises ValueError for malformed or unsupported definitions. A matching hash
    proves content consistency only, never human approval or running-code identity.
    No source code, provider, queue, service, or workflow is invoked.
    """
    _exact(value, _ROOT_FIELDS, "WORKFLOW_CATALOG_FIELDS_INVALID")
    _labels(value, SCHEMA)
    if value["catalog_version"] != CATALOG_VERSION:
        raise ValueError("WORKFLOW_CATALOG_VERSION_INVALID")
    if not isinstance(value["catalog_hash"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["catalog_hash"]):
        raise ValueError("WORKFLOW_CATALOG_HASH_INVALID")
    if not isinstance(value["workflows"], list):
        raise ValueError("WORKFLOW_DEFINITIONS_INVALID")
    seen = set()
    for row in value["workflows"]:
        _exact(row, _DEFINITION_FIELDS, "WORKFLOW_DEFINITION_FIELDS_INVALID")
        _labels(row, DEFINITION_SCHEMA)
        kind = row["kind"]
        if not isinstance(kind, str) or kind not in _DEFINITIONS:
            raise ValueError("WORKFLOW_KIND_UNKNOWN")
        if kind in seen:
            raise ValueError("WORKFLOW_KIND_DUPLICATE")
        seen.add(kind)
        expected = _DEFINITIONS[kind]
        shared = expected["availability"] == "existing-shared"
        if (row["availability"] != expected["availability"]
                or row["shared_status"] != ("existing-shared" if shared else "not-wired")):
            raise ValueError("WORKFLOW_AVAILABILITY_INVALID")
        profile = row["profile"]
        if shared:
            _exact(profile, set(_SHARED_PROFILE), "WORKFLOW_PROFILE_INVALID")
            if any(type(profile[key]) is not int or profile[key] != limit
                   for key, limit in _SHARED_PROFILE.items()):
                raise ValueError("WORKFLOW_PROFILE_INVALID")
        elif profile is not None:
            raise ValueError("WORKFLOW_PROFILE_INVALID")
        _validate_contracts(row["inputs"], expected["inputs"])
        _validate_contracts(row["outputs"], expected["outputs"])
        if row["evidence_refs"] != expected["evidence_refs"]:
            raise ValueError("WORKFLOW_EVIDENCE_INVALID")
    if seen != set(_DEFINITIONS):
        raise ValueError("WORKFLOW_KINDS_INCOMPLETE")
    body = {key: item for key, item in value.items() if key != "catalog_hash"}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode("utf-8")
    if hashlib.sha256(raw).hexdigest() != value["catalog_hash"]:
        raise ValueError("WORKFLOW_CATALOG_HASH_MISMATCH")
    return copy.deepcopy(value)


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("WORKFLOW_CATALOG_DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _nonfinite(_value):
    raise ValueError("WORKFLOW_CATALOG_NONFINITE_JSON")


def load_workflow_catalog(path=None):
    """Read one bounded regular local JSON file, without writes or imports.

    Explicit paths are caller-owned local inputs, not HTTP or dispatch parameters.
    Symlinks, duplicate keys, non-finite values and unsupported metadata fail closed.
    """
    path = DEFAULT_CATALOG_PATH if path is None else Path(path)
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("WORKFLOW_CATALOG_SYMLINK")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("WORKFLOW_CATALOG_NOT_REGULAR")
        raw = stream.read(MAX_CATALOG_BYTES + 1)
    if len(raw) > MAX_CATALOG_BYTES:
        raise ValueError("WORKFLOW_CATALOG_SIZE_LIMIT")
    try:
        value = json.loads(raw, object_pairs_hook=_object, parse_constant=_nonfinite)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("WORKFLOW_CATALOG_JSON_INVALID") from None
    return validate_workflow_catalog(value)


def get_workflow(kind, catalog=None):
    """Return one labeled definition after validating the entire catalog.

    Availability describes existing boundaries; it grants no execution rights.
    Unknown kinds are rejected, including standalone renderers without a job kind.
    """
    if not isinstance(kind, str) or kind not in _DEFINITIONS:
        raise ValueError("WORKFLOW_KIND_UNKNOWN")
    validated = load_workflow_catalog() if catalog is None else validate_workflow_catalog(catalog)
    return next(row for row in validated["workflows"] if row["kind"] == kind)
