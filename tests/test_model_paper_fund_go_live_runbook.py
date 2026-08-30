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
