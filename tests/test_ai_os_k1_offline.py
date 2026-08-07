"""Offline tests for AIOS-K1 task contracts, registry, and reconciler."""

from __future__ import annotations

import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))

from ai_os.reconciler import reconcile  # noqa: E402
from ai_os.registry import replay_events  # noqa: E402
from ai_os.task_compiler import SPEC_BLOCKED, SPEC_READY, compile_task_manifest  # noqa: E402


NOW = datetime(2026, 8, 7, 9, 30, tzinfo=timezone.utc)


def valid_task_source(**overrides):
    source = {
        "schema": "ai-task.v1",
        "task_id": "A-006-task-manifest",
        "source_issue": 193,
        "architecture_block": ["块6-AI系统"],
        "objective": "Create a read-only AIOS task manifest contract.",
        "non_goals": ["Do not call model APIs"],
        "human_owner": "Reed",
        "reviewer": "Junyan",
        "executor_candidates": ["Codex"],
        "dependencies": ["A-004"],
        "authority_docs": ["docs/llm/AI_OS_BUILD_GUIDE.md"],
        "file_scope": ["scripts/llm/ai_os", "docs/llm"],
        "forbidden_scope": ["experiments/execution_tracker"],
        "input_contracts": [],
        "output_artifacts": ["scripts/llm/schemas/task.schema.json"],
        "acceptance_tests": ["tests/test_ai_os_k1_offline.py"],
        "risk_level": "LOW",
        "network_policy": "OFFLINE",
        "budget": {"max_cny": "0", "max_minutes": 60},
        "approval_gates": ["PR_REVIEW", "JUNYAN_MERGE"],
    }
    source.update(overrides)
    return source


def event(event_id, from_state, to_state, evidence_refs=None):
    return {
        "event_id": event_id,
        "task_id": "A-006-task-manifest",
        "from_state": from_state,
        "to_state": to_state,
        "actor": "Codex",
        "reason": f"{from_state}->{to_state}",
        "evidence_refs": evidence_refs or [],
        "timestamp_utc": "2026-08-07T09:00:00Z",
    }


def test_task_manifest_compiles_complete_contract() -> None:
    result = compile_task_manifest(valid_task_source(), now=NOW)

    assert result.status == SPEC_READY
    assert result.errors == ()
    assert result.manifest is not None
    assert result.manifest["schema"] == "ai-task.v1"
    assert result.manifest["created_at"] == "2026-08-07T09:30:00+00:00"
    assert result.manifest["budget"] == {"max_cny": "0", "max_minutes": 60}
    assert result.manifest["source_hash"].startswith("sha256:")
    json.dumps(result.to_dict(), ensure_ascii=False)


def test_task_manifest_missing_acceptance_fails_closed() -> None:
    result = compile_task_manifest(valid_task_source(acceptance_tests=[]), now=NOW)

    assert result.status == SPEC_BLOCKED
    assert result.manifest is None
    assert "acceptance_tests must be a non-empty string list" in result.errors


def test_task_manifest_rejects_bad_budget_and_network() -> None:
    result = compile_task_manifest(
        valid_task_source(
            budget={"max_cny": "-1", "max_minutes": True},
            network_policy="OPEN_INTERNET",
        ),
        now=NOW,
    )

    assert result.status == SPEC_BLOCKED
    assert result.manifest is None
    assert "network_policy is not supported" in result.errors
    assert "budget.max_cny must be non-negative" in result.errors


def test_registry_replays_events_idempotently() -> None:
    events = [
        event("evt-1", "DISCOVERED", "TRIAGED"),
        event("evt-2", "TRIAGED", "SPEC_READY"),
        event("evt-2", "TRIAGED", "SPEC_READY"),
        event("evt-3", "SPEC_READY", "DONE", ["pr#1", "test#1"]),
    ]

    snapshot = replay_events(events).to_dict()

    assert snapshot["tasks"]["A-006-task-manifest"]["state"] == "DONE"
    assert snapshot["duplicate_events"] == ["evt-2"]
    assert snapshot["invalid_events"] == []
    assert snapshot["tasks"]["A-006-task-manifest"]["evidence_refs"] == [
        "pr#1",
        "test#1",
    ]


