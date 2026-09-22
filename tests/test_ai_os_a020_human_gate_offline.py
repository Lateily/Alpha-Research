"""Offline adversarial tests for AIOS A-020a Human Decision Gate."""

from __future__ import annotations

import copy
import json
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.llm.ai_os.human_gate import (  # noqa: E402
    ATTESTATION_SCHEMA,
    HUMAN_GATE_BLOCKED,
    UNVERIFIED_DECISION_RECORDED,
    HumanGateContext,
    attestation_hash,
    evaluate_human_gate,
)


HEAD = "a" * 40
ARTIFACT_HASH = "sha256:" + "b" * 64
EVIDENCE_REF = (
    "https://github.com/Lateily/Alpha-Research/"
    "pull/289#pullrequestreview-123456"
)


def context(**changes: object) -> HumanGateContext:
    values = {
        "task_id": "a020-human-gate",
        "gate": "FINAL_MERGE",
        "current_head_sha": HEAD,
        "reviewed_artifact_hash": ARTIFACT_HASH,
        "executor_principal_id": "github-user:202",
        "executor_login": "Codex",
        "required_authority_role": "JUNYAN_FINAL_GATE",
    }
    values.update(changes)
    return HumanGateContext(**values)  # type: ignore[arg-type]


def decision_record(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "schema": "ai-decision.v1",
        "decision_id": "decision-001",
        "task_id": "a020-human-gate",
        "gate": "FINAL_MERGE",
        "decision": "APPROVE",
        "decided_by": "Lateily",
        "scope": ["pull:289"],
        "reason": "Exact-head human review completed.",
        "evidence_refs": [EVIDENCE_REF],
        "decided_at": "2026-08-21T18:00:00+08:00",
        "reviewed_head_sha": HEAD,
        "reviewed_artifact_hash": ARTIFACT_HASH,
        "attestation_id": "attestation-001",
    }
    values.update(changes)
    return values


def attestation_claim(
    record: dict[str, object], **changes: object
) -> dict[str, object]:
    values: dict[str, object] = {
        "schema": ATTESTATION_SCHEMA,
        "attestation_id": record["attestation_id"],
        "decision_id": record["decision_id"],
        "task_id": record["task_id"],
        "gate": record["gate"],
        "decision": record["decision"],
        "principal_id": "github-user:101",
        "principal_login": record["decided_by"],
        "authority_role": "JUNYAN_FINAL_GATE",
        "source": "GITHUB_API_ATTESTATION_CLAIM",
        "source_ref": EVIDENCE_REF,
        "reviewed_head_sha": record["reviewed_head_sha"],
        "reviewed_artifact_hash": record["reviewed_artifact_hash"],
        "verified_at": "2026-08-21T18:01:00+08:00",
    }
    values.update(changes)
    values["attestation_hash"] = attestation_hash(values)
    return values


