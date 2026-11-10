import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';
import {context,packetHash,list,detail,annotation} from './nonprod-review-portal.test.mjs';
import {reviewLabels} from '../tools/nonprod_workbench/ui/review-portal-view.mjs';

async function scenario(check){
  const state={slots:[],cursor:0,pending:[],dirty:true};
  const hooks={createElement:(type,props,...children)=>({type,props:{...props,children}}),Fragment:Symbol('Fragment'),
    useState(initial){const n=state.cursor++;if(!(n in state.slots))state.slots[n]=typeof initial==='function'?initial():initial;return[state.slots[n],v=>{state.slots[n]=typeof v==='function'?v(state.slots[n]):v;state.dirty=true;}];},
    useRef(v){const n=state.cursor++;return state.slots[n]||={current:v};},
    useEffect(fn,deps){const n=state.cursor++,old=state.slots[n];if(!old||deps.some((v,k)=>v!==old.deps[k]))state.pending.push(()=>{old?.cleanup?.();state.slots[n]={deps,cleanup:fn()};});}};
  const oldHooks=globalThis.__arReviewHooks,oldWindow=globalThis.window;globalThis.__arReviewHooks=hooks;
  const values=new Map();globalThis.window={localStorage:{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)}};
  try{
    const output=await build({entryPoints:['tools/nonprod_workbench/ui/review-portal.jsx'],bundle:true,write:false,format:'esm',platform:'node',plugins:[{name:'review-hooks',setup(b){
      b.onResolve({filter:/^react$/},()=>({path:'react',namespace:'hooks'}));b.onLoad({filter:/.*/,namespace:'hooks'},()=>({contents:'const h=globalThis.__arReviewHooks;export default h;export const {useState,useRef,useEffect}=h;'}));
      b.onResolve({filter:/^lucide-react$/},()=>({path:'icons',namespace:'icons'}));b.onLoad({filter:/.*/,namespace:'icons'},()=>({contents:'export const RefreshCw=()=>null,Send=()=>null;'}));
    }}]});
    const {default:Portal}=await import('data:text/javascript;base64,'+Buffer.from(output.outputFiles[0].text).toString('base64')+'#'+Math.random());
    let tree,fail=false,postFail=false,hold=false,release;const calls=[],posts=[];
    const props={...context,parentStale:false,refreshRevision:0,renew:async()=>{},api:async(path,body)=>{
      calls.push(path);if(body){posts.push(body);if(postFail)throw new Error('CONNECTION_LOST');return {...reviewLabels,disposition:'APPENDED',annotation:{...annotation(),...{annotation_id:body.command_id,comment:body.comment}}};}
      if(fail)throw new Error('PIN_CHANGED');if(hold)await new Promise(resolve=>{release=resolve;});return path.endsWith('/reviews')?list():detail();
    }};
    function nodes(v){if(Array.isArray(v))return v.flatMap(nodes);if(!v||typeof v!=='object')return[];return[v,...nodes(v.props?.children)];}
    async function settle(){for(let i=0;i<18;i++){if(state.dirty){state.cursor=0;state.dirty=false;tree=Portal(props);}while(state.pending.length)state.pending.shift()();await Promise.resolve();}}
    const find=label=>nodes(tree).find(n=>n.props?.['aria-label']===label);
    await settle();find('审阅样稿').props.onChange({target:{value:packetHash}});await settle();
    find('批注事项').props.onChange({target:{value:'F1'}});find('批注内容').props.onChange({target:{value:'口径需复核'}});await settle();
    await check({props,posts,calls,find,settle,nodes:()=>nodes(tree),render:()=>{state.dirty=true;},fail:()=>{fail=true;},postFail:()=>{postFail=true;},hold:()=>{hold=true;},release:()=>{hold=false;release?.();}});
  }finally{for(const slot of state.slots)slot?.cleanup?.();globalThis.__arReviewHooks=oldHooks;globalThis.window=oldWindow;}
}
test('actual review component renders sample as text and refuses retained submit after refresh',()=>scenario(async s=>{
  assert.ok(s.nodes().some(n=>n.type==='pre'&&JSON.stringify(n.props.children).includes('<script>')));
  assert.ok(!s.nodes().some(n=>n.props?.dangerouslySetInnerHTML));
  assert.equal(s.find('提交批注').props.disabled,false);const old=s.find('提交批注').props.onClick;
  s.fail();s.find('刷新审阅').props.onClick();old();await s.settle();old();assert.equal(s.posts.length,0);assert.equal(s.find('提交批注').props.disabled,true);
}));
test('actual review component fences account workspace version and parent expiry',async()=>{
  for(const [key,value] of [['login','owner'],['workspaceId','22222222-2222-4222-8222-222222222222'],['codeSha','c'.repeat(40)],['parentStale',true]])await scenario(async s=>{
    const old=s.find('提交批注').props.onClick;s.props[key]=value;s.render();await s.settle();old();assert.equal(s.posts.length,0);assert.equal(s.find('提交批注')?.props.disabled??true,true);
  });
});
test('uncertain submission retries the exact persisted command and ignores double click',()=>scenario(async s=>{
  s.postFail();const submit=s.find('提交批注').props.onClick;submit();submit();await s.settle();assert.equal(s.posts.length,1);
  s.find('重试原批注').props.onClick();await s.settle();assert.equal(s.posts.length,2);assert.deepEqual(s.posts[0],s.posts[1]);
  assert.ok(JSON.stringify(s.nodes()).includes('SUBMISSION_UNCONFIRMED'));
}));
test('a complete matching receipt confirms a successful submission and unlocks the form',()=>scenario(async s=>{
  s.find('提交批注').props.onClick();await s.settle();assert.equal(s.posts.length,1);
  assert.ok(JSON.stringify(s.nodes()).includes('APPENDED'));assert.equal(s.find('重试原批注'),undefined);
  assert.equal(s.find('批注内容').props.disabled,false);
}));
