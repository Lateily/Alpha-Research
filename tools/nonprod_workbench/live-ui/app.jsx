import React,{useEffect,useRef,useState} from 'react';
import {Activity,ChevronRight,FileSearch,FlaskConical,Home,LockKeyhole,RefreshCw,ShieldCheck,Wallet} from 'lucide-react';
import {DailyView,Drawer,Empty,IconButton} from '../daily-ui/app.jsx';
import {destinations,dateText,isFresh} from '../daily-ui/view.mjs';
import {readSharedContext} from '../ui/shared-view.mjs';
import {readCardQuery} from '../ui/research-cards-view.mjs';
import {apiRequest,actionCurrent,cardCommand,pendingStore,readJob,requestReceipt,readSharedSnapshot} from './live-state.mjs';
import {useRead} from './use-read.jsx';
import {LiveResearch} from './research.jsx';

const icons={today:Home,research:FileSearch,holdings:Wallet,macro:Activity,tests:FlaskConical};
const api=(path,body)=>apiRequest(fetch,path,body);
async function renew(){const response=await fetch('/',{credentials:'same-origin',cache:'no-store',redirect:'error'});if(!response.ok)throw Error('SESSION_RENEWAL_FAILED');}
const routeFromHash=()=>destinations.some(item=>item.id===location.hash.slice(1))?location.hash.slice(1):'today';

