import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/llm'))
import foundation_observation as observation


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'observations'

    def response(self, api, params, fields):
        values = {'ts_code': params['ts_code'], 'trade_date': params['trade_date'],
                  'close': 10.0, 'net_amount': 1.0}
        return {'code': 0, 'data': {'fields': fields, 'items': [[values[k] for k in fields]]}}

    def test_exact_scope_and_single_invocation(self):
        invoke = Mock(side_effect=self.response)
        receipt = observation.observe(self.root, observation.initial_grant(),
            expected_grant_hash=observation.digest(observation.initial_grant()), invoke=invoke)
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(receipt['status'], 'OBSERVED_SCOPE_VALID')
        self.assertEqual(receipt['research_readiness'], 'NOT_EVALUATED')
        with self.assertRaises(ValueError):
            observation.observe(self.root, observation.initial_grant(),
                expected_grant_hash=observation.digest(observation.initial_grant()), invoke=invoke)
        self.assertEqual(invoke.call_count, 2)

    def test_scope_change_refused_before_invocation(self):
        grant = observation.initial_grant(); grant['ts_code'] = '600000.SH'
        invoke = Mock()
        with self.assertRaises(ValueError):
            observation.observe(self.root, grant, expected_grant_hash=observation.digest(grant), invoke=invoke)
        invoke.assert_not_called()

    def test_gap_retained_no_retry_and_separate_precise_grant(self):
        invoke = Mock(side_effect=RuntimeError('secret provider text'))
        grant = observation.initial_grant()
        failed = observation.observe(self.root, grant, expected_grant_hash=observation.digest(grant), invoke=invoke)
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(failed['status'], 'DATA_BLOCKED')
        self.assertNotIn('secret', json.dumps(failed))
        retry = observation.retry_grant(failed, api_name='daily', approval_ref='Junyan-test-retry')
        success = observation.observe(self.root, retry, expected_grant_hash=observation.digest(retry),
                                      invoke=self.response, previous=failed)
        self.assertEqual(len(success['calls']), 1)
        self.assertEqual(success['calls'][0]['start']['api_name'], 'daily')
        changed = copy.deepcopy(failed); changed['status'] = 'OBSERVED_SCOPE_VALID'
        with self.assertRaises(ValueError):
            observation.observe(self.root, retry, expected_grant_hash=observation.digest(retry),
                                invoke=self.response, previous=changed)

    def test_stale_and_empty_are_not_recovery(self):
        def empty(api, params, fields):
            return {'code': 0, 'data': {'fields': fields, 'items': []}}
        grant = observation.initial_grant()
        result = observation.observe(self.root, grant, expected_grant_hash=observation.digest(grant), invoke=empty)
        self.assertEqual(result['status'], 'DATA_BLOCKED')
        self.assertTrue(all('EMPTY_REQUIRED' in row['result']['gaps'] for row in result['calls']))

    def test_external_hash_is_required(self):
        invoke = Mock()
        with self.assertRaises(ValueError):
            observation.observe(self.root, observation.initial_grant(), expected_grant_hash='0' * 64, invoke=invoke)
        invoke.assert_not_called()
