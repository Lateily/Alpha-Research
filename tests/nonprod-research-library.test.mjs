import assert from 'node:assert/strict';
import test from 'node:test';
import { existsSync } from 'node:fs';
const url = new URL('../tools/nonprod_workbench/ui/research-library-view.mjs', import.meta.url);
const view = existsSync(url) ? await import(url) : {};
const context = { login: 'owner', codeSha: 'a'.repeat(40), filters: { industry_key: 'chip & memory', research_date: '20261105' }, page: 0 };
function fixture() { return { schema: 'ar.shared-research-library.v1', my_workspace: {login:'owner'}, consumer_code_sha:'a'.repeat(40),
  library_hash:'b'.repeat(64), status:'EMPTY', total:0, page:0, page_size:50, results:[],
  query: {industry_key:'chip & memory', industry_taxonomy:null, taxonomy_version:null, research_date:'20261105', ts_code:null},
  content_sharing_allowed:false, content_status:'RIGHTS_UNVERIFIED_CONTENT_DENIED',
  rights:{status:'UNVERIFIED',visibility:'PRIVATE',sharing_allowed:false,model_use_allowed:false},
  human_review:'PENDING',production_authority:false,paper_authority:false,u4_authority:false,trading_authority:false }; }

test('research query preserves research date and encodes only closed exact filters', async () => {
  assert.equal(typeof view.readResearchLibrary, 'function');
  let path; const response = await view.readResearchLibrary(async value => {path=value;return fixture();}, context, async()=>{});
  const parsed = new URL(path,'https://local');
  assert.equal(parsed.pathname,'/api/shared-workspace/research-library');
  assert.equal(parsed.searchParams.get('industry_key'),'chip & memory');
  assert.equal(parsed.searchParams.get('research_date'),'20261105');
  assert.equal(parsed.searchParams.has('trade_date'),false);
  assert.equal(response.status,'EMPTY');
});

test('actor version query and content-authority mismatches refuse the whole response', async () => {
  assert.equal(typeof view.readResearchLibrary, 'function');
  for (const change of [v=>v.my_workspace.login='member',v=>v.consumer_code_sha='c'.repeat(40),
    v=>v.query.research_date='20261004',v=>v.content_sharing_allowed=true,v=>v.rights.sharing_allowed=true,
    v=>v.production_authority=true,v=>v.human_review='PASS',v=>v.results=[{report:'restricted'}],
    v=>v.library_hash=null,v=>v.page=1]) {
    const data=fixture();change(data);
    await assert.rejects(view.readResearchLibrary(async()=>data,context,async()=>{}),/RESEARCH_LIBRARY_CONTEXT_MISMATCH/);
  }
  const disabled=fixture();disabled.status='NOT_CONFIGURED';disabled.library_hash=null;
  assert.equal((await view.readResearchLibrary(async()=>disabled,context,async()=>{})).status,'NOT_CONFIGURED');
});

test('manual refresh is single flight and disposed contexts cannot apply stale responses', async () => {
  assert.equal(typeof view.createLibraryReader,'function');
  let resolve, calls=0; const applied=[];
  const reader=view.createLibraryReader({read:()=>{calls++;return new Promise(r=>resolve=r);},apply:v=>applied.push(v),fail:assert.fail});
  const first=reader.refresh();reader.refresh();reader.refresh();assert.equal(calls,1);
  reader.stop();resolve('old');await first;assert.deepEqual(applied,[]);
});

test('different login filter version and page contexts never retain prior data', () => {
  assert.equal(typeof view.libraryContextKey,'function');
  const key=view.libraryContextKey(context), state={key,data:fixture(),stale:false,error:''};
  assert.equal(view.libraryView(state,key,false).stale,false);
  for(const changed of [{...context,login:'member'},{...context,codeSha:'d'.repeat(40)},
    {...context,page:1},{...context,filters:{research_date:'20261004'}}]) {
    assert.notEqual(view.libraryContextKey(changed),key);
    assert.equal(view.libraryView(state,view.libraryContextKey(changed),false).data,null);
  }
  assert.equal(view.libraryView({...state,stale:true,error:'HASH_INVALID'},key,false).status,'DISCONNECTED');
  assert.equal(view.libraryView(state,key,true).stale,true);
});

test('valid metadata rows render only with bounded identities and source clocks', async () => {
  const data=fixture();data.status='RESULTS_AVAILABLE_NOT_HUMAN_VERIFIED';data.total=1;
  const row={material_id:'research-result-test',version:'v1',company:'600000.SH',industry_key:'chip & memory',
    industry_taxonomy:'test',taxonomy_version:'v1',research_date:'20261105',source_cutoff_at:'2026-10-04T00:00:00Z',
    artifact_generated_at:'2026-11-04T18:00:00Z',archived_at:'2026-11-04T18:01:00Z',execution_attestation:'RECORDED_NOT_REMOTE_ATTESTED',
    stored_verification:'BYTE_BINDINGS_VERIFIED_NOT_RERUN',human_review:'PENDING',assessments:['UNRESOLVED'],
    ...Object.fromEntries(['result_hash','pack_hash','record_hash','report_sha256'].map(key=>[key,'b'.repeat(64)])),
    ...Object.fromEntries(['production_authority','paper_authority','u4_authority','trading_authority'].map(key=>[key,false])),
    consumer_execution_identity:{code_sha:'c'.repeat(40),source_tree_hash:'d'.repeat(64)},
    importer_execution_identity:{code_sha:'e'.repeat(40),source_tree_hash:'f'.repeat(64)},
    source_documents:[{material_id:'source',version:'v1',pdf_sha256:'a'.repeat(64),published_at:'2026-10-01',
      available_at:'2026-10-04',captured_at:'2026-10-04',publication_precision:null,publisher_status:'UNVERIFIED'}]};
  data.results=[row];assert.equal((await view.readResearchLibrary(async()=>data,context,async()=>{})).results.length,1);
  for (const bad of [null,{...row,consumer_execution_identity:null},{...row,company:{}},
    {...row,source_documents:[{...row.source_documents[0],excerpt:'restricted'}]}]) {
    data.results=[bad];await assert.rejects(view.readResearchLibrary(async()=>data,context,async()=>{}),/RESEARCH_LIBRARY_CONTEXT_MISMATCH/);
  }
});
