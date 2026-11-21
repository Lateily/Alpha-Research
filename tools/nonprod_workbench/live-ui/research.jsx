import React,{useEffect,useState} from 'react';
import {ArrowLeft,ArrowRight,ChevronLeft,ChevronRight,FileText,FolderOpen,RefreshCw,Search,ShieldCheck} from 'lucide-react';
import {Status,SectionTitle,Empty,EvidenceLink,Subtabs,PageHeading,TaskRows,ReportDetail} from '../daily-ui/app.jsx';
import {dateText,filterReports,groupReports,titleFor} from '../daily-ui/view.mjs';
import {sharedRead} from '../ui/shared-view.mjs';
import {validateReviewList,validateReviewDetail} from '../ui/review-portal-view.mjs';
import {cardTaskEvidence} from '../ui/research-cards-view.mjs';
import {matchingReview,queryFilters,captureProofs} from './live-state.mjs';
import {useRead} from './use-read.jsx';
import {StudySubmit,CommentEditor} from './research-actions.jsx';

export const industryName=value=>({semiconductor:'半导体',chip:'芯片'})[value]||value||'未分类';

function StudyReview({context,reads,row,api,renew,enabled,onEvidence}) {
  const key=enabled&&row?JSON.stringify(['review',context,row.pack_hash,row.content_hash,row.basis_hash]):null;
  const review=useRead(key,async()=>{
    const listing=validateReviewList(await sharedRead(api,'/api/shared-workspace/reviews',renew),context);
    const matches=[];
    for(const item of listing.packets){
      const detail=validateReviewDetail(await sharedRead(api,'/api/shared-workspace/review/'+item.packet_hash,renew),context,item.packet_hash);
      if(detail.grant_hash!==item.grant_hash||detail.packet.original_manifest_sha256!==item.manifest_sha256||detail.packet.packet_id!==item.packet_id)throw Error('REVIEW_PIN_CHANGED');
      if(matchingReview(detail,row))matches.push(detail);
    }
    if(matches.length>1)throw Error('REVIEW_PACKET_AMBIGUOUS');
    return {detail:matches[0]||null};
  });
  if(!enabled)return <Empty title="当前身份未开放审阅"/>;
  const detail=review.data?.detail;
  const proofs=captureProofs([...reads,[review.reader,key]]);
  return <section className="study-review"><div className="section-title"><h2>审阅与批注</h2><button className="icon-button" title="刷新审阅材料" aria-label="刷新审阅材料" onClick={review.refresh}><RefreshCw size={16}/></button></div>
    {!review.fresh&&<div className="quiet-notice warning">{review.state.error||'审阅材料正在核验或读取已过期'} · 写入不可用</div>}
    {detail?<><details className="review-sample"><summary>获准审阅样稿 · F 事实 / C 计算 / R 规则 / L 解释</summary><pre>{detail.packet.sample}</pre></details>
      <details className="review-sources"><summary>来源与缺项 · {detail.packet.sources.length} 项来源 / {detail.packet.gaps.length} 项缺口</summary>
        {detail.packet.sources.map(item=><div className="material-row" key={item.id}><div><strong>{item.title}</strong><p>物理页 {item.pages?.join(' / ')||'未提供'} · 来源真实性待核验</p></div><EvidenceLink onClick={()=>onEvidence('来源登记',item,proofs)}/></div>)}
        {detail.packet.gaps.map(item=><div className="review-gap" key={item.id}><strong>{item.title}</strong><Status value={item.status}/><p>{item.reason}</p></div>)}
      </details>
      <CommentEditor key={key} context={context} reads={[...reads,[review.reader,key]]} row={row} detail={detail} api={api} onSaved={review.refresh}/>
    </>:review.data&&<Empty title="本研究暂无匹配且获准的审阅样稿"/>}
  </section>;
}

