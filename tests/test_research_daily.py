"""Legacy shares may be reconstructed only by an exact producer replay."""
import copy
from datetime import datetime
from decimal import getcontext
import importlib
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/llm'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import workbench_evidence as ev
from experiments.research_workflows.smc_ict_input import _exchange_sessions


def observation():
    dates = _exchange_sessions('20260703', '20260803')
    result = {
        'schema': 'ar.local-daily-context-observation.v1', 'company': '603986.SH',
        'source_trade_date': dates[-1], 'captured_at': '2026-08-03T16:00:00+08:00',
        'source_scope': 'SQLITE_MAIN_FILE_IMMUTABLE_READ_NOT_FULL_WAL_OR_PUBLICATION_ACCEPTANCE',
        'source_db_sha256_before_after': 'a' * 64, 'source_health_sha256': 'b' * 64,
        'source_health_as_of': dates[-1], 'wal_present_at_capture': False, 'wal_size_bytes': None,
        'daily': [{'ts_code': '603986.SH', 'trade_date': day, 'open': 10.0, 'high': 12.0,
                   'low': 9.0, 'close': 11.0, 'volume_shares': 100.0, 'amount_cny': 1100.0} for day in dates],
        'moneyflow': [], 'adjustment_factors': [{'ts_code': '603986.SH', 'trade_date': day, 'adj_factor': 1.0} for day in dates],
        'counts': {'daily': len(dates), 'moneyflow': 0, 'adjustment_factors': len(dates)},
        'daily_parser': {}, 'atomic_observations': {}, 'pending': [],
        'human_review': 'PENDING', 'sample_purpose': 'WORKFLOW_DEBUG',
        'source_authenticity': 'UNVERIFIED', 'rights': 'UNVERIFIED_PRIVATE_LOCAL_ONLY',
        'production_authority': False, 'paper_authority': False, 'trading_authority': False,
        'claim_allowed': False, 'prospective_sample_eligible': False, 'provider_calls': 0, 'model_calls': 0}
    return reseal(result)


def reseal(value):
    value['observation_hash'] = ev.sealed({k: v for k, v in value.items() if k != 'observation_hash'})
    return value


class DailyResearchTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('research_daily'), 'daily adapter missing')
        return importlib.import_module('research_daily')

    def build(self, value=None, pin=None, generated='2026-08-04T16:00:00+08:00'):
        value = value or observation()
        return self.module().adapt(value, pin or value['observation_hash'], '603986.SH', generated)

    def test_both_observed_float_tails_replay_and_keep_trace(self):
        source = observation()
        source['daily'][0]['volume_shares'] = 57510792.00000001
        source['daily'][1]['volume_shares'] = 29969134.999999996
        reseal(source); original = copy.deepcopy(source)
        card = self.build(source)
        self.assertEqual(card['status'], 'INPUT_ADAPTED_GATES_PENDING')
        self.assertEqual([r['volume'] for r in card['daily_bars'][:2]], [57510792, 29969135])
        self.assertEqual(card['conversion_count'], 2)
        self.assertEqual(card['conversion_trace'][0]['source_float_hex'], float(source['daily'][0]['volume_shares']).hex())
        self.assertEqual(source, original)
        self.assertEqual(card['volume_scope'], 'REGULAR_DAILY_AH_VOLUME_NOT_SUPPLIED')
        self.assertIsNone(card['entry_stop_target'])
        self.assertFalse(card['paper_registration_allowed'])

    def test_nonproducer_near_integer_and_real_fractional_shares_are_rejected(self):
        for bad in (1.0000000000000002, 57510792.00000002, 100.5, -1, True, 2**40, '100'):
            source = observation(); source['daily'][0]['volume_shares'] = bad; reseal(source)
            with self.subTest(bad=bad), self.assertRaises(ValueError): self.build(source)
        for bad in (float('nan'), float('inf')):
            with self.subTest(bad=bad), self.assertRaises(ValueError): self.module().shares(bad)

    def test_external_pin_and_observation_hash_are_not_self_authorization(self):
        source = observation(); source['daily'][0]['close'] = 10.5
        with self.assertRaises(ValueError): self.build(source)
        reseal(source)
        with self.assertRaises(ValueError): self.build(source, 'f' * 64)

    def test_date_identity_ohlc_factors_and_scope_are_enforced(self):
        for change in ('gap', 'duplicate', 'ticker', 'ohlc', 'factor-missing', 'factor-duplicate', 'factor-zero',
                       'factor-bool', 'future', 'preclose-capture', 'count', 'promote', 'scope', 'flow'):
            source = observation()
            if change == 'gap': source['daily'].pop(4); source['counts']['daily'] -= 1
            if change == 'duplicate': source['daily'][4] = copy.deepcopy(source['daily'][3])
            if change == 'ticker': source['daily'][0]['ts_code'] = '600000.SH'
            if change == 'ohlc': source['daily'][0]['low'] = 11.5
            if change == 'factor-missing': source['adjustment_factors'].pop(); source['counts']['adjustment_factors'] -= 1
            if change == 'factor-duplicate': source['adjustment_factors'][1] = copy.deepcopy(source['adjustment_factors'][0])
            if change == 'factor-zero': source['adjustment_factors'][0]['adj_factor'] = 0
            if change == 'factor-bool': source['adjustment_factors'][0]['adj_factor'] = True
            if change == 'future': source['captured_at'] = '2026-08-05T16:00:00+08:00'
            if change == 'preclose-capture': source['captured_at'] = '2026-08-03T14:00:00+08:00'
            if change == 'count': source['counts']['daily'] += 1
            if change == 'promote': source['paper_authority'] = True
            if change == 'scope': source['source_scope'] = 'PROVIDER_VERIFIED'
            if change == 'flow': source['moneyflow'] = [{'ts_code': '600000.SH', 'trade_date': '20260803', 'net_amount_cny': 1, 'net_amount_rate': 1, 'input_hash': 'a'*64}]; source['counts']['moneyflow'] = 1
            reseal(source)
            with self.subTest(change=change), self.assertRaises(ValueError): self.build(source)

    def test_daily_descriptors_are_decimal_context_independent_and_not_minute_signals(self):
        before = self.build(); context = getcontext().copy()
        try:
            getcontext().prec = 4
            self.assertEqual(self.build(), before)
        finally:
            import decimal
            decimal.setcontext(context)
        self.assertEqual(before['observations']['atr14_raw'], '3')
        self.assertNotIn('fvg', before['observations'])


if __name__ == '__main__':
    unittest.main()
