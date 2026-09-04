#!/usr/bin/env python3
"""Offline executable checks for the U4 pre-decision packet contract."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs/research/contracts/u4_pre_decision_packet.v0.schema.json"
DOC_PATH = ROOT / "docs/research/prospective/U4_PRE_DECISION_PACKET_V0.md"
CI_PATH = ROOT / ".github/workflows/python-ci.yml"
IMMUTABLE_REF_FIELDS = {
    "same_day_bundle_ref",
    "same_day_bundle_hash",
    "u2_candidate_pool_hash",
    "u3_battery_hash",
    "feature_store_health_ref",
    "feature_store_health_hash",
    "funnel_health_ref",
    "funnel_health_hash",
    "stage_receipts_hash",
    "diagnostic_report_ref",
    "diagnostic_report_hash",
}
EXTERNAL_ROW_BLOCKERS = {
    "QUALITY_GATE_INCOMPLETE",
    "RECEIPT_SELF_REPORT_MISMATCH",
    "DIAGNOSTIC_EVIDENCE_HASH_MISMATCH",
}


def _strict_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key: {key}")
        out[key] = value
    return out


SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _derived_status(packet: Mapping[str, Any]) -> str:
    publication = packet["source_publication"]
    statuses = {
        publication["daily_source_status"],
        publication["quarterly_source_status"],
    }
    if "PENDING" in statuses:
        return "SOURCE_PUBLICATION_PENDING"
    if statuses.intersection({"STALE", "DATA_BLOCKED"}):
        return "DATA_BLOCKED"
    if not any(row["allowed_for_u4_packet"] is True for row in packet["candidate_rows"]):
        return "BLOCKED_BEFORE_U4"
    return "READY_FOR_JUNYAN_REVIEW"


def _seal(packet: dict[str, Any]) -> dict[str, Any]:
    rows = packet["candidate_rows"]
    allowed = sum(row["allowed_for_u4_packet"] is True for row in rows)
    publication = packet["source_publication"]
    blockers = sorted({code for row in rows for code in row["blocked_reasons"]})
    if publication["daily_source_status"] != "PUBLISHED":
        blockers.append("DAILY_SOURCE_NOT_PUBLISHED")
    if publication["quarterly_source_status"] != "PUBLISHED":
        blockers.append("QUARTERLY_SOURCE_NOT_PUBLISHED")
    packet["diagnostic"] = {
        "tool": "u4_pre_decision.py",
        "tool_version": "0.1",
        "evidence_rows_checked": len(rows),
        "evidence_rows_hash_verified": True,
        "receipt_self_report_checked": True,
        "red_flag_only_rows": sum(bool(row["red_flag_channels"]) for row in rows),
        "positive_channel_rows": sum(bool(row["positive_channels"]) for row in rows),
        "u3_complete_rows": sum(
            "U3_BATTERY_INCOMPLETE" not in row["blocked_reasons"] for row in rows
        ),
        "u4_ready_rows": allowed,
        "blocker_codes": sorted(set(blockers)),
    }
    packet["source_refs"]["diagnostic_report_hash"] = _digest(packet["diagnostic"])
    packet["packet_summary"] = {
        "candidate_count": len(rows),
        "allowed_for_review_count": allowed,
        "blocked_count": len(rows) - allowed,
        "red_flag_count": sum(bool(row["red_flag_channels"]) for row in rows),
        "data_blocked_count": sum(row["quality_status"] == "DATA_BLOCKED" for row in rows),
        "same_day_hash": _digest({
            "as_of": packet["as_of"],
            "source_refs": packet["source_refs"],
            "source_publication": publication,
            "candidate_rows": rows,
        }),
    }
    packet["status"] = _derived_status(packet)
    packet["packet_hash"] = _digest({
        key: value for key, value in packet.items() if key != "packet_hash"
    })
    return packet


def _frozen_evidence(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Build test-only stand-ins for evidence loaded from immutable artifacts."""
    rows: dict[str, Any] = {}
    for row in packet["candidate_rows"]:
        rows[row["ts_code"]] = {
            "display_name": row["display_name"],
            "candidate_status": row["candidate_status"],
            "method_version": row["method_version"],
            "cohort_id": row["cohort_id"],
            "cohort_identity_state": row["cohort_identity_state"],
            "causal_cluster_id": row["causal_cluster_id"],
            "causal_cluster_identity_state": row["causal_cluster_identity_state"],
            "u2_candidate_row_hash": row["u2_candidate_row_hash"],
            "u3_battery_row_hash": row["u3_battery_row_hash"],
            "peak_earnings": json.loads(json.dumps(row["peak_earnings"])),
            "positive_channels": list(row["positive_channels"]),
            "red_flag_channels": list(row["red_flag_channels"]),
            "u3_complete": "U3_BATTERY_INCOMPLETE" not in row["blocked_reasons"],
            "missing_evidence": list(row["missing_evidence"]),
            "diagnostic_blockers": sorted(
                set(row["blocked_reasons"]).intersection(EXTERNAL_ROW_BLOCKERS)
            ),
        }
    return {
        "as_of": packet["as_of"],
        "method_version": packet["method_version"],
        "source_publication": json.loads(json.dumps(packet["source_publication"])),
        "source_refs": {
            key: packet["source_refs"][key] for key in sorted(IMMUTABLE_REF_FIELDS)
        },
        "rows": rows,
    }


