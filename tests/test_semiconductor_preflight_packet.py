#!/usr/bin/env python3
"""Offline tests for semiconductor preflight packet automation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.research_funnel import semiconductor_preflight_packet as packet  # noqa: E402

SCRIPT = ROOT / "experiments/research_funnel/semiconductor_preflight_packet.py"
CI_PATH = ROOT / ".github/workflows/python-ci.yml"
TARGET = "20260831"
SHA = "a" * 40
HASH = "1" * 64


def _source_scan(*states: tuple[str, str, str]) -> dict[str, Any]:
    rows = [
        {
            "source_name": source_name,
            "as_of": as_of,
            "original_source_hash": "2" * 64,
            "active_source_hash": "3" * 64,
            "original_row_count": 197,
            "active_row_count": 197,
            "expected_rows": 197,
            "minimum_rows": 188,
            "universe_hash": "4" * 64,
            "repair_chain_length": 0,
            "point_in_time_status": "ORIGINAL_INGESTION",
            "state": state,
        }
        for source_name, as_of, state in states
    ]
    scan = {
        "schema": "ar.semiconductor_source_repair_scan",
        "schema_version": "0.1",
        "daily_sources": ["cyq_perf", "moneyflow_dc"],
        "coverage_ratio": 0.95,
        "rows": rows,
        "authority": {
            "production_authority": False,
            "trade_authority": False,
            "claim_allowed": False,
            "no_trade_flag": True,
        },
    }
    scan["scan_hash"] = packet._hash(scan)
    return scan


def _diagnostic(*, status: str = "READY_FOR_U4_PACKET", u4_ready: bool = True) -> dict[str, Any]:
    blockers = [] if u4_ready else [{"code": "EMPTY_U4_READY_POOL", "detail": "no rows"}]
    return {
        "diagnostic_schema": "ar.semiconductor_u1_u3_diagnostic.v0",
        "source": {
            "intake_attempt_id": "semiconductor-intake-20260831",
            "method_version": "RESEARCH_CLOSED_LOOP_V1",
            "source_status": "BLOCKED_BEFORE_U4",
            "terminal_stage": "U3",
        },
        "status": status,
        "u4_ready": u4_ready,
        "counts": {
            "semiconductor_u2_rows": 75,
            "semiconductor_positive_channel_rows": 75,
            "semiconductor_red_flag_only_rows": 0,
            "semiconductor_u3_rows": 75,
            "semiconductor_u4_ready_rows": 75,
        },
        "blockers": blockers,
        "forbidden_shortcuts": [],
        "required_next_gate": [],
        "authority": {
            "selection_owner": "Junyan",
            "production_authority": False,
            "trade_authority": False,
            "claim_allowed": False,
            "no_trade_flag": True,
        },
        "disclaimer": "不是买卖指令；研究信号，human executes.",
    }


def _ready_packet(**overrides: Any) -> dict[str, Any]:
    git_status = overrides.pop("_git_status", "")
    git_origin = overrides.pop("_git_origin", SHA)
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    bundle_path = root / "same-day-bundle.json"
    battery_path = root / "u3-battery.json"
    bundle_path.write_text(
        json.dumps({"as_of": TARGET, "run_identity": "same-day-run-20260831"}),
        encoding="utf-8",
    )
    battery_path.write_text(
        json.dumps({"as_of": TARGET, "row_count": 75}),
        encoding="utf-8",
    )
    kwargs = {
        "source_scan": _source_scan(
            ("cyq_perf", TARGET, "CLEAN_ACTIVE"),
            ("moneyflow_dc", TARGET, "CLEAN_ACTIVE"),
        ),
        "source_scan_ref": "output/source-scan.json",
        "diagnostic": _diagnostic(),
        "diagnostic_ref": "output/diagnostic.json",
        "target_trade_date": TARGET,
        "prepared_at_utc": "2026-08-31T01:00:00+00:00",
        "origin_main_sha": SHA,
        "worktree_status": "CLEAN",
        "same_day_bundle_ref": str(bundle_path),
        "same_day_bundle_hash": None,
        "same_day_as_of": TARGET,
        "same_day_run_id": "same-day-run-20260831",
        "u3_battery_ref": str(battery_path),
        "u3_battery_hash": None,
        "u3_battery_as_of": TARGET,
        "u3_row_count": 75,
        "repo_root": root,
    }
    kwargs.update(overrides)

    def fake_git_output(args: list[str], repo_root: Path) -> str:
        if args == ["rev-parse", "origin/main"]:
            return git_origin
        if args == ["status", "--short"]:
            return git_status
        raise AssertionError(f"unexpected git command: {args}")

    try:
        with mock.patch.object(packet, "_git_output", side_effect=fake_git_output):
            return packet.build_packet(**kwargs)
    finally:
        temp_dir.cleanup()


class SemiconductorPreflightPacketTests(unittest.TestCase):
    def test_all_clean_inputs_allow_u1_u3_handoff_without_granting_authority(self) -> None:
        result = _ready_packet()
        self.assertEqual(result["schema"], "ar.semiconductor_rerun_operator_packet.v0")
        self.assertEqual(result["handoff_intent"], "ALLOW_U1_U3_RERUN")
        self.assertEqual(result["stop_conditions"], [])
        self.assertEqual(result["source_scan"]["status"], "CLEAN")
        self.assertEqual(result["diagnostic"]["status"], "READY_FOR_U4_PACKET")
        self.assertEqual(result["authority"]["authority"], "HUMAN_JUNYAN_ONLY")
        self.assertFalse(result["authority"]["production_authority"])
        self.assertFalse(result["authority"]["trade_authority"])
        self.assertFalse(result["authority"]["paper_order_authority"])
        self.assertTrue(result["authority"]["no_trade_flag"])
        self.assertRegex(result["packet_hash"], r"^[0-9a-f]{64}$")

    def test_pending_daily_source_stops_before_rerun(self) -> None:
        result = _ready_packet(source_scan=_source_scan(
            ("cyq_perf", TARGET, "SOURCE_PUBLICATION_PENDING"),
            ("moneyflow_dc", TARGET, "CLEAN_ACTIVE"),
        ))
        codes = {row["code"] for row in result["stop_conditions"]}
        self.assertEqual(result["handoff_intent"], "STOP_BEFORE_RERUN")
        self.assertEqual(result["worktree_status"], "CLEAN")
        self.assertEqual(result["source_scan"]["status"], "DATA_BLOCKED")
        self.assertIn("SOURCE_PUBLICATION_PENDING", codes)

    def test_each_daily_source_needs_target_date_row(self) -> None:
        result = _ready_packet(source_scan=_source_scan(
            ("cyq_perf", "20260830", "SOURCE_PUBLICATION_PENDING"),
            ("moneyflow_dc", TARGET, "CLEAN_ACTIVE"),
        ))
        codes = {row["code"] for row in result["stop_conditions"]}
        self.assertEqual(result["handoff_intent"], "STOP_BEFORE_RERUN")
        self.assertIn("DAILY_SOURCE_MISSING_TARGET_ROW", codes)

    def test_unsafe_artifact_refs_are_rejected_before_packet_build(self) -> None:
        with self.assertRaisesRegex(packet.PreflightPacketError, "unsupported characters"):
            _ready_packet(source_scan_ref="output/source-scan.json\nraw-model-text")
        with self.assertRaisesRegex(packet.PreflightPacketError, "unsupported characters"):
            _ready_packet(diagnostic_ref="raw-model-text: agent claims this is reviewed")

    def test_repair_required_stops_and_requires_exact_approval_reference(self) -> None:
        result = _ready_packet(source_scan=_source_scan(
            ("cyq_perf", TARGET, "REPAIR_REQUIRED"),
            ("moneyflow_dc", TARGET, "CLEAN_ACTIVE"),
        ))
        codes = {row["code"] for row in result["stop_conditions"]}
        self.assertEqual(result["handoff_intent"], "STOP_BEFORE_RERUN")
        self.assertEqual(result["source_scan"]["status"], "REPAIR_REQUIRED")
        self.assertIn("SOURCE_REPAIR_REQUIRED", codes)
        self.assertIn("MISSING_REPAIR_APPROVAL_REF", codes)

    def test_diagnostic_blockers_stop_before_rerun(self) -> None:
        result = _ready_packet(diagnostic=_diagnostic(status="BLOCKED_BEFORE_U4", u4_ready=False))
        codes = {row["code"] for row in result["stop_conditions"]}
        self.assertEqual(result["handoff_intent"], "STOP_BEFORE_RERUN")
        self.assertIn("INTAKE_DIAGNOSTIC_NOT_READY", codes)
        self.assertEqual(result["diagnostic"]["blocker_codes"], ["EMPTY_U4_READY_POOL"])

    def test_diagnostic_counts_force_stop_even_when_self_reported_ready(self) -> None:
        diagnostic = _diagnostic()
        diagnostic["counts"] = {
            "semiconductor_u2_rows": 75,
            "semiconductor_positive_channel_rows": 0,
            "semiconductor_red_flag_only_rows": 75,
            "semiconductor_u3_rows": 0,
            "semiconductor_u4_ready_rows": 0,
        }
        result = _ready_packet(diagnostic=diagnostic)
        codes = {row["code"] for row in result["stop_conditions"]}
        self.assertEqual(result["handoff_intent"], "STOP_BEFORE_RERUN")
        self.assertIn("RECEIPT_SELF_REPORT_MISMATCH", codes)
        self.assertIn("NO_POSITIVE_CHANNEL_ROWS", codes)
        self.assertIn("RED_FLAG_ONLY_COHORT", codes)
        self.assertIn("NO_SAME_RUN_U3_BATTERY", codes)
        self.assertIn("EMPTY_U4_READY_POOL", codes)

    def test_diagnostic_reported_blockers_force_stop_even_when_ready(self) -> None:
        diagnostic = _diagnostic()
        diagnostic["blockers"] = [{"code": "E1_RED_FLAG_ACTIVE", "detail": "active red flag"}]
        result = _ready_packet(diagnostic=diagnostic)
        codes = {row["code"] for row in result["stop_conditions"]}
        self.assertEqual(result["handoff_intent"], "STOP_BEFORE_RERUN")
        self.assertIn("INTAKE_DIAGNOSTIC_HAS_BLOCKERS", codes)
        self.assertIn("RECEIPT_SELF_REPORT_MISMATCH", codes)

    def test_missing_same_day_artifacts_still_generates_stop_packet(self) -> None:
        result = _ready_packet(
            same_day_bundle_ref=None,
            same_day_bundle_hash=None,
            same_day_as_of=None,
            u3_battery_ref=None,
            u3_battery_hash=None,
            u3_row_count=None,
        )
        codes = {row["code"] for row in result["stop_conditions"]}
        self.assertEqual(result["handoff_intent"], "STOP_BEFORE_RERUN")
        self.assertIn("SAME_DAY_BUNDLE_MISSING", codes)
        self.assertIn("U3_BATTERY_MISSING", codes)

    def test_same_day_bundle_must_match_target_trade_date(self) -> None:
        result = _ready_packet(same_day_as_of="20260828")
        codes = {row["code"] for row in result["stop_conditions"]}
        self.assertEqual(result["handoff_intent"], "STOP_BEFORE_RERUN")
        self.assertIn("SAME_DAY_BUNDLE_DATE_MISMATCH", codes)

    def test_same_day_bundle_hash_is_recomputed_from_readable_file(self) -> None:
        result = _ready_packet(same_day_bundle_hash="sha256:" + "d" * 64)
        codes = {row["code"] for row in result["stop_conditions"]}
        self.assertEqual(result["handoff_intent"], "STOP_BEFORE_RERUN")
        self.assertIn("SAME_DAY_BUNDLE_UNVERIFIED", codes)
        self.assertNotEqual(result["same_day_bundle"]["hash"], "sha256:" + "d" * 64)

    def test_u3_battery_must_bind_target_trade_date(self) -> None:
        result = _ready_packet(u3_battery_as_of="20260828")
        codes = {row["code"] for row in result["stop_conditions"]}
        self.assertEqual(result["handoff_intent"], "STOP_BEFORE_RERUN")
        self.assertIn("U3_BATTERY_DATE_MISMATCH", codes)

    def test_u3_battery_row_count_must_be_positive_to_allow(self) -> None:
        result = _ready_packet(u3_row_count=0)
        codes = {row["code"] for row in result["stop_conditions"]}
        self.assertEqual(result["handoff_intent"], "STOP_BEFORE_RERUN")
        self.assertIn("U3_BATTERY_EMPTY", codes)

    def test_git_metadata_must_match_real_observed_values(self) -> None:
        with self.assertRaisesRegex(packet.PreflightPacketError, "origin_main_sha does not match"):
            _ready_packet(origin_main_sha="f" * 40)
        with self.assertRaisesRegex(packet.PreflightPacketError, "worktree_status does not match"):
            _ready_packet(_git_status=" M docs/example.md", worktree_status="CLEAN")

    def test_dirty_worktree_is_reported_in_stop_packet(self) -> None:
        result = _ready_packet(_git_status=" M docs/example.md", worktree_status=None)
        codes = {row["code"] for row in result["stop_conditions"]}
        self.assertEqual(result["handoff_intent"], "STOP_BEFORE_RERUN")
        self.assertIn("WORKTREE_NOT_CLEAN", codes)
        self.assertEqual(result["worktree_dirty_files"], [" M docs/example.md"])

    def test_source_scan_hash_must_recompute(self) -> None:
        scan = _source_scan(("cyq_perf", TARGET, "CLEAN_ACTIVE"))
        scan["rows"][0]["state"] = "REPAIR_REQUIRED"
        with self.assertRaisesRegex(packet.PreflightPacketError, "hash does not recompute"):
            _ready_packet(source_scan=scan)

    def test_diagnostic_authority_cannot_be_escalated(self) -> None:
        diagnostic = _diagnostic()
        diagnostic["authority"]["trade_authority"] = True
        with self.assertRaisesRegex(packet.PreflightPacketError, "authority boundary changed"):
            _ready_packet(diagnostic=diagnostic)

    def test_cli_writes_lf_json_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git_root = root / "git-root"
            git_root.mkdir()
            subprocess.run(["git", "init"], cwd=git_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "ci@example.test"], cwd=git_root, check=True)
            subprocess.run(["git", "config", "user.name", "CI"], cwd=git_root, check=True)
            (git_root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=git_root, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=git_root, check=True, capture_output=True, text=True)
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=git_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "update-ref", "refs/remotes/origin/main", head],
                cwd=git_root,
                check=True,
            )
            scan_path = root / "scan.json"
            diagnostic_path = root / "diagnostic.json"
            bundle_path = root / "same-day-bundle.json"
            battery_path = root / "u3-battery.json"
            out_path = root / "packet.json"
            scan_path.write_text(json.dumps(_source_scan(
                ("cyq_perf", TARGET, "CLEAN_ACTIVE"),
                ("moneyflow_dc", TARGET, "CLEAN_ACTIVE"),
            )), encoding="utf-8")
            diagnostic_path.write_text(json.dumps(_diagnostic()), encoding="utf-8")
            bundle_path.write_text(
                json.dumps({"as_of": TARGET, "run_identity": "same-day-run-20260831"}),
                encoding="utf-8",
            )
            battery_path.write_text(json.dumps({"as_of": TARGET, "row_count": 75}), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-scan",
                    str(scan_path),
                    "--diagnostic",
                    str(diagnostic_path),
                    "--target-trade-date",
                    TARGET,
                    "--prepared-at-utc",
                    "2026-08-31T01:00:00+00:00",
                    "--origin-main-sha",
                    head,
                    "--worktree-status",
                    "CLEAN",
                    "--same-day-bundle-ref",
                    str(bundle_path),
                    "--same-day-as-of",
                    TARGET,
                    "--same-day-run-id",
                    "same-day-run-20260831",
                    "--u3-battery-ref",
                    str(battery_path),
                    "--u3-battery-as-of",
                    TARGET,
                    "--u3-row-count",
                    "75",
                    "--repo-root",
                    str(git_root),
                    "--output",
                    str(out_path),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.stdout, "")
            raw = out_path.read_bytes()
            self.assertNotIn(b"\r\n", raw)
            payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(payload["handoff_intent"], "ALLOW_U1_U3_RERUN")

    def test_ci_runs_preflight_packet_tests(self) -> None:
        ci = CI_PATH.read_text(encoding="utf-8")
        self.assertIn("python3 tests/test_semiconductor_preflight_packet.py", ci)


if __name__ == "__main__":
    unittest.main(verbosity=2)
