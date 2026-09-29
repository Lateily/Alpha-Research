#!/usr/bin/env python3
"""Offline pins for the paid-model route gate.

The seven Vercel routes that spend the owner's Anthropic / OpenAI / Gemini keys
(api/research-multi.js, research.js, chat.js, debate.js, macro.js,
morning-report.js, research-pulse.js) must reject a request before any
provider call unless it carries the server key, comes from an allowed Origin
(or no Origin, i.e. server-to-server) and stays under the per-IP rate limit.
The key must never reach the browser bundle; in-repo server-side callers send
it from the environment only.

No network: node runners replace global fetch and the Anthropic SDK with
counters that throw if reached; the Python caller test stubs urlopen.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "api" / "_lib" / "llm-route-guard.js"
CLIENT_PATH = ROOT / "src" / "llmRouteClient.js"
NODE_SUITE = ROOT / "tests" / "llm-route-guard.test.mjs"
RUN_RESEARCH_PATH = ROOT / "scripts" / "run_research.py"
MORNING_WORKFLOW = ROOT / ".github" / "workflows" / "morning-report.yml"
GOOD_KEY = "offline-llm-route-key-0123456789abcdef"
BROWSER_KEY = "offline-llm-browser-key-fedcba9876543210"
PAID_ROUTES = (
    "research-multi",
    "research",
    "chat",
    "debate",
    "macro",
    "morning-report",
    "research-pulse",
)

NODE_PRELUDE = r"""
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL } from 'node:url';

