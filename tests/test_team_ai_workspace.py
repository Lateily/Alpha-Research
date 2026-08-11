#!/usr/bin/env python3
"""Offline behavioral tests for the shared AR Team AI Workspace."""

from __future__ import annotations

import json
import copy
import datetime as dt
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
    assert report["status"] == "PASS_WITH_GAPS"
    assert report["skills"]["missing"] == []
    assert report["skills"]["invalid"] == []
    assert report["task_compiler"]["status"] == "SPEC_READY"
    assert report["task_compiler"]["task_id"] == "TEAM-EXAMPLE-001"
    assert report["command_policy"]["status"] == "VALID"
    assert report["sync_policy"]["status"] == "VALID"
    assert report["command_policy"]["final_approver"] == "Junyan"
    assert report["hygiene"]["tracked_secret_findings"] == []
    assert report["workspace_contract"]["missing"] == []
    assert workspace._strict_json(ROOT / workspace.CONFIG_REL)["runtime_baseline"][
        "codex_cli_requirement"
    ] == "TASK_DECLARED_ONLY"
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
    assert "LOCAL_WORKSPACE_CONTRACT_V2.md" in text
    assert "Final merge authority belongs to Junyan" in text


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
    contract = (ROOT / "docs/team/LOCAL_WORKSPACE_CONTRACT_V2.md").read_text(
        encoding="utf-8"
    )
    skill = (ROOT / ".agents/skills/ar-workspace-sync/SKILL.md").read_text(
        encoding="utf-8"
    )

    for domain in ("research", "macro", "aios", "product"):
        assert f"`{domain}/`" in contract
    assert "git worktree remove" in contract
    assert "pr-<number>-<short-slug>" in contract
    assert "READ_ONLY_LEGACY" in contract
    assert "one registered ACTIVE canonical clone" in contract
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
    assert payload["status"] == "PASS_WITH_GAPS"
    assert payload["profile"] == "ci"
    assert payload["evidence"]["network_refresh_performed"] is False
    assert report_after == report_before
    assert status_after == status_before


def test_onboarding_contract_reuses_existing_clone_and_defines_write_boundary() -> None:
    root_contract = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    onboarding = (ROOT / "docs/team/TEAM_AI_WORKSPACE_V2.md").read_text(encoding="utf-8")
    normalized_root_contract = " ".join(root_contract.split())

    assert "Reuse an existing valid clone" in root_contract
    assert "explicitly authorized control-plane check" in root_contract
    assert "does not modify tracked files or Git state" in root_contract
    assert "one active canonical clone" in onboarding
    assert "py -3.11 .\\scripts\\team_ai_workspace.py doctor" in onboarding
    assert "npm.cmd install -g @openai/codex" in onboarding
    assert "`bootstrap` is optional" in onboarding.lower()
    assert "PASS_WITH_GAPS" in onboarding
    assert "team-command-policy.v2.json" in root_contract
    assert "layout adoption never justifies a duplicate clone" in normalized_root_contract


def test_command_policy_preserves_task_autonomy_and_junyan_final_authority() -> None:
    policy = workspace._strict_json(ROOT / workspace.COMMAND_POLICY_REL)
    report = workspace.validate_command_policy(policy)

    assert report["status"] == "VALID", report
    assert report["better_default"] == "TASK_SCOPED"
    assert report["final_approver"] == "Junyan"
    assert report["task_scoped_roles"] == ["Better", "Jason", "Reed", "Simon"]
    assert report["allowed_entrypoints"] == [
        "scripts/llm/ai_os/cli.py",
        "scripts/team_ai_workspace.py",
    ]

    mutations = []
    allow_all = copy.deepcopy(policy)
    allow_all["authority"]["default_outside_declared_task"] = "ALLOW"
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

    no_owner = copy.deepcopy(policy)
    no_owner["authority"]["final_human_approver"] = "Agent"
    mutations.append(no_owner)

    agent_merge = copy.deepcopy(policy)
    agent_merge["authority"]["final_actions"].remove("MERGE_PR")
    mutations.append(agent_merge)

    better_blocked = copy.deepcopy(policy)
    better_blocked["roles"]["Better"]["default_script_execution"] = "DENY"
    mutations.append(better_blocked)

    for mutation in mutations:
        assert workspace.validate_command_policy(mutation)["status"] == "INVALID"


def test_windows_codex_execution_denied_is_gap_unless_cli_is_task_required() -> None:
    with mock.patch.object(workspace.shutil, "which", return_value="C:/Codex/codex.exe"):
        with mock.patch.object(workspace, "_run", side_effect=PermissionError("denied")):
            tool = workspace._tool_version(["codex", "--version"], ROOT)

    assert tool == {
        "available": False,
        "command": "C:/Codex/codex.exe",
        "version": None,
        "reason": "EXECUTION_DENIED",
    }
    assert workspace.codex_cli_finding(tool, True) == (
        "GAP",
        "CODEX_CLI_UNAVAILABLE",
    )

    assert workspace.codex_cli_finding(tool, True, cli_required=True) == (
        "FAIL",
        "CODEX_CLI_REQUIRED_UNAVAILABLE",
    )


