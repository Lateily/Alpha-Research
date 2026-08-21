"""Offline tests for H7 Product-AIOS Bridge Phase 3."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
PHASE1_FIXTURES = (
    ROOT
    / "docs"
    / "contracts"
    / "product"
    / "fixtures"
    / "h7-task-ux-fixtures.v0.json"
)
UI_FIXTURES = (
    ROOT
    / "docs"
    / "contracts"
    / "product"
    / "fixtures"
    / "h7-task-ux-ui-fixtures.v0.json"
)
BRIDGE_FIXTURE = (
    ROOT
    / "docs"
    / "contracts"
    / "product"
    / "fixtures"
    / "h7-product-aios-bridge-phase3.v0.json"
)

STATUSES = {
    "COMPLETE",
    "PARTIAL",
    "STALE",
    "BLOCKED",
    "ERROR",
    "AWAITING_HUMAN_REVIEW",
}
NON_COMPLETE = STATUSES - {"COMPLETE"}
REQUIRED_REGIONS = {
    "request_header",
    "task_preview",
    "run_projection",
    "evidence_table",
    "gap_panel",
    "human_review_dock",
    "audit_strip",
}
TRACE_STAGES = [
    "product_request",
    "ai_task_preview",
    "agent_output_packet",
    "human_review",
    "page_display",
]
FORBIDDEN_RUNTIME_ACTIONS = {
    "provider_model_call",
    "agent_execution",
    "router_request",
    "context_retrieval",
    "policy_decision",
    "github_write",
    "memory_write",
    "production_write",
    "final_merge_authorization",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _case_by_status(cases: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {case["input_status"]: case for case in cases}


class H7ProductAiosBridgePhase3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.phase1 = _load_json(PHASE1_FIXTURES)["fixtures"]
        cls.ui = _load_json(UI_FIXTURES)["view_model"]
        cls.bridge = _load_json(BRIDGE_FIXTURE)

    def test_page_contract_points_to_h7_contracts(self) -> None:
        page = self.bridge["page"]
        self.assertEqual(page["route"], "/aios/product-bridge")
        self.assertEqual(page["source_packet_schema"], "h7-task-ux.v0")
        self.assertEqual(page["ui_view_schema"], "h7-task-ux-ui.v0")
        self.assertIs(page["no_trade_flag"], True)

    def test_required_regions_are_exactly_declared(self) -> None:
        self.assertEqual(set(self.bridge["page"]["regions"]), REQUIRED_REGIONS)

    def test_trace_stage_order_is_declared(self) -> None:
        self.assertEqual(self.bridge["page"]["trace_stage_order"], TRACE_STAGES)

    def test_forbidden_runtime_actions_are_explicit(self) -> None:
        self.assertEqual(
            set(self.bridge["page"]["forbidden_runtime_actions"]),
            FORBIDDEN_RUNTIME_ACTIONS,
        )

    def test_acceptance_cases_cover_every_h7_status(self) -> None:
        statuses = {case["input_status"] for case in self.bridge["acceptance_cases"]}
        self.assertEqual(statuses, set(self.phase1))
        self.assertEqual(statuses, STATUSES)

    def test_non_complete_cases_cannot_be_success(self) -> None:
        cases = _case_by_status(self.bridge["acceptance_cases"])
        for status in NON_COMPLETE:
            with self.subTest(status=status):
                self.assertIs(cases[status]["must_not_show_as_success"], True)
                self.assertNotEqual(cases[status]["expected_tone"], "complete")
                self.assertIs(
                    cases[status]["display_guards"]["can_show_complete"],
                    False,
                )

    def test_every_case_binds_the_full_bridge_trace(self) -> None:
        for case in self.bridge["acceptance_cases"]:
            packet = self.phase1[case["input_status"]]
            with self.subTest(status=case["input_status"]):
                self.assertEqual(
                    case["trace_id"],
                    packet["user_input"]["request_id"],
                )
                self.assertEqual(case["required_trace_stages"], TRACE_STAGES)
                self.assertIn("user_input", packet)
                self.assertIn("projection", packet)
                self.assertIn("human_review", packet)

    def test_display_guards_cannot_grant_runtime_or_authority(self) -> None:
        for case in self.bridge["acceptance_cases"]:
            guards = case["display_guards"]
            with self.subTest(status=case["input_status"]):
                self.assertIs(guards["can_authorize_merge"], False)
                self.assertIs(guards["can_promote_memory"], False)
                self.assertIs(guards["must_preserve_untrusted_data"], True)

    def test_complete_case_still_keeps_junyan_authority_visible(self) -> None:
        complete = _case_by_status(self.bridge["acceptance_cases"])["COMPLETE"]
        self.assertIn("audit_strip", complete["must_show"])
        self.assertIs(complete["display_guards"]["can_show_complete"], True)
        complete_packet = self.phase1["COMPLETE"]
        self.assertEqual(
            complete_packet["human_review"]["final_merge_authority"],
            "Junyan",
        )
        self.assertIs(complete_packet["human_review"]["final_merge_authorized"], False)

    def test_bridge_cases_align_with_ui_tones(self) -> None:
        tones = {view["status"]: view["tone"] for view in self.ui["state_views"]}
        for case in self.bridge["acceptance_cases"]:
            with self.subTest(status=case["input_status"]):
                self.assertEqual(case["expected_tone"], tones[case["input_status"]])

    def test_blocked_case_has_no_runnable_manifest(self) -> None:
        blocked = _case_by_status(self.bridge["acceptance_cases"])["BLOCKED"]
        self.assertIn("task_manifest_null", blocked["must_show"])
        self.assertIsNone(self.phase1["BLOCKED"]["task_manifest"])

    def test_human_review_case_cannot_hide_missing_decision_ref(self) -> None:
        review = _case_by_status(self.bridge["acceptance_cases"])[
            "AWAITING_HUMAN_REVIEW"
        ]
        self.assertIn("decision_ref_null", review["must_show"])
        self.assertIsNone(
            self.phase1["AWAITING_HUMAN_REVIEW"]["human_review"]["decision_ref"]
        )

    def test_responsive_acceptance_covers_desktop_and_mobile(self) -> None:
        responsive = self.bridge["responsive_acceptance"]
        self.assertIn("desktop", responsive)
        self.assertIn("mobile_390", responsive)
        self.assertIn("evidence_columns_readable", responsive["desktop"])
        self.assertIn("no_horizontal_text_overflow", responsive["mobile_390"])


if __name__ == "__main__":
    unittest.main()
