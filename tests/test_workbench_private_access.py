"""Owner-only Serve transport: in-memory HTTP, never contacts Tailscale."""
import io
import json
import socket
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/llm"))
import nonprod_workbench as wb

ORIGIN = "https://owner.tail-test.ts.net"
OWNER = "owner@example.test"


class PrivateAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = wb.Store(Path(self.tmp.name) / "state")
        self.assets = {"/": (b"private trial", "text/html"), "/index.html": (b"private trial", "text/html")}
        for name in ("socket", "create_connection", "getaddrinfo"):
            guard = mock.patch.object(socket, name, side_effect=AssertionError("unexpected network"))
            guard.start()
            self.addCleanup(guard.stop)

    def test_remote_origin_cannot_reuse_local_session_minter(self):
        with self.assertRaises(wb.WorkbenchError):
            wb.make_handler(self.store, self.assets, ORIGIN, "test-session")

    def http(self, path="/", body=None, overrides=None, duplicates=(), peer="127.0.0.1"):
        policy = wb.private_access(ORIGIN, OWNER)
        Handler = wb.make_handler(self.store, self.assets, ORIGIN, "test-session", private=policy)
        handler = object.__new__(Handler)
        handler.path = path
        handler.client_address = (peer, 12345)
        handler.headers = Message()
        raw = wb.canonical(body).encode() if body is not None else b""
        headers = {"Host": ORIGIN[8:], "Origin": ORIGIN, "Cookie": "ar_workbench=test-session",
                   "Tailscale-User-Login": OWNER, "Content-Type": "application/json", "Content-Length": str(len(raw))}
        headers.update(overrides or {})
        for key, value in headers.items():
            if value is not None:
                handler.headers[key] = value
        for key, value in duplicates:
            handler.headers[key] = value
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler.request_version, handler.requestline = "HTTP/1.1", "test"
        handler.command = "POST" if body is not None else "GET"
        (handler.do_POST if body is not None else handler.do_GET)()
        return handler.wfile.getvalue()

    def probe(self):
        return {"command_id": "private-probe-001", "provider": "deepseek", "mode": "offline", "fixture": "contract-smoke"}

    def test_owner_can_mint_secure_session_and_use_offline_adapter(self):
        raw = self.http(overrides={"Cookie": None, "Origin": None})
        self.assertIn(b"200 OK", raw)
        self.assertIn(b"Set-Cookie: ar_workbench=test-session; HttpOnly; SameSite=Strict; Path=/; Secure", raw)
        self.assertNotIn(OWNER.encode(), raw)
        self.assertIn(b"200 OK", self.http("/api/gateway/probe", self.probe()))
        state = self.store.snapshot()
        self.assertEqual(len(state["receipts"]), 1)
        receipt = state["receipts"][0]
        self.assertIs(receipt["provider_contacted"], False)
        self.assertEqual(receipt["usage"]["charged_cny"], "0")
        for key in ("production_write_enabled", "paid_calls_enabled", "team_access_enabled"):
            self.assertIs(state["policy"][key], False)

    def test_unauthenticated_entry_cannot_mint_cookie(self):
        for path in ("/", "/index.html"):
            raw = self.http(path, overrides={"Tailscale-User-Login": None})
            self.assertIn(b"403 Forbidden", raw)
            self.assertIn(b"PRIVATE_OWNER_REQUIRED", raw)
            self.assertNotIn(b"Set-Cookie", raw)
            self.assertNotIn(b"private trial", raw)

    def test_foreign_identity_cannot_read_with_valid_session(self):
        for login in ("teammate@example.test", "OWNER@example.test", " owner@example.test", "owner@example.test.evil", "", None):
            raw = self.http("/api/state", overrides={"Tailscale-User-Login": login})
            self.assertIn(b"403 Forbidden", raw)
            self.assertNotIn(b"receipts", raw)

    def test_private_post_guard_precedes_any_state_write(self):
        before = self.store.snapshot()
        raw = self.http("/api/gateway/probe", self.probe(), {"Tailscale-User-Login": "teammate@example.test"})
        self.assertIn(b"403 Forbidden", raw)
        self.assertEqual(self.store.snapshot(), before)

    def test_display_name_never_substitutes_for_identity(self):
        raw = self.http(overrides={"Tailscale-User-Login": None, "Tailscale-User-Name": OWNER, "X-Forwarded-User": OWNER})
        self.assertIn(b"403 Forbidden", raw)

    def test_proxy_must_be_loopback(self):
        self.assertIn(b"200 OK", self.http())
        for peer in ("100.64.0.1", "192.168.1.9", "::1"):
            self.assertIn(b"LOOPBACK_PROXY_REQUIRED", self.http(peer=peer))

    def test_duplicate_security_headers_refused_before_cookie_mint(self):
        for name, value in (("Host", ORIGIN[8:]), ("Origin", ORIGIN), ("Cookie", "ar_workbench=test-session"),
                            ("Tailscale-User-Login", OWNER), ("Sec-Fetch-Site", "same-origin")):
            overrides = {"Sec-Fetch-Site": "same-origin"} if name == "Sec-Fetch-Site" else {}
            raw = self.http(overrides=overrides, duplicates=[(name, value)])
            self.assertIn(b"AMBIGUOUS_SECURITY_HEADER", raw)
            self.assertNotIn(b"Set-Cookie", raw)

    def test_owner_does_not_bypass_csrf_host_or_session(self):
        for headers in ({"Origin": None}, {"Origin": "https://evil.test"}, {"Host": "localhost:8770"},
                        {"Sec-Fetch-Site": "cross-site"}, {"Cookie": None}, {"Cookie": "ar_workbench=wrong"}):
            self.assertIn(b"403 Forbidden", self.http("/api/gateway/probe", self.probe(), headers))
        self.assertEqual(self.store.snapshot()["receipts"], [])
        self.assertIn(b"403 Forbidden", self.http(overrides={"Host": "evil.test"}))

    def test_owner_does_not_gain_privileged_routes(self):
        for path in ("/api/team/grants", "/api/gateway/live", "/api/production/write", "/api/deploy", "/api/rebaseline"):
            self.assertIn(b"403 Forbidden", self.http(path, {"approved_by": "Junyan"}))
        self.assertEqual(self.store.snapshot()["revision"], 0)

    def test_private_origin_must_be_exact_https_tailnet(self):
        self.assertEqual(wb.private_access(ORIGIN, OWNER).origin, ORIGIN)
        for origin in ("http://owner.tail-test.ts.net", ORIGIN + "/", ORIGIN + ":443", ORIGIN + "?x=1",
                       ORIGIN + ".evil.test", "https://*.tail-test.ts.net", "https://user@owner.tail-test.ts.net", None):
            with self.assertRaises(wb.WorkbenchError):
                wb.private_access(origin, OWNER)

    def test_private_login_must_be_exact_nonempty_single_identity(self):
        for login in (None, "", "*", "@example.test", OWNER + "\n", OWNER + ",other@example.test", " owner@example.test"):
            with self.assertRaises(wb.WorkbenchError):
                wb.private_access(ORIGIN, login)
        self.assertIsNone(wb.private_access(None, None))

    def test_private_policy_cannot_bind_another_origin(self):
        with self.assertRaises(wb.WorkbenchError):
            wb.make_handler(self.store, self.assets, "http://127.0.0.1:8770", "session", private=wb.private_access(ORIGIN, OWNER))

    def test_invalid_private_cli_refused_before_state_open(self):
        root = Path(self.tmp.name) / "must-not-exist"
        for args in (["--private-origin", ORIGIN], ["--private-owner-login", OWNER],
                     ["--private-origin", "http://bad.test", "--private-owner-login", OWNER]):
            with self.assertRaises(wb.WorkbenchError):
                wb.main(["--state-root", str(root)] + args)
            self.assertFalse(root.exists())

    def test_read_paths_stay_a_closed_asset_allowlist(self):
        for path in ("/../../.env", "/api/state?path=/etc/passwd", "/data/workspace.sqlite3", "/api/production"):
            self.assertIn(b"404 Not Found", self.http(path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
