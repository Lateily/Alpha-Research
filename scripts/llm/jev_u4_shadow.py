#!/usr/bin/env python3
"""Offline orchestration and immutable storage for Jev U4 shadow receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
RESEARCH_FUNNEL_ROOT = REPO_ROOT / "experiments/research_funnel"
if str(RESEARCH_FUNNEL_ROOT) not in sys.path:
    sys.path.insert(0, str(RESEARCH_FUNNEL_ROOT))

from experiments.research_funnel import u4_pre_decision, u4_shadow  # noqa: E402

from adapters import AgentRequest, Usage, run_adapter  # noqa: E402
from adapters.jev_shadow import OfflineFixtureDecisionAdapter  # noqa: E402
from capability import (  # noqa: E402
    CapabilityRecord,
    CapabilityRegistry,
    CapabilityStatus,
    RouteMode,
    RouteRequest,
    RouteStatus,
    route,
)
from typed_decision import canonical_hash, question_set_payload  # noqa: E402


REQUEST_SCHEMA = "ar.jev_u4_shadow_request.v1"
TASK_ID = "JEV-U4-SHADOW-ENGINE-001"
TASK_TYPE = "u4_shadow_decision"
KNOWN_FIXTURE_IDS = frozenset({"synthetic-mixed"})
_ARTIFACT_SCOPE = "sandbox/artifacts"
_STATE_SCOPE = "sandbox/state"
_REQUEST_FIELDS = {
    "schema",
    "command_id",
    "task_id",
    "mode",
    "observed_at",
    "packet_ref",
    "bundle_ref",
    "feature_health_ref",
    "funnel_health_ref",
    "diagnostic_ref",
    "industry",
    "method_version",
    "cyclical_flags_ref",
    "fixture_id",
}
_REF_FIELDS = (
    "packet_ref",
    "bundle_ref",
    "feature_health_ref",
    "funnel_health_ref",
    "diagnostic_ref",
)
_COMMAND_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_REF_PATTERN = re.compile(r"[A-Za-z0-9._/-]+")
_TOKEN_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
_METHOD_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{2,63}_V[0-9]+")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


class ShadowRunError(RuntimeError):
    """Stable fail-closed error surfaced by the engine, store, and CLI."""

    def __init__(
        self,
        code: str,
        *,
        status: str | None = None,
        message: str | None = None,
    ) -> None:
        self.code = code
        self.status = status or code
        self.safe_message = message or code
        label = self.code if self.status == self.code else f"{self.status}/{self.code}"
        super().__init__(label)

    def to_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "code": self.code,
            "message": self.safe_message,
        }


@dataclass(frozen=True)
class ResolvedRequestPaths:
    packet: Path
    bundle: Path
    feature_health: Path
    funnel_health: Path
    diagnostic: Path
    cyclical_flags: Path | None


def _blocked(message: str = "request is outside the approved shadow specification") -> ShadowRunError:
    return ShadowRunError("SPEC_BLOCKED", message=message)


def _live_provider_blocked() -> ShadowRunError:
    return ShadowRunError(
        "LIVE_PROVIDER_NOT_INSTALLED",
        status="SPEC_BLOCKED",
        message="live provider is not installed",
    )


def _validate_relative_ref(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or _REF_PATTERN.fullmatch(value) is None
        or "\\" in value
        or ":" in value
    ):
        raise _blocked(f"{field} must be a root-relative reference")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value.startswith(("/", "~"))
        or value.endswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise _blocked(f"{field} must be a root-relative reference")
    return path.as_posix()


def _validate_observed_at(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise _blocked("observed_at must be timezone-aware")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _blocked("observed_at must be timezone-aware") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _blocked("observed_at must be timezone-aware")
    return value


def validate_request(payload: object) -> dict[str, Any]:
    """Validate and copy the exact version-one request contract."""
    if not isinstance(payload, Mapping) or set(payload) != _REQUEST_FIELDS:
        raise _blocked("shadow request fields are not exact")
    request = dict(payload)
    if request["schema"] != REQUEST_SCHEMA:
        raise _blocked("shadow request schema is invalid")
    if request["task_id"] != TASK_ID:
        raise _blocked("shadow request task_id is invalid")
    command_id = request["command_id"]
    if not isinstance(command_id, str) or _COMMAND_PATTERN.fullmatch(command_id) is None:
        raise _blocked("command_id is invalid")

    mode = request["mode"]
    if mode == "TYPESAFE_JEV":
        raise _live_provider_blocked()
    if not isinstance(mode, str) or mode not in {
        "OFFLINE_FIXTURE",
        "POLICY_PREVIEW",
    }:
        raise _blocked("shadow request mode is not supported")

    _validate_observed_at(request["observed_at"])
    for field in _REF_FIELDS:
        request[field] = _validate_relative_ref(request[field], field)
    cyclical_ref = request["cyclical_flags_ref"]
    if cyclical_ref is not None:
        request["cyclical_flags_ref"] = _validate_relative_ref(
            cyclical_ref, "cyclical_flags_ref"
        )

    industry = request["industry"]
    if not isinstance(industry, str) or _TOKEN_PATTERN.fullmatch(industry) is None:
        raise _blocked("industry is invalid")
    method_version = request["method_version"]
    if (
        not isinstance(method_version, str)
        or _METHOD_PATTERN.fullmatch(method_version) is None
    ):
        raise _blocked("method_version is invalid")

    fixture_id = request["fixture_id"]
    if mode == "OFFLINE_FIXTURE":
        if not isinstance(fixture_id, str) or fixture_id not in KNOWN_FIXTURE_IDS:
            raise _blocked("fixture_id is not an approved synthetic fixture")
    elif fixture_id is not None:
        raise _blocked("POLICY_PREVIEW requires a null fixture_id")
    return request


def _absolute_root(root: Path | str, *, must_exist: bool) -> Path:
    path = Path(root)
    if not path.is_absolute():
        raise _blocked("root must be absolute")
    if path.is_symlink():
        raise _blocked("symlink root refused")
    if path.exists():
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise _blocked("root could not be inspected") from exc
        if not stat.S_ISDIR(mode):
            raise _blocked("root must be a directory")
    elif must_exist:
        raise _blocked("root does not exist")
    return path


def safe_ref(root: Path | str, ref: str) -> Path:
    """Resolve one existing reference without traversing any symlink below root."""
    root_path = _absolute_root(root, must_exist=True)
    normalized = _validate_relative_ref(ref, "reference")
    current = root_path
    parts = PurePosixPath(normalized).parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except (FileNotFoundError, NotADirectoryError, OSError) as exc:
            raise _blocked("referenced evidence is missing") from exc
        if stat.S_ISLNK(mode):
            raise _blocked("symlink reference refused")
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            raise _blocked("reference parent is not a directory")

    try:
        resolved_root = root_path.resolve(strict=True)
        resolved = current.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise _blocked("reference escaped the artifact root") from exc
    return resolved


def _require_kind(path: Path, *, directory: bool) -> Path:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise _blocked("referenced evidence could not be inspected") from exc
    valid = stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)
    if not valid:
        raise _blocked("referenced evidence has the wrong file type")
    return path


def resolve_request_paths(
    artifact_root: Path | str, payload: Mapping[str, Any]
) -> ResolvedRequestPaths:
    """Resolve all request evidence beneath one symlink-free artifact root."""
    root = _absolute_root(artifact_root, must_exist=True)
    return ResolvedRequestPaths(
        packet=_require_kind(safe_ref(root, payload["packet_ref"]), directory=False),
        bundle=_require_kind(safe_ref(root, payload["bundle_ref"]), directory=True),
        feature_health=_require_kind(
            safe_ref(root, payload["feature_health_ref"]), directory=False
        ),
        funnel_health=_require_kind(
            safe_ref(root, payload["funnel_health_ref"]), directory=False
        ),
        diagnostic=_require_kind(
            safe_ref(root, payload["diagnostic_ref"]), directory=False
        ),
        cyclical_flags=(
            _require_kind(
                safe_ref(root, payload["cyclical_flags_ref"]), directory=False
            )
            if payload["cyclical_flags_ref"] is not None
            else None
        ),
    )


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _decode_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"),
        parse_constant=_reject_constant,
        object_pairs_hook=_object_without_duplicates,
    )


def load_exact_json(path: Path) -> Any:
    """Load strict UTF-8 JSON from an already resolved regular file."""
    try:
        return _decode_json(_read_regular_file(path))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise _blocked("JSON evidence is invalid") from exc


def offline_capability_registry() -> CapabilityRegistry:
    """Return the sole deterministic, offline, shadow-only v1 capability."""
    return CapabilityRegistry(
        [
            CapabilityRecord(
                agent="offline_fixture",
                task_type=TASK_TYPE,
                tool_access=frozenset(),
                file_scope=(_ARTIFACT_SCOPE, _STATE_SCOPE),
                network_access=frozenset({"deny"}),
                status=CapabilityStatus.SHADOW_ONLY,
                cost_cny_per_run="0",
                eval_version=None,
                eval_score=None,
                known_failures=("LIVE_PROVIDER_NOT_INSTALLED",),
                deterministic=True,
            )
        ]
    )


def route_request(payload: Mapping[str, Any]) -> RouteRequest:
    """Project a validated request into the fixed AIOS shadow route contract."""
    request = validate_request(payload)
    artifact_targets = tuple(
        f"{_ARTIFACT_SCOPE}/{request[field]}" for field in _REF_FIELDS
    )
    if request["cyclical_flags_ref"] is not None:
        artifact_targets += (
            f"{_ARTIFACT_SCOPE}/{request['cyclical_flags_ref']}",
        )
    return RouteRequest(
        task_type=TASK_TYPE,
        mode=RouteMode.SHADOW,
        required_tools=frozenset(),
        target_paths=artifact_targets + (f"{_STATE_SCOPE}/jev-u4-shadow",),
        network_policy="deny",
        risk_level="MEDIUM",
        budget_max_cny="0",
    )


def _sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _provider_payload(adapter: object) -> dict[str, Any]:
    return {
        "name": getattr(adapter, "provider", None),
        "model": getattr(adapter, "model", None),
        "model_revision": getattr(adapter, "model_revision", None),
        "provider_contacted": False,
        "network_policy": "deny",
        "usage": Usage.not_applicable().to_dict(),
        "cost_cny": "0",
    }


def _execute_candidates_once(
    packet: Mapping[str, Any], payload: Mapping[str, Any], adapter: object
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    rows = packet.get("candidate_rows")
    if not isinstance(rows, list):
        raise _blocked("packet candidate_rows are invalid")
    for row in rows:
        gate = u4_shadow.derive_gate(row)
        if gate["state"] != "ELIGIBLE_FOR_TYPED_JUDGMENT":
            results.append(u4_shadow.compose_candidate_result(packet, row))
            continue
        state = u4_shadow.assemble_candidate_state(packet, row)
        state_hash = canonical_hash(state)
        agent_request = AgentRequest(
            task_id=payload["task_id"],
            task_type=TASK_TYPE,
            input_payload={
                "state": state,
                "state_hash": state_hash,
                "question_set": question_set_payload(),
            },
            prompt_version=question_set_payload()["version"],
            risk_level="MEDIUM",
            evidence_grade="E4",
            network_policy="deny",
        )
        provider_result = run_adapter(adapter, agent_request)
        results.append(
            u4_shadow.compose_candidate_result(
                packet,
                row,
                provider_result=provider_result,
            )
        )
    return results


def run_shadow(
    raw_request: object,
    *,
    artifact_root: Path | str,
    state_root: Path | str,
    adapter: object,
) -> dict[str, Any]:
    """Reopen evidence, route once, execute each eligible row once, and verify."""
    payload = validate_request(raw_request)
    if getattr(adapter, "provider", None) != "offline_fixture":
        if getattr(adapter, "provider", None) == "typesafe_jev":
            raise _live_provider_blocked()
        raise _blocked("only the offline fixture adapter is approved")

    try:
        _absolute_root(state_root, must_exist=False)
        paths = resolve_request_paths(artifact_root, payload)
        packet_raw = _read_regular_file(paths.packet)
        packet = _decode_json(packet_raw)
        if not isinstance(packet, Mapping):
            raise ValueError("packet must be an object")
        diagnostic = load_exact_json(paths.diagnostic)
        if (
            diagnostic != packet.get("diagnostic")
            or canonical_hash(diagnostic)
            != packet.get("source_refs", {}).get("diagnostic_report_hash")
        ):
            raise ValueError("diagnostic differs from packet binding")
        u4_pre_decision.validate_packet(
            packet,
            bundle_dir=paths.bundle,
            feature_health_path=paths.feature_health,
            funnel_health_path=paths.funnel_health,
            diagnostic_ref=payload["diagnostic_ref"],
            industry=payload["industry"],
            method_version=payload["method_version"],
            cyclical_flags_path=paths.cyclical_flags,
        )
        decision = route(offline_capability_registry(), route_request(payload))
        if decision.status is not RouteStatus.SELECTED:
            raise _blocked("offline shadow capability was not selected")
        candidate_results = _execute_candidates_once(packet, payload, adapter)
        receipt = u4_shadow.build_receipt(
            payload,
            packet,
            candidate_results,
            packet_file_hash=_sha256_bytes(packet_raw),
            provider=_provider_payload(adapter),
        )
        u4_shadow.verify_receipt(receipt)
        return receipt
    except ShadowRunError:
        raise
    except Exception as exc:
        raise _blocked("shadow evidence or receipt validation failed") from exc


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ShadowRunError("INTEGRITY_ERROR") from exc


def _read_regular_file(path: Path) -> bytes:
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise OSError("not a regular file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise OSError("file changed while opening")
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                raw = handle.read()
        finally:
            os.close(descriptor)
        return raw
    except OSError:
        raise


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class ShadowStore:
    """Crash-convergent SQLite index plus immutable canonical receipt files."""

    def __init__(
        self,
        state_root: Path | str,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.state_root = Path(state_root)
        self.base_directory = self.state_root / "jev-u4-shadow"
        self.database_path = self.base_directory / "shadow.sqlite3"
        self._fault_injector = fault_injector
        self._initialize()

    def _integrity(self, exc: Exception | None = None) -> ShadowRunError:
        error = ShadowRunError("INTEGRITY_ERROR")
        if exc is not None:
            error.__cause__ = exc
        return error

    def _assert_directory(self, path: Path) -> None:
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise self._integrity(exc)
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise self._integrity()

    def _initialize(self) -> None:
        if not self.state_root.is_absolute() or self.state_root.is_symlink():
            raise self._integrity()
        try:
            self.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._assert_directory(self.state_root)
            if self.base_directory.is_symlink():
                raise self._integrity()
            self.base_directory.mkdir(exist_ok=True, mode=0o700)
            self._assert_directory(self.base_directory)
            if self.database_path.is_symlink():
                raise self._integrity()
            with self._connect() as database:
                database.execute(
                    """
                    CREATE TABLE IF NOT EXISTS receipts (
                        command_id TEXT PRIMARY KEY,
                        request_hash TEXT NOT NULL,
                        request_bytes BLOB NOT NULL,
                        receipt_hash TEXT NOT NULL,
                        receipt_bytes BLOB NOT NULL
                    )
                    """
                )
            os.chmod(self.database_path, 0o600)
        except ShadowRunError:
            raise
        except (OSError, sqlite3.DatabaseError) as exc:
            raise self._integrity(exc) from exc

    def _connect(self) -> sqlite3.Connection:
        self._assert_directory(self.state_root)
        self._assert_directory(self.base_directory)
        if self.database_path.is_symlink():
            raise self._integrity()
        if self.database_path.exists():
            try:
                if not stat.S_ISREG(self.database_path.lstat().st_mode):
                    raise self._integrity()
            except OSError as exc:
                raise self._integrity(exc) from exc
        database = sqlite3.connect(str(self.database_path), timeout=30)
        database.execute("PRAGMA synchronous=FULL")
        database.execute("PRAGMA journal_mode=DELETE")
        return database

    def receipt_path(self, command_id: str) -> Path:
        if not isinstance(command_id, str) or _COMMAND_PATTERN.fullmatch(command_id) is None:
            raise self._integrity()
        return self.base_directory / command_id / "receipt.json"

    def _command_directory(self, command_id: str) -> Path:
        directory = self.receipt_path(command_id).parent
        if directory.is_symlink():
            raise self._integrity()
        try:
            directory.mkdir(exist_ok=True, mode=0o700)
            self._assert_directory(directory)
        except ShadowRunError:
            raise
        except OSError as exc:
            raise self._integrity(exc) from exc
        return directory

    def _fault(self, point: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(point)

    def _parse_receipt_bytes(self, raw: bytes) -> dict[str, Any]:
        try:
            receipt = _decode_json(raw)
            if not isinstance(receipt, dict):
                raise ValueError("receipt must be an object")
            if u4_shadow.canonical_receipt_bytes(receipt) != raw:
                raise ValueError("receipt bytes are not canonical")
            u4_shadow.verify_receipt(receipt)
            return receipt
        except Exception as exc:
            raise self._integrity(exc) from exc

    def _publish_or_adopt(
        self, command_id: str, receipt_bytes: bytes, receipt_hash: str
    ) -> None:
        directory = self._command_directory(command_id)
        final_path = directory / "receipt.json"
        if final_path.exists() or final_path.is_symlink():
            try:
                existing = _read_regular_file(final_path)
            except OSError as exc:
                raise self._integrity(exc) from exc
            parsed = self._parse_receipt_bytes(existing)
            if existing != receipt_bytes or parsed.get("receipt_hash") != receipt_hash:
                raise self._integrity()
            return

        descriptor, temporary_name = tempfile.mkstemp(prefix=".receipt-", dir=directory)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(receipt_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, final_path, follow_symlinks=False)
            except FileExistsError:
                existing = _read_regular_file(final_path)
                parsed = self._parse_receipt_bytes(existing)
                if existing != receipt_bytes or parsed.get("receipt_hash") != receipt_hash:
                    raise self._integrity()
            _fsync_directory(directory)
        except ShadowRunError:
            raise
        except OSError as exc:
            raise self._integrity(exc) from exc
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _validate_pair(
        self, request: Mapping[str, Any], receipt: Mapping[str, Any]
    ) -> tuple[bytes, str, bytes, str]:
        payload = validate_request(request)
        try:
            u4_shadow.verify_receipt(receipt)
        except Exception as exc:
            raise self._integrity(exc) from exc
        identity = receipt.get("identity", {})
        expected_identity = {
            "task_id": payload["task_id"],
            "command_id": payload["command_id"],
            "run_mode": payload["mode"],
            "observed_at": payload["observed_at"],
        }
        if any(identity.get(key) != value for key, value in expected_identity.items()):
            raise self._integrity()
        request_bytes = _canonical_bytes(payload)
        request_hash = canonical_hash(payload)
        receipt_bytes = u4_shadow.canonical_receipt_bytes(receipt)
        receipt_hash = receipt["receipt_hash"]
        return request_bytes, request_hash, receipt_bytes, receipt_hash

    def write(
        self, request: Mapping[str, Any], receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        request_bytes, request_hash, receipt_bytes, receipt_hash = self._validate_pair(
            request, receipt
        )
        command_id = request["command_id"]
        database: sqlite3.Connection | None = None
        try:
            database = self._connect()
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                """
                SELECT request_hash, request_bytes, receipt_hash, receipt_bytes
                FROM receipts WHERE command_id = ?
                """,
                (command_id,),
            ).fetchone()
            if row is not None:
                stored = self._verified_row(command_id, row)
                if row[0] != request_hash or bytes(row[1]) != request_bytes:
                    raise ShadowRunError("COMMAND_ID_CONFLICT")
                if row[2] != receipt_hash or bytes(row[3]) != receipt_bytes:
                    raise ShadowRunError("COMMAND_ID_CONFLICT")
                database.commit()
                return {"disposition": "IDEMPOTENT", "receipt": stored}

            self._publish_or_adopt(command_id, receipt_bytes, receipt_hash)
            self._fault("after_publish")
            database.execute(
                """
                INSERT INTO receipts
                    (command_id, request_hash, request_bytes, receipt_hash, receipt_bytes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (command_id, request_hash, request_bytes, receipt_hash, receipt_bytes),
            )
            self._fault("after_insert")
            database.commit()
            return {"disposition": "CREATED", "receipt": dict(receipt)}
        except ShadowRunError:
            if database is not None:
                database.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            if database is not None:
                database.rollback()
            raise self._integrity(exc) from exc
        except Exception:
            if database is not None:
                database.rollback()
            raise
        finally:
            if database is not None:
                database.close()

    def _verified_row(self, command_id: str, row: tuple[Any, ...]) -> dict[str, Any]:
        request_hash, request_raw, receipt_hash, receipt_raw = row
        try:
            request_bytes = bytes(request_raw)
            receipt_bytes = bytes(receipt_raw)
            request = _decode_json(request_bytes)
            payload = validate_request(request)
            if _canonical_bytes(payload) != request_bytes:
                raise ValueError("request bytes are not canonical")
            if canonical_hash(payload) != request_hash:
                raise ValueError("request hash mismatch")
            if payload["command_id"] != command_id:
                raise ValueError("request command mismatch")
            receipt = self._parse_receipt_bytes(receipt_bytes)
            if receipt.get("receipt_hash") != receipt_hash:
                raise ValueError("stored receipt hash mismatch")
            if receipt.get("identity", {}).get("command_id") != command_id:
                raise ValueError("receipt command mismatch")
            identity = receipt["identity"]
            if (
                identity["task_id"] != payload["task_id"]
                or identity["run_mode"] != payload["mode"]
                or identity["observed_at"] != payload["observed_at"]
            ):
                raise ValueError("stored request differs from receipt identity")
            disk_path = self.receipt_path(command_id)
            self._assert_directory(disk_path.parent)
            disk_bytes = _read_regular_file(disk_path)
            if disk_bytes != receipt_bytes:
                raise ValueError("disk receipt mismatch")
            return receipt
        except ShadowRunError:
            raise
        except Exception as exc:
            raise self._integrity(exc) from exc

    def read(self, command_id: str) -> dict[str, Any]:
        self.receipt_path(command_id)
        database: sqlite3.Connection | None = None
        try:
            database = self._connect()
            row = database.execute(
                """
                SELECT request_hash, request_bytes, receipt_hash, receipt_bytes
                FROM receipts WHERE command_id = ?
                """,
                (command_id,),
            ).fetchone()
            if row is None:
                raise self._integrity()
            return self._verified_row(command_id, row)
        except ShadowRunError:
            raise
        except sqlite3.DatabaseError as exc:
            raise self._integrity(exc) from exc
        finally:
            if database is not None:
                database.close()


