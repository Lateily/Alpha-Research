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
import test_research_closure_experiment as closure_fixtures  # noqa: E402


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
    closure._write_replay_outputs(output, packet, receipt, queue, report)
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
    return {
        "schema": cycle.CASE_SCHEMA,
        "schema_version": cycle.SCHEMA_VERSION,
        "generated_at": "2026-08-13T10:10:00+00:00",
        "ticker": ticker,
        "name": "闭环样本",
        "theme": "闭环行业",
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


def build_bar_draft(ticker: str) -> dict:
    return {
        "schema": cycle.BARS_SCHEMA,
        "schema_version": cycle.SCHEMA_VERSION,
        "ticker": ticker,
        "source": "OFFLINE_FIXTURE_SETTLED",
        "generated_at": "2026-08-17T16:00:00+00:00",
        "rows": [
            {"date": "20260813", "open": 98.0, "high": 101.0, "low": 97.0, "close": 100.0},
            {"date": "20260814", "open": 99.0, "high": 102.0, "low": 98.0, "close": 101.0},
            {"date": "20260817", "open": 110.0, "high": 116.0, "low": 108.0, "close": 115.0},
        ],
        "production_authority": False,
    }


def build_replay(root: Path):
    closure_bundle, codes, _, _, _ = build_closure_bundle(root)
    case = cycle.seal_case(build_case_draft(closure_bundle, codes[0]), closure_bundle)
    bars = cycle.seal_bars(build_bar_draft(codes[0]), case)
    outputs = cycle.run_cycle(
        bundle_dir=closure_bundle,
        case=case,
        bars=bars,
        generated_at="2026-08-17T16:10:00+00:00",
    )
    cycle_bundle = root / "cycle-result"
    cycle._write_cycle_outputs(cycle_bundle, closure_bundle, case, bars, *outputs)
    return closure_bundle, cycle_bundle, case, bars, outputs


class ResearchCycleTests(unittest.TestCase):
    def test_cli_runs_the_entire_u4_to_reviewed_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, codes, _, _, _ = build_closure_bundle(root)
            case_draft = root / "case-draft.json"
            case_path = root / "case.json"
            bars_draft = root / "bars-draft.json"
            bars_path = root / "bars.json"
            cycle_bundle = root / "cycle"
            postmortem_draft = root / "postmortem-draft.json"
            postmortem = root / "postmortem.json"
            reviewed_bundle = root / "reviewed"
            closure_fixtures.write_json(case_draft, build_case_draft(closure_bundle, codes[0]))
            closure_fixtures.write_json(bars_draft, build_bar_draft(codes[0]))
            script = ROOT / "experiments" / "research_funnel" / "research_cycle.py"
            env = {**os.environ, "AR_OFFLINE": "1", "PYTHONPYCACHEPREFIX": str(root / "pycache")}

            commands = [
                [sys.executable, str(script), "seal-case", "--closure-bundle", str(closure_bundle), "--input", str(case_draft), "--output", str(case_path)],
                [sys.executable, str(script), "seal-bars", "--closure-bundle", str(closure_bundle), "--case", str(case_path), "--input", str(bars_draft), "--output", str(bars_path)],
                [sys.executable, str(script), "replay", "--closure-bundle", str(closure_bundle), "--case", str(case_path), "--bars", str(bars_path), "--generated-at", "2026-08-17T16:10:00+00:00", "--output-dir", str(cycle_bundle)],
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
            closure_fixtures.write_json(postmortem_draft, {
                "schema": cycle.REVIEW_RECEIPT_SCHEMA,
                "schema_version": cycle.SCHEMA_VERSION,
                "research_cycle_id": trace["research_cycle_id"],
                "mechanical_review_hash": review["review_hash"],
                "claimed_reviewer": "Junyan",
                "identity_verification": "UNAVAILABLE",
                "production_authority": False,
                "reviewed_at": "2026-08-17T16:20:00+00:00",
                "authorization_text": f"批准离线 paper 复盘，绑定 review_hash {review['review_hash'][:12]}，不产生生产权限。",
                "primary_attribution": "PROCESS_OK",
                "lessons": ["CLI 全链按预注册规则执行。"],
                "rule_change_proposals": [],
                "disclaimer": cycle.DISCLAIMER,
            })
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
            closure_bundle, cycle_bundle, _, _, (trace, fund, review) = build_replay(root)
            verified = cycle.verify_cycle_bundle(cycle_bundle, closure_bundle)
            order = fund["orders"][0]
            self.assertEqual(trace["final_state"], "REVIEW_READY")
            self.assertEqual(order["fill_date"], "20260814")
            self.assertEqual(order["exit_date"], "20260817")
            self.assertEqual(order["exit_reason"], "target")
            self.assertFalse(fund["performance"]["claim_allowed"])
            self.assertEqual(verified["status"], "VERIFIED")

            draft = {
                "schema": cycle.REVIEW_RECEIPT_SCHEMA,
                "schema_version": cycle.SCHEMA_VERSION,
                "research_cycle_id": trace["research_cycle_id"],
                "mechanical_review_hash": review["review_hash"],
                "claimed_reviewer": "Junyan",
                "identity_verification": "UNAVAILABLE",
                "production_authority": False,
                "reviewed_at": "2026-08-17T16:20:00+00:00",
                "authorization_text": f"批准离线 paper 复盘，绑定 review_hash {review['review_hash'][:12]}，不产生生产权限。",
                "primary_attribution": "PROCESS_OK",
                "lessons": ["全链证据和 T+1 结算规则均按预注册执行。"],
                "rule_change_proposals": [],
                "disclaimer": cycle.DISCLAIMER,
            }
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
            case = cycle.seal_case(draft, closure_bundle)
            bars = cycle.seal_bars(build_bar_draft(codes[0]), case)
            trace, fund, review = cycle.run_cycle(
                bundle_dir=closure_bundle, case=case, bars=bars,
                generated_at="2026-08-17T16:10:00+00:00",
            )
            self.assertEqual(trace["final_state"], "NO_TRADE")
            self.assertEqual(fund["orders"], [])
            self.assertEqual(review["paper_state"], "NO_TRADE")

    def test_same_bar_stop_and_target_uses_conservative_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, codes, _, _, _ = build_closure_bundle(root)
            case = cycle.seal_case(build_case_draft(closure_bundle, codes[0]), closure_bundle)
            draft = build_bar_draft(codes[0])
            draft["rows"] = draft["rows"][:2]
            draft["rows"][1] = {
                "date": "20260814", "open": 99.0, "high": 116.0,
                "low": 94.0, "close": 100.0,
            }
            draft["generated_at"] = "2026-08-14T16:00:00+00:00"
            bars = cycle.seal_bars(draft, case)
            _, fund, review = cycle.run_cycle(
                bundle_dir=closure_bundle, case=case, bars=bars,
                generated_at="2026-08-14T16:10:00+00:00",
            )
            order = fund["orders"][0]
            self.assertEqual(order["fill_date"], "20260814")
            self.assertEqual(order["exit_reason"], "stop_and_target_same_bar->stop")
            self.assertEqual(order["exit_price"], 95.0)
            self.assertEqual(review["realized_R"], -1.0)

    def test_pre_registration_settled_bar_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            closure_bundle, codes, _, _, _ = build_closure_bundle(Path(tmp))
            case = cycle.seal_case(build_case_draft(closure_bundle, codes[0]), closure_bundle)
            draft = build_bar_draft(codes[0])
            draft["rows"][0]["date"] = "20260812"
            with self.assertRaisesRegex(cycle.CycleError, "pre-registration"):
                cycle.seal_bars(draft, case)

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
            closure_bundle, cycle_bundle, _, _, _ = build_replay(root)
            review_path = cycle_bundle / "mechanical_review.json"
            review = json.loads(review_path.read_text())
            review["claim_allowed"] = True
            closure_fixtures.write_json(review_path, review)
            with self.assertRaisesRegex(cycle.CycleError, "artifact hash mismatch"):
                cycle.verify_cycle_bundle(cycle_bundle, closure_bundle)

    def test_cycle_manifest_cannot_rewrite_paper_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, cycle_bundle, _, _, _ = build_replay(root)
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
            closure_bundle, cycle_bundle, _, _, _ = build_replay(root)
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
            original = cycle.paper_fund.compute_performance
            try:
                cycle.paper_fund.compute_performance = lambda *_args, **_kwargs: {
                    "claim_allowed": True,
                    "n_closed": 1,
                }
                with self.assertRaisesRegex(cycle.CycleError, "unlocked a claim"):
                    cycle.run_cycle(
                        bundle_dir=closure_bundle, case=case, bars=bars,
                        generated_at="2026-08-17T16:10:00+00:00",
                    )
            finally:
                cycle.paper_fund.compute_performance = original

    def test_postmortem_receipt_must_bind_outcome_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, cycle_bundle, _, _, (trace, _, review) = build_replay(root)
            draft = {
                "schema": cycle.REVIEW_RECEIPT_SCHEMA,
                "schema_version": cycle.SCHEMA_VERSION,
                "research_cycle_id": trace["research_cycle_id"],
                "mechanical_review_hash": "0" * 64,
                "claimed_reviewer": "Junyan",
                "identity_verification": "UNAVAILABLE",
                "production_authority": False,
                "reviewed_at": "2026-08-17T16:20:00+00:00",
                "authorization_text": f"批准离线复盘，绑定 review_hash {review['review_hash'][:12]}，不产生生产权限。",
                "primary_attribution": "PROCESS_OK",
                "lessons": ["闭环证据完整。"],
                "rule_change_proposals": [],
                "disclaimer": cycle.DISCLAIMER,
            }
            with self.assertRaisesRegex(cycle.CycleError, "not bound"):
                cycle.seal_review_receipt(draft, review)

    def test_final_manifest_cannot_rewrite_paper_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_bundle, cycle_bundle, _, _, (trace, _, review) = build_replay(root)
            draft = {
                "schema": cycle.REVIEW_RECEIPT_SCHEMA,
                "schema_version": cycle.SCHEMA_VERSION,
                "research_cycle_id": trace["research_cycle_id"],
                "mechanical_review_hash": review["review_hash"],
                "claimed_reviewer": "Junyan",
                "identity_verification": "UNAVAILABLE",
                "production_authority": False,
                "reviewed_at": "2026-08-17T16:20:00+00:00",
                "authorization_text": f"批准离线复盘，绑定 review_hash {review['review_hash'][:12]}，不产生生产权限。",
                "primary_attribution": "PROCESS_OK",
                "lessons": ["闭环证据完整。"],
                "rule_change_proposals": [],
                "disclaimer": cycle.DISCLAIMER,
            }
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
