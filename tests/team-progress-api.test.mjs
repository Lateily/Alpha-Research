import assert from 'node:assert/strict';

import handler from '../api/team-progress.js';

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

function progressComment(event) {
  return {
    body: `<!-- ai-progress:v2 -->\n\`\`\`json\n${JSON.stringify(event, null, 2)}\n\`\`\``,
  };
}

async function testReadOnlySnapshot() {
  const originalFetch = globalThis.fetch;
  const originalToken = process.env.GITHUB_TOKEN;
  const originalProgressToken = process.env.PROGRESS_GITHUB_TOKEN;
  const calls = [];

  delete process.env.GITHUB_TOKEN;
  delete process.env.PROGRESS_GITHUB_TOKEN;

  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      status: 200,
      statusText: 'OK',
      async json() {
        return [
          progressComment({
            schema: 'ai-progress.v2',
            event: 'CLAIM',
            task: '#demo',
            human_owner: 'Tianrui',
            executor: 'Codex',
            reviewer: 'Junyan',
            status: 'in_progress',
            summary: 'Build a shared read-only progress board.',
            branch: 'feat/demo',
            files: ['api', 'docs/llm'],
            timestamp_utc: '2026-07-31T00:00:00+00:00',
            expires_at: '2099-01-01T00:00:00+00:00',
          }),
          progressComment({
            schema: 'ai-progress.v2',
            event: 'DONE',
            task: '#old',
            human_owner: 'Tianrui',
            executor: 'Codex',
            reviewer: 'Junyan',
            status: 'done',
            summary: 'Old task completed.',
            timestamp_utc: '2026-07-30T00:00:00+00:00',
          }),
          { body: '```json\n{\"event\":\"NOT_A_PROGRESS_EVENT\"}\n```' },
        ];
      },
    };
  };

  try {
    const req = { method: 'GET', headers: { origin: 'http://localhost:5173' } };
    const res = makeResponse();
    await handler(req, res);

    assert.equal(res.code, 200);
    assert.equal(res.headers['X-Progress-Board-Readonly'], 'true');
    assert.equal(res.headers['Access-Control-Allow-Origin'], 'http://localhost:5173');
    assert.equal(calls.length, 1);
    assert.equal(calls[0].options.headers.Authorization, undefined);
    assert.equal(res.body.schema, 'ai-progress.snapshot.v1');
    assert.equal(res.body.contract_version, '1.5');
    assert.equal(res.body.ok, true);
    assert.equal(res.body.summary.events, 2);
    assert.equal(res.body.summary.active_claims, 1);
    assert.equal(res.body.summary.done, 1);
    assert.equal(res.body.active_claims[0].task, '#demo');
    assert.equal(res.body.timeline.length, 2);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalToken === undefined) delete process.env.GITHUB_TOKEN;
    else process.env.GITHUB_TOKEN = originalToken;
    if (originalProgressToken === undefined) delete process.env.PROGRESS_GITHUB_TOKEN;
    else process.env.PROGRESS_GITHUB_TOKEN = originalProgressToken;
  }
}

async function testOptionsIsReadOnly() {
  const req = { method: 'OPTIONS', headers: { origin: 'http://localhost:5173' } };
  const res = makeResponse();
  await handler(req, res);

  assert.equal(res.code, 200);
  assert.equal(res.ended, true);
  assert.equal(res.headers['Access-Control-Allow-Methods'], 'GET, OPTIONS');
}

await testReadOnlySnapshot();
await testOptionsIsReadOnly();
console.log('ALL TEAM PROGRESS API TESTS PASS (0 network calls)');
