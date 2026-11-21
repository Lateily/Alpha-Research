export const destinations = [
  {id:'today',label:'今日'}, {id:'research',label:'研究'},
  {id:'holdings',label:'持仓'}, {id:'macro',label:'宏观'}, {id:'tests',label:'测试'}
];
export function isFresh(lastSuccessAt, now=Date.now()) {
  return typeof lastSuccessAt==='number' && Number.isFinite(lastSuccessAt) &&
    Number.isFinite(now) && now>=lastSuccessAt && now-lastSuccessAt<15000;
}
export function canDownload(fresh,lastSuccessAt,now=Date.now()) {
  return fresh===true && isFresh(lastSuccessAt,now);
}
export function validProjection(data) {
  return data?.schema==='ar.daily-preview.v1' && data.mode==='ISOLATED_READ_ONLY' &&
    data.sample_purpose==='WORKFLOW_DEBUG' && data.provenance?.permission_expanded===false &&
    ['submit_research','submit_comment','run_tests','trade'].every(k=>data.capabilities?.[k]===false) &&
    typeof data.source?.source_trade_date==='string' &&
    Array.isArray(data.cards?.library?.results) && Array.isArray(data.cards?.inputs?.inputs) &&
    Array.isArray(data.shared?.team_jobs) && typeof data.task_details==='object' && data.task_details!==null &&
    typeof data.macro==='object' && data.macro!==null &&
    typeof data.acceptance?.code_sha==='string' && data.acceptance.local_ci!=null && data.acceptance.local_mutations!=null;
}
const states = {
  SUCCEEDED:['任务完成','positive'], ARCHIVED:['已归档','neutral'],
  COMPLETE:['采集完成','neutral'], OK:['已取得','neutral'],
  PENDING:['待人审','warning'], DATA_BLOCKED:['缺少依据','warning'],
  PARTIAL:['资料不完整','warning'], BREAK:['连续性未通过','warning'],
  STALE:['核验已过期','danger'], DISCONNECTED:['读取失败','danger'],
  STOP:['已停止','danger'], INTERRUPTED:['已中断','danger'],
  NOT_SUPPLIED:['未提供','neutral'], UNRESOLVED:['尚待解决','warning'],
  RUNNING:['进行中','neutral'], QUEUED:['排队中','neutral'],
  BASIS_PARTIAL_NORMALIZATION_PENDING:['估值依据未齐','warning'],
  INPUT_ADAPTED_GATES_PENDING:['技术依据未齐','warning'],
  CITED_DRAFT_NOT_HUMAN_VERIFIED:['引用待核验','warning'],
  DATA_INVALID:['来源校验未通过','warning'], CURRENT:['来源可用','neutral']
};
export function statusInfo(value) {
  const raw=value??'NOT_SUPPLIED';
  const [label,tone]=states[raw]??['未核验状态','neutral'];
  return {raw,label,tone};
}
export function filterReports(rows,{query='',industry='',date=''}={}) {
  const tokens=query.normalize('NFKC').trim().toLowerCase().split(/\s+/).filter(Boolean);
  const day=date.replaceAll('-','');
  return rows.filter(row=>{
    const text=[row.company,row.company_name,row.industry_label,row.industry_key,row.job_id]
      .filter(Boolean).join(' ').normalize('NFKC').toLowerCase();
    return (!industry||row.industry_key===industry)&&(!day||row.research_date===day)&&tokens.every(t=>text.includes(t));
  });
}
export function groupReports(rows) {
  const groups=new Map();
  for (const row of rows) {
    const key=row.input_hash&&row.report_sha256?
      JSON.stringify([row.company,row.research_date,row.input_hash,row.report_sha256]):row.job_id;
    const group=groups.get(key)||{row,records:[]};
    group.records.push(row);
    if ((row.submitted_at??0)>(group.row.submitted_at??0))group.row=row;
    groups.set(key,group);
  }
  return [...groups.values()];
}
export function numberText(value) {
  return typeof value==='number'&&Number.isFinite(value)?value.toLocaleString('zh-CN',{maximumFractionDigits:2}):'未提供';
}
export function dateText(value) {
  if(!value||typeof value!=='string')return '未提供';
  return /^\d{8}$/.test(value)?`${value.slice(0,4)}-${value.slice(4,6)}-${value.slice(6,8)}`:value.slice(0,10);
}
export function titleFor(job) {
  return ({'research-cards-review':'研究卡核验','earnings-review':'财报逐条回应',
    'snapshot-brief':'市场简报','observe':'数据观察'})[job?.kind]||'历史任务';
}
