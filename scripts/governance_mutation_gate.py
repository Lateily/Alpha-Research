#!/usr/bin/env python3
"""Prove that high-risk Macro/AIOS governance gates are test-pinned.

Each declared mutation disables exactly one production guard inside a temporary
copy of the repository.  The relevant behavioral test suite must then fail.
The real checkout is never modified and child processes run without secrets or
network access.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SECRET_NAME_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
SINGLE_TEST_RUNNER = """
import json
import runpy
import sys
import unittest
from pathlib import Path

MODULE_NAME = "mutation_gate_target"
script, name, kind, class_name, receipt_path = sys.argv[1:6]
sys.argv = [script]
scope = runpy.run_path(script, run_name=MODULE_NAME)

def is_expected_runtime_target(value, expected_name):
    return (
        getattr(value, "__module__", None) == MODULE_NAME
        and getattr(value, "__name__", None) == expected_name
    )

if kind == "function":
    target = scope.get(name)
    if (
        not callable(target)
        or not is_expected_runtime_target(target, name)
    ):
        raise LookupError(f"local function target changed identity: {name}")
    failures = []
    errors = []
    skipped = []
    expected_failures = []
    unexpected_successes = []
    try:
        target()
    except unittest.SkipTest as exc:
        skipped.append(str(exc))
    except AssertionError as exc:
        failures.append(repr(exc))
    except BaseException as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    tests_run = 1
else:
    target_class = scope.get(class_name)
    if (
        not isinstance(target_class, type)
        or not issubclass(target_class, unittest.TestCase)
        or not is_expected_runtime_target(target_class, class_name)
        or name not in target_class.__dict__
        or not is_expected_runtime_target(target_class.__dict__.get(name), name)
    ):
        raise LookupError(f"local TestCase target changed identity: {class_name}.{name}")
    result = unittest.TestResult()
    unittest.TestSuite([target_class(name)]).run(result)
    tests_run = result.testsRun
    failures = [trace for _test, trace in result.failures]
    errors = [trace for _test, trace in result.errors]
    skipped = [reason for _test, reason in result.skipped]
    expected_failures = [trace for _test, trace in result.expectedFailures]
    unexpected_successes = [str(test) for test in result.unexpectedSuccesses]

