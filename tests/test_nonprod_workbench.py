"""Nonproduction boundary tests. All transport is in-memory; sockets are blocked."""
from __future__ import annotations

import io
import json
import os
import socket
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/llm"))
import nonprod_workbench as wb


def request(command_id="test-command-001", **overrides):
    return dict({"command_id": command_id, "provider": "deepseek", "mode": "offline", "fixture": "contract-smoke"}, **overrides)


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = wb.Store(Path(self.tmp.name) / "sandbox")
        for name in ("socket", "create_connection", "getaddrinfo"):
            guard = mock.patch.object(socket, name, side_effect=AssertionError("unexpected network"))
            guard.start()
            self.addCleanup(guard.stop)

    def rejected(self, callback, code):
        with self.assertRaises(wb.WorkbenchError) as found:
            callback()
        self.assertEqual(found.exception.code, code)

    def test_default_policy_has_no_authority(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "canary-secret-never-persist", "ALLOW_PAID_CALLS": "true", "TEAM_ENABLED": "true"}):
            state = self.store.snapshot()
            for field in ("paid_calls_enabled", "team_access_enabled", "production_write_enabled", "cloud_deployed", "cutover_allowed"):
                self.assertIs(state["policy"][field], False)
            self.assertEqual(state["policy"]["team_grants"], [])
            self.assertEqual(state["policy"]["model_budget_cny"], "0")
            self.assertEqual(state["readiness"]["missing"], list(wb.CONFIG_FIELDS))

    def test_live_and_foreign_provider_refused(self):
        for override in ({"mode": "live"}, {"provider": "anthropic"}, {"provider": "openai"}):
            self.rejected(lambda: wb.dispatch(self.store, "/api/gateway/probe", request(**override)), "LIVE_PROVIDER_CALL_DISABLED")
        self.assertEqual(self.store.snapshot()["receipts"], [])

    def test_unknown_privileged_fields_refused(self):
        for name in ("api_key", "allow_real_call", "approved_by", "prompt", "base_url", "team_grants"):
            self.rejected(lambda: wb.dispatch(self.store, "/api/gateway/probe", request(**{name: "untrusted"})), "PROBE_FIELDS_INVALID")

    def test_synthetic_fixture_allowlist(self):
        for value in ("../production", {}, ["contract-smoke"], None):
            self.rejected(lambda: self.store.probe(request(fixture=value)), "ONLY_BUILTIN_SYNTHETIC_FIXTURES")

    def test_no_team_production_or_paid_routes(self):
        for path in ("/api/team/grants", "/api/gateway/live", "/api/deploy", "/api/migrate", "/api/production/write", "/api/rebaseline"):
            self.rejected(lambda: wb.dispatch(self.store, path, {"approved_by": "Junyan", "enabled": True}), "CAPABILITY_DISABLED")
        self.assertEqual(self.store.snapshot()["revision"], 0)

    def test_offline_receipt_uses_adapter_without_secret_or_transport(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "canary-secret-never-persist"}), \
             mock.patch.object(wb.DeepSeekAdapter, "_read_api_key", side_effect=AssertionError("key read")), \
             mock.patch.object(wb.DeepSeekAdapter, "_post_chat_completion", side_effect=AssertionError("provider transport")):
            result = wb.dispatch(self.store, "/api/gateway/probe", request())
        receipt = result["receipt"]
        self.assertEqual(receipt["mode"], "offline_stub")
        self.assertIsNone(receipt["actual_model"])
        self.assertIs(receipt["provider_contacted"], False)
        self.assertEqual(receipt["usage"], {"status": "NOT_APPLICABLE", "input_tokens": None, "output_tokens": None, "charged_cny": "0"})
        self.assertEqual(receipt["sample_purpose"], "WORKFLOW_DEBUG")
        self.assertEqual(receipt["result"], "OFFLINE_CONTRACT_OK")
        self.assertNotIn(b"canary-secret", self.store.path.read_bytes())
        self.assertEqual(receipt["receipt_hash"], wb.digest({k: v for k, v in receipt.items() if k != "receipt_hash"}))

    def test_missing_evidence_is_not_an_inference_success(self):
        receipt = self.store.probe(request(fixture="evidence-missing"))["receipt"]
        self.assertEqual(receipt["result"], "DATA_BLOCKED")
        self.assertEqual(receipt["status"], "OFFLINE_SIMULATION")
        self.assertEqual(receipt["evidence_grade"], "SYNTHETIC_NOT_RESEARCH_EVIDENCE")

    def test_retry_returns_identical_receipt_after_restart(self):
        first = self.store.probe(request())
        reopened = wb.Store(self.store.path.parent)
        second = reopened.probe(request())
        self.assertEqual(second["disposition"], "IDEMPOTENT")
        self.assertEqual(first["receipt"], second["receipt"])
        self.assertEqual(len(reopened.snapshot()["receipts"]), 1)

    def test_command_id_reuse_with_different_content_refused(self):
        self.store.probe(request())
        self.rejected(lambda: self.store.probe(request(fixture="evidence-missing")), "COMMAND_ID_CONFLICT")
        self.assertEqual(len(self.store.snapshot()["receipts"]), 1)

    def test_concurrent_duplicates_create_one_receipt(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.store.probe(request()), range(12)))
        self.assertEqual(sum(r["disposition"] == "CREATED" for r in results), 1)
        self.assertEqual(len({wb.canonical(r["receipt"]) for r in results}), 1)
        self.assertEqual(len(self.store.snapshot()["receipts"]), 1)

    def test_receipt_limit_is_bounded(self):
        with mock.patch.object(wb, "MAX_RECEIPTS", 1):
            self.store.probe(request())
            self.rejected(lambda: self.store.probe(request(command_id="second-command")), "SANDBOX_RECEIPT_LIMIT")
            self.assertEqual(self.store.probe(request())["disposition"], "IDEMPOTENT")

    def test_draft_cannot_turn_into_approval(self):
        config = {"cloud_provider": "UNVERIFIED", "account_id": "test-account", "region": "test-region", "monthly_budget": "0", "currency": "CNY", "private_destination": "s3://example-private/deployment-test"}
        wb.dispatch(self.store, "/api/deployment-draft", {"expected_revision": 0, "config": config})
        state = self.store.snapshot()
        self.assertEqual(state["config"], config)
        self.assertEqual(state["readiness"]["missing"], [])
        self.assertEqual(state["readiness"]["status"], "DRAFT_AWAITING_HUMAN_VERIFICATION")
        self.assertIs(state["readiness"]["cutover_allowed"], False)
        self.assertIs(state["policy"]["paid_calls_enabled"], False)
        self.assertEqual(len(state["readiness"]["required_gates"]), 8)

    def test_stale_draft_writer_refused(self):
        payload = {"expected_revision": 0, "config": dict.fromkeys(wb.CONFIG_FIELDS)}
        self.store.save_config(payload)
        self.rejected(lambda: self.store.save_config(payload), "DRAFT_REVISION_CONFLICT")
        self.assertEqual(self.store.snapshot()["revision"], 1)

    def test_drafts_keep_revision_history(self):
        self.store.save_config({"expected_revision": 0, "config": dict.fromkeys(wb.CONFIG_FIELDS)})
        config = dict.fromkeys(wb.CONFIG_FIELDS); config["cloud_provider"] = "UNVERIFIED"
        self.store.save_config({"expected_revision": 1, "config": config})
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0], 2)

    def test_public_or_signed_destinations_refused(self):
        for destination in ("https://public.example/files", "s3://bucket", "s3://key:secret@bucket/prefix", "s3://bucket/a/../secret", "s3://bucket/path?token=secret"):
            config = dict.fromkeys(wb.CONFIG_FIELDS); config["private_destination"] = destination
            self.rejected(lambda: self.store.save_config({"expected_revision": 0, "config": config}), "PRIVATE_DESTINATION_REFERENCE_REQUIRED")

    def test_budget_and_draft_fields_fail_closed(self):
        for budget in ("NaN", "Infinity", "-1", "1e9", True, 0, {}):
            config = dict.fromkeys(wb.CONFIG_FIELDS); config["monthly_budget"] = budget
            with self.assertRaises(wb.WorkbenchError):
                self.store.save_config({"expected_revision": 0, "config": config})
        config = dict.fromkeys(wb.CONFIG_FIELDS); config["approved_by"] = "Junyan"
        self.rejected(lambda: self.store.save_config({"expected_revision": 0, "config": config}), "DRAFT_FIELDS_INVALID")

    def test_loopback_only(self):
        self.assertEqual(wb.serve_host("127.0.0.1"), "127.0.0.1")
        for host in ("0.0.0.0", "::", "192.168.1.5", "public.example"):
            self.rejected(lambda: wb.serve_host(host), "TEAM_ACCESS_DISABLED_LOOPBACK_ONLY")

    def test_cross_origin_write_refused(self):
        headers = {"Host": "127.0.0.1:8766", "Origin": "https://untrusted.example", "Cookie": "ar_workbench=local-test"}
        self.rejected(lambda: wb.authorize(headers, "http://127.0.0.1:8766", "local-test", True), "SAME_ORIGIN_REQUIRED")
        headers.pop("Origin")
        self.rejected(lambda: wb.authorize(headers, "http://127.0.0.1:8766", "local-test", True), "SAME_ORIGIN_REQUIRED")

    def test_host_rebinding_refused(self):
        headers = {"Host": "untrusted.example:8766", "Cookie": "ar_workbench=local-test"}
        self.rejected(lambda: wb.authorize(headers, "http://127.0.0.1:8766", "local-test"), "LOOPBACK_HOST_REQUIRED")

    def test_session_required(self):
        headers = {"Host": "127.0.0.1:8766", "Origin": "http://127.0.0.1:8766"}
        self.rejected(lambda: wb.authorize(headers, "http://127.0.0.1:8766", "local-test", True), "LOCAL_SESSION_REQUIRED")
        headers["Cookie"] = "ar_workbench=other-session"
        self.rejected(lambda: wb.authorize(headers, "http://127.0.0.1:8766", "local-test", True), "LOCAL_SESSION_REQUIRED")

    def http(self, path, body=None, extra_headers=None):
        assets = {"/": (b"test index", "text/html"), "/index.html": (b"test index", "text/html")}
        Handler = wb.make_handler(self.store, assets, "http://127.0.0.1:8766", "local-test")
        handler = object.__new__(Handler)
        handler.path = path
        handler.headers = Message()
        raw = wb.canonical(body).encode() if body is not None else b""
        headers = {"Host": "127.0.0.1:8766", "Origin": "http://127.0.0.1:8766", "Cookie": "ar_workbench=local-test", "Content-Type": "application/json", "Content-Length": str(len(raw))}
        headers.update(extra_headers or {})
        for key, value in headers.items():
            handler.headers[key] = value
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler.request_version, handler.requestline, handler.command = "HTTP/1.1", "test", "POST" if body is not None else "GET"
        (handler.do_POST if body is not None else handler.do_GET)()
        return handler.wfile.getvalue()

    def test_http_real_dispatch_security_and_roundtrip(self):
        raw = self.http("/api/gateway/probe", request())
        self.assertIn(b"200 OK", raw)
        self.assertIn(b"OFFLINE_SIMULATION", raw)
        self.assertIn(b"OFFLINE_CONTRACT_OK", self.http("/api/state"))
        self.assertIn(b"403 Forbidden", self.http("/api/team/grants", {"approved_by": "Junyan"}))
        self.assertIn(b"403 Forbidden", self.http("/api/gateway/probe", request(), {"Origin": "https://evil.example"}))
        self.assertEqual(len(self.store.snapshot()["receipts"]), 1)

    def test_http_body_limit_and_content_type(self):
        self.assertIn(b"413 Request Entity Too Large", self.http("/api/gateway/probe", request(), {"Content-Length": "99999"}))
        self.assertIn(b"415 Unsupported Media Type", self.http("/api/gateway/probe", request(), {"Content-Type": "text/plain"}))
        self.assertIn(b"411 Length Required", self.http("/api/gateway/probe", request(), {"Transfer-Encoding": "chunked"}))
        self.assertEqual(self.store.snapshot()["receipts"], [])

    def test_http_paths_are_not_filesystem_paths(self):
        for path in ("/../../.ar_env", "/api/research", "/api/state?path=/etc/passwd", "/assets/../.env"):
            self.assertIn(b"404 Not Found", self.http(path))

    def test_http_security_headers_and_cookie(self):
        raw = self.http("/")
        self.assertIn(b"HttpOnly; SameSite=Strict", raw)
        self.assertIn(b"frame-ancestors 'none'", raw)
        self.assertIn(b"Cache-Control: no-store", raw)
        self.assertNotIn(b"Access-Control-Allow-Origin", raw)
        self.assertIn(b"403 Forbidden", self.http("/", extra_headers={"Sec-Fetch-Site": "cross-site"}))

    def test_duplicate_and_nonfinite_json_refused(self):
        for raw in (b'{"mode":"offline","mode":"live"}', b'{"x":NaN}', b'{"x":Infinity}', b'not json'):
            with self.assertRaises(wb.WorkbenchError):
                wb.decode_json(raw)

    def test_no_partial_receipt_on_adapter_failure(self):
        with mock.patch.object(wb, "execute_offline", side_effect=RuntimeError("synthetic failure")):
            self.assertIn(b"500 Internal Server Error", self.http("/api/gateway/probe", request()))
        self.assertEqual(self.store.snapshot()["receipts"], [])
        self.assertEqual(self.store.probe(request())["disposition"], "CREATED")

    def test_state_and_asset_symlinks_refused(self):
        target = Path(self.tmp.name) / "outside"; target.mkdir()
        link = Path(self.tmp.name) / "link"; link.symlink_to(target, target_is_directory=True)
        self.rejected(lambda: wb.Store(link), "STATE_SYMLINK_REFUSED")
        assets = Path(self.tmp.name) / "dist"; assets.mkdir()
        (target / "index.html").write_text("outside")
        (assets / "index.html").symlink_to(target / "index.html")
        self.rejected(lambda: wb.load_assets(assets), "ASSET_SYMLINK_REFUSED")
        self.assertEqual(list(target.iterdir()), [target / "index.html"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
