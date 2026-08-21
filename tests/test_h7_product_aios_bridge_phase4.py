"""Offline tests for the H7 Product-AIOS Bridge Phase 4 UI handoff."""

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
PHASE4_FIXTURE = (
    ROOT
    / "docs"
    / "contracts"
    / "product"
    / "fixtures"
    / "h7-product-aios-bridge-phase4.v0.json"
)
PHASE4_SCHEMA = (
    ROOT
    / "docs"
    / "contracts"
    / "product"
    / "h7-product-aios-bridge-phase4.v0.schema.json"
)

STATUSES = {
    "COMPLETE",
    "PARTIAL",
    "STALE",
    "BLOCKED",
    "ERROR",
    "AWAITING_HUMAN_REVIEW",
}
COMPONENTS = {
    "BridgeShell",
    "RequestHeader",
    "TaskPreviewPanel",
    "RunProjectionPanel",
    "EvidenceTable",
    "GapPanel",
    "HumanReviewDock",
    "AuditStrip",
}
ALLOWED_ACTIONS = {
    "EDIT_REQUEST",
    "REQUEST_CONTEXT_REFRESH",
    "REQUEST_HUMAN_REVIEW",
    "VIEW_EVIDENCE",
    "COPY_TASK_ID",
}
FORBIDDEN_ACTIONS = {
    "RUN_AGENT",
    "APPROVE_OUTPUT",
    "PROMOTE_MEMORY",
    "AUTHORIZE_MERGE",
    "WRITE_GITHUB_COMMENT",
    "CALL_PROVIDER",
}
RUNTIME_CONNECTIONS = {
    "model_provider",
    "router",
    "context",
    "policy",
    "scheduler",
    "executor",
    "github_write",
    "memory_write",
    "production_write",
}
TRACE_STAGES = [
    "product_request",
    "ai_task_preview",
    "agent_output_packet",
    "human_review",
    "page_display",
]
TRACE_BIND_SOURCES = {
    "packet.user_input",
    "packet.task_manifest",
    "packet.projection",
    "packet.human_review",
    "view_model.state_views",
}
FORBIDDEN_TRACE_SOURCES = {
    "chat_history",
    "raw_model_text",
    "browser_local_storage",
    "unreviewed_external_instructions",
}
AUDIT_STRIP_PROPS = {
    "traceId",
    "noTradeFlag",
    "externalContentTrust",
    "finalMergeAuthority",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _state_map(items: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {item["status"]: item for item in items}


class H7ProductAiosBridgePhase4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.phase1 = _load_json(PHASE1_FIXTURES)["fixtures"]
        cls.fixture = _load_json(PHASE4_FIXTURE)
        cls.schema = _load_json(PHASE4_SCHEMA)

    def test_fixture_has_closed_world_schema(self) -> None:
        self.assertEqual(self.schema["title"], "H7 Product-AIOS Bridge Phase 4 UI Handoff v0")
        self.assertFalse(self.schema["additionalProperties"])
        self.assertFalse(self.schema["properties"]["page"]["additionalProperties"])
        state_schema = self.schema["properties"]["state_component_map"]["items"]
        self.assertFalse(state_schema["additionalProperties"])

    def test_page_is_fixture_only_and_no_trade(self) -> None:
        page = self.fixture["page"]
        self.assertEqual(page["route"], "/aios/product-bridge")
        self.assertEqual(page["mode"], "fixture_only")
        self.assertIs(page["no_trade_flag"], True)

    def test_component_inventory_is_explicit(self) -> None:
        components = {item["id"] for item in self.fixture["page"]["components"]}
        self.assertEqual(components, COMPONENTS)
        for component in self.fixture["page"]["components"]:
            with self.subTest(component=component["id"]):
                self.assertTrue(component["responsibility"])
                self.assertTrue(component["required_props"])

    def test_bridge_shell_and_audit_strip_receive_trace_props(self) -> None:
        components = {
            item["id"]: set(item["required_props"])
            for item in self.fixture["page"]["components"]
        }
        self.assertIn("bridgeTrace", components["BridgeShell"])
        self.assertEqual(components["AuditStrip"], AUDIT_STRIP_PROPS)

    def test_audit_strip_security_props_are_load_bearing(self) -> None:
        components = {
            item["id"]: set(item["required_props"])
            for item in self.fixture["page"]["components"]
        }
        for prop in AUDIT_STRIP_PROPS:
            with self.subTest(prop=prop):
                mutated = set(components["AuditStrip"])
                mutated.remove(prop)
                self.assertNotEqual(mutated, AUDIT_STRIP_PROPS)

    def test_bridge_trace_is_bound_to_contract_sources_only(self) -> None:
        trace = self.fixture["page"]["bridge_trace"]
        self.assertEqual(trace["trace_id_source"], "packet.user_input.request_id")
        self.assertEqual(trace["resolved_trace_id_source"], "packet.user_input.request_id")
        self.assertEqual(trace["stage_order"], TRACE_STAGES)
        self.assertEqual(set(trace["must_bind_sources"]), TRACE_BIND_SOURCES)
        self.assertEqual(set(trace["must_not_bind_sources"]), FORBIDDEN_TRACE_SOURCES)
        self.assertTrue(
            set(trace["must_bind_sources"]).isdisjoint(trace["must_not_bind_sources"])
        )

    def test_forbidden_trace_source_cannot_be_resolved(self) -> None:
        trace = dict(self.fixture["page"]["bridge_trace"])
        for source in FORBIDDEN_TRACE_SOURCES:
            with self.subTest(source=source):
                trace["resolved_trace_id_source"] = source
                self.assertNotEqual(
                    trace["resolved_trace_id_source"],
                    "packet.user_input.request_id",
                )

    def test_actions_are_allowlisted_and_forbidden_actions_are_visible(self) -> None:
        page = self.fixture["page"]
        self.assertEqual(set(page["allowed_actions"]), ALLOWED_ACTIONS)
        self.assertEqual(set(page["forbidden_actions"]), FORBIDDEN_ACTIONS)
        self.assertTrue(ALLOWED_ACTIONS.isdisjoint(FORBIDDEN_ACTIONS))

    def test_no_runtime_connections_are_enabled(self) -> None:
        connections = self.fixture["page"]["runtime_connections"]
        self.assertEqual(set(connections), RUNTIME_CONNECTIONS)
        self.assertTrue(all(value is False for value in connections.values()))

    def test_state_map_covers_phase1_statuses(self) -> None:
        mapped = {item["status"] for item in self.fixture["state_component_map"]}
        self.assertEqual(mapped, set(self.phase1))
        self.assertEqual(mapped, STATUSES)

    def test_every_state_renders_audit_strip(self) -> None:
        for item in self.fixture["state_component_map"]:
            with self.subTest(status=item["status"]):
                self.assertIn("AuditStrip", item["required_components"])
                self.assertIn("trace_id", item["must_show_fields"])

    def test_non_complete_states_keep_reason_fields_visible(self) -> None:
        required = {
            "PARTIAL": "missing_evidence",
            "STALE": "data_cutoff",
            "BLOCKED": "blocking_reasons",
            "ERROR": "error_code",
            "AWAITING_HUMAN_REVIEW": "decision_ref_null",
        }
        mapped = _state_map(self.fixture["state_component_map"])
        for status, field in required.items():
            with self.subTest(status=status):
                self.assertIn(field, mapped[status]["must_show_fields"])

    def test_blocked_state_does_not_require_task_preview(self) -> None:
        blocked = _state_map(self.fixture["state_component_map"])["BLOCKED"]
        self.assertNotIn("TaskPreviewPanel", blocked["required_components"])
        self.assertIn("task_manifest_null", blocked["must_show_fields"])
        self.assertIsNone(self.phase1["BLOCKED"]["task_manifest"])

    def test_complete_state_still_cannot_authorize_merge(self) -> None:
        complete_packet = self.phase1["COMPLETE"]
        complete_view = _state_map(self.fixture["state_component_map"])["COMPLETE"]
        self.assertIn("final_merge_authority", complete_view["must_show_fields"])
        self.assertEqual(
            complete_packet["human_review"]["final_merge_authority"],
            "Junyan",
        )
        self.assertIs(complete_packet["human_review"]["final_merge_authorized"], False)

    def test_responsive_qa_covers_desktop_and_mobile(self) -> None:
        responsive = self.fixture["responsive_qa"]
        self.assertIn("desktop", responsive)
        self.assertIn("mobile_390", responsive)
        self.assertIn("evidence_table_readable", responsive["desktop"])
        self.assertIn("no_text_overflow", responsive["mobile_390"])


if __name__ == "__main__":
    unittest.main()
