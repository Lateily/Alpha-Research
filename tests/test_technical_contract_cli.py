"""Real offline inspection entry point, using invented nonproduction evidence."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
import test_technical_contract as fixtures


GUARD = '''import errno, json, os, pathlib, socket, sqlite3, subprocess
class BlockedSocket(socket.socket):
    def __init__(self, *a, **k): raise AssertionError("SOCKET_FORBIDDEN")
socket.socket = BlockedSocket
socket.create_connection = socket.getaddrinfo = lambda *a, **k: (_ for _ in ()).throw(AssertionError("NETWORK_FORBIDDEN"))
sqlite3.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("SQLITE_FORBIDDEN"))
subprocess.Popen = lambda *a, **k: (_ for _ in ()).throw(AssertionError("SUBPROCESS_FORBIDDEN"))
cfg = json.loads(os.environ.get("INSPECTION_FAULT", "{}"))
original_mkdir, original_open, original_link = os.mkdir, os.open, os.link
original_write, original_fsync = os.write, os.fsync
names = {}
fired = False
def inject(boundary):
    global fired
    if not fired and cfg.get("boundary") == boundary:
        fired = True
        if cfg.get("change"):
            with open(cfg["change"], "ab") as stream: stream.write(b" ")
        if cfg.get("replace"):
            target = cfg["replace"]
            with open(target, "rb") as stream: raw = stream.read()
            os.rename(target, target + ".old")
            with open(target, "wb") as stream: stream.write(raw)
        if cfg.get("alias"):
            os.symlink(cfg["alias"], cfg["output"])
        if cfg.get("parent_alias"):
            parent = os.path.dirname(cfg["output"])
            os.rename(parent, parent + ".old")
            os.symlink(cfg["parent_alias"], parent)
        if cfg.get("stage_alias"):
            pending = os.path.join(cfg["output"], ".manifest.pending")
            os.unlink(pending)
            os.symlink(cfg["stage_alias"], pending)
        if cfg.get("fail"):
            raise OSError(errno.EIO, "SECRET_RAW_EXCEPTION")
def mkdir(path, *a, **k):
    if str(path) == os.path.basename(cfg.get("output", "")): inject("create")
    return original_mkdir(path, *a, **k)
def opener(path, *a, **k):
    if a and a[0] & os.O_CREAT: inject(str(path))
    fd = original_open(path, *a, **k)
    names[fd] = str(path)
    return fd
def link(source, target, *a, **k):
    inject(str(target))
    return original_link(source, target, *a, **k)
def write(fd, raw):
    inject("write:" + names.get(fd, ""))
    return original_write(fd, raw)
def fsync(fd):
    inject("fsync:" + names.get(fd, ""))
    return original_fsync(fd)
os.mkdir, os.open, os.link = mkdir, opener, link
os.write, os.fsync = write, fsync
'''


def inventory(paths):
    result = {}
    for root in paths:
        entries = [root] + (list(root.rglob('*')) if root.is_dir() else [])
        for path in entries:
            info = path.lstat()
            result[str(path)] = (info.st_dev, info.st_ino, info.st_mtime_ns,
                                 hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None)
    return result


class TechnicalInspectionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.TechnicalSemanticTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.ready_observation()
        self.f.seal(register=True)
        self.contract = self.f.contract
        self.output = self.f.root / 'inspection'
        self.guard = self.f.root / 'guard'
        self.guard.mkdir()
        (self.guard / 'sitecustomize.py').write_text(GUARD)

    def run_cli(self, fault=None, output=None, pack_id='synthetic-1'):
        output = output or self.output
        env = dict(os.environ, AR_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1',
                   PYTHONPATH=os.pathsep.join([str(self.guard), str(REPO)]),
                   INSPECTION_FAULT=json.dumps(dict(fault or {}, output=str(output))))
        return subprocess.run([sys.executable, '-B', '-m',
            'experiments.research_workflows.technical_contract', 'inspect',
            '--registry', str(self.f.registry), '--pack-id', pack_id, '--output', str(output)],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=30)

    def inspect(self):
        api = getattr(self.contract, 'inspect_registered_pack', None)
        self.assertTrue(callable(api), 'inspection API must publish bounded new artifacts')
        return api(self.f.registry, 'synthetic-1', self.f.roots, self.output)

    def read(self, name):
        return json.loads((self.output / name).read_bytes())

    def assert_refused(self, completed, code, receipt=True):
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertNotIn('SECRET_RAW_EXCEPTION', completed.stderr)
        self.assertNotIn('Traceback', completed.stderr)
        self.assertFalse((self.output / 'manifest.json').exists())
        if receipt:
            name = 'failure-receipt.json' if (self.output / 'failure-receipt.json').exists() else 'receipt.json'
            self.assertIn(code, self.read(name)['reason_codes'])
            validation = self.read('validation.json') if (self.output / 'validation.json').exists() else None
            if validation and validation['status'] == 'REFUSED':
                self.assertEqual(validation['inputs'], {})
                self.assertEqual(validation['bindings'], {})

    def test_cli_historical_structural_observation_exact_snapshots(self):
        before = inventory([self.f.registry, self.f.pack, self.f.evidence])
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 3, completed.stderr)
        validation = self.read('validation.json')
        self.assertEqual(validation['quality']['structural_input_status'], 'STRUCTURALLY_VALID')
        self.assertIn('HISTORICAL_NO_U4_AUTHORITY', validation['reason_codes'])
        self.assertFalse(validation['authority']['u4_authority'])
        manifest = self.read('manifest.json')
        self.assertTrue(manifest['complete'])
        for relative, digest in manifest['files'].items():
            self.assertEqual(fixtures.sha((self.output / relative).read_bytes()), digest)
        for path in self.f.pack.rglob('*'):
            if path.is_file():
                self.assertEqual((self.output / 'evidence/pack' / path.relative_to(self.f.pack)).read_bytes(), path.read_bytes())
        for key in validation['bindings']['evidence_byte_hashes']:
            alias, relative = key.split(':', 1)
            self.assertEqual((self.output / 'evidence/external' / alias / relative).read_bytes(),
                             (self.f.roots[alias] / relative).read_bytes())
        self.assertEqual((self.output / 'evidence/operator-registry.json').read_bytes(), self.f.registry.read_bytes())
        self.assertEqual(before, inventory([self.f.registry, self.f.pack, self.f.evidence]))

    def test_api_snapshots_exact_noncanonical_source_bytes(self):
        raw = fixtures.encode(self.f.payloads['bars']) + b'  \n'
        self.f.seal(register=True, raw_roles={'bars': raw})
        result = self.inspect()
        self.assertEqual(result['status'], 'DATA_BLOCKED')
        self.assertEqual((self.output / 'evidence/pack/inputs/bars.json').read_bytes(), raw)

    def test_cli_missing_role_receipt_preserves_block(self):
        next(s for s in self.f.manifest['sources'] if s['role'] == 'context')['missing_reason'] = 'NOT_FROZEN'
        self.f.seal(register=True)
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertIsNone(self.read('validation.json')['inputs']['context'])
        self.assertEqual(self.read('receipt.json')['status'], 'DATA_BLOCKED')

    def test_cli_contradictory_input_has_safe_new_failure_receipt(self):
        self.f.payloads['bars']['rows'][-1]['ts_code'] = 'WRONG'
        self.f.seal(register=True)
        completed = self.run_cli()
        self.assert_refused(completed, 'BAR_IDENTITY_MISMATCH')
        validation = self.read('validation.json')
        self.assertIsNone(validation['request'])
        self.assertIsNone(validation['source_manifest'])
        self.assertEqual(validation['inputs'], {})
        self.assertEqual(validation['bindings'], {})

    def test_cli_actual_select_keeps_unavailable_identity_blocked(self):
        self.f.u4()
        self.f.seal(register=True)
        before = inventory([self.f.registry, self.f.pack, self.f.evidence])
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertIn('U4_COHORT_UNBOUND', self.read('validation.json')['reason_codes'])
        self.assertEqual(before, inventory([self.f.registry, self.f.pack, self.f.evidence]))

    def test_cli_existing_output_is_never_overwritten(self):
        self.output.mkdir()
        (self.output / 'receipt.json').write_bytes(b'original sentinel')
        before = inventory([self.output])
        completed = self.run_cli()
        self.assertEqual(before, inventory([self.output]))
        self.assert_refused(completed, 'OUTPUT_EXISTS', receipt=False)
        self.assertIn('OUTPUT_EXISTS', completed.stderr)

    def test_cli_output_inside_pack_refused_without_write(self):
        before = inventory([self.f.pack])
        completed = self.run_cli(output=self.f.pack / 'new-output')
        self.assertEqual(before, inventory([self.f.pack]))
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertIn('OUTPUT_IN_SOURCE_TREE', completed.stderr)

    def test_cli_matching_late_receipt_blocks_context_not_refuses(self):
        late = '2026-10-10T15:00:00+08:00'
        self.f.payloads['context']['reviewed_at'] = late
        self.f.context_receipt(late)
        self.f.seal(register=True)
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 3, completed.stderr)
        context = self.read('validation.json')['quality']['context']
        self.assertEqual(context['status'], 'DATA_BLOCKED')
        self.assertIn('CONTEXT_REVIEW_AFTER_CUTOFF', context['reason_codes'])

    def test_cli_unused_alias_of_existing_root_does_not_reject_accepted_sources(self):
        registry = json.loads(self.f.registry.read_bytes())
        registry['evidence_roots']['unused'] = str(self.f.evidence)
        self.f.registry.write_bytes(fixtures.encode(registry))
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertTrue(self.read('manifest.json')['complete'])
        self.assertFalse((self.output / 'evidence/external/unused').exists())

    def test_cli_input_and_production_output_boundaries(self):
        before = inventory([self.f.registry, self.f.pack, self.f.evidence])
        for output in [self.f.pack / 'new', self.f.evidence / 'new', self.f.registry,
                       self.f.root / 'data_history' / 'new', self.f.root / 'public' / 'new',
                       self.f.root / 'ar-live' / 'new', Path('/'),
                       Path('/' + str(self.output))]:
            with self.subTest(output=str(output)):
                completed = self.run_cli(output=output)
                self.assertEqual(completed.returncode, 2, completed.stderr)
                self.assertIn('OUTPUT', completed.stderr)
        self.assertEqual(before, inventory([self.f.registry, self.f.pack, self.f.evidence]))
        self.assertFalse((self.f.root / 'data_history').exists())

    def test_cli_unwritable_output_stderr_only(self):
        completed = self.run_cli(fault={'boundary': 'create', 'fail': True})
        self.assert_refused(completed, 'OUTPUT_UNWRITABLE', receipt=False)
        self.assertFalse(self.output.exists())
        self.assertIn('OUTPUT_UNWRITABLE', completed.stderr)

    def test_cli_absent_optional_root_allows_safe_sibling_scratch(self):
        registry = json.loads(self.f.registry.read_bytes())
        registry['evidence_roots']['unused'] = str(self.f.root / 'absent-optional')
        self.f.registry.write_bytes(fixtures.encode(registry))
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertTrue(self.read('manifest.json')['complete'])
        self.assertFalse((self.f.root / 'absent-optional').exists())

    def test_cli_missing_parent_is_not_created(self):
        completed = self.run_cli(output=self.f.root / 'absent' / 'output')
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertFalse((self.f.root / 'absent').exists())

    def test_cli_source_race_at_snapshot_refused(self):
        completed = self.run_cli(fault={'boundary': 'create', 'change': str(self.f.pack / 'inputs/bars.json')})
        self.assert_refused(completed, 'SOURCE_CHANGED')

    def test_cli_external_source_race_at_snapshot_refused(self):
        completed = self.run_cli(fault={'boundary': 'create', 'change': str(self.f.evidence / 'e1-original.json')})
        self.assert_refused(completed, 'SOURCE_CHANGED')

    def test_cli_registry_race_at_snapshot_refused(self):
        completed = self.run_cli(fault={'boundary': 'create', 'change': str(self.f.registry)})
        self.assert_refused(completed, 'SOURCE_CHANGED')

    def test_cli_same_bytes_new_inode_refused(self):
        completed = self.run_cli(fault={'boundary': 'create', 'replace': str(self.f.registry)})
        self.assert_refused(completed, 'SOURCE_CHANGED')

    def test_cli_source_race_at_manifest_boundary_refused(self):
        completed = self.run_cli(fault={'boundary': 'receipt.json', 'change': str(self.f.pack / 'inputs/bars.json')})
        self.assert_refused(completed, 'SOURCE_CHANGED')

    def test_cli_registry_race_at_manifest_boundary_refused(self):
        completed = self.run_cli(fault={'boundary': 'receipt.json', 'change': str(self.f.registry)})
        self.assert_refused(completed, 'SOURCE_CHANGED')

    def test_cli_output_leaf_alias_race_never_writes_source(self):
        before = inventory([self.f.pack])
        completed = self.run_cli(fault={'boundary': 'create', 'alias': str(self.f.pack)})
        self.assert_refused(completed, 'OUTPUT_EXISTS', receipt=False)
        self.assertEqual(before, inventory([self.f.pack]))

    def test_cli_output_parent_alias_race_never_writes_source(self):
        parent = self.f.root / 'scratch'
        parent.mkdir()
        self.output = parent / 'inspection'
        before = inventory([self.f.pack])
        completed = self.run_cli(fault={'boundary': 'create', 'parent_alias': str(self.f.pack)})
        displaced = Path(str(parent) + '.old') / 'inspection'
        self.assertEqual(list(displaced.iterdir()), [])
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertIn('OUTPUT_CHANGED', completed.stderr)
        self.assertEqual(before, inventory([self.f.pack]))
        self.assertFalse((parent / 'inspection').exists())

    def test_cli_output_symlink_ancestor_refused(self):
        alias = self.f.root / 'alias'
        alias.symlink_to(self.f.pack, target_is_directory=True)
        before = inventory([self.f.pack])
        completed = self.run_cli(output=alias / 'inspection')
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(before, inventory([self.f.pack]))

    def test_cli_manifest_staging_alias_race_never_publishes(self):
        before = inventory([self.f.pack])
        completed = self.run_cli(fault={'boundary': 'manifest.json',
            'stage_alias': str(self.f.pack / 'request.json')})
        self.assert_refused(completed, 'OUTPUT_CHANGED')
        self.assertEqual(before, inventory([self.f.pack]))

    def test_cli_each_writer_failure_leaves_no_complete_manifest(self):
        for boundary in ['bars.json', 'validation.json', 'receipt.json', 'SHA256SUMS',
                         '.manifest.pending', 'manifest.json', 'write:bars.json', 'fsync:.manifest.pending']:
            with self.subTest(boundary=boundary):
                self.output = self.f.root / ('failure-' + boundary.replace('.', '-'))
                completed = self.run_cli(fault={'boundary': boundary, 'fail': True})
                self.assert_refused(completed, 'OUTPUT_WRITE_FAILED')

    def test_cli_partial_write_failure_retains_earlier_output(self):
        completed = self.run_cli(fault={'boundary': 'receipt.json', 'fail': True})
        self.assert_refused(completed, 'OUTPUT_WRITE_FAILED')
        self.assertTrue((self.output / 'validation.json').exists())
        self.assertTrue((self.output / 'evidence/pack/inputs/bars.json').exists())

    def test_cli_unknown_pack_safe_receipt_in_new_directory(self):
        completed = self.run_cli(pack_id='not-registered')
        self.assert_refused(completed, 'PACK_NOT_REGISTERED')

    def test_exit_zero_routing_unit_only_not_upstream_validation(self):
        main = getattr(self.contract, 'main', None)
        self.assertTrue(callable(main), 'CLI must route the validation status')
        synthetic = self.contract._result()
        synthetic['status'] = 'VALIDATED'
        with patch.object(self.contract, 'inspect_registered_pack', return_value=synthetic):
            self.assertEqual(main(['inspect', '--registry', str(self.f.registry),
                '--pack-id', 'synthetic-1', '--output', str(self.output)]), 0)


if __name__ == '__main__':
    unittest.main()
