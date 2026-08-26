#!/usr/bin/env python3
"""Offline checks for the Research Quality Scorecard V0 contract."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs/research/contracts/research_quality_scorecard.v0.json"
DOC_PATH = ROOT / "docs/research/RESEARCH_QUALITY_SCORECARD_V0.md"

EXPECTED_AXES = [
    "FACT_COMPLETENESS",
    "VARIANT_THESIS",
    "FALSIFIABILITY",
    "VALUATION_DISCIPLINE",
    "TIMING_REGISTRATION",
    "REVIEWABILITY",
]


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key: {key}")
        out[key] = value
    return out


def _load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)


class ResearchQualityScorecardContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = _load_contract()

    def test_contract_surface_is_closed_for_v0(self) -> None:
        self.assertEqual(
            set(self.contract),
            {
                "schema",
                "schema_version",
                "status",
                "purpose",
                "applies_to",
                "quality_axes",
                "gate",
                "hard_blockers",
                "authority",
                "non_inputs",
                "disclaimer",
            },
        )
        self.assertEqual(self.contract["schema"], "ar.research_quality_scorecard_contract.v0")
        self.assertEqual(self.contract["schema_version"], "0.1")
        self.assertEqual(self.contract["status"], "DRAFT_OFFLINE_QUALITY_GATE")

    def test_axes_are_ordered_complete_and_evidence_bearing(self) -> None:
        axes = self.contract["quality_axes"]
        self.assertEqual([axis["id"] for axis in axes], EXPECTED_AXES)
        for axis in axes:
            with self.subTest(axis=axis["id"]):
                self.assertEqual(set(axis), {"id", "question", "required_evidence"})
                self.assertIsInstance(axis["question"], str)
                self.assertGreaterEqual(len(axis["required_evidence"]), 4)
                self.assertTrue(all(isinstance(item, str) and item for item in axis["required_evidence"]))

    def test_doc_promised_evidence_terms_are_machine_readable(self) -> None:
        by_axis = {
            axis["id"]: set(axis["required_evidence"])
            for axis in self.contract["quality_axes"]
        }
        self.assertIn("issuer_or_exchange_facts", by_axis["FACT_COMPLETENESS"])
        self.assertIn("invalidation_reference", by_axis["TIMING_REGISTRATION"])
        self.assertIn("reviewer_notes", by_axis["REVIEWABILITY"])

    def test_quality_pass_gate_and_honest_stop_states_are_fixed(self) -> None:
        gate = self.contract["gate"]
        self.assertEqual(gate["quality_pass_average_min"], 70)
        self.assertEqual(gate["quality_pass_axis_min"], 50)
        self.assertEqual(
            gate["statuses"],
            ["QUALITY_PASS", "REVISE_REQUIRED", "DATA_BLOCKED", "KILL"],
        )
        self.assertEqual(
            gate["next_states"],
            [
                "READY_FOR_HUMAN_REVIEW",
                "REVISE_BEFORE_REVIEW",
                "WAIT_FOR_DATA",
                "STOP_DO_NOT_USE",
            ],
        )

    def test_hard_blockers_cover_research_self_deception_paths(self) -> None:
        blockers = set(self.contract["hard_blockers"])
        self.assertTrue(
            {
                "E1_RED_FLAG_SUPPRESSED",
                "MISSING_DATA_FILLED",
                "NO_WRONG_IF",
                "TIMING_AFTER_OUTCOME",
                "PNL_REWRITES_RESEARCH_QUALITY",
                "DENOMINATOR_OMITS_REJECTED_OR_BLOCKED",
                "AUTHORITY_ESCALATION",
            }.issubset(blockers)
        )

    def test_authority_boundary_cannot_claim_selection_or_trading_power(self) -> None:
        self.assertEqual(
            self.contract["authority"],
            {
                "u4_selection_authority": "HUMAN_JUNYAN_ONLY",
                "paper_registration_authority": "HUMAN_JUNYAN_ONLY",
                "production_authority": False,
                "trade_authority": False,
                "claim_allowed": False,
                "no_trade_flag": True,
            },
        )

    def test_pnl_and_future_price_path_are_not_score_inputs(self) -> None:
        self.assertEqual(
            self.contract["non_inputs"],
            ["paper_pnl", "future_price_path", "real_trade_execution", "portfolio_weight"],
        )
        doc = DOC_PATH.read_text(encoding="utf-8")
        normalized = " ".join(doc.split())
        self.assertIn("Paper P&L is not an input to this quality score", doc)
        self.assertIn("A profitable case can still have a weak or wrong thesis", normalized)

    def test_human_document_matches_contract_boundary(self) -> None:
        doc = DOC_PATH.read_text(encoding="utf-8")
        normalized = " ".join(doc.split())
        for axis in EXPECTED_AXES:
            self.assertIn(axis, doc)
        self.assertIn("DRAFT_OFFLINE_QUALITY_GATE / PRODUCTION_UNWIRED", normalized)
        self.assertIn("Junyan remains the authority", normalized)
        self.assertIn("not investment correctness, paper P&L, alpha, or trade readiness", normalized)
        self.assertIn("不是买卖指令；研究信号，human executes.", doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
