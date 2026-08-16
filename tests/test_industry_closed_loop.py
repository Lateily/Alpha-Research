#!/usr/bin/env python3
"""Behavior regressions for the paper-only single-industry closed loop."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.research_closed_loop import industry_pilot as pilot


FIXTURE = (
    ROOT
    / "experiments"
    / "research_closed_loop"
    / "fixtures"
    / "livestock_pilot.complete.json"
)
SPEC = (
    ROOT
    / "experiments"
    / "research_closed_loop"
    / "specs"
    / "livestock_pilot.v1.json"
)


class IndustryClosedLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = pilot.load_json_strict(FIXTURE)
        self.spec = pilot.load_json_strict(SPEC)

    def build(self, payload: dict | None = None) -> dict:
        return pilot.build_receipt(payload or self.payload, self.spec)

    def test_complete_fixture_closes_cycle_without_unlocking_claim(self) -> None:
        receipt = self.build()
        self.assertEqual("CYCLE_REVIEWED", receipt["status"])
        self.assertEqual("COMPLETE", receipt["stages"]["review"])
        self.assertFalse(receipt["claim_gate"]["claim_allowed"])
        self.assertEqual("INSUFFICIENT_SAMPLE", receipt["claim_gate"]["state"])
        self.assertEqual(0, receipt["claim_gate"]["fixture_contribution"])
        self.assertEqual("FORBIDDEN", receipt["claim_gate"]["profitability_guarantee"])
        self.assertEqual(
            "REFERENCE_ONLY_NOT_IDENTITY_PROOF",
            receipt["selection"]["approval_evidence_strength"],
        )
        self.assertEqual(
            "REFERENCE_ONLY_NOT_IDENTITY_PROOF",
            receipt["paper_portfolio"]["approval_evidence_strength"],
        )

    def test_missing_primary_outcome_stays_pending(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["outcomes"] = []
        payload["reviews"] = []
        receipt = self.build(payload)
        self.assertEqual("OUTCOME_PENDING", receipt["status"])
        self.assertEqual("WINDOW_OPEN", receipt["stages"]["outcome_attribution"])

    def test_settled_primary_without_review_enters_review_queue(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["reviews"] = []
        receipt = self.build(payload)
        self.assertEqual("REVIEW_REQUIRED", receipt["status"])
        self.assertEqual("THESIS-FIX001-LT-001", receipt["review_queue"][0]["reason"])

    def test_blocked_factor_remains_visible_and_blocks_cycle(self) -> None:
        payload = copy.deepcopy(self.payload)
        factor = payload["factors"][0]
        factor.update(value=None, status="DATA_BLOCKED", blocked_reason="fixture outage")
        receipt = self.build(payload)
        self.assertEqual("DATA_BLOCKED", receipt["status"])
        self.assertEqual(["HOG_SPOT_PRICE"], receipt["factor_coverage"]["blocked_factor_ids"])

    def test_stale_available_factor_is_refused(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["factors"][0]["as_of"] = "20260701"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "stale factor"):
            self.build(payload)

    def test_data_conflict_cannot_carry_canonical_value(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["factors"][0].update(
            status="DATA_CONFLICT",
            value=18.2,
            conflict_refs=["fixture:E1/a", "fixture:E1/b"],
        )
        with self.assertRaisesRegex(pilot.ClosedLoopError, "cannot carry"):
            self.build(payload)

    def test_u4_selection_cannot_be_automated_or_impersonated(self) -> None:
        automated = copy.deepcopy(self.payload)
        automated["selection"]["auto_selection"] = True
        with self.assertRaisesRegex(pilot.ClosedLoopError, "auto_selection"):
            self.build(automated)
        impersonated = copy.deepcopy(self.payload)
        impersonated["selection"]["selected_by"] = "junyan-agent"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "must be Junyan"):
            self.build(impersonated)

    def test_selection_must_bind_same_day_immutable_bundle(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["selection"]["source_bundle_as_of"] = "20260809"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "source bundle"):
            self.build(payload)
        payload = copy.deepcopy(self.payload)
        payload["selection"]["source_bundle_hash"] = "not-a-hash"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "must be sha256"):
            self.build(payload)
        payload = copy.deepcopy(self.payload)
        payload["selection"]["tickers"].append("FIX002.TEST")
        with self.assertRaisesRegex(pilot.ClosedLoopError, "exactly one selected ticker"):
            self.build(payload)

    def test_approval_dates_are_compared_in_beijing_time(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["selection"]["selected_at"] = "2026-08-10T20:10:00-04:00"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "registered_trade_date"):
            self.build(payload)

    def test_load_bearing_research_facts_must_be_e1(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["companies"][0]["factpack"][0]["evidence_grade"] = "E2"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "load-bearing fact must be E1"):
            self.build(payload)

    def test_factpack_cannot_use_post_registration_evidence(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["companies"][0]["factpack"][0]["as_of"] = "20260811"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "post-registration fact"):
            self.build(payload)

    def test_fewer_than_three_load_bearing_e1_requires_review(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["companies"][0]["factpack"][0]["load_bearing"] = False
        receipt = self.build(payload)
        self.assertEqual("REVIEW_REQUIRED", receipt["status"])
        self.assertEqual("REVIEW_REQUIRED", receipt["stages"]["deep_research"])

    def test_decision_pack_cannot_emit_action_posture(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["companies"][0]["decision_pack"]["execution_gate"]["posture"] = "BUY_NOW"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "decision pack invalid"):
            self.build(payload)

    def test_nested_trading_authority_field_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["companies"][0]["decision_pack"]["trade_action"] = "BUY"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "forbidden authority field"):
            self.build(payload)

    def test_nested_formal_blocking_authority_must_stay_false(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["companies"][0]["decision_pack"]["formal_blocking_authority"] = True
        with self.assertRaisesRegex(pilot.ClosedLoopError, "must remain false"):
            self.build(payload)

    def test_human_pass_review_must_bind_junyan(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["companies"][0]["human_review"]["reviewer"] = "agent"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "not bound to Junyan"):
            self.build(payload)
        payload = copy.deepcopy(self.payload)
        payload["companies"][0]["human_review"]["reviewed_at"] = "2026-08-09T16:00:00+08:00"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "outside PIT window"):
            self.build(payload)

    def test_swing_and_long_term_are_explicit_and_mutually_checked(self) -> None:
        payload = copy.deepcopy(self.payload)
        company = payload["companies"][0]
        company["holding_policy"] = {
            "style": "SWING",
            "horizon_days": 20,
            "sector_confirmation": "fixture:sector confirmed",
            "entry_condition": "fixture:paper review condition",
            "structural_invalidation": "fixture:structure break",
            "time_stop_days": 20,
        }
        payload["paper_portfolio"]["allocations"][0]["style"] = "SWING"
        receipt = self.build(payload)
        self.assertEqual("SWING", receipt["companies"][0]["holding_style"])
        company["holding_policy"]["horizon_days"] = 61
        with self.assertRaisesRegex(pilot.ClosedLoopError, "outside SWING bounds"):
            self.build(payload)

    def test_portfolio_is_paper_only_and_cannot_exceed_caps(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["paper_portfolio"]["capital_authority"] = True
        with self.assertRaisesRegex(pilot.ClosedLoopError, "capital_authority"):
            self.build(payload)
        payload = copy.deepcopy(self.payload)
        payload["paper_portfolio"]["allocations"][0]["paper_risk_units"] = 0.75
        with self.assertRaisesRegex(pilot.ClosedLoopError, "single-name cap"):
            self.build(payload)

    def test_portfolio_style_cannot_disagree_with_thesis(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["paper_portfolio"]["allocations"][0]["style"] = "SWING"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "style disagrees"):
            self.build(payload)

    def test_outcome_cannot_be_future_dated_or_self_reported_without_hash(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["outcomes"][1]["observed_as_of"] = "20260817"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "outside PIT window"):
            self.build(payload)
        payload = copy.deepcopy(self.payload)
        payload["outcomes"][1]["source_hash"] = "self-reported"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "lacks source hash"):
            self.build(payload)

    def test_review_requires_settled_t5_and_cannot_auto_change_policy(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["outcomes"] = payload["outcomes"][:1]
        with self.assertRaisesRegex(pilot.ClosedLoopError, r"lacks a settled T\+5"):
            self.build(payload)
        payload = copy.deepcopy(self.payload)
        payload["reviews"][0]["automatic_policy_change"] = True
        with self.assertRaisesRegex(pilot.ClosedLoopError, "cannot change policy automatically"):
            self.build(payload)
        payload = copy.deepcopy(self.payload)
        payload["reviews"][0]["reviewed_at"] = "2026-08-15T16:00:00+08:00"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "post-outcome PIT window"):
            self.build(payload)

    def test_test_ticker_cannot_escape_fixture_mode(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["fixture_only"] = False
        with self.assertRaisesRegex(pilot.ClosedLoopError, "TEST tickers"):
            self.build(payload)

    def test_receipt_tampering_cannot_unlock_authority_or_claim(self) -> None:
        receipt = self.build()
        tampered = copy.deepcopy(receipt)
        tampered["claim_gate"]["claim_allowed"] = True
        with self.assertRaisesRegex(pilot.ClosedLoopError, "claim_allowed"):
            pilot.validate_receipt(tampered, self.spec)
        tampered = copy.deepcopy(receipt)
        tampered["permissions"]["trading_authority"] = True
        with self.assertRaisesRegex(pilot.ClosedLoopError, "must remain false"):
            pilot.validate_receipt(tampered, self.spec)
        tampered = copy.deepcopy(receipt)
        tampered["selection"]["approval_evidence_strength"] = "VERIFIED_IDENTITY"
        with self.assertRaisesRegex(pilot.ClosedLoopError, "evidence strength"):
            pilot.validate_receipt(tampered, self.spec)

    def test_spec_cannot_enable_authority_or_relax_claim_gate(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["permissions"]["trading_authority"] = True
        with self.assertRaisesRegex(pilot.ClosedLoopError, "permission must be false"):
            pilot.build_receipt(self.payload, spec)
        spec = copy.deepcopy(self.spec)
        spec["claim_gate"]["minimum_independent_clusters"] = 29
        with self.assertRaisesRegex(pilot.ClosedLoopError, "threshold must remain 30"):
            pilot.build_receipt(self.payload, spec)
        spec = copy.deepcopy(self.spec)
        spec["claim_gate"]["historical_or_fixture_contribution"] = 1
        with self.assertRaisesRegex(pilot.ClosedLoopError, "contribution must remain zero"):
            pilot.build_receipt(self.payload, spec)

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.json"
            path.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
            with self.assertRaisesRegex(pilot.ClosedLoopError, "duplicate JSON key"):
                pilot.load_json_strict(path)

    def test_cli_runs_real_entrypoint_and_writes_only_declared_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "receipt.json"
            env = dict(os.environ, AR_OFFLINE="1")
            result = subprocess.run(
                [
                    "python3",
                    str(ROOT / "experiments/research_closed_loop/industry_pilot.py"),
                    "--input",
                    str(FIXTURE),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("CYCLE_REVIEWED", json.loads(output.read_text())["status"])

    def test_cli_refusal_does_not_overwrite_existing_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_input = tmp_path / "bad-input.json"
            output = tmp_path / "receipt.json"
            payload = copy.deepcopy(self.payload)
            payload["paper_portfolio"]["capital_authority"] = True
            bad_input.write_text(json.dumps(payload), encoding="utf-8")
            output.write_text("sentinel\n", encoding="utf-8")
            result = subprocess.run(
                [
                    "python3",
                    str(ROOT / "experiments/research_closed_loop/industry_pilot.py"),
                    "--input",
                    str(bad_input),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                env=dict(os.environ, AR_OFFLINE="1"),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(1, result.returncode)
            self.assertIn("REFUSED", result.stderr)
            self.assertEqual("sentinel\n", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
