"""Deferred opaque retention cases; quarantined data never becomes research input."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/llm"))
import foundation_quarantine as quarantine
from foundation_preservation import build_preservation_manifest, verify_preservation_copy
import workbench_evidence as ev


class QuarantineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.source = self.root / "source"; self.source.mkdir()
        self.raw = b"%PDF-1.4\n/OpenAction opaque synthetic bytes; never executed\n%%EOF\n"
        (self.source / "original.PDF").write_bytes(self.raw)
        self.row = {"kind": "original", "material_id": "cninfo-fixture", "ts_code": "600000.SH",
                    "provenance": {"source_locator": "https://static.cninfo.com.cn/finalpage/2020-01-01/1234567890.PDF"},
                    "files": [{"source_path": "original.PDF", "sha256": ev.sha(self.raw), "size_bytes": len(self.raw)}]}

    def create(self):
        return quarantine.create_quarantine(self.source, self.root / "quarantine", [self.row], created_at="2026-11-02T00:00:00Z")

    def test_opaque_original_is_preserved_not_admitted_and_full_package_can_reopen(self):
        result = self.create()
        self.assertEqual((self.root / "quarantine/objects" / (ev.sha(self.raw) + ".pdf")).read_bytes(), self.raw)
        self.assertEqual(result["policy"], quarantine.POLICY)
        self.assertFalse(result["policy"]["research_use_allowed"])
        manifest = build_preservation_manifest([{"package_id": "quarantine", "kind": "QUARANTINED_ORIGINALS",
                                               "local_root": self.root / "quarantine", "expected_content_hash": result["quarantine_hash"]}],
                                              created_at="2026-11-02T00:00:00Z")
        checked = verify_preservation_copy(manifest, {"quarantine": self.root / "quarantine"},
                                          expected_preservation_hash=manifest["preservation_hash"])
        self.assertEqual(checked["package_bytes"], "MATCH")
        self.assertEqual(checked["requirements"]["off_machine_storage"], "NOT_ATTESTED")

    def test_self_resealed_policy_cannot_enable_research_or_rendering(self):
        self.create()
        path = self.root / "quarantine/manifest.json"
        for field in ("research_use_allowed", "render_allowed", "execution_allowed", "transfer_authority"):
            value = json.loads(path.read_text()); value["policy"][field] = True
            value["quarantine_hash"] = ev.sealed({key: row for key, row in value.items() if key != "quarantine_hash"})
            path.write_text(ev.canonical(value))
            with self.subTest(field=field), self.assertRaises(ValueError):
                quarantine.verify_quarantine(self.root / "quarantine")
            value["policy"][field] = False
            value["quarantine_hash"] = ev.sealed({key: row for key, row in value.items() if key != "quarantine_hash"})
            path.write_text(ev.canonical(value))

    def test_wrong_source_hash_or_existing_root_never_overwrites(self):
        (self.source / "original.PDF").write_bytes(self.raw + b"changed")
        with self.assertRaises(ValueError): self.create()
        self.assertFalse((self.root / "quarantine").exists())
        (self.source / "original.PDF").write_bytes(self.raw)
        self.create()
        with self.assertRaises(ValueError): self.create()

    def test_missing_extra_or_modified_member_refuses_reopen(self):
        result = self.create()
        root = self.root / "quarantine"
        (root / "extra.txt").write_bytes(b"unexpected")
        with self.assertRaises(ValueError): quarantine.verify_quarantine(root, expected_quarantine_hash=result["quarantine_hash"])
        (root / "extra.txt").unlink()
        (root / "objects" / (ev.sha(self.raw) + ".pdf")).write_bytes(self.raw + b"changed")
        with self.assertRaises(ValueError): quarantine.verify_quarantine(root, expected_quarantine_hash=result["quarantine_hash"])

    def test_symlink_parent_cannot_create_inside_original_source(self):
        link = self.root / "linked-parent"
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            quarantine.create_quarantine(self.source, link / "new-quarantine", [self.row],
                                         created_at="2026-11-02T00:00:00Z")
        self.assertEqual(sorted(path.name for path in self.source.iterdir()), ["original.PDF"])


if __name__ == "__main__": unittest.main()
