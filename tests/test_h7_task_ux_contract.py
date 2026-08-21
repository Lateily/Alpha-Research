"""Offline acceptance tests for the H7 Task UX Phase 1 contract."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.llm.ai_os.task_compiler import (  # noqa: E402
    SPEC_BLOCKED,
    SPEC_READY,
    compile_task_manifest,
)


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
TASK_STATES = {
    "DISCOVERED",
    "TRIAGED",
    "SPEC_READY",
    "CLAIMED",
    "RUNNING",
    "VERIFYING",
    "REVIEWING",
    "AWAITING_APPROVAL",
    "DONE",
    "SPEC_BLOCKED",
    "BLOCKED",
    "FAILED",
}
RUN_STATES = {
    "SPEC_READY",
    "RUNNING",
    "VERIFYING",
    "REVIEWING",
    "AWAITING_APPROVAL",
    "DONE",
    "SPEC_BLOCKED",
    "BLOCKED",
    "FAILED",
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
    "human_gate_receipt",
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
RECEIPT_KEYS = {
    "schema",
    "receipt_id",
    "trace_id",
    "actor",
    "decision",
    "decision_ref",
    "reviewed_artifact_id",
    "reviewed_artifact_hash",
    "decided_at",
}
STATUS_STATE_MAP = {
    "COMPLETE": ("DONE", "DONE"),
    "PARTIAL": ("VERIFYING", "VERIFYING"),
    "STALE": ("RUNNING", "RUNNING"),
    "BLOCKED": ("SPEC_BLOCKED", None),
    "ERROR": ("FAILED", "FAILED"),
    "AWAITING_HUMAN_REVIEW": ("REVIEWING", "VERIFYING"),
}
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
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


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _string_list(value: Any, *, allow_empty: bool = True) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_non_empty_string(item) for item in value)
    )


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _contains_secret(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in SECRET_PATTERNS)
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    if isinstance(value, Mapping):
        return any(_contains_secret(item) for item in value.values())
    return False


def _artifact_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
        for field in ("request_id", "goal", "human_owner", "reviewer"):
            if not _non_empty_string(user_input.get(field)):
                errors.append(f"user_input.{field} is invalid")
        source_issue = user_input.get("source_issue")
        if isinstance(source_issue, bool) or not isinstance(source_issue, int) or source_issue <= 0:
            errors.append("source_issue is invalid")
        if not _aware_timestamp(user_input.get("data_cutoff")):
            errors.append("data_cutoff is invalid")
        if not _aware_timestamp(user_input.get("submitted_at")):
            errors.append("submitted_at is invalid")
        if not isinstance(user_input.get("max_cny"), str) or not re.fullmatch(
            r"\d+(?:\.\d+)?", user_input["max_cny"]
        ):
            errors.append("max_cny is invalid")
        max_minutes = user_input.get("max_minutes")
        if isinstance(max_minutes, bool) or not isinstance(max_minutes, int) or max_minutes <= 0:
            errors.append("max_minutes is invalid")
        refs = user_input.get("announcement_refs")
        if not isinstance(refs, list) or not refs:
            errors.append("announcement_refs are invalid")
        else:
            for ref in refs:
                if not isinstance(ref, Mapping) or set(ref) != SOURCE_REF_KEYS:
                    errors.append("announcement_ref fields are invalid")
                    continue
                for field in ("source_id", "locator"):
                    if not _non_empty_string(ref.get(field)):
                        errors.append(f"announcement_ref.{field} is invalid")
                if ref.get("source_kind") != "ANNOUNCEMENT":
                    errors.append("announcement_ref source_kind is invalid")
                if not _valid_date(ref.get("publish_date")):
                    errors.append("announcement_ref publish_date is invalid")
                if ref.get("trust") != "UNTRUSTED_DATA":
                    errors.append("announcement_ref trust is invalid")
                if not _aware_timestamp(ref.get("data_cutoff")):
                    errors.append("announcement_ref cutoff is invalid")
        facts = user_input.get("fact_fields")
        if not _string_list(facts, allow_empty=packet.get("status") == "BLOCKED"):
            errors.append("fact_fields are required")

    projection = packet.get("projection")
    if not isinstance(projection, Mapping) or set(projection) != PROJECTION_KEYS:
        errors.append("projection fields are invalid")
    else:
        if projection.get("task_state") not in TASK_STATES:
            errors.append("projection task_state is invalid")
        if (
            projection.get("run_state") is not None
            and projection.get("run_state") not in RUN_STATES
        ):
            errors.append("projection run_state is invalid")
        if projection.get("freshness") not in {"CURRENT", "STALE", "UNKNOWN"}:
            errors.append("projection freshness is invalid")
        if projection.get("external_content_trust") != "UNTRUSTED_DATA":
            errors.append("external content trust is invalid")
        if projection.get("model") != "offline-fixture":
            errors.append("fixture model label is invalid")
        if projection.get("prompt_version") != "h7.announcement-fact-extraction.v0":
            errors.append("prompt version is invalid")
        if not _non_empty_string(projection.get("summary")):
            errors.append("projection summary is invalid")
        for field in ("missing_evidence", "warnings", "blocking_reasons"):
            if not _string_list(projection.get(field)):
                errors.append(f"projection {field} is invalid")
        error_code = projection.get("error_code")
        if error_code is not None and not _non_empty_string(error_code):
            errors.append("projection error_code is invalid")
        evidence = projection.get("evidence")
        if not isinstance(evidence, list):
            errors.append("evidence must be a list")
        else:
            for item in evidence:
                if not isinstance(item, Mapping) or set(item) != EVIDENCE_KEYS:
                    errors.append("evidence fields are invalid")
                    continue
                for field in ("source_id", "locator", "fact"):
                    if not _non_empty_string(item.get(field)):
                        errors.append(f"evidence {field} is invalid")
                if not _valid_date(item.get("publish_date")):
                    errors.append("evidence publish_date is invalid")
                if not _aware_timestamp(item.get("data_cutoff")):
                    errors.append("evidence cutoff is invalid")
                if item.get("evidence_tier") not in {"E1", "E2", "E3", "E4"}:
                    errors.append("evidence tier is invalid")
                if item.get("verification_status") not in {
                    "VERIFIED",
                    "UNVERIFIED",
                    "CONFLICTING",
                }:
                    errors.append("evidence verification status is invalid")
            if isinstance(user_input, Mapping):
                refs_by_id = {
                    ref.get("source_id"): ref
                    for ref in user_input.get("announcement_refs", [])
                    if isinstance(ref, Mapping)
                }
                for item in evidence:
                    if not isinstance(item, Mapping):
                        continue
                    source_ref = refs_by_id.get(item.get("source_id"))
                    if source_ref is None:
                        errors.append("evidence source is not in user input")
                    elif (
                        item.get("publish_date") != source_ref.get("publish_date")
                        or item.get("data_cutoff") != source_ref.get("data_cutoff")
                    ):
                        errors.append("evidence provenance does not match source reference")

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
        if review.get("reviewer") is not None and not _non_empty_string(
            review.get("reviewer")
        ):
            errors.append("human reviewer is invalid")
        if review.get("decision_ref") is not None and not _non_empty_string(
            review.get("decision_ref")
        ):
            errors.append("human review decision_ref is invalid")
        if review.get("state") in {"NOT_REQUESTED", "PENDING"} and review.get(
            "decision_ref"
        ) is not None:
            errors.append("unreviewed output cannot carry a decision_ref")
        if review.get("final_merge_authority") != "Junyan":
            errors.append("final merge authority is invalid")
        if review.get("final_merge_authorized") is not False:
            errors.append("H7 cannot authorize final merge")

    receipt = packet.get("human_gate_receipt")
    if receipt is not None:
        if not isinstance(receipt, Mapping) or set(receipt) != RECEIPT_KEYS:
            errors.append("human_gate_receipt fields are invalid")
        else:
            if receipt.get("schema") != "human-gate-receipt.v0":
                errors.append("human_gate_receipt schema is invalid")
            for field in (
                "receipt_id",
                "trace_id",
                "actor",
                "decision_ref",
                "reviewed_artifact_id",
            ):
                if not _non_empty_string(receipt.get(field)):
                    errors.append(f"human_gate_receipt.{field} is invalid")
            if receipt.get("decision") not in {"APPROVED", "REVISE", "REJECTED"}:
                errors.append("human_gate_receipt decision is invalid")
            if not isinstance(receipt.get("reviewed_artifact_hash"), str) or not HASH_RE.fullmatch(
                receipt["reviewed_artifact_hash"]
            ):
                errors.append("human_gate_receipt reviewed_artifact_hash is invalid")
            if not _aware_timestamp(receipt.get("decided_at")):
                errors.append("human_gate_receipt decided_at is invalid")
            if isinstance(user_input, Mapping) and receipt.get("trace_id") != user_input.get(
                "request_id"
            ):
                errors.append("human_gate_receipt trace_id must match request")
            if isinstance(review, Mapping):
                if receipt.get("actor") != review.get("reviewer"):
                    errors.append("human_gate_receipt actor must match reviewer")
                if receipt.get("decision") != review.get("state"):
                    errors.append("human_gate_receipt decision must match review")
                if receipt.get("decision_ref") != review.get("decision_ref"):
                    errors.append("human_gate_receipt decision_ref must match review")
            if isinstance(projection, Mapping) and receipt.get(
                "reviewed_artifact_hash"
            ) != _artifact_hash(projection):
                errors.append("human_gate_receipt must bind reviewed projection")

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
        expected_states = STATUS_STATE_MAP.get(status)
        if expected_states is not None and (
            projection.get("task_state"),
            projection.get("run_state"),
        ) != expected_states:
            errors.append("status does not match task/run state")
        if status == "COMPLETE":
            if not projection.get("evidence") or projection.get("missing_evidence"):
                errors.append("COMPLETE evidence is invalid")
            if review.get("state") != "APPROVED" or not review.get("decision_ref"):
                errors.append("COMPLETE requires independent review")
            if receipt is None:
                errors.append("COMPLETE requires trusted human gate receipt")
        elif review.get("state") == "APPROVED" or review.get("decision_ref") is not None:
            errors.append("non-COMPLETE cannot carry approved human review")
        if status != "COMPLETE" and receipt is not None:
            errors.append("non-COMPLETE cannot carry human gate receipt")
        if status == "PARTIAL" and not projection.get("missing_evidence"):
            errors.append("PARTIAL requires missing evidence")
        if status == "STALE" and projection.get("freshness") != "STALE":
            errors.append("STALE requires stale freshness")
        if status == "BLOCKED" and not projection.get("blocking_reasons"):
            errors.append("BLOCKED requires blocking reasons")
        if status == "ERROR" and not projection.get("error_code"):
            errors.append("ERROR requires an error code")
        if status != "ERROR" and projection.get("error_code") is not None:
            errors.append("error_code is only allowed for ERROR")
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
        synthetic_value = "gho_" + "1234567890abcdef"
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["user_input"]["goal"] = synthetic_value
        errors = validate_packet(packet)
        self.assertIn("packet contains secret-like data", errors)
        self.assertNotIn(synthetic_value, json.dumps(errors))

    def test_naive_timestamp_fails_closed(self) -> None:
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["user_input"]["data_cutoff"] = "2026-08-20T09:00:00"
        self.assertIn("data_cutoff is invalid", validate_packet(packet))

    def test_bad_publish_date_fails_closed(self) -> None:
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["user_input"]["announcement_refs"][0]["publish_date"] = "tomorrow"
        self.assertIn(
            "announcement_ref publish_date is invalid",
            validate_packet(packet),
        )

    def test_bad_evidence_tier_fails_closed(self) -> None:
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["projection"]["evidence"][0]["evidence_tier"] = "E9"
        self.assertIn("evidence tier is invalid", validate_packet(packet))

    def test_empty_summary_fails_closed(self) -> None:
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["projection"]["summary"] = ""
        self.assertIn("projection summary is invalid", validate_packet(packet))

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

    def test_complete_requires_trusted_human_gate_receipt(self) -> None:
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["human_gate_receipt"] = None
        self.assertIn(
            "COMPLETE requires trusted human gate receipt",
            validate_packet(packet),
        )

    def test_fake_text_review_cannot_complete_packet(self) -> None:
        packet = copy.deepcopy(self.fixtures["AWAITING_HUMAN_REVIEW"])
        packet["human_review"]["state"] = "APPROVED"
        packet["human_review"]["reviewer"] = "Jason"
        packet["human_review"]["decision_ref"] = "raw-model-text: agent claims Jason approved"
        errors = validate_packet(packet)
        self.assertIn("non-COMPLETE cannot carry approved human review", errors)
        self.assertIn(
            "AWAITING_HUMAN_REVIEW must remain pending",
            errors,
        )

    def test_receipt_must_bind_reviewed_projection(self) -> None:
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["projection"]["summary"] = "Tampered after review."
        self.assertIn(
            "human_gate_receipt must bind reviewed projection",
            validate_packet(packet),
        )

    def test_complete_status_requires_done_states(self) -> None:
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["projection"]["task_state"] = "REVIEWING"
        packet["projection"]["run_state"] = "VERIFYING"
        self.assertIn("status does not match task/run state", validate_packet(packet))

    def test_pending_review_cannot_carry_decision(self) -> None:
        packet = copy.deepcopy(self.fixtures["AWAITING_HUMAN_REVIEW"])
        packet["human_review"]["decision_ref"] = "fixture:false-approval"
        self.assertIn(
            "AWAITING_HUMAN_REVIEW must remain pending",
            validate_packet(packet),
        )

    def test_evidence_must_reference_submitted_source(self) -> None:
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["projection"]["evidence"][0]["source_id"] = "unknown-source"
        self.assertIn("evidence source is not in user input", validate_packet(packet))

    def test_evidence_provenance_must_match_source(self) -> None:
        packet = copy.deepcopy(self.fixtures["COMPLETE"])
        packet["projection"]["evidence"][0]["publish_date"] = "2026-08-19"
        self.assertIn(
            "evidence provenance does not match source reference",
            validate_packet(packet),
        )

    def test_non_error_cannot_carry_error_code(self) -> None:
        packet = copy.deepcopy(self.fixtures["PARTIAL"])
        packet["projection"]["error_code"] = "MISLEADING_ERROR"
        self.assertIn("error_code is only allowed for ERROR", validate_packet(packet))


if __name__ == "__main__":
    unittest.main()
