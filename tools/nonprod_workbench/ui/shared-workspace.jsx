import React, { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Database, Download, FileText, Library, Play, RefreshCw, Users, X } from 'lucide-react';
import { statusTone } from './status-tone.mjs';
import { commonSyncView, createSharedRefreshPair, getPending, latestOwnedJob, pollSharedPending, recordSubmissionFailure, retainedStatus, retrySharedPending, savePending, sharedActorQuery, sharedQueryState, sharedRead, sharedViewFreshness } from './shared-view.mjs';
import DataCenter from './data-center';
import ResearchLibrary from './research-library';
import ResearchCards, { CitationLocations } from './research-cards';
import { cardTaskEvidence, detailReadCurrent, jobDetailReader } from './research-cards-view.mjs';
import ReviewPortal from './review-portal';

const views = [['my', '我的任务', FileText], ['team', '团队结果', Users], ['common', '共同数据', Database], ['research', '研究资料库', Library], ['cards','研究卡',FileText]];
const cardKind='research-cards-review';
const detailKinds=new Set(['observe','snapshot-brief','earnings-review',cardKind]);
const cardStatuses=new Set(['QUEUED','RUNNING','SUCCEEDED','STOP','INTERRUPTED','RECOVERY_REQUIRED']);
function Status({ value, stale = false }) {
  const display = retainedStatus(value, stale);
  return <span className={`badge ${statusTone(display)}`}>{display || 'NOT_PRODUCED'}</span>;
}
function CardTaskEvidence({evidence,detail,stale,onDownload}) {
  return <>
    {evidence ? <><div className="source-strip"><Status value={evidence.receipt.status}/><code>{evidence.receipt.actor}</code>
      <span>正常化估值</span><Status value={evidence.valuationStatus}/></div>
      <dl>{[['执行版本',evidence.receipt.code_sha],['输入 hash',evidence.receipt.input_hash],
        ['输出 hash',evidence.receipt.output_hash]].map(([label,value])=><React.Fragment key={label}><dt>{label}</dt><dd><code>{value}</code></dd></React.Fragment>)}</dl>
      <div className="shared-toolbar"><button onClick={onDownload}><Download size={16}/>任务回执</button></div></>
      : !stale&&detail&&(detail.status==='SUCCEEDED'?<p role="status">研究卡证据不可用</p>:<Status value={detail.status}/>)}
    <details hidden={!evidence}><summary>核验步骤 · {evidence?.steps.length??0}</summary>
      {evidence&&<ol>{evidence.steps.map(step=><li key={step}><code>{step}</code></li>)}</ol>}</details>
    <CitationLocations hidden={!evidence} locations={evidence?.citation_locations??[]}/>
  </>;
}
function download(name, value, type = 'application/json') {
  const blob = new Blob([typeof value === 'string' ? value : JSON.stringify(value, null, 2)], { type });
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function SharedWorkspace({ api, access, refreshRevision }) {
  const [view, setView] = useState('my'), [page, setPage] = useState(0);
  const [query, setQuery] = useState({ data: null, connection: 'WAIT', stale: false, error: '' });
  const [busy, setBusy] = useState(false), [pending, setPending] = useState([]);
  const [detail, setDetail] = useState(null), [selection, setSelected] = useState(null), [detailError, setDetailError] = useState('');
  const [detailStale, setDetailStale] = useState(false);
  const [libraryRefreshRevision, setLibraryRefreshRevision] = useState(0);
  const poller = useRef(null), selectedRef = useRef(null), detailSequence = useRef(0), detailLoading = useRef(null), readerRef = useRef(null), cardDownloadRef = useRef(null);
  const [now, setNow] = useState(Date.now);
  const actorContext = useRef({ login: access.login });
  if (actorContext.current.login !== access.login) actorContext.current = { login: access.login };
  const visibleQuery = sharedActorQuery(query, access.login);
  const submissionContext = useRef(null);
  submissionContext.current = { workspaceId: visibleQuery.data?.my_workspace.workspace_id,
    codeSha: visibleQuery.data?.execution_identity?.code_sha };
  readerRef.current=jobDetailReader(readerRef.current,access.login,submissionContext.current.workspaceId,submissionContext.current.codeSha);
  const reader=readerRef.current;
  const selected=selection?.reader===reader?selection:null;
  async function renew() {
    const response = await fetch('/', { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new Error('SESSION_RENEWAL_FAILED');
  }
  function reload() { setLibraryRefreshRevision(value => value + 1); return poller.current?.refresh(); }
  useEffect(() => {
    const context = actorContext.current;
    const current = createSharedRefreshPair({
      read: () => sharedRead(api, `/api/shared-workspace?page=${page}`, renew),
      apply: data => {
        if (actorContext.current !== context) return;
        if (data.my_workspace.login !== access.login) throw new Error('SHARED_IDENTITY_CHANGED');
        const workspaceId = data.my_workspace.workspace_id;
        setQuery(previous => sharedQueryState(previous, data));
      },
      readDetails: async data => {
        if (poller.current !== current || actorContext.current !== context) return;
        const workspaceId = data.my_workspace.workspace_id;
        await pollSharedPending(api, window.localStorage, workspaceId, data.owned_commands || {}, renew);
        if (poller.current !== current || actorContext.current !== context || submissionContext.current?.workspaceId !== workspaceId) return;
        setPending(getPending(window.localStorage, workspaceId));
        const chosen=selectedRef.current;
        if (chosen) await open(chosen.jobId,chosen.kind,false,chosen.reader);
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
  }, [reader]);
  async function open(jobId,kind,select=true,requestReader=readerRef.current) {
    if(requestReader!==readerRef.current||!requestReader.ready||!detailKinds.has(kind))return;
    let chosen=selectedRef.current;
    const same=chosen?.jobId===jobId&&chosen.kind===kind&&chosen.reader===requestReader;
    if(!select&&(!same||detailLoading.current!==null))return;
    if(!same){chosen={jobId,kind,reader:requestReader};selectedRef.current=chosen;setSelected(chosen);setDetail(null);}
    const request = ++detailSequence.current;
    detailLoading.current = request;
    setDetailError(''); setDetailStale(true);
    const current=()=>request===detailSequence.current&&detailReadCurrent(chosen,selectedRef.current,readerRef.current);
    try {
      const data = await sharedRead(api, `/api/shared-workspace/jobs/${encodeURIComponent(jobId)}`, renew);
      if(!current())return;
      if(data?.job_id!==jobId||data.kind!==kind||(kind===cardKind&&!cardStatuses.has(data.status)))
        throw new Error('SHARED_DETAIL_BINDING_MISMATCH');
      setDetail(data);setDetailStale(false);
    } catch (error) {
      if(current())setDetailError(kind===cardKind?'RESEARCH_CARD_DETAIL_UNAVAILABLE':error.message);
    } finally { if (detailLoading.current === request) detailLoading.current = null; }
  }
  async function run(kind, selection = null) {
    const context = actorContext.current;
    const requestReader=readerRef.current;
    const workspaceId = visibleQuery.data?.my_workspace.workspace_id;
    const snapshotId = selection?.snapshot_id || visibleQuery.data?.common_data.current_snapshot_id;
    if (kind === 'earnings-review' && (!selection || selection.workspace_id !== submissionContext.current?.workspaceId ||
        selection.code_sha !== submissionContext.current?.codeSha || workspaceId !== selection.workspace_id)) return;
    if (kind === 'research-cards-review' && (!selection || selection.workspace_id !== submissionContext.current?.workspaceId ||
        selection.code_sha !== submissionContext.current?.codeSha || workspaceId !== selection.workspace_id)) return;
    if (!workspaceId || !snapshotId || sharedViewFreshness(visibleQuery).commonStale) return;
    const body = { command_id: `shared_${crypto.randomUUID().replaceAll('-', '')}`, kind, snapshot_id: snapshotId };
    if (kind === 'earnings-review') Object.assign(body, { expected_workspace_id: selection.workspace_id, expected_code_sha: selection.code_sha });
    if (kind === 'research-cards-review') Object.assign(body, { expected_workspace_id: selection.workspace_id, expected_code_sha: selection.code_sha });
    setBusy(true);
    try {
      savePending(window.localStorage, workspaceId, body);
      setPending(getPending(window.localStorage, workspaceId));
      const receipt = await api('/api/workspace/job', body);
      if (actorContext.current !== context) return;
      savePending(window.localStorage, workspaceId, body, receipt.job_id);
      await reload();
      if (actorContext.current === context) await open(receipt.job_id,kind,true,requestReader);
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
    const requestReader=readerRef.current;
    const workspaceId = visibleQuery.data?.my_workspace.workspace_id;
    if (!workspaceId || sharedViewFreshness(visibleQuery).commonStale || busy) return;
    setBusy(true);
    try {
      const kind=getPending(window.localStorage,workspaceId).find(item=>item.body.command_id===commandId)?.body.kind;
      const scopedApi = (...args) => {
        if (actorContext.current !== context) throw new Error('SHARED_IDENTITY_CHANGED');
        return api(...args);
      };
      const receipt = await retrySharedPending(scopedApi, window.localStorage, workspaceId, commandId, renew);
      if (actorContext.current !== context) return;
      await reload();
      if (actorContext.current === context) await open(receipt.job_id,kind,true,requestReader);
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
  const cardEvidence=selected?.kind===cardKind?cardTaskEvidence(detail,{jobId:selected.jobId,stale:freshness.detailStale}):null;
  cardDownloadRef.current=cardEvidence;
  function downloadCard(){
    if(cardEvidence&&cardDownloadRef.current===cardEvidence&&detailLoading.current===null&&detailReadCurrent(selected,selectedRef.current,readerRef.current))
      download(`${selected.jobId}.json`,cardEvidence.receipt);
  }
  const syncView = commonSyncView(common, freshness.commonStale);
  const cardRevision=JSON.stringify([refreshRevision,libraryRefreshRevision]);
  const syncTime = value => value == null ? 'NOT_CHECKED' : new Date(value * 1000).toLocaleString();
  return <div className="workspace-surface shared-workspace">
    <div className="shared-heading"><div><h2>共享研究工作台</h2><code>{login}</code></div>
      <div className="shared-status"><code>{data?.execution_identity?.code_sha || 'VERSION_UNAVAILABLE'}</code><Status value={freshness.commonStale ? 'DISCONNECTED' : query.connection} /><button className="icon-button" title="刷新" aria-label="刷新共享工作区" onClick={reload}><RefreshCw size={17} /></button></div>
    </div>
    <div className="source-strip"><span>WORKFLOW_DEBUG</span><span>人工核验 PENDING</span><span>生产 / 交易权限 false</span><span>最新本人简报 <Status value={latest?.status} stale={freshness.commonStale} /></span></div>
    {visibleQuery.error && <div className="shared-error" role="alert">DISCONNECTED · {visibleQuery.error}</div>}
    {visiblePending.some(item => !item.job_id) && <div className="source-strip"><Status value="SUBMISSION_UNCONFIRMED" stale={freshness.commonStale} /></div>}
    {!syncView.canBrief && <div className="shared-error" role="status">{freshness.commonStale ? 'DISCONNECTED' : common?.error || 'NO_FROZEN_PUBLICATION'}</div>}
    <nav className="shared-tabs" aria-label="共享工作区视图">{[...views,...(access.review_portal_enabled===true?[['review','研究审阅',FileText]]:[])].map(([key, label, Icon]) => <button key={key} aria-current={view === key ? 'page' : undefined} onClick={() => { setView(key); setPage(0); }}><Icon size={16} />{label}</button>)}</nav>
    {view === 'review' && access.review_portal_enabled===true ? <ReviewPortal api={api} renew={renew} login={access.login} workspaceId={data?.my_workspace.workspace_id} codeSha={data?.execution_identity?.code_sha} parentStale={freshness.commonStale} refreshRevision={cardRevision}/> : view === 'cards' ? <ResearchCards api={api} renew={renew} login={access.login} workspaceId={data?.my_workspace.workspace_id} codeSha={data?.execution_identity?.code_sha} parentStale={freshness.commonStale} refreshRevision={cardRevision} onRun={selection=>run(cardKind,selection)} onOpenJob={jobId=>open(jobId,cardKind,true,reader)} busy={busy||pending.length>=2}/> : view === 'research' ? <ResearchLibrary api={api} renew={renew} login={access.login} workspaceId={data?.my_workspace.workspace_id} codeSha={data?.execution_identity?.code_sha} parentStale={freshness.commonStale} refreshRevision={`${refreshRevision}:${libraryRefreshRevision}`} onRun={selection => run('earnings-review', selection)} busy={busy || pending.length >= 2} /> : view !== 'common' ? <>
      <div className="shared-toolbar"><span>{total} 个任务</span>{view === 'my' && <div><button disabled={busy || pending.length >= 2 || freshness.commonStale || !common?.current_snapshot_id} onClick={() => run('observe')}><Database size={16} />观察</button><button className="primary" disabled={busy || pending.length >= 2 || freshness.commonStale || !common?.current_snapshot_id} onClick={() => run('snapshot-brief')}><Play size={16} />{busy ? '提交中' : '生成简报'}</button>{pending.length > 0 && !busy && <button onClick={reload}><RefreshCw size={16} />核对原任务</button>}</div>}</div>
      {view === 'my' && visiblePending.filter(item => !item.job_id).map(item => <div className="source-strip" key={item.body.command_id}><code>{item.body.command_id}</code><span>{item.body.kind}</span><code>{item.body.snapshot_id}</code><button disabled={busy || freshness.commonStale} aria-label={`重试原提交 ${item.body.command_id}`} onClick={() => retry(item.body.command_id)}><RefreshCw size={16} />重试原提交</button></div>)}
      <div className="shared-job-list">{rows.map(job => <button className="shared-job-row" key={job.job_id} onClick={() => open(job.job_id,job.kind,true,reader)}>
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
    {view === 'common' && <DataCenter api={api} renew={renew} login={login} snapshotId={common?.current_snapshot_id} parentStale={freshness.commonStale} refreshRevision={refreshRevision} onOpenJob={jobId=>open(jobId,'snapshot-brief',true,reader)} />}
    {data && selected && <section className="shared-detail"><div className="section-title"><h3>任务详情</h3><div><button className="icon-button" title="重新验证" aria-label="重新验证任务" onClick={() => open(selected.jobId,selected.kind,true,selected.reader)}><RefreshCw size={17} /></button><button className="icon-button" title="关闭详情" aria-label="关闭任务详情" onClick={() => { ++detailSequence.current; selectedRef.current = null; setSelected(null); setDetail(null); }}><X size={17} /></button></div></div><code>{selected.jobId}</code>
      {detailError && <div role="alert" className="shared-error">DISCONNECTED · {detailError}</div>}
      {detail&&freshness.detailStale&&<div className="shared-error" role="status">DISCONNECTED · STALE</div>}
      {selected.kind===cardKind ? <CardTaskEvidence key={selected.jobId} detail={detail} evidence={cardEvidence} stale={freshness.detailStale} onDownload={downloadCard}/> :
      detail ? <><div className="source-strip"><Status value={detail.status} stale={freshness.detailStale} /><code>{detail.actor}</code><code>{detail.workspace_id || 'LEGACY_UNATTRIBUTED'}</code></div><dl>{[['执行版本', detail.code_sha], ['输入 hash', detail.input_hash], ['输出 hash', detail.output_hash], ['失败原因', detail.error]].map(([label, value]) => <React.Fragment key={label}><dt>{label}</dt><dd><code>{value || 'NOT_PRODUCED'}</code></dd></React.Fragment>)}</dl>
        <div className="shared-toolbar"><button disabled={!freshness.downloadsEnabled} onClick={() => download(`${selected.jobId}.json`, detail)}><Download size={16} />任务回执</button>{detail.report && <><button disabled={!freshness.downloadsEnabled} onClick={() => download(`${selected.jobId}.md`, detail.report, 'text/markdown')}><Download size={16} />报告</button><button disabled={!freshness.downloadsEnabled} onClick={() => download(`${selected.jobId}-citations.json`, detail.citations)}><Download size={16} />引用</button></>}</div>
        {detail.research && <><div className="source-strip"><Status value={detail.research.archive_status} stale={freshness.detailStale} /><Status value={detail.research.human_review} stale={freshness.detailStale} /><span>{detail.research.company} · {detail.research.research_date}</span><span>{detail.research.content_status}</span></div><dl>{[['原件截止', detail.research.source_cutoff_at], ['报告 SHA256', detail.research.report_sha256], ['回库 hash', detail.research.archive_library_hash]].map(([name,value]) => <React.Fragment key={name}><dt>{name}</dt><dd><code>{value}</code></dd></React.Fragment>)}</dl><div className="table-scroll"><table><thead><tr><th>问题</th><th>PDF SHA256</th><th>物理页 / 文本行</th></tr></thead><tbody>{detail.research.citation_locations.map((row,i) => <tr key={i}><td>{row.question_id}</td><td><code>{row.sha256}</code></td><td>{row.page} / {row.start}–{row.end}</td></tr>)}</tbody></table></div></>}
        {detail.report && <pre className="shared-report">{detail.report}</pre>}<details><summary>步骤与引用</summary><pre>{JSON.stringify({ result: detail.result, citations: detail.citations, research: detail.research }, null, 2)}</pre></details></> : !detailError && <p>WAIT</p>}
    </section>}
  </div>;
}
