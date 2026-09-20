#!/usr/bin/env python3
"""Executable contract tests for provider-neutral typed shadow decisions."""

from __future__ import annotations

import copy
import math
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))

import typed_decision as typed  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
