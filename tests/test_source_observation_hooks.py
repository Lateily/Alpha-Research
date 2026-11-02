"""WORKFLOW_DEBUG: deferred source-hook acceptance; NOT_RUN, review PENDING.

All authorities remain false. Fixtures never authorize live provider calls.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments/execution_tracker"))
import fund_source as fs  # noqa: E402
import rotation_panel  # noqa: E402
import run_official_sample as official  # noqa: E402
import tushare_rows  # noqa: E402
from tushare_https import TushareHTTPS  # noqa: E402
from experiments.data_governance.call_receipts import (  # noqa: E402
    CallReceiptSink, read_call_receipts, record_call,
)
from experiments.data_governance.catalog import catalog_hash, load_catalog  # noqa: E402

TARGET = "20261030"
TOKEN = "synthetic-credential-not-a-real-token"
NOW = datetime(2026, 10, 30, 8, tzinfo=timezone.utc)


def rpc(fields, items):
    return {"code": 0, "msg": "", "data": {"fields": fields.split(","), "items": items}}


class SessionDouble:
    """Only the explicit session boundary is fake; source readers stay real."""

    target_trade_date = TARGET

    def __init__(self, failure=None):
        self.calls = []
        self.responses = []
        self.failure = failure

    def observe(self, api_name, params, fields, invoke):
        self.calls.append((api_name, dict(params), fields))
        if self.failure == "start":
            raise OSError(TOKEN + " private recorder failure")
        response = invoke()
        self.responses.append(response)
        if self.failure == "finish":
            raise OSError(TOKEN + " private recorder failure")
        return response


class SourceObservationHooksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.session = SessionDouble()
        self.catalog = load_catalog(ROOT / "config/data-source-catalog.v1.json")
        patcher = mock.patch.dict(os.environ, {"AR_OFFLINE": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("socket", "create_connection", "getaddrinfo"):
            patcher = mock.patch.object(socket, name, side_effect=AssertionError("NETWORK_FORBIDDEN"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def context(self, api="daily", ticker="600000.SH"):
        return {"logical_call_id": "d3b02f03-a274-40fc-a46b-1d3af231a134",
                "collector_run_id": "synthetic-source-hooks", "source_id": "tushare." + api,
                "target_trade_date": TARGET, "ts_code": ticker,
                "invoked_at": NOW.isoformat(), "catalog_hash": catalog_hash(self.catalog)}

    def opener(self, values, seen):
        def open_fixture(request, timeout):
            seen.append((json.loads(request.data), timeout))
            value = values[min(len(seen) - 1, len(values) - 1)]
            if isinstance(value, Exception):
                raise value
            return io.BytesIO(json.dumps(value).encode())
        return open_fixture

    def test_lowlevel_records_full_rpc_once_not_just_data(self):
        value = rpc("ts_code,trade_date,close", [["600000.SH", TARGET, 12]])
        seen = []
        with mock.patch.object(fs, "_http_json", side_effect=lambda **kw: seen.append(kw) or value):
            data = fs._tushare_call("daily", TOKEN, {"ts_code": "600000.SH"},
                                   "ts_code,trade_date,close", endpoint_session=self.session)
        self.assertEqual(data, value["data"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["attempts"], 3)
        self.assertEqual(self.session.responses, [value])
        self.assertEqual(self.session.calls, [("daily", {"ts_code": "600000.SH"},
                                              "ts_code,trade_date,close")])

    def test_internal_transport_retries_stay_one_logical_call(self):
        value = rpc("ts_code,trade_date,close", [["600000.SH", TARGET, 12]])
        seen, sleeps = [], []
        with mock.patch.object(fs.urllib.request, "urlopen", self.opener(
                [socket.timeout(TOKEN), socket.timeout(TOKEN), value], seen)), \
                mock.patch.object(fs.time, "sleep", side_effect=sleeps.append):
            result = fs._tushare_call("daily", TOKEN, {"ts_code": "600000.SH"},
                                      "ts_code,trade_date,close", endpoint_session=self.session)
        self.assertEqual(result, value["data"])
        self.assertEqual(len(seen), 3)
        self.assertEqual(sleeps, [0.5, 1.0])
        self.assertEqual(len(self.session.calls), 1)
        self.assertEqual([timeout for _, timeout in seen], [12, 12, 12])

    def test_mixed_observers_refuse_before_provider_or_recorder(self):
        for old in ({"observation_context": self.context()}, {"receipt_sink": object()},
                    {"observation_context": self.context(), "receipt_sink": object()}):
            with self.subTest(old=list(old)), mock.patch.object(fs, "_http_json") as transport:
                with self.assertRaisesRegex(ValueError, "OBSERVATION_MODES_MUTUALLY_EXCLUSIVE"):
                    fs._tushare_call("daily", TOKEN, {}, "", endpoint_session=self.session, **old)
                transport.assert_not_called()
        self.assertEqual(self.session.calls, [])

    def test_offline_refuses_both_recorders_and_transport(self):
        seen = []
        with mock.patch.dict(os.environ, {"AR_OFFLINE": "1"}), \
                mock.patch.object(fs, "_http_json") as transport:
            with self.assertRaisesRegex(RuntimeError, "TUSHARE_OFFLINE"):
                fs.tushare_daily("600000.SH", TOKEN, endpoint_session=self.session)
            with self.assertRaisesRegex(RuntimeError, "TUSHARE_OFFLINE"):
                TushareHTTPS(TOKEN, endpoint_session=self.session).daily(ts_code="600000.SH")
            result = tushare_rows.fetch_rows("daily", TOKEN, endpoint_session=self.session,
                                             opener=self.opener([], seen))
            self.assertEqual(result, (None, "TUSHARE_OFFLINE"))
            transport.assert_not_called()
        self.assertEqual((self.session.calls, seen), ([], []))

    def test_recording_failure_propagates_safely_without_replay(self):
        value = rpc("ts_code,trade_date,close", [["600000.SH", TARGET, 12]])
        for failure, expected_calls in (("start", 0), ("finish", 1)):
            seen = []
            session = SessionDouble(failure)
            with self.subTest(failure=failure), \
                    mock.patch.object(fs, "_http_json", side_effect=lambda **kw: seen.append(kw) or value):
                with self.assertRaises(RuntimeError) as caught:
                    fs._tushare_call("daily", TOKEN, {}, "", endpoint_session=session)
            self.assertEqual(len(seen), expected_calls)
            self.assertNotIn(TOKEN, str(caught.exception))
            self.assertNotIn("private", str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)

    def test_observed_provider_error_never_echoes_message(self):
        with mock.patch.object(fs, "_http_json", return_value={"code": 403, "msg": TOKEN + " private"}):
            with self.assertRaisesRegex(RuntimeError, "TUSHARE_OBSERVED_RESPONSE_FAILED") as caught:
                fs._tushare_call("daily", TOKEN, {}, "", endpoint_session=self.session)
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_rows_provider_denial_is_not_retried_into_later_success(self):
        denial = {"code": 403, "msg": TOKEN + " private"}
        success = rpc("trade_date,name,net_amount,pct_change", [[TARGET, "Sector", 3, 0.5]])
        seen, sleeps = [], []
        with self.assertRaisesRegex(RuntimeError, "TUSHARE_OBSERVED_RESPONSE_FAILED") as caught:
            tushare_rows.fetch_rows("moneyflow_ind_dc", TOKEN, trade_date=TARGET,
                    endpoint_session=self.session, timeout=17, attempts=3, pause=2,
                    opener=self.opener([denial, success], seen), sleep=sleeps.append)
        self.assertEqual((len(seen), sleeps), (1, []))
        self.assertEqual([timeout for _, timeout in seen], [17])
        self.assertEqual(self.session.responses, [denial])
        self.assertEqual(self.session.calls, [("moneyflow_ind_dc", {"trade_date": TARGET}, "")])
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertNotIn("private", str(caught.exception))

    def test_rows_transport_retries_remain_one_logical_call(self):
        value = rpc("trade_date,name,net_amount,pct_change", [[TARGET, "Sector", 3, 0.5]])
        seen, sleeps = [], []
        result = tushare_rows.fetch_rows("moneyflow_ind_dc", TOKEN, trade_date=TARGET,
                endpoint_session=self.session, timeout=17, attempts=3, pause=2,
                opener=self.opener([OSError(TOKEN), OSError(TOKEN), value], seen),
                sleep=sleeps.append)
        self.assertEqual(result, ([{"trade_date": TARGET, "name": "Sector",
                                   "net_amount": 3, "pct_change": 0.5}], None))
        self.assertEqual((len(seen), sleeps), (3, [2, 2]))
        self.assertEqual([timeout for _, timeout in seen], [17, 17, 17])
        self.assertEqual(self.session.responses, [value])
        self.assertEqual(self.session.calls, [("moneyflow_ind_dc", {"trade_date": TARGET}, "")])

    def test_rows_recording_failure_is_not_swallowed_or_retried(self):
        value = rpc("trade_date,net_amount", [[TARGET, 1]])
        seen = []
        with self.assertRaises(RuntimeError) as caught:
            tushare_rows.fetch_rows("moneyflow_mkt_dc", TOKEN, endpoint_session=SessionDouble("finish"),
                    attempts=4, opener=self.opener([value], seen), sleep=lambda _: self.fail("replayed"))
        self.assertEqual(len(seen), 1)
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_rows_exhaustion_is_safe_and_does_not_add_observer_retry(self):
        seen = []
        with self.assertRaises(RuntimeError) as caught:
            tushare_rows.fetch_rows("moneyflow_mkt_dc", TOKEN, endpoint_session=self.session,
                    attempts=2, opener=self.opener([OSError(TOKEN + " private")], seen),
                    sleep=lambda _: None)
        self.assertEqual((len(seen), len(self.session.calls)), (2, 1))
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertNotIn("private", str(caught.exception))

    def test_rows_malformed_final_rpc_reaches_observer_without_replay(self):
        seen = []
        value = {"code": 0, "data": {"fields": [["unhashable"]], "items": [[1]]}}
        with self.assertRaisesRegex(RuntimeError, "TUSHARE_OBSERVED_RESPONSE_FAILED"):
            tushare_rows.fetch_rows("moneyflow_mkt_dc", TOKEN, endpoint_session=self.session,
                    attempts=2, opener=self.opener([value], seen), sleep=lambda _: None)
        self.assertEqual(len(seen), 2)
        self.assertEqual(self.session.responses, [value])

    def test_legacy_rows_failure_and_empty_success_are_unchanged(self):
        seen = []
        result = tushare_rows.fetch_rows("daily", TOKEN, attempts=2,
                opener=self.opener([{"code": 403, "msg": TOKEN + " denied"}], seen), sleep=lambda _: None)
        self.assertEqual(result, (None, "TUSHARE_CODE_403:*** denied"))
        self.assertEqual(len(seen), 2)
        self.assertEqual(tushare_rows.fetch_rows("daily", TOKEN,
                opener=self.opener([rpc("close", [])], [])), ([], None))

    def test_legacy_denials_keep_retry_and_failure_semantics(self):
        success = rpc("trade_date,net_amount", [[TARGET, 1]])
        failures = [urllib.error.HTTPError("https://synthetic.invalid", code, TOKEN, {}, None)
                    for code in (401, 403)] + [PermissionError(TOKEN)]
        for failure in failures:
            seen, sleeps = [], []
            with self.subTest(failure=type(failure).__name__, code=getattr(failure, "code", None)):
                result = tushare_rows.fetch_rows("moneyflow_mkt_dc", TOKEN, attempts=2,
                        opener=self.opener([failure, success], seen), sleep=sleeps.append)
                self.assertEqual(result, ([{"trade_date": TARGET, "net_amount": 1}], None))
                self.assertEqual((len(seen), sleeps), (2, [1.5]))
                seen = []
                result = tushare_rows.fetch_rows("moneyflow_mkt_dc", TOKEN, attempts=2,
                        opener=self.opener([failure], seen), sleep=lambda _: None)
                self.assertEqual(result, (None, "TUSHARE_EXCEPTION:" + type(failure).__name__))
                self.assertEqual(len(seen), 2)

    def test_legacy_row_conversion_failure_retains_original_retry_semantics(self):
        seen = []
        value = {"code": 0, "data": {"fields": [["unhashable"]], "items": [[1]]}}
        result = tushare_rows.fetch_rows("daily", TOKEN, attempts=2,
                opener=self.opener([value], seen), sleep=lambda _: None)
        self.assertEqual(result, (None, "TUSHARE_EXCEPTION:TypeError"))
        self.assertEqual(len(seen), 2)

    def test_missing_session_target_refuses_before_provider(self):
        with mock.patch.object(fs, "_http_json") as transport:
            with self.assertRaisesRegex(RuntimeError, "OBSERVATION_TARGET_REQUIRED"):
                fs.tushare_daily("600000.SH", TOKEN, endpoint_session=object())
            transport.assert_not_called()

    def test_legacy_daily_keeps_original_request_fields_and_latest_row(self):
        value = rpc("trade_date,open,high,low,close,pct_chg", [
            [TARGET, 10, 12, 9, 11, 2], ["20261102", 20, 22, 19, 21, 1]])
        with mock.patch.object(fs, "_http_json", return_value=value) as transport:
            result = fs.tushare_daily("600000.SH", TOKEN)
        body = json.loads(transport.call_args.kwargs["data"])
        self.assertEqual(body["params"], {"ts_code": "600000.SH"})
        self.assertEqual(body["fields"], "trade_date,open,high,low,close,pct_chg")
        self.assertEqual((result["date"], result["close"]), ("20261102", 21))

    def test_daily_opt_in_selects_target_entity_and_excludes_future_bars(self):
        value = rpc("ts_code,trade_date,open,high,low,close,pct_chg", [
            ["600000.SH", "20261102", 20, 22, 19, 21, 1],
            ["600000.SH", TARGET, 10, 12, 9, 11, 2],
            ["600000.SH", "20261029", 9, 11, 8, 10, 3]])
        with mock.patch.object(fs, "_http_json", return_value=value):
            result = fs.tushare_daily("600000.SH", TOKEN, endpoint_session=self.session)
        self.assertEqual((result["date"], result["close"]), (TARGET, 11))
        self.assertEqual(result["ohlc_bars"], [{"high": 11, "low": 8, "close": 10},
                                              {"high": 12, "low": 9, "close": 11}])

    def test_daily_missing_target_entity_or_ambiguous_target_is_not_latest_fallback(self):
        for items in ([["600000.SH", "20261029", 12, 9, 11, 2]],
                      [["600001.SH", TARGET, 12, 9, 11, 2]],
                      [["600000.SH", TARGET, 12, 9, 11, 2]] * 2):
            with self.subTest(items=items), mock.patch.object(fs, "_http_json", return_value=rpc(
                    "ts_code,trade_date,high,low,close,pct_chg", items)):
                with self.assertRaisesRegex(RuntimeError, "OBSERVATION_"):
                    fs.tushare_daily("600000.SH", TOKEN, endpoint_session=self.session)

    def test_fund_observed_target_not_provider_order_and_no_missing_to_zero(self):
        fields = "ts_code,trade_date,close,pct_change,net_amount,buy_elg_amount,buy_lg_amount,buy_md_amount,buy_sm_amount"
        value = rpc(fields, [["600000.SH", "20261029", 10, 1, 10000, 5000, 5000, 0, 0],
                             ["600000.SH", TARGET, 11, 2, 20000, 10000, 10000, 0, 0]])
        with mock.patch.object(fs, "_http_json", return_value=value):
            result = fs.tushare_stock_fund("600000.SH", TOKEN, endpoint_session=self.session)
            legacy = fs.tushare_stock_fund("600000.SH", TOKEN)
        self.assertEqual((result["date"], result["main"]), (TARGET, 2.0))
        self.assertEqual((legacy["date"], legacy["main"]), ("20261029", 1.0))
        value["data"]["items"][1][4] = None
        with mock.patch.object(fs, "_http_json", return_value=value):
            with self.assertRaisesRegex(RuntimeError, "OBSERVATION_NUMERIC_REQUIRED"):
                fs.tushare_stock_fund("600000.SH", TOKEN, endpoint_session=self.session)

    def test_https_daily_basic_forwards_instance_session_to_source_helper(self):
        value = rpc("ts_code,trade_date,pe_ttm,pb,total_mv", [["600000.SH", TARGET, 8, 1, 20000]])
        with mock.patch.object(fs, "_http_json", return_value=value), \
                mock.patch.object(fs, "tushare_daily_basic", wraps=fs.tushare_daily_basic) as helper:
            frame = TushareHTTPS(TOKEN, endpoint_session=self.session).daily_basic(
                    ts_code="600000.SH", end_date=TARGET, fields="ts_code,trade_date,pe_ttm,pb,total_mv")
        self.assertEqual(frame.total_mv.tolist(), [20000])
        self.assertEqual(helper.call_count, 1)
        self.assertEqual(self.session.responses, [value])

    def test_https_allowlist_is_not_expanded_by_observer(self):
        with mock.patch.object(fs, "_http_json") as transport:
            with self.assertRaisesRegex(ValueError, "TUSHARE_READ_API_NOT_ALLOWED"):
                TushareHTTPS(TOKEN, endpoint_session=self.session).moneyflow_ind_dc(trade_date=TARGET)
            transport.assert_not_called()
        self.assertEqual(self.session.calls, [])

    def test_https_default_daily_basic_preserves_narrow_fields_and_nulls(self):
        value = rpc("trade_date,pe_ttm,pb,total_mv", [[TARGET, None, 1, 20000]])
        with mock.patch.object(fs, "_http_json", return_value=value) as transport:
            frame = TushareHTTPS(TOKEN).daily_basic(ts_code="600000.SH", end_date=TARGET,
                                                   fields="trade_date,pe_ttm,pb,total_mv")
        body = json.loads(transport.call_args.kwargs["data"])
        self.assertEqual(body["params"], {"ts_code": "600000.SH", "end_date": TARGET})
        self.assertEqual(body["fields"], "trade_date,pe_ttm,pb,total_mv")
        self.assertTrue(frame.pe_ttm.isna().iloc[0])

    def test_fund_wrapper_recording_error_never_falls_back_or_becomes_manual(self):
        value = rpc("ts_code,trade_date,net_amount", [["600000.SH", TARGET, 10000]])
        with mock.patch.object(fs, "_http_json", return_value=value) as transport, \
                mock.patch.object(fs, "eastmoney_stock_fund") as fallback:
            with self.assertRaises(RuntimeError):
                fs.get_many(["600000.SH"], token=TOKEN, endpoint_session=SessionDouble("finish"))
            self.assertEqual(transport.call_count, 1)
            fallback.assert_not_called()

    def test_first_five_v1_paths_accept_safe_fields_without_changing_receipt_schema(self):
        fixtures = [
            ("daily", "600000.SH", "ts_code,trade_date,close", [["600000.SH", TARGET, 10]]),
            ("daily_basic", "600000.SH", "ts_code,trade_date,pe,pe_ttm,pb,total_mv",
             [["600000.SH", TARGET, 7, 8, 1, 20000]]),
            ("moneyflow_dc", "600000.SH", "ts_code,trade_date,net_amount", [["600000.SH", TARGET, 10000]]),
            ("moneyflow_ind_dc", None, "trade_date,name,net_amount,pct_change", [[TARGET, "Sector", 3, 1]]),
            ("moneyflow_mkt_dc", None, "trade_date,net_amount", [[TARGET, 100000000]])]
        for api, ticker, fields, items in fixtures:
            sink = CallReceiptSink(self.root / api)
            params = {"ts_code": ticker} if ticker else {"trade_date": TARGET}
            with self.subTest(api=api), mock.patch.object(fs, "_http_json", return_value=rpc(fields, items)):
                fs._tushare_call(api, TOKEN, params, fields, observation_context=self.context(api, ticker),
                                 receipt_sink=sink)
            row, = read_call_receipts(sink.root)
            self.assertEqual((row["schema"], row["status"]), ("ar.data-call-receipt.v1", "SUCCEEDED"))

    def test_v1_numeric_and_date_guards_remain_fail_closed(self):
        for invalid in (None, True, "NaN", float("inf")):
            sink = CallReceiptSink(self.root / str(type(invalid).__name__))
            with self.subTest(invalid=invalid), self.assertRaisesRegex(RuntimeError, "INVALID_RESPONSE"):
                record_call(self.catalog, self.context("daily_basic"), {"ts_code": "600000.SH", "fields": "pb"},
                        lambda: rpc("ts_code,trade_date,pb", [["600000.SH", TARGET, invalid]]), sink, lambda: NOW)
        with self.assertRaisesRegex(ValueError, "PARAM_DATE_MISMATCH"):
            fs._tushare_call("daily_basic", TOKEN, {"ts_code": "600000.SH", "trade_date": "20261029"},
                    "pb", observation_context=self.context("daily_basic"),
                    receipt_sink=CallReceiptSink(self.root / "wrong-date"))

    def test_old_v1_receipt_with_historical_catalog_hash_still_reads(self):
        for api, ticker, params in (("daily", "600000.SH", {"ts_code": "600000.SH"}),
                                    ("daily_basic", None, {})):
            ctx = self.context(api, ticker)
            ctx["catalog_hash"] = "0" * 64
            sink = CallReceiptSink(self.root / ("historical-" + api))
            sink.start(ctx, dict(params, fields="trade_date,close"))
            sink.finish(ctx["logical_call_id"], {"status": "SUCCEEDED", "rows": 1,
                "first_date": TARGET, "last_date": TARGET, "target_rows": 1, "missing_date_rows": 0,
                "response_hash": "1" * 64, "elapsed_ms": 0, "error_code": None,
                "completed_at": NOW.isoformat()})
            row, = read_call_receipts(sink.root)
            self.assertEqual(row["context"]["catalog_hash"], "0" * 64)

    def test_real_session_daily_hook_persists_one_call_and_refuses_replay(self):
        from experiments.data_governance.endpoint_calls import EndpointSession, read_endpoint_receipts
        root = self.root / "endpoint-real"
        session = EndpointSession(root, collector_run_id="synthetic-source-hooks",
                                  target_trade_date=TARGET, clock=lambda: NOW)
        value = rpc("ts_code,trade_date,open,high,low,close,pct_chg",
                    [["600000.SH", TARGET, 10, 12, 9, 11, 2]])
        with mock.patch.object(fs, "_http_json", return_value=value) as transport:
            result = fs.tushare_daily("600000.SH", TOKEN, endpoint_session=session)
            with self.assertRaises(RuntimeError):
                fs.tushare_daily("600000.SH", TOKEN, endpoint_session=session)
            self.assertEqual(transport.call_count, 1)
        self.assertEqual((result["date"], result["close"]), (TARGET, 11))
        row, = read_endpoint_receipts(root)
        self.assertEqual(row["result"]["request_status"], "SUCCEEDED")
        self.assertEqual(row["verification"], "NOT_RUN")
        self.assertNotIn(TOKEN, "".join(p.read_text() for p in root.rglob("*.json")))

    def test_real_session_missing_entity_is_quality_gap_and_helper_refusal(self):
        from experiments.data_governance.endpoint_calls import EndpointSession, read_endpoint_receipts
        root = self.root / "endpoint-missing-entity"
        session = EndpointSession(root, collector_run_id="synthetic-source-hooks",
                                  target_trade_date=TARGET, clock=lambda: NOW)
        value = rpc("trade_date,open,high,low,close,pct_chg", [[TARGET, 10, 12, 9, 11, 2]])
        with mock.patch.object(fs, "_http_json", return_value=value) as transport:
            with self.assertRaisesRegex(RuntimeError, "OBSERVATION_ENTITY_AND_DATE_REQUIRED"):
                fs.tushare_daily("600000.SH", TOKEN, endpoint_session=session)
            self.assertEqual(transport.call_count, 1)
        row, = read_endpoint_receipts(root)
        self.assertEqual(row["result"]["request_status"], "SUCCEEDED")
        self.assertNotEqual(row["result"]["dataset_quality"], "OBSERVED_SCOPE_VALID")

    def test_real_session_rows_finish_failure_leaves_no_replayed_provider_call(self):
        from experiments.data_governance.endpoint_calls import EndpointSession, read_endpoint_receipts
        root = self.root / "endpoint-row-finish"
        session = EndpointSession(root, collector_run_id="synthetic-source-hooks",
                                  target_trade_date=TARGET, clock=lambda: NOW)
        seen = []
        value = rpc("trade_date,net_amount", [[TARGET, 100000000]])
        with mock.patch.object(session, "_finish", side_effect=OSError(TOKEN)):
            with self.assertRaises(RuntimeError):
                tushare_rows.fetch_rows("moneyflow_mkt_dc", TOKEN, endpoint_session=session,
                        opener=self.opener([value], seen), sleep=lambda _: self.fail("replayed"))
        with self.assertRaises(RuntimeError):
            tushare_rows.fetch_rows("moneyflow_mkt_dc", TOKEN, endpoint_session=session,
                    opener=self.opener([value], seen), sleep=lambda _: self.fail("replayed"))
        self.assertEqual(len(seen), 1)
        row, = read_endpoint_receipts(root)
        self.assertEqual(row["result"]["request_status"], "INTERRUPTED")

    def test_real_session_rows_denials_record_permission_denied_after_one_attempt(self):
        from experiments.data_governance.endpoint_calls import EndpointSession, read_endpoint_receipts
        failures = [urllib.error.HTTPError("https://synthetic.invalid", code, TOKEN, {}, None)
                    for code in (401, 403)] + [PermissionError(TOKEN), {"code": 403, "msg": TOKEN + " private"}]
        success = rpc("trade_date,net_amount", [[TARGET, 100000000]])
        for index, failure in enumerate(failures):
            root = self.root / ("endpoint-row-denial-" + str(index))
            session = EndpointSession(root, collector_run_id="synthetic-source-hooks",
                                      target_trade_date=TARGET, clock=lambda: NOW)
            seen, sleeps = [], []
            with self.subTest(index=index), self.assertRaises(RuntimeError) as caught:
                tushare_rows.fetch_rows("moneyflow_mkt_dc", TOKEN, endpoint_session=session,
                        attempts=4, opener=self.opener([failure, success], seen), sleep=sleeps.append)
            self.assertEqual((len(seen), sleeps), (1, []))
            self.assertNotIn(TOKEN, str(caught.exception))
            row, = read_endpoint_receipts(root)
            self.assertEqual(row["result"]["request_status"], "FAILED")
            self.assertEqual(row["result"]["error_code"], "PERMISSION_DENIED")
            self.assertNotIn(TOKEN, "".join(p.read_text() for p in root.rglob("*.json")))

    def test_real_session_daily_basic_narrow_fields_leave_identity_gap_visible(self):
        from experiments.data_governance.endpoint_calls import EndpointSession, read_endpoint_receipts
        root = self.root / "endpoint-daily-basic-narrow"
        session = EndpointSession(root, collector_run_id="synthetic-source-hooks",
                                  target_trade_date=TARGET, clock=lambda: NOW)
        value = rpc("trade_date,pe_ttm,pb,total_mv", [[TARGET, 8, 1, 20000]])
        with mock.patch.object(fs, "_http_json", return_value=value):
            frame = TushareHTTPS(TOKEN, endpoint_session=session).daily_basic(
                ts_code="600000.SH", end_date=TARGET, fields="trade_date,pe_ttm,pb,total_mv")
        self.assertEqual(frame.pb.tolist(), [1])
        row, = read_endpoint_receipts(root)
        self.assertEqual(row["result"]["request_status"], "SUCCEEDED")
        self.assertIn("MISSING_FIELDS", row["result"]["gaps"])
        self.assertEqual(row["human_review"], "PENDING")
        self.assertTrue(all(value is False for value in row["authorities"].values()))

    def test_real_session_rotation_calendar_and_industry_share_context(self):
        from experiments.data_governance.endpoint_calls import EndpointSession, read_endpoint_receipts
        root = self.root / "endpoint-rotation"
        session = EndpointSession(root, collector_run_id="synthetic-source-hooks",
                                  target_trade_date=TARGET, clock=lambda: NOW)
        def response(request, timeout):
            body = json.loads(request.data)
            if body["api_name"] == "trade_cal":
                value = rpc("exchange,cal_date,is_open", [["SSE", "20261029", 1], ["SSE", TARGET, 1]])
            else:
                value = rpc("ts_code,trade_date,name,net_amount,pct_change",
                    [["BK0451.DC", body["params"]["trade_date"], "Sector", 1, 0.5]])
            return io.BytesIO(json.dumps(value).encode())
        with mock.patch.object(tushare_rows.urllib.request, "urlopen", side_effect=response), \
                mock.patch.object(rotation_panel.time, "sleep"), \
                mock.patch.object(rotation_panel, "OUT", str(self.root / "real-panel.json")), \
                contextlib.redirect_stdout(io.StringIO()):
            panel = rotation_panel.run(TOKEN, n_days=2, endpoint_session=session)
        self.assertEqual(panel["days"], ["20261029", TARGET])
        rows = read_endpoint_receipts(root)
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["start"]["collector_run_id"] for r in rows}, {"synthetic-source-hooks"})
        self.assertEqual({r["start"]["target_trade_date"] for r in rows}, {TARGET})

    def test_rotation_uses_same_session_and_its_target_not_wall_clock(self):
        def response(request, timeout):
            body = json.loads(request.data)
            if body["api_name"] == "trade_cal":
                value = rpc("cal_date", [["20261029"], [TARGET], ["20261102"]])
            else:
                value = rpc("trade_date,name,net_amount,pct_change",
                            [[body["params"]["trade_date"], "Sector", 1, 0.5]])
            return io.BytesIO(json.dumps(value).encode())
        with mock.patch.object(tushare_rows.urllib.request, "urlopen", side_effect=response), \
                mock.patch.object(rotation_panel, "target_trade_date", return_value="20261102"), \
                mock.patch.object(rotation_panel.time, "sleep"), \
                mock.patch.object(rotation_panel, "OUT", str(self.root / "panel.json")), \
                contextlib.redirect_stdout(io.StringIO()):
            panel = rotation_panel.run(TOKEN, n_days=2, endpoint_session=self.session)
        self.assertEqual(panel["days"], ["20261029", TARGET])
        self.assertEqual(panel["n_sectors"], 1)
        self.assertEqual([c[0] for c in self.session.calls], ["trade_cal", "moneyflow_ind_dc", "moneyflow_ind_dc"])

    def test_rotation_observed_calendar_never_substitutes_prior_date_for_target(self):
        seen = []
        with mock.patch.object(tushare_rows.urllib.request, "urlopen", self.opener(
                [rpc("cal_date", [["20261029"]])], seen)):
            with self.assertRaisesRegex(RuntimeError, "OBSERVATION_TARGET_ROW_REQUIRED"):
                rotation_panel.recent_trade_dates(TOKEN, n=1, endpoint_session=self.session)
        self.assertEqual(len(seen), 1)

    def test_rotation_observed_industry_rows_cannot_be_relabelled_as_requested_day(self):
        seen = []
        values = [rpc("cal_date", [[TARGET]]),
                  rpc("trade_date,name,net_amount,pct_change", [["20261029", "Sector", 1, 0.5]])]
        with mock.patch.object(tushare_rows.urllib.request, "urlopen", self.opener(values, seen)), \
                mock.patch.object(rotation_panel, "OUT", str(self.root / "must-not-exist.json")):
            with self.assertRaisesRegex(RuntimeError, "OBSERVATION_REQUEST_DATE_REQUIRED"):
                rotation_panel.run(TOKEN, n_days=1, endpoint_session=self.session)
        self.assertEqual(len(seen), 2)
        self.assertFalse((self.root / "must-not-exist.json").exists())

    def test_market_target_selection_and_recording_failure_do_not_become_unavailable(self):
        value = rpc("trade_date,net_amount", [["20261102", 900000000], [TARGET, 200000000]])
        with mock.patch.object(fs, "_http_json", return_value=value):
            self.assertEqual(official._market_main_flow(TOKEN, endpoint_session=self.session), 2.0)
            self.assertEqual(official._market_main_flow(TOKEN), 9.0)
            with self.assertRaises(RuntimeError):
                official._market_main_flow(TOKEN, endpoint_session=SessionDouble("finish"))
        with mock.patch.object(fs, "_http_json", return_value=rpc("trade_date,net_amount", [["20261029", 1]])):
            with self.assertRaisesRegex(RuntimeError, "OBSERVATION_TARGET_ROW_REQUIRED"):
                official._market_main_flow(TOKEN, endpoint_session=self.session)

    def test_endpoint_session_is_never_enabled_by_environment(self):
        value = rpc("trade_date,close", [[TARGET, 10]])
        with mock.patch.dict(os.environ, {"AR_ENDPOINT_SESSION": "enabled"}), \
                mock.patch.object(fs, "_http_json", return_value=value):
            self.assertEqual(fs._tushare_call("unregistered_legacy", TOKEN, {}, ""), value["data"])
        self.assertEqual(self.session.calls, [])


if __name__ == "__main__":
    unittest.main()
