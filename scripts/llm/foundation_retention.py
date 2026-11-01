"""Local immutable references to independently identified portable backups."""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath

import workbench_backup as backup
import workbench_evidence as ev
from workbench_shared_inputs import FrozenInputs, SCOPE
from workbench_snapshot_brief import reject_credentials

SCHEMA = "ar.retention-pin.v1"
LABELS = {"sample_purpose": "WORKFLOW_DEBUG", "testing_status": "NOT_RUN",
          "human_review": "PENDING", "production_authority": False,
          "trading_authority": False}
LIMITS = {"off_machine_retention": "NOT_ATTESTED", "source_rights": "NOT_ATTESTED",
          "case_authorization": "NOT_VERIFIED", "deletion_authority": False}
MAX_SELECTIONS = 100
MAX_PIN_BYTES = 1024 * 1024
SNAPSHOT_FIELDS = ("snapshot_id", "input_hash", "publication_fingerprint",
                   "attempt_fingerprint", "source_run_id", "source_trade_date",
                   "validation_scope")
SNAPSHOT_KEYS = {*SNAPSHOT_FIELDS, "snapshot_hash", "envelope_ref", "publication_ref",
                 "attempt_ref", "records"}
JOB_KEYS = {"job_id", "registration", "registry_hash", "kind", "status", "binding",
            "result", "artifact_refs"}
JOB_BINDING_FIELDS = ("job_id", "command_id", "workspace_id", "actor", "snapshot_id", "input_hash",
                      "code_sha", "source_tree_hash", "source_run_id", "source_trade_date", "attempt_id",
                      "schema_version", "job_schema", "input_schema", "output_hash")
BACKUP_KEYS = {"backup_hash", "schema", "inventory_scope", "manifest_ref", "data_ref",
               "credentials_included"}
PIN_KEYS = {"schema", *LABELS, "created_at", "backup", "snapshots", "jobs", "case_refs",
            "limitations", "pin_hash"}


def _fail(code):
    raise ev.EvidenceError("RETENTION_" + code)


def _json_copy(value):
    """Bound containers before serialization, including cyclic caller inputs."""
    pending, nodes, characters = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 50000 or depth > 16:
            _fail("JSON_LIMIT")
        if type(item) is dict:
            if len(item) > 50000 or any(type(key) is not str for key in item):
                _fail("JSON_SHAPE_INVALID")
            pending.extend((child, depth + 1) for child in item.values())
            pending.extend((key, depth + 1) for key in item)
        elif type(item) is list:
            if len(item) > 50000:
                _fail("JSON_LIMIT")
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            characters += len(item)
            if characters > MAX_PIN_BYTES:
                _fail("JSON_LIMIT")
        elif item is not None and type(item) not in {bool, int, float}:
            _fail("JSON_SHAPE_INVALID")
    try:
        raw = ev.canonical(value).encode("utf-8")
    except (ValueError, OverflowError):
        _fail("JSON_SHAPE_INVALID")
    if len(raw) > MAX_PIN_BYTES:
        _fail("JSON_LIMIT")
    result = ev.parse(raw)
    reject_credentials(result)
    return result


def _hash(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        _fail("HASH_INVALID")
    return value


def _identifier(value, *, snapshot=False):
    if type(value) is not str or not re.fullmatch(ev.ID, value):
        _fail("IDENTITY_INVALID")
    if snapshot:
        try:
            if str(uuid.UUID(value)) != value:
                raise ValueError
        except ValueError:
            _fail("SNAPSHOT_ID_INVALID")
    return value


def _ref(value):
    if (type(value) is not str or len(value) > 1024
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}(?:/[A-Za-z0-9][A-Za-z0-9_.-]{0,150}){0,7}", value)
            or any(part in {".", ".."} for part in PurePosixPath(value).parts)):
        _fail("PORTABLE_REFERENCE_INVALID")
    return value


def _selection(values, *, snapshot=False, refs=False):
    if type(values) not in {list, tuple} or len(values) > MAX_SELECTIONS:
        _fail("SELECTION_LIMIT_OR_SHAPE")
    result = [_ref(value) if refs else _identifier(value, snapshot=snapshot) for value in values]
    if len(set(result)) != len(result):
        _fail("DUPLICATE_SELECTION")
    return sorted(result)


