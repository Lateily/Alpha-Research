"""Bounded transport retry regression for the production Tushare adapter."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import ssl
import sys
import unittest
import urllib.error
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))

import fund_source as fs  # noqa: E402


class _Response(io.BytesIO):
    status = 200


def _success_response() -> _Response:
    return _Response(
        json.dumps(
            {
                "code": 0,
                "data": {
                    "fields": ["exchange", "cal_date", "is_open"],
                    "items": [["SSE", "20260821", "1"]],
                },
            }
        ).encode("utf-8")
    )


def _moneyflow_response() -> _Response:
    return _Response(
        json.dumps(
            {
                "code": 0,
                "data": {
                    "fields": ["ts_code", "trade_date", "net_amount"],
                    "items": [["600000.SH", "20260821", 10000]],
                },
            }
        ).encode("utf-8")
    )


class FundSourceTransportTests(unittest.TestCase):
    def test_tushare_call_recovers_from_one_tls_eof(self) -> None:
        transient = urllib.error.URLError(
            ssl.SSLEOFError(8, "EOF occurred in violation of protocol")
        )
        with mock.patch.object(
            fs.urllib.request,
            "urlopen",
            side_effect=[transient, _success_response()],
        ) as urlopen, mock.patch.object(fs.time, "sleep") as sleep:
            result = fs._tushare_call(
                "trade_cal",
                "fixture-token",
                {"exchange": "SSE", "start_date": "20260821"},
                "exchange,cal_date,is_open",
            )

        self.assertEqual(result["items"], [["SSE", "20260821", "1"]])
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(0.5)

    def test_moneyflow_call_recovers_from_one_tls_eof(self) -> None:
        transient = urllib.error.URLError(
            ssl.SSLEOFError(8, "EOF occurred in violation of protocol")
        )
        with mock.patch.object(
            fs.urllib.request,
            "urlopen",
            side_effect=[transient, _moneyflow_response()],
        ) as urlopen, mock.patch.object(fs.time, "sleep") as sleep:
            result = fs.tushare_stock_fund("600000.SH", "fixture-token")

        self.assertEqual(result["date"], "20260821")
        self.assertEqual(result["main"], 1.0)
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(0.5)

    def test_retry_exhaustion_preserves_transport_failure(self) -> None:
        transient = urllib.error.URLError(
            ssl.SSLEOFError(8, "EOF occurred in violation of protocol")
        )
        sleeps: list[float] = []

        def fail(_request, timeout):
            self.assertEqual(timeout, 12)
            raise transient

        with self.assertRaises(urllib.error.URLError) as raised:
            fs._http_json(
                url=fs.TUSHARE_URL,
                data=b"{}",
                headers={"Content-Type": "application/json"},
                attempts=3,
                opener=fail,
                sleeper=sleeps.append,
            )

        self.assertIs(raised.exception, transient)
        self.assertEqual(sleeps, [0.5, 1.0])

    def test_http_error_is_not_retried(self) -> None:
        error = urllib.error.HTTPError(
            fs.TUSHARE_URL, 403, "Forbidden", hdrs=None, fp=None
        )
        opener = mock.Mock(side_effect=error)
        sleeper = mock.Mock()
        with self.assertRaises(urllib.error.HTTPError):
            fs._http_json(
                url=fs.TUSHARE_URL,
                opener=opener,
                sleeper=sleeper,
            )
        self.assertEqual(opener.call_count, 1)
        sleeper.assert_not_called()

    def test_malformed_json_is_not_retried(self) -> None:
        opener = mock.Mock(return_value=_Response(b"not-json"))
        sleeper = mock.Mock()
        with self.assertRaises(json.JSONDecodeError):
            fs._http_json(
                url=fs.TUSHARE_URL,
                opener=opener,
                sleeper=sleeper,
            )
        self.assertEqual(opener.call_count, 1)
        sleeper.assert_not_called()

    def test_invalid_attempt_count_is_refused_before_network(self) -> None:
        opener = mock.Mock()
        with self.assertRaisesRegex(ValueError, "attempts must be >= 1"):
            fs._http_json(url=fs.TUSHARE_URL, attempts=0, opener=opener)
        opener.assert_not_called()


if __name__ == "__main__":
    os.environ.setdefault("AR_OFFLINE", "1")
    unittest.main(verbosity=2)
