"""Offline tests for AIOS-K1 task contracts, registry, and reconciler."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))

from ai_os.reconciler import reconcile  # noqa: E402
from ai_os.registry import replay_events  # noqa: E402
from ai_os.task_compiler import (  # noqa: E402
    MANIFEST_ORDER,
    NETWORK_POLICIES,
    RISK_LEVELS,
    SPEC_BLOCKED,
    SPEC_READY,
    compile_task_manifest,
)


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


def event(
    event_id,
    from_state,
    to_state,
    evidence_refs=None,
    timestamp_utc="2026-08-07T09:00:00Z",
):
    return {
        "event_id": event_id,
        "task_id": "A-006-task-manifest",
        "from_state": from_state,
        "to_state": to_state,
        "actor": "Codex",
        "reason": f"{from_state}->{to_state}",
        "evidence_refs": evidence_refs or [],
        "timestamp_utc": timestamp_utc,
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


def test_task_manifest_rejects_bad_schema_risk_and_source_issue() -> None:
    cases = [
        (
            valid_task_source(schema="ai-task.v0"),
            "schema must be ai-task.v1",
        ),
        (
            valid_task_source(risk_level="AUTO_APPROVE"),
            "risk_level is not supported",
        ),
        (
            valid_task_source(source_issue=True),
            "source_issue must be a positive integer when present",
        ),
        (
            valid_task_source(source_issue=0),
            "source_issue must be a positive integer when present",
        ),
    ]

    for source, expected_error in cases:
        result = compile_task_manifest(source, now=NOW)
        assert result.status == SPEC_BLOCKED
        assert result.manifest is None
        assert expected_error in result.errors


def test_task_manifest_rejects_non_finite_budget_and_bad_created_at() -> None:
    cases = [
        valid_task_source(budget={"max_cny": "NaN", "max_minutes": 60}),
        valid_task_source(budget={"max_cny": "Infinity", "max_minutes": 60}),
        valid_task_source(created_at=123),
        valid_task_source(created_at="   "),
        valid_task_source(created_at="2026-08-07T09:30:00"),
    ]

    for source in cases:
        result = compile_task_manifest(source, now=NOW)
        assert result.status == SPEC_BLOCKED
        assert result.manifest is None


def test_task_manifest_cli_bad_input_exits_spec_blocked() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "bad_task.json"
        source_path.write_text(
            json.dumps(valid_task_source(budget={"max_cny": "NaN", "max_minutes": 60})),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "llm" / "ai_os" / "cli.py"),
                "compile",
                "--input",
                str(source_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    assert completed.returncode == 2
    assert '"status": "SPEC_BLOCKED"' in completed.stdout


def test_registry_replays_events_idempotently() -> None:
    events = [
        event("evt-1", "DISCOVERED", "TRIAGED", timestamp_utc="2026-08-07T09:00:00Z"),
        event("evt-2", "TRIAGED", "SPEC_READY", timestamp_utc="2026-08-07T09:01:00Z"),
        event("evt-2", "TRIAGED", "SPEC_READY", timestamp_utc="2026-08-07T09:01:00Z"),
        event("evt-3", "SPEC_READY", "CLAIMED", timestamp_utc="2026-08-07T09:02:00Z"),
        event("evt-4", "CLAIMED", "RUNNING", timestamp_utc="2026-08-07T09:03:00Z"),
        event("evt-5", "RUNNING", "VERIFYING", timestamp_utc="2026-08-07T09:04:00Z"),
        event("evt-6", "VERIFYING", "REVIEWING", timestamp_utc="2026-08-07T09:05:00Z"),
        event(
            "evt-7",
            "REVIEWING",
            "AWAITING_APPROVAL",
            timestamp_utc="2026-08-07T09:06:00Z",
        ),
        event("evt-8", "AWAITING_APPROVAL", "MERGED", timestamp_utc="2026-08-07T09:07:00Z"),
        event("evt-9", "MERGED", "VALIDATING", timestamp_utc="2026-08-07T09:08:00Z"),
        event("evt-10", "VALIDATING", "DONE", ["pr#1", "test#1"], "2026-08-07T09:09:00Z"),
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
    assert snapshot["invalid_events"][0]["reason"] == "transition RUNNING->DONE is not allowed"


def test_registry_requires_done_evidence() -> None:
    snapshot = replay_events(
        [
            event("evt-1", "DISCOVERED", "TRIAGED"),
            event("evt-2", "TRIAGED", "SPEC_READY"),
            event("evt-3", "SPEC_READY", "CLAIMED"),
            event("evt-4", "CLAIMED", "RUNNING"),
            event("evt-5", "RUNNING", "VERIFYING"),
            event("evt-6", "VERIFYING", "REVIEWING"),
            event("evt-7", "REVIEWING", "AWAITING_APPROVAL"),
            event("evt-8", "AWAITING_APPROVAL", "MERGED"),
            event("evt-9", "MERGED", "VALIDATING"),
            event("evt-10", "VALIDATING", "DONE"),
        ]
    ).to_dict()

    assert snapshot["tasks"]["A-006-task-manifest"]["state"] == "VALIDATING"
    assert snapshot["invalid_events"][0]["reason"] == "DONE requires evidence_refs"


def test_registry_rejects_from_state_mismatch() -> None:
    snapshot = replay_events(
        [
            event("evt-1", "DISCOVERED", "TRIAGED"),
            event("evt-2", "DISCOVERED", "DONE", ["PR#1"]),
        ]
    ).to_dict()

    assert snapshot["tasks"]["A-006-task-manifest"]["state"] == "TRIAGED"
    assert snapshot["invalid_events"][0]["reason"] == (
        "from_state DISCOVERED does not match current TRIAGED"
    )


def test_registry_rejects_duplicate_event_id_with_changed_payload() -> None:
    snapshot = replay_events(
        [
            event("evt-1", "DISCOVERED", "TRIAGED"),
            event("evt-1", "DISCOVERED", "TRIAGED", evidence_refs=["PR#1"]),
        ]
    ).to_dict()

    assert snapshot["tasks"]["A-006-task-manifest"]["state"] == "TRIAGED"
    assert snapshot["duplicate_events"] == []
    assert snapshot["invalid_events"][0]["reason"] == "event_id reused with different payload"


def test_registry_rejects_empty_event_id_and_empty_required_fields() -> None:
    empty_event_id = event("", "DISCOVERED", "TRIAGED")
    empty_actor = event("evt-2", "DISCOVERED", "TRIAGED")
    empty_actor["actor"] = " "

    snapshot = replay_events([empty_event_id, empty_actor]).to_dict()

    assert snapshot["tasks"] == {}
    assert [item["reason"] for item in snapshot["invalid_events"]] == [
        "event_id must be a non-empty string",
        "actor must be a non-empty string",
    ]


def test_registry_rejects_jump_back_self_loop_and_time_reversal() -> None:
    snapshot = replay_events(
        [
            event("evt-1", "DISCOVERED", "DONE", ["pr#1"], "2026-08-07T09:00:00Z"),
            event("evt-2", "DISCOVERED", "DEPLOYED", [], "2026-08-07T09:01:00Z"),
            event("evt-3", "DISCOVERED", "DISCOVERED", [], "2026-08-07T09:02:00Z"),
        ]
    ).to_dict()

    assert "A-006-task-manifest" in snapshot["tasks"]
    assert snapshot["tasks"]["A-006-task-manifest"]["state"] == "DISCOVERED"
    assert [item["reason"] for item in snapshot["invalid_events"]] == [
        "transition DISCOVERED->DONE is not allowed",
        "transition DISCOVERED->DEPLOYED is not allowed",
        "transition DISCOVERED->DISCOVERED is not allowed",
    ]

    reversed_time = replay_events(
        [
            event("evt-1", "DISCOVERED", "TRIAGED", [], "2026-08-07T09:10:00Z"),
            event("evt-2", "TRIAGED", "SPEC_READY", [], "2026-08-07T09:00:00Z"),
        ]
    ).to_dict()
    assert reversed_time["tasks"]["A-006-task-manifest"]["state"] == "TRIAGED"
    assert reversed_time["invalid_events"][0]["reason"] == "timestamp_utc is older than current task state"


def test_registry_allows_blocked_recovery_path() -> None:
    snapshot = replay_events(
        [
            event("evt-1", "DISCOVERED", "TRIAGED", [], "2026-08-07T09:00:00Z"),
            event("evt-2", "TRIAGED", "SPEC_READY", [], "2026-08-07T09:01:00Z"),
            event("evt-3", "SPEC_READY", "BLOCKED", ["issue#193"], "2026-08-07T09:02:00Z"),
            event("evt-4", "BLOCKED", "SPEC_READY", ["issue#193"], "2026-08-07T09:03:00Z"),
        ]
    ).to_dict()

    assert snapshot["tasks"]["A-006-task-manifest"]["state"] == "SPEC_READY"
    assert snapshot["invalid_events"] == []


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
            {
                "event": "DONE",
                "task": "#237",
                "pr": "https://github.com/Lateily/Alpha-Research/pull/237",
                "next": "review",
                "cost_cny": "0",
            },
        ],
        pull_requests=[
            {"number": 250, "state": "OPEN", "linked_issue": None},
            {"number": 237, "state": "OPEN", "linked_issue": 237},
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


def test_reconciler_does_not_hide_open_unlinked_pr() -> None:
    report = reconcile(
        pull_requests=[
            {
                "number": 250,
                "state": "OPEN",
                "linked_issue": None,
                "ai_id": "AIOS-K1",
                "has_acceptance": True,
                "has_progress_claim": True,
            }
        ],
        now=NOW,
    )

    assert report["unlinked_prs"] == [
        {
            "pr": 250,
            "missing": ["linked_issue"],
            "reason": "open PR is not fully linked to AIOS control records",
        }
    ]


def test_reconciler_does_not_hide_done_with_unknown_pr() -> None:
    report = reconcile(
        progress_events=[
            {
                "event": "DONE",
                "task": "#404",
                "pr": "PR#404",
                "next": "review",
                "cost_cny": "0",
            }
        ],
        pull_requests=[],
        now=NOW,
    )

    assert report["oversold_done"] == [
        {
            "task": "#404",
            "pr": 404,
            "reason": "DONE references unknown PR",
        }
    ]


def test_reconciler_reports_invalid_claim_leases() -> None:
    report = reconcile(
        progress_events=[
            {"event": "CLAIM", "task": "missing-expiry"},
            {"event": "CLAIM", "task": "bad-expiry", "expires_at": "not-a-time"},
            {"event": "CLAIM", "task": "naive-expiry", "expires_at": "2026-08-07T09:00:00"},
        ],
        now=NOW,
    )

    assert [item["task"] for item in report["stale_claims"]] == [
        "missing-expiry",
        "bad-expiry",
        "naive-expiry",
    ]
    assert [item["reason"] for item in report["stale_claims"]] == [
        "CLAIM expires_at is missing",
        "CLAIM expires_at is invalid",
        "CLAIM expires_at must include timezone",
    ]


def test_reconciler_cross_checks_done_against_pr_state() -> None:
    report = reconcile(
        registry_snapshot={
            "tasks": {
                "A-007": {
                    "state": "MERGED",
                    "evidence_refs": ["https://github.com/Lateily/Alpha-Research/pull/300"],
                },
            }
        },
        progress_events=[
            {
                "event": "DONE",
                "task": "#999",
                "pr": "PR#999",
                "next": "none",
                "cost_cny": "0",
            },
            {
                "event": "DONE",
                "task": "#301",
                "pr": "https://github.com/Lateily/Alpha-Research/pull/301",
                "next": "none",
                "cost_cny": "0",
            },
        ],
        pull_requests=[
            {"number": 999, "state": "OPEN"},
            {"number": 300, "state": "OPEN"},
            {
                "number": 301,
                "state": "MERGED",
                "requires_runtime": True,
                "runtime_verified": False,
            },
        ],
        now=NOW,
    )

    reasons = [item["reason"] for item in report["oversold_done"]]
    assert "DONE references PR that is not merged" in reasons
    assert "registry MERGED references PR that is still open" in reasons
    assert "DONE references PR without required runtime verification" in reasons


def test_reconciler_reports_done_comment_missing_required_fields() -> None:
    report = reconcile(
        progress_events=[
            {"event": "DONE", "task": "#248", "pr": "PR#248"},
        ],
        pull_requests=[{"number": 248, "state": "MERGED"}],
        now=NOW,
    )

    assert report["oversold_done"] == [
        {
            "task": "#248",
            "missing": ["next", "cost_cny"],
            "reason": "DONE comment lacks required evidence fields",
        }
    ]


def test_reconciler_requires_explicit_parseable_pr_evidence() -> None:
    report = reconcile(
        registry_snapshot={
            "tasks": {
                "A-note": {"state": "DONE", "evidence_refs": ["note#5"]},
                "A-pull": {
                    "state": "DONE",
                    "evidence_refs": ["https://github.com/Lateily/Alpha-Research/pull/6"],
                },
            }
        },
        progress_events=[
            {
                "event": "DONE",
                "task": "#bad-pr-field",
                "pr": "test#1",
                "next": "review",
                "cost_cny": "0",
            },
        ],
        pull_requests=[
            {"number": 5, "state": "MERGED"},
            {"number": 6, "state": "OPEN"},
            {"number": 1, "state": "MERGED"},
        ],
        now=NOW,
    )

    findings = report["oversold_done"]
    assert {
        "task": "A-note",
        "pr": ["note#5"],
        "reason": "registry DONE lacks parseable PR evidence",
    } in findings
    assert {
        "task": "A-pull",
        "pr": 6,
        "reason": "DONE references PR that is not merged",
    } in findings
    assert {
        "task": "#bad-pr-field",
        "pr": "test#1",
        "reason": "PR reference is not parseable",
    } in findings


def test_reconciler_cli_invalid_claim_exits_nonzero() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        fixture_path = Path(temp_dir) / "reconcile.json"
        fixture_path.write_text(
            json.dumps(
                {
                    "progress_events": [
                        {"event": "CLAIM", "task": "bad", "expires_at": "not-a-time"}
                    ]
                }
            ),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "llm" / "ai_os" / "cli.py"),
                "reconcile",
                "--input",
                str(fixture_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    assert completed.returncode == 1
    assert "CLAIM expires_at is invalid" in completed.stdout


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


def test_k1_schemas_are_documented_contracts_with_consistency_guards() -> None:
    task_schema = json.loads(
        (REPO_ROOT / "scripts" / "llm" / "schemas" / "task.schema.json").read_text(
            encoding="utf-8"
        )
    )
    event_schema = json.loads(
        (REPO_ROOT / "scripts" / "llm" / "schemas" / "event.schema.json").read_text(
            encoding="utf-8"
        )
    )
    decision_schema = json.loads(
        (REPO_ROOT / "scripts" / "llm" / "schemas" / "decision.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert "Runtime validation is implemented" in task_schema["$comment"]
    assert "Runtime validation is implemented" in event_schema["$comment"]
    assert "K1 does not consume this schema yet" in decision_schema["$comment"]
    assert set(task_schema["required"]) == set(MANIFEST_ORDER) - {"source_issue"}
    assert set(task_schema["properties"]["risk_level"]["enum"]) == RISK_LEVELS
    assert set(task_schema["properties"]["network_policy"]["enum"]) == NETWORK_POLICIES
    assert set(event_schema["required"]) == {
        "event_id",
        "task_id",
        "from_state",
        "to_state",
        "actor",
        "reason",
        "evidence_refs",
        "timestamp_utc",
    }


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
