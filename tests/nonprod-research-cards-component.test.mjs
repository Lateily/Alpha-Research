import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';

function archiveRow(){
  return {company:'603986.SH',research_date:'20261110',source_cutoff_at:'2026-10-04T23:59:59+08:00',
    artifact_generated_at:'2026-11-10T01:48:00+08:00',industry_key:'chip',industry_taxonomy:'manual',taxonomy_version:'v1',
    job_id:'0cfde834-bca2-4a5a-8d8c-06c9110e1604',workspace_id:'51715142-1963-466f-8470-ceb609afccbd',
    actor:'owner@example.com',submitted_at:1,code_sha:'a'.repeat(40),
    ...Object.fromEntries(['input_hash','pack_hash','content_hash','basis_hash','output_hash','report_sha256','archive_library_hash'].map(k=>[k,'b'.repeat(64)])),
    status:'SUCCEEDED',archive_status:'ARCHIVED',human_review:'PENDING',content_sharing_allowed:false,
    content_status:'RIGHTS_UNVERIFIED_CONTENT_DENIED',sample_purpose:'WORKFLOW_DEBUG',
    content_producer:{code_sha:'c'.repeat(40),source_tree_hash:'d'.repeat(64)},basis_producer:{code_sha:'c'.repeat(40),source_tree_hash:'e'.repeat(64)},
    citation_locations:[{fact_id:'historical_fact',sha256:'a'.repeat(64),page:6,start:4,end:5}],
    steps:['REGISTERED_INPUT_VERIFIED','CONTENT_RECOMPUTED','BASIS_RECOMPUTED','METADATA_ARCHIVED','OUTPUT_SEALED'],
    cards:{facts:{status:'CITED_DRAFT_NOT_HUMAN_VERIFIED',observation_count:1,calculation_count:6,assessment_counts:{MIXED:2,UNRESOLVED:1}},
      valuation:{status:'BASIS_EVIDENCE_PARTIAL',normalized_eps_status:'NOT_ESTABLISHED',value_band_status:'NOT_ESTABLISHED',
        cash_status:'DATA_BLOCKED',net_cash_status:'NOT_ESTABLISHED',missing_cash_components:['other_interest_debt'],
        fair_multiple_status:'NOT_ESTABLISHED',missing_normalization_assumptions:['revenue']},
      daily:{status:'DATA_BLOCKED',eligible:false,reason_codes:[],continuity_status:'BREAK',vintage_status:'CAPTURE_ONLY_NOT_EVENT_VINTAGE',source_trade_date:'20261105'},
      execution_feedback:{status:'NOT_SUPPLIED',pnl_status:'NOT_SUPPLIED'}}};
}

