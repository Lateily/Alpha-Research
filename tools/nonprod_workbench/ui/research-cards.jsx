import React, { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, FileSearch, Play, RefreshCw, Search } from 'lucide-react';
import { canRunCard, cardsContextKey, cardsView, readCardInputs, readCardLibrary } from './research-cards-view.mjs';
import { createSharedPoller } from './shared-view.mjs';
import { statusTone } from './status-tone.mjs';

export default function ResearchCards({api,renew,login,workspaceId,codeSha,parentStale,refreshRevision,onRun,onOpenJob,busy}) {
  const [draft,setDraft]=useState({industry_key:'',research_date:'',ts_code:''});
  const [filters,setFilters]=useState({}),[page,setPage]=useState(0),[selected,setSelected]=useState('');
  const [state,setState]=useState(null),reader=useRef(null),active=useRef(null);
  const cycle=useRef({stale:parentStale,epoch:0});
  if(cycle.current.stale!==parentStale)cycle.current={stale:parentStale,epoch:cycle.current.epoch+1};
  const epoch=JSON.stringify([refreshRevision,cycle.current.epoch]);
  const context={login,workspaceId,codeSha,filters,page},key=cardsContextKey(context),requestKey=JSON.stringify([key,epoch]);
  active.current=requestKey;
  const view=cardsView(state,key,parentStale,epoch),data=view.data;
  const choices=!view.stale?data?.registeredInputs?.inputs||[]:[];
  const selectedInput=choices.find(row=>row.snapshot_id===selected);
  useEffect(()=>{setSelected('');},[login,workspaceId,codeSha,epoch]);
  useEffect(()=>{
    if(!codeSha||!workspaceId||parentStale){reader.current=null;return;}
    const current=createSharedPoller({
      read:async()=>{const inputs=await readCardInputs(api,context,renew);const library=await readCardLibrary(api,context,renew);return {...library,registeredInputs:inputs};},
      apply:data=>{if(active.current===requestKey)setState({key,verificationEpoch:epoch,data,stale:false,error:''});},
      fail:error=>{if(active.current===requestKey)setState(old=>({key,verificationEpoch:epoch,data:old?.key===key?old.data:null,stale:true,error:error.message}));},
      schedule:()=>null,cancel:()=>{}
    });
    reader.current=current;current.refresh();
    return()=>{current.stop();if(reader.current===current)reader.current=null;};
  },[requestKey,parentStale]);
  const badge=value=><span className={`badge ${statusTone(view.stale?'DISCONNECTED':value==='BREAK'?'DATA_BLOCKED':value)}`}>{view.stale?'DISCONNECTED':value}</span>;
  function submit(event){
    event.preventDefault();const next={...draft,research_date:draft.research_date.replaceAll('-','')};
    setPage(0);setFilters(next);
    // governance-mutation: SHARED_CARDS_QUERY_REFRESH
    if(cardsContextKey({...context,filters:next,page:0})===key)reader.current?.refresh();
  }
  function run(){
    if(!canRunCard({activeKey:active.current,requestKey,stale:view.stale,busy,selected:selectedInput}))return;
    onRun({snapshot_id:selectedInput.snapshot_id,workspace_id:workspaceId,code_sha:codeSha});
  }
  return <div className="data-center research-library">
    <div className="section-title"><h3>研究卡</h3><div>{badge(view.status)}<button className="icon-button" aria-label="刷新研究卡" title="重新核验研究卡" onClick={()=>reader.current?.refresh()}><RefreshCw size={17}/></button></div></div>
    <div className="source-strip"><span>WORKFLOW_DEBUG</span><span>人工核验 PENDING</span><span>正文分发 DENIED</span><code>{view.hashStatus}</code></div>
    {view.error&&<div className="shared-error" role="alert">DISCONNECTED · {view.error}</div>}
    <div className="research-filters"><label>冻结研究卡<select aria-label="冻结研究卡" value={selected} onChange={event=>setSelected(event.target.value)}><option value="">选择研究卡包</option>{choices.map(row=><option key={row.snapshot_id} value={row.snapshot_id}>{row.company} · {row.research_date} · {row.content_hash.slice(0,12)}</option>)}</select></label><button className="icon-button" aria-label="提交研究卡核验" title="提交研究卡核验" disabled={busy||view.stale||!selectedInput} onClick={run}><Play size={18}/></button></div>
    {selectedInput&&<dl className="input-card-fields"><dt>输入 hash</dt><dd><code>{selectedInput.input_hash}</code></dd><dt>原件截止</dt><dd><code>{selectedInput.source_cutoff_at}</code></dd><dt>研究稿生成</dt><dd><code>{selectedInput.artifact_generated_at}</code></dd></dl>}
    <form className="research-filters" onSubmit={submit}>{[['industry_key','行业','text'],['research_date','研究日','date'],['ts_code','股票代码','text']].map(([key,label,type])=><label key={key}>{label}<input type={type} maxLength={128} value={draft[key]} onChange={event=>setDraft({...draft,[key]:event.target.value})}/></label>)}<button className="icon-button" title="查询研究卡" aria-label="查询研究卡" type="submit"><Search size={17}/></button></form>
    <div className="source-strip"><span>{data?.total??'NOT_CHECKED'} 项</span></div>
    {(data?.results||[]).map(row=><section className="research-metadata" key={row.job_id}>
      <div className="section-title"><h4>{row.company} · {row.research_date}</h4><button className="icon-button" disabled={view.stale} title="查看研究卡任务" aria-label={`查看研究卡任务 ${row.job_id}`} onClick={()=>onOpenJob(row.job_id)}><FileSearch size={17}/></button></div>
      <div className="source-strip">{badge(row.human_review)}{badge(row.archive_status)}<span>{row.actor}</span><code>{row.job_id}</code></div>
      <dl className="input-card-fields">{[['原件截止',row.source_cutoff_at],['研究稿生成',row.artifact_generated_at],['输入 hash',row.input_hash],['报告 SHA256',row.report_sha256],['产物来源版本',row.content_producer.code_sha],['任务执行版本',row.code_sha]].map(([name,value])=><React.Fragment key={name}><dt>{name}</dt><dd><code>{value}</code></dd></React.Fragment>)}</dl>
      <div className="table-scroll"><table><thead><tr><th>研究卡</th><th>状态</th><th>缺口 / 核验</th></tr></thead><tbody>
        <tr><td>事实回应</td><td>{badge(row.cards.facts.status)}</td><td>{row.cards.facts.observation_count} 条数字引用 · {row.cards.facts.calculation_count} 项计算<code>{JSON.stringify(row.cards.facts.assessment_counts)}</code></td></tr>
        <tr><td>正常化估值</td><td>{badge(row.cards.valuation.status)}</td><td><div>EPS {row.cards.valuation.normalized_eps_status}</div><div>净现金 {row.cards.valuation.net_cash_status}</div><div>合理倍数 {row.cards.valuation.fair_multiple_status}</div><div>价值带 {row.cards.valuation.value_band_status}</div><code>{row.cards.valuation.missing_normalization_assumptions.join(' · ')}</code><code>{row.cards.valuation.missing_cash_components.join(' · ')}</code></td></tr>
        <tr><td>日线技术</td><td>{badge(row.cards.daily.status)}{badge(row.cards.daily.continuity_status)}</td><td><code>{row.cards.daily.source_trade_date||'NOT_SUPPLIED'}</code><span>{row.cards.daily.vintage_status}</span><code>{row.cards.daily.reason_codes.join(' · ')}</code><div>eligible false</div></td></tr>
        <tr><td>执行反馈</td><td>{badge(row.cards.execution_feedback.status)}</td><td>{row.cards.execution_feedback.pnl_status}</td></tr>
      </tbody></table></div>
    </section>)}
    {!data?.results.length&&<p className="shared-empty">{view.error?'UNAVAILABLE':data?'无匹配研究卡':'WAIT'}</p>}
    <div className="shared-pagination"><button className="icon-button" title="上一页研究卡" aria-label="上一页研究卡" disabled={!page} onClick={()=>setPage(page-1)}><ChevronLeft size={17}/></button><span>{page+1} / {Math.max(1,Math.ceil((data?.total||0)/50))}</span><button className="icon-button" title="下一页研究卡" aria-label="下一页研究卡" disabled={!data||(page+1)*50>=data.total} onClick={()=>setPage(page+1)}><ChevronRight size={17}/></button></div>
  </div>;
}
