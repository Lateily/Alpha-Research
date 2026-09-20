#!/usr/bin/env python3
"""Pure-domain contract tests for the Jev U4 shadow policy and receipts."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))
sys.path.insert(0, str(REPO_ROOT / "experiments" / "research_funnel"))

import typed_decision as typed  # noqa: E402
import u4_shadow as shadow  # noqa: E402
from adapters import (  # noqa: E402
    AgentError,
    AgentResult,
    AgentStatus,
    Usage,
)


FIXTURE_ROOT = REPO_ROOT / "scripts/llm/fixtures/jev_u4_shadow/synthetic-mixed"
PACKET_FILE_HASH = "sha256:" + "f" * 64
PROVIDER = {
    "name": "offline_fixture",
    "model": None,
    "model_revision": None,
    "provider_contacted": False,
    "network_policy": "deny",
    "usage": Usage.not_applicable().to_dict(),
    "cost_cny": "0",
}


def _load(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _cassette() -> dict:
    payload = _load("cassettes.json")
    return copy.deepcopy(next(value for key, value in payload.items() if key != "_meta"))


def _agent_result(
    output: dict | None = None,
    *,
    run_id: str = "run_a",
    started_at: str = "2026-08-12T09:30:01+00:00",
    finished_at: str = "2026-08-12T09:30:02+00:00",
    duration_ms: int = 1000,
    error: AgentError | None = None,
) -> AgentResult:
    return AgentResult(
        run_id=run_id,
        task_id="JEV-U4-SHADOW-ENGINE-001",
        task_type="u4_shadow_decision",
        provider="offline_fixture",
        model=None,
        prompt_version=typed.QUESTION_SET_VERSION,
        evidence_grade="E4",
        input_hash="sha256:" + "a" * 64,
        status=AgentStatus.SUCCEEDED if error is None else AgentStatus.FAILED,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        output=(
            copy.deepcopy(output if output is not None else _cassette())
            if error is None
            else None
        ),
        usage=Usage.not_applicable(),
        evidence_refs=("offline-cassette:synthetic",),
        error=error,
    )


def _reseal(receipt: dict) -> dict:
    receipt["receipt_hash"] = typed.canonical_hash(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )
    return receipt


class JevU4ShadowPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.packet = _load("u4-pre-decision.json")
        self.request = _load("request.json")
        self.ready_rows = [
            copy.deepcopy(row)
            for row in self.packet["candidate_rows"]
            if row["allowed_for_u4_packet"] is True
        ]

    def test_gate_preserves_u3_precedence_and_all_reason_codes(self) -> None:
        ready_row = self.ready_rows[0]
        gate = shadow.derive_gate(
            {
                **ready_row,
                "blocked_reasons": [
                    "U3_BATTERY_INCOMPLETE",
                    "E1_RED_FLAG_ACTIVE",
                    "E1_RED_FLAG_ACTIVE",
                ],
                "red_flag_channels": ["E1_EVENT"],
                "allowed_for_u4_packet": False,
            }
        )

        self.assertEqual(
            {
                "state": "FORCED_DATA_BLOCKED",
                "forced_shadow_outcome": "DATA_BLOCKED",
                "reason_codes": ["E1_RED_FLAG_ACTIVE", "U3_BATTERY_INCOMPLETE"],
            },
            gate,
        )

    def test_gate_covers_red_flag_policy_stop_and_eligible_states(self) -> None:
        red_flag = copy.deepcopy(self.packet["candidate_rows"][0])
        stopped = copy.deepcopy(self.packet["candidate_rows"][3])
        ready = self.ready_rows[0]

        self.assertEqual(
            {
                "state": "FORCED_REJECT",
                "forced_shadow_outcome": "REJECT",
                "reason_codes": ["E1_RED_FLAG_ACTIVE"],
            },
            shadow.derive_gate(red_flag),
        )
        self.assertEqual(
            {
                "state": "POLICY_STOPPED",
                "forced_shadow_outcome": None,
                "reason_codes": [
                    "NO_POSITIVE_CHANNEL",
                    "RANDOM_CONTROL_NOT_SELECTABLE",
                ],
            },
            shadow.derive_gate(stopped),
        )
        self.assertEqual(
            {
                "state": "ELIGIBLE_FOR_TYPED_JUDGMENT",
                "forced_shadow_outcome": None,
                "reason_codes": [],
            },
            shadow.derive_gate(ready),
        )

    def test_candidate_state_matches_the_committed_cassette_binding(self) -> None:
        state = shadow.assemble_candidate_state(self.packet, self.ready_rows[0])
        cassette_keys = {
            key for key in _load("cassettes.json") if key != "_meta"
        }

        self.assertEqual(
            {
                f"{typed.canonical_hash(state)}:{typed.QUESTION_SET_VERSION}"
            },
            cassette_keys,
        )
        self.assertEqual(
            {
                "packet_hash",
                "as_of",
                "method_version",
                "source_publication",
                "ticker",
                "display_name",
                "candidate_status",
                "causal_cluster_id",
                "causal_cluster_identity_state",
                "positive_channels",
                "missing_evidence",
                "peak_earnings",
                "battery_dimension_verdicts",
                "u2_candidate_row_hash",
                "u3_battery_row_hash",
                "question_for_junyan",
                "diagnostic_summary",
            },
            set(state),
        )

    def test_composer_records_observation_without_granting_authority(self) -> None:
        candidate = shadow.compose_candidate_result(
            self.packet,
            self.ready_rows[0],
            provider_result=_agent_result(),
        )

        self.assertEqual("SELECT_FOR_DEEP_RESEARCH", candidate["shadow_outcome"])
        self.assertEqual(
            {
                "shadow_outcome_state": "OBSERVED_NOT_AUTHORIZED",
                "top_choice_label": "SELECT_FOR_DEEP_RESEARCH",
                "top_choice_probability": "0.500000",
                "second_choice_probability": "0.200000",
                "top_two_margin": "0.300000",
                "research_priority_score": "63.500000",
                "needs_human_review_probability": "0.800000",
            },
            candidate["composer_observation"],
        )
        self.assertEqual("SUCCEEDED", candidate["provider_result"]["status"])
        self.assertNotIn("run_id", candidate["provider_result"])
        self.assertNotIn("started_at", candidate["provider_result"])
        self.assertNotIn("duration_ms", candidate["provider_result"])

    def test_composer_keeps_forced_and_stopped_rows_provider_free(self) -> None:
        red = shadow.compose_candidate_result(self.packet, self.packet["candidate_rows"][0])
        stopped = shadow.compose_candidate_result(
            self.packet, self.packet["candidate_rows"][3]
        )

        self.assertEqual("REJECT", red["shadow_outcome"])
        self.assertIsNone(red["typed_answers"])
        self.assertEqual({"status": "NOT_CALLED"}, red["provider_result"])
        self.assertIsNone(stopped["shadow_outcome"])
        self.assertIsNone(stopped["composer_observation"])
        self.assertEqual({"status": "NOT_CALLED"}, stopped["provider_result"])
        with self.assertRaisesRegex(shadow.ShadowPolicyError, "must not receive"):
            shadow.compose_candidate_result(
                self.packet,
                self.packet["candidate_rows"][0],
                provider_result=_agent_result(),
            )

    def test_composer_keeps_provider_failure_visible_without_an_outcome(self) -> None:
        failure = AgentError(
            code="MODEL_UNAVAILABLE",
            message="no cassette for exact state",
            retryable=False,
        )
        candidate = shadow.compose_candidate_result(
            self.packet,
            self.ready_rows[1],
            provider_result=_agent_result(error=failure),
        )

        self.assertEqual("MODEL_UNAVAILABLE", candidate["provider_result"]["status"])
        self.assertEqual(
            {
                "code": "MODEL_UNAVAILABLE",
                "message": "no cassette for exact state",
                "retryable": False,
            },
            candidate["failure"],
        )
        self.assertIsNone(candidate["typed_answers"])
        self.assertIsNone(candidate["shadow_outcome"])

    def test_provider_cannot_introduce_action_or_authority_fields_recursively(self) -> None:
        for forbidden in (
            "orders",
            "selected_tickers",
            "position_size",
            "trade_authority",
            "machine_selection_authority",
        ):
            with self.subTest(forbidden=forbidden):
                provider_result = _agent_result().to_dict()
                provider_result["untrusted_metadata"] = {"nested": [{forbidden: False}]}
                with self.assertRaisesRegex(shadow.ShadowPolicyError, "forbidden"):
                    shadow.compose_candidate_result(
                        self.packet,
                        self.ready_rows[0],
                        provider_result=provider_result,
                    )


class JevU4ShadowReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.packet = _load("u4-pre-decision.json")
        self.request = _load("request.json")

    def _candidate_results(self, success: AgentResult | None = None) -> list[dict]:
        eligible_index = 0
        results: list[dict] = []
        for row in self.packet["candidate_rows"]:
            if row["allowed_for_u4_packet"] is not True:
                results.append(shadow.compose_candidate_result(self.packet, row))
                continue
            if eligible_index == 0:
                provider_result = success or _agent_result()
            else:
                provider_result = _agent_result(
                    error=AgentError(
                        code="MODEL_UNAVAILABLE",
                        message="no cassette for exact state",
                        retryable=False,
                    )
                )
            results.append(
                shadow.compose_candidate_result(
                    self.packet,
                    row,
                    provider_result=provider_result,
                )
            )
            eligible_index += 1
        return results

    def _receipt(self, success: AgentResult | None = None) -> dict:
        return shadow.build_receipt(
            self.request,
            self.packet,
            self._candidate_results(success),
            packet_file_hash=PACKET_FILE_HASH,
            provider=copy.deepcopy(PROVIDER),
        )

    def test_receipt_has_fixed_authority_and_recomputed_summary(self) -> None:
        receipt = self._receipt()

        self.assertEqual(
            {
                "production_authority": False,
                "trade_authority": False,
                "paper_order_authority": False,
                "formal_selection_authority": False,
            },
            receipt["authority"],
        )
        self.assertEqual(
            {
                "total_candidates": 6,
                "eligible_count": 2,
                "forced_count": 1,
                "stopped_count": 3,
                "typed_judgment_count": 1,
                "unavailable_count": 1,
                "gate_counts": {
                    "ELIGIBLE_FOR_TYPED_JUDGMENT": 2,
                    "FORCED_DATA_BLOCKED": 0,
                    "FORCED_REJECT": 1,
                    "POLICY_STOPPED": 3,
                },
                "provider_result_counts": {
                    "MODEL_UNAVAILABLE": 1,
                    "NOT_CALLED": 4,
                    "SUCCEEDED": 1,
                },
                "shadow_outcome_counts": {
                    "DATA_BLOCKED": 0,
                    "DEFER": 0,
                    "NO_TRADE": 0,
                    "REJECT": 1,
                    "SELECT_FOR_DEEP_RESEARCH": 1,
                },
            },
            receipt["batch_summary"],
        )
        self.assertIsNone(shadow.verify_receipt(receipt))

    def test_operational_agent_result_metadata_is_not_in_canonical_receipt(self) -> None:
        first = self._receipt(
            _agent_result(
                run_id="run_first",
                started_at="2026-08-12T09:30:01+00:00",
                finished_at="2026-08-12T09:30:02+00:00",
                duration_ms=1000,
            )
        )
        second = self._receipt(
            _agent_result(
                run_id="run_second",
                started_at="2031-01-01T00:00:00+00:00",
                finished_at="2031-01-01T00:01:00+00:00",
                duration_ms=60000,
            )
        )

        self.assertEqual(
            shadow.canonical_receipt_bytes(first),
            shadow.canonical_receipt_bytes(second),
        )

    def test_source_question_and_provider_tampering_invalidates_receipt_hash(self) -> None:
        mutators = {
            "source": lambda value: value["source_binding"]["evidence_refs"].__setitem__(
                "u2_candidate_pool_hash", "sha256:" + "0" * 64
            ),
            "question": lambda value: value["engine"]["question_set"]["questions"][0].__setitem__(
                "kind", "SCORE"
            ),
            "provider": lambda value: value["provider"].__setitem__("model_revision", "changed"),
        }
        for field, mutate in mutators.items():
            with self.subTest(field=field):
                receipt = self._receipt()
                mutate(receipt)
                with self.assertRaisesRegex(shadow.ShadowPolicyError, "receipt_hash"):
                    shadow.verify_receipt(receipt)

    def test_verifier_rejects_exact_schema_violations_even_when_resealed(self) -> None:
        cases = []

        extra_top = self._receipt()
        extra_top["unexpected"] = None
        cases.append(extra_top)

        extra_nested = self._receipt()
        extra_nested["identity"]["unexpected"] = None
        cases.append(extra_nested)

        missing_nested = self._receipt()
        del missing_nested["provider"]["network_policy"]
        cases.append(missing_nested)

        for receipt in cases:
            with self.subTest(keys=sorted(receipt)):
                with self.assertRaises(shadow.ShadowPolicyError):
                    shadow.verify_receipt(_reseal(receipt))

    def test_verifier_recomputes_state_hash_summary_and_typed_answers(self) -> None:
        state_tamper = self._receipt()
        state_tamper["candidate_results"][1]["state"]["display_name"] = "Changed"

        summary_tamper = self._receipt()
        summary_tamper["batch_summary"]["typed_judgment_count"] = 2

        typed_tamper = self._receipt()
        typed_tamper["candidate_results"][1]["typed_answers"]["answers"][2][
            "probabilities"
        ]["SELECT_FOR_DEEP_RESEARCH"] = "0.600000"

        for label, receipt in (
            ("state", state_tamper),
            ("summary", summary_tamper),
            ("typed", typed_tamper),
        ):
            with self.subTest(label=label):
                with self.assertRaises(shadow.ShadowPolicyError):
                    shadow.verify_receipt(_reseal(receipt))

    def test_verifier_rejects_authority_and_forbidden_actions_when_resealed(self) -> None:
        authority = self._receipt()
        authority["authority"]["trade_authority"] = True

        action = self._receipt()
        action["candidate_results"][1]["provider_result"]["orders"] = []

        nested_authority = self._receipt()
        nested_authority["candidate_results"][1]["provider_result"][
            "production_authority"
        ] = False

        for receipt in (authority, action, nested_authority):
            with self.assertRaises(shadow.ShadowPolicyError):
                shadow.verify_receipt(_reseal(receipt))

    def test_verifier_rejects_boolean_integer_type_confusion_when_resealed(self) -> None:
        authority = self._receipt()
        authority["authority"]["trade_authority"] = 0

        summary = self._receipt()
        summary["batch_summary"]["typed_judgment_count"] = True

        for receipt in (authority, summary):
            with self.assertRaises(shadow.ShadowPolicyError):
                shadow.verify_receipt(_reseal(receipt))

    def test_builder_rejects_caller_supplied_authority_and_action_fields(self) -> None:
        candidate_results = self._candidate_results()
        candidate_results[1]["provider_result"]["nested"] = {"targets": []}
        with self.assertRaisesRegex(shadow.ShadowPolicyError, "forbidden"):
            shadow.build_receipt(
                self.request,
                self.packet,
                candidate_results,
                packet_file_hash=PACKET_FILE_HASH,
                provider=copy.deepcopy(PROVIDER),
            )

        provider = copy.deepcopy(PROVIDER)
        provider["formal_selection_authority"] = False
        with self.assertRaisesRegex(shadow.ShadowPolicyError, "forbidden"):
            shadow.build_receipt(
                self.request,
                self.packet,
                self._candidate_results(),
                packet_file_hash=PACKET_FILE_HASH,
                provider=provider,
            )

    def test_observed_at_is_caller_supplied_and_bound_into_the_receipt(self) -> None:
        receipt = self._receipt()
        changed_request = copy.deepcopy(self.request)
        changed_request["observed_at"] = "2026-08-12T10:30:00+00:00"
        changed = shadow.build_receipt(
            changed_request,
            self.packet,
            self._candidate_results(),
            packet_file_hash=PACKET_FILE_HASH,
            provider=copy.deepcopy(PROVIDER),
        )

        self.assertEqual(self.request["observed_at"], receipt["identity"]["observed_at"])
        self.assertNotEqual(receipt["receipt_hash"], changed["receipt_hash"])
        self.assertNotIn("generated_at", receipt["identity"])
        self.assertNotIn("run_id", receipt["identity"])


if __name__ == "__main__":
    unittest.main()
