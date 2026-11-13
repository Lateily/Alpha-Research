"""Offline regressions for the stricter operational acceptance contract."""
import datetime
import fcntl
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/execution_tracker"))
import nightly_publish as publish
import run_nightly as nightly
import run_premarket_monitor as opening
import watchtower
import nightly_deadline as deadlines
import run_eod_decision as eod


class OperationalGatesTest(unittest.TestCase):
    def test_unknown_calendar_never_admits(self):
        date = "20261111"
        for result in ({"items": []}, {"items": [["20261110", 1]]},
                       {"items": [[date, "0"]]}, {"items": [[date, True]]},
                       {"items": [[date, 1], [date, 0]]}, OSError("fixture unavailable")):
            with self.subTest(result=result):
                options = ({"side_effect": result} if isinstance(result, Exception) else
                           {"return_value": {"fields": ["cal_date", "is_open"], **result}})
                with mock.patch.object(opening.fs, "_tushare_call", **options):
                    self.assertIsNot(opening.is_trading_day(date, "fixture")[0], True)
        with mock.patch.object(opening.fs, "_tushare_call", return_value={
            "fields": ["cal_date", "is_open"], "items": [[date, 1]],
        }):
            self.assertIs(opening.is_trading_day(date, "fixture")[0], True)

    def test_watchtower_before_auction_refuses_before_calendar(self):
        now = datetime.datetime(2026, 11, 11, 9, 14, 59, tzinfo=opening.mc.SHANGHAI)
        calendar = mock.Mock(return_value=(True, "fixture"))
        self.assertEqual(watchtower.start_admission("fixture", now, calendar)[0], watchtower.OUTSIDE_MARKET_HOURS)
        calendar.assert_not_called()

    def test_recovered_staging_cannot_enter_publish_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            et = repo / "experiments/execution_tracker"
            for directory in (et, repo / "experiments/research_funnel", repo / "experiments/macro_os"):
                directory.mkdir(parents=True, exist_ok=True)
            run = et / "runs/R_OLD"
            stage = publish.prepare_stage(str(et), str(repo), str(run))
            marker = et / "run_state.json"
            marker.write_text(json.dumps({"orchestrator": "nightly_v4", "run_id": "R_OLD",
                                          "phase": "RUNNING_STAGING", "pid": 1}))
            state = et / "publication_state.json"
            with mock.patch.multiple(nightly, HERE=str(et), REPO_ROOT=str(repo), RUN_STATE=str(marker),
                                     RUNS_DIR=str(et / "runs"), PUBLICATION_STATE=str(state)), \
                    mock.patch.object(deadlines.os, "killpg") as kill_group:
                nightly._crash_check_and_rollback()
                kill_group.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, "FENCED"):
                publish.publish_stage("R_OLD", "20261111", stage, str(et), str(repo), str(run), str(state))
            self.assertFalse(state.exists())
            self.assertFalse((run / "publish_plan.json").exists())

    def test_calendar_must_be_explicit_even_after_callback_returns(self):
        now = datetime.datetime(2026, 11, 11, 10, 0, tzinfo=opening.mc.SHANGHAI)
        self.assertEqual(opening.mc.session_admission(lambda: now, lambda _: (1, "malformed"))[0],
                         opening.mc.CALENDAR_UNPROVEN)

    def test_calendar_return_after_close_is_refused(self):
        before = datetime.datetime(2026, 11, 11, 14, 59, 59, tzinfo=opening.mc.SHANGHAI)
        clock = iter((before, before + datetime.timedelta(seconds=1)))
        self.assertEqual(opening.mc.session_admission(lambda: next(clock), lambda _: (True, "open"))[0],
                         opening.mc.OUTSIDE_MARKET_HOURS)

    def test_watchtower_poll_checks_calendar_before_reading_local_inputs(self):
        now = datetime.datetime(2026, 11, 11, 10, 0, tzinfo=opening.mc.SHANGHAI)
        with mock.patch.object(watchtower, "load_json", side_effect=AssertionError("early data read")):
            quote = mock.Mock()
            self.assertEqual(watchtower.poll_once("fixture", clock=lambda: now, quote_fn=quote,
                                                 trading_day_fn=lambda _: (None, "unproven")), [])
            quote.assert_not_called()

    def test_expired_process_is_fenced_before_group_cleanup(self):
        order = []
        child = mock.Mock()
        deadline = mock.Mock()
        deadline.remaining.side_effect = [1, 0]
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(deadlines.subprocess, "Popen", return_value=child) as spawn, \
                mock.patch.object(deadlines, "_exit_observer", return_value=mock.MagicMock()), \
                mock.patch.object(deadlines, "_stop_group", side_effect=lambda _: order.append("signal")):
            code, _ = deadlines.run_owned(["fixture"], tmp, {}, deadline, lambda _: order.append("fence"), lock_fd=33)
        self.assertEqual(code, 124)
        self.assertEqual(order, ["fence", "signal"])
        self.assertEqual(spawn.call_args.kwargs["pass_fds"], (33,))

    @unittest.skipUnless(sys.platform == "darwin", "macOS group signal semantics")
    def test_cooperative_timeout_reaps_without_escalation_on_macos(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(deadlines.os, "killpg", wraps=deadlines.os.killpg) as send:
            code, _ = deadlines.run_owned(
                [sys.executable, "-I", "-B", "-c", "import time; time.sleep(45)"],
                tmp, {}, deadlines.Deadline(0.35), mock.Mock())
        self.assertEqual(code, 124)
        self.assertIn(signal.SIGTERM, [call.args[1] for call in send.call_args_list])
        self.assertNotIn(signal.SIGKILL, [call.args[1] for call in send.call_args_list])

    def _cleanup_trace(self, *, owned=True, live=True, term_sent=True):
        now = 5_000_000_000
        trace = []
        child = mock.Mock(pid=1234, returncode=None)

        def sleep(seconds):
            nonlocal now
            now += round(seconds * 10**9)

        def send(pgid, sig):
            self.assertEqual(pgid, child.pid)
            if sig:
                trace.append((signal.Signals(sig).name, now))
            if sig == signal.SIGTERM and not term_sent:
                raise ProcessLookupError

        def group(_):
            return child.pid if owned or now < 25_000_000_000 else 5678

        with mock.patch.object(deadlines, "continuous_ns", side_effect=lambda: now), \
                mock.patch.object(deadlines.time, "sleep", side_effect=sleep), \
                mock.patch.object(deadlines.os, "getpgid", side_effect=group), \
                mock.patch.object(deadlines.os, "getsid", return_value=child.pid), \
                mock.patch.object(deadlines.os, "killpg", side_effect=send), \
                mock.patch.object(deadlines, "_group_has_live_process", return_value=live):
            deadlines._stop_group(child)
        child.wait.assert_called_once()
        return trace

    def test_cleanup_waits_two_full_windows(self):
        self.assertEqual(self._cleanup_trace(), [
            ("SIGTERM", 15_000_000_000), ("SIGKILL", 25_000_000_000),
        ])

    def test_kill_requires_current_owned_group(self):
        self.assertEqual(self._cleanup_trace(owned=False), [("SIGTERM", 15_000_000_000)])

    def test_kill_requires_proven_liveness(self):
        for live in (False, None):
            with self.subTest(live=live):
                self.assertEqual(self._cleanup_trace(live=live), [("SIGTERM", 15_000_000_000)])

    def test_no_kill_when_term_target_has_already_exited(self):
        self.assertEqual(self._cleanup_trace(term_sent=False), [("SIGTERM", 15_000_000_000)])

    def test_cleanup_clock_fault_requires_full_grace_on_fallback(self):
        now = 0

        def sleep(seconds):
            nonlocal now
            now += round(seconds * 10**9)

        with mock.patch.object(deadlines, "continuous_ns", side_effect=[100, 100, 99]), \
                mock.patch.object(deadlines.time, "monotonic_ns", side_effect=lambda: now), \
                mock.patch.object(deadlines.time, "sleep", side_effect=sleep):
            self.assertTrue(deadlines._wait_cleanup_grace(10))
        self.assertEqual(now, 10_100_000_000)

    def test_linux_group_liveness_needs_a_non_zombie_member_in_the_owned_session(self):
        leader = mock.Mock(name="leader-entry")
        leader.name = "1234"
        descendant = mock.Mock(name="descendant-entry")
        descendant.name = "5678"
        with mock.patch.object(deadlines.os, "scandir", return_value=mock.MagicMock()) as proc, \
                mock.patch("builtins.open") as read_stat:
            proc.return_value.__enter__.return_value = [leader, descendant]
            for stat, expected in (("S 1234 1234 1234", True), ("Z 1234 1234 1234", None),
                                   ("S 1234 1234 8000", None)):
                with self.subTest(stat=stat):
                    read_stat.side_effect = [
                        mock.mock_open(read_data="1234 (leader) Z 1 1234 1234")(),
                        mock.mock_open(read_data="5678 (child with a ) in name) " + stat)(),
                    ]
                    self.assertIs(deadlines._linux_group_has_live_process(1234), expected)

    def test_failed_durable_fence_never_enters_cleanup(self):
        deadline = mock.Mock()
        deadline.remaining.side_effect = [1, 0]
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(deadlines.subprocess, "Popen"), \
                mock.patch.object(deadlines, "_exit_observer", return_value=mock.MagicMock()), \
                mock.patch.object(deadlines, "_stop_group") as cleanup:
            with self.assertRaisesRegex(OSError, "fixture fsync"):
                deadlines.run_owned(["fixture"], tmp, {}, deadline, mock.Mock(side_effect=OSError("fixture fsync")))
            cleanup.assert_not_called()

    def test_group_signal_permission_error_with_live_member_is_not_swallowed(self):
        child = mock.Mock(pid=1234, returncode=None)
        with mock.patch.object(deadlines.sys, "platform", "darwin"), \
                mock.patch.object(deadlines.os, "killpg", side_effect=PermissionError), \
                mock.patch.object(deadlines, "_darwin_group_has_live_process", return_value=True):
            with self.assertRaises(PermissionError):
                deadlines._send_group(child, 0)

    def test_sleep_elapsed_and_rollback_cannot_revive_deadline(self):
        with mock.patch.object(deadlines, "_sample", side_effect=[(100, 200), (101, 600000000201)]):
            deadline = deadlines.Deadline(600)
            self.assertEqual(deadline.remaining(), 0)
        with mock.patch.object(deadlines, "_sample", side_effect=[(100, 200), (99, 201), (102, 202)]):
            deadline = deadlines.Deadline(600)
            self.assertEqual(deadline.remaining(), 0)
            self.assertEqual(deadline.remaining(), 0)

    def test_fence_blocks_commit_if_deadline_expires_at_pointer_replace(self):
        self._assert_late_pointer_rolls_back(after_write=False)

    def test_pointer_fsync_must_finish_before_commit_proof(self):
        self._assert_late_pointer_rolls_back(after_write=True)

    def _assert_late_pointer_rolls_back(self, after_write):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            et = repo / "experiments/execution_tracker"
            public = repo / "public/data/v2"
            for directory in (et, public, repo / "experiments/research_funnel", repo / "experiments/macro_os"):
                directory.mkdir(parents=True, exist_ok=True)
            for pointer in (et / "current_run.json", public / "current_run.json"):
                pointer.write_bytes(b'{"run_id":"PRIOR","target_trade_date":"20261110"}')
            (et / "rotation_panel.json").write_bytes(b"prior output")
            run = et / "runs/R_LATE"
            stage = publish.prepare_stage(str(et), str(repo), str(run))
            (et / "run_state.json").write_text(json.dumps({
                "phase": "PUBLISHING", "run_id": "R_LATE", "target_trade_date": "20261111", "run_dir": str(run),
            }))
            (Path(stage["et"]) / "rotation_panel.json").write_bytes(b"late output")
            real_json = publish.atomic_json
            expired = False

            def interrupt_at_marker(path, value, **kwargs):
                nonlocal expired
                if not after_write and path == str(public / "current_run.json"):
                    expired = True
                real_json(path, value, **kwargs)
                if after_write and path == str(et / "current_run.json"):
                    expired = True

            def check():
                if expired:
                    self.assertEqual(json.loads((et / "publication_state.json").read_bytes())["status"],
                                     "PUBLISHING")
                    publish.fence_run("R_LATE", str(run), "TEST_DEADLINE")
                    raise deadlines.DeadlineExpired("PUBLICATION_FENCED")

            with mock.patch.object(publish, "atomic_json", side_effect=interrupt_at_marker):
                with self.assertRaisesRegex(deadlines.DeadlineExpired, "FENCED"):
                    publish.publish_stage("R_LATE", "20261111", stage, str(et), str(repo), str(run),
                                          str(et / "publication_state.json"), deadline_guard=check)
            self.assertTrue((run / "publication_fence.json").exists())
            self.assertEqual((et / "rotation_panel.json").read_bytes(), b"prior output")
            self.assertEqual((et / "current_run.json").read_bytes(), b'{"run_id":"PRIOR","target_trade_date":"20261110"}')
            self.assertEqual((public / "current_run.json").read_bytes(), b'{"run_id":"PRIOR","target_trade_date":"20261110"}')
            self.assertFalse((public / "runs/R_LATE/manifest.json").exists())

    def test_second_opening_read_requires_new_calendar_confirmation(self):
        now = datetime.datetime(2026, 11, 11, 10, 0, tzinfo=opening.mc.SHANGHAI)
        calendar = mock.Mock(side_effect=[(True, "first open"), (None, "second unknown")])
        quote = mock.Mock(return_value=[])
        result = opening.monitor("fixture", clock=lambda: now, trading_day_fn=calendar, quote_fn=quote)
        self.assertEqual(result["admission_status"], opening.mc.CALENDAR_UNPROVEN)
        self.assertEqual(quote.call_count, 1)

    def test_surviving_step_keeps_controller_lock_after_controller_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "nightly.lock")
            held = []

            def interrupted(lock_fd):
                held.append(subprocess.Popen(
                    [sys.executable, "-I", "-B", "-c", "import sys; sys.stdin.buffer.read()"],
                    stdin=subprocess.PIPE, pass_fds=(lock_fd,),
                ))
                return 1

            with mock.patch.object(nightly, "NIGHTLY_LOCK", path), \
                    mock.patch.object(nightly, "_execute_nightly", side_effect=interrupted), \
                    mock.patch.object(sys, "argv", ["run_nightly.py"]):
                try:
                    self.assertEqual(nightly.main(), 1)
                    with open(path) as contender:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    for child in held:
                        child.communicate(timeout=5)
                with open(path) as contender:
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_corrupt_or_fenced_committed_run_cannot_authorize_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            et = repo / "experiments/execution_tracker"
            public = repo / "public/data/v2"
            for directory in (et, public, repo / "experiments/research_funnel", repo / "experiments/macro_os"):
                directory.mkdir(parents=True, exist_ok=True)
            prior = b'{"run_id":"PRIOR","target_trade_date":"20261110"}'
            for pointer in (et / "current_run.json", public / "current_run.json"):
                pointer.write_bytes(prior)
            (public / "meta.json").write_bytes(b'{"value":"prior"}')
            run = et / "runs/R_LATE"
            stage = publish.prepare_stage(str(et), str(repo), str(run))
            (Path(stage["public"]) / "meta.json").write_bytes(b'{"value":"new"}')
            active = et / "run_state.json"
            active.write_text(json.dumps({
                "orchestrator": "nightly_v4", "phase": "PUBLISHING", "run_id": "R_LATE",
                "target_trade_date": "20261111", "run_dir": str(run),
            }))
            state = str(et / "publication_state.json")
            publish.publish_stage("R_LATE", "20261111", stage, str(et), str(repo), str(run), state,
                                  deadline_guard=lambda: None)
            committed_bytes = Path(state).read_bytes()
            committed = json.loads(committed_bytes)
            self.assertEqual(committed["schema"], publish.PUBLICATION_STATE_SCHEMA)
            self.assertEqual(committed["commit_guard"], publish.COMMIT_PROOF)
            committed_pointer = (public / "current_run.json").read_bytes()
            self.assertNotEqual(committed_pointer, prior)
            durable_manifest = run / "manifest.json"
            original = durable_manifest.read_bytes()
            self.assertEqual(publish.recover_interrupted_publish(state, str(et), str(repo))["status"],
                             "COMMITTED_VERIFIED")
            for broken in ({k: v for k, v in committed.items() if k != "commit_guard"},
                           {**committed, "commit_guard": "DEADLINE_NOT_PROVEN"},
                           {**committed, "schema": publish.LEGACY_PUBLICATION_STATE_SCHEMA}):
                broken_bytes = json.dumps(broken).encode()
                Path(state).write_bytes(broken_bytes)
                with mock.patch.multiple(nightly, HERE=str(et), REPO_ROOT=str(repo),
                                         RUN_STATE=str(active), PUBLICATION_STATE=state):
                    with self.assertRaisesRegex(RuntimeError, "COMMIT_DEADLINE_UNPROVEN"):
                        nightly._crash_check_and_rollback()
                self.assertTrue(active.exists())
                self.assertEqual(Path(state).read_bytes(), broken_bytes)
                self.assertFalse((run / "publication_fence.json").exists())
                self.assertEqual((public / "current_run.json").read_bytes(), committed_pointer)
            Path(state).write_bytes(committed_bytes)
            durable_manifest.unlink()
            (public / "meta.json").write_bytes(b'{"value":"later"}')
            with mock.patch.multiple(nightly, HERE=str(et), REPO_ROOT=str(repo),
                                     RUN_STATE=str(active), PUBLICATION_STATE=state):
                for _ in range(2):
                    with self.assertRaises(RuntimeError):
                        nightly._crash_check_and_rollback()
                    self.assertFalse((run / "publication_fence.json").exists())
                durable_manifest.write_bytes(original)
                publish.fence_run("R_LATE", str(run), "UNPROVEN_TEST_FENCE")
                with self.assertRaisesRegex(RuntimeError, "PUBLICATION_FENCED"):
                    nightly._crash_check_and_rollback()
            self.assertEqual((et / "current_run.json").read_bytes(), committed_pointer)
            self.assertEqual((public / "current_run.json").read_bytes(), committed_pointer)
            self.assertEqual((public / "meta.json").read_bytes(), b'{"value":"later"}')

    def test_replay_cannot_replace_newer_current_run_even_with_active_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            et = repo / "experiments/execution_tracker"
            public = repo / "public/data/v2"
            for directory in (et, public, repo / "experiments/research_funnel", repo / "experiments/macro_os"):
                directory.mkdir(parents=True, exist_ok=True)
            prior = b'{"run_id":"NEWER","target_trade_date":"20261111"}'
            for pointer in (et / "current_run.json", public / "current_run.json"):
                pointer.write_bytes(prior)
            run = et / "runs/R_REPLAY"
            stage = publish.prepare_stage(str(et), str(repo), str(run))
            (et / "run_state.json").write_text(json.dumps({
                "phase": "PUBLISHING", "run_id": "R_REPLAY", "target_trade_date": "20261110", "run_dir": str(run),
            }))
            with self.assertRaisesRegex(RuntimeError, "REPLAY_OR_DATE_REGRESSION"):
                publish.publish_stage("R_REPLAY", "20261110", stage, str(et), str(repo), str(run),
                                      str(et / "publication_state.json"), deadline_guard=lambda: None)
            self.assertEqual((public / "current_run.json").read_bytes(), prior)
            self.assertFalse((run / "publish_plan.json").exists())

    def test_daemon_0914_waits_without_calendar_or_poll_until_0915(self):
        now = datetime.datetime(2026, 11, 11, 9, 14, tzinfo=opening.mc.SHANGHAI)
        readings = []

        def sleep(seconds):
            nonlocal now
            now += datetime.timedelta(seconds=seconds)

        def poll():
            nonlocal now
            readings.append(now.strftime("%H:%M:%S"))
            now = now.replace(hour=15, minute=0)

        calendar = mock.Mock(return_value=(True, "fixture"))
        with mock.patch.object(watchtower, "notify"):
            watchtower.daemon("fixture", clock=lambda: now, sleep=sleep, poll=poll, trading_day_fn=calendar)
        self.assertEqual(readings, ["09:15:00"])
        self.assertEqual(calendar.call_count, 2)

    def test_quote_fallback_cannot_cross_close(self):
        mc = opening.mc
        now = datetime.datetime(2026, 11, 11, 14, 59, 59, tzinfo=mc.SHANGHAI)

        def primary(**_):
            nonlocal now
            now += datetime.timedelta(seconds=1)
            raise OSError("fixture primary failed")

        fallback = mock.Mock()
        rtq = types.SimpleNamespace(get_realtime_quotes_sina=fallback, symbol_verify=lambda s: s)
        modules = {"tushare": types.SimpleNamespace(realtime_quote=primary, get_realtime_quotes=fallback),
                   "tushare.stock": types.SimpleNamespace(rtq=rtq)}
        with mock.patch.dict(sys.modules, modules), self.assertRaises(mc.SessionRefused):
            opening.fs.tushare_realtime_quotes(["TEST.SH"], before_read=lambda: mc.require_session(
                lambda: now, lambda d: (True, "fixture"), "20261111"))
        fallback.assert_not_called()

    def test_eod_quote_returning_after_eod_window_cannot_append(self):
        mc = opening.mc
        now = datetime.datetime(2026, 11, 11, 14, 55, 59, tzinfo=mc.SHANGHAI)

        def quote(_):
            nonlocal now
            now += datetime.timedelta(seconds=1)
            return []

        with mock.patch.dict(eod.os.environ, {"TUSHARE_TOKEN": "fixture"}), \
                mock.patch.object(eod, "_load", return_value=[{"ticker": "TEST.SH", "setup_type": "execution_gate"}]), \
                mock.patch.object(eod, "append_log") as append:
            self.assertEqual(eod.main([], clock=lambda: now, quote_fn=quote, trading_day_fn=lambda d: (True, "fixture")), 0)
        append.assert_not_called()

    def test_eod_rechecks_date_on_final_quote_guard_sample(self):
        mc = opening.mc
        now = datetime.datetime(2026, 11, 11, 14, 30, tzinfo=mc.SHANGHAI)
        clock = iter([now] * 7 + [now + datetime.timedelta(days=1)] * 2)
        attempted = []

        def adapter(_, *, src, before_read):
            before_read()
            attempted.append("provider")
            return []

        with mock.patch.dict(eod.os.environ, {"TUSHARE_TOKEN": "fixture"}), \
                mock.patch.object(eod, "_load", return_value=[{"ticker": "TEST.SH", "setup_type": "execution_gate"}]), \
                mock.patch.object(opening.fs, "tushare_realtime_quotes", side_effect=adapter):
            self.assertEqual(eod.main([], clock=lambda: next(clock), trading_day_fn=lambda d: (True, "fixture")),
                             eod.EXIT_OUTSIDE_MARKET_HOURS)
        self.assertEqual(attempted, [])

    def test_standalone_realtime_cli_refuses_unknown_calendar_before_quote(self):
        mc = opening.mc
        now = datetime.datetime(2026, 11, 11, 10, 0, tzinfo=mc.SHANGHAI)
        with mock.patch.object(sys, "argv", ["fund_source.py", "--realtime", "TEST.SH"]), \
                mock.patch.object(mc, "shanghai_now", return_value=now), \
                mock.patch.object(opening, "is_trading_day", return_value=(None, "unproven")), \
                mock.patch.object(opening.fs, "tushare_realtime_quotes", return_value=[]) as quote:
            with self.assertRaises(SystemExit) as exc:
                opening.fs.main()
        self.assertEqual(exc.exception.code, 1)
        quote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
