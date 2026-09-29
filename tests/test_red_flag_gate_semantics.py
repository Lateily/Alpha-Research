"""U3 red-flag gate v1 semantics — offline, zero network, zero token.

2026-09-25 re-review P1 #2/#3: the U3 gate (red_flag_gate.check_ticker, feeding
full_battery 基本面 -> funnel U3 -> u4_pre_decision) misread the express
``yoy_net_profit`` AMOUNT as a YoY percent, never retired guidance/express that
a filed statement had already superseded, and let NaN income or positional
quarter pairs PASS silently.  v1 delegates to e1_event_layer.classify_ticker,
the same rule set as the full-market E1 layer, so the two gates cannot drift.

Run: python3 tests/test_red_flag_gate_semantics.py
不是买卖指令；研究信号，human executes。
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ["AR_OFFLINE"] = "1"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "experiments", "execution_tracker"))
sys.path.insert(0, os.path.join(ROOT, "experiments", "research_funnel"))

import pandas as pd  # noqa: E402

import e1_event_layer as e1  # noqa: E402
import red_flag_gate  # noqa: E402
from red_flag_gate import check_ticker  # noqa: E402

FORECAST_COLUMNS = ["ts_code", "ann_date", "end_date", "type", "net_profit_min", "net_profit_max",
                    "p_change_min", "p_change_max"]
EXPRESS_COLUMNS = ["ts_code", "ann_date", "end_date", "revenue", "n_income", "yoy_net_profit",
                   "yoy_dedu_np"]
INCOME_COLUMNS = ["ts_code", "ann_date", "end_date", "report_type", "n_income_attr_p"]
RED_PREFIXES = ("最新预告", "最新快报净利同比", "最近季度归母")
NAN = float("nan")


def _frame(rows, columns):
    # Mimic the provider: a DataFrame whose missing numerics are NaN, not None.
    return pd.DataFrame([{c: row.get(c, NAN if c not in ("ts_code", "ann_date", "end_date",
                                                         "type", "report_type") else None)
                          for c in columns} for row in rows], columns=columns)


def _income(*rows):
    return [{"ann_date": ann, "end_date": end, "report_type": "1", "n_income_attr_p": value}
            for ann, end, value in rows]


# Filed cumulative attributable profit, CNY: FY2025 → H1-2026, all positive.
FILED_THROUGH_H1_2026 = _income(
    ("20251028", "20250930", 3.0e8),
    ("20260328", "20251231", 4.0e8),
    ("20260428", "20260331", 1.0e8),
    ("20260828", "20260630", 2.5e8),
)
FILED_THROUGH_Q1_2026 = FILED_THROUGH_H1_2026[:3]


class FakePro:
    def __init__(self, forecast=(), express=(), income=(), fail=()):
        self._rows = {"forecast": list(forecast), "express": list(express), "income": list(income)}
        self._fail = set(fail)
        self.calls = []

    def _serve(self, api, columns, kwargs):
        self.calls.append((api, dict(kwargs)))
        if api in self._fail:
            raise RuntimeError("TUSHARE_READ_FAILED:URLError")
        return _frame(self._rows[api], columns)

    def forecast(self, **kw):
        return self._serve("forecast", FORECAST_COLUMNS, kw)

    def express(self, **kw):
        return self._serve("express", EXPRESS_COLUMNS, kw)

    def income(self, **kw):
        return self._serve("income", INCOME_COLUMNS, kw)


class ExpressSemanticsTests(unittest.TestCase):
    def test_express_prior_year_amount_is_not_a_percent(self):
        # 920038.BJ-shaped row: yoy_net_profit is last year's profit (-74,400,964.91 CNY).
        pro = FakePro(express=[{"ann_date": "20260720", "end_date": "20260630",
                                "n_income": -55_846_879.39, "yoy_net_profit": -74_400_964.91}],
                      income=FILED_THROUGH_Q1_2026)
        result = check_ticker(pro, "920038.BJ", "20260725")
        self.assertEqual("PASS", result["verdict"], result)
        self.assertNotIn("EXPRESS_NET_PROFIT_DROP_GT_30PCT", result["reason_codes"])
        self.assertFalse(any("7440" in text or "%" in text for text in result["reasons"]), result)
        self.assertEqual("PRESENT", result["evidence_coverage"]["express"])

    def test_express_real_drop_still_flags_with_computed_percent(self):
        pro = FakePro(express=[{"ann_date": "20260720", "end_date": "20260630",
                                "n_income": 2.0e7, "yoy_net_profit": 1.0e8}],
                      income=FILED_THROUGH_Q1_2026)
        result = check_ticker(pro, "600001.SH", "20260725")
        self.assertEqual("RED_FLAG", result["verdict"], result)
        self.assertEqual(["EXPRESS_NET_PROFIT_DROP_GT_30PCT"], result["reason_codes"])
        self.assertTrue(result["reasons"][0].startswith("最新快报净利同比-80.0%"), result)

    def test_null_express_row_is_not_evidence(self):
        pro = FakePro(express=[{"ann_date": "20260720", "end_date": "20260630"}],
                      income=FILED_THROUGH_Q1_2026)
        result = check_ticker(pro, "600001.SH", "20260725")
        self.assertEqual("DATA_BLOCKED", result["verdict"], result)
        self.assertEqual(["EXPRESS_YOY_METRIC_MISSING"], result["reason_codes"])


class SupersessionTests(unittest.TestCase):
    def test_fy2025_guidance_superseded_by_filed_h1_2026(self):
        pro = FakePro(forecast=[{"ann_date": "20260131", "end_date": "20251231", "type": "预减",
                                 "net_profit_min": 20000.0, "net_profit_max": 30000.0}],
                      express=[{"ann_date": "20260228", "end_date": "20251231",
                                "n_income": 4.0e8, "yoy_net_profit": -4.384e8}],
                      income=FILED_THROUGH_H1_2026)
        result = check_ticker(pro, "688512.SH", "20260924")
        self.assertEqual("PASS", result["verdict"], result)
        self.assertEqual([], result["reasons"])
        self.assertEqual("SUPERSEDED", result["evidence_coverage"]["forecast"])
        self.assertEqual("SUPERSEDED", result["evidence_coverage"]["express"])
        self.assertEqual("20260630", result["latest_filed_period"])
        # latest_e1_date now reflects the filing that was read, not the stale guidance.
        self.assertEqual("20260828", result["latest_e1_date"])

    def test_genuine_current_period_first_loss_still_flags(self):
        pro = FakePro(forecast=[{"ann_date": "20260915", "end_date": "20260930", "type": "首亏",
                                 "net_profit_min": -18000.0, "net_profit_max": -15000.0}],
                      income=FILED_THROUGH_H1_2026)
        result = check_ticker(pro, "601127.SH", "20260924")
        self.assertEqual("RED_FLAG", result["verdict"], result)
        self.assertEqual(["NEGATIVE_ISSUER_GUIDANCE"], result["reason_codes"])
        self.assertTrue(result["reasons"][0].startswith("最新预告[首亏] 20260915 期末20260930"))
        self.assertIn("[code=NEGATIVE_ISSUER_GUIDANCE]", result["reasons"][0])
        self.assertEqual("20260915", result["latest_e1_date"])

    def test_filing_after_as_of_cannot_supersede(self):
        # H1 filed on 20260828, but the gate runs as of 20260815: no lookahead.
        pro = FakePro(forecast=[{"ann_date": "20260713", "end_date": "20260630", "type": "首亏",
                                 "net_profit_min": -18000.0, "net_profit_max": -15000.0}],
                      income=FILED_THROUGH_H1_2026)
        result = check_ticker(pro, "601127.SH", "20260815")
        self.assertEqual("RED_FLAG", result["verdict"], result)
        self.assertEqual("20260331", result["latest_filed_period"])

    def test_latest_period_outranks_later_announced_old_period(self):
        pro = FakePro(forecast=[
            {"ann_date": "20260713", "end_date": "20260930", "type": "预增",
             "net_profit_min": 1000.0, "net_profit_max": 2000.0},
            {"ann_date": "20260801", "end_date": "20251231", "type": "预减",
             "net_profit_min": 100.0, "net_profit_max": 200.0},
        ], income=FILED_THROUGH_Q1_2026)
        result = check_ticker(pro, "600001.SH", "20260805")
        self.assertEqual("PASS", result["verdict"], result)


class IncomeSemanticsTests(unittest.TestCase):
    def test_nan_latest_net_income_never_passes(self):
        income = FILED_THROUGH_H1_2026[:3] + _income(("20260828", "20260630", NAN))
        result = check_ticker(FakePro(income=income), "600001.SH", "20260924")
        self.assertEqual("DATA_BLOCKED", result["verdict"], result)
        self.assertEqual(["INCOME_VALUE_MISSING"], result["reason_codes"])
        self.assertTrue(result["reasons"][0].startswith("INCOME_VALUE_MISSING:"), result)
        # The null filing is still a filing: it is the latest E1 fact read.
        self.assertEqual("20260630", result["latest_filed_period"])

    def test_nan_predecessor_net_income_never_passes(self):
        income = _income(("20260328", "20251231", 4.0e8), ("20260428", "20260331", NAN),
                         ("20260828", "20260630", 2.5e8))
        result = check_ticker(FakePro(income=income), "600001.SH", "20260924")
        self.assertEqual("DATA_BLOCKED", result["verdict"], result)
        self.assertEqual(["INCOME_VALUE_MISSING"], result["reason_codes"])

    def test_non_adjacent_quarters_are_not_paired(self):
        # Q1-2026 missing: v0 would diff whatever rows sat at positions -1/-2/-3.
        income = _income(("20250828", "20250630", 2.0e8), ("20251028", "20250930", 3.0e8),
                         ("20260328", "20251231", 4.0e8), ("20260828", "20260630", -5.0e8))
        result = check_ticker(FakePro(income=income), "600001.SH", "20260924")
        self.assertEqual("DATA_BLOCKED", result["verdict"], result)
        self.assertEqual(["INSUFFICIENT_FILED_QUARTER_HISTORY"], result["reason_codes"])

    def test_negative_and_worsening_quarter_flags_on_adjacent_pair(self):
        income = _income(("20260328", "20251231", 4.0e8), ("20260428", "20260331", -0.7e8),
                         ("20260828", "20260630", -2.1e8))
        result = check_ticker(FakePro(income=income), "688512.SH", "20260924")
        self.assertEqual("RED_FLAG", result["verdict"], result)
        self.assertEqual(["NEGATIVE_AND_WORSENING_QUARTER_PROFIT"], result["reason_codes"])
        self.assertTrue(result["reasons"][0].startswith("最近季度归母-1.40亿为负且环比恶化(前季-0.70亿)"),
                        result)

    def test_zero_evidence_is_blocked(self):
        result = check_ticker(FakePro(), "999999.SZ", "20260924")
        self.assertEqual("DATA_BLOCKED", result["verdict"], result)
        self.assertEqual(["INSUFFICIENT_FILED_QUARTER_HISTORY"], result["reason_codes"])


class NullForecastTests(unittest.TestCase):
    def test_null_forecast_row_is_not_evidence(self):
        pro = FakePro(forecast=[{"ann_date": "20260915", "end_date": "20260930"}],
                      income=FILED_THROUGH_H1_2026)
        result = check_ticker(pro, "600001.SH", "20260924")
        self.assertEqual("DATA_BLOCKED", result["verdict"], result)
        self.assertEqual(["FORECAST_GUIDANCE_UNSCORABLE"], result["reason_codes"])


class SourceFailureTests(unittest.TestCase):
    def test_income_failure_blocks_even_negative_guidance(self):
        # Without filings the gate cannot tell whether FY2025 guidance is still live.
        pro = FakePro(forecast=[{"ann_date": "20260131", "end_date": "20251231", "type": "预减",
                                 "net_profit_min": 100.0, "net_profit_max": 200.0}],
                      fail={"income"})
        result = check_ticker(pro, "600001.SH", "20260924")
        self.assertEqual("DATA_BLOCKED", result["verdict"], result)
        self.assertEqual(["INCOME_SOURCE_UNAVAILABLE"], result["reason_codes"])
        self.assertIn("income:TUSHARE_READ_FAILED", result["reasons"][0])

    def test_express_failure_never_passes(self):
        pro = FakePro(income=FILED_THROUGH_H1_2026, fail={"express"})
        result = check_ticker(pro, "600001.SH", "20260924")
        self.assertEqual("DATA_BLOCKED", result["verdict"], result)
        self.assertEqual(["E1_SOURCE_PARTIAL"], result["reason_codes"])
        self.assertIn("express:TUSHARE_READ_FAILED", result["reasons"][0])

    def test_verified_red_flag_survives_partial_source(self):
        income = _income(("20260328", "20251231", 4.0e8), ("20260428", "20260331", -0.7e8),
                         ("20260828", "20260630", -2.1e8))
        result = check_ticker(FakePro(income=income, fail={"forecast"}), "600001.SH", "20260924")
        self.assertEqual("RED_FLAG", result["verdict"], result)

    def test_windows_are_relative_to_as_of_and_never_future(self):
        pro = FakePro(income=FILED_THROUGH_H1_2026)
        check_ticker(pro, "600001.SH", "20260924")
        self.assertEqual({"forecast", "express", "income"}, {api for api, _ in pro.calls})
        for _api, kwargs in pro.calls:
            self.assertEqual("20260924", kwargs["end_date"])
            self.assertLess(kwargs["start_date"], "20240901")
            self.assertIn("ann_date", kwargs["fields"])


class OutputContractTests(unittest.TestCase):
    CASES = {
        "clean": FakePro(income=FILED_THROUGH_H1_2026),
        "guidance": FakePro(forecast=[{"ann_date": "20260915", "end_date": "20260930",
                                       "type": "续亏", "net_profit_min": -2000.0,
                                       "net_profit_max": -1000.0}],
                            express=[{"ann_date": "20260920", "end_date": "20260930",
                                      "n_income": 1.0e7, "yoy_net_profit": 9.0e7}],
                            income=_income(("20260328", "20251231", 4.0e8),
                                           ("20260428", "20260331", -0.7e8),
                                           ("20260828", "20260630", -2.1e8))),
        "blocked": FakePro(income=FILED_THROUGH_H1_2026[:3]
                           + _income(("20260828", "20260630", NAN))),
    }

    def test_consumer_keys_and_verdict_vocabulary(self):
        for name, pro in self.CASES.items():
            result = check_ticker(pro, "600001.SH", "20260924")
            with self.subTest(case=name):
                for key in ("ts_code", "verdict", "reasons", "latest_e1_date", "checked_at"):
                    self.assertIn(key, result)
                self.assertIn(result["verdict"], {"PASS", "RED_FLAG", "DATA_BLOCKED"})
                self.assertIsInstance(result["reasons"], list)
                allowed = set(red_flag_gate.RED_FLAG_CODES) | set(red_flag_gate.BLOCK_CODES)
                self.assertTrue(set(result["reason_codes"]) <= allowed, result)

    def test_reason_text_prefixes_are_stable_for_downstream_parsers(self):
        result = check_ticker(self.CASES["guidance"], "600001.SH", "20260924")
        self.assertEqual("RED_FLAG", result["verdict"], result)
        self.assertEqual(3, len(result["reasons"]), result)
        self.assertEqual(
            ["最新预告", "最新快报净利同比", "最近季度归母"],
            [next((p for p in RED_PREFIXES if text.startswith(p)), None)
             for text in result["reasons"]],
        )
        # reason_codes are sorted (E1 convention); each text carries its own closed code.
        self.assertEqual(sorted(result["reason_codes"]),
                         sorted(text.rsplit("[code=", 1)[1].rstrip("]") for text in result["reasons"]))
        blocked = check_ticker(self.CASES["blocked"], "600001.SH", "20260924")
        self.assertFalse(any(text.startswith(RED_PREFIXES) for text in blocked["reasons"]))


class NoDriftWithE1LayerTests(unittest.TestCase):
    """U3 check_ticker and the batch E1 layer classify identical rows identically."""

    def test_u3_matches_batch_layer_row_for_row(self):
        as_of = "20260924"
        registry = e1._fixture_registry(as_of)
        income_null = FILED_THROUGH_H1_2026[:3] + _income(("20260828", "20260630", None))
        scenarios = {
            "600001.SH": {"forecast": [{"ann_date": "20260131", "end_date": "20251231",
                                        "type": "预减", "net_profit_min": 1.0,
                                        "net_profit_max": 2.0}],
                          "income": FILED_THROUGH_H1_2026},
            "600002.SH": {"forecast": [{"ann_date": "20260915", "end_date": "20260930",
                                        "type": "首亏", "net_profit_min": -2.0,
                                        "net_profit_max": -1.0}],
                          "income": FILED_THROUGH_H1_2026},
            "600003.SH": {"express": [{"ann_date": "20260920", "end_date": "20260930",
                                       "n_income": -5.58e7, "yoy_net_profit": -7.44e7}],
                          "income": FILED_THROUGH_H1_2026},
            "600004.SH": {"income": income_null},
            "600005.SH": {"income": _income(("20260328", "20251231", 4.0e8),
                                            ("20260428", "20260331", -0.7e8),
                                            ("20260828", "20260630", -2.1e8))},
        }
        batch_rows = {"forecast_vip": [], "express_vip": [], "income_vip": []}
        for code, rows in scenarios.items():
            for endpoint, key in (("forecast_vip", "forecast"), ("express_vip", "express"),
                                  ("income_vip", "income")):
                batch_rows[endpoint].extend({**row, "ts_code": code} for row in rows.get(key, []))
        periods = ["20260630", "20260331", "20251231", "20250930"]
        layer = e1.build_event_layer(
            registry, batch_rows, as_of=as_of, generated_at="2026-09-24T09:00:00+00:00",
            periods=periods,
            source_calls=[{"endpoint": ep, "period": p, "status": "OK", "rows": 0}
                          for ep in e1.ENDPOINTS for p in periods])
        e1.validate_event_layer(layer)
        by_code = {row["ts_code"]: row for row in layer["rows"]}
        expected = {"600001.SH": "NO_RED_FLAG_FOUND", "600002.SH": "RED_FLAG",
                    "600003.SH": "NO_RED_FLAG_FOUND", "600004.SH": "DATA_BLOCKED",
                    "600005.SH": "RED_FLAG"}
        for code, rows in scenarios.items():
            result = check_ticker(FakePro(rows.get("forecast", ()), rows.get("express", ()),
                                          rows.get("income", ())), code, as_of)
            with self.subTest(code=code):
                self.assertEqual(expected[code], by_code[code]["verdict"])
                self.assertEqual(red_flag_gate.VERDICT_MAP[by_code[code]["verdict"]],
                                 result["verdict"])
                self.assertEqual(by_code[code]["reason_codes"], result["reason_codes"])
                self.assertEqual(by_code[code]["evidence_coverage"], result["evidence_coverage"])
                self.assertEqual(by_code[code]["latest_e1_date"], result["latest_e1_date"])
        self.assertEqual(["INCOME_VALUE_MISSING"], by_code["600004.SH"]["reason_codes"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
