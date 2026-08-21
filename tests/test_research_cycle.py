#!/usr/bin/env python3
"""End-to-end regressions for the offline U4-to-paper research cycle."""

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
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import closure_experiment as closure  # noqa: E402
import decision_pack as decision_pack_contract  # noqa: E402
import decision_sheet as decision_sheet_contract  # noqa: E402
import funnel_pipeline as funnel  # noqa: E402
import research_cycle as cycle  # noqa: E402
import research_method as method  # noqa: E402
import test_research_closure_experiment as closure_fixtures  # noqa: E402
import test_research_method as method_fixtures  # noqa: E402


def build_closure_bundle(root: Path) -> tuple[Path, list[str], dict, dict, dict]:
    source_bundle, battery, codes = closure_fixtures.build_bundle(root)
    packet = closure.build_review_packet(
        bundle_dir=source_bundle,
        battery=battery,
        generated_at=closure_fixtures.GENERATED_AT,
    )
    receipt = closure_fixtures.receipt_for(packet, codes[:3])
    queue, report = closure.run_offline_replay(
        bundle_dir=source_bundle,
        battery=battery,
        packet=packet,
        receipt=receipt,
        generated_at="2026-08-13T10:06:00+00:00",
    )
    output = root / "closure-result"
    closure._write_replay_outputs(
        output, source_bundle, battery, packet, receipt, queue, report,
    )
    return output, codes[:3], packet, receipt, queue


def build_case_draft(closure_bundle: Path, ticker: str) -> dict:
    closure_manifest = json.loads((closure_bundle / "manifest.json").read_text())
    receipt = json.loads((closure_bundle / "review_receipt.json").read_text())
    queue = json.loads((closure_bundle / "deep_research_queue.json").read_text())
    core = decision_sheet_contract._valid_core()
    core["identity"]["ticker"] = ticker
    core["identity"]["name"] = {"zh": "闭环样本", "en": "Closure Fixture"}
    core["identity"]["as_of"] = "2026-08-11"
    core_hash = funnel._hash(core)
    pack = decision_pack_contract._complete_pack()
    pack["execution_gate"]["posture"] = "RECLAIM_REVIEW"
    pack["paper_plan"] = {
        "entry_review": 100.0,
        "stop_reference": 95.0,
        "take_profit_reference": 115.0,
        "invalidation": 94.9,
        "no_trade_flag": True,
    }
    cluster = {
        "cluster_id": f"CL-{ticker.replace('.', '-')}-20260813",
        "cluster_reason": "One disclosure-bound demand mechanism.",
        "invalidating_fact": "Issuer disclosure contradicts the demand mechanism.",
        "rule_version": "offline-cycle-v1",
        "registered_at": "20260813",
        "retrospective": False,
        "counting_eligible": False,
    }
    cluster["object_hash"] = funnel._hash(cluster)
    draft = {
        "schema": cycle.CASE_SCHEMA,
        "schema_version": cycle.SCHEMA_VERSION,
        "generated_at": "2026-08-13T10:10:00+00:00",
        "ticker": ticker,
        "name": "闭环样本",
        "theme": "闭环行业",
        "industry_code": "SEMICONDUCTOR",
        "source_refs": {
            "closure_bundle_hash": closure_manifest["bundle_hash"],
            "u4_receipt_hash": receipt["receipt_hash"],
            "u4_rows_hash": queue["rows_hash"],
        },
        "factpack": {
            "status": "COMPLETE",
            "as_of": "20260811",
            "items": [
                {
                    "claim": "Issuer disclosed the load-bearing operating metric.",
                    "evidence_tier": "E1",
                    "source": "issuer filing line 42",
                    "source_date": "20260811",
                    "causal_tag": "PROVEN",
                    "validated": True,
                },
                {
                    "claim": "The market may be discounting a slower recovery.",
                    "evidence_tier": "E2",
                    "source": "analyst inference bound to the filing",
                    "source_date": "20260811",
                    "causal_tag": "INFERRED",
                    "validated": True,
                },
            ],
        },
        "thesis_core": core,
        "red_team": {
            "verdict": "PASS",
            "core_hash": core_hash,
            "claimed_reviewer": "Junyan",
            "identity_verification": "UNAVAILABLE",
            "production_authority": False,
            "reviewed_at": "2026-08-13T10:07:00+00:00",
            "axes": {name: 80 for name in cycle.RED_TEAM_AXES},
        },
        "thesis_ticket": {
            "status": "PASS",
            "core_hash": core_hash,
            "stance": "STARTER_CANDIDATE",
            "reward_to_risk": 3.0,
            "wrong_if_hash": funnel._hash(core["wrong_if"]["triggers"]),
            "u4_receipt_hash": receipt["receipt_hash"],
            "no_trade_flag": True,
            "production_authority": False,
        },
        "timing_ticket": {
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
        },
        "decision_pack": pack,
        "causal_cluster": cluster,
        "paper_order": {
            "registered_at": "20260813",
            "risk_pct": 0.01,
            "setup": "RECLAIM",
            "reason": "Offline fixture for the evidence-bound paper cycle.",
            "invalid_if": "Issuer evidence invalidates the mechanism.",
            "gate_state": "RECLAIM_REVIEW",
        },
        "no_trade_flag": True,
        "production_authority": False,
        "disclaimer": cycle.DISCLAIMER,
    }
    registration_draft, _, _, _ = method_fixtures.registration_draft()
    registration_draft["ticker"] = ticker
    registration_draft["as_of"] = "20260811"
    registration_draft["thesis_core_hash"] = funnel._hash(core)
    registration_draft["timing_ticket_hash"] = funnel._hash(draft["timing_ticket"])
    registration_draft["decision_pack_hash"] = funnel._hash(pack)
    wrong_if = core["wrong_if"]["triggers"]
    registration_draft["wrong_if_hash"] = funnel._hash(wrong_if)
    registration_draft["thesis_expectations"][2]["wrong_if_trigger_hash"] = funnel._hash(wrong_if[0])
    registration_draft["thesis_expectations"][3]["wrong_if_trigger_hash"] = funnel._hash(wrong_if[1])
    registration_draft["valuation"]["scenario_band_hash"] = funnel._hash(
        core["valuation_target_range"]
    )
    registration_draft["smc"]["thesis_line_hash"] = funnel._hash(wrong_if)
    draft["method_registration"] = method.seal_registration(
        registration_draft, thesis_core=core, timing_ticket=draft["timing_ticket"],
        decision_pack=pack,
    )
    return draft


