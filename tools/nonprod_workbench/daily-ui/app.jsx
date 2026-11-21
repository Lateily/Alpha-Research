import React, { useEffect, useRef, useState } from 'react';
import { Activity, ArrowDownToLine, ArrowLeft, ArrowRight, BarChart3, Check, ChevronDown, ChevronRight, Clock3, FileCheck2, FileSearch, FileText, FlaskConical, FolderOpen, Home, Info, Layers3, LockKeyhole, PanelLeftClose, RefreshCw, Search, ShieldCheck, Wallet, X } from 'lucide-react';
import { canDownload, dateText, destinations, filterReports, groupReports, isFresh, numberText, statusInfo, titleFor, validProjection } from './view.mjs';
const icons = {
  today: Home,
  research: FileText,
  holdings: Wallet,
  macro: Activity,
  tests: FlaskConical
};
const industryLabel = value => ({
  semiconductor: '半导体'
})[value] || value || '未分类';
const metricLabels = {
  ahe_level: '平均时薪',
  headline_cpi_sa: '美国 CPI',
  final_demand_ppi_sa: '美国 PPI',
  total_nonfarm_employment: '非农就业',
  civilian_unemployment_rate: '失业率',
  job_openings: '职位空缺',
  vix_close: 'VIX 波动率',
  real_gdp_qoq_saar: '美国实际 GDP',
  core_pce_price_index: '核心 PCE',
  retail_sales_value_sa: '美国零售销售',
  hy_oas: '高收益债利差',
  ig_oas: '投资级债利差',
  real_yield_10y: '10年实际利率',
  y10: '10年美债收益率',
  y2: '2年美债收益率'
};
const basisLabels = {
  diluted_shares: '稀释股数',
  gross_margin_pct: '正常毛利率',
  net_operating_adjustments: '经营调整',
  operating_expenses: '经营费用',
  revenue: '周期收入',
  tax_pct: '正常税负',
  long_term_debt: '长期债务',
  other_interest_debt: '其他有息债务',
  short_term_debt: '短期债务'
};
const stepLabels = {
  REGISTERED_INPUT_VERIFIED: '核对冻结材料',
  CONTENT_RECOMPUTED: '复核事实与计算',
  BASIS_RECOMPUTED: '复核估值与技术依据',
  METADATA_ARCHIVED: '结果入库',
  OUTPUT_SEALED: '封存结果'
};
function Status({
  value
}) {
  const s = statusInfo(value);
  return <span className={`status ${s.tone}`} title={s.raw}><i />{s.label}</span>;
}
function IconButton({
  label,
  children,
  ...props
}) {
  return <button className="icon-button" title={label} aria-label={label} {...props}>{children}</button>;
}
function SectionTitle({
  title,
  count,
  action
}) {
  return <div className="section-title"><h2>{title}{count != null && <span className="count">{count}</span>}</h2>{action}</div>;
}
function Empty({
  icon: Icon = FolderOpen,
  title,
  detail
}) {
  return <div className="empty-state"><Icon size={28} strokeWidth={1.4} /><h3>{title}</h3>{detail && <p>{detail}</p>}</div>;
}
function EvidenceLink({
  onClick
}) {
  return <button className="text-button" onClick={onClick}><ShieldCheck size={15} />证据详情<ChevronRight size={14} /></button>;
}
function Subtabs({
  items,
  value,
  onChange,
  label
}) {
  const buttons=useRef([]);
  function keyDown(event,index) {
    const next=event.key==='ArrowRight'?(index+1)%items.length:
      event.key==='ArrowLeft'?(index+items.length-1)%items.length:
      event.key==='Home'?0:event.key==='End'?items.length-1:null;
    if(next===null)return;
    event.preventDefault();onChange(items[next][0]);buttons.current[next]?.focus();
  }
  return <div className="subtabs" role="tablist" aria-label={label}>{items.map(([id, text],index) => <button key={id} ref={element=>{buttons.current[index]=element;}} role="tab" tabIndex={value===id?0:-1} aria-selected={value === id} onKeyDown={event=>keyDown(event,index)} onClick={() => onChange(id)}>{text}</button>)}</div>;
}
function PageHeading({
  eyebrow,
  title,
  children,
  action
}) {
  return <header className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{children}</div>{action}</header>;
}
function Stat({
  label,
  value,
  detail,
  icon: Icon
}) {
  const sizeClass=typeof value==='string'&&/[\u4e00-\u9fff]/.test(value)?'text-value':String(value).length>8?'long-value':'';
  return <div className="stat"><div className="stat-label">{Icon && <Icon size={15} />} {label}</div><strong className={sizeClass}>{value}</strong><span>{detail}</span></div>;
}
function TaskRows({
  jobs,
  onOpen
}) {
  return <div className="task-list">{jobs.map(job => <button className="task-row" data-job-id={job.job_id} key={job.job_id} onClick={() => onOpen(job)}><div className={`task-icon ${job.kind === 'research-cards-review' ? 'green' : ''}`}><FileCheck2 size={19} /></div><div className="task-name"><strong>{titleFor(job)}</strong><span>{new Date(job.submitted_at * 1000).toLocaleString('zh-CN', {
            timeZone: 'Europe/London',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
          })}<span className="task-short"> · {job.job_id.slice(0, 8)}</span></span></div><Status value={job.status} /><ChevronRight size={16} /></button>)}</div>;
}
function Attention({
  row,
  onOpen
}) {
  const cards = row?.cards;
  if (!cards) return <Empty title="暂无待处理研究" />;
  return <div className="attention-list">{[['估值依据', cards?.valuation?.normalized_eps_status === 'NOT_ESTABLISHED' ? '正常化 EPS、净现金和合理倍数未齐' : '待核对估值依据', BarChart3], ['日线技术', cards?.daily?.continuity_status === 'BREAK' ? '日线连续性未通过' : '技术依据待核验', Activity], ['人工核验', '样稿尚未由研究者签署', FileCheck2]].map(([title, detail, Icon]) => <button key={title} onClick={onOpen} className="attention-row"><Icon size={17} /><div><strong>{title}</strong><span>{detail}</span></div><ArrowRight size={15} /></button>)}</div>;
}
function Today({
  data,
  navigate,
  onEvidence,
  onOpenJob
}) {
  const reports = groupReports(data.cards.library.results).map(group=>group.row),
    jobs = data.shared.team_jobs || [],
    row = reports[0];
  const [filter, setFilter] = useState('all');
  const cardsKnown=data.availability?.cards!==false,historyKnown=data.availability?.history!==false;
  const sourceKnown=historyKnown&&!!data.source.source_trade_date;
  const shown = [...jobs].sort((a, b) => b.submitted_at - a.submitted_at).filter(j => filter === 'all' || j.kind === filter).slice(0, 5);
  return <>
    <PageHeading eyebrow="工作空间 / 今日" title="今日工作" action={<button className="button dark" onClick={() => navigate('research')}><FileSearch size={16} />查看研究<ArrowRight size={16} /></button>}><p>资料截至 {dateText(data.source.source_trade_date)} <span className="inline-divider" />历史封存副本</p></PageHeading>
    <div className="stats-band"><Stat icon={FileText} label="研究结果" value={cardsKnown?reports.length:'待核验'} detail="已归档的研究卡" /><Stat icon={Clock3} label="待人工核验" value={cardsKnown?reports.filter(x => x.human_review === 'PENDING').length:'待核验'} detail="未计为研究通过" /><Stat icon={Layers3} label="任务记录" value={historyKnown?(data.shared.team_total ?? jobs.length):'待核验'} detail="历史任务 · 只读" /></div>
    <div className="today-columns"><section><SectionTitle title="继续研究" action={<button className="text-button" onClick={() => navigate('research')}>全部研究<ArrowRight size={15} /></button>} />
      {row ? <button className="featured-research" onClick={() => navigate('research')}><div className="featured-top"><span className="document-icon"><FileText size={23} /></span><Status value={row.human_review} /></div><h3>{row.company}<span>{industryLabel(row.industry_key)}</span></h3><p>财报事实、估值依据与日线技术</p><div className="featured-bottom"><span>研究日 {dateText(row.research_date)}</span><ArrowRight size={18} /></div></button> : <Empty title={cardsKnown?'尚无研究结果':'研究结果待核验'} />}
      <SectionTitle title="最近任务" action={<Subtabs label="任务类型" items={[["all", "全部"], ["research-cards-review", "研究卡"], ["snapshot-brief", "简报"]]} value={filter} onChange={setFilter} />} />
      {historyKnown?<TaskRows jobs={shown} onOpen={job => onOpenJob&&job.kind==='research-cards-review'?onOpenJob(job.job_id):onEvidence(titleFor(job), data.task_details[job.job_id] || job)} />:<Empty title="任务记录待核验"/>}
    </section><aside className="today-aside"><SectionTitle title="需要关注" />{cardsKnown?<Attention row={row} onOpen={() => navigate('research')} />:<Empty title="研究缺项待核验"/>}<div className="source-note"><span className="source-note-icon"><LockKeyhole size={18} /></span><h3>{sourceKnown?'历史发布来源':'发布来源尚未核验'}</h3><dl><dt>来源交易日</dt><dd>{dateText(data.source.source_trade_date)}</dd><dt>研究用途</dt><dd>流程调试</dd><dt>研究批准</dt><dd>尚未取得</dd></dl><EvidenceLink onClick={() => onEvidence('封存来源', data.source)} /></div></aside></div>
  </>;
}
function ReportDetail({
  row,
  data,
  fresh,
  onBack,
  onEvidence
}) {
  const [panel, setPanel] = useState('overview'),
    [citationQuery, setCitationQuery] = useState('');
  const cards = row.cards,
    detail = data.task_details[row.job_id];
  const citations = row.citation_locations || [];
  const shown = citations.filter(c => [c.fact_id, c.page, c.sha256].some(v => String(v).toLowerCase().includes(citationQuery.toLowerCase())));
  const steps = detail?.research_cards?.steps || [];
  return <div className="report-detail"><button className="text-button back-button" onClick={onBack}><ArrowLeft size={16} />研究结果</button>
    <div className="report-heading"><div><div className="eyebrow">{industryLabel(row.industry_key)} / 财报研究</div><h1>{row.company}</h1><p>研究日 {dateText(row.research_date)} <span className="inline-divider" />已归档</p></div><Status value={row.human_review} /></div>
    <div className="report-source"><span>原件截止 <strong>{dateText(row.source_cutoff_at)}</strong></span><span>日线来源 <strong>{dateText(cards.daily.source_trade_date)}</strong></span><EvidenceLink onClick={() => onEvidence('研究证据', row)} /></div>
    <Subtabs label="研究详情" value={panel} onChange={setPanel} items={[["overview", "概览"], ["facts", "事实与引用"], ["valuation", "估值"], ["technical", "技术"], ["workflow", "任务步骤"]]} />
    {panel === 'overview' && <><div className="research-warning"><Info size={18} /><div><strong>研究依据尚未齐备</strong><p>估值与日线仍有缺项，本结果未获人工研究批准。</p></div><span className="raw-state">DATA_BLOCKED</span></div><div className="report-grid">{[['事实与引用', `${cards.facts.observation_count} 条数字引用 · ${cards.facts.calculation_count} 项计算`, cards.facts.status, 'facts', FileText], ['正常化估值', 'EPS、完整净现金、合理倍数待建立', 'DATA_BLOCKED', 'valuation', BarChart3], ['日线技术', `来源 ${dateText(cards.daily.source_trade_date)}`, cards.daily.continuity_status, 'technical', Activity], ['执行反馈', '尚未提供本案例的执行记录', cards.execution_feedback.status, null, Clock3]].map(([title, text, status, target, Icon]) => <div className="result-module" key={title}><div className="module-top"><Icon size={19} /><Status value={status} /></div><h3>{title}</h3><p>{text}</p>{target && <button className="text-button" onClick={() => setPanel(target)}>查看<ArrowRight size={15} /></button>}</div>)}</div></>}
    {panel === 'facts' && <section><SectionTitle title="事实与引用" count={citations.length} action={<label className="search-field compact"><Search size={16} /><input aria-label="搜索引用" placeholder="事实标识或页码" value={citationQuery} onChange={e => setCitationQuery(e.target.value)} /></label>} /><div className="quiet-notice"><Status value={cards.facts.status} /><span>仅展示已获准的引用位置；原件正文未分发。</span></div><div className="reference-list">{shown.map((c, i) => <button key={i} onClick={() => onEvidence('引用位置', c)} className="reference-row"><span className="reference-index">{String(i + 1).padStart(2, '0')}</span><div><strong>{c.fact_id}</strong><span>原件 {c.sha256.slice(0, 10)} · 实体页 {c.page} · 文本行 {c.start}–{c.end}</span></div><ChevronRight size={16} /></button>)}</div>{!shown.length && <Empty title="没有匹配的引用" />}</section>}
    {panel === 'valuation' && <section><SectionTitle title="正常化估值" action={<Status value="DATA_BLOCKED" />} /><div className="value-table">{[['正常化 EPS', cards.valuation.normalized_eps_status], ['完整净现金', cards.valuation.net_cash_status], ['合理倍数', cards.valuation.fair_multiple_status], ['价值带', cards.valuation.value_band_status]].map(([name, state]) => <div key={name}><strong>{name}</strong><span>尚未建立</span><Status value={state === 'NOT_ESTABLISHED' ? 'DATA_BLOCKED' : state} /></div>)}</div><SectionTitle title="待补依据" /><div className="gap-list">{[...cards.valuation.missing_normalization_assumptions, ...cards.valuation.missing_cash_components].map(item => <div key={item}><span className="gap-dot" />{basisLabels[item] || item}<span>缺少依据</span></div>)}</div></section>}
    {panel === 'technical' && <section><SectionTitle title="日线技术" action={<Status value={cards.daily.status} />} /><div className="value-table"><div><strong>日线来源</strong><span>{dateText(cards.daily.source_trade_date)}</span></div><div><strong>连续性</strong><Status value={cards.daily.continuity_status} /></div><div><strong>策略准入</strong><span>{cards.daily.eligible === true ? '原合同允许' : '未通过'}</span></div><div><strong>时点依据</strong><span>仅捕获时点，非完整事件时点</span></div></div><div className="quiet-notice"><Info size={16} /><span>未产出可执行入场、止损或目标。</span></div></section>}
    {panel === 'workflow' && <section><SectionTitle title="任务步骤" action={<Status value={detail?.status} />} /><p className="secondary">任务 {row.job_id}</p><ol className="workflow-steps">{steps.map((step, i) => <li key={step}><span className="step-check"><Check size={15} /></span><div><strong>{stepLabels[step] || step}</strong><span>{step}</span></div><span className="step-order">{i + 1}</span></li>)}</ol>{!steps.length && <Empty title="未提供步骤记录" />}<EvidenceLink onClick={() => onEvidence('任务执行证据', detail || row)} /></section>}
    <div className="report-footer"><span><LockKeyhole size={14} /> 原件正文未开放 · 交易权限未开放</span><span>{fresh ? '封存副本可读' : '核验已过期'}</span></div>
  </div>;
}
function Research({
  data,
  fresh,
  onEvidence,
  navigate
}) {
  const [view, setView] = useState('reports'),
    [query, setQuery] = useState(''),
    [industry, setIndustry] = useState(''),
    [date, setDate] = useState(''),
    [selected, setSelected] = useState(null);
  const reports = data.cards.library.results.map(row => ({
    ...row,
    industry_label: industryLabel(row.industry_key)
  }));
  const rows = groupReports(filterReports(reports, {
    query,
    industry,
    date
  })).map(group=>group.row);
  const industries = [...new Set(reports.map(x => x.industry_key))];
  if (selected) {
    const row = reports.find(x => x.job_id === selected);
    if (row) return <ReportDetail key={selected} row={row} data={data} fresh={fresh} onBack={() => setSelected(null)} onEvidence={onEvidence} />;
  }
  return <><PageHeading eyebrow="工作空间 / 研究" title="研究" action={<span className="read-only-tag"><LockKeyhole size={14} />执行入口未接入本预览</span>}><p>已登记材料与封存结果</p></PageHeading>
    <Subtabs label="研究内容" items={[["reports", "研究结果"], ["tasks", "任务记录"], ["materials", "材料"]]} value={view} onChange={setView} />
    {view === 'reports' && <><div className="research-toolbar"><label className="search-field"><Search size={17} /><input aria-label="搜索研究" placeholder="搜索股票、行业或任务" value={query} onChange={e => setQuery(e.target.value)} />{query && <IconButton label="清空搜索" onClick={() => setQuery('')}><X size={14} /></IconButton>}</label><div className="filter-fields"><label><span className="sr-only">行业</span><select aria-label="行业" value={industry} onChange={e => setIndustry(e.target.value)}><option value="">全部行业</option>{industries.map(i => <option value={i} key={i}>{industryLabel(i)}</option>)}</select></label><label><span className="sr-only">研究日期</span><input aria-label="研究日期" type="date" value={date} onChange={e => setDate(e.target.value)} /></label></div></div><div className="list-meta"><span>{rows.length} 份结果</span><span>检索范围：已载入的登记元数据</span></div><div className="reports-list"><div className="reports-list-head"><span>研究</span><span>研究日</span><span>人工核验</span><span>依据</span></div>{rows.map(row => <button className="report-row" key={row.job_id} onClick={() => setSelected(row.job_id)}><span className="report-name"><span className="document-icon small"><FileText size={19} /></span><span><strong>{row.company}</strong><small>{industryLabel(row.industry_key)} · 财报研究<span className="task-short"> · {row.job_id.slice(0, 8)}</span></small></span></span><span className="report-date">{dateText(row.research_date)}</span><Status value={row.human_review} /><span className="report-gap"><i />缺少依据<ChevronRight size={16} /></span></button>)}</div>{!rows.length && <Empty icon={Search} title="没有匹配的研究" detail="当前筛选条件下无已登记结果。" />}</>}
    {view === 'tasks' && <><div className="list-meta"><span>{data.shared.team_total} 个历史任务</span><span>伦敦时间</span></div><TaskRows jobs={[...data.shared.team_jobs].sort((a, b) => b.submitted_at - a.submitted_at)} onOpen={job => {
        const row = reports.find(x => x.job_id === job.job_id);
        if (row) setSelected(row.job_id);else onEvidence(titleFor(job), data.task_details[job.job_id] || job);
      }} /></>}
    {view === 'materials' && <section><SectionTitle title="已登记材料" count={data.cards.inputs.inputs.length} />{data.cards.inputs.inputs.map(input => <div className="material-row" key={input.snapshot_id}><span className="document-icon"><FolderOpen size={22} /></span><div><h3>{input.company} · 财报材料</h3><p>{industryLabel(input.industry_key)} · 原件截止 {dateText(input.source_cutoff_at)}</p><span className="secondary">正文未开放</span></div><EvidenceLink onClick={() => onEvidence('登记材料', input)} /></div>)}</section>}
  </>;
}
function Holdings({
  data,
  onEvidence
}) {
  const p = data.portfolio?.data;
  if (!p) return <><PageHeading eyebrow="工作空间 / 持仓" title="持仓分析" /><Empty icon={Wallet} title="持仓数据未接入" detail="未提供可核对的持仓，不显示估算收益。" /></>;
  const positions = p.open_positions;
  return <><PageHeading eyebrow="工作空间 / 持仓" title="持仓分析" action={<Status value={data.portfolio.data_quality} />}><p>模拟账本 · 来源 {dateText(data.portfolio.target_trade_date)}</p></PageHeading><div className="stats-band"><Stat label="现金" value={numberText(p.cash)} detail="人民币 · 历史账本" /><Stat label="持仓数量" value={Array.isArray(positions) ? positions.length : '未提供'} detail="非实盘账户" /><Stat label="估值状态" value="资料不完整" detail="结算价与 NAV 仍有缺口" /></div><section><SectionTitle title="当前持仓" action={<EvidenceLink onClick={() => onEvidence('模拟账本来源', data.portfolio)} />} />{Array.isArray(positions) && !positions.length ? <Empty icon={Wallet} title="该日模拟账本为空仓" detail="无可展示的持仓分析，不能据此确认新订单价格齐备。" /> : positions ? <div className="value-table">{positions.map((row, i) => <button className="task-row" key={i} onClick={() => onEvidence('持仓记录', row)}>{row.ts_code || row.code || '持仓记录'}<ChevronRight size={16} /></button>)}</div> : <Empty title="持仓明细未提供" />}</section><div className="quiet-notice warning"><Info size={16} /><span>结算价与历史净值有缺口；收益率暂不展示。</span></div></>;
}
function Macro({
  data,
  onEvidence
}) {
  const sources = data.macro?.source_health?.data;
  const [filter, setFilter] = useState('all');
  const [region,setRegion]=useState('GLOBAL_US');
  if (!Array.isArray(sources)) return <><PageHeading eyebrow="工作空间 / 宏观" title="宏观面板" /><Empty icon={Activity} title="宏观数据未接入" /></>;
  const shown = sources.filter(s => filter === 'all' || s.status !== 'OK');
  const events = data.macro?.macro_events?.data || [];
  const axes=data.macro?.macro_panel?.data?.regions?.[region]?.axes;
  const environmentLabel=value=>({STABLE_OR_MIXED:'稳定或分化',HEATING_OR_DEFLATION_RISK:'升温或通缩风险',DATA_BLOCKED:'缺少依据'})[value]||value||'未提供';
  return <>
    <PageHeading eyebrow="工作空间 / 宏观" title="宏观面板" action={<Status value="PARTIAL"/>}>
      <p>来源 {dateText(data.source.source_trade_date)} · 历史观察</p>
    </PageHeading>
    <div className="stats-band">
      <Stat label="已取得来源" value={`${sources.filter(x=>x.status==='OK').length} / ${sources.length}`} detail="仍有过期与不可用来源"/>
      <Stat label="事件实际值" value={`${events.filter(x=>x.actual!=null).length} / ${events.length}`} detail="不补齐缺失值"/>
      <Stat label="预期差" value={events.some(x=>x.surprise!=null)?numberText(events.filter(x=>x.surprise!=null).length):'未建立'} detail="一致预期依据不足"/>
    </div>
    <section className="macro-environment">
      <SectionTitle title="宏观环境" action={<Subtabs label="宏观地区" items={[["GLOBAL_US","美国"],["CHINA","中国"]]} value={region} onChange={setRegion}/>}/>
      <div className="macro-axes">{[['GROWTH','增长'],['INFLATION','通胀'],['LIQUIDITY','流动性'],['RISK','风险偏好']].map(([key,label])=>
        <div className="macro-axis" key={key}><span>{label}</span><strong>{environmentLabel(axes?.[key]?.label)}</strong><Status value={axes?.[key]?.data_status}/></div>)}</div>
    </section>
    <section>
      <SectionTitle title="指标与来源" action={<Subtabs label="宏观来源筛选" items={[["all","全部"],["gaps","仅看缺项"]]} value={filter} onChange={setFilter}/>}/>
      <div className="macro-list">{shown.map((row,i)=><button className="macro-row" key={i} onClick={()=>onEvidence('宏观来源',row)}>
        <span className={`source-mark ${row.status==='OK'?'':'blocked'}`}><Activity size={17}/></span>
        <span className="macro-name"><strong>{metricLabels[row.metric_key]||row.metric_key}</strong><small>{row.provider}</small></span>
        <span className="macro-date">{dateText(row.as_of)}</span><Status value={row.status}/><ChevronRight size={15}/>
      </button>)}</div>
    </section>
    <div className="quiet-notice"><Info size={16}/><span>宏观观察尚未接入研究选股判断，不产生交易指令。</span></div>
  </>;
}
function Tests({
  data,
  onEvidence
}) {
  const a = data.acceptance;
  if(!a)return <><PageHeading eyebrow="工作空间 / 测试" title="模型与测试"/><Empty icon={FlaskConical} title="工程验收归档未接入此入口" detail="不以任务完成或样稿核验推断模型有效性。"/><SectionTitle title="当前运行版本"/><code>{data.consumer_code_sha||'未核验'}</code></>;
  return <><PageHeading eyebrow="工作空间 / 测试" title="模型与测试" action={<span className="read-only-tag"><LockKeyhole size={14} />执行入口未接入本预览</span>}><p>工程验收归档 · {a.code_sha.slice(0, 7)}</p></PageHeading><div className="stats-band"><Stat icon={FileCheck2} label="本地检查" value={`${a.local_ci.passed} / ${a.local_ci.total}`} detail="历史工程验收记录" /><Stat icon={ShieldCheck} label="防线变异" value={`${a.local_mutations.killed} / ${a.local_mutations.total}`} detail="不等于策略收益验证" /><Stat icon={LockKeyhole} label="研究批准" value="未取得" detail="工程通过不替代人审" /></div><section><SectionTitle title="验收记录" /><button className="test-record" onClick={() => onEvidence('已归档工程验收', a)}><span className="test-symbol"><FlaskConical size={22} /></span><div><strong>读取性能与校验回归</strong><span>版本 {a.code_sha.slice(0, 7)} · Draft #{a.draft_pr} · 未合并</span></div><ChevronRight size={17} /></button></section><section><SectionTitle title="研究表现" /><Empty icon={BarChart3} title="尚无可用的独立研究表现结论" detail="未将工程测试、历史任务或样稿核验计作策略有效性。" /></section></>;
}
export function DailyView({
  route,
  data,
  fresh,
  onEvidence = () => {},
  navigate = () => {},
  onOpenJob
}) {
  const props = {
    data,
    fresh,
    onEvidence,
    navigate,
    onOpenJob
  };
  return route === 'today' ? <Today {...props} /> : route === 'research' ? <Research {...props} /> : route === 'holdings' ? <Holdings {...props} /> : route === 'macro' ? <Macro {...props} /> : <Tests {...props} />;
}
function Drawer({
  entry,
  onClose,
  fresh,
  lastSuccessAt,
  canRead=()=>true
}) {
  const ref = useRef(null);
  useEffect(() => {
    const d = ref.current;
    d.showModal();
    return () => d.close();
  }, []);
  function download() {
    if (!canDownload(fresh,lastSuccessAt)||!canRead()) return;
    const blob = new Blob([JSON.stringify(entry.value, null, 2) + '\n'], {
      type: 'application/json'
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'ar-permitted-metadata.json';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <dialog className="evidence-drawer" ref={ref} onCancel={onClose}><header><div><span className="eyebrow">原始元数据</span><h2>{entry.title}</h2></div><IconButton label="关闭证据详情" onClick={onClose}><X size={19} /></IconButton></header><div className="drawer-state"><ShieldCheck size={17} /><span>{fresh ? '已读取封存副本' : '核验已过期'}</span></div><pre>{JSON.stringify(entry.value, null, 2)}</pre><footer><span>不包含未获准的原件正文</span><IconButton label="下载许可元数据" disabled={!fresh} onClick={download}><ArrowDownToLine size={18} /></IconButton></footer></dialog>;
}
export default function App() {
  const [route, setRoute] = useState(() => destinations.some(d => d.id === location.hash.slice(1)) ? location.hash.slice(1) : 'today');
  const [resource, setResource] = useState({
      data: null,
      lastSuccessAt: null,
      error: '',
      loading: true
    }),
    [now, setNow] = useState(Date.now),
    [evidence, setEvidence] = useState(null);
  const generation = useRef(0),
    abort = useRef(null);
  async function load() {
    const token = ++generation.current;
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    const timeout = setTimeout(() => controller.abort(), 15000);
    setResource(old => ({
      ...old,
      loading: true
    }));
    try {
      const result = await fetch('/api/preview', {
        cache: 'no-store',
        credentials: 'same-origin',
        signal: controller.signal
      });
      if (!result.ok) throw Error('READ_VERIFICATION_FAILED');
      const response = await result.json();
      if (!validProjection(response.data)) throw Error('PROJECTION_CONTRACT_INVALID');
      if (generation.current !== token) return;
      const receivedAt=Date.now();
      setNow(receivedAt);
      setResource({
        data: response.data,
        lastSuccessAt: receivedAt,
        error: '',
        loading: false
      });
    } catch (error) {
      if (generation.current !== token) return;
      setResource(old => ({
        ...old,
        lastSuccessAt: null,
        error: '封存副本暂时无法核验',
        loading: false
      }));
    } finally {
      clearTimeout(timeout);
    }
  }
  useEffect(() => {
    load();
    const timer = setInterval(load, 10000);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      ++generation.current;
      abort.current?.abort();
      clearInterval(timer);
      clearInterval(tick);
    };
  }, []);
  useEffect(() => {
    const handler = () => setRoute(destinations.some(d => d.id === location.hash.slice(1)) ? location.hash.slice(1) : 'today');
    addEventListener('hashchange', handler);
    return () => removeEventListener('hashchange', handler);
  }, []);
  const fresh = !resource.error && isFresh(resource.lastSuccessAt, now);
  function navigate(id) {
    location.hash = id;
    setRoute(id);
    setEvidence(null);
    window.scrollTo({
      top: 0,
      behavior: 'instant'
    });
  }
  function openEvidence(title, value) {
    setEvidence({
      title,
      value
    });
  }
  const data = resource.data;
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><span className="brand-mark">AR</span><div><strong>研究工作台</strong><small>Alpha Research</small></div></div><div className="workspace-name"><span className="workspace-avatar">J</span><span>Junyan / Reed</span><LockKeyhole size={13} /></div><div className="nav-caption">工作空间</div><nav className="primary-nav" aria-label="主导航">{destinations.map(item => {
          const Icon = icons[item.id];
          return <button key={item.id} onClick={() => navigate(item.id)} aria-current={route === item.id ? 'page' : undefined}><Icon size={19} strokeWidth={1.7} /><span>{item.label}</span>{route === item.id && <span className="nav-active-dot" />}</button>;
        })}</nav><div className="sidebar-footer"><div><span className="preview-dot" />隔离预览</div><span>本机只读 · 正式服务未切换</span><button className="text-button" onClick={() => openEvidence('预览来源', data ? {
          ...data.provenance,
          source: data.source,
          mode: data.mode
        } : resource)}><ShieldCheck size={15} />证据与版本</button></div></aside>
    <div className="workspace-main"><header className="topbar"><span className="mobile-brand">AR <strong>研究工作台</strong></span><span className="breadcrumb">工作空间 <ChevronRight size={13} /> {destinations.find(x => x.id === route)?.label}</span><div className="topbar-right"><span className={`connection ${fresh ? 'connected' : ''}`}><i />{fresh ? '副本可读' : resource.loading && !data ? '读取中' : '读取已过期'}</span><IconButton label="刷新封存副本" onClick={load} disabled={resource.loading}><RefreshCw size={16} className={resource.loading ? 'spinning' : ''} /></IconButton><span className="user-avatar" title="本机隔离预览，不作真人身份认证">J</span></div></header>
    <main><div className="preview-banner"><span><LockKeyhole size={13} />只读预览</span><span>历史资料{data ? ` · ${dateText(data.source.source_trade_date)}` : ''}</span></div>{resource.error && <div className="read-error" role="alert">{resource.error} · 操作不可用</div>}{data && !fresh && <div className="read-error" role="status">核验已过期，以下为上次读取的历史副本。</div>}{data ? <DailyView key={route} route={route} data={data} fresh={fresh} navigate={navigate} onEvidence={openEvidence} /> : <Empty icon={Clock3} title={resource.error ? '暂时无法读取' : '正在核对封存材料'} />}<footer className="page-footer"><span>AR / 研究信号，非买卖指令</span><span>人工研究批准独立保留</span></footer></main></div>{evidence && <Drawer entry={evidence} fresh={fresh} lastSuccessAt={resource.lastSuccessAt} onClose={() => setEvidence(null)} />}</div>;
}

export {Status,IconButton,SectionTitle,Empty,EvidenceLink,Subtabs,PageHeading,TaskRows,ReportDetail,Drawer};
