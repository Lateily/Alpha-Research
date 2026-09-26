#!/usr/bin/env python3
"""Contract checks for the artifact-only isolated U0-U3 workflow mode."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "fetch-data.yml"


class IsolatedU3WorkflowContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_manual_mode_is_explicit_and_does_not_run_daily_refresh(self) -> None:
        self.assertIn("mode:", self.text)
        self.assertIn("isolated_u3", self.text)
        self.assertIn("target_trade_date:", self.text)
        self.assertIn("inputs.mode != 'isolated_u3'", self.text)

    def test_isolated_job_is_read_only_and_artifact_only(self) -> None:
        start = self.text.index("  isolated-u3:")
        isolated = self.text[start:]
        self.assertIn("permissions:\n      contents: read", isolated)
        self.assertIn("actions/upload-artifact@v7", isolated)
        self.assertNotIn("git push", isolated)
        self.assertNotIn("gh pr", isolated)

    def test_isolated_job_runs_the_frozen_u0_to_u3_chain(self) -> None:
        required = (
            "security_registry.py",
            "feature_store.py",
            "e1_event_layer.py",
            "rotation_panel.py",
            "funnel_dag.py candidates",
            "funnel_dag.py battery",
            "funnel_dag.py finalize",
            "SHA256SUMS",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_isolated_job_never_advances_human_or_execution_stages(self) -> None:
        start = self.text.index("  isolated-u3:")
        isolated = self.text[start:]
        forbidden = (
            "u4_decision_ledger.py",
            "paper_registration_bridge.py",
            "model_paper_fund.py",
            "current_run.json",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, isolated)


if __name__ == "__main__":
    unittest.main()
