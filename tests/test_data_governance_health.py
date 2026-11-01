"""Synthetic mixed-date incident, with receipts through the real recorder."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from experiments.data_governance.call_receipts import CallReceiptSink, read_call_receipts, record_call
from experiments.data_governance.catalog import load_catalog, aware_time, canonical
import hashlib
from experiments.data_governance.health import evaluate_health, plan_backfills
from test_data_source_catalog import CATALOG, context
from test_data_call_receipts import NOW, response


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "receipts"
        self.sink = CallReceiptSink(self.root)
        self.catalog = load_catalog(CATALOG)
        for target in ("socket.socket", "socket.create_connection", "socket.getaddrinfo"):
            patcher = mock.patch(target, side_effect=AssertionError("NETWORK_FORBIDDEN"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def add(self, source="tushare.daily", ticker="600000.SH", date="20261030",
            error=None, run=None, at=None, target="20261030", empty=False):
        ctx = context(source, ticker, call_id=str(uuid.uuid4()))
        ctx.update(target_trade_date=target)
        if run:
            ctx["collector_run_id"] = run
        if at:
            ctx["invoked_at"] = at
        def invoke():
            if error:
                raise error("FAKE-secret")
            value = response(date, ticker)
            if empty:
                value["data"]["items"] = []
            return value
        try:
            clock = aware_time(ctx["invoked_at"]) + timedelta(seconds=1)
            record_call(self.catalog, ctx, {"ts_code": ticker}, invoke, self.sink, lambda: clock)
        except RuntimeError:
            if not error:
                raise
        return ctx

    def health(self):
        return evaluate_health(self.catalog, read_call_receipts(self.root), target_trade_date="20261030")

    def test_mixed_dates_block_affected_source(self):
        self.add()
        for ticker in ("600000.SH", "600001.SH", "600002.SH"):
            self.add("tushare.moneyflow_dc", ticker)
        self.add("tushare.moneyflow_dc", "603629.SH", "20261029")
        health = self.health()
        self.assertEqual(health["sources"]["tushare.moneyflow_dc"]["status"], "STALE")
        gaps = health["sources"]["tushare.moneyflow_dc"]["scopes"]
        affected = [v for v in gaps if v["status"] != "OK"]
        self.assertEqual([v["ts_code"] for v in affected], ["603629.SH"])
        self.assertIn("official_sample", affected[0]["downstream"])
        self.assertEqual(health["status"], "PARTIAL")
        self.assertEqual(health["coverage"], "OBSERVED_CALLS_ONLY")

    def test_unknown_and_future_dates_not_ok(self):
        self.add(date=None)
        self.add(ticker="600001.SH", date="20261102")
        health = self.health()
        source = health["sources"]["tushare.daily"]
        self.assertEqual(source["status"], "DATA_BLOCKED")
        self.assertEqual({s["reason"] for s in source["scopes"]}, {"MISSING_DATE", "FUTURE_DATE"})

    def test_registered_but_uninstrumented(self):
        self.add()
        source = self.health()["sources"]["tushare.daily_basic"]
        self.assertEqual(source["status"], "NOT_RUN")
        self.assertEqual(source["reason"], "NOT_INSTRUMENTED")

    def test_empty_required_is_not_valid_empty(self):
        self.add(empty=True)
        scope = self.health()["sources"]["tushare.daily"]["scopes"][0]
        self.assertEqual((scope["status"], scope["reason"]), ("DATA_BLOCKED", "EMPTY_REQUIRED"))

    def test_new_failure_does_not_reuse_previous_success(self):
        self.add(at="2026-10-30T16:00:00+08:00")
        self.add(error=TimeoutError, at="2026-10-30T16:01:00+08:00")
        self.assertEqual(self.health()["sources"]["tushare.daily"]["status"], "SOURCE_DOWN")

    def test_tied_or_different_runs_not_hidden(self):
        self.add()
        self.add(error=TimeoutError)
        self.add(run="second-synthetic-run")
        scopes = self.health()["sources"]["tushare.daily"]["scopes"]
        self.assertEqual(len(scopes), 2)
        self.assertEqual({v["status"] for v in scopes}, {"OK", "SOURCE_DOWN"})

    def test_old_target_does_not_fill_current_target(self):
        self.add(target="20261029", date="20261029")
        health = self.health()
        self.assertEqual(health["sources"]["tushare.daily"]["status"], "NOT_RUN")
        self.assertEqual(health["out_of_scope_calls"], 1)

    def test_backfill_is_stable_and_non_dispatching(self):
        self.add("tushare.moneyflow_dc", "603629.SH", "20261029")
        health = self.health()
        before = {str(p): p.read_bytes() for p in self.root.rglob("*.json")}
        first = plan_backfills(health, now=NOW)
        second = plan_backfills(health, now=datetime(2026, 11, 1, tzinfo=timezone.utc))
        self.assertEqual([v["gap_id"] for v in first], [v["gap_id"] for v in second])
        self.assertTrue(all(v["dispatch_allowed"] is False for v in first))
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob("*.json")})
        flow, = [v for v in first if v["ts_code"] == "603629.SH"]
        self.assertEqual(flow["status"], "PLANNED_NOT_DISPATCHABLE")

    def test_exhausted_or_permission_gap_not_retried(self):
        self.add(error=TimeoutError)
        self.add(error=TimeoutError)
        self.add("tushare.moneyflow_dc", error=PermissionError)
        plans = plan_backfills(self.health(), now=NOW)
        daily, = [v for v in plans if v["source_id"] == "tushare.daily"]
        fund, = [v for v in plans if v["source_id"] == "tushare.moneyflow_dc"]
        self.assertEqual((daily["status"], daily["attempts_seen"]), ("EXHAUSTED", 2))
        self.assertEqual(fund["status"], "BLOCKED_PERMISSION")

    def test_interrupted_and_duplicate_receipts_do_not_invent_attempts(self):
        ctx = context()
        self.sink.start(ctx, {"ts_code": "600000.SH"})
        rows = read_call_receipts(self.root)
        health = evaluate_health(self.catalog, rows + rows, target_trade_date="20261030")
        plans = plan_backfills(health, now=NOW)
        daily, = [v for v in plans if v["source_id"] == "tushare.daily"]
        self.assertEqual(daily["status"], "BLOCKED_RECONCILIATION")
        self.assertEqual(daily["attempts_seen"], 0)
        self.assertEqual(len(daily["evidence_refs"]), 1)

    def test_catalog_binding_and_receipt_contract_refused(self):
        self.add()
        rows = read_call_receipts(self.root)
        rows[0]["context"]["catalog_hash"] = "0" * 64
        with self.assertRaises(ValueError):
            evaluate_health(self.catalog, rows, target_trade_date="20261030")
        with self.assertRaises(ValueError):
            evaluate_health(self.catalog, [{"status": "OK"}], target_trade_date="20261030")

    def test_future_timestamp_cannot_mask_new_failure(self):
        self.add()
        self.add(error=TimeoutError, at="2026-10-30T16:01:00+08:00")
        rows = read_call_receipts(self.root)
        prior, = [r for r in rows if r["status"] == "SUCCEEDED"]
        prior["context"]["invoked_at"] = "2099-01-01T00:00:00Z"
        start = {k: prior[k] for k in ("schema", "context", "params", "recording_scope",
                                        "transport_attempts", "transport_visibility")}
        start["status"] = "STARTED"
        prior["start_hash"] = hashlib.sha256(canonical(start)).hexdigest()
        with self.assertRaisesRegex(ValueError, "INVOCATION_CLOCK_CONFLICT"):
            evaluate_health(self.catalog, rows, target_trade_date="20261030")

    def test_historical_ambiguous_receipt_never_becomes_ok(self):
        self.add()
        rows = read_call_receipts(self.root)
        rows[0].update(rows=2, target_rows=2)
        health = evaluate_health(self.catalog, rows, target_trade_date="20261030")
        self.assertEqual(health["sources"]["tushare.daily"]["status"], "DATA_BLOCKED")
        plan, = [p for p in plan_backfills(health, now=NOW) if p["source_id"] == "tushare.daily"]
        self.assertEqual(plan["status"], "BLOCKED_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
