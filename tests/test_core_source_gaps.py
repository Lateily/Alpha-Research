"""Exact-scope gap history from actual offline EndpointSession receipts."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
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
               stamp='2026-11-09T18:00:00+00:00'):
        self.serial+=1; root=self.root/('source-'+str(self.serial))
        clock=lambda:datetime.fromisoformat(stamp)
        session=EndpointSession(root,collector_run_id='gap-fixture-'+str(self.serial),target_trade_date=date,clock=clock)
        fields=['ts_code','trade_date','net_amount' if api=='moneyflow_dc' else 'close']
        def invoke():
            if kind=='down': raise OSError('PRIVATE_PROVIDER_ERROR')
            if kind=='permission': raise PermissionError('PRIVATE_PERMISSION_MESSAGE')
            return {'code':0,'data':{'fields':fields,'items':[] if kind=='empty' else [[symbol,date,2.5]]}}
        try: session.observe(api,{'ts_code':symbol,'trade_date':date},','.join(fields),invoke)
        except EndpointObservationError: pass
        return root

    def ingest(self,source,head=None):
        m=self.module(); pin=m.evidence(source)['evidence_hash']
        return m.ingest(self.ledger,source,expected_evidence_hash=pin,expected_head=head or '0'*64)

    def view(self,head):
        return self.module().view(self.ledger,expected_head=head,observed_at='2099-01-01T00:00:00Z')

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


if __name__=='__main__': unittest.main()
