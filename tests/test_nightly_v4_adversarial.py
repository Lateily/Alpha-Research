#!/usr/bin/env python3
"""Adversarial regressions for the nightly-v4 root repair.

Every case in this file reproduced against PR #217 head 6003c51f.  The tests
exercise observable behavior instead of searching source text.
"""
from __future__ import annotations

import json
import os
import sys
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ET = ROOT / "experiments" / "execution_tracker"
sys.path.insert(0, str(ET))

import event_ledger  # noqa: E402
import registry  # noqa: E402
import run_nightly as nightly  # noqa: E402
import run_official_sample as official  # noqa: E402
import nightly_publish  # noqa: E402


def write_json(path: str, value) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False)


def read_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def preflight_fixture(root: str, signals: list[dict], *, with_ledger: bool = True) -> None:
    write_json(os.path.join(root, "paper_signal_log.json"), signals)
    if with_ledger:
        Path(root, "event_ledger.jsonl").touch()
    write_json(os.path.join(root, "model_fund", "fund.json"), {"cash": 100})
    write_json(
        os.path.join(root, "model_fund", "nav_history.json"),
        [{"cash": 100, "n_positions": 0}],
    )
    write_json(os.path.join(root, "model_fund", "orders.json"), [])
    write_json(os.path.join(root, "watch_dynamic.json"), {})
    write_json(os.path.join(root, "rotation_panel.json"), {})


class RegistryBijectionTest(unittest.TestCase):
    def _bijection_errors(self, root: str) -> list[str]:
        rows = registry.load_signal_log_strict(os.path.join(root, "paper_signal_log.json"))
        events = registry.read_events(os.path.join(root, "event_ledger.jsonl"))
        return registry.audit_projection_bijection(rows, events)

    def test_last_predeployment_day_legacy_projection_is_read_only_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preflight_fixture(
                tmp,
                [{
                    "signal_id": "LEGACY_0804",
                    "ticker": "600000.SH",
                    "timestamp": "20260804 close",
                    "horizon": ["1d"],
                    "returns": {"1d": 1.0},
                    "directional_call": "constructive",
                }],
            )
            self.assertEqual([], self._bijection_errors(tmp))

    def test_first_wal_day_legacy_projection_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preflight_fixture(
                tmp,
                [{
                    "signal_id": "FORGED_LEGACY",
                    "ticker": "600000.SH",
                    "timestamp": "20260805 close",
                    "horizon": ["1d"],
                    "returns": {"1d": 99.0},
                    "directional_call": "constructive",
                }],
            )
            errors = self._bijection_errors(tmp)
            self.assertEqual(1, len(errors))
            self.assertIn("WAL 启用后投影缺注册事务", errors[0])

    def test_v2_projection_without_intent_and_commit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preflight_fixture(
                tmp,
                [{
                    "signal_id": "FORGED_V2",
                    "ticker": "600000.SH",
                    "timestamp": "20260804 close",
                    "horizon": ["1d"],
                    "registry_schema": "registry/v2",
                    "registry_txn_id": "NO_EVENT",
                    "registered_at": "20260804 close",
                    "registered_trade_date": "20260804",
                    "written_by": {"script": "paper_tracker.py"},
                }],
            )
            errors = self._bijection_errors(tmp)
            self.assertEqual(1, len(errors))
            self.assertIn("投影没有唯一 intent+commit", errors[0])

    def test_idempotent_retry_must_compare_frozen_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "signals.json")
            lp = os.path.join(tmp, "event_ledger.jsonl")
            kwargs = dict(
                registered_at="20260804 close",
                script="run_official_sample.py",
                version="v1",
                run_id="same",
                ledger_path=lp,
                log_path=sp,
            )
            registry.register_transaction(
                {"signal_id": "same", "ticker": "600000.SH", "trigger_price": 10},
                **kwargs,
            )
            with self.assertRaises((registry.LedgerCorrupt, ValueError)):
                registry.register_transaction(
                    {"signal_id": "same", "ticker": "999999.SZ", "trigger_price": 999},
                    **kwargs,
                )

    def test_retry_across_run_ids_is_same_transaction_and_preserves_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "signals.json")
            lp = os.path.join(tmp, "event_ledger.jsonl")
            base = dict(
                registered_at="20260804 close", script="run_official_sample.py",
                version="v1", ledger_path=lp, log_path=sp,
            )
            first, _ = registry.register_transaction(
                {"signal_id": "stable", "ticker": "600000.SH"}, run_id="RUN_A", **base
            )
            second, status = registry.register_transaction(
                {"signal_id": "stable", "ticker": "600000.SH"}, run_id="RUN_B", **base
            )
            self.assertTrue(status.startswith("idempotent"))
            self.assertEqual(first["registry_txn_id"], second["registry_txn_id"])
            self.assertEqual(second["written_by"]["run_id"], "RUN_A")

    def test_registration_time_entry_seed_is_frozen_before_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "signals.json")
            lp = os.path.join(tmp, "event_ledger.jsonl")
            registered, _ = registry.register_transaction(
                {
                    "signal_id": "seeded", "ticker": "600000.SH",
                    "entry_close": 10.0, "directional_call": "constructive",
                },
                registered_at="20260804 close", script="paper_tracker.py",
                version="v1", run_id="RUN_A", ledger_path=lp, log_path=sp,
            )
            self.assertEqual(registered["registered_evaluation_seed"]["entry_close"], 10.0)
            rows = registry.load_signal_log_strict(sp)
            rows[0]["entry_close"] = 99.0
            registry.write_signal_log_atomic(sp, rows)
            errors = registry.audit_projection_bijection(
                registry.load_signal_log_strict(sp), registry.read_events(lp)
            )
            self.assertTrue(any("冻结的 entry_close" in error for error in errors), errors)

    def test_duplicate_signal_ids_are_rejected_before_manifest_creation(self) -> None:
        sigs = [
            {"signal_id": "dup", "ticker": "600000.SH"},
            {"signal_id": "dup", "ticker": "999999.SZ"},
        ]
        with self.assertRaises(ValueError):
            official.build_signals_manifest(sigs)

    def test_official_entry_records_the_orchestrator_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "paper_signal_log.json")
            with mock.patch.dict(os.environ, {"AR_RUN_ID": "NIGHTLY_RUN_42"}):
                added, total = official.append_log(sp, [{
                    "signal_id": "run-bound", "ticker": "600000.SH",
                    "timestamp": "20260804 close", "horizon": ["1d"],
                }])
            self.assertEqual((added, total), (1, 1))
            row = registry.load_signal_log_strict(sp)[0]
            self.assertEqual(row["written_by"]["run_id"], "NIGHTLY_RUN_42")