def test_sync_policy_rejects_any_automation_takeover_of_final_authority() -> None:
    policy = workspace._strict_json(ROOT / workspace.SYNC_POLICY_REL)
    assert workspace.validate_sync_policy(policy)["status"] == "VALID"

    mutations = []
    for field in (
        "automation_may_merge",
        "automation_may_deploy_production",
        "automation_may_approve_methodology_or_capital_rules",
    ):
        mutation = copy.deepcopy(policy)
        mutation["authority"][field] = True
        mutations.append(mutation)
    wrong_owner = copy.deepcopy(policy)
    wrong_owner["authority"]["final_approver"] = "Simon"
    mutations.append(wrong_owner)
    fake_crypto = copy.deepcopy(policy)
    fake_crypto["workspace_registration"]["evidence_strength"] = "CRYPTOGRAPHIC"
    mutations.append(fake_crypto)

    assert all(
        workspace.validate_sync_policy(mutation)["status"] == "INVALID"
        for mutation in mutations
    )


def test_delivery_profile_fails_closed_without_identity_task_and_main_anchor() -> None:
    report = workspace.evaluate_workspace(ROOT, require_tools=False, profile="delivery")

    assert report["status"] == "FAIL"
    assert "WORKSPACE_REGISTRATION_REQUIRED" in report["failures"]
    assert "ACTIVE_TASK_REQUIRED" in report["failures"]
    assert "EXPECTED_MAIN_SHA_REQUIRED" in report["failures"]


def test_delivery_profile_requires_real_active_task() -> None:
    assert workspace.delivery_requires_active_task("UNBOUND", "REQUIRED")
    assert not workspace.delivery_requires_active_task("SPEC_READY", "REQUIRED")
    assert not workspace.delivery_requires_active_task("UNBOUND", "GAP_IF_MISSING")


def test_real_task_is_separate_from_compiler_smoke() -> None:
    report = workspace.evaluate_workspace(
        ROOT,
        require_tools=False,
        task_source="scripts/llm/fixtures/team_task_source.example.json",
    )

    assert report["task_compiler_smoke"]["task_id"] == "TEAM-EXAMPLE-001"
    assert report["active_task"]["status"] == "SPEC_READY"
    assert "ACTIVE_TASK_UNBOUND" not in report["gaps"]


def test_expected_main_sha_is_an_external_anchor_not_a_live_network_claim() -> None:
    observed = "1" * 40
    assert not workspace.expected_main_mismatch(observed, observed)
    assert workspace.expected_main_mismatch(observed, "0" * 40)

    policy = workspace._strict_json(ROOT / workspace.SYNC_POLICY_REL)
    assert policy["fact_source"]["offline_doctor_remote_claim"] == "LOCAL_ORIGIN_MAIN_ONLY"


def test_workspace_registration_records_junyan_reference_and_classifies_legacy_roots() -> None:
    policy = workspace._strict_json(ROOT / workspace.SYNC_POLICY_REL)
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "registration.json"
        payload = {
            "schema": "ar.local_workspace_registration.v1",
            "workspace_id": "reed-windows-primary",
            "member": "Reed",
            "machine_id": "reed-windows-01",
            "canonical_root": str(ROOT),
            "repository": "Lateily/Alpha-Research",
            "lifecycle": "ACTIVE",
            "registered_at": "2026-08-12T09:00:00+08:00",
            "approved_by": "Junyan",
            "approval_ref": "issue#workspace-approval",
            "evidence_strength": "TRANSCRIPT_REFERENCE_NOT_CRYPTOGRAPHIC",
            "legacy_roots": [
                {"path": "C:/old/Alpha-Research", "lifecycle": "READ_ONLY_LEGACY"}
            ],
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        report = workspace.inspect_workspace_registration(ROOT, policy, path)
        assert report["status"] == "REGISTERED_DECLARED", report

        payload["approved_by"] = "Agent"
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert workspace.inspect_workspace_registration(ROOT, policy, path)["status"] == "INVALID"

        payload["approved_by"] = "Junyan"
        payload["legacy_roots"][0]["lifecycle"] = "ACTIVE"
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert workspace.inspect_workspace_registration(ROOT, policy, path)["status"] == "INVALID"


def test_report_expiry_prevents_stale_status_from_becoming_current_fact() -> None:
    now = dt.datetime(2026, 8, 12, 12, tzinfo=dt.timezone.utc)
    fresh = {"evidence": {"expires_at": "2026-08-12T13:00:00+00:00"}}
    stale = {"evidence": {"expires_at": "2026-08-12T11:59:59+00:00"}}

    assert workspace.report_is_fresh(fresh, now)
    assert not workspace.report_is_fresh(stale, now)
    assert not workspace.report_is_fresh({}, now)


def test_known_missing_product_contracts_are_explicit_gaps_not_fake_passes() -> None:
    report = workspace.evaluate_workspace(ROOT, require_tools=False, profile="ci")
    missing = set(report["canonical_readiness"]["missing"])

    assert "ISSUE_158_AI_TASK" in missing
    assert "ISSUE_198_AI_TASK" in missing
    assert "MODEL_PORTFOLIO_STATE_SCHEMA" in missing
    assert "TRADE_CARDS_SCHEMA" in missing
    assert "SIMON_PLATFORM_ARCHITECTURE" in missing
    assert report["status"] == "PASS_WITH_GAPS"


def test_v1_contracts_are_only_compatibility_pointers() -> None:
    for name in ("TEAM_AI_WORKSPACE_V1.md", "LOCAL_WORKSPACE_CONTRACT_V1.md"):
        text = (ROOT / "docs/team" / name).read_text(encoding="utf-8")
        assert "Superseded" in text
        assert "Do not use this file as an independent authority source" in " ".join(text.split())


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
