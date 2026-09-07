"""Read-only relocation preserves the real publication verifier's guards."""
import hashlib
import fnmatch
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tests')]
import test_publish_rebaseline_offline as fixture

FILES = (
    'experiments/execution_tracker/publication_state.json',
    'experiments/execution_tracker/publication_rebaseline_events.jsonl',
    'experiments/execution_tracker/publication_rebaseline_events.jsonl.anchor.json',
    'experiments/execution_tracker/current_run.json',
    'public/data/v2/current_run.json',
)


class OriginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        et, repo, _, state, _ = fixture._layout(str(self.base))
        fixture.nightly_publish.rebaseline_lost_manifest(state, et, repo, now=fixture.NOW, **fixture.APPROVAL)
        self.source = Path(repo)
        self.runtime = self.base / 'runtime'
        shutil.copytree(self.source, self.runtime)
        self.context = {
            'schema': 'ar.isolated-origin.v1', 'sample_purpose': 'WORKFLOW_DEBUG',
            'production_authority': False, 'origin_root': str(self.source),
            'runtime_root': str(self.runtime),
            'files': {name: hashlib.sha256((self.runtime / name).read_bytes()).hexdigest() for name in FILES},
        }
        self.path = self.base / 'origin.json'
        self.pin()
        self.et = self.runtime / 'experiments/execution_tracker'
        self.state = self.et / 'publication_state.json'

    def pin(self):
        self.path.write_text(json.dumps(self.context), encoding='utf-8')
        self.hash = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def module(self):
        self.assertTrue((ROOT / 'tools/isolated_nightly_origin.py').is_file(), 'isolated origin compatibility is not implemented')
        return importlib.import_module('isolated_nightly_origin')

    def verify(self):
        return self.module().verify_context(self.path, self.hash)

    def repin_file(self, name):
        self.context['files'][name] = hashlib.sha256((self.runtime / name).read_bytes()).hexdigest()
        self.pin()

    def test_real_verifier_accepts_original_identity_on_copy_only(self):
        before = {str(p): p.read_bytes() for p in self.runtime.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(RuntimeError, 'SUPERSEDED'):
            fixture.nightly_publish.recover_interrupted_publish(str(self.state), str(self.et), str(self.runtime))
        result = self.verify()
        self.assertEqual(result['status'], 'SUPERSEDED_BY_OPERATOR')
        self.assertEqual(result['rebaseline_event'], fixture.read_json(str(self.state))['superseded_event_hash'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.runtime.rglob('*') if p.is_file()})
        # The production path is still strict after the temporary view is gone.
        with self.assertRaisesRegex(RuntimeError, 'SUPERSEDED'):
            fixture.nightly_publish.recover_interrupted_publish(str(self.state), str(self.et), str(self.runtime))

    def test_source_does_not_need_to_exist_or_be_read(self):
        shutil.rmtree(self.source)
        self.assertEqual(self.verify()['status'], 'SUPERSEDED_BY_OPERATOR')

    def test_context_pin_is_required(self):
        self.path.write_text(self.path.read_text() + ' ')
        with self.assertRaisesRegex(RuntimeError, 'context hash'):
            self.verify()

    def test_copy_hash_is_required(self):
        self.state.write_text(self.state.read_text() + ' ')
        with self.assertRaisesRegex(RuntimeError, 'artifact hash'):
            self.verify()

    def test_closed_artifact_set(self):
        (self.runtime / 'extra.json').write_text('{}')
        self.context['files']['extra.json'] = hashlib.sha256(b'{}').hexdigest()
        self.pin()
        with self.assertRaisesRegex(RuntimeError, 'artifact set'):
            self.verify()

    def test_production_authority_refused(self):
        self.context['production_authority'] = True
        self.pin()
        with self.assertRaisesRegex(RuntimeError, 'authority'):
            self.verify()

    def test_origin_and_runtime_must_be_disjoint(self):
        self.context['runtime_root'] = str(self.source)
        self.pin()
        with self.assertRaisesRegex(RuntimeError, 'disjoint'):
            self.verify()

    def test_parent_symlink_refused(self):
        old = self.runtime / 'public'
        other = self.base / 'other_public'
        old.rename(other)
        old.symlink_to(other, target_is_directory=True)
        with self.assertRaises((RuntimeError, OSError)):
            self.verify()

    def test_fifo_is_rejected_without_waiting_for_a_writer(self):
        fifo = self.base / 'context-fifo'
        os.mkfifo(fifo)
        code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                "from isolated_nightly_origin import _read_regular\n"
                "try: _read_regular(sys.argv[2], 'context-fifo')\n"
                "except RuntimeError: print('REFUSED')\n")
        try:
            result = subprocess.run([sys.executable, '-B', '-c', code,
                                     str(ROOT / 'tools'), str(self.base)],
                                    capture_output=True, text=True, timeout=2)
        except subprocess.TimeoutExpired:
            self.fail('special file read waited for a writer')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'REFUSED')

    def test_resealed_wrong_origin_is_not_accepted(self):
        self.context['origin_root'] = str(self.base / 'wrong-origin')
        self.pin()
        with self.assertRaises(RuntimeError):
            self.verify()

    def test_resealed_broken_anchor_is_rejected_by_real_guard(self):
        name = FILES[2]
        p = self.runtime / name
        value = json.loads(p.read_text())
        value['head'] = '0' * 64
        p.write_text(json.dumps(value))
        self.repin_file(name)
        with self.assertRaisesRegex(RuntimeError, 'fail-closed'):
            self.verify()

    def test_resealed_divergent_pointer_is_rejected(self):
        name = FILES[-1]
        p = self.runtime / name
        value = json.loads(p.read_text())
        value['run_id'] = 'OTHER'
        p.write_text(json.dumps(value))
        self.repin_file(name)
        with self.assertRaisesRegex(RuntimeError, 'fail-closed'):
            self.verify()

    def test_resealed_state_projection_is_rejected(self):
        value = json.loads(self.state.read_text())
        value['approved_by'] = 'not-the-frozen-identity'
        self.state.write_text(json.dumps(value))
        self.repin_file(FILES[0])
        with self.assertRaisesRegex(RuntimeError, 'fail-closed'):
            self.verify()

    def test_readonly_view_rejects_write_and_unknown_read(self):
        view = self.module().load_context(self.path, self.hash)
        with self.assertRaisesRegex(RuntimeError, 'read-only'):
            view.open(str(self.source / FILES[0]), 'w')
        with self.assertRaisesRegex(RuntimeError, 'unregistered'):
            view.open(str(self.source / '.ar_env'))

    def test_runner_recovery_calls_verifier_and_restores_hooks(self):
        module = self.module()
        original = fixture.nightly_publish.recover_interrupted_publish
        with module.relocated_recovery(self.path, self.hash, fixture.nightly_publish):
            result = fixture.nightly_publish.recover_interrupted_publish(str(self.state), str(self.et), str(self.runtime))
        self.assertEqual(result['rebaseline_event'], fixture.read_json(str(self.state))['superseded_event_hash'])
        self.assertIs(fixture.nightly_publish.recover_interrupted_publish, original)

    def test_runner_recovery_detects_copy_drift(self):
        module = self.module()
        with module.relocated_recovery(self.path, self.hash, fixture.nightly_publish):
            self.state.write_text(self.state.read_text() + ' ')
            with self.assertRaisesRegex(RuntimeError, 'artifact hash'):
                fixture.nightly_publish.recover_interrupted_publish(str(self.state), str(self.et), str(self.runtime))

    def test_runner_does_not_intercept_unrelated_state(self):
        module = self.module()
        other = self.base / 'other.json'
        other.write_text('{broken')
        with module.relocated_recovery(self.path, self.hash, fixture.nightly_publish):
            with self.assertRaisesRegex(RuntimeError, 'publication_state'):
                fixture.nightly_publish.recover_interrupted_publish(str(other), str(self.et), str(self.runtime))

    def test_new_runtime_rebaseline_uses_normal_recovery(self):
        module = self.module()
        original = fixture.nightly_publish.recover_interrupted_publish
        with module.relocated_recovery(self.path, self.hash, fixture.nightly_publish):
            state = {'schema': 'nightly_publication_state/v2', 'status': 'COMMITTED',
                     'run_id': 'R_NEW', 'target_trade_date': '20260828', 'artifact_count': 0,
                     'plan': str(self.et / 'runs/R_NEW/publish_plan.json'),
                     'manifest': str(self.et / 'runs/R_NEW/manifest.json')}
            pointer = {'schema': 'nightly_current_run/v2', 'run_id': 'R_NEW',
                       'target_trade_date': '20260828', 'manifest_sha256': '496d11d6' * 8,
                       'manifest_path': 'runs/R_NEW/manifest.json', 'artifacts': {}}
            fixture.write_json(str(self.state), state)
            for name in FILES[-2:]:
                fixture.write_json(str(self.runtime / name), pointer)
            fixture.nightly_publish.rebaseline_lost_manifest(
                str(self.state), str(self.et), str(self.runtime),
                now=fixture.LATER, **fixture.approval_for('R_NEW'))
            expected = original(str(self.state), str(self.et), str(self.runtime))
            try:
                result = fixture.nightly_publish.recover_interrupted_publish(
                    str(self.state), str(self.et), str(self.runtime))
            except RuntimeError as exc:
                self.fail('new valid runtime event was intercepted: ' + str(exc))
            self.assertEqual(result, expected)
            self.assertEqual(result['run_id'], 'R_NEW')

    def test_helper_only_change_triggers_python_ci(self):
        workflow = (ROOT / '.github/workflows/python-ci.yml').read_text()
        pull_config = workflow.split('  pull_request:', 1)[1].split('  push:', 1)[0]
        patterns = re.findall(r'^\s+- "([^"\n]+)"\s*$', pull_config, re.MULTILINE)
        self.assertTrue(any(fnmatch.fnmatchcase('tools/isolated_nightly_origin.py', pattern)
                            for pattern in patterns), 'helper-only change skips python-ci')


if __name__ == '__main__':
    unittest.main(verbosity=2)
