#!/usr/bin/env python3
"""U4 decision ledger v1.1: structured human_warning and machine_flag_disputed_ref."""

from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))

from experiments.execution_tracker import event_ledger  # noqa: E402
from experiments.research_funnel import disagreement_ledger as dl  # noqa: E402
from experiments.research_funnel import u4_decision_ledger as ledger  # noqa: E402
import test_disagreement_ledger as adj  # noqa: E402
import test_u4_decision_ledger as base  # noqa: E402
import test_u4_decision_ledger_spec as frozen_spec  # noqa: E402


V11_SCHEMA_PATH = ROOT / "docs/research/contracts/u4_decision_ledger.v1_1.schema.json"
V11_SCHEMA = json.loads(V11_SCHEMA_PATH.read_text(encoding="utf-8"))
ADJ_QUEUE_AT = "2026-08-21T20:00:00+08:00"
ADJ_DECIDED_AT = "2026-08-21T21:00:00+08:00"
ADJ_REGISTERED_AT = "2026-08-21T21:05:00"
WARNING = {
    "retained": True,
    "warning_text": "人工警示保留：AI 研究意见为 WATCH/REVISE_REQUIRED，不解除警示，不批准 paper。",
    "target_surface": "PAPER",
}


def _schema_errors(value: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    """Minimal validator for the keywords the v1.1 contract uses."""
    if "$ref" in schema:
        node: Any = V11_SCHEMA
        for part in schema["$ref"][2:].split("/"):
            node = node[part]
        return _schema_errors(value, node, path)
    errors: list[str] = []
    if "oneOf" in schema:
        matches = sum(not _schema_errors(value, item, path) for item in schema["oneOf"])
        return [] if matches == 1 else [f"{path}: oneOf matched {matches}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: const")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: enum")
    kind = schema.get("type")
    checks = {
        "object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "null": lambda v: v is None,
    }
    if kind is not None and not checks[kind](value):
        return errors + [f"{path}: type"]
    if "minimum" in schema and checks["integer"](value) and value < schema["minimum"]:
        errors.append(f"{path}: minimum")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            errors.extend(f"{path}: additional {key}" for key in value if key not in props)
        for key, child in props.items():
            if key in value:
                errors.extend(_schema_errors(value[key], child, f"{path}.{key}"))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: minItems")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: maxItems")
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(_schema_errors(item, schema["items"], f"{path}[{index}]"))
        if "contains" in schema and not any(not _schema_errors(item, schema["contains"]) for item in value):
            errors.append(f"{path}: contains")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: minLength")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{path}: pattern")
    for rule in schema.get("allOf", []):
        if not _schema_errors(value, rule["if"], path):
            errors.extend(_schema_errors(value, rule["then"], path))
    return errors


def v11_draft(packet: dict, *, warnings: dict | None = None, refs: dict | None = None,
              decisions: dict | None = None, **kwargs) -> dict:
    draft = base.draft_for(packet, decisions, **kwargs)
    for row in draft["decisions"]:
        row["human_warning"] = copy.deepcopy((warnings or {}).get(row["ts_code"]))
        row["machine_flag_disputed_ref"] = (refs or {}).get(row["ts_code"])
    return draft


def red_flag_packet() -> dict:
    return base.packet_with_synthetic_red_flag(base.packet_fixture(), base.REJECT_CODE)


def red_flag_draft(packet: dict, ref: str | None) -> dict:
    draft = v11_draft(packet, refs={base.REJECT_CODE: ref})
    row = next(item for item in draft["decisions"] if item["ts_code"] == base.REJECT_CODE)
    row["reason_codes"] = ["RED_FLAG_ACTIVE"]
    return draft