def test_registry_blocks_forbidden_done_shortcut() -> None:
    snapshot = replay_events(
        [
            event("evt-1", "DISCOVERED", "TRIAGED"),
            event("evt-2", "TRIAGED", "SPEC_READY"),
            event("evt-3", "SPEC_READY", "CLAIMED"),
            event("evt-4", "CLAIMED", "RUNNING"),
            event("evt-5", "RUNNING", "DONE", ["pr#1"]),
        ]
    ).to_dict()

    assert snapshot["tasks"]["A-006-task-manifest"]["state"] == "RUNNING"
    assert snapshot["invalid_events"][0]["reason"] == "forbidden shortcut RUNNING->DONE"


def test_registry_requires_done_evidence() -> None:
    snapshot = replay_events(
        [
            event("evt-1", "DISCOVERED", "TRIAGED"),
            event("evt-2", "TRIAGED", "SPEC_READY"),
            event("evt-3", "SPEC_READY", "DONE"),
        ]
    ).to_dict()

    assert snapshot["tasks"]["A-006-task-manifest"]["state"] == "SPEC_READY"
    assert snapshot["invalid_events"][0]["reason"] == "DONE requires evidence_refs"


def test_reconciler_reports_k1_gaps() -> None:
    report = reconcile(
        backlog_items=[
            {"id": "A-006", "status": "APPROVED"},
            {"id": "A-003", "status": "DELIVERED_UNWIRED", "issue": 161},
        ],
        manifests=[],
        registry_snapshot={
            "tasks": {
                "A-020": {"state": "DONE", "evidence_refs": []},
            }
        },
        progress_events=[
            {
                "event": "CLAIM",
                "task": "#193",
                "expires_at": "2026-08-07T08:00:00Z",
            },
            {"event": "DONE", "task": "#237", "cost_cny": "0"},
        ],
        pull_requests=[
            {"number": 250, "state": "OPEN", "linked_issue": None},
            {
                "number": 251,
                "state": "MERGED",
                "requires_runtime": True,
                "runtime_verified": False,
            },
        ],
        doc_claims=[
            {"path": "docs/llm/x.md", "claim": "待合并", "actual": "已合并"},
        ],
        alerts=[{"id": "alert-1", "severity": "HIGH", "ack": False}],
        followups=[{"source": "memory-1", "summary": "Add prompt red-team"}],
        now=NOW,
    )

    assert report["schema"] == "ai-os-reconciliation.v1"
    assert report["orphan_tasks"][0]["task_id"] == "A-006"
    assert report["stale_claims"][0]["task"] == "#193"
    assert report["unlinked_prs"][0]["pr"] == 250
    assert report["oversold_done"][0]["task"] == "#237"
    assert report["oversold_done"][1]["task"] == "A-020"
    assert report["delivered_unwired"][0]["task_id"] == "A-003"
    assert report["delivered_unwired"][1]["pr"] == 251
    assert report["stale_docs"][0]["path"] == "docs/llm/x.md"
    assert report["unconsumed_alerts"][0]["alert_id"] == "alert-1"
    assert report["missing_followups"][0]["source"] == "memory-1"
    json.dumps(report, ensure_ascii=False)


def test_ai_os_k1_has_zero_network_surface() -> None:
    original_socket = socket.socket

    def blocked_socket(*_args, **_kwargs):
        raise AssertionError("network access is forbidden in AIOS-K1 tests")

    socket.socket = blocked_socket
    try:
        result = compile_task_manifest(valid_task_source(), now=NOW)
        report = reconcile(now=NOW)
    finally:
        socket.socket = original_socket

    assert result.status == SPEC_READY
    assert report["schema"] == "ai-os-reconciliation.v1"


def run_all_tests() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    return len(tests)


if __name__ == "__main__":
    test_count = run_all_tests()
    print(f"ALL AIOS K1 OFFLINE TESTS PASS ({test_count} tests, 0 network calls)")