const SDK_STUB = `
export default class Anthropic {
  constructor() {
    this.messages = {
      create: async () => { globalThis.__llmProviderCalls += 1; throw new Error('provider reached'); },
      stream: () => { globalThis.__llmProviderCalls += 1; throw new Error('provider reached'); },
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
globalThis.__fetchCalls = 0;
globalThis.fetch = async () => { globalThis.__fetchCalls += 1; throw new Error('network is forbidden'); };

const [root, argJson] = process.argv.slice(2);
const args = JSON.parse(argJson || '{}');
const GOOD_KEY = args.good_key;
const BROWSER_KEY = args.browser_key;
const BOTH_KEYS = { AR_LLM_ROUTE_KEY: GOOD_KEY, AR_LLM_BROWSER_ROUTE_KEY: BROWSER_KEY };
const load = rel => import(pathToFileURL(`${root}/${rel}`).href);
function makeResponse() {
  return {
    code: null, headers: {}, body: null,
    setHeader(name, value) { this.headers[name.toLowerCase()] = value; },
    status(code) { this.code = code; return this; },
    json(payload) { this.body = payload; return this; },
    end() { return this; },
  };
}
function runGuard(guard, { method = 'POST', origin, key, env = { AR_LLM_ROUTE_KEY: GOOD_KEY }, route = 'research', ip = '203.0.113.7', now = 1800000000000 } = {}) {
  const headers = { 'x-real-ip': ip };
  if (origin !== undefined) headers.origin = origin;
  if (key !== undefined) headers['x-ar-llm-key'] = key;
  const res = makeResponse();
  const ok = guard.guardLlmRoute({ method, headers }, res, route, { env, now });
  return { ok, res };
}
"""

RUNNERS = {
    "fails_closed": r"""
const guard = await load('api/_lib/llm-route-guard.js');
for (const env of [{}, { AR_LLM_ROUTE_KEY: '' }, { AR_LLM_ROUTE_KEY: 'too-short' }]) {
  const configured = env.AR_LLM_ROUTE_KEY;
  for (const key of [GOOD_KEY, configured, undefined]) {
    const { ok, res } = runGuard(guard, { env, key });
    assert.equal(ok, false);
    assert.equal(res.code, 503, `missing/short server key must fail closed with 503, got ${res.code}`);
    assert.equal(res.body.code, 'LLM_ROUTE_KEY_NOT_CONFIGURED');
  }
}
""",
    "key_match": r"""
const guard = await load('api/_lib/llm-route-guard.js');
for (const key of [undefined, '', `${GOOD_KEY}x`, GOOD_KEY.slice(0, -1), 'x'.repeat(GOOD_KEY.length)]) {
  const { ok, res } = runGuard(guard, { key });
  assert.equal(ok, false, `key ${JSON.stringify(key)} must not pass`);
  assert.equal(res.code, 401);
  assert.equal(res.body.code, 'LLM_ROUTE_UNAUTHORIZED');
}
assert.equal(runGuard(guard, { key: GOOD_KEY }).ok, true);
""",
    "origin": r"""
const guard = await load('api/_lib/llm-route-guard.js');
for (const origin of ['https://evil.example', 'null', 'https://lateily.github.io.evil.example', 'http://equity-research-ten.vercel.app']) {
  const { ok, res } = runGuard(guard, { key: GOOD_KEY, origin });
  assert.equal(ok, false, `origin ${origin} must be refused`);
  assert.equal(res.code, 403);
  assert.equal(res.headers['access-control-allow-origin'], undefined);
}
for (const origin of ['https://evil.example', 'null']) {
  assert.equal(runGuard(guard, { key: BROWSER_KEY, origin, env: BOTH_KEYS }).res.code, 403,
    `origin ${origin} must be refused even with the browser key`);
}
const allowed = runGuard(guard, { key: BROWSER_KEY, origin: 'https://equity-research-ten.vercel.app', env: BOTH_KEYS });
assert.equal(allowed.ok, true);
assert.equal(allowed.res.headers['access-control-allow-origin'], 'https://equity-research-ten.vercel.app');
""",
    "whitespace_key": r"""
const guard = await load('api/_lib/llm-route-guard.js');
for (const padded of [`${GOOD_KEY}\n`, `${GOOD_KEY} `, ` ${GOOD_KEY}`, `${GOOD_KEY}\r\n`]) {
  const { ok, res } = runGuard(guard, { key: GOOD_KEY, env: { AR_LLM_ROUTE_KEY: padded } });
  assert.equal(ok, false);
  assert.equal(res.code, 503, `whitespace-padded server key must be 503 (not a silent 401), got ${res.code}`);
  assert.equal(res.body.code, 'LLM_ROUTE_KEY_NOT_CONFIGURED');
}
const browser = runGuard(guard, { key: BROWSER_KEY, origin: 'https://lateily.github.io',
  env: { AR_LLM_ROUTE_KEY: GOOD_KEY, AR_LLM_BROWSER_ROUTE_KEY: `${BROWSER_KEY}\n` } });
assert.equal(browser.res.code, 503);
""",
    "browser_key_separate": r"""
const guard = await load('api/_lib/llm-route-guard.js');
const origin = 'https://lateily.github.io';
// The automation key never unlocks an Origin-bearing request ...
let r = runGuard(guard, { key: GOOD_KEY, origin, env: BOTH_KEYS });
assert.equal(r.ok, false, 'server key must not unlock a browser request');
assert.equal(r.res.code, 401);
// ... and with no browser key configured the browser path is closed.
r = runGuard(guard, { key: GOOD_KEY, origin, env: { AR_LLM_ROUTE_KEY: GOOD_KEY } });
assert.equal(r.ok, false);
assert.equal(r.res.code, 503);
// The browser key never unlocks a server-to-server request.
r = runGuard(guard, { key: BROWSER_KEY, env: BOTH_KEYS });
assert.equal(r.ok, false, 'browser key must not unlock a server-to-server request');
assert.equal(r.res.code, 401);
assert.equal(runGuard(guard, { key: BROWSER_KEY, origin, env: BOTH_KEYS }).ok, true);
assert.equal(runGuard(guard, { key: GOOD_KEY, env: BOTH_KEYS, ip: '198.51.100.1' }).ok, true);
""",
    "browser_key_must_differ": r"""
const guard = await load('api/_lib/llm-route-guard.js');
const r = runGuard(guard, { key: GOOD_KEY, origin: 'https://lateily.github.io',
  env: { AR_LLM_ROUTE_KEY: GOOD_KEY, AR_LLM_BROWSER_ROUTE_KEY: GOOD_KEY } });
assert.equal(r.ok, false, 'a browser key equal to the server key must be refused');
assert.equal(r.res.code, 503);
assert.equal(r.res.body.code, 'LLM_BROWSER_KEY_NOT_SEPARATE');
""",
    "rate_limit": r"""
const guard = await load('api/_lib/llm-route-guard.js');
guard.resetRateLimits();
const limit = guard.RATE_LIMITS['research-multi'];
assert.equal(limit, 3);
for (let i = 0; i < limit; i += 1) {
  assert.equal(runGuard(guard, { key: GOOD_KEY, route: 'research-multi', now: 1800000000000 + i }).ok, true);
}
const limited = runGuard(guard, { key: GOOD_KEY, route: 'research-multi', now: 1800000000000 + limit });
assert.equal(limited.ok, false, 'burst above the per-IP limit must be refused');
assert.equal(limited.res.code, 429);
assert.ok(Number(limited.res.headers['retry-after']) > 0);
""",
    "handlers": r"""
for (const route of args.routes) {
  const { default: handler } = await load(`api/${route}.js`);
  const body = { ticker: '600519.SH', regime_data: { sectors: [] }, article: { title: 't' }, text: 't', date: '2026-09-29' };
  const cases = [
    { configured: undefined, headers: { 'x-ar-llm-key': GOOD_KEY }, code: 503 },
    { configured: GOOD_KEY, headers: {}, code: 401 },
    { configured: GOOD_KEY, headers: { 'x-ar-llm-key': 'wrong-key-wrong-key-wrong-key-wrong' }, code: 401 },
    { configured: GOOD_KEY, headers: { 'x-ar-llm-key': GOOD_KEY, origin: 'https://evil.example' }, code: 403 },
  ];
  for (const item of cases) {
    if (item.configured === undefined) delete process.env.AR_LLM_ROUTE_KEY;
    else process.env.AR_LLM_ROUTE_KEY = item.configured;
    const before = [globalThis.__llmProviderCalls, globalThis.__fetchCalls];
    const res = makeResponse();
    await handler({ method: 'POST', headers: item.headers, body }, res);
    assert.equal(res.code, item.code, `${route}: expected ${item.code}, got ${res.code}`);
    assert.deepEqual([globalThis.__llmProviderCalls, globalThis.__fetchCalls], before,
      `${route}: provider/network reached before the gate rejected`);
    assert.notEqual(res.headers['access-control-allow-origin'], '*', `${route}: wildcard CORS`);
  }
}
""",
    "browser_client": r"""
const client = await load('src/llmRouteClient.js');
let calls = 0;
const fetchImpl = async () => { calls += 1; return { status: 200 }; };
client.configureLlmRoutes({ browserEnabled: '1' });
client.setOperatorLlmKey(GOOD_KEY);
client.configureLlmRoutes({ browserEnabled: undefined });
for (const route of client.LLM_ROUTE_PATHS) {
  await assert.rejects(
    client.llmRouteFetch(route, { method: 'POST' }, { fetchImpl }),
    err => err.code === 'LLM_BROWSER_ROUTES_DISABLED',
  );
}
client.configureLlmRoutes({ browserEnabled: '1' });
await assert.rejects(
  client.llmRouteFetch('/api/research', { method: 'POST' }, { fetchImpl }),
  err => err.code === 'LLM_ROUTE_KEY_MISSING',
);
assert.equal(calls, 0, 'a locked browser client must not touch the network');
""",
}


def _node_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not any(part in key.upper() for part in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))
    }
    env.update(
        {
            "ANTHROPIC_API_KEY": "offline",
            "OPENAI_API_KEY": "offline",
            "GOOGLE_AI_API_KEY": "offline",
            "AR_OFFLINE": "1",
        }
    )
    return env


def _load_run_research():
    sys.path.insert(0, str(RUN_RESEARCH_PATH.parent))
    try:
        spec = importlib.util.spec_from_file_location("run_research_under_test", RUN_RESEARCH_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(RUN_RESEARCH_PATH.parent))


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b'{"success": true}'


@unittest.skipUnless(shutil.which("node"), "node is required for the route-gate runners")
class LlmRouteGuardTest(unittest.TestCase):
    def _run_node(self, runner: str, **arguments: object) -> None:
        payload = {"good_key": GOOD_KEY, "browser_key": BROWSER_KEY, **arguments}
        with tempfile.TemporaryDirectory(prefix="ar-llm-route-guard-") as tmp:
            script = Path(tmp) / "runner.mjs"
            script.write_text(NODE_PRELUDE + RUNNERS[runner], encoding="utf-8")
            try:
                completed = subprocess.run(
                    ["node", "--no-warnings", str(script), str(ROOT), json.dumps(payload)],
                    cwd=ROOT,
                    env=_node_env(),
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:  # a hang counts as a failed guard, not an error
                self.fail(f"node runner {runner} timed out: {exc}")
        self.assertEqual(
            completed.returncode,
            0,
            f"node runner {runner} failed:\n{completed.stdout}\n{completed.stderr}",
        )

    def test_guard_fails_closed_without_server_key(self) -> None:
        self._run_node("fails_closed")

    def test_guard_rejects_missing_or_wrong_key(self) -> None:
        self._run_node("key_match")

    def test_guard_refuses_foreign_origin_even_with_key(self) -> None:
        self._run_node("origin")

    def test_guard_rate_limits_authenticated_bursts(self) -> None:
        self._run_node("rate_limit")

    def test_guard_fails_closed_on_whitespace_padded_key(self) -> None:
        self._run_node("whitespace_key")

    def test_guard_keeps_browser_and_server_keys_separate(self) -> None:
        self._run_node("browser_key_separate")

    def test_guard_refuses_browser_key_equal_to_server_key(self) -> None:
        self._run_node("browser_key_must_differ")

    def test_every_paid_handler_rejects_before_provider(self) -> None:
        self._run_node("handlers", routes=list(PAID_ROUTES))

    def test_browser_client_is_locked_without_flag_and_key(self) -> None:
        self._run_node("browser_client")

    def test_node_suite_passes(self) -> None:
        completed = subprocess.run(
            ["node", "--no-warnings", str(NODE_SUITE)],
            cwd=ROOT,
            env=_node_env(),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("ALL LLM ROUTE GUARD TESTS PASS", completed.stdout)


class LlmRouteStaticPinTest(unittest.TestCase):
    def test_key_compare_is_constant_time(self) -> None:
        # Timing cannot be measured offline; pin the exact compare instead.
        source = GUARD_PATH.read_text(encoding="utf-8")
        match = re.search(
            r"export function timingSafeEqualString\(a, b\) \{\n(?P<body>.*?)\n\}\n", source, re.S
        )
        self.assertIsNotNone(match, "timingSafeEqualString must stay a top-level exported function")
        body = match.group("body")
        self.assertRegex(
            body,
            r"\n  return timingSafeEqual\(digestA, digestB\) && a\.length === b\.length;\Z",
        )
        self.assertEqual(len(re.findall(r"\breturn\b", body)), 2)
        self.assertNotRegex(body, r"\b[ab]\s*[!=]==?\s*[ab]\b", "direct compare of the key strings")
        self.assertNotRegex(source, r"(?<!typeof )providedKey\s*[!=]==?|[!=]==?\s*providedKey")


class LlmRouteCallerTest(unittest.TestCase):
    def test_run_research_refuses_to_call_without_key(self) -> None:
        module = _load_run_research()
        seen: list[urllib.request.Request] = []
        original = urllib.request.urlopen

        def fake_urlopen(request, timeout=None):
            seen.append(request)
            return _FakeResponse()

        urllib.request.urlopen = fake_urlopen
        previous = os.environ.pop("AR_LLM_ROUTE_KEY", None)
        try:
            with self.assertRaises(module.MissingLlmRouteKey):
                module.call_research_api("http://127.0.0.1:9/api/research", "600519.SH", None, "NEUTRAL", None, None)
            self.assertEqual(seen, [], "no HTTP request may be attempted without the key")

            os.environ["AR_LLM_ROUTE_KEY"] = GOOD_KEY
            module.call_research_api("http://127.0.0.1:9/api/research", "600519.SH", None, "NEUTRAL", None, None)
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0].get_header("X-ar-llm-key"), GOOD_KEY)
        finally:
            urllib.request.urlopen = original
            if previous is None:
                os.environ.pop("AR_LLM_ROUTE_KEY", None)
            else:
                os.environ["AR_LLM_ROUTE_KEY"] = previous

    def test_morning_report_workflow_sends_key_from_secret_env_only(self) -> None:
        text = MORNING_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("AR_LLM_ROUTE_KEY: ${{ secrets.AR_LLM_ROUTE_KEY }}", text)
        self.assertIn("'X-AR-LLM-Key': llm_route_key", text)
        self.assertIn("os.environ.get('AR_LLM_ROUTE_KEY'", text)
        # The secret must not be template-interpolated into the script body or echoed.
        self.assertEqual(text.count("secrets.AR_LLM_ROUTE_KEY"), 1)
        self.assertNotRegex(text, r"print\([^)]*llm_route_key")
        # The automation path uses the server key only, never the browser key.
        self.assertNotIn("AR_LLM_BROWSER_ROUTE_KEY", text)

    def test_morning_report_workflow_fails_fast_without_secret(self) -> None:
        # Without the exit the step would POST an empty X-AR-LLM-Key and fail
        # later as a generic 401/503 instead of naming the missing secret.
        text = MORNING_WORKFLOW.read_text(encoding="utf-8")
        match = re.search(
            r"llm_route_key = os\.environ\.get\('AR_LLM_ROUTE_KEY', ''\)\.strip\(\)\n"
            r"\s+if not llm_route_key:\n\s+print\([^\n]*\)\n\s+sys\.exit\(1\)\n",
            text,
        )
        self.assertIsNotNone(match, "missing secret must sys.exit(1) right after the check")
        sends_key = text.index("'X-AR-LLM-Key': llm_route_key")
        self.assertLess(match.end(), sends_key, "fail-fast must run before the key is sent")

    def test_browser_sources_never_name_the_server_key(self) -> None:
        for path in (ROOT / "src").rglob("*"):
            if path.is_file() and path.suffix in {".js", ".jsx", ".mjs", ".ts", ".tsx"}:
                text = path.read_text(encoding="utf-8")
                self.assertNotRegex(text, r"AR_LLM_(BROWSER_)?ROUTE_KEY", str(path))
                self.assertNotRegex(text, r"VITE_[A-Z_]*LLM[A-Z_]*KEY", str(path))


if __name__ == "__main__":
    unittest.main()
