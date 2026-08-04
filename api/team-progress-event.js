import { timingSafeEqual as cryptoTimingSafeEqual } from 'node:crypto';

const DEFAULT_REPO = 'Lateily/Alpha-Research';
const DEFAULT_ISSUE = '164';
const EVENT_TYPES = new Set(['CLAIM', 'UPDATE', 'DONE', 'BLOCKED', 'RELEASE']);
const STATUS_BY_EVENT = {
  CLAIM: 'in_progress',
  UPDATE: 'in_progress',
  DONE: 'done',
  BLOCKED: 'blocked',
  RELEASE: 'released',
};
const DEFAULT_TTL_MS = 3 * 60 * 60 * 1000;
// Best-effort per-instance rate limit. Serverless instances do not share state,
// so this bounds abuse per warm instance only — honest limit, not a guarantee.
const RATE_WINDOW_MS = 10 * 60 * 1000;
const RATE_MAX_POSTS = 6;
const rateLog = [];

function rateLimited(now = Date.now()) {
  while (rateLog.length && now - rateLog[0] > RATE_WINDOW_MS) rateLog.shift();
  if (rateLog.length >= RATE_MAX_POSTS) return true;
  rateLog.push(now);
  return false;
}
const MAX_FIELD_LENGTH = 1200;
const MAX_FILES = 20;
const MAX_FILE_LENGTH = 180;

