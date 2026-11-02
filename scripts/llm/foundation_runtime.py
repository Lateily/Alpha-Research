"""Read-only local version inventory; never a running-service attestation."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LABELS = {"sample_purpose": "WORKFLOW_DEBUG", "testing_status": "NOT_RUN", "human_review": "PENDING",
          "production_authority": False, "trading_authority": False}
NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def _time(value):
    if (not isinstance(value, str) or len(value) > 40
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value)):
        raise ValueError("INVENTORY_TIME_INVALID")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() is None:
            raise ValueError
    except ValueError:
        raise ValueError("INVENTORY_TIME_INVALID") from None
    return result


def _zone(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 80 or value.startswith(("/", ".")):
        raise ValueError("INVENTORY_ZONE_INVALID")
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("INVENTORY_ZONE_INVALID") from None


def _name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError("INVENTORY_NAME_INVALID")
    return value


def _root(value):
    if (not isinstance(value, (str, Path)) or not str(value) or len(str(value)) > 4096
            or "://" in str(value) or any(ord(char) < 32 for char in str(value))):
        raise ValueError("INVENTORY_ROOT_INVALID")
    path = Path(value).absolute()
    if ".." in path.parts or any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("INVENTORY_ROOT_UNSAFE")
    return path


def _git(root, *args):
    # Ignore caller Git injection and disable repository-configured helper hooks.
    environment = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0",
                   "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                   "GIT_NO_LAZY_FETCH": "1"}
    argv = ["git", "--no-pager", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull,
            "-c", "core.quotePath=true", "-C", str(root), *args]
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=environment, timeout=3, check=False)
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"
    except OSError:
        return None, "GIT_UNAVAILABLE"
    if result.returncode:
        return None, "NOT_AVAILABLE"
    if len(result.stdout) > 65536:
        return None, "OUTPUT_LIMIT"
    try:
        return result.stdout.decode("utf-8").strip(), None
    except UnicodeError:
        return None, "OUTPUT_INVALID"


def _repository(role, value):
    root = _root(value)
    row = {"role": role, "local_root": str(root), "status": "NOT_OBSERVED", "code_sha": None,
           "branch": None, "dirty": None, "tracked_change_count": None, "untracked_entry_count": None,
           "cached_main_sha": None, "remote_ref_scope": "LOCAL_CACHED_NOT_FETCHED",
           "service_code_binding": "NOT_ATTESTED",
           "consistency_scope": "SEQUENTIAL_LOCAL_GIT_READS_NOT_ATOMIC"}
    if not root.exists():
        return {**row, "status": "MISSING"}
    if not root.is_dir():
        return {**row, "status": "NOT_DIRECTORY"}
    top, error = _git(root, "rev-parse", "--show-toplevel")
    if error or Path(top).resolve() != root.resolve():
        return {**row, "status": "NOT_REPOSITORY_ROOT", "error": error or "ROOT_MISMATCH"}
    head, error = _git(root, "rev-parse", "--verify", "HEAD")
    if error or not SHA.fullmatch(head):
        return {**row, "status": "HEAD_UNAVAILABLE", "error": error or "HEAD_INVALID"}
    branch, branch_error = _git(root, "symbolic-ref", "--short", "-q", "HEAD")
    filters, filter_error = _git(root, "config", "--get-regexp", r"^filter\..*\.(clean|process)$")
    if filters or filter_error not in {None, "NOT_AVAILABLE"}:
        changes, change_error = None, "FILTER_CONFIGURATION_NOT_EXECUTED"
    else:
        changes, change_error = _git(root, "status", "--porcelain=v1", "--untracked-files=normal", "--ignore-submodules=all")
    cached, cached_error = _git(root, "rev-parse", "--verify", "refs/remotes/origin/main")
    final_head, final_error = _git(root, "rev-parse", "--verify", "HEAD")
    if final_error or final_head != head:
        return {**row, "status": "UNSTABLE_HEAD", "error": "HEAD_CHANGED_OR_UNAVAILABLE"}
    entries = changes.splitlines() if changes else []
    row.update(code_sha=head, branch=branch if not branch_error else None,
               branch_status="OBSERVED" if not branch_error else "DETACHED_OR_UNAVAILABLE",
               cached_main_sha=cached if not cached_error and SHA.fullmatch(cached) else None,
               cached_main_status="CACHED" if not cached_error and SHA.fullmatch(cached) else "NOT_AVAILABLE",
               dirty=bool(entries) if not change_error else None,
               tracked_change_count=sum(not line.startswith("??") for line in entries) if not change_error else None,
               untracked_entry_count=sum(line.startswith("??") for line in entries) if not change_error else None,
               status="OBSERVED_LOCAL_ONLY" if not change_error else "PARTIAL",
               worktree_observation_error=change_error, submodule_scope="NOT_INSPECTED")
    return row


def _service(value, repositories):
    allowed = {"service_id", "repository_role", "observed_state", "observed_code_sha", "schedule"}
    if not isinstance(value, dict) or "service_id" not in value or set(value) - allowed:
        raise ValueError("INVENTORY_SERVICE_INVALID")
    identifier = _name(value["service_id"])
    role = value.get("repository_role")
    if role is not None and _name(role) not in repositories:
        raise ValueError("INVENTORY_SERVICE_ROLE_UNKNOWN")
    state = value.get("observed_state", "UNKNOWN")
    if not isinstance(state, str) or state not in {"UNKNOWN", "RUNNING", "STOPPED", "FAILED"}:
        raise ValueError("INVENTORY_SERVICE_STATE_INVALID")
    code = value.get("observed_code_sha")
    if code is not None and (not isinstance(code, str) or not SHA.fullmatch(code)):
        raise ValueError("INVENTORY_SERVICE_SHA_INVALID")
    schedule = value.get("schedule")
    if schedule is not None:
        if (not isinstance(schedule, dict) or set(schedule) != {"local_time", "weekdays"}
                or not isinstance(schedule["local_time"], str)
                or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", schedule["local_time"])
                or not isinstance(schedule["weekdays"], list) or not schedule["weekdays"]
                or len(schedule["weekdays"]) > 7
                or any(type(day) is not int or not 0 <= day <= 6 for day in schedule["weekdays"])
                or len(set(schedule["weekdays"])) != len(schedule["weekdays"])):
            raise ValueError("INVENTORY_SERVICE_SCHEDULE_INVALID")
        schedule = {"local_time": schedule["local_time"], "weekdays": sorted(schedule["weekdays"])}
    repository_code = repositories[role]["code_sha"] if role is not None else None
    relation = "UNKNOWN" if code is None or repository_code is None else "CALLER_ASSERTED_MATCH" if code == repository_code else "DIVERGENT"
    return {"service_id": identifier, "repository_role": role, "caller_observed_state": state,
            "caller_observed_code_sha": code, "repository_relation": relation,
            "running_service_attestation": "NOT_ATTESTED", "declared_schedule": schedule,
            "schedule_installation": "NOT_ATTESTED"}


def collect_runtime_inventory(repository_roots, services, *, observed_at,
                              scheduler_timezone="Europe/London", market_timezone="Asia/Shanghai"):
    """Observe local repositories and convert a caller timestamp, without dispatch."""
    if not isinstance(repository_roots, dict) or len(repository_roots) > 16:
        raise ValueError("INVENTORY_REPOSITORY_LIMIT")
    if not isinstance(services, list) or len(services) > 32:
        raise ValueError("INVENTORY_SERVICE_LIMIT")
    stamp = _time(observed_at)
    scheduler, market = _zone(scheduler_timezone), _zone(market_timezone)
    for role in repository_roots:
        _name(role)
    repositories = {_name(role): _repository(role, root) for role, root in sorted(repository_roots.items())}
    service_rows = [_service(value, repositories) for value in services]
    if len({value["service_id"] for value in service_rows}) != len(service_rows):
        raise ValueError("INVENTORY_SERVICE_DUPLICATE")
    return {"schema": "ar.runtime-inventory.v1", **LABELS, "observed_at": stamp.isoformat(),
            "observation_time_authority": "CALLER_SUPPLIED", "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "repository_capture_scope": "CURRENT_LOCAL_READ_NOT_HISTORICAL_RECONSTRUCTION", "read_only": True,
            "repositories": list(repositories.values()), "services": service_rows,
            "clocks": {"utc": stamp.astimezone(timezone.utc).isoformat(),
                       "scheduler_timezone": scheduler.key, "scheduler_time": stamp.astimezone(scheduler).isoformat(),
                       "market_timezone": market.key, "market_time": stamp.astimezone(market).isoformat()},
            "remote_fetch_performed": False, "service_probe_performed": False,
            "deployment_authority": False}
