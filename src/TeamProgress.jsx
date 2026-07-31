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
  ShieldCheck,
  UserRound,
  XCircle,
} from 'lucide-react';

const ENDPOINT = '/api/team-progress';
const SNAPSHOT_SCHEMA = 'ai-progress.snapshot.v1';
const CONTRACT_VERSION = '1.5';
const REFRESH_MS = 30000;

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
      const data = validateSnapshot(await response.json());
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