function allowCors(req, res) {
  const origin = req.headers?.origin;
  const localOrigins = ['http://localhost:5173', 'http://127.0.0.1:5173'];
  const configured = (process.env.PROGRESS_ALLOWED_ORIGINS || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  const allowed = [...localOrigins, ...configured];

  if (origin && allowed.includes(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
  }
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-Progress-Write-Key');
}

function headerValue(req, name) {
  const value = req.headers?.[name] || req.headers?.[name.toLowerCase()];
  return Array.isArray(value) ? value[0] : value;
}

function timingSafeEqualString(a, b) {
  // Constant-time compare: a plain !== leaks length/prefix timing.
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  const bufA = Buffer.from(a, 'utf8');
  const bufB = Buffer.from(b, 'utf8');
  if (bufA.length !== bufB.length) {
    // Still burn a comparison so length mismatch costs the same as content mismatch.
    cryptoTimingSafeEqual(bufB, bufB);
    return false;
  }
  return cryptoTimingSafeEqual(bufA, bufB);
}

function requireWriteAccess(req) {
  const configuredKey = process.env.PROGRESS_WRITE_KEY;
  if (!configuredKey) {
    return { ok: false, code: 503, error: 'PROGRESS_WRITE_KEY is not configured.' };
  }

  const providedKey = headerValue(req, 'x-progress-write-key');
  if (!timingSafeEqualString(providedKey || '', configuredKey)) {
    return { ok: false, code: 401, error: 'Invalid progress write key.' };
  }

  const token = process.env.PROGRESS_GITHUB_TOKEN || process.env.GITHUB_TOKEN;
  if (!token) {
    return { ok: false, code: 503, error: 'PROGRESS_GITHUB_TOKEN is not configured.' };
  }

  return { ok: true, token };
}

async function parseBody(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  if (typeof req.body === 'string') return JSON.parse(req.body);

  const chunks = [];
  for await (const chunk of req) chunks.push(Buffer.from(chunk));
  const raw = Buffer.concat(chunks).toString('utf8').trim();
  return raw ? JSON.parse(raw) : {};
}

function cleanString(value, field) {
  if (value === undefined || value === null) return '';
  if (typeof value !== 'string') throw new Error(`${field} must be a string.`);
  const cleaned = value.trim();
  if (cleaned.length > MAX_FIELD_LENGTH) throw new Error(`${field} is too long.`);
  return cleaned;
}

function cleanFiles(value) {
  if (value === undefined || value === null || value === '') return [];
  const rawItems = Array.isArray(value) ? value : String(value).split(',');
  const files = rawItems
    .map((item) => String(item).trim().replace(/\\/g, '/'))
    .filter(Boolean);

  if (files.length > MAX_FILES) throw new Error('files has too many entries.');
  for (const file of files) {
    if (file.length > MAX_FILE_LENGTH) throw new Error('files contains an entry that is too long.');
    if (file.startsWith('/') || file.includes('..')) {
      throw new Error('files must stay inside repository-relative paths.');
    }
  }
  return files;
}

function requireFields(event, payload) {
  const required = ['task', 'human_owner', 'executor', 'reviewer', 'summary'];
  if (event === 'CLAIM') required.push('branch', 'files');

  for (const field of required) {
    if (field === 'files') {
      if (!payload.files.length) throw new Error('CLAIM requires at least one file or folder scope.');
      continue;
    }
    if (!payload[field]) throw new Error(`${field} is required.`);
  }
}

function buildProgressEvent(input, now = new Date()) {
  const event = cleanString(input.event || 'CLAIM', 'event').toUpperCase();
  if (!EVENT_TYPES.has(event)) throw new Error(`Unsupported event: ${event || 'missing'}.`);

  const payload = {
    schema: 'ai-progress.v2',
    event,
    task: cleanString(input.task, 'task'),
    human_owner: cleanString(input.human_owner, 'human_owner'),
    executor: cleanString(input.executor, 'executor'),
    reviewer: cleanString(input.reviewer, 'reviewer'),
    status: STATUS_BY_EVENT[event],
    summary: cleanString(input.summary, 'summary'),
    branch: cleanString(input.branch, 'branch'),
    files: cleanFiles(input.files),
    pr: cleanString(input.pr, 'pr'),
    next: cleanString(input.next, 'next'),
    blocked_by: cleanString(input.blocked_by, 'blocked_by'),
    cost_cny: cleanString(input.cost_cny, 'cost_cny'),
    risk: cleanString(input.risk || 'none', 'risk'),
    timestamp_utc: now.toISOString(),
  };

  if (payload.cost_cny && !/^[0-9]+(\.[0-9]+)?$/.test(payload.cost_cny)) {
    throw new Error('cost_cny must be a numeric string.');
  }

  if (event === 'CLAIM') {
    payload.expires_at = new Date(now.getTime() + DEFAULT_TTL_MS).toISOString();
  }

  requireFields(event, payload);

  return Object.fromEntries(
    Object.entries(payload).filter(([, value]) => {
      if (Array.isArray(value)) return value.length > 0;
      return value !== undefined && value !== null && value !== '';
    })
  );
}

function formatComment(event) {
  return `<!-- ai-progress:v2 -->\n\`\`\`json\n${JSON.stringify(event, null, 2)}\n\`\`\``;
}

const FENCED_JSON_RE = /```json\s*(\{[\s\S]*?\})\s*```/g;

function activeClaims(comments, nowMs = Date.now()) {
  // Same parse discipline as the read endpoint: fenced JSON blocks only,
  // CLAIM closed by matching DONE/RELEASE on the same task, or by expiry.
  const claims = new Map();
  for (const comment of comments) {
    const body = typeof comment?.body === 'string' ? comment.body : '';
    for (const match of body.matchAll(FENCED_JSON_RE)) {
      let event;
      try {
        event = JSON.parse(match[1]);
      } catch {
        continue;
      }
      const task = String(event.task || '');
      if (event.event === 'CLAIM') {
        const expires = event.expires_at ? Date.parse(event.expires_at) : 0;
        if (expires > nowMs) claims.set(task, event);
      } else if (event.event === 'DONE' || event.event === 'RELEASE') {
        claims.delete(task);
      }
    }
  }
  return claims;
}

function claimConflict(claims, candidate) {
  const actor = (e) => `${e.human_owner || ''}:${e.executor || ''}`;
  const mine = actor(candidate);
  const files = new Set(candidate.files || []);
  for (const claim of claims.values()) {
    if (actor(claim) === mine) continue;                 // 同人续领不算冲突
    if (String(claim.task || '') === candidate.task) return claim;
    for (const f of claim.files || []) {
      if (files.has(f)) return claim;
    }
  }
  return null;
}

async function fetchIssueComments(repo, issue, token) {
  const url = `https://api.github.com/repos/${repo}/issues/${issue}/comments?per_page=100`;
  const response = await fetch(url, {
    headers: {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${token}`,
      'User-Agent': 'alpha-research-team-progress',
    },
  });
  if (!response.ok) throw new Error(`GitHub comments read failed: ${response.status}`);
  return response.json();
}

async function postGithubComment(repo, issue, token, body) {
  const url = `https://api.github.com/repos/${repo}/issues/${issue}/comments`;
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      'User-Agent': 'alpha-research-team-progress',
    },
    body: JSON.stringify({ body }),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`GitHub comment write failed: ${response.status} ${response.statusText}`);
  }
  return data;
}

export { buildProgressEvent, formatComment, activeClaims, claimConflict, rateLimited };

export default async function handler(req, res) {
  allowCors(req, res);
  res.setHeader('X-Progress-Board-Write', 'server-only');
  res.setHeader('Cache-Control', 'no-store');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ ok: false, error: 'Method not allowed' });

  const access = requireWriteAccess(req);
  if (!access.ok) return res.status(access.code).json({ ok: false, error: access.error });

  if (rateLimited()) {
    return res.status(429).json({ ok: false, error: 'Rate limited: too many progress posts. Wait a few minutes.' });
  }

  try {
    const input = await parseBody(req);
    const event = buildProgressEvent(input);
    const comment = formatComment(event);
    const repo = process.env.PROGRESS_REPO || DEFAULT_REPO;
    const issue = process.env.PROGRESS_ISSUE || DEFAULT_ISSUE;
    if (event.event === 'CLAIM') {
      // Protocol: run the conflict check BEFORE posting a CLAIM — checking after
      // a collision is only an after-the-fact audit.
      const comments = await fetchIssueComments(repo, issue, access.token);
      const conflict = claimConflict(activeClaims(Array.isArray(comments) ? comments : []), event);
      if (conflict) {
        return res.status(409).json({
          ok: false,
          error: 'Active CLAIM overlaps this task or file scope. Coordinate under the earlier CLAIM.',
          conflict: { task: conflict.task, human_owner: conflict.human_owner,
                      executor: conflict.executor, expires_at: conflict.expires_at || '' },
        });
      }
    }
    const result = await postGithubComment(repo, issue, access.token, comment);

    return res.status(201).json({
      ok: true,
      source: { kind: 'github', value: `${repo}#${issue}` },
      event,
      comment_url: result.html_url || '',
    });
  } catch (error) {
    return res.status(400).json({
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    });
  }
}
