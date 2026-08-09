"""Read-only AIOS K1 reconciliation checks."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


ACTIVE_BACKLOG_STATES = {"APPROVED", "IN_PROGRESS", "BLOCKED", "DELIVERED_UNWIRED"}


def reconcile(
    *,
    backlog_items: Sequence[Mapping[str, Any]] = (),
    manifests: Sequence[Mapping[str, Any]] = (),
    registry_snapshot: Mapping[str, Any] | None = None,
    progress_events: Sequence[Mapping[str, Any]] = (),
    pull_requests: Sequence[Mapping[str, Any]] = (),
    doc_claims: Sequence[Mapping[str, Any]] = (),
    alerts: Sequence[Mapping[str, Any]] = (),
    followups: Sequence[Mapping[str, Any]] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return K1 reconciliation gaps without mutating external systems."""

    now = now or datetime.now(timezone.utc)
    manifest_ids = {
        item.get("task_id") for item in manifests if isinstance(item.get("task_id"), str)
    }
    registry_tasks = (registry_snapshot or {}).get("tasks", {})
    pr_by_number = _pr_index(pull_requests)

    return {
        "schema": "ai-os-reconciliation.v1",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "orphan_tasks": _orphan_tasks(backlog_items, manifest_ids, registry_tasks),
        "stale_claims": _stale_claims(progress_events, now),
        "unlinked_prs": _unlinked_prs(pull_requests),
        "oversold_done": _oversold_done(progress_events, registry_tasks, pr_by_number),
        "delivered_unwired": _delivered_unwired(backlog_items, pull_requests),
        "stale_docs": _stale_docs(doc_claims),
        "unconsumed_alerts": _unconsumed_alerts(alerts),
        "missing_followups": _missing_followups(followups),
    }


def _orphan_tasks(
    backlog_items: Sequence[Mapping[str, Any]],
    manifest_ids: set[Any],
    registry_tasks: Mapping[str, Any],
) -> list[dict[str, Any]]:
    findings = []
    for item in backlog_items:
        task_id = item.get("id") or item.get("task_id")
        status = item.get("status")
        has_issue = bool(item.get("issue"))
        if (
            status in ACTIVE_BACKLOG_STATES
            and not has_issue
            and task_id not in manifest_ids
            and task_id not in registry_tasks
        ):
            findings.append(
                {
                    "task_id": task_id,
                    "status": status,
                    "reason": "active backlog item has no issue, manifest, or registry state",
                }
            )
    return findings


