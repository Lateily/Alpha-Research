"""Registered earnings inputs use the existing persistent queue and seals."""
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts/llm'), str(ROOT / 'tests')]
import workbench_shared_material as material
import workbench_evidence as ev
import tests.test_foundation_research as research_tests


class SharedMaterialTests(unittest.TestCase):
    def setUp(self):
        self.fixture = research_tests.MaterialResearchTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        import foundation_research as research
        self.identity = {'code_sha': 'a' * 40, 'source_tree_hash': 'b' * 64}
        patch = mock.patch.object(research, '_execution_identity', return_value=self.identity)
        patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.object(research, '_observed_at', return_value='2020-01-06T18:00:00+08:00')
        patch.start(); self.addCleanup(patch.stop)
        self.pack = self.root / 'pack'
        self.prepared = research.prepare_research_pack(self.fixture.library, self.fixture.request, self.pack)

    def test_input_binding_and_tamper_refusal(self):
        snapshot = material.snapshot(self.fixture.library, self.pack,
            expected_library_hash=self.fixture.request['expected_library_hash'],
            expected_pack_hash=self.prepared['pack_hash'])
        root = self.root / 'registered'
        material.copy_input(self.fixture.library, self.pack, root, snapshot)
        material.verify_input(root, snapshot)
        (root / 'unexpected.json').write_text('{}')
        with self.assertRaises(ValueError):
            material.verify_input(root, snapshot)

    def test_market_identity_never_inferred_from_research_date(self):
        snapshot = material.snapshot(self.fixture.library, self.pack,
            expected_library_hash=self.fixture.request['expected_library_hash'],
            expected_pack_hash=self.prepared['pack_hash'])
        envelope = material.envelope(snapshot)
        self.assertIsNone(envelope['source_trade_date'])
        self.assertIsNone(envelope['source_run_id'])
        self.assertEqual(envelope['snapshot']['research_date'], '20200106')

    def test_archive_must_bind_selected_pack(self):
        value = material.snapshot(self.fixture.library, self.pack,
            expected_library_hash=self.fixture.request['expected_library_hash'], expected_pack_hash=self.prepared['pack_hash'])
        root = self.root / 'registered'; material.copy_input(self.fixture.library, self.pack, root, value)
        output = self.root / 'output'; material.render(root, output, value)
        changed = {**value, 'pack_hash': '0' * 64}
        with self.assertRaises(ValueError): material.verify_output(output, changed)

    def test_output_and_archive_reopen_and_rights_guard(self):
        snapshot = material.snapshot(self.fixture.library, self.pack,
            expected_library_hash=self.fixture.request['expected_library_hash'],
            expected_pack_hash=self.prepared['pack_hash'])
        root = self.root / 'registered'; material.copy_input(self.fixture.library, self.pack, root, snapshot)
        output = self.root / 'output'
        material.render(root, output, snapshot)
        result = material.verify_output(output, snapshot)
        self.assertEqual(result['human_review'], 'PENDING')
        self.assertFalse(result['content_sharing_allowed'])
        self.assertEqual(result['archive_status'], 'ARCHIVED')
        (output / 'case/600000.SH/report.md').write_text('changed')
        with self.assertRaises(ValueError): material.verify_output(output, snapshot)

    def queue(self, enabled=True):
        import nonprod_workbench as wb
        import workbench_workspace as ws
        import workbench_shared_workspace as shared
        from workbench_shared_test_support import committed_code
        from workbench_shared_inputs import FrozenInputs
        from workbench_shared_jobs import SharedJobQueue
        code = self.root / ('code-enabled' if enabled else 'code-disabled')
        committed_code(code, shared.EXECUTION_FILES)
        patch = mock.patch.object(shared, 'CODE_ROOT', code); patch.start(); self.addCleanup(patch.stop)
        store = wb.Store(self.root / ('state-enabled' if enabled else 'state-disabled'), shared_v1=True)
        view = shared.SharedWorkspace(ws.Workspace(store, private_mode=True), materials_enabled=enabled)
        inputs = FrozenInputs(store)
        entry = material.register(inputs, self.fixture.library, self.pack,
            expected_library_hash=self.fixture.request['expected_library_hash'], expected_pack_hash=self.prepared['pack_hash'])
        return SharedJobQueue(view, inputs, view._execution_identity['code_sha']), view, entry

    def test_existing_queue_seals_archive_query_and_backup(self):
        import workbench_shared_worker as worker
        queue, view, entry = self.queue()
        payload = {'command_id': 'material-command-001', 'kind': material.KIND, 'snapshot_id': entry['snapshot_id']}
        job = queue.enqueue(payload, 'owner@example.com')
        self.assertEqual(queue.enqueue(payload, 'owner@example.com')['job_id'], job['job_id'])
        claim = queue.claim(); result = worker.run_attempt(claim)
        self.assertEqual(result['status'], 'SUCCEEDED', result)
        queue.finish(claim, result)
        detail = view.job(job['job_id'], 'member@example.com')
        self.assertEqual(detail['status'], 'SUCCEEDED')
        self.assertEqual(len(detail['research']['citation_locations']), 1)
        self.assertNotIn('report', detail)
        found = view.research_results('member@example.com', research_date='20200106', ts_code='600000.SH')
        self.assertEqual(found['total'], 1)
        self.assertEqual(found['results'][0]['assessments'], ['UNRESOLVED'])
        self.assertIsNone(view.snapshot('owner@example.com')['common_data']['current_snapshot_id'])
        self.assertEqual(queue.recover()['recovery_required'], [])
        from workbench_shared_jobs import verify_queue_state
        import workbench_shared_state as state
        with queue.store.connect() as db:
            tables = {name: [list(row) for row in db.execute('SELECT * FROM ' + name)] for name in state.ALL_TABLES}
        verify_queue_state(queue.store.path.parent, tables)
        import workbench_backup as backup
        archive = self.root / 'backup'
        backed = backup.backup_shared(queue.store, archive)
        restored = backup.restore_shared(archive, self.root / 'cold-state')
        self.assertEqual(restored['status'], 'LOCAL_SHARED_RESTORE_VERIFIED')
        from foundation_retention import build_retention_pin, verify_retention_pin
        pin = build_retention_pin(archive, expected_backup_hash=backed['backup_hash'],
                                 snapshot_ids=[entry['snapshot_id']], job_ids=[job['job_id']],
                                 created_at='2026-11-05T12:00:00+00:00')
        self.assertEqual(verify_retention_pin(pin, archive, expected_backup_hash=backed['backup_hash']), pin)

    def test_kind_mismatch_and_default_off(self):
        from workbench_workspace import WorkspaceError
        queue, view, entry = self.queue(False)
        with self.assertRaises(WorkspaceError):
            queue.enqueue({'command_id': 'disabled-material', 'kind': material.KIND, 'snapshot_id': entry['snapshot_id']}, 'owner@example.com')
        with self.assertRaises(WorkspaceError):
            queue.enqueue({'command_id': 'wrong-kind-material', 'kind': 'snapshot-brief', 'snapshot_id': entry['snapshot_id']}, 'owner@example.com')
        with self.assertRaises(WorkspaceError): queue.inputs.select_current(entry['snapshot_id'])

    def test_http_registered_inputs_and_closed_submission(self):
        import json
        import nonprod_workbench as wb
        from workbench_shared_test_support import OWNER, MEMBER, http
        queue, view, entry = self.queue()
        allow = self.root / 'members.json'; allow.write_text(json.dumps({'members': [MEMBER]})); allow.chmod(0o600)
        private = wb.private_access('https://workbench.test-tail.ts.net:8443', OWNER, allow)
        status, choices = http(queue.store, view.system, private, '/api/shared-workspace/research-inputs', shared=view)
        self.assertEqual(status, 200); self.assertTrue(choices['enabled'])
        self.assertEqual(choices['inputs'][0]['snapshot_id'], entry['snapshot_id'])
        body = {'command_id': 'http-material-command', 'kind': material.KIND, 'snapshot_id': entry['snapshot_id']}
        status, job = http(queue.store, view.system, private, '/api/workspace/job', body=body, login=MEMBER, shared=view)
        self.assertEqual(status, 202)
        self.assertEqual(view.job(job['job_id'], OWNER)['actor'], MEMBER)
        status, rejected = http(queue.store, view.system, private, '/api/workspace/job',
                               body={**body, 'path': '/etc/passwd'}, shared=view)
        self.assertEqual(status, 400)
        self.assertEqual(http(queue.store, view.system, private, '/api/shared-workspace/research-inputs',
                              login='unknown@example.com', shared=view)[0], 403)
