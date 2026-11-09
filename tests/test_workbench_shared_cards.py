"""New card tasks keep real producer verification, honest gaps and denied bodies."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts/llm'),str(ROOT/'tests'),str(ROOT)]
import workbench_evidence as ev
import test_research_content as content_tests

class SharedCardTests(unittest.TestCase):
    def setUp(self):
        self.fixture=content_tests.ResearchContentTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root
        import research_content as content
        import research_basis_evidence as basis
        from test_research_normalization import fixture
        self.content=self.root/'content'
        with patch.object(content,'_observed_at',return_value=self.fixture.draft['generated_at']):
            self.content_receipt=content.create(self.fixture.draft,self.root/'pack',
                self.fixture.pack['pack_hash'],self.content)
        _,normal=fixture(); normal['company']='600000.SH'
        self.worksheet={'schema':'ar.research-basis-worksheet.v1','company':'600000.SH',
            'normalization_worksheet':normal,'dilution':[],'tax':[],'rd':[],
            'cash':None,'notes':[],'daily':None,
            'multiple':{key:{'value':None,'unit':'PCT','rationale':'Not established.',
                'fact_ids':[]} for key in ['discount_pct','growth_pct','payout_pct']}}
        raw=ev.canonical(self.worksheet).encode(); self.basis=self.root/'basis'
        self.basis_receipt=basis.create(raw,ev.sha(raw),self.content,self.content_receipt['content_hash'],
            self.root/'pack',self.fixture.pack['pack_hash'],self.basis)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('workbench_shared_cards'),'shared cards not implemented')
        import workbench_shared_cards
        return workbench_shared_cards

    def snapshot(self,**overrides):
        return self.module().snapshot(self.fixture.fixture.library,self.root/'pack',self.content,self.basis,
            **({'expected_library_hash':self.fixture.request['expected_library_hash'],
                'expected_pack_hash':self.fixture.pack['pack_hash'],
                'expected_content_hash':self.content_receipt['content_hash'],
                'expected_basis_hash':self.basis_receipt['basis_hash']}|overrides))

    def test_wrong_external_content_pin_refuses(self):
        with self.assertRaises(ValueError): self.snapshot(expected_content_hash='0'*64)

    def test_distinct_envelope_and_original_producer_identity(self):
        value=self.snapshot(); entry=self.module().envelope(value)
        self.assertEqual(entry['schema'],'ar.shared-research-card-input.v1')
        self.assertIsNone(entry['source_run_id']); self.assertIsNone(entry['source_trade_date'])
        self.assertEqual(value['company'],'600000.SH')
        self.assertEqual(value['content_hash'],self.content_receipt['content_hash'])

    def test_frozen_content_and_basis_tampering_is_refused(self):
        m=self.module(); value=self.snapshot(); frozen=self.root/'frozen'
        m.copy_input(self.fixture.fixture.library,self.root/'pack',self.content,self.basis,frozen,value)
        m.verify_input(frozen,value)
        (frozen/'basis/basis-card.json').write_bytes(b'{}')
        with self.assertRaises(ValueError): m.verify_input(frozen,value)

    def test_card_archive_reopen_metadata_only_and_missing_not_zero(self):
        m=self.module(); value=self.snapshot(); frozen=self.root/'frozen'
        m.copy_input(self.fixture.fixture.library,self.root/'pack',self.content,self.basis,frozen,value)
        output=self.root/'output'; m.render(frozen,output,value)
        detail=m.detail(output,value,frozen)
        self.assertFalse(detail['content_sharing_allowed'])
        self.assertEqual(detail['human_review'],'PENDING')
        self.assertEqual(detail['cards']['valuation']['normalized_eps_status'],'NOT_ESTABLISHED')
        self.assertEqual(detail['cards']['daily']['status'],'DATA_BLOCKED')
        self.assertNotIn('Cash receipts',ev.canonical(detail))
        self.assertNotIn('Cash flow was 20 CNY.',ev.canonical(detail))
        self.assertNotIn('"observations":',ev.canonical(detail))
        for name in ['report','worksheet','observations','responses']:
            self.assertNotIn(name,detail)
        (output/'archive.json').write_text('{}')
        with self.assertRaises(ValueError): m.verify_output(output,value)

    def test_resealed_changed_card_output_cannot_replace_frozen_projection(self):
        m=self.module(); value=self.snapshot(); frozen=self.root/'frozen'
        m.copy_input(self.fixture.fixture.library,self.root/'pack',self.content,self.basis,frozen,value)
        output=self.root/'output'; m.render(frozen,output,value)
        review=ev.parse((output/'review.json').read_bytes())
        review['cards']['valuation']['normalized_eps_status']='FAKE_READY'
        raw=ev.canonical(review).encode(); (output/'review.json').write_bytes(raw)
        archive=ev.parse((output/'archive.json').read_bytes())
        archive['files']['review.json']=archive['result_hash']=ev.sha(raw)
        archive['archive_hash']=ev.sealed({k:v for k,v in archive.items() if k!='archive_hash'})
        (output/'archive.json').write_text(ev.canonical(archive))
        with self.assertRaises(ValueError): m.verify_output(output,value)

    def test_source_change_after_copy_is_not_adopted_as_registration_success(self):
        m=self.module(); value=self.snapshot(); original=m._copy
        def change(source,target,inventory):
            original(source,target,inventory)
            if Path(source)==self.basis: (self.basis/'report.md').write_bytes(b'CHANGED_AFTER_COPY')
        with patch.object(m,'_copy',side_effect=change):
            with self.assertRaises(ValueError):
                m.copy_input(self.fixture.fixture.library,self.root/'pack',self.content,self.basis,self.root/'frozen',value)

    def queue(self,enabled=True):
        import inspect
        import nonprod_workbench as wb
        import workbench_workspace as ws
        import workbench_shared_workspace as shared
        from workbench_shared_test_support import committed_code
        from workbench_shared_inputs import FrozenInputs
        from workbench_shared_jobs import SharedJobQueue
        self.assertIn('cards_enabled',inspect.signature(shared.SharedWorkspace).parameters)
        code=self.root/'committed-code'; committed_code(code,shared.EXECUTION_FILES)
        change=patch.object(shared,'CODE_ROOT',code); change.start(); self.addCleanup(change.stop)
        store=wb.Store(self.root/'state',shared_v1=True)
        view=shared.SharedWorkspace(ws.Workspace(store,private_mode=True),cards_enabled=enabled)
        inputs=FrozenInputs(store)
        self.assertTrue(hasattr(self.module(),'register'),'operator card registration missing')
        entry=self.module().register(inputs,self.fixture.fixture.library,self.root/'pack',self.content,self.basis,
            expected_library_hash=self.fixture.request['expected_library_hash'],
            expected_pack_hash=self.fixture.pack['pack_hash'],expected_content_hash=self.content_receipt['content_hash'],
            expected_basis_hash=self.basis_receipt['basis_hash'])
        queue=SharedJobQueue(view,inputs,view._execution_identity['code_sha'])
        payload={'command_id':'card-test-command','kind':'research-cards-review','snapshot_id':entry['snapshot_id'],
            'expected_workspace_id':view.identity('owner@example.com')['workspace_id'],
            'expected_code_sha':queue.code_sha}
        return queue,view,entry,payload

    def test_kind_context_and_default_off_are_enforced(self):
        from workbench_workspace import WorkspaceError
        queue,view,entry,payload=self.queue(False)
        with self.assertRaises(WorkspaceError): queue.enqueue(payload,'owner@example.com')
        with self.assertRaises(WorkspaceError): queue.inputs.select_current(entry['snapshot_id'])

    def test_queued_card_task_seal_query_and_cold_restore(self):
        import workbench_shared_worker as worker
        queue,view,entry,payload=self.queue()
        job=queue.enqueue(payload,'owner@example.com')
        self.assertEqual(queue.enqueue(payload,'owner@example.com')['job_id'],job['job_id'])
        claim=queue.claim(); response=worker.run_attempt(claim)
        self.assertEqual(response['status'],'SUCCEEDED',response)
        queue.finish(claim,response)
        detail=view.job(job['job_id'],'member@example.com')
        self.assertEqual(detail['status'],'SUCCEEDED'); self.assertNotIn('report',detail)
        self.assertEqual(detail['research_cards']['cards']['daily']['status'],'DATA_BLOCKED')
        found=view.research_card_results('member@example.com',industry_key='UNSPECIFIED',research_date='20200106',ts_code='600000.SH')
        self.assertEqual(found['total'],1)
        self.assertEqual(view.research_card_results('member@example.com',ts_code='603986.SH')['total'],0)
        import workbench_backup as backup
        original=backup.backup_shared(queue.store,self.root/'backup')
        restored=backup.restore_shared(self.root/'backup',self.root/'cold-state')
        self.assertEqual(restored['status'],'LOCAL_SHARED_RESTORE_VERIFIED')
        self.assertTrue(original['backup_hash'])

    def test_stale_workspace_or_code_cannot_submit_registered_cards(self):
        from workbench_workspace import WorkspaceError
        queue,view,entry,payload=self.queue()
        for key,value in [('expected_code_sha','0'*40),('expected_workspace_id','0'*36)]:
            with self.assertRaises(WorkspaceError): queue.enqueue({**payload,key:value},'owner@example.com')

    def test_http_card_choices_closed_query_and_exact_submission(self):
        import nonprod_workbench as wb
        from workbench_shared_test_support import http,OWNER,MEMBER
        queue,view,entry,payload=self.queue()
        allow=self.root/'members.json'; allow.write_text(ev.canonical({'members':[MEMBER]})); allow.chmod(0o600)
        private=wb.private_access('https://workbench.test-tail.ts.net:8443',OWNER,allow)
        status,data=http(queue.store,view.system,private,'/api/shared-workspace/research-card-inputs',shared=view)
        self.assertEqual(status,200); self.assertEqual(data['inputs'][0]['input_hash'],entry['input_hash'])
        status,data=http(queue.store,view.system,private,'/api/shared-workspace/research-card-library?ts_code=600000.SH',shared=view)
        self.assertEqual(status,200); self.assertEqual(data['total'],0)
        for query in ['?ts_code=600000.SH&ts_code=603986.SH','?path=/private/tmp','?page=-1','?research_date=20261340']:
            status,_=http(queue.store,view.system,private,'/api/shared-workspace/research-card-library'+query,shared=view)
            self.assertEqual(status,400)
        status,data=http(queue.store,view.system,private,'/api/workspace/job',body=payload,shared=view)
        self.assertEqual(status,202)
        status,_=http(queue.store,view.system,private,'/api/workspace/job',body={**payload,'path':'/private/tmp'},shared=view)
        self.assertEqual(status,400)

    def test_recovery_card_optin_is_explicit_versioned_and_cold_verifiable(self):
        import inspect
        import test_workbench_recovery as fixtures
        fixture=fixtures.RecoveryTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        recovery=fixture.module()
        self.assertIn('cards_enabled',inspect.signature(recovery.prepare).parameters)
        made=fixture.prepare(cards_enabled=True)
        profile=ev.parse((Path(made['root'])/'profile.json').read_bytes())
        self.assertEqual(profile['schema'],'ar.isolated-recovery.v2')
        self.assertEqual(profile['features'],{'research_cards_enabled':True})
        self.assertIn('--shared-research-cards-v1',recovery.arguments(profile))
        with fixture.checks():
            self.assertEqual(recovery.verify(Path(made['root'])/'profile.json',made['profile_hash']),profile)
        legacy=fixture.prepare(root=fixture.base/'legacy-capsule')
        value=ev.parse((Path(legacy['root'])/'profile.json').read_bytes())
        self.assertEqual(value['schema'],'ar.isolated-recovery.v1'); self.assertNotIn('features',value)
        self.assertNotIn('--shared-research-cards-v1',recovery.arguments(value))
        for changed in [dict(profile,features={'research_cards_enabled':1}),
                        dict(profile,features={'research_cards_enabled':True,'production':True}),
                        dict(value,features={'research_cards_enabled':True})]:
            with self.assertRaises(ValueError): recovery._validate(changed,Path(changed['root']))

    def test_browser_card_contract(self):
        import subprocess
        value=subprocess.run(['node','--test','tests/nonprod-research-cards.test.mjs','tests/nonprod-shared-refresh-pair.test.mjs'],cwd=ROOT,
            capture_output=True,text=True,timeout=40)
        self.assertEqual(value.returncode,0,(value.stdout+value.stderr)[-5000:])

    def test_combined_input_inventory_stays_bounded(self):
        m=self.module(); self.assertTrue(hasattr(m,'_files'))
        with patch.object(m.results,'_tree',return_value={str(i)+'.json':b'{}' for i in range(513)}):
            with self.assertRaisesRegex(ValueError,'SHARED_CARDS_INPUT_LIMIT'):
                m._files({'library':self.root})

    def test_four_valid_trees_over_256_combined_files_copy_and_verify(self):
        import foundation_materials as materials
        import foundation_results as results
        import research_content as content
        import research_basis_evidence as basis
        source=self.fixture.fixture; additions=[]
        for group in range(15):
            row=copy.deepcopy(source.row); row.update(material_id='capacity-'+str(group),files=[])
            for item in range(16):
                name='capacity-'+str(group)+'-'+str(item)+'.txt'; raw=('Synthetic capacity '+name+'\n').encode()
                (source.source/name).write_bytes(raw)
                row['files'].append({'source_path':name,'sha256':ev.sha(raw),'size_bytes':len(raw)})
            additions.append(row)
        enlarged=materials.ingest_material(source.source,source.library,{
            'schema':'ar.material-intake.v1','library_id':'synthetic-library',
            'created_at':'2020-01-06T12:00:00+08:00','materials':additions},
            expected_library_hash=self.fixture.request['expected_library_hash'])
        request=copy.deepcopy(source.request); request['expected_library_hash']=enlarged['library_hash']
        pack=source.prepare(request,name='expanded-pack'); draft=copy.deepcopy(self.fixture.draft)
        draft['pack_hash']=pack['pack_hash']; proot=self.root/'expanded-pack'
        croot=self.root/'expanded-content'; broot=self.root/'expanded-basis'
        with patch.object(content,'_observed_at',return_value=draft['generated_at']):
            made=content.create(draft,proot,pack['pack_hash'],croot)
        worksheet=ev.canonical(self.worksheet).encode()
        derived=basis.create(worksheet,ev.sha(worksheet),croot,made['content_hash'],proot,pack['pack_hash'],broot)
        m=self.module(); value=m.snapshot(source.library,proot,croot,broot,expected_library_hash=enlarged['library_hash'],
            expected_pack_hash=pack['pack_hash'],expected_content_hash=made['content_hash'],expected_basis_hash=derived['basis_hash'])
        self.assertGreater(len(value['files']),256); self.assertLessEqual(len(value['files']),512)
        for path in (source.library,proot,croot,broot): self.assertLessEqual(len(results._tree(path)),256)
        target=self.root/'expanded-frozen'
        try:
            m.copy_input(source.library,proot,croot,broot,target,value)
        except ValueError as error:
            self.fail('A valid four-tree input must stay usable: '+str(error))
        self.assertEqual(m.verify_input(target,value),value)
        (target/'unexpected').mkdir()
        with self.assertRaises(ValueError): m.verify_input(target,value)

    def test_new_card_date_does_not_relabel_old_material_or_market_date(self):
        import research_content as content
        import research_basis_evidence as basis
        draft=copy.deepcopy(self.fixture.draft)
        draft.update(as_of='20200107',generated_at='2020-01-07T19:00:00+08:00')
        self.content=self.root/'content-next'; self.basis=self.root/'basis-next'
        with patch.object(content,'_observed_at',return_value=draft['generated_at']):
            self.content_receipt=content.create(draft,self.root/'pack',self.fixture.pack['pack_hash'],self.content)
        raw=ev.canonical(self.worksheet).encode()
        self.basis_receipt=basis.create(raw,ev.sha(raw),self.content,self.content_receipt['content_hash'],
            self.root/'pack',self.fixture.pack['pack_hash'],self.basis)
        value=self.snapshot()
        self.assertEqual(value['research_date'],'20200107')
        self.assertEqual(value['source_cutoff_at'],self.fixture.request['source_cutoff_at'])
        self.assertIsNone(self.module().envelope(value)['source_trade_date'])

    def test_existing_actor_read_does_not_need_an_unrelated_writer_lock(self):
        import sqlite3
        queue,view,entry,payload=self.queue()
        expected=view.identity('owner@example.com')
        blocker=queue.store.connect(); blocker.execute('BEGIN IMMEDIATE')
        try:
            with patch.object(queue.store,'connect',side_effect=lambda:sqlite3.connect(str(queue.store.path),timeout=0)):
                try:actual=view.identity('owner@example.com')
                except sqlite3.OperationalError as error:self.fail('Existing actor GET acquired a writer lock: '+str(error))
            self.assertEqual(actual,expected)
        finally:blocker.rollback(); blocker.close()

    def test_legacy_detail_reopen_contract_keeps_its_existing_call_signature(self):
        from test_workbench_shared_jobs import SharedJobTests
        result=unittest.TestResult()
        SharedJobTests('test_detail_read_rechecks_bytes_after_seal_reopen').run(result)
        self.assertEqual(result.testsRun,1);self.assertEqual(result.errors,[]);self.assertEqual(result.failures,[])

    def complete_card(self,queue,payload):
        import workbench_shared_worker as worker
        job=queue.enqueue(payload,'owner@example.com'); claim=queue.claim()
        result=worker.run_attempt(claim); self.assertEqual(result['status'],'SUCCEEDED')
        queue.finish(claim,result); return job

    def test_detail_verifies_semantics_once_per_request_and_never_caches_across_reads(self):
        queue,view,entry,payload=self.queue(); job=self.complete_card(queue,payload); m=self.module()
        with patch.object(m,'verify_input',wraps=m.verify_input) as checked:
            first=view.job(job['job_id'],'owner@example.com')
            self.assertEqual(first['status'],'SUCCEEDED'); self.assertEqual(checked.call_count,1)
            second=view.job(job['job_id'],'member@example.com')
            self.assertEqual(second['research_cards'],first['research_cards']); self.assertEqual(checked.call_count,2)

    def test_query_reuses_only_request_local_verification_for_the_same_input(self):
        queue,view,entry,payload=self.queue(); self.complete_card(queue,payload)
        self.complete_card(queue,{**payload,'command_id':'card-second-query'})
        m=self.module()
        with patch.object(m,'verify_input',wraps=m.verify_input) as checked:
            self.assertEqual(view.research_card_results('owner@example.com')['total'],2)
            self.assertEqual(checked.call_count,1)
            self.assertEqual(view.research_card_results('member@example.com')['total'],2)
            self.assertEqual(checked.call_count,2)

    def test_request_local_reuse_rejects_bytes_changed_after_semantic_check(self):
        queue,view,entry,payload=self.queue(); job=self.complete_card(queue,payload); m=self.module()
        self.assertTrue(hasattr(m,'_metadata_detail'))
        original=m._metadata_detail
        def mutate(output,value,frozen_root):
            (Path(frozen_root)/'content/report.md').write_bytes(b'CHANGED_AFTER_SEMANTIC_CHECK')
            return original(output,value,frozen_root)
        with patch.object(m,'_metadata_detail',side_effect=mutate):
            detail=view.job(job['job_id'],'owner@example.com')
        self.assertEqual(detail['status'],'RECOVERY_REQUIRED'); self.assertNotIn('research_cards',detail)
        self.assertEqual(view.job(job['job_id'],'owner@example.com')['status'],'RECOVERY_REQUIRED')

    def test_request_local_reuse_rechecks_pdf_content_basis_and_root_after_projection(self):
        queue,view,entry,payload=self.queue(); job=self.complete_card(queue,payload); m=self.module()
        root=Path(queue.inputs.verify(entry['snapshot_id'])['frozen_root'])
        pdf=next(path for path in root.rglob('*.pdf'))
        original=m._metadata_detail; project=m._projection
        for path in (pdf,root/'content/report.md',root/'basis/report.md'):
            with self.subTest(path=path.name):
                raw=path.read_bytes()
                def late(output,value,frozen_root):
                    def mutate(*args):
                        result=project(*args);path.write_bytes(b'CHANGED_AFTER_PROJECTION');return result
                    with patch.object(m,'_projection',side_effect=mutate):return original(output,value,frozen_root)
                try:
                    with patch.object(m,'_metadata_detail',side_effect=late):
                        self.assertEqual(view.job(job['job_id'],'owner@example.com')['status'],'RECOVERY_REQUIRED')
                finally:path.write_bytes(raw)
        extra=root/'unexpected'
        def late_root(output,value,frozen_root):
            def mutate(*args):
                result=project(*args);extra.mkdir();return result
            with patch.object(m,'_projection',side_effect=mutate):return original(output,value,frozen_root)
        try:
            with patch.object(m,'_metadata_detail',side_effect=late_root):
                self.assertEqual(view.job(job['job_id'],'owner@example.com')['status'],'RECOVERY_REQUIRED')
        finally:extra.rmdir()
        self.assertEqual(view.job(job['job_id'],'owner@example.com')['status'],'SUCCEEDED')

if __name__=='__main__': unittest.main()
