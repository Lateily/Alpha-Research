#!/usr/bin/env python3
"""Executable contract tests for provider-neutral typed shadow decisions."""

from __future__ import annotations

import copy
import math
import os
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))

import typed_decision as typed  # noqa: E402
from adapters import AgentRequest, AgentStatus, UsageStatus, run_adapter  # noqa: E402
from adapters.jev_shadow import (  # noqa: E402
    DisabledTypeSafeJevAdapter,
    OfflineFixtureDecisionAdapter,
)


VALID_RESPONSE = {
    "question_set_version": "JEV_U4_SHADOW_QUESTIONS_V1",
    "answers": [
        {
            "question_id": "evidence_sufficient",
            "kind": "NOUL",
            "probability_true": "0.700000",
        },
        {
            "question_id": "research_priority",
            "kind": "SCORE",
            "score": "63.500000",
        },
        {
            "question_id": "shadow_disposition",
            "kind": "CHOICE",
            "probabilities": {
                "SELECT_FOR_DEEP_RESEARCH": "0.500000",
                "DEFER": "0.200000",
                "REJECT": "0.100000",
                "NO_TRADE": "0.100000",
                "DATA_BLOCKED": "0.100000",
            },
        },
        {
            "question_id": "needs_human_review",
            "kind": "NOUL",
            "probability_true": "0.800000",
        },
    ],
}


class _TypeSafeKeyTrap(dict[str, str]):
    """Record every environment access and reject any TypeSafe-key lookup."""

    def __init__(self, values: dict[str, str]) -> None:
        super().__init__(values)
        self.type_safe_key_reads: list[str] = []

    def __getitem__(self, key: str) -> str:
        if key == "TYPESAFE_API_KEY":
            self.type_safe_key_reads.append("getitem")
            raise AssertionError("TYPESAFE_API_KEY must not be read")
        return super().__getitem__(key)

    def get(self, key: str, default: object = None) -> str | object:
        if key == "TYPESAFE_API_KEY":
            self.type_safe_key_reads.append("get")
            raise AssertionError("TYPESAFE_API_KEY must not be read")
        return super().get(key, default)

    def __contains__(self, key: object) -> bool:
        if key == "TYPESAFE_API_KEY":
            self.type_safe_key_reads.append("contains")
            raise AssertionError("TYPESAFE_API_KEY must not be read")
        return super().__contains__(key)


def _adapter_request(state_hash: str) -> AgentRequest:
    return AgentRequest(
        task_id="JEV-U4-SHADOW-TYPED-TEST",
        task_type="u4_shadow_fixture",
        input_payload={
            "state": {"sample_purpose": "WORKFLOW_DEBUG", "candidate": "synthetic"},
            "state_hash": state_hash,
            "question_set": typed.question_set_payload(),
        },
        prompt_version="JEV_U4_SHADOW_QUESTIONS_V1",
        evidence_grade="E4",
        network_policy="deny",
    )


