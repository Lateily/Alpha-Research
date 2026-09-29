// api/_lib/llm-route-guard.js — shared gate for every paid-model route.
//
// The `_lib` underscore prefix keeps Vercel from deploying this file as its own
// function. Every handler that calls Anthropic / OpenAI / Gemini must call
// guardLlmRoute() as its first statement, before reading the body or touching a
// provider SDK / fetch.
//
// Order: CORS allowlist headers -> OPTIONS preflight (204 / 403)
//        -> forbidden Origin (403) -> non-POST (405)
//        -> the caller class's key is configured, >= 32 chars, not
//           whitespace-padded, and (browser) differs from the server key
//           (503, fail closed)
//        -> X-AR-LLM-Key constant-time match (401)
//        -> per-IP rate limit (429).
// Every rejection happens before any provider call.
//
// Two keys, one per caller class, so each can be rotated on its own:
//   - AR_LLM_ROUTE_KEY: server-to-server callers (no Origin header): the
//     morning-report workflow (GitHub Actions secret) and scripts/run_research.py.
//   - AR_LLM_BROWSER_ROUTE_KEY: requests that carry an allow-listed Origin, i.e.
//     the dashboard with VITE_AR_LLM_BROWSER_ROUTES=1 and the operator typing the
//     key into the tab. Unset = browser calls fail closed (503). It must differ
//     from AR_LLM_ROUTE_KEY, so a key exposed in a browser tab never unlocks the
//     automation path.
// Neither key is ever bundled into the browser build. The Origin allowlist is
// defence in depth against drive-by browser use only; a non-browser client can
// forge Origin, so the keys are the actual control.
import { createHash, timingSafeEqual } from 'node:crypto';

export const LLM_KEY_HEADER = 'x-ar-llm-key';
export const LLM_KEY_ENV = 'AR_LLM_ROUTE_KEY';
export const LLM_BROWSER_KEY_ENV = 'AR_LLM_BROWSER_ROUTE_KEY';
export const LLM_ORIGINS_ENV = 'AR_LLM_ALLOWED_ORIGINS';
export const MIN_KEY_LENGTH = 32;

export const DEFAULT_ALLOWED_ORIGINS = Object.freeze([
  'https://equity-research-ten.vercel.app',
  'https://lateily.github.io',
]);

// Best-effort per-instance limit, same honest caveat as api/team-progress-event.js:
// serverless instances do not share memory, so this bounds spend per warm
// instance only. A durable limit needs Vercel Firewall rules or a shared store.
export const RATE_WINDOW_MS = 10 * 60 * 1000;
export const RATE_LIMITS = Object.freeze({
  'research-multi': 3,
  research: 10,
  debate: 10,
  'morning-report': 5,
  'research-pulse': 30,
  macro: 20,
  chat: 60,
});
const DEFAULT_RATE_LIMIT = 10;
const MAX_TRACKED_KEYS = 5000;
const rateLog = new Map();

function headerValue(req, name) {
  const headers = req?.headers || {};
  const value = headers[name] ?? headers[name.toLowerCase()];
  return Array.isArray(value) ? value[0] : value;
}

export function allowedOrigins(env = process.env) {
  const configured = String(env[LLM_ORIGINS_ENV] || '')
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item && item !== '*' && item !== 'null');
  return [...DEFAULT_ALLOWED_ORIGINS, ...configured];
}

// Constant-time compare (same intent as api/team-progress-event.js). Hashing both
// sides first gives equal-length buffers, so unequal lengths cost the same as
// unequal content; the length check afterwards only runs on a digest match.
export function timingSafeEqualString(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  const digestA = createHash('sha256').update(a, 'utf8').digest();
  const digestB = createHash('sha256').update(b, 'utf8').digest();
  // governance-mutation: LLM_ROUTE_CONSTANT_TIME_COMPARE
  return timingSafeEqual(digestA, digestB) && a.length === b.length;
}

// A configured key is usable only if it is a string of at least MIN_KEY_LENGTH
// with no surrounding whitespace. A value pasted with a trailing newline (common
// with `vercel env add` from a pipe) can never equal an HTTP header value, since
// every caller trims what it sends; treating it as unconfigured turns a silent,
// permanent 401 into an explicit 503 LLM_ROUTE_KEY_NOT_CONFIGURED.
export function usableConfiguredKey(value) {
  // governance-mutation: LLM_ROUTE_FAILS_CLOSED_WITHOUT_SERVER_KEY
  if (typeof value !== 'string' || value.length < MIN_KEY_LENGTH) return null;
  // governance-mutation: LLM_ROUTE_KEY_WHITESPACE_FAILS_CLOSED
  if (value !== value.trim()) return null;
  return value;
}

