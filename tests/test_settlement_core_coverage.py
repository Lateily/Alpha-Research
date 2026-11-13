"""Finite settlement observation and authorization boundary tests."""
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts/llm'), str(ROOT)]

from experiments.data_governance.endpoint_calls import EndpointSession
import core_source_gaps as gaps
import workbench_evidence as ev


class CoverageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.incident = self.root / 'original.json'
        original = {
            'run_id': '20261030_203005_1234567890_abcdef01', 'generated_at': '20261030 20:41',
            'report': 'INCOMPLETE', 'published': False, 'target_trade_date': None,
            'data_quality': 'DATA_BLOCKED', 'steps': [
                {'step': 'official_sample', 'status': 'FAILED', 'exit_code': 1,
                 'tail': 'DATA_BLOCKED: settlement-date mismatch across sources fixture source_dates='
                 + ev.canonical({'daily': {'603629.SH': '20261030'},
                                 'moneyflow_dc': {'603629.SH': '20261029'},
                                 'index_daily': {code: '20261030' for code in
                                                 ('000001.SH', '399001.SZ', '399006.SZ')}})},
                {'step': 'feature_store', 'status': 'SKIPPED_STALE_INPUT'},
                {'step': 'macro_m1c', 'status': 'DATA_BLOCKED'},
            ],
        }
        self.pin = self.write(self.incident, original)
        self.when = '2026-11-14T00:00:00Z'

    @staticmethod
    def write(path, obj):
        raw = ev.canonical(obj).encode()
        path.write_bytes(raw)
        return ev.sha(raw)

    def packet(self, *, omit=(), stale=(), wrong_scope=False):
        import settlement_core_coverage as core
        root = Path(tempfile.mkdtemp(dir=self.root))
        plan = core.plan_for_approval('Junyan-chat-synthetic-only')
        self.write(root / 'plan.json', plan)
        plan_pin = ev.sealed(plan)
        session = EndpointSession(root / 'endpoints', collector_run_id='settlement-' + plan_pin[:32],
                                  target_trade_date='20261030',
                                  clock=lambda: datetime(2026, 11, 13, 12, tzinfo=timezone.utc))
        for spec in plan['scopes']:
            api = spec['api_name']
            if api in omit:
                continue
            params, fields = dict(spec['params']), spec['fields'].split(',')
            if wrong_scope and api == 'index_daily':
                params['ts_code'] = '399001.SZ'
            def invoke():
                return {'code': 0, 'data': {'fields': fields, 'items': [[
                    params['ts_code'] if field == 'ts_code' else
                    ('20261029' if api in stale else '20261030') if field == 'trade_date'
                    else 4.0 for field in fields]]}}
            session.observe(api, params, spec['fields'], invoke)
        receipt = {'schema': 'ar.settlement-core-capture.v1', 'plan_hash': plan_pin,
                   'sealed_at': '2026-11-13T12:01:00Z',
                   'evidence_hash': ev.sealed(gaps._inventory(root / 'endpoints'))}
        return {'capture_root': root, 'plan_pin': plan_pin,
                'capture_pin': self.write(root / 'capture.json', receipt)}

    def report(self, **kwargs):
        import settlement_core_coverage as core
        return core.project(self.root / 'absent-v1-ledger', expected_head=gaps.ZERO,
                            incident_path=self.incident, incident_pin=self.pin,
                            observed_at=self.when, **kwargs)

    def test_original_index_date_is_not_a_call_receipt(self):
        value = self.report()
        self.assertEqual(value['counts'], {'expected': 6, 'observed': 0, 'valid': 0, 'blocked': 6})
        row = next(r for r in value['scopes'] if r['scope_id'] == 'index-sh')
        self.assertEqual(row['original_date'], '20261030')
        self.assertEqual(row['status'], 'DATA_BLOCKED')
        self.assertEqual(row['reason'], 'NO_CALL_EVIDENCE')
        self.assertIsNone(value['incident']['accepted_trade_date'])
        self.assertEqual(value['incident']['downstream_observations']['feature_store'], 'SKIPPED_STALE_INPUT')
        self.assertFalse(value['dispatch_allowed'])

    def test_three_valid_calls_do_not_cover_other_indexes_or_repair_old_run(self):
        value = self.report(**self.packet())
        self.assertEqual(value['counts'], {'expected': 6, 'observed': 3, 'valid': 3, 'blocked': 3})
        self.assertEqual(value['status'], 'DATA_BLOCKED')
        self.assertFalse(value['original_run_repaired'])
        self.assertFalse(value['prospective_sample_eligible'])
        by_id = {r['scope_id']: r for r in value['scopes']}
        self.assertEqual(by_id['market-flow']['original_role'], 'CONTEXT_ONLY')
        self.assertIsNone(by_id['market-flow']['original_date'])
        self.assertEqual(by_id['index-sz']['reason'], 'NO_CALL_EVIDENCE')
        self.assertEqual(by_id['index-cyb']['reason'], 'NO_CALL_EVIDENCE')

    def test_unapproved_scope_inside_resealed_capture_refuses(self):
        with self.assertRaisesRegex(ValueError, 'SETTLEMENT_CAPTURE_SCOPE'):
            self.report(**self.packet(wrong_scope=True))

    def test_missing_and_stale_observations_are_separate(self):
        value = self.report(**self.packet(omit=('index_daily',), stale=('moneyflow_mkt_dc',)))
        by_id = {r['scope_id']: r for r in value['scopes']}
        self.assertEqual(value['counts']['observed'], 2)
        self.assertEqual(value['counts']['valid'], 1)
        self.assertEqual(by_id['index-sh']['reason'], 'NO_CALL_EVIDENCE')
        self.assertEqual(by_id['market-flow']['status'], 'DATA_BLOCKED')
        self.assertIn('STALE', by_id['market-flow']['receipt']['gaps'])

    def test_call_visible_only_after_capture_is_sealed(self):
        args = self.packet()
        self.when = '2026-11-13T12:00:30Z'
        self.assertEqual(self.report(**args)['counts']['observed'], 0)

    def test_changed_receipt_bytes_are_refused_even_when_valid_json(self):
        args = self.packet()
        path = next((args['capture_root'] / 'endpoints' / 'calls').glob('*/terminal.json'))
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'SETTLEMENT_CAPTURE_BYTES'):
            self.report(**args)

    def test_parser_cannot_see_transient_substitute_terminal(self):
        import settlement_core_coverage as core
        args = self.packet(stale=('daily',))
        endpoints = args['capture_root'] / 'endpoints'
        original = next(path for path in (endpoints / 'calls').glob('*/terminal.json')
                        if ev.parse(path.read_bytes())['result']['dataset_quality'] == 'DATA_BLOCKED')
        raw = original.read_bytes()
        other = self.packet()['capture_root'] / 'endpoints'
        substitute = other / original.relative_to(endpoints)
        actual = core.read_endpoint_receipts
        def transient(root):
            original.write_bytes(substitute.read_bytes())
            try:
                return actual(root)
            finally:
                original.write_bytes(raw)
        with patch.object(core, 'read_endpoint_receipts', side_effect=transient):
            result = self.report(**args)
        row = next(x for x in result['scopes'] if x['scope_id'] == 'stock-daily')
        self.assertEqual(row['status'], 'DATA_BLOCKED')

    def report_with_ledger(self, *, stamp, fail=False, price=5.0):
        import settlement_core_coverage as core
        args = self.packet()
        ledger = self.root / 'ledger'
        session = EndpointSession(self.root / 'legacy', collector_run_id='prior-ledger',
                                  target_trade_date='20261030',
                                  clock=lambda: datetime.fromisoformat(stamp))
        fields = ['close', 'trade_date', 'ts_code']
        params = {'trade_date': '20261030', 'ts_code': '603629.SH'}
        session.observe('daily', params, ','.join(fields), lambda: {'code': 0, 'data': {
            'fields': fields, 'items': [[price, '20261029' if fail else '20261030', '603629.SH']]}})
        source = self.root / 'legacy'
        head = gaps.ingest(ledger, source, expected_evidence_hash=gaps.evidence(source)['evidence_hash'],
                           expected_head=gaps.ZERO)['head_hash']
        value = core.project(ledger, expected_head=head, incident_path=self.incident,
                             incident_pin=self.pin, observed_at=self.when, **args)
        return next(x for x in value['scopes'] if x['scope_id'] == 'stock-daily')

    def test_conflicting_same_time_successes_are_blocked(self):
        row = self.report_with_ledger(stamp='2026-11-13T12:00:00+00:00')
        self.assertEqual((row['status'], row['reason']), ('DATA_BLOCKED', 'CONFLICTING_TIME_EVIDENCE'))

    def test_older_capture_cannot_mask_newer_failed_ledger(self):
        row = self.report_with_ledger(stamp='2026-11-13T13:00:00+00:00', fail=True)
        self.assertEqual((row['status'], row['reason']), ('DATA_BLOCKED', 'LEGACY_SCOPE_NOT_VALID'))

    def test_equal_time_matching_values_do_not_false_block(self):
        row = self.report_with_ledger(stamp='2026-11-13T12:00:00+00:00', price=4.0)
        self.assertEqual((row['status'], row['reason']), ('OBSERVED_SCOPE_VALID', None))

    def test_wrong_authorization_pin_refuses(self):
        args = self.packet()
        args['plan_pin'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'SETTLEMENT_PLAN_PIN'):
            self.report(**args)

    def test_malformed_empty_endpoint_root_is_not_missing_evidence(self):
        import settlement_core_coverage as core
        for mode in ('regular-file', 'symlink'):
            with self.subTest(mode=mode):
                root = Path(tempfile.mkdtemp(dir=self.root))
                endpoints = root / 'endpoints'
                if mode == 'regular-file':
                    endpoints.write_bytes(b'')
                else:
                    endpoints.symlink_to(tempfile.mkdtemp(dir=self.root), target_is_directory=True)
                plan = core.plan_for_approval('Junyan-chat-synthetic-only')
                self.write(root / 'plan.json', plan)
                pin = ev.sealed(plan)
                capture = {'schema': 'ar.settlement-core-capture.v1', 'plan_hash': pin,
                           'sealed_at': '2026-11-13T12:01:00Z', 'evidence_hash': ev.sealed({})}
                capture_pin = self.write(root / 'capture.json', capture)
                with self.assertRaisesRegex(ValueError, 'SETTLEMENT_CAPTURE_ENDPOINT_ROOT'):
                    self.report(capture_root=root, plan_pin=pin, capture_pin=capture_pin)

    def test_cli_is_read_only_and_rejects_partial_capture_arguments(self):
        command = [sys.executable, '-B', str(ROOT / 'scripts/llm/settlement_core_coverage.py'),
                   '--ledger', str(self.root / 'absent-v1-ledger'), '--expected-head', gaps.ZERO,
                   '--incident-path', str(self.incident), '--incident-pin', self.pin, '--observed-at', self.when]
        before = sorted(self.root.iterdir())
        result = subprocess.run(command, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(ev.parse(result.stdout), self.report())
        refused = subprocess.run(command + ['--plan-pin', 'f' * 64], capture_output=True, timeout=20)
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(refused.stdout, b'')
        self.assertEqual(sorted(self.root.iterdir()), before)


if __name__ == '__main__':
    unittest.main()
