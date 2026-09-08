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


if __name__ == "__main__":
    unittest.main(verbosity=2)
