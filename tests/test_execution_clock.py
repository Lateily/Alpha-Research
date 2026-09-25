"""Asia/Shanghai clock for the intraday execution jobs (2026-09 London-clock incident).

The production Mac moved to Europe/London on 2026-09-16 and launchd re-anchored
to London time after the ~2026-09-22 reboot: the watchtower (09:14 local) polled
16:14-22:05 Beijing and the EOD window (14:26 local) ran at 21:26 Beijing, so 36
nowcasts were computed from completed-session features. Every scenario below
injects the clock: a London-local launchd fire must fail closed, a Beijing-local
fire must behave as before, and the evaluator must never score a read it cannot
prove was taken in-session.

Run: python3 tests/test_execution_clock.py
不是买卖指令；研究信号，human executes。
"""

import datetime
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "experiments", "execution_tracker"))

import market_clock as mc  # noqa: E402
import nowcast_evaluator as ne  # noqa: E402
import run_eod_decision as eod  # noqa: E402
import run_premarket_monitor as rpm  # noqa: E402
import watchtower as wt  # noqa: E402

BST = datetime.timezone(datetime.timedelta(hours=1))      # Europe/London in September
CST = mc.SHANGHAI


def at(tz, hour, minute, second=0, day=23):
    """An instant on 2026-09-<day> (Wed 23rd by default) on the given wall clock."""
    return datetime.datetime(2026, 9, day, hour, minute, second, tzinfo=tz)


class FakeClock:
    """Injected clock; `sleep` advances it instead of blocking."""

    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now = self.now + datetime.timedelta(seconds=seconds)


def trading_day(_date):
    return True, "open(injected)"


def holiday(_date):
    return False, "非交易日(injected)"


def sinking_read(ticker="300001.SZ", name="甲"):
    # gap -4%, 2% under the open -> DISTRIBUTION_PROBABLE (conf 0.66)
    return {"ticker": ticker, "name": name, "price": 96.0, "open": 98.0, "high": 98.5,
            "gap": -0.04, "from_open": -0.0204, "from_high": -0.0254,
            "gapped_up": False, "faded": True, "intraday_range": 0.027}


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def path(self, name):
        return os.path.join(self.tmp, name)


class MarketClockTests(unittest.TestCase):
    def test_absolute_instant_ignores_machine_local_zone(self):
        previous = os.environ.get("TZ")
        os.environ["TZ"] = "LON-1"            # POSIX form of UTC+1, i.e. the London machine
        time.tzset()
        try:
            local_wall = datetime.datetime.now()
            now = mc.shanghai_now()
            utc = datetime.datetime.now(datetime.timezone.utc)
        finally:
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            time.tzset()
        self.assertEqual(now.utcoffset(), datetime.timedelta(hours=8))
        self.assertLess(abs((now - utc).total_seconds()), 60)
        wall_gap = (now.replace(tzinfo=None) - local_wall).total_seconds()
        self.assertAlmostEqual(wall_gap, 7 * 3600, delta=60)

    def test_london_instant_converts_to_beijing_wall_clock(self):
        misfire = at(BST, 9, 14)
        self.assertEqual(mc.hhmm(misfire), "1614")
        self.assertEqual(mc.trade_date(misfire), "20260923")
        self.assertEqual(mc.stamp(misfire), "2026-09-23T16:14:00+08:00")
        self.assertFalse(mc.in_trading_session(misfire))
        self.assertTrue(mc.in_trading_session(at(CST, 9, 14 + 1)))

    def test_naive_datetime_is_refused(self):
        with self.assertRaises(ValueError):
            mc.to_shanghai(datetime.datetime(2026, 9, 23, 10, 0))

    def test_session_boundaries(self):
        self.assertEqual(mc.capture_verdict("20260923", at(CST, 14, 59, 59)), mc.IN_SESSION)
        self.assertEqual(mc.capture_verdict("20260923", at(CST, 15, 0)), mc.POST_CLOSE)
        self.assertEqual(mc.capture_verdict("20260923", at(CST, 9, 14)), mc.UNPROVEN_IN_SESSION)
        self.assertEqual(mc.capture_verdict("20260923", at(CST, 10, 0, day=24)), mc.POST_CLOSE)
        self.assertEqual(mc.capture_verdict("20260926", at(CST, 10, 0, day=26)),
                         mc.UNPROVEN_IN_SESSION)      # Saturday


