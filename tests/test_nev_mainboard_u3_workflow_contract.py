#!/usr/bin/env python3
"""The live-data runner remains an isolated manual U3 artifact producer."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nev-mainboard-u3.yml"
BRIDGE = ROOT / ".github" / "workflows" / "fetch-data.yml"
TASK = ROOT / "scripts" / "llm" / "fixtures" / "nev_etf_mainboard_u3.task.json"


class WorkflowContractTests(unittest.TestCase):
    def test_workflow_is_manual_read_only_and_stops_at_u3(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("workflow_call:", text)
        self.assertNotIn("schedule:", text)
        self.assertIn("contents: read", text)
        self.assertIn("target_trade_date", text)
        self.assertIn("399976.SZ", text)
        self.assertIn("930997.CSI", text)
        self.assertIn("etf_mainboard_universe.py", text)
        self.assertIn("--source-output", text)
        self.assertIn("AR_FUNNEL_SCOPE_REGISTRY", text)
        self.assertIn("etf_mainboard_projection.py candidates", text)
        self.assertNotIn("AR_FUNNEL_EVENT_REVIEW_CODES", text)
        self.assertIn("AR_U3_PIPELINE_COMPLETE", text)
        self.assertNotIn("funnel_dag.py candidates", text)
        self.assertIn("funnel_dag.py battery", text)
        self.assertIn("funnel_dag.py finalize", text)
        self.assertIn("full-security-registry.json", text)
        self.assertIn("projection-receipt.json", text)
        self.assertIn("validate-artifact", text)
        self.assertIn("isolated-projection-manifest.json", text)
        self.assertIn('row.get("candidate_status") == "MAIN_CHANNEL"', text)
        self.assertIn("READY_FOR_HUMAN_U3_REVIEW", text)
        self.assertIn("REVIEW_ONLY_NO_POSITIVE_MAIN_CHANNEL", text)
        self.assertNotIn("READY_FOR_HUMAN_U3_SELECTION", text)
        self.assertIn("actions/upload-artifact", text)
        self.assertIn('"paper_registration": False', text)
        for forbidden in (
            "current_run.json", "model_fund", "paper_registration_bridge.py",
            "git push", "contents: write", "pull-requests: write",
        ):
            self.assertNotIn(forbidden, text)

    def test_existing_default_branch_workflow_is_a_dispatch_bridge_only(self) -> None:
        text = BRIDGE.read_text(encoding="utf-8")
        self.assertIn("nev_mainboard_u3", text)
        self.assertIn("uses: ./.github/workflows/nev-mainboard-u3.yml", text)
        self.assertIn("inputs.mode != 'nev_mainboard_u3'", text)
        self.assertIn("inputs.mode == 'nev_mainboard_u3'", text)
        self.assertIn("target_trade_date: ${{ inputs.target_trade_date }}", text)
        self.assertIn("contents: read", text)
        self.assertNotIn("secrets: inherit", text)
        self.assertIn("TUSHARE_TOKEN: ${{ secrets.TUSHARE_TOKEN }}", text)
        self.assertIn("isolated-nev-mainboard-u3", text)

    def test_ai_task_scope_matches_the_projection_implementation(self) -> None:
        task = json.loads(TASK.read_text(encoding="utf-8"))
        scope = set(task["file_scope"])
        self.assertIn("experiments/research_funnel/etf_mainboard_projection.py", scope)
        self.assertIn(".github/workflows/python-ci.yml", scope)
        self.assertNotIn("experiments/research_funnel/funnel_pipeline.py", scope)
        self.assertNotIn("experiments/research_funnel/funnel_dag.py", scope)


if __name__ == "__main__":
    unittest.main()
