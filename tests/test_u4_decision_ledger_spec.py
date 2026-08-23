#!/usr/bin/env python3
"""Offline executable checks for the U4 decision-ledger JSON contract."""

from __future__ import annotations

import json
import re
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs/research/contracts/u4_decision_ledger.v1.schema.json"
DOC_PATH = ROOT / "docs/research/U4_DECISION_LEDGER_SPEC_V1.md"


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
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(_errors(item, schema["items"], f"{path}[{index}]"))
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


def _contract_errors(value: Mapping[str, Any]) -> list[str]:
    """Validate JSON shape plus cross-field chronology the schema cannot express."""
    errors = _errors(value, SCHEMA)
    try:
        registered = datetime.fromisoformat(
            str(value["registered_at"]).replace("Z", "+00:00")
        )
        decided = datetime.fromisoformat(
            str(value["human_decision"]["decided_at"]).replace("Z", "+00:00")
        )
        if registered.tzinfo is None or decided.tzinfo is None:
            raise ValueError("timezone missing")
        if registered < decided:
            errors.append("$.registered_at: durable registration predates claimed decision")
    except (KeyError, TypeError, ValueError):
        if not errors:
            errors.append("$: decision chronology is not verifiable")
    return errors


def _event(decision: str = "SELECT") -> dict[str, Any]:
    missing = ["E1_EVENT_EVIDENCE"] if decision == "DATA_BLOCKED" else []
    question = "Can evidence support a falsifiable semiconductor thesis?" if decision == "SELECT" else None
    reason = {
        "SELECT": "EVIDENCE_CHAIN_COMPLETE",
        "REJECT": "RED_FLAG_ACTIVE",
        "DEFER": "QUEUE_CAPACITY",
        "NO_TRADE": "NO_ACTIONABLE_SETUP",
        "DATA_BLOCKED": "E1_EVIDENCE_MISSING",
    }[decision]
    return {
        "schema": "ar.u4_decision_event.v1",
        "event_version": "1.0",
        "event_kind": "U4_DECISION",
        "ledger_id": "u4-ledger:20260822:aaaaaaaaaaaa",
        "sequence": 1,
        "previous_event_hash": None,
        "decision_id": "u4d_" + "b" * 32,
        "decision_revision": 1,
        "supersedes_decision_id": None,
        "method_version": "WORKFLOW_DEBUG_V0",
        "registered_at": "2026-08-22T09:31:00+08:00",
        "registration_source": "R015_EVENT_LEDGER_TS",
        "candidate": {
            "ts_code": "688001.SH",
            "display_name": "Fixture Semiconductor",
            "industry_code": "SEMICONDUCTOR",
            "cohort_id": "cohort-semiconductor-20260822",
            "causal_cluster_id": "cluster-semiconductor-demand-001",
        },
        "source": {
            "as_of": "20260822",
            "run_id": "run-20260822-fixture",
            "u2_bundle_hash": "sha256:" + "1" * 64,
            "u2_candidate_row_hash": "sha256:" + "2" * 64,
            "u3_battery_hash": "sha256:" + "3" * 64,
            "u3_battery_row_hash": "sha256:" + "4" * 64,
            "u4_packet_hash": "sha256:" + "a" * 64,
        },
        "decision": decision,
        "reason_codes": [reason],
        "reason_note": "Fixture decision retained for contract validation.",
        "missing_evidence": missing,
        "research_question": question,
        "human_decision": {
            "claimed_decision_owner": "Junyan",
            "identity_verification": "UNAVAILABLE",
            "decided_at": "2026-08-22T09:30:00+08:00",
            "authorization_text": "批准记录本次 U4 研究决策。",
            "authorization_evidence_ref": "conversation:2026-08-22-u4-fixture",
        },
        "authority": {
            "u4_selection_authority": "HUMAN_JUNYAN_ONLY",
            "production_authority": False,
            "trade_authority": False,
            "claim_allowed": False,
            "no_trade_flag": True,
        },
        "record_hash": "sha256:" + "f" * 64,
    }


