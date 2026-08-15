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


def receipt(**overrides: object) -> gate.TestReceipt:
    payload: dict[str, object] = {
        "schema": "ar-governance-test-receipt.v1",
        "target": gate.MUTATIONS[0].expected_failure_marker,
        "kind": "method",
        "class_name": "SyntheticTests",
        "tests_run": 1,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "expected_failures": 0,
        "unexpected_successes": 0,
        "diagnostics": {
            "failures": [],
            "errors": [],
            "skipped": [],
            "expected_failures": [],
            "unexpected_successes": [],
        },
    }
    payload.update(overrides)
    if "diagnostics" not in overrides:
        payload["diagnostics"] = {
            field: [f"synthetic {field}"] * int(payload[field])
            for field in (
                "failures",
                "errors",
                "skipped",
                "expected_failures",
                "unexpected_successes",
            )
        }
    return gate.TestReceipt(**payload)  # type: ignore[arg-type]


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
            (root / "test_source.py").write_text(
                "def synthetic():\n"
                "    return None\n",
                encoding="utf-8",
            )
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
            (root / "test_source.py").write_text(
                "def synthetic():\n"
                "    return None\n",
                encoding="utf-8",
            )
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

    def test_validate_manifest_enforces_funnel_marker_coverage(self) -> None:
        case = gate.MutationCase(
            mutation_id="FUNNEL_SYNTHETIC_GATE",
            component="Research funnel synthetic",
            source_path="source.py",
            test_script="test_source.py",
            before="guard = True",
            after="guard = False",
            expected_failure_marker="synthetic",
            rationale="Synthetic case used to prove funnel marker coverage is load-bearing.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "source.py").write_text("guard = True\n", encoding="utf-8")
            (root / "test_source.py").write_text(
                "def synthetic():\n    pass\n",
                encoding="utf-8",
            )
            for relative in (*gate.K1_GOVERNANCE_PATHS, *gate.R043_GOVERNANCE_PATHS):
                marker_path = root / relative
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                marker_path.write_text("# no markers\n", encoding="utf-8")
            for relative in gate.FUNNEL_GOVERNANCE_PATHS:
                marker_path = root / relative
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                marker_path.write_text("# missing marker\n", encoding="utf-8")
            with self.assertRaisesRegex(
                gate.MutationGateError,
                "mutations_without_markers.*FUNNEL_SYNTHETIC_GATE",
            ):
                gate.validate_manifest(root, [case])

    def test_validate_manifest_enforces_funnel_nightly_marker_coverage(self) -> None:
        """夜链接入的治理规则同样必须带 marker,而且按 ID 前缀配对。

        前缀配对是必要的:run_nightly.py 同时承载 Macro 的 marker,按文件精确配对
        会把不相干的治理族卷进来判成漂移。
        """
        case = gate.MutationCase(
            mutation_id="FUNNEL_NIGHTLY_SYNTHETIC_GATE",
            component="Nightly funnel wiring synthetic",
            source_path="source.py",
            test_script="test_source.py",
            before="guard = True",
            after="guard = False",
            expected_failure_marker="synthetic",
            rationale="Synthetic case used to prove nightly marker coverage is load-bearing.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "source.py").write_text("guard = True\n", encoding="utf-8")
            (root / "test_source.py").write_text(
                "def synthetic():\n    pass\n",
                encoding="utf-8",
            )
            for relative in (
                *gate.K1_GOVERNANCE_PATHS,
                *gate.R043_GOVERNANCE_PATHS,
                *gate.FUNNEL_GOVERNANCE_PATHS,
            ):
                marker_path = root / relative
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                marker_path.write_text("# no markers\n", encoding="utf-8")
            for relative in gate.FUNNEL_NIGHTLY_GOVERNANCE_PATHS:
                marker_path = root / relative
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                # 同文件里放一个别的治理族的 marker:它不得被这条规则判成漂移。
                marker_path.write_text(
                    "# governance-mutation: MACRO_M1C_FAILURE_ISOLATION\n",
                    encoding="utf-8",
                )
            with self.assertRaisesRegex(
                gate.MutationGateError,
                "funnel nightly governance marker drift.*"
                "mutations_without_markers.*FUNNEL_NIGHTLY_SYNTHETIC_GATE",
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
            gate.classify_mutation(
                case,
                gate.CommandResult(0, "all green", receipt=receipt()),
            )

    def test_infrastructure_error_is_not_accepted_as_a_kill(self) -> None:
        case = gate.MUTATIONS[0]
        with self.assertRaisesRegex(gate.MutationGateError, "only assertion failures"):
            gate.classify_mutation(
                case,
                gate.CommandResult(
                    1,
                    "Traceback\nPermissionError: network disabled",
                    receipt=receipt(
                        errors=1,
                        diagnostics={
                            "failures": [],
                            "errors": ["PermissionError: network disabled"],
                            "skipped": [],
                            "expected_failures": [],
                            "unexpected_successes": [],
                        },
                    ),
                ),
            )

    def test_behavioral_assertion_failure_is_a_valid_kill(self) -> None:
        gate.classify_mutation(
            gate.MUTATIONS[0],
            gate.CommandResult(
                1,
                "",
                receipt=receipt(
                    failures=1,
                    diagnostics={
                        "failures": ["AssertionError: gate not raised"],
                        "errors": [],
                        "skipped": [],
                        "expected_failures": [],
                        "unexpected_successes": [],
                    },
                ),
            ),
        )

    def test_receipt_for_a_different_target_is_not_accepted_as_a_kill(self) -> None:
        with self.assertRaisesRegex(gate.MutationGateError, "target mismatch"):
            gate.classify_mutation(
                gate.MUTATIONS[0],
                gate.CommandResult(
                    1,
                    "",
                    receipt=receipt(target="test_something_else", failures=1),
                ),
            )

    def test_default_target_is_the_declared_failure_marker(self) -> None:
        case = gate.MUTATIONS[0]
        self.assertEqual(case.expected_failure_marker, gate._target_test(case))

    def test_single_test_runner_does_not_execute_unrelated_testcase_method(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guard = root / "guard"
            script = root / "test_exact.py"
            script.write_text(
                "import unittest\n"
                "class ExactTests(unittest.TestCase):\n"
                "    def test_target(self):\n"
                "        self.assertTrue(True)\n"
                "    def test_unrelated(self):\n"
                "        self.fail('must not run')\n",
                encoding="utf-8",
            )
            gate._write_network_guard(guard)
            result = gate.run_test_script(root, guard, "test_exact.py", "test_target")
        self.assertEqual(0, result.returncode, result.output)
        self.assertIsNotNone(result.receipt)
        assert result.receipt is not None
        self.assertEqual("test_target", result.receipt.target)
        self.assertEqual(1, result.receipt.tests_run)
        self.assertNotIn("test_unrelated", result.output)

    def test_manifest_rejects_imported_and_ambiguous_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            imported = root / "test_imported.py"
            imported.write_text(
                "from helper import test_target\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(gate.MutationGateError, "found 0"):
                gate._local_test_target(imported, "test_target")

            ambiguous = root / "test_ambiguous.py"
            ambiguous.write_text(
                "import unittest\n"
                "def test_target():\n"
                "    return None\n"
                "class DuplicateTests(unittest.TestCase):\n"
                "    def test_target(self):\n"
                "        return None\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(gate.MutationGateError, "found 2"):
                gate._local_test_target(ambiguous, "test_target")

    def test_runner_rejects_imported_target_identity(self) -> None:
        fixtures = {
            "function": (
                "from helper import imported_function\n"
                "def test_target():\n"
                "    return None\n"
                "test_target = imported_function\n"
            ),
            "class": (
                "from helper import ImportedTests as ForeignTests\n"
                "class LocalTests(unittest.TestCase):\n"
                "    def test_target(self):\n"
                "        self.assertTrue(True)\n"
                "LocalTests = ForeignTests\n"
            ),
            "method": (
                "from helper import imported_target\n"
                "class LocalTests(unittest.TestCase):\n"
                "    def test_target(self):\n"
                "        self.assertTrue(True)\n"
                "LocalTests.test_target = imported_target\n"
            ),
        }
        for label, body in fixtures.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                guard = root / "guard"
                (root / "helper.py").write_text(
                    "import unittest\n"
                    "def imported_function():\n"
                    "    return None\n"
                    "def imported_target(self):\n"
                    "    self.assertTrue(True)\n"
                    "class ImportedTests(unittest.TestCase):\n"
                    "    def test_target(self):\n"
                    "        self.assertTrue(True)\n",
                    encoding="utf-8",
                )
                script = root / "test_imported.py"
                script.write_text("import unittest\n" + body, encoding="utf-8")
                gate._write_network_guard(guard)
                result = gate.run_test_script(root, guard, "test_imported.py", "test_target")
                self.assertNotEqual(0, result.returncode)
                self.assertIsNone(result.receipt)
                self.assertIn("changed identity", result.output)

    def test_runner_receipt_separates_assertion_failure_error_and_skip(self) -> None:
        cases = {
            "assertion": (
                "self.fail('behavioral failure')",
                {"failures": 1, "errors": 0, "skipped": 0},
            ),
            "error": (
                "raise PermissionError('network disabled')",
                {"failures": 0, "errors": 1, "skipped": 0},
            ),
            "skip": (
                "self.skipTest('not executed')",
                {"failures": 0, "errors": 0, "skipped": 1},
            ),
        }
        for label, (statement, expected) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                guard = root / "guard"
                (root / "test_receipt.py").write_text(
                    "import unittest\n"
                    "class ReceiptTests(unittest.TestCase):\n"
                    "    def test_target(self):\n"
                    f"        {statement}\n",
                    encoding="utf-8",
                )
                gate._write_network_guard(guard)
                result = gate.run_test_script(root, guard, "test_receipt.py", "test_target")
                self.assertIsNotNone(result.receipt)
                assert result.receipt is not None
                self.assertEqual(expected["failures"], result.receipt.failures)
                self.assertEqual(expected["errors"], result.receipt.errors)
                self.assertEqual(expected["skipped"], result.receipt.skipped)

    def test_classifier_rejects_error_and_skip_receipts(self) -> None:
        case = gate.MUTATIONS[0]
        for invalid in (
            receipt(errors=1),
            receipt(failures=1, errors=1),
            receipt(skipped=1),
            receipt(expected_failures=1),
            receipt(unexpected_successes=1),
        ):
            with self.subTest(receipt=invalid), self.assertRaisesRegex(
                gate.MutationGateError,
                "only assertion failures",
            ):
                gate.classify_mutation(case, gate.CommandResult(1, "", receipt=invalid))

    def test_baseline_requires_one_clean_pass(self) -> None:
        for invalid in (
            receipt(skipped=1),
            receipt(errors=1),
            receipt(expected_failures=1),
            receipt(unexpected_successes=1),
        ):
            with self.subTest(receipt=invalid), self.assertRaisesRegex(
                gate.MutationGateError,
                "one clean pass",
            ):
                gate.validate_baseline_result(
                    "test_source.py",
                    invalid.target,
                    gate.CommandResult(0, "", receipt=invalid),
                )

    def test_gate_does_not_credit_an_unrelated_failure(self) -> None:
        case = gate.MutationCase(
            mutation_id="SYNTHETIC_EXACT_ATTRIBUTION",
            component="synthetic exact attribution",
            source_path="source.py",
            test_script="test_source.py",
            before="GUARD = True",
            after="GUARD = False",
            expected_failure_marker="test_declared_target",
            rationale="An unrelated failure cannot be credited to the declared target.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "source.py").write_text("GUARD = True\n", encoding="utf-8")
            (root / "test_source.py").write_text(
                "import unittest\n"
                "import source\n"
                "class AttributionTests(unittest.TestCase):\n"
                "    def test_declared_target(self):\n"
                "        self.assertTrue(True)\n"
                "    def test_unrelated(self):\n"
                "        self.assertTrue(source.GUARD)\n",
                encoding="utf-8",
            )
            for relative in (
                *gate.K1_GOVERNANCE_PATHS,
                *gate.R043_GOVERNANCE_PATHS,
                *gate.FUNNEL_GOVERNANCE_PATHS,
                *gate.FUNNEL_NIGHTLY_GOVERNANCE_PATHS,
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# no governance markers in synthetic fixture\n", encoding="utf-8")
            with self.assertRaisesRegex(gate.MutationGateError, "SURVIVED"):
                gate.run_gate(root, [case])

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
