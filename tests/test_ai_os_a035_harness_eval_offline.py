"""Offline regressions for A-035 Harness Eval Phase 1."""

from __future__ import annotations

import copy
import json
import socket
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))

from ai_os.harness_eval import (  # noqa: E402
    EVAL_FAIL,
    EVAL_PASS,
    SPEC_BLOCKED,
    evaluate_harness_matrix,
)


MATRIX_PATH = (
    REPO_ROOT / "scripts" / "llm" / "fixtures" / "harness_eval_matrix.v1.json"
)


def matrix_fixture():
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def passing_observations(matrix=None):
    matrix = matrix or matrix_fixture()
    observations = []
    for case in matrix["cases"]:
        evidence_head = case["current_head"]
        executor_id = "github:executor"
        reviewer_id = "github:reviewer"
        if case["case_id"] == "done-stale-evidence-deny":
            evidence_head = "5555555555555555555555555555555555555555"
        if case["case_id"] == "done-self-review-deny":
            reviewer_id = executor_id
        observations.append(
            {
                "case_id": case["case_id"],
                "decision": case["expected_decision"],
                "reason": case["expected_reason"],
                "evidence_head": evidence_head,
                "executor_id": executor_id,
                "reviewer_id": reviewer_id,
                "side_effect_count": 0,
            }
        )
    return observations


def finding_codes(report):
    return {finding.code for finding in report.findings}


def observation(observations, case_id):
    return next(item for item in observations if item["case_id"] == case_id)


def synthetic_secret(*parts):
    return "".join(parts)


def test_versioned_four_domain_fixture_passes_expected_negative_cases_offline() -> None:
    original_socket = socket.socket

    def blocked_socket(*_args, **_kwargs):
        raise AssertionError("network access is forbidden in A-035 tests")

    socket.socket = blocked_socket
    try:
        matrix = matrix_fixture()
        report = evaluate_harness_matrix(matrix, passing_observations(matrix))
    finally:
        socket.socket = original_socket

    assert report.status == EVAL_PASS
    assert report.evaluated_cases == 9
    assert report.matrix_hash is not None
    assert report.matrix_hash.startswith("sha256:")
    assert {case["domain"] for case in matrix["cases"]} == {
        "AUTHORITY",
        "CONTEXT",
        "P5",
        "DONE",
    }
    json.dumps(report.to_dict(), sort_keys=True)


def test_malformed_duplicate_or_incomplete_matrix_is_spec_blocked() -> None:
    mutations = []
    bad_schema = matrix_fixture()
    bad_schema["schema"] = "ai-harness-eval-matrix.v0"
    mutations.append(bad_schema)

    duplicate = matrix_fixture()
    duplicate["cases"][1]["case_id"] = duplicate["cases"][0]["case_id"]
    mutations.append(duplicate)

    unknown_domain = matrix_fixture()
    unknown_domain["cases"][0]["domain"] = "MODEL_BRAND"
    mutations.append(unknown_domain)

    missing_domain = matrix_fixture()
    missing_domain["cases"] = [
        case for case in missing_domain["cases"] if case["domain"] != "P5"
    ]
    mutations.append(missing_domain)

    for matrix in mutations:
        report = evaluate_harness_matrix(matrix, passing_observations(matrix))
        assert report.status == SPEC_BLOCKED
        assert report.evaluated_cases == 0
        assert report.errors


def test_malformed_missing_or_unknown_observations_are_spec_blocked() -> None:
    matrix = matrix_fixture()
    cases = [
        passing_observations(matrix)[:-1],
        passing_observations(matrix)
        + [
            {
                "case_id": "unknown",
                "decision": "ALLOW",
                "reason": "OK",
                "evidence_head": "a" * 40,
                "executor_id": "github:a",
                "reviewer_id": "github:b",
                "side_effect_count": 0,
            }
        ],
    ]
    malformed = passing_observations(matrix)
    malformed[0]["side_effect_count"] = True
    cases.append(malformed)

    for observations in cases:
        report = evaluate_harness_matrix(matrix, observations)
        assert report.status == SPEC_BLOCKED
        assert report.errors


