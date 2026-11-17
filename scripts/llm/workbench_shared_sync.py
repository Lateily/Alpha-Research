"""Default-off scoped file synchronizer. No producer, provider or human authority."""
from __future__ import annotations

import copy
import errno
import fcntl
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import workbench_evidence as ev
from workbench_snapshot_brief import SnapshotBriefError, reject_credentials
from workbench_shared_inputs import ATTEMPT, POINTER, FrozenInputs
from workbench_workspace import WorkspaceError

POLL_SECONDS = 60
_LOG = logging.getLogger(__name__)
_RUN_ID = re.compile(r"[0-9]{8}_[0-9]{6}_[0-9]{19}_[0-9a-f]{8}")
_SYNC_ERRORS = frozenset({
    "CREDENTIAL_SHAPED_CONTENT_REFUSED", "PUBLICATION_DATE_INVALID", "PUBLICATION_IDENTITY_REQUIRED",
    "SOURCE_CHANGED", "SOURCE_SHAPE_INVALID", "SOURCE_ATTEMPT_IDENTITY_INVALID", "READ_ONLY_SOURCE_ROOT_INVALID",
    "FROZEN_SOURCE_STATE_OVERLAP", "FROZEN_DIRECTORY_INVALID", "FROZEN_ORIGINAL_UNAVAILABLE",
    "FROZEN_ORIGINAL_CONFLICT", "FROZEN_PUBLICATION_BINDING_INVALID", "FROZEN_MANIFEST_CATALOG_CONFLICT",
    "FROZEN_BUNDLE_BINDING_INVALID", "FROZEN_CAPTURE_BINDING_CONFLICT", "FROZEN_EXISTING_CONTENT_CONFLICT",
    "FROZEN_FILE_SIZE_LIMIT", "FROZEN_INPUT_CAPACITY_BLOCKED", "FROZEN_REGISTRY_BINDING_INVALID",
    "FROZEN_SEAL_UNAVAILABLE_OR_INVALID", "FROZEN_SEAL_BINDING_INVALID", "FROZEN_SNAPSHOT_NOT_REGISTERED",
    "SYNC_SELECTION_BINDING_INVALID", "MARKET_PUBLICATION_REQUIRED", "WORKSPACE_EVENT_LIMIT",
    "FROZEN_SOURCE_HASH_MISMATCH", "FROZEN_MODULE_IDENTITY_MISMATCH", "SYNC_POLLER_ALREADY_RUNNING",
})
_DB_ERRORS = {getattr(sqlite3, code): code for code in
              ("SQLITE_BUSY", "SQLITE_LOCKED", "SQLITE_READONLY", "SQLITE_IOERR", "SQLITE_CORRUPT",
               "SQLITE_FULL", "SQLITE_CANTOPEN", "SQLITE_CONSTRAINT", "SQLITE_NOTADB") if hasattr(sqlite3, code)}
_IO_ERRORS = {errno.ENOENT: "IO_NOT_FOUND", errno.EACCES: "IO_PERMISSION", errno.EPERM: "IO_PERMISSION",
              errno.ENOSPC: "IO_NO_SPACE", errno.EROFS: "IO_READ_ONLY", errno.EIO: "IO_ERROR"}


def _diagnostic_code(exc):
    if isinstance(exc, WorkspaceError):
        code = exc.code
        return code if isinstance(code, str) and code in _SYNC_ERRORS else "WORKSPACE_ERROR_REDACTED"
    if isinstance(exc, (ev.EvidenceError, SnapshotBriefError)):
        code = exc.args[0] if len(exc.args) == 1 else None
        return code if isinstance(code, str) and code in _SYNC_ERRORS else "EVIDENCE_ERROR_REDACTED"
    if isinstance(exc, sqlite3.Error):
        number = getattr(exc, "sqlite_errorcode", None)
        return _DB_ERRORS.get(number & 0xff, "SQLITE_ERROR") if type(number) is int else "SQLITE_ERROR"
    if isinstance(exc, FileNotFoundError):
        return "IO_NOT_FOUND"
    if isinstance(exc, OSError):
        return _IO_ERRORS.get(exc.errno, "IO_ERROR")
    return "UNEXPECTED_ERROR"


