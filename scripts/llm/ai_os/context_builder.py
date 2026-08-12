"""Build deterministic, traceable AIOS context packets from task manifests."""

from __future__ import annotations

import json
import subprocess
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA = "ai-context.v1"
CONTEXT_READY = "CONTEXT_READY"
SPEC_BLOCKED = "SPEC_BLOCKED"
BASE_AUTHORITY_ORDER = (
    "AGENTS.md",
    "docs/ARCHITECTURE_MAP.md",
    "docs/llm/AI_OS_ENGINEERING_BACKLOG.md",
)
NESTED_AUTHORITY_BY_PREFIX = (
    ("scripts/llm", "scripts/llm/AGENTS.md"),
    ("experiments", "experiments/AGENTS.md"),
    ("web", "web/AGENTS.md"),
)
CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


@dataclass(frozen=True)
class ContextBuildResult:
    status: str
    context: dict[str, Any] | None
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "context": self.context,
            "errors": list(self.errors),
        }


def build_context_packet(
    manifest: Mapping[str, Any],
    *,
    repo_root: Path,
    loaded_at: datetime | None = None,
    data_cutoff: str | None = None,
    external_inputs: Iterable[Mapping[str, Any]] | None = None,
) -> ContextBuildResult:
    """Return a deterministic context packet or SPEC_BLOCKED with visible errors."""

    loaded_at = loaded_at or datetime.now(timezone.utc)
    root = repo_root.resolve()
    errors = _validate_manifest(manifest)
    if errors:
        return ContextBuildResult(SPEC_BLOCKED, None, tuple(errors))

    task_id = str(manifest["task_id"]).strip()
    read_plan = _read_plan(manifest)
    records: list[dict[str, Any]] = []
    missing: list[str] = []
    conflicts: list[str] = []

    for role, rel_path in read_plan:
        safe_path = _normalize_repo_path(rel_path)
        # governance-mutation: AIOS_A010_SAFE_PATH_BLOCK
        if safe_path is None:
            errors.append(f"{rel_path} is not a safe repository-relative path")
            continue
        absolute = (root / safe_path).resolve()
        if not _is_within(root, absolute):
            errors.append(f"{safe_path} escapes repository root")
            continue
        # governance-mutation: AIOS_A010_MISSING_CONTEXT_BLOCK
        if not absolute.exists() or not absolute.is_file():
            missing.append(safe_path)
            records.append(
                {
                    "path": safe_path,
                    "role": role,
                    "exists": False,
                    "content_hash": None,
                    "git_blob": None,
                    "mtime_utc": None,
                    "size_bytes": None,
                }
            )
            continue
        content = absolute.read_bytes()
        text = content.decode("utf-8", errors="replace")
        # governance-mutation: AIOS_A010_CONFLICT_MARKER_BLOCK
        if _has_conflict_marker(text):
            conflicts.append(safe_path)
        records.append(
            {
                "path": safe_path,
                "role": role,
                "exists": True,
                "content_hash": _hash_bytes(content),
                "git_blob": _git_blob(root, safe_path),
                "mtime_utc": datetime.fromtimestamp(
                    absolute.stat().st_mtime, timezone.utc
                ).isoformat(),
                "size_bytes": len(content),
            }
        )

    external = [
        _external_input_record(item)
        for item in (external_inputs or [])
        if isinstance(item, Mapping)
    ]
    if missing:
        errors.append("missing authority/input files: " + ", ".join(missing))
    if conflicts:
        errors.append("conflict markers in authority/input files: " + ", ".join(conflicts))
    if errors:
        return ContextBuildResult(SPEC_BLOCKED, None, tuple(errors))

    commit_sha = _git_text(root, "rev-parse", "HEAD")
    context_without_hash: dict[str, Any] = {
        "schema": SCHEMA,
        "task_id": task_id,
        "source_hash": manifest.get("source_hash"),
        "commit_sha": commit_sha,
        "loaded_at": loaded_at.astimezone(timezone.utc).isoformat(),
        "data_cutoff": data_cutoff,
        "freshness": {
            "status": "UNKNOWN" if data_cutoff is None else "PINNED",
            "reason": "data_cutoff omitted" if data_cutoff is None else "explicit data_cutoff",
        },
        "read_order": [record["path"] for record in records],
        "files": records,
        "external_inputs": external,
        "untrusted_external_input": bool(external),
        "excluded_conflicts": [],
    }
    context_hash = _hash_json(_context_hash_material(context_without_hash))
    context = {"context_hash": context_hash, **context_without_hash}
    return ContextBuildResult(CONTEXT_READY, context, ())


