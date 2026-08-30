#!/usr/bin/env python3
"""Offline checks for research go/no-go and fundamental screening contracts."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GO_NO_GO_DOC = ROOT / "docs/research/MODEL_PAPER_FUND_GO_NO_GO_TABLE_V0.md"
SCREEN_DOC = ROOT / "docs/research/FUNDAMENTAL_SCREENING_CONTRACT_V0.md"
SCREEN_CONTRACT = ROOT / "docs/research/contracts/fundamental_screening_contract.v0.json"
CI_PATH = ROOT / ".github/workflows/python-ci.yml"


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key: {key}")
        out[key] = value
    return out


def _load_contract() -> dict[str, Any]:
    return json.loads(SCREEN_CONTRACT.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)


class ResearchGoNoGoAndFundamentalScreeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.go_no_go = GO_NO_GO_DOC.read_text(encoding="utf-8")
        cls.screen_doc = SCREEN_DOC.read_text(encoding="utf-8")
        cls.contract = _load_contract()

    def test_go_no_go_table_keeps_paper_authority_closed(self) -> None:
        for phrase in (
            "DRAFT_OFFLINE_OPERATOR_TABLE / PAPER_ONLY / PRODUCTION_UNWIRED",
            "not a U4 decision",
            "not a paper order",
            "STOP_BEFORE_RERUN",
            "STOP_BEFORE_U4_REVIEW",
            "STOP_BEFORE_PAPER_REGISTRATION",
            "HUMAN_JUNYAN_ONLY",
            "PRODUCTION_AUTHORITY: false",
            "TRADE_AUTHORITY: false",
            "PAPER_ORDER_AUTHORITY: false",
            "NO_TRADE_FLAG: true",
        ):
            self.assertIn(phrase, self.go_no_go)

    def test_go_no_go_table_blocks_stale_or_legacy_display_sources(self) -> None:
        for phrase in (
            "last visible state is dated `20260806`",
            "stale for the next paper cycle",
            "public/data/model_portfolio.json",
            "model_action",
            "LONG",
            "SHORT",
            "WATCH_SHORT",
            "display state is `DATA_BLOCKED`",
        ):
            self.assertIn(phrase, self.go_no_go)

    def test_fundamental_contract_surface_is_closed_for_v0(self) -> None:
        self.assertEqual(
            set(self.contract),
            {
                "schema",
                "schema_version",
                "status",
                "purpose",
                "modes",
                "minimum_gates",
                "threshold_required_fields",
                "candidate_row_required_fields",
                "output_states",
                "cohort_buckets",
                "hard_stops",
                "authority",
                "non_goals",
                "disclaimer",
            },
        )
        self.assertEqual(self.contract["schema"], "ar.fundamental_screening_contract.v0")
        self.assertEqual(self.contract["status"], "DRAFT_OFFLINE_SCREENING_CONTRACT")

    def test_threshold_profile_requires_source_missing_behavior_and_reason(self) -> None:
        self.assertEqual(
            self.contract["threshold_required_fields"],
            [
                "threshold_id",
                "metric",
                "operator",
                "value",
                "unit",
                "lookback_window",
                "industry_adjustment",
                "source_ref",
                "missing_behavior",
                "reason",
            ],
        )

    def test_candidate_rows_preserve_explanations_gaps_and_sample_denominators(self) -> None:
        required = set(self.contract["candidate_row_required_fields"])
        self.assertTrue(
            {
                "why_in",
                "why_out",
                "positive_channels",
                "red_flag_channels",
                "missing_evidence",
                "method_version",
                "cohort_id",
                "causal_cluster_id",
                "data_status",
                "threshold_profile_ref",
                "no_trade_flag",
            }.issubset(required)
        )

    def test_output_states_are_research_intake_states_not_trade_actions(self) -> None:
        states = set(self.contract["output_states"])
        self.assertEqual(
            states,
            {
                "FUNDAMENTAL_RESEARCH_PASS",
                "FUNDAMENTAL_WATCH_WITH_GAP",
                "DATA_BLOCKED",
                "REJECT_RED_FLAG",
                "REJECT_QUALITY",
                "CONTROL_SAMPLE",
            },
        )
        forbidden = {"BUY", "SELL", "LONG", "SHORT", "WATCH_SHORT"}
        self.assertFalse(states & forbidden)

    def test_red_flags_missing_data_and_denominator_are_hard_stops(self) -> None:
        blockers = set(self.contract["hard_stops"])
        self.assertTrue(
            {
                "MISSING_FUNDAMENTAL_FILLED_AS_ZERO",
                "E1_RED_FLAG_CANNOT_BE_OFFSET",
                "WHY_IN_OR_WHY_OUT_MISSING",
                "DENOMINATOR_OMITS_REJECTED_BLOCKED_WATCH_OR_CONTROL",
                "SAMPLE_CLUSTER_FIELD_MISSING_WITHOUT_UNAVAILABLE_REASON",
                "AUTHORITY_ESCALATION",
            }.issubset(blockers)
        )

    def test_authority_boundary_matches_human_only_research_flow(self) -> None:
        self.assertEqual(
            self.contract["authority"],
            {
                "u4_selection_authority": "HUMAN_JUNYAN_ONLY",
                "paper_registration_authority": "HUMAN_JUNYAN_ONLY",
                "production_authority": False,
                "trade_authority": False,
                "paper_order_authority": False,
                "claim_allowed": False,
                "no_trade_flag": True,
            },
        )

    def test_human_doc_says_this_is_value_research_not_pure_quant_or_recommendation(self) -> None:
        normalized = " ".join(self.screen_doc.split())
        for phrase in (
            "value-investing workflow, not a purely quantitative stock picker",
            "all-A-share universe into explainable research cohorts",
            "Fundamental screening is one evidence channel",
            "cannot overwrite E1 red flags",
            "cannot force U4 to select any name",
            "Thresholds are explicit research assumptions",
            "No weighted total score may offset",
            "These states are research-intake states",
            "not `BUY`, `SELL`, `LONG`, or `SHORT`",
            "A strong fundamental row can still be `WAIT`",
        ):
            self.assertIn(phrase, normalized)

    def test_ci_runs_this_contract_test(self) -> None:
        ci = CI_PATH.read_text(encoding="utf-8")
        self.assertIn("python3 tests/test_research_go_no_go_and_fundamental_screening.py", ci)
        self.assertIn('"docs/research/**"', ci)


if __name__ == "__main__":
    unittest.main(verbosity=2)
