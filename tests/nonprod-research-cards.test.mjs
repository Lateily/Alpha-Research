import assert from 'node:assert/strict';
import test from 'node:test';
import { existsSync } from 'node:fs';
const url=new URL('../tools/nonprod_workbench/ui/research-cards-view.mjs',import.meta.url);
const cards=existsSync(url)?await import(url):{};
const context={login:'owner',workspaceId:'workspace-a',codeSha:'a'.repeat(40),filters:{industry_key:'chip',research_date:'20261110'},page:0};
function base(){return {my_workspace:{login:'owner',workspace_id:'workspace-a'},consumer_code_sha:context.codeSha,
  sample_purpose:'WORKFLOW_DEBUG',human_review:'PENDING',content_sharing_allowed:false,
    content_status:'RIGHTS_UNVERIFIED_CONTENT_DENIED',production_authority:false,paper_authority:false,u4_authority:false,trading_authority:false,
    prospective_sample_eligible:false,network_calls:0,model_calls:0,claim_allowed:false,no_trade_flag:true};}
function library(){return {...base(),schema:'ar.shared-research-card-library.v1',status:'EMPTY',library_hash:'b'.repeat(64),
  query:{industry_key:'chip',industry_taxonomy:null,taxonomy_version:null,research_date:'20261110',ts_code:null},
  page:0,page_size:50,total:0,results:[],rights:{status:'UNVERIFIED',visibility:'PRIVATE',sharing_allowed:false,model_use_allowed:false}};}
