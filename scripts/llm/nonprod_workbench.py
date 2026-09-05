"""Loopback-only deployment workbench. No live inference or production executor.

The local browser session is NOT Junyan authentication. Drafts and receipts are
nonproduction records, not approvals, research evidence, or formal ledgers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import sqlite3
import sys
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from adapters.base import AgentRequest
from adapters.deepseek import DEFAULT_MODEL, DeepSeekAdapter

ROOT = Path(__file__).resolve().parents[2]
PROMPT_VERSION = "workbench_contract_smoke_v1"
MAX_BODY = 4096
MAX_RECEIPTS = 1000
CONFIG_FIELDS = ("cloud_provider", "account_id", "region", "monthly_budget", "currency", "private_destination")
FIXTURES = {
    "contract-smoke": "Return OFFLINE_CONTRACT_OK for a synthetic deployment test.",
    "evidence-missing": "Synthetic evidence is missing. Return DATA_BLOCKED.",
}


class WorkbenchError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return "sha256:" + hashlib.sha256(canonical(value).encode()).hexdigest()


def decode_json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise WorkbenchError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def reject_constant(_value):
        raise WorkbenchError("NONFINITE_JSON")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError):
        raise WorkbenchError("INVALID_JSON") from None


def policy():
    return {
        "environment": "NONPRODUCTION_LOCAL",
        "identity": "LOCAL_BROWSER_SESSION_NOT_HUMAN_AUTHENTICATION",
        "final_authority_owner": "Junyan",
        "provider": "deepseek", "configured_model": DEFAULT_MODEL,
        "network_policy": "OFFLINE", "paid_calls_enabled": False,
        "model_budget_cny": "0", "team_access_enabled": False,
        "team_grants": [], "production_write_enabled": False,
        "cloud_deployed": False, "cutover_allowed": False,
        "sample_purpose": "WORKFLOW_DEBUG", "no_trade_flag": True,
    }


def require_capability(capability):
    if capability not in {"offline_probe", "save_deployment_draft"}:
        raise WorkbenchError("CAPABILITY_DISABLED", 403)


def validate_probe(payload):
    if not isinstance(payload, dict) or set(payload) != {"command_id", "provider", "mode", "fixture"}:
        raise WorkbenchError("PROBE_FIELDS_INVALID")
    if payload["provider"] != "deepseek" or payload["mode"] != "offline":
        raise WorkbenchError("LIVE_PROVIDER_CALL_DISABLED", 403)
    if not isinstance(payload["fixture"], str) or payload["fixture"] not in FIXTURES:
        raise WorkbenchError("ONLY_BUILTIN_SYNTHETIC_FIXTURES")
    if not isinstance(payload["command_id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", payload["command_id"]):
        raise WorkbenchError("COMMAND_ID_INVALID")


def validate_config(config):
    if not isinstance(config, dict) or set(config) != set(CONFIG_FIELDS):
        raise WorkbenchError("DRAFT_FIELDS_INVALID")
    for value in config.values():
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 240 or any(ord(c) < 32 for c in value)):
            raise WorkbenchError("DRAFT_VALUE_INVALID")
    budget = config["monthly_budget"]
    if budget is not None and not re.fullmatch(r"[0-9]{1,8}(\.[0-9]{1,2})?", budget):
        raise WorkbenchError("MONTHLY_BUDGET_INVALID")
    if config["currency"] not in {None, "CNY", "USD"}:
        raise WorkbenchError("BUDGET_CURRENCY_INVALID")
    destination = config["private_destination"]
    if destination:
        parsed = urlsplit(destination)
        if (parsed.scheme not in {"s3", "gs", "oss", "az"} or not parsed.netloc
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not parsed.path.strip("/") or ".." in parsed.path.split("/")):
            raise WorkbenchError("PRIVATE_DESTINATION_REFERENCE_REQUIRED")


def readiness(config):
    missing = [name for name in CONFIG_FIELDS if not config.get(name)]
    return {
        "status": "DRAFT_INCOMPLETE" if missing else "DRAFT_AWAITING_HUMAN_VERIFICATION",
        "missing": missing,
        "cutover_allowed": False,
        "required_gates": [
            "CLOUD_ACCOUNT_REGION_BUDGET_DESTINATION_APPROVAL",
            "ALL_WRITERS_INVENTORIED_INCLUDING_SECOND_MACHINE",
            "PRIVATE_STORAGE_AND_IDENTITY_VERIFIED",
            "NONPRODUCTION_INDEPENDENT_ACCEPTANCE",
            "SEPARATE_CUTOVER_APPROVAL",
            "QUIESCE_AND_DRAIN_ALL_OLD_WRITERS",
            "CONSISTENT_BACKUP_SECRET_SCAN_HASHES_RESTORE_TEST",
            "CLOUD_CANARY_AND_FORMAL_LEDGER_RECONCILIATION",
        ],
    }


def offline_completion(payload, _timeout):
    # No user text, tool arguments, credentials or production evidence enters
    # this stub. A receipt explicitly distinguishes it from provider inference.
    blocked = payload["messages"][-1]["content"] == FIXTURES["evidence-missing"]
    return {"choices": [{"message": {"content": "DATA_BLOCKED" if blocked else "OFFLINE_CONTRACT_OK"}}]}


offline_completion.offline_stub = True


def execute_offline(payload):
    validate_probe(payload)
    adapter = DeepSeekAdapter(completion=offline_completion, allow_real_call=False)
    result = adapter.execute(AgentRequest(
        task_id=payload["command_id"], task_type="WORKFLOW_DEBUG",
        input_payload={"prompt": FIXTURES[payload["fixture"]]},
        prompt_version=PROMPT_VERSION, network_policy="deny", evidence_grade="E4",
    ))
    return {
        "schema": "ar-workbench-receipt.v1", "command_id": payload["command_id"],
        "request_hash": digest(payload), "fixture": payload["fixture"],
        "provider": "deepseek", "configured_model": adapter.model,
        "actual_model": None, "provider_contacted": False,
        "mode": result.output["provider_mode"], "prompt_version": PROMPT_VERSION,
        "evidence_grade": "SYNTHETIC_NOT_RESEARCH_EVIDENCE",
        "sample_purpose": "WORKFLOW_DEBUG", "no_trade_flag": True,
        "status": "OFFLINE_SIMULATION", "result": result.output["text"],
        "usage": {"status": "NOT_APPLICABLE", "input_tokens": None, "output_tokens": None, "charged_cny": "0"},
    }


class Store:
    """Sandbox SQLite transactions; not the production append-only WAL."""

    def __init__(self, directory: Path):
        if directory.is_symlink() or (directory / "workbench.sqlite3").is_symlink():
            raise WorkbenchError("STATE_SYMLINK_REFUSED")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "workbench.sqlite3"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, receipt TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS drafts (revision INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        self.path.chmod(0o600)

    def connect(self):
        return sqlite3.connect(str(self.path), timeout=5)

    def current(self, db):
        row = db.execute("SELECT revision, payload FROM drafts ORDER BY revision DESC LIMIT 1").fetchone()
        return (row[0], json.loads(row[1])) if row else (0, dict.fromkeys(CONFIG_FIELDS))

    def save_config(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"expected_revision", "config"}:
            raise WorkbenchError("DRAFT_REQUEST_INVALID")
        validate_config(payload["config"])
        if type(payload["expected_revision"]) is not int or payload["expected_revision"] < 0:
            raise WorkbenchError("REVISION_INVALID")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            revision, _ = self.current(db)
            if payload["expected_revision"] != revision:
                raise WorkbenchError("DRAFT_REVISION_CONFLICT", 409)
            db.execute("INSERT INTO drafts VALUES (?, ?)", (revision + 1, canonical(payload["config"])))
        return {"revision": revision + 1, "status": "DRAFT_ONLY_NOT_APPROVAL"}

    def probe(self, payload):
        validate_probe(payload)
        request_hash = digest(payload)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT request_hash, receipt FROM receipts WHERE id=?", (payload["command_id"],)).fetchone()
            if row:
                if row[0] != request_hash:
                    raise WorkbenchError("COMMAND_ID_CONFLICT", 409)
                return {"disposition": "IDEMPOTENT", "receipt": json.loads(row[1])}
            if db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] >= MAX_RECEIPTS:
                raise WorkbenchError("SANDBOX_RECEIPT_LIMIT", 429)
            receipt = execute_offline(payload)
            receipt["receipt_hash"] = digest(receipt)
            db.execute("INSERT INTO receipts VALUES (?, ?, ?)", (payload["command_id"], request_hash, canonical(receipt)))
        return {"disposition": "CREATED", "receipt": receipt}

    def snapshot(self):
        with self.connect() as db:
            revision, config = self.current(db)
            rows = db.execute("SELECT receipt FROM receipts ORDER BY rowid DESC").fetchall()
        return {
            "schema": "ar-workbench-state.v1", "policy": policy(),
            "revision": revision, "config": config, "readiness": readiness(config),
            "receipts": [json.loads(row[0]) for row in rows],
        }


def authorize(headers, origin, session, write=False):
    if headers.get("Host") != urlsplit(origin).netloc or headers.get("Sec-Fetch-Site") == "cross-site":
        raise WorkbenchError("LOOPBACK_HOST_REQUIRED", 403)
    supplied_origin = headers.get("Origin")
    if (write and supplied_origin != origin) or (supplied_origin is not None and supplied_origin != origin):
        raise WorkbenchError("SAME_ORIGIN_REQUIRED", 403)
    try:
        cookies = SimpleCookie(headers.get("Cookie", ""))
        value = cookies["ar_workbench"].value if "ar_workbench" in cookies else ""
    except Exception:
        value = ""
    if not secrets.compare_digest(value, session):
        raise WorkbenchError("LOCAL_SESSION_REQUIRED", 403)


def serve_host(host):
    if host != "127.0.0.1":
        raise WorkbenchError("TEAM_ACCESS_DISABLED_LOOPBACK_ONLY", 403)
    return host


def dispatch(store, path, payload):
    operations = {"/api/gateway/probe": "offline_probe", "/api/deployment-draft": "save_deployment_draft"}
    capability = operations.get(path, "disabled")
    require_capability(capability)
    if capability == "offline_probe":
        return store.probe(payload)
    if capability == "save_deployment_draft":
        return store.save_config(payload)
    raise WorkbenchError("UNKNOWN_OPERATION", 404)


def load_assets(directory):
    if not (directory / "index.html").is_file():
        raise WorkbenchError("BUILD_WORKBENCH_UI_FIRST")
    assets = {}
    for path in directory.rglob("*"):
        if path.is_file():
            if path.is_symlink() or directory.resolve() not in path.resolve().parents:
                raise WorkbenchError("ASSET_SYMLINK_REFUSED")
            suffix = path.suffix
            mime = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}.get(suffix)
            if mime:
                assets["/" + path.relative_to(directory).as_posix()] = (path.read_bytes(), mime)
    assets["/"] = assets["/index.html"]
    return assets


def make_handler(store, assets, origin, session):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *_args):
            pass

        def reply(self, status, payload, mime="application/json", cookie=False):
            raw = payload if isinstance(payload, bytes) else canonical(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            if cookie:
                self.send_header("Set-Cookie", f"ar_workbench={session}; HttpOnly; SameSite=Strict; Path=/")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            try:
                # Only the exact local entry point may mint a development session.
                if self.path in {"/", "/index.html"}:
                    headers = dict(self.headers)
                    headers["Cookie"] = f"ar_workbench={session}"
                    authorize(headers, origin, session)
                    content, mime = assets[self.path]
                    self.reply(200, content, mime, cookie=True)
                    return
                authorize(self.headers, origin, session)
                if self.path == "/api/state":
                    self.reply(200, store.snapshot())
                elif self.path in assets:
                    content, mime = assets[self.path]
                    self.reply(200, content, mime)
                else:
                    raise WorkbenchError("NOT_FOUND", 404)
            except WorkbenchError as exc:
                self.reply(exc.status, {"error": exc.code})
            except Exception:
                self.reply(500, {"error": "LOCAL_STATE_UNAVAILABLE"})

        def do_POST(self):
            try:
                authorize(self.headers, origin, session, write=True)
                lengths = self.headers.get_all("Content-Length", [])
                if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,6}", lengths[0]):
                    raise WorkbenchError("BODY_LENGTH_REQUIRED", 411)
                size = int(lengths[0])
                if size > MAX_BODY:
                    raise WorkbenchError("BODY_TOO_LARGE", 413)
                if self.headers.get("Content-Type") != "application/json":
                    raise WorkbenchError("JSON_REQUIRED", 415)
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise WorkbenchError("BODY_TRUNCATED")
                self.reply(200, dispatch(store, self.path, decode_json(raw)))
            except WorkbenchError as exc:
                self.reply(exc.status, {"error": exc.code})
            except Exception:
                self.reply(500, {"error": "LOCAL_OPERATION_FAILED"})

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(argv)
    host = serve_host(args.host)
    assets = load_assets(ROOT / "tools/nonprod_workbench/dist")
    state_root = ROOT / ".ai-workspace/nonprod-workbench"
    if (ROOT / ".ai-workspace").is_symlink():
        raise WorkbenchError("STATE_PARENT_SYMLINK_REFUSED")
    store = Store(state_root)
    origin = f"http://{host}:{args.port}"
    server = ThreadingHTTPServer((host, args.port), make_handler(store, assets, origin, secrets.token_hex(32)))
    server.daemon_threads = True
    print(f"NONPRODUCTION_LOCAL {origin} | team=DENY paid=DENY production=DENY", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WorkbenchError as exc:
        print(f"REFUSED: {exc.code}", file=sys.stderr)
        raise SystemExit(2)
