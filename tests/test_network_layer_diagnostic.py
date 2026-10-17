#!/usr/bin/env python3
"""Offline tests for execution-environment network layer diagnostics."""

from __future__ import annotations

import socket
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import network_layer_diagnostic as diagnostic  # noqa: E402


def _pass(_endpoint):
    return {"detail": "reached"}


class NetworkLayerDiagnosticTests(unittest.TestCase):
    def test_reached_http_status_does_not_collide_with_layer_status(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 204
        with mock.patch.object(diagnostic.urllib.request, "urlopen", return_value=response):
            receipt = diagnostic.probe_endpoint(
                "https://example.invalid/calendar",
                execution_context="HOST_TERMINAL",
                environment={},
                proxy_map={},
                dns_probe=_pass,
                tcp_probe=_pass,
                tls_probe=_pass,
            )

        self.assertEqual("PASS", receipt["status"])
        self.assertEqual("PASS", receipt["layers"][-1]["status"])
        self.assertEqual(204, receipt["layers"][-1]["response_status"])

    def test_dns_failure_is_scoped_to_execution_environment(self) -> None:
        calls = []

        def dns(_endpoint):
            calls.append("dns")
            raise socket.gaierror(-2, "fixture name resolution failure")

        receipt = diagnostic.probe_endpoint(
            "https://example.invalid/calendar",
            execution_context="CODEX_SANDBOX",
            environment={},
            proxy_map={},
            dns_probe=dns,
            tcp_probe=lambda endpoint: calls.append("tcp"),
            tls_probe=lambda endpoint: calls.append("tls"),
            http_probe=lambda endpoint: calls.append("http"),
        )

        self.assertEqual("BLOCKED", receipt["status"])
        self.assertEqual("DNS_RESOLUTION", receipt["failure_layer"])
        self.assertEqual(
            "UNCONFIRMED_BEYOND_THIS_EXECUTION_ENVIRONMENT",
            receipt["cause_attribution"],
        )
        self.assertEqual(["dns"], calls)
        self.assertNotIn("fixture name resolution failure", str(receipt))

    def test_offline_policy_stops_before_any_network_probe(self) -> None:
        calls = []
        receipt = diagnostic.probe_endpoint(
            "https://example.invalid/calendar",
            execution_context="CODEX_SANDBOX",
            environment={"AR_OFFLINE": "1"},
            proxy_map={},
            dns_probe=lambda endpoint: calls.append("dns"),
            tcp_probe=lambda endpoint: calls.append("tcp"),
            tls_probe=lambda endpoint: calls.append("tls"),
            http_probe=lambda endpoint: calls.append("http"),
        )

        self.assertEqual("EXECUTION_POLICY", receipt["failure_layer"])
        self.assertEqual([], calls)

    def test_proxy_metadata_is_redacted(self) -> None:
        receipt = diagnostic.probe_endpoint(
            "https://example.invalid/calendar",
            execution_context="HOST_TERMINAL",
            environment={},
            proxy_map={"https": "http://user:secret@127.0.0.1:7890/private?token=x"},
            dns_probe=_pass,
            tcp_probe=_pass,
            tls_probe=_pass,
            http_probe=_pass,
        )

        self.assertEqual("PASS", receipt["status"])
        self.assertEqual(
            {"scheme": "http", "host": "127.0.0.1", "port": 7890},
            receipt["proxy"]["routes"]["https"],
        )
        self.assertNotIn("secret", str(receipt))
        self.assertNotIn("token=x", str(receipt))

    def test_compare_detects_execution_environment_difference(self) -> None:
        blocked = diagnostic.probe_endpoint(
            "https://example.invalid/calendar",
            execution_context="CODEX_SANDBOX",
            environment={},
            proxy_map={},
            dns_probe=lambda endpoint: (_ for _ in ()).throw(socket.gaierror()),
            tcp_probe=_pass,
            tls_probe=_pass,
            http_probe=_pass,
        )
        reached = diagnostic.probe_endpoint(
            "https://example.invalid/calendar",
            execution_context="HOST_TERMINAL",
            environment={},
            proxy_map={},
            dns_probe=_pass,
            tcp_probe=_pass,
            tls_probe=_pass,
            http_probe=_pass,
        )

        comparison = diagnostic.compare_receipts(blocked, reached)

        self.assertEqual("EXECUTION_ENVIRONMENT_PATH_DIFFERENCE", comparison["finding"])
        self.assertFalse(comparison["host_dns_failure_confirmed"])

    def test_endpoint_rejects_secret_bearing_or_non_https_urls(self) -> None:
        for url in (
            "http://example.com/calendar",
            "https://user:secret@example.com/calendar",
            "https://example.com/calendar?token=secret",
        ):
            with self.subTest(url=url):
                with self.assertRaises(diagnostic.DiagnosticError):
                    diagnostic.probe_endpoint(url, execution_context="TEST")


if __name__ == "__main__":
    unittest.main(verbosity=2)
