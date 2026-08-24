#!/usr/bin/env python3
"""Machine checks for the frozen Research Closed Loop V1 assembly."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs/research/contracts/research_closed_loop.v1.json"
DOC_PATH = ROOT / "docs/research/RESEARCH_CLOSED_LOOP_V1.md"
TASK_PATH = ROOT / "scripts/llm/fixtures/research_closed_loop_v1.task.json"


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key: {key}")
        out[key] = value
    return out


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _validate(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected_top = {
        "schema", "schema_version", "method_version", "status", "frozen_at",
        "source_base", "ordered_blocks", "decision_denominator", "authority",
        "sample_policy", "legacy_order_policy", "production", "artifact_bindings",
        "disclaimer",
    }
    if set(manifest) != expected_top:
        errors.append("top-level contract surface changed")
    if manifest.get("schema") != "ar.research_closed_loop_manifest.v1":
        errors.append("schema changed")
    if manifest.get("schema_version") != "1.1":
        errors.append("manifest revision changed")
    if manifest.get("method_version") != "RESEARCH_CLOSED_LOOP_V1_1":
        errors.append("method version changed")
    if manifest.get("status") != "FROZEN_OFFLINE_WORKFLOW_DEBUG":
        errors.append("frozen status changed")
    if manifest.get("source_base") != {
        "assembly_code_commit": "af6a0175660176eccf1fc93a375dfa8e091c514a",
        "base_main": "a83a5d87cb660b579a295b3a2540977bf1f2f398",
        "review_pr": 306,
        "data_dependency_pr": 297,
        "data_dependency_status": "MERGED_MAIN",
    }:
        errors.append("merged data dependency changed")

    block_ids = [row.get("id") for row in manifest.get("ordered_blocks", [])]
    if block_ids != [
        "SCREENING", "U4_DECISION", "RESEARCH_REGISTRATION", "PAPER_EXECUTION",
        "OUTCOME_SCORING", "FIVE_AXIS_ATTRIBUTION", "METHOD_LEARNING",
    ]:
        errors.append("ordered block chain changed")
    for row in manifest.get("ordered_blocks", []):
        if set(row) != {"id", "stage", "purpose", "output", "honest_stop_states"}:
            errors.append(f"block surface changed: {row.get('id')}")
        if not row.get("honest_stop_states"):
            errors.append(f"block lost honest stop states: {row.get('id')}")

    denominator = manifest.get("decision_denominator", {})
    if denominator.get("required_decisions") != [
        "SELECT", "REJECT", "DEFER", "NO_TRADE", "DATA_BLOCKED"
    ]:
        errors.append("U4 decision denominator changed")
    if denominator.get("selected_count_allowed") != [0, 3, 4, 5]:
        errors.append("U4 selection count changed")
    if denominator.get("rejected_and_blocked_rows_retained") is not True:
        errors.append("rejected decisions no longer retained")

    authority = manifest.get("authority", {})
    if authority != {
        "u4_selection_authority": "HUMAN_JUNYAN_ONLY",
        "paper_registration_authority": "HUMAN_JUNYAN_ONLY",
        "production_authority": False,
        "trade_authority": False,
        "claim_allowed": False,
        "no_trade_flag": True,
    }:
        errors.append("authority boundary changed")

    policy = manifest.get("sample_policy", {})
    if not 5 <= policy.get("first_wave_min_cycles", -1) <= policy.get("first_wave_max_cycles", -1) <= 10:
        errors.append("first-wave cycle range changed")
    for key in (
        "first_wave_sample_eligible",
        "first_wave_method_claim_sample_eligible",
        "first_wave_portfolio_promotion_eligible",
    ):
        if policy.get(key) is not False:
            errors.append(f"workflow-debug eligibility changed: {key}")
    if policy.get("minimum_independent_clusters_for_method_claim") != 30:
        errors.append("independent-cluster threshold changed")
    if policy.get("independence_key") != "CAUSAL_CLUSTER_ID":
        errors.append("independence key changed")
    if policy.get("cross_industry_replication_required_for_portfolio") is not True:
        errors.append("cross-industry promotion gate changed")

    legacy = manifest.get("legacy_order_policy", {})
    if legacy != {
        "order_count": 5,
        "execution_evidence_status": "UNVERIFIED_SIMULATION",
        "sample_eligible": False,
        "method_claim_sample_eligible": False,
        "portfolio_promotion_eligible": False,
        "claim_allowed": False,
    }:
        errors.append("legacy-order claim boundary changed")

    production = manifest.get("production", {})
    if production != {
        "wired": False,
        "nightly_step_added": False,
        "runtime_state_written": False,
        "deployment_requires_separate_approval": True,
    }:
        errors.append("production boundary changed")
    if manifest.get("disclaimer") != "不是买卖指令；研究信号，human executes.":
        errors.append("disclaimer changed")
    return errors


class ResearchClosedLoopV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = _load(MANIFEST_PATH)

    def test_manifest_is_strict_and_frozen(self) -> None:
        self.assertEqual(_validate(self.manifest), [])

    def test_every_bound_artifact_matches_its_exact_bytes(self) -> None:
        rows = self.manifest["artifact_bindings"]
        paths = [row["path"] for row in rows]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertGreaterEqual(len(paths), 15)
        for row in rows:
            self.assertEqual(set(row), {"path", "sha256"})
            path = ROOT / row["path"]
            self.assertTrue(path.is_file(), row["path"])
            self.assertEqual(row["sha256"], _sha(path), row["path"])

    def test_revision_1_1_binds_the_semiconductor_screening_assembly(self) -> None:
        self.assertEqual(self.manifest["schema_version"], "1.1")
        self.assertEqual(self.manifest["method_version"], "RESEARCH_CLOSED_LOOP_V1_1")
        bound = {row["path"] for row in self.manifest["artifact_bindings"]}
        self.assertTrue({
            "docs/research/RESEARCH_CLOSED_LOOP_V1.md",
            "experiments/research_funnel/funnel_pipeline.py",
            "experiments/research_funnel/feature_store.py",
            "experiments/research_funnel/funnel_dag.py",
            "experiments/research_funnel/semiconductor_inputs.py",
            "experiments/research_funnel/industry_taxonomy.v1.json",
        }.issubset(bound))

    def test_authority_cannot_be_promoted(self) -> None:
        self.assertEqual(
            self.manifest["authority"],
            {
                "u4_selection_authority": "HUMAN_JUNYAN_ONLY",
                "paper_registration_authority": "HUMAN_JUNYAN_ONLY",
                "production_authority": False,
                "trade_authority": False,
                "claim_allowed": False,
                "no_trade_flag": True,
            },
        )
        for key, bad in (
            ("u4_selection_authority", "AUTOMATED_MODEL"),
            ("paper_registration_authority", "AUTOMATED_MODEL"),
            ("production_authority", True),
            ("trade_authority", True),
            ("claim_allowed", True),
            ("no_trade_flag", False),
        ):
            mutated = json.loads(json.dumps(self.manifest))
            mutated["authority"][key] = bad
            with self.subTest(key=key):
                self.assertIn("authority boundary changed", _validate(mutated))

    def test_workflow_debug_samples_cannot_enter_claims_or_portfolio(self) -> None:
        policy = self.manifest["sample_policy"]
        self.assertFalse(policy["first_wave_sample_eligible"])
        self.assertFalse(policy["first_wave_method_claim_sample_eligible"])
        self.assertFalse(policy["first_wave_portfolio_promotion_eligible"])
        for key in (
            "first_wave_sample_eligible",
            "first_wave_method_claim_sample_eligible",
            "first_wave_portfolio_promotion_eligible",
        ):
            mutated = json.loads(json.dumps(self.manifest))
            mutated["sample_policy"][key] = True
            with self.subTest(key=key):
                self.assertTrue(any("workflow-debug eligibility" in e for e in _validate(mutated)))

    def test_method_gate_requires_thirty_independent_clusters_and_replication(self) -> None:
        policy = self.manifest["sample_policy"]
        self.assertEqual(policy["minimum_independent_clusters_for_method_claim"], 30)
        self.assertEqual(policy["independence_key"], "CAUSAL_CLUSTER_ID")
        self.assertTrue(policy["cross_industry_replication_required_for_portfolio"])
        mutated = json.loads(json.dumps(self.manifest))
        mutated["sample_policy"]["minimum_independent_clusters_for_method_claim"] = 29
        self.assertIn("independent-cluster threshold changed", _validate(mutated))
        mutated = json.loads(json.dumps(self.manifest))
        mutated["sample_policy"]["cross_industry_replication_required_for_portfolio"] = False
        self.assertIn("cross-industry promotion gate changed", _validate(mutated))

    def test_reject_defer_no_trade_and_data_blocked_remain_in_denominator(self) -> None:
        denominator = self.manifest["decision_denominator"]
        self.assertEqual(
            denominator["required_decisions"],
            ["SELECT", "REJECT", "DEFER", "NO_TRADE", "DATA_BLOCKED"],
        )
        self.assertEqual(denominator["selected_count_allowed"], [0, 3, 4, 5])
        self.assertTrue(denominator["rejected_and_blocked_rows_retained"])
        mutated = json.loads(json.dumps(self.manifest))
        mutated["decision_denominator"]["required_decisions"] = ["SELECT"]
        self.assertIn("U4 decision denominator changed", _validate(mutated))
        mutated = json.loads(json.dumps(self.manifest))
        mutated["decision_denominator"]["rejected_and_blocked_rows_retained"] = False
        self.assertIn("rejected decisions no longer retained", _validate(mutated))

    def test_inherited_orders_are_factually_preserved_but_claim_ineligible(self) -> None:
        orders = _load(ROOT / "experiments/execution_tracker/model_fund/orders.json")
        self.assertEqual(len(orders), self.manifest["legacy_order_policy"]["order_count"])
        for order in orders:
            self.assertFalse(order["sample_eligible"])
            self.assertFalse(order["method_claim_sample_eligible"])
            self.assertFalse(order["portfolio_promotion_eligible"])
            self.assertFalse(order["claim_allowed"])
            self.assertEqual(order["execution_evidence_status"], "UNVERIFIED_SIMULATION")
            self.assertEqual(order["_migration"]["production_application_status"], "NOT_APPLIED_BY_THIS_PR")

    def test_task_scope_and_human_doc_match_the_frozen_boundary(self) -> None:
        task = _load(TASK_PATH)
        self.assertEqual(task["network_policy"], "OFFLINE")
        self.assertEqual(task["risk_level"], "CONSTITUTIONAL")
        text = DOC_PATH.read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        self.assertIn("Research Closed Loop V1.1", normalized)
        self.assertIn("FROZEN_OFFLINE_WORKFLOW_DEBUG / PRODUCTION_UNWIRED", normalized)
        self.assertIn("E1 red flags override every positive channel", normalized)
        self.assertIn("first five to ten semiconductor prospective cycles", normalized)
        self.assertIn("30 independent", normalized)
        self.assertIn("requires the method to reproduce across industries", normalized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