receipt = {
    "schema": "ar-governance-test-receipt.v1",
    "target": name,
    "kind": kind,
    "class_name": class_name or None,
    "tests_run": tests_run,
    "failures": len(failures),
    "errors": len(errors),
    "skipped": len(skipped),
    "expected_failures": len(expected_failures),
    "unexpected_successes": len(unexpected_successes),
    "diagnostics": {
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "expected_failures": expected_failures,
        "unexpected_successes": unexpected_successes,
    },
}
Path(receipt_path).write_text(
    json.dumps(receipt, ensure_ascii=True, sort_keys=True),
    encoding="utf-8",
)
raise SystemExit(
    1
    if failures or errors or unexpected_successes
    else 0
)
"""
GOVERNANCE_MARKER_RE = re.compile(
    r"^\s*# governance-mutation: (?P<mutation_id>[A-Z0-9_]+)\s*$"
)
K1_GOVERNANCE_PATHS = (
    "scripts/llm/ai_os/task_compiler.py",
    "scripts/llm/ai_os/registry.py",
    "scripts/llm/ai_os/reconciler.py",
)
A035_GOVERNANCE_PATHS = (
    "scripts/llm/ai_os/harness_eval.py",
)
A035_MUTATION_PREFIX = "AIOS_A035_"
R043_GOVERNANCE_PATHS = (
    "experiments/execution_tracker/publication_migration.py",
)
FUNNEL_GOVERNANCE_PATHS = (
    "experiments/research_funnel/funnel_pipeline.py",
    "experiments/research_funnel/r035_evaluation.py",
    "experiments/research_funnel/closure_experiment.py",
    "experiments/research_funnel/research_cycle.py",
    "experiments/research_funnel/research_method.py",
    "experiments/research_funnel/industry_cohort.py",
    "experiments/execution_tracker/paper_portfolio.py",
    "experiments/execution_tracker/model_paper_fund.py",
    "experiments/research_funnel/u4_decision_ledger.py",
    "experiments/execution_tracker/event_ledger.py",
)
# 夜链接入方式(隔离 / 产物销毁 / 不进发布树)同样是漏斗治理,必须同样被 marker
# 覆盖 —— 否则新的 wiring 规则可以靠改组件名绕开检查。但它不能并进上面那条规则:
# run_nightly.py 同时承载 Macro 的 marker,而那条规则是双向精确配对的。这里按
# **ID 前缀**配对,只管 FUNNEL_NIGHTLY_*,不动同文件里别的治理族。
FUNNEL_NIGHTLY_GOVERNANCE_PATHS = (
    "experiments/research_funnel/nightly_funnel.py",
    "experiments/execution_tracker/run_nightly.py",
)
FUNNEL_NIGHTLY_MUTATION_PREFIX = "FUNNEL_NIGHTLY_"
NIGHTLY_ACCEPTANCE_GOVERNANCE_PATHS = (
    "experiments/execution_tracker/nightly_acceptance.py",
    "experiments/execution_tracker/run_nightly.py",
)
NIGHTLY_ACCEPTANCE_MUTATION_PREFIX = "NIGHTLY_ACCEPTANCE_"


class MutationGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class MutationCase:
    mutation_id: str
    component: str
    source_path: str
    test_script: str
    before: str
    after: str
    expected_failure_marker: str
    rationale: str
    test_function: str | None = None


MUTATIONS: tuple[MutationCase, ...] = (
    MutationCase(
        mutation_id="MACRO_M0B_FRED_KEYLESS_ROUTE",
        component="Macro M0-B collection",
        source_path="experiments/macro_os/collectors.py",
        test_script="tests/test_macro_m0b_offline.py",
        before=(
            '        # governance-mutation: MACRO_M0B_FRED_KEYLESS_ROUTE\n'
            "        if key:"
        ),
        after=(
            '        # governance-mutation: MACRO_M0B_FRED_KEYLESS_ROUTE\n'
            "        if True:"
        ),
        expected_failure_marker="test_fred_without_credentials_uses_e2_official_csv_export",
        rationale="A missing FRED key must select the credential-free official CSV transport.",
    ),
    MutationCase(
        mutation_id="MACRO_M0B_FRED_CSV_SERIES_BINDING",
        component="Macro M0-B collection",
        source_path="experiments/macro_os/collectors.py",
        test_script="tests/test_macro_m0b_offline.py",
        before=(
            '    # governance-mutation: MACRO_M0B_FRED_CSV_SERIES_BINDING\n'
            "    if reader.fieldnames != expected_header:"
        ),
        after=(
            '    # governance-mutation: MACRO_M0B_FRED_CSV_SERIES_BINDING\n'
            "    if False:"
        ),
        expected_failure_marker="test_fred_csv_header_is_bound_to_requested_series",
        rationale="A FRED CSV response must be bound to the exact requested native series.",
    ),
    MutationCase(
        mutation_id="MACRO_M0B_TIMEOUT_TRANSLATION",
        component="Macro M0-B collection",
        source_path="experiments/macro_os/collectors.py",
        test_script="tests/test_macro_m0b_offline.py",
        before=(
            '            # governance-mutation: MACRO_M0B_TIMEOUT_TRANSLATION\n'
            '            raise CollectionError("SOURCE_DOWN", "TIMEOUT", "source request timed out") from exc'
        ),
        after=(
            '            # governance-mutation: MACRO_M0B_TIMEOUT_TRANSLATION\n'
            '            raise CollectionError("DATA_INVALID", "TIMEOUT", "source request timed out") from exc'
        ),
        expected_failure_marker="test_socket_timeout_is_reported_as_source_down",
        rationale="Transport timeouts must become structured SOURCE_DOWN evidence instead of escaping.",
    ),
    MutationCase(
        mutation_id="MACRO_M0B3_RULES_HASH",
        component="Macro M0-B3",
        source_path="experiments/macro_os/m0b3.py",
        test_script="tests/test_macro_m0b3_offline.py",
        before='    if payload["registry_hash"] != rules_hash(payload):\n'
        '        raise M0B3Error("release discovery registry_hash mismatch")',
        after='    if False:\n'
        '        raise M0B3Error("release discovery registry_hash mismatch")',
        expected_failure_marker="test_rules_reject_status_hash_and_reachable_spec_mutations",
        rationale="Discovery rules must remain bound to their committed hash.",
    ),
    MutationCase(
        mutation_id="MACRO_M1A_MANIFEST_HASH",
        component="Macro M1-A",
        source_path="experiments/macro_os/m1a.py",
        test_script="tests/test_macro_m1a_offline.py",
        before='    if manifest["artifacts"] != expected_hashes:\n'
        '        raise M1AError("M1-A manifest does not match published artifacts")',
        after='    if False:\n'
        '        raise M1AError("M1-A manifest does not match published artifacts")',
        expected_failure_marker="test_calibration_and_manifest_mutations_fail_closed",
        rationale="A published M1-A bundle must match its byte-level manifest.",
    ),
    MutationCase(
        mutation_id="MACRO_M1A_STALENESS",
        component="Macro M1-A",
        source_path="experiments/macro_os/m1a.py",
        test_script="tests/test_macro_m1a_offline.py",
        before='    if age_seconds > int(rule["max_age_seconds"]):\n'
        '        base.update({"data_status": "STALE", "reason": "OBSERVATION_EXPIRED"})\n'
        "        return base",
        after='    if False:\n'
        '        base.update({"data_status": "STALE", "reason": "OBSERVATION_EXPIRED"})\n'
        "        return base",
        expected_failure_marker="test_stale_official_observation_cannot_emit_a_factor_signal",
        rationale="Expired official observations cannot emit current factor signals.",
    ),
    MutationCase(
        mutation_id="MACRO_M1A_RISK_BUDGET_EVIDENCE",
        component="Macro M1-A",
        source_path="experiments/macro_os/m1a.py",
        test_script="tests/test_macro_m1a_offline.py",
        before='    if data["risk_budget_context"] != expected_budget:\n'
        '        raise M1AError("risk-budget context must come from observed credit stress, not missing evidence")',
        after='    if False:\n'
        '        raise M1AError("risk-budget context must come from observed credit stress, not missing evidence")',
        expected_failure_marker="test_missing_evidence_cannot_tighten_risk_budget",
        rationale="Missing Macro evidence cannot be reinterpreted as a risk-budget tightening signal.",
    ),
    MutationCase(
        mutation_id="MACRO_M1B_FORBIDDEN_OUTPUT",
        component="Macro M1-B",
        source_path="experiments/macro_os/m1b.py",
        test_script="tests/test_macro_m1b_offline.py",
        before="            if str(key).casefold() in FORBIDDEN_KEYS:\n"
        '                raise M1BError(f"forbidden M1-B output field: {key}")',
        after="            if False:\n"
        '                raise M1BError(f"forbidden M1-B output field: {key}")',
        expected_failure_marker="test_forbidden_action_and_formal_state_remain_impossible",
        rationale="Macro consumers may not publish trade actions or direct blocks.",
    ),
    MutationCase(
        mutation_id="MACRO_M1B_FORMAL_STATE",
        component="Macro M1-B",
        source_path="experiments/macro_os/m1b.py",
        test_script="tests/test_macro_m1b_offline.py",
        before='    if payload["data"]["mrg"]["formal_state"] is not None:\n'
        '        raise M1BError("panel cannot promote MRG to a formal state")',
        after='    if False:\n'
        '        raise M1BError("panel cannot promote MRG to a formal state")',
        expected_failure_marker="test_forbidden_action_and_formal_state_remain_impossible",
        rationale="CALIBRATING MRG output cannot be promoted to a formal regime.",
    ),
    MutationCase(
        mutation_id="MACRO_M1B_RANKING",
        component="Macro M1-B",
        source_path="experiments/macro_os/m1b.py",
        test_script="tests/test_macro_m1b_offline.py",
        before='    if payload["data"]["ranking_allowed"] is not False:\n'
        '        raise M1BError("portfolio score cannot become a ranking input")',
        after='    if False:\n'
        '        raise M1BError("portfolio score cannot become a ranking input")',
        expected_failure_marker="test_current_context_contributions_scores_and_ranking_are_recomputed",
        rationale="Calibration-only portfolio context cannot become a ranking input.",
    ),
    MutationCase(
        mutation_id="MACRO_M1C_FAILURE_ISOLATION",
        component="Macro M1-C nightly boundary",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_macro_m1c_offline.py",
        before='        if name in ISOLATED_CALIBRATION_STEPS and status != "OK":',
        after='        if False:',
        expected_failure_marker="test_macro_failure_is_isolated_and_cannot_stop_unrelated_publication",
        rationale="A calibration-only Macro failure cannot veto unrelated nightly publication.",
    ),
    MutationCase(
        mutation_id="MACRO_M1C_ISOLATION_ALLOWLIST",
        component="Macro M1-C nightly boundary",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_macro_m1c_offline.py",
        before="    _validate_isolated_calibration_steps()",
        after="    pass  # mutation: skip isolation allowlist validation",
        expected_failure_marker="test_business_steps_cannot_enter_macro_isolation_allowlist",
        rationale="Business-critical steps must never acquire calibration failure isolation.",
    ),
    MutationCase(
        mutation_id="MACRO_M1C_FAILURE_VISIBILITY",
        component="Macro M1-C nightly observability",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_macro_m1c_offline.py",
        before='        if not entry.get("blocks_publication", True):',
        after="        if False:",
        expected_failure_marker="test_failed_macro_step_discards_partial_outputs_but_keeps_inputs",
        rationale="An isolated Macro failure must remain visible in top-level data quality during production verification.",
    ),
    MutationCase(
        mutation_id="MACRO_M1C_RUN_AUTHORITY_CALL",
        component="Macro M1-C runtime boundary",
        source_path="experiments/macro_os/m1c.py",
        test_script="tests/test_macro_m1c_offline.py",
        before="    _walk_authority(manifest)",
        after="    pass  # mutation: skip pre-write authority validation",
        expected_failure_marker="test_run_calls_authority_validator_before_writing_manifest",
        rationale="The runtime must invoke the calibration authority validator before writing its manifest.",
    ),
    MutationCase(
        mutation_id="MACRO_M1C_VALIDATE_AUTHORITY_CALL",
        component="Macro M1-C validation boundary",
        source_path="experiments/macro_os/m1c.py",
        test_script="tests/test_macro_m1c_offline.py",
        before="    _walk_authority(payload)",
        after="    pass  # mutation: skip published-manifest authority validation",
        expected_failure_marker="test_validate_run_calls_authority_validator",
        rationale="Published M1-C manifests must pass the calibration authority validator.",
    ),
    MutationCase(
        mutation_id="AIOS_REQUEST_SPEC_BLOCK",
        component="AIOS AgentAdapter",
        source_path="scripts/llm/adapters/base.py",
        test_script="tests/test_agent_adapter_offline.py",
        before="    if errors:\n        return _result(",
        after="    if False and errors:\n        return _result(",
        expected_failure_marker="test_invalid_request_fails_closed_without_calling_worker",
        rationale="Invalid agent requests must fail closed before provider execution.",
        test_function="test_invalid_request_fails_closed_without_calling_worker",
    ),
    MutationCase(
        mutation_id="R015_PUBLICATION_MIGRATION_EVENT_UNIQUENESS",
        component="R-015 event ledger",
        source_path="experiments/execution_tracker/event_ledger.py",
        test_script="tests/test_registry_schema_v2.py",
        before='                "publication_migration_intent", "publication_migration_commit",\n'
        '                "publication_migration_abort"}',
        after='                "publication_migration_abort"}',
        expected_failure_marker="test_publication_migration_events_are_unique_and_chain_valid",
        rationale="Publication migration WAL terminal events cannot be duplicated on retry.",
    ),
    MutationCase(
        mutation_id="R043_FIRST_WAL_APPEND_RECOVERY",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before="        _bootstrap_control_ledger(ctx)\n"
        "        pending = _pending_for_run(_load_events(ctx), plan[\"run_id\"])",
        after="        pending = _pending_for_run(_load_events(ctx), plan[\"run_id\"])",
        expected_failure_marker="test_first_intent_crash_before_anchor_advance_is_recoverable",
        rationale="The first intent append must retain a recoverable n=0 anchor crash boundary.",
    ),
    MutationCase(
        mutation_id="R043_POINTER_ARTIFACT_REPLACEMENT",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='    target_current["artifacts"] = copy.deepcopy(actual)\n',
        after='    target_current["artifacts"] = copy.deepcopy(current.get("artifacts"))\n',
        expected_failure_marker="test_migration_replaces_pointer_artifact_map",
        rationale="The current_run artifact map must be replaced by the complete manifest map.",
    ),
    MutationCase(
        mutation_id="R043_POINTER_MANIFEST_EQUALITY",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='        if current.get("artifacts") != manifest_artifacts:\n'
        '            problems.append("current_run artifact map differs from current manifest")',
        after='        if False:\n'
        '            problems.append("current_run artifact map differs from current manifest")',
        expected_failure_marker="test_verify_rejects_pointer_manifest_artifact_map_drift",
        rationale="Verification must reject pointer and manifest artifact-map drift.",
    ),
    MutationCase(
        mutation_id="R043_APPROVAL_EVIDENCE_STRENGTH",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='    if str(approval.get("evidence_strength") or "") != "TRANSCRIPT_ONLY_NOT_CRYPTOGRAPHIC":\n'
        '        raise MigrationError(\n'
        '            "approval must self-declare evidence_strength=TRANSCRIPT_ONLY_NOT_CRYPTOGRAPHIC "\n'
        '            "— the ledger must not imply more proof than it holds")',
        after='    if False:\n'
        '        raise MigrationError(\n'
        '            "approval must self-declare evidence_strength=TRANSCRIPT_ONLY_NOT_CRYPTOGRAPHIC "\n'
        '            "— the ledger must not imply more proof than it holds")',
        expected_failure_marker="test_approval_must_carry_verbatim_text_and_honest_strength",
        rationale="Transcript-only approval must not masquerade as cryptographic identity proof.",
    ),
    MutationCase(
        mutation_id="R043_APPROVAL_CHANNEL",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='    if approval.get("approval_channel") != "session_verbatim":\n'
        '        raise MigrationError("approval_channel must be session_verbatim (plan B)")',
        after='    if False:\n'
        '        raise MigrationError("approval_channel must be session_verbatim (plan B)")',
        expected_failure_marker="test_approval_must_carry_verbatim_text_and_honest_strength",
        rationale="R-043 accepts only the explicitly documented transcript evidence channel.",
    ),
    MutationCase(
        mutation_id="R043_APPROVAL_VERBATIM",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='    if len(verbatim) < 12:\n'
        '        raise MigrationError(\n'
        '            "approval_verbatim must carry the human authorization text, quoted in full")',
        after='    if False:\n'
        '        raise MigrationError(\n'
        '            "approval_verbatim must carry the human authorization text, quoted in full")',
        expected_failure_marker="test_approval_verbatim_length_floor_is_enforced",
        rationale="A bare yes/no token is not enough audit evidence for an irreversible migration.",
    ),
    MutationCase(
        mutation_id="R043_APPROVAL_FRESHNESS",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='    if approved_at - requested_at > dt.timedelta(hours=APPROVAL_MAX_AGE_HOURS):\n'
        '        raise MigrationError(\n'
        '            f"approval is stale: approved_at exceeds requested_at by more than "\n'
        '            f"{APPROVAL_MAX_AGE_HOURS}h — re-approve against a fresh plan")',
        after='    if False:\n'
        '        raise MigrationError(\n'
        '            f"approval is stale: approved_at exceeds requested_at by more than "\n'
        '            f"{APPROVAL_MAX_AGE_HOURS}h — re-approve against a fresh plan")',
        expected_failure_marker="test_approval_must_carry_verbatim_text_and_honest_strength",
        rationale="Old transcript evidence cannot be replayed onto a newly requested plan indefinitely.",
    ),
    MutationCase(
        mutation_id="R043_APPROVAL_PLAN_BINDING",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='    if approval.get("plan_hash") != plan_hash:\n'
        '        raise MigrationError("approval is not bound to this plan_hash")',
        after='    if False:\n'
        '        raise MigrationError("approval is not bound to this plan_hash")',
        expected_failure_marker="test_empty_or_self_reported_approval_cannot_authorize",
        rationale="A signed approval cannot be replayed onto a different migration plan.",
    ),
    MutationCase(
        mutation_id="R043_APPROVAL_ORDERING",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='    if approved_at < requested_at:\n'
        '        raise MigrationError("approved_at must not precede requested_at")',
        after='    if False:\n'
        '        raise MigrationError("approved_at must not precede requested_at")',
        expected_failure_marker="test_empty_or_self_reported_approval_cannot_authorize",
        rationale="A pre-existing approval cannot authorize a later migration request.",
    ),
    MutationCase(
        mutation_id="R043_STATE_FILE_TOPOLOGY",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='        if descriptor != expected_state[entry["name"]]:\n'
        '            raise MigrationError(f"state file descriptor is invalid: {entry[\'name\']}")',
        after='        if False:\n'
        '            raise MigrationError(f"state file descriptor is invalid: {entry[\'name\']}")',
        expected_failure_marker="test_signed_plan_with_wrong_file_topology_is_rejected",
        rationale="A valid signature cannot authorize a plan that targets arbitrary files.",
    ),
    MutationCase(
        mutation_id="R043_CURRENT_RUN_BINDING",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='    if et.get("run_id") != run_id:\n'
        '        raise MigrationError(\n'
        '            f"requested run_id {run_id} is not current ({et.get(\'run_id\')})"\n'
        '        )',
        after='    if False:\n'
        '        raise MigrationError(\n'
        '            f"requested run_id {run_id} is not current ({et.get(\'run_id\')})"\n'
        '        )',
        expected_failure_marker="test_old_run_id_is_rejected_before_plan",
        rationale="A migration cannot rebind current_run to a historical run.",
    ),
    MutationCase(
        mutation_id="R043_PLAN_TOCTOU",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='        if rebuilt["plan_hash"] != plan["plan_hash"]:\n'
        '            raise MigrationError("live state changed after planning; plan_hash is stale")',
        after='        if False:\n'
        '            raise MigrationError("live state changed after planning; plan_hash is stale")',
        expected_failure_marker="test_plan_hash_toctou_refuses_before_intent",
        rationale="Apply must recheck the frozen plan after taking nightly.lock.",
    ),
    MutationCase(
        mutation_id="R043_NOOP_FULL_VERIFY",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='            if problems:\n'
        '                raise MigrationError(f"NOOP refused because full verification failed: {problems}")',
        after='            if False:\n'
        '                raise MigrationError(f"NOOP refused because full verification failed: {problems}")',
        expected_failure_marker="test_noop_requires_full_verification",
        rationale="NOOP is valid only after complete publication verification.",
    ),
    MutationCase(
        mutation_id="R043_CURRENT_MANIFEST_EQUALITY",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='        if et_sha != public_sha:\n'
        '            problems.append("ET/public manifests differ")',
        after='        if False:\n'
        '            problems.append("ET/public manifests differ")',
        expected_failure_marker="test_noop_rejects_et_public_manifest_byte_drift",
        rationale="NOOP cannot hide byte drift between durable and published manifests.",
    ),
    MutationCase(
        mutation_id="R043_VERIFY_BEFORE_COMMIT",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='    if problems:\n'
        '        raise MigrationError(f"post-migration verification failed: {problems}")',
        after='    if False:\n'
        '        raise MigrationError(f"post-migration verification failed: {problems}")',
        expected_failure_marker="test_verify_failure_cannot_be_committed",
        rationale="A publication migration cannot append commit after target verification fails.",
    ),
    MutationCase(
        mutation_id="R043_COMMIT_RECEIPT_BINDING",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='        if recorded_receipt != receipt:\n'
        '            raise MigrationError("committed migration verification receipt drifted")',
        after='        if False:\n'
        '            raise MigrationError("committed migration verification receipt drifted")',
        expected_failure_marker="test_committed_verification_receipt_drift_is_rejected",
        rationale="A committed event must remain bound to the exact target bytes it verified.",
    ),
    MutationCase(
        mutation_id="R043_ABORT_TERMINAL_WRITE",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='    event_ledger.append(\n'
        '        "publication_migration_abort",',
        after='    if False:\n'
        '        event_ledger.append(\n'
        '            "publication_migration_abort",',
        expected_failure_marker="test_intent_then_third_state_drift_refuses_recovery",
        rationale="An unrecoverable intent must receive one durable abort terminal, not remain wedged forever.",
    ),
    MutationCase(
        mutation_id="R043_TERMINAL_EXCLUSIVITY",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='    if len(terminals) > 1:\n'
        '        raise MigrationError(f"migration {migration_id} has two terminal states")',
        after='    if False:\n'
        '        raise MigrationError(f"migration {migration_id} has two terminal states")',
        expected_failure_marker="test_dual_terminal_state_is_rejected",
        rationale="Commit and abort are mutually exclusive terminal states for one migration.",
    ),
    MutationCase(
        mutation_id="R043_RECOVERY_ARTIFACT_PREWRITE",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='        if _current_digest(path) != row["sha256_after"]:\n',
        after='        if False and _current_digest(path) != row["sha256_after"]:\n',
        expected_failure_marker="test_recover_refuses_before_any_write_when_artifact_drifts",
        rationale="Recovery must reject changed artifacts before rewriting any manifest or pointer.",
    ),
    MutationCase(
        mutation_id="R043_RECOVERY_THIRD_STATE",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='    if current not in allowed:\n'
        '        raise RecoveryConflict(\n'
        '            f"file drifted outside frozen before/after states: {path} ({current})"\n'
        '        )',
        after='    if False:\n'
        '        raise RecoveryConflict(\n'
        '            f"file drifted outside frozen before/after states: {path} ({current})"\n'
        '        )',
        expected_failure_marker="test_intent_then_third_state_drift_refuses_recovery",
        rationale="Recovery may converge only frozen before or target bytes.",
    ),
    MutationCase(
        mutation_id="R043_CONTROL_WAL_CYCLE",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='    if overlap:\n'
        '        raise MigrationError(f"control WAL cannot be governed by its own manifest: {sorted(overlap)}")',
        after='    if False:\n'
        '        raise MigrationError(f"control WAL cannot be governed by its own manifest: {sorted(overlap)}")',
        expected_failure_marker="test_control_ledger_cannot_enter_governed_manifest",
        rationale="The migration WAL cannot create a circular hash dependency with its manifest.",
    ),
    MutationCase(
        mutation_id="R043_PUBLICATION_STATE_BINDING",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='    if publication_state.get("run_id") != run_id:\n'
        '        raise MigrationError("publication_state does not name the current run")',
        after='    if False:\n'
        '        raise MigrationError("publication_state does not name the current run")',
        expected_failure_marker="test_publication_state_is_frozen_and_must_name_current_run",
        rationale="The durable publication commit must name the run being migrated.",
    ),
    MutationCase(
        mutation_id="R043_DEDICATED_WAL_KINDS",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='        if not row.get("kind", "").startswith("publication_migration_"):\n'
        '            raise MigrationError(f"foreign event kind in dedicated migration WAL: {row.get(\'kind\')}")',
        after='        if False:\n'
        '            raise MigrationError(f"foreign event kind in dedicated migration WAL: {row.get(\'kind\')}")',
        expected_failure_marker="test_foreign_event_kind_is_rejected_in_dedicated_wal",
        rationale="The dedicated control ledger cannot silently mix unrelated event domains.",
    ),
    MutationCase(
        mutation_id="R043_CONTROL_WAL_GIT_PREFIX",
        component="R-043 publication migration",
        source_path="experiments/execution_tracker/publication_migration.py",
        test_script="tests/test_publication_migration_offline.py",
        before='    if not chain["ok"] or not anchor["ok"] or not append_only["ok"]:\n',
        after='    if not chain["ok"] or not anchor["ok"]:\n',
        expected_failure_marker="test_committed_control_wal_rewrite_is_rejected_by_git_prefix",
        rationale="A self-consistent rewrite of committed migration history must fail the R-015 git-prefix layer.",
    ),
    MutationCase(
        mutation_id="AIOS_DEEPSEEK_NETWORK_POLICY",
        component="AIOS DeepSeek adapter",
        source_path="scripts/llm/adapters/deepseek.py",
        test_script="tests/test_agent_adapter_offline.py",
        before='        if self._allow_real_call and request.network_policy != "provider_only":\n'
        '            raise PermissionError("real DeepSeek calls require network_policy=provider_only")',
        after='        if False:\n'
        '            raise PermissionError("real DeepSeek calls require network_policy=provider_only")',
        expected_failure_marker="test_deepseek_real_call_requires_provider_network_policy",
        rationale="A real provider call requires an explicit provider-only network policy.",
        test_function="test_deepseek_real_call_requires_provider_network_policy",
    ),
    MutationCase(
        mutation_id="AIOS_DEEPSEEK_USAGE_REQUIRED",
        component="AIOS DeepSeek adapter",
        source_path="scripts/llm/adapters/deepseek.py",
        test_script="tests/test_agent_adapter_offline.py",
        before="        usage = usage_from_response(response, model=self.model, require_reported=self._allow_real_call)",
        after="        usage = usage_from_response(response, model=self.model, require_reported=False)",
        expected_failure_marker="test_deepseek_real_call_requires_reported_usage",
        rationale="Paid provider calls cannot succeed without reported usage.",
        test_function="test_deepseek_real_call_requires_reported_usage",
    ),
    MutationCase(
        mutation_id="AIOS_KIMI_NETWORK_POLICY",
        component="AIOS Kimi adapter",
        source_path="scripts/llm/adapters/kimi.py",
        test_script="tests/test_agent_adapter_offline.py",
        before='        if request.network_policy != "provider_only":\n'
        '            raise PermissionError("Kimi requires network_policy=provider_only")',
        after='        if False:\n'
        '            raise PermissionError("Kimi requires network_policy=provider_only")',
        expected_failure_marker="test_kimi_wrapper_denies_wrong_network_policy",
        rationale="Kimi execution cannot bypass the provider-only network policy.",
        test_function="test_kimi_wrapper_denies_wrong_network_policy",
    ),
    MutationCase(
        mutation_id="AIOS_A035_SIDE_EFFECT_BEFORE_GATE",
        component="AIOS A-035 Harness Eval",
        source_path="scripts/llm/ai_os/harness_eval.py",
        test_script="tests/test_ai_os_a035_harness_eval_offline.py",
        before='        if observation.decision == "DENY" and observation.side_effect_count != 0:',
        after="        if False:",
        expected_failure_marker="test_denial_after_side_effect_is_not_safe",
        rationale="A denial is not safe when a side effect already happened.",
        test_function="test_denial_after_side_effect_is_not_safe",
    ),
    MutationCase(
        mutation_id="AIOS_A035_CURRENT_HEAD",
        component="AIOS A-035 Harness Eval",
        source_path="scripts/llm/ai_os/harness_eval.py",
        test_script="tests/test_ai_os_a035_harness_eval_offline.py",
        before=(
            "        if observation.evidence_head != case.current_head and not (\n"
            '            observation.decision == "DENY"\n'
            '            and observation.reason == "STALE_EVIDENCE"\n'
            "        ):"
        ),
        after="        if False:",
        expected_failure_marker="test_stale_head_cannot_support_allow",
        rationale="An allow receipt cannot rely on evidence from a different head.",
        test_function="test_stale_head_cannot_support_allow",
    ),
    MutationCase(
        mutation_id="AIOS_A035_REVIEW_INDEPENDENCE",
        component="AIOS A-035 Harness Eval",
        source_path="scripts/llm/ai_os/harness_eval.py",
        test_script="tests/test_ai_os_a035_harness_eval_offline.py",
        before=(
            "        if case.require_independent_review and (\n"
            "            observation.executor_id == observation.reviewer_id\n"
            "            and not (\n"
            '                observation.decision == "DENY"\n'
            '                and observation.reason == "REVIEW_NOT_INDEPENDENT"\n'
            "            )\n"
            "        ):"
        ),
        after="        if False:",
        expected_failure_marker="test_executor_self_review_cannot_support_allow",
        rationale="The executor cannot be the independent reviewer for an allow receipt.",
        test_function="test_executor_self_review_cannot_support_allow",
    ),
    MutationCase(
        mutation_id="AIOS_A035_EXPECTED_DECISION",
        component="AIOS A-035 Harness Eval",
        source_path="scripts/llm/ai_os/harness_eval.py",
        test_script="tests/test_ai_os_a035_harness_eval_offline.py",
        before="        if observation.decision != case.expected_decision:",
        after="        if False:",
        expected_failure_marker="test_false_pass_and_false_reject_are_distinguished",
        rationale="Harness Evals must distinguish false passes from false rejects.",
        test_function="test_false_pass_and_false_reject_are_distinguished",
    ),
    MutationCase(
        mutation_id="AIOS_A035_REASON_ATTRIBUTION",
        component="AIOS A-035 Harness Eval",
        source_path="scripts/llm/ai_os/harness_eval.py",
        test_script="tests/test_ai_os_a035_harness_eval_offline.py",
        before="        if observation.reason != case.expected_reason:",
        after="        if False:",
        expected_failure_marker="test_wrong_reason_is_not_accepted",
        rationale="A matching decision with the wrong reason is not a valid regression pass.",
        test_function="test_wrong_reason_is_not_accepted",
    ),
    MutationCase(
        mutation_id="AIOS_A035_MATRIX_HASH",
        component="AIOS A-035 Harness Eval",
        source_path="scripts/llm/ai_os/harness_eval.py",
        test_script="tests/test_ai_os_a035_harness_eval_offline.py",
        before="    matrix_hash = _hash_json(matrix)",
        after="    matrix_hash = None",
        expected_failure_marker="test_matrix_hash_is_stable_and_content_sensitive",
        rationale="A Harness Eval report must bind the exact matrix content.",
        test_function="test_matrix_hash_is_stable_and_content_sensitive",
    ),
    MutationCase(
        mutation_id="AIOS_A035_OBSERVATIONS_HASH",
        component="AIOS A-035 Harness Eval",
        source_path="scripts/llm/ai_os/harness_eval.py",
        test_script="tests/test_ai_os_a035_harness_eval_offline.py",
        before="    observations_hash = _hash_json(canonical_observations)",
        after="    observations_hash = matrix_hash",
        expected_failure_marker="test_observations_hash_is_stable_and_content_sensitive",
        rationale="A Harness Eval report must bind the exact normalized observations.",
        test_function="test_observations_hash_is_stable_and_content_sensitive",
    ),
    MutationCase(
        mutation_id="AIOS_A035_PRINCIPAL_CANONICALIZATION",
        component="AIOS A-035 Harness Eval",
        source_path="scripts/llm/ai_os/harness_eval.py",
        test_script="tests/test_ai_os_a035_harness_eval_offline.py",
        before="    if subject != subject.casefold():",
        after="    if False:",
        expected_failure_marker="test_github_case_alias_cannot_claim_independent_review",
        rationale="Case aliases of one GitHub principal cannot satisfy independent review.",
        test_function="test_github_case_alias_cannot_claim_independent_review",
    ),
    MutationCase(
        mutation_id="AIOS_A035_REQUIRED_INDEPENDENCE",
        component="AIOS A-035 Harness Eval",
        source_path="scripts/llm/ai_os/harness_eval.py",
        test_script="tests/test_ai_os_a035_harness_eval_offline.py",
        before=(
            "        if (\n"
            "            (domain, expected_decision) in INDEPENDENT_REVIEW_CASES\n"
            "            and independent is not True\n"
            "        ):"
        ),
        after="        if False:",
        expected_failure_marker="test_matrix_cannot_disable_done_allow_independence",
        rationale="A matrix cannot switch off the DONE allow independent-review invariant.",
        test_function="test_matrix_cannot_disable_done_allow_independence",
    ),
    MutationCase(
        mutation_id="AIOS_A035_SECRET_CASE_ID_BLOCK",
        component="AIOS A-035 Harness Eval",
        source_path="scripts/llm/ai_os/harness_eval.py",
        test_script="tests/test_ai_os_a035_harness_eval_offline.py",
        before="        elif _contains_secret_like(case_id):",
        after="        elif False:",
        expected_failure_marker="test_rejected_identifiers_never_echo_secret_like_values",
        rationale="Secret-like matrix identifiers must fail closed before entering reports.",
        test_function="test_rejected_identifiers_never_echo_secret_like_values",
    ),
    MutationCase(
        mutation_id="AIOS_A035_ERROR_ID_REDACTION",
        component="AIOS A-035 Harness Eval",
        source_path="scripts/llm/ai_os/harness_eval.py",
        test_script="tests/test_ai_os_a035_harness_eval_offline.py",
        before='        errors.append(f"unknown observations: count={len(unknown)}")',
        after='        errors.append(f"unknown observations: {unknown}")',
        expected_failure_marker="test_rejected_identifiers_never_echo_secret_like_values",
        rationale="Rejected observation identifiers cannot be copied into logs or reports.",
        test_function="test_rejected_identifiers_never_echo_secret_like_values",
    ),
    MutationCase(
        mutation_id="AIOS_K1_TASK_REQUIRED_FIELDS",
        component="AIOS K1 Task Compiler",
        source_path="scripts/llm/ai_os/task_compiler.py",
        test_script="tests/test_ai_os_k1_offline.py",
        before="    if errors:\n        return CompileResult(SPEC_BLOCKED, None, tuple(errors))",
        after="    if False:\n        return CompileResult(SPEC_BLOCKED, None, tuple(errors))",
        expected_failure_marker="test_task_manifest_missing_acceptance_fails_closed",
        rationale="Incomplete task specifications must remain SPEC_BLOCKED.",
        test_function="test_task_manifest_missing_acceptance_fails_closed",
    ),
    MutationCase(
        mutation_id="AIOS_K1_STATE_TRANSITION",
        component="AIOS K1 Registry",
        source_path="scripts/llm/ai_os/registry.py",
        test_script="tests/test_ai_os_k1_offline.py",
        before="        if (from_state, to_state) not in ALLOWED_TRANSITIONS:\n"
        "            invalid_events.append(\n"
        "                _invalid(index, event, f\"transition {from_state}->{to_state} is not allowed\")\n"
        "            )\n"
        "            continue",
        after="        if False:\n"
        "            invalid_events.append(\n"
        "                _invalid(index, event, f\"transition {from_state}->{to_state} is not allowed\")\n"
        "            )\n"
        "            continue",
        expected_failure_marker="test_registry_blocks_forbidden_done_shortcut",
        rationale="Registry state transitions cannot skip review and verification states.",
        test_function="test_registry_blocks_forbidden_done_shortcut",
    ),
    MutationCase(
        mutation_id="AIOS_K1_UNLINKED_OPEN_PR",
        component="AIOS K1 Reconciler",
        source_path="scripts/llm/ai_os/reconciler.py",
        test_script="tests/test_ai_os_k1_offline.py",
        before="        if missing:\n"
        "            findings.append(\n"
        "                {\n"
        '                    "pr": pr.get("number"),\n'
        '                    "missing": missing,\n'
        '                    "reason": "open PR is not fully linked to AIOS control records",\n'
        "                }\n"
        "            )",
        after="        if False:\n"
        "            findings.append(\n"
        "                {\n"
        '                    "pr": pr.get("number"),\n'
        '                    "missing": missing,\n'
        '                    "reason": "open PR is not fully linked to AIOS control records",\n'
        "                }\n"
        "            )",
        expected_failure_marker="test_reconciler_does_not_hide_open_unlinked_pr",
        rationale="Open PRs missing AIOS control links must remain visible findings.",
        test_function="test_reconciler_does_not_hide_open_unlinked_pr",
    ),
    MutationCase(
        mutation_id="AIOS_K1_UNKNOWN_PR",
        component="AIOS K1 Reconciler",
        source_path="scripts/llm/ai_os/reconciler.py",
        test_script="tests/test_ai_os_k1_offline.py",
        before='        return [{**owner, "pr": number, "reason": "DONE references unknown PR"}]',
        after="        return []",
        expected_failure_marker="test_reconciler_does_not_hide_done_with_unknown_pr",
        rationale="DONE evidence pointing to an unknown PR cannot be treated as clean.",
        test_function="test_reconciler_does_not_hide_done_with_unknown_pr",
    ),
    MutationCase(
        mutation_id="AIOS_K1_OVERSOLD_DONE_EVIDENCE",
        component="AIOS K1 Reconciler",
        source_path="scripts/llm/ai_os/reconciler.py",
        test_script="tests/test_ai_os_k1_offline.py",
        before="            if missing:\n"
        "                findings.append(\n"
        "                    {\n"
        '                        "task": event.get("task"),\n'
        '                        "missing": missing,\n'
        '                        "reason": "DONE comment lacks required evidence fields",\n'
        "                    }\n"
        "                )\n"
        "                continue",
        after="            if False:\n"
        "                findings.append(\n"
        "                    {\n"
        '                        "task": event.get("task"),\n'
        '                        "missing": missing,\n'
        '                        "reason": "DONE comment lacks required evidence fields",\n'
        "                    }\n"
        "                )\n"
        "                continue",
        expected_failure_marker="test_reconciler_reports_done_comment_missing_required_fields",
        rationale="DONE cannot be accepted without its required evidence fields.",
        test_function="test_reconciler_reports_done_comment_missing_required_fields",
    ),
    MutationCase(
        mutation_id="GOVERNANCE_K1_MARKER_COVERAGE_CALL",
        component="Governance mutation gate",
        source_path="scripts/governance_mutation_gate.py",
        test_script="tests/test_governance_mutation_gate.py",
        before=("    validate_k1_" "marker_coverage(root, cases)"),
        after=(
            "    if False:\n"
            "        validate_k1_"
            "marker_coverage(root, cases)"
        ),
        expected_failure_marker="test_validate_manifest_enforces_k1_marker_coverage",
        rationale="The manifest validator must not silently stop enforcing K1 marker coverage.",
    ),
    MutationCase(
        mutation_id="GOVERNANCE_A035_MARKER_COVERAGE_CALL",
        component="Governance mutation gate",
        source_path="scripts/governance_mutation_gate.py",
        test_script="tests/test_governance_mutation_gate.py",
        before=("    validate_a035_" "marker_coverage(root, cases)"),
        after=(
            "    if False:\n"
            "        validate_a035_"
            "marker_coverage(root, cases)"
        ),
        expected_failure_marker="test_validate_manifest_enforces_a035_marker_coverage",
        rationale="The mutation manifest must enforce A-035 marker coverage.",
    ),
    MutationCase(
        mutation_id="GOVERNANCE_R043_MARKER_COVERAGE_CALL",
        component="Governance mutation gate",
        source_path="scripts/governance_mutation_gate.py",
        test_script="tests/test_governance_mutation_gate.py",
        before=("    validate_r043_" "marker_coverage(root, cases)"),
        after=(
            "    if False:\n"
            "        validate_r043_"
            "marker_coverage(root, cases)"
        ),
        expected_failure_marker="test_validate_manifest_enforces_r043_marker_coverage",
        rationale="The mutation manifest must not silently stop enforcing R-043 marker coverage.",
    ),
    MutationCase(
        mutation_id="GOVERNANCE_LOCAL_TARGET_REQUIRED",
        component="Governance mutation gate",
        source_path="scripts/governance_mutation_gate.py",
        test_script="tests/test_governance_mutation_gate.py",
        before=(
            "    if not candidates:\n"
            "        raise MutationGateError(\n"
            '            f"exactly one local test target required: {name}; found 0"\n'
            "        )\n"
        ),
        after=(
            "    if not candidates:\n"
            '        return LocalTestTarget(name=name, kind="function")\n'
        ),
        expected_failure_marker="test_manifest_rejects_imported_and_ambiguous_targets",
        rationale="An imported symbol cannot substitute for a missing local test definition.",
    ),
    MutationCase(
        mutation_id="GOVERNANCE_LOCAL_TARGET_UNIQUENESS",
        component="Governance mutation gate",
        source_path="scripts/governance_mutation_gate.py",
        test_script="tests/test_governance_mutation_gate.py",
        before=(
            "    if len(candidates) > 1:\n"
            "        raise MutationGateError(\n"
            '            f"exactly one local test target required: {name}; found {len(candidates)}"\n'
            "        )\n"
        ),
        after=(
            "    if len(candidates) > 1:\n"
            "        return candidates[0]\n"
        ),
        expected_failure_marker="test_manifest_rejects_imported_and_ambiguous_targets",
        rationale="A declared test target must have exactly one local definition.",
    ),
    MutationCase(
        mutation_id="GOVERNANCE_DYNAMIC_TARGET_OWNERSHIP",
        component="Governance mutation gate",
        source_path="scripts/governance_mutation_gate.py",
        test_script="tests/test_governance_mutation_gate.py",
        before=(
            "def is_expected_runtime_target(value, expected_name):\n"
            "    return (\n"
            '        getattr(value, "__module__", None) == MODULE_NAME\n'
            '        and getattr(value, "__name__", None) == expected_name\n'
            "    )\n"
        ),
        after=(
            "def is_expected_runtime_target(value, expected_name):\n"
            "    return True\n"
        ),
        expected_failure_marker="test_runner_rejects_imported_target_identity",
        rationale="Runtime rebinding cannot replace a local test with an imported object.",
    ),
    MutationCase(
        mutation_id="GOVERNANCE_ASSERTION_ONLY_KILL",
        component="Governance mutation gate",
        source_path="scripts/governance_mutation_gate.py",
        test_script="tests/test_governance_mutation_gate.py",
        before=(
            "    if (\n"
            "        receipt.errors\n"
            "        or receipt.skipped\n"
            "        or receipt.expected_failures\n"
            "        or receipt.unexpected_successes\n"
            "    ):\n"
        ),
        after="    if False:\n",
        expected_failure_marker="test_classifier_rejects_error_and_skip_receipts",
        rationale="Errors, skips, and expected failures cannot masquerade as mutation kills.",
    ),
    MutationCase(
        mutation_id="GOVERNANCE_BASELINE_CLEAN_PASS",
        component="Governance mutation gate",
        source_path="scripts/governance_mutation_gate.py",
        test_script="tests/test_governance_mutation_gate.py",
        before=(
            "        result.returncode != 0\n"
            "        or receipt.failures\n"
            "        or receipt.errors\n"
            "        or receipt.skipped\n"
            "        or receipt.expected_failures\n"
        ),
        after=(
            "        result.returncode != 0\n"
            "        or receipt.failures\n"
            "        or receipt.errors\n"
            "        or False\n"
            "        or receipt.expected_failures\n"
        ),
        expected_failure_marker="test_baseline_requires_one_clean_pass",
        rationale="A skipped baseline is not evidence that the declared test executes cleanly.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U0_NONEMPTY_ELIGIBLE",
        component="Research funnel U0 eligibility",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='    if not rows:\n'
        '        raise FunnelError("U0 has no U1-eligible securities")',
        after='    if False:\n'
        '        raise FunnelError("U0 has no U1-eligible securities")',
        expected_failure_marker="test_u0_zero_eligible_universe_fails_closed",
        rationale="An empty eligible universe cannot be published as a successful zero-row scan.",
    ),
    MutationCase(
        mutation_id="FUNNEL_EVIDENCE_DATE_NORMALIZATION",
        component="Research funnel PIT date parsing",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before="        return _date8(raw)",
        after="        return str(value)",
        expected_failure_marker="test_evidence_dates_normalize_iso_without_lexical_bypass",
        rationale="ISO-formatted evidence dates cannot bypass point-in-time checks through lexical ordering.",
    ),
    MutationCase(
        mutation_id="FUNNEL_E1_SCHEMA_ASOF",
        component="Research funnel E1 boundary",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='    if payload.get("schema") != "ar.e1_event_layer" or payload_as_of != as_of:\n'
        '        raise FunnelError("E1 event layer schema/as_of mismatch")',
        after='    if False:\n'
        '        raise FunnelError("E1 event layer schema/as_of mismatch")',
        expected_failure_marker="test_e1_schema_and_asof_are_bound_to_the_scan",
        rationale="The E1 input must use the expected schema and the same PIT date as U1.",
    ),
    MutationCase(
        mutation_id="FUNNEL_E1_ROWS_HASH",
        component="Research funnel E1 integrity",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='    if payload.get("rows_hash") != _hash(rows):\n'
        '        raise FunnelError("E1 event rows_hash mismatch")',
        after='    if False:\n'
        '        raise FunnelError("E1 event rows_hash mismatch")',
        expected_failure_marker="test_e1_rows_hash_is_recomputed",
        rationale="The funnel cannot trust an E1 payload whose rows no longer match its hash.",
    ),
    MutationCase(
        mutation_id="FUNNEL_E1_VERDICT",
        component="Research funnel E1 vocabulary",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='        if verdict not in {"RED_FLAG", "NO_RED_FLAG_FOUND", "DATA_BLOCKED"}:\n'
        '            raise FunnelError("E1 event verdict is invalid")',
        after='        if False:\n'
        '            raise FunnelError("E1 event verdict is invalid")',
        expected_failure_marker="test_e1_verdict_enum_is_fail_closed",
        rationale="Unknown E1 verdicts cannot become clean funnel evidence.",
    ),
    MutationCase(
        mutation_id="FUNNEL_E1_EVIDENCE_ASOF",
        component="Research funnel E1 PIT boundary",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='        if normalized_latest is not None and normalized_latest > as_of:\n'
        '            raise FunnelError("E1 event evidence exceeds scan as_of")',
        after='        if False:\n'
        '            raise FunnelError("E1 event evidence exceeds scan as_of")',
        expected_failure_marker="test_e1_future_evidence_is_rejected",
        rationale="Evidence published after the scan date cannot enter a point-in-time U1 row.",
    ),
    MutationCase(
        mutation_id="FUNNEL_ROTATION_DATE_BINDING",
        component="Research funnel rotation boundary",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='    if target and target != as_of:\n'
        '        raise FunnelError("rotation panel is not from the requested trade date")',
        after='    if False:\n'
        '        raise FunnelError("rotation panel is not from the requested trade date")',
        expected_failure_marker="test_rotation_panel_date_is_bound_to_scan_date",
        rationale="A stale rotation panel cannot be presented as same-day industry evidence.",
    ),
    MutationCase(
        mutation_id="FUNNEL_MACRO_CALIBRATING",
        component="Research funnel Macro authority",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='    if payload.get("mode") != "CALIBRATING":\n'
        '        raise FunnelError("Macro industry input must remain CALIBRATING")',
        after='    if False:\n'
        '        raise FunnelError("Macro industry input must remain CALIBRATING")',
        expected_failure_marker="test_macro_input_must_remain_calibrating",
        rationale="Macro context cannot silently graduate from calibration inside the funnel.",
    ),
    MutationCase(
        mutation_id="FUNNEL_MACRO_NO_BLOCK_AUTHORITY",
        component="Research funnel Macro authority",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='    if policy.get("formal_blocking_authority") is not False:\n'
        '        raise FunnelError("Macro industry input acquired formal blocking authority")',
        after='    if False:\n'
        '        raise FunnelError("Macro industry input acquired formal blocking authority")',
        expected_failure_marker="test_macro_input_cannot_acquire_formal_blocking_authority",
        rationale="Calibration-only Macro context cannot veto or direct research flow.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U1_NO_COMPOSITE_SCORE",
        component="Research funnel U1",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='    if FORBIDDEN_AGGREGATE_KEYS.intersection(_walk_keys(payload)):\n'
        '        raise FunnelError("cross-channel aggregate score is forbidden")',
        after='    if False:\n'
        '        raise FunnelError("cross-channel aggregate score is forbidden")',
        expected_failure_marker="test_u1_rejects_composite_score_and_missing_channel",
        rationale="U1 channels cannot be combined into a score that offsets contrary evidence.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U1_NO_TRADE_AUTHORITY",
        component="Research funnel U1 authority",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='    if FORBIDDEN_ACTION_KEYS.intersection(_walk_keys(payload)):\n'
        '        raise FunnelError("trade or blocking authority field is forbidden")',
        after='    if False:\n'
        '        raise FunnelError("trade or blocking authority field is forbidden")',
        expected_failure_marker="test_u1_rejects_trade_or_blocking_authority_fields",
        rationale="The scan layer cannot emit a trade action or formal blocking authority.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U1_SOURCE_ASOF",
        component="Research funnel U1 PIT boundary",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='        if normalized_source_as_of is not None and normalized_source_as_of > as_of:\n'
        '            raise FunnelError("all_market_scan source evidence is from the future")',
        after='        if False:\n'
        '            raise FunnelError("all_market_scan source evidence is from the future")',
        expected_failure_marker="test_u1_rejects_future_source_evidence_after_iso_normalization",
        rationale="No channel may carry source evidence newer than the U1 scan date.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U1_DATA_STATUS",
        component="Research funnel U1 data quality",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='        if row["data_status"] not in VALID_DATA_STATUS:\n'
        '            raise FunnelError("invalid channel data_status")',
        after='        if False:\n'
        '            raise FunnelError("invalid channel data_status")',
        expected_failure_marker="test_u1_rejects_unknown_data_status",
        rationale="Unknown status labels cannot bypass visible DATA_BLOCKED/PARTIAL semantics.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U1_SIX_CHANNEL_COVERAGE",
        component="Research funnel U1",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='    if set(seen) != eligible or any(channels != set(CHANNELS) for channels in seen.values()):\n'
        '        raise FunnelError("every eligible security must have exactly six channel rows")',
        after='    if False:\n'
        '        raise FunnelError("every eligible security must have exactly six channel rows")',
        expected_failure_marker="test_u1_rejects_composite_score_and_missing_channel",
        rationale="A full-market scan cannot silently omit one of the six independent channels.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U2_QUOTA_FLOOR",
        component="Research funnel U2 reserved quota",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before="    main_capacity = target_size - reserved_total",
        after="    main_capacity = target_size",
        expected_failure_marker="test_u2_reserved_quota_floor_preserves_main_channel_capacity",
        rationale="Main-channel intake must leave capacity for slow-bull, contrarian and control floors.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U2_CONTROL_ALGORITHM",
        component="Research funnel U2 random control",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='    if frame.get("algo") != CONTROL_ALGO:\n'
        '        raise FunnelError("random control algorithm drift")',
        after='    if False:\n'
        '        raise FunnelError("random control algorithm drift")',
        expected_failure_marker="test_u2_rejects_untraceable_reason_and_algorithm_drift",
        rationale="The preregistered random-control algorithm cannot drift after outcomes become visible.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U2_CONTROL_SEED",
        component="Research funnel U2 random control",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before="    rng = random.Random(int(seed_hex[:16], 16))",
        after="    rng = random.Random(0)",
        expected_failure_marker="test_u2_random_control_is_same_pool_stratified_and_reproducible",
        rationale="The preregistered seed must determine the actual draw, not merely its label.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U2_RED_FLAG_NOT_POSITIVE",
        component="Research funnel U2 red-flag boundary",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before="    selected_main: set[str] = set()",
        after="    selected_main: set[str] = set(red_flag_codes)",
        expected_failure_marker="test_red_flag_without_positive_channel_is_excluded_not_a_u2_candidate",
        rationale="An E1 red flag is an exclusion fact, not a positive candidate signal.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U2_EXACT_EVIDENCE_PROJECTION",
        component="Research funnel U2 evidence boundary",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='        if row.get("source_channels") != expected_channels or row.get("entry_reasons") != expected_reasons:\n'
        '            raise FunnelError("candidate U1 channel/reason projection is not exact")',
        after='        if False:\n'
        '            raise FunnelError("candidate U1 channel/reason projection is not exact")',
        expected_failure_marker="test_u2_rejects_untraceable_reason_and_algorithm_drift",
        rationale="U2 must be an exact projection of the same-day U1 channel evidence.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U4_AUTHORITY_BOUNDARY",
        component="Research funnel U4 authority",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='    if (\n'
        '        authority.get("auto_selection") is not False\n'
        '        or authority.get("human_selection_required") is not True\n'
        '        or authority.get("selection_owner") != "Junyan"\n'
        '    ):\n'
        '        raise FunnelError("U4 authority boundary changed")',
        after='    if False:\n'
        '        raise FunnelError("U4 authority boundary changed")',
        expected_failure_marker="test_u4_authority_boundary_is_not_covered_only_by_rows_hash",
        rationale="Only Junyan may select U4; sibling authority fields need their own fail-closed guard.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U4_SAME_DAY_BATTERY",
        component="Research funnel U4 evidence freshness",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='    if trade_date is not None and target != _date8(trade_date):\n'
        '        raise FunnelError("U3 battery is not from the requested trade date")',
        after='    if False:\n'
        '        raise FunnelError("U3 battery is not from the requested trade date")',
        expected_failure_marker="test_u4_rejects_stale_u3_battery",
        rationale="U4 and U0 cannot advance a candidate using a stale U3 battery artifact.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U4_HUMAN_SELECTION_SIZE",
        component="Research funnel U4 authority",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='    if selected and not 3 <= len(selected) <= 5:\n'
        '        raise FunnelError("U4 human selection must contain 3..5 securities")',
        after='    if False:\n'
        '        raise FunnelError("U4 human selection must contain 3..5 securities")',
        expected_failure_marker="test_u4_selection_size_is_human_governance_gate",
        rationale="The weekly U4 queue must remain an explicit human-selected 3..5-name decision.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U4_NO_TRADE_AUTHORITY",
        component="Research funnel U4 authority",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='    if FORBIDDEN_ACTION_KEYS.intersection(_walk_keys(payload)):\n'
        '        raise FunnelError("U4 queue cannot contain trade or blocking authority")',
        after='    if False:\n'
        '        raise FunnelError("U4 queue cannot contain trade or blocking authority")',
        expected_failure_marker="test_u4_requires_explicit_human_selection_and_never_emits_action",
        rationale="U4 can queue research work but cannot emit an order or acquire blocking authority.",
    ),
    MutationCase(
        mutation_id="FUNNEL_U4_RESEARCH_QUESTION",
        component="Research funnel U4 entry gate",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_research_funnel_closure.py",
        before='    if missing_questions:\n'
        '        raise FunnelError(f"U4 selection lacks a clear research question: {missing_questions}")',
        after='    if False:\n'
        '        raise FunnelError(f"U4 selection lacks a clear research question: {missing_questions}")',
        expected_failure_marker="test_u4_requires_an_explicit_research_question",
        rationale="A U3 name cannot enter deep research without a concrete question to answer.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_PARTIAL_STATUS",
        component="Research funnel industry partial-data honesty",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    return (\n'
        '        "PARTIAL"\n'
        '        if any(row["data_gap_channels"] or row["data_partial_channels"] for row in rows)\n'
        '        else "COMPLETE"\n'
        '    )',
        after='    return "COMPLETE"',
        expected_failure_marker="test_partial_security_data_makes_snapshot_partial",
        rationale="One degraded security must make the snapshot PARTIAL even when the rest of the channel is usable.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_TAXONOMY_CLOSED_WORLD",
        component="Research funnel industry taxonomy shape",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    _require_exact_fields(payload, TAXONOMY_FIELDS, "industry taxonomy")',
        after='    pass',
        expected_failure_marker="test_taxonomy_and_registry_contracts_are_closed_world",
        rationale="Undeclared taxonomy fields cannot smuggle authority into an otherwise valid mapping file.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_TAXONOMY_POLICY",
        component="Research funnel industry taxonomy authority policy",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    if policy != expected_policy:\n'
        '        raise FunnelError("industry taxonomy policy changed")',
        after='    if False:\n'
        '        raise FunnelError("industry taxonomy policy changed")',
        expected_failure_marker="test_taxonomy_policy_guard_is_behaviorally_pinned",
        rationale="The taxonomy cannot acquire production or U4 authority during a refactor.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_IDENTITY_NO_ROTATION",
        component="Research funnel unreviewed industry mapping boundary",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='            rotation_aliases = []',
        after='            rotation_aliases = [source_key]',
        expected_failure_marker="test_identity_only_does_not_guess_cross_source_aliases",
        rationale="An unreviewed exact-name coincidence cannot become rotation confirmation.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_REGISTRY_CLOSED_WORLD",
        component="Research funnel industry registry shape",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    _require_exact_fields(payload, INDUSTRY_REGISTRY_FIELDS, "industry registry")',
        after='    pass',
        expected_failure_marker="test_taxonomy_and_registry_contracts_are_closed_world",
        rationale="The registry contract cannot carry undeclared action or authority fields.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_REGISTRY_POLICY",
        component="Research funnel industry registry authority policy",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    if payload.get("policy") != REGISTRY_POLICY:\n'
        '        raise FunnelError("industry registry authority or coverage policy changed")',
        after='    if False:\n'
        '        raise FunnelError("industry registry authority or coverage policy changed")',
        expected_failure_marker="test_registry_policy_guard_is_behaviorally_pinned",
        rationale="The all-industry registry must retain its no-selection and no-production boundary.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_ALL_INDUSTRIES",
        component="Research funnel industry U0 coverage",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    if rows != expected_rows or payload.get("rows_hash") != _hash(expected_rows):\n'
        '        raise FunnelError("industry registry rows do not cover the U0 taxonomy exactly")',
        after='    if False:\n'
        '        raise FunnelError("industry registry rows do not cover the U0 taxonomy exactly")',
        expected_failure_marker="test_all_u0_industries_are_retained_and_tamper_rejected",
        rationale="Every eligible U0 industry must remain represented even when its mapping is identity-only.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_ROTATION_FRESHNESS",
        component="Research funnel industry rotation point-in-time binding",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='        _validate_rotation_wrapper(payload, data, as_of)',
        after='        pass',
        expected_failure_marker="test_stale_or_blocked_rotation_wrapper_is_rejected",
        rationale="A stale or blocked rotation body cannot borrow a current wrapper date and confirm P1.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_ROTATION_WRAPPER_REQUIRED",
        component="Research funnel industry rotation provenance",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    if not wrapped:\n'
        '        raise FunnelError("rotation panel must use the governed wrapper contract")',
        after='    if False:\n'
        '        raise FunnelError("rotation panel must use the governed wrapper contract")',
        expected_failure_marker="test_rotation_payload_without_governed_wrapper_is_rejected",
        rationale="Raw rotation rows cannot bypass wrapper status, quality, date, and run provenance.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_RELATIVE_BENCHMARK",
        component="Research funnel industry-relative snapshot evidence",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='        relative_benchmark, relative_excess, relative_sample_count = _industry_relative_price_evidence(\n'
        '            codes, scan_by_code,\n'
        '        )',
        after='        relative_benchmark, relative_excess, relative_sample_count = None, {}, 0',
        expected_failure_marker="test_relative_evidence_uses_within_industry_median",
        rationale="Relative evidence must be positive excess over the current industry's median, not raw return.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_ROTATION_ALIAS",
        component="Research funnel industry cross-source context",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='        rotation_context = _rotation_context(industry["rotation_aliases"], rotation_rows)',
        after='        rotation_context = _rotation_context([], rotation_rows)',
        expected_failure_marker="test_semiconductor_rotation_alias_is_observed",
        rationale="A reviewed cross-source alias must affect the industry's research context without changing issuer membership.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_RELATIVE_RESEARCH_ONLY",
        component="Research funnel industry relative-evidence boundary",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='        if any(rep.get("ready_for_u4") is not False for rep in reps):\n'
        '            raise FunnelError("industry cohort representative acquired U4 readiness")',
        after='        if False:\n'
        '            raise FunnelError("industry cohort representative acquired U4 readiness")',
        expected_failure_marker="test_relative_representatives_never_gain_u4_readiness",
        rationale="Industry-relative leaders cannot become U4-ready without absolute U1 evidence and a later human gate.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_RED_FLAG_EXCLUSION",
        component="Research funnel industry E1 exclusion",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='        if red_flags.intersection(codes):\n'
        '            raise FunnelError("E1 red-flag security cannot become an industry representative")',
        after='        if False:\n'
        '            raise FunnelError("E1 red-flag security cannot become an industry representative")',
        expected_failure_marker="test_red_flags_never_become_representatives",
        rationale="A current E1 red flag must exclude a security from every industry representative role.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_NO_AUTHORITY",
        component="Research funnel industry snapshot authority boundary",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    _require_exact_fields(payload, INDUSTRY_SNAPSHOT_FIELDS, "industry snapshot")',
        after='    pass',
        expected_failure_marker="test_forbidden_authority_fields_fail_closed",
        rationale="A closed snapshot contract cannot acquire undeclared trade, U4, or score authority.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_SNAPSHOT_POLICY",
        component="Research funnel industry snapshot authority policy",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    if payload.get("policy") != SNAPSHOT_POLICY:\n'
        '        raise FunnelError("industry snapshot acquired selection or production authority")',
        after='    if False:\n'
        '        raise FunnelError("industry snapshot acquired selection or production authority")',
        expected_failure_marker="test_snapshot_policy_guard_is_behaviorally_pinned",
        rationale="A structurally valid snapshot still cannot change its macro, U4, or production policy.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_RELATIVE_COHORT",
        component="Research funnel industry-relative cohort membership",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='        relative_benchmark, relative_excess, _ = _industry_relative_price_evidence(\n'
        '            selectable, scan_by_code,\n'
        '        )',
        after='        relative_benchmark, relative_excess, _ = None, {}, 0',
        expected_failure_marker="test_relative_evidence_uses_within_industry_median",
        rationale="Relative representatives must be chosen from the same explicit median-excess evidence as the snapshot.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_NO_TRADE_OR_U4_AUTHORITY",
        component="Research funnel industry cohort authority boundary",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    _require_exact_fields(payload, INDUSTRY_COHORT_FIELDS, "industry cohort")',
        after='    pass',
        expected_failure_marker="test_forbidden_authority_fields_fail_closed",
        rationale="A closed cohort contract is research context and cannot emit undeclared trade or U4 authority.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_FIXED_GATE_TEXT",
        component="Research funnel industry next-gate boundary",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    if payload.get("next_gate") != COHORT_NEXT_GATE or payload.get("disclaimer") != DISCLAIMER:\n'
        '        raise FunnelError("industry cohort next gate or disclaimer changed")',
        after='    if False:\n'
        '        raise FunnelError("industry cohort next gate or disclaimer changed")',
        expected_failure_marker="test_cohort_next_gate_and_disclaimer_are_fixed",
        rationale="A valid rows hash cannot legitimize an automatic execution gate or erase the research-only disclaimer.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_RECOMPUTE",
        component="Research funnel industry cohort evidence binding",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    if rows != expected_rows or payload.get("rows_hash") != _hash(expected_rows):\n'
        '        raise FunnelError("industry cohort membership or evidence does not recompute")',
        after='    if False:\n'
        '        raise FunnelError("industry cohort membership or evidence does not recompute")',
        expected_failure_marker="test_cohort_membership_recomputes_from_u1",
        rationale="Representative membership and its channel evidence must recompute from the bound U1 snapshot.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_EVIDENCE_STATUS",
        component="Research funnel industry honest status",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    if (\n'
        '        payload.get("status") != expected_status\n'
        '        or payload.get("coverage") != dict(expected_coverage)\n'
        '    ):\n'
        '        raise FunnelError(f"{label} status/coverage do not recompute from evidence")',
        after='    if False:\n'
        '        raise FunnelError(f"{label} status/coverage do not recompute from evidence")',
        expected_failure_marker="test_status_and_coverage_are_recomputed_from_rows",
        rationale="A contract cannot self-report COMPLETE or inflate coverage independently of its rows.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_UPSTREAM_QUALITY",
        component="Research funnel industry cohort quality propagation",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    if industry_snapshot_status != "COMPLETE":\n'
        '        return "PARTIAL"',
        after='    if False:\n'
        '        return "PARTIAL"',
        expected_failure_marker="test_partial_snapshot_cannot_be_hidden_by_absolute_cohort_rows",
        rationale="Absolute representatives cannot hide partial upstream evidence in the cohort status.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_IMMUTABLE_BUNDLE",
        component="Research funnel industry immutable history",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    if os.path.lexists(target):\n'
        '        raise FunnelError(f"industry cohort bundle already exists; refusing overwrite: {target}")',
        after='    if False:\n'
        '        raise FunnelError(f"industry cohort bundle already exists; refusing overwrite: {target}")',
        expected_failure_marker="test_immutable_bundle_refuses_same_run_overwrite",
        rationale="A later refresh must create a new run rather than overwrite a prior industry snapshot.",
    ),
    MutationCase(
        mutation_id="INDUSTRY_COHORT_EXACT_ARTIFACT_SET",
        component="Research funnel industry bundle path boundary",
        source_path="experiments/research_funnel/industry_cohort.py",
        test_script="tests/test_industry_cohort_offline.py",
        before='    if set(contracts) != set(CONTRACT_SCHEMAS):\n'
        '        raise FunnelError("industry cohort bundle artifact set is not exact")',
        after='    if False:\n'
        '        raise FunnelError("industry cohort bundle artifact set is not exact")',
        expected_failure_marker="test_bundle_artifact_names_cannot_escape_staging",
        rationale="Only the three declared contract names may be written inside the immutable bundle staging directory.",
    ),
    MutationCase(
        mutation_id="FUNNEL_CLOSURE_BUNDLE_HASH",
        component="Research funnel offline closure",
        source_path="experiments/research_funnel/closure_experiment.py",
        test_script="tests/test_research_closure_experiment.py",
        before='    if manifest.get("bundle_hash") != funnel._hash(artifacts):\n'
        '        raise ClosureError("bundle manifest bundle_hash mismatch")',
        after='    if False:\n'
        '        raise ClosureError("bundle manifest bundle_hash mismatch")',
        expected_failure_marker="test_bundle_hash_must_match_manifest_artifacts",
        rationale="A self-consistent artifact list must remain bound to the frozen bundle hash.",
    ),
    MutationCase(
        mutation_id="FUNNEL_CLOSURE_DUPLICATE_JSON_KEYS",
        component="Research funnel offline closure",
        source_path="experiments/research_funnel/closure_experiment.py",
        test_script="tests/test_research_closure_experiment.py",
        before='        if key in value:\n'
        '            raise ClosureError(f"duplicate JSON key: {key}")',
        after='        if False:\n'
        '            raise ClosureError(f"duplicate JSON key: {key}")',
        expected_failure_marker="test_duplicate_json_keys_are_rejected",
        rationale="A duplicated receipt or manifest field cannot present one value to a human and another to the parser.",
    ),
    MutationCase(
        mutation_id="FUNNEL_CLOSURE_PACKET_HASH",
        component="Research funnel offline closure",
        source_path="experiments/research_funnel/closure_experiment.py",
        test_script="tests/test_research_closure_experiment.py",
        before='    if packet.get("packet_hash") != funnel._hash(_without_hash(packet, "packet_hash")):\n'
        '        raise ClosureError("review packet hash mismatch")',
        after='    if False:\n'
        '        raise ClosureError("review packet hash mismatch")',
        expected_failure_marker="test_packet_hash_must_cover_packet",
        rationale="The review packet cannot be edited after its evidence hash is frozen.",
    ),
    MutationCase(
        mutation_id="FUNNEL_CLOSURE_U3_FULL_BATTERY",
        component="Research funnel offline closure",
        source_path="experiments/research_funnel/closure_experiment.py",
        test_script="tests/test_research_closure_experiment.py",
        before='        if (\n'
        '            not isinstance(dims, dict)\n'
        '            or set(dims) != BATTERY_DIMENSIONS\n'
        '            or completeness.get("covered") != 6\n'
        '            or completeness.get("of") != 6\n'
        '            or completeness.get("missing") != []\n'
        '            or any(\n'
        '                not isinstance(value, dict)\n'
        '                or value.get("status") in {"DATA_BLOCKED", "NOT_RUN"}\n'
        '                for value in dims.values()\n'
        '            )\n'
        '        ):\n'
        '            raise ClosureError(f"U3 battery claims COMPLETE without six complete dimensions: {code}")',
        after='        if False:\n'
        '            raise ClosureError(f"U3 battery claims COMPLETE without six complete dimensions: {code}")',
        expected_failure_marker="test_u3_complete_stamp_requires_six_complete_dimensions",
        rationale="A self-reported COMPLETE stamp cannot replace the six actual U3 dimensions.",
    ),
    MutationCase(
        mutation_id="FUNNEL_CLOSURE_RECEIPT_PACKET_BINDING",
        component="Research funnel offline closure",
        source_path="experiments/research_funnel/closure_experiment.py",
        test_script="tests/test_research_closure_experiment.py",
        before='    if receipt.get("packet_hash") != packet.get("packet_hash"):\n'
        '        raise ClosureError("review receipt is not bound to this packet")',
        after='    if False:\n'
        '        raise ClosureError("review receipt is not bound to this packet")',
        expected_failure_marker="test_receipt_must_bind_exact_packet",
        rationale="A review receipt cannot be replayed against a different candidate packet.",
    ),
    MutationCase(
        mutation_id="FUNNEL_CLOSURE_RECEIPT_AUTHORITY",
        component="Research funnel offline closure",
        source_path="experiments/research_funnel/closure_experiment.py",
        test_script="tests/test_research_closure_experiment.py",
        before='    if (\n'
        '        receipt.get("decision") != RECEIPT_DECISION\n'
        '        or receipt.get("claimed_reviewer") != "Junyan"\n'
        '        or receipt.get("identity_verification") != "UNAVAILABLE"\n'
        '        or receipt.get("production_authority") is not False\n'
        '        or receipt.get("receipt_class") != RECEIPT_CLASS\n'
        '    ):\n'
        '        raise ClosureError("review receipt authority boundary changed")',
        after='    if False:\n'
        '        raise ClosureError("review receipt authority boundary changed")',
        expected_failure_marker="test_receipt_cannot_claim_verified_identity_or_production_authority",
        rationale="A JSON receipt records supplied review text but cannot prove identity or grant production authority.",
    ),
    MutationCase(
        mutation_id="FUNNEL_CLOSURE_PACKET_REBUILD",
        component="Research funnel offline closure",
        source_path="experiments/research_funnel/closure_experiment.py",
        test_script="tests/test_research_closure_experiment.py",
        before='    if packet != expected_packet:\n'
        '        raise ClosureError("review packet is not the deterministic projection of replay inputs")',
        after='    if False:\n'
        '        raise ClosureError("review packet is not the deterministic projection of replay inputs")',
        expected_failure_marker="test_replay_rebuilds_packet_from_frozen_inputs",
        rationale="A self-consistent but rewritten packet must not replace the projection of frozen inputs.",
    ),
    MutationCase(
        mutation_id="FUNNEL_CLOSURE_REPLAY_CHRONOLOGY",
        component="Research funnel offline closure",
        source_path="experiments/research_funnel/closure_experiment.py",
        test_script="tests/test_research_closure_experiment.py",
        before='    if replay_at < reviewed_at:\n'
        '        raise ClosureError("replay generated_at cannot predate its review receipt")',
        after='    if False:\n'
        '        raise ClosureError("replay generated_at cannot predate its review receipt")',
        expected_failure_marker="test_replay_timestamp_cannot_predate_review_receipt",
        rationale="A U4 replay cannot appear to exist before the human review text it consumes.",
    ),
    MutationCase(
        mutation_id="FUNNEL_CLOSURE_REPORT_HASH",
        component="Research funnel offline closure",
        source_path="experiments/research_funnel/closure_experiment.py",
        test_script="tests/test_research_closure_experiment.py",
        before='    if report.get("report_hash") != funnel._hash(_without_hash(report, "report_hash")):\n'
        '        raise ClosureError("closure report hash mismatch")',
        after='    if False:\n'
        '        raise ClosureError("closure report hash mismatch")',
        expected_failure_marker="test_report_hash_must_cover_report",
        rationale="The closure verdict must remain byte-bound to the reviewed evidence chain.",
    ),
    MutationCase(
        mutation_id="FUNNEL_CLOSURE_REPORT_EVIDENCE",
        component="Research funnel offline closure",
        source_path="experiments/research_funnel/closure_experiment.py",
        test_script="tests/test_research_closure_experiment.py",
        before='    if (\n'
        '        refs.get("bundle_hash") != (packet.get("source_refs") or {}).get("bundle_hash")\n'
        '        or refs.get("packet_hash") != packet.get("packet_hash")\n'
        '        or refs.get("receipt_hash") != receipt.get("receipt_hash")\n'
        '        or refs.get("u4_rows_hash") != queue.get("rows_hash")\n'
        '        or discovery.get("control_batch_id") != packet_control.get("control_batch_id")\n'
        '        or discovery.get("algo") != packet_control.get("algo")\n'
        '        or discovery.get("seed_hex") != packet_control.get("seed_hex")\n'
        '        or discovery.get("drawn_hash") != packet_control.get("drawn_hash")\n'
        '        or u3.get("battery_hash") != (packet.get("source_refs") or {}).get("battery_hash")\n'
        '        or u3.get("selected_count") != len(queue.get("rows") or [])\n'
        '        or u4.get("selected_count") != len(queue.get("rows") or [])\n'
        '    ):\n'
        '        raise ClosureError("closure report evidence chain is broken")',
        after='    if False:\n'
        '        raise ClosureError("closure report evidence chain is broken")',
        expected_failure_marker="test_report_rejects_rewritten_control_evidence_even_with_new_hash",
        rationale="A freshly rehashed report cannot rewrite the packet-bound control or battery evidence.",
    ),
    MutationCase(
        mutation_id="FUNNEL_CLOSURE_NO_CLAIM_OR_AUTHORITY",
        component="Research funnel offline closure",
        source_path="experiments/research_funnel/closure_experiment.py",
        test_script="tests/test_research_closure_experiment.py",
        before='    if (\n'
        '        report.get("claim_allowed") is not False\n'
        '        or report.get("no_trade_flag") is not True\n'
        '        or report.get("status") != "PARTIAL"\n'
        '        or (report.get("u5_handoff") or {}).get("status") != "DATA_BLOCKED"\n'
        '        or (report.get("u4_review") or {}).get("production_authority") is not False\n'
        '        or funnel.FORBIDDEN_ACTION_KEYS.intersection(funnel._walk_keys(report))\n'
        '    ):\n'
        '        raise ClosureError("offline closure report acquired claim or trading authority")',
        after='    if False:\n'
        '        raise ClosureError("offline closure report acquired claim or trading authority")',
        expected_failure_marker="test_report_rejects_claim_or_trade_authority",
        rationale="An offline replay cannot unlock a claim, U5 handoff, or trading authority.",
    ),
    MutationCase(
        mutation_id="FUNNEL_CLOSURE_RESULT_BUNDLE_HASH",
        component="Research funnel offline closure",
        source_path="experiments/research_funnel/closure_experiment.py",
        test_script="tests/test_research_closure_experiment.py",
        before='    if manifest.get("bundle_hash") != funnel._hash(artifacts):\n'
        '        raise ClosureError("result bundle_hash mismatch")',
        after='    if False:\n'
        '        raise ClosureError("result bundle_hash mismatch")',
        expected_failure_marker="test_result_bundle_verifier_rejects_manifest_bundle_hash_mutation",
        rationale="An independently verified closure result must remain byte-bound to its artifact map.",
    ),
    MutationCase(
        mutation_id="FUNNEL_CLOSURE_RESULT_MANIFEST_FIELDS",
        component="Research funnel offline closure",
        source_path="experiments/research_funnel/closure_experiment.py",
        test_script="tests/test_research_closure_experiment.py",
        before='    if set(manifest) != RESULT_MANIFEST_FIELDS:\n'
        '        raise ClosureError("result bundle manifest fields are not exact")',
        after='    if False:\n'
        '        raise ClosureError("result bundle manifest fields are not exact")',
        expected_failure_marker="test_result_bundle_manifest_rejects_extra_authority_field",
        rationale="A result manifest cannot smuggle an undeclared authority or action field beside valid hashes.",
    ),
    MutationCase(
        mutation_id="FUNNEL_CLOSURE_RESULT_ARTIFACT_HASH",
        component="Research funnel offline closure",
        source_path="experiments/research_funnel/closure_experiment.py",
        test_script="tests/test_research_closure_experiment.py",
        before='        if not path.is_file() or path.is_symlink() or _sha256_path(path) != expected_hash:\n'
        '            raise ClosureError(f"result artifact hash mismatch: {name}")',
        after='        if False:\n'
        '            raise ClosureError(f"result artifact hash mismatch: {name}")',
        expected_failure_marker="test_result_bundle_verifier_rejects_artifact_mutation",
        rationale="A result artifact cannot change bytes while retaining the frozen manifest digest.",
    ),
    MutationCase(
        mutation_id="FUNNEL_CLOSURE_RESULT_DETERMINISTIC",
        component="Research funnel offline closure",
        source_path="experiments/research_funnel/closure_experiment.py",
        test_script="tests/test_research_closure_experiment.py",
        before='    if packet != expected_packet or queue != expected_queue or report != expected_report:\n'
        '        raise ClosureError("result bundle is not the deterministic projection of frozen evidence")',
        after='    if False:\n'
        '        raise ClosureError("result bundle is not the deterministic projection of frozen evidence")',
        expected_failure_marker="test_result_bundle_verifier_rebuilds_outputs_from_frozen_evidence",
        rationale="A self-consistently rehashed result must still reproduce from its frozen U1-U3 evidence.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_CASE_HASH",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if case.get("case_hash") != _hash(_without_hash(case, "case_hash")):\n'
        '        raise CycleError("research case hash mismatch")',
        after='    if False:\n'
        '        raise CycleError("research case hash mismatch")',
        expected_failure_marker="test_case_hash_must_cover_every_prospective_input",
        rationale="Every prospective research input must freeze before settled outcomes exist.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_NO_OVERWRITE",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if os.path.lexists(path):\n'
        '        raise CycleError(f"output already exists; refusing overwrite: {path}")',
        after='    if False:\n'
        '        raise CycleError(f"output already exists; refusing overwrite: {path}")',
        expected_failure_marker="test_cli_runs_the_entire_u4_to_reviewed_chain",
        rationale="A retry cannot overwrite a prospectively sealed case, bars file, or review receipt.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_FACTPACK_E1",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if "E1" not in tiers:\n'
        '        raise CycleError("factpack lacks load-bearing E1 evidence")',
        after='    if False:\n'
        '        raise CycleError("factpack lacks load-bearing E1 evidence")',
        expected_failure_marker="test_factpack_without_e1_is_rejected",
        rationale="A deep thesis cannot advance on inference alone.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_SOURCE_BINDING",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if refs != expected_refs:\n'
        '        raise CycleError("research case is not bound to the exact U4 evidence chain")',
        after='    if False:\n'
        '        raise CycleError("research case is not bound to the exact U4 evidence chain")',
        expected_failure_marker="test_case_must_bind_exact_u4_source",
        rationale="A case cannot swap the reviewed U4 selection or evidence bundle.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_THESIS_QUALIFICATION",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if errors:\n'
        '        raise CycleError(f"thesis core is not qualified: {errors[:3]}")',
        after='    if False:\n'
        '        raise CycleError(f"thesis core is not qualified: {errors[:3]}")',
        expected_failure_marker="test_unqualified_thesis_is_rejected",
        rationale="The orchestrator must reuse the qualified Core Thesis Factory contract.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_REDTEAM_BINDING",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if red_team_invalid:\n'
        '        raise CycleError("red-team PASS is not bound to the qualified thesis core")',
        after='    if False:\n'
        '        raise CycleError("red-team PASS is not bound to the qualified thesis core")',
        expected_failure_marker="test_red_team_must_bind_exact_core",
        rationale="A PASS for one thesis cannot authorize a rewritten thesis.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_DUAL_TICKET_LEVELS",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if levels_diverge:\n'
        '        raise CycleError("thesis, timing, and paper-plan levels are not identical")',
        after='    if False:\n'
        '        raise CycleError("thesis, timing, and paper-plan levels are not identical")',
        expected_failure_marker="test_dual_ticket_levels_cannot_diverge",
        rationale="The timing layer cannot silently rewrite the reviewed paper levels.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_TIMING_EVIDENCE",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if timing_evidence_invalid:\n'
        '        raise CycleError("a PASS timing ticket lacks settled market/sector/flow/structure/portfolio evidence")',
        after='    if False:\n'
        '        raise CycleError("a PASS timing ticket lacks settled market/sector/flow/structure/portfolio evidence")',
        expected_failure_marker="test_pass_timing_ticket_requires_all_five_evidence_gates",
        rationale="A PASS timing ticket must be backed by every settled execution gate.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_INDUSTRY_BINDING",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if registration["valuation"]["industry"] != case.get("industry_code"):\n'
        '        raise CycleError("registered valuation industry differs from the research case")',
        after='    if False:\n'
        '        raise CycleError("registered valuation industry differs from the research case")',
        expected_failure_marker="test_case_industry_must_match_registered_valuation_adapter",
        rationale="A research case cannot borrow a valuation adapter from a different industry method.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_RAW_SETTLED_BARS",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/paper_portfolio.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '    # governance-mutation: PAPER_EXECUTION_RAW_SETTLED_BARS\n'
            '    if bar.get("price_basis") != "RAW_UNADJUSTED" or bar.get("settled") is not True:'
        ),
        after=(
            '    # governance-mutation: PAPER_EXECUTION_RAW_SETTLED_BARS\n'
            '    if False:'
        ),
        expected_failure_marker="test_adjusted_or_unsettled_bar_is_rejected",
        rationale="Adjusted or unsettled bars cannot serve as executable-price evidence.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_DATE_SEQUENCE",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/paper_portfolio.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '        # governance-mutation: PAPER_EXECUTION_DATE_SEQUENCE\n'
            '        if dates != sorted(set(dates)):'
        ),
        after=(
            '        # governance-mutation: PAPER_EXECUTION_DATE_SEQUENCE\n'
            '        if False:'
        ),
        expected_failure_marker="test_realistic_bar_dates_must_be_ordered_unique_calendar_dates",
        rationale="Direct fill-engine callers cannot reorder or duplicate settlement sessions.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_CORPORATE_ACTION_FREEZE",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/paper_portfolio.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '    # governance-mutation: PAPER_EXECUTION_CORPORATE_ACTION_FREEZE\n'
            '    if detail is not None:'
        ),
        after=(
            '    # governance-mutation: PAPER_EXECUTION_CORPORATE_ACTION_FREEZE\n'
            '    if False:'
        ),
        expected_failure_marker="test_corporate_action_price_chain_break_freezes_without_false_exit",
        rationale="A raw-price discontinuity cannot apply stale nominal levels across a corporate action.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_FROZEN_STAYS_FROZEN",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/paper_portfolio.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '        # governance-mutation: PAPER_EXECUTION_FROZEN_STAYS_FROZEN\n'
            '        if entry.get("execution_frozen") is True:'
        ),
        after=(
            '        # governance-mutation: PAPER_EXECUTION_FROZEN_STAYS_FROZEN\n'
            '        if False:'
        ),
        expected_failure_marker="test_corporate_action_price_chain_break_freezes_without_false_exit",
        rationale="A frozen paper order cannot resume against stale nominal levels on a shorter replay window.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_FROZEN_NAV_BLOCK",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/model_paper_fund.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '    # governance-mutation: PAPER_EXECUTION_FROZEN_NAV_BLOCK\n'
            '    if frozen_positions:'
        ),
        after=(
            '    # governance-mutation: PAPER_EXECUTION_FROZEN_NAV_BLOCK\n'
            '    if False:'
        ),
        expected_failure_marker="test_corporate_action_price_chain_break_freezes_without_false_exit",
        rationale="A frozen filled position cannot emit a false NAV from stale shares and post-action prices.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_LIMIT_UP_NO_BUY",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/paper_portfolio.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '                # governance-mutation: PAPER_EXECUTION_LIMIT_UP_NO_BUY\n'
            '                if require_realistic and _one_price_at(b, "up_limit"):'
        ),
        after=(
            '                # governance-mutation: PAPER_EXECUTION_LIMIT_UP_NO_BUY\n'
            '                if False:'
        ),
        expected_failure_marker="test_one_price_limit_up_does_not_fill",
        rationale="A one-price limit-up bar cannot be treated as an available buy fill.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_LIQUIDITY_CAP",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/paper_portfolio.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '                # governance-mutation: PAPER_EXECUTION_LIQUIDITY_CAP\n'
            '                if require_realistic and not _participation_ok(entry, b):'
        ),
        after=(
            '                # governance-mutation: PAPER_EXECUTION_LIQUIDITY_CAP\n'
            '                if False:'
        ),
        expected_failure_marker="test_liquidity_participation_cap_blocks_fill",
        rationale="A paper order cannot consume more than the registered share of settled volume.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_NO_CHASE_LIMIT",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/paper_portfolio.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '                # governance-mutation: PAPER_EXECUTION_NO_CHASE_LIMIT\n'
            '                if require_realistic and (not _number(max_fill) or fill > float(max_fill)):'
        ),
        after=(
            '                # governance-mutation: PAPER_EXECUTION_NO_CHASE_LIMIT\n'
            '                if False:'
        ),
        expected_failure_marker="test_registered_no_chase_limit_blocks_large_gap",
        rationale="A gap above the prospectively registered entry zone cannot be chased after the fact.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_T1_SELL",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/paper_portfolio.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '        # governance-mutation: PAPER_EXECUTION_T1_SELL\n'
            '        for b in (x for x in eligible if x["date"] > entry["fill_date"]):'
        ),
        after=(
            '        # governance-mutation: PAPER_EXECUTION_T1_SELL\n'
            '        for b in (x for x in eligible if x["date"] >= entry["fill_date"]):'
        ),
        expected_failure_marker="test_fill_day_stop_and_target_cannot_sell_under_t1",
        rationale="A-share cash-equity fills cannot be sold on their purchase date.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_LIMIT_DOWN_NO_SELL",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/paper_portfolio.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '                # governance-mutation: PAPER_EXECUTION_LIMIT_DOWN_NO_SELL\n'
            '                if require_realistic and _one_price_at(b, "down_limit"):'
        ),
        after=(
            '                # governance-mutation: PAPER_EXECUTION_LIMIT_DOWN_NO_SELL\n'
            '                if False:'
        ),
        expected_failure_marker="test_one_price_limit_down_does_not_fake_stop_exit",
        rationale="A one-price limit-down bar cannot manufacture an available stop exit.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_COSTS_APPLIED",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/model_paper_fund.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '    # governance-mutation: PAPER_EXECUTION_COSTS_APPLIED\n'
            '    return round(commission + transfer + stamp, 2)'
        ),
        after=(
            '    # governance-mutation: PAPER_EXECUTION_COSTS_APPLIED\n'
            '    return 0.0'
        ),
        expected_failure_marker="test_costs_reduce_cash_and_net_pnl",
        rationale="Workflow-debug PnL must remain net of the declared conservative cost proxy.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_COST_SIDE_ENUM",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/model_paper_fund.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '    # governance-mutation: PAPER_EXECUTION_COST_SIDE_ENUM\n'
            '    if side not in ("buy", "sell"):'
        ),
        after=(
            '    # governance-mutation: PAPER_EXECUTION_COST_SIDE_ENUM\n'
            '    if False:'
        ),
        expected_failure_marker="test_transaction_cost_rejects_unknown_or_noncanonical_side",
        rationale="An unknown side cannot silently fall through to the cheaper buy-side fee path.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_COST_MODEL_FROZEN",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/model_paper_fund.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '    # governance-mutation: PAPER_EXECUTION_COST_MODEL_FROZEN\n'
            '    if model != WORKFLOW_DEBUG_COST_MODEL:'
        ),
        after=(
            '    # governance-mutation: PAPER_EXECUTION_COST_MODEL_FROZEN\n'
            '    if False:'
        ),
        expected_failure_marker="test_cost_model_cannot_be_silently_zeroed",
        rationale="A caller cannot zero a fee while retaining the approved cost-model label.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_DEBUG_NOT_CLAIM_SAMPLE",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/model_paper_fund.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '        # governance-mutation: PAPER_EXECUTION_DEBUG_NOT_CLAIM_SAMPLE\n'
            '        "sample_eligible": False if realistic else True,'
        ),
        after=(
            '        # governance-mutation: PAPER_EXECUTION_DEBUG_NOT_CLAIM_SAMPLE\n'
            '        "sample_eligible": True,'
        ),
        expected_failure_marker="test_workflow_debug_receipt_never_becomes_claim_sample",
        rationale="The first workflow-debug cycles cannot enter the 30-sample method claim set.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_RECEIPT_NO_CLAIM",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/model_paper_fund.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '        # governance-mutation: PAPER_EXECUTION_RECEIPT_NO_CLAIM\n'
            '        "method_claim_sample_eligible": False,'
        ),
        after=(
            '        # governance-mutation: PAPER_EXECUTION_RECEIPT_NO_CLAIM\n'
            '        "method_claim_sample_eligible": True,'
        ),
        expected_failure_marker="test_workflow_debug_receipt_never_becomes_claim_sample",
        rationale="A realism receipt must never promote workflow-debug fills into claim evidence.",
    ),
    MutationCase(
        mutation_id="PAPER_EXECUTION_CLAIM_COUNT_EXCLUDES_DEBUG",
        component="Research funnel paper execution realism",
        source_path="experiments/execution_tracker/model_paper_fund.py",
        test_script="tests/test_paper_execution_realism.py",
        before=(
            '    # governance-mutation: PAPER_EXECUTION_CLAIM_COUNT_EXCLUDES_DEBUG\n'
            '    closed = [o for o in closed_all if o.get("sample_eligible") is True]'
        ),
        after=(
            '    # governance-mutation: PAPER_EXECUTION_CLAIM_COUNT_EXCLUDES_DEBUG\n'
            '    closed = list(closed_all)'
        ),
        expected_failure_marker="test_thirty_workflow_debug_closures_do_not_unlock_claims",
        rationale="Thirty workflow-debug closures cannot masquerade as the independent claim set.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_NO_LOOKAHEAD_BARS",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if bars_invalid:\n'
        '        raise CycleError("settled bars are unordered, duplicated, or pre-registration")',
        after='    if False:\n'
        '        raise CycleError("settled bars are unordered, duplicated, or pre-registration")',
        expected_failure_marker="test_pre_registration_settled_bar_is_rejected",
        rationale="Outcome evidence must remain later than the prospectively sealed case.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_BARS_SETTLEMENT_TIME",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if bars_not_yet_settled:\n'
        '        raise CycleError("settled bars include a session not yet closed at bars.generated_at")',
        after='    if False:\n'
        '        raise CycleError("settled bars include a session not yet closed at bars.generated_at")',
        expected_failure_marker="test_bar_session_after_generated_at_is_rejected",
        rationale="A future or still-open session cannot be sealed as settled outcome evidence.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_SCORING_ASOF",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if outcomes["scoring_as_of"] != bars["rows"][-1]["date"]:\n'
        '        raise CycleError("method outcomes and settled bars do not share one scoring as_of")',
        after='    if False:\n'
        '        raise CycleError("method outcomes and settled bars do not share one scoring as_of")',
        expected_failure_marker="test_scoring_as_of_must_equal_last_settled_bar",
        rationale="Facts and price-path scoring must close on the same settled observation date.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_PAPER_ONLY_AUTHORITY",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if paper_boundary_broken:\n'
        '        raise CycleError("offline paper replay acquired authority or unlocked a claim")',
        after='    if False:\n'
        '        raise CycleError("offline paper replay acquired authority or unlocked a claim")',
        expected_failure_marker="test_replay_rejects_paper_engine_authority_drift",
        rationale="One replay cannot gain real-capital authority or unlock a performance claim.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_DETERMINISTIC_VERIFY",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if projection_changed:\n'
        '        raise CycleError("cycle bundle is not the deterministic projection of its evidence")',
        after='    if False:\n'
        '        raise CycleError("cycle bundle is not the deterministic projection of its evidence")',
        expected_failure_marker="test_cycle_verifier_rebuilds_outputs_after_self_consistent_rehash",
        rationale="Self-consistent rehashing cannot rewrite the mechanical outcome.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_MANIFEST_AUTHORITY",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if manifest_boundary_invalid:\n'
        '        raise CycleError("cycle bundle manifest is invalid")',
        after='    if False:\n'
        '        raise CycleError("cycle bundle manifest is invalid")',
        expected_failure_marker="test_cycle_manifest_cannot_rewrite_paper_authority",
        rationale="A cycle manifest cannot rewrite the paper-only boundary beside valid artifact hashes.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_FINAL_MANIFEST_AUTHORITY",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if final_manifest_boundary_invalid:\n'
        '        raise CycleError("reviewed-cycle manifest is invalid")',
        after='    if False:\n'
        '        raise CycleError("reviewed-cycle manifest is invalid")',
        expected_failure_marker="test_final_manifest_cannot_rewrite_paper_authority",
        rationale="A reviewed bundle manifest cannot erase its no-trade boundary.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_POSTMORTEM_BINDING",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if receipt_unbound:\n'
        '        raise CycleError("postmortem receipt is not bound to the mechanical outcome")',
        after='    if False:\n'
        '        raise CycleError("postmortem receipt is not bound to the mechanical outcome")',
        expected_failure_marker="test_postmortem_receipt_must_bind_outcome_hash",
        rationale="Human attribution must occur after and bind the exact mechanical result.",
    ),
    MutationCase(
        mutation_id="RESEARCH_CYCLE_POSTMORTEM_OUTCOME_REQUIRED",
        component="Research funnel full paper cycle",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if outcome_incomplete:\n'
        '        raise CycleError("postmortem refused because the paper outcome is incomplete")',
        after='    if False:\n'
        '        raise CycleError("postmortem refused because the paper outcome is incomplete")',
        expected_failure_marker="test_postmortem_requires_closed_or_no_trade_outcome",
        rationale="Attribution requires a closed or explicitly no-trade mechanical outcome.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_WRONG_IF_COVERAGE",
        component="Research funnel method registration",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before='    if observed_hashes != required_hashes:\n'
        '        raise MethodError("structured invalidation claims do not exactly cover thesis wrong-if triggers")',
        after='    if False:\n'
        '        raise MethodError("structured invalidation claims do not exactly cover thesis wrong-if triggers")',
        expected_failure_marker="test_wrong_if_coverage_is_exact_not_a_count",
        rationale="Each mechanized thesis invalidation must be individually represented in the registered scoreable claims.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_WRONG_IF_ONE_TO_ONE",
        component="Research funnel method registration",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before='    if duplicate_trigger_mapping:\n'
        '        raise MethodError("each thesis wrong-if trigger must map to exactly one invalidation claim")',
        after='    if False:\n'
        '        raise MethodError("each thesis wrong-if trigger must map to exactly one invalidation claim")',
        expected_failure_marker="test_wrong_if_trigger_maps_to_only_one_invalidation_claim",
        rationale="Conflicting duplicate invalidation claims cannot share one registered wrong-if trigger.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_VALUATION_DERIVATION",
        component="Research funnel method valuation",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before='    if output.get("calculation_status") != "MANUAL_UNVALIDATED" or declared != computed:\n'
        '        raise MethodError("valuation output is not derived from its adapter inputs")',
        after='    if False:\n'
        '        raise MethodError("valuation output is not derived from its adapter inputs")',
        expected_failure_marker="test_semiconductor_valuation_must_be_derived_from_inputs",
        rationale="An industry valuation label cannot legitimize an output that was not calculated from its frozen inputs.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_VALUATION_FORECAST_COVERAGE",
        component="Research funnel method valuation",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before='    if not required_metrics.issubset(metrics):\n'
        '        raise MethodError("valuation forecasts omit a load-bearing adapter input")',
        after='    if False:\n'
        '        raise MethodError("valuation forecasts omit a load-bearing adapter input")',
        expected_failure_marker="test_valuation_forecasts_cover_the_load_bearing_adapter_input",
        rationale="An industry adapter must register a later fact capable of testing its load-bearing modeled input.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_SMC_STOP_DERIVATION",
        component="Research funnel method manual SMC",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before='    if abs(stop - expected_stop) > 1e-8:\n'
        '        raise MethodError("SMC structure_stop is not derived from invalidation - ATR buffer")',
        after='    if False:\n'
        '        raise MethodError("SMC structure_stop is not derived from invalidation - ATR buffer")',
        expected_failure_marker="test_smc_stop_is_derived_and_dual_ticket_levels_cannot_drift",
        rationale="A paper stop must be derived from the registered structure invalidation and ATR buffer.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_SMC_PASS_EVIDENCE",
        component="Research funnel method manual SMC",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before='    if status == "PASS" and not pass_evidence:\n'
        '        raise MethodError("SMC PASS lacks structure, discount, volume, flow, or sector evidence")',
        after='    if False:\n'
        '        raise MethodError("SMC PASS lacks structure, discount, volume, flow, or sector evidence")',
        expected_failure_marker="test_smc_pass_requires_all_manual_confirmation_evidence",
        rationale="Manual SMC cannot report PASS while any required settled confirmation is missing.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_SMC_POI_BINDING",
        component="Research funnel method manual SMC",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before='    if entry_high < poi_low or poi_high < entry_low:\n'
        '        raise MethodError("SMC entry zone does not overlap the registered point of interest")',
        after='    if False:\n'
        '        raise MethodError("SMC entry zone does not overlap the registered point of interest")',
        expected_failure_marker="test_smc_entry_zone_must_overlap_registered_point_of_interest",
        rationale="A manual SMC entry cannot cite a point of interest located somewhere else on the chart.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_SMC_TIMING_BINDING",
        component="Research funnel method manual SMC",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before='    if not timing_evidence:\n'
        '        raise MethodError("SMC confirmations and timing ticket evidence disagree")',
        after='    if False:\n'
        '        raise MethodError("SMC confirmations and timing ticket evidence disagree")',
        expected_failure_marker="test_smc_and_timing_ticket_must_share_settled_confirmation_evidence",
        rationale="The timing ticket cannot contradict the settled flow, sector, or structure evidence registered by SMC.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_SMC_LEVEL_BINDING",
        component="Research funnel method manual SMC",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before='    if levels != expected_levels or pack_levels != expected_levels:\n'
        '        raise MethodError("timing ticket and paper plan are not derived from SMC/valuation references")',
        after='    if False:\n'
        '        raise MethodError("timing ticket and paper plan are not derived from SMC/valuation references")',
        expected_failure_marker="test_smc_levels_must_bind_both_timing_ticket_and_decision_pack",
        rationale="Timing and paper-order layers cannot silently rewrite registered SMC and valuation levels.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_REGISTRATION_HASH",
        component="Research funnel method registration",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before='    if registration.get("registration_hash") != _hash(_without(registration, "registration_hash")):\n'
        '        raise MethodError("method registration hash mismatch")',
        after='    if False:\n'
        '        raise MethodError("method registration hash mismatch")',
        expected_failure_marker="test_registration_hash_covers_every_method_input",
        rationale="A registered method must freeze every thesis, valuation, and timing input before outcomes exist.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_OUTCOME_HASH",
        component="Research funnel method outcomes",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before='    if outcomes.get("outcome_hash") != _hash(_without(outcomes, "outcome_hash")):\n'
        '        raise MethodError("method outcomes hash mismatch")',
        after='    if False:\n'
        '        raise MethodError("method outcomes hash mismatch")',
        expected_failure_marker="test_outcome_hash_covers_every_later_fact",
        rationale="Later facts cannot be rewritten after the scoring artifact is sealed.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_OUTCOME_REGISTERED_DATE",
        component="Research funnel method outcomes",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before=('    # governance-mutation: RESEARCH_METHOD_OUTCOME_REGISTERED_DATE\n'
                '    registered_at = _date8(registration.get("registered_at"), "registration.registered_at")'),
        after=('    # governance-mutation: RESEARCH_METHOD_OUTCOME_REGISTERED_DATE\n'
               '    registered_at = str(registration.get("registered_at"))'),
        expected_failure_marker="test_outcome_chronology_normalizes_registered_date",
        rationale="Accepted registration date spellings must be normalized before every point-in-time comparison.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_SCORING_DATE_NORMALIZATION",
        component="Research funnel method scorecard",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before=('    # governance-mutation: RESEARCH_METHOD_SCORING_DATE_NORMALIZATION\n'
                '    scoring_as_of = _date8(outcomes["scoring_as_of"], "outcomes.scoring_as_of")'),
        after=('    # governance-mutation: RESEARCH_METHOD_SCORING_DATE_NORMALIZATION\n'
               '    scoring_as_of = str(outcomes["scoring_as_of"])'),
        expected_failure_marker="test_scorecard_normalizes_scoring_date_before_due_fact_classification",
        rationale="Due missing facts must remain DATA_BLOCKED for every accepted scoring date spelling.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_FACT_BINDING",
        component="Research funnel method outcomes",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before=('        if (\n'
                '            item.get("measurement_period") != expected.get("measurement_period")\n'
                '            or item.get("source_ref") != expected.get("source_ref")\n'
                '            or item.get("verification_status") != "MANUAL_EVIDENCE_BOUND_UNVERIFIED_IDENTITY"\n'
                '        ):\n'
                '            raise MethodError(f"fact {claim_id} is not bound to its registered period/source")'),
        after=('        if False:\n'
               '            raise MethodError(f"fact {claim_id} is not bound to its registered period/source")'),
        expected_failure_marker="test_outcomes_bind_each_fact_to_registered_period_and_source",
        rationale="A later number cannot score a different reporting period or source than the prospectively registered claim.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_ATTRIBUTION_RULE",
        component="Research funnel method attribution",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before='        return f"THESIS_{thesis}_TIMING_{timing}"',
        after='        return "UNRESOLVED"',
        expected_failure_marker="test_machine_attribution_separates_thesis_timing_and_pnl",
        rationale="Machine attribution must preserve the thesis/timing quadrant and remain independent of profit or loss.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_SCORECARD_CHRONOLOGY",
        component="Research funnel method attribution",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before=('    if _iso(scorecard.get("generated_at"), "scorecard.generated_at") < _iso(\n'
                '        outcomes.get("generated_at"), "outcomes.generated_at"\n'
                '    ):\n'
                '        raise MethodError("method scorecard predates its outcomes")'),
        after=('    if False:\n'
               '        raise MethodError("method scorecard predates its outcomes")'),
        expected_failure_marker="test_scorecard_cannot_predate_outcome_evidence",
        rationale="A scorecard cannot exist before the later facts it claims to score.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_ATTRIBUTION_DERIVATION",
        component="Research funnel method attribution",
        source_path="experiments/research_funnel/research_method.py",
        test_script="tests/test_research_method.py",
        before='    if scorecard.get("machine_attribution") != expected:\n'
        '        raise MethodError("machine attribution is not derived from thesis and timing ledgers")',
        after='    if False:\n'
        '        raise MethodError("machine attribution is not derived from thesis and timing ledgers")',
        expected_failure_marker="test_scorecard_tampering_and_authority_injection_are_rejected",
        rationale="A self-consistently rehashed scorecard cannot rewrite the machine attribution label.",
    ),
    MutationCase(
        mutation_id="RESEARCH_METHOD_HUMAN_REVIEW_EVIDENCE",
        component="Research funnel method human review",
        source_path="experiments/research_funnel/research_cycle.py",
        test_script="tests/test_research_cycle.py",
        before='    if dispute_invalid:\n'
        '        raise CycleError("human attribution confirmation/dispute lacks bound evidence semantics")',
        after='    if False:\n'
        '        raise CycleError("human attribution confirmation/dispute lacks bound evidence semantics")',
        expected_failure_marker="test_human_dispute_requires_evidence_and_preserves_machine_result",
        rationale="Junyan may supersede machine attribution, but the disagreement must remain explicit and evidence-bound.",
    ),
    MutationCase(
        mutation_id="FIVE_AXIS_BETA_BENCHMARK_BINDING",
        component="Five-axis paper attribution",
        source_path="experiments/research_funnel/five_axis_attribution.py",
        test_script="tests/test_five_axis_attribution.py",
        before=(
            '    # governance-mutation: FIVE_AXIS_BETA_BENCHMARK_BINDING\n'
            '    if beta.get("benchmark_id") != market_id:\n'
            '        raise AttributionError("beta estimate market benchmark differs")'
        ),
        after=(
            '    # governance-mutation: FIVE_AXIS_BETA_BENCHMARK_BINDING\n'
            '    if False:\n'
            '        raise AttributionError("beta estimate market benchmark differs")'
        ),
        expected_failure_marker="test_beta_samples_are_bound_to_the_market_benchmark",
        rationale="A beta estimate for another market benchmark cannot be reused for this cycle.",
    ),
    MutationCase(
        mutation_id="FIVE_AXIS_BETA_ASSET_BINDING",
        component="Five-axis paper attribution",
        source_path="experiments/research_funnel/five_axis_attribution.py",
        test_script="tests/test_five_axis_attribution.py",
        before=(
            '    # governance-mutation: FIVE_AXIS_BETA_ASSET_BINDING\n'
            '    if beta.get("asset_id") != registration.get("ticker"):\n'
            '        raise AttributionError("beta estimate asset differs from cycle ticker")'
        ),
        after=(
            '    # governance-mutation: FIVE_AXIS_BETA_ASSET_BINDING\n'
            '    if False:\n'
            '        raise AttributionError("beta estimate asset differs from cycle ticker")'
        ),
        expected_failure_marker="test_beta_samples_are_bound_to_the_cycle_ticker",
        rationale="A beta estimate for another security cannot be reused for this paper cycle.",
    ),
    MutationCase(
        mutation_id="FIVE_AXIS_BETA_POINT_IN_TIME",
        component="Five-axis paper attribution",
        source_path="experiments/research_funnel/five_axis_attribution.py",
        test_script="tests/test_five_axis_attribution.py",
        before=(
            '    # governance-mutation: FIVE_AXIS_BETA_POINT_IN_TIME\n'
            '    if not start < end <= registered <= method_as_of <= method_registered:\n'
            '        raise AttributionError("beta estimate is not point-in-time registered evidence")'
        ),
        after=(
            '    # governance-mutation: FIVE_AXIS_BETA_POINT_IN_TIME\n'
            '    if False:\n'
            '        raise AttributionError("beta estimate is not point-in-time registered evidence")'
        ),
        expected_failure_marker="test_beta_estimate_must_be_point_in_time",
        rationale="A paper-cycle beta must be frozen before the method registration and cannot consume later returns.",
    ),
    MutationCase(
        mutation_id="FIVE_AXIS_BETA_RECOMPUTATION",
        component="Five-axis paper attribution",
        source_path="experiments/research_funnel/five_axis_attribution.py",
        test_script="tests/test_five_axis_attribution.py",
        before=(
            '    # governance-mutation: FIVE_AXIS_BETA_RECOMPUTATION\n'
            '    if not math.isclose(value_number, computed, rel_tol=0.0, abs_tol=1e-10):\n'
            '        raise AttributionError("beta estimate is not derived from frozen return samples")'
        ),
        after=(
            '    # governance-mutation: FIVE_AXIS_BETA_RECOMPUTATION\n'
            '    if False:\n'
            '        raise AttributionError("beta estimate is not derived from frozen return samples")'
        ),
        expected_failure_marker="test_beta_is_recomputed_from_frozen_return_samples",
        rationale="The declared beta must be recomputed from the frozen point-in-time return sample instead of trusted as a label.",
    ),
    MutationCase(
        mutation_id="FIVE_AXIS_MARKET_SOURCE_BINDING",
        component="Five-axis paper attribution",
        source_path="experiments/research_funnel/five_axis_attribution.py",
        test_script="tests/test_five_axis_attribution.py",
        before=(
            '    # governance-mutation: FIVE_AXIS_MARKET_SOURCE_BINDING\n'
            '    if any(market.get(key) != value for key, value in expected.items()):\n'
            '        raise AttributionError("market evidence is not bound to the exact cycle and order")'
        ),
        after=(
            '    # governance-mutation: FIVE_AXIS_MARKET_SOURCE_BINDING\n'
            '    if False:\n'
            '        raise AttributionError("market evidence is not bound to the exact cycle and order")'
        ),
        expected_failure_marker="test_market_evidence_is_bound_to_exact_cycle_and_order",
        rationale="Market evidence from another cycle or order cannot be reused for this attribution.",
    ),
    MutationCase(
        mutation_id="FIVE_AXIS_EXECUTION_ORDER_BINDING",
        component="Five-axis paper attribution",
        source_path="experiments/research_funnel/five_axis_attribution.py",
        test_script="tests/test_five_axis_attribution.py",
        before=(
            '    # governance-mutation: FIVE_AXIS_EXECUTION_ORDER_BINDING\n'
            '    if any(receipt.get(key) != value for key, value in expected.items()):\n'
            '        raise AttributionError("execution evidence is not bound to the exact cycle and order")'
        ),
        after=(
            '    # governance-mutation: FIVE_AXIS_EXECUTION_ORDER_BINDING\n'
            '    if False:\n'
            '        raise AttributionError("execution evidence is not bound to the exact cycle and order")'
        ),
        expected_failure_marker="test_execution_evidence_is_bound_to_exact_order",
        rationale="An execution audit cannot be borrowed from a different paper order.",
    ),
    MutationCase(
        mutation_id="FIVE_AXIS_EXECUTION_SOURCE_RECEIPT",
        component="Five-axis paper attribution",
        source_path="experiments/research_funnel/five_axis_attribution.py",
        test_script="tests/test_five_axis_attribution.py",
        before=(
            '        # governance-mutation: FIVE_AXIS_EXECUTION_SOURCE_RECEIPT\n'
            '        raise AttributionError("execution wrapper is not bound to its full source receipt")'
        ),
        after=(
            '        # governance-mutation: FIVE_AXIS_EXECUTION_SOURCE_RECEIPT\n'
            '        pass'
        ),
        expected_failure_marker="test_execution_wrapper_freezes_the_full_source_receipt",
        rationale="The wrapper must freeze the complete execution-realism receipt instead of accepting copied pass labels.",
    ),
    MutationCase(
        mutation_id="FIVE_AXIS_EXECUTION_DEBUG_BOUNDARY",
        component="Five-axis paper attribution",
        source_path="experiments/research_funnel/five_axis_attribution.py",
        test_script="tests/test_five_axis_attribution.py",
        before=(
            '    # governance-mutation: FIVE_AXIS_EXECUTION_DEBUG_BOUNDARY\n'
            '    if status == "PASS_WORKFLOW_DEBUG" and not all(checks.values()):\n'
            '        raise AttributionError("PASS_WORKFLOW_DEBUG execution evidence has failed checks")'
        ),
        after=(
            '    # governance-mutation: FIVE_AXIS_EXECUTION_DEBUG_BOUNDARY\n'
            '    if False:\n'
            '        raise AttributionError("PASS_WORKFLOW_DEBUG execution evidence has failed checks")'
        ),
        expected_failure_marker="test_execution_pass_requires_every_realism_check",
        rationale="A workflow-debug execution pass cannot contain a failed realism check.",
    ),
    MutationCase(
        mutation_id="FIVE_AXIS_MISSING_EXECUTION_VISIBLE",
        component="Five-axis paper attribution",
        source_path="experiments/research_funnel/five_axis_attribution.py",
        test_script="tests/test_five_axis_attribution.py",
        before=(
            '        # governance-mutation: FIVE_AXIS_MISSING_EXECUTION_VISIBLE\n'
            '        status = "DATA_BLOCKED"'
        ),
        after=(
            '        # governance-mutation: FIVE_AXIS_MISSING_EXECUTION_VISIBLE\n'
            '        status = "WORKFLOW_DEBUG_ONLY"'
        ),
        expected_failure_marker="test_missing_evidence_stays_visible_and_does_not_block_other_axes",
        rationale="Missing execution-realism evidence must remain visible instead of becoming a debug pass.",
    ),
    MutationCase(
        mutation_id="FIVE_AXIS_EXECUTION_WORKFLOW_ONLY",
        component="Five-axis paper attribution",
        source_path="experiments/research_funnel/five_axis_attribution.py",
        test_script="tests/test_five_axis_attribution.py",
        before=(
            '        # governance-mutation: FIVE_AXIS_EXECUTION_WORKFLOW_ONLY\n'
            '        status = "WORKFLOW_DEBUG_ONLY"'
        ),
        after=(
            '        # governance-mutation: FIVE_AXIS_EXECUTION_WORKFLOW_ONLY\n'
            '        status = "COMPLIANT"'
        ),
        expected_failure_marker="test_workflow_debug_execution_never_becomes_method_sample",
        rationale="A realism receipt in the first debug cycles cannot be relabeled as validated execution skill.",
    ),
    MutationCase(
        mutation_id="FIVE_AXIS_MISSING_MARKET_VISIBLE",
        component="Five-axis paper attribution",
        source_path="experiments/research_funnel/five_axis_attribution.py",
        test_script="tests/test_five_axis_attribution.py",
        before=(
            '            # governance-mutation: FIVE_AXIS_MISSING_MARKET_VISIBLE\n'
            '            "status": "DATA_BLOCKED",'
        ),
        after=(
            '            # governance-mutation: FIVE_AXIS_MISSING_MARKET_VISIBLE\n'
            '            "status": "ATTRIBUTED_DIAGNOSTIC",'
        ),
        expected_failure_marker="test_missing_evidence_stays_visible_and_does_not_block_other_axes",
        rationale="Missing market evidence cannot silently become a beta attribution.",
    ),
    MutationCase(
        mutation_id="FIVE_AXIS_MARKET_BETA_DERIVATION",
        component="Five-axis paper attribution",
        source_path="experiments/research_funnel/five_axis_attribution.py",
        test_script="tests/test_five_axis_attribution.py",
        before=(
            '            # governance-mutation: FIVE_AXIS_MARKET_BETA_DERIVATION\n'
            '            values = {'
        ),
        after=(
            '            # governance-mutation: FIVE_AXIS_MARKET_BETA_DERIVATION\n'
            '            contribution = 0.0\n'
            '            values = {'
        ),
        expected_failure_marker="test_market_beta_is_derived_and_never_called_alpha",
        rationale="Market-beta contribution and residual must be derived from the registered beta and same-window market return.",
    ),
    MutationCase(
        mutation_id="FIVE_AXIS_DERIVED_NO_CLAIM",
        component="Five-axis paper attribution",
        source_path="experiments/research_funnel/five_axis_attribution.py",
        test_script="tests/test_five_axis_attribution.py",
        before=(
            '        # governance-mutation: FIVE_AXIS_DERIVED_NO_CLAIM\n'
            '        "method_sample_eligible": False,'
        ),
        after=(
            '        # governance-mutation: FIVE_AXIS_DERIVED_NO_CLAIM\n'
            '        "method_sample_eligible": True,'
        ),
        expected_failure_marker="test_derived_receipt_hardcodes_the_no_claim_boundary",
        rationale="Workflow-debug attribution must remain excluded from the 30-sample method gate by construction.",
    ),
    MutationCase(
        mutation_id="FIVE_AXIS_DETERMINISTIC_PROJECTION",
        component="Five-axis paper attribution",
        source_path="experiments/research_funnel/five_axis_attribution.py",
        test_script="tests/test_five_axis_attribution.py",
        before=(
            '    # governance-mutation: FIVE_AXIS_DETERMINISTIC_PROJECTION\n'
            '    if dict(receipt) != expected:\n'
            '        raise AttributionError("five-axis attribution is not the deterministic evidence projection")'
        ),
        after=(
            '    # governance-mutation: FIVE_AXIS_DETERMINISTIC_PROJECTION\n'
            '    if False:\n'
            '        raise AttributionError("five-axis attribution is not the deterministic evidence projection")'
        ),
        expected_failure_marker="test_receipt_is_a_deterministic_projection",
        rationale="A self-rehashed receipt cannot rewrite any axis away from its verified sources.",
    ),
    MutationCase(
        mutation_id="GOVERNANCE_FUNNEL_MARKER_COVERAGE_CALL",
        component="Governance mutation gate",
        source_path="scripts/governance_mutation_gate.py",
        test_script="tests/test_governance_mutation_gate.py",
        before=("    validate_funnel_" "marker_coverage(root, cases)"),
        after=(
            "    if False:\n"
            "        validate_funnel_"
            "marker_coverage(root, cases)"
        ),
        expected_failure_marker="test_validate_manifest_enforces_funnel_marker_coverage",
        rationale="The mutation manifest must not silently stop enforcing funnel marker coverage.",
    ),
    # R-035 keeps discovery-vs-control and battery-separation scoring distinct.
    # These mutations pin the outcome-blind input, preregistered return basis,
    # descriptive statistics, and the permanently blocked claim boundary.
    MutationCase(
        mutation_id="R035_CANDIDATE_OUTCOME_BLIND",
        component="Research funnel R-035 evaluation",
        source_path="experiments/research_funnel/r035_evaluation.py",
        test_script="tests/test_research_funnel_r035.py",
        before='    if any(row.get("aligned_return") is not None for row in candidates["rows"]):\n'
        '        raise EvaluationError("candidate bundle already contains outcome data")',
        after='    if False:\n'
        '        raise EvaluationError("candidate bundle already contains outcome data")',
        expected_failure_marker="test_candidate_bundle_must_remain_outcome_blind",
        rationale="U2 candidates must not receive outcome data before R-035 evaluates them.",
    ),
    MutationCase(
        mutation_id="R035_BUNDLE_HASH_BINDING",
        component="Research funnel R-035 evaluation",
        source_path="experiments/research_funnel/r035_evaluation.py",
        test_script="tests/test_research_funnel_r035.py",
        before='    if declared != measured or manifest.get("bundle_hash") != _hash(declared):\n'
        '        raise EvaluationError("funnel bundle manifest or artifact hash drift")',
        after='    if False:\n'
        '        raise EvaluationError("funnel bundle manifest or artifact hash drift")',
        expected_failure_marker="test_bundle_artifact_hash_drift_is_rejected",
        rationale="Standalone R-035 evaluation must independently bind every immutable bundle artifact.",
    ),
    MutationCase(
        mutation_id="R035_CONTROL_FRAME_BINDING",
        component="Research funnel R-035 evaluation",
        source_path="experiments/research_funnel/r035_evaluation.py",
        test_script="tests/test_research_funnel_r035.py",
        before='    if batch_id != f"CTRL_{as_of}_v1":\n'
        '        raise EvaluationError("control batch is not bound to the candidate as_of")',
        after='    if False:\n'
        '        raise EvaluationError("control batch is not bound to the candidate as_of")',
        expected_failure_marker="test_control_frame_must_be_bound_to_candidate_asof",
        rationale="Random controls must remain bound to the same registered U2 batch.",
    ),
    MutationCase(
        mutation_id="R035_COMMON_T0_REQUIRED",
        component="Research funnel R-035 evaluation",
        source_path="experiments/research_funnel/r035_evaluation.py",
        test_script="tests/test_research_funnel_r035.py",
        before='            if not by_code[code] or by_code[code][0]["trade_date"] != as_of:\n'
        '                # governance-mutation: R035_COMMON_T0_REQUIRED\n'
        '                raise EvaluationError(f"candidate lacks the common U2 t0 close: {code}")',
        after='            if not by_code[code]:\n'
        '                # governance-mutation: R035_COMMON_T0_REQUIRED\n'
        '                raise EvaluationError(f"candidate lacks the common U2 t0 close: {code}")',
        expected_failure_marker="test_missing_common_t0_fails_closed",
        rationale="Every scored security must use the same U2 as-of settled close.",
    ),
    MutationCase(
        mutation_id="R035_ATOMIC_SOURCE_BATCH",
        component="Research funnel R-035 evaluation",
        source_path="experiments/research_funnel/r035_evaluation.py",
        test_script="tests/test_research_funnel_r035.py",
        before='        if partial_dates:\n'
        '            raise EvaluationError(f"feature store contains partial source batches: {partial_dates}")',
        after='        if False:\n'
        '            raise EvaluationError(f"feature store contains partial source batches: {partial_dates}")',
        expected_failure_marker="test_partial_feature_store_batch_fails_closed",
        rationale="R-035 may score only dates committed atomically across every R-008 source endpoint.",
    ),
    MutationCase(
        mutation_id="R035_COMMITTED_PRICE_DATES",
        component="Research funnel R-035 evaluation",
        source_path="experiments/research_funnel/r035_evaluation.py",
        test_script="tests/test_research_funnel_r035.py",
        before='            if row["trade_date"] not in endpoints_by_date:\n'
        '                raise EvaluationError(\n'
        '                    f"price evidence is not backed by an atomic source batch: {row[\'trade_date\']}"\n'
        '                )',
        after='            if False:\n'
        '                raise EvaluationError(\n'
        '                    f"price evidence is not backed by an atomic source batch: {row[\'trade_date\']}"\n'
        '                )',
        expected_failure_marker="test_price_rows_without_a_committed_source_batch_are_rejected",
        rationale="Aligned returns may use only price rows backed by a committed R-008 source date.",
    ),
    MutationCase(
        mutation_id="R035_ALIGNED_HORIZON",
        component="Research funnel R-035 evaluation",
        source_path="experiments/research_funnel/r035_evaluation.py",
        test_script="tests/test_research_funnel_r035.py",
        before='                value = observed["adjusted_close"] / t0["adjusted_close"] - 1.0',
        after='                value = 0.0',
        expected_failure_marker="test_aligned_returns_use_one_t0_and_all_preregistered_horizons",
        rationale="Aligned returns must be calculated from the common t0, never fabricated as zero.",
    ),
    MutationCase(
        mutation_id="R035_TWO_LAYER_SEPARATION",
        component="Research funnel R-035 evaluation",
        source_path="experiments/research_funnel/r035_evaluation.py",
        test_script="tests/test_research_funnel_r035.py",
        before='        "u3_battery_separation": _test_result(\n'
        '            rows, field="u3_group", groups=U3_GROUPS\n'
        '        ),',
        after='        "u3_battery_separation": _test_result(\n'
        '            rows, field="u1_u2_group", groups=U12_GROUPS\n'
        '        ),',
        expected_failure_marker="test_u12_and_u3_statistics_are_separate_and_batch_bound",
        rationale="U1/U2 discovery and U3 battery separation are different tests and cannot be blended.",
    ),
    MutationCase(
        mutation_id="R035_NO_TRADE_AUTHORITY",
        component="Research funnel R-035 evaluation",
        source_path="experiments/research_funnel/r035_evaluation.py",
        test_script="tests/test_research_funnel_r035.py",
        before='    if offending:\n'
        '        raise EvaluationError(f"R-035 receipt contains trade authority: {sorted(offending)}")',
        after='    if False:\n'
        '        raise EvaluationError(f"R-035 receipt contains trade authority: {sorted(offending)}")',
        expected_failure_marker="test_trade_or_blocking_authority_is_rejected",
        rationale="R-035 is a research evaluator and can never emit trade or blocking authority.",
    ),
    MutationCase(
        mutation_id="R035_POLICY_FROZEN",
        component="Research funnel R-035 evaluation",
        source_path="experiments/research_funnel/r035_evaluation.py",
        test_script="tests/test_research_funnel_r035.py",
        before='    if (\n'
        '        policy.get("entry_basis") != "U2_AS_OF_SETTLED_CLOSE"',
        after='    if False and (\n'
        '        policy.get("entry_basis") != "U2_AS_OF_SETTLED_CLOSE"',
        expected_failure_marker="test_preregistered_policy_and_top_level_status_are_recomputed",
        rationale="The registered entry basis, horizons, price basis, and test method cannot drift.",
    ),
    MutationCase(
        mutation_id="R035_LAYER_ROW_SEPARATION",
        component="Research funnel R-035 evaluation",
        source_path="experiments/research_funnel/r035_evaluation.py",
        test_script="tests/test_research_funnel_r035.py",
        before='        if row.get("u1_u2_group") == "RANDOM_CONTROL" and (\n'
        '            row.get("u3_group") is not None or row.get("u3_group_reason") is not None\n'
        '        ):\n'
        '            raise EvaluationError("R-035 random controls cannot enter the U3 test")',
        after='        if False:\n'
        '            raise EvaluationError("R-035 random controls cannot enter the U3 test")',
        expected_failure_marker="test_random_controls_cannot_enter_the_u3_test",
        rationale="Random controls cannot be recycled into the battery-separation test.",
    ),
    MutationCase(
        mutation_id="R035_STATISTICS_RECOMPUTED",
        component="Research funnel R-035 evaluation",
        source_path="experiments/research_funnel/r035_evaluation.py",
        test_script="tests/test_research_funnel_r035.py",
        before='    if payload.get("tests") != _tests_from_rows(rows):\n'
        '        raise EvaluationError("R-035 test statistics do not match scored rows")',
        after='    if False:\n'
        '        raise EvaluationError("R-035 test statistics do not match scored rows")',
        expected_failure_marker="test_statistics_are_recomputed_from_rows",
        rationale="Published descriptive statistics must be recomputed from the scored rows.",
    ),
    MutationCase(
        mutation_id="R035_STATUS_RECOMPUTED",
        component="Research funnel R-035 evaluation",
        source_path="experiments/research_funnel/r035_evaluation.py",
        test_script="tests/test_research_funnel_r035.py",
        before='    if payload.get("status") != expected_status:\n'
        '        raise EvaluationError("R-035 top-level status does not match observed coverage")',
        after='    if False:\n'
        '        raise EvaluationError("R-035 top-level status does not match observed coverage")',
        expected_failure_marker="test_preregistered_policy_and_top_level_status_are_recomputed",
        rationale="Missing outcomes or open windows must remain visible as PARTIAL.",
    ),
    MutationCase(
        mutation_id="R035_CLAIM_BLOCKED",
        component="Research funnel R-035 evaluation",
        source_path="experiments/research_funnel/r035_evaluation.py",
        test_script="tests/test_research_funnel_r035.py",
        before='    if (\n'
        '        claim.get("status") != "BLOCKED"',
        after='    if False and (\n'
        '        claim.get("status") != "BLOCKED"',
        expected_failure_marker="test_claim_cannot_be_unlocked_by_sample_count",
        rationale="R-035 sample counts cannot unlock a claim before prospective causal-cluster governance.",
    ),
    # ── 研究漏斗夜链接入(观察期隔离)──
    # 守的是**接入方式**,不是漏斗自己的研究契约:隔离、销毁、不进发布树。
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_ISOLATION",
        component="Nightly funnel wiring isolation",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            '        if name in ISOLATED_CALIBRATION_STEPS and status != "OK":'
        ),
        after='        if name == "macro_m1c" and status != "OK":',
        expected_failure_marker="test_funnel_failure_cannot_stop_unrelated_publication",
        rationale="A funnel crash must never veto NAV, ledger, or unrelated research publication.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_DISCARD",
        component="Nightly funnel wiring isolation",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            "        if not os.path.isfile(stage_file):\n"
            "            continue\n"
            "        os.remove(stage_file)"
        ),
        after=(
            "        if not os.path.isfile(stage_file):\n"
            "            continue\n"
        ),
        expected_failure_marker="test_funnel_failure_discards_its_own_health_not_macro_outputs",
        rationale="Isolation without discard republishes yesterday's summary as today's output.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_DISCARD_DISPATCH",
        component="Nightly funnel wiring isolation",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before='    "funnel_finalize": _discard_failed_funnel_outputs,',
        after='    "funnel_finalize": _discard_failed_macro_outputs,',
        expected_failure_marker="test_funnel_failure_discards_its_own_health_not_macro_outputs",
        rationale="Two isolated steps share one branch; a funnel failure must not wipe Macro outputs.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_DISCARD_POLICY_REQUIRED",
        component="Nightly funnel wiring isolation",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            "    if discard is None:\n"
            "        raise RuntimeError(\n"
            '            f"isolated step {step} has no declared output discard policy"\n'
            "        )"
        ),
        after=(
            "    if discard is None:\n"
            "        return []"
        ),
        expected_failure_marker="test_an_isolated_step_without_a_discard_policy_fails_closed",
        rationale="A new isolated step must declare how its staged outputs are destroyed.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_ARTIFACT_FRESHNESS",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            '    "funnel_finalize":       [(os.path.join("..", "..", "public", "data", "v2",\n'
            '                                             "funnel_health.json"),\n'
            '                                "as_of", True)],'
        ),
        after=(
            '    "funnel_finalize":       [(os.path.join("..", "..", "public", "data", "v2",\n'
            '                                             "funnel_health.json"),\n'
            '                                "as_of", False)],'
        ),
        expected_failure_marker="test_funnel_health_artifact_is_bound_to_this_run",
        rationale="Without freshness the funnel can report OK every night on yesterday's summary.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_DATE_PATH_GUARD",
        component="Nightly funnel wiring runner",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            "    if candidate.is_symlink() or os.path.realpath(candidate) != os.path.join(\n"
            "        os.path.realpath(root), target\n"
            "    ):"
        ),
        after="    if False:",
        expected_failure_marker="test_date_container_symlink_is_also_refused",
        rationale="The date container must not escape the observation root through a symlink.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_IMMUTABLE_RUN_PATH",
        component="Nightly funnel wiring runner",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            "    if candidate.is_symlink() or os.path.realpath(candidate) != os.path.join(\n"
            "        os.path.realpath(date_dir), run_id\n"
            "    ):"
        ),
        after="    if False:",
        expected_failure_marker="test_bundle_directory_refuses_a_symlink_that_escapes_the_root",
        rationale="Every run bundle must remain an immutable child of its validated date container.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_RUN_CONTEXT",
        component="Nightly funnel wiring runner",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            "    if not value:\n"
            '        raise FunnelError(f"缺少必需环境变量 {name} '
            '—— 拒绝在无本轮上下文时产出漏斗产物")'
        ),
        after="    if False:\n        pass",
        expected_failure_marker="test_runner_refuses_without_run_context",
        rationale="Producing a bundle without run context lets an unbound artifact claim this run.",
    ),
    # ── 复审(#269 第一轮)打出来的三条:health 可伪造 / 根 symlink 越界删除 /
    #    隔离失败在运维层静默。外加观察区 retention。
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_ROOT_SYMLINK",
        component="Nightly funnel wiring runner",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            "    if root.is_symlink():\n"
            "        raise FunnelError(\n"
            '            f"观察区根本身是符号链接,拒绝使用: {root} -> {os.path.realpath(root)}"\n'
            "        )"
        ),
        after="    pass",
        expected_failure_marker="test_a_symlinked_observation_root_is_refused",
        rationale="A symlinked observation root turns the retention sweep into arbitrary deletion.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_HEALTH_EVIDENCE",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            '    if str(manifest.get("as_of") or "") != target:'
        ),
        after="    if False:",
        expected_failure_marker="test_health_refuses_a_manifest_from_another_trade_date",
        rationale="Health must be derived from the bundle it claims to describe.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_HEALTH_CONTRACT",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            "        try:\n"
            "            _validate_funnel_health(data, artifact_path)\n"
            "        except Exception as exc:\n"
            '            return "FAILED", f"漏斗 health 契约校验失败: {exc}"'
        ),
        after='        pass',
        expected_failure_marker="test_a_content_free_health_cannot_pass_the_artifact_contract",
        rationale="Health is this step's only verifiable artifact; unvalidated means unverified.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_ISOLATED_ALARM",
        component="Nightly funnel wiring isolation",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before='        if res["report"] == "COMPLETE" and not isolated:',
        after='        if res["report"] == "COMPLETE":',
        expected_failure_marker="test_isolated_degradation_still_raises_the_ops_alarm",
        rationale="Isolation means not vetoing others, never that the failure goes unnoticed.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_RETENTION",
        component="Nightly funnel wiring runner",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            "    if keep < 1:\n"
            '        raise FunnelError(f"观察区保留天数必须 >= 1: {keep}")'
        ),
        after="    keep = max(keep, 1)",
        expected_failure_marker="test_retention_refuses_a_non_positive_keep",
        rationale="A silently clamped retention window hides a misconfigured sweep.",
    ),
    # ── 复审第二轮:verifier 不验持久 bundle / PARTIAL 不上浮 / retention 删本轮 /
    #    契约未收口 ──
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_BUNDLE_EXISTS",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            "    if not os.path.isdir(bundle_dir):\n"
            '        raise ValueError(f"health 声称的 bundle 不存在: {location}")'
        ),
        after="    if False:\n        pass",
        expected_failure_marker="test_a_health_whose_bundle_is_absent_is_rejected",
        rationale="A self-reported health with no bundle on disk is a claim, not evidence.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_BUNDLE_COUNTS",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before='    if data.get("counts") != measured_counts:',
        after="    if False:",
        expected_failure_marker="test_counts_that_disagree_with_the_bundle_are_rejected",
        rationale="Counts must be recomputed from the bundle, never taken on the health's word.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_QUALITY_ROLLUP",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            "    if (step not in RESEARCH_DATA_STEPS | MACRO_DATA_STEPS | FUNNEL_DATA_STEPS\n"
        ),
        after=(
            "    if (step not in RESEARCH_DATA_STEPS | MACRO_DATA_STEPS\n"
        ),
        expected_failure_marker="test_funnel_partial_reaches_the_top_level_quality",
        rationale="A funnel PARTIAL that never reaches the rollup is hidden behind a top-level COMPLETE.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_RETENTION_PROTECT",
        component="Nightly funnel wiring runner",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            "        if name in protected:\n"
            "            continue"
        ),
        after="        pass",
        expected_failure_marker="test_retention_never_deletes_the_current_target",
        rationale="Re-running a historical date must not let the sweep delete this run's own bundle.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_BUNDLE_CONTRACTS",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before='    validate_bundle_contracts(payloads, registry, "all_market_scan.json")',
        after="    pass",
        expected_failure_marker="test_build_health_runs_the_bundle_contracts",
        rationale="Hashes prove the files did not change, not that their content is still compliant.",
    ),
    # ── 对抗复核第三轮:rollup 只钉 helper 未钉传播 / as_of 未校形状 /
    #    verifier 不跑契约 / status 重算未钉 / 陈旧 bundle 被直接删 ──
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_QUALITY_PROPAGATION",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before='        for artifact in entry.get("artifacts", []):',
        after="        for artifact in []:",
        expected_failure_marker="test_partial_reaches_research_data_quality_end_to_end",
        rationale="Pinning the helper is not pinning the wiring that carries its answer upward.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_HEALTH_DATE_SHAPE",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            "    for key in (\"as_of\", \"target_trade_date\"):\n"
            "        value = str(data.get(key) or \"\")\n"
            "        if not (len(value) == 8 and value.isdigit()):"
        ),
        after=(
            "    for key in ():\n"
            "        value = str(data.get(key) or \"\")\n"
            "        if not (len(value) == 8 and value.isdigit()):"
        ),
        expected_failure_marker="test_a_traversal_as_of_cannot_redirect_the_verifier",
        rationale="as_of is joined into a filesystem path; an unshaped value redirects the verifier.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_VERIFIER_CONTRACTS",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            "    if registry is None:\n"
            '        raise ValueError("找不到本轮 registry,无法在验证侧复核 bundle 契约")\n'
            "    nightly_funnel.validate_bundle_contracts(\n"
            '        payloads, registry, "all_market_scan.json"\n'
            "    )"
        ),
        after="    pass",
        expected_failure_marker="test_the_verifier_also_runs_the_bundle_contracts",
        rationale="Hashes prove the bytes are unchanged, not that the content is still compliant.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_BUNDLE_STATUS",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before='    if str(data.get("status") or "").upper() != measured_status:',
        after="    if False:",
        expected_failure_marker="test_a_status_that_disagrees_with_the_bundle_is_rejected",
        rationale="Re-deriving status is the load-bearing half of making health a transcript.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_RUN_SCOPED_OUTPUT",
        component="Nightly funnel wiring runner",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before="    bundle_dir = _bundle_dir(output_root, target, run_id)",
        after="    bundle_dir = _date_dir(output_root, target)",
        expected_failure_marker="test_outer_publication_failure_keeps_the_bundle_referenced_by_live_health",
        rationale="A fixed-date output overwrites evidence before the outer publication transaction commits.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_OUTPUT_NO_OVERWRITE",
        component="Nightly funnel wiring runner",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            "    if os.path.lexists(bundle_dir):\n"
            '        raise FunnelError(f"本轮漏斗 bundle 已存在,拒绝覆盖: {bundle_dir}")'
        ),
        after="    if False:\n        pass",
        expected_failure_marker="test_same_run_id_can_never_overwrite_an_existing_bundle",
        rationale="The run-scoped address is immutable only if retries cannot overwrite it.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_IMMUTABLE_HEALTH_LOCATION",
        component="Nightly funnel wiring runner",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before='            "location": f"data_history/funnel/{target}/{run_id}",',
        after='            "location": f"data_history/funnel/{target}",',
        expected_failure_marker="test_health_location_is_run_scoped_and_immutable",
        rationale="The staged health must bind the exact immutable run bundle, not a mutable date alias.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_CONTRACT_REGISTRY",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before='    validate_registry(payloads["security_registry_projected.json"])',
        after="    pass",
        expected_failure_marker="test_projected_registry_contract_is_called",
        rationale="The projected registry must still satisfy its own contract.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_CONTRACT_SCAN",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before='    validate_all_market_scan(payloads[scan_key], registry)',
        after="    pass",
        expected_failure_marker="test_scan_contract_is_called",
        rationale="A scan carrying a composite score must be refused, not merely hashed.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_CONTRACT_CANDIDATES",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before='    validate_candidate_review(\n        payloads["candidate_review.json"], registry, payloads[scan_key]\n    )',
        after="    pass",
        expected_failure_marker="test_candidate_contract_is_called",
        rationale="Candidate review must stay bound to the same U0/U1 as_of.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_CONTRACT_QUEUE",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before='    validate_deep_research_queue(payloads["deep_research_queue.json"])',
        after="    pass",
        expected_failure_marker="test_deep_queue_contract_is_called",
        rationale="The U4 authority boundary must be re-checked, not assumed.",
    ),
    # ── 终审复核第四轮:无交易权限 / 降级明细 / symlink;外层发布事务复核 ──
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_PUBLISHED_RETENTION_PROTECT",
        component="Nightly funnel wiring runner",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before="    return as_of",
        after="    return None",
        expected_failure_marker="test_retention_protects_the_date_referenced_by_live_health",
        rationale="Retention must derive the live pointer it protects rather than accepting an arbitrary path.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_HEALTH_NO_TRADE",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before="    offending = fp.FORBIDDEN_ACTION_KEYS.intersection(fp._walk_keys(data))",
        after="    offending = set()",
        expected_failure_marker="test_health_cannot_carry_a_trade_action",
        rationale="An observation artifact carrying trade_action or blocking authority crosses the platform's red line.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_BUNDLE_DEGRADED",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before='    if data.get("degraded_channels") != measured_degraded:',
        after="    if False:",
        expected_failure_marker="test_degraded_channels_that_disagree_are_rejected",
        rationale="The degradation breakdown is the only actionable part of a perpetual PARTIAL.",
    ),
    MutationCase(
        mutation_id="FUNNEL_NIGHTLY_BUNDLE_SYMLINK",
        component="Nightly funnel wiring artifact contract",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_nightly_offline.py",
        before=(
            "    if (os.path.islink(funnel_root) or os.path.islink(date_dir) or\n"
            "            os.path.islink(bundle_dir) or\n"
            "            os.path.realpath(bundle_dir) != os.path.join(\n"
            "                os.path.realpath(funnel_root), as_of, run_id\n"
            "            )\n"
            "    ):"
        ),
        after="    if False:",
        expected_failure_marker="test_a_symlinked_bundle_pointing_outside_is_rejected",
        rationale="os.path.isdir follows symlinks; a link out of the observation area borrows someone else's bundle.",
    ),
    MutationCase(
        mutation_id="NIGHTLY_ACCEPTANCE_ENTRYPOINT",
        component="Nightly production acceptance",
        source_path="experiments/execution_tracker/nightly_acceptance.py",
        test_script="tests/test_nightly_acceptance_offline.py",
        before=(
            '    if payload.get("ProgramArguments") != expected_args:\n'
            '        raise AcceptanceError("launchd ProgramArguments do not bind the expected wrapper and runner")'
        ),
        after="    if False:\n        raise AcceptanceError(\"launchd ProgramArguments do not bind the expected wrapper and runner\")",
        expected_failure_marker="test_plist_must_use_wrapper_and_exact_runner",
        rationale="A successful engine run is not launchd acceptance when the installed job bypasses the wrapper or points elsewhere.",
    ),
    MutationCase(
        mutation_id="NIGHTLY_ACCEPTANCE_LAUNCHD_ADVANCED",
        component="Nightly production acceptance",
        source_path="experiments/execution_tracker/nightly_acceptance.py",
        test_script="tests/test_nightly_acceptance_offline.py",
        before="    if runs <= inputs.runs_before:",
        after="    if False:",
        expected_failure_marker="test_launchd_counter_must_advance_and_exit_zero",
        rationale="Filesystem output alone cannot prove the scheduled job was invoked; the launchd run counter must advance.",
    ),
    MutationCase(
        mutation_id="NIGHTLY_ACCEPTANCE_LAUNCHD_EXIT",
        component="Nightly production acceptance",
        source_path="experiments/execution_tracker/nightly_acceptance.py",
        test_script="tests/test_nightly_acceptance_offline.py",
        before="    if last_exit != 0:",
        after="    if False:",
        expected_failure_marker="test_launchd_nonzero_exit_is_rejected_after_counter_advanced",
        rationale="An advanced launchd counter with a nonzero terminal status is not a successful scheduled run.",
    ),
    MutationCase(
        mutation_id="NIGHTLY_ACCEPTANCE_PERSISTENT_BUNDLE",
        component="Nightly production acceptance",
        source_path="experiments/execution_tracker/nightly_acceptance.py",
        test_script="tests/test_nightly_acceptance_offline.py",
        before="    run_nightly._validate_funnel_health(health, str(health_path))",
        after="    pass",
        expected_failure_marker="test_funnel_health_must_survive_the_production_bundle_verifier",
        rationale="The health summary cannot attest to its own immutable bundle; the production verifier must inspect the persisted bytes.",
    ),
    MutationCase(
        mutation_id="NIGHTLY_ACCEPTANCE_EXACT_LOG_SEGMENT",
        component="Nightly production acceptance",
        source_path="experiments/execution_tracker/nightly_acceptance.py",
        test_script="tests/test_nightly_acceptance_offline.py",
        before='    if not re.search(r"(?m)^research_funnel: OK\\s*$", tail):',
        after="    if False:",
        expected_failure_marker="test_old_funnel_ok_before_exact_run_marker_cannot_pass",
        rationale="An OK line from an older append-only log segment must not certify the current scheduled run.",
    ),
    MutationCase(
        mutation_id="NIGHTLY_ACCEPTANCE_LOG_RUN_BOUNDARY",
        component="Nightly production acceptance",
        source_path="experiments/execution_tracker/nightly_acceptance.py",
        test_script="tests/test_nightly_acceptance_offline.py",
        before='    if next_run:\n        tail = tail[:len(marker) + next_run.start()]',
        after='    if False:\n        tail = tail[:len(marker) + next_run.start()]',
        expected_failure_marker="test_later_run_cannot_supply_evidence_for_the_expected_run",
        rationale="A later launchd run cannot supply funnel or report evidence for the expected run marker.",
    ),
    MutationCase(
        mutation_id="NIGHTLY_ACCEPTANCE_NO_ALARM",
        component="Nightly production acceptance",
        source_path="experiments/execution_tracker/nightly_acceptance.py",
        test_script="tests/test_nightly_acceptance_offline.py",
        before="    if inputs.alarm_path.exists():",
        after="    if False:",
        expected_failure_marker="test_alarm_flag_is_never_accepted_as_a_clean_run",
        rationale="The incomplete flag is an explicit terminal contradiction and cannot coexist with a PASS receipt.",
    ),
    MutationCase(
        mutation_id="NIGHTLY_ACCEPTANCE_RUN_CONTEXT_LOG",
        component="Nightly production acceptance",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_nightly_acceptance_offline.py",
        before=(
            '    print(\n'
            '        f"[run] run_id={res.get(\'run_id\')} "\n'
            '        f"target_trade_date={res.get(\'target_trade_date\')}"\n'
            '    )'
        ),
        after='    print("[run] context unavailable")',
        expected_failure_marker="test_terminal_report_emits_run_marker_before_step_lines",
        rationale="A reusable launchd log needs an exact run boundary before any step status can be accepted.",
    ),
    MutationCase(
        mutation_id="GOVERNANCE_NIGHTLY_ACCEPTANCE_MARKER_COVERAGE_CALL",
        component="Governance mutation gate",
        source_path="scripts/governance_mutation_gate.py",
        test_script="tests/test_governance_mutation_gate.py",
        before=("    validate_nightly_acceptance_" "marker_coverage(root, cases)"),
        after=(
            "    if False:\n"
            "        validate_nightly_acceptance_"
            "marker_coverage(root, cases)"
        ),
        expected_failure_marker=(
            "test_validate_manifest_enforces_nightly_acceptance_marker_coverage"
        ),
        rationale="The gate must not silently stop enforcing acceptance-verifier marker coverage.",
    ),
    # ── 三段子 DAG:候选清单 / 电池覆盖 / 段间绑定 ──
    MutationCase(
        mutation_id="FUNNEL_MANIFEST_COUNT_FROM_LIST",
        component="Research funnel candidate battery",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_funnel_dag_offline.py",
        before='    if payload.get("expected_count") != len(codes):',
        after="    if False:",
        expected_failure_marker="test_expected_count_is_derived_from_the_list_not_hardcoded",
        rationale="The candidate count must be derived from the manifest list, never hardcoded.",
    ),
    MutationCase(
        mutation_id="FUNNEL_BATTERY_MANIFEST_BINDING",
        component="Research funnel candidate battery",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_funnel_dag_offline.py",
        before='    if battery.get("manifest_hash") != manifest.get("manifest_hash"):',
        after="    if False:",
        expected_failure_marker="test_battery_bound_to_another_manifest_is_refused",
        rationale="A battery not bound to this run's candidate manifest is evidence for another run.",
    ),
    MutationCase(
        mutation_id="FUNNEL_BATTERY_SET_EQUALITY",
        component="Research funnel candidate battery",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_funnel_dag_offline.py",
        before="    if set(observed) != expected:",
        after="    if False:",
        expected_failure_marker="test_one_missing_row_is_a_silent_absence_and_refused",
        rationale="expected == observed as sets; one silent absence is one candidate never batteried.",
    ),
    MutationCase(
        mutation_id="FUNNEL_BATTERY_SIX_DIMS",
        component="Research funnel candidate battery",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_funnel_dag_offline.py",
        before=(
            "        if tuple(dims.keys()) != BATTERY_DIMENSIONS and set(dims.keys()) != set(BATTERY_DIMENSIONS):"
        ),
        after="        if False:",
        expected_failure_marker="test_a_row_missing_a_dimension_is_refused_not_tolerated",
        rationale="A missing dimension must appear as explicit DATA_BLOCKED, never be absent.",
    ),
    MutationCase(
        mutation_id="FUNNEL_BATTERY_ROW_SAME_DAY",
        component="Research funnel candidate battery",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_funnel_dag_offline.py",
        before='        if _date8(str(row.get("checked_at") or "")) != _date8(str(manifest.get("as_of") or "")):',
        after="        if False:",
        expected_failure_marker="test_a_prior_day_row_cannot_be_repacked_as_same_day_battery",
        rationale="Every battery row must come from the same trade date as the immutable candidate manifest.",
    ),
    MutationCase(
        mutation_id="FUNNEL_BATTERY_COMPLETENESS_RECOMPUTED",
        component="Research funnel candidate battery",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_funnel_dag_offline.py",
        before=(
            '        if (\n'
            '            completeness.get("covered") != 6 - len(blocked_dims)\n'
            '            or set(completeness.get("missing") or []) != set(blocked_dims)\n'
            '            or completeness.get("verdict") != expected_verdict\n'
            '        ):'
        ),
        after='        if False:',
        expected_failure_marker="test_completeness_is_recomputed_from_dimensions_not_self_reported",
        rationale="A row cannot self-report COMPLETE when its six dimensions contain blocked evidence.",
    ),
    MutationCase(
        mutation_id="FUNNEL_BATTERY_DIMENSION_EVIDENCE",
        component="Research funnel candidate battery",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_funnel_dag_offline.py",
        before='            if not isinstance(evidence, dict) or not evidence:',
        after='            if False:',
        expected_failure_marker="test_an_empty_dimension_is_not_complete_evidence",
        rationale="A named dimension must contain evidence; an empty object is not COMPLETE.",
    ),
    MutationCase(
        mutation_id="FUNNEL_BATTERY_DIMENSION_STATUS",
        component="Research funnel candidate battery",
        source_path="experiments/research_funnel/funnel_pipeline.py",
        test_script="tests/test_funnel_dag_offline.py",
        before='            if status is not None and status not in {"DATA_BLOCKED", "NOT_RUN"}:',
        after='            if False:',
        expected_failure_marker="test_an_unknown_dimension_status_is_not_complete_evidence",
        rationale="Unknown dimension states cannot be treated as successfully measured evidence.",
    ),
    MutationCase(
        mutation_id="FUNNEL_DAG_TOKENLESS_DEGRADATION",
        component="Nightly funnel wiring DAG",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_dag_offline.py",
        before='    ("candidate_battery", ["python3", "../research_funnel/funnel_dag.py", "battery"], False,',
        after='    ("candidate_battery", ["python3", "../research_funnel/funnel_dag.py", "battery"], True,',
        expected_failure_marker="test_live_orchestrator_runs_battery_without_token_for_explicit_rows",
        rationale="The live orchestrator must run the battery stage without a token so it can materialize per-ticket DATA_BLOCKED rows.",
    ),
    MutationCase(
        mutation_id="FUNNEL_DAG_FINAL_MANIFEST_EVIDENCE",
        component="Nightly funnel wiring DAG",
        source_path="experiments/research_funnel/funnel_dag.py",
        test_script="tests/test_funnel_dag_offline.py",
        before="    return BUNDLE_FILES + DAG_EVIDENCE_FILES",
        after="    return BUNDLE_FILES",
        expected_failure_marker="test_final_bundle_pins_candidate_manifest_and_battery_bytes",
        rationale="The final immutable manifest must pin the candidate manifest and per-ticket battery bytes.",
    ),
    MutationCase(
        mutation_id="FUNNEL_DAG_FINAL_CONTRACT",
        component="Nightly funnel wiring DAG",
        source_path="experiments/research_funnel/nightly_funnel.py",
        test_script="tests/test_funnel_dag_offline.py",
        before='            or dag.get("candidate_manifest_hash") != candidate_manifest.get("manifest_hash")',
        after="            or False",
        expected_failure_marker="test_final_bundle_revalidates_dag_bindings_not_only_file_hashes",
        rationale="Hash integrity is insufficient; the final verifier must re-check all cross-artifact DAG bindings.",
    ),
    MutationCase(
        mutation_id="FUNNEL_DAG_HEALTH_COVERAGE_RECOMPUTED",
        component="Nightly funnel wiring DAG",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_dag_offline.py",
        before='        if data.get("battery_coverage") != measured_battery:',
        after="        if False:",
        expected_failure_marker="test_production_verifier_recomputes_health_battery_coverage",
        rationale="The production verifier must derive 105/105 and blocked-row counts from immutable battery evidence.",
    ),
    MutationCase(
        mutation_id="FUNNEL_DAG_NO_LEGACY_DOWNGRADE",
        component="Nightly funnel wiring DAG",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_dag_offline.py",
        before='    if "battery_coverage" in data and "candidate_battery.json" not in payloads:',
        after='    if False:',
        expected_failure_marker="test_production_verifier_rejects_dag_evidence_downgrade",
        rationale="A DAG health receipt cannot be reinterpreted as a legacy four-file bundle.",
    ),
    MutationCase(
        mutation_id="FUNNEL_DAG_STAGE_NO_OVERWRITE",
        component="Nightly funnel wiring DAG",
        source_path="experiments/research_funnel/funnel_dag.py",
        test_script="tests/test_funnel_dag_offline.py",
        before="        if os.path.lexists(bundle_dir / name):\n            raise FunnelError(f\"stage {stage} 产物已存在,拒绝覆盖: {name}\")",
        after="        if False:\n            pass",
        expected_failure_marker="test_a_stage_refuses_to_overwrite_its_own_outputs",
        rationale="Re-running a stage under the same run_id must not silently replace evidence.",
    ),
    MutationCase(
        mutation_id="FUNNEL_DAG_STAGE_BINDING",
        component="Nightly funnel wiring DAG",
        source_path="experiments/research_funnel/funnel_dag.py",
        test_script="tests/test_funnel_dag_offline.py",
        before='    if manifest.get("as_of") != as_of or manifest.get("run_id") != run_id:',
        after="    if False:",
        expected_failure_marker="test_write_then_read_stage_binds_run_and_verifies_bytes",
        rationale="A later stage must refuse a prior stage that belongs to another run or day.",
    ),
    MutationCase(
        mutation_id="FUNNEL_DAG_FINALIZE_COVERAGE",
        component="Nightly funnel wiring DAG",
        source_path="experiments/research_funnel/funnel_dag.py",
        test_script="tests/test_funnel_dag_offline.py",
        before="    coverage = validate_candidate_battery(battery, manifest)\n    scan, candidates = p1",
        after="    coverage = {\"expected\": 0, \"observed\": 0, \"data_blocked_rows\": 0, \"complete_rows\": 0}\n    scan, candidates = p1",
        expected_failure_marker="test_three_stages_run_end_to_end_without_token",
        rationale="Finalize must publish coverage measured from the candidate battery, not a fabricated receipt.",
    ),
    MutationCase(
        mutation_id="FUNNEL_DAG_RECEIPT_CHAIN",
        component="Nightly funnel wiring DAG",
        source_path="experiments/research_funnel/funnel_dag.py",
        test_script="tests/test_funnel_dag_offline.py",
        before='                or receipt.get("stage_hash") != stage_manifest["stage_hash"]):',
        after="                or False):",
        expected_failure_marker="test_finalize_refuses_a_swapped_stage_receipt",
        rationale="Published stage receipts must match the observation-area stage manifests byte for byte.",
    ),
    MutationCase(
        mutation_id="FUNNEL_DAG_SKIP_STAYS_ISOLATED",
        component="Nightly funnel wiring DAG",
        source_path="experiments/execution_tracker/run_nightly.py",
        test_script="tests/test_funnel_dag_offline.py",
        before="            if name in ISOLATED_CALIBRATION_STEPS:\n                # 隔离步依赖隔离步",
        after="            if False:\n                # 隔离步依赖隔离步",
        expected_failure_marker="test_a_skipped_downstream_stage_stays_isolated",
        rationale="A skipped isolated stage must not veto publication through the dependency back door.",
    ),
    MutationCase(
        mutation_id="GOVERNANCE_FUNNEL_NIGHTLY_MARKER_COVERAGE_CALL",
        component="Governance mutation gate",
        source_path="scripts/governance_mutation_gate.py",
        test_script="tests/test_governance_mutation_gate.py",
        before=("    validate_funnel_nightly_" "marker_coverage(root, cases)"),
        after=(
            "    if False:\n"
            "        validate_funnel_nightly_"
            "marker_coverage(root, cases)"
        ),
        expected_failure_marker=(
            "test_validate_manifest_enforces_funnel_nightly_marker_coverage"
        ),
        rationale="The manifest must not silently stop enforcing nightly wiring marker coverage.",
    ),
    # ── U4 complete-decision ledger: selected, rejected, deferred, and blocked ──
    MutationCase(
        mutation_id="U4_LEDGER_MACHINE_GATE_SOURCE",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '        # governance-mutation: U4_LEDGER_MACHINE_GATE_SOURCE\n'
            '        if (raw["ready"] and blocked) or (not raw["ready"] and not blocked):'
        ),
        after=(
            '        # governance-mutation: U4_LEDGER_MACHINE_GATE_SOURCE\n'
            '        if False:'
        ),
        expected_failure_marker="test_ready_source_semantics_and_pool_hash_are_recomputed",
        rationale="A ready flag must not contradict the packet's explicit machine-block reasons.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_PACKET_POOL_BINDING",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '    # governance-mutation: U4_LEDGER_PACKET_POOL_BINDING\n'
            '    if source_refs.get("ready_pool_hash") != funnel._hash(rows):'
        ),
        after=(
            '    # governance-mutation: U4_LEDGER_PACKET_POOL_BINDING\n'
            '    if False:'
        ),
        expected_failure_marker="test_ready_source_semantics_and_pool_hash_are_recomputed",
        rationale="The complete decision set must be bound to the packet's frozen ready-pool bytes.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_MACHINE_GATE_EVIDENCE",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '        # governance-mutation: U4_LEDGER_MACHINE_GATE_EVIDENCE\n'
            '        if (\n'
            '            battery_verdict not in {"COMPLETE", "PARTIAL"}\n'
            '            or not set(blocked).issubset(MACHINE_BLOCK_REASONS)\n'
            '            or (raw["ready"] and battery_verdict != "COMPLETE")\n'
            '            or ((battery_verdict != "COMPLETE") != ("U3_BATTERY_INCOMPLETE" in blocked))\n'
            '        ):'
        ),
        after=(
            '        # governance-mutation: U4_LEDGER_MACHINE_GATE_EVIDENCE\n'
            '        if False:'
        ),
        expected_failure_marker="test_ready_source_must_match_u3_and_e1_gate_evidence",
        rationale="A rehashed packet cannot label partial U3 evidence as a ready U4 candidate.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_AUTHORITY_BOUNDARY",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '    # governance-mutation: U4_LEDGER_AUTHORITY_BOUNDARY\n'
            '    if (\n'
            '        draft.get("claimed_reviewer") != "Junyan"\n'
            '        or draft.get("identity_verification") != "UNAVAILABLE"\n'
            '        or draft.get("production_authority") is not False\n'
            '    ):'
        ),
        after=(
            '    # governance-mutation: U4_LEDGER_AUTHORITY_BOUNDARY\n'
            '    if False:'
        ),
        expected_failure_marker="test_authority_chronology_and_packet_binding_fail_closed",
        rationale="A local JSON draft cannot verify identity or grant production authority.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_METHOD_VERSION",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '    # governance-mutation: U4_LEDGER_METHOD_VERSION\n'
            '    if not isinstance(draft.get("method_version"), str) or not METHOD_VERSION_RE.fullmatch(\n'
            '        draft["method_version"]\n'
            '    ):'
        ),
        after=(
            '    # governance-mutation: U4_LEDGER_METHOD_VERSION\n'
            '    if False:'
        ),
        expected_failure_marker="test_authority_chronology_and_packet_binding_fail_closed",
        rationale="U4 workflow-debug decisions must remain tied to a versioned research method token.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_REVIEW_CHRONOLOGY",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '    # governance-mutation: U4_LEDGER_REVIEW_CHRONOLOGY\n'
            '    if _iso(draft.get("reviewed_at"), "decision reviewed_at") < _iso(\n'
            '        packet.get("generated_at"), "review packet generated_at"\n'
            '    ):'
        ),
        after=(
            '    # governance-mutation: U4_LEDGER_REVIEW_CHRONOLOGY\n'
            '    if False:'
        ),
        expected_failure_marker="test_authority_chronology_and_packet_binding_fail_closed",
        rationale="A decision cannot be registered before the evidence packet it claims to review.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_COMPLETE_READY_COVERAGE",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '    # governance-mutation: U4_LEDGER_COMPLETE_READY_COVERAGE\n'
            '    if set(decisions) != expected:'
        ),
        after=(
            '    # governance-mutation: U4_LEDGER_COMPLETE_READY_COVERAGE\n'
            '    if False:'
        ),
        expected_failure_marker="test_machine_blocked_candidate_cannot_enter_human_decision_set",
        rationale="Omitted ready candidates are rejected samples erased from the decision record.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_BATCH_PACKET_BINDING",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '    # governance-mutation: U4_LEDGER_BATCH_PACKET_BINDING\n'
            '    if (\n'
            '        batch.get("packet_hash") != packet.get("packet_hash")\n'
            '        or batch.get("ready_pool_hash") != packet.get("source_refs", {}).get("ready_pool_hash")\n'
            '    ):'
        ),
        after=(
            '    # governance-mutation: U4_LEDGER_BATCH_PACKET_BINDING\n'
            '    if False:'
        ),
        expected_failure_marker="test_batch_packet_binding_is_independent_of_receipt_projection",
        rationale="A rehashed batch cannot migrate its decisions to another review packet.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_REGISTRATION_SOURCE",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '    # governance-mutation: U4_LEDGER_REGISTRATION_SOURCE\n'
            '    if (\n'
            '        not isinstance(batch.get("method_version"), str)\n'
            '        or not METHOD_VERSION_RE.fullmatch(batch["method_version"])\n'
            '        or batch.get("registration_source") != REGISTRATION_SOURCE\n'
            '    ):'
        ),
        after=(
            '    # governance-mutation: U4_LEDGER_REGISTRATION_SOURCE\n'
            '    if False:'
        ),
        expected_failure_marker="test_registration_source_cannot_be_caller_supplied",
        rationale="Durable U4 registration time must come from the R-015 event timestamp, not caller text.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_MACHINE_REJECTION_PRESERVED",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '        # governance-mutation: U4_LEDGER_MACHINE_REJECTION_PRESERVED\n'
            '        if source["ready"] is False and (\n'
            '            row.get("decision") != "REJECT"\n'
            '            or row.get("decision_origin") != MACHINE_ORIGIN\n'
            '            or reason_codes != source["blocked_reasons"]\n'
            '            or row.get("research_question") != ""\n'
            '        ):'
        ),
        after=(
            '        # governance-mutation: U4_LEDGER_MACHINE_REJECTION_PRESERVED\n'
            '        if False:'
        ),
        expected_failure_marker="test_machine_rejection_cannot_be_rewritten_even_with_new_hashes",
        rationale="A machine-blocked candidate cannot disappear or be recast as a human-reviewed choice.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_BATCH_COUNTS",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '    # governance-mutation: U4_LEDGER_BATCH_COUNTS\n'
            '    if (\n'
            '        batch.get("ready_candidate_count") != sum(row["ready"] is True for row in ready_rows)\n'
            '        or batch.get("machine_blocked_count") != sum(row["ready"] is False for row in ready_rows)\n'
            '        or batch.get("selected_count") != selected\n'
            '        or batch.get("rejected_count") != rejected\n'
            '        or batch.get("deferred_count") != deferred\n'
            '        or selected not in {0, 3, 4, 5}\n'
            '    ):'
        ),
        after=(
            '    # governance-mutation: U4_LEDGER_BATCH_COUNTS\n'
            '    if False:'
        ),
        expected_failure_marker="test_batch_counts_hashes_and_no_authority_are_recomputed",
        rationale="Decision counts must be recomputed from the complete set, not trusted labels.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_NO_AUTHORITY_OR_CLAIM",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '    # governance-mutation: U4_LEDGER_NO_AUTHORITY_OR_CLAIM\n'
            '    if (\n'
            '        batch.get("production_authority") is not False\n'
            '        or batch.get("method_sample_eligible") is not False\n'
            '        or batch.get("claim_allowed") is not False\n'
            '        or batch.get("no_trade_flag") is not True\n'
            '    ):'
        ),
        after=(
            '    # governance-mutation: U4_LEDGER_NO_AUTHORITY_OR_CLAIM\n'
            '    if False:'
        ),
        expected_failure_marker="test_batch_counts_hashes_and_no_authority_are_recomputed",
        rationale="A workflow-debug U4 decision cannot become a method sample or trading authority.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_RECEIPT_PROJECTION",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '    # governance-mutation: U4_LEDGER_RECEIPT_PROJECTION\n'
            '    if batch.get("projected_receipt_hash") != expected_receipt_hash:'
        ),
        after=(
            '    # governance-mutation: U4_LEDGER_RECEIPT_PROJECTION\n'
            '    if False:'
        ),
        expected_failure_marker="test_batch_counts_hashes_and_no_authority_are_recomputed",
        rationale="The decision batch must deterministically bind the existing U4 receipt it projects.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_IDEMPOTENT_NO_REWRITE",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '    # governance-mutation: U4_LEDGER_IDEMPOTENT_NO_REWRITE\n'
            '    if existing is not None:\n'
            '        if existing.get("payload") != payload:'
        ),
        after=(
            '    # governance-mutation: U4_LEDGER_IDEMPOTENT_NO_REWRITE\n'
            '    if existing is not None:\n'
            '        if False:'
        ),
        expected_failure_marker="test_append_is_idempotent_but_same_packet_rewrite_is_refused",
        rationale="Idempotency accepts only exact retry; it cannot authorize a rewritten decision set.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_SHARED_READ_LOCK",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '            # governance-mutation: U4_LEDGER_SHARED_READ_LOCK\n'
            '            if _fcntl is not None:\n'
            '                _fcntl.flock(lock_file, _fcntl.LOCK_SH)\n'
            '            elif _msvcrt is not None:\n'
            '                lock_file.seek(0)\n'
            '                _msvcrt.locking(lock_file.fileno(), _msvcrt.LK_LOCK, 1)\n'
            '            else:\n'
            '                raise OSError("no supported file-lock implementation on this platform")'
        ),
        after=(
            '            # governance-mutation: U4_LEDGER_SHARED_READ_LOCK\n'
            '            pass'
        ),
        expected_failure_marker="test_verifier_waits_for_atomic_ledger_and_anchor_snapshot",
        rationale="Readers must not observe the ledger replacement before its matching anchor commit.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_EXISTING_SNAPSHOT",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '    # governance-mutation: U4_LEDGER_EXISTING_SNAPSHOT\n'
            '    with _ledger_read_snapshot(path):'
        ),
        after=(
            '    # governance-mutation: U4_LEDGER_EXISTING_SNAPSHOT\n'
            '    with nullcontext():'
        ),
        expected_failure_marker="test_exact_retry_waits_for_atomic_ledger_and_anchor_snapshot",
        rationale="Idempotent retry must verify and read events from one shared-lock snapshot.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_VERIFY_SNAPSHOT",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '        # governance-mutation: U4_LEDGER_VERIFY_SNAPSHOT\n'
            '        with _ledger_read_snapshot(ledger_path):'
        ),
        after=(
            '        # governance-mutation: U4_LEDGER_VERIFY_SNAPSHOT\n'
            '        with nullcontext():'
        ),
        expected_failure_marker="test_verifier_waits_for_atomic_ledger_and_anchor_snapshot",
        rationale="Public verification must read the event chain and anchor under the same snapshot lock.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_DEDICATED_EVENT_KIND",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '            # governance-mutation: U4_LEDGER_DEDICATED_EVENT_KIND\n'
            '            if event.get("kind") != EVENT_KIND:'
        ),
        after=(
            '            # governance-mutation: U4_LEDGER_DEDICATED_EVENT_KIND\n'
            '            if False:'
        ),
        expected_failure_marker="test_dedicated_verifier_rejects_foreign_kind_and_tampering",
        rationale="A dedicated U4 ledger cannot mix unrelated event semantics into the same history.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_EVENT_PACKET_ID",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '            # governance-mutation: U4_LEDGER_EVENT_PACKET_ID\n'
            '            if event.get("id") != packet_hash or packet_hash in seen:'
        ),
        after=(
            '            # governance-mutation: U4_LEDGER_EVENT_PACKET_ID\n'
            '            if False:'
        ),
        expected_failure_marker="test_dedicated_verifier_binds_event_id_to_packet_hash",
        rationale="The event identity must be the packet hash so one packet cannot acquire two outcomes.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_REGISTRATION_CHRONOLOGY",
        component="Research funnel U4 decision ledger",
        source_path="experiments/research_funnel/u4_decision_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '    # governance-mutation: U4_LEDGER_REGISTRATION_CHRONOLOGY\n'
            '    if registered < _iso(reviewed_at, "decision reviewed_at"):'
        ),
        after=(
            '    # governance-mutation: U4_LEDGER_REGISTRATION_CHRONOLOGY\n'
            '    if False:'
        ),
        expected_failure_marker="test_ledger_timestamp_is_the_registration_chronology_boundary",
        rationale="The durable event timestamp, not a self-reported review time, defines registration chronology.",
    ),
    MutationCase(
        mutation_id="U4_LEDGER_EVENT_KIND_UNIQUE",
        component="Research funnel U4 decision ledger",
        source_path="experiments/execution_tracker/event_ledger.py",
        test_script="tests/test_u4_decision_ledger.py",
        before=(
            '                # governance-mutation: U4_LEDGER_EVENT_KIND_UNIQUE\n'
            '                "u4_decision",'
        ),
        after=(
            '                # governance-mutation: U4_LEDGER_EVENT_KIND_UNIQUE\n'
            '                # u4_decision uniqueness removed by mutation'
        ),
        expected_failure_marker="test_u4_decision_event_kind_is_unique_in_shared_chain",
        rationale="The shared chain must reject a second terminal decision for the same U4 packet.",
    ),
)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str
    receipt: "TestReceipt | None" = None


@dataclass(frozen=True)
class LocalTestTarget:
    name: str
    kind: str
    class_name: str | None = None


@dataclass(frozen=True)
class TestReceipt:
    schema: str
    target: str
    kind: str
    class_name: str | None
    tests_run: int
    failures: int
    errors: int
    skipped: int
    expected_failures: int
    unexpected_successes: int
    diagnostics: dict[str, list[str]]


def _local_test_target(test_script: Path, name: str) -> LocalTestTarget:
    tree = ast.parse(test_script.read_text(encoding="utf-8"), filename=str(test_script))
    candidates: list[LocalTestTarget] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            candidates.append(LocalTestTarget(name=name, kind="function"))
        elif isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            raise MutationGateError(f"async test targets are unsupported: {name}")
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == name:
                    candidates.append(
                        LocalTestTarget(name=name, kind="method", class_name=node.name)
                    )
                elif isinstance(member, ast.AsyncFunctionDef) and member.name == name:
                    raise MutationGateError(f"async test targets are unsupported: {node.name}.{name}")
    if not candidates:
        raise MutationGateError(
            f"exactly one local test target required: {name}; found 0"
        )
    if len(candidates) > 1:
        raise MutationGateError(
            f"exactly one local test target required: {name}; found {len(candidates)}"
        )
    return candidates[0]


def _parse_receipt(path: Path) -> TestReceipt:
    if not path.is_file():
        raise MutationGateError("test subprocess did not produce a structured receipt")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MutationGateError("test subprocess produced an invalid receipt") from exc
    required = {
        "schema",
        "target",
        "kind",
        "class_name",
        "tests_run",
        "failures",
        "errors",
        "skipped",
        "expected_failures",
        "unexpected_successes",
        "diagnostics",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise MutationGateError("test receipt shape is invalid")
    if payload["schema"] != "ar-governance-test-receipt.v1":
        raise MutationGateError("test receipt schema is invalid")
    if payload["kind"] not in {"function", "method"}:
        raise MutationGateError("test receipt target kind is invalid")
    if not isinstance(payload["target"], str) or not payload["target"]:
        raise MutationGateError("test receipt target is invalid")
    if payload["class_name"] is not None and not isinstance(payload["class_name"], str):
        raise MutationGateError("test receipt class name is invalid")
    for field in (
        "tests_run",
        "failures",
        "errors",
        "skipped",
        "expected_failures",
        "unexpected_successes",
    ):
        value = payload[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MutationGateError(f"test receipt count is invalid: {field}")
    diagnostics = payload["diagnostics"]
    if not isinstance(diagnostics, dict) or set(diagnostics) != {
        "failures",
        "errors",
        "skipped",
        "expected_failures",
        "unexpected_successes",
    }:
        raise MutationGateError("test receipt diagnostics are invalid")
    if any(
        not isinstance(values, list) or not all(isinstance(item, str) for item in values)
        for values in diagnostics.values()
    ):
        raise MutationGateError("test receipt diagnostics must contain string lists")
    for field in diagnostics:
        if len(diagnostics[field]) != payload[field]:
            raise MutationGateError(f"test receipt diagnostic count mismatch: {field}")
    return TestReceipt(**payload)


def replace_exact(text: str, before: str, after: str, mutation_id: str) -> str:
    count = text.count(before)
    if count != 1:
        raise MutationGateError(
            f"{mutation_id}: mutation anchor must occur exactly once; found {count}"
        )
    if before == after:
        raise MutationGateError(f"{mutation_id}: mutation must change source bytes")
    return text.replace(before, after, 1)


def _resolved_under(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise MutationGateError(f"path escapes repository: {relative}") from exc
    return candidate


def validate_manifest(root: Path, cases: Sequence[MutationCase]) -> None:
    ids: set[str] = set()
    for case in cases:
        if case.mutation_id in ids:
            raise MutationGateError(f"duplicate mutation id: {case.mutation_id}")
        ids.add(case.mutation_id)
        source = _resolved_under(root, case.source_path)
        test_script = _resolved_under(root, case.test_script)
        if not source.is_file() or not test_script.is_file():
            raise MutationGateError(f"{case.mutation_id}: source or test script is missing")
        replace_exact(source.read_text(encoding="utf-8"), case.before, case.after, case.mutation_id)
        _local_test_target(test_script, _target_test(case))
    validate_k1_marker_coverage(root, cases)
    validate_a035_marker_coverage(root, cases)
    validate_r043_marker_coverage(root, cases)
    validate_funnel_marker_coverage(root, cases)
    validate_funnel_nightly_marker_coverage(root, cases)
    validate_nightly_acceptance_marker_coverage(root, cases)


def validate_k1_marker_coverage(
    root: Path,
    cases: Sequence[MutationCase],
    marker_paths: Sequence[str] = K1_GOVERNANCE_PATHS,
) -> None:
    marked: dict[str, str] = {}
    for relative in marker_paths:
        source = _resolved_under(root, relative)
        if not source.is_file():
            raise MutationGateError(f"K1 governance marker source is missing: {relative}")
        for line_number, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = GOVERNANCE_MARKER_RE.fullmatch(line)
            if not match:
                continue
            mutation_id = match.group("mutation_id")
            if mutation_id in marked:
                raise MutationGateError(
                    f"duplicate K1 governance marker: {mutation_id} at "
                    f"{marked[mutation_id]} and {relative}:{line_number}"
                )
            marked[mutation_id] = f"{relative}:{line_number}"

    declared = {
        case.mutation_id for case in cases if case.component.startswith("AIOS K1")
    }
    marker_ids = set(marked)
    missing_mutations = sorted(marker_ids - declared)
    missing_markers = sorted(declared - marker_ids)
    if missing_mutations or missing_markers:
        raise MutationGateError(
            "K1 governance marker drift: "
            f"markers_without_mutations={missing_mutations}; "
            f"mutations_without_markers={missing_markers}"
        )


def validate_a035_marker_coverage(
    root: Path,
    cases: Sequence[MutationCase],
    marker_paths: Sequence[str] = A035_GOVERNANCE_PATHS,
    prefix: str = A035_MUTATION_PREFIX,
) -> None:
    declared = {
        case.mutation_id for case in cases if case.mutation_id.startswith(prefix)
    }
    existing_paths = [
        relative for relative in marker_paths if _resolved_under(root, relative).is_file()
    ]
    if not declared and not existing_paths:
        return

    marked: dict[str, str] = {}
    for relative in marker_paths:
        source = _resolved_under(root, relative)
        if not source.is_file():
            raise MutationGateError(f"A-035 governance marker source is missing: {relative}")
        for line_number, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = GOVERNANCE_MARKER_RE.fullmatch(line)
            if not match:
                continue
            mutation_id = match.group("mutation_id")
            if not mutation_id.startswith(prefix):
                continue
            if mutation_id in marked:
                raise MutationGateError(
                    f"duplicate A-035 governance marker: {mutation_id} at "
                    f"{marked[mutation_id]} and {relative}:{line_number}"
                )
            marked[mutation_id] = f"{relative}:{line_number}"

    marker_ids = set(marked)
    missing_mutations = sorted(marker_ids - declared)
    missing_markers = sorted(declared - marker_ids)
    if missing_mutations or missing_markers:
        raise MutationGateError(
            "A-035 governance marker drift: "
            f"markers_without_mutations={missing_mutations}; "
            f"mutations_without_markers={missing_markers}"
        )


def validate_r043_marker_coverage(
    root: Path,
    cases: Sequence[MutationCase],
    marker_paths: Sequence[str] = R043_GOVERNANCE_PATHS,
) -> None:
    marked: dict[str, str] = {}
    for relative in marker_paths:
        source = _resolved_under(root, relative)
        if not source.is_file():
            raise MutationGateError(f"R-043 governance marker source is missing: {relative}")
        for line_number, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = GOVERNANCE_MARKER_RE.fullmatch(line)
            if not match:
                continue
            mutation_id = match.group("mutation_id")
            if mutation_id in marked:
                raise MutationGateError(
                    f"duplicate R-043 governance marker: {mutation_id} at "
                    f"{marked[mutation_id]} and {relative}:{line_number}"
                )
            marked[mutation_id] = f"{relative}:{line_number}"

    declared = {
        case.mutation_id
        for case in cases
        if case.component.startswith("R-043 publication migration")
    }
    marker_ids = set(marked)
    missing_mutations = sorted(marker_ids - declared)
    missing_markers = sorted(declared - marker_ids)
    if missing_mutations or missing_markers:
        raise MutationGateError(
            "R-043 governance marker drift: "
            f"markers_without_mutations={missing_mutations}; "
            f"mutations_without_markers={missing_markers}"
        )


def validate_funnel_marker_coverage(
    root: Path,
    cases: Sequence[MutationCase],
    marker_paths: Sequence[str] = FUNNEL_GOVERNANCE_PATHS,
) -> None:
    marked: dict[str, str] = {}
    for relative in marker_paths:
        source = _resolved_under(root, relative)
        if not source.is_file():
            raise MutationGateError(f"funnel governance marker source is missing: {relative}")
        for line_number, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = GOVERNANCE_MARKER_RE.fullmatch(line)
            if not match:
                continue
            mutation_id = match.group("mutation_id")
            if mutation_id in marked:
                raise MutationGateError(
                    f"duplicate funnel governance marker: {mutation_id} at "
                    f"{marked[mutation_id]} and {relative}:{line_number}"
                )
            marked[mutation_id] = f"{relative}:{line_number}"

    declared = {
        case.mutation_id
        for case in cases
        if case.component.startswith("Research funnel")
    }
    marker_ids = set(marked)
    missing_mutations = sorted(marker_ids - declared)
    missing_markers = sorted(declared - marker_ids)
    if missing_mutations or missing_markers:
        raise MutationGateError(
            "funnel governance marker drift: "
            f"markers_without_mutations={missing_mutations}; "
            f"mutations_without_markers={missing_markers}"
        )


def validate_funnel_nightly_marker_coverage(
    root: Path,
    cases: Sequence[MutationCase],
    marker_paths: Sequence[str] = FUNNEL_NIGHTLY_GOVERNANCE_PATHS,
    prefix: str = FUNNEL_NIGHTLY_MUTATION_PREFIX,
) -> None:
    """夜链接入的治理规则必须逐条带 marker,双向配对。

    与上面那条的差别只有一个:按 mutation_id 前缀筛,不按 component 前缀。
    原因是 run_nightly.py 同时承载 Macro 的 marker —— 按文件精确配对会把不相干的
    治理族卷进来。前缀配对让两条规则互不干扰,同时谁都逃不掉。
    """
    marked: dict[str, str] = {}
    for relative in marker_paths:
        source = _resolved_under(root, relative)
        if not source.is_file():
            raise MutationGateError(
                f"funnel nightly governance marker source is missing: {relative}"
            )
        for line_number, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = GOVERNANCE_MARKER_RE.fullmatch(line)
            if not match:
                continue
            mutation_id = match.group("mutation_id")
            if not mutation_id.startswith(prefix):
                continue
            if mutation_id in marked:
                raise MutationGateError(
                    f"duplicate funnel nightly governance marker: {mutation_id} at "
                    f"{marked[mutation_id]} and {relative}:{line_number}"
                )
            marked[mutation_id] = f"{relative}:{line_number}"

    declared = {
        case.mutation_id for case in cases if case.mutation_id.startswith(prefix)
    }
    marker_ids = set(marked)
    missing_mutations = sorted(marker_ids - declared)
    missing_markers = sorted(declared - marker_ids)
    if missing_mutations or missing_markers:
        raise MutationGateError(
            "funnel nightly governance marker drift: "
            f"markers_without_mutations={missing_mutations}; "
            f"mutations_without_markers={missing_markers}"
        )


def validate_nightly_acceptance_marker_coverage(
    root: Path,
    cases: Sequence[MutationCase],
    marker_paths: Sequence[str] = NIGHTLY_ACCEPTANCE_GOVERNANCE_PATHS,
    prefix: str = NIGHTLY_ACCEPTANCE_MUTATION_PREFIX,
) -> None:
    """The acceptance verifier's fail-closed checks must be mutation-pinned."""
    marked: dict[str, str] = {}
    for relative in marker_paths:
        source = _resolved_under(root, relative)
        if not source.is_file():
            raise MutationGateError(
                f"nightly acceptance governance marker source is missing: {relative}"
            )
        for line_number, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = GOVERNANCE_MARKER_RE.fullmatch(line)
            if not match:
                continue
            mutation_id = match.group("mutation_id")
            if not mutation_id.startswith(prefix):
                continue
            if mutation_id in marked:
                raise MutationGateError(
                    f"duplicate nightly acceptance governance marker: {mutation_id} at "
                    f"{marked[mutation_id]} and {relative}:{line_number}"
                )
            marked[mutation_id] = f"{relative}:{line_number}"
    declared = {
        case.mutation_id for case in cases if case.mutation_id.startswith(prefix)
    }
    missing_mutations = sorted(set(marked) - declared)
    missing_markers = sorted(declared - set(marked))
    if missing_mutations or missing_markers:
        raise MutationGateError(
            "nightly acceptance governance marker drift: "
            f"markers_without_mutations={missing_mutations}; "
            f"mutations_without_markers={missing_markers}"
        )


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache"}
    return {name for name in names if name in ignored or name.endswith((".pyc", ".pyo"))}


