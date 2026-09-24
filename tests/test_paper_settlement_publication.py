#!/usr/bin/env python3
"""Settlement replay binds catch-up event time to the current publication."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))
import model_paper_fund as engine
import nightly_publish as publish

TARGET = "20260907"
RID = "20260907_fixture"


def fixture():
    fund = {"cash": 900000.0, "initial_capital": 1000000.0, "paper_only": True}
    order = {
        "ticker": "600001.SH", "name": "Fixture", "registered_at": "20260820",
        "setup": "RECLAIM", "status": "filled", "shares": 1000,
        "entry_reference": 100.0, "stop_reference": 95.0, "take_profit_reference": 115.0,
        "fill_date": "20260821", "fill_price": 100.0,
        "exit_date": None, "exit_price": None, "exit_reason": None,
        "no_trade_flag": True,
    }
    bars = [
        {"date": "20260903", "open": 105.0, "high": 110.0, "low": 103.0, "close": 108.0},
        {"date": "20260904", "open": 110.0, "high": 116.0, "low": 108.0, "close": 115.0},
    ]
    return fund, [order], [{"date": "20260820", "action": "REGISTER_ORDER"}], bars


class PaperSettlementPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / RID
        self.et = self.run / "staging" / "repo" / "experiments" / "execution_tracker"
        self.fund, self.orders, self.log, self.bars = fixture()
        self.before = {"fund.json": copy.deepcopy(self.fund),
                       "orders.json": copy.deepcopy(self.orders),
                       "decision_log.json": copy.deepcopy(self.log)}
        self.write()
        publish.atomic_json(str(self.run / "staging_input.json"), {
            "protected": {"model_fund": publish._tree_hashes(str(self.et / "model_fund"))},
            "protected_content": {"model_fund": self.before},
        })

    def write(self):
        for name, value in (("fund.json", self.fund), ("orders.json", self.orders),
                            ("decision_log.json", self.log)):
            publish.atomic_json(str(self.et / "model_fund" / name), value)

    def advance(self):
        engine.process_day(self.fund, self.orders, self.log, None,
                           series_fn=lambda *_: copy.deepcopy(self.bars),
                           recording={"target_trade_date": TARGET, "run_id": RID})
        self.write()

    def errors(self):
        self.write()
        return publish.verify_protected_inputs(str(self.et), str(self.run), TARGET)

    def test_historical_exit_is_replayed_without_relabeling_event_date(self):
        self.advance()
        self.assertEqual(self.log[-1]["date"], "20260904")
        self.assertEqual(self.log[-1]["action"], "PAPER_EXIT")
        self.assertEqual(self.fund["cash"], 1015000.0)
        self.assertEqual(self.errors(), [])

    def test_legacy_backdated_row_without_receipt_still_refuses(self):
        engine.process_day(self.fund, self.orders, self.log, None,
                           series_fn=lambda *_: self.bars)
        self.assertTrue(self.errors())

    def test_future_bars_refuse_before_any_state_mutation(self):
        self.bars[-1]["date"] = "20260908"
        with self.assertRaises(ValueError):
            self.advance()
        self.assertEqual(self.fund, self.before["fund.json"])
        self.assertEqual(self.orders, self.before["orders.json"])
        self.assertEqual(self.log, self.before["decision_log.json"])

    def test_recording_run_cannot_be_rebound(self):
        self.advance()
        self.orders[0]["settlement_receipt"]["recording"]["run_id"] = "other_run"
        self.assertTrue(self.errors())

    def test_recording_target_cannot_be_rebound(self):
        self.advance()
        self.orders[0]["settlement_receipt"]["recording"]["target_trade_date"] = "20260908"
        self.assertTrue(self.errors())

    def test_original_order_hash_is_not_self_reported_authority(self):
        self.advance()
        self.orders[0]["settlement_receipt"]["before_order_hash"] = "0" * 64
        self.log[-1]["settlement_order_hash"] = "0" * 64
        self.assertTrue(self.errors())

    def test_order_fields_are_replayed_even_when_event_is_unchanged(self):
        self.advance()
        self.orders[0]["net_pnl_cny"] = 999999.0
        self.assertTrue(self.errors())

    def test_changed_bars_require_matching_hash(self):
        self.advance()
        self.orders[0]["settlement_receipt"]["bars"][0]["close"] = 107.0
        self.assertTrue(self.errors())

    def test_resealed_bars_must_still_explain_order(self):
        self.advance()
        receipt = self.orders[0]["settlement_receipt"]
        receipt["bars"][-1]["high"] = 114.0
        receipt["bars_hash"] = engine.settlement_hash(receipt["bars"])
        self.assertTrue(self.errors())

    def test_resealed_future_bars_refuse_at_publication(self):
        self.advance()
        receipt = self.orders[0]["settlement_receipt"]
        receipt["bars"].append({**self.bars[-1], "date": "20260908"})
        receipt["bars_hash"] = engine.settlement_hash(receipt["bars"])
        self.assertTrue(self.errors())

    def test_forged_event_price_cannot_borrow_valid_receipt(self):
        self.advance()
        self.log[-1]["price"] = 116.0
        self.assertTrue(self.errors())

    def test_missing_event_refuses_even_when_log_is_unchanged(self):
        self.advance()
        self.log.pop()
        self.assertTrue(self.errors())

    def test_duplicate_event_refuses(self):
        self.advance()
        self.log.append(copy.deepcopy(self.log[-1]))
        self.assertTrue(self.errors())

    def test_removing_both_receipt_and_event_cannot_hide_historical_transition(self):
        self.advance()
        self.orders[0].pop("settlement_receipt")
        self.log.pop()
        self.assertTrue(self.errors())

    def test_unrelated_backdated_action_does_not_get_exception(self):
        self.advance()
        self.log.append({"date": "20260904", "action": "TIGHTEN_STOP", "ticker": "600001.SH"})
        self.assertTrue(self.errors())

    def test_old_decision_rows_still_immutable(self):
        self.advance()
        self.log[0]["date"] = TARGET
        self.assertTrue(self.errors())

    def test_missing_receipt_order_cannot_authorize_event(self):
        self.advance()
        self.orders[:] = copy.deepcopy(self.before["orders.json"])
        self.fund.update(self.before["fund.json"])
        self.assertTrue(self.errors())

    def test_cash_must_match_replay_including_when_unchanged(self):
        self.advance()
        self.fund["cash"] = 900000.0
        self.assertTrue(self.errors())

    def test_receipt_schema_is_closed(self):
        self.advance()
        self.orders[0]["settlement_receipt"]["authority"] = True
        self.assertTrue(self.errors())

    def test_realistic_execution_costs_are_replayed_not_gross_approximated(self):
        from test_paper_execution_realism import registered_order, bar
        self.fund, self.orders, self.log, _ = registered_order()
        self.before = {"fund.json": copy.deepcopy(self.fund),
                       "orders.json": copy.deepcopy(self.orders),
                       "decision_log.json": copy.deepcopy(self.log)}
        self.write()
        publish.atomic_json(str(self.run / "staging_input.json"), {
            "protected": {"model_fund": publish._tree_hashes(str(self.et / "model_fund"))},
            "protected_content": {"model_fund": self.before},
        })
        self.bars = [bar("20260821", 99.0, 102.0, 98.0, 101.0),
                     bar("20260824", 110.0, 116.0, 108.0, 115.0, pre_close=101.0)]
        self.advance()
        self.assertGreater(self.orders[0]["exit_fees_cny"], 0)
        self.assertEqual(self.errors(), [])
        self.fund["cash"] += self.orders[0]["exit_fees_cny"]
        self.assertTrue(self.errors())

    def test_two_orders_failure_does_not_partially_commit(self):
        second = copy.deepcopy(self.orders[0])
        second["ticker"] = "600002.SH"
        self.orders.append(second)
        before = copy.deepcopy((self.fund, self.orders, self.log))
        def loader(ticker, *_):
            if ticker == "600002.SH":
                raise OSError("source unavailable")
            return self.bars
        with self.assertRaises(OSError):
            engine.process_day(self.fund, self.orders, self.log, None, series_fn=loader,
                               recording={"target_trade_date": TARGET, "run_id": RID})
        self.assertEqual((self.fund, self.orders, self.log), before)

    def test_replay_retry_of_closed_order_adds_no_event(self):
        self.advance()
        before = copy.deepcopy((self.fund, self.orders, self.log))
        self.advance()
        self.assertEqual((self.fund, self.orders, self.log), before)

    def test_cli_source_failure_refuses_before_any_projection_write(self):
        second = copy.deepcopy(self.orders[0])
        second.update(ticker="600002.SH", status="pending", fill_date=None,
                      fill_price=None, entry_review_price=100.0)
        self.orders.append(second)
        self.write()
        directory = self.et / "model_fund"
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        def loader(ticker, *_):
            if ticker == "600002.SH":
                raise OSError("fixture source unavailable")
            return self.bars + [{**self.bars[-1], "date": TARGET}]
        with mock.patch.dict("os.environ", {"TUSHARE_TOKEN": "fixture", "AR_OFFLINE": "",
                                              "AR_RUN_ID": RID, "AR_TARGET_TRADE_DATE": TARGET}), \
                mock.patch.object(sys, "argv", ["model_paper_fund", "--daily", "--fund-dir",
                                                str(directory)]), \
                mock.patch.object(engine, "assert_paper_registration_ready"), \
                mock.patch.object(engine.pp, "qfq_ohlc_series", side_effect=loader):
            code = engine.main()
        self.assertNotEqual(code, 0)
        self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir()}, before)

    def test_cli_daily_passes_exact_nightly_recording_context(self):
        observed = []
        def capture(*args, **kwargs):
            observed.append(kwargs.get("recording"))
            return []
        with mock.patch.dict("os.environ", {"TUSHARE_TOKEN": "fixture", "AR_OFFLINE": "",
                                              "AR_RUN_ID": RID, "AR_TARGET_TRADE_DATE": TARGET}), \
                mock.patch.object(sys, "argv", ["model_paper_fund", "--daily", "--fund-dir",
                                                str(self.et / "model_fund")]), \
                mock.patch.object(engine, "assert_paper_registration_ready"), \
                mock.patch.object(engine, "process_day", side_effect=capture) as advance, \
                mock.patch.object(engine.pp, "qfq_ohlc_series", return_value=[
                    {"date": TARGET, "close": 108.0}]):
            self.assertEqual(engine.main(), 0)
            self.assertEqual(advance.call_count, 1)
        self.assertEqual(observed, [{"target_trade_date": TARGET, "run_id": RID}])

    def test_missing_nav_preserves_due_attempt_and_other_exit_for_publication(self):
        from test_paper_t10_integration import deadline_policy
        from test_research_cycle import execution_row

        fund = {"cash": 1_000_000.0, "initial_capital": 1_000_000.0, "paper_only": True}
        orders, log = [], []
        for ticker in ("000001.SZ", "000002.SZ"):
            order, reason = engine.register_order(
                fund, orders, log, ticker=ticker, name=ticker, theme="FIXTURE",
                setup="RECLAIM", registered_at="20260813", entry=100.0,
                stop=95.0, target=115.0, risk_pct=0.005,
                reason="Synthetic T+10 publication", max_fill_price=101.0,
                cost_model=engine.WORKFLOW_DEBUG_COST_MODEL,
                execution_mode=engine.pp.EXECUTION_MODEL_VERSION,
                deadline_policy=deadline_policy(),
            )
            self.assertIsNotNone(order, reason)
        session_days = [row["date"] for row in deadline_policy()["calendar"]["days"]
                        if row["is_open"] and row["date"] > "20260813"]
        entry = execution_row(session_days[0], 100, 102, 98, 100, pre_close=100)
        engine.process_day(fund, orders, log, None,
                           series_fn=lambda *_: [entry],
                           recording={"target_trade_date": session_days[0],
                                      "run_id": "INITIAL_FIXTURE"})
        self.assertTrue(all(order["status"] == "filled" for order in orders))
        due = orders[0]["deadline_due_date"]
        previous = [execution_row(day, 100, 102, 98, 100, pre_close=100)
                    for day in session_days if day < due]
        exit_bar = execution_row(due, 110, 116, 108, 115, pre_close=100)
        rows = {"000001.SZ": previous, "000002.SZ": previous + [exit_bar]}
        nav = []
        engine.update_nav(fund, orders, nav, session_days[0],
                          marks={ticker: 100.0 for ticker in rows},
                          require_complete_marks=True)
        directory = self.et / "model_fund"
        for name, value in (("fund.json", fund), ("orders.json", orders),
                            ("decision_log.json", log), ("nav_history.json", nav)):
            publish.atomic_json(str(directory / name), value)
        before = {name: copy.deepcopy(value) for name, value in
                  (("fund.json", fund), ("orders.json", orders),
                   ("decision_log.json", log), ("nav_history.json", nav))}
        publish.atomic_json(str(self.run / "staging_input.json"), {
            "protected": {"model_fund": publish._tree_hashes(str(directory))},
            "protected_content": {"model_fund": before},
        })

        def daily():
            with mock.patch.dict("os.environ", {"TUSHARE_TOKEN": "fixture", "AR_OFFLINE": "",
                                                "AR_RUN_ID": RID, "AR_TARGET_TRADE_DATE": due}), \
                    mock.patch.object(sys, "argv", ["model_paper_fund", "--daily",
                                                    "--fund-dir", str(directory)]), \
                    mock.patch.object(engine, "assert_paper_registration_ready"), \
                    mock.patch.object(engine.pp, "execution_ohlc_series",
                                      side_effect=lambda ticker, *_: copy.deepcopy(rows[ticker])), \
                    mock.patch.object(engine.pp, "qfq_ohlc_series",
                                      return_value=copy.deepcopy(previous)):
                return engine.main()

        self.assertEqual(daily(), 0)
        after_orders = engine.load("orders.json", [], str(directory))
        after_log = engine.load("decision_log.json", [], str(directory))
        after_nav = engine.load("nav_history.json", [], str(directory))
        self.assertEqual(after_orders[0]["deadline_attempts"][-1]["reason"], "MISSING_BAR")
        self.assertEqual(after_orders[1]["status"], "closed")
        self.assertTrue(any(row["action"] == "PAPER_DEADLINE_ATTEMPT" for row in after_log))
        self.assertTrue(any(row["action"] == "PAPER_EXIT" for row in after_log))
        self.assertEqual(after_nav[-1]["date"], due)
        self.assertIsNone(after_nav[-1]["nav"])
        self.assertEqual(after_nav[-1]["status"], "DATA_BLOCKED")
        self.assertEqual(publish.verify_protected_inputs(str(self.et), str(self.run), due), [])
        import export_contracts
        with mock.patch.object(export_contracts, "HERE", str(self.et)), \
                mock.patch.dict("os.environ", {"AR_TARGET_TRADE_DATE": due}):
            portfolio = export_contracts.build_model_portfolio_state()
        self.assertEqual(portfolio["pipeline_status"], "OK")
        self.assertEqual(portfolio["data_quality"], "BLOCKED")
        self.assertEqual(portfolio["data"]["nav_latest"]["nav"], None)
        self.assertEqual(engine.compute_performance(
            engine.load("fund.json", None, str(directory)), after_orders, after_nav
        )["nav"], None)
        files = {path.name: path.read_bytes() for path in directory.iterdir()}
        self.assertEqual(daily(), 0)
        self.assertEqual({path.name: path.read_bytes() for path in directory.iterdir()}, files)
        next_day = next(row["date"] for row in deadline_policy()["calendar"]["days"]
                       if row["is_open"] and row["date"] > due)
        rows["000001.SZ"] = previous + [execution_row(
            next_day, 105, 110, 103, 108, pre_close=100)]
        next_orders = copy.deepcopy(after_orders)
        next_log = copy.deepcopy(after_log)
        next_fund = engine.load("fund.json", None, str(directory))
        engine.process_day(next_fund, next_orders, next_log, None,
                           series_fn=lambda ticker, *_: copy.deepcopy(rows[ticker]),
                           recording={"target_trade_date": next_day, "run_id": "NEXT_RUN"})
        self.assertEqual(next_orders[0]["status"], "closed")
        self.assertEqual(len(next_orders[0]["deadline_attempts"]), 2)
        self.assertEqual(next_orders[0]["deadline_attempts"][0]["reason"], "MISSING_BAR")
        after_nav[-1]["status"] = "COMPLETE"
        publish.atomic_json(str(directory / "nav_history.json"), after_nav)
        self.assertEqual(daily(), 1)

    def test_daily_projection_crash_replays_or_rejects_without_mixed_files(self):
        directory = self.et / "model_fund"
        publish.atomic_json(str(directory / "nav_history.json"), [])
        before = {name: (directory / name).read_bytes() for name in engine._DAILY_PROJECTIONS}
        after_fund = {**self.fund, "cash": self.fund["cash"] + 100.0}
        after_log = self.log + [{"date": TARGET, "action": "PAPER_DEADLINE_ATTEMPT",
                                 "ticker": "600001.SH", "no_trade_flag": True}]
        after_nav = [{"date": TARGET, "nav": None, "cash": after_fund["cash"],
                      "n_positions": 1, "daily_return": None, "cum_return": None,
                      "status": "DATA_BLOCKED", "reason": "MISSING_TARGET_CLOSE",
                      "missing_tickers": ["600001.SH"]}]
        original_save = engine.save

        def crash(name, obj, root=None):
            if name == "orders.json":
                raise OSError("crash after first projection")
            return original_save(name, obj, root)

        with mock.patch.object(engine, "save", side_effect=crash):
            with self.assertRaisesRegex(OSError, "crash after first projection"):
                engine._commit_daily_projections(str(directory), TARGET, RID,
                                                 after_fund, self.orders, after_log, after_nav)
        self.assertNotEqual((directory / "fund.json").read_bytes(), before["fund.json"])
        self.assertTrue((directory / engine._DAILY_INTENT).exists())
        with self.assertRaisesRegex(ValueError, "bound to another run"):
            engine._finish_daily_intent(str(directory), expected_target=TARGET,
                                        expected_run="OTHER_RUN")
        self.assertEqual((directory / "orders.json").read_bytes(), before["orders.json"])
        self.assertTrue(engine._finish_daily_intent(str(directory)))
        self.assertFalse((directory / engine._DAILY_INTENT).exists())
        self.assertEqual(engine.load("fund.json", None, str(directory)), after_fund)
        self.assertEqual(engine.load("decision_log.json", None, str(directory)), after_log)
        snapshot = {name: (directory / name).read_bytes() for name in engine._DAILY_PROJECTIONS}
        self.assertFalse(engine._finish_daily_intent(str(directory)))
        self.assertEqual(snapshot, {name: (directory / name).read_bytes()
                                    for name in engine._DAILY_PROJECTIONS})

        with mock.patch.object(engine, "save", side_effect=crash):
            with self.assertRaises(OSError):
                engine._commit_daily_projections(str(directory), "20260908", "NEXT",
                                                 after_fund, self.orders, after_log, after_nav)
        publish.atomic_json(str(directory / "orders.json"), [{"unexpected": "state"}])
        with self.assertRaisesRegex(ValueError, "differs from both intent states"):
            engine._finish_daily_intent(str(directory))

    def test_blocked_nav_requires_matching_open_position_and_cash_at_publication(self):
        directory = self.et / "model_fund"
        previous = [{"date": "20260904", "nav": 1000000.0, "cash": 900000.0,
                     "n_positions": 1, "daily_return": 0.0, "cum_return": 0.0}]
        publish.atomic_json(str(directory / "nav_history.json"), previous)
        before = {**self.before, "nav_history.json": previous}
        publish.atomic_json(str(self.run / "staging_input.json"), {
            "protected": {"model_fund": publish._tree_hashes(str(directory))},
            "protected_content": {"model_fund": before},
        })
        blocked = engine.record_unavailable_nav(self.fund, self.orders, previous, TARGET,
                                                ["600001.SH"])
        publish.atomic_json(str(directory / "nav_history.json"), previous)
        self.assertEqual(publish.verify_protected_inputs(str(self.et), str(self.run), TARGET), [])
        for key, value in (("status", "COMPLETE"), ("missing_tickers", ["600099.SH"]),
                           ("cash", 1.0), ("cum_return", 0.0)):
            with self.subTest(field=key):
                altered = copy.deepcopy(previous)
                altered[-1][key] = value
                publish.atomic_json(str(directory / "nav_history.json"), altered)
                self.assertTrue(publish.verify_protected_inputs(str(self.et), str(self.run), TARGET))
        self.assertEqual(blocked["reason"], "MISSING_TARGET_CLOSE")

    def test_return_after_blocked_day_does_not_claim_one_day_gain(self):
        history = [{"date": "20260904", "nav": 1000000.0},
                   {"date": "20260907", "nav": None, "status": "DATA_BLOCKED"}]
        rec = engine.update_nav(self.fund, self.orders, history, "20260908",
                                marks={"600001.SH": 108.0}, require_complete_marks=True)
        self.assertIsNone(rec["daily_return"])
        self.assertEqual(rec["cum_return"], 0.008)

    def test_promoter_emits_no_ready_proposal_when_nav_is_blocked(self):
        import setup_promoter as promoter
        directory = self.et / "model_fund"
        publish.atomic_json(str(directory / "nav_history.json"), [
            {"date": TARGET, "nav": None, "cash": self.fund["cash"],
             "n_positions": 1, "daily_return": None, "cum_return": None,
             "status": "DATA_BLOCKED", "reason": "MISSING_TARGET_CLOSE",
             "missing_tickers": ["600001.SH"]},
        ])
        publish.atomic_json(str(self.et / "paper_signal_log.json"), [
            {"ticker": "600001.SH", "setup_type": "execution_gate",
             "outcome_status": "pending", "official_sample": False},
        ])
        with mock.patch.dict("os.environ", {"TUSHARE_TOKEN": "fixture",
                                              "AR_TARGET_TRADE_DATE": TARGET,
                                              "AR_RUN_ID": RID}), \
                mock.patch.object(sys, "argv", ["setup_promoter"]), \
                mock.patch.object(promoter, "HERE", str(self.et)), \
                mock.patch.object(promoter, "OUT", str(self.et / "promotion_queue.json")), \
                mock.patch.object(promoter, "load_qc_context", return_value={}), \
                mock.patch("glob.glob", return_value=[str(self.et / "sample.json")]), \
                mock.patch.object(engine.pp, "qfq_ohlc_series",
                                  side_effect=AssertionError("no market call")):
            promoter.main()
        result = json.loads((self.et / "promotion_queue.json").read_text())
        self.assertEqual(result["queue"], [])
        self.assertEqual(result["nav_quality"], "DATA_BLOCKED")
        self.assertEqual([row["ticker"] for row in result["data_blocked"]], ["600001.SH"])

    def test_weekly_recap_never_computes_return_across_blocked_nav(self):
        import weekly_recap
        directory = self.et / "model_fund"
        publish.atomic_json(str(directory / "nav_history.json"), [
            {"date": "20260904", "nav": None, "cash": self.fund["cash"]},
            {"date": TARGET, "nav": 1008000.0, "cash": self.fund["cash"]},
        ])
        text = weekly_recap.build_recap("20260904", TARGET, fund_dir=str(directory),
                                        tracker_dir=str(self.et))
        self.assertIn("单日或缺值,不计", text)

    def test_portfolio_contract_keeps_historical_nav_gap_visible(self):
        import export_contracts
        directory = self.et / "model_fund"
        publish.atomic_json(str(directory / "nav_history.json"), [
            {"date": "20260903", "nav": None, "cash": self.fund["cash"],
             "n_positions": 1, "daily_return": None, "cum_return": None,
             "status": "DATA_BLOCKED", "reason": "MISSING_TARGET_CLOSE",
             "missing_tickers": ["600001.SH"]},
            {"date": TARGET, "nav": 1008000.0, "cash": self.fund["cash"],
             "n_positions": 1, "daily_return": None, "cum_return": 0.008},
        ])
        with mock.patch.object(export_contracts, "HERE", str(self.et)), \
                mock.patch.dict("os.environ", {"AR_TARGET_TRADE_DATE": TARGET}):
            contract = export_contracts.build_model_portfolio_state()
        self.assertEqual(contract["pipeline_status"], "OK")
        self.assertEqual(contract["data_quality"], "PARTIAL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
