#!/usr/bin/env python3
"""Missing rotation breadth and NAV gaps are recorded as missing, never as zero.

A. Rotation: a failed Tushare call is not an empty answer; a failed or empty
   limit_list_d day is DATA_BLOCKED (None), not a zero-limit-up day; a missing
   net_amount drops that sector-day; Q2 and the precursor calibration exclude
   and count blocked days without turning the nightly step PARTIAL.
B. NAV: daily_return only for one-session steps; multi-session steps keep a
   period_return with basis_date / sessions_covered / calendar_source; the
   portfolio contract is PARTIAL and lists missing sessions.

Offline, synthetic fixtures only.
不是买卖指令；研究信号，human executes。
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ET = ROOT / "experiments" / "execution_tracker"
sys.path.insert(0, str(ET))

import court_wakeup  # noqa: E402
import export_contracts  # noqa: E402
import lead_precursor  # noqa: E402
import model_paper_fund  # noqa: E402
import rotation_panel  # noqa: E402
import rotation_validation as rv  # noqa: E402
import run_nightly  # noqa: E402
import session_calendar  # noqa: E402
import tushare_rows  # noqa: E402

TOKEN = "fixture-token-abcdef"


class _Resp(io.BytesIO):
    pass


def _opener(payloads):
    calls = []

    def opener(req, timeout=None):
        calls.append(req)
        item = payloads[min(len(calls) - 1, len(payloads) - 1)]
        if isinstance(item, Exception):
            raise item
        return _Resp(json.dumps(item).encode())
    opener.calls = calls
    return opener


def _ok(fields, items):
    return {"code": 0, "data": {"fields": fields, "items": items}}


class FetchRowsTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"AR_OFFLINE": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def fetch(self, payloads, **kw):
        return tushare_rows.fetch_rows("limit_list_d", TOKEN, opener=_opener(payloads),
                                       sleep=lambda *_: None, **kw)

    def test_failure_is_none_with_reason_not_empty_list(self):
        rows, err = self.fetch([OSError("boom")])
        self.assertIsNone(rows)
        self.assertEqual(err, "TUSHARE_EXCEPTION:OSError")

    def test_code_zero_empty_is_an_empty_answer(self):
        rows, err = self.fetch([_ok(["industry", "limit"], [])])
        self.assertEqual(rows, [])
        self.assertIsNone(err)

    def test_provider_error_code_is_reported_and_token_scrubbed(self):
        rows, err = self.fetch([{"code": 40203, "msg": f"quota for {TOKEN} exceeded"}])
        self.assertIsNone(rows)
        self.assertTrue(err.startswith("TUSHARE_CODE_40203:"))
        self.assertNotIn(TOKEN, err)

    def test_retry_recovers_after_transient_failure(self):
        rows, err = self.fetch([OSError("x"), _ok(["industry", "limit"], [["电力", "U"]])])
        self.assertEqual(rows, [{"industry": "电力", "limit": "U"}])
        self.assertIsNone(err)

    def test_malformed_rows_are_a_failure(self):
        rows, err = self.fetch([_ok(["a", "b"], [["only-one"]])])
        self.assertIsNone(rows)
        self.assertEqual(err, "TUSHARE_DATA_SHAPE")

    def test_offline_refuses_without_opening_a_socket(self):
        opener = _opener([_ok(["a"], [[1]])])
        with mock.patch.dict(os.environ, {"AR_OFFLINE": "1"}):
            rows, err = tushare_rows.fetch_rows("daily", TOKEN, opener=opener)
        self.assertEqual((rows, err), (None, "TUSHARE_OFFLINE"))
        self.assertEqual(opener.calls, [])

    def test_optional_float_keeps_missing_missing(self):
        self.assertIsNone(tushare_rows.optional_float(None))
        self.assertIsNone(tushare_rows.optional_float(""))
        self.assertIsNone(tushare_rows.optional_float(float("nan")))
        self.assertEqual(tushare_rows.optional_float("0"), 0.0)


def _flow_rows(names, net=1.0):
    return [{"name": n, "net_amount": net, "pct_change": 0.5} for n in names]


class FakeTushare:
    """Scripted provider: {(api, trade_date): (rows, err)}."""

    def __init__(self, cal_days, script):
        self.cal_days = cal_days
        self.script = script

    def __call__(self, name, token, **params):
        if name == "trade_cal":
            return [{"cal_date": d} for d in self.cal_days], None
        return self.script.get((name, params.get("trade_date")), (None, "UNSCRIPTED"))


def _hist(days, limit=None):
    flows = {d: {"电力": [1.0, 0.5], "半导体": [-1.0, -0.5]} for d in days}
    return {"days": list(days), "flows": flows,
            "limit_up_by_industry": dict(limit or {d: {"电力": 3} for d in days})}


class RotationAppendTests(unittest.TestCase):
    def test_limit_counts_never_store_zero(self):
        self.assertEqual(rv.limit_counts_from_rows(None, "TUSHARE_EXCEPTION:OSError"),
                         (None, "TUSHARE_EXCEPTION:OSError"))
        cnt, why = rv.limit_counts_from_rows([], None)
        self.assertIsNone(cnt)
        self.assertEqual(why, "EMPTY_LIMIT_LIST_IMPLAUSIBLE_FOR_SETTLED_DAY")
        cnt, why = rv.limit_counts_from_rows(
            [{"industry": "电力", "limit": "U"}, {"industry": "电力", "limit": "D"}], None)
        self.assertEqual((cnt, why), ({"电力": 1}, None))

    def test_historical_limit_failure_appends_flows_but_marks_limit_blocked(self):
        hist = _hist(["20260911"])
        api = FakeTushare(["20260911", "20260914", "20260915"], {
            ("moneyflow_ind_dc", "20260914"): (_flow_rows(["电力", "半导体"]), None),
            ("limit_list_d", "20260914"): (None, "TUSHARE_EXCEPTION:URLError"),
            ("moneyflow_ind_dc", "20260915"): (_flow_rows(["电力", "半导体"]), None),
            ("limit_list_d", "20260915"): ([{"industry": "电力", "limit": "U"}], None),
        })
        out, report = rv.append_days(hist, TOKEN, "20260915", api=api)
        self.assertEqual(out["days"], ["20260911", "20260914", "20260915"])
        self.assertIsNone(out["limit_up_by_industry"]["20260914"])
        self.assertNotEqual(out["limit_up_by_industry"]["20260914"], {})
        self.assertEqual(out[rv.LIMIT_BLOCKED_KEY], {"20260914": "TUSHARE_EXCEPTION:URLError"})
        self.assertEqual(report["limit_blocked_appended"], ["20260914"])
        self.assertIn("电力", out["flows"]["20260914"])

    def test_target_day_limit_failure_or_empty_skips_the_day(self):
        for rows, err in ((None, "TUSHARE_CODE_-1:busy"), ([], None)):
            with self.subTest(err=err):
                hist = _hist(["20260911"])
                api = FakeTushare(["20260911", "20260914"], {
                    ("moneyflow_ind_dc", "20260914"): (_flow_rows(["电力"]), None),
                    ("limit_list_d", "20260914"): (rows, err),
                })
                out, report = rv.append_days(hist, TOKEN, "20260914", api=api)
                self.assertEqual(out["days"], ["20260911"])
                self.assertNotIn("20260914", out["flows"])
                self.assertEqual([s["date"] for s in report["skipped"]], ["20260914"])

    def test_target_day_flow_failure_skips_but_history_flow_failure_aborts(self):
        hist = _hist(["20260911"])
        api = FakeTushare(["20260911", "20260914"], {
            ("moneyflow_ind_dc", "20260914"): (None, "TUSHARE_EXCEPTION:URLError"),
        })
        out, report = rv.append_days(hist, TOKEN, "20260914", api=api)
        self.assertEqual(out["days"], ["20260911"])
        api = FakeTushare(["20260911", "20260914", "20260915"], {
            ("moneyflow_ind_dc", "20260914"): (None, "TUSHARE_EXCEPTION:URLError"),
        })
        out, why = rv.append_days(_hist(["20260911"]), TOKEN, "20260915", api=api)
        self.assertIsNone(out)
        self.assertIn("20260914", why)

    def test_trade_cal_failure_is_blocked(self):
        def api(name, token, **params):
            return None, "TUSHARE_EXCEPTION:URLError"
        out, why = rv.append_days(_hist(["20260911"]), TOKEN, "20260914", api=api)
        self.assertIsNone(out)
        self.assertIn("trade_cal", why)

    def test_missing_net_amount_drops_the_sector_day(self):
        rows = _flow_rows(["电力", "半导体"]) + [
            {"name": "缺值板块", "net_amount": None, "pct_change": 1.0}]
        flows, dropped = rv.flows_from_rows(rows)
        self.assertNotIn("缺值板块", flows)
        self.assertEqual(dropped, 1)
        hist = _hist(["20260911"])
        api = FakeTushare(["20260911", "20260914"], {
            ("moneyflow_ind_dc", "20260914"): (rows, None),
            ("limit_list_d", "20260914"): ([{"industry": "电力", "limit": "U"}], None),
        })
        out, _ = rv.append_days(hist, TOKEN, "20260914", api=api)
        self.assertNotIn("缺值板块", out["flows"]["20260914"])
        self.assertEqual(out[rv.FLOW_MISSING_KEY], {"20260914": 1})

    def test_roll_keeps_blocked_reading_as_none(self):
        days = [f"2026090{i}" for i in range(1, 4)]
        hist = _hist(days, limit={days[0]: {"电力": 2}, days[1]: {"电力": 2}})
        hist[rv.LIMIT_BLOCKED_KEY] = {days[0]: "OLD"}
        api = FakeTushare(days, {})
        out, _ = rv.append_days(hist, TOKEN, days[-1], api=api, window=2)
        self.assertEqual(out["days"], days[1:])
        self.assertIsNone(out["limit_up_by_industry"][days[2]])
        self.assertEqual(out[rv.LIMIT_BLOCKED_KEY], {})


def _panel_hist(n_days=30, blocked=()):
    import random
    rng = random.Random(5)
    days = [f"d{i:02d}" for i in range(n_days)]
    flows = {}
    for d in days:
        row = {f"N{k}": [rng.uniform(-1, 1), rng.gauss(0, 1)] for k in range(18)}
        row["P"] = [2.0, 1.5 + 0.3 * rng.random()]
        flows[d] = row
    limit = {d: ({} if d in blocked else {"P": 3}) for d in days}
    return {"days": days, "flows": flows, "limit_up_by_industry": limit}


class RotationValidationTests(unittest.TestCase):
    def test_q2_excludes_blocked_days_instead_of_counting_narrow(self):
        clean = _panel_hist()
        sectors, exc, hot = rv.build_states(clean)
        base = rv.run_q2(clean, sectors, exc, hot)
        blocked_days = [f"d{i:02d}" for i in range(10, 20)]
        dirty = _panel_hist(blocked=blocked_days)
        sectors, exc, hot = rv.build_states(dirty)
        q2 = rv.run_q2(dirty, sectors, exc, hot)
        self.assertEqual(q2["limit_reading"]["blocked_days"], blocked_days)
        self.assertEqual(q2["limit_reading"]["blocked_days_n"], 10)
        self.assertGreater(q2["limit_reading"]["excluded_hot_obs_n"], 0)
        self.assertLessEqual(q2["narrow_n"], base["narrow_n"])
        self.assertEqual(q2["broad_n"] + q2["narrow_n"] + q2["limit_reading"]["excluded_hot_obs_n"],
                         base["broad_n"] + base["narrow_n"])

    def test_marked_and_legacy_empty_and_missing_readings_are_all_blocked(self):
        hist = _panel_hist(n_days=6)
        hist["limit_up_by_industry"]["d01"] = {}
        hist["limit_up_by_industry"]["d02"] = None
        del hist["limit_up_by_industry"]["d03"]
        hist[rv.LIMIT_BLOCKED_KEY] = {"d04": "TUSHARE_EXCEPTION:URLError"}
        self.assertEqual(rv.limit_blocked_days(hist), ["d01", "d02", "d03", "d04"])
        self.assertEqual(rv.limit_reading(hist, "d05"), {"P": 3})

    def test_blocked_days_are_counted_without_making_the_step_partial(self):
        hist = _panel_hist(blocked=["d05", "d06"])
        v = rv.validate(hist)
        self.assertEqual(v["data_coverage"]["limit_up_blocked_days_n"], 2)
        self.assertEqual(v["data_coverage"]["limit_up_valid_days_n"], 28)
        # Q3 chain names do not exist in the synthetic panel; judge only the new parts.
        scanned = {k: val for k, val in v.items() if not k.startswith(("Q3", "C2"))}
        self.assertEqual(run_nightly._artifact_status_scan("rotation_validation", scanned),
                         ("OK", ""))


class LeadPrecursorTests(unittest.TestCase):
    def _hist(self):
        days = [f"d{i}" for i in range(1, 9)]
        flows = {d: {"电子": [-10 - i, -1.0 - i * 0.1], "计算机": [-1, -1],
                     "光通信模块": [-1, -1]} for i, d in enumerate(days)}
        flows["d6"] = {"电子": [-11, -3], "计算机": [4, 1.2], "光通信模块": [5, 2.0],
                       "印制电路板": [3, 1.0]}
        return {"days": days, "flows": flows,
                "limit_up_by_industry": {d: {"电力": 5} for d in days}}

    def test_blocked_limit_day_cannot_light_or_score_defense_crowding(self):
        hist = self._hist()
        lit = lead_precursor.detect_day(hist, 5)
        self.assertIn("defense_crowding", [x["key"] for x in lit["lights"]])
        hist["limit_up_by_industry"]["d6"] = {}
        read = lead_precursor.detect_day(hist, 5)
        self.assertNotIn("defense_crowding", [x["key"] for x in read["lights"]])
        self.assertIs(read["limit_reading_available"], False)
        self.assertEqual(read["unevaluable_lights"], ["defense_crowding"])
        self.assertIsNone(read["features"]["defense_limit_up_count"])

    def test_blocked_limit_days_are_excluded_from_calibration_and_counted(self):
        hist = self._hist()
        hist["limit_up_by_industry"]["d6"] = {}
        hist["limit_up_data_blocked"] = {"d7": "TUSHARE_EXCEPTION:URLError"}
        report = lead_precursor.evaluate_history(hist, include_latest_nowcast=False)
        excl = report["calibration_exclusions"]
        self.assertEqual(excl["limit_reading_blocked_days"], ["d6", "d7"])
        self.assertNotIn("d6", [r["date"] for r in report["scored_examples"]])
        self.assertNotIn("d7", [r["date"] for r in report["scored_examples"]])


class PanelAndWakeupTests(unittest.TestCase):
    def test_rotation_panel_drops_sector_with_missing_value(self):
        days = ["d1", "d2", "d3", "d4", "d5"]
        flows = {"完整": {d: (1.0, 1.0) for d in days},
                 "缺值": {d: (1.0, 1.0) for d in days}}
        flows["缺值"]["d3"] = (None, 1.0)
        panel = rotation_panel.build_panel(flows, days)
        self.assertEqual([r["sector"] for r in panel["inflow_cont"]], ["完整"])

    def test_court_wakeup_failed_price_call_is_data_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            court = Path(tmp, "court.json")
            court.write_text(json.dumps([{"ticker": "600001.SH", "name": "Fixture",
                                          "sector_key": "x", "checkpoints": []}]))
            with mock.patch.object(court_wakeup, "COURT", str(court)), \
                    mock.patch.object(court_wakeup, "PANEL", str(Path(tmp, "p.json"))), \
                    mock.patch.object(court_wakeup, "OUT", str(Path(tmp, "out.json"))), \
                    mock.patch.object(court_wakeup, "_api",
                                      return_value=(None, "TUSHARE_EXCEPTION:URLError")), \
                    mock.patch.object(court_wakeup.time, "sleep"), \
                    mock.patch.dict(os.environ, {"AR_TARGET_TRADE_DATE": "20260914",
                                                 "AR_RUN_ID": "fixture"}), \
                    mock.patch("sys.stdout", new=io.StringIO()):
                result = court_wakeup.run(TOKEN, "20260914")
        self.assertEqual([b["ticker"] for b in result["data_blocked"]], ["600001.SH"])


class SessionCalendarTests(unittest.TestCase):
    def test_static_2026_calendar_skips_holidays_not_sessions(self):
        cal = session_calendar.SessionCalendar([])
        span = cal.sessions_between("20260924", "20260928")      # 0925 中秋
        self.assertEqual(span["sessions"], ["20260928"])
        self.assertEqual(span["calendar_source"], session_calendar.SOURCE_STATIC)
        self.assertTrue(span["calendar_caveat"])
        span = cal.sessions_between("20260828", "20260908")
        self.assertEqual(span["sessions"], ["20260831", "20260901", "20260902", "20260903",
                                            "20260904", "20260907", "20260908"])
        self.assertEqual(cal.sessions_between("20260930", "20261008")["sessions"],
                         ["20261008"])

    def test_trade_cal_days_are_preferred_when_they_span_the_range(self):
        observed = ["20260911", "20260914", "20260915", "20260916"]
        span = session_calendar.SessionCalendar(observed).sessions_between("20260911", "20260916")
        self.assertEqual(span["calendar_source"], session_calendar.SOURCE_ROTATION)
        self.assertEqual(span["sessions"], ["20260914", "20260915", "20260916"])

    def test_disagreeing_sources_make_the_range_unavailable(self):
        observed = ["20260911", "20260915"]                       # claims 0914 closed
        span = session_calendar.SessionCalendar(observed).sessions_between("20260911", "20260915")
        self.assertIsNone(span["sessions"])
        self.assertEqual(span["reason"], "CALENDAR_SOURCES_DISAGREE")

    def test_no_offline_calendar_or_non_session_end_is_unavailable(self):
        cal = session_calendar.SessionCalendar([])
        self.assertEqual(cal.sessions_between("20261231", "20270104")["reason"],
                         "NO_OFFLINE_CALENDAR_FOR_RANGE")
        self.assertEqual(cal.sessions_between("20260924", "20260925")["reason"],
                         "END_DATE_IS_NOT_A_SESSION")
        self.assertEqual(cal.sessions_between("20260915", "20260914")["reason"],
                         "NON_INCREASING_RANGE")


def _fund(cash=1_000_000.0):
    return {"initial_capital": 1_000_000.0, "cash": cash, "paper_only": True}


STATIC = session_calendar.SessionCalendar([])


class NavGapTests(unittest.TestCase):
    def test_one_session_step_keeps_daily_return(self):
        history = [{"date": "20260827", "nav": 1_000_000.0}]
        rec = model_paper_fund.update_nav(_fund(1_010_000.0), [], history, "20260828",
                                          calendar=STATIC)
        self.assertEqual(rec["daily_return"], 0.01)
        self.assertEqual(rec["period_return"], 0.01)
        self.assertEqual(rec["sessions_covered"], 1)
        self.assertEqual(rec["gap_sessions"], [])
        self.assertEqual(rec["basis_date"], "20260827")
        self.assertEqual(rec["calendar_source"], session_calendar.SOURCE_STATIC)

    def test_multi_session_gap_is_period_return_not_daily(self):
        history = [{"date": "20260828", "nav": 1_018_464.0}]
        rec = model_paper_fund.update_nav(_fund(1_025_380.0), [], history, "20260908",
                                          calendar=STATIC)
        self.assertIsNone(rec["daily_return"])
        self.assertEqual(rec["period_return"], 0.00679)
        self.assertEqual(rec["sessions_covered"], 7)
        self.assertEqual(rec["gap_sessions"], ["20260831", "20260901", "20260902",
                                               "20260903", "20260904", "20260907"])

    def test_blocked_row_between_and_unprovable_calendar_are_not_daily(self):
        history = [{"date": "20260904", "nav": 1_000_000.0},
                   {"date": "20260907", "nav": None, "status": "DATA_BLOCKED"}]
        rec = model_paper_fund.update_nav(_fund(1_008_000.0), [], history, "20260908",
                                          calendar=STATIC)
        self.assertIsNone(rec["daily_return"])
        self.assertEqual(rec["sessions_covered"], 2)
        history = [{"date": "20261231", "nav": 1_000_000.0}]
        rec = model_paper_fund.update_nav(_fund(1_001_000.0), [], history, "20270104",
                                          calendar=STATIC)
        self.assertIsNone(rec["daily_return"])
        self.assertIsNone(rec["sessions_covered"])
        self.assertEqual(rec["calendar_source"], session_calendar.SOURCE_UNAVAILABLE)

    def test_inception_row_has_no_daily_return(self):
        rec = model_paper_fund.update_nav(_fund(), [], [], "20260706", calendar=STATIC)
        self.assertIsNone(rec["daily_return"])
        self.assertEqual(rec["basis_date"], "INCEPTION")
        self.assertEqual(rec["period_return"], 0.0)

    def test_performance_withholds_drawdown_over_gaps(self):
        history = [{"date": "20260827", "nav": 1_000_000.0}]
        model_paper_fund.update_nav(_fund(990_000.0), [], history, "20260828", calendar=STATIC)
        clean = model_paper_fund.compute_performance(_fund(), [], history)
        self.assertEqual(clean["max_drawdown"], -0.01)
        self.assertNotIn("nav_gap_row_dates", clean)
        model_paper_fund.update_nav(_fund(1_020_000.0), [], history, "20260908", calendar=STATIC)
        gapped = model_paper_fund.compute_performance(_fund(), [], history)
        self.assertIsNone(gapped["max_drawdown"])
        self.assertEqual(gapped["max_drawdown_observed_marks_only"], -0.01)
        self.assertEqual(gapped["nav_gap_row_dates"], ["20260908"])

    def test_legacy_rows_are_checked_against_a_supplied_calendar(self):
        legacy = [{"date": "20260827", "nav": 1_000_000.0, "daily_return": 0.0},
                  {"date": "20260828", "nav": 990_000.0, "daily_return": -0.01},
                  {"date": "20260908", "nav": 1_020_000.0, "daily_return": 0.0303}]
        self.assertEqual(model_paper_fund.compute_performance(_fund(), [], legacy)["max_drawdown"],
                         -0.01)
        perf = model_paper_fund.compute_performance(_fund(), [], legacy, calendar=STATIC)
        self.assertIsNone(perf["max_drawdown"])
        self.assertEqual(perf["nav_gap_row_dates"], ["20260908"])


class PortfolioContractTests(unittest.TestCase):
    def _contract(self, nav):
        with tempfile.TemporaryDirectory() as tmp:
            fund_dir = Path(tmp, "model_fund")
            fund_dir.mkdir()
            for name, value in (("fund.json", _fund(nav[-1]["cash"])), ("orders.json", []),
                                ("nav_history.json", nav)):
                (fund_dir / name).write_text(json.dumps(value), encoding="utf-8")
            with mock.patch.object(export_contracts, "HERE", tmp), \
                    mock.patch.object(session_calendar, "ROTATION_HISTORY",
                                      str(Path(tmp, "absent.json"))), \
                    mock.patch.dict(os.environ, {"AR_TARGET_TRADE_DATE": nav[-1]["date"],
                                                 "AR_RUN_ID": "fixture"}):
                return export_contracts.build_model_portfolio_state()

    @staticmethod
    def _row(date, nav=1_000_000.0, daily=0.0):
        return {"date": date, "nav": nav, "cash": nav, "n_positions": 0,
                "daily_return": daily, "cum_return": round(nav / 1_000_000.0 - 1, 5)}

    def test_contiguous_series_stays_complete(self):
        contract = self._contract([self._row("20260924"), self._row("20260928")])
        self.assertEqual(contract["data_quality"], "COMPLETE")
        self.assertEqual(contract["data"]["nav_session_audit"]["contiguity"], "CONTIGUOUS")

    def test_gapped_series_is_partial_and_lists_missing_sessions(self):
        contract = self._contract([self._row("20260828"),
                                   self._row("20260908", 1_006_790.0, 0.00679),
                                   self._row("20260909", 1_006_790.0, 0.0)])
        self.assertEqual(contract["pipeline_status"], "OK")
        self.assertEqual(contract["data_quality"], "PARTIAL")
        audit = contract["data"]["nav_session_audit"]
        self.assertEqual(audit["contiguity"], "GAPPED")
        self.assertEqual(audit["missing_sessions"], ["20260831", "20260901", "20260902",
                                                     "20260903", "20260904", "20260907"])
        self.assertEqual(audit["multi_session_daily_return_dates"], ["20260908"])
        degraded = [d for d in contract["degraded_sources"] if d.get("why") == "NAV_SESSION_GAP"]
        self.assertEqual(degraded[0]["missing_sessions"], audit["missing_sessions"])

    def test_unprovable_span_is_partial_not_complete(self):
        contract = self._contract([self._row("20261231"), self._row("20270104")])
        self.assertEqual(contract["data_quality"], "PARTIAL")
        self.assertEqual(contract["data"]["nav_session_audit"]["contiguity"], "UNVERIFIABLE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
