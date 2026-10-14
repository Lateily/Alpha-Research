"""Registered immutable scoped publications and safe attempt observations."""
from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from pathlib import Path

import workbench_evidence as ev
import workbench_snapshot_brief as brief
from workbench_backup import write_new
from workbench_workspace import WorkspaceError

POINTER = "public/data/v2/current_run.json"
ATTEMPT = "experiments/execution_tracker/nightly_run.json"
SCOPE = "SCOPED_SNAPSHOT_NOT_FULL_NIGHTLY_ACCEPTANCE"


def publication_paths(snapshot):
    rid, date = snapshot.get("published_run_id"), snapshot.get("target_trade_date")
    if not isinstance(rid, str) or not re.fullmatch(ev.ID, rid):
        raise WorkspaceError("FROZEN_PUBLICATION_ID_INVALID", 409)
    if not isinstance(date, str) or not re.fullmatch(r"\d{8}", date):
        raise WorkspaceError("FROZEN_PUBLICATION_DATE_INVALID", 409)
    return {POINTER, f"public/data/v2/runs/{rid}/manifest.json",
            *("public/data/v2/" + name for name in ev.PUBLIC),
            *(f"data_history/funnel/{date}/{rid}/" + name for name in ev.BUNDLE)}


def validate_snapshot(snapshot, frozen_root, *, sealed_originals=False):
    """One boundary for imports, reopening and isolated rendering."""
    ev.verify(snapshot)
    frozen_root = Path(frozen_root)
    if any(p.is_symlink() for p in (frozen_root, *frozen_root.parents)):
        raise WorkspaceError("FROZEN_ROOT_SYMLINK", 409)
    paths = publication_paths(snapshot)
    if sealed_originals:
        actual = {p.relative_to(frozen_root).as_posix() for p in frozen_root.rglob("*") if p.is_file() or p.is_symlink()}
        if actual != paths | {"publication.json"}:
            raise WorkspaceError("FROZEN_ORIGINAL_INVENTORY_INVALID", 409)
    records = snapshot.get("records")
    if not isinstance(records, dict) or set(records) != paths | {ATTEMPT}:
        raise WorkspaceError("FROZEN_WHITELIST_INVALID", 409)
    brief.render(snapshot)  # Existing date, credential, run and module guards.
    originals = {}
    for name in sorted(paths):
        row = records[name]
        if row.get("status") != "OBSERVED" or row.get("binding") != ("UNBOUND" if name == POINTER else "MATCH"):
            raise WorkspaceError("FROZEN_PUBLICATION_MISSING_OR_CONFLICTING", 409)
        try:
            raw = ev.read_local(Path(frozen_root), name)
        except OSError:
            raise WorkspaceError("FROZEN_ORIGINAL_UNAVAILABLE", 409) from None
        value = ev.parse(raw)
        brief.reject_credentials(value)
        if name != POINTER:
            identity, _run, date = ev.artifact_identity(row, snapshot["published_run_id"], snapshot["target_trade_date"])
            if identity != "BOUND_TO_PUBLISHED_RUN" or date != snapshot["target_trade_date"]:
                raise WorkspaceError("FROZEN_MODULE_IDENTITY_REQUIRED", 409)
        if ev.sha(raw) != row.get("source_sha256") or value != row.get("payload"):
            raise WorkspaceError("FROZEN_ORIGINAL_CONFLICT", 409)
        originals[name] = raw
    rid, date = snapshot["published_run_id"], snapshot["target_trade_date"]
    pointer = records[POINTER]["payload"]
    manifest = records[f"public/data/v2/runs/{rid}/manifest.json"]["payload"]
    if (pointer.get("schema") != "nightly_current_run/v2" or pointer.get("run_id") != rid
            or pointer.get("target_trade_date") != date or pointer.get("manifest_path") != f"runs/{rid}/manifest.json"
            or manifest.get("schema") != "nightly_manifest/v2" or manifest.get("run_id") != rid
            or manifest.get("target_trade_date") != date
            or not isinstance(pointer.get("manifest_sha256"), str)
            or pointer["manifest_sha256"].removeprefix("sha256:") != records[f"public/data/v2/runs/{rid}/manifest.json"]["source_sha256"]):
        raise WorkspaceError("FROZEN_PUBLICATION_BINDING_INVALID", 409)
    health = records["public/data/v2/funnel_health.json"]["payload"]
    bundle = health.get("bundle")
    location = f"data_history/funnel/{date}/{rid}"
    if (health.get("run_id") != rid or health.get("as_of") != date or not isinstance(bundle, dict)
            or bundle.get("location") != location):
        raise WorkspaceError("FROZEN_BUNDLE_BINDING_INVALID", 409)
    for names, hashes, prefix, key_prefix in (
        (ev.PUBLIC, pointer.get("artifacts"), "public/data/v2/", "public:"),
        (ev.BUNDLE, bundle.get("artifacts"), location + "/", ""),
    ):
        if not isinstance(hashes, dict):
            raise WorkspaceError("FROZEN_HASH_CATALOG_INVALID", 409)
        for name in names:
            expected = hashes.get(key_prefix + name)
            if not isinstance(expected, str) or expected.removeprefix("sha256:") != records[prefix + name]["source_sha256"]:
                raise WorkspaceError("FROZEN_HASH_CATALOG_INVALID", 409)
    attempt = records[ATTEMPT]
    if attempt.get("status") == "OBSERVED":
        payload = attempt.get("payload")
        keys = {"run_id", "target_trade_date", "generated_at", "report", "data_quality", "research_data_quality", "published", "steps"}
        step_keys = {"step", "status", "exit_code", "elapsed_sec", "blocks_publication"}
        if (attempt.get("projection") != "OPERATIONAL_FIELDS_ONLY" or not isinstance(payload, dict)
                or set(payload) != keys or not isinstance(payload["steps"], list)
                or any(not isinstance(row, dict) or set(row) != step_keys for row in payload["steps"])):
            raise WorkspaceError("FROZEN_ATTEMPT_PROJECTION_INVALID", 409)
    elif attempt != {"status": "MISSING_OR_INVALID", "binding": "UNVERIFIED", "payload": None, "source_sha256": None}:
        raise WorkspaceError("FROZEN_ATTEMPT_PROJECTION_INVALID", 409)
    if sealed_originals or "frozen_input_hash" in snapshot:
        _publication, pub_hash, attempt_hash = fingerprints(snapshot, originals)
        if snapshot.get("frozen_input_hash") != ev.sealed({"publication_fingerprint": pub_hash, "attempt_fingerprint": attempt_hash}):
            raise WorkspaceError("FROZEN_CONTENT_IDENTITY_INVALID", 409)
    return originals


