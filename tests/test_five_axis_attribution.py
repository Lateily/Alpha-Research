#!/usr/bin/env python3
"""Behavior tests for the offline five-axis paper-cycle attribution receipt."""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))

import five_axis_attribution as attribution  # noqa: E402
import research_cycle as cycle  # noqa: E402
import research_method as method  # noqa: E402
import test_research_cycle as cycle_fixtures  # noqa: E402
import test_research_method as method_fixtures  # noqa: E402


def build_replay(root: Path, *, thesis_wrong: bool = False):
    closure_bundle, codes, _, _, _ = cycle_fixtures.build_closure_bundle(root)
    case = cycle.seal_case(
        cycle_fixtures.build_case_draft(closure_bundle, codes[0]),
        closure_bundle,
    )
    bars = cycle.seal_bars(cycle_fixtures.build_bar_draft(codes[0]), case)
    outcomes = method.seal_outcomes(
        method_fixtures.outcome_draft(
            case["method_registration"], thesis_wrong=thesis_wrong
        ),
        case["method_registration"],
    )
    outputs = cycle.run_cycle(
        bundle_dir=closure_bundle,
        case=case,
        bars=bars,
        outcomes=outcomes,
        generated_at="2026-08-17T16:10:00+00:00",
    )
    cycle_bundle = root / "cycle-result"
    cycle._write_cycle_outputs(
        cycle_bundle, closure_bundle, case, bars, outcomes, *outputs
    )
    return closure_bundle, cycle_bundle, case, outputs


def complete_market_draft(asset_id: str) -> dict:
    samples = []
    current = datetime.strptime("20260105", "%Y%m%d")
    while len(samples) < 120:
        if current.weekday() < 5:
            market_return = 0.01 if len(samples) % 2 == 0 else -0.01
            samples.append(
                {
                    "date": current.strftime("%Y%m%d"),
                    "asset_return": 1.5 * market_return,
                    "benchmark_return": market_return,
                }
            )
        current += timedelta(days=1)
    return {
        "schema": attribution.MARKET_EVIDENCE_SCHEMA,
        "schema_version": attribution.SCHEMA_VERSION,
        "generated_at": "2026-08-17T16:20:00+00:00",
        "market": {
            "status": "COMPLETE",
            "identity": "000300.SH",
            "start_date": "20260814",
            "start_close": 100.0,
            "end_date": "20260817",
            "end_close": 102.0,
            "source_ref": "settled CSI 300 close fixture",
            "evidence_tier": "E2",
            "evidence_hash": "1" * 64,
            "reason_codes": [],
        },
        "industry": {
            "status": "COMPLETE",
            "identity": "SEMICONDUCTOR",
            "start_date": "20260814",
            "start_close": 100.0,
            "end_date": "20260817",
            "end_close": 105.0,
            "source_ref": "settled point-in-time semiconductor cohort fixture",
            "evidence_tier": "E2",
            "evidence_hash": "2" * 64,
            "reason_codes": [],
        },
        "beta_estimate": {
            "status": "COMPLETE",
            "value": 1.5,
            "asset_id": asset_id,
            "benchmark_id": "000300.SH",
            "lookback_start": samples[0]["date"],
            "lookback_end": samples[-1]["date"],
            "observations": 120,
            "method": "OLS_DAILY_RETURNS",
            "registered_at": "20260811",
            "source_ref": "point-in-time 120-session beta fixture",
            "evidence_hash": "3" * 64,
            "samples": samples,
            "samples_hash": attribution._hash(samples),
            "reason_codes": [],
        },
        "no_trade_flag": True,
        "production_authority": False,
        "disclaimer": attribution.DISCLAIMER,
    }


