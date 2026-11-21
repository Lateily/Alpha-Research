import { isFresh } from '../daily-ui/view.mjs';
import { sharedRead } from '../ui/shared-view.mjs';
import { cardTaskEvidence } from '../ui/research-cards-view.mjs';

const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const sha=/^[a-f0-9]{40}$/;
const command=/^[A-Za-z0-9_-]{8,100}$/;
const states=['QUEUED','RUNNING','SUCCEEDED','STOP','INTERRUPTED','RECOVERY_REQUIRED','FAILED','CANCELLED'];
const need=(ok,message)=>{if(!ok)throw Error(message);};

export function resource(clock=Date.now) {
  let current={key:null,data:null,at:null,error:'',loading:false},epoch=0,inFlight=null,revision=0;
  const subscribers=new Set();
  function update(next){current=next;for(const listener of subscribers)listener();}
  const reader={
    value:()=>current,
    subscribe(fn){subscribers.add(fn);return()=>subscribers.delete(fn);},
    fresh(key){return current.key===key&&current.data!==null&&!current.error&&isFresh(current.at,clock());},
    capture(key){return reader.fresh(key)?Object.freeze({reader,key,revision,at:current.at}):null;},
    owns(proof){return proof?.reader===reader&&proof.revision===revision&&reader.fresh(proof.key)&&isFresh(proof.at,clock());},
    invalidate(retain=false){++epoch;++revision;update(retain?{...current,at:null,error:'',loading:false}:{key:null,data:null,at:null,error:'',loading:false});},
    read(key,loader){
      if(current.key!==key){++epoch;++revision;update({key,data:null,at:null,error:'',loading:false});}
      const token=epoch;
      if(inFlight?.token===token)return inFlight.promise;
      const previous=inFlight?.promise||Promise.resolve(),owned={token};
      inFlight=owned;
      owned.promise=(async()=>{
        await previous;
        if(epoch!==token)return;
        update({...current,loading:true});
        try{
          const data=await loader();
          if(epoch===token){
            if(current.error||JSON.stringify(data)!==JSON.stringify(current.data))++revision;
            update({key,data,at:clock(),error:'',loading:false});
          }
        }catch(error){
          if(epoch===token){++revision;update({...current,at:null,error:error.message||'READ_FAILED',loading:false});}
        }finally{if(inFlight===owned)inFlight=null;}
      })();
      return owned.promise;
    }
  };
  return reader;
}

export const captureProofs=reads=>reads.map(([reader,key])=>reader.capture(key));
export const proofsCurrent=proofs=>Array.isArray(proofs)&&proofs.length>0&&proofs.every(proof=>proof?.reader.owns(proof));

