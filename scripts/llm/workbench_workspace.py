"""Local workspace command service. Review records never grant production rights.

The event log has transactional application-level append-only guards and a hash
chain, not tamper-proof storage against a machine administrator. Owner credentials
identify the local account only; they do not authenticate Junyan's legal identity.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import re
import secrets
import sqlite3
import sys
import threading
import time
from pathlib import Path

import workbench_evidence as evidence

KINDS = {"observe", "integrity", "research-replay", "backup"}
DOCUMENT_FIELDS = {"title", "ticker", "thesis", "valuation", "timing", "invalidation", "evidence_ref"}
REVIEW_OUTCOMES = {"ACCEPTED_LOCAL", "CHANGES_REQUESTED", "REJECTED_LOCAL"}
MAX_EVENTS = 10000
PBKDF_ROUNDS = 600000
CODE_ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    ("Nightly", "experiments/execution_tracker/run_nightly.py", "OBSERVE_ONLY"),
    ("Macro M1-C", "experiments/macro_os/m1c.py", "OBSERVE_ONLY_CALIBRATING"),
    ("U1-U4", "experiments/research_funnel/funnel_pipeline.py", "FIXED_OFFLINE_REPLAY"),
    ("Research cycle", "experiments/research_funnel/research_cycle.py", "FIXED_OFFLINE_REPLAY"),
    ("Paper execution", "experiments/execution_tracker/model_paper_fund.py", "FIXED_OFFLINE_REPLAY"),
    ("Five-axis attribution", "experiments/research_funnel/five_axis_attribution.py", "FIXED_OFFLINE_REPLAY"),
    ("Knowledge cards", "experiments/research_funnel/knowledge_cards.py", "READ_ONLY_CATALOG"),
    ("DeepSeek", "scripts/llm/adapters/deepseek.py", "OFFLINE_STUB_ONLY"),
)


def method_catalog():
    modules = []
    for name, path, mode in MODULES:
        try:
            checksum = evidence.sha(evidence.read_local(CODE_ROOT, path))
        except (OSError, ValueError):
            checksum = None
        modules.append({"name": name, "path": path, "mode": mode, "source_sha256": checksum, "status": "SOURCE_PRESENT" if checksum else "MISSING"})
    try:
        module_root = str(CODE_ROOT / "experiments/research_funnel")
        if module_root not in sys.path:
            sys.path.insert(0, module_root)
        spec = importlib.util.spec_from_file_location("workbench_knowledge_catalog", CODE_ROOT / "experiments/research_funnel/knowledge_cards.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        path = CODE_ROOT / "data/knowledge_cards/semiconductor_materials.json"
        cards = module.load_cards(path)
        methods = {"status": "SCHEMA_VALID_NOT_METHOD_VALIDATED", "source_sha256": evidence.sha(path.read_bytes()),
                   "cards": [{**card, "collection_coverage": module.source_coverage(card)} for card in cards]}
    except (OSError, ValueError, ImportError):
        methods = {"status": "DATA_BLOCKED", "cards": []}
    return {"modules": modules, "methods": methods, "formal_claim_allowed": False}


class WorkspaceError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


def exact(payload, keys):
    if not isinstance(payload, dict) or set(payload) != set(keys):
        raise WorkspaceError("WORKSPACE_FIELDS_INVALID")


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{8,100}", value):
        raise WorkspaceError("WORKSPACE_ID_INVALID")


def text_field(value, maximum=12000, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise WorkspaceError("WORKSPACE_TEXT_REQUIRED")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise WorkspaceError("WORKSPACE_TEXT_INVALID")


def derive(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF_ROUNDS).hex()


def projection(events):
    documents, schedules, jobs = {}, {}, {}
    for event in events:
        item, kind = event["data"], event["kind"]
        if kind == "DRAFT_SAVED":
            documents[item["document_id"]] = {**item, "status": "DRAFT", "review": None}
        elif kind == "SUBMITTED":
            documents[item["document_id"]]["status"] = "IN_REVIEW"
        elif kind == "REVIEWED":
            documents[item["document_id"]].update(status=item["outcome"], review=item)
        elif kind == "SCHEDULE_SET":
            schedules[item["schedule_id"]] = item
        elif kind == "JOB_STARTED":
            jobs[item["job_id"]] = {**item, "status": "STARTED", "result": None}
        elif kind == "JOB_FINISHED":
            jobs[item["job_id"]].update(status=item["status"], result=item["result"])
    return {"documents": list(documents.values()), "schedules": list(schedules.values()), "jobs": list(jobs.values())}


class Workspace:
    def __init__(self, store, source_root=None, clock=time.time):
        self.store, self.clock = store, clock
        self.source_root = Path(source_root) if source_root else None
        if self.source_root and (self.source_root.is_symlink() or not self.source_root.is_dir()):
            raise WorkspaceError("READ_ONLY_SOURCE_ROOT_INVALID")
        if self.source_root and self.source_root.resolve() in store.path.resolve().parents:
            raise WorkspaceError("STATE_MUST_BE_OUTSIDE_READ_ONLY_SOURCE")
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.owner_failures = []
        self.catalog = method_catalog()
        with store.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS workspace_events (seq INTEGER PRIMARY KEY, command_id TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL, body TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS workspace_observations (snapshot_hash TEXT PRIMARY KEY, body TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS workspace_owner (singleton INTEGER PRIMARY KEY CHECK(singleton=1), salt TEXT NOT NULL, password_hash TEXT NOT NULL)")
            for table in ("workspace_events", "workspace_observations", "workspace_owner"):
                for action in ("UPDATE", "DELETE"):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'workspace append-only'); END")

    def events(self, db):
        rows = db.execute("SELECT seq, command_id, request_hash, body FROM workspace_events ORDER BY seq").fetchall()
        events, previous = [], "0" * 64
        for seq, command_id, request_hash, body in rows:
            event = json.loads(body)
            if (seq != len(events) + 1 or event.get("seq") != seq or event.get("prev_hash") != previous
                    or event.get("command_id") != command_id or event.get("request_hash") != request_hash
                    or evidence.sealed({k: v for k, v in event.items() if k != "event_hash"}) != event.get("event_hash")):
                raise WorkspaceError("WORKSPACE_EVENT_CHAIN_INVALID", 409)
            previous = event["event_hash"]
            events.append(event)
        return events

    def append(self, db, events, command_id, request_hash, kind, data):
        if len(events) >= MAX_EVENTS:
            raise WorkspaceError("WORKSPACE_EVENT_LIMIT", 429)
        event = {"seq": len(events) + 1, "prev_hash": events[-1]["event_hash"] if events else "0" * 64,
                 "command_id": command_id, "request_hash": request_hash, "kind": kind, "data": data,
                 "at": self.clock(), "sample_purpose": "WORKFLOW_DEBUG", "production_authority": False}
        event["event_hash"] = evidence.sealed(event)
        db.execute("INSERT INTO workspace_events VALUES (?, ?, ?, ?)", (event["seq"], command_id, request_hash, evidence.canonical(event)))
        return event

    def owner_exists(self, db):
        return bool(db.execute("SELECT 1 FROM workspace_owner").fetchone())

    def require_owner(self, db, password):
        now = self.clock()
        self.owner_failures = [t for t in self.owner_failures if now - t < 300]
        if len(self.owner_failures) >= 5:
            raise WorkspaceError("OWNER_AUTH_RATE_LIMIT", 429)
        row = db.execute("SELECT salt, password_hash FROM workspace_owner WHERE singleton=1").fetchone()
        supplied = derive(password, row[0]) if row and isinstance(password, str) and len(password) <= 256 else ""
        if not row or not hmac.compare_digest(supplied, row[1]):
            self.owner_failures.append(now)
            raise WorkspaceError("LOCAL_OWNER_AUTH_REQUIRED", 403)

    def configure_owner(self, payload):
        exact(payload, {"password", "confirmation"})
        password = payload["password"]
        if not isinstance(password, str) or not 14 <= len(password) <= 256 or password != payload["confirmation"]:
            raise WorkspaceError("OWNER_PASSWORD_MIN_14_AND_CONFIRMATION")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if self.owner_exists(db):
                raise WorkspaceError("LOCAL_OWNER_ALREADY_CONFIGURED", 409)
            salt = secrets.token_hex(32)
            db.execute("INSERT INTO workspace_owner VALUES (1, ?, ?)", (salt, derive(password, salt)))
            events = self.events(db)
            self.append(db, events, "owner-bootstrap", evidence.sealed({"scope": "LOCAL_REVIEW_ONLY"}), "OWNER_CONFIGURED", {"scope": "LOCAL_REVIEW_ONLY_NOT_JUNYAN_IDENTITY"})
        return {"status": "LOCAL_OWNER_CONFIGURED", "team_grants": [], "production_authority": False}

    def command(self, kind, payload):
        fields = {
            "draft": {"command_id", "document_id", "expected_revision", "content"},
            "submit": {"command_id", "document_id", "revision", "content_hash"},
            "review": {"command_id", "document_id", "revision", "content_hash", "outcome", "reason", "password"},
            "schedule": {"command_id", "schedule_id", "expected_revision", "kind", "interval_minutes", "enabled", "password"},
        }
        if kind not in fields:
            raise WorkspaceError("WORKSPACE_OPERATION_DISABLED", 403)
        exact(payload, fields[kind])
        identifier(payload["command_id"])
        safe_request = {k: v for k, v in payload.items() if k != "password"}
        request_hash = evidence.sealed({"kind": kind, "payload": safe_request})
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if kind in {"review", "schedule"}:
                self.require_owner(db, payload["password"])
            events = self.events(db)
            existing = next((e for e in events if e["command_id"] == payload["command_id"]), None)
            if existing:
                if existing["request_hash"] != request_hash:
                    raise WorkspaceError("WORKSPACE_COMMAND_ID_CONFLICT", 409)
                return {"disposition": "IDEMPOTENT", "event": existing}
            state = projection(events)
            if kind == "schedule":
                identifier(payload["schedule_id"])
                minutes = payload["interval_minutes"]
                if payload["kind"] not in KINDS or type(minutes) is not int or not 10 <= minutes <= 10080 or type(payload["enabled"]) is not bool:
                    raise WorkspaceError("OFFLINE_SCHEDULE_ALLOWLIST_REQUIRED")
                prior = next((x for x in state["schedules"] if x["schedule_id"] == payload["schedule_id"]), {})
                revision = prior.get("revision", 0)
                if type(payload["expected_revision"]) is not int or payload["expected_revision"] != revision:
                    raise WorkspaceError("SCHEDULE_REVISION_CONFLICT", 409)
                data = {k: payload[k] for k in ("schedule_id", "kind", "interval_minutes", "enabled")}
                data.update(revision=revision + 1, starts_at=self.clock(), missed_policy="NO_BACKFILL", network="OFFLINE")
                event_kind = "SCHEDULE_SET"
            else:
                identifier(payload["document_id"])
                prior = next((x for x in state["documents"] if x["document_id"] == payload["document_id"]), {})
                if kind == "draft":
                    exact(payload["content"], DOCUMENT_FIELDS)
                    for key, value in payload["content"].items():
                        text_field(value, 200 if key in {"title", "ticker"} else 12000, empty=key != "title")
                    if prior.get("status") in {"IN_REVIEW", "ACCEPTED_LOCAL"}:
                        raise WorkspaceError("SUBMITTED_REVISION_IS_FROZEN", 409)
                    revision = prior.get("revision", 0)
                    if type(payload["expected_revision"]) is not int or payload["expected_revision"] != revision:
                        raise WorkspaceError("DOCUMENT_REVISION_CONFLICT", 409)
                    data = {"document_id": payload["document_id"], "revision": revision + 1, "content": payload["content"], "content_hash": evidence.sealed(payload["content"])}
                    event_kind = "DRAFT_SAVED"
                else:
                    if not prior or type(payload["revision"]) is not int or payload["revision"] != prior["revision"] or payload["content_hash"] != prior["content_hash"]:
                        raise WorkspaceError("REVIEW_CONTENT_BINDING_INVALID", 409)
                    data = {k: payload[k] for k in ("document_id", "revision", "content_hash")}
                    if kind == "submit":
                        if prior["status"] != "DRAFT":
                            raise WorkspaceError("SUBMIT_REQUIRES_DRAFT", 409)
                        missing = sorted(k for k, v in prior["content"].items() if not v.strip())
                        if missing:
                            raise WorkspaceError("DRAFT_FIELDS_MISSING:" + ",".join(missing))
                        event_kind = "SUBMITTED"
                    else:
                        if prior["status"] != "IN_REVIEW" or payload["outcome"] not in REVIEW_OUTCOMES:
                            raise WorkspaceError("REVIEW_TRANSITION_INVALID", 409)
                        text_field(payload["reason"], 2000)
                        data.update(outcome=payload["outcome"], reason=payload["reason"], authority="LOCAL_DOCUMENT_REVIEW_ONLY", formal_u4_approval=False, registration_allowed=False)
                        event_kind = "REVIEWED"
            event = self.append(db, events, payload["command_id"], request_hash, event_kind, data)
        return {"disposition": "CREATED", "event": event}

    def observe(self):
        if self.source_root is None:
            raise WorkspaceError("READ_ONLY_SOURCE_NOT_CONFIGURED", 409)
        snapshot = evidence.capture(self.source_root)
        evidence.verify(snapshot)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM workspace_observations").fetchone()[0] >= 100:
                raise WorkspaceError("OBSERVATION_LIMIT_EXPORT_AND_ROTATE_MANUALLY", 429)
            db.execute("INSERT OR IGNORE INTO workspace_observations VALUES (?, ?)", (snapshot["snapshot_hash"], evidence.canonical(snapshot)))
        return {"snapshot_hash": snapshot["snapshot_hash"], "issues": len(snapshot["issues"]), "status": "OBSERVED_WITH_GAPS" if snapshot["issues"] else "OBSERVED_NOT_PUBLICATION_ACCEPTED"}

    def start_job(self, payload, scheduled=False, schedule_guard=None):
        exact(payload, {"command_id", "kind"})
        identifier(payload["command_id"])
        if payload["kind"] not in KINDS:
            raise WorkspaceError("JOB_KIND_NOT_OFFLINE_ALLOWLIST", 403)
        job_id, request_hash = payload["command_id"], evidence.sealed(payload)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            events = self.events(db)
            if scheduled:
                active = next((s for s in projection(events)["schedules"] if s["schedule_id"] == schedule_guard[0]), None) if schedule_guard else None
                if not active or not active["enabled"] or active["revision"] != schedule_guard[1]:
                    return {"disposition": "CANCELLED_BEFORE_CLAIM", "job_id": job_id}
            prior = next((e for e in events if e["command_id"] == job_id), None)
            if prior:
                if prior["request_hash"] != request_hash:
                    raise WorkspaceError("WORKSPACE_COMMAND_ID_CONFLICT", 409)
                return {"disposition": "IDEMPOTENT", "job_id": job_id}
            self.append(db, events, job_id, request_hash, "JOB_STARTED", {"job_id": job_id, "kind": payload["kind"], "scheduled": scheduled, "recovery": "NO_AUTOMATIC_RETRY_IF_INTERRUPTED"})
        try:
            if payload["kind"] == "observe":
                result = self.observe()
            elif payload["kind"] == "integrity":
                result = self.verify_all()
            elif payload["kind"] == "backup":
                import workbench_backup
                result = workbench_backup.create(self, job_id)
            else:
                receipt = self.store.replay({"command_id": "job_" + evidence.sealed(job_id)[:40], "scenario": "complete-replay"})["receipt"]
                result = {"receipt_hash": receipt["receipt_hash"], "replay_id": receipt["command_id"], "status": receipt["status"], "synthetic": True}
            status = "SUCCEEDED" if result.get("status") not in {"STOP", "INTEGRITY_ERROR"} else "STOP"
        except Exception as exc:
            status = "STOP"
            # Never persist raw exception text from engines or provider transports.
            code = str(exc) if isinstance(exc, (WorkspaceError, evidence.EvidenceError)) else "LOCAL_JOB_FAILED"
            result = {"error": code}
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.append(db, self.events(db), "finish_" + job_id, request_hash, "JOB_FINISHED", {"job_id": job_id, "status": status, "result": result})
        return {"disposition": "CREATED", "job_id": job_id, "status": status, "result": result}

    def verify_all(self):
        with self.store.connect() as db:
            events = self.events(db)
            rows = db.execute("SELECT snapshot_hash, body FROM workspace_observations").fetchall()
            for stored_hash, raw in rows:
                snapshot = evidence.verify(json.loads(raw))
                if stored_hash != snapshot["snapshot_hash"]:
                    raise WorkspaceError("OBSERVATION_ID_BINDING_INVALID", 409)
        replay_state = self.store.snapshot()["research_runs"]
        broken = [r["command_id"] for r in replay_state if r["status"] == "INTEGRITY_ERROR"]
        return {"status": "INTEGRITY_ERROR" if broken else "LOCAL_INTEGRITY_OK", "events": len(events), "observations": len(rows), "broken_replays": broken, "production_acceptance": False}

    def tick(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            with self.store.connect() as db:
                events = self.events(db)
                state = projection(events)
            now = self.clock()
            for schedule in state["schedules"]:
                interval = schedule["interval_minutes"] * 60
                if not schedule["enabled"] or now < schedule["starts_at"] + interval:
                    continue
                slot = int((now - schedule["starts_at"]) // interval)
                command_id = "scheduled_" + evidence.sealed({"id": schedule["schedule_id"], "revision": schedule["revision"], "slot": slot})[:40]
                if not any(e["command_id"] == command_id for e in events):
                    self.start_job({"command_id": command_id, "kind": schedule["kind"]}, scheduled=True, schedule_guard=(schedule["schedule_id"], schedule["revision"]))
        finally:
            self.lock.release()

    def scheduler(self):
        while not self.stopping.wait(10):
            try:
                self.tick()
                self.scheduler_error = None
            except Exception:
                self.scheduler_error = "SCHEDULER_STOPPED_BY_INTEGRITY_OR_STORAGE_ERROR"

    def snapshot(self):
        with self.store.connect() as db:
            events = self.events(db)
            state = projection(events)
            owner = self.owner_exists(db)
            completed = [j for j in state["jobs"] if j["status"] == "SUCCEEDED" and j["kind"] == "observe" and j.get("result", {}).get("snapshot_hash")]
            snapshot_id = completed[-1]["result"]["snapshot_hash"] if completed else None
            rows = db.execute("SELECT snapshot_hash, body FROM workspace_observations WHERE snapshot_hash=?", (snapshot_id,)).fetchall()
        observation, issue = None, None
        if snapshot_id and not rows:
            issue = "OBSERVATION_INTEGRITY_ERROR"
        if rows:
            try:
                raw = json.loads(rows[0][1])
                if rows[0][0] != raw.get("snapshot_hash"):
                    raise evidence.EvidenceError("OBSERVATION_ID_BINDING_INVALID")
                observation = evidence.view(raw)
            except (ValueError, KeyError):
                issue = "OBSERVATION_INTEGRITY_ERROR"
        return {"schema": "ar-local-workspace.v1", **state, "observation": observation,
                "observation_error": issue, "events": events, "owner_configured": owner,
                "read_only_source_configured": self.source_root is not None,
                "scheduler": {"runtime": "IN_PROCESS_LOCAL_SERVER", "status": getattr(self, "scheduler_error", None) or "AVAILABLE", "missed_policy": "NO_BACKFILL", "requires_awake_host": True},
                "authority": {"team_access": False, "paid_calls": False, "production_write": False, "formal_u4_approval": False, "local_review_only": True},
                "catalog": self.catalog,
                "sample_purpose": "WORKFLOW_DEBUG"}

    def dispatch(self, path, payload):
        if path == "/api/workspace/owner":
            return self.configure_owner(payload)
        if path == "/api/workspace/job":
            return self.start_job(payload)
        routes = {"/api/workspace/draft": "draft", "/api/workspace/submit": "submit", "/api/workspace/review": "review", "/api/workspace/schedule": "schedule"}
        if path not in routes:
            raise WorkspaceError("WORKSPACE_OPERATION_DISABLED", 403)
        return self.command(routes[path], payload)