def _validate_manifest(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, Mapping):
        return ["manifest must be a mapping"]
    if manifest.get("schema") != "ai-task.v1":
        errors.append("manifest.schema must be ai-task.v1")
    for field in ("task_id", "source_hash"):
        if not isinstance(manifest.get(field), str) or not manifest.get(field, "").strip():
            errors.append(f"manifest.{field} must be a non-empty string")
    for field in (
        "authority_docs",
        "file_scope",
        "forbidden_scope",
        "input_contracts",
        "acceptance_tests",
    ):
        if not isinstance(manifest.get(field), list) or not all(
            isinstance(item, str) and item.strip() for item in manifest.get(field, [])
        ):
            errors.append(f"manifest.{field} must be a string list")
    return errors


def _read_plan(manifest: Mapping[str, Any]) -> list[tuple[str, str]]:
    planned: list[tuple[str, str]] = []
    for path in BASE_AUTHORITY_ORDER:
        planned.append(("base_authority", path))
    prefixes = [*manifest.get("file_scope", []), *manifest.get("input_contracts", [])]
    for prefix, authority in NESTED_AUTHORITY_BY_PREFIX:
        if any(_path_key(item).startswith(prefix) for item in prefixes):
            planned.append(("nested_authority", authority))
    for path in manifest.get("authority_docs", []):
        planned.append(("task_authority", path))
    for path in manifest.get("input_contracts", []):
        planned.append(("input_contract", path))
    for path in manifest.get("acceptance_tests", []):
        if _looks_like_repo_file(path):
            planned.append(("acceptance_test", path))
    return _dedupe_plan(planned)


def _dedupe_plan(items: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for role, path in items:
        safe_path = _normalize_repo_path(path)
        key = _path_key(safe_path or path)
        if key in seen:
            continue
        seen.add(key)
        result.append((role, path))
    return result


def _external_input_record(item: Mapping[str, Any]) -> dict[str, Any]:
    label = str(item.get("label", "")).strip()
    kind = str(item.get("kind", "external")).strip() or "external"
    content = str(item.get("content", ""))
    return {
        "label": label,
        "kind": kind,
        "content_hash": _hash_bytes(content.encode("utf-8")),
        "trust": "UNTRUSTED",
    }


def _has_conflict_marker(text: str) -> bool:
    return any(line.startswith(CONFLICT_MARKERS) for line in text.splitlines())


def _looks_like_repo_file(value: str) -> bool:
    safe_path = _normalize_repo_path(value)
    return safe_path is not None and " " not in safe_path and "/" in safe_path


def _normalize_repo_path(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = unicodedata.normalize("NFKC", value.strip()).replace("\\", "/")
    if not cleaned or cleaned.startswith("/") or ":" in cleaned or "%" in cleaned:
        return None
    parts = [part for part in cleaned.split("/") if part]
    if any(part in {".", ".."} or part.endswith(".") for part in parts):
        return None
    return "/".join(parts)


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _path_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().replace("\\", "/")


def _git_blob(root: Path, rel_path: str) -> str | None:
    return _git_text(root, "rev-parse", f"HEAD:{rel_path}")


def _git_text(root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _context_hash_material(context: Mapping[str, Any]) -> dict[str, Any]:
    """Return stable context identity without per-run observation timestamps."""

    return {
        **context,
        "loaded_at": None,
        "files": [
            {key: value for key, value in record.items() if key != "mtime_utc"}
            for record in context["files"]
        ],
    }


def _hash_json(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()