class TypedDecisionContractTests(unittest.TestCase):
    def test_question_set_payload_has_the_exact_versioned_questions(self) -> None:
        self.assertEqual(
            typed.question_set_payload(),
            {
                "version": "JEV_U4_SHADOW_QUESTIONS_V1",
                "questions": [
                    {"question_id": "evidence_sufficient", "kind": "NOUL"},
                    {"question_id": "research_priority", "kind": "SCORE"},
                    {
                        "question_id": "shadow_disposition",
                        "kind": "CHOICE",
                        "labels": [
                            "SELECT_FOR_DEEP_RESEARCH",
                            "DEFER",
                            "REJECT",
                            "NO_TRADE",
                            "DATA_BLOCKED",
                        ],
                    },
                    {"question_id": "needs_human_review", "kind": "NOUL"},
                ],
            },
        )
        with self.assertRaises((AttributeError, TypeError)):
            typed.QUESTION_SET_V1[0].question_id = "changed"

    def test_normalizes_a_valid_complete_response(self) -> None:
        normalized = typed.normalize_typed_response(copy.deepcopy(VALID_RESPONSE))

        self.assertEqual(normalized, VALID_RESPONSE)
        self.assertEqual(
            normalized["answers"][2]["probabilities"]["SELECT_FOR_DEEP_RESEARCH"],
            "0.500000",
        )

    def test_rejects_missing_duplicate_and_out_of_order_answers(self) -> None:
        cases = []

        missing = copy.deepcopy(VALID_RESPONSE)
        missing["answers"].pop()
        cases.append(("missing", missing))

        duplicate = copy.deepcopy(VALID_RESPONSE)
        duplicate["answers"][3]["question_id"] = "shadow_disposition"
        duplicate["answers"][3]["kind"] = "CHOICE"
        duplicate["answers"][3].pop("probability_true")
        duplicate["answers"][3]["probabilities"] = copy.deepcopy(
            VALID_RESPONSE["answers"][2]["probabilities"]
        )
        cases.append(("duplicate", duplicate))

        out_of_order = copy.deepcopy(VALID_RESPONSE)
        out_of_order["answers"][0], out_of_order["answers"][1] = (
            out_of_order["answers"][1],
            out_of_order["answers"][0],
        )
        cases.append(("out of order", out_of_order))

        for name, payload in cases:
            with self.subTest(name=name):
                with self.assertRaises(typed.TypedDecisionError):
                    typed.normalize_typed_response(payload)

    def test_rejects_unknown_fields_at_every_contract_level(self) -> None:
        payloads = []

        root_unknown = copy.deepcopy(VALID_RESPONSE)
        root_unknown["provider_note"] = "not part of the contract"
        payloads.append(root_unknown)

        answer_unknown = copy.deepcopy(VALID_RESPONSE)
        answer_unknown["answers"][0]["score"] = "0.000000"
        payloads.append(answer_unknown)

        choice_unknown = copy.deepcopy(VALID_RESPONSE)
        choice_unknown["answers"][2]["probabilities"]["UNAPPROVED"] = "0.000000"
        payloads.append(choice_unknown)

        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(typed.TypedDecisionError):
                    typed.normalize_typed_response(payload)

    def test_rejects_bad_version_kind_and_missing_choice_label(self) -> None:
        bad_version = copy.deepcopy(VALID_RESPONSE)
        bad_version["question_set_version"] = "JEV_U4_SHADOW_QUESTIONS_V2"

        bad_kind = copy.deepcopy(VALID_RESPONSE)
        bad_kind["answers"][1]["kind"] = "NOUL"
        bad_kind["answers"][1]["probability_true"] = "0.000000"
        bad_kind["answers"][1].pop("score")

        missing_label = copy.deepcopy(VALID_RESPONSE)
        missing_label["answers"][2]["probabilities"].pop("DATA_BLOCKED")

        for payload in (bad_version, bad_kind, missing_label):
            with self.subTest(payload=payload):
                with self.assertRaises(typed.TypedDecisionError):
                    typed.normalize_typed_response(payload)

    def test_rejects_non_six_decimal_and_boolean_numeric_values(self) -> None:
        values = ("0.7", "00.700000", "-0.000001", 0.7, True)
        for value in values:
            payload = copy.deepcopy(VALID_RESPONSE)
            payload["answers"][0]["probability_true"] = value
            with self.subTest(value=value):
                with self.assertRaises(typed.TypedDecisionError):
                    typed.normalize_typed_response(payload)

    def test_rejects_probability_and_score_values_outside_their_bounds(self) -> None:
        probability = copy.deepcopy(VALID_RESPONSE)
        probability["answers"][0]["probability_true"] = "1.000001"

        score = copy.deepcopy(VALID_RESPONSE)
        score["answers"][1]["score"] = "100.000001"

        for payload in (probability, score):
            with self.subTest(payload=payload):
                with self.assertRaises(typed.TypedDecisionError):
                    typed.normalize_typed_response(payload)

    def test_rejects_nonfinite_strings_and_nonexact_choice_probability_mass(self) -> None:
        payloads = []
        for value in ("NaN", "Infinity", "-Infinity"):
            payload = copy.deepcopy(VALID_RESPONSE)
            payload["answers"][0]["probability_true"] = value
            payloads.append(payload)

        wrong_mass = copy.deepcopy(VALID_RESPONSE)
        wrong_mass["answers"][2]["probabilities"]["DATA_BLOCKED"] = "0.100001"
        payloads.append(wrong_mass)

        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(typed.TypedDecisionError):
                    typed.normalize_typed_response(payload)

    def test_canonical_hash_is_stable_ascii_and_rejects_nonfinite_numbers(self) -> None:
        self.assertEqual(
            typed.canonical_hash({"z": chr(0xE9), "a": [2, 1]}),
            "sha256:6793d9a4404421ee0f4501f06deeb5508e33e9957ff30cc3443f3ab031f5a6d4",
        )
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    typed.canonical_hash({"value": value})

    def test_offline_cassette_succeeds_without_network_or_typesafe_key_access(self) -> None:
        state_hash = "sha256:synthetic-state"
        adapter = OfflineFixtureDecisionAdapter({
            f"{state_hash}:JEV_U4_SHADOW_QUESTIONS_V1": copy.deepcopy(VALID_RESPONSE),
        })
        environment = _TypeSafeKeyTrap(dict(os.environ))

        def forbidden_socket(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("offline fixture must not open a socket")

        with (
            mock.patch.object(socket, "socket", side_effect=forbidden_socket) as socket_ctor,
            mock.patch.object(
                socket, "create_connection", side_effect=forbidden_socket
            ) as create_connection,
            mock.patch.object(socket, "getaddrinfo", side_effect=forbidden_socket) as getaddrinfo,
            mock.patch.object(os, "environ", environment),
        ):
            result = run_adapter(
                adapter,
                _adapter_request(state_hash),
                run_id_factory=lambda: "typed_test_run",
            )

        socket_ctor.assert_not_called()
        create_connection.assert_not_called()
        getaddrinfo.assert_not_called()
        self.assertEqual(AgentStatus.SUCCEEDED, result.status)
        self.assertEqual("offline_fixture", result.provider)
        self.assertIsNone(result.model)
        self.assertEqual(UsageStatus.NOT_APPLICABLE, result.usage.status)
        self.assertEqual([], environment.type_safe_key_reads)

    def test_offline_cassette_requires_exact_state_hash(self) -> None:
        adapter = OfflineFixtureDecisionAdapter({})

        result = run_adapter(
            adapter,
            _adapter_request("sha256:synthetic-missing-state"),
            run_id_factory=lambda: "typed_test_run",
        )

        self.assertEqual(AgentStatus.FAILED, result.status)
        self.assertIsNotNone(result.error)
        self.assertEqual("MODEL_UNAVAILABLE", result.error.code)
        self.assertEqual(UsageStatus.NOT_APPLICABLE, result.usage.status)

    def test_disabled_live_adapter_refuses_before_reading_fake_typesafe_key(self) -> None:
        environment = _TypeSafeKeyTrap({"TYPESAFE_API_KEY": "fake-key"})

        with mock.patch.object(os, "environ", environment):
            result = run_adapter(
                DisabledTypeSafeJevAdapter(),
                _adapter_request("sha256:synthetic-state"),
                run_id_factory=lambda: "typed_test_run",
            )

        self.assertEqual(AgentStatus.FAILED, result.status)
        self.assertIsNotNone(result.error)
        self.assertEqual("LIVE_PROVIDER_NOT_INSTALLED", result.error.code)
        self.assertFalse(result.error.retryable)
        self.assertEqual([], environment.type_safe_key_reads)


if __name__ == "__main__":
    unittest.main()
