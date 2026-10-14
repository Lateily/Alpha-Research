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
import workbench_evidence as ev

ROOT = Path(__file__).resolve().parents[1]
OWNER, MEMBER = "owner@example.com", "member@example.com"


def frozen_source(root, rid="published_one", date="20261013", *, cash=None):
    """Complete scoped publication; no producer/provider is run."""
    def write(name, value):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = ev.canonical(value).encode()
        target.write_bytes(raw)
        return ev.sha(raw)

    base = "public/data/v2/"
    location = f"data_history/funnel/{date}/{rid}"
    hashes = {name: write(location + "/" + name,
                         {"run_id": rid, "target_trade_date": date, "status": "DATA_BLOCKED"})
              for name in ev.BUNDLE}
    health = {"run_id": rid, "as_of": date, "status": "PARTIAL",
              "bundle": {"location": location, "artifacts": hashes}}
    public = {}
    for name in ev.PUBLIC:
        value = {"run_id": rid, "target_trade_date": date, "status": "DATA_BLOCKED"}
        if name == "funnel_health.json":
            value = health
        if name == "model_portfolio_state.json":
            value["data"] = {} if cash is None else {"cash": cash}
        public["public:" + name] = write(base + name, value)
    manifest = {"schema": "nightly_manifest/v2", "run_id": rid, "target_trade_date": date}
    mh = write(base + f"runs/{rid}/manifest.json", manifest)
    pointer = {"schema": "nightly_current_run/v2", "run_id": rid, "target_trade_date": date,
               "manifest_path": f"runs/{rid}/manifest.json", "manifest_sha256": mh, "artifacts": public}
    write(base + "current_run.json", pointer)
    write("experiments/execution_tracker/nightly_run.json",
          {"run_id": "attempt_newer", "target_trade_date": "20261014", "report": "INCOMPLETE",
           "generated_at": "2026-10-14T00:00:00+00:00", "published": False,
           "steps": [{"step": "sample", "status": "FAILED", "tail": "omitted raw diagnostic"}]})
    return pointer


def historical_state(root):
    """Old audit bytes include success, STOP, STARTED and an unregistered directory."""
    src = root / "source"
    frozen_source(src)
    store = wb.Store(root / "legacy")
    system = ws.Workspace(store, src)
    system.start_job({"command_id": "success_brief", "kind": "snapshot-brief"})
    (src / "public/data/v2/model_portfolio_state.json").write_bytes(b"{}")
    system.start_job({"command_id": "stopped_brief", "kind": "snapshot-brief"})
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        system.append(db, system.events(db), "started_brief", "1" * 64, "JOB_STARTED",
                      {"job_id": "started_brief", "kind": "snapshot-brief", "scheduled": False})
        db.execute("INSERT INTO workspace_owner VALUES (1, 'not-a-secret-salt', 'not-a-secret-hash')")
    for name in ("stopped_brief", "started_brief", "orphan_brief"):
        path = store.path.parent / "snapshot-briefs" / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "partial.json").write_bytes(b'{"status":"UNSEALED"}')
    (store.path.parent / "allowlist.json").write_bytes(b'{"members":["private"]}')
    (store.path.parent / "cookie.key").write_bytes(b"local-session-material")
    return store, system


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
