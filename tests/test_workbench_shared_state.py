"""Explicit migration and portable scrubbed state, never an in-use service."""
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/llm"))
sys.path.insert(0, str(ROOT / "tests"))
import nonprod_workbench as wb
import workbench_backup as backup
import workbench_evidence as ev
import workbench_workspace as ws
from workbench_shared_test_support import historical_state, frozen_source


@contextmanager
def interrupted_file_write(module, selected, phase, seen):
    """Interrupt real file I/O, preserving the created inode and written prefix."""
    write, fdopen, opened = module.write_new, backup.os.fdopen, backup.os.open
    paths = {}
    class InterruptedStream:
        def __init__(self, stream, path): self.stream, self.path = stream, path
        def __enter__(self): self.stream.__enter__(); return self
        def __exit__(self, *args): return self.stream.__exit__(*args)
        def __getattr__(self, name): return getattr(self.stream, name)
        def write(self, raw):
            seen["partial"] = self.path
            if phase != "after_creation":
                self.stream.write(raw[:8] if phase == "during_write" else raw)
            self.stream.flush(); backup.os.fsync(self.stream.fileno())
            raise RuntimeError("INJECTED_FILE_WRITE")
    def open_file(path, flags, *args, **kwargs):
        fd = opened(path, flags, *args, **kwargs)
        if flags & backup.os.O_CREAT: paths[fd] = Path(path)
        return fd
    def open_stream(fd, *args, **kwargs):
        stream = fdopen(fd, *args, **kwargs)
        return InterruptedStream(stream, paths[fd]) if fd in paths else stream
    def writer(path, raw, *args, **kwargs):
        if selected(Path(path)) and not seen:
            seen.update(destination=Path(path), raw=raw)
            with patch.object(backup.os, "open", side_effect=open_file), patch.object(backup.os, "fdopen", side_effect=open_stream):
                return write(path, raw, *args, **kwargs)
        return write(path, raw, *args, **kwargs)
    with patch.object(module, "write_new", side_effect=writer): yield


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store, self.system = historical_state(self.root)

    def state(self):
        self.assertIsNotNone(importlib.util.find_spec("workbench_shared_state"), "shared migration missing")
        import workbench_shared_state
        return workbench_shared_state

    def archived(self, name="backup"):
        self.assertTrue(hasattr(backup, "backup_shared"), "consistent shared backup missing")
        path = self.root / name
        backup.backup_shared(self.store, path)
        return path

    def test_sync_selection_backup_restores_reused_cursor(self):
        from workbench_shared_inputs import FrozenInputs
        from workbench_shared_sync import ReadOnlySync
        from workbench_shared_test_support import publisher_source
        source = self.root / "cursor-source"; publisher_source(source)
        store = wb.Store(self.root / "cursor-state", shared_v1=True)
        inputs = FrozenInputs(store); poller = ReadOnlySync(inputs, source)
        try:
            poller.start(); first = poller.state()
            publisher_source(source, "second_cursor", "20261014"); poller.tick()
            publisher_source(source); reused = poller.tick()
        finally: poller.stop()
        with store.connect() as db: before = ws.Workspace.events(None, db)
        self.assertEqual(len([e for e in before if e["kind"] == "SHARED_INPUT_SELECTED"]), 3)
        archive = self.root / "cursor-backup"; backup.backup_shared(store, archive)
        scratch = self.root / "cursor-restored"; backup.restore_shared(archive, scratch)
        restored = wb.Store(scratch, shared_v1=True)
        with restored.connect() as db: self.assertEqual(ws.Workspace.events(None, db), before)
        (source / "public/data/v2/current_run.json").unlink()
        state = ReadOnlySync(FrozenInputs(restored), source).tick()
        self.assertEqual(state["current_snapshot_id"], first["current_snapshot_id"])
        self.assertEqual(state["current_snapshot_id"], reused["current_snapshot_id"])
        self.assertEqual(state["status"], "SYNC_FAILED")

    def test_backup_refuses_selection_not_bound_to_registered_original(self):
        from workbench_shared_inputs import FrozenInputs
        from workbench_shared_sync import ReadOnlySync
        source = self.root / "bad-cursor-source"; frozen_source(source)
        store = wb.Store(self.root / "bad-cursor-state", shared_v1=True)
        inputs = FrozenInputs(store); first = ReadOnlySync(inputs, source).tick()
        system = ws.Workspace(store, private_mode=True)
        forged = {**inputs._descriptor(inputs.verify(first["current_snapshot_id"])), "input_hash": "f" * 64}
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            system.append(db, system.events(db), "synthetic_bad_selection", ev.sealed(forged), "SHARED_INPUT_SELECTED", forged, actor="SYSTEM_READ_ONLY_SYNC")
        with self.assertRaises(ValueError): backup.backup_shared(store, self.root / "bad-cursor-backup")
        self.assertFalse((self.root / "bad-cursor-backup").exists())

    def test_migration_preserves_event_chain_and_unknown_actor(self):
        state = self.state(); archive = self.archived()
        with self.store.connect() as db: before = db.execute("SELECT * FROM workspace_events ORDER BY seq").fetchall()
        result = state.migrate_legacy(archive, self.root / "target")
        restored = wb.Store(self.root / "target", shared_v1=True)
        with restored.connect() as db:
            self.assertEqual(before, db.execute("SELECT * FROM workspace_events ORDER BY seq").fetchall())
            self.assertEqual(db.execute("SELECT COUNT(*) FROM shared_workspaces").fetchone()[0], 0)
        jobs = result["legacy_jobs"]
        started = next(j for j in jobs if j["job_id"] == "started_brief")
        self.assertEqual((started["actor"], started["workspace_id"], started["status"]),
                         ("LEGACY_UNATTRIBUTED", None, "INTERRUPTED"))
        self.assertEqual(started["recovery"], "LEGACY_NOT_RECOVERABLE")
        for path in (self.store.path.parent / "snapshot-briefs").rglob("*"):
            if path.is_file(): self.assertEqual(path.read_bytes(), (restored.path.parent / path.relative_to(self.store.path.parent)).read_bytes())

    def test_migration_requires_new_target(self):
        state = self.state(); archive = self.archived()
        for target in (self.store.path.parent, archive, self.root / "existing"):
            target.mkdir(exist_ok=True)
            with self.assertRaises(ValueError): state.migrate_legacy(archive, target)

    def test_shared_backup_restore_includes_inputs_and_jobs(self):
        state = self.state()
        import workbench_shared_inputs as inputs
        src = self.root / "complete"; frozen_source(src)
        shared = wb.Store(self.root / "shared", shared_v1=True)
        item = inputs.FrozenInputs(shared).import_once(src)
        import workbench_shared_workspace as views
        from workbench_shared_jobs import SharedJobQueue
        from workbench_workspace import Workspace
        from workbench_shared_test_support import committed_code
        code = self.root / "queue-code"
        sha = committed_code(code, views.EXECUTION_FILES)
        with patch.object(views, "CODE_ROOT", code):
            view = views.SharedWorkspace(Workspace(shared, private_mode=True))
            queue = SharedJobQueue(view, inputs.FrozenInputs(shared), sha)
            queue.enqueue({"command_id": "queued_command", "kind": "observe", "snapshot_id": item["snapshot_id"]}, "known@example.invalid")
        archive = self.root / "shared-backup"; backup.backup_shared(shared, archive)
        scratch = self.root / "restored"; result = backup.restore_shared(archive, scratch)
        self.assertEqual(result["status"], "LOCAL_SHARED_RESTORE_VERIFIED")
        restored = wb.Store(scratch, shared_v1=True)
        self.assertEqual(inputs.FrozenInputs(restored).verify(item["snapshot_id"])["input_hash"], item["input_hash"])
        with restored.connect() as db:
            self.assertEqual(json.loads(db.execute("SELECT body FROM shared_jobs").fetchone()[0])["status"], "QUEUED")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM shared_workspaces").fetchone()[0], 1)

    def test_migration_crash_converges_without_rewriting_source(self):
        state = self.state(); archive = self.archived()
        source_bytes = self.store.path.read_bytes()
        archive_bytes = {p.relative_to(archive): p.read_bytes() for p in archive.rglob("*") if p.is_file()}
        original = state.write_new
        # Every actual persistent file write is crashed immediately after fsync.
        calls = []
        def record(path, raw, **kwargs): calls.append(str(path)); return original(path, raw, **kwargs)
        with patch.object(state, "write_new", side_effect=record): state.migrate_legacy(archive, self.root / "probe")
        self.assertGreater(len(calls), 5)
        for position in range(1, len(calls) + 1):
            target = self.root / f"crash-{position}"; counter = [0]
            def crash(path, raw, **kwargs):
                original(path, raw, **kwargs); counter[0] += 1
                if counter[0] == position: raise RuntimeError("injected crash")
            with patch.object(state, "write_new", side_effect=crash):
                with self.assertRaises(RuntimeError): state.migrate_legacy(archive, target)
            if target.exists():
                with self.assertRaises(ValueError): wb.Store(target, shared_v1=True)
            result = state.migrate_legacy(archive, target)
            self.assertEqual(result["status"], "SHARED_MIGRATION_VERIFIED")
            self.assertEqual(state.migrate_legacy(archive, target), result)
        for boundary in ("_build_state", "_promote"):
            target = self.root / boundary
            function = getattr(state, boundary)
            def crash_boundary(*args, **kwargs): function(*args, **kwargs); raise RuntimeError("injected crash")
            with patch.object(state, boundary, side_effect=crash_boundary):
                with self.assertRaises(RuntimeError): state.migrate_legacy(archive, target)
            staging = target.parent / ("." + target.name + ".migration")
            if staging.exists():
                with self.assertRaisesRegex(ValueError, "MIGRATION_STAGING_NOT_SERVABLE"):
                    wb.Store(staging, shared_v1=True)
            self.assertEqual(state.migrate_legacy(archive, target)["status"], "SHARED_MIGRATION_VERIFIED")
        self.assertEqual(self.store.path.read_bytes(), source_bytes)
        self.assertEqual({p.relative_to(archive): p.read_bytes() for p in archive.rglob("*") if p.is_file()}, archive_bytes)

    def test_legacy_stop_and_orphan_artifacts_are_accounted(self):
        state = self.state(); archive = self.archived()
        result = state.migrate_legacy(archive, self.root / "target")
        inventory = {r["path"]: r for r in result["artifact_inventory"]}
        for job, status in (("success_brief", "SUCCEEDED"), ("stopped_brief", "STOP"),
                            ("started_brief", "INTERRUPTED"), ("orphan_brief", "ORPHAN")):
            row = inventory["snapshot-briefs/" + job]
            self.assertEqual(row["status"], status)
            self.assertTrue(row["files"])
            self.assertEqual(row["source_backup_hash"], result["backup_hash"])

    def test_migration_binding_rejects_different_source(self):
        state = self.state(); first = self.archived("first")
        target = self.root / "target"; state.migrate_legacy(first, target)
        equivalent = self.root / "equivalent"
        shutil.copytree(first, equivalent)
        manifest = ev.parse((equivalent / "manifest.json").read_bytes())
        manifest["archive_label"] = "different-backup-identity"
        manifest["backup_hash"] = ev.sealed({k: v for k, v in manifest.items() if k != "backup_hash"})
        (equivalent / "manifest.json").write_bytes(ev.canonical(manifest).encode())
        with self.assertRaises(ValueError): state.migrate_legacy(equivalent, target)
        with self.store.connect() as db:
            self.system.append(db, self.system.events(db), "extra_event", "3" * 64, "PRIVATE_LOGIN", {"scope": "TEST"})
        second = self.archived("second")
        with self.assertRaisesRegex(ValueError, "MIGRATION_SOURCE_CONFLICT"): state.migrate_legacy(second, target)

    def test_backup_uses_consistent_sqlite_api_and_scrubs_credentials(self):
        self.state()
        with self.store.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA wal_autocheckpoint=0")
            self.system.append(db, self.system.events(db), "wal_only_event", "4" * 64, "PRIVATE_LOGIN", {"scope": "WAL_TEST"})
            db.commit()
            copied = self.root / "unsafe-file-copy.sqlite3"; shutil.copyfile(self.store.path, copied)
            with sqlite3.connect(copied) as unsafe:
                self.assertLess(unsafe.execute("SELECT COUNT(*) FROM workspace_events").fetchone()[0], 6)
            archive = self.archived()
        data = ev.parse((archive / "data.json").read_bytes())
        self.assertNotIn("workspace_owner", data["tables"])
        self.assertFalse(any(p.name in {"cookie.key", "allowlist.json"} or p.suffix == ".sqlite3" for p in archive.rglob("*")))
        manifest = backup.verify_shared(archive)
        self.assertEqual(manifest["integrity_check"], "ok")
        self.assertEqual(manifest["table_counts"]["workspace_events"], 6)
        self.assertEqual(data["tables"]["workspace_events"][-1][1], "wal_only_event")
        self.assertEqual(manifest["event_tail"], self.system.events(self.store.connect())[-1]["event_hash"])

    def test_backup_refuses_unsafe_or_missing_orphan_and_resealed_counts(self):
        self.state()
        link = self.store.path.parent / "snapshot-briefs/orphan_brief/unsafe.json"
        link.symlink_to(self.root / "source/public/data/v2/current_run.json")
        with self.assertRaises(ValueError): backup.backup_shared(self.store, self.root / "unsafe")
        link.unlink(); archive = self.archived()
        missing_archive = self.root / "missing-artifact"; shutil.copytree(archive, missing_archive)
        (missing_archive / "snapshot-briefs/orphan_brief/partial.json").unlink()
        with self.assertRaises(ValueError): backup.restore_shared(missing_archive, self.root / "missing-restore")
        manifest = ev.parse((archive / "manifest.json").read_bytes())
        manifest["table_counts"]["workspace_events"] = 0
        manifest["backup_hash"] = ev.sealed({k: v for k, v in manifest.items() if k != "backup_hash"})
        (archive / "manifest.json").write_bytes(ev.canonical(manifest).encode())
        with self.assertRaises(ValueError): backup.restore_shared(archive, self.root / "bad-restore")

    def test_s1_binary_refuses_persistent_schema_and_no_implicit_upgrade(self):
        self.state()
        new = wb.Store(self.root / "new", shared_v1=True)
        old_code = subprocess.check_output(["git", "show", "b30b1979cfc5edefd2291fb516f4c9d38a64597d:scripts/llm/nonprod_workbench.py"], cwd=ROOT)
        namespace = {"__name__": "historical_s1", "__file__": str(ROOT / "scripts/llm/nonprod_workbench.py")}
        exec(compile(old_code, namespace["__file__"], "exec"), namespace)
        with self.assertRaisesRegex(ValueError, "SHARED_SCHEMA_INCOMPATIBLE"):
            namespace["Store"](new.path.parent, shared_v1=True)
        s1 = self.root / "s1"; namespace["Store"](s1, shared_v1=True)
        raw = (s1 / "shared-workbench.sqlite3").read_bytes()
        with self.assertRaisesRegex(ValueError, "SHARED_SCHEMA_INCOMPATIBLE"): wb.Store(s1, shared_v1=True)
        self.assertEqual((s1 / "shared-workbench.sqlite3").read_bytes(), raw)

    def test_empty_stop_orphan_directories_are_preserved(self):
        state = self.state()
        path = self.store.path.parent / "snapshot-briefs/empty_orphan"
        path.mkdir()
        (self.store.path.parent / "snapshot-briefs/stopped_brief/empty_nested").mkdir()
        archive = self.archived(); target = self.root / "target"
        result = state.migrate_legacy(archive, target)
        self.assertTrue((target / "snapshot-briefs/empty_orphan").is_dir())
        self.assertTrue((target / "snapshot-briefs/stopped_brief/empty_nested").is_dir())
        self.assertEqual(next(row for row in result["artifact_inventory"] if row["path"] == "snapshot-briefs/empty_orphan")["status"], "ORPHAN")

    def test_backup_verifier_rejects_resealed_frozen_registry_conflict(self):
        self.state()
        import workbench_shared_inputs as inputs
        shared = wb.Store(self.root / "shared", shared_v1=True)
        src = self.root / "complete"; frozen_source(src)
        inputs.FrozenInputs(shared).import_once(src)
        archive = self.root / "archive"; backup.backup_shared(shared, archive)
        data = ev.parse((archive / "data.json").read_bytes())
        data["tables"]["shared_inputs"][0][1] = "0" * 64
        raw = ev.canonical(data).encode(); (archive / "data.json").write_bytes(raw)
        manifest = ev.parse((archive / "manifest.json").read_bytes())
        manifest["files"]["data.json"] = ev.sha(raw)
        manifest["backup_hash"] = ev.sealed({k: v for k, v in manifest.items() if k != "backup_hash"})
        (archive / "manifest.json").write_bytes(ev.canonical(manifest).encode())
        with self.assertRaises(ValueError): backup.verify_shared(archive)

    def test_limited_historical_export_blocks_complete_migration(self):
        state = self.state()
        result = backup.create(self.system, "old_format_backup")
        archive = self.store.path.parent / result["location"]
        before = (archive / "manifest.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "COMPLETE_INVENTORY_REQUIRED"):
            state.migrate_legacy(archive, self.root / "historical-target")
        self.assertFalse((self.root / "historical-target").exists())
        self.assertFalse((self.root / ".historical-target.migration").exists())
        self.assertEqual((archive / "manifest.json").read_bytes(), before)

    def test_complete_backup_shared_reconciles_legacy_omissions(self):
        state = self.state(); archive = self.archived("complete-reconciliation")
        target = self.root / "reconciled-target"
        source_raw = self.store.path.read_bytes()
        with patch.object(self.store, "connect", side_effect=AssertionError("MIGRATION_OPENED_OLD_SOURCE")):
            result = state.migrate_legacy(archive, target)
        self.assertEqual(result["status"], "SHARED_MIGRATION_VERIFIED")
        for name in ("stopped_brief", "started_brief", "orphan_brief"):
            path = "snapshot-briefs/" + name + "/partial.json"
            self.assertEqual((target / path).read_bytes(), (self.store.path.parent / path).read_bytes())
        self.assertEqual(self.store.path.read_bytes(), source_raw)
        self.assertEqual({row["status"] for row in result["artifact_inventory"]}, {"SUCCEEDED", "STOP", "INTERRUPTED", "ORPHAN"})

    def test_bound_migration_partial_file_writes_converge(self):
        state = self.state(); archive = self.archived()
        source_raw = self.store.path.read_bytes()
        for name in ("migration-intent.json", "snapshot-briefs/stopped_brief/partial.json", "migration-receipt.json"):
            for phase in ("after_creation", "during_write", "before_publish"):
                with self.subTest(name=name, phase=phase):
                    target = self.root / (name.replace("/", "-") + "-" + phase); seen = {}
                    with interrupted_file_write(state, lambda path: path.as_posix().endswith("/" + name), phase, seen):
                        with self.assertRaises(RuntimeError): state.migrate_legacy(archive, target)
                    self.assertFalse(target.exists())
                    self.assertFalse(seen["destination"].exists())
                    self.assertTrue(seen["partial"].is_file())
                    partial = seen["partial"].read_bytes()
                    stage = target.parent / ("." + target.name + ".migration")
                    with self.assertRaises(ValueError): wb.Store(stage, shared_v1=True)
                    result = state.migrate_legacy(archive, target)
                    self.assertEqual(result["status"], "SHARED_MIGRATION_VERIFIED")
                    self.assertEqual(state.migrate_legacy(archive, target), result)
                    moved_partial = target / seen["partial"].relative_to(stage)
                    self.assertEqual(moved_partial.read_bytes(), partial)
                    receipt = target / "migration-receipt.json"; receipt.write_bytes(b'{"broken')
                    with self.assertRaises(ValueError): state.migrate_legacy(archive, target)
                    self.assertEqual(receipt.read_bytes(), b'{"broken')
        self.assertEqual(self.store.path.read_bytes(), source_raw)

    def test_partial_intent_binding_refuses_different_backup(self):
        state = self.state(); first = self.archived("first-bound"); target = self.root / "bound-target"
        seen = {}
        with interrupted_file_write(state, lambda path: path.name == "migration-intent.json", "during_write", seen):
            with self.assertRaises(RuntimeError): state.migrate_legacy(first, target)
        second = self.root / "second-bound"; shutil.copytree(first, second)
        manifest = ev.parse((second / "manifest.json").read_bytes()); manifest["archive_label"] = "different-source"
        manifest["backup_hash"] = ev.sealed({k: v for k, v in manifest.items() if k != "backup_hash"})
        (second / "manifest.json").write_bytes(ev.canonical(manifest).encode())
        partial = seen["partial"].read_bytes()
        with self.assertRaisesRegex(ValueError, "MIGRATION_SOURCE_CONFLICT"): state.migrate_legacy(second, target)
        self.assertEqual(seen["partial"].read_bytes(), partial)
        self.assertEqual(state.migrate_legacy(first, target)["status"], "SHARED_MIGRATION_VERIFIED")

    def test_recovered_partial_evidence_is_preserved_by_complete_backup(self):
        state = self.state(); archive = self.archived(); target = self.root / "evidence-target"
        seen = {}
        with interrupted_file_write(state, lambda path: path.name == "migration-receipt.json", "during_write", seen):
            with self.assertRaises(RuntimeError): state.migrate_legacy(archive, target)
        stage = target.parent / ("." + target.name + ".migration")
        relative = seen["partial"].relative_to(stage)
        raw = seen["partial"].read_bytes()
        state.migrate_legacy(archive, target)
        exported = self.root / "evidence-backup"
        backup.backup_shared(wb.Store(target, shared_v1=True), exported)
        restored = self.root / "evidence-restored"; backup.restore_shared(exported, restored)
        self.assertEqual((restored / relative).read_bytes(), raw)
        self.assertTrue(any(row["status"] == "RECOVERY_EVIDENCE" for row in backup.verify_shared(exported)["artifact_inventory"]))

    def second_generation_archive(self):
        state = self.state()
        shared = wb.Store(self.root / "generation-source", shared_v1=True)
        first = self.root / "generation-A"; backup.backup_shared(shared, first)
        migrated = self.root / "generation-B"; seen = {}
        with interrupted_file_write(state, lambda path: path.name == "migration-receipt.json", "during_write", seen):
            with self.assertRaises(RuntimeError): state.migrate_legacy(first, migrated)
        state.migrate_legacy(first, migrated)
        archive = self.root / "generation-C"
        backup.backup_shared(wb.Store(migrated, shared_v1=True), archive)
        return archive, backup.verify_shared(archive)

    def test_second_generation_partial_receipt_retry_preserves_bound_history(self):
        state = self.state(); archive, manifest = self.second_generation_archive()
        before = {p.relative_to(archive): p.read_bytes() for p in archive.rglob("*") if p.is_file()}
        history = {name: (archive / name).read_bytes() for name in manifest["files"] if name.startswith("migration-evidence/")}
        self.assertTrue(history)
        for restore in (False, True):
            with self.subTest(restore=restore):
                target = self.root / ("generation-D-restore" if restore else "generation-D-migrate")
                migrate = backup.restore_shared if restore else state.migrate_legacy
                seen = {}
                with interrupted_file_write(state, lambda path: path.name == "migration-receipt.json", "during_write", seen):
                    with self.assertRaises(RuntimeError): migrate(archive, target)
                stage = target.parent / ("." + target.name + ".migration")
                partial = seen["partial"].read_bytes()
                self.assertEqual(len(partial), 8)
                self.assertFalse(target.exists())
                self.assertFalse(seen["destination"].exists())
                with self.assertRaisesRegex(ValueError, "MIGRATION_STAGING_NOT_SERVABLE"): wb.Store(stage, shared_v1=True)
                try: result = migrate(archive, target)
                except ValueError as exc: self.fail("identical second-generation retry refused: " + str(exc))
                self.assertEqual(result["status"], "LOCAL_SHARED_RESTORE_VERIFIED" if restore else "SHARED_MIGRATION_VERIFIED")
                self.assertEqual(result["backup_hash"], manifest["backup_hash"])
                self.assertEqual({name: (target / name).read_bytes() for name in history}, history)
                self.assertEqual((target / seen["partial"].relative_to(stage)).read_bytes(), partial)
                wb.Store(target, shared_v1=True)
                self.assertEqual(state.migrate_legacy(archive, target)["backup_hash"], manifest["backup_hash"])
        self.assertEqual({p.relative_to(archive): p.read_bytes() for p in archive.rglob("*") if p.is_file()}, before)

    def test_second_generation_missing_or_altered_history_is_not_healed(self):
        state = self.state(); archive, manifest = self.second_generation_archive()
        historical = next(name for name in manifest["files"] if name.startswith("migration-evidence/"))
        for damage in ("missing-file", "altered-file", "missing-directory", "extra-file", "extra-directory"):
            with self.subTest(damage=damage):
                target = self.root / ("history-" + damage); seen = {}
                with interrupted_file_write(state, lambda path: path.name == "migration-receipt.json", "during_write", seen):
                    with self.assertRaises(RuntimeError): state.migrate_legacy(archive, target)
                stage = target.parent / ("." + target.name + ".migration")
                path = stage / historical
                if damage == "missing-file": path.unlink()
                elif damage == "altered-file": path.write_bytes(b"altered-historical-evidence")
                elif damage == "missing-directory": shutil.rmtree(path.parent)
                elif damage == "extra-file": (path.parent / "unbound.partial").write_bytes(b"foreign")
                else: (path.parent / "unbound-directory").mkdir()
                before = {p.relative_to(stage): p.read_bytes() for p in stage.rglob("*") if p.is_file()}
                with self.assertRaisesRegex(ValueError, "MIGRATION_HISTORICAL_EVIDENCE_CONFLICT"):
                    state.migrate_legacy(archive, target)
                self.assertFalse(target.exists())
                self.assertEqual({p.relative_to(stage): p.read_bytes() for p in stage.rglob("*") if p.is_file()}, before)

    def test_second_generation_retry_refuses_foreign_or_different_current_source(self):
        state = self.state(); archive, manifest = self.second_generation_archive()
        different = self.root / "different-generation-C"; shutil.copytree(archive, different)
        other_manifest = {**manifest, "archive_label": "different-current-backup"}
        other_manifest["backup_hash"] = ev.sealed({k: v for k, v in other_manifest.items() if k != "backup_hash"})
        (different / "manifest.json").write_bytes(ev.canonical(other_manifest).encode())
        for foreign in (False, True):
            target = self.root / ("foreign-history" if foreign else "different-current"); seen = {}
            with interrupted_file_write(state, lambda path: path.name == "migration-receipt.json", "during_write", seen):
                with self.assertRaises(RuntimeError): state.migrate_legacy(archive, target)
            stage = target.parent / ("." + target.name + ".migration")
            if foreign:
                (stage / "migration-evidence" / ("f" * 64)).mkdir()
            before = {p.relative_to(stage): p.read_bytes() for p in stage.rglob("*") if p.is_file()}
            with self.assertRaisesRegex(ValueError, "MIGRATION_SOURCE_CONFLICT"):
                state.migrate_legacy(archive if foreign else different, target)
            self.assertFalse(target.exists())
            self.assertEqual({p.relative_to(stage): p.read_bytes() for p in stage.rglob("*") if p.is_file()}, before)

        target = self.root / "unbound-historical"; seen = {}
        with interrupted_file_write(state, lambda path: path.name == "migration-intent.json", "during_write", seen):
            with self.assertRaises(RuntimeError): state.migrate_legacy(archive, target)
        stage = target.parent / ("." + target.name + ".migration")
        historical_root = next(name for name in manifest["directories"] if name.startswith("migration-evidence/") and name.count("/") == 1)
        (stage / historical_root).mkdir()
        partial = seen["partial"].read_bytes()
        with self.assertRaisesRegex(ValueError, "MIGRATION_SOURCE_CONFLICT"):
            state.migrate_legacy(archive, target)
        self.assertFalse(target.exists())
        self.assertEqual(seen["partial"].read_bytes(), partial)

    def test_second_generation_interrupted_historical_file_restore_converges(self):
        state = self.state(); archive, manifest = self.second_generation_archive()
        historical = next(name for name in manifest["files"] if name.startswith("migration-evidence/"))
        target = self.root / "partial-history-restore"; seen = {}
        with interrupted_file_write(state, lambda path: path.as_posix().endswith("/" + historical), "during_write", seen):
            with self.assertRaises(RuntimeError): state.migrate_legacy(archive, target)
        stage = target.parent / ("." + target.name + ".migration")
        self.assertFalse((stage / "shared-workbench.sqlite3").exists())
        self.assertFalse(seen["destination"].exists())
        partial = seen["partial"].read_bytes()
        try: result = state.migrate_legacy(archive, target)
        except ValueError as exc: self.fail("incomplete historical restore refused: " + str(exc))
        self.assertEqual(result["status"], "SHARED_MIGRATION_VERIFIED")
        self.assertEqual((target / historical).read_bytes(), (archive / historical).read_bytes())
        self.assertEqual((target / seen["partial"].relative_to(stage)).read_bytes(), partial)

    def test_atomic_publish_hides_partial_file_and_never_replaces_committed_bytes(self):
        raw = b'{"status":"UNSEALED_TEST_EVIDENCE"}'
        for phase in ("after_creation", "during_write", "before_publish"):
            destination = self.root / (phase + ".json")
            evidence_root = self.root / "write-evidence" / ev.sha(raw)
            seen = {}
            with interrupted_file_write(backup, lambda path: path == destination, phase, seen):
                with self.assertRaises(RuntimeError): backup.write_new(destination, raw, evidence_root=evidence_root)
            self.assertFalse(destination.exists())
            partial = seen["partial"].read_bytes()
            backup.write_new(destination, raw, evidence_root=evidence_root)
            self.assertEqual(destination.read_bytes(), raw)
            self.assertEqual(seen["partial"].read_bytes(), partial)
            with self.assertRaises(FileExistsError): backup.write_new(destination, b"different", evidence_root=evidence_root)
            self.assertEqual(destination.read_bytes(), raw)
            destination.write_bytes(b"committed-corruption")
            with self.assertRaises(FileExistsError): backup.write_new(destination, raw, evidence_root=evidence_root)
            self.assertEqual(destination.read_bytes(), b"committed-corruption")

    def test_crash_each_schema_statement_and_directory_creation(self):
        state = self.state(); archive = self.archived()
        source_bytes = self.store.path.read_bytes()
        real_connect, real_build, real_mkdir = sqlite3.connect, state._build_state, Path.mkdir
        statements = []
        class Recording(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql.startswith(("CREATE ", "INSERT ")): statements.append(sql)
                return super().execute(sql, parameters)
        def recording_build(*args):
            with patch.object(sqlite3, "connect", side_effect=lambda *a, **k: real_connect(*a, **k, factory=Recording)):
                real_build(*args)
        with patch.object(state, "_build_state", side_effect=recording_build):
            state.migrate_legacy(archive, self.root / "sql-probe")
        self.assertGreater(len(statements), 25)
        for phase in ("before", "after"):
            for position in range(1, len(statements) + 1):
                target = self.root / f"sql-{phase}-{position}"; counter = [0]
                class Crashing(sqlite3.Connection):
                    def execute(self, sql, parameters=()):
                        writing = sql.startswith(("CREATE ", "INSERT "))
                        if writing: counter[0] += 1
                        if writing and counter[0] == position and phase == "before": raise RuntimeError("sql crash")
                        result = super().execute(sql, parameters)
                        if writing and counter[0] == position and phase == "after": raise RuntimeError("sql crash")
                        return result
                def crashing_build(*args):
                    with patch.object(sqlite3, "connect", side_effect=lambda *a, **k: real_connect(*a, **k, factory=Crashing)):
                        real_build(*args)
                with patch.object(state, "_build_state", side_effect=crashing_build):
                    with self.assertRaises(RuntimeError): state.migrate_legacy(archive, target)
                staging = target.parent / ("." + target.name + ".migration")
                with self.assertRaises(ValueError): wb.Store(staging, shared_v1=True)
                state.migrate_legacy(archive, target)
                self.assertEqual((target / "shared-workbench.sqlite3").stat().st_mode & 0o777, 0o600)
        for phase in ("before_commit", "after_commit"):
            target = self.root / phase
            class CommitCrashing(sqlite3.Connection):
                def __exit__(self, typ, value, trace):
                    if typ is None:
                        if phase == "before_commit":
                            super().__exit__(RuntimeError, RuntimeError("commit crash"), None)
                        else:
                            super().__exit__(typ, value, trace)
                        raise RuntimeError("commit crash")
                    return super().__exit__(typ, value, trace)
            def commit_crash_build(*args):
                with patch.object(sqlite3, "connect", side_effect=lambda *a, **k: real_connect(*a, **k, factory=CommitCrashing)):
                    real_build(*args)
            with patch.object(state, "_build_state", side_effect=commit_crash_build):
                with self.assertRaises(RuntimeError): state.migrate_legacy(archive, target)
            state.migrate_legacy(archive, target)
            self.assertEqual((target / "shared-workbench.sqlite3").stat().st_mode & 0o777, 0o600)
        dirs = []; probe = self.root / "dir-probe"; stage = self.root / ".dir-probe.migration"
        def record_mkdir(path, *args, **kwargs):
            if (path == stage or stage in path.parents) and not path.exists(): dirs.append(path)
            return real_mkdir(path, *args, **kwargs)
        with patch.object(Path, "mkdir", record_mkdir): state.migrate_legacy(archive, probe)
        for phase in ("before", "after"):
            for position in range(1, len(dirs) + 1):
                target = self.root / f"dir-{phase}-{position}"; stage = self.root / ("." + target.name + ".migration")
                counter = [0]
                def crash_mkdir(path, *args, **kwargs):
                    creating = (path == stage or stage in path.parents) and not path.exists()
                    if creating: counter[0] += 1
                    if creating and counter[0] == position and phase == "before": raise RuntimeError("directory crash")
                    result = real_mkdir(path, *args, **kwargs)
                    if creating and counter[0] == position and phase == "after": raise RuntimeError("directory crash")
                    return result
                with patch.object(Path, "mkdir", crash_mkdir):
                    with self.assertRaises(RuntimeError): state.migrate_legacy(archive, target)
                state.migrate_legacy(archive, target)
        self.assertEqual(self.store.path.read_bytes(), source_bytes)
        print(f"CRASH_MATRIX schema={len(statements)}x2 directories={len(dirs)}x2")

    def test_unclassified_orphan_or_credential_shaped_artifact_blocks_backup(self):
        self.state()
        unknown = self.store.path.parent / "unclassified-output"
        unknown.mkdir(); (unknown / "result.json").write_bytes(b"{}")
        with self.assertRaises(ValueError): backup.backup_shared(self.store, self.root / "unknown-backup")
        shutil.rmtree(unknown)
        path = self.store.path.parent / "snapshot-briefs/orphan_brief/partial.json"
        path.write_bytes(b'{"diagnostic":"Bearer fixture_token_123456"}')
        with self.assertRaises(ValueError): backup.backup_shared(self.store, self.root / "credential-backup")


if __name__ == "__main__": unittest.main(verbosity=2)
