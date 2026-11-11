"""Exact-scope gap history from actual offline EndpointSession receipts."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts/llm'),str(ROOT)]
import workbench_evidence as ev
from experiments.data_governance.endpoint_calls import EndpointSession, EndpointObservationError


class CoreGapTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('core_source_gaps'),'core gap ledger is not implemented')
        import core_source_gaps
        return core_source_gaps

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve(); self.serial=0
        self.ledger=self.root/'ledger'

    def source(self, *, api='moneyflow_dc',date='20261030',symbol='603629.SH',kind='down',
               stamp='2026-11-09T18:00:00+00:00',number=2.5):
        self.serial+=1; root=self.root/('source-'+str(self.serial))
        clock=lambda:datetime.fromisoformat(stamp)
        session=EndpointSession(root,collector_run_id='gap-fixture-'+str(self.serial),target_trade_date=date,clock=clock)
        fields=['ts_code','trade_date','net_amount' if api=='moneyflow_dc' else 'close']
        def invoke():
            if kind=='down': raise OSError('PRIVATE_PROVIDER_ERROR')
            if kind=='permission': raise PermissionError('PRIVATE_PERMISSION_MESSAGE')
            return {'code':0,'data':{'fields':fields,'items':[] if kind=='empty' else [[symbol,date,number]]}}
        try: session.observe(api,{'ts_code':symbol,'trade_date':date},','.join(fields),invoke)
        except EndpointObservationError: pass
        return root

    def ingest(self,source,head=None):
        m=self.module(); pin=m.evidence(source)['evidence_hash']
        return m.ingest(self.ledger,source,expected_evidence_hash=pin,expected_head=head or '0'*64)

    def view(self,head):
        return self.module().view(self.ledger,expected_head=head,observed_at='2099-01-01T00:00:00Z')

    def scope(self,api='moneyflow_dc',date='20261030',symbol='603629.SH'):
        return {'api_name':api,'ts_code':symbol,'trade_date':date,
                'fields':','.join(sorted(['ts_code','trade_date','net_amount' if api=='moneyflow_dc' else 'close']))}

    def coverage(self,scopes,head=None,pin=None):
        m=self.module()
        self.assertTrue(callable(getattr(m,'coverage',None)),
                        'required but never-called core scopes are not projected')
        return m.coverage(self.ledger,scopes,expected_scope_hash=pin or ev.sealed(scopes),
                          expected_head=head or '0'*64,observed_at='2099-01-01T00:00:00Z')

    def test_required_but_never_called_scope_stays_explicitly_blocked(self):
        scopes=[self.scope('daily'),self.scope()]
        value=self.coverage(scopes)
        self.assertEqual(value['status'],'DATA_BLOCKED')
        self.assertEqual(value['counts'],{'expected':2,'observed':0,'valid':0,'missing':2})
        self.assertEqual(len(value['scopes']),2)
        self.assertTrue(all(r['status']=='DATA_BLOCKED' and r['reason']=='NO_CALL_EVIDENCE'
                            and not r['dispatch_allowed'] for r in value['scopes']))
        self.assertFalse(self.ledger.exists(),'read-only coverage must not create a ledger')
        self.assertFalse(value['automatic_retry'])
        self.assertEqual(value['research_readiness'],'NOT_EVALUATED')

    def test_coverage_cli_accepts_exact_envelope_and_refuses_unknown_fields(self):
        head=self.ingest(self.source(api='daily',kind='good'))['head_hash']
        scopes=[self.scope('daily'),self.scope()]
        source=self.root/'expectations.json'
        envelope={'schema':'ar.core-source-expectations.v1','scopes':scopes}
        command=[sys.executable,'-B',str(ROOT/'scripts/llm/core_source_gaps.py'),'coverage',
                 '--root',str(self.ledger),'--expectations',str(source),'--head',head,
                 '--observed-at','2099-01-01T00:00:00Z','--scope-pin',ev.sealed(scopes)]
        source.write_bytes(ev.canonical(envelope).encode())
        actual=subprocess.run(command,capture_output=True,timeout=30)
        self.assertEqual(actual.returncode,0,actual.stderr.decode())
        self.assertEqual(ev.parse(actual.stdout),self.coverage(scopes,head))
        wrong_pin=subprocess.run(command[:-1]+['f'*64],capture_output=True,timeout=30)
        self.assertEqual(wrong_pin.returncode,2)
        self.assertEqual(wrong_pin.stdout,b'')
        for malformed in (scopes,{**envelope,'schema':'unknown'},{**envelope,'dispatch_allowed':True}):
            with self.subTest(malformed=malformed):
                source.write_bytes(ev.canonical(malformed).encode())
                refused=subprocess.run(command,capture_output=True,timeout=30)
                self.assertEqual(refused.returncode,2)
                self.assertEqual(refused.stdout,b'')

    def test_expected_day_and_entity_never_use_another_observation(self):
        receipt=self.ingest(self.source(api='daily',kind='good'))
        scopes=[self.scope('daily'),self.scope('daily',date='20261102'),
                self.scope('daily',symbol='600000.SH')]
        value=self.coverage(scopes,receipt['head_hash'])
        self.assertEqual(value['counts'],{'expected':3,'observed':1,'valid':1,'missing':2})
        self.assertEqual(value['status'],'DATA_BLOCKED')
        matched=next(r for r in value['scopes'] if r['gap_id']==ev.sealed(scopes[0]))
        self.assertEqual(matched['status'],'VALID_SCOPE_OBSERVED')
        self.assertEqual(value['outside_expected_scope_count'],0)

    def test_expectation_field_order_uses_existing_endpoint_canonicalization(self):
        receipt=self.ingest(self.source(kind='good'))
        scope={**self.scope(),'fields':'ts_code,trade_date,net_amount'}
        value=self.coverage([scope],receipt['head_hash'])
        self.assertEqual(value['status'],'OBSERVED_SCOPE_VALID')
        self.assertEqual(value['scopes'][0]['fields'],'net_amount,trade_date,ts_code')

    def test_expectation_input_is_held_across_observation_reopen(self):
        m=self.module(); scopes=[self.scope()]; original=m.view
        def mutate(*args,**kwargs):
            scopes[0]['ts_code']='600000.SH'
            return original(*args,**kwargs)
        with patch.object(m,'view',side_effect=mutate):
            value=self.coverage(scopes)
        self.assertEqual(value['scopes'][0]['ts_code'],'603629.SH')

    def test_coverage_recovers_exact_scope_and_preserves_original_failure(self):
        failed=self.ingest(self.source())
        good=self.ingest(self.source(kind='good',stamp='2026-11-09T18:30:00+00:00'),failed['head_hash'])
        value=self.coverage([self.scope()],good['head_hash'])
        self.assertEqual(value['status'],'OBSERVED_SCOPE_VALID')
        self.assertEqual(value['counts'],{'expected':1,'observed':1,'valid':1,'missing':0})
        self.assertEqual(value['scopes'][0]['status'],'RECOVERED_SCOPE_OBSERVED')
        self.assertEqual(len(value['scopes'][0]['history']),2)
        self.assertEqual(value['rights'],'UNVERIFIED')

    def test_coverage_pin_is_independent_and_precedes_observation_read(self):
        m=self.module(); self.assertTrue(callable(getattr(m,'coverage',None)))
        with patch.object(m,'view') as observed:
            with self.assertRaisesRegex(ValueError,'GAPS_EXPECTATION_PIN_MISMATCH'):
                self.coverage([self.scope()],pin='f'*64)
            observed.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_coverage_refuses_empty_duplicate_invalid_or_authority_expanded_scopes(self):
        good=self.scope()
        for scopes in ([],[good,good],[good,{**good,'fields':'ts_code,trade_date,net_amount'}],[{**good,'trade_date':'20260230'}],
                       [{**good,'ts_code':'anything'}],[{**good,'api_name':'income'}],
                       [{**good,'fields':'ts_code,trade_date,net_amount,net_amount'}],
                       [{**good,'dispatch_allowed':True}], [good]*65):
            with self.subTest(scopes=str(scopes)[:160]):
                with self.assertRaisesRegex(ValueError,'GAPS_EXPECTATION'):
                    self.coverage(scopes)

    def test_retained_ledger_semantics_reopen_without_writes_or_data_promotion(self):
        m=self.module()
        self.assertTrue(callable(getattr(m,'verify_retained',None)),
                        'preservation has no existing gap-ledger semantic reopen API')
        receipt=self.ingest(self.source())
        before={p.relative_to(self.ledger).as_posix():p.read_bytes() for p in self.ledger.rglob('*') if p.is_file()}
        result=m.verify_retained(self.ledger)
        self.assertEqual(result['head_hash'],receipt['head_hash'])
        self.assertEqual(result['event_count'],1)
        self.assertEqual(result['logical_call_count'],1)
        self.assertFalse(result['automatic_retry'])
        self.assertEqual(result['research_readiness'],'NOT_EVALUATED')
        self.assertEqual(before,{p.relative_to(self.ledger).as_posix():p.read_bytes() for p in self.ledger.rglob('*') if p.is_file()})
        next((self.ledger/'sources').rglob('terminal.json')).write_bytes(b'{}')
        with self.assertRaises(ValueError): m.verify_retained(self.ledger)

    def test_empty_directory_is_not_a_retained_gap_ledger(self):
        m=self.module(); self.assertTrue(callable(getattr(m,'verify_retained',None)))
        with self.assertRaisesRegex(ValueError,'GAPS_RETAINED_HISTORY_REQUIRED'):
            m.verify_retained(self.ledger)
        self.assertFalse(self.ledger.exists())

    def test_wrong_external_source_pin_precedes_any_ledger_creation(self):
        m=self.module(); source=self.source()
        with self.assertRaisesRegex(ValueError,'GAPS_EVIDENCE_PIN'):
            m.ingest(self.ledger,source,expected_evidence_hash='0'*64,expected_head='0'*64)
        self.assertFalse(self.ledger.exists())

    def test_failure_is_persistent_and_recheck_is_only_a_bounded_proposal(self):
        source=self.source(); before={str(p):p.read_bytes() for p in source.rglob('*.json')}
        receipt=self.ingest(source); value=self.view(receipt['head_hash'])
        row=value['scopes'][0]
        self.assertEqual(row['status'],'DATA_BLOCKED')
        self.assertEqual(row['next_eligible_at'],'2026-11-09T18:15:00Z')
        self.assertEqual(row['recheck_status'],'PROPOSED_HUMAN_REVIEW_ONLY')
        self.assertEqual(row['attempts_seen'],1)
        self.assertFalse(row['dispatch_allowed']); self.assertFalse(value['automatic_retry'])
        self.assertEqual(value['research_readiness'],'NOT_EVALUATED')
        self.assertEqual(before,{str(p):p.read_bytes() for p in source.rglob('*.json')})

    def test_same_scope_later_valid_observation_recovers_without_erasing_failure(self):
        failed=self.source(); a=self.ingest(failed)
        good=self.source(kind='good',stamp='2026-11-09T18:30:00+00:00')
        b=self.ingest(good,a['head_hash']); row=self.view(b['head_hash'])['scopes'][0]
        self.assertEqual(row['status'],'RECOVERED_SCOPE_OBSERVED')
        self.assertEqual(row['attempts_seen'],2)
        self.assertEqual([x['dataset_quality'] for x in row['history']],['NOT_ASSESSED','OBSERVED_SCOPE_VALID'])
        self.assertEqual(row['rights'],'UNVERIFIED')

    def test_new_day_or_other_entity_cannot_close_the_old_gap(self):
        a=self.ingest(self.source())
        b=self.ingest(self.source(date='20261102',kind='good'),a['head_hash'])
        c=self.ingest(self.source(symbol='600000.SH',kind='good'),b['head_hash'])
        rows=self.view(c['head_hash'])['scopes']
        old=next(r for r in rows if r['ts_code']=='603629.SH' and r['trade_date']=='20261030')
        self.assertEqual(old['status'],'DATA_BLOCKED'); self.assertEqual(len(rows),3)

    def test_head_cas_and_duplicate_call_are_not_silent_replays(self):
        m=self.module(); source=self.source(); a=self.ingest(source)
        duplicate=self.ingest(source,a['head_hash'])
        self.assertEqual(duplicate['head_hash'],a['head_hash'])
        self.assertEqual(duplicate['disposition'],'IDEMPOTENT')
        with self.assertRaisesRegex(ValueError,'GAPS_HEAD_CONFLICT'):
            self.ingest(self.source(kind='good'), '0'*64)
        with self.assertRaisesRegex(ValueError,'GAPS_HEAD_CONFLICT'):
            self.view('0'*64)

    def test_frozen_source_tampering_fails_cold_reopen(self):
        source=self.source(); a=self.ingest(source)
        file=next((self.ledger/'sources').rglob('terminal.json'))
        file.write_bytes(file.read_bytes()+b' ')
        with self.assertRaises(ValueError): self.view(a['head_hash'])

    def test_permission_empty_and_interrupted_remain_distinct(self):
        for kind,expected in [('permission','BLOCKED_PERMISSION'),('empty','PROPOSED_HUMAN_REVIEW_ONLY'),
                              ('interrupted','BLOCKED_RECONCILIATION')]:
            self.ledger=self.root/('ledger-'+kind)
            source=self.source(kind='good' if kind=='interrupted' else kind)
            if kind=='interrupted': next(source.rglob('terminal.json')).unlink()
            a=self.ingest(source); row=self.view(a['head_hash'])['scopes'][0]
            self.assertEqual(row['recheck_status'],expected)
            self.assertFalse(row['dispatch_allowed'])
            if kind=='interrupted': self.assertIsNone(row['next_eligible_at'])

    def test_two_failed_observations_exhaust_proposals_but_keep_both(self):
        a=self.ingest(self.source())
        b=self.ingest(self.source(stamp='2026-11-09T18:30:00+00:00'),a['head_hash'])
        row=self.view(b['head_hash'])['scopes'][0]
        self.assertEqual(row['recheck_status'],'EXHAUSTED')
        self.assertEqual(len(row['history']),2)

    def test_equal_time_contradiction_and_late_older_receipt_never_overwrite_newer_data(self):
        a=self.ingest(self.source())
        b=self.ingest(self.source(kind='good'),a['head_hash'])
        self.assertEqual(self.view(b['head_hash'])['scopes'][0]['status'],'CONFLICTING_TIME_EVIDENCE')
        self.ledger=self.root/'chronology-ledger'
        a=self.ingest(self.source(kind='good',stamp='2026-11-09T19:00:00+00:00'))
        b=self.ingest(self.source(stamp='2026-11-09T18:00:00+00:00'),a['head_hash'])
        self.assertEqual(self.view(b['head_hash'])['scopes'][0]['status'],'RECOVERED_SCOPE_OBSERVED')

    def test_later_ingestion_is_not_knowledge_available_in_an_earlier_view(self):
        m=self.module()
        with patch.object(m,'datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,11,10,tzinfo=timezone.utc)
            a=self.ingest(self.source(kind='good'))
        # After provider observation but before local ingestion: isolate this guard.
        value=self.module().view(self.ledger,expected_head=a['head_hash'],observed_at='2026-11-09T18:01:00Z')
        self.assertEqual(value['scopes'],[])
        self.assertFalse(value['prospective_sample_eligible'])

    def test_directory_inventory_is_bounded_even_for_empty_directories(self):
        source=self.source()
        for index in range(513): (source/('empty-'+str(index))).mkdir()
        with self.assertRaisesRegex(ValueError,'GAPS_EVIDENCE_LIMIT'): self.module().evidence(source)

    def test_event_tamper_and_truncation_refuse_external_head(self):
        a=self.ingest(self.source()); event=next((self.ledger/'events').iterdir())
        original=event.read_bytes(); value=json.loads(original); value['production_authority']=True
        event.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'GAPS_CHAIN_INVALID'): self.view(a['head_hash'])
        event.write_bytes(original); event.unlink()
        with self.assertRaisesRegex(ValueError,'GAPS_HEAD_CONFLICT'): self.view(a['head_hash'])

    def test_symlink_and_overlapping_roots_refuse_before_writing(self):
        m=self.module(); source=self.source(); pin=m.evidence(source)['evidence_hash']
        alias=self.root/'alias'; alias.symlink_to(source,target_is_directory=True)
        with self.assertRaises(ValueError): m.evidence(alias)
        with self.assertRaisesRegex(ValueError,'GAPS_ROOT_OVERLAP'):
            m.ingest(source/'child',source,expected_evidence_hash=pin,expected_head='0'*64)
        self.assertFalse((source/'child').exists())

    def test_view_reopen_is_read_only_and_wrong_scope_fields_rejected(self):
        source=self.source(); a=self.ingest(source)
        before={p.relative_to(self.ledger).as_posix():p.read_bytes() for p in self.ledger.rglob('*') if p.is_file()}
        self.view(a['head_hash'])
        self.assertEqual(before,{p.relative_to(self.ledger).as_posix():p.read_bytes() for p in self.ledger.rglob('*') if p.is_file()})
        extra=self.root/'other-fields'
        session=EndpointSession(extra,collector_run_id='extra-field-call',target_trade_date='20261030')
        session.observe('moneyflow_dc',{'ts_code':'603629.SH','trade_date':'20261030'},'ts_code,trade_date,net_amount,buy_sm_amount',
            lambda:{'code':0,'data':{'fields':['ts_code','trade_date','net_amount','buy_sm_amount'],
                                   'items':[['603629.SH','20261030',1.0,2.0]]}})
        with self.assertRaisesRegex(ValueError,'GAPS_OUT_OF_SCOPE'): self.module().evidence(extra)

    def test_busy_lock_and_nonprivate_root_refuse(self):
        import fcntl
        a=self.ingest(self.source()); other=self.source(kind='good')
        with (self.ledger/'ledger.lock').open('rb') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError,'GAPS_LEDGER_BUSY'): self.ingest(other,a['head_hash'])
        os.chmod(self.ledger,0o755)
        with self.assertRaisesRegex(ValueError,'GAPS_PRIVATE_ROOT_REQUIRED'): self.view(a['head_hash'])

    def test_equal_time_different_successful_response_bytes_are_conflicting(self):
        a=self.ingest(self.source(kind='good',number=2.5))
        b=self.ingest(self.source(kind='good',number=99.0),a['head_hash'])
        row=self.view(b['head_hash'])['scopes'][0]
        self.assertEqual(row['status'],'CONFLICTING_TIME_EVIDENCE')
        self.assertEqual(row['recheck_status'],'BLOCKED_RECONCILIATION')
        self.assertIsNone(row['next_eligible_at']); self.assertFalse(row['dispatch_allowed'])

    def test_equal_time_identical_successes_do_not_false_block(self):
        a=self.ingest(self.source(kind='good'))
        b=self.ingest(self.source(kind='good'),a['head_hash'])
        self.assertEqual(self.view(b['head_hash'])['scopes'][0]['status'],'VALID_SCOPE_OBSERVED')

    def test_preexisting_private_directory_does_not_bypass_repository_guard(self):
        repository=self.root/'fixture-repository'; (repository/'.git').mkdir(parents=True)
        self.ledger=repository/'empty-ledger'; self.ledger.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError,'GAPS_ROOT_INSIDE_REPOSITORY'): self.ingest(self.source())
        self.assertEqual(list(self.ledger.iterdir()),[])


if __name__=='__main__': unittest.main()
