"""Portable capacity and corruption regressions; synthetic history only."""
import hashlib
import importlib
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/llm"))
sys.path.insert(0, str(ROOT / "tests"))
import workbench_backup as backup
import workbench_evidence as ev
from workbench_shared_test_support import historical_state
from workbench_shared_state import ALL_TABLES


class ChunkedBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def codec(self):
        self.assertIsNotNone(importlib.util.find_spec("workbench_backup_chunks"))
        return importlib.import_module("workbench_backup_chunks")

    def archive(self):
        store, _system = historical_state(self.root)
        archive = self.root / "archive"
        backup.backup_shared(store, archive)
        manifest, data = backup.read_shared(archive)
        files = self.codec().encode(data["tables"])
        for name, raw in files.items():
            path = archive / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(raw)
        manifest["schema"] = "ar-shared-workspace-backup.v2"
        manifest["files"].update({name: ev.sha(raw) for name, raw in files.items()})
        self.save_manifest(archive, manifest)
        return archive

    def save_manifest(self, archive, manifest):
        manifest["backup_hash"] = ev.sealed({k: v for k, v in manifest.items() if k != "backup_hash"})
        (archive / "manifest.json").write_bytes(ev.canonical(manifest).encode())

    def change_index(self, archive, change):
        manifest = ev.parse((archive / "manifest.json").read_bytes())
        index = ev.parse((archive / "data.json").read_bytes())
        change(index)
        index["index_hash"] = ev.sealed({k: v for k, v in index.items() if k != "index_hash"})
        raw = ev.canonical(index).encode()
        (archive / "data.json").write_bytes(raw)
        manifest["files"]["data.json"] = ev.sha(raw)
        self.save_manifest(archive, manifest)

    def change_chunk(self, archive, change, *, reseal=True):
        manifest = ev.parse((archive / "manifest.json").read_bytes())
        index = ev.parse((archive / "data.json").read_bytes())
        descriptor = index["tables"]["workspace_events"][0]
        body = ev.parse((archive / descriptor["path"]).read_bytes())
        change(body)
        if reseal:
            body["chunk_hash"] = ev.sealed({k: v for k, v in body.items() if k != "chunk_hash"})
        raw = ev.canonical(body).encode()
        (archive / descriptor["path"]).write_bytes(raw)
        descriptor.update(bytes=len(raw), sha256=ev.sha(raw))
        manifest["files"][descriptor["path"]] = ev.sha(raw)
        index["total_bytes"] = sum(d["bytes"] for ds in index["tables"].values() for d in ds)
        index["index_hash"] = ev.sealed({k: v for k, v in index.items() if k != "index_hash"})
        raw_index = ev.canonical(index).encode()
        (archive / "data.json").write_bytes(raw_index)
        manifest["files"]["data.json"] = ev.sha(raw_index)
        self.save_manifest(archive, manifest)

    def assert_refused_before_restore(self, archive, reason=None):
        target = self.root / "refused-state"
        with self.assertRaises((ValueError, OSError)) as caught:
            backup.restore_shared(archive, target)
        if reason:
            self.assertIn(reason, str(caught.exception))
        self.assertFalse(target.exists())
        self.assertFalse((self.root / ".refused-state.migration").exists())

    def test_small_v1_export_and_restore_remain_compatible(self):
        store, _ = historical_state(self.root)
        archive = self.root / "small"
        result = backup.backup_shared(store, archive)
        manifest, data = backup.read_shared(archive)
        self.assertEqual(manifest["schema"], "ar-shared-workspace-backup.v1")
        self.assertEqual(ev.parse((archive / "data.json").read_bytes()), data)
        self.assertEqual(backup.restore_shared(archive, self.root / "new")["backup_hash"], result["backup_hash"])

    def test_chunk_missing_extra_and_byte_tamper_are_rejected(self):
        good = self.archive()
        name = next(p for p in (good / "data-chunks").iterdir())
        for mode in ("missing", "extra", "tamper", "symlink"):
            with self.subTest(mode=mode):
                archive = self.root / mode
                shutil.copytree(good, archive)
                chosen = archive / "data-chunks" / name.name
                if mode == "missing": chosen.unlink()
                elif mode == "extra": (archive / "data-chunks/unknown.json").write_bytes(b"{}")
                elif mode == "tamper": chosen.write_bytes(b"{}")
                else:
                    chosen.unlink()
                    chosen.symlink_to(name)
                self.assert_refused_before_restore(archive)

    def test_resealed_order_span_and_path_contradictions_are_rejected(self):
        good = self.archive()
        changes = {
            "ordinal": lambda i: i["tables"]["workspace_events"][0].update(index=1),
            "span": lambda i: i["tables"]["workspace_events"][0].update(row_start=1),
            "path": lambda i: i["tables"]["workspace_events"][0].update(path="data-chunks/../data.json"),
            "table": lambda i: i["tables"]["workspace_events"][0].update(table="receipts"),
            "boolean": lambda i: i["tables"]["workspace_events"][0].update(index=False),
        }
        for mode, change in changes.items():
            with self.subTest(mode=mode):
                archive = self.root / mode
                shutil.copytree(good, archive)
                self.change_index(archive, change)
                self.assert_refused_before_restore(archive, "CHUNK_")

    def test_resealed_aggregate_and_table_counts_are_rejected(self):
        good = self.archive()
        changes = {
            "chunks": lambda i: i.update(chunk_count=i["chunk_count"] + 1),
            "rows": lambda i: i.update(row_count=i["row_count"] + 1),
            "bytes": lambda i: i.update(total_bytes=i["total_bytes"] + 1),
            "table": lambda i: i["table_counts"].update(workspace_events=1),
            "oversize": lambda i: i["tables"]["workspace_events"][0].update(bytes=12582913),
            "unknown": lambda i: i["tables"].update(unregistered=[]),
        }
        for mode, change in changes.items():
            with self.subTest(mode=mode):
                archive = self.root / mode
                shutil.copytree(good, archive)
                self.change_index(archive, change)
                self.assert_refused_before_restore(archive, "CHUNK_")

    def test_rehashed_chunk_still_requires_inner_seal(self):
        archive = self.archive()
        self.change_chunk(archive, lambda c: c.update(chunk_hash="0" * 64), reseal=False)
        self.assert_refused_before_restore(archive, "CHUNK_SEAL_INVALID")

    def test_rehashed_index_still_requires_inner_seal(self):
        archive = self.archive()
        manifest = ev.parse((archive / "manifest.json").read_bytes())
        index = ev.parse((archive / "data.json").read_bytes())
        index["index_hash"] = "0" * 64
        raw = ev.canonical(index).encode()
        (archive / "data.json").write_bytes(raw)
        manifest["files"]["data.json"] = ev.sha(raw)
        self.save_manifest(archive, manifest)
        self.assert_refused_before_restore(archive, "CHUNK_INDEX_INVALID")

    def test_resealed_credential_row_is_not_restorable(self):
        archive = self.archive()
        def credential_row(chunk):
            event = ev.parse(chunk["rows"][0][3])
            event["data"]["diagnostic"] = "Bearer fixture_token_123456"
            event["event_hash"] = ev.sealed({k: v for k, v in event.items() if k != "event_hash"})
            chunk["rows"][0][3] = ev.canonical(event)
        self.change_chunk(archive, credential_row)
        self.assert_refused_before_restore(archive, "CREDENTIAL_SHAPED_CONTENT_REFUSED")

    def test_resealed_descriptor_and_body_cannot_move_chunk_ordinal(self):
        archive = self.archive()
        self.change_chunk(archive, lambda c: c.update(index=1))
        self.change_index(archive, lambda i: i["tables"]["workspace_events"][0].update(index=1))
        self.assert_refused_before_restore(archive, "CHUNK_ORDER_OR_SPAN_INVALID")

    def test_declared_overflow_rejected_before_chunk_files_are_read(self):
        archive = self.archive()
        self.change_index(archive, lambda i: i.update(total_bytes=268435457))
        original = ev.read_local
        def read_without_chunks(root, name):
            if str(name).startswith("data-chunks/"):
                raise OSError("CHUNK_IO_BEFORE_BOUNDS_CHECK")
            return original(root, name)
        with patch.object(ev, "read_local", side_effect=read_without_chunks):
            self.assert_refused_before_restore(archive, "CHUNK_COUNT_OR_SIZE_INVALID")

    def test_rehashed_chunk_requires_actual_declared_byte_count(self):
        archive = self.archive()
        def wrong_size(index):
            index["tables"]["workspace_events"][0]["bytes"] += 1
            index["total_bytes"] += 1
        self.change_index(archive, wrong_size)
        self.assert_refused_before_restore(archive, "CHUNK_BYTES_OR_HASH_INVALID")

    def test_resealed_chunk_body_identity_and_row_count_are_rejected(self):
        good = self.archive()
        changes = {
            "table": lambda c: c.update(table="drafts"),
            "ordinal": lambda c: c.update(index=1),
            "span": lambda c: c.update(row_start=1),
            "count": lambda c: c["rows"].pop(),
        }
        for mode, change in changes.items():
            with self.subTest(mode=mode):
                archive = self.root / mode
                shutil.copytree(good, archive)
                self.change_chunk(archive, change)
                self.assert_refused_before_restore(archive, "CHUNK_ROW_BINDING_INVALID")

    def test_duplicate_primary_identity_refused_even_with_resealed_chunks(self):
        codec = self.codec()
        tables = {name: [] for name in ALL_TABLES}
        tables["drafts"] = [[1, "{}"], [1, '{"other":true}']]
        files = codec.encode(tables)
        archive = self.root / "duplicate"
        archive.mkdir()
        for name, raw in files.items():
            path = archive / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(raw)
        index = ev.parse(files["data.json"])
        failure = None
        try:
            codec.decode(archive, index, {name: ev.sha(raw) for name, raw in files.items()}, ALL_TABLES)
        except ValueError as exc:
            failure = str(exc)
        self.assertEqual(failure, "BACKUP_CHUNK_DUPLICATE_ROW")

    def test_chunk_bounds_refuse_row_total_and_chunk_overflow(self):
        codec = self.codec()
        tables = {name: [] for name in ALL_TABLES}
        tables["drafts"] = [[i, ev.canonical({"note": "offline-note-" * 30})] for i in range(5)]
        for limit, value in (("MAX_ROWS", 4), ("MAX_EXPORT_BYTES", 100), ("MAX_CHUNKS", 1)):
            with self.subTest(limit=limit), patch.object(codec, limit, value), patch.object(codec, "CHUNK_TARGET_BYTES", 700):
                failure = None
                try: codec.encode(tables)
                except ValueError as exc: failure = str(exc)
                self.assertIsNotNone(failure, "overflow must fail closed")
        tables["drafts"] = [[1, "offline-note-" * (12582912 // 13 + 1)]]
        with self.assertRaisesRegex(ValueError, "CHUNK_ROW_SIZE_LIMIT"):
            codec.encode(tables)

    def test_chunk_restore_interruptions_preserve_archive_and_recover(self):
        import workbench_shared_state as state
        archive = self.archive()
        before = {p.relative_to(archive): p.read_bytes() for p in archive.rglob("*") if p.is_file()}
        original, writes = state.write_new, []
        def recording(path, raw, **kwargs):
            writes.append(Path(path).name)
            return original(path, raw, **kwargs)
        with patch.object(state, "write_new", side_effect=recording):
            state.migrate_legacy(archive, self.root / "probe")
        self.assertGreater(len(writes), 5)
        for position in range(1, len(writes) + 1):
            target = self.root / ("crash-%02d" % position)
            calls = [0]
            def crash(path, raw, **kwargs):
                original(path, raw, **kwargs)
                calls[0] += 1
                if calls[0] == position: raise RuntimeError("injected-after-write")
            with patch.object(state, "write_new", side_effect=crash):
                with self.assertRaises(RuntimeError): state.migrate_legacy(archive, target)
            self.assertFalse(target.exists())
            self.assertEqual(state.migrate_legacy(archive, target)["status"], "SHARED_MIGRATION_VERIFIED")
            self.assertFalse((target / "data-chunks").exists())
        self.assertEqual(before, {p.relative_to(archive): p.read_bytes() for p in archive.rglob("*") if p.is_file()})

    def test_v2_preservation_reopens_all_chunks_and_keeps_authority_closed(self):
        import foundation_preservation as preservation
        archive = self.archive()
        expected = backup.verify_shared(archive)["backup_hash"]
        manifest = preservation.build_preservation_manifest([
            {"package_id": "chunked-backup", "kind": "SHARED_BACKUP", "local_root": archive,
             "expected_content_hash": expected}], created_at="2026-11-02T18:10:00Z")
        self.assertFalse(manifest["production_authority"])
        self.assertFalse(manifest["deployment_authority"])
        checked = preservation.verify_preservation_copy(manifest, {"chunked-backup": archive},
            expected_preservation_hash=manifest["preservation_hash"])
        self.assertEqual(checked["package_bytes"], "MATCH")
        self.assertEqual(checked["verification_scope"], "PACKAGE_BYTES_AND_ORIGINAL_VALIDATORS_ONLY")
        self.assertEqual(checked["preservation_hash"], manifest["preservation_hash"])

    def test_v2_retention_keeps_historical_report_seals(self):
        import foundation_retention as retention
        archive = self.archive()
        expected = backup.verify_shared(archive)["backup_hash"]
        pin = retention.build_retention_pin(archive, expected_backup_hash=expected,
            snapshot_ids=[], job_ids=["success_brief"], created_at="2026-11-02T18:10:00Z")
        self.assertEqual(pin["backup"]["schema"], "ar-shared-workspace-backup.v2")
        self.assertEqual(pin["jobs"][0]["status"], "SUCCEEDED")
        self.assertFalse(pin["production_authority"])
        self.assertEqual(retention.verify_retention_pin(pin, archive, expected_backup_hash=expected), pin)

    def test_actual_size_history_roundtrip_preserves_every_row_and_artifact(self):
        store, system = historical_state(self.root)
        note = "offline historical material " * 80000
        with store.connect() as db:
            events = system.events(db)
            for number in range(11):
                event = system.append(db, events, "retained_%02d" % number, "a" * 64,
                                      "PRIVATE_LOGIN", {"note": note, "number": number})
                events.append(event)
            present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            expected = {table: [list(row) for row in db.execute(
                "SELECT " + ", ".join(columns) + " FROM " + table + " ORDER BY rowid")]
                if table in present else [] for table, columns in ALL_TABLES.items()}
        export_size = len(ev.canonical({"schema": "ar-shared-workspace-data-export.v1", "tables": expected}).encode())
        self.assertGreater(export_size, 21677758)
        source_hash = hashlib.sha256(store.path.read_bytes()).hexdigest()
        archive, restored = self.root / "archive", self.root / "restored"
        failure = None
        try:
            result = backup.backup_shared(store, archive)
        except ev.EvidenceError as exc:
            failure = str(exc)
        self.assertIsNone(failure, "complete bounded history must export: " + str(failure))
        self.assertEqual(result["status"], "LOCAL_SHARED_BACKUP_VERIFIED")
        manifest, data = backup.read_shared(archive)
        self.assertEqual(manifest["schema"], "ar-shared-workspace-backup.v2")
        self.assertEqual(data["tables"], expected)
        self.assertTrue(any(name.startswith("data-chunks/") for name in manifest["files"]))
        self.assertTrue(all((archive / name).stat().st_size <= 12582912 for name in manifest["files"]))
        receipt = backup.restore_shared(archive, restored)
        self.assertEqual(receipt["status"], "LOCAL_SHARED_RESTORE_VERIFIED")
        with sqlite3.connect(restored / "shared-workbench.sqlite3") as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
            for table, columns in ALL_TABLES.items():
                rows = [list(row) for row in db.execute("SELECT " + ", ".join(columns) + " FROM " + table + " ORDER BY rowid")]
                if table == "shared_migrations":
                    rows = [row for row in rows if row[0] != receipt["backup_hash"]]
                self.assertEqual(rows, expected[table], table)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM workspace_owner").fetchone()[0], 0)
        for name, digest in manifest["files"].items():
            if name == "data.json" or name.startswith("data-chunks/"):
                self.assertFalse((restored / name).exists())
            else:
                self.assertEqual(hashlib.sha256((restored / name).read_bytes()).hexdigest(), digest, name)
        self.assertEqual(hashlib.sha256(store.path.read_bytes()).hexdigest(), source_hash)
        self.assertEqual(backup.restore_shared(archive, self.root / "another")["backup_hash"], receipt["backup_hash"])


if __name__ == "__main__":
    unittest.main()
