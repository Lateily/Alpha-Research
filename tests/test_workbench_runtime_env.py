"""Offline runtime integrity boundaries; real rebuilds are separate operation evidence."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/llm'))
import workbench_evidence as ev


class RuntimeEnvironmentTests(unittest.TestCase):
    def module(self):
        import workbench_runtime_env
        return workbench_runtime_env

    def fixture(self, root):
        m = self.module()
        root.mkdir(mode=0o700)
        (root / 'venv').mkdir()
        (root / 'venv/probe').write_bytes(b'not an executable; integrity fixture only')
        value = {'schema': 'ar.isolated-runtime.v1', 'lock_hash': ev.sealed(m.LOCK),
                 'python_version': '3.12.14', 'base_executable': str(Path(sys.executable).resolve()),
                 'base_hash': m.file_hash(Path(sys.executable).resolve()),
                 'dependencies': {'pypdf': '6.10.0'}, 'files': m.inventory(root),
                 'scope': 'ISOLATED_ONLY', 'production_authority': False}
        raw = ev.canonical(value).encode()
        (root / 'runtime.json').write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def test_external_pin_and_exact_inventory(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / 'runtime'
            pin = self.fixture(root)
            self.assertEqual(m.verify_environment(root, pin)['dependencies'], {'pypdf': '6.10.0'})
            with self.assertRaisesRegex(ValueError, 'RUNTIME_PIN'):
                m.verify_environment(root, '0' * 64)
            with self.assertRaises(ValueError): m.verify_environment(root, None)
            (root / 'venv/extra').write_bytes(b'unknown')
            with self.assertRaisesRegex(ValueError, 'RUNTIME_FILES'):
                m.verify_environment(root, pin)

    def test_changed_bytes_and_resealed_manifest_refused(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / 'runtime'; pin = self.fixture(root)
            (root / 'venv/probe').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'RUNTIME_FILES'): m.verify_environment(root, pin)
            value = json.loads((root / 'runtime.json').read_text()); value['files'] = m.inventory(root)
            (root / 'runtime.json').write_text(ev.canonical(value))
            with self.assertRaisesRegex(ValueError, 'RUNTIME_PIN'): m.verify_environment(root, pin)

    def test_links_and_base_change_refused(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / 'runtime'; pin = self.fixture(root)
            (root / 'venv/probe').unlink(); (root / 'venv/probe').symlink_to('/etc/hosts')
            with self.assertRaises(ValueError): m.verify_environment(root, pin)
            (root / 'venv/probe').unlink(); (root / 'venv/probe').write_bytes(b'not an executable; integrity fixture only')
            with patch.object(m, 'file_hash', return_value='0' * 64):
                with self.assertRaises(ValueError): m.verify_environment(root, pin)

    def test_wrong_missing_wheels_never_execute_or_create_output(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(); wheels = base / 'wheels'; wheels.mkdir()
            with patch.object(m.subprocess, 'run', side_effect=AssertionError('UNVERIFIED_WHEEL_EXECUTED')) as execute:
                for fake in (False, True):
                    if fake:
                        for name in m.LOCK['wheels']: (wheels / name).write_bytes(b'not official')
                    with self.assertRaisesRegex(ValueError, 'RUNTIME_WHEEL'):
                        m.build_environment(base / 'out', wheels)
                    self.assertFalse((base / 'out').exists())
                execute.assert_not_called()

    def test_existing_output_overlap_and_failed_build_not_accepted(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(); output = base / 'existing'; output.mkdir()
            with self.assertRaisesRegex(ValueError, 'RUNTIME_NEW_ROOT'):
                m.build_environment(output, base)
            with self.assertRaises(ValueError): m.build_environment(base / 'new', base / 'new/wheels')
            (output / 'BUILD_STARTED').write_bytes(b'interrupted')
            with self.assertRaises(ValueError): m.verify_environment(output, '1' * 64)

    def test_lock_cannot_be_resealed_to_add_dependencies_or_network(self):
        m = self.module()
        for key, value in (('index', 'https://example.com'), ('dependencies', {'pypdf':'latest'})):
            lock = copy.deepcopy(m.LOCK); lock[key] = value
            with self.assertRaisesRegex(ValueError, 'RUNTIME_LOCK'): m.validate_lock(lock)

    def test_in_place_change_and_replacement_during_hash_are_refused(self):
        m=self.module()
        for replacement in (False,True):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve(); target=root/'large'; target.write_bytes(b'A'*(2*1024*1024))
                original=m.os.fdopen; mutated=[]
                class Stream:
                    def __init__(self, stream): self.stream=stream
                    def __enter__(self): self.stream.__enter__(); return self
                    def __exit__(self,*args): return self.stream.__exit__(*args)
                    def fileno(self): return self.stream.fileno()
                    def read(self,size):
                        data=self.stream.read(size)
                        if not mutated:
                            if replacement:
                                target.rename(root/'retained-original'); target.write_bytes(b'B'*(2*1024*1024))
                            else:
                                with target.open('r+b') as writer: writer.write(b'B'*1024)
                            mutated.append(True)
                        return data
                with patch.object(m.os,'fdopen',side_effect=lambda *a,**kw:Stream(original(*a,**kw))):
                    with self.assertRaisesRegex(ValueError,'RUNTIME_FILE_CHANGED'): m.file_hash(target)


if __name__ == '__main__': unittest.main()