def _stale_claims(
    progress_events: Sequence[Mapping[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    active: dict[str, Mapping[str, Any]] = {}
    for event in progress_events:
        task = event.get("task")
        kind = event.get("event")
        if not isinstance(task, str):
            continue
        if kind == "CLAIM":
            active[task] = event
        elif kind in {"DONE", "RELEASE"}:
            active.pop(task, None)

    findings = []
    for task, event in active.items():
        expires_at = _parse_time(event.get("expires_at"))
        if isinstance(expires_at, str):
            findings.append(
                {
                    "task": task,
                    "expires_at": event.get("expires_at"),
                    "reason": expires_at,
                }
            )
        elif expires_at < now:
            findings.append(
                {
                    "task": task,
                    "expires_at": event.get("expires_at"),
                    "reason": "CLAIM expired without DONE or RELEASE",
                }
            )
    return findings


def _unlinked_prs(pull_requests: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for pr in pull_requests:
        if pr.get("state") != "OPEN":
            continue
        missing = [
            name
            for name in ("linked_issue", "ai_id", "has_acceptance", "has_progress_claim")
            if not pr.get(name)
        ]
        # governance-mutation: AIOS_K1_UNLINKED_OPEN_PR
        if missing:
            findings.append(
                {
                    "pr": pr.get("number"),
                    "missing": missing,
                    "reason": "open PR is not fully linked to AIOS control records",
                }
            )
    return findings


def _oversold_done(
    progress_events: Sequence[Mapping[str, Any]],
    registry_tasks: Mapping[str, Any],
    pr_by_number: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    findings = []
    for event in progress_events:
        if event.get("event") == "DONE":
            missing = [name for name in ("pr", "next", "cost_cny") if not event.get(name)]
            # governance-mutation: AIOS_K1_OVERSOLD_DONE_EVIDENCE
            if missing:
                findings.append(
                    {
                        "task": event.get("task"),
                        "missing": missing,
                        "reason": "DONE comment lacks required evidence fields",
                    }
                )
                continue
            findings.extend(
                _pr_findings(
                    owner={"task": event.get("task")},
                    pr_value=event.get("pr"),
                    pr_by_number=pr_by_number,
                    done_context=True,
                )
            )
    for task_id, state in registry_tasks.items():
        if state.get("state") == "DONE" and not state.get("evidence_refs"):
            findings.append(
                {
                    "task": task_id,
                    "missing": ["evidence_refs"],
                    "reason": "registry DONE lacks evidence refs",
                }
            )
            continue
        if state.get("state") in {"DONE", "MERGED"}:
            pr_values = [
                value
                for value in state.get("evidence_refs", [])
                if _pr_number(value) is not None
            ]
            if not pr_values:
                findings.append(
                    {
                        "task": task_id,
                        "pr": state.get("evidence_refs", []),
                        "reason": f"registry {state.get('state')} lacks parseable PR evidence",
                    }
                )
                continue
            for pr_value in pr_values:
                findings.extend(
                    _pr_findings(
                        owner={"task": task_id},
                        pr_value=pr_value,
                        pr_by_number=pr_by_number,
                        done_context=state.get("state") == "DONE",
                        registry_state=state.get("state"),
                    )
                )
    return findings


def _delivered_unwired(
    backlog_items: Sequence[Mapping[str, Any]],
    pull_requests: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    findings = []
    for item in backlog_items:
        if item.get("status") == "DELIVERED_UNWIRED":
            findings.append(
                {
                    "task_id": item.get("id") or item.get("task_id"),
                    "reason": "backlog item is delivered but not wired to a consumer",
                }
            )
    for pr in pull_requests:
        if pr.get("state") == "MERGED" and pr.get("requires_runtime") and not pr.get(
            "runtime_verified"
        ):
            findings.append(
                {"pr": pr.get("number"), "reason": "merged PR requires runtime verification"}
            )
    return findings


def _stale_docs(doc_claims: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"path": item.get("path"), "claim": item.get("claim"), "actual": item.get("actual")}
        for item in doc_claims
        if item.get("claim") and item.get("actual") and item.get("claim") != item.get("actual")
    ]


def _unconsumed_alerts(alerts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "alert_id": item.get("id"),
            "severity": item.get("severity"),
            "reason": "high alert is not acknowledged",
        }
        for item in alerts
        if item.get("severity") in {"HIGH", "BLOCKER"} and not item.get("ack")
    ]


def _missing_followups(followups: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source": item.get("source"),
            "summary": item.get("summary"),
            "reason": "follow-up has no A-ID/R-ID/Issue",
        }
        for item in followups
        if not (item.get("id") or item.get("issue"))
    ]


def _parse_time(value: Any) -> datetime | str:
    if not isinstance(value, str) or not value.strip():
        return "CLAIM expires_at is missing"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "CLAIM expires_at is invalid"
    if parsed.tzinfo is None:
        return "CLAIM expires_at must include timezone"
    return parsed.astimezone(timezone.utc)


def _pr_index(pull_requests: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    index = {}
    for pr in pull_requests:
        number = pr.get("number")
        if isinstance(number, int) and not isinstance(number, bool):
            index[number] = pr
    return index


def _pr_findings(
    *,
    owner: dict[str, Any],
    pr_value: Any,
    pr_by_number: Mapping[int, Mapping[str, Any]],
    done_context: bool,
    registry_state: str | None = None,
) -> list[dict[str, Any]]:
    number = _pr_number(pr_value)
    if number is None:
        return [{**owner, "pr": pr_value, "reason": "PR reference is not parseable"}]
    pr = pr_by_number.get(number)
    # governance-mutation: AIOS_K1_UNKNOWN_PR
    if pr is None:
        return [{**owner, "pr": number, "reason": "DONE references unknown PR"}]

    findings = []
    state = pr.get("state")
    if state == "OPEN" and registry_state == "MERGED":
        findings.append(
            {**owner, "pr": number, "reason": "registry MERGED references PR that is still open"}
        )
    elif done_context and state != "MERGED":
        findings.append({**owner, "pr": number, "reason": "DONE references PR that is not merged"})
    if done_context and pr.get("requires_runtime") and not pr.get("runtime_verified"):
        findings.append(
            {
                **owner,
                "pr": number,
                "reason": "DONE references PR without required runtime verification",
            }
        )
    return findings


def _pr_number(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    patterns = (
        r"(?i)^PR#(\d+)$",
        r"^!(\d+)$",
        r"(?i)(?:^|/)pull/(\d+)(?:\b|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None