def _semantic_errors(packet: Mapping[str, Any], evidence: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        publication = packet["source_publication"]
        rows = packet["candidate_rows"]
        refs = packet["source_refs"]
        evidence_publication = evidence["source_publication"]
        evidence_refs = evidence["source_refs"]
        evidence_rows = evidence["rows"]
    except (KeyError, TypeError):
        return ["semantic inputs are missing"]
    if not all(
        isinstance(value, Mapping)
        for value in (publication, refs, evidence_publication, evidence_refs, evidence_rows)
    ) or not isinstance(rows, list):
        return ["semantic inputs have the wrong type"]
    if packet.get("as_of") != evidence.get("as_of"):
        errors.append("as_of does not match frozen evidence")
    if packet.get("method_version") != evidence.get("method_version"):
        errors.append("packet method_version does not match frozen evidence")
    if dict(publication) != dict(evidence_publication):
        errors.append("source publication does not match frozen evidence")
    if {key: refs.get(key) for key in IMMUTABLE_REF_FIELDS} != dict(evidence_refs):
        errors.append("immutable source refs do not match frozen evidence")
    codes = [row.get("ts_code") for row in rows if isinstance(row, Mapping)]
    if (
        len(codes) != len(evidence_rows)
        or len(codes) != len(set(codes))
        or set(codes) != set(evidence_rows)
    ):
        errors.append("candidate denominator does not match frozen evidence")
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f"candidate_rows[{index}] is not an object")
            continue
        source = evidence_rows.get(row.get("ts_code"))
        if not isinstance(source, Mapping):
            errors.append(f"candidate_rows[{index}] is absent from frozen evidence")
            continue
        positive = row.get("positive_channels")
        red_flags = row.get("red_flag_channels")
        blocked = row.get("blocked_reasons")
        missing = row.get("missing_evidence")
        if not all(isinstance(value, list) for value in (positive, red_flags, blocked, missing)):
            errors.append(f"candidate_rows[{index}] evidence lists are invalid")
            continue
        for field in (
            "display_name", "candidate_status", "method_version",
            "cohort_id", "cohort_identity_state",
            "causal_cluster_id", "causal_cluster_identity_state",
            "u2_candidate_row_hash", "u3_battery_row_hash", "positive_channels",
            "red_flag_channels", "missing_evidence", "peak_earnings",
        ):
            if row.get(field) != source.get(field):
                errors.append(f"candidate_rows[{index}] {field} differs from frozen evidence")
        if row.get("method_version") != packet.get("method_version"):
            errors.append(f"candidate_rows[{index}] method_version differs from packet")
        expected_blocked = list(source.get("diagnostic_blockers", []))
        if source.get("u3_complete") is not True:
            expected_blocked.append("U3_BATTERY_INCOMPLETE")
        if source.get("red_flag_channels"):
            expected_blocked.append("E1_RED_FLAG_ACTIVE")
        if not source.get("positive_channels"):
            expected_blocked.append("NO_POSITIVE_CHANNEL")
        if source.get("candidate_status") == "RANDOM_CONTROL":
            expected_blocked.append("RANDOM_CONTROL_NOT_SELECTABLE")
        expected_blocked.sort()
        if blocked != expected_blocked:
            errors.append(f"candidate_rows[{index}] blockers are not derived from frozen evidence")
        if bool(expected_blocked) == (row.get("allowed_for_u4_packet") is True):
            errors.append(f"candidate_rows[{index}] allowed flag is not derived")
        expected_quality = (
            "DATA_BLOCKED" if any(code != "E1_RED_FLAG_ACTIVE" for code in expected_blocked)
            else "REVISE_REQUIRED" if "E1_RED_FLAG_ACTIVE" in expected_blocked
            else "WARN" if missing
            else "PASS"
        )
        if row.get("quality_status") != expected_quality:
            errors.append(f"candidate_rows[{index}] quality is not derived")
        if row.get("cohort_id") != "UNAVAILABLE" or row.get("cohort_identity_state") != "UNAVAILABLE_UNBOUND":
            errors.append(f"candidate_rows[{index}] invents an unbound cohort identity")
        cluster_state = row.get("causal_cluster_identity_state")
        if cluster_state == "UNAVAILABLE_PENDING":
            if row.get("causal_cluster_id") != "UNAVAILABLE" or "causal_cluster_id" not in missing:
                errors.append(f"candidate_rows[{index}] hides unavailable causal cluster")
        elif cluster_state != "VERIFIED_UPSTREAM" or row.get("causal_cluster_id") == "UNAVAILABLE":
            errors.append(f"candidate_rows[{index}] causal cluster identity is invalid")
    try:
        expected = _seal(json.loads(json.dumps(packet)))
    except (KeyError, TypeError, ValueError):
        return errors + ["semantic receipt cannot be recomputed"]
    for field in ("status", "diagnostic", "packet_summary", "packet_hash"):
        if packet.get(field) != expected.get(field):
            errors.append(f"{field} is not derived")
    if refs.get("diagnostic_report_hash") != expected["source_refs"]["diagnostic_report_hash"]:
        errors.append("diagnostic_report_hash is not derived")
    all_published = all(
        publication.get(field) == "PUBLISHED"
        for field in ("daily_source_status", "quarterly_source_status")
    )
    if all_published != (publication.get("pending_sources") == []):
        errors.append("pending_sources disagrees with source status")
    return errors


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
    if expected == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
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
        "cohort_id": "UNAVAILABLE",
        "cohort_identity_state": "UNAVAILABLE_UNBOUND",
        "causal_cluster_id": "UNAVAILABLE",
        "causal_cluster_identity_state": "UNAVAILABLE_PENDING",
        "u2_candidate_row_hash": "sha256:" + "1" * 64,
        "u3_battery_row_hash": "sha256:" + "2" * 64,
        "peak_earnings": {
            "flag": None,
            "needs_normalized_bridge": None,
            "roe_vs_5y_median": None,
            "gm_vs_5y_median": None,
            "source_hash": None,
            "reason": "CYCLICAL_FLAG_NOT_COMPUTED",
        },
        "positive_channels": ["PRICE_VOLUME", "FUNDAMENTAL_VALUATION"],
        "red_flag_channels": [],
        "blocked_reasons": [],
        "missing_evidence": ["causal_cluster_id", "cohort_id"],
        "quality_status": "WARN",
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
        "diagnostic": {},
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
    return _seal(packet)


