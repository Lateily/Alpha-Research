from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/llm'))
import foundation_local_store as storage
import foundation_materials as materials
import workbench_evidence as ev


class LocalStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        from tests.test_foundation_materials import FoundationMaterialsTests
        fixture = FoundationMaterialsTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        receipt = fixture.ingest()
        self.packages = [{'package_id': 'originals', 'kind': 'RESEARCH_LIBRARY',
                          'local_root': fixture.library, 'expected_content_hash': receipt['library_hash']}]

    def create(self, destination=None):
        return storage.create_generation(self.packages, destination or self.root / 'generation',
                                         created_at='2026-11-05T12:00:00+00:00')

    def test_immutable_copy_and_cold_restore(self):
        result = self.create()
        self.assertEqual(result['off_machine'], 'NOT_ATTESTED')
        restored = storage.restore_generation(self.root / 'generation', self.root / 'restored',
                                             expected_generation_hash=result['generation_hash'])
        self.assertEqual(restored['generation_hash'], result['generation_hash'])
        with self.assertRaises((ValueError, OSError)):
            self.create()

    def test_corruption_and_extra_file_refused(self):
        result = self.create()
        (self.root / 'generation/extra.txt').write_text('unexpected')
        with self.assertRaises(ValueError):
            storage.restore_generation(self.root / 'generation', self.root / 'restored',
                                         expected_generation_hash=result['generation_hash'])
        self.assertFalse((self.root / 'restored').exists())

    def test_overlap_and_wrong_external_pin(self):
        with self.assertRaises(ValueError):
            self.create(Path(self.packages[0]['local_root']) / 'unsafe')
        result = self.create()
        with self.assertRaises(ValueError):
            storage.restore_generation(self.root / 'generation', self.root / 'restored',
                                         expected_generation_hash='0' * 64)
