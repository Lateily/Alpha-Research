#!/usr/bin/env python3
"""Behavior tests for automatic paper admission after a human stock pick."""

from __future__ import annotations

import json
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))

import auto_paper_admission as admission  # noqa: E402
import model_paper_fund as fund_engine  # noqa: E402


def settled_bars() -> list[dict]:
    rows = []
    for day in range(1, 21):
        rows.append({
            "date": f"202609{day:02d}",
            "open": float(day + 8),
            "high": float(day + 9),
            "low": float(day + 4),
            "close": float(day + 8.5),
            "pre_close": float(day + 7.5),
            "up_limit": float(day + 18),
            "down_limit": float(max(0.01, day - 2)),
            "volume_shares": 10_000_000.0,
            "amount_cny": 200_000_000.0,
            "suspended": False,
            "settled": True,
            "price_basis": "RAW_UNADJUSTED",
            "source": "OFFLINE_FIXTURE_SETTLED_V2",
        })
    return rows


def eastmoney_payload() -> dict:
    klines = []
    for day in range(1, 22):
        klines.append(
            f"2026-09-{day:02d},{day + 8},{day + 8.5},{day + 9},{day + 4},"
            f"100000,200000000,1.0,0.1,0.1,1.0"
        )
    return {"data": {"code": "688035", "name": "德邦科技", "klines": klines}}


def tencent_payload() -> dict:
    rows = []
    for day in range(1, 22):
        rows.append([
            f"2026-09-{day:02d}", str(day + 8), str(day + 8.5),
            str(day + 9), str(day + 4), "10000000",
        ])
    return {
        "code": 0,
        "data": {
            "sh688035": {
                "day": rows,
                "qt": {"sh688035": ["1", "德邦科技", "688035"]},
            }
        },
    }


def selection() -> dict:
    return {
        "schema": "ar.human_paper_selection.v1",
        "ticker": "688035.SH",
        "name": "德邦科技",
        "theme": "半导体材料",
        "decision": "SELECT",
        "selected_by": "Junyan",
        "selected_at": "2026-09-26T10:00:00+08:00",
        "selection_ref": "conversation:688035-human-selection",
        "standing_authority_ref": "conversation:auto-paper-authority-20260926",
        "rule_version": "AUTO_AFTER_HUMAN_PICK_V0",
        "paper_only": True,
        "no_trade_flag": True,
        "trade_authority": False,
        "production_authority": False,
    }