def test_display_names_and_unsafe_tokens_are_spec_blocked() -> None:
    matrix = matrix_fixture()
    observations = passing_observations(matrix)
    observations[0]["executor_id"] = "Jason"
    report = evaluate_harness_matrix(matrix, observations)
    assert report.status == SPEC_BLOCKED
    assert any("principal IDs" in error for error in report.errors)

    unsafe_matrix = matrix_fixture()
    unsafe_matrix["cases"][0]["case_id"] = "../../outside"
    report = evaluate_harness_matrix(
        unsafe_matrix,
        passing_observations(unsafe_matrix),
    )
    assert report.status == SPEC_BLOCKED
    assert any("safe case token" in error for error in report.errors)


def test_github_case_alias_cannot_claim_independent_review() -> None:
    matrix = matrix_fixture()
    observations = passing_observations(matrix)
    target = observation(observations, "done-evidence-ready-allow")
    target["executor_id"] = "github:jason"
    target["reviewer_id"] = "github:Jason"

    report = evaluate_harness_matrix(matrix, observations)

    assert report.status == SPEC_BLOCKED
    assert any("principal IDs" in error for error in report.errors)


def test_rejected_identifiers_never_echo_secret_like_values() -> None:
    secret_like = synthetic_secret("gh", "p_", "notarealcredential123")
    matrix = matrix_fixture()
    observations = passing_observations(matrix)
    observations.append(
        {
            "case_id": secret_like,
            "decision": "ALLOW",
            "reason": "OK",
            "evidence_head": "a" * 40,
            "executor_id": "github:executor",
            "reviewer_id": "github:reviewer",
            "side_effect_count": 0,
        }
    )

    unknown = evaluate_harness_matrix(matrix, observations)
    serialized_unknown = json.dumps(unknown.to_dict(), ensure_ascii=False)

    secret_matrix = matrix_fixture()
    secret_matrix["cases"][0]["case_id"] = secret_like
    malformed = evaluate_harness_matrix(
        secret_matrix,
        passing_observations(secret_matrix),
    )
    serialized_malformed = json.dumps(malformed.to_dict(), ensure_ascii=False)

    assert unknown.status == SPEC_BLOCKED
    assert malformed.status == SPEC_BLOCKED
    assert secret_like not in serialized_unknown
    assert secret_like not in serialized_malformed


def test_unknown_contract_fields_are_spec_blocked() -> None:
    matrix = matrix_fixture()
    matrix["cases"][0]["hidden_override"] = "ALLOW"
    report = evaluate_harness_matrix(matrix, passing_observations(matrix))
    assert report.status == SPEC_BLOCKED
    assert any("fields must match" in error for error in report.errors)

    matrix = matrix_fixture()
    observations = passing_observations(matrix)
    observations[0]["hidden_override"] = "ALLOW"
    report = evaluate_harness_matrix(matrix, observations)
    assert report.status == SPEC_BLOCKED
    assert any("fields must match" in error for error in report.errors)


def test_matrix_hash_is_stable_and_content_sensitive() -> None:
    first_matrix = matrix_fixture()
    first = evaluate_harness_matrix(
        first_matrix,
        passing_observations(first_matrix),
    )
    same = evaluate_harness_matrix(
        copy.deepcopy(first_matrix),
        passing_observations(first_matrix),
    )
    changed_matrix = copy.deepcopy(first_matrix)
    changed_matrix["version"] = "a035-phase1-2026-08-16-r2"
    changed = evaluate_harness_matrix(
        changed_matrix,
        passing_observations(changed_matrix),
    )

    assert first.matrix_hash == same.matrix_hash
    assert first.matrix_hash != changed.matrix_hash


def test_observations_hash_is_stable_and_content_sensitive() -> None:
    matrix = matrix_fixture()
    first_observations = passing_observations(matrix)
    same_observations = copy.deepcopy(first_observations)
    changed_observations = copy.deepcopy(first_observations)
    changed_observations[0]["executor_id"] = "github:another-executor"

    first = evaluate_harness_matrix(matrix, first_observations)
    same = evaluate_harness_matrix(matrix, same_observations)
    changed = evaluate_harness_matrix(matrix, changed_observations)

    assert first.status == EVAL_PASS
    assert same.status == EVAL_PASS
    assert changed.status == EVAL_PASS
    assert first.observations_hash is not None
    assert first.observations_hash == same.observations_hash
    assert first.observations_hash != changed.observations_hash