class NowcastWriterTests(TempDirCase):
    def test_london_misfire_read_logs_nothing(self):
        log_path = self.path("nowcast_log.json")
        added = rpm.log_nowcasts([sinking_read()], "20260923", "wt0914",
                                 log_path=log_path, captured_at=at(BST, 9, 14))
        self.assertEqual(added, [])
        self.assertFalse(os.path.exists(log_path))

    def test_beijing_session_read_records_captured_at(self):
        log_path = self.path("nowcast_log.json")
        added = rpm.log_nowcasts([sinking_read()], "20260923", "wt1000",
                                 log_path=log_path, captured_at=at(CST, 10, 0))
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].get("captured_at"), "2026-09-23T10:00:00+08:00")
        with open(log_path, encoding="utf-8") as fh:
            stored = json.load(fh)
        self.assertEqual(stored[0].get("captured_at"), "2026-09-23T10:00:00+08:00")
        self.assertEqual(mc.nowcast_admission(stored[0]), mc.IN_SESSION)

    def test_closing_auction_boundary_is_post_close(self):
        log_path = self.path("nowcast_log.json")
        last = rpm.log_nowcasts([sinking_read()], "20260923", "wt1459",
                                log_path=log_path, captured_at=at(CST, 14, 59, 59))
        late = rpm.log_nowcasts([sinking_read("300002.SZ", "乙")], "20260923", "wt1500",
                                log_path=log_path, captured_at=at(CST, 15, 0))
        self.assertEqual(len(last), 1)
        self.assertEqual(late, [])

    def test_read_dated_on_the_wrong_day_is_refused(self):
        log_path = self.path("nowcast_log.json")
        added = rpm.log_nowcasts([sinking_read()], "20260922", "wt1000",
                                 log_path=log_path, captured_at=at(CST, 10, 0))
        self.assertEqual(added, [])


