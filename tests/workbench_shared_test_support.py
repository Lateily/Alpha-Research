"""Test-only shared-state and committed-source fixtures."""
import io
import json
import shutil
import subprocess
from email.message import Message
from pathlib import Path

import nonprod_workbench as wb
import workbench_workspace as ws
from test_workbench_workspace import source

ROOT = Path(__file__).resolve().parents[1]
OWNER, MEMBER = "owner@example.com", "member@example.com"


def fixture_state(root: Path) -> tuple[wb.Store, ws.Workspace]:
    source_root = root / "source"
    source_root.mkdir()
    source(source_root)
    store = wb.Store(root / "state", shared_v1=True)
    return store, ws.Workspace(store, source_root, private_mode=True)


def committed_code(root, files):
    root.mkdir()
    for name in files:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    for args in (("init", "-q"), ("add", "--", *files),
                 ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                  "-c", "commit.gpgsign=false", "commit", "-qm", "committed execution fixture")):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def http(store, system, private, path, body=None, login=OWNER, extra=(), shared=None):
    assets = {"/": (b"fixture index", "text/html")}
    options = {"shared": shared} if shared is not None else {}
    handler = object.__new__(wb.make_handler(store, assets, private.origin, "test-session",
                                           system, private, **options))
    handler.path, handler.client_address = path, ("127.0.0.1", 12345)
    raw = wb.canonical(body).encode() if body is not None else b""
    handler.headers = Message()
    for key, value in {"Host": private.origin.split("//")[1], "Origin": private.origin,
                       "Cookie": "ar_workbench=" + wb.private_session("test-session", login),
                       "Tailscale-User-Login": login, "Content-Type": "application/json",
                       "Content-Length": str(len(raw))}.items():
        handler.headers[key] = value
    for key, value in extra:
        handler.headers[key] = value
    handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
    handler.request_version, handler.requestline = "HTTP/1.1", "fixture"
    handler.command = "POST" if body is not None else "GET"
    (handler.do_POST if body is not None else handler.do_GET)()
    head, raw = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
    return int(head.split()[1]), json.loads(raw)
