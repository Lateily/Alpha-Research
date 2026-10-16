"""Registered immutable scoped publications and safe attempt observations."""
from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import workbench_evidence as ev
import workbench_snapshot_brief as brief
from workbench_backup import write_new
from workbench_workspace import Workspace, WorkspaceError

POINTER = "public/data/v2/current_run.json"
ATTEMPT = "experiments/execution_tracker/nightly_run.json"
SCOPE = "SCOPED_SNAPSHOT_NOT_FULL_NIGHTLY_ACCEPTANCE"
OPTIONAL_ALIASES = {"macro_gate.json"}
_UNSET_ATTEMPT = object()
SELECTION_EVENT = "SHARED_INPUT_SELECTED"
SYNC_ACTOR = "SYSTEM_READ_ONLY_SYNC"
# The second spelling is the explicitly retained legacy observation contract.
# governance-mutation: WORKBENCH_SHARED_PUBLISHER_MANIFEST
MANIFEST_SCHEMAS = {"nightly_publish_manifest/v2", "nightly_manifest/v2"}


def _bundle_catalog_binding(snapshot):
    try:
        return ev.bundle_catalog_binding(snapshot)
    except ev.EvidenceError as error:
        raise WorkspaceError(str(error), 409) from error


def publication_paths(snapshot):
    rid, date = snapshot.get("published_run_id"), snapshot.get("target_trade_date")
    if not isinstance(rid, str) or not re.fullmatch(ev.ID, rid):
        raise WorkspaceError("FROZEN_PUBLICATION_ID_INVALID", 409)
    if not isinstance(date, str) or not re.fullmatch(r"\d{8}", date):
        raise WorkspaceError("FROZEN_PUBLICATION_DATE_INVALID", 409)
    return {POINTER, f"public/data/v2/runs/{rid}/manifest.json",
            *("public/data/v2/" + name for name in ev.PUBLIC),
            *(f"data_history/funnel/{date}/{rid}/" + name for name in ev.BUNDLE)}


def _required_paths(snapshot):
    paths = publication_paths(snapshot)
    pointer = snapshot["records"][POINTER].get("payload") or {}
    catalog = pointer.get("artifacts") or {}
    for name in OPTIONAL_ALIASES:
        # governance-mutation: WORKBENCH_SHARED_DECLARED_ALIAS_BYTES
        if "public:" + name not in catalog:
            paths.remove("public/data/v2/" + name)
    return paths


def _intrinsic_date(payload):
    if payload.get("target_trade_date") is not None:
        return payload["target_trade_date"]
    value = payload.get("as_of")
    return value if isinstance(value, str) and re.fullmatch(r"\d{8}", value) else None


def publication_provenance(snapshot, originals):
    records = snapshot["records"]
    result = {}
    catalog_binding = _bundle_catalog_binding(snapshot)
    bundle_manifest = f"data_history/funnel/{snapshot['target_trade_date']}/{snapshot['published_run_id']}/manifest.json"
    for name in originals:
        row = records[name]
        payload = row["payload"]
        run, date = payload.get("run_id"), _intrinsic_date(payload)
        result[name] = {
            "basis": "PUBLICATION_POINTER" if name == POINTER else
                     "HASH_BOUND_PUBLICATION_CONTEXT" if run is None or date is None else "INTRINSIC_AND_HASH_BOUND_PUBLICATION",
            "intrinsic_run_id": run, "intrinsic_trade_date": date,
            "intrinsic_run_status": "ABSENT" if run is None else "PRESENT",
            "intrinsic_date_status": "ABSENT" if date is None else "PRESENT",
            "publication_run_id": snapshot["published_run_id"], "publication_trade_date": snapshot["target_trade_date"],
            "source_sha256": row["source_sha256"], "pointer_sha256": records[POINTER]["source_sha256"],
            "manifest_sha256": records[f"public/data/v2/runs/{snapshot['published_run_id']}/manifest.json"]["source_sha256"],
        }
        if catalog_binding is not None and name == bundle_manifest:
            result[name].update(catalog_binding)
    return result


