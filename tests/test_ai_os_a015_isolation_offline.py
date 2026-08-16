"""Offline adversarial tests for the A-015a isolation plan contract."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))

from ai_os.executor import (  # noqa: E402
    IsolationRequest,
    IsolationStatus,
    build_isolation_plan,
)


COMMIT_SHA = "d46bafe95c2c403a35a7d315777df2c4e5eb0cdb"


def request(**overrides) -> IsolationRequest:
    values = {
        "task_id": "issue-195-a015a",
        "run_id": "run_a015a_001",
        "branch": "codex/aios-a015-isolation-plan",
        "commit_sha": COMMIT_SHA,
        "file_scope": ("docs/llm",),
        "target_paths": ("docs/llm/AI_OS_BUILD_GUIDE.md",),
        "allowed_tools": frozenset({"read_file", "apply_patch"}),
        "requested_tools": frozenset({"read_file"}),
        "timeout_seconds": 300,
        "network_policy": "deny",
        "risk_level": "LOW",
        "mode": "SHADOW",
    }
    values.update(overrides)
    return IsolationRequest(**values)


def test_ready_plan_binds_run_branch_worktree_commit_and_cleanup() -> None:
    result = build_isolation_plan(request())

    assert result.status is IsolationStatus.READY
    assert result.reasons == ()
    assert result.plan is not None
    assert result.plan.task_id == "issue-195-a015a"
    assert result.plan.run_id == "run_a015a_001"
    assert result.plan.branch == "codex/aios-a015-isolation-plan"
    assert result.plan.worktree == ".ar/ai-os/worktrees/run_a015a_001"
    assert result.plan.commit_sha == COMMIT_SHA
    assert result.plan.tools == ("read_file",)
    assert result.plan.timeout_seconds == 300
    assert result.plan.cleanup_policy == "REMOVE_WORKTREE_KEEP_BRANCH"
    assert result.plan.plan_hash.startswith("sha256:")


def test_plan_is_deterministic_and_hash_is_content_sensitive() -> None:
    first = build_isolation_plan(
        request(
            file_scope=("docs/llm", "scripts/llm/ai_os"),
            target_paths=(
                "docs/llm/AI_OS_BUILD_GUIDE.md",
                "scripts/llm/ai_os/executor.py",
            ),
            requested_tools=frozenset({"apply_patch", "read_file"}),
            allowed_tools=frozenset({"read_file", "apply_patch"}),
        )
    )
    second = build_isolation_plan(
        request(
            file_scope=("scripts/llm/ai_os", "docs/llm"),
            target_paths=(
                "scripts/llm/ai_os/executor.py",
                "docs/llm/AI_OS_BUILD_GUIDE.md",
            ),
            requested_tools=frozenset({"read_file", "apply_patch"}),
            allowed_tools=frozenset({"apply_patch", "read_file"}),
        )
    )
    changed = build_isolation_plan(
        request(commit_sha="81473c3836980ae9fa63e7b10d1dcb918b1203ac")
    )

    assert first.status is IsolationStatus.READY
    assert second.status is IsolationStatus.READY
    assert changed.status is IsolationStatus.READY
    assert first.plan is not None and second.plan is not None and changed.plan is not None
    assert first.plan.to_dict() == second.plan.to_dict()
    assert first.plan.plan_hash != changed.plan.plan_hash


def test_malformed_request_is_spec_blocked_without_plan() -> None:
    invalid = [
        None,
        request(run_id="../escape"),
        request(run_id="ｒｕｎ＿００１"),
        request(commit_sha="short"),
        request(commit_sha=COMMIT_SHA.upper()),
        request(file_scope=["docs/llm"]),
        request(target_paths=("docs//llm/file.md",)),
        request(target_paths=("docs/%2e%2e/file.md",)),
        request(allowed_tools={"read_file"}),
    ]

    for item in invalid:
        result = build_isolation_plan(item)
        assert result.status is IsolationStatus.SPEC_BLOCKED
        assert result.plan is None
        json.dumps(result.to_dict())


def test_path_control_and_format_characters_are_spec_blocked() -> None:
    unsafe_paths = (
        "docs/llm/line\nspoof.md",
        "docs/llm/tab\tspoof.md",
        "docs/llm/c1\x85spoof.md",
        "docs/llm/bidi\u202espoof.md",
    )

    for path in unsafe_paths:
        result = build_isolation_plan(request(target_paths=(path,)))
        assert result.status is IsolationStatus.SPEC_BLOCKED
        assert result.plan is None
        assert result.reasons == ("target_paths must contain safe relative paths",)


def test_target_paths_cannot_overlap_or_use_equivalent_aliases() -> None:
    cases = (
        ("docs/llm", "docs/llm/file.md"),
        ("docs/llm/File.md", "docs/llm/file.md"),
        ("docs/llm/Ａ.md", "docs/llm/A.md"),
    )

    for target_paths in cases:
        result = build_isolation_plan(request(target_paths=target_paths))
        assert result.status is IsolationStatus.SPEC_BLOCKED
        assert result.plan is None
        assert result.reasons in (
            ("target_paths must not contain overlapping paths",),
            ("target_paths must not contain duplicate paths",),
        )


def test_timeout_must_be_a_positive_integer() -> None:
    for value in (0, -1, True, 1.5, "300"):
        result = build_isolation_plan(request(timeout_seconds=value))
        assert result.status is IsolationStatus.SPEC_BLOCKED
        assert result.plan is None
        assert result.reasons == ("timeout_seconds must be a positive integer",)


def test_protected_branch_is_policy_blocked_including_unicode_alias() -> None:
    for branch in ("main", "refs/heads/main", "ｍａｉｎ"):
        result = build_isolation_plan(request(branch=branch))
        assert result.status is IsolationStatus.POLICY_BLOCKED
        assert result.plan is None
        assert "protected branches" in " ".join(result.reasons)


def test_target_paths_must_remain_inside_declared_file_scope() -> None:
    result = build_isolation_plan(
        request(target_paths=("scripts/llm/ai_os/executor.py",))
    )

    assert result.status is IsolationStatus.POLICY_BLOCKED
    assert result.plan is None
    assert result.reasons == ("target_paths must stay within file_scope",)


def test_execution_tracker_and_git_scopes_are_always_blocked_case_insensitively() -> None:
    cases = [
        request(file_scope=("experiments/EXECUTION_TRACKER",)),
        request(
            file_scope=("experiments",),
            target_paths=("experiments/EXECUTION_TRACKER/run.json",),
        ),
        request(file_scope=(".ＧＩＴ",), target_paths=(".ＧＩＴ/config",)),
    ]

    for item in cases:
        result = build_isolation_plan(item)
        assert result.status is IsolationStatus.POLICY_BLOCKED
        assert result.plan is None
        assert "forbidden scope" in " ".join(result.reasons)


def test_forbidden_file_scope_blocks_even_a_safe_sibling_target() -> None:
    result = build_isolation_plan(
        request(
            file_scope=("experiments",),
            target_paths=("experiments/safe_fixture.json",),
        )
    )

    assert result.status is IsolationStatus.POLICY_BLOCKED
    assert result.plan is None
    assert result.reasons == ("file_scope overlaps a forbidden scope",)


def test_requested_tools_cannot_exceed_policy_allowance() -> None:
    result = build_isolation_plan(
        request(
            allowed_tools=frozenset({"read_file"}),
            requested_tools=frozenset({"read_file", "shell"}),
        )
    )

    assert result.status is IsolationStatus.POLICY_BLOCKED
    assert result.plan is None
    assert result.reasons == ("requested_tools exceed allowed_tools",)


def test_a015a_only_allows_low_shadow_offline_plans() -> None:
    cases = [
        request(risk_level="MEDIUM"),
        request(risk_level="HIGH"),
        request(mode="PRODUCTION"),
        request(network_policy="provider_only"),
    ]

    for item in cases:
        result = build_isolation_plan(item)
        assert result.status is IsolationStatus.POLICY_BLOCKED
        assert result.plan is None


def test_block_reasons_do_not_echo_untrusted_values() -> None:
    untrusted = "unexpected-sensitive-value"
    result = build_isolation_plan(request(branch=f"bad branch {untrusted}"))
    serialized = json.dumps(result.to_dict())

    assert result.status is IsolationStatus.SPEC_BLOCKED
    assert untrusted not in serialized


def test_secret_like_values_are_blocked_without_echo_across_request_fields() -> None:
    synthetic_secret = "ghp_" + ("A" * 24)
    cases = (
        request(task_id=synthetic_secret),
        request(run_id=synthetic_secret),
        request(branch=f"codex/{synthetic_secret}"),
        request(
            file_scope=(f"docs/{synthetic_secret}",),
            target_paths=(f"docs/{synthetic_secret}/file.md",),
        ),
        request(target_paths=(f"docs/llm/{synthetic_secret}.md",)),
        request(allowed_tools=frozenset({"read_file", synthetic_secret})),
        request(
            requested_tools=frozenset({synthetic_secret}),
            allowed_tools=frozenset({synthetic_secret}),
        ),
    )

    for item in cases:
        result = build_isolation_plan(item)
        serialized = json.dumps(result.to_dict())
        assert result.status is IsolationStatus.SPEC_BLOCKED
        assert result.plan is None
        assert "request contains a secret-like value" in result.reasons
        assert synthetic_secret not in serialized


def test_ordinary_secret_related_words_are_not_false_positive_blocked() -> None:
    result = build_isolation_plan(
        request(
            file_scope=("docs/llm",),
            target_paths=("docs/llm/sk-learning-guide.md",),
        )
    )

    assert result.status is IsolationStatus.READY
    assert result.plan is not None


def test_planner_has_zero_network_and_filesystem_write_surface() -> None:
    original_socket = socket.socket

    def blocked_socket(*_args, **_kwargs):
        raise AssertionError("network access is forbidden in A-015a tests")

    socket.socket = blocked_socket
    try:
        result = build_isolation_plan(request())
    finally:
        socket.socket = original_socket

    assert result.status is IsolationStatus.READY


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
    print(
        f"ALL AIOS A-015a ISOLATION OFFLINE TESTS PASS "
        f"({test_count} tests, 0 network calls, 0 worktrees created)"
    )
