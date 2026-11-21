import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';
import {readFile} from 'node:fs/promises';
import {resource} from '../tools/nonprod_workbench/live-ui/live-state.mjs';
import {reviewLabels} from '../tools/nonprod_workbench/ui/review-portal-view.mjs';

async function harness(name,check,mutant=null){
  const slots=[],effects=[];let cursor=0,dirty=true,tree,now=1000;
  const old=Date.now;Date.now=()=>now;
  const hooks={Fragment:Symbol('Fragment'),createElement:(type,props,...children)=>({type,props:{...props,children}}),
    useState(initial){const n=cursor++;if(!(n in slots))slots[n]=typeof initial==='function'?initial():initial;return[slots[n],value=>{slots[n]=typeof value==='function'?value(slots[n]):value;dirty=true;}];},
    useRef(initial){const n=cursor++;return slots[n]||=( {current:initial});},
    useEffect(fn,deps){const n=cursor++,old=slots[n];if(!old||deps.some((v,i)=>v!==old.deps[i]))effects.push(()=>{old?.cleanup?.();slots[n]={deps,cleanup:fn()};});}};
  globalThis.__dailyLiveHooks=hooks;
  try{
    const result=await build({entryPoints:['tools/nonprod_workbench/live-ui/research-actions.jsx'],bundle:true,write:false,format:'esm',platform:'node',plugins:[{name:'hooks',setup(b){
      if(mutant)b.onLoad({filter:/research-actions\.jsx$/},async args=>{
        const source=await readFile(args.path,'utf8');
        const pattern=mutant==='submit'?/\/\/ governance-mutation: DAILY_LIVE_SUBMIT_CLICK\s+if\(current\.key!==key\|\|!actionCurrent\(current\.reads,current\.busy\)[\s\S]*?return;/:/if\(current\.key!==key\|\|!actionCurrent\(current\.reads\)\|\|posting\.current\|\|current\.storageError\|\|!matchingReview\(current\.detail,current\.row\)\)return;/;
        assert.equal((source.match(new RegExp(pattern.source,'g'))||[]).length,1,'precise actual handler guard');
        return{contents:source.replace(pattern,'if(false)return;'),loader:'jsx'};
      });
      b.onResolve({filter:/^react$/},()=>({path:'react',namespace:'hooks'}));b.onLoad({filter:/.*/,namespace:'hooks'},()=>({contents:'const h=globalThis.__dailyLiveHooks;export default h;export const {useState,useRef,useEffect}=h;'}));
      b.onResolve({filter:/^lucide-react$/},()=>({path:'icons',namespace:'icons'}));b.onLoad({filter:/.*/,namespace:'icons'},()=>({contents:'export const Play=()=>null,RefreshCw=()=>null,Send=()=>null,Check=()=>null,ChevronRight=()=>null;'}));
    }}]});
    const module=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64')+'#'+Math.random());
    const c={login:'owner@example.com',workspaceId:'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',codeSha:'a'.repeat(40)};
    const identity=resource(()=>now),data=resource(()=>now);await identity.read('actor',async()=>c);await data.read('evidence',async()=>({ok:true}));
    const calls=[],storageMap=new Map(),storage={getItem:k=>storageMap.get(k)??null,setItem:(k,v)=>storageMap.set(k,v),removeItem:k=>storageMap.delete(k)};
    const props={context:c,reads:[[identity,'actor'],[data,'evidence']],query:{registeredInputs:{enabled:true,inputs:[{snapshot_id:'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',company:'603986.SH',research_date:'20261110',source_cutoff_at:'2026-10-04T23:59:59+08:00'}]}},busy:false,pending:null,onSubmit:async id=>calls.push(id),onRetry:async()=>calls.push('retry'),storage,
      row:{pack_hash:'p'.repeat(64),content_hash:'c'.repeat(64),basis_hash:'b'.repeat(64)},
      detail:{packet_hash:'d'.repeat(64),packet:{pack_hash:'p'.repeat(64),content_hash:'c'.repeat(64),basis_hash:'b'.repeat(64),items:[{id:'F01',title:'事实核对',layer:'F',prompt:'核对冻结来源'}]},annotations:[]},
      api:async(path,body)=>{calls.push({path,body});return{...reviewLabels,disposition:'APPENDED',annotation:{packet_hash:body.packet_hash,item_id:body.item_id,actor:c.login,workspace_id:c.workspaceId,code_sha:c.codeSha,status:body.status,severity:body.severity,comment:body.comment,human_review:'PENDING',research_approval:false,annotation_id:body.command_id,at:1,event_hash:'e'.repeat(64)}};},onSaved:()=>calls.push('saved')};
    const nodes=v=>Array.isArray(v)?v.flatMap(nodes):v&&typeof v==='object'?[v,...nodes(v.props?.children)]:[];
    async function settle(){for(let i=0;i<15;i++){if(dirty){cursor=0;dirty=false;tree=module[name](props);}while(effects.length)effects.shift()();await Promise.resolve();}}
    const find=label=>nodes(tree).find(n=>n.props?.['aria-label']===label);
    await settle();await check({props,calls,find,nodes:()=>nodes(tree),settle,at:n=>{now=n;},render:()=>{dirty=true;},identity,data,storageMap});
  }finally{for(const slot of slots)slot?.cleanup?.();Date.now=old;delete globalThis.__dailyLiveHooks;}
}
test('actual submit button uses selected frozen input once and rejects retained callback at exact expiry',()=>harness('StudySubmit',async s=>{
  assert.equal(s.find('提交研究').props.disabled,true);
  s.find('冻结研究材料').props.onChange({target:{value:s.props.query.registeredInputs.inputs[0].snapshot_id}});await s.settle();
  assert.equal(s.find('提交研究').props.disabled,false);const retained=s.find('提交研究').props.onClick;
  s.at(16000);await retained();assert.equal(s.calls.length,0);
  s.at(1000);await retained();assert.deepEqual(s.calls,[s.props.query.registeredInputs.inputs[0].snapshot_id]);
}));
test('actual submit refuses after version change and exposes explicit uncertain-command retry only',()=>harness('StudySubmit',async s=>{
  s.find('冻结研究材料').props.onChange({target:{value:s.props.query.registeredInputs.inputs[0].snapshot_id}});await s.settle();
  const retained=s.find('提交研究').props.onClick;s.props.context={...s.props.context,codeSha:'d'.repeat(40)};s.render();await s.settle();await retained();assert.equal(s.calls.length,0);
  s.props.pending={body:{command_id:'shared_12345678'}};s.render();await s.settle();assert.ok(s.find('核对原提交'));assert.equal(s.calls.length,0);
}));
test('actual comment handler rejects expired own evidence even with fresh identity and preserves human pending',()=>harness('CommentEditor',async s=>{
  s.find('批注事项').props.onChange({target:{value:'F01'}});s.find('批注内容').props.onChange({target:{value:'隔离工程核对，不是研究批准。'}});await s.settle();
  const retained=s.find('提交批注').props.onClick;s.at(16000);await s.identity.read('actor',async()=>s.props.context);await retained();assert.equal(s.calls.length,0);
  await s.data.read('evidence',async()=>({ok:true}));await retained();await s.settle();assert.equal(s.calls[0].path,'/api/shared-workspace/review-comment');assert.equal(s.calls[0].body.item_id,'F01');assert.equal(s.calls[1],'saved');
  assert.equal(s.storageMap.size,0);
}));
test('actual uncertain comment keeps the exact command for an explicit retry, never automatic POST',()=>harness('CommentEditor',async s=>{
  s.props.api=async(path,body)=>{s.calls.push({path,body});throw Error('NETWORK_UNCONFIRMED');};s.render();await s.settle();
  s.find('批注事项').props.onChange({target:{value:'F01'}});s.find('批注内容').props.onChange({target:{value:'请核对原来源。'}});await s.settle();await s.find('提交批注').props.onClick();await s.settle();
  assert.equal(s.calls.length,1);const original=s.calls[0].body;assert.ok(s.find('重试原批注'));
  await s.settle();assert.equal(s.calls.length,1);await s.find('重试原批注').props.onClick();await s.settle();assert.deepEqual(s.calls[1].body,original);
}));
test('mismatched review packet has no comment submit control',()=>harness('CommentEditor',async s=>{
  s.props.row={...s.props.row,basis_hash:'wrong'};s.render();await s.settle();assert.equal(s.find('提交批注'),undefined);
}));
test('removing the actual submit handler guard makes an expired retained click submit',()=>harness('StudySubmit',async s=>{
  s.find('冻结研究材料').props.onChange({target:{value:s.props.query.registeredInputs.inputs[0].snapshot_id}});await s.settle();
  const retained=s.find('提交研究').props.onClick;s.at(16000);await retained();assert.equal(s.calls.length,1);
},'submit'));
test('removing the actual comment handler guard makes an expired retained click POST',()=>harness('CommentEditor',async s=>{
  s.find('批注事项').props.onChange({target:{value:'F01'}});s.find('批注内容').props.onChange({target:{value:'工程反例'}});await s.settle();
  const retained=s.find('提交批注').props.onClick;s.at(16000);await retained();await s.settle();assert.equal(s.calls[0].path,'/api/shared-workspace/review-comment');
},'comment'));
test('actual evidence drawer rechecks its own live source on retained download; removing it is detected',async()=>{
  const original={now:Date.now,document:globalThis.document,create:URL.createObjectURL,revoke:URL.revokeObjectURL};
  let downloads=0,now=1000,allowed=false;
  Date.now=()=>now;globalThis.document={createElement:()=>({click(){downloads++;}})};URL.createObjectURL=()=> 'blob:isolated-test';URL.revokeObjectURL=()=>{};
  globalThis.__dailyDrawerHooks={createElement:(type,props,...children)=>({type,props:{...props,children}}),Fragment:Symbol('fragment'),useRef:()=>({current:null}),useEffect:()=>{},useState:()=>{throw Error('unexpected state');}};
  try{
    for(const mutate of [false,true]){
      const result=await build({entryPoints:['tools/nonprod_workbench/daily-ui/app.jsx'],bundle:true,write:false,format:'esm',platform:'node',plugins:[{name:'drawer',setup(b){
        b.onLoad({filter:/daily-ui\/app\.jsx$/},async args=>{let source=await readFile(args.path,'utf8');if(mutate){assert.equal(source.split('||!canRead()').length,2);source=source.replace('||!canRead()','');}return{contents:source,loader:'jsx'};});
        b.onResolve({filter:/^react$/},()=>({path:'react',namespace:'h'}));b.onLoad({filter:/.*/,namespace:'h'},()=>({contents:'const h=globalThis.__dailyDrawerHooks;export default h;export const {useRef,useEffect,useState}=h;'}));
        b.onResolve({filter:/^lucide-react$/},()=>({path:'icons',namespace:'i'}));b.onLoad({filter:/.*/,namespace:'i'},()=>({contents:'export const '+['Activity','ArrowDownToLine','ArrowLeft','ArrowRight','BarChart3','Check','ChevronDown','ChevronRight','Clock3','FileCheck2','FileSearch','FileText','FlaskConical','FolderOpen','Home','Info','Layers3','LockKeyhole','PanelLeftClose','RefreshCw','Search','ShieldCheck','Wallet','X'].map(name=>name+'=()=>null').join(',')+';'}));
      }}]});
      const {Drawer}=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64')+'#'+Math.random());
      const tree=Drawer({entry:{title:'任务证据',value:{sample_purpose:'WORKFLOW_DEBUG'}},fresh:true,lastSuccessAt:1000,canRead:()=>allowed,onClose:()=>{}});
      const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
      const click=nodes(tree).find(value=>value.props?.label==='下载许可元数据').props.onClick;
      now=1000;allowed=false;const before=downloads;click();assert.equal(downloads-before,mutate?1:0);
      if(!mutate){allowed=true;click();assert.equal(downloads,before+1);now=16000;click();assert.equal(downloads,before+1);}
    }
  }finally{Date.now=original.now;globalThis.document=original.document;URL.createObjectURL=original.create;URL.revokeObjectURL=original.revoke;delete globalThis.__dailyDrawerHooks;}
});
