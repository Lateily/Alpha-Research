#!/usr/bin/env python3
"""Behavior, WAL, concurrency, and #295 contract tests for the U4 ledger."""

from __future__ import annotations

import copy
import json
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
import test_u4_decision_ledger_spec as frozen_spec  # noqa: E402


GENERATED_AT = "2026-08-22T00:10:00+08:00"
DECIDED_AT = "2026-08-22T00:15:00+08:00"
REGISTERED_AT = "2026-08-22T00:16:00"


def ready_row(code: str, *, ready: bool, reasons: list[str] | None = None) -> dict:
    reasons = list(reasons or [])
    return {
        "ts_code": code,
        "ready": ready,
        "industry_key": "SEMICONDUCTOR",
        "sector_os_status": "AVAILABLE",
        "candidate_status": "MAIN_CHANNEL",
        "battery_verdict": "PARTIAL" if "U3_BATTERY_INCOMPLETE" in reasons else "COMPLETE",
        "blocked_reasons": reasons,
    }


def packet_fixture() -> dict:
    rows = [
        ready_row("600001.SH", ready=True),
        ready_row("600002.SH", ready=True),
        ready_row("600003.SH", ready=True),
        ready_row("600004.SH", ready=True),
        ready_row("600005.SH", ready=True),
        ready_row("600006.SH", ready=True),
        ready_row("600007.SH", ready=False, reasons=["U3_BATTERY_INCOMPLETE"]),
        ready_row("600008.SH", ready=False, reasons=["E1_RED_FLAG_REQUIRES_SEPARATE_REVIEW"]),
    ]
    packet = {
        "schema": closure.PACKET_SCHEMA,
        "schema_version": closure.SCHEMA_VERSION,
        "mode": "OFFLINE_RESEARCH_REPLAY",
        "status": "AWAITING_JUNYAN_REVIEW",
        "as_of": "20260821",
        "generated_at": GENERATED_AT,
        "source_refs": {
            "bundle_hash": "1" * 64,
            "scan_rows_hash": "2" * 64,
            "candidate_rows_hash": "3" * 64,
            "battery_hash": "4" * 64,
            "ready_pool_hash": funnel._hash(rows),
        },
        "random_control": {
            "control_batch_id": "CTRL_20260821_TEST",
            "eligible_universe_hash": "5" * 64,
            "seed_hex": "6" * 64,
            "algo": funnel.CONTROL_ALGO,
            "drawn_hash": "7" * 64,
            "replay_verified": True,
        },
        "authority": {
            "selection_owner": "Junyan",
            "identity_verification": "UNAVAILABLE",
            "production_authority": False,
            "required_selection_size": {"min": 3, "max": 5},
        },
        "ready_pool": rows,
        "claim_allowed": False,
        "next_gate": "JUNYAN_REVIEW_RECEIPT_BOUND_TO_PACKET_HASH",
        "disclaimer": closure.DISCLAIMER,
    }
    packet["packet_hash"] = funnel._hash(packet)
    closure.validate_review_packet(packet)
    return packet


DEFAULT_DECISIONS = {
    "600001.SH": "SELECT",
    "600002.SH": "SELECT",
    "600003.SH": "SELECT",
    "600004.SH": "REJECT",
    "600005.SH": "DEFER",
    "600006.SH": "NO_TRADE",
    "600007.SH": "DATA_BLOCKED",
    "600008.SH": "REJECT",
}


def candidate(code: str) -> dict:
    return {
        "ts_code": code,
        "display_name": f"Fixture {code}",
        "industry_code": "SEMICONDUCTOR",
        "cohort_id": "cohort-semiconductor-20260821",
        "causal_cluster_id": f"cluster-{code.replace('.', '-').lower()}",
    }


