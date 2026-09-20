#!/usr/bin/env python3
"""Offline orchestration and immutable storage for Jev U4 shadow receipts."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import ctypes.util
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import secrets
import stat
import sys
import threading
import types
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


def _load_side_effect_free_adapters() -> tuple[types.ModuleType, types.ModuleType]:
    """Load only the base and Jev adapters without executing adapters/__init__.py."""
    package_name = "_jev_u4_shadow_adapters"
    package = types.ModuleType(package_name)
    package.__path__ = [str(Path(__file__).with_name("adapters"))]
    sys.modules[package_name] = package

    loaded: list[types.ModuleType] = []
    for module_name, filename in (("base", "base.py"), ("jev_shadow", "jev_shadow.py")):
        qualified = f"{package_name}.{module_name}"
        spec = importlib.util.spec_from_file_location(
            qualified,
            Path(__file__).with_name("adapters") / filename,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("offline adapter contract could not be loaded")
        module = importlib.util.module_from_spec(spec)
        sys.modules[qualified] = module
        spec.loader.exec_module(module)
        loaded.append(module)
    return loaded[0], loaded[1]


_adapter_base, _jev_adapter = _load_side_effect_free_adapters()
AgentRequest = _adapter_base.AgentRequest
AdapterOutput = _adapter_base.AdapterOutput
AdapterExecutionError = _adapter_base.AdapterExecutionError
Usage = _adapter_base.Usage
UsageStatus = _adapter_base.UsageStatus
run_adapter = _adapter_base.run_adapter
OfflineFixtureDecisionAdapter = _jev_adapter.OfflineFixtureDecisionAdapter


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
_DATABASE_LOCKS_GUARD = threading.Lock()
_DATABASE_LOCKS: dict[tuple[int, int], threading.RLock] = {}


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
    packet_bytes: bytes


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


_DIRECTORY_FLAGS = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
)
_FILE_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
)


@dataclass
class _DirectoryHandle:
    fd: int

    @property
    def identity(self) -> tuple[int, int]:
        info = os.fstat(self.fd)
        return info.st_dev, info.st_ino

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


class RetainedFile:
    """A no-path file capability that remains bound to the opened inode."""

    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor
        self._lock = threading.Lock()

    def read_bytes(self) -> bytes:
        with self._lock:
            if self._descriptor < 0:
                raise ValueError("retained file is closed")
            info = os.fstat(self._descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise OSError("retained file is not regular")
            os.lseek(self._descriptor, 0, os.SEEK_SET)
            return _read_fd(self._descriptor)

    def close(self) -> None:
        with self._lock:
            if self._descriptor >= 0:
                os.close(self._descriptor)
                self._descriptor = -1

    def __enter__(self) -> "RetainedFile":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


def _fd_path(descriptor: int) -> Path:
    proc_path = Path(f"/proc/self/fd/{descriptor}")
    if proc_path.exists():
        return Path(os.readlink(proc_path))
    get_path = getattr(fcntl, "F_GETPATH", None)
    if get_path is not None:
        raw = fcntl.fcntl(descriptor, get_path, b"\0" * 1024)
        return Path(raw.split(b"\0", 1)[0].decode())
    raise OSError("descriptor paths are unavailable on this platform")


def _open_absolute_directory(path: Path) -> int:
    descriptor = os.open(path.anchor, _DIRECTORY_FLAGS)
    try:
        for part in path.parts[1:]:
            next_descriptor = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_root(root: Path | str, *, create: bool) -> _DirectoryHandle:
    supplied = Path(root)
    if not supplied.is_absolute():
        raise _blocked("root must be one absolute non-symlink directory")
    path = Path(os.path.abspath(supplied))
    if path.is_symlink():
        raise _blocked("root must be one absolute non-symlink directory")
    missing: list[str] = []
    cursor = path
    while not os.path.lexists(cursor):
        if cursor.parent == cursor:
            raise _blocked("root has no existing parent")
        missing.append(cursor.name)
        cursor = cursor.parent
    if missing and not create:
        raise _blocked("root does not exist")
    try:
        if not missing:
            if path == Path(path.anchor):
                descriptor = _open_absolute_directory(path)
                return _DirectoryHandle(descriptor)
            parent = path.parent.resolve(strict=True)
            parent_fd = _open_absolute_directory(parent)
            try:
                descriptor = os.open(path.name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
            finally:
                os.close(parent_fd)
            return _DirectoryHandle(descriptor)

        canonical_parent = cursor.resolve(strict=True)
        descriptor = _open_absolute_directory(canonical_parent)
        for part in reversed(missing):
            os.mkdir(part, mode=0o700, dir_fd=descriptor)
            os.fsync(descriptor)
            next_descriptor = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("root is not a directory")
        return _DirectoryHandle(descriptor)
    except Exception as exc:
        try:
            os.close(descriptor)
        except (NameError, OSError):
            pass
        if isinstance(exc, ShadowRunError):
            raise
        raise _blocked("root could not be opened safely") from exc


def _open_relative(
    root_fd: int,
    ref: str,
    *,
    directory: bool,
    race_injector: Callable[[str], None] | None = None,
    event: str | None = None,
) -> int:
    normalized = _validate_relative_ref(ref, "reference")
    parts = PurePosixPath(normalized).parts
    parent_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        if event is not None and race_injector is not None:
            race_injector(event)
        flags = _DIRECTORY_FLAGS if directory else _FILE_READ_FLAGS
        result = os.open(parts[-1], flags, dir_fd=parent_fd)
        mode = os.fstat(result).st_mode
        if (directory and not stat.S_ISDIR(mode)) or (
            not directory and not stat.S_ISREG(mode)
        ):
            os.close(result)
            raise OSError("reference has the wrong file type")
        return result
    finally:
        os.close(parent_fd)


def _read_fd(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _remove_directory_contents(directory_fd: int) -> None:
    for name in os.listdir(directory_fd):
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory_fd)
            try:
                _remove_directory_contents(child_fd)
            finally:
                os.close(child_fd)
            os.rmdir(name, dir_fd=directory_fd)
        else:
            os.unlink(name, dir_fd=directory_fd)


def safe_ref(root: Path | str, ref: str) -> RetainedFile:
    """Open one root-relative regular file as a retained capability."""
    handle = _open_root(root, create=False)
    descriptor = -1
    try:
        descriptor = _open_relative(handle.fd, ref, directory=False)
        capability = RetainedFile(descriptor)
        descriptor = -1
        return capability
    except OSError as exc:
        raise _blocked("reference could not be opened safely") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        handle.close()


def _destination_parent(root_fd: int, ref: str) -> tuple[int, str]:
    parts = PurePosixPath(_validate_relative_ref(ref, "reference")).parts
    descriptor = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            next_descriptor = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor, parts[-1]
    except Exception:
        os.close(descriptor)
        raise


def _write_snapshot_file(root_fd: int, ref: str, raw: bytes) -> None:
    parent_fd, name = _destination_parent(root_fd, ref)
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        try:
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)


def _copy_snapshot_file(
    source_root_fd: int,
    destination_root_fd: int,
    ref: str,
    *,
    race_injector: Callable[[str], None] | None = None,
    event: str | None = None,
) -> bytes:
    source_fd = _open_relative(
        source_root_fd,
        ref,
        directory=False,
        race_injector=race_injector,
        event=event,
    )
    try:
        raw = _read_fd(source_fd)
    finally:
        os.close(source_fd)
    _write_snapshot_file(destination_root_fd, ref, raw)
    return raw


def _copy_directory_contents(
    source_fd: int,
    destination_fd: int,
    *,
    race_injector: Callable[[str], None] | None = None,
) -> None:
    for name in sorted(os.listdir(source_fd)):
        info = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            raise OSError("symlink in artifact bundle")
        if stat.S_ISDIR(info.st_mode):
            os.mkdir(name, mode=0o700, dir_fd=destination_fd)
            source_child = os.open(name, _DIRECTORY_FLAGS, dir_fd=source_fd)
            destination_child = os.open(name, _DIRECTORY_FLAGS, dir_fd=destination_fd)
            try:
                opened = os.fstat(source_child)
                if (
                    not stat.S_ISDIR(opened.st_mode)
                    or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                ):
                    raise OSError("artifact bundle directory changed while opening")
                _copy_directory_contents(
                    source_child,
                    destination_child,
                    race_injector=race_injector,
                )
            finally:
                os.close(source_child)
                os.close(destination_child)
        elif stat.S_ISREG(info.st_mode):
            if race_injector is not None:
                race_injector("artifact_bundle_file_statted")
            source_file = os.open(
                name,
                _FILE_READ_FLAGS | getattr(os, "O_NONBLOCK", 0),
                dir_fd=source_fd,
            )
            try:
                opened = os.fstat(source_file)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                ):
                    raise OSError("artifact bundle file changed while opening")
                raw = _read_fd(source_file)
            finally:
                os.close(source_file)
            destination_file = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=destination_fd,
            )
            try:
                view = memoryview(raw)
                while view:
                    written = os.write(destination_file, view)
                    view = view[written:]
            finally:
                os.close(destination_file)
        else:
            raise OSError("unsupported artifact bundle entry")


def _copy_snapshot_directory(
    source_root_fd: int,
    destination_root_fd: int,
    ref: str,
    *,
    race_injector: Callable[[str], None] | None = None,
) -> None:
    source_fd = _open_relative(source_root_fd, ref, directory=True)
    destination_fd = -1
    try:
        parent_fd, name = _destination_parent(destination_root_fd, ref)
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            destination_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
        _copy_directory_contents(
            source_fd,
            destination_fd,
            race_injector=race_injector,
        )
    finally:
        os.close(source_fd)
        if destination_fd >= 0:
            os.close(destination_fd)


@contextlib.contextmanager
def resolve_request_paths(
    artifact_root: Path | str,
    payload: Mapping[str, Any],
    *,
    state_root: Path | str,
    race_injector: Callable[[str], None] | None = None,
    artifact_handle: _DirectoryHandle | None = None,
    state_handle: _DirectoryHandle | None = None,
):
    """Yield a private descriptor-anchored snapshot for authoritative reopen."""
    own_artifact = artifact_handle is None
    own_state = state_handle is None
    artifact = artifact_handle or _open_root(artifact_root, create=False)
    state = state_handle or _open_root(state_root, create=True)
    snapshot_name = f".jev-u4-shadow-reopen-{secrets.token_hex(12)}"
    snapshot_fd = -1
    snapshot_path: Path | None = None
    try:
        os.mkdir(snapshot_name, mode=0o700, dir_fd=state.fd)
        os.fsync(state.fd)
        snapshot_fd = os.open(snapshot_name, _DIRECTORY_FLAGS, dir_fd=state.fd)
        packet_raw = _copy_snapshot_file(
            artifact.fd,
            snapshot_fd,
            payload["packet_ref"],
            race_injector=race_injector,
            event="artifact_packet_parent_opened",
        )
        _copy_snapshot_directory(
            artifact.fd,
            snapshot_fd,
            payload["bundle_ref"],
            race_injector=race_injector,
        )
        for field in ("feature_health_ref", "funnel_health_ref", "diagnostic_ref"):
            _copy_snapshot_file(artifact.fd, snapshot_fd, payload[field])
        if payload["cyclical_flags_ref"] is not None:
            _copy_snapshot_file(
                artifact.fd, snapshot_fd, payload["cyclical_flags_ref"]
            )
        snapshot_path = _fd_path(snapshot_fd)
        yield ResolvedRequestPaths(
            packet=snapshot_path / payload["packet_ref"],
            bundle=snapshot_path / payload["bundle_ref"],
            feature_health=snapshot_path / payload["feature_health_ref"],
            funnel_health=snapshot_path / payload["funnel_health_ref"],
            diagnostic=snapshot_path / payload["diagnostic_ref"],
            cyclical_flags=(
                snapshot_path / payload["cyclical_flags_ref"]
                if payload["cyclical_flags_ref"] is not None
                else None
            ),
            packet_bytes=packet_raw,
        )
    except ShadowRunError:
        raise
    except Exception as exc:
        raise _blocked("artifact snapshot could not be opened safely") from exc
    finally:
        if snapshot_fd >= 0:
            try:
                _remove_directory_contents(snapshot_fd)
                current = os.stat(
                    snapshot_name, dir_fd=state.fd, follow_symlinks=False
                )
                opened = os.fstat(snapshot_fd)
                if (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino):
                    os.rmdir(snapshot_name, dir_fd=state.fd)
            except OSError:
                pass
            os.close(snapshot_fd)
        if own_artifact:
            artifact.close()
        if own_state:
            state.close()


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


def _root_scope(prefix: str, handle: _DirectoryHandle) -> str:
    device, inode = handle.identity
    identity = hashlib.sha256(f"{device}:{inode}".encode("ascii")).hexdigest()
    return f"{prefix}/{identity}"


def _offline_capability_registry(
    artifact: _DirectoryHandle, state: _DirectoryHandle
) -> CapabilityRegistry:
    artifact_scope = _root_scope(_ARTIFACT_SCOPE, artifact)
    state_scope = _root_scope(_STATE_SCOPE, state)
    return CapabilityRegistry(
        [
            CapabilityRecord(
                agent="offline_fixture",
                task_type=TASK_TYPE,
                tool_access=frozenset(),
                file_scope=(artifact_scope, state_scope),
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


def offline_capability_registry(
    *, artifact_root: Path | str, state_root: Path | str
) -> CapabilityRegistry:
    """Return the offline capability bound to two supplied root objects."""
    artifact: _DirectoryHandle | None = None
    state: _DirectoryHandle | None = None
    try:
        artifact = _open_root(artifact_root, create=False)
        state = _open_root(state_root, create=True)
        return _offline_capability_registry(artifact, state)
    finally:
        if artifact is not None:
            artifact.close()
        if state is not None:
            state.close()


def _route_request(
    payload: Mapping[str, Any], artifact: _DirectoryHandle, state: _DirectoryHandle
) -> RouteRequest:
    request = validate_request(payload)
    artifact_scope = _root_scope(_ARTIFACT_SCOPE, artifact)
    state_scope = _root_scope(_STATE_SCOPE, state)
    artifact_targets = tuple(
        f"{artifact_scope}/{request[field]}" for field in _REF_FIELDS
    )
    if request["cyclical_flags_ref"] is not None:
        artifact_targets += (
            f"{artifact_scope}/{request['cyclical_flags_ref']}",
        )
    return RouteRequest(
        task_type=TASK_TYPE,
        mode=RouteMode.SHADOW,
        required_tools=frozenset(),
        target_paths=artifact_targets + (f"{state_scope}/jev-u4-shadow",),
        network_policy="deny",
        risk_level="MEDIUM",
        budget_max_cny="0",
    )


def route_request(
    payload: Mapping[str, Any], *, artifact_root: Path | str, state_root: Path | str
) -> RouteRequest:
    """Project a request into a route bound to the supplied root objects."""
    artifact: _DirectoryHandle | None = None
    state: _DirectoryHandle | None = None
    try:
        artifact = _open_root(artifact_root, create=False)
        state = _open_root(state_root, create=True)
        return _route_request(payload, artifact, state)
    finally:
        if artifact is not None:
            artifact.close()
        if state is not None:
            state.close()


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


def _usage_from_adapter(value: object) -> object:
    if isinstance(value, Usage):
        return value
    to_dict = getattr(value, "to_dict", None)
    if not callable(to_dict):
        raise TypeError("adapter usage is invalid")
    payload = to_dict()
    return Usage(
        status=UsageStatus(payload["status"]),
        input_tokens=payload["input_tokens"],
        cached_input_tokens=payload["cached_input_tokens"],
        output_tokens=payload["output_tokens"],
        estimated_cost_cny=payload["estimated_cost_cny"],
    )


class _AdapterBridge:
    def __init__(self, delegate: object) -> None:
        self._delegate = delegate
        self.provider = getattr(delegate, "provider", "unknown")
        self.model = getattr(delegate, "model", None)

    def execute(self, request: object) -> object:
        try:
            output = self._delegate.execute(request)
        except Exception as exc:
            if all(
                hasattr(exc, name)
                for name in ("code", "safe_message", "retryable", "usage")
            ):
                raise AdapterExecutionError(
                    code=exc.code,
                    message=exc.safe_message,
                    retryable=exc.retryable,
                    usage=_usage_from_adapter(exc.usage),
                ) from exc
            raise
        if isinstance(output, AdapterOutput):
            return output
        return AdapterOutput(
            output=output.output,
            usage=_usage_from_adapter(output.usage),
            evidence_refs=tuple(output.evidence_refs),
        )


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
        provider_result = run_adapter(_AdapterBridge(adapter), agent_request)
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
    race_injector: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Reopen evidence, route once, execute each eligible row once, and verify."""
    payload = validate_request(raw_request)
    if getattr(adapter, "provider", None) != "offline_fixture":
        if getattr(adapter, "provider", None) == "typesafe_jev":
            raise _live_provider_blocked()
        raise _blocked("only the offline fixture adapter is approved")

    artifact: _DirectoryHandle | None = None
    state: _DirectoryHandle | None = None
    try:
        artifact = _open_root(artifact_root, create=False)
        state = _open_root(state_root, create=True)
        with resolve_request_paths(
            artifact_root,
            payload,
            state_root=state_root,
            race_injector=race_injector,
            artifact_handle=artifact,
            state_handle=state,
        ) as paths:
            packet_raw = paths.packet_bytes
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
            decision = route(
                _offline_capability_registry(artifact, state),
                _route_request(payload, artifact, state),
            )
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
    finally:
        if artifact is not None:
            artifact.close()
        if state is not None:
            state.close()


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
        descriptor = os.open(path, _FILE_READ_FLAGS)
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


