#!/usr/bin/env python3
"""Offline behavioral tests for scheduled-nightly acceptance."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
ET = REPO_ROOT / "experiments" / "execution_tracker"
sys.path.insert(0, str(ET))

import nightly_acceptance as acceptance  # noqa: E402
import run_nightly  # noqa: E402


TARGET = "20260817"
RUN_ID = "20260817_163500_1787042100000000000_abcdef12"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class AcceptanceFixture:
    def __init__(self, root: Path):
        self.root = root
        self.start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=30)
        self.log = root / "tmp" / "ar-nightly.log"
        self.alarm = root / "tmp" / "ar-nightly-incomplete"
        self.plist = root / "Library" / "LaunchAgents" / "com.ar.nightly.plist"
        self.state = root / "launchctl.txt"
        self.et = root / "experiments" / "execution_tracker"
        self.health_path = root / "public" / "data" / "v2" / "funnel_health.json"
        self.bundle = root / "data_history" / "funnel" / TARGET / RUN_ID
        self._write_valid()

    def _write_valid(self) -> None:
        self.log.parent.mkdir(parents=True)
        self.log.write_text(
            "old run output\nresearch_funnel: OK\n"
            f"[run] run_id={RUN_ID} target_trade_date={TARGET}\n"
            "official_sample: OK\nresearch_funnel: OK\n"
            f"[report] COMPLETE  data_quality=PARTIAL  run_id={RUN_ID}  target={TARGET}\n",
            encoding="utf-8",
        )
        self.bundle.mkdir(parents=True)
        write_json(self.bundle / "manifest.json", {"schema": "fixture"})
        write_json(self.et / "nightly_run.json", {
            "run_id": RUN_ID,
            "target_trade_date": TARGET,
            "report": "COMPLETE",
            "published": True,
            "steps": [{"step": "research_funnel", "status": "OK"}],
        })
        write_json(self.health_path, {
            "run_id": RUN_ID,
            "target_trade_date": TARGET,
            "bundle": {"location": f"data_history/funnel/{TARGET}/{RUN_ID}"},
        })
        self.plist.parent.mkdir(parents=True)
        wrapper = self.et / "launchd" / "ar_env_wrapper.sh"
        runner = self.et / "run_nightly.py"
        with self.plist.open("wb") as fh:
            plistlib.dump({
                "Label": "com.ar.nightly",
                "ProgramArguments": [str(wrapper), "/usr/bin/python3", str(runner)],
                "StandardOutPath": str(self.log),
                "StartCalendarInterval": [
                    {"Weekday": weekday, "Hour": 16, "Minute": 35}
                    for weekday in range(1, 6)
                ],
            }, fh)
        self.state.write_text(
            "gui/501/com.ar.nightly = {\n"
            "\truns = 12\n"
            "\tlast exit code = 0\n"
            "}\n",
            encoding="utf-8",
        )

    def inputs(self) -> acceptance.Inputs:
        return acceptance.Inputs(
            repo_root=self.root,
            expected_start=self.start,
            expected_target=TARGET,
            runs_before=11,
            log_path=self.log,
            alarm_path=self.alarm,
            plist_path=self.plist,
            launchd_label="com.ar.nightly",
            launchctl_state_file=self.state,
        )


class NightlyAcceptanceTests(unittest.TestCase):
    def test_clean_scheduled_run_produces_pass_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = AcceptanceFixture(Path(tmp))
            with mock.patch.object(run_nightly, "_validate_funnel_health") as verifier:
                receipt = acceptance.audit(fixture.inputs())
            self.assertEqual("PASS", receipt["status"])
            self.assertTrue(all(row["status"] == "PASS" for row in receipt["checks"]))
            verifier.assert_called_once()
            self.assertEqual(
                "FILESYSTEM_AND_LAUNCHCTL_PROXY_NOT_PROCESS_ATTESTATION",
                receipt["evidence_strength"],
            )

    def test_old_funnel_ok_before_exact_run_marker_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = AcceptanceFixture(Path(tmp))
            fixture.log.write_text(
                "research_funnel: OK\n"
                f"[run] run_id={RUN_ID} target_trade_date={TARGET}\n"
                f"[report] COMPLETE  data_quality=PARTIAL  "
                f"run_id={RUN_ID}  target={TARGET}\n",
                encoding="utf-8",
            )
            with mock.patch.object(run_nightly, "_validate_funnel_health"):
                receipt = acceptance.audit(fixture.inputs())
            rows = {row["name"]: row for row in receipt["checks"]}
            self.assertEqual("FAIL", receipt["status"])
            self.assertEqual("FAIL", rows["exact_run_log_segment"]["status"])

    def test_later_run_cannot_supply_evidence_for_the_expected_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = AcceptanceFixture(Path(tmp))
            fixture.log.write_text(
                f"[run] run_id={RUN_ID} target_trade_date={TARGET}\n"
                "official_sample: OK\n"
                "[report] COMPLETE  data_quality=PARTIAL  "
                f"run_id={RUN_ID}  target={TARGET}\n"
                "[run] run_id=later_run target_trade_date=20260818\n"
                "research_funnel: OK\n"
                "[report] COMPLETE  data_quality=PARTIAL  "
                "run_id=later_run  target=20260818\n",
                encoding="utf-8",
            )
            with mock.patch.object(run_nightly, "_validate_funnel_health"):
                receipt = acceptance.audit(fixture.inputs())
            rows = {row["name"]: row for row in receipt["checks"]}
            self.assertEqual("FAIL", rows["exact_run_log_segment"]["status"])

    def test_launchd_counter_must_advance_and_exit_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = AcceptanceFixture(Path(tmp))
            fixture.state.write_text("runs = 11\nlast exit code = 0\n", encoding="utf-8")
            with mock.patch.object(run_nightly, "_validate_funnel_health"):
                receipt = acceptance.audit(fixture.inputs())
            rows = {row["name"]: row for row in receipt["checks"]}
            self.assertEqual("FAIL", rows["launchd_process_state"]["status"])

    def test_launchd_nonzero_exit_is_rejected_after_counter_advanced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = AcceptanceFixture(Path(tmp))
            fixture.state.write_text("runs = 12\nlast exit code = 1\n", encoding="utf-8")
            with mock.patch.object(run_nightly, "_validate_funnel_health"):
                receipt = acceptance.audit(fixture.inputs())
            rows = {row["name"]: row for row in receipt["checks"]}
            self.assertEqual("FAIL", rows["launchd_process_state"]["status"])

    def test_plist_must_use_wrapper_and_exact_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = AcceptanceFixture(Path(tmp))
            with fixture.plist.open("rb") as fh:
                payload = plistlib.load(fh)
            payload["ProgramArguments"][0] = "/tmp/bypass-wrapper.sh"
            with fixture.plist.open("wb") as fh:
                plistlib.dump(payload, fh)
            with mock.patch.object(run_nightly, "_validate_funnel_health"):
                receipt = acceptance.audit(fixture.inputs())
            rows = {row["name"]: row for row in receipt["checks"]}
            self.assertEqual("FAIL", rows["launchd_plist_binding"]["status"])

    def test_alarm_flag_is_never_accepted_as_a_clean_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = AcceptanceFixture(Path(tmp))
            fixture.alarm.write_text("incomplete", encoding="utf-8")
            with mock.patch.object(run_nightly, "_validate_funnel_health"):
                receipt = acceptance.audit(fixture.inputs())
            rows = {row["name"]: row for row in receipt["checks"]}
            self.assertEqual("FAIL", rows["no_incomplete_alarm"]["status"])

    def test_funnel_health_must_survive_the_production_bundle_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = AcceptanceFixture(Path(tmp))
            with mock.patch.object(
                run_nightly,
                "_validate_funnel_health",
                side_effect=ValueError("injected bundle drift"),
            ):
                receipt = acceptance.audit(fixture.inputs())
            rows = {row["name"]: row for row in receipt["checks"]}
            self.assertEqual("FAIL", rows["nightly_and_funnel_artifacts"]["status"])
            self.assertIn("bundle drift", rows["nightly_and_funnel_artifacts"]["error"])

    def test_run_and_health_must_bind_the_same_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = AcceptanceFixture(Path(tmp))
            health = json.loads(fixture.health_path.read_text(encoding="utf-8"))
            health["run_id"] = RUN_ID + "_other"
            write_json(fixture.health_path, health)
            with mock.patch.object(run_nightly, "_validate_funnel_health"):
                receipt = acceptance.audit(fixture.inputs())
            rows = {row["name"]: row for row in receipt["checks"]}
            self.assertEqual("FAIL", rows["nightly_and_funnel_artifacts"]["status"])

    def test_terminal_report_emits_run_marker_before_step_lines(self) -> None:
        result = {
            "run_id": RUN_ID,
            "target_trade_date": TARGET,
            "report": "COMPLETE",
            "data_quality": "PARTIAL",
            "steps": [{"step": "research_funnel", "status": "OK"}],
        }
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            run_nightly._print_terminal_report(result, output_path="nightly_run.json")
        lines = stream.getvalue().splitlines()
        self.assertEqual(f"[run] run_id={RUN_ID} target_trade_date={TARGET}", lines[0])
        self.assertEqual("research_funnel: OK", lines[1])
        self.assertTrue(lines[2].startswith("[report] COMPLETE"))

    def test_strict_json_rejects_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.json"
            path.write_text('{"run_id":"one","run_id":"two"}', encoding="utf-8")
            with self.assertRaisesRegex(acceptance.AcceptanceError, "duplicate JSON key"):
                acceptance._load_json(path)


if __name__ == "__main__":
    unittest.main()