// Vercel overwrites x-real-ip / x-forwarded-for at its edge, so a caller cannot
// pick its own bucket there. Off Vercel the value is whatever the proxy sets.
export function clientIp(req) {
  const real = headerValue(req, 'x-real-ip');
  if (real) return String(real).trim();
  const forwarded = headerValue(req, 'x-forwarded-for');
  if (forwarded) return String(forwarded).split(',')[0].trim();
  return req?.socket?.remoteAddress || 'unknown';
}

// Returns 0 when the call may proceed, else the Retry-After seconds.
export function rateLimited(route, ip, now = Date.now()) {
  const limit = RATE_LIMITS[route] ?? DEFAULT_RATE_LIMIT;
  const key = `${route}|${ip}`;
  const hits = (rateLog.get(key) || []).filter((t) => now - t < RATE_WINDOW_MS);
  if (hits.length >= limit) {
    rateLog.set(key, hits);
    return Math.max(1, Math.ceil((RATE_WINDOW_MS - (now - hits[0])) / 1000));
  }
  hits.push(now);
  rateLog.delete(key);
  rateLog.set(key, hits);
  while (rateLog.size > MAX_TRACKED_KEYS) rateLog.delete(rateLog.keys().next().value);
  return 0;
}

export function resetRateLimits() {
  rateLog.clear();
}

function reject(res, status, code, error) {
  res.setHeader('Cache-Control', 'no-store');
  res.status(status).json({ error, code });
  return false;
}

// Returns true when the handler may continue; otherwise it has already responded.
export function guardLlmRoute(req, res, route, { env = process.env, now = Date.now() } = {}) {
  const origin = headerValue(req, 'origin');
  const originAllowed = typeof origin === 'string' && allowedOrigins(env).includes(origin);
  res.setHeader('Vary', 'Origin');
  if (originAllowed) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-AR-LLM-Key');
    res.setHeader('Access-Control-Max-Age', '600');
  }

  if (req?.method === 'OPTIONS') {
    if (!originAllowed) return reject(res, 403, 'LLM_ORIGIN_FORBIDDEN', 'Origin not allowed.');
    res.status(204).end();
    return false;
  }

  // No Origin header = server-to-server caller (GitHub Actions, scripts); the key decides.
  // governance-mutation: LLM_ROUTE_ORIGIN_ALLOWLIST
  if (origin !== undefined && !originAllowed) {
    return reject(res, 403, 'LLM_ORIGIN_FORBIDDEN', 'Origin not allowed.');
  }

  if (req?.method !== 'POST') {
    return reject(res, 405, 'LLM_METHOD_NOT_ALLOWED', 'Method not allowed');
  }

  // Origin-bearing (browser) requests are checked against the browser key only;
  // server-to-server requests against the server key only.
  const browserCaller = origin !== undefined;
  // governance-mutation: LLM_ROUTE_BROWSER_KEY_SEPARATE
  const keyEnv = browserCaller ? LLM_BROWSER_KEY_ENV : LLM_KEY_ENV;

  // Fail closed: a missing, short or whitespace-padded key disables that path.
  const configuredKey = usableConfiguredKey(env[keyEnv]);
  if (configuredKey === null) {
    return reject(res, 503, 'LLM_ROUTE_KEY_NOT_CONFIGURED',
      `${keyEnv} is not configured (missing, shorter than ${MIN_KEY_LENGTH} chars, or has surrounding whitespace).`);
  }
  // governance-mutation: LLM_ROUTE_BROWSER_KEY_MUST_DIFFER
  if (browserCaller && configuredKey === usableConfiguredKey(env[LLM_KEY_ENV])) {
    return reject(res, 503, 'LLM_BROWSER_KEY_NOT_SEPARATE',
      `${LLM_BROWSER_KEY_ENV} must differ from ${LLM_KEY_ENV}.`);
  }

  const providedKey = headerValue(req, LLM_KEY_HEADER);
  // governance-mutation: LLM_ROUTE_REQUIRES_KEY_MATCH
  if (!timingSafeEqualString(typeof providedKey === 'string' ? providedKey : '', configuredKey)) {
    return reject(res, 401, 'LLM_ROUTE_UNAUTHORIZED', 'Missing or invalid X-AR-LLM-Key.');
  }

  const retryAfter = rateLimited(route, clientIp(req), now);
  // governance-mutation: LLM_ROUTE_RATE_LIMIT
  if (retryAfter) {
    res.setHeader('Retry-After', String(retryAfter));
    return reject(res, 429, 'LLM_ROUTE_RATE_LIMITED', 'Rate limited for this route. Retry later.');
  }
  return true;
}
