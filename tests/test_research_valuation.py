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


if __name__ == '__main__':
    unittest.main()