async function scenario(check,populated=false,scopedInputs=false,combinedQuery=false){
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
    const calls=[],submitted=[],opened=[],releases=[];let fail=false,hold=false,holdInputs=false,failLibrary=false,emptyInputs=false,tree;
    const original={now:Date.now,setTimeout:globalThis.setTimeout,clearTimeout:globalThis.clearTimeout,
      setInterval:globalThis.setInterval,clearInterval:globalThis.clearInterval};
    let now=1000,nextTimer=0;const timers=new Map();
    Date.now=()=>now;
    globalThis.setTimeout=(fn,delay)=>{const id=++nextTimer;timers.set(id,{fn,at:now+delay});return id;};
    globalThis.setInterval=(fn,delay)=>{const id=++nextTimer;timers.set(id,{fn,at:now+delay,interval:delay});return id;};
    globalThis.clearTimeout=globalThis.clearInterval=id=>timers.delete(id);
    const props={login:'owner',workspaceId:'workspace-a',codeSha:'a'.repeat(40),parentStale:false,refreshRevision:0,busy:false,scopedInputs,combinedQuery,
      parentFresh:()=>!props.parentStale,
      renew:async()=>{},onRun:value=>submitted.push(value),onOpenJob:value=>opened.push(value),api:async path=>{
        calls.push(path);if(fail||(failLibrary&&path.includes('/research-card-library?')))throw new Error('HASH_CHANGED');
        if(hold||(holdInputs&&path.endsWith('/research-card-inputs')))await new Promise(resolve=>{releases.push(resolve);});
        const base={my_workspace:{login:props.login,workspace_id:props.workspaceId},consumer_code_sha:props.codeSha,
          sample_purpose:'WORKFLOW_DEBUG',human_review:'PENDING',content_sharing_allowed:false,content_status:'RIGHTS_UNVERIFIED_CONTENT_DENIED',
          production_authority:false,paper_authority:false,u4_authority:false,trading_authority:false,
          prospective_sample_eligible:false,network_calls:0,model_calls:0,claim_allowed:false,no_trade_flag:true};
        const combined=path.includes('/research-card-query?');
        const input={...base,
          schema:path.endsWith('-scoped')||combined?'ar.shared-research-card-inputs.v2':'ar.shared-research-card-inputs.v1',
          ...(path.endsWith('-scoped')||combined?{validation_scope:'MATCHING_CARDS_ONLY_OTHER_INPUTS_NOT_EVALUATED'}:{}),enabled:true,inputs:emptyInputs?[]:[{
          snapshot_id:'registered-card',input_hash:'b'.repeat(64),company:'603986.SH',research_date:'20261110',
          source_cutoff_at:'2026-10-04T23:59:59+08:00',artifact_generated_at:'2026-11-10T01:48:00+08:00',
          industry_key:'chip',industry_taxonomy:'manual',taxonomy_version:'v1',pack_hash:'c'.repeat(64),
          content_hash:'d'.repeat(64),basis_hash:'e'.repeat(64),classification_status:'SOURCE_METADATA_NOT_RECLASSIFIED',projection_hash:'f'.repeat(64)}]};
        if(path.endsWith('/research-card-inputs')||path.endsWith('/research-card-inputs-scoped'))return input;
        const query=Object.fromEntries(new URL(path,'https://local').searchParams);delete query.page;
        const library={...base,schema:'ar.shared-research-card-library.v1',status:populated?'RESULTS_AVAILABLE_NOT_HUMAN_VERIFIED':'EMPTY',library_hash:'b'.repeat(64),total:populated?1:0,page:0,page_size:50,results:populated?[archiveRow()]:[],
          query:{industry_key:null,industry_taxonomy:null,taxonomy_version:null,research_date:null,ts_code:null,...query},
          rights:{status:'UNVERIFIED',visibility:'PRIVATE',sharing_allowed:false,model_use_allowed:false}};
        return combined?{schema:'ar.shared-research-card-query.v1',validation_scope:'MATCHING_CARDS_AND_RESULTS_NOT_FULL_HISTORY',inputs:input,library}:library;
      }};
    function render(){state.cursor=0;state.dirty=false;tree=Cards(props);}
    async function settle(){for(let i=0;i<12;i++){if(state.dirty)render();while(state.pending.length)state.pending.shift()();await Promise.resolve();}}
    function nodes(value){if(Array.isArray(value))return value.flatMap(nodes);if(!value||typeof value!=='object')return[];return[value,...nodes(value.props?.children)];}
    const button=()=>nodes(tree).find(n=>n.props?.['aria-label']==='提交研究卡核验');
    async function advance(ms){const target=now+ms;
      for(;;){const entry=[...timers].filter(([,t])=>t.at<=target).sort((a,b)=>a[1].at-b[1].at)[0];if(!entry)break;
        const [id,timer]=entry;now=timer.at;if(timer.interval)timer.at+=timer.interval;else timers.delete(id);
        timer.fn();await settle();}
      now=target;await settle();}
    try{
      await settle();
      await check({props,calls,submitted,opened,settle,advance,setTime:value=>{now=value;},emptyInputs:()=>{emptyInputs=true;},nodes:()=>nodes(tree),button,CitationLocations,fail:()=>{fail=true;},
        recover:()=>{fail=false;failLibrary=false;},hold:()=>{hold=true;},halfFailure:()=>{holdInputs=true;failLibrary=true;},
        release:()=>{hold=false;holdInputs=false;for(const resolve of releases.splice(0))resolve();},render:()=>{state.dirty=true;}});
    }finally{
      for(const slot of state.slots)slot?.cleanup?.();
      Date.now=original.now;Object.assign(globalThis,{setTimeout:original.setTimeout,clearTimeout:original.clearTimeout,
        setInterval:original.setInterval,clearInterval:original.clearInterval});
    }
  }finally{for(const slot of state.slots)slot?.cleanup?.();globalThis.__arCardHooks=previous;}
}
test('actual combined card consumer makes one GET without separate input or library requests',()=>scenario(async s=>{
  assert.deepEqual(s.calls,['/api/shared-workspace/research-card-query?page=0']);
  s.nodes().find(n=>n.props?.['aria-label']==='冻结研究卡').props.onChange({target:{value:'registered-card'}});await s.settle();
  assert.equal(s.button().props.disabled,false);
},false,true,true));
test('combined evidence expires after fifteen seconds despite a fresh parent and refuses retained actions',()=>scenario(async s=>{
  s.nodes().find(n=>n.props?.['aria-label']==='冻结研究卡').props.onChange({target:{value:'registered-card'}});await s.settle();
  const retained=s.button().props.onClick;s.hold();await s.advance(15000);
  assert.equal(s.button().props.disabled,false);
  s.props.parentFresh=()=>true;s.render();s.setTime(16001);await s.settle();retained();
  assert.equal(s.submitted.length,0);await s.advance(1000);assert.equal(s.button().props.disabled,true);
  s.release();await s.settle();await s.settle();assert.equal(s.button().props.disabled,false);
},false,true,true));
test('actual scoped card consumer uses V2 without a legacy input GET',()=>scenario(async s=>{
  assert.ok(s.calls.includes('/api/shared-workspace/research-card-inputs-scoped'));
  assert.ok(!s.calls.includes('/api/shared-workspace/research-card-inputs'));
  s.nodes().find(n=>n.props?.['aria-label']==='冻结研究卡').props.onChange({target:{value:'registered-card'}});await s.settle();
  assert.equal(s.button().props.disabled,false);
},false,true));
test('fresh scoped parent context cannot renew held card evidence or a retained action',()=>scenario(async s=>{
  s.nodes().find(n=>n.props?.['aria-label']==='冻结研究卡').props.onChange({target:{value:'registered-card'}});await s.settle();
  const retained=s.button().props.onClick;s.hold();await s.advance(15000);
  assert.equal(s.button().props.disabled,false);
  s.props.parentFresh=()=>true;s.render();s.setTime(16001);await s.settle();retained();
  assert.equal(s.submitted.length,0);await s.advance(1000);assert.equal(s.button().props.disabled,true);
  s.release();await s.settle();assert.equal(s.button().props.disabled,false);
},false,true));
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

