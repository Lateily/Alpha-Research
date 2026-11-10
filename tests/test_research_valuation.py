"""Evidence bridges must not turn a partial disclosure into normal earnings."""
import copy
import importlib
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/llm'))


def fixture():
    values = {'profit': '100', 'ex_profit': '70', 'total': '30', 'gain': '40',
              'tax': '8', 'minority': '2', 'cash': '1000', 'restricted': '100',
              'short_debt': '100', 'long_debt': '20', 'current_debt': '30',
              'leases': '10', 'other_debt': '5', 'shares': '100', 'eps': '1', 'ex_eps': '0.7', 'ocf': '80'}
    facts = {key: {'id': key, 'value': value, 'period': '2026H1', 'unit': 'CNY'} for key, value in values.items()}
    for key in ('cash', 'restricted', 'short_debt', 'long_debt', 'current_debt', 'leases', 'other_debt', 'shares'):
        facts[key]['period'] = '20260630'
    facts['shares']['unit'] = 'COUNT'
    for key in ('eps', 'ex_eps'): facts[key]['unit'] = 'CNY_PER_SHARE'
    basis = {'schema': 'ar.valuation-basis.v1', 'period': '2026H1',
             'nonrecurring': {'profit': 'profit', 'ex_profit': 'ex_profit', 'total': 'total',
                 'pretax_items': [{'fact_id': 'gain', 'sign': 1}], 'tax': 'tax', 'minority': 'minority',
                 'coverage_note': 'Explicit numeric rows only; blank other items not imputed.'},
             'anchors': {'reported_eps': 'eps', 'ex_nonrecurring_eps': 'ex_eps', 'operating_cashflow': 'ocf'},
             'cash_inventory': {'period': '20260630', 'components': {
                 'cash': 'cash', 'restricted_cash': 'restricted', 'short_term_debt': 'short_debt',
                 'long_term_debt': 'long_debt', 'current_debt_and_lease': 'current_debt',
                 'lease_debt': 'leases', 'other_interest_debt': 'other_debt', 'period_end_shares': 'shares'}}}
    return basis, facts


class ValuationBasisTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('research_valuation'), 'valuation basis missing')
        return importlib.import_module('research_valuation')

    def test_complete_synthetic_bridge_and_inventory_are_not_normalized_eps(self):
        value, facts = fixture(); card = self.module().evaluate(value, facts)
        self.assertEqual(card['nonrecurring']['status'], 'ARITHMETIC_RECONCILED_SEMANTICS_UNVERIFIED')
        self.assertEqual(card['nonrecurring']['after_tax_calculated'], '30')
        self.assertEqual(card['cash_inventory']['net_cash_per_share'], '7.35')
        self.assertEqual(card['anchors']['half_year_ex_eps_x2_sensitivity'], '1.4')
        self.assertEqual(card['status'], 'BASIS_PARTIAL_NORMALIZATION_PENDING')
        self.assertIsNone(card['normalized_eps']); self.assertIsNone(card['value_band'])
        self.assertFalse(card['target_price']); self.assertEqual(card['human_review'], 'PENDING')

    def test_contradictory_bridge_is_visible_not_reconciled(self):
        value, facts = fixture(); facts['tax']['value'] = '7'
        card = self.module().evaluate(value, facts)
        self.assertEqual(card['status'], 'DATA_BLOCKED')
        self.assertEqual(card['nonrecurring']['after_tax_calculated'], '31')
        self.assertEqual(card['nonrecurring']['declared_total'], '30')

    def test_missing_cash_component_is_not_zero_or_partial_net_cash(self):
        value, facts = fixture(); value['cash_inventory']['components']['long_term_debt'] = None
        card = self.module().evaluate(value, facts)['cash_inventory']
        self.assertEqual(card['status'], 'DATA_BLOCKED')
        self.assertIsNone(card['net_cash_per_share']); self.assertIsNone(card['net_cash'])
        self.assertEqual(card['missing_components'], ['long_term_debt'])
        self.assertEqual(card['observed_cash'], '1000')

    def test_typed_references_periods_units_and_signs_are_enforced(self):
        for change in ('period', 'unit', 'ref', 'sign', 'duplicate', 'denominator', 'denominator-fraction', 'cash-period', 'cash-duplicate', 'eps-period'):
            value, facts = fixture()
            if change == 'period': facts['tax']['period'] = '2025FY'
            if change == 'unit': facts['minority']['unit'] = 'PCT'
            if change == 'ref': value['nonrecurring']['tax'] = 'missing'
            if change == 'sign': value['nonrecurring']['pretax_items'][0]['sign'] = True
            if change == 'duplicate': value['nonrecurring']['pretax_items'] *= 2
            if change == 'denominator': facts['shares']['value'] = '0'
            if change == 'denominator-fraction': facts['shares']['value'] = '100.1'
            if change == 'cash-period': facts['restricted']['period'] = '20251231'
            if change == 'cash-duplicate': value['cash_inventory']['components']['long_term_debt'] = 'cash'
            if change == 'eps-period': facts['eps']['period'] = '2026Q1'
            with self.subTest(change=change), self.assertRaises(ValueError): self.module().evaluate(value, facts)

    def test_signed_losses_tax_and_minority_are_not_naively_added(self):
        value, facts = fixture(); facts['loss'] = {**facts['gain'], 'id': 'loss', 'value': '-5'}
        value['nonrecurring']['pretax_items'].append({'fact_id': 'loss', 'sign': 1})
        facts['total']['value'] = '25'; facts['ex_profit']['value'] = '75'
        card = self.module().evaluate(value, facts)
        self.assertEqual(card['nonrecurring']['after_tax_calculated'], '25')

    def v2(self):
        value, facts = fixture(); value['schema'] = 'ar.valuation-basis.v2'
        fields = ('revenue', 'ex_profit', 'reported_eps', 'ex_eps', 'operating_cashflow',
                  'pre_tax_profit', 'tax_expense', 'interest_income', 'operating_cost',
                  'selling_expense', 'admin_expense', 'rd_expense')
        row = {key: None for key in fields}; row.update(period='2025FY', revenue='prior-revenue', ex_eps='prior-eps')
        facts['prior-revenue'] = {'id': 'prior-revenue', 'value': '200', 'unit': 'CNY', 'period': '2025FY'}
        facts['prior-eps'] = {'id': 'prior-eps', 'value': '2', 'unit': 'CNY_PER_SHARE', 'period': '2025FY'}
        value.update(earnings_history=[row], cash_disclosures=[], multiple_observation=None)
        return value, facts

    def evaluate_v2(self, value, facts, **kwargs):
        return self.module().evaluate(value, facts, **{'generated_at': '2026-08-05T16:00:00+08:00', **kwargs})

    def test_v2_requires_a_real_draft_chronology_bound(self):
        value, facts = self.v2()
        with self.assertRaisesRegex(ValueError, 'CHRONOLOGY_BOUND_REQUIRED'):
            self.module().evaluate(value, facts)
        value['period'] = '2028H1'; value['cash_inventory'] = None
        for row in facts.values():
            if row['period'] == '2026H1': row['period'] = '2028H1'
        with self.assertRaisesRegex(ValueError, 'PERIOD_AFTER_CHRONOLOGY_BOUND'):
            self.evaluate_v2(value, facts)

    def test_v2_annual_history_is_not_automatically_normalized_eps(self):
        value, facts = self.v2(); card = self.evaluate_v2(value, facts)
        self.assertEqual(card['earnings_history'][0]['values']['ex_eps'], '2')
        self.assertIsNone(card['normalized_eps']); self.assertIsNone(card['value_band'])
        self.assertIn('operating_cost', card['earnings_history'][0]['missing_fields'])
        self.assertEqual(card['multiple_basis']['status'], 'DATA_BLOCKED')

    def test_v2_future_or_nonannual_history_and_wrong_units_are_rejected(self):
        for bad in ('future', 'half-year', 'unit', 'duplicate'):
            value, facts = self.v2()
            if bad in ('future', 'half-year'):
                period = '2026FY' if bad == 'future' else '2025H1'
                value['earnings_history'][0]['period'] = period
                facts['prior-revenue']['period'] = facts['prior-eps']['period'] = period
            if bad == 'unit': facts['prior-eps']['unit'] = 'CNY'
            if bad == 'duplicate': value['earnings_history'] *= 2
            with self.subTest(bad=bad), self.assertRaises(ValueError): self.evaluate_v2(value, facts)

    def test_v2_nonapplicability_is_bound_but_not_a_fabricated_numeric_zero(self):
        value, facts = self.v2(); value['cash_inventory']['components']['long_term_debt'] = None
        quote = '45\u3001 \u957f\u671f\u501f\u6b3e\n(1) \u957f\u671f\u501f\u6b3e\u5206\u7c7b\n\u25a1\u9002\u7528 \u221a\u4e0d\u9002\u7528'
        citation = {'sha256': 'a'*64, 'page': 1, 'start': 1, 'end': 3, 'expected': quote}
        value['cash_disclosures'] = [{'component': 'long_term_debt', 'period': '20260630',
            'kind': 'EXPLICIT_NOT_APPLICABLE', 'citation': citation}]
        read = lambda name: quote.encode()
        card = self.evaluate_v2(value, facts, read=read)
        self.assertIsNone(card['cash_inventory']['net_cash_per_share'])
        self.assertEqual(card['cash_disclosures'][0]['numeric_zero_inferred'], False)
        for bad in ('changed-quote', 'period', 'conflicting-number'):
            broken = copy.deepcopy(value)
            if bad == 'changed-quote': broken['cash_disclosures'][0]['citation']['expected'] = 'not the same quote'
            if bad == 'period': broken['cash_disclosures'][0]['period'] = '20251231'
            if bad == 'conflicting-number': broken['cash_inventory']['components']['long_term_debt'] = 'long_debt'
            with self.subTest(bad=bad), self.assertRaises(ValueError): self.evaluate_v2(broken, facts, read=read)

    def test_v2_multiple_history_is_not_a_fair_multiple_and_pin_is_checked(self):
        import workbench_evidence as ev
        value, facts = self.v2()
        payload = {'schema': 'ar.local-pe-observation.v1', 'company': '603986.SH',
            'captured_at': '2026-08-04T16:00:00+08:00', 'cutoff_trade_date': '20260803',
            'source_scope': 'SQLITE_MAIN_FILE_IMMUTABLE_READ_NOT_FULL_WAL_OR_PUBLICATION_ACCEPTANCE',
            'source_table': 'raw_daily_basic', 'source_db_sha256': 'a'*64,
            'rows': [{'trade_date': '20260803', 'pe_ttm': '20', 'pb': '2'}]}
        payload['observation_hash'] = ev.sealed(payload)
        value['multiple_observation'] = {'observation': payload, 'observation_hash': payload['observation_hash']}
        kwargs = {'company': '603986.SH', 'generated_at': '2026-08-05T16:00:00+08:00'}
        card = self.module().evaluate(value, facts, **kwargs)
        self.assertEqual(card['multiple_basis']['observed_positive_pe_range'], {'low': '20', 'high': '20'})
        self.assertIsNone(card['multiple_basis']['fair_multiple_low'])
        self.assertEqual(card['multiple_basis']['status'], 'OBSERVED_MARKET_PE_NOT_FAIR_MULTIPLE')
        value['multiple_observation']['observation_hash'] = 'f'*64
        with self.assertRaisesRegex(ValueError, 'PIN'): self.module().evaluate(value, facts, **kwargs)

    def test_malformed_basis_type_still_raises_a_contract_error(self):
        for value in ([], 'invalid', 1, None):
            with self.subTest(value=value), self.assertRaises(ValueError): self.module().evaluate(value, {})

    def test_classification_gap_keeps_a_disclosed_payable_out_of_an_invented_debt_total(self):
        value, facts = self.v2(); value['cash_inventory']['components']['other_interest_debt'] = None
        quote = 'Asset purchase payables 5; financing scope unverified.'
        value['cash_disclosures'] = [{'component': 'other_interest_debt', 'period': '20260630',
            'kind': 'CLASSIFICATION_SCOPE_UNRESOLVED', 'citation': {'sha256': 'a'*64,
             'page': 1, 'start': 1, 'end': 1, 'expected': quote}}]
        card = self.evaluate_v2(value, facts, read=lambda name: quote.encode())
        self.assertEqual(card['cash_inventory']['missing_components'], ['other_interest_debt'])
        self.assertIsNone(card['cash_inventory']['net_cash_per_share'])

    def test_multiple_future_identity_order_and_preclose_captures_are_rejected(self):
        import workbench_evidence as ev
        for change in ('company', 'future', 'preclose', 'order', 'nonfinite'):
            value, facts = self.v2()
            source = {'schema': 'ar.local-pe-observation.v1', 'company': '603986.SH',
                'captured_at': '2026-08-04T16:00:00+08:00', 'cutoff_trade_date': '20260803',
                'source_scope': 'SQLITE_MAIN_FILE_IMMUTABLE_READ_NOT_FULL_WAL_OR_PUBLICATION_ACCEPTANCE',
                'source_table': 'raw_daily_basic', 'source_db_sha256': 'a'*64,
                'rows': [{'trade_date': '20260803', 'pe_ttm': '20', 'pb': '2'}]}
            if change == 'company': source['company'] = '600000.SH'
            if change == 'future': source['captured_at'] = '2026-08-06T16:00:00+08:00'
            if change == 'preclose': source['captured_at'] = '2026-08-03T14:00:00+08:00'
            if change == 'order': source['rows'] *= 2
            if change == 'nonfinite': source['rows'][0]['pe_ttm'] = 'Infinity'
            source['observation_hash'] = ev.sealed(source)
            value['multiple_observation'] = {'observation': source, 'observation_hash': source['observation_hash']}
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.module().evaluate(value, facts, company='603986.SH', generated_at='2026-08-05T16:00:00+08:00')


if __name__ == '__main__':
    unittest.main()
