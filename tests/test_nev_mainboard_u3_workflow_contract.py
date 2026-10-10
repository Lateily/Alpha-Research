#!/usr/bin/env python3
"""The live-data runner remains an isolated manual U3 artifact producer."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nev-mainboard-u3.yml"
BRIDGE = ROOT / ".github" / "workflows" / "fetch-data.yml"


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
        self.assertIn("AR_FUNNEL_EVENT_REVIEW_CODES: 600418.SH", text)
        self.assertIn("AR_U3_PIPELINE_COMPLETE", text)
        self.assertIn("funnel_dag.py candidates", text)
        self.assertIn("funnel_dag.py battery", text)
        self.assertIn("funnel_dag.py finalize", text)
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


if __name__ == "__main__":
    unittest.main()
