import assert from 'node:assert/strict';

import handler, { buildProgressEvent, formatComment, activeClaims, claimConflict, rateLimited } from '../api/team-progress-event.js';

function makeResponse() {
  return {
    code: null,
    headers: {},
    body: null,
    ended: false,
    setHeader(name, value) {
      this.headers[name] = value;
    },
    status(code) {
      this.code = code;
      return this;
    },
    json(payload) {
      this.body = payload;
      return this;
    },
    end() {
      this.ended = true;
      return this;
    },
  };
}

function basePayload(overrides = {}) {
  return {
    event: 'CLAIM',
    task: '#demo',
    human_owner: 'Reed',
    executor: 'Codex',
    reviewer: 'Junyan',
    summary: 'Claim progress board v2.1 write endpoint.',
    branch: 'feat/demo',
    files: ['api/team-progress-event.js'],
    cost_cny: '0',
    risk: 'server token only',
    ...overrides,
  };
}

async function withEnv(values, fn) {
  const previous = {};
  for (const key of Object.keys(values)) {
    previous[key] = process.env[key];
    if (values[key] === undefined) delete process.env[key];
    else process.env[key] = values[key];
  }

  try {
    await fn();
  } finally {
    for (const key of Object.keys(values)) {
      if (previous[key] === undefined) delete process.env[key];
      else process.env[key] = previous[key];
    }
  }
}

