#!/usr/bin/env python3
"""Offline behavioral tests for the shared AR Team AI Workspace."""

from __future__ import annotations

import json
import copy
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import team_ai_workspace as workspace  # noqa: E402


def test_current_workspace_contract_is_complete() -> None:
    report = workspace.evaluate_workspace(ROOT, require_tools=False)

    assert report["failures"] == [], report
    assert report["skills"]["missing"] == []
    assert report["skills"]["invalid"] == []
    assert report["task_compiler"]["status"] == "SPEC_READY"
    assert report["task_compiler"]["task_id"] == "TEAM-EXAMPLE-001"
    assert report["command_policy"]["status"] == "VALID"
    assert report["hygiene"]["tracked_secret_findings"] == []
    assert report["workspace_contract"]["missing"] == []
    assert workspace._strict_json(ROOT / workspace.CONFIG_REL)["runtime_baseline"][
        "codex_version_enforcement"
    ] == "WARN_ONLY"
    assert report["workspace_contract"]["layout"]["root_container"] == "AR"
    assert report["workspace_contract"]["layout"]["containers"] == [
        "projects",
        "worktrees",
        "runtime",
        "archive",
        "local-ai",
    ]


def test_root_instructions_remove_legacy_role_and_contract_conflicts() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "secondary collaborator, not the primary builder" not in text
    assert "Current 5-stock watchlist" not in text
    assert "Compile the task source" in text
    assert "Final merge authority belongs to Junyan" in text
    assert "Do not create a parallel task format" in text
    assert "LOCAL_WORKSPACE_CONTRACT_V1.md" in text


def test_required_skills_have_metadata_and_ui_prompt() -> None:
    config = workspace._strict_json(ROOT / workspace.CONFIG_REL)
    report = workspace.inspect_skills(ROOT, config["required_skills"])

    assert report["missing"] == []
    assert report["invalid"] == []
    assert sorted(report["discovered"]) == sorted(config["required_skills"])


def test_secret_scanner_reports_rule_and_path_without_secret_value() -> None:
    secret = "sk-" + "Z" * 32
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        path = root / "bad.py"
        path.write_text(f'API_KEY = "{secret}"\n', encoding="utf-8")
        findings = workspace.find_secret_violations(root, ["bad.py"])

    rendered = json.dumps(findings)
    assert findings == [
        {"file": "bad.py", "rule": "OPENAI_STYLE_KEY"},
        {"file": "bad.py", "rule": "ASSIGNED_SECRET"},
    ]
    assert secret not in rendered


def test_secret_scanner_does_not_flag_environment_reads_or_test_placeholders() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "safe.py").write_text(
            'token = os.environ.get("TUSHARE_TOKEN", "")\n'
            'API_KEY = "CENSUS_SECRET_123"\n',
            encoding="utf-8",
        )
        findings = workspace.find_secret_violations(root, ["safe.py"])

    assert findings == []


def test_local_only_matching_never_rejects_env_example() -> None:
    patterns = [".env", ".env.*", ".ai-workspace/", "*.key"]

    assert workspace._matches_local_only(".env", patterns)
    assert workspace._matches_local_only(".env.local", patterns)
    assert workspace._matches_local_only(".ai-workspace/report.json", patterns)
    assert workspace._matches_local_only("secret.key", patterns)
    assert not workspace._matches_local_only(".env.example", patterns)


def test_remote_identity_accepts_equivalent_github_url_forms() -> None:
    expected = "Lateily/Alpha-Research"
    remotes = [
        "https://github.com/Lateily/Alpha-Research",
        "https://github.com/Lateily/Alpha-Research.git",
        "git@github.com:Lateily/Alpha-Research",
        "git@github.com:Lateily/Alpha-Research.git",
    ]

    assert all(workspace.remote_repository_slug(remote) == expected for remote in remotes)
    assert workspace.remote_repository_slug("/tmp/local-repository") is None


def test_local_workspace_contract_pins_domain_and_retirement_rules() -> None:
    contract = (ROOT / "docs/team/LOCAL_WORKSPACE_CONTRACT_V1.md").read_text(
        encoding="utf-8"
    )
    skill = (ROOT / ".agents/skills/ar-workspace-sync/SKILL.md").read_text(
        encoding="utf-8"
    )

    for domain in ("research", "macro", "aios", "product"):
        assert f"`{domain}/`" in contract
    assert "git worktree remove" in contract
    assert "pr-<number>-<short-slug>" in contract
    assert "git worktree remove" in skill
    assert "production runtime outside development worktrees" in skill
    assert "Do not move, rename, or govern Application" in skill