def validate_snapshot(snapshot, frozen_root, *, sealed_originals=False):
    """One boundary for imports, reopening and isolated rendering."""
    ev.verify(snapshot)
    frozen_root = Path(frozen_root)
    if any(p.is_symlink() for p in (frozen_root, *frozen_root.parents)):
        raise WorkspaceError("FROZEN_ROOT_SYMLINK", 409)
    paths = publication_paths(snapshot)
    records = snapshot.get("records")
    if not isinstance(records, dict) or set(records) != paths | {ATTEMPT}:
        raise WorkspaceError("FROZEN_WHITELIST_INVALID", 409)
    brief.render(snapshot)  # Existing date, credential, run and module guards.
    required = _required_paths(snapshot)
    catalog_binding = _bundle_catalog_binding(snapshot)
    bundle_manifest = f"data_history/funnel/{snapshot['target_trade_date']}/{snapshot['published_run_id']}/manifest.json"
    if sealed_originals:
        actual = {p.relative_to(frozen_root).as_posix() for p in frozen_root.rglob("*") if p.is_file() or p.is_symlink()}
        if actual != required | {"publication.json"}:
            raise WorkspaceError("FROZEN_ORIGINAL_INVENTORY_INVALID", 409)
    originals = {}
    for name in sorted(paths):
        row = records[name]
        payload = row.get("payload") or {}
        rid, date = snapshot["published_run_id"], snapshot["target_trade_date"]
        as_of = payload.get("as_of")
        # Absent intrinsic fields stay absent; present contradictions never inherit context.
        # governance-mutation: WORKBENCH_SHARED_CONTEXT_CONTRADICTION
        if ((payload.get("run_id") is not None and payload["run_id"] != rid)
                or (payload.get("target_trade_date") is not None and payload["target_trade_date"] != date)
                or (isinstance(as_of, str) and re.fullmatch(r"\d{8}", as_of) and as_of != date)):
            raise WorkspaceError("FROZEN_MODULE_IDENTITY_CONFLICT", 409)
        if name not in required:
            if ((sealed_originals or "frozen_input_hash" in snapshot)
                    and (row.get("status") not in {"OPTIONAL_UNBOUND", "OPTIONAL_MISSING_OR_INVALID"}
                         or row.get("payload") is not None or row.get("binding") not in {"UNBOUND", "UNVERIFIED"})):
                raise WorkspaceError("FROZEN_OPTIONAL_ALIAS_NOT_DEGRADED", 409)
            if (frozen_root / name).is_symlink() or row.get("binding") == "MISMATCH":
                raise WorkspaceError("FROZEN_OPTIONAL_ALIAS_UNSAFE_OR_CONFLICTING", 409)
            if row.get("status") not in {"OBSERVED", "MISSING_OR_INVALID", "OPTIONAL_UNBOUND", "OPTIONAL_MISSING_OR_INVALID"}:
                raise WorkspaceError("FROZEN_OPTIONAL_ALIAS_INVALID", 409)
            continue
        catalog_manifest = catalog_binding is not None and name == bundle_manifest
        if row.get("status") != "OBSERVED" or row.get("binding") != ("UNBOUND" if name == POINTER or catalog_manifest else "MATCH"):
            raise WorkspaceError("FROZEN_PUBLICATION_MISSING_OR_CONFLICTING", 409)
        try:
            raw = ev.read_local(Path(frozen_root), name)
        except OSError:
            raise WorkspaceError("FROZEN_ORIGINAL_UNAVAILABLE", 409) from None
        value = ev.parse(raw)
        brief.reject_credentials(value)
        if ev.sha(raw) != row.get("source_sha256") or value != row.get("payload"):
            raise WorkspaceError("FROZEN_ORIGINAL_CONFLICT", 409)
        originals[name] = raw
    rid, date = snapshot["published_run_id"], snapshot["target_trade_date"]
    pointer = records[POINTER]["payload"]
    manifest = records[f"public/data/v2/runs/{rid}/manifest.json"]["payload"]
    if (pointer.get("schema") != "nightly_current_run/v2" or pointer.get("run_id") != rid
            or pointer.get("target_trade_date") != date or pointer.get("manifest_path") != f"runs/{rid}/manifest.json"
            or manifest.get("schema") not in MANIFEST_SCHEMAS or manifest.get("run_id") != rid
            or manifest.get("target_trade_date") != date
            or not isinstance(pointer.get("manifest_sha256"), str)
            or pointer["manifest_sha256"].removeprefix("sha256:") != records[f"public/data/v2/runs/{rid}/manifest.json"]["source_sha256"]):
        raise WorkspaceError("FROZEN_PUBLICATION_BINDING_INVALID", 409)
    # The publisher copies the same artifact catalog into its manifest and pointer.
    if ((manifest["schema"] == "nightly_publish_manifest/v2" and not isinstance(manifest.get("artifacts"), dict))
            or ("artifacts" in manifest and manifest["artifacts"] != pointer.get("artifacts"))):
        raise WorkspaceError("FROZEN_MANIFEST_CATALOG_CONFLICT", 409)
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
            if prefix + name not in required:
                continue
            if catalog_binding is not None and prefix + name == bundle_manifest:
                continue
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
        if snapshot.get("publication_provenance") != publication_provenance(snapshot, originals):
            raise WorkspaceError("FROZEN_PUBLICATION_PROVENANCE_INVALID", 409)
        _publication, pub_hash, attempt_hash = fingerprints(snapshot, originals)
        if snapshot.get("frozen_input_hash") != ev.sealed({"publication_fingerprint": pub_hash, "attempt_fingerprint": attempt_hash}):
            raise WorkspaceError("FROZEN_CONTENT_IDENTITY_INVALID", 409)
    return originals


