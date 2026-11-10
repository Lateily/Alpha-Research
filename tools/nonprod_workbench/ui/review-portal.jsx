import React,{useEffect,useRef,useState} from 'react';
import {RefreshCw,Send} from 'lucide-react';
import {sharedRead} from './shared-view.mjs';
import {canSubmitReview,clearPending,definitiveReviewRejection,readPending,reviewLabels,savePending,validateCommentReceipt,validateReviewDetail,validateReviewList} from './review-portal-view.mjs';

export default function ReviewPortal({api,renew,login,workspaceId,codeSha,parentStale,refreshRevision}){
  const [selected,setSelected]=useState(''),[state,setState]=useState(null),[revision,setRevision]=useState(0);
  const [item,setItem]=useState(''),[status,setStatus]=useState('ISSUE'),[severity,setSeverity]=useState('MAJOR'),[comment,setComment]=useState('');
  const [pending,setPending]=useState(null),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false);
  const active=useRef(null),verified=useRef(null),posting=useRef(false),cycle=useRef({stale:parentStale,epoch:0});
  if(cycle.current.stale!==parentStale)cycle.current={stale:parentStale,epoch:cycle.current.epoch+1};
  const context={login,workspaceId,codeSha},identity=JSON.stringify(context);
  const key=JSON.stringify([identity,selected,refreshRevision,revision,cycle.current.epoch,parentStale]);active.current=key;
  const data=state?.identity===identity?state.data:null,detail=data?.detail,packet=detail?.packet;
  const stale=parentStale||state?.key!==key||state?.stale!==false;
  useEffect(()=>{setSelected('');setItem('');setComment('');setPending(null);setNotice('');setBusy(false);posting.current=false;},[identity]);
  useEffect(()=>{
    verified.current=null;let stopped=false;
    if(parentStale||!workspaceId||!codeSha)return;
    (async()=>{
      try{
        const listing=validateReviewList(await sharedRead(api,'/api/shared-workspace/reviews',renew),context);
        let detail=null,retained=null;
        if(selected){
          const row=listing.packets.find(r=>r.packet_hash===selected);if(!row)throw new Error('REVIEW_PACKET_UNAVAILABLE');
          detail=validateReviewDetail(await sharedRead(api,'/api/shared-workspace/review/'+selected,renew),context,selected);
          if(detail.grant_hash!==row.grant_hash||detail.packet.original_manifest_sha256!==row.manifest_sha256||detail.packet.packet_id!==row.packet_id)throw new Error('REVIEW_PIN_CHANGED');
          retained=readPending(window.localStorage,context,selected);
          if(retained&&detail.annotations.some(r=>r.annotation_id===retained.command_id)){
            validateCommentReceipt({...reviewLabels,disposition:'IDEMPOTENT',annotation:detail.annotations.find(r=>r.annotation_id===retained.command_id)},context,retained);
            clearPending(window.localStorage,context,selected);retained=null;
          }
        }
        if(!stopped&&active.current===key){verified.current=key;setState({identity,key,data:{listing,detail},stale:false,error:''});setPending(retained);}
      }catch(error){if(!stopped&&active.current===key){verified.current=null;setState(old=>({identity,key,data:old?.identity===identity?old.data:null,stale:true,error:error.message}));}}
    })();return()=>{stopped=true;if(verified.current===key)verified.current=null;};
  },[key]);
  function refresh(){verified.current=null;active.current=null;setRevision(n=>n+1);}
  function choose(value){verified.current=null;active.current=null;setSelected(value);setItem('');setComment('');setPending(null);setNotice('');}
  async function submit(retry=false){
    if(!canSubmitReview({stale,verifiedKey:verified.current,activeKey:active.current,requestKey:key,posting:posting.current,packet}))return;
    const body=retry?pending:{command_id:'review_'+crypto.randomUUID().replaceAll('-',''),packet_hash:selected,item_id:item,expected_workspace_id:workspaceId,expected_code_sha:codeSha,status,severity,comment};
    if(!body||(!retry&&pending)||!packet.items.some(r=>r.id===body.item_id)||!body.comment.trim())return;
    const token={};posting.current=token;setBusy(true);setNotice('SUBMITTING');
    try{
      savePending(window.localStorage,context,selected,body);setPending(body);
      const receipt=validateCommentReceipt(await api('/api/shared-workspace/review-comment',body),context,body);
      if(active.current!==key)return;
      clearPending(window.localStorage,context,selected);setPending(null);setComment('');setNotice(receipt.disposition);refresh();
    }catch(error){
      if(definitiveReviewRejection(error,retry)){
        try{clearPending(window.localStorage,context,selected);if(active.current===key){setPending(null);setNotice('REJECTED · '+error.message);}}
        catch(storageError){if(active.current===key)setNotice('LOCAL_RETRY_STATE_ERROR · '+storageError.message);}
      }else if(active.current===key)setNotice('SUBMISSION_UNCONFIRMED · '+error.message);
    }
    finally{if(posting.current===token){posting.current=false;setBusy(false);}}
  }
  return <section className="data-center review-portal">
    <div className="section-title"><h3>研究审阅</h3><div><span className="badge">{stale?'DISCONNECTED':'VERIFIED_BYTES'}</span><button className="icon-button" aria-label="刷新审阅" title="重新核验审阅材料" onClick={refresh}><RefreshCw size={17}/></button></div></div>
    <div className="source-strip"><span>WORKFLOW_DEBUG</span><span>人工核验 PENDING</span><span>原件正文 DENIED</span><span>生产 / 交易权限 false</span></div>
    {state?.error&&<div className="shared-error" role="alert">DISCONNECTED · {state.error}</div>}
    <label>审阅样稿<select aria-label="审阅样稿" value={selected} disabled={parentStale||busy} onChange={e=>choose(e.target.value)}><option value="">选择样稿</option>{(data?.listing.packets||[]).map(row=><option key={row.packet_hash} value={row.packet_hash}>{row.packet_id} · {row.packet_hash.slice(0,12)}</option>)}</select></label>
    {packet&&<>
      <dl className="input-card-fields">{[['样稿 hash',detail.packet_hash],['授权 hash',detail.grant_hash],['原输入 manifest SHA256',packet.original_manifest_sha256],['原件截止',packet.source_cutoff_at],['行情来源日',packet.daily_source_trade_date],['源稿生成时间',packet.source_draft_generated_at],['研究生产版本',packet.source_producer],['当前消费版本',codeSha]].map(([label,value])=><React.Fragment key={label}><dt>{label}</dt><dd><code>{value}</code></dd></React.Fragment>)}</dl>
      <details open><summary>研究样稿 · F 事实 / C 计算 / R 规则 / L 解释</summary><pre className="shared-report review-sample">{packet.sample}</pre></details>
      <details><summary>来源登记 · {packet.sources.length}</summary>{packet.sources.map(source=><section className="research-metadata" key={source.id}><h4>{source.title}</h4><code>{source.sha256}</code><div>物理页 {source.pages?.join(' / ')||'NOT_SUPPLIED'}</div><div>{source.published_at||'NOT_SUPPLIED'} · {source.captured_at||'NOT_SUPPLIED'}</div><div>来源真实性 UNVERIFIED · 原件权利 UNVERIFIED / PRIVATE</div>{source.registered_public_url&&<a href={source.registered_public_url} target="_blank" rel="noopener noreferrer">公开登记地址 · 未重新核实</a>}</section>)}</details>
      <details open><summary>缺数与待核验 · {packet.gaps.length}</summary><div className="table-scroll"><table><thead><tr><th>项目</th><th>状态</th><th>依据 / 缺项</th></tr></thead><tbody>{packet.gaps.map(row=><tr key={row.id}><td>{row.title}</td><td>{row.status}</td><td>{row.reason}</td></tr>)}</tbody></table></div></details>
      <div className="review-comment-form"><h4>新增批注</h4><div className="research-filters">
        <label>核对事项<select aria-label="批注事项" value={item} disabled={busy||!!pending} onChange={e=>setItem(e.target.value)}><option value="">选择事项</option>{packet.items.map(row=><option value={row.id} key={row.id}>{row.id} · {row.layer} · {row.title}</option>)}</select></label>
        <label>意见<select aria-label="批注意见" value={status} disabled={busy||!!pending} onChange={e=>setStatus(e.target.value)}>{['MATCH','ISSUE','NEEDS_SOURCE','OUT_OF_SCOPE'].map(v=><option key={v}>{v}</option>)}</select></label>
        <label>影响<select aria-label="批注影响" value={severity} disabled={busy||!!pending} onChange={e=>setSeverity(e.target.value)}>{['NONE','MINOR','MAJOR','BLOCKING'].map(v=><option key={v}>{v}</option>)}</select></label>
      </div><p>{packet.items.find(r=>r.id===item)?.prompt}</p><label>批注<textarea aria-label="批注内容" maxLength={4000} rows={4} value={comment} disabled={busy||!!pending} onChange={e=>setComment(e.target.value)}/></label>
      <div className="shared-toolbar"><span>{notice||'NOT_SUBMITTED'}</span><button className="icon-button" aria-label="提交批注" title="提交批注" disabled={stale||busy||!!pending||!item||!comment.trim()} onClick={()=>submit()}><Send size={17}/></button>{pending&&<button aria-label="重试原批注" disabled={stale||busy} onClick={()=>submit(true)}><RefreshCw size={17}/>重试原批注</button>}</div></div>
      <h4>团队批注 · {detail.annotations.length}</h4>{detail.annotations.map(row=><section className="research-metadata" key={row.annotation_id}><div className="source-strip"><code>{row.actor}</code><span>{row.item_id} · {row.status} · {row.severity}</span><span>{new Date(row.at*1000).toLocaleString()}</span><span>人工核验 PENDING</span></div><p className="review-comment-text">{row.comment}</p><code>{row.annotation_id}</code><code>{row.event_hash}</code></section>)}
    </>}
    {!packet&&<p className="shared-empty">{stale?'DISCONNECTED':data?.listing.packets.length?'NOT_SELECTED':'无获准审阅材料'}</p>}
  </section>;
}
