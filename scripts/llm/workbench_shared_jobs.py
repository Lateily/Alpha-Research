"""Single-coordinator persistent FIFO queue, token fencing and sealed recovery."""
from __future__ import annotations

import json
import secrets
import uuid
from pathlib import Path

import workbench_evidence as ev
import workbench_shared_workspace as shared_module
from workbench_shared_inputs import FrozenInputs
from workbench_shared_worker import BINDING_FIELDS, KINDS, verify_seal
from workbench_workspace import WorkspaceError, exact, identifier

JOB_SCHEMA = "ar.shared-job.v1"
ACTIVE = {"QUEUED", "RUNNING"}
TERMINAL = {"SUCCEEDED", "STOP", "INTERRUPTED", "RECOVERY_REQUIRED"}


def _request(payload, actor, workspace_id):
    return ev.sealed({"actor": actor, "workspace_id": workspace_id, **payload})


def _output_root(root, job, attempt):
    for value in (job["workspace_id"], job["job_id"], attempt["attempt_id"]):
        if str(uuid.UUID(value)) != value: raise WorkspaceError("SHARED_JOB_PATH_INVALID", 409)
    return Path(root) / "shared-jobs" / job["workspace_id"] / job["job_id"] / "attempts" / attempt["attempt_id"]


def _accepted(events, job_id):
    if isinstance(events, dict): return events.get(job_id)
    return next((event for event in events if event["kind"] == "SHARED_JOB_QUEUED" and event["data"].get("job_id") == job_id), None)


def _check_job(job, row, events, identities):
    accepted = _accepted(events, row[0])
    if (job.get("job_id") != row[0] or job.get("command_id") != row[1] or job.get("job_schema") != JOB_SCHEMA
            or job.get("schema_version") != shared_module.SCHEMA or job.get("input_schema") != "ar.shared-input.v1"
            or job.get("kind") not in KINDS or job.get("status") not in ACTIVE | TERMINAL
            or identities.get(job.get("actor")) != job.get("workspace_id") or accepted is None):
        raise WorkspaceError("SHARED_JOB_BINDING_INVALID", 409)
    payload = {key: job[key] for key in ("command_id", "kind", "snapshot_id")}
    if (row[2] != _request(payload, job["actor"], job["workspace_id"])
            or accepted["request_hash"] != row[2] or accepted.get("actor") != job["actor"]
            or any(accepted["data"].get(key) != job.get(key) for key in (*BINDING_FIELDS, "command_id", "submitted_at"))):
        raise WorkspaceError("SHARED_JOB_BINDING_INVALID", 409)


def verify_queue_state(root: Path, tables: dict) -> None:
    """The backup verifier uses the same binding and reopened-seal boundary."""
    events = [ev.parse(row[3]) for row in tables["workspace_events"]]
    identities = dict(tables["shared_workspaces"])
    inputs = {row[0]: row[1:] for row in tables["shared_inputs"]}
    registered = {row[0]: row for row in tables["shared_jobs"]}
    attempts = {}
    for attempt_id, job_id, raw in tables["shared_attempts"]:
        attempt = ev.parse(raw)
        if (job_id not in registered or attempt.get("attempt_id") != attempt_id or attempt.get("job_id") != job_id
                or attempt.get("status") not in {"RUNNING", "ABANDONED", *TERMINAL}
                or not isinstance(attempt.get("token_hash"), str) or len(attempt["token_hash"]) != 64):
            raise WorkspaceError("SHARED_ATTEMPT_BINDING_INVALID", 409)
        attempts.setdefault(job_id, []).append(attempt)
    for job_id, row in registered.items():
        job = ev.parse(row[3]); _check_job(job, row, events, identities)
        owned = attempts.get(job_id, [])
        if len(owned) > 2 or job["attempt_count"] != len(owned):
            raise WorkspaceError("SHARED_ATTEMPT_COUNT_INVALID", 409)
        for number, attempt in enumerate(owned, 1):
            if attempt.get("number") != number or attempt.get("binding") != {key: job[key] for key in BINDING_FIELDS}:
                raise WorkspaceError("SHARED_ATTEMPT_BINDING_INVALID", 409)
        terminal = [e for e in events if e["kind"] == "SHARED_JOB_TERMINAL" and e["data"].get("job_id") == job_id]
        if (len(terminal) != (0 if job["status"] in ACTIVE else 1)
                or job.get("terminal_event_reserved") != (job["status"] in ACTIVE)):
            raise WorkspaceError("SHARED_TERMINAL_BINDING_INVALID", 409)
        envelope = FrozenInputs.verify_registered(Path(root) / "frozen-inputs", job["snapshot_id"], inputs[job["snapshot_id"]])
        if envelope["input_hash"] != job["input_hash"]:
            raise WorkspaceError("SHARED_JOB_INPUT_INVALID", 409)
        if job.get("attempt_id"):
            current = next((a for a in owned if a["attempt_id"] == job["attempt_id"]), None)
            if current is None: raise WorkspaceError("SHARED_ATTEMPT_BINDING_INVALID", 409)
        elif job["status"] == "RUNNING" or job["status"] == "SUCCEEDED":
            raise WorkspaceError("SHARED_ATTEMPT_BINDING_INVALID", 409)
        if terminal:
            if terminal[0]["data"] != {"job_id": job_id, "attempt_id": job["attempt_id"],
                                       "status": job["status"], "result": job["result"]}:
                raise WorkspaceError("SHARED_TERMINAL_BINDING_INVALID", 409)
        if job["status"] == "SUCCEEDED":
            result = verify_seal(_output_root(root, job, current), job, current, envelope)
            if result != job["result"] or job["output_hash"] != result["output_hash"] or current["status"] != "SUCCEEDED":
                raise WorkspaceError("SHARED_TERMINAL_SEAL_INVALID", 409)


