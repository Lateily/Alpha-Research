"""Four research cards must add content without laundering evidence or authority."""
import copy
import importlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_foundation_research as material_fixtures
import workbench_evidence as ev


class ResearchContentTests(unittest.TestCase):
    def setUp(self):
        fixture = material_fixtures.MaterialResearchTests('test_real_pdf_prepare_verify_and_existing_earnings_renderer')
        self.fixture = fixture
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        self.pack = fixture.prepare()
        self.root, self.request = fixture.root, fixture.request
        citation = copy.deepcopy(self.request['questions'][0]['citations'][0])
        self.draft = {
            'schema': 'ar.research-content-request.v1', 'company': '600000.SH',
            'as_of': '20200106', 'generated_at': '2020-01-06T19:00:00+08:00',
            'pack_hash': self.pack['pack_hash'],
            'authoring': {'kind': 'AI_DRAFT', 'model': 'SYNTHETIC_TEST', 'prompt_version': 'content-test.v1'},
            'facts': [{'id': 'revenue', 'metric': 'revenue', 'period': '2019FY', 'unit': 'CNY',
                       'citation': citation, 'token_index': 0, 'value': '100'},
                      {'id': 'cash', 'metric': 'operating_cash_flow', 'period': '2019FY', 'unit': 'CNY',
                       'citation': {**citation, 'start': 2, 'end': 2, 'expected': 'Cash flow was 20 CNY.'},
                       'token_index': 0, 'value': '20'}],
            'calculations': [{'id': 'cash-conversion', 'operator': 'RATIO', 'operands': ['cash', 'revenue']}],
            'responses': [{'claim_id': 'cash-quality', 'assessment': 'MIXED',
                           'fact_ids': ['revenue', 'cash'], 'calculation_ids': ['cash-conversion'],
                           'reasoning': 'Cash receipts are not the same as revenue; this ratio alone cannot establish durability.',
                           'counterevidence': ['Only one period is available.'],
                           'missing_evidence': ['Receivable and payable movements remain unverified.']}],
            'valuation': None, 'technical': None, 'feedback': None}

    def content(self):
        self.assertIsNotNone(importlib.util.find_spec('research_content'), 'research-content implementation is missing')
        return importlib.import_module('research_content')

    def build(self, draft=None):
        return self.content().build(draft or self.draft, self.root / 'pack', self.pack['pack_hash'])

    def test_content_and_missing_cards_are_honest(self):
        output = self.build()
        self.assertEqual(output['facts']['calculations'][0]['value'], '0.2')
        self.assertEqual(output['facts']['responses'][0]['assessment'], 'MIXED')
        self.assertEqual(output['facts']['responses'][0]['status'], 'AI_ASSERTION_NOT_THESIS_SCORE')
        self.assertEqual(output['valuation']['status'], 'DATA_BLOCKED')
        self.assertIsNone(output['valuation']['value_band'])
        self.assertEqual(output['technical']['status'], 'DATA_BLOCKED')
        self.assertEqual(output['technical']['daily_workflow'], 'MANUAL_EVIDENCE_REQUIRED')
        self.assertEqual(output['execution_feedback']['status'], 'NOT_SUPPLIED')
        self.assertIsNone(output['execution_feedback']['pnl'])
        self.assertFalse(output['paper_authority'])
        self.assertEqual(output['human_review'], 'PENDING')

    def v2_draft(self):
        from test_research_daily import observation, reseal
        source = observation()
        source['company'] = self.draft['company']
        for key in ('daily', 'adjustment_factors'):
            for row in source[key]: row['ts_code'] = source['company']
        reseal(source)
        draft = copy.deepcopy(self.draft)
        draft.update(schema='ar.research-content-request.v2', as_of='20260804', generated_at='2026-08-04T16:00:00+08:00',
                     technical={'adapter': 'LEGACY_FEATURE_STORE_DAILY_V1', 'observation': source,
                                'observation_hash': source['observation_hash']})
        return draft

    def test_v2_daily_wiring_does_not_change_v1_or_promote_gates(self):
        old = self.build()
        result = self.build(self.v2_draft())
        self.assertEqual(result['schema'], 'ar.research-content-cards.v2')
        self.assertEqual(result['technical']['status'], 'INPUT_ADAPTED_GATES_PENDING')
        self.assertEqual(result['technical']['source_trade_date'], '20260803')
        self.assertEqual(result['material_cutoff_at'], self.request['source_cutoff_at'])
        self.assertEqual(self.build(), old)
        self.assertEqual(old['schema'], 'ar.research-content-cards.v1')

    def test_v2_valuation_basis_is_rederived_from_quoted_facts(self):
        draft = self.v2_draft()
        for key, original in [('total', 0), ('gain', 0), ('tax', 1), ('minority', 1)]:
            draft['facts'].append({**copy.deepcopy(draft['facts'][original]), 'id': key})
        draft['valuation'] = {'schema': 'ar.valuation-basis.v1', 'period': '2019FY',
            'nonrecurring': {'profit': 'revenue', 'ex_profit': 'cash', 'total': 'total',
                'pretax_items': [{'fact_id': 'gain', 'sign': 1}], 'tax': 'tax', 'minority': 'minority',
                'coverage_note': 'Deliberately contradictory synthetic semantic mapping.'},
            'anchors': {'reported_eps': None, 'ex_nonrecurring_eps': None, 'operating_cashflow': 'cash'}, 'cash_inventory': None}
        result = self.build(draft)['valuation']
        self.assertEqual(result['schema'], 'ar.valuation-basis-card.v1')
        self.assertEqual(result['nonrecurring']['after_tax_calculated'], '60')
        self.assertEqual(result['status'], 'DATA_BLOCKED')
        fields = ('revenue', 'ex_profit', 'reported_eps', 'ex_eps', 'operating_cashflow',
                  'pre_tax_profit', 'tax_expense', 'interest_income', 'operating_cost',
                  'selling_expense', 'admin_expense', 'rd_expense')
        history = {key: None for key in fields}; history.update(period='2019FY', revenue='revenue', ex_profit='cash')
        draft['valuation'].update(schema='ar.valuation-basis.v2', earnings_history=[history],
                                  cash_disclosures=[], multiple_observation=None)
        result = self.build(draft)['valuation']
        self.assertEqual(result['schema'], 'ar.valuation-basis-card.v2')
        self.assertEqual(result['earnings_history'][0]['diagnostics']['ex_profit_margin_pct'], '20')
        self.assertIsNone(result['normalized_eps']); self.assertIsNone(result['multiple_basis']['fair_multiple_low'])

    def test_v2_resealed_daily_card_is_rebuilt_and_source_pin_cannot_be_changed(self):
        content = self.content(); draft = self.v2_draft()
        with mock.patch.object(content, '_observed_at', return_value='2026-08-04T17:00:00+08:00'):
            receipt = content.create(draft, self.root / 'pack', self.pack['pack_hash'], self.root / 'v2')
        cards_path = self.root / 'v2/cards.json'; cards = ev.parse(cards_path.read_bytes())
        cards['technical']['daily_bars'][0]['volume'] = 999
        cards_path.write_text(ev.canonical(cards))
        marker = self.root / 'v2/content-manifest.json'; manifest = ev.parse(marker.read_bytes())
        manifest['files']['cards.json'] = ev.sha(cards_path.read_bytes())
        manifest['content_hash'] = ev.sealed({k: v for k, v in manifest.items() if k != 'content_hash'})
        marker.write_text(ev.canonical(manifest))
        with self.assertRaisesRegex(ValueError, 'DERIVATION'):
            content.verify(self.root / 'v2', manifest['content_hash'], self.root / 'pack', self.pack['pack_hash'])
        draft['technical']['observation_hash'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'PIN'): self.build(draft)

    def test_v2_output_size_preflight_refuses_without_a_partial_destination(self):
        content = self.content(); draft = self.v2_draft()
        output = self.root / 'oversized'
        # A renderer can amplify a bounded request; preflight its actual bytes.
        with mock.patch.object(content, '_observed_at', return_value='2026-08-04T17:00:00+08:00'), \
                mock.patch.object(content, 'report', return_value=b'x' * (ev.MAX_FILE + 1)):
            with self.assertRaisesRegex(ValueError, 'OUTPUT_SIZE'):
                content.create(draft, self.root / 'pack', self.pack['pack_hash'], output)
        self.assertFalse(output.exists())

    def test_v2_reviewer_leading_zero_amplification_refuses_before_any_writes(self):
        from test_research_daily import reseal
        content = self.content(); draft = self.v2_draft(); source = draft['technical']['observation']
        source['daily'][0]['open'] = '10.00'; reseal(source)
        draft['technical']['observation_hash'] = source['observation_hash']
        padding = ev.MAX_FILE - len(ev.canonical(draft).encode()) - 128
        source['daily'][0]['open'] = '0' * padding + '10.00'; reseal(source)
        draft['technical']['observation_hash'] = source['observation_hash']
        self.assertLess(len(ev.canonical(draft).encode()), ev.MAX_FILE)
        output = self.root / 'reviewer-amplification'
        with mock.patch.object(content, '_observed_at', return_value='2026-08-04T17:00:00+08:00'):
            with self.assertRaisesRegex(ValueError, 'SIZE|PRICE_REPRESENTATION'):
                content.create(draft, self.root / 'pack', self.pack['pack_hash'], output)
        self.assertFalse(output.exists())

    def test_pack_pin_and_resealed_quote_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'PIN'):
            self.content().build(self.draft, self.root / 'pack', 'f' * 64)
        draft = copy.deepcopy(self.draft)
        draft['facts'][0]['citation']['expected'] = 'Revenue was 999 CNY.'
        with self.assertRaisesRegex(ValueError, 'QUOTE'):
            self.build(draft)

    def test_numeric_token_cannot_float_free_of_quote_or_column(self):
        for field, value in [('value', '999'), ('value', 'nan'), ('value', True), ('token_index', 1), ('token_index', False)]:
            draft = copy.deepcopy(self.draft); draft['facts'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.build(draft)

    def test_changed_numeric_value_is_rejected_by_behavior(self):
        draft = copy.deepcopy(self.draft); draft['facts'][0]['value'] = '999'
        with self.assertRaises(ValueError): self.build(draft)

    def test_nonempty_subset_of_frozen_questions_is_rejected(self):
        request = copy.deepcopy(self.request)
        request['questions'].append({**copy.deepcopy(request['questions'][0]), 'id': 'second-question'})
        pack = self.fixture.prepare(request, name='pack-two')
        draft = {**self.draft, 'pack_hash': pack['pack_hash']}
        with self.assertRaisesRegex(ValueError, 'QUESTION_COVERAGE'):
            self.content().build(draft, self.root / 'pack-two', pack['pack_hash'])

    def test_units_periods_and_missing_operands_cannot_be_mixed(self):
        for change in ('unit', 'period', 'missing', 'duplicate'):
            draft = copy.deepcopy(self.draft)
            if change == 'unit': draft['facts'][1]['unit'] = 'CNY_PER_SHARE'
            if change == 'period': draft['facts'][1]['period'] = '2018FY'
            if change == 'missing': draft['calculations'][0]['operands'][0] = 'unknown'
            if change == 'duplicate': draft['facts'][1]['id'] = 'revenue'
            with self.subTest(change=change), self.assertRaises(ValueError): self.build(draft)

    def test_response_coverage_and_references_are_exact(self):
        for change in ('unknown-claim', 'missing', 'duplicate', 'unknown-fact', 'unknown-calculation', 'promotion', 'no-reason'):
            draft = copy.deepcopy(self.draft)
            if change == 'unknown-claim': draft['responses'][0]['claim_id'] = 'unrelated-question'
            if change == 'missing': draft['responses'] = []
            if change == 'duplicate': draft['responses'] *= 2
            if change == 'unknown-fact': draft['responses'][0]['fact_ids'] = ['unknown']
            if change == 'unknown-calculation': draft['responses'][0]['calculation_ids'] = ['unknown']
            if change == 'promotion': draft['responses'][0]['assessment'] = 'HUMAN_PASS'
            if change == 'no-reason': draft['responses'][0]['reasoning'] = ''
            with self.subTest(change=change), self.assertRaises(ValueError): self.build(draft)

    def test_valuation_assumptions_are_not_reported_eps_or_targets(self):
        draft = copy.deepcopy(self.draft)
        draft['valuation'] = {'adapter': 'SEMICONDUCTOR_NORMALIZED_EARNINGS', 'currency': 'CNY',
            'assumptions': {key: {'value': value, 'basis': 'Synthetic analyst assumption; not a source fact.', 'fact_ids': ['revenue']}
                for key, value in [('normalized_eps', '2'), ('fair_multiple_low', '10'),
                                   ('fair_multiple_high', '15'), ('net_cash_per_share', '1')]}}
        result = self.build(draft)['valuation']
        self.assertEqual(result['value_band'], {'low': '21', 'high': '31', 'unit': 'CNY_PER_SHARE'})
        self.assertEqual(result['status'], 'SCENARIO_ONLY_UNCALIBRATED')
        self.assertFalse(result['target_price'])
        for change in ('missing', 'inverted', 'nonfinite', 'no-basis', 'automatic-approval'):
            bad = copy.deepcopy(draft)
            if change == 'missing': del bad['valuation']['assumptions']['normalized_eps']
            if change == 'inverted': bad['valuation']['assumptions']['fair_multiple_low']['value'] = '20'
            if change == 'nonfinite': bad['valuation']['assumptions']['normalized_eps']['value'] = 'Infinity'
            if change == 'no-basis': bad['valuation']['assumptions']['normalized_eps']['basis'] = ''
            if change == 'automatic-approval': bad['valuation']['human_review'] = 'PASS'
            with self.subTest(change=change), self.assertRaises(ValueError): self.build(bad)

    def test_historical_schema_company_and_future_drafts_are_not_relabelled(self):
        for change in ('legacy', 'company', 'backdate'):
            draft = copy.deepcopy(self.draft)
            if change == 'legacy': draft['schema'] = 'ar.material-research-request.v1'
            if change == 'company': draft['company'] = '600001.SH'
            if change == 'backdate': draft['generated_at'] = '2020-01-01T19:00:00+08:00'
            with self.subTest(change=change), self.assertRaises(ValueError): self.build(draft)

    def test_zero_is_not_missing_and_zero_denominator_is_blocked(self):
        # This is a pure arithmetic boundary, not a fabricated source observation.
        content = self.content()
        self.assertEqual(content.calculate('RATIO', ['0', '100']), '0')
        self.assertIsNone(content.calculate('RATIO', ['100', '0']))
        self.assertEqual(content.calculate('GROWTH_PCT', ['50', '100']), '-50')
        self.assertEqual(content.calculate('ANNUALIZED_HALF_YEAR_SENSITIVITY', ['7']), '14')

    def test_growth_requires_comparable_prior_year_not_ratio_period_rules(self):
        draft = copy.deepcopy(self.draft)
        draft['calculations'][0]['operator'] = 'GROWTH_PCT'
        draft['facts'][1]['period'] = '2020FY'
        self.assertEqual(self.build(draft)['facts']['calculations'][0]['value'], '-80')
        draft['facts'][1]['period'] = '2020Q1'
        with self.assertRaisesRegex(ValueError, 'PERIOD_OR_UNIT'): self.build(draft)
        draft['facts'][1]['period'] = '2022FY'
        with self.assertRaisesRegex(ValueError, 'PERIOD_OR_UNIT'): self.build(draft)

    def test_existing_technical_engine_is_recomputed_without_daily_relabelling(self):
        from test_smc_ict_engine import frozen_payload, digest
        payload = frozen_payload()
        draft = copy.deepcopy(self.draft)
        draft.update(as_of='20261001', generated_at='2026-10-01T19:00:00+08:00',
                     technical={'input': payload, 'input_hash': digest(payload)})
        card = self.build(draft)['technical']
        self.assertEqual(card['timeframe'], 'EXISTING_INTRADAY_ENGINE_NOT_DAILY')
        self.assertEqual(card['daily_workflow'], 'NOT_EVALUATED')
        self.assertIn('engine_receipt', card)
        self.assertFalse(card['paper_registration_allowed'])
        for change in ('pin', 'ticker', 'future'):
            bad = copy.deepcopy(draft)
            if change == 'pin': bad['technical']['input_hash'] = 'sha256:' + 'f' * 64
            if change == 'ticker': bad['technical']['input']['ticker'] = '600001.SH'
            if change == 'future': bad['generated_at'] = '2026-09-30T06:00:00+00:00'; bad['as_of'] = '20260930'
            with self.subTest(change=change), self.assertRaises(ValueError): self.build(bad)

    def test_feedback_requires_external_pins_and_rebuilds_each_axis(self):
        import test_research_cycle as cycle_fixtures
        root = self.root / 'replay'; root.mkdir()
        closure, cycle, case, _, _, outputs = cycle_fixtures.build_replay(root)
        pins = {'cycle_manifest_sha256': ev.sha((cycle / 'manifest.json').read_bytes()),
                'closure_manifest_sha256': ev.sha((closure / 'manifest.json').read_bytes())}
        request = {'company': case['ticker'], 'as_of': '20260818', 'generated_at': '2026-08-18T20:00:00+08:00'}
        card = self.content()._feedback(pins, request, cycle, closure)
        self.assertEqual(card['axes']['thesis'], outputs[2]['thesis'])
        self.assertEqual(card['pnl'], outputs[2]['pnl'])
        self.assertEqual(card['registration_status'], 'OFFLINE_REPLAY_ONLY')
        bad = {**pins, 'cycle_manifest_sha256': 'f' * 64}
        with self.assertRaisesRegex(ValueError, 'PIN'): self.content()._feedback(bad, request, cycle, closure)
        with self.assertRaisesRegex(ValueError, 'COMPANY'):
            self.content()._feedback(pins, {**request, 'company': '600099.SH'}, cycle, closure)
        with self.assertRaisesRegex(ValueError, 'FUTURE'):
            self.content()._feedback(pins, {**request, 'generated_at': '2026-08-13T19:00:00+08:00'}, cycle, closure)
        score = ev.parse((cycle / 'method_scorecard.json').read_bytes())
        score['thesis']['status'] = 'CORRECT'
        (cycle / 'method_scorecard.json').write_text(ev.canonical(score))
        with self.assertRaises(ValueError): self.content()._feedback(pins, request, cycle, closure)

    def test_output_refuses_extra_files_history_overwrite_and_partial_writes(self):
        content = self.content()
        with mock.patch.object(content, '_observed_at', return_value='2020-01-06T20:00:00+08:00'):
            receipt = content.create(self.draft, self.root / 'pack', self.pack['pack_hash'], self.root / 'content')
            with self.assertRaises(FileExistsError):
                content.create(self.draft, self.root / 'pack', self.pack['pack_hash'], self.root / 'content')
            with self.assertRaisesRegex(ValueError, 'ROOT_OVERLAP'):
                content.create(self.draft, self.root / 'pack', self.pack['pack_hash'], self.root / 'pack/new')
        (self.root / 'content/extra.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'INVENTORY'):
            content.verify(self.root / 'content', receipt['content_hash'], self.root / 'pack', self.pack['pack_hash'])

    def test_each_used_page_read_is_pinned_after_initial_verification(self):
        content = self.content()
        _, read = content._pack(self.root / 'pack', self.pack['pack_hash'])
        page = next((self.root / 'pack/inputs/pages').iterdir())
        page.write_bytes(page.read_bytes() + b'\nchanged')
        with self.assertRaisesRegex(ValueError, 'SOURCE_CHANGED'):
            read(page.relative_to(self.root / 'pack').as_posix())

    def test_manifest_reseal_after_pack_verification_cannot_change_consumed_bytes(self):
        content = self.content()
        original_verify = content.material.verify_research_pack
        def interleave(*args):
            result = original_verify(*args)
            marker = self.root / 'pack/material-pack.json'
            manifest = ev.parse(marker.read_bytes())
            page = next((self.root / 'pack/inputs/pages').iterdir())
            page.write_bytes(page.read_bytes().replace(b'100', b'999'))
            manifest['files'][page.relative_to(self.root / 'pack').as_posix()] = ev.sha(page.read_bytes())
            manifest['pack_hash'] = ev.sealed({k: v for k, v in manifest.items() if k != 'pack_hash'})
            marker.write_text(ev.canonical(manifest))
            return result
        draft = copy.deepcopy(self.draft)
        draft['facts'][0]['value'] = '999'
        draft['facts'][0]['citation']['expected'] = 'Revenue was 999 CNY.'
        with mock.patch.object(content.material, 'verify_research_pack', side_effect=interleave):
            with self.assertRaisesRegex(ValueError, 'PIN'): self.build(draft)

    def test_numeric_formatting_preserves_maximum_precision_under_small_context(self):
        from decimal import Decimal, localcontext
        value = '123456789012345678.123456789012'
        with localcontext() as context:
            context.prec = 6
            self.assertEqual(self.content()._decimal(Decimal(value)), value)
            self.assertEqual(self.content().calculate('DIFFERENCE', [value, '0']), value)

    def test_rounding_and_exponents_do_not_depend_on_ambient_decimal_context(self):
        from decimal import localcontext, ROUND_UP
        with localcontext() as context:
            context.rounding = ROUND_UP
            context.Emax = 9
            self.assertEqual(self.content().calculate('RATIO', ['1', '3']), '0.33333333')
            self.assertEqual(self.content().calculate('DIFFERENCE', ['1234567890123', '1']), '1234567890122')

    def test_feedback_snapshot_preserves_exact_source_inventory(self):
        root = self.root / 'inventory'; root.mkdir()
        (root / 'score.json').write_bytes(b'original')
        manifest = {'artifacts': {'score.json': ev.sha(b'original')}}
        (root / 'manifest.json').write_text(ev.canonical(manifest))
        (root / 'unlisted.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'FEEDBACK_INVENTORY'):
            self.content()._bundle_snapshot(root, ev.sha((root / 'manifest.json').read_bytes()))

    def test_feedback_aba_manifest_swap_cannot_replace_verified_score(self):
        import test_research_cycle as fixtures
        from experiments.research_funnel import research_cycle
        content = self.content()
        root = self.root / 'aba'; root.mkdir()
        closure, cycle, case, _, _, outputs = fixtures.build_replay(root)
        original_manifest = (cycle / 'manifest.json').read_bytes()
        pins = {'cycle_manifest_sha256': ev.sha(original_manifest),
                'closure_manifest_sha256': ev.sha((closure / 'manifest.json').read_bytes())}
        request = {'company': case['ticker'], 'as_of': '20260818', 'generated_at': '2026-08-18T20:00:00+08:00'}
        original_verify = research_cycle.verify_cycle_bundle
        original_read = content.ev.read_local
        attacked = False
        def interleave(*args):
            nonlocal attacked
            result = original_verify(*args)
            score = ev.parse((cycle / 'method_scorecard.json').read_bytes())
            score['pnl']['pnl_cny'] = 999999999
            (cycle / 'method_scorecard.json').write_text(ev.canonical(score))
            manifest = ev.parse(original_manifest)
            manifest['artifacts']['method_scorecard.json'] = ev.sha((cycle / 'method_scorecard.json').read_bytes())
            manifest['bundle_hash'] = fixtures.cycle._hash(manifest['artifacts'])
            (cycle / 'manifest.json').write_text(ev.canonical(manifest))
            attacked = True
            return result
        def restore_manifest_on_last_read(root, name):
            raw = original_read(root, name)
            if attacked and Path(root) == cycle and name == 'method_outcomes.json':
                (cycle / 'manifest.json').write_bytes(original_manifest)
            return raw
        with mock.patch.object(research_cycle, 'verify_cycle_bundle', side_effect=interleave), mock.patch.object(content.ev, 'read_local', side_effect=restore_manifest_on_last_read):
            card = content._feedback(pins, request, cycle, closure)
        self.assertEqual(card['pnl'], outputs[2]['pnl'])

    def test_feedback_snapshot_refuses_modified_artifact_against_initial_manifest(self):
        root = self.root / 'snapshot'; root.mkdir()
        manifest = {'artifacts': {'score.json': ev.sha(b'original')}}
        (root / 'manifest.json').write_text(ev.canonical(manifest))
        pin = ev.sha((root / 'manifest.json').read_bytes())
        (root / 'score.json').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'FEEDBACK_CHANGED'):
            self.content()._bundle_snapshot(root, pin)

    def test_sealed_output_is_rebuilt_not_only_rehashed(self):
        content = self.content()
        with mock.patch.object(content, '_observed_at', return_value='2020-01-06T20:00:00+08:00'):
            receipt = content.create(self.draft, self.root / 'pack', self.pack['pack_hash'], self.root / 'content')
        verified = content.verify(self.root / 'content', receipt['content_hash'], self.root / 'pack', self.pack['pack_hash'])
        self.assertEqual(verified['content_hash'], receipt['content_hash'])
        with self.assertRaises(ValueError):
            content.verify(self.root / 'content', 'f' * 64, self.root / 'pack', self.pack['pack_hash'])
        cards = ev.parse((self.root / 'content/cards.json').read_bytes())
        cards['human_review'] = 'PASS'
        (self.root / 'content/cards.json').write_text(ev.canonical(cards))
        manifest = ev.parse((self.root / 'content/content-manifest.json').read_bytes())
        manifest['files']['cards.json'] = ev.sha((self.root / 'content/cards.json').read_bytes())
        manifest['content_hash'] = ev.sealed({k: v for k, v in manifest.items() if k != 'content_hash'})
        (self.root / 'content/content-manifest.json').write_text(ev.canonical(manifest))
        with self.assertRaisesRegex(ValueError, 'DERIVATION'):
            content.verify(self.root / 'content', manifest['content_hash'], self.root / 'pack', self.pack['pack_hash'])


if __name__ == '__main__':
    unittest.main()
