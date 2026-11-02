"""Deferred offline retention-pin regressions. Execution was NOT_RUN in wave 2."""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/llm"))
sys.path.insert(0, str(ROOT / "tests"))

import foundation_retention as retention
import nonprod_workbench as wb
import workbench_backup as backup
import workbench_evidence as ev
import workbench_shared_jobs as jobs
import workbench_shared_worker as worker
import workbench_shared_workspace as shared
import workbench_workspace as ws
from workbench_shared_inputs import FrozenInputs
from workbench_shared_test_support import publisher_source

CREATED_AT = "2026-11-01T12:00:00+00:00"


class RetentionPinTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source"
        publisher_source(self.source, "retained_old_run", "20261012")
        self.store = wb.Store(self.root / "state", shared_v1=True)
        self.inputs = FrozenInputs(self.store)
        self.old = self.inputs.import_once(self.source)
        self.system = ws.Workspace(self.store, self.source, private_mode=True)
        # Synthetic code identity isolates this fixture from Git and credentials;
        # archive/input/queue/seal verification below remains the real boundary.
        identity = {"code_sha": "a" * 40, "source_tree_hash": "b" * 64}
        patch = mock.patch.object(shared, "execution_identity", return_value=identity)
        patch.start()
        self.addCleanup(patch.stop)
        self.view = shared.SharedWorkspace(self.system)
        self.queue = jobs.SharedJobQueue(self.view, self.inputs, identity["code_sha"])
        accepted = self.queue.enqueue({"command_id": "retention-observe-001", "kind": "observe",
                                       "snapshot_id": self.old["snapshot_id"]}, "fixture@example.invalid")
        self.job_id = accepted["job_id"]
        claim = self.queue.claim()

        def render_in_process(_argv, _env, _cwd, **_options):
            worker._render_child(claim["kind"], Path(claim["frozen_root"]), Path(claim["output_root"]))
            return {"status": "SUCCEEDED"}

        with mock.patch.object(worker, "run_bounded", side_effect=render_in_process):
            result = worker.run_attempt(claim)
        self.assertEqual(result["status"], "SUCCEEDED", result)
        self.assertEqual(self.queue.finish(claim, result)["status"], "SUCCEEDED")
        self.seal_hash = result["seal_hash"]
        publisher_source(self.source, "current_new_run", "20261014")
        self.new = self.inputs.import_once(self.source)
        self.archive = self.root / "archive"
        archived = backup.backup_shared(self.store, self.archive)
        self.expected = archived["backup_hash"]

    def build(self, **changes):
        request = {"expected_backup_hash": self.expected, "snapshot_ids": [self.old["snapshot_id"]],
                   "job_ids": [self.job_id], "case_refs": ["cases/review-note-001"], "created_at": CREATED_AT}
        request.update(changes)
        return retention.build_retention_pin(self.archive, **request)

    def verify(self, pin, *, root=None, expected=None):
        return retention.verify_retention_pin(pin, root or self.archive,
                                              expected_backup_hash=expected or self.expected)

    def reseal_pin(self, pin):
        pin["pin_hash"] = ev.sealed({key: value for key, value in pin.items() if key != "pin_hash"})
        return pin

    def reseal_archive(self, changed_file=None):
        path = self.archive / "manifest.json"
        manifest = ev.parse(path.read_bytes())
        if changed_file:
            manifest["files"][changed_file] = ev.sha((self.archive / changed_file).read_bytes())
        manifest["backup_hash"] = ev.sealed({key: value for key, value in manifest.items() if key != "backup_hash"})
        path.write_bytes(ev.canonical(manifest).encode())
        return manifest["backup_hash"]

    def test_round_trip_preserves_historical_hashes_seal_and_unbound(self):
        before = {path.relative_to(self.archive): path.read_bytes()
                  for path in self.archive.rglob("*") if path.is_file()}
        pin = self.build()
        self.assertEqual(self.verify(pin), pin)
        snapshot = pin["snapshots"][0]
        self.assertEqual(snapshot["snapshot_id"], self.old["snapshot_id"])
        self.assertNotEqual(snapshot["snapshot_id"], self.new["snapshot_id"])
        self.assertEqual(snapshot["source_run_id"], "retained_old_run")
        self.assertEqual(snapshot["input_hash"], self.old["input_hash"])
        self.assertEqual(snapshot["records"]["public/data/v2/current_run.json"]["binding"], "UNBOUND")
        alias = snapshot["records"]["public/data/v2/macro_gate.json"]
        self.assertEqual(alias["status"], "OPTIONAL_UNBOUND")
        self.assertEqual(alias["binding"], "UNBOUND")
        self.assertEqual(pin["jobs"][0]["result"]["seal_hash"], self.seal_hash)
        self.assertEqual(pin["jobs"][0]["binding"]["snapshot_id"], self.old["snapshot_id"])
        for key, value in retention.LABELS.items():
            self.assertEqual(pin[key], value)
        self.assertEqual(pin["case_refs"], [{"ref": "cases/review-note-001",
                                           "verification": "NOT_VERIFIED", "case_authority": False}])
        self.assertEqual({path.relative_to(self.archive): path.read_bytes()
                          for path in self.archive.rglob("*") if path.is_file()}, before)
        self.assertNotIn(str(self.root), json.dumps(pin))
        self.assertNotIn("owner_credentials", json.dumps(pin))

    def test_expected_hash_is_required_independently_for_build_and_verify(self):
        pin = self.build()
        with self.assertRaisesRegex(ValueError, "EXPECTED_BACKUP_HASH_MISMATCH"):
            self.build(expected_backup_hash="0" * 64)
        with self.assertRaisesRegex(ValueError, "EXPECTED_BACKUP_HASH_MISMATCH"):
            self.verify(pin, expected="0" * 64)
        with self.assertRaises(TypeError):
            retention.build_retention_pin(self.archive, snapshot_ids=[], job_ids=[self.job_id], created_at=CREATED_AT)

    def test_snapshot_only_and_job_only_are_real_selections(self):
        self.assertEqual(self.build(job_ids=[])["jobs"], [])
        self.assertEqual(self.build(snapshot_ids=[])["snapshots"], [])
        with self.assertRaisesRegex(ValueError, "REGISTERED_SELECTION_REQUIRED"):
            self.build(snapshot_ids=[], job_ids=[])

    def test_unknown_snapshot_and_job_are_not_promoted_from_notes_or_artifacts(self):
        unknown = "00000000-0000-0000-0000-000000000001"
        with self.assertRaisesRegex(ValueError, "SNAPSHOT_NOT_REGISTERED"):
            self.build(snapshot_ids=[unknown], case_refs=[self.old["snapshot_id"]])
        with self.assertRaisesRegex(ValueError, "JOB_NOT_REGISTERED"):
            self.build(job_ids=[unknown])

    def test_resealed_archive_does_not_replace_independently_expected_hash(self):
        manifest = self.archive / "manifest.json"
        value = ev.parse(manifest.read_bytes())
        value["archive_label"] = "different-history"
        manifest.write_bytes(ev.canonical(value).encode())
        changed = self.reseal_archive()
        self.assertNotEqual(changed, self.expected)
        with self.assertRaisesRegex(ValueError, "EXPECTED_BACKUP_HASH_MISMATCH"):
            self.build()

    def test_tampered_archive_file_is_rejected(self):
        (self.archive / "data.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "BACKUP_ARTIFACT_HASH_INVALID"):
            self.build()

    def test_resealed_successful_job_seal_still_reaches_existing_seal_guard(self):
        relative = next(name for name in backup.verify_shared(self.archive)["files"]
                        if name.startswith("shared-jobs/") and name.endswith("/seal.json"))
        path = self.archive / relative
        seal = ev.parse(path.read_bytes())
        seal["binding"]["code_sha"] = "c" * 40
        seal["seal_hash"] = ev.sealed({key: value for key, value in seal.items() if key != "seal_hash"})
        path.write_bytes(ev.canonical(seal).encode())
        newly_expected = self.reseal_archive(relative)
        with self.assertRaisesRegex(ValueError, "BACKUP_SHARED_QUEUE_BINDING_INVALID"):
            self.build(expected_backup_hash=newly_expected)

    def test_missing_successful_job_output_fails_even_with_resealed_catalog(self):
        manifest_path = self.archive / "manifest.json"
        manifest = ev.parse(manifest_path.read_bytes())
        relative = next(name for name in manifest["files"] if name.endswith("/result/observation.json"))
        (self.archive / relative).unlink()
        del manifest["files"][relative]
        for group in manifest["artifact_inventory"]:
            if relative in group["files"]:
                group["files"].remove(relative)
        manifest_path.write_bytes(ev.canonical(manifest).encode())
        expected = self.reseal_archive()
        with self.assertRaisesRegex(ValueError, "BACKUP_SHARED_QUEUE_BINDING_INVALID"):
            self.build(expected_backup_hash=expected)

    def test_pin_self_hash_and_resealed_forged_archive_binding_are_rejected(self):
        pin = self.build()
        tampered = copy.deepcopy(pin)
        tampered["snapshots"][0]["source_run_id"] = "forged_run"
        with self.assertRaisesRegex(ValueError, "PIN_HASH_INVALID"):
            self.verify(tampered)
        with self.assertRaisesRegex(ValueError, "PIN_ARCHIVE_BINDING_INVALID"):
            self.verify(self.reseal_pin(tampered))
        tampered = copy.deepcopy(pin)
        tampered["jobs"][0]["result"]["seal_hash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "PIN_ARCHIVE_BINDING_INVALID"):
            self.verify(self.reseal_pin(tampered))

    def test_pin_authority_and_case_note_promotion_are_refused_even_resealed(self):
        for field in ("production_authority", "trading_authority"):
            pin = self.build()
            pin[field] = True
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "LABEL_OR_AUTHORITY_INVALID"):
                self.verify(self.reseal_pin(pin))
        pin = self.build()
        pin["case_refs"][0]["case_authority"] = True
        with self.assertRaisesRegex(ValueError, "CASE_AUTHORITY_REFUSED"):
            self.verify(self.reseal_pin(pin))

    def test_immutable_write_has_serializable_portable_receipt_and_no_overwrite(self):
        pin = self.build()
        pin_root = self.root / "pins"
        receipt = retention.write_retention_pin(pin_root, pin)
        self.assertEqual(json.loads(json.dumps(receipt)), receipt)
        self.assertEqual(receipt["pin_ref"], pin["pin_hash"] + ".json")
        self.assertFalse(receipt["archive_reverified"])
        self.assertEqual(receipt["testing_status"], "NOT_RUN")
        path = pin_root / receipt["pin_ref"]
        before = (path.stat().st_ino, path.read_bytes())
        self.assertEqual(ev.parse(before[1]), pin)
        with self.assertRaisesRegex(ValueError, "PIN_ALREADY_EXISTS"):
            retention.write_retention_pin(pin_root, pin)
        self.assertEqual((path.stat().st_ino, path.read_bytes()), before)

    def test_backup_and_pin_roots_refuse_symlinks_including_parent_links(self):
        pin = self.build()
        link = self.root / "archive-link"
        link.symlink_to(self.archive, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "ROOT_SYMLINK"):
            self.verify(pin, root=link)
        outside = self.root / "outside"
        outside.mkdir()
        link = self.root / "pin-parent-link"
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "ROOT_SYMLINK"):
            retention.write_retention_pin(link / "pins", pin)
        self.assertEqual(list(outside.iterdir()), [])

    def test_archive_member_and_pin_destination_symlinks_are_refused(self):
        pin = self.build()
        data = self.archive / "data.json"
        outside = self.root / "outside-data.json"
        data.rename(outside)
        data.symlink_to(outside)
        with self.assertRaises((ValueError, OSError)):
            self.build()
        pin_root = self.root / "pins"
        pin_root.mkdir()
        destination = pin_root / (pin["pin_hash"] + ".json")
        destination.symlink_to(self.root / "missing")
        with self.assertRaisesRegex(ValueError, "PIN_ALREADY_EXISTS"):
            retention.write_retention_pin(pin_root, pin)
        self.assertFalse((self.root / "missing").exists())

    def test_portability_does_not_require_live_source_or_owner_credentials(self):
        pin = self.build()
        moved = self.root / "portable-copy"
        shutil.copytree(self.archive, moved)
        shutil.rmtree(self.source)
        shutil.rmtree(self.store.path.parent)
        self.assertEqual(self.verify(pin, root=moved), pin)
        self.assertFalse(any(path.suffix == ".sqlite3" or path.name == "cookie.key" for path in moved.rglob("*")))

    def test_legacy_registered_job_is_retained_without_inventing_shared_identity(self):
        legacy_root = self.root / "legacy-fixture"
        from workbench_shared_test_support import historical_state
        store, _system = historical_state(legacy_root)
        archive = self.root / "legacy-archive"
        expected = backup.backup_shared(store, archive)["backup_hash"]
        pin = retention.build_retention_pin(archive, expected_backup_hash=expected,
                                            snapshot_ids=[], job_ids=["success_brief", "started_brief"],
                                            created_at=CREATED_AT)
        self.assertEqual(pin["jobs"][0]["status"], "INTERRUPTED")
        self.assertEqual(pin["jobs"][1]["status"], "SUCCEEDED")
        self.assertTrue(all(row["registration"] == "workspace_events" for row in pin["jobs"]))
        self.assertTrue(all("snapshot_id" not in row["binding"] for row in pin["jobs"]))
        self.assertEqual(retention.verify_retention_pin(pin, archive, expected_backup_hash=expected), pin)

    def test_bounded_inputs_reject_duplicates_traversal_unsafe_notes_and_bad_time(self):
        requests = [
            {"snapshot_ids": [self.old["snapshot_id"], self.old["snapshot_id"]]},
            {"job_ids": [self.job_id, self.job_id]},
            {"snapshot_ids": "not-an-array"}, {"job_ids": ["../other-job"]},
            {"job_ids": [True]}, {"case_refs": ["../case"]}, {"case_refs": ["/absolute/case"]},
            {"case_refs": ["https://example.invalid/case"]}, {"case_refs": ["case\\secret"]},
            {"case_refs": ["case"] * 101}, {"case_refs": ["case", "case"]},
            {"created_at": "2026-11-01T12:00:00"}, {"created_at": "2026-02-30T12:00:00Z"},
            {"created_at": "2026-11-01T12:00:00+00:60"},
            {"expected_backup_hash": None}, {"expected_backup_hash": "A" * 64},
        ]
        for request in requests:
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.build(**request)
        with self.assertRaisesRegex(ValueError, "ROOT_INVALID"):
            retention.write_retention_pin(self.root / "pins/../unsafe", self.build())

    def test_malformed_cyclic_large_and_credential_shaped_pin_is_not_written(self):
        pin = self.build()
        mutations = []
        cyclic = copy.deepcopy(pin)
        cyclic["cycle"] = cyclic
        mutations.append(cyclic)
        large = copy.deepcopy(pin)
        large["extra"] = "x" * (retention.MAX_PIN_BYTES + 1)
        mutations.append(large)
        credentials = copy.deepcopy(pin)
        credentials["authorization"] = "Bearer synthetic-retention-secret"
        mutations.append(credentials)
        unsafe_binding = copy.deepcopy(pin)
        unsafe_binding["jobs"][0]["binding"]["source_run_id"] = "/private/unsafe"
        mutations.append(self.reseal_pin(unsafe_binding))
        unsafe_reference = copy.deepcopy(pin)
        unsafe_reference["jobs"][0]["artifact_refs"] = ["../outside.json"]
        mutations.append(self.reseal_pin(unsafe_reference))
        malformed_schema = copy.deepcopy(pin)
        malformed_schema["backup"]["schema"] = []
        mutations.append(self.reseal_pin(malformed_schema))
        malformed_registration = copy.deepcopy(pin)
        malformed_registration["jobs"][0]["registration"] = {}
        mutations.append(self.reseal_pin(malformed_registration))
        for index, value in enumerate(mutations):
            path = self.root / ("refused-" + str(index))
            with self.subTest(index=index), self.assertRaises(ValueError):
                retention.write_retention_pin(path, value)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