def test_doctor_cli_emits_parseable_redacted_report() -> None:
    report_path = ROOT / workspace.LOCAL_REPORT_REL
    report_before = report_path.read_bytes() if report_path.exists() else None
    status_before = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/team_ai_workspace.py"), "doctor", "--ci", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema"] == workspace.SCHEMA
    assert payload["failures"] == []
    assert "value" not in json.dumps(payload["hygiene"]).lower()
    report_after = report_path.read_bytes() if report_path.exists() else None
    status_after = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert report_after == report_before
    assert status_after == status_before


def test_onboarding_contract_reuses_existing_clone_and_defines_write_boundary() -> None:
    root_contract = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    onboarding = (ROOT / "docs/team/TEAM_AI_WORKSPACE_V1.md").read_text(encoding="utf-8")
    normalized_root_contract = " ".join(root_contract.split())

    assert "Reuse an existing valid clone" in root_contract
    assert "explicitly authorized control-plane check" in root_contract
    assert "does not modify tracked files or Git state" in root_contract
    assert "Set-Location 'C:\\path\\to\\existing\\Alpha-Research'" in onboarding
    assert "py -3.11 .\\scripts\\team_ai_workspace.py doctor" in onboarding
    assert "`bootstrap` is optional" in onboarding.lower()
    assert "team-command-policy.v1.json" in root_contract
    assert "layout adoption never justifies a duplicate clone" in normalized_root_contract


def test_command_policy_pins_better_to_narrow_control_plane_allowlist() -> None:
    policy = workspace._strict_json(ROOT / workspace.COMMAND_POLICY_REL)
    report = workspace.validate_command_policy(policy)

    assert report["status"] == "VALID", report
    assert report["better_default"] == "DENY"
    assert report["allowed_entrypoints"] == [
        "scripts/llm/ai_os/cli.py",
        "scripts/team_ai_workspace.py",
    ]

    mutations = []
    allow_all = copy.deepcopy(policy)
    allow_all["authority"]["default_script_execution"] = "ALLOW"
    mutations.append(allow_all)

    no_doctor = copy.deepcopy(policy)
    no_doctor["common_control_plane_allowlist"] = [
        entry
        for entry in no_doctor["common_control_plane_allowlist"]
        if entry["id"] != "TEAM_WORKSPACE_DOCTOR"
    ]
    mutations.append(no_doctor)

    duplicate_clone = copy.deepcopy(policy)
    duplicate_clone["workspace_adoption"]["duplicate_clone_for_layout_only"] = True
    mutations.append(duplicate_clone)

    better_runs_all = copy.deepcopy(policy)
    better_runs_all["roles"]["Better"]["default_script_execution"] = "TASK_SCOPED"
    mutations.append(better_runs_all)

    for mutation in mutations:
        assert workspace.validate_command_policy(mutation)["status"] == "INVALID"


def test_windows_codex_execution_denied_is_diagnostic_not_workspace_failure() -> None:
    with mock.patch.object(workspace.shutil, "which", return_value="C:/Codex/codex.exe"):
        with mock.patch.object(workspace, "_run", side_effect=PermissionError("denied")):
            tool = workspace._tool_version(["codex", "--version"], ROOT)

    assert tool == {
        "available": False,
        "command": "C:/Codex/codex.exe",
        "version": None,
        "reason": "EXECUTION_DENIED",
    }
    baseline = {"codex_required": True, "codex_version_enforcement": "WARN_ONLY"}
    assert workspace.codex_cli_finding(baseline, tool, True) == (
        "WARN",
        "CODEX_CLI_UNAVAILABLE",
    )

    hard = {"codex_required": True, "codex_version_enforcement": "REQUIRED"}
    assert workspace.codex_cli_finding(hard, tool, True) == (
        "FAIL",
        "CODEX_UNAVAILABLE",
    )

    invalid = {"codex_required": True, "codex_version_enforcement": "SILENT"}
    assert workspace.codex_cli_finding(invalid, tool, True) == (
        "FAIL",
        "CODEX_ENFORCEMENT_INVALID",
    )


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
    count = run_all_tests()
    print(f"ALL TEAM AI WORKSPACE TESTS PASS ({count} tests, 0 network calls)")
