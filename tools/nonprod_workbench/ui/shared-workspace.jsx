import React, { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Database, Download, FileText, Play, RefreshCw, Users, X } from 'lucide-react';
import { statusTone } from './status-tone.mjs';
import { latestOwnedJob, sharedQueryState } from './shared-view.mjs';

const views = [['my', '我的任务', FileText], ['team', '团队结果', Users], ['common', '共同数据', Database]];
function Status({ value }) {
  return <span className={`badge ${statusTone(value)}`}>{value || 'NOT_PRODUCED'}</span>;
}
function download(name, value, type = 'application/json') {
  const blob = new Blob([typeof value === 'string' ? value : JSON.stringify(value, null, 2)], { type });
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url);
}

export default function SharedWorkspace({ api, access, refreshRevision }) {
  const [view, setView] = useState('my'), [page, setPage] = useState(0);
  const [query, setQuery] = useState({ data: null, connection: 'WAIT', stale: false, error: '' });
  const [busy, setBusy] = useState(false), [pending, setPending] = useState(null);
  const [detail, setDetail] = useState(null), [selected, setSelected] = useState(null), [detailError, setDetailError] = useState('');
  const sequence = useRef(0), detailSequence = useRef(0);
  async function reload() {
    const request = ++sequence.current;
    try {
      const data = await api(`/api/shared-workspace?page=${page}`);
      if (request === sequence.current) setQuery(previous => sharedQueryState(previous, data));
    } catch (error) {
      if (request === sequence.current) setQuery(previous => sharedQueryState(previous, null, error.message));
    }
  }
  useEffect(() => {
    reload();
    const timer = window.setInterval(reload, 5000);
    return () => { window.clearInterval(timer); ++sequence.current; };
  }, [page, refreshRevision]);
  async function open(jobId) {
    const request = ++detailSequence.current;
    setSelected(jobId); setDetail(null); setDetailError('');
    try {
      const data = await api(`/api/shared-workspace/jobs/${encodeURIComponent(jobId)}`);
      if (request === detailSequence.current) setDetail(data);
    } catch (error) {
      if (request === detailSequence.current) setDetailError(error.message);
    }
  }
  async function run(kind) {
    const body = pending || { command_id: `shared_${crypto.randomUUID().replaceAll('-', '')}`, kind };
    setPending(body); setBusy(true);
    try {
      const receipt = await api('/api/workspace/job', body);
      setPending(null); await reload(); await open(receipt.job_id);
    } catch (error) {
      setQuery(previous => sharedQueryState(previous, null, error.message));
    } finally { setBusy(false); }
  }
  const data = query.data, login = data?.my_workspace.login || access.login;
  const latest = latestOwnedJob(data?.latest_owned_jobs || data?.my_jobs || [], login, 'snapshot-brief');
  const rows = view === 'my' ? data?.my_jobs || [] : data?.team_jobs || [];
  const total = view === 'my' ? data?.my_total || 0 : data?.team_total || 0;
  const common = data?.common_data, observation = common?.observation;
  return <div className="workspace-surface shared-workspace">
    <div className="shared-heading"><div><h2>共享研究工作台</h2><code>{login}</code></div>
      <div className="shared-status"><Status value={query.connection} /><button className="icon-button" title="刷新" aria-label="刷新共享工作区" onClick={reload}><RefreshCw size={17} /></button></div>
    </div>
    <div className="source-strip"><span>WORKFLOW_DEBUG</span><span>人工核验 PENDING</span><span>生产 / 交易权限 false</span><span>最新本人简报 <Status value={query.stale ? 'DISCONNECTED' : latest?.status} /></span></div>
    {query.error && <div className="shared-error" role="alert">DISCONNECTED · {query.error}</div>}
    <nav className="shared-tabs" aria-label="共享工作区视图">{views.map(([key, label, Icon]) => <button key={key} aria-current={view === key ? 'page' : undefined} onClick={() => { setView(key); setPage(0); }}><Icon size={16} />{label}</button>)}</nav>
    {view !== 'common' ? <>
      <div className="shared-toolbar"><span>{total} 个任务</span>{view === 'my' && <div><button disabled={busy || !!pending} onClick={() => run('observe')}><Database size={16} />观察</button><button className="primary" disabled={busy || !!pending} onClick={() => run('snapshot-brief')}><Play size={16} />{busy ? '执行中' : '生成简报'}</button>{pending && !busy && <button onClick={() => run(pending.kind)}><RefreshCw size={16} />核对原请求</button>}</div>}</div>
      <div className="shared-job-list">{rows.map(job => <button className="shared-job-row" key={job.job_id} onClick={() => open(job.job_id)}>
        <div><code>{job.job_id}</code><span>{job.actor}</span><span>{job.kind} · {new Date(job.submitted_at * 1000).toLocaleString()}</span></div>
        <div><Status value={query.stale ? 'DISCONNECTED' : job.status} />{job.error && <span className="text-red">{job.error}</span>}<code>{job.input_hash || 'INPUT_NOT_BOUND'}</code></div><ChevronRight size={16} />
      </button>)}{!rows.length && <p className="shared-empty">{data ? '暂无任务' : 'WAIT'}</p>}</div>
      <div className="shared-pagination"><button className="icon-button" title="上一页" aria-label="上一页" disabled={!page} onClick={() => setPage(p => p - 1)}><ChevronLeft size={17} /></button><span>{page + 1} / {Math.max(1, Math.ceil(total / 50))}</span><button className="icon-button" title="下一页" aria-label="下一页" disabled={(page + 1) * 50 >= total} onClick={() => setPage(p => p + 1)}><ChevronRight size={17} /></button></div>
    </> : <section className="shared-common">
      <div className="section-title"><h3>共同数据</h3><Status value={common?.error || common?.sync_status || 'NOT_PRODUCED'} /></div>
      {observation ? <><div className="shared-source-identities">{[['最新尝试', observation.run_identity.latest_attempt], ['最后发布', observation.run_identity.last_published], ['当前观察', observation.run_identity.displayed]].map(([label, identity]) => <div key={label}><h3>{label}</h3><code>{identity.run_id || 'NOT_PRODUCED'}</code><span>{identity.target_trade_date || 'UNBOUND'}</span>{identity.report && <Status value={identity.report} />}{identity.snapshot_hash && <code>{identity.snapshot_hash}</code>}</div>)}</div>
        <div className="table-scroll"><table><thead><tr><th>模块</th><th>源身份</th><th>身份 / 质量</th></tr></thead><tbody>{(observation.module_sources || []).map((item, i) => <tr key={i}><td>{item.module}</td><td><code>{item.run_id || 'UNBOUND'}</code><span>{item.source_trade_date || 'UNBOUND'}</span></td><td><Status value={item.identity_status} /><Status value={item.data_quality} /></td></tr>)}</tbody></table></div>
        <details><summary>来源与质量</summary><pre>{JSON.stringify(observation, null, 2)}</pre></details></> : <p className="shared-empty">{common?.error || 'NOT_PRODUCED'}</p>}
    </section>}
    {selected && <section className="shared-detail"><div className="section-title"><h3>任务详情</h3><div><button className="icon-button" title="重新验证" aria-label="重新验证任务" onClick={() => open(selected)}><RefreshCw size={17} /></button><button className="icon-button" title="关闭详情" aria-label="关闭任务详情" onClick={() => { ++detailSequence.current; setSelected(null); setDetail(null); }}><X size={17} /></button></div></div><code>{selected}</code>
      {detailError && <div role="alert" className="shared-error">DISCONNECTED · {detailError}</div>}
      {detail ? <><div className="source-strip"><Status value={detail.status} /><code>{detail.actor}</code><code>{detail.workspace_id || 'LEGACY_UNATTRIBUTED'}</code></div><dl>{[['执行版本', detail.code_sha], ['输入 hash', detail.input_hash], ['输出 hash', detail.output_hash], ['失败原因', detail.error]].map(([label, value]) => <React.Fragment key={label}><dt>{label}</dt><dd><code>{value || 'NOT_PRODUCED'}</code></dd></React.Fragment>)}</dl>
        <div className="shared-toolbar"><button onClick={() => download(`${selected}.json`, detail)}><Download size={16} />任务回执</button>{detail.report && <><button onClick={() => download(`${selected}.md`, detail.report, 'text/markdown')}><Download size={16} />报告</button><button onClick={() => download(`${selected}-citations.json`, detail.citations)}><Download size={16} />引用</button></>}</div>
        {detail.report && <pre className="shared-report">{detail.report}</pre>}<details><summary>步骤与引用</summary><pre>{JSON.stringify({ result: detail.result, citations: detail.citations }, null, 2)}</pre></details></> : !detailError && <p>WAIT</p>}
    </section>}
  </div>;
}