class SharedJobQueue:
    def __init__(self, shared, inputs: FrozenInputs, code_sha: str):
        self.shared, self.inputs, self.store = shared, inputs, shared.store
        if inputs.store.path != self.store.path or code_sha != shared._execution_identity["code_sha"]:
            raise WorkspaceError("SHARED_QUEUE_CONSTRUCTION_INVALID", 409)
        self.code_sha = code_sha
        self.shared.queue = self

    def _rows(self, db):
        return db.execute("SELECT job_id, command_id, request_hash, body FROM shared_jobs ORDER BY rowid").fetchall()

    def _load(self, db, job_id):
        row = db.execute("SELECT job_id, command_id, request_hash, body FROM shared_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None: raise WorkspaceError("SHARED_JOB_NOT_FOUND", 404)
        return row, ev.parse(row[3])

    def _update(self, db, job):
        db.execute("UPDATE shared_jobs SET body=? WHERE job_id=?", (ev.canonical(job), job["job_id"]))

    def _attempts(self, db, job_id):
        return [ev.parse(row[0]) for row in db.execute("SELECT body FROM shared_attempts WHERE job_id=? ORDER BY rowid", (job_id,))]

    def _compatible(self, db, row, job):
        _check_job(job, row, self.shared.system.events(db), dict(db.execute("SELECT login, workspace_id FROM shared_workspaces")))
        code = shared_module.execution_identity(shared_module.CODE_ROOT)
        if any(job[key] != code[key] or code[key] != self.shared._execution_identity[key] for key in ("code_sha", "source_tree_hash")):
            raise WorkspaceError("SHARED_RECOVERY_CODE_CHANGED", 409)
        envelope = self.inputs.verify(job["snapshot_id"])
        if envelope["input_hash"] != job["input_hash"] or envelope["schema"] != job["input_schema"]:
            raise WorkspaceError("SHARED_RECOVERY_INPUT_CHANGED", 409)
        return envelope

    def enqueue(self, payload: dict, actor: str) -> dict:
        exact(payload, {"command_id", "kind", "snapshot_id"}); identifier(payload["command_id"])
        if payload["kind"] not in KINDS: raise WorkspaceError("PRIVATE_OPERATION_DISABLED", 403)
        owner = self.shared.identity(actor)
        request_hash = _request(payload, actor, owner["workspace_id"])
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT job_id, request_hash FROM shared_jobs WHERE command_id=?", (payload["command_id"],)).fetchone()
            if prior:
                if prior[1] != request_hash: raise WorkspaceError("WORKSPACE_COMMAND_ID_CONFLICT", 409)
                _, original = self._load(db, prior[0])
                return {"job_id": prior[0], "status": self._view(original)["status"], "disposition": "IDEMPOTENT"}
            events = self.shared.system.events(db)
            if any(event["command_id"] == payload["command_id"] for event in events):
                raise WorkspaceError("WORKSPACE_COMMAND_ID_CONFLICT", 409)
            code = shared_module.execution_identity(shared_module.CODE_ROOT)
            if code != self.shared._execution_identity:
                raise WorkspaceError("EXECUTION_CODE_CHANGED_RESTART_REQUIRED", 409)
            envelope = self.inputs.verify(payload["snapshot_id"])
            active = [ev.parse(row[3]) for row in self._rows(db) if ev.parse(row[3])["status"] in ACTIVE]
            # governance-mutation: WORKBENCH_SHARED_QUEUE_LIMITS
            if len(active) >= 20 or sum(job["actor"] == actor for job in active) >= 2:
                raise WorkspaceError("SHARED_QUEUE_LIMIT", 429)
            import workbench_workspace as ws
            if len(events) + len(active) + 2 > ws.MAX_EVENTS:
                raise WorkspaceError("WORKSPACE_EVENT_LIMIT", 429)
            if payload["kind"] == "observe": self._observation_capacity(db, envelope)
            job = {**payload, **code, **FrozenInputs._descriptor(envelope), "job_id": str(uuid.uuid4()),
                   "actor": actor, "workspace_id": owner["workspace_id"], "submitted_at": self.shared.system.clock(),
                   "schema_version": shared_module.SCHEMA, "job_schema": JOB_SCHEMA, "input_schema": envelope["schema"],
                   "status": "QUEUED", "attempt_count": 0, "attempt_id": None, "token_hash": None,
                   "result": None, "output_hash": None, "terminal_event_reserved": True}
            db.execute("INSERT INTO shared_jobs VALUES (?, ?, ?, ?)", (job["job_id"], payload["command_id"], request_hash, ev.canonical(job)))
            self.shared.system.append(db, events, payload["command_id"], request_hash, "SHARED_JOB_QUEUED",
                                      {key: job[key] for key in (*BINDING_FIELDS, "command_id", "submitted_at")}, actor=actor)
        return {"job_id": job["job_id"], "status": "QUEUED", "disposition": "CREATED"}

    def _observation_capacity(self, db, envelope):
        existing = {row[0] for row in db.execute("SELECT snapshot_hash FROM workspace_observations")}
        reserved = {self.inputs.verify(job["snapshot_id"])["snapshot"]["snapshot_hash"]
                    for row in self._rows(db) for job in [ev.parse(row[3])] if job["status"] in ACTIVE and job["kind"] == "observe"}
        if len(existing | reserved | {envelope["snapshot"]["snapshot_hash"]}) > 100:
            raise WorkspaceError("OBSERVATION_LIMIT", 429)

    def _claim_view(self, job, attempt, token, envelope):
        return {**{key: job[key] for key in BINDING_FIELDS}, "attempt_id": attempt["attempt_id"], "token": token,
                "frozen_root": envelope["frozen_root"], "output_root": _output_root(self.store.path.parent, job, attempt),
                "code_root": shared_module.CODE_ROOT, "envelope": envelope}

    def claim(self) -> dict | None:
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = self._rows(db)
            if sum(ev.parse(row[3])["status"] == "RUNNING" for row in rows) >= 2: return None
            for row in rows:
                job = ev.parse(row[3])
                # governance-mutation: WORKBENCH_SHARED_ATOMIC_CLAIM
                if job["status"] != "QUEUED": continue
                try: envelope = self._compatible(db, row, job)
                except (OSError, ValueError, KeyError, TypeError):
                    self._terminal(db, row, job, "RECOVERY_REQUIRED", {"error": "RECOVERY_BINDING_INVALID"}); continue
                if job["attempt_count"] >= 2:
                    self._terminal(db, row, job, "INTERRUPTED", {"error": "RECOVERY_ATTEMPT_LIMIT"}); continue
                token = secrets.token_hex(32)
                attempt = {"attempt_id": str(uuid.uuid4()), "job_id": job["job_id"], "number": job["attempt_count"] + 1,
                           "token_hash": ev.sha(token.encode()), "status": "RUNNING", "binding": {key: job[key] for key in BINDING_FIELDS}}
                db.execute("INSERT INTO shared_attempts VALUES (?, ?, ?)", (attempt["attempt_id"], job["job_id"], ev.canonical(attempt)))
                job.update(status="RUNNING", attempt_count=attempt["number"], attempt_id=attempt["attempt_id"], token_hash=attempt["token_hash"])
                self._update(db, job)
                return self._claim_view(job, attempt, token, envelope)
        return None

    def _terminal(self, db, row, job, status, result):
        accepted = _accepted(self.shared.system.events(db), row[0])
        # A corrupt technical projection cannot reassign the immutable acceptance.
        if accepted and accepted["command_id"] == row[1] and accepted["request_hash"] == row[2]:
            job.update(accepted["data"])
        job.update(job_id=row[0], command_id=row[1])
        job.update(status=status, result=result, output_hash=result.get("output_hash"), terminal_event_reserved=False, token_hash=None)
        self._update(db, job)
        if job["attempt_id"]:
            attempt = next((a for a in self._attempts(db, job["job_id"]) if a["attempt_id"] == job["attempt_id"]), None)
            if attempt is not None:
                attempt["status"] = status
                db.execute("UPDATE shared_attempts SET body=? WHERE attempt_id=?", (ev.canonical(attempt), attempt["attempt_id"]))
        self.shared.system.append(db, self.shared.system.events(db), "shared_finish_" + job["job_id"], row[2],
                                  "SHARED_JOB_TERMINAL", {"job_id": job["job_id"], "attempt_id": job["attempt_id"], "status": status, "result": result}, actor=job["actor"])
        return {"job_id": job["job_id"], "status": status, "result": result}

    def finish(self, claim: dict, result: dict) -> dict:
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row, job = self._load(db, claim["job_id"])
            # governance-mutation: WORKBENCH_SHARED_TOKEN_FENCE
            if job["status"] != "RUNNING" or job["attempt_id"] != claim["attempt_id"] or job["token_hash"] != ev.sha(claim["token"].encode()):
                raise WorkspaceError("SHARED_ATTEMPT_TOKEN_STALE", 409)
            try:
                envelope = self._compatible(db, row, job)
                attempt = next(a for a in self._attempts(db, job["job_id"]) if a["attempt_id"] == job["attempt_id"])
                output = _output_root(self.store.path.parent, job, attempt)
                sealed = (output / "seal.json").exists() or (output / "seal.json").is_symlink()
                if result.get("status") == "SUCCEEDED" or sealed:
                    result = verify_seal(output, job, attempt, envelope, publish=True)
                    if job["kind"] == "observe":
                        self._observation_capacity(db, envelope)
                        snapshot = envelope["snapshot"]
                        db.execute("INSERT OR IGNORE INTO workspace_observations VALUES (?, ?)", (snapshot["snapshot_hash"], ev.canonical(snapshot)))
                else:
                    code = result.get("error")
                    result = {"error": code if code in {"WORKER_TIMEOUT", "WORKER_RENDER_FAILED", "WORKER_START_FAILED", "WORKER_OUTPUT_INVALID"} else "WORKER_RENDER_FAILED"}
            except (OSError, ValueError, KeyError, TypeError, StopIteration):
                return self._terminal(db, row, job, "RECOVERY_REQUIRED", {"error": "RECOVERY_BINDING_INVALID"})
            return self._terminal(db, row, job, "SUCCEEDED" if result.get("status") == "SUCCEEDED" else "STOP", result)

    def recover(self) -> dict:
        report = {key: [] for key in ("converged", "rescheduled", "interrupted", "recovery_required")}
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in self._rows(db):
                job = ev.parse(row[3])
                if job["status"] not in ACTIVE:
                    if job["status"] == "SUCCEEDED" and self._view(job)["status"] == "RECOVERY_REQUIRED": report["recovery_required"].append(job["job_id"])
                    continue
                try:
                    envelope = self._compatible(db, row, job)
                    attempts = self._attempts(db, job["job_id"])
                    if len(attempts) != job["attempt_count"]: raise ValueError
                    if job["status"] == "QUEUED": continue
                    attempt = next(a for a in attempts if a["attempt_id"] == job["attempt_id"])
                    output = _output_root(self.store.path.parent, job, attempt)
                    if (output / "seal.json").exists() or (output / "seal.json").is_symlink():
                        result = verify_seal(output, job, attempt, envelope, publish=True)
                        self._terminal(db, row, job, "SUCCEEDED", result)
                        report["converged"].append(job["job_id"]); continue
                    if (output / "result").exists() or (output / "result").is_symlink():
                        raise WorkspaceError("SHARED_PUBLISHED_SEAL_MISSING", 409)
                    # governance-mutation: WORKBENCH_SHARED_RECOVERY_ATTEMPT_CAP
                    if job["attempt_count"] >= 2:
                        self._terminal(db, row, job, "INTERRUPTED", {"error": "RECOVERY_ATTEMPT_LIMIT"})
                        report["interrupted"].append(job["job_id"]); continue
                    attempt["status"] = "ABANDONED"
                    db.execute("UPDATE shared_attempts SET body=? WHERE attempt_id=?", (ev.canonical(attempt), attempt["attempt_id"]))
                    job.update(status="QUEUED", attempt_id=None, token_hash=None)
                    self._update(db, job); report["rescheduled"].append(job["job_id"])
                except (OSError, ValueError, KeyError, TypeError):
                    self._terminal(db, row, job, "RECOVERY_REQUIRED", {"error": "RECOVERY_BINDING_INVALID"})
                    report["recovery_required"].append(job["job_id"])
            for job in self.shared._legacy_jobs():
                if job.get("recovery") == "LEGACY_NOT_RECOVERABLE" or job["status"] == "INTERRUPTED":
                    report["interrupted"].append(job["job_id"])
        return report

    def _view(self, job, *, context=None):
        job = dict(job)
        accepted = None
        try:
            if context is None:
                with self.store.connect() as db:
                    row, _ = self._load(db, job["job_id"])
                    events = self.shared.system.events(db)
                    identities = dict(db.execute("SELECT login, workspace_id FROM shared_workspaces"))
            else:
                row, events, identities = context
            accepted = _accepted(events, row[0])
            _check_job(job, row, events, identities)
        except (OSError, ValueError, KeyError, TypeError):
            if accepted: job.update(accepted["data"])
            job.update(status="RECOVERY_REQUIRED", result={"error": "SHARED_JOB_BINDING_INVALID"})
            return job
        if job["status"] == "SUCCEEDED":
            try:
                envelope = self.inputs.verify(job["snapshot_id"])
                with self.store.connect() as db:
                    attempt = next(a for a in self._attempts(db, job["job_id"]) if a["attempt_id"] == job["attempt_id"])
                if attempt["binding"] != {key: job[key] for key in BINDING_FIELDS} or attempt["status"] != "SUCCEEDED":
                    raise WorkspaceError("SHARED_ATTEMPT_BINDING_INVALID", 409)
                terminals = [e for e in events if e["kind"] == "SHARED_JOB_TERMINAL" and e["data"].get("job_id") == job["job_id"]]
                if len(terminals) != 1 or terminals[0]["data"] != {"job_id": job["job_id"], "attempt_id": job["attempt_id"], "status": "SUCCEEDED", "result": job["result"]}:
                    raise WorkspaceError("SHARED_TERMINAL_BINDING_INVALID", 409)
                if verify_seal(_output_root(self.store.path.parent, job, attempt), job, attempt, envelope) != job["result"]:
                    raise ValueError
            except (OSError, ValueError, KeyError, TypeError, StopIteration):
                job.update(status="RECOVERY_REQUIRED", result={"error": "SHARED_OUTPUT_INTEGRITY_ERROR"})
        return job

    def jobs(self):
        with self.store.connect() as db:
            rows = self._rows(db)
            events = self.shared.system.events(db)
            accepted = {event["data"]["job_id"]: event for event in events if event["kind"] == "SHARED_JOB_QUEUED"}
            identities = dict(db.execute("SELECT login, workspace_id FROM shared_workspaces"))
        result = []
        for row in rows:
            job = ev.parse(row[3])
            try: _check_job(job, row, accepted, identities)
            except (ValueError, KeyError, TypeError):
                if row[0] in accepted: job.update(accepted[row[0]]["data"])
                job.update(status="RECOVERY_REQUIRED", job_schema=JOB_SCHEMA, result={"error": "SHARED_JOB_BINDING_INVALID"})
            result.append(job)
        return result

    def views(self, selected):
        with self.store.connect() as db:
            events = self.shared.system.events(db)
            identities = dict(db.execute("SELECT login, workspace_id FROM shared_workspaces"))
            contexts = [(self._load(db, job["job_id"])[0], events, identities) for job in selected]
        return [self._view(job, context=context) for job, context in zip(selected, contexts)]

    def job(self, job_id):
        identifier(job_id)
        with self.store.connect() as db: _, job = self._load(db, job_id)
        job = self._view(job)
        detail = {**self.shared._metadata(job), "result": job["result"], "snapshot_id": job["snapshot_id"]}
        if job["status"] == "SUCCEEDED" and job["kind"] == "snapshot-brief":
            output = _output_root(self.store.path.parent, job, {"attempt_id": job["attempt_id"]}) / "result"
            try:
                seal = ev.parse(ev.read_local(output.parent, "seal.json"))
                report = ev.read_local(output, "report.md")
                citations = ev.read_local(output, "citations.json")
                if (seal["seal_hash"] != job["result"]["seal_hash"]
                        or seal["seal_hash"] != ev.sealed({k: v for k, v in seal.items() if k != "seal_hash"})
                        or ev.sha(report) != job["output_hash"] or ev.sha(report) != seal["files"]["report.md"]
                        or ev.sha(citations) != seal["files"]["citations.json"]):
                    raise WorkspaceError("SHARED_REPORT_CHANGED", 409)
                detail.update(report=report.decode(), citations=json.loads(citations))
            except (OSError, ValueError, KeyError, TypeError):
                detail.update(status="RECOVERY_REQUIRED", error="SHARED_OUTPUT_INTEGRITY_ERROR",
                              result={"error": "SHARED_OUTPUT_INTEGRITY_ERROR"})
        return detail
