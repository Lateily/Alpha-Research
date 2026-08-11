"""Offline tests for AIOS A-011 Scheduler readiness gates."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))

from ai_os.scheduler import (  # noqa: E402
    SCHEDULE_BLOCKED,
    SCHEDULE_READY,
    build_schedule,
)
from ai_os.task_compiler import compile_task_manifest  # noqa: E402


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)
HASH = "sha256:" + "a" * 64


def manifest(task_id="A-011-scheduler", dependencies=None):
    source = {
        "schema": "ai-task.v1",
        "task_id": task_id,
        "source_issue": 194,
        "architecture_block": ["block-6-aios"],
        "objective": "Schedule only ready AIOS work.",
        "non_goals": ["Do not call Router", "Do not execute Agents"],
        "human_owner": "Reed",
        "reviewer": "Junyan",
        "executor_candidates": ["Codex"],
        "dependencies": dependencies or [],
        "authority_docs": ["docs/llm/AI_OS_BUILD_GUIDE.md"],
        "file_scope": ["scripts/llm/ai_os", "docs/llm"],
        "forbidden_scope": ["experiments/execution_tracker"],
        "input_contracts": ["scripts/llm/schemas/task.schema.json"],
        "output_artifacts": ["scripts/llm/schemas/schedule.schema.json"],
        "acceptance_tests": ["tests/test_ai_os_a011_scheduler_offline.py"],
        "risk_level": "LOW",
        "network_policy": "OFFLINE",
        "budget": {"max_cny": "0", "max_minutes": 60},
        "approval_gates": ["PR_REVIEW", "JUNYAN_MERGE"],
    }
    result = compile_task_manifest(source, now=NOW)
    assert result.manifest is not None, result.errors
    return result.manifest


def policy(task_id, status="POLICY_ALLOWED"):
    return {"task_id": task_id, "status": status}


def context(task_id, status="CONTEXT_READY", loaded_at=NOW, freshness="PINNED"):
    return {
        "task_id": task_id,
        "status": status,
        "context": {
            "context_hash": HASH,
            "freshness": {"status": freshness, "reason": "test"},
            "loaded_at": loaded_at.isoformat(),
        },
    }


def registry_state(task_id, state):
    return {
        "schema": "ai-registry.snapshot.v1",
        "tasks": {task_id: {"state": state, "evidence_refs": ["PR#1"]}},
        "invalid_events": [],
        "duplicate_events": [],
    }


def test_scheduler_marks_ready_when_dependencies_policy_and_context_are_ready() -> None:
    task = manifest(dependencies=["A-010"])
    result = build_schedule(
        manifests=[task],
        registry_snapshot=registry_state("A-010", "DONE"),
        policy_decisions=[policy("A-011-scheduler")],
        context_packets=[context("A-011-scheduler")],
        now=NOW,
    ).to_dict()

    assert result["status"] == SCHEDULE_READY
    assert result["report"]["ready"][0]["task_id"] == "A-011-scheduler"
    assert result["report"]["blocked"] == []


def test_scheduler_blocks_dependency_that_is_missing_or_not_done() -> None:
    waiting = build_schedule(
        manifests=[manifest(dependencies=["A-010"])],
        registry_snapshot=registry_state("A-010", "MERGED"),
        policy_decisions=[policy("A-011-scheduler")],
        context_packets=[context("A-011-scheduler")],
        now=NOW,
    ).to_dict()
    missing = build_schedule(
        manifests=[manifest(dependencies=["A-999"])],
        policy_decisions=[policy("A-011-scheduler")],
        context_packets=[context("A-011-scheduler")],
        now=NOW,
    ).to_dict()

    assert waiting["status"] == SCHEDULE_BLOCKED
    assert "dependency A-010 is not DONE" in waiting["report"]["blocked"][0]["reasons"]
    assert "dependency A-999 is not DONE" in missing["report"]["blocked"][0]["reasons"]


def test_scheduler_blocks_cyclic_dependencies() -> None:
    first = manifest(task_id="A-cycle-1", dependencies=["A-cycle-2"])
    second = manifest(task_id="A-cycle-2", dependencies=["A-cycle-1"])
    result = build_schedule(
        manifests=[first, second],
        policy_decisions=[policy("A-cycle-1"), policy("A-cycle-2")],
        context_packets=[context("A-cycle-1"), context("A-cycle-2")],
        now=NOW,
    ).to_dict()

    assert result["status"] == SCHEDULE_BLOCKED
    assert {item["task_id"] for item in result["report"]["blocked"]} == {
        "A-cycle-1",
        "A-cycle-2",
    }
    assert all(
        "cyclic dependency" in item["reasons"]
        for item in result["report"]["blocked"]
    )


def test_scheduler_blocks_policy_and_context_failures_before_router() -> None:
    result = build_schedule(
        manifests=[manifest()],
        policy_decisions=[policy("A-011-scheduler", "POLICY_BLOCKED")],
        context_packets=[context("A-011-scheduler", status="SPEC_BLOCKED")],
        now=NOW,
    ).to_dict()

    assert result["status"] == SCHEDULE_BLOCKED
    reasons = result["report"]["blocked"][0]["reasons"]
    assert "policy status is POLICY_BLOCKED" in reasons
    assert "context status is SPEC_BLOCKED" in reasons


def test_scheduler_blocks_stale_or_unpinned_context() -> None:
    stale = build_schedule(
        manifests=[manifest()],
        policy_decisions=[policy("A-011-scheduler")],
        context_packets=[
            context("A-011-scheduler", loaded_at=NOW - timedelta(days=2))
        ],
        now=NOW,
    ).to_dict()
    unpinned = build_schedule(
        manifests=[manifest()],
        policy_decisions=[policy("A-011-scheduler")],
        context_packets=[context("A-011-scheduler", freshness="UNKNOWN")],
        now=NOW,
    ).to_dict()

    assert "context is stale" in stale["report"]["blocked"][0]["reasons"]
    assert "context freshness is not PINNED" in unpinned["report"]["blocked"][0]["reasons"]


def test_scheduler_rejects_malformed_manifest_inputs() -> None:
    result = build_schedule(
        manifests=[{"schema": "ai-task.v0", "task_id": "bad"}],
        policy_decisions=[],
        context_packets=[],
        now=NOW,
    ).to_dict()

    assert result["status"] == SCHEDULE_BLOCKED
    assert result["report"]["invalid_inputs"] == ["manifest[0].schema must be ai-task.v1"]


def test_scheduler_rejects_bad_context_age_without_crashing() -> None:
    result = build_schedule(
        manifests=[manifest()],
        policy_decisions=[policy("A-011-scheduler")],
        context_packets=[context("A-011-scheduler")],
        now=NOW,
        max_context_age_minutes="24h",
    ).to_dict()

    assert result["status"] == SCHEDULE_BLOCKED
    assert result["report"]["ready"] == []
    assert result["report"]["blocked"][0]["reasons"] == ["scheduler input is invalid"]
    assert result["report"]["invalid_inputs"] == [
        "max_context_age_minutes must be a positive integer"
    ]


def test_scheduler_cli_returns_nonzero_for_blocked_and_zero_for_ready() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        blocked_path = Path(temp_dir) / "blocked.json"
        ready_path = Path(temp_dir) / "ready.json"
        blocked_path.write_text(
            json.dumps(
                {
                    "manifests": [manifest()],
                    "policy_decisions": [policy("A-011-scheduler", "POLICY_BLOCKED")],
                    "context_packets": [context("A-011-scheduler")],
                }
            ),
            encoding="utf-8-sig",
        )
        ready_path.write_text(
            json.dumps(
                {
                    "manifests": [manifest()],
                    "policy_decisions": [policy("A-011-scheduler")],
                    "context_packets": [context("A-011-scheduler")],
                }
            ),
            encoding="utf-8-sig",
        )
        blocked = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "llm" / "ai_os" / "cli.py"),
                "schedule",
                "--input",
                str(blocked_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        ready = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "llm" / "ai_os" / "cli.py"),
                "schedule",
                "--input",
                str(ready_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    assert blocked.returncode == 1
    assert '"status": "SCHEDULE_BLOCKED"' in blocked.stdout
    assert ready.returncode == 0
    assert '"status": "SCHEDULE_READY"' in ready.stdout


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
    count = run_all_tests()
    print(f"ALL AIOS A-011 SCHEDULER TESTS PASS ({count} tests, 0 network calls)")