def _log_run_id(value):
    return value if isinstance(value, str) and _RUN_ID.fullmatch(value) else None


def warn_sync_failure(exc, progress, *, code_sha=None, attempt_run_id=None):
    # Diagnostics are operator-only and must never mask the original result.
    try:
        _LOG.warning("%s", json.dumps({
            "event": "workbench_sync_failure.v1",
            "at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "code_sha": code_sha if isinstance(code_sha, str) and re.fullmatch(r"[0-9a-f]{40}", code_sha) else None,
            "stage": progress["stage"],
            "error_code": _diagnostic_code(exc),
            "latest_attempt_run_id": _log_run_id(attempt_run_id),
            "publication_run_id": _log_run_id(progress.get("publication_run_id")),
            "registry_outcome": progress.get("registry_outcome", "NOT_ATTEMPTED"),
        }, separators=(",", ":")))
    except Exception:
        pass


class ReadOnlySync:
    def __init__(self, inputs: FrozenInputs, source_root: Path, *,
                 clock: Callable[[], float] = time.time, stop_event: threading.Event | None = None,
                 code_sha: str | None = None):
        self.inputs = inputs
        self.source_root = inputs.check_source_root(source_root)
        self.clock = clock
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self._lock = threading.RLock()
        self._lifecycle = threading.Lock()
        self._thread = None
        self._lease = None
        self._fingerprint = None
        self._code_sha = code_sha
        self._state = {"status": "NOT_CHECKED", "last_checked_at": None, "last_successful_sync_at": None,
                       "current_snapshot_id": None, "source_run_id": None, "source_trade_date": None,
                       "safe_error": None, "latest_attempt": None, "actor": "SYSTEM_READ_ONLY_SYNC",
                       "missed_policy": "NO_BACKFILL", "production_authority": False, "human_review": "PENDING"}
        try:
            # governance-mutation: WORKBENCH_SHARED_SYNC_SELECTION_RESTORE
            selected = inputs.current_selection()
            if selected is not None:
                binding = selected["binding"]
                self._state.update(current_snapshot_id=binding["snapshot_id"], source_run_id=binding["source_run_id"],
                                   source_trade_date=binding["source_trade_date"], last_successful_sync_at=selected["at"])
        except (OSError, ValueError) as exc:
            self._state.update(status="SYNC_FAILED", safe_error="SYNC_SELECTION_BINDING_INVALID")
            warn_sync_failure(exc, {"stage": "RESTORE_SELECTION"}, code_sha=self._code_sha)

    def state(self):
        with self._lock: return copy.deepcopy(self._state)

    def tick(self) -> dict:
        progress = {"stage": "SOURCE_ROOT"}
        failure = None
        with self._lock:
            self._state["last_checked_at"] = self.clock()
            self._state["latest_attempt"] = None
            try:
                self.inputs.check_source_root(self.source_root)
                progress["stage"] = "READ_ATTEMPT"
                try:
                    attempt_raw = ev.read_local(self.source_root, ATTEMPT)
                    attempt = ev.parse(attempt_raw)
                    reject_credentials(attempt)
                    if (not isinstance(attempt.get("run_id"), str) or not re.fullmatch(ev.ID, attempt["run_id"])
                            or not isinstance(attempt.get("target_trade_date"), str)
                            or not re.fullmatch(r"\d{8}", attempt["target_trade_date"])
                            or (attempt.get("report") is not None and not isinstance(attempt["report"], str))
                            or (attempt.get("published") is not None and type(attempt["published"]) is not bool)):
                        raise WorkspaceError("SOURCE_ATTEMPT_IDENTITY_INVALID", 409)
                    # Use the existing safe display contract, not diagnostic text.
                    self._state["latest_attempt"] = {k: attempt.get(k) for k in ("run_id", "target_trade_date", "report", "published")}
                    attempt_hash = ev.sha(attempt_raw)
                except FileNotFoundError:
                    self._state["latest_attempt"] = None
                    attempt_hash = None
                progress["stage"] = "READ_POINTER"
                pointer = ev.read_local(self.source_root, POINTER)
                reject_credentials(ev.parse(pointer))
                fingerprint = (ev.sha(pointer), attempt_hash)
                if fingerprint == self._fingerprint and self._state["status"] == "SYNCED":
                    if self._state["current_snapshot_id"]:
                        progress.update(stage="VERIFY_CURRENT", registry_outcome="NOT_CONFIRMED",
                                        publication_run_id=self._state["source_run_id"])
                        self.inputs.verify(self._state["current_snapshot_id"])
                    return self.state()
                progress["stage"] = "IMPORT"
                descriptor = self.inputs.import_once(self.source_root, expected_attempt_sha=attempt_hash,
                                                     diagnostic=progress)
                progress["stage"] = "VERIFY_INPUT"
                envelope = self.inputs.verify(descriptor["snapshot_id"])
                progress["stage"] = "SELECT_CURRENT"
                # governance-mutation: WORKBENCH_SHARED_SYNC_SELECTION_COMMIT
                selected = self.inputs.select_current(descriptor["snapshot_id"], clock=self.clock)
                progress["stage"] = "UPDATE_PROJECTION"
                records = envelope["snapshot"]["records"]
                captured_attempt = records[ATTEMPT].get("payload")
                self._state["latest_attempt"] = ({k: captured_attempt.get(k) for k in ("run_id", "target_trade_date", "report", "published")}
                                                 if captured_attempt else None)
                self._fingerprint = (records[POINTER]["source_sha256"], records[ATTEMPT].get("source_sha256"))
                self._state.update(status="SYNCED", safe_error=None, last_successful_sync_at=selected["at"],
                                   **{k: descriptor[k] for k in ("source_run_id", "source_trade_date")},
                                   current_snapshot_id=descriptor["snapshot_id"])
            except Exception as exc:
                code = exc.code if isinstance(exc, WorkspaceError) else (
                    "SOURCE_SHAPE_INVALID" if isinstance(exc, ev.EvidenceError) and str(exc) == "SOURCE_SHAPE_INVALID"
                    else "SOURCE_UNAVAILABLE_OR_INVALID")
                self._state.update(status="CAPACITY_BLOCKED" if "CAPACITY" in code or code == "WORKSPACE_EVENT_LIMIT" else "SYNC_FAILED",
                                   safe_error=code)
                failure = exc
            result = self.state()
        if failure is not None:
            warn_sync_failure(failure, progress, code_sha=self._code_sha,
                              attempt_run_id=(result["latest_attempt"] or {}).get("run_id"))
        return result

    def start(self) -> None:
        with self._lifecycle:
            if self._thread is not None:
                raise WorkspaceError("SYNC_POLLER_ALREADY_RUNNING", 409)
            path = self.inputs.store.path.parent / "read-only-sync.lock"
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            lease = os.fdopen(fd, "rb+")
            try:
                fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                lease.close()
                raise WorkspaceError("SYNC_POLLER_ALREADY_RUNNING", 409) from None
            self._lease = lease
            try:
                self.tick()
                self._thread = threading.Thread(target=self._poll, name="read-only-shared-sync", daemon=True)
                self._thread.start()
            except BaseException:
                self._lease.close(); self._lease = None
                self._thread = None
                raise

    def _poll(self):
        while not self.stop_event.is_set():
            deadline = time.monotonic() + POLL_SECONDS
            while True:
                remaining = max(0, deadline - time.monotonic())
                if self.stop_event.wait(remaining): return
                if time.monotonic() >= deadline: break
            # governance-mutation: WORKBENCH_SHARED_SYNC_WORKER_BOUNDARY
            try:
                self.tick()
            except Exception:
                with self._lock:
                    self._state.update(status="SYNC_FAILED", safe_error="SYNC_WORKER_FAILURE")
                warn_sync_failure(sys.exc_info()[1], {"stage": "WORKER"}, code_sha=self._code_sha)

    def stop(self) -> None:
        with self._lifecycle:
            if self._thread is None: return
            self.stop_event.set()
            self._thread.join()
            self._thread = None
            self._lease.close(); self._lease = None