class U4DecisionLedgerSpecTests(unittest.TestCase):
    def assertValid(self, value: Mapping[str, Any]) -> None:
        self.assertEqual(_contract_errors(value), [])

    def assertInvalid(self, value: Mapping[str, Any], fragment: str) -> None:
        errors = _contract_errors(value)
        self.assertTrue(any(fragment in error for error in errors), errors)

    def test_all_five_decisions_are_closed_world_and_valid(self) -> None:
        for decision in ("SELECT", "REJECT", "DEFER", "NO_TRADE", "DATA_BLOCKED"):
            with self.subTest(decision=decision):
                self.assertValid(_event(decision))
        row = _event()
        row["decision"] = "BUY"
        self.assertInvalid(row, "outside enum")

    def test_select_requires_question_and_forbids_missing_evidence(self) -> None:
        row = _event("SELECT")
        row["research_question"] = None
        self.assertInvalid(row, "wrong type")
        row = _event("SELECT")
        row["missing_evidence"] = ["MACRO_CONTEXT"]
        self.assertInvalid(row, "too many items")

    def test_data_blocked_requires_explicit_missing_evidence(self) -> None:
        row = _event("DATA_BLOCKED")
        row["missing_evidence"] = []
        self.assertInvalid(row, "too few items")

    def test_authority_constants_and_extra_trade_fields_fail_closed(self) -> None:
        for field, bad in (
            ("u4_selection_authority", "AUTOMATED_MODEL"),
            ("production_authority", True),
            ("trade_authority", True),
            ("claim_allowed", True),
            ("no_trade_flag", False),
        ):
            row = _event()
            row["authority"][field] = bad
            with self.subTest(field=field):
                self.assertInvalid(row, "expected const")
        row = _event()
        row["trade_action"] = "BUY"
        self.assertInvalid(row, "additional property trade_action")

    def test_claimed_owner_is_not_misrepresented_as_verified_identity(self) -> None:
        row = _event()
        row["human_decision"]["claimed_decision_owner"] = "Automation"
        self.assertInvalid(row, "expected const")
        row = _event()
        row["human_decision"]["identity_verification"] = "VERIFIED"
        self.assertInvalid(row, "expected const")
        row = _event()
        row["human_decision"]["decided_at"] = "20260822"
        self.assertInvalid(row, "invalid date-time")

    def test_durable_registration_time_is_not_self_reported_or_backdated(self) -> None:
        row = _event()
        row["registration_source"] = "CALLER_SUPPLIED"
        self.assertInvalid(row, "expected const")
        row = _event()
        row["registered_at"] = "2026-08-22T09:29:59+08:00"
        self.assertInvalid(row, "durable registration predates claimed decision")

    def test_method_version_is_required_and_closed_to_versioned_tokens(self) -> None:
        row = _event()
        del row["method_version"]
        self.assertInvalid(row, "missing method_version")
        row = _event()
        row["method_version"] = "unversioned draft"
        self.assertInvalid(row, "pattern mismatch")

    def test_full_and_row_battery_hashes_are_both_required_by_contract(self) -> None:
        row = _event()
        del row["source"]["u3_battery_hash"]
        self.assertInvalid(row, "missing u3_battery_hash")
        row = _event()
        del row["source"]["u3_battery_row_hash"]
        self.assertInvalid(row, "missing u3_battery_row_hash")

    def test_revisions_and_hash_chain_are_append_only_shaped(self) -> None:
        row = _event("DEFER")
        row["decision_revision"] = 2
        self.assertInvalid(row, "wrong type")
        row["supersedes_decision_id"] = "u4d_" + "c" * 32
        self.assertValid(row)
        row = _event()
        row["sequence"] = 2
        self.assertInvalid(row, "wrong type")
        row["previous_event_hash"] = "sha256:" + "d" * 64
        self.assertValid(row)

    def test_reason_and_missing_evidence_taxonomies_are_closed(self) -> None:
        row = _event("REJECT")
        row["reason_codes"] = ["MADE_UP_REASON"]
        self.assertInvalid(row, "outside enum")
        row = _event("DATA_BLOCKED")
        row["missing_evidence"] = ["UNKNOWN_FEED"]
        self.assertInvalid(row, "outside enum")

    def test_spec_explicitly_preserves_rejections_and_defers_implementation(self) -> None:
        text = DOC_PATH.read_text(encoding="utf-8")
        self.assertIn("retain `REJECT`, `DEFER`, `NO_TRADE`, and `DATA_BLOCKED`", text)
        self.assertIn("specification only", text)
        self.assertIn("does not add a writer", text)
        self.assertIn("Historical U4 choices are not reconstructed", text)
        self.assertEqual(
            SCHEMA["x-ar-packet-closure"]["selected_count_allowed"],
            [0, 3, 4, 5],
        )
        self.assertIn("prospective anchor", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
