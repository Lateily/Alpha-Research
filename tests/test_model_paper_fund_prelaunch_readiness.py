#!/usr/bin/env python3
"""Freeze model-paper-fund prelaunch readiness artifacts."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "research"
FRONTEND_AUDIT = DOCS / "MODEL_PAPER_FUND_FRONTEND_DISPLAY_AUDIT_20260830.md"
DRY_RUN_DOC = DOCS / "MODEL_PAPER_FUND_DRY_RUN_20260830.md"
ACCEPTANCE_CHECKLIST = DOCS / "PR319_PR322_ACCEPTANCE_CHECKLIST_V0.md"
DRY_RUN_FIXTURE = DOCS / "fixtures" / "model_paper_fund_dry_run_v0.json"
LEGACY_MODEL_PORTFOLIO = ROOT / "public" / "data" / "model_portfolio.json"
V2_MODEL_PORTFOLIO_STATE = ROOT / "public" / "data" / "v2" / "model_portfolio_state.json"


class ModelPaperFundPrelaunchReadinessTests(unittest.TestCase):
    def test_frontend_audit_classifies_legacy_action_fields(self) -> None:
        audit = FRONTEND_AUDIT.read_text(encoding="utf-8")
        legacy = LEGACY_MODEL_PORTFOLIO.read_text(encoding="utf-8")
        v2_state_text = V2_MODEL_PORTFOLIO_STATE.read_text(encoding="utf-8")
        v2_state = json.loads(v2_state_text)

        if '"model_action"' in legacy:
            self.assertIn("LEGACY_RECOMMENDATION_LANGUAGE_PRESENT", audit)
            self.assertIn("Do not use `public/data/model_portfolio.json`", audit)

        self.assertTrue(v2_state["data"]["paper_only"])
        self.assertNotIn('"model_action"', v2_state_text)

    def test_dry_run_fixture_is_fake_paper_only_and_ordered(self) -> None:
        doc = DRY_RUN_DOC.read_text(encoding="utf-8")
        fixture = json.loads(DRY_RUN_FIXTURE.read_text(encoding="utf-8"))

        self.assertIn("OFFLINE_FIXTURE_ONLY", doc)
        self.assertFalse(fixture["security"]["is_real_security"])
        self.assertEqual(fixture["security"]["ticker"], "FAKE001.PAPER")

        authority = fixture["authority"]
        self.assertTrue(authority["paper_only"])
        self.assertTrue(authority["no_trade_flag"])
        self.assertFalse(authority["trade_authority"])
        self.assertFalse(authority["production_authority"])
        self.assertEqual(authority["u4_selection_authority"], "HUMAN_JUNYAN_ONLY")

        self.assertEqual(
            [stage["stage"] for stage in fixture["stages"]],
            ["U4_SELECT", "SEALED_CASE", "PAPER_REGISTRATION_PLAN", "PENDING_ORDER"],
        )
        self.assertEqual(fixture["stages"][0]["actor"], "Junyan")
        self.assertEqual(fixture["stages"][3]["order_status"], "PENDING_DRY_RUN")
        self.assertEqual(fixture["stages"][3]["ledger_write_mode"], "OFFLINE_FIXTURE_ONLY")

        plan_hash = fixture["paper_registration_plan"]["plan_hash"]
        self.assertRegex(plan_hash, r"^[0-9a-f]{64}$")
        self.assertEqual(plan_hash, fixture["stages"][2]["plan_hash"])

    def test_dry_run_fixture_contains_no_real_security_symbol(self) -> None:
        fixture_text = DRY_RUN_FIXTURE.read_text(encoding="utf-8")
        real_symbol_pattern = re.compile(r"\b(?:[036]\d{5}\.(?:SZ|SH)|\d{1,5}\.HK|[A-Z]{1,5}\.US)\b")
        self.assertIsNone(real_symbol_pattern.search(fixture_text))

    def test_pr319_pr322_checklist_keeps_gate_separation(self) -> None:
        text = ACCEPTANCE_CHECKLIST.read_text(encoding="utf-8")
        for token in (
            "#322 - U4 Pre-Decision Runtime",
            "#319 - Paper Registration Bridge",
            "must never make the U4 choice",
            "must never bypass Junyan",
            "PENDING",
            "STALE",
            "DATA_BLOCKED",
            "E1 red flags",
            "plan_hash",
            "paper_registration_intent",
            "paper_registration_commit",
            "no_trade_flag=true",
            "trade_authority=false",
            "production_authority=false",
        ):
            with self.subTest(token=token):
                self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