class _SQLiteImageError(RuntimeError):
    pass


def _load_sqlite_library() -> ctypes.CDLL:
    library_name = ctypes.util.find_library("sqlite3")
    if library_name is None:
        raise RuntimeError("system SQLite library is unavailable")
    library = ctypes.CDLL(library_name)
    pointer = ctypes.c_void_p
    integer = ctypes.c_int
    int64 = ctypes.c_longlong

    library.sqlite3_open_v2.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(pointer),
        integer,
        ctypes.c_char_p,
    ]
    library.sqlite3_open_v2.restype = integer
    library.sqlite3_close.argtypes = [pointer]
    library.sqlite3_close.restype = integer
    library.sqlite3_errmsg.argtypes = [pointer]
    library.sqlite3_errmsg.restype = ctypes.c_char_p
    library.sqlite3_exec.argtypes = [
        pointer,
        ctypes.c_char_p,
        pointer,
        pointer,
        ctypes.POINTER(ctypes.c_char_p),
    ]
    library.sqlite3_exec.restype = integer
    library.sqlite3_prepare_v2.argtypes = [
        pointer,
        ctypes.c_char_p,
        integer,
        ctypes.POINTER(pointer),
        ctypes.POINTER(ctypes.c_char_p),
    ]
    library.sqlite3_prepare_v2.restype = integer
    library.sqlite3_bind_text.argtypes = [
        pointer,
        integer,
        ctypes.c_char_p,
        integer,
        pointer,
    ]
    library.sqlite3_bind_text.restype = integer
    library.sqlite3_bind_blob.argtypes = [
        pointer,
        integer,
        pointer,
        integer,
        pointer,
    ]
    library.sqlite3_bind_blob.restype = integer
    library.sqlite3_step.argtypes = [pointer]
    library.sqlite3_step.restype = integer
    library.sqlite3_finalize.argtypes = [pointer]
    library.sqlite3_finalize.restype = integer
    library.sqlite3_column_count.argtypes = [pointer]
    library.sqlite3_column_count.restype = integer
    library.sqlite3_column_type.argtypes = [pointer, integer]
    library.sqlite3_column_type.restype = integer
    library.sqlite3_column_text.argtypes = [pointer, integer]
    library.sqlite3_column_text.restype = pointer
    library.sqlite3_column_blob.argtypes = [pointer, integer]
    library.sqlite3_column_blob.restype = pointer
    library.sqlite3_column_bytes.argtypes = [pointer, integer]
    library.sqlite3_column_bytes.restype = integer
    library.sqlite3_serialize.argtypes = [
        pointer,
        ctypes.c_char_p,
        ctypes.POINTER(int64),
        ctypes.c_uint,
    ]
    library.sqlite3_serialize.restype = pointer
    library.sqlite3_deserialize.argtypes = [
        pointer,
        ctypes.c_char_p,
        pointer,
        int64,
        int64,
        ctypes.c_uint,
    ]
    library.sqlite3_deserialize.restype = integer
    library.sqlite3_malloc64.argtypes = [ctypes.c_ulonglong]
    library.sqlite3_malloc64.restype = pointer
    library.sqlite3_free.argtypes = [pointer]
    library.sqlite3_free.restype = None
    return library


