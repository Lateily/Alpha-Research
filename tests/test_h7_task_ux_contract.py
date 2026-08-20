"""Offline acceptance tests for the H7 Task UX Phase 1 contract."""

from __future__ import annotations

import copy
import json
import re
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from scripts.llm.ai_os.task_compiler import SPEC_BLOCKED, SPEC_READY, compile_task_manifest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES_PATH = (
    ROOT
    / "docs"
    / "contracts"
    / "product"
    / "fixtures"
    / "h7-task-ux-fixtures.v0.json"
)
SCHEMA_PATH = (
    ROOT / "docs" / "contracts" / "product" / "h7-task-ux.v0.schema.json"
)

STATUSES = {
    "COMPLETE",
    "PARTIAL",
    "STALE",
    "BLOCKED",
    "ERROR",
    "AWAITING_HUMAN_REVIEW",
}
ROOT_KEYS = {
    "schema",
    "workflow_type",
    "status",
    "generated_at",
    "user_input",
    "task_manifest",
    "projection",
    "human_review",
    "no_trade_flag",
}
USER_INPUT_KEYS = {
    "request_id",
    "source_issue",
    "goal",
    "human_owner",
    "reviewer",
    "announcement_refs",
    "fact_fields",
    "data_cutoff",
    "max_cny",
    "max_minutes",
    "submitted_at",
}
SOURCE_REF_KEYS = {
    "source_id",
    "source_kind",
    "locator",
    "publish_date",
    "data_cutoff",
    "trust",
}
PROJECTION_KEYS = {
    "task_state",
    "run_state",
    "freshness",
    "model",
    "prompt_version",
    "summary",
    "evidence",
    "missing_evidence",
    "warnings",
    "blocking_reasons",
    "external_content_trust",
    "error_code",
}
EVIDENCE_KEYS = {
    "source_id",
    "locator",
    "publish_date",
    "data_cutoff",
    "evidence_tier",
    "fact",
    "verification_status",
}
REVIEW_KEYS = {
    "state",
    "reviewer",
    "decision_ref",
    "final_merge_authority",
    "final_merge_authorized",
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
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _contains_secret(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in SECRET_PATTERNS)
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    if isinstance(value, Mapping):
        return any(_contains_secret(item) for item in value.values())
    return False


def _compiler_source(packet: Mapping[str, Any]) -> dict[str, Any]:
    user_input = packet["user_input"]
    fact_fields = user_input["fact_fields"]
    return {
        "schema": "ai-task.v1",
        "task_id": user_input["request_id"],
        "source_issue": user_input["source_issue"],
        "architecture_block": ["H7", "Product-AIOS Bridge"],
        "objective": user_input["goal"],
        "non_goals": [
            "No investment conclusion",
            "No buy or sell instruction",
            "No production write",
        ],
        "human_owner": user_input["human_owner"],
        "reviewer": user_input["reviewer"],
        "executor_candidates": ["Codex"],
        "dependencies": ["#280"],
        "authority_docs": [
            "docs/team/TEAM_CHARTER_v4.md",
            "docs/product/H7_TASK_UX_V0.md",
        ],
        "file_scope": ["docs/product/", "docs/contracts/product/"],
        "forbidden_scope": ["experiments/execution_tracker/", "public/data/"],
        "input_contracts": [
            "h7-task-ux.v0",
            *[
                f"announcement-ref:{item['source_id']}"
                for item in user_input["announcement_refs"]
            ],
            f"data-cutoff:{user_input['data_cutoff']}",
        ],
        "output_artifacts": ["product-aios-bridge.v0"],
        "acceptance_tests": [
            f"Extract {field} with a source citation." for field in fact_fields
        ],
        "risk_level": "LOW",
        "network_policy": "OFFLINE",
        "budget": {
            "max_cny": user_input["max_cny"],
            "max_minutes": user_input["max_minutes"],
        },
        "approval_gates": [
            "Independent Human Review",
            "Junyan final merge authority",
        ],
        "created_at": user_input["submitted_at"],
    }


def validate_packet(packet: Any) -> list[str]:
    """Validate the H7 product boundary without returning supplied values."""

    errors: list[str] = []
    if not isinstance(packet, Mapping):
        return ["packet must be an object"]
    if set(packet) != ROOT_KEYS:
        errors.append("packet fields are invalid")
    if _contains_secret(packet):
        errors.append("packet contains secret-like data")
    if packet.get("schema") != "h7-task-ux.v0":
        errors.append("schema is unsupported")
    if packet.get("workflow_type") != "ANNOUNCEMENT_FACT_EXTRACTION":
        errors.append("workflow_type is unsupported")
    if packet.get("status") not in STATUSES:
        errors.append("status is unsupported")
    if not _aware_timestamp(packet.get("generated_at")):
        errors.append("generated_at is invalid")
    if packet.get("no_trade_flag") is not True:
        errors.append("no_trade_flag must be true")

    user_input = packet.get("user_input")
    if not isinstance(user_input, Mapping) or set(user_input) != USER_INPUT_KEYS:
        errors.append("user_input fields are invalid")
    else:
        if not _aware_timestamp(user_input.get("data_cutoff")):
            errors.append("data_cutoff is invalid")
        if not _aware_timestamp(user_input.get("submitted_at")):
            errors.append("submitted_at is invalid")
        refs = user_input.get("announcement_refs")
        if not isinstance(refs, list) or not refs:
            errors.append("announcement_refs are invalid")
        else:
            for ref in refs:
                if not isinstance(ref, Mapping) or set(ref) != SOURCE_REF_KEYS:
                    errors.append("announcement_ref fields are invalid")
                    continue
                if ref.get("trust") != "UNTRUSTED_DATA":
                    errors.append("announcement_ref trust is invalid")
                if not _aware_timestamp(ref.get("data_cutoff")):
                    errors.append("announcement_ref cutoff is invalid")
        facts = user_input.get("fact_fields")
        if packet.get("status") != "BLOCKED" and (
            not isinstance(facts, list) or not facts
        ):
            errors.append("fact_fields are required")

    projection = packet.get("projection")
    if not isinstance(projection, Mapping) or set(projection) != PROJECTION_KEYS:
        errors.append("projection fields are invalid")
    else:
        if projection.get("external_content_trust") != "UNTRUSTED_DATA":
            errors.append("external content trust is invalid")
        if projection.get("model") != "offline-fixture":
            errors.append("fixture model label is invalid")
        if projection.get("prompt_version") != "h7.announcement-fact-extraction.v0":
            errors.append("prompt version is invalid")
        evidence = projection.get("evidence")
        if not isinstance(evidence, list):
            errors.append("evidence must be a list")
        else:
            for item in evidence:
                if not isinstance(item, Mapping) or set(item) != EVIDENCE_KEYS:
                    errors.append("evidence fields are invalid")
                    continue
                if not _aware_timestamp(item.get("data_cutoff")):
                    errors.append("evidence cutoff is invalid")

    review = packet.get("human_review")
    if not isinstance(review, Mapping) or set(review) != REVIEW_KEYS:
        errors.append("human_review fields are invalid")
    else:
        if review.get("state") not in {
            "NOT_REQUESTED",
            "PENDING",
            "APPROVED",
            "REVISE",
            "REJECTED",
        }:
            errors.append("human review state is invalid")
        if review.get("final_merge_authority") != "Junyan":
            errors.append("final merge authority is invalid")
        if review.get("final_merge_authorized") is not False:
            errors.append("H7 cannot authorize final merge")

    status = packet.get("status")
    manifest = packet.get("task_manifest")
    if isinstance(user_input, Mapping):
        compile_result = compile_task_manifest(_compiler_source(packet))
        if status == "BLOCKED":
            if compile_result.status != SPEC_BLOCKED or manifest is not None:
                errors.append("BLOCKED must not expose a runnable task manifest")
        elif compile_result.status != SPEC_READY or manifest != compile_result.manifest:
            errors.append("task_manifest does not match canonical compiler output")

    if isinstance(manifest, Mapping):
        if "task_type" in manifest or "workflow_type" in manifest:
            errors.append("H7 cannot invent task manifest fields")
        executors = manifest.get("executor_candidates", [])
        if isinstance(review, Mapping) and review.get("reviewer") in executors:
            errors.append("executor cannot review its own output")
        if (
            isinstance(review, Mapping)
            and review.get("state") == "APPROVED"
            and review.get("reviewer") != manifest.get("reviewer")
        ):
            errors.append("approved reviewer must match task reviewer")

    if isinstance(projection, Mapping) and isinstance(review, Mapping):
        if status == "COMPLETE":
            if not projection.get("evidence") or projection.get("missing_evidence"):
                errors.append("COMPLETE evidence is invalid")
            if review.get("state") != "APPROVED" or not review.get("decision_ref"):
                errors.append("COMPLETE requires independent review")
        if status == "PARTIAL" and not projection.get("missing_evidence"):
            errors.append("PARTIAL requires missing evidence")
        if status == "STALE" and projection.get("freshness") != "STALE":
            errors.append("STALE requires stale freshness")
        if status == "BLOCKED" and not projection.get("blocking_reasons"):
            errors.append("BLOCKED requires blocking reasons")
        if status == "ERROR" and not projection.get("error_code"):
            errors.append("ERROR requires an error code")
        if status == "AWAITING_HUMAN_REVIEW" and (
            review.get("state") != "PENDING" or review.get("decision_ref") is not None
        ):
            errors.append("AWAITING_HUMAN_REVIEW must remain pending")

    return list(dict.fromkeys(errors))


class H7TaskUxContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture_set = _load_json(FIXTURES_PATH)
        cls.schema = _load_json(SCHEMA_PATH)
        cls.fixtures = fixture_set["fixtures"]
        cls.fixture_set = fixture_set

    def test_fixture_inventory_is_exact(self) -> None:
        self.assertEqual(self.fixture_set["schema"], "h7-task-ux.fixtures.v0")
        self.assertEqual(set(self.fixtures), STATUSES)

    def test_schema_and_runtime_required_fields_match(self) -> None:
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(set(self.schema["required"]), ROOT_KEYS)
        self.assertEqual(set(self.schema["properties"]["status"]["enum"]), STATUSES)

    def test_all_sanitized_fixtures_validate(self) -> None:
        for status, packet in self.fixtures.items():
            with self.subTest(status=status):
                self.assertEqual(packet["status"], status)
                self.assertEqual(validate_packet(packet), [])

    def test_non_blocked_fixtures_match_canonical_compiler(self) -> None:
        for status, packet in self.fixtures.items():
            result = compile_task_manifest(_compiler_source(packet))
            with self.subTest(status=status):
                if status == "BLOCKED":
                    self.assertEqual(result.status, SPEC_BLOCKED)
                    self.assertIsNone(packet["task_manifest"])
                else:
                    self.assertEqual(result.status, SPEC_READY)
                    self.assertEqual(result.manifest, packet["task_manifest"])

    def test_unknown_field_fails_closed(self) -> None:
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["user_input"]["router_task_type"] = "announcement"
        self.assertIn("user_input fields are invalid", validate_packet(packet))

    def test_workflow_type_never_enters_ai_task(self) -> None:
        packet = self.fixtures["COMPLETE"]
        self.assertNotIn("task_type", packet["task_manifest"])
        self.assertNotIn("workflow_type", packet["task_manifest"])

    def test_secret_like_value_fails_without_echo(self) -> None:
        token = "gho_1234567890abcdef"
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["user_input"]["goal"] = token
        errors = validate_packet(packet)
        self.assertIn("packet contains secret-like data", errors)
        self.assertNotIn(token, json.dumps(errors))

    def test_naive_timestamp_fails_closed(self) -> None:
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["user_input"]["data_cutoff"] = "2026-08-20T09:00:00"
        self.assertIn("data_cutoff is invalid", validate_packet(packet))

    def test_complete_cannot_hide_missing_evidence(self) -> None:
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["projection"]["missing_evidence"] = ["disclosed_amount"]
        self.assertIn("COMPLETE evidence is invalid", validate_packet(packet))

    def test_stale_cannot_claim_current_freshness(self) -> None:
        packet = copy.deepcopy(self.fixtures["STALE"])
        packet["projection"]["freshness"] = "CURRENT"
        self.assertIn("STALE requires stale freshness", validate_packet(packet))

    def test_executor_cannot_self_review(self) -> None:
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["human_review"]["reviewer"] = "Codex"
        self.assertIn("executor cannot review its own output", validate_packet(packet))

    def test_approved_reviewer_must_match_task(self) -> None:
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["human_review"]["reviewer"] = "Simon"
        self.assertIn(
            "approved reviewer must match task reviewer",
            validate_packet(packet),
        )

    def test_h7_cannot_claim_final_merge_authority(self) -> None:
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["human_review"]["final_merge_authorized"] = True
        self.assertIn("H7 cannot authorize final merge", validate_packet(packet))

    def test_pending_review_cannot_carry_decision(self) -> None:
        packet = copy.deepcopy(self.fixtures["AWAITING_HUMAN_REVIEW"])
        packet["human_review"]["decision_ref"] = "fixture:false-approval"
        self.assertIn(
            "AWAITING_HUMAN_REVIEW must remain pending",
            validate_packet(packet),
        )


if __name__ == "__main__":
    unittest.main()