def fingerprints(snapshot, originals):
    publication = {"source_run_id": snapshot["published_run_id"], "source_trade_date": snapshot["target_trade_date"],
                   "files": {name: ev.sha(raw) for name, raw in originals.items()}}
    return publication, ev.sealed(publication), ev.sealed(snapshot["records"][ATTEMPT])


def _new_or_identical(path, raw, *, evidence_root=None):
    if len(raw) > ev.MAX_FILE:
        raise WorkspaceError("FROZEN_FILE_SIZE_LIMIT", 409)
    if path.exists() or path.is_symlink():
        if ev.read_local(path.parent, path.name) != raw:
            raise WorkspaceError("FROZEN_EXISTING_CONTENT_CONFLICT", 409)
    else:
        write_new(path, raw, evidence_root=evidence_root)


def verify_selection_events(events, verify):
    """Selection is authority only when its event binds registered reopened originals."""
    selected, reopened = None, {}
    for event in events:
        if event["kind"] != SELECTION_EVENT:
            continue
        try:
            binding = event["data"]
            snapshot_id = binding["snapshot_id"]
            if snapshot_id not in reopened:
                reopened[snapshot_id] = verify(snapshot_id)
            descriptor = FrozenInputs._descriptor(reopened[snapshot_id])
            if (binding != descriptor or event.get("actor") != SYNC_ACTOR
                    or event.get("production_authority") is not False
                    or event["request_hash"] != ev.sealed(descriptor)
                    or type(event["at"]) not in {int, float}):
                raise WorkspaceError("SYNC_SELECTION_BINDING_INVALID", 409)
            selected = {"binding": descriptor, "at": event["at"]}
        except (OSError, ValueError, KeyError, TypeError):
            raise WorkspaceError("SYNC_SELECTION_BINDING_INVALID", 409) from None
    return selected


