"""Real filesystem crash/no-replay checks using synthetic provider responses."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock
import uuid
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "experiments/execution_tracker"))
import fund_source as fs  # noqa: E402
from experiments.data_governance.call_receipts import (  # noqa: E402
    CallReceiptSink, record_call, read_call_receipts,
)
from experiments.data_governance import call_receipts as receipts_module  # noqa: E402
from experiments.data_governance.catalog import canonical, load_catalog  # noqa: E402
from test_data_source_catalog import CATALOG, context  # noqa: E402

NOW = datetime(2026, 10, 30, 8, 0, 0, tzinfo=timezone.utc)


def response(date="20261030", ticker="600000.SH"):
    return {"code": 0, "data": {"fields": ["ts_code", "trade_date", "close", "net_amount"],
                                "items": [[ticker, date, 10.0, 10000]]}}


class CallReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "receipts"
        self.catalog = load_catalog(CATALOG)
        self.ctx = context()
        self.sink = CallReceiptSink(self.root)
        self.invoke = mock.Mock(return_value=response())
        for target in ("socket.socket", "socket.create_connection", "socket.getaddrinfo"):
            patcher = mock.patch(target, side_effect=AssertionError("NETWORK_FORBIDDEN"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def call(self, **kwargs):
        args = dict(catalog=self.catalog, context=self.ctx, params={"ts_code": "600000.SH"},
                    invoke=self.invoke, sink=self.sink, clock=lambda: NOW)
        args.update(kwargs)
        return record_call(**args)

    def test_success_is_recorded_once(self):
        self.assertEqual(self.call(), response())
        self.invoke.assert_called_once_with()
        row, = read_call_receipts(self.root)
        self.assertEqual(row["status"], "SUCCEEDED")
        self.assertEqual((row["rows"], row["first_date"], row["last_date"], row["target_rows"]),
                         (1, "20261030", "20261030", 1))
        self.assertEqual(row["response_hash"], hashlib.sha256(canonical(response())).hexdigest())
        self.assertEqual(row["recording_scope"], "LOGICAL_PROVIDER_CALL")
        self.assertIsNone(row["transport_attempts"])
        self.assertEqual(row["transport_visibility"], "NOT_INSTRUMENTED")

    def test_start_failure_prevents_call(self):
        with mock.patch.object(self.sink, "start", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(RuntimeError, "CALL_RECORDING_INCOMPLETE"):
                self.call()
        self.invoke.assert_not_called()

    def test_finish_failure_never_replays_call(self):
        with mock.patch.object(self.sink, "finish", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(RuntimeError, "CALL_RECORDING_INCOMPLETE"):
                self.call()
        self.assertEqual(self.invoke.call_count, 1)
        self.assertEqual(read_call_receipts(self.root)[0]["status"], "INTERRUPTED")
        with self.assertRaisesRegex(RuntimeError, "CALL_ALREADY_STARTED"):
            self.call()
        self.assertEqual(self.invoke.call_count, 1)

    def test_duplicate_completed_call_does_not_invoke(self):
        self.call()
        before = {p.name: p.read_bytes() for p in self.root.rglob("*.json")}
        with self.assertRaisesRegex(RuntimeError, "CALL_ALREADY_STARTED"):
            self.call()
        self.assertEqual(self.invoke.call_count, 1)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.rglob("*.json")})

    def test_orphan_start_is_interrupted(self):
        self.assertTrue(self.sink.start(self.ctx, {"ts_code": "600000.SH"}))
        self.assertFalse(self.sink.start(self.ctx, {"ts_code": "600000.SH"}))
        row, = read_call_receipts(self.root)
        self.assertEqual(row["status"], "INTERRUPTED")
        self.assertFalse((self.root / self.ctx["logical_call_id"] / "terminal.json").exists())
        self.invoke.assert_not_called()

    def test_conflicting_start_and_terminal_refused(self):
        self.call()
        with self.assertRaisesRegex(ValueError, "RECEIPT_CONFLICT"):
            self.sink.start(dict(self.ctx, target_trade_date="20261029"), {"ts_code": "600000.SH"})
        terminal = json.loads((self.root / self.ctx["logical_call_id"] / "terminal.json").read_text())["result"]
        terminal["rows"] = 99
        with self.assertRaisesRegex(ValueError, "RECEIPT_CONFLICT"):
            self.sink.finish(self.ctx["logical_call_id"], terminal)

    def test_credentials_and_raw_error_not_persisted(self):
        secret = "test-DO-NOT-PERSIST-TOKEN"
        with self.assertRaises(ValueError):
            self.call(params={"ts_code": "600000.SH", "token": secret})
        self.invoke.assert_not_called()
        self.invoke.side_effect = PermissionError(secret)
        with self.assertRaisesRegex(RuntimeError, "PERMISSION_DENIED"):
            self.call()
        row, = read_call_receipts(self.root)
        self.assertEqual(row["error_code"], "PERMISSION_DENIED")
        self.assertNotIn(secret, "".join(p.read_text() for p in self.root.rglob("*.json")))

    def test_bad_context_or_params_blocks_before_call(self):
        for changes in ({"catalog_hash": "0" * 64}, {"source_id": "tushare.unregistered"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.call(context=dict(self.ctx, **changes))
        for params in ({"ts_code": "600001.SH"}, {"limit": True},
                       {"trade_date": "20261029"}, {"fields": "token,url"}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.call(params=params)
        self.invoke.assert_not_called()

    def test_stock_receipt_cannot_claim_unscoped_request(self):
        for ctx, params in ((self.ctx, {}),
                            (dict(self.ctx, ts_code=None, logical_call_id=str(uuid.uuid4())), {})):
            with self.subTest(ctx=ctx), self.assertRaises(ValueError):
                self.call(context=ctx, params=params)
        self.invoke.assert_not_called()

    def test_empty_and_missing_date_remain_visible(self):
        empty = {"code": 0, "data": {"fields": ["trade_date"], "items": []}}
        self.call(invoke=lambda: empty)
        row, = read_call_receipts(self.root)
        self.assertEqual(row["rows"], 0)
        self.assertIsNone(row["last_date"])

    def test_invalid_response_has_safe_failure_not_success(self):
        for value in ({"code": -1, "msg": "FAKE-secret"}, response(ticker="600001.SH"),
                      {"code": 0, "data": {"fields": ["trade_date"], "items": [[float('nan')]]}}):
            with self.subTest(value=value):
                self.ctx = context(call_id=str(uuid.uuid4()))
                with self.assertRaisesRegex(RuntimeError, "INVALID_RESPONSE"):
                    self.call(invoke=lambda: value)
        self.assertTrue(all(r["status"] == "FAILED" for r in read_call_receipts(self.root)))
        self.assertNotIn("FAKE-secret", "".join(p.read_text() for p in self.root.rglob("*.json")))

    def test_capacity_counts_orphans_before_invocation(self):
        sink = CallReceiptSink(self.root, max_calls=1)
        sink.start(self.ctx, {"ts_code": "600000.SH"})
        with self.assertRaisesRegex(RuntimeError, "CALL_RECORDING_INCOMPLETE"):
            self.call(context=context(call_id=str(uuid.uuid4())), sink=sink)
        self.invoke.assert_not_called()

    def test_symlink_and_oversize_refused(self):
        self.root.symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            self.call()
        self.invoke.assert_not_called()
        self.root.unlink()
        with self.assertRaises(RuntimeError):
            self.call(sink=CallReceiptSink(self.root, max_record_bytes=10))
        self.invoke.assert_not_called()

    def test_receipt_tampering_and_unsupported_version_refused(self):
        self.call()
        path = self.root / self.ctx["logical_call_id"] / "terminal.json"
        value = json.loads(path.read_text())
        value["start_hash"] = "0" * 64
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            read_call_receipts(self.root)

    def test_crash_at_each_publication_boundary_never_reinvokes_after_restart(self):
        real_link, real_fsync = receipts_module.os.link, receipts_module._fsync
        for stage in ("start_before_link", "start_after_link", "terminal_before_link", "terminal_after_link"):
            with self.subTest(stage=stage):
                root = self.root / stage
                sink = CallReceiptSink(root)
                invoke = mock.Mock(return_value=response())
                def link(src, dest, **kwargs):
                    if stage == dest.stem + "_before_link":
                        raise OSError("synthetic crash before publication")
                    return real_link(src, dest, **kwargs)
                def fsync(path):
                    for name in ("start", "terminal"):
                        if stage == name + "_after_link" and (path / (name + ".json")).exists():
                            raise OSError("synthetic crash after publication")
                    return real_fsync(path)
                with mock.patch.object(receipts_module.os, "link", side_effect=link), \
                        mock.patch.object(receipts_module, "_fsync", side_effect=fsync):
                    with self.assertRaisesRegex(RuntimeError, "CALL_RECORDING_INCOMPLETE"):
                        self.call(sink=sink, invoke=invoke)
                expected_calls = 0 if stage.startswith("start") else 1
                self.assertEqual(invoke.call_count, expected_calls)
                if stage == "start_before_link":
                    with self.assertRaises((ValueError, FileNotFoundError)):
                        read_call_receipts(root)
                else:
                    row, = read_call_receipts(root)
                    expected_status = "SUCCEEDED" if stage == "terminal_after_link" else "INTERRUPTED"
                    self.assertEqual(row["status"], expected_status)
                restarted = CallReceiptSink(root)
                with self.assertRaises(RuntimeError):
                    self.call(sink=restarted, invoke=invoke)
                self.assertEqual(invoke.call_count, expected_calls)

    def test_unknown_receipt_schema_is_refused(self):
        self.call()
        path = self.root / self.ctx["logical_call_id"] / "start.json"
        start = json.loads(path.read_text())
        start["schema"] = "ar.data-call-receipt.v0"
        path.write_text(json.dumps(start))
        with self.assertRaises(ValueError):
            read_call_receipts(self.root)

    def test_future_invocation_refused_before_any_call(self):
        error = None
        try:
            self.call(context=dict(self.ctx, invoked_at="2099-01-01T00:00:00Z"))
        except (ValueError, RuntimeError) as exc:
            error = exc
        self.assertIsInstance(error, ValueError)
        self.assertEqual(str(error), "INVOCATION_CLOCK_CONFLICT")
        self.invoke.assert_not_called()

    def test_opt_in_fund_consumes_target_row_not_provider_order(self):
        value = response("20261029")
        value["data"]["items"].append(["600000.SH", "20261030", 11.0, 20000])
        ctx = context("tushare.moneyflow_dc")
        with mock.patch.object(fs, "_http_json", return_value=value):
            legacy = fs.tushare_stock_fund("600000.SH", "FAKE-KEY", "20261030")
            current = fs.tushare_stock_fund("600000.SH", "FAKE-KEY", "20261030",
                                           observation_context=ctx, receipt_sink=self.sink)
        self.assertEqual(legacy["date"], "20261029")
        self.assertEqual((current["date"], current["main"]), ("20261030", 2.0))

    def test_ambiguous_target_is_rejected_through_adapter_receipt_and_health(self):
        from experiments.data_governance.health import evaluate_health, plan_backfills
        value = response()
        value["data"]["items"].append(["600000.SH", "20261030", 11.0, 20000])
        ctx = context("tushare.moneyflow_dc")
        with mock.patch.object(fs, "_http_json", return_value=value):
            with self.assertRaisesRegex(RuntimeError, "INVALID_RESPONSE"):
                fs.tushare_stock_fund("600000.SH", "FAKE-KEY", "20261030",
                                      observation_context=ctx, receipt_sink=self.sink)
        rows = read_call_receipts(self.root)
        self.assertEqual(rows[0]["status"], "FAILED")
        health = evaluate_health(self.catalog, rows, target_trade_date="20261030")
        self.assertEqual(health["sources"]["tushare.moneyflow_dc"]["status"], "DATA_BLOCKED")
        plan, = [p for p in plan_backfills(health, now=NOW) if p["source_id"] == "tushare.moneyflow_dc"]
        self.assertEqual(plan["status"], "BLOCKED_EVIDENCE")

    def test_http_denials_have_safe_nonretryable_classification(self):
        for code in (401, 403):
            self.ctx = context(call_id=str(uuid.uuid4()))
            error = urllib.error.HTTPError("https://synthetic.invalid", code, "FAKE-SECRET", {}, None)
            with self.subTest(code=code), self.assertRaisesRegex(RuntimeError, "PERMISSION_DENIED"):
                self.call(invoke=mock.Mock(side_effect=error))
        for row in read_call_receipts(self.root):
            self.assertEqual(row["error_code"], "PERMISSION_DENIED")
        self.assertNotIn("FAKE-SECRET", "".join(p.read_text() for p in self.root.rglob("*.json")))

    def test_terminal_retry_does_not_accumulate_partials(self):
        captured = []
        real_finish = self.sink.finish
        def fail_finish(identifier, result):
            captured.append(result)
            with mock.patch.object(receipts_module.os, "link", side_effect=OSError("disk full")):
                real_finish(identifier, result)
        with mock.patch.object(self.sink, "finish", side_effect=fail_finish):
            with self.assertRaisesRegex(RuntimeError, "CALL_RECORDING_INCOMPLETE"):
                self.call()
        for _ in range(8):
            with mock.patch.object(receipts_module.os, "link", side_effect=OSError("disk full")):
                with self.assertRaises((ValueError, OSError)):
                    self.sink.finish(self.ctx["logical_call_id"], captured[0])
        self.assertEqual(len(list(self.root.rglob("*.partial"))), 1)

    def test_adapters_opt_in_and_legacy_default(self):
        for method, source in (("daily", "tushare.daily"), ("fund", "tushare.moneyflow_dc")):
            with self.subTest(method=method):
                self.ctx = context(source, call_id=str(uuid.uuid4()))
                with mock.patch.object(fs, "_http_json", return_value=response()) as transport:
                    if method == "daily":
                        got = fs._tushare_call("daily", "FAKE-KEY", {"ts_code": "600000.SH"},
                                              "ts_code,trade_date,close", observation_context=self.ctx,
                                              receipt_sink=self.sink)
                        self.assertEqual(got, response()["data"])
                    else:
                        got = fs.tushare_stock_fund("600000.SH", "FAKE-KEY", "20261030",
                                                   observation_context=self.ctx, receipt_sink=self.sink)
                        self.assertEqual(got["main"], 1.0)
                    self.assertEqual(transport.call_count, 1)
        self.assertEqual(len(read_call_receipts(self.root)), 2)
        with mock.patch.object(fs, "_http_json", return_value=response()):
            fs._tushare_call("unregistered_legacy", "FAKE-KEY", {}, "")
        self.assertEqual(len(read_call_receipts(self.root)), 2)


if __name__ == "__main__":
    unittest.main()
