"""Bounded transport retry for the U0 security registry's Tushare calls.

2026-09-21: one `daily` read timeout during the liquidity window became a source
error, E1 refused the join, and the whole nightly stayed unpublished. On Python
3.9 (the production interpreter) socket.timeout is not a TimeoutError, so the
retry tuple must name it explicitly.
"""

from __future__ import annotations

import ast
import io
import json
import socket
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))

import security_registry as registry  # noqa: E402


def _named_in_tuple(module_file: str, name: str) -> set[str]:
    """Element expressions of a module-level tuple, read from source.

    On Python 3.11+ socket.timeout IS TimeoutError, so a runtime membership check
    cannot tell whether socket.timeout was named. The 3.9 production interpreter
    needs it named, so the guard reads the source instead.
    """
    tree = ast.parse(Path(module_file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return {ast.unparse(element) for element in node.value.elts}
    raise AssertionError(f"{name} is not a module-level tuple in {module_file}")


class _Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _payload(fields, items, code=0):
    return _Response(json.dumps({"code": code, "data": {"fields": fields, "items": items}}).encode("utf-8"))


def _daily(trade_date, rows):
    return _payload(["ts_code", "trade_date", "amount"], [[c, trade_date, a] for c, a in rows])


def _read_timeout():
    return socket.timeout("The read operation timed out")


class SecurityRegistryTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        # Pin the budget clock: the step "started" at 0 and it is now t=10s.
        patcher = mock.patch.object(registry, "_STEP_STARTED", 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        clock = mock.patch.object(registry.time, "monotonic", return_value=10.0)
        clock.start()
        self.addCleanup(clock.stop)

    def test_socket_timeout_is_retryable_on_python39(self) -> None:
        """在 3.9 上 socket.timeout 不是 TimeoutError,必须在元组里点名,否则读超时永不重试。"""
        named = _named_in_tuple(registry.__file__, "TRANSIENT_TRANSPORT_ERRORS")
        self.assertIn("socket.timeout", named)
        self.assertIn(socket.timeout, registry.TRANSIENT_TRANSPORT_ERRORS)
        self.assertNotIn(urllib.error.HTTPError, registry.TRANSIENT_TRANSPORT_ERRORS)

    def test_read_timeout_then_success_is_retried(self) -> None:
        with mock.patch.object(
            registry.urllib.request, "urlopen",
            side_effect=[_read_timeout(), _payload(["cal_date", "is_open"], [["20260921", "1"]])],
        ) as urlopen, mock.patch.object(registry.time, "sleep") as sleep, \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            try:
                rows = registry._tushare_call("fixture-token", "trade_cal", {}, "cal_date,is_open")
            except registry.RegistryError as exc:
                self.fail(f"a single read timeout must be retried, got {exc}")
        self.assertEqual([{"cal_date": "20260921", "is_open": "1"}], rows)
        self.assertEqual(2, urlopen.call_count)
        sleep.assert_called_once_with(2.0)
        self.assertIn("U0_TRANSIENT_RETRY api=trade_cal attempt=2/3 reason=TIMEOUT", out.getvalue())

    def test_exhausted_retries_fail_closed_with_the_attempt_count(self) -> None:
        with mock.patch.object(
            registry.urllib.request, "urlopen", side_effect=[_read_timeout()] * 3,
        ) as urlopen, mock.patch.object(registry.time, "sleep") as sleep, \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaises(registry.RegistryError) as caught:
                registry._tushare_call("fixture-token", "daily", {}, "ts_code")
        self.assertEqual(3, urlopen.call_count)
        self.assertEqual([mock.call(2.0), mock.call(5.0)], sleep.call_args_list)
        self.assertIn("Tushare daily request failed after 3 attempt(s)", str(caught.exception))

    def test_provider_error_is_not_retried(self) -> None:
        with mock.patch.object(
            registry.urllib.request, "urlopen", side_effect=[_payload([], [], code=40203)],
        ) as urlopen, mock.patch.object(registry.time, "sleep") as sleep:
            with self.assertRaises(registry.RegistryError):
                registry._tushare_call("fixture-token", "daily", {}, "ts_code")
        self.assertEqual(1, urlopen.call_count)
        sleep.assert_not_called()

    def test_http_error_is_not_retried(self) -> None:
        error = urllib.error.HTTPError("https://api.tushare.pro", 403, "Forbidden", {}, None)
        with mock.patch.object(
            registry.urllib.request, "urlopen", side_effect=[error, _payload([], [])],
        ) as urlopen, mock.patch.object(registry.time, "sleep") as sleep:
            with self.assertRaises(registry.RegistryError):
                registry._tushare_call("fixture-token", "daily", {}, "ts_code")
        self.assertEqual(1, urlopen.call_count)
        sleep.assert_not_called()

    def test_no_retry_once_budget_is_spent(self) -> None:
        """预算用尽后不得再开新一轮重试,以免把步骤推过夜链 600 秒超时。"""
        with mock.patch.object(registry.time, "monotonic", return_value=280.0), \
                mock.patch.object(
                    registry.urllib.request, "urlopen",
                    side_effect=[_read_timeout(), _payload(["cal_date"], [["20260921"]])],
                ) as urlopen, mock.patch.object(registry.time, "sleep") as sleep:
            with self.assertRaises(registry.RegistryError):
                registry._tushare_call("fixture-token", "trade_cal", {}, "cal_date")
        self.assertEqual(1, urlopen.call_count)
        sleep.assert_not_called()

    def test_one_read_timeout_in_the_liquidity_window_leaves_no_source_error(self) -> None:
        """2026-09-21 的回归:窗口内一次读超时后重试成功,不得再记成来源错误。"""
        calendar = _payload(["cal_date", "is_open"], [["20260918", "1"], ["20260921", "1"]])
        responses = [
            calendar,
            _daily("20260918", [("600000.SH", 1000.0)]),
            _read_timeout(),
            _daily("20260921", [("600000.SH", 2000.0)]),
        ]
        with mock.patch.object(registry.urllib.request, "urlopen", side_effect=responses), \
                mock.patch.object(registry.time, "sleep"), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            amounts, traded, dates, errors = registry.fetch_liquidity("fixture-token", "20260921", 2)
        self.assertEqual([], errors)
        self.assertEqual(["20260918", "20260921"], dates)
        self.assertEqual([1000000.0, 2000000.0], amounts["600000.SH"])
        self.assertEqual({"600000.SH"}, traded)


if __name__ == "__main__":
    unittest.main(verbosity=2)
