import assert from 'node:assert/strict';
import test from 'node:test';
import * as shared from '../tools/nonprod_workbench/ui/shared-view.mjs';
import { build } from 'esbuild';

async function contextScenario(check){
  const state={slots:[],cursor:0,pending:[]};
  const hooks={createElement:(type,props,...children)=>({type,props:{...props,children}}),Fragment:Symbol('Fragment'),
    useState(initial){const n=state.cursor++;if(!(n in state.slots))state.slots[n]=typeof initial==='function'?initial():initial;
      return [state.slots[n],value=>{state.slots[n]=typeof value==='function'?value(state.slots[n]):value;}];},
    useRef(value){const n=state.cursor++;return state.slots[n]||={current:value};},
    useEffect(fn,deps){const n=state.cursor++,old=state.slots[n];if(!old||deps.some((value,i)=>value!==old.deps[i]))
      state.pending.push(()=>{old?.cleanup?.();state.slots[n]={deps,cleanup:fn()};});}};
  const old={hooks:globalThis.__arContextHooks,window:globalThis.window,now:Date.now,
    setTimeout:globalThis.setTimeout,clearTimeout:globalThis.clearTimeout};
  globalThis.__arContextHooks=hooks;
  try{
    const bundle=await build({entryPoints:['tools/nonprod_workbench/ui/shared-workspace.jsx'],bundle:true,write:false,format:'esm',platform:'node',
      plugins:[{name:'context-hooks',setup(b){
        b.onResolve({filter:/^react$/},()=>({path:'react',namespace:'hooks'}));
        b.onLoad({filter:/.*/,namespace:'hooks'},()=>({contents:'const h=globalThis.__arContextHooks;export default h;export const {useState,useRef,useEffect}=h;'}));
        b.onResolve({filter:/^lucide-react$/},()=>({path:'icons',namespace:'icons'}));
        b.onLoad({filter:/.*/,namespace:'icons'},()=>({contents:'export const ChevronLeft=()=>null,ChevronRight=()=>null,Database=()=>null,Download=()=>null,FileText=()=>null,Library=()=>null,Play=()=>null,RefreshCw=()=>null,Users=()=>null,X=()=>null,FileSearch=()=>null,Search=()=>null,Send=()=>null;'}));
      }}]});
    const {default:Workspace}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64')+'#'+Math.random());
    let now=1000,id=0,tree,code='a'.repeat(40),badScope=false;const timers=new Map(),calls=[],held=[],holding=new Set(),values=new Map();
    Date.now=()=>now;globalThis.setTimeout=(fn,delay)=>{timers.set(++id,{fn,at:now+delay});return id;};
    globalThis.clearTimeout=key=>timers.delete(key);
    const storage={getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value)};
    globalThis.window={localStorage:storage,setInterval:(fn,delay)=>{timers.set(++id,{fn,at:now+delay,interval:delay});return id;},clearInterval:key=>timers.delete(key)};
    const workspace='51715142-1963-466f-8470-ceb609afccbd',job='0cfde834-bca2-4a5a-8d8c-06c9110e1604';
    const props={access:{login:'owner@example.com'},refreshRevision:0,api:async(path,body)=>{
      calls.push(path);assert.equal(body,undefined,'read-only lifecycle must never POST');
      const kind=path==='/api/shared-workspace/context'?'context':path.includes('/jobs/')?'detail':'full';
      const identity={code_sha:code,source_tree_hash:'b'.repeat(64)},owner={login:props.access.login,workspace_id:workspace};
      const data=kind==='context'?{schema:'ar.shared-workspace-context.v1',my_workspace:owner,execution_identity:identity,
        owned_commands:{'pending-card-command':{job_id:job}},validation_scope:badScope?'OUTPUTS_VERIFIED':'IDENTITY_AND_JOB_REGISTRATION_NOT_OUTPUTS',
        sample_purpose:'WORKFLOW_DEBUG',human_review:'PENDING',production_authority:false,trading_authority:false}:
        kind==='detail'?{job_id:job,kind:'research-cards-review',status:'RUNNING',my_workspace:owner,workspace_id:workspace,actor:owner.login}:
        {my_workspace:owner,execution_identity:identity,owned_commands:{},my_jobs:[],team_jobs:[],
          latest_owned_jobs:[{job_id:'latest-brief',actor:owner.login,kind:'snapshot-brief',status:'OLD_BRIEF_STATUS',submitted_at:1}],
          common_data:{sync_status:'SYNCED',current_snapshot_id:'old-publication'}};
      if(holding.has(kind))await new Promise(resolve=>held.push({kind,resolve}));
      return data;
    }};
    function nodes(value){if(Array.isArray(value))return value.flatMap(nodes);if(!value||typeof value!=='object')return[];
      return [value,...nodes(value.props?.children)];}
    async function settle(){for(let i=0;i<14;i++){state.cursor=0;tree=Workspace(props);while(state.pending.length)state.pending.shift()();await Promise.resolve();}}
    async function advance(ms){const end=now+ms;for(;;){const next=[...timers].filter(([,timer])=>timer.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!next)break;
      if(next[1].interval)next[1].at+=next[1].interval;else timers.delete(next[0]);
      now=next[1].interval?next[1].at-next[1].interval:next[1].at;next[1].fn();await settle();}now=end;await settle();}
    const click=async label=>{nodes(tree).find(node=>node.type==='button'&&node.props.children.includes(label)).props.onClick();await settle();};
    const card=()=>nodes(tree).find(node=>node.type?.name==='ResearchCards');
    try{await settle();await check({props,calls,storage,workspace,job,card,click,settle,advance,nodes:()=>nodes(tree),
      text:()=>JSON.stringify(tree),setCode:value=>{code=value;},badScope:()=>{badScope=true;},hold:kind=>holding.add(kind),
      release:kind=>{holding.delete(kind);for(const row of held.filter(row=>row.kind===kind))row.resolve();}});
    }finally{for(const slot of state.slots)slot?.cleanup?.();}
  }finally{globalThis.__arContextHooks=old.hooks;globalThis.window=old.window;Date.now=old.now;
    globalThis.setTimeout=old.setTimeout;globalThis.clearTimeout=old.clearTimeout;}
}

