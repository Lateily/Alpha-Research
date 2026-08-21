#!/usr/bin/env python3
"""Behavior-level audit of the workflow-debug A-share paper fill model."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))

import model_paper_fund as fund_engine  # noqa: E402
import paper_portfolio as fills  # noqa: E402


def bar(
    date: str, open_: float, high: float, low: float, close: float, *,
    pre_close: float = 100.0, up_limit: float = 120.0,
    down_limit: float = 80.0, volume_shares: float = 10_000_000.0,
    amount_cny: float = 1_000_000_000.0, suspended: bool = False,
) -> dict:
    return {
        "date": date, "open": open_, "high": high, "low": low, "close": close,
        "pre_close": pre_close, "up_limit": up_limit, "down_limit": down_limit,
        "volume_shares": volume_shares, "amount_cny": amount_cny,
        "suspended": suspended, "settled": True,
        "price_basis": "RAW_UNADJUSTED",
        "source": "OFFLINE_FIXTURE_SETTLED_V2",
    }


def registered_order(*, ticker: str = "600001.SH", max_fill: float = 101.0):
    fund = {
        "initial_capital": 1_000_000.0, "cash": 1_000_000.0,
        "created": "20260820", "policy": "test", "paper_only": True,
    }
    orders: list[dict] = []
    decisions: list[dict] = []
    order, message = fund_engine.register_order(
        fund, orders, decisions,
        ticker=ticker, name="Execution Fixture", theme="SEMICONDUCTOR",
        setup="SWEEP_RECLAIM", registered_at="20260820",
        entry=100.0, stop=95.0, target=115.0, risk_pct=0.01,
        reason="execution realism fixture", gate_state="RECLAIM_REVIEW",
        max_fill_price=max_fill,
        cost_model=copy.deepcopy(fund_engine.WORKFLOW_DEBUG_COST_MODEL),
        max_volume_participation=fund_engine.MAX_VOLUME_PARTICIPATION,
        execution_mode=fills.EXECUTION_MODEL_VERSION,
    )
    if order is None:
        raise AssertionError(message)
    return fund, orders, decisions, order


class PaperExecutionRealismTests(unittest.TestCase):
    def test_adjusted_or_unsettled_bar_is_rejected(self) -> None:
        row = bar("20260821", 99.0, 102.0, 98.0, 101.0)
        row["price_basis"] = "QFQ_ADJUSTED"
        with self.assertRaisesRegex(ValueError, "raw, unadjusted"):
            fills.validate_realistic_bar(row)
        row["price_basis"] = "RAW_UNADJUSTED"
        row["settled"] = False
        with self.assertRaisesRegex(ValueError, "raw, unadjusted"):
            fills.validate_realistic_bar(row)

    def test_realistic_bar_dates_must_be_ordered_unique_calendar_dates(self) -> None:
        _, _, _, order = registered_order()
        rows = [
            bar("20260822", 99.0, 102.0, 98.0, 101.0),
            bar("20260821", 99.0, 102.0, 98.0, 101.0),
        ]
        with self.assertRaisesRegex(ValueError, "strictly ordered and unique"):
            fills._advance(order, rows, require_realistic=True)
        invalid = bar("2026-08-21", 99.0, 102.0, 98.0, 101.0)
        with self.assertRaisesRegex(ValueError, "YYYYMMDD"):
            fills.validate_realistic_bar(invalid)

    def test_fill_day_stop_and_target_cannot_sell_under_t1(self) -> None:
        fund, orders, decisions, order = registered_order()
        rows = [
            bar("20260820", 98.0, 101.0, 97.0, 100.0),
            bar("20260821", 99.0, 116.0, 94.0, 100.0),
        ]
        fund_engine.process_day(
            fund, orders, decisions, None,
            series_fn=lambda *_: rows, require_realistic=True,
        )
        self.assertEqual(order["status"], "filled")
        self.assertEqual(order["fill_date"], "20260821")
        self.assertIsNone(order["exit_date"])

    def test_one_price_limit_up_does_not_fill(self) -> None:
        fund, orders, decisions, order = registered_order(max_fill=114.0)
        rows = [bar(
            "20260821", 110.0, 110.0, 110.0, 110.0,
            up_limit=110.0, down_limit=90.0,
        )]
        fund_engine.process_day(
            fund, orders, decisions, None,
            series_fn=lambda *_: rows, require_realistic=True,
        )
        self.assertEqual(order["status"], "pending")
        self.assertEqual(order["last_execution_blocker"], "ONE_PRICE_LIMIT_UP_NO_BUY")

    def test_one_price_limit_down_does_not_fake_stop_exit(self) -> None:
        fund, orders, decisions, order = registered_order()
        rows = [
            bar("20260821", 99.0, 102.0, 98.0, 101.0),
            bar(
                "20260824", 90.0, 90.0, 90.0, 90.0,
                pre_close=100.0, up_limit=110.0, down_limit=90.0,
            ),
        ]
        fund_engine.process_day(
            fund, orders, decisions, None,
            series_fn=lambda *_: rows, require_realistic=True,
        )
        self.assertEqual(order["status"], "filled")
        self.assertEqual(order["last_execution_blocker"], "ONE_PRICE_LIMIT_DOWN_NO_SELL")

    def test_liquidity_participation_cap_blocks_fill(self) -> None:
        fund, orders, decisions, order = registered_order()
        rows = [bar(
            "20260821", 99.0, 102.0, 98.0, 101.0,
            volume_shares=1_000.0, amount_cny=100_000.0,
        )]
        fund_engine.process_day(
            fund, orders, decisions, None,
            series_fn=lambda *_: rows, require_realistic=True,
        )
        self.assertEqual(order["status"], "pending")
        self.assertEqual(order["last_execution_blocker"], "LIQUIDITY_PARTICIPATION_EXCEEDED")

    def test_registered_no_chase_limit_blocks_large_gap(self) -> None:
        fund, orders, decisions, order = registered_order(max_fill=101.0)
        rows = [bar("20260821", 105.0, 106.0, 104.0, 105.0)]
        fund_engine.process_day(
            fund, orders, decisions, None,
            series_fn=lambda *_: rows, require_realistic=True,
        )
        self.assertEqual(order["status"], "pending")
        self.assertEqual(order["last_execution_blocker"], "FILL_ABOVE_REGISTERED_ENTRY_LIMIT")

        # The pre-slippage trigger is inside the registered zone, but the modeled
        # fill is not. The ceiling governs the actual fill, not merely the quote
        # observed before slippage.
        fund, orders, decisions, order = registered_order(max_fill=100.02)
        rows = [bar("20260821", 99.0, 102.0, 98.0, 101.0)]
        fund_engine.process_day(
            fund, orders, decisions, None,
            series_fn=lambda *_: rows, require_realistic=True,
        )
        self.assertEqual(order["status"], "pending")
        self.assertEqual(order["last_execution_blocker"], "FILL_ABOVE_REGISTERED_ENTRY_LIMIT")

    def test_costs_reduce_cash_and_net_pnl(self) -> None:
        fund, orders, decisions, order = registered_order()
        rows = [
            bar("20260821", 99.0, 102.0, 98.0, 101.0),
            bar("20260824", 110.0, 116.0, 108.0, 115.0, pre_close=101.0),
        ]
        fund_engine.process_day(
            fund, orders, decisions, None,
            series_fn=lambda *_: rows, require_realistic=True,
        )
        gross_pnl = order["shares"] * (order["exit_price"] - order["fill_price"])
        self.assertEqual(order["status"], "closed")
        self.assertGreater(order["entry_fees_cny"], 0)
        self.assertGreater(order["exit_fees_cny"], order["entry_fees_cny"])
        self.assertLess(order["net_pnl_cny"], gross_pnl)
        self.assertEqual(fund["cash"], 1_000_000.0 + order["net_pnl_cny"])

    def test_cost_model_cannot_be_silently_zeroed(self) -> None:
        model = copy.deepcopy(fund_engine.WORKFLOW_DEBUG_COST_MODEL)
        model["commission_rate"] = 0.0
        with self.assertRaisesRegex(ValueError, "exactly match the frozen proxy"):
            fund_engine._validate_cost_model(model)

    def test_workflow_debug_receipt_never_becomes_claim_sample(self) -> None:
        _, _, _, order = registered_order()
        receipt = fund_engine.execution_realism_receipt(order)
        self.assertEqual(receipt["status"], "PASS_WORKFLOW_DEBUG")
        self.assertFalse(receipt["method_claim_sample_eligible"])
        self.assertFalse(receipt["portfolio_promotion_eligible"])
        self.assertFalse(order["sample_eligible"])
        order["sample_eligible"] = True
        self.assertEqual(
            fund_engine.execution_realism_receipt(order)["status"],
            "DATA_BLOCKED",
        )

    def test_thirty_workflow_debug_closures_do_not_unlock_claims(self) -> None:
        fund, _, _, order = registered_order()
        closed = []
        for index in range(30):
            row = copy.deepcopy(order)
            row.update({
                "entry_id": f"debug-{index}", "status": "closed",
                "paper_return": 0.1, "realized_R": 1.0,
                "sample_eligible": False,
            })
            closed.append(row)
        result = fund_engine.compute_performance(
            fund, closed, [{"date": "20260821", "nav": 1_000_000.0}],
        )
        self.assertEqual(result["n_closed"], 30)
        self.assertEqual(result["n_claim_eligible"], 0)
        self.assertEqual(result["n_workflow_debug_closed"], 30)
        self.assertFalse(result["claim_allowed"])
        self.assertIsNone(result["win_rate"])

    def test_star_quantity_uses_200_share_minimum_then_one_share_steps(self) -> None:
        self.assertEqual(fund_engine._round_shares(199.9, "688001.SH"), 0)
        self.assertEqual(fund_engine._round_shares(245.9, "688001.SH"), 245)
        self.assertEqual(fund_engine._round_shares(245.9, "600001.SH"), 200)

    def test_execution_source_preserves_raw_prices_and_normalizes_units(self) -> None:
        original = fills.fs._tushare_call

        def fake(endpoint, _token, _params, _fields):
            if endpoint == "daily":
                return {
                    "fields": [
                        "trade_date", "open", "high", "low", "close",
                        "pre_close", "vol", "amount",
                    ],
                    "items": [["20260821", 10.0, 10.5, 9.8, 10.2, 9.9, 1234.0, 5678.0]],
                }
            if endpoint == "stk_limit":
                return {
                    "fields": ["trade_date", "up_limit", "down_limit"],
                    "items": [["20260821", 10.89, 8.91]],
                }
            raise AssertionError(endpoint)

        try:
            fills.fs._tushare_call = fake
            rows = fills.execution_ohlc_series("600001.SH", "token", "20260820")
        finally:
            fills.fs._tushare_call = original
        self.assertEqual(rows[0]["open"], 10.0)
        self.assertEqual(rows[0]["price_basis"], "RAW_UNADJUSTED")
        self.assertEqual(rows[0]["volume_shares"], 123_400.0)
        self.assertEqual(rows[0]["amount_cny"], 5_678_000.0)
        fills.validate_realistic_bar(rows[0])

    def test_realistic_portfolio_update_defaults_to_raw_execution_source(self) -> None:
        _, _, _, order = registered_order()
        calls: list[str] = []
        original_raw = fills.execution_ohlc_series
        original_qfq = fills.qfq_ohlc_series

        def raw_source(*_args):
            calls.append("raw")
            return [bar("20260821", 99.0, 102.0, 98.0, 101.0)]

        def adjusted_source(*_args):
            raise AssertionError("realistic update selected the adjusted source")

        try:
            fills.execution_ohlc_series = raw_source
            fills.qfq_ohlc_series = adjusted_source
            fills.update_portfolio([order], None, require_realistic=True)
        finally:
            fills.execution_ohlc_series = original_raw
            fills.qfq_ohlc_series = original_qfq
        self.assertEqual(calls, ["raw"])
        self.assertEqual(order["status"], "filled")


if __name__ == "__main__":
    unittest.main(verbosity=2)
