#!/usr/bin/env python3
"""Executable contract tests for provider-neutral typed shadow decisions."""

from __future__ import annotations

import copy
import json
import math
import os
import re
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))
sys.path.insert(0, str(REPO_ROOT / "experiments" / "research_funnel"))

import typed_decision as typed  # noqa: E402
import u4_pre_decision as pre  # noqa: E402
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

FIXTURE_ROOT = REPO_ROOT / "scripts/llm/fixtures/jev_u4_shadow/synthetic-mixed"
_AUTHORITATIVE_FIXTURE_FILES = (
    "data_history",
    "public",
    "u4-pre-decision.json",
    "u4_pre_decision_diagnostic.json",
)


def _fixture_candidate_state(packet: dict, row: dict) -> dict:
    return {
        "packet_hash": packet["packet_hash"],
        "as_of": packet["as_of"],
        "method_version": packet["method_version"],
        "source_publication": packet["source_publication"],
        "ticker": row["ts_code"],
        "display_name": row["display_name"],
        "candidate_status": row["candidate_status"],
        "causal_cluster_id": row["causal_cluster_id"],
        "causal_cluster_identity_state": row["causal_cluster_identity_state"],
        "positive_channels": row["positive_channels"],
        "missing_evidence": row["missing_evidence"],
        "peak_earnings": row["peak_earnings"],
        "battery_dimension_verdicts": row["battery_dimension_verdicts"],
        "u2_candidate_row_hash": row["u2_candidate_row_hash"],
        "u3_battery_row_hash": row["u3_battery_row_hash"],
        "question_for_junyan": row["question_for_junyan"],
        "diagnostic_summary": packet["diagnostic"],
    }


def _authoritative_fixture_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for relative in _AUTHORITATIVE_FIXTURE_FILES:
        path = root / relative
        if path.is_file():
            paths.append(Path(relative))
        else:
            paths.extend(child.relative_to(root) for child in path.rglob("*") if child.is_file())
    return sorted(paths)


def _generate_authoritative_fixture(root: Path, seed: int) -> None:
    script = """
import json
import sys
from pathlib import Path

output_root = Path(sys.argv[1])
repo_root = Path(sys.argv[2])
sys.path.insert(0, str(repo_root / "tests"))

import test_u4_pre_decision_runtime as runtime

packet, diagnostic, _bundle, _feature_health, _funnel_health = runtime._build(
    output_root, red_flag=True
)
for name, payload in (
    ("u4-pre-decision.json", packet),
    ("u4_pre_decision_diagnostic.json", diagnostic),
):
    (output_root / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\\n",
        encoding="utf-8",
    )
"""
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = str(seed)
    environment["PYTHONPYCACHEPREFIX"] = "/private/tmp/pycache-jev-u4-shadow-task3"
    subprocess.run(
        [sys.executable, "-c", script, str(root), str(REPO_ROOT)],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )


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


def _adapter_request(state_hash: str, state: dict | None = None) -> AgentRequest:
    return AgentRequest(
        task_id="JEV-U4-SHADOW-TYPED-TEST",
        task_type="u4_shadow_fixture",
        input_payload={
            "state": state or {
                "sample_purpose": "WORKFLOW_DEBUG",
                "candidate": "synthetic",
            },
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

    def test_committed_fixture_reopens_and_exercises_one_cassette_hit_and_miss(self) -> None:
        request = json.loads((FIXTURE_ROOT / "request.json").read_text(encoding="utf-8"))
        packet = json.loads(
            (FIXTURE_ROOT / request["packet_ref"]).read_text(encoding="utf-8")
        )
        pre.validate_packet(
            packet,
            bundle_dir=FIXTURE_ROOT / request["bundle_ref"],
            feature_health_path=FIXTURE_ROOT / request["feature_health_ref"],
            funnel_health_path=FIXTURE_ROOT / request["funnel_health_ref"],
            diagnostic_ref=request["diagnostic_ref"],
            industry=request["industry"],
            method_version=request["method_version"],
        )

        eligible = [row for row in packet["candidate_rows"] if row["allowed_for_u4_packet"]]
        self.assertEqual(2, len(eligible))
        self.assertTrue(
            all(re.fullmatch(r"T[0-9]{6}\.SZ", row["ts_code"]) for row in packet["candidate_rows"])
        )
        self.assertTrue(
            all(
                row["display_name"] == f"Name {int(row['ts_code'][1:7])}"
                for row in packet["candidate_rows"]
            )
        )
        battery = json.loads(
            (
                FIXTURE_ROOT
                / request["bundle_ref"]
                / "candidate_battery.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual("FIXTURE", battery["provider_state"])
        self.assertTrue(
            all(row["dims"]["基本面"]["fixture"] is True for row in battery["results"])
        )
        projected = json.loads(
            (
                FIXTURE_ROOT
                / request["bundle_ref"]
                / "security_registry_projected.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(
            all(
                re.fullmatch(r"T[0-9]{6}\.SZ", row["ts_code"])
                and row["name"] == f"Name {int(row['ts_code'][1:7])}"
                for row in projected["rows"]
            )
        )
        scan = json.loads(
            (
                FIXTURE_ROOT
                / request["bundle_ref"]
                / "all_market_scan.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(
            all(re.fullmatch(r"T[0-9]{6}\.SZ", row["ts_code"]) for row in scan["rows"])
        )

        cassette_payload = json.loads(
            (FIXTURE_ROOT / "cassettes.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {"fixture_id": "synthetic-mixed", "sample_purpose": "WORKFLOW_DEBUG"},
            cassette_payload["_meta"],
        )
        cassettes = {key: value for key, value in cassette_payload.items() if key != "_meta"}
        self.assertEqual(1, len(cassettes))
        cassette_key, cassette_response = next(iter(cassettes.items()))
        self.assertEqual(cassette_response, typed.normalize_typed_response(cassette_response))

        states = [_fixture_candidate_state(packet, row) for row in eligible]
        state_hashes = [typed.canonical_hash(state) for state in states]
        self.assertEqual(
            {f"{state_hashes[0]}:{typed.QUESTION_SET_VERSION}"},
            {cassette_key},
        )
        adapter = OfflineFixtureDecisionAdapter(cassettes)
        cassette_result = run_adapter(
            adapter,
            _adapter_request(state_hashes[0], states[0]),
            run_id_factory=lambda: "fixture_cassette_hit",
        )
        missing_result = run_adapter(
            adapter,
            _adapter_request(state_hashes[1], states[1]),
            run_id_factory=lambda: "fixture_cassette_miss",
        )
        self.assertEqual(AgentStatus.SUCCEEDED, cassette_result.status)
        self.assertEqual(AgentStatus.FAILED, missing_result.status)
        self.assertIsNotNone(missing_result.error)
        self.assertEqual("MODEL_UNAVAILABLE", missing_result.error.code)

    def test_committed_fixture_is_byte_reproducible_under_hash_seeds_zero_and_one(self) -> None:
        expected_paths = _authoritative_fixture_paths(FIXTURE_ROOT)
        for seed in (0, 1):
            with self.subTest(seed=seed), tempfile.TemporaryDirectory() as temporary:
                generated_root = Path(temporary)
                _generate_authoritative_fixture(generated_root, seed)
                self.assertEqual(expected_paths, _authoritative_fixture_paths(generated_root))
                for relative in expected_paths:
                    self.assertEqual(
                        (FIXTURE_ROOT / relative).read_bytes(),
                        (generated_root / relative).read_bytes(),
                        relative.as_posix(),
                    )


if __name__ == "__main__":
    unittest.main()
