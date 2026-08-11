#!/usr/bin/env python3
"""Read-only workspace doctor with an optional local-report bootstrap mode."""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse


SCHEMA = "ar.team_ai_workspace_report.v1"
CONFIG_REL = Path("config/team-ai-workspace.v1.json")
COMMAND_POLICY_REL = Path("config/team-command-policy.v1.json")
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
        return {"available": False, "command": command[0], "version": None}
    try:
        result = _run([executable, *command[1:]], root)
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "command": command[0], "version": None}
    output = (result.stdout or result.stderr).strip().splitlines()
    return {
        "available": result.returncode == 0,
        "command": executable,
        "version": output[0] if output else None,
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


def compile_fixture(root: Path, config: dict[str, Any], python_tool: dict[str, Any]) -> dict[str, Any]:
    if not python_tool.get("available"):
        return {"status": "BLOCKED", "reason": "PYTHON_BASELINE_UNAVAILABLE"}
    result = _run(
        [
            python_tool["command"],
            config["task_compiler"],
            "compile",
            "--input",
            config["task_fixture"],
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
    }


def validate_command_policy(policy: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if policy.get("schema") != "ar.team_command_execution_policy.v1":
        errors.append("SCHEMA_INVALID")

    authority = policy.get("authority") or {}
    if authority.get("default_script_execution") != "DENY":
        errors.append("DEFAULT_MUST_DENY")
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
        ("scripts/team_ai_workspace.py", ("doctor",)),
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

    better = (policy.get("roles") or {}).get("Better") or {}
    if better.get("default_script_execution") != "DENY":
        errors.append("BETTER_DEFAULT_MUST_DENY")
    if better.get("inherits_common_control_plane_allowlist") is not True:
        errors.append("BETTER_CONTROL_PLANE_NOT_INHERITED")
    forbidden = better.get("forbidden_without_task_specific_junyan_approval") or []
    if "experiments/execution_tracker/" not in forbidden or "production runtime" not in forbidden:
        errors.append("BETTER_PRODUCTION_DENYLIST_INCOMPLETE")

    return {
        "status": "VALID" if not errors else "INVALID",
        "errors": errors,
        "better_default": better.get("default_script_execution"),
        "allowed_entrypoints": sorted(path for path, _ in allowed),
    }


def evaluate_workspace(root: Path, require_tools: bool = True) -> dict[str, Any]:
    root = root.resolve()
    config = _strict_json(root / CONFIG_REL)
    command_policy = validate_command_policy(_strict_json(root / COMMAND_POLICY_REL))
    required_instructions = config["required_instruction_files"]
    missing_instructions = [path for path in required_instructions if not (root / path).is_file()]
    required_workspace_files = config["required_workspace_files"]
    missing_workspace_files = [
        path for path in required_workspace_files if not (root / path).is_file()
    ]
    files = tracked_files(root)
    local_only_tracked = sorted(
        path for path in files if _matches_local_only(path, config["local_only"])
    )
    secret_findings = find_secret_violations(root, files)
    skill_report = inspect_skills(root, config["required_skills"])

    baseline = config["runtime_baseline"]
    python_tool = select_project_python(root, baseline["python_minimum"])
    node_tool = _tool_version(["node", "--version"], root)
    git_tool = _tool_version(["git", "--version"], root)
    codex_tool = _tool_version(["codex", "--version"], root)
    node_version = _version_tuple(node_tool.get("version") or "")
    node_minimum = _version_tuple(baseline["node_minimum"])
    node_ok = bool(node_tool["available"] and node_version and node_minimum and node_version >= node_minimum)

    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "branch", "--show-current")
    remote = _git(root, "remote", "get-url", "origin")
    dirty_lines = (_git(root, "status", "--porcelain") or "").splitlines()
    behind_text = _git(root, "rev-list", "--count", "HEAD..origin/main")
    ahead_text = _git(root, "rev-list", "--count", "origin/main..HEAD")
    compiler = compile_fixture(root, config, python_tool)

    failures = []
    warnings = []
    if not head:
        failures.append("NOT_A_GIT_WORKSPACE")
    remote_slug = remote_repository_slug(remote)
    if remote_slug is None or remote_slug.casefold() != config["repository"].casefold():
        failures.append("UNEXPECTED_ORIGIN_REMOTE")
    if missing_instructions:
        failures.append("MISSING_INSTRUCTION_FILES")
    if missing_workspace_files:
        failures.append("MISSING_WORKSPACE_CONTRACT_FILES")
    if command_policy["status"] != "VALID":
        failures.append("COMMAND_POLICY_INVALID")
    if skill_report["missing"] or skill_report["invalid"]:
        failures.append("SKILL_SET_INVALID")
    if local_only_tracked:
        failures.append("LOCAL_ONLY_FILE_TRACKED")
    if secret_findings:
        failures.append("TRACKED_SECRET_PATTERN")
    if compiler.get("status") != "SPEC_READY" or compiler.get("exit_code") != 0:
        failures.append("TASK_COMPILER_SMOKE_FAILED")
    if require_tools and not python_tool["available"]:
        failures.append("PYTHON_BASELINE_UNAVAILABLE")
    if require_tools and not node_ok:
        warnings.append("NODE_BASELINE_UNAVAILABLE")
    if require_tools and baseline.get("codex_required") and not codex_tool["available"]:
        failures.append("CODEX_UNAVAILABLE")
    if dirty_lines:
        warnings.append("WORKTREE_DIRTY")
    if behind_text and int(behind_text) > 0:
        warnings.append("BEHIND_ORIGIN_MAIN")

    status = "FAIL" if failures else "WARN" if warnings else "PASS"
    return {
        "schema": SCHEMA,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "repository": {
            "root": str(root),
            "origin": remote,
            "branch": branch,
            "head": head,
            "ahead_origin_main": int(ahead_text) if ahead_text and ahead_text.isdigit() else None,
            "behind_origin_main": int(behind_text) if behind_text and behind_text.isdigit() else None,
            "dirty_file_count": len(dirty_lines),
        },
        "instructions": {
            "required": required_instructions,
            "missing": missing_instructions,
        },
        "workspace_contract": {
            "required": required_workspace_files,
            "missing": missing_workspace_files,
            "layout": config["workspace_layout"],
        },
        "skills": skill_report,
        "tools": {
            "python_project": python_tool,
            "node": {**node_tool, "meets_baseline": node_ok},
            "git": git_tool,
            "codex": codex_tool,
        },
        "task_compiler": compiler,
        "command_policy": command_policy,
        "hygiene": {
            "local_only_tracked": local_only_tracked,
            "tracked_secret_findings": secret_findings,
        },
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
    print(f"  branch={repo['branch']} head={(repo['head'] or '')[:12]} dirty={repo['dirty_file_count']}")
    print(
        "  skills="
        f"{len(report['skills']['discovered'])}/{len(report['skills']['required'])} "
        f"task_compiler={report['task_compiler']['status']}"
    )
    for item in report["failures"]:
        print(f"  FAIL {item}")
    for item in report["warnings"]:
        print(f"  WARN {item}")
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
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        report = evaluate_workspace(root, require_tools=not args.ci)
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
