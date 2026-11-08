"""Reported arithmetic and analyst scenarios must never become financial approval."""
import copy
import importlib
import importlib.util
from pathlib import Path
import sys
import subprocess
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/llm'))


def fixture():
    import research_valuation as valuation
    values = dict(revenue='1000', operating_cost='600', selling_expense='100',
                  admin_expense='20', rd_expense='30', pre_tax_profit='280',
                  tax_expense='28', interest_income='10')
    facts = [{'id': k, 'value': v, 'period': '2025FY', 'unit': 'CNY'} for k, v in values.items()]
    annual = {'period': '2025FY', 'references': {k: k if k in values else None for k in valuation.HISTORY_FIELDS}}
    cards = {'company': '603986.SH', 'material_cutoff_at': '2026-10-04T23:59:59+08:00',
             'generated_at': '2026-11-09T02:00:00+08:00',
             'facts': {'observations': facts}, 'valuation': {'earnings_history': [annual],
             'cash_inventory': {'status': 'DATA_BLOCKED', 'net_cash_per_share': None},
             'multiple_basis': {'fair_multiple_low': None, 'fair_multiple_high': None}}}
    units = {'revenue': 'CNY', 'gross_margin_pct': 'PCT', 'operating_expenses': 'CNY',
             'net_operating_adjustments': 'CNY', 'tax_pct': 'PCT', 'diluted_shares': 'COUNT'}
    worksheet = {'schema': 'ar.normalization-worksheet.v1', 'company': cards['company'],
                 'assumptions': {k: {'value': None, 'unit': unit,
                     'rationale': 'Not yet established.', 'fact_ids': ['revenue']} for k, unit in units.items()},
                 'interest_policy': 'UNRESOLVED', 'interest_reconciliation': None, 'dilution_anchors': []}
    return cards, worksheet


class NormalizationTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('research_normalization'), 'normalization worksheet missing')
        return importlib.import_module('research_normalization')

    def test_reported_bridge_is_not_ebit_or_normal_eps(self):
        cards, worksheet = fixture(); result = self.module().derive(cards, worksheet)
        row = result['reported_bridges'][0]
        self.assertEqual(row['gross_profit'], '400')
        self.assertEqual(row['sales_admin_rd'], '150')
        self.assertEqual(row['gross_less_sales_admin_rd'], '250')
        self.assertEqual(row['residual_to_pretax'], '30')
        self.assertEqual(row['pretax_less_reported_interest_income'], '270')
        self.assertEqual(row['reported_effective_tax_pct'], '10')
        self.assertIsNone(result['normalized_eps']); self.assertIsNone(result['value_band'])
        self.assertIsNone(result['scenario']['eps'])
        self.assertEqual(len(result['scenario']['missing_assumptions']), 6)

    def test_zero_pretax_does_not_impute_a_normal_tax_rate(self):
        cards, worksheet = fixture()
        next(row for row in cards['facts']['observations'] if row['id']=='pre_tax_profit')['value']='0'
        row=self.module().derive(cards,worksheet)['reported_bridges'][0]
        self.assertIsNone(row['reported_effective_tax_pct'])
        self.assertIsNone(self.module().derive(cards,worksheet)['assumptions']['tax_pct']['value'])

    def test_complete_synthetic_scenario_is_only_an_e4_hypothesis(self):
        cards, worksheet = fixture()
        for k, v in dict(revenue='1000', gross_margin_pct='50', operating_expenses='100',
                         net_operating_adjustments='0', tax_pct='20', diluted_shares='100').items():
            worksheet['assumptions'][k]['value'] = v
        worksheet.update(interest_policy='EXCLUDED_FROM_OPERATING_EARNINGS',
                         interest_reconciliation={'fact_ids': ['interest_income'],
                             'rationale': 'Synthetic: cash interest excluded from operating adjustments.'})
        result = self.module().derive(cards, worksheet)
        self.assertEqual(result['scenario']['eps'], '3.2')
        self.assertEqual(result['scenario']['status'], 'HYPOTHETICAL_UNCALIBRATED_E4')
        self.assertIsNone(result['normalized_eps']); self.assertFalse(result['calibrated'])
        self.assertEqual(result['human_review'], 'PENDING')

    def test_missing_or_conflicting_reported_fields_are_not_zero(self):
        cards, worksheet = fixture(); cards['facts']['observations'] = [x for x in cards['facts']['observations'] if x['id'] != 'rd_expense']
        with self.assertRaises(ValueError): self.module().derive(cards, worksheet)
        cards, worksheet = fixture(); cards['valuation']['earnings_history'][0]['references']['rd_expense'] = None
        result = self.module().derive(cards, worksheet)
        self.assertIsNone(result['reported_bridges'][0]['sales_admin_rd'])
        self.assertIsNone(result['reported_bridges'][0]['residual_to_pretax'])

    def test_period_units_identity_and_assumption_ranges_are_enforced(self):
        for change in ('company', 'fact_period', 'fact_unit', 'unknown_fact', 'tax', 'shares', 'nonfinite', 'extra'):
            cards, worksheet = fixture()
            if change == 'company': worksheet['company'] = '600000.SH'
            if change == 'fact_period': cards['facts']['observations'][0]['period'] = '2026H1'
            if change == 'fact_unit': cards['facts']['observations'][0]['unit'] = 'PCT'
            if change == 'unknown_fact': worksheet['assumptions']['revenue']['fact_ids'] = ['missing']
            if change == 'tax': worksheet['assumptions']['tax_pct']['value'] = '101'
            if change == 'shares': worksheet['assumptions']['diluted_shares']['value'] = '0'
            if change == 'nonfinite': worksheet['assumptions']['revenue']['value'] = 'Infinity'
            if change == 'extra': worksheet['approved'] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.module().derive(cards, worksheet)

    def test_unknown_assumption_can_have_no_evidence_but_numeric_claim_cannot(self):
        cards, worksheet = fixture(); worksheet['assumptions']['diluted_shares']['fact_ids'] = []
        try:
            result = self.module().derive(cards, worksheet)
        except ValueError as exc:
            self.fail('Honest missing denominator was refused: ' + str(exc))
        self.assertIsNone(result['scenario']['eps'])
        worksheet['assumptions']['diluted_shares']['value'] = '100'
        with self.assertRaises(ValueError): self.module().derive(cards, worksheet)

    def test_negative_margin_is_a_visible_loss_hypothesis_not_false_refusal(self):
        cards, worksheet = fixture()
        for key,value in dict(revenue='1000', gross_margin_pct='-50', operating_expenses='100',
                              net_operating_adjustments='0', tax_pct='20', diluted_shares='100').items():
            worksheet['assumptions'][key]['value'] = value
        worksheet.update(interest_policy='EXCLUDED_FROM_OPERATING_EARNINGS',
                         interest_reconciliation={'fact_ids': ['interest_income'], 'rationale': 'Explicit synthetic exclusion.'})
        try:
            result = self.module().derive(cards, worksheet)
        except ValueError as exc:
            self.fail('Loss hypothesis was refused: ' + str(exc))
        self.assertEqual(result['scenario']['eps'], '-4.8')
        self.assertIsNone(result['normalized_eps'])

    def test_reported_dilution_does_not_infer_precise_shares_from_rounded_eps(self):
        cards, worksheet = fixture()
        cards['facts']['observations'].extend([
            {'id': 'ni', 'value': '248', 'period': '2025FY', 'unit': 'CNY'},
            {'id': 'deps', 'value': '2.47', 'period': '2025FY', 'unit': 'CNY_PER_SHARE'}])
        anchor = {'period': '2025FY', 'profit_fact_id': 'ni', 'diluted_eps_fact_id': 'deps',
                  'denominator_fact_id': None}
        worksheet['dilution_anchors'] = [anchor]
        row = self.module().derive(cards, worksheet)['reported_dilution'][0]
        self.assertEqual(row['reported_diluted_eps'], '2.47')
        self.assertIsNone(row['weighted_diluted_shares'])
        self.assertEqual(row['status'], 'DENOMINATOR_NOT_DISCLOSED')
        for bad in ('period', 'unit'):
            with self.subTest(bad=bad):
                changed = copy.deepcopy(cards)
                if bad == 'period': changed['facts']['observations'][-1]['period'] = '2024FY'
                if bad == 'unit': changed['facts']['observations'][-1]['unit'] = 'COUNT'
                with self.assertRaises(ValueError): self.module().derive(changed, worksheet)
        cards['facts']['observations'][-1]['value'] = '0'
        self.assertEqual(self.module().derive(cards, worksheet)['reported_dilution'][0]['reported_diluted_eps'], '0')
        cards['facts']['observations'][-1]['value'] = '-2.47'
        self.assertEqual(self.module().derive(cards, worksheet)['reported_dilution'][0]['reported_diluted_eps'], '-2.47')


