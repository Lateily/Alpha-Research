const DEFAULT_REPO = 'Lateily/Alpha-Research';
const DEFAULT_ISSUE = '164';
const SNAPSHOT_SCHEMA = 'ai-progress.snapshot.v1';
const CONTRACT_VERSION = '1.5';
const EVENT_TYPES = new Set(['CLAIM', 'UPDATE', 'DONE', 'BLOCKED', 'RELEASE']);
const FENCED_JSON_RE = /```json\s*(\{[\s\S]*?\})\s*```/g;

function zeroSummary() {
  return {
    events: 0,
    active_claims: 0,
    done: 0,
    blocked: 0,
    released: 0,
    conflicts: 0,
  };
}

function baseSnapshot(source) {
  return {
    schema: SNAPSHOT_SCHEMA,
    contract_version: CONTRACT_VERSION,
    ok: false,
    source,
    refreshed_at_utc: new Date().toISOString(),
    summary: zeroSummary(),
    active_claims: [],
    conflicts: [],
    timeline: [],
  };
}

function parseEventsFromComments(comments) {
  const events = [];
  for (const comment of comments) {
    const body = typeof comment?.body === 'string' ? comment.body : '';
    for (const match of body.matchAll(FENCED_JSON_RE)) {
      try {
        const candidate = JSON.parse(match[1]);
        if (EVENT_TYPES.has(candidate.event)) events.push(normalizeEvent(candidate));
      } catch {
        // Ignore malformed fenced JSON. The board is append-only and must not break on one bad comment.
      }
    }
  }
  return events;
}

function normalizeEvent(event) {
  const normalized = {
    schema: event.schema,
    event: event.event,
    task: String(event.task || ''),
    human_owner: String(event.human_owner || event.owner || ''),
    executor: String(event.executor || 'unknown'),
    reviewer: String(event.reviewer || 'unknown'),
    status: event.status,
    summary: event.summary,
    branch: event.branch,
    files: Array.isArray(event.files) ? event.files.map(String) : undefined,
    pr: event.pr,
    next: event.next,
    blocked_by: event.blocked_by,
    cost_cny: event.cost_cny,
    risk: event.risk,
    timestamp_utc: event.timestamp_utc,
    expires_at: event.expires_at || event.expires_at_utc,
  };

  return Object.fromEntries(
    Object.entries(normalized).filter(([, value]) => {
      if (value === undefined || value === null || value === '') return false;
      if (Array.isArray(value) && value.length === 0) return false;
      return true;
    })
  );
}

function eventKey(event) {
  return `${event.task || ''}::${event.human_owner || ''}::${event.executor || ''}`;
}

function parseTime(value) {
  const time = value ? Date.parse(value) : Number.NEGATIVE_INFINITY;
  return Number.isFinite(time) ? time : Number.NEGATIVE_INFINITY;
}

function activeClaims(events, nowMs) {
  const claimsByKey = new Map();
  const sorted = [...events].sort((a, b) => {
    return String(a.timestamp_utc || '').localeCompare(String(b.timestamp_utc || ''));
  });

  for (const event of sorted) {
    const key = eventKey(event);
    if (event.event === 'DONE' || event.event === 'RELEASE') {
      claimsByKey.delete(key);
      continue;
    }
    if (event.event !== 'CLAIM') continue;
    if (parseTime(event.expires_at) > nowMs) claimsByKey.set(key, event);
  }

  return [...claimsByKey.values()];
}

function actor(event) {
  return `${event.human_owner || 'unknown'}:${event.executor || 'unknown'}`;
}

function normalizePath(value) {
  return String(value || '').replace(/\\/g, '/').trim().replace(/^\/+|\/+$/g, '').toLowerCase();
}

function overlappingFiles(leftFiles = [], rightFiles = []) {
  const left = leftFiles.map(normalizePath);
  const right = rightFiles.map(normalizePath);
  const overlaps = [];

  for (const leftPath of left) {
    for (const rightPath of right) {
      if (!leftPath || !rightPath) continue;
      if (
        leftPath === rightPath ||
        leftPath.startsWith(`${rightPath}/`) ||
        rightPath.startsWith(`${leftPath}/`)
      ) {
        overlaps.push(`${leftPath}<->${rightPath}`);
      }
    }
  }
  return overlaps;
}

function findConflicts(active) {
  const conflicts = [];
  for (let i = 0; i < active.length; i += 1) {
    for (let j = i + 1; j < active.length; j += 1) {
      const left = active[i];
      const right = active[j];
      const files = overlappingFiles(left.files || [], right.files || []);
      if (files.length > 0 && actor(left) !== actor(right)) {
        conflicts.push({
          left: actor(left),
          right: actor(right),
          left_task: left.task || '',
          right_task: right.task || '',
          files,
        });
      }
    }
  }
  return conflicts;
}

function summarize(events, active, conflicts) {
  return {
    events: events.length,
    active_claims: active.length,
    done: events.filter((event) => event.event === 'DONE').length,
    blocked: events.filter((event) => event.event === 'BLOCKED').length,
    released: events.filter((event) => event.event === 'RELEASE').length,
    conflicts: conflicts.length,
  };
}

async function fetchGithubComments(repo, issue) {
  const url = `https://api.github.com/repos/${repo}/issues/${issue}/comments?per_page=100`;
  const headers = {
    Accept: 'application/vnd.github+json',
    'User-Agent': 'alpha-research-team-progress',
  };
  const token = process.env.GITHUB_TOKEN || process.env.PROGRESS_GITHUB_TOKEN;
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(url, { headers });
  if (!response.ok) {
    throw new Error(`GitHub comments read failed: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

function allowCors(req, res) {
  const origin = req.headers?.origin;
  const localOrigins = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'https://lateily.github.io',
  ];
  const configured = (process.env.PROGRESS_ALLOWED_ORIGINS || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  const allowed = [...localOrigins, ...configured];

  if (origin && allowed.includes(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
  }
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
}

export default async function handler(req, res) {
  allowCors(req, res);
  res.setHeader('X-Progress-Board-Readonly', 'true');
  res.setHeader('Cache-Control', 's-maxage=30, stale-while-revalidate=60');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });

  const repo = process.env.PROGRESS_REPO || DEFAULT_REPO;
  const issue = process.env.PROGRESS_ISSUE || DEFAULT_ISSUE;
  const source = { kind: 'github', value: `${repo}#${issue}` };
  const snapshot = baseSnapshot(source);

  try {
    const comments = await fetchGithubComments(repo, issue);
    const events = parseEventsFromComments(Array.isArray(comments) ? comments : []);
    const active = activeClaims(events, Date.now()).sort((a, b) => {
      return String(a.expires_at || '').localeCompare(String(b.expires_at || ''));
    });
    const conflicts = findConflicts(active);

    return res.status(200).json({
      ...snapshot,
      ok: true,
      summary: summarize(events, active, conflicts),
      active_claims: active,
      conflicts,
      timeline: events.sort((a, b) => {
        return String(a.timestamp_utc || '').localeCompare(String(b.timestamp_utc || ''));
      }),
    });
  } catch (error) {
    return res.status(502).json({
      ...snapshot,
      error: error instanceof Error ? error.message : String(error),
    });
  }
}
