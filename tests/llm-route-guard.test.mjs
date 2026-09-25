// Offline regression for the paid-model route gate (api/_lib/llm-route-guard.js)
// and its browser client (src/llmRouteClient.js). No network: global fetch and
// the Anthropic SDK are replaced by counters that throw if reached.
//
//   node tests/llm-route-guard.test.mjs
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const SDK_STUB = `
export default class Anthropic {
  constructor() {
    this.messages = {
      create: async () => {
        globalThis.__llmProviderCalls = (globalThis.__llmProviderCalls || 0) + 1;
        throw new Error('provider SDK must not be reached in the route-gate test');
      },
      stream: () => {
        globalThis.__llmProviderCalls = (globalThis.__llmProviderCalls || 0) + 1;
        throw new Error('provider SDK must not be reached in the route-gate test');
      },
    };
  }
}`;
const HOOKS = `
export async function resolve(specifier, context, nextResolve) {
  if (specifier === '@anthropic-ai/sdk') {
    return { url: 'data:text/javascript,' + encodeURIComponent(${JSON.stringify(SDK_STUB)}), shortCircuit: true };
  }
  return nextResolve(specifier, context);
}`;
register('data:text/javascript,' + encodeURIComponent(HOOKS));

globalThis.__llmProviderCalls = 0;
let fetchCalls = 0;
globalThis.fetch = async (url) => {
  fetchCalls += 1;
  throw new Error(`network is forbidden in the route-gate test: ${url}`);
};

const guard = await import(pathToFileURL(path.join(ROOT, 'api/_lib/llm-route-guard.js')).href);
const client = await import(pathToFileURL(path.join(ROOT, 'src/llmRouteClient.js')).href);

const GOOD_KEY = 'offline-llm-route-key-0123456789abcdef';
const ROUTES = ['research-multi', 'research', 'chat', 'debate', 'macro', 'morning-report', 'research-pulse'];

function makeResponse() {
  return {
    code: null, headers: {}, body: null, ended: false,
    setHeader(name, value) { this.headers[name.toLowerCase()] = value; },
    status(code) { this.code = code; return this; },
    json(payload) { this.body = payload; return this; },
    end() { this.ended = true; return this; },
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
    return await fn();
  } finally {
    for (const key of Object.keys(values)) {
      if (previous[key] === undefined) delete process.env[key];
      else process.env[key] = previous[key];
    }
  }
}

function counters() {
  return { provider: globalThis.__llmProviderCalls, fetch: fetchCalls };
}

// ── guard unit behaviour ────────────────────────────────────────────────────
function testTimingSafeEqual() {
  assert.equal(guard.timingSafeEqualString(GOOD_KEY, GOOD_KEY), true);
  assert.equal(guard.timingSafeEqualString(GOOD_KEY, `${GOOD_KEY}x`), false);
  assert.equal(guard.timingSafeEqualString('', GOOD_KEY), false);
  assert.equal(guard.timingSafeEqualString(undefined, GOOD_KEY), false);
  assert.equal(guard.timingSafeEqualString(GOOD_KEY, undefined), false);
  const source = readFileSync(path.join(ROOT, 'api/_lib/llm-route-guard.js'), 'utf8');
  assert.match(source, /timingSafeEqual\(digestA, digestB\)/, 'key compare must stay constant-time');
}

function runGuard({ method = 'POST', origin, key, env = { AR_LLM_ROUTE_KEY: GOOD_KEY }, route = 'research', ip = '203.0.113.7', now } = {}) {
  const headers = { 'x-real-ip': ip };
  if (origin !== undefined) headers.origin = origin;
  if (key !== undefined) headers['x-ar-llm-key'] = key;
  const res = makeResponse();
  const ok = guard.guardLlmRoute({ method, headers }, res, route, { env, now: now ?? Date.now() });
  return { ok, res };
}

