#!/usr/bin/env python3
"""Behavior, crash-recovery, and authority tests for paper registration."""

from __future__ import annotations

import copy
import fcntl
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
for path in (
    ROOT,
    ROOT / "tests",
    ROOT / "experiments" / "research_funnel",
    ROOT / "experiments" / "execution_tracker",
):
    sys.path.insert(0, str(path))

from experiments.execution_tracker import event_ledger  # noqa: E402
from experiments.execution_tracker import model_paper_fund as paper_fund  # noqa: E402
from experiments.research_funnel import closure_experiment as closure  # noqa: E402
from experiments.research_funnel import paper_registration_bridge as bridge  # noqa: E402
from experiments.research_funnel import research_cycle  # noqa: E402
from experiments.research_funnel import u4_decision_ledger as u4_ledger  # noqa: E402
import test_research_closure_experiment as closure_fixtures  # noqa: E402
import test_research_cycle as cycle_fixtures  # noqa: E402
import test_u4_decision_ledger as u4_fixtures  # noqa: E402


PACKET_AT = "2026-08-13T10:00:00+00:00"
U4_DECIDED_AT = "2026-08-13T10:11:00+00:00"
U4_REGISTERED_AT = "2026-08-13T18:12:00"
CASE_AT = "2026-08-13T10:20:00+00:00"
PLAN_AT = "2026-08-13T10:30:00+00:00"
APPROVED_AT = "2026-08-13T10:31:00+00:00"
INTENT_AT = "2026-08-13T18:32:00"
RETRY_AT = "2026-08-13T18:34:00"


def write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def build_context(root: Path) -> dict:
    source_bundle = root / "source-bundle"
    shutil.copytree(u4_fixtures.SOURCE_BUNDLE, source_bundle)
    packet = closure.build_review_packet(
        bundle_dir=source_bundle,
        battery=None,
        generated_at=PACKET_AT,
    )
    battery = json.loads(
        (source_bundle / "candidate_battery.json").read_text(encoding="utf-8")
    )
    receipt = closure_fixtures.receipt_for(packet, list(u4_fixtures.SELECT_CODES))
    queue, report = closure.run_offline_replay(
        bundle_dir=source_bundle,
        battery=battery,
        packet=packet,
        receipt=receipt,
        generated_at="2026-08-13T10:06:00+00:00",
    )
    closure_bundle = root / "closure-bundle"
    closure._write_replay_outputs(
        closure_bundle,
        source_bundle,
        battery,
        packet,
        receipt,
        queue,
        report,
    )

    ledger_path = root / "event-ledger.jsonl"
    draft = u4_fixtures.draft_for(packet, decided_at=U4_DECIDED_AT)
    with patch.object(event_ledger, "_runtime_timestamp", return_value=U4_REGISTERED_AT):
        u4_ledger.append_decision_batch(
            packet=packet,
            draft=draft,
            ledger_path=ledger_path,
            bundle_dir=source_bundle,
        )

    case_draft = cycle_fixtures.build_case_draft(
        closure_bundle, u4_fixtures.SELECT_CODES[0]
    )
    case_draft["generated_at"] = CASE_AT
    case = research_cycle.seal_case(case_draft, closure_bundle)

    fund_dir = root / "model-fund"
    paper_fund.init_fund(
        fund_dir=str(fund_dir), capital=paper_fund.INITIAL_CAPITAL, date="20260813"
    )
    marks = bridge.seal_marks(
        {
            "schema": bridge.MARKS_SCHEMA,
            "schema_version": bridge.SCHEMA_VERSION,
            "as_of": "20260813",
            "generated_at": "2026-08-13T15:30:00+08:00",
            "run_id": "FIXTURE_RUN_20260813",
            "source": "TUSHARE_DAILY_SETTLED",
            "marks": {},
            "no_trade_flag": True,
            "trade_authority": False,
            "production_authority": False,
        },
        [],
    )
    plan = bridge.build_plan(
        closure_bundle=closure_bundle,
        case=case,
        u4_ledger_path=ledger_path,
        fund_dir=fund_dir,
        marks=marks,
        generated_at=PLAN_AT,
    )
    approval = bridge.seal_approval(
        {
            "schema": bridge.APPROVAL_SCHEMA,
            "schema_version": bridge.SCHEMA_VERSION,
            "plan_hash": plan["plan_hash"],
            "claimed_approver": "Junyan",
            "identity_verification": "UNAVAILABLE",
            "approved_at": APPROVED_AT,
            "authorization_text": (
                "批准执行本次模拟 paper 登记，完整绑定 plan_hash "
                f"{plan['plan_hash']}；不产生真实交易或生产权限。"
            ),
            "authorization_evidence_ref": "conversation:paper-registration-fixture",
            "no_trade_flag": True,
            "trade_authority": False,
            "production_authority": False,
        },
        plan,
    )
    return {
        "source_bundle": source_bundle,
        "closure_bundle": closure_bundle,
        "packet": packet,
        "case": case,
        "ledger_path": ledger_path,
        "fund_dir": fund_dir,
        "marks": marks,
        "plan": plan,
        "approval": approval,
        "nightly_lock": root / "nightly.lock",
    }


