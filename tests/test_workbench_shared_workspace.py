"""S1 ownership, source identity and legacy compatibility behavior pins."""
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/llm"))
sys.path.insert(0, str(ROOT / "tests"))
import nonprod_workbench as wb
import workbench_workspace as ws
import workbench_evidence as ev
import workbench_shared_test_support as support
from workbench_shared_test_support import OWNER, MEMBER, committed_code, fixture_state, http

spec = importlib.util.find_spec("workbench_shared_workspace")
shared = __import__("workbench_shared_workspace") if spec else None


class SharedWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(shared, "S1 shared workspace behavior is not implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.store, self.system = fixture_state(self.root)
        self.code = self.root / "code"
        self.sha = committed_code(self.code, shared.EXECUTION_FILES)
        patch = mock.patch.object(shared, "CODE_ROOT", self.code)
        patch.start(); self.addCleanup(patch.stop)
        self.view = shared.SharedWorkspace(self.system)
        allowlist = self.root / "members.json"
        allowlist.write_text(json.dumps({"members": [MEMBER]}))
        allowlist.chmod(0o600)
        self.private = wb.private_access("https://workbench.test-tail.ts.net:8443", OWNER, allowlist)
        for name in ("socket", "create_connection", "getaddrinfo"):
            guard = mock.patch.object(socket, name, side_effect=AssertionError("unexpected network"))
            guard.start(); self.addCleanup(guard.stop)

    def request(self, name="shared-job-001", kind="observe", actor=OWNER):
        return self.view.dispatch({"command_id": name, "kind": kind}, actor)

    def test_identity_stable_across_restart(self):
        first, second = self.view.identity(OWNER), self.view.identity(MEMBER)
        self.assertNotEqual(first["workspace_id"], second["workspace_id"])
        self.assertEqual(first["login"], OWNER)
        reopened = shared.SharedWorkspace(ws.Workspace(wb.Store(self.root / "state", shared_v1=True), private_mode=True))
        self.assertEqual(reopened.identity(OWNER), first)
        self.assertEqual(reopened.identity(MEMBER), second)
        with self.store.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE shared_workspaces SET workspace_id='replacement'")

    def test_my_view_filters_but_team_can_read_both(self):
        self.request("owner-observe-001")
        self.request("member-brief-001", "snapshot-brief", MEMBER)
        for actor, mine in ((OWNER, "owner-observe-001"), (MEMBER, "member-brief-001")):
            state = self.view.snapshot(actor)
            self.assertEqual(state["schema"], "ar.shared-workspace.v1")
            self.assertEqual([j["job_id"] for j in state["my_jobs"]], [mine])
            self.assertEqual({j["job_id"] for j in state["team_jobs"]}, {"owner-observe-001", "member-brief-001"})
            detail = self.view.job("member-brief-001", actor)
            self.assertEqual(detail["actor"], MEMBER)
            self.assertEqual(detail["workspace_id"], self.view.identity(MEMBER)["workspace_id"])
            self.assertEqual(detail["status"], "SUCCEEDED")
            self.assertIn("WORKFLOW_DEBUG", detail["report"])
            self.assertEqual(hashlib.sha256(detail["report"].encode()).hexdigest(), detail["output_hash"])
            self.assertNotIn("report", state["team_jobs"][0])
            self.assertNotIn("result", state["team_jobs"][0])
            self.assertEqual(detail["human_review"], "PENDING")
            self.assertFalse(detail["production_authority"])
            self.assertFalse(detail["trading_authority"])
        common = self.view.snapshot(OWNER)["common_data"]
        self.assertEqual(common["observation"]["run_identity"]["latest_attempt"]["run_id"], "failed-newer-run")
        self.assertFalse(common["observation"]["publication_verified"])

    def test_legacy_unattributed_is_preserved(self):
        with self.store.connect() as db:
            self.system.append(db, [], "legacy-job-001", ev.sealed("old"), "JOB_STARTED",
                               {"job_id": "legacy-job-001", "kind": "observe", "scheduled": False})
            before = db.execute("SELECT body FROM workspace_events").fetchall()
        state = self.view.snapshot(OWNER)
        self.assertEqual(state["my_jobs"], [])
        self.assertEqual(state["team_jobs"][0]["actor"], "LEGACY_UNATTRIBUTED")
        self.assertIsNone(state["team_jobs"][0]["workspace_id"])
        self.assertEqual(state["team_jobs"][0]["status"], "INTERRUPTED")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT body FROM workspace_events").fetchall(), before)

    def test_http_actor_and_workspace_injection_refused(self):
        for field in ("actor", "workspace_id", "path", "url", "provider", "code_sha", "source_tree_hash", "snapshot_id"):
            status, _ = http(self.store, self.system, self.private, "/api/workspace/job",
                             {"command_id": "forged-job-001", "kind": "observe", field: "forged"}, shared=self.view)
            self.assertIn(status, (400, 403))
        with self.store.connect() as db:
            self.assertEqual(len(self.system.events(db)), 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM workspace_observations").fetchone()[0], 0)
        status, state = http(self.store, self.system, self.private, "/api/shared-workspace", shared=self.view)
        self.assertEqual(status, 200)
        self.assertEqual(state["my_workspace"]["login"], OWNER)

    def test_http_verified_identity_and_detail(self):
        status, receipt = http(self.store, self.system, self.private, "/api/workspace/job",
                               {"command_id": "http-member-001", "kind": "snapshot-brief"}, login=MEMBER, shared=self.view)
        self.assertEqual(status, 200)
        self.assertEqual(receipt["status"], "SUCCEEDED")
        status, detail = http(self.store, self.system, self.private, "/api/shared-workspace/jobs/http-member-001", shared=self.view)
        self.assertEqual(status, 200)
        self.assertEqual(detail["actor"], MEMBER)
        for login, extra in (("stranger@example.com", ()), (OWNER, (("Tailscale-User-Login", MEMBER),)),
                             (OWNER, (("Host", "foreign"),)), (OWNER, (("Cookie", "bad"),))):
            status, _ = http(self.store, self.system, self.private, "/api/shared-workspace", login=login, extra=extra, shared=self.view)
            self.assertEqual(status, 403)
        status, _ = http(self.store, self.system, self.private, "/api/workspace", shared=self.view)
        self.assertEqual(status, 404)

    def test_other_actor_cannot_reuse_command(self):
        self.request()
        self.assertEqual(self.request()["disposition"], "IDEMPOTENT")
        for actor, kind in ((MEMBER, "observe"), (OWNER, "snapshot-brief")):
            with self.assertRaises(ws.WorkspaceError) as found:
                self.request(kind=kind, actor=actor)
            self.assertEqual(found.exception.status, 409)
        with self.store.connect() as db:
            self.assertEqual(len(self.system.events(db)), 2)

    def test_observe_metadata_identifies_the_actual_observation(self):
        self.request("observe-metadata-001")
        detail = self.view.job("observe-metadata-001", OWNER)
        self.assertEqual(detail["source_run_id"], "20260828_163504_test")
        self.assertEqual(detail["source_trade_date"], "20260828")
        self.assertEqual(detail["input_hash"], detail["result"]["snapshot_hash"])

    def test_default_mode_refuses_shared_state(self):
        normal = wb.Store(self.root / "normal")
        self.assertEqual(normal.probe({"command_id": "legacy-probe-001", "provider": "deepseek", "mode": "offline", "fixture": "contract-smoke"})["disposition"], "CREATED")
        before = (self.store.path.stat().st_ino, self.store.path.stat().st_mtime_ns, self.store.path.read_bytes())
        with self.assertRaises(wb.WorkbenchError) as found:
            wb.Store(self.root / "state")
        self.assertEqual(found.exception.code, "SHARED_STATE_FLAG_REQUIRED")
        self.assertTrue((self.root / "state/workbench.sqlite3").is_dir())
        self.assertEqual(list((self.root / "state/workbench.sqlite3").iterdir()), [])
        self.assertEqual((self.store.path.stat().st_ino, self.store.path.stat().st_mtime_ns, self.store.path.read_bytes()), before)

    def test_legacy_binary_cannot_open_shared_state(self):
        old = support.historical_script("pre-shared")
        script = self.root / "legacy.py"
        script.write_bytes(old)
        command = [sys.executable, "-B", "-c", "import runpy,sys; from pathlib import Path; m=runpy.run_path(sys.argv[1]); s=m['Store'](Path(sys.argv[2])); print(s.probe({'command_id':'legacy-probe-001','provider':'deepseek','mode':'offline','fixture':'contract-smoke'})['receipt']['result'])", str(script)]
        env = {**os.environ, "PYTHONPATH": str(ROOT / "scripts/llm")}
        positive = subprocess.run([*command, str(self.root / "legacy-normal")], env=env, capture_output=True, text=True)
        self.assertEqual(positive.returncode, 0, positive.stderr)
        self.assertIn("OFFLINE_CONTRACT_OK", positive.stdout)
        before = (self.store.path.stat().st_ino, self.store.path.stat().st_mtime_ns, self.store.path.read_bytes())
        negative = subprocess.run([*command, str(self.root / "state")], env=env, capture_output=True, text=True)
        self.assertNotEqual(negative.returncode, 0)
        self.assertIn("unable to open database file", negative.stderr)
        self.assertEqual((self.store.path.stat().st_ino, self.store.path.stat().st_mtime_ns, self.store.path.read_bytes()), before)

    def test_legacy_binary_portable_without_historical_git(self):
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            with mock.patch.object(subprocess, "check_output", side_effect=AssertionError("historical Git extraction unavailable")):
                self.test_legacy_binary_cannot_open_shared_state()
        finally:
            os.chdir(previous)

    def test_historical_fixture_full_bytes_and_integrity_fail_closed(self):
        self.assertTrue(hasattr(support, "historical_script"), "verified historical fixture loader missing")
        for name, digest in (("pre-shared", "56833b05d5ae622ad34f0357f6bbbb2a945caa9273d6999e098c305286750d25"),
                             ("s1", "2835ebb7da89ff9f202aff3513b903b6b7a2dfebd81d0002986afa2ae79f40ed")):
            with self.subTest(name=name):
                raw = support.historical_script(name)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
                isolated = self.root / name
                fixtures = isolated / "tests/fixtures/workbench-history"
                fixtures.mkdir(parents=True)
                path = fixtures / (name + ".py.txt")
                with mock.patch.object(support, "ROOT", isolated):
                    with self.assertRaisesRegex(ValueError, "HISTORICAL_FIXTURE_MISSING"):
                        support.historical_script(name)
                    path.write_bytes(raw)
                    self.assertEqual(support.historical_script(name), raw)
                    path.write_bytes(raw + b"\n# corrupted fixture\n")
                    with self.assertRaisesRegex(ValueError, "HISTORICAL_FIXTURE_CORRUPT"):
                        support.historical_script(name)

    def test_shared_mode_never_migrates_or_follows_links(self):
        old = wb.Store(self.root / "old")
        before = old.path.read_bytes()
        with self.assertRaises(wb.WorkbenchError) as found:
            wb.Store(self.root / "old", shared_v1=True)
        self.assertEqual(found.exception.code, "STATE_MIGRATION_REQUIRED")
        self.assertEqual(old.path.read_bytes(), before)
        for name in ("workbench.sqlite3", "shared-workbench.sqlite3"):
            target = self.root / (name + "-root")
            target.mkdir()
            (target / name).symlink_to(old.path)
            with self.assertRaises(wb.WorkbenchError):
                wb.Store(target, shared_v1=True)

    def test_code_identity_is_server_derived_and_dirty_code_refused(self):
        hashes = {name: hashlib.sha256((self.code / name).read_bytes()).hexdigest() for name in shared.EXECUTION_FILES}
        tree_hash = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(shared.execution_identity(self.code)["code_sha"], self.sha)
        self.request()
        detail = self.view.job("shared-job-001", OWNER)
        self.assertEqual(detail["code_sha"], self.sha)
        self.assertEqual(detail["source_tree_hash"], tree_hash)
        dirty = self.code / "scripts/llm/workbench_evidence.py"
        dirty.write_bytes(dirty.read_bytes() + b"\n# dirty execution code\n")
        with self.assertRaises(ws.WorkspaceError) as found:
            self.request("dirty-job-001")
        self.assertEqual(found.exception.code, "EXECUTION_CODE_DIRTY")
        with self.store.connect() as db:
            self.assertEqual(len(self.system.events(db)), 2)

    def test_running_executor_refuses_committed_execution_drift(self):
        self.request("pinned-job-001")
        changed = self.code / "scripts/llm/workbench_evidence.py"
        original = changed.read_text()
        replacement = original.replace("return hashlib.sha256(raw).hexdigest()", "return hashlib.sha256(b'changed-executor' + raw).hexdigest()")
        self.assertNotEqual(original, replacement)
        changed.write_text(replacement)
        subprocess.run(["git", "-C", str(self.code), "add", "--", "scripts/llm/workbench_evidence.py"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.code), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "genuine execution-code change"], check=True, capture_output=True)
        new_sha = subprocess.check_output(["git", "-C", str(self.code), "rev-parse", "HEAD"], text=True).strip()
        self.assertNotEqual(new_sha, self.sha)
        self.assertEqual(self.request("pinned-job-001")["disposition"], "IDEMPOTENT")
        self.assertEqual(self.view.job("pinned-job-001", OWNER)["code_sha"], self.sha)
        with self.assertRaises(ws.WorkspaceError) as found:
            self.request("drifted-new-job-001")
        self.assertEqual(found.exception.code, "EXECUTION_CODE_CHANGED_RESTART_REQUIRED")
        with self.store.connect() as db:
            self.assertEqual(len(self.system.events(db)), 2)

    def test_dirty_code_refused_at_executor_construction_but_retry_does_not_execute(self):
        self.request("pinned-dirty-001")
        changed = self.code / "scripts/llm/workbench_evidence.py"
        changed.write_bytes(changed.read_bytes() + b"\n# dirty execution bytes\n")
        try:
            retry = self.request("pinned-dirty-001")
        except ws.WorkspaceError as exc:
            self.fail("an idempotent query attempted dirty-code execution: " + exc.code)
        self.assertEqual(retry["disposition"], "IDEMPOTENT")
        with self.assertRaises(ws.WorkspaceError) as found:
            shared.SharedWorkspace(self.system)
        self.assertEqual(found.exception.code, "EXECUTION_CODE_DIRTY")
        with self.assertRaises(ws.WorkspaceError) as found:
            self.request("pinned-dirty-001", actor=MEMBER)
        self.assertEqual(found.exception.status, 409)

    def test_retained_view_staleness(self):
        result = subprocess.run(["node", "--test", str(ROOT / "tests/nonprod-workbench-shared.test.mjs")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_slow_poll_and_age_guards(self):
        result = subprocess.run(["node", "--test", str(ROOT / "tests/nonprod-workbench-shared.test.mjs")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_detail_revalidates_and_never_treats_ids_as_paths(self):
        self.request("sealed-brief-001", "snapshot-brief")
        workspace_id = self.view.identity(OWNER)["workspace_id"]
        output = self.root / "state/workspaces" / workspace_id / "snapshot-briefs/sealed-brief-001/report.md"
        output.write_text("changed")
        detail = self.view.job("sealed-brief-001", MEMBER)
        self.assertEqual(detail["status"], "STOP")
        self.assertNotIn("report", detail)
        for job_id in ("../sealed-brief-001", "unknown-job-001", "/etc/passwd"):
            with self.assertRaises(ws.WorkspaceError):
                self.view.job(job_id, OWNER)

    def test_metadata_pages_are_bounded(self):
        with self.store.connect() as db:
            events = []
            for number in range(55):
                event = self.system.append(db, events, f"historic-job-{number:03d}", ev.sealed(number), "JOB_STARTED",
                                           {"job_id": f"historic-job-{number:03d}", "kind": "observe"}, actor=OWNER)
                events.append(event)
        self.assertEqual(len(self.view.snapshot(OWNER)["team_jobs"]), 50)
        status, state = http(self.store, self.system, self.private, "/api/shared-workspace?page=1", shared=self.view)
        self.assertEqual(status, 200)
        self.assertEqual(len(state["team_jobs"]), 5)

    def test_latest_owned_job_is_not_replaced_by_an_old_page(self):
        with self.store.connect() as db:
            events = []
            for number in range(55):
                event = self.system.append(db, events, f"historic-brief-{number:03d}", ev.sealed(number), "JOB_STARTED",
                                           {"job_id": f"historic-brief-{number:03d}", "kind": "snapshot-brief"}, actor=OWNER)
                events.append(event)
        state = self.view.snapshot(OWNER, page=1)
        self.assertEqual(state.get("latest_owned_jobs", [{}])[0].get("job_id"), "historic-brief-054")

    def test_dirty_transitive_execution_dependency_refused(self):
        name = "experiments/macro_os/storage.py"
        path = self.code / name
        if not path.exists():
            shutil.copyfile(ROOT / name, path)
            subprocess.run(["git", "-C", str(self.code), "add", "--", name], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(self.code), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "transitive fixture"], check=True, capture_output=True)
        path.write_bytes(path.read_bytes() + b"\n# dirty dependency\n")
        with self.assertRaises(ws.WorkspaceError) as found:
            self.request("dirty-transitive-001")
        self.assertEqual(found.exception.code, "EXECUTION_CODE_DIRTY")

    def test_reading_missing_workspace_output_never_recreates_it(self):
        self.request("missing-output-001", "snapshot-brief")
        output = self.root / "state/workspaces" / self.view.identity(OWNER)["workspace_id"]
        shutil.rmtree(output)
        self.assertEqual(self.view.job("missing-output-001", MEMBER)["status"], "STOP")
        self.assertFalse(output.exists(), "a read-only query recreated missing artifact state")

    def test_shared_requires_private_mode(self):
        with self.assertRaises(ws.WorkspaceError):
            shared.SharedWorkspace(ws.Workspace(self.store))
        with mock.patch.object(wb, "load_assets", side_effect=AssertionError("must reject before assets/state")):
            with self.assertRaises(wb.WorkbenchError) as found:
                wb.main(["--shared-workspace-v1", "--state-root", str(self.root / "not-created")])
        self.assertEqual(found.exception.code, "SHARED_PRIVATE_MODE_REQUIRED")
        self.assertFalse((self.root / "not-created").exists())

    def test_latest_owned_failure(self):
        result = subprocess.run(["node", "--test", str(ROOT / "tests/nonprod-workbench-shared.test.mjs")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
