"""S2b real SQLite/HTTP/subprocess safety and recovery pins."""
import contextlib
import http.client
import importlib.util
import io
import json
import os
import signal
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts/llm"), str(ROOT / "tests"), str(ROOT)]
import nonprod_workbench as wb
import workbench_workspace as ws
import workbench_shared_workspace as shared
import workbench_evidence as ev
import workbench_backup as backup
from workbench_shared_inputs import FrozenInputs
from workbench_shared_test_support import OWNER, MEMBER, committed_code, frozen_source, historical_state, publisher_source, reseal_publisher

jobs = __import__("workbench_shared_jobs") if importlib.util.find_spec("workbench_shared_jobs") else None
worker = __import__("workbench_shared_worker") if importlib.util.find_spec("workbench_shared_worker") else None

FAULT_SCRIPT = r'''
import json,os,sys
from pathlib import Path
code,state,snapshot,phase = sys.argv[1:]
sys.path.insert(0, str(Path(code)/"scripts/llm"))
import nonprod_workbench as wb
import workbench_workspace as ws
import workbench_shared_workspace as shared
import workbench_shared_jobs as jobs
import workbench_shared_worker as worker
import workbench_backup as backup
import workbench_shared_state as migration
import workbench_evidence as ev
from workbench_shared_inputs import FrozenInputs
shared.CODE_ROOT = Path(code)
def crash(): os._exit(77)
if phase.startswith("migration_"):
    original = migration.initialize
    def initialize(db):
        if phase == "migration_before": crash()
        original(db)
        if phase == "migration_middle": crash()
    migration.initialize = initialize
    build = migration._build_state
    def build_state(*args):
        build(*args)
        if phase == "migration_after": crash()
    migration._build_state = build_state
    migration.migrate_legacy(Path(snapshot), Path(state))
    raise SystemExit(0)
store = wb.Store(Path(state), shared_v1=True)
view = shared.SharedWorkspace(ws.Workspace(store, private_mode=True))
queue = jobs.SharedJobQueue(view, FrozenInputs(store), view._execution_identity["code_sha"])
operation = phase.split("_")[0]
original_connect = store.connect
class Connection:
    def __init__(self): self.db = original_connect(); self.written = False
    def __enter__(self): self.db.__enter__(); return self
    def __exit__(self,*args):
        if self.written and phase == operation+"_before": crash()
        value = self.db.__exit__(*args)
        if self.written and phase == operation+"_after": crash()
        self.db.close(); return value
    def execute(self,sql,*args):
        if (operation == "enqueue" and sql.startswith("INSERT INTO shared_jobs")
                or operation == "claim" and sql.startswith("INSERT INTO shared_attempts")
                or operation == "finish" and sql.startswith("UPDATE shared_jobs") and ev.parse(args[0][0])["status"] in jobs.TERMINAL):
            self.written = True
        return self.db.execute(sql,*args)
store.connect = Connection
if operation == "enqueue": queue.enqueue({"command_id":"fault-command-001", "kind":"snapshot-brief", "snapshot_id":snapshot}, "owner@example.com")
elif operation == "claim": queue.claim()
else:
    claim = queue.claim()
    if operation == "finish":
        result = worker.run_attempt(claim)
        if result["status"] != "SUCCEEDED": raise RuntimeError("real render failed")
        queue.finish(claim,result)
    elif phase.startswith("artifact_"):
        output = Path(claim["output_root"]); backup.durable_directory(output)
        worker.write_new(output/"input.json",ev.canonical({"kind":claim["kind"],"snapshot":claim["envelope"]["snapshot"],"input_hash":claim["input_hash"]}).encode())
        write = Path.write_bytes; count = [0]
        position = 1 if "first" in phase else 3
        def fault_write(path,raw):
            count[0] += 1
            if count[0] == position and phase.endswith("before"): crash()
            result = write(path,raw)
            if count[0] == position and phase.endswith("after"): crash()
            return result
        Path.write_bytes = fault_write
        worker._render_child(claim["kind"],Path(claim["frozen_root"]),output)
    else:
        write = worker.write_new
        def fault_seal(path,raw,**kwargs):
            if path.name == "seal.json" and phase == "seal_before": crash()
            if path.name == "seal.json" and phase == "seal_middle":
                # Exercise a genuinely partial fsynced inode, never a fake complete seal.
                backup.os.link = lambda *args, **kwargs: crash()
                write(path,raw[:len(raw)//2])
            if phase in {"temporary_created", "temporary_fsynced"}:
                original_open, original_fsync = backup.os.open, backup.os.fsync
                temporary_fds = set()
                def open_temporary(name,flags,*args,**options):
                    fd = original_open(name,flags,*args,**options)
                    if Path(name).name.startswith(".write-") and flags & os.O_CREAT:
                        temporary_fds.add(fd)
                        if phase == "temporary_created": crash()
                    return fd
                def fsync_temporary(fd):
                    result = original_fsync(fd)
                    if fd in temporary_fds: crash()
                    return result
                backup.os.open, backup.os.fsync = open_temporary, fsync_temporary
            result = write(path,raw,**kwargs)
            if path.name == "seal.json" and phase == "seal_after": crash()
            return result
        worker.write_new = fault_seal
        rename = worker.os.rename
        def fault_publish(source,target):
            if phase == "publish_before": crash()
            result = rename(source,target)
            if phase == "publish_after": crash()
            return result
        worker.os.rename = fault_publish
        worker.run_attempt(claim)
raise SystemExit(0)
'''


class SharedJobTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(jobs, "S2b persistent queue is missing")
        self.assertIsNotNone(worker, "S2b bounded worker is missing")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.code = self.root / "code"
        self.sha = committed_code(self.code, shared.EXECUTION_FILES)
        patch = mock.patch.object(shared, "CODE_ROOT", self.code)
        patch.start(); self.addCleanup(patch.stop)
        self.store = wb.Store(self.root / "state", shared_v1=True)
        self.system = ws.Workspace(self.store, private_mode=True)
        self.view = shared.SharedWorkspace(self.system)
        self.inputs = FrozenInputs(self.store)
        self.source = self.root / "source"
        frozen_source(self.source, cash=123)
        self.input = self.inputs.import_once(self.source)
        self.queue = jobs.SharedJobQueue(self.view, self.inputs, self.sha)
        self.lock = wb.service_lock(self.root / "state")
        self.addCleanup(self.lock.close)
        members = self.root / "members.json"
        members.write_text(json.dumps({"members": [MEMBER]})); members.chmod(0o600)
        self.private = wb.private_access("https://workbench.test-tail.ts.net:8443", OWNER, members)

    def enqueue(self, command="queue-job-0001", actor=OWNER, kind="snapshot-brief", snapshot=None):
        return self.queue.enqueue({"command_id": command, "kind": kind,
                                   "snapshot_id": snapshot or self.input["snapshot_id"]}, actor)

    def body(self, job_id):
        with self.store.connect() as db:
            return json.loads(db.execute("SELECT body FROM shared_jobs WHERE job_id=?", (job_id,)).fetchone()[0])

    def complete(self, claim=None):
        claim = claim or self.queue.claim()
        result = worker.run_attempt(claim)
        self.assertEqual(result["status"], "SUCCEEDED", result)
        return self.queue.finish(claim, result)

    @contextlib.contextmanager
    def server(self, secret="first-session"):
        server = wb.ThreadingHTTPServer(("127.0.0.1", 0), wb.make_handler(
            self.store, {"/": (b"fixture", "text/html")}, self.private.origin,
            secret, self.system, self.private, self.view))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try: yield server.server_address[1]
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def http(self, port, path, payload=None, *, secret="first-session", cookie=None, actor=OWNER):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            headers = {"Host": self.private.origin.split("//")[1], "Origin": self.private.origin,
                       "Tailscale-User-Login": actor, "Content-Type": "application/json",
                       "Cookie": cookie or "ar_workbench=" + wb.private_session(secret, actor)}
            connection.request("POST" if payload is not None else "GET", path,
                               json.dumps(payload) if payload is not None else None, headers)
            response = connection.getresponse(); raw = response.read()
            return response.status, (json.loads(raw) if path != "/" else raw), response.getheader("Set-Cookie")
        finally: connection.close()

    def entry_get(self, path="/", *, headers=None, shared_mode=True):
        values = {"Host": self.private.origin.split("//")[1], "Origin": self.private.origin,
                  "Tailscale-User-Login": OWNER,
                  "Cookie": "ar_workbench=" + wb.private_session("first-session", OWNER)}
        values.update(headers or {})
        class Transport:
            def __init__(self):
                self.input = io.BytesIO((f"GET {path} HTTP/1.0\r\n" + "".join(
                    f"{key}: {value}\r\n" for key, value in values.items()) + "\r\n").encode())
                self.output = b""
            def makefile(self, *args): return self.input
            def settimeout(self, value): pass
            def sendall(self, value): self.output += value
        transport = Transport()
        handler = wb.make_handler(self.store, {"/": (b"fixture", "text/html")}, self.private.origin,
                                  "renewed-session", self.system, self.private, self.view if shared_mode else None)
        handler(transport, ("127.0.0.1", 12345), object())
        head, body = transport.output.split(b"\r\n\r\n", 1)
        lines = head.split(b"\r\n", 1)
        return int(lines[0].split()[1]), http.client.parse_headers(io.BytesIO(lines[1] + b"\r\n\r\n")), body

    def test_enqueue_returns_before_renderer_completes(self):
        with self.server() as port:
            before = time.monotonic()
            status, result, _ = self.http(port, "/api/workspace/job", {
                "command_id": "http-async-0001", "kind": "snapshot-brief", "snapshot_id": self.input["snapshot_id"]})
            self.assertEqual(status, 202)
            self.assertLess(time.monotonic() - before, 2)
            self.assertEqual(result["status"], "QUEUED")
            self.assertEqual(self.body(result["job_id"])["status"], "QUEUED")
            self.complete()
            status, detail, _ = self.http(port, "/api/shared-workspace/jobs/" + result["job_id"])
            self.assertEqual(status, 200)
            self.assertEqual(detail["status"], "SUCCEEDED")
            self.assertEqual(ev.sha(detail["report"].encode()), detail["output_hash"])
            self.assertNotIn(OWNER, detail["report"])
            self.assertNotIn(result["job_id"], detail["report"])
            for extra in ({"timeout_seconds": 0.01}, {"actor": MEMBER}, {"reserve": False}):
                status, _, _ = self.http(port, "/api/workspace/job", {
                    "command_id": "forged-http-001", "kind": "observe", "snapshot_id": self.input["snapshot_id"], **extra})
                self.assertEqual(status, 400)

    def test_two_claimers_one_job(self):
        job = self.enqueue(); barrier = threading.Barrier(2); claimed = []
        def claim():
            barrier.wait(); claimed.append(self.queue.claim())
        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(sum(item is not None for item in claimed), 1)
        self.assertEqual(self.complete(next(item for item in claimed if item))["job_id"], job["job_id"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM shared_attempts").fetchone()[0], 1)
            terminal = [e for e in self.system.events(db) if e["kind"] == "SHARED_JOB_TERMINAL"]
            self.assertEqual(len(terminal), 1)

    def test_fifo_two_slots_and_actor_limits(self):
        first = self.enqueue("fifo-owner-001"); second = self.enqueue("fifo-member-001", MEMBER)
        third = self.enqueue("fifo-owner-002")
        with self.assertRaises(ws.WorkspaceError) as found: self.enqueue("fifo-owner-003")
        self.assertEqual(found.exception.status, 429)
        a, b = self.queue.claim(), self.queue.claim()
        self.assertEqual([a["job_id"], b["job_id"]], [first["job_id"], second["job_id"]])
        self.assertIsNone(self.queue.claim())
        self.complete(a)
        self.assertEqual(self.queue.claim()["job_id"], third["job_id"])
        # Direct trusted actors exercise the independent global limit; HTTP still has its allowlist.
        other = wb.Store(self.root / "global", shared_v1=True)
        view = shared.SharedWorkspace(ws.Workspace(other, private_mode=True))
        inputs = FrozenInputs(other); descriptor = inputs.import_once(self.source)
        queue = jobs.SharedJobQueue(view, inputs, self.sha)
        for index in range(20):
            queue.enqueue({"command_id": f"global-job-{index:03d}", "kind": "observe", "snapshot_id": descriptor["snapshot_id"]}, f"actor{index}@fixture.invalid")
        with self.assertRaises(ws.WorkspaceError) as found:
            queue.enqueue({"command_id": "global-overflow-001", "kind": "observe", "snapshot_id": descriptor["snapshot_id"]}, "overflow@fixture.invalid")
        self.assertEqual(found.exception.status, 429)

    def test_cross_actor_retry_conflict(self):
        original = self.enqueue()
        self.assertEqual(self.enqueue()["job_id"], original["job_id"])
        for actor, kind in ((MEMBER, "snapshot-brief"), (OWNER, "observe")):
            with self.assertRaises(ws.WorkspaceError) as found: self.enqueue(actor=actor, kind=kind)
            self.assertEqual(found.exception.status, 409)
        claim = self.queue.claim()
        self.queue.finish(claim, {"status": "STOP", "error": "WORKER_TIMEOUT"})
        self.assertEqual(self.enqueue()["status"], "STOP")
        with mock.patch.object(shared, "execution_identity", side_effect=AssertionError("retry must not execute")):
            self.assertEqual(self.enqueue()["status"], "STOP")

    def test_terminal_capacity_reserved(self):
        with mock.patch.object(ws, "MAX_EVENTS", 4):
            self.system.audit_login(OWNER)
            job = self.enqueue()
            claim = self.queue.claim()
            self.system.audit_login(OWNER)
            with self.assertRaises(ws.WorkspaceError) as found: self.system.audit_login(OWNER)
            self.assertEqual(found.exception.status, 429)
            self.assertEqual(self.complete(claim)["status"], "SUCCEEDED")
            self.assertEqual(self.enqueue()["job_id"], job["job_id"])
            with self.store.connect() as db:
                self.assertEqual(len(self.system.events(db)), 4)

    def test_pending_job_never_changes_input(self):
        first = self.enqueue()
        frozen_source(self.source, "published_two", "20261014", cash=456)
        second_input = self.inputs.import_once(self.source)
        self.enqueue("new-input-job-001", MEMBER, snapshot=second_input["snapshot_id"])
        self.assertEqual(self.body(first["job_id"])["input_hash"], self.input["input_hash"])
        self.complete()
        detail = self.view.job(first["job_id"], OWNER)
        self.assertIn("123", detail["report"])
        self.assertNotIn("456", detail["report"])
        self.assertEqual(detail["source_run_id"], "published_one")

    def test_timeout_releases_slot_and_kills_process_group(self):
        self.enqueue(); self.enqueue("parallel-good-001", MEMBER)
        hung, good = self.queue.claim(), self.queue.claim()
        marker = self.root / "grandchild-alive"
        grandchild = f"import time,pathlib; time.sleep(.6); pathlib.Path({str(marker)!r}).write_text('alive')"
        helper = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{grandchild!r}]); time.sleep(2)"
        result = worker.run_bounded([sys.executable, "-c", helper], {"SECRET_KEY": "not-inherited"}, self.root, .15)
        self.assertEqual(result.get("error"), "WORKER_TIMEOUT")
        self.assertEqual(self.queue.finish(hung, result)["status"], "STOP")
        self.complete(good)
        self.enqueue("after-timeout-001")
        self.assertIsNotNone(self.queue.claim())
        time.sleep(.7); self.assertFalse(marker.exists(), "timed-out process group survived")

    def test_network_reconnect_preserves_job_id_after_cookie_renewal(self):
        with self.server() as port:
            status, receipt, _ = self.http(port, "/api/workspace/job", {"command_id": "reconnect-001", "kind": "observe", "snapshot_id": self.input["snapshot_id"]})
            self.assertEqual(status, 202)
        self.queue.recover()
        with self.server("renewed-session") as port:
            status, _, _ = self.http(port, "/api/shared-workspace/jobs/" + receipt["job_id"])
            self.assertEqual(status, 403)
            status, _, cookie = self.http(port, "/", secret="renewed-session")
            self.assertEqual(status, 200)
            status, detail, _ = self.http(port, "/api/shared-workspace/jobs/" + receipt["job_id"], cookie=cookie.split(";")[0])
            self.assertEqual(status, 200); self.assertEqual(detail["job_id"], receipt["job_id"])
        with self.store.connect() as db: self.assertEqual(db.execute("SELECT COUNT(*) FROM shared_jobs").fetchone()[0], 1)

    def test_old_token_finish_refused(self):
        self.enqueue(); old = self.queue.claim()
        self.queue.recover(); new = self.queue.claim()
        self.assertNotEqual(old["token"], new["token"])
        self.assertNotEqual(old["output_root"], new["output_root"])
        late_result = worker.run_attempt(old)
        with self.assertRaises(ws.WorkspaceError) as found: self.queue.finish(old, late_result)
        self.assertEqual(found.exception.status, 409)
        self.complete(new)
        with self.store.connect() as db: self.assertEqual(sum(e["kind"] == "SHARED_JOB_TERMINAL" for e in self.system.events(db)), 1)

    def test_sealed_output_recovers_without_rerender(self):
        job = self.enqueue(); claim = self.queue.claim(); self.assertEqual(worker.run_attempt(claim)["status"], "SUCCEEDED")
        report = Path(claim["output_root"]) / "result/report.md"
        before = (report.stat().st_ino, report.stat().st_mtime_ns, report.read_bytes())
        recovered = self.queue.recover()
        self.assertEqual(recovered["converged"], [job["job_id"]])
        self.assertEqual(self.body(job["job_id"])["status"], "SUCCEEDED")
        self.assertEqual((report.stat().st_ino, report.stat().st_mtime_ns, report.read_bytes()), before)
        self.assertIsNone(self.queue.claim())
        self.assertEqual(self.queue.recover()["converged"], [])

    def test_recovery_attempt_limit(self):
        job = self.enqueue(); self.queue.claim()
        self.assertEqual(self.queue.recover()["rescheduled"], [job["job_id"]])
        self.queue.claim()
        self.assertEqual(self.queue.recover()["interrupted"], [job["job_id"]])
        self.assertIsNone(self.queue.claim())
        self.assertEqual(self.enqueue()["status"], "INTERRUPTED")
        with self.store.connect() as db: self.assertEqual(db.execute("SELECT COUNT(*) FROM shared_attempts").fetchone()[0], 2)

    def test_incompatible_code_or_missing_input_requires_recovery(self):
        job = self.enqueue()
        path = self.inputs.base / "envelopes" / (self.input["snapshot_id"] + ".json")
        raw = path.read_bytes(); path.unlink()
        self.assertEqual(self.queue.recover()["recovery_required"], [job["job_id"]])
        self.assertEqual(self.enqueue()["status"], "RECOVERY_REQUIRED")
        path.write_bytes(raw)
        second = self.enqueue("schema-changed-001")
        with self.store.connect() as db:
            body = self.body(second["job_id"]); body["schema_version"] = "unapproved.v99"
            db.execute("UPDATE shared_jobs SET body=? WHERE job_id=?", (ev.canonical(body), second["job_id"]))
        self.assertEqual(self.queue.recover()["recovery_required"], [second["job_id"]])
        third = self.enqueue("code-changed-001")
        changed = self.code / "scripts/llm/workbench_shared_worker.py"
        changed.write_bytes(changed.read_bytes() + b"\n# different committed execution release\n")
        for args in (("add", "--", "scripts/llm/workbench_shared_worker.py"),
                     ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "changed execution release")):
            subprocess.run(["git", "-C", str(self.code), *args], check=True, capture_output=True)
        self.assertNotEqual(shared.execution_identity(self.code)["code_sha"], self.sha)
        self.assertEqual(self.queue.recover()["recovery_required"], [third["job_id"]])

    def test_legacy_started_never_guessed_success(self):
        with self.store.connect() as db:
            self.system.append(db, [], "legacy-started-001", ev.sealed("legacy"), "JOB_STARTED", {"job_id": "legacy-started-001", "kind": "observe", "scheduled": False})
            before = db.execute("SELECT body FROM workspace_events").fetchall()
        self.assertIn("legacy-started-001", self.queue.recover()["interrupted"])
        self.assertEqual(self.view.job("legacy-started-001", OWNER)["status"], "INTERRUPTED")
        self.assertEqual(self.view.job("legacy-started-001", OWNER)["error"], "LEGACY_NOT_RECOVERABLE")
        with self.store.connect() as db: self.assertEqual(db.execute("SELECT body FROM workspace_events").fetchall(), before)

    def test_backup_restore_crosschecks_queue_seal_and_attempts(self):
        job = self.enqueue(); self.complete()
        result = backup.backup_shared(self.store, self.root / "good-backup")
        self.assertEqual(result["restore_check"]["status"], "LOCAL_SHARED_RESTORE_VERIFIED")
        body = self.body(job["job_id"])
        report = self.root / "state/shared-jobs" / body["workspace_id"] / job["job_id"] / "attempts" / body["attempt_id"] / "result/report.md"
        report.write_text("altered")
        self.assertEqual(self.view.job(job["job_id"], OWNER)["status"], "RECOVERY_REQUIRED")
        with self.assertRaises((ev.EvidenceError, ws.WorkspaceError, ValueError)):
            backup.backup_shared(self.store, self.root / "bad-backup")

    def test_conflicting_output_seal_requires_recovery(self):
        job = self.enqueue(); claim = self.queue.claim()
        self.assertEqual(worker.run_attempt(claim)["status"], "SUCCEEDED")
        (Path(claim["output_root"]) / "result/unsealed-extra.txt").write_text("conflicting artifact")
        self.assertEqual(self.queue.recover()["recovery_required"], [job["job_id"]])
        self.assertEqual(self.enqueue()["status"], "RECOVERY_REQUIRED")

    def test_missing_published_seal_requires_recovery(self):
        job = self.enqueue(); claim = self.queue.claim()
        self.assertEqual(worker.run_attempt(claim)["status"], "SUCCEEDED")
        (Path(claim["output_root"]) / "seal.json").unlink()
        self.assertEqual(self.queue.recover()["recovery_required"], [job["job_id"]])
        self.assertIsNone(self.queue.claim())

    def test_failed_result_cannot_hide_a_conflicting_seal(self):
        self.enqueue(); claim = self.queue.claim()
        self.assertEqual(worker.run_attempt(claim)["status"], "SUCCEEDED")
        (Path(claim["output_root"]) / "seal.json").write_text('{}')
        self.assertEqual(self.queue.finish(claim, {"status": "STOP", "error": "WORKER_OUTPUT_INVALID"})["status"], "RECOVERY_REQUIRED")

    def test_resealed_mutable_job_cannot_replace_accepted_binding(self):
        job = self.enqueue(); claim = self.queue.claim(); self.complete(claim)
        body = self.body(job["job_id"])
        body["code_sha"] = "b" * 40
        seal_path = Path(claim["output_root"]) / "seal.json"
        seal = json.loads(seal_path.read_bytes()); seal["binding"]["code_sha"] = "b" * 40
        seal["seal_hash"] = ev.sealed({k: v for k, v in seal.items() if k != "seal_hash"})
        body["result"]["seal_hash"] = seal["seal_hash"]
        seal_path.write_text(ev.canonical(seal))
        with self.store.connect() as db:
            db.execute("UPDATE shared_jobs SET body=? WHERE job_id=?", (ev.canonical(body), job["job_id"]))
        self.assertEqual(self.view.job(job["job_id"], OWNER)["status"], "RECOVERY_REQUIRED")

    def test_queue_inventory_is_not_a_legacy_output_placeholder(self):
        job = self.enqueue(); self.complete()
        backup.backup_shared(self.store, self.root / "inventory-backup")
        manifest = backup.verify_shared(self.root / "inventory-backup")
        owned = [row for row in manifest["artifact_inventory"] if row["job_id"] == job["job_id"]]
        self.assertEqual(len(owned), 1)
        self.assertEqual(owned[0]["presence"], "PRESENT")
        self.assertTrue(owned[0]["path"].startswith("shared-jobs/"))

    def test_missing_current_attempt_requires_recovery_without_crashing(self):
        job = self.enqueue(); claim = self.queue.claim()
        with self.store.connect() as db: db.execute("DELETE FROM shared_attempts WHERE attempt_id=?", (claim["attempt_id"],))
        try: report = self.queue.recover()
        except Exception as exc: self.fail(f"missing technical attempt must be quarantined, not crash: {type(exc).__name__}")
        self.assertEqual(report["recovery_required"], [job["job_id"]])
        self.assertEqual(self.enqueue()["status"], "RECOVERY_REQUIRED")

    def test_dangling_current_attempt_is_quarantined(self):
        job = self.enqueue(); self.queue.claim()
        body = self.body(job["job_id"]); body["attempt_id"] = "00000000-0000-4000-8000-000000000001"
        with self.store.connect() as db:
            db.execute("UPDATE shared_jobs SET body=? WHERE job_id=?", (ev.canonical(body), job["job_id"]))
        try: report = self.queue.recover()
        except Exception as exc: self.fail(f"intact attempt rows with dangling pointer must not crash: {type(exc).__name__}")
        self.assertEqual(report["recovery_required"], [job["job_id"]])
        self.assertEqual(self.body(job["job_id"])["status"], "RECOVERY_REQUIRED")

    def test_current_attempt_contract_shared_by_backup_recovery_and_finish(self):
        job = self.enqueue(); old = self.queue.claim()
        self.queue.recover(); current = self.queue.claim()
        self.assertEqual(worker.run_attempt(old)["status"], "SUCCEEDED")
        original = self.body(job["job_id"])
        with self.store.connect() as db:
            rows = db.execute("SELECT attempt_id, body FROM shared_attempts ORDER BY rowid").fetchall()
        cases = ("old_pointer", "status", "token", "number", "binding")
        for mode in cases:
            for consumer in ("backup", "recovery", "finish"):
                with self.subTest(mode=mode, consumer=consumer):
                    state = self.root / (mode + "-" + consumer)
                    shutil.copytree(self.store.path.parent, state)
                    store = wb.Store(state, shared_v1=True)
                    view = shared.SharedWorkspace(ws.Workspace(store, private_mode=True))
                    queue = jobs.SharedJobQueue(view, FrozenInputs(store), self.sha)
                    body = dict(original)
                    changed = json.loads(rows[-1][1])
                    if mode == "old_pointer": body["attempt_id"] = old["attempt_id"]
                    elif mode == "status": changed["status"] = "ABANDONED"
                    elif mode == "token": changed["token_hash"] = "0" * 64
                    elif mode == "number": changed["number"] = 1
                    else: changed["binding"]["input_hash"] = "0" * 64
                    with store.connect() as db:
                        db.execute("UPDATE shared_jobs SET body=? WHERE job_id=?", (ev.canonical(body), job["job_id"]))
                        db.execute("UPDATE shared_attempts SET body=? WHERE attempt_id=?", (ev.canonical(changed), current["attempt_id"]))
                    if consumer == "backup":
                        with self.assertRaises(ev.EvidenceError):
                            backup.backup_shared(store, self.root / ("invalid-" + mode))
                    elif consumer == "recovery":
                        self.assertEqual(queue.recover()["recovery_required"], [job["job_id"]])
                    else:
                        claim = dict(current)
                        if mode == "old_pointer": claim["attempt_id"] = old["attempt_id"]
                        self.assertEqual(queue.finish(claim, {"status": "STOP"})["status"], "RECOVERY_REQUIRED")

    def test_sealed_observe_recovery_restores_observation_projection(self):
        job = self.enqueue(kind="observe"); claim = self.queue.claim()
        self.assertEqual(worker.run_attempt(claim)["status"], "SUCCEEDED")
        seal = Path(claim["output_root"]) / "seal.json"
        before = (seal.stat().st_ino, seal.stat().st_mtime_ns, seal.read_bytes())
        self.assertEqual(self.queue.recover()["converged"], [job["job_id"]])
        with self.store.connect() as db:
            observed = db.execute("SELECT snapshot_hash, body FROM workspace_observations").fetchall()
            self.assertEqual(len(observed), 1)
            self.assertEqual(json.loads(observed[0][1]), claim["envelope"]["snapshot"])
            self.assertEqual(sum(e["kind"] == "SHARED_JOB_TERMINAL" for e in self.system.events(db)), 1)
        self.assertEqual(self.queue.recover()["converged"], [])
        self.assertEqual((seal.stat().st_ino, seal.stat().st_mtime_ns, seal.read_bytes()), before)

    def test_sealed_observe_recovery_checks_observation_capacity(self):
        job = self.enqueue(kind="observe"); claim = self.queue.claim()
        self.assertEqual(worker.run_attempt(claim)["status"], "SUCCEEDED")
        with self.store.connect() as db:
            db.executemany("INSERT INTO workspace_observations VALUES (?, ?)", [(f"existing-{n}", "{}") for n in range(100)])
        self.assertEqual(self.queue.recover()["recovery_required"], [job["job_id"]])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM workspace_observations").fetchone()[0], 100)
        self.assertEqual(self.body(job["job_id"])["status"], "RECOVERY_REQUIRED")

    def test_session_renewal_remains_available_at_reserved_event_capacity(self):
        with mock.patch.object(ws, "MAX_EVENTS", 4):
            self.system.audit_login(OWNER)
            job = self.enqueue(kind="observe"); claim = self.queue.claim()
            self.system.audit_login(OWNER)
            path = "/api/shared-workspace/jobs/" + job["job_id"]
            self.assertEqual(self.entry_get(path)[0], 403)
            for full in (False, True):
                with self.subTest(full=full):
                    if full: self.complete(claim)
                    with self.store.connect() as db: before = db.execute("SELECT body FROM workspace_events ORDER BY seq").fetchall()
                    status, headers, _ = self.entry_get()
                    self.assertEqual(status, 200)
                    self.assertEqual(headers.get("X-Workbench-Login-Audit"), "EVENT_CAPACITY_EXHAUSTED")
                    cookie = headers.get("Set-Cookie")
                    self.assertIsNotNone(cookie)
                    status, _, raw = self.entry_get(path, headers={"Cookie": cookie.split(";")[0]})
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(raw)["job_id"], job["job_id"])
                    for invalid in ({"Host": "evil.invalid"}, {"Origin": "https://evil.invalid"},
                                    {"Tailscale-User-Login": "stranger@example.com"}):
                        rejected, denied, _ = self.entry_get(headers=invalid)
                        self.assertEqual(rejected, 403)
                        self.assertIsNone(denied.get("Set-Cookie"))
                    self.assertEqual(self.entry_get(shared_mode=False)[0], 429)
                    with self.store.connect() as db: self.assertEqual(db.execute("SELECT body FROM workspace_events ORDER BY seq").fetchall(), before)

    def test_shared_entry_reports_appended_login_audit(self):
        status, headers, _ = self.entry_get()
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Workbench-Login-Audit"), "APPENDED")
        with self.store.connect() as db:
            self.assertEqual([event["kind"] for event in self.system.events(db)], ["PRIVATE_LOGIN"])

    def test_corrupt_pending_binding_remains_attributed_to_acceptance(self):
        job = self.enqueue(); original = self.body(job["job_id"])
        body = dict(original); body.update(actor=MEMBER, workspace_id=self.view.identity(MEMBER)["workspace_id"])
        with self.store.connect() as db: db.execute("UPDATE shared_jobs SET body=? WHERE job_id=?", (ev.canonical(body), job["job_id"]))
        self.assertEqual(self.queue.recover()["recovery_required"], [job["job_id"]])
        detail = self.view.job(job["job_id"], OWNER)
        self.assertEqual(detail["actor"], OWNER)
        self.assertEqual(detail["workspace_id"], original["workspace_id"])

    def test_detail_read_rechecks_bytes_after_seal_reopen(self):
        job = self.enqueue(); claim = self.queue.claim(); self.complete(claim)
        report = Path(claim["output_root"]) / "result/report.md"
        original_view = self.queue._view
        def change_after_verify(body):
            result = original_view(body); report.write_text("changed after reopen"); return result
        with mock.patch.object(self.queue, "_view", side_effect=change_after_verify):
            detail = self.view.job(job["job_id"], OWNER)
        self.assertEqual(detail["status"], "RECOVERY_REQUIRED")
        self.assertNotIn("report", detail)

    def test_backup_refuses_missing_current_attempt_or_forged_seal_binding(self):
        job = self.enqueue(); claim = self.queue.claim(); self.complete(claim)
        good = self.root / "bound-backup"; backup.backup_shared(self.store, good)
        data_path = good / "data.json"; original = data_path.read_bytes()
        data = json.loads(original)
        data["tables"]["shared_attempts"] = []
        raw = ev.canonical(data).encode(); data_path.write_bytes(raw)
        manifest_path = good / "manifest.json"; manifest = json.loads(manifest_path.read_bytes())
        manifest["files"]["data.json"] = ev.sha(raw); manifest["table_counts"]["shared_attempts"] = 0
        manifest["backup_hash"] = ev.sealed({k: v for k, v in manifest.items() if k != "backup_hash"})
        manifest_path.write_text(ev.canonical(manifest))
        with self.assertRaises((ValueError, KeyError)):
            backup.restore_shared(good, self.root / "forged-restore")
        self.assertFalse((self.root / "forged-restore").exists())
        seal_path = Path(claim["output_root"]) / "seal.json"
        original_seal = seal_path.read_bytes()
        for key, value in (("actor", MEMBER), ("input_hash", "b" * 64), ("code_sha", "c" * 40)):
            seal = json.loads(original_seal); seal["binding"][key] = value
            seal["seal_hash"] = ev.sealed({k: v for k, v in seal.items() if k != "seal_hash"})
            seal_path.write_text(ev.canonical(seal))
            with self.assertRaises(ValueError): backup.backup_shared(self.store, self.root / ("bad-" + key))
        seal_path.write_bytes(original_seal)

    def test_observation_capacity_is_not_bypassed(self):
        snapshot = self.inputs.verify(self.input["snapshot_id"])["snapshot"]
        with self.store.connect() as db:
            for index in range(100):
                value = {**snapshot, "observed_at": f"fixture-{index}"}
                value["snapshot_hash"] = ev.sealed({k: v for k, v in value.items() if k != "snapshot_hash"})
                ev.verify(value)
                db.execute("INSERT INTO workspace_observations VALUES (?, ?)", (value["snapshot_hash"], ev.canonical(value)))
        with self.assertRaises(ws.WorkspaceError) as found: self.enqueue(kind="observe")
        self.assertEqual(found.exception.status, 429)
        with self.assertRaises(wb.WorkbenchError): wb.service_lock(self.root / "state")

    def test_orphan_child_deadline_kills_its_own_group_without_coordinator(self):
        self.assertIsNotNone(getattr(worker, "_arm_deadline", None), "renderer needs its own deadline after coordinator death")
        marker = self.root / "orphan-descendant"
        descendant = f"import time,pathlib; time.sleep(.6); pathlib.Path({str(marker)!r}).write_text('alive')"
        program = f"import sys,time,subprocess; sys.path.insert(0,{str(self.code / 'scripts/llm')!r}); import workbench_shared_worker as w; w._arm_deadline(.2); subprocess.Popen([sys.executable,'-c',{descendant!r}]); time.sleep(3)"
        process = subprocess.Popen([sys.executable, "-I", "-B", "-c", program], start_new_session=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.assertEqual(process.wait(timeout=2), -signal.SIGKILL)
            time.sleep(.7); self.assertFalse(marker.exists())
        finally:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait()

    def test_worker_retries_busy_sqlite_finish_without_rerender(self):
        job = self.enqueue()
        rendered, permit_finish = threading.Event(), threading.Event()
        original = worker.run_attempt
        output = []
        def render(claim):
            result = original(claim); output.append(Path(claim["output_root"]) / "result/report.md")
            rendered.set(); permit_finish.wait(5); return result
        def short_connection(): return sqlite3.connect(str(self.store.path), timeout=.05)
        runner = worker.SharedWorker(self.queue)
        with mock.patch.object(self.store, "connect", side_effect=short_connection), mock.patch.object(worker, "run_attempt", side_effect=render):
            runner.start()
            database = None
            try:
                self.assertTrue(rendered.wait(5))
                database = sqlite3.connect(str(self.store.path)); database.execute("BEGIN IMMEDIATE")
                before = (output[0].stat().st_ino, output[0].stat().st_mtime_ns)
                permit_finish.set(); time.sleep(.3)
                database.rollback(); database.close(); database = None
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and self.body(job["job_id"])["status"] != "SUCCEEDED": time.sleep(.05)
                self.assertEqual(self.body(job["job_id"])["status"], "SUCCEEDED")
                self.assertEqual((output[0].stat().st_ino, output[0].stat().st_mtime_ns), before)
                self.assertEqual(len(output), 1)
                self.assertTrue(all(thread.is_alive() for thread in runner.threads))
            finally:
                permit_finish.set()
                if database: database.rollback(); database.close()
                runner.stop()

    def test_paginated_projection_reopens_only_visible_and_latest_results(self):
        submitted = []
        for index in range(3):
            submitted.append(self.enqueue(f"page-job-{index:03d}")); self.complete()
        reopened = []
        original = jobs.verify_seal
        def verify(*args, **kwargs):
            reopened.append(args[1]["job_id"]); return original(*args, **kwargs)
        with mock.patch.object(shared, "PAGE_SIZE", 1), mock.patch.object(jobs, "verify_seal", side_effect=verify):
            data = self.view.snapshot(OWNER, page=1)
        self.assertEqual(data["my_jobs"][0]["job_id"], submitted[1]["job_id"])
        self.assertEqual(set(reopened), {submitted[1]["job_id"], submitted[2]["job_id"]})
        self.assertEqual(len(reopened), 2, 'my/team/latest duplicate jobs must be verified once per request')

    def test_request_dedup_never_caches_a_seal_across_requests(self):
        owner = self.enqueue("owner-read-dedup"); self.complete()
        member = self.enqueue("member-read-dedup", MEMBER); self.complete()
        original = jobs.verify_seal
        with mock.patch.object(jobs, "verify_seal", wraps=original) as seals, mock.patch.object(self.inputs, "verify", wraps=self.inputs.verify) as inputs:
            for actor in (OWNER, MEMBER):
                data = self.view.snapshot(actor)
                self.assertEqual(len(data["my_jobs"]), 1)
                self.assertEqual(len(data["team_jobs"]), 2)
                self.assertTrue(all(row["status"] == "SUCCEEDED" for row in data["team_jobs"]))
            self.assertEqual(seals.call_count, 4, 'two physical seals must be reopened on each request')
            self.assertEqual(inputs.call_count, 2, 'one shared input must be reopened once per request, not cached across requests')
        current = self.body(owner["job_id"])
        output = jobs._output_root(self.store.path.parent, current, {"attempt_id": current["attempt_id"]})
        (output / "result/report.md").write_bytes(b"tampered between requests")
        data = self.view.snapshot(MEMBER)
        self.assertEqual(next(row for row in data["team_jobs"] if row["job_id"] == owner["job_id"])["status"], "RECOVERY_REQUIRED")
        self.assertEqual(data["my_jobs"][0]["job_id"], member["job_id"])

    def test_malformed_macro_display_does_not_break_shared_overview(self):
        for report in ({"invalid": True}, [], "UNKNOWN", None):
            with self.subTest(report=report):
                publisher_source(self.source)
                reseal_publisher(self.source, "public/data/v2/macro/macro_events.json", {
                    "schema": "ar.macro.events", "schema_version": "1.0",
                    "run_id": "publisher_run", "report": report})
                self.inputs.import_once(self.source)
                data = self.view.snapshot(OWNER)
                self.assertEqual(data["my_jobs"], [])
                self.assertIsNone(data["common_data"]["error"])
                macro = next(row for row in data["common_data"]["observation"]["module_sources"] if row["module"] == "Macro")
                self.assertEqual(macro["data_quality"], "UNAVAILABLE")
                self.assertEqual(macro["pipeline_status"], "UNAVAILABLE")

    def test_crash_at_every_persistent_boundary(self):
        phases = ("enqueue_before", "enqueue_after", "claim_before", "claim_after",
                  "artifact_first_before", "artifact_first_after", "artifact_middle_before", "artifact_middle_after",
                  "seal_before", "seal_middle", "seal_after", "publish_before", "publish_after", "finish_before", "finish_after")
        for phase in phases:
            with self.subTest(phase=phase):
                store = wb.Store(self.root / phase, shared_v1=True)
                view = shared.SharedWorkspace(ws.Workspace(store, private_mode=True))
                inputs = FrozenInputs(store); descriptor = inputs.import_once(self.source)
                queue = jobs.SharedJobQueue(view, inputs, self.sha)
                payload = {"command_id": "fault-command-001", "kind": "snapshot-brief", "snapshot_id": descriptor["snapshot_id"]}
                if not phase.startswith("enqueue_"): queue.enqueue(payload, OWNER)
                crashed = subprocess.run([sys.executable, "-I", "-B", "-c", FAULT_SCRIPT,
                                          str(self.code), str(store.path.parent), descriptor["snapshot_id"], phase], capture_output=True, text=True)
                self.assertEqual(crashed.returncode, 77, crashed.stderr)
                original = queue.enqueue(payload, OWNER)
                # A later publication is available at recovery; the old command must not drift.
                if phase == "finish_after":
                    frozen_source(self.source, "across_run_update", "20261014", cash=456)
                    inputs.import_once(self.source)
                report = queue.recover()
                current = queue.job(original["job_id"])
                if phase in {"seal_after", "publish_before", "publish_after", "finish_before", "finish_after"}:
                    self.assertEqual(current["status"], "SUCCEEDED")
                    self.assertIsNone(queue.claim())
                else:
                    self.assertEqual(current["status"], "QUEUED", report)
                    claim = queue.claim()
                    self.assertEqual(queue.finish(claim, worker.run_attempt(claim))["status"], "SUCCEEDED")
                with store.connect() as db:
                    self.assertLessEqual(db.execute("SELECT COUNT(*) FROM shared_attempts").fetchone()[0], 2)
                    events = view.system.events(db)
                    self.assertEqual(sum(e["kind"] == "SHARED_JOB_TERMINAL" for e in events), 1)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM shared_jobs").fetchone()[0], 1)
        historical_store, _ = historical_state(self.root / "historical")
        archive = self.root / "historical-backup"; backup.backup_shared(historical_store, archive)
        original_bytes = historical_store.path.read_bytes()
        import workbench_shared_state as migration
        for phase in ("migration_before", "migration_middle", "migration_after"):
            target = self.root / phase
            crashed = subprocess.run([sys.executable, "-I", "-B", "-c", FAULT_SCRIPT,
                                      str(self.code), str(target), str(archive), phase], capture_output=True, text=True)
            self.assertEqual(crashed.returncode, 77, crashed.stderr)
            receipt = migration.migrate_legacy(archive, target)
            self.assertEqual(receipt["status"], "SHARED_MIGRATION_VERIFIED")
            self.assertEqual(historical_store.path.read_bytes(), original_bytes)
        print("S2B_CRASH_MATRIX six_groups=18 subprocess_fault_points", flush=True)

    def test_clean_child_environment_and_closed_registry(self):
        output = self.root / "env.json"
        program = "import os,json,pathlib; pathlib.Path('env.json').write_text(json.dumps(dict(os.environ)))"
        result = worker.run_bounded([sys.executable, "-I", "-c", program], {"SECRET_KEY": "must-not-leak", "PYTHONPATH": "/bad", "PATH": "/usr/bin:/bin"}, self.root)
        self.assertEqual(result["status"], "SUCCEEDED")
        environment = json.loads(output.read_text())
        self.assertNotIn("SECRET_KEY", environment); self.assertNotIn("PYTHONPATH", environment)
        job = self.enqueue(); claim = self.queue.claim(); claim["kind"] = "market"
        self.assertEqual(worker.run_attempt(claim)["status"], "STOP")
        self.assertEqual(self.body(job["job_id"])["status"], "RUNNING")

    def test_deterministic_two_actors_and_worker_lifecycle(self):
        first = self.enqueue(); second = self.enqueue("same-input-member-001", MEMBER)
        runner = worker.SharedWorker(self.queue); runner.start()
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and any(self.body(item["job_id"])["status"] != "SUCCEEDED" for item in (first, second)):
                time.sleep(.05)
            self.assertEqual(self.body(first["job_id"])["status"], "SUCCEEDED")
            self.assertEqual(self.body(second["job_id"])["output_hash"], self.body(first["job_id"])["output_hash"])
            self.assertEqual(len(runner.threads), 2)
        finally: runner.stop()
        self.assertTrue(all(not thread.is_alive() for thread in runner.threads))

    def test_first_use_directory_race_completes_both_bound_tasks(self):
        for same_actor in (False, True):
            with self.subTest(same_actor=same_actor):
                store = wb.Store(self.root / ("race-same" if same_actor else "race-distinct"), shared_v1=True)
                view = shared.SharedWorkspace(ws.Workspace(store, private_mode=True))
                inputs = FrozenInputs(store); descriptor = inputs.import_once(self.source)
                queue = jobs.SharedJobQueue(view, inputs, self.sha)
                accepted = [queue.enqueue({"command_id": f"race-command-{i}", "kind": "snapshot-brief",
                                           "snapshot_id": descriptor["snapshot_id"]}, actor)
                            for i, actor in enumerate((OWNER, OWNER if same_actor else MEMBER))]
                claims = [queue.claim(), queue.claim()]
                common = store.path.parent / "shared-jobs"
                barrier = threading.Barrier(2)
                original_mkdir = Path.mkdir
                results, errors = {}, []
                def synchronized_mkdir(path, *args, **kwargs):
                    if path == common: barrier.wait(timeout=5)
                    return original_mkdir(path, *args, **kwargs)
                def execute(claim):
                    try: results[claim["job_id"]] = queue.finish(claim, worker.run_attempt(claim))
                    except Exception as error: errors.append(repr(error))
                with mock.patch.object(Path, "mkdir", synchronized_mkdir):
                    threads = [threading.Thread(target=execute, args=(claim,)) for claim in claims]
                    for thread in threads: thread.start()
                    for thread in threads: thread.join(timeout=15)
                self.assertTrue(all(not thread.is_alive() for thread in threads))
                self.assertEqual(errors, [])
                self.assertEqual([results[item["job_id"]]["status"] for item in accepted], ["SUCCEEDED", "SUCCEEDED"])
                for claim in claims:
                    detail = queue.job(claim["job_id"])
                    for key in ("job_id", "workspace_id", "actor", "input_hash", "snapshot_id", "code_sha"):
                        self.assertEqual(detail[key], claim[key])
                self.assertEqual(queue.job(accepted[0]["job_id"])["output_hash"], queue.job(accepted[1]["job_id"])["output_hash"])

    def test_retained_worker_temporaries_survive_recovery_backup_restore(self):
        for phase in ("temporary_created", "temporary_fsynced", "seal_middle"):
            with self.subTest(phase=phase):
                store = wb.Store(self.root / phase, shared_v1=True)
                view = shared.SharedWorkspace(ws.Workspace(store, private_mode=True))
                inputs = FrozenInputs(store); descriptor = inputs.import_once(self.source)
                queue = jobs.SharedJobQueue(view, inputs, self.sha)
                accepted = queue.enqueue({"command_id": "fault-command-001", "kind": "snapshot-brief",
                                          "snapshot_id": descriptor["snapshot_id"]}, OWNER)
                crashed = subprocess.run([sys.executable, "-I", "-B", "-c", FAULT_SCRIPT,
                                          str(self.code), str(store.path.parent), descriptor["snapshot_id"], phase], capture_output=True, text=True)
                self.assertEqual(crashed.returncode, 77, crashed.stderr)
                partials = list((store.path.parent / "shared-jobs").rglob(".write-*.partial"))
                self.assertEqual(len(partials), 1)
                relative = partials[0].relative_to(store.path.parent).as_posix()
                raw = partials[0].read_bytes()
                self.assertEqual(bool(raw), phase != "temporary_created")
                queue.recover()
                claim = queue.claim(); self.assertIsNotNone(claim)
                self.assertEqual(queue.finish(claim, worker.run_attempt(claim))["status"], "SUCCEEDED")
                self.assertEqual(queue.job(accepted["job_id"])["input_hash"], descriptor["input_hash"])
                archive = self.root / (phase + "-backup")
                try: receipt = backup.backup_shared(store, archive)
                except ValueError as error: self.fail(f"retained service temporary must be backuppable: {error}")
                self.assertEqual(receipt["status"], "LOCAL_SHARED_BACKUP_VERIFIED")
                manifest = backup.verify_shared(archive)
                self.assertEqual(manifest["files"][relative], ev.sha(raw))
                self.assertTrue(any(relative in row.get("recovery_evidence", []) for row in manifest["artifact_inventory"]))
                source_files = {path.relative_to(store.path.parent).as_posix(): path.read_bytes()
                                for area in backup.ARTIFACT_ROOTS for path in (store.path.parent / area).rglob("*") if path.is_file()}
                self.assertEqual(set(manifest["files"]) - {"data.json"}, set(source_files))
                scratch = self.root / (phase + "-restored")
                self.assertEqual(backup.restore_shared(archive, scratch)["status"], "LOCAL_SHARED_RESTORE_VERIFIED")
                for name, original in source_files.items():
                    self.assertEqual((archive / name).read_bytes(), original)
                    self.assertEqual((scratch / name).read_bytes(), original)
                restored_files = {path.relative_to(scratch).as_posix()
                                  for area in backup.ARTIFACT_ROOTS - {"migration-evidence"}
                                  for path in (scratch / area).rglob("*") if path.is_file()}
                self.assertEqual(restored_files, set(source_files))
                self.assertEqual((scratch / relative).read_bytes(), raw)


if __name__ == "__main__": unittest.main(verbosity=2)
