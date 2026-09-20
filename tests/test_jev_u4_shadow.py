#!/usr/bin/env python3
"""Pure-domain contract tests for the Jev U4 shadow policy and receipts."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))
sys.path.insert(0, str(REPO_ROOT / "experiments" / "research_funnel"))

import typed_decision as typed  # noqa: E402
import jev_u4_shadow as engine  # noqa: E402
import u4_shadow as shadow  # noqa: E402
from adapters.jev_shadow import OfflineFixtureDecisionAdapter  # noqa: E402
from capability import RouteStatus, route  # noqa: E402
from adapters import (  # noqa: E402
    AgentError,
    AgentRequest,
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
    packet: dict | None = None,
    row: dict | None = None,
    input_hash: str | None = None,
    evidence_refs: tuple[str, ...] | None = None,
    run_id: str = "run_a",
    started_at: str = "2026-08-12T09:30:01+00:00",
    finished_at: str = "2026-08-12T09:30:02+00:00",
    duration_ms: int = 1000,
    error: AgentError | None = None,
) -> AgentResult:
    packet = packet or _load("u4-pre-decision.json")
    row = row or next(
        candidate
        for candidate in packet["candidate_rows"]
        if candidate["allowed_for_u4_packet"] is True
    )
    state = shadow.assemble_candidate_state(packet, row)
    state_hash = typed.canonical_hash(state)
    if input_hash is None:
        input_hash = AgentRequest(
            task_id="JEV-U4-SHADOW-ENGINE-001",
            task_type="u4_shadow_decision",
            input_payload={
                "state": state,
                "state_hash": state_hash,
                "question_set": typed.question_set_payload(),
            },
            prompt_version=typed.QUESTION_SET_VERSION,
            evidence_grade="E4",
            network_policy="deny",
        ).input_hash()
    if evidence_refs is None:
        evidence_refs = (
            ()
            if error is not None
            else (f"offline-cassette:{state_hash}:{typed.QUESTION_SET_VERSION}",)
        )
    return AgentResult(
        run_id=run_id,
        task_id="JEV-U4-SHADOW-ENGINE-001",
        task_type="u4_shadow_decision",
        provider="offline_fixture",
        model=None,
        prompt_version=typed.QUESTION_SET_VERSION,
        evidence_grade="E4",
        input_hash=input_hash,
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
        evidence_refs=evidence_refs,
        error=error,
    )


def _reseal(receipt: dict) -> dict:
    receipt["receipt_hash"] = typed.canonical_hash(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )
    return receipt


def _reseal_candidate_state(receipt: dict, index: int) -> dict:
    candidate = receipt["candidate_results"][index]
    candidate["state_hash"] = typed.canonical_hash(candidate["state"])
    return _reseal(receipt)


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
            provider_result=_agent_result(
                packet=self.packet,
                row=self.ready_rows[1],
                error=failure,
            ),
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

    def test_composer_rejects_provider_input_hash_for_another_candidate(self) -> None:
        foreign_result = _agent_result(
            packet=self.packet,
            row=self.ready_rows[1],
        )

        with self.assertRaisesRegex(shadow.ShadowPolicyError, "input_hash"):
            shadow.compose_candidate_result(
                self.packet,
                self.ready_rows[0],
                provider_result=foreign_result,
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
                provider_result = success or _agent_result(packet=self.packet, row=row)
            else:
                provider_result = _agent_result(
                    packet=self.packet,
                    row=row,
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

    def test_authority_contract_cannot_be_mutated_to_accept_action_fields(self) -> None:
        required = {
            "production_authority": False,
            "trade_authority": False,
            "paper_order_authority": False,
            "formal_selection_authority": False,
        }
        runtime_authority = getattr(shadow, "AUTHORITY", None)
        original = copy.deepcopy(runtime_authority)
        try:
            if isinstance(runtime_authority, dict):
                runtime_authority.clear()
                runtime_authority["buy"] = False
            receipt = self._receipt()
        finally:
            if isinstance(runtime_authority, dict):
                runtime_authority.clear()
                runtime_authority.update(original)

        self.assertEqual(required, receipt["authority"])
        malformed = copy.deepcopy(receipt)
        malformed["authority"] = {"buy": False}
        with self.assertRaises(shadow.ShadowPolicyError):
            shadow.verify_receipt(_reseal(malformed))

    def test_verifier_rejects_unsafe_source_and_provider_evidence_refs(self) -> None:
        unsafe_refs = (
            "/private/forbidden-health.json",
            "../../outside.json",
            "file:///private/forbidden.json",
            "C:\\private\\forbidden.json",
        )
        for unsafe in unsafe_refs:
            with self.subTest(kind="source", unsafe=unsafe):
                receipt = self._receipt()
                receipt["source_binding"]["evidence_refs"][
                    "diagnostic_report_ref"
                ] = unsafe
                with self.assertRaises(shadow.ShadowPolicyError):
                    shadow.verify_receipt(_reseal(receipt))
            with self.subTest(kind="provider", unsafe=unsafe):
                receipt = self._receipt()
                receipt["candidate_results"][1]["provider_result"][
                    "evidence_refs"
                ] = [unsafe]
                with self.assertRaises(shadow.ShadowPolicyError):
                    shadow.verify_receipt(_reseal(receipt))

    def test_verifier_rejects_invalid_peak_and_battery_state_semantics(self) -> None:
        invented_peak = self._receipt()
        invented_peak["candidate_results"][0]["state"]["peak_earnings"][
            "flag"
        ] = False

        invalid_peak_reason = self._receipt()
        invalid_peak_reason["candidate_results"][0]["state"]["peak_earnings"][
            "reason"
        ] = "BUY"

        invalid_battery = self._receipt()
        invalid_battery["candidate_results"][0]["state"][
            "battery_dimension_verdicts"
        ]["资金"] = "BUY"

        for label, receipt in (
            ("invented_peak", invented_peak),
            ("invalid_peak_reason", invalid_peak_reason),
            ("invalid_battery", invalid_battery),
        ):
            with self.subTest(label=label):
                with self.assertRaises(shadow.ShadowPolicyError):
                    shadow.verify_receipt(_reseal_candidate_state(receipt, 0))

    def test_provider_input_hash_binds_exact_state_and_question_set(self) -> None:
        receipt = self._receipt()
        eligible = [
            row
            for row in self.packet["candidate_rows"]
            if row["allowed_for_u4_packet"] is True
        ]
        foreign_state_hash = _agent_result(
            packet=self.packet,
            row=eligible[1],
        ).input_hash

        state = receipt["candidate_results"][1]["state"]
        state_hash = receipt["candidate_results"][1]["state_hash"]
        wrong_questions = typed.question_set_payload()
        wrong_questions["questions"][0]["kind"] = "SCORE"
        foreign_question_hash = AgentRequest(
            task_id="JEV-U4-SHADOW-ENGINE-001",
            task_type="u4_shadow_decision",
            input_payload={
                "state": state,
                "state_hash": state_hash,
                "question_set": wrong_questions,
            },
            prompt_version=typed.QUESTION_SET_VERSION,
            evidence_grade="E4",
            network_policy="deny",
        ).input_hash()

        for label, input_hash in (
            ("foreign_state", foreign_state_hash),
            ("foreign_questions", foreign_question_hash),
        ):
            with self.subTest(label=label):
                tampered = self._receipt()
                tampered["candidate_results"][1]["provider_result"][
                    "input_hash"
                ] = input_hash
                with self.assertRaisesRegex(shadow.ShadowPolicyError, "input_hash"):
                    shadow.verify_receipt(_reseal(tampered))

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

    def test_receipt_binds_the_exact_canonical_request_hash(self) -> None:
        receipt = self._receipt()
        expected = typed.canonical_hash(self.request)
        mutations = {
            "schema": "ar.jev_u4_shadow_request.v2",
            "command_id": "another-command",
            "task_id": "another-task",
            "mode": "POLICY_PREVIEW",
            "observed_at": "2026-08-12T10:30:00+00:00",
            "packet_ref": "alternate/u4-pre-decision.json",
            "bundle_ref": "alternate/data_history/funnel/run",
            "feature_health_ref": "alternate/feature-health.json",
            "funnel_health_ref": "alternate/funnel-health.json",
            "diagnostic_ref": "alternate/diagnostic.json",
            "industry": "BANK",
            "method_version": "RESEARCH_CLOSED_LOOP_V2",
            "cyclical_flags_ref": "alternate/cyclical.json",
            "fixture_id": "another-fixture",
        }

        self.assertEqual(expected, receipt["identity"]["request_hash"])
        self.assertEqual(set(self.request), set(mutations))
        for field, value in mutations.items():
            with self.subTest(field=field):
                self.assertNotEqual(
                    expected,
                    typed.canonical_hash({**self.request, field: value}),
                )


class _CountingAdapter:
    provider = "offline_fixture"
    model = None

    def __init__(self, cassettes: dict) -> None:
        self.calls = 0
        self._delegate = OfflineFixtureDecisionAdapter(cassettes)

    def execute(self, request: AgentRequest):
        self.calls += 1
        return self._delegate.execute(request)


class _ExplodingAdapter:
    provider = "offline_fixture"
    model = None

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, _request: AgentRequest):
        self.calls += 1
        raise AssertionError("blocked requests must not execute an adapter")


class JevU4ShadowEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        temporary_root = Path(self.temporary.name)
        self.artifact_root = temporary_root / "synthetic-mixed"
        shutil.copytree(FIXTURE_ROOT, self.artifact_root)
        self.state_root = temporary_root / "state"
        self.request = _load("request.json")
        cassette_payload = _load("cassettes.json")
        self.cassettes = {
            key: copy.deepcopy(value)
            for key, value in cassette_payload.items()
            if key != "_meta"
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _adapter(self, cassettes: dict | None = None) -> OfflineFixtureDecisionAdapter:
        return OfflineFixtureDecisionAdapter(
            self.cassettes if cassettes is None else cassettes
        )

    def _run(
        self,
        request: dict | None = None,
        *,
        adapter=None,
        race_injector=None,
    ) -> dict:
        return engine.run_shadow(
            copy.deepcopy(request if request is not None else self.request),
            artifact_root=self.artifact_root,
            state_root=self.state_root,
            adapter=adapter or self._adapter(),
            race_injector=race_injector,
        )

    def test_request_schema_and_root_relative_references_are_exact(self) -> None:
        self.assertEqual(self.request, engine.validate_request(self.request))

        extra = {**self.request, "provider": "typesafe_jev"}
        with self.assertRaisesRegex(engine.ShadowRunError, "SPEC_BLOCKED"):
            engine.validate_request(extra)

        for field, value in (("mode", []), ("fixture_id", [])):
            with self.subTest(field=field):
                malformed = {**self.request, field: value}
                with self.assertRaisesRegex(engine.ShadowRunError, "SPEC_BLOCKED"):
                    engine.validate_request(malformed)

        for value in (
            "/private/u4-pre-decision.json",
            "../u4-pre-decision.json",
            "nested/../../u4-pre-decision.json",
            "nested/./u4-pre-decision.json",
            "nested//u4-pre-decision.json",
            "C:\\private\\u4-pre-decision.json",
        ):
            with self.subTest(value=value):
                unsafe = {**self.request, "packet_ref": value}
                with self.assertRaisesRegex(engine.ShadowRunError, "SPEC_BLOCKED"):
                    engine.validate_request(unsafe)

    def test_safe_ref_rejects_symlink_roots_and_files(self) -> None:
        real_root = Path(self.temporary.name) / "real-root"
        real_root.mkdir()
        (real_root / "packet.json").write_text("{}", encoding="utf-8")
        linked_root = Path(self.temporary.name) / "linked-root"
        linked_root.symlink_to(real_root, target_is_directory=True)
        linked_file = real_root / "linked.json"
        linked_file.symlink_to(real_root / "packet.json")

        with self.assertRaisesRegex(engine.ShadowRunError, "SPEC_BLOCKED"):
            engine.safe_ref(linked_root, "packet.json")
        with self.assertRaisesRegex(engine.ShadowRunError, "SPEC_BLOCKED"):
            engine.safe_ref(real_root, "linked.json")

    def test_run_reopens_the_exact_packet_with_exact_validator_arguments(self) -> None:
        calls: list[tuple[dict, dict]] = []

        def record(packet: dict, **kwargs: object) -> None:
            self.assertEqual(
                (self.artifact_root / self.request["packet_ref"]).read_bytes(),
                Path(self.request["packet_ref"]).read_bytes(),
            )
            self.assertEqual(
                (self.artifact_root / self.request["diagnostic_ref"]).read_bytes(),
                Path(kwargs["diagnostic_ref"]).read_bytes(),
            )
            calls.append((packet, kwargs))

        with mock.patch.object(engine.u4_pre_decision, "validate_packet", record):
            receipt = self._run()

        self.assertEqual(1, len(calls))
        packet, kwargs = calls[0]
        self.assertEqual(
            json.loads((self.artifact_root / self.request["packet_ref"]).read_text()),
            packet,
        )
        self.assertEqual(
            {
                "bundle_dir": Path(self.request["bundle_ref"]),
                "feature_health_path": Path(self.request["feature_health_ref"]),
                "funnel_health_path": Path(self.request["funnel_health_ref"]),
                "diagnostic_ref": self.request["diagnostic_ref"],
                "industry": self.request["industry"],
                "method_version": self.request["method_version"],
                "cyclical_flags_path": None,
            },
            kwargs,
        )
        self.assertEqual("ar.jev_u4_shadow_receipt.v1", receipt["schema"])

    def test_mixed_method_version_and_modified_packet_fail_closed(self) -> None:
        mixed = {**self.request, "method_version": "RESEARCH_CLOSED_LOOP_V2"}
        with self.assertRaisesRegex(engine.ShadowRunError, "SPEC_BLOCKED"):
            self._run(mixed)

        packet_path = self.artifact_root / self.request["packet_ref"]
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        packet["candidate_rows"][0]["display_name"] = "Modified"
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        with self.assertRaisesRegex(engine.ShadowRunError, "SPEC_BLOCKED"):
            self._run()

    def test_policy_preview_without_cassette_never_fabricates_output(self) -> None:
        request = {**self.request, "mode": "POLICY_PREVIEW", "fixture_id": None}
        receipt = self._run(request, adapter=self._adapter({}))
        eligible = [
            row
            for row in receipt["candidate_results"]
            if row["gate"]["state"] == "ELIGIBLE_FOR_TYPED_JUDGMENT"
        ]

        self.assertGreater(len(eligible), 0)
        for row in eligible:
            self.assertEqual("MODEL_UNAVAILABLE", row["provider_result"]["status"])
            self.assertIsNone(row["typed_answers"])
            self.assertIsNone(row["shadow_outcome"])
        self.assertFalse(receipt["provider"]["provider_contacted"])

    def test_offline_capability_is_deterministic_shadow_only(self) -> None:
        registry = engine.offline_capability_registry(
            artifact_root=self.artifact_root,
            state_root=self.state_root,
        )
        self.assertEqual(1, len(registry.records))
        capability = registry.records[0]
        request = engine.route_request(
            self.request,
            artifact_root=self.artifact_root,
            state_root=self.state_root,
        )
        decision = route(registry, request)

        self.assertEqual("SHADOW_ONLY", capability.status.value)
        self.assertTrue(capability.deterministic)
        self.assertEqual(frozenset(), capability.tool_access)
        self.assertEqual(frozenset({"deny"}), capability.network_access)
        self.assertEqual("MEDIUM", request.risk_level)
        self.assertEqual("deny", request.network_policy)
        self.assertEqual(RouteStatus.SELECTED, decision.status)
        self.assertEqual("offline_fixture", decision.selected_agent)

    def test_capability_route_is_bound_to_the_supplied_root_objects(self) -> None:
        other_artifact = Path(self.temporary.name) / "other-artifact"
        other_state = Path(self.temporary.name) / "other-state"
        shutil.copytree(self.artifact_root, other_artifact)
        other_state.mkdir()
        registry = engine.offline_capability_registry(
            artifact_root=self.artifact_root,
            state_root=self.state_root,
        )
        other_request = engine.route_request(
            self.request,
            artifact_root=other_artifact,
            state_root=other_state,
        )

        decision = route(registry, other_request)

        self.assertEqual(RouteStatus.NO_ELIGIBLE_CAPABILITY, decision.status)
        self.assertIsNone(decision.selected_agent)

    def test_artifact_parent_swap_cannot_redirect_packet_read(self) -> None:
        parent = self.artifact_root / "packet-parent"
        moved = self.artifact_root / "packet-parent-moved"
        parent.mkdir()
        packet_name = "u4-pre-decision.json"
        original_bytes = (self.artifact_root / packet_name).read_bytes()
        (parent / packet_name).write_bytes(original_bytes)
        external = Path(self.temporary.name) / "external-artifacts"
        external.mkdir()
        (external / packet_name).write_bytes(original_bytes + b"\n")
        request = {**self.request, "packet_ref": f"packet-parent/{packet_name}"}
        fired = False

        def swap(point: str) -> None:
            nonlocal fired
            if point == "artifact_packet_parent_opened" and not fired:
                fired = True
                parent.rename(moved)
                parent.symlink_to(external, target_is_directory=True)

        receipt = self._run(request, race_injector=swap)

        self.assertTrue(fired)
        self.assertEqual(
            "sha256:" + hashlib.sha256(original_bytes).hexdigest(),
            receipt["source_binding"]["packet_file_hash"],
        )

    def test_import_and_unsupported_mode_do_not_read_provider_environment(self) -> None:
        script = """
