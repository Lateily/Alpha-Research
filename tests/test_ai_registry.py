"""Offline tests for the AIOS task registry seed.

Run with:
    python tests/test_ai_registry.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))

import ai_registry  # noqa: E402


FIXTURE = REPO_ROOT / "docs" / "llm" / "examples" / "ai-progress.registry.fixture.json"
COMMENTS_RESPONSE_FIXTURE = (
    REPO_ROOT
    / "docs"
    / "llm"
    / "examples"
    / "ai-progress.registry.comments-response.fixture.json"
)


def test_registry_replays_current_task_states() -> None:
    snapshot = ai_registry.build_registry(ai_registry.load_events(FIXTURE))

    assert snapshot["schema"] == "ai-task-registry.v1"
    assert snapshot["summary"] == {
        "events": 7,
        "tasks": 3,
        "active": 0,
        "done": 1,
        "blocked": 1,
        "released": 1,
    }

    tasks = {task["task_id"]: task for task in snapshot["tasks"]}
    assert tasks["task-alpha"]["status"] == "done"
    assert tasks["task-alpha"]["active"] is False
    assert tasks["task-alpha"]["pr"].endswith("/999")
    assert tasks["task-alpha"]["history_count"] == 3

    assert tasks["task-beta"]["status"] == "blocked"
    assert tasks["task-beta"]["blocked_by"] == "contract sign-off"
    assert tasks["task-beta"]["history_count"] == 2

    assert tasks["task-gamma"]["status"] == "released"
    assert tasks["task-gamma"]["active"] is False
    assert tasks["task-gamma"]["history_count"] == 2


def test_registry_replay_is_idempotent() -> None:
    events = ai_registry.load_events(FIXTURE)
    assert ai_registry.build_registry(events) == ai_registry.build_registry(events)


def test_cli_json_output() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/llm/ai_registry.py", str(FIXTURE), "--json"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["schema"] == "ai-task-registry.v1"
    assert payload["summary"]["tasks"] == 3


def test_comments_response_wrapper_is_supported() -> None:
    snapshot = ai_registry.build_registry(
        ai_registry.load_events(COMMENTS_RESPONSE_FIXTURE)
    )
    assert snapshot["summary"] == {
        "events": 2,
        "tasks": 1,
        "active": 0,
        "done": 1,
        "blocked": 0,
        "released": 0,
    }
    task = snapshot["tasks"][0]
    assert task["task_id"] == "task-delta"
    assert task["status"] == "done"
    assert task["pr"].endswith("/1000")


if __name__ == "__main__":
    test_registry_replays_current_task_states()
    test_registry_replay_is_idempotent()
    test_cli_json_output()
    test_comments_response_wrapper_is_supported()
    print("ALL AI REGISTRY TESTS PASS (0 network calls)")
