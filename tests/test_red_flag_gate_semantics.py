"""U3 red-flag gate v1 semantics — offline, zero network, zero token.

2026-09-25 re-review P1 #2/#3: the U3 gate (red_flag_gate.check_ticker, feeding
full_battery 基本面 -> funnel U3 -> u4_pre_decision) misread the express
``yoy_net_profit`` AMOUNT as a YoY percent, never retired guidance/express that
a filed statement had already superseded, and let NaN income or positional
quarter pairs PASS silently.  v1 delegates to e1_event_layer.classify_ticker,
the same rule set as the full-market E1 layer: identical rows classify
identically.  The fetch windows differ (U3: 800 days of announcements; batch:
the four report periods up to as_of), which the production-window tests pin.

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
INCOME_COLUMNS = ["ts_code", "ann_date", "end_date", "report_type", "n_income_attr_p", "update_flag"]
STRING_COLUMNS = ("ts_code", "ann_date", "end_date", "type", "report_type", "update_flag")
RED_PREFIXES = ("最新预告", "最新快报净利同比", "最近季度归母")
NAN = float("nan")


def _frame(rows, columns):
    # Mimic the provider: a DataFrame whose missing numerics are NaN, not None.
    return pd.DataFrame([{c: row.get(c, None if c in STRING_COLUMNS else NAN)
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


# Filed cumulative profit Q1-2025 → Q3-2025 only: FY2025, Q1-2026, H1-2026 never filed.
FILED_THROUGH_Q3_2025 = _income(
    ("20250428", "20250331", 1.0e8),
    ("20250828", "20250630", 2.0e8),
    ("20251028", "20250930", 3.0e8),
)
FY2025_PREINCREASE = {"ann_date": "20260125", "end_date": "20251231", "type": "预增",
                      "net_profit_min": 40000.0, "net_profit_max": 50000.0}
FY2025_FIRST_LOSS = {"ann_date": "20260125", "end_date": "20251231", "type": "首亏",
                     "net_profit_min": -18000.0, "net_profit_max": -15000.0}
Q1_2026_PREINCREASE = {"ann_date": "20260410", "end_date": "20260331", "type": "预增",
                       "net_profit_min": 10000.0, "net_profit_max": 12000.0}


class FreshnessTests(unittest.TestCase):
    """Review F1: a stopped filer must not PASS on year-old quarters."""

    def test_stale_filings_with_positive_guidance_are_blocked(self):
        pro = FakePro(forecast=[FY2025_PREINCREASE], income=FILED_THROUGH_Q3_2025)
        result = check_ticker(pro, "600001.SH", "20260924")
        self.assertEqual("DATA_BLOCKED", result["verdict"], result)
        self.assertEqual(["FILED_PERIOD_STALE"], result["reason_codes"])
        self.assertEqual("20250930", result["latest_filed_period"])
        self.assertEqual("20260630", result["latest_due_period"])
        self.assertTrue(result["reasons"][0].startswith("FILED_PERIOD_STALE:"), result)
        self.assertEqual("DATA_BLOCKED", result["evidence_coverage"]["income"])

    def test_stale_filings_without_guidance_are_blocked(self):
        result = check_ticker(FakePro(income=FILED_THROUGH_Q3_2025), "600001.SH", "20260924")
        self.assertEqual("DATA_BLOCKED", result["verdict"], result)
        self.assertEqual(["FILED_PERIOD_STALE"], result["reason_codes"])

    def test_deadline_boundary_is_strictly_after(self):
        # H1 is due by 08-31: on 08-31 a Q1 filer is still current; on 09-01 it is stale.
        on_deadline = check_ticker(FakePro(income=FILED_THROUGH_Q1_2026), "600001.SH", "20260831")
        self.assertEqual("PASS", on_deadline["verdict"], on_deadline)
        after = check_ticker(FakePro(income=FILED_THROUGH_Q1_2026), "600001.SH", "20260901")
        self.assertEqual("DATA_BLOCKED", after["verdict"], after)
        self.assertEqual(["FILED_PERIOD_STALE"], after["reason_codes"])

    def test_live_negative_guidance_still_flags_for_a_stale_filer(self):
        pro = FakePro(forecast=[{"ann_date": "20260715", "end_date": "20260630", "type": "首亏",
                                 "net_profit_min": -2000.0, "net_profit_max": -1000.0}],
                      income=FILED_THROUGH_Q3_2025)
        result = check_ticker(pro, "600001.SH", "20260924")
        self.assertEqual("RED_FLAG", result["verdict"], result)
        self.assertEqual(["NEGATIVE_ISSUER_GUIDANCE"], result["reason_codes"])


class ActivePeriodTests(unittest.TestCase):
    """Review F2: every unsuperseded period is judged; a later 预增 cannot mask a live 首亏."""

    def test_fy_first_loss_not_masked_by_later_q1_preincrease(self):
        pro = FakePro(forecast=[FY2025_FIRST_LOSS, Q1_2026_PREINCREASE],
                      income=FILED_THROUGH_Q3_2025)
        result = check_ticker(pro, "601127.SH", "20260415")
        self.assertEqual("RED_FLAG", result["verdict"], result)
        self.assertEqual(["NEGATIVE_ISSUER_GUIDANCE"], result["reason_codes"])
        self.assertEqual(1, len(result["reasons"]), result)
        self.assertTrue(result["reasons"][0].startswith("最新预告[首亏] 20260125 期末20251231"), result)
        self.assertEqual({"forecast": ["20260331", "20251231"], "express": []},
                         result["active_periods"])

    def test_fy_express_drop_not_masked_by_later_q1_express(self):
        pro = FakePro(express=[
            {"ann_date": "20260228", "end_date": "20251231", "n_income": 2.0e7, "yoy_net_profit": 1.0e8},
            {"ann_date": "20260412", "end_date": "20260331", "n_income": 3.0e7, "yoy_net_profit": 2.0e7},
        ], income=FILED_THROUGH_Q3_2025)
        result = check_ticker(pro, "600001.SH", "20260415")
        self.assertEqual("RED_FLAG", result["verdict"], result)
        self.assertEqual(["EXPRESS_NET_PROFIT_DROP_GT_30PCT"], result["reason_codes"])
        self.assertIn("期末20251231", result["reasons"][0])

    def test_restated_guidance_for_one_period_uses_latest_announcement(self):
        pro = FakePro(forecast=[
            {"ann_date": "20260125", "end_date": "20251231", "type": "首亏",
             "net_profit_min": -2000.0, "net_profit_max": -1000.0},
            {"ann_date": "20260228", "end_date": "20251231", "type": "扭亏",
             "net_profit_min": 1000.0, "net_profit_max": 2000.0},
        ], income=FILED_THROUGH_Q3_2025)
        result = check_ticker(pro, "600001.SH", "20260415")
        self.assertEqual("PASS", result["verdict"], result)


class SamePeriodSupersessionTests(unittest.TestCase):
    """Review RF-TEST-2: a filing for the SAME period retires guidance and express."""

    ROWS = {
        "forecast": [{"ann_date": "20260713", "end_date": "20260630", "type": "首亏",
                      "net_profit_min": -18000.0, "net_profit_max": -15000.0}],
        "express": [{"ann_date": "20260720", "end_date": "20260630",
                     "n_income": 2.0e7, "yoy_net_profit": 1.0e8}],
        "income": FILED_THROUGH_H1_2026,  # H1-2026 filed 20260828
    }

    def _run(self, as_of):
        return check_ticker(FakePro(self.ROWS["forecast"], self.ROWS["express"],
                                    self.ROWS["income"]), "601127.SH", as_of)

    def test_same_period_filing_supersedes_guidance_and_express(self):
        result = self._run("20260924")
        self.assertEqual("PASS", result["verdict"], result)
        self.assertEqual("SUPERSEDED", result["evidence_coverage"]["forecast"])
        self.assertEqual("SUPERSEDED", result["evidence_coverage"]["express"])
        self.assertEqual("20260630", result["latest_filed_period"])

    def test_before_the_same_period_filing_both_still_flag(self):
        result = self._run("20260827")
        self.assertEqual("RED_FLAG", result["verdict"], result)
        self.assertEqual(["EXPRESS_NET_PROFIT_DROP_GT_30PCT", "NEGATIVE_ISSUER_GUIDANCE"],
                         result["reason_codes"])
        self.assertEqual("PRESENT", result["evidence_coverage"]["forecast"])
        self.assertEqual("PRESENT", result["evidence_coverage"]["express"])


class ExpressSignTests(unittest.TestCase):
    """Review RF-TEST-3: a sharply narrowing loss is an improvement (+73%), not -73%."""

    def test_narrowing_loss_is_not_a_drop(self):
        pro = FakePro(express=[{"ann_date": "20260720", "end_date": "20260630",
                                "n_income": -20_000_000.0, "yoy_net_profit": -74_400_964.91}],
                      income=FILED_THROUGH_Q1_2026)
        result = check_ticker(pro, "920038.BJ", "20260725")
        self.assertEqual("PASS", result["verdict"], result)
        self.assertEqual("PRESENT", result["evidence_coverage"]["express"])

    def test_widening_loss_is_a_drop(self):
        pro = FakePro(express=[{"ann_date": "20260720", "end_date": "20260630",
                                "n_income": -1.5e8, "yoy_net_profit": -7.44e7}],
                      income=FILED_THROUGH_Q1_2026)
        result = check_ticker(pro, "920038.BJ", "20260725")
        self.assertEqual("RED_FLAG", result["verdict"], result)
        self.assertTrue(result["reasons"][0].startswith("最新快报净利同比-101.6%"), result)


class FilingSelectionTests(unittest.TestCase):
    """Review RF-TEST-4 / F5: same-period filing choice never depends on arrival order."""

    BASE = _income(("20260328", "20251231", 4.0e8), ("20260428", "20260331", 1.0e8))

    def _check(self, h1_rows):
        for order in (h1_rows, list(reversed(h1_rows))):
            yield check_ticker(FakePro(income=self.BASE + order), "600001.SH", "20260924")

    def test_valued_row_beats_null_on_same_announcement_date(self):
        rows = [{"ann_date": "20260828", "end_date": "20260630", "report_type": "1",
                 "n_income_attr_p": NAN},
                {"ann_date": "20260828", "end_date": "20260630", "report_type": "1",
                 "n_income_attr_p": 2.5e8}]
        for result in self._check(rows):
            self.assertEqual("PASS", result["verdict"], result)
            self.assertEqual("COMPLETE", result["evidence_coverage"]["income"])

    def test_later_restatement_wins(self):
        rows = [{"ann_date": "20260828", "end_date": "20260630", "report_type": "1",
                 "n_income_attr_p": 2.5e8},
                {"ann_date": "20260915", "end_date": "20260630", "report_type": "1",
                 "n_income_attr_p": -1.0e8}]
        for result in self._check(rows):
            self.assertEqual("RED_FLAG", result["verdict"], result)
            self.assertEqual(["NEGATIVE_AND_WORSENING_QUARTER_PROFIT"], result["reason_codes"])
            self.assertEqual("20260915", result["latest_e1_date"])

    def test_update_flag_breaks_a_valued_tie(self):
        rows = [{"ann_date": "20260828", "end_date": "20260630", "report_type": "1",
                 "n_income_attr_p": 2.5e8, "update_flag": "0"},
                {"ann_date": "20260828", "end_date": "20260630", "report_type": "1",
                 "n_income_attr_p": -1.0e8, "update_flag": "1"}]
        for result in self._check(rows):
            self.assertEqual("RED_FLAG", result["verdict"], result)

    def test_foreign_ticker_rows_are_ignored(self):
        foreign_income = _income(("20260428", "20260331", -0.7e8), ("20260828", "20260630", -2.1e8))
        for row in foreign_income:
            row["ts_code"] = "000001.SZ"
        pro = FakePro(forecast=[{"ts_code": "000001.SZ", "ann_date": "20260915",
                                 "end_date": "20260930", "type": "首亏",
                                 "net_profit_min": -2.0, "net_profit_max": -1.0}],
                      income=FILED_THROUGH_H1_2026 + foreign_income)
        result = check_ticker(pro, "600001.SH", "20260924")
        self.assertEqual("PASS", result["verdict"], result)
        self.assertEqual("EMPTY_VALID", result["evidence_coverage"]["forecast"])

    def test_gate_requests_the_batch_field_sets(self):
        pro = FakePro(income=FILED_THROUGH_H1_2026)
        check_ticker(pro, "600001.SH", "20260924")
        fields = {api: kwargs["fields"] for api, kwargs in pro.calls}
        self.assertEqual({"forecast": e1.FORECAST_FIELDS, "express": e1.EXPRESS_FIELDS,
                          "income": e1.INCOME_FIELDS}, fields)
        self.assertIn("update_flag", fields["income"])


class PartialSourceTextTests(unittest.TestCase):
    def test_forecast_failure_never_passes(self):
        pro = FakePro(income=FILED_THROUGH_H1_2026, fail={"forecast"})
        result = check_ticker(pro, "600001.SH", "20260924")
        self.assertEqual("DATA_BLOCKED", result["verdict"], result)
        self.assertEqual(["E1_SOURCE_PARTIAL"], result["reason_codes"])
        self.assertIn("forecast:TUSHARE_READ_FAILED", result["reasons"][0])

    def test_red_flag_under_partial_source_names_the_failed_source(self):
        income = _income(("20260328", "20251231", 4.0e8), ("20260428", "20260331", -0.7e8),
                         ("20260828", "20260630", -2.1e8))
        result = check_ticker(FakePro(income=income, fail={"express"}), "600001.SH", "20260924")
        self.assertEqual("RED_FLAG", result["verdict"], result)
        self.assertEqual(["NEGATIVE_AND_WORSENING_QUARTER_PROFIT"], result["reason_codes"])
        self.assertTrue(result["reasons"][0].startswith("最近季度归母"), result)
        note = result["reasons"][-1]
        self.assertTrue(note.startswith("E1_SOURCE_PARTIAL:express:TUSHARE_READ_FAILED"), result)
        self.assertFalse(note.startswith(RED_PREFIXES))

    def test_income_failure_keeps_negative_guidance_visible_within_battery_truncation(self):
        pro = FakePro(forecast=[FY2025_FIRST_LOSS, Q1_2026_PREINCREASE], fail={"income"})
        result = check_ticker(pro, "601127.SH", "20260415")
        self.assertEqual("DATA_BLOCKED", result["verdict"], result)
        self.assertEqual(["INCOME_SOURCE_UNAVAILABLE"], result["reason_codes"])
        # full_battery keeps only the first 60 chars of the joined reasons.
        battery_err = ";".join(result["reasons"])[:60]
        self.assertIn("未确认负面预告[首亏]期末20251231", battery_err)
        self.assertFalse(result["reasons"][0].startswith(RED_PREFIXES))
        self.assertEqual([{"kind": "ISSUER_GUIDANCE", "period": "20251231", "ann_date": "20260125",
                           "type": "首亏"}], result["unconfirmed_negative_evidence"])


class RuleRevisionTests(unittest.TestCase):
    def test_rule_identity_distinguishes_the_revision(self):
        self.assertNotEqual(e1.RULE_VERSION, e1.RULE_REVISION)
        self.assertTrue(e1.RULE_REVISION.startswith(e1.RULE_VERSION + "+"))
        self.assertIn(e1.RULE_REVISION, red_flag_gate.RULE_VERSION)
        result = check_ticker(FakePro(income=FILED_THROUGH_H1_2026), "600001.SH", "20260924")
        self.assertEqual(red_flag_gate.RULE_VERSION, result["rule_version"])


class ProductionWindowTests(unittest.TestCase):
    """Review F1 / RF-INT-1: U3 and the batch layer side by side with their REAL fetch windows.

    U3 reads every row announced in its look-back window; the batch layer reads only
    the four report periods up to as_of (``e1._recent_periods``).  Both must agree
    on the verdict and reason codes wherever the rule, not the window, decides.
    """

    SCENARIOS = {
        # as_of 20260924
        "600001.SH": ("stale filer with positive FY guidance",
                      {"forecast": [FY2025_PREINCREASE], "income": FILED_THROUGH_Q3_2025},
                      "DATA_BLOCKED", ["FILED_PERIOD_STALE"]),
        "600002.SH": ("stale filer, no guidance",
                      {"income": FILED_THROUGH_Q3_2025},
                      "DATA_BLOCKED", ["FILED_PERIOD_STALE"]),
        "600003.SH": ("current filer with superseded FY 预减",
                      {"forecast": [{"ann_date": "20260131", "end_date": "20251231",
                                     "type": "预减", "net_profit_min": 1.0,
                                     "net_profit_max": 2.0}],
                       "income": FILED_THROUGH_Q3_2025[:2] + FILED_THROUGH_H1_2026},
                      "NO_RED_FLAG_FOUND", []),
        "600004.SH": ("same-period H1 filing retires H1 首亏 guidance",
                      {"forecast": [{"ann_date": "20260713", "end_date": "20260630",
                                     "type": "首亏", "net_profit_min": -2.0,
                                     "net_profit_max": -1.0}],
                       "income": FILED_THROUGH_H1_2026},
                      "NO_RED_FLAG_FOUND", []),
        "600005.SH": ("current filer, negative and worsening quarter",
                      {"income": _income(("20251028", "20250930", 3.0e8),
                                         ("20260328", "20251231", 4.0e8),
                                         ("20260428", "20260331", -0.7e8),
                                         ("20260828", "20260630", -2.1e8))},
                      "RED_FLAG", ["NEGATIVE_AND_WORSENING_QUARTER_PROFIT"]),
    }

    @staticmethod
    def _batch_layer(scenarios, as_of):
        periods = e1._recent_periods(as_of, 4)
        batch = {"forecast_vip": [], "express_vip": [], "income_vip": []}
        for code, (_label, rows, _v, _c) in scenarios.items():
            for endpoint, key in (("forecast_vip", "forecast"), ("express_vip", "express"),
                                  ("income_vip", "income")):
                # The batch endpoints are period-keyed: only these four end_dates exist.
                batch[endpoint].extend({**row, "ts_code": code} for row in rows.get(key, [])
                                       if row["end_date"] in periods)
        layer = e1.build_event_layer(
            e1._fixture_registry(as_of), batch, as_of=as_of,
            generated_at="2026-09-24T09:00:00+00:00", periods=periods,
            source_calls=[{"endpoint": ep, "period": p, "status": "OK", "rows": 0}
                          for ep in e1.ENDPOINTS for p in periods])
        e1.validate_event_layer(layer)
        return {row["ts_code"]: row for row in layer["rows"]}

    def test_u3_and_batch_agree_under_production_windows(self):
        as_of = "20260924"
        by_code = self._batch_layer(self.SCENARIOS, as_of)
        for code, (label, rows, verdict, codes) in self.SCENARIOS.items():
            result = check_ticker(FakePro(rows.get("forecast", ()), rows.get("express", ()),
                                          rows.get("income", ())), code, as_of)
            with self.subTest(case=label):
                self.assertEqual(verdict, by_code[code]["verdict"], by_code[code])
                self.assertEqual(codes, by_code[code]["reason_codes"])
                self.assertEqual(red_flag_gate.VERDICT_MAP[verdict], result["verdict"], result)
                self.assertEqual(codes, result["reason_codes"])
                for key in ("forecast", "express", "income"):
                    self.assertEqual(by_code[code]["evidence_coverage"][key],
                                     result["evidence_coverage"][key], key)

    def test_documented_window_difference_future_period_guidance(self):
        # A Q3 预告 announced 20260915 for period 20260930 (> as_of 20260924): the
        # per-ticker U3 fetch sees it; the period-keyed batch fetch never requests
        # 20260930.  Pinned here so the difference stays deliberate, not silent.
        scenario = {"600001.SH": ("future-period guidance",
                                  {"forecast": [{"ann_date": "20260915", "end_date": "20260930",
                                                 "type": "首亏", "net_profit_min": -2.0,
                                                 "net_profit_max": -1.0}],
                                   "income": FILED_THROUGH_H1_2026}, None, None)}
        batch = self._batch_layer(scenario, "20260924")["600001.SH"]
        u3 = check_ticker(FakePro(scenario["600001.SH"][1]["forecast"], (),
                                  FILED_THROUGH_H1_2026), "600001.SH", "20260924")
        self.assertEqual("NO_RED_FLAG_FOUND", batch["verdict"])
        self.assertEqual("RED_FLAG", u3["verdict"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
