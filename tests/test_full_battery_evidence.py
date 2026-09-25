#!/usr/bin/env python3
"""Offline behavior regressions for missing and after-as-of U3 evidence."""
from __future__ import annotations

import datetime
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))

import full_battery  # noqa: E402
import funnel_dag  # noqa: E402
import funnel_pipeline  # noqa: E402
import red_flag_gate  # noqa: E402
import u4_pre_decision  # noqa: E402

TARGET = "20260923"
CODE = "002119.SZ"
FUNDAMENTALS = "基本面"
NEWS = "消息面"
VALUATION = "估值"


class FakeProvider:
    def __init__(self, empty=(), loss_pe=False, announcements=None):
        self.empty = set(empty)
        self.loss_pe = loss_pe
        self.announcements = announcements

    def daily(self, **_kwargs):
        end = datetime.date(2026, 9, 23)
        return pd.DataFrame([
            {"trade_date": (end - datetime.timedelta(days=60 - i)).strftime("%Y%m%d"),
             "close": 10.0, "high": 11.0, "low": 9.0, "pct_chg": 0.0,
             "amount": 100000.0, "vol": 10000.0}
            for i in range(61)
        ])

    def moneyflow_dc(self, **_kwargs):
        return pd.DataFrame([
            {"trade_date": f"202609{day:02d}", "net_amount": 100.0}
            for day in range(14, 24)
        ])

    def income(self, **_kwargs):
        columns = ["end_date", "report_type", "revenue", "n_income_attr_p"]
        rows = [] if "income" in self.empty else [["20260630", "1", 1e9, 1e8]]
        return pd.DataFrame(rows, columns=columns)

    def fina_indicator(self, **_kwargs):
        columns = ["end_date", "grossprofit_margin", "roe"]
        rows = [] if "fina_indicator" in self.empty else [["20260630", 20.0, 10.0]]
        return pd.DataFrame(rows, columns=columns)

    def daily_basic(self, **_kwargs):
        columns = ["trade_date", "pe_ttm", "pb", "total_mv"]
        pe = float("nan") if self.loss_pe else 20.0
        rows = [] if "daily_basic" in self.empty else [[TARGET, pe, 2.0, 1000000.0]]
        return pd.DataFrame(rows, columns=columns)

    def anns_d(self, **_kwargs):
        if self.announcements is None:
            raise RuntimeError("fixture source unavailable")
        return pd.DataFrame(self.announcements, columns=["ann_date", "title"])


