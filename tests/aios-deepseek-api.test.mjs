import assert from 'node:assert/strict';

import handler, {
  dryRunResponse,
  estimateCostCny,
  normalizeRequest,
  requireLiveAccess,
} from '../api/aios-deepseek.js';

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

function testNormalizeRequestDefaultsToDryRun() {
  const request = normalizeRequest({ prompt: 'Summarize this event packet.' });

  assert.equal(request.model, 'deepseek-v4-flash');
  assert.equal(request.mode, 'dry_run');
  assert.equal(request.thinking, 'disabled');
  assert.equal(request.maxTokens, 512);
}

function testRejectsOversizedPrompt() {
  assert.throws(
    () => normalizeRequest({ prompt: 'x'.repeat(6001) }),
    /prompt is too long/
  );
}

function testDryRunNeverNeedsKeys() {
  const payload = dryRunResponse(normalizeRequest({ prompt: 'hello' }));

  assert.equal(payload.ok, true);
  assert.equal(payload.mode, 'dry_run');
  assert.equal(payload.provider, 'deepseek');
  assert.equal(payload.usage.estimated_cost_cny, '0.000000');
  assert.equal(payload.output.no_trade_flag, true);
  assert.match(payload.input_hash, /^sha256:/);
  assert.doesNotMatch(JSON.stringify(payload), /hello/);
}

function testCostEstimate() {
  assert.equal(
    estimateCostCny('deepseek-v4-flash', {
      prompt_tokens: 100,
      prompt_cache_hit_tokens: 20,
      prompt_cache_miss_tokens: 80,
      completion_tokens: 10,
    }),
    '0.000101'
  );
}

async function testLiveModeRequiresRunKeyBeforeProviderKey() {
  await withEnv(
    {
      AIOS_DEEPSEEK_RUN_KEY: undefined,
      DEEPSEEK_API_KEY: undefined,
    },
    async () => {
      const access = requireLiveAccess({ headers: {} });
      assert.equal(access.ok, false);
      assert.equal(access.code, 503);
      assert.match(access.error, /AIOS_DEEPSEEK_RUN_KEY/);
    }
  );
}

async function testHandlerDryRunDoesNotCallFetch() {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new Error('fetch should not be called in dry-run');
  };

  try {
    const req = { method: 'POST', headers: {}, body: { prompt: 'dry run packet' } };
    const res = makeResponse();
    await handler(req, res);

    assert.equal(res.code, 200);
    assert.equal(res.body.ok, true);
    assert.equal(res.body.mode, 'dry_run');
    assert.equal(calls, 0);
    assert.equal(res.headers['X-AIOS-Key-Boundary'], 'server-only');
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function testHandlerLiveRejectsWrongKeyBeforeFetch() {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new Error('fetch should not be called with bad run key');
  };

  try {
    await withEnv(
      {
        AIOS_DEEPSEEK_RUN_KEY: 'expected',
        DEEPSEEK_API_KEY: 'provider-secret',
      },
      async () => {
        const req = {
          method: 'POST',
          headers: { 'x-aios-run-key': 'wrong' },
          body: { mode: 'live', prompt: 'live packet' },
        };
        const res = makeResponse();
        await handler(req, res);

        assert.equal(res.code, 401);
        assert.equal(res.body.ok, false);
        assert.equal(calls, 0);
        assert.doesNotMatch(JSON.stringify(res.body), /provider-secret/);
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function testHandlerLiveRequiresReportedUsage() {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    async json() {
      return { choices: [{ message: { content: 'missing usage' } }] };
    },
  });

  try {
    await withEnv(
      {
        AIOS_DEEPSEEK_RUN_KEY: 'expected',
        DEEPSEEK_API_KEY: 'provider-secret',
      },
      async () => {
        const req = {
          method: 'POST',
          headers: { 'x-aios-run-key': 'expected' },
          body: { mode: 'live', prompt: 'live packet' },
        };
        const res = makeResponse();
        await handler(req, res);

        assert.equal(res.code, 400);
        assert.match(res.body.error, /usage/);
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function testHandlerLiveSuccessReportsCost() {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          model: 'deepseek-v4-flash',
          choices: [{ message: { content: 'structured backend result' }, finish_reason: 'stop' }],
          usage: {
            prompt_tokens: 100,
            prompt_cache_hit_tokens: 20,
            prompt_cache_miss_tokens: 80,
            completion_tokens: 10,
          },
        };
      },
    };
  };

  try {
    await withEnv(
      {
        AIOS_DEEPSEEK_RUN_KEY: 'expected',
        DEEPSEEK_API_KEY: 'provider-secret',
      },
      async () => {
        const req = {
          method: 'POST',
          headers: { 'x-aios-run-key': 'expected' },
          body: { mode: 'live', prompt: 'live packet' },
        };
        const res = makeResponse();
        await handler(req, res);

        assert.equal(res.code, 200);
        assert.equal(res.body.ok, true);
        assert.equal(res.body.mode, 'live');
        assert.equal(res.body.usage.status, 'REPORTED');
        assert.equal(res.body.usage.estimated_cost_cny, '0.000101');
        assert.equal(res.body.output.no_trade_flag, true);
        assert.equal(calls.length, 1);
        assert.equal(calls[0].url, 'https://api.deepseek.com/chat/completions');
        assert.equal(calls[0].options.headers.Authorization, 'Bearer provider-secret');
        assert.doesNotMatch(JSON.stringify(res.body), /provider-secret|live packet/);
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
}

testNormalizeRequestDefaultsToDryRun();
testRejectsOversizedPrompt();
testDryRunNeverNeedsKeys();
testCostEstimate();
await testLiveModeRequiresRunKeyBeforeProviderKey();
await testHandlerDryRunDoesNotCallFetch();
await testHandlerLiveRejectsWrongKeyBeforeFetch();
await testHandlerLiveRequiresReportedUsage();
await testHandlerLiveSuccessReportsCost();

console.log('ALL AIOS DEEPSEEK API TESTS PASS (0 real network calls)');
