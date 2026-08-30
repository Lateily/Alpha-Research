#!/usr/bin/env python3
"""Freeze the paper-fund go-live runbook's load-bearing boundaries."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "research" / "MODEL_PAPER_FUND_GO_LIVE_RUNBOOK_V0.md"


class ModelPaperFundGoLiveRunbookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = RUNBOOK.read_text(encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main()
