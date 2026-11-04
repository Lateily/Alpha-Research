import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';
import { readFile } from 'node:fs/promises';

async function componentScenario(mutant = false) {
  const runtime = { active: null, instances: new Map(), pending: [] };
  const hooks = {
    createElement: (type, props, ...children) => ({type,props:{...props,children}}), Fragment: Symbol('Fragment'),
    useState(initial) { const i=runtime.active,n=i.cursor++;if(!(n in i.slots))i.slots[n]=typeof initial==='function'?initial():initial;
      return [i.slots[n],v=>{i.slots[n]=typeof v==='function'?v(i.slots[n]):v;}]; },
    useRef(initial) {const i=runtime.active,n=i.cursor++;return i.slots[n] ||= {current:initial};},
    useEffect(fn,deps) {const i=runtime.active,n=i.cursor++,old=i.slots[n];if(!old||deps.some((v,k)=>v!==old.deps[k]))
      runtime.pending.push(()=>{old?.cleanup?.();i.slots[n]={deps,cleanup:fn()};});}
  };
  const old={hooks:globalThis.__arLibraryHooks,window:globalThis.window,setTimeout:globalThis.setTimeout,clearTimeout:globalThis.clearTimeout};
  globalThis.__arLibraryHooks=hooks;
  try {
    const bundle=await build({entryPoints:['tools/nonprod_workbench/ui/shared-workspace.jsx'],bundle:true,write:false,format:'esm',platform:'node',
      plugins:[{name:'component-hooks',setup(b){
        if(mutant)b.onLoad({filter:/shared-workspace\.jsx$/},async args=>{
          const source=await readFile(args.path,'utf8'),before='refreshRevision={`${refreshRevision}:${libraryRefreshRevision}`}';
          assert.equal(source.split(before).length,2,'counterexample requires the actual parent-child refresh binding');
          return {contents:source.replace(before,'refreshRevision={refreshRevision}'),loader:'jsx'};
        });
        b.onResolve({filter:/^react$/},()=>({path:'react',namespace:'hooks'}));
        b.onLoad({filter:/.*/,namespace:'hooks'},()=>({contents:'const h=globalThis.__arLibraryHooks;export default h;export const {useState,useRef,useEffect}=h;'}));
        b.onResolve({filter:/^lucide-react$/},()=>({path:'icons',namespace:'icons'}));
        b.onLoad({filter:/.*/,namespace:'icons'},()=>({contents:'export const ChevronLeft=()=>null,ChevronRight=()=>null,Database=()=>null,Download=()=>null,FileText=()=>null,Library=()=>null,Play=()=>null,RefreshCw=()=>null,Users=()=>null,X=()=>null,FileSearch=()=>null,Search=()=>null;'}));
      }}]});
    const {default:SharedWorkspace}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
    const timers=new Map();let nextTimer=0;
    globalThis.setTimeout=callback=>{timers.set(++nextTimer,callback);return nextTimer;};
    globalThis.clearTimeout=id=>timers.delete(id);
    globalThis.window={setInterval:()=>null,clearInterval:()=>{},localStorage:{getItem:()=>null,setItem:()=>{}}};
    const calls=[];let parentFails=false,libraryFails=false;
    const props={access:{login:'owner'},refreshRevision:0,api:async path=>{
      calls.push(path);
      if(path.startsWith('/api/shared-workspace/research-library')){
        if(libraryFails)throw new Error('SYNTHETIC_LIBRARY_MISSING');
        return {schema:'ar.shared-research-library.v1',my_workspace:{login:'owner'},consumer_code_sha:'a'.repeat(40),library_hash:'b'.repeat(64),
          status:'EMPTY',total:0,page:0,page_size:50,results:[],query:{industry_key:null,industry_taxonomy:null,taxonomy_version:null,research_date:null,ts_code:null},
          human_review:'PENDING',production_authority:false,paper_authority:false,u4_authority:false,trading_authority:false,
          content_sharing_allowed:false,content_status:'RIGHTS_UNVERIFIED_CONTENT_DENIED',
          rights:{status:'UNVERIFIED',visibility:'PRIVATE',sharing_allowed:false,model_use_allowed:false}};
      }
      if(parentFails)throw new Error('SYNTHETIC_PARENT_OFFLINE');
      return {my_workspace:{login:'owner',workspace_id:'synthetic'},execution_identity:{code_sha:'a'.repeat(40)},
        common_data:{},owned_commands:{},my_jobs:[],team_jobs:[]};
    }};
    function nodes(tree,result=[]){if(Array.isArray(tree))for(const n of tree)nodes(n,result);else if(tree&&typeof tree==='object'){
      result.push(tree);nodes(tree.props?.children,result);}return result;}
    function render(fn,p,name){const i=runtime.instances.get(name)||{slots:[]};runtime.instances.set(name,i);i.cursor=0;
      runtime.active=i;const tree=fn(p);runtime.active=null;return tree;}
    let tree,child,childTree;
    async function settle(){for(let n=0;n<10;n++){tree=render(SharedWorkspace,props,'parent');
      child=nodes(tree).find(v=>v.type?.name==='ResearchLibrary');if(child)childTree=render(child.type,child.props,'child');
      for(const effect of runtime.pending.splice(0))effect();await Promise.resolve();await Promise.resolve();}}
    const reads=()=>calls.filter(path=>path.includes('/research-library')).length;
    const header=()=>nodes(tree).find(v=>v.type==='button'&&v.props['aria-label']==='刷新共享工作区');
    async function parentTick(){assert.equal(timers.size,1,'only the parent has a scheduled poll');
      const [id,callback]=[...timers.entries()][0];timers.delete(id);callback();await settle();}
    await settle();nodes(tree).find(v=>v.type==='button'&&v.props.children.includes('研究资料库')).props.onClick();await settle();
    const before=reads();header().props.onClick();await settle();
    assert.equal(reads()-before,1,'header refresh must reverify the mounted library');
    parentFails=true;await parentTick();
    const disconnected=reads();parentFails=false;libraryFails=true;await parentTick();
    assert.ok(reads()>disconnected,'parent recovery must initiate its own library verification');
    const text=JSON.stringify(childTree);
    assert.ok(text.includes('DISCONNECTED')&&text.includes('SYNTHETIC_LIBRARY_MISSING'),
      'a healthy parent cannot clear stale library status after its independent read fails');
  } finally {
    for(const i of runtime.instances.values())for(const slot of i.slots)slot?.cleanup?.();
    globalThis.__arLibraryHooks=old.hooks;globalThis.window=old.window;
    globalThis.setTimeout=old.setTimeout;globalThis.clearTimeout=old.clearTimeout;
  }
}

test('actual shared refresh handler revalidates the mounted research component', () => componentScenario());
test('dropping actual parent-child refresh binding fails by behavior, not a source-string assertion', async () => {
  await assert.rejects(componentScenario(true), error => error.code === 'ERR_ASSERTION' && error.actual === 0 && error.expected === 1);
});
