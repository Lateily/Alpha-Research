"""Persistent offline observation/outbox, never actual phone-delivery evidence."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/llm'))


class OperationsAlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('workbench_operations_alerts'),
                             'durable independent-observer handoff is missing')
        import workbench_operations_alerts
        return workbench_operations_alerts

    def observer(self):
        return self.module().Observer(self.root, service='workbench', host='host-a', observer='host-b')

    def pulse(self, sequence=1, sent_at=1000, status='HEALTHY'):
        return {'schema': 'ar.workbench-heartbeat.v1', 'service': 'workbench', 'host': 'host-a',
                'sequence': sequence, 'sent_at': sent_at, 'code_sha': 'a'*40, 'health': status}

    def test_missing_heartbeat_from_start_queues_once_and_persists(self):
        observer = self.observer(); self.assertEqual(observer.check(1000)['status'], 'AWAITING_HEARTBEAT')
        self.assertEqual(observer.check(1299)['outbox'], [])
        result = self.observer().check(1300)
        self.assertEqual(len(result['outbox']), 1)
        self.assertEqual(result['outbox'][0]['kind'], 'HOST_LOST')
        self.assertEqual(len(self.observer().check(1500)['outbox']), 1)
        self.assertEqual(result['external_detection'], 'NOT_ATTESTED')
        self.assertEqual(result['phone_delivery'], 'NOT_ATTESTED')

    def test_heartbeat_stale_future_replay_wrong_identity_and_unknown_fields_rejected(self):
        observer = self.observer(); observer.accept(self.pulse(), received_at=1001)
        for pulse, now in ((self.pulse(), 1002), (self.pulse(2, 900), 1300),
                           (self.pulse(2, 1500), 1002),
                           ({**self.pulse(2,1002), 'host':'other'},1002),
                           ({**self.pulse(2,1002), 'secret':'do-not-log'},1002)):
            with self.subTest(pulse=pulse), self.assertRaises(ValueError):
                observer.accept(pulse, received_at=now)
        result = observer.check(1301)
        self.assertEqual(len(result['outbox']), 1)
        self.assertEqual(result['outbox'][0]['kind'], 'HOST_LOST')

    def test_clock_rollback_refused_and_does_not_clear_loss(self):
        observer = self.observer(); observer.check(1000); observer.check(1300)
        with self.assertRaisesRegex(ValueError, 'OBSERVER_CLOCK'):
            observer.check(1200)
        self.assertEqual(len(self.observer().check(1301)['outbox']), 1)

    def test_health_failure_and_recovery_have_distinct_idempotent_alerts(self):
        observer = self.observer()
        observer.accept(self.pulse(status='SYNC_FAILED'), received_at=1000)
        observer.accept(self.pulse(2,1001,'SYNC_FAILED'), received_at=1001)
        self.assertEqual([x['kind'] for x in observer.check(1001)['outbox']], ['SERVICE_DEGRADED'])
        observer.accept(self.pulse(3,1002), received_at=1002)
        self.assertEqual([x['kind'] for x in observer.check(1002)['outbox']], ['SERVICE_DEGRADED','RECOVERED'])

    def test_outbox_is_not_delivery_and_receipt_is_not_human_ack(self):
        observer = self.observer(); observer.check(1000)
        alert = observer.check(1300)['outbox'][0]
        result = observer.record_delivery(alert['id'], channel='test-channel', receipt_hash='b'*64, at=1301)
        self.assertEqual(result['phone_delivery'], 'NOT_ATTESTED')
        self.assertEqual(result['human_acknowledgement'], 'PENDING')
        with self.assertRaises(ValueError):
            observer.record_delivery('unknown', channel='test-channel', receipt_hash='b'*64, at=1302)
        self.assertEqual(len(self.observer().check(1302)['outbox']),1)

    def test_same_host_cannot_be_configured_as_independent_observer(self):
        m = self.module()
        with self.assertRaisesRegex(ValueError,'OBSERVER_HOST_NOT_INDEPENDENT'):
            m.Observer(self.root,service='workbench',host='host-a',observer='host-a')

    def test_observer_binding_cannot_change_on_reopen(self):
        self.observer()
        with self.assertRaisesRegex(ValueError,'OBSERVER_BINDING'):
            self.module().Observer(self.root,service='workbench',host='different',observer='host-b')

    def test_fresh_pulse_after_observer_reopen_retains_overdue_gap(self):
        self.observer().accept(self.pulse(),received_at=1000)
        result = self.observer().accept(self.pulse(2,1360),received_at=1360)
        self.assertEqual([row['kind'] for row in result['outbox']],['HOST_LOST','RECOVERED'])
        self.assertEqual(result['status'],'HEALTHY')

    def test_first_late_pulse_retains_missing_initial_heartbeat(self):
        self.observer().check(1000)
        result = self.observer().accept(self.pulse(1,1360),received_at=1360)
        self.assertEqual([row['kind'] for row in result['outbox']],['HOST_LOST','RECOVERED'])


if __name__ == '__main__': unittest.main()