def test_matrix_cannot_disable_done_allow_independence() -> None:
    matrix = matrix_fixture()
    target_case = next(
        case for case in matrix["cases"] if case["case_id"] == "done-evidence-ready-allow"
    )
    target_case["require_independent_review"] = False
    observations = passing_observations(matrix)
    target = observation(observations, "done-evidence-ready-allow")
    target["reviewer_id"] = target["executor_id"]

    report = evaluate_harness_matrix(matrix, observations)

    assert report.status == SPEC_BLOCKED
    assert any("must be true for DONE ALLOW" in error for error in report.errors)


def test_false_pass_and_false_reject_are_distinguished() -> None:
    matrix = matrix_fixture()
    observations = passing_observations(matrix)
    false_pass = observation(observations, "authority-conflict-deny")
    false_pass.update(decision="ALLOW", reason="AUTHORITY_RESOLVED")
    false_reject = observation(observations, "context-current-allow")
    false_reject.update(decision="DENY", reason="CONTEXT_INCOMPLETE")

    report = evaluate_harness_matrix(matrix, observations)

    assert report.status == EVAL_FAIL
    assert finding_codes(report) == {"FALSE_PASS", "FALSE_REJECT"}


def test_wrong_reason_is_not_accepted() -> None:
    matrix = matrix_fixture()
    observations = passing_observations(matrix)
    observation(observations, "context-missing-deny")["reason"] = "POLICY_BLOCKED"

    report = evaluate_harness_matrix(matrix, observations)

    assert report.status == EVAL_FAIL
    assert finding_codes(report) == {"WRONG_ATTRIBUTION"}


def test_stale_head_cannot_support_allow() -> None:
    matrix = matrix_fixture()
    observations = passing_observations(matrix)
    target = observation(observations, "authority-resolved-allow")
    target["evidence_head"] = "9" * 40

    report = evaluate_harness_matrix(matrix, observations)

    assert report.status == EVAL_FAIL
    assert finding_codes(report) == {"STALE_EVIDENCE"}


def test_stale_denial_must_use_stale_attribution() -> None:
    matrix = matrix_fixture()
    observations = passing_observations(matrix)
    target = observation(observations, "context-missing-deny")
    target["evidence_head"] = "9" * 40

    report = evaluate_harness_matrix(matrix, observations)

    assert report.status == EVAL_FAIL
    assert finding_codes(report) == {"STALE_EVIDENCE"}


def test_executor_self_review_cannot_support_allow() -> None:
    matrix = matrix_fixture()
    observations = passing_observations(matrix)
    target = observation(observations, "done-evidence-ready-allow")
    target["reviewer_id"] = target["executor_id"]

    report = evaluate_harness_matrix(matrix, observations)

    assert report.status == EVAL_FAIL
    assert finding_codes(report) == {"REVIEW_NOT_INDEPENDENT"}


def test_self_review_denial_must_use_independence_attribution() -> None:
    matrix = matrix_fixture()
    observations = passing_observations(matrix)
    target = observation(observations, "done-stale-evidence-deny")
    target["reviewer_id"] = target["executor_id"]

    report = evaluate_harness_matrix(matrix, observations)

    assert report.status == EVAL_FAIL
    assert finding_codes(report) == {"REVIEW_NOT_INDEPENDENT"}


def test_denial_after_side_effect_is_not_safe() -> None:
    matrix = matrix_fixture()
    observations = passing_observations(matrix)
    target = observation(observations, "p5-scope-escalation-deny")
    target["side_effect_count"] = 1

    report = evaluate_harness_matrix(matrix, observations)

    assert report.status == EVAL_FAIL
    assert finding_codes(report) == {"SIDE_EFFECT_BEFORE_GATE"}


def test_input_objects_are_not_mutated() -> None:
    matrix = matrix_fixture()
    observations = passing_observations(matrix)
    original_matrix = copy.deepcopy(matrix)
    original_observations = copy.deepcopy(observations)

    evaluate_harness_matrix(matrix, observations)

    assert matrix == original_matrix
    assert observations == original_observations


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
    print(f"ALL AIOS A-035 HARNESS EVAL TESTS PASS ({test_count} tests, 0 network calls)")
