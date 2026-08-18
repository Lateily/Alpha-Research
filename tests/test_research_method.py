#!/usr/bin/env python3
"""Behavior regressions for registered research methods and attribution."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))
sys.path.insert(0, str(ROOT / "scripts"))

import decision_pack as decision_pack_contract  # noqa: E402
import decision_sheet as decision_sheet_contract  # noqa: E402
import funnel_pipeline as funnel  # noqa: E402
import research_method as method  # noqa: E402


def method_inputs() -> tuple[dict, dict, dict]:
    core = decision_sheet_contract._valid_core()
    core["identity"]["ticker"] = "688001.SH"
    core["identity"]["as_of"] = "2026-08-11"
    pack = decision_pack_contract._complete_pack()
    pack["execution_gate"]["posture"] = "RECLAIM_REVIEW"
    pack["paper_plan"] = {
        "entry_review": 100.0,
        "stop_reference": 95.0,
        "take_profit_reference": 115.0,
        "invalidation": 94.9,
        "no_trade_flag": True,
    }
    timing = {
        "status": "PASS",
        "as_of": "20260813",
        "posture": "RECLAIM_REVIEW",
        "market_state": "WEAK_REPAIR",
        "sector_state": "CONFIRMED",
        "flow_state": "SETTLED_INFLOW_CONFIRMED",
        "technical_state": "STRUCTURE_VALID",
        "portfolio_state": "WITHIN_LIMITS",
        "entry_review": 100.0,
        "stop_reference": 95.0,
        "take_profit_reference": 115.0,
        "intraday_sample_eligible": False,
        "settlement_required": True,
        "human_executes": True,
        "no_trade_flag": True,
        "production_authority": False,
    }
    return core, timing, pack


def registration_draft() -> tuple[dict, dict, dict, dict]:
    core, timing, pack = method_inputs()
    wrong_if = core["wrong_if"]["triggers"]
    draft = {
        "schema": method.REGISTRATION_SCHEMA,
        "schema_version": method.SCHEMA_VERSION,
        "ticker": "688001.SH",
        "as_of": "20260811",
        "registered_at": "20260813",
        "strategy_mode": "SWING",
        "thesis_core_hash": funnel._hash(core),
        "timing_ticket_hash": funnel._hash(timing),
        "decision_pack_hash": funnel._hash(pack),
        "wrong_if_hash": funnel._hash(wrong_if),
        "thesis_expectations": [
            {
                "claim_id": "CATALYST_H1",
                "kind": "CATALYST",
                "metric": "H1_REPORT_RELEASED",
                "operator": "OCCURRED",
                "threshold": True,
                "due_date": "20260817",
                "required_tier": "E1",
                "source_ref": "issuer filing calendar",
                "measurement_period": "FY2026_H1_RELEASE",
                "wrong_if_trigger_hash": None,
            },
            {
                "claim_id": "FUND_NORMALIZED_EPS",
                "kind": "FUNDAMENTAL",
                "metric": "NORMALIZED_EPS",
                "operator": "GTE",
                "threshold": 3.5,
                "due_date": "20260817",
                "required_tier": "E1",
                "source_ref": "issuer settled results",
                "measurement_period": "FY2026_H1",
                "wrong_if_trigger_hash": None,
            },
            {
                "claim_id": "INVALID_GM",
                "kind": "INVALIDATION",
                "metric": "GM_PCT",
                "operator": "LTE",
                "threshold": 16.5,
                "due_date": "20260817",
                "required_tier": "E1",
                "source_ref": "issuer settled results",
                "measurement_period": "FY2026_H1",
                "wrong_if_trigger_hash": funnel._hash(wrong_if[0]),
            },
            {
                "claim_id": "INVALID_NP",
                "kind": "INVALIDATION",
                "metric": "NP_YOY_PCT",
                "operator": "LTE",
                "threshold": -40.0,
                "due_date": "20260817",
                "required_tier": "E1",
                "source_ref": "issuer settled results",
                "measurement_period": "FY2026_H1",
                "wrong_if_trigger_hash": funnel._hash(wrong_if[1]),
            },
        ],
        "valuation": {
            "adapter": "SEMICONDUCTOR_NORMALIZED_EARNINGS",
            "industry": "SEMICONDUCTOR",
            "currency": "CNY",
            "scenario_band_hash": funnel._hash(core["valuation_target_range"]),
            "reference_price": 93.75,
            "reference_price_source": "settled close 20260813",
            "market_implied_case": "Market discounts normalized EPS below 3.5.",
            "paper_exit_reference": 100.0,
            "model_inputs": {
                "normalized_eps": 4.0,
                "fair_multiple_low": 22.5,
                "fair_multiple_high": 25.0,
                "net_cash_per_share": 5.0,
            },
            "model_output": {
                "computed_base_low": 95.0,
                "computed_base_high": 105.0,
                "calculation_status": "MANUAL_UNVALIDATED",
            },
            "forecasts": [
                {
                    "forecast_id": "VALUATION_NORMALIZED_EPS",
                    "metric": "NORMALIZED_EPS",
                    "low": 3.5,
                    "high": 4.5,
                    "due_date": "20260817",
                    "required_tier": "E1",
                    "source_ref": "issuer settled results",
                    "measurement_period": "FY2026_H1",
                }
            ],
            "calibrated": False,
        },
        "smc": {
            "method_version": "manual-smc-v1",
            "status": "PASS",
            "evidence_as_of": "20260813",
            "higher_timeframe_structure": "RECOVERY",
            "setup_type": "SWEEP_RECLAIM",
            "liquidity_reference": "20260812 sell-side liquidity sweep",
            "poi_type": "DEMAND_ORDER_BLOCK",
            "poi_zone": {"low": 96.0, "high": 99.0},
            "range_location": "DISCOUNT",
            "volume_state": "CONFIRMED",
            "flow_state": "SETTLED_INFLOW_CONFIRMED",
            "sector_state": "CONFIRMED",
            "entry_zone": {"low": 99.0, "high": 101.0},
            "entry_trigger": 100.0,
            "structure_invalidation": 97.0,
            "atr14": 1.0,
            "atr_buffer_multiple": 2.0,
            "structure_stop": 95.0,
            "target_1": 115.0,
            "target_2": 150.0,
            "thesis_line_hash": funnel._hash(wrong_if),
            "disaster_line": 90.0,
            "source": "MANUAL_SMC_E3_SETTLED",
            "evidence_hash": "a" * 64,
            "calibrated": False,
            "no_trade_flag": True,
            "production_authority": False,
        },
        "method_status": "MANUAL_UNVALIDATED",
        "no_trade_flag": True,
        "production_authority": False,
        "disclaimer": method.DISCLAIMER,
    }
    return draft, core, timing, pack


def valid_registration() -> dict:
    draft, core, timing, pack = registration_draft()
    return method.seal_registration(
        draft, thesis_core=core, timing_ticket=timing, decision_pack=pack
    )


def outcome_draft(registration: dict, *, thesis_wrong: bool = False) -> dict:
    facts = [
        {
            "claim_id": "CATALYST_H1",
            "measurement_period": "FY2026_H1_RELEASE",
            "observed_at": "20260817",
            "actual": True,
            "evidence_tier": "E1",
            "source_ref": "issuer filing calendar",
            "evidence_hash": "1" * 64,
            "verification_status": "MANUAL_EVIDENCE_BOUND_UNVERIFIED_IDENTITY",
        },
        {
            "claim_id": "FUND_NORMALIZED_EPS",
            "measurement_period": "FY2026_H1",
            "observed_at": "20260817",
            "actual": 4.0,
            "evidence_tier": "E1",
            "source_ref": "issuer settled results",
            "evidence_hash": "2" * 64,
            "verification_status": "MANUAL_EVIDENCE_BOUND_UNVERIFIED_IDENTITY",
        },
        {
            "claim_id": "INVALID_GM",
            "measurement_period": "FY2026_H1",
            "observed_at": "20260817",
            "actual": 15.0 if thesis_wrong else 17.5,
            "evidence_tier": "E1",
            "source_ref": "issuer settled results",
            "evidence_hash": "3" * 64,
            "verification_status": "MANUAL_EVIDENCE_BOUND_UNVERIFIED_IDENTITY",
        },
        {
            "claim_id": "INVALID_NP",
            "measurement_period": "FY2026_H1",
            "observed_at": "20260817",
            "actual": -20.0,
            "evidence_tier": "E1",
            "source_ref": "issuer settled results",
            "evidence_hash": "4" * 64,
            "verification_status": "MANUAL_EVIDENCE_BOUND_UNVERIFIED_IDENTITY",
        },
        {
            "claim_id": "VALUATION_NORMALIZED_EPS",
            "measurement_period": "FY2026_H1",
            "observed_at": "20260817",
            "actual": 4.0,
            "evidence_tier": "E1",
            "source_ref": "issuer settled results",
            "evidence_hash": "5" * 64,
            "verification_status": "MANUAL_EVIDENCE_BOUND_UNVERIFIED_IDENTITY",
        },
    ]
    return {
        "schema": method.OUTCOME_SCHEMA,
        "schema_version": method.SCHEMA_VERSION,
        "ticker": registration["ticker"],
        "registration_hash": registration["registration_hash"],
        "generated_at": "2026-08-17T16:05:00+00:00",
        "scoring_as_of": "20260817",
        "facts": facts,
        "facts_hash": funnel._hash(facts),
        "production_authority": False,
        "disclaimer": method.DISCLAIMER,
    }


def closed_order(*, exit_reason: str = "target", pnl_cny: float = 22500.0) -> dict:
    return {
        "entry_review_price": 100.0,
        "stop_reference": 95.0,
        "take_profit_reference": 115.0,
        "no_trade_flag": True,
        "status": "closed",
        "fill_date": "20260814",
        "fill_price": 100.0,
        "exit_date": "20260817",
        "exit_reason": exit_reason,
        "paper_return": 0.15 if pnl_cny > 0 else -0.05,
        "realized_R": 3.0 if pnl_cny > 0 else -1.0,
        "pnl_cny": pnl_cny,
        "risk_budget_cny": 10000.0,
        "notional": 150000.0,
    }


def settled_bars() -> list[dict]:
    return [
        {"date": "20260814", "open": 99.0, "high": 102.0, "low": 98.0, "close": 101.0},
        {"date": "20260817", "open": 110.0, "high": 116.0, "low": 108.0, "close": 115.0},
    ]


class ResearchMethodTests(unittest.TestCase):
    def test_semiconductor_registration_binds_thesis_valuation_smc_and_levels(self) -> None:
        registration = valid_registration()
        self.assertEqual(registration["valuation"]["model_output"]["computed_base_low"], 95.0)
        self.assertEqual(registration["smc"]["structure_stop"], 95.0)
        self.assertFalse(registration["production_authority"])

    def test_wrong_if_coverage_is_exact_not_a_count(self) -> None:
        draft, core, timing, pack = registration_draft()
        draft["thesis_expectations"][3]["wrong_if_trigger_hash"] = draft["thesis_expectations"][2]["wrong_if_trigger_hash"]
        with self.assertRaisesRegex(method.MethodError, "exactly cover"):
            method.seal_registration(
                draft, thesis_core=core, timing_ticket=timing, decision_pack=pack
            )

    def test_wrong_if_trigger_maps_to_only_one_invalidation_claim(self) -> None:
        draft, core, timing, pack = registration_draft()
        duplicate = copy.deepcopy(draft["thesis_expectations"][2])
        duplicate["claim_id"] = "INVALID_GM_CONFLICTING_DUPLICATE"
        duplicate["threshold"] = 25.0
        draft["thesis_expectations"].append(duplicate)
        with self.assertRaisesRegex(method.MethodError, "exactly one invalidation"):
            method.seal_registration(
                draft, thesis_core=core, timing_ticket=timing, decision_pack=pack
            )

    def test_semiconductor_valuation_must_be_derived_from_inputs(self) -> None:
        draft, core, timing, pack = registration_draft()
        draft["valuation"]["model_output"]["computed_base_low"] = 94.0
        with self.assertRaisesRegex(method.MethodError, "not derived"):
            method.seal_registration(
                draft, thesis_core=core, timing_ticket=timing, decision_pack=pack
            )

    def test_innovative_drug_adapter_uses_rnpv_inputs(self) -> None:
        draft, core, timing, pack = registration_draft()
        core["valuation_target_range"]["base"].update({"low": 81.0, "high": 99.0})
        draft["thesis_core_hash"] = funnel._hash(core)
        draft["valuation"].update({
            "adapter": "INNOVATIVE_DRUG_RNPV",
            "industry": "INNOVATIVE_DRUG",
            "scenario_band_hash": funnel._hash(core["valuation_target_range"]),
            "paper_exit_reference": 95.0,
            "model_inputs": {
                "net_cash_per_share": 10.0,
                "pipeline_rnpv_per_share": 60.0,
                "commercial_value_per_share": 30.0,
                "dilution_haircut_pct": 0.10,
            },
            "model_output": {
                "computed_base_low": 81.0,
                "computed_base_high": 99.0,
                "calculation_status": "MANUAL_UNVALIDATED",
            },
        })
        draft["valuation"]["forecasts"] = [
            {
                "forecast_id": "VALUATION_PIPELINE_RNPV",
                "metric": "PIPELINE_RNPV_PER_SHARE",
                "low": 50.0,
                "high": 70.0,
                "due_date": "20260817",
                "required_tier": "E2",
                "source_ref": "registered pipeline rNPV evidence",
                "measurement_period": "FY2026_H1",
            }
        ]
        registration = method.seal_registration(
            draft, thesis_core=core, timing_ticket=timing, decision_pack=pack
        )
        self.assertEqual(registration["valuation"]["adapter"], "INNOVATIVE_DRUG_RNPV")

    def test_valuation_forecasts_cover_the_load_bearing_adapter_input(self) -> None:
        draft, core, timing, pack = registration_draft()
        draft["valuation"]["forecasts"][0]["metric"] = "REVENUE"
        with self.assertRaisesRegex(method.MethodError, "load-bearing adapter input"):
            method.seal_registration(
                draft, thesis_core=core, timing_ticket=timing, decision_pack=pack
            )

    def test_smc_pass_requires_all_manual_confirmation_evidence(self) -> None:
        draft, core, timing, pack = registration_draft()
        draft["smc"]["flow_state"] = "DATA_BLOCKED"
        with self.assertRaisesRegex(method.MethodError, "PASS lacks"):
            method.seal_registration(
                draft, thesis_core=core, timing_ticket=timing, decision_pack=pack
            )

    def test_smc_stop_is_derived_and_dual_ticket_levels_cannot_drift(self) -> None:
        draft, core, timing, pack = registration_draft()
        draft["smc"]["structure_stop"] = 94.0
        timing["stop_reference"] = 94.0
        pack["paper_plan"]["stop_reference"] = 94.0
        draft["timing_ticket_hash"] = funnel._hash(timing)
        draft["decision_pack_hash"] = funnel._hash(pack)
        with self.assertRaisesRegex(method.MethodError, "not derived"):
            method.seal_registration(
                draft, thesis_core=core, timing_ticket=timing, decision_pack=pack
            )

    def test_smc_levels_must_bind_both_timing_ticket_and_decision_pack(self) -> None:
        draft, core, timing, pack = registration_draft()
        timing["entry_review"] = 100.5
        draft["timing_ticket_hash"] = funnel._hash(timing)
        with self.assertRaisesRegex(method.MethodError, "not derived from SMC"):
            method.seal_registration(
                draft, thesis_core=core, timing_ticket=timing, decision_pack=pack
            )

    def test_smc_entry_zone_must_overlap_registered_point_of_interest(self) -> None:
        draft, core, timing, pack = registration_draft()
        draft["smc"]["poi_zone"] = {"low": 90.0, "high": 94.0}
        with self.assertRaisesRegex(method.MethodError, "does not overlap"):
            method.seal_registration(
                draft, thesis_core=core, timing_ticket=timing, decision_pack=pack
            )

    def test_smc_and_timing_ticket_must_share_settled_confirmation_evidence(self) -> None:
        draft, core, timing, pack = registration_draft()
        timing["sector_state"] = "NOT_CONFIRMED"
        draft["timing_ticket_hash"] = funnel._hash(timing)
        with self.assertRaisesRegex(method.MethodError, "evidence disagree"):
            method.seal_registration(
                draft, thesis_core=core, timing_ticket=timing, decision_pack=pack
            )

    def test_registration_hash_covers_every_method_input(self) -> None:
        registration = valid_registration()
        registration["smc"]["target_2"] = 151.0
        core, timing, pack = method_inputs()
        with self.assertRaisesRegex(method.MethodError, "hash mismatch"):
            method.validate_registration(
                registration, thesis_core=core, timing_ticket=timing, decision_pack=pack
            )

    def test_outcomes_reject_backdating_and_weak_evidence(self) -> None:
        registration = valid_registration()
        draft = outcome_draft(registration)
        draft["facts"][0]["observed_at"] = "20260812"
        draft["facts_hash"] = funnel._hash(draft["facts"])
        with self.assertRaisesRegex(method.MethodError, "chronology"):
            method.seal_outcomes(draft, registration)
        draft = outcome_draft(registration)
        draft["facts"][0]["evidence_tier"] = "E3"
        draft["facts_hash"] = funnel._hash(draft["facts"])
        outcomes = method.seal_outcomes(draft, registration)
        scorecard = method.build_scorecard(
            registration, outcomes, order=closed_order(), bars=settled_bars(),
            fund_snapshot={"fund": {"initial_capital": 1_000_000.0}},
            generated_at="2026-08-17T16:10:00+00:00",
        )
        self.assertEqual(scorecard["thesis"]["status"], "DATA_BLOCKED")

    def test_outcome_chronology_normalizes_registered_date(self) -> None:
        draft, core, timing, pack = registration_draft()
        draft["registered_at"] = "2026-08-13"
        registration = method.seal_registration(
            draft, thesis_core=core, timing_ticket=timing, decision_pack=pack
        )
        outcomes = outcome_draft(registration)
        outcomes["facts"][0]["observed_at"] = "20260812"
        outcomes["facts_hash"] = funnel._hash(outcomes["facts"])
        with self.assertRaisesRegex(method.MethodError, "chronology"):
            method.seal_outcomes(outcomes, registration)

    def test_outcomes_bind_each_fact_to_registered_period_and_source(self) -> None:
        registration = valid_registration()
        draft = outcome_draft(registration)
        draft["facts"][0]["measurement_period"] = "FY2025_H1_RELEASE"
        draft["facts_hash"] = funnel._hash(draft["facts"])
        with self.assertRaisesRegex(method.MethodError, "registered period/source"):
            method.seal_outcomes(draft, registration)

        draft = outcome_draft(registration)
        draft["facts"][0]["source_ref"] = "different filing source"
        draft["facts_hash"] = funnel._hash(draft["facts"])
        with self.assertRaisesRegex(method.MethodError, "registered period/source"):
            method.seal_outcomes(draft, registration)

    def test_outcome_hash_covers_every_later_fact(self) -> None:
        registration = valid_registration()
        outcomes = method.seal_outcomes(outcome_draft(registration), registration)
        outcomes["facts"][0]["actual"] = False
        with self.assertRaisesRegex(method.MethodError, "outcomes hash mismatch"):
            method.validate_outcomes(outcomes, registration)

    def test_machine_attribution_separates_thesis_timing_and_pnl(self) -> None:
        registration = valid_registration()
        right = method.seal_outcomes(outcome_draft(registration), registration)
        stopped = closed_order(exit_reason="stop", pnl_cny=-7500.0)
        scorecard = method.build_scorecard(
            registration, right, order=stopped, bars=settled_bars(),
            fund_snapshot={"fund": {"initial_capital": 1_000_000.0}},
            generated_at="2026-08-17T16:10:00+00:00",
        )
        self.assertEqual(scorecard["machine_attribution"], "THESIS_RIGHT_TIMING_WRONG")
        self.assertEqual(scorecard["pnl"]["status"], "LOSS")

        wrong = method.seal_outcomes(outcome_draft(registration, thesis_wrong=True), registration)
        scorecard = method.build_scorecard(
            registration, wrong, order=closed_order(), bars=settled_bars(),
            fund_snapshot={"fund": {"initial_capital": 1_000_000.0}},
            generated_at="2026-08-17T16:10:00+00:00",
        )
        self.assertEqual(scorecard["machine_attribution"], "THESIS_WRONG_TIMING_RIGHT")
        self.assertEqual(scorecard["pnl"]["status"], "PROFIT")

    def test_scorecard_tampering_and_authority_injection_are_rejected(self) -> None:
        registration = valid_registration()
        outcomes = method.seal_outcomes(outcome_draft(registration), registration)
        scorecard = method.build_scorecard(
            registration, outcomes, order=closed_order(), bars=settled_bars(),
            fund_snapshot={"fund": {"initial_capital": 1_000_000.0}},
            generated_at="2026-08-17T16:10:00+00:00",
        )
        tampered = copy.deepcopy(scorecard)
        tampered["machine_attribution"] = "THESIS_WRONG_TIMING_WRONG"
        tampered["scorecard_hash"] = funnel._hash(
            {key: value for key, value in tampered.items() if key != "scorecard_hash"}
        )
        with self.assertRaisesRegex(method.MethodError, "not derived"):
            method.validate_scorecard(tampered, registration, outcomes)

        draft, core, timing, pack = registration_draft()
        draft["valuation"]["formal_blocking_authority"] = True
        with self.assertRaisesRegex(method.MethodError, "fields are not exact|authority"):
            method.seal_registration(
                draft, thesis_core=core, timing_ticket=timing, decision_pack=pack
            )

    def test_scorecard_cannot_predate_outcome_evidence(self) -> None:
        registration = valid_registration()
        outcomes = method.seal_outcomes(outcome_draft(registration), registration)
        with self.assertRaisesRegex(method.MethodError, "predates"):
            method.build_scorecard(
                registration, outcomes, order=closed_order(), bars=settled_bars(),
                fund_snapshot={"fund": {"initial_capital": 1_000_000.0}},
                generated_at="2026-08-17T16:04:59+00:00",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
