"""Offline AIOS scheduler gate for dependency and readiness checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence


SCHEMA = "ai-schedule.v1"
SCHEDULE_READY = "SCHEDULE_READY"
SCHEDULE_BLOCKED = "SCHEDULE_BLOCKED"
POLICY_ALLOWED = "POLICY_ALLOWED"
CONTEXT_READY = "CONTEXT_READY"
SPEC_BLOCKED = "SPEC_BLOCKED"
TERMINAL_DEPENDENCY_STATES = {"DONE"}


@dataclass(frozen=True)
class ScheduleResult:
    status: str
    report: dict[str, Any]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "report": self.report,
            "errors": list(self.errors),
        }


def build_schedule(
    *,
    manifests: Sequence[Mapping[str, Any]],
    registry_snapshot: Mapping[str, Any] | None = None,
    policy_decisions: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    context_packets: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    now: datetime | None = None,
    max_context_age_minutes: int = 1440,
) -> ScheduleResult:
    """Return ready and blocked tasks without dispatching any worker."""

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    errors: list[str] = []
    max_age_minutes = _positive_int(max_context_age_minutes)
    if max_age_minutes is None:
        errors.append("max_context_age_minutes must be a positive integer")
        max_age_minutes = 1
    manifest_map, manifest_errors = _manifest_map(manifests)
    errors.extend(manifest_errors)
    policy_by_task = _by_task_id(policy_decisions)
    context_by_task = _by_task_id(context_packets)
    registry_tasks = _registry_tasks(registry_snapshot)
    cycle_tasks = _cycle_tasks(manifest_map)

    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    for task_id in sorted(manifest_map):
        manifest = manifest_map[task_id]
        reasons: list[str] = []

        if errors:
            reasons.append("scheduler input is invalid")
        if task_id in cycle_tasks:
            reasons.append("cyclic dependency")
        reasons.extend(_dependency_blocks(manifest, manifest_map, registry_tasks))
        reasons.extend(_policy_blocks(task_id, policy_by_task))
        reasons.extend(
            _context_blocks(
                task_id,
                context_by_task,
                now=now,
                max_age=timedelta(minutes=max_age_minutes),
            )
        )

        if reasons:
            blocked.append({"task_id": task_id, "reasons": reasons})
            continue
        ready.append(
            {
                "task_id": task_id,
                "reason": "dependencies, policy, and context are ready",
                "dependencies": list(manifest.get("dependencies", [])),
            }
        )

    status = SCHEDULE_BLOCKED if errors or blocked else SCHEDULE_READY
    report = {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "ready": ready,
        "blocked": blocked,
        "invalid_inputs": errors,
    }
    return ScheduleResult(status, report, tuple(errors))


def _manifest_map(
    manifests: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    result: dict[str, Mapping[str, Any]] = {}
    errors: list[str] = []
    if not isinstance(manifests, Sequence) or isinstance(manifests, (str, bytes)):
        return {}, ["manifests must be a list"]
    for index, manifest in enumerate(manifests):
        if not isinstance(manifest, Mapping):
            errors.append(f"manifest[{index}] must be a mapping")
            continue
        task_id = manifest.get("task_id")
        if manifest.get("schema") != "ai-task.v1":
            errors.append(f"manifest[{index}].schema must be ai-task.v1")
            continue
        if not isinstance(task_id, str) or not task_id.strip():
            errors.append(f"manifest[{index}].task_id must be a non-empty string")
            continue
        if not _string_list(manifest.get("dependencies", [])):
            errors.append(f"manifest[{index}].dependencies must be a string list")
            continue
        if task_id in result:
            errors.append(f"duplicate manifest task_id: {task_id}")
            continue
        result[task_id] = manifest
    return result, errors


def _dependency_blocks(
    manifest: Mapping[str, Any],
    manifest_map: Mapping[str, Mapping[str, Any]],
    registry_tasks: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    for dependency in manifest.get("dependencies", []):
        dep_state = registry_tasks.get(dependency, {}).get("state")
        if dependency in manifest_map:
            reasons.append(f"dependency {dependency} is in current schedule, not complete")
        elif dep_state not in TERMINAL_DEPENDENCY_STATES:
            reasons.append(f"dependency {dependency} is not DONE")
    return reasons


def _policy_blocks(
    task_id: str,
    policy_by_task: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    decision = policy_by_task.get(task_id)
    if decision is None:
        return ["missing policy decision"]
    if decision.get("status") != POLICY_ALLOWED:
        return [f"policy status is {decision.get('status', 'UNKNOWN')}"]
    return []


def _context_blocks(
    task_id: str,
    context_by_task: Mapping[str, Mapping[str, Any]],
    *,
    now: datetime,
    max_age: timedelta,
) -> list[str]:
    packet = context_by_task.get(task_id)
    if packet is None:
        return ["missing context packet"]
    if packet.get("status") != CONTEXT_READY:
        return [f"context status is {packet.get('status', 'UNKNOWN')}"]
    context = packet.get("context")
    if not isinstance(context, Mapping):
        return ["context payload is missing"]
    if not isinstance(context.get("context_hash"), str) or not context["context_hash"]:
        return ["context_hash is missing"]
    freshness = context.get("freshness")
    if not isinstance(freshness, Mapping) or freshness.get("status") != "PINNED":
        return ["context freshness is not PINNED"]
    loaded_at = _parse_time(context.get("loaded_at"))
    if loaded_at is None:
        return ["context loaded_at is invalid"]
    if now - loaded_at > max_age:
        return ["context is stale"]
    return []


def _cycle_tasks(manifest_map: Mapping[str, Mapping[str, Any]]) -> set[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    cycles: set[str] = set()
    stack: list[str] = []

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        if task_id in visiting:
            cycle_start = stack.index(task_id)
            cycles.update(stack[cycle_start:])
            return
        visiting.add(task_id)
        stack.append(task_id)
        for dependency in manifest_map[task_id].get("dependencies", []):
            if dependency in manifest_map:
                visit(dependency)
        stack.pop()
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in manifest_map:
        visit(task_id)
    return cycles


def _registry_tasks(snapshot: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if not isinstance(snapshot, Mapping):
        return {}
    tasks = snapshot.get("tasks")
    if not isinstance(tasks, Mapping):
        return {}
    return {
        str(task_id): task
        for task_id, task in tasks.items()
        if isinstance(task, Mapping)
    }


def _by_task_id(
    records: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> dict[str, Mapping[str, Any]]:
    if records is None:
        return {}
    if isinstance(records, Mapping):
        if "task_id" in records:
            records = [records]
        else:
            return {
                str(task_id): record
                for task_id, record in records.items()
                if isinstance(record, Mapping)
            }
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        task_id = record.get("task_id")
        if isinstance(task_id, str) and task_id.strip():
            result[task_id] = record
    return result


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value
