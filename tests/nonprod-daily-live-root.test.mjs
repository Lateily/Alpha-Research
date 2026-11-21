import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {pendingStore} from '../tools/nonprod_workbench/live-ui/live-state.mjs';

const clone=value=>structuredClone(value),deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
const hash='b'.repeat(64),jobId='cccccccc-cccc-cccc-cccc-cccccccccccc';
function fixtures(){
 const labels={sample_purpose:'WORKFLOW_DEBUG',human_review:'PENDING',production_authority:false,trading_authority:false};
 const c={login:'owner@example.com',workspaceId:'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',codeSha:'a'.repeat(40)};
 const row={job_id:jobId,workspace_id:c.workspaceId,actor:c.login,submitted_at:1,code_sha:c.codeSha,
  company:'603986.SH',research_date:'20261110',source_cutoff_at:'2026-10-04T23:59:59+08:00',artifact_generated_at:'2026-11-10T01:48:00+08:00',industry_key:'semiconductor',industry_taxonomy:'manual',taxonomy_version:'v1',
  ...Object.fromEntries(['input_hash','pack_hash','content_hash','basis_hash','output_hash','report_sha256','archive_library_hash'].map(key=>[key,hash])),
  status:'SUCCEEDED',archive_status:'ARCHIVED',human_review:'PENDING',content_sharing_allowed:false,content_status:'RIGHTS_UNVERIFIED_CONTENT_DENIED',sample_purpose:'WORKFLOW_DEBUG',
  content_producer:{code_sha:'c'.repeat(40),source_tree_hash:'d'.repeat(64)},basis_producer:{code_sha:'c'.repeat(40),source_tree_hash:'e'.repeat(64)},
  citation_locations:[{fact_id:'synthetic_fact',sha256:hash,page:6,start:4,end:5}],steps:['REGISTERED_INPUT_VERIFIED','CONTENT_RECOMPUTED','BASIS_RECOMPUTED','METADATA_ARCHIVED','OUTPUT_SEALED'],
  cards:{facts:{status:'CITED_DRAFT_NOT_HUMAN_VERIFIED',observation_count:1,calculation_count:1,assessment_counts:{UNRESOLVED:1}},
   valuation:{status:'BASIS_EVIDENCE_PARTIAL',normalized_eps_status:'NOT_ESTABLISHED',value_band_status:'NOT_ESTABLISHED',cash_status:'DATA_BLOCKED',net_cash_status:'NOT_ESTABLISHED',missing_cash_components:['other_interest_debt'],fair_multiple_status:'NOT_ESTABLISHED',missing_normalization_assumptions:['revenue']},
   daily:{status:'DATA_BLOCKED',eligible:false,reason_codes:[],continuity_status:'BREAK',vintage_status:'CAPTURE_ONLY_NOT_EVENT_VINTAGE',source_trade_date:'20261105'},execution_feedback:{status:'NOT_SUPPLIED',pnl_status:'NOT_SUPPLIED'}}};
 const input={...Object.fromEntries(['company','research_date','source_cutoff_at','artifact_generated_at','industry_key','industry_taxonomy','taxonomy_version','input_hash','pack_hash','content_hash','basis_hash'].map(key=>[key,row[key]])),snapshot_id:'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',classification_status:'SOURCE_METADATA_NOT_RECLASSIFIED',projection_hash:hash};
 const {job_id,workspace_id,actor,submitted_at,code_sha,input_hash,...review}=row;
 const detail={job_id,workspace_id,actor,submitted_at,code_sha,input_hash,...labels,command_id:'shared_12345678',kind:'research-cards-review',snapshot_id:input.snapshot_id,attempt_id:jobId,source_tree_hash:hash,source_run_id:null,source_trade_date:null,schema_version:'ar.shared-workspace.v1',error:null,status:'SUCCEEDED',output_hash:hash,research_cards:review,
  result:{status:'SUCCEEDED',archive_status:'ARCHIVED',content_sharing_allowed:false,human_review:'PENDING',seal_hash:hash,output_hash:hash,archive_library_hash:hash,report_sha256:hash}};
 return{labels,c,row,input,detail};
}