import json
import os
import sys

forbidden = {
    "TYPESAFE_API_KEY",
    "DEEPSEEK_API_KEY",
    "LLM_USD_CNY",
    "DEEPSEEK_V4_FLASH_CACHE_HIT_USD_PER_1M",
    "DEEPSEEK_V4_FLASH_CACHE_MISS_USD_PER_1M",
    "DEEPSEEK_V4_FLASH_OUTPUT_USD_PER_1M",
    "DEEPSEEK_V4_PRO_CACHE_HIT_USD_PER_1M",
    "DEEPSEEK_V4_PRO_CACHE_MISS_USD_PER_1M",
    "DEEPSEEK_V4_PRO_OUTPUT_USD_PER_1M",
}
original = os.environ

class Trap(dict):
    def __getitem__(self, key):
        if key in forbidden:
            raise AssertionError(f"environment key read: {key}")
        return original[key]

    def get(self, key, default=None):
        if key in forbidden:
            raise AssertionError(f"environment key read: {key}")
        return original.get(key, default)

    def __contains__(self, key):
        if key in forbidden:
            raise AssertionError(f"environment key read: {key}")
        return key in original

os.environ = Trap()
sys.path.insert(0, %r)
import jev_u4_shadow as engine

request = {
    "schema": "ar.jev_u4_shadow_request.v1",
    "command_id": "unsupported-import-probe",
    "task_id": "JEV-U4-SHADOW-ENGINE-001",
    "mode": "TYPESAFE_JEV",
    "observed_at": "2026-08-12T09:30:00+00:00",
    "packet_ref": "packet.json",
    "bundle_ref": "bundle",
    "feature_health_ref": "feature.json",
    "funnel_health_ref": "funnel.json",
    "diagnostic_ref": "diagnostic.json",
    "industry": "TECH",
    "method_version": "RESEARCH_CLOSED_LOOP_V1",
    "cyclical_flags_ref": None,
    "fixture_id": None,
}
try:
    engine.validate_request(request)