export function LiveResearch({model,onEvidence}) {
  const tab=model.researchTab,setTab=model.setResearchTab;
  const [localQuery,setLocalQuery]=useState('');
  const applied=()=>({industry:model.filters.industry_key||'',date:model.filters.research_date?model.filters.research_date.slice(0,4)+'-'+model.filters.research_date.slice(4,6)+'-'+model.filters.research_date.slice(6):'',ticker:model.filters.ts_code||''});
  const [draft,setDraft]=useState(applied),[filterError,setFilterError]=useState('');
  useEffect(()=>setDraft(applied()),[JSON.stringify(model.filters)]);
  const {context,contextRead,cards,history,selected,detail,api,renew}=model;
  const library=cards.data,inputs=library?.registeredInputs?.inputs||[],rows=library?.results||[];
  const visible=groupReports(filterReports(rows.map(row=>({...row,industry_label:industryName(row.industry_key)})),{query:localQuery})).map(group=>group.row);
  const industries=[...new Set([...inputs,...rows].map(row=>row.industry_key).filter(Boolean))];
  // Retain verified historical bytes during a slow read; every action still uses live own-read guards.
  const data=detail.data,evidence=selected?cardTaskEvidence(data,{jobId:selected,stale:false}):null;
  const row=evidence?{...data.research_cards,job_id:data.job_id,workspace_id:data.workspace_id,actor:data.actor,
    submitted_at:data.submitted_at,code_sha:data.code_sha,input_hash:data.input_hash}:null;
  const [panel,setPanel]=useState('result');
  useEffect(()=>setPanel('result'),[selected]);
  function search(event){event.preventDefault();try{model.query(queryFilters(draft));setFilterError('');}catch(error){setFilterError(error.message);}}
  if(selected)return <>
    <button className="text-button back-button" onClick={()=>model.open(null)}><ArrowLeft size={16}/>研究</button>
    <div className="task-current"><div><span className="eyebrow">研究任务</span><strong>{selected}</strong></div><Status value={detail.fresh?data?.status:'STALE'}/><button className="icon-button" aria-label="刷新任务" title="刷新任务" onClick={detail.refresh}><RefreshCw size={16}/></button></div>
    {!detail.fresh&&<div className="quiet-notice warning">{detail.state.error||'任务正在核验或读取已过期'} · 以下内容不作为当前核验结果</div>}
    {data&&<div className="source-caption">{data.actor} · 执行版本 {data.code_sha?.slice(0,7)} · 人工核验 PENDING</div>}
    {row?<><Subtabs label="任务内容" value={panel} onChange={setPanel} items={[["result","研究结果"],["review","批注"]]}/>
      {panel==='result'?<ReportDetail key={selected} row={row} data={{task_details:{[selected]:data}}} fresh={detail.fresh} onBack={()=>model.open(null)} onEvidence={onEvidence}/>
        :<StudyReview context={context} reads={[...model.parentReads,[detail.reader,detail.key]]} row={row} api={api} renew={renew} enabled={model.access.review_portal_enabled===true} onEvidence={onEvidence}/>}
      <button className="text-button" aria-label="按本任务回查结果" onClick={()=>{setDraft({industry:row.industry_key,date:row.research_date.slice(0,4)+'-'+row.research_date.slice(4,6)+'-'+row.research_date.slice(6),ticker:row.company});model.query({industry_key:row.industry_key,research_date:row.research_date,ts_code:row.company});setTab('results');}}>按行业／日期／股票回查<ArrowRight size={16}/></button>
    </>:data?<><Empty title={data.status==='SUCCEEDED'?'任务证据不可用':data.status==='RUNNING'?'研究核验进行中':data.status==='QUEUED'?'任务已排队':'任务未完成'} detail={data.error||'完成后显示核验步骤、引用及入库状态。'}/><EvidenceLink onClick={()=>onEvidence('任务登记元数据',data)}/></>:<Empty title="正在读取任务详情"/>}
  </>;
  return <>
    <PageHeading eyebrow="工作空间 / 研究" title="研究"><p>冻结材料、核验任务与研究结果</p></PageHeading>
    {context&&<StudySubmit key={JSON.stringify(context)} context={context} reads={model.actionReads} query={library} busy={model.busy} pending={model.pending} onSubmit={model.submit} onRetry={model.retry}/>}
    <Subtabs label="研究内容" value={tab} onChange={setTab} items={[["results","研究结果"],["tasks","任务记录"],["materials","材料"]]}/>
    {!cards.fresh&&<div className="quiet-notice warning">{cards.state.error||'研究材料正在核验或读取已过期'} · 提交和下载不可用</div>}
    {tab==='results'&&<>
      <form className="research-toolbar server-filters" onSubmit={search}><label>行业<select aria-label="行业" value={draft.industry} onChange={event=>setDraft({...draft,industry:event.target.value})}><option value="">全部行业</option>{industries.map(value=><option value={value} key={value}>{industryName(value)}</option>)}</select></label>
        <label>研究日<input aria-label="研究日期" type="date" value={draft.date} onChange={event=>setDraft({...draft,date:event.target.value})}/></label>
        <label>股票<input aria-label="股票代码" placeholder="603986.SH" value={draft.ticker} maxLength={20} onChange={event=>setDraft({...draft,ticker:event.target.value})}/></label>
        <button className="icon-button" type="submit" aria-label="查询研究结果" title="按行业、研究日和股票查询"><Search size={17}/></button></form>
      {filterError&&<p role="alert" className="read-error">{filterError}</p>}
      <div className="list-meta"><span>{library?visible.length+' 份研究':'研究待核验'} · {library?.total??'—'} 条核验记录</span><label className="search-field compact"><Search size={15}/><input aria-label="搜索已载入研究" placeholder="搜索已载入结果" value={localQuery} onChange={event=>setLocalQuery(event.target.value)}/></label></div>
      <div className="reports-list">{visible.map(item=><button className="report-row" key={item.job_id} disabled={!cards.fresh} onClick={()=>model.open(item.job_id)}><span className="report-name"><span className="document-icon small"><FileText size={19}/></span><span><strong>{item.company}</strong><small>{industryName(item.industry_key)} · {item.job_id.slice(0,8)}</small></span></span><span>{dateText(item.research_date)}</span><Status value={item.human_review}/><span className="report-gap">缺少依据<ArrowRight size={16}/></span></button>)}</div>
      {!visible.length&&<Empty icon={Search} title={library?'没有匹配的研究结果':'正在核验研究结果'}/>}
      <div className="result-pagination"><button className="icon-button" aria-label="上一页结果" title="上一页" disabled={!model.page} onClick={()=>model.setPage(model.page-1)}><ChevronLeft size={16}/></button><span>{model.page+1} / {Math.max(1,Math.ceil((library?.total||0)/50))}</span><button className="icon-button" aria-label="下一页结果" title="下一页" disabled={!library||(model.page+1)*50>=library.total} onClick={()=>model.setPage(model.page+1)}><ChevronRight size={16}/></button></div>
    </>}
    {tab==='tasks'&&<><div className="section-title"><h2>任务记录</h2><button className="icon-button" title="刷新任务列表" aria-label="刷新任务列表" onClick={history.refresh}><RefreshCw size={16}/></button></div>
      {!history.fresh&&<div className="quiet-notice warning">{history.state.error||'列表核验中或已过期'}</div>}
      <TaskRows jobs={history.data?.team_jobs||[]} onOpen={job=>job.kind==='research-cards-review'?model.open(job.job_id):onEvidence(titleFor(job),job)}/>
      <div className="result-pagination"><button className="icon-button" title="上一页任务" aria-label="上一页任务" disabled={!model.historyPage} onClick={()=>model.setHistoryPage(model.historyPage-1)}><ChevronLeft size={16}/></button><span>{model.historyPage+1} / {Math.max(1,Math.ceil((history.data?.team_total||0)/50))}</span><button className="icon-button" title="下一页任务" aria-label="下一页任务" disabled={!history.data||(model.historyPage+1)*50>=history.data.team_total} onClick={()=>model.setHistoryPage(model.historyPage+1)}><ChevronRight size={16}/></button></div>
    </>}
    {tab==='materials'&&<section><SectionTitle title="已登记材料" count={library?inputs.length:'待核验'}/>{inputs.map(item=><div className="material-row" key={item.snapshot_id}><span className="document-icon"><FolderOpen size={22}/></span><div><h3>{item.company}</h3><p>{industryName(item.industry_key)} · 研究日 {dateText(item.research_date)} · 原件截止 {dateText(item.source_cutoff_at)}</p><span className="secondary">原件正文未开放</span></div><EvidenceLink onClick={()=>onEvidence('已登记冻结材料',item)}/></div>)}</section>}
  </>;
}
