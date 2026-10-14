"""Default-off scoped file synchronizer. No producer, provider or human authority."""
from __future__ import annotations

import copy
import fcntl
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable

import workbench_evidence as ev
from workbench_snapshot_brief import reject_credentials
from workbench_shared_inputs import ATTEMPT, POINTER, FrozenInputs
from workbench_workspace import WorkspaceError

POLL_SECONDS = 60


class ReadOnlySync:
    def __init__(self, inputs: FrozenInputs, source_root: Path, *,
                 clock: Callable[[], float] = time.time, stop_event: threading.Event | None = None):
        self.inputs = inputs
        self.source_root = inputs.check_source_root(source_root)
        self.clock = clock
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self._lock = threading.RLock()
        self._lifecycle = threading.Lock()
        self._thread = None
        self._lease = None
        self._fingerprint = None
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
        except (OSError, ValueError):
            self._state.update(status="SYNC_FAILED", safe_error="SYNC_SELECTION_BINDING_INVALID")

    def state(self):
        with self._lock: return copy.deepcopy(self._state)

    def tick(self) -> dict:
        with self._lock:
            self._state["last_checked_at"] = self.clock()
            self._state["latest_attempt"] = None
            try:
                self.inputs.check_source_root(self.source_root)
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
                pointer = ev.read_local(self.source_root, POINTER)
                reject_credentials(ev.parse(pointer))
                fingerprint = (ev.sha(pointer), attempt_hash)
                if fingerprint == self._fingerprint and self._state["status"] == "SYNCED":
                    if self._state["current_snapshot_id"]:
                        self.inputs.verify(self._state["current_snapshot_id"])
                    return self.state()
                descriptor = self.inputs.import_once(self.source_root, expected_attempt_sha=attempt_hash)
                envelope = self.inputs.verify(descriptor["snapshot_id"])
                # governance-mutation: WORKBENCH_SHARED_SYNC_SELECTION_COMMIT
                selected = self.inputs.select_current(descriptor["snapshot_id"], clock=self.clock)
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
            return self.state()

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

    def stop(self) -> None:
        with self._lifecycle:
            if self._thread is None: return
            self.stop_event.set()
            self._thread.join()
            self._thread = None
            self._lease.close(); self._lease = None
