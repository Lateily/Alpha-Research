"""Opt-in deadline provenance from a reviewed case to settlement and attribution."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / "tests", ROOT / "experiments/research_funnel",
               ROOT / "experiments/execution_tracker"):
    sys.path.insert(0, str(folder))
import research_cycle as cycle
import research_method as method
import model_paper_fund as fund
import test_research_cycle as fixtures
import test_research_method as method_fixtures
import test_paper_registration_bridge as bridge_fixtures
import test_five_axis_attribution as axis_fixtures
import nightly_publish as publish


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def deadline_policy():
    # This is a declared synthetic exchange calendar, not a production weekday fallback.
    days = []
    for offset in range(50):
        day = date(2026, 8, 13) + timedelta(days=offset)
        days.append({"date": day.strftime("%Y%m%d"), "is_open": day.weekday() < 5})
    calendar = {"schema": "ar.exchange_calendar.v1", "calendar_id": "SYNTHETIC-T10",
                "exchange": "SZSE", "as_of": "20260813", "source": "OFFLINE_FIXTURE",
                "days": days}
    calendar["calendar_hash"] = digest(calendar)
    policy = {"schema": "ar.paper_deadline_policy.v1", "calendar": calendar,
              "clock_origin": "FILL_DATE", "holding_sessions": 10,
              "pending_valid_sessions": 3, "exit_price": "CLOSE",
              "retry": "NEXT_EXCHANGE_SESSION"}
    policy["policy_hash"] = digest(policy)
    return policy


def new_case(root):
    closure, codes, *_ = fixtures.build_closure_bundle(root)
    draft = fixtures.build_case_draft(closure, codes[0])
    draft["schema_version"] = "1.1"
    draft["paper_order"]["deadline_policy"] = deadline_policy()
    return closure, cycle.seal_case(draft, closure)


def replay_inputs(case, *, missing_due=False, never_fill=False):
    sessions = [row["date"] for row in deadline_policy()["calendar"]["days"]
                if row["is_open"] and "20260814" <= row["date"] <= "20260828"]
    rows = [fixtures.execution_row(day, 100., 102., 98., 100., pre_close=100.)
            for day in sessions]
    if never_fill:
        rows = [fixtures.execution_row(day, 90., 91., 89., 90., pre_close=90.)
                for day in sessions]
    if missing_due:
        rows.pop()
    bar_draft = {"schema": cycle.BARS_SCHEMA, "schema_version": "1.1",
                 "ticker": case["ticker"], "source": "OFFLINE_FIXTURE_SETTLED",
                 "generated_at": "2026-08-28T16:00:00+00:00",
                 "scoring_as_of": "20260828", "rows": rows,
                 "production_authority": False}
    bars = cycle.seal_bars(bar_draft, case)
    outcome = method_fixtures.outcome_draft(case["method_registration"], thesis_wrong=True)
    outcome["scoring_as_of"] = "20260828"
    outcome["generated_at"] = "2026-08-28T16:01:00+00:00"
    outcomes = method.seal_outcomes(outcome, case["method_registration"])
    return bars, outcomes


class T10IntegrationTests(unittest.TestCase):
    def test_new_case_requires_bound_explicit_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            closure, codes, *_ = fixtures.build_closure_bundle(Path(tmp))
            draft = fixtures.build_case_draft(closure, codes[0])
            draft["schema_version"] = "1.1"
            draft["paper_order"]["deadline_policy"] = deadline_policy()
            try:
                sealed = cycle.seal_case(draft, closure)
            except cycle.CycleError as exc:
                self.fail(f"explicit opt-in case must seal: {exc}")
            self.assertEqual(sealed["paper_order"]["deadline_policy"], deadline_policy())
            del draft["paper_order"]["deadline_policy"]
            with self.assertRaises(cycle.CycleError):
                cycle.seal_case(draft, closure)

    def test_legacy_case_cannot_silently_take_new_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            closure, codes, *_ = fixtures.build_closure_bundle(Path(tmp))
            draft = fixtures.build_case_draft(closure, codes[0])
            legacy = cycle.seal_case(draft, closure)
            self.assertNotIn("deadline_policy", legacy["paper_order"])
            draft["paper_order"]["deadline_policy"] = deadline_policy()
            with self.assertRaises(cycle.CycleError):
                cycle.seal_case(draft, closure)

    def test_case_rejects_resealed_policy_with_bad_calendar_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            closure, case = new_case(Path(tmp))
            draft = {k: copy.deepcopy(v) for k, v in case.items() if k != "case_hash"}
            policy = draft["paper_order"]["deadline_policy"]
            policy["calendar"]["days"][1]["is_open"] = False
            policy["policy_hash"] = digest({k: v for k, v in policy.items() if k != "policy_hash"})
            with self.assertRaises(cycle.CycleError):
                cycle.seal_case(draft, closure)

    def test_registration_projection_binds_policy_and_cannot_drop_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = bridge_fixtures.build_context(Path(tmp))
            draft = {k: copy.deepcopy(v) for k, v in ctx["case"].items() if k != "case_hash"}
            draft["schema_version"] = "1.1"
            draft["paper_order"]["deadline_policy"] = deadline_policy()
            ctx["case"] = bridge_fixtures.research_cycle.seal_case(draft, ctx["closure_bundle"])
            plan = bridge_fixtures.bridge.build_plan(
                closure_bundle=ctx["closure_bundle"], case=ctx["case"],
                u4_ledger_path=ctx["ledger_path"], fund_dir=ctx["fund_dir"],
                marks=ctx["marks"], generated_at=bridge_fixtures.PLAN_AT)
            self.assertEqual(plan["schema_version"], "1.1")
            for item in (plan["paper_request"], plan["projection"]["order"],
                         plan["projection"]["order_registration_projection"]):
                self.assertEqual(item["deadline_policy"], deadline_policy())
            plan["paper_request"].pop("deadline_policy")
            plan["plan_hash"] = bridge_fixtures.bridge._sha(
                {k: v for k, v in plan.items() if k != "plan_hash"})
            with self.assertRaises(bridge_fixtures.bridge.PaperRegistrationError):
                bridge_fixtures.bridge.validate_plan(plan)

    def test_opt_in_plan_registers_once_in_sandbox_and_preserves_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = bridge_fixtures.build_context(Path(tmp))
            draft = {k: copy.deepcopy(v) for k, v in ctx["case"].items() if k != "case_hash"}
            draft["schema_version"] = "1.1"
            draft["paper_order"]["deadline_policy"] = deadline_policy()
            ctx["case"] = bridge_fixtures.research_cycle.seal_case(draft, ctx["closure_bundle"])
            ctx["plan"] = bridge_fixtures.bridge.build_plan(
                closure_bundle=ctx["closure_bundle"], case=ctx["case"],
                u4_ledger_path=ctx["ledger_path"], fund_dir=ctx["fund_dir"],
                marks=ctx["marks"], generated_at=bridge_fixtures.PLAN_AT)
            approval_draft = {k: copy.deepcopy(v) for k, v in ctx["approval"].items() if k != "approval_hash"}
            old_hash = approval_draft["plan_hash"]
            approval_draft["plan_hash"] = ctx["plan"]["plan_hash"]
            approval_draft["authorization_text"] = approval_draft["authorization_text"].replace(old_hash, ctx["plan"]["plan_hash"])
            ctx["approval"] = bridge_fixtures.bridge.seal_approval(approval_draft, ctx["plan"])
            bridge_fixtures.apply_context(ctx)
            before = (ctx["fund_dir"] / "orders.json").read_bytes()
            bridge_fixtures.apply_context(ctx, now=bridge_fixtures.RETRY_AT)
            self.assertEqual((ctx["fund_dir"] / "orders.json").read_bytes(), before)
            orders = json.loads(before)
            self.assertEqual(len(orders), 1)
            self.assertEqual(orders[0]["deadline_policy"], deadline_policy())
            self.assertFalse(orders[0]["sample_eligible"])

    def test_cycle_exits_at_t10_and_preserves_wrong_thesis(self):
        with tempfile.TemporaryDirectory() as tmp:
            closure, case = new_case(Path(tmp))
            bars, outcomes = replay_inputs(case)
            outputs = cycle.run_cycle(bundle_dir=closure, case=case, bars=bars,
                                      outcomes=outcomes, generated_at="2026-08-28T16:10:00+00:00")
            trace, snapshot, scorecard, review = outputs
            self.assertEqual(trace["final_state"], "REVIEW_READY")
            self.assertEqual(snapshot["orders"][0]["exit_date"], "20260828")
            self.assertEqual(review["horizons"]["T+10"]["date"], "20260828")
            self.assertFalse(snapshot["performance"]["claim_allowed"])
            bundle = Path(tmp) / "cycle"
            cycle._write_cycle_outputs(bundle, closure, case, bars, outcomes, *outputs)
            self.assertTrue(cycle.verify_cycle_bundle(bundle, closure))
            market_draft = axis_fixtures.complete_market_draft(case["ticker"])
            market_draft["generated_at"] = "2026-08-28T16:20:00+00:00"
            for item in (market_draft["market"], market_draft["industry"]):
                item["end_date"] = "20260828"
            market = axis_fixtures.attribution.seal_market_evidence(market_draft, bundle, closure)
            execution_draft = axis_fixtures.complete_execution_draft()
            execution_draft["generated_at"] = "2026-08-28T16:20:00+00:00"
            execution = axis_fixtures.attribution.seal_execution_evidence(execution_draft, bundle, closure)
            receipt = axis_fixtures.attribution.build_attribution(
                bundle, closure, market_evidence=market, execution_evidence=execution,
                generated_at="2026-08-28T16:30:00+00:00")
            self.assertEqual(set(receipt["axes"]), axis_fixtures.attribution.AXIS_KEYS)
            self.assertEqual(receipt["axes"]["thesis"]["status"], "WRONG")
            self.assertFalse(receipt["claim_allowed"])

    def test_missing_due_bar_is_data_blocked_not_window_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            closure, case = new_case(Path(tmp))
            bars, outcomes = replay_inputs(case, missing_due=True)
            trace, snapshot, _, review = cycle.run_cycle(
                bundle_dir=closure, case=case, bars=bars, outcomes=outcomes,
                generated_at="2026-08-28T16:10:00+00:00")
            self.assertEqual(snapshot["orders"][0]["status"], "filled")
            self.assertEqual(review["horizons"]["T+10"]["status"], "DATA_BLOCKED")
            self.assertNotEqual(trace["final_state"], "REVIEW_READY")
            self.assertIsNone(review["paper_return"])

    def test_pending_expiry_is_not_fake_closed_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            closure, case = new_case(Path(tmp))
            bars, outcomes = replay_inputs(case, never_fill=True)
            trace, snapshot, _, review = cycle.run_cycle(
                bundle_dir=closure, case=case, bars=bars, outcomes=outcomes,
                generated_at="2026-08-28T16:10:00+00:00")
            self.assertEqual(trace["final_state"], "EXPIRED")
            self.assertIsNone(review["fill_date"])
            self.assertIsNone(review["paper_return"])
            self.assertEqual(snapshot["fund"]["cash"], fund.INITIAL_CAPITAL)

    def test_missing_final_nav_is_dated_and_not_current_performance(self):
        with tempfile.TemporaryDirectory() as tmp:
            closure, case = new_case(Path(tmp))
            bars, outcomes = replay_inputs(case, missing_due=True)
            bars["rows"][-1].update(open=110., high=112., low=108., close=110.)
            bars["rows_hash"] = digest(bars["rows"])
            outputs = cycle.run_cycle(bundle_dir=closure, case=case, bars=bars,
                outcomes=outcomes, generated_at="2026-08-28T16:10:00+00:00")
            performance = outputs[1]["performance"]
            self.assertIn("nav_quality", performance)
            self.assertEqual(performance["nav_quality"], "DATA_BLOCKED")
            self.assertEqual(performance["as_of"], "20260828")
            self.assertEqual(performance["nav_as_of"], "20260827")
            self.assertGreater(performance["last_known_nav"]["nav"], fund.INITIAL_CAPITAL)
            self.assertEqual(performance["last_known_nav"]["date"], "20260827")
            for metric in ("nav", "cum_return", "max_drawdown"):
                self.assertIsNone(performance[metric])
            bundle = Path(tmp) / "cycle"
            cycle._write_cycle_outputs(bundle, closure, case, bars, outcomes, *outputs)
            self.assertTrue(cycle.verify_cycle_bundle(bundle, closure))

    def test_empty_series_expires_without_inventing_a_completed_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            closure, case = new_case(Path(tmp))
            bars, outcomes = replay_inputs(case)
            draft = {k: v for k, v in bars.items() if k != "rows_hash"}
            draft["rows"] = []
            try:
                bars = cycle.seal_bars(draft, case)
                outputs = cycle.run_cycle(bundle_dir=closure, case=case, bars=bars,
                    outcomes=outcomes, generated_at="2026-08-28T16:10:00+00:00")
            except (cycle.CycleError, IndexError) as exc:
                self.fail(f"covered empty series must produce a degraded cycle: {exc}")
            trace, snapshot, _, review = outputs
            self.assertEqual(trace["final_state"], "EXPIRED")
            self.assertEqual(snapshot["fund"]["cash"], fund.INITIAL_CAPITAL)
            self.assertEqual(snapshot["nav_history"], [])
            self.assertIsNone(review["fill_date"])
            self.assertIsNone(review["paper_return"])
            self.assertEqual(len(review["nav_missing_sessions"]), 11)
            self.assertEqual(snapshot["performance"]["nav_quality"], "DATA_BLOCKED")
            self.assertIsNone(snapshot["performance"]["nav"])
            self.assertFalse(trace["claim_allowed"])
            bundle = Path(tmp) / "cycle"
            cycle._write_cycle_outputs(bundle, closure, case, bars, outcomes, *outputs)
            self.assertTrue(cycle.verify_cycle_bundle(bundle, closure))
            legacy = copy.deepcopy(case)
            legacy["schema_version"] = "1.0"
            draft["schema_version"] = "1.0"
            draft.pop("scoring_as_of")
            with self.assertRaises(cycle.CycleError):
                cycle.seal_bars(draft, legacy)

    def test_filled_corporate_freeze_delivers_blocked_cycle_without_nav(self):
        with tempfile.TemporaryDirectory() as tmp:
            closure, case = new_case(Path(tmp))
            bars, outcomes = replay_inputs(case)
            for row in bars["rows"][2:]:
                row.update(open=50., high=52., low=49., close=50., pre_close=50.)
            bars["rows_hash"] = digest(bars["rows"])
            try:
                outputs = cycle.run_cycle(bundle_dir=closure, case=case, bars=bars,
                    outcomes=outcomes, generated_at="2026-08-28T16:10:00+00:00")
            except fund.CorporateActionUnresolved as exc:
                self.fail(f"frozen NAV must stay unavailable without losing the cycle: {exc}")
            trace, snapshot, _, review = outputs
            order = snapshot["orders"][0]
            self.assertEqual(trace["final_state"], "FILLED")
            self.assertTrue(order["execution_frozen"])
            self.assertIsNone(order.get("exit_date"))
            self.assertIsNone(review["paper_return"])
            self.assertEqual(order["deadline_attempts"][-1]["reason"], "CORPORATE_ACTION_BREAK")
            self.assertEqual(review["horizons"]["T+10"]["status"], "DATA_BLOCKED")
            self.assertEqual(snapshot["nav_history"][-1]["date"], "20260817")
            self.assertEqual(snapshot["performance"]["nav_quality"], "DATA_BLOCKED")
            self.assertIsNone(snapshot["performance"]["nav"])
            self.assertTrue(all(row["reason"] == "CORPORATE_ACTION_BREAK"
                                for row in snapshot["performance"]["unavailable_sessions"]))
            bundle = Path(tmp) / "cycle"
            cycle._write_cycle_outputs(bundle, closure, case, bars, outcomes, *outputs)
            self.assertTrue(cycle.verify_cycle_bundle(bundle, closure))

    def test_recorded_missing_bar_attempt_replays_from_publication_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            closure, case = new_case(Path(tmp))
            bars, outcomes = replay_inputs(case, missing_due=True)
            state = {"cash": fund.INITIAL_CAPITAL, "initial_capital": fund.INITIAL_CAPITAL,
                     "paper_only": True}
            orders, log = [], []
            order, message = fund.register_order(state, orders, log, ticker=case["ticker"],
                name=case["name"], theme=case["theme"], setup="RECLAIM", registered_at="20260813",
                entry=100., stop=95., target=115., risk_pct=.005, reason="Synthetic T10 replay",
                max_fill_price=101., cost_model=fund.WORKFLOW_DEBUG_COST_MODEL,
                execution_mode=fund.pp.EXECUTION_MODEL_VERSION, deadline_policy=deadline_policy())
            self.assertIsNotNone(order, message)
            before = {"fund.json": copy.deepcopy(state), "orders.json": copy.deepcopy(orders),
                      "decision_log.json": copy.deepcopy(log)}
            context = {"target_trade_date": "20260828", "run_id": "T10_SYNTHETIC"}
            fund.process_day(state, orders, log, None, series_fn=lambda *_: copy.deepcopy(bars["rows"]),
                             recording=context)
            self.assertEqual(order["status"], "filled")
            self.assertTrue(order.get("deadline_attempts"))
            after = {"fund.json": state, "orders.json": orders, "decision_log.json": log}
            errors, _, _ = publish._check_paper_settlement(before, after, "20260828", "T10_SYNTHETIC")
            self.assertEqual(errors, [])
            snapshot = copy.deepcopy((state, orders, log))
            fund.process_day(state, orders, log, None, series_fn=lambda *_: copy.deepcopy(bars["rows"]),
                             recording=context)
            self.assertEqual((state, orders, log), snapshot)


class T10PublicationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / "T10_P1_SYNTHETIC"
        self.et = self.run / "staging" / "repo" / "experiments" / "execution_tracker"
        self.state = {"cash": fund.INITIAL_CAPITAL,
                      "initial_capital": fund.INITIAL_CAPITAL, "paper_only": True}
        self.orders, self.log = [], []
        self.order, message = fund.register_order(
            self.state, self.orders, self.log, ticker="000001.SZ", name="Synthetic",
            theme="OFFLINE_FIXTURE", setup="RECLAIM", registered_at="20260813",
            entry=100., stop=95., target=115., risk_pct=.005, reason="P1 regression",
            max_fill_price=101., cost_model=fund.WORKFLOW_DEBUG_COST_MODEL,
            execution_mode=fund.pp.EXECUTION_MODEL_VERSION, deadline_policy=deadline_policy())
        self.assertIsNotNone(self.order, message)
        self.snapshot()

    def write(self):
        for name, value in (("fund.json", self.state), ("orders.json", self.orders),
                            ("decision_log.json", self.log)):
            publish.atomic_json(str(self.et / "model_fund" / name), value)

    def snapshot(self):
        self.write()
        publish.atomic_json(str(self.run / "staging_input.json"), {
            "protected": {"model_fund": publish._tree_hashes(str(self.et / "model_fund"))},
            "protected_content": {"model_fund": {
                "fund.json": copy.deepcopy(self.state), "orders.json": copy.deepcopy(self.orders),
                "decision_log.json": copy.deepcopy(self.log)}},
        })

    def advance(self, target="20260818", rows=()):
        fund.process_day(self.state, self.orders, self.log, None,
                         series_fn=lambda *_: copy.deepcopy(list(rows)),
                         recording={"target_trade_date": target, "run_id": self.run.name})

    def errors(self, target="20260818"):
        self.write()
        return publish.verify_protected_inputs(str(self.et), str(self.run), target)

    def test_bound_pending_stop_refuses_before_initial_settlement(self):
        before = copy.deepcopy((self.state, self.orders, self.log))
        accepted, reason = fund.tighten_stop(self.orders, self.log, self.order["ticker"],
                                            96., "20260813", "unsupported amendment")
        self.assertFalse(accepted, reason)
        self.assertIn("deadline", reason)
        self.assertEqual((self.state, self.orders, self.log), before)
        self.assertNotIn("deadline_state", self.order)

    def test_bound_stop_refusal_preserves_next_and_deadline_settlement(self):
        days = [row["date"] for row in deadline_policy()["calendar"]["days"]
                if row["is_open"] and "20260814" <= row["date"] <= "20260828"]
        bars = [fixtures.execution_row(day, 100., 102., 98., 100., pre_close=100.)
                for day in days]
        self.advance(days[0], bars[:1])
        self.assertEqual(self.order["status"], "filled")
        before = copy.deepcopy((self.state, self.orders, self.log))
        accepted, reason = fund.tighten_stop(self.orders, self.log, self.order["ticker"],
                                            96., days[0], "unsupported amendment")
        self.assertFalse(accepted, reason)
        self.assertEqual((self.state, self.orders, self.log), before)
        self.snapshot()
        self.advance(days[1], bars[:2])
        self.assertEqual(self.errors(days[1]), [])
        self.snapshot()
        self.advance(days[-1], bars)
        self.assertEqual(self.order["status"], "closed")
        self.assertEqual(self.order["exit_reason"], "deadline_close")
        self.assertEqual(self.order["stop_reference"], 95.)
        self.assertEqual(self.errors(days[-1]), [])

    def test_price_only_stop_tightening_keeps_original_behavior(self):
        self.order.pop("deadline_policy")
        self.order.pop("deadline_policy_bound_at")
        original_policy = copy.deepcopy(self.order)
        accepted, reason = fund.tighten_stop(self.orders, self.log, self.order["ticker"],
                                            96., "20260814", "legacy trail")
        self.assertTrue(accepted, reason)
        self.assertEqual(self.order, {**original_policy, "stop_reference": 96.})
        self.assertEqual(self.log[-1]["action"], "TIGHTEN_STOP")
        before = copy.deepcopy((self.orders, self.log))
        accepted, _ = fund.tighten_stop(self.orders, self.log, self.order["ticker"],
                                       94., "20260814", "forbidden loosen")
        self.assertFalse(accepted)
        self.assertEqual((self.orders, self.log), before)

    def test_real_expiry_passes_full_publication_without_cash_or_fake_fill(self):
        self.advance()
        self.assertEqual(self.order["status"], "expired")
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.state["cash"], fund.INITIAL_CAPITAL)
        for key in ("fill_price", "fill_date", "exit_price", "exit_date", "pnl_cny", "paper_return"):
            self.assertIsNone(self.order[key])
        self.assertEqual(self.log[-1]["action"], "PAPER_EXPIRED_UNFILLED")
        before = copy.deepcopy((self.state, self.orders, self.log))
        self.advance()
        self.assertEqual((self.state, self.orders, self.log), before)

    def test_unchanged_expired_order_is_known_terminal_next_publication(self):
        self.advance()
        self.snapshot()
        before = copy.deepcopy((self.state, self.orders, self.log))
        self.advance("20260819")
        self.assertEqual((self.state, self.orders, self.log), before)
        self.assertEqual(self.errors("20260819"), [])

    def test_expiry_requires_a_new_receipt_even_on_publication_date(self):
        self.advance()
        self.order.pop("settlement_receipt")
        self.log[:] = self.log[:1]
        self.assertTrue(self.errors())

    def test_expiry_cannot_borrow_the_previous_pending_receipt(self):
        self.advance("20260814")
        old_receipt = copy.deepcopy(self.order["settlement_receipt"])
        self.snapshot()
        old_log = copy.deepcopy(self.log)
        self.advance()
        self.order["settlement_receipt"] = old_receipt
        self.log[:] = old_log
        self.assertTrue(self.errors())

    def test_expiry_cash_and_receipt_tampering_still_refuse(self):
        self.advance()
        valid_order, valid_log = copy.deepcopy((self.order, self.log))
        for fault in ("cash", "receipt", "expiry_date", "pnl", "missing_event"):
            with self.subTest(fault=fault):
                self.order.clear()
                self.order.update(copy.deepcopy(valid_order))
                self.log[:] = copy.deepcopy(valid_log)
                self.state["cash"] = fund.INITIAL_CAPITAL
                if fault == "cash":
                    self.state["cash"] += 100.
                elif fault == "receipt":
                    self.order["settlement_receipt"]["bars_hash"] = "0" * 64
                elif fault == "expiry_date":
                    self.order["expiry_date"] = "20260817"
                elif fault == "pnl":
                    self.order["pnl_cny"] = 100.
                else:
                    self.log.pop()
                self.assertTrue(self.errors())

    def test_expired_transition_is_terminal_and_filled_cannot_expire(self):
        self.advance()
        expired = copy.deepcopy(self.order)
        self.assertEqual(publish._check_orders([expired], [expired]), [])
        for status in ("pending", "filled", "closed", "cancelled"):
            with self.subTest(status=status):
                errors = publish._check_orders([expired], [{**expired, "status": status}])
                self.assertTrue(any("非法迁移" in item for item in errors), errors)
        errors = publish._check_orders([{**expired, "status": "filled"}], [expired])
        self.assertTrue(any("非法迁移" in item for item in errors), errors)

    def test_new_unregistered_expired_row_cannot_be_appended(self):
        self.advance()
        self.snapshot()
        self.orders.append({**copy.deepcopy(self.order), "entry_id": "forged-new-expiry"})
        self.orders[-1].pop("settlement_receipt")
        self.assertTrue(self.errors())

    def test_persisted_expiry_evidence_is_immutable(self):
        self.advance()
        self.snapshot()
        expired = copy.deepcopy(self.order)
        for field, value in (("expiry_date", "20260817"), ("pnl_cny", 100.),
                             ("stop_reference", 96.)):
            with self.subTest(field=field):
                self.order.clear()
                self.order.update(copy.deepcopy(expired))
                self.order[field] = value
                self.assertTrue(self.errors("20260819"))

    def test_expiry_counts_are_explicit_and_excluded_from_closed_samples(self):
        for expected in (0, 1):
            if expected:
                self.advance()
            for result in (fund.compute_performance(self.state, self.orders, []),
                           fund.pp.summarize(self.orders)):
                with self.subTest(expected=expected, result=result):
                    self.assertEqual(result.get("n_expired"), expected)
                    self.assertEqual(result["n_pending"], 1 - expected)
                    self.assertEqual(result["n_closed"], 0)
                    self.assertEqual(result["n_claim_eligible"], 0)
                    self.assertIsNone(result["win_rate"])
                    self.assertFalse(result["claim_allowed"])

    def test_price_only_summary_bytes_remain_unchanged(self):
        self.order.pop("deadline_policy")
        self.order.pop("deadline_policy_bound_at")
        # Captured from untouched 329933c with one pending price-only order.
        self.assertEqual(fund.settlement_hash(fund.compute_performance(self.state, self.orders, [])),
                         "afffa78433a149ddb0a7f59a4ae5f76a15c6c63a23bf74cb5bb943933ba96803")
        self.assertEqual(fund.settlement_hash(fund.pp.summarize(self.orders)),
                         "8fa153ee5a04e609d334058e23c1aeb3144773c35c22f822f01202bf006a8c1b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