class AutoPaperAdmissionTests(unittest.TestCase):
    def test_fixed_rule_builds_breakout_stop_target_and_conservative_size(self) -> None:
        plan = admission.build_auto_plan(
            selection(), settled_bars(), nav=1_000_000.0,
            registered_at="20260926",
        )

        self.assertEqual(plan["entry_review_price"], 29.0)
        self.assertEqual(plan["stop_reference"], 15.0)
        self.assertEqual(plan["take_profit_reference"], 57.0)
        self.assertEqual(plan["risk_pct"], 0.005)
        self.assertEqual(plan["max_fill_price"], 29.58)
        self.assertEqual(plan["setup"], "AUTO_20D_BREAKOUT_10D_STOP_2R")
        self.assertEqual(plan["rule_version"], "AUTO_AFTER_HUMAN_PICK_V0")
        self.assertEqual(plan["source_cutoff"], "20260920")
        self.assertFalse(plan["method_claim_sample_eligible"])

    def test_plan_rejects_nonhuman_selection_and_future_or_incomplete_bars(self) -> None:
        not_selected = selection()
        not_selected["decision"] = "WAIT"
        with self.assertRaisesRegex(admission.AutoAdmissionError, "human SELECT"):
            admission.build_auto_plan(
                not_selected, settled_bars(), nav=1_000_000.0,
                registered_at="20260926",
            )

        with self.assertRaisesRegex(admission.AutoAdmissionError, "at least 20"):
            admission.build_auto_plan(
                selection(), settled_bars()[:19], nav=1_000_000.0,
                registered_at="20260926",
            )

        future = settled_bars()
        future[-1]["date"] = "20260927"
        with self.assertRaisesRegex(admission.AutoAdmissionError, "after registration"):
            admission.build_auto_plan(
                selection(), future, nav=1_000_000.0,
                registered_at="20260926",
            )

        wrong_identity = selection()
        wrong_identity["name"] = "上海新阳"
        with self.assertRaisesRegex(admission.AutoAdmissionError, "identity mismatch"):
            admission.build_auto_plan(
                wrong_identity, settled_bars(), nav=1_000_000.0,
                registered_at="20260926",
            )

    def test_register_is_idempotent_and_persists_auditable_pending_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fund_dir = Path(tmp) / "fund"
            fund_engine.init_fund(
                fund_dir=str(fund_dir), capital=1_000_000.0, date="20260926",
            )

            first = admission.admit_selection(
                selection=selection(), bars=settled_bars(),
                fund_dir=fund_dir, registered_at="20260926",
            )
            second = admission.admit_selection(
                selection=selection(), bars=settled_bars(),
                fund_dir=fund_dir, registered_at="20260926",
            )
            orders = json.loads((fund_dir / "orders.json").read_text(encoding="utf-8"))
            decisions = json.loads((fund_dir / "decision_log.json").read_text(encoding="utf-8"))
            receipts = json.loads(
                (fund_dir / "auto_admission_receipts.json").read_text(encoding="utf-8")
            )

        self.assertEqual(first["status"], "REGISTERED")
        self.assertEqual(second["status"], "IDEMPOTENT")
        self.assertEqual(len(orders), 1)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(orders[0]["ticker"], "688035.SH")
        self.assertEqual(orders[0]["status"], "pending")
        self.assertEqual(orders[0]["admission_mode"], "AUTO_AFTER_HUMAN_PICK_V0")
        self.assertFalse(orders[0]["sample_eligible"])
        self.assertFalse(orders[0]["method_claim_sample_eligible"])
        self.assertEqual(decisions[-1]["action"], "REGISTER_ORDER")
        self.assertEqual(receipts[0]["plan_hash"], orders[0]["auto_plan_hash"])

    def test_status_reports_buy_point_fill_time_and_unrealized_pnl(self) -> None:
        order = {
            "ticker": "688035.SH",
            "name": "德邦科技",
            "status": "filled",
            "entry_review_price": 29.0,
            "fill_date": "20260928",
            "fill_price": 29.1,
            "shares": 300,
            "stop_reference": 27.0,
            "take_profit_reference": 33.2,
            "no_trade_flag": True,
        }

        view = admission.paper_status_view(order, mark=30.1, mark_date="20260929")

        self.assertEqual(view["buy_point"], 29.0)
        self.assertEqual(view["buy_time"], "20260928")
        self.assertEqual(view["mark_date"], "20260929")
        self.assertEqual(view["unrealized_pnl_cny"], 300.0)
        self.assertEqual(view["unrealized_return"], 0.0344)
        self.assertEqual(view["paper_only"], True)

    def test_cli_fetches_settled_bars_and_registers_without_manual_plan_fields(self) -> None:
        observed = {}

        def series_fn(ticker, token, start_date):
            observed.update(ticker=ticker, token=token, start_date=start_date)
            return settled_bars() + [{**settled_bars()[-1], "date": "20260927"}]

        with tempfile.TemporaryDirectory() as tmp:
            fund_dir = Path(tmp) / "fund"
            fund_engine.init_fund(
                fund_dir=str(fund_dir), capital=1_000_000.0, date="20260926",
            )
            stdout = io.StringIO()
            with mock.patch.dict(os.environ, {"TUSHARE_TOKEN": "fixture-token"}), redirect_stdout(stdout):
                rc = admission.main([
                    "register",
                    "--ticker", "688035.SH",
                    "--name", "德邦科技",
                    "--theme", "半导体材料",
                    "--selected-by", "Junyan",
                    "--selected-at", "2026-09-26T10:00:00+08:00",
                    "--selection-ref", "conversation:688035-human-selection",
                    "--standing-authority-ref", "conversation:auto-paper-authority-20260926",
                    "--registered-at", "20260926",
                    "--fund-dir", str(fund_dir),
                ], series_fn=series_fn)
            orders = json.loads((fund_dir / "orders.json").read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(observed["ticker"], "688035.SH")
        self.assertEqual(observed["token"], "fixture-token")
        self.assertEqual(observed["start_date"], "20260628")
        self.assertEqual(orders[0]["source_bars_hash"], json.loads(stdout.getvalue())["source_bars_hash"])
        self.assertNotIn("fixture-token", stdout.getvalue())

    def test_retry_recovers_missing_receipt_without_duplicate_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fund_dir = Path(tmp) / "fund"
            fund_engine.init_fund(
                fund_dir=str(fund_dir), capital=1_000_000.0, date="20260926",
            )
            admission.admit_selection(
                selection=selection(), bars=settled_bars(),
                fund_dir=fund_dir, registered_at="20260926",
            )
            (fund_dir / "auto_admission_receipts.json").write_text("[]\n", encoding="utf-8")
            (fund_dir / "decision_log.json").write_text("[]\n", encoding="utf-8")

            recovered = admission.admit_selection(
                selection=selection(), bars=settled_bars(),
                fund_dir=fund_dir, registered_at="20260926",
            )
            orders = json.loads((fund_dir / "orders.json").read_text(encoding="utf-8"))
            decisions = json.loads((fund_dir / "decision_log.json").read_text(encoding="utf-8"))
            receipts = json.loads(
                (fund_dir / "auto_admission_receipts.json").read_text(encoding="utf-8")
            )

        self.assertEqual(recovered["status"], "RECOVERED")
        self.assertEqual(len(orders), 1)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(decisions[-1]["action"], "RECOVER_ADMISSION")

    def test_concurrent_writer_lock_refuses_a_second_registration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fund_dir = Path(tmp) / "fund"
            fund_engine.init_fund(
                fund_dir=str(fund_dir), capital=1_000_000.0, date="20260926",
            )
            (fund_dir / ".auto_admission.lock").write_text("active\n", encoding="utf-8")

            with self.assertRaisesRegex(admission.AutoAdmissionError, "already in progress"):
                admission.admit_selection(
                    selection=selection(), bars=settled_bars(),
                    fund_dir=fund_dir, registered_at="20260926",
                )

    def test_public_kline_payload_is_identity_bound_and_usable_for_plan_only(self) -> None:
        bars = admission.eastmoney_payload_to_plan_bars(
            eastmoney_payload(), ticker="688035.SH", expected_name="德邦科技",
        )
        plan = admission.build_auto_plan(
            selection(), bars, nav=1_000_000.0, registered_at="20260926",
        )

        self.assertEqual(len(bars), 21)
        self.assertEqual(bars[-1]["date"], "20260921")
        self.assertEqual(bars[-1]["source"], "EASTMONEY_PUBLIC_KLINE_PLAN_ONLY_V1")
        self.assertEqual(plan["entry_review_price"], 30.0)
        self.assertEqual(plan["stop_reference"], 16.0)

        wrong = eastmoney_payload()
        wrong["data"]["name"] = "上海新阳"
        with self.assertRaisesRegex(admission.AutoAdmissionError, "identity mismatch"):
            admission.eastmoney_payload_to_plan_bars(
                wrong, ticker="688035.SH", expected_name="德邦科技",
            )

    def test_cli_can_register_from_a_frozen_public_kline_payload_without_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fund_dir = root / "fund"
            payload_path = root / "688035-eastmoney.json"
            marks_path = root / "marks.json"
            payload_path.write_text(
                json.dumps(eastmoney_payload(), ensure_ascii=False), encoding="utf-8",
            )
            marks_path.write_text("{}\n", encoding="utf-8")
            fund_engine.init_fund(
                fund_dir=str(fund_dir), capital=1_000_000.0, date="20260926",
            )
            stdout = io.StringIO()
            with mock.patch.dict(os.environ, {}, clear=True), redirect_stdout(stdout):
                rc = admission.main([
                    "register",
                    "--ticker", "688035.SH",
                    "--name", "德邦科技",
                    "--theme", "半导体材料",
                    "--selected-by", "Junyan",
                    "--selected-at", "2026-09-26T10:00:00+08:00",
                    "--selection-ref", "conversation:688035-human-selection",
                    "--standing-authority-ref", "conversation:auto-paper-authority-20260926",
                    "--registered-at", "20260926",
                    "--fund-dir", str(fund_dir),
                    "--bars-json", str(payload_path),
                    "--marks-json", str(marks_path),
                ])

        self.assertEqual(rc, 0)
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["status"], "pending")
        self.assertEqual(output["source_cutoff"], "20260921")

    def test_tencent_raw_kline_keeps_missing_amount_explicit_but_can_build_plan(self) -> None:
        bars = admission.tencent_payload_to_plan_bars(
            tencent_payload(), ticker="688035.SH", expected_name="德邦科技",
        )
        plan = admission.build_auto_plan(
            selection(), bars, nav=1_000_000.0, registered_at="20260926",
        )

        self.assertIsNone(bars[-1]["amount_cny"])
        self.assertEqual(
            bars[-1]["liquidity_status"], "DATA_BLOCKED_AMOUNT_UNAVAILABLE",
        )
        self.assertEqual(bars[-1]["source"], "TENCENT_PUBLIC_RAW_KLINE_PLAN_ONLY_V1")
        self.assertEqual(plan["entry_review_price"], 30.0)
        self.assertEqual(plan["stop_reference"], 16.0)

    def test_existing_filled_positions_require_marks_and_bind_nav_basis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fund_dir = Path(tmp) / "fund"
            fund_engine.init_fund(
                fund_dir=str(fund_dir), capital=1_000_000.0, date="20260926",
            )
            fund_engine.save("fund.json", {
                "initial_capital": 1_000_000.0,
                "cash": 999_000.0,
                "created": "20260926",
                "policy": "MODEL_PAPER_FUND_POLICY.md v0",
                "paper_only": True,
            }, str(fund_dir))
            fund_engine.save("orders.json", [{
                "ticker": "002714.SZ",
                "name": "牧原股份",
                "theme": "生猪",
                "status": "filled",
                "shares": 100,
                "fill_price": 10.0,
                "notional": 1_000.0,
            }], str(fund_dir))

            with self.assertRaisesRegex(admission.AutoAdmissionError, "current settled marks"):
                admission.admit_selection(
                    selection=selection(), bars=settled_bars(),
                    fund_dir=fund_dir, registered_at="20260926",
                )
            result = admission.admit_selection(
                selection=selection(), bars=settled_bars(),
                fund_dir=fund_dir, registered_at="20260926",
                marks={"002714.SZ": 11.0},
            )

        self.assertEqual(result["plan"]["nav_cny"], 1_000_100.0)
        self.assertEqual(result["plan"]["nav_basis"], "CURRENT_SETTLED_MARKS")
        self.assertRegex(result["plan"]["nav_marks_hash"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
