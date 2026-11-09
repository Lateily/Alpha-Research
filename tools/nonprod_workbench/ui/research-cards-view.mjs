import { sharedRead } from './shared-view.mjs';
import { libraryView } from './research-library-view.mjs';

const filters=['industry_key','industry_taxonomy','taxonomy_version','research_date','ts_code'];
const authorities=['production_authority','paper_authority','u4_authority','trading_authority'];
const hash=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const code=v=>typeof v==='string'&&/^[a-f0-9]{40}$/.test(v);
const text=v=>typeof v==='string'&&v.length>0&&v.length<=200;
const date=v=>typeof v==='string'&&/^\d{8}$/.test(v);
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
function common(v,c){return v&&safe(v)&&v.my_workspace?.login===c.login&&v.my_workspace?.workspace_id===c.workspaceId&&
  v.consumer_code_sha===c.codeSha&&code(c.codeSha)&&v.sample_purpose==='WORKFLOW_DEBUG'&&v.human_review==='PENDING'&&
  v.content_sharing_allowed===false&&v.content_status==='RIGHTS_UNVERIFIED_CONTENT_DENIED'&&authorities.every(k=>v[k]===false);}
function metadata(row){return row&&text(row.company)&&date(row.research_date)&&
  ['source_cutoff_at','artifact_generated_at','industry_key','industry_taxonomy','taxonomy_version'].every(k=>text(row[k]))&&
  ['input_hash','pack_hash','content_hash','basis_hash'].every(k=>hash(row[k]));}
function cardProjection(v){
  if(!exact(v,['facts','valuation','daily','execution_feedback']))return false;
  const {facts:f,valuation:n,daily:d,execution_feedback:e}=v;
  return exact(f,['status','observation_count','calculation_count','assessment_counts'])&&f.status==='CITED_DRAFT_NOT_HUMAN_VERIFIED'&&
    Number.isSafeInteger(f.observation_count)&&f.observation_count>=0&&f.observation_count<=96&&
    Number.isSafeInteger(f.calculation_count)&&f.calculation_count>=0&&f.calculation_count<=64&&
    f.assessment_counts&&Object.entries(f.assessment_counts).every(([k,v])=>['SUPPORTS','CHALLENGES','MIXED','UNRESOLVED'].includes(k)&&Number.isSafeInteger(v)&&v>=0&&v<=64)&&
    exact(n,['status','normalized_eps_status','value_band_status','cash_status','net_cash_status','missing_cash_components','fair_multiple_status','missing_normalization_assumptions'])&&
    n.status==='BASIS_EVIDENCE_PARTIAL'&&['normalized_eps_status','value_band_status','net_cash_status','fair_multiple_status'].every(k=>['NOT_ESTABLISHED','UNREVIEWED_VALUE_PRESENT'].includes(n[k]))&&
    text(n.cash_status)&&array(n.missing_cash_components,16)&&n.missing_cash_components.every(text)&&array(n.missing_normalization_assumptions,16)&&n.missing_normalization_assumptions.every(text)&&
    exact(d,['status','eligible','reason_codes','continuity_status','vintage_status','source_trade_date'])&&text(d.status)&&d.eligible===false&&
    array(d.reason_codes,64)&&d.reason_codes.every(text)&&text(d.continuity_status)&&text(d.vintage_status)&&(d.source_trade_date===null||date(d.source_trade_date))&&
    exact(e,['status','pnl_status'])&&text(e.status)&&['NOT_SUPPLIED','LOCAL_EVIDENCE_NOT_HUMAN_VERIFIED'].includes(e.pnl_status);
}
function row(v){return exact(v,['job_id','workspace_id','actor','submitted_at','code_sha','input_hash','output_hash',
  'status','report_sha256','archive_library_hash','archive_status','human_review','content_sharing_allowed','company',
  'research_date','source_cutoff_at','artifact_generated_at','industry_key','industry_taxonomy','taxonomy_version',
  'content_hash','basis_hash','pack_hash','content_producer','basis_producer','citation_locations','cards','steps',
  'content_status','sample_purpose'])&&metadata(v)&&['job_id','workspace_id','actor'].every(k=>text(v[k]))&&code(v.code_sha)&&
  ['output_hash','report_sha256','archive_library_hash'].every(k=>hash(v[k]))&&
  v.status==='SUCCEEDED'&&v.archive_status==='ARCHIVED'&&v.human_review==='PENDING'&&v.content_sharing_allowed===false&&
  v.content_status==='RIGHTS_UNVERIFIED_CONTENT_DENIED'&&identity(v.content_producer)&&identity(v.basis_producer)&&cardProjection(v.cards)&&
  array(v.citation_locations)&&v.citation_locations.every(x=>exact(x,['fact_id','sha256','page','start','end'])&&text(x.fact_id)&&hash(x.sha256)&&
    ['page','start','end'].every(k=>Number.isSafeInteger(x[k])&&x[k]>=1)&&x.end>=x.start)&&
  array(v.steps,8)&&v.steps.every(text);}
export function cardsContextKey(c){return JSON.stringify([c.login,c.workspaceId,c.codeSha,...filters.map(k=>c.filters?.[k]||''),c.page||0]);}
export const cardsView=libraryView;
export function canRunCard({activeKey,requestKey,stale,busy,selected}){
  // governance-mutation: SHARED_CARDS_CLIENT_SUBMISSION
  return activeKey===requestKey&&!stale&&!busy&&Boolean(selected);
}
export async function readCardInputs(api,c,renew){
  const data=await sharedRead(api,'/api/shared-workspace/research-card-inputs',renew);
  // governance-mutation: SHARED_CARDS_CLIENT_INPUT_CONTEXT
  if(!common(data,c)||data.schema!=='ar.shared-research-card-inputs.v1'||typeof data.enabled!=='boolean'||!array(data.inputs,100)||
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
  if(!common(data,c)||data.schema!=='ar.shared-research-card-library.v1'||!['EMPTY','RESULTS_AVAILABLE_NOT_HUMAN_VERIFIED'].includes(data.status)||
    !hash(data.library_hash)||data.page!==(c.page||0)||data.page_size!==50||!array(data.results,50)||
    !Number.isSafeInteger(data.total)||data.total<data.results.length||data.total>100||
    filters.some(k=>(data.query?.[k]??null)!==(c.filters?.[k]||null))||data.results.some(v=>!row(v))||
    data.rights?.status!=='UNVERIFIED'||data.rights?.visibility!=='PRIVATE'||data.rights?.sharing_allowed!==false||data.rights?.model_use_allowed!==false)
    throw new Error('CARDS_CONTEXT_MISMATCH');
  return data;
}
