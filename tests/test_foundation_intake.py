"""Deferred intake regressions; not full acceptance or real provider evidence."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/llm"))
import foundation_intake as intake
import foundation_materials as materials
import workbench_evidence as ev


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"; self.source.mkdir()
        self.company = self.source / "sources/600000.SH"; (self.company / "raw").mkdir(parents=True)
        self.pdf = b"%PDF-1.4\nsynthetic original without active features\n%%EOF\n"
        (self.company / "raw/original.PDF").write_bytes(self.pdf)
        created = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.document = {"schema": "loop_v1.source_manifest.v1", "ticker": "600000.SH",
                         "originals": {"source-1": {"path": "raw/original.PDF", "sha256": ev.sha(self.pdf),
                            "company": "600000.SH", "format": "pdf", "published_on": "20200101",
                            "origin": "https://static.cninfo.com.cn/finalpage/2020-01-01/1234567890.PDF",
                            "observed_at": "2020-01-02T00:00:00Z"}},
                         "capture_meta": {"source-1": {"bytes": len(self.pdf), "http_status": 200, "title": "Synthetic original"}}}
        self.anchor_path = self.company / "source_manifest.json"
        self.anchor_path.write_bytes(ev.canonical(self.document).encode())
        self.request = {"schema": "ar.cninfo-intake-request.v1", "source_root": str(self.source),
                        "manifests": [{"ts_code": "600000.SH", "relative_path": "sources/600000.SH/source_manifest.json",
                                       "expected_sha256": ev.sha(self.anchor_path.read_bytes())}],
                        "classification": None, "run_id": "synthetic-intake", "library_id": "synthetic-library",
                        "research_date": datetime.now(timezone.utc).strftime("%Y%m%d"),
                        "cutoff_at": "2020-01-02T15:00:00+08:00", "created_at": created, "code_sha": "a" * 40}
        self.identity = {"code_sha": "a" * 40, "source_tree_hash": "b" * 64}

    def run_intake(self, request=None, name="operation"):
        with mock.patch.object(intake, "_execution_identity", return_value=self.identity):
            return intake.run_cninfo_intake(request or self.request, self.root / name)

    def test_real_bytes_flow_to_query_pin_and_preservation_without_network(self):
        receipt = self.run_intake()
        self.assertEqual(receipt["registered_originals"], 1)
        self.assertEqual(receipt["status"], "LOCAL_MATERIALS_REGISTERED_PENDING_ACCEPTANCE")
        self.assertEqual(receipt["testing_status"], "NOT_RUN")
        self.assertFalse(receipt["external_upload_performed"])
        records = self.root / "operation/records"
        pin = ev.parse((records / "retention-pin.json").read_bytes())
        self.assertEqual(pin["library_hash"], receipt["library_hash"])
        self.assertEqual(pin["off_machine_retention"], "NOT_ATTESTED")
        query = ev.parse((records / "query-600000.SH.json").read_bytes())
        row = query["materials"][0]
        self.assertEqual(row["provenance"]["publication_precision"]["published_on"], "20200101")
        self.assertEqual(row["industry_key"], "UNSPECIFIED")
        self.assertFalse(row["rights"]["sharing_allowed"])
        copied = next((self.root / "operation/library").glob("registrations/*/files/*.pdf"))
        self.assertEqual(copied.read_bytes(), self.pdf)

    def test_external_manifest_hash_mismatch_has_no_write(self):
        value = copy.deepcopy(self.request); value["manifests"][0]["expected_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "ANCHOR_HASH"):
            self.run_intake(value)
        self.assertFalse((self.root / "operation").exists())

    def test_source_and_classification_anchor_credentials_refused_before_write(self):
        for kind in ("source", "encoded-source", "classification"):
            with self.subTest(kind=kind):
                request = copy.deepcopy(self.request)
                if kind in {"source", "encoded-source"}:
                    document = copy.deepcopy(self.document)
                    document["capture_note"] = "Authorization: Bearer synthetic-review-only"
                    raw = ev.canonical(document).encode()
                    if kind == "encoded-source":
                        credential_fixture = "Authorization: Bearer synthetic-review-only"
                        escaped = "".join("\\u%04x" % ord(char) for char in credential_fixture).encode()
                        raw = raw.replace(credential_fixture.encode(), escaped)
                    self.anchor_path.write_bytes(raw)
                    request["manifests"][0]["expected_sha256"] = ev.sha(self.anchor_path.read_bytes())
                else:
                    self.anchor_path.write_bytes(ev.canonical(self.document).encode())
                    request["manifests"][0]["expected_sha256"] = ev.sha(self.anchor_path.read_bytes())
                    path = self.source / "cohort.md"
                    path.write_bytes(b"Authorization: Bearer synthetic-review-only")
                    request["classification"] = {"industry_key": "semiconductor", "taxonomy_version": "draft-v1",
                        "evidence_path": "cohort.md", "expected_sha256": ev.sha(path.read_bytes())}
                with self.assertRaisesRegex(ValueError, "CREDENTIAL"):
                    self.run_intake(request, name="secret-" + kind)
                self.assertFalse((self.root / ("secret-" + kind)).exists())

    def test_symlink_output_parent_refused_before_any_creation(self):
        link = self.root / "linked-parent"
        link.symlink_to(self.source, target_is_directory=True)
        before = {str(p.relative_to(self.source)): p.read_bytes() if p.is_file() else None
                  for p in self.source.rglob("*")}
        with self.assertRaises((ValueError, OSError)):
            self.run_intake(name="linked-parent/new-operation")
        self.assertEqual(before, {str(p.relative_to(self.source)): p.read_bytes() if p.is_file() else None
                                 for p in self.source.rglob("*")})

    def test_raced_output_parent_cannot_redirect_creation_into_source(self):
        parent = self.root / "new-parent"; parent.mkdir()
        moved = self.root / "held-parent"
        original_mkdir = intake.materials.os.mkdir
        fired = []
        def raced(path, *args, **kwargs):
            if not fired and str(path) in {"new-operation", str(parent / "new-operation")}:
                fired.append(True)
                parent.rename(moved)
                parent.symlink_to(self.source, target_is_directory=True)
            return original_mkdir(path, *args, **kwargs)
        with mock.patch.object(intake.materials.os, "mkdir", side_effect=raced):
            with self.assertRaises((ValueError, OSError)):
                self.run_intake(name="new-parent/new-operation")
        self.assertTrue(fired)
        self.assertFalse((self.source / "new-operation").exists())

    def test_original_hash_mismatch_is_retained_as_blocked_not_registered(self):
        (self.company / "raw/original.PDF").write_bytes(self.pdf + b"changed")
        result = self.run_intake()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["registered_originals"], 0)
        self.assertEqual(len(result["rejected"]), 1)
        self.assertFalse((self.root / "operation/library").exists())

    def test_legacy_shapes_are_explicit_and_ambiguous_shape_is_refused(self):
        value = copy.deepcopy(self.document)
        row = value.pop("originals")["source-1"]
        row.update(source_name="source-1", bytes=len(self.pdf), http_status=200, title="Synthetic")
        value["raw_files"] = [row]
        self.assertEqual(intake._originals(value)[0], "raw_files")
        value["pdf_originals"] = {"source-1": row}
        with self.assertRaisesRegex(ValueError, "AMBIGUOUS"):
            intake._originals(value)

    def test_date_only_precision_and_case_insensitive_pdf_are_preserved(self):
        anchor = self.request["manifests"][0]
        row = intake._material(self.request, anchor, self.document, "source-1", self.document["originals"]["source-1"])
        manifest = intake._manifest(self.request, [row])
        self.assertEqual(materials.inspect_material_source(self.source, manifest)["files"][row["files"][0]["source_path"]], ev.sha(self.pdf))
        row["published_at"] = "2020-01-01T12:00:00+08:00"
        with self.assertRaisesRegex(ValueError, "PUBLICATION_PRECISION_CONFLICT"):
            materials.inspect_material_source(self.source, manifest)

    def test_unknown_request_fields_or_changed_code_and_output_reuse_refused(self):
        value = copy.deepcopy(self.request); value["upload"] = True
        with self.assertRaises(ValueError): self.run_intake(value)
        self.run_intake()
        with self.assertRaises(ValueError): self.run_intake()
        with mock.patch.object(intake, "_execution_identity", side_effect=[self.identity, {"code_sha": "c" * 40}]):
            with self.assertRaisesRegex(ValueError, "CODE_CHANGED"):
                intake.run_cninfo_intake(self.request, self.root / "changed-code")

    def test_cohort_classification_is_not_a_verified_industry_mapping(self):
        path = self.source / "cohort.md"; path.write_bytes(b"Synthetic draft research cohort, not official industry data")
        value = copy.deepcopy(self.request)
        value["classification"] = {"industry_key": "semiconductor", "taxonomy_version": "draft-v1",
                                   "evidence_path": "cohort.md", "expected_sha256": ev.sha(path.read_bytes())}
        result = self.run_intake(value)
        self.assertEqual(result["classification_status"], "UNVERIFIED_RESEARCH_COHORT_NOT_PROVIDER_INDUSTRY")
        query = ev.parse((self.root / "operation/records/query-cohort.json").read_bytes())
        self.assertEqual(query["materials"][0]["industry_taxonomy"], "AR_RESEARCH_COHORT")

    def test_security_refusal_keeps_opaque_bytes_out_of_admitted_library(self):
        raw = b"%PDF-1.4\n/OpenAction synthetic opaque original\n%%EOF\n"
        (self.company / "raw/original.PDF").write_bytes(raw)
        self.document["originals"]["source-1"]["sha256"] = ev.sha(raw)
        self.document["capture_meta"]["source-1"]["bytes"] = len(raw)
        self.anchor_path.write_bytes(ev.canonical(self.document).encode())
        self.request["manifests"][0]["expected_sha256"] = ev.sha(self.anchor_path.read_bytes())
        result = self.run_intake()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["registered_originals"], 0)
        self.assertEqual(result["quarantined_originals"], 1)
        self.assertFalse((self.root / "operation/library").exists())
        manifest = ev.parse((self.root / "operation/records/preservation.json").read_bytes())
        self.assertEqual(manifest["packages"][0]["kind"], "QUARANTINED_ORIGINALS")
        self.assertFalse(manifest["packages"][0]["semantics"]["policy"]["research_use_allowed"])


if __name__ == "__main__": unittest.main()