class U4PreDecisionPacketContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_evidence = _frozen_evidence(_packet())

    def assertValid(
        self, value: Mapping[str, Any], evidence: Mapping[str, Any] | None = None,
    ) -> None:
        self.assertEqual(
            _errors(value, SCHEMA) + _semantic_errors(value, evidence or self.base_evidence),
            [],
        )

    def assertInvalid(
        self, value: Mapping[str, Any], fragment: str,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        errors = _errors(value, SCHEMA) + _semantic_errors(value, evidence or self.base_evidence)
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
                "cohort_identity_state",
                "causal_cluster_id",
                "causal_cluster_identity_state",
                "peak_earnings",
                "blocked_reasons",
                "quality_status",
            }.issubset(required)
        )
        for field in (
            "method_version", "cohort_id", "cohort_identity_state",
            "causal_cluster_id", "causal_cluster_identity_state",
            "peak_earnings",
        ):
            packet = _packet(candidate_rows=[_candidate()])
            del packet["candidate_rows"][0][field]
            self.assertInvalid(packet, f"missing {field}")

    def test_peak_earnings_has_exact_available_or_explicitly_uncomputed_shape(self) -> None:
        available = {
            "flag": True,
            "needs_normalized_bridge": True,
            "roe_vs_5y_median": 1.4,
            "gm_vs_5y_median": 1.2,
            "source_hash": "sha256:" + "c" * 64,
            "reason": None,
        }
        packet = _packet(candidate_rows=[_candidate(peak_earnings=available)])
        self.assertValid(packet, _frozen_evidence(packet))

        invented = _packet()
        invented["candidate_rows"][0]["peak_earnings"]["flag"] = False
        self.assertInvalid(invented, "oneOf matched")

        malformed = _packet(candidate_rows=[_candidate(peak_earnings=available)])
        malformed["candidate_rows"][0]["peak_earnings"]["score_total"] = 1
        self.assertInvalid(malformed, "oneOf matched")

    def test_pending_daily_source_cannot_be_reported_ready(self) -> None:
        packet = _packet()
        packet["source_publication"]["daily_source_status"] = "PENDING"
        packet["source_publication"]["pending_sources"] = ["cyq_perf"]
        packet["source_publication"]["retry_after_utc"] = "2026-08-26T09:00:00+00:00"
        self.assertInvalid(packet, "expected const 'SOURCE_PUBLICATION_PENDING'")
        packet["status"] = "SOURCE_PUBLICATION_PENDING"
        packet = _seal(packet)
        self.assertValid(packet, _frozen_evidence(packet))

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
                packet = _seal(packet)
                self.assertValid(packet, _frozen_evidence(packet))

    def test_quarterly_source_status_is_a_real_packet_gate(self) -> None:
        packet = _packet()
        packet["source_publication"]["quarterly_source_status"] = "PENDING"
        packet["source_publication"]["pending_sources"] = ["fina_indicator_pit"]
        self.assertInvalid(packet, "expected const 'SOURCE_PUBLICATION_PENDING'")
        packet["status"] = "SOURCE_PUBLICATION_PENDING"
        packet = _seal(packet)
        self.assertValid(packet, _frozen_evidence(packet))

        packet = _packet()
        packet["source_publication"]["quarterly_source_status"] = "DATA_BLOCKED"
        packet["source_publication"]["pending_sources"] = ["fina_indicator_pit"]
        self.assertInvalid(packet, "outside enum")
        packet["status"] = "DATA_BLOCKED"
        packet = _seal(packet)
        self.assertValid(packet, _frozen_evidence(packet))

    def test_zero_reviewable_pool_must_stop_before_u4(self) -> None:
        packet = _packet(candidate_rows=[])
        packet["packet_summary"]["candidate_count"] = 0
        packet["packet_summary"]["allowed_for_review_count"] = 0
        packet["status"] = "READY_FOR_JUNYAN_REVIEW"
        self.assertInvalid(packet, "outside enum")
        packet["status"] = "BLOCKED_BEFORE_U4"
        packet = _seal(packet)
        self.assertValid(packet, _frozen_evidence(packet))

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
        self.assertValid(packet, _frozen_evidence(packet))
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
        packet = _seal(packet)
        self.assertValid(packet, _frozen_evidence(packet))

    def test_quality_and_summary_are_recomputed_not_self_reported(self) -> None:
        packet = _packet()
        packet["candidate_rows"][0]["quality_status"] = "DATA_BLOCKED"
        self.assertInvalid(packet, "quality is not derived")
        packet = _packet()
        packet["packet_summary"].update({
            "candidate_count": 999,
            "allowed_for_review_count": 999,
            "blocked_count": 0,
        })
        self.assertInvalid(packet, "packet_summary is not derived")
        packet = _packet()
        packet["diagnostic"]["u4_ready_rows"] = 999
        self.assertInvalid(packet, "diagnostic is not derived")

    def test_candidate_denominator_and_frozen_row_bindings_are_external(self) -> None:
        second = _candidate(
            ts_code="688002.SH",
            display_name="Second Semiconductor",
            u2_candidate_row_hash="sha256:" + "c" * 64,
            u3_battery_row_hash="sha256:" + "d" * 64,
        )
        source_packet = _packet(candidate_rows=[_candidate(), second])
        frozen = _frozen_evidence(source_packet)
        omitted = _packet(candidate_rows=[_candidate()])
        self.assertInvalid(
            omitted, "candidate denominator does not match frozen evidence", frozen
        )
        duplicate = _packet(candidate_rows=[_candidate(), _candidate()])
        self.assertInvalid(
            duplicate, "candidate denominator does not match frozen evidence", frozen
        )
        invented_hash = json.loads(json.dumps(source_packet))
        invented_hash["candidate_rows"][0]["u3_battery_row_hash"] = "sha256:" + "e" * 64
        invented_hash = _seal(invented_hash)
        self.assertInvalid(
            invented_hash, "u3_battery_row_hash differs from frozen evidence", frozen
        )

        reversed_packet = _packet(candidate_rows=[second, _candidate()])
        self.assertValid(reversed_packet, frozen)

    def test_date_publication_and_method_are_bound_to_frozen_evidence(self) -> None:
        pending = _packet()
        pending["source_publication"] = {
            "daily_source_status": "PENDING",
            "quarterly_source_status": "PUBLISHED",
            "pending_sources": ["cyq_perf"],
            "retry_after_utc": "2026-08-26T10:00:00+00:00",
        }
        pending = _seal(pending)
        frozen = _frozen_evidence(pending)

        relabeled = json.loads(json.dumps(pending))
        relabeled["source_publication"] = {
            "daily_source_status": "PUBLISHED",
            "quarterly_source_status": "PUBLISHED",
            "pending_sources": [],
            "retry_after_utc": None,
        }
        relabeled = _seal(relabeled)
        self.assertEqual(relabeled["status"], "READY_FOR_JUNYAN_REVIEW")
        self.assertInvalid(
            relabeled, "source publication does not match frozen evidence", frozen
        )

        for field, value, fragment in (
            ("as_of", "20260827", "as_of does not match frozen evidence"),
            (
                "method_version",
                "INVENTED_RESEARCH_METHOD_V9",
                "packet method_version does not match frozen evidence",
            ),
        ):
            packet = json.loads(json.dumps(pending))
            packet[field] = value
            if field == "method_version":
                packet["candidate_rows"][0]["method_version"] = value
            packet = _seal(packet)
            with self.subTest(field=field):
                self.assertInvalid(packet, fragment, frozen)

    def test_external_diagnostic_blockers_are_visible_and_derived(self) -> None:
        for blocker in sorted(EXTERNAL_ROW_BLOCKERS):
            row = _candidate(
                blocked_reasons=[blocker],
                quality_status="DATA_BLOCKED",
                allowed_for_u4_packet=False,
                question_for_junyan=None,
            )
            source_packet = _packet(candidate_rows=[row])
            frozen = _frozen_evidence(source_packet)
            with self.subTest(blocker=blocker):
                self.assertValid(source_packet, frozen)
                concealed = json.loads(json.dumps(source_packet))
                concealed["candidate_rows"][0]["blocked_reasons"] = []
                concealed["candidate_rows"][0]["quality_status"] = "WARN"
                concealed["candidate_rows"][0]["allowed_for_u4_packet"] = True
                concealed["candidate_rows"][0]["question_for_junyan"] = (
                    "Does the same-day evidence support deep research?"
                )
                concealed = _seal(concealed)
                self.assertInvalid(
                    concealed, "blockers are not derived from frozen evidence", frozen
                )

    def test_random_control_and_incomplete_u3_cannot_be_marked_reviewable(self) -> None:
        for blocker in ("RANDOM_CONTROL_NOT_SELECTABLE", "U3_BATTERY_INCOMPLETE"):
            packet = _packet(candidate_rows=[_candidate(blocked_reasons=[blocker])])
            with self.subTest(blocker=blocker):
                self.assertInvalid(packet, "expected const")
        packet = _packet(candidate_rows=[_candidate(candidate_status="RANDOM_CONTROL")])
        self.assertInvalid(packet, "contains matched no items")

    def test_unavailable_cohort_identity_is_visible_but_not_an_offline_u4_stop(self) -> None:
        packet = _packet()
        self.assertValid(packet)
        packet = _packet(candidate_rows=[_candidate(
            cohort_id="invented-cohort",
            cohort_identity_state="UNAVAILABLE_UNBOUND",
        )])
        self.assertInvalid(packet, "expected const 'UNAVAILABLE'")
        packet = _packet(candidate_rows=[_candidate(
            causal_cluster_id="invented-cluster",
            causal_cluster_identity_state="UNAVAILABLE_PENDING",
        )])
        self.assertInvalid(packet, "expected const 'UNAVAILABLE'")
        verified = _packet(candidate_rows=[_candidate(
            causal_cluster_id="cluster-semiconductor-demand-001",
            causal_cluster_identity_state="VERIFIED_UPSTREAM",
            missing_evidence=["cohort_id"],
            quality_status="WARN",
        )])
        self.assertValid(verified, _frozen_evidence(verified))

    def test_u3_incomplete_plus_e1_remains_data_blocked_with_both_reasons(self) -> None:
        row = _candidate(
            red_flag_channels=["E1_EVENT"],
            blocked_reasons=["E1_RED_FLAG_ACTIVE", "U3_BATTERY_INCOMPLETE"],
            quality_status="DATA_BLOCKED",
            allowed_for_u4_packet=False,
            question_for_junyan=None,
        )
        packet = _packet(candidate_rows=[row])
        self.assertValid(packet, _frozen_evidence(packet))
        packet["candidate_rows"][0]["quality_status"] = "REVISE_REQUIRED"
        packet = _seal(packet)
        self.assertInvalid(
            packet, "quality is not derived", _frozen_evidence(_packet(candidate_rows=[row]))
        )

    def test_packet_hash_and_health_bindings_are_required(self) -> None:
        packet = _packet()
        del packet["packet_hash"]
        self.assertInvalid(packet, "missing packet_hash")
        packet = _packet()
        del packet["source_refs"]["feature_store_health_hash"]
        self.assertInvalid(packet, "missing feature_store_health_hash")

    def test_valid_format_digest_tampering_is_rejected(self) -> None:
        packet = _packet()
        packet["packet_summary"]["same_day_hash"] = "sha256:" + "0" * 64
        packet["packet_hash"] = _digest({
            key: value for key, value in packet.items() if key != "packet_hash"
        })
        self.assertInvalid(packet, "packet_summary is not derived")

        packet = _packet()
        packet["source_refs"]["diagnostic_report_hash"] = "sha256:" + "0" * 64
        packet["packet_summary"]["same_day_hash"] = _digest({
            "as_of": packet["as_of"],
            "source_refs": packet["source_refs"],
            "source_publication": packet["source_publication"],
            "candidate_rows": packet["candidate_rows"],
        })
        packet["packet_hash"] = _digest({
            key: value for key, value in packet.items() if key != "packet_hash"
        })
        self.assertInvalid(packet, "diagnostic_report_hash is not derived")

        packet = _packet()
        packet["packet_hash"] = "sha256:" + "0" * 64
        self.assertInvalid(packet, "packet_hash is not derived")

    def test_selection_boundary_and_no_trade_authority_are_constants(self) -> None:
        packet = _packet()
        packet["selection_boundary"]["allowed_selected_counts"] = [0, 1, 3, 5]
        self.assertInvalid(packet, "expected const 3")
        for field, value in (
            ("human_selection_authority", "MODEL"),
            ("machine_selection_authority", "AUTO"),
        ):
            packet = _packet()
            packet["selection_boundary"][field] = value
            with self.subTest(field=field):
                self.assertInvalid(packet, "expected const")
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
        self.assertRegex(
            ci,
            r"(?m)^\s*run:\s*python3 tests/test_u4_pre_decision_packet\.py\s*$",
        )
        self.assertIn('"docs/research/**"', ci)


if __name__ == "__main__":
    unittest.main(verbosity=2)