def complete_execution_draft() -> dict:
    return {
        "schema": attribution.EXECUTION_EVIDENCE_SCHEMA,
        "schema_version": attribution.SCHEMA_VERSION,
        "generated_at": "2026-08-17T16:20:00+00:00",
        "source_receipt": {
            "schema": "ar.paper_execution_realism_receipt",
            "schema_version": "1.0",
            "status": "PASS_WORKFLOW_DEBUG",
            "checks": {key: True for key in sorted(attribution.EXECUTION_CHECKS)},
            "cost_verification_status": "ASSUMPTION_ONLY_NOT_BROKER_VERIFIED",
            "known_residuals": [
                "DAILY_OHLC_HAS_NO_INTRADAY_SEQUENCE",
                "NO_PARTIAL_FILL_MODEL",
            ],
            "method_claim_sample_eligible": False,
            "portfolio_promotion_eligible": False,
            "no_trade_flag": True,
        },
        "reason_codes": [],
        "no_trade_flag": True,
        "production_authority": False,
        "disclaimer": attribution.DISCLAIMER,
    }


def sealed_evidence(root: Path, *, thesis_wrong: bool = False):
    closure, cycle_bundle, case, outputs = build_replay(
        root, thesis_wrong=thesis_wrong
    )
    market = attribution.seal_market_evidence(
        complete_market_draft(case["ticker"]), cycle_bundle, closure
    )
    execution = attribution.seal_execution_evidence(
        complete_execution_draft(), cycle_bundle, closure
    )
    return closure, cycle_bundle, case, outputs, market, execution


def all_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from all_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from all_keys(child)


