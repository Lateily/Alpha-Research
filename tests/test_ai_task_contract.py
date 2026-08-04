"""Offline tests for the ai-task.v1 contract.

Run with:
    python tests/test_ai_task_contract.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))

import ai_task  # noqa: E402


EXAMPLES = REPO_ROOT / "docs" / "llm" / "examples"


def test_valid_examples_pass() -> None:
    valid_paths = sorted(EXAMPLES.glob("ai-task.valid.*.json"))
    assert valid_paths, "expected at least one valid ai-task fixture"
    for path in valid_paths:
        result = ai_task.validate_path(path)
        assert result.ok, f"{path} should pass: {result.errors}"
        assert result.status == "SPEC_READY"


def test_invalid_examples_are_spec_blocked() -> None:
    invalid_paths = sorted(EXAMPLES.glob("ai-task.invalid.*.json"))
    assert invalid_paths, "expected invalid ai-task fixtures"
    for path in invalid_paths:
        result = ai_task.validate_path(path)
        assert not result.ok, f"{path} should fail closed"
        assert result.status == "SPEC_BLOCKED"
        assert result.errors


def test_missing_acceptance_is_explicit() -> None:
    path = EXAMPLES / "ai-task.invalid.missing-acceptance.json"
    result = ai_task.validate_path(path)
    assert not result.ok
    assert "missing required field: acceptance_tests" in result.errors


def test_empty_scope_is_explicit() -> None:
    path = EXAMPLES / "ai-task.invalid.empty-scope.json"
    result = ai_task.validate_path(path)
    assert not result.ok
    assert "scope_paths must contain at least 1 item(s)" in result.errors


def test_cli_exit_codes() -> None:
    valid_path = EXAMPLES / "ai-task.valid.a006.json"
    invalid_path = EXAMPLES / "ai-task.invalid.bad-risk.json"

    ok = subprocess.run(
        [sys.executable, "scripts/llm/ai_task.py", str(valid_path)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0
    assert "OK" in ok.stdout

    bad = subprocess.run(
        [sys.executable, "scripts/llm/ai_task.py", str(invalid_path)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert bad.returncode == 1
    assert "SPEC_BLOCKED" in bad.stdout


if __name__ == "__main__":
    test_valid_examples_pass()
    test_invalid_examples_are_spec_blocked()
    test_missing_acceptance_is_explicit()
    test_empty_scope_is_explicit()
    test_cli_exit_codes()
    print("ALL AI TASK CONTRACT TESTS PASS (0 network calls)")