def decision_row(
    code: str,
    decision: str,
    *,
    revision: int = 1,
    supersedes: str | None = None,
) -> dict:
    reason = {
        "SELECT": "EVIDENCE_CHAIN_COMPLETE",
        "REJECT": "HUMAN_JUDGMENT",
        "DEFER": "QUEUE_CAPACITY",
        "NO_TRADE": "NO_ACTIONABLE_SETUP",
        "DATA_BLOCKED": "U3_INCOMPLETE",
    }[decision]
    if code == "600008.SH":
        reason = "RED_FLAG_ACTIVE"
    missing = ["U3_SIX_DIMENSION_BATTERY"] if decision == "DATA_BLOCKED" else []
    return {
        "candidate": candidate(code),
        "decision": decision,
        "reason_codes": [reason],
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
    result = ledger.append_decision_batch(
        packet=packet,
        draft=draft,
        ledger_path=path,
        _test_now=now,
    )
    return packet, draft, result


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
        self.assertEqual(verified["n"], 8)
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

    def test_registration_cannot_predate_human_decision(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "registered_at cannot predate"):
                append_fixture(path, packet=packet, now="2026-08-22T00:14:59")
            self.assertFalse(path.exists())

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
        ready_codes = [f"60000{index}.SH" for index in range(1, 7)]
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
        packet["ready_pool"][0]["blocked_reasons"] = ["U3_BATTERY_INCOMPLETE"]
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
        draft["decisions"][0]["candidate"]["ts_code"] = "699999.SH"
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "candidate set"):
            ledger._validate_draft(packet, draft)

    def test_machine_blocked_rows_cannot_be_silently_selected_or_deferred(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        blocked = next(row for row in draft["decisions"] if row["candidate"]["ts_code"] == "600007.SH")
        blocked.update({
            "decision": "DEFER",
            "reason_codes": ["QUEUE_CAPACITY"],
            "missing_evidence": [],
        })
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "explicit DATA_BLOCKED"):
            ledger._validate_draft(packet, draft)
        draft = draft_for(packet)
        flagged = next(row for row in draft["decisions"] if row["candidate"]["ts_code"] == "600008.SH")
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
                tail_sequence=state["tail_sequence"],
                tail_hash=state["tail_hash"],
            )

    def test_zero_selection_commits_no_trade_and_never_projects_a_queue_receipt(self) -> None:
        packet = packet_fixture()
        decisions = dict(DEFAULT_DECISIONS)
        for code in [f"60000{index}.SH" for index in range(1, 7)]:
            decisions[code] = "NO_TRADE"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            receipt_path = Path(tmp) / "receipt.json"
            result = ledger.append_decision_batch(
                packet=packet,
                draft=draft_for(packet, decisions),
                ledger_path=path,
                receipt_path=receipt_path,
                _test_now=REGISTERED_AT,
            )
        closure_receipt = result["closure"]
        self.assertEqual(closure_receipt["selected_count"], 0)
        self.assertEqual(closure_receipt["outcome"], "NO_TRADE_NO_QUEUE")
        self.assertIsNone(closure_receipt["projected_receipt"])
        self.assertFalse(receipt_path.exists())

    def test_no_trade_refuses_a_stale_receipt_before_any_wal_write(self) -> None:
        packet = packet_fixture()
        decisions = dict(DEFAULT_DECISIONS)
        for code in [f"60000{index}.SH" for index in range(1, 7)]:
            decisions[code] = "NO_TRADE"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            receipt_path = Path(tmp) / "receipt.json"
            receipt_path.write_text('{"stale":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "stale projected receipt"):
                ledger.append_decision_batch(
                    packet=packet,
                    draft=draft_for(packet, decisions),
                    ledger_path=path,
                    receipt_path=receipt_path,
                    _test_now=REGISTERED_AT,
                )
            self.assertFalse(path.exists())
            self.assertEqual(json.loads(receipt_path.read_text(encoding="utf-8")), {"stale": True})

    def test_three_selected_rows_project_the_existing_packet_bound_receipt(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            receipt_path = Path(tmp) / "receipt.json"
            result = ledger.append_decision_batch(
                packet=packet,
                draft=draft_for(packet),
                ledger_path=path,
                receipt_path=receipt_path,
                _test_now=REGISTERED_AT,
            )
            written = json.loads(receipt_path.read_text(encoding="utf-8"))
        closure.validate_review_receipt(written, packet)
        self.assertEqual(result["closure"]["selected_count"], 3)
        self.assertEqual(result["projected_receipt"], written)

    def test_exact_retry_is_idempotent_and_conflicting_retry_is_refused(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            first = ledger.append_decision_batch(packet=packet, draft=draft, ledger_path=path, _test_now=REGISTERED_AT)
            before = path.read_bytes()
            retry = ledger.append_decision_batch(packet=packet, draft=draft, ledger_path=path, _test_now="2026-08-22T00:17:00")
            conflict = draft_for(packet)
            conflict["decisions"][3]["reason_note"] = "Conflicting rewrite at the same revision."
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "different content"):
                ledger.append_decision_batch(packet=packet, draft=conflict, ledger_path=path, _test_now="2026-08-22T00:18:00")
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
                ledger.append_decision_batch(
                    packet=packet,
                    draft=draft,
                    ledger_path=path,
                    _test_now=REGISTERED_AT,
                    fail_after_decisions=3,
                )
            interrupted = ledger.verify_decision_ledger(path)
            resumed = ledger.append_decision_batch(
                packet=packet,
                draft=draft,
                ledger_path=path,
                _test_now="2026-08-22T00:17:00",
            )
            final = ledger.verify_decision_ledger(path)
        self.assertTrue(interrupted["ok"])
        self.assertEqual(interrupted["n"], 3)
        self.assertEqual(len(interrupted["pending_packets"]), 1)
        self.assertEqual(resumed["decision_events_appended"], 5)
        self.assertEqual(final["n"], 8)
        self.assertEqual(final["closures"], 1)
        self.assertEqual(final["pending_packets"], [])

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
                        _test_now=f"2026-08-22T00:16:{index:02d}",
                    )["status"]
                except (ledger.DecisionLedgerError, ValueError):
                    return "REFUSED"

            with ThreadPoolExecutor(max_workers=8) as pool:
                statuses = list(pool.map(run, range(8)))
            verified = ledger.verify_decision_ledger(path)
        self.assertEqual(statuses.count("APPENDED"), 1)
        self.assertEqual(statuses.count("IDEMPOTENT"), 7)
        self.assertEqual(verified["n"], 8)
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
                        _test_now=REGISTERED_AT,
                    )["status"]
                except ledger.DecisionLedgerError:
                    return "REFUSED"

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
            revised_decisions["600004.SH"] = "NO_TRADE"
            revised = draft_for(
                packet,
                revised_decisions,
                revision=2,
                supersedes=supersedes,
                decided_at="2026-08-22T00:20:00+08:00",
            )
            ledger.append_decision_batch(
                packet=packet,
                draft=revised,
                ledger_path=path,
                _test_now="2026-08-22T00:21:00",
            )
            current = ledger.current_packet_decisions(path, packet["packet_hash"])
            verified = ledger.verify_decision_ledger(path)
        self.assertEqual(len(original), 8)
        self.assertEqual(len(current), 8)
        self.assertTrue(all(event["decision_revision"] == 2 for event in current))
        self.assertEqual(verified["n"], 16)
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
        self.assertEqual(verified["n"], 8)

    def test_verifier_detects_payload_tampering_even_when_outer_chain_is_rehashed(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            lines[0]["payload"]["decision"] = "NO_TRADE"
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

    def test_closure_cardinality_and_hash_are_independent_gates(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            state = ledger._snapshot_state(path)
        packet_ref = ledger._packet_hash_ref(packet)
        events = sorted(
            (copy.deepcopy(event) for (subject_packet, _), event in state["current"].items() if subject_packet == packet_ref),
            key=lambda event: event["candidate"]["ts_code"],
        )
        for event in events:
            if event["candidate"]["ts_code"] == "600003.SH":
                event["decision"] = "DEFER"
        invalid_count = ledger._build_closure(
            packet,
            events,
            tail_sequence=state["tail_sequence"],
            tail_hash=state["tail_hash"],
        )
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "zero or 3..5"):
            ledger.validate_packet_closure(
                invalid_count,
                {(event["source"]["u4_packet_hash"], event["candidate"]["ts_code"]): event for event in events},
                tail_sequence=state["tail_sequence"],
                tail_hash=state["tail_hash"],
            )
        valid = copy.deepcopy(state["closures"][packet_ref][-1])
        valid["closure_hash"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "closure hash"):
            ledger.validate_packet_closure(
                valid,
                state["current"],
                tail_sequence=state["tail_sequence"],
                tail_hash=state["tail_hash"],
            )

    def test_outer_r015_timestamp_binding_cannot_be_relabelled(self) -> None:
        packet = packet_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            append_fixture(path, packet=packet)
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            lines[0]["ts"] = "2026-08-22T00:15:59"
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

    def test_both_u4_outer_event_kinds_are_unique_in_the_shared_wal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            event_ledger.append(ledger.EVENT_KIND, "same", {}, path=str(path), now=REGISTERED_AT)
            with self.assertRaisesRegex(ValueError, "拒绝重复登记"):
                event_ledger.append(ledger.EVENT_KIND, "same", {}, path=str(path), now=REGISTERED_AT)
            event_ledger.append(ledger.CLOSURE_KIND, "closure", {}, path=str(path), now=REGISTERED_AT)
            with self.assertRaisesRegex(ValueError, "拒绝重复登记"):
                event_ledger.append(ledger.CLOSURE_KIND, "closure", {}, path=str(path), now=REGISTERED_AT)

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

            with patch.object(event_ledger, "write_anchor", side_effect=delayed_anchor):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    writer = pool.submit(
                        ledger.append_decision_batch,
                        packet=packet,
                        draft=draft,
                        ledger_path=path,
                        _test_now=REGISTERED_AT,
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
            receipt_path = root / "receipt.json"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            draft_path.write_text(json.dumps(draft), encoding="utf-8")
            args = [
                "--packet", str(packet_path),
                "--draft", str(draft_path),
                "--ledger", str(ledger_path),
                "--receipt", str(receipt_path),
            ]
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(ledger.main(args), 0)
                self.assertEqual(ledger.main(args), 0)
                self.assertEqual(ledger.main(["--packet", str(packet_path), "--draft", str(draft_path), "--ledger", str(ledger_path), "--verify"]), 0)
            lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(lines[0]["status"], "APPENDED")
        self.assertEqual(lines[1]["status"], "IDEMPOTENT")
        self.assertTrue(lines[2]["ok"])

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
                ])
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED", stderr.getvalue())
        self.assertFalse(ledger_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
