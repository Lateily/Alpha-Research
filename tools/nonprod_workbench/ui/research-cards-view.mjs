import { sharedRead } from './shared-view.mjs';
import { libraryView } from './research-library-view.mjs';

const filters=['industry_key','industry_taxonomy','taxonomy_version','research_date','ts_code'];
const authorities=['production_authority','paper_authority','u4_authority','trading_authority'];
const labels={sample_purpose:'WORKFLOW_DEBUG',human_review:'PENDING',content_sharing_allowed:false,
  content_status:'RIGHTS_UNVERIFIED_CONTENT_DENIED',production_authority:false,paper_authority:false,
  u4_authority:false,trading_authority:false,prospective_sample_eligible:false,network_calls:0,model_calls:0,
  claim_allowed:false,no_trade_flag:true};
const commonKeys=['schema','my_workspace','consumer_code_sha',...Object.keys(labels)];
const hash=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const code=v=>typeof v==='string'&&/^[a-f0-9]{40}$/.test(v);
const text=v=>typeof v==='string'&&v.length>0&&v.length<=200;
const login=v=>typeof v==='string'&&/^[a-z0-9.!#$%&'*+/=?^_\x60{|}~-]{1,128}@[a-z0-9.-]{1,125}$/.test(v)&&v.trim()===v;
const commandId=v=>typeof v==='string'&&/^[A-Za-z0-9_-]{8,100}$/.test(v)&&v.trim()===v;
const ticker=v=>typeof v==='string'&&/^\d{6}\.(?:SH|SZ|BJ)$/.test(v)&&v.trim()===v;
function date(v){
  if(typeof v!=='string'||v.length!==8||!/^\d{8}$/.test(v)||v.startsWith('0000'))return false;
  const iso=v.slice(0,4)+'-'+v.slice(4,6)+'-'+v.slice(6);
  const parsed=new Date(iso+'T00:00:00Z');
  return Number.isFinite(parsed.getTime())&&parsed.toISOString().slice(0,10)===iso;
}
const exact=(v,keys)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join('|')===[...keys].sort().join('|');
const identity=v=>exact(v,['code_sha','source_tree_hash'])&&code(v.code_sha)&&hash(v.source_tree_hash);
const array=(v,max=96)=>Array.isArray(v)&&v.length<=max;
const forbidden=new Set(['report','questions','excerpt','citations','artifact_files','pack_files','path','worksheet',
  'observations','responses','normalized_eps','net_cash_per_share','fair_multiple_low','fair_multiple_high','value_band']);
function safe(v,depth=0){
  if(depth>12)return false;
  if(v&&typeof v==='object')return Object.entries(v).every(([key,value])=>!forbidden.has(key)&&safe(value,depth+1));
  return typeof v!=='string'||v.length<=256;
}
function common(v,c){return v&&safe(v)&&exact(v.my_workspace,['login','workspace_id'])&&
  Object.entries(labels).every(([key,value])=>v[key]===value)&&
  v.my_workspace?.login===c.login&&v.my_workspace?.workspace_id===c.workspaceId&&
  v.consumer_code_sha===c.codeSha&&code(c.codeSha)&&v.sample_purpose==='WORKFLOW_DEBUG'&&v.human_review==='PENDING'&&
  v.content_sharing_allowed===false&&v.content_status==='RIGHTS_UNVERIFIED_CONTENT_DENIED'&&authorities.every(k=>v[k]===false);}
function metadata(row){return row&&ticker(row.company)&&date(row.research_date)&&
  [row.source_cutoff_at,row.artifact_generated_at].every(instant)&&
  Date.parse(row.source_cutoff_at)<=Date.parse(row.artifact_generated_at)&&
  new Date(Date.parse(row.artifact_generated_at)+8*3600000).toISOString().slice(0,10).replaceAll('-','')===row.research_date&&
  [row.industry_key,row.industry_taxonomy,row.taxonomy_version].every(token)&&
  ['input_hash','pack_hash','content_hash','basis_hash'].every(k=>hash(row[k]));}
const cashComponents=['cash','restricted_cash','short_term_debt','long_term_debt','current_debt_and_lease','lease_debt','other_interest_debt','period_end_shares'];
const normalizationAssumptions=['revenue','gross_margin_pct','operating_expenses','net_operating_adjustments','tax_pct','diluted_shares'];
const missingSubset=(list,allowed)=>array(list,allowed.length)&&
  list.every((item,i)=>allowed.includes(item)&&(i===0||list[i-1]<item));
function dailyBasisEvidence(d){
  if(d.continuity_status==='NOT_RECORDED')
    return d.vintage_status==='NOT_RECORDED'&&d.reason_codes.length===1&&d.reason_codes[0]==='DAILY_EVIDENCE_NOT_SUPPLIED';
  // governance-mutation: SHARED_CARDS_DAILY_REASON_EVIDENCE
  return ['BREAK','UNKNOWN_NO_ABSENCE_PROOF'].includes(d.continuity_status)&&d.vintage_status==='CAPTURE_ONLY_NOT_EVENT_VINTAGE'&&d.reason_codes.length===0;
}
function cardProjection(v){
  if(!exact(v,['facts','valuation','daily','execution_feedback']))return false;
  const {facts:f,valuation:n,daily:d,execution_feedback:e}=v;
  return exact(f,['status','observation_count','calculation_count','assessment_counts'])&&f.status==='CITED_DRAFT_NOT_HUMAN_VERIFIED'&&
    Number.isSafeInteger(f.observation_count)&&f.observation_count>=1&&f.observation_count<=96&&
    Number.isSafeInteger(f.calculation_count)&&f.calculation_count>=0&&f.calculation_count<=64&&
    f.assessment_counts&&typeof f.assessment_counts==='object'&&!Array.isArray(f.assessment_counts)&&
    Object.entries(f.assessment_counts).every(([k,v])=>['SUPPORTS','CHALLENGES','MIXED','UNRESOLVED'].includes(k)&&Number.isSafeInteger(v)&&v>=1&&v<=16)&&
    Object.keys(f.assessment_counts).length>0&&Object.values(f.assessment_counts).reduce((sum,n)=>sum+n,0)<=16&&
    exact(n,['status','normalized_eps_status','value_band_status','cash_status','net_cash_status','missing_cash_components','fair_multiple_status','missing_normalization_assumptions'])&&
    // governance-mutation: SHARED_CARDS_VALUATION_NO_VALUES
    n.status==='BASIS_EVIDENCE_PARTIAL'&&['normalized_eps_status','value_band_status','fair_multiple_status'].every(k=>n[k]==='NOT_ESTABLISHED')&&
    ['NOT_ESTABLISHED','UNREVIEWED_VALUE_PRESENT'].includes(n.net_cash_status)&&
    ['DATA_BLOCKED','INVENTORY_ARITHMETIC_SEMANTICS_UNVERIFIED'].includes(n.cash_status)&&
    missingSubset(n.missing_cash_components,cashComponents)&&missingSubset(n.missing_normalization_assumptions,normalizationAssumptions)&&
    (!n.missing_cash_components.length||(n.cash_status==='DATA_BLOCKED'&&n.net_cash_status==='NOT_ESTABLISHED'))&&
    (n.cash_status!=='INVENTORY_ARITHMETIC_SEMANTICS_UNVERIFIED'||n.net_cash_status==='UNREVIEWED_VALUE_PRESENT')&&
    // governance-mutation: SHARED_CARDS_DAILY_BLOCKED_ENUM
    exact(d,['status','eligible','reason_codes','continuity_status','vintage_status','source_trade_date'])&&d.status==='DATA_BLOCKED'&&d.eligible===false&&
    array(d.reason_codes,1)&&dailyBasisEvidence(d)&&(d.source_trade_date===null||date(d.source_trade_date))&&
    exact(e,['status','pnl_status'])&&e.status==='NOT_SUPPLIED'&&e.pnl_status==='NOT_SUPPLIED';
}
function stepsVerified(steps){
  // governance-mutation: SHARED_CARDS_TASK_EVIDENCE_STEPS
  return array(steps,taskSteps.length)&&steps.length===taskSteps.length&&taskSteps.every((step,i)=>step===steps[i]);
}
function row(v){return exact(v,['job_id','workspace_id','actor','submitted_at','code_sha','input_hash','output_hash',
  'status','report_sha256','archive_library_hash','archive_status','human_review','content_sharing_allowed','company',
  'research_date','source_cutoff_at','artifact_generated_at','industry_key','industry_taxonomy','taxonomy_version',
  'content_hash','basis_hash','pack_hash','content_producer','basis_producer','citation_locations','cards','steps',
  'content_status','sample_purpose'])&&metadata(v)&&[v.job_id,v.workspace_id].every(uuid)&&login(v.actor)&&code(v.code_sha)&&
  Number.isFinite(v.submitted_at)&&v.submitted_at>0&&
  ['output_hash','report_sha256','archive_library_hash'].every(k=>hash(v[k]))&&
  v.status==='SUCCEEDED'&&v.archive_status==='ARCHIVED'&&v.human_review==='PENDING'&&v.content_sharing_allowed===false&&
  v.sample_purpose==='WORKFLOW_DEBUG'&&v.output_hash===v.archive_library_hash&&
  v.content_status==='RIGHTS_UNVERIFIED_CONTENT_DENIED'&&identity(v.content_producer)&&identity(v.basis_producer)&&cardProjection(v.cards)&&
  (v.cards.daily.source_trade_date===null||Date.parse(v.cards.daily.source_trade_date.slice(0,4)+'-'+
    v.cards.daily.source_trade_date.slice(4,6)+'-'+v.cards.daily.source_trade_date.slice(6)+'T15:00:00+08:00')<=Date.parse(v.artifact_generated_at))&&
  array(v.citation_locations)&&v.citation_locations.length===v.cards.facts.observation_count&&
  v.citation_locations.every(x=>exact(x,['fact_id','sha256','page','start','end'])&&token(x.fact_id)&&hash(x.sha256)&&
    ['page','start','end'].every(k=>Number.isSafeInteger(x[k])&&x[k]>=1)&&x.end>=x.start)&&
  new Set(v.citation_locations.map(x=>x.fact_id)).size===v.citation_locations.length&&stepsVerified(v.steps);}

const taskSteps=['REGISTERED_INPUT_VERIFIED','CONTENT_RECOMPUTED','BASIS_RECOMPUTED','METADATA_ARCHIVED','OUTPUT_SEALED'];
const detailKeys=['job_id','command_id','workspace_id','actor','kind','snapshot_id','input_hash','source_run_id',
  'source_trade_date','submitted_at','code_sha','source_tree_hash','schema_version','status','attempt_id','output_hash',
  'error','sample_purpose','human_review','production_authority','trading_authority','result','research_cards'];
const resultKeys=['status','archive_status','content_sharing_allowed','human_review','seal_hash','output_hash',
  'archive_library_hash','report_sha256'];
const token=v=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$/.test(v)&&v.trim()===v;
const uuid=v=>typeof v==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(v);
const instant=v=>typeof v==='string'&&/^\d{4}-\d\d-\d\dT(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(v)&&
  v.trim()===v&&date(v.slice(0,10).replaceAll('-',''))&&Number.isFinite(Date.parse(v));

export function cardValuationStatus(value){
  const fields=['normalized_eps_status','net_cash_status','fair_multiple_status','value_band_status'];
  return value.cash_status==='DATA_BLOCKED'||fields.some(key=>value[key]==='NOT_ESTABLISHED')
    ? 'DATA_BLOCKED' : value.status;
}

export function cardTaskEvidence(detail,{jobId,stale}){
  // governance-mutation: SHARED_CARDS_TASK_EVIDENCE_FRESH
  if(stale||detail?.kind!=='research-cards-review'||detail.job_id!==jobId||detail.status!=='SUCCEEDED')return null;
  const {research_cards:review,result,job_id,workspace_id,actor,submitted_at,code_sha,input_hash,
    snapshot_id,attempt_id,source_tree_hash,output_hash}=detail;
  if(!exact(detail,detailKeys)||!safe(detail)||detail.schema_version!=='ar.shared-workspace.v1'||
     detail.production_authority!==false||detail.trading_authority!==false||detail.human_review!=='PENDING'||
     detail.sample_purpose!=='WORKFLOW_DEBUG'||detail.error!==null||detail.source_run_id!==null||detail.source_trade_date!==null||
     ![job_id,workspace_id,snapshot_id,attempt_id].every(uuid)||!commandId(detail.command_id)||!hash(source_tree_hash)||
     !Number.isFinite(submitted_at)||submitted_at<=0)return null;
  if(!review||['job_id','workspace_id','actor','submitted_at','code_sha','input_hash'].some(key=>Object.hasOwn(review,key))||
     !row({...review,job_id,workspace_id,actor,submitted_at,code_sha,input_hash})||
     review.sample_purpose!=='WORKFLOW_DEBUG'||review.output_hash!==output_hash||review.archive_library_hash!==output_hash)return null;
  // governance-mutation: SHARED_CARDS_TASK_RECEIPT_RESULT
  if(!exact(result,resultKeys)||!hash(result.seal_hash)||resultKeys.some(key=>key!=='seal_hash'&&result[key]!==review[key]))return null;
  const receipt={schema:'ar.shared-card-client-receipt.v1',job_id,workspace_id,actor,submitted_at,code_sha,input_hash,
    snapshot_id,attempt_id,source_tree_hash,output_hash,seal_hash:result.seal_hash,status:'SUCCEEDED',research_cards:review};
  return {steps:review.steps,citation_locations:review.citation_locations,valuationStatus:cardValuationStatus(review.cards.valuation),receipt};
}

export function jobDetailReader(previous,login,workspaceId,codeSha){
  const key=JSON.stringify([login,workspaceId,codeSha]);
  return previous?.key===key?previous:{key,ready:Boolean(login&&workspaceId&&code(codeSha))};
}

export function detailReadCurrent(selection,active,reader){
  // governance-mutation: SHARED_CARDS_TASK_READER_CONTEXT
  return Boolean(selection&&selection===active&&selection.reader===reader);
}

export function cardsContextKey(c){return JSON.stringify([c.login,c.workspaceId,c.codeSha,...filters.map(k=>c.filters?.[k]||''),c.page||0]);}
export const cardsView=libraryView;
export function refreshCardVerification({verified,active,setSelected,setRevision}){
  verified.current=null;active.current=null;setSelected('');setRevision(value=>value+1);
}
export function canRunCard({activeKey,requestKey,stale,busy,selected}){
  // governance-mutation: SHARED_CARDS_CLIENT_SUBMISSION
  return activeKey===requestKey&&!stale&&!busy&&Boolean(selected);
}
export async function readCardInputs(api,c,renew){
  const data=await sharedRead(api,'/api/shared-workspace/research-card-inputs',renew);
  // governance-mutation: SHARED_CARDS_CLIENT_INPUT_CONTEXT
  if(!exact(data,[...commonKeys,'enabled','inputs'])||!common(data,c)||data.schema!=='ar.shared-research-card-inputs.v1'||typeof data.enabled!=='boolean'||!array(data.inputs,100)||
    (!data.enabled&&data.inputs.length)||data.inputs.some(v=>!exact(v,['snapshot_id','input_hash','company','research_date',
      'source_cutoff_at','artifact_generated_at','industry_key','industry_taxonomy','taxonomy_version','pack_hash',
      'content_hash','basis_hash','classification_status','projection_hash'])||!metadata(v)||!text(v.snapshot_id)||!hash(v.projection_hash)||!text(v.classification_status)))
    throw new Error('CARDS_CONTEXT_MISMATCH');
  return data;
}
export async function readCardLibrary(api,c,renew){
  const params=new URLSearchParams({page:String(c.page||0)});
  if(Object.keys(c.filters||{}).some(k=>!filters.includes(k)))throw new Error('CARDS_CONTEXT_MISMATCH');
  for(const key of filters)if(c.filters?.[key])params.set(key,c.filters[key]);
  const data=await sharedRead(api,`/api/shared-workspace/research-card-library?${params}`,renew);
  // governance-mutation: SHARED_CARDS_CLIENT_LIBRARY_CONTEXT
  if(!exact(data,[...commonKeys,'status','library_hash','query','page','page_size','total','results','rights'])||
    !common(data,c)||!exact(data.query,filters)||!exact(data.rights,['status','visibility','sharing_allowed','model_use_allowed'])||
    data.schema!=='ar.shared-research-card-library.v1'||!['EMPTY','RESULTS_AVAILABLE_NOT_HUMAN_VERIFIED'].includes(data.status)||
    !hash(data.library_hash)||data.page!==(c.page||0)||data.page_size!==50||!array(data.results,50)||
    // governance-mutation: SHARED_CARDS_ARCHIVE_PAGE_COVERAGE
    !Number.isSafeInteger(data.total)||data.total<0||data.total>100||
    data.status!==(data.total?'RESULTS_AVAILABLE_NOT_HUMAN_VERIFIED':'EMPTY')||
    data.results.length!==Math.min(50,Math.max(0,data.total-data.page*50))||
    new Set(data.results.map(v=>v?.job_id)).size!==data.results.length||
    filters.some(k=>(data.query?.[k]??null)!==(c.filters?.[k]||null))||data.results.some(v=>!row(v))||
    data.results.some(v=>filters.some(k=>data.query[k]!==null&&v[k==='ts_code'?'company':k]!==data.query[k]))||
    data.rights?.status!=='UNVERIFIED'||data.rights?.visibility!=='PRIVATE'||data.rights?.sharing_allowed!==false||data.rights?.model_use_allowed!==false)
    throw new Error('CARDS_CONTEXT_MISMATCH');
  return data;
}