function testGuardOrderAndStatuses() {
  guard.resetRateLimits();
  // Fail closed: no server key configured.
  let r = runGuard({ key: GOOD_KEY, env: {} });
  assert.equal(r.ok, false); assert.equal(r.res.code, 503);
  assert.equal(r.res.body.code, 'LLM_ROUTE_KEY_NOT_CONFIGURED');
  // Too-short server key is treated as unconfigured.
  r = runGuard({ key: 'short', env: { AR_LLM_ROUTE_KEY: 'short' } });
  assert.equal(r.res.code, 503);
  // Missing / wrong client key.
  r = runGuard({});
  assert.equal(r.res.code, 401); assert.equal(r.res.body.code, 'LLM_ROUTE_UNAUTHORIZED');
  r = runGuard({ key: `${GOOD_KEY}-wrong` });
  assert.equal(r.res.code, 401);
  // Forbidden Origin is refused even with the right key.
  r = runGuard({ key: GOOD_KEY, origin: 'https://evil.example' });
  assert.equal(r.res.code, 403); assert.equal(r.res.headers['access-control-allow-origin'], undefined);
  r = runGuard({ key: GOOD_KEY, origin: 'null' });
  assert.equal(r.res.code, 403);
  // Non-POST.
  r = runGuard({ key: GOOD_KEY, method: 'GET' });
  assert.equal(r.res.code, 405);
  // Allowed Origin + key passes, and CORS echoes the exact origin (never '*').
  r = runGuard({ key: GOOD_KEY, origin: 'https://lateily.github.io' });
  assert.equal(r.ok, true);
  assert.equal(r.res.headers['access-control-allow-origin'], 'https://lateily.github.io');
  assert.match(r.res.headers['access-control-allow-headers'], /X-AR-LLM-Key/);
  // Server-to-server (no Origin) + key passes.
  r = runGuard({ key: GOOD_KEY });
  assert.equal(r.ok, true);
  // Preflight.
  r = runGuard({ method: 'OPTIONS', origin: 'https://equity-research-ten.vercel.app' });
  assert.equal(r.ok, false); assert.equal(r.res.code, 204);
  r = runGuard({ method: 'OPTIONS', origin: 'https://evil.example' });
  assert.equal(r.res.code, 403);
  // Configured extra origins; '*' can never be configured in.
  const env = { AR_LLM_ROUTE_KEY: GOOD_KEY, AR_LLM_ALLOWED_ORIGINS: 'http://localhost:5173, *' };
  assert.equal(runGuard({ key: GOOD_KEY, origin: 'http://localhost:5173', env }).ok, true);
  assert.equal(runGuard({ key: GOOD_KEY, origin: 'https://evil.example', env }).res.code, 403);
  assert.ok(!guard.allowedOrigins(env).includes('*'));
}

function testRateLimit() {
  guard.resetRateLimits();
  const now = 1_800_000_000_000;
  const limit = guard.RATE_LIMITS['research-multi'];
  for (let i = 0; i < limit; i += 1) {
    assert.equal(runGuard({ key: GOOD_KEY, route: 'research-multi', now: now + i }).ok, true);
  }
  const limited = runGuard({ key: GOOD_KEY, route: 'research-multi', now: now + limit });
  assert.equal(limited.ok, false);
  assert.equal(limited.res.code, 429);
  assert.ok(Number(limited.res.headers['retry-after']) > 0);
  // Another IP has its own bucket; the window expires.
  assert.equal(runGuard({ key: GOOD_KEY, route: 'research-multi', ip: '198.51.100.9', now: now + limit }).ok, true);
  assert.equal(runGuard({ key: GOOD_KEY, route: 'research-multi', now: now + guard.RATE_WINDOW_MS + 1 }).ok, true);
  // Unauthenticated calls never consume the bucket.
  guard.resetRateLimits();
  for (let i = 0; i < 10; i += 1) runGuard({ route: 'research-multi', now });
  assert.equal(runGuard({ key: GOOD_KEY, route: 'research-multi', now }).ok, true);
  guard.resetRateLimits();
}

// ── every paid-model handler is gated before any provider call ───────────────
async function testEveryHandlerRejectsBeforeProvider() {
  for (const route of ROUTES) {
    const { default: handler } = await import(pathToFileURL(path.join(ROOT, `api/${route}.js`)).href);
    const body = { ticker: '600519.SH', regime_data: { sectors: [] }, article: { title: 't' }, text: 't' };
    const cases = [
      { env: { AR_LLM_ROUTE_KEY: undefined }, headers: { 'x-ar-llm-key': GOOD_KEY }, code: 503 },
      { env: { AR_LLM_ROUTE_KEY: GOOD_KEY }, headers: {}, code: 401 },
      { env: { AR_LLM_ROUTE_KEY: GOOD_KEY }, headers: { 'x-ar-llm-key': 'wrong-key-wrong-key-wrong-key-wrong' }, code: 401 },
      { env: { AR_LLM_ROUTE_KEY: GOOD_KEY }, headers: { 'x-ar-llm-key': GOOD_KEY, origin: 'https://evil.example' }, code: 403 },
    ];
    for (const item of cases) {
      const before = counters();
      const res = makeResponse();
      await withEnv({ ...item.env, ANTHROPIC_API_KEY: 'offline', OPENAI_API_KEY: 'offline', GOOGLE_AI_API_KEY: 'offline' },
        () => handler({ method: 'POST', headers: item.headers, body }, res));
      assert.equal(res.code, item.code, `${route}: expected ${item.code}, got ${res.code}`);
      assert.deepEqual(counters(), before, `${route}: a provider/network call happened before the gate rejected`);
      assert.notEqual(res.headers['access-control-allow-origin'], '*', `${route}: wildcard CORS is back`);
    }
    const preflight = makeResponse();
    await handler({ method: 'OPTIONS', headers: { origin: 'https://evil.example' } }, preflight);
    assert.equal(preflight.code, 403, `${route}: foreign preflight must be refused`);
  }
}

