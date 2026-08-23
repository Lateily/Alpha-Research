#!/usr/bin/env python3
"""Behavior, WAL, concurrency, and #295 contract tests for the U4 ledger."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import shutil
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from threading import Event, Lock
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))

from experiments.execution_tracker import event_ledger  # noqa: E402
from experiments.research_funnel import closure_experiment as closure  # noqa: E402
from experiments.research_funnel import funnel_pipeline as funnel  # noqa: E402
from experiments.research_funnel import u4_decision_ledger as ledger  # noqa: E402
import test_research_funnel_closure as funnel_fixtures  # noqa: E402
import test_u4_decision_ledger_spec as frozen_spec  # noqa: E402


GENERATED_AT = "2026-08-22T00:10:00+08:00"
DECIDED_AT = "2026-08-22T00:15:00+08:00"
REGISTERED_AT = "2026-08-22T00:16:00"
SOURCE_RUN_ID = "FIXTURE_RUN_20260811"


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _build_source_evidence(root: Path) -> tuple[Path, dict, dict, dict[str, tuple[str, ...] | str]]:
    registry, _, scan, candidates = funnel_fixtures.build_candidates(n=9)
    candidate_rows = candidates["rows"]
    clean_codes = sorted(
        row["ts_code"] for row in candidate_rows if "RED_FLAG" not in row["flags"]
    )
    red_codes = sorted(
        row["ts_code"] for row in candidate_rows if "RED_FLAG" in row["flags"]
    )
    if len(clean_codes) != 7 or len(red_codes) != 2:
        raise AssertionError("U4 source fixture no longer has 7 clean and 2 red-flag rows")
    candidate_manifest = funnel.build_candidate_manifest(
        candidate_review=candidates,
        scan=scan,
        run_id=SOURCE_RUN_ID,
    )
    blocked_code = clean_codes[-1]
    dual_blocked_code = red_codes[0]
    results = []
    for code in sorted(clean_codes + red_codes):
        dims = {
            name: {"fixture": True} for name in funnel.BATTERY_DIMENSIONS
        }
        if code in {blocked_code, dual_blocked_code}:
            dims["基本面"] = {"status": "DATA_BLOCKED", "err": "fixture evidence unavailable"}
        missing = [name for name, evidence in dims.items() if evidence.get("status") == "DATA_BLOCKED"]
        results.append({
            "ts_code": code,
            "checked_at": funnel_fixtures.TRADE_DATE,
            "dims": dims,
            "completeness": {
                "covered": 6 - len(missing),
                "of": 6,
                "missing": missing,
                "verdict": "PARTIAL" if missing else "COMPLETE",
            },
        })
    battery = {
        "schema": funnel.BATTERY_U2_SCHEMA,
        "schema_version": funnel.SCHEMA_VERSION,
        "rule_version": funnel.RULE_VERSION,
        "as_of": funnel_fixtures.TRADE_DATE,
        "target_trade_date": funnel_fixtures.TRADE_DATE,
        "checked_at": funnel_fixtures.TRADE_DATE,
        "run_id": SOURCE_RUN_ID,
        "generated_at": funnel_fixtures.GENERATED_AT,
        "manifest_hash": candidate_manifest["manifest_hash"],
        "provider_state": "FIXTURE",
        "results": results,
        "disclaimer": funnel.DISCLAIMER,
    }
    battery["rows_hash"] = funnel._hash(results)
    funnel.validate_candidate_battery(battery, candidate_manifest)
    queue = funnel.build_deep_research_queue(
        candidate_review=candidates,
        battery=battery,
        selected_tickers=(),
        trade_date=funnel_fixtures.TRADE_DATE,
        generated_at=funnel_fixtures.GENERATED_AT,
    )
    projected = funnel.advance_registry(
        registry=registry,
        scan=scan,
        candidate_review=candidates,
        battery=battery,
        deep_queue=queue,
        generated_at=funnel_fixtures.GENERATED_AT,
    )
    bundle = root / "bundle"
    bundle.mkdir()
    payloads = {
        "all_market_scan.json": scan,
        "candidate_review.json": candidates,
        "candidate_manifest.json": candidate_manifest,
        "candidate_battery.json": battery,
        "deep_research_queue.json": queue,
        "security_registry_projected.json": projected,
    }
    for name, value in payloads.items():
        _write_json(bundle / name, value)
    artifacts = {
        name: hashlib.sha256((bundle / name).read_bytes()).hexdigest()
        for name in sorted(payloads)
    }
    manifest = {
        "schema": "ar.research_funnel_bundle",
        "schema_version": funnel.SCHEMA_VERSION,
        "rule_version": funnel.RULE_VERSION,
        "as_of": funnel_fixtures.TRADE_DATE,
        "run_id": SOURCE_RUN_ID,
        "generated_at": funnel_fixtures.GENERATED_AT,
        "artifacts": artifacts,
        "dag": {
            "stages": ["candidates", "battery", "finalize"],
            "candidate_manifest_hash": candidate_manifest["manifest_hash"],
            "battery_rows_hash": battery["rows_hash"],
        },
    }
    manifest["bundle_hash"] = funnel._hash(artifacts)
    _write_json(bundle / "manifest.json", manifest)
    packet = closure.build_review_packet(
        bundle_dir=bundle,
        battery=None,
        generated_at=GENERATED_AT,
    )
    semantics: dict[str, tuple[str, ...] | str] = {
        "selected": tuple(clean_codes[:3]),
        "reject": clean_codes[3],
        "defer": clean_codes[4],
        "no_trade": clean_codes[5],
        "blocked": blocked_code,
        "dual_blocked": dual_blocked_code,
        "red_flags": tuple(red_codes),
        "ready": tuple(clean_codes[:6]),
    }
    return bundle, battery, packet, semantics


_SOURCE_TMP = tempfile.TemporaryDirectory(prefix="ar-u4-source-")
SOURCE_BUNDLE, SOURCE_BATTERY, _PACKET_TEMPLATE, _SEMANTICS = _build_source_evidence(
    Path(_SOURCE_TMP.name)
)
SELECT_CODES = tuple(_SEMANTICS["selected"])
REJECT_CODE = str(_SEMANTICS["reject"])
DEFER_CODE = str(_SEMANTICS["defer"])
NO_TRADE_CODE = str(_SEMANTICS["no_trade"])
BLOCKED_CODE = str(_SEMANTICS["blocked"])
DUAL_BLOCKED_CODE = str(_SEMANTICS["dual_blocked"])
RED_FLAG_CODES = tuple(_SEMANTICS["red_flags"])
PLAIN_RED_FLAG_CODE = next(code for code in RED_FLAG_CODES if code != DUAL_BLOCKED_CODE)
READY_CODES = tuple(_SEMANTICS["ready"])
TOTAL_ROWS = len(_PACKET_TEMPLATE["ready_pool"])


def packet_fixture(*, generated_at: str = GENERATED_AT) -> dict:
    if generated_at == GENERATED_AT:
        return copy.deepcopy(_PACKET_TEMPLATE)
    return closure.build_review_packet(
        bundle_dir=SOURCE_BUNDLE,
        battery=None,
        generated_at=generated_at,
    )


DEFAULT_DECISIONS = {
    **{code: "SELECT" for code in SELECT_CODES},
    REJECT_CODE: "REJECT",
    DEFER_CODE: "DEFER",
    NO_TRADE_CODE: "NO_TRADE",
    BLOCKED_CODE: "DATA_BLOCKED",
    DUAL_BLOCKED_CODE: "DATA_BLOCKED",
    PLAIN_RED_FLAG_CODE: "REJECT",
}


def decision_row(
    code: str,
    decision: str,
    *,
    revision: int = 1,
    supersedes: str | None = None,
) -> dict:
    reason_codes = [{
        "SELECT": "EVIDENCE_CHAIN_COMPLETE",
        "REJECT": "HUMAN_JUDGMENT",
        "DEFER": "QUEUE_CAPACITY",
        "NO_TRADE": "NO_ACTIONABLE_SETUP",
        "DATA_BLOCKED": "U3_INCOMPLETE",
    }[decision]]
    if code in RED_FLAG_CODES:
        reason_codes = ["RED_FLAG_ACTIVE"]
        if decision == "DATA_BLOCKED":
            reason_codes.insert(0, "U3_INCOMPLETE")
    missing = ["U3_SIX_DIMENSION_BATTERY"] if decision == "DATA_BLOCKED" else []
    return {
        "ts_code": code,
        "decision": decision,
        "reason_codes": reason_codes,
        "reason_note": f"Frozen offline U4 decision for {code}: {decision}.",
        "missing_evidence": missing,
        "research_question": (
            f"Which registered evidence would falsify the semiconductor thesis for {code}?"
            if decision == "SELECT" else None
        ),
        "decision_revision": revision,
        "supersedes_decision_id": supersedes,
    }


def draft_for(
    packet: dict,
    decisions: dict[str, str] | None = None,
    *,
    revision: int = 1,
    supersedes: dict[str, str] | None = None,
    decided_at: str = DECIDED_AT,
) -> dict:
    decisions = dict(decisions or DEFAULT_DECISIONS)
    supersedes = supersedes or {}
    return {
        "method_version": "SEMICONDUCTOR_WORKFLOW_DEBUG_V1",
        "decided_at": decided_at,
        "claimed_decision_owner": "Junyan",
        "identity_verification": "UNAVAILABLE",
        "authorization_text": (
            f"批准离线 U4 决策记录，绑定 packet_hash {packet['packet_hash'][:12]}，"
            "仅用于研究闭环调试，不产生交易或生产权限。"
        ),
        "authorization_evidence_ref": "conversation:2026-08-22-u4-ledger-v1",
        "decisions": [
            decision_row(code, decision, revision=revision, supersedes=supersedes.get(code))
            for code, decision in sorted(decisions.items())
        ],
    }


def append_fixture(
    path: Path,
    *,
    packet: dict | None = None,
    draft: dict | None = None,
    now: str = REGISTERED_AT,
) -> tuple[dict, dict, dict]:
    packet = packet or packet_fixture()
    draft = draft or draft_for(packet)
    result = append_batch(packet=packet, draft=draft, ledger_path=path, now=now)
    return packet, draft, result


def append_batch(*, now: str = REGISTERED_AT, **kwargs) -> dict:
    kwargs.setdefault("bundle_dir", SOURCE_BUNDLE)
    with patch.object(event_ledger, "_runtime_timestamp", return_value=now):
        return ledger.append_decision_batch(**kwargs)


class U4DecisionLedgerTests(unittest.TestCase):
    def test_all_five_outcomes_are_persisted_as_individual_295_events(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            events = ledger.current_packet_decisions(path, packet["packet_hash"])
            verified = ledger.verify_decision_ledger(path)
        self.assertEqual({event["decision"] for event in events}, ledger.DECISIONS)
        self.assertEqual(len(events), len(packet["ready_pool"]))
        self.assertTrue(all(frozen_spec._contract_errors(event) == [] for event in events))
        self.assertEqual(verified["n"], TOTAL_ROWS)
        self.assertEqual(verified["closures"], 1)
        self.assertEqual(verified["pending_packets"], [])

    def test_registered_at_is_writer_stamped_from_outer_r015_timestamp(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        draft["registered_at"] = "2020-01-01T00:00:00+08:00"
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "fields are not exact"):
            ledger._validate_draft(packet, draft)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet, now=REGISTERED_AT)
            outer = [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if json.loads(line)["kind"] == ledger.EVENT_KIND
            ]
        self.assertTrue(all(item["payload"]["registered_at"] == "2026-08-22T00:16:00+08:00" for item in outer))
        self.assertTrue(all(item["payload"]["registration_source"] == "R015_EVENT_LEDGER_TS" for item in outer))
        self.assertTrue(all(item["id"] == item["payload"]["decision_id"] for item in outer))
        parameters = inspect.signature(ledger.append_decision_batch).parameters
        self.assertNotIn("_test_now", parameters)
        self.assertNotIn("registered_at", parameters)
        self.assertNotIn("receipt_path", parameters)

    def test_fractional_decision_time_is_preserved_at_the_r015_boundary(self) -> None:
        decided_at = "2026-08-22T00:15:00.500+08:00"
        expected_registered_at = "2026-08-22T00:15:00.500000+08:00"
        self.assertEqual(
            ledger._registered_at_from_outer(decided_at),
            expected_registered_at,
        )
        packet = packet_fixture()
        draft = draft_for(packet, decided_at=decided_at)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_batch(
                packet=packet,
                draft=draft,
                ledger_path=path,
                now=decided_at,
            )
            events = ledger.current_packet_decisions(path, packet["packet_hash"])
        self.assertTrue(events)
        self.assertTrue(
            all(event["registered_at"] == expected_registered_at for event in events)
        )

    def test_runtime_stamp_precision_preserves_u4_and_following_shared_event(self) -> None:
        decided_at = "2026-08-22T00:15:00.500+08:00"
        runtime_at = "2026-08-22T00:15:00.600000"
        packet = packet_fixture()
        draft = draft_for(packet, decided_at=decided_at)

        self.assertRegex(
            event_ledger._runtime_timestamp(),
            r"\.\d{6}$",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            try:
                with patch.object(
                    event_ledger, "_runtime_timestamp", return_value=runtime_at
                ) as typed_clock:
                    ledger.append_decision_batch(
                        packet=packet,
                        draft=draft,
                        bundle_dir=SOURCE_BUNDLE,
                        ledger_path=path,
                    )
            except ledger.DecisionLedgerError as exc:
                self.fail(f"typed U4 runtime timestamp lost subsecond ordering: {exc}")
            with patch.object(
                event_ledger,
                "_runtime_timestamp",
                return_value="2026-08-22T00:15:00.700000",
            ):
                foreign = event_ledger.append("note", "same-second-later", {}, path=str(path))
            events = ledger.current_packet_decisions(path, packet["packet_hash"])
            verified = event_ledger.verify(str(path))

        self.assertTrue(events)
        self.assertTrue(
            all(
                event["registered_at"] == "2026-08-22T00:15:00.600000+08:00"
                for event in events
            )
        )
        self.assertEqual(foreign["ts"], "2026-08-22T00:15:00.700000")
        self.assertTrue(verified["ok"])
        self.assertTrue(typed_clock.call_args_list)
        self.assertTrue(all(not call.args and not call.kwargs for call in typed_clock.call_args_list))

    def test_registration_cannot_predate_human_decision(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "registered before"):
                append_fixture(path, packet=packet, now="2026-08-22T00:14:59")
            self.assertFalse(path.exists())
        rows, draft_rows = ledger._validate_draft(packet, draft_for(packet))
        ready_by_code = {row["ts_code"]: row for row in rows}
        item = ledger._intent_from_draft(
            packet,
            draft_for(packet),
            draft_rows[SELECT_CODES[0]],
            ready_by_code[SELECT_CODES[0]],
        )
        backdated = ledger._build_event(
            item,
            sequence=1,
            previous_hash=None,
            registered_at="2026-08-22T00:14:59+08:00",
        )
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "registered_at cannot predate"):
            ledger.validate_decision_event(backdated)

    def test_malformed_candidate_is_rejected_before_its_wal_append(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        original = ledger._build_event

        def malformed(*args, **kwargs):
            event = original(*args, **kwargs)
            if kwargs.get("registered_at") == "2026-08-22T00:16:00+08:00":
                event["authority"]["trade_authority"] = True
                event["record_hash"] = ledger._record_hash(event)
            return event

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            with patch.object(ledger, "_build_event", side_effect=malformed):
                with self.assertRaisesRegex(ledger.DecisionLedgerError, "forbidden trade"):
                    append_batch(packet=packet, draft=draft, ledger_path=path)
            kinds = [
                json.loads(line)["kind"]
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
        self.assertEqual(kinds, [ledger.INTENT_KIND])

    def test_method_version_is_required_and_versioned(self) -> None:
        packet = packet_fixture()
        for value in (None, "", "workflow-debug", "SEMICONDUCTOR_WORKFLOW"):
            draft = draft_for(packet)
            if value is None:
                del draft["method_version"]
                marker = "fields are not exact"
            else:
                draft["method_version"] = value
                marker = "method_version"
            with self.subTest(value=value):
                with self.assertRaisesRegex(ledger.DecisionLedgerError, marker):
                    ledger._validate_draft(packet, draft)

    def test_selection_count_is_only_zero_or_three_to_five(self) -> None:
        packet = packet_fixture()
        ready_codes = list(READY_CODES)
        for count in (1, 2, 6):
            decisions = dict(DEFAULT_DECISIONS)
            for index, code in enumerate(ready_codes):
                decisions[code] = "SELECT" if index < count else "DEFER"
            with self.subTest(count=count):
                with self.assertRaisesRegex(ledger.DecisionLedgerError, "zero or 3..5"):
                    ledger._validate_draft(packet, draft_for(packet, decisions))
        for count in (0, 3, 4, 5):
            decisions = dict(DEFAULT_DECISIONS)
            for index, code in enumerate(ready_codes):
                decisions[code] = "SELECT" if index < count else "DEFER"
            ledger._validate_draft(packet, draft_for(packet, decisions))

    def test_packet_candidate_set_must_include_reject_defer_no_trade_and_blocked_rows(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        draft["decisions"] = draft["decisions"][:-1]
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "candidate set"):
            ledger._validate_draft(packet, draft)

    def test_ready_pool_machine_source_and_hash_are_recomputed(self) -> None:
        packet = packet_fixture()
        ready_row = next(row for row in packet["ready_pool"] if row["ready"])
        ready_row["blocked_reasons"] = ["U3_BATTERY_INCOMPLETE"]
        packet["source_refs"]["ready_pool_hash"] = funnel._hash(packet["ready_pool"])
        packet["packet_hash"] = funnel._hash({key: value for key, value in packet.items() if key != "packet_hash"})
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "contradicts blocked_reasons"):
            ledger._ready_rows(packet)
        packet = packet_fixture()
        packet["source_refs"]["ready_pool_hash"] = "9" * 64
        packet["packet_hash"] = funnel._hash({key: value for key, value in packet.items() if key != "packet_hash"})
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "ready_pool hash mismatch"):
            ledger._ready_rows(packet)
        packet = packet_fixture()
        draft = draft_for(packet)
        draft["decisions"][0]["ts_code"] = "699999.SH"
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "candidate set"):
            ledger._validate_draft(packet, draft)

    def test_event_candidate_and_source_are_derived_only_from_the_packet(self) -> None:
        packet = packet_fixture()
        rows, decisions = ledger._validate_draft(packet, draft_for(packet))
        intent = ledger._build_packet_intent(
            packet, draft_for(packet), decisions, rows
        )
        first = intent["candidate_intents"][0]
        packet_row = packet["ready_pool"][0]
        self.assertEqual(first["candidate"], ledger._candidate_for(packet_row))
        self.assertEqual(first["source"], ledger._source_for(packet, packet_row))
        tampered = copy.deepcopy(intent)
        tampered["candidate_intents"][0]["candidate"]["display_name"] = "Invented Name"
        tampered["intent_hash"] = ledger._intent_hash(tampered)
        tampered["intent_id"] = ledger._packet_intent_id(tampered)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "packet-bound provenance"):
            ledger.validate_packet_intent(tampered)

    def test_source_separates_full_battery_and_candidate_row_hashes(self) -> None:
        packet = packet_fixture()
        row = packet["ready_pool"][0]
        source = ledger._source_for(packet, row)
        self.assertEqual(
            source["u3_battery_hash"],
            "sha256:" + packet["source_refs"]["battery_hash"],
        )
        self.assertEqual(
            source["u3_battery_row_hash"],
            "sha256:" + row["u3_battery_row_hash"],
        )
        self.assertNotEqual(
            source["u3_battery_hash"], source["u3_battery_row_hash"]
        )

    def test_writer_rebuilds_packet_from_immutable_u2_u3_evidence_before_wal(self) -> None:
        for mutate in ("run_id", "candidate"):
            packet = packet_fixture()
            if mutate == "run_id":
                packet["source_refs"]["run_id"] = "FORGED_RUN"
            else:
                packet["ready_pool"][0]["display_name"] = "Fabricated Candidate"
                packet["source_refs"]["ready_pool_hash"] = funnel._hash(packet["ready_pool"])
            packet["packet_hash"] = funnel._hash({
                key: value for key, value in packet.items() if key != "packet_hash"
            })
            closure.validate_review_packet(packet)
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "events.jsonl"
                with self.assertRaisesRegex(
                    ledger.DecisionLedgerError, "deterministic projection"
                ):
                    append_batch(
                        packet=packet,
                        draft=draft_for(packet),
                        ledger_path=path,
                    )
                self.assertFalse(path.exists())

    def test_packet_and_human_decision_cannot_predate_frozen_evidence(self) -> None:
        packet = closure.build_review_packet(
            bundle_dir=SOURCE_BUNDLE,
            battery=None,
            generated_at="2026-08-11T00:30:00+00:00",
        )
        draft = draft_for(packet, decided_at="2026-08-11T01:00:00+00:00")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            with self.assertRaisesRegex(
                ledger.DecisionLedgerError, "predates frozen evidence"
            ):
                append_batch(
                    packet=packet,
                    draft=draft,
                    ledger_path=path,
                    now="2026-08-22T00:16:00",
                )
            self.assertFalse(path.exists())

    def test_writer_rejects_drifted_dag_bundle_before_wal(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "bundle"
            shutil.copytree(SOURCE_BUNDLE, bundle)
            battery_path = bundle / "candidate_battery.json"
            battery_path.write_text(
                battery_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
            )
            path = root / "events.jsonl"
            with self.assertRaisesRegex(
                ledger.DecisionLedgerError, "bundle artifact hash mismatch"
            ):
                append_batch(
                    packet=packet,
                    draft=draft_for(packet),
                    ledger_path=path,
                    bundle_dir=bundle,
                )
            self.assertFalse(path.exists())

    def test_dag_manifest_cannot_relabel_embedded_stage_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle"
            shutil.copytree(SOURCE_BUNDLE, bundle)
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["dag"]["candidate_manifest_hash"] = "0" * 64
            manifest["dag"]["battery_rows_hash"] = "1" * 64
            _write_json(manifest_path, manifest)
            with self.assertRaisesRegex(closure.ClosureError, "DAG bundle evidence"):
                closure.load_bundle(bundle)

    def test_dag_manifest_metadata_is_exact_and_version_bound(self) -> None:
        mutations = (
            ("stages", lambda manifest: manifest["dag"].__setitem__("stages", ["finalize"])),
            ("unknown", lambda manifest: manifest["dag"].__setitem__("invented", True)),
            ("rule_version", lambda manifest: manifest.__setitem__("rule_version", "RELABELLED_V999")),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                bundle = Path(tmp) / "bundle"
                shutil.copytree(SOURCE_BUNDLE, bundle)
                manifest_path = bundle / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                mutate(manifest)
                _write_json(manifest_path, manifest)
                with self.assertRaisesRegex(
                    closure.ClosureError,
                    "canonical three-stage contract|rule_version mismatch",
                ):
                    closure.load_bundle(bundle)

    def test_dag_candidate_manifest_cannot_self_consistently_omit_a_u2_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle"
            shutil.copytree(SOURCE_BUNDLE, bundle)
            candidate_manifest_path = bundle / "candidate_manifest.json"
            candidate_manifest = json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
            omitted = candidate_manifest["ts_codes"].pop()
            candidate_manifest["expected_count"] = len(candidate_manifest["ts_codes"])
            candidate_manifest["manifest_hash"] = funnel._hash({
                key: value
                for key, value in candidate_manifest.items()
                if key != "manifest_hash"
            })
            _write_json(candidate_manifest_path, candidate_manifest)

            battery_path = bundle / "candidate_battery.json"
            battery = json.loads(battery_path.read_text(encoding="utf-8"))
            battery["results"] = [
                row for row in battery["results"] if row["ts_code"] != omitted
            ]
            battery["rows_hash"] = funnel._hash(battery["results"])
            battery["manifest_hash"] = candidate_manifest["manifest_hash"]
            _write_json(battery_path, battery)

            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"]["candidate_manifest.json"] = hashlib.sha256(
                candidate_manifest_path.read_bytes()
            ).hexdigest()
            manifest["artifacts"]["candidate_battery.json"] = hashlib.sha256(
                battery_path.read_bytes()
            ).hexdigest()
            manifest["dag"]["candidate_manifest_hash"] = candidate_manifest["manifest_hash"]
            manifest["dag"]["battery_rows_hash"] = battery["rows_hash"]
            manifest["bundle_hash"] = funnel._hash(manifest["artifacts"])
            _write_json(manifest_path, manifest)

            with self.assertRaisesRegex(closure.ClosureError, "exact projection"):
                closure.load_bundle(bundle)

    def test_normal_pipeline_candidates_keep_pending_clusters_without_blocking_u4(self) -> None:
        packet = packet_fixture()
        candidates = json.loads(
            (SOURCE_BUNDLE / "candidate_review.json").read_text(encoding="utf-8")
        )
        self.assertTrue(all(row["cluster_id"] is None for row in candidates["rows"]))
        self.assertTrue(all(row["causal_cluster_id"] == "UNAVAILABLE" for row in packet["ready_pool"]))
        self.assertTrue(all(row["cohort_id"] == "UNAVAILABLE" for row in packet["ready_pool"]))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            result = append_batch(
                packet=packet,
                draft=draft_for(packet),
                ledger_path=path,
            )
            events = ledger.current_packet_decisions(path, packet["packet_hash"])
        self.assertEqual(result["closure"]["selected_count"], 3)
        self.assertEqual(sum(event["decision"] == "SELECT" for event in events), 3)
        self.assertTrue(all(event["candidate"]["causal_cluster_id"] == "UNAVAILABLE" for event in events))
        self.assertTrue(all(event["candidate"]["cohort_id"] == "UNAVAILABLE" for event in events))
        self.assertTrue(all(event["authority"]["production_authority"] is False for event in events))

    def test_legacy_review_packet_is_valid_but_cannot_enter_the_v1_ledger(self) -> None:
        packet = closure.build_review_packet(
            bundle_dir=SOURCE_BUNDLE,
            battery=None,
            generated_at=GENERATED_AT,
            packet_version=closure.LEGACY_PACKET_SCHEMA_VERSION,
        )
        closure.validate_review_packet(packet)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "requires review packet v1.1"):
            ledger._validate_draft(packet, draft_for(packet))

    def test_dual_u3_and_red_flag_block_preserves_both_evidence_reasons(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        dual = next(row for row in draft["decisions"] if row["ts_code"] == DUAL_BLOCKED_CODE)
        self.assertEqual(dual["decision"], "DATA_BLOCKED")
        self.assertEqual(set(dual["reason_codes"]), {"U3_INCOMPLETE", "RED_FLAG_ACTIVE"})
        ledger._validate_draft(packet, draft)

        attack = copy.deepcopy(draft)
        attacked = next(row for row in attack["decisions"] if row["ts_code"] == DUAL_BLOCKED_CODE)
        attacked["reason_codes"] = ["U3_INCOMPLETE"]
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "preserve both evidence"):
            ledger._validate_draft(packet, attack)

        rows, decisions = ledger._validate_draft(packet, draft)
        intent = ledger._build_packet_intent(packet, draft, decisions, rows)
        item = next(
            candidate for candidate in intent["candidate_intents"]
            if candidate["candidate"]["ts_code"] == DUAL_BLOCKED_CODE
        )
        ready_row = next(row for row in rows if row["ts_code"] == DUAL_BLOCKED_CODE)
        item["reason_codes"] = ["U3_INCOMPLETE"]
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "hides the E1 side"):
            ledger._validate_candidate_intent(
                item,
                packet,
                ready_row,
                revision=int(intent["decision_revision"]),
                method_version=str(intent["method_version"]),
                ledger_id=str(intent["ledger_id"]),
            )

    def test_machine_blocked_rows_cannot_be_silently_selected_or_deferred(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        blocked = next(row for row in draft["decisions"] if row["ts_code"] == BLOCKED_CODE)
        blocked.update({
            "decision": "DEFER",
            "reason_codes": ["QUEUE_CAPACITY"],
            "missing_evidence": [],
        })
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "explicit DATA_BLOCKED"):
            ledger._validate_draft(packet, draft)
        draft = draft_for(packet)
        flagged = next(row for row in draft["decisions"] if row["ts_code"] == PLAIN_RED_FLAG_CODE)
        flagged.update({"decision": "SELECT", "reason_codes": ["EVIDENCE_CHAIN_COMPLETE"], "research_question": "Why?"})
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "explicit REJECT"):
            ledger._validate_draft(packet, draft)

    def test_select_and_data_blocked_semantics_fail_closed_before_wal(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        selected = next(row for row in draft["decisions"] if row["decision"] == "SELECT")
        selected["research_question"] = None
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "SELECT requires"):
            ledger._validate_draft(packet, draft)
        draft = draft_for(packet)
        blocked = next(row for row in draft["decisions"] if row["decision"] == "DATA_BLOCKED")
        blocked["missing_evidence"] = []
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "DATA_BLOCKED requires"):
            ledger._validate_draft(packet, draft)

    def test_closed_taxonomies_and_authority_fail_closed(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        draft["decisions"][0]["reason_codes"] = ["MADE_UP_REASON"]
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "closed taxonomy"):
            ledger._validate_draft(packet, draft)
        for field, value in (
            ("claimed_decision_owner", "Automation"),
            ("identity_verification", "VERIFIED"),
        ):
            draft = draft_for(packet)
            draft[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ledger.DecisionLedgerError, "authority boundary"):
                    ledger._validate_draft(packet, draft)

    def test_authorization_and_chronology_are_packet_bound(self) -> None:
        packet = packet_fixture()
        mutations = (
            ("authorization_text", "批准执行本次离线研究决策记录，但这段文字故意没有绑定任何冻结证据。", "packet-bound"),
            ("authorization_evidence_ref", "local-note", "externally anchored"),
            ("decided_at", "2026-08-22T00:09:59+08:00", "cannot predate"),
        )
        for field, value, marker in mutations:
            draft = draft_for(packet)
            draft[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ledger.DecisionLedgerError, marker):
                    ledger._validate_draft(packet, draft)

    def test_typed_append_rejects_unbound_or_predated_human_evidence_before_wal(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        rows, draft_rows = ledger._validate_draft(packet, draft)
        base_intent = ledger._build_packet_intent(packet, draft, draft_rows, rows)

        def unbind_authorization(human: dict) -> None:
            human["authorization_text"] = (
                "Substantive offline authorization text that is not bound to the packet hash."
            )

        def predate_packet(human: dict) -> None:
            human["decided_at"] = "2026-08-21T00:00:00+08:00"

        for mutate, marker in (
            (unbind_authorization, "packet-bound"),
            (predate_packet, "predate"),
        ):
            intent = copy.deepcopy(base_intent)
            for item in intent["candidate_intents"]:
                mutate(item["human_decision"])
            intent["intent_hash"] = ledger._intent_hash(intent)
            intent["intent_id"] = ledger._packet_intent_id(intent)
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "events.jsonl"
                with patch.object(
                    event_ledger, "_runtime_timestamp", return_value=REGISTERED_AT
                ):
                    with self.assertRaisesRegex(ledger.DecisionLedgerError, marker):
                        event_ledger.append_u4_stamped(
                            ledger.INTENT_KIND,
                            lambda _outer_ts: (intent["intent_id"], intent),
                            bundle_dir=SOURCE_BUNDLE,
                            path=str(path),
                        )
                self.assertFalse(path.exists())

    def test_event_hashes_and_internal_chain_are_recomputed(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            events = ledger.current_packet_decisions(path, packet["packet_hash"])
        for index, event in enumerate(events, 1):
            self.assertEqual(event["sequence"], index)
            self.assertEqual(event["decision_id"], ledger._decision_id(event))
            self.assertEqual(event["record_hash"], ledger._record_hash(event))
            expected_prev = None if index == 1 else events[index - 2]["record_hash"]
            self.assertEqual(event["previous_event_hash"], expected_prev)

    def test_persisted_decision_semantics_and_both_hash_formulas_are_independent_gates(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            events = ledger.current_packet_decisions(path, packet["packet_hash"])
        selected = copy.deepcopy(next(event for event in events if event["decision"] == "SELECT"))
        selected["research_question"] = None
        selected["decision_id"] = ledger._decision_id(selected)
        selected["record_hash"] = ledger._record_hash(selected)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "SELECT semantics"):
            ledger.validate_decision_event(selected)
        blocked = copy.deepcopy(next(event for event in events if event["decision"] == "DATA_BLOCKED"))
        blocked["missing_evidence"] = []
        blocked["decision_id"] = ledger._decision_id(blocked)
        blocked["record_hash"] = ledger._record_hash(blocked)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "DATA_BLOCKED"):
            ledger.validate_decision_event(blocked)
        bad_id = copy.deepcopy(events[0])
        bad_id["decision_id"] = "u4d_" + "a" * 32
        bad_id["record_hash"] = ledger._record_hash(bad_id)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "decision_id formula"):
            ledger.validate_decision_event(bad_id)
        bad_hash = copy.deepcopy(events[0])
        bad_hash["record_hash"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "record_hash formula"):
            ledger.validate_decision_event(bad_hash)

    def test_packet_intent_recomputes_packet_identity_and_its_own_hash(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            state = ledger._snapshot_state(path)
        packet_ref = ledger._packet_hash_ref(packet)
        intent = state["intents"][(packet_ref, 1)]
        wrong_packet = copy.deepcopy(intent)
        wrong_packet["u4_packet_hash"] = "sha256:" + "9" * 64
        wrong_packet["intent_hash"] = ledger._intent_hash(wrong_packet)
        wrong_packet["intent_id"] = ledger._packet_intent_id(wrong_packet)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "complete frozen packet"):
            ledger.validate_packet_intent(wrong_packet)
        wrong_hash = copy.deepcopy(intent)
        wrong_hash["intent_hash"] = "sha256:" + "a" * 64
        wrong_hash["intent_id"] = ledger._packet_intent_id(wrong_hash)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "intent hash"):
            ledger.validate_packet_intent(wrong_hash)

    def test_decision_event_must_match_the_preceding_full_packet_intent(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            state = ledger._snapshot_state(path)
        packet_ref = ledger._packet_hash_ref(packet)
        intent = state["intents"][(packet_ref, 1)]
        event = copy.deepcopy(min(state["current"].values(), key=lambda item: item["sequence"]))
        event["reason_note"] = "A self-consistent event that was never in the frozen packet intent."
        event["record_hash"] = ledger._record_hash(event)
        records = [
            {"kind": ledger.INTENT_KIND, "id": intent["intent_id"], "payload": intent, "ts": REGISTERED_AT},
            {"kind": ledger.EVENT_KIND, "id": event["decision_id"], "payload": event, "ts": REGISTERED_AT},
        ]
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "differs from its frozen packet intent"):
            ledger._replay_records(records)

    def test_closure_recomputes_its_packet_intent_binding(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            state = ledger._snapshot_state(path)
        packet_ref = ledger._packet_hash_ref(packet)
        receipt = copy.deepcopy(state["closures"][packet_ref][-1])
        receipt["intent_hash"] = "sha256:" + "b" * 64
        receipt["closure_hash"] = ledger._closure_hash(receipt)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "complete packet intent"):
            ledger.validate_packet_closure(
                receipt,
                state["current"],
                state["intents"][(packet_ref, 1)],
                tail_sequence=state["tail_sequence"],
                tail_hash=state["tail_hash"],
            )

    def test_candidate_and_closure_authority_never_escalate(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            state = ledger._snapshot_state(path)
        packet_ref = ledger._packet_hash_ref(packet)
        event = copy.deepcopy(next(iter(state["current"].values())))
        event["authority"]["trade_authority"] = True
        event["record_hash"] = ledger._record_hash(event)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "forbidden trade or production authority"):
            ledger.validate_decision_event(event)
        receipt = copy.deepcopy(state["closures"][packet_ref][-1])
        receipt["production_authority"] = True
        receipt["closure_hash"] = ledger._closure_hash(receipt)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "forbidden authority"):
            ledger.validate_packet_closure(
                receipt,
                state["current"],
                state["intents"][(packet_ref, 1)],
                tail_sequence=state["tail_sequence"],
                tail_hash=state["tail_hash"],
            )

    def test_zero_selection_commits_no_trade_and_never_projects_a_queue_receipt(self) -> None:
        packet = packet_fixture()
        decisions = dict(DEFAULT_DECISIONS)
        for code in READY_CODES:
            decisions[code] = "NO_TRADE"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            result = append_batch(
                packet=packet,
                draft=draft_for(packet, decisions),
                ledger_path=path,
            )
            receipt_path = Path(result["projection_path"])
            self.assertFalse(receipt_path.exists())
        closure_receipt = result["closure"]
        self.assertEqual(closure_receipt["selected_count"], 0)
        self.assertEqual(closure_receipt["outcome"], "NO_TRADE_NO_QUEUE")
        self.assertIsNone(closure_receipt["projected_receipt"])
        self.assertFalse(receipt_path.exists())

    def test_no_trade_retires_a_stale_derived_projection_after_commit(self) -> None:
        packet = packet_fixture()
        decisions = dict(DEFAULT_DECISIONS)
        for code in READY_CODES:
            decisions[code] = "NO_TRADE"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            receipt_path = ledger.projection_path_for(path, packet["packet_hash"])
            receipt_path.write_text('{"stale":true}\n', encoding="utf-8")
            result = append_batch(
                packet=packet,
                draft=draft_for(packet, decisions),
                ledger_path=path,
            )
            self.assertTrue(path.exists())
            self.assertFalse(receipt_path.exists())
            self.assertEqual(result["closure"]["selected_count"], 0)

    def test_three_selected_rows_project_the_existing_packet_bound_receipt(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            result = append_batch(
                packet=packet,
                draft=draft_for(packet),
                ledger_path=path,
            )
            receipt_path = Path(result["projection_path"])
            written = json.loads(receipt_path.read_text(encoding="utf-8"))
            ledger.validate_projection_envelope(written, packet)
            ledger.validate_current_projection(path, written, packet)
            tampered = copy.deepcopy(written)
            tampered["current_decision_set_hash"] = "sha256:" + "0" * 64
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "projection hash"):
                ledger.validate_projection_envelope(tampered, packet)
        closure.validate_review_receipt(written["review_receipt"], packet)
        self.assertEqual(result["closure"]["selected_count"], 3)
        self.assertEqual(result["projected_receipt"], written)

    def test_exact_retry_is_idempotent_and_conflicting_retry_is_refused(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            first = append_batch(packet=packet, draft=draft, ledger_path=path)
            before = path.read_bytes()
            retry = append_batch(packet=packet, draft=draft, ledger_path=path, now="2026-08-22T00:17:00")
            conflict = draft_for(packet)
            conflict["decisions"][3]["reason_note"] = "Conflicting rewrite at the same revision."
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "different frozen intent"):
                append_batch(packet=packet, draft=conflict, ledger_path=path, now="2026-08-22T00:18:00")
            after = path.read_bytes()
        self.assertEqual(first["status"], "APPENDED")
        self.assertEqual(retry["status"], "IDEMPOTENT")
        self.assertEqual(before, after)

    def test_interruption_after_intent_events_resumes_to_one_closure(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "injected interruption"):
                append_batch(
                    packet=packet,
                    draft=draft,
                    ledger_path=path,
                    _fail_after_decisions=3,
                )
            interrupted = ledger.verify_decision_ledger(path)
            visible_while_pending = ledger.current_packet_decisions(
                path, packet["packet_hash"]
            )
            resumed = append_batch(
                packet=packet,
                draft=draft,
                ledger_path=path,
                now="2026-08-22T00:17:00",
            )
            final = ledger.verify_decision_ledger(path)
        self.assertTrue(interrupted["ok"])
        self.assertEqual(interrupted["n"], 3)
        self.assertEqual(len(interrupted["pending_packets"]), 1)
        self.assertEqual(visible_while_pending, [])
        self.assertEqual(resumed["decision_events_appended"], TOTAL_ROWS - 3)
        self.assertEqual(final["n"], TOTAL_ROWS)
        self.assertEqual(final["closures"], 1)
        self.assertEqual(final["pending_packets"], [])

    def test_self_consistent_subset_closure_is_rejected_against_frozen_intent(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            state = ledger._snapshot_state(path)
        packet_ref = ledger._packet_hash_ref(packet)
        intent = state["intents"][(packet_ref, 1)]
        subset = sorted(
            (
                copy.deepcopy(event)
                for (subject_packet, code), event in state["current"].items()
                if subject_packet == packet_ref and code in set(SELECT_CODES)
            ),
            key=lambda event: event["candidate"]["ts_code"],
        )
        forged = ledger._build_closure(
            packet,
            subset,
            intent,
            tail_sequence=len(subset),
            tail_hash=subset[-1]["record_hash"],
        )
        subset_current = {ledger._subject(event): event for event in subset}
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "complete packet intent|subject set"):
            ledger.validate_packet_closure(
                forged,
                subset_current,
                intent,
                tail_sequence=len(subset),
                tail_hash=subset[-1]["record_hash"],
            )

    def test_conflicting_partial_retry_is_refused_before_any_new_wal_event(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "injected interruption"):
                append_batch(
                    packet=packet,
                    draft=draft,
                    ledger_path=path,
                    _fail_after_decisions=3,
                )
            before = path.read_bytes()
            conflict = copy.deepcopy(draft)
            conflict["decisions"][5]["reason_note"] = "Changed after the packet intent was frozen."
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "different frozen intent"):
                append_batch(
                    packet=packet,
                    draft=conflict,
                    ledger_path=path,
                    now="2026-08-22T00:17:00",
                )
            after = path.read_bytes()
            verified = ledger.verify_decision_ledger(path)
        self.assertEqual(before, after)
        self.assertEqual(verified["n"], 3)
        self.assertEqual(verified["intents"], 1)
        self.assertEqual(len(verified["pending_packets"]), 1)

    def test_partial_later_revision_keeps_the_prior_closure_public(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_batch(packet=packet, draft=draft_for(packet), ledger_path=path)
            committed = ledger.current_packet_decisions(path, packet["packet_hash"])
            supersedes = {
                event["candidate"]["ts_code"]: event["decision_id"]
                for event in committed
            }
            revised_decisions = dict(DEFAULT_DECISIONS)
            revised_decisions[REJECT_CODE] = "NO_TRADE"
            revised = draft_for(
                packet,
                revised_decisions,
                revision=2,
                supersedes=supersedes,
                decided_at="2026-08-22T00:20:00+08:00",
            )
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "injected interruption"):
                append_batch(
                    packet=packet,
                    draft=revised,
                    ledger_path=path,
                    now="2026-08-22T00:21:00",
                    _fail_after_decisions=3,
                )
            visible = ledger.current_packet_decisions(path, packet["packet_hash"])
            state = ledger._snapshot_state(path)
        self.assertTrue(all(event["decision_revision"] == 1 for event in visible))
        self.assertEqual(visible, committed)
        self.assertTrue(any(
            event["decision_revision"] == 2
            for event in state["staged_current"].values()
        ))

    def test_exact_retry_after_unrelated_packet_recovers_projection_without_wal_append(self) -> None:
        packet_a = packet_fixture()
        packet_b = packet_fixture(generated_at="2026-08-22T00:11:00+08:00")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            result_a = append_batch(packet=packet_a, draft=draft_for(packet_a), ledger_path=path)
            append_batch(packet=packet_b, draft=draft_for(packet_b), ledger_path=path)
            projection_a = Path(result_a["projection_path"])
            projection_a.unlink()
            before = path.read_bytes()
            retry_error = None
            try:
                retry = append_batch(
                    packet=packet_a,
                    draft=draft_for(packet_a),
                    ledger_path=path,
                    now="2026-08-22T00:17:00",
                )
            except Exception as exc:  # converted to an assertion so mutation kills stay attributable
                retry_error = exc
                retry = {}
            after = path.read_bytes()
            written = json.loads(projection_a.read_text(encoding="utf-8")) if projection_a.exists() else None
            state = ledger._snapshot_state(path)
        packet_ref = ledger._packet_hash_ref(packet_a)
        self.assertIsNone(retry_error)
        self.assertEqual(retry["status"], "IDEMPOTENT")
        self.assertEqual(before, after)
        self.assertEqual(written, retry["projected_receipt"])
        self.assertEqual(len(state["closures"][packet_ref]), 1)

    def test_projection_failure_after_closure_is_recovered_by_exact_retry(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            projection_path = ledger.projection_path_for(path, packet["packet_hash"])
            with patch.object(
                ledger,
                "_reconcile_projection",
                side_effect=ledger.DecisionLedgerError("injected projection interruption"),
            ):
                with self.assertRaisesRegex(ledger.DecisionLedgerError, "projection interruption"):
                    append_batch(packet=packet, draft=draft, ledger_path=path)
            committed = ledger.verify_decision_ledger(path)
            self.assertFalse(projection_path.exists())
            retry = append_batch(
                packet=packet,
                draft=draft,
                ledger_path=path,
                now="2026-08-22T00:17:00",
            )
            final = ledger.verify_decision_ledger(path)
            projection_recovered = projection_path.exists()
        self.assertTrue(committed["ok"])
        self.assertEqual(committed["closures"], 1)
        self.assertEqual(committed["pending_packets"], [])
        self.assertEqual(retry["status"], "IDEMPOTENT")
        self.assertTrue(projection_recovered)
        self.assertEqual(final["closures"], 1)

    def test_selected_revision_to_zero_selection_retires_committed_projection(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            first = append_batch(packet=packet, draft=draft_for(packet), ledger_path=path)
            projection_path = Path(first["projection_path"])
            self.assertTrue(projection_path.exists())
            stale_projection = json.loads(projection_path.read_text(encoding="utf-8"))
            current = ledger.current_packet_decisions(path, packet["packet_hash"])
            supersedes = {event["candidate"]["ts_code"]: event["decision_id"] for event in current}
            no_selection = dict(DEFAULT_DECISIONS)
            for code in READY_CODES:
                no_selection[code] = "NO_TRADE"
            revised = draft_for(
                packet,
                no_selection,
                revision=2,
                supersedes=supersedes,
                decided_at="2026-08-22T00:20:00+08:00",
            )
            second = append_batch(
                packet=packet,
                draft=revised,
                ledger_path=path,
                now="2026-08-22T00:21:00",
            )
            verified = ledger.verify_decision_ledger(path)
            projection_retired = not projection_path.exists()
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "stale or revoked"):
                ledger.validate_current_projection(path, stale_projection, packet)
            self.assertIsNone(ledger.load_current_projection(path, packet))
            closure.validate_review_receipt(stale_projection["review_receipt"], packet)
        self.assertEqual(second["closure"]["selected_count"], 0)
        self.assertEqual(second["closure"]["outcome"], "NO_TRADE_NO_QUEUE")
        self.assertTrue(projection_retired)
        self.assertEqual(verified["closures"], 2)
        self.assertEqual(verified["pending_packets"], [])

    def test_concurrent_exact_retries_converge_to_one_wal_transaction(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"

            def run(index: int) -> str:
                try:
                    return ledger.append_decision_batch(
                        packet=packet,
                        draft=draft,
                        ledger_path=path,
                        bundle_dir=SOURCE_BUNDLE,
                    )["status"]
                except (ledger.DecisionLedgerError, ValueError):
                    return "REFUSED"

            with patch.object(event_ledger, "_runtime_timestamp", return_value=REGISTERED_AT):
                with ThreadPoolExecutor(max_workers=8) as pool:
                    statuses = list(pool.map(run, range(8)))
            verified = ledger.verify_decision_ledger(path)
        self.assertEqual(statuses.count("APPENDED"), 1)
        self.assertEqual(statuses.count("IDEMPOTENT"), 7)
        self.assertEqual(verified["n"], TOTAL_ROWS)
        self.assertEqual(verified["closures"], 1)

    def test_concurrent_conflicting_retries_have_one_winner(self) -> None:
        packet = packet_fixture()
        first = draft_for(packet)
        second = draft_for(packet)
        second["decisions"][3]["reason_note"] = "A mutually exclusive decision rationale."
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"

            def run(draft: dict) -> str:
                try:
                    return ledger.append_decision_batch(
                        packet=packet,
                        draft=draft,
                        ledger_path=path,
                        bundle_dir=SOURCE_BUNDLE,
                    )["status"]
                except ledger.DecisionLedgerError:
                    return "REFUSED"

            with patch.object(event_ledger, "_runtime_timestamp", return_value=REGISTERED_AT):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    outcomes = list(pool.map(run, (first, second)))
            verified = ledger.verify_decision_ledger(path)
        self.assertEqual(sorted(outcomes), ["APPENDED", "REFUSED"])
        self.assertTrue(verified["ok"])

    def test_revision_appends_new_events_and_preserves_originals(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            original = ledger.current_packet_decisions(path, packet["packet_hash"])
            supersedes = {event["candidate"]["ts_code"]: event["decision_id"] for event in original}
            revised_decisions = dict(DEFAULT_DECISIONS)
            revised_decisions[REJECT_CODE] = "NO_TRADE"
            revised = draft_for(
                packet,
                revised_decisions,
                revision=2,
                supersedes=supersedes,
                decided_at="2026-08-22T00:20:00+08:00",
            )
            append_batch(
                packet=packet,
                draft=revised,
                ledger_path=path,
                now="2026-08-22T00:21:00",
            )
            current = ledger.current_packet_decisions(path, packet["packet_hash"])
            verified = ledger.verify_decision_ledger(path)
        self.assertEqual(len(original), TOTAL_ROWS)
        self.assertEqual(len(current), TOTAL_ROWS)
        self.assertTrue(all(event["decision_revision"] == 2 for event in current))
        self.assertEqual(verified["n"], TOTAL_ROWS * 2)
        self.assertEqual(verified["closures"], 2)

    def test_stale_or_cross_subject_revision_is_refused(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        draft["decisions"][0]["decision_revision"] = 2
        draft["decisions"][0]["supersedes_decision_id"] = "u4d_" + "a" * 32
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "coherent decision revision"):
            ledger._validate_draft(packet, draft)

    def test_shared_r015_ledger_may_contain_foreign_events(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            event_ledger.append("note", "foreign", {"value": 1}, path=str(path), now="2026-08-22T00:15:30")
            append_fixture(path, packet=packet)
            verified = ledger.verify_decision_ledger(path)
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["n"], TOTAL_ROWS)

    def test_verifier_detects_payload_tampering_even_when_outer_chain_is_rehashed(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            decision_outer = next(line for line in lines if line["kind"] == ledger.EVENT_KIND)
            decision_outer["payload"]["decision"] = "NO_TRADE"
            previous = event_ledger.GENESIS_PREV
            for outer in lines:
                outer["prev"] = previous
                outer["hash"] = event_ledger.record_hash(outer)
                previous = outer["hash"]
            path.write_text("\n".join(event_ledger.canonical(line) for line in lines) + "\n", encoding="utf-8")
            event_ledger.write_anchor(str(path), len(lines), lines[-1]["hash"])
            verified = ledger.verify_decision_ledger(path)
        self.assertFalse(verified["ok"])
        self.assertIn("decision_id formula mismatch", verified["errors"][0])

    def test_verifier_detects_closure_count_and_set_tampering(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            closure_outer = next(line for line in lines if line["kind"] == ledger.CLOSURE_KIND)
            closure_outer["payload"]["selected_count"] = 4
            closure_outer["payload"]["closure_hash"] = ledger._closure_hash(closure_outer["payload"])
            closure_outer["hash"] = event_ledger.record_hash(closure_outer)
            path.write_text("\n".join(event_ledger.canonical(line) for line in lines) + "\n", encoding="utf-8")
            event_ledger.write_anchor(str(path), len(lines), lines[-1]["hash"])
            verified = ledger.verify_decision_ledger(path)
        self.assertFalse(verified["ok"])
        self.assertIn("counts", verified["errors"][0])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            closure_outer = next(line for line in lines if line["kind"] == ledger.CLOSURE_KIND)
            codes = closure_outer["payload"]["reviewed_candidate_ids"][:-1]
            closure_outer["payload"]["reviewed_candidate_ids"] = codes
            closure_outer["payload"]["reviewed_candidate_set_hash"] = ledger._sha_value(codes)
            closure_outer["payload"]["closure_hash"] = ledger._closure_hash(closure_outer["payload"])
            previous = event_ledger.GENESIS_PREV
            for outer in lines:
                outer["prev"] = previous
                outer["hash"] = event_ledger.record_hash(outer)
                previous = outer["hash"]
            path.write_text("\n".join(event_ledger.canonical(line) for line in lines) + "\n", encoding="utf-8")
            event_ledger.write_anchor(str(path), len(lines), lines[-1]["hash"])
            verified_set = ledger.verify_decision_ledger(path)
        self.assertFalse(verified_set["ok"])
        self.assertIn("subject set", verified_set["errors"][0])

    def test_closure_numeric_fields_reject_bool_and_float_aliases(self) -> None:
        packet = packet_fixture()
        decisions = dict(DEFAULT_DECISIONS)
        for code in READY_CODES:
            decisions[code] = "NO_TRADE"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            result = append_batch(
                packet=packet,
                draft=draft_for(packet, decisions),
                ledger_path=path,
            )
            state = ledger._snapshot_state(path)
        packet_ref = ledger._packet_hash_ref(packet)
        intent = state["intents"][(packet_ref, 1)]

        def rehash(receipt: dict) -> None:
            identity = {
                "u4_packet_hash": receipt["u4_packet_hash"],
                "intent_id": receipt["intent_id"],
                "closure_revision": receipt["closure_revision"],
                "current_decision_ids": receipt["current_decision_ids"],
                "ledger_tail_hash": receipt["ledger_tail_hash"],
            }
            receipt["closure_id"] = "u4c_" + hashlib.sha256(
                ledger._canonical(identity).encode("utf-8")
            ).hexdigest()[:32]
            receipt["closure_hash"] = ledger._closure_hash(receipt)

        mutations = []
        bool_revision_and_count = copy.deepcopy(result["closure"])
        bool_revision_and_count["closure_revision"] = True
        bool_revision_and_count["selected_count"] = False
        mutations.append(bool_revision_and_count)
        bool_decision_count = copy.deepcopy(result["closure"])
        bool_decision_count["decision_counts"]["SELECT"] = False
        mutations.append(bool_decision_count)
        float_tail = copy.deepcopy(result["closure"])
        float_tail["ledger_tail_sequence"] = float(float_tail["ledger_tail_sequence"])
        mutations.append(float_tail)

        for receipt in mutations:
            rehash(receipt)
            with self.subTest(receipt=receipt):
                with self.assertRaisesRegex(ledger.DecisionLedgerError, "exact non-negative integers"):
                    ledger.validate_packet_closure(
                        receipt,
                        state["current"],
                        intent,
                        tail_sequence=state["tail_sequence"],
                        tail_hash=state["tail_hash"],
                    )

    def test_packet_intent_cardinality_and_closure_hash_are_independent_gates(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            state = ledger._snapshot_state(path)
        packet_ref = ledger._packet_hash_ref(packet)
        invalid_count = copy.deepcopy(state["intents"][(packet_ref, 1)])
        item = next(
            candidate_intent for candidate_intent in invalid_count["candidate_intents"]
            if candidate_intent["candidate"]["ts_code"] == SELECT_CODES[2]
        )
        item["decision"] = "DEFER"
        item["reason_codes"] = ["QUEUE_CAPACITY"]
        item["research_question"] = None
        invalid_count["intent_hash"] = ledger._intent_hash(invalid_count)
        invalid_count["intent_id"] = ledger._packet_intent_id(invalid_count)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "zero or 3..5"):
            ledger.validate_packet_intent(invalid_count)
        valid = copy.deepcopy(state["closures"][packet_ref][-1])
        valid["closure_hash"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "closure hash"):
            ledger.validate_packet_closure(
                valid,
                state["current"],
                state["intents"][(packet_ref, 1)],
                tail_sequence=state["tail_sequence"],
                tail_hash=state["tail_hash"],
            )

    def test_packet_intent_cannot_mix_distinct_human_decisions(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            state = ledger._snapshot_state(path)
        packet_ref = ledger._packet_hash_ref(packet)
        mixed = copy.deepcopy(state["intents"][(packet_ref, 1)])
        mixed["candidate_intents"][0]["human_decision"]["authorization_text"] = (
            f"A different offline authorization for packet_hash {packet['packet_hash'][:12]} "
            "cannot be spliced into the same frozen packet."
        )
        mixed["intent_hash"] = ledger._intent_hash(mixed)
        mixed["intent_id"] = ledger._packet_intent_id(mixed)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "coherent human decision"):
            ledger.validate_packet_intent(mixed)

    def test_outer_r015_timestamp_binding_cannot_be_relabelled(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            decision_outer = next(line for line in lines if line["kind"] == ledger.EVENT_KIND)
            decision_index = lines.index(decision_outer)
            for outer in lines[decision_index:]:
                outer["ts"] = "2026-08-22T00:16:01"
            previous = event_ledger.GENESIS_PREV
            for outer in lines:
                outer["prev"] = previous
                outer["hash"] = event_ledger.record_hash(outer)
                previous = outer["hash"]
            path.write_text("\n".join(event_ledger.canonical(line) for line in lines) + "\n", encoding="utf-8")
            event_ledger.write_anchor(str(path), len(lines), lines[-1]["hash"])
            verified = ledger.verify_decision_ledger(path)
        self.assertFalse(verified["ok"])
        self.assertIn("outer R-015 id/timestamp", verified["errors"][0])

    def test_u4_kinds_are_reserved_from_raw_and_generic_stamped_writers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            for kind in (ledger.INTENT_KIND, ledger.EVENT_KIND, ledger.CLOSURE_KIND):
                with self.subTest(kind=kind):
                    with self.assertRaisesRegex(ValueError, "typed-only"):
                        event_ledger.append(kind, kind, {}, path=str(path), now=REGISTERED_AT)
                    with self.assertRaisesRegex(ValueError, "typed-only"):
                        event_ledger.append_stamped(
                            kind, lambda _ts: (kind, {}), path=str(path)
                        )
                    with self.assertRaises(ledger.DecisionLedgerError):
                        event_ledger.append_u4_stamped(
                            kind,
                            lambda _ts: (kind, {}),
                            bundle_dir=SOURCE_BUNDLE,
                            path=str(path),
                        )
            self.assertFalse(path.exists())

    def test_typed_writer_rejects_self_consistent_fabricated_source(self) -> None:
        packet = packet_fixture()
        packet["source_refs"]["bundle_hash"] = "f" * 64
        packet["packet_hash"] = funnel._hash({
            key: value for key, value in packet.items() if key != "packet_hash"
        })
        closure.validate_review_packet(packet)
        rows, decisions = ledger._validate_draft(packet, draft_for(packet))
        intent = ledger._build_packet_intent(
            packet, draft_for(packet), decisions, rows
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            with self.assertRaisesRegex(
                ledger.DecisionLedgerError, "deterministic projection"
            ):
                event_ledger.append_u4_stamped(
                    ledger.INTENT_KIND,
                    lambda _ts: (intent["intent_id"], intent),
                    bundle_dir=SOURCE_BUNDLE,
                    path=str(path),
                )
            self.assertFalse(path.exists())

    def test_r015_u4_kind_uniqueness_is_independent_of_typed_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for kind in (ledger.INTENT_KIND, ledger.EVENT_KIND, ledger.CLOSURE_KIND):
                path = str(Path(tmp) / f"{kind}.jsonl")
                state, lines = event_ledger._append_preflight(path)
                event_ledger._append_verified(
                    kind, "same-id", {}, path, REGISTERED_AT, state, lines
                )
                state, lines = event_ledger._append_preflight(path)
                with self.subTest(kind=kind):
                    with self.assertRaisesRegex(ValueError, "拒绝重复登记"):
                        event_ledger._append_verified(
                            kind, "same-id", {}, path, REGISTERED_AT, state, lines
                        )

    def test_verifier_waits_for_atomic_ledger_anchor_snapshot(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            anchor_reached = Event()
            release_anchor = Event()
            verifier_started = Event()
            replay_entered = Event()
            counter_lock = Lock()
            calls = 0
            original_anchor = event_ledger.write_anchor
            original_replay = ledger._replay_records

            def delayed_anchor(*args, **kwargs):
                nonlocal calls
                with counter_lock:
                    calls += 1
                    first = calls == 1
                if first:
                    anchor_reached.set()
                    if not release_anchor.wait(timeout=5):
                        raise AssertionError("test did not release delayed anchor")
                return original_anchor(*args, **kwargs)

            def observed_replay(records):
                replay_entered.set()
                return original_replay(records)

            def verify() -> dict:
                verifier_started.set()
                return ledger.verify_decision_ledger(path)

            with patch.object(event_ledger, "_runtime_timestamp", return_value=REGISTERED_AT):
                with patch.object(event_ledger, "write_anchor", side_effect=delayed_anchor):
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        writer = pool.submit(
                            ledger.append_decision_batch,
                            packet=packet,
                            draft=draft,
                            ledger_path=path,
                            bundle_dir=SOURCE_BUNDLE,
                        )
                        self.assertTrue(anchor_reached.wait(timeout=5))
                        with patch.object(ledger, "_replay_records", side_effect=observed_replay):
                            reader = pool.submit(verify)
                            self.assertTrue(verifier_started.wait(timeout=5))
                            self.assertFalse(replay_entered.wait(timeout=0.2))
                            release_anchor.set()
                            self.assertTrue(reader.result(timeout=10)["ok"])
                        self.assertEqual(writer.result(timeout=10)["status"], "APPENDED")

    def test_strict_json_rejects_duplicate_keys_nonfinite_and_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            duplicate = Path(tmp) / "duplicate.json"
            duplicate.write_text('{"decisions":[],"decisions":[]}\n', encoding="utf-8")
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "duplicate JSON key"):
                ledger._load_json(duplicate)
            nonfinite = Path(tmp) / "nan.json"
            nonfinite.write_text('{"value":NaN}\n', encoding="utf-8")
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "non-finite"):
                ledger._load_json(nonfinite)
        packet = packet_fixture()
        draft = draft_for(packet)
        draft["trade_action"] = "BUY"
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "fields are not exact"):
            ledger._validate_draft(packet, draft)

    def test_cli_appends_then_verifies_without_a_production_default(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_path = root / "packet.json"
            draft_path = root / "draft.json"
            ledger_path = root / "ledger.jsonl"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            draft_path.write_text(json.dumps(draft), encoding="utf-8")
            args = [
                "--packet", str(packet_path),
                "--draft", str(draft_path),
                "--ledger", str(ledger_path),
                "--bundle-dir", str(SOURCE_BUNDLE),
            ]
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(ledger.main(args), 0)
                self.assertEqual(ledger.main(args), 0)
                self.assertEqual(
                    ledger.main(["--ledger", str(ledger_path), "--verify"]), 0
                )
            lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(lines[0]["status"], "APPENDED")
        self.assertEqual(lines[1]["status"], "IDEMPOTENT")
        self.assertEqual(lines[0]["projection_path"], lines[1]["projection_path"])
        self.assertTrue(lines[2]["ok"])

    def test_missing_ledger_is_not_a_clean_verification_or_cli_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.jsonl"
            result = ledger.verify_decision_ledger(path)
            self.assertFalse(result["ok"])
            self.assertIn("does not exist", result["errors"][0])
            self.assertFalse(Path(f"{path}.lock").exists())
            stdout = StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(
                    ledger.main(["--ledger", str(path), "--verify"]), 1
                )
            self.assertFalse(json.loads(stdout.getvalue())["ok"])

    def test_cli_write_requires_packet_and_draft_after_verify_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            stderr = StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(
                    ledger.main([
                        "--ledger", str(path),
                        "--bundle-dir", str(SOURCE_BUNDLE),
                    ]),
                    1,
                )
            self.assertIn("--packet and --draft", stderr.getvalue())
            self.assertFalse(path.exists())

    def test_cli_refuses_bad_contract_without_writing(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        draft["method_version"] = "bad"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_path = root / "packet.json"
            draft_path = root / "draft.json"
            ledger_path = root / "ledger.jsonl"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            draft_path.write_text(json.dumps(draft), encoding="utf-8")
            stderr = StringIO()
            with redirect_stderr(stderr):
                rc = ledger.main([
                    "--packet", str(packet_path),
                    "--draft", str(draft_path),
                    "--ledger", str(ledger_path),
                    "--bundle-dir", str(SOURCE_BUNDLE),
                ])
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED", stderr.getvalue())
        self.assertFalse(ledger_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
