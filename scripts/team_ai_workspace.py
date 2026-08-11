#!/usr/bin/env python3
"""Read-only workspace doctor with an optional local-report bootstrap mode."""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse


SCHEMA = "ar.team_ai_workspace_report.v2"
CONFIG_REL = Path("config/team-ai-workspace.v2.json")
COMMAND_POLICY_REL = Path("config/team-command-policy.v2.json")
SYNC_POLICY_REL = Path("config/team-sync-policy.v2.json")
LOCAL_REPORT_REL = Path(".ai-workspace/doctor-report.json")
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION_RE = re.compile(r"(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?")
SECRET_PATTERNS = (
    ("OPENAI_STYLE_KEY", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("GITHUB_TOKEN", re.compile(rb"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b")),
    ("PRIVATE_KEY", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "ASSIGNED_SECRET",
        re.compile(
            rb"(?im)^[ \t]*[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY)[ \t]*=[ \t]*"
            rb"[\"']([^\"'\r\n]{16,})[\"']"
        ),
    ),
)
PLACEHOLDER_MARKERS = (
    b"example",
    b"placeholder",
    b"replace",
    b"your_",
    b"redact",
    b"dummy",
    b"test",
    b"secret",
    b"${",
    b"***",
    b"...",
    b"<",
)


class WorkspaceError(RuntimeError):
    pass


def _run(args: Sequence[str], root: Path, timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args),
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _strict_json(path: Path) -> Any:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise WorkspaceError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"cannot read JSON {path}: {exc}") from exc


def _version_tuple(text: str) -> tuple[int, int, int] | None:
    match = VERSION_RE.search(text or "")
    if not match:
        return None
    return tuple(int(match.group(name) or 0) for name in ("major", "minor", "patch"))


def _tool_version(command: Sequence[str], root: Path) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if not executable:
        return {
            "available": False,
            "command": command[0],
            "version": None,
            "reason": "NOT_FOUND",
        }
    try:
        result = _run([executable, *command[1:]], root)
    except PermissionError:
        return {
            "available": False,
            "command": executable,
            "version": None,
            "reason": "EXECUTION_DENIED",
        }
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "command": executable,
            "version": None,
            "reason": "TIMEOUT",
        }
    except OSError:
        return {
            "available": False,
            "command": executable,
            "version": None,
            "reason": "EXECUTION_FAILED",
        }
    output = (result.stdout or result.stderr).strip().splitlines()
    return {
        "available": result.returncode == 0,
        "command": executable,
        "version": output[0] if output else None,
        "reason": None if result.returncode == 0 else "NONZERO_EXIT",
    }


def _tool_version_candidates(commands: Sequence[Sequence[str]], root: Path) -> dict[str, Any]:
    attempts = []
    for command in commands:
        result = _tool_version(command, root)
        attempts.append({"command": command[0], "reason": result.get("reason")})
        if result.get("available"):
            return result
        if result.get("reason") not in {"NOT_FOUND"}:
            return {**result, "attempts": attempts}
    return {
        "available": False,
        "command": commands[0][0],
        "version": None,
        "reason": "NOT_FOUND",
        "attempts": attempts,
    }


