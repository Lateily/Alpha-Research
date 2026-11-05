from pathlib import Path
import sys
import tempfile
import unittest
import os
from unittest import mock

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

    def test_parent_alias_never_writes_into_source(self):
        source = Path(self.packages[0]['local_root'])
        alias = source.parent / 'alias'; alias.mkdir()
        with self.assertRaises(ValueError): self.create(alias / '..' / source.name / 'nested')
        self.assertFalse((source / 'nested').exists())
        materials.verify_library(source, expected_library_hash=self.packages[0]['expected_content_hash'])

    def test_concurrent_destination_is_not_adopted(self):
        original = storage._destination
        def race(*args):
            target = original(*args); target.mkdir(); (target / 'unrelated.txt').write_text('not in request')
            return target
        with mock.patch.object(storage, '_destination', side_effect=race):
            with self.assertRaises((ValueError, OSError)): self.create()
        self.assertFalse((self.root / 'generation/generation.json').exists())

    def test_payload_files_are_synced_before_success(self):
        seen = set(); original = os.fsync
        def sync(fd):
            info = os.fstat(fd); seen.add((info.st_dev, info.st_ino)); return original(fd)
        with mock.patch.object(os, 'fsync', side_effect=sync):
            result = self.create()
            storage.restore_generation(self.root / 'generation', self.root / 'restored',
                                       expected_generation_hash=result['generation_hash'])
        for base in (self.root / 'generation', self.root / 'restored'):
            for path in base.rglob('*'):
                if path.is_file():
                    info = path.stat(); self.assertIn((info.st_dev, info.st_ino), seen, str(path))

    def test_relative_valid_source_is_normalized(self):
        source = Path(self.packages[0]['local_root']); previous = Path.cwd()
        try:
            os.chdir(source.parent)
            self.packages[0]['local_root'] = source.name
            result = self.create()
        finally: os.chdir(previous)
        self.assertEqual(storage.verify_generation(self.root / 'generation',
            expected_generation_hash=result['generation_hash'])['generation_hash'], result['generation_hash'])
