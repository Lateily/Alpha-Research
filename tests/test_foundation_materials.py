"""Deferred materials regressions: authored only; NOT_RUN in foundation wave 3."""
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/llm"))

import foundation_materials as materials
import workbench_evidence as ev


class FoundationMaterialsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir(mode=0o700)
        self.library = self.root / "library"
        self.original = b"%PDF-1.7\r\nSynthetic original bytes.\r\n%%EOF\r\n"
        self.source.joinpath("filing.pdf").write_bytes(self.original)

    def row(self, **changes):
        row = {"material_id": "issuer-filing", "kind": "original", "version": "v1",
               "title": "Synthetic issuer filing", "industry_key": "801010",
               "industry_taxonomy": "SW", "taxonomy_version": "2021",
               "ts_code": "600000.SH", "trade_date": "20200103", "run_id": "research-001",
               "code_sha": "a" * 40, "published_at": "2020-01-02T08:00:00+08:00",
               "available_at": "2020-01-02T09:00:00+08:00", "cutoff_at": "2020-01-03T15:00:00+08:00",
               "provenance": {"publisher": "Synthetic issuer", "provider_id": "issuer-site",
                              "source_locator": "https://issuer.example.invalid/filing/2020.pdf",
                              "captured_at": "2020-01-02T10:00:00+08:00"},
               "original_refs": [], "files": [{"source_path": "filing.pdf",
                   "sha256": hashlib.sha256(self.original).hexdigest(), "size_bytes": len(self.original)}]}
        row.update(changes)
        return row

    def manifest(self, rows=None):
        return {"schema": "ar.material-intake.v1", "library_id": "synthetic-private-library",
                "created_at": "2020-01-06T18:00:00+08:00", "materials": rows or [self.row()]}

    def ingest(self, manifest=None, library=None):
        return materials.ingest_material(self.source, library or self.library, manifest or self.manifest())

    def derived(self, original, **changes):
        raw = b"Synthetic thesis, no formal approval.\n"
        self.source.joinpath("thesis.md").write_bytes(raw)
        return self.row(material_id="issuer-thesis", kind="thesis", title="Synthetic thesis",
                        provenance=None, original_refs=[original["files"][0]["sha256"]],
                        files=[{"source_path": "thesis.md", "sha256": hashlib.sha256(raw).hexdigest(),
                                "size_bytes": len(raw)}], **changes)

    def assert_labels(self, result):
        for key, value in materials.LABELS.items():
            self.assertIs(type(result[key]), type(value))
            self.assertEqual(result[key], value)
        self.assertEqual(result["status"], "IMPLEMENTED_UNTESTED")

    def test_exact_original_and_complete_portable_inventory(self):
        receipt = self.ingest()
        self.assert_labels(receipt)
        reopened = materials.verify_library(self.library, expected_library_hash=receipt["library_hash"])
        actual = {path.relative_to(self.library).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in self.library.rglob("*") if path.is_file()}
        self.assertEqual(reopened["files"], actual)
        self.assertIn("library.json", actual)
        self.assertTrue(any(name.endswith("registration.json") for name in actual))
        name = next(name for name in actual if name.endswith(".pdf"))
        self.assertEqual(self.library.joinpath(name).read_bytes(), self.original)
        self.assertEqual(self.source.joinpath("filing.pdf").read_bytes(), self.original)
        row = reopened["materials"][0]
        self.assertEqual(row["rights"], materials.RIGHTS)
        self.assertEqual(row["provenance"], self.row()["provenance"])
        self.assertEqual(reopened["hash_binding"], "MATCHED_EXTERNAL_EXPECTATION")

    def test_exact_query_filters_and_reopen_tampering(self):
        receipt = self.ingest()
        found = materials.query_library(self.library, industry_key="801010", trade_date="20200103", ts_code="600000.SH")
        self.assertEqual(len(found["materials"]), 1)
        self.assertEqual(found["files"], receipt["files"])
        self.assertEqual(materials.query_library(self.library, industry_key="other")["materials"], [])
        blob = next(name for name in receipt["files"] if name.endswith(".pdf"))
        self.library.joinpath(blob).write_bytes(self.original.replace(b"original", b"tampered"))
        with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"):
            materials.query_library(self.library)

    def test_wrong_external_source_hash_does_not_commit(self):
        manifest = self.manifest()
        manifest["materials"][0]["files"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "ORIGINAL_HASH_MISMATCH"):
            self.ingest(manifest)
        self.assertEqual(list(self.library.glob("registrations/*/registration.json")), [])
        with self.assertRaisesRegex(ValueError, "INTERRUPTED_REGISTRATION_QUARANTINED"):
            materials.verify_library(self.library)

    def test_external_library_hash_metadata_tamper_and_extra_files(self):
        receipt = self.ingest()
        with self.assertRaisesRegex(ValueError, "EXPECTED_LIBRARY_HASH_MISMATCH"):
            materials.verify_library(self.library, expected_library_hash="0" * 64)
        marker = self.library / "library.json"
        marker.write_bytes(marker.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "METADATA_NOT_CANONICAL"):
            materials.verify_library(self.library)
        marker.write_text(ev.canonical(materials._marker(receipt["library_id"])))
        self.library.joinpath("extra.txt").write_text("unregistered")
        with self.assertRaises(ValueError):
            materials.verify_library(self.library)

    def test_same_registration_and_identity_never_replace(self):
        first = self.ingest()
        before = {name: self.library.joinpath(name).read_bytes() for name in first["files"]}
        with self.assertRaisesRegex(ValueError, "REGISTRATION_ALREADY_EXISTS"):
            self.ingest()
        changed = self.manifest()
        changed["materials"][0]["title"] = "Conflicting same version"
        with self.assertRaisesRegex(ValueError, "DUPLICATE_IDENTITY"):
            self.ingest(changed)
        self.assertEqual(before, {name: self.library.joinpath(name).read_bytes() for name in before})

    def test_new_explicit_version_and_taxonomy_conflict(self):
        self.ingest()
        revised = b"%PDF-1.7\nNew immutable original version\n%%EOF\n"
        self.source.joinpath("revised.pdf").write_bytes(revised)
        files = [{"source_path": "revised.pdf", "sha256": hashlib.sha256(revised).hexdigest(), "size_bytes": len(revised)}]
        receipt = self.ingest(self.manifest([self.row(version="v2", files=files)]))
        self.assertEqual([row["version"] for row in receipt["materials"]], ["v1", "v2"])
        conflict = self.manifest([self.row(version="v3", taxonomy_version="2099", files=files)])
        with self.assertRaisesRegex(ValueError, "IDENTITY_TAXONOMY_CONFLICT"):
            self.ingest(conflict)

    def test_derived_post_cutoff_draft_is_valid_but_not_pit_attested(self):
        original = self.row()
        draft = self.derived(original, published_at="2020-01-06T10:00:00+08:00",
                             available_at="2020-01-06T11:00:00+08:00")
        receipt = self.ingest(self.manifest([original, draft]))
        thesis = next(row for row in receipt["materials"] if row["kind"] == "thesis")
        self.assertGreater(thesis["available_at"], thesis["cutoff_at"])
        self.assertEqual(thesis["artifact_pit_use"], "NOT_ATTESTED")
        self.assertIs(thesis["prospective_sample_eligible"], False)

    def test_retrospective_original_and_derived_capture_are_explicit(self):
        original = self.row()
        original["provenance"]["captured_at"] = "2020-01-06T09:00:00+08:00"
        draft = self.derived(original, published_at="2020-01-06T10:00:00+08:00",
                             available_at="2020-01-06T11:00:00+08:00")
        receipt = self.ingest(self.manifest([original, draft]))
        for row in receipt["materials"]:
            self.assertEqual(row["point_in_time_capture_status"], "RETROSPECTIVE_CAPTURE")
            self.assertIs(row["prospective_sample_eligible"], False)
            self.assertEqual(row["artifact_pit_use"], "NOT_ATTESTED")
        self.assertEqual(receipt["materials"][0]["available_at"], original["available_at"])

    def test_source_known_after_cutoff_is_refused_even_with_later_capture(self):
        original = self.row(available_at="2020-01-06T08:00:00+08:00")
        original["provenance"]["captured_at"] = "2020-01-06T09:00:00+08:00"
        with self.assertRaisesRegex(ValueError, "ORIGINAL_NOT_AVAILABLE_AT_CUTOFF"):
            self.ingest(self.manifest([original]))
        original = self.row(cutoff_at="2020-01-06T08:00:00+08:00", trade_date="20200106",
                            available_at="2020-01-06T08:00:00+08:00")
        original["provenance"]["captured_at"] = "2020-01-06T09:00:00+08:00"
        draft = self.derived(original, published_at="2020-01-06T10:00:00+08:00",
                             available_at="2020-01-06T11:00:00+08:00")
        with self.assertRaisesRegex(ValueError, "ORIGINAL_NOT_AVAILABLE_AT_CUTOFF"):
            self.ingest(self.manifest([original, draft]))

    def test_missing_original_reference_and_provenance_are_refused(self):
        original = self.row()
        draft = self.derived(original)
        with self.assertRaisesRegex(ValueError, "ORIGINAL_NOT_REGISTERED"):
            self.ingest(self.manifest([draft]))
        for provenance in (None, {}, {**original["provenance"], "source_locator": "file:///private/secret"},
                           {**original["provenance"], "source_locator": "https://user:pass@example.invalid/report"},
                           {**original["provenance"], "source_locator": "https://example.invalid/report?key=synthetic"},
                           {**original["provenance"], "captured_at": "2021-01-01T00:00:00Z"}):
            with self.subTest(provenance=provenance), self.assertRaises(ValueError):
                self.ingest(self.manifest([self.row(provenance=provenance)]))

    def test_time_date_and_unverified_rights_conflicts(self):
        changes = [{"published_at": "2020-01-04T00:00:00Z"}, {"cutoff_at": "2020-01-07T00:00:00Z"},
                   {"trade_date": "20200230"}, {"available_at": "2020-01-02T09:00:00"},
                   {"available_at": "2020-01-02T09:00:00+00:60"},
                   {"human_review": "APPROVED"}, {"production_authority": True},
                   {"rights": {**materials.RIGHTS, "sharing_allowed": True}},
                   {"rights": {**materials.RIGHTS, "model_use_allowed": True}},
                   {"rights": {**materials.RIGHTS, "status": "VERIFIED"}},
                   {"prospective_sample_eligible": True}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.ingest(self.manifest([self.row(**change)]))
        self.assertFalse(self.library.exists())

    def test_case_or_review_registration_is_never_approval(self):
        original = self.row()
        case = self.derived(original)
        case["kind"] = "case"
        receipt = self.ingest(self.manifest([original, case]))
        self.assertIs(receipt["limitations"]["formal_case_approval"], False)
        for row in receipt["materials"]:
            self.assertEqual(row["human_review"], "PENDING")
            self.assertEqual(row["rights"], materials.RIGHTS)

    def test_duplicate_file_identity_traversal_and_bounds(self):
        original = self.row()
        bad = [self.manifest([original, copy.deepcopy(original)])]
        duplicate_file = self.row()
        duplicate_file["files"].append(copy.deepcopy(duplicate_file["files"][0]))
        bad.append(self.manifest([duplicate_file]))
        for path in ("../filing.pdf", "/filing.pdf", "sub/../filing.pdf", "credentials.txt", "payload.py", "payload.zip"):
            row = self.row()
            row["files"][0]["source_path"] = path
            bad.append(self.manifest([row]))
        for size in (True, 0, materials.MAX_FILE_BYTES + 1):
            row = self.row()
            row["files"][0]["size_bytes"] = size
            bad.append(self.manifest([row]))
        for manifest in bad:
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                self.ingest(manifest)
        cyclic = self.manifest()
        cyclic["loop"] = cyclic
        with self.assertRaisesRegex(ValueError, "JSON_LIMIT"):
            self.ingest(cyclic)

    def test_empty_owned_root_allowed_unrecognized_root_is_unchanged(self):
        self.library.mkdir(mode=0o700)
        self.ingest()
        other = self.root / "repository-or-state"
        other.mkdir(mode=0o700)
        other.joinpath("sentinel").write_bytes(b"leave me alone")
        with self.assertRaises(ValueError):
            self.ingest(library=other)
        self.assertEqual({path.name for path in other.iterdir()}, {"sentinel"})
        self.assertEqual(other.joinpath("sentinel").read_bytes(), b"leave me alone")
        with self.assertRaisesRegex(ValueError, "ROOTS_MUST_BE_DISJOINT"):
            self.ingest(library=self.source / "nested")

    def test_symlinks_hardlinks_and_executable_originals_are_refused(self):
        source = self.source / "filing.pdf"
        outside = self.root / "outside.pdf"
        outside.write_bytes(self.original)
        source.unlink()
        source.symlink_to(outside)
        with self.assertRaises((ValueError, OSError)):
            self.ingest(library=self.root / "link-library")
        source.unlink()
        os.link(outside, source)
        with self.assertRaisesRegex(ValueError, "LINK_INVALID"):
            self.ingest(library=self.root / "hardlink-library")
        source.unlink()
        source.write_bytes(self.original)
        source.chmod(0o700)
        with self.assertRaises(ValueError):
            self.ingest(library=self.root / "executable-library")
        parent_link = self.root / "linked-parent"
        parent_link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            self.ingest(library=parent_link / "through-link")

    def test_reopened_library_hardlink_is_rejected(self):
        receipt = self.ingest()
        blob = self.library / next(name for name in receipt["files"] if name.endswith(".pdf"))
        os.link(blob, self.root / "alias.pdf")
        with self.assertRaisesRegex(ValueError, "LINK_INVALID"):
            materials.verify_library(self.library)

    def test_interruption_quarantines_without_deletion_or_retry(self):
        publish = materials.backup.write_new

        def interrupted(path, raw, **kwargs):
            if Path(path).name == "registration.json":
                raise OSError("synthetic interruption before registration commit")
            return publish(path, raw, **kwargs)

        with mock.patch.object(materials.backup, "write_new", side_effect=interrupted):
            with self.assertRaises(OSError):
                self.ingest()
        before = sorted(path.relative_to(self.library).as_posix() for path in self.library.rglob("*"))
        for operation in (lambda: materials.verify_library(self.library), lambda: self.ingest()):
            with self.assertRaisesRegex(ValueError, "INTERRUPTED_REGISTRATION_QUARANTINED"):
                operation()
        self.assertEqual(before, sorted(path.relative_to(self.library).as_posix() for path in self.library.rglob("*")))

    def test_secret_shaped_content_active_pdf_and_binary_disguise(self):
        payloads = [("unsafe.txt", b"Authorization: " + b"Bearer synthetic-materials-only"),
                    ("active.pdf", b"%PDF-1.7\n/JavaScript (untrusted)\n%%EOF\n"),
                    ("disguised.txt", b"PK\x03\x04binary archive"),
                    ("invalid.json", b'{"x":1,"x":2}')]
        for index, (name, raw) in enumerate(payloads):
            self.source.joinpath(name).write_bytes(raw)
            row = self.row(files=[{"source_path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}])
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.ingest(self.manifest([row]), library=self.root / ("refused-" + str(index)))


if __name__ == "__main__":
    unittest.main()