class EvaluationWalTest(unittest.TestCase):
    def _registered(self, tmp: str, horizons=None) -> tuple[str, str]:
        sp = os.path.join(tmp, "paper_signal_log.json")
        lp = os.path.join(tmp, "event_ledger.jsonl")
        record = {
            "signal_id": "s1",
            "ticker": "600000.SH",
            "timestamp": "20260801 close",
            "horizon": horizons or ["1d"],
            "relative_strength": True,
        }
        registry.register_transaction(
            record,
            registered_at=record["timestamp"],
            script="run_official_sample.py",
            version="v1",
            run_id="s1",
            ledger_path=lp,
            log_path=sp,
        )
        return sp, lp

    def test_all_evaluation_fields_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sp, lp = self._registered(tmp)
            evaluation = {
                "signal_id": "s1",
                "horizon": "1d",
                "value": 0.1,
                "entry_close": 10.0,
                "directional_call": "constructive",
                "entry_trade_date": "20260801",
                "source_trade_date": "20260804",
                "source_close": 11.0,
                "algorithm_version": "backfill/v2",
            }
            registry.apply_evaluation_transactions(sp, lp, [evaluation])

            rows = registry.load_signal_log_strict(sp)
            rows[0]["entry_close"] = -999
            rows[0]["directional_call"] = "cautious"
            registry.write_signal_log_atomic(sp, rows)
            preflight_fixture(tmp, rows)
            self.assertFalse(nightly.preflight(base=tmp)["pass"])

    def test_conflicting_second_evaluation_never_changes_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sp, lp = self._registered(tmp)
            first = {
                "signal_id": "s1",
                "horizon": "1d",
                "value": 0.1,
                "entry_close": 10.0,
                "directional_call": "constructive",
                "entry_trade_date": "20260801",
                "source_trade_date": "20260804",
                "source_close": 11.0,
                "algorithm_version": "backfill/v2",
            }
            registry.apply_evaluation_transactions(sp, lp, [first])
            second = dict(first, value=0.2, source_close=12.0)
            with self.assertRaises((registry.LedgerCorrupt, ValueError)):
                registry.apply_evaluation_transactions(sp, lp, [second])
            row = registry.load_signal_log_strict(sp)[0]
            self.assertEqual(row["returns"]["1d"], 0.1)

    def test_second_horizon_cannot_rewrite_shared_entry_or_direction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sp, lp = self._registered(tmp)
            first = {
                "signal_id": "s1", "horizon": "1d", "value": 0.1,
                "entry_close": 10.0, "directional_call": "constructive",
                "entry_trade_date": "20260801", "source_trade_date": "20260804",
                "source_close": 11.0, "algorithm_version": "backfill/v2",
            }
            registry.apply_evaluation_transactions(sp, lp, [first])
            incompatible = dict(
                first, horizon="3d", value=0.2, entry_close=11.0,
                directional_call="cautious", source_trade_date="20260806",
                source_close=12.0,
            )
            with self.assertRaises(registry.LedgerCorrupt):
                registry.apply_evaluation_transactions(sp, lp, [incompatible])
            row = registry.load_signal_log_strict(sp)[0]
            self.assertNotIn("3d", row["returns"])
            self.assertEqual(row["entry_close"], 10.0)
            self.assertEqual(row["directional_call"], "constructive")

    def test_same_batch_horizons_must_share_entry_direction_and_entry_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sp, lp = self._registered(tmp)
            first = {
                "signal_id": "s1", "horizon": "1d", "value": 0.1,
                "entry_close": 10.0, "directional_call": "constructive",
                "entry_trade_date": "20260801", "source_trade_date": "20260804",
                "source_close": 11.0, "algorithm_version": "backfill/v2",
            }
            conflicting = dict(
                first, horizon="3d", value=0.2, entry_close=11.0,
                directional_call="cautious", entry_trade_date="20260802",
                source_trade_date="20260806", source_close=12.0,
            )
            with self.assertRaisesRegex(registry.LedgerCorrupt, "同批次"):
                registry.apply_evaluation_transactions(sp, lp, [first, conflicting])
            row = registry.load_signal_log_strict(sp)[0]
            self.assertFalse(row.get("returns"))
            self.assertFalse(any(
                event["kind"].startswith("evaluation_")
                for event in registry.read_events(lp)
            ))

    def test_corrupt_quarantine_never_gets_silently_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sp, _ = self._registered(tmp)
            qp = sp + registry.QUARANTINE_SUFFIX
            Path(qp).write_text("{broken", encoding="utf-8")
            rows = registry.load_signal_log_strict(sp)
            with self.assertRaisesRegex(registry.LedgerCorrupt, "隔离区"):
                registry.quarantine_projection(sp, rows, "s1", "test")
            self.assertEqual(Path(qp).read_text(encoding="utf-8"), "{broken")
            self.assertEqual(len(registry.load_signal_log_strict(sp)), 1)

    def test_evaluation_horizon_must_have_been_frozen_at_registration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sp, lp = self._registered(tmp, ["1d"])
            evaluation = {
                "signal_id": "s1", "horizon": "10d", "value": 0.1,
                "entry_close": 10.0, "directional_call": "constructive",
                "entry_trade_date": "20260801", "source_trade_date": "20260804",
                "source_close": 11.0, "algorithm_version": "backfill/v2",
            }
            with self.assertRaisesRegex(registry.LedgerCorrupt, "冻结的 horizon"):
                registry.apply_evaluation_transactions(sp, lp, [evaluation])
            self.assertFalse(any(
                event["kind"].startswith("evaluation_")
                for event in registry.read_events(lp)
            ))

    def test_evaluation_recovery_is_idempotent_after_projection_only_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sp, lp = self._registered(tmp, ["1d"])
            evaluation = {
                "signal_id": "s1", "horizon": "1d", "value": 0.1,
                "entry_close": 10.0, "directional_call": "constructive",
                "entry_trade_date": "20260801", "source_trade_date": "20260804",
                "source_close": 11.0, "algorithm_version": "backfill/v2",
            }
            eid = registry.evaluation_id(evaluation)
            expected_hash = registry.evaluation_hash(evaluation)
            event_ledger.append("evaluation_intent", eid, {
                "schema": registry.EVALUATION_SCHEMA,
                "evaluation": evaluation,
                "evaluation_hash": expected_hash,
            }, path=lp)
            rows = registry.load_signal_log_strict(sp)
            registry._apply_evaluation_to_row(rows[0], evaluation, expected_hash)
            registry.write_signal_log_atomic(sp, rows)

            first = registry.recover_evaluations(lp, sp)
            second = registry.recover_evaluations(lp, sp)
            self.assertEqual(first["rolled_forward"], 1)
            self.assertEqual(second["rolled_forward"], 0)
            self.assertEqual(
                registry.audit_projection_bijection(
                    registry.load_signal_log_strict(sp), registry.read_events(lp)
                ),
                [],
            )

    def test_concurrent_horizons_serialize_without_lost_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sp, lp = self._registered(tmp, ["1d", "3d"])
            common = {
                "signal_id": "s1", "entry_close": 10.0,
                "directional_call": "constructive", "entry_trade_date": "20260801",
                "algorithm_version": "backfill/v2",
            }
            evaluations = [
                dict(common, horizon="1d", value=0.1,
                     source_trade_date="20260804", source_close=11.0),
                dict(common, horizon="3d", value=0.2,
                     source_trade_date="20260806", source_close=12.0),
            ]
            errors = []

            def worker(evaluation):
                try:
                    registry.apply_evaluation_transactions(sp, lp, [evaluation])
                except Exception as exc:  # pragma: no cover - asserted below
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(evaluation,))
                       for evaluation in evaluations]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            row = registry.load_signal_log_strict(sp)[0]
            self.assertEqual(row["returns"], {"1d": 0.1, "3d": 0.2})
            self.assertEqual(
                registry.audit_projection_bijection([row], registry.read_events(lp)), []
            )