def _python_candidates() -> list[str]:
    home = Path.home()
    candidates = [
        shutil.which("python3.12"),
        shutil.which("python3.11"),
        str(home / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"),
        str(home / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"),
        sys.executable,
        shutil.which("python3"),
        shutil.which("python"),
    ]
    seen: set[str] = set()
    result = []
    for item in candidates:
        if not item:
            continue
        resolved = str(Path(item).expanduser())
        if resolved not in seen and os.path.isfile(resolved):
            seen.add(resolved)
            result.append(resolved)
    return result


def select_project_python(root: Path, minimum: str) -> dict[str, Any]:
    required = _version_tuple(minimum)
    for candidate in _python_candidates():
        result = _run([candidate, "--version"], root)
        version_text = (result.stdout or result.stderr).strip()
        parsed = _version_tuple(version_text)
        if result.returncode == 0 and parsed and required and parsed >= required:
            return {"available": True, "command": candidate, "version": version_text}
    return {
        "available": False,
        "command": None,
        "version": None,
        "required": minimum,
    }


def _git(root: Path, *args: str) -> str | None:
    result = _run(["git", *args], root)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def remote_repository_slug(remote: str | None) -> str | None:
    """Return owner/repository for common GitHub HTTPS and SSH remotes."""
    value = (remote or "").strip().rstrip("/")
    if not value:
        return None
    if "://" in value:
        path = urlparse(value).path
    elif value.startswith("git@") and ":" in value:
        path = value.split(":", 1)[1]
    else:
        return None
    slug = path.strip("/")
    if slug.endswith(".git"):
        slug = slug[:-4]
    return slug or None


def tracked_files(root: Path) -> list[str]:
    output = _git(root, "ls-files", "-z")
    if output is None:
        raise WorkspaceError("git ls-files failed")
    return [item for item in output.split("\0") if item]


def _matches_local_only(path: str, patterns: Iterable[str]) -> bool:
    normalized = path.replace(os.sep, "/")
    if normalized == ".env.example":
        return False
    for pattern in patterns:
        p = pattern.replace(os.sep, "/")
        if p.endswith("/") and normalized.startswith(p):
            return True
        if fnmatch.fnmatch(normalized, p) or fnmatch.fnmatch(Path(normalized).name, p):
            return True
    return False


def find_secret_violations(root: Path, files: Iterable[str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for relative in files:
        path = root / relative
        if not path.is_file() or path.stat().st_size > 1_000_000:
            continue
        try:
            content = path.read_bytes()
        except OSError:
            findings.append({"file": relative, "rule": "UNREADABLE_TRACKED_FILE"})
            continue
        for rule, pattern in SECRET_PATTERNS:
            match = pattern.search(content)
            if not match:
                continue
            sample = match.group(1) if rule == "ASSIGNED_SECRET" else match.group(0)
            lowered = sample.lower()
            if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
                continue
            findings.append({"file": relative, "rule": rule})
    return findings


def _skill_metadata(skill_file: Path) -> dict[str, str]:
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    _, frontmatter, _ = text.split("---", 2)
    result = {}
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip('"')
    return result


def inspect_skills(root: Path, required: Sequence[str]) -> dict[str, Any]:
    base = root / ".agents/skills"
    discovered = sorted(path.parent.name for path in base.glob("*/SKILL.md")) if base.exists() else []
    invalid = []
    for name in discovered:
        skill_file = base / name / "SKILL.md"
        meta = _skill_metadata(skill_file)
        ui_file = base / name / "agents/openai.yaml"
        if (
            meta.get("name") != name
            or not SKILL_NAME_RE.fullmatch(name)
            or len(meta.get("description", "")) < 30
            or not ui_file.is_file()
            or f"${name}" not in ui_file.read_text(encoding="utf-8")
        ):
            invalid.append(name)
    return {
        "required": list(required),
        "discovered": discovered,
        "missing": sorted(set(required) - set(discovered)),
        "invalid": invalid,
    }


def compile_task_source(
    root: Path,
    config: dict[str, Any],
    python_tool: dict[str, Any],
    source_path: str | Path,
) -> dict[str, Any]:
    if not python_tool.get("available"):
        return {"status": "BLOCKED", "reason": "PYTHON_BASELINE_UNAVAILABLE"}
    source = Path(source_path)
    if not source.is_absolute():
        source = root / source
    if not source.is_file():
        return {
            "status": "BLOCKED",
            "reason": "TASK_SOURCE_MISSING",
            "source": str(source),
        }
    result = _run(
        [
            python_tool["command"],
            config["task_compiler"],
            "compile",
            "--input",
            str(source),
        ],
        root,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "status": "BLOCKED",
            "reason": "COMPILER_OUTPUT_INVALID",
            "exit_code": result.returncode,
        }
    return {
        "status": payload.get("status"),
        "exit_code": result.returncode,
        "task_id": (payload.get("manifest") or {}).get("task_id"),
        "errors": payload.get("errors", []),
        "source": str(source),
    }


def compile_fixture(root: Path, config: dict[str, Any], python_tool: dict[str, Any]) -> dict[str, Any]:
    return compile_task_source(root, config, python_tool, config["task_fixture"])


def validate_command_policy(policy: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if policy.get("schema") != "ar.team_command_execution_policy.v2":
        errors.append("SCHEMA_INVALID")

    authority = policy.get("authority") or {}
    if authority.get("default_outside_declared_task") != "DENY":
        errors.append("OUTSIDE_TASK_DEFAULT_MUST_DENY")
    if authority.get("task_scoped_creation_without_intermediate_approval") is not True:
        errors.append("TASK_SCOPED_AUTONOMY_NOT_GRANTED")
    # governance-mutation: TEAM_COMMAND_JUNYAN_FINAL_APPROVER
    if authority.get("final_human_approver") != "Junyan":
        errors.append("FINAL_APPROVER_MUST_BE_JUNYAN")
    required_final_actions = {
        "MERGE_PR",
        "PRODUCTION_DEPLOY",
        "PRODUCTION_DATA_MIGRATION",
        "CONSTITUTIONAL_CHANGE",
        "METHODOLOGY_CHANGE",
        "CAPITAL_OR_TRADING_RULE_CHANGE",
    }
    if not required_final_actions.issubset(set(authority.get("final_actions") or [])):
        errors.append("FINAL_ACTIONS_INCOMPLETE")
    if authority.get("active_session_revocation_required_for_legacy_blanket_bans") is not True:
        errors.append("ACTIVE_SESSION_REVOCATION_NOT_REQUIRED")

    adoption = policy.get("workspace_adoption") or {}
    if adoption.get("reuse_existing_valid_clone") is not True:
        errors.append("EXISTING_CLONE_REUSE_NOT_REQUIRED")
    if adoption.get("duplicate_clone_for_layout_only") is not False:
        errors.append("DUPLICATE_CLONE_NOT_FORBIDDEN")

    allowlist = policy.get("common_control_plane_allowlist") or []
    allowed = {
        (entry.get("path"), tuple(entry.get("subcommands") or []))
        for entry in allowlist
        if isinstance(entry, dict)
    }
    required = {
        ("scripts/team_ai_workspace.py", ("doctor", "bootstrap")),
        ("scripts/llm/ai_os/cli.py", ("compile",)),
    }
    if not required.issubset(allowed):
        errors.append("CONTROL_PLANE_ALLOWLIST_INCOMPLETE")
    for entry in allowlist:
        if not isinstance(entry, dict):
            errors.append("ALLOWLIST_ENTRY_INVALID")
            continue
        if entry.get("network") != "OFFLINE":
            errors.append("CONTROL_PLANE_NETWORK_NOT_OFFLINE")
        if entry.get("tracked_writes") != "NONE":
            errors.append("CONTROL_PLANE_TRACKED_WRITE_ALLOWED")
        if entry.get("git_state_changes") != "NONE":
            errors.append("CONTROL_PLANE_GIT_CHANGE_ALLOWED")

    roles = policy.get("roles") or {}
    better = roles.get("Better") or {}
    for role_name in ("Better", "Reed", "Jason", "Simon"):
        role = roles.get(role_name) or {}
        if role.get("default_script_execution") != "TASK_SCOPED":
            errors.append(f"{role_name.upper()}_MUST_BE_TASK_SCOPED")
        if role.get("inherits_common_control_plane_allowlist") is not True:
            errors.append(f"{role_name.upper()}_CONTROL_PLANE_NOT_INHERITED")
    if better.get("inherits_common_control_plane_allowlist") is not True:
        errors.append("BETTER_CONTROL_PLANE_NOT_INHERITED")
    forbidden = better.get("forbidden_without_task_specific_junyan_approval") or []
    if "experiments/execution_tracker/" not in forbidden or "production runtime" not in forbidden:
        errors.append("BETTER_PRODUCTION_DENYLIST_INCOMPLETE")

    return {
        "status": "VALID" if not errors else "INVALID",
        "errors": errors,
        "better_default": better.get("default_script_execution"),
        "final_approver": authority.get("final_human_approver"),
        "task_scoped_roles": sorted(
            name
            for name, value in roles.items()
            if value.get("default_script_execution") == "TASK_SCOPED"
        ),
        "allowed_entrypoints": sorted(path for path, _ in allowed),
    }


def validate_sync_policy(policy: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if policy.get("schema") != "ar.team_sync_policy.v2":
        errors.append("SCHEMA_INVALID")
    if policy.get("repository") != "Lateily/Alpha-Research":
        errors.append("REPOSITORY_INVALID")
    fact_source = policy.get("fact_source") or {}
    if fact_source.get("canonical") != "MERGED_MAIN":
        errors.append("MAIN_NOT_CANONICAL")
    authority = policy.get("authority") or {}
    # governance-mutation: TEAM_SYNC_JUNYAN_FINAL_APPROVER
    if authority.get("final_approver") != "Junyan":
        errors.append("FINAL_APPROVER_MUST_BE_JUNYAN")
    # governance-mutation: TEAM_SYNC_AUTOMATION_DENY
    for key in (
        "automation_may_merge",
        "automation_may_deploy_production",
        "automation_may_approve_methodology_or_capital_rules",
    ):
        if authority.get(key) is not False:
            errors.append(f"{key.upper()}_MUST_BE_FALSE")
    evidence = policy.get("evidence") or {}
    if not isinstance(evidence.get("ttl_hours"), int) or evidence.get("ttl_hours", 0) <= 0:
        errors.append("REPORT_TTL_INVALID")
    registration = policy.get("workspace_registration") or {}
    if registration.get("active_approver") != "Junyan":
        errors.append("REGISTRATION_APPROVER_MUST_BE_JUNYAN")
    # governance-mutation: TEAM_REGISTRATION_EVIDENCE_STRENGTH
    if registration.get("evidence_strength") != "TRANSCRIPT_REFERENCE_NOT_CRYPTOGRAPHIC":
        errors.append("REGISTRATION_EVIDENCE_STRENGTH_INVALID")
    if set(policy.get("overall_statuses") or []) != {"PASS", "PASS_WITH_GAPS", "FAIL"}:
        errors.append("OVERALL_STATUSES_INVALID")
    stages = policy.get("delivery_stages") or []
    if stages != [
        "LOCAL_ONLY",
        "PUSHED",
        "PR_OPEN",
        "MERGED",
        "DEPLOYED",
        "PRODUCTION_VERIFIED",
    ]:
        errors.append("DELIVERY_STAGES_INVALID")
    for name in ("ci", "onboarding", "delivery"):
        if name not in (policy.get("profiles") or {}):
            errors.append(f"PROFILE_MISSING:{name}")
    return {"status": "VALID" if not errors else "INVALID", "errors": errors}


def codex_cli_finding(
    codex_tool: dict[str, Any], require_tools: bool, cli_required: bool = False
) -> tuple[str, str] | None:
    if not require_tools or codex_tool.get("available"):
        return None
    if cli_required:
        return ("FAIL", "CODEX_CLI_REQUIRED_UNAVAILABLE")
    return ("GAP", "CODEX_CLI_UNAVAILABLE")


def _git_common_dir(root: Path) -> Path | None:
    value = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(value).resolve() if value else None


def inspect_workspace_registration(
    root: Path,
    policy: dict[str, Any],
    registration_file: str | Path | None = None,
) -> dict[str, Any]:
    contract = policy["workspace_registration"]
    path = Path(registration_file) if registration_file else root / contract["path"]
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        return {"status": "UNREGISTERED", "path": str(path), "errors": []}
    try:
        payload = _strict_json(path)
    except WorkspaceError as exc:
        return {"status": "INVALID", "path": str(path), "errors": [str(exc)]}

    errors = []
    for field in contract["required_fields"]:
        if field not in payload:
            errors.append(f"MISSING_FIELD:{field}")
    if payload.get("schema") != contract["schema"]:
        errors.append("SCHEMA_INVALID")
    if payload.get("repository") != policy["repository"]:
        errors.append("REPOSITORY_INVALID")
    if payload.get("lifecycle") != "ACTIVE":
        errors.append("PRIMARY_LIFECYCLE_NOT_ACTIVE")
    # governance-mutation: TEAM_WORKSPACE_JUNYAN_REGISTRATION
    if payload.get("approved_by") != contract["active_approver"]:
        errors.append("APPROVER_INVALID")
    if payload.get("evidence_strength") != contract["evidence_strength"]:
        errors.append("EVIDENCE_STRENGTH_INVALID")
    if not isinstance(payload.get("approval_ref"), str) or not payload.get("approval_ref", "").strip():
        errors.append("APPROVAL_REF_MISSING")
    for field in ("workspace_id", "member", "machine_id"):
        if not isinstance(payload.get(field), str) or not payload.get(field, "").strip():
            errors.append(f"{field.upper()}_INVALID")

    canonical_text = payload.get("canonical_root")
    canonical = Path(canonical_text).expanduser() if isinstance(canonical_text, str) else None
    if canonical is None or not canonical.is_absolute() or not canonical.is_dir():
        errors.append("CANONICAL_ROOT_INVALID")
    elif _git_common_dir(canonical) != _git_common_dir(root):
        errors.append("CANONICAL_ROOT_DIFFERENT_REPOSITORY")

    legacy_roots = payload.get("legacy_roots")
    if not isinstance(legacy_roots, list):
        errors.append("LEGACY_ROOTS_INVALID")
        legacy_roots = []
    for entry in legacy_roots:
        if not isinstance(entry, dict):
            errors.append("LEGACY_ROOT_ENTRY_INVALID")
            continue
        if entry.get("lifecycle") not in {"READ_ONLY_LEGACY", "ARCHIVED"}:
            errors.append("LEGACY_ROOT_LIFECYCLE_INVALID")
        if not isinstance(entry.get("path"), str) or not entry.get("path", "").strip():
            errors.append("LEGACY_ROOT_PATH_INVALID")

    return {
        "status": "INVALID" if errors else "REGISTERED_DECLARED",
        "path": str(path),
        "errors": errors,
        "workspace_id": payload.get("workspace_id"),
        "member": payload.get("member"),
        "canonical_root": canonical_text,
        "legacy_roots": legacy_roots,
        "approval_ref": payload.get("approval_ref"),
    }


def inspect_canonical_readiness(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for item in policy.get("canonical_readiness_artifacts") or []:
        present = (root / item["path"]).is_file()
        rows.append({**item, "present": present})
    return {
        "status": "READY" if all(row["present"] for row in rows) else "GAPS",
        "artifacts": rows,
        "missing": [row["id"] for row in rows if not row["present"]],
    }


def report_is_fresh(report: dict[str, Any], now: dt.datetime | None = None) -> bool:
    try:
        expires = dt.datetime.fromisoformat(str(report["evidence"]["expires_at"]))
    except (KeyError, TypeError, ValueError):
        return False
    now = now or dt.datetime.now(dt.timezone.utc)
    if expires.tzinfo is None:
        return False
    # governance-mutation: TEAM_REPORT_EXPIRY
    return now <= expires.astimezone(dt.timezone.utc)


def expected_main_mismatch(origin_main: str | None, expected_main_sha: str) -> bool:
    # governance-mutation: TEAM_EXPECTED_MAIN_SHA
    return origin_main != expected_main_sha.lower()


def delivery_requires_active_task(active_task_status: str, requirement: str) -> bool:
    # governance-mutation: TEAM_DELIVERY_ACTIVE_TASK
    return active_task_status == "UNBOUND" and requirement == "REQUIRED"


def _dimension(status: str, reasons: Sequence[str]) -> dict[str, Any]:
    return {"status": status, "reasons": sorted(set(reasons))}


def evaluate_workspace(
    root: Path,
    require_tools: bool = True,
    *,
    profile: str = "onboarding",
    task_source: str | Path | None = None,
    expected_main_sha: str | None = None,
    registration_file: str | Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    generated_at = dt.datetime.now(dt.timezone.utc)
    config = _strict_json(root / CONFIG_REL)
    command_policy = validate_command_policy(_strict_json(root / COMMAND_POLICY_REL))
    sync_policy_raw = _strict_json(root / SYNC_POLICY_REL)
    sync_policy = validate_sync_policy(sync_policy_raw)
    if profile not in (sync_policy_raw.get("profiles") or {}):
        raise WorkspaceError(f"unsupported doctor profile: {profile}")
    profile_policy = sync_policy_raw["profiles"][profile]

    required_instructions = config["required_instruction_files"]
    missing_instructions = [path for path in required_instructions if not (root / path).is_file()]
    required_workspace_files = config["required_workspace_files"]
    missing_workspace_files = [path for path in required_workspace_files if not (root / path).is_file()]
    files = tracked_files(root)
    local_only_tracked = sorted(path for path in files if _matches_local_only(path, config["local_only"]))
    secret_findings = find_secret_violations(root, files)
    skill_report = inspect_skills(root, config["required_skills"])

    baseline = config["runtime_baseline"]
    python_tool = select_project_python(root, baseline["python_minimum"])
    node_tool = _tool_version(["node", "--version"], root)
    npm_commands = [["npm.cmd", "--version"], ["npm", "--version"]] if platform.system() == "Windows" else [["npm", "--version"]]
    npm_tool = _tool_version_candidates(npm_commands, root)
    git_tool = _tool_version(["git", "--version"], root)
    codex_tool = _tool_version(["codex", "--version"], root)
    node_version = _version_tuple(node_tool.get("version") or "")
    node_minimum = _version_tuple(baseline["node_minimum"])
    node_ok = bool(node_tool["available"] and node_version and node_minimum and node_version >= node_minimum)

    head = _git(root, "rev-parse", "HEAD")
    origin_main = _git(root, "rev-parse", "origin/main")
    branch = _git(root, "branch", "--show-current")
    remote = _git(root, "remote", "get-url", "origin")
    dirty_lines = (_git(root, "status", "--porcelain") or "").splitlines()
    behind_text = _git(root, "rev-list", "--count", "HEAD..origin/main")
    ahead_text = _git(root, "rev-list", "--count", "origin/main..HEAD")
    compiler_smoke = compile_fixture(root, config, python_tool)
    active_task = (
        compile_task_source(root, config, python_tool, task_source)
        if task_source
        else {"status": "UNBOUND", "reason": "ACTIVE_TASK_SOURCE_NOT_PROVIDED"}
    )
    registration = inspect_workspace_registration(root, sync_policy_raw, registration_file)
    readiness = inspect_canonical_readiness(root, sync_policy_raw)

    failures: list[str] = []
    gaps: list[str] = []
    repo_failures: list[str] = []
    repo_gaps: list[str] = []
    if config.get("schema") != "ar.team_ai_workspace.v2":
        failures.append("WORKSPACE_CONFIG_INVALID")
    if not head:
        repo_failures.append("NOT_A_GIT_WORKSPACE")
    remote_slug = remote_repository_slug(remote)
    if remote_slug is None or remote_slug.casefold() != config["repository"].casefold():
        repo_failures.append("UNEXPECTED_ORIGIN_REMOTE")
    if expected_main_sha:
        if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_main_sha):
            repo_failures.append("EXPECTED_MAIN_SHA_INVALID")
        elif expected_main_mismatch(origin_main, expected_main_sha):
            repo_failures.append("EXPECTED_MAIN_SHA_MISMATCH")
    elif profile_policy["expected_main_sha"] == "REQUIRED":
        repo_failures.append("EXPECTED_MAIN_SHA_REQUIRED")
    elif profile_policy["expected_main_sha"] == "GAP_IF_MISSING":
        repo_gaps.append("REMOTE_MAIN_UNANCHORED")
    if dirty_lines:
        repo_gaps.append("WORKTREE_DIRTY")
    if behind_text and int(behind_text) > 0:
        repo_gaps.append("BEHIND_LOCAL_ORIGIN_MAIN")
    failures.extend(repo_failures)
    gaps.extend(repo_gaps)

    if missing_instructions:
        failures.append("MISSING_INSTRUCTION_FILES")
    if missing_workspace_files:
        failures.append("MISSING_WORKSPACE_CONTRACT_FILES")
    if command_policy["status"] != "VALID":
        failures.append("COMMAND_POLICY_INVALID")
    if sync_policy["status"] != "VALID":
        failures.append("SYNC_POLICY_INVALID")
    if skill_report["missing"] or skill_report["invalid"]:
        failures.append("SKILL_SET_INVALID")
    if local_only_tracked:
        failures.append("LOCAL_ONLY_FILE_TRACKED")
    if secret_findings:
        failures.append("TRACKED_SECRET_PATTERN")
    if compiler_smoke.get("status") != "SPEC_READY" or compiler_smoke.get("exit_code") != 0:
        failures.append("TASK_COMPILER_SMOKE_FAILED")

    if registration["status"] == "INVALID":
        failures.append("WORKSPACE_REGISTRATION_INVALID")
    elif registration["status"] == "UNREGISTERED":
        if profile_policy["registration"] == "REQUIRED":
            failures.append("WORKSPACE_REGISTRATION_REQUIRED")
        elif profile_policy["registration"] == "GAP_IF_MISSING":
            gaps.append("CANONICAL_WORKSPACE_UNREGISTERED")

    if active_task["status"] == "UNBOUND":
        if delivery_requires_active_task(active_task["status"], profile_policy["active_task"]):
            failures.append("ACTIVE_TASK_REQUIRED")
        elif profile_policy["active_task"] == "GAP_IF_MISSING":
            gaps.append("ACTIVE_TASK_UNBOUND")
    elif active_task.get("status") != "SPEC_READY" or active_task.get("exit_code") != 0:
        failures.append("ACTIVE_TASK_SPEC_BLOCKED")

    if require_tools and not python_tool["available"]:
        failures.append("PYTHON_BASELINE_UNAVAILABLE")
    if require_tools and not git_tool["available"]:
        failures.append("GIT_UNAVAILABLE")
    if require_tools and not node_ok:
        gaps.append("NODE_BASELINE_UNAVAILABLE")
    if require_tools and not npm_tool["available"]:
        gaps.append("NPM_UNAVAILABLE")
    codex_finding = codex_cli_finding(codex_tool, require_tools)
    if codex_finding:
        severity, finding = codex_finding
        (failures if severity == "FAIL" else gaps).append(finding)

    gaps.extend(f"CANONICAL_ARTIFACT_MISSING:{item}" for item in readiness["missing"])
    failures = sorted(set(failures))
    gaps = sorted(set(gaps))
    status = "FAIL" if failures else "PASS_WITH_GAPS" if gaps else "PASS"

    registration_reasons = []
    if registration["status"] != "REGISTERED_DECLARED":
        registration_reasons.append(registration["status"])
    task_reasons = [] if active_task.get("status") == "SPEC_READY" else [active_task.get("reason", active_task.get("status", "UNKNOWN"))]
    contract_reasons = failures.copy()
    contract_reasons = [item for item in contract_reasons if item in {"MISSING_INSTRUCTION_FILES", "MISSING_WORKSPACE_CONTRACT_FILES", "COMMAND_POLICY_INVALID", "SYNC_POLICY_INVALID", "SKILL_SET_INVALID", "LOCAL_ONLY_FILE_TRACKED", "TRACKED_SECRET_PATTERN", "TASK_COMPILER_SMOKE_FAILED", "WORKSPACE_CONFIG_INVALID"}]
    tool_reasons = [item for item in failures + gaps if item in {"PYTHON_BASELINE_UNAVAILABLE", "GIT_UNAVAILABLE", "NODE_BASELINE_UNAVAILABLE", "NPM_UNAVAILABLE", "CODEX_CLI_UNAVAILABLE", "CODEX_CLI_REQUIRED_UNAVAILABLE"}]
    expires_at = generated_at + dt.timedelta(hours=sync_policy_raw["evidence"]["ttl_hours"])

    return {
        "schema": SCHEMA,
        "generated_at": generated_at.isoformat(),
        "status": status,
        "profile": profile,
        "failures": failures,
        "gaps": gaps,
        "warnings": gaps,
        "evidence": {
            "observed_at": generated_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "workspace_id": registration.get("workspace_id"),
            "canonical_root": registration.get("canonical_root") or str(root),
            "local_head_sha": head,
            "local_origin_main_sha": origin_main,
            "expected_main_sha": expected_main_sha,
            "dirty_file_count": len(dirty_lines),
            "profile": profile,
            "network_refresh_performed": False,
        },
        "dimensions": {
            "repository_sync": _dimension("FAIL" if repo_failures else "GAP" if repo_gaps else "PASS", repo_failures + repo_gaps),
            "workspace_identity": _dimension(
                "FAIL"
                if registration["status"] == "INVALID" or "WORKSPACE_REGISTRATION_REQUIRED" in failures
                else "GAP"
                if "CANONICAL_WORKSPACE_UNREGISTERED" in gaps
                else "PASS"
                if registration["status"] == "REGISTERED_DECLARED"
                else "NOT_EVALUATED",
                registration_reasons,
            ),
            "shared_contracts": _dimension("FAIL" if contract_reasons else "PASS", contract_reasons),
            "tools": _dimension("FAIL" if any(item in failures for item in tool_reasons) else "GAP" if tool_reasons else "PASS", tool_reasons),
            "active_task": _dimension(
                "FAIL"
                if "ACTIVE_TASK_SPEC_BLOCKED" in failures or "ACTIVE_TASK_REQUIRED" in failures
                else "GAP"
                if "ACTIVE_TASK_UNBOUND" in gaps
                else "PASS"
                if active_task.get("status") == "SPEC_READY"
                else "NOT_EVALUATED",
                task_reasons,
            ),
            "canonical_readiness": _dimension("GAP" if readiness["missing"] else "PASS", readiness["missing"]),
            "deployment": _dimension("NOT_EVALUATED", ["OFFLINE_DOCTOR_DOES_NOT_ASSERT_DEPLOYMENT"]),
        },
        "repository": {
            "root": str(root),
            "origin": remote,
            "branch": branch,
            "head": head,
            "origin_main": origin_main,
            "ahead_origin_main": int(ahead_text) if ahead_text and ahead_text.isdigit() else None,
            "behind_origin_main": int(behind_text) if behind_text and behind_text.isdigit() else None,
            "dirty_file_count": len(dirty_lines),
            "remote_tracking_claim": sync_policy_raw["fact_source"]["offline_doctor_remote_claim"],
        },
        "instructions": {"required": required_instructions, "missing": missing_instructions},
        "workspace_contract": {"required": required_workspace_files, "missing": missing_workspace_files, "layout": config["workspace_layout"]},
        "workspace_registration": registration,
        "skills": skill_report,
        "tools": {
            "python_project": python_tool,
            "node": {**node_tool, "meets_baseline": node_ok},
            "npm": npm_tool,
            "git": git_tool,
            "codex_cli": codex_tool,
            "codex_desktop": {"status": "MANUAL_SMOKE_REQUIRED", "does_not_satisfy_cli": True},
            "remediation": {
                "windows_codex_cli": "powershell -ExecutionPolicy ByPass -c \"irm https://chatgpt.com/codex/install.ps1 | iex\"",
                "alternate_codex_cli": "npm install -g @openai/codex",
                "windows_path": ["C:\\Program Files\\nodejs", "%APPDATA%\\npm"],
                "policy": "REPORT_ONLY; never install, alter PATH, or create a shim automatically",
            },
        },
        "task_compiler_smoke": compiler_smoke,
        "task_compiler": compiler_smoke,
        "active_task": active_task,
        "command_policy": command_policy,
        "sync_policy": sync_policy,
        "canonical_readiness": readiness,
        "hygiene": {"local_only_tracked": local_only_tracked, "tracked_secret_findings": secret_findings},
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _print_human(report: dict[str, Any]) -> None:
    print(f"AR Team AI Workspace: {report['status']}")
    repo = report["repository"]
    print(
        f"  profile={report['profile']} branch={repo['branch']} "
        f"head={(repo['head'] or '')[:12]} origin_main={(repo['origin_main'] or '')[:12]} "
        f"dirty={repo['dirty_file_count']}"
    )
    print(
        "  skills="
        f"{len(report['skills']['discovered'])}/{len(report['skills']['required'])} "
        f"compiler_smoke={report['task_compiler_smoke']['status']} "
        f"active_task={report['active_task']['status']}"
    )
    for item in report["failures"]:
        print(f"  FAIL {item}")
    for item in report["gaps"]:
        print(f"  GAP {item}")
    for finding in report["hygiene"]["tracked_secret_findings"]:
        print(f"  FAIL secret-pattern {finding['rule']} in {finding['file']} (value not printed)")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("doctor", "bootstrap"),
        help=(
            "doctor changes no tracked file or Git state; bootstrap additionally "
            "writes only .ai-workspace/doctor-report.json"
        ),
    )
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--ci", action="store_true", help="Do not require local Codex/Node tools")
    parser.add_argument(
        "--profile",
        choices=("ci", "onboarding", "delivery"),
        default="onboarding",
        help="ci is repository-only; delivery requires canonical registration, a task, and an expected main SHA",
    )
    parser.add_argument("--task-source", help="Path to the active ai-task.v1 source")
    parser.add_argument("--expected-main-sha", help="Externally observed 40-character origin/main SHA")
    parser.add_argument("--registration-file", help="Override the local-only workspace registration path")
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        report = evaluate_workspace(
            root,
            require_tools=not args.ci,
            profile="ci" if args.ci else args.profile,
            task_source=args.task_source,
            expected_main_sha=args.expected_main_sha,
            registration_file=args.registration_file,
        )
        if args.command == "bootstrap":
            _atomic_json(root / LOCAL_REPORT_REL, report)
        if args.as_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            _print_human(report)
            if args.command == "bootstrap":
                print(f"  redacted_report={LOCAL_REPORT_REL}")
        return 1 if report["status"] == "FAIL" else 0
    except (WorkspaceError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"WORKSPACE_BLOCKED {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
