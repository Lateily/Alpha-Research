"""Offline tests for the AIOS reconciler.

Run with:
    python tests/test_ai_reconciler.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))

import ai_reconciler  # noqa: E402
import ai_registry  # noqa: E402
import progress_conflicts  # noqa: E402


FIXTURE = REPO_ROOT / "docs" / "llm" / "examples" / "ai-progress.reconciler.fixture.json"
COMMENTS_RESPONSE_FIXTURE = (
    REPO_ROOT
    / "docs"
    / "llm"
    / "examples"
    / "ai-progress.registry.comments-response.fixture.json"
)
NOW = datetime(2026, 8, 4, 6, 0, tzinfo=timezone.utc)


def test_reconciler_finds_actionable_progress_board_issues() -> None:
    events = ai_registry.load_events(FIXTURE)
    snapshot = ai_reconciler.reconcile(events, NOW, include_history_findings=True)

    assert snapshot["schema"] == "ai-reconciler.v1"
    assert snapshot["summary"] == {
        "findings": 5,
        "blocker": 0,
        "major": 5,
        "minor": 0,
    }

    by_rule = {finding["rule_id"]: finding for finding in snapshot["findings"]}
    assert by_rule["AIOS-R002"]["task"] == "stale-claim"
    assert by_rule["AIOS-R004"]["task"] == "incomplete-done"
    assert by_rule["AIOS-R005"]["task"] == "incomplete-blocked"
    assert by_rule["AIOS-R006"]["task"] == "overlap-a <-> overlap-b"
    assert by_rule["AIOS-R007"]["task"] == "orphan-done"


def test_clean_comments_response_has_no_reconciler_findings() -> None:
    events = ai_registry.load_events(COMMENTS_RESPONSE_FIXTURE)
    snapshot = ai_reconciler.reconcile(events, NOW)

    assert snapshot["summary"]["findings"] == 0
    assert snapshot["findings"] == []


def test_cli_json_and_fail_on_findings() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/llm/ai_reconciler.py",
            str(FIXTURE),
            "--now",
            "2026-08-04T06:00:00Z",
            "--json",
            "--fail-on-findings",
            "--include-history-findings",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["summary"]["findings"] == 5


def test_progress_conflicts_accepts_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "comments-response-bom.json"
    payload = COMMENTS_RESPONSE_FIXTURE.read_text(encoding="utf-8")
    path.write_text(payload, encoding="utf-8-sig")

    events = progress_conflicts.load_events(path)

    assert len(events) == 2
    assert events[0]["task"] == "task-delta"


if __name__ == "__main__":
    test_reconciler_finds_actionable_progress_board_issues()
    test_clean_comments_response_has_no_reconciler_findings()
    test_cli_json_and_fail_on_findings()
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        test_progress_conflicts_accepts_utf8_bom(Path(tmp))
    print("ALL AI RECONCILER TESTS PASS (0 network calls)")
