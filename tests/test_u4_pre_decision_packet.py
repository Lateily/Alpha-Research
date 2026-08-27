#!/usr/bin/env python3
"""Offline executable checks for the U4 pre-decision packet contract."""

from __future__ import annotations

import json
import re
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs/research/contracts/u4_pre_decision_packet.v0.schema.json"
DOC_PATH = ROOT / "docs/research/prospective/U4_PRE_DECISION_PACKET_V0.md"
CI_PATH = ROOT / ".github/workflows/python-ci.yml"


def _strict_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key: {key}")
        out[key] = value
    return out


SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)


def _resolve_ref(ref: str) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise AssertionError(f"external refs are not allowed in this contract test: {ref}")
    value: Any = SCHEMA
    for part in ref[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise AssertionError(f"unsupported schema type in test validator: {expected}")


def _errors(value: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    if "$ref" in schema:
        return _errors(value, _resolve_ref(schema["$ref"]), path)
    errors: list[str] = []
    if "oneOf" in schema:
        matches = sum(not _errors(value, item, path) for item in schema["oneOf"])
        if matches != 1:
            errors.append(f"{path}: oneOf matched {matches} branches")
        return errors
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is outside enum")
    expected = schema.get("type")
    if expected is not None:
        types = [expected] if isinstance(expected, str) else expected
        if not any(_type_matches(value, item) for item in types):
            return errors + [f"{path}: wrong type"]
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}: additional property {key}")
        for key, child in properties.items():
            if key in value:
                errors.extend(_errors(value[key], child, f"{path}.{key}"))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: too many items")
        if schema.get("uniqueItems"):
            keys = [json.dumps(item, sort_keys=True, ensure_ascii=True) for item in value]
            if len(keys) != len(set(keys)):
                errors.append(f"{path}: duplicate items")
        if "prefixItems" in schema:
            for index, item_schema in enumerate(schema["prefixItems"]):
                if index < len(value):
                    errors.extend(_errors(value[index], item_schema, f"{path}[{index}]"))
        if schema.get("items") is False and "prefixItems" in schema and len(value) > len(schema["prefixItems"]):
            errors.append(f"{path}: too many prefix items")
        elif isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(_errors(item, schema["items"], f"{path}[{index}]"))
        if "contains" in schema:
            if not any(not _errors(item, schema["contains"], f"{path}[*]") for item in value):
                errors.append(f"{path}: contains matched no items")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: too short")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            errors.append(f"{path}: pattern mismatch")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("timezone missing")
            except ValueError:
                errors.append(f"{path}: invalid date-time")
    if isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get("minimum", value):
            errors.append(f"{path}: below minimum")
    for branch in schema.get("allOf", []):
        condition = branch.get("if")
        if condition is None:
            errors.extend(_errors(value, branch, path))
        elif not _errors(value, condition, path):
            errors.extend(_errors(value, branch.get("then", {}), path))
    return errors


def _candidate(**updates: Any) -> dict[str, Any]:
    row = {
        "ts_code": "688001.SH",
        "display_name": "Fixture Semiconductor",
        "candidate_status": "MAIN_CHANNEL",
        "method_version": "RESEARCH_CLOSED_LOOP_V1",
        "cohort_id": "cohort-semiconductor-20260826",
        "causal_cluster_id": "cluster-semiconductor-demand-001",
        "u2_candidate_row_hash": "sha256:" + "1" * 64,
        "u3_battery_row_hash": "sha256:" + "2" * 64,
        "positive_channels": ["PRICE_VOLUME", "FUNDAMENTAL_VALUATION"],
        "red_flag_channels": [],
        "blocked_reasons": [],
        "missing_evidence": [],
        "quality_status": "PASS",
        "allowed_for_u4_packet": True,
        "question_for_junyan": "Does the same-day evidence support deep research?",
    }
    row.update(updates)
    return row


def _packet(**updates: Any) -> dict[str, Any]:
    packet = {
        "schema": "ar.u4_pre_decision_packet.v0",
        "packet_version": "0.1",
        "status": "READY_FOR_JUNYAN_REVIEW",
        "as_of": "20260826",
        "generated_at": "2026-08-26T09:00:00+00:00",
        "method_version": "RESEARCH_CLOSED_LOOP_V1",
        "source_refs": {
            "same_day_bundle_ref": "experiments/research_funnel/output/semiconductor-20260826",
            "same_day_bundle_hash": "sha256:" + "3" * 64,
            "u2_candidate_pool_hash": "sha256:" + "4" * 64,
            "u3_battery_hash": "sha256:" + "5" * 64,
            "feature_store_health_ref": "public/data/v2/feature_store_health.json",
            "feature_store_health_hash": "sha256:" + "7" * 64,
            "funnel_health_ref": "public/data/v2/funnel_health.json",
            "funnel_health_hash": "sha256:" + "8" * 64,
            "stage_receipts_hash": "sha256:" + "b" * 64,
            "diagnostic_report_ref": "tmp/semiconductor-diagnostic-20260826.json",
            "diagnostic_report_hash": "sha256:" + "9" * 64,
        },
        "source_publication": {
            "daily_source_status": "PUBLISHED",
            "quarterly_source_status": "PUBLISHED",
            "pending_sources": [],
            "retry_after_utc": None,
        },
        "diagnostic": {
            "tool": "u4_pre_decision.py",
            "tool_version": "0.1",
            "evidence_rows_checked": 75,
            "evidence_rows_hash_verified": True,
            "receipt_self_report_checked": True,
            "red_flag_only_rows": 0,
            "positive_channel_rows": 75,
            "u3_complete_rows": 75,
            "u4_ready_rows": 3,
            "blocker_codes": [],
        },
        "candidate_rows": [_candidate()],
        "packet_summary": {
            "candidate_count": 1,
            "allowed_for_review_count": 1,
            "blocked_count": 0,
            "red_flag_count": 0,
            "data_blocked_count": 0,
            "same_day_hash": "sha256:" + "6" * 64,
        },
        "selection_boundary": {
            "allowed_selected_counts": [0, 3, 4, 5],
            "zero_selection_meaning": "NO_TRADE_NO_QUEUE",
            "human_selection_authority": "HUMAN_JUNYAN_ONLY",
            "machine_selection_authority": "NONE",
        },
        "authority": {
            "production_authority": False,
            "trade_authority": False,
            "paper_order_authority": False,
            "claim_allowed": False,
            "no_trade_flag": True,
        },
        "packet_hash": "sha256:" + "a" * 64,
    }
    packet.update(updates)
    return packet


class U4PreDecisionPacketContractTests(unittest.TestCase):
    def assertValid(self, value: Mapping[str, Any]) -> None:
        self.assertEqual(_errors(value, SCHEMA), [])

    def assertInvalid(self, value: Mapping[str, Any], fragment: str) -> None:
        errors = _errors(value, SCHEMA)
        self.assertTrue(any(fragment in error for error in errors), errors)

    def test_valid_reviewable_packet_shape(self) -> None:
        self.assertValid(_packet())

    def test_candidate_rows_bind_research_denominator_fields(self) -> None:
        row_schema = SCHEMA["$defs"]["candidate_row"]
        required = set(row_schema["required"])
        self.assertTrue(
            {
                "method_version",
                "cohort_id",
                "causal_cluster_id",
                "blocked_reasons",
                "quality_status",
            }.issubset(required)
        )
        for field in ("method_version", "cohort_id", "causal_cluster_id"):
            packet = _packet(candidate_rows=[_candidate()])
            del packet["candidate_rows"][0][field]
            self.assertInvalid(packet, f"missing {field}")

    def test_pending_daily_source_cannot_be_reported_ready(self) -> None:
        packet = _packet()
        packet["source_publication"]["daily_source_status"] = "PENDING"
        packet["source_publication"]["pending_sources"] = ["cyq_perf"]
        packet["source_publication"]["retry_after_utc"] = "2026-08-26T09:00:00+00:00"
        self.assertInvalid(packet, "expected const 'SOURCE_PUBLICATION_PENDING'")
        packet["status"] = "SOURCE_PUBLICATION_PENDING"
        self.assertValid(packet)

        packet = _packet()
        packet["source_publication"]["pending_sources"] = ["not-really-pending"]
        self.assertInvalid(packet, "too many items")

    def test_stale_or_data_blocked_daily_source_cannot_be_reported_ready(self) -> None:
        for daily_status in ("STALE", "DATA_BLOCKED"):
            packet = _packet()
            packet["source_publication"]["daily_source_status"] = daily_status
            packet["source_publication"]["pending_sources"] = ["cyq_perf"]
            with self.subTest(daily_status=daily_status):
                self.assertInvalid(packet, "outside enum")
                packet["status"] = "DATA_BLOCKED"
                self.assertValid(packet)

    def test_quarterly_source_status_is_a_real_packet_gate(self) -> None:
        packet = _packet()
        packet["source_publication"]["quarterly_source_status"] = "PENDING"
        packet["source_publication"]["pending_sources"] = ["fina_indicator_pit"]
        self.assertInvalid(packet, "expected const 'SOURCE_PUBLICATION_PENDING'")
        packet["status"] = "SOURCE_PUBLICATION_PENDING"
        self.assertValid(packet)

        packet = _packet()
        packet["source_publication"]["quarterly_source_status"] = "DATA_BLOCKED"
        packet["source_publication"]["pending_sources"] = ["fina_indicator_pit"]
        self.assertInvalid(packet, "outside enum")
        packet["status"] = "DATA_BLOCKED"
        self.assertValid(packet)

    def test_zero_reviewable_pool_must_stop_before_u4(self) -> None:
        packet = _packet(candidate_rows=[])
        packet["packet_summary"]["candidate_count"] = 0
        packet["packet_summary"]["allowed_for_review_count"] = 0
        packet["status"] = "READY_FOR_JUNYAN_REVIEW"
        self.assertInvalid(packet, "outside enum")
        packet["status"] = "BLOCKED_BEFORE_U4"
        self.assertValid(packet)

    def test_diagnostic_must_crosscheck_evidence_rows_not_self_report_only(self) -> None:
        for field in ("evidence_rows_hash_verified", "receipt_self_report_checked"):
            packet = _packet()
            packet["diagnostic"][field] = False
            with self.subTest(field=field):
                self.assertInvalid(packet, "expected const")

    def test_red_flag_candidate_is_blocked_and_visible(self) -> None:
        packet = _packet(
            status="BLOCKED_BEFORE_U4",
            candidate_rows=[
                _candidate(
                    red_flag_channels=["E1_EVENT"],
                    blocked_reasons=["E1_RED_FLAG_ACTIVE"],
                    quality_status="REVISE_REQUIRED",
                    allowed_for_u4_packet=False,
                    question_for_junyan=None,
                )
            ],
        )
        packet["packet_summary"].update(
            {
                "allowed_for_review_count": 0,
                "blocked_count": 1,
                "red_flag_count": 1,
            }
        )
        self.assertValid(packet)
        packet["candidate_rows"][0]["blocked_reasons"] = ["BUY_SIGNAL"]
        self.assertInvalid(packet, "outside enum")

    def test_red_flag_candidate_cannot_be_marked_allowed_for_u4_packet(self) -> None:
        packet = _packet(
            candidate_rows=[
                _candidate(
                    red_flag_channels=["E1_EVENT"],
                    blocked_reasons=["E1_RED_FLAG_ACTIVE"],
                    quality_status="REVISE_REQUIRED",
                    allowed_for_u4_packet=True,
                )
            ]
        )
        self.assertInvalid(packet, "expected const")
        packet = _packet(candidate_rows=[_candidate(
            red_flag_channels=["E1_EVENT"],
            blocked_reasons=[],
            allowed_for_u4_packet=False,
            question_for_junyan=None,
        )])
        self.assertInvalid(packet, "contains matched no items")
        packet = _packet(
            candidate_rows=[
                _candidate(
                    red_flag_channels=[],
                    blocked_reasons=["E1_RED_FLAG_ACTIVE"],
                    quality_status="REVISE_REQUIRED",
                    allowed_for_u4_packet=True,
                )
            ]
        )
        self.assertInvalid(packet, "expected const")

    def test_no_positive_channel_cannot_be_marked_reviewable(self) -> None:
        packet = _packet(candidate_rows=[_candidate(positive_channels=[])])
        self.assertInvalid(packet, "contains matched no items")
        packet["candidate_rows"][0].update({
            "blocked_reasons": ["NO_POSITIVE_CHANNEL"],
            "quality_status": "DATA_BLOCKED",
            "allowed_for_u4_packet": False,
            "question_for_junyan": None,
        })
        self.assertValid(packet)

    def test_random_control_and_incomplete_u3_cannot_be_marked_reviewable(self) -> None:
        for blocker in ("RANDOM_CONTROL_NOT_SELECTABLE", "U3_BATTERY_INCOMPLETE"):
            packet = _packet(candidate_rows=[_candidate(blocked_reasons=[blocker])])
            with self.subTest(blocker=blocker):
                self.assertInvalid(packet, "expected const")
        packet = _packet(candidate_rows=[_candidate(candidate_status="RANDOM_CONTROL")])
        self.assertInvalid(packet, "contains matched no items")

    def test_unavailable_cohort_identity_is_visible_but_not_an_offline_u4_stop(self) -> None:
        packet = _packet(candidate_rows=[_candidate(
            cohort_id="UNAVAILABLE",
            causal_cluster_id="UNAVAILABLE",
            missing_evidence=["cohort_id", "causal_cluster_id"],
            quality_status="WARN",
        )])
        self.assertValid(packet)

    def test_packet_hash_and_health_bindings_are_required(self) -> None:
        packet = _packet()
        del packet["packet_hash"]
        self.assertInvalid(packet, "missing packet_hash")
        packet = _packet()
        del packet["source_refs"]["feature_store_health_hash"]
        self.assertInvalid(packet, "missing feature_store_health_hash")

    def test_selection_boundary_and_no_trade_authority_are_constants(self) -> None:
        packet = _packet()
        packet["selection_boundary"]["allowed_selected_counts"] = [0, 1, 3, 5]
        self.assertInvalid(packet, "expected const 3")
        for field in ("production_authority", "trade_authority", "paper_order_authority", "claim_allowed"):
            packet = _packet()
            packet["authority"][field] = True
            with self.subTest(field=field):
                self.assertInvalid(packet, "expected const")
        packet = _packet()
        packet["authority"]["no_trade_flag"] = False
        self.assertInvalid(packet, "expected const")

    def test_doc_freezes_non_trading_operator_boundary(self) -> None:
        text = DOC_PATH.read_text(encoding="utf-8")
        for phrase in (
            "not a recommendation list",
            "u4_pre_decision.py",
            "E1 red flags remain one-vote vetoes",
            "random-control observation",
            "prevent offline U4 research",
            "HUMAN_JUNYAN_ONLY",
            "no_trade_flag=true",
            "first 5-10 semiconductor cycles are workflow-debug samples only",
            "At least 30 independent, de-clustered",
        ):
            self.assertIn(phrase, text)

    def test_ci_runs_this_contract(self) -> None:
        ci = CI_PATH.read_text(encoding="utf-8")
        self.assertIn("python3 tests/test_u4_pre_decision_packet.py", ci)
        self.assertIn('"docs/research/**"', ci)


if __name__ == "__main__":
    unittest.main(verbosity=2)
