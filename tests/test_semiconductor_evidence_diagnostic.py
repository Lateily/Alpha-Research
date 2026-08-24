#!/usr/bin/env python3
"""Behavioral tests for the semiconductor U1-U3 evidence diagnostic."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))

import semiconductor_evidence_diagnostic as diag  # noqa: E402


INTAKE_PATH = (
    ROOT
    / "docs"
    / "research"
    / "prospective"
    / "semiconductor_workflow_debug_001_20260820.json"
)
SCRIPT_PATH = ROOT / "experiments" / "research_funnel" / "semiconductor_evidence_diagnostic.py"


def _load_fixture() -> dict:
    return json.loads(INTAKE_PATH.read_text(encoding="utf-8"))


class SemiconductorEvidenceDiagnosticTests(unittest.TestCase):
    def test_current_intake_stops_before_u4_without_trade_authority(self) -> None:
        result = diag.build_diagnostic(_load_fixture())
        self.assertEqual(result["diagnostic_schema"], diag.DIAGNOSTIC_SCHEMA)
        self.assertEqual(result["status"], "BLOCKED_BEFORE_U4")
        self.assertFalse(result["u4_ready"])
        self.assertEqual(result["counts"]["semiconductor_u2_rows"], 25)
        self.assertEqual(result["counts"]["semiconductor_positive_channel_rows"], 0)
        self.assertEqual(result["counts"]["semiconductor_u3_rows"], 0)
        self.assertEqual(result["counts"]["semiconductor_u4_ready_rows"], 0)
        self.assertEqual(
            result["authority"],
            {
                "selection_owner": "Junyan",
                "production_authority": False,
                "trade_authority": False,
                "claim_allowed": False,
                "no_trade_flag": True,
            },
        )
        self.assertEqual(result["disclaimer"], diag.DISCLAIMER)
        codes = {row["code"] for row in result["blockers"]}
        self.assertIn("RED_FLAG_ONLY_COHORT", codes)
        self.assertIn("NO_POSITIVE_CHANNEL_ROWS", codes)
        self.assertIn("NO_SAME_RUN_U3_BATTERY", codes)
        self.assertIn("EMPTY_U4_READY_POOL", codes)
        self.assertIn("UPSTREAM_CHANNEL_GAPS", codes)

    def test_authority_promotion_is_rejected(self) -> None:
        fixture = _load_fixture()
        for field, bad in (
            ("production_authority", True),
            ("trade_authority", True),
            ("claim_allowed", True),
            ("no_trade_flag", False),
        ):
            mutated = copy.deepcopy(fixture)
            mutated["authority"][field] = bad
            with self.subTest(field=field):
                with self.assertRaisesRegex(diag.DiagnosticError, "authority boundary changed"):
                    diag.build_diagnostic(mutated)

    def test_registered_cycle_is_rejected(self) -> None:
        fixture = _load_fixture()
        mutated = copy.deepcopy(fixture)
        mutated["prospective_case"]["cycle_registered"] = True
        with self.assertRaisesRegex(diag.DiagnosticError, "already crossed pre-U4 boundary"):
            diag.build_diagnostic(mutated)

    def test_malformed_counts_fail_closed(self) -> None:
        fixture = _load_fixture()
        mutated = copy.deepcopy(fixture)
        mutated["screening_result"]["semiconductor_u3_rows"] = -1
        with self.assertRaisesRegex(diag.DiagnosticError, "nonnegative integer"):
            diag.build_diagnostic(mutated)

    def test_ready_state_requires_at_least_three_u4_ready_rows(self) -> None:
        fixture = _load_fixture()
        fixture["screening_result"]["semiconductor_positive_channel_rows"] = 4
        fixture["screening_result"]["semiconductor_red_flag_only_rows"] = 0
        fixture["screening_result"]["semiconductor_u3_rows"] = 4
        fixture["screening_result"]["semiconductor_u4_ready_rows"] = 4
        fixture["source_bindings"]["funnel_health"]["degraded_channels"] = {
            channel: 0
            for channel in fixture["source_bindings"]["funnel_health"]["degraded_channels"]
        }
        result = diag.build_diagnostic(fixture)
        self.assertEqual(result["status"], "READY_FOR_U4_PACKET")
        self.assertTrue(result["u4_ready"])

    def test_degraded_channels_block_ready_status(self) -> None:
        fixture = _load_fixture()
        fixture["screening_result"]["semiconductor_positive_channel_rows"] = 4
        fixture["screening_result"]["semiconductor_red_flag_only_rows"] = 0
        fixture["screening_result"]["semiconductor_u3_rows"] = 4
        fixture["screening_result"]["semiconductor_u4_ready_rows"] = 4
        result = diag.build_diagnostic(fixture)
        self.assertEqual(result["status"], "BLOCKED_BEFORE_U4")
        self.assertFalse(result["u4_ready"])
        self.assertIn("UPSTREAM_CHANNEL_GAPS", {row["code"] for row in result["blockers"]})

    def test_cli_writes_deterministic_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "diagnostic.json"
            subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--intake", str(INTAKE_PATH), "--output", str(output)],
                check=True,
            )
            first = output.read_text(encoding="utf-8")
            subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--intake", str(INTAKE_PATH), "--output", str(output)],
                check=True,
            )
            self.assertEqual(first, output.read_text(encoding="utf-8"))
            payload = json.loads(first)
            self.assertEqual(payload["status"], "BLOCKED_BEFORE_U4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