async function testMissingWriteKeyDoesNotCallGitHub() {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new Error('fetch should not be called');
  };

  try {
    await withEnv(
      {
        PROGRESS_WRITE_KEY: undefined,
        PROGRESS_GITHUB_TOKEN: 'token',
      },
      async () => {
        const req = { method: 'POST', headers: {}, body: basePayload() };
        const res = makeResponse();
        await handler(req, res);

        assert.equal(res.code, 503);
        assert.equal(res.body.ok, false);
        assert.match(res.body.error, /PROGRESS_WRITE_KEY/);
        assert.equal(calls, 0);
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function testInvalidWriteKeyDoesNotCallGitHub() {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new Error('fetch should not be called');
  };

  try {
    await withEnv(
      {
        PROGRESS_WRITE_KEY: 'expected',
        PROGRESS_GITHUB_TOKEN: 'token',
      },
      async () => {
        const req = {
          method: 'POST',
          headers: { 'x-progress-write-key': 'wrong' },
          body: basePayload(),
        };
        const res = makeResponse();
        await handler(req, res);

        assert.equal(res.code, 401);
        assert.equal(res.body.ok, false);
        assert.equal(calls, 0);
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function testOfficialGithubPagesOriginIsAllowed() {
  const req = { method: 'OPTIONS', headers: { origin: 'https://lateily.github.io' } };
  const res = makeResponse();
  await handler(req, res);

  assert.equal(res.code, 200);
  assert.equal(res.headers['Access-Control-Allow-Origin'], 'https://lateily.github.io');
}

async function testValidPostWritesStandardComment() {
  const originalFetch = globalThis.fetch;
  const calls = [];

  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      status: 201,
      statusText: 'Created',
      async json() {
        return { html_url: 'https://github.com/Lateily/Alpha-Research/issues/164#issuecomment-demo' };
      },
    };
  };

  try {
    await withEnv(
      {
        PROGRESS_WRITE_KEY: 'expected',
        PROGRESS_GITHUB_TOKEN: 'server-token',
        GITHUB_TOKEN: undefined,
      },
      async () => {
        const req = {
          method: 'POST',
          headers: { 'x-progress-write-key': 'expected', origin: 'http://localhost:5173' },
          body: basePayload({ event: 'DONE', branch: '', files: [] }),
        };
        const res = makeResponse();
        await handler(req, res);

        assert.equal(res.code, 201);
        assert.equal(res.body.ok, true);
        assert.equal(res.body.event.event, 'DONE');
        assert.equal(res.body.event.status, 'done');
        assert.equal(res.headers['X-Progress-Board-Write'], 'server-only');
        assert.equal(res.headers['Access-Control-Allow-Origin'], 'http://localhost:5173');
        assert.equal(calls.length, 1);
        assert.equal(
          calls[0].url,
          'https://api.github.com/repos/Lateily/Alpha-Research/issues/164/comments'
        );
        assert.equal(calls[0].options.method, 'POST');
        assert.equal(calls[0].options.headers.Authorization, 'Bearer server-token');

        const posted = JSON.parse(calls[0].options.body);
        assert.match(posted.body, /<!-- ai-progress:v2 -->/);
        assert.match(posted.body, /"event": "DONE"/);
        assert.doesNotMatch(JSON.stringify(res.body), /server-token/);
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function testValidationRejectsUnsafeFilesBeforeWrite() {
  assert.throws(
    () => buildProgressEvent(basePayload({ files: ['../outside'] })),
    /repository-relative paths/
  );
}

function testCommentFormat() {
  const event = buildProgressEvent(basePayload(), new Date('2026-08-05T00:00:00.000Z'));
  const comment = formatComment(event);

  assert.match(comment, /<!-- ai-progress:v2 -->/);
  assert.match(comment, /```json/);
  assert.match(comment, /"schema": "ai-progress.v2"/);
  assert.equal(event.expires_at, '2026-08-05T03:00:00.000Z');
}

await testMissingWriteKeyDoesNotCallGitHub();
await testInvalidWriteKeyDoesNotCallGitHub();
await testOfficialGithubPagesOriginIsAllowed();
await testValidPostWritesStandardComment();
await testValidationRejectsUnsafeFilesBeforeWrite();
testCommentFormat();


// ── 边界修订(Junyan 2026-08-04)配套加固的回归 ──────────────────────────────

// ① CLAIM 冲突:协议要求发 CLAIM 前查活跃 CLAIM —— 服务端必须自己查,不能信客户端
{
  const now = Date.now();
  const mk = (event, task, owner, exec, extra = {}) => ({
    body: '```json\n' + JSON.stringify({ event, task, human_owner: owner, executor: exec,
      files: extra.files || [], expires_at: extra.expires_at }) + '\n```',
  });
  const live = new Date(now + 60 * 60 * 1000).toISOString();
  // 同任务、不同人 → 冲突
  const claims = activeClaims([mk('CLAIM', '#x', 'Reed', 'Codex', { expires_at: live })], now);
  assert.ok(claimConflict(claims, { task: '#x', human_owner: 'Better', executor: 'Codex', files: [] }),
    'same-task different-actor must conflict');
  // 文件域交叠 → 冲突
  const claims2 = activeClaims([mk('CLAIM', '#a', 'Reed', 'Codex',
    { expires_at: live, files: ['api/x.js'] })], now);
  assert.ok(claimConflict(claims2, { task: '#b', human_owner: 'Better', executor: 'Codex',
    files: ['api/x.js'] }), 'file-scope overlap must conflict');
  // 同人续领 → 放行
  assert.equal(claimConflict(claims, { task: '#x', human_owner: 'Reed', executor: 'Codex', files: [] }),
    null, 'same actor renewal must pass');
  // DONE 关闭 → 放行
  const closed = activeClaims([
    mk('CLAIM', '#x', 'Reed', 'Codex', { expires_at: live }),
    mk('DONE', '#x', 'Reed', 'Codex'),
  ], now);
  assert.equal(claimConflict(closed, { task: '#x', human_owner: 'Better', executor: 'Codex', files: [] }),
    null, 'DONE-closed claim must not conflict');
  // 过期 → 放行
  const expired = activeClaims([mk('CLAIM', '#x', 'Reed', 'Codex',
    { expires_at: new Date(now - 1000).toISOString() })], now);
  assert.equal(expired.size, 0, 'expired claim must not be active');
  console.log('PASS claim conflict gate (same-task / file-overlap / renewal / DONE / expiry)');
}

// ② handler 层:活跃冲突 ⇒ 409,且**不发**写请求
await withEnv({ PROGRESS_WRITE_KEY: 'k', PROGRESS_GITHUB_TOKEN: 't' }, async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const live = new Date(Date.now() + 3600 * 1000).toISOString();
  globalThis.fetch = async (url, opts = {}) => {
    calls.push({ url: String(url), method: opts.method || 'GET' });
    return {
      ok: true,
      json: async () => [{ body: '```json\n' + JSON.stringify({
        event: 'CLAIM', task: '#demo', human_owner: 'Better', executor: 'Codex',
        files: [], expires_at: live }) + '\n```' }],
    };
  };
  try {
    const res = makeResponse();
    await handler({ method: 'POST', headers: { 'x-progress-write-key': 'k' },
      body: basePayload() }, res);
    assert.equal(res.code, 409, `expected 409, got ${res.code}`);
    assert.ok(!calls.some((c) => c.method === 'POST'), 'must not POST when conflicted');
  } finally {
    globalThis.fetch = originalFetch;
  }
  console.log('PASS handler returns 409 on active conflict and does not write');
});

// ③ 速率限制:每实例窗口内第 7 次拒绝;窗口滑走后恢复
{
  const t0 = Date.now() + 10 * 24 * 3600 * 1000;   // 远未来,清空历史窗口
  for (let i = 0; i < 6; i += 1) {
    assert.equal(rateLimited(t0 + i), false, `post ${i + 1} should pass`);
  }
  assert.equal(rateLimited(t0 + 6), true, '7th post within window must be limited');
  assert.equal(rateLimited(t0 + 11 * 60 * 1000), false, 'after window slides, posts resume');
  console.log('PASS per-instance rate limit (6/10min, best-effort by design)');
}

console.log('ALL TEAM PROGRESS EVENT API TESTS PASS (0 real network calls)');