async function rootScenario(check,options={}){
 const f=fixtures(),slots=[],effects=[],timers=new Map(),calls=[],storageMap=new Map();let now=1000,cursor=0,dirty=true,tree,id=0,post=null,task=f.detail,holdCards=false,holdHistory=false,empty=options.empty===true;
 const original={now:Date.now,...Object.fromEntries(['fetch','window','location','addEventListener','removeEventListener','setInterval','clearInterval','setTimeout','clearTimeout'].map(key=>[key,globalThis[key]]))};
 const storage={getItem:key=>storageMap.get(key)??null,setItem:(key,value)=>storageMap.set(key,value),removeItem:key=>storageMap.delete(key)};
 Date.now=()=>now;globalThis.location={hash:options.route||'#research'};globalThis.window={localStorage:storage,scrollTo(){}};globalThis.addEventListener=globalThis.removeEventListener=()=>{};
 globalThis.setInterval=()=>++id;globalThis.clearInterval=()=>{};globalThis.setTimeout=(fn,delay)=>{timers.set(++id,{fn,delay});return id;};globalThis.clearTimeout=id=>timers.delete(id);
 globalThis.__dailyRootHooks={Fragment:Symbol('f'),createElement:(type,props,...children)=>({type,props:{...props,children}}),useState(initial){const n=cursor++;if(!(n in slots))slots[n]=typeof initial==='function'?initial():initial;return[slots[n],value=>{slots[n]=typeof value==='function'?value(slots[n]):value;dirty=true;}];},useRef(initial){const n=cursor++;return slots[n]||={current:initial};},useEffect(fn,deps){const n=cursor++,old=slots[n];if(!old||deps.some((value,index)=>value!==old.deps[index]))effects.push(()=>{old?.cleanup?.();slots[n]={deps,cleanup:fn()};});}};
 let commands={};
 function query(path){
  const common={...f.labels,my_workspace:{login:f.c.login,workspace_id:f.c.workspaceId},consumer_code_sha:f.c.codeSha,content_sharing_allowed:false,content_status:'RIGHTS_UNVERIFIED_CONTENT_DENIED',paper_authority:false,u4_authority:false,prospective_sample_eligible:false,network_calls:0,model_calls:0,claim_allowed:false,no_trade_flag:true};
  const params=Object.fromEntries(new URL(path,'https://synthetic.example').searchParams);delete params.page;
  return{schema:'ar.shared-research-card-query.v1',validation_scope:'MATCHING_CARDS_AND_RESULTS_NOT_FULL_HISTORY',inputs:{...common,schema:'ar.shared-research-card-inputs.v2',validation_scope:'MATCHING_CARDS_ONLY_OTHER_INPUTS_NOT_EVALUATED',enabled:true,inputs:[f.input]},
   library:{...common,schema:'ar.shared-research-card-library.v1',status:empty?'EMPTY':'RESULTS_AVAILABLE_NOT_HUMAN_VERIFIED',library_hash:hash,query:{industry_key:null,industry_taxonomy:null,taxonomy_version:null,research_date:null,ts_code:null,...params},page:0,page_size:50,total:empty?0:1,results:empty?[]:[f.row],rights:{status:'UNVERIFIED',visibility:'PRIVATE',sharing_allowed:false,model_use_allowed:false}}};
 }
 globalThis.fetch=async(path,opts={})=>{
  calls.push({path,method:opts.method,body:opts.body});
  if(opts.method==='POST')return post?post(JSON.parse(opts.body)):{ok:false,status:429,json:async()=>({error:'SHARED_QUEUE_LIMIT'})};
  let data;
  if(path==='/api/state')data={access:{shared_workspace_v1:true,login:f.c.login,allowed_job_kinds:['research-cards-review']}};
  else if(path==='/api/shared-workspace/context')data={...f.labels,schema:'ar.shared-workspace-context.v1',my_workspace:{login:f.c.login,workspace_id:f.c.workspaceId},execution_identity:{code_sha:f.c.codeSha,source_tree_hash:hash},owned_commands:commands,validation_scope:'IDENTITY_AND_JOB_REGISTRATION_NOT_OUTPUTS'};
  else if(path.startsWith('/api/shared-workspace/research-card-query?')){if(holdCards||options.holdCards)return new Promise(()=>{});data=query(path);}
  else if(path.startsWith('/api/shared-workspace?page=')){if(holdHistory||options.holdHistory)return new Promise(()=>{});data={...f.labels,schema:'ar.shared-workspace.v1',my_workspace:{login:f.c.login,workspace_id:f.c.workspaceId},execution_identity:{code_sha:f.c.codeSha,source_tree_hash:hash},page:0,page_size:50,my_total:0,team_total:0,my_jobs:[],team_jobs:[],common_data:{observation:null}};}
  else if(path.startsWith('/api/shared-workspace/jobs/'))data=task;
  else throw Error('UNEXPECTED_GET '+path);
  return{ok:true,status:200,json:async()=>clone(data)};
 };
 const icons=['Activity','ArrowDownToLine','ArrowLeft','ArrowRight','BarChart3','Check','ChevronDown','ChevronLeft','ChevronRight','Clock3','FileCheck2','FileSearch','FileText','FlaskConical','FolderOpen','Home','Info','Layers3','LockKeyhole','PanelLeftClose','Play','RefreshCw','Search','Send','ShieldCheck','Wallet','X'];
 try{
  const result=await build({entryPoints:['tools/nonprod_workbench/live-ui/app.jsx'],bundle:true,write:false,format:'esm',platform:'node',plugins:[{name:'root',setup(b){b.onResolve({filter:/^react$/},()=>({path:'react',namespace:'h'}));b.onLoad({filter:/.*/,namespace:'h'},()=>({contents:'const h=globalThis.__dailyRootHooks;export default h;export const {useState,useEffect,useRef}=h;'}));b.onResolve({filter:/^lucide-react$/},()=>({path:'icons',namespace:'i'}));b.onLoad({filter:/.*/,namespace:'i'},()=>({contents:'export const '+icons.map(name=>name+'=()=>null').join(',')+';'}));}}]});
  const {default:App}=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64')+'#'+Math.random());
  const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
  const find=name=>nodes(tree).find(value=>value.type?.name===name),model=()=>find('LiveResearch')?.props.model;
  async function settle(){for(let i=0;i<150;i++){if(dirty){cursor=0;dirty=false;tree=App();}while(effects.length)effects.shift()();await Promise.resolve();}}
  function nav(label){const button=nodes(tree).find(value=>value.type==='button'&&value.props.children?.some(child=>child?.props?.children?.includes(label)));assert.ok(button,label);button.props.onClick();}
  async function renewParents(){for(const [reader,key]of model().parentReads)await reader.read(key,async()=>reader.value().data);await settle();}
  await settle();await check({f,model,find,calls,storage,storageMap,settle,nav,renewParents,at:value=>{now=value;dirty=true;},task:value=>{task=value;},post:fn=>{post=fn;},empty:()=>{empty=true;},holdCards:()=>{holdCards=true;},holdHistory:()=>{holdHistory=true;},runTimers:async()=>{const pending=[...timers.values()];timers.clear();for(const timer of pending)timer.fn();await settle();},unmount:()=>{for(const slot of slots)slot?.cleanup?.();}});
 }finally{for(const slot of slots)slot?.cleanup?.();Date.now=original.now;for(const[key,value]of Object.entries(original)){if(key==='now')continue;if(value===undefined)delete globalThis[key];else globalThis[key]=value;}delete globalThis.__dailyRootHooks;}
}

