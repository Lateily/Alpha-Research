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

    def test_material_ingest_requires_an_explicit_nonoverlapping_write_root(self):
        filename = self.request({"source_root": "/synthetic/source", "manifest": {}})
        for tail in ([], ["--write-root", "/synthetic/source"], ["--write-root", "/synthetic/source/library"],
                     ["--write-root", "/synthetic"]):
            with mock.patch("foundation_materials.ingest_material") as ingest:
                code, output, _error = self.run_cli(["material-ingest", "--request", filename, *tail])
            self.assertEqual((code, output), (2, ""))
            ingest.assert_not_called()

    def test_coverage_and_material_query_do_not_ingest_or_dispatch(self):
        with mock.patch("foundation_sources.build_source_coverage", return_value={"schema": "coverage"}) as coverage:
            code, output, error = self.run_cli(["sources", "--repository", "/synthetic/repository"])
        self.assertEqual((code, error), (0, ""))
        coverage.assert_called_once_with("/synthetic/repository", inventory_path=None)
        self.assertFalse(json.loads(output)["deployment_authority"])
        with mock.patch("foundation_materials.query_library", return_value={"schema": "query"}) as query:
            code, _output, error = self.run_cli(["materials", "--library-root", "/synthetic/library", "--industry", "semiconductors",
                                                "--date", "20261029", "--ticker", "002119.SZ"])
        self.assertEqual((code, error), (0, ""))
        query.assert_called_once_with("/synthetic/library", industry_key="semiconductors", trade_date="20261029", ts_code="002119.SZ")

    def test_preservation_and_reconciliation_are_read_only_request_routes(self):
        rows = (("preservation", "foundation_preservation.build_preservation_manifest",
                 {"packages": [], "created_at": "2026-11-02T10:00:00Z"}),
                ("preservation-verify", "foundation_preservation.verify_preservation_copy",
                 {"manifest": {}, "package_roots": {}, "expected_preservation_hash": "a" * 64}),
                ("reconcile", "foundation_release.reconcile_deployments", {"inventory": {}, "release": {}}))
        for command, function, value in rows:
            filename = self.request(value)
            with mock.patch(function, return_value={"schema": "stub"}) as operation:
                code, output, error = self.run_cli([command, "--request", filename])
            self.assertEqual((code, error), (0, ""))
            operation.assert_called_once()
            self.assertEqual(json.loads(output)["testing_status"], "NOT_RUN")
            value["upload"] = True; filename = self.request(value)
            with mock.patch(function) as operation:
                code, output, _error = self.run_cli([command, "--request", filename])
            self.assertEqual((code, output), (2, ""))
            operation.assert_not_called()


if __name__ == "__main__": unittest.main()
