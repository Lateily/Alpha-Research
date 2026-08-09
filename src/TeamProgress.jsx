import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  ExternalLink,
  FileCode2,
  GitPullRequest,
  Radio,
  RefreshCw,
  Send,
  ShieldCheck,
  Clipboard,
  UserRound,
  XCircle,
} from 'lucide-react';
import {
  normalizeProgressWriteKey,
  readProgressApiResponse,
  resolveProgressApiBase,
} from './progressBoardClient.js';

const PROGRESS_API_BASE = resolveProgressApiBase({
  configuredBase: import.meta.env.VITE_PROGRESS_API_BASE_URL,
  hostname: window.location.hostname,
});
const ENDPOINT = `${PROGRESS_API_BASE}/api/team-progress`;
const WRITE_ENDPOINT = `${PROGRESS_API_BASE}/api/team-progress-event`;
const SNAPSHOT_SCHEMA = 'ai-progress.snapshot.v1';
const CONTRACT_VERSION = '1.5';
const REFRESH_MS = 30000;
const ISSUE_URL = 'https://github.com/Lateily/Alpha-Research/issues/164';
const EVENT_TYPES = ['CLAIM', 'UPDATE', 'DONE', 'BLOCKED', 'RELEASE'];

// ── BLUEPRINT: 八块元数据 (事实源 docs/ARCHITECTURE_MAP.md · 2026-08-09) ─────
const BP_BLOCKS = [
  { id:'块1', name:'研究框架', role:'大脑',   pct:75, owner:'Junyan',        lbl:'块1-研究框架', ok:true  },
  { id:'块2', name:'数据源',   role:'原料',   pct:55, owner:'Junyan+Macro Agent', lbl:'块2-数据源',   ok:true  },
  { id:'块3', name:'引擎层',   role:'车间',   pct:80, owner:'Claude+Macro Agent', lbl:'块3-引擎层',   ok:true  },
  { id:'块4', name:'契约层',   role:'传送带', pct:70, owner:'Junyan+Claude', lbl:'块4-契约层',   ok:true  },
  { id:'块5', name:'前端载体', role:'展厅',   pct:10, owner:'Better',        lbl:'块5-前端',     ok:false, note:'最薄弱'},
  { id:'块6', name:'AI 系统',  role:'工人',   pct:15, owner:'Reed',          lbl:'块6-AI系统',   ok:false },
  { id:'块7', name:'团队流程', role:'神经',   pct:60, owner:'Junyan',        lbl:'块7-团队流程', ok:true  },
  { id:'块8', name:'运维',     role:'电力',   pct:55, owner:'Claude',        lbl:'块8-运维',     ok:true  },
];

// ── BLUEPRINT: 在途工作流分组(GitHub label 匹配) ─────────────────────────────
const STREAMS = [
  { title:'研究线 R0–R6',   sub:'Junyan · Claude', lbls:['块1-研究框架','块2-数据源','块3-引擎层'] },
  { title:'AI OS 线 K1–K6', sub:'Reed (+ Jason)',  lbls:['块6-AI系统']                            },
  { title:'产品线 M0–M6',   sub:'Better',          lbls:['块5-前端']                              },
];

const GH_REFRESH_MS  = 300000; // 5 min — GitHub unauthenticated rate limit = 60 req/hr
const GH_API         = 'https://api.github.com/repos/Lateily/Alpha-Research';
const GH_ISSUE_LINK  = (n) => `https://github.com/Lateily/Alpha-Research/issues/${n}`;
const GH_PR_LINK     = (n) => `https://github.com/Lateily/Alpha-Research/pull/${n}`;
const GH_ACCEPT      = { Accept: 'application/vnd.github+json' };

const palette = {
  ink: '#172033',
  muted: '#647084',
  bg: '#f6f7f2',
  panel: '#ffffff',
  line: '#dfe4dc',
  soft: '#eef2e8',
  green: '#237a57',
  amber: '#a86416',
  red: '#b33a3a',
  blue: '#2b66b1',
  violet: '#6350a3',
};

const statusMeta = {
  CLAIM: { label: 'CLAIM', color: palette.blue, icon: Radio },
  UPDATE: { label: 'UPDATE', color: palette.violet, icon: Activity },
  DONE: { label: 'DONE', color: palette.green, icon: CheckCircle2 },
  BLOCKED: { label: 'BLOCKED', color: palette.red, icon: AlertTriangle },
  RELEASE: { label: 'RELEASE', color: palette.amber, icon: ShieldCheck },
};

function validateSnapshot(value) {
  if (!value || typeof value !== 'object') {
    throw new Error('Empty or invalid snapshot response.');
  }
  if (value.schema !== SNAPSHOT_SCHEMA) {
    throw new Error(`Unsupported schema: ${value.schema || 'missing'}.`);
  }
  if (value.contract_version !== CONTRACT_VERSION) {
    throw new Error(`Unsupported contract version: ${value.contract_version || 'missing'}.`);
  }
  return value;
}

