import assert from 'node:assert/strict';

import {
  DEFAULT_PROGRESS_API_ORIGIN,
  normalizeProgressWriteKey,
  parseProgressApiPayload,
  resolveProgressApiBase,
} from '../src/progressBoardClient.js';

assert.equal(resolveProgressApiBase({ hostname: 'equity-research-ten.vercel.app' }), '');
assert.equal(resolveProgressApiBase({ hostname: 'lateily.github.io' }), DEFAULT_PROGRESS_API_ORIGIN);
assert.equal(
  resolveProgressApiBase({ configuredBase: ' https://example.test/ ', hostname: 'lateily.github.io' }),
  'https://example.test'
);
assert.equal(normalizeProgressWriteKey('  secret-key\r\n'), 'secret-key');
assert.deepEqual(
  parseProgressApiPayload({ status: 200, contentType: 'application/json', body: '{"ok":true}' }),
  { ok: true }
);
assert.throws(
  () => parseProgressApiPayload({
    status: 401,
    contentType: 'text/html',
    body: '<html><title>Protected Deployment</title></html>',
  }),
  /deployment protection/i
);
assert.throws(
  () => parseProgressApiPayload({ status: 502, contentType: 'text/plain', body: 'gateway error' }),
  /non-JSON HTTP 502/
);

console.log('ALL TEAM PROGRESS CLIENT TESTS PASS');