def execution_row(
    date: str, open_: float, high: float, low: float, close: float,
    *, pre_close: float | None = None, volume_shares: float = 10_000_000.0,
    amount_cny: float = 1_000_000_000.0, suspended: bool = False,
) -> dict:
    reference = float(pre_close if pre_close is not None else open_)
    return {
        "date": date, "open": open_, "high": high, "low": low, "close": close,
        "pre_close": reference,
        "up_limit": round(reference * 1.2, 4),
        "down_limit": round(reference * 0.8, 4),
        "volume_shares": volume_shares, "amount_cny": amount_cny,
        "suspended": suspended, "settled": True,
        "price_basis": "RAW_UNADJUSTED",
        "source": "OFFLINE_FIXTURE_SETTLED_V2",
    }


def build_bar_draft(ticker: str) -> dict:
    return {
        "schema": cycle.BARS_SCHEMA,
        "schema_version": cycle.SCHEMA_VERSION,
        "ticker": ticker,
        "source": "OFFLINE_FIXTURE_SETTLED",
        "generated_at": "2026-08-17T16:00:00+00:00",
        "rows": [
            execution_row("20260813", 98.0, 101.0, 97.0, 100.0),
            execution_row("20260814", 99.0, 102.0, 98.0, 101.0, pre_close=100.0),
            execution_row("20260817", 110.0, 116.0, 108.0, 115.0, pre_close=101.0),
        ],
        "production_authority": False,
    }