test('cards alone use narrow context while other views retain full history polling',()=>contextScenario(async s=>{
  const full=()=>s.calls.filter(path=>path.startsWith('/api/shared-workspace?page=')).length;
  await s.click('研究卡');const before=full();
  assert.ok(s.calls.includes('/api/shared-workspace/context'));assert.equal(s.card().props.scopedInputs,true);
  assert.ok(s.text().includes('IDENTITY_AND_JOB_REGISTRATION_NOT_OUTPUTS'));
  assert.ok(!s.text().includes('OLD_BRIEF_STATUS'));assert.ok(!s.text().includes('NO_FROZEN_PUBLICATION'));
  await s.advance(12000);assert.equal(full(),before,'cards must stop scheduling expensive history reads');
  await s.click('我的任务');assert.equal(full(),before+1);
  const contexts=s.calls.filter(path=>path==='/api/shared-workspace/context').length;
  await s.advance(6000);assert.equal(s.calls.filter(path=>path==='/api/shared-workspace/context').length,contexts);
}));
test('a retired full read cannot overwrite a new generation after cards and full A B A switching',()=>contextScenario(async s=>{
  s.hold('full');await s.advance(5000);await s.click('研究卡');
  s.setCode('c'.repeat(40));await s.click('我的任务');s.release('full');await s.settle();
  assert.ok(s.text().includes('c'.repeat(40)));assert.ok(!s.text().includes('a'.repeat(40)));
}));
test('retired context responses cannot cross cards full cards or actor generations',()=>contextScenario(async s=>{
  s.hold('context');await s.click('研究卡');assert.ok(s.calls.includes('/api/shared-workspace/context'));await s.click('我的任务');
  s.props.access={login:'member@example.com'};s.setCode('c'.repeat(40));
  s.release('context');await s.click('研究卡');await s.settle();
  assert.equal(s.card().props.login,'member@example.com');assert.equal(s.card().props.codeSha,'c'.repeat(40));
  assert.ok(!s.text().includes('SHARED_IDENTITY_CHANGED'));
}));
test('wrong context scope cannot fall back to cached full metadata',()=>contextScenario(async s=>{
  s.badScope();await s.click('研究卡');
  assert.equal(s.card().props.workspaceId,undefined);assert.equal(s.card().props.parentStale,true);
  assert.ok(s.text().includes('SHARED_CONTEXT_MISMATCH'));assert.ok(!s.text().includes('OLD_BRIEF_STATUS'));
}));
test('fresh narrow context reconciles owned pending IDs without a full GET or POST',()=>contextScenario(async s=>{
  shared.savePending(s.storage,s.workspace,{command_id:'pending-card-command',kind:'research-cards-review',snapshot_id:'original-input'});
  const before=s.calls.filter(path=>path.startsWith('/api/shared-workspace?page=')).length;
  await s.click('研究卡');await s.settle();
  assert.equal(shared.getPending(s.storage,s.workspace)[0].job_id,s.job);
  assert.ok(s.calls.includes('/api/shared-workspace/jobs/'+s.job));
  assert.equal(s.calls.filter(path=>path.startsWith('/api/shared-workspace?page=')).length,before);
}));
test('fresh context never advances selected detail own fifteen-second freshness',()=>contextScenario(async s=>{
  await s.click('研究卡');s.card().props.onOpenJob(s.job);await s.settle();s.hold('detail');
  await s.advance(16000);
  assert.equal(s.card().props.parentStale,false);assert.ok(s.text().includes('DISCONNECTED · STALE'));
  s.release('detail');await s.settle();
}));
