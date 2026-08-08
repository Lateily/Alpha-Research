"""Append-only AIOS event replay for K1 task state."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping, Sequence


STATES = {
    "DISCOVERED",
    "TRIAGED",
    "SPEC_READY",
    "CLAIMED",
    "RUNNING",
    "VERIFYING",
    "REVIEWING",
    "AWAITING_APPROVAL",
    "MERGED",
    "DEPLOYED",
    "VALIDATING",
    "DONE",
    "SPEC_BLOCKED",
    "BLOCKED",
    "RELEASED",
    "FAILED",
    "SUPERSEDED",
    "RETIRED",
    "DELIVERED_UNWIRED",
}
ALLOWED_TRANSITIONS = {
    ("DISCOVERED", "TRIAGED"),
    ("TRIAGED", "SPEC_READY"),
    ("TRIAGED", "SPEC_BLOCKED"),
    ("SPEC_BLOCKED", "SPEC_READY"),
    ("SPEC_READY", "CLAIMED"),
    ("SPEC_READY", "BLOCKED"),
    ("CLAIMED", "RUNNING"),
    ("CLAIMED", "RELEASED"),
    ("CLAIMED", "BLOCKED"),
    ("RELEASED", "CLAIMED"),
    ("RUNNING", "VERIFYING"),
    ("RUNNING", "FAILED"),
    ("RUNNING", "BLOCKED"),
    ("VERIFYING", "REVIEWING"),
    ("VERIFYING", "FAILED"),
    ("VERIFYING", "BLOCKED"),
    ("REVIEWING", "AWAITING_APPROVAL"),
    ("REVIEWING", "FAILED"),
    ("REVIEWING", "BLOCKED"),
    ("AWAITING_APPROVAL", "MERGED"),
    ("AWAITING_APPROVAL", "RETIRED"),
    ("AWAITING_APPROVAL", "BLOCKED"),
    ("MERGED", "DEPLOYED"),
    ("MERGED", "VALIDATING"),
    ("MERGED", "DELIVERED_UNWIRED"),
    ("DEPLOYED", "VALIDATING"),
    ("VALIDATING", "DONE"),
    ("VALIDATING", "FAILED"),
    ("VALIDATING", "BLOCKED"),
    ("DELIVERED_UNWIRED", "VALIDATING"),
    ("BLOCKED", "SPEC_READY"),
    ("BLOCKED", "CLAIMED"),
    ("BLOCKED", "RUNNING"),
    ("BLOCKED", "VERIFYING"),
    ("BLOCKED", "REVIEWING"),
    ("BLOCKED", "AWAITING_APPROVAL"),
    ("FAILED", "RUNNING"),
}


@dataclass
class TaskState:
    task_id: str
    state: str = "DISCOVERED"
    events: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    last_timestamp: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "state": self.state,
            "events": list(self.events),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass
class RegistrySnapshot:
    tasks: dict[str, TaskState]
    invalid_events: list[dict[str, Any]]
    duplicate_events: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ai-registry.snapshot.v1",
            "tasks": {
                task_id: state.to_dict()
                for task_id, state in sorted(self.tasks.items())
            },
            "invalid_events": list(self.invalid_events),
            "duplicate_events": list(self.duplicate_events),
        }


def replay_events(events: Sequence[Mapping[str, Any]]) -> RegistrySnapshot:
    tasks: dict[str, TaskState] = {}
    invalid_events: list[dict[str, Any]] = []
    duplicate_events: list[str] = []
    seen: dict[str, str] = {}

    for index, event in enumerate(events):
        event_id = event.get("event_id")
        fingerprint = _fingerprint(event)
        if not isinstance(event_id, str) or not event_id.strip():
            invalid_events.append(
                _invalid(index, event, "event_id must be a non-empty string")
            )
            continue
        if event_id in seen:
            if seen[event_id] != fingerprint:
                invalid_events.append(
                    _invalid(index, event, "event_id reused with different payload")
                )
            else:
                duplicate_events.append(event_id)
            continue
        seen[event_id] = fingerprint

        error = _validate_event(event)
        if error:
            invalid_events.append(_invalid(index, event, error))
            continue
        timestamp = _parse_timestamp(str(event["timestamp_utc"]))
        if isinstance(timestamp, str):
            invalid_events.append(_invalid(index, event, timestamp))
            continue

        task_id = str(event["task_id"])
        current = tasks.setdefault(task_id, TaskState(task_id=task_id))
        from_state = event.get("from_state", current.state)
        to_state = event["to_state"]
        evidence_refs = _string_list(event.get("evidence_refs", []))

        if from_state != current.state:
            invalid_events.append(
                _invalid(
                    index,
                    event,
                    f"from_state {from_state} does not match current {current.state}",
                )
            )
            continue
        if current.last_timestamp and timestamp < current.last_timestamp:
            invalid_events.append(
                _invalid(index, event, "timestamp_utc is older than current task state")
            )
            continue
        if (from_state, to_state) not in ALLOWED_TRANSITIONS:
            invalid_events.append(
                _invalid(index, event, f"transition {from_state}->{to_state} is not allowed")
            )
            continue
        if to_state == "DONE" and not evidence_refs:
            invalid_events.append(_invalid(index, event, "DONE requires evidence_refs"))
            continue

        current.state = to_state
        current.events.append(event_id)
        current.evidence_refs.extend(evidence_refs)
        current.last_timestamp = timestamp

    return RegistrySnapshot(tasks, invalid_events, duplicate_events)


def _validate_event(event: Mapping[str, Any]) -> str | None:
    for field_name in (
        "task_id",
        "from_state",
        "to_state",
        "actor",
        "reason",
        "timestamp_utc",
    ):
        value = event.get(field_name)
        if not isinstance(value, str) or not value.strip():
            return f"{field_name} must be a non-empty string"
    if event["from_state"] not in STATES:
        return "from_state is not supported"
    if event["to_state"] not in STATES:
        return "to_state is not supported"
    if not isinstance(event.get("evidence_refs", []), list):
        return "evidence_refs must be a list"
    if not all(
        isinstance(item, str) and item.strip()
        for item in event.get("evidence_refs", [])
    ):
        return "evidence_refs must contain non-empty strings"
    return None


def _invalid(index: int, event: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "index": index,
        "event_id": event.get("event_id"),
        "task_id": event.get("task_id"),
        "reason": reason,
    }


def _fingerprint(event: Mapping[str, Any]) -> str:
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _parse_timestamp(value: str) -> datetime | str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "timestamp_utc is invalid"
    if parsed.tzinfo is None:
        return "timestamp_utc must include timezone"
    return parsed.astimezone(timezone.utc)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