def fingerprints(snapshot, originals):
    publication = {"source_run_id": snapshot["published_run_id"], "source_trade_date": snapshot["target_trade_date"],
                   "files": {name: ev.sha(raw) for name, raw in originals.items()}}
    return publication, ev.sealed(publication), ev.sealed(snapshot["records"][ATTEMPT])


def _new_or_identical(path, raw):
    if len(raw) > ev.MAX_FILE:
        raise WorkspaceError("FROZEN_FILE_SIZE_LIMIT", 409)
    if path.exists() or path.is_symlink():
        if ev.read_local(path.parent, path.name) != raw:
            raise WorkspaceError("FROZEN_EXISTING_CONTENT_CONFLICT", 409)
    else:
        write_new(path, raw)


class FrozenInputs:
    def __init__(self, store):
        if not store.shared_v1:
            raise WorkspaceError("SHARED_INPUT_STORE_REQUIRED", 403)
        self.store = store
        self.base = store.path.parent / "frozen-inputs"

    def import_once(self, source_root: Path) -> dict:
        source_root = Path(source_root)
        state_root = self.store.path.parent.resolve()
        source = source_root.resolve()
        if source == state_root or source in state_root.parents or state_root in source.parents:
            raise WorkspaceError("FROZEN_SOURCE_STATE_OVERLAP", 409)
        snapshot = ev.capture(source_root)
        originals = validate_snapshot(snapshot, source_root)
        publication, pub_hash, attempt_hash = fingerprints(snapshot, originals)
        input_hash = ev.sealed({"publication_fingerprint": pub_hash, "attempt_fingerprint": attempt_hash})
        snapshot["frozen_input_hash"] = input_hash
        snapshot["snapshot_hash"] = ev.sealed({k: v for k, v in snapshot.items() if k != "snapshot_hash"})
        # Capture and copying cannot straddle a public pointer replacement.
        if ev.read_local(source_root, POINTER) != originals[POINTER]:
            raise WorkspaceError("SOURCE_CHANGED", 409)
        if any(p.is_symlink() for p in (self.base, *self.base.parents)):
            raise WorkspaceError("FROZEN_DIRECTORY_INVALID", 409)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT snapshot_id FROM shared_inputs WHERE input_hash=?", (input_hash,)).fetchone()
            if prior:
                return self._descriptor(self.verify(prior[0]))
            if db.execute("SELECT COUNT(*) FROM shared_inputs").fetchone()[0] >= 100:
                raise WorkspaceError("FROZEN_INPUT_CAPACITY_BLOCKED", 429)
            publications = self.base / "publications"
            publications.mkdir(parents=True, exist_ok=True, mode=0o700)
            frozen_root = publications / pub_hash
            if not frozen_root.exists():
                with tempfile.TemporaryDirectory(prefix=".capture-", dir=publications) as temporary:
                    staging = Path(temporary) / "publication"
                    staging.mkdir(mode=0o700)
                    for name, raw in originals.items():
                        _new_or_identical(staging / name, raw)
                    _new_or_identical(staging / "publication.json", ev.canonical(publication).encode())
                    validate_snapshot(snapshot, staging, sealed_originals=True)
                    os.rename(staging, frozen_root)
            _new_or_identical(frozen_root / "publication.json", ev.canonical(publication).encode())
            validate_snapshot(snapshot, frozen_root, sealed_originals=True)
            attempt = snapshot["records"][ATTEMPT]
            _new_or_identical(self.base / "attempts" / (attempt_hash + ".json"), ev.canonical(attempt).encode())
            snapshot_id = str(uuid.uuid4())
            envelope = {"schema": "ar.shared-input.v1", "snapshot_id": snapshot_id, "input_hash": input_hash,
                        "publication_fingerprint": pub_hash, "attempt_fingerprint": attempt_hash,
                        "source_run_id": snapshot["published_run_id"], "source_trade_date": snapshot["target_trade_date"],
                        "validation_scope": SCOPE, "snapshot": snapshot}
            _new_or_identical(self.base / "envelopes" / (snapshot_id + ".json"), ev.canonical(envelope).encode())
            if ev.read_local(source_root, POINTER) != originals[POINTER]:
                raise WorkspaceError("SOURCE_CHANGED", 409)
            db.execute("INSERT INTO shared_inputs VALUES (?, ?, ?)", (snapshot_id, input_hash, ev.canonical(envelope)))
        return self._descriptor(self.verify(snapshot_id))

    @staticmethod
    def _descriptor(envelope):
        return {k: envelope[k] for k in ("snapshot_id", "input_hash", "publication_fingerprint", "attempt_fingerprint",
                                        "source_run_id", "source_trade_date", "validation_scope")}

    def verify(self, snapshot_id: str) -> dict:
        try:
            if not isinstance(snapshot_id, str) or str(uuid.UUID(snapshot_id)) != snapshot_id:
                raise ValueError
        except (ValueError, AttributeError):
            raise WorkspaceError("FROZEN_SNAPSHOT_ID_INVALID", 409) from None
        with self.store.connect() as db:
            row = db.execute("SELECT input_hash, body FROM shared_inputs WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise WorkspaceError("FROZEN_SNAPSHOT_NOT_REGISTERED", 404)
        return self.verify_registered(self.base, snapshot_id, row)

    @staticmethod
    def verify_registered(base, snapshot_id, row):
        """Reopen a fixed exported registry row using the same live boundary."""
        try:
            envelope = ev.parse(ev.read_local(base, "envelopes/" + snapshot_id + ".json"))
            registered = ev.parse(row[1])
            if envelope != registered or envelope.get("snapshot_id") != snapshot_id or envelope.get("input_hash") != row[0]:
                raise WorkspaceError("FROZEN_REGISTRY_BINDING_INVALID", 409)
            pub_hash, attempt_hash = envelope["publication_fingerprint"], envelope["attempt_fingerprint"]
            if any(not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h) for h in (pub_hash, attempt_hash)):
                raise WorkspaceError("FROZEN_FINGERPRINT_INVALID", 409)
            frozen_root = base / "publications" / pub_hash
            originals = validate_snapshot(envelope["snapshot"], frozen_root, sealed_originals=True)
            publication, actual_pub, actual_attempt = fingerprints(envelope["snapshot"], originals)
            if (actual_pub != pub_hash or actual_attempt != attempt_hash
                    or ev.parse(ev.read_local(frozen_root, "publication.json")) != publication
                    or ev.parse(ev.read_local(base, "attempts/" + attempt_hash + ".json")) != envelope["snapshot"]["records"][ATTEMPT]
                    or ev.sealed({"publication_fingerprint": pub_hash, "attempt_fingerprint": attempt_hash}) != row[0]
                    or envelope.get("schema") != "ar.shared-input.v1" or envelope.get("validation_scope") != SCOPE
                    or envelope.get("source_run_id") != envelope["snapshot"]["published_run_id"]
                    or envelope.get("source_trade_date") != envelope["snapshot"]["target_trade_date"]):
                raise WorkspaceError("FROZEN_SEAL_BINDING_INVALID", 409)
        except (OSError, KeyError, TypeError):
            raise WorkspaceError("FROZEN_SEAL_UNAVAILABLE_OR_INVALID", 409) from None
        return {**envelope, "frozen_root": frozen_root}