_SQLITE = _load_sqlite_library()
_SQLITE_OK = 0
_SQLITE_ROW = 100
_SQLITE_DONE = 101
_SQLITE_OPEN_READWRITE = 0x00000002
_SQLITE_OPEN_CREATE = 0x00000004
_SQLITE_OPEN_MEMORY = 0x00000080
_SQLITE_INTEGER = 1
_SQLITE_FLOAT = 2
_SQLITE_TEXT = 3
_SQLITE_BLOB = 4
_SQLITE_NULL = 5
_SQLITE_DESERIALIZE_FREEONCLOSE = 1
_SQLITE_DESERIALIZE_RESIZEABLE = 2
_SQLITE_TRANSIENT = ctypes.c_void_p(-1)


class _SQLiteResult:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class _SQLiteImageDatabase:
    """A SQLite connection whose complete state lives in memory."""

    def __init__(self, raw: bytes | None) -> None:
        self._database = ctypes.c_void_p()
        result = _SQLITE.sqlite3_open_v2(
            b":memory:",
            ctypes.byref(self._database),
            _SQLITE_OPEN_READWRITE | _SQLITE_OPEN_CREATE | _SQLITE_OPEN_MEMORY,
            None,
        )
        if result != _SQLITE_OK:
            self._raise(result)
        if raw is not None:
            capacity = max(len(raw) + 65536, len(raw) * 2)
            memory = _SQLITE.sqlite3_malloc64(capacity)
            if not memory:
                self.close()
                raise _SQLiteImageError("SQLite image allocation failed")
            ctypes.memmove(memory, raw, len(raw))
            result = _SQLITE.sqlite3_deserialize(
                self._database,
                b"main",
                memory,
                len(raw),
                capacity,
                _SQLITE_DESERIALIZE_FREEONCLOSE
                | _SQLITE_DESERIALIZE_RESIZEABLE,
            )
            if result != _SQLITE_OK:
                self.close()
                raise _SQLiteImageError(f"SQLite image deserialize failed: {result}")

    def _message(self) -> str:
        if not self._database:
            return "SQLite connection is closed"
        raw = _SQLITE.sqlite3_errmsg(self._database)
        return raw.decode("utf-8", "replace") if raw else "SQLite error"

    def _raise(self, result: int) -> None:
        raise _SQLiteImageError(f"SQLite error {result}: {self._message()}")

    def _exec(self, statement: str) -> None:
        result = _SQLITE.sqlite3_exec(
            self._database,
            statement.encode("utf-8"),
            None,
            None,
            None,
        )
        if result != _SQLITE_OK:
            self._raise(result)

    def execute(
        self, statement: str, parameters: tuple[Any, ...] = ()
    ) -> _SQLiteResult:
        prepared = ctypes.c_void_p()
        result = _SQLITE.sqlite3_prepare_v2(
            self._database,
            statement.encode("utf-8"),
            -1,
            ctypes.byref(prepared),
            None,
        )
        if result != _SQLITE_OK:
            self._raise(result)
        buffers: list[object] = []
        try:
            for index, value in enumerate(parameters, start=1):
                if isinstance(value, str):
                    encoded = value.encode("utf-8")
                    result = _SQLITE.sqlite3_bind_text(
                        prepared,
                        index,
                        encoded,
                        len(encoded),
                        _SQLITE_TRANSIENT,
                    )
                elif isinstance(value, (bytes, bytearray, memoryview)):
                    encoded = bytes(value)
                    buffer = ctypes.create_string_buffer(encoded, max(1, len(encoded)))
                    buffers.append(buffer)
                    result = _SQLITE.sqlite3_bind_blob(
                        prepared,
                        index,
                        ctypes.cast(buffer, ctypes.c_void_p),
                        len(encoded),
                        _SQLITE_TRANSIENT,
                    )
                else:
                    raise TypeError("unsupported SQLite parameter")
                if result != _SQLITE_OK:
                    self._raise(result)

            result = _SQLITE.sqlite3_step(prepared)
            if result == _SQLITE_DONE:
                return _SQLiteResult(None)
            if result != _SQLITE_ROW:
                self._raise(result)
            row = tuple(
                self._column(prepared, index)
                for index in range(_SQLITE.sqlite3_column_count(prepared))
            )
            result = _SQLITE.sqlite3_step(prepared)
            if result == _SQLITE_ROW:
                raise _SQLiteImageError("SQLite query returned multiple rows")
            if result != _SQLITE_DONE:
                self._raise(result)
            return _SQLiteResult(row)
        finally:
            _SQLITE.sqlite3_finalize(prepared)

    def _column(self, statement: ctypes.c_void_p, index: int) -> Any:
        kind = _SQLITE.sqlite3_column_type(statement, index)
        if kind == _SQLITE_NULL:
            return None
        if kind in {_SQLITE_INTEGER, _SQLITE_FLOAT}:
            raise _SQLiteImageError("unexpected numeric SQLite value")
        size = _SQLITE.sqlite3_column_bytes(statement, index)
        if kind == _SQLITE_TEXT:
            pointer = _SQLITE.sqlite3_column_text(statement, index)
            return ctypes.string_at(pointer, size).decode("utf-8")
        if kind == _SQLITE_BLOB:
            pointer = _SQLITE.sqlite3_column_blob(statement, index)
            return ctypes.string_at(pointer, size)
        raise _SQLiteImageError("unexpected SQLite value type")

    def commit(self) -> None:
        self._exec("COMMIT")

    def rollback(self) -> None:
        self._exec("ROLLBACK")

    def serialize(self) -> bytes:
        size = ctypes.c_longlong()
        pointer = _SQLITE.sqlite3_serialize(
            self._database, b"main", ctypes.byref(size), 0
        )
        if not pointer:
            raise _SQLiteImageError("SQLite image serialization failed")
        try:
            return ctypes.string_at(pointer, size.value)
        finally:
            _SQLITE.sqlite3_free(pointer)

    def close(self) -> None:
        if self._database:
            result = _SQLITE.sqlite3_close(self._database)
            self._database = ctypes.c_void_p()
            if result != _SQLITE_OK:
                raise _SQLiteImageError(f"SQLite close failed: {result}")


