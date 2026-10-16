import React, { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Database, Download, FileText, Play, RefreshCw, Users, X } from 'lucide-react';
import { statusTone } from './status-tone.mjs';
import { commonSyncView, createSharedPoller, getPending, latestOwnedJob, pollSharedPending, recordSubmissionFailure, retainedStatus, retrySharedPending, savePending, sharedActorQuery, sharedQueryState, sharedRead, sharedViewFreshness } from './shared-view.mjs';

const views = [['my', '我的任务', FileText], ['team', '团队结果', Users], ['common', '共同数据', Database]];
function Status({ value, stale = false }) {
  const display = retainedStatus(value, stale);
  return <span className={`badge ${statusTone(display)}`}>{display || 'NOT_PRODUCED'}</span>;
}
function download(name, value, type = 'application/json') {
  const blob = new Blob([typeof value === 'string' ? value : JSON.stringify(value, null, 2)], { type });
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url);
}

export default function SharedWorkspace({ api, access, refreshRevision }) {
  const [view, setView] = useState('my'), [page, setPage] = useState(0);
  const [query, setQuery] = useState({ data: null, connection: 'WAIT', stale: false, error: '' });
  const [busy, setBusy] = useState(false), [pending, setPending] = useState([]);
  const [detail, setDetail] = useState(null), [selected, setSelected] = useState(null), [detailError, setDetailError] = useState('');
  const [detailStale, setDetailStale] = useState(false);
  const poller = useRef(null), selectedRef = useRef(null), detailSequence = useRef(0), detailLoading = useRef(null);
  const [now, setNow] = useState(Date.now);
  const actorContext = useRef({ login: access.login });
  if (actorContext.current.login !== access.login) actorContext.current = { login: access.login };
  const visibleQuery = sharedActorQuery(query, access.login);
  selectedRef.current = selected;
  async function renew() {
    const response = await fetch('/', { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new Error('SESSION_RENEWAL_FAILED');
  }
  function reload() { return poller.current?.refresh(); }
  useEffect(() => {
    const context = actorContext.current;
    const current = createSharedPoller({
      read: () => sharedRead(api, `/api/shared-workspace?page=${page}`, renew),
      apply: async data => {
        if (actorContext.current !== context) return;
        if (data.my_workspace.login !== access.login) throw new Error('SHARED_IDENTITY_CHANGED');
        const workspaceId = data.my_workspace.workspace_id;
        setQuery(previous => sharedQueryState(previous, data));
        await pollSharedPending(api, window.localStorage, workspaceId, data.owned_commands || {}, renew);
        if (poller.current !== current || actorContext.current !== context) return;
        setPending(getPending(window.localStorage, workspaceId));
        if (selectedRef.current) await open(selectedRef.current, false);
      },
      fail: error => {
        if (actorContext.current !== context) return;
        setQuery(previous => sharedQueryState(previous, null, error.message));
        setDetailStale(true);
      }
    });
    poller.current = current; current.refresh();
    return () => { current.stop(); ++detailSequence.current; };
  }, [page, access.login]);
  useEffect(() => { reload(); }, [refreshRevision]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    ++detailSequence.current;
    selectedRef.current = null;
    setSelected(null); setDetail(null); setDetailStale(true); setBusy(false);
    setPending(getPending(window.localStorage, visibleQuery.data?.my_workspace.workspace_id));
  }, [visibleQuery.data?.my_workspace.workspace_id, access.login]);
  async function open(jobId, select = true) {
    const context = actorContext.current;
    if (!select && (selectedRef.current !== jobId || detailLoading.current !== null)) return;
    const request = ++detailSequence.current;
    detailLoading.current = request;
    if (select) { selectedRef.current = jobId; setSelected(jobId); setDetail(null); }
    setDetailError(''); setDetailStale(true);
    try {
      const data = await sharedRead(api, `/api/shared-workspace/jobs/${encodeURIComponent(jobId)}`, renew);
      if (request === detailSequence.current && actorContext.current === context) { setDetail(data); setDetailStale(false); }
    } catch (error) {
      if (request === detailSequence.current && actorContext.current === context) setDetailError(error.message);
    } finally { if (detailLoading.current === request) detailLoading.current = null; }
  }
  async function run(kind) {
    const context = actorContext.current;
    const workspaceId = visibleQuery.data?.my_workspace.workspace_id;
    const snapshotId = visibleQuery.data?.common_data.current_snapshot_id;
    if (!workspaceId || !snapshotId || sharedViewFreshness(visibleQuery).commonStale) return;
    const body = { command_id: `shared_${crypto.randomUUID().replaceAll('-', '')}`, kind, snapshot_id: snapshotId };
    setBusy(true);
    try {
      savePending(window.localStorage, workspaceId, body);
      setPending(getPending(window.localStorage, workspaceId));
      const receipt = await api('/api/workspace/job', body);
      if (actorContext.current !== context) return;
      savePending(window.localStorage, workspaceId, body, receipt.job_id);
      await reload();
      if (actorContext.current === context) await open(receipt.job_id);
    } catch (error) {
      if (actorContext.current !== context) return;
      recordSubmissionFailure(window.localStorage, workspaceId, body.command_id, error);
      setPending(getPending(window.localStorage, workspaceId));
      setQuery(previous => sharedQueryState(previous, null, error.message));
      setDetailStale(true);
    } finally { if (actorContext.current === context) setBusy(false); }
  }
  async function retry(commandId) {
    const context = actorContext.current;
    const workspaceId = visibleQuery.data?.my_workspace.workspace_id;
    if (!workspaceId || sharedViewFreshness(visibleQuery).commonStale || busy) return;
    setBusy(true);
    try {
      const scopedApi = (...args) => {
        if (actorContext.current !== context) throw new Error('SHARED_IDENTITY_CHANGED');
        return api(...args);
      };
      const receipt = await retrySharedPending(scopedApi, window.localStorage, workspaceId, commandId, renew);
      if (actorContext.current !== context) return;
      await reload();
      if (actorContext.current === context) await open(receipt.job_id);
    } catch (error) {
      if (actorContext.current !== context) return;
      recordSubmissionFailure(window.localStorage, workspaceId, commandId, error);
      setPending(getPending(window.localStorage, workspaceId));
      setQuery(previous => sharedQueryState(previous, null, error.message));
      setDetailStale(true);
    } finally { if (actorContext.current === context) setBusy(false); }
  }
  const data = visibleQuery.data, login = data?.my_workspace.login || access.login;
  const visiblePending = data ? pending : [];
  const latest = latestOwnedJob(data?.latest_owned_jobs || data?.my_jobs || [], login, 'snapshot-brief');
  const rows = view === 'my' ? data?.my_jobs || [] : data?.team_jobs || [];
  const total = view === 'my' ? data?.my_total || 0 : data?.team_total || 0;
  const common = data?.common_data, observation = common?.observation;
  const freshness = sharedViewFreshness(visibleQuery, detailStale, now);
  const syncView = commonSyncView(common, freshness.commonStale);
  const syncTime = value => value == null ? 'NOT_CHECKED' : new Date(value * 1000).toLocaleString();
  return <div className="workspace-surface shared-workspace">
    <div className="shared-heading"><div><h2>共享研究工作台</h2><code>{login}</code></div>
      <div className="shared-status"><code>{data?.execution_identity?.code_sha || 'VERSION_UNAVAILABLE'}</code><Status value={freshness.commonStale ? 'DISCONNECTED' : query.connection} /><button className="icon-button" title="刷新" aria-label="刷新共享工作区" onClick={reload}><RefreshCw size={17} /></button></div>
    </div>
    <div className="source-strip"><span>WORKFLOW_DEBUG</span><span>人工核验 PENDING</span><span>生产 / 交易权限 false</span><span>最新本人简报 <Status value={latest?.status} stale={freshness.commonStale} /></span></div>
    {visibleQuery.error && <div className="shared-error" role="alert">DISCONNECTED · {visibleQuery.error}</div>}
    {visiblePending.some(item => !item.job_id) && <div className="source-strip"><Status value="SUBMISSION_UNCONFIRMED" stale={freshness.commonStale} /></div>}
    {!syncView.canBrief && <div className="shared-error" role="status">{freshness.commonStale ? 'DISCONNECTED' : common?.error || 'NO_FROZEN_PUBLICATION'}</div>}
    <nav className="shared-tabs" aria-label="共享工作区视图">{views.map(([key, label, Icon]) => <button key={key} aria-current={view === key ? 'page' : undefined} onClick={() => { setView(key); setPage(0); }}><Icon size={16} />{label}</button>)}</nav>
    {view !== 'common' ? <>
      <div className="shared-toolbar"><span>{total} 个任务</span>{view === 'my' && <div><button disabled={busy || pending.length >= 2 || freshness.commonStale || !common?.current_snapshot_id} onClick={() => run('observe')}><Database size={16} />观察</button><button className="primary" disabled={busy || pending.length >= 2 || freshness.commonStale || !common?.current_snapshot_id} onClick={() => run('snapshot-brief')}><Play size={16} />{busy ? '提交中' : '生成简报'}</button>{pending.length > 0 && !busy && <button onClick={reload}><RefreshCw size={16} />核对原任务</button>}</div>}</div>
      {view === 'my' && visiblePending.filter(item => !item.job_id).map(item => <div className="source-strip" key={item.body.command_id}><code>{item.body.command_id}</code><span>{item.body.kind}</span><code>{item.body.snapshot_id}</code><button disabled={busy || freshness.commonStale} aria-label={`重试原提交 ${item.body.command_id}`} onClick={() => retry(item.body.command_id)}><RefreshCw size={16} />重试原提交</button></div>)}
      <div className="shared-job-list">{rows.map(job => <button className="shared-job-row" key={job.job_id} onClick={() => open(job.job_id)}>
        <div><code>{job.job_id}</code><span>{job.actor}</span><span>{job.kind} · {new Date(job.submitted_at * 1000).toLocaleString()}</span></div>
        <div><Status value={job.status} stale={freshness.commonStale} />{job.error && <span className="text-red">{job.error}</span>}<code>{job.input_hash || 'INPUT_NOT_BOUND'}</code></div><ChevronRight size={16} />
      </button>)}{!rows.length && <p className="shared-empty">{data ? '暂无任务' : 'WAIT'}</p>}</div>
      <div className="shared-pagination"><button className="icon-button" title="上一页" aria-label="上一页" disabled={!page} onClick={() => setPage(p => p - 1)}><ChevronLeft size={17} /></button><span>{page + 1} / {Math.max(1, Math.ceil(total / 50))}</span><button className="icon-button" title="下一页" aria-label="下一页" disabled={(page + 1) * 50 >= total} onClick={() => setPage(p => p + 1)}><ChevronRight size={17} /></button></div>
    </> : <section className="shared-common">
      <div className="section-title"><h3>共同数据</h3><Status value={syncView.status} /></div>
      <dl className="shared-sync-times"><dt>上次检查</dt><dd>{syncTime(syncView.lastCheckedAt)}</dd><dt>上次同步成功</dt><dd>{syncTime(syncView.lastSuccessfulSyncAt)}</dd><dt>验证范围</dt><dd><code>{common?.validation_scope || 'NOT_EVALUATED'}</code></dd><dt>完整夜链验收</dt><dd>NOT_EVALUATED</dd></dl>
      {syncView.error && <div className="shared-error" role="alert">{syncView.error}</div>}
      {freshness.commonStale && <div className="shared-error" role="status">DISCONNECTED · STALE</div>}
      <div className="shared-source-identities">{[['最新尝试', syncView.latestAttempt], ['最后发布', syncView.lastPublished], ['当前冻结输入', syncView.currentSnapshot]].map(([label, identity]) => <div key={label}><h3>{label}</h3><code>{identity.run_id || 'NOT_PRODUCED'}</code><span>{identity.target_trade_date || 'UNBOUND'}</span>{identity.report && <Status value={identity.report} stale={freshness.commonStale} />}{identity.snapshot_hash && <code>{identity.snapshot_hash}</code>}{identity.snapshot_id && <code>{identity.snapshot_id}</code>}</div>)}</div>
      {observation ? <>
        <div className="table-scroll"><table><thead><tr><th>模块</th><th>源身份</th><th>绑定 / 数据状态</th><th>状态依据</th></tr></thead><tbody>{(observation.module_sources || []).map((item, i) => <tr key={i}><td>{item.module}</td><td><code>{item.run_id || 'UNBOUND'}</code><span>{item.source_trade_date || 'UNBOUND'}</span></td><td><Status value={item.identity_status} stale={freshness.commonStale} /><Status value={item.data_quality} stale={freshness.commonStale} /></td><td><code>{item.quality_basis}</code>{item.research_quality && <span>研究核验 {item.research_quality}</span>}</td></tr>)}</tbody></table></div>
        <details><summary>来源与质量</summary><pre>{JSON.stringify(observation, null, 2)}</pre></details></> : <p className="shared-empty">{common?.error || 'NOT_PRODUCED'}</p>}
    </section>}
    {data && selected && <section className="shared-detail"><div className="section-title"><h3>任务详情</h3><div><button className="icon-button" title="重新验证" aria-label="重新验证任务" onClick={() => open(selected)}><RefreshCw size={17} /></button><button className="icon-button" title="关闭详情" aria-label="关闭任务详情" onClick={() => { ++detailSequence.current; selectedRef.current = null; setSelected(null); setDetail(null); }}><X size={17} /></button></div></div><code>{selected}</code>
      {detailError && <div role="alert" className="shared-error">DISCONNECTED · {detailError}</div>}
      {detail ? <>{freshness.detailStale && <div className="shared-error" role="status">DISCONNECTED · STALE</div>}<div className="source-strip"><Status value={detail.status} stale={freshness.detailStale} /><code>{detail.actor}</code><code>{detail.workspace_id || 'LEGACY_UNATTRIBUTED'}</code></div><dl>{[['执行版本', detail.code_sha], ['输入 hash', detail.input_hash], ['输出 hash', detail.output_hash], ['失败原因', detail.error]].map(([label, value]) => <React.Fragment key={label}><dt>{label}</dt><dd><code>{value || 'NOT_PRODUCED'}</code></dd></React.Fragment>)}</dl>
        <div className="shared-toolbar"><button disabled={!freshness.downloadsEnabled} onClick={() => download(`${selected}.json`, detail)}><Download size={16} />任务回执</button>{detail.report && <><button disabled={!freshness.downloadsEnabled} onClick={() => download(`${selected}.md`, detail.report, 'text/markdown')}><Download size={16} />报告</button><button disabled={!freshness.downloadsEnabled} onClick={() => download(`${selected}-citations.json`, detail.citations)}><Download size={16} />引用</button></>}</div>
        {detail.report && <pre className="shared-report">{detail.report}</pre>}<details><summary>步骤与引用</summary><pre>{JSON.stringify({ result: detail.result, citations: detail.citations }, null, 2)}</pre></details></> : !detailError && <p>WAIT</p>}
    </section>}
  </div>;
}