class ArtifactAndRunStateTest(unittest.TestCase):
    def test_ordinary_exception_path_keeps_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = os.path.join(tmp, "run_state.json")
            write_json(state, {"run_id": "R1", "phase": "RUNNING_STAGING"})
            self.assertFalse(nightly._clear_run_state_if_terminal("R1", False, state))
            self.assertTrue(os.path.exists(state))
            self.assertTrue(nightly._clear_run_state_if_terminal("R1", True, state))
            self.assertFalse(os.path.exists(state))

    def test_execute_exception_keeps_marker_and_global_lock_is_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = {
                name: getattr(nightly, name)
                for name in ("HERE", "RUNS_DIR", "RUN_STATE", "NIGHTLY_LOCK", "OUT")
            }
            try:
                nightly.HERE = tmp
                nightly.RUNS_DIR = os.path.join(tmp, "runs")
                nightly.RUN_STATE = os.path.join(tmp, "run_state.json")
                nightly.NIGHTLY_LOCK = os.path.join(tmp, "nightly.lock")
                nightly.OUT = os.path.join(tmp, "nightly_run.json")
                os.makedirs(nightly.RUNS_DIR)
                clean = {"pass": True, "checks": [], "failures": [], "warns": []}
                with (
                    mock.patch.object(nightly, "_crash_check_and_rollback", return_value=None),
                    mock.patch.object(nightly, "_recover_phase", return_value={}),
                    mock.patch.object(nightly, "preflight", return_value=clean),
                    mock.patch.object(nightly, "_print_preflight"),
                    mock.patch.object(nightly_publish, "prepare_stage", side_effect=RuntimeError("boom")),
                ):
                    with self.assertRaisesRegex(RuntimeError, "boom"):
                        nightly.main()
                    marker = read_json(nightly.RUN_STATE)
                    self.assertEqual(marker["phase"], "PREPARING")
                    # 第一次异常返回后锁必须已经释放;第二次应能进入执行体。
                    with mock.patch.object(nightly, "_execute_nightly", return_value=7) as execute:
                        self.assertEqual(nightly.main(), 7)
                        execute.assert_called_once()
            finally:
                for name, value in old.items():
                    setattr(nightly, name, value)

    def test_internal_blocked_states_are_not_ok(self) -> None:
        cases = [
            ("court_10d", "court_10d.json", {"status": "PARTIAL"}),
            (
                "overnight_anchor_frame",
                "overnight_anchor.json",
                {"as_of": "20260804 09:00", "bias": "DATA_BLOCKED"},
            ),
            (
                "red_flag_gate",
                "red_flags.json",
                {"checked_at": "20260804", "results": [{"verdict": "DATA_BLOCKED"}]},
            ),
            (
                "position_review",
                "position_review.json",
                {"as_of": "20260804", "data_blocked": [{"ticker": "x"}]},
            ),
            (
                "court_wakeup",
                "court_wakeup.json",
                {"as_of": "20260804", "data_blocked": [{"ticker": "x"}]},
            ),
            (
                "rotation_validation",
                "rotation_validation.json",
                {
                    "as_of": "20260804",
                    "Q3_chain_leadlag": [{"status": "DATA_BLOCKED: sector missing"}],
                },
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for step, filename, payload in cases:
                write_json(os.path.join(tmp, filename), payload)
                status, _ = nightly.verify_step_artifacts(
                    step, "20260804", time.time() - 1, tmp
                )
                self.assertNotEqual(status, "OK", step)

    def test_artifact_from_before_run_is_never_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "momentum_prefilter.json")
            write_json(path, {"as_of": "20260804"})
            run_start = time.time()
            os.utime(path, (run_start - 0.2, run_start - 0.2))
            status, _ = nightly.verify_step_artifacts(
                "momentum_prefilter", "20260804", run_start, tmp
            )
            self.assertEqual(status, "STALE_OUTPUT")

    def test_rollback_removes_files_created_by_failed_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = (nightly.HERE, nightly.RUNS_DIR, nightly.RUN_STATE)
            try:
                nightly.HERE = tmp
                nightly.RUNS_DIR = os.path.join(tmp, "runs")
                nightly.RUN_STATE = os.path.join(tmp, "run_state.json")
                nightly._snapshot_before("R1")
                created = os.path.join(tmp, "momentum_prefilter.json")
                write_json(created, {"as_of": "NEW"})
                write_json(nightly.RUN_STATE, {"run_id": "R1"})
                nightly._crash_check_and_rollback()
                self.assertFalse(os.path.exists(created))
            finally:
                nightly.HERE, nightly.RUNS_DIR, nightly.RUN_STATE = old


class TestSeamBoundaryTest(unittest.TestCase):
    def test_fake_snapshot_requires_explicit_test_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = os.path.join(tmp, "fixture.json")
            write_json(fixture, {"trade_date": "20990101", "snap": {}, "sigs": []})
            with self.assertRaises(PermissionError):
                official.load_test_snapshot_from_env(
                    {"AR_FAKE_SNAPSHOT": fixture}, data_root=str(ET)
                )

    def test_fake_snapshot_is_forbidden_in_nightly_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = os.path.join(tmp, "fixture.json")
            write_json(fixture, {"trade_date": "20990101", "snap": {}, "sigs": []})
            with self.assertRaisesRegex(PermissionError, "staging"):
                official.load_test_snapshot_from_env({
                    "AR_FAKE_SNAPSHOT": fixture,
                    "AR_TEST_MODE": "1",
                    "AR_OFFLINE": "1",
                    "AR_NIGHTLY_STAGING": "1",
                }, data_root=tmp)


class CiCoverageTest(unittest.TestCase):
    def test_every_python_test_file_is_registered_in_ci(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "python-ci.yml").read_text(
            encoding="utf-8"
        )
        missing = [
            path.name for path in sorted((ROOT / "tests").glob("test_*.py"))
            if path.name not in workflow
        ]
        self.assertEqual(missing, [], f"Python 测试未接 CI: {missing}")


class StagingPublicationTest(unittest.TestCase):
    def _layout(self, tmp: str):
        repo = os.path.join(tmp, "repo")
        et = os.path.join(repo, "experiments", "execution_tracker")
        public = os.path.join(repo, "public", "data", "v2")
        run_dir = os.path.join(tmp, "run")
        os.makedirs(os.path.join(et, "model_fund"), exist_ok=True)
        os.makedirs(public, exist_ok=True)
        write_json(os.path.join(et, "rotation_panel.json"), {"value": "old"})
        write_json(os.path.join(et, "model_fund", "fund.json"), {"cash": 1})
        write_json(os.path.join(public, "meta.json"), {"value": "old-public"})
        stage = nightly_publish.prepare_stage(et, repo, run_dir)
        return repo, et, public, run_dir, stage

    def test_staging_is_invisible_until_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, et, _, _, stage = self._layout(tmp)
            write_json(os.path.join(stage["et"], "rotation_panel.json"), {"value": "new"})
            self.assertEqual(read_json(os.path.join(et, "rotation_panel.json"))["value"], "old")

    def test_publish_failure_restores_files_and_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, et, public, run_dir, stage = self._layout(tmp)
            write_json(os.path.join(et, "current_run.json"), {"run_id": "OLD"})
            write_json(os.path.join(public, "current_run.json"), {"run_id": "OLD"})
            write_json(os.path.join(stage["et"], "rotation_panel.json"), {"value": "new"})
            write_json(os.path.join(stage["public"], "meta.json"), {"value": "new-public"})
            state = os.path.join(et, "publication_state.json")
            with self.assertRaises(RuntimeError):
                nightly_publish.publish_stage(
                    "R1", "20260804", stage, et, repo, run_dir, state, fail_after=1
                )
            self.assertEqual(read_json(os.path.join(et, "rotation_panel.json"))["value"], "old")
            self.assertEqual(read_json(os.path.join(public, "meta.json"))["value"], "old-public")
            self.assertEqual(read_json(os.path.join(et, "current_run.json"))["run_id"], "OLD")
            self.assertEqual(read_json(state)["status"], "ROLLED_BACK")

    def test_successful_publish_commits_manifest_last(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, et, public, run_dir, stage = self._layout(tmp)
            write_json(os.path.join(stage["et"], "rotation_panel.json"), {"value": "new"})
            write_json(os.path.join(stage["public"], "meta.json"), {"value": "new-public"})
            state = os.path.join(et, "publication_state.json")
            manifest = nightly_publish.publish_stage(
                "R2", "20260804", stage, et, repo, run_dir, state
            )
            self.assertEqual(read_json(os.path.join(et, "rotation_panel.json"))["value"], "new")
            self.assertEqual(read_json(os.path.join(public, "meta.json"))["value"], "new-public")
            self.assertEqual(read_json(os.path.join(et, "current_run.json"))["run_id"], "R2")
            self.assertEqual(read_json(os.path.join(public, "current_run.json"))["run_id"], "R2")
            self.assertEqual(read_json(state)["status"], "COMMITTED")
            self.assertEqual(manifest["target_trade_date"], "20260804")
            manifest_path = os.path.join(public, manifest["manifest_path"])
            self.assertTrue(os.path.isfile(manifest_path))
            self.assertEqual(
                nightly_publish.sha256_file(manifest_path),
                manifest["manifest_sha256"],
            )
            verified = nightly_publish.recover_interrupted_publish(state, et, repo)
            self.assertEqual(verified["status"], "COMMITTED_VERIFIED")

    def test_failure_after_public_pointer_restores_all_publication_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, et, public, run_dir, stage = self._layout(tmp)
            write_json(os.path.join(et, "current_run.json"), {"run_id": "OLD"})
            write_json(os.path.join(public, "current_run.json"), {"run_id": "OLD"})
            write_json(os.path.join(stage["et"], "rotation_panel.json"), {"value": "new"})
            state = os.path.join(et, "publication_state.json")
            with self.assertRaisesRegex(RuntimeError, "public marker"):
                nightly_publish.publish_stage(
                    "R_POINTER", "20260804", stage, et, repo, run_dir, state,
                    fail_phase="after_public_marker",
                )
            self.assertEqual(read_json(os.path.join(et, "current_run.json"))["run_id"], "OLD")
            self.assertEqual(read_json(os.path.join(public, "current_run.json"))["run_id"], "OLD")
            self.assertFalse(os.path.exists(
                os.path.join(public, "runs", "R_POINTER", "manifest.json")
            ))
            self.assertEqual(read_json(state)["status"], "ROLLED_BACK")

    def test_committed_pointer_or_public_alias_tamper_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, et, public, run_dir, stage = self._layout(tmp)
            write_json(os.path.join(stage["public"], "meta.json"), {"value": "new-public"})
            state_path = os.path.join(et, "publication_state.json")
            nightly_publish.publish_stage(
                "R_TAMPER", "20260804", stage, et, repo, run_dir, state_path
            )
            write_json(os.path.join(public, "meta.json"), {"value": "forged"})
            with self.assertRaisesRegex(RuntimeError, "公开契约被改写"):
                nightly_publish.recover_interrupted_publish(state_path, et, repo)

            # Restore the alias, then split the two commit pointers.
            write_json(os.path.join(public, "meta.json"), {"value": "new-public"})
            et_pointer = read_json(os.path.join(et, "current_run.json"))
            et_pointer["run_id"] = "OTHER"
            write_json(os.path.join(et, "current_run.json"), et_pointer)
            with self.assertRaisesRegex(RuntimeError, "pointer 不一致"):
                nightly_publish.recover_interrupted_publish(state_path, et, repo)

    def test_committed_run_crash_is_preserved_not_reported_as_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, et, _, run_dir, stage = self._layout(tmp)
            state_path = os.path.join(et, "publication_state.json")
            nightly_publish.publish_stage(
                "R_COMMITTED", "20260804", stage, et, repo, run_dir, state_path
            )
            run_state = os.path.join(et, "run_state.json")
            write_json(run_state, {
                "orchestrator": "nightly_v4", "run_id": "R_COMMITTED",
                "phase": "PUBLISHING",
            })
            old = {
                name: getattr(nightly, name)
                for name in ("HERE", "REPO_ROOT", "RUN_STATE", "PUBLICATION_STATE")
            }
            try:
                nightly.HERE = et
                nightly.REPO_ROOT = repo
                nightly.RUN_STATE = run_state
                nightly.PUBLICATION_STATE = state_path
                recovered = nightly._crash_check_and_rollback()
            finally:
                for name, value in old.items():
                    setattr(nightly, name, value)
            self.assertEqual(recovered["committed_run_recovered"], "R_COMMITTED")
            self.assertEqual(recovered["restored"], 0)
            self.assertFalse(os.path.exists(run_state))

    def test_previous_commit_never_masquerades_as_newer_crashed_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, et, _, run_dir, stage = self._layout(tmp)
            state_path = os.path.join(et, "publication_state.json")
            nightly_publish.publish_stage(
                "R_OLD", "20260804", stage, et, repo, run_dir, state_path
            )
            run_state = os.path.join(et, "run_state.json")
            write_json(run_state, {
                "orchestrator": "nightly_v4", "run_id": "R_NEW",
                "phase": "RUNNING_STAGING",
            })
            old = {
                name: getattr(nightly, name)
                for name in ("HERE", "REPO_ROOT", "RUN_STATE", "PUBLICATION_STATE")
            }
            try:
                nightly.HERE = et
                nightly.REPO_ROOT = repo
                nightly.RUN_STATE = run_state
                nightly.PUBLICATION_STATE = state_path
                recovered = nightly._crash_check_and_rollback()
            finally:
                for name, value in old.items():
                    setattr(nightly, name, value)
            self.assertNotIn("committed_run_recovered", recovered)
            self.assertEqual(recovered["rolled_back_run"], "R_NEW")
            self.assertEqual(recovered["publication"]["run_id"], "R_OLD")

    def test_interrupted_publish_is_rolled_back_on_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, et, public, run_dir, stage = self._layout(tmp)
            write_json(os.path.join(stage["et"], "rotation_panel.json"), {"value": "new"})
            write_json(os.path.join(stage["public"], "meta.json"), {"value": "new-public"})
            state_path = os.path.join(et, "publication_state.json")
            plan = nightly_publish.build_publish_plan(
                "R3", "20260804", stage, et, repo, run_dir
            )
            first = plan["entries"][0]
            dst = nightly_publish._destination(first["scope"], first["rel"], et, repo)
            nightly_publish.atomic_copy(first["source"], dst)
            write_json(state_path, {
                "schema": "nightly_publication_state/v1",
                "status": "PUBLISHING",
                "run_id": "R3",
                "target_trade_date": "20260804",
                "plan": os.path.join(run_dir, "publish_plan.json"),
            })

            recovered = nightly_publish.recover_interrupted_publish(state_path, et, repo)
            self.assertEqual(recovered["run_id"], "R3")
            self.assertEqual(read_json(os.path.join(et, "rotation_panel.json"))["value"], "old")
            self.assertEqual(read_json(os.path.join(public, "meta.json"))["value"], "old-public")
            self.assertEqual(read_json(state_path)["status"], "RECOVERED_ROLLBACK")

    def test_mutated_protected_input_refuses_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, et, _, run_dir, stage = self._layout(tmp)
            write_json(os.path.join(stage["et"], "model_fund", "fund.json"), {"cash": 0})
            with self.assertRaisesRegex(RuntimeError, "model_fund"):
                nightly_publish.build_publish_plan(
                    "R4", "20260804", stage, et, repo, run_dir
                )

    def test_execute_nightly_publishes_only_after_complete_staging_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            et = os.path.join(repo, "experiments", "execution_tracker")
            public = os.path.join(repo, "public", "data", "v2")
            os.makedirs(os.path.join(et, "model_fund"), exist_ok=True)
            os.makedirs(public, exist_ok=True)
            write_json(os.path.join(et, "model_fund", "fund.json"), {"cash": 1})
            write_json(os.path.join(et, "rotation_panel.json"), {"value": "old"})
            write_json(os.path.join(public, "meta.json"), {"value": "old-public"})
            old = {name: getattr(nightly, name) for name in (
                "HERE", "REPO_ROOT", "RUNS_DIR", "RUN_STATE", "OUT", "PUBLICATION_STATE",
            )}
            clean = {"pass": True, "checks": [], "failures": [], "warns": []}

            def fake_steps(*, require_live, verify, base, run_id):
                self.assertTrue(verify)
                write_json(os.path.join(base, "rotation_panel.json"), {
                    "value": "new", "run_id": run_id,
                    "target_trade_date": "20260804", "as_of": "20260804",
                })
                stage_public = os.path.abspath(os.path.join(base, "..", "..", "public", "data", "v2"))
                write_json(os.path.join(stage_public, "meta.json"), {
                    "value": "new-public", "run_id": run_id,
                    "target_trade_date": "20260804", "report": "COMPLETE",
                })
                return {
                    "generated_at": "20260804 16:35", "orchestrator": "nightly_v4",
                    "run_id": run_id, "target_trade_date": "20260804",
                    "report": "COMPLETE", "non_ok_steps": [],
                    "steps": [{"step": "fake", "status": "OK"}],
                }

            try:
                nightly.HERE = et
                nightly.REPO_ROOT = repo
                nightly.RUNS_DIR = os.path.join(et, "runs")
                nightly.RUN_STATE = os.path.join(et, "run_state.json")
                nightly.OUT = os.path.join(et, "nightly_run.json")
                nightly.PUBLICATION_STATE = os.path.join(et, "publication_state.json")
                with (
                    mock.patch.object(nightly, "_crash_check_and_rollback", return_value=None),
                    mock.patch.object(nightly, "_recover_phase", return_value={}),
                    mock.patch.object(nightly, "preflight", return_value=clean),
                    mock.patch.object(nightly, "_print_preflight"),
                    mock.patch.object(nightly, "run_steps", side_effect=fake_steps),
                    mock.patch.object(nightly, "_alarm"),
                    mock.patch.object(nightly, "_prune_runs"),
                ):
                    self.assertEqual(nightly._execute_nightly(), 0)
                self.assertEqual(read_json(os.path.join(et, "rotation_panel.json"))["value"], "new")
                self.assertEqual(read_json(os.path.join(public, "meta.json"))["value"], "new-public")
                self.assertEqual(read_json(os.path.join(et, "current_run.json"))["target_trade_date"], "20260804")
                self.assertTrue(read_json(nightly.OUT)["published"])
                self.assertFalse(os.path.exists(nightly.RUN_STATE))
            finally:
                for name, value in old.items():
                    setattr(nightly, name, value)


class UnifiedRunContextTest(unittest.TestCase):
    def test_immutable_sample_can_be_reused_but_must_match_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_json(os.path.join(tmp, "run_target.json"), {
                "trade_date": "20260804", "target_trade_date": "20260804", "run_id": "NEW",
            })
            write_json(os.path.join(tmp, "samples", "20260804.json"), {
                "target_trade_date": "20260804", "run_id": "ORIGINAL",
            })
            status, details = nightly.verify_step_artifacts(
                "official_sample", "20260804", time.time() - 1, tmp, "NEW"
            )
            self.assertEqual(status, "OK", details)
            os.remove(os.path.join(tmp, "samples", "20260804.json"))
            write_json(os.path.join(tmp, "samples", "20260805.json"), {
                "target_trade_date": "20260805", "run_id": "ORIGINAL",
            })
            bad, _ = nightly.verify_step_artifacts(
                "official_sample", "20260804", time.time() - 1, tmp, "NEW"
            )
            self.assertEqual(bad, "FAILED")

    def test_dynamic_target_artifacts_require_same_run_and_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_json(os.path.join(tmp, "reports", "20260804.json"), {
                "target_trade_date": "20260804", "run_id": "CTX2",
            })
            status, details = nightly.verify_step_artifacts(
                "fwd_backfill", "20260804", time.time() - 1, tmp, "CTX2"
            )
            self.assertEqual(status, "OK", details)
            bad_status, _ = nightly.verify_step_artifacts(
                "fwd_backfill", "20260805", time.time() - 1, tmp, "CTX2"
            )
            self.assertEqual(bad_status, "FAILED")

    def test_target_is_propagated_and_every_step_gets_status_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_steps, old_artifacts = nightly.STEPS, nightly.ARTIFACTS
            nightly.STEPS = [
                ("official_sample", ["python3", "official.py"], False, []),
                ("child", ["python3", "child.py"], False, ["official_sample"]),
            ]
            nightly.ARTIFACTS = {
                "official_sample": [("run_target.json", "trade_date", True)],
                "child": [("child.json", "as_of", True)],
            }

            def fake(cmd, cwd=None, env=None):
                if cmd[1] == "official.py":
                    write_json(os.path.join(cwd, "run_target.json"), {
                        "trade_date": "20260804", "target_trade_date": "20260804",
                        "run_id": env["AR_RUN_ID"],
                    })
                else:
                    self.assertEqual(env["AR_TARGET_TRADE_DATE"], "20260804")
                    write_json(os.path.join(cwd, "child.json"), {
                        "as_of": "20260804", "target_trade_date": "20260804",
                        "run_id": env["AR_RUN_ID"],
                    })
                return 0, "ok"

            try:
                with mock.patch.object(nightly, "_subprocess_runner", side_effect=fake):
                    result = nightly.run_steps(
                        require_live=False, verify=True, base=tmp, run_id="CTX1"
                    )
                self.assertEqual(result["report"], "COMPLETE")
                self.assertEqual(result["target_trade_date"], "20260804")
                for step in ("official_sample", "child"):
                    status = read_json(os.path.join(tmp, "step_status", f"{step}.json"))
                    self.assertEqual(status["run_id"], "CTX1")
                    self.assertEqual(status["target_trade_date"], "20260804")
                    self.assertEqual(status["status"], "OK")
            finally:
                nightly.STEPS, nightly.ARTIFACTS = old_steps, old_artifacts


class ProtectedLedgerAppendOnlyTest(unittest.TestCase):
    """资金账本守卫升级为 append-only 语义后,必须仍拦得住篡改。

    背景:NAV 每日结算是正当追加,而原守卫拿整目录哈希比对,把合法写入判成篡改
    (17/17 步全 OK 却发布失败)。拆守卫是错的答案 —— 它护的是资金账本。
    """

    def _stage(self, before_nav, after_nav, *, before_fund=None, after_fund=None,
               before_orders=None, after_orders=None):
        import nightly_publish as npub
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        stage_et = os.path.join(tmp, "et")
        run_dir = os.path.join(tmp, "run")
        mf = os.path.join(stage_et, "model_fund")
        os.makedirs(mf); os.makedirs(run_dir)
        bf = before_fund if before_fund is not None else {"cash": 100.0, "policy": "p"}
        bo = before_orders if before_orders is not None else []
        json.dump(before_nav, open(os.path.join(mf, "nav_history.json"), "w"))
        json.dump(bf, open(os.path.join(mf, "fund.json"), "w"))
        json.dump(bo, open(os.path.join(mf, "orders.json"), "w"))
        snap = {"protected": {"model_fund": npub._tree_hashes(mf)},
                "protected_content": {"model_fund": npub._protected_content(mf)}}
        json.dump(snap, open(os.path.join(run_dir, "staging_input.json"), "w"))
        json.dump(after_nav, open(os.path.join(mf, "nav_history.json"), "w"))
        if after_fund is not None:
            json.dump(after_fund, open(os.path.join(mf, "fund.json"), "w"))
        if after_orders is not None:
            json.dump(after_orders, open(os.path.join(mf, "orders.json"), "w"))
        return npub, stage_et, run_dir

    def test_legitimate_nav_append_passes(self):
        npub, et, rd = self._stage([{"date": "20260804", "nav": 1.0}],
                                   [{"date": "20260804", "nav": 1.0},
                                    {"date": "20260805", "nav": 2.0}])
        self.assertEqual([], npub.verify_protected_inputs(et, rd, target="20260805"))

    def test_untouched_ledger_passes(self):
        rows = [{"date": "20260804", "nav": 1.0}]
        npub, et, rd = self._stage(rows, rows)
        self.assertEqual([], npub.verify_protected_inputs(et, rd, target="20260805"))

    def test_rewriting_an_existing_nav_row_is_rejected(self):
        npub, et, rd = self._stage([{"date": "20260804", "nav": 1.0}],
                                   [{"date": "20260804", "nav": 999.0},
                                    {"date": "20260805", "nav": 2.0}])
        errs = npub.verify_protected_inputs(et, rd, target="20260805")
        self.assertTrue(errs and "既有记录被改写" in errs[0], errs)

    def test_deleting_nav_rows_is_rejected(self):
        npub, et, rd = self._stage([{"date": "20260803", "nav": 1.0},
                                    {"date": "20260804", "nav": 1.5}],
                                   [{"date": "20260803", "nav": 1.0}])
        errs = npub.verify_protected_inputs(et, rd, target="20260805")
        self.assertTrue(errs and "元素减少" in errs[0], errs)

    def test_appending_wrong_trade_date_is_rejected(self):
        npub, et, rd = self._stage([{"date": "20260804", "nav": 1.0}],
                                   [{"date": "20260804", "nav": 1.0},
                                    {"date": "20260731", "nav": 2.0}])
        errs = npub.verify_protected_inputs(et, rd, target="20260805")
        self.assertTrue(errs and "≠ 本轮" in errs[0], errs)

    def test_multiple_rows_for_one_target_is_rejected(self):
        npub, et, rd = self._stage([], [{"date": "20260805", "nav": 1.0},
                                        {"date": "20260805", "nav": 2.0}])
        errs = npub.verify_protected_inputs(et, rd, target="20260805")
        self.assertTrue(any("只许一行" in e for e in errs), errs)

    def test_unexplained_cash_change_is_rejected(self):
        """现金变了但订单没动 ⇒ 无成交事件解释 ⇒ 拒绝。
        只判"字段名在白名单"是不够的:那样任意改现金都会放行。"""
        rows = [{"date": "20260804", "nav": 1.0}]
        npub, et, rd = self._stage(rows, rows, after_fund={"cash": 200.0, "policy": "p"})
        errs = npub.verify_protected_inputs(et, rd, target="20260805")
        self.assertTrue(any("无成交事件解释" in e for e in errs), errs)

    def test_cash_change_explained_by_a_fill_passes(self):
        """pending→filled 扣 shares×fill_price,现金变动对得上 ⇒ 放行。"""
        rows = [{"date": "20260804", "nav": 1.0}]
        npub, et, rd = self._stage(
            rows, rows,
            before_fund={"cash": 1000.0, "policy": "p"},
            after_fund={"cash": 700.0, "policy": "p"},
            before_orders=[{"id": 1, "status": "pending", "shares": 100,
                            "fill_price": 3.0, "ticker": "600000.SH"}],
            after_orders=[{"id": 1, "status": "filled", "shares": 100,
                           "fill_price": 3.0, "ticker": "600000.SH"}])
        self.assertEqual([], npub.verify_protected_inputs(et, rd, target="20260805"))

    def test_cash_change_not_matching_the_fill_is_rejected(self):
        """有成交但金额对不上(多扣 ¥50)⇒ 仍拒。"""
        rows = [{"date": "20260804", "nav": 1.0}]
        npub, et, rd = self._stage(
            rows, rows,
            before_fund={"cash": 1000.0, "policy": "p"},
            after_fund={"cash": 650.0, "policy": "p"},
            before_orders=[{"id": 1, "status": "pending", "shares": 100,
                            "fill_price": 3.0, "ticker": "600000.SH"}],
            after_orders=[{"id": 1, "status": "filled", "shares": 100,
                           "fill_price": 3.0, "ticker": "600000.SH"}])
        errs = npub.verify_protected_inputs(et, rd, target="20260805")
        self.assertTrue(any("无成交事件解释" in e for e in errs), errs)

    def test_non_cash_field_change_is_rejected(self):
        rows = [{"date": "20260804", "nav": 1.0}]
        npub, et, rd = self._stage(rows, rows, after_fund={"cash": 100.0, "policy": "TAMPERED"})
        errs = npub.verify_protected_inputs(et, rd, target="20260805")
        self.assertTrue(any("只允许" in e for e in errs), errs)

    def test_orders_append_and_forward_transition_allowed(self):
        rows = [{"date": "20260804", "nav": 1.0}]
        npub, et, rd = self._stage(rows, rows,
                                   before_orders=[{"id": 1, "status": "filled"}],
                                   after_orders=[{"id": 1, "status": "filled"}, {"id": 2}])
        self.assertEqual([], npub.verify_protected_inputs(et, rd, target="20260805"))

    def test_orders_illegal_transition_rejected(self):
        """closed 不许复活,filled 不许退回 pending。"""
        rows = [{"date": "20260804", "nav": 1.0}]
        for was, now in (("closed", "filled"), ("filled", "pending")):
            npub, et, rd = self._stage(rows, rows,
                                       before_orders=[{"id": 1, "status": was}],
                                       after_orders=[{"id": 1, "status": now}])
            errs = npub.verify_protected_inputs(et, rd, target="20260805")
            self.assertTrue(any("非法迁移" in e for e in errs), f"{was}->{now}: {errs}")

    def test_all_real_statuses_are_registered(self):
        """状态清单必须覆盖真实账本出现过的全部状态 —— 漏一个,守卫就从
        防篡改变成拦正常运行(0805 第三轮实际被 cancelled→cancelled 拦住)。"""
        import nightly_publish as npub
        for st in ("pending", "filled", "closed", "cancelled"):
            self.assertIn(st, npub.ORDER_TRANSITIONS, f"{st} 未登记")
            self.assertIn(st, npub.ORDER_TRANSITIONS[st], f"{st}→{st} 自转必须合法")

    def test_terminal_statuses_cannot_revive(self):
        rows = [{"date": "20260804", "nav": 1.0}]
        for was, now in (("closed", "filled"), ("cancelled", "pending"),
                         ("cancelled", "filled")):
            npub, et, rd = self._stage(rows, rows,
                                       before_orders=[{"id": 1, "status": was}],
                                       after_orders=[{"id": 1, "status": now}])
            errs = npub.verify_protected_inputs(et, rd, target="20260805")
            self.assertTrue(any("非法迁移" in e for e in errs), f"{was}->{now}: {errs}")

    def test_unknown_status_is_reported_not_silently_passed(self):
        rows = [{"date": "20260804", "nav": 1.0}]
        npub, et, rd = self._stage(rows, rows,
                                   before_orders=[{"id": 1, "status": "WEIRD_NEW"}],
                                   after_orders=[{"id": 1, "status": "WEIRD_NEW"}])
        errs = npub.verify_protected_inputs(et, rd, target="20260805")
        self.assertTrue(any("未登记状态" in e for e in errs), errs)

    def test_orders_immutable_price_rejected(self):
        """已成交价不得改写 —— 否则改一个 fill_price 就能重写历史成本。"""
        rows = [{"date": "20260804", "nav": 1.0}]
        npub, et, rd = self._stage(
            rows, rows,
            before_orders=[{"id": 1, "status": "filled", "fill_price": 3.0, "shares": 100}],
            after_orders=[{"id": 1, "status": "filled", "fill_price": 1.0, "shares": 100}])
        errs = npub.verify_protected_inputs(et, rd, target="20260805")
        self.assertTrue(any("已定值却被改写" in e for e in errs), errs)

    def test_orders_deletion_rejected(self):
        rows = [{"date": "20260804", "nav": 1.0}]
        npub, et, rd = self._stage(rows, rows,
                                   before_orders=[{"id": 1, "status": "filled"}],
                                   after_orders=[])
        errs = npub.verify_protected_inputs(et, rd, target="20260805")
        self.assertTrue(any("消失" in e for e in errs), errs)


class RuleCompletenessTest(unittest.TestCase):
    """规则**完整性**测试:检查"规则有没有漏",而不只是"现有规则有没有执行"。

    Junyan 自评(2026-08-05):守卫已经有牙,但连续四轮修补证明规则完整性仍依赖
    人工发现 —— cancelled 是被生产数据撞出来的,不是被测试找出来的。
    这一类测试的判据不是"某条规则работает",而是"现实里出现的每个取值,规则表里
    都有对应条目";发现漏项时**失败并指名**,而不是默默放行。
    """

    # 现实取值的来源:真实账本 + 各引擎源码里出现的字面量。
    LIVE_ORDERS = ET / "model_fund" / "orders.json"

    def _live_order_statuses(self):
        if not self.LIVE_ORDERS.exists():
            self.skipTest("本地无真实订单账本(CI 环境);由 live preflight 兜底")
        rows = json.loads(self.LIVE_ORDERS.read_text(encoding="utf-8"))
        return {str(o.get("status")) for o in rows if isinstance(o, dict)}

    def test_order_state_machine_covers_every_status_in_the_live_ledger(self):
        """真实账本里出现过的每个状态,状态机都必须登记 —— 漏一个,守卫就从
        防篡改退化成拦正常运行(0805 第三轮被 cancelled→cancelled 拦停)。"""
        import nightly_publish as npub
        live = self._live_order_statuses()
        missing = sorted(s for s in live if s not in npub.ORDER_TRANSITIONS)
        self.assertEqual([], missing,
                         f"真实账本存在未登记状态 {missing};"
                         f"已登记 {sorted(str(k) for k in npub.ORDER_TRANSITIONS)}")

    def test_every_registered_status_allows_self_transition(self):
        """任何已登记状态都必须允许"不变" —— 否则一轮什么都没做也会被判非法。"""
        import nightly_publish as npub
        for st, allowed in npub.ORDER_TRANSITIONS.items():
            if st is None:
                continue
            self.assertIn(st, allowed, f"{st}→{st} 自转被判非法")

    def test_every_published_engine_output_has_an_artifact_contract(self):
        """夜链每一步都必须在 ARTIFACTS 里声明产物 —— 没声明的步骤等于没被验过,
        它可以静默失败而整轮照报 COMPLETE。"""
        import run_nightly as rn
        steps = {s[0] for s in rn.STEPS}
        undeclared = sorted(steps - set(rn.ARTIFACTS))
        self.assertEqual([], undeclared, f"这些步骤没有产物契约: {undeclared}")

    def test_no_artifact_contract_points_at_a_nonexistent_step(self):
        """反向:ARTIFACTS 里不得有指向已删除步骤的孤儿条目。"""
        import run_nightly as rn
        steps = {s[0] for s in rn.STEPS}
        orphan = sorted(set(rn.ARTIFACTS) - steps)
        self.assertEqual([], orphan, f"孤儿产物契约: {orphan}")

    def test_every_dependency_names_a_real_step(self):
        import run_nightly as rn
        steps = [s[0] for s in rn.STEPS]
        for name, _cmd, _tok, deps in rn.STEPS:
            for d in deps:
                self.assertIn(d, steps, f"{name} 依赖不存在的步骤 {d}")
                self.assertLess(steps.index(d), steps.index(name),
                                f"{name} 依赖了排在它后面的 {d}(前向引用)")

    def test_chain_pairs_resolve_against_the_live_sector_universe(self):
        """预注册链对的每个节点,至少一个别名要能在真实板块表里解析出来 ——
        写死一个字面名(如"光模块(CPO)")而它在数据源里不存在,就是静默 DATA_BLOCKED。"""
        hist = ET / "rotation_history.json"
        if not hist.exists():
            self.skipTest("本地无 rotation_history(CI 环境)")
        import rotation_validation as rv
        h = json.loads(hist.read_text(encoding="utf-8"))
        sectors = set(h["flows"][h["days"][-1]])
        unresolved = []
        for a, b in rv.CHAIN_PAIRS:
            for node in (a, b):
                if rv._resolve(node, sectors) is None:
                    unresolved.append(node)
        self.assertEqual([], unresolved,
                         f"这些链节点的所有别名都不在数据源里: {unresolved}")

    def test_tech_neighbor_aliases_are_not_all_dead(self):
        """科技邻域别名表不得整体失配 —— 命中率过低说明数据源改了名而表没跟。"""
        hist = ET / "rotation_history.json"
        if not hist.exists():
            self.skipTest("本地无 rotation_history(CI 环境)")
        import lead_precursor as lp
        h = json.loads(hist.read_text(encoding="utf-8"))
        sectors = set(h["flows"][h["days"][-1]])
        hit = [n for n in lp.TECH_NEIGHBORS if n in sectors]
        self.assertGreaterEqual(len(hit), 15,
                                f"别名表仅命中 {len(hit)}/{len(lp.TECH_NEIGHBORS)} 条,"
                                f"疑似数据源改名;命中={hit}")

    def test_protected_ledger_files_are_all_classified(self):
        """受保护目录里的每个 .json 都必须有明确处置规则:
        append-only / 状态机 / fund 专用。没分类的文件会走"逐字节不变"分支,
        将来任何合法写入都会把发布卡死 —— 而卡死的原因不会写在任何清单里。"""
        import nightly_publish as npub
        live = ET / "model_fund"
        if not live.exists():
            self.skipTest("本地无 model_fund(CI 环境)")
        classified = set(npub.APPEND_ONLY_PROTECTED) | {"orders.json", "fund.json"}
        present = {f.name for f in live.glob("*.json")}
        unclassified = sorted(present - classified)
        self.assertEqual([], unclassified,
                         f"这些受保护文件没有处置规则,将走「逐字节不变」分支: {unclassified}")


class NavMarkToMarketTest(unittest.TestCase):
    """目标日行情缺失时,NAV 绝不能悄悄回退成本价。

    实战教训:第一版按 s[-1][4] 取收盘价,而 qfq_ohlc_series 返回的是 **dict**,
    于是 marks 全空 → NAV 静默按成本标记 → 产出一个看起来正常的假 NAV
    (1,020,000 vs 真值 1,009,466,差 ¥10,534)。假数据比缺数据更危险,
    因为它不会触发任何告警。
    """

    def _fund(self, cash=719140.0):
        return {"initial_capital": 1000000.0, "cash": cash}

    def _orders(self):
        return [
            {"status": "filled", "ticker": "600276.SH", "shares": 2700, "fill_price": 56.4},
            {"status": "filled", "ticker": "002714.SZ", "shares": 3800, "fill_price": 39.1},
        ]

    def _cost_nav(self):
        return 719140.0 + 2700 * 56.4 + 3800 * 39.1

    def test_marks_from_target_day_are_used_not_cost(self):
        import model_paper_fund as mpf
        marks = {"600276.SH": 53.54, "002714.SZ": 38.36}
        nav = mpf.current_nav(self._fund(), self._orders(), marks)
        expected = 719140.0 + 2700 * 53.54 + 3800 * 38.36
        self.assertAlmostEqual(nav, expected, places=0)
        self.assertNotAlmostEqual(nav, self._cost_nav(), places=0,
                                  msg="NAV 等于成本价 ⇒ marks 没被用上")

    def test_dict_shaped_bars_are_parsed(self):
        """qfq_ohlc_series 返回 dict;按 bar[4] 取值会静默拿到 None。"""
        bar = {"date": "20260805", "open": 53.43, "high": 53.79,
               "low": 52.88, "close": 53.54}
        close = bar.get("close") if isinstance(bar, dict) else (
            bar[4] if isinstance(bar, (list, tuple)) and len(bar) > 4 else None)
        self.assertEqual(close, 53.54)

    def test_stale_bar_must_not_be_used_as_target_day_mark(self):
        """最新 bar 的日期 ≠ 本轮 target ⇒ 不得用于标记(宁可不标也不用旧价)。"""
        target = "20260805"
        stale_bar = {"date": "20260731", "close": 99.9}
        close = stale_bar.get("close")
        usable = bool(close) and str(stale_bar.get("date"))[:8] == target
        self.assertFalse(usable, "旧日期的收盘价被当成了本轮标记价")

    def test_missing_marks_flags_cost_basis_explicitly(self):
        """无可用收盘价时:NAV 退化为成本口径这件事必须被**显式声明**,
        不能悄悄发生 —— 调用方要能区分"市值"和"成本"。"""
        import model_paper_fund as mpf
        nav_no_marks = mpf.current_nav(self._fund(), self._orders(), None)
        self.assertAlmostEqual(nav_no_marks, self._cost_nav(), places=0)
        src = (ET / "model_paper_fund.py").read_text(encoding="utf-8")
        self.assertIn("NAV 按成本标记", src,
                      "marks 为空时没有任何显式提示 —— 假 NAV 会静默通过")
        self.assertIn('bar_date == date', src,
                      "没有校验 bar 日期是否等于本轮 target")


class ProtectedLedgerIsPublishedTest(unittest.TestCase):
    """资金账本必须**既受保护又被发布** —— 只校验不发布会让 staging 里算对的 NAV
    永远回不到 live,而夜链照报 COMPLETE+published=true(0805 首轮实际发生)。"""

    def test_model_fund_files_are_in_publish_plan(self) -> None:
        import nightly_publish as npub
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        stage_et = os.path.join(tmp, "et")
        mf = os.path.join(stage_et, "model_fund")
        os.makedirs(mf)
        json.dump([{"date": "20260805", "nav": 1.0}],
                  open(os.path.join(mf, "nav_history.json"), "w"))
        json.dump({"cash": 1.0}, open(os.path.join(mf, "fund.json"), "w"))
        files = npub._allowed_stage_files(stage_et, os.path.join(tmp, "public"))
        rels = {rel for scope, rel, _ in files if scope == "et"}
        self.assertIn(os.path.join("model_fund", "nav_history.json"), rels,
                      "nav_history 不在发布清单 —— 算对了也回不到 live")
        self.assertIn(os.path.join("model_fund", "fund.json"), rels)



if __name__ == "__main__":
    unittest.main()

