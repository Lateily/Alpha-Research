"""Offline behavioral pins for the five accepted data review blockers."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments/execution_tracker"))

import fund_source as fs  # noqa: E402
import tushare_rows  # noqa: E402
from experiments.data_governance.call_receipts import (  # noqa: E402
    CallReceiptSink, read_call_receipts,
)
from experiments.data_governance.catalog import catalog_hash, load_catalog  # noqa: E402
from experiments.data_governance.endpoint_calls import (  # noqa: E402
    EndpointSession, read_endpoint_receipts,
)
from experiments.data_governance.endpoints import (  # noqa: E402
    project_endpoint_health, propose_backfills,
)
from experiments.data_governance.health import evaluate_health  # noqa: E402

TARGET = "20261030"
NOW = datetime(2026, 10, 30, 8, tzinfo=timezone.utc)
PRIVATE_TEXT = "dummy-private-provider-text"
DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,pct_chg"


def rpc(fields, items):
    return {"code": 0, "msg": PRIVATE_TEXT,
            "data": {"fields": fields.split(","), "items": items}}


class EndpointReviewRegressions(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.next_root = 0
        for name in ("socket", "create_connection", "getaddrinfo"):
            patcher = mock.patch.object(socket, name, side_effect=AssertionError("NETWORK_FORBIDDEN"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def session(self, target=TARGET):
        self.next_root += 1
        now = datetime.strptime(target, "%Y%m%d").replace(tzinfo=timezone.utc)
        return EndpointSession(self.root / str(self.next_root), collector_run_id="review-regression",
                               target_trade_date=target, clock=lambda: now)

    def v1_context(self):
        catalog = load_catalog(ROOT / "config/data-source-catalog.v1.json")
        return catalog, {
            "logical_call_id": "d3b02f03-a274-40fc-a46b-1d3af231a134",
            "collector_run_id": "review-v1-identity", "source_id": "tushare.daily",
            "target_trade_date": TARGET, "ts_code": "600000.SH",
            "invoked_at": NOW.isoformat(), "catalog_hash": catalog_hash(catalog),
        }

    def observed_daily(self, session, raw):
        # Only the adapter's offline view is replaced; process AR_OFFLINE stays 1.
        # The transport is a fixture, with socket and DNS refusal above it.
        with mock.patch.object(fs, "os", SimpleNamespace(environ={})), \
                mock.patch.object(fs, "_http_json", return_value=raw):
            return fs.tushare_daily("600000.SH", "dummy", endpoint_session=session)

    def test_v1_missing_response_ticker_cannot_record_success_or_ok_health(self):
        catalog, context = self.v1_context()
        raw = rpc("trade_date,open,high,low,close,pct_chg", [[TARGET, 10, 12, 9, 11, 2]])
        failure = None
        with mock.patch.object(fs, "_http_json", return_value=raw):
            try:
                fs.tushare_daily("600000.SH", "dummy", observation_context=context,
                                 receipt_sink=CallReceiptSink(self.root))
            except RuntimeError as exc:
                failure = str(exc)
        rows = read_call_receipts(self.root)
        self.assertEqual(rows[0]["status"], "FAILED")
        self.assertEqual(rows[0]["error_code"], "INVALID_RESPONSE")
        self.assertEqual(failure, "INVALID_RESPONSE")
        health = evaluate_health(catalog, rows, target_trade_date=TARGET)
        self.assertEqual(health["sources"]["tushare.daily"]["status"], "DATA_BLOCKED")
        self.assertNotIn(PRIVATE_TEXT, "".join(p.read_text() for p in self.root.rglob("*.json")))

    def test_v1_present_response_ticker_and_numeric_zero_remain_valid(self):
        catalog, context = self.v1_context()
        raw = rpc(DAILY_FIELDS, [["600000.SH", TARGET, 0, 0, 0, 0, 0]])
        with mock.patch.object(fs, "_http_json", return_value=raw):
            result = fs.tushare_daily("600000.SH", "dummy", observation_context=context,
                                      receipt_sink=CallReceiptSink(self.root))
        self.assertEqual(result["close"], 0)
        health = evaluate_health(catalog, read_call_receipts(self.root), target_trade_date=TARGET)
        self.assertEqual(health["sources"]["tushare.daily"]["status"], "OK")

    def test_observed_daily_duplicate_historical_dates_cannot_return_ohlc_bars(self):
        session = self.session()
        raw = rpc(DAILY_FIELDS, [
            ["600000.SH", "20261029", 1, 3, 1, 2, 1],
            ["600000.SH", "20261029", 4, 6, 4, 5, 1],
            ["600000.SH", TARGET, 10, 12, 9, 11, 2],
        ])
        with self.assertRaisesRegex(RuntimeError, "^OBSERVATION_DUPLICATE_DATE$"):
            self.observed_daily(session, raw)
        result = read_endpoint_receipts(session.root)[0]["result"]
        self.assertEqual(result["request_status"], "SUCCEEDED")
        self.assertEqual(result["dataset_quality"], "DATA_BLOCKED")
        self.assertIn("DUPLICATE_ROW_KEY", result["gaps"])

    def test_unobserved_daily_duplicate_history_keeps_legacy_return_behavior(self):
        raw = rpc(DAILY_FIELDS, [
            ["600000.SH", "20261029", 1, 3, 1, 2, 1],
            ["600000.SH", "20261029", 4, 6, 4, 5, 1],
            ["600000.SH", TARGET, 10, 12, 9, 11, 2],
        ])
        with mock.patch.object(fs, "_http_json", return_value=raw):
            result = fs.tushare_daily("600000.SH", "dummy")
        self.assertEqual(result["ohlc_bars"], [
            {"high": 3, "low": 1, "close": 2},
            {"high": 6, "low": 4, "close": 5},
            {"high": 12, "low": 9, "close": 11},
        ])

    def test_forecast_published_future_report_period_is_not_invalid_period(self):
        session = self.session("20260915")
        raw = rpc("ts_code,ann_date,end_date,type,p_change_min,p_change_max",
                  [["600000.SH", "20260915", "20260930", "6", -100, -80]])
        returned = session.observe("forecast", {"ts_code": "600000.SH", "start_date": "20260101",
                                               "end_date": "20260915"}, "", lambda: raw)
        self.assertIs(returned, raw)
        result = read_endpoint_receipts(session.root)[0]["result"]
        self.assertEqual(result["gaps"], ["ANNOUNCEMENT_WINDOW_ONLY"])
        self.assertEqual(result["dataset_quality"], "PARTIAL")
        self.assertIsNone(result["target_date_rows"])

    def test_forecast_future_period_selector_is_distinct_from_publication_cutoff(self):
        session = self.session("20260915")
        raw = rpc("ts_code,ann_date,end_date,type,p_change_min,p_change_max",
                  [["600000.SH", "20260915", "20260930", "6", -100, -80]])
        try:
            returned = session.observe("forecast", {"ts_code": "600000.SH", "period": "20260930"},
                                       "", lambda: raw)
        except ValueError as exc:
            self.fail("Published forecast period was rejected: " + str(exc))
        self.assertIs(returned, raw)
        result = read_endpoint_receipts(session.root)[0]["result"]
        self.assertEqual(result["gaps"], ["ANNOUNCEMENT_WINDOW_ONLY"])

    def test_forecast_future_publication_requests_still_refuse_before_invoke(self):
        for dates in ({"ann_date": "20260916"}, {"end_date": "20260916"},
                      {"start_date": "20260916"}):
            with self.subTest(dates=dates):
                session = self.session("20260915")
                with self.assertRaisesRegex(ValueError, "^FUTURE_ENDPOINT_REQUEST$"):
                    session.observe("forecast", {"ts_code": "600000.SH", **dates}, "",
                                    lambda: self.fail("future publication request invoked"))
                self.assertFalse(session.root.exists())

    def test_forecast_future_publication_response_and_period_mismatch_remain_blocked(self):
        session = self.session("20260915")
        raw = rpc("ts_code,ann_date,end_date,type,p_change_min,p_change_max",
                  [["600000.SH", "20260916", "20260930", "6", -100, -80]])
        session.observe("forecast", {"ts_code": "600000.SH", "period": "20260630"}, "", lambda: raw)
        result = read_endpoint_receipts(session.root)[0]["result"]
        self.assertEqual(result["dataset_quality"], "DATA_BLOCKED")
        self.assertIn("FUTURE_DATE", result["gaps"])
        self.assertIn("PERIOD_MISMATCH", result["gaps"])

    def test_filed_report_future_periods_are_not_relaxed_with_forecasts(self):
        cases = [
            ("income", "ts_code,ann_date,end_date,report_type,n_income_attr_p", ["1", 1]),
            ("express", "ts_code,ann_date,end_date,n_income,yoy_net_profit", [1, 2]),
            ("fina_indicator", "ts_code,ann_date,end_date,roe,grossprofit_margin", [1, 2]),
        ]
        for api, fields, values in cases:
            with self.subTest(api=api):
                session = self.session()
                raw = rpc(fields, [["600000.SH", TARGET, "20261231", *values]])
                session.observe(api, {"ts_code": "600000.SH"}, "", lambda: raw)
                self.assertIn("INVALID_PERIOD", read_endpoint_receipts(session.root)[0]["result"]["gaps"])
                with self.assertRaisesRegex(ValueError, "^FUTURE_ENDPOINT_REQUEST$"):
                    session.observe(api, {"ts_code": "600000.SH", "period": "20261231"}, "",
                                    lambda: self.fail("future filed-report period invoked"))

    def test_observed_http_parameter_error_is_one_attempt_param_error_and_blocked_plan(self):
        for code in (400, 422):
            with self.subTest(code=code):
                session = self.session()
                attempts = []

                def opener(request, timeout):
                    attempts.append(True)
                    raise HTTPError("https://synthetic.invalid", code, PRIVATE_TEXT, {}, None)

                with mock.patch.object(tushare_rows, "os", SimpleNamespace(environ={})):
                    with self.assertRaisesRegex(RuntimeError, "^ENDPOINT_OBSERVATION_FAILED$") as failure:
                        tushare_rows.fetch_rows("moneyflow_ind_dc", "dummy", trade_date=TARGET,
                                                endpoint_session=session, opener=opener, sleep=lambda _: None)
                self.assertEqual(len(attempts), 1)
                result = read_endpoint_receipts(session.root)[0]["result"]
                self.assertEqual(result["error_code"], "PARAM_ERROR")
                self.assertIsNone(result["rows"])
                health = project_endpoint_health(session.catalog, read_endpoint_receipts(session.root),
                                                 target_trade_date=TARGET)
                proposals = propose_backfills(health, catalog=session.catalog)["proposals"]
                plan = next(p for p in proposals if p["api_name"] == "moneyflow_ind_dc")
                self.assertEqual(plan["status"], "BLOCKED_EVIDENCE")
                self.assertNotIn(PRIVATE_TEXT, str(failure.exception))
                self.assertNotIn(PRIVATE_TEXT, "".join(p.read_text() for p in session.root.rglob("*.json")))

    def test_unobserved_http_parameter_error_preserves_legacy_retry_count(self):
        for code in (400, 422):
            with self.subTest(code=code):
                attempts = []

                def opener(request, timeout):
                    attempts.append(True)
                    raise HTTPError("https://synthetic.invalid", code, PRIVATE_TEXT, {}, None)

                with mock.patch.object(tushare_rows, "os", SimpleNamespace(environ={})):
                    rows, reason = tushare_rows.fetch_rows("moneyflow_ind_dc", "dummy", trade_date=TARGET,
                                                          attempts=3, opener=opener, sleep=lambda _: None)
                self.assertEqual(len(attempts), 3)
                self.assertIsNone(rows)
                self.assertEqual(reason, "TUSHARE_EXCEPTION:HTTPError")

    def global_call(self, returned_date):
        session = self.session("20261102")
        raw = rpc("ts_code,trade_date,close,pct_chg", [["IXIC", returned_date, 1, 2]])
        session.observe("index_global", {"ts_code": "IXIC", "trade_date": "20261030"}, "", lambda: raw)
        return session

    def test_global_explicit_trade_date_mismatch_is_outside_request_not_only_calendar_gap(self):
        session = self.global_call("20261102")
        result = read_endpoint_receipts(session.root)[0]["result"]
        self.assertEqual(result["outside_date_rows"], 1)
        self.assertIn("DATE_OUTSIDE_REQUEST", result["gaps"])
        self.assertEqual(result["dataset_quality"], "DATA_BLOCKED")
        self.assertIsNone(result["target_date_rows"])

    def test_global_matching_selected_date_keeps_null_target_and_unverified_calendar(self):
        session = self.global_call("20261030")
        result = read_endpoint_receipts(session.root)[0]["result"]
        self.assertEqual(result["gaps"], ["GLOBAL_CALENDAR_UNVERIFIED"])
        self.assertEqual(result["outside_date_rows"], 0)
        self.assertEqual(result["dataset_quality"], "PARTIAL")
        self.assertIsNone(result["target_date_rows"])

    def test_global_selected_bounds_reject_reopened_outside_count_gap_forgery(self):
        session = self.global_call("20261102")
        path = next((session.root / "calls").glob("*/terminal.json"))
        value = json.loads(path.read_text())
        result = value["result"]
        result["outside_date_rows"] = 0
        result["gaps"] = [g for g in result["gaps"] if g != "DATE_OUTSIDE_REQUEST"]
        result["dataset_quality"] = "PARTIAL"
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "^ENDPOINT_OUTSIDE_COUNT_MISMATCH$"):
            read_endpoint_receipts(session.root)


if __name__ == "__main__":
    unittest.main()
