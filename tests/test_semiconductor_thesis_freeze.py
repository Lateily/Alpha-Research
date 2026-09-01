#!/usr/bin/env python3
"""Behavior gates for the first three semiconductor thesis-freeze proposals."""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))
sys.path.insert(0, str(ROOT / "scripts" / "llm"))

import semiconductor_thesis_freeze as freeze  # noqa: E402
from ai_os.task_compiler import SPEC_READY, compile_task_manifest  # noqa: E402


ARTIFACT_DIR = ROOT / "docs/research/prospective/semiconductor_workflow_debug_001"
BUNDLE_PATH = ARTIFACT_DIR / "freeze_proposals.json"
TASK_PATH = ROOT / "scripts/llm/fixtures/semiconductor_thesis_freeze.task.json"


def load_bundle() -> dict:
    return json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))


class SemiconductorThesisFreezeTests(unittest.TestCase):
    def test_task_contract_compiles_to_spec_ready(self) -> None:
        source = json.loads(TASK_PATH.read_text(encoding="utf-8"))
        result = compile_task_manifest(source)
        self.assertEqual(SPEC_READY, result.status, result.errors)

    def test_directory_manifest_and_all_content_receipts_verify(self) -> None:
        self.assertEqual([], freeze.validate_directory(ARTIFACT_DIR))
        bundle = load_bundle()
        self.assertEqual(freeze.EXPECTED_BUNDLE_HASH, bundle["bundle_hash"])
        self.assertEqual(freeze.EXPECTED_LEDGER_SHA256, bundle["u4_ledger_snapshot_sha256"])

    def test_exact_three_u4_selects_remain_wait_without_authority(self) -> None:
        bundle = load_bundle()
        self.assertEqual(sorted(freeze.EXPECTED_CASES), bundle["selected_tickers"])
        for case in bundle["cases"]:
            with self.subTest(ticker=case["ticker"]):
                self.assertEqual("SELECT", case["u4_binding"]["decision"])
                self.assertEqual("WAIT", case["timing_ticket"]["status"])
                self.assertEqual("WAIT", case["method_registration_draft"]["smc"]["status"])
                self.assertTrue(case["timing_ticket"]["no_trade_flag"])
                self.assertFalse(case["timing_ticket"]["production_authority"])
                self.assertEqual("AWAITING_JUNYAN_CONTENT_REVIEW", case["status"])

    def test_factpack_and_settled_e3_chronology_is_explicit(self) -> None:
        bundle = load_bundle()
        self.assertEqual("20260824", bundle["fact_cutoff"])
        self.assertEqual("20260831", bundle["settled_e3_cutoff"])
        self.assertEqual("20260901", bundle["smc_assessment_date"])
        for case in bundle["cases"]:
            source_dates = [row["source_date"] for row in case["source_evidence"]["financial_records"]]
            self.assertTrue(all(date <= "20260824" for date in source_dates))
            self.assertEqual(
                "20260831",
                case["source_evidence"]["settled_e3"]["technical_summary"]["settled_trade_date"],
            )

    def test_fengda_h1_post_cutoff_numbers_are_not_in_factpack(self) -> None:
        case = next(case for case in load_bundle()["cases"] if case["ticker"] == "688279.SH")
        serialized = json.dumps(case["source_evidence"]["financial_records"], ensure_ascii=False)
        self.assertNotIn("20260828", serialized)
        self.assertNotIn("560903072.28", serialized)
        gaps = [gap for axis in case["quality_scorecard"]["axes"] for gap in axis["gaps"]]
        self.assertTrue(any("H1 was unavailable" in gap for gap in gaps))

    def test_valuation_is_derived_and_reference_price_exceeds_base_for_all_three(self) -> None:
        for case in load_bundle()["cases"]:
            with self.subTest(ticker=case["ticker"]):
                valuation = case["method_registration_draft"]["valuation"]
                inputs = valuation["model_inputs"]
                expected_low = round(
                    inputs["normalized_eps"] * inputs["fair_multiple_low"]
                    + inputs["net_cash_per_share"],
                    4,
                )
                expected_high = round(
                    inputs["normalized_eps"] * inputs["fair_multiple_high"]
                    + inputs["net_cash_per_share"],
                    4,
                )
                output = valuation["model_output"]
                self.assertEqual(expected_low, output["computed_base_low"])
                self.assertEqual(expected_high, output["computed_base_high"])
                self.assertGreater(valuation["reference_price"], expected_high)

    def test_each_case_has_five_mechanized_wrong_if_lines(self) -> None:
        for case in load_bundle()["cases"]:
            with self.subTest(ticker=case["ticker"]):
                triggers = case["thesis_core"]["wrong_if"]["triggers"]
                invalidations = [
                    item
                    for item in case["method_registration_draft"]["thesis_expectations"]
                    if item["kind"] == "INVALIDATION"
                ]
                self.assertEqual(5, len(triggers))
                self.assertEqual(5, len(invalidations))
                self.assertEqual(
                    {freeze._hash(trigger) for trigger in triggers},
                    {item["wrong_if_trigger_hash"] for item in invalidations},
                )

    def test_quality_pass_measures_reviewability_not_trade_readiness(self) -> None:
        for case in load_bundle()["cases"]:
            with self.subTest(ticker=case["ticker"]):
                scorecard = case["quality_scorecard"]
                self.assertEqual("QUALITY_PASS", scorecard["status"])
                self.assertEqual("READY_FOR_HUMAN_REVIEW", scorecard["next_state"])
                self.assertGreaterEqual(scorecard["average_score"], 70)
                self.assertEqual(freeze.AUTHORITY, scorecard["authority"])
                self.assertEqual("WAIT", case["timing_ticket"]["status"])

    def test_post_cutoff_fact_fails_even_when_resealed(self) -> None:
        mutated = load_bundle()
        mutated["cases"][0]["source_evidence"]["financial_records"][0]["source_date"] = "20260825"
        with self.assertRaisesRegex(freeze.FreezeError, "post-cutoff fact"):
            freeze.seal_bundle(mutated)

    def test_u4_row_hash_substitution_fails_closed(self) -> None:
        mutated = load_bundle()
        mutated["cases"][0]["u4_binding"]["u3_battery_row_hash"] = "0" * 64
        with self.assertRaisesRegex(freeze.FreezeError, "U4 binding"):
            freeze.seal_bundle(mutated)

    def test_content_edit_needs_a_new_junyan_review_hash(self) -> None:
        mutated = load_bundle()
        mutated["cases"][0]["thesis_core"]["thesis"]["mechanism"]["zh"] += "（擅自改写）"
        with self.assertRaisesRegex(freeze.FreezeError, "frozen case content hash"):
            freeze.seal_bundle(mutated)

    def test_bundle_metadata_edit_needs_a_new_junyan_review_hash(self) -> None:
        mutated = load_bundle()
        mutated["generated_at"] = "2026-09-01T15:01:00+08:00"
        with self.assertRaisesRegex(freeze.FreezeError, "frozen bundle content hash"):
            freeze.seal_bundle(mutated)

    def test_smc_wait_cannot_be_promoted_without_pass_evidence(self) -> None:
        mutated = load_bundle()
        mutated["cases"][0]["method_registration_draft"]["smc"]["status"] = "PASS"
        mutated["cases"][0]["timing_ticket"]["status"] = "PASS"
        with self.assertRaisesRegex(freeze.FreezeError, "SMC PASS lacks"):
            freeze.seal_bundle(mutated)

    def test_source_metadata_is_inside_record_hash(self) -> None:
        mutated = load_bundle()
        record = mutated["cases"][0]["source_evidence"]["financial_records"][1]
        record["source_ref"] = "unreviewed replacement"
        errors = freeze.validate_bundle(mutated)
        self.assertTrue(any("financial source record hash mismatch" in error for error in errors), errors)

    def test_invalid_ohlc_shape_fails_closed(self) -> None:
        mutated = load_bundle()
        bar = mutated["cases"][0]["source_evidence"]["settled_e3"]["bars"][0]
        bar["low"] = bar["close"] + 1.0
        with self.assertRaisesRegex(freeze.FreezeError, "bar shape"):
            freeze.seal_bundle(mutated)

    def test_split_case_drift_is_visible_even_if_bundle_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "freeze"
            shutil.copytree(ARTIFACT_DIR, root)
            path = root / "300236.SZ.json"
            case = json.loads(path.read_text(encoding="utf-8"))
            case["name"] = "drifted copy"
            path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
            errors = freeze.validate_directory(root)
            self.assertTrue(any("artifact hash mismatch" in error for error in errors), errors)
            self.assertTrue(any("case copy differs" in error for error in errors), errors)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.json"
            path.write_text('{"schema":"a","schema":"b"}', encoding="utf-8")
            with self.assertRaisesRegex(freeze.FreezeError, "duplicate JSON key"):
                freeze._load(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
