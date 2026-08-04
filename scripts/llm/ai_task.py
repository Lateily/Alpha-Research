"""Validate AIOS task manifests.

The validator intentionally uses only the Python standard library. JSON Schema
remains the human-facing contract, while this module provides the fail-closed
checks that AIOS-K1 needs before task execution.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = (
    "schema",
    "task_id",
    "title",
    "source",
    "objective",
    "non_goals",
    "human_owner",
    "executor",
    "reviewer",
    "status",
    "risk_level",
    "scope_paths",
    "acceptance_tests",
    "depends_on",
    "authority_docs",
    "network_policy",
    "budget",
    "approval_gates",
    "created_at",
)

VALID_STATUSES = {
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
}

VALID_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "CONSTITUTIONAL"}
VALID_NETWORK_POLICIES = {"OFFLINE", "ALLOWLIST", "LIVE_DATA"}
VALID_ACCEPTANCE_METHODS = {"command", "schema", "file_check", "manual_review"}


@dataclass(frozen=True)
class ValidationResult:
    path: str
    status: str
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ai-task.validation.v1",
            "path": self.path,
            "status": self.status,
            "ok": self.ok,
            "errors": self.errors,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ai-task.v1 manifests.")
    parser.add_argument("paths", nargs="+", help="Manifest JSON paths to validate.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable validation results.",
    )
    args = parser.parse_args()

    results = [validate_path(Path(path)) for path in args.paths]
    if args.json:
        print(json.dumps([result.to_dict() for result in results], indent=2))
    else:
        for result in results:
            if result.ok:
                print(f"OK {result.path}")
            else:
                print(f"SPEC_BLOCKED {result.path}")
                for error in result.errors:
                    print(f"- {error}")

    return 0 if all(result.ok for result in results) else 1


def validate_path(path: Path) -> ValidationResult:
    try:
        task = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return ValidationResult(str(path), "SPEC_BLOCKED", [f"invalid JSON: {exc}"])

    if not isinstance(task, dict):
        return ValidationResult(str(path), "SPEC_BLOCKED", ["manifest must be an object"])

    errors = validate_task(task)
    return ValidationResult(
        str(path),
        "SPEC_READY" if not errors else "SPEC_BLOCKED",
        errors,
    )


def validate_task(task: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in task:
            errors.append(f"missing required field: {field}")

    if errors:
        return errors

    expect_equal(errors, task, "schema", "ai-task.v1")
    expect_non_empty_string(errors, task, "task_id")
    expect_non_empty_string(errors, task, "title")
    expect_non_empty_string(errors, task, "objective")
    expect_non_empty_string(errors, task, "human_owner")
    expect_non_empty_string(errors, task, "executor")
    expect_non_empty_string(errors, task, "reviewer")
    expect_non_empty_string(errors, task, "created_at")
    expect_string_array(errors, task, "non_goals")
    expect_string_array(errors, task, "depends_on")
    expect_string_array(errors, task, "authority_docs")
    expect_string_array(errors, task, "approval_gates")
    expect_string_array(errors, task, "scope_paths", min_items=1)

    if task["status"] not in VALID_STATUSES:
        errors.append(f"status must be one of {sorted(VALID_STATUSES)}")
    if task["risk_level"] not in VALID_RISK_LEVELS:
        errors.append(f"risk_level must be one of {sorted(VALID_RISK_LEVELS)}")
    if task["network_policy"] not in VALID_NETWORK_POLICIES:
        errors.append(
            f"network_policy must be one of {sorted(VALID_NETWORK_POLICIES)}"
        )

    validate_source(errors, task["source"])
    validate_budget(errors, task["budget"])
    validate_acceptance_tests(errors, task["acceptance_tests"])
    return errors


def validate_source(errors: list[str], source: Any) -> None:
    if not isinstance(source, dict):
        errors.append("source must be an object")
        return
    if source.get("kind") not in {"issue", "pr", "progress", "backlog", "manual"}:
        errors.append("source.kind must be issue/pr/progress/backlog/manual")
    if not isinstance(source.get("ref"), str) or not source["ref"].strip():
        errors.append("source.ref must be a non-empty string")


def validate_budget(errors: list[str], budget: Any) -> None:
    if not isinstance(budget, dict):
        errors.append("budget must be an object")
        return
    max_cny = budget.get("max_cny")
    max_minutes = budget.get("max_minutes")
    if not isinstance(max_cny, str) or not max_cny.strip():
        errors.append("budget.max_cny must be a non-empty string")
    if not isinstance(max_minutes, int) or max_minutes < 1:
        errors.append("budget.max_minutes must be an integer >= 1")


def validate_acceptance_tests(errors: list[str], acceptance_tests: Any) -> None:
    if not isinstance(acceptance_tests, list) or not acceptance_tests:
        errors.append("acceptance_tests must be a non-empty array")
        return
    for index, item in enumerate(acceptance_tests):
        prefix = f"acceptance_tests[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in ("id", "description", "method", "expected"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                errors.append(f"{prefix}.{field} must be a non-empty string")
        if item.get("method") not in VALID_ACCEPTANCE_METHODS:
            errors.append(
                f"{prefix}.method must be one of {sorted(VALID_ACCEPTANCE_METHODS)}"
            )


def expect_equal(
    errors: list[str],
    task: dict[str, Any],
    field: str,
    expected: str,
) -> None:
    if task.get(field) != expected:
        errors.append(f"{field} must be {expected}")


def expect_non_empty_string(
    errors: list[str],
    task: dict[str, Any],
    field: str,
) -> None:
    if not isinstance(task.get(field), str) or not task[field].strip():
        errors.append(f"{field} must be a non-empty string")


def expect_string_array(
    errors: list[str],
    task: dict[str, Any],
    field: str,
    min_items: int = 0,
) -> None:
    value = task.get(field)
    if not isinstance(value, list):
        errors.append(f"{field} must be an array")
        return
    if len(value) < min_items:
        errors.append(f"{field} must contain at least {min_items} item(s)")
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{field}[{index}] must be a non-empty string")


if __name__ == "__main__":
    raise SystemExit(main())