export function actionCurrent(reads,busy=false) {
  // governance-mutation: DAILY_LIVE_ACTION_FRESH
  return !busy&&reads.length>0&&reads.every(([read,key])=>read.fresh(key));
}
function identity(c){return typeof c?.login==='string'&&c.login.length>0&&c.login.length<=254&&!/[\s\x00-\x1f]/.test(c.login)&&uuid.test(c.workspaceId)&&sha.test(c.codeSha);}
export function cardCommand(c,selected,id,reads,query) {
  need(actionCurrent(reads),'EVIDENCE_NOT_CURRENT');
  need(identity(c)&&command.test(id),'COMMAND_CONTEXT_INVALID');
  need(query?.registeredInputs?.enabled===true&&query.registeredInputs.inputs.some(row=>row.snapshot_id===selected),'INPUT_NOT_SELECTED');
  return {command_id:id,kind:'research-cards-review',snapshot_id:selected,expected_workspace_id:c.workspaceId,expected_code_sha:c.codeSha};
}
export function requestReceipt(v) {
  need(v&&Object.keys(v).sort().join('|')==='disposition|job_id|status'&&uuid.test(v.job_id)&&states.includes(v.status)&&['CREATED','IDEMPOTENT'].includes(v.disposition),'SUBMISSION_RECEIPT_INVALID');
  return v;
}
export async function readJob(api,id,renew) {
  need(uuid.test(id),'TASK_ID_INVALID');
  const value=await sharedRead(api,'/api/shared-workspace/jobs/'+id,renew);
  need(value?.job_id===id&&value.kind==='research-cards-review'&&states.includes(value.status)&&value.sample_purpose==='WORKFLOW_DEBUG'&&
    value.human_review==='PENDING'&&value.production_authority===false&&value.trading_authority===false,'TASK_EVIDENCE_INVALID');
  if(value.status==='SUCCEEDED')need(cardTaskEvidence(value,{jobId:id,stale:false}),'TASK_EVIDENCE_INVALID');
  else{
    const keys='job_id command_id workspace_id actor kind snapshot_id input_hash source_run_id source_trade_date submitted_at code_sha source_tree_hash schema_version status attempt_id output_hash error sample_purpose human_review production_authority trading_authority result'.split(' ').sort();
    const digest=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
    const errorCode=value=>typeof value==='string'&&/^[A-Z][A-Z0-9_]{0,199}$/.test(value);
    need(Object.keys(value).sort().join('|')===keys.join('|')&&identity({login:value.actor,workspaceId:value.workspace_id,codeSha:value.code_sha})&&
      command.test(value.command_id)&&uuid.test(value.snapshot_id)&&digest(value.input_hash)&&digest(value.source_tree_hash)&&
      value.schema_version==='ar.shared-workspace.v1'&&value.source_run_id===null&&value.source_trade_date===null&&
      Number.isFinite(value.submitted_at)&&value.submitted_at>=0&&(value.attempt_id===null||uuid.test(value.attempt_id))&&
      (value.status!=='RUNNING'||uuid.test(value.attempt_id))&&(value.output_hash===null||digest(value.output_hash))&&
      (value.error===null||errorCode(value.error))&&(value.result===null||
        Object.keys(value.result).join('|')==='error'&&errorCode(value.result.error)),'TASK_EVIDENCE_INVALID');
  }
  return value;
}
export function pendingStore(storage,c) {
  need(identity(c),'COMMAND_CONTEXT_INVALID');
  const key='ar.daily.card.pending.v1:'+JSON.stringify([c.login,c.workspaceId,c.codeSha]);
  function validBody(body){
    need(body&&Object.keys(body).sort().join('|')==='command_id|expected_code_sha|expected_workspace_id|kind|snapshot_id'&&
      command.test(body.command_id)&&body.kind==='research-cards-review'&&uuid.test(body.snapshot_id)&&
      body.expected_workspace_id===c.workspaceId&&body.expected_code_sha===c.codeSha,'PENDING_COMMAND_INVALID');
  }
  function read(){
    const raw=storage.getItem(key);if(raw===null)return null;
    need(raw.length<=20000,'PENDING_COMMAND_INVALID');
    const row=JSON.parse(raw);need(row&&Object.keys(row).sort().join('|')==='body|job_id','PENDING_COMMAND_INVALID');
    validBody(row.body);need(row.job_id===null||uuid.test(row.job_id),'PENDING_COMMAND_INVALID');return row;
  }
  return {read,save(body,job_id=null){
    validBody(body);need(job_id===null||uuid.test(job_id),'PENDING_COMMAND_INVALID');
    const prior=read();
    need(!prior||JSON.stringify(prior.body)===JSON.stringify(body),'PENDING_COMMAND_EXISTS');
    const raw=JSON.stringify({body,job_id:job_id||prior?.job_id||null});storage.setItem(key,raw);
    need(storage.getItem(key)===raw,'PENDING_COMMAND_NOT_PERSISTED');
  },clear(){storage.removeItem(key);need(storage.getItem(key)===null,'PENDING_COMMAND_NOT_CLEARED');}};
}
export function matchingReview(detail,row) {
  // governance-mutation: DAILY_LIVE_REVIEW_BINDING
  return !!detail?.packet&&!!row&&['pack_hash','content_hash','basis_hash'].every(key=>
    typeof row[key]==='string'&&row[key].length>0&&detail.packet[key]===row[key]);
}
export function queryFilters({industry='',date='',ticker=''}={}) {
  const out={};industry=industry.trim();date=date.trim().replaceAll('-','');ticker=ticker.trim().toUpperCase();
  if(industry){need(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$/.test(industry),'INDUSTRY_KEY_INVALID');out.industry_key=industry;}
  if(date){
    const iso=date.slice(0,4)+'-'+date.slice(4,6)+'-'+date.slice(6);
    const d=new Date(iso+'T00:00:00Z');
    need(/^\d{8}$/.test(date)&&!date.startsWith('0000')&&Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===iso,'RESEARCH_DATE_INVALID');out.research_date=date;
  }
  if(ticker){need(/^\d{6}\.(?:SH|SZ|BJ)$/.test(ticker),'EXACT_TICKER_REQUIRED');out.ts_code=ticker;}
  return out;
}
export async function apiRequest(fetcher,path,body) {
  need(typeof path==='string'&&/^\/api\/[A-Za-z0-9_/?=&.%+-]+$/.test(path)&&!path.includes('..'),'API_PATH_REFUSED');
  if(body!==undefined)need(['/api/workspace/job','/api/shared-workspace/review-comment'].includes(path),'API_WRITE_REFUSED');
  const response=await fetcher(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',redirect:'error',
    ...(body===undefined?{}:{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
  const data=await response.json();
  if(!response.ok){const error=Error(data.error||'HTTP_'+response.status);error.status=response.status;throw error;}
  return data;
}
export async function readSharedSnapshot(api,c,page,renew) {
  const data=await sharedRead(api,'/api/shared-workspace?page='+page,renew);
  const validRows=rows=>Array.isArray(rows)&&rows.length<=50&&new Set(rows.map(row=>row.job_id)).size===rows.length&&rows.every(row=>command.test(row.job_id)&&
    row.sample_purpose==='WORKFLOW_DEBUG'&&row.human_review==='PENDING'&&row.production_authority===false&&row.trading_authority===false);
  need(data?.schema==='ar.shared-workspace.v1'&&data.my_workspace?.login===c.login&&data.my_workspace.workspace_id===c.workspaceId&&
    data.execution_identity?.code_sha===c.codeSha&&/^[a-f0-9]{64}$/.test(data.execution_identity.source_tree_hash)&&
    data.sample_purpose==='WORKFLOW_DEBUG'&&data.human_review==='PENDING'&&data.production_authority===false&&data.trading_authority===false&&
    data.page===page&&data.page_size===50&&validRows(data.my_jobs)&&validRows(data.team_jobs)&&
    [data.my_total,data.team_total].every(value=>Number.isSafeInteger(value)&&value>=0)&&data.common_data&&typeof data.common_data==='object','SHARED_HISTORY_INVALID');
  return data;
}
