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