def apply_context(ctx: dict, *, fail_after: str | None = None, now: str = INTENT_AT):
    with patch.object(event_ledger, "_runtime_timestamp", return_value=now):
        return bridge.apply_plan(
            plan=ctx["plan"],
            approval=ctx["approval"],
            closure_bundle=ctx["closure_bundle"],
            case=ctx["case"],
            u4_ledger_path=ctx["ledger_path"],
            event_ledger_path=ctx["ledger_path"],
            fund_dir=ctx["fund_dir"],
            nightly_lock_path=ctx["nightly_lock"],
            _fail_after=fail_after,
        )


def rehash_plan(plan: dict) -> dict:
    plan["plan_hash"] = bridge._sha(bridge._without(plan, "plan_hash"))
    return plan


def approval_for(plan: dict, *, evidence_ref: str = "conversation:paper-registration-fixture") -> dict:
    return bridge.seal_approval(
        {
            "schema": bridge.APPROVAL_SCHEMA,
            "schema_version": bridge.SCHEMA_VERSION,
            "plan_hash": plan["plan_hash"],
            "claimed_approver": "Junyan",
            "identity_verification": "UNAVAILABLE",
            "approved_at": APPROVED_AT,
            "authorization_text": (
                "批准执行本次模拟 paper 登记，完整绑定 plan_hash "
                f"{plan['plan_hash']}；不产生真实交易或生产权限。"
            ),
            "authorization_evidence_ref": evidence_ref,
            "no_trade_flag": True,
            "trade_authority": False,
            "production_authority": False,
        },
        plan,
    )


def source_context_for(ctx: dict) -> dict:
    return {
        "closure_bundle": ctx["closure_bundle"],
        "case": copy.deepcopy(ctx["case"]),
        "u4_ledger_path": ctx["ledger_path"],
        "fund_dir": ctx["fund_dir"],
    }


