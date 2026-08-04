import assert from 'node:assert/strict';

import handler, { buildProgressEvent, formatComment } from '../api/team-progress-event.js';

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
await testValidPostWritesStandardComment();
await testValidationRejectsUnsafeFilesBeforeWrite();
testCommentFormat();

console.log('ALL TEAM PROGRESS EVENT API TESTS PASS (0 real network calls)');
