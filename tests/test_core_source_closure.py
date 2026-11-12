"""Incident closure controls built from the real offline endpoint producer."""
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts/llm'), str(ROOT)]

import core_source_gaps as gaps
import workbench_evidence as ev
from experiments.data_governance.endpoint_calls import EndpointSession


class ClosureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.ledger = self.root / 'ledger'
        self.original = self.root / 'result.json'
        self.scope = {'api_name': 'moneyflow_dc', 'ts_code': '603629.SH',
                      'trade_date': '20261030', 'fields': 'net_amount,trade_date,ts_code'}
        dates = {'daily': {'603629.SH': '20261030'}, 'index_daily': {'000001.SH': '20261030'},
                 'moneyflow_dc': {'603629.SH': '20261029'}}
        self.incident = {
            'run_id': '20261030_203005_1234567890_abcdef01', 'generated_at': '20261030 20:41',
            'report': 'INCOMPLETE', 'published': False, 'target_trade_date': None,
            'data_quality': 'DATA_BLOCKED', 'steps': [
                {'step': 'official_sample', 'status': 'FAILED', 'exit_code': 1,
                 'tail': 'DATA_BLOCKED: settlement-date mismatch across sources fund=fixture source_dates='
                 + ev.canonical(dates) + '\n'},
                {'step': 'feature_store', 'status': 'SKIPPED_STALE_INPUT'},
                {'step': 'macro_m1c', 'status': 'DATA_BLOCKED'},
                {'step': 'rotation_panel', 'status': 'OK'},
            ],
        }
        self.pin = self.write(self.original, self.incident)
        self.expected = [self.scope, {**self.scope, 'api_name': 'daily',
                                      'fields': 'close,trade_date,ts_code'}]
        self.head = gaps.ZERO
        self.when = '2099-01-01T00:00:00Z'

    def write(self, path, value):
        raw = ev.canonical(value).encode()
        path.write_bytes(raw)
        return ev.sha(raw)

    def make_recheck(self, *, ingest=True, price=7, trade_date='20261030',
                     stamp=datetime(2026, 11, 9, 21, 37, tzinfo=timezone.utc)):
        from core_source_closure import PURPOSE, APPROVAL_EVIDENCE
        root = Path(tempfile.mkdtemp(dir=self.root))
        params = {'ts_code': self.scope['ts_code'], 'trade_date': trade_date}
        fields = self.scope['fields'].split(',')
        grant = {'schema': 'ar.historical-recheck-grant.v1', 'api_name': self.scope['api_name'],
                 'params': params, 'fields': fields, 'max_attempts': 1,
                 'approval_ref': 'Junyan-chat-test-only', 'purpose': PURPOSE,
                 'automatic_retry': False, 'production_authority': False,
                 'prospective_sample_eligible': False}
        grant_hash = ev.sealed(grant)
        session = EndpointSession(root / 'endpoints', collector_run_id='historical-' + grant_hash[:32],
                                  target_trade_date=trade_date, clock=lambda: stamp)
        session.observe(grant['api_name'], params, self.scope['fields'],
                        lambda: {'code': 0, 'data': {'fields': fields,
                            'items': [[price, trade_date, params['ts_code']]]}})
        source = gaps.evidence(root / 'endpoints')
        if ingest:
            self.head = gaps.ingest(self.ledger, root / 'endpoints',
                                    expected_evidence_hash=source['evidence_hash'],
                                    expected_head=self.head)['head_hash']
        receipt = {'schema': 'ar.historical-recheck.v1', 'grant_hash': grant_hash,
                   'calls': source['calls'], 'status': 'OBSERVED_SCOPE_VALID', 'purpose': PURPOSE,
                   **gaps.LABELS, 'human_review': 'PENDING', 'approval_evidence': APPROVAL_EVIDENCE}
        receipt['receipt_hash'] = ev.sealed(receipt)
        self.write(root / 'grant.json', grant)
        self.write(root / 'receipt.json', receipt)
        marker = root / 'consumed.json'
        self.write(marker, {'receipt_hash': receipt['receipt_hash']})
        return dict(recheck_root=root, grant_pin=grant_hash, receipt_pin=receipt['receipt_hash'],
                    consumption_marker=marker)

    def report(self, **kwargs):
        from core_source_closure import closure
        return closure(self.ledger, self.expected, expectation_pin=ev.sealed(self.expected),
                       expected_head=self.head, observed_at=self.when, incident_path=self.original,
                       incident_pin=self.pin, incident_scope=ev.sealed(self.scope), **kwargs)

    def test_realized_impact_is_separate_from_late_scope_observation(self):
        value = self.report(**self.make_recheck())
        self.assertEqual(value['incident']['status'], 'DATA_BLOCKED')
        self.assertIsNone(value['incident']['accepted_trade_date'])
        self.assertFalse(value['incident']['published'])
        self.assertEqual(value['incident']['attempted_trade_date'], '20261030')
        self.assertEqual(value['incident']['observed_source_date'], '20261029')
        self.assertEqual(value['incident']['downstream_observations'],
                         {'feature_store': 'SKIPPED_STALE_INPUT', 'macro_m1c': 'DATA_BLOCKED'})
        self.assertEqual(value['recheck']['status'], 'AUTHORIZED_LATE_SCOPE_OBSERVED')
        self.assertEqual(value['coverage']['counts'], {'expected': 2, 'observed': 1, 'valid': 1, 'missing': 1})
        self.assertFalse(value['dispatch_allowed'])
        self.assertFalse(value['original_run_repaired'])
        self.assertFalse(value['prospective_sample_eligible'])

    def test_incident_bytes_must_match_external_pin(self):
        self.write(self.original, {**self.incident, 'generated_at': '20261030 20:43'})
        with self.assertRaisesRegex(ValueError, 'CLOSURE_INCIDENT_PIN_MISMATCH'):
            self.report()

    def test_same_scope_call_without_grant_is_not_authorized(self):
        self.make_recheck()
        value = self.report()
        self.assertEqual(value['recheck']['status'], 'NO_AUTHORIZED_RECHECK_EVIDENCE')
        self.assertEqual(value['coverage']['counts']['valid'], 1)

    def test_cli_reports_without_writes_and_rejects_partial_recheck(self):
        expectations = self.root / 'expectations.json'
        self.write(expectations, {'schema': 'ar.core-source-expectations.v1', 'scopes': self.expected})
        command = [sys.executable, '-B', str(ROOT / 'scripts/llm/core_source_closure.py'),
                   '--root', str(self.ledger), '--expectations', str(expectations),
                   '--incident', str(self.original), '--incident-pin', self.pin,
                   '--incident-scope', ev.sealed(self.scope), '--scope-pin', ev.sealed(self.expected),
                   '--observed-at', self.when, '--head', self.head]
        actual = subprocess.run(command, capture_output=True, timeout=20)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(ev.parse(actual.stdout), self.report())
        refused = subprocess.run(command + ['--grant-pin', '1' * 64], capture_output=True, timeout=20)
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(refused.stdout, b'')
        self.assertFalse(self.ledger.exists())

    def test_recheck_must_match_expected_day_and_entity(self):
        with self.assertRaisesRegex(ValueError, 'CLOSURE_GRANT_SCOPE'):
            self.report(**self.make_recheck(trade_date='20261104'))

    def test_consumption_marker_must_bind_exact_receipt(self):
        args = self.make_recheck()
        self.write(args['consumption_marker'], {'receipt_hash': 'f' * 64})
        with self.assertRaisesRegex(ValueError, 'CLOSURE_CONSUMPTION_MISMATCH'):
            self.report(**args)

    def test_recheck_not_ingested_is_not_observed(self):
        args = self.make_recheck(ingest=False)
        self.assertEqual(self.report(**args)['recheck']['status'], 'AUTHORIZED_RECHECK_NOT_VISIBLE')

    def test_recheck_not_known_at_cutoff_cannot_enter_projection(self):
        args = self.make_recheck()
        self.when = '2026-11-01T00:00:00Z'
        value = self.report(**args)
        self.assertEqual(value['recheck'], {'status': 'AUTHORIZED_RECHECK_NOT_VISIBLE'})
        self.assertEqual(value['coverage']['counts']['valid'], 0)

    def test_recheck_cannot_predate_original_failure(self):
        args = self.make_recheck(stamp=datetime(2026, 10, 30, 18, tzinfo=timezone.utc))
        with self.assertRaisesRegex(ValueError, 'CLOSURE_RECHECK_NOT_LATE'):
            self.report(**args)

    def test_later_same_scope_conflict_does_not_close(self):
        args = self.make_recheck()
        # Same grant would use the same logical-call identity. Use a distinct
        # ordinary call to exercise a competing receipt without replay.
        source = self.root / 'conflicting'
        now = datetime(2026, 11, 9, 21, 37, tzinfo=timezone.utc)
        session = EndpointSession(source, collector_run_id='distinct-conflict',
                                  target_trade_date='20261030', clock=lambda: now)
        session.observe('moneyflow_dc', {'ts_code': '603629.SH', 'trade_date': '20261030'},
                        self.scope['fields'], lambda: {'code': 0, 'data': {
                            'fields': self.scope['fields'].split(','),
                            'items': [[14, '20261030', '603629.SH']]}})
        self.head = gaps.ingest(self.ledger, source, expected_head=self.head,
                                expected_evidence_hash=gaps.evidence(source)['evidence_hash'])['head_hash']
        self.assertEqual(self.report(**args)['recheck']['status'], 'AUTHORIZED_RECHECK_RECONCILIATION_REQUIRED')


if __name__ == '__main__':
    unittest.main()