class BatteryEvidenceTests(unittest.TestCase):
    def setUp(self):
        offline = mock.patch.dict(os.environ, {"AR_OFFLINE": "1"})
        offline.start()
        self.addCleanup(offline.stop)
        network = mock.patch("socket.socket.connect", side_effect=AssertionError("network forbidden"))
        network.start()
        self.addCleanup(network.stop)

    def run_battery(self, provider=None, titles=()):
        # Red-flag internals are outside this regression; U3/U4 remain real.
        with mock.patch.object(red_flag_gate, "check_ticker", return_value={
            "verdict": "PASS", "reasons": [], "latest_e1_date": "20260820",
        }), mock.patch.object(full_battery, "_fetch_anns_eastmoney", return_value=titles):
            return funnel_dag._sanitize_row(
                full_battery.battery(provider or FakeProvider(), CODE, TARGET)
            )

    def u4_row(self, row):
        candidate = {"ts_code": CODE, "industry_key": "半导体",
                     "source_channels": ["PRICE_VOLUME"], "flags": [],
                     "review_status": "MAIN_CHANNEL", "cluster_id": None}
        battery = {"checked_at": TARGET, "results": [row]}
        queue = funnel_pipeline.build_deep_research_queue(
            candidate_review={"rows": [candidate]}, battery=battery,
            selected_tickers=[], trade_date=TARGET,
        )
        bundle = {"candidate_manifest": {"ts_codes": [CODE]},
                  "candidates": {"rows": [candidate]},
                  "registry": {"rows": [{"ts_code": CODE, "name": "Fixture"}]},
                  "battery": battery, "manifest": {"as_of": TARGET}, "queue": queue}
        return u4_pre_decision._candidate_rows(bundle, "半导体", "RESEARCH_CLOSED_LOOP_V1", {})[0]

    def assert_blocked(self, row, dimension):
        self.assertEqual("PARTIAL", row["completeness"]["verdict"])
        self.assertEqual("DATA_BLOCKED", row["dims"][dimension].get("status"))
        self.assertIn(dimension, row["completeness"]["missing"])
        projected = self.u4_row(row)
        self.assertFalse(projected["allowed_for_u4_packet"])
        self.assertIn("U3_BATTERY_INCOMPLETE", projected["blocked_reasons"])

    def test_empty_income_cannot_reach_u4(self):
        row = self.run_battery(FakeProvider(empty={"income"}))
        self.assert_blocked(row, FUNDAMENTALS)
        self.assertIn("INCOME_EMPTY", row["dims"][FUNDAMENTALS]["reason_codes"])

    def test_empty_fina_indicator_cannot_reach_u4(self):
        row = self.run_battery(FakeProvider(empty={"fina_indicator"}))
        self.assert_blocked(row, FUNDAMENTALS)
        self.assertIn("FINA_INDICATOR_EMPTY", row["dims"][FUNDAMENTALS]["reason_codes"])

    def test_empty_daily_basic_cannot_reach_u4(self):
        row = self.run_battery(FakeProvider(empty={"daily_basic"}))
        self.assert_blocked(row, VALUATION)
        self.assertIn("DAILY_BASIC_EMPTY", row["dims"][VALUATION]["err"])

    def test_both_empty_financial_sources_remain_explicit(self):
        row = self.run_battery(FakeProvider(empty={"income", "fina_indicator"}))
        self.assert_blocked(row, FUNDAMENTALS)
        self.assertEqual(["INCOME_EMPTY", "FINA_INDICATOR_EMPTY"],
                         row["dims"][FUNDAMENTALS]["reason_codes"])

    def test_loss_pe_and_optional_ma250_remain_complete(self):
        row = self.run_battery(FakeProvider(loss_pe=True))
        self.assertEqual("COMPLETE", row["completeness"]["verdict"])
        self.assertIsNone(row["dims"][VALUATION]["pe_ttm"])
        self.assertEqual(2.0, row["dims"][VALUATION]["pb"])
        self.assertIsNone(row["dims"]["技术面"]["vs_MA250_pct"])
        self.assertTrue(self.u4_row(row)["allowed_for_u4_packet"])

    def test_future_announcements_excluded_from_counts_and_titles(self):
        row = self.run_battery(titles=[("2026-09-24", "future"),
                                       ("2026-09-23", "at cutoff"),
                                       ("2026-09-10", "older")])
        news = row["dims"][NEWS]
        self.assertEqual(["2026-09-23 at cutoff", "2026-09-10 older"], news["最新3条"])
        self.assertEqual(2, news["最近公告条数"])
        self.assertEqual(1, news["近7日公告条数"])
        self.assertEqual(1, news["excluded_after_as_of_count"])
        self.assertIn("ANNOUNCEMENT_AFTER_AS_OF_EXCLUDED", news["reason_codes"])
        self.assertEqual("COMPLETE", row["completeness"]["verdict"])

    def test_full_eastmoney_page_cannot_claim_historical_counts_complete(self):
        titles = [("2026-09-24", f"future {i}") for i in range(29)]
        titles.append(("2026-09-23", "at cutoff"))
        row = self.run_battery(titles=titles)
        self.assert_blocked(row, NEWS)
        news = row["dims"][NEWS]
        self.assertEqual(["2026-09-23 at cutoff"], news["最新3条"])
        self.assertIsNone(news["最近公告条数"])
        self.assertIsNone(news["近7日公告条数"])
        self.assertIn("ANNOUNCEMENT_PAGE_COVERAGE_UNVERIFIED", news["reason_codes"])

    def test_only_future_announcements_are_unknown_not_zero(self):
        row = self.run_battery(titles=[("2026-09-24", "future")])
        self.assert_blocked(row, NEWS)
        news = row["dims"][NEWS]
        self.assertEqual([], news["最新3条"])
        self.assertIsNone(news["最近公告条数"])
        self.assertIsNone(news["近7日公告条数"])
        self.assertEqual(1, news["excluded_after_as_of_count"])
        self.assertIn("NO_ANNOUNCEMENT_AT_OR_BEFORE_AS_OF", news["reason_codes"])

    def test_unknown_announcement_dates_are_unknown_not_zero(self):
        for raw_date in (None, "", "unknown", "2026-09-31"):
            with self.subTest(raw_date=raw_date):
                row = self.run_battery(titles=[(raw_date, "unverifiable")])
                self.assert_blocked(row, NEWS)
                news = row["dims"][NEWS]
                self.assertIsNone(news["最近公告条数"])
                self.assertIsNone(news["近7日公告条数"])
                self.assertEqual([], news["最新3条"])
                self.assertIn("ANNOUNCEMENT_DATE_UNVERIFIABLE", news["reason_codes"])

    def test_mixed_unknown_dates_keep_known_titles_but_block_counts(self):
        row = self.run_battery(titles=[("20260923", "known"), ("", "unknown")])
        self.assert_blocked(row, NEWS)
        news = row["dims"][NEWS]
        self.assertEqual(["20260923 known"], news["最新3条"])
        self.assertIsNone(news["近7日公告条数"])
        self.assertEqual(1, news["unverifiable_date_count"])

    def test_confirmed_empty_news_is_zero_not_failure(self):
        row = self.run_battery(titles=[])
        news = row["dims"][NEWS]
        self.assertEqual(0, news["最近公告条数"])
        self.assertEqual(0, news["近7日公告条数"])
        self.assertEqual([], news["最新3条"])
        self.assertEqual("COMPLETE", row["completeness"]["verdict"])

    def test_eastmoney_error_envelopes_do_not_claim_zero_announcements(self):
        responses = (
            {"code": 500, "data": None},
            {"code": 500, "data": {"list": []}},
            {"success": False, "data": {"list": []}},
            {"data": {}},
            {"data": {"list": None}},
        )
        for response in responses:
            with self.subTest(response=response):
                body = json.dumps(response).encode("utf-8")
                with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), \
                        mock.patch("urllib.request.urlopen", side_effect=lambda *_args, **_kwargs: io.BytesIO(body)):
                    self.assertIsNone(full_battery._fetch_anns_eastmoney(CODE))
                    with mock.patch.object(red_flag_gate, "check_ticker", return_value={
                        "verdict": "PASS", "reasons": [], "latest_e1_date": "20260820",
                    }):
                        row = funnel_dag._sanitize_row(
                            full_battery.battery(FakeProvider(), CODE, TARGET)
                        )
                self.assert_blocked(row, NEWS)

    def test_eastmoney_successful_empty_page_remains_zero(self):
        body = b'{"code":1,"success":true,"data":{"list":[],"total_hits":0}}'
        with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), \
                mock.patch("urllib.request.urlopen", return_value=io.BytesIO(body)):
            self.assertEqual([], full_battery._fetch_anns_eastmoney(CODE))

    def test_eastmoney_proven_short_page_remains_usable(self):
        body = b'{"code":1,"success":true,"data":{"list":[{"notice_date":"2026-09-22","title":"Fixture disclosure"}],"total_hits":1}}'
        with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), \
                mock.patch("urllib.request.urlopen", return_value=io.BytesIO(body)):
            self.assertEqual([("2026-09-22", "Fixture disclosure")],
                             full_battery._fetch_anns_eastmoney(CODE))

    def test_eastmoney_proven_full_page_is_not_marked_incomplete(self):
        page = [{"notice_date": "2026-09-23", "title": f"Fixture {i}"}
                for i in range(30)]
        body = json.dumps({"code": 1, "success": True, "data": {
            "list": page, "total_hits": len(page),
        }}).encode("utf-8")
        with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), \
                mock.patch("urllib.request.urlopen", return_value=io.BytesIO(body)), \
                mock.patch.object(red_flag_gate, "check_ticker", return_value={
                    "verdict": "PASS", "reasons": [], "latest_e1_date": "20260820",
                }):
            row = funnel_dag._sanitize_row(full_battery.battery(FakeProvider(), CODE, TARGET))
        self.assertEqual(30, row["dims"][NEWS]["最近公告条数"])
        self.assertNotIn("ANNOUNCEMENT_PAGE_COVERAGE_UNVERIFIED",
                         row["dims"][NEWS]["reason_codes"])

    def test_eastmoney_overlength_page_is_not_trusted(self):
        page = [{"notice_date": "2026-09-23", "title": f"Fixture {i}"}
                for i in range(31)]
        body = json.dumps({"code": 1, "success": True, "data": {
            "list": page, "total_hits": len(page),
        }}).encode("utf-8")
        with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), \
                mock.patch("urllib.request.urlopen", return_value=io.BytesIO(body)):
            self.assertIsNone(full_battery._fetch_anns_eastmoney(CODE, page_size=30))

    def test_eastmoney_ambiguous_empty_response_blocks_u4(self):
        responses = (
            {"code": 0, "message": "backend unavailable", "data": {"list": [], "total_hits": 0}},
            {"code": 1, "data": {"list": [], "total_hits": 0}},
            {"code": 500, "success": True, "data": {"list": [], "total_hits": 0}},
        )
        for response in responses:
            with self.subTest(response=response):
                body = json.dumps(response).encode("utf-8")
                with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), \
                        mock.patch("urllib.request.urlopen", side_effect=lambda *_args, **_kwargs: io.BytesIO(body)), \
                        mock.patch.object(red_flag_gate, "check_ticker", return_value={
                            "verdict": "PASS", "reasons": [], "latest_e1_date": "20260820",
                        }):
                    row = funnel_dag._sanitize_row(full_battery.battery(FakeProvider(), CODE, TARGET))
                self.assert_blocked(row, NEWS)

    def test_eastmoney_malformed_success_page_blocks_u4(self):
        responses = (
            {"code": 1, "success": True, "data": {"total_hits": 0}},
            {"code": 1, "success": True, "data": {"list": None, "total_hits": 0}},
        )
        for response in responses:
            with self.subTest(response=response):
                body = json.dumps(response).encode("utf-8")
                with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), \
                        mock.patch("urllib.request.urlopen", side_effect=lambda *_args, **_kwargs: io.BytesIO(body)), \
                        mock.patch.object(red_flag_gate, "check_ticker", return_value={
                            "verdict": "PASS", "reasons": [], "latest_e1_date": "20260820",
                        }):
                    row = funnel_dag._sanitize_row(full_battery.battery(FakeProvider(), CODE, TARGET))
                self.assert_blocked(row, NEWS)

    def test_eastmoney_short_page_requires_matching_total_hits(self):
        responses = (
            {"code": 1, "success": True, "data": {"list": []}},
            {"code": 1, "success": True, "data": {"list": [], "total_hits": 42}},
            {"code": 1, "success": True, "data": {"list": [
                {"notice_date": "2026-09-22", "title": "Fixture disclosure"},
            ], "total_hits": 0}},
        )
        for response in responses:
            with self.subTest(response=response):
                body = json.dumps(response).encode("utf-8")
                with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), \
                        mock.patch("urllib.request.urlopen", side_effect=lambda *_args, **_kwargs: io.BytesIO(body)), \
                        mock.patch.object(red_flag_gate, "check_ticker", return_value={
                            "verdict": "PASS", "reasons": [], "latest_e1_date": "20260820",
                        }):
                    row = funnel_dag._sanitize_row(full_battery.battery(FakeProvider(), CODE, TARGET))
                self.assert_blocked(row, NEWS)

    def test_latest_announcements_are_ordered_by_date(self):
        row = self.run_battery(titles=[
            ("2026-09-01", "old"), ("2026-09-20", "newer"),
            ("2026-09-10", "middle"), ("2026-09-23", "latest"),
        ])
        self.assertEqual([
            "2026-09-23 latest", "2026-09-20 newer", "2026-09-10 middle",
        ], row["dims"][NEWS]["最新3条"])

    def test_failed_news_sources_are_not_zero(self):
        row = self.run_battery(titles=None)
        self.assert_blocked(row, NEWS)
        self.assertIsNone(row["dims"][NEWS].get("近7日公告条数"))

    def test_fallback_news_obeys_same_as_of_filter(self):
        provider = FakeProvider(announcements=[("20260924", "future"), ("20260923", "known")])
        row = self.run_battery(provider, titles=None)
        news = row["dims"][NEWS]
        self.assertEqual(["20260923 known"], news["最新3条"])
        self.assertEqual(1, news["最近公告条数"])
        self.assertEqual(1, news["excluded_after_as_of_count"])

    def test_fallback_news_does_not_truncate_after_eight_rows(self):
        provider = FakeProvider(announcements=[(TARGET, f"filing {i}") for i in range(12)])
        row = self.run_battery(provider, titles=None)
        news = row["dims"][NEWS]
        self.assertEqual(12, news["最近公告条数"])
        self.assertEqual("COMPLETE", row["completeness"]["verdict"])


if __name__ == "__main__":
    unittest.main()
