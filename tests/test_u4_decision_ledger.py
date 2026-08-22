#!/usr/bin/env python3
"""Offline U4 decision-ledger behavior and append-only regression tests."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))

from experiments.execution_tracker import event_ledger  # noqa: E402
from experiments.research_funnel import closure_experiment as closure  # noqa: E402
from experiments.research_funnel import funnel_pipeline as funnel  # noqa: E402
from experiments.research_funnel import u4_decision_ledger as ledger  # noqa: E402


GENERATED_AT = "2026-08-22T00:10:00+08:00"
REVIEWED_AT = "2026-08-22T00:15:00+08:00"


def ready_row(code: str, *, ready: bool, reasons: list[str] | None = None) -> dict:
    reasons = list(reasons or [])
    return {
        "ts_code": code,
        "ready": ready,
        "industry_key": "半导体",
        "sector_os_status": "AVAILABLE",
        "candidate_status": "MAIN_CHANNEL",
        "battery_verdict": (
            "PARTIAL" if "U3_BATTERY_INCOMPLETE" in reasons else "COMPLETE"
        ),
        "blocked_reasons": reasons,
    }


def packet_fixture() -> dict:
    rows = [
        ready_row("600001.SH", ready=True),
        ready_row("600002.SH", ready=True),
        ready_row("600003.SH", ready=True),
        ready_row("600004.SH", ready=True),
        ready_row("600005.SH", ready=False, reasons=["U3_BATTERY_INCOMPLETE"]),
        ready_row("600006.SH", ready=False, reasons=["E1_RED_FLAG_REQUIRES_SEPARATE_REVIEW"]),
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


def draft_for(packet: dict, decisions: dict[str, str] | None = None) -> dict:
    decisions = decisions or {
        "600001.SH": "SELECT",
        "600002.SH": "SELECT",
        "600003.SH": "SELECT",
        "600004.SH": "DEFER",
    }
    rows = []
    for code, decision in sorted(decisions.items()):
        rows.append({
            "ts_code": code,
            "decision": decision,
            "reason_code": {
                "SELECT": "THESIS_RESEARCH_REQUIRED",
                "REJECT": "EVIDENCE_NOT_PERSUASIVE",
                "DEFER": "AWAIT_FRESH_EVIDENCE",
            }[decision],
            "reason_text": {
                "SELECT": "The frozen evidence merits an offline deep-research factpack.",
                "REJECT": "The frozen evidence does not justify scarce deep-research capacity.",
                "DEFER": "Wait for a registered catalyst update before another review.",
            }[decision],
            "research_question": (
                f"Which registered fact would invalidate the thesis for {code}?"
                if decision == "SELECT" else ""
            ),
        })
    return {
        "reviewed_at": REVIEWED_AT,
        "claimed_reviewer": "Junyan",
        "identity_verification": "UNAVAILABLE",
        "production_authority": False,
        "authorization_text": (
            f"批准离线 U4 决策批次，绑定 packet_hash {packet['packet_hash'][:12]}，"
            "不产生交易、组合或生产权限。"
        ),
        "decisions": rows,
    }


def rehash_batch(batch: dict) -> None:
    batch["decision_set_hash"] = funnel._hash(batch["decisions"])
    batch["batch_hash"] = funnel._hash({
        key: value for key, value in batch.items() if key != "batch_hash"
    })


class U4DecisionLedgerTests(unittest.TestCase):
    def test_complete_ready_pool_is_recorded_with_machine_rejections(self) -> None:
        packet = packet_fixture()
        batch = ledger.seal_decision_batch(draft_for(packet), packet)
        self.assertEqual(len(batch["decisions"]), len(packet["ready_pool"]))
        self.assertEqual(batch["selected_count"], 3)
        self.assertEqual(batch["machine_blocked_count"], 2)
        blocked = {row["ts_code"]: row for row in batch["decisions"] if not row["source_ready"]}
        self.assertEqual(blocked["600005.SH"]["decision"], "REJECT")
        self.assertEqual(blocked["600005.SH"]["decision_origin"], ledger.MACHINE_ORIGIN)
        self.assertEqual(blocked["600005.SH"]["reason_codes"], ["U3_BATTERY_INCOMPLETE"])

    def test_every_ready_candidate_requires_exactly_one_human_decision(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        draft["decisions"] = draft["decisions"][:-1]
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "cover every ready candidate"):
            ledger.seal_decision_batch(draft, packet)

    def test_machine_blocked_candidate_cannot_enter_human_decision_set(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        draft["decisions"].append({
            "ts_code": "600005.SH",
            "decision": "SELECT",
            "reason_code": "OVERRIDE_MACHINE_GATE",
            "reason_text": "Attempt to override the machine gate.",
            "research_question": "Why was this candidate blocked?",
        })
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "cover every ready candidate"):
            ledger.seal_decision_batch(draft, packet)

    def test_ready_source_semantics_and_pool_hash_are_recomputed(self) -> None:
        packet = packet_fixture()
        packet["ready_pool"][0]["blocked_reasons"] = ["CONTRADICTS_READY_TRUE"]
        packet["source_refs"]["ready_pool_hash"] = funnel._hash(packet["ready_pool"])
        packet["packet_hash"] = funnel._hash({
            key: value for key, value in packet.items() if key != "packet_hash"
        })
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "contradicts blocked_reasons"):
            ledger.seal_decision_batch(draft_for(packet), packet)

        packet = packet_fixture()
        packet["source_refs"]["ready_pool_hash"] = "9" * 64
        packet["packet_hash"] = funnel._hash({
            key: value for key, value in packet.items() if key != "packet_hash"
        })
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "ready_pool hash mismatch"):
            ledger.seal_decision_batch(draft_for(packet), packet)

    def test_ready_source_must_match_u3_and_e1_gate_evidence(self) -> None:
        packet = packet_fixture()
        packet["ready_pool"][0]["battery_verdict"] = "PARTIAL"
        packet["source_refs"]["ready_pool_hash"] = funnel._hash(packet["ready_pool"])
        packet["packet_hash"] = funnel._hash({
            key: value for key, value in packet.items() if key != "packet_hash"
        })
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "U3/E1 gate evidence"):
            ledger.seal_decision_batch(draft_for(packet), packet)

    def test_zero_selections_records_no_trade_and_projects_no_receipt(self) -> None:
        packet = packet_fixture()
        decisions = {
            "600001.SH": "REJECT",
            "600002.SH": "DEFER",
            "600003.SH": "REJECT",
            "600004.SH": "DEFER",
        }
        batch = ledger.seal_decision_batch(draft_for(packet, decisions), packet)
        self.assertEqual(batch["batch_outcome"], ledger.NO_TRADE_OUTCOME)
        self.assertEqual(batch["selected_count"], 0)
        self.assertIsNone(batch["projected_receipt_hash"])
        self.assertIsNone(ledger.project_review_receipt(batch, packet))
        self.assertFalse(batch["method_sample_eligible"])
        self.assertTrue(batch["no_trade_flag"])

    def test_three_selected_rows_project_existing_review_receipt(self) -> None:
        packet = packet_fixture()
        batch = ledger.seal_decision_batch(draft_for(packet), packet)
        receipt = ledger.project_review_receipt(batch, packet)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        closure.validate_review_receipt(receipt, packet)
        self.assertEqual(receipt["receipt_hash"], batch["projected_receipt_hash"])
        self.assertEqual(
            [row["ts_code"] for row in receipt["selections"]],
            ["600001.SH", "600002.SH", "600003.SH"],
        )

    def test_one_or_two_selected_candidates_are_refused(self) -> None:
        packet = packet_fixture()
        for selected_count in (1, 2):
            decisions = {
                code: ("SELECT" if index < selected_count else "DEFER")
                for index, code in enumerate((
                    "600001.SH", "600002.SH", "600003.SH", "600004.SH",
                ))
            }
            with self.subTest(selected_count=selected_count):
                with self.assertRaisesRegex(ledger.DecisionLedgerError, "zero or 3..5"):
                    ledger.seal_decision_batch(draft_for(packet, decisions), packet)

    def test_authority_chronology_and_packet_binding_fail_closed(self) -> None:
        packet = packet_fixture()
        no_trade = {
            "600001.SH": "REJECT",
            "600002.SH": "DEFER",
            "600003.SH": "REJECT",
            "600004.SH": "DEFER",
        }
        for field, value, marker in (
            ("claimed_reviewer", "NotJunyan", "authority boundary"),
            ("identity_verification", "VERIFIED", "authority boundary"),
            ("production_authority", True, "authority boundary"),
            ("reviewed_at", "2026-08-21T23:59:00+08:00", "cannot predate"),
            ("authorization_text", "批准离线，但未绑定哈希。", "packet-bound"),
        ):
            draft = draft_for(packet, no_trade)
            draft[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ledger.DecisionLedgerError, marker):
                    ledger.seal_decision_batch(draft, packet)

    def test_human_decision_and_authorization_fields_are_not_coerced(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        draft["decisions"][0]["reason_text"] = 123
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "verbatim strings"):
            ledger.seal_decision_batch(draft, packet)
        draft = draft_for(packet)
        draft["authorization_text"] = ["not", "verbatim", "text"]
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "verbatim text"):
            ledger.seal_decision_batch(draft, packet)

    def test_batch_packet_binding_is_independent_of_receipt_projection(self) -> None:
        packet = packet_fixture()
        batch = ledger.seal_decision_batch(draft_for(packet), packet)
        batch["packet_hash"] = "8" * 64
        rehash_batch(batch)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "not bound to this packet"):
            ledger.validate_decision_batch(batch, packet)

    def test_machine_rejection_cannot_be_rewritten_even_with_new_hashes(self) -> None:
        packet = packet_fixture()
        batch = ledger.seal_decision_batch(draft_for(packet), packet)
        row = next(row for row in batch["decisions"] if row["ts_code"] == "600005.SH")
        row.update({
            "decision": "DEFER",
            "decision_origin": ledger.HUMAN_ORIGIN,
            "reason_codes": ["OVERRIDE_MACHINE_GATE"],
            "reason_text": "Attempted override of a frozen machine rejection.",
            "research_question": "",
        })
        batch["rejected_count"] -= 1
        batch["deferred_count"] += 1
        rehash_batch(batch)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "machine-gate rejection"):
            ledger.validate_decision_batch(batch, packet)

    def test_batch_counts_hashes_and_no_authority_are_recomputed(self) -> None:
        packet = packet_fixture()
        pristine = ledger.seal_decision_batch(draft_for(packet), packet)
        mutations = (
            ("selected_count", 4, "counts"),
            ("claim_allowed", True, "authority or a method claim"),
            ("method_sample_eligible", True, "authority or a method claim"),
            ("projected_receipt_hash", "0" * 64, "receipt hash"),
            ("decision_set_hash", "0" * 64, "decision_set_hash"),
        )
        for field, value, marker in mutations:
            batch = copy.deepcopy(pristine)
            batch[field] = value
            batch["batch_hash"] = funnel._hash({
                key: item for key, item in batch.items() if key != "batch_hash"
            })
            with self.subTest(field=field):
                with self.assertRaisesRegex(ledger.DecisionLedgerError, marker):
                    ledger.validate_decision_batch(batch, packet)

    def test_append_is_idempotent_but_same_packet_rewrite_is_refused(self) -> None:
        packet = packet_fixture()
        batch = ledger.seal_decision_batch(draft_for(packet), packet)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "u4_decisions.jsonl"
            first = ledger.append_decision_batch(
                packet=packet, batch=batch, ledger_path=path,
                now="2026-08-22T00:16:00",
            )
            retry = ledger.append_decision_batch(
                packet=packet, batch=batch, ledger_path=path,
                now="2026-08-22T00:17:00",
            )
            no_trade = ledger.seal_decision_batch(draft_for(packet, {
                "600001.SH": "REJECT",
                "600002.SH": "REJECT",
                "600003.SH": "DEFER",
                "600004.SH": "DEFER",
            }), packet)
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "different content"):
                ledger.append_decision_batch(
                    packet=packet, batch=no_trade, ledger_path=path,
                    now="2026-08-22T00:18:00",
                )
            verified = ledger.verify_decision_ledger(path)
        self.assertEqual(first["status"], "APPENDED")
        self.assertEqual(retry["status"], "IDEMPOTENT")
        self.assertEqual(first["event"], retry["event"])
        self.assertEqual(verified, {"ok": True, "n": 1, "errors": []})

    def test_concurrent_exact_retry_converges_and_conflicting_batch_has_one_winner(self) -> None:
        packet = packet_fixture()
        selected = ledger.seal_decision_batch(draft_for(packet), packet)
        no_trade = ledger.seal_decision_batch(draft_for(packet, {
            "600001.SH": "REJECT",
            "600002.SH": "REJECT",
            "600003.SH": "DEFER",
            "600004.SH": "DEFER",
        }), packet)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "same.jsonl"

            def append_same(index: int) -> str:
                return ledger.append_decision_batch(
                    packet=packet,
                    batch=selected,
                    ledger_path=path,
                    now=f"2026-08-22T00:16:{index:02d}",
                )["status"]

            with ThreadPoolExecutor(max_workers=8) as pool:
                statuses = list(pool.map(append_same, range(8)))
            self.assertEqual(statuses.count("APPENDED"), 1)
            self.assertEqual(statuses.count("IDEMPOTENT"), 7)
            self.assertEqual(ledger.verify_decision_ledger(path)["n"], 1)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conflict.jsonl"

            def append_conflict(batch: dict) -> str:
                try:
                    return ledger.append_decision_batch(
                        packet=packet,
                        batch=batch,
                        ledger_path=path,
                        now="2026-08-22T00:17:00",
                    )["status"]
                except ledger.DecisionLedgerError:
                    return "REFUSED"

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(append_conflict, (selected, no_trade)))
            self.assertEqual(sorted(outcomes), ["APPENDED", "REFUSED"])
            self.assertEqual(ledger.verify_decision_ledger(path), {"ok": True, "n": 1, "errors": []})

    def test_u4_decision_event_kind_is_unique_in_shared_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            event_ledger.append(
                ledger.EVENT_KIND, "packet-1", {"value": 1}, path=str(path),
                now="2026-08-22T00:16:00",
            )
            with self.assertRaisesRegex(ValueError, "拒绝重复登记"):
                event_ledger.append(
                    ledger.EVENT_KIND, "packet-1", {"value": 1}, path=str(path),
                    now="2026-08-22T00:17:00",
                )

    def test_dedicated_verifier_rejects_foreign_kind_and_tampering(self) -> None:
        packet = packet_fixture()
        batch = ledger.seal_decision_batch(draft_for(packet), packet)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "u4_decisions.jsonl"
            event_ledger.append(
                "foreign_event", packet["packet_hash"],
                {"packet": packet, "batch": batch}, path=str(path),
                now="2026-08-22T00:16:00",
            )
            self.assertFalse(ledger.verify_decision_ledger(path)["ok"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "u4_decisions.jsonl"
            ledger.append_decision_batch(
                packet=packet, batch=batch, ledger_path=path,
                now="2026-08-22T00:16:00",
            )
            event = json.loads(path.read_text(encoding="utf-8"))
            event["payload"]["batch"]["selected_count"] = 99
            path.write_text(event_ledger.canonical(event) + "\n", encoding="utf-8")
            self.assertFalse(ledger.verify_decision_ledger(path)["ok"])

    def test_dedicated_verifier_binds_event_id_to_packet_hash(self) -> None:
        packet = packet_fixture()
        batch = ledger.seal_decision_batch(draft_for(packet), packet)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "u4_decisions.jsonl"
            event_ledger.append(
                ledger.EVENT_KIND,
                "wrong-packet-id",
                {"packet": packet, "batch": batch},
                path=str(path),
                now="2026-08-22T00:16:00",
            )
            result = ledger.verify_decision_ledger(path)
        self.assertFalse(result["ok"])
        self.assertIn("unique packet hash", result["errors"][0])

    def test_ledger_timestamp_is_the_registration_chronology_boundary(self) -> None:
        packet = packet_fixture()
        batch = ledger.seal_decision_batch(draft_for(packet), packet)
        too_early = "2026-08-22T00:14:59"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "u4_decisions.jsonl"
            event_ledger.append(
                ledger.EVENT_KIND,
                packet["packet_hash"],
                {"packet": packet, "batch": batch},
                path=str(path),
                now=too_early,
            )
            result = ledger.verify_decision_ledger(path)
        self.assertFalse(result["ok"])
        self.assertIn("registration cannot predate", result["errors"][0])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "u4_decisions.jsonl"
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "registration cannot predate"):
                ledger.append_decision_batch(
                    packet=packet, batch=batch, ledger_path=path, now=too_early,
                )
            self.assertFalse(path.exists())

    def test_append_refuses_an_existing_foreign_ledger_before_writing(self) -> None:
        packet = packet_fixture()
        batch = ledger.seal_decision_batch(draft_for(packet), packet)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "u4_decisions.jsonl"
            event_ledger.append(
                "foreign_event", "x", {"value": 1}, path=str(path),
                now="2026-08-22T00:16:00",
            )
            before = path.read_bytes()
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "existing decision ledger is invalid"):
                ledger.append_decision_batch(
                    packet=packet, batch=batch, ledger_path=path,
                    now="2026-08-22T00:17:00",
                )
            self.assertEqual(path.read_bytes(), before)

    def test_cli_duplicate_json_keys_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.json"
            path.write_text('{"decisions": [], "decisions": []}\n', encoding="utf-8")
            with self.assertRaisesRegex(ledger.DecisionLedgerError, "duplicate JSON key"):
                ledger._load_json(path)

    def test_cli_appends_idempotently_and_projects_the_existing_receipt(self) -> None:
        packet = packet_fixture()
        draft = draft_for(packet)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_path = root / "packet.json"
            draft_path = root / "draft.json"
            ledger_path = root / "u4_decisions.jsonl"
            receipt_path = root / "receipt.json"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            draft_path.write_text(json.dumps(draft), encoding="utf-8")
            argv = [
                "--packet", str(packet_path),
                "--draft", str(draft_path),
                "--ledger", str(ledger_path),
                "--receipt", str(receipt_path),
            ]
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(ledger.main(argv), 0)
                self.assertEqual(ledger.main(argv), 0)
            lines = [json.loads(line) for line in output.getvalue().splitlines()]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            verified = ledger.verify_decision_ledger(ledger_path)
        self.assertEqual([line["status"] for line in lines], ["APPENDED", "IDEMPOTENT"])
        closure.validate_review_receipt(receipt, packet)
        self.assertEqual(verified, {"ok": True, "n": 1, "errors": []})


if __name__ == "__main__":
    unittest.main(verbosity=2)
