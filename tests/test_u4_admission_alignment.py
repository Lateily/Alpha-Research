#!/usr/bin/env python3
"""Versioned U4 admission, source replay, and writer downgrade regressions."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "experiments/research_funnel")]

from experiments.research_funnel import closure_experiment as closure
from experiments.research_funnel import u4_decision_ledger as ledger
import test_u4_decision_ledger as ledger_fixture
import test_u4_pre_decision_runtime as fixture


def reseal(packet: dict) -> None:
    packet["source_refs"]["ready_pool_hash"] = closure.funnel._hash(packet["ready_pool"])
    packet["packet_hash"] = closure.funnel._hash({
        key: value for key, value in packet.items() if key != "packet_hash"
    })


class U4AdmissionAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle, self.feature_health, self.funnel_health = fixture._fixture_tree(Path(self.tmp.name))
        self.evidence = closure.load_bundle(self.bundle)
        self.candidates = {row["ts_code"]: row for row in self.evidence["candidates"]["rows"]}

    def packet(self, version: str | None = None) -> dict:
        kwargs = {} if version is None else {"packet_version": version}
        return closure.build_review_packet(
            bundle_dir=self.bundle, battery=None, generated_at=fixture.GENERATED_AT, **kwargs,
        )

    def test_new_packets_have_an_explicit_admission_version(self) -> None:
        self.assertEqual(self.packet()["schema_version"], "1.2")

    def test_random_control_remains_visible_but_is_not_selectable(self) -> None:
        rows = [row for row in self.packet()["ready_pool"] if row["candidate_status"] == "RANDOM_CONTROL"]
        self.assertTrue(rows)
        for row in rows:
            self.assertFalse(row["ready"])
            self.assertIn("RANDOM_CONTROL_NOT_SELECTABLE", row["blocked_reasons"])

    def test_no_positive_channel_is_explicitly_blocked(self) -> None:
        rows = [row for row in self.packet()["ready_pool"] if not self.candidates[row["ts_code"]]["source_channels"]]
        self.assertTrue(rows)
        for row in rows:
            self.assertFalse(row["ready"])
            self.assertIn("NO_POSITIVE_CHANNEL", row["blocked_reasons"])

    def test_pre_decision_and_review_admission_agree(self) -> None:
        review = {row["ts_code"]: row for row in self.packet()["ready_pool"]}
        rows = fixture.pre._candidate_rows(
            self.evidence, "TECH", "SEMICONDUCTOR_WORKFLOW_DEBUG_V1", {},
        )
        self.assertTrue(rows)
        self.assertEqual([], [row["ts_code"] for row in rows if row["allowed_for_u4_packet"] != review[row["ts_code"]]["ready"]])

    def test_legacy_v11_still_rebuilds_with_original_admission(self) -> None:
        packet = self.packet("1.1")
        controls = [row for row in packet["ready_pool"] if row["candidate_status"] == "RANDOM_CONTROL"]
        self.assertTrue(any(row["ready"] for row in controls))
        try:
            ledger._validate_packet_source(packet, self.bundle)
        except ledger.DecisionLedgerError as exc:
            self.fail(f"historical source replay changed: {exc}")

    def test_resealed_control_whitewash_is_rejected_from_source(self) -> None:
        packet = self.packet()
        row = next(row for row in packet["ready_pool"] if row["candidate_status"] == "RANDOM_CONTROL")
        row.update(ready=True, blocked_reasons=[])
        reseal(packet)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "deterministic projection"):
            ledger._validate_packet_source(packet, self.bundle)

    def test_new_draft_cannot_select_a_nonready_candidate(self) -> None:
        packet = ledger_fixture.packet_fixture()
        row = next(row for row in packet["ready_pool"] if row["ts_code"] == ledger_fixture.SELECT_CODES[0])
        row.update(ready=False, blocked_reasons=["NO_POSITIVE_CHANNEL"])
        reseal(packet)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "non-ready candidate cannot be SELECT"):
            ledger._validate_draft(packet, ledger_fixture.draft_for(packet))

    def test_persisted_intent_cannot_select_a_nonready_candidate(self) -> None:
        packet = ledger_fixture.packet_fixture()
        row = next(row for row in packet["ready_pool"] if row["ts_code"] == ledger_fixture.SELECT_CODES[0])
        row.update(ready=False, blocked_reasons=["NO_POSITIVE_CHANNEL"])
        reseal(packet)
        draft = ledger_fixture.draft_for(packet)
        item = ledger._intent_from_draft(packet, draft, draft["decisions"][0], row)
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "non-ready candidate cannot be SELECT"):
            ledger._validate_candidate_intent(
                item, packet, row, revision=1, method_version=draft["method_version"],
                ledger_id=ledger._ledger_id(packet),
            )

    def test_new_legacy_packet_intent_is_refused_by_typed_writer(self) -> None:
        packet = closure.build_review_packet(
            bundle_dir=ledger_fixture.SOURCE_BUNDLE, battery=None,
            generated_at=ledger_fixture.GENERATED_AT, packet_version="1.1",
        )
        path = Path(self.tmp.name) / "ledger.jsonl"
        with self.assertRaisesRegex(ledger.DecisionLedgerError, "new U4 intent requires review packet v1.2"):
            ledger_fixture.append_batch(packet=packet, draft=ledger_fixture.draft_for(packet), ledger_path=path)
        self.assertFalse(path.exists() and path.read_text().strip())

    def test_legacy_intent_can_resume_and_retry_without_rewriting_history(self) -> None:
        packet = closure.build_review_packet(
            bundle_dir=ledger_fixture.SOURCE_BUNDLE, battery=None,
            generated_at=ledger_fixture.GENERATED_AT, packet_version="1.1",
        )
        draft = ledger_fixture.draft_for(packet)
        rows, decisions = ledger._validate_draft(packet, draft)
        intent = ledger._build_packet_intent(packet, draft, decisions, rows)
        path = Path(self.tmp.name) / "legacy.jsonl"
        # Seed the historical crash-after-intent state; only this fixture uses
        # the low-level writer. Resume/retry below use the unchanged public API.
        event_ledger = ledger_fixture.event_ledger
        state, lines = event_ledger._append_preflight(str(path))
        event_ledger._append_verified(
            ledger.INTENT_KIND, intent["intent_id"], intent, str(path),
            ledger_fixture.REGISTERED_AT, state, lines,
        )
        original = path.read_bytes()
        try:
            ledger_fixture.append_batch(packet=packet, draft=draft, ledger_path=path)
            self.assertTrue(path.read_bytes().startswith(original))
            committed = path.read_bytes()
            ledger_fixture.append_batch(packet=packet, draft=draft, ledger_path=path)
            verified = ledger.verify_decision_ledger(path)
        except ledger.DecisionLedgerError as exc:
            self.fail(f"historical intent resume/retry was broken: {exc}")
        self.assertEqual(path.read_bytes(), committed)
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["intents"], 1)
        self.assertEqual(verified["closures"], 1)

    def test_v11_closure_receipt_and_replay_remain_valid(self) -> None:
        import test_research_closure_experiment as replay_fixture
        packet = self.packet("1.1")
        codes = [row["ts_code"] for row in packet["ready_pool"] if row["ready"]][:3]
        receipt = replay_fixture.receipt_for(packet, codes)
        try:
            queue, report = closure.run_offline_replay(
                bundle_dir=self.bundle, battery=self.evidence["battery"], packet=packet, receipt=receipt,
                generated_at="2026-08-13T10:06:00+00:00",
            )
        except closure.ClosureError as exc:
            self.fail(f"v1.1 closure replay changed: {exc}")
        self.assertEqual(len(queue["rows"]), 3)
        self.assertFalse(report["claim_allowed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
