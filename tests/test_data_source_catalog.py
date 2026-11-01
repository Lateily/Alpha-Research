"""Offline contracts for the explicitly limited first source catalog."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
import os

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.data_governance.catalog import (  # noqa: E402
    catalog_hash, load_catalog, require_source, validate_call_context,
)

CATALOG = ROOT / "config/data-source-catalog.v1.json"
FIVE = {"tushare." + s for s in (
    "daily", "daily_basic", "moneyflow_dc", "moneyflow_ind_dc", "moneyflow_mkt_dc")}


def context(source="tushare.daily", ticker="600000.SH", call_id=None):
    return {
        "logical_call_id": call_id or "d3b02f03-a274-40fc-a46b-1d3af231a134",
        "collector_run_id": "synthetic-20261030",
        "source_id": source, "target_trade_date": "20261030", "ts_code": ticker,
        "invoked_at": "2026-10-30T16:00:00+08:00",
        "catalog_hash": catalog_hash(load_catalog(CATALOG)),
    }


class CatalogTests(unittest.TestCase):
    def test_catalog_scope_is_explicit(self):
        catalog = load_catalog(CATALOG)
        self.assertEqual(set(catalog["sources"]), FIVE)
        self.assertEqual(catalog["coverage"], "FIRST_FIVE_REQUIRED_ENDPOINTS_ONLY")
        self.assertTrue(all(v["rights_status"] == "UNVERIFIED"
                            for v in catalog["sources"].values()))
        self.assertEqual(catalog["sources"]["tushare.daily_basic"]["instrumentation"],
                         "NOT_INSTRUMENTED")

    def test_unknown_source_refused(self):
        with self.assertRaisesRegex(ValueError, "SOURCE_NOT_REGISTERED"):
            require_source(load_catalog(CATALOG), "tushare.unregistered")

    def test_unverified_rights_do_not_grant_team(self):
        value = load_catalog(CATALOG)
        for status in ("TEAM_DISPLAY_ALLOWED", "PERSONAL_ONLY"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                modified = copy.deepcopy(value)
                modified["sources"]["tushare.daily"]["rights_status"] = status
                path = Path(tmp).resolve() / "catalog.json"
                path.write_text(json.dumps(modified))
                with self.assertRaisesRegex(ValueError, "RIGHTS_EVIDENCE_REQUIRED"):
                    load_catalog(path)

    def test_strict_json_and_schema(self):
        for raw in ('{"schema": "x", "schema": "y"}', '{"x": NaN}',
                    '{"schema": "ar.data-source-catalog.v0"}'):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp).resolve() / "catalog.json"
                path.write_text(raw)
                with self.assertRaises(ValueError):
                    load_catalog(path)

    def test_context_extra_fields_refused(self):
        for name in ("token", "url", "actor"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_call_context(dict(context(), **{name: "secret"}))

    def test_context_identity_date_and_clock(self):
        valid = context()
        self.assertEqual(validate_call_context(valid), valid)
        for name, value in (("target_trade_date", "20260230"),
                            ("invoked_at", "2026-10-30T16:00:00"),
                            ("logical_call_id", "../../bad"),
                            ("source_id", "tushare.unregistered"),
                            ("catalog_hash", "x"), ("ts_code", "secret-token")):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_call_context(dict(valid, **{name: value}))

    def test_catalog_hash_is_content_bound(self):
        catalog = load_catalog(CATALOG)
        other = copy.deepcopy(catalog)
        other["sources"]["tushare.daily"]["consumers"].append("synthetic-consumer")
        self.assertNotEqual(catalog_hash(catalog), catalog_hash(other))

    def test_timestamp_errors_do_not_repeat_input(self):
        secret = "FAKE-SECRET-TIMESTAMP"
        with self.assertRaises(ValueError) as raised:
            validate_call_context(dict(context(), invoked_at=secret))
        self.assertNotIn(secret, str(raised.exception))
        self.assertEqual(str(raised.exception), "INVALID_TIMESTAMP")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO requires POSIX")
    def test_fifo_is_refused_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "catalog.json"
            os.mkfifo(path)
            code = ("from experiments.data_governance.catalog import read_json; "
                    "from pathlib import Path; read_json(Path(__import__('sys').argv[1]))")
            try:
                result = subprocess.run([sys.executable, "-B", "-c", code, str(path)],
                                        cwd=ROOT, capture_output=True, text=True, timeout=2)
            except subprocess.TimeoutExpired:
                self.fail("FIFO evidence blocked instead of rejecting nonregular input")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("EVIDENCE_NOT_REGULAR", result.stderr)

    def test_catalog_changes_trigger_its_ci_validation(self):
        workflow = (ROOT / ".github/workflows/python-ci.yml").read_text()
        pr = workflow.split("  pull_request:\n", 1)[1].split("  push:", 1)[0]
        self.assertIn('      - "config/data-source-catalog.v1.json"', pr.splitlines())
        self.assertIn("python3 -B tests/test_data_source_catalog.py", workflow)


if __name__ == "__main__":
    unittest.main()
