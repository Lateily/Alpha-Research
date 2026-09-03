#!/usr/bin/env python3
"""Freeze the paper-fund go-live runbook's load-bearing boundaries."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "research" / "MODEL_PAPER_FUND_GO_LIVE_RUNBOOK_V0.md"
INTRADAY_TEMPLATE = ROOT / "docs" / "research" / "MODEL_PAPER_FUND_INTRADAY_OBSERVATION_TEMPLATE_V0.md"
POST_CLOSE_TEMPLATE = ROOT / "docs" / "research" / "MODEL_PAPER_FUND_POST_CLOSE_REPORT_TEMPLATE_V0.md"


class ModelPaperFundGoLiveRunbookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = RUNBOOK.read_text(encoding="utf-8")
        self.intraday_text = INTRADAY_TEMPLATE.read_text(encoding="utf-8")
        self.post_close_text = POST_CLOSE_TEMPLATE.read_text(encoding="utf-8")

    def test_runbook_keeps_paper_only_authority_boundary(self) -> None:
        for token in (
            "PAPER_ONLY",
            "no_trade_flag=true",
            "trade_authority=false",
            "production_authority=false",
            "Junyan",
            "STOP_BEFORE_PAPER_REGISTRATION",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_runbook_keeps_registration_bridge_sequence(self) -> None:
        for token in (
            "committed U4 SELECT",
            "deterministic plan",
            "plan_hash",
            "paper_registration_intent",
            "paper_registration_commit",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_runbook_freezes_paper_admission_required_fields(self) -> None:
        for token in (
            "Paper Admission Acceptance Gate",
            "`ticker`",
            "`target_trade_date`",
            "`u4_decision_ref`",
            "`u4_decision_actor`",
            "`u4_decision`",
            "`source_packet_ref`",
            "`source_packet_hash`",
            "`evidence_hash`",
            "`method_version`",
            "`cohort_id`",
            "`causal_cluster_id`",
            "`thesis_hash`",
            "`valuation_hash`",
            "`wrong_if`",
            "`manual_smc_hash`",
            "`timing_state`",
            "`entry_zone`",
            "`structure_stop`",
            "`fund_snapshot_hash`",
            "`paper_registration_plan_hash`",
            "`human_approval_ref`",
            "`observation_schedule`",
            "`paper_only`",
            "`no_trade_flag`",
            "`trade_authority`",
            "`production_authority`",
            "`sample_eligible`",
            "`method_claim_sample_eligible`",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_runbook_freezes_paper_admission_stop_conditions(self) -> None:
        for token in (
            "not by Junyan",
            "not `SELECT`",
            "stale, pending, missing, or not hash-bound",
            "active E1 red flag",
            "unsealed",
            "`timing_state` is `WAIT` or `DATA_BLOCKED`",
            "after seeing the target price path",
            "model text, chat text",
            "full `paper_registration_plan_hash`",
            "fund snapshot is missing, stale, or not hash-bound",
            "outside the reviewed bridge",
            "`T+1`, `T+3`, `T+5`, or `T+10`",
            "method-validity samples",
            "STOP_BEFORE_PAPER_REGISTRATION",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_runbook_keeps_t_checkpoint_observation_schedule(self) -> None:
        for token in ("T+1", "T+3", "T+5", "T+10", "DATA_BLOCKED"):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_runbook_keeps_forbidden_intraday_outputs(self) -> None:
        for token in (
            "official fills",
            "official exits",
            "official NAV",
            "moving a stop looser",
            "rewriting the original thesis",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_runbook_links_daily_operator_templates(self) -> None:
        for token in (
            "MODEL_PAPER_FUND_INTRADAY_OBSERVATION_TEMPLATE_V0.md",
            "MODEL_PAPER_FUND_POST_CLOSE_REPORT_TEMPLATE_V0.md",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_intraday_template_blocks_official_accounting(self) -> None:
        for token in (
            "INTRADAY_OBSERVATION_ONLY",
            "paper_only=true",
            "no_trade_flag=true",
            "trade_authority=false",
            "production_authority=false",
            "official_fill_status=null",
            "official_exit_status=null",
            "official_nav_status=null",
            "WAIT_FOR_SETTLED_BAR",
            "QUESTION_FOR_JUNYAN",
            "DATA_BLOCKED",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.intraday_text)

    def test_post_close_template_requires_settled_engine_outputs(self) -> None:
        for token in (
            "POST_CLOSE_REPORT",
            "SETTLED_BAR_REQUIRED",
            "settled_bar_status",
            "official NAV only when all required marks are complete",
            "position_review",
            "court_10d",
            "watch_dynamic",
            "T+1",
            "T+3",
            "T+5",
            "T+10",
            "DATA_BLOCKED",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.post_close_text)

    def test_daily_templates_keep_paper_only_authority_boundary(self) -> None:
        for path, text in (
            (INTRADAY_TEMPLATE, self.intraday_text),
            (POST_CLOSE_TEMPLATE, self.post_close_text),
        ):
            with self.subTest(path=path.name):
                self.assertIn("paper_only=true", text)
                self.assertIn("no_trade_flag=true", text)
                self.assertIn("trade_authority=false", text)
                self.assertIn("production_authority=false", text)


if __name__ == "__main__":
    unittest.main()