test('actual root retained evidence cannot borrow a newer time or survive changed task verification',()=>rootScenario(async s=>{
 s.model().open(jobId);await s.settle();const old=s.model().detail.data,callback=s.find('LiveResearch').props.onEvidence;
 const {research_cards,...metadata}=old;
 s.at(5000);s.task({...metadata,status:'RECOVERY_REQUIRED',result:null,error:'SHARED_OUTPUT_INTEGRITY_ERROR'});await s.model().detail.refresh();await s.renewParents();await s.settle();assert.equal(s.model().detail.data.status,'RECOVERY_REQUIRED');
 callback('old succeeded evidence',old);await s.settle();const drawer=s.find('Drawer');assert.ok(!drawer||drawer.props.canRead()===false);
}));
test('actual root expired evidence cannot be stamped with a later identical response time',()=>rootScenario(async s=>{
 s.model().open(jobId);await s.settle();const old=s.model().detail.data,callback=s.find('LiveResearch').props.onEvidence;
 s.at(20000);await s.model().detail.refresh();await s.renewParents();callback('old evidence',old);await s.settle();const drawer=s.find('Drawer');assert.ok(!drawer||drawer.props.canRead()===false);
}));
for(const field of ['codeSha','workspaceId','login'])test('held POST retires busy without losing old pending across '+field,()=>rootScenario(async s=>{
 const d=deferred(),old=clone(s.f.c);s.post(()=>d.promise);const request=s.model().submit(s.f.input.snapshot_id);await s.settle();assert.equal(s.model().busy,true);
 s.f.c[field]=field==='codeSha'?'d'.repeat(40):field==='workspaceId'?'dddddddd-dddd-dddd-dddd-dddddddddddd':'member@example.com';
 if(field==='login')s.find('IconButton').props.onClick();else await s.model().contextRead.refresh();await s.settle();
 assert.equal(s.model().context[field],s.f.c[field]);assert.equal(s.model().busy,false);
 d.resolve({ok:true,status:200,json:async()=>({job_id:jobId,status:'QUEUED',disposition:'CREATED'})});await request;await s.settle();
 assert.equal(s.model().busy,false);assert.equal(s.model().pending,null);assert.equal(pendingStore(s.storage,old).read().job_id,jobId);
}));
test('older POST completion cannot unlock a newer context attempt or replace its pending command',()=>rootScenario(async s=>{
 const a=deferred(),b=deferred(),old=clone(s.f.c);s.post(()=>a.promise);const first=s.model().submit(s.f.input.snapshot_id);await s.settle();
 s.f.c.codeSha='d'.repeat(40);await s.model().contextRead.refresh();await s.settle();s.post(()=>b.promise);const second=s.model().submit(s.f.input.snapshot_id);await s.settle();
 const pending=clone(s.model().pending);a.resolve({ok:true,status:200,json:async()=>({job_id:jobId,status:'QUEUED',disposition:'CREATED'})});await first;await s.settle();
 assert.equal(s.model().busy,true);assert.deepEqual(s.model().pending,pending);assert.equal(pendingStore(s.storage,old).read().job_id,jobId);
 b.resolve({ok:false,status:429,json:async()=>({error:'SYNTHETIC_REJECTED'})});await assert.rejects(second);await s.settle();assert.equal(s.model().busy,false);assert.equal(s.model().pending,null);
}));
test('retained root submit and retry cannot write after Research is disposed into Today',()=>rootScenario(async s=>{
 const submit=s.model().submit,retry=s.model().retry;
 const body={command_id:'shared_12345678',kind:'research-cards-review',snapshot_id:s.f.input.snapshot_id,expected_workspace_id:s.f.c.workspaceId,expected_code_sha:s.f.c.codeSha};pendingStore(s.storage,s.f.c).save(body);
 s.nav('今日');await s.settle();await assert.rejects(submit(s.f.input.snapshot_id));await assert.rejects(retry());
 assert.equal(s.calls.filter(call=>call.method==='POST').length,0);
}));
for(const status of [400,403,429])test('definitive fresh '+status+' releases only its own pending command',()=>rootScenario(async s=>{
 s.post(()=>({ok:false,status,json:async()=>({error:'SYNTHETIC_REJECTED'})}));await assert.rejects(s.model().submit(s.f.input.snapshot_id));await s.settle();
 assert.equal(pendingStore(s.storage,s.f.c).read(),null);assert.equal(s.model().pending,null);assert.equal(s.model().busy,false);
}));
test('unknown delivery followed by a rejected explicit retry keeps the original command',()=>rootScenario(async s=>{
 s.post(()=>{throw Error('NETWORK_UNCONFIRMED');});await assert.rejects(s.model().submit(s.f.input.snapshot_id));await s.settle();const original=clone(pendingStore(s.storage,s.f.c).read());
 s.post(()=>({ok:false,status:403,json:async()=>({error:'SESSION_REQUIRED'})}));await assert.rejects(s.model().retry());await s.settle();assert.deepEqual(pendingStore(s.storage,s.f.c).read(),original);
 assert.deepEqual(s.calls.filter(call=>call.method==='POST').map(call=>JSON.parse(call.body).command_id),[original.body.command_id,original.body.command_id]);
}));
test('selected detail stops polling after navigating to Tests',()=>rootScenario(async s=>{
 s.model().open(jobId);await s.settle();s.nav('测试');await s.settle();const before=s.calls.filter(call=>call.path.includes('/jobs/')).length;await s.runTimers();assert.equal(s.calls.filter(call=>call.path.includes('/jobs/')).length,before);
}));
const require=createRequire(import.meta.url);let actualDaily;
async function dailyHTML(props){
 if(!actualDaily){const built=await build({entryPoints:['tools/nonprod_workbench/daily-ui/app.jsx'],bundle:true,write:false,platform:'node',format:'esm',plugins:[{name:'actual',setup(b){b.onResolve({filter:/^(react|lucide-react)$/},args=>({path:pathToFileURL(require.resolve(args.path)).href,external:true}));}}]});actualDaily=(await import('data:text/javascript;base64,'+Buffer.from(built.outputFiles[0].text).toString('base64'))).DailyView;}
 return renderToStaticMarkup(React.createElement(actualDaily,props));
}
test('actual root loading counters stay unknown until each data source verifies',()=>rootScenario(async s=>{
 const html=await dailyHTML(s.find('DailyView').props);assert.ok(!/<strong[^>]*>0<\/strong>/.test(html));assert.ok(!html.includes('材料与结果已封存'));assert.ok(html.includes('待核验')||html.includes('未核验'));
},{route:'#today',holdCards:true,holdHistory:true}));
test('actual root partial reads do not turn missing task evidence into zero',()=>rootScenario(async s=>{
 const html=await dailyHTML(s.find('DailyView').props);assert.ok(!/<strong[^>]*>0<\/strong>/.test(html));
},{route:'#today',holdHistory:true}));
test('verified empty sources may display actual zeros, unlike unavailable reads',()=>rootScenario(async s=>{
 const html=await dailyHTML(s.find('DailyView').props);assert.equal((html.match(/<strong[^>]*>0<\/strong>/g)||[]).length,3);
 assert.ok(html.includes('发布来源尚未核验'));
},{route:'#today',empty:true}));
