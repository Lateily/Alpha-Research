"""Replay AI Progress Board events into current task states.

This is the first AIOS-K1 registry seed. It is read-only and deterministic:
the same event stream always produces the same task registry snapshot.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import progress_conflicts


TERMINAL_EVENTS = {"DONE", "RELEASE"}


@dataclass
class TaskState:
    task_id: str
    status: str = "DISCOVERED"
    active: bool = False
    event: str = ""
    human_owner: str = ""
    executor: str = ""
    reviewer: str = ""
    summary: str = ""
    branch: str = ""
    files: list[str] = field(default_factory=list)
    pr: str = ""
    next: str = ""
    blocked_by: str = ""
    cost_cny: str = ""
    risk: str = ""
    updated_at: str = ""
    expires_at: str = ""
    history_count: int = 0

    def apply(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("event", ""))
        self.event = event_type
        self.status = status_from_event(event)
        self.active = event_type in {"CLAIM", "UPDATE"}
        self.human_owner = str(event.get("human_owner", self.human_owner) or "")
        self.executor = str(event.get("executor", self.executor) or "")
        self.reviewer = str(event.get("reviewer", self.reviewer) or "")
        self.summary = str(event.get("summary", self.summary) or "")
        self.branch = str(event.get("branch", self.branch) or "")
        self.files = normalize_files(event.get("files", self.files))
        self.pr = str(event.get("pr", self.pr) or "")
        self.next = str(event.get("next", self.next) or "")
        self.blocked_by = str(event.get("blocked_by", self.blocked_by) or "")
        self.cost_cny = str(event.get("cost_cny", self.cost_cny) or "")
        self.risk = str(event.get("risk", self.risk) or "")
        self.updated_at = str(event.get("timestamp_utc", self.updated_at) or "")
        self.expires_at = str(event.get("expires_at", self.expires_at) or "")
        self.history_count += 1

        if event_type in TERMINAL_EVENTS or event_type == "BLOCKED":
            self.active = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "active": self.active,
            "last_event": self.event,
            "human_owner": self.human_owner,
            "executor": self.executor,
            "reviewer": self.reviewer,
            "summary": self.summary,
            "branch": self.branch,
            "files": self.files,
            "pr": self.pr,
            "next": self.next,
            "blocked_by": self.blocked_by,
            "cost_cny": self.cost_cny,
            "risk": self.risk,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "history_count": self.history_count,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay ai-progress.v2 events into an AIOS task registry."
    )
    parser.add_argument(
        "path",
        help="JSON file containing ai-progress events, comments, or comments response.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the registry snapshot as JSON.",
    )
    args = parser.parse_args()

    snapshot = build_registry(load_events(Path(args.path)))
    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    else:
        for task in snapshot["tasks"]:
            marker = "active" if task["active"] else "inactive"
            print(f"{task['task_id']}: {task['status']} ({marker})")
    return 0


def load_events(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))

    if isinstance(raw, list):
        if all(progress_conflicts.is_event(item) for item in raw):
            return [progress_conflicts.normalize_event(item) for item in raw]
        return progress_conflicts.events_from_comments(raw)

    if isinstance(raw, dict):
        if progress_conflicts.is_event(raw):
            return [progress_conflicts.normalize_event(raw)]
        comments = raw.get("comments")
        if isinstance(comments, list):
            return progress_conflicts.events_from_comments(comments)

    raise ValueError("Input must be an event, event list, comments list, or comments response.")


def build_registry(events: list[dict[str, Any]]) -> dict[str, Any]:
    states: dict[str, TaskState] = {}
    sorted_events = sorted(events, key=lambda item: str(item.get("timestamp_utc", "")))

    for event in sorted_events:
        task_id = str(event.get("task", "")).strip()
        if not task_id:
            continue
        state = states.setdefault(task_id, TaskState(task_id=task_id))
        state.apply(event)

    tasks = [state.to_dict() for state in states.values()]
    tasks.sort(key=lambda item: item["task_id"])
    return {
        "schema": "ai-task-registry.v1",
        "source_schema": "ai-progress.v2",
        "summary": summarize(tasks, len(sorted_events)),
        "tasks": tasks,
    }


def summarize(tasks: list[dict[str, Any]], event_count: int) -> dict[str, int]:
    return {
        "events": event_count,
        "tasks": len(tasks),
        "active": sum(1 for task in tasks if task["active"]),
        "done": sum(1 for task in tasks if task["status"] == "done"),
        "blocked": sum(1 for task in tasks if task["status"] == "blocked"),
        "released": sum(1 for task in tasks if task["status"] == "released"),
    }


def status_from_event(event: dict[str, Any]) -> str:
    event_type = str(event.get("event", ""))
    if event_type == "DONE":
        return "done"
    if event_type == "BLOCKED":
        return "blocked"
    if event_type == "RELEASE":
        return "released"
    return str(event.get("status") or "in_progress")


def normalize_files(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"SPEC_BLOCKED: {exc}", file=sys.stderr)
        raise SystemExit(1)
