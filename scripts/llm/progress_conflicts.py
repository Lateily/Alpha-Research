"""Read AI Progress Board events and warn on overlapping active CLAIMs."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FENCED_JSON_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check AI Progress Board events for active file-scope conflicts."
    )
    parser.add_argument(
        "path",
        help=(
            "JSON file containing progress events, GitHub issue comments, or a "
            "connector response with a comments array."
        ),
    )
    parser.add_argument(
        "--now",
        default=None,
        help="Override current time for deterministic checks, ISO timestamp.",
    )
    args = parser.parse_args()

    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    events = load_events(Path(args.path))
    conflicts = find_conflicts(events, now)

    if not conflicts:
        print("OK: no active overlapping CLAIMs found.")
        return 0

    print("WARNING: active overlapping CLAIMs found.")
    for left, right, files in conflicts:
        print(
            "- "
            f"{actor(left)} task={left.get('task')} "
            f"overlaps {actor(right)} task={right.get('task')} "
            f"files={', '.join(files)}"
        )
    return 1


def load_events(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(raw, list):
        if all(is_event(item) for item in raw):
            return [normalize_event(item) for item in raw]
        return events_from_comments(raw)

    if isinstance(raw, dict):
        if is_event(raw):
            return [normalize_event(raw)]
        comments = raw.get("comments")
        if isinstance(comments, list):
            return events_from_comments(comments)

    raise ValueError("Input must be an event, event list, comments list, or comments response.")


def events_from_comments(comments: list[Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for comment in comments:
        body = comment.get("body", "") if isinstance(comment, dict) else str(comment)
        for match in FENCED_JSON_RE.finditer(body):
            try:
                candidate = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if is_event(candidate):
                events.append(normalize_event(candidate))
    return events


def is_event(value: Any) -> bool:
    return isinstance(value, dict) and value.get("event") in {
        "CLAIM",
        "UPDATE",
        "DONE",
        "BLOCKED",
        "RELEASE",
    }


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(event)
    if "owner" in normalized and "human_owner" not in normalized:
        normalized["human_owner"] = normalized["owner"]
    normalized.setdefault("executor", "unknown")
    normalized.setdefault("reviewer", "unknown")
    if "expires_at_utc" in normalized and "expires_at" not in normalized:
        normalized["expires_at"] = normalized["expires_at_utc"]
    return normalized


def find_conflicts(
    events: list[dict[str, Any]], now: datetime
) -> list[tuple[dict[str, Any], dict[str, Any], list[str]]]:
    active = active_claims(events, now)
    conflicts: list[tuple[dict[str, Any], dict[str, Any], list[str]]] = []

    for idx, left in enumerate(active):
        for right in active[idx + 1 :]:
            overlap = overlapping_files(left.get("files", []), right.get("files", []))
            if overlap and actor(left) != actor(right):
                conflicts.append((left, right, overlap))
    return conflicts


def active_claims(events: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    sorted_events = sorted(events, key=lambda item: item.get("timestamp_utc", ""))
    claims_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

    for event in sorted_events:
        key = event_key(event)
        if event.get("event") in {"DONE", "RELEASE"}:
            claims_by_key.pop(key, None)
            continue
        if event.get("event") != "CLAIM":
            continue
        expires_at = parse_time(event.get("expires_at"))
        if expires_at > now:
            claims_by_key[key] = event

    return list(claims_by_key.values())


def event_key(event: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(event.get("task", "")),
        str(event.get("human_owner", "")),
        str(event.get("executor", "")),
    )


def overlapping_files(left: list[Any], right: list[Any]) -> list[str]:
    left_paths = [normalize_path(item) for item in left]
    right_paths = [normalize_path(item) for item in right]
    overlaps: list[str] = []

    for left_path in left_paths:
        for right_path in right_paths:
            if not left_path or not right_path:
                continue
            if (
                left_path == right_path
                or left_path.startswith(right_path + "/")
                or right_path.startswith(left_path + "/")
            ):
                overlaps.append(f"{left_path}<->{right_path}")
    return overlaps


def normalize_path(value: Any) -> str:
    return str(value).replace("\\", "/").strip().strip("/").lower()


def parse_time(value: Any) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    raw = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def actor(event: dict[str, Any]) -> str:
    return f"{event.get('human_owner')}:{event.get('executor')}"


if __name__ == "__main__":
    raise SystemExit(main())