test('card query and context use separate closed contract',async()=>{
  assert.equal(typeof cards.readCardLibrary,'function');let path;
  const value=await cards.readCardLibrary(async p=>{path=p;return library();},context,async()=>{});
  assert.equal(new URL(path,'https://local').pathname,'/api/shared-workspace/research-card-library');
  assert.equal(value.total,0);
});
test('actor workspace code rights and query mismatch reject',async()=>{
  assert.equal(typeof cards.readCardLibrary,'function');
  for(const change of [d=>d.my_workspace.login='member',d=>d.my_workspace.workspace_id='workspace-b',
    d=>d.consumer_code_sha='c'.repeat(40),d=>d.query.research_date='20261004',d=>d.content_sharing_allowed=true,
    d=>d.rights.model_use_allowed=true,d=>d.human_review='PASS',d=>d.production_authority=true,
    d=>d.results=[{report:'DENIED_CONTENT'}]]){
    const value=library();change(value);
    await assert.rejects(cards.readCardLibrary(async()=>value,context,async()=>{}),/CARDS_CONTEXT_MISMATCH/);
  }
});
test('card choices are exact identity metadata and not arbitrary source paths',async()=>{
  assert.equal(typeof cards.readCardInputs,'function');
  const value={...base(),schema:'ar.shared-research-card-inputs.v1',enabled:true,inputs:[]};
  assert.equal((await cards.readCardInputs(async()=>value,context,async()=>{})).enabled,true);
  await assert.rejects(cards.readCardInputs(async()=>({...value,inputs:[{path:'/private/tmp'}]}),context,async()=>{}),/CARDS_CONTEXT_MISMATCH/);
});
test('response roots nested envelopes and all fixed labels are closed',async()=>{
  for(const change of [d=>d.raw_financial_data={revenue_value:123456,source_text:'DENIED_PROSE'},
    d=>d.claim_allowed=true,d=>d.no_trade_flag=false,d=>d.prospective_sample_eligible=true,
    d=>d.network_calls=1,d=>d.model_calls=false,d=>d.deployment_authority=true,
    d=>d.my_workspace.extra='DENIED',d=>d.query.extra='DENIED',d=>d.rights.extra='DENIED']){
    const value=library();change(value);
    await assert.rejects(cards.readCardLibrary(async()=>value,context,async()=>{}),/CARDS_CONTEXT_MISMATCH/);
  }
  for(const change of [d=>d.extra={source_text:'DENIED'},d=>d.claim_allowed=true,d=>d.my_workspace.extra=true]){
    const value={...base(),schema:'ar.shared-research-card-inputs.v1',enabled:true,inputs:[]};change(value);
    await assert.rejects(cards.readCardInputs(async()=>value,context,async()=>{}),/CARDS_CONTEXT_MISMATCH/);
  }
});
test('workspace changes and revalidation epochs hide stale card data',()=>{
  assert.equal(typeof cards.cardsContextKey,'function');
  const key=cards.cardsContextKey(context),state={key,verificationEpoch:'old',data:library(),stale:false};
  assert.notEqual(cards.cardsContextKey({...context,workspaceId:'workspace-b'}),key);
  assert.equal(cards.cardsView(state,key,false,'new').stale,true);
  assert.equal(cards.cardsView(state,'changed',false,'old').data,null);
  assert.equal(cards.cardsView(state,key,false,'old').stale,false);
});
test('actual submission predicate rejects retained handlers stale views and missing selections',()=>{
  assert.equal(typeof cards.canRunCard,'function');
  const ready={activeKey:'current',requestKey:'current',stale:false,busy:false,selected:{snapshot_id:'frozen'}};
  assert.equal(cards.canRunCard(ready),true);
  for(const changed of [{activeKey:'new-workspace'},{stale:true},{busy:true},{selected:null}])
    assert.equal(cards.canRunCard({...ready,...changed}),false);
});
test('refresh handler clears live verification active context selection and increments epoch synchronously',()=>{
  const verified={current:'old'},active={current:'old'};let selected='old',revision=4;
  cards.refreshCardVerification({verified,active,setSelected:v=>{selected=v;},setRevision:fn=>{revision=fn(revision);}});
  assert.equal(verified.current,null);assert.equal(active.current,null);assert.equal(selected,'');assert.equal(revision,5);
});
test('populated cards preserve missing valuation and daily continuity break without body leakage',async()=>{
  const item={company:'603986.SH',research_date:'20261110',source_cutoff_at:'2026-10-04T23:59:59+08:00',
    artifact_generated_at:'2026-11-10T01:48:00+08:00',industry_key:'chip',industry_taxonomy:'manual',taxonomy_version:'v1',
    job_id:'test-job',workspace_id:'workspace-a',actor:'owner',submitted_at:1,code_sha:'a'.repeat(40),
    ...Object.fromEntries(['input_hash','pack_hash','content_hash','basis_hash','output_hash','report_sha256','archive_library_hash'].map(k=>[k,'b'.repeat(64)])),
    status:'SUCCEEDED',archive_status:'ARCHIVED',human_review:'PENDING',content_sharing_allowed:false,
    content_status:'RIGHTS_UNVERIFIED_CONTENT_DENIED',sample_purpose:'WORKFLOW_DEBUG',
    content_producer:{code_sha:'c'.repeat(40),source_tree_hash:'d'.repeat(64)},
    basis_producer:{code_sha:'c'.repeat(40),source_tree_hash:'e'.repeat(64)},citation_locations:[],steps:['OUTPUT_SEALED'],
    cards:{facts:{status:'CITED_DRAFT_NOT_HUMAN_VERIFIED',observation_count:86,calculation_count:6,assessment_counts:{MIXED:2,UNRESOLVED:1}},
      valuation:{status:'BASIS_EVIDENCE_PARTIAL',normalized_eps_status:'NOT_ESTABLISHED',value_band_status:'NOT_ESTABLISHED',
        cash_status:'DATA_BLOCKED',net_cash_status:'NOT_ESTABLISHED',missing_cash_components:['other_interest_debt'],
        fair_multiple_status:'NOT_ESTABLISHED',missing_normalization_assumptions:['revenue']},
      daily:{status:'DATA_BLOCKED',eligible:false,reason_codes:[],continuity_status:'BREAK',vintage_status:'CAPTURE_ONLY_NOT_EVENT_VINTAGE',source_trade_date:'20261105'},
      execution_feedback:{status:'NOT_SUPPLIED',pnl_status:'NOT_SUPPLIED'}}};
  const value=library();Object.assign(value,{status:'RESULTS_AVAILABLE_NOT_HUMAN_VERIFIED',total:1,results:[item]});
  assert.equal((await cards.readCardLibrary(async()=>value,context,async()=>{})).results[0].cards.daily.continuity_status,'BREAK');
  for(const change of [r=>r.cards.daily.eligible=true,r=>r.cards.valuation.normalized_eps=0,
    r=>r.cards.facts.report='DENIED',r=>r.paper_authority=true,r=>r.cards.facts.assessment_counts.APPROVED=1]){
    const bad=structuredClone(value);change(bad.results[0]);
    await assert.rejects(cards.readCardLibrary(async()=>bad,context,async()=>{}),/CARDS_CONTEXT_MISMATCH/);
  }
});