def _write_network_guard(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "sitecustomize.py").write_text(
        "import socket\n"
        "\n"
        "_Socket = socket.socket\n"
        "class OfflineSocket(_Socket):\n"
        "    def connect(self, *_args, **_kwargs):\n"
        "        raise PermissionError('network disabled by governance mutation gate')\n"
        "    def connect_ex(self, *_args, **_kwargs):\n"
        "        raise PermissionError('network disabled by governance mutation gate')\n"
        "socket.socket = OfflineSocket\n"
        "def _blocked(*_args, **_kwargs):\n"
        "    raise PermissionError('network disabled by governance mutation gate')\n"
        "socket.create_connection = _blocked\n"
        "socket.getaddrinfo = _blocked\n",
        encoding="utf-8",
    )


def _subprocess_env(sandbox: Path, guard: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(part in key.upper() for part in SECRET_NAME_PARTS)
    }
    environment.update(
        {
            "AR_OFFLINE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "TZ": "UTC",
            "PYTHONPATH": os.pathsep.join((str(guard), str(sandbox))),
        }
    )
    return environment


def run_test_script(
    sandbox: Path,
    guard: Path,
    script: str,
    test_function: str,
) -> CommandResult:
    test_script = _resolved_under(sandbox, script)
    target = _local_test_target(test_script, test_function)
    receipt_id = hashlib.sha256(
        f"{script}\0{test_function}".encode("utf-8")
    ).hexdigest()
    receipt_path = guard / "receipts" / f"{os.getpid()}-{receipt_id}.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.unlink(missing_ok=True)
    command = [
        sys.executable,
        "-B",
        "-c",
        SINGLE_TEST_RUNNER,
        script,
        target.name,
        target.kind,
        target.class_name or "",
        str(receipt_path),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=sandbox,
            env=_subprocess_env(sandbox, guard),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MutationGateError(f"test timed out: {script}") from exc
    receipt = _parse_receipt(receipt_path) if receipt_path.exists() else None
    if receipt is not None and (
        receipt.target != target.name
        or receipt.kind != target.kind
        or receipt.class_name != target.class_name
    ):
        raise MutationGateError("test receipt does not match the resolved local target")
    return CommandResult(
        returncode=completed.returncode,
        output=(completed.stdout or "") + (completed.stderr or ""),
        receipt=receipt,
    )


def classify_mutation(case: MutationCase, result: CommandResult) -> None:
    receipt = result.receipt
    if receipt is None:
        raise MutationGateError(f"{case.mutation_id}: missing structured test receipt")
    if receipt.target != _target_test(case):
        raise MutationGateError(f"{case.mutation_id}: test receipt target mismatch")
    if receipt.tests_run != 1:
        raise MutationGateError(f"{case.mutation_id}: expected exactly one test execution")
    if (
        receipt.errors
        or receipt.skipped
        or receipt.expected_failures
        or receipt.unexpected_successes
    ):
        raise MutationGateError(
            f"{case.mutation_id}: invalid kill; only assertion failures count"
        )
    if receipt.failures < 1 or result.returncode != 1:
        raise MutationGateError(f"{case.mutation_id}: SURVIVED; declared test did not fail")


def validate_baseline_result(script: str, target: str, result: CommandResult) -> None:
    receipt = result.receipt
    if receipt is None:
        raise MutationGateError(f"baseline missing structured receipt: {script}::{target}")
    if receipt.target != target or receipt.tests_run != 1:
        raise MutationGateError(f"baseline target receipt mismatch: {script}::{target}")
    if (
        result.returncode != 0
        or receipt.failures
        or receipt.errors
        or receipt.skipped
        or receipt.expected_failures
        or receipt.unexpected_successes
    ):
        raise MutationGateError(f"baseline test was not one clean pass: {script}::{target}")


def _tail(output: str, lines: int = 30) -> str:
    return "\n".join(output.splitlines()[-lines:])


def _target_test(case: MutationCase) -> str:
    return case.test_function or case.expected_failure_marker


def run_gate(root: Path = REPO_ROOT, cases: Sequence[MutationCase] = MUTATIONS) -> None:
    validate_manifest(root, cases)
    with tempfile.TemporaryDirectory(prefix="ar-governance-mutations-") as tmp:
        tmp_root = Path(tmp)
        sandbox = tmp_root / "repo"
        guard = tmp_root / "guard"
        shutil.copytree(root, sandbox, ignore=_copy_ignore)
        _write_network_guard(guard)

        targets = tuple(dict.fromkeys((case.test_script, _target_test(case)) for case in cases))
        for script, test_function in targets:
            result = run_test_script(sandbox, guard, script, test_function)
            try:
                validate_baseline_result(script, test_function, result)
            except MutationGateError as exc:
                raise MutationGateError(
                    f"baseline failed before mutation: {script}::{test_function}: {exc}\n"
                    f"{_tail(result.output)}"
                ) from exc
            print(f"BASELINE PASS  {script}::{test_function}")

        for case in cases:
            target = _resolved_under(sandbox, case.source_path)
            original = target.read_text(encoding="utf-8")
            mutated = replace_exact(original, case.before, case.after, case.mutation_id)
            result: CommandResult | None = None
            try:
                target.write_text(mutated, encoding="utf-8")
                result = run_test_script(
                    sandbox,
                    guard,
                    case.test_script,
                    _target_test(case),
                )
                classify_mutation(case, result)
            except MutationGateError as exc:
                if result is not None and result.output:
                    raise MutationGateError(f"{exc}\n{_tail(result.output)}") from exc
                raise
            finally:
                target.write_text(original, encoding="utf-8")
            print(f"KILLED         {case.mutation_id} [{case.component}]")

    print(f"governance mutation gate: {len(cases)}/{len(cases)} mutations killed")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list declared mutations")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list:
        for case in MUTATIONS:
            print(f"{case.mutation_id}\t{case.component}\t{case.source_path}")
        return 0
    try:
        run_gate()
    except MutationGateError as exc:
        print(f"governance mutation gate: FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
