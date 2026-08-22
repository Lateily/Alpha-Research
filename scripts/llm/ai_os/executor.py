"""Side-effect-free isolation planning for AIOS Harness A-015a.

This module validates an isolated run before any shell command, worktree,
provider, or filesystem mutation is allowed.  It deliberately stops at a
deterministic plan; the later A-015 runner must consume the plan without
weakening these guards.

The planner validates the shape and binding of a commit SHA but does not prove
that the object exists or belongs to the requested branch.  That requires the
later Git-aware runner and remains outside this side-effect-free slice.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any


COMMIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9#._-]+\Z")
SECRET_LIKE_PATTERNS = (
    re.compile(r"(?i)\bsk(?:_live)?[-_][a-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\bgh[opsur]_[a-z0-9_]{20,}\b"),
    re.compile(r"(?i)\bgithub_pat_[a-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"(?i)\bxox[baprs]-[a-z0-9-]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |)PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY)\s*=\s*"
        r"[\"'][^\"'\r\n]{16,}[\"']"
    ),
)
WINDOWS_RESERVED_COMPONENT_RE = re.compile(
    r"(?i)(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9]|LPT[1-9])"
    r"(?:\..*)?\Z"
)
PROTECTED_BRANCHES = {"main", "master", "refs/heads/main", "refs/heads/master"}
FORBIDDEN_SCOPES = (".git", "experiments/execution_tracker")
WORKTREE_ROOT = ".ar/ai-os/worktrees"


class IsolationStatus(str, Enum):
    READY = "READY"
    SPEC_BLOCKED = "SPEC_BLOCKED"
    POLICY_BLOCKED = "POLICY_BLOCKED"


@dataclass(frozen=True)
class IsolationRequest:
    task_id: str
    run_id: str
    branch: str
    commit_sha: str
    file_scope: tuple[str, ...]
    target_paths: tuple[str, ...]
    allowed_tools: frozenset[str]
    requested_tools: frozenset[str]
    timeout_seconds: int
    network_policy: str
    risk_level: str
    mode: str

    def spec_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if _contains_secret_like_value(
            (
                self.task_id,
                self.run_id,
                self.branch,
                self.commit_sha,
                self.file_scope,
                self.target_paths,
                self.allowed_tools,
                self.requested_tools,
                self.network_policy,
                self.risk_level,
                self.mode,
            )
        ):
            errors.append("request contains a secret-like value")
        if not _safe_identifier(self.task_id):
            errors.append("task_id must be a safe non-empty identifier")
        if not _safe_identifier(self.run_id):
            errors.append("run_id must be a safe path component")
        if not _valid_branch(self.branch):
            errors.append("branch must be a valid non-empty branch name")
        if not isinstance(self.commit_sha, str) or not COMMIT_SHA_RE.fullmatch(
            self.commit_sha
        ):
            errors.append("commit_sha must be a lowercase full commit SHA")

        errors.extend(_path_collection_errors("file_scope", self.file_scope, False))
        errors.extend(
            _path_collection_errors(
                "target_paths",
                self.target_paths,
                False,
                reject_overlaps=True,
            )
        )
        errors.extend(_tool_collection_errors("allowed_tools", self.allowed_tools))
        errors.extend(_tool_collection_errors("requested_tools", self.requested_tools))

        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int)
            or self.timeout_seconds <= 0
        ):
            errors.append("timeout_seconds must be a positive integer")
        if not isinstance(self.network_policy, str) or not self.network_policy:
            errors.append("network_policy must be a non-empty string")
        if not isinstance(self.risk_level, str) or not self.risk_level:
            errors.append("risk_level must be a non-empty string")
        if not isinstance(self.mode, str) or not self.mode:
            errors.append("mode must be a non-empty string")
        return tuple(errors)


@dataclass(frozen=True)
class IsolationPlan:
    task_id: str
    run_id: str
    branch: str
    worktree: str
    commit_sha: str
    file_scope: tuple[str, ...]
    target_paths: tuple[str, ...]
    tools: tuple[str, ...]
    timeout_seconds: int
    network_policy: str
    risk_level: str
    mode: str
    cleanup_policy: str
    plan_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "branch": self.branch,
            "worktree": self.worktree,
            "commit_sha": self.commit_sha,
            "file_scope": list(self.file_scope),
            "target_paths": list(self.target_paths),
            "tools": list(self.tools),
            "timeout_seconds": self.timeout_seconds,
            "network_policy": self.network_policy,
            "risk_level": self.risk_level,
            "mode": self.mode,
            "cleanup_policy": self.cleanup_policy,
            "plan_hash": self.plan_hash,
        }


@dataclass(frozen=True)
class IsolationResult:
    status: IsolationStatus
    plan: IsolationPlan | None
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "plan": self.plan.to_dict() if self.plan else None,
            "reasons": list(self.reasons),
        }


def build_isolation_plan(request: IsolationRequest) -> IsolationResult:
    """Validate one LOW/SHADOW offline run and return an immutable plan."""

    if not isinstance(request, IsolationRequest):
        return IsolationResult(
            IsolationStatus.SPEC_BLOCKED,
            None,
            ("request must be an IsolationRequest",),
        )

    spec_errors = request.spec_errors()
    if spec_errors:
        return IsolationResult(IsolationStatus.SPEC_BLOCKED, None, spec_errors)

    file_scope = tuple(
        sorted(
            (_normalize_path(item) for item in request.file_scope),
            key=_comparison_path,
        )
    )
    target_paths = tuple(
        sorted(
            (_normalize_path(item) for item in request.target_paths),
            key=_comparison_path,
        )
    )
    policy_errors: list[str] = []

    if _branch_identity(request.branch) in PROTECTED_BRANCHES:
        policy_errors.append("protected branches cannot be isolation targets")
    if request.risk_level != "LOW":
        policy_errors.append("A-015a only permits LOW risk")
    if request.mode != "SHADOW":
        policy_errors.append("A-015a only permits SHADOW mode")
    if request.network_policy != "deny":
        policy_errors.append("A-015a requires network_policy=deny")
    if _contains_forbidden_scope(file_scope):
        policy_errors.append("file_scope overlaps a forbidden scope")
    if not all(_path_is_within(path, file_scope) for path in target_paths):
        policy_errors.append("target_paths must stay within file_scope")
    if not request.requested_tools <= request.allowed_tools:
        policy_errors.append("requested_tools exceed allowed_tools")

    if policy_errors:
        return IsolationResult(
            IsolationStatus.POLICY_BLOCKED,
            None,
            tuple(policy_errors),
        )

    worktree = f"{WORKTREE_ROOT}/{request.run_id}"
    payload = {
        "task_id": request.task_id,
        "run_id": request.run_id,
        "branch": request.branch,
        "worktree": worktree,
        "commit_sha": request.commit_sha,
        "file_scope": list(file_scope),
        "target_paths": list(target_paths),
        "tools": sorted(request.requested_tools),
        "timeout_seconds": request.timeout_seconds,
        "network_policy": request.network_policy,
        "risk_level": request.risk_level,
        "mode": request.mode,
        "cleanup_policy": "REMOVE_WORKTREE_KEEP_BRANCH",
    }
    plan_hash = _hash_payload(payload)
    return IsolationResult(
        IsolationStatus.READY,
        IsolationPlan(
            task_id=request.task_id,
            run_id=request.run_id,
            branch=request.branch,
            worktree=worktree,
            commit_sha=request.commit_sha,
            file_scope=file_scope,
            target_paths=target_paths,
            tools=tuple(sorted(request.requested_tools)),
            timeout_seconds=request.timeout_seconds,
            network_policy=request.network_policy,
            risk_level=request.risk_level,
            mode=request.mode,
            cleanup_policy="REMOVE_WORKTREE_KEEP_BRANCH",
            plan_hash=plan_hash,
        ),
        (),
    )


def _path_collection_errors(
    name: str,
    value: Any,
    allow_empty: bool,
    *,
    reject_overlaps: bool = False,
) -> list[str]:
    if not isinstance(value, tuple) or (not allow_empty and not value):
        return [f"{name} must be a non-empty tuple"]
    if not all(_safe_relative_path(item) for item in value):
        return [f"{name} must contain safe relative paths"]
    normalized = [_comparison_path(item) for item in value]
    if len(normalized) != len(set(normalized)):
        return [f"{name} must not contain duplicate paths"]
    if reject_overlaps and _contains_overlapping_paths(normalized):
        return [f"{name} must not contain overlapping paths"]
    return []


def _tool_collection_errors(name: str, value: Any) -> list[str]:
    if not isinstance(value, frozenset):
        return [f"{name} must be a frozenset"]
    if not all(_safe_tool_name(item) for item in value):
        return [f"{name} must contain safe non-empty tool names"]
    return []


def _safe_identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value not in {".", ".."}
        and bool(IDENTIFIER_RE.fullmatch(value))
    )


def _valid_branch(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if _contains_unsafe_serialized_identifier(value):
        return False
    if value.startswith("/") or value.endswith(("/", ".")):
        return False
    if ".." in value or "@{" in value or "\\" in value:
        return False
    if any(char.isspace() or ord(char) < 32 for char in value):
        return False
    if any(char in value for char in ("~", "^", ":", "?", "*", "[")):
        return False
    parts = value.split("/")
    return all(
        part and part not in {".", ".."} and not part.endswith(".lock")
        for part in parts
    )


def _branch_identity(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    normalized = unicodedata.normalize("NFKC", value).replace("\\", "/")
    if _contains_unsafe_unicode(normalized):
        return False
    if normalized.startswith("/") or "\x00" in normalized or "%" in normalized:
        return False
    if ":" in normalized:
        return False
    parts = normalized.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        return False
    if any(part != part.rstrip(" .") for part in parts):
        return False
    if any(_is_windows_reserved_component(part) for part in parts):
        return False
    path = PurePosixPath(normalized)
    return not path.is_absolute()


def _normalize_path(value: str) -> str:
    return str(PurePosixPath(unicodedata.normalize("NFKC", value).replace("\\", "/")))


def _comparison_path(value: str) -> str:
    return _normalize_path(value).casefold()


def _safe_tool_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and not any(char.isspace() or ord(char) < 32 for char in value)
        and not _contains_unsafe_serialized_identifier(value)
    )


def _contains_unsafe_unicode(value: str) -> bool:
    return any(unicodedata.category(char).startswith("C") for char in value)


def _contains_unsafe_serialized_identifier(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value)
    return _contains_unsafe_unicode(normalized)


def _is_windows_reserved_component(value: str) -> bool:
    return bool(WINDOWS_RESERVED_COMPONENT_RE.fullmatch(value))


def _contains_overlapping_paths(paths: list[str]) -> bool:
    return any(
        _paths_overlap(left, right)
        for index, left in enumerate(paths)
        for right in paths[index + 1 :]
    )


def _contains_secret_like_value(value: Any) -> bool:
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFKC", value)
        return any(pattern.search(normalized) for pattern in SECRET_LIKE_PATTERNS)
    if isinstance(value, dict):
        return any(
            _contains_secret_like_value(item)
            for pair in value.items()
            for item in pair
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_secret_like_value(item) for item in value)
    return False


def _contains_forbidden_scope(paths: tuple[str, ...]) -> bool:
    return any(
        _paths_overlap(path, forbidden)
        for path in paths
        for forbidden in FORBIDDEN_SCOPES
    )


def _paths_overlap(left: str, right: str) -> bool:
    left_id = _comparison_path(left)
    right_id = _comparison_path(right)
    return (
        left_id == right_id
        or left_id.startswith(right_id + "/")
        or right_id.startswith(left_id + "/")
    )


def _path_is_within(path: str, scopes: tuple[str, ...]) -> bool:
    path_id = _comparison_path(path)
    return any(
        path_id == _comparison_path(scope)
        or path_id.startswith(_comparison_path(scope) + "/")
        for scope in scopes
    )


def _hash_payload(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
