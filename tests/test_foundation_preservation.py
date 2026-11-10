"""Deferred preservation regressions: NOT_RUN; human_review PENDING.

All fixtures are synthetic WORKFLOW_DEBUG packages. No production, trading, or
deployment authority is granted. This file was authored, not executed, in wave 3.
"""
import copy
from datetime import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/llm"))

import foundation_preservation as preservation
import workbench_backup as backup
import workbench_evidence as ev
from workbench_shared_state import ALL_TABLES, STORAGE_SCHEMA

CREATED_AT = "2026-11-02T00:00:00+00:00"


class PreservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.archive = self.root / "backup"
        self.expected = self.make_backup(self.archive)

    def make_backup(self, root, *, marker="first", legacy=False):
        """Encode a tiny existing-format archive, not a live state or backup job."""
        root.mkdir()
        observation = {"schema": "ar-workbench-observation.v1", **preservation.LABELS,
                       "formal_authority": False, "production_write": False,
                       "records": {"legacy-alias": {"binding": "UNBOUND", "status": "OPTIONAL_UNBOUND"}},
                       "marker": marker}
        observation["snapshot_hash"] = ev.sealed(observation)
        tables = {name: [] for name in (backup.TABLES if legacy else ALL_TABLES)}
        tables["workspace_observations"] = [[observation["snapshot_hash"], ev.canonical(observation)]]
        data = {"schema": "ar-workspace-data-export.v1" if legacy else "ar-shared-workspace-data-export.v1",
                "tables": tables}
        (root / "data.json").write_bytes(ev.canonical(data).encode())
        manifest = {"schema": "ar-workspace-backup.v1" if legacy else "ar-shared-workspace-backup.v1",
                    **preservation.LABELS, "credentials_included": False,
                    "files": {"data.json": ev.sha((root / "data.json").read_bytes())}}
        if not legacy:
            manifest.update(source_storage_schema=STORAGE_SCHEMA, integrity_check="ok",
                            table_counts={name: len(rows) for name, rows in tables.items()},
                            event_tail="0" * 64, artifact_inventory=[], directories=[],
                            inventory_scope="ISOLATED_STATE_ARTIFACT_ROOTS")
        manifest["backup_hash"] = ev.sealed(manifest)
        (root / "manifest.json").write_bytes(ev.canonical(manifest).encode())
        return manifest["backup_hash"]

    def request(self, **changes):
        request = {"package_id": "backup-001", "kind": "SHARED_BACKUP",
                   "local_root": self.archive, "expected_content_hash": self.expected}
        request.update(changes)
        return request

    def build(self, packages=None, *, created_at=CREATED_AT):
        return preservation.build_preservation_manifest(
            [self.request()] if packages is None else packages, created_at=created_at)

    def verify(self, manifest, roots=None, *, expected=None):
        return preservation.verify_preservation_copy(
            manifest, {"backup-001": self.archive} if roots is None else roots,
            expected_preservation_hash=manifest["preservation_hash"] if expected is None else expected)

    def reseal_manifest(self, manifest):
        manifest["preservation_hash"] = ev.sealed(
            {key: value for key, value in manifest.items() if key != "preservation_hash"})
        return manifest

    def reseal_backup(self, root):
        path = root / "manifest.json"
        manifest = ev.parse(path.read_bytes())
        manifest["files"] = {name: ev.sha((root / name).read_bytes()) for name in manifest["files"]}
        manifest["backup_hash"] = ev.sealed(
            {key: value for key, value in manifest.items() if key != "backup_hash"})
        path.write_bytes(ev.canonical(manifest).encode())
        return manifest["backup_hash"]

    def test_portable_complete_bytes_and_original_validator_reopen_without_writes(self):
        before = {path.relative_to(self.archive).as_posix(): path.read_bytes()
                  for path in self.archive.rglob("*") if path.is_file()}
        with mock.patch.object(backup, "read_shared", wraps=backup.read_shared) as read, \
                mock.patch.object(backup, "verify_shared", wraps=backup.verify_shared) as verify:
            manifest = self.build()
            self.assertTrue(read.called)
            self.assertTrue(verify.called)
        raw = json.dumps(manifest, sort_keys=True)
        self.assertNotIn(str(self.root), raw)
        self.assertNotIn("local_root", raw)
        row = manifest["packages"][0]
        self.assertEqual(row["files"], {name: ev.sha(value) for name, value in before.items()})
        self.assertEqual(row["total_bytes"], sum(map(len, before.values())))
        self.assertEqual(json.loads(raw), manifest)
        moved = self.root / "destination"
        shutil.copytree(self.archive, moved)
        result = self.verify(manifest, {"backup-001": moved})
        self.assertEqual(result["package_bytes"], "MATCH")
        self.assertEqual(result["verified_package_ids"], ["backup-001"])
        self.assertEqual(before, {path.relative_to(self.archive).as_posix(): path.read_bytes()
                                  for path in self.archive.rglob("*") if path.is_file()})

    def test_local_copy_or_same_root_never_attests_off_machine_restore_or_rights(self):
        manifest = self.build()
        result = self.verify(manifest)
        for output in (manifest, result):
            self.assertEqual(output["requirements"], preservation.REQUIREMENTS)
            self.assertEqual(output["testing_status"], "NOT_RUN")
            self.assertEqual(output["human_review"], "PENDING")
            self.assertEqual(output["status"], "IMPLEMENTED_UNTESTED")
            self.assertEqual(output["sample_purpose"], "WORKFLOW_DEBUG")
            for key in ("production_authority", "trading_authority", "deployment_authority"):
                self.assertIs(output[key], False)
        self.assertEqual(result["requirements"]["off_machine_storage"], "NOT_ATTESTED")
        self.assertEqual(result["requirements"]["restore"], "NOT_ATTESTED")

    def test_tampered_missing_and_unexpected_destination_files_are_refused(self):
        manifest = self.build()
        for mutation in ("tampered", "missing", "unexpected"):
            moved = self.root / mutation
            shutil.copytree(self.archive, moved)
            if mutation == "tampered":
                (moved / "data.json").write_bytes(b"{}")
            elif mutation == "missing":
                (moved / "data.json").unlink()
            else:
                (moved / "unexpected.bin").write_bytes(b"extra")
            with self.subTest(mutation=mutation), self.assertRaises((ValueError, OSError)):
                self.verify(manifest, {"backup-001": moved})

    def test_self_resealed_backup_does_not_replace_independent_content_hash(self):
        manifest = self.build()
        moved = self.root / "resealed"
        shutil.copytree(self.archive, moved)
        data = ev.parse((moved / "data.json").read_bytes())
        data["tables"]["drafts"].append([1, ev.canonical({"marker": "changed"})])
        (moved / "data.json").write_bytes(ev.canonical(data).encode())
        changed = ev.parse((moved / "manifest.json").read_bytes())
        changed["table_counts"]["drafts"] = 1
        (moved / "manifest.json").write_bytes(ev.canonical(changed).encode())
        replacement_hash = self.reseal_backup(moved)
        self.assertNotEqual(replacement_hash, self.expected)
        self.assertEqual(backup.verify_shared(moved)["backup_hash"], replacement_hash)
        with self.assertRaisesRegex(ValueError, "EXPECTED_CONTENT_HASH_MISMATCH"):
            self.verify(manifest, {"backup-001": moved})
        with self.assertRaisesRegex(ValueError, "EXPECTED_CONTENT_HASH_MISMATCH"):
            self.build([self.request(local_root=moved)])

    def test_self_resealed_handoff_does_not_replace_independent_preservation_hash(self):
        manifest = self.build()
        independent = manifest["preservation_hash"]
        changed = copy.deepcopy(manifest)
        changed["created_at"] = "2026-11-03T00:00:00Z"
        self.reseal_manifest(changed)
        with self.assertRaisesRegex(ValueError, "EXPECTED_PRESERVATION_HASH_MISMATCH"):
            self.verify(changed, expected=independent)
        with self.assertRaises(TypeError):
            preservation.verify_preservation_copy(manifest, {"backup-001": self.archive})
        with self.assertRaises(ValueError):
            self.verify(manifest, expected="f" * 64)

    def test_package_set_kind_identity_and_swapped_roots_are_refused(self):
        other = self.root / "other"
        other_hash = self.make_backup(other, marker="second")
        manifest = self.build([self.request(), self.request(package_id="backup-002", local_root=other,
                                                          expected_content_hash=other_hash)])
        bad_roots = [{"backup-001": self.archive},
                     {"backup-001": self.archive, "backup-002": other, "extra": self.archive},
                     {"backup-001": other, "backup-002": self.archive},
                     {"renamed": self.archive, "backup-002": other}]
        for roots in bad_roots:
            with self.subTest(ids=list(roots)), self.assertRaises(ValueError):
                self.verify(manifest, roots)
        changed = copy.deepcopy(manifest)
        changed["packages"][0]["package_id"] = "renamed"
        self.reseal_manifest(changed)
        with self.assertRaisesRegex(ValueError, "EXPECTED_PRESERVATION_HASH_MISMATCH"):
            self.verify(changed, expected=manifest["preservation_hash"])
        changed = copy.deepcopy(manifest)
        changed["packages"][0]["kind"] = "OTHER"
        self.reseal_manifest(changed)
        with self.assertRaisesRegex(ValueError, "PACKAGE_KIND_INVALID"):
            self.verify(changed, {"backup-001": self.archive, "backup-002": other})

    def test_original_observation_seals_and_unbound_semantics_are_preserved(self):
        manifest = self.build()
        _archive, data = backup.read_shared(self.archive)
        observation = ev.parse(data["tables"]["workspace_observations"][0][1])
        self.assertEqual(observation["records"]["legacy-alias"]["binding"], "UNBOUND")
        self.assertEqual(manifest["preserved_semantics"]["unbound_evidence"], "PRESERVED_NOT_PROMOTED")
        observation["records"]["legacy-alias"]["binding"] = "MATCH"
        data["tables"]["workspace_observations"][0][1] = ev.canonical(observation)
        (self.archive / "data.json").write_bytes(ev.canonical(data).encode())
        changed_hash = self.reseal_backup(self.archive)
        with self.assertRaisesRegex(ValueError, "OBSERVATION_HASH_MISMATCH"):
            self.build([self.request(expected_content_hash=changed_hash)])

    def test_legacy_backup_uses_existing_validator_without_resealing_derived_metadata(self):
        legacy = self.root / "legacy"
        expected = self.make_backup(legacy, legacy=True)
        manifest = self.build([self.request(local_root=legacy, expected_content_hash=expected)])
        self.assertEqual(manifest["packages"][0]["semantics"]["inventory_scope"], "LEGACY_BACKUP_CONTENT_ONLY")
        self.assertEqual(manifest["packages"][0]["content_hash"], expected)
        self.verify(manifest, {"backup-001": legacy})

    def test_empty_directory_set_is_bound_in_addition_to_complete_file_bytes(self):
        manifest = self.build()
        moved = self.root / "extra-directory"
        shutil.copytree(self.archive, moved)
        (moved / "extra-empty-directory").mkdir()
        with self.assertRaisesRegex(ValueError, "DESTINATION_PACKAGE_BINDING_MISMATCH"):
            self.verify(manifest, {"backup-001": moved})

    def test_root_member_parent_symlinks_and_special_files_are_refused(self):
        manifest = self.build()
        link = self.root / "linked"
        link.symlink_to(self.archive, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "ROOT_SYMLINK"):
            self.verify(manifest, {"backup-001": link})
        parent = self.root / "linked-parent"
        parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "ROOT_SYMLINK"):
            self.verify(manifest, {"backup-001": parent / "backup"})
        for kind in ("symlink", "dangling", "fifo"):
            moved = self.root / kind
            shutil.copytree(self.archive, moved)
            if kind == "fifo":
                os.mkfifo(moved / "unexpected")
            else:
                (moved / "unexpected").symlink_to(self.archive / ("data.json" if kind == "symlink" else "absent"))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.verify(manifest, {"backup-001": moved})

    def test_closed_bounded_inputs_time_collisions_and_overlapping_roots_are_refused(self):
        requests = [[], [self.request()] * (preservation.MAX_PACKAGES + 1),
                    [self.request(), self.request()],
                    [self.request(), self.request(package_id="BACKUP-001")],
                    [self.request(package_id="../escape")], [self.request(package_id=True)],
                    [self.request(kind=[])], [self.request(kind="UPLOAD")],
                    [self.request(expected_content_hash="A" * 64)],
                    [self.request(local_root="https://example.invalid/package")],
                    [self.request(local_root=Path("/"))],
                    [self.request(local_root=self.archive / "../backup")],
                    [self.request(local_root=self.archive / "missing")],
                    [self.request(extra="not-allowed")],
                    [self.request(), self.request(package_id="backup-002")]]
        for packages in requests:
            with self.subTest(packages=packages), self.assertRaises(ValueError):
                self.build(packages)
        for value in ("2026-11-02T00:00:00", "2026-02-30T00:00:00Z", "2026-11-02T00:00:00+00:60", None):
            with self.subTest(created_at=value), self.assertRaises(ValueError):
                self.build(created_at=value)
        with mock.patch.object(preservation, "MAX_ENTRIES", 1), self.assertRaisesRegex(ValueError, "ENTRY_LIMIT"):
            self.build()
        with mock.patch.object(preservation, "MAX_TOTAL_BYTES", 1), self.assertRaises(ValueError):
            self.build()
        # Case-insensitive filesystems cannot create these as distinct siblings.
        with mock.patch.object(preservation.os, "scandir") as scan:
            scan.return_value.__enter__.return_value = [Path("data.json"), Path("DATA.json")]
            with self.assertRaisesRegex(ValueError, "PORTABLE_PATH_COLLISION"):
                self.build()

    def test_duplicate_json_keys_cyclic_manifest_and_authority_promotion_are_refused(self):
        manifest = self.build()
        cyclic = copy.deepcopy(manifest)
        cyclic["cycle"] = cyclic
        with self.assertRaisesRegex(ValueError, "JSON_LIMIT"):
            self.verify(cyclic)
        for value in (float("nan"), float("inf"), 1 << 100, {"non-json"}):
            changed = copy.deepcopy(manifest)
            changed["extra"] = value
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                self.verify(changed)
        for key, value in (("production_authority", True), ("deployment_authority", True),
                           ("trading_authority", True), ("testing_status", "PASS"),
                           ("human_review", "APPROVED"), ("remote_receipt", {"status": "PASS"})):
            changed = copy.deepcopy(manifest)
            changed[key] = value
            self.reseal_manifest(changed)
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.verify(changed)
        changed = copy.deepcopy(manifest)
        changed["requirements"]["off_machine_storage"] = "PASS"
        self.reseal_manifest(changed)
        with self.assertRaisesRegex(ValueError, "LABEL_OR_AUTHORITY_INVALID"):
            self.verify(changed)
        path = self.archive / "manifest.json"
        raw = path.read_bytes()
        path.write_bytes(b'{"schema":"duplicate",' + raw[1:])
        with self.assertRaisesRegex(ValueError, "DUPLICATE_SOURCE_KEY"):
            self.build()

    def test_library_boundary_requires_exact_hash_and_complete_file_catalog_in_mixed_package(self):
        # Contract-double test only; real material intake integration is separate.
        library = self.root / "library-contract"
        library.mkdir()
        (library / "registration.json").write_bytes(b'{"binding":"UNBOUND"}')
        files = {"registration.json": ev.sha((library / "registration.json").read_bytes())}
        expected = "d" * 64
        request = self.request(package_id="library-001", kind="RESEARCH_LIBRARY", local_root=library,
                               expected_content_hash=expected)
        with mock.patch("foundation_materials.verify_library", return_value={"library_hash": expected, "files": files}) as verify:
            manifest = self.build([request, self.request()])
            verify.assert_called_once_with(library, expected_library_hash=expected)
            moved = self.root / "mixed-copy"
            moved.mkdir()
            shutil.copytree(library, moved / "library")
            shutil.copytree(self.archive, moved / "backup")
            self.verify(manifest, {"backup-001": moved / "backup", "library-001": moved / "library"})
            (moved / "library" / "registration.json").write_bytes(b'{"binding":"MATCH"}')
            with self.assertRaisesRegex(ValueError, "VALIDATOR_FILE_SET_MISMATCH"):
                self.verify(manifest, {"backup-001": moved / "backup", "library-001": moved / "library"})
        for returned in ({"library_hash": "e" * 64, "files": files},
                         {"library_hash": expected, "files": {}},
                         {"library_hash": expected, "files": {**files, "missing.json": "a" * 64}}):
            with mock.patch("foundation_materials.verify_library", return_value=returned), self.assertRaises(ValueError):
                self.build([request])

    def test_real_material_intake_and_backup_mixed_copy_retains_bytes_and_unapproved_rights(self):
        import foundation_materials as materials

        source = self.root / "material-source"
        source.mkdir()
        raw = b"Synthetic original: preservation is not source-rights approval.\n"
        (source / "original.md").write_bytes(raw)
        library = self.root / "material-library"
        intake = {"schema": "ar.material-intake.v1", **materials.LABELS,
                  "library_id": "preservation-fixture", "created_at": CREATED_AT,
                  "materials": [{"material_id": "original-001", "kind": "original", "version": "v1",
                                 "title": "Synthetic preservation original", "industry_key": "sample-industry",
                                 "industry_taxonomy": "synthetic", "taxonomy_version": "v1", "ts_code": "600000.SH",
                                 "trade_date": "20261102", "run_id": "preservation-fixture-run", "code_sha": "a" * 40,
                                 "published_at": "2026-11-01T00:00:00Z", "available_at": "2026-11-01T00:30:00Z",
                                 "cutoff_at": "2026-11-01T01:00:00Z", "original_refs": [],
                                 "provenance": {"publisher": "Synthetic", "provider_id": "synthetic",
                                                "source_locator": "document:original-001",
                                                "captured_at": "2026-11-01T00:45:00Z"},
                                 "rights": dict(materials.RIGHTS),
                                 "files": [{"source_path": "original.md", "sha256": ev.sha(raw), "size_bytes": len(raw)}]}]}
        registered = materials.ingest_material(source, library, intake)
        request = self.request(package_id="library-001", kind="RESEARCH_LIBRARY", local_root=library,
                               expected_content_hash=registered["library_hash"])
        manifest = self.build([self.request(), request])
        library_row = next(row for row in manifest["packages"] if row["kind"] == "RESEARCH_LIBRARY")
        self.assertEqual(library_row["files"], registered["files"])
        destination_library = self.root / "copied-material-library"
        destination_backup = self.root / "copied-shared-backup"
        shutil.copytree(library, destination_library)
        shutil.copytree(self.archive, destination_backup)
        roots = {"backup-001": destination_backup, "library-001": destination_library}
        result = self.verify(manifest, roots)
        self.assertEqual(result["verified_package_ids"], ["backup-001", "library-001"])
        self.assertEqual(result["requirements"]["source_rights"], "NOT_ATTESTED")
        reopened = materials.verify_library(destination_library, expected_library_hash=registered["library_hash"])
        self.assertEqual(reopened["materials"][0]["rights"], materials.RIGHTS)
        original = next(name for name in registered["files"] if "/files/" in name)
        self.assertEqual((destination_library / original).read_bytes(), raw)
        (destination_library / original).write_bytes(b"tampered original")
        with self.assertRaises(ValueError):
            self.verify(manifest, roots)

    def test_streaming_preserves_library_original_above_shared_evidence_file_limit(self):
        # The library validator supports 256 MiB originals; the handoff must not
        # inherit the backup JSON reader's smaller 12 MiB payload ceiling.
        library = self.root / "larger-library-contract"
        library.mkdir()
        raw = b"x" * (ev.MAX_FILE + 1)
        (library / "original.txt").write_bytes(raw)
        expected = "d" * 64
        files = {"original.txt": ev.sha(raw)}
        request = self.request(package_id="library-001", kind="RESEARCH_LIBRARY", local_root=library,
                               expected_content_hash=expected)
        with mock.patch("foundation_materials.verify_library", return_value={"library_hash": expected, "files": files}):
            manifest = self.build([request])
            self.assertEqual(manifest["packages"][0]["total_bytes"], len(raw))
            self.verify(manifest, {"library-001": library})

    def retained_inventory(self, root):
        files, directories, total = {}, [], 0
        for path in sorted(root.rglob("*")):
            name = path.relative_to(root).as_posix()
            if path.is_dir():
                directories.append(name)
            else:
                raw = path.read_bytes()
                files[name] = ev.sha(raw)
                total += len(raw)
        return {"files": files, "directories": directories, "total_bytes": total}

    def gap_request(self):
        import core_source_gaps as gaps
        from experiments.data_governance.endpoint_calls import EndpointObservationError, EndpointSession

        source, ledger = self.root / "gap-source", self.root / "gap-ledger"
        session = EndpointSession(source, collector_run_id="preservation-gap-fixture",
                                  target_trade_date="20261104",
                                  clock=lambda: datetime.fromisoformat("2026-11-09T18:00:00+00:00"))

        def unavailable():
            raise OSError("synthetic offline source unavailable")

        with self.assertRaises(EndpointObservationError):
            session.observe("moneyflow_dc", {"ts_code": "603629.SH", "trade_date": "20261104"},
                            "ts_code,trade_date,net_amount", unavailable)
        source_hash = gaps.evidence(source)["evidence_hash"]
        saved = gaps.ingest(ledger, source, expected_evidence_hash=source_hash, expected_head="0" * 64)
        (ledger / "write-evidence" / "retained-empty").mkdir()
        (ledger / "write-evidence" / "failed-copy.partial").write_bytes(b"uncommitted source-copy evidence\n")
        request = self.request(package_id="gaps-001", kind="CORE_GAP_LEDGER", local_root=ledger,
                               expected_content_hash=ev.sealed(self.retained_inventory(ledger)))
        return request, saved["head_hash"]

    def build_gap(self, request):
        try:
            return self.build([request])
        except ValueError as error:
            self.fail("pinned retained gap package must be accepted: " + str(error))

    def test_core_gap_mixed_cold_copy_reopens_real_validators_without_promoting_failed_evidence(self):
        import core_source_gaps as gaps
        import foundation_materials as materials
        import foundation_quarantine as quarantine
        from tests.test_foundation_materials import FoundationMaterialsTests
        from tests.test_foundation_quarantine import QuarantineTests

        request, head = self.gap_request()
        material_fixture = FoundationMaterialsTests()
        material_fixture.setUp()
        self.addCleanup(material_fixture.doCleanups)
        admitted = material_fixture.ingest()
        quarantine_fixture = QuarantineTests()
        quarantine_fixture.setUp()
        self.addCleanup(quarantine_fixture.doCleanups)
        opaque = quarantine_fixture.create()
        requests = [self.request(), request,
                    self.request(package_id="library-001", kind="RESEARCH_LIBRARY",
                                 local_root=material_fixture.library, expected_content_hash=admitted["library_hash"]),
                    self.request(package_id="quarantine-001", kind="QUARANTINED_ORIGINALS",
                                 local_root=quarantine_fixture.root / "quarantine",
                                 expected_content_hash=opaque["quarantine_hash"])]
        before = {row["package_id"]: self.retained_inventory(row["local_root"]) for row in requests}
        try:
            manifest = self.build(requests)
        except ValueError as error:
            self.fail("finite mixed package must include its retained gap ledger: " + str(error))
        gap_row = next(row for row in manifest["packages"] if row["package_id"] == "gaps-001")
        self.assertEqual(gap_row["files"], before["gaps-001"]["files"])
        self.assertIn("write-evidence/retained-empty", gap_row["directories"])
        self.assertIn("write-evidence/failed-copy.partial", gap_row["files"])
        self.assertEqual(gap_row["semantics"]["validator"], "core_source_gaps.verify_retained")
        self.assertEqual(gap_row["semantics"]["head_hash"], head)
        self.assertEqual(gap_row["semantics"]["event_count"], 1)
        self.assertEqual(gap_row["semantics"]["source_count"], 1)
        self.assertEqual(gap_row["semantics"]["logical_call_count"], 1)
        self.assertFalse(gap_row["semantics"]["automatic_retry"])
        self.assertEqual(gap_row["semantics"]["research_readiness"], "NOT_EVALUATED")

        moved = {}
        for row in requests:
            identity, source = row["package_id"], row["local_root"]
            self.assertEqual(self.retained_inventory(source), before[identity])
            destination = self.root / ("cold-" + identity)
            shutil.copytree(source, destination)
            moved[identity] = destination
            source.rename(source.with_name(source.name + "-unavailable"))
        checked = self.verify(manifest, moved)
        self.assertEqual(checked["verified_package_ids"], ["backup-001", "gaps-001", "library-001", "quarantine-001"])
        self.assertEqual(checked["package_bytes"], "MATCH")
        self.assertEqual(checked["requirements"]["off_machine_storage"], "NOT_ATTESTED")
        self.assertEqual(checked["human_review"], "PENDING")
        self.assertFalse(checked["production_authority"])
        self.assertFalse(checked["trading_authority"])
        reopened = gaps.view(moved["gaps-001"], expected_head=head, observed_at="2099-01-01T00:00:00Z")
        self.assertEqual(len(reopened["scopes"]), 1)
        self.assertEqual(reopened["scopes"][0]["status"], "DATA_BLOCKED")
        self.assertEqual(reopened["scopes"][0]["attempts_seen"], 1)
        self.assertEqual(materials.verify_library(moved["library-001"],
                         expected_library_hash=admitted["library_hash"])["materials"][0]["rights"], materials.RIGHTS)
        self.assertFalse(quarantine.verify_quarantine(moved["quarantine-001"],
                         expected_quarantine_hash=opaque["quarantine_hash"])["policy"]["research_use_allowed"])
        for identity, destination in moved.items():
            self.assertEqual(self.retained_inventory(destination), before[identity])

    def test_core_gap_external_complete_inventory_pin_precedes_semantic_acceptance(self):
        import core_source_gaps as gaps

        request, _head = self.gap_request()
        inventory = self.retained_inventory(request["local_root"])
        pins = ["f" * 64, ev.sealed(inventory["files"]),
                ev.sealed({**inventory, "directories": []}),
                ev.sealed({**inventory, "total_bytes": inventory["total_bytes"] + 1})]
        with mock.patch.object(gaps, "verify_retained", side_effect=AssertionError("semantic reader ran before pin refusal")):
            for pin in pins:
                with self.subTest(pin=pin), self.assertRaisesRegex(ValueError, "EXPECTED_CONTENT_HASH_MISMATCH"):
                    self.build([{**request, "expected_content_hash": pin}])
        self.assertEqual(self.retained_inventory(request["local_root"]), inventory)

    def test_core_gap_correct_inventory_does_not_bypass_existing_chain_validator(self):
        request, _head = self.gap_request()
        event = next((request["local_root"] / "events").iterdir())
        value = ev.parse(event.read_bytes())
        value["previous_hash"] = "f" * 64
        event.write_bytes(ev.canonical(value).encode())
        request["expected_content_hash"] = ev.sealed(self.retained_inventory(request["local_root"]))
        with self.assertRaisesRegex(ValueError, "GAPS_CHAIN_INVALID"):
            self.build([request])

    def test_core_gap_cold_tamper_missing_extra_and_empty_directory_refuse_original_pin(self):
        request, _head = self.gap_request()
        manifest = self.build_gap(request)
        for change in ("tampered", "missing", "extra", "directory"):
            destination = self.root / ("gap-" + change)
            shutil.copytree(request["local_root"], destination)
            if change == "tampered":
                (destination / "metadata.json").write_bytes(b"{}")
            elif change == "missing":
                (destination / "write-evidence" / "failed-copy.partial").unlink()
            elif change == "extra":
                (destination / "write-evidence" / "extra.partial").write_bytes(b"unexpected")
            else:
                (destination / "write-evidence" / "another-empty").mkdir()
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "EXPECTED_CONTENT_HASH_MISMATCH"):
                self.verify(manifest, {"gaps-001": destination})

    def test_core_gap_authority_cannot_be_promoted_by_resealing_metadata_or_handoff(self):
        request, _head = self.gap_request()
        manifest = self.build_gap(request)
        for key, value in (("production_authority", True), ("automatic_retry", True),
                           ("rights", "VERIFIED"), ("research_readiness", "APPROVED")):
            changed = copy.deepcopy(manifest)
            changed["packages"][0]["semantics"][key] = value
            self.reseal_manifest(changed)
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, "DESTINATION_PACKAGE_BINDING_MISMATCH"):
                self.verify(changed, {"gaps-001": request["local_root"]})
        metadata = request["local_root"] / "metadata.json"
        value = ev.parse(metadata.read_bytes())
        value["production_authority"] = True
        metadata.write_bytes(ev.canonical(value).encode())
        request["expected_content_hash"] = ev.sealed(self.retained_inventory(request["local_root"]))
        with self.assertRaisesRegex(ValueError, "GAPS_METADATA_INVALID"):
            self.build([request])

    def test_core_gap_inventory_is_rechecked_after_semantic_validation(self):
        import core_source_gaps as gaps

        request, _head = self.gap_request()
        original = gaps.verify_retained

        def append_after_reopen(root):
            result = original(root)
            (root / "write-evidence" / "concurrent.partial").write_bytes(b"concurrent failed evidence")
            return result

        with mock.patch.object(gaps, "verify_retained", side_effect=append_after_reopen):
            with self.assertRaisesRegex(ValueError, "PACKAGE_CHANGED"):
                self.build([request])


if __name__ == "__main__":
    unittest.main()
