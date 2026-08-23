#!/usr/bin/env python3
"""Offline fixture replay for the U1/U2/U3/U4/U5 research closure."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))
sys.path.insert(0, str(ROOT / "tests"))

import closure_experiment as closure  # noqa: E402
import funnel_pipeline as funnel  # noqa: E402
import test_research_funnel_closure as fixtures  # noqa: E402


GENERATED_AT = "2026-08-13T10:00:00+00:00"


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_bundle(root: Path) -> tuple[Path, dict, list[str]]:
    registry, _, scan, candidates = fixtures.build_candidates(n=90)
    clean_codes = [
        row["ts_code"] for row in candidates["rows"]
        if "RED_FLAG" not in row["flags"] and row["review_status"] != "RANDOM_CONTROL"
    ][:8]
    battery = fixtures.battery_fixture(clean_codes)
    battery["run_id"] = "FIXTURE_RUN_20260813"
    for row in battery["data"]["results"]:
        row["dims"] = {name: {"fixture": True} for name in closure.BATTERY_DIMENSIONS}
        row["completeness"] = {
            "covered": 6, "of": 6, "missing": [], "verdict": "COMPLETE",
        }
    queue = funnel.build_deep_research_queue(
        candidate_review=candidates,
        battery=battery,
        selected_tickers=(),
        trade_date=fixtures.TRADE_DATE,
        generated_at=GENERATED_AT,
    )
    projected = funnel.advance_registry(
        registry=registry,
        scan=scan,
        candidate_review=candidates,
        battery=battery,
        deep_queue=queue,
        generated_at=GENERATED_AT,
    )
    bundle = root / "bundle"
    bundle.mkdir()
    payloads = {
        "all_market_scan.json": scan,
        "candidate_review.json": candidates,
        "deep_research_queue.json": queue,
        "security_registry_projected.json": projected,
    }
    for name, payload in payloads.items():
        write_json(bundle / name, payload)
    artifacts = {
        name: hashlib.sha256((bundle / name).read_bytes()).hexdigest()
        for name in sorted(payloads)
    }
    manifest = {
        "schema": "ar.research_funnel_bundle",
        "schema_version": funnel.SCHEMA_VERSION,
        "rule_version": funnel.RULE_VERSION,
        "as_of": fixtures.TRADE_DATE,
        "generated_at": GENERATED_AT,
        "artifacts": artifacts,
        "bundle_hash": funnel._hash(artifacts),
    }
    write_json(bundle / "manifest.json", manifest)
    return bundle, battery, clean_codes


def receipt_for(packet: dict, codes: list[str]) -> dict:
    receipt = {
        "schema": closure.RECEIPT_SCHEMA,
        "schema_version": closure.SCHEMA_VERSION,
        "receipt_class": closure.RECEIPT_CLASS,
        "decision": closure.RECEIPT_DECISION,
        "claimed_reviewer": "Junyan",
        "identity_verification": "UNAVAILABLE",
        "production_authority": False,
        "packet_hash": packet["packet_hash"],
        "reviewed_at": "2026-08-13T10:05:00+00:00",
        "authorization_text": (
            f"批准离线研究回放，绑定 packet_hash {packet['packet_hash'][:12]}，"
            "不产生生产权限。"
        ),
        "selections": [
            {
                "ts_code": code,
                "research_question": f"Which registered fact would invalidate {code}?",
                "selection_reason": "Synthetic fixture exercises the U4 evidence boundary.",
            }
            for code in codes
        ],
        "disclaimer": closure.DISCLAIMER,
    }
    receipt["receipt_hash"] = funnel._hash(receipt)
    return receipt


class ResearchClosureExperimentTests(unittest.TestCase):
    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp) / "duplicate.json"
            payload.write_text('{"claim_allowed": false, "claim_allowed": true}\n')
            with self.assertRaisesRegex(closure.ClosureError, "duplicate JSON key"):
                closure._load_object(payload)

    def test_bundle_hash_must_match_manifest_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, _ = build_bundle(Path(tmp))
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["bundle_hash"] = "0" * 64
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(closure.ClosureError, "bundle_hash mismatch"):
                closure.build_review_packet(
                    bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
                )

    def test_packet_hash_must_cover_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, _ = build_bundle(Path(tmp))
            packet = closure.build_review_packet(
                bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
            )
            packet["claim_allowed"] = True
            with self.assertRaisesRegex(closure.ClosureError, "packet hash mismatch"):
                closure.validate_review_packet(packet)

    def test_packet_projects_exact_run_and_candidate_evidence_from_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, _ = build_bundle(Path(tmp))
            try:
                packet = closure.build_review_packet(
                    bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
                )
            except closure.ClosureError as exc:
                self.fail(f"default v1.1 packet construction failed: {exc}")
            candidates = json.loads(
                (bundle / "candidate_review.json").read_text(encoding="utf-8")
            )
            registry = json.loads(
                (bundle / "security_registry_projected.json").read_text(encoding="utf-8")
            )
            candidate_by_code = {row["ts_code"]: row for row in candidates["rows"]}
            registry_by_code = {row["ts_code"]: row for row in registry["rows"]}
            battery_by_code = funnel._battery_rows(battery, packet["as_of"])
            row = packet["ready_pool"][0]
            code = row["ts_code"]
        self.assertEqual(packet["schema_version"], closure.PACKET_SCHEMA_VERSION)
        self.assertEqual(packet["source_refs"]["run_id"], battery["run_id"])
        self.assertEqual(row["display_name"], registry_by_code[code]["name"])
        self.assertEqual(row["cohort_id"], closure.COHORT_ID_UNAVAILABLE)
        self.assertNotEqual(row["cohort_id"], candidate_by_code[code]["industry_key"])
        self.assertEqual(
            row["causal_cluster_id"],
            str(candidate_by_code[code].get("cluster_id") or "UNAVAILABLE"),
        )
        self.assertEqual(row["u2_candidate_row_hash"], funnel._hash(candidate_by_code[code]))
        self.assertEqual(row["u3_battery_row_hash"], funnel._hash(battery_by_code[code]))

    def test_packet_does_not_fabricate_cohort_identity_from_industry_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, _ = build_bundle(Path(tmp))
            packet = closure.build_review_packet(
                bundle_dir=bundle,
                battery=battery,
                generated_at=GENERATED_AT,
            )
            candidates = json.loads(
                (bundle / "candidate_review.json").read_text(encoding="utf-8")
            )
            candidate_by_code = {row["ts_code"]: row for row in candidates["rows"]}
        self.assertTrue(packet["ready_pool"])
        self.assertTrue(
            all(
                row["cohort_id"] == closure.COHORT_ID_UNAVAILABLE
                and row["cohort_id"] != candidate_by_code[row["ts_code"]]["industry_key"]
                for row in packet["ready_pool"]
            )
        )

    def test_legacy_v1_packet_remains_valid_and_replayable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, codes = build_bundle(Path(tmp))
            try:
                packet = closure.build_review_packet(
                    bundle_dir=bundle,
                    battery=battery,
                    generated_at=GENERATED_AT,
                    packet_version=closure.LEGACY_PACKET_SCHEMA_VERSION,
                )
                receipt = receipt_for(packet, codes[:3])
                closure.validate_review_packet(packet)
                queue, report = closure.run_offline_replay(
                    bundle_dir=bundle,
                    battery=battery,
                    packet=packet,
                    receipt=receipt,
                    generated_at="2026-08-13T10:06:00+00:00",
                )
            except closure.ClosureError as exc:
                self.fail(f"legacy v1.0 packet compatibility regressed: {exc}")
        self.assertEqual(packet["schema_version"], "1.0")
        self.assertEqual(set(packet["source_refs"]), closure.LEGACY_PACKET_SOURCE_REF_FIELDS)
        self.assertTrue(
            all(set(row) == closure.LEGACY_PACKET_READY_ROW_FIELDS for row in packet["ready_pool"])
        )
        self.assertEqual(len(queue["rows"]), 3)
        self.assertEqual(report["u5_handoff"]["status"], "DATA_BLOCKED")

    def test_packet_refuses_a_battery_without_an_exact_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, _ = build_bundle(Path(tmp))
            battery.pop("run_id")
            with self.assertRaisesRegex(closure.ClosureError, "exact U3 run_id"):
                closure.build_review_packet(
                    bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
                )

    def test_u3_complete_stamp_requires_six_complete_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, _ = build_bundle(Path(tmp))
            del battery["data"]["results"][0]["dims"]["估值"]
            with self.assertRaisesRegex(closure.ClosureError, "without six complete dimensions"):
                closure.build_review_packet(
                    bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
                )

    def test_fixture_replay_binds_control_u4_and_blocks_u5(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, codes = build_bundle(Path(tmp))
            packet = closure.build_review_packet(
                bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
            )
            receipt = receipt_for(packet, codes[:3])
            queue, report = closure.run_offline_replay(
                bundle_dir=bundle,
                battery=battery,
                packet=packet,
                receipt=receipt,
                generated_at="2026-08-13T10:06:00+00:00",
            )
        self.assertEqual(len(queue["rows"]), 3)
        self.assertEqual(report["u1_u2_discovery"]["status"], "REPLAY_VERIFIED")
        self.assertEqual(report["u5_handoff"]["status"], "DATA_BLOCKED")
        self.assertFalse(report["claim_allowed"])
        self.assertFalse(report["u4_review"]["selection_identity_verified"])
        self.assertFalse(report["u4_review"]["production_authority"])

    def test_random_control_mutation_is_rejected_before_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, _ = build_bundle(Path(tmp))
            candidates_path = bundle / "candidate_review.json"
            candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
            candidates["control_sampling_frame"]["drawn"][0]["ts_code"] = "999999.SZ"
            candidates["rows_hash"] = funnel._hash(candidates["rows"])
            write_json(candidates_path, candidates)
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"][candidates_path.name] = hashlib.sha256(
                candidates_path.read_bytes()
            ).hexdigest()
            manifest["bundle_hash"] = funnel._hash(manifest["artifacts"])
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(closure.ClosureError, "random control rows differ"):
                closure.build_review_packet(
                    bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
                )

    def test_receipt_must_bind_exact_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, codes = build_bundle(Path(tmp))
            packet = closure.build_review_packet(
                bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
            )
            receipt = receipt_for(packet, codes[:3])
            receipt["packet_hash"] = "0" * 64
            receipt["receipt_hash"] = funnel._hash(
                closure._without_hash(receipt, "receipt_hash")
            )
            with self.assertRaisesRegex(closure.ClosureError, "not bound"):
                closure.validate_review_receipt(receipt, packet)

    def test_replay_rebuilds_packet_from_frozen_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, codes = build_bundle(Path(tmp))
            packet = closure.build_review_packet(
                bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
            )
            packet["ready_pool"] = packet["ready_pool"][1:]
            packet["source_refs"]["ready_pool_hash"] = funnel._hash(packet["ready_pool"])
            packet["packet_hash"] = funnel._hash(
                closure._without_hash(packet, "packet_hash")
            )
            receipt = receipt_for(packet, codes[1:4])
            with self.assertRaisesRegex(closure.ClosureError, "deterministic projection"):
                closure.run_offline_replay(
                    bundle_dir=bundle,
                    battery=battery,
                    packet=packet,
                    receipt=receipt,
                    generated_at="2026-08-13T10:06:00+00:00",
                )

    def test_receipt_cannot_claim_verified_identity_or_production_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, codes = build_bundle(Path(tmp))
            packet = closure.build_review_packet(
                bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
            )
            for field, value in (
                ("identity_verification", "VERIFIED"),
                ("production_authority", True),
            ):
                receipt = receipt_for(packet, codes[:3])
                receipt[field] = value
                receipt["receipt_hash"] = funnel._hash(
                    closure._without_hash(receipt, "receipt_hash")
                )
                with self.assertRaisesRegex(closure.ClosureError, "authority boundary"):
                    closure.validate_review_receipt(receipt, packet)

    def test_receipt_rejects_unready_selection_and_missing_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, codes = build_bundle(Path(tmp))
            packet = closure.build_review_packet(
                bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
            )
            receipt = receipt_for(packet, codes[:3])
            receipt["selections"][0]["ts_code"] = "999999.SZ"
            receipt["receipt_hash"] = funnel._hash(
                closure._without_hash(receipt, "receipt_hash")
            )
            with self.assertRaisesRegex(closure.ClosureError, "not backed"):
                closure.validate_review_receipt(receipt, packet)
            receipt = receipt_for(packet, codes[:3])
            receipt["selections"][0]["research_question"] = ""
            receipt["receipt_hash"] = funnel._hash(
                closure._without_hash(receipt, "receipt_hash")
            )
            with self.assertRaisesRegex(closure.ClosureError, "not backed"):
                closure.validate_review_receipt(receipt, packet)

    def test_report_rejects_claim_or_trade_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, codes = build_bundle(Path(tmp))
            packet = closure.build_review_packet(
                bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
            )
            receipt = receipt_for(packet, codes[:3])
            queue, report = closure.run_offline_replay(
                bundle_dir=bundle,
                battery=battery,
                packet=packet,
                receipt=receipt,
                generated_at="2026-08-13T10:06:00+00:00",
            )
            for key, value in (("claim_allowed", True), ("nested_trade_action", "BUY")):
                mutated = copy.deepcopy(report)
                if key == "nested_trade_action":
                    mutated["u4_review"]["trade_action"] = value
                else:
                    mutated[key] = value
                mutated["report_hash"] = funnel._hash(
                    closure._without_hash(mutated, "report_hash")
                )
                with self.assertRaisesRegex(closure.ClosureError, "claim or trading authority"):
                    closure.validate_closure_report(mutated, packet, receipt, queue)

    def test_report_hash_must_cover_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, codes = build_bundle(Path(tmp))
            packet = closure.build_review_packet(
                bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
            )
            receipt = receipt_for(packet, codes[:3])
            queue, report = closure.run_offline_replay(
                bundle_dir=bundle,
                battery=battery,
                packet=packet,
                receipt=receipt,
                generated_at="2026-08-13T10:06:00+00:00",
            )
            report["u5_handoff"]["status"] = "COMPLETE"
            with self.assertRaisesRegex(closure.ClosureError, "report hash mismatch"):
                closure.validate_closure_report(report, packet, receipt, queue)

    def test_report_rejects_rewritten_control_evidence_even_with_new_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, codes = build_bundle(Path(tmp))
            packet = closure.build_review_packet(
                bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
            )
            receipt = receipt_for(packet, codes[:3])
            queue, report = closure.run_offline_replay(
                bundle_dir=bundle,
                battery=battery,
                packet=packet,
                receipt=receipt,
                generated_at="2026-08-13T10:06:00+00:00",
            )
            report["u1_u2_discovery"]["seed_hex"] = "0" * 64
            report["report_hash"] = funnel._hash(
                closure._without_hash(report, "report_hash")
            )
            with self.assertRaisesRegex(closure.ClosureError, "evidence chain is broken"):
                closure.validate_closure_report(report, packet, receipt, queue)

    def test_replay_timestamp_cannot_predate_review_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, battery, codes = build_bundle(Path(tmp))
            packet = closure.build_review_packet(
                bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
            )
            receipt = receipt_for(packet, codes[:3])
            with self.assertRaisesRegex(closure.ClosureError, "cannot predate"):
                closure.run_offline_replay(
                    bundle_dir=bundle,
                    battery=battery,
                    packet=packet,
                    receipt=receipt,
                    generated_at="2026-08-13T09:00:00+00:00",
                )

    def test_result_bundle_is_self_contained_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, battery, codes = build_bundle(root)
            packet = closure.build_review_packet(
                bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
            )
            receipt = receipt_for(packet, codes[:3])
            queue, report = closure.run_offline_replay(
                bundle_dir=bundle,
                battery=battery,
                packet=packet,
                receipt=receipt,
                generated_at="2026-08-13T10:06:00+00:00",
            )
            output = root / "result"
            closure._write_replay_outputs(
                output, bundle, battery, packet, receipt, queue, report,
            )
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                set(manifest["artifacts"]),
                closure.RESULT_ARTIFACTS,
            )
            for name, digest in manifest["artifacts"].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), digest)
            self.assertEqual(manifest["bundle_hash"], funnel._hash(manifest["artifacts"]))
            self.assertFalse(manifest["production_authority"])
            self.assertFalse(manifest["claim_allowed"])
            verified = closure.verify_result_bundle(output)
            self.assertEqual(verified["status"], "VERIFIED")
            self.assertEqual(verified["u5_status"], "DATA_BLOCKED")
            with self.assertRaisesRegex(closure.ClosureError, "already exists"):
                closure._write_replay_outputs(
                    output, bundle, battery, packet, receipt, queue, report,
                )

    def test_result_bundle_freezes_and_verifies_the_complete_dag_source(self) -> None:
        import test_u4_decision_ledger as u4_fixtures

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "dag-bundle"
            shutil.copytree(u4_fixtures.SOURCE_BUNDLE, bundle)
            battery = copy.deepcopy(u4_fixtures.SOURCE_BATTERY)
            packet = closure.build_review_packet(
                bundle_dir=bundle,
                battery=None,
                generated_at=GENERATED_AT,
            )
            receipt = receipt_for(packet, list(u4_fixtures.SELECT_CODES))
            queue, report = closure.run_offline_replay(
                bundle_dir=bundle,
                battery=battery,
                packet=packet,
                receipt=receipt,
                generated_at="2026-08-13T10:06:00+00:00",
            )
            output = root / "result"
            try:
                closure._write_replay_outputs(
                    output, bundle, battery, packet, receipt, queue, report,
                )
            except (closure.ClosureError, OSError) as exc:
                self.fail(f"valid DAG source was not frozen as a replay bundle: {exc}")
            source_names = set(
                json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))["artifacts"]
            )
            result_manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            expected = closure._result_artifact_names(source_names)
            self.assertEqual(set(result_manifest["artifacts"]), expected)
            self.assertTrue({
                "frozen_funnel_bundle/candidate_manifest.json",
                "frozen_funnel_bundle/candidate_battery.json",
            }.issubset(expected))
            self.assertEqual(closure.verify_result_bundle(output)["status"], "VERIFIED")

    def test_result_bundle_verifier_rejects_artifact_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, battery, codes = build_bundle(root)
            packet = closure.build_review_packet(
                bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
            )
            receipt = receipt_for(packet, codes[:3])
            queue, report = closure.run_offline_replay(
                bundle_dir=bundle,
                battery=battery,
                packet=packet,
                receipt=receipt,
                generated_at="2026-08-13T10:06:00+00:00",
            )
            output = root / "result"
            closure._write_replay_outputs(
                output, bundle, battery, packet, receipt, queue, report,
            )
            report_path = output / "closure_report.json"
            report_path.write_text(
                report_path.read_text(encoding="utf-8") + " ", encoding="utf-8",
            )
            with self.assertRaisesRegex(closure.ClosureError, "artifact hash mismatch"):
                closure.verify_result_bundle(output)

    def test_result_bundle_verifier_rebuilds_outputs_from_frozen_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, battery, codes = build_bundle(root)
            packet = closure.build_review_packet(
                bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
            )
            receipt = receipt_for(packet, codes[:3])
            queue, report = closure.run_offline_replay(
                bundle_dir=bundle,
                battery=battery,
                packet=packet,
                receipt=receipt,
                generated_at="2026-08-13T10:06:00+00:00",
            )
            output = root / "result"
            closure._write_replay_outputs(
                output, bundle, battery, packet, receipt, queue, report,
            )
            report_path = output / "closure_report.json"
            rewritten = json.loads(report_path.read_text(encoding="utf-8"))
            rewritten["experiment_verdict"] = "SELF_CONSISTENT_REWRITE"
            rewritten["report_hash"] = funnel._hash(
                closure._without_hash(rewritten, "report_hash")
            )
            write_json(report_path, rewritten)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"][report_path.name] = hashlib.sha256(
                report_path.read_bytes()
            ).hexdigest()
            manifest["bundle_hash"] = funnel._hash(manifest["artifacts"])
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(closure.ClosureError, "deterministic projection"):
                closure.verify_result_bundle(output)

    def test_result_bundle_verifier_rejects_manifest_bundle_hash_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, battery, codes = build_bundle(root)
            packet = closure.build_review_packet(
                bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
            )
            receipt = receipt_for(packet, codes[:3])
            queue, report = closure.run_offline_replay(
                bundle_dir=bundle,
                battery=battery,
                packet=packet,
                receipt=receipt,
                generated_at="2026-08-13T10:06:00+00:00",
            )
            output = root / "result"
            closure._write_replay_outputs(
                output, bundle, battery, packet, receipt, queue, report,
            )
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["bundle_hash"] = "0" * 64
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(closure.ClosureError, "bundle_hash mismatch"):
                closure.verify_result_bundle(output)

    def test_result_bundle_manifest_rejects_extra_authority_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, battery, codes = build_bundle(root)
            packet = closure.build_review_packet(
                bundle_dir=bundle, battery=battery, generated_at=GENERATED_AT,
            )
            receipt = receipt_for(packet, codes[:3])
            queue, report = closure.run_offline_replay(
                bundle_dir=bundle,
                battery=battery,
                packet=packet,
                receipt=receipt,
                generated_at="2026-08-13T10:06:00+00:00",
            )
            output = root / "result"
            closure._write_replay_outputs(
                output, bundle, battery, packet, receipt, queue, report,
            )
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["trade_action"] = "BUY"
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(closure.ClosureError, "fields are not exact"):
                closure.verify_result_bundle(output)

    def test_cli_packet_receipt_replay_and_verify_are_one_closed_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, battery, codes = build_bundle(root)
            battery_path = root / "battery.json"
            packet_path = root / "packet.json"
            draft_path = root / "receipt-draft.json"
            receipt_path = root / "receipt.json"
            output = root / "result"
            write_json(battery_path, battery)
            script = ROOT / "experiments" / "research_funnel" / "closure_experiment.py"
            env = {**os.environ, "AR_OFFLINE": "1", "PYTHONDONTWRITEBYTECODE": "1"}

            commands = [[
                sys.executable, str(script), "packet",
                "--bundle", str(bundle), "--battery", str(battery_path),
                "--generated-at", GENERATED_AT, "--output", str(packet_path),
            ]]
            for command in commands:
                completed = subprocess.run(
                    command, cwd=ROOT, env=env, text=True, capture_output=True, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            draft = receipt_for(packet, codes[:3])
            draft.pop("receipt_hash")
            write_json(draft_path, draft)
            followups = [
                [
                    sys.executable, str(script), "receipt",
                    "--packet", str(packet_path), "--draft", str(draft_path),
                    "--output", str(receipt_path),
                ],
                [
                    sys.executable, str(script), "replay",
                    "--bundle", str(bundle), "--battery", str(battery_path),
                    "--packet", str(packet_path), "--receipt", str(receipt_path),
                    "--generated-at", "2026-08-13T10:06:00+00:00",
                    "--output-dir", str(output),
                ],
                [
                    sys.executable, str(script), "verify", "--output-dir", str(output),
                ],
            ]
            for command in followups:
                completed = subprocess.run(
                    command, cwd=ROOT, env=env, text=True, capture_output=True, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            verification = json.loads(completed.stdout.splitlines()[0])
            self.assertEqual(verification["status"], "VERIFIED")
            self.assertEqual(verification["u4_rows"], 3)
            self.assertEqual(verification["u5_status"], "DATA_BLOCKED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