def build_adjudications(root: Path, *, decided_at: str = ADJ_DECIDED_AT,
                        now: str = ADJ_REGISTERED_AT) -> tuple[Path, dict[str, str]]:
    """Commit two adjudications on the red-flag ticker: one disputes, one confirms."""
    code = base.REJECT_CODE
    rows = [
        adj.queue_row(code, as_of=base.funnel_fixtures.TRADE_DATE, rank=1),
        adj.queue_row(code, "E1_RED_FLAG_CONTROL_SAMPLE", as_of=base.funnel_fixtures.TRADE_DATE, rank=2),
        adj.queue_row(base.DEFER_CODE, as_of=base.funnel_fixtures.TRADE_DATE, rank=3),
    ]
    queue = adj.make_queue(rows, as_of=base.funnel_fixtures.TRADE_DATE, run_id=base.SOURCE_RUN_ID,
                           generated_at=ADJ_QUEUE_AT)
    bundle = adj.write_bundle(root, queue, name="adjudication_bundle")
    draft = dl.build_draft(dl.load_bundle_queue(bundle))
    control_id = rows[1]["row_id"]
    batch = adj.fill(draft, decided_at=decided_at)
    for row in batch["rows"]:
        if row["row_id"] == control_id:
            row["human_verdict"] = "MACHINE_VERDICT_CONFIRMED"
    path = root / "adjudications.jsonl"
    adj.record(bundle, batch, path, now=now)
    committed = dl.committed_adjudications(path)
    refs = {}
    for record_hash, event in committed.items():
        if event["ts_code"] == base.DEFER_CODE:
            refs["other_ticker"] = record_hash
        elif event["human_verdict"] == "MACHINE_VERDICT_CONFIRMED":
            refs["confirmed"] = record_hash
        else:
            refs["disputes"] = record_hash
    return path, refs


def append_unsourced(**kwargs) -> dict:
    """Write a synthetic red-flag packet; the immutable-source check is exercised elsewhere."""
    with patch.object(ledger, "_validate_packet_source", lambda _packet, _bundle: None):
        return base.append_batch(**kwargs)


