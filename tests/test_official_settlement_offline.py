#!/usr/bin/env python3
"""Offline replay of the 2026-09-07 mixed settlement dates; no live inputs."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))
import run_official_sample as official
import run_nightly as nightly
import nightly_publish as publication

TODAY = "20260907"
PRIOR = "20260904"


class SettlementTest(unittest.TestCase):
    def run_entry(self, root, settle_after=2, error=None, regress=False):
        rounds = []
        sleeps = []
        output = io.StringIO()
        append = Mock(return_value=(0, 0))

        def index(_token, code):
            if code == official.INDICES[0][0]:
                rounds.append(len(rounds) + 1)
                self.assertFalse((root / "run_target.json").exists())
                self.assertFalse((root / "samples").exists())
            return {"trade_date": PRIOR if regress and len(rounds) > 1 else TODAY,
                    "pct_chg": 0.1}

        def fund(code, **_kwargs):
            if error:
                raise error
            date = TODAY
            if regress and len(rounds) > 1:
                date = PRIOR
            elif len(rounds) < settle_after and code == "300502.SZ":
                date = PRIOR
            return {"date": date, "main": 1, "super_large": 1, "small": 1}

        def daily(code, **_kwargs):
            return {"date": PRIOR if regress and len(rounds) > 1 else TODAY,
                    "close": 10, "pct_chg": 0.1, "ohlc_bars": []}

        snap = {"market_gate": {"state": "FIXTURE", "one_line": "WORKFLOW_DEBUG"},
                "portfolio_gate": {"portfolio_posture": "FIXTURE", "single_beta_exposure": False},
                "ticker_gates": [], "sample_purpose": "WORKFLOW_DEBUG", "no_trade_flag": True}
        caught = None
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(official, "HERE", str(root)))
            stack.enter_context(patch.object(official, "_index_chg", side_effect=index))
            stack.enter_context(patch.object(official, "_market_main_flow", return_value=None))
            stack.enter_context(patch.object(official, "real_holdings", return_value=[]))
            stack.enter_context(patch.object(official.fs, "get_stock_fund", side_effect=fund))
            stack.enter_context(patch.object(official.fs, "tushare_daily", side_effect=daily))
            stack.enter_context(patch.object(official.et, "build_snapshot", return_value=snap))
            stack.enter_context(patch.object(official.et, "make_paper_signals", return_value=[]))
            stack.enter_context(patch.object(official, "append_log", append))
            stack.enter_context(patch.object(official.time, "sleep", side_effect=sleeps.append))
            stack.enter_context(patch.dict(os.environ, {"TUSHARE_TOKEN": "offline-fixture", "AR_RUN_ID": "DEBUG_NEW"}, clear=True))
            stack.enter_context(patch.object(sys, "argv", ["run_official_sample.py"]))
            stack.enter_context(contextlib.redirect_stdout(output))
            try:
                official.main()
            except (SystemExit, Exception) as exc:
                caught = exc
        return {"rounds": len(rounds), "sleeps": sleeps, "error": caught,
                "output": output.getvalue(), "append": append}

    def test_pending_then_settled_main_retries_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self.run_entry(root)
            self.assertIsNone(out["error"], str(out["error"]))
            self.assertEqual(out["rounds"], 2)
            self.assertEqual([s for s in out["sleeps"] if s >= 1], [30])
            self.assertEqual(json.loads((root / "run_target.json").read_text())["trade_date"], TODAY)
            self.assertTrue((root / "samples" / (TODAY + ".json")).is_file())
            out["append"].assert_called_once()

    def test_persistent_mismatch_is_bounded_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self.run_entry(root, settle_after=99)
            self.assertIsInstance(out["error"], SystemExit)
            self.assertIn("DATA_BLOCKED", str(out["error"]))
            self.assertEqual(out["rounds"], 3)
            self.assertEqual([s for s in out["sleeps"] if s >= 1], [30, 30])
            self.assertEqual(list(root.iterdir()), [])
            out["append"].assert_not_called()

    def test_mismatch_diagnostic_identifies_source_and_ticker(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.run_entry(Path(tmp), settle_after=99)
            diagnostic = str(out["error"])
            self.assertIn('"moneyflow_dc"', diagnostic)
            self.assertIn('"300502.SZ": "20260904"', diagnostic)
            self.assertIn('"300475.SZ": "20260907"', diagnostic)
            self.assertNotIn("offline-fixture", diagnostic + out["output"])

    def test_generic_api_or_schema_error_is_not_settlement_retry(self):
        for error in (RuntimeError("quota exhausted"), ValueError("bad JSON"),
                      SystemExit("DATA_BLOCKED: unrelated failure")):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as tmp:
                out = self.run_entry(Path(tmp), error=error)
                self.assertIs(out["error"], error)
                self.assertEqual(out["rounds"], 1)
                self.assertEqual([s for s in out["sleeps"] if s >= 1], [])
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_retry_cannot_regress_to_an_older_consistent_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.run_entry(Path(tmp), regress=True)
            self.assertIsInstance(out["error"], SystemExit)
            self.assertEqual(out["rounds"], 3)
            self.assertEqual(list(Path(tmp).iterdir()), [])
            out["append"].assert_not_called()

    def test_existing_consensus_guard_remains_load_bearing(self):
        with self.assertRaises(SystemExit):
            official.assert_date_consistent({PRIOR, TODAY}, {TODAY}, [TODAY] * 3)
        with self.assertRaises(SystemExit):
            official.assert_date_consistent({TODAY}, {TODAY}, [None])
        self.assertEqual(official.assert_date_consistent({TODAY}, {TODAY}, [TODAY]), TODAY)

    def test_pending_entry_keeps_nightly_incomplete_with_verify_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def runner(_cmd):
                out = self.run_entry(root, settle_after=99)
                return 1, out["output"] + str(out["error"])
            steps = [("official_sample", ["python3", "run_official_sample.py"], False, []),
                     ("child", ["python3", "child.py"], False, ["official_sample"])]
            with patch.object(nightly, "STEPS", steps):
                result = nightly.run_steps(runner=runner, require_live=False, verify=True,
                                           base=str(root), run_id="DEBUG_NEW")
            self.assertEqual(result["report"], "INCOMPLETE")
            self.assertTrue(result["steps"][0]["blocks_publication"])
            self.assertEqual(result["steps"][1]["status"], "SKIPPED_STALE_INPUT")
            self.assertFalse((root / "current_run.json").exists())


class PublicationRecoveryTest(unittest.TestCase):
    def layout(self, root):
        et = root / "experiments" / "execution_tracker"
        public = root / "public" / "data" / "v2"
        for path in (et, public, root / "experiments" / "research_funnel",
                     root / "experiments" / "macro_os"):
            path.mkdir(parents=True)
        old = "DEBUG_MISSING"
        missing = et / "runs" / old / "manifest.json"
        state_path = et / "publication_state.json"
        publication.atomic_json(str(state_path), {
            "schema": "nightly_publication_state/v2", "status": "COMMITTED",
            "run_id": old, "target_trade_date": "20260828", "manifest": str(missing),
            "artifact_count": 0})
        pointer = {"schema": "nightly_current_run/v2", "run_id": old,
                   "target_trade_date": "20260828", "manifest_sha256": "a" * 64,
                   "manifest_path": "runs/" + old + "/manifest.json", "artifacts": {}}
        for path in (et / "current_run.json", public / "current_run.json"):
            publication.atomic_json(str(path), pointer)
        publication.rebaseline_lost_manifest(
            str(state_path), str(et), str(root), reason="WORKFLOW_DEBUG fixture only",
            approved_by="Junyan", approval_ref="session:synthetic-regression",
            approval_verbatim=publication.required_rebaseline_approval(old),
            now="2026-09-04T18:00:00.000000")
        return et, public, state_path, missing

    def test_fresh_publish_replaces_pointers_without_reinventing_missing_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "repo"
            et, public, state, missing = self.layout(root)
            ledger = et / publication.REBASELINE_LEDGER_NAME
            ledger_before = ledger.read_bytes()
            recovered = publication.recover_interrupted_publish(str(state), str(et), str(root))
            self.assertEqual(recovered["status"], "SUPERSEDED_BY_OPERATOR")
            run_dir = et / "runs" / "DEBUG_NEW"
            stage = publication.prepare_stage(str(et), str(root), str(run_dir))
            publication.atomic_json(os.path.join(stage["public"], "meta.json"),
                                    {"run_id": "DEBUG_NEW", "sample_purpose": "WORKFLOW_DEBUG"})
            publication.publish_stage("DEBUG_NEW", TODAY, stage, str(et), str(root), str(run_dir), str(state))
            self.assertEqual(publication.recover_interrupted_publish(
                str(state), str(et), str(root))["status"], "COMMITTED_VERIFIED")
            self.assertEqual((et / "current_run.json").read_bytes(), (public / "current_run.json").read_bytes())
            self.assertEqual((run_dir / "manifest.json").read_bytes(),
                             (public / "runs" / "DEBUG_NEW" / "manifest.json").read_bytes())
            self.assertFalse(missing.exists())
            self.assertFalse((public / "runs" / "DEBUG_MISSING" / "manifest.json").exists())
            self.assertEqual(ledger.read_bytes(), ledger_before)

    def test_failed_new_publication_preserves_supersession_and_old_pointers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "repo"
            et, public, state, missing = self.layout(root)
            before = (public / "current_run.json").read_bytes()
            ledger = (et / publication.REBASELINE_LEDGER_NAME).read_bytes()
            run_dir = et / "runs" / "DEBUG_FAILED"
            stage = publication.prepare_stage(str(et), str(root), str(run_dir))
            publication.atomic_json(os.path.join(stage["public"], "meta.json"), {"sample_purpose": "WORKFLOW_DEBUG"})
            with self.assertRaises(RuntimeError):
                publication.publish_stage("DEBUG_FAILED", TODAY, stage, str(et), str(root),
                                          str(run_dir), str(state), fail_phase="after_public_marker")
            self.assertEqual((public / "current_run.json").read_bytes(), before)
            self.assertEqual((et / "current_run.json").read_bytes(), before)
            self.assertEqual((et / publication.REBASELINE_LEDGER_NAME).read_bytes(), ledger)
            self.assertFalse(missing.exists())
            self.assertFalse((public / "runs" / "DEBUG_FAILED" / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
