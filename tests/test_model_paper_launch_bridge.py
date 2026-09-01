#!/usr/bin/env python3
"""Readiness checks for the model paper fund launch bridge note."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/research/prospective/MODEL_PAPER_FUND_LAUNCH_BRIDGE_20260901.md"
SAFE_STATE = ROOT / "public/data/v2/model_portfolio_state.json"
LEGACY_STATE = ROOT / "public/data/model_portfolio.json"


class ModelPaperLaunchBridgeTests(unittest.TestCase):
    def test_bridge_names_safe_and_legacy_frontend_sources(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("public/data/v2/model_portfolio_state.json", text)
        self.assertIn("public/data/model_portfolio.json", text)
        self.assertIn("must not use this legacy pilot file", text)
        self.assertIn("Forbidden display language", text)

    def test_safe_frontend_source_is_paper_state_not_model_action_feed(self) -> None:
        state = json.loads(SAFE_STATE.read_text(encoding="utf-8"))
        legacy = json.loads(LEGACY_STATE.read_text(encoding="utf-8"))

        self.assertTrue(state["data"]["paper_only"])
        self.assertNotIn("candidates", state["data"])
        self.assertNotIn("model_action", json.dumps(state, ensure_ascii=False))

        legacy_text = json.dumps(legacy, ensure_ascii=False)
        self.assertIn("model_action", legacy_text)
        self.assertRegex(legacy_text, r"\b(LONG|SHORT|WATCH_SHORT)\b")

    def test_bridge_keeps_registration_stopped_until_required_gates_land(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("STOP_BEFORE_PAPER_REGISTRATION", text)
        self.assertIn("#319 is not merged", text)
        self.assertIn("#324 is not merged", text)
        self.assertIn("Junyan has not committed a U4 `SELECT`", text)
        self.assertIn("NO_TRADE_FLAG: true", text)
        self.assertIn("TRADE_AUTHORITY: false", text)
        self.assertIn("PRODUCTION_AUTHORITY: false", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
