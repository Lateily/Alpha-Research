"""Offline Jev shadow workbench boundary and projection tests."""

from __future__ import annotations

import json
import contextlib
import io
import socket
import shutil
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from email.message import Message
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/llm"))

import nonprod_workbench as workbench
import workbench_jev_shadow as facade
import jev_u4_shadow as engine


class ShadowFacadeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = workbench.Store(Path(temporary.name) / "sandbox")
        for name in ("socket", "create_connection", "getaddrinfo"):
            guard = mock.patch.object(socket, name, side_effect=AssertionError("network called"))
            guard.start()
            self.addCleanup(guard.stop)

    def request(self, **changes: object) -> dict[str, object]:
        return {"command_id": "jev-demo-0001", "scenario": "synthetic-mixed", **changes}

    def http(self, path: str, body: object = None, headers: dict[str, str] | None = None) -> bytes:
        assets = {"/": (b"test index", "text/html"), "/index.html": (b"test index", "text/html")}
        handler_type = workbench.make_handler(
            self.store, assets, "http://127.0.0.1:8766", "local-test"
        )
        handler = object.__new__(handler_type)
        handler.path = path
        handler.headers = Message()
        raw = workbench.canonical(body).encode() if body is not None else b""
        actual_headers = {
            "Host": "127.0.0.1:8766", "Origin": "http://127.0.0.1:8766",
            "Cookie": "ar_workbench=local-test", "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
        }
        actual_headers.update(headers or {})
        for name, value in actual_headers.items():
            handler.headers[name] = value
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler.request_version = "HTTP/1.1"
        handler.requestline = "test"
        handler.command = "POST" if body is not None else "GET"
        (handler.do_POST if body is not None else handler.do_GET)()
        return handler.wfile.getvalue()

    def test_exact_synthetic_request_and_idempotent_verified_receipt(self) -> None:
        created = facade.run_synthetic(self.store, self.request())
        self.assertEqual("CREATED", created["disposition"])
        self.assertEqual("SIMULATED", created["display_mode"])
        self.assertEqual("SHADOW_ONLY", created["authority"])
        receipt = created["receipt"]
        self.assertEqual("OFFLINE_FIXTURE", receipt["identity"]["run_mode"])
        self.assertFalse(receipt["provider"]["provider_contacted"])
        self.assertFalse(receipt["authority"]["formal_selection_authority"])
        self.assertEqual(receipt, facade.get_run(self.store, "jev-demo-0001"))
        self.assertEqual("IDEMPOTENT", facade.run_synthetic(self.store, self.request())["disposition"])
        self.assertEqual(1, len(facade.list_runs(self.store)))

    def test_concurrent_retry_creates_one_verified_run(self) -> None:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: facade.run_synthetic(self.store, self.request()), range(4)))
        self.assertEqual(1, sum(row["disposition"] == "CREATED" for row in results))
        self.assertEqual(1, len(facade.list_runs(self.store)))
        self.assertEqual(1, len({row["receipt"]["receipt_hash"] for row in results}))

    def test_sandbox_run_limit_is_bounded_and_retry_remains_allowed(self) -> None:
        with mock.patch.object(facade, "MAX_SHADOW_RUNS", 1):
            facade.run_synthetic(self.store, self.request())
            with self.assertRaises(facade.ShadowWorkbenchError) as caught:
                facade.run_synthetic(self.store, self.request(command_id="jev-demo-0002"))
            self.assertEqual("SHADOW_RUN_LIMIT", caught.exception.code)
            self.assertEqual("IDEMPOTENT", facade.run_synthetic(self.store, self.request())["disposition"])
        self.assertEqual(1, len(facade.list_runs(self.store)))

    def test_browser_cannot_supply_paths_provider_answers_or_approval(self) -> None:
        for field in ("path", "artifact_root", "provider", "answers", "api_key", "allow_real_call", "approved_by", "selected_tickers"):
            with self.subTest(field=field), mock.patch.object(facade.engine, "run_shadow", side_effect=AssertionError("engine reached")):
                with self.assertRaises(facade.ShadowWorkbenchError) as caught:
                    facade.run_synthetic(self.store, self.request(**{field: "untrusted"}))
                self.assertEqual("SHADOW_REQUEST_INVALID", caught.exception.code)
        self.assertFalse((self.store.path.parent / "jev-u4-shadow").exists())

    def test_unknown_scenario_and_invalid_id_stop_before_engine(self) -> None:
        for payload in (self.request(scenario="../real"), self.request(command_id="../unsafe")):
            with mock.patch.object(facade.engine, "run_shadow", side_effect=AssertionError("engine reached")):
                with self.assertRaises(facade.ShadowWorkbenchError):
                    facade.run_synthetic(self.store, payload)

    def test_changed_or_symlinked_committed_request_is_rejected(self) -> None:
        source = facade.SHADOW_SCENARIOS["synthetic-mixed"]
        copied = self.store.path.parent / "fixture-copy"
        shutil.copytree(source, copied)
        request_path = copied / "request.json"
        original = request_path.read_bytes()
        with mock.patch.dict(facade.SHADOW_SCENARIOS, {"synthetic-mixed": copied}):
            request_path.write_bytes(original + b" ")
            with self.assertRaises(facade.ShadowWorkbenchError):
                facade.run_synthetic(self.store, self.request())
            request_path.unlink()
            outside = self.store.path.parent / "changed-request.json"
            outside.write_bytes(original)
            request_path.symlink_to(outside)
            with self.assertRaises(facade.ShadowWorkbenchError):
                facade.run_synthetic(self.store, self.request())
        self.assertFalse((self.store.path.parent / "jev-u4-shadow").exists())

    def test_verified_cli_preview_can_be_registered_server_side_only(self) -> None:
        fixture_root = facade.SHADOW_SCENARIOS["synthetic-mixed"]
        request = json.loads((fixture_root / "request.json").read_text(encoding="utf-8"))
        request.update(command_id="jev-preview-001", mode="POLICY_PREVIEW", fixture_id=None)
        receipt = engine.run_shadow(
            request, artifact_root=fixture_root, state_root=self.store.path.parent
        )
        shadow = engine.ShadowStore(self.store.path.parent)
        try:
            shadow.write(request, receipt)
        finally:
            shadow.close()
        self.assertEqual([], facade.list_runs(self.store))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = facade.main([
                "register-preview", "--state-root", str(self.store.path.parent),
                "--command-id", "jev-preview-001",
            ])
        self.assertEqual(0, status)
        self.assertIn('"disposition": "CREATED"', output.getvalue())
        self.assertEqual("POLICY_PREVIEW", facade.list_runs(self.store)[0]["run_mode"])
        self.assertGreater(facade.get_run(self.store, "jev-preview-001")["batch_summary"]["unavailable_count"], 0)
        self.assertEqual("IDEMPOTENT", facade.register_verified_preview(self.store, "jev-preview-001"))
        self.assertIn(b"403 Forbidden", self.http("/api/jev-u4-shadow/register-preview", {"command_id": "jev-preview-001"}))

    def test_tampered_cli_preview_cannot_be_registered(self) -> None:
        fixture_root = facade.SHADOW_SCENARIOS["synthetic-mixed"]
        request = json.loads((fixture_root / "request.json").read_text(encoding="utf-8"))
        request.update(command_id="jev-preview-002", mode="POLICY_PREVIEW", fixture_id=None)
        receipt = engine.run_shadow(
            request, artifact_root=fixture_root, state_root=self.store.path.parent
        )
        shadow = engine.ShadowStore(self.store.path.parent)
        try:
            shadow.write(request, receipt)
        finally:
            shadow.close()
        path = self.store.path.parent / "jev-u4-shadow" / "jev-preview-002" / "receipt.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(facade.ShadowWorkbenchError) as caught:
            facade.register_verified_preview(self.store, "jev-preview-002")
        self.assertEqual("INTEGRITY_ERROR", caught.exception.code)
        self.assertEqual([], facade.list_runs(self.store))

    def test_synthetic_receipt_cannot_be_registered_as_cli_preview(self) -> None:
        fixture_root = facade.SHADOW_SCENARIOS["synthetic-mixed"]
        request = json.loads((fixture_root / "request.json").read_text(encoding="utf-8"))
        request["command_id"] = "jev-cli-synthetic-001"
        receipt = engine.run_shadow(
            request, artifact_root=fixture_root, state_root=self.store.path.parent
        )
        shadow = engine.ShadowStore(self.store.path.parent)
        try:
            shadow.write(request, receipt)
        finally:
            shadow.close()
        with self.assertRaises(facade.ShadowWorkbenchError) as caught:
            facade.register_verified_preview(self.store, "jev-cli-synthetic-001")
        self.assertEqual("PREVIEW_MODE_REQUIRED", caught.exception.code)

    def test_changed_receipt_is_integrity_only_in_list_and_detail(self) -> None:
        facade.run_synthetic(self.store, self.request())
        receipt_path = self.store.path.parent / "jev-u4-shadow" / "jev-demo-0001" / "receipt.json"
        receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
        rows = facade.list_runs(self.store)
        self.assertEqual([{
            "command_id": "jev-demo-0001", "status": "INTEGRITY_ERROR",
            "sample_purpose": "WORKFLOW_DEBUG", "authority": "SHADOW_ONLY",
        }], rows)
        with self.assertRaises(facade.ShadowWorkbenchError) as caught:
            facade.get_run(self.store, "jev-demo-0001")
        self.assertEqual("INTEGRITY_ERROR", caught.exception.code)
        self.assertNotIn("candidate_results", json.dumps(rows))

    def test_unknown_run_is_not_a_cached_conclusion(self) -> None:
        with self.assertRaises(facade.ShadowWorkbenchError) as caught:
            facade.get_run(self.store, "no-such-run-0001")
        self.assertEqual("SHADOW_RUN_NOT_FOUND", caught.exception.code)

    def test_http_synthetic_run_and_verified_projections(self) -> None:
        created = self.http("/api/jev-u4-shadow/run", self.request())
        self.assertIn(b"200 OK", created)
        payload = json.loads(created.partition(b"\r\n\r\n")[2])
        self.assertEqual("SIMULATED", payload["display_mode"])
        self.assertEqual("SHADOW_ONLY", payload["authority"])
        self.assertFalse(payload["receipt"]["provider"]["provider_contacted"])
        self.assertIn(b"jev_u4_shadow_runs", self.http("/api/state"))
        listing = json.loads(self.http("/api/jev-u4-shadow/runs").partition(b"\r\n\r\n")[2])
        self.assertEqual("SHADOW_ONLY", listing["runs"][0]["authority"])
        self.assertNotIn("human_u4_outcome", listing["runs"][0])
        self.assertNotIn("approved_by", listing["runs"][0])
        detail = self.http("/api/jev-u4-shadow/runs/jev-demo-0001")
        self.assertIn(b"200 OK", detail)
        self.assertIn(b"candidate_results", detail)

    def test_http_rejects_untrusted_fields_origin_session_and_paths(self) -> None:
        path = "/api/jev-u4-shadow/run"
        self.assertIn(b"400 Bad Request", self.http(path, self.request(path="/tmp/other")))
        self.assertIn(b"400 Bad Request", self.http(path, self.request(provider="typesafe_jev")))
        self.assertIn(b"400 Bad Request", self.http(path, self.request(scenario="real")))
        self.assertIn(b"403 Forbidden", self.http(path, self.request(), {"Origin": "https://evil.example"}))
        self.assertIn(b"403 Forbidden", self.http(path, self.request(), {"Cookie": ""}))
        self.assertIn(b"413 Request Entity Too Large", self.http(path, self.request(), {"Content-Length": "99999"}))
        for invalid in ("/api/jev-u4-shadow/runs/../secret", "/api/jev-u4-shadow/runs/%2e%2e", "/api/jev-u4-shadow/runs/jev-demo-0001?x=1"):
            self.assertIn(b"404 Not Found", self.http(invalid))
        self.assertEqual([], facade.list_runs(self.store))

    def test_http_changed_receipt_cannot_show_cached_conclusion(self) -> None:
        self.http("/api/jev-u4-shadow/run", self.request())
        receipt_path = self.store.path.parent / "jev-u4-shadow" / "jev-demo-0001" / "receipt.json"
        receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
        listing = self.http("/api/jev-u4-shadow/runs")
        self.assertIn(b"INTEGRITY_ERROR", listing)
        self.assertNotIn(b"candidate_results", listing)
        detail = self.http("/api/jev-u4-shadow/runs/jev-demo-0001")
        self.assertIn(b"409 Conflict", detail)
        self.assertNotIn(b"candidate_results", detail)


if __name__ == "__main__":
    unittest.main()
