import assert from 'node:assert/strict';
import test from 'node:test';
import { resource, actionCurrent, cardCommand, readJob, requestReceipt, pendingStore,
  matchingReview, queryFilters, apiRequest, readSharedSnapshot } from '../tools/nonprod_workbench/live-ui/live-state.mjs';

const context={login:'owner@example.com',workspaceId:'a'.repeat(8)+'-aaaa-aaaa-aaaa-'+'a'.repeat(12),codeSha:'a'.repeat(40)};
const input={snapshot_id:'b'.repeat(8)+'-bbbb-bbbb-bbbb-'+'b'.repeat(12),input_hash:'b'.repeat(64)};
const storage=()=>{const map=new Map();return{getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)};};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};

test('each read expires at exactly fifteen seconds and future timestamps never enable actions',async()=>{
  let now=1000;const r=resource(()=>now);await r.read('x',async()=>({value:1}));
  assert.equal(r.fresh('x'),true);now=15999;assert.equal(r.fresh('x'),true);
  now=16000;assert.equal(r.fresh('x'),false);now=999;assert.equal(r.fresh('x'),false);
});
test('a fresh context cannot renew held card or detail evidence; failures retire the old timestamp',async()=>{
  let now=1000;const c=resource(()=>now),d=resource(()=>now),held=deferred();
  await c.read('actor',async()=>context);await d.read('card',async()=>({registeredInputs:{inputs:[input]}}));
  const read=d.read('card',()=>held.promise);now=16000;await c.read('actor',async()=>context);
  assert.equal(actionCurrent([[c,'actor'],[d,'card']]),false);
  held.reject(Error('SEAL_CHANGED'));await read;
  assert.equal(d.value().error,'SEAL_CHANGED');assert.equal(d.fresh('card'),false);
});
test('generation changes reject late reads and do not overlap same-resource requests',async()=>{
  const r=resource(()=>1000),a=deferred();let entered=0;
  const first=r.read('a',async()=>{entered++;return a.promise;});
  await Promise.resolve();const next=r.read('b',async()=>{entered++;return {actor:'b'};});
  assert.equal(r.fresh('a'),false);assert.equal(entered,1);
  a.resolve({actor:'a'});await first;await next;
  assert.equal(r.value().data.actor,'b');assert.equal(entered,2);assert.equal(r.fresh('a'),false);
});
test('same-key refresh is single flight; detached resources cannot deliver late results',async()=>{
  const r=resource(()=>1000),d=deferred();let calls=0;
  const a=r.read('x',()=>{calls++;return d.promise;}),b=r.read('x',()=>{calls++;return d.promise;});
  await Promise.resolve();assert.equal(calls,1);r.invalidate();d.resolve({ok:true});await a;await b;
  assert.equal(r.fresh('x'),false);assert.equal(r.value().data,null);
});
test('explicit revalidation retains visible bytes but immediately retires their action timestamp',async()=>{
  const r=resource(()=>1000);await r.read('x',async()=>({draft:'keep visible'}));
  r.invalidate(true);assert.equal(r.value().data.draft,'keep visible');assert.equal(r.fresh('x'),false);
});
test('retained submit guard refuses stale, busy or changed selection, and binds current version/workspace',async()=>{
  let now=1000;const c=resource(()=>now),r=resource(()=>now);
  await c.read('c',async()=>context);await r.read('q',async()=>({registeredInputs:{enabled:true,inputs:[input]}}));
  const make=()=>cardCommand(context,input.snapshot_id,'shared_12345678',[[c,'c'],[r,'q']],r.value().data);
  assert.deepEqual(make(),{command_id:'shared_12345678',kind:'research-cards-review',snapshot_id:input.snapshot_id,expected_workspace_id:context.workspaceId,expected_code_sha:context.codeSha});
  now=16000;assert.throws(make,/EVIDENCE_NOT_CURRENT/);
  assert.equal(actionCurrent([[c,'c']],true),false);
  now=1000;assert.throws(()=>cardCommand(context,'not-selected','shared_12345678',[[c,'c'],[r,'q']],r.value().data),/INPUT_NOT_SELECTED/);
});
test('uncertain commands persist by actor/workspace/version and cannot be replaced or silently resent',()=>{
  const s=storage(),p=pendingStore(s,context),body={command_id:'shared_12345678',kind:'research-cards-review',snapshot_id:input.snapshot_id,expected_workspace_id:context.workspaceId,expected_code_sha:context.codeSha};
  p.save(body);assert.deepEqual(p.read().body,body);
  assert.throws(()=>p.save({...body,command_id:'shared_87654321'}),/PENDING_COMMAND_EXISTS/);
  assert.equal(pendingStore(s,{...context,login:'member@example.com'}).read(),null);
  assert.equal(pendingStore(s,{...context,codeSha:'c'.repeat(40)}).read(),null);
  p.save(body,'c'.repeat(8)+'-cccc-cccc-cccc-'+'c'.repeat(12));assert.ok(p.read().job_id);p.clear();assert.equal(p.read(),null);
});
test('submission receipt rejects invented status, fields, job identity or approval',()=>{
  const good={job_id:'c'.repeat(8)+'-cccc-cccc-cccc-'+'c'.repeat(12),status:'QUEUED',disposition:'CREATED'};
  assert.deepEqual(requestReceipt(good),good);
  for(const bad of [{...good,status:'APPROVED'},{...good,job_id:'bad'},{...good,human_review:'PASS'}])assert.throws(()=>requestReceipt(bad));
});
test('completed task without closed-schema verified steps/citations/output is rejected',async()=>{
  const bad={job_id:'c'.repeat(8)+'-cccc-cccc-cccc-'+'c'.repeat(12),kind:'research-cards-review',status:'SUCCEEDED',human_review:'PENDING',production_authority:false,trading_authority:false};
  await assert.rejects(readJob(async()=>bad,bad.job_id,async()=>{}),/TASK_EVIDENCE_INVALID/);
});
test('review packet must match pack, content and basis together; no permissive fallback',()=>{
  const row={pack_hash:'p',content_hash:'c',basis_hash:'b'};
  assert.equal(matchingReview({packet:{...row}},row),true);
  for(const key of Object.keys(row))assert.equal(matchingReview({packet:{...row,[key]:'other'}},row),false);
});
test('server filters are exact AND values, normalize date/code, never fuzzy-widen scope',()=>{
  assert.deepEqual(queryFilters({industry:'semiconductor',date:'2026-11-10',ticker:'603986.sh'}),{industry_key:'semiconductor',research_date:'20261110',ts_code:'603986.SH'});
  assert.throws(()=>queryFilters({ticker:'60398'}),/EXACT_TICKER_REQUIRED/);
  assert.throws(()=>queryFilters({date:'2026-02-30'}),/RESEARCH_DATE_INVALID/);
});
test('API wrapper never retries a POST or calls an external endpoint',async()=>{
  let calls=0;const fetcher=async()=>{calls++;throw Error('NETWORK_UNCONFIRMED');};
  await assert.rejects(apiRequest(fetcher,'/api/workspace/job',{command_id:'x'}));assert.equal(calls,1);
  await assert.rejects(apiRequest(fetcher,'https://provider.example/api'),/API_PATH_REFUSED/);assert.equal(calls,1);
});
test('shared history is bound to current actor/version and cannot claim production authority',async()=>{
  const good={schema:'ar.shared-workspace.v1',my_workspace:{login:context.login,workspace_id:context.workspaceId},execution_identity:{code_sha:context.codeSha,source_tree_hash:'b'.repeat(64)},sample_purpose:'WORKFLOW_DEBUG',human_review:'PENDING',production_authority:false,trading_authority:false,page:0,page_size:50,my_jobs:[],team_jobs:[],my_total:0,team_total:0,common_data:{observation:null}};
  assert.deepEqual(await readSharedSnapshot(async()=>good,context,0,async()=>{}),good);
  const historical={...good,team_total:1,team_jobs:[{job_id:'job_cccccccc-cccc-cccc-cccc-cccccccccccc',sample_purpose:'WORKFLOW_DEBUG',human_review:'PENDING',production_authority:false,trading_authority:false}]};
  assert.deepEqual(await readSharedSnapshot(async()=>historical,context,0,async()=>{}),historical);
  for(const bad of [{...good,production_authority:true},{...good,my_workspace:{...good.my_workspace,login:'other@example.com'}},{...good,execution_identity:{...good.execution_identity,code_sha:'c'.repeat(40)}}])
    await assert.rejects(readSharedSnapshot(async()=>bad,context,0,async()=>{}),/SHARED_HISTORY_INVALID/);
});
