"""Deferred CLI contract cases. Not executed in the implementation-only batch."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/llm"))
import foundation_cli as cli


class FoundationCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def request(self, value):
        path = self.root / "request.json"
        path.write_text(json.dumps(value))
        return str(path)

    def run_cli(self, argv):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = cli.main(argv)
        return code, output.getvalue(), error.getvalue()

    def test_inventory_binds_requested_clock_and_never_claims_acceptance(self):
        filename = self.request({"repositories": {}, "services": [], "observed_at": "2026-11-01T20:00:00Z"})
        with mock.patch("foundation_runtime.collect_runtime_inventory", return_value={"schema": "ar.runtime-inventory.v1"}) as collect:
            code, output, error = self.run_cli(["inventory", "--config", filename])
        self.assertEqual((code, error), (0, ""))
        collect.assert_called_once_with({}, [], observed_at="2026-11-01T20:00:00Z",
                                        scheduler_timezone="Europe/London", market_timezone="Asia/Shanghai")
        result = json.loads(output)
        self.assertEqual(result["testing_status"], "NOT_RUN")
        self.assertFalse(result["production_authority"])

    def test_unknown_keys_are_refused_without_echo_or_backend_call(self):
        filename = self.request({"repositories": {}, "observed_at": "2026-11-01T20:00:00Z", "unexpected": "test-private-value"})
        with mock.patch("foundation_runtime.collect_runtime_inventory") as collect:
            code, output, error = self.run_cli(["inventory", "--config", filename])
        self.assertEqual((code, output), (2, ""))
        collect.assert_not_called()
        self.assertNotIn("test-private-value", error)

    def test_pin_without_explicit_write_root_only_returns_proposal(self):
        filename = self.request({"backup_root": "/synthetic/archive", "expected_backup_hash": "a" * 64,
                                 "snapshot_ids": [], "job_ids": [], "created_at": "2026-11-01T20:00:00Z"})
        with mock.patch("foundation_retention.build_retention_pin", return_value={"schema": "ar.retention-pin.v1"}), \
                mock.patch("foundation_retention.write_retention_pin") as write:
            code, output, error = self.run_cli(["pin", "--request", filename])
        self.assertEqual((code, error), (0, ""))
        write.assert_not_called()
        self.assertIsNone(json.loads(output)["result"]["write_receipt"])

    def test_unknown_command_is_a_safe_refusal(self):
        code, output, error = self.run_cli(["trade", "--unexpected", "test-private-value"])
        self.assertEqual((code, output), (2, ""))
        self.assertNotIn("test-private-value", error)

    def test_pin_write_root_cannot_be_the_archive_or_its_child(self):
        filename = self.request({"backup_root": "/synthetic/archive", "expected_backup_hash": "a" * 64,
                                 "snapshot_ids": [], "job_ids": [], "created_at": "2026-11-01T20:00:00Z"})
        for destination in ("/synthetic/archive", "/synthetic/archive/pins", "/synthetic"):
            with mock.patch("foundation_retention.build_retention_pin") as build, \
                    mock.patch("foundation_retention.write_retention_pin") as write:
                code, output, _error = self.run_cli(["pin", "--request", filename, "--write-root", destination])
            self.assertEqual((code, output), (2, ""))
            build.assert_not_called()
            write.assert_not_called()


if __name__ == "__main__": unittest.main()