class FiveAxisAttributionTests(unittest.TestCase):
    def test_complete_debug_cycle_has_five_independent_axes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, _, _, market, execution = sealed_evidence(Path(tmp))
            receipt = attribution.build_attribution(
                bundle,
                closure,
                market_evidence=market,
                execution_evidence=execution,
                generated_at="2026-08-17T16:30:00+00:00",
            )
            self.assertEqual(set(receipt["axes"]), attribution.AXIS_KEYS)
            self.assertEqual(receipt["axes"]["thesis"]["status"], "RIGHT")
            self.assertEqual(receipt["axes"]["valuation"]["status"], "IN_RANGE")
            self.assertEqual(receipt["axes"]["timing"]["status"], "RIGHT")
            self.assertEqual(
                receipt["axes"]["execution"]["status"], "WORKFLOW_DEBUG_ONLY"
            )
            self.assertEqual(
                receipt["axes"]["market_beta"]["status"],
                "ATTRIBUTED_DIAGNOSTIC",
            )
            self.assertEqual(receipt["axis_policy"], "INDEPENDENT_AXES_NO_COMPOSITE_SCORE")
            self.assertEqual(receipt["completeness_status"], "WORKFLOW_DEBUG_COMPLETE")

    def test_profit_cannot_rewrite_a_wrong_thesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, _, _, market, execution = sealed_evidence(
                Path(tmp), thesis_wrong=True
            )
            receipt = attribution.build_attribution(
                bundle,
                closure,
                market_evidence=market,
                execution_evidence=execution,
                generated_at="2026-08-17T16:30:00+00:00",
            )
            self.assertEqual(receipt["axes"]["thesis"]["status"], "WRONG")
            self.assertGreater(receipt["paper_result"]["pnl_cny"], 0)
            self.assertEqual(
                receipt["completeness_status"], "WORKFLOW_DEBUG_COMPLETE_WITH_MISS"
            )

    def test_missing_evidence_stays_visible_and_does_not_block_other_axes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, _, _ = build_replay(Path(tmp))
            receipt = attribution.build_attribution(
                bundle,
                closure,
                market_evidence=None,
                execution_evidence=None,
                generated_at="2026-08-17T16:30:00+00:00",
            )
            self.assertEqual(receipt["axes"]["thesis"]["status"], "RIGHT")
            self.assertEqual(receipt["axes"]["execution"]["status"], "DATA_BLOCKED")
            self.assertEqual(receipt["axes"]["market_beta"]["status"], "DATA_BLOCKED")
            self.assertEqual(receipt["completeness_status"], "DATA_BLOCKED")

    def test_beta_estimate_must_be_point_in_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, case, _ = build_replay(Path(tmp))
            draft = complete_market_draft(case["ticker"])
            draft["beta_estimate"]["lookback_end"] = "20260814"
            with self.assertRaisesRegex(attribution.AttributionError, "point-in-time"):
                attribution.seal_market_evidence(draft, bundle, closure)

            draft = complete_market_draft(case["ticker"])
            draft["beta_estimate"]["registered_at"] = "20260814"
            with self.assertRaisesRegex(attribution.AttributionError, "point-in-time"):
                attribution.seal_market_evidence(draft, bundle, closure)

            draft = complete_market_draft(case["ticker"])
            draft["beta_estimate"]["registered_at"] = "20260618"
            with self.assertRaisesRegex(attribution.AttributionError, "point-in-time"):
                attribution.seal_market_evidence(draft, bundle, closure)

            draft = complete_market_draft(case["ticker"])
            draft["beta_estimate"]["registered_at"] = draft["beta_estimate"][
                "lookback_end"
            ]
            attribution.seal_market_evidence(draft, bundle, closure)

    def test_beta_requires_enough_settled_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, case, _ = build_replay(Path(tmp))
            draft = complete_market_draft(case["ticker"])
            draft["beta_estimate"]["observations"] = 59
            with self.assertRaisesRegex(attribution.AttributionError, "at least 60"):
                attribution.seal_market_evidence(draft, bundle, closure)

    def test_beta_samples_are_bound_to_the_cycle_ticker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, case, _ = build_replay(Path(tmp))
            draft = complete_market_draft(case["ticker"])
            draft["beta_estimate"]["asset_id"] = "600000.SH"
            with self.assertRaisesRegex(attribution.AttributionError, "asset differs"):
                attribution.seal_market_evidence(draft, bundle, closure)

    def test_beta_samples_are_bound_to_the_market_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, case, _ = build_replay(Path(tmp))
            draft = complete_market_draft(case["ticker"])
            draft["beta_estimate"]["benchmark_id"] = "000905.SH"
            with self.assertRaisesRegex(attribution.AttributionError, "benchmark differs"):
                attribution.seal_market_evidence(draft, bundle, closure)

    def test_beta_is_recomputed_from_frozen_return_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, case, _ = build_replay(Path(tmp))
            draft = complete_market_draft(case["ticker"])
            draft["beta_estimate"]["value"] = 1.4
            with self.assertRaisesRegex(attribution.AttributionError, "not derived"):
                attribution.seal_market_evidence(draft, bundle, closure)

            draft = complete_market_draft(case["ticker"])
            draft["beta_estimate"]["samples"][0]["date"] = draft["beta_estimate"]["samples"][1]["date"]
            draft["beta_estimate"]["samples_hash"] = attribution._hash(
                draft["beta_estimate"]["samples"]
            )
            with self.assertRaisesRegex(attribution.AttributionError, "unique ordered"):
                attribution.seal_market_evidence(draft, bundle, closure)

    def test_market_and_industry_windows_must_match_the_closed_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, case, _ = build_replay(Path(tmp))
            draft = complete_market_draft(case["ticker"])
            draft["market"]["start_date"] = "20260813"
            with self.assertRaisesRegex(attribution.AttributionError, "exact paper holding window"):
                attribution.seal_market_evidence(draft, bundle, closure)

            draft = complete_market_draft(case["ticker"])
            draft["industry"]["identity"] = "INNOVATIVE_DRUG"
            with self.assertRaisesRegex(attribution.AttributionError, "registered evidence"):
                attribution.seal_market_evidence(draft, bundle, closure)

    def test_complete_price_evidence_requires_settled_tier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, case, _ = build_replay(Path(tmp))
            draft = complete_market_draft(case["ticker"])
            draft["market"]["evidence_tier"] = "E3"
            with self.assertRaisesRegex(attribution.AttributionError, "settled E1/E2"):
                attribution.seal_market_evidence(draft, bundle, closure)

    def test_market_evidence_is_bound_to_exact_cycle_and_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, _, _, market, _ = sealed_evidence(Path(tmp))
            changed = copy.deepcopy(market)
            changed["order_hash"] = "f" * 64
            changed["market_evidence_hash"] = attribution._hash(
                attribution._without(changed, "market_evidence_hash")
            )
            with self.assertRaisesRegex(attribution.AttributionError, "exact cycle and order"):
                attribution.validate_market_evidence(changed, bundle, closure)

    def test_execution_evidence_is_bound_to_exact_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, _, _, _, execution = sealed_evidence(Path(tmp))
            changed = copy.deepcopy(execution)
            changed["order_hash"] = "f" * 64
            changed["execution_evidence_hash"] = attribution._hash(
                attribution._without(changed, "execution_evidence_hash")
            )
            with self.assertRaisesRegex(attribution.AttributionError, "exact cycle and order"):
                attribution.validate_execution_evidence(changed, bundle, closure)

    def test_execution_pass_requires_every_realism_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, _, _ = build_replay(Path(tmp))
            draft = complete_execution_draft()
            draft["source_receipt"]["checks"]["t_plus_one_sell"] = False
            with self.assertRaisesRegex(attribution.AttributionError, "failed checks"):
                attribution.seal_execution_evidence(draft, bundle, closure)

    def test_execution_wrapper_freezes_the_full_source_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, _, _, _, execution = sealed_evidence(Path(tmp))
            changed = copy.deepcopy(execution)
            changed["source_receipt"]["cost_verification_status"] = "BROKER_VERIFIED"
            changed["execution_evidence_hash"] = attribution._hash(
                attribution._without(changed, "execution_evidence_hash")
            )
            with self.assertRaisesRegex(attribution.AttributionError, "full source receipt"):
                attribution.validate_execution_evidence(changed, bundle, closure)

    def test_workflow_debug_execution_never_becomes_method_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, _, _, market, execution = sealed_evidence(Path(tmp))
            receipt = attribution.build_attribution(
                bundle,
                closure,
                market_evidence=market,
                execution_evidence=execution,
                generated_at="2026-08-17T16:30:00+00:00",
            )
            self.assertFalse(receipt["method_sample_eligible"])
            self.assertFalse(receipt["claim_allowed"])
            self.assertEqual(receipt["sample_purpose"], "WORKFLOW_DEBUG")
            self.assertEqual(
                receipt["axes"]["execution"]["status"], "WORKFLOW_DEBUG_ONLY"
            )
            self.assertEqual(
                receipt["axes"]["execution"]["reason_codes"],
                ["EXECUTION_AUDIT_NOT_METHOD_CLAIM_ELIGIBLE"],
            )

    def test_derived_receipt_hardcodes_the_no_claim_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, _, _, market, execution = sealed_evidence(Path(tmp))
            receipt = attribution._derive_attribution(
                attribution._cycle_inputs(bundle, closure),
                market_evidence=market,
                execution_evidence=execution,
                generated_at="2026-08-17T16:30:00+00:00",
            )
            self.assertFalse(receipt["method_sample_eligible"])
            self.assertFalse(receipt["claim_allowed"])
            self.assertFalse(receipt["production_authority"])
            self.assertTrue(receipt["no_trade_flag"])

    def test_receipt_cannot_acquire_claim_or_trade_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, _, _, market, execution = sealed_evidence(Path(tmp))
            receipt = attribution.build_attribution(
                bundle,
                closure,
                market_evidence=market,
                execution_evidence=execution,
                generated_at="2026-08-17T16:30:00+00:00",
            )
            changed = copy.deepcopy(receipt)
            changed["method_sample_eligible"] = True
            changed["attribution_hash"] = attribution._hash(
                attribution._without(changed, "attribution_hash")
            )
            with self.assertRaisesRegex(attribution.AttributionError, "authority or sample"):
                attribution.validate_attribution(
                    changed,
                    bundle,
                    closure,
                    market_evidence=market,
                    execution_evidence=execution,
                )

    def test_market_beta_is_derived_and_never_called_alpha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, _, outputs, market, execution = sealed_evidence(Path(tmp))
            receipt = attribution.build_attribution(
                bundle,
                closure,
                market_evidence=market,
                execution_evidence=execution,
                generated_at="2026-08-17T16:30:00+00:00",
            )
            axis = receipt["axes"]["market_beta"]
            order = outputs[1]["orders"][0]
            self.assertAlmostEqual(order["fill_price"], 100.05)
            self.assertAlmostEqual(order["exit_price"], 115.0)
            expected_gross = order["exit_price"] / order["fill_price"] - 1.0
            self.assertAlmostEqual(axis["gross_stock_return"], expected_gross)
            self.assertAlmostEqual(axis["market_return"], 0.02)
            self.assertAlmostEqual(axis["industry_return"], 0.05)
            self.assertAlmostEqual(axis["market_beta_contribution"], 0.03)
            self.assertAlmostEqual(axis["beta_residual_return"], expected_gross - 0.03)
            self.assertAlmostEqual(axis["market_excess_return"], expected_gross - 0.02)
            self.assertAlmostEqual(axis["industry_excess_return"], expected_gross - 0.05)
            self.assertEqual(axis["interpretation"], "DIAGNOSTIC_NOT_ALPHA")
            self.assertNotIn("alpha", set(all_keys(receipt)))

    def test_data_blocked_market_leg_cannot_carry_prices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, case, _ = build_replay(Path(tmp))
            draft = complete_market_draft(case["ticker"])
            draft["market"].update(
                {
                    "status": "DATA_BLOCKED",
                    "start_close": None,
                    "end_close": None,
                    "evidence_tier": None,
                    "reason_codes": ["SETTLED_MARKET_PRICE_MISSING"],
                }
            )
            market = attribution.seal_market_evidence(draft, bundle, closure)
            receipt = attribution.build_attribution(
                bundle,
                closure,
                market_evidence=market,
                execution_evidence=None,
                generated_at="2026-08-17T16:30:00+00:00",
            )
            self.assertEqual(receipt["axes"]["market_beta"]["status"], "DATA_BLOCKED")
            self.assertIsNone(receipt["axes"]["market_beta"]["market_return"])

    def test_receipt_is_a_deterministic_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, _, _, market, execution = sealed_evidence(Path(tmp))
            receipt = attribution.build_attribution(
                bundle,
                closure,
                market_evidence=market,
                execution_evidence=execution,
                generated_at="2026-08-17T16:30:00+00:00",
            )
            changed = copy.deepcopy(receipt)
            changed["axes"]["thesis"]["status"] = "WRONG"
            changed["attribution_hash"] = attribution._hash(
                attribution._without(changed, "attribution_hash")
            )
            with self.assertRaisesRegex(attribution.AttributionError, "deterministic"):
                attribution.validate_attribution(
                    changed,
                    bundle,
                    closure,
                    market_evidence=market,
                    execution_evidence=execution,
                )

    def test_receipt_cannot_predate_its_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure, bundle, _, _, market, execution = sealed_evidence(Path(tmp))
            with self.assertRaisesRegex(attribution.AttributionError, "predates"):
                attribution.build_attribution(
                    bundle,
                    closure,
                    market_evidence=market,
                    execution_evidence=execution,
                    generated_at="2026-08-17T16:19:59+00:00",
                )

    def test_output_is_append_only_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure, bundle, _, _, market, execution = sealed_evidence(root)
            receipt = attribution.build_attribution(
                bundle,
                closure,
                market_evidence=market,
                execution_evidence=execution,
                generated_at="2026-08-17T16:30:00+00:00",
            )
            output = root / "five-axis.json"
            attribution._write_new_json(output, receipt)
            original = output.read_bytes()
            with self.assertRaisesRegex(attribution.AttributionError, "refusing to overwrite"):
                attribution._write_new_json(output, receipt)
            self.assertEqual(output.read_bytes(), original)

    def test_cli_requires_explicit_evidence_paths_and_refuses_replay_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure, bundle, _, _, market, execution = sealed_evidence(root)
            market_path = root / "market.json"
            execution_path = root / "execution.json"
            output = root / "attribution.json"
            market_path.write_text(json.dumps(market), encoding="utf-8")
            execution_path.write_text(json.dumps(execution), encoding="utf-8")
            argv = [
                "--cycle-bundle",
                str(bundle),
                "--closure-bundle",
                str(closure),
                "--market-evidence",
                str(market_path),
                "--execution-evidence",
                str(execution_path),
                "--generated-at",
                "2026-08-17T16:30:00+00:00",
                "--output",
                str(output),
            ]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(attribution.main(argv), 0)
            first = output.read_bytes()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(attribution.main(argv), 1)
            self.assertEqual(output.read_bytes(), first)

    def test_duplicate_json_keys_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.json"
            path.write_text('{"schema":"one","schema":"two"}', encoding="utf-8")
            with self.assertRaisesRegex(attribution.AttributionError, "duplicate JSON key"):
                attribution._load_object(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