class NormalizationArtifactTests(unittest.TestCase):
    def setUp(self):
        from test_research_content import ResearchContentTests
        import workbench_evidence as ev
        self.ev = ev
        self.f = ResearchContentTests('test_content_and_missing_cards_are_honest')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.content = self.f.content(); self.root = self.f.root
        self.content_root = self.root/'content'
        with mock.patch.object(self.content, '_observed_at', return_value='2020-01-06T20:00:00+08:00'):
            self.receipt = self.content.create(self.f.draft, self.root/'pack', self.f.pack['pack_hash'], self.content_root)
        self.worksheet = fixture()[1]; self.worksheet['company'] = '600000.SH'
        self.raw = ev.canonical(self.worksheet).encode(); self.pin = ev.sha(self.raw)

    def module(self):
        return importlib.import_module('research_normalization')

    def args(self):
        return (self.content_root, self.receipt['content_hash'], self.root/'pack', self.f.pack['pack_hash'])

    def test_actual_sealed_reopen_and_tamper_rejection(self):
        module = self.module(); output = self.root/'normalization'
        receipt = module.create(self.raw, self.pin, *self.args(), output)
        self.assertEqual(module.verify(output, receipt['normalization_hash'], *self.args()), receipt)
        card = self.ev.parse((output/'normalization-card.json').read_bytes()); card['normalized_eps'] = '99'
        (output/'normalization-card.json').write_text(self.ev.canonical(card))
        manifest = self.ev.parse((output/module.MARKER).read_bytes())
        manifest['files']['normalization-card.json'] = self.ev.sha((output/'normalization-card.json').read_bytes())
        manifest['normalization_hash'] = self.ev.sealed({k:v for k,v in manifest.items() if k!='normalization_hash'})
        (output/module.MARKER).write_text(self.ev.canonical(manifest))
        with self.assertRaisesRegex(ValueError, 'DERIVATION'):
            module.verify(output, manifest['normalization_hash'], *self.args())

    def test_wrong_external_worksheet_pin_refuses_before_output(self):
        output = self.root/'refused'
        with self.assertRaisesRegex(ValueError, 'WORKSHEET_PIN'):
            self.module().create(self.raw, 'f'*64, *self.args(), output)
        self.assertFalse(output.exists())

    def test_cli_create_verify_and_external_pin_refusal(self):
        worksheet = self.root/'worksheet.json'; worksheet.write_bytes(self.raw)
        output = self.root/'cli-result'
        command = [sys.executable, '-B', str(Path(__file__).resolve().parents[1]/'scripts/llm/research_normalization.py')]
        common = ['--content-root', str(self.content_root), '--content-hash', self.receipt['content_hash'],
                  '--pack-root', str(self.root/'pack'), '--pack-hash', self.f.pack['pack_hash'], '--output', str(output)]
        created = subprocess.run(command+['create', *common, '--worksheet', str(worksheet), '--worksheet-hash', self.pin], capture_output=True, timeout=30)
        self.assertEqual(created.returncode, 0, created.stderr.decode())
        receipt = self.ev.parse(created.stdout)
        reopened = subprocess.run(command+['verify', *common, '--normalization-hash', receipt['normalization_hash']], capture_output=True, timeout=30)
        self.assertEqual(reopened.returncode, 0, reopened.stderr.decode())
        self.assertEqual(self.ev.parse(reopened.stdout), receipt)
        wrong = subprocess.run(command+['verify', *common, '--normalization-hash', 'f'*64], capture_output=True, timeout=30)
        self.assertNotEqual(wrong.returncode, 0)

    def test_output_limit_and_root_overlap_refuse_before_creation(self):
        output = self.root/'overlimit'
        with mock.patch.object(self.ev, 'MAX_FILE', 32):
            with self.assertRaises(ValueError): self.module().create(self.raw, self.pin, *self.args(), output)
        self.assertFalse(output.exists())
        with self.assertRaisesRegex(ValueError, 'ROOT_OVERLAP'):
            self.module().create(self.raw, self.pin, *self.args(), self.content_root/'child')
        self.assertFalse((self.content_root/'child').exists())

    def test_coherent_source_reseal_does_not_replace_externally_pinned_source(self):
        path = self.content_root/'cards.json'; data = self.ev.parse(path.read_bytes())
        data['company'] = '603986.SH'; path.write_text(self.ev.canonical(data))
        marker = self.content_root/'content-manifest.json'; manifest = self.ev.parse(marker.read_bytes())
        manifest['files']['cards.json'] = self.ev.sha(path.read_bytes())
        manifest['content_hash'] = self.ev.sealed({k:v for k,v in manifest.items() if k!='content_hash'})
        marker.write_text(self.ev.canonical(manifest))
        output = self.root/'changed-source'
        with self.assertRaises(ValueError): self.module().create(self.raw, self.pin, *self.args(), output)
        self.assertFalse(output.exists())

    def test_source_manifest_swapped_after_verify_is_not_accepted(self):
        module = self.module(); original_verify = self.content.verify
        def changed(*args):
            receipt = original_verify(*args)
            path = self.content_root/'content-manifest.json'; manifest = self.ev.parse(path.read_bytes())
            manifest['created_at'] = '2020-01-07T20:00:00+08:00'
            manifest['content_hash'] = self.ev.sealed({k:v for k,v in manifest.items() if k!='content_hash'})
            path.write_text(self.ev.canonical(manifest))
            return receipt
        with mock.patch.object(self.content, 'verify', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'SOURCE_PIN'):
                module._snapshot(*self.args())


if __name__ == '__main__':
    unittest.main()
