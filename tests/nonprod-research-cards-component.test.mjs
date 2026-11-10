import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';

async function scenario(check){
  const state={slots:[],cursor:0,pending:[],dirty:true};
  const hooks={createElement:(type,props,...children)=>({type,props:{...props,children}}),Fragment:Symbol('Fragment'),
    useState(initial){const n=state.cursor++;if(!(n in state.slots))state.slots[n]=typeof initial==='function'?initial():initial;
      return [state.slots[n],value=>{state.slots[n]=typeof value==='function'?value(state.slots[n]):value;state.dirty=true;}];},
    useRef(value){const n=state.cursor++;return state.slots[n]||=( {current:value});},
    useEffect(fn,deps){const n=state.cursor++,old=state.slots[n];if(!old||deps.some((v,k)=>v!==old.deps[k]))
      state.pending.push(()=>{old?.cleanup?.();state.slots[n]={deps,cleanup:fn()};});}};
  const previous=globalThis.__arCardHooks;globalThis.__arCardHooks=hooks;
  try{
    const result=await build({entryPoints:['tools/nonprod_workbench/ui/research-cards.jsx'],bundle:true,write:false,format:'esm',platform:'node',
      plugins:[{name:'card-hooks',setup(b){
        b.onResolve({filter:/^react$/},()=>({path:'react',namespace:'hooks'}));
        b.onLoad({filter:/.*/,namespace:'hooks'},()=>({contents:'const h=globalThis.__arCardHooks;export default h;export const {useState,useRef,useEffect}=h;'}));
        b.onResolve({filter:/^lucide-react$/},()=>({path:'icons',namespace:'icons'}));
        b.onLoad({filter:/.*/,namespace:'icons'},()=>({contents:'export const ChevronLeft=()=>null,ChevronRight=()=>null,FileSearch=()=>null,Play=()=>null,RefreshCw=()=>null,Search=()=>null;'}));
      }}]});
    const {default:Cards,CitationLocations}=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64')+'#'+Math.random());
    const calls=[],submitted=[];let fail=false,hold=false,release,tree;
    const props={login:'owner',workspaceId:'workspace-a',codeSha:'a'.repeat(40),parentStale:false,refreshRevision:0,busy:false,
      renew:async()=>{},onRun:value=>submitted.push(value),onOpenJob:()=>{},api:async path=>{
        calls.push(path);if(fail)throw new Error('HASH_CHANGED');
        if(hold)await new Promise(resolve=>{release=resolve;});
        const base={my_workspace:{login:props.login,workspace_id:props.workspaceId},consumer_code_sha:props.codeSha,
          sample_purpose:'WORKFLOW_DEBUG',human_review:'PENDING',content_sharing_allowed:false,content_status:'RIGHTS_UNVERIFIED_CONTENT_DENIED',
          production_authority:false,paper_authority:false,u4_authority:false,trading_authority:false,
          prospective_sample_eligible:false,network_calls:0,model_calls:0,claim_allowed:false,no_trade_flag:true};
        if(path.endsWith('/research-card-inputs'))return {...base,schema:'ar.shared-research-card-inputs.v1',enabled:true,inputs:[{
          snapshot_id:'registered-card',input_hash:'b'.repeat(64),company:'603986.SH',research_date:'20261110',
          source_cutoff_at:'2026-10-04T23:59:59+08:00',artifact_generated_at:'2026-11-10T01:48:00+08:00',
          industry_key:'chip',industry_taxonomy:'manual',taxonomy_version:'v1',pack_hash:'c'.repeat(64),
          content_hash:'d'.repeat(64),basis_hash:'e'.repeat(64),classification_status:'SOURCE_METADATA_NOT_RECLASSIFIED',projection_hash:'f'.repeat(64)}]};
        const query=Object.fromEntries(new URL(path,'https://local').searchParams);delete query.page;
        return {...base,schema:'ar.shared-research-card-library.v1',status:'EMPTY',library_hash:'b'.repeat(64),total:0,page:0,page_size:50,results:[],
          query:{industry_key:null,industry_taxonomy:null,taxonomy_version:null,research_date:null,ts_code:null,...query},
          rights:{status:'UNVERIFIED',visibility:'PRIVATE',sharing_allowed:false,model_use_allowed:false}};
      }};
    function render(){state.cursor=0;state.dirty=false;tree=Cards(props);}
    async function settle(){for(let i=0;i<12;i++){if(state.dirty)render();while(state.pending.length)state.pending.shift()();await Promise.resolve();}}
    function nodes(value){if(Array.isArray(value))return value.flatMap(nodes);if(!value||typeof value!=='object')return[];return[value,...nodes(value.props?.children)];}
    const button=()=>nodes(tree).find(n=>n.props?.['aria-label']==='提交研究卡核验');
    await settle();
    await check({props,calls,submitted,settle,nodes:()=>nodes(tree),button,CitationLocations,fail:()=>{fail=true;},
      hold:()=>{hold=true;},release:()=>{hold=false;release?.();},render:()=>{state.dirty=true;}});
  }finally{for(const slot of state.slots)slot?.cleanup?.();globalThis.__arCardHooks=previous;}
}
test('actual card selection clears on workspace change and a retained click cannot submit',()=>scenario(async s=>{
  s.nodes().find(n=>n.props?.['aria-label']==='冻结研究卡').props.onChange({target:{value:'registered-card'}});await s.settle();
  assert.equal(s.button().props.disabled,false);const old=s.button().props.onClick;
  s.props.workspaceId='workspace-b';s.render();await s.settle();
  assert.equal(s.button().props.disabled,true);old();await s.settle();assert.equal(s.submitted.length,0);
}));
test('submitting unchanged query revalidates the actual mounted card archive',()=>scenario(async s=>{
  const count=()=>s.calls.filter(p=>p.includes('/research-card-library?')).length;
  const before=count();s.nodes().find(n=>n.type==='form').props.onSubmit({preventDefault(){}});await s.settle();
  assert.equal(count(),before+1);
}));
test('a failed independent revalidation does not retain actionable old card choices',()=>scenario(async s=>{
  s.nodes().find(n=>n.props?.['aria-label']==='冻结研究卡').props.onChange({target:{value:'registered-card'}});await s.settle();
  assert.equal(s.button().props.disabled,false);s.fail();s.props.refreshRevision++;s.render();await s.settle();
  assert.equal(s.button().props.disabled,true);assert.ok(JSON.stringify(s.nodes()).includes('DISCONNECTED'));
}));
test('actual card citation component displays bound fact PDF page and line locations',()=>scenario(async s=>{
  assert.equal(typeof s.CitationLocations,'function');
  const tree=s.CitationLocations({locations:[{fact_id:'bound-fact',sha256:'a'.repeat(64),page:6,start:4,end:5}]});
  const shown=JSON.stringify(tree);
  assert.ok(shown.includes('bound-fact'));assert.ok(shown.includes('a'.repeat(64)));
  assert.ok(shown.includes('6'));assert.ok(shown.includes('4'));assert.ok(shown.includes('5'));
}));
test('same-context refresh fences retained handlers immediately and after failure',()=>scenario(async s=>{
  s.nodes().find(n=>n.props?.['aria-label']==='冻结研究卡').props.onChange({target:{value:'registered-card'}});await s.settle();
  const old=s.button().props.onClick;s.fail();
  s.nodes().find(n=>n.props?.['aria-label']==='刷新研究卡').props.onClick();old();
  await s.settle();old();assert.equal(s.submitted.length,0);assert.equal(s.button().props.disabled,true);
}));
test('same-context refresh disables selection throughout pending verification',()=>scenario(async s=>{
  s.nodes().find(n=>n.props?.['aria-label']==='冻结研究卡').props.onChange({target:{value:'registered-card'}});await s.settle();
  s.hold();s.nodes().find(n=>n.props?.['aria-label']==='刷新研究卡').props.onClick();await s.settle();
  const disabled=s.button().props.disabled;s.release();await s.settle();
  assert.equal(disabled,true);assert.equal(s.button().props.disabled,true);
}));
