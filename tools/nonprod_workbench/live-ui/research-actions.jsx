import React,{useEffect,useRef,useState} from 'react';
import {Play,RefreshCw,Send} from 'lucide-react';
import {dateText} from '../daily-ui/view.mjs';
import {actionCurrent,matchingReview} from './live-state.mjs';
import {readPending,savePending,clearPending,validateCommentReceipt,definitiveReviewRejection,reviewLabels} from '../ui/review-portal-view.mjs';

export function StudySubmit({context,reads,query,busy,pending,onSubmit,onRetry}) {
  const [selected,setSelected]=useState(''),[notice,setNotice]=useState('');
  const key=JSON.stringify(context),live=useRef(null),posting=useRef(false);
  live.current={key,reads,query,busy,pending,selected,onSubmit,onRetry};
  useEffect(()=>{setSelected('');setNotice('');},[key]);
  const inputs=query?.registeredInputs?.inputs||[],chosen=inputs.find(row=>row.snapshot_id===selected);
  async function submit(){
    const current=live.current;
    // governance-mutation: DAILY_LIVE_SUBMIT_CLICK
    if(current.key!==key||!actionCurrent(current.reads,current.busy)||posting.current||current.pending||
      !current.query?.registeredInputs?.inputs.some(row=>row.snapshot_id===current.selected))return;
    posting.current=true;setNotice('正在登记任务');
    try{await current.onSubmit(current.selected);setNotice('任务已登记，请核对任务详情');}
    catch(error){setNotice(error.message);}
    finally{posting.current=false;}
  }
  async function retry(){
    const current=live.current;
    if(current.key!==key||!actionCurrent(current.reads,current.busy)||posting.current||!current.pending)return;
    posting.current=true;
    try{await current.onRetry();}catch(error){setNotice(error.message);}finally{posting.current=false;}
  }
  const current=actionCurrent(reads,busy);
  return <section className="study-submit"><div className="section-title"><h2>提交研究</h2><span className="secondary">冻结材料 · 流程核验</span></div>
    <div className="submit-fields"><label>材料<select aria-label="冻结研究材料" disabled={!current||busy||!!pending} value={selected} onChange={event=>setSelected(event.target.value)}>
      <option value="">选择已登记材料</option>{inputs.map(row=><option key={row.snapshot_id} value={row.snapshot_id}>{row.company} · {row.research_date}</option>)}</select></label>
      <button className="button dark" aria-label="提交研究" title="提交冻结研究核验" onClick={submit} disabled={!current||busy||!!pending||!chosen}><Play size={16}/>提交研究</button></div>
    {chosen&&<div className="source-caption">原件截止 {dateText(chosen.source_cutoff_at)} · 研究日 {dateText(chosen.research_date)} · 待人审</div>}
    {pending&&<div className="pending-command"><span>原提交待核对</span><code>{pending.body.command_id}</code><button className="text-button" aria-label="核对原提交" disabled={!current||busy} onClick={retry}><RefreshCw size={15}/>核对原提交</button></div>}
    {notice&&<p className="action-notice" role="status">{notice}</p>}
    {!current&&<p className="secondary">材料尚未核验或读取已过期，提交不可用。</p>}
  </section>;
}

