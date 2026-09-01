#!/usr/bin/env python3
"""Offline checks for the research strategy quality upgrade plan."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs/research/RESEARCH_STRATEGY_QUALITY_UPGRADE_V0.md"
CONTRACT_PATH = ROOT / "docs/research/contracts/research_strategy_quality.v0.json"
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


class ResearchStrategyQualityUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = DOC_PATH.read_text(encoding="utf-8")
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
                "pipeline_order",
                "candidate_buckets",
                "fundamental_precision_fields",
                "timing_ticket_required_fields",
                "timing_statuses",
                "backtest_hygiene",
                "five_axis_learning",
                "sample_policy",
                "cluster_counting_rules",
                "pre_registration_failure_modes",
                "method_claim_gate",
                "authority",
                "hard_stops",
                "non_goals",
                "disclaimer",
            },
        )
        self.assertEqual(self.contract["schema"], "ar.research_strategy_quality_contract.v0")
        self.assertEqual(self.contract["status"], "DRAFT_OFFLINE_QUALITY_PLAN")

    def test_pipeline_order_keeps_fundamentals_timing_paper_and_attribution_separate(self) -> None:
        self.assertEqual(
            self.contract["pipeline_order"],
            [
                "U0_ELIGIBLE_UNIVERSE",
                "FUNDAMENTAL_THRESHOLD_PROFILE",
                "U1_INDEPENDENT_CHANNELS",
                "U2_BUCKETED_CANDIDATE_POOL",
                "U3_SIX_DIMENSION_BATTERY",
                "U4_HUMAN_JUNYAN_DECISION",
                "THESIS_VALUATION_WRONG_IF",
                "MANUAL_SMC_TIMING_TICKET",
                "PROSPECTIVE_PAPER_REGISTRATION",
                "PAPER_EXECUTION_A_SHARE_CONSTRAINTS",
                "T_PLUS_OBSERVATION",
                "FIVE_AXIS_ATTRIBUTION",
                "METHOD_KEEP_REVISE_KILL",
            ],
        )

    def test_candidate_buckets_keep_breadth_and_controls(self) -> None:
        self.assertEqual(
            self.contract["candidate_buckets"],
            [
                "A_FUNDAMENTAL_PASS_TIMING_NEAR",
                "B_FUNDAMENTAL_PASS_TIMING_WAIT",
                "C_REPAIR_OR_REVERSAL_WATCH",
                "D_CONTROL_OR_DENOMINATOR",
            ],
        )
        for bucket in self.contract["candidate_buckets"]:
            self.assertIn(bucket, self.doc)

    def test_fundamental_precision_preserves_why_gaps_and_sample_identity(self) -> None:
        self.assertEqual(
            self.contract["fundamental_precision_fields"],
            [
                "threshold_profile_ref",
                "why_in",
                "why_out",
                "missing_evidence",
                "method_version",
                "cohort_id",
                "causal_cluster_id",
            ],
        )
        for field in self.contract["fundamental_precision_fields"]:
            self.assertIn(f"`{field}`", self.doc)

    def test_timing_ticket_requires_wait_reason_and_pre_outcome_evidence(self) -> None:
        required = set(self.contract["timing_ticket_required_fields"])
        self.assertTrue(
            {
                "timing_method_version",
                "evidence_as_of",
                "setup_type",
                "entry_zone",
                "structure_invalidation",
                "structure_stop",
                "wait_reason",
            }.issubset(required)
        )
        self.assertEqual(self.contract["timing_statuses"], ["PASS", "WAIT", "DATA_BLOCKED"])
        self.assertIn("Timing can only say `PASS`, `WAIT`, or `DATA_BLOCKED`", self.doc)
        self.assertIn("A strong fundamental case with weak timing remains `WAIT`", self.normalized)

    def test_backtest_hygiene_blocks_future_leakage_and_unrealistic_execution(self) -> None:
        hygiene = set(self.contract["backtest_hygiene"])
        self.assertTrue(
            {
                "POINT_IN_TIME_SOURCES",
                "A_SHARE_T_PLUS_1_PRICE_LIMIT_LOT_COST_SLIPPAGE_VOLUME",
                "NO_SAME_DAY_FILL_AFTER_REGISTRATION",
                "RANDOM_AND_NON_PASS_CONTROLS",
                "FULL_DENOMINATOR_RETENTION",
                "CAUSAL_CLUSTER_INDEPENDENCE",
                "OVERFIT_COST_TURNOVER_SENSITIVITY",
            }.issubset(hygiene)
        )

    def test_five_axis_learning_keeps_pnl_from_rewriting_research(self) -> None:
        self.assertEqual(
            self.contract["five_axis_learning"],
            ["THESIS", "VALUATION", "TIMING", "EXECUTION", "MARKET_BETA"],
        )
        self.assertIn("P&L is recorded, but it cannot rewrite any axis", self.doc)

    def test_sample_policy_blocks_method_claims_before_30_clusters_and_cross_industry(self) -> None:
        self.assertEqual(
            self.contract["sample_policy"],
            {
                "first_semiconductor_cycles": "WORKFLOW_DEBUG_ONLY",
                "first_batch_size": "5_TO_10",
                "minimum_method_claim_clusters": 30,
                "requires_cross_industry_replication": True,
                "portfolio_promotion_allowed": False,
            },
        )

    def test_cluster_counting_rules_exclude_debug_cycles_from_method_claims(self) -> None:
        rules = self.contract["cluster_counting_rules"]
        for rule in (
            "count closed samples by causal_cluster_id, not ticker rows",
            "exclude WORKFLOW_DEBUG_ONLY cycles from minimum_method_claim_clusters",
            "DATA_BLOCKED and NO_TRADE rows remain in the denominator but cannot be counted as method-success samples",
            "method claims require at least 30 independent closed causal clusters and cross-industry replication",
        ):
            self.assertIn(rule, rules)

        for phrase in (
            "Method quality is counted by independent causal clusters, not raw ticker rows",
            "The first 5-10 semiconductor cycles test the process and do not count toward the 30-cluster method threshold",
            "Exclude those workflow-debug cycles from the 30-cluster method denominator",
        ):
            self.assertIn(phrase, self.normalized)

    def test_pre_registration_failure_modes_are_explicit_before_paper_review(self) -> None:
        self.assertEqual(
            self.contract["pre_registration_failure_modes"],
            [
                "THESIS_NOT_SEALED",
                "VALUATION_RANGE_NOT_SEALED",
                "WRONG_IF_NOT_SEALED",
                "TIMING_TICKET_NOT_PRE_OUTCOME",
                "MANUAL_SMC_STATUS_NOT_PASS",
                "ACTIVE_E1_RED_FLAG",
                "SOURCE_DATA_BLOCKED",
                "U4_SELECT_MISSING_OR_UNTRUSTED",
                "PLAN_HASH_UNBOUND",
                "AUTHORITY_ESCALATION",
            ],
        )
        for mode in self.contract["pre_registration_failure_modes"]:
            self.assertIn(mode, self.doc)

    def test_method_claim_gate_blocks_alpha_profitability_and_promotion_claims(self) -> None:
        gate = self.contract["method_claim_gate"]
        self.assertEqual(gate["claim_status_before_threshold"], "METHOD_CLAIM_BLOCKED")
        self.assertEqual(gate["minimum_independent_closed_clusters"], 30)
        self.assertFalse(gate["workflow_debug_counts_toward_threshold"])
        self.assertTrue(gate["requires_cross_industry_replication"])
        self.assertTrue(gate["requires_pre_registered_failure_modes"])
        self.assertEqual(
            gate["allowed_claims_before_threshold"],
            [
                "workflow_debug_observation",
                "process_quality_issue",
                "data_gap_report",
            ],
        )
        self.assertEqual(
            gate["blocked_claims_before_threshold"],
            [
                "alpha_claim",
                "profitability_claim",
                "method_validity_claim",
                "portfolio_promotion_claim",
            ],
        )
        self.assertIn("METHOD_CLAIM_BELOW_30_INDEPENDENT_CLUSTERS", self.contract["hard_stops"])
        self.assertIn("Blocked claims before that threshold", self.doc)
        self.assertIn("a method claim is made below 30 independent closed causal clusters", self.doc)

    def test_authority_and_non_goals_cannot_claim_trade_or_paper_power(self) -> None:
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

    def test_doc_explains_value_research_quality_not_ui_or_auto_trading(self) -> None:
        for phrase in (
            "better research precision before it needs more UI",
            "The goal is a better research production line, not an automatic stock picker",
            "Thresholds are explicit research assumptions",
            "It is not allowed to mutate silently",
            "Backtests must measure whether a rule had information before the outcome",
            "The next product value is not a prettier page",
            "Not trading advice; research signal, human executes.",
        ):
            self.assertIn(phrase, self.normalized)

    def test_ci_runs_this_contract_test(self) -> None:
        ci = CI_PATH.read_text(encoding="utf-8")
        self.assertIn("python3 tests/test_research_strategy_quality_upgrade.py", ci)
        self.assertIn('"docs/research/**"', ci)


if __name__ == "__main__":
    unittest.main(verbosity=2)
