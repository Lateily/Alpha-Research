import React, { useEffect, useRef, useState } from 'react';
import { Activity, ArrowRight, CalendarClock, Check, ClipboardCheck, Database, Download, FileText, Layers3, ListFilter, LockKeyhole, Play, Plus, RefreshCw, Save, Search, Send, ShieldCheck, Wallet, X } from 'lucide-react';
export const workspaceTabs = [['desk', '研究总览', Layers3], ['nightly', '夜链与计划', CalendarClock], ['macro', '宏观与数据', Activity], ['models', '模型与方法', ShieldCheck], ['candidates', '候选证据', ListFilter], ['drafts', '研究稿', FileText], ['reviews', '提交与审核', ClipboardCheck], ['paper', '模拟盘与归因', Wallet], ['records', '数据与审计', Database]];
const jobLabels = {
  observe: '只读数据快照',
  integrity: '本地完整性检查',
  'research-replay': '固定研究用例回放',
  backup: '备份与恢复自检'
};
const labels = {
  title: '研究标题',
  ticker: '标的 / 行业',
  thesis: 'Thesis 与可判定预期',
  valuation: '估值依据与情景',
  timing: '择时结构与 WAIT 条件',
  invalidation: '失效条件',
  evidence_ref: '证据来源与时点'
};
const newContent = () => Object.fromEntries(Object.keys(labels).map(k => [k, '']));
const id = prefix => `${prefix}_${crypto.randomUUID()}`;
const fmt = value => typeof value === 'number' ? value.toLocaleString('zh-CN', {
  maximumFractionDigits: 2
}) : '—';
const show = value => value == null ? 'UNAVAILABLE' : typeof value === 'object' ? JSON.stringify(value) : String(value);
const dateTime = epoch => new Date(epoch * 1000).toLocaleString('zh-CN', {
  timeZone: 'Asia/Shanghai',
  hour12: false
});
function Status({
  value
}) {
  const tone = /MISSING|INVALID|INCOMPLETE|FAILED|ERROR|STOP|REJECT/.test(value || '') ? 'red' : /STALE|BLOCKED|PARTIAL|UNBOUND|WAIT|DRAFT|IN_REVIEW/.test(value || '') ? 'amber' : /OK|SUCCEEDED|MATCH|ACCEPTED/.test(value || '') ? 'green' : 'neutral';
  return <span className={`badge ${tone}`}>{value || 'UNAVAILABLE'}</span>;
}
function Table({
  heads,
  children
}) {
  return <div className="table-scroll workspace-table"><table><thead><tr>{heads.map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>;
}
function Empty({
  title
}) {
  return <div className="empty"><Database size={26} /><h3>{title}</h3></div>;
}
function exportJSON(name, value) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + '\n'], {
    type: 'application/json'
  }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function JsonEvidence({
  title,
  value
}) {
  return <details className="json-evidence"><summary>{title}</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>;
}
function SourceStrip({
  observation
}) {
  if (!observation) return null;
  return <div className="source-strip"><span>数据日期 <strong>{observation.target_trade_date || '未确定'}</strong></span><Status value={observation.freshness.status} /><span>日历年龄 {observation.freshness.calendar_age_days ?? '未知'} 天</span><span>源端状态为历史值 · 未签发生产验收</span></div>;
}
function Chart({
  series
}) {
  const ref = useRef();
  useEffect(() => {
    const canvas = ref.current,
      ctx = canvas.getContext('2d');
    const draw = () => {
      const width = canvas.clientWidth,
        height = 190,
        dpr = window.devicePixelRatio || 1;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, width, height);
      const rows = series.filter(r => Number.isFinite(r.nav));
      if (!rows.length) return;
      const values = rows.map(r => r.nav),
        lo = Math.min(...values),
        hi = Math.max(...values),
        span = hi - lo || 1;
      ctx.font = '11px sans-serif';
      ctx.fillStyle = '#818984';
      ctx.strokeStyle = '#e0e5e2';
      ctx.lineWidth = 1;
      for (let i = 0; i < 4; i++) {
        const y = 14 + i * 46;
        ctx.beginPath();
        ctx.moveTo(65, y);
        ctx.lineTo(width - 16, y);
        ctx.stroke();
        ctx.fillText(fmt(hi - i * span / 3), 0, y + 4);
      }
      ctx.beginPath();
      rows.forEach((r, i) => {
        const x = 65 + i * Math.max(width - 85, 10) / Math.max(rows.length - 1, 1),
          y = 14 + (hi - r.nav) / span * 138;
        if (i) ctx.lineTo(x, y);else ctx.moveTo(x, y);
      });
      ctx.strokeStyle = '#26685d';
      ctx.lineWidth = 2.2;
      ctx.stroke();
      ctx.fillStyle = '#818984';
      ctx.fillText(rows[0].date, 65, 183);
      ctx.fillText(rows.at(-1).date, Math.max(width - 85, 65), 183);
    };
    const resize = new ResizeObserver(draw);
    resize.observe(canvas);
    draw();
    return () => resize.disconnect();
  }, [series]);
  return <canvas ref={ref} className="nav-chart" role="img" aria-label="已发布模拟盘历史净值曲线，非方法有效性证明" />;
}
export default function Workspace({
  tab,
  api,
  reloadBase,
  refreshRevision
}) {
  const [state, setState] = useState(null),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState('');
  const [query, setQuery] = useState(''),
    [industry, setIndustry] = useState('ALL'),
    [page, setPage] = useState(0);
  const [content, setContent] = useState(newContent),
    [documentId, setDocumentId] = useState(null),
    [revision, setRevision] = useState(0);
  const [password, setPassword] = useState(''),
    [confirmation, setConfirmation] = useState(''),
    [reason, setReason] = useState('');
  const [scheduleKind, setScheduleKind] = useState('observe'),
    [intervalMinutes, setIntervalMinutes] = useState(60),
    [pending, setPending] = useState(null);
  async function reload() {
    const data = await api('/api/workspace');
    setState(data);
    return data;
  }
  useEffect(() => {
    reload().catch(e => setError(e.message));
    const timer = window.setInterval(() => reload().catch(e => setError(e.message)), 30000);
    return () => window.clearInterval(timer);
  }, [tab, refreshRevision]);
  async function act(path, body, message = '已记录', onReload = null) {
    setBusy(true);
    setError('');
    setNotice('');
    setPassword('');
    setConfirmation('');
    const request = pending || {
      path,
      body
    };
    setPending(request);
    try {
      await api(request.path, request.body);
      setPending(null);
      const refreshed = await reload();
      if (onReload) onReload(refreshed);
      if (reloadBase) await reloadBase();
      setNotice(message);
    } catch (e) {
      setError(e.message);
      if (e.status && e.status < 500) setPending(null);
    } finally {
      setBusy(false);
    }
  }
  function run(kind) {
    return act('/api/workspace/job', {
      command_id: id('job'),
      kind
    }, '任务已执行，结果见任务记录');
  }
  function edit(doc) {
    setDocumentId(doc.document_id);
    setRevision(doc.revision);
    setContent({
      ...doc.content
    });
  }
  const obs = state?.observation,
    attempt = obs?.attempt || {},
    paper = obs?.paper || {};
  const rows = obs?.candidates || [],
    industries = [...new Set(rows.map(r => r.industry_key).filter(Boolean))].sort();
  const filtered = rows.filter(r => (industry === 'ALL' || industry === r.industry_key) && `${r.ts_code} ${r.industry_key} ${r.review_status}`.toLowerCase().includes(query.toLowerCase()));
  const selectedDoc = state?.documents.find(d => d.document_id === documentId);
  const savedContentMatches = selectedDoc && Object.keys(labels).every(key => selectedDoc.content[key] === content[key]);
  const frozen = selectedDoc && ['IN_REVIEW', 'ACCEPTED_LOCAL'].includes(selectedDoc.status);
  const inReview = state?.documents.filter(d => d.status === 'IN_REVIEW') || [];
  const macroRegions = obs?.macro?.macro_state?.payload?.data?.regions || {};
  return <div className="workspace-surface">
    {error && <div className="alert error" role="alert"><X size={16} /><code>{error}</code></div>}
    {notice && <div className="alert success" role="status"><Check size={16} />{notice}</div>}
    {pending && !busy && <div className="pending-actions"><button onClick={() => act(pending.path, pending.body)}><RefreshCw size={15} />核对同一请求</button><button onClick={() => {
        setPending(null);
        setError('');
      }}>结束待核请求</button></div>}
    {!state ? <Empty title="工作台状态读取中" /> : <>
      {state.observation_error && <div className="alert error" role="alert">{state.observation_error}</div>}
      {['desk', 'nightly', 'macro', 'candidates', 'paper'].includes(tab) && <SourceStrip observation={obs} />}
      {tab === 'desk' && <>
        <div className="workspace-metrics"><article><span>最后公开数据</span><strong>{obs?.target_trade_date || '未导入'}</strong><Status value={obs?.freshness.status || 'NO_SNAPSHOT'} /></article><article><span>最近夜链尝试</span><strong>{attempt.report || '未观察'}</strong><span>{attempt.generated_at || '没有运行凭证'}</span></article><article><span>本地待审核</span><strong>{inReview.length}<small>份</small></strong><span>不等于正式 U4 授权</span></article><article><span>本入口已付费用</span><strong>0<small>CNY</small></strong><span>DeepSeek 与云资源未启用</span></article></div>
        <section><div className="section-title"><h2>今日运行台账</h2><button className="primary" disabled={busy || !state.read_only_source_configured || !!pending} onClick={() => run('observe')}><RefreshCw size={16} />读取本地实物</button></div><div className="status-lines"><div><span>最后公开 run</span><code>{obs?.published_run_id || 'UNAVAILABLE'}</code></div><div><span>最近尝试 run</span><code>{attempt.run_id || 'UNAVAILABLE'}</code></div><div><span>公开文件观察</span><Status value={obs ? `${obs.issues.length} ISSUES` : 'NOT_OBSERVED'} /></div><div><span>宏观运行权限</span><Status value="CALIBRATING / NO_BLOCKING_AUTHORITY" /></div><div><span>正式交易 / 生产切换</span><Status value="DISABLED" /></div></div></section>
        <section><div className="section-title"><h2>研究闭环</h2><Status value="LOCAL WORKSPACE / WORKFLOW_DEBUG" /></div><div className="workflow-rail">{[['数据采集', '旧生产只读观察'], ['U1–U3 筛选', '实物候选 / 缺数保留'], ['深研与估值', '人类稿件 / 版本冻结'], ['审核', '本地稿件审核'], ['模拟成交', '隔离合成回放'], ['五轴复盘', '回放工件与归因']].map(([title, sub], i) => <div key={title}><span>{String(i + 1).padStart(2, '0')}</span><h3>{title}</h3><p>{sub}</p>{i < 5 && <ArrowRight size={14} />}</div>)}</div></section>
        <section><div className="section-title"><h2>最近工作记录</h2><button className="icon-button" title="导出本地审计记录" onClick={() => exportJSON('workspace-events.json', state.events)}><Download size={16} /></button></div><Table heads={['时间（北京时间）', '事件', '序号 / hash']}>{[...state.events].reverse().slice(0, 8).map(e => <tr key={e.seq}><td>{dateTime(e.at)}</td><td>{e.kind}</td><td><code>{e.seq} / {e.event_hash.slice(0, 16)}</code></td></tr>)}</Table>{!state.events.length && <Empty title="尚无本地工作记录" />}</section>
      </>}
      {tab === 'nightly' && <>
        <section><div className="section-title"><h2>旧生产最近尝试</h2><Status value={attempt.report} /></div><div className="step-grid">{(attempt.steps || []).map((s, i) => <article key={s.step} className={s.status === 'OK' ? 'step-ok' : 'step-gap'}><span>{String(i + 1).padStart(2, '0')}</span><h3>{s.step}</h3><Status value={s.status} /><small>{s.elapsed_sec == null ? '—' : `${s.elapsed_sec}s`}</small></article>)}</div>{!attempt.steps?.length && <Empty title="尚无夜链状态快照" />}</section>
        <section><div className="section-title"><h2>本地计划任务</h2><Status value={state.scheduler.status} /></div><div className="source-strip"><span>服务器运行且电脑唤醒时执行</span><span>错过时段不补跑</span><span>新任务默认不启用 · 无实时采集权</span></div><div className="toolbar">{Object.entries(jobLabels).map(([kind, label]) => <button key={kind} disabled={busy || !!pending} onClick={() => run(kind)}><Play size={14} />{label}</button>)}</div><Table heads={['任务', '频率', '状态', '变更']}>{state.schedules.map(s => <tr key={s.schedule_id}><td>{jobLabels[s.kind]}</td><td>{s.interval_minutes} 分钟</td><td><Status value={s.enabled ? 'ENABLED_LOCAL' : 'PAUSED'} /></td><td><button disabled={busy || !password || !!pending} onClick={() => act('/api/workspace/schedule', {
                  command_id: id('schedule'),
                  schedule_id: s.schedule_id,
                  expected_revision: s.revision,
                  kind: s.kind,
                  interval_minutes: s.interval_minutes,
                  enabled: !s.enabled,
                  password
                })}>{s.enabled ? '暂停' : '启用'}</button></td></tr>)}</Table>
          <form className="schedule-form" onSubmit={e => {
            e.preventDefault();
            act('/api/workspace/schedule', {
              command_id: id('schedule'),
              schedule_id: id('plan'),
              expected_revision: 0,
              kind: scheduleKind,
              interval_minutes: Number(intervalMinutes),
              enabled: false,
              password
            }, '计划已保存为暂停状态');
          }}><label>任务类型<select value={scheduleKind} onChange={e => setScheduleKind(e.target.value)}>{Object.entries(jobLabels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label><label>间隔（分钟）<input type="number" min="10" max="10080" value={intervalMinutes} onChange={e => setIntervalMinutes(e.target.value)} /></label><label>本地管理员口令<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label><button type="submit" disabled={busy || !state.owner_configured || !!pending}><Plus size={16} />新增暂停计划</button></form></section>
        <section><div className="section-title"><h2>新载体执行记录</h2><Status value="OFFLINE ONLY" /></div><Table heads={['任务 ID', '类型', '状态', '实物结果']}>{[...state.jobs].reverse().map(j => <tr key={j.job_id}><td><code>{j.job_id}</code></td><td>{jobLabels[j.kind]}</td><td><Status value={j.status} />{j.status === 'STARTED' && <p>运行中或中断未收尾；不自动重复</p>}</td><td><JsonEvidence title="结果回执" value={j.result} /></td></tr>)}</Table></section>
      </>}
      {tab === 'macro' && <>
        <section><div className="section-title"><h2>四轴宏观面板</h2><Status value="CALIBRATING" /></div>{['CN','US'].map(region => <div key={region}><h3 className="region-heading">{region === 'CN' ? '中国' : '美国'}</h3><div className="macro-axes">{[['GROWTH','增长'],['INFLATION','通胀'],['LIQUIDITY','流动性'],['RISK','风险偏好']].map(([key,axis]) => {const row=macroRegions[region]?.axes?.[key]; return <article key={key}><Activity size={18}/><h3>{axis}</h3><strong>{row?.label || 'UNAVAILABLE'}</strong><Status value={row?.data_status || 'DATA_BLOCKED'}/></article>;})}</div></div>)}{obs?.macro?.macro_panel?.payload && <JsonEvidence title="四轴源契约（未经本工作台重新推断）" value={obs.macro.macro_panel.payload} />}</section>
        <section><div className="section-title"><h2>宏观产物与来源</h2><span>不以旧版 macro_gate 补齐四轴</span></div><Table heads={['契约', '文件状态', '哈希绑定', '内容']}>{Object.entries(obs?.macro || {}).map(([name, record]) => <tr key={name}><td>{name}</td><td><Status value={record.status} /></td><td><Status value={record.binding} /></td><td>{record.payload ? <JsonEvidence title="原始契约" value={record.payload} /> : '缺失'}</td></tr>)}</Table></section>
        <section><div className="section-title"><h2>旧版宏观上下文</h2><Status value="LEGACY / REVIEW_CONTEXT_ONLY" /></div><span className="muted">源文件生成于 {obs?.macro_legacy?.generated_at || '未知'}，下列数值不是本轮采集</span><Table heads={['指标', '源报告期', '历史值', '前值']}>{(obs?.macro_legacy?.items || []).map(row => <tr key={row.endpoint}><td>{row.endpoint}</td><td>{row.as_of}</td><td>{fmt(row.actual)} {row.unit}</td><td>{fmt(row.previous)}</td></tr>)}</Table></section>
        <section><div className="section-title"><h2>半导体正向输入</h2><Status value={obs?.feature?.semiconductor_positive_inputs?.status} /></div><Table heads={['数据源', '源端状态', '行数', '阻断原因']}>{Object.entries(obs?.feature?.semiconductor_positive_inputs?.sources || {}).map(([name, row]) => <tr key={name}><td>{name}</td><td><Status value={row.status} /></td><td>{row.row_count ?? '—'}</td><td>{(row.reason_codes || []).join(', ') || '—'}</td></tr>)}</Table><JsonEvidence title="完整数据健康契约" value={obs?.feature || {
            status: 'NO_SNAPSHOT'
          }} /></section>
      </>}
      {tab === 'candidates' && <>
        <section><div className="section-title"><h2>候选池与排除样本</h2><Status value="OBSERVATION ONLY / NO SELECT" /></div><div className="toolbar"><label className="search"><Search size={16} /><input aria-label="搜索候选" placeholder="代码、行业或状态" value={query} onChange={e => {
                setQuery(e.target.value);
                setPage(0);
              }} /></label><select aria-label="行业过滤" value={industry} onChange={e => {
              setIndustry(e.target.value);
              setPage(0);
            }}><option value="ALL">全部行业</option>{industries.map(i => <option key={i}>{i}</option>)}</select><span className="muted">{filtered.length} 行</span><button className="icon-button" title="导出观察候选（非裁决）" onClick={() => exportJSON('candidate-observation.json', {
              sample_purpose: 'WORKFLOW_DEBUG',
              snapshot_hash: obs?.snapshot_hash,
              rows: filtered
            })}><Download size={16} /></button></div><Table heads={['代码', '行业', '原始状态', '通道与排除依据']}>{filtered.slice(page * 30, (page + 1) * 30).map((r, i) => <tr key={`${r.ts_code}-${i}`}><td><code>{r.ts_code}</code></td><td>{r.industry_key}</td><td><Status value={r.review_status} /></td><td><span>{(r.source_channels || []).join(' · ')}</span><p className="muted">{r.exclusion_reason || (r.flags || []).join(' · ') || '—'}</p><JsonEvidence title="本行原始证据" value={r} /></td></tr>)}</Table><div className="pagination"><button disabled={!page} onClick={() => setPage(page - 1)}>上一页</button><span>{page + 1} / {Math.max(1, Math.ceil(filtered.length / 30))}</span><button disabled={(page + 1) * 30 >= filtered.length} onClick={() => setPage(page + 1)}>下一页</button></div></section>
      </>}
      {tab === 'models' && <>
        <section><div className="section-title"><h2>执行模块与版本</h2><Status value="NO AUTONOMOUS PROMOTION"/></div><Table heads={['模块','当前接入方式','代码状态','SHA256']}>{(state.catalog?.modules || []).map(m=><tr key={m.name}><td>{m.name}</td><td><Status value={m.mode}/></td><td><Status value={m.status}/><code>{m.path}</code></td><td><code>{m.source_sha256 || 'UNAVAILABLE'}</code></td></tr>)}</Table></section>
        <section><div className="section-title"><h2>半导体方法卡</h2><span>{state.catalog?.methods?.cards?.length || 0} 张 · REVIEWED 不等于 VALIDATED</span></div><Status value={state.catalog?.methods?.status}/><Table heads={['方法','状态 / 证据层级','逻辑类型 / 数据获取','依据与证伪条件']}>{(state.catalog?.methods?.cards || []).map(card=><tr key={card.card_id}><td><strong>{card.variable}</strong><p><code>{card.card_id}</code></p></td><td><Status value={card.status}/><p>{card.evidence_tier} / {card.sub_sector}</p></td><td><span>{card.judgment_logic.type}</span><p>{card.data_source.availability}</p><JsonEvidence title="实际采集覆盖" value={card.collection_coverage}/></td><td><JsonEvidence title="完整研究方法卡" value={card}/></td></tr>)}</Table></section>
        <div className="source-strip"><span>方法迭代：提出修改 → 离线检查 → 独立复审 → Junyan 批准</span><span>模型不能自改准入规则、自动晋级方法或绕过人类</span></div>
      </>}
      {tab === 'drafts' && <>
        <section><div className="section-title"><h2>人类研究稿</h2><button disabled={busy} onClick={() => {
              setContent(newContent());
              setDocumentId(null);
              setRevision(0);
            }}><Plus size={16} />新稿</button></div><Table heads={['标题', '标的 / 行业', '版本 / 状态', '操作']}>{state.documents.map(d => <tr key={d.document_id}><td>{d.content.title}</td><td>{d.content.ticker || '未填'}</td><td>v{d.revision} <Status value={d.status} /></td><td><button onClick={() => edit(d)}><FileText size={15} />打开</button><button className="icon-button" title="导出版本" onClick={() => exportJSON(`${d.document_id}.json`, d)}><Download size={15} /></button></td></tr>)}</Table></section>
        <section><div className="section-title"><h2>{documentId ? `稿件 v${revision}` : '新建研究稿'}</h2><Status value={selectedDoc?.status || 'DRAFT'} /></div><form className="research-form" onSubmit={e => {
            e.preventDefault();
            const docId = documentId || id('doc');
            setDocumentId(docId);
            act('/api/workspace/draft', {
              command_id: id('save'),
              document_id: docId,
              expected_revision: revision,
              content
            }, '稿件版本已保存', s => {
              const d = s.documents.find(x => x.document_id === docId);
              if (d) setRevision(d.revision);
            });
          }}>{Object.entries(labels).map(([key, label]) => <label key={key} className={key === 'title' || key === 'ticker' ? '' : 'wide'}><span>{label}</span>{key === 'title' || key === 'ticker' ? <input aria-label={label} value={content[key]} disabled={frozen} maxLength={200} onChange={e => setContent({
                ...content,
                [key]: e.target.value
              })} /> : <textarea aria-label={label} value={content[key]} disabled={frozen} maxLength={12000} rows={4} onChange={e => setContent({
                ...content,
                [key]: e.target.value
              })} />}</label>)}<div className="form-footer"><span>本地工作稿 · 非 sealed case / 非正式研究登记</span><div className="actions"><button type="submit" disabled={busy || frozen || !!pending}><Save size={16} />保存版本</button><button className="primary" type="button" disabled={busy || !selectedDoc || selectedDoc.status !== 'DRAFT' || !!pending || !savedContentMatches} onClick={() => act('/api/workspace/submit', {
                  command_id: id('submit'),
                  document_id: documentId,
                  revision: selectedDoc.revision,
                  content_hash: selectedDoc.content_hash
                }, '版本已冻结并进入本地待审核')}><Send size={16} />提交审核</button></div></div></form>{selectedDoc?.review && <JsonEvidence title="上一轮审核记录" value={selectedDoc.review} />}</section>
      </>}
      {tab === 'reviews' && <>
        <section><div className="section-title"><h2>本地审核身份</h2><Status value={state.owner_configured ? 'LOCAL OWNER CONFIGURED' : 'NOT CONFIGURED'} /></div>{!state.owner_configured ? <form className="config-form" onSubmit={e => {
            e.preventDefault();
            act('/api/workspace/owner', {
              password,
              confirmation
            }, '本地管理员口令已设置；团队与生产权限未改变');
          }}><label>本地管理员口令（至少 14 字符）<input type="password" autoComplete="new-password" minLength={14} value={password} onChange={e => setPassword(e.target.value)} /></label><label>再次输入<input type="password" autoComplete="new-password" value={confirmation} onChange={e => setConfirmation(e.target.value)} /></label><button type="submit" disabled={busy || !!pending}><LockKeyhole size={16} />设置本地口令</button></form> : <label className="owner-input">本地管理员口令<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>}<div className="source-strip"><span>只批准本地稿件版本，不签发 U4、模拟盘注册、团队或生产权限</span><span>本机账户不等于真实人类身份认证</span></div></section>
        <section><div className="section-title"><h2>待审核稿件</h2><span>{inReview.length} 份</span></div><label className="review-reason">审核理由<textarea aria-label="审核理由" value={reason} maxLength={2000} onChange={e => setReason(e.target.value)} rows={3} /></label>{inReview.map(d => <article className="review-item" key={d.document_id}><div className="section-title"><h3>{d.content.title} · v{d.revision}</h3><code>{d.content_hash.slice(0, 16)}</code></div><JsonEvidence title="冻结全文" value={d.content} /><div className="actions">{[['ACCEPTED_LOCAL', '接受稿件'], ['CHANGES_REQUESTED', '退回修改'], ['REJECTED_LOCAL', '不接受']].map(([outcome, label]) => <button key={outcome} disabled={busy || !state.owner_configured || !password || !reason.trim() || !!pending} onClick={() => act('/api/workspace/review', {
                command_id: id('review'),
                document_id: d.document_id,
                revision: d.revision,
                content_hash: d.content_hash,
                outcome,
                reason,
                password
              }, '审核意见已绑定冻结版本')}><ClipboardCheck size={15} />{label}</button>)}</div></article>)}{!inReview.length && <Empty title="没有待审核稿件" />}</section>
      </>}
      {tab === 'paper' && <>
        <div className="workspace-metrics"><article><span>历史已发布 NAV</span><strong>{fmt(typeof paper.nav_latest === 'object' ? paper.nav_latest?.nav : paper.nav_latest)}</strong><span>账面 CNY · 非当前实盘</span></article><article><span>历史现金</span><strong>{fmt(paper.cash)}</strong><span>源端 paper 账本</span></article><article><span>历史未平仓</span><strong>{paper.open_positions?.length ?? '—'}</strong><span>只读，不产生交易动作</span></article><article><span>方法有效性</span><strong className="small-metric">不作声称</strong><span>独立样本未在此验收</span></article></div><section><div className="section-title"><h2>已发布模拟盘历史净值</h2><Status value="HISTORICAL SNAPSHOT" /></div>{paper.nav_series?.length ? <Chart series={paper.nav_series} /> : <Empty title="没有净值实物" />}</section><section><div className="section-title"><h2>持仓与成交记录</h2><button className="icon-button" title="下载历史模拟盘快照" onClick={() => exportJSON('paper-observation.json', {
              sample_purpose: 'WORKFLOW_DEBUG',
              source_date: obs?.target_trade_date,
              paper
            })}><Download size={16} /></button></div><JsonEvidence title={`未平仓 ${paper.open_positions?.length ?? '未知'} 条`} value={paper.open_positions} /><JsonEvidence title={`历史平仓 ${paper.closed_trades_n ?? '未知'} 条`} value={paper.closed_trades} /></section><section><div className="section-title"><h2>新载体规则执行</h2><Status value="SYNTHETIC / WORKFLOW_DEBUG" /></div><div className="status-lines"><div><span>成交与出场</span><span>复用 model_paper_fund / paper_portfolio</span></div><div><span>归因</span><span>Thesis / Valuation / Timing / Execution / Market beta</span></div><div><span>人类稿件 → 正式注册</span><Status value="PRODUCTION_UNWIRED" /></div></div><button disabled={busy || !!pending} onClick={() => run('research-replay')}><Play size={16} />运行固定规则回放</button></section>
      </>}
      {tab === 'records' && <>
        <section><div className="section-title"><h2>本地完整性</h2><div className="actions"><button disabled={busy || !!pending} onClick={() => run('integrity')}><ShieldCheck size={16} />重新检查</button><button onClick={() => exportJSON('workspace-audit-export.json', state)}><Download size={16} />导出审计包</button></div></div><div className="status-lines"><div><span>最近快照 SHA256</span><code>{obs?.snapshot_hash || 'UNAVAILABLE'}</code></div><div><span>事件链尾</span><code>{state.events.at(-1)?.event_hash || 'EMPTY'}</code></div><div><span>数据库保护</span><span>事务 + UPDATE/DELETE 触发器 + 逐行 hash；不抵御主机管理员重写</span></div></div></section><section><div className="section-title"><h2>观察文件目录</h2><span>{obs?.files?.length || 0} 文件</span></div><Table heads={['文件', '读取状态', '源端哈希绑定', 'SHA256']}>{(obs?.files || []).map(f => <tr key={f.path}><td><code>{f.path}</code></td><td><Status value={f.status} /></td><td><Status value={f.binding} /></td><td><code>{f.source_sha256 || 'UNAVAILABLE'}</code></td></tr>)}</Table></section><section><div className="section-title"><h2>追加事件</h2><span>{state.events.length} 条</span></div><Table heads={['序号', '时间（北京时间）', '动作', '冻结内容']}>{[...state.events].reverse().map(e => <tr key={e.seq}><td>{e.seq}</td><td>{dateTime(e.at)}</td><td>{e.kind}</td><td><JsonEvidence title={e.command_id} value={e} /></td></tr>)}</Table></section>
      </>}
    </>}
  </div>;
}