def _load_cli_request(path: Path) -> dict[str, Any]:
    try:
        payload = _decode_json(_read_regular_file(path))
    except Exception as exc:
        raise _blocked("request JSON is invalid") from exc
    return validate_request(payload)


def _load_fixture_adapter(
    request: Mapping[str, Any], artifact_root: Path
) -> OfflineFixtureDecisionAdapter:
    if request["mode"] == "POLICY_PREVIEW":
        return OfflineFixtureDecisionAdapter({})
    cassette_path = safe_ref(artifact_root, "cassettes.json")
    payload = load_exact_json(cassette_path)
    if not isinstance(payload, dict) or payload.get("_meta", {}).get("fixture_id") != request["fixture_id"]:
        raise _blocked("fixture cassette identity is invalid")
    cassettes = {key: value for key, value in payload.items() if key != "_meta"}
    return OfflineFixtureDecisionAdapter(cassettes)


class _StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise _blocked("command arguments are invalid")


def _parser() -> argparse.ArgumentParser:
    parser = _StableArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run_command = commands.add_parser("run")
    run_command.add_argument("--request", type=Path, required=True)
    run_command.add_argument("--artifact-root", type=Path, required=True)
    run_command.add_argument("--state-root", type=Path, required=True)
    verify_command = commands.add_parser("verify")
    verify_command.add_argument("--state-root", type=Path, required=True)
    verify_command.add_argument("--command-id", required=True)
    evaluate_command = commands.add_parser("evaluate")
    evaluate_command.add_argument("--state-root", type=Path, required=True)
    evaluate_command.add_argument("--command-id", required=True)
    evaluate_command.add_argument("--ledger", type=Path, required=True)
    return parser


def _print_json(value: object, *, stream: Any) -> None:
    stream.write(_canonical_bytes(value).decode("ascii") + "\n")
    stream.flush()


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "evaluate":
            raise ShadowRunError(
                "EVALUATION_NOT_INSTALLED",
                status="SPEC_BLOCKED",
                message="evaluation is deferred to Task 6",
            )
        if args.command == "verify":
            receipt = ShadowStore(args.state_root).read(args.command_id)
            _print_json(receipt, stream=sys.stdout)
            return 0

        request = _load_cli_request(args.request)
        adapter = _load_fixture_adapter(request, args.artifact_root)
        receipt = run_shadow(
            request,
            artifact_root=args.artifact_root,
            state_root=args.state_root,
            adapter=adapter,
        )
        result = ShadowStore(args.state_root).write(request, receipt)
        _print_json(result, stream=sys.stdout)
        return 0
    except ShadowRunError as exc:
        _print_json(exc.to_dict(), stream=sys.stderr)
        return 2
    except Exception:
        error = _blocked("shadow command failed closed")
        _print_json(error.to_dict(), stream=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