def _database_process_lock(identity: tuple[int, int]) -> threading.RLock:
    with _DATABASE_LOCKS_GUARD:
        lock = _DATABASE_LOCKS.get(identity)
        if lock is None:
            lock = threading.RLock()
            _DATABASE_LOCKS[identity] = lock
        return lock


class ShadowStore:
    """Crash-convergent SQLite index plus immutable canonical receipt files."""

    def __init__(
        self,
        state_root: Path | str,
        *,
        fault_injector: Callable[[str], None] | None = None,
        race_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.state_root = Path(state_root)
        self._fault_injector = fault_injector
        self._race_injector = race_injector
        self._state_handle: _DirectoryHandle | None = None
        self._base_handle: _DirectoryHandle | None = None
        self._database_lock: threading.RLock | None = None
        self._lock_fd = -1
        try:
            self._initialize()
        except Exception:
            self.close()
            raise

    @property
    def base_directory(self) -> Path:
        if self._base_handle is None:
            raise self._integrity()
        try:
            return _fd_path(self._base_handle.fd)
        except OSError as exc:
            raise self._integrity(exc) from exc

    @property
    def database_path(self) -> Path:
        return self.base_directory / "shadow.sqlite3"

    def close(self) -> None:
        if self._lock_fd >= 0:
            os.close(self._lock_fd)
            self._lock_fd = -1
        if self._base_handle is not None:
            self._base_handle.close()
            self._base_handle = None
        if self._state_handle is not None:
            self._state_handle.close()
            self._state_handle = None

    def __del__(self) -> None:
        self.close()

    def _integrity(self, exc: Exception | None = None) -> ShadowRunError:
        error = ShadowRunError("INTEGRITY_ERROR")
        if exc is not None:
            error.__cause__ = exc
        return error

    def _initialize(self) -> None:
        try:
            self._state_handle = _open_root(self.state_root, create=True)
            try:
                os.mkdir("jev-u4-shadow", mode=0o700, dir_fd=self._state_handle.fd)
                os.fsync(self._state_handle.fd)
            except FileExistsError:
                pass
            self._base_handle = _DirectoryHandle(
                os.open("jev-u4-shadow", _DIRECTORY_FLAGS, dir_fd=self._state_handle.fd)
            )
            lock_created = False
            try:
                self._lock_fd = os.open(
                    ".shadow.lock",
                    os.O_RDWR
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=self._base_handle.fd,
                )
                lock_created = True
            except FileExistsError:
                self._lock_fd = os.open(
                    ".shadow.lock",
                    os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=self._base_handle.fd,
                )
            lock_info = os.fstat(self._lock_fd)
            if not stat.S_ISREG(lock_info.st_mode):
                raise OSError("database lock is not a regular file")
            os.fchmod(self._lock_fd, 0o600)
            if lock_created:
                os.fsync(self._base_handle.fd)
            self._database_lock = _database_process_lock(
                (lock_info.st_dev, lock_info.st_ino)
            )
            with self._connect(write=True, allow_missing=True) as database:
                database.execute("BEGIN IMMEDIATE")
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
                database.commit()
        except ShadowRunError as exc:
            raise self._integrity(exc) from exc
        except Exception as exc:
            raise self._integrity(exc) from exc

    def _lock_name_still_bound(self) -> None:
        if self._base_handle is None or self._lock_fd < 0:
            raise self._integrity()
        descriptor = -1
        try:
            descriptor = os.open(
                ".shadow.lock",
                os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=self._base_handle.fd,
            )
            expected = os.fstat(self._lock_fd)
            current = os.fstat(descriptor)
            if (expected.st_dev, expected.st_ino) != (current.st_dev, current.st_ino):
                raise self._integrity()
        except ShadowRunError:
            raise
        except OSError as exc:
            raise self._integrity(exc) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _read_database_bytes(
        self, *, allow_missing: bool
    ) -> tuple[bytes | None, tuple[int, int] | None]:
        if self._base_handle is None:
            raise self._integrity()
        descriptor = -1
        try:
            try:
                descriptor = os.open(
                    "shadow.sqlite3", _FILE_READ_FLAGS, dir_fd=self._base_handle.fd
                )
            except FileNotFoundError:
                if allow_missing:
                    return None, None
                raise
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise OSError("database is not a regular file")
            raw = _read_fd(descriptor)
            if not raw:
                raise OSError("database is empty")
            return raw, (info.st_dev, info.st_ino)
        except ShadowRunError:
            raise
        except OSError as exc:
            raise self._integrity(exc) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _database_name_still_bound(self, expected: tuple[int, int]) -> None:
        if self._base_handle is None:
            raise self._integrity()
        descriptor = -1
        try:
            descriptor = os.open(
                "shadow.sqlite3", _FILE_READ_FLAGS, dir_fd=self._base_handle.fd
            )
            current = os.fstat(descriptor)
            if (current.st_dev, current.st_ino) != expected:
                raise self._integrity()
        except ShadowRunError:
            raise
        except OSError as exc:
            raise self._integrity(exc) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _persist_database(
        self, raw: bytes, expected: tuple[int, int] | None
    ) -> None:
        if self._base_handle is None:
            raise self._integrity()
        temporary_name = f".shadow.sqlite3-{secrets.token_hex(16)}"
        descriptor = -1
        published = False
        try:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=self._base_handle.fd,
            )
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
            self._fault("after_database_temp_fsync")
            os.close(descriptor)
            descriptor = -1

            if expected is None:
                os.link(
                    temporary_name,
                    "shadow.sqlite3",
                    src_dir_fd=self._base_handle.fd,
                    dst_dir_fd=self._base_handle.fd,
                    follow_symlinks=False,
                )
                published = True
            else:
                self._database_name_still_bound(expected)
                os.rename(
                    temporary_name,
                    "shadow.sqlite3",
                    src_dir_fd=self._base_handle.fd,
                    dst_dir_fd=self._base_handle.fd,
                )
                published = True
            self._fault("after_database_publish")
            os.fsync(self._base_handle.fd)
        except ShadowRunError:
            raise
        except OSError as exc:
            raise self._integrity(exc) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if not published or expected is None:
                try:
                    os.unlink(temporary_name, dir_fd=self._base_handle.fd)
                except FileNotFoundError:
                    pass

    @contextlib.contextmanager
    def _connect(self, *, write: bool, allow_missing: bool = False):
        if self._database_lock is None or self._lock_fd < 0:
            raise self._integrity()
        database: _SQLiteImageDatabase | None = None
        locked = False
        with self._database_lock:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
                locked = True
                self._lock_name_still_bound()
                self._race("database_parent_opened")
                self._lock_name_still_bound()
                raw, identity = self._read_database_bytes(
                    allow_missing=allow_missing
                )
                database = _SQLiteImageDatabase(raw)
                yield database
                if write:
                    self._lock_name_still_bound()
                    self._persist_database(database.serialize(), identity)
            except ShadowRunError:
                raise
            except (OSError, _SQLiteImageError) as exc:
                raise self._integrity(exc) from exc
            finally:
                if database is not None:
                    try:
                        database.close()
                    except _SQLiteImageError:
                        pass
                if locked:
                    fcntl.flock(self._lock_fd, fcntl.LOCK_UN)

    def receipt_path(self, command_id: str) -> Path:
        self._validate_command_id(command_id)
        return self.base_directory / command_id / "receipt.json"

    def _validate_command_id(self, command_id: object) -> str:
        if not isinstance(command_id, str) or _COMMAND_PATTERN.fullmatch(command_id) is None:
            raise self._integrity()
        return command_id

    def _command_directory(
        self, command_id: str, *, create: bool
    ) -> tuple[int, tuple[int, int]]:
        command_id = self._validate_command_id(command_id)
        if self._base_handle is None:
            raise self._integrity()
        try:
            if create:
                try:
                    os.mkdir(command_id, mode=0o700, dir_fd=self._base_handle.fd)
                    os.fsync(self._base_handle.fd)
                    self._fault("after_command_directory_fsync")
                except FileExistsError:
                    pass
            descriptor = os.open(
                command_id, _DIRECTORY_FLAGS, dir_fd=self._base_handle.fd
            )
            info = os.fstat(descriptor)
            return descriptor, (info.st_dev, info.st_ino)
        except OSError as exc:
            raise self._integrity(exc) from exc

    def _fault(self, point: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(point)

    def _race(self, point: str) -> None:
        if self._race_injector is not None:
            self._race_injector(point)

    def _read_named_file(self, directory_fd: int, name: str) -> bytes:
        descriptor = os.open(name, _FILE_READ_FLAGS, dir_fd=directory_fd)
        try:
            return _read_fd(descriptor)
        finally:
            os.close(descriptor)

    def _command_name_still_bound(
        self, command_id: str, expected: tuple[int, int]
    ) -> None:
        if self._base_handle is None:
            raise self._integrity()
        descriptor = -1
        try:
            descriptor = os.open(
                command_id, _DIRECTORY_FLAGS, dir_fd=self._base_handle.fd
            )
            info = os.fstat(descriptor)
            if (info.st_dev, info.st_ino) != expected:
                raise self._integrity()
        except ShadowRunError:
            raise
        except OSError as exc:
            raise self._integrity(exc) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

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
        directory_fd, identity = self._command_directory(command_id, create=True)
        temporary_name: str | None = None
        try:
            self._race("receipt_parent_opened")
            try:
                existing = self._read_named_file(directory_fd, "receipt.json")
            except FileNotFoundError:
                existing = None
            except OSError as exc:
                raise self._integrity(exc) from exc
            if existing is not None:
                parsed = self._parse_receipt_bytes(existing)
                if existing != receipt_bytes or parsed.get("receipt_hash") != receipt_hash:
                    raise self._integrity()
                self._command_name_still_bound(command_id, identity)
                return

            temporary_name = f".receipt-{secrets.token_hex(16)}"
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            try:
                view = memoryview(receipt_bytes)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            try:
                os.link(
                    temporary_name,
                    "receipt.json",
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                existing = self._read_named_file(directory_fd, "receipt.json")
                parsed = self._parse_receipt_bytes(existing)
                if existing != receipt_bytes or parsed.get("receipt_hash") != receipt_hash:
                    raise self._integrity()
            os.fsync(directory_fd)
            self._command_name_still_bound(command_id, identity)
        except ShadowRunError:
            raise
        except OSError as exc:
            raise self._integrity(exc) from exc
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
            os.close(directory_fd)

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
        if identity.get("request_hash") != request_hash:
            raise self._integrity()
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
        try:
            with self._connect(write=True) as database:
                database.execute("BEGIN IMMEDIATE")
                try:
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
                except Exception:
                    database.rollback()
                    raise
        except _SQLiteImageError as exc:
            raise self._integrity(exc) from exc

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
                or identity["request_hash"] != request_hash
            ):
                raise ValueError("stored request differs from receipt identity")
            directory_fd, _identity = self._command_directory(command_id, create=False)
            try:
                disk_bytes = self._read_named_file(directory_fd, "receipt.json")
            finally:
                os.close(directory_fd)
            if disk_bytes != receipt_bytes:
                raise ValueError("disk receipt mismatch")
            return receipt
        except ShadowRunError:
            raise
        except Exception as exc:
            raise self._integrity(exc) from exc

    def read(self, command_id: str) -> dict[str, Any]:
        self._validate_command_id(command_id)
        try:
            with self._connect(write=False) as database:
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
        except _SQLiteImageError as exc:
            raise self._integrity(exc) from exc


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
    artifact = _open_root(artifact_root, create=False)
    descriptor = -1
    try:
        descriptor = _open_relative(artifact.fd, "cassettes.json", directory=False)
        payload = _decode_json(_read_fd(descriptor))
    except Exception as exc:
        raise _blocked("fixture cassette is invalid") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        artifact.close()
    if not isinstance(payload, dict) or payload.get("_meta", {}).get("fixture_id") != request["fixture_id"]:
        raise _blocked("fixture cassette identity is invalid")
    cassettes = {key: value for key, value in payload.items() if key != "_meta"}
    return OfflineFixtureDecisionAdapter(cassettes)


class _StableArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)

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
