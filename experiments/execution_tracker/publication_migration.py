#!/usr/bin/env python3
"""R-043 published-manifest migration with a recoverable R-015 WAL.

This tool repairs an already-published nightly bundle only when an approved,
content-addressed plan explains every changed artifact. It never runs from the
nightly pipeline and it never edits production without an explicit apply call.

Safety model:
  * plan: bind the current run, both manifests, both pointers, evidence and all
    target bytes into one plan_hash;
  * approval: require a Junyan approval document signed by a local HMAC key;
  * apply: hold the exact nightly.lock used by run_nightly.py, append an R-015
    intent, atomically converge files, verify, then append commit;
  * recover: replay the complete intent. Every file must be either its frozen
    before bytes or target bytes; a third state is refused;
  * audit: preserve both original manifests and append one immutable
    supersession record per migration.

The control-plane WAL is deliberately not an artifact in the manifest it
governs. Putting its own hash into that manifest would create a circular hash
dependency when intent/commit events are appended.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import copy
import datetime as dt
import fcntl
import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import event_ledger


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PLAN_SCHEMA = "ar.publication_manifest_migration_plan.v1"
APPROVAL_SCHEMA = "ar.publication_manifest_migration_approval.v1"
INTENT_SCHEMA = "ar.publication_manifest_migration_intent.v1"
COMMIT_SCHEMA = "ar.publication_manifest_migration_commit.v1"
SUPERSESSION_SCHEMA = "ar.manifest_supersession.v1"
GOVERNANCE_REF = "R-043"
CONTROL_LEDGER_NAME = "publication_migration_events.jsonl"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")
APPROVAL_REF_RE = re.compile(r"^(session|device):[A-Za-z0-9_./:#-]{3,240}$")
EVIDENCE_REF_RE = re.compile(
    r"^(PR #[0-9]+|https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/"
    r"(pull|commit)/[A-Za-z0-9]+|commit:[0-9a-fA-F]{7,64})$"
)


class MigrationError(RuntimeError):
    """A fail-closed migration refusal."""


@dataclass(frozen=True)
class Context:
    et_root: Path
    public_root: Path
    control_ledger: Path
    nightly_lock: Path
    approval_key: Path

    @classmethod
    def production(cls) -> "Context":
        return cls(
            et_root=HERE,
            public_root=REPO / "public" / "data" / "v2",
            control_ledger=HERE / CONTROL_LEDGER_NAME,
            nightly_lock=HERE / "nightly.lock",
            approval_key=Path.home() / ".ar_publication_migration_approval_key",
        )


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise MigrationError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as fh:
            value = json.load(fh, object_pairs_hook=_strict_object)
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MigrationError(f"JSON root must be an object: {path}")
    return value


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise MigrationError(f"cannot hash {path}: {exc}") from exc


def b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def unb64(value: str) -> bytes:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, TypeError) as exc:
        raise MigrationError("plan contains invalid base64 bytes") from exc


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".r043.tmp")
    try:
        with tmp.open("wb") as fh:
            fh.write(value)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if tmp.exists():
            tmp.unlink()


def _scope_root(ctx: Context, scope: str) -> Path:
    if scope == "et":
        return ctx.et_root
    if scope == "public":
        return ctx.public_root
    raise MigrationError(f"unknown scope: {scope}")


def _safe_path(ctx: Context, scope: str, rel: str) -> Path:
    if not rel or Path(rel).is_absolute():
        raise MigrationError(f"unsafe relative path: {rel!r}")
    root = _scope_root(ctx, scope).resolve()
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise MigrationError(f"path escapes {scope} root: {rel}") from exc
    return candidate


def _manifest_rel(run_id: str) -> str:
    return f"runs/{run_id}/manifest.json"


def _manifest_path(ctx: Context, scope: str, run_id: str) -> Path:
    return _safe_path(ctx, scope, _manifest_rel(run_id))


def _current_path(ctx: Context, scope: str) -> Path:
    return _safe_path(ctx, scope, "current_run.json")


def _artifact_path(ctx: Context, key: str) -> Path:
    scope, sep, rel = key.partition(":")
    if not sep:
        raise MigrationError(f"invalid artifact key: {key}")
    return _safe_path(ctx, scope, rel)


def _validate_run_id(run_id: str) -> None:
    if not RUN_ID_RE.fullmatch(run_id or ""):
        raise MigrationError(f"invalid run_id: {run_id!r}")


def _read_current_pair(ctx: Context, run_id: str) -> tuple[dict[str, Any], bytes, bytes]:
    et_path = _current_path(ctx, "et")
    public_path = _current_path(ctx, "public")
    et_bytes, public_bytes = et_path.read_bytes(), public_path.read_bytes()
    et, public = load_json(et_path), load_json(public_path)
    if et != public:
        raise MigrationError("ET/public current_run pointers differ before migration")
    if et.get("run_id") != run_id:
        raise MigrationError(
            f"requested run_id {run_id} is not current ({et.get('run_id')})"
        )
    if et.get("manifest_path") != _manifest_rel(run_id):
        raise MigrationError("current_run manifest_path does not name the current run")
    return et, et_bytes, public_bytes


def _metadata_without_artifacts(value: dict[str, Any]) -> dict[str, Any]:
    return {key: val for key, val in value.items() if key != "artifacts"}


def _plan_hash(plan: dict[str, Any]) -> str:
    payload = {key: val for key, val in plan.items() if key != "plan_hash"}
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def validate_plan(plan: dict[str, Any]) -> None:
    if plan.get("schema") != PLAN_SCHEMA or plan.get("governance_ref") != GOVERNANCE_REF:
        raise MigrationError("unsupported publication migration plan")
    _validate_run_id(str(plan.get("run_id") or ""))
    if not str(plan.get("reason") or "").strip():
        raise MigrationError("migration reason is required")
    try:
        requested_at = dt.datetime.fromisoformat(
            str(plan.get("requested_at") or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise MigrationError("requested_at must be an ISO-8601 timestamp") from exc
    if requested_at.tzinfo is None:
        raise MigrationError("requested_at must include a timezone")
    expected = _plan_hash(plan)
    if not hmac.compare_digest(str(plan.get("plan_hash") or ""), expected):
        raise MigrationError("plan_hash does not match plan contents")
    if not isinstance(plan.get("state_files"), list) or not plan["state_files"]:
        raise MigrationError("plan has no frozen state files")
    if not isinstance(plan.get("derived_files"), list) or not plan["derived_files"]:
        raise MigrationError("plan has no immutable archive/supersession files")
    if not isinstance(plan.get("guard_files"), list) or len(plan["guard_files"]) != 1:
        raise MigrationError("plan must freeze publication_state as one read-only guard")
    state_names = {entry.get("name") for entry in plan["state_files"]}
    if state_names != {
        "et_manifest", "public_manifest", "et_current_run", "public_current_run"
    }:
        raise MigrationError("plan state file set is incomplete or duplicated")
    derived_names = {entry.get("name") for entry in plan["derived_files"]}
    if derived_names != {
        "et_manifest_archive", "public_manifest_archive",
        "et_supersession", "public_supersession",
    }:
        raise MigrationError("plan audit file set is incomplete or duplicated")
    run_id = str(plan["run_id"])
    expected_state = {
        "et_manifest": ("manifest", "et", _manifest_rel(run_id)),
        "public_manifest": ("manifest", "public", _manifest_rel(run_id)),
        "et_current_run": ("current", "et", "current_run.json"),
        "public_current_run": ("current", "public", "current_run.json"),
    }
    for entry in plan["state_files"]:
        descriptor = (entry.get("phase"), entry.get("scope"), entry.get("rel"))
        if descriptor != expected_state[entry["name"]]:
            raise MigrationError(f"state file descriptor is invalid: {entry['name']}")
    guard = plan["guard_files"][0]
    if (guard.get("name"), guard.get("scope"), guard.get("rel")) != (
        "publication_state", "et", "publication_state.json"
    ):
        raise MigrationError("publication_state guard descriptor is invalid")
    for entry in plan["state_files"]:
        target = unb64(entry.get("after_b64", ""))
        if sha256_bytes(target) != entry.get("after_sha256"):
            raise MigrationError(f"state target hash is invalid: {entry.get('name')}")
    for entry in plan["derived_files"]:
        target = unb64(entry.get("content_b64", ""))
        if sha256_bytes(target) != entry.get("sha256"):
            raise MigrationError(f"audit target hash is invalid: {entry.get('name')}")
    changes = plan.get("changes")
    if not isinstance(changes, list):
        raise MigrationError("plan changes must be a list")
    artifacts = [row.get("artifact") for row in changes if isinstance(row, dict)]
    if len(artifacts) != len(changes) or len(set(artifacts)) != len(artifacts):
        raise MigrationError("plan changes contain invalid or duplicate artifacts")
    if any(
        not EVIDENCE_REF_RE.fullmatch(str(row.get("evidence_ref") or ""))
        for row in changes
    ):
        raise MigrationError("every changed artifact requires a verifiable PR/commit evidence_ref")
    core = {
        key: val
        for key, val in plan.items()
        if key not in {"migration_id", "derived_files", "plan_hash"}
    }
    expected_migration_id = (
        "r043-" + hashlib.sha256(canonical(core).encode("utf-8")).hexdigest()[:24]
    )
    if plan.get("migration_id") != expected_migration_id:
        raise MigrationError("migration_id is not derived from the frozen plan core")
    expected_derived = {
        "et_manifest_archive": (
            "archive", "et",
            f"runs/{run_id}/migration_archive/{expected_migration_id}/et_manifest."
            f"{next(row for row in plan['state_files'] if row['name'] == 'et_manifest')['before_sha256']}.json",
        ),
        "public_manifest_archive": (
            "archive", "public",
            f"runs/{run_id}/migration_archive/{expected_migration_id}/public_manifest."
            f"{next(row for row in plan['state_files'] if row['name'] == 'public_manifest')['before_sha256']}.json",
        ),
        "et_supersession": (
            "supersession", "et", f"runs/{run_id}/supersessions/{expected_migration_id}.json"
        ),
        "public_supersession": (
            "supersession", "public", f"runs/{run_id}/supersessions/{expected_migration_id}.json"
        ),
    }
    for entry in plan["derived_files"]:
        descriptor = (entry.get("phase"), entry.get("scope"), entry.get("rel"))
        if descriptor != expected_derived[entry["name"]]:
            raise MigrationError(f"audit file descriptor is invalid: {entry['name']}")


def build_plan(
    ctx: Context,
    run_id: str,
    *,
    reason: str,
    evidence: dict[str, str],
    requested_at: str | None = None,
) -> dict[str, Any]:
    """Build a frozen migration plan without writing any file."""
    _validate_run_id(run_id)
    reason = reason.strip()
    if not reason:
        raise MigrationError("migration reason is required")
    requested_at = requested_at or dt.datetime.now(dt.timezone.utc).isoformat()

    current, et_current_bytes, public_current_bytes = _read_current_pair(ctx, run_id)
    et_manifest_path = _manifest_path(ctx, "et", run_id)
    public_manifest_path = _manifest_path(ctx, "public", run_id)
    et_manifest_bytes = et_manifest_path.read_bytes()
    public_manifest_bytes = public_manifest_path.read_bytes()
    et_manifest = load_json(et_manifest_path)
    public_manifest = load_json(public_manifest_path)
    publication_state_path = _safe_path(ctx, "et", "publication_state.json")
    publication_state = load_json(publication_state_path)
    if publication_state.get("status") != "COMMITTED":
        raise MigrationError("publication_state is not COMMITTED")
    if publication_state.get("run_id") != run_id:
        raise MigrationError("publication_state does not name the current run")
    state_manifest = Path(str(publication_state.get("manifest") or "")).resolve()
    if state_manifest != et_manifest_path.resolve():
        raise MigrationError("publication_state does not bind the durable current manifest")
    if et_manifest.get("run_id") != run_id or public_manifest.get("run_id") != run_id:
        raise MigrationError("manifest run_id does not match requested current run")
    if _metadata_without_artifacts(et_manifest) != _metadata_without_artifacts(public_manifest):
        raise MigrationError("manifest metadata differs beyond artifact hashes")
    et_artifacts = et_manifest.get("artifacts")
    public_artifacts = public_manifest.get("artifacts")
    if not isinstance(et_artifacts, dict) or not isinstance(public_artifacts, dict):
        raise MigrationError("manifest artifacts must be objects")
    if set(et_artifacts) != set(public_artifacts):
        raise MigrationError("ET/public manifest artifact key sets differ")
    forbidden_control = {
        f"et:{CONTROL_LEDGER_NAME}",
        f"et:{CONTROL_LEDGER_NAME}.anchor.json",
        f"et:{CONTROL_LEDGER_NAME}.lock",
    }
    overlap = forbidden_control & set(et_artifacts)
    if overlap:
        raise MigrationError(f"control WAL cannot be governed by its own manifest: {sorted(overlap)}")

    actual: dict[str, str] = {}
    changes: list[dict[str, str]] = []
    for key in sorted(et_artifacts):
        path = _artifact_path(ctx, key)
        if not path.is_file():
            raise MigrationError(f"artifact missing: {key}")
        digest = sha256_file(path)
        actual[key] = digest
        if et_artifacts[key] == public_artifacts[key] == digest:
            continue
        ref = str(evidence.get(key) or "").strip()
        if not ref:
            raise MigrationError(f"evidence is required for changed artifact: {key}")
        changes.append(
            {
                "artifact": key,
                "sha256_et_before": str(et_artifacts[key]),
                "sha256_public_before": str(public_artifacts[key]),
                "sha256_after": digest,
                "evidence_ref": ref,
            }
        )

    target_manifest = copy.deepcopy(et_manifest)
    target_manifest["artifacts"] = actual
    target_manifest_bytes = json_bytes(target_manifest)
    target_manifest_sha = sha256_bytes(target_manifest_bytes)
    target_current = copy.deepcopy(current)
    target_current["manifest_sha256"] = target_manifest_sha
    target_current["artifacts"] = copy.deepcopy(actual)
    target_current_bytes = json_bytes(target_current)

    core = {
        "schema": PLAN_SCHEMA,
        "governance_ref": GOVERNANCE_REF,
        "run_id": run_id,
        "target_trade_date": str(et_manifest.get("target_trade_date") or ""),
        "requested_at": requested_at,
        "reason": reason,
        "evidence": {key: str(evidence[key]) for key in sorted(evidence)},
        "changes": changes,
        "guard_files": [
            {
                "name": "publication_state",
                "scope": "et",
                "rel": "publication_state.json",
                "sha256": sha256_file(publication_state_path),
            }
        ],
        "state_files": [
            {
                "name": "et_manifest",
                "phase": "manifest",
                "scope": "et",
                "rel": _manifest_rel(run_id),
                "before_sha256": sha256_bytes(et_manifest_bytes),
                "after_sha256": target_manifest_sha,
                "after_b64": b64(target_manifest_bytes),
            },
            {
                "name": "public_manifest",
                "phase": "manifest",
                "scope": "public",
                "rel": _manifest_rel(run_id),
                "before_sha256": sha256_bytes(public_manifest_bytes),
                "after_sha256": target_manifest_sha,
                "after_b64": b64(target_manifest_bytes),
            },
            {
                "name": "et_current_run",
                "phase": "current",
                "scope": "et",
                "rel": "current_run.json",
                "before_sha256": sha256_bytes(et_current_bytes),
                "after_sha256": sha256_bytes(target_current_bytes),
                "after_b64": b64(target_current_bytes),
            },
            {
                "name": "public_current_run",
                "phase": "current",
                "scope": "public",
                "rel": "current_run.json",
                "before_sha256": sha256_bytes(public_current_bytes),
                "after_sha256": sha256_bytes(target_current_bytes),
                "after_b64": b64(target_current_bytes),
            },
        ],
    }
    migration_id = "r043-" + hashlib.sha256(canonical(core).encode("utf-8")).hexdigest()[:24]
    supersession_common = {
        "schema": SUPERSESSION_SCHEMA,
        "governance_ref": GOVERNANCE_REF,
        "migration_id": migration_id,
        "run_id": run_id,
        "reason": reason,
        "manifest_sha256_after": target_manifest_sha,
    }
    derived: list[dict[str, str]] = []
    for scope, original, original_sha in (
        ("et", et_manifest_bytes, sha256_bytes(et_manifest_bytes)),
        ("public", public_manifest_bytes, sha256_bytes(public_manifest_bytes)),
    ):
        archive_rel = (
            f"runs/{run_id}/migration_archive/{migration_id}/"
            f"{scope}_manifest.{original_sha}.json"
        )
        supersession = dict(supersession_common, manifest_sha256_before=original_sha)
        supersession_bytes = json_bytes(supersession)
        derived.extend(
            [
                {
                    "name": f"{scope}_manifest_archive",
                    "phase": "archive",
                    "scope": scope,
                    "rel": archive_rel,
                    "sha256": original_sha,
                    "content_b64": b64(original),
                },
                {
                    "name": f"{scope}_supersession",
                    "phase": "supersession",
                    "scope": scope,
                    "rel": f"runs/{run_id}/supersessions/{migration_id}.json",
                    "sha256": sha256_bytes(supersession_bytes),
                    "content_b64": b64(supersession_bytes),
                },
            ]
        )
    plan = dict(core, migration_id=migration_id, derived_files=derived)
    plan["plan_hash"] = _plan_hash(plan)
    validate_plan(plan)
    return plan


def load_plan(path: Path) -> dict[str, Any]:
    plan = load_json(path)
    validate_plan(plan)
    return plan


def _approval_payload(approval: dict[str, Any]) -> dict[str, Any]:
    return {key: val for key, val in approval.items() if key != "signature"}


def _read_approval_key(path: Path) -> bytes:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise MigrationError(f"approval key permissions must deny group/other access: {oct(mode)}")
        key = path.read_bytes().strip()
    except OSError as exc:
        raise MigrationError(f"cannot read approval key {path}: {exc}") from exc
    if len(key) < 32:
        raise MigrationError("approval key must contain at least 32 bytes")
    return key


def validate_approval(
    approval: dict[str, Any], plan: dict[str, Any], key_path: Path
) -> dict[str, Any]:
    validate_plan(plan)
    plan_hash = plan["plan_hash"]
    if approval.get("schema") != APPROVAL_SCHEMA:
        raise MigrationError("unsupported approval schema")
    if approval.get("decision") != "APPROVE":
        raise MigrationError("approval decision must be APPROVE")
    if approval.get("approved_by") != "Junyan":
        raise MigrationError("approval must be bound to Junyan exactly")
    if approval.get("plan_hash") != plan_hash:
        raise MigrationError("approval is not bound to this plan_hash")
    ref = str(approval.get("approval_ref") or "")
    if not APPROVAL_REF_RE.fullmatch(ref):
        raise MigrationError("approval_ref must be a non-empty session: or device: anchor")
    if approval.get("approval_channel") not in {"session_verbatim", "device_signature"}:
        raise MigrationError("approval_channel must be session_verbatim or device_signature")
    try:
        approved_at = dt.datetime.fromisoformat(str(approval.get("approved_at") or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise MigrationError("approved_at must be an ISO-8601 timestamp") from exc
    if approved_at.tzinfo is None:
        raise MigrationError("approved_at must include a timezone")
    requested_at = dt.datetime.fromisoformat(
        str(plan["requested_at"]).replace("Z", "+00:00")
    )
    if approved_at < requested_at:
        raise MigrationError("approved_at must not precede requested_at")
    signature = str(approval.get("signature") or "")
    key = _read_approval_key(key_path)
    expected = hmac.new(
        key, canonical(_approval_payload(approval)).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise MigrationError("approval signature is invalid")
    return approval


def load_approval(path: Path, plan: dict[str, Any], key_path: Path) -> dict[str, Any]:
    return validate_approval(load_json(path), plan, key_path)


@contextlib.contextmanager
def nightly_lock(ctx: Context) -> Iterator[None]:
    ctx.nightly_lock.parent.mkdir(parents=True, exist_ok=True)
    with ctx.nightly_lock.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise MigrationError("nightly.lock is held; migration refuses concurrent apply") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_events(ctx: Context) -> list[dict[str, Any]]:
    chain = event_ledger.verify(str(ctx.control_ledger))
    anchor = event_ledger.verify_anchor(str(ctx.control_ledger))
    append_only = event_ledger.verify_append_only(str(ctx.control_ledger), "HEAD")
    if not chain["ok"] or not anchor["ok"] or not append_only["ok"]:
        raise MigrationError(
            "publication migration WAL is invalid: "
            f"chain={chain['errors']} anchor={anchor['errors']} "
            f"append_only={append_only['errors']}"
        )
    rows = []
    for raw in event_ledger._read_lines(str(ctx.control_ledger)):
        row = json.loads(raw)
        if not row.get("kind", "").startswith("publication_migration_"):
            raise MigrationError(f"foreign event kind in dedicated migration WAL: {row.get('kind')}")
        rows.append(row)
    return rows


def _bootstrap_control_ledger(ctx: Context) -> None:
    """Create a durable empty-chain anchor before the first intent append.

    With an n=0 anchor already on disk, a crash after the first ledger replace
    but before anchor advancement remains recoverable: the old anchor proves
    the empty prefix and verify_anchor reports one appended row.
    """
    path = ctx.control_ledger
    anchor = Path(str(path) + event_ledger.ANCHOR_SUFFIX)
    if path.exists() and not path.is_file():
        raise MigrationError(f"publication migration WAL is not a file: {path}")
    if anchor.exists() and not path.exists():
        raise MigrationError("publication migration WAL anchor exists without its ledger")
    if not path.exists():
        _atomic_write(path, b"")
    if not anchor.exists():
        chain = event_ledger.verify(str(path))
        if not chain["ok"] or chain["n"] != 0:
            raise MigrationError(
                "non-empty publication migration WAL has no anchor; refuse reconstruction"
            )
        event_ledger.write_anchor(str(path), 0, None)


def _event_state(events: list[dict[str, Any]], migration_id: str) -> dict[str, Any]:
    selected = [row for row in events if row.get("id") == migration_id]
    by_kind = {row["kind"]: row for row in selected}
    terminals = [
        kind
        for kind in ("publication_migration_commit", "publication_migration_abort")
        if kind in by_kind
    ]
    if len(terminals) > 1:
        raise MigrationError(f"migration {migration_id} has two terminal states")
    commit = by_kind.get("publication_migration_commit")
    abort = by_kind.get("publication_migration_abort")
    intent = by_kind.get("publication_migration_intent")
    if (commit or abort) and not intent:
        raise MigrationError(f"migration {migration_id} has an orphan terminal event")
    return {"intent": intent, "commit": commit, "abort": abort}


def _pending_for_run(events: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    pending = []
    for row in events:
        if row.get("kind") != "publication_migration_intent":
            continue
        state = _event_state(events, str(row.get("id")))
        plan = (row.get("payload") or {}).get("plan") or {}
        if plan.get("run_id") == run_id and not state["commit"] and not state["abort"]:
            pending.append(row)
    return pending


def _current_digest(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() else None


def _assert_recoverable_file(path: Path, before: str | None, after: str) -> None:
    current = _current_digest(path)
    allowed = {after}
    if before is not None:
        allowed.add(before)
    if current not in allowed:
        raise MigrationError(
            f"file drifted outside frozen before/after states: {path} ({current})"
        )


def _write_derived(ctx: Context, entry: dict[str, Any]) -> None:
    path = _safe_path(ctx, entry["scope"], entry["rel"])
    target = unb64(entry["content_b64"])
    if sha256_bytes(target) != entry["sha256"]:
        raise MigrationError(f"derived file hash mismatch in plan: {entry['name']}")
    if path.exists():
        if sha256_file(path) != entry["sha256"]:
            raise MigrationError(f"immutable derived file already exists with other bytes: {path}")
        return
    _atomic_write(path, target)


def _write_state(ctx: Context, entry: dict[str, Any]) -> None:
    path = _safe_path(ctx, entry["scope"], entry["rel"])
    target = unb64(entry["after_b64"])
    if sha256_bytes(target) != entry["after_sha256"]:
        raise MigrationError(f"target hash mismatch in plan: {entry['name']}")
    _assert_recoverable_file(path, entry["before_sha256"], entry["after_sha256"])
    if _current_digest(path) != entry["after_sha256"]:
        _atomic_write(path, target)


def verify_target(ctx: Context, plan: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for entry in plan["guard_files"]:
        path = _safe_path(ctx, entry["scope"], entry["rel"])
        if _current_digest(path) != entry["sha256"]:
            problems.append(f"{entry['name']}: read-only guard changed")
    for entry in plan["state_files"]:
        path = _safe_path(ctx, entry["scope"], entry["rel"])
        if _current_digest(path) != entry["after_sha256"]:
            problems.append(f"{entry['name']}: target hash mismatch")
    for entry in plan["derived_files"]:
        path = _safe_path(ctx, entry["scope"], entry["rel"])
        if _current_digest(path) != entry["sha256"]:
            problems.append(f"{entry['name']}: immutable audit file missing or changed")
    try:
        current, _, _ = _read_current_pair(ctx, plan["run_id"])
        if current.get("manifest_sha256") != plan["state_files"][0]["after_sha256"]:
            problems.append("current_run does not bind the migrated manifest")
        manifest = load_json(_manifest_path(ctx, "public", plan["run_id"]))
        manifest_artifacts = manifest.get("artifacts")
        if not isinstance(manifest_artifacts, dict):
            problems.append("migrated manifest artifacts is not an object")
            manifest_artifacts = {}
        if current.get("artifacts") != manifest_artifacts:
            problems.append("current_run artifact map differs from migrated manifest")
        for key, expected in manifest_artifacts.items():
            if _current_digest(_artifact_path(ctx, key)) != expected:
                problems.append(f"{key}: artifact does not match migrated manifest")
    except MigrationError as exc:
        problems.append(str(exc))
    return problems


def verify_current(ctx: Context, run_id: str) -> list[str]:
    """Verify current publication without repairing it."""
    problems: list[str] = []
    try:
        current, _, _ = _read_current_pair(ctx, run_id)
        et_manifest = _manifest_path(ctx, "et", run_id)
        public_manifest = _manifest_path(ctx, "public", run_id)
        et_sha, public_sha = sha256_file(et_manifest), sha256_file(public_manifest)
        if et_sha != public_sha:
            problems.append("ET/public manifests differ")
        if current.get("manifest_sha256") != public_sha:
            problems.append("current_run manifest_sha256 is stale")
        manifest = load_json(public_manifest)
        manifest_artifacts = manifest.get("artifacts")
        if not isinstance(manifest_artifacts, dict):
            problems.append("current manifest artifacts is not an object")
            manifest_artifacts = {}
        if current.get("artifacts") != manifest_artifacts:
            problems.append("current_run artifact map differs from current manifest")
        for key, expected in manifest_artifacts.items():
            if _current_digest(_artifact_path(ctx, key)) != expected:
                problems.append(f"{key}: artifact hash mismatch")
    except (MigrationError, OSError) as exc:
        problems.append(str(exc))
    return problems


def _converge(
    ctx: Context,
    plan: dict[str, Any],
    *,
    fail_after: str | None = None,
) -> None:
    for entry in plan["guard_files"]:
        path = _safe_path(ctx, entry["scope"], entry["rel"])
        if _current_digest(path) != entry["sha256"]:
            raise MigrationError(f"read-only guard changed after planning: {entry['name']}")
    for phase in ("archive", "supersession"):
        for entry in plan["derived_files"]:
            if entry["phase"] == phase:
                _write_derived(ctx, entry)
        if fail_after == f"after_{phase}":
            raise RuntimeError(f"test crash {fail_after}")
    for phase in ("manifest", "current"):
        for entry in plan["state_files"]:
            if entry["phase"] == phase:
                _write_state(ctx, entry)
        if fail_after == f"after_{phase}":
            raise RuntimeError(f"test crash {fail_after}")
    problems = verify_target(ctx, plan)
    if problems:
        raise MigrationError(f"post-migration verification failed: {problems}")


def _append_intent(
    ctx: Context, plan: dict[str, Any], approval: dict[str, Any]
) -> None:
    event_ledger.append(
        "publication_migration_intent",
        plan["migration_id"],
        {
            "schema": INTENT_SCHEMA,
            "plan_hash": plan["plan_hash"],
            "plan": plan,
            "approval": approval,
        },
        path=str(ctx.control_ledger),
    )


def _append_commit(ctx: Context, plan: dict[str, Any], approval: dict[str, Any]) -> None:
    event_ledger.append(
        "publication_migration_commit",
        plan["migration_id"],
        {
            "schema": COMMIT_SCHEMA,
            "plan_hash": plan["plan_hash"],
            "approval_ref": approval["approval_ref"],
            "state_sha256": {
                entry["name"]: entry["after_sha256"] for entry in plan["state_files"]
            },
        },
        path=str(ctx.control_ledger),
    )


def _apply_locked(
    ctx: Context,
    plan: dict[str, Any],
    approval: dict[str, Any] | None,
    *,
    fail_after: str | None = None,
) -> dict[str, Any]:
    validate_plan(plan)
    events = _load_events(ctx)
    state = _event_state(events, plan["migration_id"])
    if state["abort"]:
        raise MigrationError("migration has an abort terminal event")
    if state["commit"]:
        problems = verify_target(ctx, plan)
        if problems:
            raise MigrationError(f"committed migration target drifted: {problems}")
        return {"status": "NOOP_VERIFIED", "migration_id": plan["migration_id"]}

    if state["intent"]:
        payload = state["intent"].get("payload") or {}
        recorded_plan = payload.get("plan") or {}
        if payload.get("plan_hash") != plan["plan_hash"] or recorded_plan != plan:
            raise MigrationError("pending intent does not match supplied frozen plan")
        approval = validate_approval(
            payload.get("approval") or {}, plan, ctx.approval_key
        )
    else:
        if approval is None:
            raise MigrationError("a signed approval is required before intent")
        approval = validate_approval(approval, plan, ctx.approval_key)
        if not plan["changes"]:
            problems = verify_current(ctx, plan["run_id"])
            if problems:
                raise MigrationError(f"NOOP refused because full verification failed: {problems}")
            return {"status": "NOOP_VERIFIED", "migration_id": None}
        rebuilt = build_plan(
            ctx,
            plan["run_id"],
            reason=plan["reason"],
            evidence=plan["evidence"],
            requested_at=plan["requested_at"],
        )
        if rebuilt["plan_hash"] != plan["plan_hash"]:
            raise MigrationError("live state changed after planning; plan_hash is stale")
        _append_intent(ctx, plan, approval)
        if fail_after == "after_intent":
            raise RuntimeError("test crash after_intent")

    _converge(ctx, plan, fail_after=fail_after)
    _append_commit(ctx, plan, approval)
    if fail_after == "after_commit":
        raise RuntimeError("test crash after_commit")
    return {
        "status": "APPLIED" if not state["intent"] else "RECOVERED",
        "migration_id": plan["migration_id"],
        "plan_hash": plan["plan_hash"],
        "changed": [row["artifact"] for row in plan["changes"]],
    }


def apply_plan(
    ctx: Context,
    plan: dict[str, Any],
    approval: dict[str, Any] | None,
    *,
    fail_after: str | None = None,
) -> dict[str, Any]:
    with nightly_lock(ctx):
        _bootstrap_control_ledger(ctx)
        pending = _pending_for_run(_load_events(ctx), plan["run_id"])
        if len(pending) > 1:
            raise MigrationError("more than one pending publication migration for current run")
        if pending and pending[0]["id"] != plan["migration_id"]:
            raise MigrationError("another publication migration is pending for this run")
        return _apply_locked(ctx, plan, approval, fail_after=fail_after)


def recover(
    ctx: Context, run_id: str, plan_hash: str, *, fail_after: str | None = None
) -> dict[str, Any]:
    _validate_run_id(run_id)
    with nightly_lock(ctx):
        _bootstrap_control_ledger(ctx)
        pending = _pending_for_run(_load_events(ctx), run_id)
        if len(pending) != 1:
            raise MigrationError(f"expected exactly one pending intent for {run_id}; found {len(pending)}")
        payload = pending[0].get("payload") or {}
        plan = payload.get("plan") or {}
        validate_plan(plan)
        if not hmac.compare_digest(str(plan_hash), str(plan.get("plan_hash"))):
            raise MigrationError("recover plan_hash does not match pending intent")
        return _apply_locked(ctx, plan, None, fail_after=fail_after)


def _parse_evidence(values: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in values:
        key, sep, value = item.partition("=")
        if not sep or not key or not value.strip() or key in out:
            raise MigrationError(f"invalid or duplicate --evidence: {item!r}")
        out[key] = value.strip()
    return out


def _write_plan(path: Path, plan: dict[str, Any]) -> None:
    if path.exists():
        raise MigrationError(f"plan output already exists: {path}")
    _atomic_write(path, json_bytes(plan))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id")
    parser.add_argument("--reason", default="")
    parser.add_argument("--evidence", action="append", default=[], metavar="ARTIFACT=REF")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--plan-output")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--plan-file")
    parser.add_argument("--plan-hash")
    parser.add_argument("--approval-file")
    args = parser.parse_args(argv)
    ctx = Context.production()
    try:
        if sum(bool(flag) for flag in (args.plan, args.apply, args.recover, args.verify, args.selftest)) != 1:
            raise MigrationError(
                "choose exactly one of --plan, --apply, --recover, --verify or --selftest"
            )
        if args.selftest:
            env = dict(os.environ, AR_OFFLINE="1")
            result = subprocess.run(
                [sys.executable, str(REPO / "tests" / "test_publication_migration_offline.py")],
                cwd=str(REPO),
                env=env,
            )
            return result.returncode
        if args.plan:
            if not args.run_id:
                raise MigrationError("--run-id is required for --plan")
            plan = build_plan(
                ctx, args.run_id, reason=args.reason, evidence=_parse_evidence(args.evidence)
            )
            if args.plan_output:
                _write_plan(Path(args.plan_output), plan)
            print(json.dumps(plan, ensure_ascii=False, indent=1))
            return 0
        if args.apply:
            if not args.plan_file or not args.plan_hash or not args.approval_file:
                raise MigrationError(
                    "--apply requires --plan-file, --plan-hash and --approval-file"
                )
            plan = load_plan(Path(args.plan_file))
            if not hmac.compare_digest(args.plan_hash, plan["plan_hash"]):
                raise MigrationError("CLI plan_hash does not match plan file")
            approval = load_approval(Path(args.approval_file), plan, ctx.approval_key)
            print(json.dumps(apply_plan(ctx, plan, approval), ensure_ascii=False, indent=1))
            return 0
        if args.recover:
            if not args.run_id or not args.plan_hash:
                raise MigrationError("--recover requires --run-id and --plan-hash")
            print(
                json.dumps(
                    recover(ctx, args.run_id, args.plan_hash), ensure_ascii=False, indent=1
                )
            )
            return 0
        if args.verify:
            if not args.run_id:
                raise MigrationError("--run-id is required for --verify")
            problems = verify_current(ctx, args.run_id)
            print(json.dumps({"run_id": args.run_id, "problems": problems}, ensure_ascii=False, indent=1))
            return 1 if problems else 0
        parser.error("choose exactly one of --plan, --apply, --recover, --verify or --selftest")
    except MigrationError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