test('a transient parent expiry does not discard the verified card selection after recovery',()=>scenario(async s=>{
  s.nodes().find(n=>n.props?.['aria-label']==='冻结研究卡').props.onChange({target:{value:'registered-card'}});await s.settle();
  assert.equal(s.button().props.disabled,false);
  const retained=s.button().props.onClick;
  s.props.parentStale=true;s.render();await s.settle();
  assert.equal(s.button().props.disabled,true);retained();
  assert.equal(s.submitted.length,0,'a retained handler cannot bypass current parent expiry');
  s.props.parentStale=false;s.render();await s.settle();
  assert.equal(s.button().props.disabled,false,'fresh context must recover without erasing a valid choice');
}));

test('card evidence expires independently at fifteen seconds and recovers after held verification',()=>scenario(async s=>{
  s.nodes().find(n=>n.props?.['aria-label']==='冻结研究卡').props.onChange({target:{value:'registered-card'}});await s.settle();
  const old=s.button().props.onClick;s.hold();await s.advance(15000);
  assert.equal(s.button().props.disabled,false,'the existing exact boundary remains valid');
  await s.advance(1000);assert.equal(s.props.parentStale,false);
  assert.equal(s.button().props.disabled,true);old();assert.equal(s.submitted.length,0);
  assert.equal(s.calls.length,4,'a held refresh must not create overlapping polls');
  s.release();await s.settle();assert.equal(s.button().props.disabled,false);
  s.button().props.onClick();assert.equal(s.submitted.length,1);
}));

test('a failed card verification recovers autonomously without a page refresh or automatic submission',()=>scenario(async s=>{
  s.nodes().find(n=>n.props?.['aria-label']==='冻结研究卡').props.onChange({target:{value:'registered-card'}});await s.settle();
  s.fail();await s.advance(5000);assert.equal(s.button().props.disabled,true);
  s.recover();await s.advance(5000);assert.equal(s.button().props.disabled,false);
  assert.equal(s.submitted.length,0);
}));

test('parent expiry while card verification is pending does not cancel progress',()=>scenario(async s=>{
  s.hold();await s.advance(5000);const calls=s.calls.length;
  s.props.parentStale=true;s.render();await s.settle();
  s.props.parentStale=false;s.render();await s.settle();
  assert.equal(s.calls.length,calls,'parent availability is not a new verification context');
  s.release();await s.settle();
  s.nodes().find(n=>n.props?.['aria-label']==='冻结研究卡').props.onChange({target:{value:'registered-card'}});await s.settle();
  assert.equal(s.button().props.disabled,false);
}));