class WatchtowerTests(TempDirCase):
    def setUp(self):
        super().setUp()
        for attr, name, payload in (("STATE_PATH", "state.json", None),
                                    ("ALERT_LOG", "alerts.json", None),
                                    ("FUND_ORDERS", "orders.json", []),
                                    ("WATCH_DYNAMIC", "watch.json", {"watch": [
                                        {"ticker": "300001.SZ", "name": "甲"}]})):
            path = self.path(name)
            if payload is not None:
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh)
            patcher = mock.patch.object(wt, attr, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.nowcast_log = self.path("nowcast_log.json")
        for patcher in (mock.patch.object(rpm, "NOWCAST_LOG", self.nowcast_log),
                        mock.patch.object(wt, "notify", self._record_notify)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.notifications = []

    def _record_notify(self, title, body, dry=False):
        self.notifications.append(title)
        return {"dry": True}

    def test_london_clock_start_is_outside_market_hours(self):
        status, why = wt.start_admission("", now=at(BST, 9, 14), trading_day_fn=trading_day)
        self.assertEqual(status, wt.OUTSIDE_MARKET_HOURS)
        self.assertIn("16:14:00+08:00", why)

    def test_beijing_clock_start_is_admitted(self):
        status, _ = wt.start_admission("", now=at(CST, 9, 14), trading_day_fn=trading_day)
        self.assertEqual(status, wt.ADMITTED)

    def test_non_trading_day_start_is_refused(self):
        status, _ = wt.start_admission("", now=at(CST, 9, 14), trading_day_fn=holiday)
        self.assertEqual(status, wt.NON_TRADING_DAY)

    def test_london_daemon_exits_without_polling_or_logging(self):
        clock = FakeClock(at(BST, 9, 14))
        polls = []
        status = wt.daemon("", clock=clock, sleep=clock.sleep,
                           poll=lambda: polls.append(clock()), trading_day_fn=trading_day)
        self.assertEqual(status, wt.OUTSIDE_MARKET_HOURS)
        self.assertEqual(polls, [])
        self.assertEqual(self.notifications, [])
        self.assertFalse(os.path.exists(self.nowcast_log))

    def test_beijing_daemon_logs_only_in_session_flips(self):
        clock = FakeClock(at(CST, 14, 50))

        def quotes(_tickers):
            now = clock()
            if now.time() < datetime.time(15, 0):      # gap-down, sinking
                row = {"price": 96.0, "pre_close": 100.0, "open": 98.0, "high": 98.5, "low": 95.8}
            else:                                       # post-close: flips to FAKE_STRENGTH
                row = {"price": 104.5, "pre_close": 100.0, "open": 104.0, "high": 110.0, "low": 103.0}
            row.update({"ticker": "300001.SZ", "name": "甲"})
            return [row]

        polled = []

        def poll():
            polled.append(mc.hhmm(clock()))
            wt.poll_once("", dry=True, clock=clock, quote_fn=quotes)

        status = wt.daemon("", clock=clock, sleep=clock.sleep, poll=poll,
                           trading_day_fn=trading_day)
        self.assertEqual(status, "SESSION_END")
        self.assertEqual(polled[0], "1450")
        self.assertIn("1504", polled)                   # 15:00-15:05 still polls alerts
        with open(self.nowcast_log, encoding="utf-8") as fh:
            logged = json.load(fh)
        self.assertEqual([(r["date"], r["checkpoint"], r.get("captured_at")) for r in logged],
                         [("20260923", "wt1450", "2026-09-23T14:50:00+08:00")])
        with open(wt.ALERT_LOG, encoding="utf-8") as fh:
            flips = [a["key"] for a in json.load(fh) if a["rule"] == "NOWCAST_FLIP"]
        self.assertEqual(len(flips), 2)                 # the 15:00 flip alerted, never logged


class EodDecisionTests(TempDirCase):
    SIGNAL = {"ticker": "002463.SZ", "name": "沪电", "setup_type": "execution_gate",
              "outcome_status": "pending", "official_sample": False, "signal_id": "a2a40a",
              "trigger_condition": "回踩127-130承接", "invalidation": "收盘<123"}

    def setUp(self):
        super().setUp()
        self.out = self.path("eod_candidates.json")
        signals = self.path("paper_signal_log.json")
        with open(signals, "w", encoding="utf-8") as fh:
            json.dump([self.SIGNAL], fh, ensure_ascii=False)
        for patcher in (mock.patch.object(eod, "OUT", self.out),
                        mock.patch.object(eod, "SIGNALS", signals),
                        mock.patch.dict(os.environ, {"TUSHARE_TOKEN": "offline-test"})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.quote_calls = []

    def quotes(self, tickers):
        self.quote_calls.append(tuple(tickers))
        return [{"ticker": "002463.SZ", "price": 131.0, "low": 128.5, "high": 137.0}]

    def run_main(self, instant, argv=(), trading_day_fn=trading_day):
        clock = FakeClock(instant)
        return eod.main(list(argv), clock=clock, quote_fn=self.quotes,
                        trading_day_fn=trading_day_fn)

    def test_london_clock_eod_fire_is_outside_market_hours(self):
        code = self.run_main(at(BST, 14, 26))
        self.assertEqual(code, eod.EXIT_OUTSIDE_MARKET_HOURS)
        self.assertEqual(self.quote_calls, [])
        self.assertFalse(os.path.exists(self.out))

    def test_force_cannot_bypass_outside_market_hours(self):
        code = self.run_main(at(BST, 14, 26), argv=["--force"])
        self.assertEqual(code, eod.EXIT_OUTSIDE_MARKET_HOURS)
        self.assertFalse(os.path.exists(self.out))

    def test_beijing_clock_eod_window_writes_stamped_candidates(self):
        code = self.run_main(at(CST, 14, 26))
        self.assertEqual(code, 0)
        with open(self.out, encoding="utf-8") as fh:
            rows = json.load(fh)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "20260923")
        self.assertEqual(rows[0]["window"], "1426")
        self.assertEqual(rows[0].get("captured_at"), "2026-09-23T14:26:00+08:00")
        self.assertEqual(rows[0]["verdict"], "REVIEW_CANDIDATE")

    def test_in_session_off_window_is_unchanged(self):
        code = self.run_main(at(CST, 10, 0))
        self.assertEqual(code, 0)
        self.assertEqual(self.quote_calls, [])
        self.assertFalse(os.path.exists(self.out))

    def test_non_trading_day_eod_is_refused(self):
        code = self.run_main(at(CST, 14, 26), trading_day_fn=holiday)
        self.assertEqual(code, 0)
        self.assertEqual(self.quote_calls, [])
        self.assertFalse(os.path.exists(self.out))


def _record(**fields):
    base = {"nowcast_id": "x", "ticker": "A.SZ", "state": "OPENING_FADE",
            "predicted_flow_dir": -1, "scored": False}
    base.update(fields)
    return base


def _score(log):
    return ne.score_log(log, token=None, settle_fn=lambda t, d: -5.0, ret_fn=lambda t, d: -0.01)


class NowcastEvaluatorTests(unittest.TestCase):
    # (date, checkpoint) of the 36 London-clock records in production, 2026-09-18..24
    INCIDENT = [("20260918", "wt1238"), ("20260918", "wt1352"), ("20260921", "wt0910"),
                ("20260921", "wt1405"), ("20260922", "wt0942"), ("20260923", "wt0926"),
                ("20260924", "wt0927")]

    def test_post_close_capture_is_never_scored(self):
        log = [_record(date="20260923", checkpoint="wt1614",
                       captured_at="2026-09-23T16:14:00+08:00")]
        frozen = json.dumps(log, sort_keys=True)
        n_flow, n_ret = _score(log)
        self.assertEqual((n_flow, n_ret), (0, 0))
        self.assertEqual(json.dumps(log, sort_keys=True), frozen)

    def test_post_close_capture_is_counted_separately(self):
        log = [_record(date="20260923", checkpoint="wt1614",
                       captured_at="2026-09-23T16:14:00+08:00"),
               _record(date="20260923", checkpoint="wt1000",
                       captured_at="2026-09-23T10:00:00+08:00")]
        counts = ne.admission_counts(log)
        self.assertEqual(counts[mc.POST_CLOSE], 1)
        self.assertEqual(counts[mc.IN_SESSION], 1)

    def test_post_cutover_legacy_label_is_unproven(self):
        log = [_record(date=d, checkpoint=c) for d, c in self.INCIDENT]
        frozen = json.dumps(log, sort_keys=True)
        n_flow, _ = _score(log)
        self.assertEqual(n_flow, 0)
        self.assertEqual(json.dumps(log, sort_keys=True), frozen)
        self.assertEqual(ne.admission_counts(log)[mc.UNPROVEN_IN_SESSION], len(self.INCIDENT))

    def test_pre_cutover_legacy_label_is_still_scored(self):
        log = [_record(date="20260916", checkpoint="wt1037"),
               _record(date="20260915", checkpoint="1030")]
        n_flow, _ = _score(log)
        self.assertEqual(n_flow, 2)
        self.assertTrue(all(r["scored"] for r in log))

    def test_naive_captured_at_is_unproven(self):
        log = [_record(date="20260923", checkpoint="wt1000", captured_at="2026-09-23T10:00:00")]
        n_flow, _ = _score(log)
        self.assertEqual(n_flow, 0)
        self.assertEqual(ne.admission_counts(log)[mc.UNPROVEN_IN_SESSION], 1)

    def test_already_scored_excluded_record_never_reaches_hit_rate(self):
        log = [_record(date="20260923", checkpoint="wt1000", captured_at="2026-09-23T10:00:00+08:00",
                       scored=True, flow_hit=True, actual_main_flow=-5.0),
               _record(date="20260923", checkpoint="wt0926",       # legacy London label,
                       scored=True, flow_hit=True, actual_main_flow=-5.0)]  # scored elsewhere
        agg = ne.aggregate(log)
        self.assertEqual(agg["total_scored"], 1)
        self.assertEqual(agg["excluded_unproven_in_session"], 1)
        self.assertEqual(agg["excluded_post_close"], 0)


class ModuleSelftestTests(unittest.TestCase):
    def test_module_selftests_pass(self):
        for module in (mc, wt, eod, ne):
            with self.subTest(module=module.__name__):
                self.assertTrue(module.selftest())


if __name__ == "__main__":
    unittest.main(verbosity=2)
