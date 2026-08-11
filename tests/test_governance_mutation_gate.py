"""Selftests for the deterministic governance mutation runner."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import governance_mutation_gate as gate  # noqa: E402


class GovernanceMutationGateTests(unittest.TestCase):
    def test_production_manifest_has_unique_live_anchors(self) -> None:
        gate.validate_manifest(REPO_ROOT, gate.MUTATIONS)
        self.assertGreaterEqual(len(gate.MUTATIONS), 16)

    def test_validate_manifest_enforces_k1_marker_coverage(self) -> None:
        case = gate.MutationCase(
            mutation_id="AIOS_K1_SYNTHETIC_GATE",
            component="AIOS K1 synthetic",
            source_path="source.py",
            test_script="test_source.py",
            before="guard = True",
            after="guard = False",
            expected_failure_marker="synthetic",
            rationale="Synthetic case used to prove marker coverage is load-bearing.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "source.py").write_text("guard = True\n", encoding="utf-8")
            (root / "test_source.py").write_text("# fixture\n", encoding="utf-8")
            for relative in gate.K1_GOVERNANCE_PATHS:
                marker_path = root / relative
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                marker_path.write_text("# missing marker\n", encoding="utf-8")
            with self.assertRaisesRegex(
                gate.MutationGateError,
                "mutations_without_markers.*AIOS_K1_SYNTHETIC_GATE",
            ):
                gate.validate_manifest(root, [case])

    def test_validate_manifest_enforces_r043_marker_coverage(self) -> None:
        case = gate.MutationCase(
            mutation_id="R043_SYNTHETIC_GATE",
            component="R-043 publication migration synthetic",
            source_path="source.py",
            test_script="test_source.py",
            before="guard = True",
            after="guard = False",
            expected_failure_marker="synthetic",
            rationale="Synthetic case used to prove R-043 marker coverage is load-bearing.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "source.py").write_text("guard = True\n", encoding="utf-8")
            (root / "test_source.py").write_text("# fixture\n", encoding="utf-8")
            for relative in gate.K1_GOVERNANCE_PATHS:
                marker_path = root / relative
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                marker_path.write_text("# no K1 markers\n", encoding="utf-8")
            for relative in gate.R043_GOVERNANCE_PATHS:
                marker_path = root / relative
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                marker_path.write_text("# missing marker\n", encoding="utf-8")
            with self.assertRaisesRegex(
                gate.MutationGateError,
                "mutations_without_markers.*R043_SYNTHETIC_GATE",
            ):
                gate.validate_manifest(root, [case])

    def test_validate_manifest_enforces_workspace_marker_coverage(self) -> None:
        case = gate.MutationCase(
            mutation_id="TEAM_SYNTHETIC_GATE",
            component="Team Workspace synthetic",
            source_path="source.py",
            test_script="test_source.py",
            before="guard = True",
            after="guard = False",
            expected_failure_marker="synthetic",
            rationale="Synthetic case used to prove workspace marker coverage is load-bearing.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "source.py").write_text("guard = True\n", encoding="utf-8")
            (root / "test_source.py").write_text("# fixture\n", encoding="utf-8")
            for relative in (
                *gate.K1_GOVERNANCE_PATHS,
                *gate.R043_GOVERNANCE_PATHS,
                *gate.WORKSPACE_GOVERNANCE_PATHS,
            ):
                marker_path = root / relative
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                marker_path.write_text("# missing marker\n", encoding="utf-8")
            with self.assertRaisesRegex(
                gate.MutationGateError,
                "mutations_without_markers.*TEAM_SYNTHETIC_GATE",
            ):
                gate.validate_manifest(root, [case])

    def test_k1_marker_coverage_rejects_missing_or_orphaned_mutations(self) -> None:
        k1_case = next(
            case for case in gate.MUTATIONS if case.component.startswith("AIOS K1")
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "k1.py"
            source.write_text("# no marker\n", encoding="utf-8")
            with self.assertRaisesRegex(gate.MutationGateError, "mutations_without_markers"):
                gate.validate_k1_marker_coverage(root, [k1_case], ("k1.py",))

            source.write_text(
                "# governance-mutation: AIOS_K1_ORPHAN_GATE\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(gate.MutationGateError, "markers_without_mutations"):
                gate.validate_k1_marker_coverage(root, [k1_case], ("k1.py",))

    def test_k1_marker_coverage_rejects_duplicate_markers(self) -> None:
        k1_case = next(
            case for case in gate.MUTATIONS if case.component.startswith("AIOS K1")
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "k1.py"
            marker = f"# governance-mutation: {k1_case.mutation_id}\n"
            source.write_text(marker + marker, encoding="utf-8")
            with self.assertRaisesRegex(gate.MutationGateError, "duplicate K1 governance marker"):
                gate.validate_k1_marker_coverage(root, [k1_case], ("k1.py",))

    def test_r043_marker_coverage_rejects_missing_or_orphaned_mutations(self) -> None:
        r043_case = next(
            case
            for case in gate.MUTATIONS
            if case.component.startswith("R-043 publication migration")
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "r043.py"
            source.write_text("# no marker\n", encoding="utf-8")
            with self.assertRaisesRegex(gate.MutationGateError, "mutations_without_markers"):
                gate.validate_r043_marker_coverage(root, [r043_case], ("r043.py",))

            source.write_text(
                "# governance-mutation: R043_ORPHAN_GATE\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(gate.MutationGateError, "markers_without_mutations"):
                gate.validate_r043_marker_coverage(root, [r043_case], ("r043.py",))

    def test_exact_replace_rejects_missing_and_duplicate_anchors(self) -> None:
        with self.assertRaisesRegex(gate.MutationGateError, "found 0"):
            gate.replace_exact("clean", "guard", "pass", "MISSING")
        with self.assertRaisesRegex(gate.MutationGateError, "found 2"):
            gate.replace_exact("guard guard", "guard", "pass", "DUPLICATE")

    def test_surviving_mutation_is_a_failure(self) -> None:
        case = gate.MUTATIONS[0]
        with self.assertRaisesRegex(gate.MutationGateError, "SURVIVED"):
            gate.classify_mutation(case, gate.CommandResult(0, "all green"))

    def test_infrastructure_error_is_not_accepted_as_a_kill(self) -> None:
        case = gate.MUTATIONS[0]
        with self.assertRaisesRegex(gate.MutationGateError, "infrastructure"):
            gate.classify_mutation(
                case,
                gate.CommandResult(1, "Traceback\nModuleNotFoundError: missing"),
            )

    def test_behavioral_assertion_failure_is_a_valid_kill(self) -> None:
        marker = gate.MUTATIONS[0].expected_failure_marker
        gate.classify_mutation(
            gate.MUTATIONS[0],
            gate.CommandResult(
                1,
                f"FAIL: {marker}\nFAILED (failures=1)\nAssertionError: gate not raised",
            ),
        )

    def test_unrelated_failure_is_not_accepted_as_a_kill(self) -> None:
        with self.assertRaisesRegex(gate.MutationGateError, "wrong test failed"):
            gate.classify_mutation(
                gate.MUTATIONS[0],
                gate.CommandResult(
                    1,
                    "FAIL: test_something_else\nFAILED (failures=1)\nAssertionError",
                ),
            )

    def test_paths_cannot_escape_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(gate.MutationGateError, "escapes repository"):
                gate._resolved_under(root, "../outside.py")

    def test_generated_sitecustomize_blocks_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guard = root / "guard"
            gate._write_network_guard(guard)
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    "import socket; socket.create_connection(('127.0.0.1', 9))",
                ],
                cwd=root,
                env=gate._subprocess_env(root, guard),
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("network disabled by governance mutation gate", result.stderr)

    def test_child_environment_strips_secret_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict(
                os.environ,
                {
                    "MOONSHOT_API_KEY": "must-not-leak",
                    "GITHUB_TOKEN": "must-not-leak",
                    "SAFE_VALUE": "kept",
                },
                clear=True,
            ):
                environment = gate._subprocess_env(root, root / "guard")
        self.assertNotIn("MOONSHOT_API_KEY", environment)
        self.assertNotIn("GITHUB_TOKEN", environment)
        self.assertEqual("kept", environment["SAFE_VALUE"])
        self.assertEqual("1", environment["AR_OFFLINE"])


if __name__ == "__main__":
    unittest.main()