class FrozenInputs:
    def __init__(self, store):
        if not store.shared_v1:
            raise WorkspaceError("SHARED_INPUT_STORE_REQUIRED", 403)
        self.store = store
        self.base = store.path.parent / "frozen-inputs"

    def current_selection(self):
        with self.store.connect() as db:
            events = Workspace.events(None, db)
        return verify_selection_events(events, self.verify)

    def select_current(self, snapshot_id, *, clock=time.time):
        descriptor = self._descriptor(self.verify(snapshot_id))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            events = Workspace.events(None, db)
            selected = verify_selection_events(events, self.verify)
            if selected is not None and selected["binding"] == descriptor:
                return selected
            # Reuse the existing append-only event and reserved-terminal capacity gate.
            event = Workspace.append(SimpleNamespace(store=self.store, clock=clock), db, events,
                                     "sync_select_" + uuid.uuid4().hex, ev.sealed(descriptor),
                                     SELECTION_EVENT, descriptor, actor=SYNC_ACTOR)
        return {"binding": descriptor, "at": event["at"]}

    def check_source_root(self, source_root):
        source_root = Path(source_root).absolute()
        state = self.store.path.parent.resolve()
        source = source_root.resolve()
        if source == state or source in state.parents or state in source.parents:
            raise WorkspaceError("FROZEN_SOURCE_STATE_OVERLAP", 409)
        if (any(p.is_symlink() for p in (source_root, *source_root.parents))
                or not source_root.is_dir()):
            raise WorkspaceError("READ_ONLY_SOURCE_ROOT_INVALID", 409)
        return source_root

    @staticmethod
    def _source_stamp(source_root):
        # Content equality alone cannot distinguish a pointer ABA replacement.
        rows = []
        for path in (source_root, source_root / POINTER):
            item = path.stat(follow_symlinks=False)
            if stat.S_ISLNK(item.st_mode): raise WorkspaceError("SOURCE_CHANGED", 409)
            rows.append((item.st_dev, item.st_ino, item.st_mtime_ns, item.st_ctime_ns))
        return rows

    @staticmethod
    def _history_fingerprints(snapshot):
        ev.verify(snapshot)
        files = {name: snapshot["records"][name]["source_sha256"] for name in _required_paths(snapshot)}
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in files.values()):
            raise WorkspaceError("FROZEN_CAPTURE_BINDING_CONFLICT", 409)
        publication = {"source_run_id": snapshot["published_run_id"], "source_trade_date": snapshot["target_trade_date"], "files": files}
        pub_hash, attempt_hash = ev.sealed(publication), ev.sealed(snapshot["records"][ATTEMPT])
        input_hash = ev.sealed({"publication_fingerprint": pub_hash, "attempt_fingerprint": attempt_hash})
        if snapshot.get("frozen_input_hash") != input_hash:
            raise WorkspaceError("FROZEN_CAPTURE_BINDING_CONFLICT", 409)
        return input_hash, pub_hash, attempt_hash

    def _capacity(self, db, input_hash, pub_hash, attempt_hash):
        registered = db.execute("SELECT snapshot_id, input_hash, body FROM shared_inputs").fetchall()
        history = {row[1] for row in registered}
        linked_publications, linked_attempts = {pub_hash}, {attempt_hash}
        def link(snapshot_id, expected_hash, snapshot):
            actual, publication, attempt = self._history_fingerprints(snapshot)
            if actual != expected_hash or snapshot_id != str(uuid.uuid5(uuid.NAMESPACE_URL, "ar.shared-input.v1:" + actual)):
                raise WorkspaceError("FROZEN_CAPTURE_BINDING_CONFLICT", 409)
            return actual, publication, attempt
        def envelope_binding(envelope, snapshot_id, expected_hash):
            actual, publication, attempt = link(snapshot_id, expected_hash, envelope["snapshot"])
            if (envelope.get("schema") != "ar.shared-input.v1" or envelope.get("snapshot_id") != snapshot_id
                    or envelope.get("input_hash") != actual or envelope.get("publication_fingerprint") != publication
                    or envelope.get("attempt_fingerprint") != attempt or envelope.get("validation_scope") != SCOPE):
                raise WorkspaceError("FROZEN_CAPTURE_BINDING_CONFLICT", 409)
            linked_publications.add(publication); linked_attempts.add(attempt)
            return actual
        for snapshot_id, expected_hash, body in registered:
            envelope_binding(ev.parse(body), snapshot_id, expected_hash)
        work = self.store.path.parent / "input-write-evidence"
        if work.exists():
            for path in work.iterdir():
                history.add(path.name)
                try:
                    capture = ev.parse(ev.read_local(path, "capture.json"))
                    if capture.get("schema") != "ar.shared-input-capture.v1" or capture.get("input_hash") != path.name:
                        continue
                    _actual, publication, attempt = link(capture["snapshot_id"], path.name, capture["snapshot"])
                    linked_publications.add(publication); linked_attempts.add(attempt)
                except (OSError, ValueError, KeyError, TypeError):
                    pass  # Unbound or partial evidence still spends its own history slot.
        envelopes = self.base / "envelopes"
        if envelopes.exists():
            for path in envelopes.iterdir():
                try:
                    envelope = ev.parse(ev.read_local(envelopes, path.name))
                    history.add(envelope_binding(envelope, path.stem, envelope["input_hash"]))
                except (OSError, ValueError, KeyError, TypeError):
                    history.add("orphan-envelope:" + path.name)
        # governance-mutation: WORKBENCH_SHARED_SYNC_ORPHAN_BUDGET
        for name, linked in (("publications", linked_publications), ("attempts", linked_attempts)):
            path = self.base / name
            if path.exists():
                for entry in path.iterdir():
                    identity = entry.name if name == "publications" else entry.name.removesuffix(".json")
                    if identity not in linked:
                        history.add(name + ":" + entry.name)
        from workbench_workspace import MAX_EVENTS
        events = db.execute("SELECT COUNT(*) FROM workspace_events").fetchone()[0]
        reserved = db.execute("SELECT COUNT(*) FROM shared_jobs WHERE json_extract(body, '$.terminal_event_reserved')=1").fetchone()[0]
        # Count uncommitted/staged/orphan directories as well as registry rows.
        # governance-mutation: WORKBENCH_SHARED_SYNC_CAPACITY
        if len(history | {input_hash}) > 100 or events + reserved >= MAX_EVENTS:
            raise WorkspaceError("FROZEN_INPUT_CAPACITY_BLOCKED", 429)

    def _check_sync_attempt(self, snapshot, source_root, expected_attempt_sha):
        # governance-mutation: WORKBENCH_SHARED_SYNC_EXPECTED_ATTEMPT
        if expected_attempt_sha is _UNSET_ATTEMPT:
            return
        if expected_attempt_sha is not None and (not isinstance(expected_attempt_sha, str)
                                                or not re.fullmatch(r"[0-9a-f]{64}", expected_attempt_sha)):
            raise WorkspaceError("SYNC_ATTEMPT_HASH_INVALID", 409)
        try:
            raw = ev.read_local(source_root, ATTEMPT)
            brief.reject_credentials(ev.parse(raw))
            actual = ev.sha(raw)
        except FileNotFoundError:
            actual = None
        if actual != expected_attempt_sha or snapshot["records"][ATTEMPT].get("source_sha256") != expected_attempt_sha:
            raise WorkspaceError("SOURCE_CHANGED", 409)

    def _recheck_source(self, snapshot, source_root, originals, stamp, *, expected_attempt_sha=_UNSET_ATTEMPT):
        # governance-mutation: WORKBENCH_SHARED_SYNC_FILE_BINDING
        try:
            reopened = validate_snapshot(snapshot, source_root)
            if reopened != originals:
                raise WorkspaceError("SOURCE_CHANGED", 409)
            expected_attempt = snapshot["records"][ATTEMPT].get("source_sha256")
            try:
                raw_attempt = ev.read_local(source_root, ATTEMPT)
                ev.parse(raw_attempt)
                actual_attempt = ev.sha(raw_attempt)
            except FileNotFoundError:
                actual_attempt = None
            if actual_attempt != expected_attempt:
                raise WorkspaceError("SOURCE_CHANGED", 409)
            self._check_sync_attempt(snapshot, source_root, expected_attempt_sha)
        except (OSError, ValueError, TypeError):
            raise WorkspaceError("SOURCE_CHANGED", 409) from None
        # governance-mutation: WORKBENCH_SHARED_SYNC_POST_POINTER
        if self._source_stamp(source_root) != stamp or ev.read_local(source_root, POINTER) != originals[POINTER]:
            raise WorkspaceError("SOURCE_CHANGED", 409)

    def import_once(self, source_root: Path, *, expected_attempt_sha=_UNSET_ATTEMPT) -> dict:
        source_root = self.check_source_root(source_root)
        stamp = self._source_stamp(source_root)
        snapshot = ev.capture(source_root)
        self._check_sync_attempt(snapshot, source_root, expected_attempt_sha)
        originals = validate_snapshot(snapshot, source_root)
        for name in publication_paths(snapshot) - _required_paths(snapshot):
            row = snapshot["records"][name]
            row.update(status="OPTIONAL_UNBOUND" if row["status"] == "OBSERVED" else "OPTIONAL_MISSING_OR_INVALID",
                       payload=None, degraded_reason="NOT_DECLARED_IN_PUBLICATION")
        snapshot["publication_provenance"] = publication_provenance(snapshot, originals)
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
                self._recheck_source(snapshot, source_root, originals, stamp, expected_attempt_sha=expected_attempt_sha)
                return self._descriptor(self.verify(prior[0]))
            self._capacity(db, input_hash, pub_hash, attempt_hash)
            work = self.store.path.parent / "input-write-evidence" / input_hash
            snapshot_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "ar.shared-input.v1:" + input_hash))
            capture_path = work / "capture.json"
            if capture_path.exists() or capture_path.is_symlink():
                capture = ev.parse(ev.read_local(work, "capture.json"))
                if (set(capture) != {"schema", "input_hash", "snapshot_id", "snapshot"}
                        or capture["schema"] != "ar.shared-input-capture.v1" or capture["input_hash"] != input_hash
                        or capture["snapshot_id"] != snapshot_id):
                    raise WorkspaceError("FROZEN_CAPTURE_BINDING_CONFLICT", 409)
                captured = capture["snapshot"]
                captured_originals = validate_snapshot(captured, source_root)
                _pub, captured_pub, captured_attempt = fingerprints(captured, captured_originals)
                if (captured_pub, captured_attempt) != (pub_hash, attempt_hash):
                    raise WorkspaceError("FROZEN_CAPTURE_BINDING_CONFLICT", 409)
                snapshot = captured
            else:
                capture = {"schema": "ar.shared-input-capture.v1", "input_hash": input_hash,
                           "snapshot_id": snapshot_id, "snapshot": snapshot}
                _new_or_identical(capture_path, ev.canonical(capture).encode(), evidence_root=work / "writes")
            publications = self.base / "publications"
            publications.mkdir(parents=True, exist_ok=True, mode=0o700)
            frozen_root = publications / pub_hash
            if not frozen_root.exists():
                with tempfile.TemporaryDirectory(prefix=".capture-", dir=publications) as temporary:
                    staging = Path(temporary) / "publication"
                    staging.mkdir(mode=0o700)
                    for name, raw in originals.items():
                        _new_or_identical(staging / name, raw, evidence_root=work / "writes")
                    _new_or_identical(staging / "publication.json", ev.canonical(publication).encode(), evidence_root=work / "writes")
                    validate_snapshot(snapshot, staging, sealed_originals=True)
                    os.rename(staging, frozen_root)
                    from workbench_backup import fsync_directory
                    fsync_directory(publications)
            _new_or_identical(frozen_root / "publication.json", ev.canonical(publication).encode(), evidence_root=work / "writes")
            validate_snapshot(snapshot, frozen_root, sealed_originals=True)
            attempt = snapshot["records"][ATTEMPT]
            _new_or_identical(self.base / "attempts" / (attempt_hash + ".json"), ev.canonical(attempt).encode(), evidence_root=work / "writes")
            envelope = {"schema": "ar.shared-input.v1", "snapshot_id": snapshot_id, "input_hash": input_hash,
                        "publication_fingerprint": pub_hash, "attempt_fingerprint": attempt_hash,
                        "source_run_id": snapshot["published_run_id"], "source_trade_date": snapshot["target_trade_date"],
                        "validation_scope": SCOPE, "snapshot": snapshot}
            _new_or_identical(self.base / "envelopes" / (snapshot_id + ".json"), ev.canonical(envelope).encode(), evidence_root=work / "writes")
            self._recheck_source(snapshot, source_root, originals, stamp, expected_attempt_sha=expected_attempt_sha)
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
