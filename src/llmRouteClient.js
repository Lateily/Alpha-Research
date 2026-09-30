// src/llmRouteClient.js — browser side of the paid-model route gate.
//
// The dashboard used to POST anonymously to /api/research, /api/research-multi,
// /api/chat (+ /api/translate), /api/debate, /api/macro, /api/morning-report and
// /api/research-pulse. Those routes now require the header X-AR-LLM-Key (see
// api/_lib/llm-route-guard.js). Browser requests carry an Origin, so the server
// checks them against its separate browser route key, never the automation key.
//
// The key is NEVER part of the build: there is no VITE_* variable for it and
// nothing here reads one. Browser LLM calls are OFF unless BOTH hold:
//   1. the build sets VITE_AR_LLM_BROWSER_ROUTES=1 (feature flag, default off), and
//   2. the operator types the key into the dashboard at runtime for this tab.
// The typed key lives only in this module's memory (not localStorage /
// sessionStorage), mirroring the progress board's write-key field; a reload
// forgets it. With either condition missing, llmRouteFetch() rejects with
// LlmRouteLockedError and makes NO network request, so a public visitor's page
// load never spends the owner's model budget.

export const LLM_KEY_HEADER = 'X-AR-LLM-Key';
export const LLM_BROWSER_FLAG = 'VITE_AR_LLM_BROWSER_ROUTES';
export const LLM_ROUTE_PATHS = Object.freeze([
  '/api/research-multi',
  '/api/research-pulse',
  '/api/research',
  '/api/chat',
  '/api/translate',
  '/api/debate',
  '/api/macro',
  '/api/morning-report',
]);

export class LlmRouteLockedError extends Error {
  constructor(reason) {
    super(reason === 'FLAG_OFF'
      ? 'LLM routes are disabled in this build (VITE_AR_LLM_BROWSER_ROUTES is not 1).'
      : 'LLM route locked: enter the operator key for this tab first.');
    this.name = 'LlmRouteLockedError';
    this.code = reason === 'FLAG_OFF' ? 'LLM_BROWSER_ROUTES_DISABLED' : 'LLM_ROUTE_KEY_MISSING';
  }
}

let browserRoutesEnabled = false;
let operatorKey = '';
const keyListeners = new Set();

// Lets the header control re-render when the key changes outside it (a 401
// clears it inside llmRouteFetch). Returns an unsubscribe function.
export function subscribeOperatorLlmKey(listener) {
  keyListeners.add(listener);
  return () => { keyListeners.delete(listener); };
}

function notifyKeyListeners() {
  const state = hasOperatorLlmKey();
  for (const listener of [...keyListeners]) {
    try { listener(state); } catch { /* a broken listener must not break the fetch path */ }
  }
}

export function isBrowserFlagOn(value) {
  return String(value ?? '').trim() === '1';
}

export function configureLlmRoutes({ browserEnabled } = {}) {
  browserRoutesEnabled = isBrowserFlagOn(browserEnabled);
  if (!browserRoutesEnabled) operatorKey = '';
  notifyKeyListeners();
  return browserRoutesEnabled;
}

export function llmBrowserRoutesEnabled() {
  return browserRoutesEnabled;
}

export function normalizeLlmRouteKey(value) {
  return String(value ?? '').trim();
}

export function setOperatorLlmKey(value) {
  operatorKey = browserRoutesEnabled ? normalizeLlmRouteKey(value) : '';
  notifyKeyListeners();
  return operatorKey.length > 0;
}

export function clearOperatorLlmKey() {
  operatorKey = '';
  notifyKeyListeners();
}

export function hasOperatorLlmKey() {
  return browserRoutesEnabled && operatorKey.length > 0;
}

export function isLlmRoutePath(url) {
  const path = String(url ?? '').replace(/^https?:\/\/[^/]+/i, '').split(/[?#]/)[0];
  return LLM_ROUTE_PATHS.includes(path);
}

// Drop-in replacement for fetch() on the paid-model routes. Rejects without any
// network I/O while locked; otherwise adds the operator key header.
export async function llmRouteFetch(url, init = {}, { fetchImpl } = {}) {
  // governance-mutation: LLM_BROWSER_LOCKED_WITHOUT_KEY
  if (!browserRoutesEnabled) throw new LlmRouteLockedError('FLAG_OFF');
  if (!operatorKey) throw new LlmRouteLockedError('KEY_MISSING');
  const doFetch = fetchImpl || globalThis.fetch;
  const headers = { ...(init.headers || {}), [LLM_KEY_HEADER]: operatorKey };
  const response = await doFetch(url, { ...init, headers });
  // A rejected key is useless for the rest of the session: forget it so the
  // operator is asked again instead of retrying a bad key on every poll.
  if (response && response.status === 401) {
    operatorKey = '';
    notifyKeyListeners();
  }
  return response;
}

export function describeLlmRouteError(err) {
  if (err instanceof LlmRouteLockedError) return err.message;
  return err?.message || String(err);
}
