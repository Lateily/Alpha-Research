#!/usr/bin/env python3
"""Offline production-wiring tests for Macro OS M1-C."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ET = ROOT / "experiments" / "execution_tracker"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ET) not in sys.path:
    sys.path.insert(0, str(ET))

from experiments.macro_os import contracts, m0b2, m0b3, m1c  # noqa: E402
from experiments.macro_os.storage import MacroHistoryStore  # noqa: E402
import nightly_publish  # noqa: E402
import run_nightly as nightly  # noqa: E402


NOW = datetime(2026, 8, 9, 8, 35, tzinfo=timezone.utc)
TARGET = "20260809"
RUN_ID = "nightly_macro_fixture"


class BlockedTransport:
    def fetch(self, _request):
        raise m1c.collectors.CollectionError(
            "DATA_BLOCKED", "TEST_OFFLINE", "offline fixture blocks network"
        )


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def portfolio(run_id: str = RUN_ID, target: str = TARGET) -> dict:
    return {
        "contract": "model_portfolio_state",
        "schema_version": "v2.2",
        "generated_at": "20260809 08:30:00",
        "run_id": run_id,
        "target_trade_date": target,
        "sources": ["fixture/fund.json"],
        "sources_meta": {},
        "status": "OK",
        "pipeline_status": "OK",
        "data_quality": "COMPLETE",
        "degraded_sources": [],
        "blocked_why": None,
        "data": {
            "paper_only": True,
            "initial_capital": 1000000.0,
            "cash": 850000.0,
            "nav_series": [],
            "nav_latest": {
                "date": target,
                "nav": 1000000.0,
                "cash": 850000.0,
                "n_positions": 1,
                "daily_return": 0.0,
                "cum_return": 0.0,
            },
            "open_positions": [
                {
                    "entry_id": "fixture_1",
                    "ticker": "002714.SZ",
                    "name": "牧原股份",
                    "theme": "生猪",
                    "notional": 150000.0,
                    "status": "filled",
                }
            ],
            "closed_trades": [],
            "closed_trades_n": 0,
            "win_rate_note": "n<30",
        },
        "disclaimer": m1c.DISCLAIMER,
    }


class MacroM1CRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "macro.sqlite3"
        self.output = self.root / "public" / "data" / "v2" / "macro"
        self.portfolio = self.root / "public" / "data" / "v2" / "model_portfolio_state.json"
        MacroHistoryStore(self.db).initialize()
        write_json(self.portfolio, portfolio())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_m1c(self) -> dict:
        return m1c.run(
            db_path=self.db,
            output_dir=self.output,
            portfolio_path=self.portfolio,
            calendar_path=self.output / "release_calendar.json",
            market_features_path=None,
            as_of=NOW,
            run_id=RUN_ID,
            target_trade_date=TARGET,
            transport=BlockedTransport(),
        )

    def test_missing_calendar_publishes_honest_calibrating_package(self) -> None:
        manifest = self.run_m1c()
        self.assertEqual("OK", manifest["pipeline_status"])
        self.assertEqual("DATA_BLOCKED", manifest["data_quality"])
        self.assertEqual("REFRESHED", manifest["components"]["m0b"]["status"])
        self.assertEqual("DATA_BLOCKED", manifest["components"]["m0b"]["data_quality"])
        self.assertEqual("DATA_BLOCKED", manifest["components"]["m0b3"]["status"])
        self.assertEqual("RELEASE_CALENDAR_NOT_PUBLISHED", manifest["components"]["m0b3"]["reason"])
        self.assertEqual(RUN_ID, manifest["components"]["m1a"]["run_id"])
        self.assertEqual(RUN_ID, manifest["components"]["m1b"]["run_id"])
        self.assertFalse(manifest["risk_budget_annotation"]["enforceable"])
        self.assertFalse(manifest["risk_budget_annotation"]["formal_blocking_authority"])
        self.assertEqual("UNCHANGED", manifest["risk_budget_annotation"]["new_position_ceiling"])
        self.assertEqual(
            "CALIBRATION_NO_MACRO_EVIDENCE",
            manifest["risk_budget_annotation"]["reason"],
        )
        self.assertEqual(manifest, m1c.validate_run(self.output))
        schema = contracts.load_json(m1c.REPO_ROOT / "experiments" / "macro_os" / "schemas" / "m1c_run_manifest.schema.json")
        self.assertEqual(set(manifest), set(schema["required"]))
        self.assertEqual(set(manifest), set(schema["properties"]))

    def test_manifest_detects_child_artifact_mutation(self) -> None:
        self.run_m1c()
        panel_path = self.output / "macro_panel.json"
        panel = contracts.load_json(panel_path)
        panel["data"]["mrg"]["formal_state"] = "RISK_OFF_BIAS"
        write_json(panel_path, panel)
        with self.assertRaisesRegex(m1c.M1CError, "hash-mismatched"):
            m1c.validate_run(self.output)

    def test_any_blocked_component_dominates_top_level_quality(self) -> None:
        self.assertEqual(
            "DATA_BLOCKED",
            m1c._aggregate_quality(
                ["COMPLETE", "DATA_BLOCKED", "DATA_BLOCKED", "DATA_BLOCKED"]
            ),
        )

    def test_child_manifests_must_share_current_snapshot_and_sources(self) -> None:
        self.run_m1c()
        m1a_manifest = contracts.load_json(self.output / "m1a_run_manifest.json")
        m1b_manifest = contracts.load_json(self.output / "m1b_run_manifest.json")
        wrong_time = dict(m1a_manifest, as_of="2026-08-09T08:34:59Z")
        with mock.patch.object(m1c.m1a, "validate_run", return_value=wrong_time):
            with self.assertRaisesRegex(m1c.M1CError, "point-in-time snapshot"):
                m1c.validate_run(self.output)

        wrong_source = dict(m1b_manifest, source_portfolio_run_id="OLD_RUN")
        with mock.patch.object(m1c.m1b, "validate_run", return_value=wrong_source):
            with self.assertRaisesRegex(m1c.M1CError, "source bundle"):
                m1c.validate_run(self.output)

    def test_empty_but_valid_release_calendar_runs_real_m0b3_component(self) -> None:
        calendar = m0b2.build_release_calendar(
            [], generated_at="2026-08-09T08:30:00Z", run_id="calendar_fixture"
        )
        m0b2.write_json(self.output / "release_calendar.json", calendar)
        manifest = m1c.run(
            db_path=self.db,
            output_dir=self.output,
            portfolio_path=self.portfolio,
            calendar_path=self.output / "release_calendar.json",
            market_features_path=None,
            as_of=NOW,
            run_id=RUN_ID,
            target_trade_date=TARGET,
            force_collection=True,
            transport=BlockedTransport(),
        )
        self.assertEqual("REFRESHED", manifest["components"]["m0b3"]["status"])
        self.assertEqual(RUN_ID, manifest["components"]["m0b3"]["run_id"])
        self.assertEqual(
            {"release_discovery_status.json", "scheduler_status.json", "m0b3_run_manifest.json"},
            set(manifest["components"]["m0b3"]["artifacts"]),
        )
        self.assertEqual(manifest, m1c.validate_run(self.output))

    def test_m0b3_nightly_uses_the_standalone_lock_resolver(self) -> None:
        calendar = m0b2.build_release_calendar(
            [], generated_at="2026-08-09T08:30:00Z", run_id="calendar_fixture"
        )
        m0b2.write_json(self.output / "release_calendar.json", calendar)
        with mock.patch.object(
            m1c.m0b3,
            "lock_path_for_db",
            wraps=m1c.m0b3.lock_path_for_db,
        ) as resolver:
            self.run_m1c()
        resolver.assert_called_once_with(self.db)
        self.assertEqual(
            self.db.parent / m0b3.DEFAULT_LOCK.name,
            m0b3.lock_path_for_db(self.db),
        )

    def test_portfolio_must_belong_to_current_nightly_run_and_target(self) -> None:
        write_json(self.portfolio, portfolio(run_id="OLD_RUN"))
        with self.assertRaisesRegex(m1c.M1CError, "current nightly run"):
            self.run_m1c()
        write_json(self.portfolio, portfolio(target="20260808"))
        with self.assertRaisesRegex(m1c.M1CError, "target_trade_date"):
            self.run_m1c()

    def test_calibration_authority_cannot_be_promoted(self) -> None:
        manifest = self.run_m1c()
        promoted = copy.deepcopy(manifest)
        promoted["risk_budget_annotation"]["enforceable"] = True
        with self.assertRaisesRegex(m1c.M1CError, "authority changed"):
            m1c._walk_authority(promoted)
        write_json(self.output / "m1c_run_manifest.json", promoted)
        with self.assertRaises(m1c.M1CError):
            m1c.validate_run(self.output)

    def test_run_calls_authority_validator_before_writing_manifest(self) -> None:
        original_validate_run = m1c.validate_run
        with mock.patch.object(
            m1c,
            "validate_run",
            side_effect=lambda output: contracts.load_json(
                Path(output) / "m1c_run_manifest.json"
            ),
        ), mock.patch.object(
            m1c, "_walk_authority", wraps=m1c._walk_authority
        ) as authority:
            self.run_m1c()
        self.assertGreater(authority.call_count, 0)
        self.assertEqual(
            original_validate_run(self.output),
            contracts.load_json(self.output / "m1c_run_manifest.json"),
        )

    def test_validate_run_calls_authority_validator(self) -> None:
        self.run_m1c()
        with mock.patch.object(
            m1c, "_walk_authority", wraps=m1c._walk_authority
        ) as authority:
            m1c.validate_run(self.output)
        self.assertGreater(authority.call_count, 0)

    def test_cli_publishes_data_blocked_evidence_with_success_exit(self) -> None:
        cli_root = self.root / "cli"
        cli_output = cli_root / "public" / "data" / "v2" / "macro"
        cli_portfolio = cli_root / "public" / "data" / "v2" / "model_portfolio_state.json"
        cli_db = cli_root / "macro.sqlite3"
        write_json(cli_portfolio, portfolio())
        environment = dict(os.environ)
        environment["AR_OFFLINE"] = "1"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "experiments" / "macro_os" / "m1c.py"),
                "--db", str(cli_db),
                "--output-dir", str(cli_output),
                "--portfolio", str(cli_portfolio),
                "--calendar", str(cli_output / "release_calendar.json"),
                "--as-of", "2026-08-09T08:35:00Z",
                "--run-id", RUN_ID,
                "--target-trade-date", TARGET,
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("pipeline=OK data_quality=DATA_BLOCKED", result.stdout)
        self.assertEqual("DATA_BLOCKED", m1c.validate_run(cli_output)["data_quality"])

    def test_nightly_artifact_verifier_lifts_quality_without_faking_failure(self) -> None:
        started = time.time() - 1
        self.run_m1c()
        et = self.root / "experiments" / "execution_tracker"
        et.mkdir(parents=True)
        verdict, details = nightly.verify_step_artifacts(
            "macro_m1c", TARGET, started, str(et), RUN_ID
        )
        self.assertEqual("OK", verdict)
        self.assertEqual("DATA_BLOCKED", details[0]["quality_status"])

        panel = contracts.load_json(self.output / "macro_panel.json")
        panel["data"]["mrg"]["formal_state"] = "RISK_OFF_BIAS"
        write_json(self.output / "macro_panel.json", panel)
        verdict, details = nightly.verify_step_artifacts(
            "macro_m1c", TARGET, started, str(et), RUN_ID
        )
        self.assertEqual("FAILED", verdict)
        self.assertIn("契约校验失败", details[0]["why"])


class MacroM1CNightlyWiringTests(unittest.TestCase):
    def test_macro_step_is_after_current_portfolio_export_and_needs_no_tushare_token(self) -> None:
        rows = {name: (index, needs_token, deps) for index, (name, _cmd, needs_token, deps) in enumerate(nightly.STEPS)}
        macro_index, needs_token, deps = rows["macro_m1c"]
        self.assertGreater(macro_index, rows["export_contracts"][0])
        self.assertFalse(needs_token)
        self.assertEqual([], deps)
        self.assertIn("macro_m1c", nightly.ARTIFACTS)

    def test_unrelated_export_degradation_does_not_skip_macro_validation(self) -> None:
        original_steps = nightly.STEPS
        nightly.STEPS = [
            ("export_contracts", ["python3", "export.py"], False, []),
            ("macro_m1c", ["python3", "m1c.py"], False, []),
        ]
        calls = []

        def runner(command):
            calls.append(command[1])
            if command[1] == "export.py":
                return 1, "DATA_BLOCKED: unrelated contract is unavailable"
            return 0, "macro_m1c: pipeline=OK data_quality=PARTIAL"

        try:
            result = nightly.run_steps(runner=runner, require_live=False, verify=False)
        finally:
            nightly.STEPS = original_steps
        self.assertEqual(["export.py", "m1c.py"], calls)
        self.assertEqual("OK", result["steps"][1]["status"])

    def test_macro_failure_is_isolated_and_cannot_stop_unrelated_publication(self) -> None:
        original_steps = nightly.STEPS
        nightly.STEPS = [
            ("core", ["python3", "core.py"], False, []),
            ("macro_m1c", ["python3", "m1c.py"], False, []),
        ]

        def runner(command):
            return (1, "macro_m1c: REFUSED stale portfolio") if command[1] == "m1c.py" else (0, "OK")

        try:
            result = nightly.run_steps(runner=runner, require_live=False, verify=False)
        finally:
            nightly.STEPS = original_steps
        rows = {row["step"]: row for row in result["steps"]}
        self.assertEqual("COMPLETE", result["report"])
        self.assertEqual("DATA_BLOCKED", result["research_data_quality"])
        self.assertEqual([], result["non_ok_steps"])
        self.assertEqual("DATA_BLOCKED", rows["macro_m1c"]["status"])
        self.assertEqual("FAILED", rows["macro_m1c"]["isolated_status"])
        self.assertFalse(rows["macro_m1c"]["blocks_publication"])
        self.assertEqual(
            [{"step": "macro_m1c", "status": "DATA_BLOCKED", "original_status": "FAILED"}],
            result["isolated_steps"],
        )

    def test_business_steps_cannot_enter_macro_isolation_allowlist(self) -> None:
        original = nightly.ISOLATED_CALIBRATION_STEPS
        nightly.ISOLATED_CALIBRATION_STEPS = frozenset(
            {"macro_m1c", "official_sample"}
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "only macro_m1c"):
                nightly.run_steps(
                    runner=lambda _command: (1, "injected business failure"),
                    require_live=False,
                    verify=False,
                )
        finally:
            nightly.ISOLATED_CALIBRATION_STEPS = original

    def test_failed_macro_step_discards_partial_outputs_but_keeps_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            et = root / "experiments" / "execution_tracker"
            macro_data = root / "public" / "data" / "v2" / "macro"
            et.mkdir(parents=True)
            macro_data.mkdir(parents=True)
            write_json(macro_data / "release_calendar.json", {})
            write_json(macro_data / "macro_panel.json", {"run_id": "PARTIAL_WRITE"})
            original_steps = nightly.STEPS
            nightly.STEPS = [("macro_m1c", ["python3", "m1c.py"], False, [])]
            try:
                result = nightly.run_steps(
                    runner=lambda _command: (1, "macro_m1c: REFUSED injected crash"),
                    require_live=False,
                    verify=True,
                    base=str(et),
                    run_id=RUN_ID,
                )
            finally:
                nightly.STEPS = original_steps
            self.assertEqual("COMPLETE", result["report"])
            self.assertTrue((macro_data / "release_calendar.json").is_file())
            self.assertFalse((macro_data / "macro_panel.json").exists())
            self.assertIn(
                "macro_panel.json",
                result["steps"][0]["discarded_artifacts"],
            )

    def test_persistent_macro_db_is_injected_only_as_runtime_environment(self) -> None:
        captured = {}

        def fake_subprocess(cmd, cwd=None, env=None):
            if cmd[1].endswith("m1c.py"):
                captured.update(env or {})
            return 0, "OK"

        with mock.patch.object(nightly, "_subprocess_runner", side_effect=fake_subprocess):
            result = nightly.run_steps(
                require_live=False,
                verify=False,
                base=str(ET),
                run_id=RUN_ID,
                persistent_macro_db="/private/runtime/macro.sqlite3",
            )
        self.assertEqual("COMPLETE", result["report"])
        self.assertEqual("/private/runtime/macro.sqlite3", captured["AR_MACRO_DB"])

    def test_staging_copies_macro_code_as_an_executable_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            et = root / "experiments" / "execution_tracker"
            research = root / "experiments" / "research_funnel"
            macro = root / "experiments" / "macro_os"
            public = root / "public" / "data" / "v2"
            for directory in (et, research, macro, public):
                directory.mkdir(parents=True, exist_ok=True)
            (et / "runtime.py").write_text("# runtime\n", encoding="utf-8")
            (research / "funnel.py").write_text("# funnel\n", encoding="utf-8")
            (macro / "m1c.py").write_text("# macro\n", encoding="utf-8")
            run_dir = Path(tmp) / "run"
            stage = nightly_publish.prepare_stage(str(et), str(root), str(run_dir))
            self.assertTrue((Path(stage["macro"]) / "m1c.py").is_file())

    def test_staging_removes_stale_macro_outputs_but_preserves_runtime_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            et = root / "experiments" / "execution_tracker"
            research = root / "experiments" / "research_funnel"
            macro_code = root / "experiments" / "macro_os"
            macro_data = root / "public" / "data" / "v2" / "macro"
            for directory in (et, research, macro_code, macro_data):
                directory.mkdir(parents=True, exist_ok=True)
            (macro_data / "release_calendar.json").write_text("{}\n", encoding="utf-8")
            (macro_data / "market_features.json").write_text("{}\n", encoding="utf-8")
            (macro_data / "macro_panel.json").write_text('{"run_id":"OLD"}\n', encoding="utf-8")
            stage = nightly_publish.prepare_stage(
                str(et), str(root), str(Path(tmp) / "run")
            )
            staged = Path(stage["public"]) / "macro"
            self.assertTrue((staged / "release_calendar.json").is_file())
            self.assertTrue((staged / "market_features.json").is_file())
            self.assertFalse((staged / "macro_panel.json").exists())


if __name__ == "__main__":
    unittest.main()