function formatTime(value) {
  if (!value) return 'n/a';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function asList(value) {
  if (Array.isArray(value)) return value;
  if (value === undefined || value === null || value === '') return [];
  return [String(value)];
}

function splitCsv(value) {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function eventStatus(event) {
  return {
    CLAIM: 'in_progress',
    UPDATE: 'in_progress',
    DONE: 'done',
    BLOCKED: 'blocked',
    RELEASE: 'released',
  }[event] || 'in_progress';
}

export function buildProgressComment(form, now = new Date()) {
  const event = String(form.event || 'CLAIM').toUpperCase();
  const payload = {
    schema: 'ai-progress.v2',
    event,
    task: form.task?.trim(),
    human_owner: form.human_owner?.trim(),
    executor: form.executor?.trim(),
    reviewer: form.reviewer?.trim(),
    status: eventStatus(event),
    summary: form.summary?.trim(),
    branch: form.branch?.trim(),
    files: splitCsv(form.files),
    pr: form.pr?.trim(),
    next: form.next?.trim(),
    cost_cny: form.cost_cny?.trim(),
    risk: form.risk?.trim() || 'none',
    timestamp_utc: now.toISOString(),
  };

  if (event === 'CLAIM') {
    const expires = new Date(now.getTime() + 3 * 60 * 60 * 1000);
    payload.expires_at = expires.toISOString();
  }

  const cleaned = Object.fromEntries(
    Object.entries(payload).filter(([, value]) => {
      if (Array.isArray(value)) return value.length > 0;
      return value !== undefined && value !== null && value !== '';
    })
  );

  return `<!-- ai-progress:v2 -->\n\`\`\`json\n${JSON.stringify(cleaned, null, 2)}\n\`\`\``;
}

function SummaryTile({ icon: Icon, label, value, tone = palette.ink }) {
  return (
    <section style={styles.tile}>
      <div style={{ ...styles.tileIcon, color: tone, background: `${tone}14` }}>
        <Icon size={18} />
      </div>
      <div>
        <div style={styles.tileLabel}>{label}</div>
        <div style={styles.tileValue}>{value ?? 0}</div>
      </div>
    </section>
  );
}

function EventBadge({ event }) {
  const meta = statusMeta[event] || { label: event || 'EVENT', color: palette.muted, icon: Activity };
  const Icon = meta.icon;
  return (
    <span style={{ ...styles.badge, color: meta.color, borderColor: `${meta.color}55`, background: `${meta.color}12` }}>
      <Icon size={13} />
      {meta.label}
    </span>
  );
}

function FieldLine({ label, value }) {
  if (!value) return null;
  return (
    <div style={styles.fieldLine}>
      <span style={styles.fieldLabel}>{label}</span>
      <span style={styles.fieldValue}>{value}</span>
    </div>
  );
}

function FileChips({ files }) {
  const items = asList(files);
  if (items.length === 0) return null;
  return (
    <div style={styles.chipWrap}>
      {items.map((file) => (
        <span key={file} style={styles.chip}>
          <FileCode2 size={12} />
          {file}
        </span>
      ))}
    </div>
  );
}

function ActiveClaim({ claim }) {
  return (
    <article style={styles.claimCard}>
      <div style={styles.claimTop}>
        <div>
          <div style={styles.taskLine}>{claim.task || 'untitled task'}</div>
          <div style={styles.summaryText}>{claim.summary || 'No summary provided.'}</div>
        </div>
        <EventBadge event={claim.event} />
      </div>
      <div style={styles.metaGrid}>
        <FieldLine label="Owner" value={claim.human_owner} />
        <FieldLine label="Executor" value={claim.executor} />
        <FieldLine label="Reviewer" value={claim.reviewer} />
        <FieldLine label="Branch" value={claim.branch} />
        <FieldLine label="Expires" value={formatTime(claim.expires_at)} />
        <FieldLine label="Risk" value={claim.risk} />
      </div>
      <FileChips files={claim.files} />
    </article>
  );
}

function ConflictRow({ conflict }) {
  return (
    <article style={styles.conflictRow}>
      <div style={styles.conflictTitle}>
        <AlertTriangle size={16} />
        {conflict.left_task || 'task'} overlaps {conflict.right_task || 'task'}
      </div>
      <div style={styles.conflictBody}>
        {conflict.left || 'unknown'} / {conflict.right || 'unknown'}
      </div>
      <FileChips files={conflict.files} />
    </article>
  );
}

function TimelineItem({ item }) {
  const meta = statusMeta[item.event] || { color: palette.muted };
  return (
    <article style={{ ...styles.timelineItem, borderLeftColor: meta.color }}>
      <div style={styles.timelineHead}>
        <EventBadge event={item.event} />
        <span style={styles.timeText}>{formatTime(item.timestamp_utc)}</span>
      </div>
      <div style={styles.timelineTitle}>{item.task || 'untitled task'}</div>
      <div style={styles.summaryText}>{item.summary || 'No summary provided.'}</div>
      <div style={styles.timelineMeta}>
        <span><UserRound size={12} /> {item.human_owner || 'unknown'} / {item.executor || 'unknown'}</span>
        {item.cost_cny && <span>Cost ¥{item.cost_cny}</span>}
        {item.risk && <span>Risk {item.risk}</span>}
      </div>
      {item.pr && (
        <a href={item.pr} target="_blank" rel="noreferrer" style={styles.prLink}>
          <GitPullRequest size={13} />
          PR
          <ExternalLink size={12} />
        </a>
      )}
    </article>
  );
}

function EmptyState({ text }) {
  return <div style={styles.empty}>{text}</div>;
}

function FormField({ label, value, onChange, placeholder, textarea = false, type = 'text', autoComplete }) {
  const Input = textarea ? 'textarea' : 'input';
  return (
    <label style={styles.formField}>
      <span style={styles.formLabel}>{label}</span>
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        type={textarea ? undefined : type}
        autoComplete={autoComplete}
        style={textarea ? styles.textarea : styles.input}
      />
    </label>
  );
}

function CommentComposer({ onSubmitted }) {
  const [form, setForm] = useState({
    event: 'CLAIM',
    task: '',
    human_owner: 'Reed',
    executor: 'Codex',
    reviewer: 'Junyan',
    summary: '',
    branch: '',
    files: '',
    pr: '',
    next: '',
    cost_cny: '0',
    risk: 'none',
  });
  const [writeKey, setWriteKey] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [copyMessage, setCopyMessage] = useState('No frontend GitHub token. Server writes only standard #164 comments.');

  const update = (key, value) => {
    setCopyMessage('No frontend GitHub token. Server writes only standard #164 comments.');
    setForm((current) => ({ ...current, [key]: value }));
  };
  const comment = useMemo(() => buildProgressComment(form), [form]);

  const copyComment = async () => {
    try {
      await navigator.clipboard.writeText(comment);
      setCopyMessage('Copied. Paste it into GitHub Issue #164.');
    } catch {
      setCopyMessage('Clipboard blocked. Select the generated text and copy it manually.');
    }
  };

  const submitComment = async () => {
    const normalizedWriteKey = normalizeProgressWriteKey(writeKey);
    if (!normalizedWriteKey) {
      setCopyMessage('Team write key is required.');
      return;
    }
    setSubmitting(true);
    setCopyMessage('Submitting to GitHub Issue #164...');
    try {
      const response = await fetch(WRITE_ENDPOINT, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Progress-Write-Key': normalizedWriteKey,
        },
        body: JSON.stringify(form),
      });
      const data = await readProgressApiResponse(response);
      if (!response.ok || data.ok === false) {
        throw new Error(data.error || `Submit failed with HTTP ${response.status}.`);
      }
      setCopyMessage('Submitted to #164. Refreshing board...');
      onSubmitted?.();
    } catch (err) {
      setCopyMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section style={styles.panel}>
      <div style={styles.panelHead}>
        <div>
          <h2 style={styles.panelTitle}>Comment Composer</h2>
          <div style={styles.panelHint}>Generate a safe ai-progress.v2 comment, then paste it into #164.</div>
        </div>
        <a href={ISSUE_URL} target="_blank" rel="noreferrer" style={styles.issueLink}>
          Open #164
          <ExternalLink size={13} />
        </a>
      </div>
      <div style={styles.composerBody}>
        <div style={styles.formGrid}>
          <label style={styles.formField}>
            <span style={styles.formLabel}>Event</span>
            <select value={form.event} onChange={(event) => update('event', event.target.value)} style={styles.input}>
              {EVENT_TYPES.map((type) => (
                <option key={type} value={type}>{type}</option>
              ))}
            </select>
          </label>
          <FormField label="Task" value={form.task} onChange={(value) => update('task', value)} placeholder="#161 or short task name" />
          <FormField label="Human owner" value={form.human_owner} onChange={(value) => update('human_owner', value)} placeholder="Reed / Better / Junyan" />
          <FormField label="Executor" value={form.executor} onChange={(value) => update('executor', value)} placeholder="Codex / Claude / human" />
          <FormField label="Reviewer" value={form.reviewer} onChange={(value) => update('reviewer', value)} placeholder="Junyan" />
          <FormField label="Branch" value={form.branch} onChange={(value) => update('branch', value)} placeholder="feat/example" />
          <FormField label="Files" value={form.files} onChange={(value) => update('files', value)} placeholder="docs/llm,scripts/llm" />
          <FormField label="PR" value={form.pr} onChange={(value) => update('pr', value)} placeholder="https://github.com/.../pull/..." />
          <FormField label="Cost CNY" value={form.cost_cny} onChange={(value) => update('cost_cny', value)} placeholder="0" />
          <FormField label="Risk" value={form.risk} onChange={(value) => update('risk', value)} placeholder="none" />
        </div>
        <FormField
          label="Summary"
          value={form.summary}
          onChange={(value) => update('summary', value)}
          placeholder="One sentence: what changed or what you are claiming."
          textarea
        />
        <FormField
          label="Next"
          value={form.next}
          onChange={(value) => update('next', value)}
          placeholder="Next reviewer or next action."
          textarea
        />
        <FormField
          label="Team write key"
          value={writeKey}
          onChange={setWriteKey}
          placeholder="PROGRESS_WRITE_KEY, not a GitHub token"
          type="password"
          autoComplete="off"
        />
        <textarea value={comment} readOnly style={styles.commentBox} aria-label="Generated GitHub comment" />
        <div style={styles.composerActions}>
          <button
            type="button"
            onClick={submitComment}
            disabled={submitting}
            style={{
              ...styles.submitButton,
              opacity: submitting ? 0.65 : 1,
              cursor: submitting ? 'wait' : 'pointer',
            }}
          >
            <Send size={15} />
            {submitting ? 'Submitting' : 'Submit to #164'}
          </button>
          <button type="button" onClick={copyComment} style={styles.copyButton}>
            <Clipboard size={15} />
            Copy comment
          </button>
          <span style={styles.copyStatus}>{copyMessage}</span>
        </div>
      </div>
    </section>
  );
}

// ── BLUEPRINT STYLES (scoped to bpS to avoid collision with `styles`) ────────
const bpS = {
  wrap:       { marginTop:16, border:`1px solid ${palette.line}`, borderRadius:8, background:palette.panel, overflow:'hidden' },
  head:       { display:'flex', justifyContent:'space-between', alignItems:'center', padding:'12px 14px', gap:12, flexWrap:'wrap', background:palette.soft, borderBottom:`1px solid ${palette.line}` },
  headTitle:  { margin:0, fontSize:15, fontWeight:800 },
  headHint:   { color:palette.muted, fontSize:12, marginTop:3 },
  headRight:  { display:'flex', gap:8, alignItems:'center', flexWrap:'wrap' },
  body:       { padding:12, display:'grid', gap:14 },
  subHead:    { fontSize:11, fontWeight:800, color:palette.muted, textTransform:'uppercase', letterSpacing:'0.05em', marginBottom:8 },
  critGrid:   { display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(200px,1fr))', gap:8 },
  critCard:   { padding:12, border:`1px solid ${palette.line}`, borderLeft:'4px solid', borderRadius:8, background:'#fff', display:'grid', gap:5 },
  critTag:    { fontSize:11, fontWeight:800 },
  critTitle:  { fontWeight:800, fontSize:13 },
  critBody:   { color:palette.muted, fontSize:12, lineHeight:1.45 },
  blockGrid:  { display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(130px,1fr))', gap:8 },
  blockCard:  { padding:10, border:`1px solid ${palette.line}`, borderRadius:8, background:'#fff' },
  blockId:    { fontFamily:"'JetBrains Mono','Courier New',monospace", fontSize:11, fontWeight:800 },
  blockName:  { fontWeight:800, fontSize:13, marginTop:2 },
  blockSub:   { color:palette.muted, fontSize:11, marginTop:1 },
  blockBar:   { marginTop:8, height:5, background:palette.line, borderRadius:20, overflow:'hidden' },
  blockFill:  { height:'100%', borderRadius:20 },
  blockPct:   { fontFamily:"'JetBrains Mono','Courier New',monospace", fontSize:12, fontWeight:800, marginTop:4 },
  streamGrid: { display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(240px,1fr))', gap:10 },
  streamCard: { padding:12, border:`1px solid ${palette.line}`, borderRadius:8, background:'#fff', display:'grid', gap:0 },
  streamHead: { display:'flex', justifyContent:'space-between', alignItems:'center' },
  streamTitle:{ fontWeight:800, fontSize:13 },
  streamCount:{ fontFamily:"'JetBrains Mono','Courier New',monospace", fontSize:11, color:palette.muted },
  streamSub:  { color:palette.muted, fontSize:11, marginBottom:8, marginTop:2 },
  issRow:     { display:'flex', alignItems:'center', gap:6, padding:'5px 7px', borderRadius:6, background:palette.soft, textDecoration:'none', color:'inherit', minWidth:0, marginBottom:4 },
  issNum:     { fontFamily:"'JetBrains Mono','Courier New',monospace", fontSize:11, flexShrink:0 },
  issTitle:   { fontSize:12, color:palette.ink, overflow:'hidden', whiteSpace:'nowrap', textOverflow:'ellipsis', flex:1 },
  errBand:    { color:palette.red, fontSize:12, padding:'8px 10px', background:'#fff1f0', borderRadius:6, border:`1px solid ${palette.red}33` },
  stamp:      { color:palette.muted, fontSize:12, whiteSpace:'nowrap' },
  mono:       { fontFamily:"'JetBrains Mono','Courier New',monospace" },
};

// ── PROJECT BLUEPRINT COMPONENT ───────────────────────────────────────────────
// Self-contained: fetches GitHub Issues/PRs every 5 min (unauthenticated public API).
// Adds no side effects to the rest of the board — isolated state, isolated timers.
function ProjectBlueprint() {
  const [issues,    setIssues]    = useState([]);
  const [prs,       setPrs]       = useState([]);
  const [ghLoading, setGhLoading] = useState(true);
  const [ghError,   setGhError]   = useState('');
  const [ghAt,      setGhAt]      = useState('');

  const fetchGh = useCallback(async () => {
    try {
      const [ir, pr] = await Promise.all([
        fetch(`${GH_API}/issues?state=open&per_page=100`, { headers: GH_ACCEPT }),
        fetch(`${GH_API}/pulls?state=open&per_page=50`,   { headers: GH_ACCEPT }),
      ]);
      // Parse both bodies once; catch JSON failures independently
      const [id, pd] = await Promise.all([
        ir.json().catch(() => null),
        pr.json().catch(() => null),
      ]);
      if (!ir.ok) throw new Error(`GitHub Issues API ${ir.status}: ${id?.message || 'rate limit or access error'}`);
      if (!pr.ok) throw new Error(`GitHub PRs API ${pr.status}: ${pd?.message || 'rate limit or access error'}`);
      if (!Array.isArray(id)) throw new Error(`Issues: unexpected response shape — ${id?.message || String(id).slice(0, 80)}`);
      if (!Array.isArray(pd)) throw new Error(`PRs: unexpected response shape — ${pd?.message || String(pd).slice(0, 80)}`);
      // /issues endpoint returns PRs too — filter them out
      setIssues(id.filter(i => !i.pull_request));
      setPrs(pd);
      setGhAt(new Date().toISOString());
      setGhError('');
    } catch (e) {
      // Keep existing issues/prs in state (stale data > empty); only update error banner
      setGhError(e instanceof Error ? e.message : String(e));
    } finally {
      setGhLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchGh();
    const t = setInterval(fetchGh, GH_REFRESH_MS);
    return () => clearInterval(t);
  }, [fetchGh]);

  // Bug-labeled open issues → drive the critical path section (never hardcode issue numbers)
  const bugIssues = useMemo(() => issues.filter(i => i.labels.some(l => l.name === 'bug')), [issues]);

  // Issues grouped by stream (union of block labels)
  const streamIssues = useMemo(() =>
    STREAMS.map(s => issues.filter(iss => iss.labels.some(l => s.lbls.includes(l.name)))),
  [issues]);

  // Open-issue count per block (live badge)
  const blockCounts = useMemo(() => {
    const m = {};
    for (const b of BP_BLOCKS) m[b.lbl] = issues.filter(i => i.labels.some(l => l.name === b.lbl)).length;
    return m;
  }, [issues]);

  return (
    <section style={bpS.wrap} aria-label="项目蓝图">
      {/* ── header ── */}
      <div style={bpS.head}>
        <div>
          <h2 style={bpS.headTitle}>项目蓝图</h2>
          <div style={bpS.headHint}>八块进度 = ARCHITECTURE_MAP 周更快照 · 关键路径 + 在途工作流 = GitHub Issues/PR 每 5 分钟实时</div>
        </div>
        <div style={bpS.headRight}>
          {ghAt && <span style={bpS.stamp}>更新 {formatTime(ghAt)}</span>}
          <button type="button" onClick={fetchGh} style={styles.iconButton} title="刷新 GitHub 数据">
            <RefreshCw size={16} />
          </button>
          <a href="https://github.com/Lateily/Alpha-Research/issues" target="_blank" rel="noreferrer" style={styles.issueLink}>
            Issues <ExternalLink size={12} />
          </a>
        </div>
      </div>

      <div style={bpS.body}>
        {/* GitHub API error */}
        {ghError && <div style={bpS.errBand}>GitHub API: {ghError}</div>}

        {/* ── 关键路径:bug 标签 open issues + 固定样本提醒 ── */}
        <div>
          <div style={bpS.subHead}>关键路径 · 当前堵点(实时 GitHub bug 标签)</div>
          <div style={bpS.critGrid}>
            {/* Live bug-labeled issues — never hardcode issue numbers here */}
            {ghLoading && !issues.length ? (
              <div style={{ color:palette.muted, fontSize:12 }}>加载中…</div>
            ) : bugIssues.length > 0 ? (
              bugIssues.map(iss => (
                <div key={iss.number} style={{ ...bpS.critCard, borderLeftColor: palette.red }}>
                  <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                    <span style={{ ...bpS.critTag, color: palette.red }}>堵点</span>
                    <a href={GH_ISSUE_LINK(iss.number)} target="_blank" rel="noreferrer"
                      style={{ fontSize:11, color:palette.blue, display:'flex', gap:3, alignItems:'center', textDecoration:'none' }}>
                      #{iss.number} <ExternalLink size={11} />
                    </a>
                  </div>
                  <div style={bpS.critTitle}>{iss.title}</div>
                  <div style={bpS.critBody}>{iss.labels.filter(l => l.name !== 'bug').map(l => l.name).join(' · ')}</div>
                </div>
              ))
            ) : !ghError ? (
              <div style={{ ...bpS.critCard, borderLeftColor: palette.green }}>
                <span style={{ ...bpS.critTag, color: palette.green }}>无堵点</span>
                <div style={bpS.critBody}>当前无 bug 标签 open issue。</div>
              </div>
            ) : null}
            {/* Static: sample-count gate — always shown, no issue number */}
            <div style={{ ...bpS.critCard, borderLeftColor: palette.blue }}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                <span style={{ ...bpS.critTag, color: palette.blue }}>积累</span>
              </div>
              <div style={bpS.critTitle}>纸面样本 &lt; 30</div>
              <div style={bpS.critBody}>&lt; 30 独立样本前不谈胜率。持续跑官方纸面样本是一切有效性论断的前置门槛。</div>
            </div>
          </div>
        </div>

        {/* ── 八块完成度 ── */}
        <div>
          <div style={bpS.subHead}>八块完成度 · E4 工程成熟度 (ARCHITECTURE_MAP · 2026-08-09)</div>
          <div style={bpS.blockGrid}>
            {BP_BLOCKS.map(b => {
              const accent = b.ok ? palette.amber : palette.red;
              return (
                <div key={b.id} style={{ ...bpS.blockCard, borderTop:`3px solid ${accent}` }}>
                  <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                    <span style={{ ...bpS.blockId, color: accent }}>{b.id}</span>
                    {blockCounts[b.lbl] > 0 && (
                      <span style={{ ...bpS.mono, fontSize:11, color:palette.muted }}>{blockCounts[b.lbl]} open</span>
                    )}
                  </div>
                  <div style={bpS.blockName}>{b.name}</div>
                  <div style={bpS.blockSub}>{b.role} · {b.owner}</div>
                  <div style={bpS.blockBar}>
                    <div style={{ ...bpS.blockFill, width:`${b.pct}%`, background: accent }} />
                  </div>
                  <div style={{ ...bpS.blockPct, color: b.ok ? palette.ink : palette.red }}>
                    {b.pct}%{b.note ? ` · ${b.note}` : ''}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ── 在途工作流 + 开放 PR ── */}
        <div>
          <div style={bpS.subHead}>在途工作流 · 实时 GitHub Issues</div>
          <div style={bpS.streamGrid}>
            {STREAMS.map((s, si) => (
              <div key={s.title} style={bpS.streamCard}>
                <div style={bpS.streamHead}>
                  <span style={bpS.streamTitle}>{s.title}</span>
                  <span style={bpS.streamCount}>{streamIssues[si]?.length ?? 0} open</span>
                </div>
                <div style={bpS.streamSub}>{s.sub}</div>
                {ghLoading ? (
                  <div style={{ color:palette.muted, fontSize:12 }}>加载中…</div>
                ) : streamIssues[si]?.length ? (
                  streamIssues[si].slice(0, 9).map(iss => (
                    <a key={iss.number} href={GH_ISSUE_LINK(iss.number)} target="_blank" rel="noreferrer" style={bpS.issRow}>
                      <span style={{ ...bpS.issNum, color:palette.blue }}>#{iss.number}</span>
                      <span style={bpS.issTitle}>{iss.title}</span>
                      <ExternalLink size={11} style={{ flexShrink:0, color:palette.muted }} />
                    </a>
                  ))
                ) : (
                  <div style={{ color:palette.muted, fontSize:12 }}>No open issues.</div>
                )}
              </div>
            ))}

            {/* 开放 PR */}
            <div style={bpS.streamCard}>
              <div style={bpS.streamHead}>
                <span style={bpS.streamTitle}>开放 PR</span>
                <span style={bpS.streamCount}>{prs.length}</span>
              </div>
              <div style={bpS.streamSub}>等待 Junyan 审核合并</div>
              {ghLoading ? (
                <div style={{ color:palette.muted, fontSize:12 }}>加载中…</div>
              ) : prs.length ? (
                prs.slice(0, 9).map(pr => (
                  <a key={pr.number} href={GH_PR_LINK(pr.number)} target="_blank" rel="noreferrer" style={bpS.issRow}>
                    <span style={{ ...bpS.issNum, color:palette.violet }}>#{pr.number}</span>
                    <span style={bpS.issTitle}>{pr.title}</span>
                    <GitPullRequest size={11} style={{ flexShrink:0, color:palette.muted }} />
                  </a>
                ))
              ) : (
                <div style={{ color:palette.muted, fontSize:12 }}>No open PRs.</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export default function TeamProgressPage() {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [lastOkAt, setLastOkAt] = useState('');

  const loadSnapshot = useCallback(async ({ quiet = false } = {}) => {
    if (quiet) setRefreshing(true);
    else setLoading(true);
    setError('');

    try {
      const response = await fetch(ENDPOINT, { method: 'GET', cache: 'no-store' });
      const data = validateSnapshot(await readProgressApiResponse(response));
      setSnapshot(data);

      if (!response.ok || data.ok === false) {
        setError(data.error || `Progress API returned HTTP ${response.status}.`);
      } else {
        setLastOkAt(new Date().toISOString());
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadSnapshot();
    const timer = window.setInterval(() => loadSnapshot({ quiet: true }), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [loadSnapshot]);

  const summary = snapshot?.summary || {};
  const timeline = useMemo(() => {
    const items = Array.isArray(snapshot?.timeline) ? snapshot.timeline : [];
    return [...items].reverse();
  }, [snapshot]);
  const activeClaims = Array.isArray(snapshot?.active_claims) ? snapshot.active_claims : [];
  const conflicts = Array.isArray(snapshot?.conflicts) ? snapshot.conflicts : [];
  const source = snapshot?.source ? `${snapshot.source.kind}:${snapshot.source.value}` : 'n/a';

  return (
    <main style={styles.page}>
      <section style={styles.shell}>
        <header style={styles.header}>
          <div>
            <div style={styles.kicker}>
              <ShieldCheck size={15} />
              AI Progress Board
            </div>
            <h1 style={styles.title}>Team Progress</h1>
            <div style={styles.subline}>
              Source {source} · schema {snapshot?.schema || SNAPSHOT_SCHEMA} · v{snapshot?.contract_version || CONTRACT_VERSION}
            </div>
          </div>
          <div style={styles.headerActions}>
            <a href="/" style={styles.backLink}>Research</a>
            <button
              type="button"
              title="Refresh"
              onClick={() => loadSnapshot()}
              style={styles.iconButton}
            >
              <RefreshCw size={18} style={{ transform: refreshing ? 'rotate(45deg)' : 'none' }} />
            </button>
          </div>
        </header>

        {error && (
          <section style={styles.errorBand} role="status" aria-live="polite">
            <XCircle size={18} />
            <span>{error}</span>
          </section>
        )}

        <section style={styles.statusLine} aria-live="polite">
          <span>
            <Clock size={14} />
            Refreshed {formatTime(snapshot?.refreshed_at_utc)}
          </span>
          <span>
            <Activity size={14} />
            Last healthy read {formatTime(lastOkAt)}
          </span>
          <span>
            <Radio size={14} />
            30s polling
          </span>
        </section>

        <section style={styles.tiles}>
          <SummaryTile icon={Activity} label="Events" value={summary.events} tone={palette.blue} />
          <SummaryTile icon={Radio} label="Active" value={summary.active_claims} tone={palette.violet} />
          <SummaryTile icon={CheckCircle2} label="Done" value={summary.done} tone={palette.green} />
          <SummaryTile icon={AlertTriangle} label="Blocked" value={summary.blocked} tone={palette.red} />
          <SummaryTile icon={ShieldCheck} label="Released" value={summary.released} tone={palette.amber} />
          <SummaryTile icon={AlertTriangle} label="Conflicts" value={summary.conflicts} tone={summary.conflicts ? palette.red : palette.green} />
        </section>

        <CommentComposer onSubmitted={() => loadSnapshot({ quiet: true })} />

        <section style={styles.columns}>
          <section style={styles.panel}>
            <div style={styles.panelHead}>
              <h2 style={styles.panelTitle}>Active Claims</h2>
              <span style={styles.countPill}>{activeClaims.length}</span>
            </div>
            <div style={styles.stack}>
              {loading && !snapshot ? (
                <EmptyState text="Loading progress snapshot." />
              ) : activeClaims.length ? (
                activeClaims.map((claim) => (
                  <ActiveClaim key={`${claim.task}-${claim.human_owner}-${claim.executor}`} claim={claim} />
                ))
              ) : (
                <EmptyState text="No active claims." />
              )}
            </div>
          </section>

          <section style={styles.panel}>
            <div style={styles.panelHead}>
              <h2 style={styles.panelTitle}>Conflicts</h2>
              <span style={{ ...styles.countPill, color: conflicts.length ? palette.red : palette.green }}>
                {conflicts.length}
              </span>
            </div>
            <div style={styles.stack}>
              {conflicts.length ? (
                conflicts.map((conflict) => (
                  <ConflictRow
                    key={`${conflict.left_task}-${conflict.right_task}-${conflict.left}-${conflict.right}`}
                    conflict={conflict}
                  />
                ))
              ) : (
                <EmptyState text="No file-scope conflicts." />
              )}
            </div>
          </section>
        </section>

        <section style={styles.panel}>
          <div style={styles.panelHead}>
            <h2 style={styles.panelTitle}>Timeline</h2>
            <span style={styles.countPill}>{timeline.length}</span>
          </div>
          <div style={styles.timeline}>
            {timeline.length ? (
              timeline.map((item, index) => (
                <TimelineItem key={`${item.timestamp_utc}-${item.event}-${item.task}-${index}`} item={item} />
              ))
            ) : (
              <EmptyState text={loading ? 'Loading progress snapshot.' : 'No progress events.'} />
            )}
          </div>
        </section>

        <ProjectBlueprint />
      </section>
    </main>
  );
}

const styles = {
  page: {
    minHeight: '100vh',
    background: palette.bg,
    color: palette.ink,
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    letterSpacing: 0,
  },
  shell: {
    width: 'min(1240px, calc(100vw - 32px))',
    margin: '0 auto',
    padding: '24px 0 40px',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 16,
    paddingBottom: 18,
    borderBottom: `1px solid ${palette.line}`,
  },
  kicker: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    color: palette.green,
    fontSize: 13,
    fontWeight: 700,
  },
  title: {
    margin: '6px 0 6px',
    fontSize: 32,
    lineHeight: 1.05,
    fontWeight: 800,
    letterSpacing: 0,
  },
  subline: {
    color: palette.muted,
    fontSize: 13,
    lineHeight: 1.5,
  },
  headerActions: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  },
  backLink: {
    color: palette.ink,
    textDecoration: 'none',
    border: `1px solid ${palette.line}`,
    background: palette.panel,
    borderRadius: 6,
    padding: '9px 12px',
    fontSize: 13,
    fontWeight: 700,
  },
  iconButton: {
    width: 40,
    height: 40,
    display: 'grid',
    placeItems: 'center',
    border: `1px solid ${palette.line}`,
    background: palette.panel,
    color: palette.ink,
    borderRadius: 6,
    cursor: 'pointer',
  },
  errorBand: {
    marginTop: 16,
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '12px 14px',
    background: '#fff1f0',
    border: `1px solid ${palette.red}44`,
    color: palette.red,
    borderRadius: 8,
    fontSize: 13,
    fontWeight: 700,
  },
  statusLine: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 12,
    marginTop: 16,
    color: palette.muted,
    fontSize: 12,
  },
  tiles: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
    gap: 12,
    marginTop: 16,
  },
  tile: {
    minHeight: 76,
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: 14,
    background: palette.panel,
    border: `1px solid ${palette.line}`,
    borderRadius: 8,
  },
  tileIcon: {
    width: 38,
    height: 38,
    display: 'grid',
    placeItems: 'center',
    borderRadius: 6,
  },
  tileLabel: {
    color: palette.muted,
    fontSize: 12,
    fontWeight: 700,
  },
  tileValue: {
    marginTop: 2,
    fontFamily: "'JetBrains Mono', 'Courier New', monospace",
    fontSize: 24,
    fontWeight: 800,
  },
  columns: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
    gap: 16,
    marginTop: 16,
  },
  panel: {
    background: palette.panel,
    border: `1px solid ${palette.line}`,
    borderRadius: 8,
    overflow: 'hidden',
  },
  panelHead: {
    minHeight: 50,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    padding: '12px 14px',
    borderBottom: `1px solid ${palette.line}`,
    background: palette.soft,
  },
  panelTitle: {
    margin: 0,
    fontSize: 15,
    lineHeight: 1.2,
    fontWeight: 800,
    letterSpacing: 0,
  },
  panelHint: {
    marginTop: 4,
    color: palette.muted,
    fontSize: 12,
    lineHeight: 1.4,
  },
  issueLink: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    color: palette.blue,
    textDecoration: 'none',
    fontSize: 12,
    fontWeight: 800,
    whiteSpace: 'nowrap',
  },
  countPill: {
    minWidth: 28,
    height: 26,
    display: 'grid',
    placeItems: 'center',
    padding: '0 8px',
    borderRadius: 6,
    background: palette.panel,
    border: `1px solid ${palette.line}`,
    fontFamily: "'JetBrains Mono', 'Courier New', monospace",
    fontWeight: 800,
    color: palette.ink,
  },
  stack: {
    display: 'grid',
    gap: 10,
    padding: 12,
  },
  composerBody: {
    display: 'grid',
    gap: 12,
    padding: 12,
  },
  formGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
    gap: 10,
  },
  formField: {
    display: 'grid',
    gap: 5,
    minWidth: 0,
  },
  formLabel: {
    color: palette.muted,
    fontSize: 11,
    fontWeight: 800,
  },
  input: {
    width: '100%',
    minHeight: 38,
    boxSizing: 'border-box',
    border: `1px solid ${palette.line}`,
    borderRadius: 6,
    padding: '8px 10px',
    background: '#fff',
    color: palette.ink,
    fontSize: 13,
    lineHeight: 1.4,
  },
  textarea: {
    width: '100%',
    minHeight: 64,
    boxSizing: 'border-box',
    border: `1px solid ${palette.line}`,
    borderRadius: 6,
    padding: '8px 10px',
    background: '#fff',
    color: palette.ink,
    fontSize: 13,
    lineHeight: 1.5,
    resize: 'vertical',
  },
  commentBox: {
    width: '100%',
    minHeight: 220,
    boxSizing: 'border-box',
    border: `1px solid ${palette.line}`,
    borderRadius: 8,
    padding: 12,
    background: '#fbfcf8',
    color: palette.ink,
    fontFamily: "'JetBrains Mono', 'Courier New', monospace",
    fontSize: 12,
    lineHeight: 1.45,
    resize: 'vertical',
  },
  composerActions: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 10,
  },
  copyButton: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 7,
    minHeight: 38,
    border: `1px solid ${palette.blue}55`,
    borderRadius: 6,
    padding: '8px 12px',
    background: palette.blue,
    color: '#fff',
    fontSize: 13,
    fontWeight: 800,
    cursor: 'pointer',
  },
  submitButton: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 7,
    minHeight: 38,
    border: `1px solid ${palette.green}55`,
    borderRadius: 6,
    padding: '8px 12px',
    background: palette.green,
    color: '#fff',
    fontSize: 13,
    fontWeight: 800,
    cursor: 'pointer',
  },
  copyStatus: {
    color: palette.muted,
    fontSize: 12,
    lineHeight: 1.4,
  },
  claimCard: {
    border: `1px solid ${palette.line}`,
    borderRadius: 8,
    padding: 12,
    background: '#fff',
  },
  claimTop: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'flex-start',
  },
  taskLine: {
    fontSize: 14,
    fontWeight: 800,
    lineHeight: 1.3,
  },
  summaryText: {
    marginTop: 4,
    color: palette.muted,
    fontSize: 13,
    lineHeight: 1.55,
    overflowWrap: 'anywhere',
  },
  metaGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
    gap: '8px 12px',
    marginTop: 12,
  },
  fieldLine: {
    minWidth: 0,
  },
  fieldLabel: {
    display: 'block',
    color: palette.muted,
    fontSize: 11,
    fontWeight: 700,
  },
  fieldValue: {
    display: 'block',
    color: palette.ink,
    fontSize: 12,
    lineHeight: 1.5,
    overflowWrap: 'anywhere',
  },
  chipWrap: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: 10,
  },
  chip: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    maxWidth: '100%',
    padding: '4px 7px',
    borderRadius: 6,
    background: palette.soft,
    border: `1px solid ${palette.line}`,
    color: palette.ink,
    fontSize: 11,
    overflowWrap: 'anywhere',
  },
  conflictRow: {
    border: `1px solid ${palette.red}44`,
    borderRadius: 8,
    padding: 12,
    background: '#fff7f5',
  },
  conflictTitle: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    color: palette.red,
    fontWeight: 800,
    fontSize: 13,
  },
  conflictBody: {
    marginTop: 6,
    color: palette.muted,
    fontSize: 12,
    lineHeight: 1.5,
  },
  timeline: {
    display: 'grid',
    gap: 10,
    maxHeight: '58vh',
    overflowY: 'auto',
    padding: 12,
  },
  timelineItem: {
    position: 'relative',
    border: `1px solid ${palette.line}`,
    borderLeft: '4px solid',
    borderRadius: 8,
    padding: 12,
    background: '#fff',
  },
  timelineHead: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
  },
  timelineTitle: {
    marginTop: 8,
    fontSize: 14,
    fontWeight: 800,
  },
  timelineMeta: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 10,
    marginTop: 8,
    color: palette.muted,
    fontSize: 12,
  },
  timeText: {
    color: palette.muted,
    fontSize: 12,
    whiteSpace: 'nowrap',
  },
  badge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    height: 26,
    padding: '0 8px',
    border: '1px solid',
    borderRadius: 6,
    fontSize: 11,
    fontWeight: 800,
    whiteSpace: 'nowrap',
  },
  prLink: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    marginTop: 10,
    color: palette.blue,
    fontSize: 12,
    fontWeight: 800,
    textDecoration: 'none',
  },
  empty: {
    minHeight: 72,
    display: 'grid',
    placeItems: 'center',
    color: palette.muted,
    border: `1px dashed ${palette.line}`,
    borderRadius: 8,
    fontSize: 13,
    background: '#fff',
  },
};
