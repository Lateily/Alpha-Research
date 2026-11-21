import test from 'node:test';
import assert from 'node:assert/strict';
const view = await import('../tools/nonprod_workbench/daily-ui/view.mjs').catch(() => ({}));
const reports = [
  {job_id:'one',company:'603986.SH',company_name:'兆易创新',industry_key:'semiconductor',industry_label:'半导体',research_date:'20261110'},
  {job_id:'two',company:'000001.SZ',company_name:'测试银行',industry_key:'bank',industry_label:'银行',research_date:'20261111'}
];
test('exactly five daily destinations, no deployment tasks in primary navigation', () => {
  assert.deepEqual(view.destinations?.map(x => x.id), ['today','research','holdings','macro','tests']);
});
test('fresh response expires at the original fifteen-second boundary', () => {
  assert.equal(typeof view.isFresh, 'function');
  assert.equal(view.isFresh(1000,15999),true);
  assert.equal(view.isFresh(1000,16000),false);
  assert.equal(view.isFresh(null,1000),false);
  assert.equal(view.isFresh(2000,1000),false);
  assert.equal(view.isFresh(NaN,1000),false);
});
test('missing and unknown quality never become approved or usable', () => {
  assert.equal(typeof view.statusInfo,'function');
  for (const value of [null,undefined,'FUTURE_UNKNOWN','DATA_BLOCKED','BREAK','PENDING','PARTIAL','STALE']) {
    assert.notEqual(view.statusInfo(value).tone,'positive');
    assert.equal(view.statusInfo(value).raw,value??'NOT_SUPPLIED');
  }
  assert.equal(view.statusInfo('DATA_BLOCKED').label,'缺少依据');
  assert.equal(view.statusInfo('PENDING').label,'待人审');
  assert.equal(view.statusInfo('STALE').label,'核验已过期');
});
test('completed task is not labeled human research approval', () => {
  assert.equal(view.statusInfo?.('SUCCEEDED')?.label,'任务完成');
  assert.notEqual(view.statusInfo?.('SUCCEEDED')?.label,'研究通过');
});
test('loaded metadata supports code prefix and Chinese name search', () => {
  assert.equal(typeof view.filterReports,'function');
  assert.deepEqual(view.filterReports(reports,{query:'6039'}).map(x=>x.job_id),['one']);
  assert.deepEqual(view.filterReports(reports,{query:'兆易'}).map(x=>x.job_id),['one']);
  assert.deepEqual(view.filterReports(reports,{query:'半导体'}).map(x=>x.job_id),['one']);
});
test('industry, research date and search intersect without invented global lookup', () => {
  assert.equal(typeof view.filterReports,'function');
  assert.equal(view.filterReports(reports,{industry:'bank',date:'2026-11-10',query:'603986'}).length,0);
  assert.equal(view.filterReports(reports,{industry:'semiconductor',date:'2026-11-10',query:'603986'}).length,1);
  assert.equal(view.filterReports(reports,{query:'不存在'}).length,0);
});
test('numbers are not supplied when missing, malformed or non-finite', () => {
  assert.equal(typeof view.numberText,'function');
  for(const x of [null,undefined,'',NaN,Infinity])assert.equal(view.numberText(x),'未提供');
  assert.equal(view.numberText(0),'0');
});
test('old artifact dates retain their original dates', () => {
  assert.equal(typeof view.dateText,'function');
  assert.equal(view.dateText('20261110'),'2026-11-10');
  assert.equal(view.dateText(null),'未提供');
});
test('download click checks actual expiry, not the previous render tick',()=>{
  assert.equal(typeof view.canDownload,'function');
  assert.equal(view.canDownload(true,1000,15999),true);
  assert.equal(view.canDownload(true,1000,16000),false);
  assert.equal(view.canDownload(false,1000,1001),false);
});
test('malformed projections and expanded capabilities are not accepted',()=>{
  assert.equal(typeof view.validProjection,'function');
  for(const data of [null,{}, {schema:'ar.daily-preview.v1',mode:'ISOLATED_READ_ONLY',provenance:{permission_expanded:true}}])
    assert.equal(view.validProjection(data),false);
});
test('repeated verification of the same report is one study, not new research samples',()=>{
  assert.equal(typeof view.groupReports,'function');
  const original={company:'603986.SH',research_date:'20261110',input_hash:'a'.repeat(64),report_sha256:'b'.repeat(64)};
  const rows=[{...original,job_id:'first',submitted_at:1},{...original,job_id:'second',submitted_at:2}];
  const groups=view.groupReports(rows);
  assert.equal(groups.length,1);assert.equal(groups[0].row.job_id,'second');assert.equal(groups[0].records.length,2);
  assert.equal(rows[0].job_id,'first');
  assert.equal(view.groupReports([...rows,{...rows[1],report_sha256:'c'.repeat(64)}]).length,2);
});