export default function LiveApp(){
  const [route,setRoute]=useState(routeFromHash),[filters,setFilters]=useState({}),[page,setPage]=useState(0),[historyPage,setHistoryPage]=useState(0);
  const [selected,setSelected]=useState(null),[pending,setPending]=useState(null),[busy,setBusy]=useState(false),[notice,setNotice]=useState(''),[evidence,setEvidence]=useState(null),[researchTab,setResearchTab]=useState('results');
  const [,tick]=useState(0),posting=useRef(false),live=useRef(null),completed=useRef(null);
  const auth=useRead('access',async()=>{
    let data;
    try{data=await api('/api/state');}catch(error){if(error.status!==403)throw error;await renew();data=await api('/api/state');}
    if(data.access?.shared_workspace_v1!==true||typeof data.access.login!=='string'||!Array.isArray(data.access.allowed_job_kinds))throw Error('PRIVATE_SHARED_ACCESS_REQUIRED');
    return data.access;
  });
  const login=auth.data?.login,contextKey=login?'context:'+login:null;
  const contextRead=useRead(contextKey,()=>readSharedContext(api,{login},renew));
  const identity=contextRead.data;
  const context=identity?{login,workspaceId:identity.my_workspace.workspace_id,codeSha:identity.execution_identity.code_sha}:null;
  const identityKey=JSON.stringify(context);
  const needsCards=route==='today'||(route==='research'&&!selected);
  const needsHistory=['today','holdings','macro'].includes(route)||(route==='research'&&!selected&&researchTab==='tasks');
  const cardsKey=context&&needsCards?JSON.stringify(['cards',context,filters,page]):null;
  const cards=useRead(cardsKey,()=>readCardQuery(api,{...context,filters,page},renew));
  const historyKey=context&&needsHistory?JSON.stringify(['history',context,historyPage]):null;
  const history=useRead(historyKey,()=>readSharedSnapshot(api,context,historyPage,renew));
  const detailKey=context&&selected?JSON.stringify(['task',context,selected]):null;
  const detail=useRead(detailKey,async()=>{
    const value=await readJob(api,selected,renew);
    const retained=pendingStore(window.localStorage,context).read();
    if(retained?.job_id===selected&&[value.command_id===retained.body.command_id,value.actor===context.login,
      value.workspace_id===context.workspaceId,value.snapshot_id===retained.body.snapshot_id,
      value.code_sha===retained.body.expected_code_sha].some(ok=>!ok))throw Error('SUBMITTED_TASK_BINDING_MISMATCH');
    return value;
  });
  const actionReads=[[auth.reader,auth.key],[contextRead.reader,contextRead.key],[cards.reader,cards.key]];
  live.current={context,identityKey,actionReads,cards,contextRead,selected};
  useEffect(()=>{const timer=setInterval(()=>tick(value=>value+1),1000);return()=>clearInterval(timer);},[]);
  useEffect(()=>{const listener=()=>setRoute(routeFromHash());addEventListener('hashchange',listener);return()=>removeEventListener('hashchange',listener);},[]);
  useEffect(()=>{
    setSelected(null);setEvidence(null);setNotice('');setPending(null);completed.current=null;
    if(!context)return;
    try{setPending(pendingStore(window.localStorage,context).read());}catch(error){setNotice(error.message);}
  },[identityKey]);
  useEffect(()=>{
    if(!context||!detail.fresh||!detail.data)return;
    const value=detail.data;
    try{
      const store=pendingStore(window.localStorage,context),retained=store.read();
      if(retained?.job_id===value.job_id&&['SUCCEEDED','STOP','INTERRUPTED','RECOVERY_REQUIRED','FAILED','CANCELLED'].includes(value.status)){
        store.clear();setPending(null);
      }
    }catch(error){setNotice(error.message);}
    const signature=value.status==='SUCCEEDED'?value.job_id+':'+value.output_hash:null;
    if(signature&&completed.current!==signature){completed.current=signature;cards.refresh();history.refresh();}
  },[detail.data]);
  function navigate(id){location.hash=id;setRoute(id);setEvidence(null);window.scrollTo({top:0,behavior:'instant'});}
  function open(id){setSelected(id);setEvidence(null);navigate('research');}
  function query(next){setFilters(next);setPage(0);setSelected(null);if(JSON.stringify(next)===JSON.stringify(filters)&&page===0)cards.refresh();}
  async function submit(snapshotId){
    const current=live.current;
    if(posting.current||!current.context)throw Error('SUBMISSION_BUSY');
    const body=cardCommand(current.context,snapshotId,'shared_'+crypto.randomUUID().replaceAll('-',''),current.actionReads,current.cards.data);
    const store=pendingStore(window.localStorage,current.context);
    if(store.read())throw Error('PENDING_COMMAND_EXISTS');
    store.save(body);setPending(store.read());posting.current=true;setBusy(true);setNotice('');
    try{
      const receipt=requestReceipt(await api('/api/workspace/job',body));
      store.save(body,receipt.job_id);
      if(live.current.identityKey!==current.identityKey)return;
      setPending(store.read());open(receipt.job_id);
    }catch(error){if(live.current.identityKey===current.identityKey)setNotice('提交尚未确认 · '+error.message);throw error;}
    finally{posting.current=false;if(live.current.identityKey===current.identityKey)setBusy(false);}
  }
  async function retry(){
    const current=live.current;
    if(posting.current||!current.context||!actionCurrent(current.actionReads))throw Error('EVIDENCE_NOT_CURRENT');
    const store=pendingStore(window.localStorage,current.context),retained=store.read();
    if(!retained)throw Error('PENDING_COMMAND_NOT_FOUND');
    posting.current=true;setBusy(true);
    try{
      const known=retained.job_id||current.contextRead.data?.owned_commands?.[retained.body.command_id]?.job_id;
      if(known){store.save(retained.body,known);if(live.current.identityKey===current.identityKey){setPending(store.read());open(known);}return;}
      const confirmed=cardCommand(current.context,retained.body.snapshot_id,retained.body.command_id,current.actionReads,current.cards.data);
      if(JSON.stringify(confirmed)!==JSON.stringify(retained.body))throw Error('PENDING_COMMAND_CHANGED');
      const receipt=requestReceipt(await api('/api/workspace/job',retained.body));store.save(retained.body,receipt.job_id);
      if(live.current.identityKey===current.identityKey){setPending(store.read());open(receipt.job_id);}
    }finally{posting.current=false;if(live.current.identityKey===current.identityKey)setBusy(false);}
  }
  const observation=history.data?.common_data?.observation;
  const source={source_trade_date:observation?.target_trade_date||null,source_run_id:observation?.published_run_id||null,
    observed_at:observation?.observed_at||null,scope:history.data?.common_data?.validation_scope||'NOT_EVALUATED'};
  const historyRows=history.data?.team_jobs||cards.data?.results?.map(row=>({...row,kind:'research-cards-review'}))||[];
  const presentation={mode:'AUTHENTICATED_SHARED',consumer_code_sha:context?.codeSha,source,
    shared:history.data||{team_jobs:historyRows,team_total:cards.data?.total||0,loaded_results_only:true},
    cards:{library:cards.data||{results:[]},inputs:cards.data?.registeredInputs||{inputs:[]}},task_details:detail.data?{[detail.data.job_id]:detail.data}:{},
    macro:observation?Object.fromEntries(Object.entries(observation.macro||{}).filter(([,value])=>value?.payload).map(([name,value])=>[name,value.payload])):null,
    portfolio:observation?.paper?{data:observation.paper,target_trade_date:observation.target_trade_date,data_quality:'NOT_SUPPLIED'}:null,
    acceptance:null};
  const contextFresh=auth.fresh&&contextRead.fresh;
  const viewFresh=route==='research'?contextFresh&&(selected?detail.fresh:cards.fresh):['holdings','macro'].includes(route)?contextFresh&&history.fresh:route==='tests'?contextFresh:contextFresh&&cards.fresh&&history.fresh;
  const model={context,contextRead,cards,history,selected,detail,api,renew,access:auth.data||{},actionReads,parentReads:[[auth.reader,auth.key],[contextRead.reader,contextRead.key]],busy,pending,submit,retry,query,open,page,setPage,historyPage,setHistoryPage,researchTab,setResearchTab,filters};
  function refresh(){auth.refresh();contextRead.refresh();cards.refresh();history.refresh();if(selected)detail.refresh();}
  function openEvidence(title,value,reads){
    const bindings=reads||[[auth.reader,auth.key],[contextRead.reader,contextRead.key],
      route==='research'?(selected?[detail.reader,detail.key]:[cards.reader,cards.key]):[history.reader,history.key]];
    const times=bindings.map(([reader])=>reader.value().at);
    const at=times.every(Number.isFinite)?Math.min(...times):null;
    setEvidence({title,value,reads:bindings,at});
  }
  const evidenceFresh=()=>!!evidence&&isFresh(evidence.at)&&actionCurrent(evidence.reads);
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><span className="brand-mark">AR</span><div><strong>研究工作台</strong><small>Alpha Research</small></div></div>
    <div className="workspace-name"><span className="workspace-avatar">{login?.[0]?.toUpperCase()||'—'}</span><span title={login||'未连接'}>{login||'身份核验中'}</span><LockKeyhole size={13}/></div>
    <div className="nav-caption">工作空间</div><nav className="primary-nav" aria-label="主导航">{destinations.map(item=>{const Icon=icons[item.id];return <button key={item.id} aria-current={route===item.id?'page':undefined} onClick={()=>navigate(item.id)}><Icon size={19} strokeWidth={1.7}/><span>{item.label}</span>{route===item.id&&<span className="nav-active-dot"/>}</button>;})}</nav>
    <div className="sidebar-footer"><div><span className="preview-dot"/>私网研究</div><span>生产与交易权限未开放</span><button className="text-button" onClick={()=>openEvidence('运行与来源证据',{context:identity,source,shared_sync:history.data?.common_data},[[auth.reader,auth.key],[contextRead.reader,contextRead.key],[history.reader,history.key]])}><ShieldCheck size={15}/>证据与版本</button></div></aside>
    <div className="workspace-main"><header className="topbar"><span className="mobile-brand">AR <strong>研究工作台</strong></span><span className="breadcrumb">工作空间<ChevronRight size={13}/>{destinations.find(item=>item.id===route)?.label}</span><div className="topbar-right"><span className={`connection ${contextFresh?'connected':''}`}><i/>{contextFresh?'已连接':'连接核验中'}</span><code className="version-short">{context?.codeSha.slice(0,7)||'未核验'}</code><IconButton label="刷新工作台" onClick={refresh}><RefreshCw size={16}/></IconButton></div></header>
      <main><div className="preview-banner"><span><LockKeyhole size={13}/>WORKFLOW_DEBUG · 待人审</span><span>发布来源 {dateText(source.source_trade_date)}</span></div>
        {(auth.state.error||contextRead.state.error||notice)&&<div className="read-error" role="alert">{notice||auth.state.error||contextRead.state.error}</div>}
        {context?route==='research'?<LiveResearch model={model} onEvidence={openEvidence}/>:<DailyView key={route} route={route} data={presentation} fresh={viewFresh} navigate={navigate} onEvidence={openEvidence} onOpenJob={open}/>:<Empty title={auth.state.error||contextRead.state.error?'共享工作台暂时无法核验':'正在核验私网身份'}/>}
        {!viewFresh&&context&&<div className="read-error" role="status">相关资料尚未核验或读取已过期，不能作为当前核验结果。</div>}
        <footer className="page-footer"><span>AR / 研究信号，非买卖指令</span><span>人工研究批准独立保留</span></footer>
      </main></div>
    {evidence&&<Drawer entry={evidence} fresh={evidenceFresh()} lastSuccessAt={evidence.at} canRead={evidenceFresh} onClose={()=>setEvidence(null)}/>}
  </div>;
}