class PaperRegistrationBridgeTests(unittest.TestCase):
    def test_u4_and_registration_require_one_r015_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            separate = Path(tmp) / "separate-registration.jsonl"
            with self.assertRaisesRegex(
                bridge.PaperRegistrationError, "must share one R-015 ledger"
            ):
                bridge.apply_plan(
                    plan=ctx["plan"],
                    approval=ctx["approval"],
                    closure_bundle=ctx["closure_bundle"],
                    case=ctx["case"],
                    u4_ledger_path=ctx["ledger_path"],
                    event_ledger_path=separate,
                    fund_dir=ctx["fund_dir"],
                    nightly_lock_path=ctx["nightly_lock"],
                )

        self.assertFalse(separate.exists())

    def test_apply_registers_one_realistic_paper_order_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            result = apply_context(ctx)
            repeated = apply_context(ctx, now=RETRY_AT)
            state = bridge._load_fund_state(ctx["fund_dir"])
            verified = bridge.verify_registration_state(
                event_ledger_path=ctx["ledger_path"], fund_dir=ctx["fund_dir"]
            )
            paper_events = bridge._paper_outer_records(ctx["ledger_path"])

        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual(repeated["status"], "IDEMPOTENT")
        self.assertEqual(len(state["orders"]), 1)
        self.assertEqual(len(state["decision_log"]), 1)
        order = state["orders"][0]
        self.assertEqual(order["execution_mode"], paper_fund.pp.EXECUTION_MODEL_VERSION)
        self.assertEqual(order["status"], "pending")
        self.assertTrue(order["no_trade_flag"])
        self.assertFalse(order["trade_authority"])
        self.assertFalse(order["production_authority"])
        self.assertFalse(order["claim_allowed"])
        self.assertFalse(order["sample_eligible"])
        self.assertEqual([row["kind"] for row in paper_events], [bridge.INTENT_KIND, bridge.COMMIT_KIND])
        self.assertTrue(verified["ok"], verified)

    def test_all_crash_points_converge_without_duplicate_order_or_decision(self) -> None:
        for point in ("intent", "orders", "decision_log", "commit"):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as tmp:
                ctx = build_context(Path(tmp))
                with self.assertRaisesRegex(bridge.PaperRegistrationError, "injected interruption"):
                    apply_context(ctx, fail_after=point)
                if point == "commit":
                    self.assertTrue(bridge.verify_registration_state(
                        event_ledger_path=ctx["ledger_path"], fund_dir=ctx["fund_dir"]
                    )["ok"])
                else:
                    with self.assertRaises(bridge.PaperRegistrationError):
                        paper_fund.assert_paper_registration_ready(
                            str(ctx["fund_dir"]), str(ctx["ledger_path"])
                        )
                recovered = apply_context(ctx, now=RETRY_AT)
                state = bridge._load_fund_state(ctx["fund_dir"])
                replay = bridge._registration_state(ctx["ledger_path"])
                self.assertIn(recovered["status"], {"RECOVERED", "IDEMPOTENT"})
                self.assertEqual(len(state["orders"]), 1)
                self.assertEqual(len(state["decision_log"]), 1)
                self.assertEqual(len(replay["intents"]), 1)
                self.assertEqual(len(replay["commits"]), 1)
                self.assertEqual(replay["pending"], [])

    def test_current_u4_rejection_revokes_old_closure_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            events = u4_ledger.current_packet_decisions(
                ctx["ledger_path"], ctx["packet"]["packet_hash"]
            )
            supersedes = {
                event["candidate"]["ts_code"]: event["decision_id"] for event in events
            }
            decisions = dict(u4_fixtures.DEFAULT_DECISIONS)
            original = u4_fixtures.SELECT_CODES[0]
            replacement = u4_fixtures.REJECT_CODE
            decisions[original] = "REJECT"
            decisions[replacement] = "SELECT"
            revision = u4_fixtures.draft_for(
                ctx["packet"],
                decisions=decisions,
                revision=2,
                supersedes=supersedes,
                decided_at="2026-08-13T10:40:00+00:00",
            )
            with patch.object(
                event_ledger, "_runtime_timestamp", return_value="2026-08-13T18:41:00"
            ):
                u4_ledger.append_decision_batch(
                    packet=ctx["packet"],
                    draft=revision,
                    ledger_path=ctx["ledger_path"],
                    bundle_dir=ctx["source_bundle"],
                )
            with self.assertRaisesRegex(bridge.PaperRegistrationError, "not SELECT"):
                bridge.build_plan(
                    closure_bundle=ctx["closure_bundle"],
                    case=ctx["case"],
                    u4_ledger_path=ctx["ledger_path"],
                    fund_dir=ctx["fund_dir"],
                    marks=ctx["marks"],
                    generated_at="2026-08-13T10:45:00+00:00",
                )

    def test_approval_must_bind_full_plan_and_preserve_unverified_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            for field, value, message in (
                ("authorization_text", "批准模拟登记但不写完整哈希。", "full plan_hash"),
                ("plan_hash", "sha256:" + "0" * 64, "another plan"),
                ("identity_verification", "VERIFIED", "authority/evidence"),
                ("trade_authority", True, "authority/evidence"),
            ):
                with self.subTest(field=field):
                    bad = copy.deepcopy(ctx["approval"])
                    bad[field] = value
                    bad["approval_hash"] = bridge._sha(bridge._without(bad, "approval_hash"))
                    with self.assertRaisesRegex(bridge.PaperRegistrationError, message):
                        bridge.validate_approval(bad, ctx["plan"])

    def test_plan_hash_is_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            bad = copy.deepcopy(ctx["plan"])
            bad["generated_at"] = "2026-08-13T10:30:01+00:00"
            with self.assertRaisesRegex(bridge.PaperRegistrationError, "plan hash mismatch"):
                bridge.validate_plan(bad)

    def test_plan_nested_post_state_fails_closed_as_a_contract_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            bad = copy.deepcopy(ctx["plan"])
            bad["projection"]["post_state"] = []
            rehash_plan(bad)
            with self.assertRaisesRegex(
                bridge.PaperRegistrationError, "post-state must be an object"
            ):
                bridge.validate_plan(bad)

    def test_request_order_and_source_bindings_are_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            bad_request = copy.deepcopy(ctx["plan"])
            bad_request["paper_request"]["entry_review"] += 1.0
            rehash_plan(bad_request)
            with self.assertRaisesRegex(bridge.PaperRegistrationError, "request and frozen order"):
                bridge.validate_plan(bad_request)

            bad_source = copy.deepcopy(ctx["plan"])
            fake_hash = "sha256:" + "0" * 64
            bad_source["projection"]["order"]["research_case_hash"] = fake_hash
            bad_source["projection"]["order_registration_projection"] = (
                bridge._registration_projection(bad_source["projection"]["order"])
            )
            bad_source["projection"]["decision_log_event"]["research_case_hash"] = fake_hash
            rehash_plan(bad_source)
            with self.assertRaisesRegex(bridge.PaperRegistrationError, "frozen source references"):
                bridge.validate_plan(bad_source)

    def test_forbidden_action_fields_never_enter_a_paper_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            bad = copy.deepcopy(ctx["plan"])
            bad["projection"]["order"]["trade_action"] = "BUY"
            rehash_plan(bad)
            with self.assertRaisesRegex(bridge.PaperRegistrationError, "forbidden action field"):
                bridge.validate_plan(bad)

    def test_typed_intent_boundary_recomputes_current_source_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            bad_plan = copy.deepcopy(ctx["plan"])
            bad_plan["source_refs"]["closure_bundle_hash"] = "sha256:" + "0" * 64
            rehash_plan(bad_plan)
            bad_approval = approval_for(bad_plan)

            def builder(outer_ts: str):
                intent = bridge._build_intent(bad_plan, bad_approval, outer_ts)
                return intent["intent_id"], intent

            with patch.object(event_ledger, "_runtime_timestamp", return_value=INTENT_AT):
                with self.assertRaisesRegex(
                    bridge.PaperRegistrationError, "exact source projection"
                ):
                    event_ledger.append_paper_registration_stamped(
                        bridge.INTENT_KIND,
                        builder,
                        source_context=source_context_for(ctx),
                        path=str(ctx["ledger_path"]),
                    )
            self.assertEqual(bridge._paper_outer_records(ctx["ledger_path"]), [])

    def test_typed_commit_boundary_requires_projection_convergence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            captured: dict = {}

            def intent_builder(outer_ts: str):
                intent = bridge._build_intent(ctx["plan"], ctx["approval"], outer_ts)
                captured["intent"] = intent
                return intent["intent_id"], intent

            with patch.object(event_ledger, "_runtime_timestamp", return_value=INTENT_AT):
                event_ledger.append_paper_registration_stamped(
                    bridge.INTENT_KIND,
                    intent_builder,
                    source_context=source_context_for(ctx),
                    path=str(ctx["ledger_path"]),
                )

            def commit_builder(outer_ts: str):
                commit = bridge._build_commit(captured["intent"], outer_ts)
                return commit["commit_id"], commit

            with patch.object(event_ledger, "_runtime_timestamp", return_value=RETRY_AT):
                with self.assertRaisesRegex(
                    bridge.PaperRegistrationError, "precedes exact projection convergence"
                ):
                    event_ledger.append_paper_registration_stamped(
                        bridge.COMMIT_KIND,
                        commit_builder,
                        source_context=source_context_for(ctx),
                        path=str(ctx["ledger_path"]),
                    )
            replay = bridge._registration_state(ctx["ledger_path"])
            self.assertEqual(len(replay["intents"]), 1)
            self.assertEqual(len(replay["commits"]), 0)

    def test_typed_writer_snapshots_payload_before_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            captured: dict = {}

            def builder(outer_ts: str):
                payload = bridge._build_intent(ctx["plan"], ctx["approval"], outer_ts)
                captured["payload"] = payload
                return payload["intent_id"], payload

            original = bridge.validate_typed_outer_append

            def validate_then_mutate(path, preview, *, source_context):
                original(path, preview, source_context=source_context)
                captured["payload"]["plan"]["paper_request"]["ticker"] = "999999.SZ"

            with patch.object(event_ledger, "_runtime_timestamp", return_value=INTENT_AT):
                with patch.object(
                    bridge, "validate_typed_outer_append", side_effect=validate_then_mutate
                ):
                    event_ledger.append_paper_registration_stamped(
                        bridge.INTENT_KIND,
                        builder,
                        source_context=source_context_for(ctx),
                        path=str(ctx["ledger_path"]),
                    )
            stored = bridge._paper_outer_records(ctx["ledger_path"])[0]["payload"]
            self.assertEqual(stored["plan"]["paper_request"]["ticker"], ctx["case"]["ticker"])

    def test_idempotent_retry_requires_the_original_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            apply_context(ctx)
            replacement = approval_for(
                ctx["plan"], evidence_ref="conversation:substituted-approval"
            )
            ctx["approval"] = replacement
            with self.assertRaisesRegex(bridge.PaperRegistrationError, "differs from the supplied"):
                apply_context(ctx, now=RETRY_AT)

    def test_shared_nightly_lock_rejects_concurrent_registration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            with ctx["nightly_lock"].open("a+") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    with self.assertRaisesRegex(bridge.PaperRegistrationError, "nightly.lock is held"):
                        apply_context(ctx)
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)
            self.assertEqual(bridge._paper_outer_records(ctx["ledger_path"]), [])

    def test_raw_r015_append_cannot_bypass_typed_registration_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            for writer in (
                lambda: event_ledger.append(
                    bridge.INTENT_KIND, "raw", {}, path=str(path)
                ),
                lambda: event_ledger.append_stamped(
                    bridge.COMMIT_KIND, lambda _ts: ("raw", {}), path=str(path)
                ),
            ):
                with self.assertRaisesRegex(ValueError, "typed-only"):
                    writer()
            self.assertFalse(path.exists())

    def test_committed_immutable_projection_is_checked_but_fill_state_may_advance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            apply_context(ctx)
            orders = paper_fund.load("orders.json", [], str(ctx["fund_dir"]))
            orders[0].update({
                "status": "filled", "fill_date": "20260814", "fill_price": 100.05,
                "entry_gross_cny": round(orders[0]["shares"] * 100.05, 2),
                "entry_fees_cny": 45.0,
            })
            paper_fund.save("orders.json", orders, str(ctx["fund_dir"]))
            self.assertTrue(bridge.verify_registration_state(
                event_ledger_path=ctx["ledger_path"], fund_dir=ctx["fund_dir"]
            )["ok"])
            orders[0]["research_case_hash"] = "sha256:" + "0" * 64
            paper_fund.save("orders.json", orders, str(ctx["fund_dir"]))
            result = bridge.verify_registration_state(
                event_ledger_path=ctx["ledger_path"], fund_dir=ctx["fund_dir"]
            )
            self.assertFalse(result["ok"])
            self.assertIn("immutable registration fields changed", result["errors"][0])

    def test_committed_registration_decision_projection_is_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            apply_context(ctx)
            decisions = paper_fund.load("decision_log.json", [], str(ctx["fund_dir"]))
            decisions[0]["reason"] = "rewritten after commit"
            paper_fund.save("decision_log.json", decisions, str(ctx["fund_dir"]))
            result = bridge.verify_registration_state(
                event_ledger_path=ctx["ledger_path"], fund_dir=ctx["fund_dir"]
            )
            self.assertFalse(result["ok"])
            self.assertIn("registration decision changed", result["errors"][0])

    def test_daily_engine_infers_realistic_mode_from_registered_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            apply_context(ctx)
            state = bridge._load_fund_state(ctx["fund_dir"])
            rows = [
                cycle_fixtures.execution_row("20260813", 99.0, 101.0, 98.0, 100.0),
                cycle_fixtures.execution_row(
                    "20260814", 99.0, 102.0, 98.0, 101.0, pre_close=100.0
                ),
            ]
            paper_fund.process_day(
                state["fund"], state["orders"], state["decision_log"], None,
                series_fn=lambda *_args: rows,
            )
            order = state["orders"][0]
            self.assertEqual(order["status"], "filled")
            self.assertEqual(order["fill_date"], "20260814")
            self.assertGreater(order["fill_price"], order["entry_review_price"])
            self.assertGreater(order["entry_fees_cny"], 0)

    def test_daily_cli_refuses_before_advance_when_registration_preflight_fails(self) -> None:
        import nightly_context

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fund_dir = root / "fund"
            paper_fund.init_fund(
                fund_dir=str(fund_dir), capital=paper_fund.INITIAL_CAPITAL, date="20260814"
            )
            output = io.StringIO()
            argv = [
                "model_paper_fund.py", "--daily", "--fund-dir", str(fund_dir),
                "--event-ledger", str(root / "event-ledger.jsonl"),
            ]
            with patch.object(sys, "argv", argv):
                with patch.object(nightly_context, "target_trade_date", return_value="20260814"):
                    with patch.object(
                        paper_fund,
                        "assert_paper_registration_ready",
                        side_effect=RuntimeError("pending registration"),
                    ):
                        with redirect_stdout(output):
                            result = paper_fund.main()
            state = bridge._load_fund_state(fund_dir)
            self.assertEqual(result, 1)
            self.assertIn("paper registration preflight failed", output.getvalue())
            self.assertEqual(state["nav_history"], [])

    def test_marks_must_cover_every_filled_position_and_plan_is_toctou_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            state = bridge._load_fund_state(ctx["fund_dir"])
            fake = copy.deepcopy(ctx["plan"]["projection"]["order"])
            fake.update({
                "entry_id": "legacy-filled", "paper_registration_id": None,
                "ticker": "600000.SH", "status": "filled", "fill_price": 10.0,
            })
            state["orders"].append(fake)
            paper_fund.save("orders.json", state["orders"], str(ctx["fund_dir"]))
            with self.assertRaisesRegex(bridge.PaperRegistrationError, "cover exactly"):
                bridge.validate_marks(ctx["marks"], state["orders"])

        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(Path(tmp))
            state = bridge._load_fund_state(ctx["fund_dir"])
            state["decision_log"].append({
                "date": "20260813", "action": "NO_TRADE", "ticker": "X.SZ",
                "reason": "concurrent decision", "no_trade_flag": True,
            })
            paper_fund.save("decision_log.json", state["decision_log"], str(ctx["fund_dir"]))
            with self.assertRaisesRegex(
                bridge.PaperRegistrationError,
                "exact current-input projection|portfolio changed",
            ):
                apply_context(ctx)


if __name__ == "__main__":
    unittest.main(verbosity=2)