except engine.ShadowRunError as exc:
    print(json.dumps(exc.to_dict(), sort_keys=True))
""" % str(REPO_ROOT / "scripts/llm")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "LIVE_PROVIDER_NOT_INSTALLED",
            json.loads(result.stdout)["code"],
        )

    def test_unsupported_modes_and_paths_block_before_resolution_or_execution(self) -> None:
        cases = (
            ("TYPESAFE_JEV", "LIVE_PROVIDER_NOT_INSTALLED"),
            ("PRODUCTION", "SPEC_BLOCKED"),
            ("provider_only", "SPEC_BLOCKED"),
        )
        for mode, expected in cases:
            with self.subTest(mode=mode):
                adapter = _ExplodingAdapter()
                request = {**self.request, "mode": mode}
                with (
                    mock.patch.object(
                        engine,
                        "resolve_request_paths",
                        side_effect=AssertionError("path resolution reached"),
                    ),
                    mock.patch.object(
                        engine,
                        "route",
                        side_effect=AssertionError("router reached"),
                    ),
                ):
                    with self.assertRaisesRegex(engine.ShadowRunError, expected):
                        self._run(request, adapter=adapter)
                self.assertEqual(0, adapter.calls)

        adapter = _ExplodingAdapter()
        outside = {**self.request, "packet_ref": "../outside.json"}
        with mock.patch.object(
            engine,
            "resolve_request_paths",
            side_effect=AssertionError("path resolution reached"),
        ):
            with self.assertRaisesRegex(engine.ShadowRunError, "SPEC_BLOCKED"):
                self._run(outside, adapter=adapter)
        self.assertEqual(0, adapter.calls)

    def test_each_eligible_candidate_executes_the_adapter_exactly_once(self) -> None:
        adapter = _CountingAdapter(self.cassettes)
        receipt = self._run(adapter=adapter)
        eligible_count = receipt["batch_summary"]["eligible_count"]

        self.assertEqual(eligible_count, adapter.calls)
        self.assertEqual(
            receipt["batch_summary"]["total_candidates"] - eligible_count,
            receipt["batch_summary"]["provider_result_counts"]["NOT_CALLED"],
        )

    def test_receipt_is_absolute_root_free_network_free_and_key_free(self) -> None:
        def forbidden_socket(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("offline shadow run must not use the network")

        with (
            mock.patch("socket.socket", side_effect=forbidden_socket),
            mock.patch("socket.create_connection", side_effect=forbidden_socket),
            mock.patch("socket.getaddrinfo", side_effect=forbidden_socket),
        ):
            receipt = self._run()

        encoded = shadow.canonical_receipt_bytes(receipt)
        self.assertNotIn(os.fsencode(self.artifact_root), encoded)
        self.assertNotIn(os.fsencode(self.state_root), encoded)
        self.assertNotIn(b"TYPESAFE_API_KEY", encoded)


class JevU4ShadowStoreTests(JevU4ShadowEngineTests):
    def setUp(self) -> None:
        super().setUp()
        self.receipt = self._run()

    def test_concurrent_identical_writes_create_one_row_and_one_receipt(self) -> None:
        store = engine.ShadowStore(self.state_root)

        def write_once(_index: int) -> dict:
            return store.write(self.request, self.receipt)

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(write_once, range(12)))

        dispositions = [result["disposition"] for result in results]
        self.assertEqual(1, dispositions.count("CREATED"))
        self.assertEqual(11, dispositions.count("IDEMPOTENT"))
        canonical = shadow.canonical_receipt_bytes(self.receipt)
        self.assertTrue(
            all(shadow.canonical_receipt_bytes(result["receipt"]) == canonical for result in results)
        )
        with sqlite3.connect(store.database_path) as db:
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0])
        self.assertEqual(canonical, store.receipt_path(self.request["command_id"]).read_bytes())

    def test_command_id_reuse_with_changed_observed_at_is_a_conflict(self) -> None:
        store = engine.ShadowStore(self.state_root)
        store.write(self.request, self.receipt)
        changed_request = {
            **self.request,
            "observed_at": "2026-08-12T10:30:00+00:00",
        }
        changed_receipt = self._run(changed_request)

        with self.assertRaisesRegex(engine.ShadowRunError, "COMMAND_ID_CONFLICT"):
            store.write(changed_request, changed_receipt)

    def test_read_detects_disk_receipt_tampering(self) -> None:
        store = engine.ShadowStore(self.state_root)
        store.write(self.request, self.receipt)
        receipt_path = store.receipt_path(self.request["command_id"])
        receipt_path.write_bytes(receipt_path.read_bytes() + b" ")

        with self.assertRaisesRegex(engine.ShadowRunError, "INTEGRITY_ERROR"):
            store.read(self.request["command_id"])

    def test_read_rebinds_every_stored_request_field_to_receipt_hash(self) -> None:
        store = engine.ShadowStore(self.state_root)
        store.write(self.request, self.receipt)
        changed_request = {
            **self.request,
            "packet_ref": "alternate/u4-pre-decision.json",
        }
        request_bytes = json.dumps(
            changed_request,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        with sqlite3.connect(store.database_path) as db:
            db.execute(
                "UPDATE receipts SET request_hash = ?, request_bytes = ? WHERE command_id = ?",
                (
                    typed.canonical_hash(changed_request),
                    request_bytes,
                    self.request["command_id"],
                ),
            )

        with self.assertRaisesRegex(engine.ShadowRunError, "INTEGRITY_ERROR"):
            store.read(self.request["command_id"])

    def test_database_parent_swap_cannot_redirect_sqlite_or_receipts(self) -> None:
        state_root = Path(self.temporary.name) / "database-race-state"
        outside = Path(self.temporary.name) / "database-race-outside"
        outside.mkdir()
        base = state_root / "jev-u4-shadow"
        moved = state_root / "jev-u4-shadow-moved"
        fired = False

        def swap(point: str) -> None:
            nonlocal fired
            if point == "database_parent_opened" and not fired:
                fired = True
                base.rename(moved)
                base.symlink_to(outside, target_is_directory=True)

        store = engine.ShadowStore(state_root, race_injector=swap)
        result = store.write(self.request, self.receipt)

        self.assertTrue(fired)
        self.assertEqual("CREATED", result["disposition"])
        self.assertFalse(any(outside.iterdir()))
        self.assertTrue((moved / "shadow.sqlite3").is_file())
        self.assertTrue(
            (moved / self.request["command_id"] / "receipt.json").is_file()
        )

    def test_receipt_parent_swap_fails_without_redirect_or_row_commit(self) -> None:
        state_root = Path(self.temporary.name) / "receipt-race-state"
        outside = Path(self.temporary.name) / "receipt-race-outside"
        outside.mkdir()
        armed = False
        fired = False

        def swap(point: str) -> None:
            nonlocal fired
            if point == "receipt_parent_opened" and armed and not fired:
                fired = True
                command_dir = state_root / "jev-u4-shadow" / self.request["command_id"]
                moved = command_dir.with_name(command_dir.name + "-moved")
                command_dir.rename(moved)
                command_dir.symlink_to(outside, target_is_directory=True)

        store = engine.ShadowStore(state_root, race_injector=swap)
        armed = True
        with self.assertRaisesRegex(engine.ShadowRunError, "INTEGRITY_ERROR"):
            store.write(self.request, self.receipt)

        self.assertTrue(fired)
        self.assertFalse((outside / "receipt.json").exists())
        with sqlite3.connect(store.database_path) as database:
            self.assertEqual(
                0,
                database.execute("SELECT COUNT(*) FROM receipts").fetchone()[0],
            )

    def test_command_directory_parent_is_fsynced_before_row_commit(self) -> None:
        events: list[object] = []
        store = engine.ShadowStore(
            Path(self.temporary.name) / "fsync-order-state",
            fault_injector=events.append,
        )
        base_identity = (
            store.base_directory.stat().st_dev,
            store.base_directory.stat().st_ino,
        )
        original_fsync = os.fsync

        def record_fsync(descriptor: int) -> None:
            info = os.fstat(descriptor)
            events.append(("fsync", info.st_dev, info.st_ino))
            original_fsync(descriptor)

        with mock.patch.object(engine.os, "fsync", record_fsync):
            store.write(self.request, self.receipt)

        base_fsync = ("fsync", *base_identity)
        self.assertIn(base_fsync, events)
        self.assertLess(events.index(base_fsync), events.index("after_insert"))

    def test_crashes_after_publish_or_insert_converge_by_exact_orphan_adoption(self) -> None:
        for failure_point in ("after_publish", "after_insert"):
            with self.subTest(failure_point=failure_point):
                state_root = Path(self.temporary.name) / failure_point
                fired = False

                def fail_once(point: str) -> None:
                    nonlocal fired
                    if point == failure_point and not fired:
                        fired = True
                        raise RuntimeError(f"injected {failure_point}")

                crashing = engine.ShadowStore(state_root, fault_injector=fail_once)
                with self.assertRaisesRegex(RuntimeError, failure_point):
                    crashing.write(self.request, self.receipt)
                receipt_path = crashing.receipt_path(self.request["command_id"])
                self.assertEqual(shadow.canonical_receipt_bytes(self.receipt), receipt_path.read_bytes())
                with sqlite3.connect(crashing.database_path) as db:
                    self.assertEqual(0, db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0])

                recovered = engine.ShadowStore(state_root)
                result = recovered.write(self.request, self.receipt)
                self.assertEqual("CREATED", result["disposition"])
                self.assertEqual(self.receipt, recovered.read(self.request["command_id"]))

    def test_conflicting_orphan_is_never_overwritten_or_deleted(self) -> None:
        state_root = Path(self.temporary.name) / "conflicting-orphan"

        def fail_after_publish(point: str) -> None:
            if point == "after_publish":
                raise RuntimeError("injected after_publish")

        crashing = engine.ShadowStore(state_root, fault_injector=fail_after_publish)
        with self.assertRaises(RuntimeError):
            crashing.write(self.request, self.receipt)
        receipt_path = crashing.receipt_path(self.request["command_id"])
        original_bytes = receipt_path.read_bytes()
        changed_request = {
            **self.request,
            "observed_at": "2026-08-12T10:30:00+00:00",
        }
        changed_receipt = self._run(changed_request)

        with self.assertRaisesRegex(engine.ShadowRunError, "INTEGRITY_ERROR"):
            engine.ShadowStore(state_root).write(changed_request, changed_receipt)
        self.assertEqual(original_bytes, receipt_path.read_bytes())

    def test_store_refuses_symlinked_root_database_directory_and_receipt(self) -> None:
        real_root = Path(self.temporary.name) / "real-state"
        real_root.mkdir()
        linked_root = Path(self.temporary.name) / "linked-state"
        linked_root.symlink_to(real_root, target_is_directory=True)
        with self.assertRaisesRegex(engine.ShadowRunError, "INTEGRITY_ERROR"):
            engine.ShadowStore(linked_root)

        base_target = Path(self.temporary.name) / "base-target"
        base_target.mkdir()
        base_state = Path(self.temporary.name) / "base-state"
        base_state.mkdir()
        (base_state / "jev-u4-shadow").symlink_to(base_target, target_is_directory=True)
        with self.assertRaisesRegex(engine.ShadowRunError, "INTEGRITY_ERROR"):
            engine.ShadowStore(base_state)

        store = engine.ShadowStore(Path(self.temporary.name) / "db-state")
        store.database_path.unlink()
        store.database_path.symlink_to(Path(self.temporary.name) / "foreign.sqlite3")
        with self.assertRaisesRegex(engine.ShadowRunError, "INTEGRITY_ERROR"):
            store.write(self.request, self.receipt)

        receipt_store = engine.ShadowStore(Path(self.temporary.name) / "receipt-state")
        receipt_dir = receipt_store.receipt_path(self.request["command_id"]).parent
        receipt_dir.mkdir()
        foreign = Path(self.temporary.name) / "foreign-receipt.json"
        foreign.write_text("{}", encoding="utf-8")
        receipt_store.receipt_path(self.request["command_id"]).symlink_to(foreign)
        with self.assertRaisesRegex(engine.ShadowRunError, "INTEGRITY_ERROR"):
            receipt_store.write(self.request, self.receipt)

        read_store = engine.ShadowStore(Path(self.temporary.name) / "read-state")
        read_store.write(self.request, self.receipt)
        command_dir = read_store.receipt_path(self.request["command_id"]).parent
        moved_dir = command_dir.with_name(command_dir.name + "-moved")
        command_dir.rename(moved_dir)
        command_dir.symlink_to(moved_dir, target_is_directory=True)
        with self.assertRaisesRegex(engine.ShadowRunError, "INTEGRITY_ERROR"):
            read_store.read(self.request["command_id"])

    def test_cli_run_verify_and_evaluate_placeholder(self) -> None:
        request_path = self.artifact_root / "request.json"
        script = REPO_ROOT / "scripts/llm/jev_u4_shadow.py"
        run_result = subprocess.run(
            [
                sys.executable,
                str(script),
                "run",
                "--request",
                str(request_path),
                "--artifact-root",
                str(self.artifact_root),
                "--state-root",
                str(self.state_root),
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, run_result.returncode, run_result.stderr)
        run_payload = json.loads(run_result.stdout)
        self.assertEqual("CREATED", run_payload["disposition"])

        verify_result = subprocess.run(
            [
                sys.executable,
                str(script),
                "verify",
                "--state-root",
                str(self.state_root),
                "--command-id",
                self.request["command_id"],
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, verify_result.returncode, verify_result.stderr)
        self.assertEqual(self.receipt, json.loads(verify_result.stdout))

        evaluate_result = subprocess.run(
            [
                sys.executable,
                str(script),
                "evaluate",
                "--state-root",
                str(self.state_root),
                "--command-id",
                self.request["command_id"],
                "--ledger",
                str(self.artifact_root / "not-used.jsonl"),
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(0, evaluate_result.returncode)
        self.assertEqual(
            "EVALUATION_NOT_INSTALLED",
            json.loads(evaluate_result.stderr)["code"],
        )

    def test_cli_argument_errors_are_canonical_json(self) -> None:
        script = REPO_ROOT / "scripts/llm/jev_u4_shadow.py"
        result = subprocess.run(
            [sys.executable, str(script), "verify"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("SPEC_BLOCKED", json.loads(result.stderr)["code"])

    def test_cli_help_is_refused_as_canonical_json(self) -> None:
        script = REPO_ROOT / "scripts/llm/jev_u4_shadow.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertEqual("SPEC_BLOCKED", json.loads(result.stderr)["code"])


if __name__ == "__main__":
    unittest.main()