class U4LedgerV11Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "u4_events.jsonl"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def events(self) -> list[dict]:
        return [
            json.loads(line)["payload"] for line in self.path.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["kind"] == ledger.EVENT_KIND
        ]

    def test_v10_drafts_still_write_exact_v10_events(self) -> None:
        base.append_fixture(self.path)
        events = self.events()
        self.assertTrue(all(event["event_version"] == "1.0" for event in events))
        self.assertTrue(all(set(event) == ledger.EVENT_FIELDS for event in events))
        self.assertTrue(all(frozen_spec._contract_errors(event) == [] for event in events))
        intent = json.loads(self.path.read_text(encoding="utf-8").splitlines()[0])["payload"]
        self.assertEqual(intent["intent_version"], "1.0")
        self.assertEqual(ledger.verify_decision_ledger(self.path)["disputed_refs"],
                         {"count": 0, "resolution": "NONE"})

    def test_v11_human_warning_is_persisted_replayed_and_schema_valid(self) -> None:
        packet = base.packet_fixture()
        code = base.SELECT_CODES[0]
        base.append_fixture(self.path, packet=packet, draft=v11_draft(packet, warnings={code: WARNING}))
        events = self.events()
        self.assertTrue(all(event["event_version"] == "1.1" for event in events))
        warned = next(event for event in events if event["candidate"]["ts_code"] == code)
        self.assertEqual(warned["human_warning"], WARNING)
        self.assertEqual(warned["decision"], "SELECT")
        for event in events:
            self.assertEqual(_schema_errors(event, V11_SCHEMA), [], event["candidate"]["ts_code"])
            self.assertNotEqual(frozen_spec._contract_errors(event), [])
        verified = ledger.verify_decision_ledger(self.path)
        self.assertTrue(verified["ok"], verified)
        intent = json.loads(self.path.read_text(encoding="utf-8").splitlines()[0])["payload"]
        self.assertEqual(intent["intent_version"], "1.1")
        current = ledger.current_packet_decisions(self.path, packet["packet_hash"])
        self.assertEqual(next(e for e in current if e["candidate"]["ts_code"] == code)["human_warning"], WARNING)

    def test_v10_revision_can_be_superseded_by_a_v11_revision(self) -> None:
        packet = base.packet_fixture()
        base.append_fixture(self.path, packet=packet)
        original = ledger.current_packet_decisions(self.path, packet["packet_hash"])
        supersedes = {event["candidate"]["ts_code"]: event["decision_id"] for event in original}
        revised = v11_draft(packet, warnings={base.SELECT_CODES[1]: WARNING}, revision=2,
                            supersedes=supersedes, decided_at="2026-08-22T00:20:00+08:00")
        base.append_batch(packet=packet, draft=revised, ledger_path=self.path, now="2026-08-22T00:21:00")
        verified = ledger.verify_decision_ledger(self.path)
        self.assertTrue(verified["ok"], verified)
        self.assertEqual(verified["closures"], 2)
        versions = [event["event_version"] for event in self.events()]
        self.assertEqual(versions, ["1.0"] * base.TOTAL_ROWS + ["1.1"] * base.TOTAL_ROWS)

    def test_one_revision_cannot_mix_event_versions(self) -> None:
        packet = base.packet_fixture()
        draft = base.draft_for(packet)
        draft["decisions"][0]["human_warning"] = copy.deepcopy(WARNING)
        draft["decisions"][0]["machine_flag_disputed_ref"] = None
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "one coherent event version"):
            ledger._validate_draft(packet, draft)

    def test_human_warning_shape_is_closed(self) -> None:
        packet = base.packet_fixture()
        code = base.SELECT_CODES[0]
        for bad in (
            {**WARNING, "target_surface": "TRADE"},
            {**WARNING, "warning_text": "  "},
            {**WARNING, "retained": "yes"},
        ):
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "outside the v1.1 contract"):
                ledger._validate_draft(packet, v11_draft(packet, warnings={code: bad}))
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "fields are not exact"):
            ledger._validate_draft(packet, v11_draft(packet, warnings={code: {**WARNING, "buy": True}}))

    def test_disputed_ref_is_only_allowed_on_forced_red_flag_reject(self) -> None:
        packet = base.packet_fixture()
        ref = "sha256:" + "a" * 64
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "only allowed on a forced REJECT"):
            ledger._validate_draft(packet, v11_draft(packet, refs={base.SELECT_CODES[0]: ref}))
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "only allowed on a forced REJECT"):
            ledger._validate_draft(packet, v11_draft(packet, refs={base.REJECT_CODE: ref}))
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "sha256 record hash"):
            ledger._validate_draft(red_flag_packet(), red_flag_draft(red_flag_packet(), "not-a-hash"))

    def test_disputed_ref_never_relaxes_the_forced_red_flag_reject(self) -> None:
        packet = red_flag_packet()
        draft = red_flag_draft(packet, "sha256:" + "a" * 64)
        row = next(item for item in draft["decisions"] if item["ts_code"] == base.REJECT_CODE)
        row["decision"] = "DEFER"
        row["reason_codes"] = ["QUEUE_CAPACITY"]
        with self.assertRaises(ledger.DecisionLedgerError):
            ledger._validate_draft(packet, draft)

    def test_disputed_ref_requires_the_adjudication_ledger(self) -> None:
        adjudications, refs = build_adjudications(self.root)
        packet = red_flag_packet()
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "requires the adjudication ledger"):
            append_unsourced(packet=packet, draft=red_flag_draft(packet, refs["disputes"]),
                             ledger_path=self.path)
        self.assertFalse(self.path.exists())

    def test_disputed_ref_must_resolve_to_a_disputing_adjudication_of_the_same_ticker(self) -> None:
        adjudications, refs = build_adjudications(self.root)
        packet = red_flag_packet()
        for label in ("confirmed", "other_ticker"):
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "does not resolve"):
                append_unsourced(packet=packet, draft=red_flag_draft(packet, refs[label]),
                                 ledger_path=self.path, adjudication_ledger_path=adjudications)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "does not resolve"):
            append_unsourced(packet=packet, draft=red_flag_draft(packet, "sha256:" + "0" * 64),
                             ledger_path=self.path, adjudication_ledger_path=adjudications)
        self.assertFalse(self.path.exists())

    def test_resolved_disputed_ref_is_written_and_verified(self) -> None:
        adjudications, refs = build_adjudications(self.root)
        packet = red_flag_packet()
        append_unsourced(packet=packet, draft=red_flag_draft(packet, refs["disputes"]),
                         ledger_path=self.path, adjudication_ledger_path=adjudications)
        event = next(e for e in self.events() if e["candidate"]["ts_code"] == base.REJECT_CODE)
        self.assertEqual(event["decision"], "REJECT")
        self.assertIn("RED_FLAG_ACTIVE", event["reason_codes"])
        self.assertEqual(event["machine_flag_disputed_ref"], refs["disputes"])
        self.assertEqual(_schema_errors(event, V11_SCHEMA), [])
        resolved = ledger.verify_decision_ledger(self.path, adjudication_ledger_path=adjudications)
        self.assertTrue(resolved["ok"], resolved)
        self.assertEqual(resolved["disputed_refs"], {"count": 1, "resolution": "RESOLVED"})
        unchecked = ledger.verify_decision_ledger(self.path)
        self.assertEqual(unchecked["disputed_refs"], {"count": 1, "resolution": "NOT_CHECKED"})
        empty_root = self.root / "other"
        other, _ = build_adjudications(
            empty_root, decided_at="2026-08-21T21:30:00+08:00", now="2026-08-21T21:35:00",
        )
        mismatch = ledger.verify_decision_ledger(self.path, adjudication_ledger_path=other)
        self.assertFalse(mismatch["ok"])
        self.assertIn("does not resolve", mismatch["errors"][0])

    def test_disputed_ref_cannot_name_a_later_or_future_adjudication(self) -> None:
        adjudications, refs = build_adjudications(self.root)
        committed = dl.committed_adjudications(adjudications)
        record = committed[refs["disputes"]]
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "does not resolve"):
            ledger.resolve_disputed_ref(ref=refs["disputes"], ts_code=record["ts_code"],
                                        as_of="20260810", registered_at=None, adjudications=committed)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "later adjudication"):
            ledger.resolve_disputed_ref(ref=refs["disputes"], ts_code=record["ts_code"],
                                        as_of=record["as_of"], registered_at="2026-08-21T21:04:59+08:00",
                                        adjudications=committed)
        ledger.resolve_disputed_ref(ref=refs["disputes"], ts_code=record["ts_code"], as_of=record["as_of"],
                                    registered_at="2026-08-22T00:16:00+08:00", adjudications=committed)

    def test_intent_version_must_match_candidate_intents(self) -> None:
        packet = base.packet_fixture()
        draft = v11_draft(packet)
        rows, decisions = ledger._validate_draft(packet, draft)
        intent = ledger._build_packet_intent(packet, draft, decisions, rows)
        self.assertEqual(intent["intent_version"], "1.1")
        intent["intent_version"] = "1.0"
        intent["intent_hash"] = ledger._intent_hash(intent)
        intent["intent_id"] = ledger._packet_intent_id(intent)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "version does not match"):
            ledger.validate_packet_intent(intent)

    def test_v10_event_cannot_smuggle_v11_fields(self) -> None:
        packet = base.packet_fixture()
        draft = base.draft_for(packet)
        rows, decisions = ledger._validate_draft(packet, draft)
        intent = ledger._build_packet_intent(packet, draft, decisions, rows)
        event = ledger._build_event(intent["candidate_intents"][0], sequence=1, previous_hash=None,
                                    registered_at="2026-08-22T00:16:00+08:00")
        ledger.validate_decision_event(event)
        event["human_warning"] = copy.deepcopy(WARNING)
        event["machine_flag_disputed_ref"] = None
        event["decision_id"] = ledger._decision_id(event)
        event["record_hash"] = ledger._record_hash(event)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "fields are not exact"):
            ledger.validate_decision_event(event)

    def test_v11_schema_is_additive_and_keeps_v1_frozen(self) -> None:
        v1 = json.loads((ROOT / "docs/research/contracts/u4_decision_ledger.v1.schema.json").read_text())
        self.assertEqual(set(V11_SCHEMA["required"]) - set(v1["required"]), ledger.V11_FIELDS)
        self.assertEqual(V11_SCHEMA["properties"]["event_version"], {"const": "1.1"})
        surfaces = V11_SCHEMA["properties"]["human_warning"]["oneOf"][1]["properties"]["target_surface"]["enum"]
        self.assertEqual(set(surfaces), ledger.WARNING_TARGET_SURFACES)
        event = frozen_spec._event("SELECT")
        event["event_version"] = "1.1"
        event["human_warning"] = None
        event["machine_flag_disputed_ref"] = "sha256:" + "a" * 64
        self.assertTrue(any("const" in error for error in _schema_errors(event, V11_SCHEMA)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
