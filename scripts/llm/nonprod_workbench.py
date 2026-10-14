"""Loopback workbench with optional bounded Tailscale Serve access.

The local browser session is NOT Junyan authentication. Drafts and receipts are
nonproduction records, not approvals, research evidence, or formal ledgers.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import stat
import sys
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from adapters.base import AgentRequest
from adapters.deepseek import DEFAULT_MODEL, DeepSeekAdapter
import workbench_research as research
import workbench_workspace as workspace

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
    if capability not in {"offline_probe", "save_deployment_draft", "research_replay"}:
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

    def __init__(self, directory: Path, *, shared_v1: bool = False):
        legacy, shared = directory / "workbench.sqlite3", directory / "shared-workbench.sqlite3"
        if directory.is_symlink() or legacy.is_symlink() or shared.is_symlink():
            raise WorkbenchError("STATE_SYMLINK_REFUSED")
        # governance-mutation: WORKBENCH_SHARED_LEGACY_SCHEMA_FENCE
        if not shared_v1 and (shared.exists() or legacy.is_dir()):
            raise WorkbenchError("SHARED_STATE_FLAG_REQUIRED", 409)
        if shared_v1:
            from workbench_shared_state import STORAGE_SCHEMA
            if (directory / "migration-intent.json").exists():
                intent = workspace.evidence.parse(workspace.evidence.read_local(directory, "migration-intent.json"))
                if intent.get("target") != directory.name or not (directory / "migration-receipt.json").is_file():
                    raise WorkbenchError("MIGRATION_STAGING_NOT_SERVABLE", 409)
            if any(parent.is_symlink() for parent in directory.parents):
                raise WorkbenchError("STATE_SYMLINK_REFUSED")
            if legacy.exists() and not legacy.is_dir():
                raise WorkbenchError("STATE_MIGRATION_REQUIRED", 409)
            if shared.exists():
                if not shared.is_file() or not legacy.is_dir() or any(legacy.iterdir()):
                    raise WorkbenchError("SHARED_STATE_FENCE_INVALID", 409)
                with sqlite3.connect(f"file:{shared}?mode=ro", uri=True) as db:
                    try:
                        version = db.execute("SELECT schema FROM shared_metadata WHERE singleton=1").fetchone()
                    except sqlite3.Error:
                        raise WorkbenchError("SHARED_SCHEMA_INCOMPATIBLE", 409) from None
                    if version != (STORAGE_SCHEMA,):
                        raise WorkbenchError("SHARED_SCHEMA_INCOMPATIBLE", 409)
            elif directory.exists() and any(directory.iterdir()):
                raise WorkbenchError("STATE_MIGRATION_REQUIRED", 409)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.shared_v1 = shared_v1
        self.path = shared if shared_v1 else legacy
        if shared_v1:
            legacy.mkdir(exist_ok=True, mode=0o700)
        with self.connect() as db:
            if shared_v1:
                db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, receipt TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS drafts (revision INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS research_runs (id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, receipt TEXT NOT NULL)")
            if shared_v1:
                from workbench_shared_state import initialize
                initialize(db)
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
            research_rows = db.execute("SELECT id, receipt FROM research_runs ORDER BY rowid DESC").fetchall()
        runs = []
        for command_id, raw in research_rows:
            try:
                receipt = json.loads(raw)
                self.verified_research(command_id, receipt)
                runs.append(receipt)
            except (research.ReplayError, WorkbenchError, OSError, ValueError):
                runs.append({"command_id": command_id, "status": "INTEGRITY_ERROR", **research.boundary(), "stages": [], "artifacts": {}})
        return {
            "schema": "ar-workbench-state.v1", "policy": policy(),
            "revision": revision, "config": config, "readiness": readiness(config),
            "receipts": [json.loads(row[0]) for row in rows],
            "research_runs": runs,
        }

    def research_directory(self, command_id):
        research.validate_request({"command_id": command_id, "scenario": "complete-replay"})
        base = self.path.parent / "research-runs"
        if any(p.is_symlink() for p in (base, *base.parents)):
            raise WorkbenchError("RESEARCH_STATE_SYMLINK_REFUSED")
        base.mkdir(exist_ok=True, mode=0o700)
        return base / command_id

    def verified_research(self, command_id, receipt):
        directory = self.research_directory(command_id)
        if directory.is_symlink() or (directory / "receipt.json").is_symlink():
            raise research.ReplayError("REPLAY_ARTIFACT_SYMLINK")
        if json.loads((directory / "receipt.json").read_text()) != receipt:
            raise research.ReplayError("REPLAY_DISK_RECEIPT_MISMATCH")
        return research.verify_receipt(directory, receipt)

    def replay(self, payload):
        try:
            research.validate_request(payload)
            request_hash = digest(payload)
            with self.connect() as db:
                # Single transaction serializes duplicate browser/server requests.
                # A crash leaves a reserved directory, which is never overwritten.
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT request_hash, receipt FROM research_runs WHERE id=?", (payload["command_id"],)).fetchone()
                if row:
                    if request_hash != row[0]:
                        raise WorkbenchError("COMMAND_ID_CONFLICT", 409)
                    receipt = self.verified_research(payload["command_id"], json.loads(row[1]))
                    return {"disposition": "IDEMPOTENT", "receipt": receipt}
                directory = self.research_directory(payload["command_id"])
                if len(list(directory.parent.iterdir())) >= research.MAX_RUNS:
                    raise WorkbenchError("RESEARCH_SANDBOX_LIMIT", 429)
                receipt = research.launch(directory, payload)
                self.verified_research(payload["command_id"], receipt)
                db.execute("INSERT INTO research_runs VALUES (?, ?, ?)", (payload["command_id"], request_hash, canonical(receipt)))
            return {"disposition": "CREATED", "receipt": receipt}
        except research.ReplayError as exc:
            raise WorkbenchError(str(exc), 409) from None


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


LOGIN_PATTERN = re.compile(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,128}@[a-z0-9.-]{1,125}\Z")


def private_session(secret, login):
    return hmac.new(secret.encode(), login.encode(), hashlib.sha256).hexdigest()


def load_private_members(path, owner_login):
    if path is None:
        return frozenset()
    path = Path(path)
    if (not path.is_absolute() or ".." in path.parts or ROOT == path or ROOT in path.parents):
        raise WorkbenchError("PRIVATE_ALLOWLIST_UNSAFE")
    descriptor = -1
    parent = -1
    try:
        # Walk through directory FDs so no symlink parent can redirect the read.
        parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
            try:
                os.stat(".git", dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise WorkbenchError("PRIVATE_ALLOWLIST_UNSAFE")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096):
            raise WorkbenchError("PRIVATE_ALLOWLIST_UNSAFE")
        raw = os.read(descriptor, 4097)
        if len(raw) > 4096:
            raise WorkbenchError("PRIVATE_ALLOWLIST_UNSAFE")
        data = decode_json(raw)
    except OSError:
        raise WorkbenchError("PRIVATE_ALLOWLIST_UNSAFE") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent >= 0:
            os.close(parent)
    if (not isinstance(data, dict) or set(data) != {"members"}
            or not isinstance(data["members"], list) or len(data["members"]) > 20
            or any(not isinstance(login, str) or not LOGIN_PATTERN.fullmatch(login) for login in data["members"])
            or len(set(data["members"])) != len(data["members"])
            or owner_login in data["members"]):
        raise WorkbenchError("PRIVATE_ALLOWLIST_INVALID")
    return frozenset(data["members"])


class PrivateAccess:
    """Trusted-host Serve identity is access control, never human approval."""

    def __init__(self, origin, owner_login, allowlist_path=None):
        if not isinstance(origin, str) or not re.fullmatch(
            r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+(?:-[a-z0-9]+)*\.ts\.net:8443", origin
        ):
            raise WorkbenchError("PRIVATE_HTTPS_ORIGIN_REQUIRED")
        if not isinstance(owner_login, str) or not LOGIN_PATTERN.fullmatch(owner_login):
            raise WorkbenchError("EXACT_OWNER_LOGIN_REQUIRED")
        self.origin, self.owner_login = origin, owner_login
        self.members = load_private_members(allowlist_path, owner_login)

    def check(self, headers, peer):
        if peer != "127.0.0.1":
            raise WorkbenchError("LOOPBACK_PROXY_REQUIRED", 403)
        for name in ("Host", "Origin", "Cookie", "Sec-Fetch-Site", "Tailscale-User-Login",
                     "Content-Length", "Content-Type", "Transfer-Encoding"):
            if len(headers.get_all(name, [])) > 1:
                raise WorkbenchError("AMBIGUOUS_SECURITY_HEADER", 403)
        cookie = headers.get("Cookie", "")
        if cookie and not re.fullmatch(r"ar_workbench=[A-Za-z0-9_-]{1,128}", cookie):
            raise WorkbenchError("AMBIGUOUS_SECURITY_HEADER", 403)
        login = headers.get("Tailscale-User-Login", "")
        if secrets.compare_digest(login.encode("utf-8"), self.owner_login.encode("utf-8")):
            role = "OWNER"
        elif login in self.members:
            role = "MEMBER"
        else:
            raise WorkbenchError("PRIVATE_MEMBER_NOT_ALLOWED", 403)
        return {"mode": "PRIVATE_SHARED_BRIEF", "login": login, "role": role,
                "scope": "READ_SHARED_RESULTS_AND_EXPLICIT_OBSERVE_SNAPSHOT_BRIEF_ONLY",
                "allowed_job_kinds": ["observe", "snapshot-brief"],
                "human_research_approval": False, "schedules_enabled": False}


def private_access(origin, owner_login, allowlist_path=None):
    if origin is None and owner_login is None and allowlist_path is None:
        return None
    return PrivateAccess(origin, owner_login, allowlist_path)


def serve_host(host):
    if host != "127.0.0.1":
        raise WorkbenchError("TEAM_ACCESS_DISABLED_LOOPBACK_ONLY", 403)
    return host


def service_lock(directory):
    lock = directory / "service.lock"
    if lock.is_symlink():
        raise WorkbenchError("SERVICE_LOCK_SYMLINK_REFUSED")
    handle = lock.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise WorkbenchError("WORKSPACE_ALREADY_RUNNING", 409) from None
    return handle


def dispatch(store, path, payload):
    operations = {"/api/gateway/probe": "offline_probe", "/api/deployment-draft": "save_deployment_draft", "/api/research/replay": "research_replay"}
    capability = operations.get(path, "disabled")
    require_capability(capability)
    if capability == "offline_probe":
        return store.probe(payload)
    if capability == "save_deployment_draft":
        return store.save_config(payload)
    if capability == "research_replay":
        return store.replay(payload)
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


def make_handler(store, assets, origin, session, system=None, private=None, shared=None):
    if shared is not None and (private is None or not store.shared_v1):
        raise WorkbenchError("SHARED_PRIVATE_MODE_REQUIRED", 403)
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *_args):
            pass

        def reply(self, status, payload, mime="application/json", cookie=False, session_value=None):
            raw = payload if isinstance(payload, bytes) else canonical(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            if cookie:
                secure = "; Secure" if private is not None else ""
                self.send_header("Set-Cookie", f"ar_workbench={session_value or session}; HttpOnly; SameSite=Strict; Path=/" + secure)
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            try:
                identity = private.check(self.headers, self.client_address[0]) if private is not None else None
                browser_session = private_session(session, identity["login"]) if identity else session
                # Only the exact local entry point may mint a development session.
                if self.path in {"/", "/index.html"}:
                    headers = dict(self.headers)
                    headers["Cookie"] = f"ar_workbench={browser_session}"
                    authorize(headers, origin, browser_session)
                    content, mime = assets[self.path]
                    if identity and system is not None:
                        system.audit_login(identity["login"])
                    self.reply(200, content, mime, cookie=True, session_value=browser_session)
                    return
                authorize(self.headers, origin, browser_session)
                if self.path == "/api/state":
                    state = store.snapshot()
                    if identity:
                        state["policy"] = {**state["policy"], "environment": "NONPRODUCTION_PRIVATE",
                                           "identity": "TAILSCALE_ACCESS_ONLY_NOT_RESEARCH_APPROVAL",
                                           "team_access_enabled": bool(private.members),
                                           "team_grants": [], "access_scope": identity["scope"]}
                        state["access"] = identity
                        if shared is not None:
                            state["access"] = {**identity, "shared_workspace_v1": True}
                    self.reply(200, state)
                elif shared is not None and self.path.split("?", 1)[0] == "/api/shared-workspace":
                    from urllib.parse import parse_qs
                    query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                    if set(query) - {"page"} or (query and (len(query["page"]) != 1 or not re.fullmatch(r"[0-9]{1,3}", query["page"][0]))):
                        raise WorkbenchError("SHARED_PAGE_INVALID")
                    self.reply(200, shared.snapshot(identity["login"], page=int(query.get("page", ["0"])[0])))
                elif shared is not None and self.path.startswith("/api/shared-workspace/jobs/"):
                    self.reply(200, shared.job(self.path.removeprefix("/api/shared-workspace/jobs/"), identity["login"]))
                elif self.path == "/api/workspace" and system is not None and shared is None:
                    state = system.snapshot()
                    if identity:
                        state["access"] = identity
                    self.reply(200, state)
                elif self.path in assets:
                    content, mime = assets[self.path]
                    self.reply(200, content, mime)
                else:
                    raise WorkbenchError("NOT_FOUND", 404)
            except WorkbenchError as exc:
                self.reply(exc.status, {"error": exc.code})
            except workspace.WorkspaceError as exc:
                self.reply(exc.status, {"error": exc.code})
            except Exception:
                self.reply(500, {"error": "LOCAL_STATE_UNAVAILABLE"})

        def do_POST(self):
            try:
                identity = private.check(self.headers, self.client_address[0]) if private is not None else None
                browser_session = private_session(session, identity["login"]) if identity else session
                authorize(self.headers, origin, browser_session, write=True)
                if identity and (self.path != "/api/workspace/job" or system is None):
                    raise WorkbenchError("PRIVATE_OPERATION_DISABLED", 403)
                lengths = self.headers.get_all("Content-Length", [])
                if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,6}", lengths[0]):
                    raise WorkbenchError("BODY_LENGTH_REQUIRED", 411)
                size = int(lengths[0])
                if self.path.startswith("/api/workspace/") and size > 65536:
                    raise WorkbenchError("BODY_TOO_LARGE", 413)
                if size > MAX_BODY:
                    if not self.path.startswith("/api/workspace/"):
                        raise WorkbenchError("BODY_TOO_LARGE", 413)
                if self.headers.get("Content-Type") != "application/json":
                    raise WorkbenchError("JSON_REQUIRED", 415)
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise WorkbenchError("BODY_TRUNCATED")
                payload = decode_json(raw)
                if identity:
                    workspace.exact(payload, {"command_id", "kind", "snapshot_id"} if shared is not None and shared.queue is not None else {"command_id", "kind"})
                    if not isinstance(payload["kind"], str) or payload["kind"] not in {"observe", "snapshot-brief"}:
                        raise WorkbenchError("PRIVATE_OPERATION_DISABLED", 403)
                if self.path.startswith("/api/workspace/") and system is not None:
                    if shared is not None:
                        result = shared.dispatch(payload, identity["login"])
                    elif identity:
                        result = system.dispatch(self.path, payload, actor=identity["login"])
                    else:
                        result = system.dispatch(self.path, payload)
                else:
                    result = dispatch(store, self.path, payload)
                self.reply(202 if shared is not None and shared.queue is not None else 200, result)
            except WorkbenchError as exc:
                self.reply(exc.status, {"error": exc.code})
            except workspace.WorkspaceError as exc:
                self.reply(exc.status, {"error": exc.code})
            except Exception:
                self.reply(500, {"error": "LOCAL_OPERATION_FAILED"})

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--read-only-source-root", type=Path, help="Local AR root; only a fixed public artifact allowlist is read")
    parser.add_argument("--brief-pack-root", type=Path, help="Operator-frozen historical brief pack; requests/brief.json and inputs/ are read only")
    parser.add_argument("--earnings-pack-root", type=Path, help="Operator-frozen historical earnings pack; requests and inputs are read only")
    parser.add_argument("--state-root", type=Path, help="Dedicated nonproduction state directory, separate from code releases")
    parser.add_argument("--private-origin", help="Exact existing Tailscale Serve HTTPS origin on port 8443")
    parser.add_argument("--owner-login", help="Exact owner Tailscale login; access identity is not research approval")
    parser.add_argument("--private-allowlist", type=Path, help="Outside-repo owner-owned mode0600 member allowlist")
    parser.add_argument("--shared-workspace-v1", action="store_true", help="Opt-in isolated persistent shared jobs; requires private access")
    parser.add_argument("--shared-import-once", type=Path, help="Explicit one-time frozen input import for shared mode; no automatic synchronizer")
    args = parser.parse_args(argv)
    host = serve_host(args.host)
    private = private_access(args.private_origin, args.owner_login, args.private_allowlist)
    if args.shared_workspace_v1 and private is None:
        raise WorkbenchError("SHARED_PRIVATE_MODE_REQUIRED", 403)
    if args.shared_import_once and not args.shared_workspace_v1:
        raise WorkbenchError("SHARED_INPUT_STORE_REQUIRED", 403)
    assets = load_assets(ROOT / "tools/nonprod_workbench/dist")
    state_root = args.state_root or ROOT / ".ai-workspace/nonprod-workbench"
    if args.read_only_source_root and (state_root.resolve() == args.read_only_source_root.resolve() or args.read_only_source_root.resolve() in state_root.resolve().parents):
        raise WorkbenchError("STATE_MUST_BE_OUTSIDE_READ_ONLY_SOURCE")
    if args.brief_pack_root:
        pack_dir = args.brief_pack_root.resolve()
        state_dir = state_root.resolve()
        if pack_dir == state_dir or pack_dir in state_dir.parents or state_dir in pack_dir.parents:
            raise WorkbenchError("STATE_MUST_BE_OUTSIDE_FROZEN_BRIEF_PACK")
    if args.earnings_pack_root:
        pack_dir = args.earnings_pack_root.resolve()
        state_dir = state_root.resolve()
        if pack_dir == state_dir or pack_dir in state_dir.parents or state_dir in pack_dir.parents:
            raise WorkbenchError("STATE_MUST_BE_OUTSIDE_FROZEN_EARNINGS_PACK")
    if (ROOT / ".ai-workspace").is_symlink():
        raise WorkbenchError("STATE_PARENT_SYMLINK_REFUSED")
    store = Store(state_root, shared_v1=True) if args.shared_workspace_v1 else Store(state_root)
    lifetime_lock = service_lock(state_root)
    system = workspace.Workspace(store, None if args.shared_workspace_v1 else args.read_only_source_root,
                                 brief_pack_root=args.brief_pack_root,
                                 earnings_pack_root=args.earnings_pack_root,
                                 private_mode=private is not None)
    origin = private.origin if private else f"http://{host}:{args.port}"
    shared = None
    if args.shared_workspace_v1:
        from workbench_shared_workspace import SharedWorkspace
        from workbench_shared_inputs import FrozenInputs
        from workbench_shared_jobs import SharedJobQueue
        from workbench_shared_worker import SharedWorker
        shared = SharedWorkspace(system)
        inputs = FrozenInputs(store)
        if args.shared_import_once: inputs.import_once(args.shared_import_once)
        queue = SharedJobQueue(shared, inputs, shared._execution_identity["code_sha"])
    server = ThreadingHTTPServer((host, args.port), make_handler(store, assets, origin, secrets.token_hex(32), system, private=private, shared=shared))
    server.daemon_threads = True
    worker = None
    if shared is not None:
        worker = SharedWorker(queue)
        worker.start()
    if private is None:
        worker = threading.Thread(target=system.scheduler, daemon=True)
        worker.start()
    if private:
        print(f"NONPRODUCTION_PRIVATE {origin} | access=BRIEF_ONLY schedules=DENY paid=DENY production=DENY", flush=True)
    else:
        print(f"NONPRODUCTION_LOCAL {origin} | team=DENY paid=DENY production=DENY", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        system.stopping.set()
        if shared is not None and worker is not None:
            worker.stop()
        elif worker is not None:
            worker.join(timeout=35)
        server.server_close()
        lifetime_lock.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WorkbenchError as exc:
        print(f"REFUSED: {exc.code}", file=sys.stderr)
        raise SystemExit(2)
