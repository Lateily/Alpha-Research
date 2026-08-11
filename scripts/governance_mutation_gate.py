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
INFRA_FAILURE_MARKERS = (
    "SyntaxError",
    "ModuleNotFoundError",
    "ImportError",
    "No such file or directory",
)
TEST_FAILURE_MARKERS = ("AssertionError", "FAILED (", "FAIL:")
SECRET_NAME_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
GOVERNANCE_MARKER_RE = re.compile(
    r"^\s*# governance-mutation: (?P<mutation_id>[A-Z0-9_]+)\s*$"
)
K1_GOVERNANCE_PATHS = (
    "scripts/llm/ai_os/task_compiler.py",
    "scripts/llm/ai_os/registry.py",
    "scripts/llm/ai_os/reconciler.py",
)
R043_GOVERNANCE_PATHS = (
    "experiments/execution_tracker/publication_migration.py",
)


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
        mutation_id="AIOS_K2_HIGH_RISK_BLOCK",
        component="AIOS K2 policy gate",
        source_path="scripts/llm/ai_os/policy_engine.py",
        test_script="tests/test_ai_os_k2_policy_offline.py",
        before='    if risk_level in {"HIGH", "CONSTITUTIONAL"}:\n',
        after="    if False:\n",
        expected_failure_marker=(
            "test_policy_blocks_medium_production_and_all_high_risk_until_review_contract"
        ),
        rationale="HIGH and CONSTITUTIONAL routing must stay blocked until reviewer capabilities are wired.",
        test_function="test_policy_blocks_medium_production_and_all_high_risk_until_review_contract",
    ),
    MutationCase(
        mutation_id="AIOS_K2_MEDIUM_PRODUCTION_BLOCK",
        component="AIOS K2 policy gate",
        source_path="scripts/llm/ai_os/policy_engine.py",
        test_script="tests/test_ai_os_k2_policy_offline.py",
        before='    elif cleaned_mode == "PRODUCTION" and risk_level == "MEDIUM":\n',
        after="    elif False:\n",
        expected_failure_marker=(
            "test_policy_blocks_medium_production_and_all_high_risk_until_review_contract"
        ),
        rationale="MEDIUM production routing cannot proceed before independent review is wired.",
        test_function="test_policy_blocks_medium_production_and_all_high_risk_until_review_contract",
    ),
    MutationCase(
        mutation_id="AIOS_K2_ALLOWLIST_EVIDENCE",
        component="AIOS K2 policy gate",
        source_path="scripts/llm/ai_os/policy_engine.py",
        test_script="tests/test_ai_os_k2_policy_offline.py",
        before="        if not _has_allowlist_evidence(allowlist_evidence):\n",
        after="        if False:\n",
        expected_failure_marker="test_policy_requires_concrete_allowlist_evidence",
        rationale="ALLOWLIST cannot map to provider_only without structured allowlist evidence.",
        test_function="test_policy_requires_concrete_allowlist_evidence",
    ),
    MutationCase(
        mutation_id="AIOS_K2_EXECUTION_TRACKER_CASEFOLD",
        component="AIOS K2 policy gate",
        source_path="scripts/llm/ai_os/policy_engine.py",
        test_script="tests/test_ai_os_k2_policy_offline.py",
        before='    return unicodedata.normalize("NFKC", value).casefold()\n',
        after='    return unicodedata.normalize("NFKC", value)\n',
        expected_failure_marker="test_policy_blocks_execution_tracker_case_and_unicode_variants",
        rationale="execution_tracker and forbidden scopes must be compared case-insensitively.",
        test_function="test_policy_blocks_execution_tracker_case_and_unicode_variants",
    ),
    MutationCase(
        mutation_id="AIOS_K2_APPROVAL_ANCHOR",
        component="AIOS K2 policy gate",
        source_path="scripts/llm/ai_os/policy_engine.py",
        test_script="tests/test_ai_os_k2_policy_offline.py",
        before="            and has_anchor\n",
        after="            and True\n",
        expected_failure_marker="test_policy_requires_junyan_approval_for_constitutional_risk",
        rationale="CONSTITUTIONAL approval must include a structured audit anchor, not only a name.",
        test_function="test_policy_requires_junyan_approval_for_constitutional_risk",
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
)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str


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
        if case.test_function is not None:
            functions = {
                node.name
                for node in ast.parse(test_script.read_text(encoding="utf-8")).body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if case.test_function not in functions:
                raise MutationGateError(
                    f"{case.mutation_id}: test function is missing: {case.test_function}"
                )
    validate_k1_marker_coverage(root, cases)
    validate_r043_marker_coverage(root, cases)


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
    test_function: str | None = None,
) -> CommandResult:
    command = [sys.executable, "-B", script]
    if test_function is not None:
        command = [
            sys.executable,
            "-B",
            "-c",
            (
                "import runpy,sys; "
                "scope=runpy.run_path(sys.argv[1], run_name='mutation_gate_target'); "
                "scope[sys.argv[2]]()"
            ),
            script,
            test_function,
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
    return CommandResult(
        returncode=completed.returncode,
        output=(completed.stdout or "") + (completed.stderr or ""),
    )


def classify_mutation(case: MutationCase, result: CommandResult) -> None:
    if result.returncode == 0:
        raise MutationGateError(f"{case.mutation_id}: SURVIVED; tests stayed green")
    if any(marker in result.output for marker in INFRA_FAILURE_MARKERS):
        raise MutationGateError(
            f"{case.mutation_id}: invalid kill caused by infrastructure failure"
        )
    if not any(marker in result.output for marker in TEST_FAILURE_MARKERS):
        raise MutationGateError(
            f"{case.mutation_id}: nonzero exit lacked a behavioral test failure marker"
        )
    if case.expected_failure_marker not in result.output:
        raise MutationGateError(
            f"{case.mutation_id}: wrong test failed; expected "
            f"{case.expected_failure_marker}"
        )


def _tail(output: str, lines: int = 30) -> str:
    return "\n".join(output.splitlines()[-lines:])


def run_gate(root: Path = REPO_ROOT, cases: Sequence[MutationCase] = MUTATIONS) -> None:
    validate_manifest(root, cases)
    with tempfile.TemporaryDirectory(prefix="ar-governance-mutations-") as tmp:
        tmp_root = Path(tmp)
        sandbox = tmp_root / "repo"
        guard = tmp_root / "guard"
        shutil.copytree(root, sandbox, ignore=_copy_ignore)
        _write_network_guard(guard)

        targets = tuple(
            dict.fromkeys((case.test_script, case.test_function) for case in cases)
        )
        for script, test_function in targets:
            result = run_test_script(sandbox, guard, script, test_function)
            if result.returncode != 0:
                raise MutationGateError(
                    f"baseline failed before mutation: {script}"
                    f"::{test_function or 'all'}\n{_tail(result.output)}"
                )
            print(f"BASELINE PASS  {script}::{test_function or 'all'}")

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
                    case.test_function,
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
