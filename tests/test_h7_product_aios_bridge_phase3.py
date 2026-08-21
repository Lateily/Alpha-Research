"""Offline tests for H7 Product-AIOS Bridge Phase 3."""

from __future__ import annotations

import json
import hashlib
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
BRIDGE_SCHEMA = (
    ROOT
    / "docs"
    / "contracts"
    / "product"
    / "h7-product-aios-bridge-phase3.v0.schema.json"
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
BRIDGE_TRACE_KEYS = {"schema", "trace_id", "resolved_trace_id_source", "stages"}
TRACE_STAGE_KEYS = {
    "stage",
    "artifact_id",
    "artifact_hash",
    "source_contract",
    "parent_artifact_hash",
    "receipt_id",
}
TRACE_SOURCE = "packet.user_input.request_id"
SOURCE_CONTRACTS = {
    "product_request": "h7-task-ux.v0:user_input",
    "ai_task_preview": "ai-task.v1",
    "agent_output_packet": "h7-task-ux.v0:projection",
    "human_review": "human-gate-receipt.v0-or-h7-task-ux.v0:human_review",
    "page_display": "h7-product-aios-bridge-phase3.case.v0",
}
HASH_PREFIX = "sha256:"
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


def _artifact_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return HASH_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _page_display_artifact(case: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "input_status": case["input_status"],
        "expected_tone": case["expected_tone"],
        "must_show": case["must_show"],
        "must_not_show_as_success": case["must_not_show_as_success"],
        "display_guards": case["display_guards"],
    }


def _expected_stage_hash(packet: Mapping[str, Any], case: Mapping[str, Any], stage: str) -> str:
    if stage == "product_request":
        return _artifact_hash(packet["user_input"])
    if stage == "ai_task_preview":
        return _artifact_hash(packet["task_manifest"])
    if stage == "agent_output_packet":
        return _artifact_hash(packet["projection"])
    if stage == "human_review":
        return _artifact_hash(packet["human_gate_receipt"] or packet["human_review"])
    if stage == "page_display":
        return _artifact_hash(_page_display_artifact(case))
    raise AssertionError(f"unexpected trace stage: {stage}")


class H7ProductAiosBridgePhase3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.phase1 = _load_json(PHASE1_FIXTURES)["fixtures"]
        cls.ui = _load_json(UI_FIXTURES)["view_model"]
        cls.bridge = _load_json(BRIDGE_FIXTURE)
        cls.schema = _load_json(BRIDGE_SCHEMA)

    def test_fixture_has_closed_world_schema(self) -> None:
        self.assertEqual(self.schema["title"], "H7 Product-AIOS Bridge Phase 3 Fixtures v0")
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(self.schema["properties"]["page"]["additionalProperties"], False)
        case_schema = self.schema["properties"]["acceptance_cases"]["items"]
        self.assertFalse(case_schema["additionalProperties"])

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
                trace = case["bridge_trace"]
                self.assertEqual(set(trace), BRIDGE_TRACE_KEYS)
                self.assertEqual(trace["schema"], "bridge-trace.v0")
                self.assertEqual(trace["trace_id"], packet["user_input"]["request_id"])
                self.assertEqual(trace["resolved_trace_id_source"], TRACE_SOURCE)
                self.assertEqual(
                    [stage["stage"] for stage in trace["stages"]],
                    TRACE_STAGES,
                )
                previous_hash = None
                for stage in trace["stages"]:
                    self.assertEqual(set(stage), TRACE_STAGE_KEYS)
                    stage_name = stage["stage"]
                    self.assertEqual(stage["source_contract"], SOURCE_CONTRACTS[stage_name])
                    self.assertEqual(
                        stage["artifact_hash"],
                        _expected_stage_hash(packet, case, stage_name),
                    )
                    self.assertEqual(stage["parent_artifact_hash"], previous_hash)
                    previous_hash = stage["artifact_hash"]
                human_stage = trace["stages"][3]
                receipt = packet["human_gate_receipt"]
                self.assertEqual(
                    human_stage["receipt_id"],
                    receipt["receipt_id"] if receipt else None,
                )

    def test_trace_rejects_packet_tampering(self) -> None:
        case = copy_case = dict(_case_by_status(self.bridge["acceptance_cases"])["COMPLETE"])
        packet = json.loads(json.dumps(self.phase1["COMPLETE"]))
        packet["projection"]["summary"] = "Tampered after trace was built."
        agent_stage = copy_case["bridge_trace"]["stages"][2]
        self.assertNotEqual(
            agent_stage["artifact_hash"],
            _expected_stage_hash(packet, copy_case, "agent_output_packet"),
        )

    def test_trace_source_is_closed_world(self) -> None:
        case = json.loads(json.dumps(self.bridge["acceptance_cases"][0]))
        case["bridge_trace"]["resolved_trace_id_source"] = "chat_history"
        self.assertNotEqual(case["bridge_trace"]["resolved_trace_id_source"], TRACE_SOURCE)

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