def _time(value):
    if (type(value) is not str or len(value) > 40
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value)):
        _fail("CREATED_AT_INVALID")
    try:
        if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
            raise ValueError
        if datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is None:
            raise ValueError
    except ValueError:
        _fail("CREATED_AT_INVALID")
    return value


def _root(value, *, existing=False):
    if not isinstance(value, (str, Path)):
        _fail("ROOT_INVALID")
    raw = str(value)
    if (not raw or len(raw) > 4096 or "://" in raw or "\\" in raw
            or any(ord(char) < 32 or ord(char) == 127 for char in raw)):
        _fail("ROOT_INVALID")
    path = Path(value).absolute()
    if ".." in path.parts or len(path.parts) > 128:
        _fail("ROOT_INVALID")
    if any(part.is_symlink() for part in (path, *path.parents)):
        _fail("ROOT_SYMLINK")
    if (path.exists() and not path.is_dir()) or (existing and not path.is_dir()):
        _fail("ROOT_INVALID")
    return path


def _exact(value, keys):
    if type(value) is not dict or set(value) != keys:
        _fail("PIN_SHAPE_INVALID")


def _validate_pin(value):
    pin = _json_copy(value)
    _exact(pin, PIN_KEYS)
    if (pin["schema"] != SCHEMA or ev.canonical(pin["limitations"]) != ev.canonical(LIMITS)
            or any(type(pin[key]) is not type(expected) or pin[key] != expected
                   for key, expected in LABELS.items())):
        _fail("LABEL_OR_AUTHORITY_INVALID")
    _time(pin["created_at"])
    _exact(pin["backup"], BACKUP_KEYS)
    archive = pin["backup"]
    _hash(archive["backup_hash"])
    if (archive["schema"] not in ("ar-workspace-backup.v1", "ar-shared-workspace-backup.v1")
            or archive["inventory_scope"] not in ("ISOLATED_STATE_ARTIFACT_ROOTS", "LEGACY_BACKUP_CONTENT_ONLY")
            or archive["manifest_ref"] != "manifest.json" or archive["data_ref"] != "data.json"
            or archive["credentials_included"] is not False):
        _fail("BACKUP_REFERENCE_INVALID")
    for rows, keys in ((pin["snapshots"], SNAPSHOT_KEYS), (pin["jobs"], JOB_KEYS)):
        if type(rows) is not list or len(rows) > MAX_SELECTIONS:
            _fail("SELECTION_LIMIT_OR_SHAPE")
        for row in rows:
            _exact(row, keys)
    if not pin["snapshots"] and not pin["jobs"]:
        _fail("REGISTERED_SELECTION_REQUIRED")
    snapshots = _selection([row["snapshot_id"] for row in pin["snapshots"]], snapshot=True)
    jobs = _selection([row["job_id"] for row in pin["jobs"]])
    if snapshots != [row["snapshot_id"] for row in pin["snapshots"]] or jobs != [row["job_id"] for row in pin["jobs"]]:
        _fail("SELECTION_ORDER_INVALID")
    for row in pin["snapshots"]:
        for key in ("input_hash", "publication_fingerprint", "attempt_fingerprint", "snapshot_hash"):
            _hash(row[key])
        for key in ("envelope_ref", "publication_ref", "attempt_ref"):
            _ref(row[key])
        _identifier(row["source_run_id"])
        if (type(row["source_trade_date"]) is not str or not re.fullmatch(r"[0-9]{8}", row["source_trade_date"])
                or row["validation_scope"] != SCOPE
                or row["envelope_ref"] != f"frozen-inputs/envelopes/{row['snapshot_id']}.json"
                or row["publication_ref"] != "frozen-inputs/publications/" + row["publication_fingerprint"]
                or row["attempt_ref"] != "frozen-inputs/attempts/" + row["attempt_fingerprint"] + ".json"):
            _fail("SNAPSHOT_REFERENCE_INVALID")
        if type(row["records"]) is not dict:
            _fail("RECORDS_INVALID")
        for name, record in row["records"].items():
            _ref(name)
            _exact(record, {"status", "binding", "source_sha256"})
            if type(record["status"]) is not str or type(record["binding"]) is not str:
                _fail("RECORDS_INVALID")
            if record["source_sha256"] is not None:
                _hash(record["source_sha256"])
    for row in pin["jobs"]:
        _hash(row["registry_hash"])
        if (row["registration"] not in ("shared_jobs", "workspace_events")
                or type(row["binding"]) is not dict or type(row["kind"]) is not str
                or type(row["status"]) is not str
                or (row["result"] is not None and type(row["result"]) is not dict)
                or type(row["artifact_refs"]) is not list or len(row["artifact_refs"]) > 10000):
            _fail("JOB_REFERENCE_INVALID")
        binding = row["binding"]
        if set(binding) - set(JOB_BINDING_FIELDS) or binding.get("job_id") != row["job_id"]:
            _fail("JOB_REFERENCE_INVALID")
        for key, value in binding.items():
            if value is None:
                continue
            if (type(value) is not str or len(value) > 254
                    or (key != "actor" and ("/" in value or "\\" in value))
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                _fail("JOB_REFERENCE_INVALID")
            if key in {"input_hash", "source_tree_hash", "output_hash"}:
                _hash(value)
            elif key in {"workspace_id", "snapshot_id", "attempt_id"}:
                _identifier(value, snapshot=True)
        for name in row["artifact_refs"]:
            _ref(name)
    if type(pin["case_refs"]) is not list or len(pin["case_refs"]) > MAX_SELECTIONS:
        _fail("CASE_REFERENCES_INVALID")
    for note in pin["case_refs"]:
        _exact(note, {"ref", "verification", "case_authority"})
        if note["verification"] != "NOT_VERIFIED" or note["case_authority"] is not False:
            _fail("CASE_AUTHORITY_REFUSED")
    refs = _selection([note["ref"] for note in pin["case_refs"]], refs=True)
    if refs != [note["ref"] for note in pin["case_refs"]]:
        _fail("SELECTION_ORDER_INVALID")
    if _hash(pin["pin_hash"]) != ev.sealed({key: value for key, value in pin.items() if key != "pin_hash"}):
        _fail("PIN_HASH_INVALID")
    return pin


def _snapshot(root, row):
    snapshot_id, input_hash, body = row
    envelope = FrozenInputs.verify_registered(root / "frozen-inputs", snapshot_id, (input_hash, body))
    return {**{key: envelope[key] for key in SNAPSHOT_FIELDS},
            "snapshot_hash": envelope["snapshot"]["snapshot_hash"],
            "envelope_ref": f"frozen-inputs/envelopes/{snapshot_id}.json",
            "publication_ref": "frozen-inputs/publications/" + envelope["publication_fingerprint"],
            "attempt_ref": "frozen-inputs/attempts/" + envelope["attempt_fingerprint"] + ".json",
            "records": {name: {key: record[key] for key in ("status", "binding", "source_sha256")}
                        for name, record in envelope["snapshot"]["records"].items()}}


def _registered_jobs(tables, manifest):
    jobs = {}
    events = [ev.parse(row[3]) for row in tables["workspace_events"]]
    for job in backup.legacy_jobs(tables["workspace_events"]):
        identity = _identifier(job["job_id"])
        registered = [event for event in events if event["data"].get("job_id") == identity]
        jobs[identity] = (job, "workspace_events", ev.sealed(registered))
    for row in tables["shared_jobs"]:
        identity = _identifier(row[0], snapshot=True)
        if identity in jobs:
            _fail("JOB_ID_AMBIGUOUS")
        jobs[identity] = (ev.parse(row[3]), "shared_jobs", ev.sha(row[3].encode("utf-8")))
    result = {}
    for identity, (job, registration, registry_hash) in jobs.items():
        names = sorted({name for group in manifest["artifact_inventory"] if group["job_id"] == identity
                        for name in group["files"]})
        result[identity] = {"job_id": identity, "registration": registration, "registry_hash": registry_hash,
                            "kind": job["kind"], "status": job["status"],
                            "binding": {key: job[key] for key in JOB_BINDING_FIELDS if key in job},
                            "result": job.get("result"), "artifact_refs": names}
    return result


def build_retention_pin(backup_root, *, expected_backup_hash, snapshot_ids, job_ids,
                        case_refs=(), created_at):
    """Reopen a verified archive, without capturing or copying current state."""
    expected_backup_hash = _hash(expected_backup_hash)
    snapshot_ids = _selection(snapshot_ids, snapshot=True)
    job_ids = _selection(job_ids)
    case_refs = _selection(case_refs, refs=True)
    _time(created_at)
    if not snapshot_ids and not job_ids:
        _fail("REGISTERED_SELECTION_REQUIRED")
    root = _root(backup_root, existing=True)
    # The caller's independently retained hash is never inferred from this archive.
    if ev.parse(ev.read_local(root, "manifest.json")).get("backup_hash") != expected_backup_hash:
        _fail("EXPECTED_BACKUP_HASH_MISMATCH")
    manifest, data = backup.read_shared(root)
    if manifest["backup_hash"] != expected_backup_hash:
        _fail("EXPECTED_BACKUP_HASH_MISMATCH")
    tables = data["tables"]
    registered = {}
    for row in tables["shared_inputs"]:
        if row[0] in registered:
            _fail("SNAPSHOT_ID_AMBIGUOUS")
        registered[row[0]] = row
    if set(snapshot_ids) - set(registered):
        _fail("SNAPSHOT_NOT_REGISTERED")
    jobs = _registered_jobs(tables, manifest)
    if set(job_ids) - set(jobs):
        _fail("JOB_NOT_REGISTERED")
    pin = {"schema": SCHEMA, **LABELS, "created_at": created_at,
           "backup": {"backup_hash": expected_backup_hash, "schema": manifest["schema"],
                      "inventory_scope": manifest["inventory_scope"], "manifest_ref": "manifest.json",
                      "data_ref": "data.json", "credentials_included": False},
           "snapshots": [_snapshot(root, registered[identity]) for identity in snapshot_ids],
           "jobs": [jobs[identity] for identity in job_ids],
           "case_refs": [{"ref": ref, "verification": "NOT_VERIFIED", "case_authority": False} for ref in case_refs],
           "limitations": dict(LIMITS)}
    # This existing verifier also reopens successful job outputs and original seals.
    if backup.verify_shared(root) != manifest:
        _fail("BACKUP_CHANGED")
    pin = _json_copy(pin)
    pin["pin_hash"] = ev.sealed(pin)
    return _validate_pin(pin)


def verify_retention_pin(pin, backup_root, *, expected_backup_hash):
    """Re-derive every selected archive identity, not merely the pin's self-hash."""
    pin = _validate_pin(pin)
    if pin["backup"]["backup_hash"] != _hash(expected_backup_hash):
        _fail("EXPECTED_BACKUP_HASH_MISMATCH")
    reopened = build_retention_pin(
        backup_root, expected_backup_hash=expected_backup_hash,
        snapshot_ids=[row["snapshot_id"] for row in pin["snapshots"]],
        job_ids=[row["job_id"] for row in pin["jobs"]],
        case_refs=[row["ref"] for row in pin["case_refs"]], created_at=pin["created_at"])
    if reopened != pin:
        _fail("PIN_ARCHIVE_BINDING_INVALID")
    return reopened


def write_retention_pin(pin_root, pin):
    """Publish one new local pin; the receipt does not re-attest archive storage."""
    pin = _validate_pin(pin)
    root = _root(pin_root)
    name = pin["pin_hash"] + ".json"
    path = root / name
    if path.exists() or path.is_symlink():
        _fail("PIN_ALREADY_EXISTS")
    backup.write_new(path, ev.canonical(pin).encode("utf-8"))
    return {"schema": "ar.retention-pin-write.v1", **LABELS, "status": "LOCAL_PIN_WRITTEN",
            "pin_hash": pin["pin_hash"], "pin_ref": name, "archive_reverified": False,
            **LIMITS}
