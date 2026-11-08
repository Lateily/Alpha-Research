"""Daily strategy consumes registered evidence, not caller verdicts or future bars."""
import copy
from decimal import Decimal
import importlib
import importlib.util
from pathlib import Path
import sys
import subprocess
import unittest
from unittest import mock

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import test_technical_contract as fixtures


class DailyStrategyTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.TechnicalSemanticTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.ready_observation()
        bars = self.f.payloads['bars']['rows']
        bars[47]['high'] = '22.00'; bars[51]['high'] = '20.00'
        bars[55]['low'] = '9.00'
        bars[58].update(low='8.80', close='8.90')
        bars[59].update(open='9.00', high='10.50', low='9.10', close='9.50')
        bars[59]['open'] = '9.20'
        self.f.seal(register=True)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('experiments.research_workflows.daily_strategy'), 'daily strategy missing')
        return importlib.import_module('experiments.research_workflows.daily_strategy')

    def run_card(self):
        return self.module().evaluate(self.f.registry, fixtures.sha(self.f.registry.read_bytes()), 'synthetic-1')

    def test_registered_first_event_levels_and_missing_cost_are_visible(self):
        result = self.run_card()
        self.assertEqual(result['setup']['reference']['bar_id'], '20261005')
        self.assertEqual(result['setup']['sweep_date'], '20261008')
        self.assertEqual(result['setup']['reclaim_date'], '20261009')
        self.assertEqual(result['levels']['entry_reference'], '10.51')
        self.assertEqual(result['levels']['target_1'], '20')
        self.assertEqual(result['levels']['target_2'], '22')
        self.assertIsNone(result['levels']['after_cost_rr'])
        self.assertIn('COST_MODEL_NOT_SUPPLIED', result['reason_codes'])
        self.assertEqual(result['status'], 'WAIT')
        self.assertFalse(result['authority']['paper_registration_authority'])
        self.assertEqual(result['human_review']['status'], 'PENDING')

    def test_wilder_uses_recursive_history_not_a_rolling_mean(self):
        bars = [{'high': '12', 'low': '10', 'close': '11'} for _ in range(16)]
        bars[14] = {'high': '25', 'low': '9', 'close': '11'}
        self.assertEqual(self.module().wilder_at(bars, 13), 2)
        self.assertEqual(self.module().wilder_at(bars, 14), 3)
        self.assertEqual(str(self.module().wilder_at(bars, 15).quantize(Decimal('0.00000001'))), '2.92857143')

    def test_action_gap_blocks_structure_and_cannot_be_replaced_with_a_verdict(self):
        self.f.payloads['corporate_actions']['verified'] = False
        self.f.seal(register=True)
        result = self.run_card()
        self.assertEqual(result['status'], 'DATA_BLOCKED')
        self.assertIsNone(result['setup']); self.assertIsNone(result['levels'])
        self.assertIn('ACTION_COVERAGE_UNKNOWN', result['reason_codes'])

    def test_external_registry_pin_and_mutated_bars_are_refused(self):
        with self.assertRaises(ValueError):
            self.module().evaluate(self.f.registry, 'f'*64, 'synthetic-1')
        path = self.f.pack / 'inputs/bars.json'
        path.write_bytes(path.read_bytes().replace(b'8.80', b'8.70'))
        result = self.run_card()
        self.assertEqual(result['status'], 'REFUSED')
        self.assertIsNone(result['levels'])

    def test_equal_lows_are_not_strict_reference_pivots(self):
        self.f.payloads['bars']['rows'][56]['low'] = '9.00'
        self.f.seal(register=True)
        result = self.run_card()
        self.assertEqual(result['status'], 'NO_SETUP')
        self.assertIsNone(result['setup'])

    def test_future_confirmation_is_not_a_target(self):
        bars = self.f.payloads['bars']['rows']
        bars[47]['high'] = bars[51]['high'] = '10.20'
        bars[58]['high'] = '25.00'
        self.f.seal(register=True)
        result = self.run_card()
        self.assertIsNone(result['levels']['target_1'])
        self.assertIn('TARGET_MISSING', result['reason_codes'])

    def test_reclaim_cannot_use_a_later_event_to_make_reward_risk_pretty(self):
        bars = self.f.payloads['bars']['rows']
        bars[59].update(high='10.00', low='8.80', open='8.90', close='8.99')
        self.f.seal(register=True)
        result = self.run_card()
        self.assertEqual(result['status'], 'WAIT')
        self.assertEqual(result['setup']['sweep_date'], '20261008')
        self.assertIsNone(result['setup']['reclaim_date'])
        self.assertIsNone(result['levels'])

    def test_later_touch_and_invalidation_do_not_rewrite_the_event(self):
        initial = self.run_card()
        f = self.f; last = copy.deepcopy(f.payloads['bars']['rows'][-1])
        day = '20261010'; last.update(trade_date=day, bar_close_at=f.stamp(day), available_at=f.stamp(day),
                                    high='23.00', low='8.70', open='9.50', close='8.79')
        f.payloads['bars']['rows'].append(last)
        f.request.update(as_of=f.stamp(day), data_cutoff=f.stamp(day), generated_at=f.stamp(day))
        calendar = f.payloads['calendar']; calendar['coverage']['end'] = day
        calendar['days'].append(dict(trade_date=day, is_open=True, close_at=f.stamp(day), suspensions=[])); f.calendar_hash()
        f.payloads['corporate_actions']['coverage']['end'] = day
        f.seal(register=True)
        after = self.run_card()
        self.assertEqual(after['setup'], initial['setup'])
        self.assertEqual(after['levels'], initial['levels'])
        self.assertEqual(after['status'], 'INVALIDATED')
        self.assertEqual(after['lifecycle']['entry_trigger_seen_at'], day)
        self.assertEqual(after['lifecycle']['target_seen_at'], day)
        self.assertEqual(after['lifecycle']['structure_invalidated_at'], day)
        self.assertIn('INTRABAR_ORDER_UNKNOWN', after['reason_codes'])

    def test_pivot_availability_not_just_close_time_is_required(self):
        self.f.payloads['bars']['rows'][57]['available_at'] = fixtures.STAMP
        self.f.seal(register=True)
        self.assertEqual(self.run_card()['status'], 'NO_SETUP')

    def test_future_confirmed_high_cannot_improve_a_past_target(self):
        f = self.f; before = self.run_card()
        for day, high in [('20261010', '10.20'), ('20261011', '15.00'), ('20261012', '10.20'), ('20261013', '10.20')]:
            row = copy.deepcopy(f.payloads['bars']['rows'][0]); row.update(trade_date=day,
                bar_close_at=f.stamp(day), available_at=f.stamp(day), high=high)
            f.payloads['bars']['rows'].append(row)
            f.payloads['calendar']['days'].append(dict(trade_date=day, is_open=True, close_at=f.stamp(day), suspensions=[]))
        f.request.update(as_of=f.stamp(day), data_cutoff=f.stamp(day), generated_at=f.stamp(day))
        f.payloads['calendar']['coverage']['end'] = day; f.calendar_hash()
        f.payloads['corporate_actions']['coverage']['end'] = day; f.seal(register=True)
        self.assertEqual(self.run_card()['levels'], before['levels'])

    def test_saved_card_reopens_and_coherent_reseal_cannot_change_derivation(self):
        import json
        module = self.module(); self.assertTrue(hasattr(module, 'create'), 'sealed daily artifact API missing')
        output = self.f.root / 'daily-card'; pin = fixtures.sha(self.f.registry.read_bytes())
        receipt = module.create(self.f.registry, pin, 'synthetic-1', output)
        self.assertEqual(module.verify(output, receipt['strategy_hash'], self.f.registry, pin, 'synthetic-1'), receipt)
        card = json.loads((output/'strategy-card.json').read_bytes()); card['levels']['entry_reference'] = '1.00'
        raw = fixtures.encode(card); (output/'strategy-card.json').write_bytes(raw)
        marker = output/'strategy-manifest.json'; manifest = json.loads(marker.read_bytes())
        manifest['files']['strategy-card.json'] = fixtures.sha(raw)
        manifest['strategy_hash'] = fixtures.sha(fixtures.encode({k:v for k,v in manifest.items() if k!='strategy_hash'}))
        marker.write_bytes(fixtures.encode(manifest))
        with self.assertRaises(ValueError): module.verify(output, manifest['strategy_hash'], self.f.registry, pin, 'synthetic-1')

    def test_actual_cli_create_reopen_and_wrong_registry_pin(self):
        import json
        command = [sys.executable, '-B', '-m', 'experiments.research_workflows.daily_strategy']
        common = ['--registry', str(self.f.registry), '--registry-hash', fixtures.sha(self.f.registry.read_bytes()),
                  '--pack-id', 'synthetic-1', '--output', str(self.f.root/'cli-card')]
        repo = Path(__file__).resolve().parents[1]
        created = subprocess.run(command+['create', *common], cwd=repo, capture_output=True, timeout=30)
        self.assertEqual(created.returncode, 0, created.stderr.decode())
        receipt = json.loads(created.stdout)
        reopened = subprocess.run(command+['verify', *common, '--strategy-hash', receipt['strategy_hash']], cwd=repo, capture_output=True, timeout=30)
        self.assertEqual(reopened.returncode, 0, reopened.stderr.decode())
        self.assertEqual(json.loads(reopened.stdout), receipt)
        common[3] = 'f'*64
        wrong = subprocess.run(command+['verify', *common, '--strategy-hash', receipt['strategy_hash']], cwd=repo, capture_output=True, timeout=30)
        self.assertNotEqual(wrong.returncode, 0)

    def test_size_and_source_output_overlap_are_rejected_without_directory(self):
        module = self.module(); output = self.f.root/'oversize'
        pin = fixtures.sha(self.f.registry.read_bytes())
        with mock.patch.object(module.ev, 'MAX_FILE', 32):
            with self.assertRaises(ValueError): module.create(self.f.registry, pin, 'synthetic-1', output)
        self.assertFalse(output.exists())
        output = self.f.pack/'card'
        with self.assertRaises(ValueError): module.create(self.f.registry, pin, 'synthetic-1', output)
        self.assertFalse(output.exists())

    def test_event_time_context_and_exact_settled_pair_cannot_use_later_data(self):
        f = self.f
        for row in f.payloads['flow']['rows']:
            row['available_at'] = '2026-10-09T15:01:00+08:00'
        f.seal(register=True)
        result = self.run_card()
        self.assertIsNone(result['context']['settled_flow_sum'])
        self.assertIn('SETTLED_FLOW_NOT_CONFIRMED_AT_EVENT', result['reason_codes'])
        self.assertIsNone(result['levels']['after_cost_rr'])

    def test_first_event_does_not_skip_a_nearer_poor_rr_target(self):
        self.f.payloads['bars']['rows'][51]['high'] = '11.00'
        self.f.seal(register=True)
        result = self.run_card()
        self.assertEqual(result['levels']['target_1'], '11')
        self.assertEqual(result['levels']['target_2'], '22')
        self.assertIn('GROSS_RR_BELOW_TWO', result['reason_codes'])
        self.assertEqual(result['status'], 'WAIT')

    def test_weak_volume_does_not_become_signal_or_filled_execution(self):
        for row in self.f.payloads['bars']['rows'][-5:]: row['volume'] = '1'
        self.f.seal(register=True)
        result = self.run_card()
        self.assertIn('VOLUME_NOT_CONFIRMED', result['reason_codes'])
        self.assertEqual(result['status'], 'WAIT')
        self.assertIsNone(result['lifecycle']['entry_trigger_seen_at'])
        self.assertEqual(result['registration_readiness'], 'NOT_AUTHORIZED')


if __name__ == '__main__':
    unittest.main()
