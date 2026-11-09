"""New source evidence must not silently become a calibrated valuation."""
import copy
from decimal import localcontext
import importlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO/'scripts/llm'), str(REPO/'tests'), str(REPO)]


def fixture():
    from test_research_normalization import fixture as previous
    cards, normal = previous()
    values = {
        'ni': ('248','CNY','2025FY'), 'deps': ('2.48','CNY_PER_SHARE','2025FY'),
        'bs': ('100','COUNT','2025FY'), 'ds': ('100','COUNT','2025FY'),
        'current-tax': ('30','CNY','2025FY'), 'deferred-tax': ('-2','CNY','2025FY'),
        'rd-cap': ('10','CNY','2025FY'), 'rd-total': ('40','CNY','2025FY'),
        'cash': ('1000','CNY','20251231'), 'restricted': ('10','CNY','20251231'),
        'short': ('20','CNY','20251231'), 'long': ('30','CNY','20251231'),
        'current-debt': ('40','CNY','20251231'), 'lease': ('50','CNY','20251231'),
        'other': ('60','CNY','20251231'), 'end-shares': ('100','COUNT','20251231'),
        'cash-eq': ('800','CNY','20251231'), 'excluded': ('200','CNY','20251231'),
        'excluded-freeze': ('10','CNY','20251231'), 'deposit': ('180','CNY','20251231'),
        'accrual': ('10','CNY','20251231')}
    cards['facts']['observations'] += [{'id':key,'value':value,'unit':unit,'period':period}
                                      for key,(value,unit,period) in values.items()]
    missing = lambda unit: {'value':None,'unit':unit,'rationale':'Not established.','fact_ids':[]}
    worksheet = {'schema':'ar.research-basis-worksheet.v1','company':cards['company'],
        'normalization_worksheet':normal,
        'dilution':[{'period':'2025FY','profit':'ni','reported_eps':'deps','basic_shares':'bs','diluted_shares':'ds'}],
        'tax':[{'period':'2025FY','pretax':'pre_tax_profit','current':'current-tax','deferred':'deferred-tax','total':'tax_expense'}],
        'rd':[{'period':'2025FY','expense':'rd_expense','capitalized':'rd-cap','total':'rd-total'}],
        'cash':{'period':'20251231','components':{'cash':'cash','restricted_cash':'restricted',
            'short_term_debt':'short','long_term_debt':'long','current_debt_and_lease':'current-debt',
            'lease_debt':'lease','other_interest_debt':'other','period_end_shares':'end-shares'},
            'declared_equivalents':'cash-eq','excluded_from_equivalents':'excluded',
            'excluded_components':['excluded-freeze','deposit','accrual'],'operating_reserve':missing('CNY')},
        'notes':[], 'multiple':{key:missing('PCT') for key in ('discount_pct','growth_pct','payout_pct')},
        'daily':None}
    return cards, worksheet


class BasisEvidenceTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('research_basis_evidence'),'basis evidence producer missing')
        return importlib.import_module('research_basis_evidence')

    def derive(self, cards, worksheet, read=None):
        return self.module().derive(cards,worksheet,read=read)

    def test_reported_dilution_is_recomputed_not_normalized(self):
        cards,w=fixture(); result=self.derive(cards,w)
        row=result['dilution'][0]
        self.assertEqual(row['reported_denominator'],'100')
        self.assertEqual(row['recomputed_reported_eps'],'2.48')
        self.assertEqual(row['status'],'REPORTED_ARITHMETIC_RECONCILED_NOT_NORMALIZED')
        self.assertIsNone(result['normalized_eps']); self.assertIsNone(result['value_band'])
        self.assertEqual(result['human_review'],'PENDING'); self.assertFalse(result['claim_allowed'])

    def test_missing_denominator_is_not_inverted_from_eps(self):
        cards,w=fixture(); w['dilution'][0]['diluted_shares']=None
        row=self.derive(cards,w)['dilution'][0]
        self.assertIsNone(row['reported_denominator']); self.assertIsNone(row['recomputed_reported_eps'])
        self.assertEqual(row['status'],'DATA_BLOCKED')

    def test_conflicting_dilution_stays_blocked(self):
        cards,w=fixture(); next(x for x in cards['facts']['observations'] if x['id']=='ds')['value']='99'
        self.assertEqual(self.derive(cards,w)['dilution'][0]['status'],'DATA_BLOCKED')

    def test_current_and_deferred_tax_are_not_a_normal_tax_rate(self):
        cards,w=fixture(); result=self.derive(cards,w); row=result['tax'][0]
        self.assertEqual(row['current_plus_deferred'],'28')
        self.assertEqual(row['reported_effective_tax_pct'],'10')
        self.assertIsNone(row['normal_tax_pct'])
        next(x for x in cards['facts']['observations'] if x['id']=='deferred-tax')['value']='-3'
        self.assertEqual(self.derive(cards,w)['tax'][0]['status'],'DATA_BLOCKED')

    def test_rd_capitalization_is_diagnostic_not_an_automatic_addback(self):
        cards,w=fixture(); row=self.derive(cards,w)['rd'][0]
        self.assertEqual(row['expense_plus_capitalized'],'40'); self.assertEqual(row['capitalized_pct'],'25')
        self.assertIsNone(row['normalization_adjustment'])
        next(x for x in cards['facts']['observations'] if x['id']=='rd-total')['value']='41'
        self.assertEqual(self.derive(cards,w)['rd'][0]['status'],'DATA_BLOCKED')

    def test_cash_equivalent_bridge_and_financing_are_distinct(self):
        cards,w=fixture(); w['cash']['operating_reserve'].update(value='0',fact_ids=['cash'])
        row=self.derive(cards,w)['cash']
        self.assertEqual(row['cash_equivalent_bridge']['money_funds_less_excluded'],'800')
        self.assertEqual(row['cash_equivalent_bridge']['excluded_components_total'],'200')
        self.assertEqual(row['net_cash_inventory'],'790'); self.assertEqual(row['net_cash_per_share'],'7.9')
        self.assertIsNone(row['excess_cash']); self.assertFalse(row['cash_value_credit_allowed'])

    def test_partial_financing_subtotal_is_never_net_cash(self):
        cards,w=fixture(); w['cash']['components']['other_interest_debt']=None
        w['cash']['operating_reserve'].update(value='0',fact_ids=['cash'])
        row=self.derive(cards,w)['cash']
        self.assertEqual(row['known_component_residual'],'850')
        self.assertIsNone(row['net_cash_inventory']); self.assertIsNone(row['net_cash_per_share'])
        self.assertEqual(row['missing_components'],['other_interest_debt'])
        self.assertIsNone(row['excess_cash'])

    def test_missing_operating_reserve_blocks_exact_cash(self):
        cards,w=fixture(); row=self.derive(cards,w)['cash']
        self.assertIsNone(row['net_cash_inventory'])
        self.assertIsNone(row['net_cash_per_share'])
        self.assertEqual(row['known_component_residual'],'790')
        self.assertTrue(row['missing_operating_reserve'])
        self.assertEqual(row['status'],'DATA_BLOCKED')
        self.assertIsNone(row['excess_cash']); self.assertFalse(row['cash_value_credit_allowed'])

    def test_exclusion_bridge_conflict_cannot_look_reconciled(self):
        cards,w=fixture(); next(x for x in cards['facts']['observations'] if x['id']=='deposit')['value']='181'
        row=self.derive(cards,w)['cash']
        self.assertEqual(row['cash_equivalent_bridge']['status'],'DATA_BLOCKED')
        self.assertFalse(row['cash_value_credit_allowed'])

    def test_complete_e4_multiple_is_only_a_sensitivity(self):
        cards,w=fixture()
        for key,value in {'discount_pct':'10','growth_pct':'2','payout_pct':'80'}.items():
            w['multiple'][key].update(value=value,fact_ids=['revenue'])
        row=self.derive(cards,w)['multiple']
        self.assertEqual(row['hypothetical_trailing_pe'],'10.2')
        self.assertIsNone(row['fair_multiple_low']); self.assertIsNone(row['fair_multiple_high'])
        self.assertFalse(row['calibrated']); self.assertEqual(row['evidence_tier'],'E4')

    def test_multiple_missing_or_invalid_spread_never_gets_a_default(self):
        cards,w=fixture(); self.assertIsNone(self.derive(cards,w)['multiple']['hypothetical_trailing_pe'])
        for key in w['multiple']: w['multiple'][key].update(value='10',fact_ids=['revenue'])
        with self.assertRaises(ValueError): self.derive(cards,w)
        w['multiple']['growth_pct']['value']='11'
        with self.assertRaises(ValueError): self.derive(cards,w)

    def test_growth_above_discount_is_rejected_without_a_negative_multiple(self):
        cards,w=fixture()
        for key,value in {'discount_pct':'10','growth_pct':'11','payout_pct':'80'}.items():
            w['multiple'][key].update(value=value,fact_ids=['revenue'])
        with self.assertRaises(ValueError): self.derive(cards,w)

    def test_period_units_duplicates_fractional_shares_and_future_periods_refuse(self):
        for bad in ('unit','period','duplicate','fractional','future','authority'):
            cards,w=fixture()
            if bad=='unit': next(x for x in cards['facts']['observations'] if x['id']=='ds')['unit']='CNY'
            if bad=='period': next(x for x in cards['facts']['observations'] if x['id']=='ds')['period']='2026H1'
            if bad=='duplicate': w['cash']['components']['short_term_debt']='restricted'
            if bad=='fractional': next(x for x in cards['facts']['observations'] if x['id']=='ds')['value']='100.1'
            if bad=='future': w['tax'][0]['period']='2027FY'
            if bad=='authority': w['approved']=True
            with self.subTest(bad=bad), self.assertRaises(ValueError): self.derive(cards,w)

    def test_low_ambient_decimal_precision_does_not_change_diagnostics(self):
        cards,w=fixture(); expected=self.derive(cards,w)
        with localcontext() as ctx:
            ctx.prec=2
            self.assertEqual(self.derive(cards,w),expected)

    def test_qualitative_note_requires_exact_source_quote(self):
        cards,w=fixture(); citation={'sha256':'a'*64,'page':1,'start':1,'end':1,'expected':'No further classification supplied.'}
        w['notes']=[{'topic':'financing','period':'20251231','citation':citation}]
        read=lambda name:b'No further classification supplied.'
        row=self.derive(cards,w,read)['notes'][0]
        self.assertFalse(row['numeric_zero_inferred']); self.assertEqual(row['human_review'],'PENDING')
        with self.assertRaises(ValueError): self.derive(cards,w,lambda name:b'different')

    def test_empty_evidence_groups_stay_unresolved(self):
        cards,w=fixture(); w.update(dilution=[],tax=[],rd=[],cash=None)
        result=self.derive(cards,w)
        self.assertEqual(result['cash']['status'],'DATA_BLOCKED')
        self.assertIsNone(result['normalized_eps']); self.assertIsNone(result['value_band'])
        self.assertFalse(result['daily']['eligible'])

    def test_balance_date_is_not_an_earnings_period(self):
        cards,w=fixture(); w['dilution'][0]['period']='20251231'
        for row in cards['facts']['observations']:
            if row['id'] in {'ni','deps','bs','ds'}: row['period']='20251231'
        with self.assertRaises(ValueError): self.derive(cards,w)


