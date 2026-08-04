"""Reconcile AIOS task registry states into actionable findings.

This is an offline/read-only checker. It does not call model APIs and does not
write GitHub comments.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ai_registry


SEVERITY_ORDER = {"BLOCKER": 0, "MAJOR": 1, "MINOR": 2}


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    category: str
    task: str
    message: str
    evidence: str
    suggested_action: str

    def to_dict(self) -> dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "category": self.category,
            "task": self.task,
            "message": self.message,
            "evidence": self.evidence,
            "suggested_action": self.suggested_action,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile ai-progress.v2 events into AIOS findings."
    )
    parser.add_argument(
        "path",
        help="JSON file containing ai-progress events, comments, or comments response.",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="Override current time for deterministic checks, ISO timestamp.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print findings as JSON.",
    )
    parser.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="Exit 1 when any finding is produced.",
    )
    parser.add_argument(
        "--include-history-findings",
        action="store_true",
        help="Also report legacy/order findings such as DONE before CLAIM.",
    )
    args = parser.parse_args()

    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    events = ai_registry.load_events(Path(args.path))
    snapshot = reconcile(events, now, include_history_findings=args.include_history_findings)

    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    else:
        print_text(snapshot)

    if args.fail_on_findings and snapshot["summary"]["findings"] > 0:
        return 1
    return 0


def reconcile(
    events: list[dict[str, Any]],
    now: datetime,
    include_history_findings: bool = False,
) -> dict[str, Any]:
    registry = ai_registry.build_registry(events)
    tasks = registry["tasks"]
    findings = []
    findings.extend(find_stale_active_tasks(tasks, now))
    findings.extend(find_active_tasks_missing_scope(tasks))
    findings.extend(find_done_without_required_fields(tasks))
    findings.extend(find_blocked_without_next_step(tasks))
    findings.extend(find_active_file_conflicts(tasks, now))
    if include_history_findings:
        findings.extend(find_orphan_events(events))

    finding_dicts = [finding.to_dict() for finding in sorted_findings(findings)]
    return {
        "schema": "ai-reconciler.v1",
        "source_schema": registry["schema"],
        "summary": summarize(finding_dicts),
        "findings": finding_dicts,
    }


def find_stale_active_tasks(
    tasks: list[dict[str, Any]], now: datetime
) -> list[Finding]:
    findings: list[Finding] = []
    for task in tasks:
        if not task.get("active"):
            continue
        expires_at = str(task.get("expires_at", "") or "")
        parsed = try_parse_time(expires_at)
        if parsed is None:
            findings.append(
                Finding(
                    rule_id="AIOS-R001",
                    severity="MAJOR",
                    category="stale_or_bad_claim",
                    task=str(task.get("task_id", "")),
                    message="Active task has no valid expires_at timestamp.",
                    evidence=f"expires_at={expires_at or '<missing>'}",
                    suggested_action="Post UPDATE with a valid expires_at, DONE, BLOCKED, or RELEASE.",
                )
            )
            continue
        if parsed <= now:
            findings.append(
                Finding(
                    rule_id="AIOS-R002",
                    severity="MAJOR",
                    category="stale_or_bad_claim",
                    task=str(task.get("task_id", "")),
                    message="Active task is past its claimed expiry time.",
                    evidence=f"expires_at={expires_at}; now={now.isoformat()}",
                    suggested_action="Post UPDATE, DONE, BLOCKED, or RELEASE before others pick up the scope.",
                )
            )
    return findings


def find_active_tasks_missing_scope(tasks: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    for task in tasks:
        if not task.get("active"):
            continue
        missing = []
        if not task.get("branch"):
            missing.append("branch")
        if not task.get("files"):
            missing.append("files")
        if not missing:
            continue
        findings.append(
            Finding(
                rule_id="AIOS-R003",
                severity="MAJOR",
                category="incomplete_claim",
                task=str(task.get("task_id", "")),
                message="Active task is missing coordination scope.",
                evidence=f"missing={','.join(missing)}",
                suggested_action="Post UPDATE with branch and file scope so teammates can avoid collisions.",
            )
        )
    return findings


def find_done_without_required_fields(tasks: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    for task in tasks:
        if task.get("status") != "done":
            continue
        missing = []
        if not task.get("pr"):
            missing.append("pr")
        if str(task.get("cost_cny", "")).strip() == "":
            missing.append("cost_cny")
        if not missing:
            continue
        findings.append(
            Finding(
                rule_id="AIOS-R004",
                severity="MAJOR",
                category="incomplete_done",
                task=str(task.get("task_id", "")),
                message="DONE task is missing required handoff fields.",
                evidence=f"missing={','.join(missing)}",
                suggested_action="Post UPDATE or corrected DONE with PR link and cost_cny.",
            )
        )
    return findings


def find_blocked_without_next_step(tasks: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    for task in tasks:
        if task.get("status") != "blocked":
            continue
        missing = []
        if not task.get("blocked_by"):
            missing.append("blocked_by")
        if not task.get("next"):
            missing.append("next")
        if not missing:
            continue
        findings.append(
            Finding(
                rule_id="AIOS-R005",
                severity="MAJOR",
                category="incomplete_blocked",
                task=str(task.get("task_id", "")),
                message="BLOCKED task does not say what is blocking it and who should act next.",
                evidence=f"missing={','.join(missing)}",
                suggested_action="Post UPDATE/BLOCKED with blocked_by and next.",
            )
        )
    return findings


def find_active_file_conflicts(
    tasks: list[dict[str, Any]], now: datetime
) -> list[Finding]:
    active = [task for task in tasks if is_currently_claimed(task, now)]
    findings: list[Finding] = []
    for idx, left in enumerate(active):
        for right in active[idx + 1 :]:
            if actor(left) == actor(right):
                continue
            overlap = overlapping_files(left.get("files", []), right.get("files", []))
            if not overlap:
                continue
            findings.append(
                Finding(
                    rule_id="AIOS-R006",
                    severity="MAJOR",
                    category="file_conflict",
                    task=f"{left.get('task_id')} <-> {right.get('task_id')}",
                    message="Two active tasks claim overlapping file scope.",
                    evidence=f"files={'; '.join(overlap)}",
                    suggested_action="One owner should narrow files, release scope, or coordinate before editing.",
                )
            )
    return findings


def is_currently_claimed(task: dict[str, Any], now: datetime) -> bool:
    if not task.get("active"):
        return False
    expires_at = try_parse_time(str(task.get("expires_at", "") or ""))
    return expires_at is not None and expires_at > now


def find_orphan_events(events: list[dict[str, Any]]) -> list[Finding]:
    seen_claim: set[str] = set()
    findings: list[Finding] = []
    for event in sorted(events, key=lambda item: str(item.get("timestamp_utc", ""))):
        task_id = str(event.get("task", "")).strip()
        event_type = str(event.get("event", ""))
        if not task_id:
            continue
        if event_type == "CLAIM":
            seen_claim.add(task_id)
            continue
        if event_type in {"UPDATE", "DONE", "BLOCKED", "RELEASE"} and task_id not in seen_claim:
            findings.append(
                Finding(
                    rule_id="AIOS-R007",
                    severity="MAJOR",
                    category="orphan_event",
                    task=task_id,
                    message="Task has a progress event before any CLAIM.",
                    evidence=f"first_seen_event={event_type}; timestamp={event.get('timestamp_utc', '')}",
                    suggested_action="Add the missing CLAIM event or explain why this legacy event is exempt.",
                )
            )
            seen_claim.add(task_id)
    return findings


def summarize(findings: list[dict[str, str]]) -> dict[str, int]:
    return {
        "findings": len(findings),
        "blocker": sum(1 for item in findings if item["severity"] == "BLOCKER"),
        "major": sum(1 for item in findings if item["severity"] == "MAJOR"),
        "minor": sum(1 for item in findings if item["severity"] == "MINOR"),
    }


def sorted_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(
        findings,
        key=lambda item: (SEVERITY_ORDER.get(item.severity, 99), item.rule_id, item.task),
    )


def overlapping_files(left: Any, right: Any) -> list[str]:
    left_paths = [normalize_path(item) for item in left if normalize_path(item)]
    right_paths = [normalize_path(item) for item in right if normalize_path(item)]
    overlaps: list[str] = []
    for left_path in left_paths:
        for right_path in right_paths:
            if (
                left_path == right_path
                or left_path.startswith(right_path + "/")
                or right_path.startswith(left_path + "/")
            ):
                overlaps.append(f"{left_path}<->{right_path}")
    return overlaps


def normalize_path(value: Any) -> str:
    return str(value).replace("\\", "/").strip().strip("/").lower()


def actor(task: dict[str, Any]) -> str:
    return f"{task.get('human_owner')}:{task.get('executor')}"


def try_parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return parse_time(value)
    except ValueError:
        return None


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def print_text(snapshot: dict[str, Any]) -> None:
    summary = snapshot["summary"]
    if summary["findings"] == 0:
        print("OK: no AIOS reconciliation findings.")
        return

    print(
        "WARNING: "
        f"{summary['findings']} findings "
        f"(BLOCKER={summary['blocker']}, MAJOR={summary['major']}, MINOR={summary['minor']})."
    )
    for finding in snapshot["findings"]:
        print(
            "- "
            f"{finding['severity']} {finding['rule_id']} "
            f"{finding['task']}: {finding['message']} "
            f"[{finding['evidence']}]"
        )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"SPEC_BLOCKED: {exc}", file=sys.stderr)
        raise SystemExit(1)
