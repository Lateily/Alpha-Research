"""Two synthetic actors, real frozen inputs/queue/render/seals, derived GETs."""
from __future__ import annotations
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts/llm"), str(ROOT / "tests")]
import test_workbench_data_catalog_http as fixtures
from test_workbench_data_catalog import attach, candidate_source
from workbench_shared_test_support import OWNER, MEMBER
from workbench_shared_worker import run_attempt
import workbench_backup as backup
import workbench_data_catalog as dc
import workbench_shared_workspace as shared
import nonprod_workbench as wb
from workbench_workspace import Workspace
from workbench_shared_inputs import FrozenInputs
from workbench_shared_jobs import SharedJobQueue
from unittest import mock
import workbench_evidence as ev


class VerticalTests(unittest.TestCase):
    setUp = fixtures.DataCatalogHttpTests.setUp
    get = fixtures.DataCatalogHttpTests.get

    def run_briefs(self):
        sid = self.envelope["snapshot_id"]
        jobs = []
        for actor, command in ((OWNER, "owner-data-brief-001"), (MEMBER, "member-data-brief-001")):
            result = self.view.dispatch({"command_id": command, "kind": "snapshot-brief", "snapshot_id": sid}, actor)
            jobs.append(result["job_id"])
        for _ in jobs:
            claim = self.queue.claim()
            result = run_attempt(claim)
            self.assertEqual(result["status"], "SUCCEEDED", result)
            self.queue.finish(claim, result)
        return jobs

    def test_two_actors_receive_same_input_but_separate_sealed_jobs(self):
        root = self.store.path.parent / "governance-evidence"
        attach(root, self.envelope)
        self.view.governance_evidence_enabled = True
        jobs = self.run_briefs()
        for actor in (OWNER, MEMBER):
            status, card = self.get("input-card/" + self.envelope["snapshot_id"], login=actor)
            self.assertEqual(status, 200)
            self.assertEqual(card["input_hash"], self.envelope["input_hash"])
            self.assertEqual(card["governance_status"], "ATTACHED_VERIFIED")
            status, index = self.get("materials?trade_date=20261015", login=actor)
            self.assertEqual(status, 200)
            reports = [row for row in index["rows"] if row["kind"] == "SEALED_BRIEF"]
            self.assertEqual({row["job_id"] for row in reports}, set(jobs))
            self.assertEqual({row["actor"] for row in reports}, {OWNER, MEMBER})
            for row in reports:
                detail = self.view.job(row["job_id"], actor)
                self.assertEqual(ev.sha(detail["report"].encode()), row["artifact_hash"])
                self.assertEqual(detail["input_hash"], self.envelope["input_hash"])
                self.assertEqual(detail["human_review"], "PENDING")

    def test_new_publication_and_queries_never_retarget_existing_reports(self):
        jobs = self.run_briefs()
        before = [self.view.job(job, OWNER) for job in jobs]
        source = self.root / "new-source"
        candidate_source(source, [{"ts_code": "600000.SH", "industry_key": "semiconductor"}],
                         rid="newer_publication", date="20261016")
        new = self.inputs.import_once(source)
        self.assertNotEqual(new["input_hash"], self.envelope["input_hash"])
        self.assertEqual(self.get("materials")[0], 200)
        after = [self.view.job(job, MEMBER) for job in jobs]
        for original, final in zip(before, after):
            for key in ("input_hash", "snapshot_id", "code_sha", "output_hash", "report"):
                self.assertEqual(final[key], original[key])

    def test_tampered_sealed_report_is_not_indexed_as_available(self):
        jobs = self.run_briefs()
        target = next(path for path in self.store.path.parent.rglob("report.md") if "shared-jobs" in str(path))
        target.write_text("synthetic corruption")
        status, result = self.get("materials")
        self.assertEqual(status, 409)
        self.assertNotIn("SEALED_BRIEF", str(result))

    def attached(self):
        root = self.store.path.parent / "governance-evidence"
        attach(root, self.envelope)
        self.view.governance_evidence_enabled = True
        return root

    def test_backup_restore_preserves_cards_queries_reports_and_attachments(self):
        self.attached()
        jobs = self.run_briefs()
        sid = self.envelope["snapshot_id"]
        card_before = self.view.input_card(sid, OWNER)
        index_before = self.view.materials(OWNER, industry_key="semiconductor")
        details = [self.view.job(job, OWNER) for job in jobs]
        archive = self.root / "portable-backup"
        try:
            result = backup.backup_shared(self.store, archive)
        except ValueError as error:
            self.fail("Registered attachments must be portable: " + str(error))
        self.assertEqual(result["status"], "LOCAL_SHARED_BACKUP_VERIFIED")
        self.assertFalse(result["credentials_included"])
        manifest = backup.verify_shared(archive)
        self.assertIn("governance-evidence/registry.json", manifest["files"])
        restored_root = self.root / "portable-restored"
        restored_result = backup.restore_shared(archive, restored_root)
        self.assertFalse(restored_result["owner_credentials_restored"])
        restored_store = wb.Store(restored_root, shared_v1=True)
        restored_view = shared.SharedWorkspace(Workspace(restored_store, private_mode=True), governance_evidence_enabled=True)
        SharedJobQueue(restored_view, FrozenInputs(restored_store), restored_view._execution_identity["code_sha"])
        with restored_store.connect() as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchall()[0][0], "ok")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM workspace_owner").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM shared_jobs").fetchone()[0], 2)
        self.assertEqual(FrozenInputs(restored_store).verify(sid)["input_hash"], self.envelope["input_hash"])
        for actor in (OWNER, MEMBER):
            card = restored_view.input_card(sid, actor)
            for key in ("input_hash", "source_run_id", "source_trade_date", "governance_status", "health_ref", "human_review"):
                self.assertEqual(card[key], card_before[key])
            self.assertEqual(restored_view.materials(actor, industry_key="semiconductor")["rows"], index_before["rows"])
            for before in details:
                after = restored_view.job(before["job_id"], actor)
                for key in ("actor", "workspace_id", "input_hash", "snapshot_id", "code_sha", "output_hash", "report"):
                    self.assertEqual(after[key], before[key])
        self.assertEqual(backup.verify_shared(archive)["event_tail"], result["event_tail"])

    def test_attachment_backup_refuses_missing_registry_foreign_binding_and_corruption(self):
        root = self.attached()
        registry_path = root / "registry.json"
        original = registry_path.read_bytes()
        registry_path.unlink()
        with self.assertRaises(ValueError): backup.backup_shared(self.store, self.root / "missing-registry")
        registry_path.write_bytes(original)
        registry = ev.parse(original)
        registry["bindings"]["00000000-0000-4000-8000-000000000000"] = next(iter(registry["bindings"].values()))
        registry_path.write_bytes(ev.canonical(registry).encode())
        with self.assertRaises(ValueError): backup.backup_shared(self.store, self.root / "foreign-binding")
        registry_path.write_bytes(original)
        unknown = root / "00000000-0000-4000-8000-000000000001"
        unknown.mkdir(mode=0o700)
        with self.assertRaises(ValueError): backup.backup_shared(self.store, self.root / "unregistered-bundle")
        unknown.rmdir()
        path = root / self.envelope["snapshot_id"] / "health.json"
        health = ev.parse(path.read_bytes()); health["status"] = "OK"
        path.write_bytes(ev.canonical(health).encode())
        with self.assertRaises(ValueError): backup.backup_shared(self.store, self.root / "corrupt-health")

    def test_resealed_backup_cannot_launder_false_attachment_health(self):
        self.attached()
        archive = self.root / "resealed-archive"
        backup.backup_shared(self.store, archive)
        sid = self.envelope["snapshot_id"]
        health_path = archive / "governance-evidence" / sid / "health.json"
        health = ev.parse(health_path.read_bytes()); health["status"] = "OK"
        health_path.write_bytes(ev.canonical(health).encode())
        registry_path = archive / "governance-evidence/registry.json"
        registry = ev.parse(registry_path.read_bytes())
        registry["bindings"][sid]["health_sha256"] = ev.sha(health_path.read_bytes())
        registry_path.write_bytes(ev.canonical(registry).encode())
        manifest_path = archive / "manifest.json"
        manifest = ev.parse(manifest_path.read_bytes())
        for path in (health_path, registry_path):
            manifest["files"][path.relative_to(archive).as_posix()] = ev.sha(path.read_bytes())
        manifest["backup_hash"] = ev.sealed({k: v for k, v in manifest.items() if k != "backup_hash"})
        manifest_path.write_bytes(ev.canonical(manifest).encode())
        with self.assertRaisesRegex(ValueError, "GOVERNANCE"):
            backup.restore_shared(archive, self.root / "forged-restored")

    def test_interrupted_attachment_restore_recovers_without_rewriting_history(self):
        self.attached(); jobs = self.run_briefs()
        archive = self.root / "recovery-backup"
        backup.backup_shared(self.store, archive)
        archive_bytes = {p.relative_to(archive): p.read_bytes() for p in archive.rglob("*") if p.is_file()}
        target = self.root / "recovered-state"
        import workbench_shared_state as state
        ensure = state._ensure
        def interrupted(path, raw, **kwargs):
            ensure(path, raw, **kwargs)
            if "governance-evidence" in path.parts and path.name == "health.json":
                raise RuntimeError("B6_AFTER_ATTACHMENT_WRITE")
        with mock.patch.object(state, "_ensure", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "B6_AFTER_ATTACHMENT_WRITE"):
                backup.restore_shared(archive, target)
        self.assertFalse(target.exists())
        result = backup.restore_shared(archive, target)
        self.assertEqual(result["status"], "LOCAL_SHARED_RESTORE_VERIFIED")
        self.assertEqual({p.relative_to(archive): p.read_bytes() for p in archive.rglob("*") if p.is_file()}, archive_bytes)
        restored_store = wb.Store(target, shared_v1=True)
        view = shared.SharedWorkspace(Workspace(restored_store, private_mode=True), governance_evidence_enabled=True)
        SharedJobQueue(view, FrozenInputs(restored_store), view._execution_identity["code_sha"])
        self.assertEqual(view.input_card(self.envelope["snapshot_id"], OWNER)["governance_status"], "ATTACHED_VERIFIED")
        self.assertEqual(view.job(jobs[0], MEMBER)["input_hash"], self.envelope["input_hash"])

    def test_historical_backup_without_attachment_stays_not_instrumented(self):
        archive = self.root / "no-attachment-backup"
        backup.backup_shared(self.store, archive)
        target = self.root / "no-attachment-restored"
        backup.restore_shared(archive, target)
        store = wb.Store(target, shared_v1=True)
        view = shared.SharedWorkspace(Workspace(store, private_mode=True), governance_evidence_enabled=True)
        card = view.input_card(self.envelope["snapshot_id"], OWNER)
        self.assertEqual(card["governance_status"], "NOT_ATTACHED")
        self.assertEqual(card["instrumentation_status"], "NOT_INSTRUMENTED")


if __name__ == "__main__": unittest.main()