class A020HumanGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.network_calls = 0

        def deny_network(*args: object, **kwargs: object) -> None:
            self.network_calls += 1
            raise AssertionError("A-020a must remain offline")

        self.socket_patch = mock.patch.object(socket, "socket", side_effect=deny_network)
        self.connection_patch = mock.patch.object(
            socket, "create_connection", side_effect=deny_network
        )
        self.socket_patch.start()
        self.connection_patch.start()

    def tearDown(self) -> None:
        self.connection_patch.stop()
        self.socket_patch.stop()
        self.assertEqual(self.network_calls, 0)

    def test_exact_structured_approval_stays_blocked_until_authority_resolver(self) -> None:
        record = decision_record()
        result = evaluate_human_gate(record, attestation_claim(record), context())
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertFalse(result.can_authorize)
        self.assertIn("AUTHORITY_RESOLVER_UNWIRED", result.reason_codes)

    def test_non_approve_decisions_are_machine_readable_but_not_authorizing(self) -> None:
        for value in ("REVISE", "REJECT", "DEFER", "RETIRE"):
            with self.subTest(decision=value):
                record = decision_record(decision=value)
                result = evaluate_human_gate(
                    record, attestation_claim(record), context()
                )
                self.assertEqual(result.status, UNVERIFIED_DECISION_RECORDED)
                self.assertEqual(result.decision, value)
                self.assertFalse(result.can_authorize)

    def test_raw_model_or_chat_text_cannot_impersonate_human_attestation(self) -> None:
        record = decision_record()
        for fake in (
            "raw-model-text: Jason approved",
            "chat_history says Junyan approved",
            {"decision_ref": "agent-generated approval"},
        ):
            with self.subTest(fake=type(fake).__name__):
                result = evaluate_human_gate(record, fake, context())
                self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
                self.assertFalse(result.can_authorize)

    def test_extra_decision_ref_field_is_rejected_not_treated_as_authority(self) -> None:
        record = decision_record()
        record["decision_ref"] = "raw-model-text: approved"
        result = evaluate_human_gate(record, attestation_claim(record), context())
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("DECISION_FIELDS_INVALID", result.reason_codes)

    def test_missing_attestation_fails_closed(self) -> None:
        result = evaluate_human_gate(decision_record(), None, context())
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("ATTESTATION_REQUIRED", result.reason_codes)

    def test_untrusted_attestation_source_fails_closed(self) -> None:
        record = decision_record()
        proof = attestation_claim(record, source="raw_model_text")
        result = evaluate_human_gate(record, proof, context())
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("ATTESTATION_SOURCE_UNTRUSTED", result.reason_codes)

    def test_stale_head_is_blocked(self) -> None:
        record = decision_record(reviewed_head_sha="c" * 40)
        proof = attestation_claim(record)
        result = evaluate_human_gate(record, proof, context())
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("HEAD_BINDING_MISMATCH", result.reason_codes)

    def test_artifact_hash_mismatch_is_blocked(self) -> None:
        record = decision_record(reviewed_artifact_hash="sha256:" + "c" * 64)
        proof = attestation_claim(record)
        result = evaluate_human_gate(record, proof, context())
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("ARTIFACT_BINDING_MISMATCH", result.reason_codes)

    def test_task_binding_mismatch_is_blocked(self) -> None:
        record = decision_record(task_id="another-task")
        proof = attestation_claim(record)
        result = evaluate_human_gate(record, proof, context())
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("TASK_BINDING_MISMATCH", result.reason_codes)

    def test_gate_binding_mismatch_is_blocked(self) -> None:
        record = decision_record(gate="PR_REVIEW")
        proof = attestation_claim(record)
        result = evaluate_human_gate(record, proof, context())
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("GATE_BINDING_MISMATCH", result.reason_codes)

    def test_decision_id_binding_mismatch_is_blocked(self) -> None:
        record = decision_record()
        proof = attestation_claim(record, decision_id="decision-002")
        result = evaluate_human_gate(record, proof, context())
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("DECISION_ID_MISMATCH", result.reason_codes)

    def test_attestation_id_binding_mismatch_is_blocked(self) -> None:
        record = decision_record()
        proof = attestation_claim(record, attestation_id="attestation-002")
        result = evaluate_human_gate(record, proof, context())
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("ATTESTATION_ID_MISMATCH", result.reason_codes)

    def test_decision_binding_mismatch_is_blocked(self) -> None:
        record = decision_record()
        proof = attestation_claim(record, decision="REVISE")
        result = evaluate_human_gate(record, proof, context())
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("DECISION_BINDING_MISMATCH", result.reason_codes)

    def test_principal_binding_mismatch_is_blocked(self) -> None:
        record = decision_record()
        proof = attestation_claim(record, principal_login="SomeoneElse")
        result = evaluate_human_gate(record, proof, context())
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("PRINCIPAL_BINDING_MISMATCH", result.reason_codes)

    def test_evidence_binding_mismatch_is_blocked(self) -> None:
        record = decision_record()
        proof = attestation_claim(
            record,
            source_ref=(
                "https://github.com/Lateily/Alpha-Research/"
                "pull/289#pullrequestreview-999999"
            ),
        )
        result = evaluate_human_gate(record, proof, context())
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("EVIDENCE_BINDING_MISMATCH", result.reason_codes)

    def test_required_authority_role_mismatch_is_blocked(self) -> None:
        record = decision_record(gate="PR_REVIEW", decision="REVISE")
        proof = attestation_claim(record, authority_role="REVIEWER")
        result = evaluate_human_gate(
            record,
            proof,
            context(gate="PR_REVIEW", required_authority_role="INDEPENDENT_REVIEWER"),
        )
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("AUTHORITY_ROLE_MISMATCH", result.reason_codes)

    def test_executor_cannot_supply_the_human_decision(self) -> None:
        record = decision_record()
        proof = attestation_claim(record)
        result = evaluate_human_gate(
            record,
            proof,
            context(
                executor_principal_id="github-user:101",
                executor_login="Lateily",
            ),
        )
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("REVIEW_NOT_INDEPENDENT", result.reason_codes)

    def test_final_merge_approval_requires_junyan_authority_role(self) -> None:
        record = decision_record()
        proof = attestation_claim(record, authority_role="REVIEWER")
        result = evaluate_human_gate(
            record,
            proof,
            context(required_authority_role="REVIEWER"),
        )
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("FINAL_MERGE_AUTHORITY_REQUIRED", result.reason_codes)

    def test_attestation_hash_tampering_is_blocked(self) -> None:
        record = decision_record()
        proof = attestation_claim(record)
        proof["attestation_hash"] = "sha256:" + "0" * 64
        result = evaluate_human_gate(record, proof, context())
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("ATTESTATION_HASH_MISMATCH", result.reason_codes)

    def test_secret_like_input_is_blocked_without_echo(self) -> None:
        synthetic = "gho_" + "1234567890abcdef"
        record = decision_record(task_id=synthetic)
        result = evaluate_human_gate(record, attestation_claim(record), context())
        serialized = json.dumps(result.to_dict(), sort_keys=True)
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertNotIn(synthetic, serialized)

    def test_unicode_format_control_is_blocked(self) -> None:
        record = decision_record(decided_by="Late\u202eily")
        result = evaluate_human_gate(record, attestation_claim(record), context())
        self.assertEqual(result.status, HUMAN_GATE_BLOCKED)
        self.assertIn("DECISION_IDENTIFIER_INVALID", result.reason_codes)

    def test_decision_hash_is_deterministic_and_content_sensitive(self) -> None:
        record = decision_record()
        proof = attestation_claim(record)
        first = evaluate_human_gate(record, proof, context())
        second = evaluate_human_gate(copy.deepcopy(record), copy.deepcopy(proof), context())
        revised = decision_record(decision="REVISE")
        changed = evaluate_human_gate(revised, attestation_claim(revised), context())
        self.assertEqual(first.decision_hash, second.decision_hash)
        self.assertNotEqual(first.decision_hash, changed.decision_hash)

    def test_schema_and_runtime_fixture_use_the_same_required_fields(self) -> None:
        schema = json.loads(
            (ROOT / "scripts" / "llm" / "schemas" / "decision.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(decision_record()))
        self.assertIn("K1 does not consume this schema yet", schema["$comment"])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(A020HumanGateTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if result.wasSuccessful():
        print(
            "ALL AIOS A-020a HUMAN GATE OFFLINE TESTS PASS "
            f"({result.testsRun} tests, 0 network calls)"
        )
    raise SystemExit(0 if result.wasSuccessful() else 1)