class BasisArtifactTests(unittest.TestCase):
    def setUp(self):
        from test_research_normalization import NormalizationArtifactTests
        self.f=NormalizationArtifactTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.module=importlib.import_module('research_basis_evidence'); self.ev=self.f.ev
        self.root=self.f.root; _,self.worksheet=fixture()
        self.worksheet.update(company='600000.SH',normalization_worksheet=self.f.worksheet,
                              dilution=[],tax=[],rd=[],cash=None)
        self.raw=self.ev.canonical(self.worksheet).encode(); self.pin=self.ev.sha(self.raw)
        # Only in-process synthetic creation uses a deterministic Git-less identity.
        patch=mock.patch.object(self.module,'_execution_identity',return_value={'code_sha':'a'*40,'source_tree_hash':'b'*64})
        patch.start(); self.addCleanup(patch.stop)

    def args(self): return self.f.args()

    def test_public_create_reopen_and_coherent_forgery_refusal(self):
        output=self.root/'basis'; receipt=self.module.create(self.raw,self.pin,*self.args(),output)
        self.assertEqual(self.module.verify(output,receipt['basis_hash'],*self.args()),receipt)
        card=self.ev.parse((output/'basis-card.json').read_bytes()); card['normalized_eps']='99'
        (output/'basis-card.json').write_text(self.ev.canonical(card))
        marker=output/self.module.MARKER; manifest=self.ev.parse(marker.read_bytes())
        manifest['files']['basis-card.json']=self.ev.sha((output/'basis-card.json').read_bytes())
        manifest['basis_hash']=self.ev.sealed({key:value for key,value in manifest.items() if key!='basis_hash'})
        marker.write_text(self.ev.canonical(manifest))
        with self.assertRaisesRegex(ValueError,'DERIVATION'):
            self.module.verify(output,manifest['basis_hash'],*self.args())

    def test_wrong_external_worksheet_pin_refuses_before_output(self):
        output=self.root/'refused'
        with self.assertRaisesRegex(ValueError,'WORKSHEET_PIN'):
            self.module.create(self.raw,'f'*64,*self.args(),output)
        self.assertFalse(output.exists())

    def test_source_reseal_cannot_replace_the_external_content_pin(self):
        path=self.f.content_root/'cards.json'; card=self.ev.parse(path.read_bytes()); card['company']='603986.SH'
        path.write_text(self.ev.canonical(card))
        marker=self.f.content_root/'content-manifest.json'; saved=self.ev.parse(marker.read_bytes())
        saved['files']['cards.json']=self.ev.sha(path.read_bytes())
        saved['content_hash']=self.ev.sealed({key:value for key,value in saved.items() if key!='content_hash'})
        marker.write_text(self.ev.canonical(saved))
        output=self.root/'refused'
        with self.assertRaises(ValueError): self.module.create(self.raw,self.pin,*self.args(),output)
        self.assertFalse(output.exists())

    def test_size_and_source_overlap_refuse_before_output(self):
        output=self.root/'overlimit'
        with mock.patch.object(self.ev,'MAX_FILE',32):
            with self.assertRaises(ValueError): self.module.create(self.raw,self.pin,*self.args(),output)
        self.assertFalse(output.exists())
        with self.assertRaisesRegex(ValueError,'ROOT_OVERLAP'):
            self.module.create(self.raw,self.pin,*self.args(),self.f.content_root/'child')
        self.assertFalse((self.f.content_root/'child').exists())

    def test_actual_guarded_cli_create_verify_and_wrong_pin(self):
        import scripts.governance_mutation_gate as gate
        guard=self.root/'child-guard'; gate._write_network_guard(guard)
        environment=gate._subprocess_env(REPO,guard)
        environment['PYTHONPATH']=str(guard)
        source=self.root/'basis-worksheet.json'; source.write_bytes(self.raw); output=self.root/'cli-basis'
        command=[sys.executable,'-B',str(REPO/'scripts/llm/research_basis_evidence.py')]
        common=['--content-root',str(self.f.content_root),'--content-hash',self.f.receipt['content_hash'],
                '--pack-root',str(self.root/'pack'),'--pack-hash',self.f.f.pack['pack_hash'],'--output',str(output)]
        created=subprocess.run(command+['create',*common,'--worksheet',str(source),'--worksheet-hash',self.pin],
                               cwd=self.root,env=environment,capture_output=True,timeout=30)
        self.assertEqual(created.returncode,0,created.stderr.decode())
        receipt=self.ev.parse(created.stdout)
        reopened=subprocess.run(command+['verify',*common,'--basis-hash',receipt['basis_hash']],
                                cwd=self.root,env=environment,capture_output=True,timeout=30)
        self.assertEqual(reopened.returncode,0,reopened.stderr.decode())
        self.assertEqual(self.ev.parse(reopened.stdout),receipt)
        refused=subprocess.run(command+['verify',*common,'--basis-hash','f'*64],
                               cwd=self.root,env=environment,capture_output=True,timeout=30)
        self.assertNotEqual(refused.returncode,0)

    def test_rootless_cli_help_keeps_real_imports(self):
        import scripts.governance_mutation_gate as gate
        guard=self.root/'help-guard'; gate._write_network_guard(guard)
        environment=gate._subprocess_env(REPO,guard); environment['PYTHONPATH']=str(guard)
        child=subprocess.run([sys.executable,'-B',str(REPO/'scripts/llm/research_basis_evidence.py'),'--help'],
                             cwd=self.root,env=environment,capture_output=True,timeout=30)
        self.assertEqual(child.returncode,0,child.stderr.decode())
        self.assertIn(b'--content-root',child.stdout)


if __name__=='__main__': unittest.main()