export function CommentEditor({context,reads,row,detail,api,onSaved,storage=window.localStorage}) {
  const [item,setItem]=useState(''),[status,setStatus]=useState('ISSUE'),[severity,setSeverity]=useState('MAJOR');
  const [comment,setComment]=useState(''),[pending,setPending]=useState(null),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[storageError,setStorageError]=useState(false);
  const key=JSON.stringify([context,detail?.packet_hash,row?.pack_hash,row?.content_hash,row?.basis_hash]);
  const live=useRef(null),posting=useRef(false);
  live.current={key,context,reads,row,detail,item,status,severity,comment,pending,storageError};
  useEffect(()=>{
    setItem('');setComment('');setNotice('');setBusy(false);setStorageError(false);
    try{setPending(detail?readPending(storage,context,detail.packet_hash):null);}
    catch(error){setPending(null);setStorageError(true);setNotice('本地提交记录无法核验 · '+error.message);}
  },[key]);
  useEffect(()=>{
    if(!pending||!detail)return;
    const annotation=detail.annotations.find(value=>value.annotation_id===pending.command_id);
    if(!annotation)return;
    try{
      validateCommentReceipt({...reviewLabels,disposition:'IDEMPOTENT',annotation},context,pending);
      clearPending(storage,context,detail.packet_hash);setPending(null);setNotice('原批注已确认入库');
    }catch(error){setStorageError(true);setNotice(error.message);}
  },[detail,pending]);
  async function submit(retry=false){
    const current=live.current;
    // governance-mutation: DAILY_LIVE_COMMENT_CLICK
    if(current.key!==key||!actionCurrent(current.reads)||posting.current||current.storageError||!matchingReview(current.detail,current.row))return;
    const body=retry?current.pending:{command_id:'review_'+crypto.randomUUID().replaceAll('-',''),packet_hash:current.detail.packet_hash,
      item_id:current.item,expected_workspace_id:current.context.workspaceId,expected_code_sha:current.context.codeSha,
      status:current.status,severity:current.severity,comment:current.comment};
    if(!body||(!retry&&current.pending)||!current.detail.packet.items.some(value=>value.id===body.item_id)||!body.comment.trim())return;
    posting.current=true;setBusy(true);setNotice('正在保存批注');
    try{
      savePending(storage,current.context,current.detail.packet_hash,body);setPending(body);
      const receipt=validateCommentReceipt(await api('/api/shared-workspace/review-comment',body),current.context,body);
      if(live.current.key!==key)return;
      clearPending(storage,current.context,current.detail.packet_hash);setPending(null);setComment('');
      setNotice(receipt.disposition==='IDEMPOTENT'?'原批注已确认入库':'批注已入库 · 不代表研究通过');onSaved();
    }catch(error){
      if(live.current.key!==key)return;
      if(definitiveReviewRejection(error,retry)){
        try{clearPending(storage,current.context,current.detail.packet_hash);setPending(null);setNotice('批注被拒绝 · '+error.message);}
        catch(storageFailure){setStorageError(true);setNotice(storageFailure.message);}
      }else setNotice('提交尚未确认 · '+error.message);
    }finally{posting.current=false;if(live.current.key===key)setBusy(false);}
  }
  if(!matchingReview(detail,row))return <div className="quiet-notice">本研究暂无匹配且获准的审阅材料，批注未开放。</div>;
  const fresh=actionCurrent(reads),items=detail.packet.items;
  return <section className="comment-editor"><div className="section-title"><h2>批注</h2><span className="secondary">人工核验仍待完成</span></div>
    <div className="comment-filters"><label>核对事项<select aria-label="批注事项" value={item} disabled={busy||!!pending} onChange={event=>setItem(event.target.value)}><option value="">选择事项</option>{items.map(value=><option value={value.id} key={value.id}>{value.layer} · {value.title}</option>)}</select></label>
      <label>意见<select aria-label="批注意见" value={status} disabled={busy||!!pending} onChange={event=>setStatus(event.target.value)}>{[['ISSUE','存在问题'],['MATCH','与来源相符'],['NEEDS_SOURCE','需要来源'],['OUT_OF_SCOPE','不在范围']].map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label>
      <label>影响<select aria-label="批注影响" value={severity} disabled={busy||!!pending} onChange={event=>setSeverity(event.target.value)}>{[['NONE','无'],['MINOR','轻微'],['MAJOR','重要'],['BLOCKING','阻断']].map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label></div>
    {item&&<p className="secondary">{items.find(value=>value.id===item)?.prompt}</p>}
    <label>内容<textarea aria-label="批注内容" rows={4} maxLength={4000} disabled={busy||!!pending} value={comment} onChange={event=>setComment(event.target.value)}/></label>
    <div className="comment-submit"><span role="status">{notice||(!fresh?'读取已过期，提交不可用':'未提交')}</span><button className="button dark" title="提交批注" aria-label="提交批注" disabled={!fresh||busy||!!pending||storageError||!item||!comment.trim()} onClick={()=>submit(false)}><Send size={16}/>提交批注</button>
      {pending&&<button className="text-button" aria-label="重试原批注" disabled={!fresh||busy||storageError} onClick={()=>submit(true)}><RefreshCw size={16}/>重试原批注</button>}</div>
    <div className="annotation-list"><h3>已有批注 · {detail.annotations.length}</h3>{detail.annotations.map(value=><article key={value.annotation_id}><div><strong>{value.actor}</strong><span>{value.item_id} · {value.status} · {value.severity}</span></div><p>{value.comment}</p><span className="secondary">{new Date(value.at*1000).toLocaleString()} · 不代表研究批准</span></article>)}</div>
  </section>;
}