def build_replay(root: Path):
    closure_bundle, codes, _, _, _ = build_closure_bundle(root)
    case = cycle.seal_case(build_case_draft(closure_bundle, codes[0]), closure_bundle)
    bars = cycle.seal_bars(build_bar_draft(codes[0]), case)
    outcomes = method.seal_outcomes(
        method_fixtures.outcome_draft(case["method_registration"]),
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
    return closure_bundle, cycle_bundle, case, bars, outcomes, outputs


def build_review_draft(trace: dict, review: dict, *, bound: bool = True) -> dict:
    return {
        "schema": cycle.REVIEW_RECEIPT_SCHEMA,
        "schema_version": cycle.SCHEMA_VERSION,
        "research_cycle_id": trace["research_cycle_id"],
        "mechanical_review_hash": review["review_hash"] if bound else "0" * 64,
        "machine_attribution": review["machine_attribution"],
        "review_disposition": "CONFIRM",
        "human_attribution": review["machine_attribution"],
        "disagreement_reason": None,
        "evidence_refs": [f"method_scorecard:{review['method_scorecard_hash']}"],
        "claimed_reviewer": "Junyan",
        "identity_verification": "UNAVAILABLE",
        "production_authority": False,
        "reviewed_at": "2026-08-17T16:20:00+00:00",
        "authorization_text": (
            f"批准离线 paper 复盘，绑定 review_hash {review['review_hash'][:12]}，"
            "不产生生产权限。"
        ),
        "lessons": ["全链证据和机器归因已复核。"],
        "rule_change_proposals": [],
        "disclaimer": cycle.DISCLAIMER,
    }


class ResearchCycleTests(unittest.TestCase):
    def test_cli_runs_the_entire_u4_to_reviewed_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, codes, _, _, _ = build_closure_bundle(root)
            case_draft = root / "case-draft.json"
            case_path = root / "case.json"
            bars_draft = root / "bars-draft.json"
            bars_path = root / "bars.json"
            outcomes_draft = root / "outcomes-draft.json"
            outcomes_path = root / "outcomes.json"
            cycle_bundle = root / "cycle"
            postmortem_draft = root / "postmortem-draft.json"
            postmortem = root / "postmortem.json"
            reviewed_bundle = root / "reviewed"
            case_payload = build_case_draft(closure_bundle, codes[0])
            closure_fixtures.write_json(case_draft, case_payload)
            closure_fixtures.write_json(bars_draft, build_bar_draft(codes[0]))
            closure_fixtures.write_json(
                outcomes_draft,
                method_fixtures.outcome_draft(case_payload["method_registration"]),
            )
            script = ROOT / "experiments" / "research_funnel" / "research_cycle.py"
            env = {**os.environ, "AR_OFFLINE": "1", "PYTHONPYCACHEPREFIX": str(root / "pycache")}

            commands = [
                [sys.executable, str(script), "seal-case", "--closure-bundle", str(closure_bundle), "--input", str(case_draft), "--output", str(case_path)],
                [sys.executable, str(script), "seal-bars", "--closure-bundle", str(closure_bundle), "--case", str(case_path), "--input", str(bars_draft), "--output", str(bars_path)],
                [sys.executable, str(script), "seal-outcomes", "--closure-bundle", str(closure_bundle), "--case", str(case_path), "--input", str(outcomes_draft), "--output", str(outcomes_path)],
                [sys.executable, str(script), "replay", "--closure-bundle", str(closure_bundle), "--case", str(case_path), "--bars", str(bars_path), "--outcomes", str(outcomes_path), "--generated-at", "2026-08-17T16:10:00+00:00", "--output-dir", str(cycle_bundle)],
                [sys.executable, str(script), "verify", "--closure-bundle", str(closure_bundle), "--output-dir", str(cycle_bundle)],
            ]
            for command in commands:
                completed = subprocess.run(command, env=env, text=True, capture_output=True)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

            original_case = case_path.read_bytes()
            repeated = subprocess.run(commands[0], env=env, text=True, capture_output=True)
            self.assertEqual(repeated.returncode, 1, repeated.stdout + repeated.stderr)
            self.assertIn("refusing overwrite", repeated.stdout)
            self.assertEqual(case_path.read_bytes(), original_case)

            trace = json.loads((cycle_bundle / "cycle_trace.json").read_text())
            review = json.loads((cycle_bundle / "mechanical_review.json").read_text())
            closure_fixtures.write_json(postmortem_draft, build_review_draft(trace, review))
            final_commands = [
                [sys.executable, str(script), "seal-review", "--cycle-bundle", str(cycle_bundle), "--input", str(postmortem_draft), "--output", str(postmortem)],
                [sys.executable, str(script), "finalize-review", "--closure-bundle", str(closure_bundle), "--cycle-bundle", str(cycle_bundle), "--receipt", str(postmortem), "--output-dir", str(reviewed_bundle)],
                [sys.executable, str(script), "verify-final", "--closure-bundle", str(closure_bundle), "--cycle-bundle", str(cycle_bundle), "--output-dir", str(reviewed_bundle)],
            ]
            for command in final_commands:
                completed = subprocess.run(command, env=env, text=True, capture_output=True)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            final = json.loads((reviewed_bundle / "reviewed_cycle.json").read_text())
            self.assertEqual(final["status"], "REVIEWED")
            self.assertFalse(final["claim_allowed"])
            self.assertFalse(final["production_authority"])

    def test_full_cycle_uses_t1_fill_and_reaches_reviewed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, cycle_bundle, _, _, _, (trace, fund, scorecard, review) = build_replay(root)
            verified = cycle.verify_cycle_bundle(cycle_bundle, closure_bundle)
            order = fund["orders"][0]
            self.assertEqual(trace["final_state"], "REVIEW_READY")
            self.assertEqual(order["fill_date"], "20260814")
            self.assertEqual(order["exit_date"], "20260817")
            self.assertEqual(order["exit_reason"], "target")
            self.assertFalse(fund["performance"]["claim_allowed"])
            self.assertEqual(verified["status"], "VERIFIED")

            self.assertEqual(scorecard["machine_attribution"], "THESIS_RIGHT_TIMING_RIGHT")
            draft = build_review_draft(trace, review)
            receipt = cycle.seal_review_receipt(draft, review)
            final = cycle.finalize_review(cycle_bundle, closure_bundle, receipt)
            final_bundle = root / "final"
            cycle._write_final_outputs(final_bundle, cycle_bundle, closure_bundle, receipt, final)
            final_verified = cycle.verify_final_bundle(final_bundle, cycle_bundle, closure_bundle)
            self.assertEqual(final["status"], "REVIEWED")
            self.assertEqual(final_verified["status"], "VERIFIED_REVIEWED")

    def test_case_hash_must_cover_every_prospective_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure_bundle, codes, _, _, _ = build_closure_bundle(Path(tmp))
            case = cycle.seal_case(build_case_draft(closure_bundle, codes[0]), closure_bundle)
            case["theme"] = "rewritten after sealing"
            with self.assertRaisesRegex(cycle.CycleError, "case hash mismatch"):
                cycle.validate_case(case, closure_bundle)

    def test_case_industry_must_match_registered_valuation_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure_bundle, codes, _, _, _ = build_closure_bundle(Path(tmp))
            draft = build_case_draft(closure_bundle, codes[0])
            draft["industry_code"] = "INNOVATIVE_DRUG"
            with self.assertRaisesRegex(cycle.CycleError, "valuation industry differs"):
                cycle.seal_case(draft, closure_bundle)

    def test_case_must_bind_exact_u4_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure_bundle, codes, _, _, _ = build_closure_bundle(Path(tmp))
            draft = build_case_draft(closure_bundle, codes[0])
            draft["source_refs"]["u4_rows_hash"] = "0" * 64
            with self.assertRaisesRegex(cycle.CycleError, "exact U4 evidence"):
                cycle.seal_case(draft, closure_bundle)

    def test_case_ticker_must_be_selected_in_u4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure_bundle, codes, _, _, _ = build_closure_bundle(Path(tmp))
            draft = build_case_draft(closure_bundle, codes[0])
            draft["ticker"] = "999999.SZ"
            draft["thesis_core"]["identity"]["ticker"] = "999999.SZ"
            with self.assertRaisesRegex(cycle.CycleError, "not in the reviewed U4 queue"):
                cycle.seal_case(draft, closure_bundle)

    def test_factpack_without_e1_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure_bundle, codes, _, _, _ = build_closure_bundle(Path(tmp))
            draft = build_case_draft(closure_bundle, codes[0])
            draft["factpack"]["items"][0]["evidence_tier"] = "E2"
            with self.assertRaisesRegex(cycle.CycleError, "lacks load-bearing E1"):
                cycle.seal_case(draft, closure_bundle)

    def test_unqualified_thesis_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure_bundle, codes, _, _, _ = build_closure_bundle(Path(tmp))
            draft = build_case_draft(closure_bundle, codes[0])
            del draft["thesis_core"]["wrong_if"]["triggers"][0]["threshold"]
            with self.assertRaisesRegex(cycle.CycleError, "thesis core is not qualified"):
                cycle.seal_case(draft, closure_bundle)

    def test_red_team_must_bind_exact_core(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure_bundle, codes, _, _, _ = build_closure_bundle(Path(tmp))
            draft = build_case_draft(closure_bundle, codes[0])
            draft["red_team"]["core_hash"] = "0" * 64
            with self.assertRaisesRegex(cycle.CycleError, "red-team PASS"):
                cycle.seal_case(draft, closure_bundle)

    def test_dual_ticket_levels_cannot_diverge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure_bundle, codes, _, _, _ = build_closure_bundle(Path(tmp))
            draft = build_case_draft(closure_bundle, codes[0])
            draft["timing_ticket"]["entry_review"] = 101.0
            with self.assertRaisesRegex(cycle.CycleError, "levels are not identical"):
                cycle.seal_case(draft, closure_bundle)

    def test_pass_timing_ticket_requires_all_five_evidence_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure_bundle, codes, _, _, _ = build_closure_bundle(Path(tmp))
            draft = build_case_draft(closure_bundle, codes[0])
            draft["timing_ticket"]["sector_state"] = "DATA_BLOCKED"
            with self.assertRaisesRegex(cycle.CycleError, "lacks settled market"):
                cycle.seal_case(draft, closure_bundle)

    def test_paper_risk_budget_is_not_silently_clamped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure_bundle, codes, _, _, _ = build_closure_bundle(Path(tmp))
            draft = build_case_draft(closure_bundle, codes[0])
            draft["paper_order"]["risk_pct"] = 0.50
            with self.assertRaisesRegex(cycle.CycleError, "not bound to the timing ticket"):
                cycle.seal_case(draft, closure_bundle)

    def test_wait_timing_ticket_ends_honestly_at_no_trade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, codes, _, _, _ = build_closure_bundle(root)
            draft = build_case_draft(closure_bundle, codes[0])
            draft["timing_ticket"]["status"] = "WAIT"
            draft["timing_ticket"]["posture"] = "HOLD_OBSERVE"
            draft["decision_pack"]["execution_gate"]["posture"] = "HOLD_OBSERVE"
            draft["paper_order"]["gate_state"] = "HOLD_OBSERVE"
            registration_draft, core, _, _ = method_fixtures.registration_draft()
            registration_draft["ticker"] = draft["ticker"]
            registration_draft["thesis_core_hash"] = funnel._hash(draft["thesis_core"])
            registration_draft["timing_ticket_hash"] = funnel._hash(draft["timing_ticket"])
            registration_draft["decision_pack_hash"] = funnel._hash(draft["decision_pack"])
            registration_draft["valuation"]["scenario_band_hash"] = funnel._hash(
                draft["thesis_core"]["valuation_target_range"]
            )
            registration_draft["smc"]["status"] = "WAIT"
            draft["method_registration"] = method.seal_registration(
                registration_draft, thesis_core=draft["thesis_core"],
                timing_ticket=draft["timing_ticket"], decision_pack=draft["decision_pack"],
            )
            case = cycle.seal_case(draft, closure_bundle)
            bars = cycle.seal_bars(build_bar_draft(codes[0]), case)
            outcomes = method.seal_outcomes(
                method_fixtures.outcome_draft(case["method_registration"]),
                case["method_registration"],
            )
            trace, fund, scorecard, review = cycle.run_cycle(
                bundle_dir=closure_bundle, case=case, bars=bars,
                outcomes=outcomes,
                generated_at="2026-08-17T16:10:00+00:00",
            )
            self.assertEqual(trace["final_state"], "NO_TRADE")
            self.assertEqual(fund["orders"], [])
            self.assertEqual(review["paper_state"], "NO_TRADE")
            receipt = cycle.seal_review_receipt(build_review_draft(trace, review), review)
            self.assertEqual(receipt["research_cycle_id"], trace["research_cycle_id"])
            self.assertEqual(scorecard["timing"]["status"], "NO_TRADE")

    def test_fill_day_cannot_exit_under_a_share_t1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, codes, _, _, _ = build_closure_bundle(root)
            case = cycle.seal_case(build_case_draft(closure_bundle, codes[0]), closure_bundle)
            draft = build_bar_draft(codes[0])
            draft["rows"] = draft["rows"][:2]
            draft["rows"][1] = execution_row(
                "20260814", 99.0, 116.0, 94.0, 100.0, pre_close=100.0,
            )
            draft["generated_at"] = "2026-08-14T16:00:00+00:00"
            bars = cycle.seal_bars(draft, case)
            outcomes_draft = method_fixtures.outcome_draft(case["method_registration"])
            outcomes_draft["generated_at"] = "2026-08-14T16:00:00+00:00"
            outcomes_draft["scoring_as_of"] = "20260814"
            for fact in outcomes_draft["facts"]:
                fact["observed_at"] = "20260814"
            outcomes_draft["facts_hash"] = funnel._hash(outcomes_draft["facts"])
            outcomes = method.seal_outcomes(outcomes_draft, case["method_registration"])
            _, fund, scorecard, review = cycle.run_cycle(
                bundle_dir=closure_bundle, case=case, bars=bars,
                outcomes=outcomes,
                generated_at="2026-08-14T16:10:00+00:00",
            )
            order = fund["orders"][0]
            self.assertEqual(order["fill_date"], "20260814")
            self.assertEqual(order["status"], "filled")
            self.assertIsNone(order["exit_date"])
            self.assertEqual(review["paper_state"], "FILLED")
            self.assertEqual(scorecard["timing"]["status"], "UNRESOLVED")

    def test_later_same_bar_stop_and_target_uses_conservative_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, codes, _, _, _ = build_closure_bundle(root)
            case = cycle.seal_case(build_case_draft(closure_bundle, codes[0]), closure_bundle)
            draft = build_bar_draft(codes[0])
            draft["rows"][2] = execution_row(
                "20260817", 99.0, 116.0, 94.0, 100.0, pre_close=101.0,
            )
            bars = cycle.seal_bars(draft, case)
            outcomes = method.seal_outcomes(
                method_fixtures.outcome_draft(case["method_registration"]),
                case["method_registration"],
            )
            _, fund, scorecard, review = cycle.run_cycle(
                bundle_dir=closure_bundle, case=case, bars=bars,
                outcomes=outcomes, generated_at="2026-08-17T16:10:00+00:00",
            )
            order = fund["orders"][0]
            self.assertEqual(order["fill_date"], "20260814")
            self.assertEqual(order["exit_reason"], "stop_and_target_same_bar->stop")
            self.assertLess(order["exit_price"], 95.0)
            self.assertEqual(scorecard["machine_attribution"], "THESIS_RIGHT_TIMING_WRONG")
            self.assertEqual(review["paper_state"], "REVIEW_READY")

    def test_pre_registration_settled_bar_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure_bundle, codes, _, _, _ = build_closure_bundle(Path(tmp))
            case = cycle.seal_case(build_case_draft(closure_bundle, codes[0]), closure_bundle)
            draft = build_bar_draft(codes[0])
            draft["rows"][0]["date"] = "20260812"
            with self.assertRaisesRegex(cycle.CycleError, "pre-registration"):
                cycle.seal_bars(draft, case)

    def test_bar_session_after_generated_at_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure_bundle, codes, _, _, _ = build_closure_bundle(Path(tmp))
            case = cycle.seal_case(build_case_draft(closure_bundle, codes[0]), closure_bundle)
            draft = build_bar_draft(codes[0])
            draft["rows"][-1]["date"] = "20260818"
            with self.assertRaisesRegex(cycle.CycleError, "not yet closed"):
                cycle.seal_bars(draft, case)

    def test_same_session_bar_before_close_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure_bundle, codes, _, _, _ = build_closure_bundle(Path(tmp))
            case = cycle.seal_case(build_case_draft(closure_bundle, codes[0]), closure_bundle)
            draft = build_bar_draft(codes[0])
            draft["generated_at"] = "2026-08-17T06:59:59+00:00"
            with self.assertRaisesRegex(cycle.CycleError, "not yet closed"):
                cycle.seal_bars(draft, case)

    def test_scoring_as_of_must_equal_last_settled_bar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, codes, _, _, _ = build_closure_bundle(root)
            case = cycle.seal_case(build_case_draft(closure_bundle, codes[0]), closure_bundle)
            bars_draft = build_bar_draft(codes[0])
            bars_draft["rows"].append(
                execution_row("20260818", 115.0, 118.0, 112.0, 116.0, pre_close=115.0)
            )
            bars_draft["generated_at"] = "2026-08-18T16:00:00+00:00"
            bars = cycle.seal_bars(bars_draft, case)
            outcomes_draft = method_fixtures.outcome_draft(case["method_registration"])
            outcomes_draft["generated_at"] = "2026-08-18T16:05:00+00:00"
            outcomes = method.seal_outcomes(
                outcomes_draft, case["method_registration"]
            )
            with self.assertRaisesRegex(cycle.CycleError, "one scoring as_of"):
                cycle.run_cycle(
                    bundle_dir=closure_bundle, case=case, bars=bars,
                    outcomes=outcomes, generated_at="2026-08-18T16:10:00+00:00",
                )

    def test_case_cannot_acquire_production_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure_bundle, codes, _, _, _ = build_closure_bundle(Path(tmp))
            draft = build_case_draft(closure_bundle, codes[0])
            draft["production_authority"] = True
            with self.assertRaisesRegex(cycle.CycleError, "authority boundary"):
                cycle.seal_case(draft, closure_bundle)

    def test_cycle_verifier_rejects_artifact_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, cycle_bundle, _, _, _, _ = build_replay(root)
            review_path = cycle_bundle / "mechanical_review.json"
            review = json.loads(review_path.read_text())
            review["claim_allowed"] = True
            closure_fixtures.write_json(review_path, review)
            with self.assertRaisesRegex(cycle.CycleError, "artifact hash mismatch"):
                cycle.verify_cycle_bundle(cycle_bundle, closure_bundle)

    def test_cycle_manifest_cannot_rewrite_paper_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, cycle_bundle, _, _, _, _ = build_replay(root)
            manifest_path = cycle_bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["no_trade_flag"] = False
            manifest["disclaimer"] = "rewritten"
            closure_fixtures.write_json(manifest_path, manifest)
            with self.assertRaisesRegex(cycle.CycleError, "manifest is invalid"):
                cycle.verify_cycle_bundle(cycle_bundle, closure_bundle)

    def test_cycle_verifier_rebuilds_outputs_after_self_consistent_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, cycle_bundle, _, _, _, _ = build_replay(root)
            review_path = cycle_bundle / "mechanical_review.json"
            review = json.loads(review_path.read_text())
            review["human_attribution_status"] = "REVIEWED_WITHOUT_RECEIPT"
            review["review_hash"] = funnel._hash(
                cycle._without_hash(review, "review_hash")
            )
            closure_fixtures.write_json(review_path, review)
            manifest_path = cycle_bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["artifacts"]["mechanical_review.json"] = cycle._sha256_path(review_path)
            manifest["bundle_hash"] = funnel._hash(manifest["artifacts"])
            closure_fixtures.write_json(manifest_path, manifest)
            with self.assertRaisesRegex(cycle.CycleError, "deterministic projection"):
                cycle.verify_cycle_bundle(cycle_bundle, closure_bundle)

    def test_replay_rejects_paper_engine_authority_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, codes, _, _, _ = build_closure_bundle(root)
            case = cycle.seal_case(build_case_draft(closure_bundle, codes[0]), closure_bundle)
            bars = cycle.seal_bars(build_bar_draft(codes[0]), case)
            outcomes = method.seal_outcomes(
                method_fixtures.outcome_draft(case["method_registration"]),
                case["method_registration"],
            )
            original = cycle.paper_fund.compute_performance
            try:
                cycle.paper_fund.compute_performance = lambda *_args, **_kwargs: {
                    "claim_allowed": True,
                    "n_closed": 1,
                }
                with self.assertRaisesRegex(cycle.CycleError, "unlocked a claim"):
                    cycle.run_cycle(
                        bundle_dir=closure_bundle, case=case, bars=bars,
                        outcomes=outcomes,
                        generated_at="2026-08-17T16:10:00+00:00",
                    )
            finally:
                cycle.paper_fund.compute_performance = original

    def test_postmortem_receipt_must_bind_outcome_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, cycle_bundle, _, _, _, (trace, _, _, review) = build_replay(root)
            draft = build_review_draft(trace, review, bound=False)
            with self.assertRaisesRegex(cycle.CycleError, "not bound"):
                cycle.seal_review_receipt(draft, review)

    def test_postmortem_requires_closed_or_no_trade_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, codes, _, _, _ = build_closure_bundle(root)
            case = cycle.seal_case(build_case_draft(closure_bundle, codes[0]), closure_bundle)
            bar_draft = build_bar_draft(codes[0])
            bar_draft["rows"] = [
                execution_row("20260813", 97.0, 99.0, 96.0, 98.0),
                execution_row("20260814", 98.0, 99.0, 97.0, 98.5, pre_close=98.0),
            ]
            bar_draft["generated_at"] = "2026-08-14T16:00:00+00:00"
            bars = cycle.seal_bars(bar_draft, case)
            outcomes_draft = method_fixtures.outcome_draft(case["method_registration"])
            outcomes_draft["generated_at"] = "2026-08-14T16:00:00+00:00"
            outcomes_draft["scoring_as_of"] = "20260814"
            for fact in outcomes_draft["facts"]:
                fact["observed_at"] = "20260814"
            outcomes_draft["facts_hash"] = funnel._hash(outcomes_draft["facts"])
            outcomes = method.seal_outcomes(outcomes_draft, case["method_registration"])
            trace, _, _, review = cycle.run_cycle(
                bundle_dir=closure_bundle,
                case=case,
                bars=bars,
                outcomes=outcomes,
                generated_at="2026-08-14T16:10:00+00:00",
            )
            self.assertEqual(review["paper_state"], "PENDING")
            draft = build_review_draft(trace, review)
            draft["reviewed_at"] = "2026-08-14T16:20:00+00:00"
            with self.assertRaisesRegex(cycle.CycleError, "outcome is incomplete"):
                cycle.seal_review_receipt(draft, review)

    def test_human_dispute_requires_evidence_and_preserves_machine_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, cycle_bundle, _, _, _, (trace, _, _, review) = build_replay(root)
            draft = build_review_draft(trace, review)
            draft["review_disposition"] = "DISPUTE"
            draft["human_attribution"] = "THESIS_RIGHT_TIMING_WRONG"
            draft["disagreement_reason"] = "The registered target touch followed a same-day event gap, not the timing setup."
            draft["evidence_refs"].append("settled_bars:20260817")
            receipt = cycle.seal_review_receipt(draft, review)
            final = cycle.finalize_review(cycle_bundle, closure_bundle, receipt)
            self.assertEqual(final["machine_attribution"], "THESIS_RIGHT_TIMING_RIGHT")
            self.assertEqual(final["human_attribution"], "THESIS_RIGHT_TIMING_WRONG")
            self.assertEqual(final["review_disposition"], "DISPUTE")

            invalid = build_review_draft(trace, review)
            invalid["review_disposition"] = "DISPUTE"
            invalid["human_attribution"] = "THESIS_RIGHT_TIMING_WRONG"
            invalid["disagreement_reason"] = ""
            with self.assertRaisesRegex(cycle.CycleError, "lacks bound evidence"):
                cycle.seal_review_receipt(invalid, review)

    def test_final_manifest_cannot_rewrite_paper_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, cycle_bundle, _, _, _, (trace, _, _, review) = build_replay(root)
            draft = build_review_draft(trace, review)
            receipt = cycle.seal_review_receipt(draft, review)
            final = cycle.finalize_review(cycle_bundle, closure_bundle, receipt)
            final_bundle = root / "final"
            cycle._write_final_outputs(final_bundle, cycle_bundle, closure_bundle, receipt, final)
            manifest_path = final_bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["no_trade_flag"] = False
            closure_fixtures.write_json(manifest_path, manifest)
            with self.assertRaisesRegex(cycle.CycleError, "reviewed-cycle manifest is invalid"):
                cycle.verify_final_bundle(final_bundle, cycle_bundle, closure_bundle)

    def test_non_finite_json_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text('{"entry": NaN}\n', encoding="utf-8")
            with self.assertRaisesRegex(cycle.CycleError, "non-finite JSON"):
                cycle._load_object(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
