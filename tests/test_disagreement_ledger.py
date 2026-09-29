#!/usr/bin/env python3
"""Offline tests for the disagreement adjudication ledger (contract A, v0.1)."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))

from experiments.execution_tracker import event_ledger  # noqa: E402
from experiments.research_funnel import disagreement_ledger as dl  # noqa: E402
from experiments.research_funnel import funnel_pipeline as funnel  # noqa: E402


AS_OF = "20260929"
RUN_ID = "FIXTURE_RUN_20260929_disagreement"
QUEUE_GENERATED_AT = "2026-09-29T19:40:58+00:00"
DECIDED_AT = "2026-09-30T10:00:00+08:00"
REGISTERED_AT = "2026-09-30T10:05:00"
EVIDENCE_REF = "conversation:2026-09-30-adjudication-fixture"

U3_CODES = ("000001.SZ", "000002.SZ", "600000.SH")
UNROUTED_CODE = "600001.SH"
CONTROL_CODES = ("300001.SZ", "688001.SH")


def _sha(value) -> str:
    return "sha256:" + funnel._hash(value)


def queue_row(
    code: str, klass: str = "U3_RED_FLAG_VS_E1_CLEAR", *, as_of: str = AS_OF,
    routed: bool = True, rank: int = 1,
) -> dict:
    u3 = klass == "U3_RED_FLAG_VS_E1_CLEAR"
    return {
        "row_id": dl.queue_row_id(as_of, code, klass),
        "ts_code": code,
        "display_name": f"FIXTURE {code}",
        "disagreement_class": klass,
        "evidence_staleness": "SUPERSEDED_PER_E1_LAYER" if u3 else "ACTIVE_PER_E1_LAYER",
        "reason_staleness": [{
            "reason_verbatim": "最新预告: 首亏",
            "kind": "forecast",
            "e1_coverage_value": "SUPERSEDED_BY_FILED_INCOME" if u3 else "ACTIVE",
            "staleness": "SUPERSEDED_PER_E1_LAYER" if u3 else "ACTIVE_PER_E1_LAYER",
        }],
        "machine_side": {
            "surface": "U3_RED_FLAG_GATE" if u3 else "E1_LAYER",
            "verdict": "RED_FLAG",
            "reasons_verbatim": ["最新预告: 首亏"],
            "latest_e1_date": "20260830",
        },
        "counter_side": {
            "surface": "E1_LAYER" if u3 else "U3_RED_FLAG_GATE",
            "verdict": "NO_RED_FLAG_FOUND" if u3 else "NOT_DISPATCHED",
            "reason_codes": [],
            "evidence_coverage": {"forecast": "SUPERSEDED", "express": "ABSENT", "income": "FILED"} if u3 else None,
        },
        "bindings": {
            "u3_battery_row_hash": _sha({"battery": code}) if u3 else None,
            "e1_row_hash": _sha({"e1": code}),
        },
        "routing": {"queue": "HUMAN_ADJUDICATION" if routed else "OBSERVED_NOT_ROUTED", "rank": rank},
        "adjudication_status": "PENDING",
    }


def make_queue(rows: list[dict] | None = None, *, as_of: str = AS_OF, run_id: str = RUN_ID,
               generated_at: str = QUEUE_GENERATED_AT) -> dict:
    if rows is None:
        rows = [queue_row(code, rank=index + 1) for index, code in enumerate(U3_CODES)]
        rows.append(queue_row(UNROUTED_CODE, routed=False, rank=99))
        rows.extend(
            queue_row(code, "E1_RED_FLAG_CONTROL_SAMPLE", rank=10 + index)
            for index, code in enumerate(CONTROL_CODES)
        )
    human = sum(row["routing"]["queue"] == "HUMAN_ADJUDICATION" for row in rows)
    return {
        "schema": dl.QUEUE_SCHEMA,
        "schema_version": dl.QUEUE_VERSION,
        "as_of": as_of,
        "run_id": run_id,
        "generated_at": generated_at,
        "source_bindings": {
            "candidate_manifest_hash": "a" * 64,
            "battery_rows_hash": "b" * 64,
            "e1_layer_rows_hash": "c" * 64,
            "e1_layer_as_of": as_of,
            "e1_basis": "SAME_AS_OF",
        },
        "policy": {
            "human_cap": 10, "control_per_night": 2, "staleness_rule_version": "v0.1",
            "ordering": "CLASS_THEN_STALENESS_THEN_HASH/v0.1",
        },
        "counts": {
            "battery_dispatched_rows": len(rows), "u3_red_flag_rows": len(rows),
            "u3_red_flag_vs_e1_clear_rows": len(rows), "superseded_rows": len(rows),
            "out_of_e1_window_rows": 0, "active_rows": 0, "e1_coverage_empty_rows": 0,
            "undetermined_rows": 0, "control_rows": 2, "human_routed_rows": human,
            "unobservable_cells": ["U3_PASS_VS_E1_RED_FLAG"],
        },
        "rows": rows,
        "rows_hash": funnel._hash(rows),
        "authority": dict(dl.QUEUE_AUTHORITY),
        "disclaimer": dl.DISCLAIMER,
    }


def write_bundle(root: Path, queue: dict, *, name: str = "bundle") -> Path:
    bundle = root / name
    bundle.mkdir(parents=True)
    queue_path = bundle / dl.QUEUE_FILE
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                          encoding="utf-8")
    stage = {
        "schema": "ar.research_funnel_stage",
        "schema_version": "1.0",
        "rule_version": "research_funnel_v1",
        "stage": "finalize",
        "as_of": queue["as_of"],
        "run_id": queue["run_id"],
        "generated_at": queue["generated_at"],
        "binds": {"candidate_manifest_hash": "a" * 64, "battery_rows_hash": "b" * 64},
        "artifacts": {
            "deep_research_queue.json": "d" * 64,
            dl.QUEUE_FILE: hashlib.sha256(queue_path.read_bytes()).hexdigest(),
        },
    }
    stage["stage_hash"] = funnel._hash(stage)
    (bundle / dl.FINALIZE_STAGE_FILE).write_text(json.dumps(stage, sort_keys=True, indent=2) + "\n",
                                                 encoding="utf-8")
    return bundle


def fill(draft: dict, *, verdicts: dict | None = None, reviewer: str = "Junyan",
         decided_at: str = DECIDED_AT, authorization: str | None = None,
         evidence_basis: str = "QUEUE_ROW_SNAPSHOT_ONLY") -> dict:
    batch = copy.deepcopy(draft)
    verdicts = verdicts or {}
    for row in batch["rows"]:
        row["human_verdict"] = verdicts.get(row["ts_code"], "MACHINE_VERDICT_REJECTED_STALE_EVIDENCE")
        row["reason_note"] = f"{row['ts_code']}: E1 层显示预告已被正式财报取代。"
        row["evidence_basis"] = evidence_basis
    batch["human_decision"] = {
        "claimed_reviewer": reviewer,
        "identity_verification": "UNAVAILABLE",
        "decided_at": decided_at,
        "authorization_text": authorization or (
            f"批准离线裁决批次 {batch['batch_hash'][:12]}，仅作证据，不改机器判决、不授予 U4 准入。"
        ),
        "authorization_evidence_ref": EVIDENCE_REF,
    }
    return batch


def record(bundle: Path, batch: dict, ledger: Path, *, now: str = REGISTERED_AT, **kwargs) -> dict:
    with patch.object(event_ledger, "_runtime_timestamp", return_value=now):
        return dl.record_batch(bundle_dir=bundle, batch=batch, ledger_path=ledger, **kwargs)


def outer_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def rewrite_chain(path: Path, records: list[dict]) -> None:
    prev = event_ledger.GENESIS_PREV
    lines = []
    for index, rec in enumerate(records):
        rec = {key: rec[key] for key in event_ledger.HASHED_FIELDS}
        rec["seq"] = index
        rec["prev"] = prev
        rec["hash"] = event_ledger.record_hash(rec)
        prev = rec["hash"]
        lines.append(event_ledger.canonical(rec))
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    event_ledger.write_anchor(str(path), len(records), prev)


def reintent(intent: dict) -> dict:
    intent = copy.deepcopy(intent)
    intent["intent_hash"] = dl._intent_hash(intent)
    return intent


class DisagreementLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.queue = make_queue()
        self.bundle = write_bundle(self.root, self.queue)
        self.ledger = self.root / "adjudications" / "adjudication_events.jsonl"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def draft(self, **kwargs) -> dict:
        return dl.build_draft(dl.load_bundle_queue(self.bundle), **kwargs)

    # ─── draft ───
    def test_draft_routes_only_human_rows_and_never_prefills_human_fields(self) -> None:
        draft = self.draft()
        codes = [row["ts_code"] for row in draft["rows"]]
        self.assertEqual(codes, list(U3_CODES) + list(CONTROL_CODES))
        self.assertNotIn(UNROUTED_CODE, codes)
        for row in draft["rows"]:
            self.assertIsNone(row["human_verdict"])
            self.assertIsNone(row["reason_note"])
            self.assertIsNone(row["evidence_basis"])
        self.assertIsNone(draft["human_decision"]["claimed_reviewer"])
        self.assertIsNone(draft["human_decision"]["authorization_text"])
        self.assertEqual(draft["batch_hash"], dl.batch_hash_for([row["row_id"] for row in draft["rows"]]))
        with self.assertRaises(dl.AdjudicationLedgerError):
            record(self.bundle, draft, self.ledger)
        self.assertFalse(self.ledger.exists())

    def test_reviewer_roster_is_a_single_charter_bound_constant(self) -> None:
        self.assertEqual(dl.CLAIMED_REVIEWERS, ("Junyan",))

    # ─── record / verify / report ───
    def test_batch_is_persisted_as_intent_rows_and_closure(self) -> None:
        batch = fill(self.draft(), verdicts={CONTROL_CODES[0]: "MACHINE_VERDICT_CONFIRMED"})
        result = record(self.bundle, batch, self.ledger)
        self.assertEqual(result["status"], "APPENDED")
        self.assertEqual(result["rows_appended"], 5)
        kinds = [rec["kind"] for rec in outer_records(self.ledger)]
        self.assertEqual(kinds, [dl.INTENT_KIND] + [dl.EVENT_KIND] * 5 + [dl.CLOSURE_KIND])
        events = [rec["payload"] for rec in outer_records(self.ledger) if rec["kind"] == dl.EVENT_KIND]
        for event in events:
            self.assertEqual(event["information_cutoff"], AS_OF)
            self.assertEqual(event["authority"], {
                "u4_admission_authority": False, "changes_machine_verdict": False,
                "claim_allowed": False, "no_trade_flag": True,
            })
            self.assertEqual(event["human_decision"]["identity_verification"], "UNAVAILABLE")
            self.assertEqual(event["registered_at"], "2026-09-30T10:05:00+08:00")
        verified = dl.verify_ledger(self.ledger, bundle_dir=self.bundle)
        self.assertTrue(verified["ok"], verified)
        self.assertEqual(verified["adjudications"], 5)
        self.assertEqual(verified["queue_binding"], {"checked": True, "bound_batches": 1, "run_id": RUN_ID})

    def test_report_is_descriptive_and_withholds_rates_below_minimum_sample(self) -> None:
        batch = fill(self.draft(), verdicts={
            U3_CODES[1]: "MACHINE_VERDICT_CONFIRMED",
            U3_CODES[2]: "UNDETERMINED_NEEDS_DATA",
            CONTROL_CODES[0]: "COUNTER_SIDE_REJECTED",
        })
        record(self.bundle, batch, self.ledger)
        report = dl.build_report(self.ledger)
        self.assertEqual(report["claim_status"], "INSUFFICIENT_INDEPENDENT_SAMPLE")
        self.assertIsNone(report["independent_clusters"])
        self.assertEqual(report["unobservable_cells"], ["U3_PASS_VS_E1_RED_FLAG"])
        share = report["false_kill_share"]
        self.assertEqual((share["numerator"], share["denominator"], share["n"]), (1, 2, 2))
        self.assertIsNone(share["rate"])
        self.assertEqual(share["level"], "RATE_WITHHELD_N_BELOW_MIN")
        self.assertEqual(report["per_class"]["U3_RED_FLAG_VS_E1_CLEAR"]["undetermined_rows"], 1)
        cells = {(c["disagreement_class"], c["human_verdict"]): c["rows"] for c in report["confusion_table"]}
        self.assertEqual(cells[("U3_RED_FLAG_VS_E1_CLEAR", "MACHINE_VERDICT_CONFIRMED")], 1)
        self.assertEqual(cells[("E1_RED_FLAG_CONTROL_SAMPLE", "COUNTER_SIDE_REJECTED")], 1)
        self.assertEqual(report["forced_agreement"]["status"], "U4_LEDGER_NOT_PROVIDED")
        self.assertIsNone(report["forced_agreement"]["forced_reject_red_flag_rows"])
        self.assertEqual(dl.forbidden_keys(report), [])
        self.assertFalse(report["authority"]["claim_allowed"])

    def test_rate_is_computed_only_at_or_above_minimum_sample(self) -> None:
        rows = [queue_row(f"{index:06d}.SZ", rank=index) for index in range(1, 22)]
        bundle = write_bundle(self.root, make_queue(rows), name="big")
        draft = dl.build_draft(dl.load_bundle_queue(bundle))
        verdicts = {row["ts_code"]: "MACHINE_VERDICT_CONFIRMED" for row in draft["rows"][:11]}
        record(bundle, fill(draft, verdicts=verdicts), self.ledger)
        share = dl.build_report(self.ledger)["false_kill_share"]
        self.assertEqual((share["numerator"], share["n"]), (10, 21))
        self.assertEqual(share["level"], "DESCRIPTIVE_ONLY")
        self.assertAlmostEqual(share["rate"], 10 / 21, places=6)

    def test_late_adjudications_are_counted_but_excluded_from_shares(self) -> None:
        late = "2026-10-09T10:00:00+08:00"
        batch = fill(self.draft(row_ids=[queue_row(U3_CODES[0])["row_id"]]), decided_at=late)
        record(self.bundle, batch, self.ledger, now="2026-10-09T10:05:00")
        report = dl.build_report(self.ledger)
        bucket = report["per_class"]["U3_RED_FLAG_VS_E1_CLEAR"]
        self.assertEqual(bucket["late_adjudication_rows"], 1)
        self.assertEqual(bucket["in_window_determined_rows"], 0)
        self.assertEqual(report["false_kill_share"]["numerator"], 0)
        self.assertEqual(report["adjudication_lag_days"]["max"], 10)

    def test_forced_agreement_is_counted_from_a_provided_u4_ledger(self) -> None:
        u4_path = self.root / "u4.jsonl"
        for index, (decision, codes) in enumerate((
            ("REJECT", ["RED_FLAG_ACTIVE"]), ("REJECT", ["HUMAN_JUDGMENT"]), ("SELECT", ["HUMAN_JUDGMENT"]),
        )):
            state, lines = event_ledger._append_preflight(str(u4_path))
            event_ledger._append_verified(
                "u4_decision", f"u4d_{index}", {"decision": decision, "reason_codes": codes},
                str(u4_path), REGISTERED_AT, state, lines,
            )
        record(self.bundle, fill(self.draft()), self.ledger)
        forced = dl.build_report(self.ledger, u4_ledger_path=u4_path)["forced_agreement"]
        self.assertEqual(forced["forced_reject_red_flag_rows"], 1)
        self.assertEqual(forced["status"], "COUNTED_FROM_U4_LEDGER")

    # ─── transaction semantics ───
    def test_exact_retry_is_idempotent_and_conflicting_content_is_refused(self) -> None:
        batch = fill(self.draft())
        record(self.bundle, batch, self.ledger)
        before = self.ledger.read_bytes()
        again = record(self.bundle, batch, self.ledger)
        self.assertEqual(again["status"], "IDEMPOTENT")
        self.assertEqual(self.ledger.read_bytes(), before)
        conflicting = copy.deepcopy(batch)
        conflicting["rows"][0]["human_verdict"] = "MACHINE_VERDICT_CONFIRMED"
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "committed with different content"):
            record(self.bundle, conflicting, self.ledger)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_interrupted_batch_resumes_and_blocks_other_batches(self) -> None:
        first_ids = [queue_row(code)["row_id"] for code in U3_CODES]
        batch = fill(self.draft(row_ids=first_ids))
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "injected interruption"):
            record(self.bundle, batch, self.ledger, _fail_after_rows=1)
        pending = dl.verify_ledger(self.ledger)
        self.assertTrue(pending["ok"], pending)
        self.assertEqual(len(pending["pending_batches"]), 1)
        self.assertEqual(dl.build_report(self.ledger)["adjudicated_rows"], 0)
        other = fill(self.draft(row_ids=[queue_row(code, "E1_RED_FLAG_CONTROL_SAMPLE")["row_id"]
                                         for code in CONTROL_CODES]))
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "still pending"):
            record(self.bundle, other, self.ledger)
        resumed = record(self.bundle, batch, self.ledger)
        self.assertEqual((resumed["intent_appended"], resumed["rows_appended"]), (False, 2))
        self.assertTrue(dl.verify_ledger(self.ledger)["ok"])
        record(self.bundle, other, self.ledger)
        self.assertEqual(dl.verify_ledger(self.ledger)["adjudications"], 5)

    def test_replay_refuses_a_second_open_batch(self) -> None:
        first = fill(self.draft(row_ids=[queue_row(U3_CODES[0])["row_id"]]))
        with self.assertRaises(dl.AdjudicationLedgerError):
            record(self.bundle, first, self.ledger, _fail_after_rows=1)
        # Forge a second intent directly behind the pending one (bypassing the writer's check).
        second = dl.build_intent(self.queue, fill(self.draft(row_ids=[queue_row(U3_CODES[1])["row_id"]])))
        records = outer_records(self.ledger)
        records.append({"seq": 0, "ts": REGISTERED_AT, "kind": dl.INTENT_KIND,
                        "id": second["batch_id"], "payload": second, "prev": ""})
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "still pending"):
            dl._replay_records(records)

    def test_a_row_cannot_be_adjudicated_twice_by_the_same_reviewer(self) -> None:
        row_id = queue_row(U3_CODES[0])["row_id"]
        record(self.bundle, fill(self.draft(row_ids=[row_id])), self.ledger)
        again = fill(self.draft(row_ids=[row_id]), decided_at="2026-09-30T11:00:00+08:00")
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "already adjudicated"):
            record(self.bundle, again, self.ledger, now="2026-09-30T11:05:00")
        claimed = dl.snapshot_state(self.ledger)["claimed_rows"]
        excluded = self.draft(exclude_row_ids=[r for r, _ in claimed])
        self.assertNotIn(row_id, [row["row_id"] for row in excluded["rows"]])

    # ─── queue binding ───
    def test_unrouted_unknown_or_altered_rows_are_refused(self) -> None:
        draft = self.draft()
        unrouted = queue_row(UNROUTED_CODE, routed=False, rank=99)
        batch = copy.deepcopy(draft)
        batch["rows"].append({
            "row_id": unrouted["row_id"], "ts_code": UNROUTED_CODE,
            "disagreement_class": unrouted["disagreement_class"],
            "queue_row_snapshot": unrouted, "human_verdict": None, "reason_note": None,
            "evidence_basis": None,
        })
        batch["batch_hash"] = dl.batch_hash_for([row["row_id"] for row in batch["rows"]])
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "only HUMAN_ADJUDICATION"):
            dl.build_intent(self.queue, fill(batch))
        altered = fill(draft)
        altered["rows"][0]["queue_row_snapshot"]["machine_side"]["verdict"] = "PASS"
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "snapshot differs"):
            dl.build_intent(self.queue, altered)
        foreign = fill(draft)
        foreign["rows"][0]["row_id"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "not in the disagreement queue"):
            dl.build_intent(self.queue, foreign)

    def test_batch_must_bind_the_exact_queue(self) -> None:
        batch = fill(self.draft())
        for key, bad in (("run_id", "OTHER_RUN"), ("queue_rows_hash", "sha256:" + "e" * 64),
                         ("as_of", "20260928"), ("queue_generated_at", "2026-09-29T19:40:59+00:00")):
            wrong = copy.deepcopy(batch)
            wrong[key] = bad
            with self.subTest(key=key):
                with self.assertRaisesRegex(dl.AdjudicationLedgerError, "not bound to this disagreement queue"):
                    dl.build_intent(self.queue, wrong)

    def test_queue_rows_hash_and_row_id_recompute(self) -> None:
        queue = copy.deepcopy(self.queue)
        queue["rows_hash"] = "f" * 64
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "rows_hash does not recompute"):
            dl.validate_queue(queue)
        queue = copy.deepcopy(self.queue)
        queue["rows"][0]["row_id"] = "sha256:" + "1" * 64
        queue["rows_hash"] = funnel._hash(queue["rows"])
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "row_id does not recompute"):
            dl.validate_queue(queue)
        prefixed = copy.deepcopy(self.queue)
        prefixed["rows_hash"] = "sha256:" + prefixed["rows_hash"]
        self.assertEqual(len(dl.validate_queue(prefixed)), 6)

    def test_queue_must_be_the_hashed_finalize_stage_artifact(self) -> None:
        queue_path = self.bundle / dl.QUEUE_FILE
        tampered = copy.deepcopy(self.queue)
        tampered["rows"] = tampered["rows"][:2]
        tampered["rows_hash"] = funnel._hash(tampered["rows"])
        queue_path.write_text(json.dumps(tampered, sort_keys=True), encoding="utf-8")
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "finalize-stage artifact"):
            dl.load_bundle_queue(self.bundle)

    def test_typed_append_rebinds_intent_to_the_bundle_queue(self) -> None:
        other_rows = [queue_row(code, rank=1) for code in U3_CODES[:1]]
        other_queue = make_queue(other_rows, run_id="FORGED_RUN")
        intent = dl.build_intent(other_queue, fill(dl.build_draft(other_queue)))
        with patch.object(event_ledger, "_runtime_timestamp", return_value=REGISTERED_AT):
            with self.assertRaisesRegex(dl.AdjudicationLedgerError, "not bound to this disagreement queue"):
                event_ledger.append_adjudication_stamped(
                    dl.INTENT_KIND, lambda _ts: (intent["batch_id"], intent),
                    bundle_dir=self.bundle, path=str(self.ledger),
                )
        self.assertFalse(self.ledger.exists())

    def test_verify_checks_queue_binding_when_bundle_is_available(self) -> None:
        record(self.bundle, fill(self.draft()), self.ledger)
        queue_path = self.bundle / dl.QUEUE_FILE
        tampered = copy.deepcopy(self.queue)
        tampered["rows"][0]["display_name"] = "RENAMED"
        tampered["rows_hash"] = funnel._hash(tampered["rows"])
        queue_path.write_text(json.dumps(tampered, sort_keys=True), encoding="utf-8")
        stage_path = self.bundle / dl.FINALIZE_STAGE_FILE
        stage = json.loads(stage_path.read_text())
        stage["artifacts"][dl.QUEUE_FILE] = hashlib.sha256(queue_path.read_bytes()).hexdigest()
        stage["stage_hash"] = funnel._hash({k: v for k, v in stage.items() if k != "stage_hash"})
        stage_path.write_text(json.dumps(stage, sort_keys=True), encoding="utf-8")
        self.assertTrue(dl.verify_ledger(self.ledger)["ok"])
        bound = dl.verify_ledger(self.ledger, bundle_dir=self.bundle)
        self.assertFalse(bound["ok"])
        self.assertIn("not bound to this disagreement queue", bound["errors"][0])

    # ─── human boundary ───
    def test_reviewer_and_identity_boundary(self) -> None:
        draft = self.draft()
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "reviewer/identity boundary"):
            dl.build_intent(self.queue, fill(draft, reviewer="Reed"))
        unverified = fill(draft)
        unverified["human_decision"]["identity_verification"] = "VERIFIED"
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "reviewer/identity boundary"):
            dl.build_intent(self.queue, unverified)
        bad_ref = fill(draft)
        bad_ref["human_decision"]["authorization_evidence_ref"] = "chat with ai"
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "externally anchored"):
            dl.build_intent(self.queue, bad_ref)

    def test_authorization_is_batch_bound_and_offline_scoped(self) -> None:
        draft = self.draft()
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "batch-bound and offline-scoped"):
            dl.build_intent(self.queue, fill(draft, authorization="批准离线裁决这一批分歧行，仅作为证据留档，不改变任何机器判决。"))
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "batch-bound and offline-scoped"):
            dl.build_intent(self.queue, fill(
                draft, authorization=f"approve adjudication batch {draft['batch_hash'][:12]} as evidence"))
        self.assertEqual(
            dl.build_intent(self.queue, fill(
                draft, authorization=f"Approve OFFLINE adjudication batch {draft['batch_hash'][:12]}.")
            )["row_count"], 5)
        tampered = fill(draft)
        tampered["batch_hash"] = "0" * 64
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "batch_hash does not recompute"):
            dl.build_intent(self.queue, tampered)

    def test_decision_cannot_predate_queue_and_registration_cannot_predate_decision(self) -> None:
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "cannot predate its disagreement queue"):
            dl.build_intent(self.queue, fill(self.draft(), decided_at="2026-09-30T03:40:57+08:00"))
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "registered before its human decision"):
            record(self.bundle, fill(self.draft()), self.ledger, now="2026-09-30T09:59:59")
        self.assertFalse(self.ledger.exists())

    def test_replay_refuses_intent_registered_before_decision(self) -> None:
        intent = dl.build_intent(self.queue, fill(self.draft()))
        records = [{"seq": 0, "ts": "2026-09-30T09:00:00", "kind": dl.INTENT_KIND,
                    "id": intent["batch_id"], "payload": intent, "prev": ""}]
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "registered before its human decision"):
            dl._replay_records(records)

    def test_information_cutoff_and_evidence_basis_are_closed(self) -> None:
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "evidence_basis is outside"):
            dl.build_intent(self.queue, fill(self.draft(), evidence_basis="EXTERNAL_FILINGS_AFTER_AS_OF"))
        intent = dl.build_intent(self.queue, fill(self.draft()))
        intent["row_intents"][0]["information_cutoff"] = "20261009"
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "information_cutoff must equal"):
            dl.validate_intent(reintent(intent))

    def test_authority_never_escalates(self) -> None:
        intent = dl.build_intent(self.queue, fill(self.draft()))
        for field, bad in (("changes_machine_verdict", True), ("u4_admission_authority", True),
                           ("claim_allowed", True), ("no_trade_flag", False)):
            tampered = copy.deepcopy(intent)
            tampered["row_intents"][0]["authority"][field] = bad
            with self.subTest(field=field):
                with self.assertRaisesRegex(dl.AdjudicationLedgerError, "acquired machine-verdict"):
                    dl.validate_intent(reintent(tampered))
        tampered = copy.deepcopy(intent)
        tampered["row_intents"][0]["human_verdict"] = "BUY"
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "human_verdict is outside"):
            dl.validate_intent(reintent(tampered))

    def test_intent_row_set_is_bound_by_batch_hash(self) -> None:
        intent = dl.build_intent(self.queue, fill(self.draft()))
        dropped = copy.deepcopy(intent)
        for key in ("row_ids", "queue_row_snapshots", "row_intents"):
            dropped[key] = dropped[key][1:]
        dropped["row_count"] = len(dropped["row_ids"])
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "does not bind its row set"):
            dl.validate_intent(reintent(dropped))
        rehashed = copy.deepcopy(intent)
        rehashed["row_intents"][0]["reason_note"] = "changed after hashing"
        with self.assertRaisesRegex(dl.AdjudicationLedgerError, "intent hash mismatch"):
            dl.validate_intent(rehashed)

    # ─── R-015 transport ───
    def test_adjudication_kinds_are_reserved_from_raw_and_generic_writers(self) -> None:
        path = self.root / "raw.jsonl"
        for kind in sorted(dl.TYPED_KINDS):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, "typed-only"):
                    event_ledger.append(kind, kind, {}, path=str(path), now=REGISTERED_AT)
                with self.assertRaisesRegex(ValueError, "typed-only"):
                    event_ledger.append_stamped(kind, lambda _ts: (kind, {}), path=str(path))
                with self.assertRaises(dl.AdjudicationLedgerError):
                    event_ledger.append_adjudication_stamped(
                        kind, lambda _ts: (kind, {}), bundle_dir=self.bundle, path=str(path),
                    )
        with self.assertRaisesRegex(ValueError, "not a disagreement-adjudication typed kind"):
            event_ledger.append_adjudication_stamped(
                "u4_decision", lambda _ts: ("x", {}), bundle_dir=self.bundle, path=str(path),
            )
        self.assertFalse(path.exists())

    def test_r015_adjudication_kind_uniqueness_is_independent(self) -> None:
        for kind in sorted(dl.TYPED_KINDS):
            path = str(self.root / f"{kind}.jsonl")
            state, lines = event_ledger._append_preflight(path)
            event_ledger._append_verified(kind, "same-id", {}, path, REGISTERED_AT, state, lines)
            state, lines = event_ledger._append_preflight(path)
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, "拒绝重复登记"):
                    event_ledger._append_verified(kind, "same-id", {}, path, REGISTERED_AT, state, lines)

    def test_verifier_detects_payload_tampering_even_when_chain_is_rehashed(self) -> None:
        record(self.bundle, fill(self.draft()), self.ledger)
        records = outer_records(self.ledger)
        records[1]["payload"]["human_verdict"] = "MACHINE_VERDICT_CONFIRMED"
        records[1]["payload"]["record_hash"] = dl._record_hash(records[1]["payload"])
        rewrite_chain(self.ledger, records)
        result = dl.verify_ledger(self.ledger)
        self.assertFalse(result["ok"])
        self.assertIn("differs from its frozen batch intent", result["errors"][0])

    def test_verifier_recomputes_record_hash(self) -> None:
        record(self.bundle, fill(self.draft()), self.ledger)
        records = outer_records(self.ledger)
        records[1]["payload"]["record_hash"] = "sha256:" + "0" * 64
        rewrite_chain(self.ledger, records)
        result = dl.verify_ledger(self.ledger)
        self.assertFalse(result["ok"])
        self.assertIn("record_hash mismatch", result["errors"][0])

    def test_closure_cannot_commit_an_incomplete_batch(self) -> None:
        record(self.bundle, fill(self.draft()), self.ledger)
        records = outer_records(self.ledger)
        records = records[:2] + records[-1:]
        rewrite_chain(self.ledger, records)
        result = dl.verify_ledger(self.ledger)
        self.assertFalse(result["ok"])
        self.assertIn("incomplete batch", result["errors"][0])

    def test_missing_ledger_is_not_a_clean_verification(self) -> None:
        result = dl.verify_ledger(self.root / "absent.jsonl")
        self.assertFalse(result["ok"])
        self.assertIn("does not exist", result["errors"][0])

    # ─── CLI ───
    def test_cli_draft_record_verify_report_round_trip(self) -> None:
        out = self.root / "draft.json"
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(dl.main(["draft", "--bundle-dir", str(self.bundle), "--out", str(out)]), 0)
            self.assertEqual(dl.main(["draft", "--bundle-dir", str(self.bundle), "--out", str(out)]), 1)
        batch_path = self.root / "batch.json"
        batch_path.write_text(json.dumps(fill(json.loads(out.read_text()))), encoding="utf-8")
        stdout = StringIO()
        with patch.object(event_ledger, "_runtime_timestamp", return_value=REGISTERED_AT):
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                self.assertEqual(dl.main(["record", "--bundle-dir", str(self.bundle),
                                          "--batch", str(batch_path), "--ledger", str(self.ledger)]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "APPENDED")
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(dl.main(["verify", "--ledger", str(self.ledger),
                                      "--bundle-dir", str(self.bundle)]), 0)
        self.assertTrue(json.loads(stdout.getvalue())["ok"])
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(dl.main(["report", "--ledger", str(self.ledger)]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["claim_status"], "INSUFFICIENT_INDEPENDENT_SAMPLE")
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(dl.main(["verify", "--ledger", str(self.root / "absent.jsonl")]), 1)
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                dl.main(["record", "--batch", str(batch_path), "--ledger", str(self.ledger)])

    def test_payload_contract_schema_matches_persisted_events(self) -> None:
        schema = json.loads((ROOT / "docs/research/contracts/disagreement_adjudication.v0_1.schema.json")
                            .read_text(encoding="utf-8"))
        record(self.bundle, fill(self.draft()), self.ledger)
        event = next(rec["payload"] for rec in outer_records(self.ledger) if rec["kind"] == dl.EVENT_KIND)
        self.assertEqual(set(schema["required"]), dl.EVENT_FIELDS)
        self.assertEqual(set(schema["properties"]), set(event))
        self.assertEqual(schema["properties"]["human_verdict"]["enum"], list(dl.HUMAN_VERDICTS))
        self.assertEqual(
            schema["properties"]["human_decision"]["properties"]["claimed_reviewer"]["enum"],
            list(dl.CLAIMED_REVIEWERS),
        )
        self.assertEqual(sorted(schema["properties"]["evidence_basis"]["enum"]), sorted(dl.EVIDENCE_BASES))


if __name__ == "__main__":
    unittest.main(verbosity=2)
