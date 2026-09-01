#!/usr/bin/env python3
"""Offline checks for the model paper observation template."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs/research/MODEL_PAPER_OBSERVATION_TEMPLATE_V0.md"
DRY_RUN_PATH = ROOT / "docs/research/prospective/MODEL_PAPER_OBSERVATION_DRY_RUN_FAKE001_20260901.md"
CONTRACT_PATH = ROOT / "docs/research/contracts/model_paper_observation.v0.json"
CI_PATH = ROOT / ".github/workflows/python-ci.yml"


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key: {key}")
        out[key] = value
    return out


def _load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)


class ModelPaperObservationTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = DOC_PATH.read_text(encoding="utf-8")
        cls.dry_run = DRY_RUN_PATH.read_text(encoding="utf-8")
        cls.normalized = " ".join(cls.doc.split())
        cls.contract = _load_contract()

    def test_contract_surface_is_closed_for_v0(self) -> None:
        self.assertEqual(
            set(self.contract),
            {
                "schema",
                "schema_version",
                "status",
                "purpose",
                "applies_after",
                "case_header_required_fields",
                "observation_horizons",
                "daily_observation_required_fields",
                "axis_statuses",
                "source_statuses",
                "observation_statuses",
                "intraday_note_required_fields",
                "sample_policy",
                "authority",
                "hard_stops",
                "non_goals",
                "disclaimer",
            },
        )
        self.assertEqual(self.contract["schema"], "ar.model_paper_observation_contract.v0")
        self.assertEqual(self.contract["status"], "DRAFT_OFFLINE_OBSERVATION_TEMPLATE")

    def test_template_binds_the_four_required_observation_horizons(self) -> None:
        self.assertEqual(
            self.contract["observation_horizons"],
            ["T_PLUS_1", "T_PLUS_3", "T_PLUS_5", "T_PLUS_10"],
        )
        for label in ("T+1", "T+3", "T+5", "T+10"):
            self.assertIn(label, self.doc)

    def test_case_header_preserves_u4_plan_sample_and_authority_identity(self) -> None:
        required = set(self.contract["case_header_required_fields"])
        self.assertTrue(
            {
                "u4_decision_ref",
                "u4_decision_hash",
                "sealed_case_hash",
                "paper_registration_plan_hash",
                "paper_order_ref",
                "method_version",
                "cohort_id",
                "causal_cluster_id",
                "sample_purpose",
                "sample_eligible",
                "method_claim_sample_eligible",
                "portfolio_promotion_eligible",
                "no_trade_flag",
            }.issubset(required)
        )
        for phrase in (
            "SAMPLE_PURPOSE: WORKFLOW_DEBUG_ONLY",
            "SAMPLE_ELIGIBLE: false",
            "METHOD_CLAIM_SAMPLE_ELIGIBLE: false",
            "PORTFOLIO_PROMOTION_ELIGIBLE: false",
            "NO_TRADE_FLAG: true",
            "TRADE_AUTHORITY: false",
            "PAPER_ORDER_AUTHORITY: false",
        ):
            self.assertIn(phrase, self.doc)

    def test_daily_rows_keep_pnl_separate_from_five_research_axes(self) -> None:
        required = set(self.contract["daily_observation_required_fields"])
        self.assertTrue(
            {
                "paper_return_pct",
                "thesis_axis_status",
                "valuation_axis_status",
                "timing_axis_status",
                "execution_axis_status",
                "market_beta_axis_status",
                "source_status",
                "observation_status",
            }.issubset(required)
        )
        self.assertEqual(
            self.contract["axis_statuses"],
            ["PASS", "FAIL", "MIXED", "WAIT", "DATA_BLOCKED"],
        )
        self.assertIn("P&L is recorded, but it cannot rewrite any axis", self.doc)

    def test_intraday_notes_cannot_create_official_fills_or_samples(self) -> None:
        self.assertIn("Intraday watching is allowed only as a note stream", self.doc)
        self.assertIn(
            "It cannot create a fill, official sample, official return, or method claim",
            self.normalized,
        )
        self.assertIn("INTRADAY_USED_AS_OFFICIAL_SAMPLE", self.contract["hard_stops"])

    def test_sample_policy_blocks_method_claims_and_portfolio_promotion(self) -> None:
        self.assertEqual(
            self.contract["sample_policy"],
            {
                "first_semiconductor_cycles": "WORKFLOW_DEBUG_ONLY",
                "first_batch_size": "5_TO_10",
                "minimum_method_claim_clusters": 30,
                "workflow_debug_counts_toward_threshold": False,
                "requires_cross_industry_replication": True,
                "portfolio_promotion_allowed": False,
            },
        )
        self.assertIn("they do not count toward method validity", self.doc)

    def test_authority_and_non_goals_remain_closed(self) -> None:
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
        forbidden = {"BUY", "SELL", "LONG", "SHORT", "WATCH_SHORT"}
        self.assertFalse(set(self.contract["observation_statuses"]) & forbidden)
        self.assertTrue(
            {
                "stock_recommendation",
                "automatic_security_selection",
                "paper_order_creation",
                "real_trade_execution",
                "alpha_claim",
                "profitability_claim",
                "portfolio_construction",
            }.issubset(set(self.contract["non_goals"]))
        )

    def test_stop_conditions_cover_hash_data_level_mutation_and_authority_escalation(self) -> None:
        stops = set(self.contract["hard_stops"])
        self.assertTrue(
            {
                "U4_DECISION_MISSING_OR_NOT_JUNYAN_AUTHORED",
                "PAPER_PLAN_HASH_MISSING_OR_UNMATCHED",
                "SETTLED_BAR_MISSING_OR_UNHASHED",
                "ADJUSTED_OR_STALE_BAR_USED_AS_RAW_SETTLED_BAR",
                "POST_REGISTRATION_LEVEL_MUTATION",
                "CORPORATE_ACTION_BREAK_UNRESOLVED",
                "PNL_REWRITES_RESEARCH_AXIS",
                "AUTHORITY_ESCALATION",
            }.issubset(stops)
        )

    def test_dry_run_fixture_is_fake_paper_only_and_non_authoritative(self) -> None:
        dry_run_normalized = " ".join(self.dry_run.split())
        self.assertIn("FAKE001.PAPER", self.dry_run)
        self.assertIn("DRY_RUN_ONLY_NOT_JUNYAN_DECISION", self.dry_run)
        self.assertIn("STOP_BEFORE_OBSERVATION", self.dry_run)
        for label in ("T_PLUS_1", "T_PLUS_3", "T_PLUS_5", "T_PLUS_10"):
            self.assertIn(label, self.dry_run)
        for phrase in (
            "no real security",
            "no real price",
            "no real U4 decision",
            "no production data",
            "SAMPLE_ELIGIBLE: false",
            "METHOD_CLAIM_SAMPLE_ELIGIBLE: false",
            "PORTFOLIO_PROMOTION_ELIGIBLE: false",
            "NO_TRADE_FLAG: true",
            "TRADE_AUTHORITY: false",
            "PAPER_ORDER_AUTHORITY: false",
        ):
            self.assertIn(phrase, dry_run_normalized)

    def test_ci_runs_this_contract_test(self) -> None:
        ci = CI_PATH.read_text(encoding="utf-8")
        self.assertIn("python3 tests/test_model_paper_observation_template.py", ci)
        self.assertIn('"docs/research/**"', ci)


if __name__ == "__main__":
    unittest.main(verbosity=2)