test('a rejected paired read waits for its held sibling before scheduling another verification',()=>scenario(async s=>{
  s.nodes().find(n=>n.props?.['aria-label']==='冻结研究卡').props.onChange({target:{value:'registered-card'}});await s.settle();
  assert.equal(s.button().props.disabled,false);
  s.halfFailure();await s.advance(5000);
  assert.equal(s.button().props.disabled,true,'known validation failure must block before the sibling settles');
  await s.advance(5000);
  assert.equal(s.calls.length,4,'one rejected response cannot start overlapping input verifications');
  s.release();await s.settle();s.recover();await s.advance(5000);
  assert.ok(!JSON.stringify(s.nodes()).includes('HASH_CHANGED'));
}));

test('retained run callbacks use current busy state and verified input membership',()=>scenario(async s=>{
  s.nodes().find(n=>n.props?.['aria-label']==='冻结研究卡').props.onChange({target:{value:'registered-card'}});await s.settle();
  const old=s.button().props.onClick;s.props.busy=true;s.render();await s.settle();old();
  assert.equal(s.submitted.length,0);
  s.props.busy=false;s.emptyInputs();await s.advance(5000);old();
  assert.equal(s.button().props.disabled,true);assert.equal(s.submitted.length,0);
}));

test('explicit refreshes drain their predecessor instead of creating parallel verification pairs',()=>scenario(async s=>{
  s.hold();await s.advance(5000);assert.equal(s.calls.length,4);
  for(let i=0;i<3;i++){
    s.nodes().find(n=>n.props?.['aria-label']==='刷新研究卡').props.onClick();await s.settle();
    assert.equal(s.calls.length,4);
  }
  s.release();await s.settle();assert.equal(s.calls.length,6);
}));

test('draining a retired combined read does not consume the new request polling interval',()=>scenario(async s=>{
  await s.settle();s.hold();await s.advance(1000);
  assert.equal(s.calls.length,2);
  s.nodes().find(n=>n.props?.['aria-label']==='刷新研究卡').props.onClick();await s.settle();
  await s.advance(6000);assert.equal(s.calls.length,2,'new generation must drain the held predecessor');
  s.release();for(let i=0;i<8;i++)await s.settle();
  assert.equal(s.calls.length,3,'only the fresh intentional read starts');
  await s.advance(0);
  assert.equal(s.calls.length,3,'drain time cannot schedule another immediate automatic read');
  await s.advance(1000);assert.equal(s.calls.length,4);
},false,true,true));

test('slow combined proof yields one second before automatic renewal for intentional reads',()=>scenario(async s=>{
  await s.settle();s.hold();await s.advance(1000);assert.equal(s.calls.length,2);
  await s.advance(6000);s.release();for(let i=0;i<8;i++)await s.settle();
  await s.advance(0);
  assert.equal(s.calls.length,2,'slow HTTP including server admission must not create a zero-idle successor');
  await s.advance(1000);assert.equal(s.calls.length,3);
},false,true,true));

test('a disposed generation cannot apply a late rejection after an A B A context cycle',()=>scenario(async s=>{
  const original=s.props.api;let rejectOld,holdNext=true;
  s.props.api=async path=>{
    if(holdNext&&path.endsWith('/research-card-inputs')){holdNext=false;await new Promise((_,reject)=>{rejectOld=reject;});}
    return original(path);
  };
  s.props.refreshRevision++;s.render();await s.settle();
  s.props.codeSha='c'.repeat(40);s.render();await s.settle();
  s.props.codeSha='a'.repeat(40);s.render();await s.settle();
  rejectOld(new Error('DISPOSED_GENERATION_A'));await s.settle();await s.settle();
  assert.ok(!JSON.stringify(s.nodes()).includes('DISPOSED_GENERATION_A'));
  s.nodes().find(n=>n.props?.['aria-label']==='冻结研究卡').props.onChange({target:{value:'registered-card'}});await s.settle();
  assert.equal(s.button().props.disabled,false);
}));

test('populated open-job callbacks recheck parent expiry between timer renders',()=>scenario(async s=>{
  let parentSuccess=1000;s.props.parentFresh=()=>Date.now()-parentSuccess<=15000;
  await s.advance(15000);
  const open=s.nodes().find(n=>n.props?.['aria-label']?.startsWith('查看研究卡任务 '));
  assert.equal(open.props.disabled,false);
  const retained=open.props.onClick;s.setTime(16001);retained();
  assert.equal(s.opened.length,0,'parent freshness must be checked at action time');
  parentSuccess=16001;retained();assert.equal(s.opened.length,1);
  s.setTime(32000);retained();assert.equal(s.opened.length,1,'own evidence expiry also gates retained open-job callbacks');
},true));