function testNoWildcardCorsOnPaidRoutes() {
  for (const route of ROUTES) {
    const source = readFileSync(path.join(ROOT, `api/${route}.js`), 'utf8');
    assert.doesNotMatch(source, /Access-Control-Allow-Origin['"]\s*,\s*['"]\*/, `${route}.js sets wildcard CORS`);
    assert.match(source, new RegExp(`guardLlmRoute\\(req, res, '${route}'\\)`), `${route}.js lost its gate`);
  }
}

// ── browser client ───────────────────────────────────────────────────────────
async function testBrowserClientLockedByDefault() {
  let calls = 0;
  const fetchImpl = async (_url, init) => { calls += 1; return { status: 200, init }; };
  client.configureLlmRoutes({ browserEnabled: undefined });
  assert.equal(client.setOperatorLlmKey(GOOD_KEY), false, 'flag off must refuse to hold a key');
  await assert.rejects(client.llmRouteFetch('/api/research', { method: 'POST' }, { fetchImpl }), /disabled in this build/);
  client.configureLlmRoutes({ browserEnabled: '1' });
  await assert.rejects(client.llmRouteFetch('/api/research', { method: 'POST' }, { fetchImpl }), /operator key/);
  assert.equal(calls, 0, 'a locked client must not touch the network');

  assert.equal(client.setOperatorLlmKey(`  ${GOOD_KEY}\n`), true);
  const ok = await client.llmRouteFetch('/api/research', { method: 'POST', headers: { 'Content-Type': 'application/json' } }, { fetchImpl });
  assert.equal(calls, 1);
  assert.equal(ok.init.headers['X-AR-LLM-Key'], GOOD_KEY);
  assert.equal(ok.init.headers['Content-Type'], 'application/json');

  // A 401 forgets the key.
  await client.llmRouteFetch('/api/chat', {}, { fetchImpl: async () => ({ status: 401 }) });
  assert.equal(client.hasOperatorLlmKey(), false);
  client.configureLlmRoutes({ browserEnabled: '0' });
}

function testBrowserBundleNeverCarriesTheKey() {
  const dashboard = readFileSync(path.join(ROOT, 'src/Dashboard.jsx'), 'utf8');
  const clientSource = readFileSync(path.join(ROOT, 'src/llmRouteClient.js'), 'utf8');
  for (const source of [dashboard, clientSource]) {
    assert.doesNotMatch(source, /AR_LLM_ROUTE_KEY/, 'the server key env name must not appear in browser code');
    assert.doesNotMatch(source, /VITE_[A-Z_]*KEY/, 'no VITE_*KEY build variable may carry a secret');
    assert.doesNotMatch(source, /(localStorage|sessionStorage)\.setItem\([^)]*(llm|LLM)[^)]*[Kk]ey/, 'operator key must not be persisted');
  }
  // Every paid-model call in the dashboard goes through the locked client.
  const rawCalls = dashboard.match(/(?<![A-Za-z])fetch\([^)]*\/api\/(research-multi|research-pulse|research|chat|translate|debate|macro|morning-report)\b/g) || [];
  assert.deepEqual(rawCalls, [], `raw fetch() to a paid-model route: ${rawCalls.join(' | ')}`);
  assert.doesNotMatch(dashboard, /(?<![A-Za-z])fetch\(endpoint\b/, 'research endpoint must use llmRouteFetch');
  const gated = dashboard.match(/llmRouteFetch\(/g) || [];
  assert.ok(gated.length >= 11, `expected >=11 gated call sites, found ${gated.length}`);
  for (const route of client.LLM_ROUTE_PATHS) assert.ok(client.isLlmRoutePath(`https://x.example${route}?a=1`));
  assert.equal(client.isLlmRoutePath('/api/news'), false);
}

testTimingSafeEqual();
testGuardOrderAndStatuses();
testRateLimit();
await testEveryHandlerRejectsBeforeProvider();
testNoWildcardCorsOnPaidRoutes();
await testBrowserClientLockedByDefault();
testBrowserBundleNeverCarriesTheKey();
assert.equal(globalThis.__llmProviderCalls, 0);
assert.equal(fetchCalls, 0);

console.log('ALL LLM ROUTE GUARD TESTS PASS');
