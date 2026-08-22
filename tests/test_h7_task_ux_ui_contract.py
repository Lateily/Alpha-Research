"""Offline acceptance tests for the H7 Task UX Phase 2 UI contract."""

from __future__ import annotations

import copy
import json
import re
import unittest
from datetime import datetime
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
UI_SCHEMA = ROOT / "docs" / "contracts" / "product" / "h7-task-ux-ui.v0.schema.json"

ACTIVE_STATUSES = {
    "PARTIAL",
    "STALE",
    "BLOCKED",
    "ERROR",
    "AWAITING_HUMAN_REVIEW",
}
STATUS_ENUM = ACTIVE_STATUSES
LAYOUT_SECTIONS = {
    "request_summary",
    "task_manifest_preview",
    "aios_state",
    "evidence_table",
    "missing_or_blocked_items",
    "human_review",
    "audit_strip",
}
ACTION_IDS = {
    "CREATE_TASK_PREVIEW",
    "EDIT_REQUEST",
    "REFRESH_CONTEXT_REQUEST",
    "REQUEST_HUMAN_REVIEW",
    "VIEW_EVIDENCE",
    "COPY_TASK_ID",
}
SECRET_PATTERNS = (
    re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{8,}\b", re.I),
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{8,}\b", re.I),
    re.compile(r"\bAKIA[0-9A-Z]{12,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*\S{8,}", re.I),
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or value != value.strip() or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _contains_secret(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in SECRET_PATTERNS)
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    if isinstance(value, Mapping):
        return any(_contains_secret(item) for item in value.values())
    return False


def validate_view_model(view_model: Any) -> list[str]:
    """Validate the UI view model without exposing supplied values in errors."""

    errors: list[str] = []
    if not isinstance(view_model, Mapping):
        return ["view model must be an object"]
    if _contains_secret(view_model):
        errors.append("view model contains secret-like data")
    if view_model.get("schema") != "h7-task-ux-ui.v0":
        errors.append("schema is unsupported")
    if view_model.get("source_packet_schema") != "h7-task-ux.v0":
        errors.append("source packet schema is unsupported")
    if view_model.get("workflow_type") != "ANNOUNCEMENT_FACT_EXTRACTION":
        errors.append("workflow_type is unsupported")
    if not _aware_timestamp(view_model.get("rendered_at")):
        errors.append("rendered_at is invalid")
    if view_model.get("no_trade_flag") is not True:
        errors.append("no_trade_flag must be true")

    layout = view_model.get("layout")
    if not isinstance(layout, list) or set(layout) != LAYOUT_SECTIONS:
        errors.append("layout sections are invalid")

    actions = view_model.get("actions")
    if not isinstance(actions, list):
        errors.append("actions must be a list")
    else:
        action_ids = [action.get("id") for action in actions if isinstance(action, Mapping)]
        if set(action_ids) != ACTION_IDS:
            errors.append("action inventory is invalid")
        for action in actions:
            if not isinstance(action, Mapping):
                errors.append("action must be an object")
                continue
            if action.get("id") not in ACTION_IDS:
                errors.append("action id is unsupported")
            if not _non_empty_string(action.get("label")):
                errors.append("action label is invalid")
            enabled = action.get("enabled_when")
            if (
                not isinstance(enabled, list)
                or not enabled
                or any(status not in ACTIVE_STATUSES for status in enabled)
            ):
                errors.append("action enabled states are invalid")
            if action.get("id") == "REQUEST_HUMAN_REVIEW" and not action.get(
                "requires_human"
            ):
                errors.append("human review request must require a human")
            for field in (
                "calls_model",
                "writes_github",
                "writes_production",
                "writes_memory",
                "can_authorize_final_merge",
            ):
                if action.get(field) is not False:
                    errors.append(f"action {field} must be false")

    state_views = view_model.get("state_views")
    if not isinstance(state_views, list):
        errors.append("state views must be a list")
    else:
        seen = [item.get("status") for item in state_views if isinstance(item, Mapping)]
        if set(seen) != ACTIVE_STATUSES or len(seen) != len(ACTIVE_STATUSES):
            errors.append("state view inventory is invalid")
        for item in state_views:
            if not isinstance(item, Mapping):
                errors.append("state view must be an object")
                continue
            status = item.get("status")
            tone = item.get("tone")
            if status not in ACTIVE_STATUSES:
                errors.append("state status is unsupported")
            if tone == "complete":
                errors.append("non-complete states cannot use complete tone")
            if not _non_empty_string(item.get("headline")):
                errors.append("state headline is invalid")
            if not _non_empty_string(item.get("primary_message")):
                errors.append("state message is invalid")
            sections = item.get("required_sections")
            if (
                not isinstance(sections, list)
                or not sections
                or any(section not in LAYOUT_SECTIONS for section in sections)
            ):
                errors.append("state sections are invalid")
            fields = item.get("must_show_fields")
            if not isinstance(fields, list) or not fields:
                errors.append("state must_show_fields are invalid")
            if status == "PARTIAL" and "missing_evidence" not in fields:
                errors.append("PARTIAL must show missing evidence")
            if status == "STALE" and "data_cutoff" not in fields:
                errors.append("STALE must show data cutoff")
            if status == "BLOCKED" and "blocking_reasons" not in fields:
                errors.append("BLOCKED must show blocking reasons")
            if status == "ERROR" and "error_code" not in fields:
                errors.append("ERROR must show error code")
            if status == "AWAITING_HUMAN_REVIEW" and "decision_ref_null" not in fields:
                errors.append("pending review must show missing decision reference")

    audit = view_model.get("audit")
    if not isinstance(audit, Mapping):
        errors.append("audit must be an object")
    else:
        if audit.get("external_content_trust") != "UNTRUSTED_DATA":
            errors.append("external content trust is invalid")
        if audit.get("final_merge_authority") != "Junyan":
            errors.append("final merge authority is invalid")
        if audit.get("human_review_required") is not True:
            errors.append("human review must be required")
        if audit.get("memory_write_allowed") is not False:
            errors.append("memory writes are not allowed")
        if audit.get("provider_call_allowed") is not False:
            errors.append("provider calls are not allowed")

    return list(dict.fromkeys(errors))


class H7TaskUxUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.phase1 = _load_json(PHASE1_FIXTURES)["fixtures"]
        cls.schema = _load_json(UI_SCHEMA)
        cls.ui = _load_json(UI_FIXTURES)["view_model"]

    def test_ui_fixture_inventory_matches_phase1_statuses(self) -> None:
        self.assertEqual(set(self.phase1), ACTIVE_STATUSES)
        self.assertEqual(
            {view["status"] for view in self.ui["state_views"]},
            set(self.phase1),
        )

    def test_schema_declares_the_same_status_inventory(self) -> None:
        status_enum = self.schema["$defs"]["status"]["enum"]
        self.assertEqual(set(status_enum), STATUS_ENUM)
        self.assertFalse(self.schema["additionalProperties"])

    def test_ui_fixture_does_not_render_complete_before_a020(self) -> None:
        self.assertNotIn("COMPLETE", {view["status"] for view in self.ui["state_views"]})

    def test_view_model_validates(self) -> None:
        self.assertEqual(validate_view_model(self.ui), [])

    def test_non_complete_state_cannot_render_as_complete(self) -> None:
        view_model = copy.deepcopy(self.ui)
        for item in view_model["state_views"]:
            if item["status"] == "STALE":
                item["tone"] = "complete"
        self.assertIn(
            "non-complete states cannot use complete tone",
            validate_view_model(view_model),
        )

    def test_actions_cannot_write_or_call_models(self) -> None:
        for action in self.ui["actions"]:
            with self.subTest(action=action["id"]):
                self.assertIs(action["calls_model"], False)
                self.assertIs(action["writes_github"], False)
                self.assertIs(action["writes_production"], False)
                self.assertIs(action["writes_memory"], False)
                self.assertIs(action["can_authorize_final_merge"], False)

    def test_human_review_action_requires_human(self) -> None:
        view_model = copy.deepcopy(self.ui)
        for action in view_model["actions"]:
            if action["id"] == "REQUEST_HUMAN_REVIEW":
                action["requires_human"] = False
        self.assertIn(
            "human review request must require a human",
            validate_view_model(view_model),
        )

    def test_status_specific_negative_errors_are_precise(self) -> None:
        checks = {
            "PARTIAL": ("missing_evidence", "PARTIAL must show missing evidence"),
            "STALE": ("data_cutoff", "STALE must show data cutoff"),
            "BLOCKED": ("blocking_reasons", "BLOCKED must show blocking reasons"),
            "ERROR": ("error_code", "ERROR must show error code"),
            "AWAITING_HUMAN_REVIEW": (
                "decision_ref_null",
                "pending review must show missing decision reference",
            ),
        }
        for status, (field, expected) in checks.items():
            view_model = copy.deepcopy(self.ui)
            for item in view_model["state_views"]:
                if item["status"] == status:
                    item["must_show_fields"].remove(field)
            with self.subTest(status=status):
                self.assertIn(expected, validate_view_model(view_model))

    def test_secret_like_label_fails_without_echo(self) -> None:
        synthetic_value = "ghp_" + "1234567890abcdef"
        view_model = copy.deepcopy(self.ui)
        view_model["state_views"][0]["headline"] = synthetic_value
        errors = validate_view_model(view_model)
        self.assertIn("view model contains secret-like data", errors)
        self.assertNotIn(synthetic_value, json.dumps(errors))

    def test_audit_strip_is_fail_closed(self) -> None:
        view_model = copy.deepcopy(self.ui)
        view_model["audit"]["provider_call_allowed"] = True
        self.assertIn("provider calls are not allowed", validate_view_model(view_model))

    def test_workflow_type_remains_ui_metadata_only(self) -> None:
        for packet in self.phase1.values():
            manifest = packet["task_manifest"]
            if manifest is None:
                continue
            self.assertNotIn("workflow_type", manifest)
            self.assertNotIn("task_type", manifest)


if __name__ == "__main__":
    unittest.main()
