"""Scoped derivative review is not raw-source distribution or research approval."""
import copy
import csv
import importlib.util
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts/llm'),str(ROOT/'tests'),str(ROOT)]
import workbench_evidence as ev
import nonprod_workbench as wb
from workbench_workspace import Workspace,WorkspaceError


def packet(root):
    root.mkdir()
    provenance={'packet_id':'review-synthetic-20261110','source_cutoff_at':'2026-10-04T23:59:59+08:00',
        'daily_source_trade_date':'20261105','source_draft_generated_at':'2026-11-10T01:48:09+08:00',
        'source_producer':'a'*40,'pack_hash':'1'*64,'content_hash':'2'*64,'basis_hash':'3'*64,
        'source_materials':[{'id':'M1','title':'Synthetic issuer report','path':'/PRIVATE/NEVER/EXPOSE',
            'sha256':'4'*64,'pages':[6], 'published_at':'2026-08-19T23:59:59+08:00',
            'captured_at':'2026-10-04T15:11:40+00:00',
            'registered_public_url':'https://static.cninfo.com.cn/finalpage/2026-08-19/123.PDF',
            'rights':{'status':'UNVERIFIED','visibility':'PRIVATE','sharing_allowed':False,'model_use_allowed':False}}],
        'rules':[{'id':'R01','title':'Missing EPS','status':'DATA_BLOCKED','reason':'No normal assumptions.'}],
        'human_review':'PENDING','sample_purpose':'WORKFLOW_DEBUG','sent_to_reed':False}
    texts={'RESEARCH_SAMPLE.md':'# Synthetic F/C/R/L sample\nNot human verified; EPS missing.',
        'PROVENANCE.json':ev.canonical(provenance)}
    rows=io.StringIO();writer=csv.writer(rows);writer.writerow(['编号','归因层','核对事项','提示','状态'])
    writer.writerow(['F01','F','Source period','Check the column','PENDING']);texts['REVIEW_ROWS.csv']=rows.getvalue()
    for name,value in texts.items():(root/name).write_text(value)
    manifest={'schema':'ar.reed-review-delivery.v1','packet_id':provenance['packet_id'],
        'files':{n:ev.sha(v.encode()) for n,v in texts.items()},'human_review':'PENDING',
        'sample_purpose':'WORKFLOW_DEBUG','source_cutoff_at':provenance['source_cutoff_at'],
        'source_authenticity':'UNVERIFIED','sent_to_reed':False,'u4_authority':False,
        'paper_authority':False,'production_authority':False,'trading_authority':False}
    raw=ev.canonical(manifest).encode();(root/'MANIFEST.json').write_bytes(raw)
    return ev.sha(raw)


class ReviewPortalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=wb.Store(self.root/'state',shared_v1=True)
        self.system=Workspace(self.store,private_mode=True,clock=lambda:1000)
        self.ids={'owner@example.com':{'login':'owner@example.com','workspace_id':'00000000-0000-4000-8000-000000000001'},
                  'member@example.com':{'login':'member@example.com','workspace_id':'00000000-0000-4000-8000-000000000002'}}
        with self.store.connect() as db:
            db.executemany('INSERT INTO shared_workspaces VALUES (?, ?)',[(key,value['workspace_id']) for key,value in self.ids.items()])
        self.view=SimpleNamespace(store=self.store,system=self.system,review_enabled=True,
            identity=lambda actor:self.ids[actor],_execution_identity={'code_sha':'b'*40,'source_tree_hash':'c'*64})
        self.packet=self.root/'packet';self.pin=packet(self.packet)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('workbench_review_portal'),'review portal not implemented')
        import workbench_review_portal
        return workbench_review_portal

    def admitted(self):
        m=self.module();grant=m.make_grant(self.pin,sorted(self.ids),'Junyan synthetic test approval')
        result=m.register(self.view,self.packet,self.pin,grant,ev.sealed(grant))
        return m.ReviewPortal(self.view),result

    def command(self,record,**overrides):
        return {'command_id':'review-test-command','packet_hash':record['packet_hash'],'item_id':'F01',
            'expected_workspace_id':self.ids['member@example.com']['workspace_id'],'expected_code_sha':'b'*40,
            'status':'NEEDS_SOURCE','severity':'MAJOR','comment':'Please verify the period and column.',**overrides}

    def test_wrong_pin_refuses_before_review_files_or_events(self):
        m=self.module();grant=m.make_grant('0'*64,sorted(self.ids),'Synthetic approval')
        with self.assertRaises(ValueError):m.register(self.view,self.packet,'0'*64,grant,ev.sealed(grant))
        self.assertFalse((self.store.path.parent/'review-packets').exists())

    def test_audience_grant_is_independently_pinned_and_raw_sources_denied(self):
        m=self.module();grant=m.make_grant(self.pin,sorted(self.ids),'Synthetic approval')
        with self.assertRaises(ValueError):m.register(self.view,self.packet,self.pin,grant,'0'*64)
        portal,record=self.admitted();result=portal.detail(record['packet_hash'],'member@example.com')
        self.assertIn('Synthetic F/C/R/L',result['packet']['sample'])
        self.assertNotIn('/PRIVATE/NEVER',ev.canonical(result))
        self.assertFalse(result['raw_source_body_allowed']);self.assertEqual(result['human_review'],'PENDING')
        self.assertFalse(result['paper_authority']);self.assertFalse(result['production_authority'])
        with self.assertRaises(WorkspaceError) as denied:portal.detail(record['packet_hash'],'outsider@example.com')
        self.assertEqual(denied.exception.code,'REVIEW_AUDIENCE_DENIED')

    def test_packet_or_grant_tamper_cannot_self_reseal(self):
        portal,record=self.admitted();path=self.store.path.parent/'review-packets'/record['packet_hash']/'packet.json'
        old=path.read_bytes();value=json.loads(old);value['sample']='FORGED';path.write_text(ev.canonical(value))
        with self.assertRaises(WorkspaceError):portal.detail(record['packet_hash'],'member@example.com')
        path.write_bytes(old)
        grant=path.parent/'grant.json';value=json.loads(grant.read_bytes());value['audience'].append('outsider@example.com');grant.write_text(ev.canonical(value))
        with self.assertRaises(WorkspaceError):portal.detail(record['packet_hash'],'member@example.com')

    def test_comment_actor_context_retry_and_append_only(self):
        portal,record=self.admitted();command=self.command(record)
        first=portal.submit(command,'member@example.com');again=portal.submit(command,'member@example.com')
        self.assertEqual(first['annotation'],again['annotation']);self.assertEqual(again['disposition'],'IDEMPOTENT')
        self.assertEqual(first['annotation']['actor'],'member@example.com')
        self.assertEqual(first['annotation']['code_sha'],'b'*40)
        with self.assertRaises(WorkspaceError):portal.submit(self.command(record,comment='CHANGED'),'member@example.com')
        with self.assertRaises(WorkspaceError):portal.submit(command,'owner@example.com')
        with self.assertRaises(WorkspaceError):portal.submit(self.command(record,command_id='fresh-wrong-workspace',expected_workspace_id='WRONG'),'member@example.com')
        with self.assertRaises(WorkspaceError):portal.submit(self.command(record,command_id='fresh-wrong-code',expected_code_sha='d'*40),'member@example.com')
        with self.assertRaises(WorkspaceError):portal.submit(self.command(record,actor='owner@example.com'),'member@example.com')
        portal.submit(self.command(record,command_id='review-correction',comment='New correction retains old comment.'),'member@example.com')
        result=portal.detail(record['packet_hash'],'owner@example.com')
        self.assertEqual(len(result['annotations']),2)
        self.assertEqual(result['annotations'][0]['comment'],command['comment'])

    def test_invalid_status_size_item_and_source_url_refused(self):
        portal,record=self.admitted()
        for change in ({'status':'PASS'},{'comment':'x'*4001},{'item_id':'../source'},{'severity':'APPROVED'}):
            with self.assertRaises(WorkspaceError):portal.submit(self.command(record,**change),'member@example.com')
        m=self.module();p=json.loads((self.packet/'PROVENANCE.json').read_text())
        p['source_materials'][0]['registered_public_url']='javascript:alert(1)'
        raw=ev.canonical(p).encode();(self.packet/'PROVENANCE.json').write_bytes(raw)
        mf=json.loads((self.packet/'MANIFEST.json').read_text());mf['files']['PROVENANCE.json']=ev.sha(raw)
        raw=ev.canonical(mf).encode();(self.packet/'MANIFEST.json').write_bytes(raw);pin=ev.sha(raw)
        grant=m.make_grant(pin,sorted(self.ids),'Synthetic approval')
        with self.assertRaises(ValueError):m.register(self.view,self.packet,pin,grant,ev.sealed(grant))

    def test_default_off_and_cold_restore_bindings(self):
        portal,record=self.admitted();portal.submit(self.command(record),'member@example.com')
        expected=portal.detail(record['packet_hash'],'owner@example.com')
        self.view.review_enabled=False
        with self.assertRaises(WorkspaceError):portal.detail(record['packet_hash'],'owner@example.com')
        self.view.review_enabled=True
        import workbench_backup as backup
        saved=backup.backup_shared(self.store,self.root/'backup')
        backup.restore_shared(self.root/'backup',self.root/'cold')
        cold=wb.Store(self.root/'cold',shared_v1=True);system=Workspace(cold,private_mode=True)
        view=SimpleNamespace(store=cold,system=system,identity=self.view.identity,review_enabled=True,_execution_identity=self.view._execution_identity)
        actual=self.module().ReviewPortal(view).detail(record['packet_hash'],'owner@example.com')
        self.assertEqual(actual,expected)
        self.assertEqual(len(saved['backup_hash']),64)

    def test_self_rehashed_annotation_still_needs_actor_workspace_and_request_binding(self):
        portal,record=self.admitted();portal.submit(self.command(record),'member@example.com')
        with self.store.connect() as db:events=self.system.events(db)
        for field,value in [('workspace_id',self.ids['owner@example.com']['workspace_id']),('research_approval',True),('comment','silently changed')]:
            altered=copy.deepcopy(events);altered[-1]['data'][field]=value
            with self.assertRaises(ValueError):self.module().verify_retained(self.store.path.parent,altered,{k:v['workspace_id'] for k,v in self.ids.items()})

    def test_comment_credential_and_duplicate_content_length_refused(self):
        from workbench_shared_test_support import http
        portal,record=self.admitted();self.view.review_portal=portal
        with self.assertRaises(WorkspaceError):portal.submit(self.command(record,comment='Authorization: Bearer example-secret-value'),'member@example.com')
        allow=self.root/'allow.json';allow.write_text(json.dumps({'members':['member@example.com']}));allow.chmod(0o600)
        private=wb.private_access('https://workbench.test-tail.ts.net:8443','owner@example.com',allow)
        code,_=http(self.store,self.system,private,'/api/shared-workspace/review-comment',self.command(record),login='member@example.com',extra=(('Content-Length','2'),),shared=self.view)
        self.assertEqual(code,403)

    def test_actual_client_contract_and_callback_regressions(self):
        result=subprocess.run(['node','--test','tests/nonprod-review-portal.test.mjs','tests/nonprod-review-portal-component.test.mjs'],cwd=ROOT,capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_http_review_routes_keep_private_auth_and_old_operation_denials(self):
        from workbench_shared_test_support import http
        portal,record=self.admitted();self.view.review_portal=portal
        allow=self.root/'allow.json';allow.write_text(json.dumps({'members':['member@example.com']}));allow.chmod(0o600)
        private=wb.private_access('https://workbench.test-tail.ts.net:8443','owner@example.com',allow)
        code,_=http(self.store,self.system,private,'/api/shared-workspace/reviews',login='member@example.com',shared=self.view)
        self.assertEqual(code,200)
        code,result=http(self.store,self.system,private,'/api/shared-workspace/review/'+record['packet_hash'],login='member@example.com',shared=self.view)
        self.assertEqual(code,200);self.assertEqual(result['packet_hash'],record['packet_hash'])
        code,result=http(self.store,self.system,private,'/api/shared-workspace/review-comment',self.command(record),login='member@example.com',shared=self.view)
        self.assertEqual(code,200);self.assertEqual(result['annotation']['actor'],'member@example.com')
        for path in ('/api/workspace/review','/api/workspace/draft','/api/shared-workspace/review-comment/extra'):
            code,_=http(self.store,self.system,private,path,{},login='member@example.com',shared=self.view)
            self.assertEqual(code,403)
        code,_=http(self.store,self.system,private,'/api/shared-workspace/reviews',login='outsider@example.com',shared=self.view)
        self.assertEqual(code,403)
        code,_=http(self.store,self.system,private,'/api/shared-workspace/review-comment',self.command(record),login='member@example.com',extra=(('Origin','https://other.invalid'),),shared=self.view)
        self.assertEqual(code,403)
        self.view.review_enabled=False
        code,_=http(self.store,self.system,private,'/api/shared-workspace/review-comment',self.command(record),login='member@example.com',shared=self.view)
        self.assertEqual(code,403)


if __name__=='__main__':unittest.main(verbosity=2)
