"""Generate AI Progress Board event blocks for GitHub comments."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from typing import Any


DEFAULT_TTL_MINUTES = 120


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a standard AI Progress Board event block."
    )
    parser.add_argument(
        "event",
        choices=("claim", "update", "done", "blocked", "release"),
        help="Progress event type.",
    )
    parser.add_argument("--task", required=True, help="Issue number or task name.")
    parser.add_argument("--summary", required=True, help="One-sentence summary.")
    parser.add_argument(
        "--human-owner",
        required=True,
        help="Human accountable for the work, for example Tianrui.",
    )
    parser.add_argument(
        "--executor",
        required=True,
        help="Person or tool doing the work, for example Codex.",
    )
    parser.add_argument(
        "--reviewer",
        required=True,
        help="Human reviewer or approver, for example Junyan.",
    )
    parser.add_argument("--branch", default=None, help="Working branch.")
    parser.add_argument(
        "--files",
        default="",
        help="Comma-separated file or folder scope, for example docs/llm,scripts/llm.",
    )
    parser.add_argument("--pr", default=None, help="Pull request URL.")
    parser.add_argument("--next", default=None, help="Next owner or next action.")
    parser.add_argument("--blocked-by", default=None, help="Current blocker.")
    parser.add_argument("--cost-cny", default=None, help="LLM cost in RMB.")
    parser.add_argument(
        "--risk",
        default="none",
        help="Safety or coordination risk, if any.",
    )
    parser.add_argument(
        "--ttl-minutes",
        type=int,
        default=DEFAULT_TTL_MINUTES,
        help="Minutes until a CLAIM becomes stale.",
    )
    parser.add_argument(
        "--expires-at",
        default=None,
        help="Explicit CLAIM expiry timestamp with timezone. Defaults to now + ttl.",
    )
    args = parser.parse_args()
    validate_args(parser, args)

    event = build_event(args)
    print("<!-- ai-progress:v2 -->")
    print("```json")
    print(json.dumps(event, ensure_ascii=False, indent=2))
    print("```")
    return 0


def build_event(args: argparse.Namespace) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    event_type = args.event.upper()
    status_by_event = {
        "CLAIM": "in_progress",
        "UPDATE": "in_progress",
        "DONE": "done",
        "BLOCKED": "blocked",
        "RELEASE": "released",
    }

    event: dict[str, Any] = {
        "schema": "ai-progress.v2",
        "event": event_type,
        "task": args.task,
        "human_owner": args.human_owner,
        "executor": args.executor,
        "reviewer": args.reviewer,
        "status": status_by_event[event_type],
        "summary": args.summary,
        "branch": args.branch,
        "files": split_csv(args.files),
        "pr": args.pr,
        "next": args.next,
        "blocked_by": args.blocked_by,
        "cost_cny": args.cost_cny,
        "risk": args.risk,
        "timestamp_utc": now.isoformat(),
    }

    if event_type == "CLAIM":
        event["expires_at"] = args.expires_at or (
            now + timedelta(minutes=max(args.ttl_minutes, 1))
        ).isoformat()

    return {key: value for key, value in event.items() if value not in (None, [], "")}


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.event != "claim":
        return
    if not args.branch:
        parser.error("CLAIM requires --branch.")
    if not split_csv(args.files):
        parser.error("CLAIM requires --files with at least one file or folder scope.")


def split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
