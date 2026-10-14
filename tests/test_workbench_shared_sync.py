"""S3 synthetic file/SQLite/loopback integration and behavior pins."""
import contextlib
import http.client as http_client
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts/llm"), str(ROOT / "tests")]
import nonprod_workbench as wb
import workbench_evidence as ev
import workbench_shared_inputs as frozen
import workbench_shared_workspace as shared
import workbench_workspace as ws
from workbench_shared_test_support import OWNER, MEMBER, committed_code, frozen_source, publisher_source, http

sync = __import__("workbench_shared_sync") if importlib.util.find_spec("workbench_shared_sync") else None


class SharedSyncTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(sync, "S3 ReadOnlySync is missing")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / "source"
        publisher_source(self.source)
        self.store = wb.Store(self.root / "state", shared_v1=True)
        self.system = ws.Workspace(self.store, private_mode=True)
        self.inputs = frozen.FrozenInputs(self.store)
        self.now = 1000.0
        self.poller = sync.ReadOnlySync(self.inputs, self.source, clock=lambda: self.now)
        self.addCleanup(self.poller.stop)

    def count(self):
        with self.store.connect() as db:
            return db.execute("SELECT COUNT(*) FROM shared_inputs").fetchone()[0]

    def test_new_publication_imported_once_within_poll_budget(self):
        self.poller.start()
        first = self.poller.state()
        self.assertEqual(first["status"], "SYNCED")
        self.assertEqual(first["actor"], "SYSTEM_READ_ONLY_SYNC")
        publisher_source(self.source, "publication_two", "20261014")
        self.now += 60
        began = time.monotonic()
        deadline = began + 120
        second = self.poller.state()
        while second["source_run_id"] != "publication_two" and time.monotonic() < deadline:
            time.sleep(.1)
            second = self.poller.state()
        elapsed = time.monotonic() - began
        self.assertNotEqual(second["current_snapshot_id"], first["current_snapshot_id"])
        self.assertEqual(second["source_run_id"], "publication_two")
        self.assertEqual(second["last_successful_sync_at"], self.now)
        self.assertEqual(self.count(), 2)
        self.assertLessEqual(elapsed + 5, 120)

    def test_unchanged_source_not_duplicated(self):
        first = self.poller.tick()
        before = {p.relative_to(self.root / "state").as_posix(): p.read_bytes()
                  for p in (self.root / "state/input-write-evidence").rglob("*") if p.is_file()}
        with mock.patch.object(self.inputs, "import_once", side_effect=AssertionError("unchanged import")):
            for _ in range(4):
                self.now += 60
                again = self.poller.tick()
        self.assertEqual(first["current_snapshot_id"], again["current_snapshot_id"])
        self.assertEqual(again["last_successful_sync_at"], first["last_successful_sync_at"])
        self.assertEqual(again["last_checked_at"], self.now)
        self.assertEqual(self.count(), 1)
        self.assertEqual(before, {p.relative_to(self.root / "state").as_posix(): p.read_bytes()
                                 for p in (self.root / "state/input-write-evidence").rglob("*") if p.is_file()})
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM workspace_events").fetchone()[0], 0)

    def test_new_failed_attempt_does_not_replace_last_publication(self):
        first = self.poller.tick()
        original = self.inputs.verify(first["current_snapshot_id"])
        path = self.source / frozen.ATTEMPT
        attempt = ev.parse(path.read_bytes()); attempt["run_id"] = "new_failed_attempt"
        path.write_bytes(ev.canonical(attempt).encode())
        self.now += 60
        result = self.poller.tick()
        current = self.inputs.verify(result["current_snapshot_id"])
        self.assertEqual(current["publication_fingerprint"], original["publication_fingerprint"])
        self.assertNotEqual(current["attempt_fingerprint"], original["attempt_fingerprint"])
        view = self.common()
        self.assertEqual(view["observation"]["run_identity"]["latest_attempt"]["run_id"], "new_failed_attempt")
        self.assertEqual(view["observation"]["run_identity"]["last_published"]["run_id"], "publisher_run")
        self.assertEqual(original["snapshot"]["records"][frozen.ATTEMPT]["payload"]["run_id"], "later_failed_attempt")
        self.assertEqual(len(list((self.inputs.base / "publications").iterdir())), 1)

    def common(self):
        if not hasattr(self, "view"):
            code = self.root / "code"
            committed_code(code, shared.EXECUTION_FILES)
            fixture_code = mock.patch.object(shared, "CODE_ROOT", code)
            fixture_code.start(); self.addCleanup(fixture_code.stop)
            self.view = shared.SharedWorkspace(self.system)
            from workbench_shared_jobs import SharedJobQueue
            SharedJobQueue(self.view, self.inputs, self.view._execution_identity["code_sha"])
            self.view.sync = self.poller
        return self.view.snapshot(OWNER)["common_data"]

    def test_missing_manifest_or_conflicting_identity_keeps_last_good_explicit(self):
        first = self.poller.tick()
        for broken in ("missing", "identity", "catalog"):
            publisher_source(self.source, "invalid_" + broken, "20261014")
            manifest = self.source / f"public/data/v2/runs/invalid_{broken}/manifest.json"
            if broken == "missing": manifest.unlink()
            elif broken == "identity":
                from workbench_shared_test_support import reseal_publisher
                reseal_publisher(self.source, "public/data/v2/meta.json", {"run_id": "other", "target_trade_date": "20261014"})
            else:
                from workbench_shared_test_support import reseal_publisher
                value = ev.parse(manifest.read_bytes()); value["artifacts"] = {}
                reseal_publisher(self.source, manifest.relative_to(self.source).as_posix(), value)
            self.now += 60
            result = self.poller.tick()
            self.assertEqual(result["status"], "SYNC_FAILED")
            self.assertEqual(result["current_snapshot_id"], first["current_snapshot_id"])
            self.assertEqual(result["last_successful_sync_at"], first["last_successful_sync_at"])
            common = self.common()
            self.assertIsNotNone(common["error"])
            self.assertEqual(common["observation"]["target_trade_date"], "20261012")
            self.assertEqual(common["sync"]["last_checked_at"], self.now)
            self.assertEqual(self.count(), 1)

    def test_pointer_aba_and_source_hash_change_refused(self):
        # Replace real source bytes after the frozen envelope has been staged.
        write = frozen._new_or_identical
        for attack in ("pointer", "aba", "file", "date", "catalog", "attempt"):
            with self.subTest(attack=attack):
                publisher_source(self.source, "race_" + attack)
                def racing_write(path, raw, **kwargs):
                    result = write(path, raw, **kwargs)
                    if path.parent.name == "envelopes":
                        pointer = self.source / frozen.POINTER
                        old = pointer.read_bytes()
                        if attack == "pointer": pointer.write_bytes(b'{}')
                        elif attack == "aba":
                            replacement = pointer.with_suffix(".replacement")
                            replacement.write_bytes(b'{}'); os.replace(replacement, pointer)
                            replacement.write_bytes(old); os.replace(replacement, pointer)
                        elif attack == "file": (self.source / "public/data/v2/meta.json").write_bytes(b'{}')
                        elif attack == "date":
                            value = ev.parse((self.source / "public/data/v2/meta.json").read_bytes())
                            value["target_trade_date"] = "20261015"
                            (self.source / "public/data/v2/meta.json").write_bytes(ev.canonical(value).encode())
                        elif attack == "attempt":
                            path = self.source / frozen.ATTEMPT
                            value = ev.parse(path.read_bytes()); value["run_id"] = "changed_after_capture"
                            path.write_bytes(ev.canonical(value).encode())
                        else:
                            manifest = self.source / "public/data/v2" / ev.parse(old)["manifest_path"]
                            value = ev.parse(manifest.read_bytes()); value["artifacts"] = {}
                            manifest.write_bytes(ev.canonical(value).encode())
                    return result
                with mock.patch.object(frozen, "_new_or_identical", side_effect=racing_write):
                    result = self.poller.tick()
                self.assertEqual(result["status"], "SYNC_FAILED")
                self.assertEqual(result["safe_error"], "SOURCE_CHANGED")
                self.assertIsNone(result["current_snapshot_id"])
                self.assertEqual(self.count(), 0)

    def test_gap_quality_not_zero_or_complete(self):
        self.poller.tick()
        common = self.common()
        view = common["observation"]
        self.assertIsNone(view["paper"]["cash"])
        self.assertIsNone(view["paper"]["nav_latest"])
        self.assertEqual(view["funnel"]["status"], "PARTIAL")
        self.assertEqual(view["macro"]["macro_panel"]["payload"]["status"], "DATA_BLOCKED")
        self.assertFalse(view["publication_verified"])
        self.assertEqual(common["validation_scope"], frozen.SCOPE)
        self.assertEqual(common["full_nightly_acceptance"], "NOT_EVALUATED")

    def test_symlink_unreadable_oversize_and_secret_source_refused(self):
        for unsafe in ("symlink", "unreadable", "oversize", "secret"):
            publisher_source(self.source, "unsafe_" + unsafe)
            path = self.source / "public/data/v2/meta.json"
            if unsafe == "symlink":
                path.unlink(); path.symlink_to(self.source / frozen.ATTEMPT)
            elif unsafe == "unreadable": path.chmod(0)
            elif unsafe == "oversize":
                with path.open("wb") as stream: stream.truncate(ev.MAX_FILE + 1)
            else: path.write_bytes(b'{"api_key":"synthetic-canary-only"}')
            try: result = self.poller.tick()
            finally:
                if unsafe == "unreadable": path.chmod(0o600)
            self.assertEqual(result["status"], "SYNC_FAILED", unsafe)
            self.assertEqual(self.count(), 0)
        for path in (self.root / "state").rglob("*"):
            if path.is_file(): self.assertNotIn(b"synthetic-canary-only", path.read_bytes())

    def test_source_tree_inode_mtime_hash_unchanged(self):
        (self.source / "must-not-open.sqlite3").write_bytes(b"synthetic database sentinel")
        def inventory():
            return {p.relative_to(self.source).as_posix(): (p.stat().st_ino, p.stat().st_mtime_ns,
                    ev.sha(p.read_bytes()) if p.is_file() else None) for p in [self.source, *self.source.rglob("*")]}
        before = inventory()
        read = ev.read_local
        def guarded(root, name):
            self.assertFalse(name.endswith((".sqlite3", "-wal", "-shm")))
            return read(root, name)
        with mock.patch.object(ev, "read_local", side_effect=guarded):
            self.poller.tick(); self.poller.tick()
        self.assertEqual(inventory(), before)

    def test_two_pollers_one_state_refused(self):
        self.poller.start()
        second = sync.ReadOnlySync(self.inputs, self.source)
        self.addCleanup(second.stop)
        with self.assertRaises(ws.WorkspaceError) as found: second.start()
        self.assertEqual(found.exception.code, "SYNC_POLLER_ALREADY_RUNNING")
        self.assertIsNotNone(self.poller.state()["current_snapshot_id"])
        self.poller.stop(); second.start(); second.stop()

    def test_capacity_blocks_without_deletion(self):
        first = self.poller.tick()
        before = (self.inputs.base / "envelopes" / (first["current_snapshot_id"] + ".json")).read_bytes()
        history = self.store.path.parent / "input-write-evidence"
        for index in range(99): (history / f"orphan-{index}").mkdir()
        publisher_source(self.source, "after_capacity")
        result = self.poller.tick()
        self.assertEqual(result["status"], "CAPACITY_BLOCKED")
        self.assertEqual(result["current_snapshot_id"], first["current_snapshot_id"])
        self.assertEqual(len(list(history.iterdir())), 100)
        self.assertEqual((self.inputs.base / "envelopes" / (first["current_snapshot_id"] + ".json")).read_bytes(), before)
        self.assertEqual(self.count(), 1)

    def test_resume_reads_latest_without_claiming_backfill(self):
        self.poller.start(); self.poller.stop()
        publisher_source(self.source, "missed_publication")
        publisher_source(self.source, "latest_after_resume", "20261014")
        resumed = sync.ReadOnlySync(self.inputs, self.source, clock=lambda: self.now)
        self.addCleanup(resumed.stop)
        resumed.start()
        state = resumed.state()
        self.assertEqual(state["source_run_id"], "latest_after_resume")
        self.assertEqual(state["missed_policy"], "NO_BACKFILL")
        self.assertEqual(self.count(), 2)

    def test_failed_staging_counts_against_capacity(self):
        write = frozen._new_or_identical
        def crash(path, raw, **kwargs):
            write(path, raw, **kwargs)
            if path.name == "capture.json": raise OSError("synthetic interruption")
        with mock.patch.object(frozen, "_new_or_identical", side_effect=crash): self.poller.tick()
        self.assertEqual(self.count(), 0)

        history = self.store.path.parent / "input-write-evidence"
        self.assertEqual(len(list(history.iterdir())), 1)
        for index in range(99): (history / f"failed-{index}").mkdir()
        publisher_source(self.source, "new_after_failed_staging")
        result = self.poller.tick()
        self.assertEqual(result["status"], "CAPACITY_BLOCKED")
        self.assertEqual(len(list(history.iterdir())), 100)
        self.assertEqual(self.count(), 0)

    def test_event_capacity_preserves_reserved_job_terminal_and_last_good(self):
        first = self.poller.tick(); self.common()
        self.view.queue.enqueue({"command_id": "reserved-s3-job", "kind": "snapshot-brief", "snapshot_id": first["current_snapshot_id"]}, OWNER)
        publisher_source(self.source, "capacity_publication")
        with mock.patch.object(ws, "MAX_EVENTS", 2): state = self.poller.tick()
        self.assertEqual(state["status"], "CAPACITY_BLOCKED")
        self.assertEqual(state["current_snapshot_id"], first["current_snapshot_id"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM workspace_events").fetchone()[0], 1)
        self.assertEqual(self.count(), 1)

    def test_default_and_private_legacy_have_no_sync(self):
        private = object()
        for options, identity in (([], None), ([], private), (["--read-only-auto-sync"], None),
                                  (["--read-only-auto-sync"], private),
                                  (["--shared-workspace-v1", "--read-only-auto-sync"], private)):
            with mock.patch.object(wb, "private_access", return_value=identity), \
                 mock.patch.object(wb, "load_assets", side_effect=RuntimeError("before runtime")), \
                 mock.patch.object(sync, "ReadOnlySync", side_effect=AssertionError("unexpected sync")):
                try:
                    wb.main(options)
                except wb.WorkbenchError as exc:
                    self.assertTrue(options)
                    self.assertEqual(exc.code, "READ_ONLY_SYNC_CONFIGURATION_REQUIRED")
                except RuntimeError:
                    self.assertFalse(options)
                except SystemExit:
                    self.fail("missing explicit S3 CLI option")
        self.common()
        allowlist = self.root / "cli-members.json"
        allowlist.write_text(json.dumps({"members": [MEMBER]})); allowlist.chmod(0o600)
        private = wb.private_access("https://workbench.test-tail.ts.net:8443", OWNER, allowlist)
        for mode in ("local", "private", "shared", "sync"):
            arguments = ["--state-root", str(self.root / ("cli-" + mode))]
            if mode in {"shared", "sync"}: arguments += ["--shared-workspace-v1"]
            if mode == "sync": arguments += ["--read-only-auto-sync", "--read-only-source-root", str(self.source)]
            server = mock.Mock()
            with mock.patch.object(wb, "private_access", return_value=None if mode == "local" else private), \
                 mock.patch.object(wb, "load_assets", return_value={"/": (b"fixture", "text/html")}), \
                 mock.patch.object(wb, "ThreadingHTTPServer", return_value=server), \
                 mock.patch.object(sync, "ReadOnlySync", wraps=sync.ReadOnlySync) as constructor, \
                 mock.patch("builtins.print"):
                self.assertEqual(wb.main(arguments), 0)
                self.assertEqual(constructor.call_count, int(mode == "sync"))
            server.server_close.assert_called_once()
            if mode == "sync":
                with wb.Store(self.root / "cli-sync", shared_v1=True).connect() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM shared_inputs").fetchone()[0], 1)
        self.assertFalse(any(thread.name == "read-only-shared-sync" for thread in threading.enumerate()))

    def test_sync_http_privilege_arguments_refused(self):
        self.poller.tick(); self.common()
        allowlist = self.root / "members.json"
        allowlist.write_text(json.dumps({"members": [MEMBER]})); allowlist.chmod(0o600)
        private = wb.private_access("https://workbench.test-tail.ts.net:8443", OWNER, allowlist)
        for key in ("source_root", "interval", "enable", "read_only_auto_sync", "actor"):
            status, _ = http(self.store, self.system, private, "/api/workspace/job",
                             {"command_id": "http-injection", "kind": "snapshot-brief",
                              "snapshot_id": self.poller.state()["current_snapshot_id"], key: "SYSTEM_READ_ONLY_SYNC"}, shared=self.view)
            self.assertEqual(status, 400)
        status, _ = http(self.store, self.system, private, "/api/shared-workspace?interval=1", shared=self.view)
        self.assertEqual(status, 400)
        self.assertEqual(self.view.queue.jobs(), [])

    def test_real_fifo_and_socket_are_bounded_refusals(self):
        code = "import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); import workbench_evidence as e; e.read_local(Path(sys.argv[2]),sys.argv[3])"
        (self.source / "regular.json").write_bytes(b'{}')
        os.mkfifo(self.source / "special.json", mode=0o600)
        bound = socket.socket(socket.AF_UNIX); self.addCleanup(bound.close)
        bound.bind(str(self.source / "socket.json"))
        for name in ("regular.json", "special.json", "socket.json"):
            try:
                result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(ROOT / "scripts/llm"),
                                         str(self.source), name], capture_output=True, timeout=2)
            except subprocess.TimeoutExpired:
                self.fail("special file blocked before type gate")
            self.assertEqual(result.returncode == 0, name == "regular.json")

    def test_source_root_and_state_overlap_refused(self):
        for root in (self.store.path.parent, self.root, self.store.path.parent / "nested"):
            with self.assertRaises(ws.WorkspaceError): sync.ReadOnlySync(self.inputs, root)
        parent = self.root / "linked"; parent.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)): sync.ReadOnlySync(self.inputs, parent)

    def test_failed_attempt_credentials_never_enter_common_display(self):
        self.poller.tick()
        path = self.source / frozen.ATTEMPT
        attempt = ev.parse(path.read_bytes())
        attempt["report"] = "Bearer synthetic-not-a-real-credential"
        path.write_bytes(ev.canonical(attempt).encode())
        state = self.poller.tick()
        self.assertEqual(state["status"], "SYNC_FAILED")
        self.assertNotIn("synthetic-not-a-real-credential", ev.canonical(self.common()))
        self.assertIsNone(state["latest_attempt"])

    def test_missing_pointer_still_displays_latest_safe_failed_attempt(self):
        first = self.poller.tick()
        path = self.source / frozen.ATTEMPT
        attempt = ev.parse(path.read_bytes()); attempt["run_id"] = "failed_without_pointer"
        path.write_bytes(ev.canonical(attempt).encode())
        (self.source / frozen.POINTER).unlink()
        state = self.poller.tick()
        self.assertEqual(state["current_snapshot_id"], first["current_snapshot_id"])
        self.assertEqual(self.common()["observation"]["run_identity"]["latest_attempt"]["run_id"], "failed_without_pointer")

    def test_poller_uses_real_sixty_second_monotonic_wait(self):
        class Waiter:
            def __init__(self): self.stopped = False; self.waits = []; self.waited = threading.Event()
            def is_set(self): return self.stopped
            def set(self): self.stopped = True
            def wait(self, seconds): self.waits.append(seconds); self.stopped = True; self.waited.set(); return True
        event = Waiter()
        poller = sync.ReadOnlySync(self.inputs, self.source, clock=lambda: -500, stop_event=event)
        with mock.patch.object(sync.time, "monotonic", return_value=10):
            poller.start(); self.assertTrue(event.waited.wait(2)); poller.stop()
        self.assertEqual(event.waits, [60])
        self.assertEqual(poller.state()["last_checked_at"], -500)

    def test_http_queue_frozen_render_keeps_running_job_pinned(self):
        from workbench_shared_worker import run_attempt
        first = self.poller.tick(); self.common()
        allowlist = self.root / "members.json"
        allowlist.write_text(json.dumps({"members": [MEMBER]})); allowlist.chmod(0o600)
        private = wb.private_access("https://workbench.test-tail.ts.net:8443", OWNER, allowlist)
        server = wb.ThreadingHTTPServer(("127.0.0.1", 0), wb.make_handler(self.store, {}, private.origin, "session", self.system, private, self.view))
        thread = threading.Thread(target=server.serve_forever); thread.start()
        try:
            def request(method, path, body=None, actor=OWNER):
                connection = http_client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
                try:
                    connection.request(method, path, body=None if body is None else ev.canonical(body), headers={
                        "Host": private.origin.split("//")[1], "Origin": private.origin,
                        "Tailscale-User-Login": actor, "Cookie": "ar_workbench=" + wb.private_session("session", actor),
                        "Content-Type": "application/json"})
                    response = connection.getresponse(); return response.status, json.loads(response.read())
                finally: connection.close()
            status, receipt = request("POST", "/api/workspace/job", {"command_id": "s3-http-brief", "kind": "snapshot-brief", "snapshot_id": first["current_snapshot_id"]})
            self.assertEqual(status, 202)
            claim = self.view.queue.claim()
            publisher_source(self.source, "publication_while_running", "20261014")
            self.poller.tick()
            status, common = request("GET", "/api/shared-workspace", actor=MEMBER)
            self.assertEqual(status, 200)
            self.assertEqual(common["common_data"]["observation"]["published_run_id"], "publication_while_running")
            self.source.rename(self.root / "offline-source")
            result = run_attempt(claim)
            self.assertEqual(result["status"], "SUCCEEDED")
            self.view.queue.finish(claim, result)
            status, detail = request("GET", "/api/shared-workspace/jobs/" + receipt["job_id"], actor=MEMBER)
            self.assertEqual(status, 200)
            self.assertEqual(detail["source_run_id"], "publisher_run")
            self.assertEqual(detail["input_hash"], claim["input_hash"])
            self.assertEqual(detail["output_hash"], ev.sha(detail["report"].encode()))
            self.assertEqual(detail["human_review"], "PENDING")
            self.assertNotIn("publication_while_running", detail["report"])
        finally:
            server.shutdown(); thread.join(); server.server_close()


if __name__ == "__main__": unittest.main()
